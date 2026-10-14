"""Secure local profile migration and revision merging; no network/accounts."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'main'))
from racechat_store import DEFAULTS, Store
import racechat_profile_sync as sync
from racechat_sync_security import current_sid as real_current_sid, verify_permissions


@unittest.skipUnless(os.name == 'nt', 'Windows DPAPI/NTFS')
class ProfileSyncTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.one = Path(self.temp.name) / 'alpha'
        self.two = Path(self.temp.name) / 'beta'
        self.one.mkdir(); self.two.mkdir()
        self.sid_one, self.sid_two = real_current_sid(), 'S-1-5-21-123456789-234567890-345678901-9999'
        self.active = self.sid_one
        self.patches = [patch.object(sync, 'current_sid', side_effect=lambda: self.active),
                        patch.object(sync, 'account_store_path', side_effect=lambda sid: self.one if sid == self.sid_one else self.two),
                        patch.object(sync, 'ensure_logon_hook'),
                        patch.object(sync, 'account_sid', side_effect=lambda name: self.sid_one if name == 'alpha' else self.sid_two)]
        for item in self.patches:
            item.start()
        Store(self.one).save(DEFAULTS, {})
        Store(self.two).save({**DEFAULTS, 'twitch_channel': 'configured', 'youtube_video': 'abcdefghijk'},
                             {'discord_token': 'fake-discord', 'youtube_token': 'fake-youtube',
                              'youtube_refresh_token': 'fake-refresh'})
        self.originals = {name: (self.two / name).read_bytes() for name in ('settings.json', 'secrets.dpapi')}
        sync.install([('alpha', self.one), ('beta', self.two)])

    def tearDown(self):
        for item in reversed(self.patches):
            item.stop()
        self.temp.cleanup()

    def migrate(self):
        self.active = self.sid_two
        sync.synchronize(self.two)
        self.active = self.sid_one
        return sync.synchronize(self.one)

    def test_pending_then_original_user_migrates_and_both_local_stores_import(self):
        with patch('racechat_service.request') as network:
            first = sync.synchronize(self.one)
            self.assertTrue(first['migration_pending'])
            self.assertFalse(any(first['credentials'].values()))
            self.assertEqual(first['config']['twitch_channel'], 'configured')
            for name, data in self.originals.items():
                self.assertEqual((self.two / name).read_bytes(), data)
                self.assertEqual((self.two / 'profile-sync-originals' / name).read_bytes(), data)
            second = self.migrate()
            self.assertFalse(second['migration_pending'])
            self.assertEqual(second['credentials']['youtube_token'], 'fake-youtube')
            self.assertEqual(Store(self.one).secrets()['discord_token'], 'fake-discord')
            self.active = self.sid_two
            self.assertEqual(Store(self.two).secrets(), Store(self.two)._secrets_local())
            network.assert_not_called()
        for file in Path(self.temp.name).rglob('*'):
            if file.is_file():
                self.assertNotIn(b'fake-discord', file.read_bytes())
                self.assertNotIn(b'fake-refresh', file.read_bytes())
        for path in (self.one, self.two):
            verify_permissions(path / sync.TRANSFER, [self.sid_one, self.sid_two], directory=True)
            verify_permissions(path / sync.TRANSFER / sync.SNAPSHOT, [self.sid_one, self.sid_two])

    def test_sync_never_decrypts_the_other_user_legacy_blob(self):
        original = Store._secrets_local
        def read(store):
            if store.path == self.two:
                raise AssertionError('Attempted to decrypt another user’s legacy blob')
            return original(store)
        with patch.object(Store, '_secrets_local', read):
            self.assertTrue(sync.synchronize(self.one)['migration_pending'])

    def test_independent_edits_refresh_and_stale_snapshot_do_not_erase_other_fields(self):
        self.migrate()
        store_one = Store(self.one)
        old_config, old_credentials = store_one.load(), store_one.secrets()
        self.active = self.sid_two
        Store(self.two).update_tokens({'youtube_token': 'rotated', 'youtube_refresh_token': 'rotated-refresh'})
        Store(self.two).update_settings({'youtube_video': 'new-video12'})
        self.active = self.sid_one
        store_one.save({**old_config, 'twitch_channel': 'edited-channel'}, old_credentials)
        result = sync.synchronize(self.one)
        self.assertEqual(result['config']['youtube_video'], 'new-video12')
        self.assertEqual(result['config']['twitch_channel'], 'edited-channel')
        self.assertEqual(result['credentials']['youtube_token'], 'rotated')
        self.assertEqual(result['credentials']['discord_token'], 'fake-discord')
        self.active = self.sid_two
        self.assertEqual(Store(self.two).load(), result['config'])
        self.assertEqual(Store(self.two).secrets(), result['credentials'])

    def test_explicit_clear_propagates_without_reimporting_old_backup(self):
        self.migrate()
        store = Store(self.one)
        store.save(store.load(), {})
        self.assertFalse(sync.synchronize(self.one)['migration_pending'])
        self.active = self.sid_two
        self.assertFalse(any(Store(self.two).secrets().values()))
        self.assertEqual((self.two / 'profile-sync-originals' / 'secrets.dpapi').read_bytes(), self.originals['secrets.dpapi'])

    def test_concurrent_updates_preserve_each_platform_token(self):
        self.migrate()
        barrier = threading.Barrier(2)
        errors = []
        def change(values):
            try:
                barrier.wait()
                Store(self.one).update_tokens(values)
            except Exception as exc:
                errors.append(type(exc).__name__)
        threads = [threading.Thread(target=change, args=(values,))
                   for values in ({'youtube_token': 'concurrent-youtube'}, {'discord_token': 'concurrent-discord'})]
        for thread in threads: thread.start()
        for thread in threads: thread.join(15)
        self.assertEqual(errors, [])
        result = Store(self.one).secrets()
        self.assertEqual(result['youtube_token'], 'concurrent-youtube')
        self.assertEqual(result['discord_token'], 'concurrent-discord')

    def test_corrupt_transfer_fails_without_overwriting_local_secrets(self):
        self.migrate()
        before = (self.one / 'secrets.dpapi').read_bytes()
        (self.two / sync.TRANSFER / sync.SNAPSHOT).write_bytes(b'corrupted')
        with self.assertRaises(RuntimeError):
            sync.synchronize(self.one)
        self.assertEqual((self.one / 'secrets.dpapi').read_bytes(), before)

    def test_broadened_acl_refuses_transfer(self):
        directory = self.two / sync.TRANSFER
        command = ['icacls', str(directory), '/grant', '*S-1-1-0:(OI)(CI)R', '/Q']
        subprocess.run(command, check=True, capture_output=True, creationflags=subprocess.CREATE_NO_WINDOW)
        with self.assertRaises(RuntimeError):
            sync.synchronize(self.one)

    def test_profile_redirection_is_rejected(self):
        marker = self.one / sync.MARKER
        policy = json.loads(marker.read_text())
        policy['members'][1]['path'] = str(self.one / 'redirected')
        marker.write_text(json.dumps(policy))
        with self.assertRaises(RuntimeError):
            sync.synchronize(self.one)

    def test_dry_run_does_not_change_any_file(self):
        def hashes():
            return {str(p): hashlib.sha256(p.read_bytes()).hexdigest()
                    for p in Path(self.temp.name).rglob('*') if p.is_file()}
        before = hashes()
        self.assertTrue(sync.synchronize(self.one, dry_run=True)['dry_run'])
        self.assertEqual(hashes(), before)


if __name__ == '__main__':
    unittest.main()

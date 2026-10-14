"""Two local stores, encrypted transfer snapshots, and per-user DPAPI imports."""
from contextlib import contextmanager
import json
import msvcrt
import os
from pathlib import Path
import time
import uuid
import re
import subprocess
import sys
import winreg

from racechat_store import DEFAULTS, STORED_SECRET_NAMES, Store, protect
from racechat_sync_security import account_sid, current_sid, secure_directory, verify_permissions

MARKER = 'profile-sync.json'
TRANSFER = 'profile-sync-transfer'
SNAPSHOT = 'snapshot.dpapi'
STATE = 'profile-sync-state.dpapi'


def account_store_path(sid):
    key = r'SOFTWARE\Microsoft\Windows NT\CurrentVersion\ProfileList' + '\\' + sid
    with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, key) as profile:
        root = os.path.expandvars(winreg.QueryValueEx(profile, 'ProfileImagePath')[0])
    return Path(root) / 'AppData/Local/OverlayRaceChat'


def atomic_bytes(path, data, sids=None):
    path = Path(path)
    if path.exists() and sids:
        verify_permissions(path, sids)
    temp = path.with_name('.' + uuid.uuid4().hex + '.tmp')
    try:
        with temp.open('xb') as stream:
            if sids:
                verify_permissions(temp, sids)
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        temp.replace(path)
    finally:
        temp.unlink(missing_ok=True)


def read_encrypted(path, sids=None):
    path = Path(path)
    if not path.exists():
        return None
    if sids:
        verify_permissions(path, sids)
    if path.stat().st_size > 1024 * 1024:
        raise RuntimeError('RaceChat synchronization snapshot is invalid.')
    return json.loads(protect(path.read_bytes(), decrypt=True))


def profile_config(path):
    config = json.loads((Path(path) / MARKER).read_text(encoding='utf-8'))
    members = config.get('members', [])
    expected = {m.get('sid') for m in members}
    if (config.get('version') != 1 or len(members) != 2 or len(expected) != 2
            or any(not isinstance(sid, str) or not re.fullmatch(r'S-1-(?:5-21|12-1)-[0-9-]+', sid) for sid in expected)):
        raise RuntimeError('RaceChat synchronization requires two distinct authorized Windows account SIDs.')
    if any(Path(m['path']).resolve() != account_store_path(m['sid']).resolve() for m in members):
        raise RuntimeError('RaceChat synchronization cannot redirect Windows profile folders.')
    if current_sid() not in expected:
        raise RuntimeError('This Windows account is not authorized for RaceChat synchronization.')
    matching = [m for m in members if Path(m['path']).resolve() == Path(path).resolve()]
    if len(matching) != 1 or matching[0]['sid'] != current_sid():
        raise RuntimeError('RaceChat synchronization must run in the store owner’s Windows profile.')
    return config


@contextmanager
def sync_lock(members):
    sids = [m['sid'] for m in members]
    for member in members:
        secure_directory(Path(member['path']) / TRANSFER, sids)
    lock_path = Path(members[0]['path']) / TRANSFER / 'sync.lock'
    if lock_path.exists():
        verify_permissions(lock_path, sids)
    with lock_path.open('a+b') as stream:
        verify_permissions(lock_path, sids)
        if stream.tell() == 0:
            stream.write(b'\0'); stream.flush()
        deadline = time.monotonic() + 10
        while True:
            try:
                stream.seek(0)
                msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
                break
            except OSError:
                if time.monotonic() >= deadline:
                    raise RuntimeError('RaceChat synchronization is busy; try again.') from None
                time.sleep(.05)
        try:
            yield
        finally:
            stream.seek(0)
            msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)


def merge_snapshots(snapshots, allowed_sids):
    merged = {'version': 1, 'config': {}, 'credentials': {}}
    for snapshot in snapshots:
        if snapshot is None:
            continue
        if snapshot.get('version') != 1:
            raise RuntimeError('RaceChat synchronization snapshot is invalid.')
        for section, allowed in (('config', DEFAULTS), ('credentials', STORED_SECRET_NAMES)):
            for key, record in snapshot.get(section, {}).items():
                if key not in allowed:
                    raise RuntimeError('RaceChat synchronization snapshot contains an unknown field.')
                revision = record.get('revision', [])
                if (len(revision) != 2 or not isinstance(revision[0], int) or revision[0] < 0
                        or revision[1] not in allowed_sids or 'value' not in record):
                    raise RuntimeError('RaceChat synchronization snapshot is invalid.')
                if section == 'credentials' and not isinstance(record['value'], str):
                    raise RuntimeError('RaceChat synchronization credential is invalid.')
                existing = merged[section].get(key)
                if existing is None or tuple(revision) > tuple(existing['revision']):
                    merged[section][key] = record
    return merged


def initial_records(config, credentials, config_time, credentials_time, sid):
    # Empty/default unconfigured profiles must not erase another profile’s accounts.
    return {'version': 1,
            'config': {key: {'value': value, 'revision': [config_time, sid]}
                       for key, value in config.items() if key in DEFAULTS and value != DEFAULTS[key] and value != ''},
            'credentials': {key: {'value': value, 'revision': [credentials_time, sid]}
                            for key, value in credentials.items() if key in STORED_SECRET_NAMES and value}}


def synchronize(path, settings=None, tokens=None, replacement=None, dry_run=False):
    path = Path(path)
    policy = profile_config(path)
    members, sid = policy['members'], current_sid()
    if dry_run:
        return {'configured': True, 'profiles': len(members), 'dry_run': True}
    with sync_lock(members):
        return synchronize_locked(path, members, sid, settings, tokens, replacement)


def synchronize_locked(path, members, sid, settings, tokens, replacement):
    sids = [m['sid'] for m in members]
    snapshots = [read_encrypted(Path(m['path']) / TRANSFER / SNAPSHOT, sids) for m in members]
    local = Store(path)
    config = local._load_local()
    raw_credentials = local._secrets_local()
    credentials = {k: raw_credentials.get(k, '') for k in STORED_SECRET_NAMES}
    state = read_encrypted(path / STATE)
    if state is None:
        for member in members:
            profile = Path(member['path'])
            file = profile / 'settings.json'
            if file.exists():
                # Only the current Windows account decrypts its own legacy credentials.
                legacy = Store(profile)._load_local()
                secret_file = profile / 'secrets.dpapi'
                snapshots.append(initial_records(legacy, credentials if member['sid'] == sid else {},
                                  file.stat().st_mtime_ns,
                                  secret_file.stat().st_mtime_ns if secret_file.exists() else 0, member['sid']))
    merged = merge_snapshots(snapshots, sids)
    if state is not None:
        # Detect edits by older app/setup versions without treating a fresh empty
        # profile as a deletion. Revisions are per field, including explicit clears.
        for section, values in (('config', config), ('credentials', credentials)):
            old = state[section]
            for key in DEFAULTS if section == 'config' else STORED_SECRET_NAMES:
                value = values.get(key, DEFAULTS[key] if section == 'config' else '')
                if value != old.get(key, DEFAULTS[key] if section == 'config' else ''):
                    merged[section][key] = {'value': value, 'revision': [next_revision(merged), sid]}
    imported_config = {**DEFAULTS, **{k: v['value'] for k, v in merged['config'].items()}}
    imported_credentials = {k: merged['credentials'].get(k, {}).get('value', '') for k in STORED_SECRET_NAMES}
    changes = [('config', settings or {}), ('credentials', tokens or {})]
    if replacement is not None:
        desired_config, desired_credentials = replacement
        # Compare against the local baseline the caller edited, rather than blindly
        # publishing a stale whole snapshot over newer changes in the other profile.
        changes = [('config', {k: desired_config.get(k, v) for k, v in DEFAULTS.items()
                               if desired_config.get(k, v) != config.get(k, v)}),
                   ('credentials', {k: desired_credentials.get(k, '') for k in STORED_SECRET_NAMES
                                    if desired_credentials.get(k, '') != credentials.get(k, '')})]
    for section, values in changes:
        allowed = DEFAULTS if section == 'config' else STORED_SECRET_NAMES
        for key, value in values.items():
            if key in allowed:
                merged[section][key] = {'value': value, 'revision': [next_revision(merged), sid]}
                (imported_config if section == 'config' else imported_credentials)[key] = value
    encrypted = None
    for member, previous in zip(members, snapshots):
        if previous != merged:
            if encrypted is None:
                encrypted = protect(json.dumps(merged).encode(), machine=True)
            atomic_bytes(Path(member['path']) / TRANSFER / SNAPSHOT, encrypted, sids)
    if imported_config != config or imported_credentials != credentials:
        local._save(imported_config, imported_credentials)
    new_state = {'config': imported_config, 'credentials': imported_credentials}
    if state != new_state:
        atomic_bytes(path / STATE, protect(json.dumps(new_state).encode()))
    # Old per-user blobs remain backed up and are never decrypted as another user.
    pending = not merged['credentials'] and any(
        m['sid'] != sid and (Path(m['path']) / 'secrets.dpapi').exists() for m in members)
    return {**new_state, 'configured': True, 'migration_pending': pending}


def ensure_logon_hook():
    """An already opted-in store uses this same app, in its owner's session."""
    if not getattr(sys, 'frozen', False):
        return
    startup = Path(os.environ['APPDATA']) / 'Microsoft/Windows/Start Menu/Programs/Startup'
    startup.mkdir(parents=True, exist_ok=True)
    text = '@echo off\r\n' + subprocess.list2cmdline([sys.executable, '--racechat-sync']).replace('%', '%%') + '\r\n'
    target = startup / 'RaceChatProfileSync.cmd'
    if not target.exists() or target.read_bytes() != text.encode():
        atomic_bytes(target, text.encode())


def next_revision(snapshot):
    maximum = max((record['revision'][0] for section in ('config', 'credentials')
                   for record in snapshot[section].values()), default=0)
    return max(time.time_ns(), maximum + 1)


def install(paths):
    """Install opt-in markers and protected transfer folders, preserving originals."""
    members = [{'sid': account_sid(name), 'path': str(Path(path).resolve())}
               for name, path in paths]
    sids = [m['sid'] for m in members]
    policy = json.dumps({'version': 1, 'members': members}, indent=2).encode()
    for member in members:
        path = Path(member['path'])
        if not path.is_dir():
            raise RuntimeError('The existing RaceChat profile folder is missing.')
        secure_directory(path / TRANSFER, sids)
        backup = path / 'profile-sync-originals'
        secure_directory(backup, sids)
        for name in ('settings.json', 'secrets.dpapi'):
            original, saved = path / name, backup / name
            if original.exists() and not saved.exists():
                # Use new inherited ACLs, not the source file’s broader ACL.
                atomic_bytes(saved, original.read_bytes(), sids)
        marker = path / MARKER
        if marker.exists() and marker.read_bytes() != policy:
            raise RuntimeError('A different RaceChat synchronization policy already exists.')
        if not marker.exists():
            atomic_bytes(marker, policy)
    return members


def main(dry_run=False):
    store = Store()
    result = synchronize(store.path, dry_run=dry_run)
    if dry_run:
        return 0
    ensure_logon_hook()
    # The windowed executable reports only non-secret status to its local profile.
    status = {key: result[key] for key in ('configured', 'migration_pending', 'dry_run') if key in result}
    atomic_bytes(store.path / 'profile-sync-status.json', json.dumps(status).encode())
    return 0

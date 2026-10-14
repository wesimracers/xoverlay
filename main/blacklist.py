"""Persistent iRacing UserID marks for the Relative widget.

blacklist.json format: {"ids": [123456, 789012]}. Users may edit the list
directly; car numbers and names are intentionally not used as identities.
"""

import json
import os
from pathlib import Path


def normalize_user_id(value):
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        number = value
    elif isinstance(value, str) and value.strip().isdecimal():
        number = int(value.strip())
    else:
        return None
    return number if 0 < number <= 2**63 - 1 else None


class BlacklistStore:
    def __init__(self, path):
        self.path = Path(path)
        self._cached_signature = None
        self._cached_ids = set()
        self.last_error = ""

    def _read(self):
        if not self.path.exists():
            return {"ids": []}
        raw = json.loads(self.path.read_text(encoding="utf-8-sig"))
        if not isinstance(raw, dict) or not isinstance(raw.get("ids"), list):
            raise ValueError("blacklist.json must contain an object with an 'ids' list.")
        ids = raw["ids"]
        if any(normalize_user_id(value) is None for value in ids):
            raise ValueError("blacklist.json contains an invalid iRacing ID.")
        return raw

    def read_ids(self):
        return {normalize_user_id(value) for value in self._read()["ids"]}

    def current_ids(self):
        """Reload manual edits without interrupting Relative on a bad file."""
        try:
            stat = self.path.stat()
            signature = (stat.st_mtime_ns, stat.st_size)
        except FileNotFoundError:
            signature = None
        if signature == self._cached_signature and not self.last_error:
            return set(self._cached_ids)
        try:
            ids = self.read_ids()
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            self.last_error = str(exc)
            return set(self._cached_ids)
        self._cached_signature = signature
        self._cached_ids = ids
        self.last_error = ""
        return set(ids)

    def save_selection(self, visible_ids, selected_ids, manual_id=None):
        """Apply this table's checkboxes, preserving IDs from other events."""
        visible = {normalize_user_id(value) for value in visible_ids}
        selected = {normalize_user_id(value) for value in selected_ids}
        if None in visible or None in selected or not selected <= visible:
            raise ValueError("Selection contains an invalid iRacing ID.")
        added = None
        if manual_id is not None and str(manual_id).strip():
            added = normalize_user_id(manual_id)
            if added is None:
                raise ValueError("Enter a positive numeric iRacing ID.")
        raw = self._read()  # refuse to overwrite malformed manual edits
        all_ids = {normalize_user_id(value) for value in raw["ids"]}
        all_ids.difference_update(visible)
        all_ids.update(selected)
        if added is not None:
            all_ids.add(added)
        raw["ids"] = sorted(all_ids)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temp = self.path.with_name(self.path.name + ".tmp")
        try:
            with temp.open("w", encoding="utf-8") as handle:
                json.dump(raw, handle, ensure_ascii=False, indent=2)
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temp, self.path)
        finally:
            if temp.exists():
                temp.unlink()
        self._cached_signature = None
        self._cached_ids = all_ids
        self.last_error = ""
        return set(all_ids)

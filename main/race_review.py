"""Capture race entrants until checkered, transition, or disconnect."""

import json
import os
import time
from pathlib import Path

from blacklist import normalize_user_id


def race_key(signature):
    if not isinstance(signature, (list, tuple)) or len(signature) < 6:
        return None
    session_id, sub_id, uid, session_num, session_type, _track = signature[:6]
    if str(session_type or "").strip().casefold() != "race":
        return None
    for label, value in (("sub", sub_id), ("session", session_id)):
        if value not in (None, "", 0, "0") and session_num is not None:
            return f"{label}:{value}|num:{session_num}"
    if uid not in (None, "", 0, "0"):
        return f"uid:{uid}"
    return None


def participants_from_drivers(drivers):
    result = []
    for driver in drivers if isinstance(drivers, list) else []:
        if not isinstance(driver, dict) or driver.get("CarIsPaceCar") or driver.get("CarIsSpectator"):
            continue
        try:
            car_idx = int(driver.get("CarIdx", -1))
        except (TypeError, ValueError):
            continue
        if car_idx < 0:
            continue
        user_id = normalize_user_id(driver.get("UserID"))
        name = str(driver.get("UserName") or "").strip() or "Unnamed driver"
        number = str(driver.get("CarNumber") or "").strip() or "—"
        result.append({"id": user_id, "car_idx": car_idx, "number": number, "name": name})
    return result


class RaceMonitor:
    def __init__(self, path, disconnect_grace_s=3.0):
        self.path = Path(path)
        self.disconnect_grace_s = disconnect_grace_s
        self.active = None
        self.pending = []
        self.recent = None
        self.handled = []
        self.disconnected_since = None
        self.last_error = ""
        self._load()

    def _load(self):
        if not self.path.exists():
            self.last_error = ""  # 261001_CURSOR
            return
        try:
            data = json.loads(self.path.read_text(encoding="utf-8-sig"))
            if not isinstance(data, dict):
                raise ValueError("Invalid race review state.")
            self.active = data.get("active") if isinstance(data.get("active"), dict) else None
            self.pending = data.get("pending") if isinstance(data.get("pending"), list) else []
            self.recent = data.get("recent") if isinstance(data.get("recent"), dict) else None
            if self.recent is None and self.pending:
                self.recent = self.pending[-1]
            self.handled = data.get("handled") if isinstance(data.get("handled"), list) else []
            self.last_error = ""  # 261001_CURSOR
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            self.last_error = str(exc)

    def _save(self):
        if self.last_error:
            return
        data = {"active": self.active, "pending": self.pending,
                "recent": self.recent, "handled": self.handled[-200:]}
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temp = self.path.with_name(self.path.name + ".tmp")
        try:
            with temp.open("w", encoding="utf-8") as handle:
                json.dump(data, handle, ensure_ascii=False, indent=2)
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temp, self.path)
        except OSError as exc:
            self.last_error = str(exc)
        finally:
            if temp.exists():
                temp.unlink()

    def _merge(self, drivers):
        if self.active is None:
            return
        participants = self.active["participants"]
        existing = {
            (f"id:{row['id']}" if row.get("id") else f"car:{row['car_idx']}|{row['name'].casefold()}"): row
            for row in participants
        }
        changed = False
        for row in participants_from_drivers(drivers):
            key = f"id:{row['id']}" if row["id"] else f"car:{row['car_idx']}|{row['name'].casefold()}"
            if existing.get(key) != row:
                existing[key] = row
                changed = True
        if changed:
            self.active["participants"] = list(existing.values())
            self._save()

    def _finish(self):
        if self.active is None:
            return None
        event = self.active
        self.active = None
        key = event["key"]
        if key not in self.handled:
            self.handled.append(key)
        if event["participants"] and not any(item.get("key") == key for item in self.pending):
            event["participants"].sort(key=lambda row: (row["number"].zfill(5), row["name"].casefold()))
            self.recent = event
            self.pending.append(event)
            self._save()
            return event
        self._save()
        return None

    def poll(self, connected, signature=None, state=None, drivers=None, now=None):
        """Return a finished event at cooldown, transition, or disconnect."""
        # if self.last_error:
        #     return None
        if self.last_error:  # 261001_CURSOR
            self._load()  # 261001_CURSOR
        if self.last_error:  # 261001_CURSOR
            return None  # 261001_CURSOR
        now = time.monotonic() if now is None else now
        if not connected:
            if self.active is not None:
                if self.disconnected_since is None:
                    self.disconnected_since = now
                elif now - self.disconnected_since >= self.disconnect_grace_s:
                    return self._finish()
            return None
        self.disconnected_since = None
        key = race_key(signature)
        session_type = signature[4] if isinstance(signature, (tuple, list)) and len(signature) >= 5 else None
        if self.active is not None and (
            (key is not None and key != self.active["key"])
            or (session_type is not None and str(session_type).strip().casefold() != "race")
        ):
            finished = self._finish()
            if finished:
                return finished
        if key is None or key in self.handled:
            return None
        try:
            state = int(state)
        except (TypeError, ValueError):
            return None
        if state not in (4, 5, 6):
            return None
        if self.active is None:
            self.active = {"key": key, "participants": []}
            self._save()
        self._merge(drivers)
        if state == 6:
            return self._finish()
        return None

    def mark_reviewed(self, key):
        self.pending = [event for event in self.pending if event.get("key") != key]
        self._save()

    def review_event(self):
        """Most relevant collected roster for an explicit Manager click."""
        if self.active and self.active.get("participants"):
            return self.active
        if self.pending:
            return self.pending[-1]
        return self.recent

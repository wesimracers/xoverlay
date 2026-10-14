"""Latest completed laps for rankings and latest observed individual sectors."""

import math


SECTOR_COLUMNS = [
    {"id": "pos", "label": "POS", "width": 42, "enabled": True},
    {"id": "num", "label": "#", "width": 95, "enabled": True},
    {"id": "sector", "label": "Setor", "width": 125, "enabled": True},
    {"id": "sector_2", "label": "Setor", "width": 125, "enabled": True},
    {"id": "sector_3", "label": "Setor", "width": 125, "enabled": True},
    {"id": "tire", "label": "T", "width": 60, "enabled": True},
]


def sector_columns(configured):
    """Upgrade the former Time column in memory, retaining stable config keys."""
    existing = {c.get("id"): c for c in (configured or []) if isinstance(c, dict)}
    columns = []
    for default in SECTOR_COLUMNS:
        col = dict(default)
        col.update(existing.get(col["id"], {}))
        if col["id"].startswith("sector"):
            col.update(label="Setor", enabled=True)
        columns.append(col)
    return columns


class SectorHistory:
    """Keep only the latest completed lap, never fall back after a rejected lap.

    Crossings use the core's SessionTime clock. Missing boundaries, partial
    laps and durations inconsistent with the completed SDK lap are rejected.
    """

    def __init__(self):
        self.reset()

    def reset(self):
        self.last_laps = {}
        self.last_sector_times = {}
        self.sector_count = 0
        self.sector_numbers = []

    def configure_sectors(self, numbers):
        """Numbers follow lap-distance order; SDK SectorNum is converted to 1-based."""
        numbers = list(numbers)
        if self.sector_numbers != numbers:
            self.reset()
            self.sector_numbers = numbers
            self.sector_count = len(numbers)

    def record_lap(self, car_idx, start, crossings, end, lap_time, sector_count, complete=True):
        self.last_laps.pop(car_idx, None)
        if start is None or sector_count < 1:
            return False
        try:
            points = [float(start)] + [float(crossings[i]) for i in range(sector_count - 1)] + [float(end)]
            lap_time = float(lap_time)
        except (KeyError, TypeError, ValueError, OverflowError):
            return False
        if not all(math.isfinite(v) for v in points) or not math.isfinite(lap_time):
            return False
        durations = [b - a for a, b in zip(points, points[1:])]
        if not 20 <= lap_time <= 2000 or any(v <= 0 for v in durations):
            return False
        # At most one second of discrepancy from the SDK lap clock; this
        # also rejects stale S/F anchors after a missed lap or tow.
        if abs(sum(durations) - lap_time) > 1.0:
            return False
        if self.sector_count and self.sector_count != sector_count:
            self.reset()
        self.sector_count = sector_count
        if not self.sector_numbers:
            self.sector_numbers = list(range(1, sector_count + 1))
        # Individual references do not depend on incidents or sporting validity.
        for i, value in enumerate(durations):
            self.record_sector(car_idx, i, value)
        if not complete:
            return False
        self.last_laps[car_idx] = {"seconds": lap_time, "sectors": durations}
        return True

    def record_sector(self, car_idx, sector, seconds):
        if sector < 0 or not math.isfinite(seconds) or not 0 < seconds <= 2000:
            return
        self.last_sector_times.setdefault(car_idx, {})[sector] = seconds

    def latest_sectors(self, drivers):
        return {idx: lap["sectors"] for idx, lap in self.last_laps.items() if idx in drivers}

    def longest_sector(self, drivers):
        """Each eligible car contributes its latest complete lap."""
        selected, means = self.longest_sectors(drivers, 1)
        return (selected[0] if selected else None), means

    def longest_sectors(self, drivers, limit=3):
        """Select longest sectors across latest laps, without session averages."""
        latest = self.latest_sectors(drivers)
        if not latest:
            recent = [times for idx, times in self.last_sector_times.items() if idx in drivers]
            if not recent:
                return [], []
            means = [sum(values) / len(values) if values else 0.0
                     for i in range(self.sector_count)
                     for values in [[times[i] for times in recent if i in times]]]
            selected = sorted((i for i in range(self.sector_count)
                               if means[i] > 0 and self.sector_numbers[i] is not None),
                              key=lambda i: (-means[i], i))
            return selected[:limit], means
        means = [sum(values[i] for values in latest.values()) / len(latest)
                 for i in range(self.sector_count)]
        selected = sorted((i for i in range(self.sector_count)
                           if self.sector_numbers[i] is not None), key=lambda i: (-means[i], i))
        return selected[:limit], means

    def top_cars(self, drivers, sector, limit=5):
        latest = self.latest_sectors(drivers)
        ranked = [{"_idx": idx, "seconds": values[sector]}
                  for idx, values in latest.items()
                  if sector is not None and 0 <= sector < len(values)]
        ranked.sort(key=lambda row: (row["seconds"], row["_idx"]))
        return ranked[:limit]

    def top_last_laps(self, drivers, sectors, limit=5):
        """Rank by the SDK total of the latest complete lap, including incidents."""
        if not sectors:
            return []
        ranked = []
        for idx, latest in self.latest_sectors(drivers).items():
            if any(i < 0 or i >= len(latest) or not math.isfinite(latest[i])
                   or latest[i] <= 0 for i in sectors):
                continue
            values = [latest[i] for i in sectors]
            ranked.append({"_idx": idx, "seconds": self.last_laps[idx]["seconds"], "sectors": values})
        ranked.sort(key=lambda row: (row["seconds"], row["_idx"]))
        return ranked[:limit]

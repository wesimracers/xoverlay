"""Select the fastest current last-lap times from iRacing telemetry."""

import math


def format_lap_millis(seconds):
    """Format a lap as m:ss.mmm, including rounding across minute edges."""
    total_ms = round(float(seconds) * 1000)
    minutes, remainder = divmod(total_ms, 60000)
    whole_seconds, milliseconds = divmod(remainder, 1000)
    return f"{minutes}:{whole_seconds:02d}.{milliseconds:03d}"


def format_top_lap_entry(row):
    """Text shown for one car in the Standings class strip."""
    return f"#{row['num']} ({row['pos']}) {row['bestLap']} {row['tyre']}"


def top_last_laps(drivers, last_lap_times, compounds, limit=3):
    """Return up to ``limit`` drivers, ordered by their most recent lap.

    Each driver's current tyre compound is kept with the lap. A tyre change
    after the lap may therefore change the displayed compound.
    """
    if not isinstance(last_lap_times, (list, tuple)):
        return []
    if not isinstance(compounds, (list, tuple)):
        compounds = []

    ranked = []
    for car_idx, driver in drivers.items():
        if not isinstance(car_idx, int) or car_idx < 0 or car_idx >= len(last_lap_times):
            continue
        if not isinstance(driver, dict) or driver.get("CarIsPaceCar"):
            continue
        try:
            lap_sec = float(last_lap_times[car_idx])
        except (TypeError, ValueError, OverflowError):
            continue
        if not math.isfinite(lap_sec) or not 20.0 <= lap_sec <= 2000.0:
            continue

        ranked.append({
            "_idx": car_idx,
            "last_sec": lap_sec,
            "compound": compounds[car_idx] if car_idx < len(compounds) else None,
        })

    ranked.sort(key=lambda row: (row["last_sec"], row["_idx"]))
    return ranked[:limit]

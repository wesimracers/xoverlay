"""Shared Weather columns and upgrades for saved layouts."""

WEATHER_COLUMNS = [
    {"id": "rubber", "label": "Rubber", "width": 90, "enabled": True},
    {"id": "temp", "label": "Temp", "width": 70, "enabled": True},
    {"id": "track", "label": "Track", "width": 70, "enabled": True},
    {"id": "wet", "label": "Wet", "width": 90, "enabled": True},
    {"id": "condition", "label": "", "width": 269, "enabled": True},
    {"id": "prec", "label": "Prec", "width": 80, "enabled": True},
]


def weather_columns(configured):
    """Insert the condition after Wet once, preserving custom column settings."""
    columns = [dict(col) for col in (configured or WEATHER_COLUMNS)]
    if any(col.get("id") == "condition" for col in columns):
        return columns
    condition = dict(WEATHER_COLUMNS[4])
    for index, col in enumerate(columns):
        if col.get("id") == "wet":
            # Split a combined cell when it has room for both values and a divider.
            width = int(col.get("width", 360))
            if width >= 180:
                condition["width"] = width - 91
                col["width"] = 90
            condition["enabled"] = col.get("enabled", True)
            columns.insert(index + 1, condition)
            break
    else:
        columns.append(condition)
    return columns

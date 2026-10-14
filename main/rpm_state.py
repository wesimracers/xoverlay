"""RPM scale uses the player's redline, never a sampled peak or shift light."""

import math


RPM_WINDOW_DEFAULTS = {
    "x": 100, "y": 100, "width": 600, "height": 10,
    "enabled": True, "show_in_garage": False,
}
RPM_UPDATE_MS = 16


def seed_rpm_config(cfg):
    window = cfg.setdefault("windows", {}).setdefault("rpm", {})
    for key, value in RPM_WINDOW_DEFAULTS.items():
        window.setdefault(key, value)
    settings = cfg.setdefault("rpm_settings", {})
    settings.setdefault("update_ms", RPM_UPDATE_MS)
    settings.setdefault("max_rpm_by_car", {})


def finite_number(value):
    if isinstance(value, bool):
        return None
    try:
        number = float(value)
        return number if math.isfinite(number) else None
    except (ValueError, TypeError, OverflowError):
        return None


def car_key(driver_info):
    """Stable model identity for overrides; session CarIdx is not a model ID."""
    if not isinstance(driver_info, dict):
        return None
    idx = driver_info.get("DriverCarIdx")
    if idx is None:
        return None
    for driver in driver_info.get("Drivers") or []:
        if not isinstance(driver, dict) or driver.get("CarIdx") != idx:
            continue
        path = driver.get("CarPath")
        if isinstance(path, str) and path.strip():
            return "path:" + path.strip()
        car_id = finite_number(driver.get("CarID"))
        if car_id is not None and car_id >= 0 and car_id.is_integer():
            return "id:" + str(int(car_id))
    return None


def resolve_max_rpm(driver_info, settings):
    info = driver_info if isinstance(driver_info, dict) else {}
    overrides = settings.get("max_rpm_by_car") or {}
    key = car_key(info)
    override = finite_number(overrides.get(key)) if isinstance(overrides, dict) and key else None
    if override is not None and override > 0:
        return override, "car_override"
    redline = finite_number(info.get("DriverCarRedLine"))
    if redline is not None and redline > 0:
        return redline, "DriverCarRedLine"
    return None, "unavailable"


def rpm_state(rpm, driver_info, settings):
    maximum, source = resolve_max_rpm(driver_info, settings)
    current = finite_number(rpm)
    fraction = min(1.0, max(0.0, current / maximum)) if current is not None and maximum else 0.0
    status = "ready" if maximum and current is not None else (
        "missing_max_rpm" if maximum is None else "missing_rpm")
    return {"rpm": current, "max_rpm": maximum, "max_rpm_source": source,
            "car_key": car_key(driver_info), "percent": fraction * 100, "status": status}

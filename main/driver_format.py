"""Shared Relative and Standings text helpers."""
import core  # 261001_CURSOR


def inc_for_car(car_idx: int, drv: dict, pi: int):  # 261001_CURSOR
    try:  # 261001_CURSOR
        _lc_arr = core.sg("CarIdxLapCompleted", []) or []  # 261001_CURSOR
        _surf_arr = core.sg("CarIdxTrackSurface", []) or []  # 261001_CURSOR
        _pi_lc = int(_lc_arr[pi]) if pi < len(_lc_arr) else -1  # 261001_CURSOR
        _pi_surf = int(_surf_arr[pi]) if pi < len(_surf_arr) else -1  # 261001_CURSOR
        if _pi_lc < 0 or _pi_surf < 0:  # 261001_CURSOR
            return ""  # 261001_CURSOR
    except Exception:  # 261001_CURSOR
        return ""  # 261001_CURSOR
    total = core._inc_cache.get(car_idx, 0)  # 261001_CURSOR
    if car_idx == pi:  # 261001_CURSOR
        for _tvar in ("PlayerCarTeamIncidentCount", "PlayerCarMyIncidentCount", "PlayerCarDriverIncidentCount"):  # 261001_CURSOR
            try:  # 261001_CURSOR
                _v = int(float(core.sg(_tvar, 0) or 0))  # 261001_CURSOR
                if _v > total:  # 261001_CURSOR
                    total = _v  # 261001_CURSOR
            except Exception:  # 261001_CURSOR
                pass  # 261001_CURSOR
    return str(total) if total > 0 else ""  # 261001_CURSOR


def fmt_avg_delta(player_avg, car_avg, is_player=False):  # 261001_CURSOR
    if is_player:  # 261001_CURSOR
        return "0", core.CLR_WHITE  # 261001_CURSOR
    try:  # 261001_CURSOR
        pa = float(player_avg)  # 261001_CURSOR
        ca = float(car_avg)  # 261001_CURSOR
    except Exception:  # 261001_CURSOR
        return "", core.CLR_WHITE  # 261001_CURSOR
    d = pa - ca  # 261001_CURSOR
    if abs(d) < 0.05:  # 261001_CURSOR
        return "0", core.CLR_WHITE  # 261001_CURSOR
    return f"{d:.1f}", (core.CLR_GREEN if d < 0 else core.CLR_RED)  # 261001_CURSOR

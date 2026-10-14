"""Pure race-finish and fuel projections; no SDK, UI or shared-core state."""

import math


def number(value):
    try:
        value = float(value)
        return value if math.isfinite(value) else None
    except (ValueError, TypeError, OverflowError):
        return None


def positive(value):
    value = number(value)
    return value if value is not None and value > 0 else None


def lap_limit(value):
    value = number(value)
    return int(value) if value is not None and 0 < value < 32767 else None


def _crossings_until(seconds, phase, lap_time):
    # The first player crossing AT OR AFTER the leader finishes receives
    # the checker. Never round down to a mid-lap end or to the nearest lap.
    return max(1, math.ceil(phase + seconds / lap_time - 1e-8))


def project_finish(*, player_completed, player_position, player_lap_time,
                   leader_completed, leader_position, leader_lap_time,
                   time_remaining=None, total_laps=None, laps_remaining=None,
                   player_phase=None, leader_phase=None, leader_finished=False,
                   player_finished=False, player_white=False, same_class=True):
    """Return remaining distance in laps and player's projected finish count.

    Phase is elapsed fraction of the SDK model lap, when available. Position
    is distance fraction; these are deliberately separate on road circuits.
    Timed races finish at the leader's line crossing after expiry, followed
    by the player's line crossing. A simultaneous lap limit ends the race
    earlier. Finite laps_remaining is SessionLapsRemainEx, which INCLUDES
    the current lap (unlike the deprecated SessionLapsRemain field).
    """
    completed = number(player_completed)
    position = number(player_position)
    if completed is None or completed < 0 or position is None or not 0 <= position <= 1:
        return None
    completed = int(completed)
    if player_finished:
        return {"laps_left": 0.0, "finish_lap": completed, "method": "finished"}
    if player_white or leader_finished:
        return {"laps_left": max(0.0, 1.0 - position),
                "finish_lap": completed + 1, "method": "final_lap"}

    leader_completed = number(leader_completed)
    leader_position = number(leader_position)
    if leader_completed is None or leader_completed < 0 or leader_position is None or not 0 <= leader_position <= 1:
        return None
    leader_completed = int(leader_completed)
    total = lap_limit(total_laps)
    remaining = number(laps_remaining)
    if total is None and remaining is not None and 0 < remaining < 32767:
        total = leader_completed + int(remaining)

    player_lt = positive(player_lap_time)
    leader_lt = positive(leader_lap_time)
    player_phase = number(player_phase)
    leader_phase = number(leader_phase)
    if player_phase is None or not 0 <= player_phase <= 1:
        player_phase = position
    if leader_phase is None or not 0 <= leader_phase <= 1:
        leader_phase = leader_position

    horizon = None
    method = "laps"
    if total is not None:
        if total <= leader_completed:
            return {"laps_left": 1.0 - position, "finish_lap": completed + 1,
                    "method": "leader_finished"}
        if leader_lt is not None:
            horizon = ((total - leader_completed - 1) + 1 - leader_phase) * leader_lt

    seconds = number(time_remaining)
    if seconds is not None and 0 <= seconds < 604800 and leader_lt is not None:
        until_line = (1.0 - leader_phase) * leader_lt
        whole_laps = max(0, math.ceil((seconds - until_line) / leader_lt - 1e-8))
        timed_horizon = until_line + whole_laps * leader_lt
        if horizon is None or timed_horizon < horizon:
            horizon = timed_horizon
            method = "timed_finish_line"

    if total is not None and method == "laps" and same_class:
        # Do not underfuel a lap-count race by predicting that a lead-lap
        # competitor will be lapped sometime later. Use laps actually lost.
        laps_down = max(0, math.floor(leader_completed + leader_position - completed - position))
        finish_lap = max(completed, total - laps_down)
    elif horizon is not None and player_lt is not None:
        finish_lap = completed + _crossings_until(horizon, player_phase, player_lt)
        if total is not None:
            finish_lap = min(total, finish_lap)
    elif total is not None:
        # Without pace data, use physical race progress rather than scaling
        # all historical laps by today's pace ratio.
        laps_down = max(0, math.floor(leader_completed + leader_position - completed - position))
        finish_lap = max(completed, total - laps_down)
    else:
        return None
    return {"laps_left": max(0.0, finish_lap - completed - position),
            "finish_lap": finish_lap, "method": method,
            "leader_finish_seconds": horizon}


def fuel_required(laps_left, consumption, reserve, *, position=0.0, burned_this_lap=None):
    """Litres to the finish, including reserve and only the undriven distance.

    A clean S/F fuel anchor gives a more accurate remaining current-lap burn
    than distance scaling on tracks with uneven throttle use.
    """
    laps = number(laps_left)
    burn = positive(consumption)
    if laps is None or burn is None:
        return None
    if laps <= 0:
        return 0.0
    required = laps * burn
    used = number(burned_this_lap)
    pct = number(position)
    if used is not None and used >= 0 and pct is not None and 0 <= pct <= 1:
        crossings = max(1, round(laps + pct))
        required = (crossings - 1) * burn + max(0.0, burn - used)
    return max(0.0, required) + max(0.0, number(reserve) or 0.0)


def refuel_display(litres):
    value = number(litres)
    return "—" if value is None else str(max(0, math.ceil(value - 1e-9)))


def _at(values, idx, default=None):  # 261001_CURSOR
    if isinstance(idx, int) and isinstance(values, (list, tuple)) and 0 <= idx < len(values):  # 261001_CURSOR
        return values[idx]  # 261001_CURSOR
    return default  # 261001_CURSOR


def build_finish_projection(*, player_idx, player_completed, drivers, lap_completed,  # 261001_CURSOR
                            lap_dist, positions, surfaces, estimates, last_laps, best_laps,  # 261001_CURSOR
                            car_flags, time_remaining, total_laps, laps_remaining,  # 261001_CURSOR
                            session_state, is_practice, checkered_finish_lap,  # 261001_CURSOR
                            average_pace, is_safety):  # 261001_CURSOR
    """One finish projection for Fuel and Info, using project_finish."""  # 261001_CURSOR
    drivers = drivers if isinstance(drivers, dict) else {}  # 261001_CURSOR
    try:  # 261001_CURSOR
        state = int(session_state or 0)  # 261001_CURSOR
    except (TypeError, ValueError):  # 261001_CURSOR
        state = 0  # 261001_CURSOR
    cur_lap = int(player_completed)  # 261001_CURSOR

    def pace(idx):  # 261001_CURSOR
        best = positive(_at(best_laps, idx))  # 261001_CURSOR
        last = positive(_at(last_laps, idx))  # 261001_CURSOR
        average = positive(average_pace(idx) if average_pace else None)  # 261001_CURSOR
        if average:  # 261001_CURSOR
            return average  # 261001_CURSOR
        if last and (best is None or last <= best * 1.15):  # 261001_CURSOR
            return last  # 261001_CURSOR
        driver = drivers.get(idx, {})  # 261001_CURSOR
        driver = driver if isinstance(driver, dict) else {}  # 261001_CURSOR
        return best or positive(driver.get("CarClassEstLapTime"))  # 261001_CURSOR

    def phase(idx):  # 261001_CURSOR
        estimate = number(_at(estimates, idx))  # 261001_CURSOR
        driver = drivers.get(idx, {})  # 261001_CURSOR
        driver = driver if isinstance(driver, dict) else {}  # 261001_CURSOR
        model_lap = positive(driver.get("CarClassEstLapTime"))  # 261001_CURSOR
        if estimate is not None and model_lap and 0 < estimate <= model_lap:  # 261001_CURSOR
            return estimate / model_lap  # 261001_CURSOR
        return None  # 261001_CURSOR

    active = []  # 261001_CURSOR
    for idx, driver in drivers.items():  # 261001_CURSOR
        lc = number(_at(lap_completed, idx))  # 261001_CURSOR
        dp = number(_at(lap_dist, idx))  # 261001_CURSOR
        surface = number(_at(surfaces, idx))  # 261001_CURSOR
        if (is_safety(driver) or lc is None or lc < 0 or  # 261001_CURSOR
                dp is None or not 0 <= dp <= 1 or  # 261001_CURSOR
                (surface is not None and surface < 0)):  # 261001_CURSOR
            continue  # 261001_CURSOR
        active.append(idx)  # 261001_CURSOR
    leader_idx = next((idx for idx in active if _at(positions, idx) == 1), None)  # 261001_CURSOR
    if leader_idx is None and active:  # 261001_CURSOR
        leader_idx = max(active, key=lambda idx: lap_completed[idx] + lap_dist[idx])  # 261001_CURSOR
    player_dp = number(_at(lap_dist, player_idx))  # 261001_CURSOR
    player_flags = int(_at(car_flags, player_idx, 0) or 0)  # 261001_CURSOR
    player_finished = bool(player_flags & 0x1) or state >= 6  # 261001_CURSOR
    leader_finished = state == 5  # 261001_CURSOR
    new_checkered = checkered_finish_lap  # 261001_CURSOR
    if leader_finished and new_checkered is None:  # 261001_CURSOR
        new_checkered = cur_lap + 1  # 261001_CURSOR
    if new_checkered is not None and cur_lap >= new_checkered:  # 261001_CURSOR
        player_finished = True  # 261001_CURSOR
    projection = None  # 261001_CURSOR
    if not is_practice and leader_idx is not None:  # 261001_CURSOR
        player_driver = drivers.get(player_idx, {})  # 261001_CURSOR
        leader_driver = drivers.get(leader_idx, {})  # 261001_CURSOR
        player_driver = player_driver if isinstance(player_driver, dict) else {}  # 261001_CURSOR
        leader_driver = leader_driver if isinstance(leader_driver, dict) else {}  # 261001_CURSOR
        projection = project_finish(  # 261001_CURSOR
            player_completed=cur_lap, player_position=player_dp,  # 261001_CURSOR
            player_lap_time=pace(player_idx), leader_completed=_at(lap_completed, leader_idx),  # 261001_CURSOR
            leader_position=_at(lap_dist, leader_idx), leader_lap_time=pace(leader_idx),  # 261001_CURSOR
            time_remaining=time_remaining, total_laps=total_laps,  # 261001_CURSOR
            laps_remaining=laps_remaining, player_phase=phase(player_idx),  # 261001_CURSOR
            leader_phase=phase(leader_idx),  # 261001_CURSOR
            leader_finished=leader_finished, player_finished=player_finished,  # 261001_CURSOR
            player_white=bool(player_flags & 0x2),  # 261001_CURSOR
            same_class=player_driver.get("CarClassID") == leader_driver.get("CarClassID"),  # 261001_CURSOR
        )  # 261001_CURSOR
    return {  # 261001_CURSOR
        "projection": projection,  # 261001_CURSOR
        "checkered_finish_lap": new_checkered,  # 261001_CURSOR
        "player_dist": player_dp,  # 261001_CURSOR
        "leader_idx": leader_idx,  # 261001_CURSOR
    }  # 261001_CURSOR

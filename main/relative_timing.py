"""RELATIVE-only track-position intervals, using one car-model clock.

CarIdxEstTime is an SDK estimate at a position, not a running lap timer.
Even cars in the same class can have different estimated-time curves. Learn
the player's model curve, and evaluate both positions on that curve. Until
that part of the track is sampled, use an explicitly approximate distance
interval. Actual last/best laps must never wrap the SDK estimated-time clock.

Sources and regression evidence: ../research/relative_fix_20260920.md.
This module has no SDK, Qt, filesystem, or STANDINGS dependencies.
"""

from bisect import bisect_left
import math


def _number(value):
    try:
        value = float(value)
        return value if math.isfinite(value) else None
    except (TypeError, ValueError, OverflowError):
        return None


def track_position(value):
    value = _number(value)
    return value if value is not None and 0.0 <= value <= 1.0 else None


def wrap_fraction(value):
    value = _number(value)
    if value is None:
        return None
    if value > 0.5:
        value -= 1.0
    elif value < -0.5:
        value += 1.0
    return value


def _at(values, index):
    return values[index] if isinstance(values, (list, tuple)) and 0 <= index < len(values) else None


def _model(driver, index):
    # Class IDs are not model IDs (e.g. different GT3 manufacturers).
    if driver.get("CarPath"):
        return ("path", str(driver["CarPath"]))
    if driver.get("CarID"):
        return ("id", str(driver["CarID"]))
    return ("car", index)


def _lap_time(value):
    value = _number(value)
    return value if value is not None and 0.0 < value <= 86400.0 else None


def _estimate(value, position, lap_time):
    value = _number(value)
    if value is None or value < 0.0:
        return None
    if value == 0.0 and position != 0.0:
        return None  # SDK unavailable sentinel, except at start/finish.
    if lap_time is not None and value > lap_time + 0.01:
        return None
    return value


def _spatial_time_gap(player_position, target_position, player_time, target_time, lap_time):
    raw_distance = target_position - player_position
    distance = wrap_fraction(raw_distance)
    if abs(distance) < 1e-12:
        return 0.0
    result = target_time - player_time
    if raw_distance > 0.5:
        if lap_time is None:
            return None
        result -= lap_time
    elif raw_distance < -0.5:
        if lap_time is None:
            return None
        result += lap_time
    # Reject inconsistent/stale estimates instead of flipping their sign or
    # turning a small error into an almost full-lap interval.
    if result * distance < 0.0:
        return None
    return result


class RelativeTiming:
    def __init__(self):
        self.reset()

    def reset(self):
        self._scope = None
        self._last_time = None
        self._samples = {}
        self._cars = {}
        self._points = []
        self._positions = []
        self._player = None
        self._lap = None
        self._fallback_lap = None

    def update(self, player_idx, drivers, positions, estimates, surfaces,
               session_key=None, session_time=None, track_length_m=None,
               fallback_lap_time=None):
        player = drivers.get(player_idx, {})
        model = _model(player, player_idx)
        lap = _lap_time(player.get("CarClassEstLapTime"))
        length = _number(track_length_m)
        # Ten-metre buckets retain exact sample coordinates. Restrict
        # interpolation to nearby brackets, never an unsampled whole lap.
        buckets = max(100, math.ceil(length / 10.0)) if length and length > 0 else 1000
        self._max_span = min(0.05, 200.0 / length) if length and length > 0 else 0.02
        scope = (session_key, player_idx, model, lap, buckets)
        now = _number(session_time)
        if (scope != self._scope or
                (now is not None and self._last_time is not None and now < self._last_time)):
            self.reset()
            self._scope = scope
        self._last_time = now
        self._player = player_idx
        self._lap = lap
        self._fallback_lap = lap or _lap_time(fallback_lap_time)
        self._cars = {}

        for idx, driver in drivers.items():
            if not isinstance(idx, int) or idx < 0:
                continue
            position = track_position(_at(positions, idx))
            surface = _number(_at(surfaces, idx))
            if position is None or (surface is not None and surface < 0):
                continue
            car_model = _model(driver, idx)
            car_lap = _lap_time(driver.get("CarClassEstLapTime"))
            estimate = _estimate(_at(estimates, idx), position, car_lap)
            same_clock = car_model == model and car_lap == lap
            self._cars[idx] = (position, estimate, same_clock)
            if same_clock and estimate is not None and lap is not None and 0.0 < position < 1.0:
                self._samples[min(buckets - 1, int(position * buckets))] = (position, estimate)

        points = list(self._samples.values())
        if lap is not None:
            points.extend(((0.0, 0.0), (1.0, lap)))
        # Current player position is an exact anchor, even when a peer in
        # the same bucket supplied the retained historical sample.
        current = self._cars.get(player_idx)
        if current and current[1] is not None:
            points.append((current[0], current[1]))
        self._points = sorted(dict(points).items())
        self._positions = [point[0] for point in self._points]

    def _interpolate(self, position):
        index = bisect_left(self._positions, position)
        if index < len(self._points) and self._positions[index] == position:
            return self._points[index][1]
        if index == 0 or index == len(self._points):
            return None
        left, right = self._points[index - 1], self._points[index]
        span = right[0] - left[0]
        if span <= 0.0 or span > self._max_span or right[1] < left[1]:
            return None
        return left[1] + (right[1] - left[1]) * (position - left[0]) / span

    # def gap(self, target_idx):
    #     player = self._cars.get(self._player)
    #     target = self._cars.get(target_idx)
    #     debug = {"source": "unavailable", "approximate": False,
    #              "player_lap_time": self._lap, "profile_points": len(self._samples)}
    #     if player is None or target is None:
    #         return None, debug
    #     player_position, player_estimate, _ = player
    #     target_position, target_estimate, same_clock = target
    #     distance = wrap_fraction(target_position - player_position)
    #     if abs(distance) < 1e-12:
    #         debug["source"] = "coincident"
    #         return 0.0, debug
    #
    #     if same_clock and player_estimate is not None and target_estimate is not None:
    #         result = _spatial_time_gap(player_position, target_position,
    #                                    player_estimate, target_estimate, self._lap)
    #         if result is not None:
    #             debug["source"] = "same_model_live"
    #             return result, debug
    #
    #     player_time = self._interpolate(player_position)
    #     target_time = self._interpolate(target_position)
    #     if player_time is not None and target_time is not None:
    #         result = _spatial_time_gap(player_position, target_position,
    #                                    player_time, target_time, self._lap)
    #         if result is not None:
    #             debug["source"] = "player_model_profile"
    #             return result, debug
    #
    #     if self._fallback_lap is not None:
    #         debug.update(source="player_distance_estimate", approximate=True)
    #         return distance * self._fallback_lap, debug
    #     return None, debug

    def gap(self, target_idx):  # 261001_CURSOR
        return self.gap_between(self._player, target_idx)  # 261001_CURSOR

    def gap_between(self, reference_idx, target_idx):  # 261001_CURSOR
        reference = self._cars.get(reference_idx)  # 261001_CURSOR
        target = self._cars.get(target_idx)  # 261001_CURSOR
        debug = {"source": "unavailable", "approximate": False,  # 261001_CURSOR
                 "player_lap_time": self._lap, "profile_points": len(self._samples)}  # 261001_CURSOR
        if reference is None or target is None:  # 261001_CURSOR
            return None, debug  # 261001_CURSOR
        reference_position, reference_estimate, reference_same = reference  # 261001_CURSOR
        target_position, target_estimate, target_same = target  # 261001_CURSOR
        distance = wrap_fraction(target_position - reference_position)  # 261001_CURSOR
        if abs(distance) < 1e-12:  # 261001_CURSOR
            debug["source"] = "coincident"  # 261001_CURSOR
            return 0.0, debug  # 261001_CURSOR
        if reference_same and target_same and reference_estimate is not None and target_estimate is not None:  # 261001_CURSOR
            result = _spatial_time_gap(reference_position, target_position,  # 261001_CURSOR
                                       reference_estimate, target_estimate, self._lap)  # 261001_CURSOR
            if result is not None:  # 261001_CURSOR
                debug["source"] = "same_model_live"  # 261001_CURSOR
                return result, debug  # 261001_CURSOR
        reference_time = self._interpolate(reference_position)  # 261001_CURSOR
        target_time = self._interpolate(target_position)  # 261001_CURSOR
        if reference_time is not None and target_time is not None:  # 261001_CURSOR
            result = _spatial_time_gap(reference_position, target_position,  # 261001_CURSOR
                                       reference_time, target_time, self._lap)  # 261001_CURSOR
            if result is not None:  # 261001_CURSOR
                debug["source"] = "player_model_profile"  # 261001_CURSOR
                return result, debug  # 261001_CURSOR
        if self._fallback_lap is not None:  # 261001_CURSOR
            debug.update(source="player_distance_estimate", approximate=True)  # 261001_CURSOR
            return distance * self._fallback_lap, debug  # 261001_CURSOR
        return None, debug  # 261001_CURSOR

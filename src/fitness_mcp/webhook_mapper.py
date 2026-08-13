from . import util

_START = ["start_time", "startTime", "start"]
_END = ["end_time", "endTime", "end"]
_ID = ["id", "record_id", "metadata_id", "uid"]
_TIME = ["time", "timestamp"] + _START

# store kind -> (candidate top-level array names, candidate value field names)
_CUMULATIVE = {
    "steps": (["steps", "step_count", "steps_records"], ["count", "steps", "value"]),
    "distance": (["distance", "distance_records"], ["distance", "meters", "value", "length"]),
    "active_calories": (["active_calories_burned", "active_calories"], ["energy", "calories", "kilocalories", "value"]),
    "total_calories": (["total_calories_burned", "total_calories"], ["energy", "calories", "kilocalories", "value"]),
    "active_minutes": (["active_minutes", "move_minutes", "exercise_minutes"], ["minutes", "duration", "count", "value"]),
}


def _array(payload: dict, names: list[str]) -> list:
    for n in names:
        v = payload.get(n)
        if isinstance(v, list):
            return v
    return []


def map_payload(payload: dict) -> dict[str, list[dict]]:
    out: dict[str, list[dict]] = {}

    for kind, (names, value_keys) in _CUMULATIVE.items():
        recs = []
        for r in _array(payload, names):
            start = util.first(r, _START)
            val = util.to_number(util.first(r, value_keys))
            if start is None or val is None:
                continue
            end = util.first(r, _END)
            rid = util.first(r, _ID) or f"{start}|{end}"
            recs.append({"id": str(rid), "start": start, "end": end, "value": val})
        if recs:
            out[kind] = recs

    hr = []
    for r in _array(payload, ["heart_rate", "heart_rate_records", "heartrate"]):
        samples = r["samples"] if isinstance(r.get("samples"), list) else [r]
        for s in samples:
            t = util.first(s, _TIME)
            bpm = util.to_number(util.first(s, ["bpm", "beats_per_minute", "beatsPerMinute", "value"]))
            if t is None or bpm is None:
                continue
            hr.append({"id": str(t), "time": t, "bpm": bpm})
    if hr:
        out["heart_rate"] = hr

    sleep = []
    for r in _array(payload, ["sleep_sessions", "sleep", "sleep_records"]):
        start, end = util.first(r, _START), util.first(r, _END)
        if not start or not end:
            continue
        rec = {"id": str(start), "start": start, "end": end}
        dur = util.duration_minutes(start, end)
        if dur is not None:
            rec["duration_min"] = dur
        sleep.append(rec)
    if sleep:
        out["sleep"] = sleep

    workouts = []
    for r in _array(payload, ["exercise_sessions", "workouts", "exercise", "sessions"]):
        start, end = util.first(r, _START), util.first(r, _END)
        if not start or not end:
            continue
        rec = {"id": str(start), "start": start, "end": end,
               "activity_type": str(util.first(r, ["exercise_type", "type", "activity_type", "title"]) or "Unknown")}
        dur = util.duration_minutes(start, end)
        if dur is not None:
            rec["duration_min"] = dur
        dist = util.to_number(util.first(r, ["distance", "distance_m", "meters"]))
        if dist is not None:
            rec["distance_m"] = dist
        cal = util.to_number(util.first(r, ["energy", "calories", "kilocalories"]))
        if cal is not None:
            rec["calories"] = cal
        workouts.append(rec)
    if workouts:
        out["workouts"] = workouts

    body = {}
    for r in _array(payload, ["weight", "weight_records", "body"]):
        t = util.first(r, _TIME)
        w = util.to_number(util.first(r, ["weight_kg", "weight", "kilograms", "value"]))
        if t is None or w is None:
            continue
        d = str(t)[:10]
        body[d] = {"date": d, "weight_kg": w}
    if body:
        out["body_metrics"] = list(body.values())

    return out

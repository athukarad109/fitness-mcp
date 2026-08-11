from collections import defaultdict

from . import util

# store kind -> daily output field for summed cumulative metrics
SUM_FIELDS = {
    "steps": "steps",
    "distance": "distance_m",
    "active_calories": "active_calories",
    "total_calories": "calories",
    "active_minutes": "active_minutes",
}


def _clean(v):
    if isinstance(v, float) and v.is_integer():
        return int(v)
    return round(v, 3) if isinstance(v, float) else v


def build_daily(raw_by_kind: dict, start: str, end: str) -> list[dict]:
    days: dict[str, dict] = defaultdict(dict)

    for kind, field in SUM_FIELDS.items():
        for rec in raw_by_kind.get(kind, []):
            d = util.local_date(rec.get("start"))
            if d is None or not (start <= d <= end):
                continue
            val = rec.get("value")
            if isinstance(val, (int, float)) and not isinstance(val, bool):
                days[d][field] = days[d].get(field, 0) + val

    hr_by_day = defaultdict(list)
    for rec in raw_by_kind.get("heart_rate", []):
        d = util.local_date(rec.get("time"))
        if d is None or not (start <= d <= end):
            continue
        bpm = rec.get("bpm")
        if isinstance(bpm, (int, float)) and not isinstance(bpm, bool):
            hr_by_day[d].append(bpm)
    for d, vals in hr_by_day.items():
        days[d]["avg_hr"] = round(sum(vals) / len(vals), 1)
        days[d]["min_hr"] = min(vals)
        days[d]["max_hr"] = max(vals)

    rows = []
    for d in sorted(days):
        row = {"date": d}
        row.update({k: _clean(v) for k, v in days[d].items()})
        rows.append(row)
    return rows

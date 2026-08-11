from datetime import datetime


def to_number(raw):
    if isinstance(raw, bool):
        return None
    if isinstance(raw, (int, float)):
        return raw
    s = (str(raw) if raw is not None else "").strip()
    if s == "":
        return None
    try:
        f = float(s)
    except ValueError:
        return None
    return int(f) if f.is_integer() else round(f, 3)


def parse_dt(s):
    if not s:
        return None
    try:
        return datetime.fromisoformat(str(s).replace("Z", "+00:00"))
    except ValueError:
        return None


def duration_minutes(start, end):
    a, b = parse_dt(start), parse_dt(end)
    if a is None or b is None:
        return None
    return round((b - a).total_seconds() / 60, 1)


def local_date(iso):
    dt = parse_dt(iso)
    return dt.date().isoformat() if dt else None


def first(d, keys):
    for k in keys:
        v = d.get(k)
        if v not in (None, ""):
            return v
    return None

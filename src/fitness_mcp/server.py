from mcp.server.fastmcp import FastMCP

from . import aggregate, store

mcp = FastMCP("fitness")

# raw kind -> the record field carrying its timestamp (for range queries)
_RAW_DATE_FIELD = {
    "steps": "start",
    "distance": "start",
    "active_calories": "start",
    "total_calories": "start",
    "active_minutes": "start",
    "heart_rate": "time",
}

_COVERAGE = {
    "steps": "start",
    "distance": "start",
    "active_calories": "start",
    "total_calories": "start",
    "active_minutes": "start",
    "heart_rate": "time",
    "sleep": "start",
    "workouts": "start",
    "body_metrics": "date",
}


def _daily(start_date: str, end_date: str) -> list[dict]:
    raw = {k: store.query_range(k, f, start_date, end_date) for k, f in _RAW_DATE_FIELD.items()}
    return aggregate.build_daily(raw, start_date, end_date)


@mcp.tool()
def list_data_coverage() -> dict:
    """Report which data types are present and the date range each covers."""
    cov = {k: store.coverage(k, f) for k, f in _COVERAGE.items()}
    if all(v is None for v in cov.values()):
        return {"message": "no data yet — the phone app hasn't pushed anything", "coverage": cov}
    return {"coverage": cov}


@mcp.tool()
def get_daily_metrics(start_date: str, end_date: str) -> list[dict]:
    """Daily activity rows (steps, distance, calories, active minutes, heart rate) in [start_date, end_date]."""
    return _daily(start_date, end_date)


@mcp.tool()
def get_sleep(start_date: str, end_date: str) -> list[dict]:
    """Sleep sessions starting within [start_date, end_date]."""
    return store.query_range("sleep", "start", start_date, end_date)


@mcp.tool()
def get_body_metrics(start_date: str, end_date: str) -> list[dict]:
    """Body measurements (e.g. weight_kg) recorded within [start_date, end_date]."""
    return store.query_range("body_metrics", "date", start_date, end_date)


@mcp.tool()
def get_workouts(start_date: str, end_date: str, activity_type: str = "") -> list[dict]:
    """Workout sessions in [start_date, end_date], optionally filtered by activity_type (case-insensitive)."""
    rows = store.query_range("workouts", "start", start_date, end_date)
    if activity_type:
        want = activity_type.lower()
        rows = [r for r in rows if str(r.get("activity_type", "")).lower() == want]
    return rows


@mcp.tool()
def get_metric_stats(metric: str, start_date: str, end_date: str) -> dict:
    """min/max/avg/sum/count for a daily metric (e.g. 'steps') over [start_date, end_date]."""
    rows = _daily(start_date, end_date)
    vals = [r[metric] for r in rows if isinstance(r.get(metric), (int, float))]
    if not vals:
        return {"metric": metric, "count": 0, "message": "no data for this metric in range"}
    return {
        "metric": metric,
        "count": len(vals),
        "min": min(vals),
        "max": max(vals),
        "avg": round(sum(vals) / len(vals), 2),
        "sum": round(sum(vals), 2),
    }


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()

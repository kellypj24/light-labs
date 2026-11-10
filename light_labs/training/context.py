"""The planning week's context: free windows and weather per day, in one JSON file.

`lab training context [--week 2026-W47]` writes var/training/context/<yyyy>-W<ww>.json,
the default week being the next one to start after today. Computed when needed, never
stored in DuckDB: it holds only busy-derived free windows (no event titles) and a
forecast, and goes stale within days.
"""

import json
from datetime import date, datetime, timedelta
from pathlib import Path

from light_labs import config
from light_labs.training import calendar, weather


def week_start(week=None, today=None):
    """Monday of ISO week 'YYYY-Www', or of the next week to start after `today`."""
    if week:
        year, _, num = week.upper().partition("-W")
        return date.fromisocalendar(int(year), int(num), 1)
    today = today or date.today()
    return today + timedelta(days=7 - today.weekday())


def build(start, busy, grid):
    days = [start + timedelta(days=i) for i in range(7)]
    free = calendar.free_windows(busy, days)
    forecast = weather.daily(grid, days) if grid else dict.fromkeys(days)
    year, num, _ = start.isocalendar()
    return {
        "week": f"{year}-W{num:02d}",
        "generated_at": datetime.now(calendar.TZ).isoformat(timespec="seconds"),
        "days": [
            {
                "date": d.isoformat(),
                "weekday": d.strftime("%a"),
                "free": [[a.strftime("%H:%M"), b.strftime("%H:%M")] for a, b in free[d]],
                "weather": forecast[d],
            }
            for d in days
        ],
    }


def write(ctx, var=None):
    out = Path(var or config.VAR) / "training" / "context" / f"{ctx['week']}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(ctx, indent=2) + "\n")
    return out


def run(week=None, cal=None, opener=None):
    """Fetch both sources and write the file. Returns (path, context)."""
    start = week_start(week)
    busy = calendar.fetch_busy(start, cal)
    lat, lon = weather.location()
    grid = weather.fetch_grid(lat, lon, **({"opener": opener} if opener else {}))
    ctx = build(start, busy, grid)
    return write(ctx), ctx

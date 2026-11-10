"""Daily weather for the training planner from api.weather.gov (no key).

The grid data gives hourly-or-longer values for temperature, wind chill and precipitation
chance. An hour is good for an outdoor run when the air is at least 38°F, the wind chill
at least 32°F (PJ's limits, from goals.md), and it isn't icy (precipitation likely at or
near freezing). Each day reduces to its daytime (07:00–19:00 local) range, the low, the
run-able hours as one or more windows, and `outdoor_ok` when there is at least one.

The location is a `- Location: <lat>, <lon>` line in var/training/goals.md.
"""

import json
import re
import urllib.request
from datetime import datetime, time, timedelta
from pathlib import Path

from light_labs import config
from light_labs.training.calendar import TZ

API = "https://api.weather.gov"
# weather.gov asks clients to identify themselves; no personal address here.
USER_AGENT = "light-labs (github.com/kellypj24/light-labs)"
DAYTIME = (time(7, 0), time(19, 0))
MIN_TEMP_F, MIN_WIND_CHILL_F = 38, 32
ICE_PRECIP_PCT, ICE_TEMP_F = 50, 34
_LOCATION = re.compile(r"^- Location:\s*(-?\d+(?:\.\d+)?),\s*(-?\d+(?:\.\d+)?)", re.MULTILINE)
_DURATION = re.compile(r"^P(?:(\d+)D)?(?:T(?:(\d+)H)?(?:(\d+)M)?)?$")


def location(goals=None):
    text = Path(goals or config.VAR / "training" / "goals.md").read_text()
    m = _LOCATION.search(text)
    if not m:
        raise LookupError("no '- Location: <lat>, <lon>' line in goals.md")
    return float(m.group(1)), float(m.group(2))


def _get(url, opener=urllib.request.urlopen):
    req = urllib.request.Request(
        url, headers={"User-Agent": USER_AGENT, "Accept": "application/geo+json"}
    )
    with opener(req, timeout=30) as r:
        return json.loads(r.read().decode())


def _f(value, uom):
    if value is None:
        return None
    return value * 9 / 5 + 32 if uom.endswith("degC") else value


def hourly(series, uom_default="wmoUnit:degC", convert=True):
    """{local hour datetime: value} from a grid series of '<start>/<ISO duration>' values."""
    uom = series.get("uom", uom_default)
    out = {}
    for v in series.get("values", []):
        start_text, _, dur = v["validTime"].partition("/")
        m = _DURATION.match(dur)
        if not m:
            raise ValueError(f"unreadable duration {dur!r}")
        d, h, mins = (int(g or 0) for g in m.groups())
        hours = max(1, d * 24 + h + (1 if mins else 0))
        start = datetime.fromisoformat(start_text).astimezone(TZ)
        value = _f(v["value"], uom) if convert else v["value"]
        for i in range(hours):
            out[start + timedelta(hours=i)] = value
    return out


def outdoor_hour(temp_f, wind_chill_f, precip_pct):
    """One hour against PJ's rule. Unknown temperature is None, not False."""
    if temp_f is None:
        return None
    if temp_f < MIN_TEMP_F:
        return False
    if wind_chill_f is not None and wind_chill_f < MIN_WIND_CHILL_F:
        return False
    return not (precip_pct is not None and precip_pct >= ICE_PRECIP_PCT and temp_f <= ICE_TEMP_F)


def _windows(hours):
    """Consecutive hours → [["12:00", "17:00"], ...] (end is the last hour + 1)."""
    out = []
    for h in sorted(hours):
        if out and out[-1][1] == h:
            out[-1][1] = h + timedelta(hours=1)
        else:
            out.append([h, h + timedelta(hours=1)])
    return [[a.strftime("%H:%M"), b.strftime("%H:%M")] for a, b in out]


def daily(grid, days):
    """{date: {...}} for each of `days`; days past the forecast are None."""
    props = grid["properties"]
    temp = hourly(props["temperature"])
    chill = hourly(props.get("windChill", {}))
    rain = hourly(props.get("probabilityOfPrecipitation", {}), convert=False)
    out = {}
    for day in days:
        hours = [h for h in temp if h.date() == day]
        if not hours:
            out[day] = None
            continue
        daytime = [h for h in hours if DAYTIME[0] <= h.time() < DAYTIME[1]] or hours

        def pick(series, hs, fn):
            vals = [series[h] for h in hs if series.get(h) is not None]
            return round(fn(vals)) if vals else None

        good = [h for h in daytime if outdoor_hour(temp[h], chill.get(h), rain.get(h))]
        out[day] = {
            "low_f": pick(temp, hours, min),
            "daytime_min_f": pick(temp, daytime, min),
            "daytime_max_f": pick(temp, daytime, max),
            "wind_chill_min_f": pick(chill, daytime, min),
            "precip_max_pct": pick(rain, daytime, max),
            "outdoor_windows": _windows(good),
            "outdoor_ok": bool(good),
        }
    return out


def fetch_grid(lat, lon, opener=urllib.request.urlopen):
    point = _get(f"{API}/points/{lat:.4f},{lon:.4f}", opener)
    return _get(point["properties"]["forecastGridData"], opener)

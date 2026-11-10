import io
import json
import tempfile
import unittest
from datetime import date, datetime, time, timedelta
from pathlib import Path

from light_labs.core import google
from light_labs.training import calendar, context, weather

TZ = calendar.TZ
MON = date(2026, 11, 16)


def at(day, hh, mm=0):
    return datetime.combine(day, time(hh, mm), TZ).isoformat()


class FreeWindowsTest(unittest.TestCase):
    def test_gaps_between_busy_blocks_from_both_calendars(self):
        busy = [
            (at(MON, 7, 30), at(MON, 12)),  # work
            (at(MON, 11), at(MON, 13)),  # family, overlapping
            (at(MON, 17), at(MON, 17, 30)),  # too short a gap before it? 13:00-17:00 is free
        ]
        free = calendar.free_windows(busy, [MON])[MON]
        self.assertEqual(
            [(a.strftime("%H:%M"), b.strftime("%H:%M")) for a, b in free],
            [("05:00", "07:30"), ("13:00", "17:00"), ("17:30", "21:00")],
        )

    def test_short_gaps_and_all_day_events(self):
        tue = MON + timedelta(days=1)
        busy = [
            (at(MON, 5, 30), at(MON, 21)),  # 30 min at dawn: under 45, dropped
            (
                datetime.combine(tue, time(0), TZ).isoformat(),
                (datetime.combine(tue, time(0), TZ) + timedelta(days=1)).isoformat(),
            ),
        ]
        free = calendar.free_windows(busy, [MON, tue])
        self.assertEqual(free, {MON: [], tue: []})

    def test_utc_blocks_are_read_in_local_time(self):
        free = calendar.free_windows([("2026-11-16T12:00:00Z", "2026-11-16T14:00:00Z")], [MON])
        self.assertEqual(free[MON][0][1].strftime("%H:%M"), "07:00")  # 12:00Z is 07:00 EST


class FakeCalendar:
    def __init__(self):
        self.asked = None

    def resolve(self, names):
        return ["primary" if n == "primary" else "fam@import.calendar.google.com" for n in names]

    def busy(self, ids, start, end):
        self.asked = (ids, start, end)
        return {i: [(at(MON, 8), at(MON, 9))] for i in ids}


class FetchBusyTest(unittest.TestCase):
    def test_one_query_over_the_named_calendars_for_seven_days(self):
        cal = FakeCalendar()
        busy = calendar.fetch_busy(MON, cal, ["primary", "Kelly family calendar"])
        ids, start, end = cal.asked
        self.assertEqual(ids, ["primary", "fam@import.calendar.google.com"])
        self.assertEqual(end - start, timedelta(days=7))
        self.assertEqual(len(busy), 2)


def grid(start_utc, hours, temp_c, chill_c=None, pop=0):
    def series(value, uom):
        return {"uom": uom, "values": [{"validTime": f"{start_utc}/PT{hours}H", "value": value}]}

    props = {
        "temperature": series(temp_c, "wmoUnit:degC"),
        "probabilityOfPrecipitation": series(pop, "wmoUnit:percent"),
    }
    if chill_c is not None:
        props["windChill"] = series(chill_c, "wmoUnit:degC")
    return {"properties": props}


class WeatherTest(unittest.TestCase):
    def test_outdoor_hour_rule(self):
        self.assertTrue(weather.outdoor_hour(45, 40, 10))
        self.assertFalse(weather.outdoor_hour(36, None, 0))  # below 38°F
        self.assertFalse(weather.outdoor_hour(40, 30, 0))  # wind chill below freezing
        self.assertTrue(weather.outdoor_hour(45, 40, 80))  # rain, not ice
        self.assertIsNone(weather.outdoor_hour(None, None, None))

    def test_daily_finds_the_runnable_window(self):
        # 33°F (0.5°C) until 16:00 UTC (11:00 local), then 45°F (7.2°C) through the day.
        g = {
            "properties": {
                "temperature": {
                    "uom": "wmoUnit:degC",
                    "values": [
                        {"validTime": "2026-11-16T05:00:00+00:00/PT11H", "value": 0.5},
                        {"validTime": "2026-11-16T16:00:00+00:00/PT13H", "value": 7.2},
                    ],
                },
                "windChill": {
                    "uom": "wmoUnit:degC",
                    "values": [{"validTime": "2026-11-16T05:00:00+00:00/PT24H", "value": 1}],
                },
            }
        }
        day = weather.daily(g, [MON, MON + timedelta(days=2)])
        self.assertEqual(day[MON]["outdoor_windows"], [["11:00", "19:00"]])
        self.assertTrue(day[MON]["outdoor_ok"])
        self.assertEqual((day[MON]["daytime_min_f"], day[MON]["daytime_max_f"]), (33, 45))
        self.assertIsNone(day[MON + timedelta(days=2)])  # past the forecast

    def test_a_cold_day_has_no_window(self):
        g = grid("2026-11-16T05:00:00+00:00", 24, temp_c=2, chill_c=-3)
        day = weather.daily(g, [MON])[MON]
        self.assertEqual((day["outdoor_ok"], day["outdoor_windows"]), (False, []))

    def test_location_from_goals(self):
        with tempfile.NamedTemporaryFile("w", suffix=".md", delete=False) as f:
            f.write("# Goals\n- Location: 40.0931, -83.0180\n")
        self.assertEqual(weather.location(f.name), (40.0931, -83.018))
        Path(f.name).unlink()

    def test_fetch_grid_identifies_the_client_without_personal_data(self):
        seen = []

        def opener(req, timeout=None):
            seen.append(req)
            body = (
                {"properties": {"forecastGridData": "https://api.weather.gov/gridpoints/ILN/1,2"}}
                if "/points/" in req.full_url
                else {"properties": {}}
            )
            return io.BytesIO(json.dumps(body).encode())

        weather.fetch_grid(40.0931, -83.018, opener)
        self.assertEqual(seen[0].full_url, "https://api.weather.gov/points/40.0931,-83.0180")
        self.assertNotIn("@", seen[0].get_header("User-agent"))


class ContextTest(unittest.TestCase):
    def test_default_week_is_the_next_monday(self):
        self.assertEqual(context.week_start(today=date(2026, 11, 15)), MON)  # Sunday
        self.assertEqual(context.week_start(today=MON), MON + timedelta(days=7))
        self.assertEqual(context.week_start("2026-W47"), MON)

    def test_build_and_write_hold_no_event_details(self):
        g = grid("2026-11-16T05:00:00+00:00", 48, temp_c=10)
        ctx = context.build(MON, [(at(MON, 7, 30), at(MON, 17))], g)
        self.assertEqual(ctx["week"], "2026-W47")
        self.assertEqual(ctx["days"][0]["free"], [["05:00", "07:30"], ["17:00", "21:00"]])
        self.assertTrue(ctx["days"][0]["weather"]["outdoor_ok"])
        self.assertIsNone(ctx["days"][6]["weather"])
        with tempfile.TemporaryDirectory() as tmp:
            path = context.write(ctx, tmp)
            self.assertEqual(path.name, "2026-W47.json")
            self.assertNotIn("summary", path.read_text())


class CalendarClientTest(unittest.TestCase):
    def setUp(self):
        self.calls = []

        def opener(req, timeout=None):
            self.calls.append(req)
            if req.full_url == "https://t":
                body = {"access_token": "AT"}
            elif "calendarList" in req.full_url:
                body = {
                    "items": [
                        {"id": "me@x", "summary": "me@x"},
                        {
                            "id": "fam@import.calendar.google.com",
                            "summary": "Kelly Family Calendar",
                        },
                    ]
                }
            else:
                body = {
                    "calendars": {
                        "primary": {"busy": [{"start": "a", "end": "b"}]},
                        "bad": {"errors": [{"reason": "notFound"}]},
                    }
                }
            return io.BytesIO(json.dumps(body).encode())

        def get(service):
            if service == google.CLIENT_KEYCHAIN:
                return json.dumps(
                    {
                        "installed": {
                            "client_id": "c",
                            "client_secret": "s",
                            "token_uri": "https://t",
                        }
                    }
                )
            return json.dumps({"refresh_token": "RT"})

        self.cal = google.Calendar("training", "me@x", get=get, opener=opener)

    def test_resolves_names_case_insensitively(self):
        ids = self.cal.resolve(["primary", "Kelly family calendar"])
        self.assertEqual(ids, ["primary", "fam@import.calendar.google.com"])
        with self.assertRaisesRegex(LookupError, "Work"):
            self.cal.resolve(["Work"])

    def test_unreadable_calendar_raises_rather_than_looking_free(self):
        with self.assertRaisesRegex(RuntimeError, "notFound"):
            self.cal.busy(
                ["primary", "bad"],
                datetime(2026, 11, 16, tzinfo=TZ),
                datetime(2026, 11, 23, tzinfo=TZ),
            )

    def test_training_scopes_never_read_events(self):
        scopes = google.SCOPES["training"]
        self.assertTrue(
            all(s.endswith(("calendar.freebusy", "calendar.calendarlist.readonly")) for s in scopes)
        )
        self.assertFalse([m for m in dir(google.Calendar) if "event" in m.lower()])


if __name__ == "__main__":
    unittest.main()

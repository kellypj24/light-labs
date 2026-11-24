import json
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest import mock

from light_labs.training import app as app_mod
from light_labs.training.app import App, handler

PJ = "pj@example.com"
MON, TUE, WED = "2026-11-23", "2026-11-24", "2026-11-25"
BENCH = {"exercise": "Bench <Press>", "sets": 3, "reps": 5, "load_lb": 47.5}
RIDE = {"text": "Warm-up 10 min easy"}
PLAN = {
    "glance": "Three sessions.",
    "days": [
        {"date": MON, "rest": False, "slot": ["06:30", "07:15"], "type": "lift",
         "outdoor": False, "title": "Mix 3A", "items": [BENCH], "why": "Eases back in."},
        {"date": TUE, "rest": False, "slot": None, "type": "bike", "outdoor": True,
         "title": "Bike", "items": [RIDE], "why": ""},
        {"date": WED, "rest": True, "slot": None, "type": "rest", "outdoor": False,
         "title": "Rest", "items": [], "why": "Rain."},
    ],
    "summary": {"total_minutes": 95, "split": "1 lift, 1 ride", "progressed": "", "cue": "Easy."},
}  # fmt: skip


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


class AppTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.var = Path(tmp.name)
        self.plans = self.var / "training" / "plans"
        self.plans.mkdir(parents=True)
        (self.plans / "2026-W48.json").write_text(json.dumps(PLAN))
        (self.plans / "2026-W48.md").write_text("# Week 3\n")
        self.replans, self.read = [], []
        self.app = App(
            allowed=[PJ],
            var=self.var,
            clock=lambda: datetime(2026, 11, 23, 19, 0),  # Monday evening
            parser=self.parse,
            planner=self.planner,
        )
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), handler(self.app))
        self.base = f"http://127.0.0.1:{self.server.server_port}"
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)

    def parse(self, text, today):
        self.read.append(text)
        return [{"kind": "sick", "date": today.isoformat(), "end_date": None, "start": None,
                 "end": None, "minutes": None, "effort": None, "done": False, "what": text}]  # fmt: skip

    def planner(self, week, from_date=None):
        self.replans.append(week)
        out = self.plans / f"{week}.md"
        out.write_text(f"# {week}\n\n**Mon**: lift\n")
        return out, []

    def call(self, path, form=None, login=PJ, headers=None):
        if form is not None:
            form = urllib.parse.urlencode({"token": self.app.token, **form}).encode()
        req = urllib.request.Request(self.base + path, data=form, headers=headers or {})
        if login:
            req.add_header("Tailscale-User-Login", login)
        try:
            with urllib.request.build_opener(NoRedirect).open(req) as r:
                return r.status, r.read().decode()
        except urllib.error.HTTPError as e:
            with e:
                return e.code, e.headers.get("Location") or e.read().decode()

    def settle(self):
        for _ in range(200):
            if not self.app.working.locked():
                return
            time.sleep(0.01)
        self.fail("the background job never finished")

    def tap(self, n, done=1, day=MON, item=BENCH, **kw):
        form = {"date": day, "item": app_mod.item_key(item), "n": n, "done": done}
        return self.call("/check", form, **kw)

    def test_it_opens_on_todays_session(self):
        code, body = self.call("/")
        self.assertEqual(code, 200)
        self.assertIn("<h1>Mix 3A</h1>", body)
        self.assertIn("Bench &lt;Press&gt;", body)
        self.assertIn("3 × 5 @ 47.5 lb", body)
        self.assertIn("Monday, Nov 23 · 06:30–07:15", body)
        self.assertIn("0 of 3 done", body)
        self.assertIn("Eases back in.", body)
        self.assertIn('class="chip today sel" href="/d/2026-11-23"', body)
        self.assertIn('class="chip rest" href="/d/2026-11-25"', body)
        self.assertIn("<title>Workouts</title>", body)
        self.assertNotIn("Rush", body)

    def test_it_needs_an_allowed_login_and_this_machines_host(self):
        self.assertEqual(self.call("/", login=None)[0], 403)
        self.assertEqual(self.call("/", login="someone@else.com")[0], 403)
        self.assertEqual(self.call("/", headers={"Host": "evil.example"})[0], 403)
        self.assertEqual(self.tap(1, login=None)[0], 403)

    def test_a_tap_checks_a_set_off_and_a_second_tap_undoes_it(self):
        code, body = self.tap(1, headers={"X-Workouts": "1"})
        self.assertEqual(
            (code, json.loads(body)), (200, {"done": 1, "total": 3, "text": "1 of 3 done"})
        )
        self.assertEqual(self.tap(2), (303, "/d/2026-11-23"))  # no script: back to the day
        self.tap(3)
        body = self.call("/d/" + MON)[1]
        self.assertIn("Session done", body)
        self.assertEqual(body.count('class="on"'), 3)
        self.assertIn('class="chip done today sel"', body)
        self.tap(3, done=0)
        self.assertIn("2 of 3 done", self.call("/")[1])
        log = (self.var / "training" / "checks.jsonl").read_text().splitlines()
        self.assertEqual(len(log), 4)  # append-only: the undoing is a line, not an edit

    def test_only_a_set_the_plan_has_can_be_checked(self):
        self.assertEqual(self.tap(4)[0], 400)
        self.assertEqual(self.tap(0)[0], 400)
        self.assertEqual(self.tap(1, day="2026-11-29")[0], 400)
        self.assertEqual(self.tap(1, day="soon")[0], 400)
        self.assertEqual(self.tap(1, item=RIDE)[0], 400)  # Tuesday's item, not Monday's
        self.assertEqual(self.tap("x")[0], 400)
        form = {"date": MON, "item": app_mod.item_key(BENCH), "n": 1, "done": 1, "token": "old"}
        self.assertEqual(self.call("/check", form)[0], 403)
        self.assertFalse((self.var / "training" / "checks.jsonl").exists())

    def test_other_days_and_weeks(self):
        body = self.call("/d/" + TUE)[1]
        self.assertIn("<h1>Bike</h1>", body)
        self.assertIn("Tuesday, Nov 24 · outdoor", body)
        self.assertIn(">Done</button>", body)
        body = self.call("/d/" + WED)[1]
        self.assertIn("<h1>Rest</h1>", body)
        self.assertIn("Rain.", body)
        self.assertIn("Nothing planned this day.", self.call("/d/2026-11-28")[1])
        body = self.call("/w/2026-W48")[1]  # holds today, so it opens there
        self.assertIn("<h1>Mix 3A</h1>", body)
        self.assertIn('href="/w/2026-W47">‹ W47</a>', body)
        self.assertIn('href="/w/2026-W49">W49 ›</a>', body)
        self.assertIn("No plan for 2026-W49 yet.", self.call("/w/2026-W49")[1])
        for bad in ("/w/2026-W99", "/d/2026-02-31", "/w/x", "/training"):
            self.assertEqual(self.call(bad)[0], 404, bad)

    def test_a_week_with_only_its_text_is_shown_as_text(self):
        history = self.var / "training" / "history"
        history.mkdir()
        (history / "2026-W46.md").write_text(
            "<!-- Imported -->\n# Week 1\n\n**Mon**: lift\n- Bench <5x5>\n- _easy_\n"
        )
        body = self.call("/w/2026-W46")[1]
        self.assertIn("<h3>Week 1</h3>", body)
        self.assertIn("<p><b>Mon</b>: lift</p>", body)
        self.assertIn("<ul>\n<li>Bench &lt;5x5&gt;</li>\n<li><i>easy</i></li>\n</ul>", body)
        self.assertNotIn("Imported", body)

    def test_a_note_is_read_and_shown_and_replans_only_when_asked(self):
        code, to = self.call("/note", {"action": "note", "text": "a cold", "back": "/d/" + TUE})
        self.assertEqual((code, to), (303, "/d/" + TUE))
        self.settle()
        self.assertEqual((self.read, self.replans), (["a cold"], []))
        self.assertIn("sick (a cold)", self.call("/")[1])
        self.call("/note", {"action": "replan", "text": "still sick", "back": "//evil.example"})
        self.settle()
        self.assertEqual((self.read, self.replans), (["a cold", "still sick"], ["2026-W48"]))
        body = self.call("/")[1]
        self.assertIn("Updated plan for the rest of the week:", body)
        self.assertNotIn("**Mon**", body)  # the outcome, not the plan's text
        self.call("/note", {"action": "undo"})
        self.settle()
        self.assertIn("Dropped: still sick", self.call("/")[1])

    def test_replan_without_a_note_and_an_empty_note(self):
        self.assertEqual(self.call("/note", {"action": "note", "text": "  "}), (303, "/"))
        self.settle()
        self.assertEqual(self.read, [])
        self.call("/note", {"action": "replan"})
        self.settle()
        self.assertEqual((self.read, self.replans), ([], ["2026-W48"]))

    def test_the_page_says_what_it_is_doing_and_takes_one_job_at_a_time(self):
        hold = threading.Event()
        self.assertTrue(self.app.start("Replanning", hold.wait))
        self.assertFalse(self.app.start("Again", hold.wait))
        body = self.call("/")[1]
        self.assertIn("Replanning…", body)
        self.assertIn('http-equiv="refresh"', body)
        self.assertNotIn("<textarea", body)
        hold.set()
        self.settle()
        self.assertNotIn('http-equiv="refresh"', self.call("/")[1])

    def test_a_failed_job_is_reported(self):
        def boom():
            raise RuntimeError("no free windows")

        with mock.patch("traceback.print_exc"):
            self.app.start("Replanning", boom)
            self.settle()
        self.assertIn("That failed: no free windows", self.call("/")[1])

    def test_icon_script_and_manifest(self):
        req = urllib.request.Request(self.base + "/icon.png")
        req.add_header("Tailscale-User-Login", PJ)
        with urllib.request.urlopen(req) as r:
            self.assertEqual(r.headers["Content-Type"], "image/png")
            self.assertTrue(r.read().startswith(b"\x89PNG\r\n\x1a\n"))
        self.assertIn("X-Workouts", self.call("/app.js")[1])
        self.assertEqual(json.loads(self.call("/manifest.webmanifest")[1])["name"], "Workouts")


if __name__ == "__main__":
    unittest.main()

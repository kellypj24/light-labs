"""The dbt-model stage: Guts Man writes one dbt model; dbt builds it beside a reference.

Each sample:
1. `prepare()` builds the analytics project once over a seeded synthetic dataset (never
   the lab's real results) and caches the DuckDB file, keyed by the project's contents.
2. The robot gets the task and the upstream models' columns, and writes the model's SQL.
3. A throwaway copy of the project and database gets two models: the candidate
   (`<target>`) and the fixture's reference (`ref__<target>`). `dbt build` builds both.
4. The result sets are compared: same column names, same rows (any order, floats rounded).

The Go side scores the returned flags; nothing here judges. The mock contestant answers
with the reference SQL, so a mock run proves every reference builds and scores 100%.
"""

import datetime as dt
import decimal
import fcntl
import hashlib
import json
import os
import random
import shutil
import tempfile
from pathlib import Path

from light_labs import config

PROJECT = config.REPO / "analytics"
CACHE = config.VAR / "evals" / "cache"
DATA_VERSION = "3"  # bump when synthetic_samples() changes

# DuckDB may not read or write files outside its database during a fight: candidate SQL
# comes from a model.
PROFILE = """light_labs:
  target: duckdb
  outputs:
    duckdb:
      type: duckdb
      path: "{{ env_var('DUCKDB_PATH') }}"
      threads: 1
      settings:
        enable_external_access: false
"""


# --- synthetic data ------------------------------------------------------------------

STAGES = {
    "reply-draft": [
        ("chat_welcome", "chat"),
        ("chat_joke", "chat"),
        ("chat_thanks", "chat"),
        ("question_model", "question"),
        ("question_status", "question"),
        ("question_owner", "question"),
        ("work_script", "work"),
        ("work_review", "work"),
        ("work_benchmark", "work"),
        ("decision_v3", "decision"),
        ("decision_deadline", "decision"),
        ("decision_join", "decision"),
    ],
    "summarize": [
        ("short_note", "short"),
        ("short_thread", "short"),
        ("short_digest", "short"),
        ("short_email", "short"),
        ("long_paper", "long"),
        ("long_meeting", "long"),
        ("long_report", "long"),
        ("long_transcript", "long"),
    ],
}

CONTESTANTS = {
    "megaman": ("megaman", "ollama:llama3.1:8b", 1.4, 0.0),
    "proto": ("proto", "ollama:gemma3:4b", 0.8, 0.0),
    "bass": ("bass", "claude:sonnet", 4.3, 0.0075),
}

# (stage, day, contestants with samples per fixture, commit, dirty, filter, base pass rate)
RUNS = [
    ("reply-draft", 1, {"megaman": 3, "proto": 3}, None, None, None, 0.62),
    ("reply-draft", 2, {"megaman": 3, "bass": 1}, "a1b2c3d", True, None, 0.75),
    ("reply-draft", 3, {"megaman": 2}, "b2c3d4e", False, "work", 0.70),
    ("reply-draft", 4, {"megaman": 3, "proto": 3, "bass": 1}, "c3d4e5f", False, None, 0.86),
    ("summarize", 2, {"megaman": 3, "proto": 3}, "a1b2c3d", True, None, 0.55),
    ("summarize", 5, {"megaman": 3, "bass": 1}, "d4e5f6a", False, None, 0.80),
]

SKILL = {"megaman": 0.0, "proto": -0.25, "bass": 0.3}
HARDNESS = {"chat": 0.1, "question": 0.05, "work": -0.1, "decision": -0.2, "short": 0.05}


def synthetic_samples(seed=101):
    """Eval-runner JSONL rows (one dict per sample), deterministic for a seed."""
    rng = random.Random(seed)
    rows = []
    for stage, day, contestants, commit, dirty, filt, base in RUNS:
        # Midday UTC keeps the calendar date the same in any US or European time zone;
        # stages start at different hours so no two runs tie on started_at.
        hour = 12 if stage == "reply-draft" else 15
        start = dt.datetime(2026, 9, day, hour, 0, tzinfo=dt.UTC)
        run_id = f"{stage}-{start:%Y%m%dT%H%M%SZ}"
        fixtures = [f for f in STAGES[stage] if not filt or filt in f[0]]
        offset = 0
        for name, n_samples in contestants.items():
            role, brain, latency, cost = CONTESTANTS[name]
            for fixture, category in fixtures:
                for n in range(1, n_samples + 1):
                    offset += 7
                    p = base + SKILL[name] + HARDNESS.get(category, -0.05)
                    # Bass never errors, so "brains with no harness errors" is not empty.
                    row = _sample(rng, p, category, latency, cost, can_error=name != "bass")
                    row.update(
                        run_id=run_id,
                        contestant=name,
                        role=role,
                        brain=brain,
                        stage=stage,
                        fixture=fixture,
                        category=category,
                        sample=n,
                        at=(start + dt.timedelta(seconds=offset)).isoformat(),
                    )
                    if commit:
                        row.update(commit=commit, dirty=dirty)
                    if filt:
                        row["filter"] = filt
                    if name == "bass":
                        row["isolated"] = False
                    rows.append(row)
    return rows


def _sample(rng, p, category, latency, cost, can_error=True):
    if rng.random() < 0.03 and can_error:
        return {
            "passed": False,
            "checks": [{"name": "ran", "passed": False, "detail": "timeout after 300s"}],
            "draft": "",
            "latency_s": 300.0,
            "cost_usd": 0,
            "error": "timeout after 300s",
        }
    wants_escalation = category in ("work", "decision")
    passed = rng.random() < min(max(p, 0.02), 0.98)
    names = ["escalate", "max_chars", "must_not_match", "must_not_match"]
    if category == "question":
        names.append("contains_any")
    failing = None if passed else rng.choice(names)
    checks = [{"name": "ran", "passed": True}]
    for i, name in enumerate(names):
        ok = not (failing == name and (name != "must_not_match" or i == 3))
        detail = (
            ""
            if ok
            else {"escalate": "want true, got false", "max_chars": "1210 > 900"}.get(
                name, "Here's the draft"
            )
        )
        checks.append({"name": name, "passed": ok, "detail": detail})
    escalated = wants_escalation != (failing == "escalate")
    words = rng.randint(8, 1300 if failing == "max_chars" else 160)
    return {
        "passed": passed,
        "checks": checks,
        "draft": " ".join(["word"] * words)[: 1210 if failing == "max_chars" else None],
        "escalate": "do the work" if escalated else "",
        "latency_s": round(max(0.2, rng.gauss(latency, latency / 4)), 3),
        "cost_usd": cost,
    }


# --- project and database ------------------------------------------------------------


def _fingerprint():
    h = hashlib.sha256(DATA_VERSION.encode())
    for path in sorted(PROJECT.rglob("*")):
        if path.is_file() and path.suffix in (".sql", ".yml") and "target" not in path.parts:
            h.update(str(path.relative_to(PROJECT)).encode())
            h.update(path.read_bytes())
    return h.hexdigest()[:16]


def copy_project(dest):
    """The analytics project, without build output, with the sandboxed profile."""
    shutil.copytree(
        PROJECT,
        dest,
        ignore=shutil.ignore_patterns("target", "logs", "dbt_packages", "fixtures", ".user.yml"),
    )
    (Path(dest) / "profiles.yml").write_text(PROFILE)
    return Path(dest)


def dbt(project, db, *args):
    """Run dbt in-process against `db`; returns dbt's result object."""
    from dbt.adapters.duckdb.connections import DuckDBConnectionManager
    from dbt.cli.main import dbtRunner

    os.environ["DUCKDB_PATH"] = str(db)
    try:
        return _invoke(dbtRunner(), project, args)
    finally:
        # dbt-duckdb caches one database per process; without this the next call
        # reuses it, and a second file also named lab.duckdb cannot be opened.
        DuckDBConnectionManager.close_all_connections()


def _invoke(runner, project, args):
    return runner.invoke(
        [
            *args,
            "--project-dir",
            str(project),
            "--profiles-dir",
            str(project),
            "--target-path",
            str(Path(project) / "target"),
            "--log-path",
            str(Path(project) / "logs"),
            "--quiet",
        ]
    )


def prepare():
    """Path to the cached database: synthetic raw data plus the built project."""
    from light_labs.evals import results

    CACHE.mkdir(parents=True, exist_ok=True)
    # Always named lab.duckdb: DuckDB names the catalog after the file, and dbt-duckdb's
    # views refer to "lab"."raw"... by that name.
    db = CACHE / f"dbt-model-{_fingerprint()}" / "lab.duckdb"
    with open(CACHE / "dbt-model.lock", "w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        if db.exists():
            return db
        with tempfile.TemporaryDirectory() as tmp:
            data = Path(tmp) / "synthetic.jsonl"
            data.write_text("".join(json.dumps(r) + "\n" for r in synthetic_samples()))
            building = Path(tmp) / "lab.duckdb"
            results.ingest([data], db=building)
            res = dbt(copy_project(Path(tmp) / "project"), building, "build")
            if not res.success:
                failed = [
                    f"{r.node.name}: {r.message}"
                    for r in getattr(res.result, "results", None) or []
                    if str(r.status) in ("error", "fail")
                ]
                raise RuntimeError(f"building the eval database failed: {failed or res.exception}")
            db.parent.mkdir(exist_ok=True)
            shutil.move(building, db)
    return db


# --- schema context ------------------------------------------------------------------


def upstream_context(db, names):
    """Columns and types from the database, descriptions from the models' .yml files."""
    import duckdb
    import yaml

    docs = {}
    for path in PROJECT.glob("models/**/*.yml"):
        for model in (yaml.safe_load(path.read_text()) or {}).get("models", []):
            docs[model["name"]] = model
    out = []
    with duckdb.connect(str(db), read_only=True) as con:
        for name in names:
            doc = docs.get(name, {})
            col_docs = {c["name"]: c.get("description", "") for c in doc.get("columns", [])}
            cols = con.execute(
                "SELECT column_name, data_type FROM information_schema.columns "
                "WHERE table_name = ? ORDER BY ordinal_position",
                [name],
            ).fetchall()
            if not cols:
                raise ValueError(f"upstream model {name} is not in the eval database")
            out.append(
                {
                    "name": name,
                    "description": (doc.get("description") or "").strip(),
                    "columns": [
                        {"name": c, "type": t, "description": col_docs.get(c, "")} for c, t in cols
                    ],
                }
            )
    return out


# --- comparison ----------------------------------------------------------------------


def _norm(value):
    if isinstance(value, (float, decimal.Decimal)):
        return round(float(value), 6)
    if isinstance(value, (dt.date, dt.datetime)):
        return value.isoformat()
    return value


def compare(db, candidate, reference):
    """(columns_match, rows_match, note) for two relations in `db`."""
    import duckdb

    with duckdb.connect(str(db), read_only=True) as con:
        want = con.execute(f'SELECT * FROM "{reference}"')
        want_cols = [d[0].lower() for d in want.description]
        want_rows = want.fetchall()
        got = con.execute(f'SELECT * FROM "{candidate}"')
        got_cols = [d[0].lower() for d in got.description]
        got_rows = got.fetchall()
    if sorted(got_cols) != sorted(want_cols):
        missing = sorted(set(want_cols) - set(got_cols))
        extra = sorted(set(got_cols) - set(want_cols))
        return False, False, f"columns: missing {missing}, extra {extra}"
    order = [got_cols.index(c) for c in want_cols]

    def key(rows, idx=None):
        normed = [tuple(_norm(r[i]) for i in (idx or range(len(r)))) for r in rows]
        return sorted(normed, key=repr)

    if key(got_rows, order) == key(want_rows):
        return True, True, f"{len(got_rows)} rows match"
    return True, False, f"rows differ: got {len(got_rows)}, want {len(want_rows)}"


# --- one sample ----------------------------------------------------------------------


def run_sample(brain, inp):
    """Guts Man writes `inp["target"]`; returns the envelope result with check flags."""
    from light_labs.agents import guts_man
    from light_labs.agents.guts_man.builder import extract_sql, model_prompt
    from light_labs.core.brain import Mock

    target, reference = inp["target"], inp["reference"].strip()
    db = prepare()
    user = model_prompt(target, inp["task"], upstream_context(db, inp["upstream"]))
    if isinstance(brain, Mock):  # the oracle: proves the reference and the harness
        raw = reference
        brain.last = {"latency_s": 0.0, "input_tokens": 0, "output_tokens": 0, "cost_usd": 0.0}
    else:
        raw = brain.think(guts_man.system_prompt(user), user)
    sql = extract_sql(raw)
    flags = {"sql": bool(sql), "builds": False, "columns": False, "rows": False}
    result = {"raw": raw, "draft": sql, "flags": flags, "notes": ""}
    if not sql:
        result["notes"] = "no SQL in the output"
        return result

    with tempfile.TemporaryDirectory() as tmp:
        project = copy_project(Path(tmp) / "project")
        models = project / "models" / "eval"
        models.mkdir()
        (models / f"ref__{target}.sql").write_text(reference + "\n")
        (models / f"{target}.sql").write_text(sql + "\n")
        sandbox = Path(tmp) / "lab.duckdb"
        shutil.copy(db, sandbox)
        res = dbt(project, sandbox, "build", "--select", f"{target} ref__{target}")
        status = {}
        for node in getattr(res.result, "results", None) or []:
            status[node.node.name] = (str(node.status), node.message or "")
        if not status:
            # Nothing ran: the candidate broke parsing (the mock run proves references parse).
            result["notes"] = f"dbt could not parse the project: {res.exception}"[:500]
            return result
        ref_status = status.get(f"ref__{target}", ("missing", ""))
        if ref_status[0] != "success":
            raise RuntimeError(f"reference for {target} did not build: {ref_status[1]}")
        cand_status = status.get(target, ("missing", ""))
        if cand_status[0] != "success":
            result["notes"] = f"dbt build failed: {cand_status[1]}"[:500]
            return result
        flags["builds"] = True
        flags["columns"], flags["rows"], result["notes"] = compare(
            sandbox, target, f"ref__{target}"
        )
    return result

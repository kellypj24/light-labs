"""Calibrated confidence for typed decisions: a fitted map per brain and question.

docs/plans/decision-framework.md step 2. A shadow pair is one local yes/no answer's raw
probability and the label it should have had (Claude's verdict, or a ground truth such as
a PR title's type). Per (robot, question, brain): Platt scaling below PLATT_MAX pairs,
isotonic regression from there, kept only when it beats the raw probability on held-out
Brier score; otherwise, or below MIN_PAIRS, the identity. Weights never change.

Pairs come from files under var/ (`collect`); the Dagster asset `calibration` lands them
and the maps in DuckDB and exports the maps to var/calibration/maps.json, which robots
read (`lookup`): a robot never opens the DuckDB file Dagster writes.

Fitting needs scikit-learn (the analytics group); applying a map is plain Python.
"""

import bisect
import glob
import json
import math
import os
import re
from datetime import UTC, datetime
from pathlib import Path

from light_labs import config

STAGES = config.REPO / "evals" / "stages"
MIN_PAIRS = 30  # below this, the identity: too few to say anything
PLATT_MAX = 200
FOLDS = 5
BINS = 10
EPS = 1e-6


# --- pairs


def collect(var=None):
    """Every shadow pair under `var`: dicts with robot, question, brain, p, label,
    source_id, label_by, at. Pair files are var/<robot>/pairs/*.jsonl; Roll's Dependabot
    decisions are read from her queue (Roll's raw p_yes against Claude's verdict)."""
    var = Path(var or config.VAR)
    pairs = []
    for path in sorted(glob.glob(str(var / "*" / "pairs" / "*.jsonl"))):
        pairs += [json.loads(line) for line in Path(path).read_text().splitlines() if line]
    pairs += chores_pairs(var)
    return pairs


def fixture_ids(stage):
    """Fixture ids in an eval stage, so a robot is never calibrated on what it is scored on."""
    path = STAGES / f"{stage}.yaml"
    return (
        set(re.findall(r'^\s*- \{"id": "([^"]+)"', path.read_text(), re.MULTILINE))
        if path.exists()
        else set()
    )


def chores_pairs(var):
    """Roll's answer on each Dependabot PR she was asked about, labelled by Claude's
    MERGE or HOLD. Items queued before the brain was recorded have brain None; the same PR
    decided again after a rebase is its own pair (a new head). PRs that are
    dependabot-merge fixtures are left out."""
    scored = fixture_ids("dependabot-merge")
    out = []
    for path in sorted((Path(var) / "roll" / "queue").glob("*/*.json")):
        item = json.loads(path.read_text())
        roll, bb = item.get("roll"), item.get("big_brother") or {}
        if (
            item.get("kind") != "dependabot"
            or not roll
            or bb.get("verdict") not in ("MERGE", "HOLD")
        ):
            continue
        t = item.get("target") or {}
        if (
            re.sub(r"\W+", "_", f"{t.get('repo', '').split('/')[-1]}_{t.get('pr')}").lower()
            in scored
        ):
            continue
        out.append({
            "robot": "roll",
            "question": "chores-merge",
            "brain": roll.get("brain"),
            "p": roll.get("p_raw", roll["p_yes"]),
            "label": bb["verdict"] == "MERGE",
            "source_id": f"{t.get('repo')}#{t.get('pr')}@{(t.get('head') or '')[:7]}",
            "label_by": f"claude:{bb['model']}" if bb.get("model") else "claude",
            "at": item.get("created"),
        })  # fmt: skip
    return out


# --- fitting


def _logit(p):
    p = min(max(p, EPS), 1 - EPS)
    return math.log(p / (1 - p))


def brier(ps, ys):
    return sum((p - y) ** 2 for p, y in zip(ps, ys, strict=True)) / len(ps)


def ece(ps, ys, bins=BINS):
    """Expected calibration error: |mean p - hit rate| per equal-width bin, weighted."""
    total, n = 0.0, len(ps)
    for b in range(bins):
        lo, hi = b / bins, (b + 1) / bins
        idx = [i for i, p in enumerate(ps) if lo <= p < hi or (b == bins - 1 and p == 1.0)]
        if idx:
            gap = sum(ps[i] for i in idx) / len(idx) - sum(ys[i] for i in idx) / len(idx)
            total += abs(gap) * len(idx) / n
    return total


def _fit_one(method, ps, ys):
    if method == "platt":
        from sklearn.linear_model import LogisticRegression

        m = LogisticRegression(C=1e6).fit([[_logit(p)] for p in ps], ys)
        return {"method": "platt", "a": float(m.coef_[0][0]), "b": float(m.intercept_[0])}
    from sklearn.isotonic import IsotonicRegression

    m = IsotonicRegression(y_min=0.0, y_max=1.0, out_of_bounds="clip").fit(ps, ys)
    return {
        "method": "isotonic",
        "x": [float(x) for x in m.X_thresholds_],
        "y": [float(y) for y in m.y_thresholds_],
    }


def fit(ps, ys):
    """A map for one question and brain, with the numbers that chose it."""
    ys = [int(bool(y)) for y in ys]
    n, pos = len(ys), sum(ys)
    out = {"n": n, "positives": pos, "brier_raw": brier(ps, ys), "ece_raw": ece(ps, ys)}
    if n < MIN_PAIRS or pos in (0, n):
        why = "too-few" if n < MIN_PAIRS else "one-class"
        return {**out, "method": "identity", "status": why, "brier_cal": None, "ece_cal": None}
    method = "platt" if n < PLATT_MAX else "isotonic"
    # Held-out: each fold's map scores the pairs it never saw.
    held = [None] * n
    for k in range(FOLDS):
        train = [i for i in range(n) if i % FOLDS != k]
        tys = [ys[i] for i in train]
        m = _fit_one(method, [ps[i] for i in train], tys) if 0 < sum(tys) < len(tys) else None
        for i in range(k, n, FOLDS):
            held[i] = apply(m, ps[i])
    out.update(brier_cal=brier(held, ys), ece_cal=ece(held, ys))
    if out["brier_cal"] >= out["brier_raw"]:
        return {**out, "method": "identity", "status": "no-gain"}
    return {**out, **_fit_one(method, ps, ys), "status": "fitted"}


def apply(m, p):
    """The calibrated probability for raw `p` under map `m` (None or identity: `p`)."""
    if not m or m.get("method") in (None, "identity"):
        return p
    if m["method"] == "platt":
        return 1 / (1 + math.exp(-(m["a"] * _logit(p) + m["b"])))
    xs, ys = m["x"], m["y"]
    if p <= xs[0]:
        return ys[0]
    if p >= xs[-1]:
        return ys[-1]
    i = bisect.bisect_right(xs, p)
    x0, x1, y0, y1 = xs[i - 1], xs[i], ys[i - 1], ys[i]
    return y0 if x1 == x0 else y0 + (y1 - y0) * (p - x0) / (x1 - x0)


def fit_all(pairs):
    """One map per (robot, question, brain) with a recorded brain."""
    groups = {}
    for pr in pairs:
        if pr.get("brain"):
            groups.setdefault((pr["robot"], pr["question"], pr["brain"]), []).append(pr)
    built = datetime.now(UTC).isoformat(timespec="seconds")
    maps = []
    for (robot, question, brain), group in sorted(groups.items()):
        m = fit([g["p"] for g in group], [g["label"] for g in group])
        maps.append({"robot": robot, "question": question, "brain": brain, "built": built, **m})
    return maps


# --- robots' side


MAPS = None


def maps_path():
    return config.VAR / "calibration" / "maps.json"


def export(maps, path=None):
    """Write the maps robots read, atomically."""
    path = Path(path or maps_path())
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(maps, indent=2) + "\n")
    os.replace(tmp, path)


def lookup(brain, question):
    """The fitted map for `brain` (a spec, e.g. ollama:qwen2.5:14b) and `question`, or None."""
    global MAPS
    path = maps_path()
    stamp = path.stat().st_mtime_ns if path.exists() else None
    if MAPS is None or MAPS[0] != (path, stamp):
        rows = json.loads(path.read_text()) if stamp else []
        MAPS = ((path, stamp), {(r["brain"], r["question"]): r for r in rows})
    return MAPS[1].get((brain, question))

"""Shadow pairs and calibration maps in DuckDB: `raw.shadow_pairs`, `raw.calibration_maps`.

The pair files and queues under var/ stay the source of truth (core/calibrate.py
`collect`). `ingest` reloads the pairs in full, fits every map, lands both, and exports
the maps to var/calibration/maps.json for robots to read. Needs scikit-learn (the
analytics group).
"""

import json
from pathlib import Path

from light_labs import config
from light_labs.core import calibrate
from light_labs.evals import results

SCHEMA = """
CREATE SCHEMA IF NOT EXISTS raw;
CREATE TABLE IF NOT EXISTS raw.shadow_pairs (
    robot VARCHAR NOT NULL,
    question VARCHAR NOT NULL,
    brain VARCHAR,
    p DOUBLE NOT NULL,
    label BOOLEAN NOT NULL,
    source_id VARCHAR,
    label_by VARCHAR,
    "at" VARCHAR
);
CREATE TABLE IF NOT EXISTS raw.calibration_maps (
    robot VARCHAR NOT NULL,
    question VARCHAR NOT NULL,
    brain VARCHAR NOT NULL,
    built VARCHAR NOT NULL,
    method VARCHAR NOT NULL,
    status VARCHAR NOT NULL,
    n INTEGER NOT NULL,
    positives INTEGER NOT NULL,
    brier_raw DOUBLE,
    brier_cal DOUBLE,
    ece_raw DOUBLE,
    ece_cal DOUBLE,
    params JSON
);
"""

PAIR_COLUMNS = ["robot", "question", "brain", "p", "label", "source_id", "label_by", "at"]
MAP_COLUMNS = ["robot", "question", "brain", "built", "method", "status", "n", "positives",
               "brier_raw", "brier_cal", "ece_raw", "ece_cal"]  # fmt: skip


def ingest(root=None, db=None, export=True):
    """Reload raw.shadow_pairs and raw.calibration_maps; export maps.json unless told not
    to (a throwaway database must not replace the maps robots read).
    Returns (pairs, maps fitted)."""
    root = Path(root or config.VAR)
    pairs = calibrate.collect(root)
    maps = calibrate.fit_all(pairs)
    with results.connect(db) as con:
        con.execute(SCHEMA)
        con.execute("BEGIN")
        con.execute("DELETE FROM raw.shadow_pairs")
        con.execute("DELETE FROM raw.calibration_maps")
        if pairs:
            con.executemany(
                f"INSERT INTO raw.shadow_pairs VALUES ({', '.join('?' for _ in PAIR_COLUMNS)})",
                [tuple(p.get(c) for c in PAIR_COLUMNS) for p in pairs],
            )
        if maps:
            con.executemany(
                f"INSERT INTO raw.calibration_maps VALUES ({', '.join('?' * (len(MAP_COLUMNS) + 1))})",
                [
                    (*(m.get(c) for c in MAP_COLUMNS),
                     json.dumps({k: m[k] for k in ("a", "b", "x", "y") if k in m}))
                    for m in maps
                ],
            )  # fmt: skip
        con.execute("COMMIT")
    if export:
        calibrate.export(maps)  # var/calibration/maps.json, wherever the pairs came from
    return len(pairs), sum(m["status"] == "fitted" for m in maps)

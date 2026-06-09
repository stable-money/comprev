"""Export the file-based reports under out/ into a SQLite database.

comprev has no database — verdicts are stored as out/<video_id>.json. This
flattens them into a relational SQLite file (reports / check_results / evidence)
so they can be browsed and queried in DBeaver (or any SQLite client).

Usage:
    python scripts/export_sqlite.py            # writes comprev.sqlite at repo root
    python scripts/export_sqlite.py path.db    # custom output path

Re-run any time after new reviews — it rebuilds from scratch (idempotent).
"""

from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
OUT_ROOT = REPO_ROOT / "out"

SCHEMA = """
DROP TABLE IF EXISTS evidence;
DROP TABLE IF EXISTS check_results;
DROP TABLE IF EXISTS reports;

CREATE TABLE reports (
    video_id           TEXT PRIMARY KEY,
    product            TEXT,
    duration_seconds   REAL,
    overall_status     TEXT,
    needs_human_review INTEGER,
    n_checks           INTEGER,
    review_reasons     TEXT,   -- JSON array
    modified_at        REAL
);

CREATE TABLE check_results (
    id                    INTEGER PRIMARY KEY AUTOINCREMENT,
    video_id              TEXT REFERENCES reports(video_id),
    check_id              TEXT,
    status                TEXT,
    severity              TEXT,
    confidence            REAL,
    surfaces_evaluated    TEXT,   -- JSON array
    reasoning             TEXT,
    policy_ref            TEXT,
    low_confidence_inputs INTEGER,
    not_applicable        INTEGER
);

CREATE TABLE evidence (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    video_id       TEXT,
    check_id       TEXT,
    surface        TEXT,
    timestamp      TEXT,
    frame_index    INTEGER,
    quote          TEXT,
    ocr_confidence REAL,
    asr_confidence REAL
);

CREATE INDEX idx_checks_video  ON check_results(video_id);
CREATE INDEX idx_checks_status ON check_results(status);
CREATE INDEX idx_evidence_video ON evidence(video_id);
"""


def main() -> None:
    db_path = Path(sys.argv[1]) if len(sys.argv) > 1 else REPO_ROOT / "comprev.sqlite"
    conn = sqlite3.connect(db_path)
    conn.executescript(SCHEMA)

    n_reports = n_checks = n_evidence = 0
    for path in sorted(OUT_ROOT.glob("*.json")):
        try:
            data = json.loads(path.read_text())
        except (json.JSONDecodeError, OSError):
            continue
        if "overall_status" not in data:  # skip non-report json
            continue

        video_id = data.get("video_id", path.stem)
        checks = data.get("checks", [])
        conn.execute(
            "INSERT OR REPLACE INTO reports VALUES (?,?,?,?,?,?,?,?)",
            (
                video_id,
                data.get("product"),
                data.get("duration_seconds"),
                data.get("overall_status"),
                int(bool(data.get("needs_human_review"))),
                len(checks),
                json.dumps(data.get("review_reasons", [])),
                path.stat().st_mtime,
            ),
        )
        n_reports += 1

        for c in checks:
            conn.execute(
                "INSERT INTO check_results (video_id, check_id, status, severity, "
                "confidence, surfaces_evaluated, reasoning, policy_ref, "
                "low_confidence_inputs, not_applicable) VALUES (?,?,?,?,?,?,?,?,?,?)",
                (
                    video_id,
                    c.get("check_id"),
                    c.get("status"),
                    c.get("severity"),
                    c.get("confidence"),
                    json.dumps(c.get("surfaces_evaluated", [])),
                    c.get("reasoning"),
                    c.get("policy_ref"),
                    int(bool(c.get("low_confidence_inputs"))),
                    int(bool(c.get("not_applicable"))),
                ),
            )
            n_checks += 1

            for e in c.get("evidence", []) or []:
                conn.execute(
                    "INSERT INTO evidence (video_id, check_id, surface, timestamp, "
                    "frame_index, quote, ocr_confidence, asr_confidence) "
                    "VALUES (?,?,?,?,?,?,?,?)",
                    (
                        video_id,
                        c.get("check_id"),
                        e.get("surface"),
                        e.get("timestamp"),
                        e.get("frame_index"),
                        e.get("quote"),
                        e.get("ocr_confidence"),
                        e.get("asr_confidence"),
                    ),
                )
                n_evidence += 1

    conn.commit()
    conn.close()
    print(
        f"Wrote {db_path}\n"
        f"  reports={n_reports}  check_results={n_checks}  evidence={n_evidence}"
    )


if __name__ == "__main__":
    main()

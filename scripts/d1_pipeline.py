#!/usr/bin/env python3
"""Read and write the pipeline results in D1 (tables in db/schema.sql).

Used by scripts/build_site_data.py; runs SQL through wrangler, so it needs
wrangler on PATH (or WRANGLER="npx --yes wrangler@4") and, for --remote,
CLOUDFLARE_API_TOKEN / CLOUDFLARE_ACCOUNT_ID or a `wrangler login`.

    python scripts/d1_pipeline.py list [--local]
    python scripts/d1_pipeline.py import-json DIR [--local]   # DIR/<key>.json files
"""

from __future__ import annotations

import argparse
import json
import os
import shlex
import shutil
import subprocess
import tempfile
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATABASE = "pulse_api"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _lit(v) -> str:
    if v is None:
        return "NULL"
    if isinstance(v, bool):
        return "1" if v else "0"
    if isinstance(v, (int, float)):
        return repr(v)
    if not isinstance(v, str):
        v = json.dumps(v, ensure_ascii=False, separators=(",", ":"))
    return "'" + v.replace("'", "''") + "'"


def event_statements(key: str, summary: dict, updated: str | None = None) -> list[str]:
    """SQL replacing one event and its records.  `summary` is what
    waveform.site_export.event_summary returns ({event, stations, stats, ...})."""
    updated = updated or _now()
    doc = {k: v for k, v in summary.items() if k not in ("stations", "stats", "key")}
    ev = summary["event"]
    out = [
        f"DELETE FROM pipeline_records WHERE event_key = {_lit(key)};",
        "INSERT OR REPLACE INTO pipeline_events (key, usgs_id, time, mag, doc, updated) "
        f"VALUES ({_lit(key)}, {_lit(ev.get('id'))}, {_lit(ev.get('time'))}, "
        f"{_lit(ev.get('mag'))}, {_lit(doc)}, {_lit(updated)});",
    ]
    for i, s in enumerate(summary["stations"]):
        out.append("INSERT INTO pipeline_records (event_key, ord, code, doc) VALUES "
                   f"({_lit(key)}, {i}, {_lit(s['code'])}, {_lit(s)});")
    out.append(f"UPDATE site_catalogs SET updated = {_lit(updated)} WHERE id = 'pipeline';")
    return out


class D1:
    """Thin wrapper over `wrangler d1 execute`."""

    def __init__(self, local: bool = False, database: str = DATABASE):
        self.local, self.database = local, database
        cmd = os.environ.get("WRANGLER")
        self.wrangler = shlex.split(cmd) if cmd else (
            ["wrangler"] if shutil.which("wrangler") else ["npx", "--yes", "wrangler@4"])

    def _run(self, *args: str) -> str:
        cmd = [*self.wrangler, "d1", "execute", self.database,
               "--local" if self.local else "--remote", "--yes", *args]
        res = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True)
        if res.returncode:
            raise RuntimeError(f"wrangler failed ({res.returncode}):\n{res.stderr or res.stdout}")
        return res.stdout

    def query(self, sql: str) -> list[dict]:
        out = json.loads(self._run("--json", "--command", sql))
        return out[0]["results"]

    def execute(self, statements: list[str]) -> None:
        with tempfile.NamedTemporaryFile("w", suffix=".sql", delete=False,
                                         encoding="utf-8") as f:
            f.write("\n".join(statements) + "\n")
        try:
            self._run("--file", f.name)
        finally:
            os.unlink(f.name)

    def known_usgs_ids(self) -> set[str]:
        return {r["usgs_id"] for r in self.query(
            "SELECT usgs_id FROM pipeline_events WHERE usgs_id IS NOT NULL")}

    def save_event(self, key: str, summary: dict) -> None:
        self.execute(event_statements(key, summary))

    def mark_run(self) -> None:
        """Stamp the pipeline catalog with this run's time, new events or not."""
        self.execute([f"UPDATE site_catalogs SET updated = {_lit(_now())} "
                      "WHERE id = 'pipeline';"])


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--local", action="store_true", help="local D1 (wrangler pages dev)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("list")
    imp = sub.add_parser("import-json", help="load DIR/<key>.json event files")
    imp.add_argument("dir", type=Path)
    args = ap.parse_args(argv)

    db = D1(local=args.local)
    if args.cmd == "list":
        for r in db.query("SELECT key, time, mag, (SELECT COUNT(*) FROM pipeline_records r "
                          "WHERE r.event_key = e.key) AS n FROM pipeline_events e ORDER BY time"):
            print(f"{r['key']:<28} {r['time'] or '':<26} M{r['mag']}  {r['n']} records")
    else:
        stmts, stamps = [], []
        for p in sorted(args.dir.glob("*.json")):
            d = json.loads(p.read_text())
            stamps.append(d.get("generated") or _now())
            stmts += event_statements(d.get("key") or p.stem, d, updated=stamps[-1])
        stmts.append(f"UPDATE site_catalogs SET updated = {_lit(max(stamps))} "
                     "WHERE id = 'pipeline';")
        db.execute(stmts)
        print(f"imported {len(list(args.dir.glob('*.json')))} event(s) into {db.database}")


if __name__ == "__main__":
    main()

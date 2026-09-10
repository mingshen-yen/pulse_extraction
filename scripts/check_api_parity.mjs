/* Prove the D1 API logic (functions/_lib.js) reproduces the static reference
 * JSON *shape* before switching site/app.js over.
 *
 *   node scripts/check_api_parity.mjs [db/site.dev.db]
 *
 * Reads the local SQLite dev DB with the sqlite3 CLI, builds each catalog blob
 * with the same code the Pages Functions use, and diffs it against
 * site/data/reference/<id>.json.  Numeric values may drift (the audited
 * workbook carries different hypocentres than the old CSV) -- this checks the
 * contract: same catalogs, same events, same station keys, same stats keys.
 */
import { execFileSync } from "node:child_process";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import path from "node:path";
import { buildCatalog, buildIndex } from "../functions/_lib.js";

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const DB = process.argv[2] || path.join(ROOT, "db", "site.dev.db");
const REF = path.join(ROOT, "site", "data", "reference");

const q = (sql) =>
  JSON.parse(
    execFileSync("sqlite3", ["-json", DB, sql], { encoding: "utf8" }) || "[]",
  );

const SQL = {
  index: `SELECT c.id,c.label,c.short,c.url,c.pulse_only,
    COUNT(DISTINCT pr.event_key) n_events, COUNT(pr.record_id) n_records
    FROM catalogs c LEFT JOIN pulse_records pr ON pr.catalog_id=c.id
    GROUP BY c.id ORDER BY c.sort_order,c.id`,
  meta: (id) => `SELECT * FROM catalogs WHERE id='${id}'`,
  records: (
    id,
  ) => `SELECT pr.event_key,pr.station_key,pr.station_label,pr.nga_rsn,
    pr.lat,pr.lon,pr.coord_status,pr.tp_s,pr.pgv_cm_s,pr.rrup_km,pr.rhyp_km,pr.vs30,
    pr.ori_north_deg,pr.ori_fp_deg,pr.is_pulse,pr.directivity,pr.fling,
    pr.quality_flag,pr.summary_url
    FROM pulse_records pr WHERE pr.catalog_id='${id}'`,
  events: (id) => `SELECT e.* FROM events e WHERE e.event_key IN
    (SELECT DISTINCT event_key FROM pulse_records WHERE catalog_id='${id}')`,
  segments: (id) => `SELECT s.* FROM fault_segments s WHERE s.event_key IN
    (SELECT DISTINCT event_key FROM pulse_records WHERE catalog_id='${id}')
    ORDER BY s.event_key,s.segment`,
};

let fails = 0;
const bad = (msg) => {
  fails++;
  console.log("  ✗ " + msg);
};
const ok = (msg) => console.log("  ✓ " + msg);
const keysOf = (o) => Object.keys(o).sort().join(",");

// ---- index -------------------------------------------------------------
const idx = buildIndex(q(SQL.index));
const staticIdx = JSON.parse(readFileSync(path.join(REF, "index.json")));
console.log("index.json");
const dbIds = idx.catalogs.map((c) => c.id).sort();
const stIds = staticIdx.catalogs.map((c) => c.id).sort();
dbIds.join() === stIds.join()
  ? ok(`catalogs: ${dbIds.join(", ")}`)
  : bad(`catalog ids differ: db=[${dbIds}] static=[${stIds}]`);
for (const c of idx.catalogs) {
  const s = staticIdx.catalogs.find((x) => x.id === c.id);
  if (!s) continue;
  c.n_events === s.n_events && c.n_records === s.n_records
    ? ok(`${c.id}: ${c.n_events} events / ${c.n_records} records`)
    : bad(
        `${c.id}: db ${c.n_events}/${c.n_records} vs static ${s.n_events}/${s.n_records}`,
      );
  if (keysOf(c) !== keysOf(s))
    bad(`${c.id}: index keys ${keysOf(c)} vs ${keysOf(s)}`);
}

// ---- each catalog blob ----------------------------------------------- --
for (const id of dbIds) {
  console.log(`\n${id}.json`);
  const blob = buildCatalog(
    q(SQL.meta(id))[0],
    q(SQL.records(id)),
    q(SQL.events(id)),
    q(SQL.segments(id)),
  );
  const stat = JSON.parse(readFileSync(path.join(REF, `${id}.json`)));

  if (keysOf(blob) !== keysOf(stat))
    bad(`blob keys ${keysOf(blob)}\n         vs ${keysOf(stat)}`);
  else ok(`blob keys: ${keysOf(blob)}`);

  // match events by a data signature (year + sorted station codes), not by the
  // event key -- the audited workbook gives events clean display names
  // ("San Fernando" vs the old "1971 SanFernando USA"), so the derived
  // evKey(name, year) changes.  The key is only an internal Map id in app.js.
  const sig = (e) =>
    `${e.year}::${e.stations
      .map((s) => s.code)
      .sort()
      .join("|")}`;
  const bBySig = new Map(blob.events.map((e) => [sig(e), e]));
  const sBySig = new Map(stat.events.map((e) => [sig(e), e]));
  const missing = [...sBySig.keys()].filter((k) => !bBySig.has(k));
  const extra = [...bBySig.keys()].filter((k) => !sBySig.has(k));
  missing.length
    ? bad(
        `events only in static (${missing.length}): ` +
          missing
            .slice(0, 4)
            .map((k) => sBySig.get(k).key)
            .join(", "),
      )
    : ok(`all ${sBySig.size} static events matched by (year + station set)`);
  if (extra.length)
    bad(
      `events only in db (${extra.length}): ` +
        extra
          .slice(0, 4)
          .map((k) => bBySig.get(k).key)
          .join(", "),
    );

  let statKeyMismatch = 0;
  const renamed = [];
  for (const [k, se] of sBySig) {
    const be = bBySig.get(k);
    if (!be) continue;
    if (keysOf(be.stats) !== keysOf(se.stats)) statKeyMismatch++;
    if (be.key !== se.key) renamed.push(`${se.key} -> ${be.key}`);
  }
  statKeyMismatch
    ? bad(`${statKeyMismatch} events with differing stats keys`)
    : ok("stats keys identical on every matched event");
  if (renamed.length)
    console.log(
      `  · ${renamed.length} event key(s) changed (clean names from the audited table), e.g. ` +
        renamed.slice(0, 3).join(" ; "),
    );

  // spot-check the scatter/by_distance shape on the busiest event
  const busiest = [...blob.events].sort((a, b) => b.stats.n - a.stats.n)[0];
  const sp = busiest.stats.scatter[0] || {};
  const want = "PGV,Tp,code,is_pulse,repi_km,rhyp_km,rrup_km";
  keysOf(sp) === want
    ? ok(`scatter point keys ok (e.g. ${busiest.key})`)
    : bad(`scatter point keys ${keysOf(sp)} vs ${want}`);
}

console.log(fails ? `\n${fails} check(s) failed` : "\nall checks passed");
process.exit(fails ? 1 : 0);

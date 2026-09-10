/* Write site/data/reference/*.json from the audited workbook.
 *
 *   python scripts/load_workbook.py --sqlite db/site.dev.db   # xlsx -> local DB
 *   node   scripts/build_reference_json.mjs                    # DB  -> static JSON
 *
 * Uses the same functions/_lib.js the Pages Functions use, so the static
 * fallback bundle is byte-for-byte what /api/catalogs and /api/catalog/:id
 * return.  scripts/check_api_parity.mjs then only has to confirm they agree.
 */
import { execFileSync } from "node:child_process";
import { writeFileSync, mkdirSync } from "node:fs";
import { fileURLToPath } from "node:url";
import path from "node:path";
import { buildCatalog, buildIndex } from "../functions/_lib.js";

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const DB = process.argv[2] || path.join(ROOT, "db", "site.dev.db");
const OUT = path.join(ROOT, "site", "data", "reference");

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

mkdirSync(OUT, { recursive: true });

const idxRows = q(SQL.index);
const index = buildIndex(idxRows);
writeFileSync(
  path.join(OUT, "index.json"),
  JSON.stringify(index, null, 1) + "\n",
);
console.log(`index.json  (${index.catalogs.length} catalogs)`);

for (const c of index.catalogs) {
  const blob = buildCatalog(
    q(SQL.meta(c.id))[0],
    q(SQL.records(c.id)),
    q(SQL.events(c.id)),
    q(SQL.segments(c.id)),
  );
  writeFileSync(
    path.join(OUT, `${c.id}.json`),
    JSON.stringify(blob, null, 1) + "\n",
  );
  console.log(
    `${c.id}.json  ${blob.n_events} events / ${blob.n_records} records`,
  );
}

/* Shared helpers for the reference-catalog API (Cloudflare Pages Functions).
 *
 * These turn D1 rows (schema in db/schema.sql) into exactly the JSON the
 * static site already consumes:
 *
 *   /api/catalogs        <- site/data/reference/index.json
 *   /api/catalog/:id     <- site/data/reference/<id>.json
 *
 * The row -> JSON logic is a straight port of scripts/import_reference_tables.py
 * (`_stats`, `_bins`, `_trace_along_strike`, `key`) so the contract in
 * site/app.js does not change -- only the fetch URL does.
 *
 * Everything here is pure and environment-agnostic: pass in plain row arrays (the test
 * harness feeds rows from the local SQLite dev DB; the Functions feed rows from
 * `env.DB`).
 */

const R_EARTH_KM = 6371.0088;
const BIN_EDGES = [0, 5, 10, 20, 40, 80, 160];

/* frontend event key: "northern_calif_03|1954"  (see evKey in site/app.js) */
export function evKey(name, year) {
  const slug = String(name)
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "_")
    .replace(/^_|_$/g, "");
  return year ? `${slug}|${year}` : slug;
}

export function haversineKm(lat1, lon1, lat2, lon2) {
  if ([lat1, lon1, lat2, lon2].some((v) => v == null)) return null;
  const rad = (d) => (d * Math.PI) / 180;
  const p1 = rad(lat1);
  const p2 = rad(lat2);
  const dphi = rad(lat2 - lat1);
  const dlmb = rad(lon2 - lon1);
  const a =
    Math.sin(dphi / 2) ** 2 +
    Math.cos(p1) * Math.cos(p2) * Math.sin(dlmb / 2) ** 2;
  return 2 * R_EARTH_KM * Math.asin(Math.min(1, Math.sqrt(a)));
}

const round = (x, n) =>
  x == null ? null : Math.round((x + Number.EPSILON) * 10 ** n) / 10 ** n;

/* median: mean of the two middle values for an even count (matches Python
 * statistics.median). `arr` must already be sorted ascending. */
function median(arr) {
  if (!arr.length) return null;
  const m = arr.length >> 1;
  return arr.length % 2 ? arr[m] : (arr[m - 1] + arr[m]) / 2;
}

/* distance used in every plot: Rrup, else Rhyp when Rrup is missing */
const dist = (s) => (s.rrup_km != null ? s.rrup_km : s.rhyp_km);

/* ---------- stats (frozen frontend contract) --------------------------- */
export function computeStats(stations) {
  const pul = stations.filter((s) => s.is_pulse);
  const tps = pul
    .map((s) => s.Tp)
    .filter(Boolean)
    .sort((a, b) => a - b);
  const pgv = pul
    .map((s) => s.PGV)
    .filter(Boolean)
    .sort((a, b) => a - b);
  return {
    n: stations.length,
    n_pulse: pul.length,
    pulse_fraction: stations.length
      ? round(pul.length / stations.length, 3)
      : null,
    Tp_median: tps.length ? round(median(tps), 3) : null,
    PGV_median: pgv.length ? round(median(pgv), 2) : null,
    Tp_range: tps.length ? [tps[0], tps[tps.length - 1]] : [null, null],
    by_distance: bins(stations),
    scatter: stations
      .filter((s) => dist(s) != null)
      .map((s) => ({
        code: s.code,
        repi_km: s.repi_km ?? null,
        rhyp_km: s.rhyp_km ?? null,
        rrup_km: s.rrup_km ?? null,
        Tp: s.Tp ?? null,
        PGV: s.PGV ?? null,
        is_pulse: s.is_pulse,
      })),
  };
}

function bins(stations) {
  const out = [];
  for (let i = 0; i < BIN_EDGES.length - 1; i++) {
    const lo = BIN_EDGES[i];
    const hi = BIN_EDGES[i + 1];
    const g = stations.filter(
      (s) => dist(s) != null && dist(s) >= lo && dist(s) < hi,
    );
    if (!g.length) continue;
    const npul = g.filter((s) => s.is_pulse).length;
    const tps = g
      .filter((s) => s.is_pulse && s.Tp)
      .map((s) => s.Tp)
      .sort((a, b) => a - b);
    out.push({
      r_lo: lo,
      r_hi: hi,
      n: g.length,
      n_pulse: npul,
      pulse_fraction: round(npul / g.length, 3),
      Tp_median: tps.length ? tps[tps.length >> 1] : null, // upper-middle, unrounded
    });
  }
  return out;
}

/* ---------- schematic source model from stored geometry --------------- */
/* straight surface trace [[lon,lat],[lon,lat]] of `lengthKm`, bearing
 * `strike`, centred on the hypocentre (port of _trace_along_strike). */
function traceAlongStrike(lat, lon, strike, lengthKm) {
  if ([lat, lon, strike, lengthKm].some((v) => v == null)) return null;
  const kmlat = 111.32;
  const kmlon = 111.32 * Math.cos((lat * Math.PI) / 180);
  const s = (strike * Math.PI) / 180;
  const dx = Math.sin(s);
  const dy = Math.cos(s);
  const h = lengthKm / 2;
  return [
    [round(lon - (h * dx) / kmlon, 5), round(lat - (h * dy) / kmlat, 5)],
    [round(lon + (h * dx) / kmlon, 5), round(lat + (h * dy) / kmlat, 5)],
  ];
}

const normRake = (r) =>
  r == null ? null : ((((r + 180) % 360) + 360) % 360) - 180;

function sourceModel(ev) {
  if (ev.strike1 == null) return null;
  const twoPlanes = /nodal plane/i.test(ev.plane_definition || "");
  return {
    np1: [ev.strike1, ev.dip1, ev.rake1],
    np2: ev.strike2 == null ? null : [ev.strike2, ev.dip2, ev.rake2],
    source: twoPlanes ? "USGS moment-tensor" : "NGA representative fault plane",
    mag: ev.mag,
    mag_type: ev.mag_type || "Mww",
  };
}

function faultModel(ev, segs) {
  const lat = ev.hypo_lat;
  const lon = ev.hypo_lon;

  if (segs.length) {
    const s0 = segs[0];
    const total = segs.reduce((a, s) => a + (s.length_km || 0), 0);
    const width = Math.max(...segs.map((s) => s.width_km || 0)) || null;
    const rake = normRake(
      s0.rake_min_deg != null && s0.rake_max_deg != null
        ? (s0.rake_min_deg + s0.rake_max_deg) / 2
        : null,
    );
    return {
      strike: s0.strike_deg,
      dip: s0.dip_deg,
      length_km: round(total, 1),
      width_km: round(width, 1),
      model: "USGS finite-fault inversion",
      trace: traceAlongStrike(lat, lon, s0.strike_deg, total),
      rake: round(rake, 1),
      segments: segs.length,
    };
  }

  if (ev.nga_length_km != null) {
    return {
      strike: ev.nga_strike,
      dip: ev.nga_dip,
      length_km: ev.nga_length_km,
      width_km: ev.nga_width_km,
      model: "NGA representative fault plane",
      trace: traceAlongStrike(lat, lon, ev.nga_strike, ev.nga_length_km),
      rake: ev.nga_rake,
    };
  }

  if (ev.strike1 != null && ev.mag != null) {
    const L = 10 ** (-2.44 + 0.59 * ev.mag); // Wells & Coppersmith (1994)
    const W = 10 ** (-1.01 + 0.32 * ev.mag);
    return {
      strike: ev.strike1,
      dip: ev.dip1,
      length_km: round(L, 1),
      width_km: round(W, 1),
      model: "Wells & Coppersmith (1994) scaling",
      trace: traceAlongStrike(lat, lon, ev.strike1, L),
      rake: ev.rake1,
    };
  }

  return null;
}

/* ---------- row -> station / event ----------------------------------- */
function station(r, ev) {
  const s = {
    code: r.station_label || r.station_key,
    lat: r.lat ?? null,
    lon: r.lon ?? null,
    rrup_km: round(r.rrup_km, 3),
    rhyp_km: round(r.rhyp_km, 3),
    is_pulse: !!r.is_pulse,
    Tp: round(r.tp_s, 3),
    PGV: round(r.pgv_cm_s, 3),
    vs30: round(r.vs30, 3),
    ori_n: round(r.ori_north_deg, 3),
    ori_fp: round(r.ori_fp_deg, 3),
    fling: r.fling == null ? null : !!r.fling,
    directivity: r.directivity === 1 ? true : null,
    rsn: r.nga_rsn || null,
    summary_url: r.summary_url || null,
    quality_flag: r.quality_flag || null,
    coord_status:
      r.coord_status && r.coord_status !== "matched" ? r.coord_status : null,
    repi_km:
      r.lat != null && ev.hypo_lat != null
        ? round(haversineKm(ev.hypo_lat, ev.hypo_lon, r.lat, r.lon), 2)
        : null,
  };
  // drop null/undefined keys (except the always-present lat/lon/code/is_pulse)
  for (const k of Object.keys(s)) {
    if (s[k] == null && !["lat", "lon", "code", "is_pulse"].includes(k))
      delete s[k];
  }
  return s;
}

/* rows: pulse_records joined shape; evRows: events; segRows: fault_segments */
export function buildEvents(rows, evRows, segRows) {
  const evByKey = new Map(evRows.map((e) => [e.event_key, e]));
  const segByEvent = new Map();
  for (const s of segRows) {
    if (!segByEvent.has(s.event_key)) segByEvent.set(s.event_key, []);
    segByEvent.get(s.event_key).push(s);
  }
  for (const list of segByEvent.values())
    list.sort((a, b) => a.segment - b.segment);

  const grouped = new Map();
  for (const r of rows) {
    if (!grouped.has(r.event_key)) grouped.set(r.event_key, []);
    grouped.get(r.event_key).push(r);
  }

  const events = [];
  for (const [ekDb, recs] of grouped) {
    const ev = evByKey.get(ekDb) || {};
    const stations = recs.map((r) => station(r, ev));
    const segs = segByEvent.get(ekDb) || [];
    const sm = sourceModel(ev);
    const fault = faultModel(ev, segs);
    const out = {
      key: evKey(ev.name, ev.year),
      name: ev.name,
      year: ev.year == null ? null : String(ev.year),
      lat: ev.hypo_lat ?? null,
      lon: ev.hypo_lon ?? null,
      depth_km: ev.hypo_depth_km ?? null,
      mag: ev.mag ?? null,
      fault_type: ev.mechanism || null,
      stations,
      stats: computeStats(stations),
      n_mappable: stations.filter((s) => s.lat != null).length,
    };
    if (fault) out.fault = fault;
    if (sm) out.source_model = sm;
    if (ev.source_url) out.usgs_url = ev.source_url;
    events.push(out);
  }
  events.sort(
    (a, b) =>
      (a.year || "").localeCompare(b.year || "") ||
      a.name.localeCompare(b.name),
  );
  return events;
}

export function buildCatalog(meta, rows, evRows, segRows) {
  const events = buildEvents(rows, evRows, segRows);
  return {
    schema: "pulse-extraction/reference/2",
    catalog: meta.id,
    label: meta.label,
    short: meta.short,
    citation: meta.citation,
    url: meta.url,
    pulse_only: !!meta.pulse_only,
    n_events: events.length,
    n_records: events.reduce((a, e) => a + e.stats.n, 0),
    events,
  };
}

export function buildIndex(catRows) {
  return {
    catalogs: catRows.map((c) => ({
      id: c.id,
      label: c.label,
      short: c.short,
      url: c.url,
      n_events: c.n_events,
      n_records: c.n_records,
      pulse_only: !!c.pulse_only,
    })),
  };
}

/* ---------- D1 query wrappers (used by the Functions) ----------------- */
export const SQL = {
  index: `
    SELECT c.id, c.label, c.short, c.url, c.pulse_only,
           COUNT(DISTINCT pr.event_key)                       AS n_events,
           COUNT(pr.record_id)                                AS n_records
    FROM catalogs c
    LEFT JOIN pulse_records pr ON pr.catalog_id = c.id
    GROUP BY c.id
    ORDER BY c.sort_order, c.id`,
  meta: `SELECT * FROM catalogs WHERE id = ?`,
  records: `
    SELECT pr.event_key, pr.station_key, pr.station_label, pr.nga_rsn,
           pr.lat, pr.lon, pr.coord_status, pr.tp_s, pr.pgv_cm_s,
           pr.rrup_km, pr.rhyp_km, pr.vs30, pr.ori_north_deg, pr.ori_fp_deg,
           pr.is_pulse, pr.directivity, pr.fling, pr.quality_flag, pr.summary_url
    FROM pulse_records pr
    WHERE pr.catalog_id = ?`,
  events: `
    SELECT e.* FROM events e
    WHERE e.event_key IN (SELECT DISTINCT event_key FROM pulse_records WHERE catalog_id = ?)`,
  segments: `
    SELECT s.* FROM fault_segments s
    WHERE s.event_key IN (SELECT DISTINCT event_key FROM pulse_records WHERE catalog_id = ?)
    ORDER BY s.event_key, s.segment`,
};

export async function catalogIndex(db) {
  const { results } = await db.prepare(SQL.index).all();
  return buildIndex(results);
}

export async function catalogBlob(db, id) {
  const meta = await db.prepare(SQL.meta).bind(id).first();
  if (!meta) return null;
  const [recs, evs, segs] = await Promise.all([
    db.prepare(SQL.records).bind(id).all(),
    db.prepare(SQL.events).bind(id).all(),
    db.prepare(SQL.segments).bind(id).all(),
  ]);
  return buildCatalog(meta, recs.results, evs.results, segs.results);
}

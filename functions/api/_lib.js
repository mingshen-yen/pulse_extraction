// Shared helpers for the /api/* Pages Functions (D1 binding: env.DB).
//
// D1 is the source of truth.  Reference catalogs are derived on every request
// from the workbook tables (pulse_records, event_sources,
// finite_fault_segments; scripts/import_workbook.py) and pipeline results from
// pipeline_events / pipeline_records (db/schema.sql), so an edit in D1 shows up
// on the site immediately.  Only public display fields leave this module:
// audit columns, notes and local file paths in the workbook are never copied.

const JWB = "https://www.jackwbaker.com/pulse_classification_v2";
const R_EARTH_KM = 6371.0088;

export function json(body, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: {
      "Content-Type": "application/json; charset=utf-8",
      "Cache-Control": "public, max-age=60",
    },
  });
}

/* ---------- filters ------------------------------------------------------ */
const FILTERS = ["mag_min", "mag_max", "tp_min", "tp_max", "dist_min", "dist_max"];

/* Numeric filters from the query string; anything non-numeric is ignored. */
export function parseFilters(url) {
  const filters = {};
  for (const name of FILTERS) {
    const raw = url.searchParams.get(name);
    if (raw == null || raw.trim() === "") continue;
    const v = Number(raw);
    if (Number.isFinite(v)) filters[name] = v;
  }
  return filters;
}

/* distance used everywhere: Rrup, else Rhyp */
const dist = (s) => (s.rrup_km != null ? s.rrup_km : s.rhyp_km);
const within = (v, lo, hi) =>
  (lo == null && hi == null) || (v != null && (lo == null || v >= lo) && (hi == null || v <= hi));

export const eventPasses = (e, f) => within(e.mag, f.mag_min, f.mag_max);
export const stationPasses = (s, f) =>
  within(s.Tp, f.tp_min, f.tp_max) && within(dist(s), f.dist_min, f.dist_max);
export const recordFiltered = (f) =>
  ["tp_min", "tp_max", "dist_min", "dist_max"].some((k) => k in f);

/* ---------- small numeric helpers (mirror the old Python builder) -------- */
const num = (x) => {
  if (x == null || x === "") return null;
  const v = Number(x);
  return Number.isFinite(v) ? v : null;
};
const round = (x, d) => (x == null ? null : Math.round(x * 10 ** d) / 10 ** d);
const median = (xs) => {
  if (!xs.length) return null;
  const m = xs.length >> 1;
  return xs.length % 2 ? xs[m] : (xs[m - 1] + xs[m]) / 2;
};

export function haversineKm(lat1, lon1, lat2, lon2) {
  if ([lat1, lon1, lat2, lon2].some((v) => v == null)) return null;
  const r = Math.PI / 180;
  const a =
    Math.sin(((lat2 - lat1) * r) / 2) ** 2 +
    Math.cos(lat1 * r) * Math.cos(lat2 * r) * Math.sin(((lon2 - lon1) * r) / 2) ** 2;
  return 2 * R_EARTH_KM * Math.asin(Math.min(1, Math.sqrt(a)));
}

/* A browser-safe http(s) URL, optionally on one host, else null.  The
   workbook's source fields can hold local evidence paths and prose. */
export function publicUrl(value, host) {
  if (typeof value !== "string") return null;
  let u;
  try {
    u = new URL(value.trim());
  } catch {
    return null;
  }
  if (!["http:", "https:"].includes(u.protocol) || !u.hostname) return null;
  if (host && u.hostname !== host) return null;
  return value.trim();
}

/* ---------- names and keys ----------------------------------------------- */
// event_names is "seg | seg | ..."; skip alias-shaped segments (lowercase-dash-
// digit, ALL_CAPS/underscore codes, yyyy_ slugs) and take the first real name.
const ALIAS_SEG = /^[a-z]+-\d+$|^[A-Z0-9_]+$|^\d{4}_|^[a-z0-9]+(?:_[a-z0-9]+)+$/;

export function displayName(eventNames, fallback) {
  const segs = String(eventNames || fallback)
    .split("|")
    .map((s) => s.trim());
  return segs.find((s) => !ALIAS_SEG.test(s)) ?? segs[0];
}

export function eventKey(name, year = "") {
  const s = String(name)
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "_")
    .replace(/^_+|_+$/g, "");
  return year ? `${s}|${year}` : s;
}

/* ---------- fault / source model ---------------------------------------- */
function traceAlongStrike(lat, lon, strike, lengthKm) {
  if ([lat, lon, strike, lengthKm].some((v) => v == null)) return null;
  const kmlat = 111.32,
    kmlon = 111.32 * Math.cos((lat * Math.PI) / 180);
  const s = (strike * Math.PI) / 180;
  const dx = Math.sin(s),
    dy = Math.cos(s),
    h = lengthKm / 2;
  return [
    [round(lon - (h * dx) / kmlon, 5), round(lat - (h * dy) / kmlat, 5)],
    [round(lon + (h * dx) / kmlon, 5), round(lat + (h * dy) / kmlat, 5)],
  ];
}

const normRake = (r) => (r == null ? null : ((((r + 180) % 360) + 360) % 360) - 180);

export function sourceModel(ev) {
  if (ev.strike1_deg == null) return null;
  const twoPlanes = String(ev.plane_definition || "").toLowerCase().includes("nodal plane");
  return {
    np1: [ev.strike1_deg, ev.dip1_deg ?? null, ev.rake1_deg ?? null],
    np2: ev.strike2_deg == null ? null : [ev.strike2_deg, ev.dip2_deg ?? null, ev.rake2_deg ?? null],
    source: twoPlanes ? "USGS moment-tensor" : "NGA representative fault plane",
    mag: ev.catalog_magnitude ?? null,
    mag_type: ev.magnitude_type || "Mww",
  };
}

export function faultModel(ev, segs) {
  const lat = ev.hypo_latitude_deg,
    lon = ev.hypo_longitude_deg;
  if (segs.length) {
    const s0 = segs[0];
    const total = segs.reduce((a, s) => a + (s.model_length_km || 0), 0);
    const width = Math.max(...segs.map((s) => s.model_width_km || 0));
    const { rake_min_deg: rmin, rake_max_deg: rmax } = s0;
    const rake = rmin != null && rmax != null ? normRake((rmin + rmax) / 2) : null;
    return {
      strike: s0.strike_deg ?? null,
      dip: s0.dip_deg ?? null,
      length_km: round(total, 1),
      width_km: round(width, 1),
      model: "USGS finite-fault inversion",
      trace: traceAlongStrike(lat, lon, s0.strike_deg, total),
      rake: round(rake, 1),
      segments: segs.length,
    };
  }
  if (ev.nga_length_km != null)
    return {
      strike: ev.nga_strike_deg ?? null,
      dip: ev.nga_dip_deg ?? null,
      length_km: ev.nga_length_km,
      width_km: ev.nga_width_km ?? null,
      model: "NGA representative fault plane",
      trace: traceAlongStrike(lat, lon, ev.nga_strike_deg, ev.nga_length_km),
      rake: ev.nga_rake_deg ?? null,
    };
  if (ev.strike1_deg != null && ev.catalog_magnitude != null) {
    const m = ev.catalog_magnitude;
    const length = 10 ** (-2.44 + 0.59 * m),
      width = 10 ** (-1.01 + 0.32 * m);
    return {
      strike: ev.strike1_deg,
      dip: ev.dip1_deg ?? null,
      length_km: round(length, 1),
      width_km: round(width, 1),
      model: "Wells & Coppersmith (1994) scaling",
      trace: traceAlongStrike(lat, lon, ev.strike1_deg, length),
      rake: ev.rake1_deg ?? null,
    };
  }
  return null;
}

/* ---------- one pulse_records row -> station ----------------------------- */
const KEEP_NULL = new Set(["lat", "lon", "code", "is_pulse"]);

export function station(r, ev, catId, pulseOnly) {
  const rsn = r.NGA_RSN != null && r.NGA_RSN !== "" ? String(r.NGA_RSN).trim() : null;
  let pgv = num(r.PGV_cm_s);
  if (pgv == null) {
    const vals = [num(r.PGV_EW_original), num(r.PGV_NS_original)].filter((v) => v != null);
    pgv = vals.length ? Math.max(...vals) : null;
  }
  const lat = num(r.latitude_deg),
    lon = num(r.longitude_deg);
  const s = {
    code:
      r.station_original != null && r.station_original !== ""
        ? String(r.station_original).trim()
        : r.station_key,
    lat,
    lon,
    rrup_km: round(r.Rrup_km != null ? num(r.Rrup_km) : num(r.closest_distance_km), 3),
    rhyp_km: round(num(r.Rhyp_km), 3),
    // workbook booleans are stored as 1/0
    is_pulse: r.fault_normal_pulse == 1 || r.Ipulse_H == 1 || pulseOnly,
    Tp: round(r.Tp_s != null ? num(r.Tp_s) : num(r.Tp_H_s), 3),
    PGV: round(pgv, 3),
    vs30: round(num(r.vs30_original), 3),
    ori_n: round(num(r.orientation_north_deg), 3),
    ori_fp: round(num(r.orientation_fault_parallel_deg), 3),
    fling: r.fling == null ? null : r.fling == 1,
    directivity: r.directivity_effect == 1 ? true : null,
    rsn,
    summary_url: rsn && catId === "sb" ? `${JWB}/${rsn}.html` : null,
    quality_flag: r.quality_flag != null && r.quality_flag !== "" ? String(r.quality_flag) : null,
    coord_status: r.coord_status != null && r.coord_status !== "matched" ? r.coord_status : null,
    repi_km:
      lat != null
        ? round(haversineKm(ev.hypo_latitude_deg, ev.hypo_longitude_deg, lat, lon), 2)
        : null,
  };
  return Object.fromEntries(Object.entries(s).filter(([k, v]) => v != null || KEEP_NULL.has(k)));
}

/* ---------- stats over a set of stations --------------------------------- */
export function stats(stations) {
  const pul = stations.filter((s) => s.is_pulse);
  const tps = pul.map((s) => s.Tp).filter(Boolean).sort((a, b) => a - b);
  const pgv = pul.map((s) => s.PGV).filter(Boolean).sort((a, b) => a - b);
  return {
    n: stations.length,
    n_pulse: pul.length,
    pulse_fraction: stations.length ? round(pul.length / stations.length, 3) : null,
    Tp_median: round(median(tps), 3),
    PGV_median: round(median(pgv), 2),
    Tp_range: tps.length ? [tps[0], tps[tps.length - 1]] : [null, null],
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

/* ---------- catalogs ----------------------------------------------------- */
export async function getCatalogs(db) {
  const { results } = await db.prepare("SELECT * FROM site_catalogs ORDER BY ord").all();
  return results.map((c) => ({ ...c, pulse_only: !!c.pulse_only }));
}

export async function getCatalog(db, id) {
  if (!id) return null;
  const c = await db.prepare("SELECT * FROM site_catalogs WHERE id = ?").bind(id).first();
  return c && { ...c, pulse_only: !!c.pulse_only };
}

/* Every event of a catalog, with all its stations: [{...event, stations}]. */
export function loadEvents(db, cat) {
  return cat.kind === "pipeline" ? loadPipeline(db) : loadReference(db, cat);
}

const PR_COLS = [
  "event_source_key", "station_original", "station_key", "latitude_deg", "longitude_deg",
  "Rrup_km", "closest_distance_km", "Rhyp_km", "fault_normal_pulse", "Ipulse_H", "Tp_s",
  "Tp_H_s", "PGV_cm_s", "PGV_EW_original", "PGV_NS_original", "vs30_original",
  "orientation_north_deg", "orientation_fault_parallel_deg", "fling", "directivity_effect",
  "NGA_RSN", "quality_flag", "coord_status",
];
const ES_COLS = [
  "event_source_key", "event_key", "event_names", "hypo_latitude_deg", "hypo_longitude_deg",
  "hypo_depth_km", "catalog_magnitude", "magnitude_type", "mechanism", "plane_definition",
  "strike1_deg", "dip1_deg", "rake1_deg", "strike2_deg", "dip2_deg", "rake2_deg",
  "nga_strike_deg", "nga_dip_deg", "nga_rake_deg", "nga_length_km", "nga_width_km", "source_url",
];
const FF_COLS = [
  "event_key", "segment", "strike_deg", "dip_deg", "model_length_km", "model_width_km",
  "rake_min_deg", "rake_max_deg",
];
const cols = (names, alias = "") => names.map((c) => `${alias}"${c}"`).join(", ");

async function loadReference(db, cat) {
  const [recs, evs, segs] = await db.batch([
    db
      .prepare(`SELECT ${cols(PR_COLS)} FROM pulse_records WHERE active_sheet = ? ORDER BY _row`)
      .bind(cat.active_sheet),
    db
      .prepare(
        `SELECT ${cols(ES_COLS, "e.")} FROM event_sources e WHERE e.event_source_key IN
           (SELECT event_source_key FROM pulse_records WHERE active_sheet = ?)`,
      )
      .bind(cat.active_sheet),
    db.prepare(`SELECT ${cols(FF_COLS)} FROM finite_fault_segments ORDER BY event_key, segment`),
  ]);
  const evByKey = new Map(evs.results.map((e) => [e.event_source_key, e]));
  const segsByEvent = new Map();
  for (const s of segs.results) {
    if (!segsByEvent.has(s.event_key)) segsByEvent.set(s.event_key, []);
    segsByEvent.get(s.event_key).push(s);
  }

  const groups = new Map(); // event_source_key -> rows, in workbook order
  for (const r of recs.results) {
    if (!groups.has(r.event_source_key)) groups.set(r.event_source_key, []);
    groups.get(r.event_source_key).push(r);
  }

  const events = [];
  for (const [esk, rows] of groups) {
    const ev = evByKey.get(esk);
    if (!ev) continue; // record points at a missing event_sources row
    const yr = /^\d{4}/.test(ev.event_key) ? ev.event_key.slice(0, 4) : null;
    const name = displayName(ev.event_names, ev.event_key);
    const stations = rows.map((r) => station(r, ev, cat.id, cat.pulse_only));
    const out = {
      key: eventKey(name, yr || ""),
      name,
      year: yr,
      lat: ev.hypo_latitude_deg ?? null,
      lon: ev.hypo_longitude_deg ?? null,
      depth_km: ev.hypo_depth_km ?? null,
      mag: ev.catalog_magnitude ?? null,
      fault_type: ev.mechanism ?? null,
      n_mappable: stations.filter((s) => s.lat != null).length,
      stations,
    };
    const fault = faultModel(ev, segsByEvent.get(ev.event_key) || []);
    if (fault) out.fault = fault;
    const sm = sourceModel(ev);
    if (sm) out.source_model = sm;
    const usgs = publicUrl(ev.source_url, "earthquake.usgs.gov");
    if (usgs) out.usgs_url = usgs;
    events.push(out);
  }
  events.sort((a, b) => {
    const ya = a.year || "",
      yb = b.year || "";
    return ya < yb ? -1 : ya > yb ? 1 : a.name < b.name ? -1 : a.name > b.name ? 1 : 0;
  });
  return events;
}

async function loadPipeline(db) {
  const [evs, recs] = await db.batch([
    db.prepare("SELECT key, doc FROM pipeline_events"),
    db.prepare("SELECT event_key, doc FROM pipeline_records ORDER BY event_key, ord"),
  ]);
  const byEvent = new Map();
  for (const r of recs.results) {
    if (!byEvent.has(r.event_key)) byEvent.set(r.event_key, []);
    byEvent.get(r.event_key).push(JSON.parse(r.doc));
  }
  return evs.results
    .map((row) => {
      const doc = JSON.parse(row.doc);
      return { ...doc, key: row.key, mag: doc.event?.mag ?? null, stations: byEvent.get(row.key) || [] };
    })
    .sort((a, b) => ((b.event?.time || "") < (a.event?.time || "") ? -1 : 1));
}

/* List entry for one event (stations already filtered). */
export function summary(e, cat, stations) {
  const n = stations.length,
    n_pulse = stations.filter((s) => s.is_pulse).length;
  if (cat.kind === "pipeline") {
    const ev = e.event || {};
    return {
      key: e.key,
      name: ev.name ?? null,
      region: ev.region ?? null,
      time: ev.time ?? null,
      lat: ev.lat ?? null,
      lon: ev.lon ?? null,
      depth_km: ev.depth_km ?? null,
      mag: ev.mag ?? null,
      mag_type: ev.mag_type ?? null,
      source: ev.source ?? null,
      n,
      n_pulse,
      pulse_fraction: n ? round(n_pulse / n, 3) : null,
      Tp_median: stats(stations).Tp_median,
      has_fault: "fault" in ev,
    };
  }
  const { key, name, year, lat, lon, depth_km, mag } = e;
  return { key, name, year, lat, lon, depth_km, mag, n, n_pulse };
}

/* Full event document as the page expects it. */
export function document(e, stations) {
  const { stations: _all, mag: _mag, ...rest } = e;
  const doc = { ...rest, stations, stats: stats(stations) };
  if (!("event" in e)) doc.mag = e.mag; // reference events carry mag at top level
  return doc;
}

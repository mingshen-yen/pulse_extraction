// Shared helpers for the /api/* Pages Functions (D1 binding: env.DB).
// Schema: db/schema.sql.  Data: scripts/build_d1_seed.py.

// query param -> [column, operator]; records use dist_km = Rrup, else Rhyp
const EVENT_FILTERS = {
  mag_min: ["e.mag", ">="],
  mag_max: ["e.mag", "<="],
};
const RECORD_FILTERS = {
  tp_min: ["r.Tp", ">="],
  tp_max: ["r.Tp", "<="],
  dist_min: ["r.dist_km", ">="],
  dist_max: ["r.dist_km", "<="],
};

export function json(body, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: {
      "Content-Type": "application/json; charset=utf-8",
      "Cache-Control": "public, max-age=300",
    },
  });
}

/* Numeric filters from the query string; anything non-numeric is ignored. */
export function parseFilters(url) {
  const filters = {};
  for (const name of [...Object.keys(EVENT_FILTERS), ...Object.keys(RECORD_FILTERS)]) {
    const raw = url.searchParams.get(name);
    if (raw == null || raw.trim() === "") continue;
    const v = Number(raw);
    if (Number.isFinite(v)) filters[name] = v;
  }
  return filters;
}

function clauses(filters, table) {
  const sql = [],
    binds = [];
  for (const [name, [col, op]] of Object.entries(table)) {
    if (name in filters) {
      sql.push(`${col} ${op} ?`);
      binds.push(filters[name]);
    }
  }
  return { sql, binds };
}
export const eventClauses = (f) => clauses(f, EVENT_FILTERS);
export const recordClauses = (f) => clauses(f, RECORD_FILTERS);

export async function getCatalog(db, id) {
  if (!id) return null;
  return db.prepare("SELECT id, kind, doc FROM catalogs WHERE id = ?").bind(id).first();
}

const median = (xs) => {
  if (!xs.length) return null;
  const m = xs.length >> 1;
  return xs.length % 2 ? xs[m] : (xs[m - 1] + xs[m]) / 2;
};
const round = (x, d) => (x == null ? null : Math.round(x * 10 ** d) / 10 ** d);
const dist = (s) => (s.rrup_km != null ? s.rrup_km : s.rhyp_km);

/* Same definitions as build_reference_catalogs._stats, for a filtered subset.
   (by_distance is not recomputed; the front end does not use it.) */
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
        repi_km: s.repi_km,
        rhyp_km: s.rhyp_km,
        rrup_km: s.rrup_km,
        Tp: s.Tp,
        PGV: s.PGV,
        is_pulse: s.is_pulse,
      })),
  };
}

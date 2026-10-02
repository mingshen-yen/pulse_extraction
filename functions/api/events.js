// GET /api/events?catalog=<id>[&mag_min&mag_max&tp_min&tp_max&dist_min&dist_max]
// Events with at least one record passing the filters; n / n_pulse count the
// matching records only.  Distance is Rrup, else Rhyp.
import { eventClauses, getCatalog, json, parseFilters, recordClauses } from "./_lib.js";

export async function onRequestGet({ request, env }) {
  const url = new URL(request.url);
  const cat = await getCatalog(env.DB, url.searchParams.get("catalog"));
  if (!cat) return json({ error: "unknown catalog" }, 404);

  const filters = parseFilters(url);
  const ev = eventClauses(filters),
    rec = recordClauses(filters);
  const filtered = ev.sql.length + rec.sql.length > 0;

  const { results } = await env.DB.prepare(
    `SELECT e.summary, COUNT(r.ord) AS n, COALESCE(SUM(r.is_pulse), 0) AS n_pulse
       FROM events e
       LEFT JOIN records r
         ON r.catalog = e.catalog AND r.event_key = e.key
        ${rec.sql.map((c) => `AND ${c}`).join(" ")}
      WHERE e.catalog = ? ${ev.sql.map((c) => `AND ${c}`).join(" ")}
      GROUP BY e.catalog, e.key
      ${filtered ? "HAVING COUNT(r.ord) > 0" : ""}
      ORDER BY e.ord`,
  )
    .bind(...rec.binds, cat.id, ...ev.binds)
    .all();

  const events = results.map((row) => {
    const e = { ...JSON.parse(row.summary), n: row.n, n_pulse: row.n_pulse };
    if ("pulse_fraction" in e)
      e.pulse_fraction = row.n ? Math.round((row.n_pulse / row.n) * 1000) / 1000 : null;
    if (filtered) delete e.Tp_median; // list value would describe all records
    return e;
  });
  return json({
    catalog: cat.id,
    filters,
    n_events: events.length,
    n_records: events.reduce((a, e) => a + e.n, 0),
    events,
  });
}

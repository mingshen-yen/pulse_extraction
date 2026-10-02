// GET /api/event?catalog=<id>&key=<event key>[&tp_min&tp_max&dist_min&dist_max]
// One event in the same shape as the static file it came from (pipeline:
// data/events/<key>.json, reference: an entry of data/reference/<id>.json),
// with stations narrowed to the filters and stats recomputed for them.
import { getCatalog, json, parseFilters, recordClauses, stats } from "./_lib.js";

export async function onRequestGet({ request, env }) {
  const url = new URL(request.url);
  const cat = await getCatalog(env.DB, url.searchParams.get("catalog"));
  if (!cat) return json({ error: "unknown catalog" }, 404);
  const key = url.searchParams.get("key");

  const row = await env.DB.prepare("SELECT doc FROM events WHERE catalog = ? AND key = ?")
    .bind(cat.id, key)
    .first();
  if (!row) return json({ error: "unknown event" }, 404);

  const filters = parseFilters(url);
  const rec = recordClauses(filters);
  const { results } = await env.DB.prepare(
    `SELECT r.doc FROM records r
      WHERE r.catalog = ? AND r.event_key = ? ${rec.sql.map((c) => `AND ${c}`).join(" ")}
      ORDER BY r.ord`,
  )
    .bind(cat.id, key, ...rec.binds)
    .all();

  const { stats_all, ...doc } = JSON.parse(row.doc);
  const stations = results.map((r) => JSON.parse(r.doc));
  return json({
    ...doc,
    stations,
    stats: rec.sql.length ? stats(stations) : stats_all,
    filters,
  });
}

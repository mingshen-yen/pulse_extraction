// GET /api/catalogs -> { catalogs: [{ id, kind, label, ..., n_events, n_records }] }
import { json } from "./_lib.js";

export async function onRequestGet({ env }) {
  const { results } = await env.DB.prepare(
    `SELECT c.id, c.kind, c.doc,
            (SELECT COUNT(*) FROM events  e WHERE e.catalog = c.id) AS n_events,
            (SELECT COUNT(*) FROM records r WHERE r.catalog = c.id) AS n_records
       FROM catalogs c ORDER BY c.ord`,
  ).all();
  return json({
    catalogs: results.map((c) => ({
      ...JSON.parse(c.doc),
      id: c.id,
      kind: c.kind,
      n_events: c.n_events,
      n_records: c.n_records,
    })),
  });
}

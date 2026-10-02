// GET /api/catalogs -> { catalogs: [{ id, kind, label, ..., n_events, n_records }] }
import { getCatalogs, json, loadEvents } from "./_lib.js";

export async function onRequestGet({ env }) {
  const cats = await getCatalogs(env.DB);
  const out = await Promise.all(
    cats.map(async (c) => {
      const events = await loadEvents(env.DB, c);
      return {
        id: c.id,
        kind: c.kind,
        label: c.label,
        short: c.short,
        url: c.url,
        citation: c.citation,
        pulse_only: c.pulse_only,
        generated: c.updated,
        n_events: events.length,
        n_records: events.reduce((a, e) => a + e.stations.length, 0),
      };
    }),
  );
  return json({ catalogs: out });
}

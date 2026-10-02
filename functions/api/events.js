// GET /api/events?catalog=<id>[&mag_min&mag_max&tp_min&tp_max&dist_min&dist_max]
// Events with at least one record passing the filters; n / n_pulse count the
// matching records only.  Distance is Rrup, else Rhyp.
import {
  eventPasses, getCatalog, json, loadEvents, parseFilters, stationPasses, summary,
} from "./_lib.js";

export async function onRequestGet({ request, env }) {
  const url = new URL(request.url);
  const cat = await getCatalog(env.DB, url.searchParams.get("catalog"));
  if (!cat) return json({ error: "unknown catalog" }, 404);

  const filters = parseFilters(url);
  const filtered = Object.keys(filters).length > 0;
  const events = [];
  for (const e of await loadEvents(env.DB, cat)) {
    if (!eventPasses(e, filters)) continue;
    const stations = e.stations.filter((s) => stationPasses(s, filters));
    if (filtered && !stations.length) continue;
    events.push(summary(e, cat, stations));
  }
  return json({
    catalog: cat.id,
    filters,
    n_events: events.length,
    n_records: events.reduce((a, e) => a + e.n, 0),
    events,
  });
}

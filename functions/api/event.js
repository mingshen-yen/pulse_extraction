// GET /api/event?catalog=<id>&key=<event key>[&tp_min&tp_max&dist_min&dist_max]
// One event with its stations narrowed to the filters and stats for them.
import { document, getCatalog, json, loadEvents, parseFilters, stationPasses } from "./_lib.js";

export async function onRequestGet({ request, env }) {
  const url = new URL(request.url);
  const cat = await getCatalog(env.DB, url.searchParams.get("catalog"));
  if (!cat) return json({ error: "unknown catalog" }, 404);
  const key = url.searchParams.get("key");
  const e = (await loadEvents(env.DB, cat)).find((x) => x.key === key);
  if (!e) return json({ error: "unknown event" }, 404);

  const filters = parseFilters(url);
  return json({ ...document(e, e.stations.filter((s) => stationPasses(s, filters))), filters });
}

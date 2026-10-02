// Types and fetchers for the D1-backed API (functions/api/*).

export interface Catalog {
  id: string;
  kind: "pipeline" | "reference";
  label: string;
  short: string | null;
  url: string | null;
  citation: string | null;
  pulse_only: boolean;
  generated: string | null;
  n_events: number;
  n_records: number;
}

/* one row of /api/events (pipeline rows carry time/mag_type, reference rows year) */
export interface EventSummary {
  key: string;
  name: string;
  year?: string | null;
  time?: string | null;
  lat: number | null;
  lon: number | null;
  mag: number | null;
  mag_type?: string | null;
  n: number;
  n_pulse: number;
}

export interface Station {
  code: string;
  network?: string;
  lat: number | null;
  lon: number | null;
  rrup_km?: number | null;
  rhyp_km?: number | null;
  repi_km?: number | null;
  is_pulse: boolean;
  Tp?: number | null;
  PGV?: number | null;
  PI?: number | null;
  vs30?: number | null;
  angle_deg?: number | null;
  ori_n?: number | null;
  ori_fp?: number | null;
  fling?: boolean | null;
  qc?: string | null;
  summary_url?: string;
  pulse_trace?: { dt: number; v: number[] };
}

export interface ScatterRow {
  code: string;
  rrup_km: number | null;
  rhyp_km: number | null;
  Tp: number | null;
  PGV: number | null;
  is_pulse: boolean;
}

export interface Stats {
  n: number;
  n_pulse: number;
  Tp_median: number | null;
  PGV_median: number | null;
  scatter: ScatterRow[];
}

export interface SourceModel {
  np1: [number, number | null, number | null];
  source: string;
}

/* event as the page shows it, whichever catalog it came from */
export interface EventView {
  key: string;
  catalog: string;
  pulseOnly: boolean;
  pipeline: string | null;
  event: {
    name: string;
    lat: number | null;
    lon: number | null;
    depth_km: number | null;
    mag: number | null;
    mag_type: string;
    time: string | null;
    source: string;
    fault_type?: string | null;
    source_model?: SourceModel;
    usgs_url?: string;
  };
  stations: Station[];
  stats: Stats;
}

export const FILTER_KEYS = ["mag_min", "mag_max", "tp_min", "tp_max", "dist_min", "dist_max"] as const;
export type FilterKey = (typeof FILTER_KEYS)[number];
export type Filters = Partial<Record<FilterKey, number>>;

const getJSON = async <T,>(url: string): Promise<T> => {
  const r = await fetch(url);
  if (!r.ok) throw new Error(`${url}: HTTP ${r.status}`);
  return r.json() as Promise<T>;
};

const query = (filters: Filters, extra: Record<string, string>) =>
  new URLSearchParams({
    ...extra,
    ...Object.fromEntries(Object.entries(filters).map(([k, v]) => [k, String(v)])),
  });

export const fetchCatalogs = () =>
  getJSON<{ catalogs: Catalog[] }>("api/catalogs").then((d) => d.catalogs);

export const fetchEvents = (catalog: string, filters: Filters) =>
  getJSON<{ events: EventSummary[]; n_records: number }>(
    `api/events?${query(filters, { catalog })}`,
  );

/* /api/event returns the stored shape: pipeline events nest the event, reference
   events are flat.  Normalise both to EventView. */
export async function fetchEvent(cat: Catalog, key: string, filters: Filters): Promise<EventView> {
  const d = await getJSON<any>(`api/event?${query(filters, { catalog: cat.id, key })}`);
  if (cat.kind === "pipeline")
    return { key, catalog: cat.id, pulseOnly: false, pipeline: null, event: d.event,
             stations: d.stations, stats: d.stats };
  return {
    key,
    catalog: cat.id,
    pulseOnly: cat.pulse_only,
    pipeline: cat.label,
    event: {
      name: d.name, lat: d.lat, lon: d.lon, depth_km: d.depth_km, mag: d.mag, mag_type: "M",
      time: d.year, source: cat.label, fault_type: d.fault_type,
      source_model: d.source_model, usgs_url: d.usgs_url,
    },
    stations: d.stations,
    stats: d.stats,
  };
}

/* ---------- filters <-> page URL ---------------------------------------- */
export function readFilters(search: string): Filters {
  const p = new URLSearchParams(search);
  const f: Filters = {};
  for (const k of FILTER_KEYS) {
    const v = p.get(k);
    if (v != null && v.trim() !== "" && Number.isFinite(+v)) f[k] = +v;
  }
  return f;
}

export function writeFilters(filters: Filters) {
  const q = query(filters, {}).toString();
  history.replaceState(null, "", location.pathname + (q ? `?${q}` : "") + location.hash);
}

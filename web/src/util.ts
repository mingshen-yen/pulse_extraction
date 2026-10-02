import type { EventSummary, Station } from "./api";

export const PULSE = "#d62728";
export const NOPULSE = "#6b7f99";
export const FAULT = "#ff7f0e";

export const fmt = (x: number | null | undefined, d = 1) =>
  x == null || Number.isNaN(+x) ? "–" : (+x).toFixed(d);

/* distance for every plot: Rrup, or Rhyp when a station has no Rrup */
export const plotDist = (r: { rrup_km?: number | null; rhyp_km?: number | null }) =>
  r.rrup_km != null ? r.rrup_km : r.rhyp_km ?? null;

export const pgvRadius = (pgv?: number | null) => 4 + 9 * Math.sqrt(Math.max(pgv || 0, 0) / 120);

/* pulse polarisation azimuth from North, if the record has one */
export const orientation = (s: Station) => (s.angle_deg != null ? s.angle_deg : s.ori_n ?? null);
export const axis180 = (deg: number) => ((Math.round(deg) % 180) + 180) % 180;

/* newest event first: full ISO time if present, else the 4-digit year */
const evWhen = (e: EventSummary) => String(e.time || e.year || "");
export const byNewest = (events: EventSummary[]) =>
  [...events].sort((a, b) => (evWhen(b) < evWhen(a) ? -1 : evWhen(b) > evWhen(a) ? 1 : 0));

export const evDate = (e: EventSummary) => String(e.time || e.year || "").slice(0, 10);

const evKey = (n: string) =>
  String(n).toLowerCase().replace(/[^a-z0-9]+/g, "_").replace(/^_|_$/g, "");

/* the same earthquake in another catalog: a shared name token, years within 1 */
export function findMatch(list: EventSummary[], name: string, yr: string) {
  const toks = evKey(name)
    .split("_")
    .filter((t) => t.length > 3 && !/^\d{4}$/.test(t));
  return list.find((e) => {
    const k = e.key.split("|")[0];
    const yok = !yr || !e.year || Math.abs(+e.year - +yr) <= 1 || k.includes(yr);
    return yok && toks.some((t) => k.includes(t));
  });
}

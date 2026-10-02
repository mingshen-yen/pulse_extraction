// Unit tests for functions/api/_lib.js:  node --test tests/
// The D1 binding is stood in for by node:sqlite with a minimal prepare/bind/
// all/first/batch shim, so the SQL the API runs is exercised as well.
import assert from "node:assert/strict";
import { DatabaseSync } from "node:sqlite";
import { readFileSync } from "node:fs";
import test from "node:test";

import {
  displayName, document, eventKey, eventPasses, faultModel, getCatalog, loadEvents,
  parseFilters, publicUrl, station, stationPasses, stats, summary,
} from "../functions/api/_lib.js";

function d1(sql) {
  const db = new DatabaseSync(":memory:");
  db.exec(readFileSync(new URL("../db/schema.sql", import.meta.url), "utf8"));
  db.exec(sql);
  const stmt = (q, args = []) => ({
    bind: (...a) => stmt(q, a),
    all: async () => ({ results: db.prepare(q).all(...args) }),
    first: async () => db.prepare(q).get(...args) ?? null,
  });
  return { prepare: (q) => stmt(q), batch: (ss) => Promise.all(ss.map((s) => s.all())) };
}

test("publicUrl keeps http(s) links and drops local paths and prose", () => {
  assert.equal(publicUrl("/Users/name/Desktop/source.png"), null);
  assert.equal(publicUrl("NCREE original table in this workbook"), null);
  assert.equal(publicUrl("file:///tmp/source.fsp"), null);
  assert.ok(publicUrl("https://doi.org/10.1785/0120200376"));
  const usgs = "https://earthquake.usgs.gov/earthquakes/eventpage/us7000irp8";
  assert.equal(publicUrl(usgs, "earthquake.usgs.gov"), usgs);
  assert.equal(publicUrl("https://doi.org/10.1785/0120200376", "earthquake.usgs.gov"), null);
});

test("displayName skips alias-shaped segments", () => {
  assert.equal(displayName("San Fernando | 1971_SanFernando_USA", "x"), "San Fernando");
  assert.equal(displayName("turkey-1 | Pazarcik", "x"), "Pazarcik");
  assert.equal(displayName("CHICHI | Chi-Chi, Taiwan", "x"), "Chi-Chi, Taiwan");
  assert.equal(displayName(null, "2016_kumamoto"), "2016_kumamoto");
  assert.equal(eventKey("Chi-Chi, Taiwan", "1999"), "chi_chi_taiwan|1999");
});

test("station maps a workbook row, treating stored 1/0 as booleans", () => {
  const ev = { hypo_latitude_deg: 24, hypo_longitude_deg: 121 };
  const s = station(
    { station_original: " TCU052 ", latitude_deg: 24.1, longitude_deg: 121,
      closest_distance_km: 0.66, Ipulse_H: 1, fling: 0, Tp_H_s: 9.1234,
      PGV_EW_original: 120, PGV_NS_original: 180.5, coord_status: "matched" },
    ev, "ncree", false,
  );
  assert.equal(s.code, "TCU052");
  assert.equal(s.is_pulse, true);
  assert.equal(s.fling, false);
  assert.equal(s.rrup_km, 0.66);
  assert.equal(s.Tp, 9.123);
  assert.equal(s.PGV, 180.5);
  assert.ok(!("coord_status" in s) && !("summary_url" in s));
  assert.ok(Math.abs(s.repi_km - 11.12) < 0.01);

  const sb = station({ station_key: "k", NGA_RSN: 20, fault_normal_pulse: 0 }, ev, "sb", false);
  assert.equal(sb.code, "k");
  assert.equal(sb.is_pulse, false);
  assert.equal(sb.summary_url, "https://www.jackwbaker.com/pulse_classification_v2/20.html");
  assert.equal(station({ station_key: "k" }, ev, "yen", true).is_pulse, true);
});

test("faultModel prefers finite-fault segments and normalises rake", () => {
  const ev = { hypo_latitude_deg: 38, hypo_longitude_deg: 37, strike1_deg: 30,
               catalog_magnitude: 7.8 };
  const f = faultModel(ev, [
    { strike_deg: 60, dip_deg: 85, model_length_km: 200, model_width_km: 30,
      rake_min_deg: 170, rake_max_deg: 230 },
    { strike_deg: 30, dip_deg: 80, model_length_km: 150, model_width_km: 40 },
  ]);
  assert.equal(f.model, "USGS finite-fault inversion");
  assert.equal(f.length_km, 350);
  assert.equal(f.width_km, 40);
  assert.equal(f.rake, -160);
  assert.equal(f.segments, 2);
  assert.equal(faultModel(ev, []).model, "Wells & Coppersmith (1994) scaling");
  assert.equal(faultModel({}, []), null);
});

test("stats and filters", () => {
  const st = [
    { code: "a", is_pulse: true, Tp: 2, PGV: 50, rrup_km: 5 },
    { code: "b", is_pulse: true, Tp: 4, PGV: 70, rhyp_km: 30 },
    { code: "c", is_pulse: false, Tp: 1, PGV: 20 },
  ];
  const s = stats(st);
  assert.deepEqual([s.n, s.n_pulse, s.pulse_fraction, s.Tp_median, s.PGV_median],
                   [3, 2, 0.667, 3, 60]);
  assert.equal(s.scatter.length, 2); // "c" has no distance
  const f = parseFilters(new URL("http://x/?tp_min=3&dist_max=10&mag_min=abc"));
  assert.deepEqual(f, { tp_min: 3, dist_max: 10 });
  assert.deepEqual(st.filter((x) => stationPasses(x, { dist_max: 10 })).map((x) => x.code), ["a"]);
  assert.deepEqual(st.filter((x) => stationPasses(x, { tp_min: 3 })).map((x) => x.code), ["b"]);
  assert.equal(eventPasses({ mag: null }, { mag_min: 6 }), false);
  assert.equal(eventPasses({ mag: null }, {}), true);
});

test("reference catalog is derived from the workbook tables", async () => {
  const db = d1(`
    CREATE TABLE pulse_records (_row INTEGER PRIMARY KEY, active_sheet, event_source_key,
      station_original, station_key, latitude_deg, longitude_deg, Rrup_km,
      closest_distance_km, Rhyp_km, fault_normal_pulse, Ipulse_H, Tp_s, Tp_H_s, PGV_cm_s,
      PGV_EW_original, PGV_NS_original, vs30_original, orientation_north_deg,
      orientation_fault_parallel_deg, fling, directivity_effect, NGA_RSN, quality_flag,
      coord_status, notes);
    CREATE TABLE event_sources (_row INTEGER PRIMARY KEY, event_source_key, event_key,
      event_names, hypo_latitude_deg, hypo_longitude_deg, hypo_depth_km, catalog_magnitude,
      magnitude_type, mechanism, plane_definition, strike1_deg, dip1_deg, rake1_deg,
      strike2_deg, dip2_deg, rake2_deg, nga_strike_deg, nga_dip_deg, nga_rake_deg,
      nga_length_km, nga_width_km, source_url);
    CREATE TABLE finite_fault_segments (_row INTEGER PRIMARY KEY, event_key, segment,
      strike_deg, dip_deg, model_length_km, model_width_km, rake_min_deg, rake_max_deg);
    INSERT INTO event_sources (event_source_key, event_key, event_names, hypo_latitude_deg,
      hypo_longitude_deg, hypo_depth_km, catalog_magnitude, mechanism, source_url) VALUES
      ('S&B::1999_chichi', '1999_chichi', 'CHICHI | Chi-Chi, Taiwan', 23.85, 120.82, 8, 7.6,
       'Reverse-oblique', '/Users/me/evidence.png'),
      ('S&B::1994_northridge', '1994_northridge', 'Northridge-01', 34.2, -118.54, 17.5, 6.7,
       'Reverse', 'https://earthquake.usgs.gov/earthquakes/eventpage/ci3144585');
    INSERT INTO pulse_records (active_sheet, event_source_key, station_original, latitude_deg,
      longitude_deg, closest_distance_km, fault_normal_pulse, Tp_s, PGV_cm_s, notes) VALUES
      ('S&B', 'S&B::1999_chichi', 'TCU052', 24.2, 120.74, 0.7, 1, 8.4, 216, 'audit note'),
      ('S&B', 'S&B::1999_chichi', 'TCU068', 24.28, 120.77, 0.3, 1, 12.2, 263, NULL),
      ('S&B', 'S&B::1994_northridge', 'Rinaldi', 34.28, -118.48, 6.5, 0, 1.2, 167, NULL),
      ('NCREE', 'NCREE::x', 'other', 0, 0, 1, 1, 1, 1, NULL);
  `);
  const cat = await getCatalog(db, "sb");
  const events = await loadEvents(db, cat);
  assert.deepEqual(events.map((e) => e.key), ["northridge_01|1994", "chi_chi_taiwan|1999"]);
  const chichi = events[1];
  assert.equal(chichi.stations.length, 2);
  assert.equal(chichi.usgs_url, undefined); // local path never published
  assert.equal(events[0].usgs_url, "https://earthquake.usgs.gov/earthquakes/eventpage/ci3144585");
  assert.ok(!JSON.stringify(events).includes("audit note"));

  const f = { tp_min: 10 };
  const kept = chichi.stations.filter((s) => stationPasses(s, f));
  assert.deepEqual(summary(chichi, cat, kept), {
    key: "chi_chi_taiwan|1999", name: "Chi-Chi, Taiwan", year: "1999", lat: 23.85,
    lon: 120.82, depth_km: 8, mag: 7.6, n: 1, n_pulse: 1,
  });
  const doc = document(chichi, kept);
  assert.equal(doc.mag, 7.6);
  assert.equal(doc.stats.Tp_median, 12.2);
});

test("pipeline events round-trip through pipeline_events / pipeline_records", async () => {
  const doc = { schema: "s", pipeline: "p", event: { id: "us1", name: "Somewhere",
    time: "2026-01-01T00:00:00+00:00", mag: 6.5, mag_type: "Mww", lat: 1, lon: 2 } };
  const st = { code: "AB01", is_pulse: true, Tp: 2.5, PGV: 40, rrup_km: 3,
               pulse_trace: { dt: 0.1, v: [0, 1, 0] } };
  const db = d1(`
    INSERT INTO pipeline_events VALUES ('live_us1', 'us1', '${doc.event.time}', 6.5,
      '${JSON.stringify(doc)}', '2026-01-01');
    INSERT INTO pipeline_records VALUES ('live_us1', 0, 'AB01', '${JSON.stringify(st)}');
  `);
  const cat = await getCatalog(db, "pipeline");
  const [e] = await loadEvents(db, cat);
  assert.equal(e.key, "live_us1");
  const s = summary(e, cat, e.stations);
  assert.equal(s.name, "Somewhere");
  assert.equal(s.n_pulse, 1);
  assert.equal(s.has_fault, false);
  const d = document(e, e.stations);
  assert.equal(d.event.mag, 6.5);
  assert.ok(!("mag" in d));
  assert.deepEqual(d.stations[0].pulse_trace.v, [0, 1, 0]);
});

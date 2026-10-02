-- D1 schema for the showcase API (functions/api/*).
-- Rebuilt from scratch on every load: scripts/build_d1_seed.py writes
-- db/seed.sql = this file + INSERTs from site/data/*.json.
--
-- The filterable columns (mag, Tp, dist_km) are real columns with indexes;
-- everything else rides along untouched in `doc` (JSON) so the API returns the
-- same objects as the static files.

DROP TABLE IF EXISTS records;
DROP TABLE IF EXISTS events;
DROP TABLE IF EXISTS catalogs;

CREATE TABLE catalogs (
  id         TEXT PRIMARY KEY,      -- 'pipeline' | 'sb' | 'ncree' | 'yen' ...
  ord        INTEGER NOT NULL,      -- order in the "Data source" selector
  kind       TEXT NOT NULL,         -- 'pipeline' | 'reference'
  doc        TEXT NOT NULL          -- catalog metadata (label, citation, ...)
);

CREATE TABLE events (
  catalog    TEXT NOT NULL REFERENCES catalogs(id),
  key        TEXT NOT NULL,
  ord        INTEGER NOT NULL,      -- original order within the catalog
  mag        REAL,
  doc        TEXT NOT NULL,         -- event without stations / stats
  summary    TEXT NOT NULL,         -- list entry (pipeline: data/index.json row)
  PRIMARY KEY (catalog, key)
);
CREATE INDEX events_mag ON events (catalog, mag);

CREATE TABLE records (
  catalog    TEXT NOT NULL,
  event_key  TEXT NOT NULL,
  ord        INTEGER NOT NULL,      -- original order within the event
  is_pulse   INTEGER NOT NULL,
  Tp         REAL,
  PGV        REAL,
  dist_km    REAL,                  -- Rrup, else Rhyp (the distance every plot uses)
  doc        TEXT NOT NULL,         -- the station object
  FOREIGN KEY (catalog, event_key) REFERENCES events (catalog, key)
);
CREATE INDEX records_event ON records (catalog, event_key);
CREATE INDEX records_tp    ON records (catalog, Tp);
CREATE INDEX records_dist  ON records (catalog, dist_km);

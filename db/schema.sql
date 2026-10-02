-- D1 schema for the showcase API (functions/api/*).  D1 is the source of truth.
--
-- Idempotent: safe to apply to a live database at any time
--   wrangler d1 execute pulse_api --remote --file db/schema.sql --yes
--
-- The workbook tables (pulse_records, event_sources, finite_fault_segments,
-- ...) are created by scripts/import_workbook.py, one table per sheet of
-- pulse_table.xlsx with the sheet's own column names.  The API derives the
-- site's catalogs from them on every request, so edits show up immediately.

-- Catalogs in the "Data source" selector.  Reference catalogs map to the
-- pulse_records rows whose active_sheet equals `active_sheet`.
CREATE TABLE IF NOT EXISTS site_catalogs (
  id           TEXT PRIMARY KEY,
  ord          INTEGER NOT NULL,
  kind         TEXT NOT NULL CHECK (kind IN ('pipeline', 'reference')),
  label        TEXT NOT NULL,
  short        TEXT,
  citation     TEXT,
  url          TEXT,
  pulse_only   INTEGER NOT NULL DEFAULT 0,  -- every record is a pulse (no verdict column)
  active_sheet TEXT,                        -- reference only
  updated      TEXT                         -- pipeline: last run (UTC, ISO 8601)
);
INSERT OR IGNORE INTO site_catalogs VALUES
  ('pipeline', 0, 'pipeline', 'Pipeline results', NULL, NULL, NULL, 0, NULL, NULL),
  ('sb', 1, 'reference', 'S&B', 'S&B 2014',
   'Ground motions in the NGA-West2 database that were identified as pulse-like using the Shahi and Baker (2014) model.',
   'https://www.jackwbaker.com/pulse_classification_v2/Pulse-like-records.html', 0, 'S&B', NULL),
  ('ncree', 2, 'reference', 'NCREE', 'NCREE',
   'Database of Near-Fault Strong Motions with Pulse-like Velocity from NCREE, using the Shahi and Baker (2014) model.',
   'https://nfpv.ncree.org.tw/', 0, 'NCREE', NULL),
  ('yen', 3, 'reference', 'YEN', 'YEN',
   'Identified pulses from Yen et al.(2022), Türker et al. (2024) and Yen et al. (2025), using the Shahi and Baker (2014) model.',
   '', 1, 'YEN', NULL);

-- Pipeline results, written by scripts/build_site_data.py (scripts/d1_pipeline.py).
-- doc holds the nested event / fault / pipeline-settings objects as JSON.
CREATE TABLE IF NOT EXISTS pipeline_events (
  key        TEXT PRIMARY KEY,               -- e.g. 2010_darfield, live_us7000abcd
  usgs_id    TEXT,                           -- event.id, used to skip known events
  time       TEXT,
  mag        REAL,
  doc        TEXT NOT NULL,                  -- {schema, generated, pipeline, event}
  updated    TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS pipeline_records (
  event_key  TEXT NOT NULL REFERENCES pipeline_events (key) ON DELETE CASCADE,
  ord        INTEGER NOT NULL,
  code       TEXT NOT NULL,
  doc        TEXT NOT NULL,                  -- station object incl. pulse_trace
  PRIMARY KEY (event_key, ord)
);

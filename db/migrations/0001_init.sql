-- Showcase-site reference database (Cloudflare D1 / SQLite).
-- Source of truth = references/tables/pulse_table_audited.xlsx, loaded by
-- scripts/load_workbook.py into db/seed.sql, applied with wrangler d1.
--
-- Pipeline events (scripts/build_site_data.py -> waveform FDSN fetch) stay as
-- static JSON in site/data/events/ for now; only the published catalogs live
-- here.

PRAGMA foreign_keys = ON;

-- one row per catalog the "Data source" selector offers -------------------
CREATE TABLE catalogs (
  id            TEXT PRIMARY KEY,     -- 'shahi_baker_2014' | 'taiwan_ncree' | 'yen_2022'
  label         TEXT NOT NULL,
  short         TEXT,
  citation      TEXT,
  url           TEXT,
  pulse_only    INTEGER NOT NULL DEFAULT 0,
  sort_order    INTEGER NOT NULL DEFAULT 0
);

-- event dimension + source model (from sheet Event_sources) ---------------
CREATE TABLE events (
  event_key        TEXT PRIMARY KEY,
  name             TEXT NOT NULL,     -- first of event_names
  names            TEXT,              -- full "A | B" string
  year             INTEGER,
  origin_utc       TEXT,
  mag              REAL,              -- catalog_magnitude
  mag_type         TEXT,
  hypo_lat         REAL,
  hypo_lon         REAL,
  hypo_depth_km    REAL,
  mechanism        TEXT,              -- broad: strike-slip / reverse / normal
  plane_definition TEXT,
  strike1 REAL, dip1 REAL, rake1 REAL,
  strike2 REAL, dip2 REAL, rake2 REAL,
  nga_strike REAL, nga_dip REAL, nga_rake REAL,
  nga_length_km REAL, nga_width_km REAL, nga_ztor_km REAL,
  usgs_event_id    TEXT,
  source_url       TEXT,
  ff_status        TEXT,              -- 'USGS model matched' | 'No matching ...'
  ff_url           TEXT,
  ff_fsp_url       TEXT,
  ff_model_mw      REAL,
  ff_max_slip_m    REAL,
  ff_model_area_km2 REAL,
  ff_segment_count INTEGER
);

-- multi-segment finite-fault geometry (from sheet Finite_fault_segments) --
CREATE TABLE fault_segments (
  event_key    TEXT NOT NULL REFERENCES events(event_key) ON DELETE CASCADE,
  segment      INTEGER NOT NULL,
  strike_deg   REAL, dip_deg REAL,
  length_km    REAL, width_km REAL, area_km2 REAL,
  top_depth_km REAL,
  subfault_count INTEGER,
  max_slip_m   REAL,
  rake_min_deg REAL, rake_max_deg REAL,
  fsp_url      TEXT,
  PRIMARY KEY (event_key, segment)
);

-- station dimension (from sheet Station_coords) -------------------------- --
CREATE TABLE stations (
  station_key   TEXT PRIMARY KEY,
  names         TEXT,
  lat           REAL,
  lon           REAL,
  coord_status  TEXT,
  coord_note    TEXT
);

-- fact table: one row per pulse record (from sheet Pulse_records) ---------
CREATE TABLE pulse_records (
  record_id     TEXT PRIMARY KEY,
  source_sheet  TEXT NOT NULL,       -- raw provenance, kept for every row
  catalog_id    TEXT REFERENCES catalogs(id),   -- NULL = not shown on the site
  event_key     TEXT REFERENCES events(event_key),
  station_key   TEXT REFERENCES stations(station_key),
  station_label TEXT,                -- station_original (display)
  nga_rsn       TEXT,
  lat           REAL,
  lon           REAL,
  coord_status  TEXT,
  mw            REAL,
  tp_s          REAL,                -- COALESCE(Tp_s, Tp_H_s)
  tf_s          REAL,
  pgv_cm_s      REAL,               -- COALESCE(PGV_cm_s, max(PGV_EW,PGV_NS))
  rrup_km       REAL,               -- Rrup_km | closest_distance_km
  rhyp_km       REAL,
  vs30          REAL,
  ori_north_deg REAL,
  ori_fp_deg    REAL,
  is_pulse      INTEGER NOT NULL DEFAULT 0,
  directivity   INTEGER,
  fling         INTEGER,
  quality_flag  TEXT,
  summary_url   TEXT                 -- jackwbaker per-record page (Baker only)
);

CREATE INDEX ix_pr_catalog ON pulse_records(catalog_id);
CREATE INDEX ix_pr_event   ON pulse_records(event_key);
CREATE INDEX ix_seg_event  ON fault_segments(event_key);

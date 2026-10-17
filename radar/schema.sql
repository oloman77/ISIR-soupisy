-- ISIR Radar v1. D1 / SQLite. Import never overwrites manual decisions.
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS properties (
  id TEXT PRIMARY KEY,
  title TEXT NOT NULL,
  property_type TEXT NOT NULL DEFAULT 'nezjištěno',
  district TEXT NOT NULL DEFAULT '',
  municipality TEXT NOT NULL DEFAULT '',
  cadastral_territory TEXT NOT NULL DEFAULT '',
  lv TEXT NOT NULL DEFAULT '',
  parcel TEXT NOT NULL DEFAULT '',
  area_m2 REAL,
  address TEXT NOT NULL DEFAULT '',
  location_confidence TEXT NOT NULL DEFAULT 'unknown'
    CHECK(location_confidence IN ('verified','suggested','unknown')),
  sale_phase TEXT NOT NULL DEFAULT 'unknown'
    CHECK(sale_phase IN ('unknown','preparing','listed','sold')),
  created_at TEXT NOT NULL DEFAULT (datetime('now')),
  updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS property_sources (
  id TEXT PRIMARY KEY,
  property_id TEXT NOT NULL REFERENCES properties(id),
  source_type TEXT NOT NULL,
  external_id TEXT NOT NULL,
  source_title TEXT NOT NULL DEFAULT '',
  source_url TEXT NOT NULL DEFAULT '',
  published_at TEXT,
  found_at TEXT NOT NULL DEFAULT (datetime('now')),
  last_seen_at TEXT NOT NULL DEFAULT (datetime('now')),
  price_czk INTEGER,
  raw_excerpt TEXT NOT NULL DEFAULT '',
  UNIQUE(source_type, external_id)
);

CREATE INDEX IF NOT EXISTS sources_property_idx ON property_sources(property_id);
CREATE INDEX IF NOT EXISTS sources_type_idx ON property_sources(source_type);
CREATE INDEX IF NOT EXISTS properties_district_idx ON properties(district);
CREATE INDEX IF NOT EXISTS properties_municipality_idx ON properties(municipality);

CREATE TABLE IF NOT EXISTS property_decisions (
  property_id TEXT PRIMARY KEY REFERENCES properties(id),
  status TEXT NOT NULL DEFAULT 'new'
    CHECK(status IN ('new','watching','contact','offer_sent','waiting_sale','rejected','archived','acquired')),
  priority TEXT NOT NULL DEFAULT 'normal'
    CHECK(priority IN ('low','normal','high')),
  tags_json TEXT NOT NULL DEFAULT '[]',
  note TEXT NOT NULL DEFAULT '',
  follow_up_date TEXT,
  title_override TEXT,
  district_override TEXT,
  updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS decisions_status_idx ON property_decisions(status);
CREATE INDEX IF NOT EXISTS decisions_priority_idx ON property_decisions(priority);

CREATE TABLE IF NOT EXISTS decision_history (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  property_id TEXT NOT NULL REFERENCES properties(id),
  changed_at TEXT NOT NULL DEFAULT (datetime('now')),
  change_json TEXT NOT NULL
);

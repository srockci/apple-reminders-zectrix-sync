-- Sync mapping table: bidirectional record linkage
CREATE TABLE IF NOT EXISTS sync_records (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    uuid            TEXT    NOT NULL UNIQUE,         -- stable UUID for this sync pair
    source          TEXT    NOT NULL,                 -- 'apple' or 'zectrix'
    source_id       TEXT    NOT NULL,                 -- Apple's reminder UUID or Zectrix's todo ID (as text)
    dest_id         TEXT    NOT NULL,                 -- counterpart ID (apple UUID or zectrix todo id as text)
    title           TEXT    NOT NULL,
    created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    synced_at       TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    -- each record is anchored on one side; the counterpart is inferred
    UNIQUE(source, source_id)
);

CREATE INDEX IF NOT EXISTS idx_sync_uuid       ON sync_records(uuid);
CREATE INDEX IF NOT EXISTS idx_sync_source_id  ON sync_records(source, source_id);
CREATE INDEX IF NOT EXISTS idx_sync_dest_id    ON sync_records(dest_id);
-- 011 scale indexes (no Kafka, no event partitioning through the 200-seat gate)
ALTER TABLE event ADD COLUMN IF NOT EXISTS server_ts TIMESTAMPTZ NOT NULL DEFAULT now();

CREATE INDEX IF NOT EXISTS event_session_ts_idx ON event (session_id, server_ts);
CREATE INDEX IF NOT EXISTS event_org_ts_idx ON event (org_id, server_ts);
CREATE INDEX IF NOT EXISTS session_exam_idx ON session (exam_id);
CREATE INDEX IF NOT EXISTS command_pending_idx ON command (session_id) WHERE status IN ('accepted', 'dispatched');
CREATE INDEX IF NOT EXISTS outbox_unpublished_idx ON outbox (id) WHERE published_at IS NULL;
CREATE INDEX IF NOT EXISTS exam_stream_exam_seq_idx ON exam_stream (exam_id, stream_seq);
CREATE INDEX IF NOT EXISTS ingest_cursor_acked_idx ON ingest_cursor (acked_through);

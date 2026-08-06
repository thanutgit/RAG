-- ============================================================
-- Obsidian RAG — Initial Schema
-- สคริปต์นี้รันอัตโนมัติครั้งเดียว ตอนสร้าง postgres volume ใหม่เท่านั้น
-- ถ้าแก้ไฟล์นี้ทีหลัง ต้อง docker compose down -v แล้ว up ใหม่ (ข้อมูลเดิมหาย)
-- ============================================================

-- เก็บสถานะไฟล์ที่ ingest แล้ว เพื่อทำ incremental sync (ไม่ต้อง re-embed ทั้ง vault)
CREATE TABLE IF NOT EXISTS documents (
    id              BIGSERIAL PRIMARY KEY,
    file_path       TEXT        NOT NULL UNIQUE,
    content_hash    TEXT        NOT NULL,
    chunk_count     INTEGER     NOT NULL DEFAULT 0,
    last_ingested_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_documents_hash ON documents (content_hash);

-- ประวัติการสนทนา
CREATE TABLE IF NOT EXISTS chat_sessions (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    title       TEXT,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS chat_messages (
    id              BIGSERIAL PRIMARY KEY,
    session_id      UUID        NOT NULL REFERENCES chat_sessions(id) ON DELETE CASCADE,
    role            TEXT        NOT NULL CHECK (role IN ('user', 'assistant')),
    content         TEXT        NOT NULL,
    -- metadata สำหรับ observability: โมเดลที่ใช้, chunk ที่ retrieve มา, latency
    model_name      TEXT,
    retrieved_chunks JSONB,
    latency_ms      INTEGER,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_messages_session ON chat_messages (session_id, created_at);

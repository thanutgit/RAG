"""
services/postgres_service.py
เก็บสถานะไฟล์ที่ ingest แล้ว (สำหรับ incremental sync) ผ่าน PostgreSQL
"""

import psycopg2

from services import config


def get_connection():
    """เปิด connection ใหม่ไปยัง PostgreSQL"""
    return psycopg2.connect(**config.PG_CONFIG)


def load_document_state(conn) -> dict[str, str]:
    """ดึงสถานะไฟล์ที่เคย ingest ไว้ทั้งหมด -> {file_path: content_hash}"""
    with conn.cursor() as cur:
        cur.execute("SELECT file_path, content_hash FROM documents")
        return {row[0]: row[1] for row in cur.fetchall()}


def upsert_document_state(conn, file_path: str, content_hash: str, chunk_count: int):
    """บันทึกหรืออัปเดตสถานะไฟล์ (upsert ตาม file_path)"""
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO documents (file_path, content_hash, chunk_count, last_ingested_at)
            VALUES (%s, %s, %s, NOW())
            ON CONFLICT (file_path) DO UPDATE
              SET content_hash = EXCLUDED.content_hash,
                  chunk_count  = EXCLUDED.chunk_count,
                  last_ingested_at = NOW()
            """,
            (file_path, content_hash, chunk_count),
        )
    conn.commit()


def delete_document_state(conn, file_path: str):
    """ลบสถานะไฟล์ (ตอนไฟล์ถูกลบออกจาก vault)"""
    with conn.cursor() as cur:
        cur.execute("DELETE FROM documents WHERE file_path = %s", (file_path,))
    conn.commit()


def log_chat_message(
    conn,
    session_id: str,
    role: str,
    content: str,
    model_name: str = None,
    retrieved_chunks=None,
    latency_ms: int = None,
):
    """บันทึกข้อความแชท (ใช้ตอนต่อ FastAPI endpoint /query)"""
    import json

    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO chat_messages (session_id, role, content, model_name, retrieved_chunks, latency_ms)
            VALUES (%s, %s, %s, %s, %s, %s)
            """,
            (
                session_id,
                role,
                content,
                model_name,
                json.dumps(retrieved_chunks) if retrieved_chunks else None,
                latency_ms,
            ),
        )
    conn.commit()


def ensure_session(conn, session_id: str):
    """สร้าง chat session ถ้ายังไม่มี (กัน foreign key error ตอน log message)"""
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO chat_sessions (id) VALUES (%s) ON CONFLICT (id) DO NOTHING",
            (session_id,),
        )
    conn.commit()


def load_recent_messages(conn, session_id: str, limit: int = 6) -> list[dict]:
    """
    ดึงข้อความล่าสุดของ session นี้ เรียงจากเก่าไปใหม่

    limit นับเป็นจำนวน "ข้อความ" ไม่ใช่จำนวนรอบสนทนา
    6 = ประมาณ 3 รอบถาม-ตอบ ซึ่งพอสำหรับคำถามต่อเนื่องทั่วไป
    โดยไม่ทำให้ prompt ยาวจนช้า
    """
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT role, content FROM chat_messages
            WHERE session_id = %s
            ORDER BY created_at DESC, id DESC
            LIMIT %s
            """,
            (session_id, limit),
        )
        rows = cur.fetchall()
    return [{"role": r[0], "content": r[1]} for r in reversed(rows)]

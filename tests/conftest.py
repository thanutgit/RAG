"""
tests/conftest.py
ตั้งค่าร่วมสำหรับทุก test
"""

import sys
from pathlib import Path

import pytest

# ให้ import จาก root ของโปรเจกต์ได้
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def pytest_configure(config):
    config.addinivalue_line("markers", "llm: ต้องเรียก LLM จริง ใช้เวลานาน (รันด้วย -m llm)")
    config.addinivalue_line("markers", "db: ต้องมี PostgreSQL รันอยู่")


@pytest.fixture(scope="session")
def db_conn():
    """connection ไปยัง PostgreSQL ถ้าต่อไม่ได้ให้ข้าม test ทั้งหมดที่ต้องใช้"""
    from services import postgres_service

    try:
        conn = postgres_service.get_connection()
    except Exception as e:
        pytest.skip(f"เชื่อมต่อ PostgreSQL ไม่ได้: {e}")
    yield conn
    conn.close()


@pytest.fixture(scope="session")
def server_table(db_conn):
    """
    ชื่อตาราง server inventory ที่ใช้ทดสอบ
    ถ้ายังไม่ได้ ingest ให้ข้าม test ที่ต้องใช้
    """
    with db_conn.cursor() as cur:
        cur.execute(
            "SELECT table_name FROM table_catalog WHERE table_name LIKE %s LIMIT 1",
            ("%server_inventory%",),
        )
        row = cur.fetchone()
    if not row:
        pytest.skip("ยังไม่ได้ ingest server_inventory.csv")
    return row[0]

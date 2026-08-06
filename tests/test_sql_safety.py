"""
tests/test_sql_safety.py
ทดสอบตัวตรวจและตัวซ่อม SQL — ไม่ต้องเรียก LLM จึงเร็วมาก (< 1 วินาที)

test พวกนี้ครอบบั๊กที่เคยเจอจริง เพื่อไม่ให้กลับมาอีกตอนแก้ prompt
"""

import pytest

from services.sql_service import (
    SQLError,
    _clean_sql,
    extract_table_names,
    fix_known_mistakes,
    strip_unrequested_filters,
    summarize_for_llm,
    validate_sql,
    validate_tables_exist,
)

# ---------------------------------------------------------------- validate


@pytest.mark.parametrize(
    "sql",
    [
        'SELECT COUNT(*) FROM "t"',
        'SELECT "a", COUNT(*) FROM "t" GROUP BY "a" ORDER BY 2 DESC LIMIT 1',
        '  select * from "t" where "x" = 1  ',
    ],
)
def test_allows_select(sql):
    validate_sql(sql.strip())


@pytest.mark.parametrize(
    "sql,reason",
    [
        ('DROP TABLE "t"', "คำสั่งทำลายข้อมูล"),
        ('DELETE FROM "t"', "คำสั่งลบข้อมูล"),
        ('UPDATE "t" SET "a" = 1', "คำสั่งแก้ข้อมูล"),
        ('INSERT INTO "t" VALUES (1)', "คำสั่งเพิ่มข้อมูล"),
        ('SELECT * FROM "t"; DROP TABLE "t"', "หลายคำสั่งในครั้งเดียว"),
        ("SELECT * FROM pg_user", "อ่านตารางระบบ"),
        ("SELECT * FROM information_schema.tables", "อ่าน schema ระบบ"),
        ("", "คำสั่งว่าง"),
    ],
)
def test_rejects_dangerous_statements(sql, reason):
    with pytest.raises(SQLError):
        validate_sql(sql)


# ---------------------------------------------------------------- fix_known_mistakes


def test_fixes_window_function_with_groupby():
    """
    บั๊กจริง: COUNT(*) OVER () ทำงานหลัง GROUP BY จึงนับจำนวนกลุ่ม (5 ทีม)
    แทนจำนวนสมาชิกในกลุ่ม (66 server)
    """
    bad = (
        'SELECT "owner_team", COUNT(*) OVER () AS total FROM "t" '
        'GROUP BY "owner_team" ORDER BY total DESC LIMIT 1'
    )
    fixed = fix_known_mistakes(bad)
    assert "OVER" not in fixed.upper()
    assert "COUNT(*)" in fixed


def test_keeps_valid_window_function():
    """COUNT(*) OVER () ใช้ได้ถ้าไม่มี GROUP BY"""
    ok = 'SELECT "hostname", COUNT(*) OVER () AS total FROM "t" WHERE "env" = \'prod\''
    assert fix_known_mistakes(ok) == ok


# ---------------------------------------------------------------- strip_unrequested_filters


def test_strips_unrequested_filter():
    """
    บั๊กจริง: schema บอกว่า status มีค่า 'running' -> LLM ใส่ WHERE ทุกครั้ง
    ทำให้ถาม "ทีมไหนดูแลมากที่สุด" ได้ channel 41 แทน payments 66
    """
    sql = (
        'SELECT "owner_team", COUNT(*) AS total FROM "t" '
        'WHERE "status" = \'running\' GROUP BY "owner_team" ORDER BY total DESC LIMIT 1'
    )
    cleaned, removed = strip_unrequested_filters(sql, "ทีมไหนดูแล server มากที่สุด")
    assert removed, "ควรตัดเงื่อนไข status ออก"
    assert "WHERE" not in cleaned.upper()
    assert "GROUP BY" in cleaned.upper(), "ส่วนอื่นของ query ต้องอยู่ครบ"


@pytest.mark.parametrize(
    "question",
    [
        "ทีมไหนดูแล server ที่ running มากที่สุด",  # ระบุค่า
        "ทีมไหนดูแล server แยกตาม status",  # ระบุชื่อคอลัมน์
    ],
)
def test_keeps_requested_filter(question):
    sql = 'SELECT "owner_team", COUNT(*) AS total FROM "t" WHERE "status" = \'running\' GROUP BY "owner_team"'
    cleaned, removed = strip_unrequested_filters(sql, question)
    assert not removed
    assert cleaned == sql


def test_noop_without_where():
    sql = 'SELECT COUNT(*) FROM "t"'
    cleaned, removed = strip_unrequested_filters(sql, "มีกี่แถว")
    assert cleaned == sql and not removed


# ---------------------------------------------------------------- _clean_sql


@pytest.mark.parametrize(
    "raw,expected_start",
    [
        ("```sql\nSELECT 1\n```", "SELECT"),
        ("```\nSELECT 1\n```", "SELECT"),
        ("นี่คือคำสั่ง:\nSELECT 1", "SELECT"),
        ("SELECT 1;", "SELECT"),
    ],
)
def test_cleans_llm_output(raw, expected_start):
    out = _clean_sql(raw)
    assert out.upper().startswith(expected_start)
    assert "```" not in out
    assert not out.endswith(";")


# ---------------------------------------------------------------- summarize_for_llm


def test_summarizes_scalar_result():
    assert summarize_for_llm(["count"], [(76,)], 76) == "count = 76"


def test_reports_true_count_when_truncated():
    """
    บั๊กจริง: ส่งรายการที่ถูกตัดไปให้ LLM แล้วมันนับเอง ได้ตัวเลขผิด
    ต้องบอกจำนวนจริงเสมอ
    """
    rows = [(f"host-{i}",) for i in range(8)]
    out = summarize_for_llm(["hostname"], rows, total_rows=172)
    assert "172" in out
    assert "ห้าม" in out, "ต้องมีคำเตือนไม่ให้นับเอง"


def test_sends_full_small_result():
    rows = [("payments", 66), ("channel", 64)]
    out = summarize_for_llm(["owner_team", "total"], rows, total_rows=2)
    assert "payments" in out and "channel" in out


# ---------------------------------------------------------------- table names


def test_extracts_table_names():
    sql = 'SELECT * FROM "data_a_a" JOIN "data_b_b" ON 1=1'
    assert extract_table_names(sql) == {"data_a_a", "data_b_b"}


def test_rejects_unknown_table():
    """
    บั๊กจริง: LLM เดาชื่อตารางเป็น "data_messy_data" ทั้งที่ชื่อจริงคือ
    "data_messy_data_messy_data" ทำให้พังด้วย UndefinedTable ดิบ ๆ
    ต้องจับได้ก่อนรันแล้วแปลงเป็น SQLError ที่บอกผู้ใช้ได้
    """
    known = {"data_a_a", "data_b_b"}
    validate_tables_exist('SELECT * FROM "data_a_a"', known)

    with pytest.raises(SQLError, match="ไม่มีอยู่"):
        validate_tables_exist('SELECT * FROM "data_a"', known)

"""
tests/test_sql_e2e.py
ทดสอบ text-to-SQL แบบ end-to-end โดยเรียก LLM จริง

ช้ากว่า test_sql_safety มาก (~2-4 นาที) จึงแยกไฟล์และ mark ไว้
รันด้วย: pytest tests/test_sql_e2e.py -v

ต้องมี: PostgreSQL รันอยู่ + ingest ข้อมูลแล้ว + Ollama รันอยู่

ค่าเฉลยคำนวณจากไฟล์ทดสอบจริง ไม่ใช่เดา
"""

import pytest

pytestmark = [pytest.mark.llm, pytest.mark.db]


# (question, must_contain, must_not_contain, note)
CASES = [
    (
        "server ที่อยู่ใน production มีกี่เครื่อง",
        ["76"],
        ["23"],
        "นับรวมพื้นฐาน — เคยตอบ 23 ตอนยังไม่มี SQL",
    ),
    (
        "server ที่ status เป็น running มีกี่เครื่อง",
        ["172"],
        ["29"],
        "นับด้วยเงื่อนไข — เคยตอบ 29",
    ),
    (
        "ทีมไหนดูแล server มากที่สุด",
        ["payments", "66"],
        ["channel", "41", "5"],
        "GROUP BY โดยไม่มีเงื่อนไข — เคยตอบ channel 41 เพราะใส่ WHERE เอง",
    ),
    (
        "ทีมไหนดูแล server ที่ running มากที่สุด",
        ["channel", "41"],
        [],
        "GROUP BY โดยคำถามระบุเงื่อนไขเอง — ต้องไม่ถูกตัด WHERE ทิ้ง",
    ),
    (
        "server ที่อยู่ใน production มีกี่เครื่องและมีเครื่องอะไรบ้าง",
        ["76"],
        ["113"],
        # ไม่ใส่ "5" ในรายการต้องห้าม เพราะไปตรงกับชื่อ server อย่าง cache-prod-005
        # การเช็คด้วย substring ต้องระวังค่าที่สั้นเกินไป
        "นับพร้อมดึงรายการ — เคยตอบ 113 เพราะ LLM นับจากรายการเอง",
    ),
    (
        "server ที่ RAM 128GB มีกี่เครื่อง",
        ["35"],
        [],
        "กรองด้วยตัวเลข",
    ),
]


def _run(question: str):
    from services.sql_service import run_sql_query

    return run_sql_query(question)


@pytest.mark.parametrize("question,must_contain,must_not_contain,note", CASES)
def test_calculation_answers_are_correct(question, must_contain, must_not_contain, note, server_table):
    from services.sql_service import SQLError

    try:
        r = _run(question)
    except SQLError as e:
        pytest.fail(f"{note}\nสร้าง SQL ไม่สำเร็จ: {e}")

    haystack = f"{r['result_text']} {r['total_rows']}".lower()

    missing = [v for v in must_contain if v.lower() not in haystack]
    assert not missing, f"{note}\nไม่พบค่าที่คาดหวัง: {missing}\nSQL: {r['sql']}\nผลลัพธ์: {r['result_text'][:400]}"

    found_bad = [v for v in must_not_contain if v.lower() in haystack]
    assert not found_bad, (
        f"{note}\n"
        f"พบค่าที่ไม่ควรมี (น่าจะเป็นคำตอบผิดแบบเดิม): {found_bad}\n"
        f"SQL: {r['sql']}\n"
        f"ผลลัพธ์: {r['result_text'][:400]}"
    )


@pytest.mark.parametrize(
    "question",
    [
        "server ตัวไหนมีปัญหาบ่อยที่สุด",
        "เงินเดือนของวิภา ขยัน ขึ้นกี่เปอร์เซ็นต์ปีนี้",
    ],
)
def test_unanswerable_must_not_guess(question, server_table):
    """
    คำถามที่ข้อมูลไม่มีในระบบ ต้อง raise SQLError หรือได้ผลว่างเปล่า
    ห้ามแต่งตัวเลขขึ้นมา
    """
    from services.sql_service import SQLError

    try:
        r = _run(question)
    except SQLError:
        return  # ถูกต้อง — บอกว่าตอบไม่ได้
    assert r["total_rows"] == 0, f"ควรตอบไม่ได้ แต่ได้ผลลัพธ์มา\nSQL: {r['sql']}\n{r['result_text'][:300]}"


def test_routing_picks_correct_path(server_table):
    """คำถามเชิงเนื้อหาไม่ควรไปทาง SQL"""
    from services.sql_service import needs_sql

    calc_questions = ["server ใน production มีกี่เครื่อง", "ทีมไหนดูแลมากที่สุด"]
    content_questions = ["ทำพะแนงไก่ยังไง", "INC-001 แก้ปัญหายังไง"]

    for q in calc_questions:
        assert needs_sql(q, True), f"ควรไปทาง SQL: {q}"
    for q in content_questions:
        assert not needs_sql(q, True), f"ไม่ควรไปทาง SQL: {q}"

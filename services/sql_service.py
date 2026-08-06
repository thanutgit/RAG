"""
services/sql_service.py
แปลงคำถามภาษาคนเป็น SQL แล้วรันบนข้อมูลจริง

ใช้กับคำถามที่ต้องเห็นข้อมูลครบทั้งชุด เช่น นับจำนวน รวมยอด หาค่าสูงสุด เรียงลำดับ
ซึ่ง vector search ทำไม่ได้เพราะดึงมาแค่บางส่วน

ความปลอดภัย: LLM เขียน SQL เองได้ แต่ต้องผ่านการตรวจก่อนรันเสมอ
"""

import re

import requests

from services import postgres_service, tabular_service

STATEMENT_TIMEOUT_MS = 5000  # กัน query ที่กินเวลานานผิดปกติ

# แยกขีดจำกัดสองระดับ เพราะผู้ใช้กับ LLM ต้องการคนละอย่าง:
MAX_ROWS_TO_CLIENT = 1000  # ส่งให้หน้าเว็บแสดงเป็นตาราง — เยอะได้ ไม่กินอะไร
MAX_ROWS_TO_LLM = 8  # ส่งให้ LLM อ่าน — ต้องน้อย เพราะกิน token และช้า
# LLM ไม่ต้องเห็นทุกแถวอยู่แล้ว แค่รู้จำนวนกับตัวอย่างก็พอ

# คำสั่งที่ห้ามปรากฏใน SQL เด็ดขาด
_FORBIDDEN = re.compile(
    r"\b(insert|update|delete|drop|alter|create|truncate|grant|revoke|"
    r"copy|vacuum|reindex|call|do|execute|listen|notify)\b",
    re.IGNORECASE,
)


class SQLError(Exception):
    """สร้างหรือรัน SQL ไม่สำเร็จ"""


ROUTER_PROMPT = """คุณมีหน้าที่ตัดสินว่าคำถามนี้ต้องคำนวณจากข้อมูลตารางทั้งชุดหรือไม่

ตอบ SQL ถ้าคำถามเกี่ยวกับ:
- นับจำนวน (มีกี่อัน, กี่เครื่อง, กี่คน)
- รวมยอด เฉลี่ย (รวมเท่าไหร่, เฉลี่ยเท่าไหร่)
- หาค่าสูงสุด/ต่ำสุดที่แท้จริง (มากที่สุด, น้อยที่สุด)
- เปรียบเทียบหรือจัดอันดับข้ามหลายแถว (อันไหนมากกว่า, เรียงลำดับ, top 5)
- กรองด้วยเงื่อนไขแล้วนับ (ที่มีสถานะ X มีกี่อัน)

ตอบ SEARCH ถ้าคำถามเกี่ยวกับ:
- หาข้อมูลเฉพาะเจาะจง (ราคาเท่าไหร่, แก้ปัญหายังไง)
- อธิบาย สรุป หรือเนื้อหาที่เป็นข้อความ
- คำถามที่ไม่เกี่ยวกับข้อมูลตาราง

ตอบด้วยคำเดียวเท่านั้น: SQL หรือ SEARCH"""


SQL_PROMPT = """คุณเป็นผู้เชี่ยวชาญ PostgreSQL แปลงคำถามเป็นคำสั่ง SELECT

Schema ที่มี:
{schema}

ศึกษาตัวอย่างต่อไปนี้แล้วทำตามรูปแบบเดียวกัน:

--- ตัวอย่างที่ 1: นับรวมทั้งหมด ---
คำถาม: server ใน production มีกี่เครื่อง
SQL: SELECT COUNT(*) FROM "data_servers" WHERE "environment" = 'production'

--- ตัวอย่างที่ 2: แยกนับตามกลุ่ม แล้วหาอันดับหนึ่ง ---
คำถาม: ทีมไหนดูแล server มากที่สุด
SQL: SELECT "owner_team", COUNT(*) AS total FROM "data_servers" GROUP BY "owner_team" ORDER BY total DESC LIMIT 1

หมายเหตุ: ไม่มี WHERE เพราะคำถามไม่ได้ระบุเงื่อนไขใด ๆ
และใช้ COUNT(*) ธรรมดา ไม่ใช่ COUNT(*) OVER () เพราะมี GROUP BY

--- ตัวอย่างที่ 3: แยกนับตามกลุ่ม โดยคำถามระบุเงื่อนไขเอง ---
คำถาม: ทีมไหนดูแล server ที่ running มากที่สุด
SQL: SELECT "owner_team", COUNT(*) AS total FROM "data_servers" WHERE "status" = 'running' GROUP BY "owner_team" ORDER BY total DESC LIMIT 1

--- ตัวอย่างที่ 4: ดึงรายการพร้อมจำนวนรวม ---
คำถาม: server ใน production มีกี่เครื่องและมีอะไรบ้าง
SQL: SELECT "hostname", COUNT(*) OVER () AS total FROM "data_servers" WHERE "environment" = 'production'

หมายเหตุ: ใช้ COUNT(*) OVER () ได้เฉพาะกรณีนี้ คือ query ที่ไม่มี GROUP BY

--- ตัวอย่างที่ 5: รวมยอด ---
คำถาม: รายจ่ายเดือนมกราคมรวมเท่าไหร่
SQL: SELECT SUM("amount") AS total FROM "data_expenses" WHERE "month" = 'มกราคม' AND "type" = 'รายจ่าย'

--- ตัวอย่างที่ 6: หาค่าสูงสุด ---
คำถาม: อุณหภูมิสูงสุดที่วัดได้เท่าไหร่
SQL: SELECT MAX("temp_c") AS max_temp FROM "data_sensors"

--- ตัวอย่างที่ 7: ตอบไม่ได้ ---
คำถาม: server ตัวไหนมีปัญหาบ่อยที่สุด
SQL: NO_ANSWER

หมายเหตุ: schema ไม่มีข้อมูลประวัติปัญหา จึงตอบไม่ได้

กติกา:
- ใส่ double quote รอบชื่อตารางและคอลัมน์เสมอ
- ใช้ค่าที่ระบุใน "ค่าที่มี" เท่านั้น ห้ามเดาค่าเอง
- รายการ "ค่าที่มี" มีไว้ให้เขียนค่าถูกตอนคำถามระบุเงื่อนไข ไม่ได้แปลว่าต้องใส่ WHERE ทุกครั้ง
- ตอบเป็นคำสั่ง SQL ล้วน ไม่มีคำอธิบาย ไม่มี markdown code fence

คำถาม: {question}
SQL:"""


def _ask(prompt: str, system: str = None, num_predict: int = 300) -> str:
    """
    เรียก LLM สำหรับงาน routing และ generate SQL

    ใช้ ask_raw ไม่ใช่ ask_llm เพราะ ask_llm มี system prompt ของ RAG ติดมา
    ซึ่งสั่งให้ "ตอบคำถามจากโน้ต" — ทำให้โมเดลพยายามตอบคำถามแทนที่จะเขียน SQL
    """
    from services.ollama_service import ask_raw

    return ask_raw(prompt, system=system, num_predict=num_predict)


def needs_sql(question: str, has_tables: bool) -> bool:
    """ตัดสินว่าคำถามนี้ควรไปทาง SQL หรือ vector search"""
    if not has_tables:
        return False

    try:
        answer = _ask(question, system=ROUTER_PROMPT, num_predict=10)
    except requests.exceptions.RequestException:
        return False  # เรียก LLM ไม่ได้ -> ใช้ทางเดิม (vector search) ไว้ก่อน

    return "SQL" in answer.upper()


def _clean_sql(raw: str) -> str:
    """ตัด markdown fence และคำอธิบายที่ LLM ชอบใส่มาเกิน"""
    text = raw.strip()
    text = re.sub(r"^```(?:sql)?\s*", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\s*```$", "", text)

    # บางครั้ง LLM ใส่คำอธิบายก่อน/หลัง — ตัดเอาเฉพาะตั้งแต่ SELECT ตัวแรก
    m = re.search(r"\bSELECT\b", text, re.IGNORECASE)
    if m:
        text = text[m.start() :]

    return text.strip().rstrip(";").strip()


_WINDOW_WITH_GROUPBY = re.compile(
    r"COUNT\s*\(\s*\*\s*\)\s*OVER\s*\(\s*\)[\s\S]*\bGROUP\s+BY\b",
    re.IGNORECASE,
)


def fix_known_mistakes(sql: str) -> str:
    """
    แก้รูปแบบ SQL ที่ LLM เขียนผิดซ้ำ ๆ

    COUNT(*) OVER () + GROUP BY เป็นกับดักที่เจอจริง: window function ทำงาน
    หลัง GROUP BY จึงนับ "จำนวนกลุ่ม" แทน "จำนวนสมาชิกในกลุ่ม"
    ทดสอบพบว่าถาม "ทีมไหนดูแล server มากที่สุด" ได้ 5 (จำนวนทีม) แทน 66 (จำนวน server)
    """
    if _WINDOW_WITH_GROUPBY.search(sql):
        sql = re.sub(
            r"COUNT\s*\(\s*\*\s*\)\s*OVER\s*\(\s*\)",
            "COUNT(*)",
            sql,
            flags=re.IGNORECASE,
        )
    return sql


def extract_table_names(sql: str) -> set[str]:
    """ดึงชื่อตารางที่ SQL อ้างถึง (รองรับทั้งแบบ quote และไม่ quote)"""
    names = set()
    for m in re.finditer(r'\b(?:FROM|JOIN)\s+(?:"([^"]+)"|([A-Za-z_][A-Za-z0-9_]*))', sql, re.IGNORECASE):
        names.add(m.group(1) or m.group(2))
    return names


def validate_tables_exist(sql: str, known_tables: set[str]):
    """
    ตรวจว่าตารางที่ SQL อ้างถึงมีอยู่จริง

    LLM ชอบเดาชื่อตารางจากชื่อไฟล์ เช่นเขียน "data_messy_data"
    ทั้งที่ชื่อจริงคือ "data_messy_data_messy_data"
    ถ้าไม่ตรวจ จะพังด้วย UndefinedTable ดิบ ๆ แทนที่จะบอกผู้ใช้ว่าตอบไม่ได้
    """
    referenced = extract_table_names(sql)
    unknown = referenced - known_tables
    if unknown:
        raise SQLError(
            f"อ้างถึงตารางที่ไม่มีอยู่: {', '.join(sorted(unknown))} (ตารางที่มี: {', '.join(sorted(known_tables))})"
        )


def validate_sql(sql: str):
    """
    ตรวจ SQL ก่อนรัน ถ้าไม่ผ่านให้ throw ทันที

    หลักการ: อนุญาตเฉพาะสิ่งที่รู้ว่าปลอดภัย (allowlist) ไม่ใช่ห้ามสิ่งที่รู้ว่าอันตราย
    เพราะรายการสิ่งอันตรายไม่มีวันครบ
    """
    if not sql:
        raise SQLError("ไม่ได้รับคำสั่ง SQL")

    if not re.match(r"^\s*SELECT\b", sql, re.IGNORECASE):
        raise SQLError("อนุญาตเฉพาะคำสั่ง SELECT เท่านั้น")

    if ";" in sql:
        raise SQLError("ห้ามมีหลายคำสั่งในครั้งเดียว")

    if _FORBIDDEN.search(sql):
        raise SQLError("พบคำสั่งที่ไม่อนุญาตใน SQL")

    # กันการอ่านตารางระบบของ PostgreSQL
    if re.search(r"\b(pg_|information_schema)", sql, re.IGNORECASE):
        raise SQLError("ห้ามเข้าถึงตารางระบบ")


def strip_unrequested_filters(sql: str, question: str) -> tuple[str, list[str]]:
    """
    ตัดเงื่อนไข WHERE ที่ใช้ค่าซึ่งคำถามไม่ได้พูดถึง

    ปัญหาที่แก้: schema บอก LLM ว่าคอลัมน์ status มีค่า 'running', 'stopped'
    เพื่อให้เขียนค่าถูกตอนที่คำถามระบุ แต่ LLM กลับเอาไปใส่ทุกครั้ง
    เจอจริง: ถาม "ทีมไหนดูแล server มากที่สุด" ได้ channel 41 (นับเฉพาะ running)
    แทนที่จะเป็น payments 66 (นับทั้งหมด)

    คืน (sql ที่แก้แล้ว, รายการเงื่อนไขที่ตัดออก)
    """
    where_match = re.search(
        r"\bWHERE\b(.*?)(?=\bGROUP\s+BY\b|\bORDER\s+BY\b|\bLIMIT\b|$)", sql, re.IGNORECASE | re.DOTALL
    )
    if not where_match:
        return sql, []

    where_body = where_match.group(1)
    q_lower = question.lower()

    # หาเงื่อนไขรูปแบบ "col" = 'value' ทั้งหมด
    conditions = re.findall(r'"([^"]+)"\s*=\s*\'([^\']+)\'', where_body)
    unrequested = [
        (col, val) for col, val in conditions if val.lower() not in q_lower and col.lower() not in q_lower
    ]

    if not unrequested or len(unrequested) < len(conditions):
        # ตัดเฉพาะกรณีที่ "ทุกเงื่อนไข" ไม่ถูกพูดถึง เพื่อไม่ให้ทำ query พังกลางคัน
        return sql, []

    # ตัด WHERE ทั้งก้อนออก
    cleaned = sql[: where_match.start()] + " " + sql[where_match.end() :]
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned, [f"{c} = {v}" for c, v in unrequested]


def generate_sql(question: str, schema: str, known_tables: set[str] = None) -> str:
    """ให้ LLM เขียน SQL จากคำถามและ schema"""
    raw = _ask(SQL_PROMPT.format(schema=schema, question=question), num_predict=400)

    if "NO_ANSWER" in raw.upper():
        raise SQLError("ไม่สามารถตอบคำถามนี้จากข้อมูลตารางที่มี")

    sql = fix_known_mistakes(_clean_sql(raw))

    sql, removed = strip_unrequested_filters(sql, question)
    if removed:
        print(f"   ℹ️  ตัดเงื่อนไขที่คำถามไม่ได้ระบุออก: {', '.join(removed)}")

    validate_sql(sql)
    if known_tables:
        validate_tables_exist(sql, known_tables)
    return sql


def execute_sql(conn, sql: str) -> tuple[list[str], list[tuple], int]:
    """
    รัน SQL ใน read-only transaction พร้อม timeout
    คืน (ชื่อคอลัมน์, แถวข้อมูลที่ตัดแล้ว, จำนวนแถวจริงทั้งหมด)

    ต้องรู้จำนวนแถวจริงก่อนตัด เพราะถ้าบอก LLM แค่แถวที่เหลือ
    มันจะนับจากที่เห็นแล้วได้ตัวเลขผิด ซึ่งเป็นปัญหาเดียวกับที่ SQL ควรจะแก้
    """
    with conn.cursor() as cur:
        # read-only + timeout เป็นชั้นป้องกันที่สอง เผื่อ validate หลุด
        cur.execute(f"SET LOCAL statement_timeout = {STATEMENT_TIMEOUT_MS}")
        cur.execute("SET TRANSACTION READ ONLY")
        cur.execute(sql)
        columns = [d[0] for d in cur.description]
        all_rows = cur.fetchall()
    conn.rollback()  # ไม่มีอะไรให้ commit และปลดล็อก read-only
    return columns, all_rows[:MAX_ROWS_TO_CLIENT], len(all_rows)


def summarize_for_llm(columns: list[str], rows: list[tuple], total_rows: int) -> str:
    """
    สรุปผลลัพธ์แบบสั้นสำหรับให้ LLM เรียบเรียงเป็นคำตอบ

    ตั้งใจไม่ส่งข้อมูลทั้งหมด เพราะ:
      1. LLM ไม่จำเป็นต้องเห็นทุกแถวเพื่อเขียนคำตอบหนึ่งย่อหน้า
      2. ส่งเยอะ = ช้าและเปลือง token (172 แถวใช้เวลา 23 วินาที)
      3. ตารางเต็มถูกส่งให้หน้าเว็บแสดงเองอยู่แล้ว ไม่ต้องผ่าน LLM
    """
    if not rows:
        return "ไม่พบข้อมูลที่ตรงกับเงื่อนไข"

    # ผลลัพธ์ค่าเดียว (COUNT, SUM, MAX) -> บอกตรง ๆ
    if len(rows) == 1 and len(columns) == 1:
        return f"{columns[0]} = {rows[0][0]}"

    # ผลลัพธ์เป็นตารางเล็ก (เช่น GROUP BY) -> ส่งทั้งหมดได้
    if total_rows <= MAX_ROWS_TO_LLM:
        lines = [" | ".join(columns), " | ".join("---" for _ in columns)]
        for r in rows:
            lines.append(" | ".join("" if v is None else str(v) for v in r))
        return "\n".join(lines)

    # ผลลัพธ์เป็นรายการยาว -> ส่งแค่จำนวนกับตัวอย่าง
    sample = rows[:MAX_ROWS_TO_LLM]
    lines = [
        f"จำนวนแถวทั้งหมดที่ตรงเงื่อนไข: {total_rows}",
        "",
        f"ตัวอย่าง {len(sample)} แถวแรก:",
        " | ".join(columns),
        " | ".join("---" for _ in columns),
    ]
    for r in sample:
        lines.append(" | ".join("" if v is None else str(v) for v in r))

    lines += [
        "",
        f"หมายเหตุ: นี่เป็นเพียงตัวอย่าง ข้อมูลจริงมี {total_rows} แถว",
        f"ให้ตอบโดยใช้เลข {total_rows} และบอกว่ารายการทั้งหมดแสดงอยู่ในตารางด้านล่างคำตอบ",
        "ห้ามไล่รายชื่อทีละรายการในคำตอบ และห้ามนับจากตัวอย่างข้างบน",
    ]
    return "\n".join(lines)


def run_sql_query(question: str) -> dict:
    """
    รัน pipeline ฝั่ง SQL เต็มรูปแบบ: schema -> generate -> validate -> execute
    คืน dict ที่มี sql, result, columns, rows
    """
    conn = postgres_service.get_connection()
    try:
        schema = tabular_service.get_schema_description(conn)
        if not schema:
            raise SQLError("ยังไม่มีข้อมูลตารางในระบบ")

        known_tables = {t["table"] for t in tabular_service.list_tables(conn)}
        sql = generate_sql(question, schema, known_tables)

        try:
            columns, rows, total = execute_sql(conn, sql)
        except Exception as e:
            conn.rollback()
            # ให้ LLM แก้ SQL อีกครั้งโดยบอก error ที่เกิดขึ้น
            retry_prompt = (
                f"{SQL_PROMPT.format(schema=schema, question=question)}\n"
                f"{sql}\n\n"
                f"คำสั่งข้างบนรันแล้วเกิด error: {e}\n"
                f"เขียนคำสั่ง SELECT ใหม่ที่ถูกต้อง:"
            )
            sql = fix_known_mistakes(_clean_sql(_ask(retry_prompt, num_predict=400)))
            validate_sql(sql)
            validate_tables_exist(sql, known_tables)
            try:
                columns, rows, total = execute_sql(conn, sql)
            except Exception as e2:
                conn.rollback()
                # ลองแก้แล้วยังไม่ได้ -> บอกว่าตอบไม่ได้ ดีกว่าโยน exception ดิบ
                raise SQLError(f"รัน SQL ไม่สำเร็จหลังลองแก้แล้ว: {e2}") from e2

        return {
            "sql": sql,
            "columns": columns,
            "rows": [[None if v is None else str(v) for v in r] for r in rows],
            "total_rows": total,
            "truncated": total > len(rows),
            "result_text": summarize_for_llm(columns, rows, total),
        }
    finally:
        conn.close()

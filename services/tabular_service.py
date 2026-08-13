"""
services/tabular_service.py
โหลดข้อมูลจาก CSV/Excel เข้า PostgreSQL เป็นตารางจริง เพื่อให้ query ด้วย SQL ได้

ทำไมต้องมี:
  RAG ดึงข้อมูลมาแค่ไม่กี่ chunk แล้วให้ LLM อ่าน ซึ่งใช้ไม่ได้กับคำถามที่ต้อง
  "เห็นข้อมูลทั้งหมด" เช่นนับจำนวน รวมยอด หาค่าสูงสุด
  ทดสอบจริงพบว่าถาม "server ใน production มีกี่เครื่อง" (คำตอบ 76)
  ระบบตอบ 23 เพราะเห็นข้อมูลแค่ 5 จาก 49 chunks

  การเก็บลง SQL ด้วยทำให้คำถามประเภทนี้คำนวณจากข้อมูลครบถ้วนได้
"""

import hashlib
import re
from pathlib import Path

# ตารางข้อมูลทั้งหมดใช้ prefix นี้ เพื่อแยกจากตารางระบบ (documents, chat_messages)
TABLE_PREFIX = "data_"
MAX_IDENT = 55  # PostgreSQL จำกัด identifier ที่ 63 ตัวอักษร เผื่อไว้


def _sanitize_ident(name: str) -> str:
    """
    แปลงชื่อไฟล์/คอลัมน์เป็นชื่อ identifier ที่ปลอดภัยสำหรับ SQL

    ภาษาไทยใช้เป็นชื่อคอลัมน์ได้ถ้า quote ด้วย "..." แต่จะทำให้ LLM
    เขียน SQL ผิดง่าย (ลืม quote) จึงแปลงเป็น ascii + hash กันชนกัน
    """
    ascii_part = re.sub(r"[^a-zA-Z0-9]+", "_", name).strip("_").lower()

    if not ascii_part or ascii_part.isdigit():
        # ชื่อเป็นภาษาไทยล้วน -> ใช้ hash สั้น ๆ แทน
        ascii_part = "t" + hashlib.md5(name.encode()).hexdigest()[:8]
    elif len(ascii_part) < len(re.sub(r"[^\w]", "", name)) * 0.4:
        # มี ascii น้อยเกินไป (ส่วนใหญ่เป็นไทย) -> เติม hash กันชน
        ascii_part += "_" + hashlib.md5(name.encode()).hexdigest()[:6]

    return ascii_part[:MAX_IDENT]


def _infer_type(values: list[str]) -> str:
    """
    เดาชนิดข้อมูลของคอลัมน์จากค่าที่มีจริง

    เดาแค่ 3 แบบ: BIGINT / DOUBLE PRECISION / TEXT
    ถ้าเดาผิดจะ query ไม่ได้ จึงเข้มไว้ก่อน — ต้องแปลงได้ทุกค่าถึงจะถือว่าเป็นตัวเลข
    """
    non_empty = [v.strip() for v in values if v and v.strip()]
    if not non_empty:
        return "TEXT"

    def is_int(v):
        return re.fullmatch(r"-?\d{1,18}", v.replace(",", "")) is not None

    def is_float(v):
        try:
            float(v.replace(",", ""))
            return True
        except ValueError:
            return False

    if all(is_int(v) for v in non_empty):
        return "BIGINT"
    if all(is_float(v) for v in non_empty):
        return "DOUBLE PRECISION"
    return "TEXT"


def _convert(value: str, pg_type: str):
    """แปลงค่าข้อความเป็นชนิดที่ตรงกับคอลัมน์ ค่าว่างเป็น NULL"""
    v = (value or "").strip()
    if not v:
        return None
    try:
        if pg_type == "BIGINT":
            return int(v.replace(",", ""))
        if pg_type == "DOUBLE PRECISION":
            return float(v.replace(",", ""))
    except ValueError:
        return None
    return v


def ensure_catalog(conn):
    """สร้างตารางทะเบียนที่เก็บว่าตารางไหนมาจากไฟล์ไหน มีคอลัมน์อะไร"""
    with conn.cursor() as cur:
        cur.execute("""
            CREATE TABLE IF NOT EXISTS table_catalog (
                table_name   TEXT PRIMARY KEY,
                source_file  TEXT NOT NULL,
                display_name TEXT NOT NULL,
                row_count    INTEGER NOT NULL DEFAULT 0,
                columns_json JSONB NOT NULL,
                created_at   TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )
        """)
    conn.commit()


def load_table(conn, source_file: str, table_spec: dict) -> str | None:
    """
    สร้างตารางใน PostgreSQL แล้วใส่ข้อมูลลงไป
    คืนชื่อตารางที่สร้าง หรือ None ถ้าข้ามเพราะข้อมูลไม่เหมาะ
    """
    import json

    header = table_spec["header"]
    rows = table_spec["rows"]

    if not header or not rows:
        return None

    # ชื่อตาราง: ผสมชื่อไฟล์กับชื่อชีท เพื่อไม่ให้ชนกันข้ามไฟล์
    # CSV ใช้ชื่อไฟล์เป็นชื่อ sheet ด้วย จึงต้องกันไม่ให้ได้ชื่อซ้ำคำ
    # อย่าง "data_tiny_tiny" ซึ่งทำให้ LLM เขียน SQL ผิดบ่อย (มันเดาว่า "data_tiny")
    stem = Path(source_file).stem
    sheet = table_spec["name"]
    base = stem if _sanitize_ident(sheet) == _sanitize_ident(stem) else f"{stem}_{sheet}"
    table_name = TABLE_PREFIX + _sanitize_ident(base)

    # ชื่อคอลัมน์ต้องไม่ซ้ำกันในตารางเดียว
    col_names, seen = [], {}
    for i, h in enumerate(header):
        c = _sanitize_ident(h) or f"col_{i + 1}"
        if c in seen:
            seen[c] += 1
            c = f"{c}_{seen[c]}"
        else:
            seen[c] = 0
        col_names.append(c)

    # เดาชนิดข้อมูลจากค่าจริงทั้งคอลัมน์
    col_types = []
    for i in range(len(col_names)):
        values = [str(r[i]) if i < len(r) and r[i] is not None else "" for r in rows]
        col_types.append(_infer_type(values))

    cols_ddl = ", ".join(f'"{n}" {t}' for n, t in zip(col_names, col_types, strict=False))

    with conn.cursor() as cur:
        # ลบตารางเดิมก่อน เพื่อให้ข้อมูลตรงกับไฟล์ปัจจุบันเสมอ
        cur.execute(f'DROP TABLE IF EXISTS "{table_name}"')
        cur.execute(f'CREATE TABLE "{table_name}" ({cols_ddl})')

        placeholders = ", ".join(["%s"] * len(col_names))
        insert_sql = f'INSERT INTO "{table_name}" VALUES ({placeholders})'

        batch = []
        for r in rows:
            values = [
                _convert(str(r[i]) if i < len(r) and r[i] is not None else "", col_types[i])
                for i in range(len(col_names))
            ]
            batch.append(values)

        cur.executemany(insert_sql, batch)

        # บันทึกทะเบียน พร้อมค่าตัวอย่างของคอลัมน์ข้อความ
        # (สำคัญมาก: ถ้า LLM ไม่รู้ว่ามีค่าอะไรบ้าง จะเขียน WHERE ที่ไม่ match อะไรเลย)
        columns_meta = []
        for i, (n, t) in enumerate(zip(col_names, col_types, strict=False)):
            meta = {"name": n, "type": t, "original": header[i]}
            if t == "TEXT":
                cur.execute(f'SELECT DISTINCT "{n}" FROM "{table_name}" WHERE "{n}" IS NOT NULL LIMIT 12')
                vals = [row[0] for row in cur.fetchall()]
                # เก็บเฉพาะกรณีที่ค่าซ้ำ ๆ กันไม่กี่แบบ (เช่น status, environment)
                if len(vals) <= 10:
                    meta["values"] = vals
            columns_meta.append(meta)

        cur.execute(
            """
            INSERT INTO table_catalog (table_name, source_file, display_name, row_count, columns_json)
            VALUES (%s, %s, %s, %s, %s)
            ON CONFLICT (table_name) DO UPDATE
              SET source_file = EXCLUDED.source_file,
                  display_name = EXCLUDED.display_name,
                  row_count = EXCLUDED.row_count,
                  columns_json = EXCLUDED.columns_json
            """,
            (table_name, source_file, table_spec["name"], len(rows), json.dumps(columns_meta)),
        )

    conn.commit()
    return table_name


def drop_tables_for_file(conn, source_file: str):
    """ลบตารางทั้งหมดที่มาจากไฟล์นี้ (ใช้ตอนไฟล์ถูกลบหรือแก้ไข)"""
    with conn.cursor() as cur:
        cur.execute("SELECT table_name FROM table_catalog WHERE source_file = %s", (source_file,))
        names = [r[0] for r in cur.fetchall()]
        for n in names:
            cur.execute(f'DROP TABLE IF EXISTS "{n}"')
        cur.execute("DELETE FROM table_catalog WHERE source_file = %s", (source_file,))
    conn.commit()
    return len(names)


def get_schema_description(conn) -> str:
    """
    สร้างคำอธิบาย schema ทั้งหมดเป็นข้อความ สำหรับใส่ใน prompt ให้ LLM เขียน SQL

    ต้องบอกค่าที่เป็นไปได้ของคอลัมน์ข้อความด้วย ไม่งั้น LLM จะเดาผิด
    เช่นเขียน WHERE environment = 'prod' ทั้งที่ค่าจริงคือ 'production'
    """
    import json

    with conn.cursor() as cur:
        cur.execute(
            "SELECT table_name, display_name, source_file, row_count, columns_json "
            "FROM table_catalog ORDER BY table_name"
        )
        rows = cur.fetchall()

    if not rows:
        return ""

    parts = []
    for table_name, display, source, count, cols in rows:
        cols = cols if isinstance(cols, list) else json.loads(cols)
        parts.append(f'ตาราง "{table_name}" — จาก {source} ({display}), {count} แถว')
        for c in cols:
            line = f'  "{c["name"]}" {c["type"]}'
            if c.get("original") and c["original"] != c["name"]:
                line += f"  (เดิม: {c['original']})"
            if c.get("values"):
                vals = ", ".join(f"'{v}'" for v in c["values"])
                line += f"  ค่าที่มี: {vals}"
            parts.append(line)
        parts.append("")

    return "\n".join(parts)


def list_tables(conn) -> list[dict]:
    """รายชื่อตารางทั้งหมดพร้อมข้อมูลย่อ ใช้แสดงใน API"""
    with conn.cursor() as cur:
        cur.execute(
            "SELECT table_name, source_file, display_name, row_count FROM table_catalog ORDER BY table_name"
        )
        return [{"table": r[0], "source": r[1], "sheet": r[2], "rows": r[3]} for r in cur.fetchall()]

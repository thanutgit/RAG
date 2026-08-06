"""
services/query_service.py
Retrieval & Chat Pipeline พร้อมการแยกเส้นทางระหว่าง vector search กับ SQL

คำถามสองประเภทต้องใช้คนละวิธี:
  - "INC-001 แก้ยังไง"          -> vector search (หาเนื้อหาที่เกี่ยวข้อง)
  - "server ใน production มีกี่เครื่อง" -> SQL (ต้องนับจากข้อมูลครบทุกแถว)

vector search ดึงมาแค่ไม่กี่ chunk จึงนับของไม่ได้ ทดสอบจริงพบว่าตอบ 23 จาก 76
"""

import re
import time

import requests

from services import postgres_service, qdrant_service, sql_service, tabular_service
from services.ollama_service import ask_llm, ask_raw, get_embedding

SQL_ANSWER_PROMPT = """ผู้ใช้ถามคำถามเกี่ยวกับข้อมูลตาราง ระบบได้รันคำสั่ง SQL
บนข้อมูลจริงทั้งหมดแล้ว และนี่คือผลลัพธ์

คำถาม: {question}

คำสั่งที่รัน:
{sql}

ผลลัพธ์:
{result}

เรียบเรียงคำตอบเป็นภาษาไทย สั้น ๆ ไม่เกิน 3 ประโยค

กติกาสำคัญ:
- ตัวเลขในผลลัพธ์คำนวณจากข้อมูลครบทุกแถวแล้ว ให้ใช้ตรง ๆ ห้ามแก้ไข
- ห้ามนับจำนวนเองจากรายการที่เห็น ให้ใช้เลขที่ระบุว่า "จำนวนแถวทั้งหมด" เท่านั้น
- ถ้าผลลัพธ์เป็นรายการยาว ห้ามไล่รายชื่อในคำตอบ เพราะตารางเต็มแสดงอยู่ใต้คำตอบอยู่แล้ว
  ให้บอกแค่จำนวนและภาพรวม
- ไม่ต้องอธิบายคำสั่ง SQL"""


REWRITE_SYSTEM = """คุณมีหน้าที่เดียวคือเขียนคำถามใหม่ให้สมบูรณ์
ห้ามตอบคำถาม ห้ามให้ข้อมูล ห้ามเดาคำตอบ ผลลัพธ์ต้องเป็นประโยคคำถามเสมอ"""

REWRITE_PROMPT = """เติมบริบทที่ขาดหายให้คำถามล่าสุด โดยดูจากบทสนทนาก่อนหน้า

ตัวอย่าง:
บทสนทนา: ผู้ใช้ถาม "server ใน production มีกี่เครื่อง" ผู้ช่วยตอบ "76 เครื่อง"
คำถามล่าสุด: แล้วใน staging ล่ะ
ผลลัพธ์: server ใน staging มีกี่เครื่อง

ตัวอย่าง:
บทสนทนา: ผู้ใช้ถาม "รายจ่ายเดือนมกราคมเท่าไหร่" ผู้ช่วยตอบ "17400 บาท"
คำถามล่าสุด: เดือนกุมภาพันธ์
ผลลัพธ์: รายจ่ายเดือนกุมภาพันธ์เท่าไหร่

กติกา:
- เติมเฉพาะส่วนที่ขาด ห้ามเปลี่ยนคำที่ผู้ใช้พิมพ์มาแล้ว
- ห้ามใส่เงื่อนไขจากบทสนทนาเก่าที่ผู้ใช้ไม่ได้ถามถึงในคำถามล่าสุด
- ผลลัพธ์ต้องเป็นคำถาม ห้ามมีคำตอบหรือตัวเลขที่ไม่ได้อยู่ในคำถามเดิม
- ตอบเฉพาะคำถามที่เขียนใหม่ ไม่ต้องมีคำนำหน้า

บทสนทนาก่อนหน้า:
{history}

คำถามล่าสุด: {question}"""

# คำที่บ่งบอกว่าคำถามอ้างถึงสิ่งที่พูดไปก่อนหน้า อ่านเดี่ยว ๆ ไม่รู้เรื่อง
_NEEDS_CONTEXT = re.compile(
    r"(แล้ว|ล่ะ|ละ|อันนั้น|อันนี้|ตัวนั้น|เมื่อกี้|ข้างบน|ก่อนหน้า|"
    r"ดังกล่าว|นั้นล่ะ|เหมือนกัน|ด้วย$|อีก$)",
)


def _rewrite_question(question: str, history: list[dict]) -> str:
    """
    เขียนคำถามต่อเนื่องให้สมบูรณ์ก่อนนำไปค้นหา

    จำเป็นเพราะ embedding ทำงานกับคำถามเดี่ยว ๆ ไม่รู้จักบริบท
    "แล้วใน staging ล่ะ" จะ embed เป็นเวกเตอร์ที่ไม่ตรงกับอะไรเลย

    ออกแบบให้อนุรักษ์นิยม: เขียนใหม่เฉพาะเมื่อจำเป็นจริง และตรวจผลลัพธ์เข้ม
    เพราะการเขียนใหม่ผิดอันตรายกว่าไม่เขียนใหม่ — เจอจริงตอนที่ระบบเปลี่ยน
    "production" เป็น "staging" ตามบทสนทนาเก่า ทำให้ได้คำตอบผิดทั้งหมด
    โดยผู้ใช้ไม่รู้ตัว
    """
    if not history:
        return question

    q = question.strip()

    # คำถามยาวมักสมบูรณ์ในตัวเองอยู่แล้ว
    if len(q) > 45:
        return question

    # ไม่มีคำที่บ่งบอกการอ้างถึงบริบท -> ไม่ต้องเขียนใหม่
    if not _NEEDS_CONTEXT.search(q):
        return question

    convo = "\n".join(
        f"{'ผู้ใช้' if m['role'] == 'user' else 'ผู้ช่วย'}: {m['content'][:200]}" for m in history[-4:]
    )

    try:
        rewritten = (
            ask_raw(
                REWRITE_PROMPT.format(history=convo, question=q),
                system=REWRITE_SYSTEM,
                num_predict=100,
            )
            .strip()
            .strip('"')
            .strip()
        )
    except requests.exceptions.RequestException:
        return question

    rewritten = re.sub(r"^(ผลลัพธ์|เขียนใหม่|คำถามใหม่)\s*[:：]\s*", "", rewritten)
    rewritten = rewritten.split("\n")[0].strip()

    if not _is_safe_rewrite(q, rewritten):
        return question

    return rewritten


def _is_safe_rewrite(original: str, rewritten: str) -> bool:
    """
    ตรวจว่าคำถามที่เขียนใหม่ยังตรงกับเจตนาเดิมหรือไม่

    กันกรณีที่ LLM ดึงเงื่อนไขจากบทสนทนาเก่ามาปน หรือแต่งคำตอบขึ้นมาแทนคำถาม
    ถ้าไม่ผ่านข้อไหน ให้ใช้คำถามเดิม — เสียโอกาสตอบคำถามต่อเนื่องได้บ้าง
    ดีกว่าตอบผิดโดยผู้ใช้ไม่รู้ตัว
    """
    if not rewritten or len(rewritten) > 160:
        return False

    # ผลลัพธ์หน้าตาเหมือนคำตอบ ไม่ใช่คำถาม
    if "**" in rewritten or rewritten.count(",") >= 3:
        return False

    # มีตัวเลขที่ไม่ได้อยู่ในคำถามเดิม -> น่าจะแต่งคำตอบมา
    if set(re.findall(r"\d+", rewritten)) - set(re.findall(r"\d+", original)):
        return False

    # คำสำคัญในคำถามเดิมต้องยังอยู่ครบ ห้ามถูกแทนที่ด้วยคำจากบทสนทนาเก่า
    # (เจอจริง: "production" ถูกเปลี่ยนเป็น "staging")
    orig_terms = set(re.findall(r"[A-Za-z][A-Za-z0-9_-]{2,}", original.lower()))
    new_terms = set(re.findall(r"[A-Za-z][A-Za-z0-9_-]{2,}", rewritten.lower()))
    if orig_terms - new_terms:
        return False

    return True


def build_prompt(question: str, hits) -> str:
    """เอา chunk ที่ retrieve มาได้ ประกอบเป็น context ใส่ใน prompt"""
    context_parts = []
    for i, hit in enumerate(hits, start=1):
        source = hit.payload.get("file_path", "unknown")
        heading = hit.payload.get("heading", "")
        label = f"{source} · {heading}" if heading else source
        text = hit.payload.get("text", "")
        context_parts.append(f"[แหล่งที่มา {i}: {label}]\n{text}")

    context = "\n\n---\n\n".join(context_parts)
    return f"""บริบท:
{context}

คำถาม: {question}

คำตอบ:"""


def _has_tables() -> bool:
    """เช็คว่ามีข้อมูลตารางในระบบหรือยัง"""
    try:
        conn = postgres_service.get_connection()
        try:
            return bool(tabular_service.list_tables(conn))
        finally:
            conn.close()
    except Exception:
        return False


def _run_vector_query(question, search_question, top_k, score_threshold, start, history) -> dict:
    """เส้นทางเดิม: embed คำถาม -> ค้นหา chunk -> ให้ LLM ตอบจาก context"""
    client = qdrant_service.get_client()
    query_vector = get_embedding(search_question)
    hits = qdrant_service.search(client, query_vector, top_k=top_k, score_threshold=score_threshold)

    if not hits:
        return {
            "answer": "ไม่พบข้อมูลที่เกี่ยวข้องพอในโน้ต (หรือยังไม่ได้ ingest ข้อมูลเข้าระบบ)",
            "sources": [],
            "mode": "search",
            "latency_ms": int((time.time() - start) * 1000),
        }

    answer = ask_llm(build_prompt(question, hits), history=history)

    sources = [
        {
            "file_path": h.payload.get("file_path"),
            "chunk_index": h.payload.get("chunk_index"),
            "heading": h.payload.get("heading", ""),
            "score": round(h.score, 4),
            "text_preview": h.payload.get("text", "")[:150],
        }
        for h in hits
    ]

    return {
        "answer": answer,
        "sources": sources,
        "mode": "search",
        "rewritten_question": search_question if search_question != question else None,
        "latency_ms": int((time.time() - start) * 1000),
    }


def _load_history(session_id: str | None) -> list[dict]:
    """ดึงบทสนทนาก่อนหน้าของ session นี้"""
    if not session_id:
        return []
    try:
        conn = postgres_service.get_connection()
        try:
            return postgres_service.load_recent_messages(conn, session_id, limit=6)
        finally:
            conn.close()
    except Exception:
        return []


def run_query(
    question: str,
    top_k: int = None,
    score_threshold: float = None,
    session_id: str = None,
) -> dict:
    """
    รัน pipeline เต็ม โดยเลือกเส้นทางตามประเภทคำถาม
    คืน dict: answer, sources, mode, sql/table (ถ้ามี), latency_ms
    """
    start = time.time()

    history = _load_history(session_id)
    # คำถามที่ใช้ค้นหาต้องสมบูรณ์ในตัวเอง ส่วนคำถามเดิมใช้ตอนให้ LLM ตอบ
    search_question = _rewrite_question(question, history)

    # คำถามประเภทนับ/รวมยอด -> ใช้ SQL เพราะต้องเห็นข้อมูลครบ
    if sql_service.needs_sql(search_question, _has_tables()):
        try:
            r = sql_service.run_sql_query(search_question)
            # ไม่ส่ง history ตรงนี้ เพราะผลลัพธ์ SQL มีข้อมูลครบแล้ว
            # การใส่บทสนทนาเก่าทำให้ LLM เอาเงื่อนไขเดิมมาปนในคำตอบ
            # เจอจริง: ตอบว่า "ทีม channel ดูแล 41 ตัวอยู่ในสถานะ running"
            # ทั้งที่คำถามใหม่ไม่ได้ถามถึง status เลย
            answer = ask_llm(
                SQL_ANSWER_PROMPT.format(question=question, sql=r["sql"], result=r["result_text"])
            )
            return {
                "answer": answer,
                "sources": [],
                "mode": "sql",
                "sql": r["sql"],
                # ส่งตารางเต็มให้หน้าเว็บแสดงเอง ไม่ผ่าน LLM
                "table": {
                    "columns": r["columns"],
                    "rows": r["rows"],
                    "total_rows": r["total_rows"],
                    "truncated": r["truncated"],
                },
                "rewritten_question": search_question if search_question != question else None,
                "latency_ms": int((time.time() - start) * 1000),
            }
        except sql_service.SQLError as e:
            # เขียน SQL ไม่ได้ -> ถอยไปใช้ vector search แทน ดีกว่าไม่ตอบเลย
            print(f"   ℹ️  SQL ใช้ไม่ได้ ({e}) — เปลี่ยนไปใช้ vector search")
        except Exception as e:
            print(f"   ⚠️  SQL ล้มเหลว ({e}) — เปลี่ยนไปใช้ vector search")

    return _run_vector_query(question, search_question, top_k, score_threshold, start, history)

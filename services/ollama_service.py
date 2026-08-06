"""
services/ollama_service.py
คุยกับ Ollama ทั้งฝั่ง embedding และฝั่ง LLM chat
"""

import requests

from services import config
from utils.text_normalize import normalize_text

SYSTEM_PROMPT = """คุณเป็นผู้ช่วยตอบคำถามจากโน้ตส่วนตัวของผู้ใช้เท่านั้น

กติกาเนื้อหา:
1. ตอบโดยอ้างอิงจาก "บริบท" ที่ให้มาด้านล่างเท่านั้น ห้ามใช้ความรู้ภายนอก
2. ถ้าบริบทไม่มีข้อมูลที่เกี่ยวข้องพอจะตอบคำถามได้ ให้บอกตรง ๆ ว่า "ไม่พบข้อมูลที่เกี่ยวข้องในโน้ต" ห้ามเดาคำตอบ
3. ตอบเป็นภาษาไทย ตรงประเด็น ไม่ต้องเกริ่นนำหรือสรุปซ้ำท้ายคำตอบ

กติกาการจัดรูปแบบ (ตอบเป็น Markdown):
4. รักษาโครงสร้างเดิมของเนื้อหาในบริบทไว้ ถ้าต้นฉบับเป็นขั้นตอนหรือรายการ ให้ตอบเป็นขั้นตอนหรือรายการเหมือนกัน อย่ายุบรวมเป็นย่อหน้าเดียว
5. ขั้นตอนที่มีลำดับก่อนหลัง ใช้เลข 1. 2. 3. / รายการที่ไม่มีลำดับ ใช้ -
6. เน้นคำสำคัญด้วย **ตัวหนา** เท่าที่จำเป็น
7. ถ้าคำตอบมีหลายหัวข้อ ใช้ ## คั่นหัวข้อ"""


def get_embedding(text: str) -> list[float]:
    """
    แปลงข้อความเป็นเวกเตอร์ผ่านโมเดล embedding (เช่น bge-m3)

    normalize ก่อนเสมอ เพื่อให้ข้อความที่หน้าตาเหมือนกันแต่ต่าง Unicode
    (เช่น "แ" กับ "เเ" ในภาษาไทย) ได้เวกเตอร์เดียวกัน
    ใส่ไว้ตรงนี้จุดเดียวเพราะทั้ง ingest และ query ผ่านฟังก์ชันนี้ทั้งคู่
    """
    resp = requests.post(
        f"{config.OLLAMA_BASE_URL}/api/embeddings",
        json={"model": config.OLLAMA_EMBED_MODEL, "prompt": normalize_text(text)},
        timeout=60,
    )
    resp.raise_for_status()
    return resp.json()["embedding"]


def ask_llm(user_prompt: str, history: list[dict] | None = None) -> str:
    """
    ส่ง prompt ให้ LLM ตอบ โดยมี system prompt คุมพฤติกรรม

    หมายเหตุเรื่อง think=False:
    โมเดลตระกูล Qwen3 เปิด reasoning mode เป็นค่าเริ่มต้น คือจะสร้าง token
    "คิดในใจ" จำนวนมากก่อนตอบจริง ซึ่งกินเวลามหาศาลใน use case แบบ RAG
    ที่คำตอบควรมาจาก context ที่ให้ไปตรง ๆ อยู่แล้ว ไม่ต้องใช้การให้เหตุผลซับซ้อน
    การส่ง think=False ลด latency ได้มากโดยแทบไม่กระทบคุณภาพคำตอบใน use case นี้
    """
    messages = [{"role": "system", "content": SYSTEM_PROMPT}]
    if history:
        # ใส่บทสนทนาก่อนหน้า เพื่อให้ตอบคำถามต่อเนื่องได้
        # เช่น "แล้วใน staging ล่ะ" ที่ไม่มีความหมายถ้าอ่านเดี่ยว ๆ
        messages.extend(history)
    messages.append({"role": "user", "content": user_prompt})

    payload = {
        "model": config.OLLAMA_LLM_MODEL,
        "messages": messages,
        "stream": False,
        "think": False,
        "options": {
            # เพดานความยาวคำตอบ
            # ภาษาไทยกิน token มากกว่าอังกฤษราว 2-3 เท่า (tokenizer ตัดคำไทยได้ไม่ดีนัก)
            # ค่าต่ำเกินไปจะทำให้คำตอบขาดกลางประโยคโดยไม่มี error แจ้งเตือน
            # 2048 พอสำหรับคำตอบแบบมีหัวข้อและรายการหลายข้อ
            "num_predict": 2048,
        },
    }

    resp = requests.post(
        f"{config.OLLAMA_BASE_URL}/api/chat",
        json=payload,
        timeout=120,
    )

    # Ollama บางเวอร์ชันยังไม่รองรับ parameter "think" -> ลองใหม่โดยตัดออก
    if resp.status_code == 400:
        payload.pop("think", None)
        resp = requests.post(
            f"{config.OLLAMA_BASE_URL}/api/chat",
            json=payload,
            timeout=120,
        )

    resp.raise_for_status()
    data = resp.json()

    answer = data["message"]["content"]

    # Ollama บอกเหตุผลที่หยุดสร้างข้อความมาใน done_reason
    # "length" = ชนเพดาน num_predict -> คำตอบถูกตัดกลางคัน ไม่ใช่จบเองตามธรรมชาติ
    # ต้องแจ้งให้รู้ ไม่งั้นผู้ใช้จะเข้าใจว่าคำตอบที่ขาดไปคือคำตอบทั้งหมด
    if data.get("done_reason") == "length":
        answer += "\n\n---\n*(คำตอบถูกตัดเพราะยาวเกินเพดานที่ตั้งไว้ — ลองถามให้เจาะจงขึ้น)*"

    return answer


def ask_raw(prompt: str, system: str = None, num_predict: int = 200) -> str:
    """
    เรียก LLM สำหรับงานภายในระบบ เช่น เขียนคำถามใหม่ จัดประเภทคำถาม

    ต่างจาก ask_llm() ตรงที่ไม่ใส่ SYSTEM_PROMPT ของ RAG
    เพราะ prompt นั้นสั่งให้ "ตอบคำถามจากโน้ต" ซึ่งทำให้โมเดลพยายามตอบคำถาม
    แทนที่จะทำงานที่สั่ง — เจอจริงตอนทำ query rewriting: แทนที่จะเขียนคำถามใหม่
    มันแต่งคำตอบปลอมขึ้นมาแล้วส่งคำตอบนั้นไปค้นหาแทน
    """
    messages = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})

    resp = requests.post(
        f"{config.OLLAMA_BASE_URL}/api/chat",
        json={
            "model": config.OLLAMA_LLM_MODEL,
            "messages": messages,
            "stream": False,
            "think": False,
            "options": {"num_predict": num_predict, "temperature": 0},
        },
        timeout=120,
    )
    resp.raise_for_status()
    return resp.json()["message"]["content"].strip()

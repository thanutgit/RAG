"""
utils/text_normalize.py
ทำข้อความให้เป็นรูปแบบมาตรฐานก่อนส่งไป embed

ปัญหาที่แก้: ภาษาไทยมีหลายวิธีพิมพ์ที่ให้ผลหน้าตาเหมือนกันบนจอ
แต่เป็นคนละ Unicode codepoint ทำให้ embedding model มองเป็นคนละคำ

ตัวอย่างที่เจอจริงในโปรเจกต์นี้:
  "พะแนง"  ใช้ แ (U+0E41)              -> retrieval score 0.6714 ตอบถูก
  "พะเเนง" ใช้ เ+เ (U+0E40 U+0E40)     -> retrieval score 0.4694 ตอบผิด
ทั้งสองแบบ render ออกมาเหมือนกันทุกประการ ผู้ใช้ไม่มีทางรู้ว่าพิมพ์ต่างกัน
"""

import re
import unicodedata

# คู่ที่ต้องแทนที่: (รูปแบบที่พิมพ์ผิด, รูปแบบมาตรฐาน)
THAI_REPLACEMENTS = [
    ("\u0e40\u0e40", "\u0e41"),  # เ + เ  ->  แ
    ("\u0e4d\u0e32", "\u0e33"),  # นิคหิต + า  ->  ำ
    ("\u0e24\u0e32", "\u0e24\u0e45"),  # ฤ + า  ->  ฤๅ
    ("\u0e26\u0e32", "\u0e26\u0e45"),  # ฦ + า  ->  ฦๅ
]


def normalize_text(text: str) -> str:
    """
    ทำความสะอาดข้อความก่อน embed
    1. Unicode NFC — รวมตัวอักษรที่แยกส่วนกันให้เป็นรูปแบบเดียว
    2. แก้รูปแบบการพิมพ์ภาษาไทยที่ให้ผลเหมือนกันแต่ต่าง codepoint
    3. ยุบช่องว่างซ้ำและตัดหัวท้าย
    """
    if not text:
        return text

    # NFC จัดการ combining character ทั่วไป แต่แก้ เ+เ -> แ ไม่ได้
    # เพราะสองแบบนี้ไม่ถือว่า canonically equivalent ในมาตรฐาน Unicode
    text = unicodedata.normalize("NFC", text)

    for wrong, correct in THAI_REPLACEMENTS:
        text = text.replace(wrong, correct)

    # ยุบ whitespace ซ้ำ (เว้นบรรทัดใหม่ไว้ เพราะ Markdown ใช้สื่อโครงสร้าง)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)

    return text.strip()


if __name__ == "__main__":
    # ทดสอบว่าสองแบบที่หน้าตาเหมือนกัน ถูกทำให้เป็นข้อความเดียวกันจริง
    typed_wrong = "พะเเนงทำยังไง"  # เ + เ
    typed_right = "พะแนงทำยังไง"  # แ

    print(f"พิมพ์แบบผิด : {typed_wrong!r}")
    print(f"พิมพ์แบบถูก : {typed_right!r}")
    print(f"เหมือนกันก่อน normalize : {typed_wrong == typed_right}")

    a, b = normalize_text(typed_wrong), normalize_text(typed_right)
    print(f"เหมือนกันหลัง normalize : {a == b}")

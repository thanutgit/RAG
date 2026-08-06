"""
tests/test_normalize.py
ทดสอบ Unicode normalization

บั๊กจริง: "พะแนง" กับ "พะเเนง" render เหมือนกันเป๊ะบนจอ แต่เป็นคนละ codepoint
  แ  = U+0E41 (อักขระเดียว)
  เเ = U+0E40 + U+0E40 (เ สองตัว)
embedding มองเป็นคนละคำ -> retrieval score ต่างกัน 0.67 vs 0.45
ผู้ใช้ไม่มีทางรู้ว่าพิมพ์ต่างกัน
"""

import pytest

from utils.text_normalize import normalize_text


class TestThaiVariants:
    def test_เ_สองตัว_เท่ากับ_แ(self):
        assert normalize_text("พะเเนงทำยังไง") == normalize_text("พะแนงทำยังไง")

    def test_ผลลัพธ์ใช้รูปแบบมาตรฐาน(self):
        out = normalize_text("พะเเนง")
        assert "\u0e41" in out, "ต้องแปลงเป็น แ (U+0E41)"
        assert "\u0e40\u0e40" not in out, "ต้องไม่เหลือ เ สองตัวติดกัน"

    @pytest.mark.parametrize(
        "wrong,correct",
        [
            ("\u0e40\u0e40", "\u0e41"),  # เ+เ -> แ
            ("\u0e4d\u0e32", "\u0e33"),  # นิคหิต+า -> ำ
        ],
    )
    def test_คู่ที่ต้องแปลง(self, wrong, correct):
        assert normalize_text(f"ทดสอบ{wrong}ทดสอบ") == normalize_text(f"ทดสอบ{correct}ทดสอบ")


class TestPreservation:
    """normalize ต้องไม่ทำลายข้อความปกติ"""

    @pytest.mark.parametrize(
        "text",
        [
            "ข้อความภาษาไทยปกติที่ถูกต้องอยู่แล้ว",
            "Normal English text stays the same.",
            "ผสม Thai และ English 123 ตัวเลข",
            "เมื่อ เธอ เดิน",  # เ เดี่ยว ๆ ที่ถูกต้อง ห้ามแตะ
        ],
    )
    def test_ไม่เปลี่ยนข้อความที่ถูกต้อง(self, text):
        assert normalize_text(text) == text.strip()

    def test_ยุบช่องว่างซ้ำ(self):
        assert normalize_text("คำ    ที่    ห่าง") == "คำ ที่ ห่าง"

    def test_เก็บบรรทัดใหม่ไว้(self):
        """Markdown ใช้บรรทัดใหม่สื่อโครงสร้าง ห้ามยุบทิ้ง"""
        out = normalize_text("บรรทัดหนึ่ง\n\nบรรทัดสอง")
        assert "\n\n" in out

    def test_ยุบบรรทัดว่างที่เกินสองบรรทัด(self):
        assert normalize_text("ก\n\n\n\n\nข") == "ก\n\nข"


class TestEdgeCases:
    @pytest.mark.parametrize("text", ["", None])
    def test_ค่าว่างไม่พัง(self, text):
        assert normalize_text(text) == text

    def test_ตัดช่องว่างหัวท้าย(self):
        assert normalize_text("  ข้อความ  ") == "ข้อความ"

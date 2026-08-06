"""
tests/test_chunking.py
ทดสอบการหั่นเอกสารเป็น chunk

จุดนี้เคยพังหนัก: character-based chunking ตัดกลางคำภาษาไทย
ทำให้ context ที่ส่งให้ LLM ขาด แล้วคำตอบขาดกลางประโยคตาม
ใช้เวลาดีบั๊กนาน เพราะอาการปรากฏที่ปลายทาง (คำตอบ) ไม่ใช่ต้นทาง (chunking)
"""

import pytest

from utils.chunking import Chunk, chunk_text

SAMPLE = """# สรุปการลงทุน

## กองทุนดัชนี

กองทุนที่ลงทุนตามดัชนีอ้างอิง เช่น SET50 หรือ S&P 500

## การกระจายความเสี่ยง

อย่าถือสินทรัพย์เดียวหรืออุตสาหกรรมเดียวมากเกินไป

## เงินสำรองฉุกเฉิน

ควรมีเงินสดพอใช้จ่าย 3-6 เดือน
"""


class TestStructureAware:
    """หั่นตามหัวข้อ Markdown ไม่ใช่ตามจำนวนตัวอักษร"""

    def test_แยกตามหัวข้อ(self):
        chunks = chunk_text(SAMPLE)
        assert len(chunks) == 3, "ควรได้ 3 chunk ตามจำนวนหัวข้อย่อย"

    def test_ไม่ตัดกลางคำ(self):
        """
        บั๊กจริง: chunk จบที่ 'อย่าถือสินทรัพย์เดียวหรืออุ' (ตัดกลาง 'อุตสาหกรรม')
        เพราะนับครบ 800 ตัวอักษรพอดี ภาษาไทยไม่มีช่องว่างจึงตัดตรงไหนก็ได้
        """
        chunks = chunk_text(SAMPLE)
        full = " ".join(c.text for c in chunks)
        assert "อุตสาหกรรม" in full
        assert "อุตสาหกรรม" not in [c.text[-10:] for c in chunks], "คำต้องไม่ถูกตัดท้าย chunk"

    def test_แนบ_heading_path(self):
        """
        heading ที่แนบไว้ช่วยให้ embedding รู้ว่าข้อความอยู่ใต้หัวข้อไหน
        เนื้อหาบางท่อนอ่านเดี่ยว ๆ ไม่รู้ว่าพูดถึงอะไร
        """
        chunks = chunk_text(SAMPLE)
        risk = next(c for c in chunks if "สินทรัพย์เดียว" in c.text)
        assert "การกระจายความเสี่ยง" in risk.heading
        assert "สรุปการลงทุน" in risk.heading, "ควรมี heading ระดับบนด้วย"
        assert risk.heading in risk.text, "heading ต้องอยู่ในเนื้อ chunk เพื่อให้ embed เห็น"

    def test_เนื้อหาใต้หัวข้ออยู่ครบใน_chunk_เดียว(self):
        chunks = chunk_text(SAMPLE)
        risk = next(c for c in chunks if "สินทรัพย์เดียว" in c.text)
        assert "มากเกินไป" in risk.text, "เนื้อหาต้องไม่ถูกแยกไปอีก chunk"


class TestFallback:
    """section ที่ยาวเกินต้องถูกหั่นย่อย"""

    def test_หั่น_section_ที่ยาวเกิน(self):
        long_body = "\n\n".join(f"ย่อหน้าที่ {i} " + "เนื้อหาทดสอบ " * 20 for i in range(10))
        text = f"# หัวข้อ\n\n## ส่วนที่ยาว\n\n{long_body}"
        chunks = chunk_text(text, chunk_size=800, overlap=100)
        assert len(chunks) > 1, "section ยาวต้องถูกหั่นย่อย"

    def test_ทุก_chunk_ไม่เกินขนาดมากเกินไป(self):
        long_body = "ประโยคทดสอบยาว ๆ " * 300
        text = f"# หัวข้อ\n\n## ส่วนที่ยาว\n\n{long_body}"
        chunks = chunk_text(text, chunk_size=800, overlap=100)
        # เผื่อความยาว heading ที่แนบเพิ่ม
        assert all(len(c.text) <= 1000 for c in chunks)

    def test_ไม่มีหัวข้อเลยก็ยังหั่นได้(self):
        text = "ข้อความธรรมดาไม่มีหัวข้อ " * 100
        chunks = chunk_text(text, chunk_size=400, overlap=50)
        assert chunks and all(c.text.strip() for c in chunks)


class TestEdgeCases:
    @pytest.mark.parametrize("text", ["", "   ", "\n\n\n"])
    def test_ข้อความว่างคืน_list_ว่าง(self, text):
        assert chunk_text(text) == []

    def test_overlap_มากกว่า_chunk_size_ต้อง_error(self):
        """กัน infinite loop เพราะตำแหน่งจะไม่เดินหน้า"""
        with pytest.raises(ValueError):
            chunk_text("ทดสอบ", chunk_size=100, overlap=100)

    def test_chunk_index_เรียงต่อเนื่อง(self):
        chunks = chunk_text(SAMPLE)
        assert [c.chunk_index for c in chunks] == list(range(len(chunks)))

    def test_คืน_dataclass_ที่มี_field_ครบ(self):
        c = chunk_text(SAMPLE)[0]
        assert isinstance(c, Chunk)
        assert isinstance(c.text, str) and isinstance(c.chunk_index, int)
        assert isinstance(c.heading, str)

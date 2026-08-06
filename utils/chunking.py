"""
utils/chunking.py
Markdown-aware chunking พร้อม recursive fallback

ทำไมไม่ใช้ character-based ธรรมดา:
  การนับตัวอักษรแล้วตัดที่ 800 พอดี ทำให้เกิดปัญหาจริงที่เจอมาแล้ว
  1. ตัดกลางคำ — ภาษาไทยไม่มีช่องว่างระหว่างคำ จึงตัดตรงไหนก็ได้ เช่น "อุตสาหกรรม" -> "อุ"
  2. หัวข้อกับเนื้อหาถูกแยกคนละ chunk — retrieve เจอหัวข้อลอย ๆ ที่ไม่มีเนื้อหา

กลยุทธ์ที่ใช้แทน:
  1. หั่นตามหัวข้อ Markdown (#, ##, ###) — แต่ละ section คือหน่วยความหมายที่สมบูรณ์ในตัว
  2. section ที่ยาวเกิน max_chars -> หั่นย่อยตามย่อหน้า แล้วตามประโยค ตามลำดับ
  3. แนบ heading path ไว้ทุก chunk เพื่อไม่ให้เสียบริบทว่าข้อความนี้อยู่ใต้หัวข้อไหน
"""

import re
from dataclasses import dataclass, field


@dataclass
class Chunk:
    text: str
    chunk_index: int
    heading: str = ""  # heading path เช่น "สรุปการลงทุน > การกระจายความเสี่ยง"
    start_char: int = 0  # ตำแหน่งในไฟล์ต้นฉบับ ไว้ debug ย้อนกลับ


@dataclass
class _Section:
    heading_path: list[str] = field(default_factory=list)
    lines: list[str] = field(default_factory=list)
    start: int = 0

    @property
    def body(self) -> str:
        return "\n".join(self.lines).strip()

    @property
    def heading(self) -> str:
        return " > ".join(self.heading_path)


_HEADING = re.compile(r"^(#{1,6})\s+(.*)$")


def _split_sections(text: str) -> list[_Section]:
    """แยกเอกสารเป็น section ตามหัวข้อ Markdown พร้อมจำ heading path"""
    sections: list[_Section] = []
    stack: list[tuple[int, str]] = []  # (ระดับหัวข้อ, ข้อความหัวข้อ)
    current = _Section()
    pos = 0

    for line in text.split("\n"):
        m = _HEADING.match(line.strip())
        if m:
            # เจอหัวข้อใหม่ -> ปิด section เดิมก่อน
            if current.body:
                sections.append(current)

            level, title = len(m.group(1)), m.group(2).strip()
            # ตัดหัวข้อระดับลึกกว่าหรือเท่ากันออก แล้วต่อหัวข้อใหม่เข้าไป
            while stack and stack[-1][0] >= level:
                stack.pop()
            stack.append((level, title))

            current = _Section(heading_path=[t for _, t in stack], start=pos)
        else:
            current.lines.append(line)

        pos += len(line) + 1

    if current.body:
        sections.append(current)

    return sections


def _split_long(text: str, max_chars: int, overlap: int) -> list[str]:
    """
    หั่นข้อความที่ยาวเกิน max_chars แบบ recursive
    ลองตามลำดับ: ย่อหน้า -> ประโยค -> ตัวอักษร (ทางเลือกสุดท้าย)
    """
    if len(text) <= max_chars:
        return [text]

    # ระดับที่ 1: ย่อหน้า
    parts = _pack(re.split(r"\n\s*\n", text), max_chars, joiner="\n\n")
    if all(len(p) <= max_chars for p in parts):
        return parts

    # ระดับที่ 2: ประโยค (ภาษาไทยใช้ช่องว่าง/บรรทัดใหม่คั่นประโยคเป็นหลัก ไม่ใช่จุด)
    out: list[str] = []
    for p in parts:
        if len(p) <= max_chars:
            out.append(p)
            continue
        sentences = re.split(r"(?<=[.!?])\s+|\n", p)
        out.extend(_pack(sentences, max_chars, joiner=" "))

    # ระดับที่ 3: ตัดตามตัวอักษรแบบมี overlap (เฉพาะส่วนที่ยังยาวเกินจริง ๆ)
    final: list[str] = []
    for p in out:
        if len(p) <= max_chars:
            final.append(p)
            continue
        step = max_chars - overlap
        for i in range(0, len(p), step):
            piece = p[i : i + max_chars].strip()
            if piece:
                final.append(piece)

    return final


def _pack(pieces: list[str], max_chars: int, joiner: str) -> list[str]:
    """รวมชิ้นเล็ก ๆ ให้เป็นก้อนที่ใกล้ max_chars ที่สุดโดยไม่เกิน"""
    packed: list[str] = []
    buf = ""

    for piece in pieces:
        piece = piece.strip()
        if not piece:
            continue
        candidate = f"{buf}{joiner}{piece}" if buf else piece
        if len(candidate) <= max_chars:
            buf = candidate
        else:
            if buf:
                packed.append(buf)
            buf = piece

    if buf:
        packed.append(buf)
    return packed


def chunk_text(text: str, chunk_size: int = 800, overlap: int = 100) -> list[Chunk]:
    """
    หั่นเอกสาร Markdown เป็น chunk โดยรักษาโครงสร้างหัวข้อไว้

    chunk_size: ความยาวสูงสุดของเนื้อหาต่อ chunk (ไม่นับ heading ที่แนบเพิ่ม)
    overlap:    ใช้เฉพาะกรณีที่ต้อง fallback ไปตัดตามตัวอักษรจริง ๆ
    """
    text = text.strip()
    if not text:
        return []
    if overlap >= chunk_size:
        raise ValueError("overlap ต้องน้อยกว่า chunk_size")

    chunks: list[Chunk] = []
    index = 0

    for sec in _split_sections(text):
        for piece in _split_long(sec.body, chunk_size, overlap):
            piece = piece.strip()
            if not piece:
                continue

            # แนบ heading ไว้ต้น chunk เพื่อให้ retrieval รู้ว่าข้อความนี้อยู่ใต้หัวข้อไหน
            body = f"{sec.heading}\n\n{piece}" if sec.heading else piece

            chunks.append(
                Chunk(
                    text=body,
                    chunk_index=index,
                    heading=sec.heading,
                    start_char=sec.start,
                )
            )
            index += 1

    return chunks


if __name__ == "__main__":
    sample = """# สรุปการลงทุนฉบับย่อ

## กองทุนดัชนี (Index Fund)

กองทุนที่ลงทุนตามดัชนีอ้างอิง เช่น SET50 หรือ S&P 500

ข้อดีคือค่าธรรมเนียมต่ำมากเมื่อเทียบกับกองทุนที่มีการบริหารเชิงรุก

## การกระจายความเสี่ยง

อย่าถือสินทรัพย์เดียวหรืออุตสาหกรรมเดียวมากเกินไป กระจายทั้งประเภทสินทรัพย์ ประเทศ และช่วงเวลาที่เข้าซื้อ

## เงินสำรองฉุกเฉิน

ควรมีเงินสดพอใช้จ่าย 3-6 เดือนก่อนเริ่มลงทุนจริงจัง
"""
    result = chunk_text(sample, chunk_size=800, overlap=100)
    print(f"หั่นได้ {len(result)} chunks\n")
    for c in result:
        print(f"--- chunk {c.chunk_index} | heading: {c.heading!r} | {len(c.text)} ตัวอักษร")
        print(c.text)
        print()

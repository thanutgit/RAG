"""
readers/csv_reader.py
อ่าน .csv และ .tsv แปลงเป็นตาราง Markdown

ประเด็นสำคัญของข้อมูลตาราง:
  ถ้าหั่นตามตัวอักษรเฉย ๆ แถวข้อมูลจะหลุดจาก header ทำให้ตัวเลขในแถวนั้น
  ไม่รู้ว่าเป็นคอลัมน์อะไร เลยแบ่งเป็นบล็อกละ N แถว แล้ว "แนบ header ซ้ำทุกบล็อก"
  เพื่อให้ทุก chunk อ่านเข้าใจได้ด้วยตัวเอง
"""

import csv
from pathlib import Path

from readers.base import Document, ReaderError, escape_md_cell, resolve_path

ROWS_PER_BLOCK = 25  # จำนวนแถวต่อหนึ่งบล็อก (หนึ่ง section ใน Markdown)
MAX_ROWS = 5000  # กันไฟล์ใหญ่เกินจนใช้เวลานานผิดปกติ


def _sniff_dialect(sample: str, suffix: str):
    if suffix == ".tsv":
        return csv.excel_tab
    try:
        return csv.Sniffer().sniff(sample, delimiters=",;\t|")
    except csv.Error:
        return csv.excel  # เดาไม่ได้ -> ใช้ comma ตามค่าเริ่มต้น


def read(path: str | Path) -> Document:
    p = resolve_path(path)

    try:
        raw = p.read_text(encoding="utf-8-sig")
    except UnicodeDecodeError:
        try:
            raw = p.read_text(encoding="cp874")
        except UnicodeDecodeError as e:
            raise ReaderError(f"อ่าน encoding ไม่ได้: {p.name} ({e})") from e

    dialect = _sniff_dialect(raw[:4096], p.suffix.lower())
    rows = list(csv.reader(raw.splitlines(), dialect))
    rows = [r for r in rows if any(str(c).strip() for c in r)]  # ตัดแถวว่าง

    if not rows:
        raise ReaderError(f"ไฟล์ว่างหรือไม่มีข้อมูล: {p.name}")

    header, data = rows[0], rows[1:]
    truncated = len(data) > MAX_ROWS
    data = data[:MAX_ROWS]

    header_cells = [escape_md_cell(c) or f"คอลัมน์{i + 1}" for i, c in enumerate(header)]
    header_line = "| " + " | ".join(header_cells) + " |"
    sep_line = "| " + " | ".join("---" for _ in header_cells) + " |"

    parts = [f"# {p.stem}", ""]
    parts.append(f"ตารางข้อมูล {len(data)} แถว {len(header_cells)} คอลัมน์: " + ", ".join(header_cells))
    parts.append("")

    for start in range(0, len(data), ROWS_PER_BLOCK):
        block = data[start : start + ROWS_PER_BLOCK]
        parts.append(f"## แถวที่ {start + 1}-{start + len(block)}")
        parts.append("")
        parts.append(header_line)  # แนบ header ซ้ำทุกบล็อก
        parts.append(sep_line)
        for row in block:
            # เติมช่องว่างถ้าแถวสั้นกว่า header เพื่อให้ตารางไม่เพี้ยน
            cells = [escape_md_cell(row[i]) if i < len(row) else "" for i in range(len(header_cells))]
            # แถวที่ยาวเกิน header -> ต่อท้ายเซลล์สุดท้ายแทนที่จะตัดข้อมูลทิ้งเงียบ ๆ
            if len(row) > len(header_cells) and cells:
                extra = " ".join(escape_md_cell(c) for c in row[len(header_cells) :] if str(c).strip())
                if extra:
                    cells[-1] = f"{cells[-1]} {extra}".strip()
            parts.append("| " + " | ".join(cells) + " |")
        parts.append("")

    if truncated:
        parts.append(f"*(แสดงเฉพาะ {MAX_ROWS} แถวแรกจากทั้งหมด)*")

    return Document(
        text="\n".join(parts),
        source_path=str(p),
        file_type=p.suffix.lower().lstrip("."),
        metadata={"rows": len(data), "columns": len(header_cells), "truncated": truncated},
    )


def extract_tables(path: str | Path) -> list[dict]:
    """
    คืนข้อมูลดิบสำหรับโหลดเข้า SQL (ต่างจาก read() ที่คืน Markdown)

    คืน list ของ dict: {"name": ชื่อตาราง, "header": [...], "rows": [[...]]}
    CSV มีตารางเดียวเสมอ จึงคืน list ที่มีสมาชิกตัวเดียว
    """
    p = resolve_path(path)

    try:
        raw = p.read_text(encoding="utf-8-sig")
    except UnicodeDecodeError:
        raw = p.read_text(encoding="cp874")

    dialect = _sniff_dialect(raw[:4096], p.suffix.lower())
    rows = list(csv.reader(raw.splitlines(), dialect))
    rows = [r for r in rows if any(str(c).strip() for c in r)]

    if len(rows) < 2:
        return []

    header = [str(c).strip() for c in rows[0]]
    return [{"name": p.stem, "header": header, "rows": rows[1:]}]

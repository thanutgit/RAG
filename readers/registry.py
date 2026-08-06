"""
readers/registry.py
ทะเบียนกลาง — จับคู่นามสกุลไฟล์กับ reader ที่รับผิดชอบ

เพิ่มไฟล์ประเภทใหม่:
  1. เขียน readers/xxx_reader.py ที่มีฟังก์ชัน read(path) -> Document
  2. เพิ่มบรรทัดใน _REGISTRY ด้านล่าง
  ไม่ต้องแก้โค้ดส่วนอื่นเลย
"""

from pathlib import Path

from readers import csv_reader, docx_reader, pdf_reader, text_reader, xlsx_reader
from readers.base import Document, UnsupportedFileType

_REGISTRY = {
    ".md": text_reader.read,
    ".markdown": text_reader.read,
    ".txt": text_reader.read,
    ".csv": csv_reader.read,
    ".tsv": csv_reader.read,
    ".pdf": pdf_reader.read,
    ".docx": docx_reader.read,
    ".xlsx": xlsx_reader.read,
    ".xlsm": xlsx_reader.read,
}


def supported_extensions() -> list[str]:
    """นามสกุลทั้งหมดที่รองรับ (เรียงแล้ว) ใช้ตอนสแกน vault"""
    return sorted(_REGISTRY.keys())


def is_supported(path: str | Path) -> bool:
    return Path(path).suffix.lower() in _REGISTRY


def read_file(path: str | Path, **kwargs) -> Document:
    """
    อ่านไฟล์ด้วย reader ที่ตรงกับนามสกุล คืน Document ที่เป็น Markdown

    kwargs ส่งต่อไปยัง reader เช่น enable_ocr=False สำหรับ PDF
    reader ที่ไม่รับ argument นั้นจะถูกกรองออกอัตโนมัติ
    """
    p = Path(path)
    ext = p.suffix.lower()

    reader = _REGISTRY.get(ext)
    if reader is None:
        raise UnsupportedFileType(
            f"ไม่รองรับไฟล์ {ext or '(ไม่มีนามสกุล)'} — รองรับ: {', '.join(supported_extensions())}"
        )

    # ส่งเฉพาะ kwargs ที่ reader ตัวนั้นรับจริง
    import inspect

    accepted = set(inspect.signature(reader).parameters) - {"path"}
    filtered = {k: v for k, v in kwargs.items() if k in accepted}

    return reader(p, **filtered)

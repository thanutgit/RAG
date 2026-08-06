"""
readers/base.py
โครงสร้างข้อมูลและ exception ที่ reader ทุกตัวใช้ร่วมกัน
"""

from dataclasses import dataclass, field
from pathlib import Path


class ReaderError(Exception):
    """อ่านไฟล์ไม่สำเร็จ (ไฟล์เสีย, encoding ผิด, library หาย)"""


class UnsupportedFileType(ReaderError):
    """ไม่มี reader รองรับนามสกุลนี้"""


@dataclass
class Document:
    """
    ผลลัพธ์จาก reader — เนื้อหาที่แปลงเป็น Markdown แล้ว พร้อม metadata

    text:     เนื้อหาในรูปแบบ Markdown (pipeline ท้ายน้ำรับเฉพาะรูปแบบนี้)
    metadata: ข้อมูลประกอบที่แต่ละ reader เก็บได้ต่างกัน เช่น จำนวนหน้าของ PDF
              จำนวนแถวของ CSV — เก็บไว้เพื่อ debug และแสดงใน UI
    """

    text: str
    source_path: str
    file_type: str
    metadata: dict = field(default_factory=dict)

    @property
    def is_empty(self) -> bool:
        return not self.text.strip()


def escape_md_cell(value: str) -> str:
    """
    เตรียมค่าให้ใส่ในเซลล์ตาราง Markdown ได้อย่างปลอดภัย
    pipe จะทำให้ตารางเพี้ยน และ newline จะทำให้แถวขาด
    """
    return str(value).replace("|", "\\|").replace("\n", " ").strip()


def resolve_path(path: str | Path) -> Path:
    p = Path(path)
    if not p.exists():
        raise ReaderError(f"ไม่พบไฟล์: {p}")
    if not p.is_file():
        raise ReaderError(f"ไม่ใช่ไฟล์: {p}")
    return p

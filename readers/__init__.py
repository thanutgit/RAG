"""
readers/
เลเยอร์แปลงไฟล์ทุกประเภทให้เป็น Markdown ก่อนส่งเข้า pipeline เดิม

หลักการ: pipeline ท้ายน้ำ (chunking -> embedding -> Qdrant) ไม่ต้องรู้เลยว่า
ข้อมูลมาจากไฟล์ประเภทไหน เพิ่มไฟล์ประเภทใหม่ = เขียน reader ใหม่ 1 ตัว
ลงทะเบียนใน REGISTRY แล้วจบ ไม่ต้องแตะโค้ดส่วนอื่น
"""

from readers.base import Document, ReaderError, UnsupportedFileType
from readers.registry import is_supported, read_file, supported_extensions

__all__ = [
    "Document",
    "ReaderError",
    "UnsupportedFileType",
    "read_file",
    "supported_extensions",
    "is_supported",
]

"""
readers/text_reader.py
อ่านไฟล์ข้อความล้วน: .md, .txt

.md ส่งต่อตรง ๆ เพราะเป็นรูปแบบเป้าหมายอยู่แล้ว
.txt ไม่มีโครงสร้างหัวข้อ chunking จะ fallback ไปหั่นตามย่อหน้าเอง
"""

from pathlib import Path

from readers.base import Document, ReaderError, resolve_path

# encoding ที่เจอบ่อยกับไฟล์ภาษาไทยเก่า ไล่ลองตามลำดับ
_FALLBACK_ENCODINGS = ["utf-8", "utf-8-sig", "cp874", "tis-620"]


def _read_with_fallback(path: Path) -> tuple[str, str]:
    """อ่านไฟล์โดยไล่ลอง encoding หลายตัว คืน (เนื้อหา, encoding ที่ใช้ได้)"""
    last_error = None
    for enc in _FALLBACK_ENCODINGS:
        try:
            return path.read_text(encoding=enc), enc
        except UnicodeDecodeError as e:
            last_error = e
    raise ReaderError(f"อ่าน encoding ไม่ได้: {path.name} ({last_error})")


def read(path: str | Path) -> Document:
    p = resolve_path(path)
    text, encoding = _read_with_fallback(p)

    # .txt ไม่มีหัวข้อ ใส่ชื่อไฟล์เป็น H1 ให้ chunking มีบริบทอ้างอิง
    if p.suffix.lower() == ".txt" and not text.lstrip().startswith("#"):
        text = f"# {p.stem}\n\n{text}"

    return Document(
        text=text,
        source_path=str(p),
        file_type=p.suffix.lower().lstrip("."),
        metadata={"encoding": encoding, "chars": len(text)},
    )

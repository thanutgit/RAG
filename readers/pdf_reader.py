"""
readers/pdf_reader.py
อ่าน .pdf พร้อม OCR fallback สำหรับไฟล์สแกน

ทำไมใช้ pdfplumber แทน pypdf:
  ทดสอบกับ Resume ที่ทำจากโปรแกรมออกแบบ (มีการปรับ letter-spacing เพื่อความสวยงาม)
  พบว่า pypdf ดึงข้อความออกมาเป็น "Main tained and optimiz ed s yst em perf ormance"
  เพราะมันแปลงระยะห่างระหว่างตัวอักษรเป็นช่องว่างจริง ทำให้ embedding มองเป็นคนละคำ
  pdfplumber ใช้พิกัดของตัวอักษรตัดสินว่าอันไหนเป็นคำเดียวกัน จึงได้ข้อความถูกต้อง
  และเรียงลำดับเนื้อหาในเอกสารหลายคอลัมน์ได้ดีกว่ามาก

PDF มี 3 กรณีที่ต้องจัดการต่างกัน:
  1. Text-based -> ดึงชั้นข้อความได้ตรง ๆ (เร็ว แม่นยำ)
  2. Scanned    -> เป็นรูปภาพล้วน ต้อง OCR (ช้า แม่นยำน้อยกว่า)
  3. Hybrid     -> บางหน้ามีข้อความ บางหน้าเป็นรูป -> ตัดสินใจ OCR ทีละหน้า
"""

import re
from pathlib import Path

from readers.base import Document, ReaderError, resolve_path

MIN_CHARS_PER_PAGE = 50  # หน้าที่ได้ข้อความน้อยกว่านี้ ถือว่าน่าจะเป็นหน้าสแกน
OCR_LANGUAGES = "tha+eng"
OCR_DPI = 200

# x_tolerance ต่ำ = รวมตัวอักษรที่ห่างกันน้อยเข้าเป็นคำเดียวกัน
# ค่านี้สำคัญกับเอกสารที่ปรับ letter-spacing
X_TOLERANCE = 1.5
Y_TOLERANCE = 3


def _extract_text_layer(p: Path) -> tuple[list[str], int]:
    """ดึงชั้นข้อความจาก PDF คืน (ข้อความรายหน้า, จำนวนหน้า)"""
    try:
        import pdfplumber
    except ImportError:
        raise ReaderError("ต้องติดตั้ง pdfplumber ก่อน: pip install pdfplumber") from None

    try:
        with pdfplumber.open(str(p)) as pdf:
            pages = []
            for page in pdf.pages:
                try:
                    text = (
                        page.extract_text(
                            x_tolerance=X_TOLERANCE,
                            y_tolerance=Y_TOLERANCE,
                        )
                        or ""
                    )
                except Exception:
                    text = ""
                pages.append(text.strip())
            return pages, len(pdf.pages)
    except Exception as e:
        msg = str(e).lower()
        if "password" in msg or "encrypt" in msg:
            raise ReaderError(f"PDF ถูกเข้ารหัสด้วยรหัสผ่าน: {p.name}") from e
        raise ReaderError(f"เปิด PDF ไม่ได้: {p.name} ({e})") from e


def _ocr_pages(p: Path, page_numbers: list[int]) -> dict[int, str]:
    """OCR เฉพาะหน้าที่ระบุ คืน {เลขหน้า(เริ่มที่ 0): ข้อความ}"""
    try:
        import pytesseract
        from pdf2image import convert_from_path
    except ImportError:
        raise ReaderError(
            "ต้องติดตั้งเครื่องมือ OCR ก่อน:\n"
            "  pip install pytesseract pdf2image\n"
            "  sudo apt install tesseract-ocr tesseract-ocr-tha poppler-utils"
        ) from None

    results = {}
    for n in page_numbers:
        try:
            images = convert_from_path(str(p), dpi=OCR_DPI, first_page=n + 1, last_page=n + 1)
            if images:
                results[n] = pytesseract.image_to_string(images[0], lang=OCR_LANGUAGES).strip()
        except Exception as e:
            results[n] = ""
            print(f"   ⚠️  OCR หน้า {n + 1} ไม่สำเร็จ: {e}")

    return results


def _looks_like_garbage(text: str) -> bool:
    """
    เดาว่าผล OCR เป็นขยะหรือไม่

    ใช้กับกรณีที่ Tesseract พยายามอ่านสิ่งที่มันอ่านไม่ได้ (ลายมือ ภาพวาด แผนภาพ)
    แล้วคายตัวอักษรมั่ว ๆ ออกมา ซึ่งแย่กว่าไม่ได้อะไรเลย เพราะข้อมูลขยะจะเข้าไป
    ปนใน vector store แล้วถูกดึงมาตอบคำถามในอนาคตโดยไม่มีใครรู้ที่มา
    """
    stripped = "".join(text.split())
    if len(stripped) < 20:
        return True

    alnum = sum(c.isalnum() for c in stripped)
    if alnum / len(stripped) < 0.55:
        return True

    tokens = [t for t in text.split() if t]
    if tokens:
        avg_len = sum(len(t) for t in tokens) / len(tokens)
        # ภาษาไทยไม่มีช่องว่างระหว่างคำ ปกติ token จะยาว ถ้าสั้นมากแปลว่าแตกกระจาย
        if avg_len < 2.0:
            return True

    return False


# บรรทัดตัวพิมพ์ใหญ่ล้วน สั้น ไม่จบด้วยวรรคตอน -> มักเป็นหัวข้อ
# (PDF ไม่มีข้อมูลว่าบรรทัดไหนเป็นหัวข้อ ต้องเดาจากรูปแบบ)
_HEADING_LINE = re.compile(r"^[A-Z][A-Z\s&/-]{2,40}$")


def _promote_headings(text: str) -> str:
    """แปลงบรรทัดที่น่าจะเป็นหัวข้อให้เป็น Markdown heading (### เพราะ ## ใช้กับเลขหน้าแล้ว)"""
    out = []
    for line in text.split("\n"):
        stripped = line.strip()
        if stripped and _HEADING_LINE.match(stripped) and len(stripped.split()) <= 4:
            out.extend(["", f"### {stripped.title()}", ""])
        else:
            out.append(line)
    return "\n".join(out)


def read(path: str | Path, enable_ocr: bool = True) -> Document:
    p = resolve_path(path)
    pages, total = _extract_text_layer(p)

    sparse = [i for i, t in enumerate(pages) if len(t) < MIN_CHARS_PER_PAGE]
    ocr_used = []
    ocr_rejected = []

    if sparse and enable_ocr:
        print(f"   ℹ️  {p.name}: {len(sparse)}/{total} หน้าไม่มีชั้นข้อความ กำลัง OCR...")
        try:
            ocr_text = _ocr_pages(p, sparse)
            for n, t in ocr_text.items():
                if _looks_like_garbage(t):
                    ocr_rejected.append(n + 1)
                    continue
                if len(t) > len(pages[n]):
                    pages[n] = t
                    ocr_used.append(n + 1)
        except ReaderError as e:
            print(f"   ⚠️  ข้าม OCR: {e}")

    if ocr_rejected:
        print(
            f"   ⚠️  {p.name}: ข้าม {len(ocr_rejected)} หน้าที่ OCR ได้ผลไม่น่าเชื่อถือ "
            f"(หน้า {', '.join(map(str, ocr_rejected[:5]))}"
            f"{'...' if len(ocr_rejected) > 5 else ''})\n"
            f"       หน้าเหล่านี้อาจเป็นลายมือหรือภาพวาด ซึ่ง OCR ตัวพิมพ์อ่านไม่ได้\n"
            f"       ถ้าเป็นโน้ตลายมือจาก iPad แนะนำให้ใช้ฟีเจอร์แปลงลายมือเป็นข้อความ\n"
            f"       ในแอป (GoodNotes, Notability, Apple Notes) แล้ว export เป็น .txt แทน"
        )

    parts = [f"# {p.stem}", ""]
    empty_pages = 0

    for i, text in enumerate(pages):
        if not text.strip():
            empty_pages += 1
            continue
        # หลายหน้า -> คั่นด้วยเลขหน้า, หน้าเดียว -> ไม่ต้องมี เพราะไม่ให้ข้อมูลอะไร
        if total > 1:
            parts.extend([f"## หน้า {i + 1}", ""])
        parts.append(_promote_headings(text))
        parts.append("")

    doc = Document(
        text="\n".join(parts),
        source_path=str(p),
        file_type="pdf",
        metadata={
            "pages": total,
            "empty_pages": empty_pages,
            "ocr_pages": ocr_used,
            "ocr_rejected_pages": ocr_rejected,
            "used_ocr": bool(ocr_used),
        },
    )

    if doc.is_empty or len(doc.text) < 100:
        if ocr_rejected:
            raise ReaderError(
                f"ดึงข้อความจาก {p.name} ไม่ได้ — เนื้อหาน่าจะเป็นลายมือหรือภาพวาด\n"
                f"      OCR รองรับเฉพาะตัวพิมพ์ ไม่รองรับลายมือ (โดยเฉพาะภาษาไทย)\n"
                f"      ทางแก้: ใช้ฟีเจอร์แปลงลายมือเป็นข้อความในแอปที่ใช้จด "
                f"แล้ว export เป็น .txt หรือ .md"
            )
        raise ReaderError(f"ดึงข้อความจาก {p.name} ไม่ได้เลย (อาจเป็นไฟล์สแกนและยังไม่ได้ติดตั้ง OCR)")

    return doc

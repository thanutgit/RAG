"""
tests/test_readers.py
ทดสอบ reader layer — การแปลงไฟล์แต่ละประเภทเป็น Markdown

สร้างไฟล์ทดสอบขึ้นเองใน tmp_path จึงไม่ต้องพึ่งไฟล์ภายนอก
ครอบเคสสกปรกที่เจอจริง: encoding เก่า, คอลัมน์ไม่เท่ากัน, delimiter แปลก
"""

import csv

import pytest

from readers import is_supported, read_file, supported_extensions
from readers.base import ReaderError, UnsupportedFileType

# ---------------------------------------------------------------- registry


class TestRegistry:
    @pytest.mark.parametrize("ext", [".md", ".txt", ".csv", ".tsv", ".pdf", ".docx", ".xlsx"])
    def test_รองรับนามสกุลที่ควรรองรับ(self, ext):
        assert is_supported(f"file{ext}")
        assert ext in supported_extensions()

    @pytest.mark.parametrize("name", ["file.exe", "file.zip", "file.png", "noextension"])
    def test_ไม่รองรับนามสกุลอื่น(self, name):
        assert not is_supported(name)

    def test_ไฟล์ที่ไม่รองรับต้อง_raise(self, tmp_path):
        f = tmp_path / "x.zip"
        f.write_bytes(b"data")
        with pytest.raises(UnsupportedFileType):
            read_file(f)

    def test_ไฟล์ไม่มีอยู่จริงต้อง_raise(self, tmp_path):
        with pytest.raises(ReaderError):
            read_file(tmp_path / "ไม่มีไฟล์นี้.md")


# ---------------------------------------------------------------- text


class TestTextReader:
    def test_อ่าน_md_ตรง_ๆ(self, tmp_path):
        f = tmp_path / "note.md"
        f.write_text("# หัวข้อ\n\nเนื้อหาภาษาไทย", encoding="utf-8")
        d = read_file(f)
        assert "# หัวข้อ" in d.text and d.file_type == "md"

    def test_txt_ได้ชื่อไฟล์เป็นหัวข้อ(self, tmp_path):
        """
        .txt ไม่มีโครงสร้างหัวข้อ ถ้าไม่เติมให้ chunking จะไม่มีจุดอ้างอิง
        """
        f = tmp_path / "บันทึก.txt"
        f.write_text("เนื้อหาไม่มีหัวข้อ", encoding="utf-8")
        d = read_file(f)
        assert d.text.startswith("# บันทึก")

    def test_encoding_เก่ายังอ่านได้(self, tmp_path):
        """
        บั๊กจริง: ไฟล์ไทยจาก Excel รุ่นเก่าเป็น cp874 ไม่ใช่ utf-8
        ถ้าไม่มี fallback จะ raise UnicodeDecodeError แล้วข้ามไฟล์ไปเงียบ ๆ
        """
        f = tmp_path / "เก่า.txt"
        f.write_text("ปากกาลูกลื่นสีน้ำเงิน", encoding="cp874")
        d = read_file(f)
        assert "ปากกาลูกลื่น" in d.text
        assert d.metadata["encoding"] == "cp874"


# ---------------------------------------------------------------- csv


def _write_csv(path, rows, delimiter=","):
    with open(path, "w", encoding="utf-8", newline="") as fh:
        csv.writer(fh, delimiter=delimiter).writerows(rows)


class TestCsvReader:
    def test_แปลงเป็นตาราง_markdown(self, tmp_path):
        f = tmp_path / "data.csv"
        _write_csv(f, [["ชื่อ", "ราคา"], ["ปากกา", "15"], ["สมุด", "89"]])
        d = read_file(f)
        assert "| ชื่อ | ราคา |" in d.text
        assert "| ปากกา | 15 |" in d.text
        assert d.metadata["rows"] == 2

    def test_เดา_delimiter_semicolon(self, tmp_path):
        """Excel ฝั่งยุโรป export เป็น ; ไม่ใช่ ,"""
        f = tmp_path / "euro.csv"
        _write_csv(f, [["Region", "Total"], ["North", "100"]], delimiter=";")
        d = read_file(f)
        assert "| Region | Total |" in d.text

    def test_escape_pipe_ในเซลล์(self, tmp_path):
        """
        pipe ในเนื้อหาจะทำให้ตาราง Markdown เพี้ยนถ้าไม่ escape
        """
        f = tmp_path / "tricky.csv"
        _write_csv(f, [["id", "note"], ["1", "ทำ A | ทำ B"]])
        d = read_file(f)
        assert "\\|" in d.text

    def test_แถวที่คอลัมน์ไม่ครบ(self, tmp_path):
        f = tmp_path / "messy.csv"
        with open(f, "w", encoding="utf-8", newline="") as fh:
            w = csv.writer(fh)
            w.writerow(["a", "b", "c"])
            w.writerow(["1", "2", "3"])
            w.writerow(["4", "5"])  # ขาด 1 คอลัมน์
        d = read_file(f)
        assert "| 4 | 5 |  |" in d.text, "ต้องเติมช่องว่างให้ครบ"

    def test_แถวที่คอลัมน์เกินต้องไม่หายไป(self, tmp_path):
        """
        บั๊กจริง: ค่าส่วนเกินถูกตัดทิ้งเงียบ ๆ เจอตอนทดสอบด้วย dirty data
        """
        f = tmp_path / "extra.csv"
        with open(f, "w", encoding="utf-8", newline="") as fh:
            w = csv.writer(fh)
            w.writerow(["a", "b"])
            w.writerow(["1", "2", "ข้อมูลเกิน"])
        d = read_file(f)
        assert "ข้อมูลเกิน" in d.text

    def test_ข้ามแถวว่าง(self, tmp_path):
        f = tmp_path / "blank.csv"
        with open(f, "w", encoding="utf-8", newline="") as fh:
            w = csv.writer(fh)
            w.writerow(["a", "b"])
            w.writerow([])
            w.writerow(["1", "2"])
        d = read_file(f)
        assert d.metadata["rows"] == 1

    def test_แนบ_header_ซ้ำทุกบล็อก(self, tmp_path):
        """
        ตารางใหญ่ถูกหั่นหลาย chunk ถ้า header ไม่ซ้ำ แถวข้อมูลจะไม่รู้ว่า
        ตัวเลขนั้นเป็นคอลัมน์อะไร
        """
        f = tmp_path / "big.csv"
        rows = [["id", "value"]] + [[str(i), str(i * 10)] for i in range(60)]
        _write_csv(f, rows)
        d = read_file(f)
        assert d.text.count("| id | value |") >= 2

    def test_ไฟล์ว่างต้อง_raise(self, tmp_path):
        f = tmp_path / "empty.csv"
        f.write_text("", encoding="utf-8")
        with pytest.raises(ReaderError):
            read_file(f)


# ---------------------------------------------------------------- xlsx


class TestXlsxReader:
    @pytest.fixture
    def workbook(self, tmp_path):
        openpyxl = pytest.importorskip("openpyxl")
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = "ข้อมูล"
        ws.append(["📊 รายงานยอดขาย"])  # หัวเรื่องก่อนตาราง
        ws.append([])
        ws.append(["เดือน", "ยอดขาย", "กำไร"])
        for i, m in enumerate(["มกราคม", "กุมภาพันธ์", "มีนาคม"], start=1):
            ws.append([m, i * 1000, i * 200])
        path = tmp_path / "report.xlsx"
        wb.save(path)
        return path

    def test_แต่ละชีทเป็น_section(self, workbook):
        d = read_file(workbook)
        assert "## ข้อมูล" in d.text

    def test_หา_header_ที่ไม่ได้อยู่แถวแรก(self, workbook):
        """header จริงอยู่แถว 3 เพราะมีหัวเรื่องกับแถวว่างนำหน้า"""
        d = read_file(workbook)
        assert "| เดือน | ยอดขาย | กำไร |" in d.text

    def test_อ่านข้อมูลครบ(self, workbook):
        d = read_file(workbook)
        for m in ["มกราคม", "กุมภาพันธ์", "มีนาคม"]:
            assert m in d.text
        assert d.metadata["sheets"]


# ---------------------------------------------------------------- contract


class TestReaderContract:
    """reader ทุกตัวต้องคืน Document ที่หน้าตาเหมือนกัน"""

    def test_ทุก_reader_คืนโครงสร้างเดียวกัน(self, tmp_path):
        md = tmp_path / "a.md"
        md.write_text("# หัวข้อ\n\nเนื้อหา", encoding="utf-8")

        csv_file = tmp_path / "b.csv"
        _write_csv(csv_file, [["a", "b"], ["1", "2"]])

        for f in [md, csv_file]:
            d = read_file(f)
            assert isinstance(d.text, str) and d.text.strip()
            assert isinstance(d.source_path, str)
            assert isinstance(d.file_type, str)
            assert isinstance(d.metadata, dict)
            assert not d.is_empty

    def test_ผลลัพธ์เป็น_markdown_เสมอ(self, tmp_path):
        """
        pipeline ท้ายน้ำ (chunking) คาดหวัง Markdown ทุก reader ต้องคืนรูปแบบนี้
        """
        f = tmp_path / "data.csv"
        _write_csv(f, [["a", "b"], ["1", "2"]])
        d = read_file(f)
        assert d.text.lstrip().startswith("#"), "ต้องมี heading เพื่อให้ chunking แยก section ได้"

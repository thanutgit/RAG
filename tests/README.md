# Tests

> เจอบั๊กใหม่แล้วไม่รู้จะเพิ่ม test ยังไง → อ่าน [HOWTO_ADD_TEST.md](HOWTO_ADD_TEST.md)

## รันแบบเร็ว (แนะนำให้รันทุกครั้งหลังแก้โค้ด)

```bash
pytest -m "not llm"
```

ใช้เวลา ~3 วินาที ไม่ต้องมี Ollama หรือ PostgreSQL

| ไฟล์ | จำนวน | ครอบอะไร |
|:---|:---|:---|
| `test_sql_safety.py` | 26 | ตัวตรวจและตัวซ่อม SQL |
| `test_readers.py` | 29 | การแปลงไฟล์แต่ละประเภทเป็น Markdown |
| `test_normalize.py` | 14 | Unicode normalization ภาษาไทย |
| `test_chunking.py` | 13 | การหั่นเอกสารตามโครงสร้าง |
| `test_rewrite.py` | 9 | การเขียนคำถามใหม่จากบริบท |

## รันแบบเต็ม (หลังแก้ prompt)

```bash
pytest
```

ใช้เวลา ~2-4 นาที ต้องมี PostgreSQL + Ollama รันอยู่ และ ingest ข้อมูลแล้ว
ทดสอบ text-to-SQL แบบ end-to-end ด้วยคำถามที่รู้คำตอบแน่นอน

## รันเฉพาะ e2e

```bash
pytest -m llm -v
```

---

## ทำไมต้องแยกสองระดับ

การแก้ prompt หนึ่งจุดอาจทำให้อีกจุดพัง โดยไม่มี error ใด ๆ ให้เห็น
เช่นเพิ่มกฎ `COUNT(*) OVER ()` เพื่อแก้ปัญหาหนึ่ง แล้ว LLM เอาไปใช้กับ `GROUP BY`
ทำให้ได้ตัวเลขผิดในอีกคำถามหนึ่ง

test เร็วจับปัญหาที่ตรวจได้จากรูปแบบ SQL โดยไม่ต้องรัน LLM
test ช้าจับปัญหาที่เกิดจากพฤติกรรมของ LLM เอง ซึ่งเปลี่ยนได้ทุกครั้งที่แก้ prompt

## บั๊กที่ test ชุดนี้ครอบไว้

ทุกข้อเคยเกิดขึ้นจริงระหว่างพัฒนา:

| บั๊ก | อาการ | test ที่ครอบ |
|:---|:---|:---|
| `COUNT(*) OVER ()` + `GROUP BY` | นับจำนวนกลุ่ม (5) แทนสมาชิก (66) | `test_fixes_window_function_with_groupby` |
| ใส่ `WHERE` ที่คำถามไม่ได้ขอ | ถาม "ทีมไหนมากที่สุด" ได้ 41 แทน 66 | `test_strips_unrequested_filter` |
| LLM นับจากรายการที่ถูกตัด | ตอบ 113 จากข้อมูลจริง 76 | `test_reports_true_count_when_truncated` |
| Rewriting แต่งคำตอบปลอม | ค้นหาด้วยคำตอบที่โมเดลแต่งขึ้น | `test_rejects_fabricated_answer` |
| Rewriting เปลี่ยนคำสำคัญ | ถาม production ได้คำตอบของ staging | `test_rejects_changed_keyword` |
| LLM เดาชื่อตารางผิด | พังด้วย UndefinedTable ดิบ ๆ | `test_rejects_unknown_table` |
| Chunking ตัดกลางคำไทย | คำตอบขาดกลางประโยค | `test_ไม่ตัดกลางคำ` |
| หัวข้อแยกจากเนื้อหา | retrieve เจอหัวข้อลอย ๆ | `test_เนื้อหาใต้หัวข้ออยู่ครบใน_chunk_เดียว` |
| `เเ` vs `แ` ใน Unicode | คำถามเดียวกันได้ score ต่างกัน | `test_เ_สองตัว_เท่ากับ_แ` |
| encoding cp874 อ่านไม่ได้ | ไฟล์ไทยเก่าถูกข้ามเงียบ ๆ | `test_encoding_เก่ายังอ่านได้` |
| แถวที่คอลัมน์เกินหายไป | ข้อมูลถูกตัดทิ้งโดยไม่แจ้ง | `test_แถวที่คอลัมน์เกินต้องไม่หายไป` |
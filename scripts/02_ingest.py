"""
CLI wrapper สำหรับ ingest_service.run_ingest()
Logic จริงทั้งหมดอยู่ใน services/ingest_service.py — ไฟล์นี้แค่เรียกใช้ + print ผลลัพธ์

รัน: python scripts/02_ingest.py
     python scripts/02_ingest.py --force
"""

import argparse
import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parent.parent))
from services.ingest_service import run_ingest


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--force", action="store_true", help="บังคับ re-ingest ทุกไฟล์")
    args = parser.parse_args()

    print("กำลัง ingest...")
    stats = run_ingest(force=args.force)

    for d in stats["details"]:
        icon = {
            "new": "✅ ใหม่",
            "updated": "🔄 อัปเดต",
            "skipped": "⏭️  ข้าม",
            "deleted": "🗑️  ลบ",
            "empty": "⚠️  ว่าง",
            "empty_or_failed": "⚠️  ล้มเหลว",
            "error_read": "❌ อ่านไม่ได้",
            "error_encoding": "❌ encoding ผิด",
        }.get(d["action"], d["action"])
        extra = f" ({d['chunks']} chunks)" if "chunks" in d else ""
        print(f"{icon}: {d['file']}{extra}")
        if d.get("error"):
            print(f"    ↳ {d['error']}")

    print(
        f"\nสรุป: ใหม่ {stats['new']} | อัปเดต {stats['updated']} | "
        f"ข้าม {stats['skipped']} | ลบ {stats['deleted']}"
    )
    print(f"embed ใหม่ทั้งหมด {stats['chunks_embedded']} chunks")
    print(f"ตอนนี้ Qdrant มีข้อมูลรวม {stats['total_chunks_in_db']} chunks")


if __name__ == "__main__":
    main()

"""
CLI wrapper สำหรับ query_service.run_query()
Logic จริงทั้งหมดอยู่ใน services/query_service.py — ไฟล์นี้แค่ทำ interactive loop รับ input

รัน: python scripts/03_query.py
"""

import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parent.parent))
from services import qdrant_service
from services.query_service import run_query


def main():
    client = qdrant_service.get_client()
    n = qdrant_service.count(client)
    print(f"พร้อมใช้งาน — มีข้อมูลอยู่ {n} chunks")
    print("พิมพ์คำถาม (หรือ 'exit' เพื่อออก)\n")

    while True:
        question = input("❓ คำถาม: ").strip()
        if question.lower() in ("exit", "quit"):
            break
        if not question:
            continue

        result = run_query(question)

        print(f"\n🔍 พบ {len(result['sources'])} chunks ที่เกี่ยวข้อง:")
        for s in result["sources"]:
            print(f"   - {s['file_path']} (score: {s['score']})")
            print(f"     เนื้อหา: {s['text_preview']}...")

        print(f"\n💬 คำตอบ ({result['latency_ms']} ms):\n{result['answer']}\n")
        print("-" * 60)


if __name__ == "__main__":
    main()

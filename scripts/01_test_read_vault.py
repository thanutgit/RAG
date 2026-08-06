"""
Phase 2 - Step 1: ทดสอบอ่านไฟล์ .md จาก Obsidian Vault
ยังไม่ทำ embedding อะไรทั้งนั้น — แค่ยืนยันว่า path ถูก และอ่านไฟล์ได้ครบ

รัน: python scripts/01_test_read_vault.py
"""

import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

VAULT_PATH = os.getenv("OBSIDIAN_VAULT_PATH")


def main():
    if not VAULT_PATH:
        raise SystemExit("ไม่พบ OBSIDIAN_VAULT_PATH ใน .env — เช็คว่าไฟล์ .env อยู่ใน โฟลเดอร์เดียวกับที่รันสคริปต์นี้หรือไม่")

    vault = Path(VAULT_PATH)
    if not vault.exists():
        raise SystemExit(f"หา path ไม่เจอ: {vault}\nเช็ค OBSIDIAN_VAULT_PATH ใน .env อีกครั้ง")

    md_files = sorted(vault.rglob("*.md"))

    print(f"Vault path : {vault}")
    print(f"พบไฟล์ .md ทั้งหมด: {len(md_files)} ไฟล์\n")

    if not md_files:
        print("⚠️  ไม่พบไฟล์ .md เลย — ลองสร้างโน้ตทดสอบใน Obsidian สัก 2-3 ไฟล์ก่อน")
        return

    # โชว์ 5 ไฟล์แรก พร้อม preview เนื้อหา 100 ตัวอักษร เพื่อเช็คว่าอ่านภาษาไทยได้ปกติ
    for f in md_files[:5]:
        try:
            content = f.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            print(f"❌ อ่าน encoding ไม่ได้: {f.relative_to(vault)}")
            continue

        preview = content.strip().replace("\n", " ")[:100]
        print(f"📄 {f.relative_to(vault)}")
        print(f"   ขนาด: {len(content)} ตัวอักษร")
        print(f"   ตัวอย่าง: {preview}...\n")

    if len(md_files) > 5:
        print(f"... และอีก {len(md_files) - 5} ไฟล์")


if __name__ == "__main__":
    main()

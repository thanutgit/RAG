"""
services/ingest_service.py
Ingestion Pipeline พร้อม Incremental Sync
เรียกใช้จาก scripts/02_ingest.py (CLI) หรือ app/main.py (REST API) ก็ได้ — logic เดียวกัน
"""

import hashlib
import uuid
from pathlib import Path

import requests
from qdrant_client.models import PointStruct

from readers import ReaderError, is_supported, read_file, supported_extensions
from services import config, postgres_service, qdrant_service, tabular_service
from services.ollama_service import get_embedding
from utils.chunking import chunk_text


def compute_hash(content: str) -> str:
    """สร้าง fingerprint จากข้อความ"""
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


TABULAR_EXTENSIONS = {".csv", ".tsv", ".xlsx", ".xlsm"}


def _extract_tables(path: Path) -> list[dict]:
    """ดึงข้อมูลดิบจากไฟล์ตาราง (คนละทางกับ read_file ที่คืน Markdown)"""
    ext = path.suffix.lower()
    if ext in {".csv", ".tsv"}:
        from readers.csv_reader import extract_tables
    else:
        from readers.xlsx_reader import extract_tables
    return extract_tables(path)


def compute_file_hash(path: Path) -> str:
    """
    สร้าง fingerprint จากไฟล์ดิบ (bytes)

    ใช้ bytes แทนข้อความที่แปลงแล้ว เพราะ:
      - PDF/DOCX เป็น binary อ่านเป็น text ตรง ๆ ไม่ได้
      - ต้องรู้ว่าไฟล์เปลี่ยนไหม *ก่อน* จะแปลง เพราะ OCR ช้ามาก
    อ่านทีละก้อนเพื่อไม่ให้ไฟล์ใหญ่กินหน่วยความจำทั้งก้อน
    """
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(65536), b""):
            h.update(block)
    return h.hexdigest()


def deterministic_id(file_path: str, chunk_index: int) -> str:
    """สร้าง UUID คงที่จาก path+index -> รันซ้ำแล้ว upsert ทับของเดิม ไม่สร้างซ้ำซ้อน"""
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"{file_path}::{chunk_index}"))


def ingest_single_file(client, rel_path: str, content: str, file_type: str = "md") -> int:
    """หั่น -> embed -> upsert ลง Qdrant คืนค่าจำนวน chunk ที่บันทึกสำเร็จ"""
    chunks = chunk_text(content, chunk_size=config.CHUNK_SIZE, overlap=config.CHUNK_OVERLAP)
    if not chunks:
        return 0

    points = []
    for c in chunks:
        try:
            vector = get_embedding(c.text)
        except requests.exceptions.RequestException:
            continue  # ข้าม chunk ที่ embed ไม่สำเร็จ ไม่ทำให้ทั้งไฟล์พัง

        points.append(
            PointStruct(
                id=deterministic_id(rel_path, c.chunk_index),
                vector=vector,
                payload={
                    "file_path": rel_path,
                    "file_type": file_type,
                    "chunk_index": c.chunk_index,
                    "heading": c.heading,
                    "text": c.text,
                },
            )
        )

    qdrant_service.upsert_chunks(client, points)
    return len(points)


def run_ingest(force: bool = False) -> dict:
    """
    รัน ingestion pipeline เต็มรูปแบบทั้ง vault
    คืนค่า dict สรุปผล -> ใช้ทั้งใน CLI (print) และ FastAPI (JSON response)
    """
    if not config.VAULT_PATH or not Path(config.VAULT_PATH).exists():
        raise FileNotFoundError("OBSIDIAN_VAULT_PATH ไม่ถูกต้อง เช็คไฟล์ .env")

    vault = Path(config.VAULT_PATH)
    # สแกนทุกนามสกุลที่มี reader รองรับ ไม่ใช่แค่ .md
    files = sorted(f for f in vault.rglob("*") if f.is_file() and is_supported(f))

    client = qdrant_service.get_client()
    qdrant_service.ensure_collection(client)

    conn = postgres_service.get_connection()
    tabular_service.ensure_catalog(conn)
    known_docs = postgres_service.load_document_state(conn)

    stats = {
        "total_files": len(files),
        "supported_types": supported_extensions(),
        "new": 0,
        "updated": 0,
        "skipped": 0,
        "deleted": 0,
        "chunks_embedded": 0,
        "sql_tables": 0,
        "details": [],  # log ต่อไฟล์ ใช้โชว์ผลละเอียดผ่าน API
    }
    seen_paths = set()

    for f in files:
        rel_path = str(f.relative_to(vault))
        seen_paths.add(rel_path)

        # hash จากไฟล์ดิบ (bytes) ไม่ใช่จากข้อความที่แปลงแล้ว
        # เพราะ PDF/DOCX เป็น binary และการแปลงอาจให้ผลต่างกันเล็กน้อยในแต่ละครั้ง
        try:
            new_hash = compute_file_hash(f)
        except OSError as e:
            stats["details"].append({"file": rel_path, "action": "error_read", "error": str(e)})
            continue
        old_hash = known_docs.get(rel_path)

        if old_hash == new_hash and not force:
            stats["skipped"] += 1
            stats["details"].append({"file": rel_path, "action": "skipped"})
            continue

        # อ่านเนื้อหาหลังเช็ค hash แล้วเท่านั้น
        # สำคัญมากกับ PDF ที่ต้อง OCR เพราะช้ามาก ไม่ควรทำซ้ำถ้าไฟล์ไม่เปลี่ยน
        try:
            doc = read_file(f)
        except ReaderError as e:
            stats["details"].append({"file": rel_path, "action": "error_read", "error": str(e)})
            continue

        if doc.is_empty:
            stats["details"].append({"file": rel_path, "action": "empty"})
            continue

        is_update = old_hash is not None
        if is_update:
            qdrant_service.delete_file_chunks(client, rel_path)

        n = ingest_single_file(client, rel_path, doc.text, file_type=doc.file_type)
        if n == 0:
            stats["details"].append({"file": rel_path, "action": "empty_or_failed"})
            continue

        postgres_service.upsert_document_state(conn, rel_path, new_hash, n)
        stats["chunks_embedded"] += n

        # ไฟล์ตาราง -> โหลดเข้า PostgreSQL ด้วย เพื่อให้ query ด้วย SQL ได้
        # (vector search ตอบคำถามประเภทนับ/รวมยอดไม่ได้ เพราะเห็นข้อมูลแค่บางส่วน)
        if f.suffix.lower() in TABULAR_EXTENSIONS:
            try:
                tabular_service.drop_tables_for_file(conn, rel_path)
                for spec in _extract_tables(f):
                    if tabular_service.load_table(conn, rel_path, spec):
                        stats["sql_tables"] += 1
            except Exception as e:
                print(f"   ⚠️  โหลดตารางเข้า SQL ไม่สำเร็จ [{rel_path}]: {e}")
                conn.rollback()

        if is_update:
            stats["updated"] += 1
            stats["details"].append({"file": rel_path, "action": "updated", "chunks": n})
        else:
            stats["new"] += 1
            stats["details"].append({"file": rel_path, "action": "new", "chunks": n})

    # ไฟล์ที่ถูกลบออกจาก vault แล้ว -> ลบออกจาก Qdrant + Postgres ด้วย
    orphaned = set(known_docs.keys()) - seen_paths
    for rel_path in orphaned:
        qdrant_service.delete_file_chunks(client, rel_path)
        postgres_service.delete_document_state(conn, rel_path)
        tabular_service.drop_tables_for_file(conn, rel_path)
        stats["deleted"] += 1
        stats["details"].append({"file": rel_path, "action": "deleted"})

    conn.close()
    stats["total_chunks_in_db"] = qdrant_service.count(client)
    return stats

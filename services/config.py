"""
services/config.py
รวม environment config ทั้งหมดไว้ที่เดียว
ไฟล์อื่นทุกไฟล์ import จากตรงนี้ ไม่อ่าน os.getenv() ซ้ำที่อื่นอีก
"""

import os

from dotenv import load_dotenv

load_dotenv()

# ---------- Obsidian Vault ----------
VAULT_PATH = os.getenv("OBSIDIAN_VAULT_PATH")

# ---------- Ollama ----------
OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
OLLAMA_EMBED_MODEL = os.getenv("OLLAMA_EMBED_MODEL", "bge-m3")
OLLAMA_LLM_MODEL = os.getenv("OLLAMA_LLM_MODEL", "qwen3:8b")
EMBED_DIM = int(os.getenv("EMBED_DIM", "1024"))

# ---------- Qdrant ----------
# host อ่านจาก env เพราะตอนรันใน container ต้องใช้ชื่อ service ไม่ใช่ localhost
QDRANT_HOST = os.getenv("QDRANT_HOST", "localhost")
QDRANT_PORT = int(os.getenv("QDRANT_HTTP_PORT", "6333"))
QDRANT_API_KEY = os.getenv("QDRANT_API_KEY") or None
QDRANT_COLLECTION = os.getenv("QDRANT_COLLECTION", "obsidian_notes")
# qdrant-client เปิด HTTPS เองเมื่อมี api_key ซึ่งใช้ไม่ได้กับ Qdrant ใน Docker
# ที่ไม่ได้ตั้ง TLS — ต้องปิดชัดเจน ยกเว้นมี reverse proxy คั่นอยู่จริง
QDRANT_USE_HTTPS = os.getenv("QDRANT_USE_HTTPS", "false").lower() in ("1", "true", "yes")

# ---------- PostgreSQL ----------
PG_CONFIG = {
    "host": os.getenv("POSTGRES_HOST", "localhost"),
    "port": int(os.getenv("POSTGRES_PORT", "5432")),
    "user": os.getenv("POSTGRES_USER"),
    "password": os.getenv("POSTGRES_PASSWORD"),
    "dbname": os.getenv("POSTGRES_DB", "obsidian_rag"),
}

# ---------- Authentication ----------
# รับหลาย key คั่นด้วย comma เพื่อให้หมุนเวียนเปลี่ยน key ได้โดยไม่ต้องหยุดระบบ
# (ใส่ key ใหม่เพิ่ม -> เปลี่ยน client ทีละตัว -> ค่อยลบ key เก่า)
# ถ้าเว้นว่างไว้ ระบบจะไม่ตรวจสิทธิ์เลย เหมาะกับตอนพัฒนาบนเครื่องตัวเอง
API_KEYS = [k.strip() for k in os.getenv("API_KEYS", "").split(",") if k.strip()]


# ---------- RAG Parameters ----------
CHUNK_SIZE = int(os.getenv("CHUNK_SIZE", "800"))
CHUNK_OVERLAP = int(os.getenv("CHUNK_OVERLAP", "100"))
TOP_K = int(os.getenv("TOP_K", "5"))
# ตัด chunk ที่ score ต่ำกว่านี้ทิ้ง ไม่ว่าจะยังไม่ครบ TOP_K ก็ตาม
# bge-m3 มักให้ score กระจายกว้าง (ต่างจาก OpenAI embeddings ที่ score สูงเสมอ)
# ค่านี้ควรปรับตามข้อมูลจริง ไม่ใช่ตัวเลขตายตัวที่ใช้ได้ทุก dataset
SCORE_THRESHOLD = float(os.getenv("SCORE_THRESHOLD", "0.45"))

# Deployment

## รันแบบ development (แนะนำตอนพัฒนา)

database อยู่ใน container ส่วน FastAPI รันบนเครื่อง แก้โค้ดแล้วเห็นผลทันที

```bash
docker compose up -d
source .venv/bin/activate
uvicorn app.main:app --reload --port 8000
```

---

## รันทั้งระบบใน container

```bash
cp .env.example .env
```

แก้ `.env` อย่างน้อย 3 ค่า:

```bash
POSTGRES_PASSWORD=<รหัสที่แข็งแรง>
QDRANT_API_KEY=<สุ่มมาใหม่ ห้ามเว้นว่าง>
OBSIDIAN_VAULT_PATH=/path/ไปยัง/vault
```

สุ่ม API key:
```bash
openssl rand -base64 32
```

รัน:
```bash
docker compose -f docker-compose.prod.yml up -d --build
docker compose -f docker-compose.prod.yml ps      # ต้อง healthy ทั้งหมด
curl http://localhost:8000/health
```

Ingest ครั้งแรก:
```bash
docker compose -f docker-compose.prod.yml exec api python scripts/02_ingest.py
```

---

## ความต่างระหว่างสอง compose

| | `docker-compose.yml` | `docker-compose.prod.yml` |
|:---|:---|:---|
| FastAPI | รันบนเครื่อง | รันใน container |
| พอร์ต database | เปิดออกภายนอก | ปิด เข้าถึงได้เฉพาะภายใน |
| Qdrant API key | ไม่ตั้ง | **บังคับ** |
| Vault | อ่านเขียนได้ | mount แบบอ่านอย่างเดียว |
| แก้โค้ดแล้ว | เห็นผลทันที | ต้อง rebuild |

---

## Ollama ไม่ได้อยู่ใน container

โดยตั้งใจ เพราะ Ollama ต้องเข้าถึง GPU โดยตรง การใส่ใน container ต้องตั้ง
NVIDIA Container Toolkit เพิ่มและซับซ้อนขึ้นมากโดยไม่ได้ประโยชน์เท่าไร

container เรียก Ollama บนเครื่องผ่าน `host.docker.internal` ซึ่งบน Linux
ต้องมี `extra_hosts: host.docker.internal:host-gateway` (ตั้งไว้แล้วใน compose)

ถ้าย้าย Ollama ไปเครื่องอื่น แก้ `OLLAMA_BASE_URL` ใน `.env` อย่างเดียวพอ

---

## ก่อน deploy จริงบนอินเทอร์เน็ต

ระบบยังไม่มี authentication — **ห้ามเปิดสู่สาธารณะตอนนี้**

ถ้าจะ deploy จริงต้องมีอย่างน้อย:

- [ ] API key authentication บน FastAPI
- [ ] Reverse proxy (nginx/Caddy) + HTTPS
- [ ] Rate limiting
- [ ] จำกัด CORS
- [ ] ตั้ง `QDRANT_API_KEY` ให้แข็งแรง
- [ ] Backup volume ทั้งสอง

ระหว่างนี้ใช้ผ่าน SSH tunnel แทน:
```bash
ssh -L 8000:localhost:8000 user@server
```

---

## CI

`.github/workflows/ci.yml` รันทุกครั้งที่ push:

| Job | ทำอะไร |
|:---|:---|
| test | `pytest -m "not llm"` — 91 tests |
| lint | `ruff check` + `ruff format --check` |
| security | ตรวจ dependency ที่มีช่องโหว่ + กันไฟล์ความลับหลุด |
| docker | build image และตรวจว่า import ครบ (รันเมื่อ test+lint ผ่าน) |

**test ที่ต้องใช้ LLM ไม่ได้อยู่ใน CI** เพราะ runner ไม่มี GPU
ต้องรัน `pytest` เต็มบนเครื่องตัวเองก่อน push ทุกครั้งที่แก้ prompt

---

## Backup

```bash
# สำรอง
docker run --rm -v obsidian_rag_postgres_data:/data -v $(pwd):/backup \
  alpine tar czf /backup/postgres-$(date +%F).tar.gz -C /data .

docker run --rm -v obsidian_rag_qdrant_data:/data -v $(pwd):/backup \
  alpine tar czf /backup/qdrant-$(date +%F).tar.gz -C /data .
```

Qdrant สร้างใหม่ได้จากการ ingest ซ้ำ แต่ PostgreSQL มีประวัติแชทที่สร้างใหม่ไม่ได้

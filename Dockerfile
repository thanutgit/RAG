# ---------- builder: ติดตั้ง dependency แยกจาก runtime ----------
# แยกสองสเตจเพื่อไม่ให้ build tool กับ cache ติดไปใน image สุดท้าย
FROM python:3.12-slim AS builder

WORKDIR /build

# ติดตั้ง build dependency ที่ psycopg2 ต้องใช้
RUN apt-get update && apt-get install -y --no-install-recommends \
        gcc libpq-dev \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir --user -r requirements.txt


# ---------- runtime ----------
FROM python:3.12-slim

# runtime dependency:
#   libpq5           - psycopg2 ต้องใช้ตอนรัน
#   poppler-utils    - pdf2image แปลง PDF เป็นรูปก่อน OCR
#   tesseract-ocr    - OCR สำหรับ PDF สแกน (+ tha สำหรับภาษาไทย)
RUN apt-get update && apt-get install -y --no-install-recommends \
        libpq5 \
        poppler-utils \
        tesseract-ocr tesseract-ocr-tha tesseract-ocr-eng \
    && rm -rf /var/lib/apt/lists/*

# รันด้วย user ธรรมดา ไม่ใช่ root — ถ้ามีช่องโหว่จะจำกัดความเสียหายได้
RUN useradd --create-home --uid 1000 appuser
WORKDIR /app

COPY --from=builder /root/.local /home/appuser/.local
ENV PATH=/home/appuser/.local/bin:$PATH \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

# คัดลอกเฉพาะโค้ดที่ต้องใช้ตอนรัน (dev files ถูกกันด้วย .dockerignore อีกชั้น)
COPY --chown=appuser:appuser app/ ./app/
COPY --chown=appuser:appuser services/ ./services/
COPY --chown=appuser:appuser readers/ ./readers/
COPY --chown=appuser:appuser utils/ ./utils/
COPY --chown=appuser:appuser scripts/ ./scripts/
COPY --chown=appuser:appuser frontend/ ./frontend/

USER appuser
EXPOSE 8000

# healthcheck เรียก endpoint จริง ไม่ใช่แค่เช็คว่า process ยังอยู่
# เพราะ process อาจยังรันแต่ต่อ Qdrant ไม่ได้แล้ว
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=4).status==200 else 1)"

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]

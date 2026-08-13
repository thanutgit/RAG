"""
services/rate_limit.py
จำกัดจำนวน request ต่อช่วงเวลา

จำเป็นแม้จะมี API key แล้ว เพราะ:
  1. กันคนยิงสุ่มเดา key
  2. กันเรียก /ingest ซ้ำ ๆ จนเครื่องทำงานหนักผิดปกติ
  3. LLM แต่ละคำถามใช้เวลาหลายวินาที ยิงพร้อมกันเยอะจะคิวยาว

เก็บสถานะใน memory เพราะระบบรัน instance เดียว
ถ้าขยายเป็นหลาย instance ต้องย้ายไปเก็บใน Redis
"""

import time
from collections import defaultdict, deque

from fastapi import HTTPException, Request, status


class RateLimiter:
    """
    Sliding window — นับ request ในช่วง N วินาทีที่ผ่านมา

    ต่างจาก fixed window ตรงที่ไม่มีช่วงรอยต่อให้ยิงทะลุได้
    (fixed window ที่รีเซ็ตทุกนาที ยิงได้ 2 เท่าถ้ายิงคร่อมรอยต่อ)
    """

    def __init__(self, max_requests: int, window_seconds: int):
        self.max_requests = max_requests
        self.window = window_seconds
        self._hits: dict[str, deque] = defaultdict(deque)

    def check(self, key: str):
        now = time.monotonic()
        hits = self._hits[key]

        # ทิ้งรายการที่เก่ากว่าหน้าต่างเวลา
        while hits and now - hits[0] > self.window:
            hits.popleft()

        if len(hits) >= self.max_requests:
            retry_after = int(self.window - (now - hits[0])) + 1
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail=f"เรียกถี่เกินไป ลองใหม่ในอีก {retry_after} วินาที",
                headers={"Retry-After": str(retry_after)},
            )

        hits.append(now)

    def reset(self):
        """ใช้ใน test"""
        self._hits.clear()


def client_id(request: Request, api_key: str | None = None) -> str:
    """
    ระบุตัวผู้เรียกเพื่อนับแยกกัน

    ใช้ API key ถ้ามี เพราะแม่นกว่า IP (หลายคนอาจอยู่หลัง NAT เดียวกัน)
    ถ้าไม่มี key ค่อยใช้ IP
    """
    if api_key and api_key != "anonymous":
        return f"key:{api_key[:12]}"
    return f"ip:{request.client.host if request.client else 'unknown'}"


# query เรียกบ่อยได้ แต่ ingest เป็นงานหนักจึงจำกัดเข้มกว่ามาก
query_limiter = RateLimiter(max_requests=30, window_seconds=60)
ingest_limiter = RateLimiter(max_requests=3, window_seconds=300)

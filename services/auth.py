"""
services/auth.py
ตรวจสอบสิทธิ์ด้วย API key

เลือกใช้ API key แทน username/password เพราะระบบนี้เป็นเครื่องมือส่วนตัว
หรือใช้ภายในทีมเล็ก ไม่ได้มีผู้ใช้หลายคนที่ต้องแยกสิทธิ์กัน
ถ้าต้องการแยกผู้ใช้จริงในอนาคต ควรเปลี่ยนไปใช้ OAuth หรือ JWT
"""

import hmac
import secrets

from fastapi import Header, HTTPException, status

from services import config


class AuthError(HTTPException):
    """ตอบ 401 พร้อมบอกวิธีส่ง key ที่ถูกต้อง"""

    def __init__(self, detail: str):
        super().__init__(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=detail,
            headers={"WWW-Authenticate": 'ApiKey realm="obsidian-rag"'},
        )


def is_auth_enabled() -> bool:
    """auth ทำงานเมื่อมีการตั้ง API_KEYS ไว้เท่านั้น"""
    return bool(config.API_KEYS)


def verify_api_key(x_api_key: str | None = Header(default=None)) -> str:
    """
    FastAPI dependency สำหรับ endpoint ที่ต้องมีสิทธิ์

    ใช้ hmac.compare_digest เทียบ key แทน == เพราะการเทียบสตริงแบบปกติ
    จะหยุดทันทีที่เจอตัวอักษรต่างกัน ทำให้เวลาที่ใช้บอกใบ้ได้ว่าเดาถูกกี่ตัว
    (timing attack) compare_digest ใช้เวลาเท่ากันเสมอไม่ว่าจะต่างตรงไหน
    """
    if not is_auth_enabled():
        return "anonymous"

    if not x_api_key:
        raise AuthError("ต้องส่ง API key มาใน header X-API-Key")

    # compare_digest รับเฉพาะ ASCII ถ้าได้สตริงที่มีอักขระอื่นจะโยน TypeError
    # จึงเทียบในรูป bytes แทน — key ที่ผิดรูปแบบต้องได้ 401 ไม่ใช่ 500
    # (500 ยังบอกใบ้ผู้โจมตีว่าเกิดอะไรขึ้นข้างในด้วย)
    try:
        received = x_api_key.encode("utf-8")
    except (UnicodeEncodeError, AttributeError):
        raise AuthError("API key ไม่ถูกต้อง") from None

    for key in config.API_KEYS:
        if hmac.compare_digest(received, key.encode("utf-8")):
            return x_api_key

    raise AuthError("API key ไม่ถูกต้อง")


def generate_key() -> str:
    """สร้าง API key ใหม่ — ใช้ตอนตั้งค่าครั้งแรก"""
    return secrets.token_urlsafe(32)


if __name__ == "__main__":
    print(generate_key())

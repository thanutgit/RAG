"""
tests/test_auth.py
ทดสอบการตรวจสิทธิ์และการจำกัดอัตราการเรียก
"""

import time

import pytest
from fastapi import HTTPException

from services import auth, config
from services.rate_limit import RateLimiter, client_id


@pytest.fixture
def with_keys(monkeypatch):
    """ตั้ง API key ชั่วคราวสำหรับ test แล้วคืนค่าเดิมเมื่อจบ"""
    keys = ["test-key-aaa", "test-key-bbb"]
    monkeypatch.setattr(config, "API_KEYS", keys)
    return keys


class TestApiKey:
    def test_ปิด_auth_เมื่อไม่ได้ตั้ง_key(self, monkeypatch):
        """
        ตอนพัฒนาบนเครื่องตัวเองไม่ควรต้องใส่ key
        แต่ตอน deploy จริงต้องบังคับให้ตั้ง (compose ใช้ ${VAR:?} บังคับไว้)
        """
        monkeypatch.setattr(config, "API_KEYS", [])
        assert not auth.is_auth_enabled()
        assert auth.verify_api_key(None) == "anonymous"

    def test_ผ่านเมื่อ_key_ถูก(self, with_keys):
        assert auth.verify_api_key(with_keys[0]) == with_keys[0]

    def test_รองรับหลาย_key(self, with_keys):
        """
        มีหลาย key เพื่อให้หมุนเวียนเปลี่ยนได้โดยไม่ต้องหยุดระบบ
        """
        for k in with_keys:
            assert auth.verify_api_key(k) == k

    @pytest.mark.parametrize(
        "bad",
        [
            None,
            "",
            "wrong-key",
            "test-key-aa",  # ใกล้เคียงแต่ไม่ตรง
            "test-key-aaaa",  # ยาวเกิน
            "TEST-KEY-AAA",  # ตัวพิมพ์ต่าง
            "คีย์ภาษาไทย",  # อักขระนอก ASCII
            "key-with-emoji-🔑",  # emoji
            "<key จาก API_KEYS>",  # placeholder ที่ลืมแทนค่า
        ],
    )
    def test_ปฏิเสธเมื่อ_key_ผิด(self, bad, with_keys):
        with pytest.raises(HTTPException) as exc:
            auth.verify_api_key(bad)
        assert exc.value.status_code == 401

    def test_key_ที่ไม่ใช่_ascii_ต้องได้_401_ไม่ใช่_500(self, with_keys):
        """
        บั๊กจริง: hmac.compare_digest รับเฉพาะ ASCII ถ้าได้ภาษาไทยจะโยน TypeError
        ทำให้ระบบตอบ 500 แทนที่จะเป็น 401
        นอกจากผิดความหมายแล้ว 500 ยังบอกใบ้ผู้โจมตีว่าเกิดอะไรขึ้นข้างใน
        """
        for bad in ["คีย์ภาษาไทย", "🔑", "<key จาก API_KEYS>"]:
            with pytest.raises(HTTPException) as exc:
                auth.verify_api_key(bad)
            assert exc.value.status_code == 401, f"ควรเป็น 401 ไม่ใช่ {exc.value.status_code}"

    def test_ตอบ_401_พร้อมบอกวิธีส่ง_key(self, with_keys):
        with pytest.raises(HTTPException) as exc:
            auth.verify_api_key(None)
        assert "WWW-Authenticate" in exc.value.headers

    def test_key_ที่สร้างมีความยาวพอ(self):
        key = auth.generate_key()
        assert len(key) >= 32
        assert auth.generate_key() != key, "แต่ละครั้งต้องได้ค่าไม่ซ้ำ"


class TestRateLimit:
    def test_ผ่านเมื่อยังไม่เกินโควตา(self):
        limiter = RateLimiter(max_requests=3, window_seconds=60)
        for _ in range(3):
            limiter.check("client-a")

    def test_ตอบ_429_เมื่อเกินโควตา(self):
        limiter = RateLimiter(max_requests=2, window_seconds=60)
        limiter.check("client-a")
        limiter.check("client-a")

        with pytest.raises(HTTPException) as exc:
            limiter.check("client-a")
        assert exc.value.status_code == 429
        assert "Retry-After" in exc.value.headers

    def test_นับแยกกันคนละ_client(self):
        limiter = RateLimiter(max_requests=1, window_seconds=60)
        limiter.check("client-a")
        limiter.check("client-b")  # ต้องไม่กระทบกัน

    def test_ปล่อยผ่านเมื่อพ้นหน้าต่างเวลา(self):
        """sliding window ต้องลืมรายการเก่าเมื่อพ้นช่วงเวลา"""
        limiter = RateLimiter(max_requests=1, window_seconds=1)
        limiter.check("client-a")

        with pytest.raises(HTTPException):
            limiter.check("client-a")

        time.sleep(1.1)
        limiter.check("client-a")  # ควรผ่านแล้ว


class TestClientId:
    class _Req:
        def __init__(self, host):
            self.client = type("c", (), {"host": host})()

    def test_ใช้_key_เมื่อมี(self):
        cid = client_id(self._Req("1.2.3.4"), "secret-key-value-123")
        assert cid.startswith("key:")
        assert "1.2.3.4" not in cid

    def test_ไม่เก็บ_key_เต็มใน_id(self):
        """
        id ถูกเก็บใน memory และอาจโผล่ใน log จึงเก็บแค่บางส่วน
        """
        full = "secret-key-value-abcdefghijklmnop"
        cid = client_id(self._Req("1.2.3.4"), full)
        assert full not in cid

    def test_ใช้_ip_เมื่อไม่มี_key(self):
        assert client_id(self._Req("1.2.3.4"), None) == "ip:1.2.3.4"
        assert client_id(self._Req("1.2.3.4"), "anonymous") == "ip:1.2.3.4"
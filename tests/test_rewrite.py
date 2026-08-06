"""
tests/test_rewrite.py
ทดสอบการเขียนคำถามใหม่จากบริบทสนทนา

ส่วนตรวจความปลอดภัยไม่ต้องเรียก LLM จึงเร็ว
"""

import pytest

from services.query_service import _is_safe_rewrite, _rewrite_question


class TestSafetyCheck:
    def test_rejects_changed_keyword(self):
        """
        บั๊กจริง: ถาม production แต่ระบบเขียนใหม่เป็น staging
        เพราะดึงคำจากบทสนทนาเก่ามา -> ได้คำตอบผิดโดยผู้ใช้ไม่รู้ตัว
        """
        assert not _is_safe_rewrite(
            "server ใน production มีกี่เครื่อง",
            "server ใน staging มีกี่เครื่อง",
        )

    def test_rejects_fabricated_answer(self):
        """
        บั๊กจริง: system prompt ของ RAG ติดมา ทำให้ LLM ตอบคำถามแทนเขียนใหม่
        """
        assert not _is_safe_rewrite(
            "มีกี่เครื่อง",
            "server ใน production มีทั้งหมด 5 เครื่อง ได้แก่ A, B, C, D, E",
        )

    def test_rejects_new_numbers(self):
        assert not _is_safe_rewrite("มีกี่เครื่อง", "มี 76 เครื่อง")

    def test_accepts_valid_context_fill(self):
        assert _is_safe_rewrite("แล้วใน staging ล่ะ", "server ใน staging มีกี่เครื่อง")

    def test_accepts_when_keywords_kept(self):
        assert _is_safe_rewrite("แล้ว production ล่ะ", "server ใน production มีกี่เครื่อง")


class TestRewriteDecision:
    HISTORY = [
        {"role": "user", "content": "server ใน production มีกี่เครื่อง"},
        {"role": "assistant", "content": "76 เครื่อง"},
    ]

    @pytest.mark.parametrize(
        "question",
        [
            "server ที่อยู่ใน production มีกี่เครื่องและมีเครื่องอะไรบ้าง",  # ยาว
            "ทีมไหนดูแล server มากที่สุด",  # ไม่มีคำอ้างอิง
            "ทำพะแนงไก่ยังไง",  # คนละเรื่อง
        ],
    )
    def test_skips_when_question_is_complete(self, question):
        assert _rewrite_question(question, self.HISTORY) == question

    def test_skips_when_no_history(self):
        assert _rewrite_question("แล้วใน staging ล่ะ", []) == "แล้วใน staging ล่ะ"

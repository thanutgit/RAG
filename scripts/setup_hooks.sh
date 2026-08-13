#!/usr/bin/env bash
#
# scripts/setup_hooks.sh
# ติดตั้ง git hook ที่ตรวจ lint และ format ก่อน commit
#
# ทำไมต้องมี: CI ตรวจ ruff อยู่แล้ว แต่กว่าจะรู้ว่าแดงต้องรอ push แล้วรอ CI อีก 3 นาที
# hook ตรวจให้ในเครื่องภายในวินาทีเดียว แก้แล้ว commit ใหม่ได้ทันที
#
# รันครั้งเดียวหลัง clone: bash scripts/setup_hooks.sh

set -e

HOOK=".git/hooks/pre-commit"

cat > "$HOOK" << 'HOOK_EOF'
#!/usr/bin/env bash
# ตรวจโค้ดก่อน commit — ข้ามได้ด้วย git commit --no-verify ถ้าจำเป็นจริง ๆ

if ! command -v ruff >/dev/null 2>&1; then
    echo "ไม่พบ ruff — ข้ามการตรวจ (ติดตั้งด้วย pip install ruff)"
    exit 0
fi

echo "ตรวจ format..."
if ! ruff format --check . >/dev/null 2>&1; then
    echo ""
    echo "❌ โค้ดยังไม่ได้จัดรูปแบบ"
    echo "   แก้ด้วย: ruff format . && git add -u"
    echo ""
    ruff format --check . 2>&1 | tail -20
    exit 1
fi

echo "ตรวจ lint..."
if ! ruff check . >/dev/null 2>&1; then
    echo ""
    echo "❌ พบปัญหาจาก lint"
    echo "   แก้อัตโนมัติ: ruff check --fix . && git add -u"
    echo ""
    ruff check . --output-format=concise 2>&1 | head -20
    exit 1
fi

echo "ผ่าน"
HOOK_EOF

chmod +x "$HOOK"
echo "ติดตั้ง pre-commit hook แล้วที่ $HOOK"
echo "ทดสอบ: git commit จะตรวจ ruff ให้อัตโนมัติ"
echo "ข้ามชั่วคราว: git commit --no-verify"

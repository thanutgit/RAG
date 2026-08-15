#!/usr/bin/env bash
#
# scripts/setup_hooks.sh
# ติดตั้ง git hook ที่จัดรูปแบบและตรวจโค้ดก่อน commit
#
# ทำไมทำที่เครื่องไม่ใช่ที่ CI:
#   CI ควรตรวจ ไม่ควรแก้ — ถ้า CI แก้แล้ว commit กลับ โค้ดในเครื่องกับบน repo
#   จะไม่ตรงกัน ต้อง pull ทุกครั้ง และ commit จาก bot ทำให้อ่าน history ยาก
#   hook ที่เครื่องแก้ให้ทันทีก่อน commit จึงตรงจุดกว่า
#
# รันครั้งเดียวหลัง clone: bash scripts/setup_hooks.sh

set -e

HOOK=".git/hooks/pre-commit"

cat > "$HOOK" << 'HOOK_EOF'
#!/usr/bin/env bash
# จัดรูปแบบโค้ดอัตโนมัติ แล้วตรวจ lint ก่อน commit
# ข้ามได้ด้วย: git commit --no-verify

# หา ruff ให้เจอแม้ยังไม่ได้ activate venv
# เพราะ git commit มักรันในเทอร์มินัลที่ยังไม่ได้ activate
RUFF=""
for candidate in \
    "$(git rev-parse --show-toplevel)/.venv/bin/ruff" \
    "$(git rev-parse --show-toplevel)/venv/bin/ruff" \
    "$(command -v ruff 2>/dev/null)"
do
    if [ -x "$candidate" ]; then
        RUFF="$candidate"
        break
    fi
done

if [ -z "$RUFF" ]; then
    echo "ไม่พบ ruff — ข้ามการตรวจ"
    echo "ติดตั้งด้วย: pip install ruff"
    exit 0
fi

# ทำเฉพาะไฟล์ .py ที่ stage ไว้ ไม่ไปยุ่งกับไฟล์อื่นที่ยังแก้ค้างอยู่
FILES=$(git diff --cached --name-only --diff-filter=ACM | grep -E '\.py$' || true)
[ -z "$FILES" ] && exit 0

echo "จัดรูปแบบโค้ด..."
echo "$FILES" | xargs "$RUFF" format -q

echo "แก้ lint ที่แก้อัตโนมัติได้..."
echo "$FILES" | xargs "$RUFF" check --fix -q || true

# เพิ่มไฟล์ที่เพิ่งถูกแก้กลับเข้า stage ไม่งั้นจะ commit ของเก่าไป
echo "$FILES" | xargs git add

# ตรวจรอบสุดท้าย — ที่เหลือคือปัญหาที่ต้องแก้เอง
if ! echo "$FILES" | xargs "$RUFF" check -q 2>/dev/null; then
    echo ""
    echo "❌ ยังมีปัญหาที่แก้อัตโนมัติไม่ได้:"
    echo ""
    echo "$FILES" | xargs "$RUFF" check --output-format=concise
    echo ""
    echo "แก้แล้ว commit ใหม่ หรือข้ามด้วย git commit --no-verify"
    exit 1
fi

echo "ผ่าน"
HOOK_EOF

chmod +x "$HOOK"

cat << 'MSG'
ติดตั้ง pre-commit hook เรียบร้อย

ทุกครั้งที่ git commit จะ:
  1. จัดรูปแบบไฟล์ .py ที่ stage ไว้ให้อัตโนมัติ
  2. แก้ lint ที่แก้ได้เอง
  3. เพิ่มไฟล์ที่แก้แล้วกลับเข้า commit
  4. หยุดถ้ายังมีปัญหาที่ต้องแก้เอง

ข้ามชั่วคราว: git commit --no-verify
MSG
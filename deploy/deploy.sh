#!/usr/bin/env bash
#
# deploy/deploy.sh
# ดึง image ใหม่ -> เปลี่ยนไปใช้ -> ตรวจสุขภาพ -> ถ้าพังให้ย้อนกลับ version เดิม
#
# เรียกจาก GitHub Actions หรือรันเองก็ได้:
#   DEPLOY_DIR=~/deploy/obsidian-rag IMAGE=ghcr.io/user/repo IMAGE_TAG=sha-abc bash deploy/deploy.sh
#
# แบ่งหน้าที่ของสองโฟลเดอร์:
#   - โฟลเดอร์ที่รันสคริปต์ (checkout จาก git) = compose file, schema, โค้ด
#   - DEPLOY_DIR                              = .env และ .deployed_tag
#     คือของที่ไม่ควรอยู่ใน git และต้องอยู่รอดข้ามการ deploy แต่ละครั้ง
#
# แยกกันเพราะ runner ทำ checkout ทับโฟลเดอร์งานทุกครั้ง ถ้าเก็บ .env ไว้ที่นั่นจะหาย

set -Eeuo pipefail      # หยุดทันทีที่มี error, ตัวแปรที่ไม่ได้ตั้งถือเป็น error

: "${DEPLOY_DIR:?ต้องระบุ DEPLOY_DIR}"
: "${IMAGE:?ต้องระบุ IMAGE}"
: "${IMAGE_TAG:?ต้องระบุ IMAGE_TAG}"

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
COMPOSE_FILE="$REPO_DIR/docker-compose.prod.yml"
ENV_FILE="$DEPLOY_DIR/.env"
HEALTH_URL="${HEALTH_URL:-http://localhost:8001/health}"
HEALTH_RETRIES=24        # 24 ครั้ง x 5 วินาที = รอสูงสุด 2 นาที
HEALTH_INTERVAL=5

log()  { echo "[$(date '+%H:%M:%S')] $*"; }
fail() { echo "::error::$*" >&2; exit 1; }

[ -f "$COMPOSE_FILE" ] || fail "ไม่พบ $COMPOSE_FILE"
[ -f "$ENV_FILE" ]     || fail "ไม่พบ $ENV_FILE — สร้างจาก .env.example ก่อน"

# รันจาก REPO_DIR เพื่อให้ path ใน compose (เช่น ./db/init) ชี้ถูก
cd "$REPO_DIR"

# .deployed_tag เก็บใน DEPLOY_DIR เพราะต้องอยู่รอดข้าม checkout
TAG_FILE="$DEPLOY_DIR/.deployed_tag"

# ---------------------------------------------------------------- 1. จำ version เดิม
# ต้องรู้ว่ากำลังรันอะไรอยู่ ก่อนจะเปลี่ยน ไม่งั้น rollback ไม่ได้
PREVIOUS_TAG=""
if [ -f "$TAG_FILE" ]; then
    PREVIOUS_TAG=$(cat "$TAG_FILE")
    log "version ปัจจุบัน: $PREVIOUS_TAG"
else
    log "ยังไม่เคย deploy มาก่อน"
fi

# ---------------------------------------------------------------- 2. ดึง image ใหม่
log "ดึง image: $IMAGE:$IMAGE_TAG"
docker pull "$IMAGE:$IMAGE_TAG" || fail "ดึง image ไม่สำเร็จ"

# ---------------------------------------------------------------- 3. ตรวจสุขภาพ
wait_healthy() {
    local i
    for ((i = 1; i <= HEALTH_RETRIES; i++)); do
        if curl -fsS --max-time 4 "$HEALTH_URL" >/dev/null 2>&1; then
            log "health check ผ่าน (ครั้งที่ $i)"
            return 0
        fi
        sleep "$HEALTH_INTERVAL"
    done
    return 1
}

# ---------------------------------------------------------------- 4. เปลี่ยนไปใช้ version ใหม่
start_with() {
    local tag="$1"
    APP_IMAGE="$IMAGE:$tag" \
        docker compose --env-file "$ENV_FILE" -f "$COMPOSE_FILE" up -d --no-build
}

log "เปลี่ยนไปใช้ $IMAGE_TAG"
start_with "$IMAGE_TAG"

if wait_healthy; then
    echo "$IMAGE_TAG" > "$TAG_FILE"
    log "deploy สำเร็จ"

    # ลบ image เก่าที่ไม่ได้ใช้ กันดิสก์เต็ม แต่เก็บ 3 version ล่าสุดไว้เผื่อ rollback
    docker image ls "$IMAGE" --format '{{.Tag}}' \
        | grep -v latest | tail -n +4 \
        | xargs -r -I{} docker rmi "$IMAGE:{}" 2>/dev/null || true
    exit 0
fi

# ---------------------------------------------------------------- 5. rollback
log "health check ไม่ผ่าน กำลังย้อนกลับ"
docker compose --env-file "$ENV_FILE" -f "$COMPOSE_FILE" logs api --tail 40 || true

if [ -z "$PREVIOUS_TAG" ]; then
    docker compose --env-file "$ENV_FILE" -f "$COMPOSE_FILE" down || true
    fail "deploy ครั้งแรกล้มเหลว และไม่มี version เดิมให้ย้อนกลับ"
fi

log "ย้อนกลับไป $PREVIOUS_TAG"
start_with "$PREVIOUS_TAG"

if wait_healthy; then
    fail "deploy ล้มเหลว — ย้อนกลับไป $PREVIOUS_TAG สำเร็จ ระบบยังใช้งานได้"
fi

fail "deploy ล้มเหลว และย้อนกลับไม่สำเร็จด้วย — ต้องเข้าไปแก้ที่เครื่องเอง"
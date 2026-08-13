# Deploy

CD ใช้ self-hosted runner ที่รันบนเครื่องเดียวกับที่พัฒนา
ระบบต้องใช้ GPU สำหรับ Ollama ซึ่ง cloud runner ไม่มี และ VPS ที่มี GPU
ราคาไม่คุ้มกับโปรเจกต์ขนาดนี้

ขั้นตอนใน pipeline เหมือนกับ deploy ขึ้น cloud ทุกอย่าง — ต่างแค่เครื่องปลายทาง

---

## ติดตั้งครั้งแรก

### 1. เตรียมโฟลเดอร์เก็บ config

`DEPLOY_DIR` เก็บเฉพาะสิ่งที่ **ไม่ควรอยู่ใน git และต้องอยู่รอดข้าม deploy แต่ละครั้ง**:

| ไฟล์ | ทำไมต้องอยู่นอก git |
|:---|:---|
| `.env` | มีรหัสผ่านและ API key |
| `.deployed_tag` | บันทึกว่ากำลังรัน version ไหน ใช้ตอน rollback |

ส่วน compose file, schema, และโค้ด ใช้จากที่ runner checkout มา — ไม่ต้อง copy

**เหตุผลที่ต้องแยก:** runner ทำ `actions/checkout` ทับโฟลเดอร์งานทุกครั้งที่ deploy
ถ้าเก็บ `.env` ไว้ที่นั่นจะถูกลบทิ้ง

```bash
mkdir -p ~/deploy/obsidian-rag
cp ~/projects/obsidian-rag/.env.example ~/deploy/obsidian-rag/.env
nano ~/deploy/obsidian-rag/.env
```

แก้ `.env` — **ห้ามใช้ค่าเดียวกับตอน dev**

```bash
POSTGRES_PASSWORD=<รหัสใหม่>
QDRANT_API_KEY=<key ใหม่>
API_KEYS=<key ใหม่>
API_PORT=8001
OBSIDIAN_VAULT_PATH=/mnt/c/.../Rag
OLLAMA_BASE_URL=http://host.docker.internal:11434
```

### 2. ติดตั้ง runner

GitHub → repo → Settings → Actions → Runners → New self-hosted runner → Linux

ทำตามคำสั่งที่หน้านั้นให้ แล้วติดตั้งเป็น service เพื่อให้รันอัตโนมัติ:

```bash
sudo ./svc.sh install
sudo ./svc.sh start
sudo ./svc.sh status
```

### 3. ตั้ง secret และ environment

**Settings → Secrets and variables → Actions → New repository secret**

| ชื่อ | ค่า |
|:---|:---|
| `DEPLOY_DIR` | `/home/thanutsu/deploy/obsidian-rag` |

**Settings → Environments → New environment → `production`**

ติ๊ก **Required reviewers** แล้วใส่ตัวเอง — ทุก deploy จะต้องกดอนุมัติก่อน
เป็นชั้นป้องกันสุดท้ายสำหรับ repo สาธารณะ

### 4. ทดสอบสคริปต์ก่อนให้ CD รัน

```bash
cd ~/projects/obsidian-rag
DEPLOY_DIR=~/deploy/obsidian-rag \
IMAGE=ghcr.io/<user>/<repo> \
IMAGE_TAG=latest \
bash deploy/deploy.sh
```

สคริปต์หา compose file จากโฟลเดอร์ที่มันอยู่ (`../docker-compose.prod.yml`)
และอ่าน `.env` จาก `DEPLOY_DIR` — ไม่ต้องอยู่โฟลเดอร์เดียวกัน

---

## ระบบทำงานยังไง

```
git push main
    │
    ▼
CI: test → lint → security → build image → push ghcr.io
    │
    ▼ (เฉพาะเมื่อ CI ผ่านทั้งหมด)
CD: รอ approve → runner บนเครื่อง
    │
    ├─ จำ tag ปัจจุบันไว้ใน .deployed_tag
    ├─ docker pull image ใหม่
    ├─ docker compose up -d --no-build
    ├─ รอ /health ผ่าน (สูงสุด 2 นาที)
    │
    ├─ ผ่าน   → บันทึก tag ใหม่ + ลบ image เก่าที่เกิน 3 version
    └─ ไม่ผ่าน → แสดง log + ย้อนกลับ tag เดิม + แจ้งว่า deploy ล้มเหลว
```

---

## เลข version

image เดียวกันติดหลาย tag แต่ละอันมีหน้าที่ต่างกัน:

| tag | ตัวอย่าง | ใช้ทำอะไร |
|:---|:---|:---|
| version | `v2026.08.13-2` | คนอ่านรู้ว่า deploy เมื่อไหร่ รอบที่เท่าไรของวันนั้น |
| sha | `sha-a1b2c3d4...` | ระบุ commit ได้แน่นอน ใช้ตรวจว่ารันโค้ดตัวไหน |
| latest | `latest` | ชี้ตัวล่าสุดเสมอ |

เลขลำดับท้าย version นับจาก tag ที่มีอยู่ใน registry ไม่ได้เก็บ counter ไว้ที่ไหน
เพราะ workflow แต่ละครั้งเป็นคนละ process จำอะไรข้ามกันไม่ได้

**ถ้าถาม registry ไม่สำเร็จ CI จะหยุดทันที** ไม่เดาว่าเริ่มที่ 1
เพราะการเดาทำให้ tag ซ้ำแล้วชี้ทับ image เก่า ซึ่ง rollback ด้วย version
จะได้ของผิดตัวโดยไม่มีใครรู้

ข้อความ error จะบอกสาเหตุที่แท้จริง:

| ข้อความ | หมายความว่า | ทำยังไง |
|:---|:---|:---|
| ต่อ ghcr.io ไม่ได้ (curl exit 6/7) | เน็ตมีปัญหาหรือ DNS ล้มเหลว | รอแล้ว re-run |
| ไม่ตอบภายใน 20 วินาที | registry ช้าหรือล่ม | เช็ค githubstatus.com |
| ปฏิเสธการยืนยันตัวตน (401) | token หมดอายุหรือไม่มีสิทธิ์ | ตรวจ permissions ใน workflow |
| ไม่อนุญาต (403) | workflow ขาด `packages: write` | เพิ่มใน `permissions:` |
| ปัญหาฝั่ง server (5xx) | ghcr.io ล่ม | รอแล้ว re-run |
| ยังไม่มี image ใน registry (404) | push ครั้งแรก | ไม่ใช่ error เริ่มนับที่ 1 |

กด **Re-run jobs** ใน Actions ได้เลยถ้าเป็นปัญหาชั่วคราว

ดู version ที่มีทั้งหมด:
```bash
docker image ls ghcr.io/<user>/<repo>
```

ดูว่าตอนนี้รัน version ไหน:
```bash
cat ~/deploy/obsidian-rag/.deployed_tag
```

---

## Rollback ด้วยมือ

Actions → CD → Run workflow → ใส่ `image_tag`

ใส่ได้ทั้งสองแบบ:
- `v2026.08.12-3` — อ่านง่าย เลือกจากวันที่
- `sha-a1b2c3...` — แน่นอนที่สุด ถ้ารู้ commit ที่ต้องการ

หรือบนเครื่องโดยตรง:
```bash
cd ~/projects/obsidian-rag
APP_IMAGE=ghcr.io/<user>/<repo>:sha-<commit เก่า> \
  docker compose --env-file ~/deploy/obsidian-rag/.env \
                 -f docker-compose.prod.yml up -d --no-build
```

ดู tag ที่มี:
```bash
docker image ls ghcr.io/<user>/<repo>
```

---

## dev กับ prod แยกกันทุกอย่าง

| | dev | prod |
|:---|:---|:---|
| พอร์ต API | 8000 | 8001 |
| container | `obsidian-rag-*` | `obsidian-rag-prod-*` |
| volume | `obsidian_rag_*_data` | `obsidian_rag_prod_*_data` |
| compose project | `obsidian-rag` | `obsidian-rag-prod` |
| โค้ด | ไฟล์ที่กำลังแก้ | image จาก commit ที่ push แล้ว |
| อัปเดตเมื่อ | เซฟไฟล์ | push ขึ้น main |

**ต้องแยกทั้งหมด** ไม่ใช่แค่พอร์ต เพราะ:
- ชื่อ container ซ้ำ → Docker ปฏิเสธสร้างตัวใหม่
- volume ซ้ำ → prod เขียนทับข้อมูลที่ใช้พัฒนาอยู่

ระบุ project name ด้วย `-p` เสมอ ไม่งั้น compose เดาจากชื่อโฟลเดอร์
ซึ่ง runner ทำ checkout ไว้คนละที่กับที่คุณพัฒนา — compose จะมองเป็นคนละ project
แล้วพยายามสร้างของใหม่ทับ

รันพร้อมกันได้ ทดสอบเทียบได้ว่าโค้ดที่แก้อยู่กับที่ deploy แล้วต่างกันตรงไหน

---

## ข้อจำกัดที่ยอมรับ

- **ต้องเปิด WSL ไว้** ถ้าปิด job จะค้างรอจนกว่าจะเปิด
- **ไม่มี URL สาธารณะ** เข้าถึงได้เฉพาะในเครื่อง
- **ยังไม่มี HTTPS** API key ส่งแบบไม่เข้ารหัส ห้ามเปิดออกอินเทอร์เน็ต
- **Ollama อยู่นอก container** เพราะต้องใช้ GPU โดยตรง

ถ้าย้ายไป cloud ต้องแก้ `DEPLOY_DIR` กับ `OLLAMA_BASE_URL` และเพิ่ม reverse proxy
โครงสร้าง pipeline ไม่ต้องเปลี่ยน
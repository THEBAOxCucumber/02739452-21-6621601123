# 🌏 Global Disaster Intelligence Dashboard
### แดชบอร์ดติดตามภัยธรรมชาติทั่วโลก

ระบบรวบรวมและวิเคราะห์เหตุการณ์ภัยธรรมชาติทั่วโลก ได้แก่ **แผ่นดินไหว พายุ ไฟป่า น้ำท่วม** และภัยอื่น ๆ
จากหลายแหล่งข้อมูล นำมาแปลงให้อยู่ในรูปแบบเดียวกัน ตรวจสอบคุณภาพ ตัดรายการซ้ำ แล้วเก็บลงฐานข้อมูล
เพื่อแสดงผลบนเว็บแดชบอร์ดภาษาไทยที่อ่านข้อมูลจากฐานข้อมูลโดยตรง

---

## 1. หัวข้อและเป้าหมายของโครงการ

| หัวข้อ | รายละเอียด |
|---|---|
| หมวด | ภัยธรรมชาติ (Natural Disasters) |
| ปัญหาที่แก้ | ข้อมูลภัยพิบัติกระจายอยู่หลายหน่วยงาน รูปแบบไม่เหมือนกัน และมีเหตุการณ์เดียวกันซ้ำข้ามแหล่ง |
| สิ่งที่ระบบทำ | ดึงข้อมูลอัตโนมัติทุกวัน → ตรวจสอบ → แปลงเป็นรูปแบบกลาง → ตัดซ้ำ → เก็บใน PostgreSQL → แสดงผลบนแดชบอร์ด |
| ผลลัพธ์ปัจจุบัน | เหตุการณ์ไม่ซ้ำ **~2,950 รายการ** จาก 5 แหล่ง (เกณฑ์ขั้นต่ำ 100 รายการ) |

### เทคโนโลยีที่ใช้

| ส่วน | เครื่องมือ |
|---|---|
| ดึงข้อมูล / Web Scraping | Python, `requests`, `BeautifulSoup` (ไม่ใช้ Selenium) |
| ควบคุม ETL | **Apache Airflow 2.10** (TaskGroup, ทำงานขนาน, retry, timeout) |
| ฐานข้อมูล | **PostgreSQL 16** |
| แดชบอร์ด | **Streamlit** + Altair (กราฟ) + pydeck (แผนที่) |
| สภาพแวดล้อม | Docker Compose |

### สถาปัตยกรรม

```text
 USGS API ───────────┐
 NASA EONET API ─────┤
 GDACS API ──────────┤        Airflow DAG: global_disaster_etl
 GeoNet API ─────────┼──>  (1 TaskGroup ต่อแหล่ง ทำงานขนานกัน)
 ReliefWeb API ──────┤      extract → transform_validate → load (UPSERT)
 PHIVOLCS (HTML) ────┘                   │
                                         ├── ข้อมูลไม่ผ่านการตรวจ → ตาราง data_quarantine (พร้อมเหตุผล)
                                         ▼
               ตัดซ้ำข้ามแหล่ง → ตรวจคุณภาพข้อมูล → บันทึกสถานะ pipeline
                                         ▼
                                    PostgreSQL ──> แดชบอร์ด Streamlit (ภาษาไทย)
```

แหล่งข้อมูลหนึ่งล่มหรือถูกข้าม แหล่งอื่นยังทำงานต่อได้ตามปกติ

---

## 2. แหล่งข้อมูล

| # | แหล่งข้อมูล | หน่วยงาน | วิธีดึง | ข้อมูลที่ได้ | สถานะ |
|---|---|---|---|---|---|
| 1 | [USGS Earthquake API](https://earthquake.usgs.gov/fdsnws/event/1/) | สำนักสำรวจธรณีวิทยาสหรัฐฯ | REST API (GeoJSON) | แผ่นดินไหวทั่วโลก M4.5+ ล่าสุด 1,000 รายการ | ✅ ใช้งาน |
| 2 | [NASA EONET](https://eonet.gsfc.nasa.gov/docs/v3) | NASA | REST API (JSON) | ไฟป่า พายุ น้ำท่วม จากการสังเกตการณ์ดาวเทียม | ✅ ใช้งาน |
| 3 | [GDACS](https://www.gdacs.org/gdacsapi/swagger/index.html) | EC JRC / UN OCHA | REST API (GeoJSON) | แผ่นดินไหว พายุหมุน น้ำท่วม ภูเขาไฟ ภัยแล้ง ไฟป่า พร้อมระดับเตือนภัย | ✅ ใช้งาน (ดึงได้เฉพาะ 11:00–13:45 น.) |
| 4 | [GeoNet](https://api.geonet.org.nz/) | GNS Science นิวซีแลนด์ | REST API (GeoJSON) | แผ่นดินไหวนิวซีแลนด์ ~100 รายการล่าสุด | ✅ ใช้งาน |
| 5 | [PHIVOLCS](https://earthquake.phivolcs.dost.gov.ph/) | สถาบันภูเขาไฟและแผ่นดินไหวฟิลิปปินส์ | **Web Scraping** (HTML) | แผ่นดินไหวฟิลิปปินส์ทั้งเดือน (~1,300 รายการ) | ✅ ใช้งาน |
| 6 | [ReliefWeb API](https://apidoc.reliefweb.int/) | UN OCHA | REST API (JSON) | ภัยพิบัติระดับประเทศ | ⏭️ รอ appname ที่ได้รับอนุมัติ |

### การปฏิบัติตามเงื่อนไขของแหล่งข้อมูล

- **Web Scraping (PHIVOLCS)** — ใช้ `requests` + `BeautifulSoup` เท่านั้น ตรวจ `robots.txt` ทุกครั้งก่อนดึง
  (เว็บไม่มี robots.txt จึงไม่มีข้อจำกัดตามมาตรฐาน RFC 9309) ดึงเพียง **วันละ 1 request** เพราะข้อมูลทั้งเดือนอยู่ในหน้าเดียว
- **GDACS** — robots.txt กำหนดให้เข้าได้ **1 ครั้งต่อ 60 วินาที** และเฉพาะ **04:00–06:45 UTC (11:00–13:45 น. เวลาไทย)**
  ระบบจึงเว้นระยะ 60 วินาทีต่อ request และตั้งเวลารันอัตโนมัติ 11:30 น. ถ้ากดรันนอกช่วงเวลานี้ GDACS จะ **ข้ามอัตโนมัติ** โดยไม่ทำให้ระบบล้มเหลว
- **ReliefWeb** — API ต้องใช้ appname ที่ได้รับอนุมัติ ระหว่างรอ ระบบจะข้ามแหล่งนี้
- **PDPA** — เก็บเฉพาะข้อมูลระดับเหตุการณ์ (เวลา พิกัด ขนาด ตำแหน่ง) ไม่มีข้อมูลส่วนบุคคล
- ทุกรายการมี **ลิงก์ต้นทาง (`source_url`)** และ **เวลาที่ดึงข้อมูล (`fetched_at`)** ไม่มีการสร้างข้อมูลขึ้นเอง

รายละเอียดเชิงลึก (พารามิเตอร์ ข้อจำกัด ผลตรวจ robots.txt กติกาตัดซ้ำ) อยู่ที่ [docs/data_sources.md](docs/data_sources.md)

### การตรวจสอบและตัดข้อมูลซ้ำ

| ขั้นตอน | วิธีการ |
|---|---|
| ตรวจสอบความถูกต้อง | ต้องมีรหัสเหตุการณ์ เวลา (แปลงเป็น UTC) และพิกัด (ละติจูด −90..90, ลองจิจูด −180..180) — ไม่ผ่านจะถูกแยกไว้ในตาราง `data_quarantine` พร้อมเหตุผล |
| ป้องกันซ้ำเมื่อรันหลายรอบ | `INSERT ... ON CONFLICT DO UPDATE` (UPSERT) บน `(source_name, source_event_id)` — รันซ้ำกี่ครั้งก็ไม่เพิ่มรายการเดิม |
| ตัดซ้ำข้ามแหล่ง | EONET ที่อ้างอิงรายงาน GDACS · แผ่นดินไหวจาก GDACS/PHIVOLCS/GeoNet ที่เวลาต่างจาก USGS ≤ 2 นาที และห่างกัน ≤ 100 กม. → นับเป็นเหตุการณ์เดียว |
| ตรวจคุณภาพหลังโหลด | 6 รายการ เช่น มีเหตุการณ์ไม่ซ้ำ ≥ 100, พิกัดถูกต้อง, ไม่มีวันที่ในอนาคต, มีข้อมูล ≥ 3 แหล่ง |

---

## 3. วิธีติดตั้งและรัน

### สิ่งที่ต้องมี
- **Docker Desktop** (เปิดไว้ก่อนเริ่ม)
- พอร์ตว่าง: `8080` (Airflow), `8501` (แดชบอร์ด), `5432` (PostgreSQL)

### ขั้นตอน (Windows PowerShell)

**1) เข้าโฟลเดอร์โปรเจกต์และสร้างไฟล์ตั้งค่า**

```powershell
git clone https://github.com/THEBAOxCucumber/02739452-21-6621601123.git
cd 02739452-21-6621601123
Copy-Item .env.example .env
notepad .env
```

แก้ค่า `change_me` ทั้งหมดใน `.env` (รหัสผ่านฐานข้อมูล, รหัสผ่าน Airflow, `AIRFLOW_SECRET_KEY`)
> ⚠️ ห้าม commit ไฟล์ `.env` ขึ้น Git (อยู่ใน `.gitignore` แล้ว)

**2) เริ่มระบบ**

```powershell
docker compose up -d --build
docker compose ps
```

รอประมาณ 1–2 นาที ต้องเห็น `airflow-init` เป็น `Exited (0)` และ service อื่นเป็น `Up`

**3) เปิดใช้งาน**

| ระบบ | URL | การเข้าใช้ |
|---|---|---|
| Airflow | http://localhost:8080 | ชื่อผู้ใช้/รหัสผ่าน = `AIRFLOW_ADMIN_USER` / `AIRFLOW_ADMIN_PASSWORD` ใน `.env` |
| แดชบอร์ด | http://localhost:8501 | ไม่ต้องล็อกอิน |

**4) รัน ETL**

- อัตโนมัติ: ทุกวันเวลา **11:30 น.** (เวลาไทย)
- รันเอง: เปิด Airflow → DAG `global_disaster_etl` → กด **▶ Trigger DAG** (ใช้เวลาประมาณ 1 นาที; ถ้าอยู่ในช่วง 11:00–13:38 น. GDACS จะดึงด้วย ใช้เวลาเพิ่มประมาณ 5 นาที)
- เมื่อเสร็จ กด **🔄 โหลดข้อมูลล่าสุด** บนแดชบอร์ด

### การใช้งานแดชบอร์ด

| ส่วน | สิ่งที่แสดง |
|---|---|
| แถบตัวกรอง (ซ้าย) | ช่วงวันที่, ประเภทภัยพิบัติ, แหล่งข้อมูล, ขนาดแผ่นดินไหวขั้นต่ำ, แสดง/ซ่อนรายการซ้ำ |
| ตัวเลขสรุป | จำนวนเหตุการณ์ทั้งหมด / แผ่นดินไหว / ไฟป่า / น้ำท่วม / พายุ |
| 📊 ภาพรวม | กราฟจำนวนเหตุการณ์รายวัน/รายเดือน, สัดส่วนตามประเภทและแหล่ง, แผ่นดินไหวรุนแรงสุด 10 อันดับ |
| 🗺️ แผนที่ | ตำแหน่งเหตุการณ์ (ชี้ที่จุดเพื่อดูรายละเอียด) |
| 📋 รายการเหตุการณ์ | ตารางค้นหาและเรียงลำดับได้ พร้อมลิงก์ต้นทาง |
| ⚙️ แหล่งข้อมูลและสถานะระบบ | สถานะการดึงข้อมูลรอบล่าสุดของแต่ละแหล่ง, ผลตรวจคุณภาพ, ประวัติการรัน |

เวลาทั้งหมดบนแดชบอร์ดแสดงเป็น **เวลาประเทศไทย** และปี พ.ศ. (ในฐานข้อมูลเก็บเป็น UTC)

### สาธิตกรณีแหล่งข้อมูลล่ม

ใน Airflow กด **Trigger DAG w/ config** แล้วใส่:

```json
{"simulate_failure": ["usgs"]}
```

ผลลัพธ์: task `usgs.extract` ล้มเหลว แต่แหล่งอื่นยังโหลดข้อมูลได้ สถานะบันทึกเป็น "สำเร็จบางส่วน" และแสดงบนแดชบอร์ด

### ตรวจข้อมูลในฐานข้อมูล

```powershell
docker compose exec postgres psql -U disaster_user -d disaster_db
```

```sql
-- จำนวนข้อมูลแยกตามแหล่ง
SELECT source_name, COUNT(*) AS rows, COUNT(*) FILTER (WHERE duplicate_of IS NULL) AS unique_events
FROM disaster_events GROUP BY 1;

-- ข้อมูลที่ไม่ผ่านการตรวจสอบ พร้อมเหตุผล
SELECT source_name, reason, COUNT(*) FROM data_quarantine GROUP BY 1, 2;

-- สถานะ pipeline และผลตรวจคุณภาพ
SELECT * FROM pipeline_runs ORDER BY finished_at DESC LIMIT 10;
SELECT * FROM data_quality_results ORDER BY checked_at DESC LIMIT 6;
```

### รัน unit test

```powershell
pip install -r requirements.txt pytest
python -m pytest -q
```

ครอบคลุม parser ทุกแหล่ง, การแปลงเวลา/timezone, robots.txt, การเว้นระยะ request ของ GDACS, ช่วงเวลาที่ GDACS อนุญาต,
การตรวจสอบข้อมูล, การกักข้อมูลที่ไม่ผ่าน และข้อมูลซ้ำ

### ตั้งค่าเพิ่มเติม (ไฟล์ `.env`)

| ตัวแปร | ความหมาย | ค่าเริ่มต้น |
|---|---|---|
| `USGS_MIN_MAGNITUDE` | ขนาดแผ่นดินไหวขั้นต่ำจาก USGS | `4.5` |
| `GDACS_EVENT_TYPES` | ประเภทภัยที่ดึงจาก GDACS | `EQ;TC;FL;VO;DR;WF` |
| `RELIEFWEB_APPNAME` | appname ของ ReliefWeb (เว้นว่าง = ข้าม) | ว่าง |
| `SCRAPER_USER_AGENT` | ชื่อที่ระบบแสดงต่อเว็บต้นทาง (ใส่อีเมลติดต่อของทีม) | — |

### หยุด / รีเซ็ตระบบ

```powershell
docker compose down        # หยุด (ข้อมูลยังอยู่)
docker compose down -v     # หยุดและลบข้อมูลทั้งหมด (ใช้เมื่อแก้ schema)
```

---

## 4. โครงสร้างโปรเจกต์

```text
.
├── dags/
│   └── disaster_etl_dag.py         DAG หลัก (TaskGroup ต่อแหล่ง, retry, timeout, ทำงานต่อแม้บางแหล่งล้ม)
├── web/                            แดชบอร์ด Streamlit ภาษาไทย
│   ├── app.py
│   ├── requirements.txt            ไลบรารีของแดชบอร์ด
│   ├── Dockerfile
│   └── .streamlit/config.toml      ธีมสี
├── src/
│   ├── extractors/                 ตัวดึงข้อมูลแต่ละแหล่ง
│   │   ├── usgs_earthquake.py      USGS API
│   │   ├── nasa_eonet.py           NASA EONET API
│   │   ├── gdacs_api.py            GDACS API (เคารพ rate limit และช่วงเวลา)
│   │   ├── geonet_api.py           GeoNet API
│   │   ├── reliefweb_api.py        ReliefWeb API
│   │   └── web_scraper.py          Web Scraping PHIVOLCS + ตัวตรวจ robots.txt
│   ├── transformations/            แปลงเป็นรูปแบบกลาง (normalize) และตรวจสอบ (validate)
│   ├── database/postgres.py        UPSERT, quarantine, ตัดซ้ำข้ามแหล่ง, ตรวจคุณภาพ, สถานะ pipeline
│   ├── reference/                  ตารางพิกัดกึ่งกลางประเทศ (ODbL)
│   └── pipeline.py                 ขั้นตอน ETL ที่ DAG เรียกใช้
├── airflow/Dockerfile              image ของ Airflow (ติดตั้งไลบรารีจาก requirements.txt)
├── sql/                            สร้างฐานข้อมูลและตาราง
├── tests/                          unit test
├── docs/                           เอกสารแหล่งข้อมูลและภาพหน้าจอ
├── docker-compose.yml              รวมทุก service: postgres, airflow, web
├── requirements.txt                ไลบรารี Python ของ ETL pipeline
└── .env.example                    ตัวอย่างไฟล์ตั้งค่า (คัดลอกเป็น .env)
```

### ตารางในฐานข้อมูล

| ตาราง | หน้าที่ |
|---|---|
| `disaster_events` | เหตุการณ์ทั้งหมดในรูปแบบกลาง (แหล่ง, รหัส, ประเภท, ชื่อ, เวลา, พิกัด, ขนาด, ระดับเตือนภัย, ลิงก์, เวลาดึง) |
| `data_quarantine` | ข้อมูลที่ไม่ผ่านการตรวจสอบ พร้อมเหตุผล |
| `pipeline_runs` | สถานะการรันแต่ละแหล่งในแต่ละรอบ |
| `data_quality_results` | ผลตรวจคุณภาพข้อมูลแต่ละรอบ |

---

## 5. แก้ปัญหาที่พบบ่อย

| อาการ | วิธีแก้ |
|---|---|
| แดชบอร์ดขึ้น "เชื่อมต่อฐานข้อมูลไม่ได้" | ตรวจ `docker compose ps` ว่า `postgres` เป็น `healthy` |
| แดชบอร์ดขึ้น "ยังไม่มีข้อมูล" | Trigger DAG ใน Airflow แล้วรอให้เสร็จ |
| GDACS ขึ้น "ข้าม" | ปกติ — ดึงได้เฉพาะ 11:00–13:45 น. ตามเงื่อนไขของเว็บ |
| พอร์ต 5432 ถูกใช้แล้ว | ตั้ง `POSTGRES_HOST_PORT=5433` ใน `.env` |
| แผนที่ไม่แสดง | เบราว์เซอร์ต้องเปิด WebGL/hardware acceleration |

---

**ที่มาของข้อมูล:** USGS Earthquake Hazards Program · GDACS (EC JRC / UN OCHA) · NASA EONET ·
GeoNet (GNS Science, CC BY 4.0) · PHIVOLCS (DOST ฟิลิปปินส์) · ReliefWeb (UN OCHA) ·
พิกัดกึ่งกลางประเทศจาก mledoze/countries (ODbL)

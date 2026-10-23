# Global Disaster Intelligence Dashboard

## 1. ภาพรวมโครงการ

**ชื่อโครงการ:** Global Disaster Intelligence Dashboard  
**หมวด:** ภัยธรรมชาติ (Natural Disasters)  
**ขอบเขต:** รวบรวมและวิเคราะห์เหตุการณ์แผ่นดินไหว พายุ และไฟป่าทั่วโลก เพื่อติดตามสถานการณ์ วิเคราะห์แนวโน้มตามเวลาและพื้นที่ และแสดงข้อมูลบน Web Dashboard

**เป้าหมาย**
- รวมข้อมูลภัยธรรมชาติจากหลายแหล่งให้อยู่ใน schema เดียวกัน
- ใช้ Apache Airflow จัดการกระบวนการ ETL
- จัดเก็บข้อมูลใน PostgreSQL
- สร้าง Web Dashboard ที่อ่านข้อมูลจาก PostgreSQL โดยตรง
- มีข้อมูลรวมอย่างน้อย 100 รายการ โดยตรวจสอบข้อมูลซ้ำก่อนนับ

## 2. แหล่งข้อมูล

1. **NASA EONET API** — เหตุการณ์ธรรมชาติ เช่น ไฟป่าและพายุ  
   - API: https://eonet.gsfc.nasa.gov/api/v3/events?status=all&limit=500
   - เอกสาร: https://eonet.gsfc.nasa.gov/docs/v3

2. **GDACS API** — ข้อมูลแจ้งเตือนภัยพิบัติและระดับการแจ้งเตือน  
   - เอกสาร: https://www.gdacs.org/gdacsapi/swagger/index.html

3. **USGS Earthquake API** — ข้อมูลแผ่นดินไหว เช่น เวลาเกิด ขนาด ความลึก และพิกัด  
   - ตัวอย่าง: https://earthquake.usgs.gov/fdsnws/event/1/query?format=geojson&starttime=2026-01-01&minmagnitude=2.5
   - เอกสาร: https://earthquake.usgs.gov/fdsnws/event/1/

4. **Web Scraping (ข้อบังคับ)** — ดึงข้อมูลจากหน้า HTML สาธารณะที่อนุญาต โดยใช้ Python `requests` และ `BeautifulSoup` ห้ามใช้ Selenium  
   - หน้าเว็บสำหรับตรวจสอบเบื้องต้น: https://www.gdacs.org/
   - ตรวจสอบ `robots.txt` และข้อกำหนดการใช้งานก่อนเริ่ม scraping
   - หากหน้าเว็บไม่อนุญาตหรือข้อมูลไม่ได้อยู่ใน HTML ให้เลือกหน้า HTML อื่นที่อนุญาต ห้ามนับการเรียก API เป็น Web Scraping

> หมายเหตุ: ต้องตรวจสอบการอนุญาตเข้าถึงและโครงสร้าง HTML จริงก่อนเลือก scraper ขั้นสุดท้าย ห้ามฝ่าฝืน robots.txt หรือเก็บข้อมูลส่วนบุคคล

## 3. เทคโนโลยีที่ใช้

- **Python** — เรียก API, Web Scraping และแปลงข้อมูล
- **Apache Airflow** — จัดตารางและควบคุม ETL Pipeline
- **PostgreSQL** — ฐานข้อมูลกลาง
- **Docker Compose** — จัดการสภาพแวดล้อมสำหรับ Airflow และ PostgreSQL
- **Web Dashboard** — เลือกเครื่องมือได้ เช่น Streamlit หรือเว็บแอปที่เชื่อมต่อ PostgreSQL โดยตรง
- **requests + BeautifulSoup** — Web Scraping โดยไม่ใช้ Selenium
- **pandas** (ถ้าจำเป็น) — ทำความสะอาดและแปลงข้อมูล

## 4. สถาปัตยกรรมข้อมูล

```text
NASA EONET API ───────┐
GDACS API ────────────┤
USGS Earthquake API ──┼─> Apache Airflow DAG
HTML Web Scraper ─────┘        |
                               v
                  Extract -> Validate -> Transform
                               |
                               v
                   Deduplicate -> UPSERT
                               |
                               v
                          PostgreSQL
                               |
                               v
                       Web Dashboard
```

## 5. งานที่ต้องทำ (Checklist)

### ระยะที่ 1: เตรียมโปรเจกต์
- [x] สร้าง Git repository สำหรับโปรเจกต์
- [x] สร้างโครงสร้างโฟลเดอร์ เช่น `dags/`, `src/`, `sql/`, `dashboard/`, `tests/`, `docs/`
- [x] เตรียม `docker-compose.yml` สำหรับ Airflow และ PostgreSQL
- [x] ตั้งค่า `.env` สำหรับ credentials และ config
- [x] เพิ่ม `.env` ลง `.gitignore` และสร้าง `.env.example` ที่ไม่มีรหัสผ่านจริง

### ระยะที่ 2: ตรวจสอบแหล่งข้อมูล
- [x] ทดสอบเรียก NASA EONET API
- [x] ศึกษา GDACS API และทดสอบ endpoint ที่เหมาะสม
- [x] ทดสอบ USGS Earthquake API
- [ ] ตรวจสอบ `robots.txt` และข้อกำหนดของหน้าเว็บที่จะ scrape — robots.txt ตรวจแล้ว (docs/data_sources.md); **ผู้ใช้ต้องอ่านเงื่อนไขการใช้งานของ PHIVOLCS เอง**
- [x] ตรวจสอบ HTML ว่ามีรายการเหตุการณ์อยู่จริง — ✔ ใช้ PHIVOLCS (earthquake.phivolcs.dost.gov.ph) แทน ReliefWeb HTML
- [x] บันทึกแหล่งที่มา, เวลาเก็บข้อมูล, ข้อจำกัด และรูปแบบข้อมูลของแต่ละแหล่ง
- [x] ยืนยันว่า scraper ใช้ `requests`/`BeautifulSoup` และไม่ใช้ Selenium — ✔ ใช้ PHIVOLCS (earthquake.phivolcs.dost.gov.ph) แทน ReliefWeb HTML

### ระยะที่ 3: ออกแบบ PostgreSQL
- [x] ออกแบบตาราง `disaster_events`
- [x] กำหนด schema กลางสำหรับข้อมูลจากทุกแหล่ง
- [x] เก็บ `source_name`, `source_event_id`, `event_type`, `event_name`, `event_time`, `latitude`, `longitude`, `magnitude`, `severity`, `source_url`, `ingested_at`
- [x] กำหนด unique constraint สำหรับ `(source_name, source_event_id)`
- [x] เพิ่มตาราง `pipeline_runs` หรือ log สำหรับติดตามสถานะ DAG (ถ้าทำโบนัส)
- [x] สร้าง index สำหรับเวลา ประเภทเหตุการณ์ และพิกัดตามความเหมาะสม

### ระยะที่ 4: เขียน ETL
- [x] เขียนฟังก์ชัน Extract แยกตามแหล่งข้อมูล
- [x] แปลงผลลัพธ์เป็น schema กลางเดียวกัน
- [x] ตรวจสอบข้อมูลจำเป็น เช่น ID, เวลา และพิกัด
- [x] ตรวจสอบพิกัดให้อยู่ในช่วง latitude -90 ถึง 90 และ longitude -180 ถึง 180
- [x] จัดการวันที่และ timezone ให้เป็นมาตรฐาน
- [x] ตัดข้อมูลซ้ำโดยใช้ source และ event ID หรือกติกาจับคู่ที่เหมาะสม
- [x] แยกข้อมูลไม่ผ่าน validation ไปยังตาราง/ไฟล์ quarantine พร้อมเหตุผล
- [x] ใช้ UPSERT เพื่อให้รันซ้ำแล้วไม่เพิ่มรายการเดิม
- [x] ตรวจสอบว่าข้อมูลรวมที่ผ่าน validation มีอย่างน้อย 100 รายการ

### ระยะที่ 5: สร้าง Airflow DAG
- [x] สร้าง DAG หลักสำหรับ ETL
- [x] ใช้ TaskGroup แยกงานตามแหล่งข้อมูล
- [x] ให้แหล่งข้อมูลทำงานขนานกันได้
- [x] ตั้งค่า timeout, retry และ logging
- [x] ออกแบบให้แหล่งหนึ่งล้มเหลวแล้วแหล่งอื่นยังทำงานต่อได้
- [x] เพิ่มขั้นตอนรวมข้อมูลและโหลดลง PostgreSQL
- [x] เพิ่มขั้นตอนตรวจคุณภาพข้อมูลและบันทึกผล
- [x] ทดสอบรัน DAG ซ้ำและตรวจสอบว่า UPSERT ทำงานถูกต้อง

### ระยะที่ 6: สร้าง Web Dashboard
- [x] เชื่อมต่อ Dashboard กับ PostgreSQL โดยตรง
- [x] แสดง KPI เช่น จำนวนเหตุการณ์ทั้งหมด จำนวนเหตุการณ์ตามประเภท และจำนวนเหตุการณ์ในช่วงเวลาที่เลือก
- [x] แสดงกราฟจำนวนเหตุการณ์รายวันหรือรายเดือนอย่างน้อย 1 กราฟ
- [x] แสดงตารางเหตุการณ์พร้อมการเรียงลำดับและตัวกรอง
- [x] เพิ่มตัวกรองประเภทภัยพิบัติ ช่วงเวลา และแหล่งข้อมูล
- [x] แสดงแผนที่เมื่อมีพิกัดที่ผ่านการตรวจสอบ
- [x] แสดงสถานะ Pipeline ล่าสุดเพื่อเก็บคะแนนโบนัส

### ระยะที่ 7: ทดสอบและจัดทำเอกสาร
- [x] ทดสอบข้อมูลจากทุกแหล่ง
- [x] ทดสอบกรณี API timeout, rate limit หรือแหล่งข้อมูลล่ม
- [x] ทดสอบข้อมูลซ้ำและข้อมูลไม่ครบ
- [x] ทดสอบว่า Dashboard อ่านจาก PostgreSQL โดยตรง
- [x] ตรวจสอบว่าไม่มีข้อมูลส่วนบุคคล
- [ ] ตรวจสอบการปฏิบัติตาม robots.txt และข้อกำหนดเว็บไซต์ — robots.txt ✔ (scraper ตรวจอัตโนมัติ); **เงื่อนไขของ PHIVOLCS/GDACS/ReliefWeb ผู้ใช้ต้องยืนยัน**
- [x] เขียน `README.md` พร้อมวิธีติดตั้งและรัน
- [ ] บันทึกภาพหน้าจอ DAG, ตารางฐานข้อมูล และ Dashboard — **ผู้ใช้ทำเอง**
- [ ] เตรียมสาธิตการรัน ETL และการแสดงผล — **ผู้ใช้ทำเอง**

## 6. เกณฑ์ประเมินที่ต้องครอบคลุม

### ระดับ 1 — ขั้นต่ำ
- [x] ดึงข้อมูลอย่างน้อย 1 แหล่ง
- [x] มี DAG ทำ Extract → Transform → Load
- [x] โหลดข้อมูลลง PostgreSQL
- [x] มีหน้าเว็บแสดงตารางและกราฟอย่างน้อย 1 กราฟ

### ระดับ 2 — มาตรฐาน
- [x] ดึงข้อมูลอย่างน้อย 2 แหล่งแบบขนาน
- [x] ใช้ TaskGroup
- [x] รวมข้อมูลเป็น schema เดียวกัน
- [x] ใช้ UPSERT ป้องกันข้อมูลซ้ำ
- [x] Dashboard มี KPI และตัวกรอง

### ระดับ 3 — ท้าทาย
- [x] ดึงข้อมูล 3 แหล่ง
- [x] เมื่อแหล่งหนึ่งล้มเหลว แหล่งอื่นยังทำงานต่อได้
- [x] ตัดรายการซ้ำข้ามแหล่งตามกติกาที่กำหนด
- [x] ตรวจคุณภาพข้อมูล
- [x] แยกเส้นทางข้อมูลไม่ผ่าน validation พร้อมบันทึกเหตุผล

### โบนัส
- [x] หน้า Dashboard แสดงสถานะ Pipeline
- [ ] พิจารณาใช้ Dynamic Task Mapping หากเหมาะสม — พิจารณาแล้ว: ไม่ใช้ เพราะ GDACS/ReliefWeb ต้องดึงทีละหน้าตาม rate limit จึงไม่เหมาะกับการ map แบบขนาน

## 7. ข้อกำหนดที่ห้ามลืม

- ต้องมี Web Scraping อย่างน้อย 1 แหล่ง และห้ามใช้ Selenium — ✔ ใช้ PHIVOLCS (earthquake.phivolcs.dost.gov.ph) แทน ReliefWeb HTML
- ต้องตรวจสอบและปฏิบัติตาม `robots.txt` และข้อกำหนดเว็บไซต์
- ห้ามเก็บข้อมูลส่วนบุคคลตามข้อกำหนด PDPA
- ข้อมูลรวมต้องมีอย่างน้อย 100 รายการที่ตรวจสอบได้
- Dashboard ต้องอ่านข้อมูลจาก PostgreSQL โดยตรง
- เก็บ API keys/passwords ใน `.env` และห้าม commit ขึ้น Git
- ต้องแสดงที่มาของข้อมูลและเวลาที่ดึงข้อมูล
- ห้ามสร้างข้อมูลจริงปลอมขึ้นมาเพื่อให้ครบจำนวน

## 8. โครงสร้างโฟลเดอร์ที่เสนอ

```text
global-disaster-dashboard/
├── dags/
│   └── disaster_etl_dag.py
├── src/
│   ├── extractors/
│   │   ├── nasa_eonet.py
│   │   ├── gdacs_api.py
│   │   ├── usgs_earthquake.py
│   │   └── web_scraper.py
│   ├── transformations/
│   │   ├── normalize.py
│   │   └── validate.py
│   └── database/
│       └── postgres.py
├── dashboard/
│   └── app.py
├── sql/
│   └── schema.sql
├── tests/
├── docs/
├── .env.example
├── .gitignore
├── docker-compose.yml
└── README.md
```

## 9. Definition of Done

โปรเจกต์ถือว่าพร้อมส่งเมื่อ:
- [x] Airflow DAG ทำงานได้และมีผลการรันให้ตรวจสอบ
- [x] มี API อย่างน้อย 3 แหล่งตามขอบเขต และมี Web Scraping อย่างน้อย 1 แหล่งที่ได้รับอนุญาต — ✔ ใช้ PHIVOLCS (earthquake.phivolcs.dost.gov.ph) แทน ReliefWeb HTML
- [x] PostgreSQL มีข้อมูลผ่าน validation อย่างน้อย 100 รายการ
- [x] รัน ETL ซ้ำแล้วไม่มีรายการซ้ำเพิ่ม
- [x] ทดสอบการล้มเหลวของแหล่งข้อมูลได้
- [x] Dashboard อ่านข้อมูลจาก PostgreSQL โดยตรงและมี KPI กราฟ ตาราง และตัวกรอง
- [x] มี README วิธีติดตั้ง วิธีรัน และคำอธิบายแหล่งข้อมูล
- [x] ไม่เก็บข้อมูลส่วนบุคคลหรือเปิดเผย credentials

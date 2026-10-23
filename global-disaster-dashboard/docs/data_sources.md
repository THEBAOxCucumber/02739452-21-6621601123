# แหล่งข้อมูล (Data Sources)

ตรวจสอบเมื่อ: 2026-10-23 (UTC) · API อย่างเป็นทางการ 5 แหล่ง + Web Scraping 1 แหล่ง (PHIVOLCS) · มีเพียง ReliefWeb ที่ต้องใช้ appname ที่ได้รับอนุมัติ

| แหล่ง | `source_name` | ประเภท | Endpoint / URL | รูปแบบ | เวลาเหตุการณ์ |
|---|---|---|---|---|---|
| USGS Earthquake API | `usgs` | REST API | `https://earthquake.usgs.gov/fdsnws/event/1/query?format=geojson` | GeoJSON | epoch ms → UTC |
| NASA EONET v3 | `nasa_eonet` | REST API | `https://eonet.gsfc.nasa.gov/api/v3/events?status=all` | JSON (GeoJSON geometry) | ISO-8601 `Z` |
| GDACS API | `gdacs` | REST API | `https://www.gdacs.org/gdacsapi/api/events/geteventlist/SEARCH` | GeoJSON | ISO ไม่มี timezone (เป็น UTC) |
| ReliefWeb API v2 | `reliefweb_api` | REST API (ต้องมี appname) | `https://api.reliefweb.int/v2/disasters` | JSON | `date.event` ISO-8601 |
| GeoNet Quake API (NZ) | `geonet` | REST API | `https://api.geonet.org.nz/quake?MMI=-1` | GeoJSON | ISO-8601 `Z` |
| PHIVOLCS Latest Earthquakes | `phivolcs_html` | **Web Scraping** (requests + BeautifulSoup) | `https://earthquake.phivolcs.dost.gov.ph/` | HTML table | เวลาฟิลิปปินส์ (UTC+8) ระดับนาที → UTC |

เวลาที่ดึงข้อมูลแต่ละแถวเก็บไว้ในคอลัมน์ `fetched_at` และไฟล์ดิบของแต่ละรอบอยู่ที่ `data/<dag_run_id>/<source>_raw.json`

## รายละเอียดและข้อจำกัด

### USGS
- พารามิเตอร์: `starttime=2026-01-01`, `minmagnitude=4.5`, `limit=1000`, `orderby=time` (ปรับได้ใน `.env`)
- API จำกัดผลลัพธ์ไม่เกิน 20,000 รายการต่อ query (M2.5+ ตั้งแต่ต้นปี 2026 เกินแล้ว จึงใช้ M4.5+)
- `limit=1000` ได้เหตุการณ์ล่าสุด 1,000 รายการ (ประมาณ 6–7 สัปดาห์)

### NASA EONET
- ได้ไฟป่า (ส่วนใหญ่), น้ำท่วม, พายุ; `event_time` = วันที่ observation แรก (เริ่มเหตุการณ์), พิกัด/ขนาด = observation ล่าสุด ถ้าเป็น Polygon ใช้ค่าเฉลี่ยจุดยอดเป็นพิกัด
- เหตุการณ์ส่วนใหญ่อ้างอิงรายงาน GDACS (`sources[].url` = `gdacs.org/report.aspx?eventtype=..&eventid=..`) → ใช้ตัดซ้ำข้ามแหล่ง
- พบข้อมูลต้นทางผิดรูปแบบ: Polygon บางรายการสลับ `[lat, lon]` (ผิดมาตรฐาน GeoJSON) → validation ส่งเข้า quarantine ไม่แก้เอง

### GDACS API
- คืนผลสูงสุด 100 รายการต่อ request → ดึง **แยกตามประเภท** (`GDACS_EVENT_TYPES=EQ;TC;FL;VO;DR;WF`) ประเภทละ 1 request
- ไม่ใช้ `pagenumber` เพราะลำดับผลไม่คงที่: ทดสอบจริงหน้า 2 ซ้ำกับหน้า 1 ถึง 50 รายการ และไฟป่าเบียดประเภทอื่นจนได้ข้อมูลแค่ ~2 สัปดาห์
- **robots.txt ของ gdacs.org**: `Request-rate: 1/60` และ `Visit-time: 0400-0645` (UTC)
  → แต่ละ request ห่างกัน 60 วินาที (6 ประเภท ≈ 5 นาที) และตั้งเวลา DAG ที่ 04:30 UTC (11:30 เวลาไทย)
  → **นอกช่วงเวลานี้ task GDACS จะ skip อัตโนมัติ** (ไม่ส่ง request, ไม่ทำให้ DAG fail) ต้องเริ่มก่อน 06:38 UTC เพื่อให้ 6 request เสร็จก่อน 06:45 (ปิดได้ด้วย `GDACS_RESPECT_VISIT_TIME=false`)
- ใช้ API อย่างเป็นทางการเท่านั้น (ไม่ดึงหน้า HTML ของ gdacs.org)

### GeoNet API (เพิ่มเพื่อให้มี API ที่รันได้ตลอดเวลา)
- GNS Science (นิวซีแลนด์) · robots.txt อนุญาต `/quake` · ไม่ต้องใช้ key · ข้อมูลอนุญาตแบบ CC BY 4.0 (ต้องระบุ GeoNet เป็นแหล่งที่มา — แสดงไว้ท้าย Dashboard)
- ได้แผ่นดินไหวล่าสุด ~100 รายการต่อครั้ง; เหตุการณ์ที่ GeoNet ลบ (`quality = deleted`) ไม่นำเข้า
- ตัดซ้ำกับ USGS ด้วยกติกาเดียวกับ PHIVOLCS (`geonet_eq_matches_usgs`)

### ReliefWeb API
- `POST https://api.reliefweb.int/v2/disasters?appname=<RELIEFWEB_APPNAME>` (เอกสาร: https://apidoc.reliefweb.int/read/resources/disasters/)
- **ต้องใช้ appname ที่ ReliefWeb อนุมัติแล้ว** (ไม่อนุมัติ → HTTP 403) ขอได้ที่ https://apidoc.reliefweb.int/ ระหว่างรอ ให้เว้น `RELIEFWEB_APPNAME` ว่างไว้ แหล่งนี้จะถูก **skip** (ไม่ทำให้ DAG fail)
- ข้อจำกัด: ไม่เกิน 1,000 รายการต่อ call, 10,000 call ต่อวัน → ใช้ `limit=1000` + `offset` สูงสุด 5 หน้า วันละ 1 รอบ
- ฟิลด์ที่ใช้: `id`, `name`, `glide`, `status`, `date.event`, `primary_country` (name, iso3), `primary_type.code`, `url`; filter `date.event >= RELIEFWEB_START_DATE` (ค่าเริ่มต้น 2025-01-01)
- **API ไม่มีพิกัด** → ใช้จุดกึ่งกลางประเทศจาก `src/reference/country_centroids.csv` (ข้อมูลเปิด mledoze/countries v4.1.1, ODbL) และบันทึก `raw_data.location_precision = "country_centroid"` (ถ้า API คืน `primary_country.location` มาจะใช้ค่านั้นแทน)
- ประเภท EP (โรคระบาด), AC (ภัยจากเทคโนโลยี), OT ไม่ใช่ภัยธรรมชาติ → quarantine (`out-of-scope event_type`)
- ไม่เก็บข้อความคำอธิบาย ไม่มีข้อมูลส่วนบุคคล

### ทำไมไม่ใช้ RSS ของ ReliefWeb
- `https://reliefweb.int/disasters/rss.xml` ไม่มีพิกัด (20 รายการล่าสุดเท่านั้น) และ robots.txt มี `Disallow: /*/rss.xml`

### PHIVOLCS (Web Scraping)
- หน้า https://earthquake.phivolcs.dost.gov.ph/ ของ Philippine Institute of Volcanology and Seismology (หน่วยงานรัฐบาลฟิลิปปินส์)
- HTML render ฝั่ง server: ตาราง `Date - Time (Philippine Time) | Latitude (ºN) | Longitude (ºE) | Depth (km) | Mag | Location` มีแผ่นดินไหวทั้งเดือนในหน้าเดียว (~1,300 รายการ) → **1 request ต่อรอบ** ไม่ต้องไล่หน้า
- **robots.txt**: ไม่มี (HTTP 404) → ตาม RFC 9309 ถือว่าไม่มีข้อจำกัด; scraper ยังตรวจ robots.txt ทุกรอบ (ถ้ามีกฎห้ามจะหยุด, ถ้า server ตอบ 5xx จะหยุดเพื่อความปลอดภัย)
- ตัวตรวจ robots.txt รองรับ wildcard `*` และ `$` ตาม RFC 9309 (`urllib.robotparser` ของ Python ไม่รองรับ)
- เวลาเป็นเวลาฟิลิปปินส์ (UTC+8) ความละเอียดระดับนาที → แปลงเป็น UTC
- `source_event_id` = เวลาเกิดแบบ UTC ระดับนาที เช่น `20261023T0622Z` (ไม่ใช้ชื่อไฟล์ bulletin เพราะเปลี่ยนจาก `B1` → `B2F` เมื่อปรับแก้ผล) ถ้าเกิด 2 ครั้งในนาทีเดียวกันจะต่อท้าย `-2`
- หาตารางจากหัวคอลัมน์ ถ้าเว็บเปลี่ยน layout จะ error ชัดเจน (`table not found`) แทนที่จะได้ข้อมูลผิด
- ใช้ `requests` + `BeautifulSoup` เท่านั้น ไม่ใช้ Selenium; เก็บเฉพาะค่าทางแผ่นดินไหว ไม่มีข้อมูลส่วนบุคคล
- ข้อจำกัด: ครอบคลุมเฉพาะบริเวณฟิลิปปินส์ และเฉพาะเดือนปัจจุบัน (ข้อมูลเดือนก่อนที่โหลดไปแล้วยังอยู่ในฐานข้อมูล)

### ReliefWeb HTML (เลิกใช้แล้ว)
- เดิมดึง HTML จาก reliefweb.int/disasters → เปลี่ยนเป็น ReliefWeb API ตามคำแนะนำให้ใช้ช่องทางที่ผู้ให้บริการเตรียมไว้ ข้อมูล `reliefweb_html` เดิมถูกลบออกจากฐานข้อมูลแล้ว

## กติกาการตัดซ้ำข้ามแหล่ง (Cross-source dedup)

ทุกแถวยังถูกเก็บไว้ แต่แถวที่ซ้ำจะมี `duplicate_of` ชี้ไปยังแถวหลัก (canonical) และ Dashboard นับเฉพาะแถวหลักเป็นค่าเริ่มต้น
ลำดับความสำคัญ: `usgs` > `gdacs` > `geonet` > `phivolcs_html` > `nasa_eonet` > `reliefweb_api`

1. **eonet_cites_gdacs** — เหตุการณ์ EONET ที่ `source_url` ชี้ไปรายงาน GDACS `eventtype=X&eventid=N` ซ้ำกับแถว GDACS `X-N`
2. **gdacs_eq_matches_usgs** — แผ่นดินไหว GDACS ที่เวลาต่างจาก USGS ≤ 120 วินาที, ระยะห่าง ≤ 100 กม. (haversine) และขนาดต่างกัน ≤ 0.5 → ใช้แถว USGS
3. **phivolcs_eq_matches_usgs** — แผ่นดินไหว PHIVOLCS ที่เวลาต่างจาก USGS ≤ 120 วินาที และระยะห่าง ≤ 100 กม. → ใช้แถว USGS (ไม่เทียบขนาด เพราะสองหน่วยงานใช้มาตราขนาดต่างกัน เช่น PHIVOLCS 4.8 / USGS 5.2 สำหรับเหตุการณ์เดียวกัน)
4. ยุบ chain (EONET → GDACS → USGS) ให้ชี้ไปที่แถวหลักเสมอ

ReliefWeb ไม่ได้จับคู่ข้ามแหล่ง เพราะพิกัดเป็นระดับประเทศ จับคู่แล้วเสี่ยงผิดพลาด

## ผลการรันจริงครั้งแรก (2026-10-23, ตอนยังใช้ HTML scraping และ GDACS แบบแบ่งหน้า — ประวัติ)

| แหล่ง | ดึงมา | ผ่าน validation และโหลด | quarantine | ซ้ำในชุด |
|---|---|---|---|---|
| usgs | 1000 | 1000 | 0 | 0 |
| nasa_eonet | 500 | 498 | 2 (พิกัดผิดจากต้นทาง) | 0 |
| gdacs | 300 | 250 | 0 | 50 |
| reliefweb_html | 81 | 39 | 42 | 0 |

รวม 1,787 แถว, ซ้ำข้ามแหล่ง 216 แถว (eonet_cites_gdacs 149, gdacs_eq_matches_usgs 67) → **เหตุการณ์ไม่ซ้ำ 1,571 รายการ**

รอบตรวจสอบ (manual__verify2): ReliefWeb หน้าเดียวดึงได้ 60 รายการ โหลด 39 (เท่าเดิม), รันซ้ำ inserted=0 ทุกแหล่ง

รอบเปลี่ยนเป็น API (manual__api_switch): reliefweb_api = skipped (ยังไม่มี appname), แหล่งอื่น inserted=0 → **เหตุการณ์ไม่ซ้ำ 1,532 รายการ** จาก 3 แหล่ง, quality checks ผ่าน 6/6

รอบเพิ่ม PHIVOLCS (manual__phivolcs): ดึง 1,343 รายการ ผ่าน validation ทั้งหมด, ซ้ำกับ USGS 18 รายการ → **เหตุการณ์ไม่ซ้ำ 2,857 รายการ** จาก 4 แหล่ง; รันซ้ำ (manual__phivolcs2) inserted=0 updated=1343

รอบพร้อมสาธิต (manual__demo_ready, 07:20 UTC): **DAG success** — EONET, USGS, GeoNet (+95), PHIVOLCS สำเร็จ; GDACS skip (นอกช่วงเวลา), ReliefWeb skip (ไม่มี appname) → **เหตุการณ์ไม่ซ้ำ 2,952 รายการ** จาก 5 แหล่ง, quality checks 6/6

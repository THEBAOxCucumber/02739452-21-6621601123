"""แดชบอร์ดติดตามภัยธรรมชาติทั่วโลก — อ่านข้อมูลจาก PostgreSQL โดยตรง (ไม่อ่านไฟล์ ไม่เรียก API)"""
from datetime import datetime, timedelta, timezone
import os

import altair as alt
import pandas as pd
import psycopg2
import pydeck as pdk
import streamlit as st

st.set_page_config(page_title="แดชบอร์ดภัยธรรมชาติโลก", page_icon="🌏", layout="wide")

THAI_TZ = timezone(timedelta(hours=7))
THAI_MONTHS = ["ม.ค.", "ก.พ.", "มี.ค.", "เม.ย.", "พ.ค.", "มิ.ย.",
               "ก.ค.", "ส.ค.", "ก.ย.", "ต.ค.", "พ.ย.", "ธ.ค."]

# ---------- ชื่อภาษาไทย ----------
TYPE_TH = {
    "earthquake": "แผ่นดินไหว", "wildfire": "ไฟป่า", "flood": "น้ำท่วม", "storm": "พายุ",
    "volcano": "ภูเขาไฟ", "drought": "ภัยแล้ง", "landslide": "ดินถล่ม", "fire": "ไฟไหม้",
    "tsunami": "สึนามิ", "cold_wave": "คลื่นความหนาว", "heat_wave": "คลื่นความร้อน",
    "sea_lake_ice": "น้ำแข็งทะเล/ทะเลสาบ", "snow": "หิมะ", "dust_haze": "ฝุ่น/หมอกควัน",
    "temperature_extreme": "อุณหภูมิสุดขั้ว", "other_natural": "ภัยธรรมชาติอื่น ๆ",
}
TYPE_ICON = {"earthquake": "🌐", "wildfire": "🔥", "flood": "🌊", "storm": "🌀"}
SOURCE_TH = {
    "usgs": "USGS — สำนักสำรวจธรณีวิทยาสหรัฐฯ (API)",
    "gdacs": "GDACS — ระบบเตือนภัยพิบัติโลก (API)",
    "nasa_eonet": "NASA EONET — เหตุการณ์ธรรมชาติจากดาวเทียม (API)",
    "geonet": "GeoNet — แผ่นดินไหวนิวซีแลนด์ (API)",
    "reliefweb_api": "ReliefWeb — สหประชาชาติ UN OCHA (API)",
    "phivolcs_html": "PHIVOLCS — แผ่นดินไหวฟิลิปปินส์ (Web Scraping)",
}
SOURCE_SHORT = {"usgs": "USGS", "gdacs": "GDACS", "nasa_eonet": "NASA EONET", "geonet": "GeoNet",
                "reliefweb_api": "ReliefWeb", "phivolcs_html": "PHIVOLCS"}
SEVERITY_TH = {"green": "🟢 เขียว (ต่ำ)", "yellow": "🟡 เหลือง", "orange": "🟠 ส้ม", "red": "🔴 แดง (สูง)"}
STATUS_TH = {
    "success": ("✅", "สำเร็จ"), "partial_success": ("⚠️", "สำเร็จบางส่วน"),
    "quality_failed": ("⚠️", "คุณภาพข้อมูลไม่ผ่าน"), "failed": ("❌", "ล้มเหลว"),
    "skipped": ("⏭️", "ข้าม (ตามเงื่อนไข)"),
}
CHECK_TH = {
    "canonical_events_at_least_100": "มีเหตุการณ์ไม่ซ้ำอย่างน้อย 100 รายการ",
    "no_duplicate_source_ids": "ไม่มีรหัสเหตุการณ์ซ้ำในแหล่งเดียวกัน",
    "coordinates_in_range": "พิกัดอยู่ในช่วงที่ถูกต้อง",
    "no_future_events": "ไม่มีเหตุการณ์ที่วันที่อยู่ในอนาคต",
    "sources_with_data": "มีข้อมูลอย่างน้อย 3 แหล่ง",
    "duplicate_pointers_canonical": "รายการซ้ำชี้ไปยังรายการหลักเสมอ",
}

# สีตามประเภท (ลำดับคงที่ ผ่านการตรวจสำหรับผู้มีภาวะตาบอดสี) — ประเภทอื่นรวมเป็น "อื่น ๆ" สีเทา
GROUP_COLORS = {"แผ่นดินไหว": "#2a78d6", "ไฟป่า": "#eb6834", "น้ำท่วม": "#1baf7a", "พายุ": "#eda100"}
OTHER_LABEL, OTHER_COLOR = "อื่น ๆ", "#8a8984"
COLOR_SCALE = alt.Scale(domain=list(GROUP_COLORS) + [OTHER_LABEL],
                        range=list(GROUP_COLORS.values()) + [OTHER_COLOR])

# ---------- สไตล์ ----------
st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=IBM+Plex+Sans+Thai:wght@400;500;600;700&display=swap');
html, body, [class*="css"], .stMarkdown, .stMetric, button, input, textarea, select,
[data-testid="stSidebar"] * { font-family: 'IBM Plex Sans Thai', sans-serif !important; }
.block-container { padding-top: 3.2rem; max-width: 1400px; }
.hero { background: linear-gradient(120deg, #0d366b 0%, #2a78d6 100%); color: #fff;
        border-radius: 16px; padding: 22px 28px; margin-bottom: 18px; }
.hero h1 { color: #fff; font-size: 1.9rem; margin: 0 0 4px 0; padding: 0; }
.hero p { color: #dbe8fb; margin: 0; font-size: 1rem; }
.hero .badges { margin-top: 12px; display: flex; gap: 8px; flex-wrap: wrap; }
.hero .badge { background: rgba(255,255,255,.16); border: 1px solid rgba(255,255,255,.28);
               border-radius: 999px; padding: 3px 12px; font-size: .85rem; color: #fff; }
[data-testid="stMetric"] { background: #ffffff; border: 1px solid #e6e4df; border-radius: 14px;
                           padding: 14px 16px; box-shadow: 0 1px 2px rgba(0,0,0,.04); }
[data-testid="stMetricLabel"] p { font-size: .95rem; color: #52514e; }
[data-testid="stMetricValue"] { font-size: 1.9rem; font-weight: 700; color: #0b0b0b; }
.section-note { color: #52514e; font-size: .92rem; margin: -6px 0 10px 0; }
.legend { display: flex; gap: 16px; flex-wrap: wrap; font-size: .92rem; color: #0b0b0b; margin: 6px 0 2px 0; }
.legend span.dot { display: inline-block; width: 12px; height: 12px; border-radius: 50%;
                   margin-right: 6px; vertical-align: -1px; }
.src-card { border: 1px solid #e6e4df; border-radius: 12px; padding: 12px 14px; background: #fff;
            margin-bottom: 10px; }
.src-card .name { font-weight: 600; }
.src-card .meta { color: #52514e; font-size: .88rem; }
.stTabs [data-baseweb="tab"] { font-size: 1.02rem; padding: 8px 14px; }
footer { visibility: hidden; }
</style>
""", unsafe_allow_html=True)


def connect():
    return psycopg2.connect(
        host=os.getenv("DB_HOST", "localhost"),
        port=os.getenv("DB_PORT", "5432"),
        dbname=os.getenv("DB_NAME", "disaster_db"),
        user=os.getenv("DB_USER", "disaster_user"),
        password=os.getenv("DB_PASSWORD", ""),
    )


@st.cache_data(ttl=60)
def read_sql(sql, params=None):
    conn = connect()
    try:
        with conn.cursor() as cur:
            cur.execute(sql, params)
            return pd.DataFrame(cur.fetchall(), columns=[d[0] for d in cur.description])
    finally:
        conn.close()


def thai_dt(value, with_time=True):
    """แสดงวันเวลาแบบไทย (เวลาประเทศไทย UTC+7, ปี พ.ศ.)"""
    if value is None or pd.isna(value):
        return "-"
    ts = pd.Timestamp(value)
    ts = (ts.tz_localize("UTC") if ts.tzinfo is None else ts).tz_convert(THAI_TZ)
    text = f"{ts.day} {THAI_MONTHS[ts.month - 1]} {ts.year + 543}"
    return f"{text} {ts:%H:%M} น." if with_time else text


def type_th(code):
    return TYPE_TH.get(code, code)


def group_of(code):
    label = type_th(code)
    return label if label in GROUP_COLORS else OTHER_LABEL


# ---------- โหลดข้อมูลพื้นฐาน ----------
try:
    bounds = read_sql("SELECT MIN(event_time) AS lo, MAX(event_time) AS hi, MAX(fetched_at) AS fetched "
                      "FROM disaster_events")
except Exception as exc:
    st.error("เชื่อมต่อฐานข้อมูล PostgreSQL ไม่ได้ — ตรวจสอบไฟล์ `.env` และว่า service `postgres` ทำงานอยู่")
    st.code(str(exc))
    st.stop()

if bounds.empty or pd.isna(bounds.loc[0, "lo"]):
    st.info("ยังไม่มีข้อมูล — เปิด Airflow ที่ http://localhost:8080 แล้วกด ▶ Trigger DAG `global_disaster_etl`")
    st.stop()

lo = pd.Timestamp(bounds.loc[0, "lo"]).tz_convert(THAI_TZ).date()
hi = pd.Timestamp(bounds.loc[0, "hi"]).tz_convert(THAI_TZ).date()
all_types = read_sql("SELECT DISTINCT event_type FROM disaster_events ORDER BY 1")["event_type"].tolist()
all_sources = read_sql("SELECT DISTINCT source_name FROM disaster_events ORDER BY 1")["source_name"].tolist()

# ---------- แถบตัวกรอง ----------
with st.sidebar:
    st.markdown("## 🔎 ตัวกรองข้อมูล")
    default_start = max(lo, hi - timedelta(days=30))
    picked = st.date_input("ช่วงวันที่เกิดเหตุ", (default_start, hi), min_value=lo, max_value=hi,
                           format="DD/MM/YYYY", help="วันที่ตามเวลาประเทศไทย")
    start, end = picked if isinstance(picked, (list, tuple)) and len(picked) == 2 else (lo, hi)
    types = st.multiselect("ประเภทภัยพิบัติ", all_types, default=all_types, format_func=type_th)
    sources = st.multiselect("แหล่งข้อมูล", all_sources, default=all_sources,
                             format_func=lambda s: SOURCE_SHORT.get(s, s))
    min_mag = st.slider("ขนาดแผ่นดินไหวขั้นต่ำ (แมกนิจูด)", 0.0, 7.0, 0.0, 0.5,
                        help="มีผลเฉพาะแผ่นดินไหว ภัยประเภทอื่นแสดงทั้งหมด")
    include_dupes = st.toggle("แสดงรายการซ้ำข้ามแหล่ง", value=False,
                              help="ปิด = นับเหตุการณ์จริงแต่ละครั้งเพียงครั้งเดียว "
                                   "(เช่น แผ่นดินไหวเดียวกันที่ทั้ง USGS และ GDACS รายงาน)")
    if st.button("🔄 โหลดข้อมูลล่าสุด", use_container_width=True):
        st.cache_data.clear()
        st.rerun()
    st.divider()
    st.markdown("""
**วิธีอ่านแดชบอร์ด**
- ตัวเลขด้านบน = จำนวนเหตุการณ์ตามตัวกรอง
- **ภาพรวม** — แนวโน้มตามเวลาและสัดส่วนประเภท
- **แผนที่** — ชี้ที่จุดเพื่อดูรายละเอียด
- **รายการเหตุการณ์** — ค้นหา/เรียงลำดับได้
- **แหล่งข้อมูลและสถานะระบบ** — ผลการดึงข้อมูลรอบล่าสุด
""")

if not types or not sources:
    st.warning("กรุณาเลือกประเภทภัยพิบัติและแหล่งข้อมูลอย่างน้อยอย่างละ 1 รายการ")
    st.stop()

where = ["event_time >= %(start)s", "event_time < %(end)s",
         "event_type = ANY(%(types)s)", "source_name = ANY(%(sources)s)",
         "(event_type <> 'earthquake' OR COALESCE(magnitude, 0) >= %(min_mag)s)"]
if not include_dupes:
    where.append("duplicate_of IS NULL")
params = {
    "start": datetime.combine(start, datetime.min.time(), THAI_TZ),
    "end": datetime.combine(end + timedelta(days=1), datetime.min.time(), THAI_TZ),
    "types": types, "sources": sources, "min_mag": min_mag,
}
events = read_sql(f"""
    SELECT id, event_time, event_type, event_name, country, source_name, magnitude, magnitude_unit,
           severity, latitude, longitude, source_url, fetched_at, duplicate_of
    FROM disaster_events WHERE {' AND '.join(where)}
    ORDER BY event_time DESC
""", params)
totals = read_sql("""
    SELECT COUNT(*) FILTER (WHERE duplicate_of IS NULL) AS canonical, COUNT(*) AS all_rows,
           (SELECT COUNT(*) FROM data_quarantine) AS quarantined
    FROM disaster_events
""").iloc[0]
last_run = read_sql("""
    SELECT status, finished_at FROM pipeline_runs WHERE source_name = '__overall__'
    ORDER BY finished_at DESC LIMIT 1
""")

# ---------- ส่วนหัว ----------
run_badge = "ยังไม่มีการรัน pipeline"
if not last_run.empty:
    icon, label = STATUS_TH.get(last_run.loc[0, "status"], ("ℹ️", last_run.loc[0, "status"]))
    run_badge = f"{icon} Pipeline ล่าสุด: {label} · {thai_dt(last_run.loc[0, 'finished_at'])}"
st.markdown(f"""
<div class="hero">
  <h1>🌏 แดชบอร์ดติดตามภัยธรรมชาติทั่วโลก</h1>
  <p>รวมข้อมูลแผ่นดินไหว พายุ ไฟป่า น้ำท่วม และภัยธรรมชาติอื่น ๆ จาก {len(all_sources)} แหล่งข้อมูล
     ประมวลผลด้วย Apache Airflow และอ่านจากฐานข้อมูล PostgreSQL โดยตรง</p>
  <div class="badges">
    <span class="badge">📅 ช่วงที่แสดง: {thai_dt(start, False)} – {thai_dt(end, False)}</span>
    <span class="badge">🗄️ เหตุการณ์ในฐานข้อมูล: {int(totals['canonical']):,} รายการ (ไม่นับซ้ำ)</span>
    <span class="badge">⏱️ ดึงข้อมูลล่าสุด: {thai_dt(bounds.loc[0, 'fetched'])}</span>
    <span class="badge">{run_badge}</span>
  </div>
</div>
""", unsafe_allow_html=True)

# ---------- ตัวเลขสรุป ----------
counts = events["event_type"].value_counts()
k = st.columns(5)
k[0].metric("📌 ทั้งหมด", f"{len(events):,}", help="จำนวนเหตุการณ์ทุกประเภทตามตัวกรองที่เลือก")
for col, code in zip(k[1:], ["earthquake", "wildfire", "flood", "storm"]):
    col.metric(f"{TYPE_ICON[code]} {TYPE_TH[code]}", f"{int(counts.get(code, 0)):,}")

if events.empty:
    st.info("ไม่พบเหตุการณ์ตามตัวกรองที่เลือก — ลองขยายช่วงวันที่หรือเลือกประเภทเพิ่ม")
    st.stop()

events["event_time"] = pd.to_datetime(events["event_time"], utc=True)
events["time_th"] = events["event_time"].dt.tz_convert(THAI_TZ)
events["ประเภท"] = events["event_type"].map(type_th)
events["กลุ่ม"] = events["event_type"].map(group_of)
events["แหล่งข้อมูล"] = events["source_name"].map(lambda s: SOURCE_SHORT.get(s, s))

tab_overview, tab_map, tab_table, tab_system = st.tabs(
    ["📊 ภาพรวม", "🗺️ แผนที่", "📋 รายการเหตุการณ์", "⚙️ แหล่งข้อมูลและสถานะระบบ"])

# ---------- แท็บ: ภาพรวม ----------
with tab_overview:
    span_days = (end - start).days
    daily = span_days <= 62
    st.markdown(f"#### จำนวนเหตุการณ์{'รายวัน' if daily else 'รายเดือน'} แยกตามประเภท")
    st.markdown('<p class="section-note">แท่งสูง = มีเหตุการณ์มาก · ชี้ที่แท่งเพื่อดูจำนวน</p>',
                unsafe_allow_html=True)
    period = events["time_th"].dt.tz_localize(None).dt.to_period("D" if daily else "M").dt.to_timestamp()
    by_period = (events.assign(period=period).groupby(["period", "กลุ่ม"]).size()
                 .rename("จำนวน").reset_index())
    by_period["ช่วงเวลา"] = by_period["period"].map(
        lambda d: f"{d.day} {THAI_MONTHS[d.month - 1]}" if daily
        else f"{THAI_MONTHS[d.month - 1]} {str(d.year + 543)[2:]}")
    order = by_period.sort_values("period")["ช่วงเวลา"].unique().tolist()
    st.altair_chart(
        alt.Chart(by_period).mark_bar(cornerRadiusTopLeft=4, cornerRadiusTopRight=4,
                                      stroke="#fcfcfb", strokeWidth=1).encode(
            x=alt.X("ช่วงเวลา:N", sort=order, title=None, axis=alt.Axis(labelAngle=0 if len(order) <= 14 else -45)),
            y=alt.Y("sum(จำนวน):Q", title="จำนวนเหตุการณ์", axis=alt.Axis(grid=True, gridOpacity=0.4)),
            color=alt.Color("กลุ่ม:N", title="ประเภท", scale=COLOR_SCALE,
                            legend=alt.Legend(orient="top", direction="horizontal")),
            order=alt.Order("กลุ่ม:N"),
            tooltip=[alt.Tooltip("ช่วงเวลา:N"), alt.Tooltip("กลุ่ม:N", title="ประเภท"),
                     alt.Tooltip("sum(จำนวน):Q", title="จำนวน", format=",")],
        ).properties(height=340),
        use_container_width=True,
    )

    left, right = st.columns(2)
    with left:
        st.markdown("#### ประเภทภัยพิบัติ")
        by_type = events.groupby(["ประเภท", "กลุ่ม"]).size().rename("จำนวน").reset_index()
        x_max = int(by_type["จำนวน"].max() * 1.18) + 1  # เผื่อที่ให้ตัวเลขท้ายแท่ง
        base = alt.Chart(by_type).encode(
            y=alt.Y("ประเภท:N", sort="-x", title=None),
            x=alt.X("จำนวน:Q", title="จำนวนเหตุการณ์", axis=alt.Axis(grid=True, gridOpacity=0.4),
                      scale=alt.Scale(domain=[0, x_max])),
            tooltip=["ประเภท:N", alt.Tooltip("จำนวน:Q", format=",")])
        st.altair_chart(
            (base.mark_bar(cornerRadiusTopRight=4, cornerRadiusBottomRight=4).encode(
                color=alt.Color("กลุ่ม:N", scale=COLOR_SCALE, legend=None))
             + base.mark_text(align="left", dx=4, color="#52514e").encode(text=alt.Text("จำนวน:Q", format=",")))
            .properties(height=max(160, 34 * len(by_type))),
            use_container_width=True)
    with right:
        st.markdown("#### แหล่งข้อมูล")
        by_src = events.groupby("แหล่งข้อมูล").size().rename("จำนวน").reset_index()
        x_max = int(by_src["จำนวน"].max() * 1.18) + 1  # เผื่อที่ให้ตัวเลขท้ายแท่ง
        base = alt.Chart(by_src).encode(
            y=alt.Y("แหล่งข้อมูล:N", sort="-x", title=None),
            x=alt.X("จำนวน:Q", title="จำนวนเหตุการณ์", axis=alt.Axis(grid=True, gridOpacity=0.4),
                      scale=alt.Scale(domain=[0, x_max])),
            tooltip=["แหล่งข้อมูล:N", alt.Tooltip("จำนวน:Q", format=",")])
        st.altair_chart(
            (base.mark_bar(color="#2a78d6", cornerRadiusTopRight=4, cornerRadiusBottomRight=4)
             + base.mark_text(align="left", dx=4, color="#52514e").encode(text=alt.Text("จำนวน:Q", format=",")))
            .properties(height=max(160, 34 * len(by_src))),
            use_container_width=True)

    quakes = events[(events["event_type"] == "earthquake") & events["magnitude"].notna()]
    if not quakes.empty:
        st.markdown("#### 🌐 แผ่นดินไหวรุนแรงที่สุด 10 อันดับ (ในช่วงที่เลือก)")
        top = quakes.nlargest(10, "magnitude")
        st.dataframe(
            pd.DataFrame({
                "ขนาด": top["magnitude"].round(1),
                "ตำแหน่ง": top["event_name"],
                "วันเวลา (เวลาไทย)": top["event_time"].map(thai_dt),
                "แหล่งข้อมูล": top["แหล่งข้อมูล"],
                "รายละเอียด": top["source_url"],
            }),
            hide_index=True, use_container_width=True,
            column_config={
                "ขนาด": st.column_config.ProgressColumn("ขนาด (แมกนิจูด)", format="%.1f",
                                                        min_value=0, max_value=9),
                "รายละเอียด": st.column_config.LinkColumn("รายละเอียด", display_text="เปิดดู ↗"),
            })

# ---------- แท็บ: แผนที่ ----------
with tab_map:
    st.markdown("#### ตำแหน่งเหตุการณ์")
    st.markdown('<p class="section-note">ขนาดจุดของแผ่นดินไหวเพิ่มตามแมกนิจูด · ชี้ที่จุดเพื่อดูรายละเอียด · '
                'เลื่อน/ซูมแผนที่ได้</p>', unsafe_allow_html=True)
    geo = events.dropna(subset=["latitude", "longitude"]).copy()
    hex_to_rgb = lambda h: [int(h[i:i + 2], 16) for i in (1, 3, 5)]
    geo["color"] = geo["กลุ่ม"].map(lambda g: hex_to_rgb(GROUP_COLORS.get(g, OTHER_COLOR)) + [200])
    geo["radius"] = geo.apply(
        lambda r: 15000 + (max(r["magnitude"], 0) ** 2) * 6000
        if r["event_type"] == "earthquake" and pd.notna(r["magnitude"]) else 30000, axis=1)
    geo["mag_text"] = geo["magnitude"].map(lambda m: f"{m:.1f}" if pd.notna(m) else "-")
    geo["when"] = geo["event_time"].map(thai_dt)
    geo["name"] = geo["event_name"].fillna("-")
    geo["type_label"], geo["source_label"] = geo["ประเภท"], geo["แหล่งข้อมูล"]
    layer = pdk.Layer(
        "ScatterplotLayer", data=geo[["longitude", "latitude", "color", "radius", "type_label", "name",
                                      "mag_text", "when", "source_label"]],
        get_position="[longitude, latitude]", get_fill_color="color", get_radius="radius",
        radius_min_pixels=3, radius_max_pixels=28, stroked=True, get_line_color=[255, 255, 255, 220],
        line_width_min_pixels=1, pickable=True, auto_highlight=True)
    st.pydeck_chart(pdk.Deck(
        layers=[layer], map_style="light",
        initial_view_state=pdk.ViewState(latitude=12, longitude=100, zoom=1.1),
        tooltip={"html": "<b>{type_label}</b><br/>{name}<br/>ขนาด: {mag_text}<br/>{when}<br/>"
                         "<span style='opacity:.8'>ที่มา: {source_label}</span>",
                 "style": {"fontFamily": "IBM Plex Sans Thai, sans-serif", "fontSize": "13px"}},
    ), height=560)
    legend = "".join(f'<span><span class="dot" style="background:{c}"></span>{g}</span>'
                     for g, c in [*GROUP_COLORS.items(), (OTHER_LABEL, OTHER_COLOR)])
    st.markdown(f'<div class="legend">{legend}</div>', unsafe_allow_html=True)
    st.caption(f"แสดง {len(geo):,} จุด · เหตุการณ์จาก ReliefWeb ใช้ตำแหน่งกึ่งกลางประเทศ")

# ---------- แท็บ: รายการเหตุการณ์ ----------
with tab_table:
    st.markdown("#### รายการเหตุการณ์")
    q = st.text_input("ค้นหาชื่อเหตุการณ์หรือประเทศ", placeholder="เช่น Japan, Philippines, Wildfire")
    table = events
    if q:
        mask = (events["event_name"].fillna("").str.contains(q, case=False, regex=False)
                | events["country"].fillna("").str.contains(q, case=False, regex=False))
        table = events[mask]
    st.dataframe(
        pd.DataFrame({
            "วันเวลา (เวลาไทย)": table["time_th"].dt.tz_localize(None),
            "ประเภท": table["ประเภท"],
            "ชื่อ/ตำแหน่ง": table["event_name"],
            "ประเทศ": table["country"],
            "ขนาด": table["magnitude"],
            "หน่วย": table["magnitude_unit"],
            "ระดับเตือนภัย": table["severity"].map(lambda s: SEVERITY_TH.get(s, "-") if s else "-"),
            "แหล่งข้อมูล": table["แหล่งข้อมูล"],
            "ละติจูด": table["latitude"], "ลองจิจูด": table["longitude"],
            "ลิงก์ต้นทาง": table["source_url"],
            "ดึงข้อมูลเมื่อ": table["fetched_at"].map(thai_dt),
        }),
        use_container_width=True, hide_index=True, height=520,
        column_config={
            "วันเวลา (เวลาไทย)": st.column_config.DatetimeColumn(format="DD/MM/YYYY HH:mm"),
            "ขนาด": st.column_config.NumberColumn(format="%.1f"),
            "ละติจูด": st.column_config.NumberColumn(format="%.2f"),
            "ลองจิจูด": st.column_config.NumberColumn(format="%.2f"),
            "ลิงก์ต้นทาง": st.column_config.LinkColumn(display_text="เปิดดู ↗"),
        },
    )
    st.caption(f"{len(table):,} รายการ · คลิกหัวคอลัมน์เพื่อเรียงลำดับ · "
               "ระดับเตือนภัยมีเฉพาะ USGS และ GDACS")

# ---------- แท็บ: แหล่งข้อมูลและสถานะระบบ ----------
with tab_system:
    runs = read_sql("""
        SELECT dag_run_id, source_name, status, records_extracted, records_loaded,
               records_quarantined, message, finished_at
        FROM pipeline_runs
        WHERE dag_run_id = (SELECT dag_run_id FROM pipeline_runs ORDER BY finished_at DESC LIMIT 1)
    """)
    st.markdown("#### สถานะการดึงข้อมูลรอบล่าสุด")
    if runs.empty:
        st.info("ยังไม่มีประวัติการรัน pipeline")
    else:
        overall = runs[runs["source_name"] == "__overall__"].iloc[0]
        icon, label = STATUS_TH.get(overall["status"], ("ℹ️", overall["status"]))
        st.markdown(f"{icon} **{label}** — รอบ `{overall['dag_run_id']}` เสร็จเมื่อ {thai_dt(overall['finished_at'])}")
        per_source = runs[runs["source_name"] != "__overall__"].sort_values("source_name")
        cols = st.columns(3)
        for i, (_, r) in enumerate(per_source.iterrows()):
            s_icon, s_label = STATUS_TH.get(r["status"], ("ℹ️", r["status"]))
            note = r["message"] or ""
            if r["status"] == "skipped" and "visit window" in note:
                note = "นอกช่วงเวลาที่ GDACS อนุญาต (11:00–13:45 น.) — รอบอัตโนมัติ 11:30 น. จะดึงตามปกติ"
            elif r["status"] == "skipped" and "APPNAME" in note:
                note = "รอ appname ที่ได้รับอนุมัติจาก ReliefWeb"
            elif r["status"] == "success":
                note = f"ดึงมา {r['records_extracted']:,} · โหลดเข้า {r['records_loaded']:,} · " \
                       f"ไม่ผ่านตรวจสอบ {r['records_quarantined']:,}"
            full = SOURCE_TH.get(r["source_name"], r["source_name"])
            method = "Web Scraping" if "Scraping" in full else "API"
            cols[i % 3].markdown(f"""<div class="src-card">
                <div class="name">{s_icon} {SOURCE_SHORT.get(r['source_name'], r['source_name'])}
                  <span class="meta">· {method}</span></div>
                <div class="meta"><b>{s_label}</b> — {note}</div></div>""", unsafe_allow_html=True)

        quality = read_sql("""
            SELECT check_name, passed, observed_value FROM data_quality_results
            WHERE dag_run_id = %(r)s ORDER BY check_name
        """, {"r": overall["dag_run_id"]})
        if not quality.empty:
            st.markdown(f"#### ผลตรวจคุณภาพข้อมูล ({int(quality['passed'].sum())}/{len(quality)} ผ่าน)")
            st.dataframe(pd.DataFrame({
                "ผล": quality["passed"].map(lambda p: "✅ ผ่าน" if p else "❌ ไม่ผ่าน"),
                "รายการตรวจ": quality["check_name"].map(lambda c: CHECK_TH.get(c, c)),
                "ค่าที่พบ": quality["observed_value"],
            }), hide_index=True, use_container_width=True)

    st.markdown("#### ข้อมูลในฐานข้อมูลแยกตามแหล่ง")
    src = read_sql("""
        SELECT source_name, COUNT(*) AS rows_stored,
               COUNT(*) FILTER (WHERE duplicate_of IS NULL) AS unique_events,
               MIN(event_time) AS earliest, MAX(event_time) AS latest, MAX(fetched_at) AS fetched
        FROM disaster_events GROUP BY source_name ORDER BY rows_stored DESC
    """)
    st.dataframe(pd.DataFrame({
        "แหล่งข้อมูล": src["source_name"].map(lambda s: SOURCE_TH.get(s, s)),
        "จำนวนที่เก็บ": src["rows_stored"],
        "ไม่นับรายการซ้ำ": src["unique_events"],
        "เหตุการณ์เก่าสุด": src["earliest"].map(lambda v: thai_dt(v, False)),
        "เหตุการณ์ล่าสุด": src["latest"].map(lambda v: thai_dt(v, False)),
        "ดึงข้อมูลล่าสุด": src["fetched"].map(thai_dt),
    }), hide_index=True, use_container_width=True)
    st.caption(f"เก็บทั้งหมด {int(totals['all_rows']):,} แถว · ซ้ำข้ามแหล่ง "
               f"{int(totals['all_rows'] - totals['canonical']):,} แถว (เก็บไว้แต่ไม่นับซ้ำ) · "
               f"ข้อมูลที่ไม่ผ่านการตรวจสอบถูกแยกไว้ {int(totals['quarantined']):,} แถว พร้อมเหตุผล")

    history = read_sql("""
        SELECT dag_run_id, status, records_loaded, finished_at
        FROM pipeline_runs WHERE source_name = '__overall__' ORDER BY finished_at DESC LIMIT 10
    """)
    with st.expander("ประวัติการรัน 10 รอบล่าสุด"):
        st.dataframe(pd.DataFrame({
            "รอบ": history["dag_run_id"],
            "สถานะ": history["status"].map(lambda s: " ".join(STATUS_TH.get(s, ("", s)))),
            "จำนวนที่โหลด": history["records_loaded"],
            "เสร็จเมื่อ": history["finished_at"].map(thai_dt),
        }), hide_index=True, use_container_width=True)

st.divider()
st.caption("ที่มาของข้อมูล: USGS Earthquake Hazards Program · GDACS (EC JRC / UN OCHA) · NASA EONET · "
           "GeoNet (GNS Science, CC BY 4.0) · ReliefWeb (UN OCHA) · PHIVOLCS (DOST ฟิลิปปินส์) · "
           "เวลาทั้งหมดแสดงเป็นเวลาประเทศไทย (UTC+7) ปี พ.ศ.")

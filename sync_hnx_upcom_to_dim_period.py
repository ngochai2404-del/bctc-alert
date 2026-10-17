import os
import sys
import json
import re
import time
import sqlite3
from datetime import datetime
import pytz

sys.stdout.reconfigure(encoding='utf-8')

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "bctc_alert.db")
CHECKPOINT_FILE = os.path.join(BASE_DIR, "october_2026_hnx_upcom_checkpoint.json")

print("=" * 70)
print("🚀 ĐỒNG BỘ CÁC BẢN CÔNG BỐ BCTC THÁNG 10/2026 (HNX & UPCOM) VÀO dim_period")
print("=" * 70)

if not os.path.exists(CHECKPOINT_FILE):
    print(f"❌ Không tìm thấy file checkpoint: {CHECKPOINT_FILE}")
    sys.exit(1)

with open(CHECKPOINT_FILE, "r", encoding="utf-8") as f:
    disclosures = json.load(f)

print(f"📄 Đã đọc {len(disclosures)} bài công bố BCTC từ file checkpoint.")

conn = sqlite3.connect(DB_PATH)
cur = conn.cursor()

vn_tz = pytz.timezone('Asia/Ho_Chi_Minh')
now_str = datetime.now(vn_tz).strftime('%Y-%m-%d %H:%M:%S')

count_inserted_files = 0
count_updated = 0
inserted_tickers = set()

for it in disclosures:
    ticker = str(it.get('ticker', '')).strip().upper()
    exchange = str(it.get('exchange', 'HNX')).strip()
    title = str(it.get('title', '')).strip()
    date_str = str(it.get('date_str', '')).strip()
    art_id = it.get('art_id')
    raw_url = it.get('raw_url', '')
    files = it.get('files', [])

    # Phân tích ngày giờ
    pub_date = ""
    pub_time = ""
    created_ts = int(time.time())
    try:
        # Hỗ trợ dạng: "16/10/2026 18:21"
        if " " in date_str:
            parts = date_str.split(" ")
            pub_date = parts[0]
            pub_time = parts[1] + (":00" if len(parts[1].split(":")) == 2 else "")
            dt = datetime.strptime(f"{pub_date} {pub_time}", "%d/%m/%Y %H:%M:%S")
            dt_vn = vn_tz.localize(dt)
            created_ts = int(dt_vn.timestamp())
        else:
            pub_date = date_str
    except Exception:
        pass

    # Xác định năm và kỳ báo cáo
    year_period = 2026
    m_year = re.search(r'\b(202[4-6])\b', title)
    if m_year:
        year_period = int(m_year.group(1))

    title_lower = title.lower()
    if any(k in title_lower for k in ['quý 3', 'q3', 'quý iii', '9 tháng']):
        report_term_id = 4
        term_name = f"Quý 3/{year_period}"
    elif any(k in title_lower for k in ['bán niên', '6 tháng', 'quý 2', 'q2']):
        report_term_id = 3
        term_name = f"Bán niên {year_period}"
    elif any(k in title_lower for k in ['quý 1', 'q1', 'quý i']):
        report_term_id = 2
        term_name = f"Quý 1/{year_period}"
    elif any(k in title_lower for k in ['năm ']):
        report_term_id = 1
        term_name = f"Năm {year_period}"
    else:
        report_term_id = 4
        term_name = f"Quý 3/{year_period}"

    audit_status = "Đã kiểm toán" if any(k in title_lower for k in ['kiểm toán', 'soát xét', 'audited']) else "Chưa kiểm toán"

    # Nếu có danh sách file PDF đính kèm
    if files:
        for idx, f in enumerate(files, 1):
            file_name = f.get('name', '')
            pdf_url = f.get('url', '')
            fn_lower = file_name.lower()

            is_united = 1 if any(k in fn_lower or k in title_lower for k in ['hợp nhất', 'hopnhat', 'consolidated', '_hn_', 'me_va_con']) else 0
            united_name = "Hợp nhất" if is_united == 1 else "Riêng"

            has_exp = 1 if any(k in fn_lower or k in title_lower for k in ['giải trình', 'giai_trinh', 'explanation', 'gt_']) else 0
            has_bctc = 1 if any(k in fn_lower or k in title_lower for k in ['báo cáo tài chính', 'bctc', 'financial', 'fs']) else 0

            # Tạo period_id duy nhất cho từng file
            period_id = f"{ticker}_{year_period}_T{report_term_id}_{created_ts}_{idx}"

            cur.execute("""
                INSERT INTO dim_period (
                    period_id, ticker, exchange, year_period, report_term_id, term_name,
                    is_united, united_name, audit_status, has_explanation, has_bctc,
                    source, published_date, published_time, created_timestamp,
                    file_name, pdf_url, hose_news_id, raw_url, status, updated_at
                ) VALUES (
                    ?, ?, ?, ?, ?, ?,
                    ?, ?, ?, ?, ?,
                    ?, ?, ?, ?,
                    ?, ?, ?, ?, 'COMPLETED', ?
                )
                ON CONFLICT(period_id) DO UPDATE SET
                    file_name = excluded.file_name,
                    pdf_url = excluded.pdf_url,
                    updated_at = excluded.updated_at
            """, (
                period_id, ticker, exchange, year_period, report_term_id, term_name,
                is_united, united_name, audit_status, has_exp, has_bctc,
                exchange, pub_date, pub_time, created_ts,
                file_name, pdf_url, art_id, raw_url, now_str
            ))
            count_inserted_files += 1
            inserted_tickers.add(ticker)
    else:
        # Nếu bài viết không có file tải kèm trực tiếp, lưu 1 bản ghi tổng hợp
        period_id = f"{ticker}_{year_period}_T{report_term_id}_{created_ts}_1"
        cur.execute("""
            INSERT INTO dim_period (
                period_id, ticker, exchange, year_period, report_term_id, term_name,
                is_united, united_name, audit_status, has_explanation, has_bctc,
                source, published_date, published_time, created_timestamp,
                file_name, pdf_url, hose_news_id, raw_url, status, updated_at
            ) VALUES (
                ?, ?, ?, ?, ?, ?,
                0, 'Riêng', ?, 0, 1,
                ?, ?, ?, ?,
                ?, '', ?, ?, 'COMPLETED', ?
            )
            ON CONFLICT(period_id) DO UPDATE SET
                updated_at = excluded.updated_at
        """, (
            period_id, ticker, exchange, year_period, report_term_id, term_name,
            audit_status, exchange, pub_date, pub_time, created_ts,
            title, art_id, raw_url, now_str
        ))
        count_inserted_files += 1
        inserted_tickers.add(ticker)

conn.commit()

print(f"\n✅ Đã đồng bộ thành công:")
print(f"   - Số file BCTC & Giải trình được nạp: {count_inserted_files} files")
print(f"   - Số doanh nghiệp HNX & UPCoM có BCTC tháng 10/2026: {len(inserted_tickers)} doanh nghiệp")

# Thống kê tổng hợp bảng dim_period sau khi nạp
cur.execute("""
    SELECT exchange,
           COUNT(*) as total_files,
           COUNT(DISTINCT ticker) as distinct_tickers,
           SUM(has_explanation) as count_exp,
           SUM(is_united) as count_united
    FROM dim_period
    GROUP BY exchange
    ORDER BY exchange
""")
stats = cur.fetchall()

print("\n" + "=" * 70)
print("📊 THỐNG KÊ TỔNG THỂ BẢNG dim_period (THÁNG 10/2026) HIỆN TẠI:")
print("=" * 70)
print(f"{'SÀN':<8} | {'TỔNG FILE':<12} | {'SỐ MÃ ĐÃ CÓ BCTC':<18} | {'FILE GIẢI TRÌNH':<18} | {'BCTC HỢP NHẤT':<15}")
print("-" * 75)
tot_files = 0
tot_tickers = 0
for ex, n_files, n_tickers, n_exp, n_uni in stats:
    tot_files += n_files
    tot_tickers += n_tickers
    print(f"{ex:<8} | {n_files:<12} | {n_tickers:<18} | {n_exp or 0:<18} | {n_uni or 0:<15}")
print("-" * 75)
print(f"{'TỔNG':<8} | {tot_files:<12} | {tot_tickers:<18}")
print("=" * 70)

# Mẫu bản ghi thực tế
print("\n🔍 MẪU DỮ LIỆU BỔ SUNG ĐẠI DIỆN HNX & UPCOM:")
cur.execute("""
    SELECT ticker, exchange, term_name, published_date, published_time, file_name, united_name, has_explanation
    FROM dim_period
    WHERE exchange IN ('HNX', 'UPCoM')
    ORDER BY created_timestamp DESC
    LIMIT 6
""")
for r in cur.fetchall():
    exp_str = "[CÓ GIẢI TRÌNH]" if r[7] else ""
    print(f" • [{r[1]}] {r[0]:<4} - {r[2]} ({r[3]} {r[4]}) | Loại: {r[6]} {exp_str}")
    print(f"     File: {r[5][:80]}")

# Kiểm tra toàn vẹn khóa ngoại
cur.execute("PRAGMA foreign_key_check")
fk_errors = cur.fetchall()
print(f"\nKiểm tra toàn vẹn khóa ngoại (FK): {len(fk_errors)} lỗi.")

conn.close()

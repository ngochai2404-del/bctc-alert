import os
import sys
import json
import re
import sqlite3
import requests
from datetime import datetime
import pytz
from concurrent.futures import ThreadPoolExecutor

sys.stdout.reconfigure(encoding='utf-8')

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "bctc_alert.db")
HOSE_STOCKS_FILE = os.path.join(BASE_DIR, "hose_stocks.json")

vn_tz = pytz.timezone('Asia/Ho_Chi_Minh')

# Mốc thời gian: Từ 01/10/2026 00:00:00 đến 17/10/2026 23:59:59 (Giờ VN)
START_TS = int(vn_tz.localize(datetime(2026, 10, 1, 0, 0, 0)).timestamp())
END_TS = int(vn_tz.localize(datetime(2026, 10, 17, 23, 59, 59)).timestamp())

print("=" * 75)
print("🚀 ĐỒNG BỘ dim_period: CHỈ GHI NHẬN BÁO CÁO TRONG THÁNG 10/2026 (01/10 - 17/10)")
print(f"⏰ Khoảng thời gian: 01/10/2026 00:00:00 ({START_TS}) -> 17/10/2026 23:59:59 ({END_TS})")
print("=" * 75)

conn = sqlite3.connect(DB_PATH)
cur = conn.cursor()

# 1. Tái tạo bảng dim_period chuẩn xác (period_id là PRIMARY KEY duy nhất)
cur.execute("DROP TABLE IF EXISTS dim_period")
cur.execute("""
CREATE TABLE dim_period (
    period_id TEXT PRIMARY KEY,
    ticker TEXT NOT NULL,
    exchange TEXT DEFAULT 'HOSE',
    year_period INTEGER NOT NULL,
    report_term_id INTEGER NOT NULL,
    term_name TEXT NOT NULL,
    is_united INTEGER DEFAULT 0,
    united_name TEXT DEFAULT 'Riêng',
    audit_status TEXT DEFAULT 'Chưa kiểm toán',
    has_explanation INTEGER DEFAULT 0,
    has_bctc INTEGER DEFAULT 1,
    source TEXT DEFAULT 'HOSE',
    published_date TEXT,
    published_time TEXT,
    created_timestamp INTEGER,
    file_name TEXT,
    pdf_url TEXT,
    hose_news_id INTEGER,
    raw_url TEXT,
    status TEXT DEFAULT 'COMPLETED',
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (ticker) REFERENCES dim_company(ticker)
)
""")
cur.execute("CREATE INDEX IF NOT EXISTS idx_period_ticker ON dim_period(ticker, year_period, report_term_id)")
conn.commit()
print("✅ Đã thiết lập cấu trúc bảng 'dim_period' hoàn toàn mới, sẵn sàng nạp dữ liệu.")

# 2. Quét toàn bộ 406 mã HOSE từ kho Mediafiles BCTC của HSX
with open(HOSE_STOCKS_FILE, 'r', encoding='utf-8') as f:
    hose_stocks = json.load(f)

print(f"\n📡 Đang quét toàn bộ {len(hose_stocks)} doanh nghiệp HOSE (đa luồng)...")
headers = {'User-Agent': 'Mozilla/5.0'}

def scan_october_reports(item):
    ticker, info = item
    hid = info.get('id')
    if not hid:
        return []
    
    matched = []
    try:
        url = f"https://api.hsx.vn/m/api/v1/1/mediafiles/5/{hid}?pageIndex=1&pageSize=10"
        r = requests.get(url, headers=headers, timeout=6)
        if r.status_code == 200:
            files = r.json().get('data', {}).get('list', [])
            for f in files:
                f_cdate = f.get('createdDate')
                if not f_cdate:
                    continue
                
                # CHỈ LẤY CÁC FILE ĐƯỢC TẠO TỪ 01/10/2026 ĐẾN 17/10/2026
                if START_TS <= f_cdate <= END_TS:
                    fn = f.get('fileName', '')
                    fn_lower = fn.lower()
                    tm = str(f.get('time', ''))
                    
                    dt = datetime.fromtimestamp(f_cdate, tz=vn_tz)
                    d_date = dt.strftime('%d/%m/%Y')
                    d_time = dt.strftime('%H:%M:%S')
                    
                    # Xác định kỳ báo cáo
                    if '03.2026' in tm or 'q3' in fn_lower or 'quý 3' in fn_lower or '9 tháng' in fn_lower:
                        year = 2026
                        term_id = 3
                        term_name = "Quý 3/2026"
                    elif '02.2026' in tm or 'q2' in fn_lower or 'quý 2' in fn_lower or 'bán niên' in fn_lower:
                        year = 2026
                        term_id = 2
                        term_name = "Bán niên 2026"
                    elif '01.2026' in tm or 'q1' in fn_lower or 'quý 1' in fn_lower:
                        year = 2026
                        term_id = 1
                        term_name = "Quý 1/2026"
                    elif '2025' in tm or 'năm 2025' in fn_lower:
                        year = 2025
                        term_id = 5
                        term_name = "Năm 2025"
                    else:
                        year = 2026
                        term_id = 3
                        term_name = "Quý 3/2026"
                    
                    # Xác định hợp nhất / công ty mẹ
                    is_united = 1 if ('hợp nhất' in fn_lower or 'hop nhat' in fn_lower or 'hn' in fn_lower) else (0 if ('mẹ' in fn_lower or 'me' in fn_lower or 'riêng' in fn_lower) else 1)
                    united_name = 'Hợp nhất' if is_united else 'Công ty mẹ'
                    
                    # Cờ giải trình
                    has_exp = 1 if any(k in fn_lower for k in ['giải trình', 'giai trinh', 'lợi nhuận', 'loi nhuan', 'chênh lệch', 'chenh lech']) else 0
                    
                    # Lấy hose_news_id nếu có từ filePath
                    f_path = f.get('filePath', '')
                    m_nid = re.search(r'UploadDocuments/(\d+)/', f_path)
                    news_id = int(m_nid.group(1)) if m_nid else None
                    pdf_link = f_path.replace("~", "https://staticfile.hsx.vn") if f_path else ""
                    
                    p_id = f"{ticker}_{year}_T{term_id}_{f_cdate}"
                    
                    matched.append({
                        'period_id': p_id,
                        'ticker': ticker,
                        'exchange': 'HOSE',
                        'year_period': year,
                        'report_term_id': term_id,
                        'term_name': term_name,
                        'is_united': is_united,
                        'united_name': united_name,
                        'audit_status': 'Chưa kiểm toán',
                        'has_explanation': has_exp,
                        'has_bctc': 1,
                        'source': 'HOSE',
                        'published_date': d_date,
                        'published_time': d_time,
                        'created_timestamp': f_cdate,
                        'file_name': fn,
                        'pdf_url': pdf_link,
                        'hose_news_id': news_id,
                        'raw_url': f"https://www.hsx.vn/vi/quan-ly-niem-yet/co-phieu/{ticker}/{hid}",
                        'status': 'COMPLETED'
                    })
    except Exception:
        pass
    return matched

all_oct_reports = []
with ThreadPoolExecutor(max_workers=20) as executor:
    results = executor.map(scan_october_reports, hose_stocks.items())
    for reports in results:
        all_oct_reports.extend(reports)

print(f"📦 Đã quét xong 406 mã: Tìm thấy {len(all_oct_reports)} tệp BCTC công bố từ 01/10/2026 đến 17/10/2026.")

# 3. Nạp vào dim_period
for rec in all_oct_reports:
    cur.execute("""
    INSERT OR REPLACE INTO dim_period (
        period_id, ticker, exchange, year_period, report_term_id, term_name,
        is_united, united_name, audit_status, has_explanation, has_bctc, source,
        published_date, published_time, created_timestamp, file_name, pdf_url,
        hose_news_id, raw_url, status, updated_at
    ) VALUES (
        :period_id, :ticker, :exchange, :year_period, :report_term_id, :term_name,
        :is_united, :united_name, :audit_status, :has_explanation, :has_bctc, :source,
        :published_date, :published_time, :created_timestamp, :file_name, :pdf_url,
        :hose_news_id, :raw_url, :status, CURRENT_TIMESTAMP
    )
    """, rec)

conn.commit()

# 4. Thống kê và hiển thị kết quả
cur.execute("SELECT count(*), count(DISTINCT ticker) FROM dim_period")
tot_rows, tot_tickers = cur.fetchone()

print("\n" + "=" * 75)
print(f"🎯 KẾT QUẢ CUỐI CÙNG TRONG BẢNG 'dim_period' (CHỈ TỪ 01/10/2026 ĐẾN 17/10/2026):")
print(f"   • Tổng số tệp BCTC ghi nhận: {tot_rows} bản ghi")
print(f"   • Tổng số Doanh nghiệp HOSE đã có BCTC: {tot_tickers} / 406 doanh nghiệp")
print("=" * 75)

cur.execute("""
    SELECT p.ticker, c.company_name, p.term_name, p.united_name, 
           p.published_date, p.published_time, p.has_explanation, p.file_name, p.pdf_url
    FROM dim_period p
    LEFT JOIN dim_company c ON p.ticker = c.ticker
    ORDER BY p.created_timestamp DESC
""")
rows = cur.fetchall()

print("\n📋 DANH SÁCH CHI TIẾT CÁC DOANH NGHIỆP CÓ BCTC TRONG THÁNG 10/2026:")
for idx, r in enumerate(rows, 1):
    exp_badge = "🔴 [Có giải trình LN]" if r[6] == 1 else "🟢 [BCTC]"
    cname = r[1] if r[1] else f"CTCP {r[0]}"
    print(f"{idx:>2}. {r[0]:<4} - {cname:<42} | {r[2]} ({r[3]}) | {r[4]} {r[5]} {exp_badge}")
    print(f"    📄 File: {r[7]}")
    print(f"    🔗 Link: {r[8]}\n")

conn.close()
print("✅ Hoàn tất toàn bộ quy trình lọc và ghi nhận vào dim_period!")

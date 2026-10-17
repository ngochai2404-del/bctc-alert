import os
import sys
import json
import sqlite3
import requests
from datetime import datetime
import pytz

sys.stdout.reconfigure(encoding='utf-8')

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "bctc_alert.db")

print("=" * 70)
print("🚀 BẮT ĐẦU CÀO DANH SÁCH DOANH NGHIỆP TỪ HOSE VÀ LƯU VÀO dim_company")
print("=" * 70)

# 1. Khởi tạo bảng dim_company trong bctc_alert.db
conn = sqlite3.connect(DB_PATH)
cur = conn.cursor()

cur.execute("""
CREATE TABLE IF NOT EXISTS dim_company (
    ticker TEXT PRIMARY KEY,
    company_name TEXT NOT NULL,
    exchange TEXT DEFAULT 'HOSE',
    hose_id INTEGER,
    brief_name TEXT,
    address TEXT,
    phone TEXT,
    fax TEXT,
    website TEXT,
    director TEXT,
    spokesman TEXT,
    charter_capital REAL,
    isin_code TEXT,
    bloomberg_code TEXT,
    par_value REAL,
    listing_volume TEXT,
    listing_value TEXT,
    outstanding_volume TEXT,
    listing_date TEXT,
    reg_date TEXT,
    foreign_owned_ratio TEXT,
    state_owned_ratio TEXT,
    raw_json TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
)
""")
conn.commit()

# 2. Gọi API HOSE lấy toàn bộ danh sách cổ phiếu niêm yết
url = "https://api.hsx.vn/l/api/v1/1/securities/stock?pageIndex=1&pageSize=1000"
headers = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
}

print(f"📡 Đang kết nối tới API HOSE: {url} ...")
r = requests.get(url, headers=headers, timeout=15)
if r.status_code != 200:
    print(f"❌ Lỗi kết nối HOSE API: Mã HTTP {r.status_code}")
    sys.exit(1)

raw_data = r.json()
stock_list = raw_data.get('data', {}).get('list', [])
print(f"✅ Đã tải về thành công {len(stock_list)} doanh nghiệp niêm yết từ HOSE.")

# 3. Ghi nhận dữ liệu vào dim_company
vn_tz = pytz.timezone('Asia/Ho_Chi_Minh')
inserted_count = 0
updated_count = 0

for item in stock_list:
    ticker = str(item.get('code', '')).strip().upper()
    if not ticker:
        continue
        
    company_name = str(item.get('name', '')).strip()
    hose_id = item.get('id')
    brief_name = item.get('brief')
    address = item.get('address')
    phone = item.get('phone')
    fax = item.get('fax')
    website = item.get('webUrl')
    director = item.get('director')
    spokesman = item.get('spokesman')
    charter_capital = item.get('capital')
    isin_code = item.get('isin')
    bloomberg_code = item.get('bloomberg')
    par_value = item.get('parValue')
    listing_volume = item.get('listingVolume')
    listing_value = item.get('listingValue')
    outstanding_volume = item.get('outStanding')
    foreign_owned_ratio = item.get('foreignOwnedRatio')
    state_owned_ratio = item.get('stateOwnedRatio')
    
    # Chuyển đổi timestamp listDate & regDate
    list_date_str = ""
    list_ts = item.get('listDate')
    if list_ts and list_ts > 0:
        try:
            list_date_str = datetime.fromtimestamp(list_ts, tz=vn_tz).strftime('%d/%m/%Y')
        except Exception:
            pass

    reg_date_str = ""
    reg_ts = item.get('regDate')
    if reg_ts and reg_ts > 0:
        try:
            reg_date_str = datetime.fromtimestamp(reg_ts, tz=vn_tz).strftime('%d/%m/%Y')
        except Exception:
            pass
            
    raw_json = json.dumps(item, ensure_ascii=False)
    
    cur.execute("""
        INSERT INTO dim_company (
            ticker, company_name, exchange, hose_id, brief_name, address,
            phone, fax, website, director, spokesman, charter_capital,
            isin_code, bloomberg_code, par_value, listing_volume, listing_value,
            outstanding_volume, listing_date, reg_date, foreign_owned_ratio,
            state_owned_ratio, raw_json, updated_at
        ) VALUES (
            ?, ?, 'HOSE', ?, ?, ?,
            ?, ?, ?, ?, ?, ?,
            ?, ?, ?, ?, ?,
            ?, ?, ?, ?,
            ?, ?, CURRENT_TIMESTAMP
        )
        ON CONFLICT(ticker) DO UPDATE SET
            company_name = excluded.company_name,
            exchange = 'HOSE',
            hose_id = excluded.hose_id,
            brief_name = excluded.brief_name,
            address = excluded.address,
            phone = excluded.phone,
            fax = excluded.fax,
            website = excluded.website,
            director = excluded.director,
            spokesman = excluded.spokesman,
            charter_capital = excluded.charter_capital,
            isin_code = excluded.isin_code,
            bloomberg_code = excluded.bloomberg_code,
            par_value = excluded.par_value,
            listing_volume = excluded.listing_volume,
            listing_value = excluded.listing_value,
            outstanding_volume = excluded.outstanding_volume,
            listing_date = excluded.listing_date,
            reg_date = excluded.reg_date,
            foreign_owned_ratio = excluded.foreign_owned_ratio,
            state_owned_ratio = excluded.state_owned_ratio,
            raw_json = excluded.raw_json,
            updated_at = CURRENT_TIMESTAMP
    """, (
        ticker, company_name, hose_id, brief_name, address,
        phone, fax, website, director, spokesman, charter_capital,
        isin_code, bloomberg_code, par_value, listing_volume, listing_value,
        outstanding_volume, list_date_str, reg_date_str, foreign_owned_ratio,
        state_owned_ratio, raw_json
    ))
    inserted_count += 1

conn.commit()

# 4. Kiểm tra đối soát kết quả
cur.execute("SELECT count(*), exchange FROM dim_company GROUP BY exchange")
stats = cur.fetchall()
print(f"🎉 Đã nạp thành công {inserted_count} doanh nghiệp vào bảng 'dim_company'!")
for count, ex in stats:
    print(f"   📊 Sàn {ex}: {count} doanh nghiệp")

# Xem thử 5 bản ghi mẫu bao gồm cả CLC
cur.execute("""
    SELECT ticker, company_name, exchange, hose_id, website, listing_volume, listing_date 
    FROM dim_company 
    WHERE ticker IN ('CLC', 'VNM', 'HPG', 'FPT', 'SSI')
    ORDER BY ticker
""")
sample_rows = cur.fetchall()
print("\n📋 Dữ liệu mẫu đã lưu trữ:")
for r in sample_rows:
    print(f"   • {r[0]}: {r[1]} | Sàn: {r[2]} | HOSE ID: {r[3]} | Web: {r[4]} | KLNY: {r[5]} | Ngày NY: {r[6]}")

conn.close()
print("\n✅ Hoàn tất toàn bộ quy trình!")

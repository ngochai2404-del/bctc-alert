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
print("🚀 THÊM CỘT 'id' VÀO SAU CỘT 'ticker' VÀ CẬP NHẬT CHO 1.171 MÃ")
print("=" * 70)

# 1. Lấy bảng mã ID của 406 công ty HOSE từ HOSE API (hoặc file cache)
hose_id_map = {}
try:
    print("📡 Đang tải bảng ID từ API HOSE...")
    url = "https://api.hsx.vn/l/api/v1/1/securities/stock?pageIndex=1&pageSize=1000"
    headers = {'User-Agent': 'Mozilla/5.0'}
    r = requests.get(url, headers=headers, timeout=10)
    if r.status_code == 200:
        raw_list = r.json().get('data', {}).get('list', [])
        for item in raw_list:
            code = str(item.get('code', '')).strip().upper()
            hid = item.get('id')
            if code and hid:
                hose_id_map[code] = hid
        print(f"✅ Đã tải được {len(hose_id_map)} ID từ API HOSE.")
except Exception as e:
    print(f"⚠️ Lỗi kết nối HOSE API: {e}. Sẽ dùng file cache...")

# Fallback nếu cần
if len(hose_id_map) < 400 and os.path.exists(os.path.join(BASE_DIR, "hose_stocks.json")):
    with open(os.path.join(BASE_DIR, "hose_stocks.json"), "r", encoding="utf-8") as f:
        cache = json.load(f)
        for code, info in cache.items():
            if code not in hose_id_map and 'id' in info:
                hose_id_map[code] = info['id']
    print(f"✅ Tổng ID HOSE sau khi bù cache: {len(hose_id_map)}")

# 2. Kết nối DB và thực hiện tái cấu trúc bảng
conn = sqlite3.connect(DB_PATH)
cur = conn.cursor()

cur.execute("PRAGMA foreign_keys = OFF")

# Tạo bảng dim_company_new với cột 'id' nằm ngay sau 'ticker'
cur.execute("""
CREATE TABLE dim_company_new (
    ticker TEXT PRIMARY KEY,
    id INTEGER,
    company_name TEXT NOT NULL,
    exchange TEXT NOT NULL,
    sector_name TEXT,
    is_quarterly_reporting INTEGER DEFAULT 1,
    listing_volume TEXT,
    outstanding_volume TEXT,
    listing_date TEXT,
    reg_date TEXT,
    foreign_owned_ratio TEXT,
    state_owned_ratio TEXT,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
)
""")

# 3. Lấy toàn bộ dữ liệu từ bảng cũ
cur.execute("""
    SELECT ticker, company_name, exchange, sector_name, is_quarterly_reporting,
           listing_volume, outstanding_volume, listing_date, reg_date,
           foreign_owned_ratio, state_owned_ratio, updated_at
    FROM dim_company
""")
rows = cur.fetchall()

vn_tz = pytz.timezone('Asia/Ho_Chi_Minh')
now_str = datetime.now(vn_tz).strftime('%Y-%m-%d %H:%M:%S')

count_with_id = 0
count_null_id = 0

for r in rows:
    ticker = r[0]
    comp_name = r[1]
    exchange = r[2]
    sector_name = r[3]
    is_q = r[4]
    listing_vol = r[5]
    out_vol = r[6]
    list_date = r[7]
    reg_date = r[8]
    for_ratio = r[9]
    state_ratio = r[10]
    updated_at = r[11]

    # Quy tắc: Ticker nào có id (HOSE) thì ghi nhận, không có (HNX, UPCoM) thì NULL
    comp_id = hose_id_map.get(ticker)
    if comp_id:
        count_with_id += 1
    else:
        comp_id = None
        count_null_id += 1

    cur.execute("""
        INSERT INTO dim_company_new (
            ticker, id, company_name, exchange, sector_name, is_quarterly_reporting,
            listing_volume, outstanding_volume, listing_date, reg_date,
            foreign_owned_ratio, state_owned_ratio, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        ticker, comp_id, comp_name, exchange, sector_name, is_q,
        listing_vol, out_vol, list_date, reg_date,
        for_ratio, state_ratio, updated_at
    ))

# 4. Tráo bảng
cur.execute("DROP TABLE dim_company")
cur.execute("ALTER TABLE dim_company_new RENAME TO dim_company")

# 5. Tạo indexes
cur.execute("CREATE INDEX IF NOT EXISTS idx_dim_company_exchange ON dim_company(exchange)")
cur.execute("CREATE INDEX IF NOT EXISTS idx_dim_company_id ON dim_company(id)")

cur.execute("PRAGMA foreign_keys = ON")
conn.commit()

print(f"\n✅ Đã chuyển đổi hoàn tất:")
print(f"   - Số doanh nghiệp có ID (HOSE): {count_with_id}")
print(f"   - Số doanh nghiệp không có ID (HNX / UPCoM -> NULL): {count_null_id}")
print(f"   - Tổng số doanh nghiệp: {count_with_id + count_null_id}")

# 6. Kiểm tra cấu trúc cột
cur.execute("PRAGMA table_info(dim_company)")
new_cols = cur.fetchall()

print("\n" + "=" * 70)
print(f"📋 CẤU TRÚC BẢNG dim_company HIỆN TẠI ({len(new_cols)} CỘT):")
print("=" * 70)
for idx, col_name, col_type, not_null, default_val, pk in new_cols:
    pk_str = " [PRIMARY KEY]" if pk else ""
    print(f"  {idx+1:>2}. {col_name:<25} {col_type:<10}{pk_str}")

# 7. Thống kê theo sàn
print("\n" + "=" * 70)
print("📊 THỐNG KÊ ID THEO SÀN GIAO DỊCH:")
print("=" * 70)
cur.execute("""
    SELECT exchange, 
           COUNT(*) as total, 
           COUNT(id) as count_id,
           SUM(CASE WHEN id IS NULL THEN 1 ELSE 0 END) as count_null
    FROM dim_company
    GROUP BY exchange
    ORDER BY COUNT(*) DESC
""")
for ex, tot, cid, cnull in cur.fetchall():
    print(f"  - Sàn {ex:<6}: Tổng {tot:>4} | Có ID: {cid:>4} | NULL: {cnull:>4}")

# 8. Xem thử dữ liệu mẫu đại diện
print("\n" + "=" * 70)
print("🔍 MẪU DỮ LIỆU ĐẠI DIỆN:")
print("=" * 70)
cur.execute("""
    SELECT ticker, id, company_name, exchange, sector_name
    FROM dim_company
    WHERE ticker IN ('CLC', 'VNM', 'HPG', 'SHS', 'IDC', 'ACV', 'MCH')
    ORDER BY exchange, ticker
""")
for r in cur.fetchall():
    id_display = str(r[1]) if r[1] is not None else "NULL"
    print(f"[{r[3]}] Ticker: {r[0]:<5} | ID: {id_display:<6} | Tên: {r[2]}")

# 9. Kiểm tra foreign keys với dim_period
cur.execute("PRAGMA foreign_key_check")
fk_errors = cur.fetchall()
print(f"\nKiểm tra toàn vẹn khóa ngoại (FK): {len(fk_errors)} lỗi.")

conn.close()

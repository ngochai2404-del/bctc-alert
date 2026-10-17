import os
import sys
import re
import sqlite3
from datetime import datetime
import pytz

sys.stdout.reconfigure(encoding='utf-8')

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "bctc_alert.db")

print("=" * 70)
print("🚀 BẮT ĐẦU CHUẨN HÓA SCHEMA VÀ CLEAN DỮ LIỆU BẢNG dim_company")
print("=" * 70)

def clean_int_volume(val):
    if val is None or val == "":
        return None
    digits = re.sub(r'[^\d]', '', str(val))
    return int(digits) if digits else None

def clean_ratio(val):
    if val is None or val == "":
        return None
    try:
        val_str = str(val).replace(',', '.').replace('%', '').strip()
        f_val = float(val_str)
        return round(f_val, 2)
    except (ValueError, TypeError):
        return None

def clean_date_iso(val):
    if not val:
        return None
    val_str = str(val).strip()
    # Nếu là timestamp
    if val_str.isdigit() and len(val_str) >= 9:
        try:
            vn_tz = pytz.timezone('Asia/Ho_Chi_Minh')
            return datetime.fromtimestamp(int(val_str), tz=vn_tz).strftime('%Y-%m-%d')
        except Exception:
            pass
    # Nếu là DD/MM/YYYY
    m = re.match(r'^(\d{1,2})/(\d{1,2})/(\d{4})$', val_str)
    if m:
        d, mo, y = m.groups()
        return f"{y}-{int(mo):02d}-{int(d):02d}"
    # Nếu đã là YYYY-MM-DD
    if re.match(r'^\d{4}-\d{2}-\d{2}$', val_str):
        return val_str
    return None

conn = sqlite3.connect(DB_PATH)
cur = conn.cursor()

# 1. Đọc dữ liệu hiện tại
cur.execute("""
    SELECT ticker, id, company_name, exchange, sector_name, is_quarterly_reporting,
           listing_volume, outstanding_volume, listing_date, reg_date,
           foreign_owned_ratio, state_owned_ratio, updated_at
    FROM dim_company
""")
rows = cur.fetchall()
print(f"📊 Đã tải {len(rows)} bản ghi hiện tại từ dim_company.")

# 2. Tạo bảng mới chuẩn hóa
cur.execute("PRAGMA foreign_keys = OFF")

cur.execute("DROP TABLE IF EXISTS dim_company_migrated")
cur.execute("""
CREATE TABLE dim_company_migrated (
    ticker TEXT PRIMARY KEY,
    id INTEGER,
    company_name TEXT NOT NULL,
    exchange TEXT NOT NULL,
    sector_name TEXT,
    is_quarterly_reporting INTEGER DEFAULT 1,
    listing_volume INTEGER,
    outstanding_volume INTEGER,
    first_trading_date TEXT,
    listing_date TEXT,
    reg_date TEXT,
    foreign_owned_ratio REAL,
    state_owned_ratio REAL,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
)
""")

cleaned_rows = []
for r in rows:
    ticker = r[0]
    comp_id = r[1]
    name = r[2]
    exchange = r[3]
    sector = r[4]
    is_q = 1 if r[5] in (1, '1', True) else 0
    list_vol = clean_int_volume(r[6])
    out_vol = clean_int_volume(r[7])
    list_d = clean_date_iso(r[8])
    reg_d = clean_date_iso(r[9])
    first_d = list_d or reg_d
    f_ratio = clean_ratio(r[10])
    s_ratio = clean_ratio(r[11])
    up_at = r[12]

    cleaned_rows.append((
        ticker, comp_id, name, exchange, sector, is_q,
        list_vol, out_vol, first_d, list_d, reg_d,
        f_ratio, s_ratio, up_at
    ))

cur.executemany("""
    INSERT INTO dim_company_migrated (
        ticker, id, company_name, exchange, sector_name, is_quarterly_reporting,
        listing_volume, outstanding_volume, first_trading_date, listing_date, reg_date,
        foreign_owned_ratio, state_owned_ratio, updated_at
    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
""", cleaned_rows)

# 3. Thay thế bảng cũ
cur.execute("DROP TABLE dim_company")
cur.execute("ALTER TABLE dim_company_migrated RENAME TO dim_company")

# 4. Tạo Indexes
cur.execute("CREATE INDEX IF NOT EXISTS idx_dim_company_exchange ON dim_company(exchange)")
cur.execute("CREATE INDEX IF NOT EXISTS idx_dim_company_reporting ON dim_company(is_quarterly_reporting)")
cur.execute("CREATE INDEX IF NOT EXISTS idx_dim_company_id ON dim_company(id)")
cur.execute("CREATE INDEX IF NOT EXISTS idx_dim_company_first_date ON dim_company(first_trading_date)")
cur.execute("CREATE INDEX IF NOT EXISTS idx_dim_company_out_vol ON dim_company(outstanding_volume)")

cur.execute("PRAGMA foreign_keys = ON")
conn.commit()

print("✅ Đã hoàn tất di chuyển dữ liệu sang Schema chuẩn mới!")

# 5. Kiểm tra kết quả
cur.execute("PRAGMA table_info(dim_company)")
cols = cur.fetchall()
print("\n" + "=" * 70)
print(f"📋 CẤU TRÚC BẢNG dim_company MỚI ({len(cols)} CỘT):")
print("=" * 70)
for idx, col_name, col_type, not_null, default_val, pk in cols:
    pk_str = " [PRIMARY KEY]" if pk else ""
    print(f"  {idx+1:>2}. {col_name:<25} {col_type:<10}{pk_str}")

# 6. Kiểm tra mẫu đại diện
print("\n" + "=" * 70)
print("🔍 KIỂM TRA MẪU DỮ LIỆU ĐẠI DIỆN:")
print("=" * 70)
cur.execute("""
    SELECT ticker, exchange, listing_volume, outstanding_volume, 
           first_trading_date, foreign_owned_ratio, state_owned_ratio
    FROM dim_company
    WHERE ticker IN ('VNM', 'CLC', 'SHS', 'ACV')
    ORDER BY exchange, ticker
""")
for r in cur.fetchall():
    print(f"[{r[1]}] {r[0]:<5} | KLNY: {r[2]} | KLLH: {r[3]} | Ngày đầu: {r[4]} | Room ngoại: {r[5]}% | Nhà nước: {r[6]}%")

# 7. Kiểm tra foreign key với dim_period
cur.execute("PRAGMA foreign_key_check")
fk_errs = cur.fetchall()
print(f"\nKiểm tra FK với dim_period: {len(fk_errs)} lỗi.")

conn.close()

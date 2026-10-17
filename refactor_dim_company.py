import os
import sys
import sqlite3

sys.stdout.reconfigure(encoding='utf-8')

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "bctc_alert.db")

print("=" * 70)
print("🛠️ TIẾN HÀNH TINH GỌN BẢNG dim_company TRONG bctc_alert.db")
print("=" * 70)

conn = sqlite3.connect(DB_PATH)
cur = conn.cursor()

# 1. Tắt foreign keys tạm thời để tái cấu trúc bảng an toàn
cur.execute("PRAGMA foreign_keys = OFF")

# 2. Tạo bảng tạm dim_company_new chỉ với 12 trường được chỉ định
cur.execute("""
CREATE TABLE dim_company_new (
    ticker TEXT PRIMARY KEY,
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

# 3. Chuyển toàn bộ dữ liệu từ dim_company cũ sang dim_company_new
cur.execute("""
INSERT INTO dim_company_new (
    ticker,
    company_name,
    exchange,
    sector_name,
    is_quarterly_reporting,
    listing_volume,
    outstanding_volume,
    listing_date,
    reg_date,
    foreign_owned_ratio,
    state_owned_ratio,
    updated_at
)
SELECT 
    ticker,
    company_name,
    exchange,
    sector_name,
    COALESCE(is_quarterly_reporting, 1),
    listing_volume,
    outstanding_volume,
    listing_date,
    reg_date,
    foreign_owned_ratio,
    state_owned_ratio,
    updated_at
FROM dim_company
""")

# 4. Xóa bảng cũ và đổi tên bảng mới
cur.execute("DROP TABLE dim_company")
cur.execute("ALTER TABLE dim_company_new RENAME TO dim_company")

# 5. Tạo index hỗ trợ tìm kiếm nhanh
cur.execute("CREATE INDEX IF NOT EXISTS idx_dim_company_exchange ON dim_company(exchange)")
cur.execute("CREATE INDEX IF NOT EXISTS idx_dim_company_reporting ON dim_company(is_quarterly_reporting)")

# 6. Bật lại foreign keys và commit
cur.execute("PRAGMA foreign_keys = ON")
conn.commit()

print("✅ Đã tái cấu trúc bảng 'dim_company' thành công!")

# 7. Kiểm tra lại cấu trúc bảng mới
cur.execute("PRAGMA table_info(dim_company)")
new_cols = cur.fetchall()

print("\n" + "=" * 70)
print(f"📋 CẤU TRÚC BẢNG dim_company HIỆN TẠI ({len(new_cols)} CỘT):")
print("=" * 70)
for idx, col_name, col_type, not_null, default_val, pk in new_cols:
    pk_str = " [PRIMARY KEY]" if pk else ""
    print(f"  {idx+1:>2}. {col_name:<25} {col_type:<10}{pk_str}")

# 8. Kiểm tra số lượng bản ghi
cur.execute("SELECT exchange, COUNT(*) FROM dim_company GROUP BY exchange ORDER BY COUNT(*) DESC")
stats = cur.fetchall()

print("\n" + "=" * 70)
print("📊 SỐ LƯỢNG DOANH NGHIỆP SAU KHI TINH GỌN:")
print("=" * 70)
total = 0
for ex, cnt in stats:
    total += cnt
    print(f"  - Sàn {ex:<6}: {cnt:>5} doanh nghiệp")
print(f"  -----------------------------")
print(f"  👉 TỔNG CỘNG: {total:>5} doanh nghiệp")

# 9. Xem thử dữ liệu mẫu
print("\n" + "=" * 70)
print("🔍 MẪU DỮ LIỆU ĐẠI DIỆN:")
print("=" * 70)
cur.execute("""
    SELECT ticker, company_name, exchange, sector_name, is_quarterly_reporting, 
           outstanding_volume, listing_date, foreign_owned_ratio, updated_at
    FROM dim_company
    WHERE ticker IN ('CLC', 'SHS', 'ACV')
    ORDER BY exchange, ticker
""")
for r in cur.fetchall():
    print(f"[{r[2]}] {r[0]} - {r[1]}")
    print(f"     Ngành: {r[3]} | Quý: {r[4]} | KL Lưu hành: {r[5]} | Ngày niêm yết: {r[6]} | Room ngoại: {r[7]}")
    print(f"     Cập nhật: {r[8]}")

conn.close()

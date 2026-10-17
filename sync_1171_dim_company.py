import os
import sys
import sqlite3
import pandas as pd
from datetime import datetime
import pytz

sys.stdout.reconfigure(encoding='utf-8')

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "bctc_alert.db")
CSV_PATH = os.path.join(BASE_DIR, "Danh_sach_DN_cong_bo_BCTC_Quy.csv")

print("=" * 70)
print("🚀 ĐỒNG BỘ 1.171 DOANH NGHIỆP CÔNG BỐ BCTC QUÝ VÀO dim_company")
print("=" * 70)

# 1. Đọc danh sách 1.171 doanh nghiệp từ CSV
if not os.path.exists(CSV_PATH):
    print(f"❌ Không tìm thấy file: {CSV_PATH}")
    sys.exit(1)

df_1171 = pd.read_csv(CSV_PATH)
print(f"📄 Đã đọc {len(df_1171)} doanh nghiệp từ file CSV:")
print(df_1171['exchange'].value_counts().to_string())

# 2. Kết nối CSDL và nâng cấp Schema dim_company (nếu cần)
conn = sqlite3.connect(DB_PATH)
cur = conn.cursor()

# Kiểm tra các cột hiện có
cur.execute("PRAGMA table_info(dim_company)")
existing_cols = [col[1] for col in cur.fetchall()]

new_cols = [
    ("sector_name", "TEXT"),
    ("industry_1", "TEXT"),
    ("industry_2", "TEXT"),
    ("industry_3", "TEXT"),
    ("is_quarterly_reporting", "INTEGER DEFAULT 1")
]

for col_name, col_type in new_cols:
    if col_name not in existing_cols:
        print(f"➕ Thêm cột mới: {col_name} ({col_type})")
        cur.execute(f"ALTER TABLE dim_company ADD COLUMN {col_name} {col_type}")

conn.commit()

# 3. Đồng bộ 1.171 doanh nghiệp
# - Với 406 HOSE đã có: cập nhật sector, industry, is_quarterly_reporting
# - Với HNX (299) và UPCoM (466): thêm mới nếu chưa có, hoặc cập nhật nếu đã có

vn_tz = pytz.timezone('Asia/Ho_Chi_Minh')
now_str = datetime.now(vn_tz).strftime('%Y-%m-%d %H:%M:%S')

count_inserted = 0
count_updated = 0

for _, row in df_1171.iterrows():
    ticker = str(row['ticker']).strip().upper()
    comp_name = str(row['company_name']).strip()
    exchange = str(row['exchange']).strip()
    sector_name = str(row['sector_name']).strip() if pd.notna(row['sector_name']) else None
    ind1 = str(row['industry_1']).strip() if pd.notna(row['industry_1']) else None
    ind2 = str(row['industry_2']).strip() if pd.notna(row['industry_2']) else None
    ind3 = str(row['industry_3']).strip() if pd.notna(row['industry_3']) else None
    shares = str(row['total_shares']).strip() if pd.notna(row['total_shares']) else None
    
    cur.execute("SELECT ticker, exchange, hose_id FROM dim_company WHERE ticker = ?", (ticker,))
    existing = cur.fetchone()
    
    if existing:
        # Cập nhật thông tin phân ngành và cờ báo cáo quý, giữ nguyên các thông tin riêng của HOSE
        cur.execute("""
            UPDATE dim_company
            SET sector_name = ?,
                industry_1 = ?,
                industry_2 = ?,
                industry_3 = ?,
                is_quarterly_reporting = 1,
                updated_at = ?
            WHERE ticker = ?
        """, (sector_name, ind1, ind2, ind3, now_str, ticker))
        count_updated += 1
    else:
        # Thêm mới DN HNX / UPCoM
        cur.execute("""
            INSERT INTO dim_company (
                ticker, company_name, exchange, outstanding_volume,
                sector_name, industry_1, industry_2, industry_3,
                is_quarterly_reporting, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 1, ?, ?)
        """, (
            ticker, comp_name, exchange, shares,
            sector_name, ind1, ind2, ind3,
            now_str, now_str
        ))
        count_inserted += 1

conn.commit()

print(f"\n✅ Đã hoàn tất đồng bộ:")
print(f"   - Số doanh nghiệp được thêm mới: {count_inserted}")
print(f"   - Số doanh nghiệp được cập nhật bổ sung ngành: {count_updated}")

# 4. Thống kê kiểm tra sau đồng bộ
cur.execute("""
    SELECT exchange, COUNT(*), SUM(is_quarterly_reporting)
    FROM dim_company
    GROUP BY exchange
    ORDER BY COUNT(*) DESC
""")
stats = cur.fetchall()

print("\n" + "=" * 70)
print("📊 THỐNG KÊ DOANH NGHIỆP TRONG BẢNG dim_company HIỆN TẠI:")
print("=" * 70)
print(f"{'SÀN':<12} | {'TỔNG DOANH NGHIỆP':<20} | {'BÁO CÁO THEO QUÝ':<20}")
print("-" * 60)
total_companies = 0
total_quarterly = 0
for ex, cnt, q_cnt in stats:
    total_companies += cnt
    total_quarterly += (q_cnt or 0)
    print(f"{ex:<12} | {cnt:<20} | {q_cnt:<20}")
print("-" * 60)
print(f"{'TỔNG CỘNG':<12} | {total_companies:<20} | {total_quarterly:<20}")
print("=" * 70)

# Mẫu 5 bản ghi ngẫu nhiên gồm cả 3 sàn
print("\n🔍 MẪU DỮ LIỆU ĐỒNG BỘ ĐẠI DIỆN 3 SÀN:")
cur.execute("""
    SELECT ticker, company_name, exchange, sector_name, industry_1, outstanding_volume, is_quarterly_reporting
    FROM dim_company
    WHERE ticker IN ('VNM', 'CLC', 'SHS', 'IDC', 'ACV', 'MCH')
    ORDER BY exchange, ticker
""")
sample_rows = cur.fetchall()
for r in sample_rows:
    print(f" • [{r[2]}] {r[0]} - {r[1]} | Ngành: {r[4]} | CP lưu hành: {r[5]} | CBTT Quý: {r[6]}")

conn.close()

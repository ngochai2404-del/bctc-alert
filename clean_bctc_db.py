import os
import sys
import sqlite3

sys.stdout.reconfigure(encoding='utf-8')

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "bctc_alert.db")

print("=" * 70)
print("🧹 DỌN DẸP CSDL bctc_alert.db (CHỈ GIỮ LẠI dim_company VÀ dim_period)")
print("=" * 70)

conn = sqlite3.connect(DB_PATH)
cur = conn.cursor()

# 1. Tìm tất cả các bảng hiện có
cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")
all_tables = [r[0] for r in cur.fetchall()]
print(f"Các bảng hiện tại trong DB: {all_tables}")

keep_tables = {'dim_company', 'dim_period'}
dropped_tables = []

for tbl in all_tables:
    if tbl not in keep_tables:
        print(f"🗑️ Đang xóa bảng: {tbl}")
        cur.execute(f"DROP TABLE IF EXISTS {tbl}")
        dropped_tables.append(tbl)

conn.commit()

# 2. Chạy VACUUM để thu hồi dung lượng đĩa
print("\n⚙️ Đang chạy VACUUM để tối ưu dung lượng...")
cur.execute("VACUUM")
conn.commit()

# 3. Kiểm tra lại các bảng còn lại
cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")
remaining_tables = [r[0] for r in cur.fetchall()]

print("\n" + "=" * 70)
print(f"✅ HOÀN TẤT! CÁC BẢNG DUY NHẤT CÒN LẠI TRONG bctc_alert.db:")
print("=" * 70)
for tbl in remaining_tables:
    cur.execute(f"SELECT COUNT(*) FROM {tbl}")
    cnt = cur.fetchone()[0]
    print(f"  • {tbl:<20}: {cnt:>6} bản ghi")

file_size_kb = os.path.getsize(DB_PATH) / 1024
print(f"\n📦 Dung lượng file bctc_alert.db hiện tại: {file_size_kb:.2f} KB")

conn.close()

import os
import sys
import json
import sqlite3
import requests
from bs4 import BeautifulSoup
from datetime import datetime
import pytz
import urllib3

sys.stdout.reconfigure(encoding='utf-8')
urllib3.disable_warnings()

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "bctc_alert.db")

print("=" * 70)
print("🚀 BẮT ĐẦU QUÉT VÀ CẬP NHẬT THÔNG TIN CHUẨN XÁC TỪ SỞ HNX CHO 765 MÃ HNX & UPCOM")
print("=" * 70)

headers = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
    'X-Requested-With': 'XMLHttpRequest'
}

# 1. Quét toàn bộ dữ liệu gốc từ HNX Niêm yết (299 mã)
hnx_data = {}
try:
    print("📡 Đang tải bảng niêm yết chính thức từ Sở HNX...")
    payload_hnx = {
        'p_issearch': 0, 'p_keysearch': '', 'p_market_code': '',
        'p_orderby': 'STOCK_CODE', 'p_ordertype': 'ASC', 'p_currentpage': 1, 'p_record_on_page': 500
    }
    r_hnx = requests.post(
        'https://hnx.vn/ModuleIssuer/List/ListSearch_Datas',
        data=payload_hnx,
        headers={**headers, 'Referer': 'https://hnx.vn/cophieu-etfs/chung-khoan-ny.html'},
        verify=False,
        timeout=15
    )
    if r_hnx.status_code == 200:
        soup_hnx = BeautifulSoup(r_hnx.json().get('Content', ''), 'html.parser')
        for tr in soup_hnx.find_all('tr'):
            tds = [td.get_text(strip=True) for td in tr.find_all(['td', 'th'])]
            # ['STT', 'Mã CK', 'Tên tổ chức phát hành', 'Ngành', 'Ngày GD đầu tiên', 'Khối lượng NY', 'KLLH (Cổ phiếu)']
            if len(tds) >= 7 and tds[0] != 'STT':
                ticker = tds[1].strip().upper()
                listing_date = tds[4].strip()
                listing_vol = tds[5].strip()
                out_vol = tds[6].strip()
                hnx_data[ticker] = {
                    'listing_date': listing_date,
                    'listing_volume': listing_vol,
                    'outstanding_volume': out_vol
                }
        print(f"✅ Đã tải thành công {len(hnx_data)} mã niêm yết từ Sở HNX.")
    else:
        print(f"❌ Lỗi tải HNX: Mã HTTP {r_hnx.status_code}")
except Exception as e:
    print(f"❌ Lỗi kết nối HNX: {e}")

# 2. Quét toàn bộ dữ liệu gốc từ UPCoM (815 mã)
upcom_data = {}
try:
    print("\n📡 Đang tải bảng đăng ký giao dịch chính thức từ UPCoM (Sở HNX)...")
    payload_uc = {
        'p_issearch': 0, 'p_keysearch': '', 'p_market_code': '',
        'p_orderby': 'STOCK_CODE', 'p_ordertype': 'ASC', 'p_currentpage': 1, 'p_record_on_page': 1000
    }
    r_uc = requests.post(
        'https://hnx.vn/ModuleIssuer/UC_Issuer/ListSearch_Datas',
        data=payload_uc,
        headers={**headers, 'Referer': 'https://hnx.vn/cophieu-etfs/chung-khoan-uc.html'},
        verify=False,
        timeout=15
    )
    if r_uc.status_code == 200:
        soup_uc = BeautifulSoup(r_uc.json().get('Content', ''), 'html.parser')
        for tr in soup_uc.find_all('tr'):
            tds = [td.get_text(strip=True) for td in tr.find_all(['td', 'th'])]
            # ['STT', 'Mã CK', 'Tên tổ chức phát hành', 'Ngày GD đầu tiên', 'Khối lượng ĐKGD', 'KLLH (Cổ phiếu)']
            if len(tds) >= 6 and tds[0] != 'STT':
                ticker = tds[1].strip().upper()
                reg_date = tds[3].strip()
                listing_vol = tds[4].strip()
                out_vol = tds[5].strip()
                upcom_data[ticker] = {
                    'reg_date': reg_date,
                    'listing_volume': listing_vol,
                    'outstanding_volume': out_vol
                }
        print(f"✅ Đã tải thành công {len(upcom_data)} mã ĐKGD từ UPCoM.")
    else:
        print(f"❌ Lỗi tải UPCoM: Mã HTTP {r_uc.status_code}")
except Exception as e:
    print(f"❌ Lỗi kết nối UPCoM: {e}")

# 3. Nguồn tỷ lệ sở hữu nước ngoài: KHÔNG sử dụng nguồn ngoài Infor.db
foreign_map = {}

# 4. Cập nhật vào dim_company trong bctc_alert.db
conn = sqlite3.connect(DB_PATH)
cur = conn.cursor()

vn_tz = pytz.timezone('Asia/Ho_Chi_Minh')
now_str = datetime.now(vn_tz).strftime('%Y-%m-%d %H:%M:%S')

updated_hnx_count = 0
updated_upcom_count = 0

# Cập nhật HNX
for ticker, info in hnx_data.items():
    f_ratio = foreign_map.get(ticker)
    cur.execute("""
        UPDATE dim_company
        SET listing_date = COALESCE(?, listing_date),
            listing_volume = COALESCE(?, listing_volume),
            outstanding_volume = COALESCE(?, outstanding_volume),
            foreign_owned_ratio = COALESCE(?, foreign_owned_ratio),
            updated_at = ?
        WHERE ticker = ? AND exchange = 'HNX'
    """, (
        info.get('listing_date'),
        info.get('listing_volume'),
        info.get('outstanding_volume'),
        f_ratio,
        now_str,
        ticker
    ))
    if cur.rowcount > 0:
        updated_hnx_count += 1

# Cập nhật UPCoM
for ticker, info in upcom_data.items():
    f_ratio = foreign_map.get(ticker)
    cur.execute("""
        UPDATE dim_company
        SET reg_date = COALESCE(?, reg_date),
            listing_volume = COALESCE(?, listing_volume),
            outstanding_volume = COALESCE(?, outstanding_volume),
            foreign_owned_ratio = COALESCE(?, foreign_owned_ratio),
            updated_at = ?
        WHERE ticker = ? AND exchange = 'UPCoM'
    """, (
        info.get('reg_date'),
        info.get('listing_volume'),
        info.get('outstanding_volume'),
        f_ratio,
        now_str,
        ticker
    ))
    if cur.rowcount > 0:
        updated_upcom_count += 1

conn.commit()

print("\n" + "=" * 70)
print("📊 KẾT QUẢ ĐỒNG BỘ VÀO BẢNG dim_company:")
print("=" * 70)
print(f"  - Số mã HNX đã cập nhật chi tiết từ Sở: {updated_hnx_count} / 299 mã")
print(f"  - Số mã UPCoM đã cập nhật chi tiết từ Sở: {updated_upcom_count} / 466 mã")

# 5. Thống kê kiểm tra độ phủ dữ liệu
cur.execute("""
    SELECT exchange,
           COUNT(*) as total,
           COUNT(id) as has_id,
           COUNT(listing_volume) as has_list_vol,
           COUNT(outstanding_volume) as has_out_vol,
           COUNT(listing_date) as has_list_date,
           COUNT(reg_date) as has_reg_date,
           COUNT(foreign_owned_ratio) as has_for_ratio
    FROM dim_company
    GROUP BY exchange
    ORDER BY exchange
""")
stats = cur.fetchall()

print("\n" + "=" * 80)
print(f"{'SÀN':<8} | {'TỔNG':<5} | {'ID (int)':<8} | {'KL NY/ĐKGD':<11} | {'KL LƯU HÀNH':<11} | {'NGÀY NY':<8} | {'NGÀY ĐKGD':<10} | {'ROOM NGOẠI':<10}")
print("-" * 80)
for r in stats:
    print(f"{r[0]:<8} | {r[1]:<5} | {r[2]:<8} | {r[3]:<11} | {r[4]:<11} | {r[5]:<8} | {r[6]:<10} | {r[7]:<10}")
print("=" * 80)

# Mẫu bản ghi thực tế đại diện
print("\n🔍 DỮ LIỆU THỰC TẾ ĐẠI DIỆN 3 SÀN SAU KHI CẬP NHẬT:")
cur.execute("""
    SELECT ticker, id, exchange, listing_volume, outstanding_volume, listing_date, reg_date, foreign_owned_ratio
    FROM dim_company
    WHERE ticker IN ('VNM', 'CLC', 'SHS', 'IDC', 'ACV', 'MCH')
    ORDER BY exchange, ticker
""")
for r in cur.fetchall():
    id_str = str(r[1]) if r[1] is not None else "NULL"
    l_date = r[5] or "-"
    r_date = r[6] or "-"
    f_rate = f"{r[7]}%" if r[7] else "-"
    print(f" • [{r[2]}] {r[0]:<4} | ID: {id_str:<4} | KLNY/ĐKGD: {r[3]:>14} | KLLH: {r[4]:>14} | Ngày NY: {l_date:<10} | Ngày ĐKGD: {r_date:<10} | Room ngoại: {f_rate}")

conn.close()

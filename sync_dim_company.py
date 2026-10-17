import os
import sys
import re
import json
import sqlite3
from datetime import datetime
import pytz
import requests
import pandas as pd
from bs4 import BeautifulSoup
import urllib3

sys.stdout.reconfigure(encoding='utf-8')
urllib3.disable_warnings()

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "bctc_alert.db")
CSV_PATH = os.path.join(BASE_DIR, "Danh_sach_DN_cong_bo_BCTC_Quy.csv")

# =============================================================================
# CÁC HÀM TIỆN ÍCH CHUẨN HÓA DỮ LIỆU (DATA CLEANING PIPELINE)
# =============================================================================
def clean_int_volume(val) -> int | None:
    """Xóa bỏ dấu chấm, dấu phẩy, khoảng trắng để chuyển về số nguyên."""
    if val is None or val == "":
        return None
    digits = re.sub(r'[^\d]', '', str(val))
    return int(digits) if digits else None

def clean_ratio(val) -> float | None:
    """Chuyển chuỗi tỷ lệ % thành float chuẩn (0.00 - 100.00)."""
    if val is None or val == "":
        return None
    try:
        val_str = str(val).replace(',', '.').replace('%', '').strip()
        f_val = float(val_str)
        return round(f_val, 2)
    except (ValueError, TypeError):
        return None

def clean_date_iso(val) -> str | None:
    """Chuyển đổi timestamp Unix hoặc chuỗi DD/MM/YYYY sang chuẩn ISO YYYY-MM-DD."""
    if not val:
        return None
    val_str = str(val).strip()
    # Nếu là timestamp dạng int hoặc str
    if isinstance(val, (int, float)) and val > 0:
        try:
            vn_tz = pytz.timezone('Asia/Ho_Chi_Minh')
            return datetime.fromtimestamp(val, tz=vn_tz).strftime('%Y-%m-%d')
        except Exception:
            pass
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

def init_dim_company_schema(conn: sqlite3.Connection):
    """Khởi tạo bảng dim_company theo chuẩn Schema tối ưu mới nếu chưa tồn tại."""
    cur = conn.cursor()
    cur.execute("""
    CREATE TABLE IF NOT EXISTS dim_company (
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
    cur.execute("CREATE INDEX IF NOT EXISTS idx_dim_company_exchange ON dim_company(exchange)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_dim_company_reporting ON dim_company(is_quarterly_reporting)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_dim_company_id ON dim_company(id)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_dim_company_first_date ON dim_company(first_trading_date)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_dim_company_out_vol ON dim_company(outstanding_volume)")
    conn.commit()

# =============================================================================
# PIPELINE ĐỒNG BỘ DOANH NGHIỆP TỪ 3 SÀN (HOÀN TOÀN KHÔNG DÙNG Infor.db)
# =============================================================================
def sync_all_dim_company():
    print("=" * 70)
    print("🚀 BẮT ĐẦU ĐỒNG BỘ TOÀN DIỆN 1.171 DOANH NGHIỆP VÀO dim_company")
    print("   (Nguồn: Sở HOSE, Sở HNX - Tuyệt đối KHÔNG sử dụng nguồn ngoài)")
    print("=" * 70)

    conn = sqlite3.connect(DB_PATH)
    init_dim_company_schema(conn)
    cur = conn.cursor()

    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
        'X-Requested-With': 'XMLHttpRequest'
    }

    # 1. Cào dữ liệu từ Sở HOSE (API REST JSON)
    print("\n📡 [1/3] Đang tải danh sách niêm yết từ Sở GDCK TP.HCM (HOSE)...")
    hose_data = {}
    try:
        url_hose = "https://api.hsx.vn/l/api/v1/1/securities/stock?pageIndex=1&pageSize=1000"
        r_hose = requests.get(url_hose, headers={'User-Agent': headers['User-Agent']}, timeout=15)
        if r_hose.status_code == 200:
            stock_list = r_hose.json().get('data', {}).get('list', [])
            for item in stock_list:
                ticker = str(item.get('code', '')).strip().upper()
                if not ticker:
                    continue
                list_d = clean_date_iso(item.get('listDate'))
                reg_d = clean_date_iso(item.get('regDate'))
                hose_data[ticker] = {
                    'id': item.get('id'),
                    'company_name': str(item.get('name', '')).strip(),
                    'listing_volume': clean_int_volume(item.get('listingVolume')),
                    'outstanding_volume': clean_int_volume(item.get('outStanding')),
                    'listing_date': list_d,
                    'reg_date': reg_d,
                    'first_trading_date': list_d or reg_d,
                    'foreign_owned_ratio': clean_ratio(item.get('foreignOwnedRatio')),
                    'state_owned_ratio': clean_ratio(item.get('stateOwnedRatio'))
                }
            print(f"✅ Đã tải thành công {len(hose_data)} mã niêm yết từ Sở HOSE.")
        else:
            print(f"⚠️ HOSE API trả về mã lỗi HTTP {r_hose.status_code}")
    except Exception as e:
        print(f"⚠️ Lỗi kết nối HOSE API: {e}")

    # 2. Cào dữ liệu từ Sở HNX (Bảng Niêm yết HNX)
    print("\n📡 [2/3] Đang tải danh sách niêm yết chính thức từ Sở GDCK Hà Nội (HNX)...")
    hnx_data = {}
    try:
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
                if len(tds) >= 7 and tds[0] != 'STT':
                    ticker = tds[1].strip().upper()
                    l_date = clean_date_iso(tds[4].strip())
                    hnx_data[ticker] = {
                        'company_name': tds[2].strip(),
                        'listing_date': l_date,
                        'first_trading_date': l_date,
                        'listing_volume': clean_int_volume(tds[5].strip()),
                        'outstanding_volume': clean_int_volume(tds[6].strip())
                    }
            print(f"✅ Đã tải thành công {len(hnx_data)} mã niêm yết từ Sở HNX.")
        else:
            print(f"⚠️ HNX API trả về mã HTTP {r_hnx.status_code}")
    except Exception as e:
        print(f"⚠️ Lỗi kết nối HNX: {e}")

    # 3. Cào dữ liệu từ Sở HNX (Bảng ĐKGD UPCoM)
    print("\n📡 [3/3] Đang tải danh sách đăng ký giao dịch từ UPCoM (Sở HNX)...")
    upcom_data = {}
    try:
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
                if len(tds) >= 6 and tds[0] != 'STT':
                    ticker = tds[1].strip().upper()
                    r_date = clean_date_iso(tds[3].strip())
                    upcom_data[ticker] = {
                        'company_name': tds[2].strip(),
                        'reg_date': r_date,
                        'first_trading_date': r_date,
                        'listing_volume': clean_int_volume(tds[4].strip()),
                        'outstanding_volume': clean_int_volume(tds[5].strip())
                    }
            print(f"✅ Đã tải thành công {len(upcom_data)} mã ĐKGD từ UPCoM.")
        else:
            print(f"⚠️ UPCoM API trả về mã HTTP {r_uc.status_code}")
    except Exception as e:
        print(f"⚠️ Lỗi kết nối UPCoM: {e}")

    # 4. Đọc danh mục 1.171 doanh nghiệp công bố BCTC Quý từ file chuẩn
    df_1171 = None
    if os.path.exists(CSV_PATH):
        df_1171 = pd.read_csv(CSV_PATH)
        print(f"\n📄 Đã nạp {len(df_1171)} mã từ danh mục chuẩn: {os.path.basename(CSV_PATH)}")

    vn_tz = pytz.timezone('Asia/Ho_Chi_Minh')
    now_str = datetime.now(vn_tz).strftime('%Y-%m-%d %H:%M:%S')

    # 5. Lưu hoặc cập nhật dữ liệu vào SQLite
    inserted_count = 0
    updated_count = 0

    if df_1171 is not None:
        for _, row in df_1171.iterrows():
            ticker = str(row['ticker']).strip().upper()
            comp_name = str(row['company_name']).strip()
            exchange = str(row['exchange']).strip()
            sector_name = str(row['sector_name']).strip() if pd.notna(row['sector_name']) else None
            shares_csv = clean_int_volume(row['total_shares']) if 'total_shares' in row and pd.notna(row['total_shares']) else None

            # Tìm nguồn thông tin chi tiết
            c_info = {}
            if exchange == 'HOSE':
                c_info = hose_data.get(ticker, {})
            elif exchange == 'HNX':
                c_info = hnx_data.get(ticker, {})
            elif exchange == 'UPCoM':
                c_info = upcom_data.get(ticker, {})

            comp_id = c_info.get('id')
            final_name = c_info.get('company_name') or comp_name
            list_vol = c_info.get('listing_volume')
            out_vol = c_info.get('outstanding_volume') or shares_csv
            list_date = c_info.get('listing_date')
            reg_date = c_info.get('reg_date')
            first_date = c_info.get('first_trading_date') or list_date or reg_date
            foreign_ratio = c_info.get('foreign_owned_ratio')
            state_ratio = c_info.get('state_owned_ratio')

            cur.execute("""
                INSERT INTO dim_company (
                    ticker, id, company_name, exchange, sector_name, is_quarterly_reporting,
                    listing_volume, outstanding_volume, first_trading_date, listing_date, reg_date,
                    foreign_owned_ratio, state_owned_ratio, updated_at
                ) VALUES (?, ?, ?, ?, ?, 1, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(ticker) DO UPDATE SET
                    id = COALESCE(excluded.id, dim_company.id),
                    company_name = excluded.company_name,
                    exchange = excluded.exchange,
                    sector_name = COALESCE(excluded.sector_name, dim_company.sector_name),
                    is_quarterly_reporting = 1,
                    listing_volume = COALESCE(excluded.listing_volume, dim_company.listing_volume),
                    outstanding_volume = COALESCE(excluded.outstanding_volume, dim_company.outstanding_volume),
                    first_trading_date = COALESCE(excluded.first_trading_date, dim_company.first_trading_date),
                    listing_date = COALESCE(excluded.listing_date, dim_company.listing_date),
                    reg_date = COALESCE(excluded.reg_date, dim_company.reg_date),
                    foreign_owned_ratio = COALESCE(excluded.foreign_owned_ratio, dim_company.foreign_owned_ratio),
                    state_owned_ratio = COALESCE(excluded.state_owned_ratio, dim_company.state_owned_ratio),
                    updated_at = excluded.updated_at
            """, (
                ticker, comp_id, final_name, exchange, sector_name,
                list_vol, out_vol, first_date, list_date, reg_date,
                foreign_ratio, state_ratio, now_str
            ))
            if cur.rowcount > 0:
                updated_count += 1

    conn.commit()

    # 6. Thống kê kết quả
    cur.execute("""
        SELECT exchange, 
               COUNT(*) as total,
               COUNT(id) as has_id,
               COUNT(listing_volume) as has_list_vol,
               COUNT(outstanding_volume) as has_out_vol,
               COUNT(first_trading_date) as has_first_date,
               COUNT(foreign_owned_ratio) as has_for_ratio,
               COUNT(state_owned_ratio) as has_state_ratio
        FROM dim_company
        GROUP BY exchange
        ORDER BY exchange
    """)
    stats = cur.fetchall()

    print("\n" + "=" * 95)
    print(f"📊 THỐNG KÊ ĐỘ PHỦ DỮ LIỆU CHUẨN HÓA TRONG BẢNG dim_company ({sum(s[1] for s in stats)} MÃ):")
    print("=" * 95)
    print(f"{'SÀN':<8} | {'TỔNG':<6} | {'ID (HOSE)':<10} | {'KL NIÊM YẾT':<13} | {'KL LƯU HÀNH':<13} | {'NGÀY ĐẦU GD':<12} | {'ROOM NGOẠI':<11} | {'NHÀ NƯỚC':<10}")
    print("-" * 95)
    for r in stats:
        print(f"{r[0]:<8} | {r[1]:<6} | {r[2]:<10} | {r[3]:<13} | {r[4]:<13} | {r[5]:<12} | {r[6]:<11} | {r[7]:<10}")
    print("=" * 95)

    conn.close()
    print("✅ Hoàn tất đồng bộ toàn diện vào dim_company thành công!")

if __name__ == '__main__':
    sync_all_dim_company()

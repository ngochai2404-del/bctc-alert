"""
========================================================================================
MODULE CÀO DỮ LIỆU BCTC HOSE, HNX, UPCOM VÀ ĐỐI CHIẾU KHO DỮ LIỆU dim_period
========================================================================================
Hỗ trợ:
- Cào 1.171 doanh nghiệp báo cáo theo quý từ cổng chính thức HOSE & HNX.
- Lọc theo khung thời gian (Tháng / Năm).
- Phân loại theo sàn (HOSE, HNX, UPCoM, Tất cả).
- Đối chiếu kho dữ liệu dim_period trong SQLite:
  + Nếu đã có trong kho -> Bỏ qua, KHÔNG BÁO.
  + Nếu mới phát hiện -> Gửi thông báo chuẩn lên Telegram + Lưu vào dim_period.
========================================================================================
"""

import os
import sys
import re
import time
import json
import html
import calendar
import sqlite3
import requests
import urllib3
from bs4 import BeautifulSoup
from datetime import datetime
import pytz
from concurrent.futures import ThreadPoolExecutor

urllib3.disable_warnings()

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "bctc_alert.db")
CONFIG_PATH = os.path.join(BASE_DIR, "config.json")
VN_TZ = pytz.timezone('Asia/Ho_Chi_Minh')

# Danh mục rổ chỉ số trọng yếu thị trường
VN30_TICKERS = {
    'ACB', 'BID', 'BSR', 'CTG', 'FPT', 'GAS', 'GVR', 'HDB', 'HPG', 'LPB',
    'MBB', 'MCH', 'MSN', 'MWG', 'SAB', 'SHB', 'SSB', 'SSI', 'STB', 'TCB',
    'TCX', 'VCB', 'VHM', 'VIB', 'VIC', 'VJC', 'VNM', 'VPB', 'VPL', 'VRE'
}

HNX30_TICKERS = {
    'BVS', 'CAP', 'CEO', 'DP3', 'DTD', 'DVM', 'DXP', 'HUT', 'IDC', 'IDV',
    'L14', 'L18', 'LAS', 'LHC', 'MBS', 'NDN', 'NTP', 'PLC', 'PSD', 'PVB',
    'PVC', 'PVS', 'SHS', 'SLS', 'TMB', 'TNG', 'TVD', 'VC3', 'VCS', 'VFS'
}

VN100_TICKERS = {
    # 30 VN30
    'ACB', 'BID', 'BSR', 'CTG', 'FPT', 'GAS', 'GVR', 'HDB', 'HPG', 'LPB',
    'MBB', 'MCH', 'MSN', 'MWG', 'SAB', 'SHB', 'SSB', 'SSI', 'STB', 'TCB',
    'TCX', 'VCB', 'VHM', 'VIB', 'VIC', 'VJC', 'VNM', 'VPB', 'VPL', 'VRE',
    # 70 VNMidcap
    'ANV', 'BAF', 'BCM', 'BMP', 'BSI', 'BVH', 'BWE', 'CII', 'CMG', 'CTD',
    'CTR', 'CTS', 'DBC', 'DCM', 'DGW', 'DIG', 'DPM', 'DSE', 'DXG', 'EIB',
    'EVF', 'FRT', 'FTS', 'GEE', 'GEX', 'GMD', 'HAG', 'HCM', 'HDG', 'HHV',
    'HSG', 'HT1', 'KBC', 'KDC', 'KDH', 'KOS', 'MSB', 'NAB', 'NKG', 'NLG',
    'NT2', 'NVL', 'OCB', 'PAN', 'PC1', 'PDR', 'PHR', 'PLX', 'PNJ', 'POW',
    'PVD', 'PVT', 'REE', 'SBT', 'SIP', 'SJS', 'TAL', 'TCH', 'TPB', 'VCG',
    'VCI', 'VCK', 'VGC', 'VHC', 'VIX', 'VND', 'VPI', 'VPX', 'VSC', 'VTP'
}

def get_ticker_index_icon(ticker: str) -> str:
    """
    Trả về icon nhận diện chỉ số:
    - Thuộc VN30 hoặc HNX30: '🔥 '
    - Thuộc VN100 (không thuộc VN30): '💎 '
    - Các mã còn lại: ''
    """
    t = str(ticker).strip().upper()
    if t in VN30_TICKERS or t in HNX30_TICKERS:
        return "🔥 "
    if t in VN100_TICKERS:
        return "💎 "
    return ""

def load_config():
    if os.path.exists(CONFIG_PATH):
        try:
            with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {
        "telegram": {
            "enabled": True,
            "bot_token": "8880855162:AAFixBK3bYvp78fLeExM2GIONzOWNEuN6fQ",
            "chat_id": "-1004333332152"
        }
    }

def save_config(config_data):
    try:
        with open(CONFIG_PATH, "w", encoding="utf-8") as f:
            json.dump(config_data, f, ensure_ascii=False, indent=4)
        return True
    except Exception as e:
        print(f"[Error saving config] {e}")
        return False

def get_db_connection():
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn

def get_scan_queue_stats(selected_month=10, selected_year=2026, exchanges=None):
    """
    Thống kê hàng đợi quét thông minh:
    - Tổng số mã cần theo dõi
    - Số mã ĐÃ CÓ BCTC trong kỳ (Completed - có thể bỏ qua để tối ưu tốc độ)
    - Số mã CHƯA CÓ BCTC trong kỳ (Pending - ưu tiên quét nhanh)
    """
    conn = get_db_connection()
    cur = conn.cursor()
    
    where_clauses = ["is_quarterly_reporting = 1"]
    params = []
    if exchanges and "ALL" not in exchanges and "Tất cả" not in exchanges:
        placeholders = ",".join(["?"] * len(exchanges))
        where_clauses.append(f"exchange IN ({placeholders})")
        params.extend(exchanges)
        
    where_sql = " AND ".join(where_clauses)
    cur.execute(f"SELECT ticker FROM dim_company WHERE {where_sql}", params)
    all_target_tickers = set(r[0] for r in cur.fetchall())
    
    target_month_str = f"{selected_month:02d}/{selected_year}"
    q_term_id = 4 if selected_month in [10, 11, 12] else (3 if selected_month in [7, 8, 9] else (2 if selected_month in [4, 5, 6] else 1))
    
    cur.execute("""
        SELECT DISTINCT ticker FROM dim_period 
        WHERE published_date LIKE ? OR (year_period = ? AND report_term_id = ?)
    """, (f"%{target_month_str}%", selected_year, q_term_id))
    completed_tickers = set(r[0] for r in cur.fetchall()) & all_target_tickers
    
    pending_tickers = all_target_tickers - completed_tickers
    conn.close()
    
    return {
        "total": len(all_target_tickers),
        "completed": len(completed_tickers),
        "pending": len(pending_tickers),
        "completed_tickers": completed_tickers,
        "pending_tickers": pending_tickers
    }

def get_target_companies(exchanges=None, scan_mode="PENDING_ONLY", selected_month=10, selected_year=2026, watchlist=None):
    """
    Lấy danh sách doanh nghiệp cần quét từ dim_company theo hàng đợi thông minh:
    - PENDING_ONLY (Mặc định): Chỉ quét các mã CHƯA có BCTC trong tháng/năm đã chọn (Tăng tốc độ gấp 10 lần).
    - ALL: Quét toàn bộ mã (bao gồm cả mã đã có để tuần tra bổ sung giải trình / đính chính nộp sau).
    - WATCHLIST: Chỉ quét các mã trong danh sách watchlist chỉ định.
    """
    conn = get_db_connection()
    cur = conn.cursor()
    
    where_clauses = ["is_quarterly_reporting = 1"]
    params = []
    
    if scan_mode == "VN30_HNX30":
        target_set = sorted(VN30_TICKERS | HNX30_TICKERS)
        placeholders = ",".join(["?"] * len(target_set))
        where_clauses.append(f"ticker IN ({placeholders})")
        params.extend(target_set)
    elif scan_mode == "VN100":
        target_set = sorted(VN100_TICKERS)
        placeholders = ",".join(["?"] * len(target_set))
        where_clauses.append(f"ticker IN ({placeholders})")
        params.extend(target_set)
    elif scan_mode == "WATCHLIST" and watchlist:
        wl_clean = [w.strip().upper() for w in watchlist if w.strip()]
        if wl_clean:
            placeholders = ",".join(["?"] * len(wl_clean))
            where_clauses.append(f"ticker IN ({placeholders})")
            params.extend(wl_clean)
            
    if scan_mode not in ["VN30_HNX30", "VN100"] and exchanges and "ALL" not in exchanges and "Tất cả" not in exchanges:
        placeholders = ",".join(["?"] * len(exchanges))
        where_clauses.append(f"exchange IN ({placeholders})")
        params.extend(exchanges)
            
    if scan_mode == "PENDING_ONLY":
        target_month_str = f"{selected_month:02d}/{selected_year}"
        q_term_id = 4 if selected_month in [10, 11, 12] else (3 if selected_month in [7, 8, 9] else (2 if selected_month in [4, 5, 6] else 1))
        where_clauses.append(f"""
            ticker NOT IN (
                SELECT DISTINCT ticker FROM dim_period 
                WHERE published_date LIKE ? OR (year_period = ? AND report_term_id = ?)
            )
        """)
        params.extend([f"%{target_month_str}%", selected_year, q_term_id])
        
    where_sql = " AND ".join(where_clauses)
    cur.execute(f"""
        SELECT ticker, id, company_name, exchange 
        FROM dim_company 
        WHERE {where_sql}
        ORDER BY exchange, ticker
    """, params)
    
    rows = [dict(r) for r in cur.fetchall()]
    conn.close()
    return rows

def check_exists_in_dim_period(conn, ticker, pdf_url="", file_name="", published_date="", period_id=""):
    """
    Đối chiếu xem bản ghi BCTC này đã tồn tại trong dim_period hay chưa.
    Trả về True nếu đã có (không cần báo), False nếu là bản ghi mới.
    """
    cur = conn.cursor()
    
    if period_id:
        cur.execute("SELECT 1 FROM dim_period WHERE period_id = ? LIMIT 1", (period_id,))
        if cur.fetchone():
            return True
            
    if pdf_url and pdf_url.strip():
        cur.execute("SELECT 1 FROM dim_period WHERE ticker = ? AND pdf_url = ? LIMIT 1", (ticker, pdf_url.strip()))
        if cur.fetchone():
            return True
            
    if file_name and file_name.strip() and published_date:
        cur.execute("SELECT 1 FROM dim_period WHERE ticker = ? AND file_name = ? AND published_date = ? LIMIT 1", 
                    (ticker, file_name.strip(), published_date.strip()))
        if cur.fetchone():
            return True
            
    return False

def insert_new_to_dim_period(conn, rec):
    """Lưu bản ghi BCTC mới vào bảng dim_period"""
    cur = conn.cursor()
    now_str = datetime.now(VN_TZ).strftime('%Y-%m-%d %H:%M:%S')
    
    cur.execute("""
        INSERT INTO dim_period (
            period_id, ticker, exchange, year_period, report_term_id, term_name,
            is_united, united_name, audit_status, has_explanation, has_bctc,
            source, published_date, published_time, created_timestamp,
            file_name, pdf_url, hose_news_id, raw_url, status, updated_at
        ) VALUES (
            :period_id, :ticker, :exchange, :year_period, :report_term_id, :term_name,
            :is_united, :united_name, :audit_status, :has_explanation, :has_bctc,
            :source, :published_date, :published_time, :created_timestamp,
            :file_name, :pdf_url, :hose_news_id, :raw_url, 'COMPLETED', :updated_at
        )
        ON CONFLICT(period_id) DO UPDATE SET
            file_name = excluded.file_name,
            pdf_url = excluded.pdf_url,
            updated_at = excluded.updated_at
    """, {
        'period_id': rec['period_id'],
        'ticker': rec['ticker'],
        'exchange': rec.get('exchange', 'HOSE'),
        'year_period': rec.get('year_period', 2026),
        'report_term_id': rec.get('report_term_id', 3),
        'term_name': rec.get('term_name', 'Quý 3/2026'),
        'is_united': rec.get('is_united', 0),
        'united_name': rec.get('united_name', 'Riêng'),
        'audit_status': rec.get('audit_status', 'Chưa kiểm toán'),
        'has_explanation': rec.get('has_explanation', 0),
        'has_bctc': rec.get('has_bctc', 1),
        'source': rec.get('source', rec.get('exchange', 'HOSE')),
        'published_date': rec.get('published_date', ''),
        'published_time': rec.get('published_time', ''),
        'created_timestamp': rec.get('created_timestamp', int(time.time())),
        'file_name': rec.get('file_name', ''),
        'pdf_url': rec.get('pdf_url', ''),
        'hose_news_id': rec.get('hose_news_id'),
        'raw_url': rec.get('raw_url', ''),
        'updated_at': now_str
    })
    conn.commit()

def format_grouped_announcement(files):
    """
    Gom toàn bộ các file đính kèm của 1 đợt công bố BCTC thành 1 TIN NHẮN DUY NHẤT.
    Tự động chọn file BCTC chính (tiếng Việt), nhận diện Giải trình/Hợp nhất/Kiểm toán,
    và chèn link tải trực tiếp file PDF chính.
    """
    if not files:
        return ""
    if not isinstance(files, list):
        files = [files]

    first = files[0]
    ticker = first.get('ticker', 'MÃ')
    comp_name = first.get('company_name') or first.get('comp_name') or f"Công ty CP {ticker}"
    exchange = first.get('exchange', '')
    term_str = first.get('term_name', 'Báo cáo tài chính')
    pub_date = first.get('published_date', '')
    pub_time = first.get('published_time', '') or "00:00:00"

    clean_term = term_str if term_str.upper().startswith("BCTC") else f"BCTC {term_str}"

    main_file = None
    has_exp = False
    is_united = False
    is_mother = False
    is_audited = False
    is_reviewed = False

    for f in files:
        fn = f.get('file_name', '')
        fn_lower = fn.lower()

        if f.get('has_explanation') == 1 or any(k in fn_lower for k in ["giải trình", "giaitrinh", "giai_trinh", "loinhuan", "chenhlech", "explanation"]):
            has_exp = True

    # Phân loại các file thành phần
    hn_file = None
    rieng_file = None
    gt_file = None
    other_file = None

    for f in files:
        fn = f.get('file_name', '')
        fn_lower = fn.lower()

        if f.get('has_explanation') == 1 or any(k in fn_lower for k in ["giải trình", "giaitrinh", "giai_trinh", "loinhuan", "chenhlech"]):
            has_exp = True
            if not gt_file and "_en." not in fn_lower and "_en_" not in fn:
                gt_file = f

        if f.get('is_united') == 1 or any(k in fn_lower for k in ["hợp nhất", "hopnhat", "hop nhat", "_hn_", "consolidated"]):
            is_united = True
            if not hn_file and "_en." not in fn_lower and "_en_" not in fn:
                hn_file = f
        elif any(k in fn_lower for k in ["mẹ", "công ty mẹ", "me"]):
            is_mother = True
            if not rieng_file and "_en." not in fn_lower and "_en_" not in fn:
                rieng_file = f
        elif any(k in fn_lower for k in ["riêng", "rieng"]):
            if not rieng_file and "_en." not in fn_lower and "_en_" not in fn:
                rieng_file = f
        else:
            if not other_file and "_en." not in fn_lower and "_en_" not in fn:
                other_file = f

        if any(k in fn_lower for k in ["kiểm toán", "kiem toan", "audited"]):
            is_audited = True
        elif any(k in fn_lower for k in ["soát xét", "soat xet", "reviewed"]):
            is_reviewed = True

    # Xác định file đại diện
    if hn_file and rieng_file:
        main_content_text = f"{hn_file.get('file_name', '')} & {rieng_file.get('file_name', '')}"
    elif hn_file:
        main_content_text = hn_file.get('file_name', '')
    elif rieng_file:
        main_content_text = rieng_file.get('file_name', '')
    elif other_file:
        main_content_text = other_file.get('file_name', '')
    else:
        main_content_text = files[0].get('file_name', '')

    # Xây dựng ghi chú
    note_parts = []
    if hn_file and rieng_file:
        note_parts.append("BCTC Hợp nhất + BCTC Riêng")
    elif is_united:
        note_parts.append("BCTC Hợp nhất")
    elif is_mother:
        note_parts.append("BCTC Công ty mẹ")
    else:
        note_parts.append("BCTC Riêng")

    if has_exp:
        note_parts.append("Giải trình")

    if is_audited:
        note_parts.append("Kiểm toán")
    elif is_reviewed:
        note_parts.append("Soát xét")

    smart_note = " + ".join(note_parts)

    safe_ticker = html.escape(ticker)
    safe_comp = html.escape(comp_name)
    safe_ex = html.escape(exchange)
    safe_term = html.escape(clean_term)
    safe_fn = html.escape(main_content_text)
    safe_note = html.escape(smart_note)

    icon_prefix = get_ticker_index_icon(ticker)
    header = f"{icon_prefix}<b>{safe_ticker}</b> - {safe_comp} ({safe_ex})"
    time_line = f"<b>{safe_term}</b> - {pub_date} - {pub_time}"
    content_line = f"<b>Nội dung:</b> <i>{safe_fn}</i>"
    note_line = f"<b>Ghi chú:</b> {safe_note}"
    separator = "━━━━━━━━━━━━━━━━━━━━"

    # Tạo đường link tải thông minh
    action_lines = []
    if hn_file and hn_file.get('pdf_url'):
        action_lines.append(f'[👉] <a href="{hn_file["pdf_url"]}">TẢI BCTC HỢP NHẤT</a>')
    if rieng_file and rieng_file.get('pdf_url'):
        action_lines.append(f'[👉] <a href="{rieng_file["pdf_url"]}">TẢI BCTC RIÊNG</a>')
    if gt_file and gt_file.get('pdf_url') and gt_file != hn_file and gt_file != rieng_file:
        action_lines.append(f'[👉] <a href="{gt_file["pdf_url"]}">TẢI VĂN BẢN GIẢI TRÌNH</a>')

    if not action_lines:
        first_pdf = files[0].get('pdf_url')
        if first_pdf:
            action_lines.append(f'<a href="{first_pdf}">[👉] TẢI VÀ XEM TRỰC TIẾP FILE PDF BCTC</a>')
        elif files[0].get('raw_url'):
            action_lines.append(f'<a href="{files[0]["raw_url"]}">[👉] XEM CHI TIẾT CÔNG BỐ TRÊN WEBSITE SỞ</a>')
        else:
            action_lines.append("[👉] ĐÃ TIẾP NHẬN BÁO CÁO TỪ SỞ GDCK")

    action_text = "\n".join(action_lines)
    return f"{header}\n{time_line}\n{content_line}\n{note_line}\n{separator}\n{action_text}"

def format_telegram_alert(item):
    return format_grouped_announcement([item] if isinstance(item, dict) else item)

def send_telegram_alert(item, bot_token=None, chat_id=None):
    """Gửi cảnh báo qua Telegram Bot"""
    cfg = load_config()
    tg = cfg.get('telegram', {})
    
    token = bot_token or tg.get('bot_token')
    cid = chat_id or tg.get('chat_id')
    
    if not token or not cid:
        return False, "Thiếu Bot Token hoặc Chat ID"
        
    cid_str = str(cid).strip()
    if cid_str.startswith("-") and not cid_str.startswith("-100"):
        cid_str = f"-100{cid_str.lstrip('-')}"
        
    msg = format_telegram_alert(item)
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {
        "chat_id": cid_str,
        "text": msg,
        "parse_mode": "HTML",
        "disable_web_page_preview": True
    }
    
    try:
        r = requests.post(url, json=payload, timeout=10)
        if r.status_code == 200:
            return True, "Thành công"
        else:
            return False, f"Telegram API error {r.status_code}: {r.text}"
    except Exception as e:
        return False, str(e)

def test_telegram_connection(bot_token, chat_id):
    """Kiểm tra kết nối gửi tin nhắn thử nghiệm tới Telegram"""
    cid_str = str(chat_id).strip()
    if cid_str.startswith("-") and not cid_str.startswith("-100"):
        cid_str = f"-100{cid_str.lstrip('-')}"
        
    msg = (
        "🔔 <b>[BCTC ALERT - HỆ THỐNG CẢNH BÁO TÀI CHÍNH]</b>\n"
        "Kiểm tra kết nối Telegram Bot thành công!\n"
        "Hệ thống đã sẵn sàng đối chiếu kho dữ liệu và gửi thông báo BCTC thời gian thực."
    )
    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    payload = {
        "chat_id": cid_str,
        "text": msg,
        "parse_mode": "HTML"
    }
    try:
        r = requests.post(url, json=payload, timeout=10)
        if r.status_code == 200:
            return True, "Kết nối thành công! Đã gửi tin nhắn thử nghiệm đến Telegram."
        else:
            return False, f"Lỗi ({r.status_code}): {r.text}"
    except Exception as e:
        return False, f"Lỗi kết nối: {e}"

# ========================================================================================
# LOGIC QUÉT HOSE
# ========================================================================================
def scan_hose_company_media(ticker, hose_id, comp_name, start_ts, end_ts):
    """Quét các tệp BCTC của 1 mã HOSE trong khoảng start_ts -> end_ts"""
    if not hose_id:
        return []
        
    headers = {'User-Agent': 'Mozilla/5.0'}
    matched = []
    try:
        url = f"https://api.hsx.vn/m/api/v1/1/mediafiles/5/{hose_id}?pageIndex=1&pageSize=20"
        r = requests.get(url, headers=headers, timeout=6)
        if r.status_code == 200:
            files = r.json().get('data', {}).get('list', [])
            period_files = [f for f in files if f.get('createdDate') and start_ts <= f.get('createdDate') <= end_ts]
            for idx, f in enumerate(period_files, 1):
                f_cdate = f.get('createdDate')
                fn = f.get('fileName', '')
                fn_lower = fn.lower()
                tm = str(f.get('time', ''))
                
                dt = datetime.fromtimestamp(f_cdate, tz=VN_TZ)
                d_date = dt.strftime('%d/%m/%Y')
                d_time = dt.strftime('%H:%M:%S')
                
                # Xác định năm và kỳ
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
                    year = dt.year
                    term_id = 3
                    term_name = f"Quý 3/{year}"
                
                is_united = 1 if any(k in fn_lower for k in ['hợp nhất', 'hop nhat', 'hopnhat', 'hn', 'consolidated']) else (0 if any(k in fn_lower for k in ['mẹ', 'me', 'riêng', 'rieng', 'cty mẹ', 'công ty mẹ']) else 0)
                united_name = 'Hợp nhất' if is_united else ('Công ty mẹ' if any(k in fn_lower for k in ['mẹ', 'me', 'cty mẹ']) else 'Riêng')
                has_exp = 1 if any(k in fn_lower for k in ['giải trình', 'lợi nhuận', 'chênh lệch']) else 0
                
                f_path = f.get('filePath', '')
                m_nid = re.search(r'UploadDocuments/(\d+)/', f_path)
                news_id = int(m_nid.group(1)) if m_nid else None
                pdf_link = f_path.replace("~", "https://staticfile.hsx.vn") if f_path else ""
                
                p_id = f"{ticker}_{year}_T{term_id}_{f_cdate}_{idx}"
                
                matched.append({
                    'period_id': p_id,
                    'ticker': ticker,
                    'company_name': comp_name,
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
                    'raw_url': f"https://www.hsx.vn/vi/quan-ly-niem-yet/co-phieu/{ticker}/{hose_id}",
                })
    except Exception:
        pass
    return matched

# ========================================================================================
# LOGIC QUÉT HNX & UPCOM
# ========================================================================================
def scan_hnx_company_reports(ticker, exchange, comp_name, from_date_str, to_date_str, target_month_str):
    """Quét các công bố BCTC của 1 mã HNX hoặc UPCoM từ cổng HNX"""
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
        'X-Requested-With': 'XMLHttpRequest'
    }
    
    endpoints = ['/ModuleIssuer/List/BaoCaoDinhKy', '/ModuleIssuer/List/ThongTinCongBo']
    seen_art_ids = set()
    found_articles = []
    
    for ep in endpoints:
        payload = {
            'pMarketCode': '', 'pNumPage': 1, 'pAction': 0,
            'pNhomTin': '', 'pTieuDeTin': '', 'pStockCode': ticker,
            'pFromDate': from_date_str, 'pToDate': to_date_str,
            'pOrderBy': '', 'pNumRecord': 10
        }
        try:
            r = requests.post(f"https://hnx.vn{ep}", data=payload, headers=headers, verify=False, timeout=8)
            if r.status_code == 200:
                soup = BeautifulSoup(r.text, 'html.parser')
                for tr in soup.find_all('tr'):
                    tds = tr.find_all('td')
                    if len(tds) >= 3:
                        date_str = tds[1].text.strip()
                        title = tds[2].text.strip()
                        a = tds[2].find('a')
                        onclick = a.get('onclick', '') if a else ''
                        
                        # Lọc theo tháng mục tiêu (ví dụ '10/2026')
                        if target_month_str not in date_str:
                            continue
                            
                        is_bctc = any(k in title.lower() for k in [
                            'báo cáo tài chính', 'bctc', 'giải trình', 'lợi nhuận', 'kqkd', 'kết quả kinh doanh'
                        ])
                        
                        if is_bctc:
                            m_id = re.search(r'XemChiTietDetailArticlesByID\((\d+)', onclick)
                            art_id = m_id.group(1) if m_id else None
                            if art_id and art_id not in seen_art_ids:
                                seen_art_ids.add(art_id)
                                found_articles.append({
                                    'ticker': ticker,
                                    'exchange': exchange,
                                    'comp_name': comp_name,
                                    'title': title,
                                    'date_str': date_str,
                                    'art_id': art_id,
                                    'raw_url': f"https://hnx.vn/tin-cung-cap-rss-vi_vn-{art_id}-1.html"
                                })
        except Exception:
            pass
            
    # Lấy các link file PDF đính kèm
    matched_records = []
    for art in found_articles:
        files = []
        try:
            r_det = requests.get(art['raw_url'], headers={'User-Agent': headers['User-Agent']}, verify=False, timeout=6)
            if r_det.status_code == 200:
                s_det = BeautifulSoup(r_det.text, 'html.parser')
                for a_file in s_det.find_all('a', href=True):
                    h = a_file['href']
                    txt = a_file.text.strip()
                    if ('.pdf' in h.lower() or '.zip' in h.lower()) and 'ftp' in h:
                        files.append({'name': txt or h.split('/')[-1], 'url': h})
        except Exception:
            pass
            
        # Parse ngày giờ
        d_str = art['date_str']
        pub_date = d_str
        pub_time = "00:00:00"
        created_ts = int(time.time())
        try:
            if " " in d_str:
                p_parts = d_str.split(" ")
                pub_date = p_parts[0]
                pub_time = p_parts[1] + (":00" if len(p_parts[1].split(":")) == 2 else "")
                dt = datetime.strptime(f"{pub_date} {pub_time}", "%d/%m/%Y %H:%M:%S")
                dt_vn = VN_TZ.localize(dt)
                created_ts = int(dt_vn.timestamp())
            else:
                dt = datetime.strptime(pub_date, "%d/%m/%Y")
                dt_vn = VN_TZ.localize(dt)
                created_ts = int(dt_vn.timestamp())
        except Exception:
            pass
            
        # Xác định năm và kỳ
        title_lower = art['title'].lower()
        year_period = 2026
        m_year = re.search(r'\b(202[4-6])\b', art['title'])
        if m_year:
            year_period = int(m_year.group(1))
            
        if any(k in title_lower for k in ['quý 3', 'q3', 'quý iii', '9 tháng']):
            report_term_id = 4
            term_name = f"Quý 3/{year_period}"
        elif any(k in title_lower for k in ['bán niên', '6 tháng', 'quý 2', 'q2']):
            report_term_id = 3
            term_name = f"Bán niên {year_period}"
        elif any(k in title_lower for k in ['quý 1', 'q1', 'quý i']):
            report_term_id = 2
            term_name = f"Quý 1/{year_period}"
        else:
            report_term_id = 4
            term_name = f"Quý 3/{year_period}"
            
        audit_status = "Đã kiểm toán" if any(k in title_lower for k in ['kiểm toán', 'soát xét']) else "Chưa kiểm toán"
        
        if files:
            for idx, f in enumerate(files, 1):
                file_name = f['name']
                pdf_url = f['url']
                fn_lower = file_name.lower()
                
                is_united = 1 if any(k in fn_lower or k in title_lower for k in ['hợp nhất', 'hopnhat', 'consolidated', '_hn_']) else 0
                united_name = "Hợp nhất" if is_united == 1 else "Riêng"
                has_exp = 1 if any(k in fn_lower or k in title_lower for k in ['giải trình', 'giai_trinh', 'explanation']) else 0
                has_bctc = 1 if any(k in fn_lower or k in title_lower for k in ['báo cáo tài chính', 'bctc', 'financial']) else 0
                
                period_id = f"{ticker}_{year_period}_T{report_term_id}_{created_ts}_{idx}"
                matched_records.append({
                    'period_id': period_id,
                    'ticker': ticker,
                    'company_name': comp_name,
                    'exchange': exchange,
                    'year_period': year_period,
                    'report_term_id': report_term_id,
                    'term_name': term_name,
                    'is_united': is_united,
                    'united_name': united_name,
                    'audit_status': audit_status,
                    'has_explanation': has_exp,
                    'has_bctc': has_bctc,
                    'source': exchange,
                    'published_date': pub_date,
                    'published_time': pub_time,
                    'created_timestamp': created_ts,
                    'file_name': file_name,
                    'pdf_url': pdf_url,
                    'hose_news_id': art.get('art_id'),
                    'raw_url': art.get('raw_url', '')
                })
        else:
            # Bài viết không có file trực tiếp
            period_id = f"{ticker}_{year_period}_T{report_term_id}_{created_ts}_1"
            matched_records.append({
                'period_id': period_id,
                'ticker': ticker,
                'company_name': comp_name,
                'exchange': exchange,
                'year_period': year_period,
                'report_term_id': report_term_id,
                'term_name': term_name,
                'is_united': 0,
                'united_name': "Riêng",
                'audit_status': audit_status,
                'has_explanation': 0,
                'has_bctc': 1,
                'source': exchange,
                'published_date': pub_date,
                'published_time': pub_time,
                'created_timestamp': created_ts,
                'file_name': art['title'],
                'pdf_url': '',
                'hose_news_id': art.get('art_id'),
                'raw_url': art.get('raw_url', '')
            })
            
    return matched_records

# ========================================================================================
# HÀM THỰC THI CHÍNH (QUÉT, ĐỐI CHIẾU, VÀ GỬI THÔNG BÁO)
# ========================================================================================
def execute_crawl_and_sync(
    selected_month: int,
    selected_year: int,
    selected_exchanges: list,
    scan_mode: str = "PENDING_ONLY",
    watchlist: list = None,
    send_telegram: bool = True,
    bot_token: str = None,
    chat_id: str = None,
    progress_callback = None,
    max_workers: int = 15
):
    """
    Tiến trình quét tổng hợp:
    1. Xác định khung thời gian ngày/tháng/năm.
    2. Lấy danh sách doanh nghiệp cần quét (HOSE, HNX, UPCoM) theo scan_mode:
       - PENDING_ONLY: Chỉ quét các mã CHƯA CÓ BCTC trong kỳ (Tối ưu tốc độ, chống quét thừa).
       - ALL: Quét toàn bộ danh mục (Tuần tra bổ sung đính chính / giải trình).
       - WATCHLIST: Chỉ quét danh sách mã người dùng chỉ định.
    3. Quét song song đa luồng.
    4. Đối chiếu dim_period:
       - Đã có trong kho -> status = 'ALREADY_EXISTS', bỏ qua không báo.
       - Chưa có trong kho (MỚI) -> status = 'NEW', bắn Telegram (gom 1 thông báo/đợt), chèn vào dim_period.
    """
    conn = get_db_connection()
    
    # 1. Tính toán mốc thời gian
    last_day = calendar.monthrange(selected_year, selected_month)[1]
    
    # Nếu là tháng hiện tại thì ngày kết thúc là hôm nay hoặc cuối tháng
    from_date_str = f"01/{selected_month:02d}/{selected_year}"
    to_date_str = f"{last_day:02d}/{selected_month:02d}/{selected_year}"
    target_month_str = f"{selected_month:02d}/{selected_year}"
    
    start_dt = VN_TZ.localize(datetime(selected_year, selected_month, 1, 0, 0, 0))
    end_dt = VN_TZ.localize(datetime(selected_year, selected_month, last_day, 23, 59, 59))
    start_ts = int(start_dt.timestamp())
    end_ts = int(end_dt.timestamp())
    
    # 2. Lấy danh sách doanh nghiệp theo hàng đợi thông minh
    companies = get_target_companies(
        exchanges=selected_exchanges,
        scan_mode=scan_mode,
        selected_month=selected_month,
        selected_year=selected_year,
        watchlist=watchlist
    )
    total_companies = len(companies)
    
    stats = {
        "scan_mode": scan_mode,
        "total_targets": total_companies,
        "scanned": 0,
        "total_found_files": 0,
        "already_exists_count": 0,
        "new_count": 0,
        "telegram_sent_count": 0,
        "results": []
    }
    
    if total_companies == 0:
        conn.close()
        return stats
        
    def _worker(comp):
        ticker = comp['ticker']
        cid = comp.get('id')
        cname = comp.get('company_name', f"CTCP {ticker}")
        ex = comp.get('exchange', 'HOSE')
        
        if ex == 'HOSE':
            return scan_hose_company_media(ticker, cid, cname, start_ts, end_ts)
        else:
            return scan_hnx_company_reports(ticker, ex, cname, from_date_str, to_date_str, target_month_str)

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {executor.submit(_worker, c): c for c in companies}
        for future in futures:
            comp = futures[future]
            stats["scanned"] += 1
            
            try:
                records = future.result()
                if records:
                    new_groups = {}
                    for rec in records:
                        stats["total_found_files"] += 1
                        
                        # ĐỐI CHIẾU KHO DỮ LIỆU dim_period
                        exists = check_exists_in_dim_period(
                            conn,
                            ticker=rec['ticker'],
                            pdf_url=rec.get('pdf_url', ''),
                            file_name=rec.get('file_name', ''),
                            published_date=rec.get('published_date', ''),
                            period_id=rec.get('period_id', '')
                        )
                        
                        if exists:
                            stats["already_exists_count"] += 1
                            rec['check_status'] = 'ALREADY_EXISTS'
                            rec['note'] = 'Đã có trong kho dim_period (Bỏ qua)'
                        else:
                            stats["new_count"] += 1
                            rec['check_status'] = 'NEW'
                            # Nhóm theo đợt công bố: (term_name, published_date)
                            g_key = (rec.get('term_name', ''), rec.get('published_date', ''))
                            if g_key not in new_groups:
                                new_groups[g_key] = []
                            new_groups[g_key].append(rec)
                            
                        stats["results"].append(rec)

                    # Gửi đúng 1 thông báo cho mỗi đợt công bố mới
                    for g_key, g_files in new_groups.items():
                        # Lưu tất cả tệp mới vào kho
                        for rec in g_files:
                            insert_new_to_dim_period(conn, rec)
                            
                        if send_telegram:
                            # Gom toàn bộ file đính kèm thành 1 thông báo chuẩn
                            msg = format_grouped_announcement(g_files)
                            cid_str = str(chat_id).strip() if chat_id else "-1003740017431"
                            if cid_str.startswith("-") and not cid_str.startswith("-100"):
                                cid_str = f"-100{cid_str.lstrip('-')}"
                            token = bot_token or load_config().get('telegram', {}).get('bot_token')
                            
                            try:
                                r_tg = requests.post(
                                    f"https://api.telegram.org/bot{token}/sendMessage",
                                    json={"chat_id": cid_str, "text": msg, "parse_mode": "HTML", "disable_web_page_preview": True},
                                    timeout=10
                                )
                                if r_tg.status_code == 200:
                                    stats["telegram_sent_count"] += 1
                                    for rec in g_files:
                                        rec['note'] = 'Mới phát hiện ➔ Đã gửi 1 tin Telegram tổng hợp & Lưu vào kho'
                                else:
                                    for rec in g_files:
                                        rec['note'] = f'Lỗi Telegram ({r_tg.status_code}) & Lưu vào kho'
                            except Exception as e_tg:
                                for rec in g_files:
                                    rec['note'] = f'Lỗi gửi Telegram ({e_tg}) & Lưu vào kho'
                                    
                            time.sleep(1.0)
                        else:
                            for rec in g_files:
                                rec['note'] = 'Mới phát hiện ➔ Đã lưu vào kho (Tắt gửi Telegram)'
            except Exception as e:
                pass
                
            if progress_callback:
                progress_callback(stats["scanned"], total_companies, comp['ticker'], stats)

    conn.close()
    return stats

import os
import sys
import json
import time
import re
import sqlite3
import requests
import urllib3
import pandas as pd
from bs4 import BeautifulSoup
from concurrent.futures import ThreadPoolExecutor

urllib3.disable_warnings()
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CSV_FILE = os.path.join(BASE_DIR, "Danh_sach_DN_cong_bo_BCTC_Quy.csv")
CHECKPOINT_FILE = os.path.join(BASE_DIR, "upcom_466_checkpoint.json")
EXCEL_OUTPUT = os.path.join(BASE_DIR, "UPCoM_466_Kiem_Tra_BCTC_Q3.xlsx")
DB_PATH = os.path.join(BASE_DIR, "bctc_alert.db")

print("=" * 70)
print("🚀 BẮT ĐẦU KIỂM TRA CHÍNH XÁC TỪNG MÃ TRONG 466 DOANH NGHIỆP UPCOM CÔNG BỐ BCTC QUÝ 3/2026")
print("=" * 70)

# 1. Đọc dữ liệu đầu vào UPCoM
df_all = pd.read_csv(CSV_FILE)
df_upcom = df_all[df_all['exchange'] == 'UPCoM'].copy()
tickers = df_upcom['ticker'].tolist()
print(f"Tổng số mã UPCoM cần kiểm tra: {len(tickers)} mã")

# Khởi tạo kết quả trống
results = {}
if os.path.exists(CHECKPOINT_FILE):
    try:
        with open(CHECKPOINT_FILE, 'r', encoding='utf-8') as f:
            results = json.load(f)
        print(f"Đã tải {len(results)} kết quả từ checkpoint trước đó.")
    except Exception:
        results = {}

headers = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
    'X-Requested-With': 'XMLHttpRequest'
}

def check_single_upcom_ticker(ticker):
    if ticker in results and results[ticker].get('checked'):
        return ticker, results[ticker]
        
    res = {
        'ticker': ticker,
        'has_q3': False,
        'title': '',
        'pub_date': '',
        'article_id': None,
        'raw_url': '',
        'pdf_urls': [],
        'pdf_names': [],
        'checked': True
    }
    
    found = False
    for ep in ['/ModuleIssuer/List/BaoCaoDinhKy', '/ModuleIssuer/List/ThongTinCongBo']:
        url = f"https://hnx.vn{ep}"
        payload = {
            'pMarketCode': '', 'pNumPage': 1, 'pAction': 0,
            'pNhomTin': '', 'pTieuDeTin': '', 'pStockCode': ticker,
            'pFromDate': '', 'pToDate': '', 'pOrderBy': '', 'pNumRecord': 10
        }
        try:
            r = requests.post(url, data=payload, headers=headers, verify=False, timeout=8)
            if r.status_code == 200:
                soup = BeautifulSoup(r.text, 'html.parser')
                for tr in soup.find_all('tr'):
                    tds = tr.find_all('td')
                    if len(tds) >= 3:
                        date_str = tds[1].text.strip()
                        title = tds[2].text.strip()
                        a = tds[2].find('a')
                        onclick = a.get('onclick', '') if a else ''
                        
                        # BỘ LỌC CHẶN NĂM CŨ (2000-2025)
                        if re.search(r'\b(200[0-9]|201[0-9]|202[0-5])\b', title):
                            continue
                        if '2026' not in date_str:
                            continue
                            
                        # ĐIỀU KIỆN NHẬN DIỆN BCTC QUÝ 3/2026:
                        # 1. Có từ khóa Q3 / Quý 3 / Quý III / 9 tháng
                        # 2. Thuộc loại BCTC / Kết quả kinh doanh / Giải trình lợi nhuận
                        is_q3 = bool(re.search(r'(quý\s*3|q3|quý\s*iii|9\s*tháng)', title.lower()))
                        is_bctc_kw = any(k in title.lower() for k in [
                            'báo cáo tài chính', 'bctc', 'giải trình', 'lợi nhuận', 'kqkd', 'kết quả kinh doanh'
                        ])
                        
                        if is_q3 and is_bctc_kw:
                            m_id = re.search(r'XemChiTietDetailArticlesByID\((\d+)', onclick)
                            art_id = m_id.group(1) if m_id else None
                            
                            res['has_q3'] = True
                            res['title'] = title
                            res['pub_date'] = date_str
                            res['article_id'] = art_id
                            
                            # Nếu có article_id, lấy link tải PDF từ trang RSS detail của HNX/UPCoM
                            if art_id:
                                detail_url = f"https://hnx.vn/tin-cung-cap-rss-vi_vn-{art_id}-1.html"
                                res['raw_url'] = detail_url
                                try:
                                    r_det = requests.get(detail_url, headers={'User-Agent': headers['User-Agent']}, verify=False, timeout=5)
                                    if r_det.status_code == 200:
                                        s_det = BeautifulSoup(r_det.text, 'html.parser')
                                        for a_file in s_det.find_all('a', href=True):
                                            h = a_file['href']
                                            txt = a_file.text.strip()
                                            if ('.pdf' in h.lower() or '.zip' in h.lower()) and 'ftp' in h:
                                                res['pdf_urls'].append(h)
                                                res['pdf_names'].append(txt or os.path.basename(h))
                                except Exception:
                                    pass
                            found = True
                            break
        except Exception:
            pass
        if found:
            break
            
    return ticker, res

# Thực hiện quét song song đa luồng
remaining_tickers = [t for t in tickers if t not in results or not results[t].get('checked')]
print(f"Cần kiểm tra: {len(remaining_tickers)} mã (Đã có sẵn: {len(results)} mã)")

start_time = time.time()
with ThreadPoolExecutor(max_workers=12) as executor:
    futures = [executor.submit(check_single_upcom_ticker, t) for t in remaining_tickers]
    for idx, f in enumerate(futures, 1):
        try:
            t, r = f.result(timeout=12)
            results[t] = r
            if r['has_q3']:
                print(f" [ĐÃ CÓ Q3/2026] {t}: {r['title']} ({r['pub_date']})")
            if idx % 25 == 0 or idx == len(remaining_tickers):
                print(f"--- Tiến độ: {idx}/{len(remaining_tickers)} ({idx*100//len(remaining_tickers)}%) - Đã tìm thấy: {sum(1 for v in results.values() if v.get('has_q3'))} mã có BCTC Q3/2026 ---")
                with open(CHECKPOINT_FILE, 'w', encoding='utf-8') as cf:
                    json.dump(results, cf, ensure_ascii=False, indent=2)
        except Exception:
            pass

print(f"\n Hoàn tất quét 466 mã UPCoM trong {time.time()-start_time:.1f}s.")

# Nạp vào database bctc_alert.db các mã UPCoM đã có BCTC Q3/2026
conn = sqlite3.connect(DB_PATH)
cur = conn.cursor()
added_count = 0
for t, r in results.items():
    if r.get('has_q3') and r.get('article_id'):
        uid = f"HNX_{r['article_id']}"
        cur.execute("SELECT id FROM alert_disclosures WHERE id = ?", (uid,))
        if not cur.fetchone():
            cur.execute("""
                INSERT INTO alert_disclosures
                (id, source, ticker, title, category, published_time, raw_url, pdf_urls, pdf_names, downloaded_paths)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                uid, 'HNX/UPCoM', t, r['title'], 'BCTC',
                r['pub_date'], r.get('raw_url', ''),
                json.dumps(r['pdf_urls']), json.dumps(r['pdf_names']), json.dumps([])
            ))
            added_count += 1
conn.commit()
conn.close()
print(f" Đã đồng bộ {added_count} thông báo Q3/2026 mới của sàn UPCoM vào Database cảnh báo.")

# Xuất Báo cáo Excel chuẩn đẹp
records = []
for idx, row in df_upcom.iterrows():
    t = row['ticker']
    r = results.get(t, {})
    has_q3 = r.get('has_q3', False)
    records.append({
        'STT': len(records) + 1,
        'Mã CK': t,
        'Tên Doanh Nghiệp': row['company_name'],
        'Ngành Nghề': row['industry_1'],
        'Trạng Thái BCTC Q3/2026': ' ĐÃ CÔNG BỐ' if has_q3 else '⏳ Chưa công bố',
        'Ngày Giờ Công Bố (UPCoM)': r.get('pub_date', ''),
        'Tiêu Đề Công Bố': r.get('title', ''),
        'Tệp PDF Đính Kèm': r.get('pdf_urls', [''])[0] if r.get('pdf_urls') else '',
        'Link Chi Tiết UPCoM': r.get('raw_url', f"https://hnx.vn/vi-vn/cophieu-etfs/chi-tiet-chung-khoan-uc-{t.lower()}.html")
    })

df_out = pd.DataFrame(records)
with pd.ExcelWriter(EXCEL_OUTPUT, engine='openpyxl') as writer:
    df_out.to_excel(writer, sheet_name='UPCoM_466_BCTC_Q3', index=False)

print(f" Đã xuất báo cáo đối soát ra file Excel: {EXCEL_OUTPUT}")
print("=" * 70)

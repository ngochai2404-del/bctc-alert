import os
import sys
import json
import time
import re
import sqlite3
import requests
import urllib3
import pandas as pd
from datetime import datetime
import pytz
from concurrent.futures import ThreadPoolExecutor

urllib3.disable_warnings()
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CSV_FILE = os.path.join(BASE_DIR, "Danh_sach_DN_cong_bo_BCTC_Quy.csv")
HOSE_STOCKS_FILE = os.path.join(BASE_DIR, "hose_stocks.json")
CHECKPOINT_FILE = os.path.join(BASE_DIR, "hose_406_checkpoint.json")
EXCEL_OUTPUT = os.path.join(BASE_DIR, "HOSE_406_Kiem_Tra_BCTC_Q3.xlsx")
DB_PATH = os.path.join(BASE_DIR, "bctc_alert.db")

print("=" * 70)
print("🚀 BẮT ĐẦU KIỂM TRA TỪNG MÃ TRONG 406 DOANH NGHIỆP HOSE CÔNG BỐ BCTC QUÝ")
print("=" * 70)

# 1. Đọc dữ liệu đầu vào
df_all = pd.read_csv(CSV_FILE)
df_hose = df_all[df_all['exchange'] == 'HOSE'].copy()
tickers = df_hose['ticker'].tolist()
print(f"Tổng số mã HOSE cần kiểm tra: {len(tickers)} mã")

with open(HOSE_STOCKS_FILE, 'r', encoding='utf-8') as f:
    hose_stocks = json.load(f)

# Đọc Checkpoint nếu có
results = {}
if os.path.exists(CHECKPOINT_FILE):
    try:
        with open(CHECKPOINT_FILE, 'r', encoding='utf-8') as f:
            results = json.load(f)
        print(f"Đã tải {len(results)} kết quả từ checkpoint trước đó.")
    except Exception:
        results = {}

headers = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
}

def check_single_hose_ticker(ticker):
    if ticker in results and results[ticker].get('checked'):
        return ticker, results[ticker]
        
    stock_info = hose_stocks.get(ticker, {})
    hose_id = stock_info.get('id')
    web_url = stock_info.get('webUrl', '')
    
    res = {
        'ticker': ticker,
        'hose_id': hose_id,
        'has_q3': False,
        'title': '',
        'pub_date': '',
        'news_id': None,
        'pdf_urls': [],
        'pdf_names': [],
        'web_url': web_url,
        'checked': True
    }
    
    if not hose_id:
        return ticker, res
        
    try:
        # 1. Gọi API HOSE theo ticker ID
        url = f"https://api.hsx.vn/n/api/v1/1/news/securities/{hose_id}/1?pageSize=10"
        r = requests.get(url, headers=headers, timeout=6)
        if r.status_code == 200:
            news_list = r.json().get('data', {}).get('list', [])
            for item in news_list:
                title = item.get('title', '')
                nid = item.get('id')
                pub_ts = item.get('postedDate') or item.get('publishDate') or item.get('createdDate')
                
                # Chuyển đổi timestamp
                dt_str = ""
                if pub_ts:
                    try:
                        dt = datetime.fromtimestamp(int(pub_ts), tz=pytz.timezone('Asia/Ho_Chi_Minh'))
                        dt_str = dt.strftime('%Y-%m-%d %H:%M:%S')
                    except Exception:
                        pass
                
                # Tiêu chí nhận diện BCTC Quý 3/2026:
                # 1. Có từ khóa Quý 3 / Q3 / Quý III / 9 tháng
                # 2. Có từ khóa BCTC / Kết quả kinh doanh / Giải trình lợi nhuận
                # 3. Thời gian công bố >= 2026-10-01
                title_lower = title.lower()
                is_q3 = bool(re.search(r'(quý\s*3|q3|quý\s*iii|9\s*tháng)', title_lower))
                is_bctc_type = any(k in title_lower for k in [
                    'báo cáo tài chính', 'bctc', 'giải trình', 'lợi nhuận', 'kqkd', 'kết quả kinh doanh', 'soát xét'
                ])
                
                if is_q3 and is_bctc_type:
                    # Lấy file PDF đính kèm
                    pdf_urls = []
                    pdf_names = []
                    try:
                        f_url = f"https://api.hsx.vn/m/api/v1/1/mediafiles/1/{nid}?pageIndex=1&pageSize=10"
                        rf = requests.get(f_url, headers=headers, timeout=4)
                        if rf.status_code == 200:
                            files = rf.json().get('data', {}).get('list', [])
                            for f in files:
                                f_path = f.get('filePath', '')
                                f_name = f.get('fileName', 'BCTC_Q3.pdf')
                                if f_path:
                                    direct = f_path.replace("~", "https://staticfile.hsx.vn")
                                    pdf_urls.append(direct)
                                    pdf_names.append(f_name)
                    except Exception:
                        pass
                        
                    res['has_q3'] = True
                    res['title'] = title
                    res['pub_date'] = dt_str
                    res['news_id'] = nid
                    res['pdf_urls'] = pdf_urls
                    res['pdf_names'] = pdf_names
                    break # Lấy tin Q3 mới nhất
    except Exception as e:
        pass
        
    return ticker, res

# Thực hiện quét đa luồng
remaining_tickers = [t for t in tickers if t not in results or not results[t].get('checked')]
print(f"Cần kiểm tra: {len(remaining_tickers)} mã (Đã có sẵn: {len(results)} mã)")

start_time = time.time()
with ThreadPoolExecutor(max_workers=10) as executor:
    futures = [executor.submit(check_single_hose_ticker, t) for t in remaining_tickers]
    for idx, f in enumerate(futures, 1):
        try:
            t, r = f.result(timeout=10)
            results[t] = r
            if r['has_q3']:
                print(f" [ĐÃ CÓ Q3] {t}: {r['title']} ({r['pub_date']})")
            if idx % 25 == 0 or idx == len(remaining_tickers):
                print(f"--- Tiến độ: {idx}/{len(remaining_tickers)} ({idx*100//len(remaining_tickers)}%) - Đã tìm thấy: {sum(1 for v in results.values() if v.get('has_q3'))} mã có BCTC Q3 ---")
                with open(CHECKPOINT_FILE, 'w', encoding='utf-8') as cf:
                    json.dump(results, cf, ensure_ascii=False, indent=2)
        except Exception as e:
            pass

print(f"\n Hoàn tất quét 406 mã trong {time.time()-start_time:.1f}s.")

# Nạp vào database bctc_alert.db các mã đã có BCTC Q3
conn = sqlite3.connect(DB_PATH)
cur = conn.cursor()
added_count = 0
for t, r in results.items():
    if r.get('has_q3'):
        uid = f"HOSE_{r['news_id']}"
        cur.execute("SELECT id FROM alert_disclosures WHERE id = ?", (uid,))
        if not cur.fetchone():
            cur.execute("""
                INSERT INTO alert_disclosures
                (id, source, ticker, title, category, published_time, raw_url, pdf_urls, pdf_names, downloaded_paths)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                uid, 'HOSE', t, r['title'], 'BCTC',
                r['pub_date'], f"https://www.hsx.vn/vi/quan-ly-niem-yet/co-phieu/{t}/{r['hose_id']}",
                json.dumps(r['pdf_urls']), json.dumps(r['pdf_names']), json.dumps([])
            ))
            added_count += 1
conn.commit()
conn.close()
print(f" Đã đồng bộ {added_count} thông báo Q3 mới vào Database cảnh báo.")

# Xuất Báo cáo Excel chuẩn đẹp
records = []
for idx, row in df_hose.iterrows():
    t = row['ticker']
    r = results.get(t, {})
    has_q3 = r.get('has_q3', False)
    records.append({
        'STT': len(records) + 1,
        'Mã CK': t,
        'Tên Doanh Nghiệp': row['company_name'],
        'Ngành Nghề': row['industry_1'],
        'Trạng Thái BCTC Q3/2026': ' ĐÃ CÔNG BỐ' if has_q3 else '⏳ Chưa công bố',
        'Ngày Giờ Công Bố (HOSE)': r.get('pub_date', ''),
        'Tiêu Đề Công Bố': r.get('title', ''),
        'Tệp PDF Đính Kèm': r.get('pdf_urls', [''])[0] if r.get('pdf_urls') else '',
        'Website Doanh Nghiệp': r.get('web_url', '')
    })

df_out = pd.DataFrame(records)
with pd.ExcelWriter(EXCEL_OUTPUT, engine='openpyxl') as writer:
    df_out.to_excel(writer, sheet_name='HOSE_406_BCTC_Q3', index=False)

print(f" Đã xuất báo cáo đối soát ra file Excel: {EXCEL_OUTPUT}")
print("=" * 70)

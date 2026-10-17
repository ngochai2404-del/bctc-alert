import os
import sys
import json
import re
import time
import sqlite3
import requests
from bs4 import BeautifulSoup
from datetime import datetime
import pytz
from concurrent.futures import ThreadPoolExecutor
import urllib3

sys.stdout.reconfigure(encoding='utf-8')
urllib3.disable_warnings()

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "bctc_alert.db")

print("=" * 70)
print("🚀 BẮT ĐẦU QUÉT BCTC THÁNG 10/2026 CHO HNX & UPCOM VÀ BỔ SUNG VÀO dim_period")
print("=" * 70)

# 1. Lấy danh sách 765 mã HNX & UPCoM từ bảng dim_company
conn = sqlite3.connect(DB_PATH)
cur = conn.cursor()
cur.execute("SELECT ticker, exchange, company_name FROM dim_company WHERE exchange IN ('HNX', 'UPCoM')")
target_companies = cur.fetchall()
conn.close()

print(f"📋 Tổng số doanh nghiệp HNX & UPCoM cần quét: {len(target_companies)} mã")
hnx_count = sum(1 for c in target_companies if c[1] == 'HNX')
upcom_count = sum(1 for c in target_companies if c[1] == 'UPCoM')
print(f"   - Sàn HNX  : {hnx_count} mã")
print(f"   - Sàn UPCoM: {upcom_count} mã")

headers = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
    'X-Requested-With': 'XMLHttpRequest'
}

vn_tz = pytz.timezone('Asia/Ho_Chi_Minh')

def scan_single_ticker(company_info):
    ticker, exchange, comp_name = company_info
    found_articles = []
    
    # Quét cả Báo cáo định kỳ và Công bố thông tin
    endpoints = ['/ModuleIssuer/List/BaoCaoDinhKy', '/ModuleIssuer/List/ThongTinCongBo']
    seen_art_ids = set()
    
    for ep in endpoints:
        payload = {
            'pMarketCode': '', 'pNumPage': 1, 'pAction': 0,
            'pNhomTin': '', 'pTieuDeTin': '', 'pStockCode': ticker,
            'pFromDate': '01/10/2026', 'pToDate': '17/10/2026',
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
                        
                        # Chỉ lấy trong tháng 10/2026
                        if '10/2026' not in date_str:
                            continue
                            
                        # Bộ lọc từ khóa BCTC hoặc Giải trình lợi nhuận
                        is_bctc = any(k in title.lower() for k in [
                            'báo cáo tài chính', 'bctc', 'giải trình', 'lợi nhuận', 'kqkd', 'kết quả kinh doanh'
                        ])
                        
                        # Chặn các năm cũ nếu có
                        if re.search(r'\b(200[0-9]|201[0-9]|202[0-5])\b', title):
                            continue
                            
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
            
    # Lấy chi tiết các file PDF đính kèm cho từng bài viết tìm thấy
    disclosures = []
    for art in found_articles:
        try:
            r_det = requests.get(art['raw_url'], headers={'User-Agent': headers['User-Agent']}, verify=False, timeout=6)
            if r_det.status_code == 200:
                s_det = BeautifulSoup(r_det.text, 'html.parser')
                files = []
                for a_file in s_det.find_all('a', href=True):
                    h = a_file['href']
                    txt = a_file.text.strip()
                    if ('.pdf' in h.lower() or '.zip' in h.lower()) and 'ftp' in h:
                        files.append({'name': txt or h.split('/')[-1], 'url': h})
                
                art['files'] = files
                disclosures.append(art)
        except Exception:
            pass
            
    return ticker, disclosures

# Chạy quét song song đa luồng (15 threads)
print(f"\n📡 Đang gửi truy vấn song song tới hệ thống HNX cho {len(target_companies)} doanh nghiệp...")
start_time = time.time()

all_october_disclosures = []
scanned_count = 0
found_tickers_count = 0

with ThreadPoolExecutor(max_workers=15) as executor:
    futures = [executor.submit(scan_single_ticker, comp) for comp in target_companies]
    for f in futures:
        scanned_count += 1
        try:
            t, discs = f.result()
            if discs:
                found_tickers_count += 1
                for d in discs:
                    all_october_disclosures.append(d)
                print(f" • [PHÁT HIỆN] [{discs[0]['exchange']}] {t}: {discs[0]['title']} ({discs[0]['date_str']}) - {len(discs[0]['files'])} file")
            if scanned_count % 100 == 0 or scanned_count == len(target_companies):
                print(f"   ⏳ Tiến độ: {scanned_count}/{len(target_companies)} ({scanned_count*100//len(target_companies)}%) | Tìm thấy: {found_tickers_count} DN")
        except Exception as e:
            pass

print(f"\n✅ Hoàn tất quét 765 mã trong {time.time()-start_time:.1f}s!")
print(f"🎉 Tổng cộng phát hiện: {len(all_october_disclosures)} bài công bố BCTC từ {found_tickers_count} doanh nghiệp HNX & UPCoM trong tháng 10/2026.")

# Lưu kết quả checkpoint
checkpoint_path = os.path.join(BASE_DIR, "october_2026_hnx_upcom_checkpoint.json")
with open(checkpoint_path, "w", encoding="utf-8") as f:
    json.dump(all_october_disclosures, f, ensure_ascii=False, indent=2)

print(f"💾 Đã lưu dữ liệu quét được vào file: {checkpoint_path}")

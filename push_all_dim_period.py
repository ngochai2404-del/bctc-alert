"""
========================================================================================
PUSH TOÀN BỘ CÁC DOANH NGHIỆP THỰC TẾ ĐÃ CÓ BCTC (dim_period) LÊN TELEGRAM
========================================================================================
- Gom nhóm theo từng đợt công bố: (ticker, term_name, published_date).
- TUYỆT ĐỐI KHÔNG TRÙNG LẶP: Mỗi đợt công bố của DN chỉ gửi đúng 1 TIN NHẮN DUY NHẤT.
- Hỗ trợ đầy đủ các mã có cả Hợp nhất và Riêng (BMP, HAX, KBC...) với 2 link tải riêng.
- Tuân thủ Rate Limiter Telegram: 3.5s / tin nhắn.
========================================================================================
"""

import os
import sys
import time
import json
import sqlite3
import requests
from datetime import datetime

# Console UTF-8
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import bctc_crawler

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "bctc_alert.db")

print("=" * 75)
print("🚀 BẮT ĐẦU PUSH TOÀN BỘ DOANH NGHIỆP BCTC THỰC TẾ LÊN TELEGRAM (ĐÃ GOM NHÓM)")
print("=" * 75)

cfg = bctc_crawler.load_config()
tg = cfg.get("telegram", {})
bot_token = tg.get("bot_token")
chat_id = tg.get("chat_id")

if not bot_token or not chat_id:
    print("❌ Lỗi: Chưa cấu hình Bot Token hoặc Chat ID trong config.json!")
    sys.exit(1)

cid_str = str(chat_id).strip()
if cid_str.startswith("-") and not cid_str.startswith("-100"):
    cid_str = f"-100{cid_str.lstrip('-')}"

print(f"🤖 Bot Token: {bot_token[:10]}...{bot_token[-5:]}")
print(f"📢 Nhóm Telegram (Chat ID): {cid_str}")

conn = sqlite3.connect(DB_PATH)
conn.row_factory = sqlite3.Row
cur = conn.cursor()

cur.execute("""
    SELECT 
        p.period_id,
        p.ticker,
        c.company_name,
        p.exchange,
        p.year_period,
        p.report_term_id,
        p.term_name,
        p.is_united,
        p.united_name,
        p.audit_status,
        p.has_explanation,
        p.published_date,
        p.published_time,
        p.created_timestamp,
        p.file_name,
        p.pdf_url,
        p.raw_url
    FROM dim_period p
    LEFT JOIN dim_company c ON p.ticker = c.ticker
    ORDER BY p.exchange, p.ticker, p.created_timestamp ASC
""")
all_rows = [dict(r) for r in cur.fetchall()]
conn.close()

print(f"📊 Tổng số tệp trong kho dim_period: {len(all_rows)} tệp.")

# Gom nhóm theo đợt công bố: (ticker, term_name, published_date)
grouped_announcements = {}
for r in all_rows:
    key = (r['ticker'], r['term_name'], r['published_date'])
    if key not in grouped_announcements:
        grouped_announcements[key] = []
    grouped_announcements[key].append(r)

distinct_count = len(grouped_announcements)
tickers_count = len(set(k[0] for k in grouped_announcements.keys()))
print(f"🎯 Sau khi gom nhóm: Có CHUẨN XÁC {distinct_count} đợt công bố BCTC từ {tickers_count} doanh nghiệp.")
print("   (Mỗi đợt công bố chỉ gửi ĐÚNG 1 TIN NHẮN DUY NHẤT, tích hợp toàn bộ link tải BCTC Hợp nhất, Riêng, Giải trình)")
print("=" * 75)

success_count = 0
failed_count = 0

for idx, (key, files) in enumerate(grouped_announcements.items(), 1):
    ticker, term_name, pub_date = key
    ex = files[0].get('exchange', '')
    
    # Tạo thông điệp gom nhóm chuẩn đẹp
    msg = bctc_crawler.format_grouped_announcement(files)
    
    # Hiển thị tóm tắt tiến trình
    file_summary = f"{len(files)} files" if len(files) > 1 else files[0].get('file_name', '')[:40]
    print(f"[{idx:>2}/{distinct_count}] Đang gửi: [{ex:<5}] {ticker:<4} - {term_name} ({file_summary})...", end=" ", flush=True)
    
    sent = False
    retries = 3
    while retries > 0 and not sent:
        try:
            r_tg = requests.post(
                f"https://api.telegram.org/bot{bot_token}/sendMessage",
                json={
                    "chat_id": cid_str,
                    "text": msg,
                    "parse_mode": "HTML",
                    "disable_web_page_preview": True
                },
                timeout=10
            )
            if r_tg.status_code == 200:
                print("✅ OK")
                success_count += 1
                sent = True
            else:
                if r_tg.status_code == 429:
                    print("⚠️ Gặp Rate Limit Telegram, chờ 5s rồi thử lại...", flush=True)
                    time.sleep(5)
                    retries -= 1
                else:
                    print(f"❌ Lỗi ({r_tg.status_code}): {r_tg.text}")
                    failed_count += 1
                    break
        except Exception as e:
            print(f"❌ Lỗi kết nối: {e}")
            retries -= 1
            time.sleep(2)

    # Giãn cách 3.5 giây để tuân thủ Telegram API rate limit
    time.sleep(3.5)

print("\n" + "=" * 75)
print("🎉 HOÀN TẤT ĐẨY TOÀN BỘ DOANH NGHIỆP CÓ BCTC LÊN TELEGRAM!")
print(f"   • Thành công: {success_count} / {distinct_count} bản tin")
print(f"   • Thất bại  : {failed_count} bản tin")
print("=" * 75)

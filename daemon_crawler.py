import os
import sys
import time
import json
import logging
from datetime import datetime
import pytz

# Cấu hình UTF-8 cho console
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(BASE_DIR, "config.json")

# Import module cào lõi
import bctc_crawler

# Cấu hình Logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(os.path.join(BASE_DIR, "crawler_daemon.log"), encoding="utf-8")
    ]
)

def load_settings():
    """Tải cấu hình từ config.json, nếu lỗi trả về giá trị mặc định an toàn."""
    default_config = {
        "scan_interval_seconds": 30,
        "filter_mode": "PENDING_ONLY",
        "watchlist": [],
        "telegram": {
            "enabled": True,
            "bot_token": "",
            "chat_id": ""
        },
        "max_workers": 15
    }
    if os.path.exists(CONFIG_PATH):
        try:
            with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                cfg = json.load(f)
                default_config.update(cfg)
        except Exception as e:
            logging.warning(f"Không thể đọc config.json: {e}")
    return default_config

def main():
    logging.info("=" * 70)
    logging.info("🤖 BCTC ALERT DAEMON (24/7 PATROL SERVICE)")
    logging.info("   Đang khởi chạy dịch vụ tuần tra BCTC tự động trên Linux VPS...")
    logging.info("=" * 70)

    vn_tz = pytz.timezone("Asia/Ho_Chi_Minh")
    loop_count = 0

    while True:
        try:
            loop_count += 1
            cfg = load_settings()
            
            now_vn = datetime.now(vn_tz)
            curr_month = now_vn.month
            curr_year = now_vn.year

            scan_mode = cfg.get("filter_mode", "PENDING_ONLY")
            if scan_mode == "QUARTERLY_ONLY":
                scan_mode = "PENDING_ONLY"  # Khuyên dùng chế độ quét nhanh cho daemon

            interval = int(cfg.get("scan_interval_seconds", 30))
            tg_cfg = cfg.get("telegram", {})
            send_tg = tg_cfg.get("enabled", True)
            bot_token = tg_cfg.get("bot_token")
            chat_id = tg_cfg.get("chat_id")
            max_workers = int(cfg.get("max_workers", 15))
            watchlist = cfg.get("watchlist", [])

            logging.info(f"▶ [Vòng {loop_count}] Bắt đầu quét BCTC tháng {curr_month:02d}/{curr_year} (Chế độ: {scan_mode})...")

            start_t = time.time()
            stats = bctc_crawler.execute_crawl_and_sync(
                selected_month=curr_month,
                selected_year=curr_year,
                selected_exchanges=["HOSE", "HNX", "UPCoM"],
                scan_mode=scan_mode,
                watchlist=watchlist,
                send_telegram=send_tg,
                bot_token=bot_token,
                chat_id=chat_id,
                max_workers=max_workers
            )
            elapsed = time.time() - start_t

            scanned = stats.get("scanned", 0)
            new_cnt = stats.get("new_count", 0)
            tg_cnt = stats.get("telegram_sent_count", 0)
            exist_cnt = stats.get("already_exists_count", 0)

            if new_cnt > 0:
                logging.info(f"🔥 PHÁT HIỆN {new_cnt} BCTC MỚI! Đã gửi {tg_cnt} thông báo Telegram. (Hoàn tất trong {elapsed:.1f}s)")
            else:
                logging.info(f"✅ Vòng {loop_count} xong ({elapsed:.1f}s): {scanned} DN đã duyệt | {exist_cnt} tệp đã có trong kho | 0 tệp mới.")

            # Nghỉ ngơi theo chu kỳ cấu hình
            time.sleep(interval)

        except KeyboardInterrupt:
            logging.info("🛑 Người dùng dừng daemon (KeyboardInterrupt). Tạm biệt!")
            break
        except Exception as e:
            logging.error(f"❌ Lỗi ngoại lệ trong vòng quét daemon: {e}", exc_info=True)
            time.sleep(15)  # Tránh crash vòng lặp quá nhanh nếu mất mạng

if __name__ == "__main__":
    main()

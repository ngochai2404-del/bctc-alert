import os
import sys
import json
import logging
from datetime import datetime, date
import pytz

# Cấu hình UTF-8 cho console
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(BASE_DIR, "config.json")

# Import module cào lõi
import bctc_crawler

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)]
)

# =============================================================================
# LỊCH NGHỈ LỄ GIAO DỊCH CHỨNG KHOÁN VIỆT NAM (SỞ HOSE & HNX)
# =============================================================================
# Bao gồm các ngày nghỉ lễ chính thức theo Bộ luật Lao động và thông báo nghỉ
# giao dịch của Ủy ban Chứng khoán Nhà nước (UBCKNN), Sở HOSE và HNX.
VIETNAM_STOCK_HOLIDAYS = {
    # Năm 2026
    date(2026, 1, 1),    # Tết Dương lịch
    # Tết Nguyên Đán Bính Ngọ 2026 (28 Tết đến mùng 5 Tết)
    date(2026, 2, 14), date(2026, 2, 15), date(2026, 2, 16),
    date(2026, 2, 17), date(2026, 2, 18), date(2026, 2, 19), date(2026, 2, 20),
    # Giỗ Tổ Hùng Vương (10/3 Âm lịch) & Nghỉ bù
    date(2026, 4, 26), date(2026, 4, 27),
    # Ngày Chiến thắng 30/4 & Quốc tế Lao động 1/5
    date(2026, 4, 30), date(2026, 5, 1), date(2026, 5, 2),
    # Quốc khánh 2/9
    date(2026, 9, 1), date(2026, 9, 2), date(2026, 9, 3),

    # Năm 2027
    date(2027, 1, 1),
    date(2027, 2, 5), date(2027, 2, 6), date(2027, 2, 7), date(2027, 2, 8),
    date(2027, 2, 9), date(2027, 2, 10), date(2027, 2, 11), date(2027, 2, 12),
    date(2027, 4, 15), date(2027, 4, 16),
    date(2027, 4, 30), date(2027, 5, 1), date(2027, 5, 3),
    date(2027, 9, 2), date(2027, 9, 3),
}

def is_trading_time_and_day(now_vn: datetime) -> tuple[bool, str]:
    """Kiểm tra xem thời điểm hiện tại có phải là giờ làm việc/giao dịch hợp lệ không."""
    # 1. Kiểm tra ngày trong tuần (Thứ 2 = 0, Chủ nhật = 6)
    if now_vn.weekday() >= 5:
        weekday_name = "Thứ Bảy" if now_vn.weekday() == 5 else "Chủ Nhật"
        return False, f"Hôm nay là {weekday_name} (cuối tuần), thị trường không giao dịch."

    # 2. Kiểm tra ngày Lễ / Tết theo lịch Sở GDCK
    today_date = now_vn.date()
    if today_date in VIETNAM_STOCK_HOLIDAYS:
        return False, f"Hôm nay ({today_date.strftime('%d/%m/%Y')}) là ngày nghỉ Lễ theo lịch giao dịch của Sở GDCK."

    # 3. Kiểm tra khung giờ: 08:00 đến 17:00 (giờ Việt Nam)
    # Quy đổi ra số phút từ đầu ngày
    curr_minutes = now_vn.hour * 60 + now_vn.minute
    start_minutes = 8 * 60       # 08:00
    end_minutes = 17 * 60        # 17:00

    if not (start_minutes <= curr_minutes <= end_minutes):
        return False, f"Hiện tại là {now_vn.strftime('%H:%M:%S')} (ngoài khung giờ giao dịch 08:00 - 17:00)."

    return True, "Hợp lệ"

def load_settings():
    """Tải cấu hình từ config.json và ghi đè bằng biến môi trường (nếu có)."""
    cfg = {
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
                cfg.update(json.load(f))
        except Exception as e:
            logging.warning(f"Không thể đọc config.json: {e}")

    # Ưu tiên lấy Token bảo mật từ GitHub Secrets / Environment Variables
    env_token = os.getenv("TELEGRAM_BOT_TOKEN")
    env_chat = os.getenv("TELEGRAM_CHAT_ID")
    if env_token:
        cfg["telegram"]["bot_token"] = env_token.strip()
    if env_chat:
        cfg["telegram"]["chat_id"] = env_chat.strip()

    return cfg

def main():
    vn_tz = pytz.timezone("Asia/Ho_Chi_Minh")
    now_vn = datetime.now(vn_tz)
    logging.info(f"🕒 Giờ hiện tại tại Việt Nam: {now_vn.strftime('%Y-%m-%d %H:%M:%S')} (Thứ {now_vn.weekday() + 2})")

    # Kiểm tra điều kiện ngày thường và giờ giao dịch
    is_valid, reason = is_trading_time_and_day(now_vn)
    if not is_valid:
        logging.info(f"⏸️ BỎ QUA QUÉT: {reason}")
        sys.exit(0)

    logging.info("🚀 THỜI ĐIỂM GIAO DỊCH HỢP LỆ! Bắt đầu tiến trình kiểm tra BCTC...")
    cfg = load_settings()

    curr_month = now_vn.month
    curr_year = now_vn.year
    scan_mode = "PENDING_ONLY"  # Chế độ tối ưu cao nhất cho GitHub Actions

    tg_cfg = cfg.get("telegram", {})
    send_tg = tg_cfg.get("enabled", True)
    bot_token = tg_cfg.get("bot_token")
    chat_id = tg_cfg.get("chat_id")
    max_workers = int(cfg.get("max_workers", 15))

    stats = bctc_crawler.execute_crawl_and_sync(
        selected_month=curr_month,
        selected_year=curr_year,
        selected_exchanges=["HOSE", "HNX", "UPCoM"],
        scan_mode=scan_mode,
        watchlist=cfg.get("watchlist", []),
        send_telegram=send_tg,
        bot_token=bot_token,
        chat_id=chat_id,
        max_workers=max_workers
    )

    scanned = stats.get("scanned", 0)
    new_cnt = stats.get("new_count", 0)
    tg_sent = stats.get("telegram_sent_count", 0)
    exist_cnt = stats.get("already_exists_count", 0)

    logging.info("=" * 60)
    logging.info(f"📊 KẾT QUẢ ĐỢT QUÉT NÀY:")
    logging.info(f"  • Doanh nghiệp đã kiểm tra: {scanned}")
    logging.info(f"  • Tệp BCTC đã có trong kho: {exist_cnt}")
    logging.info(f"  • Tệp BCTC MỚI phát hiện:   {new_cnt}")
    logging.info(f"  • Đã gửi thông báo Telegram: {tg_sent}")
    logging.info("=" * 60)

    if new_cnt > 0:
        logging.info(f"🎉 Phát hiện {new_cnt} BCTC mới và đã cập nhật vào kho CSDL!")
    else:
        logging.info("💤 Không có BCTC mới nào được công bố trong đợt quét này.")

if __name__ == "__main__":
    main()

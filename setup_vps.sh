#!/bin/bash
# =============================================================================
# KỊCH BẢN THIẾT LẬP TỰ ĐỘNG BCTC ALERT TRÊN UBUNTU VPS (ORACLE CLOUD ALWAYS FREE)
# =============================================================================
set -e

echo "======================================================================"
echo "🚀 BẮT ĐẦU CÀI ĐẶT HỆ THỐNG CẢNH BÁO BCTC TRÊN UBUNTU VPS..."
echo "======================================================================"

# 1. Cập nhật hệ điều hành
echo "📦 1. Cập nhật danh mục gói phần mềm..."
sudo apt-get update -y
sudo apt-get install -y python3 python3-pip python3-venv git curl ufw

# 2. Tạo Virtualenv
echo "🐍 2. Khởi tạo môi trường ảo Python (venv)..."
if [ ! -d "venv" ]; then
    python3 -m venv venv
fi

# Kích hoạt venv và cài thư viện
echo "📥 3. Cài đặt các thư viện cần thiết..."
source venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt

# 3. Cấu hình Firewall mở Port 8501 (cho Streamlit) và 22 (SSH)
echo "🛡️ 4. Cấu hình tường lửa UFW..."
sudo ufw allow 22/tcp || true
sudo ufw allow 8501/tcp || true
sudo ufw --force enable || true

# 4. Cài đặt Systemd Services
echo "⚙️ 5. Cài đặt dịch vụ chạy ngầm 24/7 (Systemd)..."
CURRENT_DIR=$(pwd)
CURRENT_USER=$(whoami)

# Tạo file service với đường dẫn động chính xác
sudo tee /etc/systemd/system/bctc_crawler.service > /dev/null <<EOF
[Unit]
Description=BCTC 24/7 Crawler & Telegram Alert Daemon
After=network.target

[Service]
Type=simple
User=${CURRENT_USER}
WorkingDirectory=${CURRENT_DIR}
ExecStart=${CURRENT_DIR}/venv/bin/python daemon_crawler.py
Restart=always
RestartSec=10
StandardOutput=append:${CURRENT_DIR}/crawler_daemon.log
StandardError=append:${CURRENT_DIR}/crawler_daemon.log

[Install]
WantedBy=multi-user.target
EOF

sudo tee /etc/systemd/system/bctc_streamlit.service > /dev/null <<EOF
[Unit]
Description=BCTC Streamlit Dashboard Web App
After=network.target

[Service]
Type=simple
User=${CURRENT_USER}
WorkingDirectory=${CURRENT_DIR}
ExecStart=${CURRENT_DIR}/venv/bin/streamlit run streamlit_app.py --server.port 8501 --server.address 0.0.0.0 --server.headless true
Restart=always
RestartSec=10
StandardOutput=append:${CURRENT_DIR}/streamlit.log
StandardError=append:${CURRENT_DIR}/streamlit.log

[Install]
WantedBy=multi-user.target
EOF

# Nạp lại systemd và kích hoạt tự chạy khi reboot
sudo systemctl daemon-reload
sudo systemctl enable bctc_crawler
sudo systemctl enable bctc_streamlit

sudo systemctl restart bctc_crawler
sudo systemctl restart bctc_streamlit

echo ""
echo "======================================================================"
echo "🎉 CÀI ĐẶT THÀNH CÔNG!"
echo "======================================================================"
echo "• Trạng thái Bot cào BCTC: $(systemctl is-active bctc_crawler)"
echo "• Trạng thái Streamlit:   $(systemctl is-active bctc_streamlit)"
echo ""
echo "👉 Truy cập Dashboard qua trình duyệt: http://$(curl -s ifconfig.me):8501"
echo "👉 Xem log Bot: tail -f crawler_daemon.log"
echo "======================================================================"

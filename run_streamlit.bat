@echo off
cd /d "%~dp0"
chcp 65001 >nul
title BCTC Alert - Streamlit Dashboard
echo =======================================================================
echo          BCTC ALERT - CÀO DỮ LIỆU & ĐỐI CHIẾU KHO DIM_PERIOD
echo          Phạm vi: 1.171 Doanh nghiệp BCTC Quý (HOSE, HNX, UPCoM)
echo =======================================================================

:: Tự động giải phóng cổng 8501 nếu có tiến trình cũ
for /f "tokens=5" %%a in ('netstat -aon ^| findstr :8501 ^| findstr LISTENING') do (
    taskkill /F /PID %%a >nul 2>&1
)

echo Đang khởi động Streamlit App trên cổng 8501...
echo Trình duyệt sẽ tự động mở tại: http://localhost:8501
echo =======================================================================

start "" http://localhost:8501
python -m streamlit run streamlit_app.py --server.port 8501 --server.headless false

pause

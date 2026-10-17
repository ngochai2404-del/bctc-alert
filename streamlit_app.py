"""
========================================================================================
BCTC ALERT - STREAMLIT DASHBOARD
Cào dữ liệu BCTC HOSE, HNX, UPCoM cho 1.171 Doanh nghiệp báo cáo theo Quý
Đối chiếu kho dữ liệu (dim_period) & Gửi thông báo Telegram tự động
========================================================================================
"""

import os
import sys
import time
import json
import sqlite3
import pandas as pd
import streamlit as st
from datetime import datetime
import pytz

import bctc_crawler

# Cấu hình UTF-8 cho stdout console
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "bctc_alert.db")
CONFIG_PATH = os.path.join(BASE_DIR, "config.json")
VN_TZ = pytz.timezone('Asia/Ho_Chi_Minh')

# -----------------------------------------------------------------------------
# CẤU HÌNH TRANG STREAMLIT
# -----------------------------------------------------------------------------
st.set_page_config(
    page_title="BCTC Alert - Cào & Đối chiếu Báo Cáo Tài Chính",
    page_icon="⚡",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Custom CSS cho giao diện hiện đại, chuyên nghiệp
st.markdown("""
<style>
    /* Font & Layout */
    .main-header {
        font-size: 26px;
        font-weight: 700;
        color: #1E3A8A;
        margin-bottom: 4px;
    }
    .sub-header {
        font-size: 14px;
        color: #6B7280;
        margin-bottom: 20px;
    }
    .stat-card {
        background: #F8FAFC;
        border: 1px solid #E2E8F0;
        border-radius: 10px;
        padding: 14px 18px;
        text-align: center;
    }
    .stat-num {
        font-size: 24px;
        font-weight: 700;
        margin-top: 4px;
    }
    .badge-new {
        background-color: #DEF7EC;
        color: #03543F;
        padding: 3px 8px;
        border-radius: 6px;
        font-weight: 600;
        font-size: 12px;
    }
    .badge-exist {
        background-color: #F3F4F6;
        color: #4B5563;
        padding: 3px 8px;
        border-radius: 6px;
        font-weight: 600;
        font-size: 12px;
    }
    .stButton>button {
        border-radius: 8px;
        font-weight: 600;
    }
</style>
""", unsafe_allow_html=True)

# -----------------------------------------------------------------------------
# DỮ LIỆU CẤU HÌNH & KHO DỮ LIỆU
# -----------------------------------------------------------------------------
def get_db_stats():
    """Lấy thống kê từ SQLite"""
    try:
        conn = sqlite3.connect(DB_PATH)
        cur = conn.cursor()
        
        # Thống kê dim_company
        cur.execute("SELECT exchange, count(*) FROM dim_company WHERE is_quarterly_reporting = 1 GROUP BY exchange")
        comp_rows = cur.fetchall()
        comp_dict = {r[0]: r[1] for r in comp_rows}
        
        # Thống kê dim_period
        cur.execute("SELECT count(*), count(DISTINCT ticker) FROM dim_period")
        total_periods, total_period_tickers = cur.fetchone()
        
        cur.execute("SELECT exchange, count(*), count(DISTINCT ticker) FROM dim_period GROUP BY exchange")
        period_rows = cur.fetchall()
        period_dict = {r[0]: (r[1], r[2]) for r in period_rows}
        
        conn.close()
        return {
            "comp": comp_dict,
            "total_companies": sum(comp_dict.values()),
            "total_periods": total_periods,
            "total_period_tickers": total_period_tickers,
            "period_breakdown": period_dict
        }
    except Exception as e:
        return {
            "comp": {}, "total_companies": 0, "total_periods": 0,
            "total_period_tickers": 0, "period_breakdown": {}
        }

db_stats = get_db_stats()
config = bctc_crawler.load_config()
tg_cfg = config.get("telegram", {})

# -----------------------------------------------------------------------------
# SIDEBAR - BỘ ĐIỀU KHIỂN & CẤU HÌNH
# -----------------------------------------------------------------------------
with st.sidebar:
    st.markdown("### ⚙️ THIẾT LẬP THAM SỐ CÀO")
    
    # 1. Chọn khung thời gian (Theo tháng)
    st.markdown("**1. Khung thời gian (Chọn theo tháng):**")
    col_m, col_y = st.columns([1, 1])
    with col_m:
        month_options = list(range(1, 13))
        selected_month = st.selectbox("Tháng", options=month_options, index=9) # Tháng 10
    with col_y:
        year_options = [2026, 2025, 2024]
        selected_year = st.selectbox("Năm", options=year_options, index=0) # 2026
        
    last_day = 31 if selected_month in [1, 3, 5, 7, 8, 10, 12] else (28 if selected_month == 2 else 30)
    st.caption(f"📅 Khoảng ngày quét: `01/{selected_month:02d}/{selected_year}` ➔ `{last_day:02d}/{selected_month:02d}/{selected_year}`")

    st.markdown("---")
    
    # 2. Chọn Sàn
    st.markdown("**2. Sàn giao dịch:**")
    exchange_mode = st.radio(
        "Chọn phạm vi sàn:",
        options=[
            "Tất cả (1.171 mã - HOSE, HNX, UPCoM)",
            "HOSE (406 mã niêm yết)",
            "HNX (299 mã niêm yết)",
            "UPCoM (466 mã đăng ký GD)",
            "HNX & UPCoM (765 mã)"
        ],
        index=0
    )
    
    # Map sang danh sách sàn thực tế
    if "HOSE (406" in exchange_mode:
        target_exchanges = ["HOSE"]
    elif "HNX (299" in exchange_mode:
        target_exchanges = ["HNX"]
    elif "UPCoM (466" in exchange_mode:
        target_exchanges = ["UPCoM"]
    elif "HNX & UPCoM" in exchange_mode:
        target_exchanges = ["HNX", "UPCoM"]
    else:
        target_exchanges = ["HOSE", "HNX", "UPCoM"]

    st.markdown("---")
    
    # 3. Cơ chế Quét Thông Minh & Chống Trùng
    st.markdown("**3. Cơ chế Hàng Đợi Thông Minh:**")
    queue_stats = bctc_crawler.get_scan_queue_stats(selected_month, selected_year, target_exchanges)
    
    scan_mode_choice = st.radio(
        "Chọn chế độ quét:",
        options=[
            f"⚡ Quét nhanh: Chỉ mã CHƯA có BCTC ({queue_stats['pending']} mã)",
            f"🔄 Quét tuần tra: Toàn bộ ({queue_stats['total']} mã)",
            "🔥 VN30 & HNX30: 60 mã trọng yếu",
            "💎 VN100: 100 mã vốn hóa lớn & vừa",
            "🎯 Quét theo dõi: Watchlist chỉ định"
        ],
        index=0,
        help="⚡ 'Quét nhanh' tự động loại trừ các mã đã có BCTC. 'VN30 & HNX30' và 'VN100' tập trung các cổ phiếu đầu ngành có tác động lớn nhất tới thị trường."
    )
    
    watchlist_tickers = []
    if "VN30 & HNX30" in scan_mode_choice:
        scan_mode = "VN30_HNX30"
        target_tickers = sorted(bctc_crawler.VN30_TICKERS | bctc_crawler.HNX30_TICKERS)
        st.caption(f"🔥 Đang chọn **60 mã trọng yếu** (30 mã VN30 + 30 mã HNX30).")
        with st.expander("📋 Xem danh sách 60 mã VN30 & HNX30", expanded=False):
            st.write(", ".join(target_tickers))
    elif "VN100" in scan_mode_choice:
        scan_mode = "VN100"
        target_tickers = sorted(bctc_crawler.VN100_TICKERS)
        st.caption(f"💎 Đang chọn **100 mã rổ VN100** (30 mã VN30 + 70 mã VNMidcap).")
        with st.expander("📋 Xem danh sách 100 mã VN100", expanded=False):
            st.write(", ".join(target_tickers))
    elif "Watchlist" in scan_mode_choice:
        scan_mode = "WATCHLIST"
        wl_input = st.text_input("Nhập mã theo dõi (cách nhau bởi dấu phẩy):", value="HPG, BMP, SSI, VNM, KBC, FPT")
        watchlist_tickers = [x.strip().upper() for x in wl_input.split(",") if x.strip()]
        st.caption(f"🎯 Đang theo dõi {len(watchlist_tickers)} mã: {', '.join(watchlist_tickers)}")
    elif "Quét nhanh" in scan_mode_choice:
        scan_mode = "PENDING_ONLY"
    else:
        scan_mode = "ALL"

    st.markdown("---")
    
    # 4. Cấu hình Telegram
    st.markdown("**4. Cảnh báo Telegram:**")
    enable_telegram = st.checkbox("Gửi cảnh báo khi phát hiện BCTC MỚI", value=tg_cfg.get("enabled", True))
    bot_token_input = st.text_input("Telegram Bot Token:", value=tg_cfg.get("bot_token", ""), type="password")
    chat_id_input = st.text_input("Telegram Chat ID:", value=tg_cfg.get("chat_id", ""))
    
    col_tg_test, col_tg_save = st.columns([1, 1])
    with col_tg_test:
        if st.button("🔔 Test Bot"):
            if not bot_token_input or not chat_id_input:
                st.error("Chưa nhập đủ Token và Chat ID!")
            else:
                ok, res_msg = bctc_crawler.test_telegram_connection(bot_token_input, chat_id_input)
                if ok:
                    st.success("Gửi test thành công!")
                else:
                    st.error(res_msg)
    with col_tg_save:
        if st.button("💾 Lưu cấu hình"):
            config["telegram"] = {
                "enabled": enable_telegram,
                "bot_token": bot_token_input.strip(),
                "chat_id": chat_id_input.strip()
            }
            if bctc_crawler.save_config(config):
                st.success("Đã lưu!")
            else:
                st.error("Lỗi khi lưu!")
                
    st.markdown("---")
    workers_count = st.slider("Số luồng cào dữ liệu song song:", min_value=5, max_value=30, value=15, step=5)
    
    st.caption("⚡ Nguồn dữ liệu: Cổng thông tin chính thức HSX Mediafiles & Cổng HNX Công bố thông tin.")

# -----------------------------------------------------------------------------
# HEADER TRANG CHỦ
# -----------------------------------------------------------------------------
st.markdown("<div class='main-header'>⚡ BCTC ALERT - CÀO & ĐỐI CHIẾU BÁO CÁO TÀI CHÍNH</div>", unsafe_allow_html=True)
st.markdown(
    "<div class='sub-header'>Hệ thống tự động cào BCTC 1.171 doanh nghiệp báo cáo theo quý (HOSE: 406 | HNX: 299 | UPCoM: 466) — "
    "Đối chiếu kho dữ liệu <b>dim_period</b> (đã có thì không báo, mới thì gửi Telegram).</div>", 
    unsafe_allow_html=True
)

# Hiển thị tóm tắt tình trạng kho
c1, c2, c3, c4, c5 = st.columns(5)
with c1:
    st.metric("🏢 Tổng DN Quý", f"{db_stats['total_companies']:,} mã")
with c2:
    st.metric("🏛️ HOSE", f"{db_stats['comp'].get('HOSE', 0):,} mã")
with c3:
    st.metric("🏢 HNX", f"{db_stats['comp'].get('HNX', 0):,} mã")
with c4:
    st.metric("🏢 UPCoM", f"{db_stats['comp'].get('UPCoM', 0):,} mã")
with c5:
    st.metric("📚 Kho dim_period", f"{db_stats['total_periods']:,} file", f"{db_stats['total_period_tickers']} DN")

# -----------------------------------------------------------------------------
# CÁC TAB CHỨC NĂNG CHÍNH
# -----------------------------------------------------------------------------
tab_crawl, tab_dim_period, tab_dim_company, tab_telegram_preview = st.tabs([
    "🚀 Cào & Quét BCTC",
    "📚 Kho Dữ Liệu (dim_period)",
    "🏢 Danh Mục 1.171 Doanh Nghiệp (dim_company)",
    "📱 Mẫu Thông Báo Telegram"
])

# =============================================================================
# TAB 1: CÀO & QUÉT BCTC
# =============================================================================
with tab_crawl:
    st.markdown("#### 🔍 THỰC THI QUÉT & ĐỐI CHIẾU DỮ LIỆU")
    
    # Thẻ hiển thị hàng đợi thông minh
    qc1, qc2, qc3 = st.columns(3)
    if scan_mode == "VN30_HNX30":
        target_count = 60
        mode_desc = "🔥 <b>VN30 & HNX30:</b> Quét 60 mã trọng yếu (30 mã VN30 + 30 mã HNX30)."
    elif scan_mode == "VN100":
        target_count = 100
        mode_desc = "💎 <b>VN100:</b> Quét 100 mã rổ chỉ số VN100 (30 mã VN30 + 70 mã VNMidcap)."
    elif scan_mode == "WATCHLIST":
        target_count = len(watchlist_tickers)
        mode_desc = f"🎯 <b>Watchlist:</b> Chỉ quét {len(watchlist_tickers)} mã chỉ định ({', '.join(watchlist_tickers[:8])}{'...' if len(watchlist_tickers) > 8 else ''})."
    elif scan_mode == "PENDING_ONLY":
        target_count = queue_stats['pending']
        mode_desc = f"⚡ <b>Quét nhanh:</b> Bỏ qua {queue_stats['completed']} mã đã có BCTC, chỉ quét {queue_stats['pending']} mã đang chờ."
    else:
        target_count = queue_stats['total']
        mode_desc = f"🔄 <b>Quét tuần tra:</b> Quét toàn bộ {queue_stats['total']} mã (kiểm tra bổ sung giải trình/đính chính)."

    with qc1:
        st.markdown(f"<div class='filter-card'><b>🎯 Tổng doanh nghiệp theo dõi:</b><br><span style='font-size:1.3rem; color:#60a5fa; font-weight:700;'>{queue_stats['total']}</span> DN ({', '.join(target_exchanges)})</div>", unsafe_allow_html=True)
    with qc2:
        st.markdown(f"<div class='filter-card'><b>✅ Đã có BCTC trong kho:</b><br><span style='font-size:1.3rem; color:#4ade80; font-weight:700;'>{queue_stats['completed']}</span> DN ({'⚡ Bỏ qua để tăng tốc' if scan_mode == 'PENDING_ONLY' else 'Sẽ quét lại'})</div>", unsafe_allow_html=True)
    with qc3:
        st.markdown(f"<div class='filter-card'><b>⏳ Hàng đợi cần quét đợt này:</b><br><span style='font-size:1.3rem; color:#facc15; font-weight:700;'>{target_count}</span> DN ({scan_mode})</div>", unsafe_allow_html=True)

    st.markdown("<div style='height: 10px;'></div>", unsafe_allow_html=True)

    info_col1, info_col2 = st.columns([3, 1])
    with info_col1:
        st.info(
            f"🎯 **Cấu hình:** Tháng **{selected_month:02d}/{selected_year}** | Chế độ: {mode_desc} "
            f"| Gửi Telegram: **{'Bật' if enable_telegram else 'Tắt'}** | Kho đối chiếu: **dim_period ({db_stats['total_periods']} tệp đã lưu)**."
        )
    with info_col2:
        start_crawl_btn = st.button("🚀 BẮT ĐẦU CÀO DỮ LIỆU", type="primary", use_container_width=True)

    if start_crawl_btn:
        st.markdown("---")
        progress_bar = st.progress(0)
        status_text = st.empty()
        
        stat_c1, stat_c2, stat_c3, stat_c4 = st.columns(4)
        m_scanned = stat_c1.empty()
        m_found = stat_c2.empty()
        m_exist = stat_c3.empty()
        m_new = stat_c4.empty()
        
        log_expander = st.expander("📋 Nhật ký cào thời gian thực", expanded=True)
        log_placeholder = log_expander.empty()
        logs = []

        def on_progress(scanned, total, current_ticker, stats):
            pct = int((scanned / total) * 100) if total > 0 else 0
            progress_bar.progress(pct)
            status_text.markdown(f"⏳ Đang cào dữ liệu: **{scanned}/{total}** doanh nghiệp ({pct}%) — Hiện tại: `{current_ticker}`...")
            m_scanned.metric("Tiến độ quét", f"{scanned}/{total}")
            m_found.metric("Tệp BCTC phát hiện", f"{stats['total_found_files']}")
            m_exist.metric("Đã có trong kho (Bỏ qua)", f"{stats['already_exists_count']}")
            m_new.metric("BCTC MỚI (Đã báo Telegram)", f"{stats['new_count']}")

        start_time = time.time()
        with st.spinner("Đang kết nối cổng dữ liệu Sở GDCK HOSE & HNX..."):
            results = bctc_crawler.execute_crawl_and_sync(
                selected_month=selected_month,
                selected_year=selected_year,
                selected_exchanges=target_exchanges,
                scan_mode=scan_mode,
                watchlist=watchlist_tickers,
                send_telegram=enable_telegram,
                bot_token=bot_token_input.strip() if bot_token_input else None,
                chat_id=chat_id_input.strip() if chat_id_input else None,
                progress_callback=on_progress,
                max_workers=workers_count
            )
        elapsed = time.time() - start_time
        
        progress_bar.progress(100)
        status_text.success(f"🎉 Hoàn tất cào dữ liệu trong {elapsed:.1f} giây! Đã quét toàn bộ {results['scanned']} doanh nghiệp.")
        
        # Lưu kết quả vào session_state để người dùng xem và lọc
        st.session_state['last_crawl_results'] = results
        
    # Hiển thị kết quả quét (từ phiên vừa chạy hoặc session state)
    if 'last_crawl_results' in st.session_state:
        res = st.session_state['last_crawl_results']
        records = res.get("results", [])
        
        st.markdown("---")
        st.markdown(f"### 📊 KẾT QUẢ CÀO DỮ LIỆU ({len(records)} tệp BCTC tìm thấy)")
        
        # Metrics tổng kết
        rc1, rc2, rc3, rc4 = st.columns(4)
        rc1.metric("Tổng DN đã quét", f"{res.get('scanned', 0)} DN")
        rc2.metric("Tổng file BCTC", f"{res.get('total_found_files', 0)} tệp")
        rc3.metric("⚪ Đã có trong kho", f"{res.get('already_exists_count', 0)} tệp", "Bỏ qua không báo")
        rc4.metric("🟢 BCTC MỚI", f"{res.get('new_count', 0)} tệp", f"Đã gửi {res.get('telegram_sent_count', 0)} Telegram")

        if records:
            # Bộ lọc kết quả
            fcol1, fcol2 = st.columns([1, 2])
            with fcol1:
                filter_status = st.selectbox(
                    "Lọc theo trạng thái:",
                    options=["Tất cả", "🟢 Chỉ BCTC MỚI (Đã báo Telegram)", "⚪ Đã có trong kho (Bỏ qua)"]
                )
            with fcol2:
                search_ticker = st.text_input("Tìm kiếm theo mã chứng khoán (Ticker):").strip().upper()
                
            filtered_records = []
            for r in records:
                if filter_status == "🟢 Chỉ BCTC MỚI (Đã báo Telegram)" and r.get('check_status') != 'NEW':
                    continue
                if filter_status == "⚪ Đã có trong kho (Bỏ qua)" and r.get('check_status') != 'ALREADY_EXISTS':
                    continue
                if search_ticker and search_ticker not in r.get('ticker', ''):
                    continue
                filtered_records.append(r)

            # Chuyển thành DataFrame hiển thị đẹp
            table_data = []
            for r in filtered_records:
                status_label = "🟢 MỚI (Đã báo TG)" if r.get('check_status') == 'NEW' else "⚪ Đã có trong kho"
                table_data.append({
                    "Trạng thái": status_label,
                    "Mã CK": r.get('ticker'),
                    "Tên Doanh Nghiệp": r.get('company_name'),
                    "Sàn": r.get('exchange'),
                    "Kỳ BCTC": r.get('term_name'),
                    "Loại": r.get('united_name'),
                    "Ngày công bố": f"{r.get('published_date')} {r.get('published_time')}",
                    "Tên File": r.get('file_name'),
                    "Link Tải PDF": r.get('pdf_url'),
                    "Ghi chú xử lý": r.get('note')
                })
                
            df_display = pd.DataFrame(table_data)
            
            st.dataframe(
                df_display,
                use_container_width=True,
                column_config={
                    "Link Tải PDF": st.column_config.LinkColumn("Link PDF", display_text="Tải PDF")
                },
                hide_index=True
            )
            
            # Nút xuất Excel
            excel_filename = f"Ket_qua_cao_BCTC_T{selected_month}_{selected_year}.xlsx"
            excel_path = os.path.join(BASE_DIR, excel_filename)
            try:
                df_display.to_excel(excel_path, index=False)
                with open(excel_path, "rb") as f_ex:
                    st.download_button(
                        label="📥 Xuất kết quả ra file Excel (.xlsx)",
                        data=f_ex,
                        file_name=excel_filename,
                        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
                    )
            except Exception:
                pass
        else:
            st.warning("Không tìm thấy tệp BCTC nào trong khung thời gian và sàn đã chọn.")

# =============================================================================
# TAB 2: KHO DỮ LIỆU (dim_period)
# =============================================================================
with tab_dim_period:
    st.markdown("#### 📚 KHO DỮ LIỆU BÁO CÁO TÀI CHÍNH (dim_period)")
    st.caption("Kho lưu trữ lịch sử toàn bộ các BCTC đã tiếp nhận, phục vụ đối soát và chống trùng lặp cảnh báo.")

    # Tải dữ liệu từ bảng dim_period
    conn = sqlite3.connect(DB_PATH)
    query = """
        SELECT 
            p.ticker AS [Mã CK],
            c.company_name AS [Tên Doanh Nghiệp],
            p.exchange AS [Sàn],
            p.term_name AS [Kỳ BCTC],
            p.united_name AS [Loại Báo Cáo],
            p.audit_status AS [Kiểm Toán],
            p.published_date AS [Ngày Đăng],
            p.published_time AS [Giờ Đăng],
            p.file_name AS [Tên File],
            p.pdf_url AS [Link PDF],
            p.has_explanation AS [Giải Trình],
            p.updated_at AS [Cập Nhật Lúc]
        FROM dim_period p
        LEFT JOIN dim_company c ON p.ticker = c.ticker
        ORDER BY p.created_timestamp DESC
    """
    df_period = pd.read_sql_query(query, conn)
    conn.close()

    # Bộ lọc kho dữ liệu
    fc1, fc2, fc3 = st.columns([1, 1, 2])
    with fc1:
        ex_filter = st.selectbox("Lọc theo Sàn:", ["Tất cả"] + list(df_period["Sàn"].dropna().unique()))
    with fc2:
        exp_filter = st.selectbox("Lọc theo Giải trình:", ["Tất cả", "Có giải trình LN", "Không có giải trình"])
    with fc3:
        txt_search = st.text_input("Tìm kiếm Mã CK hoặc Tên Doanh Nghiệp:", "").strip().upper()

    df_period_filtered = df_period.copy()
    if ex_filter != "Tất cả":
        df_period_filtered = df_period_filtered[df_period_filtered["Sàn"] == ex_filter]
    if exp_filter == "Có giải trình LN":
        df_period_filtered = df_period_filtered[df_period_filtered["Giải Trình"] == 1]
    elif exp_filter == "Không có giải trình":
        df_period_filtered = df_period_filtered[df_period_filtered["Giải Trình"] == 0]
    if txt_search:
        df_period_filtered = df_period_filtered[
            df_period_filtered["Mã CK"].str.contains(txt_search, na=False) |
            df_period_filtered["Tên Doanh Nghiệp"].str.upper().str.contains(txt_search, na=False)
        ]

    st.markdown(f"Hiển thị **{len(df_period_filtered):,}** / **{len(df_period):,}** bản ghi BCTC trong kho:")
    
    st.dataframe(
        df_period_filtered,
        use_container_width=True,
        column_config={
            "Link PDF": st.column_config.LinkColumn("Tải File", display_text="Xem PDF")
        },
        hide_index=True
    )
    
    # Nút tải toàn bộ kho ra Excel
    out_master_excel = os.path.join(BASE_DIR, "Kho_Du_Lieu_dim_period.xlsx")
    try:
        df_period.to_excel(out_master_excel, index=False)
        with open(out_master_excel, "rb") as f_master:
            st.download_button(
                label="📥 Tải toàn bộ kho dữ liệu dim_period (.xlsx)",
                data=f_master,
                file_name="Kho_Du_Lieu_dim_period.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            )
    except Exception:
        pass

# =============================================================================
# TAB 3: DANH MỤC 1.171 DOANH NGHIỆP (dim_company)
# =============================================================================
with tab_dim_company:
    st.markdown("#### 🏢 DANH MỤC 1.171 DOANH NGHIỆP BÁO CÁO QUÝ (dim_company)")
    st.caption("Danh sách chuẩn hóa 1.171 mã cổ phiếu thuộc diện bắt buộc công bố BCTC theo Quý trên 3 sàn HOSE, HNX, UPCoM.")

    conn = sqlite3.connect(DB_PATH)
    df_company = pd.read_sql_query("""
        SELECT 
            ticker AS [Mã CK],
            id AS [ID HSX],
            company_name AS [Tên Doanh Nghiệp],
            exchange AS [Sàn],
            sector_name AS [Ngành],
            first_trading_date AS [Ngày GD Đầu Tiên],
            listing_volume AS [KL Niêm Yết / ĐKGD],
            outstanding_volume AS [KL Lưu Hành],
            foreign_owned_ratio AS [Room Ngoại (%)],
            state_owned_ratio AS [Sở Hữu Nhà Nước (%)]
        FROM dim_company
        WHERE is_quarterly_reporting = 1
        ORDER BY exchange, ticker
    """, conn)
    conn.close()

    comp_c1, comp_c2 = st.columns([1, 2])
    with comp_c1:
        f_ex_comp = st.selectbox("Lọc Sàn:", ["Tất cả", "HOSE", "HNX", "UPCoM"])
    with comp_c2:
        f_txt_comp = st.text_input("Tìm kiếm Mã CK / Tên DN trong danh mục:", "").strip().upper()

    df_comp_filtered = df_company.copy()
    if f_ex_comp != "Tất cả":
        df_comp_filtered = df_comp_filtered[df_comp_filtered["Sàn"] == f_ex_comp]
    if f_txt_comp:
        df_comp_filtered = df_comp_filtered[
            df_comp_filtered["Mã CK"].str.contains(f_txt_comp, na=False) |
            df_comp_filtered["Tên Doanh Nghiệp"].str.upper().str.contains(f_txt_comp, na=False)
        ]

    st.markdown(f"Tổng số doanh nghiệp: **{len(df_comp_filtered):,}** mã")
    st.dataframe(
        df_comp_filtered, 
        use_container_width=True, 
        hide_index=True,
        column_config={
            "ID HSX": st.column_config.NumberColumn("ID HSX", format="%d"),
            "KL Niêm Yết / ĐKGD": st.column_config.NumberColumn("KL Niêm Yết / ĐKGD", format="%,d"),
            "KL Lưu Hành": st.column_config.NumberColumn("KL Lưu Hành", format="%,d"),
            "Room Ngoại (%)": st.column_config.NumberColumn("Room Ngoại (%)", format="%.2f%%"),
            "Sở Hữu Nhà Nước (%)": st.column_config.NumberColumn("Sở Hữu Nhà Nước (%)", format="%.2f%%"),
        }
    )

# =============================================================================
# TAB 4: MẪU THÔNG BÁO TELEGRAM
# =============================================================================
with tab_telegram_preview:
    st.markdown("#### 📱 ĐỊNH DẠNG THÔNG BÁO TELEGRAM CHUẨN MẪU")
    st.caption("Mẫu tin nhắn cảnh báo BCTC tự động được gửi lên Kênh/Nhóm Telegram khi phát hiện tệp mới:")
    
    sample_item = {
        'ticker': 'HPG',
        'company_name': 'Tập đoàn Hòa Phát',
        'exchange': 'HOSE',
        'term_name': 'Báo cáo tài chính Quý 3/2026',
        'published_date': '17/10/2026',
        'published_time': '10:15:30',
        'file_name': '20261017 - HPG - BCTC Hop nhat Quy 3 nam 2026.pdf',
        'pdf_url': 'https://staticfile.hsx.vn/Uploads/UploadDocuments/2504999/20261017 - HPG - BCTC Hop nhat Quy 3 nam 2026.pdf',
        'is_united': 1,
        'has_explanation': 1
    }
    sample_text = bctc_crawler.format_telegram_alert(sample_item)
    
    col_prev1, col_prev2 = st.columns([1, 1])
    with col_prev1:
        st.markdown("**Hiển thị thực tế trên Telegram:**")
        st.markdown(f"""
        <div style="background-color: #F8FAFC; border-left: 4px solid #0088cc; padding: 14px 18px; border-radius: 8px; font-family: monospace; white-space: pre-wrap; font-size: 13px; line-height: 1.6;">
🔥 <b>HPG</b> - Tập đoàn Hòa Phát (HOSE)
<b>BCTC Q3/2026</b> - 17/10/2026 - 10:15:30
<b>Nội dung:</b> <i>20261017 - HPG - BCTC Hop nhat Quy 3 nam 2026.pdf</i>
<b>Ghi chú:</b> BCTC Hợp nhất + Giải trình
━━━━━━━━━━━━━━━━━━━━
<a href="https://staticfile.hsx.vn/example.pdf" style="color: #0088cc; font-weight: bold; text-decoration: none;">[👉] TẢI VÀ XEM TRỰC TIẾP FILE PDF BCTC</a>
        </div>
        """, unsafe_allow_html=True)
        st.caption("🔥 Thuộc VN30/HNX30 | 💎 Thuộc VN100 | Các mã còn lại giữ nguyên định dạng chuẩn.")
    with col_prev2:
        st.markdown("**Mã HTML được gửi qua Telegram API:**")
        st.code(sample_text, language="html")

    st.markdown("---")
    st.markdown("**💡 Nguyên tắc nhận diện chỉ số và đối chiếu chống trùng:**")
    st.markdown("""
    1. **Nhận diện tự động rổ chỉ số trọng yếu**:
       - `🔥 {ticker}`: Cổ phiếu thuộc rổ **VN30** (HOSE) hoặc **HNX30** (HNX).
       - `💎 {ticker}`: Cổ phiếu thuộc rổ **VN100** (nhóm vốn hóa lớn và trung bình của sàn HOSE).
       - Không thêm biểu tượng đối với các doanh nghiệp niêm yết thông thường còn lại.
    2. **Đối chiếu kho dữ liệu `dim_period`**:
       - **ĐÃ TỒN TẠI** (Cùng mã, cùng đường dẫn file hoặc tên file + ngày công bố) ➔ **Hệ thống bỏ qua, tuyệt đối KHÔNG gửi Telegram**.
       - **MỚI PHÁT HIỆN** (Doanh nghiệp vừa công bố trong phiên) ➔ **Lập tức đẩy thông báo Telegram + Chèn vào `dim_period`**.
    3. Nhờ cơ chế này, bạn có thể bấm **'Cào dữ liệu'** nhiều lần trong ngày hoặc chạy định kỳ mà không sợ bị lặp tin cũ.
    """)

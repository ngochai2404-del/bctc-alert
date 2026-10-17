# KHO DỮ LIỆU BÁO CÁO TÀI CHÍNH & CÔNG BỐ THÔNG TIN: HOSE (HSX) VS. HNX (HNX & UPCOM)

Tài liệu này tổng hợp toàn bộ kiến trúc kỹ thuật, cơ chế lưu trữ file, đặc thù công bố thông tin và bài học thực tế khi tích hợp dữ liệu Báo cáo tài chính (BCTC) giữa hai Sở giao dịch chứng khoán: **Sở GDCK TP.HCM (HOSE)** và **Sở GDCK Hà Nội (HNX - quản lý cả HNX và UPCoM)**.

---

## 1. BẢNG SO SÁNH TOÀN DIỆN KIẾN TRÚC KHO DỮ LIỆU

| Tiêu chí | HOSE (Sở GDCK TP.HCM) | HNX & UPCoM (Sở GDCK Hà Nội) |
| :--- | :--- | :--- |
| **Phạm vi quản lý** | 406 doanh nghiệp niêm yết cổ phiếu | • HNX: 299 doanh nghiệp niêm yết<br>• UPCoM: 820 doanh nghiệp ĐKGD (466 DN lớn nộp BCTC Quý) |
| **Máy chủ lưu trữ file PDF** | CDN / Static Web Storage của HOSE:<br>`https://static2.hsx.vn/upload/.../{filename}.pdf` | Cụm máy chủ FTP CIMS & OWA của HNX:<br>`https://owa.hnx.vn/ftp///cims/{Năm}/{Tháng_Tuần}/{ID}_{filename}.pdf`<br>*(Ví dụ: `.../2026/10_W3/000000016928589_VI_BCTC_Q3.2026.pdf`)* |
| **Cơ chế định danh cổ phiếu** | **Bắt buộc dùng `id` số nguyên (`hose_id`)**<br>*(Ví dụ: CLC = 2161, VNM = 2281, HPG = 2458)* | **Dùng trực tiếp mã chứng khoán (`StockCode`)**<br>*(Không dùng mã số nguyên, tham số API là: `pStockCode: 'SHS'`)* |
| **Quy ước đặt tên file PDF** | Doanh nghiệp tự do đặt tên khi upload:<br>*(Ví dụ: `20261016 - CLC - CBTT BCTC Q3.2026...pdf`)* | **Hệ thống tự động gắn tiền tố chuẩn hóa**:<br>• `VI_...`: Báo cáo tài chính tiếng Việt<br>• `EN_...`: Báo cáo tài chính tiếng Anh<br>• `CV_giai_trinh_...`: Công văn giải trình biến động lợi nhuận |
| **Tiêu đề tin công bố** | **Thường bị cộc lốc / thiếu kỳ báo cáo**:<br>Nhiều tin chỉ ghi `"CLC: Báo cáo tài chính"` và trường `postedDate` bị `null`. | **Đầy đủ, rõ ràng ngay trên tiêu đề**:<br>Doanh nghiệp bắt buộc ghi rõ: *"Báo cáo tài chính quý 3 năm 2026"* hoặc *"CBTT BCTC riêng Quý 3/2026 và giải trình biến động LN"*. |
| **Cổng công bố thông tin** | **Tách biệt 2 luồng**:<br>1. Tin tức chung: `/n/api/v1/1/news`<br>2. Kho Mediafile BCTC: `/m/api/v1/1/mediafiles/5/{hose_id}` | **Tập trung, chuyên trách**:<br>Cổng riêng **Báo cáo định kỳ** (`/ModuleIssuer/List/BaoCaoDinhKy`) và **Công bố thông tin** (`/ModuleIssuer/List/ThongTinCongBo`). |
| **Định dạng dữ liệu trả về** | **REST API (JSON thuần)**: Hiện đại, parse nhanh | **ASP.NET MVC Partial View (HTML qua AJAX)**: Phải parse DOM/HTML |
| **Tường lửa & WAF** | Mở, cho phép request từ hầu hết các IP | Rất khắt khe: **Chặn dải IP quốc tế, VPN và Cloudflare WARP**. Bắt buộc có header `X-Requested-With: XMLHttpRequest`. |

---

## 2. CHI TIẾT KHO DỮ LIỆU HOSE (HSX)

### 2.1. Cấu trúc lưu trữ và API
HOSE vận hành hệ thống microservices với các endpoint chuyên biệt:
- **Danh sách niêm yết cổ phiếu**:  
  `GET https://api.hsx.vn/l/api/v1/1/securities/stock?pageIndex=1&pageSize=1000`  
  *(Cung cấp đầy đủ `id` (hose_id), vốn điều lệ, KL niêm yết, KL lưu hành, room ngoại, thông tin liên hệ)*.
- **Kho file Báo cáo tài chính chuyên dụng**:  
  `GET https://api.hsx.vn/m/api/v1/1/mediafiles/5/{hose_id}`  
  *(Phân cấp theo trường `time` dạng `MM.YYYY`, ví dụ: `03.2026` = Quý 3/2026)*.
- **Tin tức niêm yết**:  
  `GET https://api.hsx.vn/n/api/v1/1/news`

### 2.2. Bài học kỹ thuật thực tế (Case study: CLC)
> [!WARNING]
> **Hiện tượng bỏ sót BCTC trên HOSE**:
> Vào ngày 16/10/2026, CLC công bố BCTC Quý 3/2026 nhưng bộ quét tin tức chung (`/news`) bỏ sót do:
> 1. Tiêu đề chỉ ghi `"CLC: Báo cáo tài chính"`, không hề chứa chữ "Quý 3" (chữ "Q3.2026" chỉ nằm trong tên file PDF đính kèm).
> 2. Trường `postedDate` trả về `null`.
>
> **Giải pháp khắc phục**:
> - Sử dụng trường `createdDate` (timestamp epoch giây) thay cho `postedDate`.
> - Triển khai cơ chế **Tuần tra Mediafiles chuyên dụng (`fetch_hose_mediafiles_patrol`)**: Gọi trực tiếp endpoint `/mediafiles/5/{hose_id}` của 406 công ty với đa luồng (20 threads) để quét sạch kho BCTC mà không phụ thuộc vào tiêu đề tin.

---

## 3. CHI TIẾT KHO DỮ LIỆU HNX & UPCOM

### 3.1. Cấu trúc hệ thống CIMS & OWA
Sở GDCK Hà Nội quản lý cả 2 sàn: sàn Niêm yết (HNX) và sàn Đăng ký giao dịch (UPCoM). Dữ liệu văn bản được đồng bộ từ hệ thống quản lý thông tin doanh nghiệp **CIMS**.

- **Endpoint dữ liệu niêm yết HNX**:  
  `POST https://hnx.vn/ModuleIssuer/List/ListSearch_Datas`
- **Endpoint dữ liệu ĐKGD UPCoM**:  
  `POST https://hnx.vn/ModuleIssuer/UC_Issuer/ListSearch_Datas`
- **Endpoint Báo cáo tài chính định kỳ**:  
  `POST https://hnx.vn/ModuleIssuer/List/BaoCaoDinhKy`  
  *Payload*: `{'pStockCode': ticker, 'pNumPage': 1, 'pNumRecord': 10}`
- **Server lưu trữ file FTP**:  
  `https://owa.hnx.vn/ftp///cims/{Năm}/{Tháng_Tuần}/{ArticleID}_{Tên_file}.pdf`

### 3.2. Ưu thế và Lưu ý kỹ thuật trên HNX
> [!TIP]
> **Ưu thế vượt trội của HNX**:
> Các file BCTC được tự động phân loại tiền tố:
> - `VI_...`: BCTC tiếng Việt
> - `EN_...`: BCTC tiếng Anh
> - `CV_giai_trinh_...`: Công văn giải trình biến động lợi nhuận
> Điều này giúp Bot bóc tách chính xác công văn giải trình đi kèm để gửi Telegram mà không cần đọc nội dung bên trong file PDF.

> [!CAUTION]
> **Lưu ý tường lửa (WAF) của HNX**:
> - HNX sẽ trả về lỗi `ConnectTimeoutError` hoặc `[WinError 10013]` nếu máy chủ chạy qua VPN / Cloudflare WARP. Cần chạy trực tiếp IP mạng Việt Nam hoặc tách luồng tunnel.
> - Bắt buộc khai báo header `Referer` và `X-Requested-With: XMLHttpRequest` khi gọi AJAX POST.

---

## 4. CHUẨN HÓA DỮ LIỆU TRONG CƠ SỞ DỮ LIỆU `bctc_alert.db`

Hệ thống lưu trữ tập trung vào 2 bảng cốt lõi (đã loại bỏ toàn bộ bảng tạm và tối ưu bằng `VACUUM`):

### 4.1. Bảng danh mục doanh nghiệp: `dim_company` (1.171 Doanh nghiệp)
Lưu trữ toàn bộ 1.171 doanh nghiệp bắt buộc công bố BCTC Quý (406 HOSE + 299 HNX + 466 UPCoM lớn). Dữ liệu số học và ngày tháng đã được chuẩn hóa về kiểu số nguyên (`INTEGER`), số thực (`REAL`) và chuẩn ISO (`YYYY-MM-DD`).

| STT | Tên cột | Kiểu dữ liệu | Mô tả |
| :---: | :--- | :--- | :--- |
| 1 | `ticker` | **TEXT (PK)** | Mã chứng khoán (3 ký tự) |
| 2 | `id` | **INTEGER** | Mã ID của Sở: **HOSE có ID dạng int** (VD: CLC = 2161), **HNX/UPCoM là NULL** |
| 3 | `company_name` | TEXT | Tên đầy đủ của doanh nghiệp |
| 4 | `exchange` | TEXT | Sàn giao dịch: `HOSE`, `HNX`, `UPCoM` |
| 5 | `sector_name` | TEXT | Khối ngành phân loại (Doanh nghiệp, Ngân hàng, Chứng khoán...) |
| 6 | `is_quarterly_reporting` | INTEGER | Cờ bắt buộc công bố BCTC Quý (`1`) |
| 7 | `listing_volume` | **INTEGER** | Khối lượng Niêm yết (HOSE, HNX) hoặc Khối lượng ĐKGD (UPCoM) (dạng số nguyên) |
| 8 | `outstanding_volume` | **INTEGER** | Khối lượng cổ phiếu đang lưu hành (dạng số nguyên) |
| 9 | `first_trading_date` | **TEXT** | Ngày giao dịch đầu tiên trên sàn (chuẩn ISO `YYYY-MM-DD`, hợp nhất từ niêm yết/ĐKGD) |
| 10 | `listing_date` | TEXT | Ngày niêm yết chính thức (HOSE, HNX) (`YYYY-MM-DD`) |
| 11 | `reg_date` | TEXT | Ngày đăng ký giao dịch đầu tiên (UPCoM) (`YYYY-MM-DD`) |
| 12 | `foreign_owned_ratio` | **REAL** | Tỷ lệ sở hữu nước ngoài / Room ngoại (%) (float chuẩn 2 chữ số thập phân) |
| 13 | `state_owned_ratio` | **REAL** | Tỷ lệ sở hữu nhà nước (%) (float chuẩn 2 chữ số thập phân) |
| 14 | `updated_at` | TIMESTAMP | Thời gian cập nhật bản ghi |

### 4.2. Bảng theo dõi kỳ báo cáo: `dim_period`
Lưu trữ toàn bộ các tệp Báo cáo tài chính & Giải trình phát hành chính thức trong tháng 10/2026 (278 tệp / 78 doanh nghiệp).
- **Khóa chính**: `period_id` (Cấu trúc chuẩn: `{ticker}_{year}_T{term_id}_{created_timestamp}_{idx}`).
  > *Lưu ý kỹ thuật*: Bắt buộc phải có hậu tố chỉ mục `_{idx}` vì khi doanh nghiệp nộp đồng thời cả BCTC Hợp nhất và BCTC Riêng (hoặc Giải trình) trong cùng 1 đợt (như trường hợp BMP, KBC, HAX, TTF trên sàn HOSE), máy chủ Sở GDCK gắn cùng 1 mốc thời gian `created_timestamp`. Nếu không có `_{idx}`, tệp Riêng sẽ ghi đè làm mất tệp Hợp nhất.
- **Trường dữ liệu**: `period_id`, `ticker`, `exchange`, `year_period`, `report_term_id`, `term_name`, `is_united`, `united_name`, `audit_status`, `has_explanation`, `has_bctc`, `source`, `published_date`, `published_time`, `created_timestamp`, `file_name`, `pdf_url`, `hose_news_id`, `raw_url`, `status`, `updated_at`.

---

## 5. DANH MỤC CÁC KỊCH BẢN THỰC THI (SCRIPTS)

| Tên kịch bản | Vai trò & Mục đích |
| :--- | :--- |
| [`sync_dim_company.py`](file:///d:/CODE/BCTC%20Alert/sync_dim_company.py) | **[Pipeline hợp nhất]** Đồng bộ toàn diện 1.171 DN từ Sở HOSE và Sở HNX, làm sạch số/ngày/tỷ lệ |
| [`sync_1171_dim_company.py`](file:///d:/CODE/BCTC%20Alert/sync_1171_dim_company.py) | Đồng bộ 1.171 doanh nghiệp công bố BCTC Quý vào `dim_company` |
| [`add_id_to_dim_company.py`](file:///d:/CODE/BCTC%20Alert/add_id_to_dim_company.py) | Thêm cột `id` (int) ngay sau `ticker`, nạp ID HOSE và điền NULL cho HNX/UPCoM |
| [`enrich_hnx_upcom_dim_company.py`](file:///d:/CODE/BCTC%20Alert/enrich_hnx_upcom_dim_company.py) | Quét trực tiếp bảng niêm yết HNX & ĐKGD UPCoM để lấp đầy khối lượng, ngày NY/ĐKGD, room ngoại |
| [`clean_bctc_db.py`](file:///d:/CODE/BCTC%20Alert/clean_bctc_db.py) | Dọn dẹp CSDL `bctc_alert.db`, chỉ giữ lại duy nhất `dim_company` và `dim_period` |
| [`sync_october_2026_dim_period.py`](file:///d:/CODE/BCTC%20Alert/sync_october_2026_dim_period.py) | Quét và đồng bộ BCTC phát hành trong tháng 10/2026 vào `dim_period` |
| [`update_hose_dim_period.py`](file:///d:/CODE/BCTC%20Alert/update_hose_dim_period.py) | Cập nhật chuẩn hóa 33 tệp BCTC HOSE có hậu tố `_{idx}` chống ghi đè mất file Hợp nhất |
| [`bctc_crawler.py`](file:///d:/CODE/BCTC%20Alert/bctc_crawler.py) | Module lõi cào dữ liệu HOSE/HNX, đối chiếu kho `dim_period` và bắn Telegram |
| [`streamlit_app.py`](file:///d:/CODE/BCTC%20Alert/streamlit_app.py) | Giao diện Streamlit chọn tháng, chọn sàn, cào BCTC 1.171 DN, đối chiếu kho và gửi Telegram |
| [`run_streamlit.bat`](file:///d:/CODE/BCTC%20Alert/run_streamlit.bat) | File thực thi 1-click khởi chạy Streamlit Dashboard trên cổng 8501 |
| [`bctc_alert_engine.py`](file:///d:/CODE/BCTC%20Alert/bctc_alert_engine.py) | Động cơ cảnh báo BCTC tự động đẩy Telegram theo mẫu chuẩn |

---

## 6. CƠ CHẾ CHỐNG TRÙNG LẶP & TỐI ƯU HÀNG ĐỢI THÔNG MINH (SMART QUEUE)

Trong mùa công bố BCTC, việc tuần tra 1.171 doanh nghiệp liên tục đối mặt với 2 rủi ro:
1. **Lãng phí tài nguyên & nguy cơ bị chặn IP**: Quét lặp đi lặp lại những doanh nghiệp đã công bố BCTC sẽ tiêu tốn hàng ngàn lượt gọi mạng vô ích.
2. **Spam thông báo**: Các doanh nghiệp nộp nhiều tệp cùng lúc (Hợp nhất, Riêng, Tiếng Anh, Giải trình) khiến Bot bắn hàng loạt tin nhắn trùng lặp.

Hệ thống đã thiết kế giải pháp 3 lớp toàn diện:

### 6.1. Hàng Đợi Quét Thông Minh (Smart Queue Modes)
- **⚡ Cấp 1 - Quét nhanh (Pending Only - Khuyến nghị)**:
  - Hệ thống tự động so khớp `dim_company` với `dim_period`.
  - Chỉ đưa vào hàng đợi những mã **CHƯA CÓ BCTC** trong kỳ (Ví dụ: 1.091 mã đang chờ BCTC Q3/2026).
  - Tự động bỏ qua các mã đã hoàn thành (80 mã đã có BCTC).
  - **Hiệu quả**: Tiết kiệm hơn **90% thời gian quét và request**, loại bỏ hoàn toàn nguy cơ nghẽn mạng và WAF rate limit.
- **🔄 Cấp 2 - Quét tuần tra toàn bộ (Full Patrol - 1.171 mã)**:
  - Quét toàn bộ danh mục doanh nghiệp.
  - Phù hợp chạy định kỳ cuối ngày hoặc khi cần kiểm tra xem doanh nghiệp có nộp thêm Công văn giải trình hoặc Báo cáo đính chính sau đó hay không.
- **🔥 Cấp 3 - Rổ chỉ số VN30 & HNX30 (60 mã trọng yếu)**:
  - Tập trung quét 60 mã cổ phiếu đầu ngành dẫn dắt thị trường (30 mã VN30 trên HOSE + 30 mã HNX30 trên HNX).
  - Hoàn tất quét toàn bộ chỉ trong 2-3 giây.
- **💎 Cấp 4 - Rổ chỉ số VN100 (100 mã vốn hóa lớn & vừa)**:
  - Quét 100 mã cổ phiếu thuộc rổ VN100 của sàn HOSE (gồm 30 mã VN30 + 70 mã VNMidcap).
- **🎯 Cấp 5 - Quét danh sách chỉ định (Watchlist tùy chọn)**:
  - Cho phép người dùng nhập danh sách mã trọng điểm (Ví dụ: `HPG, BMP, SSI, VNM, KBC, FPT`).
  - Phục vụ việc theo dõi tức thời các mã cổ phiếu ưu tiên cá nhân.

### 6.2. Cơ Chế Chống Trùng Khóa Chính CSDL (`period_id`)
- **Vấn đề đã xử lý (Case study: BMP, KBC, HAX trên sàn HOSE)**:
  - Tại HOSE, ngày 16/10/2026 lúc 17:02:24, BMP nộp cùng lúc 2 tệp: BCTC Hợp nhất và BCTC Riêng.
  - Cả 2 tệp đều có chung `createdDate = 1760612544`. Nếu đặt `period_id = {ticker}_{year}_T{term_id}_{createdDate}`, câu lệnh `INSERT OR REPLACE` sẽ khiến tệp Riêng ghi đè làm mất tệp Hợp nhất.
- **Giải pháp**:
  - Gắn hậu tố chỉ mục thứ tự: `period_id = f"{ticker}_{year}_T{term_id}_{created_timestamp}_{idx}"`.
  - Đảm bảo 100% không bị ghi đè dữ liệu, lưu giữ trọn vẹn cả BCTC Hợp nhất, BCTC Riêng và Giải trình.

### 6.3. Cơ Chế Gom Tin Telegram Tự Động (Grouped Announcement Push)
- **Vấn đề đã xử lý (Case study: PPE trên sàn HNX)**:
  - PPE nộp 4 tệp cùng đợt: `thongbaocbtt`, `_VI_` (tiếng Việt), `_EN_` (tiếng Anh), `giaitrinh`.
  - Nếu duyệt theo từng dòng tệp đính kèm, Bot sẽ bắn 4 tin nhắn riêng biệt làm tràn ngập nhóm chat.
- **Giải pháp**:
  - Bộ quét tự động nhóm các tệp theo `(ticker, term_name, published_date)`.
  - Gộp tất cả các tệp đính kèm trong 1 đợt công bố thành **đúng 1 tin nhắn Telegram duy nhất**.
  - Tự động trích xuất liên kết kép:  
    `[👉] TẢI BCTC HỢP NHẤT`  
    `[👉] TẢI BCTC RIÊNG`  
    `[👉] TẢI BCTC TIẾNG VIỆT`  
  - Định dạng chuẩn 6 dòng thẩm mỹ, có nhãn trạng thái trực quan (`+ BCTC Hợp nhất + BCTC Riêng + Giải trình`).

### 6.4. Phân Cấp Trực Quan Rổ Chỉ Số Trọng Yếu (VN30 / HNX30 / VN100)
- **Quy tắc gắn biểu tượng nhận diện dòng 1**:
  - `🔥 {ticker}`: Dành riêng cho cổ phiếu thuộc rổ **VN30** (như HPG, VNM, FPT, VCB...) hoặc **HNX30** (như CEO, PVS, SHS, IDC...).
  - `💎 {ticker}`: Dành riêng cho cổ phiếu thuộc rổ **VN100** (như KBC, BMP, DBC, DCM, DXG, NVL...).
  - Các cổ phiếu niêm yết thông thường còn lại: Giữ nguyên định dạng chuẩn, không thêm biểu tượng.



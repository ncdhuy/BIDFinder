const API_BASE_URL =
  (location.hostname.includes('localhost') || location.hostname.includes('127.0.0.1'))
    ? 'http://localhost:8001'
    : 'https://bidfinder.onrender.com';
    
class CustomSearchForm extends HTMLElement {
    connectedCallback() {
        this.attachShadow({ mode: 'open' });
        this.shadowRoot.innerHTML = `
            <style>
                :host {
                    /* Theme tokens */
                    --c-primary: var(--color-primary, #6C5CE7);
                    --c-primary-2: var(--color-primary-light, #7c6eea);
                    --c-accent: var(--color-accent, #FF6B6B);

                    --c-text: var(--color-text-primary, #1a1a2e);
                    --c-muted: var(--color-text-muted, #adb5bd);
                    --c-sub: #6c757d;

                    --c-border: var(--color-border, #e9ecef);
                    --c-surface: var(--color-surface, #fff);
                    --c-surface-2: var(--color-surface-2, #fbfcff);

                    --shadow-md: var(--shadow-md, 0 6px 18px rgba(16, 24, 40, 0.10));

                    /* Sizing */
                    --radius-lg: 10px;
                    --radius-md: 10px;
                    --field-pad-y: 10px;
                    --field-pad-x: 12px;
                    --font: 'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
                    --focus-ring: 0 0 0 3px rgba(108, 92, 231, 0.12);
                    }

                    * {
                    box-sizing: border-box;
                    }

                    .search-form {
                    position: relative;
                    padding: 14px;
                    border-radius: var(--radius-lg);
                    font-family: var(--font);
                    background: transparent;
                    border: 0;
                    box-shadow: none;
                    }

                    .search-form::before {
                    content: '';
                    position: absolute;
                    inset: 0;
                    border-radius: var(--radius-lg);
                    padding: 2px;
                    -webkit-mask: linear-gradient(#fff 0 0) content-box, linear-gradient(#fff 0 0);
                    -webkit-mask-composite: xor;
                    mask-composite: exclude;
                    pointer-events: none;
                    }

                    /* Title */
                    .search-title {
                    margin-bottom: 10px;
                    }

                    .search-title h2 {
                    margin: 0 0 6px;
                    font-size: 20px;
                    font-weight: 700;
                    letter-spacing: -0.3px;
                    display: flex;
                    align-items: center;
                    gap: 8px;
                    background: linear-gradient(135deg, var(--c-primary) 0%, var(--c-accent) 100%);
                    -webkit-background-clip: text;
                    -webkit-text-fill-color: transparent;
                    background-clip: text;
                    }

                    .search-subtitle {
                    margin: 0;
                    font-size: 13px;
                    line-height: 1.5;
                    color: var(--c-sub);
                    }

                    :host([hide-title]) .search-title {
                    display: none !important;
                    }

                    /* Sections */
                    .filters-section {
                    padding-top: 12px;
                    }

                    .section-label {
                    margin: 0 0 10px;
                    font-size: 14px;
                    font-weight: 600;
                    color: var(--c-text);
                    display: flex;
                    align-items: center;
                    gap: 8px;
                    }

                    .section-label::before {
                    content: '';
                    width: 4px;
                    height: 16px;
                    border-radius: 2px;
                    background: linear-gradient(135deg, var(--c-primary), var(--c-primary-2));
                    }

                    /* Grid */
                    .filters-grid {
                    display: grid;
                    grid-template-columns: repeat(5, minmax(180px, 1fr));
                    gap: 12px;
                    margin-bottom: 16px;
                    align-items: end;
                    }

                    .field {
                    display: flex;
                    flex-direction: column;
                    min-width: 0;
                    }

                    label {
                    display: block;
                    margin-bottom: 6px;
                    font-size: 12px;
                    font-weight: 600;
                    color: var(--c-text);
                    }

                    /* Unified control styles */
                    input,
                    select,
                    .multi-select-btn,
                    .multi-select-search input {
                    width: 100%;
                    padding: var(--field-pad-y) var(--field-pad-x);
                    border-radius: var(--radius-md);
                    border: 2px solid var(--c-border);
                    background: var(--c-surface);
                    font-family: inherit;
                    font-size: 13px;
                    transition: border-color 0.2s ease, box-shadow 0.2s ease, background 0.2s ease;
                    }

                    input:focus,
                    select:focus,
                    .multi-select-btn:focus {
                    outline: none;
                    border-color: var(--c-primary);
                    // box-shadow: var(--focus-ring);
                    }

                    /* Giữ highlight ô filter khi dropdown mở hoặc có focus bên trong */
                    .multi-select.open .multi-select-btn,
                    .multi-select:focus-within .multi-select-btn {
                    border-color: var(--c-primary);
                    // box-shadow: var(--focus-ring);
                    }

                    /* Ô Tìm nhanh không phát sáng */
                    .multi-select-search input:focus {
                    outline: none;
                    border-color: var(--c-border);
                    box-shadow: none;
                    }

                    input::placeholder {
                    color: var(--c-muted);
                    }

                    /* Select placeholder */
                    select {
                    color: var(--c-text) !important;
                    }

                    select.is-placeholder {
                    color: var(--c-muted) !important;
                    }

                    select option {
                    color: var(--c-text) !important;
                    }

                    /* Hide native select khi dùng custom multi */
                    select.js-hidden {
                    display: none !important;
                    }

                    /* Actions */
                    .actions {
                    display: flex;
                    justify-content: flex-end;
                    gap: 12px;
                    margin-top: 18px;
                    flex-wrap: wrap;
                    }

                    .btn {
                    min-width: 120px;
                    padding: 10px 14px;
                    border-radius: var(--radius-md);
                    border: none;
                    font-size: 13px;
                    font-weight: 600;
                    cursor: pointer;
                    display: inline-flex;
                    align-items: center;
                    justify-content: center;
                    gap: 8px;
                    transition: background 0.2s ease, box-shadow 0.2s ease, opacity 0.2s ease;
                    }

                    .btn-primary {
                    background: linear-gradient(135deg, var(--c-primary) 0%, var(--c-primary-2) 100%);
                    color: #fff;
                    box-shadow: 0 6px 16px rgba(108, 92, 231, 0.20);
                    }

                    .btn-primary:hover {
                    background: linear-gradient(135deg, #5f3dc4 0%, var(--c-primary) 100%);
                    }

                    .btn-secondary {
                    background: rgba(108, 92, 231, 0.08);
                    color: #5f3dc4;
                    box-shadow: none;
                    }

                    .btn-secondary:hover {
                    background: rgba(108, 92, 231, 0.14);
                    }

                    .btn:disabled {
                    opacity: 0.45;
                    cursor: not-allowed;
                    box-shadow: none;
                    }

                    /* Tooltip */
                    .title-with-help {
                    display: flex;
                    align-items: center;
                    gap: 8px;
                    }

                    .help-icon {
                    position: relative;
                    display: inline-flex;
                    align-items: center;
                    justify-content: center;
                    width: 20px;
                    height: 20px;
                    border-radius: 50%;
                    border: none;
                    background: rgba(108, 92, 231, 0.10);
                    color: var(--c-primary);
                    font-size: 12px;
                    font-weight: 700;
                    cursor: help;
                    transition: transform 0.2s ease, background 0.2s ease, box-shadow 0.2s ease, color 0.2s ease;
                    top: -3px;
                    }

                    .help-icon:hover {
                    background: linear-gradient(135deg, var(--c-primary) 0%, var(--c-primary-2) 100%);
                    color: #fff;
                    transform: scale(1.08);
                    box-shadow: 0 2px 8px rgba(108, 92, 231, 0.30);
                    }

                    .help-tooltip {
                    visibility: hidden;
                    opacity: 0;
                    position: absolute;
                    top: calc(100% + 8px);
                    left: 50%;
                    transform: translateX(-50%);
                    z-index: 1000;
                    width: 420px;
                    max-width: 90vw;
                    padding: 16px 18px;
                    border-radius: 10px;
                    background: #fff;
                    box-shadow: 0 8px 24px rgba(108, 92, 231, 0.2), 0 0 0 1px rgba(108, 92, 231, 0.1);
                    transition: opacity 0.2s ease, visibility 0.2s ease;
                    }

                    .help-icon:hover .help-tooltip {
                    visibility: visible;
                    opacity: 1;
                    }

                    .help-tooltip::after {
                    content: '';
                    position: absolute;
                    bottom: 100%;
                    left: 50%;
                    transform: translateX(-50%);
                    border: 6px solid transparent;
                    border-bottom-color: #fff;
                    }

                    .help-tooltip-title {
                    margin: 0 0 10px 0;
                    font-size: 14px;
                    font-weight: 600;
                    display: flex;
                    align-items: center;
                    gap: 6px;
                    background: linear-gradient(135deg, var(--c-primary) 0%, var(--c-accent) 100%);
                    -webkit-background-clip: text;
                    -webkit-text-fill-color: transparent;
                    background-clip: text;
                    }

                    .help-tooltip ul {
                    margin: 0;
                    padding-left: 18px;
                    list-style: none;
                    }

                    .help-tooltip li {
                    margin-bottom: 8px;
                    font-size: 12px;
                    line-height: 1.5;
                    color: var(--c-sub);
                    position: relative;
                    }

                    .help-tooltip li:last-child {
                    margin-bottom: 0;
                    }

                    .help-tooltip li::before {
                    content: "•";
                    position: absolute;
                    left: -14px;
                    color: var(--c-primary);
                    font-weight: 700;
                    }

                    .help-tooltip strong {
                    color: var(--c-text);
                    font-weight: 600;
                    }

                    .help-tooltip code {
                    background: rgba(108, 92, 231, 0.08);
                    padding: 2px 6px;
                    border-radius: 4px;
                    font-family: 'Courier New', monospace;
                    font-size: 11px;
                    color: var(--c-primary);
                    font-weight: 600;
                    }

                    /* Multi-select */
                    .multi-select {
                    position: relative;
                    width: 100%;
                    }

                    .multi-select-btn {
                    display: flex;
                    align-items: center;
                    justify-content: space-between;
                    gap: 10px;
                    cursor: pointer;
                    }

                    .multi-select-btn.is-placeholder {
                    color: var(--c-muted);
                    }

                    /* Text trong ô filter: 1 dòng + ellipsis */
                    .multi-select-btn-text {
                    flex: 1 1 auto;
                    min-width: 0;
                    white-space: nowrap;
                    overflow: hidden;
                    text-overflow: ellipsis;
                    }

                    .multi-select-caret {
                    flex: 0 0 auto;
                    opacity: 0.7;
                    }

                    .multi-select-popover {
                    position: absolute;
                    top: calc(100% + 8px);
                    left: 0;
                    right: 0;
                    z-index: 10050;
                    background: #fff;
                    border: 1.5px solid var(--c-border);
                    border-radius: var(--radius-md);
                    box-shadow: var(--shadow-md);
                    overflow: hidden;
                    display: none;
                    }

                    .multi-select.open .multi-select-popover {
                    display: block;
                    }

                    .multi-select-search {
                    padding: 10px 12px;
                    border-bottom: 1px solid var(--c-border);
                    background: var(--c-surface-2);
                    }

                    .multi-select-options {
                    max-height: 210px;
                    overflow: auto;
                    padding: 6px;
                    }

                    .multi-select-option {
                    display: flex;
                    align-items: center;
                    gap: 10px;
                    padding: 8px 10px;
                    border-radius: var(--radius-md);
                    cursor: pointer;
                    user-select: none;
                    }

                    .multi-select-option:hover {
                    background: rgba(108, 92, 231, 0.08);
                    }

                    .multi-select-option input[type="checkbox"] {
                    flex: 0 0 18px;
                    width: 18px;
                    height: 18px;
                    margin: 0;
                    accent-color: var(--c-primary);
                    }

                    .multi-select-option span {
                    flex: 1 1 auto;
                    min-width: 0;
                    }

                    .multi-select-footer {
                    display: flex;
                    justify-content: space-between;
                    gap: 10px;
                    padding: 10px 12px;
                    border-top: 1px solid var(--c-border);
                    background: #fff;
                    }

                    .multi-select-footer button {
                    padding: 8px 10px;
                    border-radius: var(--radius-md);
                    border: none;
                    cursor: pointer;
                    font-size: 13px;
                    font-weight: 600;
                    }

                    .multi-select-clear {
                    background: rgba(108, 92, 231, 0.08);
                    color: #5f3dc4;
                    }

                    .multi-select-done {
                    background: linear-gradient(135deg, var(--c-primary) 0%, var(--c-primary-2) 100%);
                    color: #fff;
                    }

                    /* Responsive */
                    @media (max-width: 768px) {
                    .search-form {
                        padding: 20px;
                    }
                    .filters-grid {
                        grid-template-columns: 1fr;
                    }
                    .actions {
                        flex-direction: column;
                    }
                    .btn {
                        width: 100%;
                    }
                    }

                    @media (max-width: 640px) {
                    .help-tooltip {
                        width: 320px;
                        padding: 14px 16px;
                        left: auto;
                        right: 0;
                        transform: none;
                    }
                    .help-tooltip::after {
                        left: auto;
                        right: 20px;
                        transform: none;
                    }
                    .help-tooltip-title {
                        font-size: 13px;
                    }
                    .help-tooltip li {
                        font-size: 11px;
                    }
                    }

            </style>

            <div class="search-form">
                <div class="search-title">
                    <div class="title-with-help">
                        <h2>Bộ lọc thông tin</h2>
                            <div class="help-icon">
                                i
                                <div class="help-tooltip">
                                    <div class="help-tooltip-title">
                                        💡 Mẹo tìm kiếm
                                    </div>
                                    <ul>
                                        <li>
                                            <strong>Tìm kiếm cơ bản:</strong> Nhập nhiều từ khóa để tìm KQ có tất cả từ, không phân biệt dấu và thứ tự.
                                        </li>
                                        <li>
                                            <strong>Toán tử <code>+</code>:</strong> Đặt dấu + trước từ khóa để hiện kết quả phải chứa từ.
                                        </li>
                                        <li>
                                            <strong>Toán tử <code>-</code>:</strong> Đặt dấu - trước từ khóa để loại bỏ kết quả có chứa từ.
                                        </li>
                                        <li>
                                            <strong>Toán tử <code>OR</code>:</strong> Dùng OR giữa các từ khóa để tìm KQ có chứa ít nhất một trong các từ.
                                        </li>
                                        <li>
                                            <strong>Tìm chính xác:</strong> Dùng dấu ngoặc kép <code>" "</code> để tìm cụm từ chính xác, có phân biệt dấu.
                                        </li>
                                    </ul>
                                </div>
                            </div>
                    </div>
                </div>
                
                <div class="filters-section">
                    <p class="section-label">📅 Ngày phê duyệt</p>
                    <div class="filters-grid">
                        <div class="field">
                            <label for="filter-date-from">Từ ngày</label>
                            <input id="filter-date-from" type="text" placeholder="dd/mm/yyyy">
                        </div>
                        <div class="field">
                            <label for="filter-date-to">Đến ngày</label>
                            <input id="filter-date-to" type="text" placeholder="dd/mm/yyyy">
                        </div>
                    </div>

                    <p class="section-label">📋Thông tin thầu</p>
                    <div class="filters-grid">
                        <div class="field">
                            <label for="filter-investor">Chủ đầu tư</label>
                            <input id="filter-investor" type="text" placeholder="Tên cơ sở KCB">
                        </div>
                        <div class="field">
                            <label for="filter-approval-decision">Quyết định phê duyệt</label>
                            <input id="filter-approval-decision" type="text" placeholder="VD: 01/QĐ-TTYT">
                        </div>
                        <div class="field">
                            <label for="filter-selection-method">Hình thức LCNT</label>
                            <select id="filter-selection-method" multiple>
                                <option value="">-- Chọn hình thức --</option>
                                <option value="Đấu thầu rộng rãi">Đấu thầu rộng rãi</option>
                                <option value="Đấu thầu hạn chế">Đấu thầu hạn chế</option>
                                <option value="Chỉ định thầu">Chỉ định thầu</option>
                                <option value="Chào hàng cạnh tranh">Chào hàng cạnh tranh</option>
                                <option value="Mua sắm trực tiếp">Mua sắm trực tiếp</option>
                                <option value="Tự thực hiện">Tự thực hiện</option>
                                <option value="Tham gia thực hiện của cộng đồng">Tham gia thực hiện của cộng đồng</option>
                                <option value="Đàm phán giá">Đàm phán giá</option>
                                <option value="Lựa chọn nhà thầu trong trường hợp đặc biệt">Lựa chọn nhà thầu trong trường hợp đặc biệt</option>
                                <option value="Đặt hàng">Đặt hàng</option>
                                <option value="Chào giá trực tuyến">Chào giá trực tuyến</option>
                                <option value="Chào giá trực tuyến theo quy trình rút gọn">Chào giá trực tuyến theo quy trình rút gọn</option>
                                <option value="Mua sắm trực tuyến">Mua sắm trực tuyến</option>
                            </select>
                            <div class="multi-select" data-for="filter-selection-method"></div>
                        </div>
                        <div class="field">
                            <label for="filter-place">Tỉnh/Thành phố</label>
                            <select id="filter-place" multiple>
                                <option value="">-- Chọn địa điểm --</option>

                                <option value="Tỉnh An Giang">An Giang</option>
                                <option value="Tỉnh Bà Rịa - Vũng Tàu">Bà Rịa - Vũng Tàu</option>
                                <option value="Tỉnh Bắc Giang">Bắc Giang</option>
                                <option value="Tỉnh Bắc Kạn">Bắc Kạn</option>
                                <option value="Tỉnh Bạc Liêu">Bạc Liêu</option>
                                <option value="Tỉnh Bắc Ninh">Bắc Ninh</option>
                                <option value="Tỉnh Bến Tre">Bến Tre</option>
                                <option value="Tỉnh Bình Định">Bình Định</option>
                                <option value="Tỉnh Bình Dương">Bình Dương</option>
                                <option value="Tỉnh Bình Phước">Bình Phước</option>
                                <option value="Tỉnh Bình Thuận">Bình Thuận</option>
                                <option value="Tỉnh Cà Mau">Cà Mau</option>
                                <option value="Thành phố Cần Thơ">Cần Thơ</option>
                                <option value="Tỉnh Cao Bằng">Cao Bằng</option>
                                <option value="Thành phố Đà Nẵng">Đà Nẵng</option>
                                <option value="Tỉnh Đăk Lăk">Đăk Lăk</option>
                                <option value="Tỉnh Đắk Nông">Đăk Nông</option>
                                <option value="Tỉnh Điện Biên">Điện Biên</option>
                                <option value="Tỉnh Đồng Nai">Đồng Nai</option>
                                <option value="Tỉnh Đồng Tháp">Đồng Tháp</option>
                                <option value="Tỉnh Gia Lai">Gia Lai</option>
                                <option value="Tỉnh Hà Giang">Hà Giang</option>
                                <option value="Tỉnh Hà Nam">Hà Nam</option>
                                <option value="Thành phố Hà Nội">Hà Nội</option>
                                <option value="Tỉnh Hà Tĩnh">Hà Tĩnh</option>
                                <option value="Tỉnh Hải Dương">Hải Dương</option>
                                <option value="Thành phố Hải Phòng">Hải Phòng</option>
                                <option value="Tỉnh Hậu Giang">Hậu Giang</option>
                                <option value="Thành phố Hồ Chí Minh">Hồ Chí Minh</option>
                                <option value="Tỉnh Hòa Bình">Hòa Bình</option>
                                <option value="Tỉnh Hưng Yên">Hưng Yên</option>
                                <option value="Tỉnh Khánh Hòa">Khánh Hòa</option>
                                <option value="Tỉnh Kiên Giang">Kiên Giang</option>
                                <option value="Tỉnh Kon Tum">Kon Tum</option>
                                <option value="Tỉnh Lai Châu">Lai Châu</option>
                                <option value="Tỉnh Lâm Đồng">Lâm Đồng</option>
                                <option value="Tỉnh Lạng Sơn">Lạng Sơn</option>
                                <option value="Tỉnh Lào Cai">Lào Cai</option>
                                <option value="Tỉnh Long An">Long An</option>
                                <option value="Tỉnh Nam Định">Nam Định</option>
                                <option value="Tỉnh Nghệ An">Nghệ An</option>
                                <option value="Tỉnh Ninh Bình">Ninh Bình</option>
                                <option value="Tỉnh Ninh Thuận">Ninh Thuận</option>
                                <option value="Tỉnh Phú Thọ">Phú Thọ</option>
                                <option value="Tỉnh Phú Yên">Phú Yên</option>
                                <option value="Tỉnh Quảng Bình">Quảng Bình</option>
                                <option value="Tỉnh Quảng Nam">Quảng Nam</option>
                                <option value="Tỉnh Quảng Ngãi">Quảng Ngãi</option>
                                <option value="Tỉnh Quảng Ninh">Quảng Ninh</option>
                                <option value="Tỉnh Quảng Trị">Quảng Trị</option>
                                <option value="Tỉnh Sóc Trăng">Sóc Trăng</option>
                                <option value="Tỉnh Sơn La">Sơn La</option>
                                <option value="Tỉnh Tây Ninh">Tây Ninh</option>
                                <option value="Tỉnh Thái Bình">Thái Bình</option>
                                <option value="Tỉnh Thái Nguyên">Thái Nguyên</option>
                                <option value="Tỉnh Thanh Hóa">Thanh Hóa</option>
                                <option value="Tỉnh Thừa Thiên Huế">Thừa Thiên Huế</option>
                                <option value="Tỉnh Tiền Giang">Tiền Giang</option>
                                <option value="Tỉnh Trà Vinh">Trà Vinh</option>
                                <option value="Tỉnh Tuyên Quang">Tuyên Quang</option>
                                <option value="Tỉnh Vĩnh Long">Vĩnh Long</option>
                                <option value="Tỉnh Vĩnh Phúc">Vĩnh Phúc</option>
                                <option value="Tỉnh Yên Bái">Yên Bái</option>
                            </select>
                            <div class="multi-select" data-for="filter-place"></div>
                        </div>

                        <div class="field">
                            <label for="filter-validity">Tình trạng hiệu lực</label>
                            <select id="filter-validity">
                                <option value="">-- Còn/hết hiệu lực --</option>
                                <option value="Còn hiệu lực">Còn hiệu lực</option>
                                <option value="Hết hiệu lực">Hết hiệu lực</option>
                            </select>
                        </div>
                    </div>

                    <p class="section-label">💊 Thông tin hàng hóa</p>
                    <div class="filters-grid">
                        <div class="field">
                            <label for="filter-drug-name">Tên thương mại</label>
                            <input id="filter-drug-name" type="text" placeholder="VD: Paracetamol">
                        </div>
                        <div class="field">
                            <label for="filter-active-ingredient">Tên hoạt chất</label>
                            <input id="filter-active-ingredient" type="text" placeholder="VD: Paracetamol">
                        </div>
                        <div class="field">
                            <label for="filter-concentration">Nồng độ, hàm lượng</label>
                            <input id="filter-concentration" type="text" placeholder="VD: 500mg">
                        </div>
                        <div class="field">
                            <label for="filter-route">Đường dùng</label>
                            <input id="filter-route" type="text" placeholder="VD: Uống">
                        </div>
                        <div class="field">
                            <label for="filter-dosage-form">Dạng bào chế</label>
                            <input id="filter-dosage-form" type="text" placeholder="VD: Viên nén">
                        </div>
                        <div class="field">
                            <label for="filter-specification">Quy cách đóng gói</label>
                            <input id="filter-specification" type="text" placeholder="VD: Hộp 10 vỉ x 10 viên">
                        </div>
                        <div class="field">
                            <label for="filter-drug-group">Nhóm thuốc</label>
                            <input id="filter-drug-group" type="text" placeholder="VD: N1">
                        </div>
                        <div class="field">
                            <label for="filter-reg-no">Số đăng ký</label>
                            <input id="filter-reg-no" type="text" placeholder="VD: VD-12345-18">
                        </div>
                        <div class="field">
                            <label for="filter-unit">Đơn vị tính</label>
                            <input id="filter-unit" type="text" placeholder="Ví dụ: Hộp, Viên, Lọ">
                        </div>
                    </div>

                    <p class="section-label">🏭 Nhà sản xuất</p>
                    <div class="filters-grid">
                        <div class="field">
                            <label for="filter-manufacturer">Cơ sở sản xuất</label>
                            <input id="filter-manufacturer" type="text" placeholder="Tên nhà máy/công ty">
                        </div>
                        <div class="field">
                            <label for="filter-country">Nước sản xuất</label>
                            <input id="filter-country" type="text" placeholder="VD: Việt Nam, Ấn Độ">
                        </div>
                    </div>
                </div>

                <div class="actions">
                    <button class="btn btn-secondary" id="reset-filters-btn">
                        Đặt lại
                    </button>
                    <button class="btn btn-primary" id="apply-filters-btn">
                        Áp dụng
                    </button>
                </div>
            </div>
        `;
        // ✅ Disable nút áp dụng lúc ban đầu + theo dõi input thay đổi
        this.attachInputListeners();
        this.updateApplyButtonState();
        this.setupSelectPlaceholderColors();
        this.setupDateEmptyState();

        const root = this.shadowRoot;
        
        this.createMultiSelectFromNative('filter-selection-method', {
            placeholder: '-- Chọn hình thức --',
            maxLabels: 2
        });

        this.createMultiSelectFromNative('filter-place', {
            placeholder: '-- Chọn địa điểm --',
            maxLabels: 2
        });

        const $from = root.getElementById('filter-date-from');
        const $to   = root.getElementById('filter-date-to');

        let fpFrom = null;
        let fpTo = null;

        if (window.flatpickr) {
            fpFrom = window.flatpickr($from, {
                dateFormat: 'Y-m-d',
                altInput: true,
                altFormat: 'd/m/Y',
                allowInput: true
            });

            fpTo = window.flatpickr($to, {
                dateFormat: 'Y-m-d',
                altInput: true,
                altFormat: 'd/m/Y',
                allowInput: true
            });
        }

        // Xử lý tooltip render ra ngoài shadow DOM
        const helpIcon = root.querySelector('.help-icon');
        const tooltipContent = root.querySelector('.help-tooltip');

        // Ẩn tooltip trong shadow DOM
        tooltipContent.style.display = 'none';

        // Tạo tooltip element bên ngoài shadow DOM
        let externalTooltip = null;

        helpIcon.addEventListener('mouseenter', () => {
            // Tạo tooltip mới ngoài shadow DOM
            externalTooltip = document.createElement('div');
            externalTooltip.className = 'external-tooltip';
            externalTooltip.innerHTML = tooltipContent.innerHTML;
            
            // Style cho tooltip
            externalTooltip.style.cssText = `
                position: absolute;
                background: #ffffff;
                border-radius: 10px;
                padding: 16px 18px;
                width: 420px;
                max-width: 90vw;
                box-shadow: 0 8px 24px rgba(108, 92, 231, 0.2), 0 0 0 1px rgba(108, 92, 231, 0.1);
                z-index: 999999;
                font-family: 'Inter', sans-serif;
            `;
            
            // Tính toán vị trí
            const rect = helpIcon.getBoundingClientRect();
            externalTooltip.style.top = `${rect.bottom + 8}px`;
            externalTooltip.style.left = `${rect.left + rect.width / 2 - 210}px`; // 210 = 420/2
            
            // Style cho nội dung bên trong
            const style = document.createElement('style');
            style.textContent = `
                .external-tooltip .help-tooltip-title {
                    margin: 0 0 10px 0;
                    font-size: 14px;
                    font-weight: 600;
                    background: linear-gradient(135deg, #6C5CE7 0%, #FF6B6B 100%);
                    -webkit-background-clip: text;
                    -webkit-text-fill-color: transparent;
                }
                .external-tooltip ul {
                    margin: 0;
                    padding-left: 18px;
                    list-style: none;
                }
                .external-tooltip li {
                    margin-bottom: 8px;
                    font-size: 12px;
                    line-height: 1.5;
                    color: #6c757d;
                    position: relative;
                }
                .external-tooltip li::before {
                    content: "•";
                    position: absolute;
                    left: -14px;
                    color: #6C5CE7;
                    font-weight: 700;
                }
                .external-tooltip strong {
                    color: #1a1a2e;
                    font-weight: 600;
                }
                .external-tooltip code {
                    background: rgba(108, 92, 231, 0.08);
                    padding: 2px 6px;
                    border-radius: 4px;
                    font-family: 'Courier New', monospace;
                    font-size: 11px;
                    color: #6C5CE7;
                    font-weight: 600;
                }
            `;
            document.head.appendChild(style);
            document.body.appendChild(externalTooltip);
        });

        helpIcon.addEventListener('mouseleave', () => {
            if (externalTooltip) {
                externalTooltip.remove();
                externalTooltip = null;
            }
        });

        const inputs = root.querySelectorAll('input, select');
        inputs.forEach(input => {
            input.addEventListener('keypress', (e) => {
                if (e.key === 'Enter') {
                    e.preventDefault();
                    root.getElementById('apply-filters-btn').click();
                }
            });
        });

        // Apply filters button
        root.getElementById('apply-filters-btn').addEventListener('click', () => {
            // ✅ Kiểm tra trước khi dispatch
            const applyBtn = root.getElementById('apply-filters-btn');
            if (applyBtn.disabled) {
                return; // không làm gì nếu nút đang disabled
            }

            const getSelectedValues = (id) =>
                Array.from(root.getElementById(id).selectedOptions || [])
                    .map(o => (o.value ?? '').trim())
                    .filter(Boolean);

            const payload = {
                // Thông tin thời gian
                dateFrom: root.getElementById('filter-date-from').value,
                dateTo: root.getElementById('filter-date-to').value,

                // Thông tin thầu
                investor: root.getElementById('filter-investor').value.trim(),
                approvalDecision: root.getElementById('filter-approval-decision').value.trim(),
                // selectionMethod: root.getElementById('filter-selection-method').value.trim(),
                // place: root.getElementById('filter-place').value.trim(),
                selectionMethod: getSelectedValues('filter-selection-method'),
                place: getSelectedValues('filter-place'),
                validity: root.getElementById('filter-validity').value.trim(),

                // Thông tin hàng hóa
                drugName: root.getElementById('filter-drug-name').value.trim(),
                activeIngredient: root.getElementById('filter-active-ingredient').value.trim(),
                concentration: root.getElementById('filter-concentration').value.trim(),
                route: root.getElementById('filter-route').value,
                dosageForm: root.getElementById('filter-dosage-form').value,
                specification: root.getElementById('filter-specification').value.trim(),
                drugGroup: root.getElementById('filter-drug-group').value.trim(),
                regNo: root.getElementById('filter-reg-no').value.trim(),
                unit: root.getElementById('filter-unit').value.trim(),

                // Thông tin nhà sản xuất
                manufacturer: root.getElementById('filter-manufacturer').value.trim(),
                country: root.getElementById('filter-country').value.trim()
            };
            this.dispatchEvent(new CustomEvent('apply-filters', {
                detail: payload,
                bubbles: true,
                composed: true
            }));
        });

        // Reset button
        root.getElementById('reset-filters-btn').addEventListener('click', () => {
            const clearSelect = (id) => {
                const s = root.getElementById(id);
                if (!s) return;

                Array.from(s.options).forEach(o => { o.selected = false; });

                const emptyOpt = Array.from(s.options).find(o => (o.value ?? '').trim() === '');
                if (emptyOpt) emptyOpt.selected = false;

                s.dispatchEvent(new Event('change', { bubbles: true }));
            };


            // Reset thông tin thời gian
            if (fpFrom && typeof fpFrom.clear === 'function') fpFrom.clear();
            else root.getElementById('filter-date-from').value = '';

            if (fpTo && typeof fpTo.clear === 'function') fpTo.clear();
            else root.getElementById('filter-date-to').value = '';

            // Reset thông tin thầu
            root.getElementById('filter-investor').value = '';
            root.getElementById('filter-approval-decision').value = '';
            // root.getElementById('filter-selection-method').value = '';
            // root.getElementById('filter-place').value = '';
            clearSelect('filter-selection-method');
            clearSelect('filter-place');
            root.getElementById('filter-validity').value = '';
    
            // Reset thông tin hàng hóa
            root.getElementById('filter-drug-name').value = '';
            root.getElementById('filter-active-ingredient').value = '';
            root.getElementById('filter-concentration').value = '';
            root.getElementById('filter-route').value = '';
            root.getElementById('filter-dosage-form').value = '';
            root.getElementById('filter-specification').value = '';
            root.getElementById('filter-drug-group').value = '';
            root.getElementById('filter-reg-no').value = '';
            root.getElementById('filter-unit').value = '';

            // Reset thông tin nhà sản xuất
            root.getElementById('filter-manufacturer').value = '';
            root.getElementById('filter-country').value = '';
            
            // Cập nhật trạng thái nút sau khi reset
            queueMicrotask(() => this.updateApplyButtonState());

            this.dispatchEvent(new CustomEvent('reset-filters', {
                bubbles: true,
                composed: true
            }));
        }); 
    }
    
    setupSelectPlaceholderColors() {
        const root = this.shadowRoot;
        const selects = root.querySelectorAll("select");

        const sync = (sel) => {
            sel.classList.toggle("is-placeholder", !sel.value);
        };

        selects.forEach((sel) => {
            if (sel.id === 'filter-selection-method' || sel.id === 'filter-place') return;
            sync(sel);
            sel.addEventListener("change", () => sync(sel));
        });
    }

    setupDateEmptyState() {
        const root = this.shadowRoot;
        const dates = root.querySelectorAll('input[type="date"]');

        const sync = (inp) => inp.classList.toggle("is-empty", !inp.value);

        dates.forEach(inp => {
            sync(inp);
            inp.addEventListener("change", () => sync(inp));
            inp.addEventListener("input", () => sync(inp));
        });
    }

    createMultiSelectFromNative(selectId, { placeholder, maxLabels = 2 }) {
        const root = this.shadowRoot;
        const sel = root.getElementById(selectId);
        const host = root.querySelector(`.multi-select[data-for="${selectId}"]`);
        if (!sel || !host) return;

        // 1) Ẩn select gốc (vẫn dùng để submit/payload)
        sel.classList.add('js-hidden');

        // 2) Lấy options (bỏ option value rỗng)
        const getOptions = () =>
            Array.from(sel.options)
            .map(o => ({ value: (o.value ?? '').trim(), label: (o.textContent ?? '').trim() }))
            .filter(o => o.value !== '');

        const options = getOptions();

        // 3) Render UI
        host.innerHTML = `
            <button type="button" class="multi-select-btn is-placeholder" aria-haspopup="listbox" aria-expanded="false">
            <span class="multi-select-btn-text"></span>
            <span class="multi-select-caret">▾</span>
            </button>

            <div class="multi-select-popover">
            <div class="multi-select-search">
                <input type="text" placeholder="Tìm nhanh...">
            </div>

            <div class="multi-select-options"></div>

            <div class="multi-select-footer">
                <button type="button" class="multi-select-clear">Xoá chọn</button>
                <button type="button" class="multi-select-done">Xong</button>
            </div>
            </div>
        `;

        const btn = host.querySelector('.multi-select-btn');
        const btnText = host.querySelector('.multi-select-btn-text');
        const search = host.querySelector('.multi-select-search input');
        const list = host.querySelector('.multi-select-options');
        const btnClear = host.querySelector('.multi-select-clear');
        const btnDone = host.querySelector('.multi-select-done');

        // ===== Helpers đọc state từ select =====
        const readSelectedValuesFromSelect = () =>
            Array.from(sel.selectedOptions || [])
            .map(o => (o.value ?? '').trim())
            .filter(Boolean);

        const buildLabel = (selectedValues) => {
            const n = selectedValues?.length || 0;
            if (n === 0) return null;

            const mapLabel = new Map(options.map(o => [o.value, o.label]));
            const labels = selectedValues.map(v => mapLabel.get(v) ?? v);

            if (n < 1) return labels.join(', ');
            return `Đã chọn ${n}`;
        };


        // ===== Render list checkbox theo query + selected values =====
        const renderList = (query, selectedValuesSet) => {
            const q = (query ?? '').trim().toLowerCase();
            const filtered = options.filter(o => !q || o.label.toLowerCase().includes(q));

            if (filtered.length === 0) {
            list.innerHTML = `<div style="padding:10px 12px;color:#93A0B2;font-size:13px;">Không có kết quả</div>`;
            return;
            }

            list.innerHTML = filtered.map(o => `
            <label class="multi-select-option">
                <input type="checkbox" value="${o.value.replace(/"/g, '&quot;')}" ${selectedValuesSet.has(o.value) ? 'checked' : ''}>
                <span>${o.label}</span>
            </label>
            `).join('');
        };

        // ===== Refresh UI TỪ select gốc =====
        const refreshFromSelect = () => {
            const selectedValues = readSelectedValuesFromSelect();
            const selectedSet = new Set(selectedValues);

            const label = buildLabel(selectedValues);
            if (!label) {
            btnText.textContent = placeholder;
            btn.classList.add('is-placeholder');
            } else {
            btnText.textContent = label;
            btn.classList.remove('is-placeholder');
            }

            // Nếu popover đang mở thì refresh checkbox list (giữ query)
            if (host.classList.contains('open')) {
            renderList(search.value, selectedSet);
            }
        };

        // ===== Open/close =====
        const open = () => {
            host.classList.add('open');
            btn.setAttribute('aria-expanded', 'true');

            const selectedSet = new Set(readSelectedValuesFromSelect());
            renderList(search.value, selectedSet);

            // setTimeout(() => search.focus(), 0);
            
        };

        const close = () => {
            host.classList.remove('open');
            btn.setAttribute('aria-expanded', 'false');
        };

        // ===== Bind events =====
        // Chống bind trùng nếu connectedCallback chạy lại
        if (host.dataset.bound === '1') {
            refreshFromSelect();
            return;
        }
        host.dataset.bound = '1';

        btn.addEventListener('click', () => {
            if (host.classList.contains('open')) close();
            else open();
        });

        btnDone.addEventListener('click', close);

        btnClear.addEventListener('click', () => {
            // clear selection bằng cách chỉnh select gốc -> dispatch change
            Array.from(sel.options).forEach(o => { o.selected = false; });
            sel.dispatchEvent(new Event('change', { bubbles: true }));
            this.updateApplyButtonState();
        });

        search.addEventListener('input', () => {
            const selectedSet = new Set(readSelectedValuesFromSelect());
            renderList(search.value, selectedSet);
        });

        // Tick checkbox -> update select gốc -> dispatch change (refreshFromSelect sẽ chạy)
        list.addEventListener('change', (e) => {
            const cb = e.target?.closest('input[type="checkbox"]');
            if (!cb) return;

            const v = (cb.value ?? '').trim();
            if (!v) return;

            const opt = Array.from(sel.options).find(o => (o.value ?? '').trim() === v);
            if (!opt) return;

            opt.selected = cb.checked;
            sel.dispatchEvent(new Event('change', { bubbles: true }));
        });

        // Click ngoài để đóng
        root.addEventListener('click', (e) => {
            if (!host.classList.contains('open')) return;
            if (host.contains(e.target)) return;
            close();
        });

        // 4) QUAN TRỌNG: lắng nghe change của select gốc
        sel.addEventListener('change', () => {
            const emptyOpt = Array.from(sel.options).find(o => (o.value ?? '').trim() === '');
            if (emptyOpt) emptyOpt.selected = false;
            refreshFromSelect();
        });

        // 5) Init UI từ select hiện có
        refreshFromSelect();
    }


    updateApplyButtonState(){
        const root = this.shadowRoot;
        if (!root) return;

        const applyBtn = root.getElementById('apply-filters-btn');
        const resetBtn = root.getElementById('reset-filters-btn');
        if (!applyBtn || !resetBtn) return;

        const inputs = root.querySelectorAll('.field input, .field select, .field textarea');

        const hasAnyValue = Array.from(inputs).some(el => {
            if (el.closest('.multi-select')) return false;
            if (el.type === 'button' || el.type === 'submit' || el.type === 'reset') return false;
            if (el.type === 'checkbox' || el.type === 'radio') return el.checked;
            return (el.value ?? '').toString().trim() !== '';
        });

        // Disable rule giống Sort: không có điều kiện => disable cả Apply + Reset
        applyBtn.disabled = !hasAnyValue;
        resetBtn.disabled = !hasAnyValue;

        // Giữ UX hint như bạn đang làm cho Apply
        applyBtn.title = hasAnyValue ? '' : 'Vui lòng nhập hoặc chọn ít nhất một tiêu chí tìm kiếm';
        resetBtn.title = hasAnyValue ? '' : 'Không có điều kiện để đặt lại';

    }

    attachInputListeners() {
        const root = this.shadowRoot;
        if (!root) return;

        const inputs = root.querySelectorAll('input, select, textarea');
        inputs.forEach(el => {
            el.addEventListener('input', () => this.updateApplyButtonState());
            el.addEventListener('change', () => this.updateApplyButtonState());
        });
    }
}

customElements.define('custom-search-form', CustomSearchForm);

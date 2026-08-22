import streamlit as st
import pandas as pd
import yfinance as yf
import requests


# ============================================================
# Page
# ============================================================

st.set_page_config(
    page_title="원화 기준 밴드 리밸런싱",
    page_icon="📊",
    layout="wide",
)

st.title("📊 원화 기준 밴드 리밸런싱 계산기")
st.caption(
    "국내 ETF와 미국 ETF를 모두 원화로 환산한 뒤 "
    "밴드 이탈 자산을 목표 비중까지 리밸런싱합니다."
)


# ============================================================
# Session state
# 계산 데이터와 UI 위젯 상태를 최대한 분리
# ============================================================

if "assets" not in st.session_state:
    st.session_state.assets = []

if "usdkrw" not in st.session_state:
    st.session_state.usdkrw = 1400.0

if "usdkrw_date" not in st.session_state:
    st.session_state.usdkrw_date = ""

if "fx_message" not in st.session_state:
    st.session_state.fx_message = ""

if "cash" not in st.session_state:
    st.session_state.cash = 0.0

if "result" not in st.session_state:
    st.session_state.result = None


# ============================================================
# Asset model
# ============================================================

def new_asset():
    return {
        "name": "",
        "ticker": "",
        "market": "",
        "currency": "",
        "exchange": "",

        "target": 0.0,
        "lower": 0.0,
        "upper": 0.0,

        "shares": 0.0,
        "price": 0.0,
        "price_date": "",
        "price_message": "",

        "search_results": [],
    }


def add_asset():
    st.session_state.assets.append(new_asset())
    st.session_state.result = None


def delete_asset(index):
    if 0 <= index < len(st.session_state.assets):
        st.session_state.assets.pop(index)
    st.session_state.result = None


# ============================================================
# Market / ticker helpers
# ============================================================

def detect_market(symbol: str, exchange: str) -> str:
    symbol = (symbol or "").upper()
    exchange = (exchange or "").upper()

    if symbol.endswith(".KS") or symbol.endswith(".KQ"):
        return "국내"

    korean_exchanges = {
        "KSC", "KOE", "KSE", "KQX", "KO"
    }

    if exchange in korean_exchanges:
        return "국내"

    return "미국"


def normalize_ticker(ticker: str, market: str) -> str:
    ticker = (ticker or "").strip().upper()

    if market != "국내":
        return ticker

    if ticker.endswith(".KS") or ticker.endswith(".KQ"):
        return ticker

    if ticker.isdigit() and len(ticker) == 6:
        return f"{ticker}.KS"

    return ticker


# ============================================================
# External data: Yahoo search
# ============================================================

@st.cache_data(ttl=600, show_spinner=False)
def search_assets(query: str):
    query = query.strip()

    if not query:
        return []

    try:
        search = yf.Search(
            query,
            max_results=10,
            news_count=0,
            lists_count=0,
        )

        results = []

        for quote in search.quotes:
            symbol = quote.get("symbol")

            if not symbol:
                continue

            quote_type = quote.get("quoteType", "")

            if quote_type not in {
                "EQUITY",
                "ETF",
                "MUTUALFUND",
            }:
                continue

            results.append({
                "symbol": symbol,
                "name": (
                    quote.get("longname")
                    or quote.get("shortname")
                    or symbol
                ),
                "exchange": quote.get("exchange", ""),
                "quoteType": quote_type,
            })

        return results

    except Exception:
        return []


# ============================================================
# External data: latest daily price
# ============================================================

@st.cache_data(ttl=600, show_spinner=False)
def get_latest_daily_price(ticker: str):
    """
    Yahoo Finance에서 가장 최근 제공 일봉의 Close를 조회.
    fast_info를 사용하지 않아 가격 기준을 일관되게 유지.
    """
    ticker = ticker.strip().upper()

    if not ticker:
        return None, None, "티커가 없습니다."

    try:
        stock = yf.Ticker(ticker)

        history = stock.history(
            period="10d",
            interval="1d",
            auto_adjust=False,
        )

        if history.empty:
            return None, None, "가격 데이터를 찾을 수 없습니다."

        close = history["Close"].dropna()

        if close.empty:
            return None, None, "종가 데이터를 찾을 수 없습니다."

        price = float(close.iloc[-1])

        if price <= 0:
            return None, None, "비정상적인 가격 데이터입니다."

        date = close.index[-1].strftime("%Y-%m-%d")

        return price, date, None

    except Exception as exc:
        return None, None, f"가격 조회 실패: {exc}"


# ============================================================
# External data: USD/KRW
# Frankfurter v2 single-rate endpoint
# ============================================================

@st.cache_data(ttl=1800, show_spinner=False)
def get_latest_usdkrw():
    """
    Frankfurter의 최신 USD/KRW 일별 환율.
    GET /v2/rate/USD/KRW
    """
    url = "https://api.frankfurter.dev/v2/rate/USD/KRW"

    try:
        response = requests.get(
            url,
            timeout=10,
        )
        response.raise_for_status()

        data = response.json()

        rate = float(data["rate"])
        date = data.get("date", "")

        if rate <= 0:
            return None, None, "비정상적인 환율 값입니다."

        return rate, date, None

    except requests.RequestException as exc:
        return None, None, f"환율 API 연결 실패: {exc}"

    except (KeyError, TypeError, ValueError) as exc:
        return None, None, f"환율 데이터 형식 오류: {exc}"

    except Exception as exc:
        return None, None, f"환율 조회 실패: {exc}"


# ============================================================
# Latest data refresh
# ============================================================

def refresh_all_market_data():
    """
    현재 선택된 모든 자산 가격 + USD/KRW를 한 번에 갱신.
    조회 결과는 계산 데이터에 저장하고,
    화면 위젯 값과 직접 충돌하지 않도록 한다.
    """
    messages = []

    # 환율
    usdkrw, fx_date, fx_error = get_latest_usdkrw()

    if fx_error:
        messages.append(f"환율: {fx_error}")
    else:
        st.session_state.usdkrw = usdkrw
        st.session_state.usdkrw_date = fx_date

    # 자산 가격
    for asset in st.session_state.assets:
        if not asset["ticker"]:
            continue

        ticker = normalize_ticker(
            asset["ticker"],
            asset["market"],
        )

        price, price_date, price_error = get_latest_daily_price(
            ticker
        )

        if price_error:
            asset["price_message"] = price_error
            messages.append(
                f"{asset['name'] or ticker}: {price_error}"
            )
        else:
            asset["price"] = price
            asset["price_date"] = price_date
            asset["price_message"] = ""

    if messages:
        st.session_state.fx_message = "\n".join(messages)
    else:
        st.session_state.fx_message = "최신 가격과 환율 조회가 완료되었습니다."

    st.session_state.result = None


# ============================================================
# Rebalancing engine
# ============================================================

def calculate_rebalancing(
    cash: float,
    assets: list[dict],
    usdkrw: float,
):
    """
    사용자가 정한 계산 규칙:

    1. 보유 자산 평가액 계산
       - 국내: 주식수 × 원화 가격
       - 미국: 주식수 × 달러 가격 × USD/KRW

    2. 총자산 = 현금 + 각 자산 평가액

    3. 현재비중 = 자산 평가액 / 총자산

    4. 상단 초과 자산:
       목표비중까지 매도

    5. 하단 미달 자산:
       목표비중까지 필요한 금액을 계산

    6. 가용현금 = 기존 현금 + 매도대금

    7. 가용현금이 부족하면 하단 미달 자산의
       목표까지 부족한 비중에 비례해서 배분

    8. 가용현금이 충분하면 목표비중까지 매수

    9. 남은 현금은 현금으로 유지
    """

    calculated = []

    for source in assets:
        asset = source.copy()

        if asset["market"] == "국내":
            asset["amount_krw"] = (
                asset["shares"] * asset["price"]
            )

        elif asset["market"] == "미국":
            asset["amount_krw"] = (
                asset["shares"]
                * asset["price"]
                * usdkrw
            )

        else:
            raise ValueError(
                f"{asset['name'] or '이름 없는 자산'}의 시장이 지정되지 않았습니다."
            )

        calculated.append(asset)

    total_assets = (
        cash
        + sum(a["amount_krw"] for a in calculated)
    )

    if total_assets <= 0:
        raise ValueError("총자산이 0원입니다.")

    target_sum = sum(
        a["target"] for a in calculated
    )

    if abs(target_sum - 100.0) > 0.0001:
        raise ValueError(
            f"목표 비중 합계가 {target_sum:.2f}%입니다. "
            "목표 비중 합계는 100%여야 합니다."
        )

    # 현재 상태 초기화
    for asset in calculated:
        asset["current_weight"] = (
            asset["amount_krw"] / total_assets * 100
        )
        asset["sell_amount"] = 0.0
        asset["buy_amount"] = 0.0
        asset["final_amount"] = asset["amount_krw"]
        asset["status"] = "유지"

    # --------------------------------------------------------
    # 1. 상단 초과 → 목표까지 매도
    # --------------------------------------------------------

    for asset in calculated:
        if asset["current_weight"] > asset["upper"]:
            target_amount = (
                total_assets * asset["target"] / 100
            )

            sell_amount = max(
                asset["amount_krw"] - target_amount,
                0.0,
            )

            asset["sell_amount"] = sell_amount
            asset["final_amount"] = target_amount
            asset["status"] = "상단 초과 → 목표까지 매도"

    total_sell = sum(
        a["sell_amount"] for a in calculated
    )

    available_cash = cash + total_sell

    # --------------------------------------------------------
    # 2. 하단 미달 → 목표까지 필요한 금액 계산
    # --------------------------------------------------------

    underweight = []

    for asset in calculated:
        if asset["current_weight"] < asset["lower"]:
            buy_difference = (
                asset["target"]
                - asset["current_weight"]
            )

            needed_amount = (
                total_assets
                * buy_difference
                / 100
            )

            asset["buy_difference"] = buy_difference
            asset["needed_amount"] = needed_amount
            asset["status"] = "하단 미달 → 목표까지 매수"

            underweight.append(asset)

        else:
            asset["buy_difference"] = 0.0
            asset["needed_amount"] = 0.0

    total_needed = sum(
        a["needed_amount"] for a in underweight
    )

    # --------------------------------------------------------
    # 3. 매수
    # --------------------------------------------------------

    if (
        total_needed > 0
        and available_cash <= total_needed
    ):
        total_difference = sum(
            a["buy_difference"] for a in underweight
        )

        if total_difference > 0:
            for asset in underweight:
                buy_amount = (
                    available_cash
                    * asset["buy_difference"]
                    / total_difference
                )

                asset["buy_amount"] = buy_amount
                asset["final_amount"] = (
                    asset["amount_krw"]
                    + buy_amount
                )

    elif (
        total_needed > 0
        and available_cash > total_needed
    ):
        for asset in underweight:
            buy_amount = asset["needed_amount"]

            asset["buy_amount"] = buy_amount
            asset["final_amount"] = (
                asset["amount_krw"]
                + buy_amount
            )

    # --------------------------------------------------------
    # 4. 최종 비중
    # --------------------------------------------------------

    for asset in calculated:
        asset["final_weight"] = (
            asset["final_amount"] / total_assets * 100
        )

    total_buy = sum(
        a["buy_amount"] for a in calculated
    )

    final_cash = (
        total_assets
        - sum(
            a["final_amount"] for a in calculated
        )
    )

    if abs(final_cash) < 0.01:
        final_cash = 0.0

    return {
        "total_assets": total_assets,
        "total_sell": total_sell,
        "total_buy": total_buy,
        "final_cash": final_cash,
        "assets": calculated,
    }


# ============================================================
# 1. Market data section
# ============================================================

st.header("① 시장 데이터")

data_col1, data_col2 = st.columns([4, 1])

with data_col1:
    st.metric(
        "적용 USD/KRW",
        f"{st.session_state.usdkrw:,.2f}원",
        help="미국 ETF를 원화로 환산할 때 사용하는 환율입니다.",
    )

    if st.session_state.usdkrw_date:
        st.caption(
            f"환율 기준일: {st.session_state.usdkrw_date}"
        )

with data_col2:
    st.write("")
    st.write("")
    refresh_clicked = st.button(
        "🔄 최신 데이터 조회",
        use_container_width=True,
        help="USD/KRW와 현재 등록된 모든 ETF의 최근 일봉 종가를 한 번에 조회합니다.",
    )

if refresh_clicked:
    refresh_all_market_data()
    st.rerun()

if st.session_state.fx_message:
    st.info(st.session_state.fx_message)


# ============================================================
# 2. Asset section
# ============================================================

st.header("② 자산 구성")

if st.button(
    "＋ 자산 추가",
    use_container_width=True,
):
    add_asset()
    st.rerun()


for i, asset in enumerate(
    st.session_state.assets
):
    asset_title = (
        asset["name"]
        if asset["name"]
        else f"자산 {i + 1}"
    )

    st.subheader(asset_title)

    # --------------------------------------------------------
    # Search
    # --------------------------------------------------------

    search_col1, search_col2 = st.columns([5, 1])

    with search_col1:
        search_query = st.text_input(
            "티커 또는 종목명 검색",
            value="",
            key=f"search_query_{i}",
            placeholder="예: VOO / S&P 500 / KODEX 200",
        )

    with search_col2:
        st.write("")
        if st.button(
            "🔍 검색",
            key=f"search_button_{i}",
            use_container_width=True,
        ):
            asset["search_results"] = search_assets(
                search_query
            )

    results = asset.get(
        "search_results",
        [],
    )

    if results:
        labels = [
            f"{r['name']} ({r['symbol']}) [{r['exchange']}]"
            for r in results
        ]

        selected_label = st.selectbox(
            "검색 결과",
            labels,
            key=f"result_select_{i}",
        )

        selected_index = labels.index(
            selected_label
        )

        selected = results[
            selected_index
        ]

        if st.button(
            "✅ 이 종목 선택",
            key=f"select_button_{i}",
            use_container_width=True,
        ):
            asset["name"] = selected["name"]
            asset["ticker"] = selected["symbol"]
            asset["exchange"] = selected["exchange"]
            asset["market"] = detect_market(
                selected["symbol"],
                selected["exchange"],
            )
            asset["currency"] = (
                "USD"
                if asset["market"] == "미국"
                else "KRW"
            )

            asset["price"] = 0.0
            asset["price_date"] = ""
            asset["price_message"] = ""
            asset["search_results"] = []

            st.session_state.result = None

            st.rerun()

    if asset["ticker"]:
        st.info(
            f"**{asset['name']}**  |  "
            f"`{asset['ticker']}`  |  "
            f"{asset['market']} / {asset['currency']}"
        )

    # --------------------------------------------------------
    # Weight form
    # IMPORTANT:
    # The form does NOT write into session_state widget keys.
    # It only writes to asset after submit.
    # --------------------------------------------------------

    current_target = float(asset["target"])
    current_lower = float(asset["lower"])
    current_upper = float(asset["upper"])

    with st.form(
        key=f"weight_form_{i}"
    ):
        st.markdown("#### 목표 비중 및 밴드")

        target_col1, target_col2 = st.columns([5, 1])

        with target_col1:
            target_slider = st.slider(
                "목표 비중 슬라이더",
                min_value=0.0,
                max_value=100.0,
                value=current_target,
                step=0.5,
            )

        with target_col2:
            target_number = st.number_input(
                "목표 %",
                min_value=0.0,
                max_value=100.0,
                value=current_target,
                step=0.5,
                format="%.1f",
            )

        lower_col1, lower_col2 = st.columns([5, 1])

        with lower_col1:
            lower_slider = st.slider(
                "하단 비중 슬라이더",
                min_value=0.0,
                max_value=100.0,
                value=current_lower,
                step=0.5,
            )

        with lower_col2:
            lower_number = st.number_input(
                "하단 %",
                min_value=0.0,
                max_value=100.0,
                value=current_lower,
                step=0.5,
                format="%.1f",
            )

        upper_col1, upper_col2 = st.columns([5, 1])

        with upper_col1:
            upper_slider = st.slider(
                "상단 비중 슬라이더",
                min_value=0.0,
                max_value=100.0,
                value=current_upper,
                step=0.5,
            )

        with upper_col2:
            upper_number = st.number_input(
                "상단 %",
                min_value=0.0,
                max_value=100.0,
                value=current_upper,
                step=0.5,
                format="%.1f",
            )

        apply_weights = st.form_submit_button(
            "✅ 비중 및 밴드 적용",
            use_container_width=True,
        )

    if apply_weights:
        # 마지막 입력값을 판별하기 위한 기준값 비교
        target_number_changed = (
            abs(target_number - current_target) > 1e-9
        )
        target_slider_changed = (
            abs(target_slider - current_target) > 1e-9
        )

        lower_number_changed = (
            abs(lower_number - current_lower) > 1e-9
        )
        lower_slider_changed = (
            abs(lower_slider - current_lower) > 1e-9
        )

        upper_number_changed = (
            abs(upper_number - current_upper) > 1e-9
        )
        upper_slider_changed = (
            abs(upper_slider - current_upper) > 1e-9
        )

        # 한쪽만 변경했다면 그 값을 사용
        # 둘 다 바꿨다면 숫자 입력을 우선
        if target_number_changed:
            applied_target = float(target_number)
        elif target_slider_changed:
            applied_target = float(target_slider)
        else:
            applied_target = current_target

        if lower_number_changed:
            applied_lower = float(lower_number)
        elif lower_slider_changed:
            applied_lower = float(lower_slider)
        else:
            applied_lower = current_lower

        if upper_number_changed:
            applied_upper = float(upper_number)
        elif upper_slider_changed:
            applied_upper = float(upper_slider)
        else:
            applied_upper = current_upper

        if not (
            0
            <= applied_lower
            <= applied_target
            <= applied_upper
            <= 100
        ):
            st.error(
                "하단 ≤ 목표 ≤ 상단 조건을 만족해야 합니다."
            )
        else:
            asset["target"] = applied_target
            asset["lower"] = applied_lower
            asset["upper"] = applied_upper

            st.session_state.result = None

            st.success(
                f"적용 완료: "
                f"{applied_lower:.1f}% ≤ "
                f"{applied_target:.1f}% ≤ "
                f"{applied_upper:.1f}%"
            )

    st.caption(
        f"현재 적용값: "
        f"{asset['lower']:.1f}% ≤ "
        f"{asset['target']:.1f}% ≤ "
        f"{asset['upper']:.1f}%"
    )

    # --------------------------------------------------------
    # Holdings
    # This is also a form, so typing doesn't trigger repeated
    # expensive calculations.
    # --------------------------------------------------------

    with st.form(
        key=f"holding_form_{i}"
    ):
        st.markdown("#### 현재 보유량")

        shares_input, price_input = st.columns(2)

        with shares_input:
            shares = st.number_input(
                "보유 주식 수",
                min_value=0.0,
                value=float(asset["shares"]),
                step=1.0,
                format="%.6f",
            )

        with price_input:
            price = st.number_input(
                "현재가",
                min_value=0.0,
                value=float(asset["price"]),
                step=0.01,
                format="%.4f",
            )

        apply_holdings = st.form_submit_button(
            "✅ 보유량/가격 적용",
            use_container_width=True,
        )

    if apply_holdings:
        asset["shares"] = float(shares)
        asset["price"] = float(price)
        st.session_state.result = None

    if asset["price_message"]:
        st.error(asset["price_message"])

    if asset["price_date"]:
        st.caption(
            f"최근 일봉 종가: "
            f"{asset['price']:,.4f} "
            f"{asset['currency']} "
            f"(기준일: {asset['price_date']})"
        )

    # Estimated KRW amount
    if (
        asset["ticker"]
        and asset["price"] > 0
    ):
        if asset["market"] == "미국":
            amount_krw = (
                asset["shares"]
                * asset["price"]
                * st.session_state.usdkrw
            )
        else:
            amount_krw = (
                asset["shares"]
                * asset["price"]
            )

        st.metric(
            "현재 원화 평가액",
            f"{amount_krw:,.0f}원",
        )

    if st.button(
        "🗑️ 자산 삭제",
        key=f"delete_asset_{i}",
    ):
        delete_asset(i)
        st.rerun()

    st.divider()


# ============================================================
# 3. Cash
# ============================================================

st.header("③ 현재 보유 현금")

with st.form("cash_form"):
    cash_input = st.number_input(
        "현재 보유 현금 (KRW)",
        min_value=0.0,
        value=float(st.session_state.cash),
        step=10000.0,
        format="%.0f",
    )

    cash_submit = st.form_submit_button(
        "✅ 현금 적용",
        use_container_width=True,
    )

if cash_submit:
    st.session_state.cash = float(cash_input)
    st.session_state.result = None
    st.success(
        f"적용 완료: {st.session_state.cash:,.0f}원"
    )

st.caption(
    f"현재 적용 현금: {st.session_state.cash:,.0f}원"
)


# ============================================================
# 4. Validate and calculate
# ============================================================

st.header("④ 리밸런싱")

calculate_clicked = st.button(
    "🚀 리밸런싱 계산",
    type="primary",
    use_container_width=True,
)

if calculate_clicked:
    try:
        if not st.session_state.assets:
            raise ValueError(
                "자산을 하나 이상 추가해주세요."
            )

        names = []

        for asset in st.session_state.assets:
            name = asset["name"].strip()

            if not name:
                raise ValueError(
                    "모든 자산의 종목을 선택해주세요."
                )

            names.append(name)

            if not asset["ticker"]:
                raise ValueError(
                    f"{name}: 종목 검색 후 선택해주세요."
                )

            if asset["market"] not in {"국내", "미국"}:
                raise ValueError(
                    f"{name}: 국내/미국 시장 정보가 없습니다."
                )

            if asset["price"] <= 0:
                raise ValueError(
                    f"{name}: 현재가를 조회하거나 직접 입력해주세요."
                )

            if not (
                0
                <= asset["lower"]
                <= asset["target"]
                <= asset["upper"]
                <= 100
            ):
                raise ValueError(
                    f"{name}: 하단 ≤ 목표 ≤ 상단 조건을 확인해주세요."
                )

        if len(names) != len(set(names)):
            raise ValueError(
                "동일한 이름의 자산이 중복되어 있습니다."
            )

        target_sum = sum(
            asset["target"]
            for asset in st.session_state.assets
        )

        if abs(target_sum - 100.0) > 0.0001:
            raise ValueError(
                f"목표 비중 합계가 {target_sum:.2f}%입니다. "
                "100%가 되도록 입력해주세요."
            )

        result = calculate_rebalancing(
            cash=float(st.session_state.cash),
            assets=st.session_state.assets,
            usdkrw=float(st.session_state.usdkrw),
        )

        st.session_state.result = result

    except ValueError as exc:
        st.session_state.result = None
        st.error(str(exc))


# ============================================================
# 5. Results
# ============================================================

if st.session_state.result is not None:
    result = st.session_state.result

    st.success("리밸런싱 계산 완료")

    c1, c2, c3, c4 = st.columns(4)

    with c1:
        st.metric(
            "총자산",
            f"{result['total_assets']:,.0f}원",
        )

    with c2:
        st.metric(
            "총 매도",
            f"{result['total_sell']:,.0f}원",
        )

    with c3:
        st.metric(
            "총 매수",
            f"{result['total_buy']:,.0f}원",
        )

    with c4:
        st.metric(
            "분배 후 현금",
            f"{result['final_cash']:,.0f}원",
        )

    # --------------------------------------------------------
    # Trades
    # --------------------------------------------------------

    st.subheader("실행할 거래")

    trade_rows = []

    for asset in result["assets"]:
        if asset["sell_amount"] > 0.5:
            trade_rows.append({
                "자산": asset["name"],
                "시장": asset["market"],
                "거래": "🔴 매도",
                "금액": asset["sell_amount"],
            })

        if asset["buy_amount"] > 0.5:
            trade_rows.append({
                "자산": asset["name"],
                "시장": asset["market"],
                "거래": "🟢 매수",
                "금액": asset["buy_amount"],
            })

    if trade_rows:
        st.dataframe(
            pd.DataFrame(trade_rows),
            use_container_width=True,
            hide_index=True,
            column_config={
                "금액": st.column_config.NumberColumn(
                    "금액",
                    format="₩%,.0f",
                )
            },
        )
    else:
        st.info(
            "현재 모든 자산이 밴드 안에 있어 "
            "매매가 필요하지 않습니다."
        )

    # --------------------------------------------------------
    # Whole portfolio
    # --------------------------------------------------------

    st.subheader("전체 포트폴리오")

    rows = []

    for asset in result["assets"]:
        rows.append({
            "자산": asset["name"],
            "시장": asset["market"],
            "현재 평가액": asset["amount_krw"],
            "현재 비중": asset["current_weight"],
            "하단": asset["lower"],
            "목표": asset["target"],
            "상단": asset["upper"],
            "매도": asset["sell_amount"],
            "매수": asset["buy_amount"],
            "분배 후 금액": asset["final_amount"],
            "분배 후 비중": asset["final_weight"],
            "상태": asset["status"],
        })

    result_df = pd.DataFrame(rows)

    st.dataframe(
        result_df,
        use_container_width=True,
        hide_index=True,
        column_config={
            "현재 평가액": st.column_config.NumberColumn(
                "현재 평가액",
                format="₩%,.0f",
            ),
            "현재 비중": st.column_config.NumberColumn(
                "현재 비중",
                format="%.2f%%",
            ),
            "하단": st.column_config.NumberColumn(
                "하단",
                format="%.1f%%",
            ),
            "목표": st.column_config.NumberColumn(
                "목표",
                format="%.1f%%",
            ),
            "상단": st.column_config.NumberColumn(
                "상단",
                format="%.1f%%",
            ),
            "매도": st.column_config.NumberColumn(
                "매도",
                format="₩%,.0f",
            ),
            "매수": st.column_config.NumberColumn(
                "매수",
                format="₩%,.0f",
            ),
            "분배 후 금액": st.column_config.NumberColumn(
                "분배 후 금액",
                format="₩%,.0f",
            ),
            "분배 후 비중": st.column_config.NumberColumn(
                "분배 후 비중",
                format="%.2f%%",
            ),
        },
    )

    st.caption(
        "가격과 환율은 조회 버튼을 눌렀을 때 저장된 최신 제공 일봉 데이터를 사용합니다. "
        "실제 주문가격과 체결가격은 다를 수 있습니다."
    )

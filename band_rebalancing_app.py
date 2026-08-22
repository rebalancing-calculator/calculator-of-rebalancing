import streamlit as st
import pandas as pd
import yfinance as yf
import requests


# ============================================================
# PAGE
# ============================================================

st.set_page_config(
    page_title="원화 기준 밴드 리밸런싱",
    page_icon="📊",
    layout="wide",
)

st.title("📊 원화 기준 밴드 리밸런싱 계산기")
st.caption(
    "국내 ETF · 미국 ETF · 직접입력 자산을 모두 원화 기준으로 환산하여 "
    "밴드 리밸런싱을 계산합니다."
)


# ============================================================
# SESSION STATE
# ============================================================

if "assets" not in st.session_state:
    st.session_state.assets = []

if "usdkrw" not in st.session_state:
    st.session_state.usdkrw = 1400.0

if "usdkrw_date" not in st.session_state:
    st.session_state.usdkrw_date = ""

if "fetched_usdkrw" not in st.session_state:
    st.session_state.fetched_usdkrw = None

if "fetched_usdkrw_date" not in st.session_state:
    st.session_state.fetched_usdkrw_date = ""

if "cash_krw_input" not in st.session_state:
    st.session_state.cash_krw_input = 0.0

if "cash_usd_input" not in st.session_state:
    st.session_state.cash_usd_input = 0.0

if "applied_cash_krw" not in st.session_state:
    st.session_state.applied_cash_krw = 0.0

if "latest_data_message" not in st.session_state:
    st.session_state.latest_data_message = ""

if "result" not in st.session_state:
    st.session_state.result = None


# ============================================================
# ASSET MODEL
# ============================================================

def create_asset():
    return {
        "name": "",
        "ticker": "",
        "exchange": "",
        "market": "기타",
        "currency": "KRW",
        "source": "manual",

        "target": 0.0,
        "lower": 0.0,
        "upper": 0.0,

        "shares": 0.0,
        "price": 0.0,
        "price_date": "",

        "fetched_price": None,
        "fetched_price_date": "",
        "price_message": "",

        "search_results": [],
    }


def add_asset():
    st.session_state.assets.append(create_asset())
    st.session_state.result = None


def delete_asset(index):
    if 0 <= index < len(st.session_state.assets):
        st.session_state.assets.pop(index)
    st.session_state.result = None


# ============================================================
# MARKET HELPERS
# ============================================================

def detect_market(symbol, exchange):
    symbol = (symbol or "").upper()
    exchange = (exchange or "").upper()

    if symbol.endswith(".KS") or symbol.endswith(".KQ"):
        return "국내"

    korean_exchanges = {"KSC", "KOE", "KSE", "KQX", "KO"}
    if exchange in korean_exchanges:
        return "국내"

    return "미국"


def normalize_ticker(ticker, market):
    ticker = (ticker or "").strip().upper()

    if market != "국내":
        return ticker

    if ticker.endswith(".KS") or ticker.endswith(".KQ"):
        return ticker

    if ticker.isdigit() and len(ticker) == 6:
        return f"{ticker}.KS"

    return ticker


# ============================================================
# SEARCH / PRICE / FX
# ============================================================

@st.cache_data(ttl=600, show_spinner=False)
def search_assets(query):
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
            if quote_type not in {"EQUITY", "ETF", "MUTUALFUND"}:
                continue

            results.append(
                {
                    "symbol": symbol,
                    "name": (
                        quote.get("longname")
                        or quote.get("shortname")
                        or symbol
                    ),
                    "exchange": quote.get("exchange", ""),
                    "quoteType": quote_type,
                }
            )

        return results

    except Exception:
        return []


@st.cache_data(ttl=600, show_spinner=False)
def get_latest_price(ticker):
    ticker = ticker.strip().upper()

    if not ticker:
        return None, None, "티커가 없습니다."

    try:
        history = yf.Ticker(ticker).history(
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


@st.cache_data(ttl=1800, show_spinner=False)
def get_latest_usdkrw():
    url = "https://api.frankfurter.dev/v2/rate/USD/KRW"

    try:
        response = requests.get(url, timeout=10)
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


def fetch_latest_data():
    messages = []

    rate, date, error = get_latest_usdkrw()

    if error:
        messages.append(f"환율: {error}")
        st.session_state.fetched_usdkrw = None
        st.session_state.fetched_usdkrw_date = ""
    else:
        st.session_state.fetched_usdkrw = rate
        st.session_state.fetched_usdkrw_date = date or ""

    for asset in st.session_state.assets:
        asset["price_message"] = ""

        if asset["source"] != "auto" or not asset["ticker"]:
            continue

        ticker = normalize_ticker(
            asset["ticker"],
            asset["market"],
        )

        price, price_date, error = get_latest_price(ticker)

        if error:
            asset["fetched_price"] = None
            asset["fetched_price_date"] = ""
            asset["price_message"] = error
            messages.append(
                f"{asset['name'] or ticker}: {error}"
            )
        else:
            asset["fetched_price"] = price
            asset["fetched_price_date"] = price_date or ""

    if messages:
        st.session_state.latest_data_message = "\n".join(messages)
    else:
        st.session_state.latest_data_message = (
            "최신 가격과 환율 조회가 완료되었습니다."
        )


def apply_latest_data():
    applied_items = []

    if st.session_state.fetched_usdkrw is not None:
        st.session_state.usdkrw = float(
            st.session_state.fetched_usdkrw
        )
        st.session_state.usdkrw_date = (
            st.session_state.fetched_usdkrw_date
        )
        applied_items.append("USD/KRW")

    for asset in st.session_state.assets:
        if (
            asset["source"] == "auto"
            and asset["fetched_price"] is not None
        ):
            asset["price"] = float(asset["fetched_price"])
            asset["price_date"] = asset["fetched_price_date"]
            applied_items.append(asset["name"])

    usd_cash_krw = (
        st.session_state.cash_usd_input
        * st.session_state.usdkrw
    )

    st.session_state.applied_cash_krw = (
        st.session_state.cash_krw_input
        + usd_cash_krw
    )

    st.session_state.result = None
    return applied_items


# ============================================================
# REBALANCING ENGINE
# ============================================================

def calculate_rebalancing(cash_krw, assets, usdkrw):
    calculated = []

    for source in assets:
        asset = source.copy()

        if asset["currency"] == "USD":
            asset["amount_krw"] = (
                asset["shares"]
                * asset["price"]
                * usdkrw
            )
        else:
            asset["amount_krw"] = (
                asset["shares"]
                * asset["price"]
            )

        calculated.append(asset)

    total_assets = (
        cash_krw
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
            "100%가 되도록 입력해주세요."
        )

    for asset in calculated:
        asset["current_weight"] = (
            asset["amount_krw"]
            / total_assets
            * 100
        )
        asset["sell_amount"] = 0.0
        asset["buy_amount"] = 0.0
        asset["final_amount"] = asset["amount_krw"]
        asset["status"] = "유지"

    # 상단 초과 → 목표까지 매도
    for asset in calculated:
        if asset["current_weight"] > asset["upper"]:
            target_amount = (
                total_assets
                * asset["target"]
                / 100
            )

            asset["sell_amount"] = max(
                asset["amount_krw"] - target_amount,
                0.0,
            )
            asset["final_amount"] = target_amount
            asset["status"] = "상단 초과 → 목표까지 매도"

    total_sell = sum(
        a["sell_amount"] for a in calculated
    )

    available_cash = cash_krw + total_sell

    # 하단 미달
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

    # 현금 부족
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
                    asset["amount_krw"] + buy_amount
                )

    # 현금 충분
    elif (
        total_needed > 0
        and available_cash > total_needed
    ):
        for asset in underweight:
            buy_amount = asset["needed_amount"]

            asset["buy_amount"] = buy_amount
            asset["final_amount"] = (
                asset["amount_krw"] + buy_amount
            )

    for asset in calculated:
        asset["final_weight"] = (
            asset["final_amount"]
            / total_assets
            * 100
        )

    total_buy = sum(
        a["buy_amount"] for a in calculated
    )

    final_cash = (
        total_assets
        - sum(
            a["final_amount"]
            for a in calculated
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
# DISPLAY HELPERS
# ============================================================

def local_trade_amount(krw_amount, asset, usdkrw):
    if asset["currency"] == "USD":
        return krw_amount / usdkrw
    return krw_amount


def estimated_shares(local_amount, price):
    if price <= 0:
        return 0.0
    return local_amount / price


def local_price_format(currency):
    if currency == "USD":
        return "USD"
    return "KRW"


# ============================================================
# 1. MARKET DATA + BULK APPLY
# ============================================================

st.header("① 시장 데이터")

data_col1, data_col2, data_col3 = st.columns(
    [2, 2, 2],
    gap="small",
)

with data_col1:
    st.metric(
        "현재 적용 USD/KRW",
        f"{st.session_state.usdkrw:,.2f}원",
    )
    if st.session_state.usdkrw_date:
        st.caption(
            f"기준일: {st.session_state.usdkrw_date}"
        )

with data_col2:
    if st.session_state.fetched_usdkrw is not None:
        st.metric(
            "조회된 USD/KRW",
            f"{st.session_state.fetched_usdkrw:,.2f}원",
        )
        if st.session_state.fetched_usdkrw_date:
            st.caption(
                f"조회일: {st.session_state.fetched_usdkrw_date}"
            )
    else:
        st.info("아직 최신 환율을 조회하지 않았습니다.")

with data_col3:
    latest_clicked = st.button(
        "🔄 최신 데이터 조회",
        use_container_width=True,
    )

    bulk_apply_clicked = st.button(
        "✅ 최신 가격 · 환율 · 현금 일괄 적용",
        use_container_width=True,
        help=(
            "조회된 최신 가격과 환율을 실제 계산값에 적용하고 "
            "KRW/USD 현금을 KRW로 통합합니다."
        ),
    )

if latest_clicked:
    fetch_latest_data()

if bulk_apply_clicked:
    applied = apply_latest_data()

    if applied:
        st.success(
            "일괄 적용 완료: " + ", ".join(applied)
        )
    else:
        st.warning(
            "적용할 최신 데이터가 없습니다. "
            "먼저 최신 데이터 조회를 실행해주세요."
        )

if st.session_state.latest_data_message:
    st.info(st.session_state.latest_data_message)


# ============================================================
# 2. ASSETS — 2 COLUMNS
# The two columns have the same internal ordering so that
# corresponding rows align visually as much as Streamlit
# column flow allows.
# ============================================================

st.header("② 자산 구성")

if st.button(
    "＋ 자산 추가",
    use_container_width=True,
):
    add_asset()
    st.rerun()


for row_start in range(
    0,
    len(st.session_state.assets),
    2
):
    row_assets = st.session_state.assets[
        row_start:row_start + 2
    ]

    cols = st.columns(
        2,
        gap="medium",
    )

    for offset, asset in enumerate(row_assets):
        i = row_start + offset

        with cols[offset]:
            with st.container(border=True):

                # --------------------------------------------
                # Header
                # --------------------------------------------

                st.markdown(
                    f"### {asset['name'] or f'자산 {i + 1}'}"
                )

                # --------------------------------------------
                # Search
                # --------------------------------------------

                search_query = st.text_input(
                    "티커 또는 종목명 검색",
                    key=f"search_{i}",
                    placeholder="예: VOO / KODEX 200",
                )

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
                        key=f"result_{i}",
                    )

                    selected = results[
                        labels.index(selected_label)
                    ]

                    if st.button(
                        "✅ 종목 선택",
                        key=f"select_{i}",
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
                        asset["source"] = "auto"
                        asset["price"] = 0.0
                        asset["price_date"] = ""
                        asset["fetched_price"] = None
                        asset["fetched_price_date"] = ""
                        asset["price_message"] = ""
                        asset["search_results"] = []
                        st.session_state.result = None
                        st.rerun()

                # --------------------------------------------
                # Source / manual mode
                # --------------------------------------------

                mode = st.radio(
                    "가격 입력 방식",
                    [
                        "자동 조회 자산",
                        "직접 입력 자산",
                    ],
                    index=(
                        0 if asset["source"] == "auto"
                        else 1
                    ),
                    horizontal=True,
                    key=f"mode_{i}",
                )

                if mode == "직접 입력 자산":
                    asset["source"] = "manual"

                    asset["name"] = st.text_input(
                        "자산명",
                        value=asset["name"],
                        key=f"manual_name_{i}",
                    )

                    asset["market"] = st.selectbox(
                        "시장",
                        ["기타", "국내", "미국"],
                        index=(
                            ["기타", "국내", "미국"].index(
                                asset["market"]
                            )
                            if asset["market"]
                            in {"기타", "국내", "미국"}
                            else 0
                        ),
                        key=f"manual_market_{i}",
                    )

                    asset["currency"] = st.selectbox(
                        "통화",
                        ["KRW", "USD"],
                        index=(
                            1 if asset["currency"] == "USD"
                            else 0
                        ),
                        key=f"manual_currency_{i}",
                    )

                    asset["ticker"] = ""

                else:
                    asset["source"] = "auto"

                if asset["ticker"]:
                    st.caption(
                        f"{asset['ticker']} · "
                        f"{asset['market']} · "
                        f"{asset['currency']}"
                    )

                # --------------------------------------------
                # Allocation
                # --------------------------------------------

                with st.form(
                    key=f"weight_form_{i}"
                ):
                    st.markdown("**목표 비중 / 밴드**")

                    target = st.number_input(
                        "목표 비중 (%)",
                        min_value=0.0,
                        max_value=100.0,
                        value=float(asset["target"]),
                        step=0.5,
                        format="%.1f",
                    )

                    lower = st.number_input(
                        "하단 비중 (%)",
                        min_value=0.0,
                        max_value=100.0,
                        value=float(asset["lower"]),
                        step=0.5,
                        format="%.1f",
                    )

                    upper = st.number_input(
                        "상단 비중 (%)",
                        min_value=0.0,
                        max_value=100.0,
                        value=float(asset["upper"]),
                        step=0.5,
                        format="%.1f",
                    )

                    apply_weights = st.form_submit_button(
                        "✅ 비중 적용",
                        use_container_width=True,
                    )

                if apply_weights:
                    if not (
                        0
                        <= lower
                        <= target
                        <= upper
                        <= 100
                    ):
                        st.error(
                            "하단 ≤ 목표 ≤ 상단 조건을 만족해야 합니다."
                        )
                    else:
                        asset["target"] = float(target)
                        asset["lower"] = float(lower)
                        asset["upper"] = float(upper)
                        st.session_state.result = None
                        st.success(
                            f"{lower:.1f}% ≤ "
                            f"{target:.1f}% ≤ "
                            f"{upper:.1f}% 적용"
                        )

                st.caption(
                    f"적용값: "
                    f"{asset['lower']:.1f}% ≤ "
                    f"{asset['target']:.1f}% ≤ "
                    f"{asset['upper']:.1f}%"
                )

                # --------------------------------------------
                # Holdings / calculation price
                # --------------------------------------------

                with st.form(
                    key=f"holdings_form_{i}"
                ):
                    st.markdown("**보유 주식 / 가격**")

                    shares = st.number_input(
                        "보유 주식 수",
                        min_value=0.0,
                        value=float(asset["shares"]),
                        step=1.0,
                        format="%.6f",
                    )

                    price = st.number_input(
                        "계산에 사용할 현재가",
                        min_value=0.0,
                        value=float(asset["price"]),
                        step=0.01,
                        format="%.4f",
                    )

                    apply_holdings = st.form_submit_button(
                        "✅ 주식수 / 가격 적용",
                        use_container_width=True,
                    )

                if apply_holdings:
                    asset["shares"] = float(shares)
                    asset["price"] = float(price)

                    if asset["source"] == "manual":
                        asset["price_date"] = "수동 입력"

                    st.session_state.result = None

                if asset["fetched_price"] is not None:
                    st.info(
                        f"조회된 가격: "
                        f"{asset['fetched_price']:,.4f} "
                        f"{asset['currency']} · "
                        f"{asset['fetched_price_date']}"
                    )

                if asset["price_message"]:
                    st.error(asset["price_message"])

                if asset["price_date"]:
                    st.caption(
                        f"계산 적용 가격: "
                        f"{asset['price']:,.4f} "
                        f"{asset['currency']} "
                        f"({asset['price_date']})"
                    )

                if asset["price"] > 0:
                    if asset["currency"] == "USD":
                        current_value = (
                            asset["shares"]
                            * asset["price"]
                            * st.session_state.usdkrw
                        )
                    else:
                        current_value = (
                            asset["shares"]
                            * asset["price"]
                        )

                    st.metric(
                        "현재 원화 평가액",
                        f"₩{current_value:,.0f}",
                    )

                if st.button(
                    "🗑️ 자산 삭제",
                    key=f"delete_{i}",
                    use_container_width=True,
                ):
                    delete_asset(i)
                    st.rerun()


# ============================================================
# 3. CASH
# ============================================================

st.header("③ 현재 보유 현금")

with st.form("cash_form"):
    cash_col1, cash_col2 = st.columns(
        2,
        gap="medium",
    )

    with cash_col1:
        cash_krw = st.number_input(
            "보유 현금 (KRW)",
            min_value=0.0,
            value=float(
                st.session_state.cash_krw_input
            ),
            step=10000.0,
            format="%.0f",
        )

    with cash_col2:
        cash_usd = st.number_input(
            "보유 현금 (USD)",
            min_value=0.0,
            value=float(
                st.session_state.cash_usd_input
            ),
            step=100.0,
            format="%.2f",
        )

    cash_apply = st.form_submit_button(
        "✅ 현금 입력 저장",
        use_container_width=True,
    )

if cash_apply:
    st.session_state.cash_krw_input = float(cash_krw)
    st.session_state.cash_usd_input = float(cash_usd)
    st.session_state.result = None

cash_usd_krw = (
    st.session_state.cash_usd_input
    * st.session_state.usdkrw
)

st.info(
    f"현재 입력 현금: "
    f"₩{st.session_state.cash_krw_input:,.0f}"
    f" + "
    f"${st.session_state.cash_usd_input:,.2f}"
    f" × "
    f"{st.session_state.usdkrw:,.2f}"
    f" = "
    f"₩{st.session_state.cash_krw_input + cash_usd_krw:,.0f}"
)

st.caption(
    "‘일괄 적용’을 누르면 이 원화·달러 현금이 현재 환율 기준의 "
    "하나의 원화 현금으로 계산됩니다."
)


# ============================================================
# 4. REBALANCE
# ============================================================

st.header("④ 리밸런싱")

if st.button(
    "🚀 원화 기준 리밸런싱 계산",
    type="primary",
    use_container_width=True,
):
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
                    "모든 자산의 이름을 입력해주세요."
                )

            names.append(name)

            if asset["price"] <= 0:
                raise ValueError(
                    f"{name}: 계산에 사용할 현재가를 입력해주세요."
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

            if (
                asset["currency"] == "USD"
                and st.session_state.usdkrw <= 0
            ):
                raise ValueError(
                    f"{name}: USD/KRW 환율을 확인해주세요."
                )

        if len(names) != len(set(names)):
            raise ValueError(
                "같은 자산명이 중복되어 있습니다."
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
            cash_krw=st.session_state.applied_cash_krw,
            assets=st.session_state.assets,
            usdkrw=st.session_state.usdkrw,
        )

        st.session_state.result = result

    except ValueError as exc:
        st.session_state.result = None
        st.error(str(exc))


# ============================================================
# 5. RESULTS
# ============================================================

if st.session_state.result is not None:
    result = st.session_state.result

    st.success("리밸런싱 계산 완료")

    c1, c2, c3, c4 = st.columns(
        4,
        gap="small",
    )

    with c1:
        st.metric(
            "총자산",
            f"₩{result['total_assets']:,.0f}",
        )

    with c2:
        st.metric(
            "총 매도",
            f"₩{result['total_sell']:,.0f}",
        )

    with c3:
        st.metric(
            "총 매수",
            f"₩{result['total_buy']:,.0f}",
        )

    with c4:
        st.metric(
            "분배 후 현금",
            f"₩{result['final_cash']:,.0f}",
        )

    # --------------------------------------------------------
    # Trade reference table
    # Required order:
    # 자산 → 시장 → 거래 → 거래금액(KRW)
    # → 거래금액(현지통화) → 통화 → 계산 사용 현재가
    # → 예상 주문 주식수
    # --------------------------------------------------------

    st.subheader("실행 참고용 거래")

    trade_rows = []

    for asset in result["assets"]:
        price = asset["price"]

        if asset["sell_amount"] > 0.01:
            local_amount = local_trade_amount(
                asset["sell_amount"],
                asset,
                st.session_state.usdkrw,
            )

            shares_estimate = estimated_shares(
                local_amount,
                price,
            )

            trade_rows.append(
                {
                    "자산": asset["name"],
                    "시장": asset["market"],
                    "거래": "🔴 매도",
                    "거래금액(KRW)": asset["sell_amount"],
                    "거래금액(현지통화)": local_amount,
                    "통화": asset["currency"],
                    "계산 사용 현재가": price,
                    "예상 주문 주식수": shares_estimate,
                }
            )

        if asset["buy_amount"] > 0.01:
            local_amount = local_trade_amount(
                asset["buy_amount"],
                asset,
                st.session_state.usdkrw,
            )

            shares_estimate = estimated_shares(
                local_amount,
                price,
            )

            trade_rows.append(
                {
                    "자산": asset["name"],
                    "시장": asset["market"],
                    "거래": "🟢 매수",
                    "거래금액(KRW)": asset["buy_amount"],
                    "거래금액(현지통화)": local_amount,
                    "통화": asset["currency"],
                    "계산 사용 현재가": price,
                    "예상 주문 주식수": shares_estimate,
                }
            )

    if trade_rows:
        trade_df = pd.DataFrame(trade_rows)

        st.dataframe(
            trade_df,
            use_container_width=True,
            hide_index=True,
            column_config={
                "거래금액(KRW)": st.column_config.NumberColumn(
                    "거래금액(KRW)",
                    format="₩%,.0f",
                ),
                "거래금액(현지통화)": st.column_config.NumberColumn(
                    "거래금액(현지통화)",
                    format="%.2f",
                ),
                "계산 사용 현재가": st.column_config.NumberColumn(
                    "계산 사용 현재가",
                    format="%.2f",
                ),
                "예상 주문 주식수": st.column_config.NumberColumn(
                    "예상 주문 주식수",
                    format="%.4f",
                ),
            },
        )
    else:
        st.info(
            "현재 밴드를 벗어난 자산이 없어 "
            "매매가 필요하지 않습니다."
        )

    # --------------------------------------------------------
    # Portfolio
    # --------------------------------------------------------

    st.subheader("전체 포트폴리오")

    portfolio_rows = []

    for asset in result["assets"]:
        portfolio_rows.append(
            {
                "자산": asset["name"],
                "시장": asset["market"],
                "통화": asset["currency"],
                "계산 사용 현재가": asset["price"],
                "현재 평가액(KRW)": asset["amount_krw"],
                "현재 비중": asset["current_weight"],
                "하단": asset["lower"],
                "목표": asset["target"],
                "상단": asset["upper"],
                "매도(KRW)": asset["sell_amount"],
                "매수(KRW)": asset["buy_amount"],
                "분배 후 금액(KRW)": asset["final_amount"],
                "분배 후 비중": asset["final_weight"],
                "상태": asset["status"],
            }
        )

    result_df = pd.DataFrame(portfolio_rows)

    st.dataframe(
        result_df,
        use_container_width=True,
        hide_index=True,
        column_config={
            "계산 사용 현재가": st.column_config.NumberColumn(
                "계산 사용 현재가",
                format="%.2f",
            ),
            "현재 평가액(KRW)": st.column_config.NumberColumn(
                "현재 평가액(KRW)",
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
            "매도(KRW)": st.column_config.NumberColumn(
                "매도(KRW)",
                format="₩%,.0f",
            ),
            "매수(KRW)": st.column_config.NumberColumn(
                "매수(KRW)",
                format="₩%,.0f",
            ),
            "분배 후 금액(KRW)": st.column_config.NumberColumn(
                "분배 후 금액(KRW)",
                format="₩%,.0f",
            ),
            "분배 후 비중": st.column_config.NumberColumn(
                "분배 후 비중",
                format="%.2f%%",
            ),
        },
    )

    st.caption(
        "미국 자산의 현지통화 거래금액은 USD, 국내·KRW 자산은 KRW입니다. "
        "예상 주문 주식수는 거래금액 ÷ 계산 사용 현재가의 참고값입니다."
    )

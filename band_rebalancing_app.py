import streamlit as st
import pandas as pd
import yfinance as yf
import requests


# ============================================================
# 0. 기본 설정
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
# 1. Session State
# ============================================================

if "assets" not in st.session_state:
    st.session_state.assets = []

if "usdkrw" not in st.session_state:
    st.session_state.usdkrw = 1400.0

if "usdkrw_date" not in st.session_state:
    st.session_state.usdkrw_date = ""

# 최신 조회 후 아직 적용하지 않은 환율
if "fetched_usdkrw" not in st.session_state:
    st.session_state.fetched_usdkrw = None

if "fetched_usdkrw_date" not in st.session_state:
    st.session_state.fetched_usdkrw_date = ""

# 현금 입력값
if "cash_krw_input" not in st.session_state:
    st.session_state.cash_krw_input = 0.0

if "cash_usd_input" not in st.session_state:
    st.session_state.cash_usd_input = 0.0

# 실제 계산에 사용할 통합 현금
if "applied_cash_krw" not in st.session_state:
    st.session_state.applied_cash_krw = 0.0

if "latest_data_message" not in st.session_state:
    st.session_state.latest_data_message = ""

if "result" not in st.session_state:
    st.session_state.result = None


# ============================================================
# 2. 자산 기본 구조
# ============================================================

def create_asset():
    return {
        # 기본 정보
        "name": "",
        "ticker": "",
        "exchange": "",
        "market": "기타",
        "currency": "KRW",

        # 자동조회 / 직접입력
        # auto = 검색된 종목
        # manual = 금 현물 등 직접 입력
        "source": "manual",

        # 목표 비중
        "target": 0.0,
        "lower": 0.0,
        "upper": 0.0,

        # 보유량
        "shares": 0.0,

        # 실제 계산에 사용하는 가격
        "price": 0.0,
        "price_date": "",

        # 최신 데이터 조회 결과
        # 아직 일괄 적용하지 않은 상태
        "fetched_price": None,
        "fetched_price_date": "",
        "price_message": "",

        # 검색 결과
        "search_results": [],
    }


def add_asset():
    st.session_state.assets.append(
        create_asset()
    )
    st.session_state.result = None


def delete_asset(index):
    if 0 <= index < len(st.session_state.assets):
        st.session_state.assets.pop(index)

    st.session_state.result = None


# ============================================================
# 3. 종목 관련 함수
# ============================================================

def detect_market(symbol, exchange):
    symbol = (symbol or "").upper()
    exchange = (exchange or "").upper()

    if symbol.endswith(".KS") or symbol.endswith(".KQ"):
        return "국내"

    korean_exchanges = {
        "KSC",
        "KOE",
        "KSE",
        "KQX",
        "KO",
    }

    if exchange in korean_exchanges:
        return "국내"

    return "미국"


def normalize_ticker(ticker, market):
    ticker = (ticker or "").strip().upper()

    if market != "국내":
        return ticker

    if ticker.endswith(".KS") or ticker.endswith(".KQ"):
        return ticker

    # 국내 6자리 종목코드
    if ticker.isdigit() and len(ticker) == 6:
        return ticker + ".KS"

    return ticker


# ============================================================
# 4. 종목 검색
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

            quote_type = quote.get(
                "quoteType",
                ""
            )

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
                "exchange": quote.get(
                    "exchange",
                    ""
                ),
                "quoteType": quote_type,
            })

        return results

    except Exception:
        return []


# ============================================================
# 5. 최신 ETF 가격 조회
# ============================================================

@st.cache_data(ttl=600, show_spinner=False)
def get_latest_price(ticker):
    """
    가장 최근 제공되는 일봉 종가를 사용.
    fast_info는 사용하지 않고 history()만 사용하여
    가격 기준을 일관되게 유지.
    """

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
            return (
                None,
                None,
                "가격 데이터를 찾을 수 없습니다."
            )

        close = history["Close"].dropna()

        if close.empty:
            return (
                None,
                None,
                "종가 데이터를 찾을 수 없습니다."
            )

        price = float(
            close.iloc[-1]
        )

        if price <= 0:
            return (
                None,
                None,
                "비정상적인 가격 데이터입니다."
            )

        date = close.index[-1].strftime(
            "%Y-%m-%d"
        )

        return (
            price,
            date,
            None
        )

    except Exception as exc:

        return (
            None,
            None,
            f"가격 조회 실패: {exc}"
        )


# ============================================================
# 6. USD/KRW 환율 조회
# ============================================================

@st.cache_data(ttl=1800, show_spinner=False)
def get_latest_usdkrw():
    """
    Frankfurter v2:
    /v2/rate/USD/KRW
    """

    url = (
        "https://api.frankfurter.dev/v2/rate/USD/KRW"
    )

    try:
        response = requests.get(
            url,
            timeout=10,
        )

        response.raise_for_status()

        data = response.json()

        rate = float(
            data["rate"]
        )

        date = data.get(
            "date",
            ""
        )

        if rate <= 0:
            return (
                None,
                None,
                "비정상적인 환율 값입니다."
            )

        return (
            rate,
            date,
            None
        )

    except requests.RequestException as exc:

        return (
            None,
            None,
            f"환율 API 연결 실패: {exc}"
        )

    except (KeyError, TypeError, ValueError) as exc:

        return (
            None,
            None,
            f"환율 데이터 형식 오류: {exc}"
        )

    except Exception as exc:

        return (
            None,
            None,
            f"환율 조회 실패: {exc}"
        )


# ============================================================
# 7. 최신 데이터 조회
# ============================================================

def fetch_latest_data():

    messages = []

    # --------------------------------------------------------
    # 환율
    # --------------------------------------------------------

    rate, date, error = get_latest_usdkrw()

    if error:

        messages.append(
            f"환율: {error}"
        )

        st.session_state.fetched_usdkrw = None
        st.session_state.fetched_usdkrw_date = ""

    else:

        st.session_state.fetched_usdkrw = rate

        st.session_state.fetched_usdkrw_date = (
            date or ""
        )


    # --------------------------------------------------------
    # 각 종목
    # --------------------------------------------------------

    for asset in st.session_state.assets:

        asset["price_message"] = ""

        # 직접 입력 자산은 자동조회하지 않음
        if (
            asset["source"] != "auto"
            or not asset["ticker"]
        ):
            continue

        ticker = normalize_ticker(
            asset["ticker"],
            asset["market"]
        )

        price, price_date, error = (
            get_latest_price(
                ticker
            )
        )

        if error:

            asset["fetched_price"] = None

            asset["fetched_price_date"] = ""

            asset["price_message"] = error

            messages.append(
                f"{asset['name'] or ticker}: {error}"
            )

        else:

            asset["fetched_price"] = (
                price
            )

            asset["fetched_price_date"] = (
                price_date or ""
            )


    if messages:

        st.session_state.latest_data_message = (
            "\n".join(messages)
        )

    else:

        st.session_state.latest_data_message = (
            "최신 데이터 조회가 완료되었습니다."
        )


# ============================================================
# 8. 일괄 가격 적용
# ============================================================

def apply_latest_data():

    applied_assets = []


    # --------------------------------------------------------
    # 환율 적용
    # --------------------------------------------------------

    if (
        st.session_state.fetched_usdkrw
        is not None
    ):

        st.session_state.usdkrw = (
            float(
                st.session_state.fetched_usdkrw
            )
        )

        st.session_state.usdkrw_date = (
            st.session_state.fetched_usdkrw_date
        )

        applied_assets.append(
            "USD/KRW"
        )


    # --------------------------------------------------------
    # ETF 가격 적용
    # --------------------------------------------------------

    for asset in st.session_state.assets:

        if (
            asset["source"] == "auto"
            and asset["fetched_price"] is not None
        ):

            asset["price"] = (
                float(
                    asset["fetched_price"]
                )
            )

            asset["price_date"] = (
                asset["fetched_price_date"]
            )

            applied_assets.append(
                asset["name"]
            )


    # --------------------------------------------------------
    # 현금 통합
    #
    # KRW 현금
    # +
    # USD 현금 × USD/KRW
    # --------------------------------------------------------

    usd_cash_krw = (
        st.session_state.cash_usd_input
        * st.session_state.usdkrw
    )

    st.session_state.applied_cash_krw = (
        st.session_state.cash_krw_input
        + usd_cash_krw
    )


    st.session_state.result = None

    return applied_assets


# ============================================================
# 9. 리밸런싱 계산 엔진
# ============================================================

def calculate_rebalancing(
    cash_krw,
    assets,
    usdkrw,
):

    calculated = []


    # --------------------------------------------------------
    # 자산 평가액
    # --------------------------------------------------------

    for source in assets:

        asset = source.copy()


        # USD 자산
        if asset["currency"] == "USD":

            asset["amount_krw"] = (
                asset["shares"]
                * asset["price"]
                * usdkrw
            )


        # KRW 자산
        else:

            asset["amount_krw"] = (
                asset["shares"]
                * asset["price"]
            )


        calculated.append(
            asset
        )


    # --------------------------------------------------------
    # 총자산
    # --------------------------------------------------------

    total_assets = (
        cash_krw
        + sum(
            asset["amount_krw"]
            for asset in calculated
        )
    )


    if total_assets <= 0:

        raise ValueError(
            "총자산이 0원입니다."
        )


    # --------------------------------------------------------
    # 목표 비중 합계
    # --------------------------------------------------------

    target_sum = sum(
        asset["target"]
        for asset in calculated
    )


    if abs(
        target_sum - 100
    ) > 0.0001:

        raise ValueError(
            f"목표 비중 합계가 "
            f"{target_sum:.2f}%입니다. "
            "100%가 되도록 입력해주세요."
        )


    # --------------------------------------------------------
    # 초기 상태
    # --------------------------------------------------------

    for asset in calculated:

        asset["current_weight"] = (
            asset["amount_krw"]
            / total_assets
            * 100
        )

        asset["sell_amount"] = 0.0

        asset["buy_amount"] = 0.0

        asset["final_amount"] = (
            asset["amount_krw"]
        )

        asset["status"] = (
            "유지"
        )


    # ========================================================
    # 1. 상단 초과 → 목표까지 매도
    # ========================================================

    for asset in calculated:

        if (
            asset["current_weight"]
            > asset["upper"]
        ):

            target_amount = (
                total_assets
                * asset["target"]
                / 100
            )

            sell_amount = max(
                asset["amount_krw"]
                - target_amount,
                0.0
            )

            asset["sell_amount"] = (
                sell_amount
            )

            asset["final_amount"] = (
                target_amount
            )

            asset["status"] = (
                "상단 초과 → 목표까지 매도"
            )


    # --------------------------------------------------------
    # 매도 후 사용 가능 현금
    # --------------------------------------------------------

    total_sell = sum(
        asset["sell_amount"]
        for asset in calculated
    )

    available_cash = (
        cash_krw
        + total_sell
    )


    # ========================================================
    # 2. 하단 미달
    # ========================================================

    underweight = []


    for asset in calculated:

        if (
            asset["current_weight"]
            < asset["lower"]
        ):

            buy_difference = (
                asset["target"]
                - asset["current_weight"]
            )

            needed_amount = (
                total_assets
                * buy_difference
                / 100
            )

            asset["buy_difference"] = (
                buy_difference
            )

            asset["needed_amount"] = (
                needed_amount
            )

            asset["status"] = (
                "하단 미달 → 목표까지 매수"
            )

            underweight.append(
                asset
            )

        else:

            asset["buy_difference"] = 0.0

            asset["needed_amount"] = 0.0


    # --------------------------------------------------------
    # 필요 매수금액
    # --------------------------------------------------------

    total_needed = sum(
        asset["needed_amount"]
        for asset in underweight
    )


    # ========================================================
    # 3. 현금 부족
    # ========================================================

    if (
        total_needed > 0
        and available_cash <= total_needed
    ):

        total_difference = sum(
            asset["buy_difference"]
            for asset in underweight
        )

        if total_difference > 0:

            for asset in underweight:

                buy_amount = (
                    available_cash
                    * asset["buy_difference"]
                    / total_difference
                )

                asset["buy_amount"] = (
                    buy_amount
                )

                asset["final_amount"] = (
                    asset["amount_krw"]
                    + buy_amount
                )


    # ========================================================
    # 4. 현금 충분
    # ========================================================

    elif (
        total_needed > 0
        and available_cash > total_needed
    ):

        for asset in underweight:

            buy_amount = (
                asset["needed_amount"]
            )

            asset["buy_amount"] = (
                buy_amount
            )

            asset["final_amount"] = (
                asset["amount_krw"]
                + buy_amount
            )


    # ========================================================
    # 5. 최종 비중
    # ========================================================

    for asset in calculated:

        asset["final_weight"] = (
            asset["final_amount"]
            / total_assets
            * 100
        )


    # --------------------------------------------------------
    # 총매수
    # --------------------------------------------------------

    total_buy = sum(
        asset["buy_amount"]
        for asset in calculated
    )


    # --------------------------------------------------------
    # 최종 현금
    # --------------------------------------------------------

    final_cash = (
        total_assets
        - sum(
            asset["final_amount"]
            for asset in calculated
        )
    )


    if abs(
        final_cash
    ) < 0.01:

        final_cash = 0.0


    return {
        "total_assets":
            total_assets,

        "total_sell":
            total_sell,

        "total_buy":
            total_buy,

        "final_cash":
            final_cash,

        "assets":
            calculated,
    }


# ============================================================
# 10. 거래 표시용 보조 함수
# ============================================================

def local_trade_amount(
    krw_amount,
    asset,
    usdkrw
):

    if asset["currency"] == "USD":

        return (
            krw_amount
            / usdkrw
        )

    return krw_amount


def estimated_shares(
    local_amount,
    price
):

    if price <= 0:
        return 0.0

    return (
        local_amount
        / price
    )


# ============================================================
# 11. 시장 데이터 UI
# ============================================================

st.header("① 시장 데이터")


data_col1, data_col2, data_col3 = (
    st.columns(
        [2, 2, 1],
        gap="small"
    )
)


with data_col1:

    st.metric(
        "현재 적용 USD/KRW",
        f"{st.session_state.usdkrw:,.2f}원"
    )

    if st.session_state.usdkrw_date:

        st.caption(
            f"기준일: "
            f"{st.session_state.usdkrw_date}"
        )


with data_col2:

    if (
        st.session_state.fetched_usdkrw
        is not None
    ):

        st.metric(
            "조회된 USD/KRW",
            f"{st.session_state.fetched_usdkrw:,.2f}원"
        )

        if st.session_state.fetched_usdkrw_date:

            st.caption(
                f"조회일: "
                f"{st.session_state.fetched_usdkrw_date}"
            )

    else:

        st.info(
            "최신 환율을 조회하지 않았습니다."
        )


with data_col3:

    latest_clicked = st.button(
        "🔄 최신 데이터 조회",
        use_container_width=True,
    )


if latest_clicked:

    fetch_latest_data()


if st.session_state.latest_data_message:

    st.info(
        st.session_state.latest_data_message
    )


# ============================================================
# 12. 자산 구성
# ============================================================

st.header("② 자산 구성")


add_col, bulk_col = st.columns(
    [1, 1],
    gap="small"
)


with add_col:

    if st.button(
        "＋ 자산 추가",
        use_container_width=True,
    ):

        add_asset()

        st.rerun()


with bulk_col:

    if st.button(
        "✅ 일괄 가격 적용",
        use_container_width=True,
        help=(
            "조회된 최신 가격·환율을 적용하고 "
            "원화/달러 현금을 원화로 통합합니다."
        )
    ):

        applied = (
            apply_latest_data()
        )

        if applied:

            st.success(
                "적용 완료: "
                + ", ".join(applied)
            )

        else:

            st.warning(
                "적용할 최신 데이터가 없습니다."
            )


# ============================================================
# 13. 자산 2열 구성
# ============================================================

for row_start in range(
    0,
    len(st.session_state.assets),
    2
):

    row_assets = st.session_state.assets[
        row_start:
        row_start + 2
    ]


    columns = st.columns(
        2,
        gap="small"
    )


    for offset, asset in enumerate(
        row_assets
    ):

        i = (
            row_start
            + offset
        )


        with columns[offset]:

            with st.container(
                border=True
            ):

                title = (
                    asset["name"]
                    if asset["name"]
                    else f"자산 {i + 1}"
                )


                st.subheader(
                    title
                )


                # ====================================================
                # 검색
                # ====================================================

                search_query = st.text_input(
                    "티커 또는 종목명 검색",
                    key=f"search_{i}",
                    placeholder=(
                        "예: VOO / KODEX 200"
                    )
                )


                if st.button(
                    "🔍 검색",
                    key=f"search_button_{i}",
                    use_container_width=True
                ):

                    asset["search_results"] = (
                        search_assets(
                            search_query
                        )
                    )


                results = asset.get(
                    "search_results",
                    []
                )


                if results:

                    labels = [
                        f"{r['name']} "
                        f"({r['symbol']}) "
                        f"[{r['exchange']}]"
                        for r in results
                    ]


                    selected_label = (
                        st.selectbox(
                            "검색 결과",
                            labels,
                            key=f"result_{i}"
                        )
                    )


                    selected = results[
                        labels.index(
                            selected_label
                        )
                    ]


                    if st.button(
                        "✅ 종목 선택",
                        key=f"select_{i}",
                        use_container_width=True
                    ):

                        asset["name"] = (
                            selected["name"]
                        )

                        asset["ticker"] = (
                            selected["symbol"]
                        )

                        asset["exchange"] = (
                            selected["exchange"]
                        )

                        asset["market"] = (
                            detect_market(
                                selected["symbol"],
                                selected["exchange"]
                            )
                        )

                        asset["currency"] = (
                            "USD"
                            if asset["market"]
                            == "미국"
                            else "KRW"
                        )

                        asset["source"] = (
                            "auto"
                        )

                        asset["price"] = 0.0

                        asset["price_date"] = ""

                        asset["fetched_price"] = (
                            None
                        )

                        asset["fetched_price_date"] = (
                            ""
                        )

                        asset["price_message"] = ""

                        asset["search_results"] = []

                        st.session_state.result = None

                        st.rerun()


                # ====================================================
                # 직접입력 자산
                # ====================================================

                mode = st.radio(
                    "가격 입력 방식",
                    [
                        "자동 조회 자산",
                        "직접 입력 자산"
                    ],
                    index=(
                        0
                        if asset["source"]
                        == "auto"
                        else 1
                    ),
                    horizontal=True,
                    key=f"mode_{i}"
                )


                if (
                    mode
                    == "직접 입력 자산"
                ):

                    asset["source"] = (
                        "manual"
                    )


                    manual_name = st.text_input(
                        "자산명",
                        value=asset["name"],
                        key=f"manual_name_{i}"
                    )


                    manual_market = (
                        st.selectbox(
                            "시장",
                            [
                                "기타",
                                "국내",
                                "미국"
                            ],
                            index=(
                                [
                                    "기타",
                                    "국내",
                                    "미국"
                                ].index(
                                    asset["market"]
                                )
                                if asset["market"]
                                in {
                                    "기타",
                                    "국내",
                                    "미국"
                                }
                                else 0
                            ),
                            key=f"market_{i}"
                        )
                    )


                    manual_currency = (
                        st.selectbox(
                            "통화",
                            [
                                "KRW",
                                "USD"
                            ],
                            index=(
                                1
                                if asset["currency"]
                                == "USD"
                                else 0
                            ),
                            key=f"currency_{i}"
                        )
                    )


                    asset["name"] = (
                        manual_name
                    )

                    asset["market"] = (
                        manual_market
                    )

                    asset["currency"] = (
                        manual_currency
                    )

                    asset["ticker"] = ""


                else:

                    asset["source"] = (
                        "auto"
                    )


                if asset["ticker"]:

                    st.caption(
                        f"{asset['ticker']} · "
                        f"{asset['market']} · "
                        f"{asset['currency']}"
                    )


                # ====================================================
                # 목표 비중 / 밴드
                # ====================================================

                with st.form(
                    key=f"weight_form_{i}"
                ):

                    st.markdown(
                        "**목표 비중 / 밴드**"
                    )


                    c1, c2 = st.columns(
                        [3, 1]
                    )


                    with c1:

                        target_slider = (
                            st.slider(
                                "목표",
                                0.0,
                                100.0,
                                float(
                                    asset["target"]
                                ),
                                0.5,
                            )
                        )


                    with c2:

                        target_number = (
                            st.number_input(
                                "목표 %",
                                0.0,
                                100.0,
                                float(
                                    asset["target"]
                                ),
                                0.5,
                                format="%.1f"
                            )
                        )


                    c1, c2 = st.columns(
                        [3, 1]
                    )


                    with c1:

                        lower_slider = (
                            st.slider(
                                "하단",
                                0.0,
                                100.0,
                                float(
                                    asset["lower"]
                                ),
                                0.5,
                            )
                        )


                    with c2:

                        lower_number = (
                            st.number_input(
                                "하단 %",
                                0.0,
                                100.0,
                                float(
                                    asset["lower"]
                                ),
                                0.5,
                                format="%.1f"
                            )
                        )


                    c1, c2 = st.columns(
                        [3, 1]
                    )


                    with c1:

                        upper_slider = (
                            st.slider(
                                "상단",
                                0.0,
                                100.0,
                                float(
                                    asset["upper"]
                                ),
                                0.5,
                            )
                        )


                    with c2:

                        upper_number = (
                            st.number_input(
                                "상단 %",
                                0.0,
                                100.0,
                                float(
                                    asset["upper"]
                                ),
                                0.5,
                                format="%.1f"
                            )
                        )


                    apply_weights = (
                        st.form_submit_button(
                            "✅ 비중 적용",
                            use_container_width=True
                        )
                    )


                if apply_weights:

                    # 마지막으로 변경한 것으로 판단하기 어려운
                    # 경우가 있으므로 숫자 입력을 명확한 override로 사용.
                    #
                    # 단, 숫자와 슬라이더가 동일하면 문제가 없다.

                    target = float(
                        target_number
                    )

                    lower = float(
                        lower_number
                    )

                    upper = float(
                        upper_number
                    )


                    if (
                        abs(
                            target_slider
                            - target_number
                        ) > 1e-9
                    ):

                        st.warning(
                            "목표 슬라이더와 숫자 입력이 다릅니다. "
                            "정확한 입력값은 숫자 칸을 기준으로 적용합니다."
                        )


                    if (
                        abs(
                            lower_slider
                            - lower_number
                        ) > 1e-9
                    ):

                        st.warning(
                            "하단 슬라이더와 숫자 입력이 다릅니다. "
                            "숫자 칸을 기준으로 적용합니다."
                        )


                    if (
                        abs(
                            upper_slider
                            - upper_number
                        ) > 1e-9
                    ):

                        st.warning(
                            "상단 슬라이더와 숫자 입력이 다릅니다. "
                            "숫자 칸을 기준으로 적용합니다."
                        )


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

                        asset["target"] = target

                        asset["lower"] = lower

                        asset["upper"] = upper

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


                # ====================================================
                # 주식 수 / 가격
                # ====================================================

                with st.form(
                    key=f"holdings_form_{i}"
                ):

                    st.markdown(
                        "**보유 주식 / 가격**"
                    )


                    shares = st.number_input(
                        "보유 주식 수",
                        min_value=0.0,
                        value=float(
                            asset["shares"]
                        ),
                        step=1.0,
                        format="%.6f"
                    )


                    manual_price = (
                        st.number_input(
                            "계산에 사용할 현재가",
                            min_value=0.0,
                            value=float(
                                asset["price"]
                            ),
                            step=0.01,
                            format="%.4f"
                        )
                    )


                    apply_holdings = (
                        st.form_submit_button(
                            "✅ 주식수/가격 적용",
                            use_container_width=True
                        )
                    )


                if apply_holdings:

                    asset["shares"] = (
                        float(shares)
                    )

                    asset["price"] = (
                        float(manual_price)
                    )

                    # 직접 입력한 가격은 항상 유효한 계산값
                    if asset["source"] == "manual":

                        asset["price_date"] = (
                            "수동 입력"
                        )

                    st.session_state.result = None


                # 조회된 가격
                if (
                    asset["fetched_price"]
                    is not None
                ):

                    st.info(
                        f"조회된 가격: "
                        f"{asset['fetched_price']:,.4f} "
                        f"{asset['currency']}"
                        f" · "
                        f"{asset['fetched_price_date']}"
                    )


                if asset["price_message"]:

                    st.error(
                        asset["price_message"]
                    )


                if asset["price_date"]:

                    st.caption(
                        f"계산 적용 가격: "
                        f"{asset['price']:,.4f} "
                        f"{asset['currency']} "
                        f"({asset['price_date']})"
                    )


                # 현재 평가액
                if (
                    asset["price"]
                    > 0
                ):

                    if (
                        asset["currency"]
                        == "USD"
                    ):

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
                        f"₩{current_value:,.0f}"
                    )


                if st.button(
                    "🗑️ 자산 삭제",
                    key=f"delete_{i}",
                    use_container_width=True
                ):

                    delete_asset(i)

                    st.rerun()


# ============================================================
# 14. 현금
# ============================================================

st.header("③ 현재 보유 현금")


with st.form(
    "cash_form"
):

    cash_col1, cash_col2 = (
        st.columns(
            2,
            gap="small"
        )
    )


    with cash_col1:

        cash_krw = st.number_input(
            "보유 현금 (KRW)",
            min_value=0.0,
            value=float(
                st.session_state.cash_krw_input
            ),
            step=10000.0,
            format="%.0f"
        )


    with cash_col2:

        cash_usd = st.number_input(
            "보유 현금 (USD)",
            min_value=0.0,
            value=float(
                st.session_state.cash_usd_input
            ),
            step=100.0,
            format="%.2f"
        )


    cash_apply = (
        st.form_submit_button(
            "✅ 현금 입력 저장",
            use_container_width=True
        )
    )


if cash_apply:

    st.session_state.cash_krw_input = (
        float(cash_krw)
    )

    st.session_state.cash_usd_input = (
        float(cash_usd)
    )

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


# ============================================================
# 15. 여기서도 일괄 가격 적용 가능
# ============================================================

if st.button(
    "✅ 최신 가격 · 환율 · 현금 일괄 적용",
    use_container_width=True
):

    applied = (
        apply_latest_data()
    )


    if applied:

        st.success(
            "일괄 적용 완료: "
            + ", ".join(applied)
        )

    else:

        st.warning(
            "조회된 최신 데이터가 없습니다."
        )


# ============================================================
# 16. 리밸런싱
# ============================================================

st.header("④ 리밸런싱")


if st.button(
    "🚀 원화 기준 리밸런싱 계산",
    type="primary",
    use_container_width=True
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


            names.append(
                name
            )


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
                    f"{name}: "
                    "하단 ≤ 목표 ≤ 상단 조건을 확인해주세요."
                )


            if (
                asset["currency"]
                == "USD"
                and st.session_state.usdkrw <= 0
            ):

                raise ValueError(
                    f"{name}: "
                    "USD/KRW 환율을 확인해주세요."
                )


        if len(
            names
        ) != len(
            set(names)
        ):

            raise ValueError(
                "같은 자산명이 중복되어 있습니다."
            )


        target_sum = sum(
            asset["target"]
            for asset in st.session_state.assets
        )


        if abs(
            target_sum - 100
        ) > 0.0001:

            raise ValueError(
                f"목표 비중 합계가 "
                f"{target_sum:.2f}%입니다. "
                "100%가 되도록 입력해주세요."
            )


        # 계산에 사용할 현금
        cash_krw = (
            st.session_state.applied_cash_krw
        )


        result = (
            calculate_rebalancing(
                cash_krw=cash_krw,
                assets=st.session_state.assets,
                usdkrw=st.session_state.usdkrw
            )
        )


        st.session_state.result = result


    except ValueError as exc:

        st.session_state.result = None

        st.error(
            str(exc)
        )


# ============================================================
# 17. 결과
# ============================================================

if (
    st.session_state.result
    is not None
):

    result = (
        st.session_state.result
    )


    st.success(
        "리밸런싱 계산 완료"
    )


    # --------------------------------------------------------
    # Summary
    # --------------------------------------------------------

    c1, c2, c3, c4 = (
        st.columns(
            4,
            gap="small"
        )
    )


    with c1:

        st.metric(
            "총자산",
            f"₩{result['total_assets']:,.0f}"
        )


    with c2:

        st.metric(
            "총 매도",
            f"₩{result['total_sell']:,.0f}"
        )


    with c3:

        st.metric(
            "총 매수",
            f"₩{result['total_buy']:,.0f}"
        )


    with c4:

        st.metric(
            "분배 후 현금",
            f"₩{result['final_cash']:,.0f}"
        )


    # ========================================================
    # 거래 참고표
    # ========================================================

    st.subheader(
        "실행 참고용 거래"
    )


    trade_rows = []


    for asset in result["assets"]:

        price = asset["price"]


        # ----------------------------------------------------
        # 매도
        # ----------------------------------------------------

        if (
            asset["sell_amount"]
            > 0.01
        ):

            local_amount = (
                local_trade_amount(
                    asset["sell_amount"],
                    asset,
                    st.session_state.usdkrw
                )
            )


            shares_estimate = (
                estimated_shares(
                    local_amount,
                    price
                )
            )


            trade_rows.append(
                {
                    "자산":
                        asset["name"],

                    "시장":
                        asset["market"],

                    "거래":
                        "🔴 매도",

                    "현재가":
                        price,

                    "통화":
                        asset["currency"],

                    "거래금액(KRW)":
                        asset["sell_amount"],

                    "거래금액(현지통화)":
                        local_amount,

                    "예상 주문 주식수":
                        shares_estimate
                }
            )


        # ----------------------------------------------------
        # 매수
        # ----------------------------------------------------

        if (
            asset["buy_amount"]
            > 0.01
        ):

            local_amount = (
                local_trade_amount(
                    asset["buy_amount"],
                    asset,
                    st.session_state.usdkrw
                )
            )


            shares_estimate = (
                estimated_shares(
                    local_amount,
                    price
                )
            )


            trade_rows.append(
                {
                    "자산":
                        asset["name"],

                    "시장":
                        asset["market"],

                    "거래":
                        "🟢 매수",

                    "현재가":
                        price,

                    "통화":
                        asset["currency"],

                    "거래금액(KRW)":
                        asset["buy_amount"],

                    "거래금액(현지통화)":
                        local_amount,

                    "예상 주문 주식수":
                        shares_estimate
                }
            )


    if trade_rows:

        trade_df = (
            pd.DataFrame(
                trade_rows
            )
        )


        st.dataframe(
            trade_df,
            use_container_width=True,
            hide_index=True,
            column_config={

                "현재가":
                    st.column_config.NumberColumn(
                        "계산 사용 현재가",
                        format="%.2f"
                    ),

                "거래금액(KRW)":
                    st.column_config.NumberColumn(
                        "거래금액(KRW)",
                        format="₩%,.0f"
                    ),

                "거래금액(현지통화)":
                    st.column_config.NumberColumn(
                        "거래금액(현지통화)",
                        format="%.2f"
                    ),

                "예상 주문 주식수":
                    st.column_config.NumberColumn(
                        "예상 주문 주식수",
                        format="%.4f"
                    )
            }
        )


    else:

        st.info(
            "현재 밴드를 벗어난 자산이 없어 "
            "매매가 필요하지 않습니다."
        )


    # ========================================================
    # 전체 포트폴리오
    # ========================================================

    st.subheader(
        "전체 포트폴리오"
    )


    rows = []


    for asset in result["assets"]:

        rows.append(
            {
                "자산":
                    asset["name"],

                "시장":
                    asset["market"],

                "통화":
                    asset["currency"],

                "계산 사용 현재가":
                    asset["price"],

                "현재 평가액(KRW)":
                    asset["amount_krw"],

                "현재 비중":
                    asset["current_weight"],

                "하단":
                    asset["lower"],

                "목표":
                    asset["target"],

                "상단":
                    asset["upper"],

                "매도(KRW)":
                    asset["sell_amount"],

                "매수(KRW)":
                    asset["buy_amount"],

                "분배 후 금액(KRW)":
                    asset["final_amount"],

                "분배 후 비중":
                    asset["final_weight"],

                "상태":
                    asset["status"]
            }
        )


    result_df = pd.DataFrame(
        rows
    )


    st.dataframe(
        result_df,
        use_container_width=True,
        hide_index=True,
        column_config={

            "계산 사용 현재가":
                st.column_config.NumberColumn(
                    "계산 사용 현재가",
                    format="%.2f"
                ),

            "현재 평가액(KRW)":
                st.column_config.NumberColumn(
                    "현재 평가액(KRW)",
                    format="₩%,.0f"
                ),

            "현재 비중":
                st.column_config.NumberColumn(
                    "현재 비중",
                    format="%.2f%%"
                ),

            "하단":
                st.column_config.NumberColumn(
                    "하단",
                    format="%.1f%%"
                ),

            "목표":
                st.column_config.NumberColumn(
                    "목표",
                    format="%.1f%%"
                ),

            "상단":
                st.column_config.NumberColumn(
                    "상단",
                    format="%.1f%%"
                ),

            "매도(KRW)":
                st.column_config.NumberColumn(
                    "매도(KRW)",
                    format="₩%,.0f"
                ),

            "매수(KRW)":
                st.column_config.NumberColumn(
                    "매수(KRW)",
                    format="₩%,.0f"
                ),

            "분배 후 금액(KRW)":
                st.column_config.NumberColumn(
                    "분배 후 금액(KRW)",
                    format="₩%,.0f"
                ),

            "분배 후 비중":
                st.column_config.NumberColumn(
                    "분배 후 비중",
                    format="%.2f%%"
                ),
        }
    )


    st.caption(
        "미국 자산의 현지통화 거래금액은 USD, "
        "국내 및 KRW 자산은 KRW로 표시합니다. "
        "예상 주문 주식수는 거래금액 ÷ 계산 사용 현재가의 참고값입니다."
    )

import streamlit as st
import pandas as pd
import yfinance as yf
import requests
from datetime import datetime


# ============================================================
# 기본 설정
# ============================================================

st.set_page_config(
    page_title="원화 기준 밴드 리밸런싱",
    page_icon="📊",
    layout="wide",
)

st.title("📊 원화 기준 밴드 리밸런싱 계산기")

st.caption(
    "국내 ETF와 미국 ETF를 원화 기준으로 통일하여 "
    "밴드 리밸런싱을 계산합니다."
)


# ============================================================
# Session State
# ============================================================

if "assets" not in st.session_state:
    st.session_state.assets = []

if "usdkrw" not in st.session_state:
    st.session_state.usdkrw = 1400.0

if "fx_date" not in st.session_state:
    st.session_state.fx_date = ""

if "fx_error" not in st.session_state:
    st.session_state.fx_error = ""

if "cash" not in st.session_state:
    st.session_state.cash = 0.0

if "result" not in st.session_state:
    st.session_state.result = None


# ============================================================
# 자산 기본 구조
# ============================================================

def create_asset():

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
        "price_error": "",
    }


# ============================================================
# 자산 추가
# ============================================================

def add_asset():

    st.session_state.assets.append(
        create_asset()
    )


# ============================================================
# 자산 삭제
# ============================================================

def delete_asset(index):

    if 0 <= index < len(
        st.session_state.assets
    ):

        st.session_state.assets.pop(index)

        # 계산 결과 초기화
        st.session_state.result = None


# ============================================================
# Yahoo Finance 종목 검색
# ============================================================

@st.cache_data(ttl=600)
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

            symbol = quote.get(
                "symbol"
            )

            if not symbol:
                continue

            quote_type = quote.get(
                "quoteType",
                ""
            )

            if quote_type not in [
                "EQUITY",
                "ETF",
                "MUTUALFUND",
            ]:

                continue

            results.append(
                {
                    "symbol": symbol,

                    "name": (
                        quote.get(
                            "longname"
                        )
                        or quote.get(
                            "shortname"
                        )
                        or symbol
                    ),

                    "exchange": quote.get(
                        "exchange",
                        ""
                    ),

                    "quoteType": quote_type,
                }
            )

        return results

    except Exception:

        return []


# ============================================================
# 시장 판별
# ============================================================

def detect_market(
    symbol,
    exchange
):

    symbol = (
        symbol or ""
    ).upper()

    exchange = (
        exchange or ""
    ).upper()

    if (
        symbol.endswith(".KS")
        or symbol.endswith(".KQ")
    ):

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


# ============================================================
# 국내 티커 정규화
# ============================================================

def normalize_ticker(
    ticker,
    market
):

    ticker = ticker.strip().upper()

    if market != "국내":

        return ticker

    if (
        ticker.endswith(".KS")
        or ticker.endswith(".KQ")
    ):

        return ticker

    # 6자리 한국 종목코드
    if (
        ticker.isdigit()
        and len(ticker) == 6
    ):

        return ticker + ".KS"

    return ticker


# ============================================================
# 최근 일봉 가격 조회
# ============================================================

@st.cache_data(ttl=300)
def get_latest_price(
    ticker
):

    try:

        stock = yf.Ticker(
            ticker
        )

        history = stock.history(
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

        close = (
            history["Close"]
            .dropna()
        )

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

        date = (
            close.index[-1]
            .strftime("%Y-%m-%d")
        )

        return (
            price,
            date,
            None
        )

    except Exception as e:

        return (
            None,
            None,
            f"가격 조회 실패: {str(e)}"
        )


# ============================================================
# USD/KRW 환율 조회
# ============================================================

@st.cache_data(ttl=1800)
def get_usdkrw():

    """
    Frankfurter API에서 가장 최근 제공되는
    USD/KRW 일별 환율을 가져온다.

    Yahoo Finance의 KRW=X를 사용하지 않음.
    """

    try:

        url = (
            "https://api.frankfurter.dev/v2/rates"
        )

        params = {
            "base": "USD",
            "quotes": "KRW",
        }

        response = requests.get(
            url,
            params=params,
            timeout=10,
        )

        response.raise_for_status()

        data = response.json()

        # v2 응답은 rate 객체/배열 구조를
        # 안전하게 처리
        rate = None
        rate_date = None

        if isinstance(data, list):

            for item in data:

                if (
                    item.get("base")
                    == "USD"
                    and item.get("quote")
                    == "KRW"
                ):

                    rate = item.get(
                        "rate"
                    )

                    rate_date = item.get(
                        "date"
                    )

                    break

        elif isinstance(data, dict):

            if "rate" in data:

                rate = data.get(
                    "rate"
                )

                rate_date = data.get(
                    "date"
                )

            elif "rates" in data:

                rates = data["rates"]

                if isinstance(
                    rates,
                    dict
                ):

                    rate = rates.get(
                        "KRW"
                    )

                rate_date = data.get(
                    "date"
                )

        if rate is None:

            return (
                None,
                None,
                "USD/KRW 환율 데이터를 찾지 못했습니다."
            )

        rate = float(rate)

        if rate <= 0:

            return (
                None,
                None,
                "비정상적인 환율 값입니다."
            )

        return (
            rate,
            rate_date,
            None
        )

    except requests.exceptions.RequestException as e:

        return (
            None,
            None,
            f"환율 API 연결 실패: {str(e)}"
        )

    except Exception as e:

        return (
            None,
            None,
            f"환율 조회 실패: {str(e)}"
        )


# ============================================================
# 리밸런싱 계산
# ============================================================

def calculate_rebalancing(
    cash,
    assets,
    usdkrw
):

    # --------------------------------------------------------
    # 계산용 복사본 생성
    # --------------------------------------------------------

    calculated = []

    for asset in assets:

        item = asset.copy()

        if item["market"] == "미국":

            item["amount_krw"] = (
                item["shares"]
                * item["price"]
                * usdkrw
            )

        elif item["market"] == "국내":

            item["amount_krw"] = (
                item["shares"]
                * item["price"]
            )

        else:

            raise ValueError(
                f"{item['name']}의 시장이 지정되지 않았습니다."
            )

        calculated.append(
            item
        )


    # --------------------------------------------------------
    # 총자산
    # --------------------------------------------------------

    total_assets = (
        cash
        + sum(
            item["amount_krw"]
            for item in calculated
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
        item["target"]
        for item in calculated
    )


    if abs(
        target_sum - 100
    ) > 0.0001:

        raise ValueError(
            f"목표 비중 합계가 "
            f"{target_sum:.2f}%입니다."
        )


    # --------------------------------------------------------
    # 현재 상태 계산
    # --------------------------------------------------------

    for item in calculated:

        item["current_weight"] = (
            item["amount_krw"]
            / total_assets
            * 100
        )

        item["sell_amount"] = 0.0
        item["buy_amount"] = 0.0

        item["final_amount"] = (
            item["amount_krw"]
        )

        item["status"] = "유지"


    # --------------------------------------------------------
    # 1. 상단 초과 자산 매도
    # --------------------------------------------------------

    for item in calculated:

        if (
            item["current_weight"]
            > item["upper"]
        ):

            target_amount = (
                total_assets
                * item["target"]
                / 100
            )

            sell_amount = (
                item["amount_krw"]
                - target_amount
            )

            sell_amount = max(
                sell_amount,
                0
            )

            item["sell_amount"] = (
                sell_amount
            )

            item["final_amount"] = (
                target_amount
            )

            item["status"] = (
                "상단 초과 → 목표까지 매도"
            )


    # --------------------------------------------------------
    # 2. 사용 가능한 자금
    # --------------------------------------------------------

    total_sell = sum(
        item["sell_amount"]
        for item in calculated
    )

    available_cash = (
        cash
        + total_sell
    )


    # --------------------------------------------------------
    # 3. 하단 미달 자산
    # --------------------------------------------------------

    underweight = []

    for item in calculated:

        if (
            item["current_weight"]
            < item["lower"]
        ):

            buy_difference = (
                item["target"]
                - item["current_weight"]
            )

            needed_amount = (
                total_assets
                * buy_difference
                / 100
            )

            item["buy_difference"] = (
                buy_difference
            )

            item["needed_amount"] = (
                needed_amount
            )

            item["status"] = (
                "하단 미달 → 목표까지 매수"
            )

            underweight.append(
                item
            )

        else:

            item["buy_difference"] = 0

            item["needed_amount"] = 0


    # --------------------------------------------------------
    # 4. 매수
    # --------------------------------------------------------

    total_needed = sum(
        item["needed_amount"]
        for item in underweight
    )


    # 현금이 부족한 경우
    if (
        total_needed > 0
        and available_cash <= total_needed
    ):

        total_difference = sum(
            item["buy_difference"]
            for item in underweight
        )

        if total_difference > 0:

            for item in underweight:

                buy_amount = (
                    available_cash
                    * item["buy_difference"]
                    / total_difference
                )

                item["buy_amount"] = (
                    buy_amount
                )

                item["final_amount"] = (
                    item["amount_krw"]
                    + buy_amount
                )


    # 현금이 충분한 경우
    elif (
        total_needed > 0
        and available_cash > total_needed
    ):

        for item in underweight:

            buy_amount = (
                item["needed_amount"]
            )

            item["buy_amount"] = (
                buy_amount
            )

            item["final_amount"] = (
                item["amount_krw"]
                + buy_amount
            )


    # --------------------------------------------------------
    # 5. 최종 비중
    # --------------------------------------------------------

    for item in calculated:

        item["final_weight"] = (
            item["final_amount"]
            / total_assets
            * 100
        )


    # --------------------------------------------------------
    # 6. 최종 현금
    # --------------------------------------------------------

    total_buy = sum(
        item["buy_amount"]
        for item in calculated
    )

    final_cash = (
        total_assets
        - sum(
            item["final_amount"]
            for item in calculated
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
# ① 환율
# ============================================================

st.header(
    "① USD/KRW 환율"
)


fx_col1, fx_col2 = st.columns(
    [4, 1]
)


with fx_col1:

    st.number_input(
        "USD/KRW",
        min_value=0.0,
        step=0.01,
        format="%.2f",
        key="usdkrw",
    )


with fx_col2:

    st.write("")

    if st.button(
        "🔄 최신 환율 조회",
        use_container_width=True,
    ):

        rate, date, error = (
            get_usdkrw()
        )

        if error:

            st.session_state.fx_error = (
                error
            )

        else:

            st.session_state.usdkrw = (
                rate
            )

            st.session_state.fx_date = (
                date
                or ""
            )

            st.session_state.fx_error = ""

        st.rerun()


if st.session_state.fx_error:

    st.error(
        st.session_state.fx_error
    )


if st.session_state.fx_date:

    st.caption(
        f"적용 환율: "
        f"1 USD = "
        f"{st.session_state.usdkrw:,.2f} KRW "
        f"(기준일: "
        f"{st.session_state.fx_date})"
    )

else:

    st.caption(
        f"현재 적용 환율: "
        f"1 USD = "
        f"{st.session_state.usdkrw:,.2f} KRW"
    )


# ============================================================
# ② 자산 구성
# ============================================================

st.header(
    "② 자산 구성"
)


if st.button(
    "＋ 자산 추가",
    use_container_width=True,
):

    add_asset()

    st.rerun()


# ============================================================
# 자산 입력
# ============================================================

for i, asset in enumerate(
    st.session_state.assets
):

    st.subheader(
        asset["name"]
        if asset["name"]
        else f"자산 {i + 1}"
    )


    # --------------------------------------------------------
    # 종목 검색
    # --------------------------------------------------------

    search_col1, search_col2 = (
        st.columns([5, 1])
    )


    with search_col1:

        search_query = st.text_input(
            "티커 또는 종목명 검색",
            key=f"search_{i}",
            placeholder=(
                "예: VOO / S&P 500 / KODEX 200"
            ),
        )


    with search_col2:

        st.write("")

        if st.button(
            "🔍 검색",
            key=f"search_button_{i}",
            use_container_width=True,
        ):

            results = search_assets(
                search_query
            )

            st.session_state[
                f"results_{i}"
            ] = results


    results = st.session_state.get(
        f"results_{i}",
        []
    )


    # --------------------------------------------------------
    # 검색 결과
    # --------------------------------------------------------

    if results:

        labels = []

        for result in results:

            labels.append(
                f"{result['name']} "
                f"({result['symbol']}) "
                f"[{result['exchange']}]"
            )


        selected_label = st.selectbox(
            "검색 결과",
            labels,
            key=f"selected_{i}",
        )


        selected_index = (
            labels.index(
                selected_label
            )
        )

        selected = results[
            selected_index
        ]


        if st.button(
            "✅ 이 종목 선택",
            key=f"select_button_{i}",
            use_container_width=True,
        ):

            ticker = selected[
                "symbol"
            ]

            market = detect_market(
                ticker,
                selected["exchange"]
            )


            asset["name"] = selected[
                "name"
            ]

            asset["ticker"] = ticker

            asset["market"] = market

            asset["exchange"] = selected[
                "exchange"
            ]

            asset["currency"] = (
                "USD"
                if market == "미국"
                else "KRW"
            )


            # 종목을 바꾸면 기존 가격 초기화
            asset["price"] = 0.0

            asset["price_date"] = ""

            asset["price_error"] = ""


            st.session_state[
                f"results_{i}"
            ] = []


            st.rerun()


    # --------------------------------------------------------
    # 선택된 종목
    # --------------------------------------------------------

    if asset["ticker"]:

        st.info(
            f"**{asset['name']}**  |  "
            f"`{asset['ticker']}`  |  "
            f"{asset['market']} | "
            f"{asset['currency']}"
        )


    # --------------------------------------------------------
    # 목표 비중 / 밴드
    # --------------------------------------------------------

    st.markdown(
        "### 목표 비중 및 밴드"
    )


    # --------------------------------------------------------
    # 목표 비중
    # --------------------------------------------------------

    target_col1, target_col2 = (
        st.columns([5, 1])
    )


    with target_col1:

        target_slider = st.slider(
            "목표 비중",
            min_value=0.0,
            max_value=100.0,
            value=float(
                asset["target"]
            ),
            step=0.5,
            key=f"target_slider_{i}",
        )


    with target_col2:

        target_number = st.number_input(
            "목표 %",
            min_value=0.0,
            max_value=100.0,
            value=float(
                target_slider
            ),
            step=0.5,
            key=f"target_number_{i}",
        )


    # 숫자 입력을 최종 목표값으로 사용
    target = float(
        target_number
    )


    # --------------------------------------------------------
    # 하단
    # --------------------------------------------------------

    lower_col1, lower_col2 = (
        st.columns([5, 1])
    )


    with lower_col1:

        lower_slider = st.slider(
            "하단 비중",
            min_value=0.0,
            max_value=target,
            value=min(
                float(
                    asset["lower"]
                ),
                target
            ),
            step=0.5,
            key=f"lower_slider_{i}",
        )


    with lower_col2:

        lower_number = st.number_input(
            "하단 %",
            min_value=0.0,
            max_value=target,
            value=float(
                lower_slider
            ),
            step=0.5,
            key=f"lower_number_{i}",
        )


    lower = float(
        lower_number
    )


    # --------------------------------------------------------
    # 상단
    # --------------------------------------------------------

    upper_col1, upper_col2 = (
        st.columns([5, 1])
    )


    with upper_col1:

        upper_slider = st.slider(
            "상단 비중",
            min_value=target,
            max_value=100.0,
            value=max(
                float(
                    asset["upper"]
                ),
                target
            ),
            step=0.5,
            key=f"upper_slider_{i}",
        )


    with upper_col2:

        upper_number = st.number_input(
            "상단 %",
            min_value=target,
            max_value=100.0,
            value=float(
                upper_slider
            ),
            step=0.5,
            key=f"upper_number_{i}",
        )


    upper = float(
        upper_number
    )


    # --------------------------------------------------------
    # 밴드 저장
    # --------------------------------------------------------

    if (
        lower
        <= target
        <= upper
    ):

        asset["target"] = target

        asset["lower"] = lower

        asset["upper"] = upper

    else:

        st.warning(
            "하단 ≤ 목표 ≤ 상단이 되도록 "
            "입력해주세요."
        )


    st.caption(
        f"밴드: "
        f"{lower:.1f}% ~ "
        f"{target:.1f}% ~ "
        f"{upper:.1f}%"
    )


    # --------------------------------------------------------
    # 현재 보유량
    # --------------------------------------------------------

    st.markdown(
        "### 현재 보유량"
    )


    holdings_col1, holdings_col2, holdings_col3 = (
        st.columns([2, 2, 2])
    )


    with holdings_col1:

        shares = st.number_input(
            "보유 주식 수",
            min_value=0.0,
            value=float(
                asset["shares"]
            ),
            step=1.0,
            format="%.6f",
            key=f"shares_{i}",
        )

        asset["shares"] = (
            float(shares)
        )


    with holdings_col2:

        price = st.number_input(
            "현재가",
            min_value=0.0,
            value=float(
                asset["price"]
            ),
            step=0.01,
            format="%.4f",
            key=f"price_{i}",
        )

        asset["price"] = (
            float(price)
        )


    with holdings_col3:

        if asset["market"]:

            if st.button(
                "🔄 최신 가격 조회",
                key=f"price_button_{i}",
                use_container_width=True,
            ):

                ticker = normalize_ticker(
                    asset["ticker"],
                    asset["market"]
                )


                price_value, date, error = (
                    get_latest_price(
                        ticker
                    )
                )


                if error:

                    asset["price_error"] = (
                        error
                    )

                else:

                    asset["price"] = (
                        price_value
                    )

                    asset["price_date"] = (
                        date
                        or ""
                    )

                    asset["price_error"] = ""


                st.rerun()


    if asset["price_error"]:

        st.error(
            asset["price_error"]
        )


    if asset["price_date"]:

        st.caption(
            f"최근 일봉 종가: "
            f"{asset['price']:,.4f} "
            f"{asset['currency']} "
            f"({asset['price_date']})"
        )


    # --------------------------------------------------------
    # 원화 평가액
    # --------------------------------------------------------

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
            "원화 평가액",
            f"{amount_krw:,.0f}원"
        )


    # --------------------------------------------------------
    # 삭제
    # --------------------------------------------------------

    if st.button(
        "🗑️ 자산 삭제",
        key=f"delete_{i}",
    ):

        delete_asset(i)

        st.rerun()


    st.divider()


# ============================================================
# ③ 현금
# ============================================================

st.header(
    "③ 현재 보유 현금"
)


cash = st.number_input(
    "보유 현금 (KRW)",
    min_value=0.0,
    value=float(
        st.session_state.cash
    ),
    step=10000.0,
    format="%.0f",
    key="cash_input",
)

st.session_state.cash = float(
    cash
)


# ============================================================
# ④ 리밸런싱 계산
# ============================================================

st.header(
    "④ 리밸런싱 결과"
)


if st.button(
    "🚀 리밸런싱 계산",
    type="primary",
    use_container_width=True,
):

    try:

        if not st.session_state.assets:

            raise ValueError(
                "자산을 하나 이상 추가해주세요."
            )


        # ----------------------------------------------------
        # 입력 검증
        # ----------------------------------------------------

        for asset in (
            st.session_state.assets
        ):

            if not asset["name"]:

                raise ValueError(
                    "모든 자산을 선택해주세요."
                )


            if not asset["ticker"]:

                raise ValueError(
                    f"{asset['name']}의 종목을 선택해주세요."
                )


            if asset["price"] <= 0:

                raise ValueError(
                    f"{asset['name']}의 가격을 "
                    "조회해주세요."
                )


            if not (
                0
                <= asset["lower"]
                <= asset["target"]
                <= asset["upper"]
                <= 100
            ):

                raise ValueError(
                    f"{asset['name']}의 "
                    "하단 ≤ 목표 ≤ 상단 조건을 확인해주세요."
                )


        # ----------------------------------------------------
        # 목표 비중 합계
        # ----------------------------------------------------

        target_sum = sum(
            asset["target"]
            for asset in (
                st.session_state.assets
            )
        )


        if abs(
            target_sum - 100
        ) > 0.0001:

            raise ValueError(
                f"목표 비중 합계가 "
                f"{target_sum:.2f}%입니다. "
                "100%가 되도록 입력해주세요."
            )


        # ----------------------------------------------------
        # 계산
        # ----------------------------------------------------

        result = calculate_rebalancing(
            cash=float(
                st.session_state.cash
            ),

            assets=(
                st.session_state.assets
            ),

            usdkrw=float(
                st.session_state.usdkrw
            ),
        )


        st.session_state.result = (
            result
        )


    except ValueError as e:

        st.session_state.result = None

        st.error(
            str(e)
        )


# ============================================================
# ⑤ 결과 표시
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
    # 요약
    # --------------------------------------------------------

    c1, c2, c3, c4 = (
        st.columns(4)
    )


    with c1:

        st.metric(
            "총자산",
            f"{result['total_assets']:,.0f}원"
        )


    with c2:

        st.metric(
            "총 매도",
            f"{result['total_sell']:,.0f}원"
        )


    with c3:

        st.metric(
            "총 매수",
            f"{result['total_buy']:,.0f}원"
        )


    with c4:

        st.metric(
            "분배 후 현금",
            f"{result['final_cash']:,.0f}원"
        )


    # --------------------------------------------------------
    # 거래
    # --------------------------------------------------------

    st.subheader(
        "실행할 거래"
    )


    trades = []


    for asset in result["assets"]:

        if (
            asset["sell_amount"]
            > 0.5
        ):

            trades.append(
                {
                    "자산":
                        asset["name"],

                    "시장":
                        asset["market"],

                    "거래":
                        "🔴 매도",

                    "금액":
                        asset["sell_amount"],
                }
            )


        if (
            asset["buy_amount"]
            > 0.5
        ):

            trades.append(
                {
                    "자산":
                        asset["name"],

                    "시장":
                        asset["market"],

                    "거래":
                        "🟢 매수",

                    "금액":
                        asset["buy_amount"],
                }
            )


    if trades:

        trade_df = pd.DataFrame(
            trades
        )


        st.dataframe(
            trade_df,
            use_container_width=True,
            hide_index=True,
            column_config={
                "금액":
                    st.column_config.NumberColumn(
                        "금액",
                        format="₩%,.0f",
                    )
            },
        )

    else:

        st.info(
            "현재 밴드를 벗어난 자산이 없어 "
            "매매가 필요하지 않습니다."
        )


    # --------------------------------------------------------
    # 전체 포트폴리오
    # --------------------------------------------------------

    st.subheader(
        "전체 포트폴리오"
    )


    rows = []


    for asset in result[
        "assets"
    ]:

        rows.append(
            {
                "자산":
                    asset["name"],

                "시장":
                    asset["market"],

                "현재 평가액":
                    asset["amount_krw"],

                "현재 비중":
                    asset["current_weight"]
                    / 100,

                "하단":
                    asset["lower"]
                    / 100,

                "목표":
                    asset["target"]
                    / 100,

                "상단":
                    asset["upper"]
                    / 100,

                "매도":
                    asset["sell_amount"],

                "매수":
                    asset["buy_amount"],

                "분배 후 금액":
                    asset["final_amount"],

                "분배 후 비중":
                    asset["final_weight"]
                    / 100,

                "상태":
                    asset["status"],
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

            "현재 평가액":
                st.column_config.NumberColumn(
                    "현재 평가액",
                    format="₩%,.0f",
                ),

            "현재 비중":
                st.column_config.NumberColumn(
                    "현재 비중",
                    format="%.2f%%",
                ),

            "하단":
                st.column_config.NumberColumn(
                    "하단",
                    format="%.1f%%",
                ),

            "목표":
                st.column_config.NumberColumn(
                    "목표",
                    format="%.1f%%",
                ),

            "상단":
                st.column_config.NumberColumn(
                    "상단",
                    format="%.1f%%",
                ),

            "매도":
                st.column_config.NumberColumn(
                    "매도",
                    format="₩%,.0f",
                ),

            "매수":
                st.column_config.NumberColumn(
                    "매수",
                    format="₩%,.0f",
                ),

            "분배 후 금액":
                st.column_config.NumberColumn(
                    "분배 후 금액",
                    format="₩%,.0f",
                ),

            "분배 후 비중":
                st.column_config.NumberColumn(
                    "분배 후 비중",
                    format="%.2f%%",
                ),
        },
    )


    st.caption(
        "미국 ETF는 USD 가격 × USD/KRW 환율로 "
        "원화 환산합니다. "
        "가격과 환율은 최신 제공 일봉 기준이며 "
        "실제 주문 체결가격과 다를 수 있습니다."
    )

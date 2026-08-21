import streamlit as st
import pandas as pd
import yfinance as yf
import requests


# ============================================================
# 기본 설정
# ============================================================

st.set_page_config(
    page_title="원화 기준 밴드 리밸런싱",
    page_icon="📊",
    layout="wide",
)

st.title("📊 원화 기준 밴드 리밸런싱")
st.caption(
    "국내 ETF와 미국 ETF를 원화 기준으로 통합하여 "
    "밴드 리밸런싱을 계산합니다."
)


# ============================================================
# Session State 초기화
# ============================================================

if "assets" not in st.session_state:
    st.session_state.assets = []

if "usdkrw" not in st.session_state:
    st.session_state.usdkrw = 1400.0

if "fx_date" not in st.session_state:
    st.session_state.fx_date = ""

if "fx_error" not in st.session_state:
    st.session_state.fx_error = ""

if "result" not in st.session_state:
    st.session_state.result = None

if "cash" not in st.session_state:
    st.session_state.cash = 0.0


# ============================================================
# 자산 데이터 구조
# ============================================================

def create_asset():

    return {
        # 종목 정보
        "name": "",
        "ticker": "",
        "market": "",
        "currency": "",
        "exchange": "",

        # 목표 비중
        "target": 0.0,
        "lower": 0.0,
        "upper": 0.0,

        # 보유량
        "shares": 0.0,
        "price": 0.0,

        # 가격 정보
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

    st.session_state.result = None


# ============================================================
# 자산 삭제
# ============================================================

def delete_asset(index):

    if 0 <= index < len(
        st.session_state.assets
    ):

        st.session_state.assets.pop(index)

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
                "",
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
                        quote.get("longname")
                        or quote.get("shortname")
                        or symbol
                    ),
                    "exchange": quote.get(
                        "exchange",
                        "",
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
    exchange,
):

    symbol = (
        symbol or ""
    ).upper()

    exchange = (
        exchange or ""
    ).upper()

    korean_exchanges = {
        "KSC",
        "KOE",
        "KSE",
        "KQX",
        "KO",
    }

    if (
        symbol.endswith(".KS")
        or symbol.endswith(".KQ")
        or exchange in korean_exchanges
    ):

        return "국내"

    return "미국"


# ============================================================
# 국내 티커 정규화
# ============================================================

def normalize_ticker(
    ticker,
    market,
):

    ticker = (
        ticker or ""
    ).strip().upper()

    if market != "국내":
        return ticker

    if (
        ticker.endswith(".KS")
        or ticker.endswith(".KQ")
    ):
        return ticker

    if (
        ticker.isdigit()
        and len(ticker) == 6
    ):
        return ticker + ".KS"

    return ticker


# ============================================================
# 최신 ETF 가격 조회
# ============================================================

@st.cache_data(ttl=300)
def get_latest_price(
    ticker,
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
                "가격 데이터를 찾을 수 없습니다.",
            )

        close = (
            history["Close"]
            .dropna()
        )

        if close.empty:

            return (
                None,
                None,
                "종가 데이터를 찾을 수 없습니다.",
            )

        price = float(
            close.iloc[-1]
        )

        if price <= 0:

            return (
                None,
                None,
                "비정상적인 가격 데이터입니다.",
            )

        price_date = (
            close.index[-1]
            .strftime("%Y-%m-%d")
        )

        return (
            price,
            price_date,
            None,
        )

    except Exception as e:

        return (
            None,
            None,
            f"가격 조회 실패: {str(e)}",
        )


# ============================================================
# USD/KRW 환율 조회
# ============================================================

@st.cache_data(ttl=1800)
def get_usdkrw():

    """
    Frankfurter 최신 영업일 USD/KRW 환율.
    Yahoo Finance의 KRW=X를 사용하지 않는다.
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

        rate = None
        date = None

        # v2 응답
        if isinstance(
            data,
            list,
        ):

            for row in data:

                if (
                    row.get("base")
                    == "USD"
                    and row.get("quote")
                    == "KRW"
                ):

                    rate = row.get(
                        "rate"
                    )

                    date = row.get(
                        "date"
                    )

                    break

        elif isinstance(
            data,
            dict,
        ):

            if "rate" in data:

                rate = data.get(
                    "rate"
                )

                date = data.get(
                    "date"
                )

            elif "rates" in data:

                rates = data.get(
                    "rates"
                )

                if isinstance(
                    rates,
                    dict,
                ):

                    rate = rates.get(
                        "KRW"
                    )

                date = data.get(
                    "date"
                )

        if rate is None:

            return (
                None,
                None,
                "USD/KRW 환율 데이터를 찾지 못했습니다.",
            )

        rate = float(rate)

        if rate <= 0:

            return (
                None,
                None,
                "비정상적인 환율 값입니다.",
            )

        return (
            rate,
            date,
            None,
        )

    except requests.exceptions.RequestException as e:

        return (
            None,
            None,
            f"환율 API 연결 실패: {str(e)}",
        )

    except Exception as e:

        return (
            None,
            None,
            f"환율 조회 실패: {str(e)}",
        )


# ============================================================
# 리밸런싱 계산
# ============================================================

def calculate_rebalancing(
    cash,
    assets,
    usdkrw,
):

    calculated = []

    # --------------------------------------------------------
    # 보유자산 계산
    # --------------------------------------------------------

    for original in assets:

        asset = original.copy()

        if asset["market"] == "미국":

            asset["amount_krw"] = (
                asset["shares"]
                * asset["price"]
                * usdkrw
            )

        elif asset["market"] == "국내":

            asset["amount_krw"] = (
                asset["shares"]
                * asset["price"]
            )

        else:

            raise ValueError(
                f"{asset['name']}의 시장을 확인해주세요."
            )

        calculated.append(
            asset
        )


    # --------------------------------------------------------
    # 총자산
    # --------------------------------------------------------

    total_assets = (
        cash
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
    # 목표비중 검증
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
    # 현재비중 초기화
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

        asset["status"] = "유지"


    # --------------------------------------------------------
    # 1. 상단 초과 → 목표비중까지 매도
    # --------------------------------------------------------

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

            sell_amount = (
                asset["amount_krw"]
                - target_amount
            )

            sell_amount = max(
                sell_amount,
                0.0,
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
    # 2. 현금 + 매도대금
    # --------------------------------------------------------

    total_sell = sum(
        asset["sell_amount"]
        for asset in calculated
    )

    available_cash = (
        cash
        + total_sell
    )


    # --------------------------------------------------------
    # 3. 하단 미달
    # --------------------------------------------------------

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
                "하단 미달 → 매수"
            )

            underweight.append(
                asset
            )

        else:

            asset["buy_difference"] = 0.0
            asset["needed_amount"] = 0.0


    # --------------------------------------------------------
    # 4. 매수
    # --------------------------------------------------------

    total_needed = sum(
        asset["needed_amount"]
        for asset in underweight
    )


    # 현금이 부족하면
    # 목표와 현재 비중 차이에 비례하여 배분
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


    # 현금이 충분하면
    # 목표비중까지 매수
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


    # --------------------------------------------------------
    # 5. 최종비중
    # --------------------------------------------------------

    for asset in calculated:

        asset["final_weight"] = (
            asset["final_amount"]
            / total_assets
            * 100
        )


    # --------------------------------------------------------
    # 6. 최종 현금
    # --------------------------------------------------------

    total_buy = sum(
        asset["buy_amount"]
        for asset in calculated
    )

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
        "total_assets": total_assets,
        "total_sell": total_sell,
        "total_buy": total_buy,
        "final_cash": final_cash,
        "assets": calculated,
    }


# ============================================================
# ① 환율
# ============================================================

st.header("① USD/KRW 환율")


fx_col1, fx_col2 = st.columns(
    [4, 1]
)


with fx_col1:

    # 실제 계산용 usdkrw와
    # 위젯 키를 분리한다.
    fx_input = st.number_input(
        "USD/KRW",
        min_value=0.0,
        step=0.01,
        value=float(
            st.session_state.usdkrw
        ),
        format="%.2f",
        key="fx_input_widget",
    )


with fx_col2:

    st.write("")

    refresh_fx = st.button(
        "🔄 최신 환율 조회",
        use_container_width=True,
    )


# 사용자가 직접 입력한 환율을 계산용 값으로 반영
st.session_state.usdkrw = float(
    fx_input
)


# 자동 조회
if refresh_fx:

    rate, date, error = (
        get_usdkrw()
    )

    if error:

        st.session_state.fx_error = (
            error
        )

        st.error(
            error
        )

    else:

        st.session_state.usdkrw = (
            float(rate)
        )

        st.session_state.fx_date = (
            date or ""
        )

        st.session_state.fx_error = ""

        # 위젯 state를 이 실행에서 직접 변경하지 않고
        # 다음 rerun에서 새 기본값을 사용하도록 한다.
        st.rerun()


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
# ② 자산
# ============================================================

st.header("② 자산 구성")


if st.button(
    "＋ 자산 추가",
    use_container_width=True,
):

    add_asset()

    st.rerun()


# ============================================================
# 자산별 입력
# ============================================================

for i, asset in enumerate(
    st.session_state.assets
):

    title = (
        asset["name"]
        if asset["name"]
        else f"자산 {i + 1}"
    )

    st.subheader(title)


    # --------------------------------------------------------
    # 종목 검색
    # --------------------------------------------------------

    search_col1, search_col2 = (
        st.columns([5, 1])
    )


    with search_col1:

        search_query = st.text_input(
            "티커 또는 종목명",
            key=f"search_{i}",
            placeholder=(
                "예: VOO / S&P 500 / KODEX 200"
            ),
        )


    with search_col2:

        st.write("")

        search_clicked = st.button(
            "🔍 검색",
            key=f"search_button_{i}",
            use_container_width=True,
        )


    if search_clicked:

        st.session_state[
            f"search_results_{i}"
        ] = search_assets(
            search_query
        )


    results = st.session_state.get(
        f"search_results_{i}",
        [],
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
            key=f"selected_result_{i}",
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
            key=f"select_asset_{i}",
            use_container_width=True,
        ):

            asset["name"] = selected[
                "name"
            ]

            asset["ticker"] = selected[
                "symbol"
            ]

            asset["exchange"] = selected[
                "exchange"
            ]

            asset["market"] = detect_market(
                selected["symbol"],
                selected["exchange"],
            )

            asset["currency"] = (
                "USD"
                if asset["market"] == "미국"
                else "KRW"
            )

            # 종목을 바꾸면 가격 초기화
            asset["price"] = 0.0
            asset["price_date"] = ""
            asset["price_error"] = ""

            st.session_state[
                f"search_results_{i}"
            ] = []

            st.session_state.result = None

            st.rerun()


    # --------------------------------------------------------
    # 선택된 종목
    # --------------------------------------------------------

    if asset["ticker"]:

        st.info(
            f"**{asset['name']}**  \n"
            f"티커: `{asset['ticker']}`  \n"
            f"시장: **{asset['market']}**  \n"
            f"통화: **{asset['currency']}**"
        )


    # ========================================================
    # 비중 / 밴드 FORM
    # ========================================================

    with st.form(
        key=f"weight_form_{i}"
    ):

        st.markdown(
            "#### 목표 비중 및 밴드"
        )

        # ----------------------------------------------------
        # 현재값
        # ----------------------------------------------------

        current_target = float(
            asset["target"]
        )

        current_lower = float(
            asset["lower"]
        )

        current_upper = float(
            asset["upper"]
        )


        # ----------------------------------------------------
        # 목표
        # ----------------------------------------------------

        target_col1, target_col2 = (
            st.columns([4, 1])
        )


        with target_col1:

            target_slider = st.slider(
                "목표 비중",
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


        # ----------------------------------------------------
        # 하단
        # ----------------------------------------------------

        lower_col1, lower_col2 = (
            st.columns([4, 1])
        )


        with lower_col1:

            lower_slider = st.slider(
                "하단 비중",
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


        # ----------------------------------------------------
        # 상단
        # ----------------------------------------------------

        upper_col1, upper_col2 = (
            st.columns([4, 1])
        )


        with upper_col1:

            upper_slider = st.slider(
                "상단 비중",
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


        # ----------------------------------------------------
        # 적용 버튼
        # ----------------------------------------------------

        apply_weights = st.form_submit_button(
            "✅ 비중 및 밴드 적용",
            use_container_width=True,
        )


    # --------------------------------------------------------
    # Form 제출
    # --------------------------------------------------------

    if apply_weights:

        # ----------------------------------------------------
        # 슬라이더와 숫자 입력이 다를 경우
        #
        # 숫자 입력값을 우선 사용
        # ----------------------------------------------------

        target = float(
            target_number
        )

        lower = float(
            lower_number
        )

        upper = float(
            upper_number
        )


        # ----------------------------------------------------
        # 검증
        # ----------------------------------------------------

        if not (
            0
            <= lower
            <= target
            <= upper
            <= 100
        ):

            st.error(
                "반드시 "
                "하단 ≤ 목표 ≤ 상단 "
                "조건을 만족해야 합니다."
            )

        else:

            asset["target"] = target
            asset["lower"] = lower
            asset["upper"] = upper

            st.session_state.result = None

            st.success(
                f"적용 완료: "
                f"{lower:.1f}% ≤ "
                f"{target:.1f}% ≤ "
                f"{upper:.1f}%"
            )


    st.caption(
        f"현재 적용값: "
        f"{asset['lower']:.1f}% ≤ "
        f"{asset['target']:.1f}% ≤ "
        f"{asset['upper']:.1f}%"
    )


    # ========================================================
    # 보유 주식 / 가격
    # ========================================================

    st.markdown(
        "#### 현재 보유량"
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

        asset["shares"] = float(
            shares
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

        asset["price"] = float(
            price
        )


    with holdings_col3:

        if asset["ticker"]:

            get_price_clicked = st.button(
                "🔄 최신 가격 조회",
                key=f"get_price_{i}",
                use_container_width=True,
            )

            if get_price_clicked:

                ticker = normalize_ticker(
                    asset["ticker"],
                    asset["market"],
                )

                price_value, price_date, error = (
                    get_latest_price(
                        ticker
                    )
                )

                if error:

                    asset["price_error"] = (
                        error
                    )

                    st.error(
                        error
                    )

                else:

                    asset["price"] = (
                        price_value
                    )

                    asset["price_date"] = (
                        price_date or ""
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


    # ========================================================
    # 원화 평가액
    # ========================================================

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


    # ========================================================
    # 삭제
    # ========================================================

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

st.header("③ 현재 보유 현금")


cash = st.number_input(
    "현재 보유 현금 (KRW)",
    min_value=0.0,
    value=float(
        st.session_state.cash
    ),
    step=10000.0,
    format="%.0f",
    key="cash_widget",
)

st.session_state.cash = float(
    cash
)


# ============================================================
# ④ 리밸런싱 계산
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


        # ----------------------------------------------------
        # 입력 검증
        # ----------------------------------------------------

        for asset in (
            st.session_state.assets
        ):

            if not asset["ticker"]:

                raise ValueError(
                    "모든 자산을 검색해서 선택해주세요."
                )


            if asset["price"] <= 0:

                raise ValueError(
                    f"{asset['name']}의 현재가를 "
                    "입력하거나 최신 가격을 조회해주세요."
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
# ⑤ 결과
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
    # 실제 거래
    # --------------------------------------------------------

    st.subheader(
        "실행할 거래"
    )


    trades = []


    for asset in result["assets"]:

        if asset["sell_amount"] > 0.5:

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


        if asset["buy_amount"] > 0.5:

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
            "현재 모든 자산이 밴드 안에 있어 "
            "매매가 필요하지 않습니다."
        )


    # --------------------------------------------------------
    # 전체 포트폴리오
    # --------------------------------------------------------

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

                "현재 평가액":
                    asset["amount_krw"],

                "현재 비중":
                    asset["current_weight"],

                "하단":
                    asset["lower"],

                "목표":
                    asset["target"],

                "상단":
                    asset["upper"],

                "매도":
                    asset["sell_amount"],

                "매수":
                    asset["buy_amount"],

                "분배 후 금액":
                    asset["final_amount"],

                "분배 후 비중":
                    asset["final_weight"],

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
        "미국 자산은 USD 가격을 USD/KRW 환율로 "
        "원화 환산합니다. 가격과 환율은 최신 제공 "
        "일봉 데이터 기준이며 실제 주문 체결가격과 "
        "다를 수 있습니다."
    )

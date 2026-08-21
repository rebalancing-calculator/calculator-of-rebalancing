import streamlit as st
import pandas as pd
import yfinance as yf


@st.cache_data(ttl=300)
def get_exchange_rate():
    """
    Yahoo Finance에서 USD/KRW 환율을 조회한다.
    KRW=X = USD/KRW
    """

    try:
        ticker = yf.Ticker("KRW=X")

        history = ticker.history(
            period="5d",
            interval="1d",
            auto_adjust=False
        )

        if history.empty:
            return None, "USD/KRW 환율 데이터를 가져오지 못했습니다."

        close = history["Close"].dropna()

        if close.empty:
            return None, "USD/KRW 환율 데이터가 없습니다."

        rate = float(close.iloc[-1])

        if rate <= 0:
            return None, "비정상적인 환율 값입니다."

        return rate, None

    except Exception as e:
        return None, f"환율 조회 실패: {str(e)}"

# ============================================================
# 기본 설정
# ============================================================

st.set_page_config(
    page_title="KRW 리밸런싱 계산기",
    page_icon="📊",
    layout="wide"
)

st.title("📊 원화 기준 밴드 리밸런싱")


# ============================================================
# 세션 상태 초기화
# ============================================================

if "assets" not in st.session_state:
    st.session_state.assets = []

if "usdkrw" not in st.session_state:
    st.session_state.usdkrw = 1400.0


# ============================================================
# 자산 추가
# ============================================================

def add_asset():

    st.session_state.assets.append({
        "name": "",
        "ticker": "",
        "market": "",

        "target": 0.0,
        "lower": 0.0,
        "upper": 0.0,

        "shares": 0.0,
        "price": 0.0,
        "currency": "",

        "search_results": []
    })


# ============================================================
# 자산 삭제
# ============================================================

def delete_asset(i):

    st.session_state.assets.pop(i)


# ============================================================
# Yahoo Finance 검색
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
            lists_count=0
        )

        results = []

        for q in search.quotes:

            symbol = q.get("symbol")

            if not symbol:
                continue

            quote_type = q.get(
                "quoteType",
                ""
            )

            # 주식 / ETF / 펀드 정도만
            if quote_type not in [
                "EQUITY",
                "ETF",
                "MUTUALFUND"
            ]:
                continue

            results.append({
                "symbol": symbol,
                "name": (
                    q.get("longname")
                    or q.get("shortname")
                    or symbol
                ),
                "exchange": q.get(
                    "exchange",
                    ""
                ),
                "quoteType": quote_type
            })

        return results

    except Exception:
        return []


# ============================================================
# 시장 판별
# ============================================================

def detect_market(symbol, exchange):

    symbol = symbol.upper()

    exchange = (
        exchange or ""
    ).upper()

    # 한국 거래소
    if (
        symbol.endswith(".KS")
        or symbol.endswith(".KQ")
        or exchange in [
            "KSC",
            "KOE",
            "KSE",
            "KO"
        ]
    ):
        return "국내"

    return "미국"


# ============================================================
# 가격 조회
# ============================================================

@st.cache_data(ttl=300)
def get_price(symbol):

    try:

        ticker = yf.Ticker(
            symbol
        )

        # --------------------------------------------
        # 1차: fast_info
        # --------------------------------------------

        try:

            fi = ticker.fast_info

            price = fi.get(
                "last_price"
            )

            currency = fi.get(
                "currency"
            )

            if price is not None:

                return (
                    float(price),
                    currency,
                    None
                )

        except Exception:
            pass


        # --------------------------------------------
        # 2차: history
        # --------------------------------------------

        history = ticker.history(
            period="5d",
            interval="1d"
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
                "가격 데이터를 찾을 수 없습니다."
            )

        price = float(
            close.iloc[-1]
        )


        # 통화 추정
        if (
            symbol.endswith(".KS")
            or symbol.endswith(".KQ")
        ):
            currency = "KRW"
        else:
            currency = "USD"


        return (
            price,
            currency,
            None
        )


    except Exception as e:

        return (
            None,
            None,
            f"가격 조회 실패: {e}"
        )


# ============================================================
# USD/KRW 환율 조회
# ============================================================

# ============================================================
# 환율
# ============================================================

st.header("💱 USD/KRW 환율")

fx_col1, fx_col2 = st.columns([3, 1])

with fx_col1:

    st.number_input(
        "USD/KRW",
        min_value=0.0,
        step=0.01,
        key="usdkrw",
        format="%.2f"
    )

with fx_col2:

    st.write("")

    if st.button(
        "🔄 환율 자동 조회",
        use_container_width=True
    ):

        rate, error = get_exchange_rate()

        if error:
            st.error(error)

        else:
            st.session_state.usdkrw = rate

            st.rerun()


st.caption(
    f"현재 적용 환율: "
    f"1 USD = {st.session_state.usdkrw:,.2f} KRW"
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
    # 원화 평가액
    # --------------------------------------------------------

    for asset in assets:

        if asset["market"] == "미국":

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


    # --------------------------------------------------------
    # 총자산
    # --------------------------------------------------------

    total_assets = (
        cash
        + sum(
            a["amount_krw"]
            for a in assets
        )
    )


    if total_assets <= 0:

        raise ValueError(
            "총자산이 0원입니다."
        )


    # --------------------------------------------------------
    # 목표 비중 확인
    # --------------------------------------------------------

    target_sum = sum(
        a["target"]
        for a in assets
    )

    if abs(
        target_sum - 100
    ) > 0.0001:

        raise ValueError(
            f"목표 비중 합계가 "
            f"{target_sum:.1f}%입니다. "
            f"100%가 되도록 입력해주세요."
        )


    # --------------------------------------------------------
    # 현재 비중
    # --------------------------------------------------------

    for asset in assets:

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
    # 상단 초과 → 목표 비중까지 매도
    # --------------------------------------------------------

    for asset in assets:

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

            asset["sell_amount"] = (
                max(
                    sell_amount,
                    0
                )
            )

            asset["final_amount"] = (
                target_amount
            )

            asset["status"] = (
                "상단 초과 → 매도"
            )


    # --------------------------------------------------------
    # 매도 + 현금
    # --------------------------------------------------------

    available_cash = (
        cash
        + sum(
            a["sell_amount"]
            for a in assets
        )
    )


    # --------------------------------------------------------
    # 하단 미달 자산
    # --------------------------------------------------------

    underweight = []

    for asset in assets:

        if (
            asset["current_weight"]
            < asset["lower"]
        ):

            difference = (
                asset["target"]
                - asset["current_weight"]
            )

            needed = (
                total_assets
                * difference
                / 100
            )

            asset["buy_difference"] = (
                difference
            )

            asset["needed_amount"] = (
                needed
            )

            underweight.append(
                asset
            )

        else:

            asset["buy_difference"] = 0
            asset["needed_amount"] = 0


    # --------------------------------------------------------
    # 하단 미달 자산에 매수금 배분
    # --------------------------------------------------------

    total_needed = sum(
        a["needed_amount"]
        for a in underweight
    )


    # 현금이 부족한 경우
    if (
        total_needed > 0
        and available_cash <= total_needed
    ):

        total_difference = sum(
            a["buy_difference"]
            for a in underweight
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


    # 현금이 충분한 경우
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
    # 최종 비중
    # --------------------------------------------------------

    for asset in assets:

        asset["final_weight"] = (
            asset["final_amount"]
            / total_assets
            * 100
        )


    # --------------------------------------------------------
    # 최종 현금
    # --------------------------------------------------------

    total_buy = sum(
        a["buy_amount"]
        for a in assets
    )

    total_sell = sum(
        a["sell_amount"]
        for a in assets
    )

    final_cash = (
        total_assets
        - sum(
            a["final_amount"]
            for a in assets
        )
    )

    if abs(final_cash) < 0.01:
        final_cash = 0


    return {
        "total_assets": total_assets,
        "total_buy": total_buy,
        "total_sell": total_sell,
        "final_cash": final_cash,
        "assets": assets
    }


# ============================================================
# 화면
# ============================================================


# ============================================================
# 1. 환율
# ============================================================

st.header("💱 환율")

fx_col1, fx_col2 = st.columns(
    [3, 1]
)


with fx_col1:

    # 세션 상태에 직접 연결
    st.number_input(
        "USD/KRW",
        min_value=0.0,
        step=0.01,
        key="usdkrw",
        format="%.2f"
    )


with fx_col2:

    st.write("")

    if st.button(
        "🔄 환율 자동 조회",
        use_container_width=True
    ):

        rate, error = (
            get_exchange_rate()
        )

        if error:

            st.error(error)

        else:

            # ----------------------------------------
            # 조회된 값을 바로 입력칸에 넣는다
            # ----------------------------------------

            st.session_state.usdkrw = rate

            st.rerun()


st.caption(
    f"현재 적용 환율: "
    f"1 USD = {st.session_state.usdkrw:,.2f} KRW"
)


# ============================================================
# 2. 자산
# ============================================================

st.header("📁 자산")


if st.button(
    "＋ 자산 추가",
    use_container_width=True
):

    add_asset()

    st.rerun()


# ============================================================
# 자산별 입력
# ============================================================

for i, asset in enumerate(
    st.session_state.assets
):

    st.subheader(
        f"자산 {i + 1}"
    )


    # ========================================================
    # 종목 검색
    # ========================================================

    search_query = st.text_input(
        "티커 또는 종목명 검색",
        key=f"search_{i}",
        placeholder=(
            "예: VOO / S&P 500 / KODEX 200"
        )
    )


    if st.button(
        "🔍 종목 검색",
        key=f"search_button_{i}"
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


    # ========================================================
    # 검색 결과
    # ========================================================

    if results:

        options = []

        for r in results:

            options.append(
                (
                    f"{r['name']} "
                    f"({r['symbol']}) "
                    f"[{r['exchange']}]",
                    r
                )
            )


        selected_label = st.selectbox(
            "검색 결과",
            options=[
                x[0]
                for x in options
            ],
            key=f"selected_{i}"
        )


        selected = next(
            x[1]
            for x in options
            if x[0] == selected_label
        )


        if st.button(
            "✅ 이 종목 선택",
            key=f"select_button_{i}"
        ):

            symbol = selected[
                "symbol"
            ]

            exchange = selected[
                "exchange"
            ]

            market = detect_market(
                symbol,
                exchange
            )


            asset["name"] = selected[
                "name"
            ]

            asset["ticker"] = symbol

            asset["market"] = market

            asset["currency"] = (
                "USD"
                if market == "미국"
                else "KRW"
            )


            # 검색 결과 초기화
            st.session_state[
                f"results_{i}"
            ] = []


            st.rerun()


    # ========================================================
    # 선택된 종목 표시
    # ========================================================

    if asset["ticker"]:

        st.info(
            f"선택된 종목: "
            f"**{asset['name']}**  \n"
            f"티커: `{asset['ticker']}`  \n"
            f"시장: **{asset['market']}**  \n"
            f"통화: **{asset['currency']}**"
        )


    # ========================================================
    # 목표 비중 / 밴드
    # ========================================================

    st.markdown(
        "### 목표 비중 및 밴드"
    )


    target_col1, target_col2 = st.columns(
        [4, 1]
    )


    with target_col1:

        target_slider = st.slider(
            "목표 비중",
            0.0,
            100.0,
            float(
                asset["target"]
            ),
            0.5,
            key=f"target_slider_{i}"
        )


    with target_col2:

        target_number = st.number_input(
            "목표 %",
            0.0,
            100.0,
            float(
                asset["target"]
            ),
            0.5,
            key=f"target_number_{i}"
        )


    # 둘 중 최신 값을 사용
    target = target_number


    lower_col1, lower_col2 = st.columns(
        [4, 1]
    )


    with lower_col1:

        lower_slider = st.slider(
            "하단",
            0.0,
            float(target),
            min(
                float(asset["lower"]),
                float(target)
            ),
            0.5,
            key=f"lower_slider_{i}"
        )


    with lower_col2:

        lower_number = st.number_input(
            "하단 %",
            0.0,
            float(target),
            min(
                float(asset["lower"]),
                float(target)
            ),
            0.5,
            key=f"lower_number_{i}"
        )


    upper_col1, upper_col2 = st.columns(
        [4, 1]
    )


    with upper_col1:

        upper_slider = st.slider(
            "상단",
            float(target),
            100.0,
            max(
                float(asset["upper"]),
                float(target)
            ),
            0.5,
            key=f"upper_slider_{i}"
        )


    with upper_col2:

        upper_number = st.number_input(
            "상단 %",
            float(target),
            100.0,
            max(
                float(asset["upper"]),
                float(target)
            ),
            0.5,
            key=f"upper_number_{i}"
        )


    asset["target"] = target
    asset["lower"] = lower_number
    asset["upper"] = upper_number


    # ========================================================
    # 현재 보유량
    # ========================================================

    st.markdown(
        "### 현재 보유량"
    )


    col1, col2, col3 = st.columns(
        [2, 2, 2]
    )


    with col1:

        asset["shares"] = st.number_input(
            "보유 주식 수",
            min_value=0.0,
            value=float(
                asset["shares"]
            ),
            step=1.0,
            key=f"shares_{i}"
        )


    with col2:

        st.number_input(
            "현재가",
            min_value=0.0,
            step=0.01,
            value=float(
                asset["price"]
            ),
            key=f"price_{i}",
            format="%.4f"
        )

        asset["price"] = st.session_state[
            f"price_{i}"
        ]


    with col3:

        if asset["ticker"]:

            if st.button(
                "🔄 현재가 자동 조회",
                key=f"price_button_{i}",
                use_container_width=True
            ):

                price, currency, error = (
                    get_price(
                        asset["ticker"]
                    )
                )


                if error:

                    st.error(error)

                else:

                    # ------------------------------------
                    # 조회 가격을 입력칸에 자동 입력
                    # ------------------------------------

                    asset["price"] = price

                    asset["currency"] = (
                        currency
                        or asset["currency"]
                    )

                    st.session_state[
                        f"price_{i}"
                    ] = price

                    st.rerun()


    # ========================================================
    # 원화 평가액
    # ========================================================

    if asset["market"] == "미국":

        amount_krw = (
            asset["shares"]
            * asset["price"]
            * st.session_state.usdkrw
        )

        st.metric(
            "원화 평가액",
            f"{amount_krw:,.0f}원"
        )

        st.caption(
            f"${asset['price']:,.2f}"
            f" × "
            f"{st.session_state.usdkrw:,.2f}"
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
        "🗑️ 이 자산 삭제",
        key=f"delete_{i}"
    ):

        delete_asset(i)

        st.rerun()


    st.divider()


# ============================================================
# 3. 현금
# ============================================================

st.header("💵 현금")

cash = st.number_input(
    "현재 보유 현금 (KRW)",
    min_value=0.0,
    value=0.0,
    step=10000.0,
    format="%.0f"
)


# ============================================================
# 4. 리밸런싱
# ============================================================

st.header("📊 리밸런싱 결과")


if st.button(
    "🚀 리밸런싱 계산",
    type="primary",
    use_container_width=True
):

    try:

        if not st.session_state.assets:

            raise ValueError(
                "자산을 하나 이상 추가해주세요."
            )


        # ----------------------------------------------------
        # 입력 검증
        # ----------------------------------------------------

        for asset in st.session_state.assets:

            if not asset["ticker"]:

                raise ValueError(
                    "모든 자산을 검색해서 선택해주세요."
                )


            if asset["price"] <= 0:

                raise ValueError(
                    f"{asset['name']}의 "
                    "현재가를 조회해주세요."
                )


        # ----------------------------------------------------
        # 계산
        # ----------------------------------------------------

        result = calculate_rebalancing(
            cash,
            st.session_state.assets,
            st.session_state.usdkrw
        )


        # ----------------------------------------------------
        # 요약
        # ----------------------------------------------------

        c1, c2, c3, c4 = st.columns(4)


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


        # ----------------------------------------------------
        # 결과 테이블
        # ----------------------------------------------------

        rows = []


        for asset in result["assets"]:

            rows.append({

                "자산":
                    asset["name"],

                "시장":
                    asset["market"],

                "현재 평가액":
                    f"{asset['amount_krw']:,.0f}원",

                "현재 비중":
                    f"{asset['current_weight']:.2f}%",

                "하단":
                    f"{asset['lower']:.1f}%",

                "목표":
                    f"{asset['target']:.1f}%",

                "상단":
                    f"{asset['upper']:.1f}%",

                "매도":
                    f"{asset['sell_amount']:,.0f}원",

                "매수":
                    f"{asset['buy_amount']:,.0f}원",

                "분배 후 비중":
                    f"{asset['final_weight']:.2f}%",

                "상태":
                    asset["status"]
            })


        st.dataframe(
            pd.DataFrame(rows),
            use_container_width=True,
            hide_index=True
        )


    except ValueError as e:

        st.error(
            str(e)
        )

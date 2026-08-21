import streamlit as st
import pandas as pd
import yfinance as yf


# ============================================================
# 기본 설정
# ============================================================

st.set_page_config(
    page_title="원화 기준 밴드 리밸런싱",
    page_icon="📊",
    layout="wide"
)


# ============================================================
# 세션 상태
# ============================================================

if "assets" not in st.session_state:

    st.session_state.assets = [
        {
            "name": "S&P500",
            "market": "미국",
            "ticker": "VOO",

            "target": 50.0,
            "lower": 45.0,
            "upper": 55.0,

            "shares": 0.0,
            "price": 0.0,
            "price_currency": "USD",

            "price_ticker": ""
        },

        {
            "name": "KODEX 200",
            "market": "국내",
            "ticker": "069500",

            "target": 20.0,
            "lower": 15.0,
            "upper": 25.0,

            "shares": 0.0,
            "price": 0.0,
            "price_currency": "KRW",

            "price_ticker": ""
        }
    ]


# ============================================================
# 자산 추가
# ============================================================

def add_asset():

    number = len(st.session_state.assets) + 1

    st.session_state.assets.append(
        {
            "name": f"자산 {number}",
            "market": "미국",
            "ticker": "",

            "target": 0.0,
            "lower": 0.0,
            "upper": 0.0,

            "shares": 0.0,
            "price": 0.0,
            "price_currency": "USD",

            "price_ticker": ""
        }
    )


# ============================================================
# 자산 삭제
# ============================================================

def delete_asset(index):

    if len(st.session_state.assets) > 1:

        st.session_state.assets.pop(index)


# ============================================================
# 목표 비중 callback
# ============================================================

def target_slider_changed(i):

    value = st.session_state[
        f"target_slider_{i}"
    ]

    st.session_state[
        f"target_number_{i}"
    ] = value


def target_number_changed(i):

    value = st.session_state[
        f"target_number_{i}"
    ]

    st.session_state[
        f"target_slider_{i}"
    ] = value


# ============================================================
# 하단 callback
# ============================================================

def lower_slider_changed(i):

    value = st.session_state[
        f"lower_slider_{i}"
    ]

    st.session_state[
        f"lower_number_{i}"
    ] = value


def lower_number_changed(i):

    value = st.session_state[
        f"lower_number_{i}"
    ]

    st.session_state[
        f"lower_slider_{i}"
    ] = value


# ============================================================
# 상단 callback
# ============================================================

def upper_slider_changed(i):

    value = st.session_state[
        f"upper_slider_{i}"
    ]

    st.session_state[
        f"upper_number_{i}"
    ] = value


def upper_number_changed(i):

    value = st.session_state[
        f"upper_number_{i}"
    ]

    st.session_state[
        f"upper_slider_{i}"
    ] = value


# ============================================================
# 국내/미국 티커 변환
# ============================================================

def make_yahoo_ticker(
    ticker,
    market
):

    ticker = ticker.strip().upper()

    if market == "미국":

        return ticker

    elif market == "국내":

        # 이미 suffix가 있다면 그대로 사용
        if ticker.endswith(".KS"):
            return ticker

        if ticker.endswith(".KQ"):
            return ticker

        # 국내 ETF는 기본적으로 KOSPI(.KS)
        return ticker + ".KS"

    return ticker


# ============================================================
# 현재가 조회
# ============================================================

@st.cache_data(ttl=300)
def get_price(
    ticker,
    market
):

    yahoo_ticker = make_yahoo_ticker(
        ticker,
        market
    )

    try:

        stock = yf.Ticker(
            yahoo_ticker
        )

        price = None

        # ----------------------------------------------------
        # fast_info
        # ----------------------------------------------------

        try:

            price = stock.fast_info.last_price

        except Exception:

            price = None


        # ----------------------------------------------------
        # history fallback
        # ----------------------------------------------------

        if price is None:

            history = stock.history(
                period="5d"
            )

            if history.empty:

                return None, None, (
                    f"{yahoo_ticker}의 "
                    "가격 데이터를 찾을 수 없습니다."
                )

            close = (
                history["Close"]
                .dropna()
            )

            if close.empty:

                return None, None, (
                    "가격 데이터를 찾을 수 없습니다."
                )

            price = close.iloc[-1]


        # ----------------------------------------------------
        # 통화
        # ----------------------------------------------------

        if market == "미국":

            currency = "USD"

        else:

            currency = "KRW"


        return (
            float(price),
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

@st.cache_data(ttl=300)
def get_usdkrw():

    try:

        fx = yf.Ticker(
            "KRW=X"
        )

        price = None


        # fast_info
        try:

            price = fx.fast_info.last_price

        except Exception:

            price = None


        # history fallback
        if price is None:

            history = fx.history(
                period="5d"
            )

            if history.empty:

                return None, (
                    "USD/KRW 환율 데이터를 "
                    "찾을 수 없습니다."
                )

            close = (
                history["Close"]
                .dropna()
            )

            if close.empty:

                return None, (
                    "USD/KRW 환율 데이터를 "
                    "찾을 수 없습니다."
                )

            price = close.iloc[-1]


        return float(price), None


    except Exception as e:

        return None, f"환율 조회 실패: {e}"


# ============================================================
# 리밸런싱 계산
# ============================================================

def calculate_rebalancing(
    cash,
    assets
):

    # ========================================================
    # 1. 각 자산 원화 평가액
    # ========================================================

    for asset in assets:

        if asset["market"] == "미국":

            asset["amount_krw"] = (
                asset["shares"]
                * asset["price"]
                * asset["exchange_rate"]
            )

        else:

            asset["amount_krw"] = (
                asset["shares"]
                * asset["price"]
            )


    # ========================================================
    # 2. 총자산
    # ========================================================

    total_assets = (
        cash
        + sum(
            asset["amount_krw"]
            for asset in assets
        )
    )


    if total_assets <= 0:

        raise ValueError(
            "총자산이 0원입니다."
        )


    # ========================================================
    # 3. 목표 비중 확인
    # ========================================================

    target_sum = sum(
        asset["target"]
        for asset in assets
    )


    if target_sum > 100.000001:

        raise ValueError(
            f"목표 비중 합계가 "
            f"{target_sum:.2f}%입니다."
        )


    # ========================================================
    # 4. 현재 비중
    # ========================================================

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


    # ========================================================
    # 5. 상단 초과 자산 매도
    # ========================================================

    for asset in assets:

        if (
            asset["current_weight"]
            > asset["upper"]
        ):

            target_amount = (
                asset["target"]
                / 100
                * total_assets
            )

            sell_amount = (
                asset["amount_krw"]
                - target_amount
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


    # ========================================================
    # 6. 매도 + 기존 현금
    # ========================================================

    total_sell = sum(
        asset["sell_amount"]
        for asset in assets
    )

    available_cash = (
        cash
        + total_sell
    )


    # ========================================================
    # 7. 하단 미달 자산
    # ========================================================

    underweight_assets = []


    for asset in assets:

        if (
            asset["current_weight"]
            < asset["lower"]
        ):

            buy_weight_diff = (
                asset["target"]
                - asset["current_weight"]
            )

            needed_amount = (
                buy_weight_diff
                / 100
                * total_assets
            )

            asset["buy_weight_diff"] = (
                buy_weight_diff
            )

            asset["needed_amount"] = (
                needed_amount
            )

            asset["status"] = (
                "하단 미달 → 목표까지 매수"
            )

            underweight_assets.append(
                asset
            )

        else:

            asset["buy_weight_diff"] = 0.0

            asset["needed_amount"] = 0.0


    # ========================================================
    # 8. 필요한 매수금액
    # ========================================================

    total_needed = sum(
        asset["needed_amount"]
        for asset in underweight_assets
    )


    # ========================================================
    # 9. 현금 부족
    # ========================================================

    if (
        total_needed > 0
        and available_cash <= total_needed
    ):

        total_gap = sum(
            asset["buy_weight_diff"]
            for asset
            in underweight_assets
        )


        if total_gap > 0:

            for asset in underweight_assets:

                buy_amount = (
                    available_cash
                    * asset["buy_weight_diff"]
                    / total_gap
                )

                asset["buy_amount"] = (
                    buy_amount
                )

                asset["final_amount"] = (
                    asset["amount_krw"]
                    + buy_amount
                )


    # ========================================================
    # 10. 현금 충분
    # ========================================================

    elif (
        total_needed > 0
        and available_cash > total_needed
    ):

        for asset in underweight_assets:

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
    # 11. 최종 비중
    # ========================================================

    for asset in assets:

        asset["final_weight"] = (
            asset["final_amount"]
            / total_assets
            * 100
        )


    # ========================================================
    # 12. 총 매수
    # ========================================================

    total_buy = sum(
        asset["buy_amount"]
        for asset in assets
    )


    # ========================================================
    # 13. 최종 현금
    # ========================================================

    final_stock_total = sum(
        asset["final_amount"]
        for asset in assets
    )

    final_cash = (
        total_assets
        - final_stock_total
    )


    if abs(final_cash) < 0.01:

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
            assets
    }


# ============================================================
# UI
# ============================================================

st.title(
    "📊 원화 기준 밴드 리밸런싱 계산기"
)

st.caption(
    "국내 ETF와 미국 ETF를 모두 원화 기준으로 환산하여 "
    "포트폴리오 비중을 계산합니다."
)


# ============================================================
# 환율
# ============================================================

st.header(
    "💱 USD/KRW 환율"
)


fx_col1, fx_col2 = st.columns(
    [3, 1]
)


with fx_col1:

    usdkrw = st.number_input(
        "USD/KRW",
        min_value=0.0,
        value=1400.0,
        step=1.0,
        format="%.2f"
    )


with fx_col2:

    if st.button(
        "환율 자동 조회"
    ):

        rate, error = get_usdkrw()

        if error:

            st.error(error)

        else:

            st.session_state[
                "usdkrw"
            ] = rate

            st.rerun()


# 세션 상태에 환율이 있으면 사용
if "usdkrw" in st.session_state:

    usdkrw = st.session_state[
        "usdkrw"
    ]

    st.info(
        f"자동 조회 환율: "
        f"1 USD = {usdkrw:,.2f} KRW"
    )


# ============================================================
# ① 자산 구성
# ============================================================

st.header(
    "① 자산 구성"
)


for i, asset in enumerate(
    st.session_state.assets
):

    col1, col2, col3, col4 = st.columns(
        [3, 2, 2, 1]
    )


    with col1:

        asset["name"] = st.text_input(
            "자산명",
            value=asset["name"],
            key=f"name_{i}"
        )


    with col2:

        asset["market"] = st.selectbox(
            "시장",
            ["미국", "국내"],
            index=(
                0
                if asset["market"] == "미국"
                else 1
            ),
            key=f"market_{i}"
        )


    with col3:

        asset["ticker"] = st.text_input(
            "티커",
            value=asset["ticker"],
            key=f"ticker_{i}",
            placeholder=(
                "예: VOO / 069500"
            )
        )


    with col4:

        if len(
            st.session_state.assets
        ) > 1:

            st.write("")

            if st.button(
                "삭제",
                key=f"delete_{i}"
            ):

                delete_asset(i)

                st.rerun()


if st.button(
    "＋ 자산 추가",
    use_container_width=True
):

    add_asset()

    st.rerun()


# ============================================================
# ② 목표 비중
# ============================================================

st.header(
    "② 목표 비중 및 밴드"
)


for i, asset in enumerate(
    st.session_state.assets
):

    # --------------------------------------------------------
    # 초기화
    # --------------------------------------------------------

    if f"target_slider_{i}" not in st.session_state:

        st.session_state[
            f"target_slider_{i}"
        ] = asset["target"]


    if f"target_number_{i}" not in st.session_state:

        st.session_state[
            f"target_number_{i}"
        ] = asset["target"]


    if f"lower_slider_{i}" not in st.session_state:

        st.session_state[
            f"lower_slider_{i}"
        ] = asset["lower"]


    if f"lower_number_{i}" not in st.session_state:

        st.session_state[
            f"lower_number_{i}"
        ] = asset["lower"]


    if f"upper_slider_{i}" not in st.session_state:

        st.session_state[
            f"upper_slider_{i}"
        ] = asset["upper"]


    if f"upper_number_{i}" not in st.session_state:

        st.session_state[
            f"upper_number_{i}"
        ] = asset["upper"]


    st.subheader(
        asset["name"]
    )


    # ========================================================
    # 목표
    # ========================================================

    st.markdown(
        "**목표 비중**"
    )


    col1, col2 = st.columns(
        [5, 1]
    )


    with col1:

        st.slider(
            "목표 비중 슬라이더",
            0.0,
            100.0,
            step=0.5,
            key=f"target_slider_{i}",
            format="%.1f%%",
            label_visibility="collapsed",
            on_change=target_slider_changed,
            args=(i,)
        )


    with col2:

        st.number_input(
            "목표 비중",
            min_value=0.0,
            max_value=100.0,
            step=0.5,
            key=f"target_number_{i}",
            format="%.1f",
            on_change=target_number_changed,
            args=(i,)
        )


    target = st.session_state[
        f"target_number_{i}"
    ]

    asset["target"] = target


    # ========================================================
    # 하단 / 상단
    # ========================================================

    col1, col2 = st.columns(2)


    # --------------------------------------------------------
    # 하단
    # --------------------------------------------------------

    with col1:

        st.markdown(
            "**하단 비중**"
        )


        if (
            st.session_state[
                f"lower_number_{i}"
            ]
            > target
        ):

            st.session_state[
                f"lower_number_{i}"
            ] = target

            st.session_state[
                f"lower_slider_{i}"
            ] = target


        st.slider(
            "하단 비중 슬라이더",
            0.0,
            float(target),
            step=0.5,
            key=f"lower_slider_{i}",
            format="%.1f%%",
            label_visibility="collapsed",
            on_change=lower_slider_changed,
            args=(i,)
        )


        st.number_input(
            "하단 비중",
            min_value=0.0,
            max_value=float(target),
            step=0.5,
            key=f"lower_number_{i}",
            format="%.1f",
            on_change=lower_number_changed,
            args=(i,)
        )


    # --------------------------------------------------------
    # 상단
    # --------------------------------------------------------

    with col2:

        st.markdown(
            "**상단 비중**"
        )


        if (
            st.session_state[
                f"upper_number_{i}"
            ]
            < target
        ):

            st.session_state[
                f"upper_number_{i}"
            ] = target

            st.session_state[
                f"upper_slider_{i}"
            ] = target


        st.slider(
            "상단 비중 슬라이더",
            float(target),
            100.0,
            step=0.5,
            key=f"upper_slider_{i}",
            format="%.1f%%",
            label_visibility="collapsed",
            on_change=upper_slider_changed,
            args=(i,)
        )


        st.number_input(
            "상단 비중",
            min_value=float(target),
            max_value=100.0,
            step=0.5,
            key=f"upper_number_{i}",
            format="%.1f",
            on_change=upper_number_changed,
            args=(i,)
        )


    asset["lower"] = st.session_state[
        f"lower_number_{i}"
    ]

    asset["upper"] = st.session_state[
        f"upper_number_{i}"
    ]


    st.caption(
        f"밴드: "
        f"{asset['lower']:.1f}%"
        f" ~ "
        f"{asset['upper']:.1f}%"
    )


    st.divider()


# ============================================================
# 목표 비중 합계
# ============================================================

target_sum = sum(
    asset["target"]
    for asset in st.session_state.assets
)


if target_sum > 100:

    st.error(
        f"목표 비중 합계 "
        f"{target_sum:.1f}% → 100% 초과"
    )

else:

    st.info(
        f"목표 비중 합계: "
        f"{target_sum:.1f}%"
    )


# ============================================================
# ③ 현재 보유량
# ============================================================

st.header(
    "③ 현재 보유량"
)


cash = st.number_input(
    "현재 보유 현금 (KRW)",
    min_value=0.0,
    value=0.0,
    step=10000.0,
    format="%.0f"
)


for i, asset in enumerate(
    st.session_state.assets
):

    st.subheader(
        asset["name"]
    )


    col1, col2, col3 = st.columns(
        [2, 2, 2]
    )


    # --------------------------------------------------------
    # 주식 수
    # --------------------------------------------------------

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


    # --------------------------------------------------------
    # 현재가 조회
    # --------------------------------------------------------

    with col2:

        if st.button(
            "현재가 자동 조회",
            key=f"price_button_{i}"
        ):

            price, currency, error = get_price(
                asset["ticker"],
                asset["market"]
            )


            if error:

                st.error(error)

            else:

                asset["price"] = price

                asset["price_currency"] = currency

                asset["price_ticker"] = (
                    make_yahoo_ticker(
                        asset["ticker"],
                        asset["market"]
                    )
                )

                st.success(
                    f"{price:,.2f} {currency}"
                )


        st.number_input(
            "현재가",
            min_value=0.0,
            value=float(
                asset["price"]
            ),
            step=0.01,
            key=f"price_{i}",
            format="%.2f"
        )


        asset["price"] = st.session_state[
            f"price_{i}"
        ]


    # --------------------------------------------------------
    # 원화 평가액
    # --------------------------------------------------------

    with col3:

        if asset["market"] == "미국":

            amount_krw = (
                asset["shares"]
                * asset["price"]
                * usdkrw
            )

            st.metric(
                "원화 평가액",
                f"{amount_krw:,.0f}원"
            )

            if asset["price"] > 0:

                st.caption(
                    f"${asset['price']:,.2f}"
                    f" × "
                    f"{usdkrw:,.2f}"
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


# ============================================================
# ④ 리밸런싱
# ============================================================

st.header(
    "④ 리밸런싱"
)


if st.button(
    "📊 원화 기준 리밸런싱 계산",
    type="primary",
    use_container_width=True
):

    try:

        # ----------------------------------------------------
        # 입력 검사
        # ----------------------------------------------------

        names = [
            asset["name"].strip()
            for asset
            in st.session_state.assets
        ]


        if any(
            name == ""
            for name in names
        ):

            raise ValueError(
                "모든 자산의 이름을 입력해주세요."
            )


        if len(names) != len(set(names)):

            raise ValueError(
                "같은 자산명이 중복되어 있습니다."
            )


        for asset in st.session_state.assets:

            if not asset["ticker"].strip():

                raise ValueError(
                    f"{asset['name']}의 "
                    "티커를 입력해주세요."
                )


            if (
                asset["shares"] > 0
                and asset["price"] <= 0
            ):

                raise ValueError(
                    f"{asset['name']}의 "
                    "현재가를 조회해주세요."
                )


        # ----------------------------------------------------
        # 환율 저장
        # ----------------------------------------------------

        for asset in st.session_state.assets:

            if asset["market"] == "미국":

                asset["exchange_rate"] = (
                    usdkrw
                )

            else:

                asset["exchange_rate"] = 1.0


        # ----------------------------------------------------
        # 계산
        # ----------------------------------------------------

        result = calculate_rebalancing(
            cash,
            st.session_state.assets
        )


        # ====================================================
        # 결과
        # ====================================================

        st.success(
            "원화 기준 리밸런싱 계산 완료"
        )


        # ----------------------------------------------------
        # 총자산
        # ----------------------------------------------------

        col1, col2, col3, col4 = st.columns(4)


        with col1:

            st.metric(
                "총 자산",
                f"{result['total_assets']:,.0f}원"
            )


        with col2:

            st.metric(
                "총 매도",
                f"{result['total_sell']:,.0f}원"
            )


        with col3:

            st.metric(
                "총 매수",
                f"{result['total_buy']:,.0f}원"
            )


        with col4:

            st.metric(
                "분배 후 현금",
                f"{result['final_cash']:,.0f}원"
            )


        # ====================================================
        # 거래 결과
        # ====================================================

        st.subheader(
            "실행할 거래"
        )


        trades = []


        for asset in result["assets"]:

            if asset["sell_amount"] > 0.5:

                trades.append({

                    "자산":
                        asset["name"],

                    "시장":
                        asset["market"],

                    "거래":
                        "🔴 매도",

                    "금액":
                        f"{asset['sell_amount']:,.0f}원"

                })


            if asset["buy_amount"] > 0.5:

                trades.append({

                    "자산":
                        asset["name"],

                    "시장":
                        asset["market"],

                    "거래":
                        "🟢 매수",

                    "금액":
                        f"{asset['buy_amount']:,.0f}원"

                })


        if trades:

            st.dataframe(
                pd.DataFrame(trades),
                use_container_width=True,
                hide_index=True
            )

        else:

            st.info(
                "현재 밴드를 벗어난 자산이 없습니다."
            )


        # ====================================================
        # 전체 포트폴리오
        # ====================================================

        st.subheader(
            "전체 포트폴리오"
        )


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

                "분배 후":
                    f"{asset['final_amount']:,.0f}원",

                "분배 후 비중":
                    f"{asset['final_weight']:.2f}%",

                "판정":
                    asset["status"]

            })


        st.dataframe(
            pd.DataFrame(rows),
            use_container_width=True,
            hide_index=True
        )


        st.caption(
            "미국 자산은 USD 가격 × USD/KRW 환율로 "
            "원화 환산한 뒤 리밸런싱을 계산합니다. "
            "국내 자산은 국내 거래가격을 그대로 원화 평가액으로 사용합니다."
        )


    except ValueError as e:

        st.error(
            str(e)
        )

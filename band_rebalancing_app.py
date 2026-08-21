import streamlit as st
import pandas as pd


# ============================================================
# 페이지 설정
# ============================================================

st.set_page_config(
    page_title="밴드 리밸런싱 계산기",
    page_icon="📊",
    layout="wide"
)


# ============================================================
# 초기 세션 상태
# ============================================================

if "assets" not in st.session_state:
    st.session_state.assets = [
        {
            "name": "S&P500",
            "target": 50.0,
            "lower": 45.0,
            "upper": 55.0,
            "shares": 0.0,
            "price": 0.0
        },
        {
            "name": "VXUS",
            "target": 20.0,
            "lower": 15.0,
            "upper": 25.0,
            "shares": 0.0,
            "price": 0.0
        }
    ]


# ============================================================
# 자산 추가
# ============================================================

def add_asset():

    st.session_state.assets.append(
        {
            "name": f"자산 {len(st.session_state.assets) + 1}",
            "target": 0.0,
            "lower": 0.0,
            "upper": 0.0,
            "shares": 0.0,
            "price": 0.0
        }
    )


# ============================================================
# 자산 삭제
# ============================================================

def delete_asset(index):

    if len(st.session_state.assets) > 1:

        st.session_state.assets.pop(index)


# ============================================================
# 리밸런싱 계산
# ============================================================

def calculate_rebalancing(
    cash,
    assets
):

    # --------------------------------------------------------
    # 1. 보유 자산 금액
    # --------------------------------------------------------

    for asset in assets:

        asset["amount"] = (
            asset["shares"]
            * asset["price"]
        )


    # --------------------------------------------------------
    # 2. 총 자산
    # --------------------------------------------------------

    total_assets = (
        cash
        + sum(
            asset["amount"]
            for asset in assets
        )
    )


    if total_assets <= 0:

        raise ValueError(
            "총 자산은 0보다 커야 합니다."
        )


    # --------------------------------------------------------
    # 3. 목표 비중 합계 확인
    # --------------------------------------------------------

    target_sum = sum(
        asset["target"]
        for asset in assets
    )


    if target_sum > 100.000001:

        raise ValueError(
            f"목표 비중 합계가 "
            f"{target_sum:.2f}%입니다. "
            "100%를 초과할 수 없습니다."
        )


    # --------------------------------------------------------
    # 4. 현재 비중
    # --------------------------------------------------------

    for asset in assets:

        asset["current_weight"] = (
            asset["amount"]
            / total_assets
            * 100
        )

        asset["sell_amount"] = 0.0
        asset["buy_amount"] = 0.0

        asset["final_amount"] = (
            asset["amount"]
        )

        asset["status"] = "유지"


    # ========================================================
    # 5. 상단 초과 → 목표비중까지 매도
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
                asset["amount"]
                - target_amount
            )

            asset["sell_amount"] = (
                sell_amount
            )

            asset["final_amount"] = (
                target_amount
            )

            asset["status"] = (
                "상단 초과 → 매도"
            )


    # --------------------------------------------------------
    # 6. 매도 후 사용할 수 있는 현금
    # --------------------------------------------------------

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

            # 목표비중까지 필요한 비중

            buy_weight_diff = (
                asset["target"]
                - asset["current_weight"]
            )

            # 목표비중까지 필요한 실제 금액

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
                "하단 미달 → 매수"
            )

            underweight_assets.append(
                asset
            )

        else:

            asset["buy_weight_diff"] = 0.0
            asset["needed_amount"] = 0.0


    # --------------------------------------------------------
    # 8. 필요한 총 매수금액
    # --------------------------------------------------------

    total_needed = sum(
        asset["needed_amount"]
        for asset in underweight_assets
    )


    # ========================================================
    # CASE 1
    # 현금 부족
    #
    # 목표비중까지 전부 채울 수 없으므로
    # 부족한 비중에 비례하여 현금 배분
    # ========================================================

    if (
        total_needed > 0
        and available_cash <= total_needed
    ):

        total_gap = sum(
            asset["buy_weight_diff"]
            for asset in underweight_assets
        )


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
                asset["amount"]
                + buy_amount
            )


    # ========================================================
    # CASE 2
    # 현금 충분
    #
    # 목표비중까지 매수
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
                asset["amount"]
                + buy_amount
            )


    # --------------------------------------------------------
    # 9. 최종 비중
    # --------------------------------------------------------

    for asset in assets:

        asset["final_weight"] = (

            asset["final_amount"]

            / total_assets

            * 100
        )


    # --------------------------------------------------------
    # 10. 총 매수
    # --------------------------------------------------------

    total_buy = sum(
        asset["buy_amount"]
        for asset in assets
    )


    # --------------------------------------------------------
    # 11. 남은 현금
    # --------------------------------------------------------

    final_stock_total = sum(
        asset["final_amount"]
        for asset in assets
    )


    final_cash = (
        total_assets
        - final_stock_total
    )


    if abs(final_cash) < 0.01:

        final_cash = 0


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
# 화면
# ============================================================

st.title("📊 밴드 리밸런싱 계산기")

st.write(
    "목표 비중과 밴드를 설정한 뒤 "
    "현재 보유량을 입력하면 리밸런싱 금액을 계산합니다."
)


# ============================================================
# STEP 1
# 자산 구성
# ============================================================

st.header("① 자산 구성")

st.caption(
    "리밸런싱할 자산의 이름을 입력하세요."
)


for i, asset in enumerate(
    st.session_state.assets
):

    col1, col2 = st.columns(
        [5, 1]
    )


    with col1:

        asset["name"] = st.text_input(
            f"자산 {i + 1}",
            value=asset["name"],
            key=f"name_{i}"
        )


    with col2:

        if len(
            st.session_state.assets
        ) > 1:

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
# STEP 2
# 목표 비중 / 밴드
# ============================================================

st.header("② 목표 비중 및 밴드")

st.caption(
    "슬라이더 또는 숫자를 직접 입력하여 목표 비중과 밴드를 설정하세요."
)


for i, asset in enumerate(
    st.session_state.assets
):

    st.subheader(asset["name"])

    # ========================================================
    # 목표 비중
    # ========================================================

    st.markdown("**목표 비중**")

    col1, col2 = st.columns([5, 1])

    with col1:

        target_slider = st.slider(

            "목표 비중 슬라이더",

            min_value=0.0,

            max_value=100.0,

            value=float(asset["target"]),

            step=0.5,

            key=f"target_slider_{i}",

            label_visibility="collapsed",

            format="%.1f%%"

        )

    with col2:

        target_number = st.number_input(

            "목표 비중",

            min_value=0.0,

            max_value=100.0,

            value=float(asset["target"]),

            step=0.5,

            key=f"target_number_{i}",

            format="%.1f"

        )

    # --------------------------------------------------------
    # 슬라이더와 숫자 입력 중 변경된 값을 사용
    # --------------------------------------------------------

    if target_slider != asset["target"]:

        asset["target"] = target_slider

        # 숫자 입력도 같은 값으로 맞춤
        st.session_state[
            f"target_number_{i}"
        ] = target_slider

    elif target_number != asset["target"]:

        asset["target"] = target_number

        # 슬라이더도 같은 값으로 맞춤
        st.session_state[
            f"target_slider_{i}"
        ] = target_number


    # ========================================================
    # 하단 / 상단
    # ========================================================

    col1, col2 = st.columns(2)


    # ========================================================
    # 하단 비중
    # ========================================================

    with col1:

        st.markdown("**하단 비중**")

        col_slider, col_number = st.columns(
            [4, 1]
        )

        with col_slider:

            lower_slider = st.slider(

                "하단 비중 슬라이더",

                min_value=0.0,

                max_value=float(
                    asset["target"]
                ),

                value=min(
                    float(asset["lower"]),
                    float(asset["target"])
                ),

                step=0.5,

                key=f"lower_slider_{i}",

                label_visibility="collapsed",

                format="%.1f%%"

            )

        with col_number:

            lower_number = st.number_input(

                "하단 비중",

                min_value=0.0,

                max_value=float(
                    asset["target"]
                ),

                value=min(
                    float(asset["lower"]),
                    float(asset["target"])
                ),

                step=0.5,

                key=f"lower_number_{i}",

                format="%.1f"

            )


        if lower_slider != asset["lower"]:

            asset["lower"] = lower_slider

            st.session_state[
                f"lower_number_{i}"
            ] = lower_slider

        elif lower_number != asset["lower"]:

            asset["lower"] = lower_number

            st.session_state[
                f"lower_slider_{i}"
            ] = lower_number


    # ========================================================
    # 상단 비중
    # ========================================================

    with col2:

        st.markdown("**상단 비중**")

        col_slider, col_number = st.columns(
            [4, 1]
        )

        with col_slider:

            upper_slider = st.slider(

                "상단 비중 슬라이더",

                min_value=float(
                    asset["target"]
                ),

                max_value=100.0,

                value=max(
                    float(asset["upper"]),
                    float(asset["target"])
                ),

                step=0.5,

                key=f"upper_slider_{i}",

                label_visibility="collapsed",

                format="%.1f%%"

            )

        with col_number:

            upper_number = st.number_input(

                "상단 비중",

                min_value=float(
                    asset["target"]
                ),

                max_value=100.0,

                value=max(
                    float(asset["upper"]),
                    float(asset["target"])
                ),

                step=0.5,

                key=f"upper_number_{i}",

                format="%.1f"

            )


        if upper_slider != asset["upper"]:

            asset["upper"] = upper_slider

            st.session_state[
                f"upper_number_{i}"
            ] = upper_slider

        elif upper_number != asset["upper"]:

            asset["upper"] = upper_number

            st.session_state[
                f"upper_slider_{i}"
            ] = upper_number


    # ========================================================
    # 현재 설정 표시
    # ========================================================

    st.caption(

        f"현재 설정: "
        f"**{asset['lower']:.1f}% "
        f"≤ {asset['target']:.1f}% "
        f"≤ {asset['upper']:.1f}%**"

    )

    st.divider()# ============================================================

# 목표비중 합계
# ============================================================

target_sum = sum(
    asset["target"]
    for asset in st.session_state.assets
)


if target_sum > 100:

    st.error(
        f"목표 비중 합계: {target_sum:.1f}% "
        "→ 100%를 초과했습니다."
    )

else:

    st.info(
        f"목표 비중 합계: {target_sum:.1f}% "
        f"│ 목표 비중 외 {100 - target_sum:.1f}%는 현금으로 남을 수 있습니다."
    )


# ============================================================
# STEP 3
# 현재 보유량
# ============================================================

st.header("③ 현재 보유량")

st.caption(
    "현재 보유 현금, 각 자산의 주식 수와 현재가를 입력하세요."
)


cash = st.number_input(

    "현재 보유 현금",

    min_value=0.0,

    value=0.0,

    step=10000.0,

    format="%.0f"

)


st.subheader("보유 주식")


for i, asset in enumerate(
    st.session_state.assets
):

    st.markdown(
        f"**{asset['name']}**"
    )


    col1, col2 = st.columns(2)


    with col1:

        asset["shares"] = st.number_input(

            "주식 수",

            min_value=0.0,

            value=float(
                asset["shares"]
            ),

            step=1.0,

            key=f"shares_{i}"

        )


    with col2:

        asset["price"] = st.number_input(

            "현재가",

            min_value=0.0,

            value=float(
                asset["price"]
            ),

            step=100.0,

            key=f"price_{i}"

        )


# ============================================================
# STEP 4
# 계산
# ============================================================

st.header("④ 리밸런싱")


if st.button(
    "📊 리밸런싱 계산",
    type="primary",
    use_container_width=True
):

    try:

        # 이름 검사

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
                "같은 이름의 자산이 중복되어 있습니다."
            )


        result = calculate_rebalancing(

            cash,

            st.session_state.assets

        )


        # ====================================================
        # 결과
        # ====================================================

        st.success(
            "리밸런싱 계산이 완료되었습니다."
        )


        st.header("⑤ 리밸런싱 결과")


        # ----------------------------------------------------
        # 핵심 숫자
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


        # ----------------------------------------------------
        # 실제 거래
        # ----------------------------------------------------

        st.subheader(
            "실행할 거래"
        )


        trade_rows = []


        for asset in result["assets"]:


            if asset["sell_amount"] > 0.5:

                trade_rows.append({

                    "자산":
                        asset["name"],

                    "거래":
                        "매도",

                    "금액":
                        asset["sell_amount"]

                })


            elif asset["buy_amount"] > 0.5:

                trade_rows.append({

                    "자산":
                        asset["name"],

                    "거래":
                        "매수",

                    "금액":
                        asset["buy_amount"]

                })


        if trade_rows:

            trade_df = pd.DataFrame(
                trade_rows
            )


            trade_df["금액"] = (
                trade_df["금액"]
                .map(
                    lambda x:
                    f"{x:,.0f}원"
                )
            )


            st.dataframe(

                trade_df,

                use_container_width=True,

                hide_index=True

            )

        else:

            st.info(
                "현재 리밸런싱이 필요한 자산이 없습니다."
            )


        # ----------------------------------------------------
        # 전체 결과
        # ----------------------------------------------------

        st.subheader(
            "전체 포트폴리오"
        )


        rows = []


        for asset in result["assets"]:

            rows.append({

                "자산":
                    asset["name"],

                "현재 금액":
                    f"{asset['amount']:,.0f}원",

                "현재 비중":
                    f"{asset['current_weight']:.2f}%",

                "하단":
                    f"{asset['lower']:.2f}%",

                "목표":
                    f"{asset['target']:.2f}%",

                "상단":
                    f"{asset['upper']:.2f}%",

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


        result_df = pd.DataFrame(
            rows
        )


        st.dataframe(

            result_df,

            use_container_width=True,

            hide_index=True

        )


        # ----------------------------------------------------
        # 설명
        # ----------------------------------------------------

        st.caption(
            "상단 초과 자산은 목표비중까지 매도하고, "
            "하단 미달 자산은 목표비중까지 매수합니다. "
            "사용 가능한 현금이 부족하면 부족한 비중에 비례하여 배분하며, "
            "매수 후 남는 금액은 현금으로 유지합니다."
        )


    except ValueError as e:

        st.error(
            str(e)
        )


import streamlit as st
import pandas as pd

st.set_page_config(
    page_title="밴드 리밸런싱 계산기",
    page_icon="📊",
    layout="wide",
)

st.title("📊 밴드 리밸런싱 계산기")
st.caption(
    "현재 비중이 밴드를 벗어난 자산만 목표비중까지 조정합니다. "
    "남는 금액은 현금으로 유지합니다."
)

EXAMPLE = """현금 3000000;
S&P500 100 200000 50 45 55;
VXUS 20 100000 20 15 25;
AVUV 10 100000 10 7.5 12.5;
금ETF 10 100000 10 7.5 12.5;
채권ETF 20 100000 10 7.5 12.5"""


def parse_input(text):
    text = text.replace("\n", ";")
    blocks = [b.strip() for b in text.split(";") if b.strip()]

    cash = None
    assets = []

    for block in blocks:
        parts = block.split()

        if parts[0].lower() in ["현금", "cash"]:
            if len(parts) != 2:
                raise ValueError(f"현금 입력 형식 오류: {block}")
            cash = float(parts[1].replace(",", "").replace("원", ""))
            continue

        if len(parts) < 6:
            raise ValueError(f"자산 입력 형식 오류: {block}")

        try:
            shares = float(parts[-5].replace(",", ""))
            price = float(parts[-4].replace(",", "").replace("원", ""))
            target = float(parts[-3].replace("%", "")) / 100
            lower = float(parts[-2].replace("%", "")) / 100
            upper = float(parts[-1].replace("%", "")) / 100
        except ValueError:
            raise ValueError(f"숫자를 읽을 수 없습니다: {block}")

        name = " ".join(parts[:-5]).strip()

        if not name:
            raise ValueError(f"자산명이 없습니다: {block}")
        if shares < 0 or price < 0:
            raise ValueError(f"{name}: 주식수와 현재가는 음수가 될 수 없습니다.")
        if not (0 <= lower <= target <= upper <= 1):
            raise ValueError(f"{name}: 하단 ≤ 목표 ≤ 상단 순서여야 합니다.")

        assets.append({
            "name": name,
            "shares": shares,
            "price": price,
            "target": target,
            "lower": lower,
            "upper": upper,
        })

    if cash is None:
        raise ValueError("'현금 금액'을 입력해주세요.")
    if cash < 0:
        raise ValueError("현금은 음수가 될 수 없습니다.")
    if not assets:
        raise ValueError("자산을 하나 이상 입력해주세요.")

    return cash, assets


def calculate_rebalancing(cash, assets):
    for asset in assets:
        asset["amount"] = asset["shares"] * asset["price"]

    total_assets = cash + sum(asset["amount"] for asset in assets)

    if total_assets <= 0:
        raise ValueError("총자산은 0보다 커야 합니다.")

    target_sum = sum(asset["target"] for asset in assets)
    if target_sum > 1.000001:
        raise ValueError(
            f"목표비중 합계가 {target_sum * 100:.2f}%입니다. "
            "100%를 초과할 수 없습니다."
        )

    for asset in assets:
        asset["current_weight"] = asset["amount"] / total_assets
        asset["weight_diff"] = asset["target"] - asset["current_weight"]
        asset["sell_amount"] = 0.0
        asset["buy_amount"] = 0.0
        asset["final_amount"] = asset["amount"]
        asset["status"] = "밴드 내"

    # 상단 초과 -> 목표비중까지 매도
    for asset in assets:
        if asset["current_weight"] > asset["upper"]:
            target_amount = asset["target"] * total_assets
            sell_amount = asset["amount"] - target_amount

            asset["sell_amount"] = sell_amount
            asset["final_amount"] = target_amount
            asset["status"] = "상단 초과 → 목표까지 매도"

    total_sell = sum(asset["sell_amount"] for asset in assets)
    available_cash = cash + total_sell

    # 하단 미달 -> 목표비중까지 필요한 금액
    underweight_assets = []
    for asset in assets:
        if asset["current_weight"] < asset["lower"]:
            buy_weight_diff = asset["target"] - asset["current_weight"]
            needed_amount = buy_weight_diff * total_assets

            asset["buy_weight_diff"] = buy_weight_diff
            asset["needed_amount"] = needed_amount
            asset["status"] = "하단 미달 → 목표까지 매수"
            underweight_assets.append(asset)
        else:
            asset["buy_weight_diff"] = 0.0
            asset["needed_amount"] = 0.0

    total_needed = sum(a["needed_amount"] for a in underweight_assets)

    # 현금 부족 -> 부족 비중 비례로 배분
    if total_needed > 0 and available_cash <= total_needed:
        total_gap = sum(a["buy_weight_diff"] for a in underweight_assets)

        for asset in underweight_assets:
            buy_amount = available_cash * asset["buy_weight_diff"] / total_gap
            asset["buy_amount"] = buy_amount
            asset["final_amount"] = asset["amount"] + buy_amount

    # 현금 충분 -> 목표비중까지만 매수
    elif total_needed > 0:
        for asset in underweight_assets:
            buy_amount = asset["needed_amount"]
            asset["buy_amount"] = buy_amount
            asset["final_amount"] = asset["amount"] + buy_amount

    for asset in assets:
        asset["final_weight"] = asset["final_amount"] / total_assets

    total_buy = sum(asset["buy_amount"] for asset in assets)
    final_stock_total = sum(asset["final_amount"] for asset in assets)
    final_cash = total_assets - final_stock_total

    if abs(final_cash) < 1e-8:
        final_cash = 0.0

    return {
        "total_assets": total_assets,
        "initial_cash": cash,
        "total_sell": total_sell,
        "available_cash": available_cash,
        "total_buy": total_buy,
        "final_cash": final_cash,
        "assets": assets,
    }


def result_dataframe(result):
    rows = []

    for a in result["assets"]:
        if a["sell_amount"] > 0.5:
            action = "매도"
            trade_amount = a["sell_amount"]
        elif a["buy_amount"] > 0.5:
            action = "매수"
            trade_amount = a["buy_amount"]
        else:
            action = "유지"
            trade_amount = 0.0

        rows.append({
            "자산": a["name"],
            "주식수": a["shares"],
            "현재가": a["price"],
            "현재금액": a["amount"],
            "현재비중": a["current_weight"],
            "하단": a["lower"],
            "목표": a["target"],
            "상단": a["upper"],
            "판정": a["status"],
            "거래": action,
            "거래금액": trade_amount,
            "분배후금액": a["final_amount"],
            "분배후비중": a["final_weight"],
        })

    return pd.DataFrame(rows)


with st.form("rebalance_form"):
    text = st.text_area(
        "포트폴리오 전체 입력",
        value=EXAMPLE,
        height=260,
        help=(
            "현금 금액; 자산명 주식수 현재가 목표비중 하단비중 상단비중; ... "
            "형식입니다. 줄바꿈과 세미콜론(;) 모두 구분자로 사용할 수 있습니다."
        ),
    )

    submitted = st.form_submit_button(
        "리밸런싱 계산",
        type="primary",
        use_container_width=True,
    )

if submitted:
    try:
        cash, assets = parse_input(text)
        result = calculate_rebalancing(cash, assets)
        df = result_dataframe(result)

        st.success("계산이 완료되었습니다.")

        c1, c2, c3, c4 = st.columns(4)
        c1.metric("총 자산", f"{result['total_assets']:,.0f}원")
        c2.metric("총 매도", f"{result['total_sell']:,.0f}원")
        c3.metric("총 매수", f"{result['total_buy']:,.0f}원")
        c4.metric("분배 후 현금", f"{result['final_cash']:,.0f}원")

        st.subheader("실행할 거래")
        trades = df[df["거래"] != "유지"][["자산", "거래", "거래금액"]].copy()

        if len(trades) == 0:
            st.info("현재 모든 자산이 밴드 안에 있어 매매가 필요하지 않습니다.")
        else:
            st.dataframe(
                trades,
                use_container_width=True,
                hide_index=True,
            )

        st.subheader("전체 결과")
        display_df = df.copy()

        for col in ["현재비중", "하단", "목표", "상단", "분배후비중"]:
            display_df[col] = display_df[col].map(lambda x: f"{x * 100:.2f}%")

        for col in ["현재가", "현재금액", "거래금액", "분배후금액"]:
            display_df[col] = display_df[col].map(lambda x: f"{x:,.0f}")

        st.dataframe(
            display_df,
            use_container_width=True,
            hide_index=True,
        )

        st.caption(
            "원칙: 상단 초과 → 목표비중까지 매도 / 밴드 내 → 유지 / "
            "하단 미달 → 목표비중까지 매수. 매수 후 남은 금액은 현금으로 유지."
        )

    except ValueError as e:
        st.error(str(e))

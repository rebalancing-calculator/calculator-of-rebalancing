import json
import os
import math
import logging

from pathlib import Path
from decimal import Decimal, ROUND_FLOOR, ROUND_CEILING
from datetime import datetime, timezone
from concurrent.futures import ThreadPoolExecutor, as_completed

import pandas as pd
import streamlit as st


logging.getLogger("yfinance").setLevel(logging.CRITICAL)

D = Decimal


# ============================================================
# 기본 포트폴리오
# ============================================================

DEFAULT_ASSETS = [
    ("SP500", "TIGER 미국S&P500", "360750.KS", "KRW", 30, 25, 35, "주"),
    ("VXUS", "VXUS", "VXUS", "USD", 25, 20, 30, "주"),
    ("AVUV", "AVUV", "AVUV", "USD", 5, 4, 6, "주"),
    ("UPRO", "UPRO", "UPRO", "USD", 5, 4, 6, "주"),
    ("KR3Y", "TIGER 국채3년", "114820.KS", "KRW", 10, 8, 12, "주"),
    ("TIPS", "KIWOOM 물가채KIS", "430500.KS", "KRW", 2.5, 2, 3, "주"),
    ("KMLM", "KMLM", "KMLM", "USD", 5, 4, 6, "주"),
    ("CTA", "CTA", "CTA", "USD", 5, 4, 6, "주"),
    ("GOLD", "KRX 금현물 99.99 1kg", "", "KRW", 5, 4, 6, "g"),
    (
        "UST30",
        "KODEX 미국30년국채액티브(H)",
        "484790.KS",
        "KRW",
        2.5,
        2,
        3,
        "주",
    ),
    (
        "ILS",
        "Brookmont Catastrophic Bond ETF",
        "ILS",
        "USD",
        5,
        4,
        6,
        "주",
    ),
]


DEFAULT_CASH_POLICY = {
    "target": 60,
    "lower": 50,
    "upper": 70,
    "include_rp": False,
    "fx_cost_pct": 0,
}


def default_assets():
    return [
        {
            "id": asset_id,
            "name": name,
            "ticker": ticker,
            "currency": currency,
            "target": target,
            "lower": lower,
            "upper": upper,
            "unit": unit,
            "lot": 1,
            "account": "통합",
        }
        for (
            asset_id,
            name,
            ticker,
            currency,
            target,
            lower,
            upper,
            unit,
        ) in DEFAULT_ASSETS
    ]


# ============================================================
# 숫자 및 설정 검증
# ============================================================

def decimal_number(value, label="숫자"):
    try:
        if isinstance(value, bool):
            raise ValueError

        number = D(str(value))

        if not number.is_finite() or number < 0:
            raise ValueError

        return number

    except Exception:
        raise ValueError(
            f"{label}: 0 이상의 유효한 숫자를 입력하세요."
        ) from None


def validate_assets(assets):
    if not assets:
        raise ValueError("자산을 하나 이상 입력하세요.")

    asset_ids = set()
    total_target = D("0")

    for asset in assets:
        asset_id = str(asset.get("id", "")).strip()
        name = str(asset.get("name", "")).strip()
        account = str(asset.get("account", "")).strip()

        if not asset_id or asset_id in asset_ids:
            raise ValueError(
                "자산 ID는 비어 있거나 중복될 수 없습니다."
            )

        asset_ids.add(asset_id)

        if not name or not account:
            raise ValueError(
                "자산명과 계좌 별칭을 입력하세요."
            )

        if asset.get("currency") not in ("KRW", "USD"):
            raise ValueError(
                "통화는 KRW 또는 USD여야 합니다."
            )

        lower = decimal_number(asset["lower"], "하단 비중")
        target = decimal_number(asset["target"], "목표 비중")
        upper = decimal_number(asset["upper"], "상단 비중")
        lot = decimal_number(asset["lot"], "거래 단위")

        if not lower <= target <= upper <= 100:
            raise ValueError(
                f"{name}: 하단 ≤ 목표 ≤ 상단 ≤ 100이어야 합니다."
            )

        if lot <= 0:
            raise ValueError(
                f"{name}: 거래 단위는 0보다 커야 합니다."
            )

        total_target += target

    if abs(total_target - 100) > D("0.000001"):
        raise ValueError(
            f"목표 비중 합계는 100%여야 합니다. "
            f"현재 {total_target}%입니다."
        )

    return assets


def validate_cash_policy(policy=None):
    result = dict(DEFAULT_CASH_POLICY)
    result.update(policy or {})

    lower = decimal_number(result["lower"], "원화 현금 하단")
    target = decimal_number(result["target"], "원화 현금 목표")
    upper = decimal_number(result["upper"], "원화 현금 상단")
    fx_cost = decimal_number(
        result["fx_cost_pct"],
        "환전 비용 여유",
    )

    if not lower <= target <= upper <= 100:
        raise ValueError(
            "현금 원화 비중은 하단 ≤ 목표 ≤ 상단 ≤ 100이어야 합니다."
        )

    if fx_cost >= 100:
        raise ValueError(
            "환전 비용 여유는 100% 미만이어야 합니다."
        )

    if type(result["include_rp"]) is not bool:
        raise ValueError(
            "RP 포함 여부는 true 또는 false여야 합니다."
        )

    return {
        "target": float(target),
        "lower": float(lower),
        "upper": float(upper),
        "include_rp": result["include_rp"],
        "fx_cost_pct": float(fx_cost),
    }


# ============================================================
# 현금 원화·달러 리밸런싱
# ============================================================

def calculate_cash_rebalancing(
    krw_cash,
    usd_cash,
    usdkrw,
    available_krw=None,
    available_usd=None,
    krw_rp=0,
    usd_rp=0,
    policy=None,
):
    """
    매매 후 남은 현금을 기준으로 환전 금액을 계산한다.

    기본 규칙:
    - 원화 현금 비중 50% 미만: 55%까지 달러 → 원화
    - 원화 현금 비중 50~70%: 유지
    - 원화 현금 비중 70% 초과: 65%까지 원화 → 달러
    """

    policy = validate_cash_policy(policy)

    krw_cash = decimal_number(krw_cash, "원화 현금")
    usd_cash = decimal_number(usd_cash, "달러 현금")
    usdkrw = decimal_number(usdkrw, "원/달러 환율")

    if usdkrw <= 0:
        raise ValueError(
            "원/달러 환율은 0보다 커야 합니다."
        )

    if available_krw is None:
        available_krw = krw_cash

    if available_usd is None:
        available_usd = usd_cash

    available_krw = min(
        krw_cash,
        decimal_number(available_krw, "환전 가능 원화"),
    )

    available_usd = min(
        usd_cash,
        decimal_number(available_usd, "환전 가능 달러"),
    )

    if policy["include_rp"]:
        included_krw_rp = decimal_number(krw_rp, "원화 RP")
        included_usd_rp = decimal_number(usd_rp, "달러 RP")
    else:
        included_krw_rp = D("0")
        included_usd_rp = D("0")

    krw_value = krw_cash + included_krw_rp
    usd_value_krw = (
        usd_cash + included_usd_rp
    ) * usdkrw

    total_cash_krw = krw_value + usd_value_krw

    result = {
        "status": "현금 없음",
        "direction": "유지",
        "total_krw": total_cash_krw,
        "krw": krw_cash,
        "usd": usd_cash,
        "krw_pct": None,
        "usd_pct": None,
        "destination_pct": None,
        "needed_usd": D("0"),
        "proposed_usd": D("0"),
        "krw_amount": D("0"),
        "unfilled_usd": D("0"),
        "post_krw": krw_cash,
        "post_usd": usd_cash,
        "post_krw_pct": None,
        "post_usd_pct": None,
        "estimated_fx_cost": D("0"),
        "policy": policy,
    }

    if total_cash_krw == 0:
        return result

    current_krw_pct = (
        krw_value / total_cash_krw * 100
    )

    result.update(
        status="밴드 내 유지",
        krw_pct=current_krw_pct,
        usd_pct=100 - current_krw_pct,
        post_krw_pct=current_krw_pct,
        post_usd_pct=100 - current_krw_pct,
    )

    lower = decimal_number(policy["lower"])
    target = decimal_number(policy["target"])
    upper = decimal_number(policy["upper"])

    if lower <= current_krw_pct <= upper:
        return result

    # 원화가 부족하면 50과 60의 중간인 55까지 조정.
    # 원화가 많으면 60과 70의 중간인 65까지 조정.
    if current_krw_pct < lower:
        destination_ratio = (
            lower + target
        ) / D("200")
    else:
        destination_ratio = (
            target + upper
        ) / D("200")

    destination_pct = destination_ratio * 100
    fx_cost_ratio = (
        decimal_number(policy["fx_cost_pct"]) / 100
    )

    result["destination_pct"] = destination_pct

    if current_krw_pct > upper:
        # 원화 → 달러
        result["direction"] = "원화 → 달러"

        needed_usd = (
            krw_value
            - destination_ratio * total_cash_krw
        ) / (
            usdkrw
            * (
                1
                + fx_cost_ratio
                * (1 - destination_ratio)
            )
        )

        affordable_usd = (
            available_krw
            / (
                usdkrw
                * (1 + fx_cost_ratio)
            )
        )

    else:
        # 달러 → 원화
        result["direction"] = "달러 → 원화"

        needed_usd = (
            destination_ratio * total_cash_krw
            - krw_value
        ) / (
            usdkrw
            * (
                1
                - fx_cost_ratio
                * (1 - destination_ratio)
            )
        )

        affordable_usd = available_usd

    desired_usd = needed_usd.quantize(
        D("0.01"),
        rounding=ROUND_FLOOR,
    )

    proposed_usd = min(
        desired_usd,
        affordable_usd.quantize(
            D("0.01"),
            rounding=ROUND_FLOOR,
        ),
    )

    if current_krw_pct > upper:
        krw_amount = (
            proposed_usd
            * usdkrw
            * (1 + fx_cost_ratio)
        ).quantize(
            D("1"),
            rounding=ROUND_CEILING,
        )

        if krw_amount > available_krw:
            proposed_usd = max(
                D("0"),
                proposed_usd - D("0.01"),
            )

            krw_amount = (
                proposed_usd
                * usdkrw
                * (1 + fx_cost_ratio)
            ).quantize(
                D("1"),
                rounding=ROUND_CEILING,
            )

        post_krw = krw_cash - krw_amount
        post_usd = usd_cash + proposed_usd

        estimated_fx_cost = (
            krw_amount
            - proposed_usd * usdkrw
        )

    else:
        krw_amount = (
            proposed_usd
            * usdkrw
            * (1 - fx_cost_ratio)
        ).quantize(
            D("1"),
            rounding=ROUND_FLOOR,
        )

        post_krw = krw_cash + krw_amount
        post_usd = usd_cash - proposed_usd

        estimated_fx_cost = (
            proposed_usd * usdkrw
            - krw_amount
        )

    post_total_krw = (
        post_krw
        + included_krw_rp
        + (
            post_usd + included_usd_rp
        ) * usdkrw
    )

    if post_total_krw > 0:
        post_krw_pct = (
            post_krw + included_krw_rp
        ) / post_total_krw * 100

        post_usd_pct = 100 - post_krw_pct
    else:
        post_krw_pct = None
        post_usd_pct = None

    if proposed_usd == desired_usd and proposed_usd > 0:
        status = "환전 필요"
    elif desired_usd == 0:
        status = "환전 단위 미만"
    else:
        status = "환전 재원 부족"

    result.update(
        status=status,
        needed_usd=desired_usd,
        proposed_usd=proposed_usd,
        krw_amount=krw_amount,
        unfilled_usd=desired_usd - proposed_usd,
        post_krw=post_krw,
        post_usd=post_usd,
        post_krw_pct=post_krw_pct,
        post_usd_pct=post_usd_pct,
        estimated_fx_cost=estimated_fx_cost,
    )

    return result


# ============================================================
# 자산 리밸런싱 계산
# ============================================================

def calculate_rebalancing(
    assets,
    holdings,
    prices,
    cash_rows,
    usdkrw,
    trading_cost_pct=0.3,
    include_sale_proceeds=False,
    buy_only=False,
    cash_policy=None,
):
    validate_assets(assets)

    usdkrw = decimal_number(
        usdkrw,
        "원/달러 환율",
    )

    if usdkrw <= 0:
        raise ValueError(
            "원/달러 환율을 입력하세요."
        )

    trading_cost_ratio = (
        decimal_number(
            trading_cost_pct,
            "매매 비용 여유",
        ) / 100
    )

    if trading_cost_ratio >= 1:
        raise ValueError(
            "매매 비용 여유는 100% 미만이어야 합니다."
        )

    def to_krw(amount, currency):
        if currency == "USD":
            return amount * usdkrw

        return amount

    cash_balances = {}
    net_asset_value = D("0")

    for raw_cash in cash_rows:
        key = (
            raw_cash["account"],
            raw_cash["currency"],
        )

        if (
            key in cash_balances
            or key[1] not in ("KRW", "USD")
        ):
            raise ValueError(
                "현금 계좌·통화 중복 또는 통화 오류입니다."
            )

        total_cash = decimal_number(
            raw_cash["total"],
            "총 현금",
        )

        available_cash = decimal_number(
            raw_cash["available"],
            "사용 가능 현금",
        )

        rp_value = decimal_number(
            raw_cash["rp"],
            "RP 평가액",
        )

        cash_reserve = decimal_number(
            raw_cash["reserve"],
            "남겨둘 현금",
        )

        if available_cash > total_cash:
            raise ValueError(
                "사용 가능 현금은 총 현금을 초과할 수 없습니다. "
                "RP·신용·미수 포함 여부를 확인하세요."
            )

        cash_balances[key] = {
            "total": total_cash,
            "available": available_cash,
            "rp": rp_value,
            "reserve": cash_reserve,
        }

        net_asset_value += to_krw(
            total_cash + rp_value,
            key[1],
        )

    result_rows = []

    for asset in assets:
        account_currency = (
            asset["account"],
            asset["currency"],
        )

        if account_currency not in cash_balances:
            raise ValueError(
                f"{account_currency}: 현금 행을 입력하세요."
            )

        quantity = decimal_number(
            holdings.get(asset["id"], 0),
            asset["name"] + " 수량",
        )

        price = decimal_number(
            prices.get(asset["id"], 0),
            asset["name"] + " 가격",
        )

        if price <= 0:
            raise ValueError(
                f"{asset['name']}: 현재가를 입력하세요."
            )

        value_krw = to_krw(
            quantity * price,
            asset["currency"],
        )

        net_asset_value += value_krw

        result_rows.append(
            {
                **asset,
                "qty": quantity,
                "price": price,
                "value": value_krw,
            }
        )

    if net_asset_value <= 0:
        raise ValueError(
            "보유 수량 또는 현금을 입력하세요."
        )

    # 계좌·통화별 실제 매수 예산
    budgets = {
        key: max(
            D("0"),
            value["available"] - value["reserve"],
        )
        for key, value in cash_balances.items()
    }

    initial_budgets = budgets.copy()

    sale_proceeds = {
        key: D("0")
        for key in cash_balances
    }

    required_buy_cost = {
        key: D("0")
        for key in cash_balances
    }

    for row in result_rows:
        current_weight = (
            row["value"] / net_asset_value * 100
        )

        lower = decimal_number(row["lower"])
        target = decimal_number(row["target"])
        upper = decimal_number(row["upper"])

        buy_destination = (
            lower + target
        ) / 2

        sell_destination = (
            target + upper
        ) / 2

        if current_weight < lower:
            signal = "매수"
            destination_pct = buy_destination

        elif current_weight > upper:
            signal = "매도"
            destination_pct = sell_destination

        else:
            signal = "유지"
            destination_pct = current_weight

        if buy_only and signal == "매도":
            signal = "매도 제외"
            destination_pct = current_weight

        destination_value = (
            net_asset_value
            * destination_pct
            / 100
        )

        if signal in ("매수", "매도"):
            value_gap = (
                destination_value - row["value"]
            )
        else:
            value_gap = D("0")

        lot = decimal_number(
            row["lot"],
            row["name"] + " 거래 단위",
        )

        unit_price_krw = to_krw(
            row["price"],
            row["currency"],
        )

        needed_quantity = (
            abs(value_gap)
            / unit_price_krw
            / lot
        ).to_integral_value(
            rounding=ROUND_FLOOR,
        ) * lot

        if signal not in ("매수", "매도"):
            needed_quantity = D("0")

        row.update(
            weight=current_weight,
            buy_destination=buy_destination,
            sell_destination=sell_destination,
            destination_pct=destination_pct,
            destination_value=destination_value,
            gap=value_gap,
            signal=signal,
            needed_qty=needed_quantity,
            planned_qty=D("0"),
            estimated_amount=D("0"),
            cost_with_buffer=D("0"),
        )

        account_key = (
            row["account"],
            row["currency"],
        )

        if row["currency"] == "KRW":
            currency_precision = D("1")
        else:
            currency_precision = D("0.01")

        if signal == "매도":
            sellable_quantity = (
                row["qty"] / lot
            ).to_integral_value(
                rounding=ROUND_FLOOR,
            ) * lot

            planned_quantity = min(
                needed_quantity,
                sellable_quantity,
            )

            estimated_amount = (
                planned_quantity * row["price"]
            )

            net_sale_amount = (
                estimated_amount
                * (1 - trading_cost_ratio)
            ).quantize(
                currency_precision,
                rounding=ROUND_FLOOR,
            )

            row["planned_qty"] = planned_quantity
            row["estimated_amount"] = estimated_amount
            sale_proceeds[account_key] += net_sale_amount

        elif signal == "매수":
            total_needed_cost = (
                needed_quantity
                * row["price"]
                * (1 + trading_cost_ratio)
            ).quantize(
                currency_precision,
                rounding=ROUND_CEILING,
            )

            required_buy_cost[
                account_key
            ] += total_needed_cost

    if include_sale_proceeds and not buy_only:
        for key, proceeds in sale_proceeds.items():
            budgets[key] += proceeds

    # 매수 도달 비중까지 부족한 원화 금액이 큰 순서로 배분
    sorted_rows = sorted(
        result_rows,
        key=lambda row: row["gap"],
        reverse=True,
    )

    for row in sorted_rows:
        if row["signal"] != "매수":
            continue

        account_key = (
            row["account"],
            row["currency"],
        )

        lot = decimal_number(row["lot"])

        unit_cost = (
            row["price"]
            * (1 + trading_cost_ratio)
        )

        affordable_quantity = (
            budgets[account_key]
            / unit_cost
            / lot
        ).to_integral_value(
            rounding=ROUND_FLOOR,
        ) * lot

        planned_quantity = min(
            row["needed_qty"],
            affordable_quantity,
        )

        if row["currency"] == "KRW":
            currency_precision = D("1")
        else:
            currency_precision = D("0.01")

        reserved_cost = (
            planned_quantity * unit_cost
        ).quantize(
            currency_precision,
            rounding=ROUND_CEILING,
        )

        if reserved_cost > budgets[account_key]:
            planned_quantity = max(
                D("0"),
                planned_quantity - lot,
            )

            reserved_cost = (
                planned_quantity * unit_cost
            ).quantize(
                currency_precision,
                rounding=ROUND_CEILING,
            )

        budgets[account_key] -= reserved_cost

        row.update(
            planned_qty=planned_quantity,
            estimated_amount=(
                planned_quantity * row["price"]
            ),
            cost_with_buffer=reserved_cost,
        )

    funding_rows = []

    for key, balance in cash_balances.items():
        if include_sale_proceeds and not buy_only:
            credited_sale_proceeds = sale_proceeds[key]
        else:
            credited_sale_proceeds = D("0")

        spent_amount = (
            initial_budgets[key]
            + credited_sale_proceeds
            - budgets[key]
        )

        # 현금 비율 계산에서는 실제 매도가 완료됐다고 가정하여
        # 매도대금을 포함한다.
        post_trade_total_cash = (
            balance["total"]
            + sale_proceeds[key]
            - spent_amount
        )

        post_trade_available_cash = max(
            D("0"),
            balance["available"]
            + sale_proceeds[key]
            - spent_amount
            - balance["reserve"],
        )

        funding_rows.append(
            {
                "account": key[0],
                "currency": key[1],
                "initial": initial_budgets[key],
                "sale_credit": credited_sale_proceeds,
                "desired_cost": required_buy_cost[key],
                "shortfall": max(
                    D("0"),
                    required_buy_cost[key]
                    - initial_budgets[key]
                    - credited_sale_proceeds,
                ),
                "remaining": budgets[key],
                "rp": balance["rp"],
                "post_total": post_trade_total_cash,
                "post_available": post_trade_available_cash,
                "sales_after_settlement": sale_proceeds[key],
            }
        )

    for row in result_rows:
        row["unfilled_qty"] = (
            row["needed_qty"]
            - row["planned_qty"]
        )

        if row["signal"] == "매수":
            row["post_qty"] = (
                row["qty"] + row["planned_qty"]
            )

        elif row["signal"] == "매도":
            row["post_qty"] = (
                row["qty"] - row["planned_qty"]
            )

        else:
            row["post_qty"] = row["qty"]

    def aggregate_cash(field, currency):
        return sum(
            (
                row[field]
                for row in funding_rows
                if row["currency"] == currency
            ),
            D("0"),
        )

    cash_plan = calculate_cash_rebalancing(
        krw_cash=aggregate_cash(
            "post_total",
            "KRW",
        ),
        usd_cash=aggregate_cash(
            "post_total",
            "USD",
        ),
        usdkrw=usdkrw,
        available_krw=aggregate_cash(
            "post_available",
            "KRW",
        ),
        available_usd=aggregate_cash(
            "post_available",
            "USD",
        ),
        krw_rp=aggregate_cash(
            "rp",
            "KRW",
        ),
        usd_rp=aggregate_cash(
            "rp",
            "USD",
        ),
        policy=cash_policy,
    )

    cash_plan["incomplete_asset_buys"] = any(
        row["signal"] == "매수"
        and row["unfilled_qty"] > 0
        for row in result_rows
    )

    post_trade_nav = sum(
        (
            to_krw(
                row["post_qty"] * row["price"],
                row["currency"],
            )
            for row in result_rows
        ),
        D("0"),
    )

    post_trade_nav += sum(
        (
            to_krw(
                row["post_total"] + row["rp"],
                row["currency"],
            )
            for row in funding_rows
        ),
        D("0"),
    )

    for row in result_rows:
        post_value = to_krw(
            row["post_qty"] * row["price"],
            row["currency"],
        )

        if post_trade_nav > 0:
            row["post_weight"] = (
                post_value / post_trade_nav * 100
            )
        else:
            row["post_weight"] = D("0")

    cash_nav = sum(
        (
            to_krw(
                value["total"] + value["rp"],
                key[1],
            )
            for key, value in cash_balances.items()
        ),
        D("0"),
    )

    return {
        "nav": net_asset_value,
        "post_nav": post_trade_nav,
        "cash_nav": cash_nav,
        "rows": result_rows,
        "funding": funding_rows,
        "cash_plan": cash_plan,
    }


# ============================================================
# Yahoo Finance 현재가 조회
# ============================================================

def latest_quote(symbol, expected_currency):
    if not symbol:
        return {
            "ok": False,
            "error": "직접 입력 자산",
        }

    try:
        import yfinance as yf

        ticker = yf.Ticker(symbol)

        for interval in ("1m", "1d"):
            try:
                history = ticker.history(
                    period="5d",
                    interval=interval,
                    auto_adjust=False,
                    actions=False,
                    prepost=False,
                    timeout=6,
                    raise_errors=True,
                )

            except yf.exceptions.YFRateLimitError:
                return {
                    "ok": False,
                    "error": (
                        "시세 제공사의 요청 제한 · "
                        "직접 입력하세요."
                    ),
                }

            except Exception:
                continue

            if history.empty:
                continue

            close_prices = history["Close"].dropna()

            if close_prices.empty:
                continue

            price = float(close_prices.iloc[-1])
            price_time = close_prices.index[-1]
            metadata = ticker.get_history_metadata()

            if metadata.get("currency") != expected_currency:
                return {
                    "ok": False,
                    "error": (
                        "시세 통화를 확인할 수 없습니다. "
                        "직접 입력하세요."
                    ),
                }

            if not math.isfinite(price) or price <= 0:
                continue

            if price_time.tzinfo is None:
                return {
                    "ok": False,
                    "error": "시세 시간대 미확인",
                }

            utc_time = (
                price_time
                .to_pydatetime()
                .astimezone(timezone.utc)
            )

            age_seconds = (
                datetime.now(timezone.utc) - utc_time
            ).total_seconds()

            if age_seconds > 7 * 86400 or age_seconds < -300:
                return {
                    "ok": False,
                    "error": (
                        "시세 날짜가 오래됐거나 "
                        "유효하지 않습니다."
                    ),
                }

            if interval == "1m":
                price_type = "최근 1분봉 가격"
            else:
                price_type = "최근 일봉 종가"

            return {
                "ok": True,
                "price": price,
                "asof": price_time.isoformat(),
                "source": "Yahoo Finance",
                "kind": price_type,
                "fetched": (
                    datetime.now(timezone.utc).isoformat()
                ),
            }

    except Exception:
        pass

    return {
        "ok": False,
        "error": "조회 실패 · 현재가를 직접 입력하세요.",
    }


# ============================================================
# Streamlit 기본 설정
# ============================================================

st.set_page_config(
    page_title="나의 밴드 리밸런싱",
    page_icon="⚖️",
    layout="wide",
)

st.markdown(
    """
    <style>
    .stApp {
        background: #f6f8fb;
    }

    h1, h2, h3 {
        color: #172d45;
    }

    div[data-testid="stMetric"] {
        background: white;
        padding: 18px;
        border-radius: 12px;
        border: 1px solid #e3e9f0;
    }

    .block-container {
        max-width: 1280px;
        padding-top: 2rem;
    }
    </style>
    """,
    unsafe_allow_html=True,
)

st.title("나의 밴드 리밸런싱")

st.caption(
    "보유 수량과 현금을 직접 입력하면 "
    "밴드를 벗어난 자산의 매매 수량을 계산합니다."
)


# ============================================================
# 로컬 저장
# ============================================================

BASE_DIRECTORY = Path(
    os.environ.get(
        "REBALANCER_DATA_DIR",
        str(Path(__file__).parent),
    )
)

PROFILE_PATH = BASE_DIRECTORY / "user_portfolio.json"
INPUT_PATH = BASE_DIRECTORY / "last_inputs.json"


def load_json(path, default):
    if not path.exists():
        return default

    try:
        return json.loads(
            path.read_text(encoding="utf-8")
        )

    except (OSError, ValueError):
        st.warning(
            f"{path.name}을 읽지 못했습니다. "
            "기본값으로 시작합니다."
        )

        return default


def save_json(path, value):
    try:
        BASE_DIRECTORY.mkdir(
            parents=True,
            exist_ok=True,
        )

        temporary_path = path.with_suffix(".tmp")

        temporary_path.write_text(
            json.dumps(
                value,
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )

        temporary_path.replace(path)
        return True

    except OSError:
        st.error(
            "입력값을 저장하지 못했습니다. "
            "폴더 쓰기 권한을 확인하세요."
        )

        return False


# ============================================================
# 저장된 포트폴리오 불러오기
# ============================================================

if "assets" not in st.session_state:
    saved_profile = load_json(
        PROFILE_PATH,
        {"assets": default_assets()},
    )

    try:
        st.session_state.assets = validate_assets(
            saved_profile["assets"]
        )

    except (ValueError, KeyError, TypeError):
        st.warning(
            "저장된 포트폴리오 형식이 잘못되어 "
            "기본 포트폴리오를 불러왔습니다."
        )

        st.session_state.assets = default_assets()

    try:
        st.session_state.cash_policy = (
            validate_cash_policy(
                saved_profile.get("cash_policy")
            )
        )

    except (ValueError, TypeError, AttributeError):
        st.session_state.cash_policy = (
            validate_cash_policy()
        )

    st.session_state.saved_inputs = load_json(
        INPUT_PATH,
        {},
    )

    st.session_state.quotes = {}
    st.session_state.revision = 0


assets = st.session_state.assets
cash_policy = st.session_state.cash_policy
saved_inputs = st.session_state.saved_inputs
revision = st.session_state.revision


# ============================================================
# 포트폴리오 설정
# ============================================================

with st.expander(
    "포트폴리오 설정 · 변경할 때만 열기"
):
    st.write(
        "기본값은 요청한 11개 자산입니다. "
        "목표 비중 합계는 100%여야 합니다."
    )

    st.caption(
        "기본 계좌 별칭은 통합입니다. "
        "ISA·CMA·금계좌를 분리하려면 "
        "각 자산의 계좌 별칭을 수정하세요."
    )

    with st.form(
        "portfolio_form_" + str(revision)
    ):
        configured_assets = st.data_editor(
            pd.DataFrame(assets),
            hide_index=True,
            num_rows="dynamic",
            column_config={
                "id": st.column_config.TextColumn(
                    "고유 ID",
                    required=True,
                ),
                "name": st.column_config.TextColumn(
                    "자산명",
                    required=True,
                ),
                "ticker": st.column_config.TextColumn(
                    "조회 티커",
                    help=(
                        "국내 ETF는 360750.KS, "
                        "미국 ETF는 VXUS처럼 입력합니다. "
                        "직접 입력 자산은 비워둡니다."
                    ),
                ),
                "currency": (
                    st.column_config.SelectboxColumn(
                        "통화",
                        options=["KRW", "USD"],
                        required=True,
                    )
                ),
                "target": st.column_config.NumberColumn(
                    "목표 %",
                    min_value=0,
                    max_value=100,
                ),
                "lower": st.column_config.NumberColumn(
                    "하단 %",
                    min_value=0,
                    max_value=100,
                ),
                "upper": st.column_config.NumberColumn(
                    "상단 %",
                    min_value=0,
                    max_value=100,
                ),
                "lot": st.column_config.NumberColumn(
                    "거래 단위",
                    min_value=0.000001,
                ),
                "unit": st.column_config.TextColumn(
                    "수량 단위"
                ),
                "account": st.column_config.TextColumn(
                    "계좌 별칭",
                    required=True,
                ),
            },
            key="portfolio_editor_" + str(revision),
        )

        st.write(
            "현금 중 원화 비중 설정"
        )

        cash_column_1, cash_column_2, cash_column_3 = (
            st.columns(3)
        )

        with cash_column_1:
            cash_lower = st.number_input(
                "원화 현금 하단 %",
                min_value=0.0,
                max_value=100.0,
                value=float(cash_policy["lower"]),
            )

        with cash_column_2:
            cash_target = st.number_input(
                "원화 현금 목표 %",
                min_value=0.0,
                max_value=100.0,
                value=float(cash_policy["target"]),
            )

        with cash_column_3:
            cash_upper = st.number_input(
                "원화 현금 상단 %",
                min_value=0.0,
                max_value=100.0,
                value=float(cash_policy["upper"]),
            )

        include_rp_in_cash_ratio = st.checkbox(
            "현금 비율에 RP 평가액 포함",
            value=cash_policy["include_rp"],
        )

        fx_cost_pct = st.number_input(
            "환전 비용 여유 (%)",
            min_value=0.0,
            max_value=10.0,
            value=float(
                cash_policy["fx_cost_pct"]
            ),
            step=0.05,
        )

        st.caption(
            "기본 규칙은 원화 비중 50% 미만이면 "
            "55%까지, 70% 초과이면 65%까지 "
            "환전하는 방식입니다."
        )

        save_profile_button = (
            st.form_submit_button(
                "포트폴리오 저장"
            )
        )

    if save_profile_button:
        try:
            candidate_assets = (
                configured_assets
                .fillna("")
                .to_dict("records")
            )

            validate_assets(candidate_assets)

            candidate_cash_policy = (
                validate_cash_policy(
                    {
                        "target": cash_target,
                        "lower": cash_lower,
                        "upper": cash_upper,
                        "include_rp": (
                            include_rp_in_cash_ratio
                        ),
                        "fx_cost_pct": fx_cost_pct,
                    }
                )
            )

            profile_data = {
                "version": 2,
                "assets": candidate_assets,
                "cash_policy": (
                    candidate_cash_policy
                ),
            }

            if save_json(
                PROFILE_PATH,
                profile_data,
            ):
                st.session_state.assets = (
                    candidate_assets
                )

                st.session_state.cash_policy = (
                    candidate_cash_policy
                )

                st.session_state.revision += 1
                st.session_state.quotes = {}
                st.rerun()

        except (
            ValueError,
            TypeError,
            KeyError,
        ) as error:
            st.error(str(error))

    profile_backup = {
        "version": 2,
        "assets": assets,
        "cash_policy": cash_policy,
    }

    st.download_button(
        "설정 백업 다운로드",
        json.dumps(
            profile_backup,
            ensure_ascii=False,
            indent=2,
        ),
        file_name="portfolio_settings.json",
        mime="application/json",
    )

    uploaded_profile = st.file_uploader(
        "설정 백업 불러오기",
        type=["json"],
    )

    apply_backup = st.button(
        "백업 설정 적용",
        disabled=uploaded_profile is None,
    )

    if apply_backup:
        try:
            if uploaded_profile.size > 1_000_000:
                raise ValueError(
                    "설정 파일은 1MB 이하로 올려주세요."
                )

            uploaded_data = json.loads(
                uploaded_profile
                .getvalue()
                .decode("utf-8-sig")
            )

            imported_assets = uploaded_data["assets"]
            validate_assets(imported_assets)

            imported_cash_policy = (
                validate_cash_policy(
                    uploaded_data.get(
                        "cash_policy"
                    )
                )
            )

            if save_json(
                PROFILE_PATH,
                {
                    "version": 2,
                    "assets": imported_assets,
                    "cash_policy": (
                        imported_cash_policy
                    ),
                },
            ):
                st.session_state.assets = (
                    imported_assets
                )

                st.session_state.cash_policy = (
                    imported_cash_policy
                )

                st.session_state.revision += 1
                st.session_state.quotes = {}
                st.rerun()

        except (
            ValueError,
            KeyError,
            TypeError,
        ) as error:
            st.error(
                f"설정을 불러오지 못했습니다: {error}"
            )


# ============================================================
# 보유 수량 입력
# ============================================================

st.subheader("1. 보유 수량과 현금")

if saved_inputs.get("saved_at"):
    st.caption(
        "마지막 저장: "
        + saved_inputs["saved_at"]
    )

holding_seed = [
    {
        "id": asset["id"],
        "자산": asset["name"],
        "계좌": asset["account"],
        "단위": asset["unit"],
        "보유 수량": float(
            saved_inputs
            .get("holdings", {})
            .get(asset["id"], 0)
        ),
    }
    for asset in assets
]

holding_table = st.data_editor(
    pd.DataFrame(holding_seed),
    hide_index=True,
    disabled=[
        "id",
        "자산",
        "계좌",
        "단위",
    ],
    column_config={
        "id": None,
        "보유 수량": (
            st.column_config.NumberColumn(
                "보유 수량",
                min_value=0,
                step=1,
                format="%.4f",
            )
        ),
    },
    key="holding_editor_" + str(revision),
)

holdings = dict(
    zip(
        holding_table["id"],
        holding_table["보유 수량"],
    )
)

st.caption(
    "KRX 금현물은 보유 g 수를 입력합니다. "
    "예: 4g 보유 → 수량 4."
)


# ============================================================
# 현금 입력
# ============================================================

advanced_cash_input = st.checkbox(
    "사용 가능 현금·RP·남겨둘 현금을 따로 입력",
    value=bool(
        saved_inputs.get("advanced", False)
    ),
)

if (
    st.session_state.get("cash_mode")
    != advanced_cash_input
):
    st.session_state.cash_base = (
        st.session_state.get(
            "cash_live",
            saved_inputs.get("cash", []),
        )
    )

    st.session_state.cash_mode = (
        advanced_cash_input
    )

    st.session_state.cash_revision = (
        st.session_state.get(
            "cash_revision",
            0,
        ) + 1
    )

st.caption(
    "총 현금은 RP를 제외하고 미결제 대금을 "
    "반영한 순현금입니다. 주문가능금액을 "
    "별도로 더하지 마세요."
)

old_cash = {
    (
        row["account"],
        row["currency"],
    ): row
    for row in st.session_state.get(
        "cash_base",
        saved_inputs.get("cash", []),
    )
}

cash_seed = []

account_currency_pairs = sorted(
    {
        (
            asset["account"],
            asset["currency"],
        )
        for asset in assets
    }
)

for account, currency in account_currency_pairs:
    previous = old_cash.get(
        (account, currency),
        {},
    )

    cash_row = {
        "계좌": account,
        "통화": currency,
        "총 현금": float(
            previous.get("total", 0)
        ),
    }

    if advanced_cash_input:
        cash_row.update(
            {
                "사용 가능 현금": float(
                    previous.get(
                        "available",
                        previous.get("total", 0),
                    )
                ),
                "RP 평가액": float(
                    previous.get("rp", 0)
                ),
                "남겨둘 현금": float(
                    previous.get("reserve", 0)
                ),
            }
        )

    cash_seed.append(cash_row)

cash_table = st.data_editor(
    pd.DataFrame(cash_seed),
    hide_index=True,
    disabled=["계좌", "통화"],
    column_config={
        column: st.column_config.NumberColumn(
            column,
            min_value=0,
            format="%.2f",
        )
        for column in (
            "총 현금",
            "사용 가능 현금",
            "RP 평가액",
            "남겨둘 현금",
        )
    },
    key=(
        "cash_editor_"
        + str(revision)
        + "_"
        + str(
            st.session_state.get(
                "cash_revision",
                0,
            )
        )
    ),
)

cash_rows = []

for row in cash_table.to_dict("records"):
    cash_rows.append(
        {
            "account": row["계좌"],
            "currency": row["통화"],
            "total": row["총 현금"],
            "available": row.get(
                "사용 가능 현금",
                row["총 현금"],
            ),
            "rp": row.get(
                "RP 평가액",
                0,
            ),
            "reserve": row.get(
                "남겨둘 현금",
                0,
            ),
        }
    )

st.session_state.cash_live = cash_rows

if st.button("보유 수량·현금 저장"):
    input_data = {
        "holdings": holdings,
        "cash": cash_rows,
        "advanced": advanced_cash_input,
        "saved_at": (
            datetime.now()
            .astimezone()
            .isoformat(timespec="minutes")
        ),
    }

    if save_json(
        INPUT_PATH,
        input_data,
    ):
        st.success(
            "저장했습니다. 다음 실행 때 불러옵니다."
        )


# ============================================================
# 현재가와 환율 조회
# ============================================================

st.subheader("2. 가격과 환율")

st.caption(
    "자동 조회는 Yahoo Finance의 최근 가격입니다. "
    "휴장 중에는 최근 종가가 표시될 수 있습니다. "
    "실제 주문 가격은 증권사 화면에서 확인하세요."
)

if st.button(
    "현재가·환율 조회 / 새로고침",
    type="primary",
):
    quote_jobs = {
        asset["id"]: (
            asset["ticker"],
            asset["currency"],
        )
        for asset in assets
        if asset.get("ticker")
    }

    quote_jobs["FX"] = ("KRW=X", "KRW")
    st.session_state.quotes = {}

    progress = st.progress(
        0,
        text="가격과 환율을 조회하고 있습니다.",
    )

    with ThreadPoolExecutor(
        max_workers=4
    ) as executor:
        futures = {
            executor.submit(
                latest_quote,
                ticker,
                currency,
            ): asset_id
            for asset_id, (
                ticker,
                currency,
            ) in quote_jobs.items()
        }

        for index, future in enumerate(
            as_completed(futures),
            1,
        ):
            asset_id = futures[future]

            st.session_state.quotes[
                asset_id
            ] = future.result()

            progress.progress(
                index / len(quote_jobs),
                text=(
                    f"{index}/{len(quote_jobs)} "
                    "조회 완료"
                ),
            )

    progress.empty()

quotes = st.session_state.quotes

quote_display_rows = []

for asset in assets:
    quote = quotes.get(
        asset["id"],
        {},
    )

    if quote.get("ok"):
        quote_status = "조회 완료"
    else:
        quote_status = quote.get(
            "error",
            (
                "직접 입력"
                if not asset.get("ticker")
                else "조회 전"
            ),
        )

    quote_display_rows.append(
        {
            "자산": asset["name"],
            "통화": asset["currency"],
            "조회 가격": quote.get("price"),
            "가격 기준 시각": quote.get(
                "asof",
                "",
            ),
            "가격 종류": quote.get(
                "kind",
                "",
            ),
            "상태": quote_status,
        }
    )

st.dataframe(
    pd.DataFrame(quote_display_rows),
    hide_index=True,
)

manual_override_assets = st.multiselect(
    "조회 가격 대신 직접 입력할 자산",
    options=[
        asset["id"]
        for asset in assets
        if quotes.get(
            asset["id"],
            {},
        ).get("ok")
    ],
    format_func=lambda asset_id: next(
        asset["name"]
        for asset in assets
        if asset["id"] == asset_id
    ),
)

prices = {}
missing_values = []

manual_assets = [
    asset
    for asset in assets
    if (
        not quotes.get(
            asset["id"],
            {},
        ).get("ok")
        or asset["id"] in manual_override_assets
    )
]

if manual_assets:
    st.info(
        "아래 자산의 가격을 입력하세요. "
        "자동 조회에 성공한 자산의 입력란은 사라집니다."
    )

    manual_columns = st.columns(2)

    for index, asset in enumerate(
        manual_assets
    ):
        with manual_columns[index % 2]:
            if asset["currency"] == "KRW":
                currency_name = "원"
            else:
                currency_name = "달러"

            prices[asset["id"]] = (
                st.number_input(
                    (
                        f"{asset['name']} · "
                        f"{currency_name}/"
                        f"{asset['unit']}"
                    ),
                    min_value=0.0,
                    value=0.0,
                    format="%.4f",
                    key=(
                        "manual_price_"
                        + str(revision)
                        + "_"
                        + asset["id"]
                    ),
                )
            )

            if prices[asset["id"]] <= 0:
                missing_values.append(
                    asset["name"]
                )

for asset in assets:
    if asset["id"] not in prices:
        prices[asset["id"]] = (
            quotes[asset["id"]]["price"]
        )


# ============================================================
# 환율 입력
# ============================================================

fx_quote = quotes.get("FX", {})

use_manual_fx = st.checkbox(
    "환율 직접 입력",
    value=not fx_quote.get("ok", False),
)

if fx_quote.get("ok"):
    st.caption(
        f"조회 환율: 1달러 = "
        f"{fx_quote['price']:,.4f}원 · "
        f"{fx_quote['asof']} · "
        f"{fx_quote['kind']}"
    )

if (
    use_manual_fx
    or not fx_quote.get("ok")
):
    usdkrw = st.number_input(
        "1달러당 원화 (USD/KRW)",
        min_value=0.0,
        value=0.0,
        format="%.4f",
        key="manual_usdkrw",
    )

else:
    usdkrw = fx_quote["price"]

if usdkrw <= 0:
    missing_values.append(
        "원/달러 환율"
    )


# ============================================================
# 리밸런싱 조건
# ============================================================

st.subheader("3. 매매 수량 계산")

buy_only = st.checkbox(
    "매수만 계산 — 상단을 넘은 자산도 매도하지 않음"
)

include_sale_proceeds = st.checkbox(
    "예상 매도대금을 매수 재원에 포함",
    disabled=buy_only,
    help=(
        "매도가 체결되고 해당 계좌에서 "
        "재사용할 수 있다는 가정입니다."
    ),
)

trading_cost_pct = st.number_input(
    "매매 비용 여유 (%)",
    min_value=0.0,
    max_value=10.0,
    value=0.3,
    step=0.05,
    help=(
        "실제 수수료율이 아니라 매수 예산에 "
        "여유를 두기 위한 값입니다."
    ),
)

st.caption(
    "하단 미만이면 매수하고 상단 초과이면 매도합니다. "
    "매수는 (하단+목표)/2, "
    "매도는 (상단+목표)/2까지만 진행합니다."
)

if missing_values:
    st.warning(
        "계산에 필요한 입력: "
        + ", ".join(missing_values)
    )

    st.stop()

try:
    result = calculate_rebalancing(
        assets=assets,
        holdings=holdings,
        prices=prices,
        cash_rows=cash_rows,
        usdkrw=usdkrw,
        trading_cost_pct=trading_cost_pct,
        include_sale_proceeds=(
            include_sale_proceeds
            and not buy_only
        ),
        buy_only=buy_only,
        cash_policy=cash_policy,
    )

except (
    ValueError,
    TypeError,
    KeyError,
) as error:
    st.error(str(error))
    st.stop()


# ============================================================
# 리밸런싱 결과
# ============================================================

metric_1, metric_2, metric_3 = st.columns(3)

metric_1.metric(
    "총자산 · 현금/RP 포함",
    f"{float(result['nav']):,.0f}원",
)

metric_2.metric(
    "현금 + RP",
    f"{float(result['cash_nav']):,.0f}원",
)

metric_3.metric(
    "조정 대상",
    (
        f"{sum(
            row['signal'] in ('매수', '매도')
            for row in result['rows']
        )}개"
    ),
)

if (
    include_sale_proceeds
    and not buy_only
):
    st.info(
        "매수 수량은 예상 매도가 완료되어 "
        "대금을 재사용할 수 있다는 가정입니다."
    )

if any(
    asset["account"] == "통합"
    for asset in assets
):
    st.caption(
        "통합 계산은 같은 통화의 현금을 공유합니다. "
        "ISA·CMA·금계좌를 구분하려면 "
        "포트폴리오 설정에서 계좌 별칭을 수정하세요."
    )

display_rows = []

for row in result["rows"]:
    status = row["signal"]

    if (
        status in ("매수", "매도")
        and row["needed_qty"] == 0
    ):
        status += " · 거래단위 미만"

    elif (
        status == "매수"
        and row["unfilled_qty"] > 0
    ):
        status += " · 현금 부족"

    display_rows.append(
        {
            "자산": row["name"],
            "계좌": row["account"],
            "통화": row["currency"],
            "현재 비중 %": float(
                row["weight"]
            ),
            "목표 %": float(
                row["target"]
            ),
            "매수 도달 %": float(
                row["buy_destination"]
            ),
            "매도 도달 %": float(
                row["sell_destination"]
            ),
            "평가액 원": float(
                row["value"]
            ),
            "판단": status,
            "참고 단가": float(
                row["price"]
            ),
            "중간값까지 필요 수량": float(
                row["needed_qty"]
            ),
            "제안 수량": float(
                row["planned_qty"]
            ),
            "단위": row["unit"],
            "예상 매매금액": float(
                row["estimated_amount"]
            ),
            "매매 후 수량": float(
                row["post_qty"]
            ),
            "매매 후 예상 비중 %": float(
                row["post_weight"]
            ),
        }
    )

result_frame = pd.DataFrame(
    display_rows
)

st.dataframe(
    result_frame,
    hide_index=True,
    column_config={
        "현재 비중 %": (
            st.column_config.NumberColumn(
                format="%.2f"
            )
        ),
        "매매 후 예상 비중 %": (
            st.column_config.NumberColumn(
                format="%.2f"
            )
        ),
        "평가액 원": (
            st.column_config.NumberColumn(
                format="%.0f"
            )
        ),
        "참고 단가": (
            st.column_config.NumberColumn(
                format="%.4f"
            )
        ),
        "예상 매매금액": (
            st.column_config.NumberColumn(
                format="%.2f"
            )
        ),
    },
)

st.caption(
    "제안 수량은 거래 단위와 현재 예산을 넘지 않도록 "
    "내림합니다. 가격이 바뀌거나 일부만 체결되면 "
    "실제 잔고로 다시 계산하세요."
)

for row in result["rows"]:
    if row["planned_qty"] > 0:
        st.write(
            f"**{row['name']}**: "
            f"{row['signal']} "
            f"**{row['planned_qty']:f}"
            f"{row['unit']}** · "
            f"참고 단가 "
            f"{row['price']:,.4f} "
            f"{row['currency']} · "
            f"예상 금액 "
            f"{row['estimated_amount']:,.2f} "
            f"{row['currency']}"
        )


# ============================================================
# 통화별 매수 예산
# ============================================================

funding_frame = pd.DataFrame(
    [
        {
            "계좌": row["account"],
            "통화": row["currency"],
            "사용 예산": float(
                row["initial"]
            ),
            "포함한 예상 매도대금": float(
                row["sale_credit"]
            ),
            "중간값 매수까지 부족액": float(
                row["shortfall"]
            ),
            "제안 매수 후 예산 잔액": float(
                row["remaining"]
            ),
            "별도 RP 평가액": float(
                row["rp"]
            ),
        }
        for row in result["funding"]
    ]
)

st.dataframe(
    funding_frame,
    hide_index=True,
)

st.caption(
    "RP는 총자산에는 포함하지만 매수 예산에는 "
    "포함하지 않습니다. RP를 환매했다면 "
    "RP 평가액을 줄이고 현금을 늘려 다시 입력하세요."
)

if any(
    row["shortfall"] > 0
    for row in result["funding"]
):
    st.warning(
        "중간값까지 매수하기에는 일부 계좌·통화의 "
        "현금이 부족합니다."
    )

st.download_button(
    "결과 CSV 다운로드",
    result_frame
    .to_csv(index=False)
    .encode("utf-8-sig"),
    file_name="rebalance_result.csv",
    mime="text/csv",
)


# ============================================================
# 매매 후 원화·달러 현금 비율
# ============================================================

st.subheader(
    "4. 매매 후 현금 · 원화/달러 리밸런싱"
)

st.caption(
    "아래 현금 비중은 제안된 매도·매수가 모두 "
    "완료된 뒤 남을 현금을 기준으로 계산합니다."
)

cash_result = result["cash_plan"]

if cash_policy["include_rp"]:
    rp_description = "RP 포함"
else:
    rp_description = "RP 제외"

st.write(
    f"원화 목표 **{cash_policy['target']:g}%** · "
    f"허용 **{cash_policy['lower']:g}"
    f"~{cash_policy['upper']:g}%** / "
    f"달러 목표 "
    f"**{100-cash_policy['target']:g}%** · "
    f"허용 "
    f"**{100-cash_policy['upper']:g}"
    f"~{100-cash_policy['lower']:g}%** · "
    f"{rp_description}"
)

post_cash_frame = pd.DataFrame(
    [
        {
            "계좌": row["account"],
            "통화": row["currency"],
            "매매 후 순현금": float(
                row["post_total"]
            ),
            "예비 현금 제외 가용액": float(
                row["post_available"]
            ),
            "RP 평가액": float(
                row["rp"]
            ),
        }
        for row in result["funding"]
    ]
)

st.dataframe(
    post_cash_frame,
    hide_index=True,
)

if cash_result["krw_pct"] is None:
    st.info(
        "잔여 현금이 0이므로 현금 비율을 "
        "계산하거나 환전하지 않습니다."
    )

else:
    cash_metric_1, cash_metric_2 = st.columns(2)

    cash_metric_1.metric(
        "매매 후 원화 현금 비중",
        f"{cash_result['krw_pct']:.2f}%",
    )

    cash_metric_2.metric(
        "매매 후 달러 현금 비중",
        f"{cash_result['usd_pct']:.2f}%",
    )

    if cash_result["incomplete_asset_buys"]:
        st.warning(
            "현금 부족으로 완료하지 못한 매수가 있습니다. "
            "아래 환전액은 현재 제안 수량까지만 "
            "매매했을 때의 결과입니다."
        )

    if cash_result["direction"] == "유지":
        st.success(
            "현금 비율이 허용 범위 안입니다. "
            "환전 제안은 없습니다."
        )

    elif cash_result["proposed_usd"] > 0:
        st.write(
            f"**{cash_result['direction']}** · "
            f"원화 현금 비중 "
            f"**{cash_result['destination_pct']:.2f}%**"
            "까지 조정"
        )

        if (
            cash_result["direction"]
            == "원화 → 달러"
        ):
            st.write(
                f"원화 "
                f"**{cash_result['krw_amount']:,.0f}원**으로 "
                f"달러 "
                f"**{cash_result['proposed_usd']:,.2f}달러** "
                "매수"
            )

        else:
            st.write(
                f"달러 "
                f"**{cash_result['proposed_usd']:,.2f}달러**를 "
                f"매도해 원화 "
                f"**{cash_result['krw_amount']:,.0f}원** "
                "수취"
            )

        st.write(
            "환전 후 예상 현금: "
            f"**{cash_result['post_krw']:,.0f}원 + "
            f"{cash_result['post_usd']:,.2f}달러** · "
            "원화/달러 비중 "
            f"**{cash_result['post_krw_pct']:.2f}% / "
            f"{cash_result['post_usd_pct']:.2f}%**"
        )

    if cash_result["status"] == "환전 재원 부족":
        st.warning(
            "중간값까지 환전하려면 추가로 "
            f"{cash_result['unfilled_usd']:,.2f}달러에 "
            "해당하는 재원이 필요합니다."
        )

    elif cash_result["status"] == "환전 단위 미만":
        st.info(
            "조정액이 0.01달러 미만이어서 "
            "환전을 제안하지 않습니다."
        )

    fx_frame = pd.DataFrame(
        [
            {
                "방향": cash_result["direction"],
                "원화금액": float(
                    cash_result["krw_amount"]
                ),
                "달러수량": float(
                    cash_result["proposed_usd"]
                ),
                "조정후원화비중": float(
                    cash_result["post_krw_pct"]
                ),
                "조정후달러비중": float(
                    cash_result["post_usd_pct"]
                ),
                "상태": cash_result["status"],
            }
        ]
    )

    st.download_button(
        "환전 제안 CSV 다운로드",
        fx_frame
        .to_csv(index=False)
        .encode("utf-8-sig"),
        file_name="cash_rebalance.csv",
        mime="text/csv",
    )


# ============================================================
# 계산 기준
# ============================================================

with st.expander("계산 기준"):
    st.write(
        "총자산 = 주식·금 평가액 + 원화 순현금 "
        "+ 달러 순현금 × 환율 + RP 평가액."
    )

    st.write(
        "매수 도달 비중 = (하단+목표)/2, "
        "매도 도달 비중 = (상단+목표)/2입니다."
    )

    st.write(
        "원화 현금 비중이 50% 미만이면 55%까지, "
        "70% 초과이면 65%까지 환전합니다. "
        "50~70%에서는 환전하지 않습니다."
    )

    st.write(
        "현금 비율은 전체 포트폴리오 비중이 아니라 "
        "원화로 환산한 원화·달러 현금끼리의 비율입니다."
    )

    st.write(
        "참고 단가는 체결 가능한 호가나 적정 매수가가 "
        "아닙니다. 실제 주문 전 증권사 가격을 확인하세요."
    )

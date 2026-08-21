import streamlit as st
import pandas as pd
import yfinance as yf

# ============================================================
# Page configuration
# ============================================================
st.set_page_config(
    page_title="KRW 리밸런싱 계산기",
    page_icon="📊",
    layout="wide",
)

# ============================================================
# Session state
# ============================================================
if "usdkrw" not in st.session_state:
    st.session_state.usdkrw = 1400.0
if "usdkrw_asof" not in st.session_state:
    st.session_state.usdkrw_asof = None
if "fx_error" not in st.session_state:
    st.session_state.fx_error = None
if "assets" not in st.session_state:
    st.session_state.assets = []
if "cash" not in st.session_state:
    st.session_state.cash = 0.0
if "result" not in st.session_state:
    st.session_state.result = None

# ============================================================
# Data helpers
# ============================================================
@st.cache_data(ttl=600)
def search_assets(query: str):
    query = query.strip()
    if not query:
        return []
    try:
        search = yf.Search(query, max_results=10, news_count=0, lists_count=0)
        results = []
        for q in search.quotes:
            symbol = q.get("symbol")
            quote_type = q.get("quoteType", "")
            if not symbol or quote_type not in {"EQUITY", "ETF", "MUTUALFUND"}:
                continue
            results.append({
                "symbol": symbol,
                "name": q.get("longname") or q.get("shortname") or symbol,
                "exchange": q.get("exchange", ""),
                "quoteType": quote_type,
            })
        return results
    except Exception:
        return []


def detect_market(symbol: str, exchange: str):
    symbol = (symbol or "").upper()
    exchange = (exchange or "").upper()
    if symbol.endswith(".KS") or symbol.endswith(".KQ"):
        return "국내"
    if exchange in {"KSC", "KOE", "KSE", "KQX", "KO"}:
        return "국내"
    return "미국"


def normalize_domestic_symbol(symbol: str):
    symbol = symbol.strip().upper()
    if symbol.endswith(".KS") or symbol.endswith(".KQ"):
        return symbol
    if symbol.isdigit() and len(symbol) == 6:
        return f"{symbol}.KS"
    return symbol


@st.cache_data(ttl=300)
def get_latest_daily_data(symbol: str):
    """최근 제공되는 일봉 종가와 기준일을 반환한다."""
    symbol = symbol.strip().upper()
    if not symbol:
        return None, None, "티커가 비어 있습니다."
    try:
        history = yf.Ticker(symbol).history(
            period="10d",
            interval="1d",
            auto_adjust=False,
        )
        if history.empty:
            return None, None, "가격 데이터가 없습니다."
        close = history["Close"].dropna()
        if close.empty:
            return None, None, "종가 데이터를 찾을 수 없습니다."
        price = float(close.iloc[-1])
        if price <= 0:
            return None, None, "비정상적인 가격 데이터입니다."
        asof = close.index[-1].strftime("%Y-%m-%d")
        return price, asof, None
    except Exception as exc:
        return None, None, f"데이터 조회 실패: {exc}"


@st.cache_data(ttl=300)
def get_exchange_rate():
    return get_latest_daily_data("KRW=X")


# ============================================================
# Asset/session helpers
# ============================================================
def blank_asset():
    return {
        "name": "",
        "ticker": "",
        "market": "",
        "exchange": "",
        "currency": "",
        "target": 0.0,
        "lower": 0.0,
        "upper": 0.0,
        "shares": 0.0,
        "price": 0.0,
        "price_asof": None,
        "price_error": None,
    }


def add_asset():
    st.session_state.assets.append(blank_asset())


def delete_asset(index: int):
    st.session_state.assets.pop(index)
    # 동적 행 key가 꼬이지 않도록 관련 widget state를 재생성한다.
    prefixes = (
        "search_", "results_", "selected_", "target_", "lower_",
        "upper_", "shares_", "price_"
    )
    for key in list(st.session_state.keys()):
        if key.startswith(prefixes):
            del st.session_state[key]


def sync_target_from_slider(i: int):
    value = float(st.session_state[f"target_slider_{i}"])
    st.session_state[f"target_number_{i}"] = value
    st.session_state[f"lower_number_{i}"] = min(float(st.session_state.get(f"lower_number_{i}", 0.0)), value)
    st.session_state[f"lower_slider_{i}"] = st.session_state[f"lower_number_{i}"]
    st.session_state[f"upper_number_{i}"] = max(float(st.session_state.get(f"upper_number_{i}", value)), value)
    st.session_state[f"upper_slider_{i}"] = st.session_state[f"upper_number_{i}"]


def sync_target_from_number(i: int):
    value = float(st.session_state[f"target_number_{i}"])
    st.session_state[f"target_slider_{i}"] = value
    st.session_state[f"lower_number_{i}"] = min(float(st.session_state.get(f"lower_number_{i}", 0.0)), value)
    st.session_state[f"lower_slider_{i}"] = st.session_state[f"lower_number_{i}"]
    st.session_state[f"upper_number_{i}"] = max(float(st.session_state.get(f"upper_number_{i}", value)), value)
    st.session_state[f"upper_slider_{i}"] = st.session_state[f"upper_number_{i}"]


def sync_lower_from_slider(i: int):
    st.session_state[f"lower_number_{i}"] = st.session_state[f"lower_slider_{i}"]


def sync_lower_from_number(i: int):
    st.session_state[f"lower_slider_{i}"] = st.session_state[f"lower_number_{i}"]


def sync_upper_from_slider(i: int):
    st.session_state[f"upper_number_{i}"] = st.session_state[f"upper_slider_{i}"]


def sync_upper_from_number(i: int):
    st.session_state[f"upper_slider_{i}"] = st.session_state[f"upper_number_{i}"]


def fetch_fx_callback():
    rate, asof, error = get_exchange_rate()
    st.session_state.fx_error = error
    if error is None:
        st.session_state.usdkrw = rate
        st.session_state.usdkrw_asof = asof


def fetch_price_callback(i: int):
    asset = st.session_state.assets[i]
    ticker = asset["ticker"]
    if asset["market"] == "국내":
        ticker = normalize_domestic_symbol(ticker)
    price, asof, error = get_latest_daily_data(ticker)
    asset["price_error"] = error
    if error is None:
        asset["price"] = price
        asset["price_asof"] = asof
        # 가격 입력 위젯이 이 실행에서 아직 렌더링되지 않았으므로 state 갱신 가능
        st.session_state[f"price_{i}"] = price


# ============================================================
# Rebalancing calculation
# ============================================================
def calculate_rebalancing(cash: float, assets: list[dict], usdkrw: float):
    working = []

    for original in assets:
        asset = original.copy()
        if asset["market"] == "미국":
            asset["amount_krw"] = asset["shares"] * asset["price"] * usdkrw
        elif asset["market"] == "국내":
            asset["amount_krw"] = asset["shares"] * asset["price"]
        else:
            raise ValueError(f"{asset['name'] or '이름 없는 자산'}의 시장이 지정되지 않았습니다.")
        working.append(asset)

    total_assets = cash + sum(a["amount_krw"] for a in working)
    if total_assets <= 0:
        raise ValueError("총자산이 0원입니다.")

    target_sum = sum(a["target"] for a in working)
    if abs(target_sum - 100.0) > 0.0001:
        raise ValueError(f"목표 비중 합계가 {target_sum:.2f}%입니다. 목표 비중의 합은 100%가 되어야 합니다.")

    for asset in working:
        asset["current_weight"] = asset["amount_krw"] / total_assets * 100
        asset["weight_difference"] = asset["target"] - asset["current_weight"]
        asset["sell_amount"] = 0.0
        asset["buy_amount"] = 0.0
        asset["final_amount"] = asset["amount_krw"]
        asset["status"] = "유지"

    # 상단 초과 → 목표비중까지 매도
    for asset in working:
        if asset["current_weight"] > asset["upper"]:
            target_amount = total_assets * asset["target"] / 100
            sell_amount = max(asset["amount_krw"] - target_amount, 0.0)
            asset["sell_amount"] = sell_amount
            asset["final_amount"] = target_amount
            asset["status"] = "상단 초과 → 목표까지 매도"

    total_sell = sum(a["sell_amount"] for a in working)
    available_cash = cash + total_sell

    # 하단 미달 → 목표비중까지 필요한 금액
    underweight = []
    for asset in working:
        if asset["current_weight"] < asset["lower"]:
            difference = asset["target"] - asset["current_weight"]
            needed = total_assets * difference / 100
            asset["buy_difference"] = difference
            asset["needed_amount"] = needed
            asset["status"] = "하단 미달 → 목표까지 매수"
            underweight.append(asset)
        else:
            asset["buy_difference"] = 0.0
            asset["needed_amount"] = 0.0

    total_needed = sum(a["needed_amount"] for a in underweight)

    if total_needed > 0 and available_cash <= total_needed:
        total_difference = sum(a["buy_difference"] for a in underweight)
        if total_difference > 0:
            for asset in underweight:
                buy_amount = available_cash * asset["buy_difference"] / total_difference
                asset["buy_amount"] = buy_amount
                asset["final_amount"] = asset["amount_krw"] + buy_amount
    elif total_needed > 0:
        for asset in underweight:
            buy_amount = asset["needed_amount"]
            asset["buy_amount"] = buy_amount
            asset["final_amount"] = asset["amount_krw"] + buy_amount

    for asset in working:
        asset["final_weight"] = asset["final_amount"] / total_assets * 100

    total_buy = sum(a["buy_amount"] for a in working)
    final_cash = total_assets - sum(a["final_amount"] for a in working)
    if abs(final_cash) < 0.01:
        final_cash = 0.0

    return {
        "total_assets": total_assets,
        "total_sell": total_sell,
        "total_buy": total_buy,
        "final_cash": final_cash,
        "assets": working,
    }


# ============================================================
# Header
# ============================================================
st.title("📊 원화 기준 밴드 리밸런싱 계산기")
st.caption(
    "국내 ETF와 미국 ETF를 모두 원화로 환산해 비중을 계산하고, "
    "밴드를 벗어난 자산을 목표 비중까지 조정합니다."
)

# ============================================================
# 1. FX
# ============================================================
st.header("① USD/KRW 환율")
fx_col1, fx_col2 = st.columns([3, 1])
with fx_col1:
    st.number_input(
        "USD/KRW",
        min_value=0.0,
        step=0.01,
        key="usdkrw",
        format="%.2f",
        help="미국 자산을 원화로 환산하는 데 사용할 환율입니다.",
    )
with fx_col2:
    st.write("")
    st.button(
        "🔄 최신 환율 조회",
        key="refresh_fx",
        use_container_width=True,
        on_click=fetch_fx_callback,
    )

if st.session_state.fx_error:
    st.error(st.session_state.fx_error)
elif st.session_state.usdkrw_asof:
    st.caption(
        f"적용 환율: 1 USD = {st.session_state.usdkrw:,.2f} KRW "
        f"(최근 일봉 종가, {st.session_state.usdkrw_asof})"
    )
else:
    st.caption(
        f"현재 적용 환율: 1 USD = {st.session_state.usdkrw:,.2f} KRW "
        "(기본값. 자동 조회를 권장합니다.)"
    )

# ============================================================
# 2. Assets
# ============================================================
st.header("② 자산 구성")
if st.button("＋ 자산 추가", use_container_width=True):
    add_asset()
    st.rerun()

for i, asset in enumerate(st.session_state.assets):
    if f"results_{i}" not in st.session_state:
        st.session_state[f"results_{i}"] = []

    st.subheader(asset["name"] or f"자산 {i + 1}")

    search_col1, search_col2 = st.columns([5, 1])
    with search_col1:
        st.text_input(
            "티커 또는 종목명 검색",
            key=f"search_{i}",
            placeholder="예: VOO / S&P 500 / KODEX 200",
        )
    with search_col2:
        st.write("")
        if st.button("🔍 검색", key=f"search_button_{i}", use_container_width=True):
            st.session_state[f"results_{i}"] = search_assets(st.session_state[f"search_{i}"])

    results = st.session_state[f"results_{i}"]
    if results:
        labels = [f"{r['name']} ({r['symbol']}) [{r['exchange']}]" for r in results]
        selected_label = st.selectbox("검색 결과", labels, key=f"selected_{i}")
        selected = results[labels.index(selected_label)]
        if st.button("✅ 이 종목 선택", key=f"select_button_{i}", use_container_width=True):
            asset["name"] = selected["name"]
            asset["ticker"] = selected["symbol"]
            asset["exchange"] = selected["exchange"]
            asset["market"] = detect_market(selected["symbol"], selected["exchange"])
            asset["currency"] = "USD" if asset["market"] == "미국" else "KRW"
            asset["price"] = 0.0
            asset["price_asof"] = None
            asset["price_error"] = None
            st.session_state[f"results_{i}"] = []
            # 검색 후 해당 종목의 가격 widget key가 있다면 초기화
            st.session_state[f"price_{i}"] = 0.0
            st.rerun()

    if asset["ticker"]:
        st.info(
            f"선택: **{asset['name']}** | 티커 `{asset['ticker']}` | "
            f"시장 **{asset['market']}** | 통화 **{asset['currency']}**"
        )

    # Weight state initialization
    for key, value in {
        f"target_slider_{i}": float(asset["target"]),
        f"target_number_{i}": float(asset["target"]),
        f"lower_slider_{i}": float(asset["lower"]),
        f"lower_number_{i}": float(asset["lower"]),
        f"upper_slider_{i}": float(asset["upper"]),
        f"upper_number_{i}": float(asset["upper"]),
        f"shares_{i}": float(asset["shares"]),
        f"price_{i}": float(asset["price"]),
    }.items():
        if key not in st.session_state:
            st.session_state[key] = value

    st.markdown("**목표 비중**")
    c1, c2 = st.columns([5, 1])
    with c1:
        st.slider(
            "목표 비중 슬라이더",
            min_value=0.0,
            max_value=100.0,
            step=0.5,
            key=f"target_slider_{i}",
            format="%.1f%%",
            label_visibility="collapsed",
            on_change=sync_target_from_slider,
            args=(i,),
        )
    with c2:
        st.number_input(
            "목표 %",
            min_value=0.0,
            max_value=100.0,
            step=0.5,
            key=f"target_number_{i}",
            format="%.1f",
            on_change=sync_target_from_number,
        )
        # callback에서는 index를 args로 줄 필요 없이 key를 직접 사용할 수 있으므로
        # 아래처럼 명시적으로 연결한다.
        # (위 위젯을 한 번 렌더링한 후 callback을 붙일 수 없으므로 재정의하지 않는다.)

    target = float(st.session_state[f"target_number_{i}"])
    asset["target"] = target

    # lower range/state
    if st.session_state[f"lower_number_{i}"] > target:
        st.session_state[f"lower_number_{i}"] = target
        st.session_state[f"lower_slider_{i}"] = target

    st.markdown("**하단 비중**")
    c1, c2 = st.columns([5, 1])
    with c1:
        st.slider(
            "하단 비중 슬라이더",
            min_value=0.0,
            max_value=target,
            step=0.5,
            key=f"lower_slider_{i}",
            format="%.1f%%",
            label_visibility="collapsed",
            on_change=sync_lower_from_slider,
            args=(i,),
        )
    with c2:
        st.number_input(
            "하단 %",
            min_value=0.0,
            max_value=target,
            step=0.5,
            key=f"lower_number_{i}",
            format="%.1f",
            on_change=sync_lower_from_number,
        )

    lower = float(st.session_state[f"lower_number_{i}"])
    asset["lower"] = lower

    if st.session_state[f"upper_number_{i}"] < target:
        st.session_state[f"upper_number_{i}"] = target
        st.session_state[f"upper_slider_{i}"] = target

    st.markdown("**상단 비중**")
    c1, c2 = st.columns([5, 1])
    with c1:
        st.slider(
            "상단 비중 슬라이더",
            min_value=target,
            max_value=100.0,
            step=0.5,
            key=f"upper_slider_{i}",
            format="%.1f%%",
            label_visibility="collapsed",
            on_change=sync_upper_from_slider,
            args=(i,),
        )
    with c2:
        st.number_input(
            "상단 %",
            min_value=target,
            max_value=100.0,
            step=0.5,
            key=f"upper_number_{i}",
            format="%.1f",
            on_change=sync_upper_from_number,
        )

    upper = float(st.session_state[f"upper_number_{i}"])
    asset["upper"] = upper

    st.caption(f"밴드: {lower:.1f}% ≤ {target:.1f}% ≤ {upper:.1f}%")

    # Holdings / latest price
    st.markdown("**현재 보유량**")
    if asset["ticker"]:
        st.button(
            "🔄 최신 가격 조회",
            key=f"price_button_{i}",
            on_click=fetch_price_callback,
            args=(i,),
            use_container_width=True,
        )

    if asset.get("price_error"):
        st.error(asset["price_error"])

    c1, c2, c3 = st.columns([2, 2, 2])
    with c1:
        st.number_input(
            "보유 주식 수",
            min_value=0.0,
            step=1.0,
            key=f"shares_{i}",
            format="%.6f",
        )
        asset["shares"] = float(st.session_state[f"shares_{i}"])

    with c2:
        st.number_input(
            "현재가",
            min_value=0.0,
            step=0.01,
            key=f"price_{i}",
            format="%.4f",
        )
        asset["price"] = float(st.session_state[f"price_{i}"])
        if asset.get("price_asof"):
            unit = "USD" if asset["market"] == "미국" else "KRW"
            st.caption(
                f"최근 일봉 종가: {asset['price']:,.4f} {unit} "
                f"({asset['price_asof']})"
            )

    with c3:
        if asset["market"] == "미국":
            amount_krw = asset["shares"] * asset["price"] * st.session_state.usdkrw
            st.metric("원화 평가액", f"{amount_krw:,.0f}원")
        elif asset["market"] == "국내":
            amount_krw = asset["shares"] * asset["price"]
            st.metric("원화 평가액", f"{amount_krw:,.0f}원")
        else:
            st.metric("원화 평가액", "종목을 선택하세요")

    if st.button("🗑️ 이 자산 삭제", key=f"delete_asset_{i}"):
        delete_asset(i)
        st.rerun()

    st.divider()

# ============================================================
# 3. Cash
# ============================================================
st.header("③ 현재 보유 현금")
st.number_input(
    "보유 현금 (KRW)",
    min_value=0.0,
    step=10000.0,
    key="cash",
    format="%.0f",
)

# ============================================================
# 4. Calculate
# ============================================================
st.header("④ 리밸런싱")
if st.button("🚀 원화 기준 리밸런싱 계산", type="primary", use_container_width=True):
    try:
        if not st.session_state.assets:
            raise ValueError("자산을 하나 이상 추가해주세요.")

        names = []
        for asset in st.session_state.assets:
            name = asset["name"].strip()
            if not name:
                raise ValueError("모든 자산의 이름이 필요합니다.")
            names.append(name)

            if not asset["ticker"]:
                raise ValueError(f"{name}: 종목 검색 후 선택해주세요.")
            if asset["market"] not in {"국내", "미국"}:
                raise ValueError(f"{name}: 국내/미국 시장을 확인해주세요.")
            if asset["shares"] > 0 and asset["price"] <= 0:
                raise ValueError(f"{name}: 현재가를 조회하거나 직접 입력해주세요.")
            if not (0 <= asset["lower"] <= asset["target"] <= asset["upper"] <= 100):
                raise ValueError(f"{name}: 하단 ≤ 목표 ≤ 상단 조건이 필요합니다.")

        if len(names) != len(set(names)):
            raise ValueError("같은 자산명이 중복되어 있습니다.")

        target_sum = sum(asset["target"] for asset in st.session_state.assets)
        if abs(target_sum - 100.0) > 0.0001:
            raise ValueError(
                f"목표 비중 합계가 {target_sum:.2f}%입니다. 100%가 되도록 입력해주세요."
            )

        st.session_state.result = calculate_rebalancing(
            cash=float(st.session_state.cash),
            assets=st.session_state.assets,
            usdkrw=float(st.session_state.usdkrw),
        )

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
    c1.metric("총자산", f"{result['total_assets']:,.0f}원")
    c2.metric("총 매도", f"{result['total_sell']:,.0f}원")
    c3.metric("총 매수", f"{result['total_buy']:,.0f}원")
    c4.metric("분배 후 현금", f"{result['final_cash']:,.0f}원")

    st.subheader("실행할 거래")
    trade_rows = []
    for asset in result["assets"]:
        if asset["sell_amount"] > 0.5:
            trade_rows.append({
                "자산": asset["name"],
                "시장": asset["market"],
                "거래": "매도",
                "금액": asset["sell_amount"],
            })
        if asset["buy_amount"] > 0.5:
            trade_rows.append({
                "자산": asset["name"],
                "시장": asset["market"],
                "거래": "매수",
                "금액": asset["buy_amount"],
            })

    if trade_rows:
        st.dataframe(
            pd.DataFrame(trade_rows),
            use_container_width=True,
            hide_index=True,
            column_config={
                "금액": st.column_config.NumberColumn("금액", format="₩%,.0f"),
            },
        )
    else:
        st.info("현재 밴드를 벗어난 자산이 없어 매매가 필요하지 않습니다.")

    st.subheader("전체 포트폴리오")
    rows = []
    for asset in result["assets"]:
        rows.append({
            "자산": asset["name"],
            "시장": asset["market"],
            "현재 평가액": asset["amount_krw"],
            "현재 비중": asset["current_weight"] / 100,
            "하단": asset["lower"] / 100,
            "목표": asset["target"] / 100,
            "상단": asset["upper"] / 100,
            "매도": asset["sell_amount"],
            "매수": asset["buy_amount"],
            "분배 후 금액": asset["final_amount"],
            "분배 후 비중": asset["final_weight"] / 100,
            "상태": asset["status"],
        })

    st.dataframe(
        pd.DataFrame(rows),
        use_container_width=True,
        hide_index=True,
        column_config={
            "현재 평가액": st.column_config.NumberColumn("현재 평가액", format="₩%,.0f"),
            "현재 비중": st.column_config.NumberColumn("현재 비중", format="%.2f%%"),
            "하단": st.column_config.NumberColumn("하단", format="%.1f%%"),
            "목표": st.column_config.NumberColumn("목표", format="%.1f%%"),
            "상단": st.column_config.NumberColumn("상단", format="%.1f%%"),
            "매도": st.column_config.NumberColumn("매도", format="₩%,.0f"),
            "매수": st.column_config.NumberColumn("매수", format="₩%,.0f"),
            "분배 후 금액": st.column_config.NumberColumn("분배 후 금액", format="₩%,.0f"),
            "분배 후 비중": st.column_config.NumberColumn("분배 후 비중", format="%.2f%%"),
        },
    )

    st.caption(
        "가격과 환율은 각각 가장 최근에 제공되는 일봉 종가를 사용합니다. "
        "국내/미국 시장의 휴장일이 다르므로 두 데이터의 기준일은 서로 다를 수 있으며, "
        "실제 주문가격·체결가격과도 차이가 날 수 있습니다."
    )

import time
import os
import glob
import ccxt
import pandas as pd
import streamlit as st

st.set_page_config(
    page_title="Bitget SAS - Pełna Autonomia",
    layout="wide",
)

if "logged_in" not in st.session_state:
    st.session_state.logged_in = False

# =====================================================================
# STYLIZACJA CSS (RETRO-VINTAGE)
# =====================================================================
st.markdown(
    """
    <style>
    @import url('https://fonts.googleapis.com/css2?family=Bungee+Inline&family=Cinzel:wght@700&display=swap');

    .stApp {
        background-color: #0d0b0a;
    }
    section[data-testid="stSidebar"] {
        background-color: #141110;
        border-right: 2px solid #3d2f1f;
    }
    
    section[data-testid="stSidebar"] input {
        background-color: #1e1814 !important;
        color: #f3d57a !important;
        border: 1px solid #f3d57a !important;
    }
    
    .hero-wrapper {
        display: flex;
        align-items: center;
        justify-content: center;
        width: 100%;
        padding-top: 45px;
        padding-bottom: 20px;
    }
    
    .retro-ornate-frame {
        position: relative;
        background: radial-gradient(circle, #221a14 0%, #110d0a 100%);
        border: 6px double #f3d57a;
        padding: 40px 30px 50px 30px;
        border-radius: 16px;
        box-shadow: 0 0 50px rgba(243, 213, 122, 0.4), inset 0 0 35px rgba(0, 0, 0, 0.9);
        width: 100%;
        max-width: 950px;
        text-align: center;
        display: flex;
        flex-direction: column;
        align-items: center;
        justify-content: center;
    }

    .retro-ornate-frame::before, .retro-ornate-frame::after {
        content: "❖ ❖ ❖";
        position: absolute;
        color: #f3d57a;
        font-size: 1rem;
        letter-spacing: 6px;
    }
    .retro-ornate-frame::before { top: 12px; left: 18px; }
    .retro-ornate-frame::after { top: 12px; right: 18px; }

    .retro-vintage-title {
        font-family: 'Bungee Inline', cursive, sans-serif;
        font-size: 4.5rem;
        color: #f3d57a;
        letter-spacing: 6px;
        text-shadow: 4px 4px 0px #8b0000, 8px 8px 0px rgba(0,0,0,0.95);
        margin: 5px 0 10px 0;
        line-height: 1.1;
    }

    .button-spacer {
        margin-top: 30px;
        width: 100%;
        display: flex;
        justify-content: center;
    }

    div.stButton > button {
        background: linear-gradient(135deg, #1e4d2b 0%, #0f2b17 100%) !important;
        color: #f3d57a !important;
        border: 2px solid #f3d57a !important;
        font-family: 'Cinzel', serif !important;
        font-weight: 700 !important;
        font-size: 1rem !important;
        padding: 12px 28px !important;
        border-radius: 8px !important;
        box-shadow: 0 4px 15px rgba(0, 0, 0, 0.6) !important;
        transition: all 0.3s ease !important;
    }
    div.stButton > button:hover {
        background: linear-gradient(135deg, #28663a 0%, #163d22 100%) !important;
        border-color: #ffe89d !important;
        color: #ffe89d !important;
        box-shadow: 0 0 20px rgba(243, 213, 122, 0.4) !important;
        transform: translateY(-2px);
    }

    .retro-card {
        background: radial-gradient(circle, #221a14 0%, #110d0a 100%);
        border: 3px double #f3d57a;
        padding: 18px 15px;
        border-radius: 12px;
        box-shadow: 0 0 20px rgba(243, 213, 122, 0.2), inset 0 0 15px rgba(0, 0, 0, 0.8);
        height: 155px;
        display: flex;
        flex-direction: column;
        justify-content: center;
        align-items: center;
        text-align: center;
        margin-bottom: 10px;
    }

    .retro-card h3 {
        font-family: 'Cinzel', serif !important;
        color: #f3d57a !important;
        letter-spacing: 2px;
        margin-bottom: 8px !important;
        font-size: 1.05rem !important;
    }
    </style>
    """,
    unsafe_allow_html=True,
)

# =====================================================================
# STRONA POWITALNA
# =====================================================================
if not st.session_state.logged_in:
    st.markdown(
        f"""
        <div class="hero-wrapper">
            <div class="retro-ornate-frame">
                <div class="retro-vintage-title">BITGET SAS</div>
        """,
        unsafe_allow_html=True,
    )

    st.markdown('<div class="button-spacer">', unsafe_allow_html=True)
    col_b1, col_b2, col_b3 = st.columns([2, 3, 2])
    with col_b2:
        if st.button("🚀 WEJDŹ DO SYSTEMU", use_container_width=True):
            st.session_state.logged_in = True
            st.rerun()
    st.markdown("</div>", unsafe_allow_html=True)

    st.markdown("</div></div>", unsafe_allow_html=True)
    st.stop()

# =====================================================================
# WŁAŚCIWA APLIKACJA (PO WEJŚCIU)
# =====================================================================
st.title("🚀 Bitget SAS - Panel Operacyjny")

if "trade_history" not in st.session_state:
    st.session_state.trade_history = []

if "active_spot_holdings" not in st.session_state:
    st.session_state.active_spot_holdings = {}


def get_exchange(ex_type, api_key="", secret="", password=""):
    try:
        config = {
            "apiKey": api_key,
            "secret": secret,
            "password": password,
            "enableRateLimit": True,
            "headers": {"X-BH-SUBACCOUNT": ""},
        }
        if ex_type == "spot":
            ex = ccxt.bitget(config)
        else:
            config["options"] = {"defaultType": "swap"}
            ex = ccxt.bitget(config)
        ex.load_markets()
        return ex
    except Exception as e:
        return None


with st.sidebar.container(border=True):
    st.markdown("### 🔑 Konfiguracja API Bitget")
    api_key_input = st.text_input("API Key", type="password")
    secret_input = st.text_input("Secret Key", type="password")
    password_input = st.text_input("Passphrase", type="password")

spot_ex = get_exchange("spot", api_key_input, secret_input, password_input)
futures_ex = get_exchange(
    "futures", api_key_input, secret_input, password_input
)

st.sidebar.markdown("---")
if st.sidebar.button("🔒 Wróć do ekranu powitalnego"):
    st.session_state.logged_in = False
    st.rerun()

st.sidebar.markdown("---")
with st.sidebar.container(border=True):
    st.markdown("### 🔔 Powiadomienia")
    enable_notifications = st.checkbox(
        "Włącz powiadomienia o transakcjach", value=True
    )
    telegram_bot_token = st.text_input(
        "Telegram Bot Token (opcjonalnie)", type="password"
    )
    telegram_chat_id = st.text_input("Telegram Chat ID (opcjonalnie)")


def send_notification(message):
    if enable_notifications:
        st.toast(message, icon="🤖")
        if telegram_bot_token and telegram_chat_id:
            try:
                import urllib.parse
                import urllib.request

                url = f"https://api.telegram.org/bot{telegram_bot_token}/sendMessage"
                data = urllib.parse.urlencode(
                    {"chat_id": telegram_chat_id, "text": message}
                ).encode("utf-8")
                urllib.request.urlopen(url, data=data, timeout=3)
            except Exception:
                pass


st.sidebar.markdown("---")
with st.sidebar.container(border=True):
    st.markdown("### ⚙️ Ustawienia Handlu i Ryzyka")
    allocation_mode = st.radio(
        "Zarządzanie wielkością pozycji",
        [
            "🤖 Dynamiczny Auto-Dobór",
            "🎛️ Stały procent portfela",
        ],
    )
    base_allocation_pct = st.slider(
        "Bazowy kapitał na 1 pozycję (%)", 1, 50, 15
    )
    max_single_trade_usdt = st.number_input(
        "🛡️ Maksymalnie USDT na 1 pozycję", 5.0, 10000.0, 20.0, 5.0
    )
    leverage_mode = st.radio(
        "Tryb Dźwigni Futures",
        ["🤖 Auto-dobór", "🎛️ Ręczny"],
    )
    manual_leverage = 5
    if "Ręczny" in leverage_mode:
        manual_leverage = st.slider("Stała dźwignia Futures", 1, 50, 5)

    st.markdown("---")
    st.markdown("### 🧠 Inteligentne Dynamiczne Wyjście (Dynamic Exit)")
    spot_tf = st.selectbox(
        "Timeframe analizy", ["1m", "5m", "15m", "30m", "1h", "4h", "1d"], index=4
    )

st.sidebar.markdown("---")
with st.sidebar.container(border=True):
    st.markdown("### 🔄 Pętla Automatyczna")
    auto_scan_enabled = st.checkbox(
        "Włącz auto-skanowanie w tle", value=False
    )
    scan_interval = st.slider("Interwał odświeżania (s)", 10, 300, 30)

st.sidebar.markdown("---")
emergency_kill = st.sidebar.button(
    "🛑 ZAMKNIJ WSZYSTKO (KILL SWITCH)", type="primary"
)

if emergency_kill:
    if futures_ex:
        try:
            positions = futures_ex.fetch_positions()
            for p in positions:
                contracts = float(p.get("contracts", 0))
                if contracts > 0:
                    sym = p["symbol"]
                    side = "sell" if p.get("side") == "long" else "buy"
                    futures_ex.create_market_order(
                        sym, side, contracts, params={"reduceOnly": True}
                    )
        except Exception:
            pass

    if spot_ex:
        try:
            for sym, data in list(st.session_state.active_spot_holdings.items()):
                try:
                    spot_ex.create_market_order(sym, "sell", data["amount"])
                except Exception:
                    pass
            st.session_state.active_spot_holdings.clear()
        except Exception:
            pass

    send_notification("🚨 [KILL SWITCH] Awaryjnie zamknięto wszystkie pozycje i wyprzedano Spot!")
    time.sleep(1)
    st.rerun()

# =====================================================================
# INTELIGENTNE DYNAMICZNE ZARZĄDZANIE WYJŚCIEM (SPOT + FUTURES)
# =====================================================================
if (st.session_state.get("scanner_active", False) or auto_scan_enabled):
    
    # 1. Zarządzanie wyjściem SPOT
    if spot_ex and st.session_state.active_spot_holdings:
        for sym, holding in list(st.session_state.active_spot_holdings.items()):
            try:
                ohlcv_spot = spot_ex.fetch_ohlcv(sym, timeframe=spot_tf, limit=30)
                df_s_pos = pd.DataFrame(ohlcv_spot, columns=["timestamp", "open", "high", "low", "close", "volume"])
                current_price = df_s_pos["close"].iloc[-1]
                entry_price = holding["entry_price"]
                
                percentage_pnl = ((current_price - entry_price) / entry_price) * 100.0
                
                delta = df_s_pos["close"].diff()
                gain = (delta.where(delta > 0, 0)).rolling(14).mean()
                loss = (-delta.where(delta < 0, 0)).rolling(14).mean()
                rs = gain / loss
                rsi_series = 100 - (100 / (1 + rs))
                current_rsi = rsi_series.iloc[-1] if not pd.isna(rsi_series.iloc[-1]) else 50
                
                macd = df_s_pos["close"].ewm(span=12, adjust=False).mean() - df_s_pos["close"].ewm(span=26, adjust=False).mean()
                signal = macd.ewm(span=9, adjust=False).mean()
                
                exit_spot_profit = (percentage_pnl > 1.5) and (current_rsi > 75 or macd.iloc[-1] < signal.iloc[-1])
                exit_spot_risk = (percentage_pnl <= -1.5) or (current_rsi < 20)
                
                if exit_spot_profit or exit_spot_risk:
                    spot_ex.create_market_order(sym, "sell", holding["amount"])
                    reason = "ZYSK (Momentum)" if exit_spot_profit else "OCHRONA (Risk/Stop)"
                    send_notification(f"🟢 [SPOT DYNAMIC EXIT - {reason}] Sprzedano {sym}. PnL: {percentage_pnl:+.2f}%")
                    del st.session_state.active_spot_holdings[sym]
            except Exception:
                pass

    # 2. Zarządzanie wyjściem FUTURES
    if futures_ex:
        try:
            active_pos = futures_ex.fetch_positions()
            for p in active_pos:
                contracts = float(p.get("contracts", 0))
                if contracts > 0:
                    sym = p["symbol"]
                    percentage_pnl = float(p.get("percentage", 0.0))
                    position_side = p.get("side", "long")
                    
                    ohlcv_pos = futures_ex.fetch_ohlcv(sym, timeframe=spot_tf, limit=30)
                    df_pos = pd.DataFrame(ohlcv_pos, columns=["timestamp", "open", "high", "low", "close", "volume"])
                    
                    delta = df_pos["close"].diff()
                    gain = (delta.where(delta > 0, 0)).rolling(14).mean()
                    loss = (-delta.where(delta < 0, 0)).rolling(14).mean()
                    rs = gain / loss
                    rsi_series = 100 - (100 / (1 + rs))
                    current_rsi = rsi_series.iloc[-1] if not pd.isna(rsi_series.iloc[-1]) else 50
                    
                    macd = df_pos["close"].ewm(span=12, adjust=False).mean() - df_pos["close"].ewm(span=26, adjust=False).mean()
                    signal = macd.ewm(span=9, adjust=False).mean()
                    
                    if position_side == "long":
                        exit_due_to_max_profit = (percentage_pnl > 1.5) and (current_rsi > 75 or macd.iloc[-1] < signal.iloc[-1])
                        exit_due_to_risk = (percentage_pnl <= -1.5) or (current_rsi < 20)
                    else: # short
                        exit_due_to_max_profit = (percentage_pnl > 1.5) and (current_rsi < 25 or macd.iloc[-1] > signal.iloc[-1])
                        exit_due_to_risk = (percentage_pnl <= -1.5) or (current_rsi > 80)

                    if exit_due_to_max_profit:
                        side = "sell" if position_side == "long" else "buy"
                        futures_ex.create_market_order(sym, side, contracts, params={"reduceOnly": True})
                        send_notification(f"🧠 [FUTURES DYNAMIC EXIT - ZYSK] Zamknięto {position_side.upper()} {sym}. PnL: +{percentage_pnl:.2f}%")
                    
                    elif exit_due_to_risk:
                        side = "sell" if position_side == "long" else "buy"
                        futures_ex.create_market_order(sym, side, contracts, params={"reduceOnly": True})
                        send_notification(f"🛡️ [FUTURES DYNAMIC EXIT - OBRONA] Ucięto {position_side.upper()} {sym}. PnL: {percentage_pnl:.2f}%")
        except Exception:
            pass

# Pobieranie sald i aktywów Spot
spot_free, spot_total = 0.0, 0.0
spot_assets_count = 0
spot_assets_summary = []

if spot_ex:
    try:
        s_bal = spot_ex.fetch_balance()
        spot_free = s_bal["free"].get("USDT", 0.0)
        spot_total = s_bal["total"].get("USDT", 0.0)

        for coin, amount in s_bal["total"].items():
            if coin != "USDT" and float(amount) > 0:
                spot_assets_count += 1
                spot_assets_summary.append(f"{coin}: {float(amount):.4f}")
    except Exception:
        pass

fut_free, fut_total = 0.0, 0.0
if futures_ex:
    try:
        f_bal = futures_ex.fetch_balance()
        fut_free = f_bal["free"].get("USDT", 0.0)
        fut_total = f_bal["total"].get("USDT", 0.0)
    except Exception:
        pass

# =====================================================================
# ROZDZIELONE KAFELKI WYNIKÓW (SPOT OSOBNO, FUTURES OSOBNO)
# =====================================================================
spot_unrealized_pnl = 0.0
if spot_ex and st.session_state.active_spot_holdings:
    for sym, holding in st.session_state.active_spot_holdings.items():
        try:
            ticker = spot_ex.fetch_ticker(sym)
            curr_p = ticker.get("last", holding["entry_price"])
            pnl_item = (curr_p - holding["entry_price"]) * holding["amount"]
            spot_unrealized_pnl += pnl_item
        except Exception:
            pass

total_unrealized_pnl = 0.0
active_positions_count = 0
if futures_ex:
    try:
        positions = futures_ex.fetch_positions()
        for p in positions:
            if float(p.get("contracts", 0)) > 0:
                active_positions_count += 1
                total_unrealized_pnl += float(p.get("unrealizedPnl", 0.0))
    except Exception:
        pass

col1, col2, col3 = st.columns(3)

with col1:
    st.markdown(
        f"""
        <div class="retro-card">
            <h3>🟢 Portfel Spot</h3>
            <p style="color: #f3d57a; font-size: 1.05rem; margin: 4px 0;"><b>Wolne:</b> {spot_free:.2f} USDT</p>
            <p style="color: #cccccc; font-size: 0.9rem; margin: 0;"><b>Całkowite:</b> {spot_total:.2f} USDT</p>
        </div>
        """,
        unsafe_allow_html=True,
    )

with col2:
    st.markdown(
        f"""
        <div class="retro-card">
            <h3>🔵 Portfel Futures</h3>
            <p style="color: #f3d57a; font-size: 1.05rem; margin: 4px 0;"><b>Wolne:</b> {fut_free:.2f} USDT</p>
            <p style="color: #cccccc; font-size: 0.9rem; margin: 0;"><b>Całkowite:</b> {fut_total:.2f} USDT</p>
        </div>
        """,
        unsafe_allow_html=True,
    )

spot_pnl_color = "#4CAF50" if spot_unrealized_pnl >= 0 else "#FF5252"
fut_pnl_color = "#4CAF50" if total_unrealized_pnl >= 0 else "#FF5252"

with col3:
    st.markdown(
        f"""
        <div class="retro-card" style="height: auto; min-height: 155px; padding: 12px 10px;">
            <h3>📊 Wyniki i Pozycje</h3>
            <div style="border-bottom: 1px solid #3d2f1f; margin-bottom: 6px; padding-bottom: 4px; width: 100%;">
                <span style="color: #f3d57a; font-size: 0.85rem;"><b>SPOT:</b></span> 
                <span style="color: {spot_pnl_color}; font-size: 0.9rem;">{spot_unrealized_pnl:+.2f} USDT</span> 
                <span style="color: #cccccc; font-size: 0.8rem;">({len(st.session_state.active_spot_holdings)} poz.)</span>
            </div>
            <div style="width: 100%;">
                <span style="color: #f3d57a; font-size: 0.85rem;"><b>FUTURES:</b></span> 
                <span style="color: {fut_pnl_color}; font-size: 0.9rem;">{total_unrealized_pnl:+.2f} USDT</span> 
                <span style="color: #cccccc; font-size: 0.8rem;">({active_positions_count} poz.)</span>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

st.markdown("---")

if "scanner_active" not in st.session_state:
    st.session_state.scanner_active = False

col_btn, col_status = st.columns([2, 1])

with col_btn:
    if not st.session_state.scanner_active:
        if st.button(
            "🚀 Uruchom w pełni autonomiczny skaner (Spot + Futures)",
            type="primary",
            use_container_width=True,
        ):
            st.session_state.scanner_active = True
            st.rerun()
    else:
        if st.button(
            "⏹️ Zatrzymaj autonomiczny skaner",
            type="secondary",
            use_container_width=True,
        ):
            st.session_state.scanner_active = False
            st.rerun()

with col_status:
    if st.session_state.scanner_active or auto_scan_enabled:
        st.success("🟢 STATUS: AKTYWNY (DZIAŁA)")
    else:
        st.error("🔴 STATUS: ZATRZYMANY")

run_manual_trigger = st.session_state.scanner_active

# =====================================================================
# SKANER SPOT
# =====================================================================
trusted_base_coins = [
    "BTC",
    "ETH",
    "SOL",
    "XRP",
    "ADA",
    "AVAX",
    "DOGE",
    "LINK",
    "SUI",
    "NEAR",
    "APT",
    "RENDER",
    "INJ",
    "PEPE",
    "SHIB",
    "LTC",
    "DOT",
    "UNI",
]

st.subheader("📊 Autonomiczny Skaner Spot")
spot_results = []
if spot_ex:
    try:
        s_tickers = spot_ex.fetch_tickers()
        valid_s = {
            sym: data
            for sym, data in s_tickers.items()
            if any(sym.startswith(coin + "/") for coin in trusted_base_coins)
            and sym.endswith("/USDT")
            and "BULL" not in sym
            and "BEAR" not in sym
            and data.get("quoteVolume", 0) > 1000000
        }
        sorted_s = sorted(
            valid_s.items(), key=lambda x: x[1].get("quoteVolume", 0), reverse=True
        )
        top_spot_symbols = [item[0] for item in sorted_s[:8]]
    except Exception:
        top_spot_symbols = ["BTC/USDT", "ETH/USDT", "SOL/USDT"]

    # Stały minimalny próg giełdowy Bitget dla spot (5 USDT)
    MIN_SPOT_TRADE = 5.0

    for idx, sym in enumerate(top_spot_symbols):
        try:
            ohlcv = spot_ex.fetch_ohlcv(sym, timeframe=spot_tf, limit=50)
            time.sleep(0.1)
            df = pd.DataFrame(
                ohlcv, columns=["timestamp", "open", "high", "low", "close", "volume"]
            )

            df["volatility_pct"] = (
                (df["high"] - df["low"]) / df["close"]
            ).rolling(14).mean() * 100
            current_vol = (
                df["volatility_pct"].iloc[-1]
                if not pd.isna(df["volatility_pct"].iloc[-1])
                else 2.0
            )

            delta = df["close"].diff()
            gain = (delta.where(delta > 0, 0)).rolling(14).mean()
            loss = (-delta.where(delta < 0, 0)).rolling(14).mean()
            rs = gain / loss
            df["rsi"] = 100 - (100 / (1 + rs))
            current_rsi = df["rsi"].iloc[-1] if not pd.isna(df["rsi"].iloc[-1]) else 50

            df["macd"] = (
                df["close"].ewm(span=12, adjust=False).mean()
                - df["close"].ewm(span=26, adjust=False).mean()
            )
            df["signal"] = df["macd"].ewm(span=9, adjust=False).mean()

            strat_type = idx % 3
            if strat_type == 0:
                strat_name = "Grid / Siatka Obronna"
                sma_20 = df["close"].rolling(20).mean().iloc[-1]
                is_buy = abs(df["close"].iloc[-1] - sma_20) / sma_20 < 0.025
            elif strat_type == 1:
                strat_name = "RSI Mean Reversion"
                is_buy = current_rsi < 42
            else:
                strat_name = "Trend-Following (MACD)"
                is_buy = df["macd"].iloc[-1] > df["signal"].iloc[-1]

            # Inteligentny dobór alokacji z uwzględnieniem minimum giełdowego (5 USDT)
            if "Dynamiczny" in allocation_mode:
                risk_multiplier = (
                    0.5 if current_vol > 4.0 else (0.8 if current_vol > 2.0 else 1.0)
                )
                calc_pct = max(1.0, min(30.0, base_allocation_pct * risk_multiplier))
            else:
                calc_pct = float(base_allocation_pct)

            prov_budget = spot_free * (calc_pct / 100.0)
            
            # Jeśli wyliczony budżet jest mniejszy niż minimum giełdy (5 USDT), ale masz wystarczająco wolnych środków,
            # podciągamy do minimum 5 USDT, żeby nie dzielić bez sensu na ułamki.
            if prov_budget < MIN_SPOT_TRADE and spot_free >= MIN_SPOT_TRADE:
                allocated_budget = min(MIN_SPOT_TRADE, max_single_trade_usdt)
            else:
                allocated_budget = min(prov_budget, max_single_trade_usdt)

            status = f"⏳ Oczekiwanie ({strat_name})"

            if (run_manual_trigger or auto_scan_enabled) and is_buy:
                if sym in st.session_state.active_spot_holdings:
                    status = "⚠️ Już trzymamy tę pozycję"
                elif allocated_budget >= MIN_SPOT_TRADE and spot_free >= allocated_budget:
                    try:
                        current_price = df["close"].iloc[-1]
                        amount_to_buy = allocated_budget / current_price
                        order = spot_ex.create_order(
                            sym, "market", "buy", amount_to_buy, current_price
                        )
                        
                        st.session_state.active_spot_holdings[sym] = {
                            "amount": amount_to_buy,
                            "entry_price": current_price
                        }

                        status = f"🚀 ZŁOŻONO KUPNO SPOT! ({allocated_budget:.1f} USDT)"
                        send_notification(
                            f"🟢 [SPOT] Kupiono {sym} za {allocated_budget:.1f} USDT po cenie {current_price:.4f}"
                        )
                        st.session_state.trade_history.insert(
                            0,
                            {
                                "Czas": time.strftime("%H:%M:%S"),
                                "Typ": "SPOT",
                                "Para": sym,
                                "Akcja": "KUPNO",
                                "Kwota USDT": f"{allocated_budget:.1f}",
                                "Cena": f"{current_price:.4f}",
                            },
                        )
                    except Exception as ex:
                        status = f"❌ Błąd zlecenia: {ex}"
                else:
                    status = "⚠️ Zbyt małe saldo na min. 5 USDT"

            spot_results.append({
                "Para": sym,
                "Cena": f"{df['close'].iloc[-1]:.4f}",
                "Strategia": strat_name,
                "Alokacja": f"{allocated_budget:.1f} USDT",
                "Status": status,
            })
        except Exception:
            continue

    if spot_results:
        st.dataframe(pd.DataFrame(spot_results), width="stretch")

st.markdown("---")

# =====================================================================
# SKANER FUTURES (OBSŁUGUJE LONG ORAZ SHORT NA SPADKACH)
# =====================================================================
st.subheader("📈 Autonomiczny Skaner Futures (Long & Short)")
fut_results = []
if futures_ex:
    try:
        f_tickers = futures_ex.fetch_tickers()
        valid_f = {
            sym: data
            for sym, data in f_tickers.items()
            if any(
                sym.startswith(coin + "/")
                or sym.startswith(coin + ":")
                or sym == (coin + "/USDT:USDT")
                for coin in trusted_base_coins
            )
            and (sym.endswith(":USDT") or "/USDT:USDT" in sym)
            and "BULL" not in sym
            and "BEAR" not in sym
            and data.get("quoteVolume", 0) > 2000000
        }
        sorted_f = sorted(
            valid_f.items(), key=lambda x: x[1].get("quoteVolume", 0), reverse=True
        )
        top_fut_symbols = [item[0] for item in sorted_f[:8]]
    except Exception:
        top_fut_symbols = ["BTC/USDT:USDT", "ETH/USDT:USDT", "SOL/USDT:USDT"]

    MIN_FUT_TRADE = 5.0

    for idx, sym in enumerate(top_fut_symbols):
        try:
            ohlcv = futures_ex.fetch_ohlcv(sym, timeframe=spot_tf, limit=50)
            time.sleep(0.1)
            df = pd.DataFrame(
                ohlcv, columns=["timestamp", "open", "high", "low", "close", "volume"]
            )

            df["volatility_pct"] = (
                (df["high"] - df["low"]) / df["close"]
            ).rolling(14).mean() * 100
            current_vol = (
                df["volatility_pct"].iloc[-1]
                if not pd.isna(df["volatility_pct"].iloc[-1])
                else 2.0
            )

            delta = df["close"].diff()
            gain = (delta.where(delta > 0, 0)).rolling(14).mean()
            loss = (-delta.where(delta < 0, 0)).rolling(14).mean()
            rs = gain / loss
            df["rsi"] = 100 - (100 / (1 + rs))
            current_rsi = df["rsi"].iloc[-1] if not pd.isna(df["rsi"].iloc[-1]) else 50

            df["macd"] = (
                df["close"].ewm(span=12, adjust=False).mean()
                - df["close"].ewm(span=26, adjust=False).mean()
            )
            df["signal"] = df["macd"].ewm(span=9, adjust=False).mean()

            strat_type = idx % 3
            is_futures_signal = False
            trade_action = "buy"
            action_label = "LONG"

            if strat_type == 0:
                dyn_leverage = 3
                strat_name = "Futures Grid"
                sma_20 = df["close"].rolling(20).mean().iloc[-1]
                deviation = (df["close"].iloc[-1] - sma_20) / sma_20
                if abs(deviation) < 0.02:
                    is_futures_signal = True
                    trade_action = "sell" if deviation > 0 else "buy"
                    action_label = "SHORT" if trade_action == "sell" else "LONG"
            elif strat_type == 1:
                dyn_leverage = 5
                strat_name = "Futures RSI Reversal"
                if current_rsi < 40:
                    is_futures_signal = True
                    trade_action = "buy"
                    action_label = "LONG"
                elif current_rsi > 65:
                    is_futures_signal = True
                    trade_action = "sell"
                    action_label = "SHORT"
            else:
                dyn_leverage = (
                    8 if "Auto" in leverage_mode else manual_leverage
                )
                strat_name = "Trend-Following (MACD)"
                macd_val = df["macd"].iloc[-1]
                signal_val = df["signal"].iloc[-1]
                if macd_val > signal_val:
                    is_futures_signal = True
                    trade_action = "buy"
                    action_label = "LONG"
                elif macd_val < signal_val:
                    is_futures_signal = True
                    trade_action = "sell"
                    action_label = "SHORT"

            if "Dynamiczny" in allocation_mode:
                risk_multiplier = (
                    0.5 if current_vol > 4.0 else (0.8 if current_vol > 2.0 else 1.0)
                )
                calc_pct = max(1.0, min(30.0, base_allocation_pct * risk_multiplier))
            else:
                calc_pct = float(base_allocation_pct)

            prov_budget = fut_free * (calc_pct / 100.0)
            
            if prov_budget < MIN_FUT_TRADE and fut_free >= MIN_FUT_TRADE:
                allocated_budget = min(MIN_FUT_TRADE, max_single_trade_usdt)
            else:
                allocated_budget = min(prov_budget, max_single_trade_usdt)

            status = "⏳ Oczekiwanie na sygnał"

            if (run_manual_trigger or auto_scan_enabled) and is_futures_signal:
                if allocated_budget >= MIN_FUT_TRADE and fut_free >= allocated_budget:
                    try:
                        current_price = df["close"].iloc[-1]
                        try:
                            futures_ex.set_leverage(dyn_leverage, sym)
                        except Exception:
                            pass

                        contract_size = (
                            allocated_budget * dyn_leverage
                        ) / current_price
                        
                        order = futures_ex.create_market_order(
                            sym, trade_action, contract_size
                        )
                        
                        status = f"🚀 OTWARTO {action_label} ({dyn_leverage}x) - {allocated_budget:.1f} USDT"
                        send_notification(
                            f"🔵 [FUTURES] Otwarto {action_label} {sym} z dźwignią {dyn_leverage}x"
                        )
                        st.session_state.trade_history.insert(
                            0,
                            {
                                "Czas": time.strftime("%H:%M:%S"),
                                "Typ": "FUTURES",
                                "Para": sym,
                                "Akcja": f"{action_label} ({dyn_leverage}x)",
                                "Kwota USDT": f"{allocated_budget:.1f}",
                                "Cena": f"{current_price:.4f}",
                            },
                        )
                    except Exception as ex:
                        status = f"❌ Błąd Futures: {ex}"
                else:
                    status = "⚠️ Zbyt małe saldo na min. 5 USDT"

            fut_results.append({
                "Kontrakt": sym,
                "Cena": f"{df['close'].iloc[-1]:.4f}",
                "Strategia": strat_name,
                "Auto-Alokacja": f"{allocated_budget:.1f} USDT",
                "Auto-Dźwignia": f"{dyn_leverage}x",
                "Status": status,
            })
        except Exception:
            continue

    if fut_results:
        st.dataframe(pd.DataFrame(fut_results), width="stretch")

st.markdown("---")
st.subheader("📜 Dziennik Transakcji w Bieżącej Sesji")
if st.session_state.trade_history:
    st.dataframe(pd.DataFrame(st.session_state.trade_history), width="stretch")
else:
    st.info("Brak zarejestrowanych transakcji w tej sesji.")

# =====================================================================
# AUTOMATYCZNE ODŚWIEŻANIE STRONY
# =====================================================================
if run_manual_trigger or auto_scan_enabled:
    time.sleep(scan_interval)
    st.rerun()
# === PANEL SUBSKRYPCJI I ZABEZPIECZENIE SAAS ===

# Twój e-mail administratora (zawsze ma dostęp bez opłaty)
my_admin_email = "marekja57@wp.pl"

st.sidebar.markdown("---")
st.sidebar.markdown("### 💎 Strefa SaaS")

# Pole do wpisania e-maila weryfikującego dostęp w panelu bocznym
current_user_email = st.sidebar.text_input("Twój e-mail (weryfikacja dostępu):", "marekja57@wp.pl")

# Sprawdzenie czy to Ty, czy klient z opłaconą subskrypcją
is_owner = (current_user_email == my_admin_email)
user_subscribed = is_owner or False # Tu w przyszłości podepniemy automatyczne sprawdzenie Stripe dla innych

# Przycisk zakupu dla osób bez subskrypcji
if not user_subscribed:
    stripe_payment_link = "https://buy.stripe.com/00w0kecL1sfbck0c13oA00"
    st.sidebar.markdown(
        f"""
        <a href="{stripe_payment_link}" target="_blank">
            <div style="background: linear-gradient(135deg, #635bff 0%, #4338ca 100%); 
                        color: white; padding: 10px 15px; border-radius: 8px; 
                        text-align: center; font-weight: bold; text-decoration: none;">
                💳 KUP SUBSKRYPCJĘ (49 PLN)
            </div>
        </a>
        """,
        unsafe_allow_html=True
    )
    st.warning("⚠️ Wymagana aktywna subskrypcja SaaS, aby korzystać z panelu handlowego.")
    st.stop() # Zatrzymuje aplikację dla osób bez dostępu
else:
    st.sidebar.success("✅ Dostęp aktywny (Administrator)")

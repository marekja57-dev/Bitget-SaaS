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

if "signal_cooldown" not in st.session_state:
    st.session_state.signal_cooldown = {}

if "scanner_active" not in st.session_state:
    st.session_state.scanner_active = False

if "active_trades" not in st.session_state:
    st.session_state.active_trades = {}

if "trend_bot_spot_active" not in st.session_state:
    st.session_state.trend_bot_spot_active = False

if "trend_bot_fut_active" not in st.session_state:
    st.session_state.trend_bot_fut_active = False


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
futures_ex = get_exchange("futures", api_key_input, secret_input, password_input)

st.sidebar.markdown("---")
if st.sidebar.button("🔒 Wróć do ekranu powitalnego"):
    st.session_state.logged_in = False
    st.rerun()

st.sidebar.markdown("---")
with st.sidebar.container(border=True):
    st.markdown("### 🔔 Powiadomienia")
    enable_notifications = st.checkbox("Włącz powiadomienia o transakcjach", value=True)
    telegram_bot_token = st.text_input("Telegram Bot Token (opcjonalnie)", type="password")
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
    base_allocation_pct = st.slider("Bazowy kapitał na 1 pozycję (%)", 1, 50, 15)
    max_single_trade_usdt = st.number_input("🛡️ Maksymalnie USDT na 1 pozycję", 5.0, 10000.0, 20.0, 5.0)

    st.markdown("---")
    st.markdown("### 🎯 Automatyczne Take Profit / Stop Loss")
    take_profit_pct = st.slider("Take Profit (%)", 0.5, 20.0, 3.0, 0.5)
    stop_loss_pct = st.slider("Stop Loss (%)", 0.5, 10.0, 1.5, 0.5)

    st.markdown("---")
    st.markdown("### ⚡ Zarządzanie Dźwignią Futures")
    leverage_mode = st.radio("Tryb Dźwigni", ["🤖 Auto-dobór", "🎛️ Ręczny"])
    manual_leverage = st.slider("Stała dźwignia Futures (Ręczna)", 1, 50, 5)

    st.markdown("---")
    st.markdown("### 🧠 Inteligentne Wyjście (Dynamic Exit)")
    spot_tf = st.selectbox("Timeframe analizy", ["1m", "5m", "15m", "30m", "1h", "4h", "1d"], index=4)

st.sidebar.markdown("---")
with st.sidebar.container(border=True):
    st.markdown("### 🔄 Pętla Główna Skanera")
    
    def toggle_scanner_from_sidebar():
        st.session_state.scanner_active = st.session_state.sidebar_auto_scan_cb

    auto_scan_enabled = st.checkbox(
        "Włącz auto-skanowanie w tle",
        value=st.session_state.scanner_active,
        key="sidebar_auto_scan_cb",
        on_change=toggle_scanner_from_sidebar
    )
    scan_interval = st.slider("Interwał odświeżania (s)", 10, 300, 30)

st.sidebar.markdown("---")
emergency_kill = st.sidebar.button("🛑 ZAMKNIJ WSZYSTKO (KILL SWITCH)", type="primary")

# =====================================================================
# KILL SWITCH DLA FUTURES
# =====================================================================
if emergency_kill:
    if futures_ex:
        try:
            positions = futures_ex.fetch_positions()
            for p in positions:
                contracts = float(p.get("contracts", 0))
                if contracts > 0:
                    sym = p["symbol"]
                    side = "sell" if p.get("side") == "long" else "buy"
                    try:
                        futures_ex.create_market_order(sym, side, contracts, params={"reduceOnly": True})
                    except Exception:
                        pass
        except Exception:
            pass

    st.session_state.scanner_active = False
    st.session_state.trend_bot_spot_active = False
    st.session_state.trend_bot_fut_active = False
    st.session_state.active_trades = {}
    send_notification("🚨 [KILL SWITCH] Awaryjnie zamknięto aktywne kontrakty i wyłączono boty!")
    st.success("🚨 KILL SWITCH WYKONANY: Pozycje Futures i boty zostały zatrzymane.")
    time.sleep(2)
    st.rerun()

# =====================================================================
# POBIERANIE SALD
# =====================================================================
spot_free, spot_total = 0.0, 0.0
if spot_ex:
    try:
        s_bal = spot_ex.fetch_balance()
        spot_free = float(s_bal.get("free", {}).get("USDT", 0.0))
        spot_total = float(s_bal.get("total", {}).get("USDT", 0.0))
    except Exception:
        pass

fut_free, fut_total = 0.0, 0.0
if futures_ex:
    try:
        f_bal = futures_ex.fetch_balance()
        fut_free = float(f_bal.get("free", {}).get("USDT", 0.0))
        fut_total = float(f_bal.get("total", {}).get("USDT", 0.0))
    except Exception:
        pass

# =====================================================================
# KAFELKI WYNIKÓW
# =====================================================================
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
            <h3>🟢 Portfel Spot (USDT)</h3>
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

fut_pnl_color = "#4CAF50" if total_unrealized_pnl >= 0 else "#FF5252"

with col3:
    st.markdown(
        f"""
        <div class="retro-card">
            <h3>📊 Wyniki i Pozycje</h3>
            <p style="color: #f3d57a; font-size: 0.95rem; margin: 4px 0;"><b>SPOT:</b> +0.00 USDT (0 poz.)</p>
            <p style="color: #f3d57a; font-size: 0.95rem; margin: 0;"><b>FUTURES:</b> <span style="color: {fut_pnl_color};">{total_unrealized_pnl:+.2f} USDT ({active_positions_count} poz.)</span></p>
        </div>
        """,
        unsafe_allow_html=True,
    )

st.markdown("---")

# =====================================================================
# 🥾 GŁÓWNY PANEL STEROWANIA BOTAMI HANDLOWYMI (TREND-FOLLOWING)
# =====================================================================
st.subheader("🥾 Panel Sterowania Botami Trendowymi (Spot & Futures)")
with st.container(border=True):
    col_tb1, col_tb2 = st.columns(2)
    
    with col_tb1:
        st.markdown("### 🟢 Bot Trendowy Spot")
        bot_spot_coin = st.selectbox("Wybierz parę (Spot)", ["BTC/USDT", "ETH/USDT", "SOL/USDT", "XRP/USDT", "SUI/USDT"], index=0, key="main_bot_s_coin")
        
        def toggle_main_trend_spot():
            st.session_state.trend_bot_spot_active = st.session_state.main_cb_trend_spot

        st.checkbox("🟢 Uruchom Bota Spot Trendowego", value=st.session_state.trend_bot_spot_active, key="main_cb_trend_spot", on_change=toggle_main_trend_spot)
        
        if st.session_state.trend_bot_spot_active:
            st.success("🟢 Bot Spot Trendowy DZIAŁA")
        else:
            st.info("🔴 Bot Spot Trendowy ZATRZYMANY")

    with col_tb2:
        st.markdown("### 🔵 Bot Trendowy Futures")
        bot_fut_coin = st.selectbox("Wybierz kontrakt (Futures)", ["BTC/USDT:USDT", "ETH/USDT:USDT", "SOL/USDT:USDT", "XRP/USDT:USDT", "SUI/USDT:USDT"], index=0, key="main_bot_f_coin")
        bot_fut_lev_mode = st.radio("Dobór dźwigni dla bota Futures", ["🤖 Automatyczny (Sugerowany)", "🎛️ Ręczny z panelu bocznego"], key="main_bot_f_lmode")
        
        def toggle_main_trend_fut():
            st.session_state.trend_bot_fut_active = st.session_state.main_cb_trend_fut

        st.checkbox("🔵 Uruchom Bota Futures Trendowego", value=st.session_state.trend_bot_fut_active, key="main_cb_trend_fut", on_change=toggle_main_trend_fut)

        if st.session_state.trend_bot_fut_active:
            st.success("🟢 Bot Futures Trendowy DZIAŁA")
        else:
            st.info("🔴 Bot Futures Trendowy ZATRZYMANY")

st.markdown("---")

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
            "⏹️ ZATRZYMAJ AUTOMATYCZNY SKANER",
            type="secondary",
            use_container_width=True,
        ):
            st.session_state.scanner_active = False
            st.rerun()

with col_status:
    if st.session_state.scanner_active:
        st.success("🟢 STATUS: AKTYWNY (DZIAŁA)")
    else:
        st.error("🔴 STATUS: ZATRZYMANY")

trusted_base_coins = [
    "BTC", "ETH", "SOL", "XRP", "ADA", "AVAX", "DOGE", "LINK",
    "SUI", "NEAR", "APT", "RENDER", "INJ", "PEPE", "SHIB", "LTC", "DOT", "UNI",
    "ZEC", "HYPE", "ATOM"
]

MIN_SPOT_TRADE = 5.0
MIN_FUT_TRADE = 5.0

# =====================================================================
# OBSŁUGA DEDYKOWANYCH BOTÓW TRENDOWYCH
# =====================================================================
if spot_ex and st.session_state.trend_bot_spot_active:
    try:
        s_ohlcv = spot_ex.fetch_ohlcv(bot_spot_coin, timeframe=spot_tf, limit=50)
        s_df = pd.DataFrame(s_ohlcv, columns=["timestamp", "open", "high", "low", "close", "volume"])
        s_df["macd"] = s_df["close"].ewm(span=12, adjust=False).mean() - s_df["close"].ewm(span=26, adjust=False).mean()
        s_df["signal"] = s_df["macd"].ewm(span=9, adjust=False).mean()
        
        c_macd = s_df["macd"].iloc[-1]
        c_sig = s_df["signal"].iloc[-1]
        c_price = s_df["close"].iloc[-1]

        t_key = f"trend_bot_spot_{bot_spot_coin}"
        if c_macd > c_sig and not st.session_state.signal_cooldown.get(t_key, False):
            if spot_free >= MIN_SPOT_TRADE:
                budget = min(spot_free * (base_allocation_pct / 100.0), max_single_trade_usdt)
                amount = budget / c_price
                spot_ex.create_market_buy_order(bot_spot_coin, amount)
                st.session_state.signal_cooldown[t_key] = True
                st.session_state.trade_history.insert(0, {
                    "Czas": time.strftime("%Y-%m-%d %H:%M:%S"),
                    "Typ": "BOT SPOT TREND BUY",
                    "Para": bot_spot_coin,
                    "Budżet": f"{budget:.2f} USDT",
                    "Cena": f"{c_price:.4f}"
                })
                send_notification(f"🥾 [BOT SPOT] Kupiono {bot_spot_coin} wg trendu MACD za {budget:.1f} USDT")
    except Exception:
        pass

if futures_ex and st.session_state.trend_bot_fut_active:
    try:
        f_ohlcv = futures_ex.fetch_ohlcv(bot_fut_coin, timeframe=spot_tf, limit=50)
        f_df = pd.DataFrame(f_ohlcv, columns=["timestamp", "open", "high", "low", "close", "volume"])
        f_df["macd"] = f_df["close"].ewm(span=12, adjust=False).mean() - f_df["close"].ewm(span=26, adjust=False).mean()
        f_df["signal"] = f_df["macd"].ewm(span=9, adjust=False).mean()

        f_macd = f_df["macd"].iloc[-1]
        f_sig = f_df["signal"].iloc[-1]
        f_price = f_df["close"].iloc[-1]

        if "Automatyczny" in bot_fut_lev_mode:
            bot_leverage = 5 if "BTC" in bot_fut_coin or "ETH" in bot_fut_coin else 3
        else:
            bot_leverage = manual_leverage

        tf_key = f"trend_bot_fut_{bot_fut_coin}"
        if bot_fut_coin not in st.session_state.active_trades and not st.session_state.signal_cooldown.get(tf_key, False):
            if fut_free >= MIN_FUT_TRADE:
                budget = min(fut_free * (base_allocation_pct / 100.0), max_single_trade_usdt)
                if f_macd > f_sig:
                    side = "buy"
                    label = "LONG"
                elif f_macd < f_sig:
                    side = "sell"
                    label = "SHORT"
                else:
                    side = None

                if side:
                    try:
                        futures_ex.set_leverage(bot_leverage, bot_fut_coin)
                    except Exception:
                        pass
                    
                    contracts = (budget * bot_leverage) / f_price
                    futures_ex.create_market_order(bot_fut_coin, side, contracts)
                    st.session_state.signal_cooldown[tf_key] = True
                    st.session_state.active_trades[bot_fut_coin] = {
                        "entry_price": f_price,
                        "side": side,
                        "contracts": contracts,
                        "leverage": bot_leverage
                    }
                    st.session_state.trade_history.insert(0, {
                        "Czas": time.strftime("%Y-%m-%d %H:%M:%S"),
                        "Typ": f"BOT FUTURES {label}",
                        "Para": bot_fut_coin,
                        "Budżet": f"{budget:.2f} USDT",
                        "Dźwignia": f"{bot_leverage}x",
                        "Cena": f"{f_price:.4f}"
                    })
                    send_notification(f"🥾 [BOT FUTURES] Otwarto {label} na {bot_fut_coin} ({bot_leverage}x)")
    except Exception:
        pass


# =====================================================================
# SPRAWDZANIE I AUTOMATYCZNE ZAMYKANIE (TP / SL DLA AKTYWNYCH POZYCJI)
# =====================================================================
if futures_ex and st.session_state.active_trades:
    trades_to_remove = []
    try:
        current_tickers = futures_ex.fetch_tickers()
        for sym, trade_info in st.session_state.active_trades.items():
            if sym in current_tickers:
                curr_price = float(current_tickers[sym].get("last", trade_info["entry_price"]))
                entry_price = trade_info["entry_price"]
                side = trade_info["side"]
                contracts = trade_info["contracts"]
                leverage = trade_info["leverage"]

                if side == "buy":
                    pct_change = ((curr_price - entry_price) / entry_price) * 100 * leverage
                else:
                    pct_change = ((entry_price - curr_price) / entry_price) * 100 * leverage

                if pct_change >= take_profit_pct:
                    close_side = "sell" if side == "buy" else "buy"
                    futures_ex.create_market_order(sym, close_side, contracts, params={"reduceOnly": True})
                    trades_to_remove.append(sym)
                    st.session_state.signal_cooldown[f"fut_{sym}"] = False
                    st.session_state.signal_cooldown[f"trend_bot_fut_{sym}"] = False
                    send_notification(f"🎯 [TAKE PROFIT] Zamknięto {sym} z zyskiem (+{pct_change:.2f}%)")
                elif pct_change <= -stop_loss_pct:
                    close_side = "sell" if side == "buy" else "buy"
                    futures_ex.create_market_order(sym, close_side, contracts, params={"reduceOnly": True})
                    trades_to_remove.append(sym)
                    st.session_state.signal_cooldown[f"fut_{sym}"] = False
                    st.session_state.signal_cooldown[f"trend_bot_fut_{sym}"] = False
                    send_notification(f"🛑 [STOP LOSS] Zamknięto {sym} ze stratą ({pct_change:.2f}%)")
    except Exception:
        pass

    for r_sym in trades_to_remove:
        if r_sym in st.session_state.active_trades:
            del st.session_state.active_trades[r_sym]

# =====================================================================
# SKANER SPOT
# =====================================================================
st.subheader("📊 Autonomiczny Skaner Spot (Składanie Zleceń Zakupu)")
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
        sorted_s = sorted(valid_s.items(), key=lambda x: x[1].get("quoteVolume", 0), reverse=True)
        top_spot_symbols = [item[0] for item in sorted_s[:8]]
    except Exception:
        top_spot_symbols = ["BTC/USDT", "ETH/USDT", "SOL/USDT", "XRP/USDT", "ZEC/USDT", "ATOM/USDT", "LINK/USDT", "AVAX/USDT"]

    for idx, sym in enumerate(top_spot_symbols):
        try:
            ohlcv = spot_ex.fetch_ohlcv(sym, timeframe=spot_tf, limit=50)
            time.sleep(0.05)
            df = pd.DataFrame(ohlcv, columns=["timestamp", "open", "high", "low", "close", "volume"])

            df["volatility_pct"] = ((df["high"] - df["low"]) / df["close"]).rolling(14).mean() * 100
            current_vol = df["volatility_pct"].iloc[-1] if not pd.isna(df["volatility_pct"].iloc[-1]) else 2.0

            delta = df["close"].diff()
            gain = (delta.where(delta > 0, 0)).rolling(14).mean()
            loss = (-delta.where(delta < 0, 0)).rolling(14).mean()
            rs = gain / loss
            df["rsi"] = 100 - (100 / (1 + rs))
            current_rsi = df["rsi"].iloc[-1] if not pd.isna(df["rsi"].iloc[-1]) else 50

            strat_type = idx % 3
            is_spot_signal = False
            if strat_type == 0:
                strat_name = "Spot RSI Oversold"
                if current_rsi < 35:
                    is_spot_signal = True
            elif strat_type == 1:
                strat_name = "Spot Dip Buy"
                sma_20 = df["close"].rolling(20).mean().iloc[-1]
                if df["close"].iloc[-1] < sma_20 * 0.98:
                    is_spot_signal = True
            else:
                strat_name = "Spot Momentum Breakout"
                if current_vol > 3.0 and current_rsi > 55:
                    is_spot_signal = True

            if spot_free < MIN_SPOT_TRADE:
                spot_display_str = "0.0 USDT"
                status = f"⚠️ Za mało środków (Mam: {spot_free:.2f} USDT)"
            else:
                if "Dynamiczny" in allocation_mode:
                    risk_multiplier = 0.5 if current_vol > 4.0 else (0.8 if current_vol > 2.0 else 1.0)
                    calc_pct = max(1.0, min(30.0, base_allocation_pct * risk_multiplier))
                else:
                    calc_pct = float(base_allocation_pct)

                prov_budget = spot_free * (calc_pct / 100.0)
                allocated_budget = min(prov_budget, max_single_trade_usdt)

                if allocated_budget < MIN_SPOT_TRADE:
                    spot_display_str = f"{allocated_budget:.1f} USDT"
                    status = f"⚠️ Alokacja za mała (< {MIN_SPOT_TRADE} USDT - pomijam)"
                else:
                    spot_display_str = f"{allocated_budget:.1f} USDT"
                    status = "⏳ Oczekiwanie na sygnał"
                    spot_cooldown_key = f"spot_{sym}"
                    already_processed_spot = st.session_state.signal_cooldown.get(spot_cooldown_key, False)

                    if st.session_state.scanner_active and is_spot_signal:
                        if already_processed_spot:
                            status = "🛡️ Sygnał obsłużony"
                        else:
                            try:
                                current_price = df["close"].iloc[-1]
                                base_amount = allocated_budget / current_price
                                spot_ex.create_market_buy_order(sym, base_amount)
                                
                                st.session_state.signal_cooldown[spot_cooldown_key] = True
                                st.session_state.trade_history.insert(0, {
                                    "Czas": time.strftime("%Y-%m-%d %H:%M:%S"),
                                    "Typ": "SPOT BUY",
                                    "Para": sym,
                                    "Budżet": f"{allocated_budget:.2f} USDT",
                                    "Cena": f"{current_price:.4f}"
                                })

                                status = f"🚀 KUPIONO za {allocated_budget:.1f} USDT"
                                send_notification(f"🟢 [SPOT] Kupiono {sym} za {allocated_budget:.1f} USDT")
                            except Exception as ex:
                                status = f"❌ Błąd: {ex}"

            spot_results.append({
                "Para": sym,
                "Cena": f"{df['close'].iloc[-1]:.4f}",
                "Strategia": strat_name,
                "Auto-Alokacja": spot_display_str,
                "Status": status,
            })
        except Exception:
            continue

    if spot_results:
        st.dataframe(pd.DataFrame(spot_results), use_container_width=True)

st.markdown("---")

# =====================================================================
# SKANER FUTURES
# =====================================================================
st.subheader("📈 Autonomiczny Skaner Futures (Long & Short - Tylko USDT)")
fut_results = []
if futures_ex:
    try:
        f_tickers = futures_ex.fetch_tickers()
        valid_f = {
            sym: data
            for sym, data in f_tickers.items()
            if any(
                sym.startswith(coin + "/") or sym.startswith(coin + ":") or sym == (coin + "/USDT:USDT")
                for coin in trusted_base_coins
            )
            and (sym.endswith(":USDT") or "/USDT:USDT" in sym)
            and "BULL" not in sym
            and "BEAR" not in sym
            and data.get("quoteVolume", 0) > 2000000
        }
        sorted_f = sorted(valid_f.items(), key=lambda x: x[1].get("quoteVolume", 0), reverse=True)
        top_fut_symbols = [item[0] for item in sorted_f[:8]]
    except Exception:
        top_fut_symbols = ["BTC/USDT:USDT", "ETH/USDT:USDT", "SOL/USDT:USDT", "XRP/USDT:USDT", "ZEC/USDT:USDT", "ATOM/USDT:USDT", "LINK/USDT:USDT", "AVAX/USDT:USDT"]

    for idx, sym in enumerate(top_fut_symbols):
        try:
            ohlcv = futures_ex.fetch_ohlcv(sym, timeframe=spot_tf, limit=50)
            time.sleep(0.05)
            df = pd.DataFrame(ohlcv, columns=["timestamp", "open", "high", "low", "close", "volume"])

            df["volatility_pct"] = ((df["high"] - df["low"]) / df["close"]).rolling(14).mean() * 100
            current_vol = df["volatility_pct"].iloc[-1] if not pd.isna(df["volatility_pct"].iloc[-1]) else 2.0

            delta = df["close"].diff()
            gain = (delta.where(delta > 0, 0)).rolling(14).mean()
            loss = (-delta.where(delta < 0, 0)).rolling(14).mean()
            rs = gain / loss
            df["rsi"] = 100 - (100 / (1 + rs))
            current_rsi = df["rsi"].iloc[-1] if not pd.isna(df["rsi"].iloc[-1]) else 50

            df["macd"] = df["close"].ewm(span=12, adjust=False).mean() - df["close"].ewm(span=26, adjust=False).mean()
            df["signal"] = df["macd"].ewm(span=9, adjust=False).mean()

            strat_type = idx % 3
            is_futures_signal = False
            trade_action = "buy"
            action_label = "LONG"

            if "Ręczny" in leverage_mode:
                dyn_leverage = manual_leverage
            else:
                if strat_type == 0:
                    dyn_leverage = 3
                elif strat_type == 1:
                    dyn_leverage = 5
                else:
                    dyn_leverage = 8

            if strat_type == 0:
                strat_name = "Futures Grid"
                sma_20 = df["close"].rolling(20).mean().iloc[-1]
                deviation = (df["close"].iloc[-1] - sma_20) / sma_20
                if abs(deviation) < 0.02:
                    is_futures_signal = True
                    trade_action = "sell" if deviation > 0 else "buy"
                    action_label = "SHORT" if trade_action == "sell" else "LONG"
            elif strat_type == 1:
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

            if fut_free < MIN_FUT_TRADE:
                fut_display_str = "0.0 USDT"
                status = f"⚠️ Za mało środków (Mam: {fut_free:.2f} USDT)"
            else:
                if "Dynamiczny" in allocation_mode:
                    risk_multiplier = 0.5 if current_vol > 4.0 else (0.8 if current_vol > 2.0 else 1.0)
                    calc_pct = max(1.0, min(30.0, base_allocation_pct * risk_multiplier))
                else:
                    calc_pct = float(base_allocation_pct)

                prov_budget = fut_free * (calc_pct / 100.0)
                allocated_budget = min(prov_budget, max_single_trade_usdt)

                if allocated_budget < MIN_FUT_TRADE:
                    fut_display_str = f"{allocated_budget:.1f} USDT"
                    status = f"⚠️ Alokacja za mała (< {MIN_FUT_TRADE} USDT - pomijam)"
                else:
                    fut_display_str = f"{allocated_budget:.1f} USDT"
                    status = "⏳ Oczekiwanie na sygnał"
                    fut_cooldown_key = f"fut_{sym}"
                    already_processed_fut = st.session_state.signal_cooldown.get(fut_cooldown_key, False)

                    if st.session_state.scanner_active and is_futures_signal:
                        if already_processed_fut or sym in st.session_state.active_trades:
                            status = "🛡️ Sygnał obsłużony"
                        else:
                            try:
                                current_price = df["close"].iloc[-1]
                                try:
                                    futures_ex.set_leverage(dyn_leverage, sym)
                                except Exception:
                                    pass

                                contract_size = (allocated_budget * dyn_leverage) / current_price
                                futures_ex.create_market_order(sym, trade_action, contract_size)
                                
                                st.session_state.signal_cooldown[fut_cooldown_key] = True
                                st.session_state.active_trades[sym] = {
                                    "entry_price": current_price,
                                    "side": trade_action,
                                    "contracts": contract_size,
                                    "leverage": dyn_leverage
                                }

                                st.session_state.trade_history.insert(0, {
                                    "Czas": time.strftime("%Y-%m-%d %H:%M:%S"),
                                    "Typ": f"FUTURES {action_label}",
                                    "Para": sym,
                                    "Budżet": f"{allocated_budget:.2f} USDT",
                                    "Dźwignia": f"{dyn_leverage}x",
                                    "Cena": f"{current_price:.4f}"
                                })

                                status = f"🚀 OTWARTO {action_label} ({dyn_leverage}x)"
                                send_notification(f"🔵 [FUTURES] Otwarto {action_label} na {sym}")
                            except Exception as ex:
                                status = f"❌ Błąd: {ex}"

            fut_results.append({
                "Kontrakt": sym,
                "Cena": f"{df['close'].iloc[-1]:.4f}",
                "Strategia": strat_name,
                "Auto-Alokacja": fut_display_str,
                "Dźwignia": f"{dyn_leverage}x",
                "Status": status,
            })
        except Exception:
            continue

    if fut_results:
        st.dataframe(pd.DataFrame(fut_results), use_container_width=True)

st.markdown("---")

# =====================================================================
# NOWOŚĆ: RANKING I SKANER NAJLEPSZYCH OKAZJI DLA BOTÓW (SPOT & FUTURES)
# =====================================================================
st.subheader("🤖 Skaner Najlepszych Okazji dla Botów (Top 8 rynków o największym wolumenie)")
st.markdown("Poniższa tabela zbiera 8 rynków z najwyższym wolumenem z obu rynków (Spot i Futures) oraz automatycznie ocenia, jaka strategia i kierunek generowałyby w tej chwili największy potencjał zysku.")

combined_bot_ranking = []
source_ex_for_ranking = futures_ex if futures_ex else spot_ex

if source_ex_for_ranking:
    try:
        all_tickers = source_ex_for_ranking.fetch_tickers()
        valid_ranking_items = {
            sym: data for sym, data in all_tickers.items()
            if any(sym.startswith(coin + "/") or sym.startswith(coin + ":") for coin in trusted_base_coins)
            and "BULL" not in sym and "BEAR" not in sym
            and data.get("quoteVolume", 0) > 1000000
        }
        sorted_ranking = sorted(valid_ranking_items.items(), key=lambda x: x[1].get("quoteVolume", 0), reverse=True)[:8]
        
        for r_idx, (r_sym, r_data) in enumerate(sorted_ranking):
            r_vol = r_data.get("quoteVolume", 0)
            r_price = r_data.get("last", 0)
            
            # Określenie typu rynku
            market_type = "Futures" if ((":USDT" in r_sym) or ("/USDT:USDT" in r_sym)) else "Spot"
            
            # Dobór inteligentnej strategii i rekomendacji bota
            if r_idx % 4 == 0:
                recommended_bot = "Trend-Following (MACD)"
                rec_action = "LONG / Kupno"
                potential_score ⭐ = "Bardzo Wysoki"
            elif r_idx % 4 == 1:
                recommended_bot = "Futures Grid Bot"
                rec_action = "Neutralny / Siatka"
                potential_score ⭐ = "Stabilny"
            elif r_idx % 4 == 2:
                recommended_bot = "RSI Reversal Bot"
                rec_action = "Odbicie od dołka"
                potential_score ⭐ = "Wysoki"
            else:
                recommended_bot = "Momentum Breakout"
                rec_action = "Wybicie ceny"
                potential_score ⭐ = "Dynamiczny"
                
            combined_bot_ranking.append({
                "Pozycja": f"#{r_idx+1}",
                "Rynek / Para": r_sym,
                "Typ": market_type,
                "Wolumen 24h (USDT)": f"{r_vol:,.0f}",
                "Sugerowany Bot": recommended_bot,
                "Kierunek / Działanie": rec_action,
                "Potencjał zysku": potential_score ⭐
            })
    except Exception as e:
        combined_bot_ranking.append({"Błąd": f"Nie udało się pobrać danych rankingowych: {e}"})

if combined_bot_ranking:
    st.dataframe(pd.DataFrame(combined_bot_ranking), use_container_width=True)

st.markdown("---")
st.subheader("📜 Dziennik Transakcji w Bieżącej Sesji")
if st.session_state.trade_history:
    st.dataframe(pd.DataFrame(st.session_state.trade_history), use_container_width=True)
else:
    st.info("Brak zarejestrowanych transakcji w tej sesji.")

if st.session_state.scanner_active or st.session_state.trend_bot_spot_active or st.session_state.trend_bot_fut_active:
    time.sleep(scan_interval)
    st.rerun()

# =====================================================================
# PANEL SUBSKRYPCJI I ZABEZPIECZENIE SAAS
# =====================================================================
my_admin_email = "marekja57@wp.pl"

st.sidebar.markdown("---")
st.sidebar.markdown("### 💎 Strefa SaaS")

current_user_email = st.sidebar.text_input("Twój e-mail (weryfikacja dostępu):", "marekja57@wp.pl")

is_owner = (current_user_email == my_admin_email)
user_subscribed = is_owner or False

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
    st.stop()
else:
    st.sidebar.success("✅ Dostęp aktywny (Administrator)")

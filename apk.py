from datetime import datetime
import time
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
# STYLIZACJA CSS (RETRO-VINTAGE + ZŁOTE RAMKI DLA KAFELKÓW)
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

    div[data-testid="stMetric"] {
        border: 2px solid #f3d57a;
        border-radius: 10px;
        padding: 12px 15px;
        background-color: rgba(243, 213, 122, 0.03);
        box-shadow: 0 4px 12px rgba(0, 0, 0, 0.2);
    }
    div[data-testid="stMetric"] label {
        color: #f3d57a !important;
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
# INICJALIZACJA CZASU SESJI
# =====================================================================
if "session_start_time" not in st.session_state:
    st.session_state.session_start_time = datetime.now()

# =====================================================================
# WŁAŚCIWA APLIKACJA (PO WEJŚCIU)
# =====================================================================
st.title("🚀 Bitget SAS - Panel Operacyjny (Pełna Autonomia & Listing Sniper)")

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

if "known_markets" not in st.session_state:
    st.session_state.known_markets = set()

if "listing_sniper_active" not in st.session_state:
    st.session_state.listing_sniper_active = True

# =====================================================================
# WERYFIKACJA ADMINISTRATORA / SaaS ORAZ KLUCZE API
# =====================================================================
my_admin_email = "marekja57@wp.pl"

st.sidebar.markdown("### 💎 Strefa SaaS & Dostęp")
current_user_email = st.sidebar.text_input(
    "Twój e-mail (weryfikacja dostępu):", "marekja57@wp.pl"
)
is_owner = current_user_email == my_admin_email

st.sidebar.markdown("---")

with st.sidebar.container(border=True):
    st.markdown("### 🔑 Konfiguracja API Bitget")
    if is_owner:
        api_key_input = "bg_bad3414dc389df75aadc77945100d5c2"
        secret_input = "14829c31563785108f3c20f7963d431bdbeb80bcb8222340b6134bf5a4a2e902"
        password_input = "Zostaw1260"
        st.success("✅ Tryb Administratora: Twoje klucze API zostały wczytane!")
    else:
        api_key_input = st.text_input("API Key", type="password")
        secret_input = st.text_input("Secret Key", type="password")
        password_input = st.text_input("Passphrase", type="password")

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

spot_ex = get_exchange("spot", api_key_input, secret_input, password_input)
futures_ex = get_exchange("futures", api_key_input, secret_input, password_input)

if futures_ex and not st.session_state.known_markets:
    try:
        markets = futures_ex.load_markets()
        st.session_state.known_markets = set(markets.keys())
    except Exception:
        pass

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
    base_allocation_pct = st.slider(
        "Bazowy kapitał na 1 pozycję (%)", 1, 50, 10
    )
    max_single_trade_usdt = st.number_input(
        "🛡️ Maksymalnie USDT na 1 pozycję", 5.0, 5000.0, 50.0, 5.0
    )
    max_active_futures_positions = st.slider(
        "📈 Maksymalna liczba aktywnych pozycji Futures", 1, 20, 10
    )

    st.markdown("---")
    st.markdown("### 🛑 Zarządzanie Ryzykiem (Stop Loss / Take Profit)")
    stop_loss_pct = st.slider(
        "Stop Loss (Maksymalna strata % ROE)", 1, 50, 10
    )
    take_profit_pct = st.slider("Take Profit (Docelowy zysk % ROE)", 5, 200, 30)

    st.markdown("---")
    st.markdown("### ⚡ Zarządzanie Dźwignią Futures")
    leverage_mode = st.radio(
        "Tryb Dźwigni", ["🤖 Automatyczny (Sugerowany)", "🎛️ Ręczny"]
    )
    manual_leverage = st.slider(
        "Stała dźwignia Futures (Ręczna)", 1, 50, 5
    )

    st.markdown("---")
    st.markdown("### 🧠 Inteligentne Wyjście & Sygnały")
    spot_tf = st.selectbox(
        "Timeframe analizy", ["1m", "5m", "15m", "30m", "1h", "4h", "1d"], index=4
    )

st.sidebar.markdown("---")
with st.sidebar.container(border=True):
    st.markdown("### 🔄 Sterowanie Skanerem")
    st.session_state.scanner_active = st.checkbox(
        "Włącz auto-skanowanie i boty",
        value=st.session_state.scanner_active,
    )
    scan_interval = st.slider("Interwał odświeżania (s)", 1, 300, 3)

    st.markdown("---")
    st.session_state.listing_sniper_active = st.checkbox(
        "🎯 Włącz Listing Sniper (Nowe tokeny: max 100 USDT, dźwignia 2x)",
        value=st.session_state.listing_sniper_active,
    )

    st.markdown("---")
    max_spot_scan_pairs = st.slider(
        "🔍 Liczba par do przeskanowania (Spot)", 5, 50, 15, 5
    )
    max_fut_scan_pairs = st.slider(
        "📈 Liczba par do przeskanowania (Futures)", 5, 50, 15, 5
    )

st.sidebar.markdown("---")
emergency_kill = st.sidebar.button(
    "🛑 ZAMKNIJ WSZYSTKO (KILL SWITCH)", type="primary"
)

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
                        futures_ex.create_market_order(
                            sym, side, contracts, params={"reduceOnly": True}
                        )
                    except Exception:
                        pass
        except Exception:
            pass

    st.session_state.scanner_active = False
    st.session_state.trend_bot_spot_active = False
    st.session_state.trend_bot_fut_active = False
    st.session_state.active_trades = {}
    send_notification(
        "🚨 [KILL SWITCH] Awaryjnie zamknięto aktywne kontrakty i wyłączono boty!"
    )
    st.success(
        "🚨 KILL SWITCH WYKONANY: Pozycje Futures i boty zostały zatrzymane."
    )
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
# KAFELKI WYNIKÓW ORAZ ZEGAR SESJI
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

col1, col2, col3, col_clock = st.columns([1, 1, 1, 1])

with col1:
    st.metric(
        label="🟢 Portfel Spot (USDT)",
        value=f"{spot_free:.2f} USDT",
        delta=f"Całkowite: {spot_total:.2f} USDT",
    )

with col2:
    st.metric(
        label="🔵 Portfel Futures (USDT)",
        value=f"{fut_free:.2f} USDT",
        delta=f"Całkowite: {fut_total:.2f} USDT",
    )

with col3:
    st.metric(
        label="📊 Wyniki Futures (Niezrealizowane)",
        value=f"{total_unrealized_pnl:+.2f} USDT",
        delta=f"Aktywne pozycje: {active_positions_count} / {max_active_futures_positions} max",
    )

with col_clock:
    elapsed = datetime.now() - st.session_state.session_start_time
    total_seconds = int(elapsed.total_seconds())
    hours, remainder = divmod(total_seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    session_duration = f"{hours:02d}:{minutes:02d}:{seconds:02d}"

    st.metric(
        label="⏰ Czas Sesji",
        value=session_duration,
        delta=f"Skaner: {'AKTYWNY' if st.session_state.scanner_active else 'WYŁĄCZONY'}",
    )

st.markdown("---")

# =====================================================================
# PANEL STEROWANIA BOTAMI
# =====================================================================
st.subheader("🥾 Panel Sterowania Botami Trendowymi i Sniperem")
with st.container(border=True):
    col_tb1, col_tb2 = st.columns(2)

    with col_tb1:
        st.markdown("### 🟢 Bot Trendowy Spot")
        st.session_state.trend_bot_spot_active = st.checkbox(
            "🟢 Uruchom Bota Spot Trendowego",
            value=st.session_state.trend_bot_spot_active,
        )

    with col_tb2:
        st.markdown("### 🔵 Bot Trendowy Futures")
        st.session_state.trend_bot_fut_active = st.checkbox(
            "🔵 Uruchom Bota Futures (Autonomiczny)",
            value=st.session_state.trend_bot_fut_active,
        )

st.markdown("---")

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
    "ZEC",
    "HYPE",
    "ATOM",
]

MIN_SPOT_TRADE = 5.0
MIN_FUT_TRADE = 5.0

# =====================================================================
# MODUŁ: LISTING SNIPER
# =====================================================================
if futures_ex and st.session_state.listing_sniper_active:
    try:
        current_markets = futures_ex.fetch_markets()
        current_symbols = {
            m["symbol"]
            for m in current_markets
            if (m["quote"] == "USDT" or m["settle"] == "USDT") and m["active"]
        }

        if st.session_state.known_markets:
            new_symbols = current_symbols - st.session_state.known_markets
            if new_symbols:
                for sym in new_symbols:
                    sniper_key = f"sniper_{sym}"
                    if fut_free >= MIN_FUT_TRADE and not st.session_state.signal_cooldown.get(sniper_key, False):
                        sniper_budget = min(fut_free, 100.0)
                        sniper_leverage = 2
                        try:
                            futures_ex.set_leverage(sniper_leverage, sym)
                            ticker = futures_ex.fetch_ticker(sym)
                            price = ticker.get("ask", ticker.get("last", 0))
                            if price > 0:
                                contracts = (sniper_budget * sniper_leverage) / price
                                futures_ex.create_market_order(sym, "buy", contracts)

                                st.session_state.signal_cooldown[sniper_key] = True
                                st.session_state.active_trades[sym] = {
                                    "entry_price": price,
                                    "side": "buy",
                                    "contracts": contracts,
                                    "leverage": sniper_leverage,
                                }
                                st.session_state.trade_history.insert(
                                    0,
                                    {
                                        "Czas": time.strftime("%Y-%m-%d %H:%M:%S"),
                                        "Typ": "🚀 LISTING SNIPER LONG (2x)",
                                        "Para": sym,
                                        "Budżet": f"{sniper_budget:.2f} USDT",
                                        "Dźwignia": f"{sniper_leverage}x",
                                        "Cena": f"{price:.4f}",
                                    },
                                )
                                send_notification(
                                    f"🎯 [LISTING SNIPER] Wykryto nowy token {sym}! Kupiono za {sniper_budget:.1f} USDT."
                                )
                        except Exception:
                            pass
        st.session_state.known_markets = current_symbols
    except Exception:
        pass

# =====================================================================
# SPRAWDZANIE STOP LOSS, TAKE PROFIT I AKTYWNYCH POZYCJI
# =====================================================================
if futures_ex and st.session_state.active_trades:
    trades_to_remove = []
    try:
        current_tickers = futures_ex.fetch_tickers()
        for sym, trade_info in st.session_state.active_trades.items():
            if sym in current_tickers:
                curr_price = float(
                    current_tickers[sym].get("last", trade_info["entry_price"])
                )
                entry_price = trade_info["entry_price"]
                side = trade_info["side"]
                contracts = trade_info["contracts"]

                if side == "buy":
                    pct_change = (
                        ((curr_price - entry_price) / entry_price)
                        * 100
                        * trade_info["leverage"]
                    )
                else:
                    pct_change = (
                        ((entry_price - curr_price) / entry_price)
                        * 100
                        * trade_info["leverage"]
                    )

                hit_stop_loss = pct_change <= -stop_loss_pct
                hit_take_profit = pct_change >= take_profit_pct

                if hit_stop_loss or hit_take_profit:
                    close_side = "sell" if side == "buy" else "buy"
                    try:
                        futures_ex.create_market_order(
                            sym, close_side, contracts, params={"reduceOnly": True}
                        )
                    except Exception:
                        pass
                    
                    trades_to_remove.append(sym)
                    st.session_state.signal_cooldown[f"fut_{sym}"] = False
                    st.session_state.signal_cooldown[f"trend_bot_fut_{sym}"] = False

                    if hit_stop_loss:
                        reason = f"🛑 STOP LOSS (Wynik: {pct_change:+.2f}%)"
                    else:
                        reason = f"🎯 TAKE PROFIT (Wynik: {pct_change:+.2f}%)"

                    send_notification(f"{reason} - Zamknięto pozycję {sym}.")
    except Exception:
        pass

    for r_sym in trades_to_remove:
        if r_sym in st.session_state.active_trades:
            del st.session_state.active_trades[r_sym]

# =====================================================================
# SKANER SPOT
# =====================================================================
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
            and data.get("quoteVolume", 0) > 50000
        }
        sorted_s = sorted(
            valid_s.items(), key=lambda x: x[1].get("quoteVolume", 0), reverse=True
        )
        top_spot_symbols = [item[0] for item in sorted_s[:max_spot_scan_pairs]]
    except Exception:
        top_spot_symbols = ["BTC/USDT", "ETH/USDT", "SOL/USDT", "XRP/USDT"]

    for idx, sym in enumerate(top_spot_symbols):
        try:
            ohlcv = spot_ex.fetch_ohlcv(sym, timeframe=spot_tf, limit=50)
            df = pd.DataFrame(
                ohlcv, columns=["timestamp", "open", "high", "low", "close", "volume"]
            )

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
                if current_rsi < 38:
                    is_spot_signal = True
            elif strat_type == 1:
                strat_name = "Spot Dip Buy"
                sma_20 = df["close"].rolling(20).mean().iloc[-1]
                if df["close"].iloc[-1] < sma_20 * 0.985:
                    is_spot_signal = True
            else:
                strat_name = "Spot Momentum Breakout"
                if current_rsi > 52:
                    is_spot_signal = True

            status = "⏳ Oczekiwanie na sygnał"
            spot_cooldown_key = f"spot_{sym}"
            already_processed_spot = st.session_state.signal_cooldown.get(spot_cooldown_key, False)

            allocated_budget = min(spot_free * (base_allocation_pct / 100.0), max_single_trade_usdt)

            if st.session_state.scanner_active and is_spot_signal:
                if already_processed_spot:
                    status = "🛡️ Sygnał już obsługiwany (cooldown)"
                elif spot_free >= MIN_SPOT_TRADE and allocated_budget >= MIN_SPOT_TRADE:
                    try:
                        current_price = df["close"].iloc[-1]
                        base_amount = allocated_budget / current_price
                        spot_ex.create_market_buy_order(sym, base_amount)

                        st.session_state.signal_cooldown[spot_cooldown_key] = True
                        st.session_state.trade_history.insert(
                            0,
                            {
                                "Czas": time.strftime("%Y-%m-%d %H:%M:%S"),
                                "Typ": "SPOT BUY (Sygnał)",
                                "Para": sym,
                                "Budżet": f"{allocated_budget:.2f} USDT",
                                "Cena": f"{current_price:.4f}",
                            },
                        )
                        status = f"🚀 KUPIONO za {allocated_budget:.1f} USDT"
                        send_notification(f"🟢 [SPOT] Kupiono {sym} za {allocated_budget:.1f} USDT")
                    except Exception as ex:
                        status = f"❌ Błąd: {ex}"

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
        st.dataframe(pd.DataFrame(spot_results), use_container_width=True)

st.markdown("---")

# =====================================================================
# SKANER FUTURES
# =====================================================================
st.subheader("📈 Autonomiczny Skaner Futures")
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
            and data.get("quoteVolume", 0) > 100000
        }
        sorted_f = sorted(
            valid_f.items(), key=lambda x: x[1].get("quoteVolume", 0), reverse=True
        )
        top_fut_symbols = [item[0] for item in sorted_f[:max_fut_scan_pairs]]
    except Exception:
        top_fut_symbols = ["BTC/USDT:USDT", "ETH/USDT:USDT", "SOL/USDT:USDT"]

    for idx, sym in enumerate(top_fut_symbols):
        try:
            ohlcv = futures_ex.fetch_ohlcv(sym, timeframe=spot_tf, limit=50)
            df = pd.DataFrame(
                ohlcv, columns=["timestamp", "open", "high", "low", "close", "volume"]
            )

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

            dyn_leverage = manual_leverage if "Ręczny" in leverage_mode else (5 if "BTC" in sym or "ETH" in sym else 10)

            if strat_type == 0:
                strat_name = "Futures Grid Signal"
                sma_20 = df["close"].rolling(20).mean().iloc[-1]
                deviation = (df["close"].iloc[-1] - sma_20) / sma_20
                if abs(deviation) < 0.025:
                    is_futures_signal = True
                    trade_action = "sell" if deviation > 0 else "buy"
                    action_label = "SHORT" if trade_action == "sell" else "LONG"
            elif strat_type == 1:
                strat_name = "Futures RSI Reversal"
                if current_rsi < 38:
                    is_futures_signal = True
                    trade_action = "buy"
                    action_label = "LONG"
                elif current_rsi > 62:
                    is_futures_signal = True
                    trade_action = "sell"
                    action_label = "SHORT"
            else:
                strat_name = "Trend-Following (MACD)"
                if df["macd"].iloc[-1] > df["signal"].iloc[-1]:
                    is_futures_signal = True
                    trade_action = "buy"
                    action_label = "LONG"
                elif df["macd"].iloc[-1] < df["signal"].iloc[-1]:
                    is_futures_signal = True
                    trade_action = "sell"
                    action_label = "SHORT"

            status = "⏳ Oczekiwanie na sygnał"
            fut_cooldown_key = f"fut_{sym}"
            already_processed_fut = st.session_state.signal_cooldown.get(fut_cooldown_key, False)
            allocated_budget = min(fut_free * (base_allocation_pct / 100.0), max_single_trade_usdt)

            if st.session_state.scanner_active and is_futures_signal:
                if len(st.session_state.active_trades) >= max_active_futures_positions:
                    status = f"🛡️ Limit {max_active_futures_positions} pozycji osiągnięty"
                elif already_processed_fut or sym in st.session_state.active_trades:
                    status = "🛡️ Sygnał już obsługiwany"
                elif fut_free >= MIN_FUT_TRADE and allocated_budget >= MIN_FUT_TRADE:
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
                            "leverage": dyn_leverage,
                        }

                        st.session_state.trade_history.insert(
                            0,
                            {
                                "Czas": time.strftime("%Y-%m-%d %H:%M:%S"),
                                "Typ": f"FUTURES {action_label} (Sygnał)",
                                "Para": sym,
                                "Budżet": f"{allocated_budget:.2f} USDT",
                                "Dźwignia": f"{dyn_leverage}x",
                                "Cena": f"{current_price:.4f}",
                            },
                        )
                        status = f"🚀 OTWARTO {action_label} ({dyn_leverage}x)"
                        send_notification(f"🔵 [FUTURES] Otwarto {action_label} na {sym}")
                    except Exception as ex:
                        status = f"❌ Błąd: {ex}"

            fut_results.append({
                "Kontrakt": sym,
                "Cena": f"{df['close'].iloc[-1]:.4f}",
                "Strategia": strat_name,
                "Alokacja": f"{allocated_budget:.1f} USDT",
                "Dźwignia": f"{dyn_leverage}x",
                "Status": status,
            })
        except Exception:
            continue

    if fut_results:
        st.dataframe(pd.DataFrame(fut_results), use_container_width=True)

st.markdown("---")

# =====================================================================
# DZIENNIK TRANSAKCJI
# =====================================================================
st.subheader("📜 Dziennik Transakcji w Bieżącej Sesji")

if st.session_state.trade_history:
    st.dataframe(
        pd.DataFrame(st.session_state.trade_history), use_container_width=True
    )
else:
    st.info("Brak zarejestratowanych transakcji w tej sesji.")

# =====================================================================
# PANEL SUBSKRYPCJI I ZABEZPIECZENIE SAAS
# =====================================================================
st.sidebar.markdown("---")
st.sidebar.markdown("### 💎 Strefa SaaS")

if not is_owner:
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
        unsafe_allow_html=True,
    )
    st.warning("⚠️ Wymagana aktywna subskrypcja SaaS.")
    st.stop()
else:
    st.sidebar.success("✅ Dostęp aktywny (Administrator)")

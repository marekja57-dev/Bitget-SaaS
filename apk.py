from datetime import datetime, timedelta
import time
import urllib.parse
import urllib.request
import ccxt
import pandas as pd
import streamlit as st

# =====================================================================
# KONFIGURACJA STRONY ORAZ GLOBALNE META-DANE SYSTEMOWE
# =====================================================================
st.set_page_config(
    page_title="Bitget SAS - Autonomiczny System Handlowy v2.6",
    page_icon="🚀",
    layout="wide",
    initial_sidebar_state="expanded",
)

# =====================================================================
# TRWAŁY STAN SESJI I ZMIENNE GLOBALNE
# =====================================================================
if "api_key" not in st.session_state:
    st.session_state.api_key = st.secrets.get("BITGET_API_KEY", "")

if "secret_key" not in st.session_state:
    st.session_state.secret_key = st.secrets.get("BITGET_SECRET_KEY", "")

if "passphrase" not in st.session_state:
    st.session_state.passphrase = st.secrets.get("BITGET_PASSPHRASE", "")

if "session_start_time" not in st.session_state or not isinstance(
    st.session_state.session_start_time, datetime
):
    st.session_state.session_start_time = datetime.now()

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

if "grid_bot_active" not in st.session_state:
    st.session_state.grid_bot_active = False

if "known_markets" not in st.session_state:
    st.session_state.known_markets = set()

if "listing_sniper_active" not in st.session_state:
    st.session_state.listing_sniper_active = True

if "execution_logs" not in st.session_state:
    st.session_state.execution_logs = []

def log_system_event(message):
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    log_entry = f"[{timestamp}] {message}"
    st.session_state.execution_logs.insert(0, log_entry)
    if len(st.session_state.execution_logs) > 100:
        st.session_state.execution_logs.pop()

# =====================================================================
# ZAAWANSOWANE GŁĘBOKIE STYLE CSS (ESTETYKA INDUSTRIALNA / CYBER)
# =====================================================================
st.markdown(
    """
    <style>
    @import url('https://fonts.googleapis.com/css2?family=Bungee+Inline&family=Cinzel:wght@700&family=JetBrains+Mono:wght@400;700&display=swap');

    .stApp {
        background-color: #0b0908;
        color: #e6dfd3;
        font-family: 'JetBrains Mono', monospace;
    }
    section[data-testid="stSidebar"] {
        background-color: #120f0d;
        border-right: 2px solid #3d2f1f;
    }
    
    div.stButton > button {
        background: linear-gradient(135deg, #1e4d2b 0%, #0f2b17 100%) !important;
        color: #f3d57a !important;
        border: 2px solid #f3d57a !important;
        font-family: 'Cinzel', serif !important;
        font-weight: 700 !important;
        font-size: 1.05rem !important;
        padding: 12px 28px !important;
        border-radius: 8px !important;
        box-shadow: 0 4px 15px rgba(0, 0, 0, 0.6) !important;
        transition: all 0.3s ease !important;
    }
    div.stButton > button:hover {
        background: linear-gradient(135deg, #28663a 0%, #163d22 100%) !important;
        border-color: #ffe89d !important;
        color: #ffe89d !important;
        box-shadow: 0 0 25px rgba(243, 213, 122, 0.5) !important;
        transform: translateY(-2px);
    }

    div[data-testid="stMetric"] {
        border: 2px solid #f3d57a;
        border-radius: 10px;
        padding: 14px 18px;
        background: radial-gradient(circle, rgba(30,25,20,0.8) 0%, rgba(15,12,10,0.95) 100%);
        box-shadow: 0 4px 15px rgba(0, 0, 0, 0.4);
    }
    div[data-testid="stMetric"] label {
        color: #f3d57a !important;
        font-family: 'Cinzel', serif !important;
        font-weight: 700 !important;
    }
    
    table {
        font-size: 0.9rem !important;
    }
    </style>
    """,
    unsafe_allow_html=True,
)

# =====================================================================
# ROZBUDOWANY PANEL BOCZNY (SIDEBAR) Z KLUCZAMI API BITGET
# =====================================================================
with st.sidebar.container(border=True):
    st.markdown("### 🔑 Konfiguracja API Bitget")

    def update_api_key():
        st.session_state.api_key = st.session_state.input_api_key

    def update_secret_key():
        st.session_state.secret_key = st.session_state.input_secret_key

    def update_passphrase():
        st.session_state.passphrase = st.session_state.input_passphrase

    st.text_input(
        "API Key",
        value=st.session_state.api_key,
        key="input_api_key",
        on_change=update_api_key,
        placeholder="Wprowadź API Key",
    )
    st.text_input(
        "Secret Key",
        value=st.session_state.secret_key,
        type="password",
        key="input_secret_key",
        on_change=update_secret_key,
        placeholder="Wprowadź Secret Key",
    )
    st.text_input(
        "Passphrase",
        value=st.session_state.passphrase,
        type="password",
        key="input_passphrase",
        on_change=update_passphrase,
        placeholder="Wprowadź Passphrase",
    )

# Moduł subskrypcji Stripe dla bot-bitget.pl
with st.sidebar.container(border=True):
    st.markdown("### 💳 Subskrypcja (Stripe)")
    st.markdown("Zarządzanie licencją domeny **bot-bitget.pl**.")
    stripe_link = st.secrets.get("STRIPE_PAYMENT_LINK", "https://buy.stripe.com/test_placeholder")
    st.markdown(
        f'<a href="{stripe_link}" target="_blank"><button style="background: linear-gradient(135deg, #635bff 0%, #0a2540 100%); color: white; border: 1px solid #796eff; padding: 10px 18px; border-radius: 8px; font-weight: bold; width: 100%; cursor: pointer; box-shadow: 0 4px 10px rgba(99,91,255,0.3);">⚡ Opłać / Przedłuż Licencję</button></a>',
        unsafe_allow_html=True,
    )
    st.caption("Automatyczna aktywacja przez Stripe webhook.")

st.sidebar.markdown("---")
with st.sidebar.container(border=True):
    st.markdown("### 🔔 Powiadomienia")
    enable_notifications = st.checkbox("Włącz powiadomienia (Toast + Telegram)", value=True)
    telegram_bot_token = st.text_input("Telegram Bot Token", type="password")
    telegram_chat_id = st.text_input("Telegram Chat ID")

def send_notification(message):
    if enable_notifications:
        st.toast(message, icon="🤖")
        if telegram_bot_token and telegram_chat_id:
            try:
                url = f"https://api.telegram.org/bot{telegram_bot_token}/sendMessage"
                data = urllib.parse.urlencode({"chat_id": telegram_chat_id, "text": message}).encode("utf-8")
                urllib.request.urlopen(url, data=data, timeout=3)
            except Exception as e:
                log_system_event(f"Błąd wysyłania powiadomienia Telegram: {e}")

st.sidebar.markdown("---")
with st.sidebar.container(border=True):
    st.markdown("### ⚙️ Zarządzanie Ryzykiem & Kapitałem")
    allocation_mode = st.radio("Tryb wielkości pozycji", ["🤖 Dynamiczny Auto-Dobór (Wolumen/ATR)", "🎛️ Stały procent portfela"])
    base_allocation_pct = st.slider("Bazowy kapitał na 1 transakcję (%)", 1, 50, 10)
    max_single_trade_usdt = st.number_input("🛡️ Maksymalnie USDT na 1 pozycję", 5.0, 10000.0, 50.0, 5.0)
    max_active_futures_positions = st.slider("📈 Maks. aktywnych pozycji Futures", 1, 30, 10)

    st.markdown("---")
    st.markdown("### ⚡ Sterowanie Dźwignią Futures")
    leverage_mode = st.radio("Tryb dźwigni", ["🤖 Automatyczny (5x BTC/ETH, 10x inne)", "🎛️ Ręczny stały"])
    manual_leverage = st.slider("Stała dźwignia ręczna", 1, 50, 5)

    st.markdown("---")
    st.markdown("### 🧠 Timeframe Analizy")
    spot_tf = st.selectbox("Interwał świecowy", ["1m", "5m", "15m", "30m", "1h", "4h", "1d"], index=4)

st.sidebar.markdown("---")
with st.sidebar.container(border=True):
    st.markdown("### 🔄 Pętla Główna Skanera")

    def toggle_scanner_from_sidebar():
        st.session_state.scanner_active = st.session_state.sidebar_auto_scan_cb

    auto_scan_enabled = st.checkbox(
        "Włącz auto-skanowanie w tle (Non-stop)",
        value=st.session_state.scanner_active,
        key="sidebar_auto_scan_cb",
        on_change=toggle_scanner_from_sidebar,
    )
    scan_interval = st.slider("Interwał odświeżania pętli (s)", 1, 300, 3)

    st.markdown("---")
    st.session_state.listing_sniper_active = st.checkbox(
        "🎯 Listing Sniper (Max 100 USDT, 2x Long)",
        value=st.session_state.listing_sniper_active,
    )

    st.markdown("---")
    max_spot_scan_pairs = st.slider("🔍 Liczba par Spot do skanowania", 5, 60, 15, 5)
    max_fut_scan_pairs = st.slider("📈 Liczba par Futures do skanowania", 5, 60, 15, 5)

st.sidebar.markdown("---")
emergency_kill = st.sidebar.button("🛑 KILL SWITCH (ZAMKNIJ WSZYSTKO)", type="primary", use_container_width=True)

# =====================================================================
# KILL SWITCH LOGIKA
# =====================================================================
if emergency_kill:
    log_system_event("AKTYWACJA KILL SWITCH – Awaryjne zamykanie wszystkich pozycji!")
    # Inicjalizacja tymczasowa giełdy do kill switch
    try:
        ks_ex = ccxt.bitget({
            "apiKey": st.session_state.api_key.strip(),
            "secret": st.session_state.secret_key.strip(),
            "password": st.session_state.passphrase.strip(),
            "enableRateLimit": True,
            "options": {"defaultType": "swap"},
        })
        positions = ks_ex.fetch_positions()
        for p in positions:
            contracts = float(p.get("contracts", 0))
            if contracts > 0:
                sym = p["symbol"]
                side = "sell" if p.get("side") == "long" else "buy"
                try:
                    ks_ex.create_market_order(sym, side, contracts, params={"reduceOnly": True})
                    log_system_event(f"Zamknięto pozycję awaryjną na {sym}")
                except Exception as ex:
                    log_system_event(f"Błąd zamykania {sym}: {ex}")
    except Exception as e:
        log_system_event(f"Błąd wykonania kill switch: {e}")

    st.session_state.scanner_active = False
    st.session_state.trend_bot_spot_active = False
    st.session_state.trend_bot_fut_active = False
    st.session_state.grid_bot_active = False
    st.session_state.active_trades = {}
    st.session_state.signal_cooldown = {}
    send_notification("🚨 [KILL SWITCH] Awaryjnie zamknięto kontrakty i zatrzymano wszystkie boty!")
    st.success("🚨 KILL SWITCH WYKONANY: Pozycje Futures zamknięte, boty zatrzymane.")
    time.sleep(2)
    st.rerun()

# =====================================================================
# INICJALIZACJA KLIENTÓW CCXT DLA BITGET
# =====================================================================
def get_exchange(market_type):
    try:
        api_key = st.session_state.api_key.strip()
        secret = st.session_state.secret_key.strip()
        passphrase = st.session_state.passphrase.strip()

        if not api_key or not secret or not passphrase:
            return None

        ex_type = "spot" if market_type == "spot" else "swap"
        exchange = ccxt.bitget({
            "apiKey": api_key,
            "secret": secret,
            "password": passphrase,
            "enableRateLimit": True,
            "options": {"defaultType": ex_type},
        })
        return exchange
    except Exception as e:
        log_system_event(f"Błąd inicjalizacji giełdy ({market_type}): {e}")
        return None

spot_ex = get_exchange("spot")
futures_ex = get_exchange("futures")

# Ładowanie rynków do snapshota Snipera
if futures_ex and not st.session_state.known_markets:
    try:
        markets = futures_ex.load_markets()
        st.session_state.known_markets = set(markets.keys())
        log_system_event(f"Załadowano {len(st.session_state.known_markets)} rynków futures do snapshota.")
    except Exception as e:
        log_system_event(f"Błąd ładowania rynków futures: {e}")

# =====================================================================
# POBIERANIE SALD Z GIEŁDY
# =====================================================================
spot_free, spot_total = 0.0, 0.0
if spot_ex:
    try:
        s_bal = spot_ex.fetch_balance()
        spot_free = float(s_bal.get("free", {}).get("USDT", 0.0))
        spot_total = float(s_bal.get("total", {}).get("USDT", 0.0))
    except Exception as e:
        log_system_event(f"Błąd pobierania salda spot: {e}")

fut_free, fut_total = 0.0, 0.0
if futures_ex:
    try:
        f_bal = futures_ex.fetch_balance()
        fut_free = float(f_bal.get("free", {}).get("USDT", 0.0))
        fut_total = float(f_bal.get("total", {}).get("USDT", 0.0))
    except Exception as e:
        log_system_event(f"Błąd pobierania salda futures: {e}")

# =====================================================================
# NAGŁÓWEK GŁÓWNY I KAFELKI METRYK
# =====================================================================
st.title("🚀 Bitget SAS - Panel Operacyjny")
st.markdown("Autonomiczny ekosystem algorytmiczny powiązany z silnikiem Bitget oraz zapleczem subskrypcyjnym Stripe.")

if not st.session_state.api_key or not st.session_state.secret_key or not st.session_state.passphrase:
    st.warning("⚠️ Wprowadź swoje klucze API Bitget (API Key, Secret Key, Passphrase) w panelu po lewej stronie, aby system mógł pobierać saldo i handlować.")

total_unrealized_pnl = 0.0
active_positions_count = 0
if futures_ex:
    try:
        positions = futures_ex.fetch_positions()
        for p in positions:
            if float(p.get("contracts", 0)) > 0:
                active_positions_count += 1
                total_unrealized_pnl += float(p.get("unrealizedPnl", 0.0))
    except Exception as e:
        log_system_event(f"Błąd pobierania PnL: {e}")

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
        label="📊 PnL Niezrealizowany (Futures)",
        value=f"{total_unrealized_pnl:+.2f} USDT",
        delta=f"Aktywne: {active_positions_count} / {max_active_futures_positions}",
    )

with col_clock:
    elapsed = datetime.now() - st.session_state.session_start_time
    total_seconds = int(elapsed.total_seconds())
    hours, remainder = divmod(total_seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    session_duration = f"{hours:02d}:{minutes:02d}:{seconds:02d}"

    st.metric(
        label="⏰ Czas Sesji Roboczej",
        value=session_duration,
        delta=f"Pętla: {scan_interval}s",
    )

st.markdown("---")

# =====================================================================
# PANEL STEROWANIA BOTAMI
# =====================================================================
st.subheader("🥾 Centralny Panel Sterowania Botami Automatycznymi")
with st.container(border=True):
    col_tb1, col_tb2, col_tb3 = st.columns(3)

    with col_tb1:
        st.markdown("### 🟢 Bot Trendowy Spot")
        def toggle_main_trend_spot():
            st.session_state.trend_bot_spot_active = st.session_state.main_cb_trend_spot
            log_system_event(f"Zmiana stanu bota spot na: {st.session_state.trend_bot_spot_active}")
        st.checkbox(
            "Uruchom Bota Spot (MACD)",
            value=st.session_state.trend_bot_spot_active,
            key="main_cb_trend_spot",
            on_change=toggle_main_trend_spot,
        )
        if st.session_state.trend_bot_spot_active:
            st.success("🟢 Bot Spot aktywny")
        else:
            st.info("🔴 Bot Spot wyłączony")

    with col_tb2:
        st.markdown("### 🔵 Bot Trendowy Futures")
        def toggle_main_trend_fut():
            st.session_state.trend_bot_fut_active = st.session_state.main_cb_trend_fut
            log_system_event(f"Zmiana stanu bota futures na: {st.session_state.trend_bot_fut_active}")
        st.checkbox(
            "Uruchom Bota Futures (Long/Short)",
            value=st.session_state.trend_bot_fut_active,
            key="main_cb_trend_fut",
            on_change=toggle_main_trend_fut,
        )
        if st.session_state.trend_bot_fut_active:
            st.success("🟢 Bot Futures aktywny")
        else:
            st.info("🔴 Bot Futures wyłączony")

    with col_tb3:
        st.markdown("### 🟣 Grid Bot (Siatka Obronna)")
        def toggle_grid_bot():
            st.session_state.grid_bot_active = st.session_state.main_cb_grid_bot
            log_system_event(f"Zmiana stanu bota grid na: {st.session_state.grid_bot_active}")
        st.checkbox(
            "Uruchom Strategię Grid",
            value=st.session_state.grid_bot_active,
            key="main_cb_grid_bot",
            on_change=toggle_grid_bot,
        )
        if st.session_state.grid_bot_active:
            st.success("🟢 Grid Bot aktywny")
        else:
            st.info("🔴 Grid Bot wyłączony")

st.markdown("---")

col_btn, col_status = st.columns([2, 1])

with col_btn:
    if not st.session_state.scanner_active:
        if st.button("🚀 URUCHOM W PEŁNI AUTONOMICZNY SKANER NON-STOP", type="primary", use_container_width=True):
            st.session_state.scanner_active = True
            log_system_event("Uruchomiono skaner non-stop z poziomu panelu głównego.")
            st.rerun()
    else:
        if st.button("⏹️ ZATRZYMAJ AUTONOMICZNY SKANER", type="secondary", use_container_width=True):
            st.session_state.scanner_active = False
            log_system_event("Zatrzymano skaner non-stop z poziomu panelu głównego.")
            st.rerun()

with col_status:
    if st.session_state.scanner_active:
        st.success("🟢 SKANER: URUCHOMIONY")
    else:
        st.error("🔴 SKANER: ZATRZYMANY")

trusted_base_coins = [
    "BTC", "ETH", "SOL", "XRP", "ADA", "AVAX", "DOGE", "LINK", 
    "SUI", "NEAR", "APT", "RENDER", "INJ", "PEPE", "SHIB", "LTC", 
    "DOT", "UNI", "ZEC", "HYPE", "ATOM", "FET"
]

MIN_SPOT_TRADE = 5.0
MIN_FUT_TRADE = 5.0

# =====================================================================
# MODUŁ: LISTING SNIPER (W TLE)
# =====================================================================
if futures_ex and st.session_state.listing_sniper_active:
    try:
        current_markets = futures_ex.fetch_markets()
        current_symbols = {
            m["symbol"] for m in current_markets 
            if (m["quote"] == "USDT" or m["settle"] == "USDT") and m["active"]
        }

        if st.session_state.known_markets:
            new_symbols = current_symbols - st.session_state.known_markets
            if new_symbols:
                for sym in new_symbols:
                    if fut_free >= MIN_FUT_TRADE:
                        sniper_budget = min(fut_free, 100.0)
                        sniper_leverage = 2
                        try:
                            futures_ex.set_leverage(sniper_leverage, sym)
                            ticker = futures_ex.fetch_ticker(sym)
                            price = ticker.get("ask", ticker.get("last", 0))
                            if price > 0:
                                contracts = (sniper_budget * sniper_leverage) / price
                                futures_ex.create_market_order(sym, "buy", contracts)

                                st.session_state.active_trades[sym] = {
                                    "entry_price": price,
                                    "side": "buy",
                                    "contracts": contracts,
                                    "leverage": sniper_leverage,
                                }
                                st.session_state.trade_history.insert(0, {
                                    "Czas": time.strftime("%Y-%m-%d %H:%M:%S"),
                                    "Typ": "🚀 LISTING SNIPER LONG (2x)",
                                    "Para": sym,
                                    "Budżet": f"{sniper_budget:.2f} USDT",
                                    "Dźwignia": f"{sniper_leverage}x",
                                    "Cena": f"{price:.4f}",
                                })
                                log_system_event(f"Listing Sniper kupił nowy token: {sym} za {sniper_budget} USDT")
                                send_notification(f"🎯 [LISTING SNIPER] Wykryto nowy token {sym}! Kupiono za {sniper_budget:.1f} USDT.")
                        except Exception as ex:
                            log_system_event(f"Błąd Listing Snipera na {sym}: {ex}")
        st.session_state.known_markets = current_symbols
    except Exception as e:
        log_system_event(f"Błąd głównej pętli Listing Snipera: {e}")

# =====================================================================
# OBSŁUGA BOTA SPOT
# =====================================================================
if spot_ex and st.session_state.trend_bot_spot_active:
    try:
        s_tickers = spot_ex.fetch_tickers()
        best_spot_candidates = sorted(
            [
                sym for sym, data in s_tickers.items()
                if any(sym.startswith(c + "/") for c in trusted_base_coins)
                and sym.endswith("/USDT")
                and "BULL" not in sym and "BEAR" not in sym
            ],
            key=lambda x: s_tickers[x].get("quoteVolume", 0),
            reverse=True,
        )[:max_spot_scan_pairs]
        if best_spot_candidates:
            auto_bot_spot_coin = best_spot_candidates[0]
            s_ohlcv = spot_ex.fetch_ohlcv(auto_bot_spot_coin, timeframe=spot_tf, limit=60)
            s_df = pd.DataFrame(s_ohlcv, columns=["timestamp", "open", "high", "low", "close", "volume"])
            s_df["macd"] = s_df["close"].ewm(span=12, adjust=False).mean() - s_df["close"].ewm(span=26, adjust=False).mean()
            s_df["signal"] = s_df["macd"].ewm(span=9, adjust=False).mean()

            c_macd = s_df["macd"].iloc[-1]
            c_sig = s_df["signal"].iloc[-1]
            c_price = s_df["close"].iloc[-1]

            t_key = f"trend_bot_spot_{auto_bot_spot_coin}"
            last_action = st.session_state.signal_cooldown.get(t_key, 0)
            if c_macd > c_sig and (time.time() - last_action > 60):
                if spot_free >= MIN_SPOT_TRADE:
                    prov_budget = spot_free * (base_allocation_pct / 100.0)
                    budget = min(prov_budget, max_single_trade_usdt)
                    if budget < MIN_SPOT_TRADE and spot_free >= MIN_SPOT_TRADE and max_single_trade_usdt >= MIN_SPOT_TRADE:
                        budget = MIN_SPOT_TRADE

                    amount = budget / c_price
                    spot_ex.create_market_buy_order(auto_bot_spot_coin, amount)
                    st.session_state.signal_cooldown[t_key] = time.time()
                    st.session_state.trade_history.insert(0, {
                        "Czas": time.strftime("%Y-%m-%d %H:%M:%S"),
                        "Typ": "BOT SPOT BUY (Auto MACD)",
                        "Para": auto_bot_spot_coin,
                        "Budżet": f"{budget:.2f} USDT",
                        "Cena": f"{c_price:.4f}",
                    })
                    log_system_event(f"Bot Spot kupił {auto_bot_spot_coin} za {budget} USDT")
                    send_notification(f"🥾 [BOT SPOT] Kupiono {auto_bot_spot_coin} za {budget:.1f} USDT")
    except Exception as e:
        log_system_event(f"Błąd bota spot: {e}")

# =====================================================================
# OBSŁUGA FUTURES: AUTOMATYCZNY WYBÓR LONG/SHORT
# =====================================================================
if futures_ex and st.session_state.trend_bot_fut_active:
    try:
        if len(st.session_state.active_trades) < max_active_futures_positions:
            f_tickers = futures_ex.fetch_tickers()
            best_fut_candidates = sorted(
                [
                    sym for sym, data in f_tickers.items()
                    if (sym.endswith(":USDT") or "/USDT:USDT" in sym)
                    and "BULL" not in sym and "BEAR" not in sym
                ],
                key=lambda x: f_tickers[x].get("quoteVolume", 0),
                reverse=True,
            )[:max_fut_scan_pairs]

            evaluated_pairs = []
            for sym in best_fut_candidates:
                try:
                    f_ohlcv = futures_ex.fetch_ohlcv(sym, timeframe=spot_tf, limit=60)
                    time.sleep(0.02)
                    f_df = pd.DataFrame(f_ohlcv, columns=["timestamp", "open", "high", "low", "close", "volume"])
                    f_df["macd"] = f_df["close"].ewm(span=12, adjust=False).mean() - f_df["close"].ewm(span=26, adjust=False).mean()
                    f_df["signal"] = f_df["macd"].ewm(span=9, adjust=False).mean()

                    f_macd = f_df["macd"].iloc[-1]
                    f_sig = f_df["signal"].iloc[-1]
                    f_price = f_df["close"].iloc[-1]

                    signal_strength = abs(f_macd - f_sig) / f_price
                    side = "buy" if f_macd > f_sig else "sell"

                    evaluated_pairs.append({
                        "symbol": sym,
                        "price": f_price,
                        "side": side,
                        "strength": signal_strength,
                    })
                except Exception:
                    continue

            top_signal_pairs = sorted(evaluated_pairs, key=lambda x: x["strength"], reverse=True)[:max_active_futures_positions]

            for item in top_signal_pairs:
                if len(st.session_state.active_trades) >= max_active_futures_positions:
                    break

                sym = item["symbol"]
                f_price = item["price"]
                side = item["side"]
                label = "LONG" if side == "buy" else "SHORT"

                if "Automatyczny" in leverage_mode:
                    bot_leverage = 5 if "BTC" in sym or "ETH" in sym else 10
                else:
                    bot_leverage = manual_leverage

                tf_key = f"trend_bot_fut_{sym}"
                last_action_time = st.session_state.signal_cooldown.get(tf_key, 0)

                if sym not in st.session_state.active_trades and (time.time() - last_action_time > 90):
                    if fut_free >= MIN_FUT_TRADE:
                        prov_budget = fut_free * (base_allocation_pct / 100.0)
                        budget = min(prov_budget, max_single_trade_usdt)
                        if budget < MIN_FUT_TRADE and fut_free >= MIN_FUT_TRADE and max_single_trade_usdt >= MIN_FUT_TRADE:
                            budget = MIN_FUT_TRADE

                        try:
                            futures_ex.set_leverage(bot_leverage, sym)
                        except Exception:
                            pass

                        contracts = (budget * bot_leverage) / f_price
                        futures_ex.create_market_order(sym, side, contracts)

                        st.session_state.signal_cooldown[tf_key] = time.time()
                        st.session_state.active_trades[sym] = {
                            "entry_price": f_price,
                            "side": side,
                            "contracts": contracts,
                            "leverage": bot_leverage,
                        }
                        st.session_state.trade_history.insert(0, {
                            "Czas": time.strftime("%Y-%m-%d %H:%M:%S"),
                            "Typ": f"BOT FUTURES {label}",
                            "Para": sym,
                            "Budżet": f"{budget:.2f} USDT",
                            "Dźwignia": f"{bot_leverage}x",
                            "Cena": f"{f_price:.4f}",
                        })
                        log_system_event(f"Bot Futures otworzył {label} na {sym} ({bot_leverage}x)")
                        send_notification(f"🥾 [BOT FUTURES] Otwarto {label} na {sym} ({bot_leverage}x)")
    except Exception as e:
        log_system_event(f"Błąd bota futures: {e}")

# =====================================================================
# SPRAWDZANIE SYGNALÓW WYJŚCIA Z AKTYWNYCH POZYCJI
# =====================================================================
if futures_ex and st.session_state.active_trades:
    trades_to_remove = []
    try:
        current_tickers = futures_ex.fetch_tickers()
        for sym, trade_info in list(st.session_state.active_trades.items()):
            if sym in current_tickers:
                curr_price = float(current_tickers[sym].get("last", trade_info["entry_price"]))
                entry_price = trade_info["entry_price"]
                side = trade_info["side"]
                contracts = trade_info["contracts"]

                if side == "buy":
                    pct_change = ((curr_price - entry_price) / entry_price) * 100 * trade_info["leverage"]
                else:
                    pct_change = ((entry_price - curr_price) / entry_price) * 100 * trade_info["leverage"]

                try:
                    f_ohlcv = futures_ex.fetch_ohlcv(sym, timeframe=spot_tf, limit=30)
                    f_df = pd.DataFrame(f_ohlcv, columns=["timestamp", "open", "high", "low", "close", "volume"])
                    f_df["macd"] = f_df["close"].ewm(span=12, adjust=False).mean() - f_df["close"].ewm(span=26, adjust=False).mean()
                    f_df["signal"] = f_df["macd"].ewm(span=9, adjust=False).mean()

                    m_val = f_df["macd"].iloc[-1]
                    s_val = f_df["signal"].iloc[-1]

                    signal_reversed = (side == "buy" and m_val < s_val) or (side == "sell" and m_val > s_val)
                except Exception:
                    signal_reversed = False

                if signal_reversed or pct_change <= -8.0 or pct_change >= 20.0:
                    close_side = "sell" if side == "buy" else "buy"
                    try:
                        futures_ex.create_market_order(sym, close_side, contracts, params={"reduceOnly": True})
                    except Exception:
                        pass
                    trades_to_remove.append(sym)
                    st.session_state.signal_cooldown[f"fut_{sym}"] = time.time()
                    st.session_state.signal_cooldown[f"trend_bot_fut_{sym}"] = time.time()
                    log_system_event(f"Zamknięto pozycję {sym} (Wynik: {pct_change:+.2f}%)")
                    send_notification(f"🔄 [WYJŚCIOWY SYGNAŁ] Zamknięto {sym} (Wynik: {pct_change:+.2f}%)")
    except Exception as e:
        log_system_event(f"Błąd sprawdzania wyjść z pozycji: {e}")

    for r_sym in trades_to_remove:
        if r_sym in st.session_state.active_trades:
            del st.session_state.active_trades[r_sym]

# =====================================================================
# SKANER RYNKÓW SPOT (TABELA + ANALIZA)
# =====================================================================
st.subheader("📊 Autonomiczny Skaner Spot (RSI, Dip Buy, Momentum)")
spot_results = []

if spot_ex:
    try:
        s_tickers = spot_ex.fetch_tickers()
        valid_s = {
            sym: data for sym, data in s_tickers.items()
            if any(sym.startswith(coin + "/") for coin in trusted_base_coins)
            and sym.endswith("/USDT")
            and "BULL" not in sym and "BEAR" not in sym
            and data.get("quoteVolume", 0) > 40000
        }
        sorted_s = sorted(valid_s.items(), key=lambda x: x[1].get("quoteVolume", 0), reverse=True)
        top_spot_symbols = [item[0] for item in sorted_s[:max_spot_scan_pairs]]
    except Exception:
        top_spot_symbols = ["BTC/USDT", "ETH/USDT", "SOL/USDT", "XRP/USDT"]

    for idx, sym in enumerate(top_spot_symbols):
        try:
            ohlcv = spot_ex.fetch_ohlcv(sym, timeframe=spot_tf, limit=60)
            time.sleep(0.02)
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
                if current_rsi < 38:
                    is_spot_signal = True
            elif strat_type == 1:
                strat_name = "Spot Dip Buy"
                sma_20 = df["close"].rolling(20).mean().iloc[-1]
                if df["close"].iloc[-1] < sma_20 * 0.985:
                    is_spot_signal = True
            else:
                strat_name = "Spot Momentum Breakout"
                if current_vol > 2.5 and current_rsi > 52:
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

                if allocated_budget < MIN_SPOT_TRADE and spot_free >= MIN_SPOT_TRADE and max_single_trade_usdt >= MIN_SPOT_TRADE:
                    allocated_budget = MIN_SPOT_TRADE

                if allocated_budget < MIN_SPOT_TRADE:
                    spot_display_str = f"{allocated_budget:.1f} USDT"
                    status = f"⚠️ Alokacja za mała (< {MIN_SPOT_TRADE} USDT)"
                else:
                    spot_display_str = f"{allocated_budget:.1f} USDT"
                    status = "⏳ Oczekiwanie na sygnał"
                    spot_cooldown_key = f"spot_{sym}"
                    last_spot_time = st.session_state.signal_cooldown.get(spot_cooldown_key, 0)
                    is_in_cooldown = time.time() - last_spot_time < 120

                    if st.session_state.scanner_active and is_spot_signal:
                        if is_in_cooldown:
                            status = "🛡️ Cooldown aktywny"
                        else:
                            try:
                                current_price = df["close"].iloc[-1]
                                base_amount = allocated_budget / current_price
                                spot_ex.create_market_buy_order(sym, base_amount)

                                st.session_state.signal_cooldown[spot_cooldown_key] = time.time()
                                st.session_state.trade_history.insert(0, {
                                    "Czas": time.strftime("%Y-%m-%d %H:%M:%S"),
                                    "Typ": "SPOT BUY (Sygnał)",
                                    "Para": sym,
                                    "Budżet": f"{allocated_budget:.2f} USDT",
                                    "Cena": f"{current_price:.4f}",
                                })

                                status = f"🚀 KUPIONO za {allocated_budget:.1f} USDT"
                                log_system_event(f"Skaner spot kupił {sym} za {allocated_budget} USDT")
                                send_notification(f"🟢 [SPOT] Kupiono {sym} za {allocated_budget:.1f} USDT")
                            except Exception as ex:
                                status = f"❌ Błąd: {ex}"

            spot_results.append({
                "Para": sym,
                "Cena": f"{df['close'].iloc[-1]:.4f}",
                "RSI": f"{current_rsi:.1f}",
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
# SKANER RYNKÓW FUTURES (TABELA + LONG/SHORT)
# =====================================================================
st.subheader("📈 Autonomiczny Skaner Futures (Grid, RSI Reversal, MACD Trend)")
fut_results = []

if futures_ex:
    try:
        f_tickers = futures_ex.fetch_tickers()
        valid_f = {
            sym: data for sym, data in f_tickers.items()
            if any(
                sym.startswith(coin + "/") or sym.startswith(coin + ":") or sym == (coin + "/USDT:USDT")
                for coin in trusted_base_coins
            )
            and (sym.endswith(":USDT") or "/USDT:USDT" in sym)
            and "BULL" not in sym and "BEAR" not in sym
            and data.get("quoteVolume", 0) > 80000
        }
        sorted_f = sorted(valid_f.items(), key=lambda x: x[1].get("quoteVolume", 0), reverse=True)
        top_fut_symbols = [item[0] for item in sorted_f[:max_fut_scan_pairs]]
    except Exception:
        top_fut_symbols = ["BTC/USDT:USDT", "ETH/USDT:USDT", "SOL/USDT:USDT"]

    for idx, sym in enumerate(top_fut_symbols):
        try:
            ohlcv = futures_ex.fetch_ohlcv(sym, timeframe=spot_tf, limit=60)
            time.sleep(0.02)
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
                dyn_leverage = 5 if "BTC" in sym or "ETH" in sym else 10

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

                if allocated_budget < MIN_FUT_TRADE and fut_free >= MIN_FUT_TRADE and max_single_trade_usdt >= MIN_FUT_TRADE:
                    allocated_budget = MIN_FUT_TRADE

                if allocated_budget < MIN_FUT_TRADE:
                    fut_display_str = f"{allocated_budget:.1f} USDT"
                    status = f"⚠️ Alokacja za mała (< {MIN_FUT_TRADE} USDT)"
                else:
                    fut_display_str = f"{allocated_budget:.1f} USDT"
                    status = "⏳ Oczekiwanie na sygnał"
                    fut_cooldown_key = f"fut_{sym}"
                    last_fut_time = st.session_state.signal_cooldown.get(fut_cooldown_key, 0)
                    is_in_cooldown = time.time() - last_fut_time < 120

                    if st.session_state.scanner_active and is_futures_signal:
                        if len(st.session_state.active_trades) >= max_active_futures_positions:
                            status = f"🛡️ Limit {max_active_futures_positions} pozycji osiągnięty"
                        elif is_in_cooldown or sym in st.session_state.active_trades:
                            status = "🛡️ Cooldown / Pozycja aktywna"
                        else:
                            try:
                                current_price = df["close"].iloc[-1]
                                try:
                                    futures_ex.set_leverage(dyn_leverage, sym)
                                except Exception:
                                    pass

                                contract_size = (allocated_budget * dyn_leverage) / current_price
                                futures_ex.create_market_order(sym, trade_action, contract_size)

                                st.session_state.signal_cooldown[fut_cooldown_key] = time.time()
                                st.session_state.active_trades[sym] = {
                                    "entry_price": current_price,
                                    "side": trade_action,
                                    "contracts": contract_size,
                                    "leverage": dyn_leverage,
                                }

                                st.session_state.trade_history.insert(0, {
                                    "Czas": time.strftime("%Y-%m-%d %H:%M:%S"),
                                    "Typ": f"FUTURES {action_label} (Sygnał)",
                                    "Para": sym,
                                    "Budżet": f"{allocated_budget:.2f} USDT",
                                    "Dźwignia": f"{dyn_leverage}x",
                                    "Cena": f"{current_price:.4f}",
                                })

                                status = f"🚀 OTWARTO {action_label} ({dyn_leverage}x)"
                                log_system_event(f"Skaner futures otworzył {action_label} na {sym} ({dyn_leverage}x)")
                                send_notification(f"🔵 [FUTURES] Otwarto {action_label} na {sym}")
                            except Exception as ex:
                                status = f"❌ Błąd: {ex}"

            fut_results.append({
                "Kontrakt": sym,
                "Cena": f"{df['close'].iloc[-1]:.4f}",
                "RSI": f"{current_rsi:.1f}",
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
# DZIENNIK TRANSAKCJI & LOGI
# =====================================================================
st.subheader("📜 Dziennik Transakcji w Bieżącej Sesji")
if st.session_state.trade_history:
    st.dataframe(pd.DataFrame(st.session_state.trade_history), use_container_width=True)
else:
    st.info("Brak zarejestrowanych transakcji w tej sesji roboczej.")

st.markdown("---")
st.subheader("🛠️ Dziennik Zdarzeń Systemowych (Logi Operacyjne)")
if st.session_state.execution_logs:
    for log_item in st.session_state.execution_logs[:15]:
        st.text(log_item)
else:
    st.info("Brak wpisów w dzienniku zdarzeń.")

# Pętla odświeżania non-stop Streamlit
if st.session_state.scanner_active or st.session_state.trend_bot_spot_active or st.session_state.trend_bot_fut_active or st.session_state.grid_bot_active:
    time.sleep(scan_interval)
    st.rerun()

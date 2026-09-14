from datetime import datetime
import json
import os
import time
import ccxt
import pandas as pd
import streamlit as st
import stripe

st.set_page_config(
    page_title="Bitget SAS - Autonomia i Panel Subskrybenta",
    layout="wide",
)

CONFIG_FILE = "bitget_config.json"
STRIPE_CONFIG_FILE = "stripe_config.json"

def load_saved_credentials():
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r") as f:
                data = json.load(f)
                return data.get("api_key"), data.get("secret_key"), data.get("passphrase")
        except Exception:
            pass
    return None, None, None

def save_credentials(api_key, secret_key, passphrase):
    try:
        with open(CONFIG_FILE, "w") as f:
            json.dump({
                "api_key": api_key,
                "secret_key": secret_key,
                "passphrase": passphrase
            }, f)
    except Exception:
        pass

def load_stripe_credentials():
    if os.path.exists(STRIPE_CONFIG_FILE):
        try:
            with open(STRIPE_CONFIG_FILE, "r") as f:
                data = json.load(f)
                return data.get("stripe_pk"), data.get("stripe_sk"), data.get("stripe_price_id")
        except Exception:
            pass
    return "", "", ""

saved_api, saved_secret, saved_pass = load_saved_credentials()
saved_stripe_pk, saved_stripe_sk, saved_stripe_price_id = load_stripe_credentials()

if "page" not in st.session_state:
    st.session_state.page = "welcome"

if "logged_in" not in st.session_state:
    st.session_state.logged_in = bool(saved_api and saved_secret and saved_pass)

if "api_key" not in st.session_state:
    st.session_state.api_key = saved_api or st.secrets.get("BITGET_API_KEY", "bg_bad3414dc389df75aadc7794100d5c2")
if "secret_key" not in st.session_state:
    st.session_state.secret_key = saved_secret or st.secrets.get("BITGET_SECRET_KEY", "14829c31563785108f3c207963d431bdbeb80bcb8222340b6134bf5a4a2e902")
if "passphrase" not in st.session_state:
    st.session_state.passphrase = saved_pass or st.secrets.get("BITGET_PASSPHRASE", "Zostaw1260")

stripe_pk_val = saved_stripe_pk or st.secrets.get("STRIPE_PK", "")
stripe_sk_val = saved_stripe_sk or st.secrets.get("STRIPE_SK", "")
stripe_price_id_val = saved_stripe_price_id or st.secrets.get("STRIPE_PRICE_ID", "price_1RxSubscriptionMock")

if stripe_sk_val:
    stripe.api_key = stripe_sk_val

def get_exchange(market_type):
    try:
        ex_type = "spot" if market_type == "spot" else "swap"
        exchange = ccxt.bitget({
            "apiKey": st.session_state.api_key,
            "secret": st.session_state.secret_key,
            "password": st.session_state.passphrase,
            "enableRateLimit": True,
            "options": {"defaultType": ex_type},
        })
        return exchange
    except Exception:
        return None

def calculate_dynamic_leverage(sym, current_vol, mode, manual_lev):
    if "Ręczny" in mode:
        return int(manual_lev)
    if current_vol > 4.0:
        return 3
    elif current_vol > 2.5:
        return 5
    elif current_vol > 1.2:
        return 8
    else:
        return 10

st.markdown(
    """
    <style>
    @import url('https://fonts.googleapis.com/css2?family=Bungee+Inline&family=Cinzel:wght@700&display=swap');
    .stApp { background-color: #0d0b0a; }
    section[data-testid="stSidebar"] { background-color: #141110; border-right: 2px solid #3d2f1f; }
    .hero-wrapper { display: flex; align-items: center; justify-content: center; width: 100%; padding-top: 50px; padding-bottom: 20px; }
    .retro-ornate-frame {
        position: relative; background: radial-gradient(circle, #221a14 0%, #110d0a 100%);
        border: 6px double #f3d57a; padding: 50px 40px; border-radius: 16px;
        box-shadow: 0 0 50px rgba(243, 213, 122, 0.4), inset 0 0 35px rgba(0, 0, 0, 0.9);
        width: 100%; max-width: 900px; text-align: center;
    }
    .retro-vintage-title {
        font-family: 'Bungee Inline', cursive, sans-serif; font-size: 3.5rem; color: #f3d57a;
        letter-spacing: 6px; text-shadow: 4px 4px 0px #8b0000, 8px 8px 0px rgba(0,0,0,0.95); margin-bottom: 10px;
    }
    .retro-subtitle { font-family: 'Cinzel', serif; color: #e6c687; font-size: 1.2rem; letter-spacing: 2px; margin-bottom: 30px; }
    div.stButton > button {
        background: linear-gradient(135deg, #1e4d2b 0%, #0f2b17 100%) !important; color: #f3d57a !important;
        border: 2px solid #f3d57a !important; font-family: 'Cinzel', serif !important; font-weight: 700 !important;
        font-size: 1rem !important; padding: 12px 28px !important; border-radius: 8px !important;
        box-shadow: 0 4px 15px rgba(0, 0, 0, 0.6) !important; transition: all 0.3s ease !important;
    }
    div.stButton > button:hover {
        background: linear-gradient(135deg, #28663a 0%, #163d22 100%) !important; border-color: #ffe89d !important;
        color: #ffe89d !important; box-shadow: 0 0 20px rgba(243, 213, 122, 0.4) !important; transform: translateY(-2px);
    }
    div[data-testid="stMetric"] {
        border: 2px solid #f3d57a; border-radius: 10px; padding: 12px 15px;
        background-color: rgba(243, 213, 122, 0.03); box-shadow: 0 4px 12px rgba(0, 0, 0, 0.2);
    }
    div[data-testid="stMetric"] label { color: #f3d57a !important; }
    </style>
    """,
    unsafe_allow_html=True,
)

if st.session_state.page == "welcome":
    st.markdown(
        """
        <div class="hero-wrapper">
            <div class="retro-ornate-frame">
                <div class="retro-vintage-title">BITGET SAS</div>
                <div class="retro-subtitle">AUTONOMICZNY SYSTEM TRANSAKCYJNY & PANEL SUBSKRYPCJI</div>
                <p style="color: #dcdcdc; font-family: Cinzel, serif; font-size: 1.1rem; margin-bottom: 30px;">
                    Profesjonalny terminal operacyjny zintegrowany ze Stripe oraz zaawansowanym zarządzaniem ryzykiem.
                </p>
        """,
        unsafe_allow_html=True,
    )
    col_l1, col_l2, col_l3 = st.columns([1, 2, 1])
    with col_l2:
        if st.button("🚪 PRZEJDŹ DO TERMINARZA", use_container_width=True):
            st.session_state.page = "main"
            st.rerun()
    st.markdown("</div></div>", unsafe_allow_html=True)
    st.stop()

if "session_start_time" not in st.session_state:
    st.session_state.session_start_time = datetime.now()
if "trade_history" not in st.session_state:
    st.session_state.trade_history = []
if "signal_cooldown" not in st.session_state:
    st.session_state.signal_cooldown = {}
if "scanner_active" not in st.session_state:
    st.session_state.scanner_active = False
if "active_trades" not in st.session_state:
    st.session_state.active_trades = {}
if "active_spot_trades" not in st.session_state:
    st.session_state.active_spot_trades = set()
if "trend_bot_spot_active" not in st.session_state:
    st.session_state.trend_bot_spot_active = False
if "trend_bot_fut_active" not in st.session_state:
    st.session_state.trend_bot_fut_active = False
if "known_markets" not in st.session_state:
    st.session_state.known_markets = set()
if "listing_sniper_active" not in st.session_state:
    st.session_state.listing_sniper_active = True
if "admin_unlocked" not in st.session_state:
    st.session_state.admin_unlocked = False

# =====================================================================
# BEZPIECZNY PANEL ADMINISTRATORA (CHRONIONY HASŁEM)
# =====================================================================
with st.sidebar.container(border=True):
    st.markdown("### 💎 Strefa Administratora")
    if not st.session_state.admin_unlocked:
        admin_pin = st.text_input("Podaj PIN Administratora", type="password")
        if st.button("🔓 ODBLOKUJ KLUCZE API", use_container_width=True):
            if admin_pin == st.session_state.passphrase:
                st.session_state.admin_unlocked = True
                st.success("Odblokowano panel administratora!")
                st.rerun()
            else:
                st.error("Nieprawidłowy PIN.")
    else:
        st.success("🔓 Panel Admina Odblokowany")
        input_api = st.text_input("Bitget API Key", value=st.session_state.api_key, type="password")
        input_secret = st.text_input("Bitget Secret Key", value=st.session_state.secret_key, type="password")
        input_pass = st.text_input("Bitget Passphrase", value=st.session_state.passphrase, type="password")

        if st.button("🚀 ZAPISZ KLUCZE", use_container_width=True):
            if input_api and input_secret and input_pass:
                st.session_state.api_key = input_api
                st.session_state.secret_key = input_secret
                st.session_state.passphrase = input_pass
                save_credentials(input_api, input_secret, input_pass)
                st.session_state.logged_in = True
                st.success("✅ Zapisano klucze pomyślnie")
                st.rerun()
            else:
                st.error("Wypełnij wszystkie pola.")
        
        if st.button("🔒 ZABLOKUJ WIDOK", use_container_width=True):
            st.session_state.admin_unlocked = False
            st.rerun()

spot_ex = get_exchange("spot")
futures_ex = get_exchange("futures")

if futures_ex and not st.session_state.known_markets:
    try:
        markets = futures_ex.load_markets()
        st.session_state.known_markets = set(markets.keys())
    except Exception:
        pass

st.sidebar.markdown("---")
if st.sidebar.button("⬅️ Powrót do ekranu powitalnego", use_container_width=True):
    st.session_state.page = "welcome"
    st.rerun()

st.sidebar.markdown("---")
with st.sidebar.container(border=True):
    st.markdown("### 🔔 Powiadomienia")
    enable_notifications = st.checkbox("Włącz powiadomienia", value=True)
    telegram_bot_token = st.text_input("Telegram Bot Token", type="password")
    telegram_chat_id = st.text_input("Telegram Chat ID")

def send_notification(message):
    if enable_notifications:
        st.toast(message, icon="🤖")
        if telegram_bot_token and telegram_chat_id:
            try:
                import urllib.parse
                import urllib.request
                url = f"https://api.telegram.org/bot{telegram_bot_token}/sendMessage"
                data = urllib.parse.urlencode({"chat_id": telegram_chat_id, "text": message}).encode("utf-8")
                urllib.request.urlopen(url, data=data, timeout=3)
            except Exception:
                pass

st.sidebar.markdown("---")
with st.sidebar.container(border=True):
    st.markdown("### ⚙️ Ustawienia Kapitału i Ryzyka")
    allocation_mode = st.radio("Zarządzanie wielkością pozycji", ["🤖 Inteligentny Auto-Dobór (Zmienność + Siła)", "🎛️ Stały procent portfela"])
    base_allocation_pct = st.slider("Maksymalny udział kapitału na 1 pozycję (%)", 1, 30, 10)
    max_single_trade_usdt = st.number_input("🛡️ Maksymalnie USDT na 1 pozycję", 5.0, 5000.0, 50.0, 5.0)
    
    # Limity liczby pozycji dla Spot oraz Futures
    max_active_spot_positions = st.slider("📈 Maksymalna liczba aktywnych pozycji Spot", 1, 20, 5)
    max_active_futures_positions = st.slider("📈 Maksymalna liczba aktywnych pozycji Futures", 1, 20, 5)

    st.markdown("---")
    st.markdown("### 🛡️ Opcjonalne Limity SL / TP")
    enable_custom_sl_tp = st.checkbox("Włącz awaryjne limity SL / TP (%)", value=False)
    custom_stop_loss_pct = st.slider("Maksymalna strata (Stop-Loss %)", 1, 30, 5, disabled=not enable_custom_sl_tp)
    custom_take_profit_pct = st.slider("Docelowy zysk (Take-Profit %)", 1, 100, 15, disabled=not enable_custom_sl_tp)

    st.markdown("---")
    st.markdown("### ⚡ Zarządzanie Dźwignią (Bezpieczne)")
    leverage_mode = st.radio("Tryb Dźwigni", ["🤖 Autonomiczny (Bezpieczny, max 10x)", "🎛️ Ręczny"])
    manual_leverage = st.slider("Stała dźwignia Futures (Ręczna)", 1, 10, 3)

    st.markdown("---")
    st.markdown("### 🧠 Timeframe Analizy")
    spot_tf = st.selectbox("Interwał", ["1m", "5m", "15m", "30m", "1h", "4h", "1d"], index=4)

st.sidebar.markdown("---")
with st.sidebar.container(border=True):
    st.markdown("### 🔄 Pętla Główna Skanera")
    if "sidebar_auto_scan_cb" not in st.session_state:
        st.session_state.sidebar_auto_scan_cb = st.session_state.scanner_active

    def toggle_scanner_from_sidebar():
        st.session_state.scanner_active = st.session_state.sidebar_auto_scan_cb

    auto_scan_enabled = st.checkbox("Włącz auto-skanowanie w tle", key="sidebar_auto_scan_cb", on_change=toggle_scanner_from_sidebar)
    scan_interval = st.slider("Interwał odświeżania (s)", 1, 300, 3)

    st.markdown("---")
    if "listing_sniper_cb" not in st.session_state:
        st.session_state.listing_sniper_cb = st.session_state.listing_sniper_active

    def toggle_listing_sniper():
        st.session_state.listing_sniper_active = st.session_state.listing_sniper_cb

    st.checkbox("🎯 Listing Sniper (Max 50 USDT, lewar 2x)", key="listing_sniper_cb", on_change=toggle_listing_sniper)

    st.markdown("---")
    max_spot_scan_pairs = st.slider("🔍 Liczba par Spot do skanowania", 5, 50, 15, 5)
    max_fut_scan_pairs = st.slider("📈 Liczba par Futures do skanowania", 5, 50, 15, 5)

st.sidebar.markdown("---")
with st.sidebar.container(border=True):
    st.markdown("### 💳 Strefa Klienta / Subskrypcja")
    client_email = st.text_input("Twój adres e-mail", value="klient@domena.pl")
    
    if st.button("💳 OPŁAĆ DOSTĘP (STRIPE)", use_container_width=True):
        if stripe_sk_val and stripe_price_id_val:
            try:
                checkout_session = stripe.checkout.Session.create(
                    payment_method_types=['card'],
                    line_items=[{
                        'price': stripe_price_id_val,
                        'quantity': 1,
                    }],
                    mode='subscription',
                    success_url='https://bot-bitget.pl/?success=true',
                    cancel_url='https://bot-bitget.pl/?canceled=true',
                    customer_email=client_email,
                )
                st.markdown(f"**🔗 Link do płatności:** [Kliknij tutaj, aby opłacić]({checkout_session.url})", unsafe_allow_html=True)
                st.success("Wygenerowano bezpieczny link płatności!")
            except Exception as e:
                st.error(f"Błąd płatności: {e}")
        else:
            st.error("Bramka płatności nie jest skonfigurowana przez administratora.")

st.sidebar.markdown("---")
emergency_kill = st.sidebar.button("🛑 ZAMKNIJ WSZYSTKO (KILL SWITCH)", type="primary", use_container_width=True)

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
    st.session_state.active_spot_trades = set()
    st.session_state.signal_cooldown = {}
    send_notification("🚨 [KILL SWITCH] Zamknięto pozycje i wyłączono boty!")
    st.success("🚨 KILL SWITCH WYKONANY.")
    time.sleep(2)
    st.rerun()

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
    st.metric(label="🟢 Portfel Spot", value=f"{spot_free:.2f} USDT", delta=f"Aktywne: {len(st.session_state.active_spot_trades)} / {max_active_spot_positions}")
with col2:
    st.metric(label="🔵 Portfel Futures", value=f"{fut_free:.2f} USDT", delta=f"Całkowite: {fut_total:.2f} USDT")
with col3:
    st.metric(label="📊 Wyniki Futures (Niezrealizowane)", value=f"{total_unrealized_pnl:+.2f} USDT", delta=f"Aktywne: {active_positions_count} / {max_active_futures_positions}")
with col_clock:
    elapsed = datetime.now() - st.session_state.session_start_time
    total_seconds = int(elapsed.total_seconds())
    hours, remainder = divmod(total_seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    st.metric(label="⏰ Czas Sesji", value=f"{hours:02d}:{minutes:02d}:{seconds:02d}", delta=f"Interwał: {scan_interval}s")

st.markdown("---")

st.subheader("🥾 Panel Sterowania Botami Trendowymi")
with st.container(border=True):
    col_tb1, col_tb2 = st.columns(2)

    with col_tb1:
        st.markdown("### 🟢 Bot Spot Trendowy")
        if "main_cb_trend_spot" not in st.session_state:
            st.session_state.main_cb_trend_spot = st.session_state.trend_bot_spot_active

        def toggle_main_trend_spot():
            st.session_state.trend_bot_spot_active = st.session_state.main_cb_trend_spot

        st.checkbox("🟢 Uruchom Bota Spot", key="main_cb_trend_spot", on_change=toggle_main_trend_spot)
        if st.session_state.trend_bot_spot_active:
            st.success("🟢 Bot Spot Aktywny")
        else:
            st.info("🔴 Bot Spot Zatrzymany")

    with col_tb2:
        st.markdown("### 🔵 Bot Futures (Inteligentny Long/Short)")
        if "main_cb_trend_fut" not in st.session_state:
            st.session_state.main_cb_trend_fut = st.session_state.trend_bot_fut_active

        def toggle_main_trend_fut():
            st.session_state.trend_bot_fut_active = st.session_state.main_cb_trend_fut

        st.checkbox("🔵 Uruchom Bota Futures", key="main_cb_trend_fut", on_change=toggle_main_trend_fut)
        if st.session_state.trend_bot_fut_active:
            st.success("🟢 Bot Futures Aktywny")
        else:
            st.info("🔴 Bot Futures Zatrzymany")

st.markdown("---")
col_btn, col_status = st.columns([2, 1])
with col_btn:
    if not st.session_state.scanner_active:
        if st.button("🚀 Uruchom Skaner Non-Stop", type="primary", use_container_width=True):
            st.session_state.scanner_active = True
            st.rerun()
    else:
        if st.button("⏹️ Zatrzymaj Skaner", type="secondary", use_container_width=True):
            st.session_state.scanner_active = False
            st.rerun()
with col_status:
    if st.session_state.scanner_active:
        st.success("STATUS: AKTYWNY")
    else:
        st.error("STATUS: ZATRZYMANY")

trusted_base_coins = ["BTC", "ETH", "SOL", "XRP", "ADA", "AVAX", "DOGE", "LINK", "SUI", "NEAR", "APT", "RENDER", "INJ", "PEPE", "SHIB", "LTC", "DOT", "UNI", "ZEC", "HYPE", "ATOM"]
MIN_SPOT_TRADE = 5.0
MIN_FUT_TRADE = 5.0

# =====================================================================
# MODUŁ: LISTING SNIPER
# =====================================================================
if futures_ex and st.session_state.listing_sniper_active:
    try:
        current_markets = futures_ex.fetch_markets()
        current_symbols = {m["symbol"] for m in current_markets if (m["quote"] == "USDT" or m["settle"] == "USDT") and m["active"]}

        if st.session_state.known_markets:
            new_symbols = current_symbols - st.session_state.known_markets
            if new_symbols:
                for sym in new_symbols:
                    if fut_free >= MIN_FUT_TRADE and sym not in st.session_state.active_trades:
                        sniper_budget = max(MIN_FUT_TRADE, min(fut_free, 50.0))
                        if sniper_budget <= fut_free:
                            sniper_leverage = 2
                            try:
                                futures_ex.set_leverage(sniper_leverage, sym)
                                ticker = futures_ex.fetch_ticker(sym)
                                price = ticker.get("ask", ticker.get("last", 0))
                                if price > 0:
                                    contracts = (sniper_budget * sniper_leverage) / price
                                    futures_ex.create_market_order(sym, "buy", contracts)
                                    st.session_state.active_trades[sym] = {"entry_price": price, "side": "buy", "contracts": contracts, "leverage": sniper_leverage}
                                    st.session_state.trade_history.insert(0, {
                                        "Czas": time.strftime("%Y-%m-%d %H:%M:%S"),
                                        "Typ": "🎯 LISTING SNIPER LONG (2x)",
                                        "Para": sym,
                                        "Budżet": f"{sniper_budget:.2f} USDT",
                                        "Dźwignia": f"{sniper_leverage}x",
                                        "Cena": f"{price:.4f}",
                                    })
                                    send_notification(f"🎯 [SNIPER] Nowy token {sym}! Zakup za {sniper_budget:.1f} USDT (2x).")
                            except Exception:
                                pass
        st.session_state.known_markets = current_symbols
    except Exception:
        pass

# =====================================================================
# OBSŁUGA BOTA SPOT (Z UWZGLĘDNIENIEM LIMITU POZYCJI)
# =====================================================================
if spot_ex and st.session_state.trend_bot_spot_active:
    try:
        if len(st.session_state.active_spot_trades) < max_active_spot_positions and spot_free >= MIN_SPOT_TRADE:
            s_tickers = spot_ex.fetch_tickers()
            best_spot_candidates = sorted(
                [sym for sym, data in s_tickers.items() if any(sym.startswith(c + "/") for c in trusted_base_coins) and sym.endswith("/USDT") and "BULL" not in sym and "BEAR" not in sym and sym not in st.session_state.active_spot_trades],
                key=lambda x: s_tickers[x].get("quoteVolume", 0), reverse=True
            )[:max_spot_scan_pairs]
            if best_spot_candidates:
                auto_bot_spot_coin = best_spot_candidates[0]
                s_ohlcv = spot_ex.fetch_ohlcv(auto_bot_spot_coin, timeframe=spot_tf, limit=50)
                s_df = pd.DataFrame(s_ohlcv, columns=["timestamp", "open", "high", "low", "close", "volume"])
                s_df["macd"] = s_df["close"].ewm(span=12, adjust=False).mean() - s_df["close"].ewm(span=26, adjust=False).mean()
                s_df["signal"] = s_df["macd"].ewm(span=9, adjust=False).mean()

                c_macd = s_df["macd"].iloc[-1]
                c_sig = s_df["signal"].iloc[-1]
                c_price = s_df["close"].iloc[-1]

                t_key = f"trend_bot_spot_{auto_bot_spot_coin}"
                if c_macd > c_sig and (time.time() - st.session_state.signal_cooldown.get(t_key, 0) > 60):
                    budget = max(MIN_SPOT_TRADE, min(spot_free * (base_allocation_pct / 100.0), max_single_trade_usdt))
                    if budget >= MIN_SPOT_TRADE and budget <= spot_free:
                        amount = budget / c_price
                        spot_ex.create_market_buy_order(auto_bot_spot_coin, amount)
                        st.session_state.active_spot_trades.add(auto_bot_spot_coin)
                        st.session_state.signal_cooldown[t_key] = time.time()
                        st.session_state.trade_history.insert(0, {
                            "Czas": time.strftime("%Y-%m-%d %H:%M:%S"),
                            "Typ": "BOT SPOT BUY",
                            "Para": auto_bot_spot_coin,
                            "Budżet": f"{budget:.2f} USDT",
                            "Cena": f"{c_price:.4f}",
                        })
                        send_notification(f"🟢 [BOT SPOT] Zakup {auto_bot_spot_coin} za {budget:.1f} USDT")
    except Exception:
        pass

# =====================================================================
# OBSŁUGA FUTURES
# =====================================================================
if futures_ex and st.session_state.trend_bot_fut_active:
    try:
        if len(st.session_state.active_trades) < max_active_futures_positions and fut_free >= MIN_FUT_TRADE:
            f_tickers = futures_ex.fetch_tickers()
            best_fut_candidates = sorted(
                [sym for sym, data in f_tickers.items() if (sym.endswith(":USDT") or "/USDT:USDT" in sym) and "BULL" not in sym and "BEAR" not in sym and sym not in st.session_state.active_trades],
                key=lambda x: f_tickers[x].get("quoteVolume", 0), reverse=True
            )[:max_fut_scan_pairs]

            evaluated_pairs = []
            for sym in best_fut_candidates:
                try:
                    f_ohlcv = futures_ex.fetch_ohlcv(sym, timeframe=spot_tf, limit=50)
                    time.sleep(0.02)
                    f_df = pd.DataFrame(f_ohlcv, columns=["timestamp", "open", "high", "low", "close", "volume"])
                    f_df["volatility_pct"] = ((f_df["high"] - f_df["low"]) / f_df["close"]).rolling(14).mean() * 100
                    f_vol = f_df["volatility_pct"].iloc[-1] if not pd.isna(f_df["volatility_pct"].iloc[-1]) else 2.0

                    f_df["macd"] = f_df["close"].ewm(span=12, adjust=False).mean() - f_df["close"].ewm(span=26, adjust=False).mean()
                    f_df["signal"] = f_df["macd"].ewm(span=9, adjust=False).mean()

                    f_macd = f_df["macd"].iloc[-1]
                    f_sig = f_df["signal"].iloc[-1]
                    f_price = f_df["close"].iloc[-1]

                    signal_strength = abs(f_macd - f_sig) / f_price
                    side = "buy" if f_macd > f_sig else "sell"

                    evaluated_pairs.append({"symbol": sym, "price": f_price, "side": side, "strength": signal_strength, "volatility": f_vol})
                except Exception:
                    continue

            top_signal_pairs = sorted(evaluated_pairs, key=lambda x: x["strength"], reverse=True)[:max_active_futures_positions]

            for item in top_signal_pairs:
                if len(st.session_state.active_trades) >= max_active_futures_positions:
                    break

                sym = item["symbol"]
                if sym in st.session_state.active_trades:
                    continue

                f_price = item["price"]
                side = item["side"]
                f_vol = item["volatility"]
                label = "LONG" if side == "buy" else "SHORT"
                
                bot_leverage = calculate_dynamic_leverage(sym, f_vol, leverage_mode, manual_leverage)

                tf_key = f"trend_bot_fut_{sym}"
                if time.time() - st.session_state.signal_cooldown.get(tf_key, 0) > 90:
                    risk_mult = 0.5 if f_vol > 3.5 else (0.8 if f_vol > 2.0 else 1.0)
                    signal_mult = min(1.0, max(0.4, item["strength"] * 150))
                    
                    if "Inteligentny" in allocation_mode:
                        calc_pct = max(1.0, min(30.0, base_allocation_pct * risk_mult * signal_mult))
                    else:
                        calc_pct = float(base_allocation_pct)

                    budget = max(MIN_FUT_TRADE, min(fut_free * (calc_pct / 100.0), max_single_trade_usdt))
                    if budget > fut_free:
                        budget = fut_free

                    if budget >= MIN_FUT_TRADE:
                        try:
                            futures_ex.set_leverage(bot_leverage, sym)
                        except Exception:
                            pass

                        contracts = (budget * bot_leverage) / f_price
                        futures_ex.create_market_order(sym, side, contracts)

                        st.session_state.signal_cooldown[tf_key] = time.time()
                        st.session_state.active_trades[sym] = {"entry_price": f_price, "side": side, "contracts": contracts, "leverage": bot_leverage}
                        st.session_state.trade_history.insert(0, {
                            "Czas": time.strftime("%Y-%m-%d %H:%M:%S"),
                            "Typ": f"BOT FUTURES {label}",
                            "Para": sym,
                            "Budżet": f"{budget:.2f} USDT",
                            "Dźwignia": f"{bot_leverage}x",
                            "Cena": f"{f_price:.4f}",
                        })
                        send_notification(f"🥾 [BOT] Otwarto {label} na {sym} ({bot_leverage}x, budżet: {budget:.1f} USDT)")
    except Exception:
        pass

# =====================================================================
# SPRAWDZANIE SYGNAŁÓW DO ZAMKNIĘCIA (FUTURES) + OPCJONALNY SL/TP
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

                sl_triggered = False
                tp_triggered = False
                if enable_custom_sl_tp:
                    if pct_change <= -custom_stop_loss_pct:
                        sl_triggered = True
                    elif pct_change >= custom_take_profit_pct:
                        tp_triggered = True

                try:
                    f_ohlcv = futures_ex.fetch_ohlcv(sym, timeframe=spot_tf, limit=30)
                    f_df = pd.DataFrame(f_ohlcv, columns=["timestamp", "open", "high", "low", "close", "volume"])
                    f_df["macd"] = f_df["close"].ewm(span=12, adjust=False).mean() - f_df["close"].ewm(span=26, adjust=False).mean()
                    f_df["signal"] = f_df["macd"].ewm(span=9, adjust=False).mean()
                    signal_reversed = (side == "buy" and f_df["macd"].iloc[-1] < f_df["signal"].iloc[-1]) or (side == "sell" and f_df["macd"].iloc[-1] > f_df["signal"].iloc[-1])
                except Exception:
                    signal_reversed = False

                if sl_triggered or tp_triggered or signal_reversed:
                    close_side = "sell" if side == "buy" else "buy"
                    try:
                        futures_ex.create_market_order(sym, close_side, contracts, params={"reduceOnly": True})
                    except Exception:
                        pass
                    trades_to_remove.append(sym)
                    st.session_state.signal_cooldown[f"fut_{sym}"] = time.time()
                    
                    reason = "SL/TP" if (sl_triggered or tp_triggered) else "Sygnał Trendu"
                    send_notification(f"🔄 [WYJŚCIE - {reason}] Zamknięto {sym} (Wynik: {pct_change:+.2f}%)")
    except Exception:
        pass

    for r_sym in trades_to_remove:
        if r_sym in st.session_state.active_trades:
            del st.session_state.active_trades[r_sym]

# =====================================================================
# SKANER SPOT (Z UWZGLĘDNIENIEM LIMITU POZYCJI)
# =====================================================================
st.subheader("📊 Skaner Spot (Wyświetlane Top 8)")
spot_results = []
if spot_ex:
    try:
        s_tickers = spot_ex.fetch_tickers()
        valid_s = {sym: data for sym, data in s_tickers.items() if any(sym.startswith(coin + "/") for coin in trusted_base_coins) and sym.endswith("/USDT") and "BULL" not in sym and "BEAR" not in sym and data.get("quoteVolume", 0) > 50000}
        top_spot_symbols = [item[0] for item in sorted(valid_s.items(), key=lambda x: x[1].get("quoteVolume", 0), reverse=True)[:max_spot_scan_pairs]]
    except Exception:
        top_spot_symbols = ["BTC/USDT", "ETH/USDT", "SOL/USDT"]

    for idx, sym in enumerate(top_spot_symbols):
        try:
            ohlcv = spot_ex.fetch_ohlcv(sym, timeframe=spot_tf, limit=50)
            time.sleep(0.02)
            df = pd.DataFrame(ohlcv, columns=["timestamp", "open", "high", "low", "close", "volume"])
            df["volatility_pct"] = ((df["high"] - df["low"]) / df["close"]).rolling(14).mean() * 100
            current_vol = df["volatility_pct"].iloc[-1] if not pd.isna(df["volatility_pct"].iloc[-1]) else 2.0

            delta = df["close"].diff()
            rs = (delta.where(delta > 0, 0)).rolling(14).mean() / (-delta.where(delta < 0, 0)).rolling(14).mean()
            current_rsi = (100 - (100 / (1 + rs))).iloc[-1]

            strat_type = idx % 3
            is_spot_signal = (current_rsi < 38) if strat_type == 0 else (df["close"].iloc[-1] < df["close"].rolling(20).mean().iloc[-1] * 0.985 if strat_type == 1 else current_vol > 2.5 and current_rsi > 52)
            strat_name = "RSI Oversold" if strat_type == 0 else ("Dip Buy" if strat_type == 1 else "Momentum Breakout")

            if spot_free < MIN_SPOT_TRADE:
                spot_display_str = "0.0 USDT"
                status = "⚠️ Za mało środków (< 5 USDT)"
            elif sym in st.session_state.active_spot_trades:
                spot_display_str = f"{MIN_SPOT_TRADE:.1f} USDT"
                status = "🛡️ Pozycja spot aktywna"
            elif len(st.session_state.active_spot_trades) >= max_active_spot_positions:
                spot_display_str = "0.0 USDT"
                status = "🛡️ Limit pozycji Spot osiągnięty"
            else:
                risk_mult = 0.5 if current_vol > 3.5 else 1.0
                allocated_budget = max(MIN_SPOT_TRADE, min(spot_free * ((base_allocation_pct * risk_mult) / 100.0), max_single_trade_usdt))
                if allocated_budget > spot_free:
                    allocated_budget = spot_free

                if allocated_budget < MIN_SPOT_TRADE:
                    spot_display_str = f"{allocated_budget:.1f} USDT"
                    status = "⚠️ Alokacja za mała (< 5 USDT)"
                else:
                    spot_display_str = f"{allocated_budget:.1f} USDT"
                    status = "⏳ Oczekiwanie"
                    if st.session_state.scanner_active and is_spot_signal:
                        if len(st.session_state.active_spot_trades) >= max_active_spot_positions:
                            status = "🛡️ Limit pozycji osiągnięty"
                        else:
                            try:
                                current_price = df["close"].iloc[-1]
                                spot_ex.create_market_buy_order(sym, allocated_budget / current_price)
                                st.session_state.active_spot_trades.add(sym)
                                st.session_state.trade_history.insert(0, {"Czas": time.strftime("%Y-%m-%d %H:%M:%S"), "Typ": "SPOT BUY", "Para": sym, "Budżet": f"{allocated_budget:.2f} USDT", "Cena": f"{current_price:.4f}"})
                                status = "🚀 KUPIONO"
                                send_notification(f"🟢 [SPOT] Kupiono {sym} za {allocated_budget:.1f} USDT")
                            except Exception as ex:
                                status = f"❌ Błąd: {ex}"

            spot_results.append({"Para": sym, "Cena": f"{df['close'].iloc[-1]:.4f}", "Strategia": strat_name, "Alokacja": spot_display_str, "Status": status})
        except Exception:
            continue
    if spot_results:
        st.dataframe(pd.DataFrame(spot_results[:8]), use_container_width=True)

st.markdown("---")

# =====================================================================
# SKANER FUTURES
# =====================================================================
st.subheader("📈 Skaner Futures (Wyświetlane Top 8)")
fut_results = []
if futures_ex:
    try:
        f_tickers = futures_ex.fetch_tickers()
        valid_f = {sym: data for sym, data in f_tickers.items() if any(sym.startswith(coin + "/") or sym.startswith(coin + ":") for coin in trusted_base_coins) and (sym.endswith(":USDT") or "/USDT:USDT" in sym) and "BULL" not in sym and "BEAR" not in sym and data.get("quoteVolume", 0) > 100000}
        top_fut_symbols = [item[0] for item in sorted(valid_f.items(), key=lambda x: x[1].get("quoteVolume", 0), reverse=True)[:max_fut_scan_pairs]]
    except Exception:
        top_fut_symbols = ["BTC/USDT:USDT", "ETH/USDT:USDT"]

    for idx, sym in enumerate(top_fut_symbols):
        try:
            ohlcv = futures_ex.fetch_ohlcv(sym, timeframe=spot_tf, limit=50)
            time.sleep(0.02)
            df = pd.DataFrame(ohlcv, columns=["timestamp", "open", "high", "low", "close", "volume"])
            df["volatility_pct"] = ((df["high"] - df["low"]) / df["close"]).rolling(14).mean() * 100
            current_vol = df["volatility_pct"].iloc[-1] if not pd.isna(df["volatility_pct"].iloc[-1]) else 2.0

            df["macd"] = df["close"].ewm(span=12, adjust=False).mean() - df["close"].ewm(span=26, adjust=False).mean()
            df["signal"] = df["macd"].ewm(span=9, adjust=False).mean()

            dyn_leverage = calculate_dynamic_leverage(sym, current_vol, leverage_mode, manual_leverage)
            is_futures_signal = (df["macd"].iloc[-1] > df["signal"].iloc[-1])
            trade_action = "buy" if is_futures_signal else "sell"
            action_label = "LONG" if is_futures_signal else "SHORT"
            strat_name = "Trend-Following (MACD)"

            if fut_free < MIN_FUT_TRADE:
                fut_display_str = "0.0 USDT"
                status = "⚠️ Za mało środków (< 5 USDT)"
            elif sym in st.session_state.active_trades:
                fut_display_str = f"{MIN_FUT_TRADE:.1f} USDT"
                status = "🛡️ Pozycja aktywna"
            elif len(st.session_state.active_trades) >= max_active_futures_positions:
                fut_display_str = "0.0 USDT"
                status = "🛡️ Limit pozycji Futures osiągnięty"
            else:
                risk_mult = 0.5 if current_vol > 3.5 else 1.0
                allocated_budget = max(MIN_FUT_TRADE, min(fut_free * ((base_allocation_pct * risk_mult) / 100.0), max_single_trade_usdt))
                if allocated_budget > fut_free:
                    allocated_budget = fut_free

                if allocated_budget < MIN_FUT_TRADE:
                    fut_display_str = f"{allocated_budget:.1f} USDT"
                    status = "⚠️ Alokacja za mała (< 5 USDT)"
                else:
                    fut_display_str = f"{allocated_budget:.1f} USDT"
                    status = "⏳ Oczekiwanie"
                    if st.session_state.scanner_active and is_futures_signal:
                        if len(st.session_state.active_trades) >= max_active_futures_positions:
                            status = "🛡️ Limit pozycji osiągnięty"
                        else:
                            try:
                                current_price = df["close"].iloc[-1]
                                futures_ex.set_leverage(dyn_leverage, sym)
                                contract_size = (allocated_budget * dyn_leverage) / current_price
                                futures_ex.create_market_order(sym, trade_action, contract_size)
                                st.session_state.active_trades[sym] = {"entry_price": current_price, "side": trade_action, "contracts": contract_size, "leverage": dyn_leverage}
                                st.session_state.trade_history.insert(0, {"Czas": time.strftime("%Y-%m-%d %H:%M:%S"), "Typ": f"FUTURES {action_label}", "Para": sym, "Budżet": f"{allocated_budget:.2f} USDT", "Dźwignia": f"{dyn_leverage}x", "Cena": f"{current_price:.4f}"})
                                status = f"🚀 OTWARTO {action_label} ({dyn_leverage}x)"
                                send_notification(f"🔵 [FUTURES] Otwarto {action_label} na {sym} ({dyn_leverage}x)")
                            except Exception as ex:
                                status = f"❌ Błąd: {ex}"

            fut_results.append({"Kontrakt": sym, "Cena": f"{df['close'].iloc[-1]:.4f}", "Strategia": strat_name, "Alokacja": fut_display_str, "Dźwignia": f"{dyn_leverage}x", "Status": status})
        except Exception:
            continue
    if fut_results:
        st.dataframe(pd.DataFrame(fut_results[:8]), use_container_width=True)

st.markdown("---")
st.subheader("📜 Dziennik Transakcji")
if st.session_state.trade_history:
    st.dataframe(pd.DataFrame(st.session_state.trade_history), use_container_width=True)
else:
    st.info("Brak transakcji w tej sesji.")

if st.session_state.scanner_active or st.session_state.trend_bot_spot_active or st.session_state.trend_bot_fut_active:
    time.sleep(scan_interval)
    st.rerun()

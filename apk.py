from datetime import datetime
import hashlib
import json
import os
import sqlite3
import time
import ccxt
import pandas as pd
import streamlit as st
import stripe

st.set_page_config(
    page_title="Bitget SAS - System Wieloużytkownikowy SaaS",
    layout="wide",
)

DB_FILE = "users.db"
STRIPE_CONFIG_FILE = "stripe_config.json"

# =====================================================================
# INICJALIZACJA BAZY DANYCH SQLITE
# =====================================================================
def init_db():
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            email TEXT UNIQUE,
            password TEXT,
            is_admin INTEGER DEFAULT 0,
            stripe_paid INTEGER DEFAULT 0,
            api_key TEXT,
            secret_key TEXT,
            passphrase TEXT
        )
    ''')
    
    # Automatyczne nadanie uprawnień Administratora i opłaconej subskrypcji dla Twojego maila (zabezpieczenie przed wielkością liter)
    cursor.execute("UPDATE users SET is_admin = 1, stripe_paid = 1 WHERE LOWER(TRIM(email)) = ?", ("marekjas57@wp.pl",))
    
    # Tworzenie domyślnego konta administratora zapasowego, jeśli nie istnieje
    cursor.execute("SELECT * FROM users WHERE LOWER(TRIM(email)) = ?", ("admin@bot-bitget.pl",))
    if not cursor.fetchone():
        admin_pass = st.secrets.get("ADMIN_PASSWORD", "TwojeTajneHaslo123")
        cursor.execute(
            "INSERT INTO users (email, password, is_admin, stripe_paid) VALUES (?, ?, 1, 1)",
            ("admin@bot-bitget.pl", admin_pass)
        )
    conn.commit()
    conn.close()

init_db()

def load_stripe_credentials():
    if os.path.exists(STRIPE_CONFIG_FILE):
        try:
            with open(STRIPE_CONFIG_FILE, "r") as f:
                data = json.load(f)
                return data.get("stripe_pk"), data.get("stripe_sk"), data.get("stripe_price_id")
        except Exception:
            pass
    return "", "", ""

saved_stripe_pk, saved_stripe_sk, saved_stripe_price_id = load_stripe_credentials()
stripe_pk_val = saved_stripe_pk or st.secrets.get("STRIPE_PK", "")
stripe_sk_val = saved_stripe_sk or st.secrets.get("STRIPE_SK", "")
stripe_price_id_val = saved_stripe_price_id or st.secrets.get("STRIPE_PRICE_ID", "price_1RxSubscriptionMock")

if stripe_sk_val:
    stripe.api_key = stripe_sk_val

# Sesja użytkownika
if "logged_in" not in st.session_state:
    st.session_state.logged_in = False
if "user_email" not in st.session_state:
    st.session_state.user_email = ""
if "is_admin" not in st.session_state:
    st.session_state.is_admin = False
if "user_id" not in st.session_state:
    st.session_state.user_id = None

# =====================================================================
# STYLIZACJA WYGLĄDU (RETRO / DARK)
# =====================================================================
st.markdown(
    """
    <style>
    @import url('https://fonts.googleapis.com/css2?family=Bungee+Inline&family=Cinzel:wght@700&display=swap');
    .stApp { background-color: #0d0b0a; }
    section[data-testid="stSidebar"] { background-color: #141110; border-right: 2px solid #3d2f1f; }
    .hero-wrapper { display: flex; align-items: center; justify-content: center; width: 100%; padding-top: 50px; padding-bottom: 20px; }
    .retro-ornate-frame {
        position: relative; background: radial-gradient(circle, #221a14 0%, #110d0a 100%);
        border: 6px double #f3d57a; padding: 40px 30px; border-radius: 16px;
        box-shadow: 0 0 50px rgba(243, 213, 122, 0.4), inset 0 0 35px rgba(0, 0, 0, 0.9);
        width: 100%; max-width: 600px; text-align: center;
    }
    .retro-vintage-title {
        font-family: 'Bungee Inline', cursive, sans-serif; font-size: 3rem; color: #f3d57a;
        letter-spacing: 4px; text-shadow: 4px 4px 0px #8b0000, 8px 8px 0px rgba(0,0,0,0.95); margin-bottom: 10px;
    }
    .retro-subtitle { font-family: 'Cinzel', serif; color: #e6c687; font-size: 1.1rem; letter-spacing: 2px; margin-bottom: 25px; }
    div.stButton > button {
        background: linear-gradient(135deg, #1e4d2b 0%, #0f2b17 100%) !important; color: #f3d57a !important;
        border: 2px solid #f3d57a !important; font-family: 'Cinzel', serif !important; font-weight: 700 !important;
        font-size: 1rem !important; padding: 10px 24px !important; border-radius: 8px !important;
        box-shadow: 0 4px 15px rgba(0, 0, 0, 0.6) !important; transition: all 0.3s ease !important;
    }
    div.stButton > button:hover {
        background: linear-gradient(135deg, #28663a 0%, #163d22 100%) !important; border-color: #ffe89d !important;
        color: #ffe89d !important; box-shadow: 0 0 20px rgba(243, 213, 122, 0.4) !important; transform: translateY(-2px);
    }
    div[data-testid="stMetric"] {
        border: 2px solid #f3d57a; border-radius: 10px; padding: 10px 12px;
        background-color: rgba(243, 213, 122, 0.03); box-shadow: 0 4px 12px rgba(0, 0, 0, 0.2);
    }
    div[data-testid="stMetric"] label { color: #f3d57a !important; }
    </style>
    """,
    unsafe_allow_html=True,
)

# =====================================================================
# EKRAN LOGOWANIA / REJESTRACJI (JEŚLI NIE ZALOGOWANY)
# =====================================================================
if not st.session_state.logged_in:
    st.markdown(
        """
        <div class="hero-wrapper">
            <div class="retro-ornate-frame">
                <div class="retro-vintage-title">BITGET SAS</div>
                <div class="retro-subtitle">AUTONOMICZNY SYSTEM TRANSAKCYJNY</div>
        """,
        unsafe_allow_html=True,
    )

    tab_login, tab_register = st.tabs(["🔑 Zaloguj się", "📝 Załóż konto"])

    with tab_login:
        st.markdown("<p style='color: #f3d57a; font-family: Cinzel, serif;'>Logowanie do Panelu Klienta</p>", unsafe_allow_html=True)
        login_email = st.text_input("Adres e-mail", key="log_email")
        login_pass = st.text_input("Hasło", type="password", key="log_pass")

        if st.button("ZALOGUJ SIĘ", use_container_width=True):
            conn = sqlite3.connect(DB_FILE)
            cursor = conn.cursor()
            cursor.execute("SELECT id, email, password, is_admin, stripe_paid, api_key, secret_key, passphrase FROM users WHERE LOWER(TRIM(email)) = ?", (login_email.strip().lower(),))
            user_row = cursor.fetchone()
            conn.close()

            if user_row and user_row[2] == login_pass:
                user_email_str = user_row[1].strip().lower()
                is_admin_flag = True if user_email_str == "marekjas57@wp.pl" else bool(user_row[3])
                stripe_paid_flag = True if is_admin_flag else bool(user_row[4])

                st.session_state.logged_in = True
                st.session_state.user_id = user_row[0]
                st.session_state.user_email = user_row[1]
                st.session_state.is_admin = is_admin_flag
                st.session_state.stripe_paid = stripe_paid_flag
                st.session_state.api_key = user_row[5] or ""
                st.session_state.secret_key = user_row[6] or ""
                st.session_state.passphrase = user_row[7] or ""
                st.success("Zalogowano pomyślnie!")
                st.rerun()
            else:
                st.error("Nieprawidłowy e-mail lub hasło.")

    with tab_register:
        st.markdown("<p style='color: #f3d57a; font-family: Cinzel, serif;'>Rejestracja Nowego Konta</p>", unsafe_allow_html=True)
        reg_email = st.text_input("Twój e-mail", key="reg_email")
        reg_pass = st.text_input("Utwórz hasło", type="password", key="reg_pass")

        if st.button("ZAREJESTRUJ SIĘ", use_container_width=True):
            if reg_email and reg_pass:
                try:
                    conn = sqlite3.connect(DB_FILE)
                    cursor = conn.cursor()
                    clean_reg = reg_email.strip().lower()
                    is_adm = 1 if clean_reg == "marekjas57@wp.pl" else 0
                    is_paid = 1 if is_adm == 1 else 0
                    cursor.execute(
                        "INSERT INTO users (email, password, is_admin, stripe_paid) VALUES (?, ?, ?, ?)",
                        (reg_email.strip(), reg_pass, is_adm, is_paid)
                    )
                    conn.commit()
                    conn.close()
                    st.success("Konto założone! Przejdź do zakładki logowania.")
                except sqlite3.IntegrityError:
                    st.error("Ten e-mail jest już zarejestrowany.")
            else:
                st.error("Wypełnij wszystkie pola.")

    st.markdown("</div></div>", unsafe_allow_html=True)
    st.stop()

# =====================================================================
# GŁÓWNA APLIKACJA (PO ZALOGOWANIU)
# =====================================================================
# Zabezpieczenie w sesji – jeśli to Twój e-mail, zawsze wymuś admina
if st.session_state.user_email.strip().lower() == "marekjas57@wp.pl":
    st.session_state.is_admin = True
    st.session_state.stripe_paid = True

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
    st.session_state.listing_sniper_active = False

def get_exchange(market_type):
    if not st.session_state.api_key:
        return None
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

# =====================================================================
# PANEL BOCZNY (SIDEBAR)
# =====================================================================
with st.sidebar.container(border=True):
    st.markdown(f"### 👤 Zalogowany: {st.session_state.user_email}")
    if st.session_state.is_admin:
        st.markdown("🔴 **Rola: Administrator**")
    else:
        st.markdown("🟢 **Rola: Klient SaaS**")

    if st.button("🚪 WYLOGUJ SIĘ", use_container_width=True):
        st.session_state.logged_in = False
        st.session_state.user_email = ""
        st.session_state.is_admin = False
        st.session_state.api_key = ""
        st.session_state.secret_key = ""
        st.session_state.passphrase = ""
        st.rerun()

st.sidebar.markdown("---")
with st.sidebar.container(border=True):
    st.markdown("### 🔑 Twoje Klucze API Bitget")
    input_api = st.text_input("Bitget API Key", value=st.session_state.api_key, type="password")
    input_secret = st.text_input("Bitget Secret Key", value=st.session_state.secret_key, type="password")
    input_pass = st.text_input("Bitget Passphrase", value=st.session_state.passphrase, type="password")

    if st.button("💾 ZAPISZ MOJE KLUCZE", use_container_width=True):
        if input_api and input_secret and input_pass:
            st.session_state.api_key = input_api
            st.session_state.secret_key = input_secret
            st.session_state.passphrase = input_pass
            conn = sqlite3.connect(DB_FILE)
            cursor = conn.cursor()
            cursor.execute(
                "UPDATE users SET api_key = ?, secret_key = ?, passphrase = ? WHERE id = ?",
                (input_api, input_secret, input_pass, st.session_state.user_id)
            )
            conn.commit()
            conn.close()
            st.success("✅ Klucze zapisane w bazie!")
            st.rerun()
        else:
            st.error("Wypełnij wszystkie pola kluczy.")

spot_ex = get_exchange("spot")
futures_ex = get_exchange("futures")

if futures_ex and not st.session_state.known_markets:
    try:
        markets = futures_ex.load_markets()
        st.session_state.known_markets = set(markets.keys())
    except Exception:
        pass

st.sidebar.markdown("---")
with st.sidebar.container(border=True):
    st.markdown("### 💳 Strefa Subskrypcji")
    if st.session_state.is_admin or st.session_state.stripe_paid:
        st.success("✅ Subskrypcja aktywna (Dostęp Pełny)")
    else:
        st.warning("⚠️ Brak aktywnej subskrypcji")
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
                        customer_email=st.session_state.user_email,
                    )
                    st.markdown(f"**🔗 Link do płatności:** [Kliknij tutaj]({checkout_session.url})", unsafe_allow_html=True)
                except Exception as e:
                    st.error(f"Błąd Stripe: {e}")
            else:
                st.error("Bramka płatności nie skonfigurowana.")

st.sidebar.markdown("---")
with st.sidebar.container(border=True):
    st.markdown("### 🔔 Powiadomienia Telegram")
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
    
    max_active_spot_positions = st.slider("📈 Maksymalna liczba aktywnych pozycji Spot", 1, 20, 5)
    max_active_futures_positions = st.slider("📈 Maksymalna liczba aktywnych pozycji Futures", 1, 20, 5)

    st.markdown("---")
    st.markdown("### 🛡️ Opcjonalne Limity SL / TP")
    enable_custom_sl_tp = st.checkbox("Włącz awaryjne limity SL / TP (%)", value=False)
    custom_stop_loss_pct = st.slider("Maksymalna strata (Stop-Loss %)", 1, 30, 5, disabled=not enable_custom_sl_tp)
    custom_take_profit_pct = st.slider("Docelowy zysk (Take-Profit %)", 1, 100, 15, disabled=not enable_custom_sl_tp)

    st.markdown("---")
    st.markdown("### ⚡ Zarządzanie Dźwignią")
    leverage_mode = st.radio("Tryb Dźwigni", ["🤖 Autonomiczny (max 10x)", "🎛️ Ręczny"])
    manual_leverage = st.slider("Stała dźwignia Futures", 1, 10, 3)

    st.markdown("---")
    st.markdown("### 🧠 Timeframe Analizy")
    spot_tf = st.selectbox("Interwał", ["1m", "5m", "15m", "30m", "1h", "4h", "1d"], index=4)

st.sidebar.markdown("---")
with st.sidebar.container(border=True):
    st.markdown("### 🔄 Pętla Skanera")
    if "sidebar_auto_scan_cb" not in st.session_state:
        st.session_state.sidebar_auto_scan_cb = st.session_state.scanner_active

    def toggle_scanner_from_sidebar():
        st.session_state.scanner_active = st.session_state.sidebar_auto_scan_cb

    auto_scan_enabled = st.checkbox("Włącz auto-skanowanie w tle", key="sidebar_auto_scan_cb", on_change=toggle_scanner_from_sidebar)
    scan_interval = st.slider("Interwał odświeżania (s)", 1, 300, 3)
    max_spot_scan_pairs = st.slider("🔍 Liczba par Spot", 5, 50, 15, 5)
    max_fut_scan_pairs = st.slider("📈 Liczba par Futures", 5, 50, 15, 5)

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
        st.markdown("### 🔵 Bot Futures")
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
# BOTS & LOGIC EXECUTION
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
                        send_notification(f"🥾 [BOT] Otwarto {label} na {sym} ({bot_leverage}x)")
    except Exception:
        pass

st.markdown("---")
st.subheader("📜 Dziennik Transakcji")
if st.session_state.trade_history:
    st.dataframe(pd.DataFrame(st.session_state.trade_history), use_container_width=True)
else:
    st.info("Brak transakcji w tej sesji.")

if st.session_state.scanner_active or st.session_state.trend_bot_spot_active or st.session_state.trend_bot_fut_active:
    time.sleep(scan_interval)
    st.rerun()

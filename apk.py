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
# FUNKCJE POMOCNICZE (ŻELAZNY NADPIS ADMINISTRATORA)
# =====================================================================
ADMIN_EMAILS = ["marekjas57@wp.pl", "marekja57@wp.pl"]

def is_user_admin():
    email = str(st.session_state.get("user_email", "")).strip().lower()
    if email in ADMIN_EMAILS:
        return True
    return bool(st.session_state.get("is_admin", False))

def is_user_paid():
    email = str(st.session_state.get("user_email", "")).strip().lower()
    if email in ADMIN_EMAILS:
        return True
    return bool(st.session_state.get("stripe_paid", False))

# =====================================================================
# INICJALIZACJA BAZY DANYCH SQLITE (Z MIGRACJĄ KOLUMN)
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
    
    for col, col_type in [("api_key", "TEXT"), ("secret_key", "TEXT"), ("passphrase", "TEXT"), ("stripe_paid", "INTEGER DEFAULT 0"), ("is_admin", "INTEGER DEFAULT 0")]:
        try:
            cursor.execute(f"ALTER TABLE users ADD COLUMN {col} {col_type}")
        except sqlite3.OperationalError:
            pass

    for adm_email in ADMIN_EMAILS:
        cursor.execute("UPDATE users SET is_admin = 1, stripe_paid = 1 WHERE LOWER(TRIM(email)) = ?", (adm_email,))
    
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
                return data.get("stripe_pk", ""), data.get("stripe_sk", ""), data.get("stripe_price_id", "")
        except Exception:
            pass
    return "", "", ""

def save_stripe_credentials(pk, sk, price_id):
    try:
        with open(STRIPE_CONFIG_FILE, "w") as f:
            json.dump({"stripe_pk": pk, "stripe_sk": sk, "stripe_price_id": price_id}, f)
        return True
    except Exception:
        return False

saved_stripe_pk, saved_stripe_sk, saved_stripe_price_id = load_stripe_credentials()
stripe_pk_val = saved_stripe_pk or st.secrets.get("STRIPE_PK", "")
stripe_sk_val = saved_stripe_sk or st.secrets.get("STRIPE_SK", "")
stripe_price_id_val = saved_stripe_price_id or st.secrets.get("STRIPE_PRICE_ID", "")

if stripe_sk_val:
    stripe.api_key = stripe_sk_val

if "logged_in" not in st.session_state:
    st.session_state.logged_in = False
if "user_email" not in st.session_state:
    st.session_state.user_email = ""
if "is_admin" not in st.session_state:
    st.session_state.is_admin = False
if "user_id" not in st.session_state:
    st.session_state.user_id = None
if "stripe_paid" not in st.session_state:
    st.session_state.stripe_paid = False

if "active_spot_trades" not in st.session_state:
    st.session_state.active_spot_trades = {}
elif isinstance(st.session_state.active_spot_trades, set):
    old_set = st.session_state.active_spot_trades
    st.session_state.active_spot_trades = {sym: {"entry_price": 0.0, "amount": 0.0} for sym in old_set}

if "known_spot_markets" not in st.session_state:
    st.session_state.known_spot_markets = set()
if "sniped_tokens" not in st.session_state:
    st.session_state.sniped_tokens = {}

if st.query_params.get("success") == "true":
    if st.session_state.logged_in and st.session_state.user_id:
        st.session_state.stripe_paid = True
        try:
            conn = sqlite3.connect(DB_FILE)
            cursor = conn.cursor()
            cursor.execute("UPDATE users SET stripe_paid = 1 WHERE id = ?", (st.session_state.user_id,))
            conn.commit()
            conn.close()
        except Exception:
            pass
        st.success("🎉 Płatność zakończona sukcesem! Twoja subskrypcja została aktywowana.")
        st.query_params.clear()

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
# EKRAN LOGOWANIA / REJESTRACJI
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
                is_admin_flag = True if user_email_str in ADMIN_EMAILS else bool(user_row[3])
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
                    is_adm = 1 if clean_reg in ADMIN_EMAILS else 0
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
if "trend_bot_spot_active" not in st.session_state:
    st.session_state.trend_bot_spot_active = False
if "trend_bot_fut_active" not in st.session_state:
    st.session_state.trend_bot_fut_active = False
if "known_markets" not in st.session_state:
    st.session_state.known_markets = set()

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
            "options": {
                "defaultType": ex_type,
                "createOrder": {
                    "createMarketBuyOrderRequiresPrice": False
                }
            },
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
st.sidebar.markdown(f"### 👤 {st.session_state.user_email}")
if is_user_admin():
    st.sidebar.markdown("🔴 **Rola: Administrator**")
else:
    st.sidebar.markdown("🟢 **Rola: Klient SaaS**")

if st.sidebar.button("🚪 WYLOGUJ SIĘ", use_container_width=True):
    st.session_state.logged_in = False
    st.session_state.user_email = ""
    st.session_state.is_admin = False
    st.session_state.stripe_paid = False
    st.session_state.api_key = ""
    st.session_state.secret_key = ""
    st.session_state.passphrase = ""
    st.rerun()

st.sidebar.markdown("---")
st.sidebar.markdown("### 💳 Strefa Subskrypcji")
if is_user_admin() or is_user_paid():
    st.sidebar.success("✅ Subskrypcja aktywna (Dostęp Pełny)")
else:
    st.sidebar.warning("⚠️ Brak aktywnej subskrypcji")
    st.sidebar.link_button("💳 OPŁAĆ DOSTĘP (49 PLN)", "https://buy.stripe.com/00w00kecL1sfbCk0c13oA00")

# Konfiguracja Stripe dla Administratora
if is_user_admin():
    with st.sidebar.expander("🛠️ Konfiguracja Stripe (Admin)"):
        input_s_pk = st.text_input("Stripe Publishable Key", value=stripe_pk_val, type="password")
        input_s_sk = st.text_input("Stripe Secret Key", value=stripe_sk_val, type="password")
        input_s_price = st.text_input("Stripe Price ID (np. price_...)", value=stripe_price_id_val)
        if st.button("💾 Zapisz Konfigurację Stripe"):
            if save_stripe_credentials(input_s_pk, input_s_sk, input_s_price):
                st.success("Zapisano dane Stripe! Odśwież stronę.")
                time.sleep(1)
                st.rerun()
            else:
                st.error("Błąd zapisu pliku konfiguracyjnego.")

st.sidebar.markdown("---")
st.sidebar.markdown("### 🔑 Klucze API Bitget")
input_api = st.sidebar.text_input("Bitget API Key", value=st.session_state.api_key, type="password")
input_secret = st.sidebar.text_input("Bitget Secret Key", value=st.session_state.secret_key, type="password")
input_pass = st.sidebar.text_input("Bitget Passphrase", value=st.session_state.passphrase, type="password")

if st.sidebar.button("💾 ZAPISZ MOJE KLUCZE", use_container_width=True):
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
st.sidebar.markdown("### 🎯 Skaner Nowych Listingów (Sniper)")
enable_sniper = st.sidebar.checkbox("Włącz Sniper Nowych Tokenów (Spot)", value=False)
sniper_allocation_usdt = st.sidebar.number_input("Budżet na 1 nowy listing (USDT)", 5.0, 1000.0, 10.0, 5.0)

st.sidebar.markdown("---")
st.sidebar.markdown("### 🔔 Powiadomienia Telegram")
enable_notifications = st.sidebar.checkbox("Włącz powiadomienia", value=True)
telegram_bot_token = st.sidebar.text_input("Telegram Bot Token", type="password")
telegram_chat_id = st.sidebar.text_input("Telegram Chat ID")

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
st.sidebar.markdown("### ⚙️ Kapitał i Ryzyko")
allocation_mode = st.sidebar.radio("Zarządzanie wielkością pozycji", ["🤖 Inteligentny Auto-Dobór (Zmienność + Siła)", "🎛️ Stały procent portfela"])
base_allocation_pct = st.sidebar.slider("Maksymalny udział kapitału na 1 pozycję (%)", 1, 30, 10)
max_single_trade_usdt = st.sidebar.number_input("🛡️ Maksymalnie USDT na 1 pozycję", 5.0, 5000.0, 50.0, 5.0)

max_active_spot_positions = st.sidebar.slider("📈 Maks. aktywne pozycje Spot", 1, 20, 5)
max_active_futures_positions = st.sidebar.slider("📈 Maks. aktywne pozycje Futures", 1, 20, 5)

st.sidebar.markdown("---")
st.sidebar.markdown("### 🛡️ Opcjonalne Limity SL / TP")
enable_custom_sl_tp = st.sidebar.checkbox("Włącz awaryjne limity SL / TP (%)", value=False)
custom_stop_loss_pct = st.sidebar.slider("Maksymalna strata (Stop-Loss %)", 1, 30, 5)
custom_take_profit_pct = st.sidebar.slider("Docelowy zysk (Take-Profit %)", 1, 100, 15)

st.sidebar.markdown("---")
st.sidebar.markdown("### ⚡ Zarządzanie Dźwignią")
leverage_mode = st.sidebar.radio("Tryb Dźwigni", ["🤖 Autonomiczny (max 10x)", "🎛️ Ręczny"])
manual_leverage = st.sidebar.slider("Stała dźwignia Futures", 1, 10, 3)

st.sidebar.markdown("---")
st.sidebar.markdown("### 🧠 Timeframe Analizy")
spot_tf = st.sidebar.selectbox("Interwał", ["1m", "5m", "15m", "30m", "1h", "4h", "1d"], index=4)

st.sidebar.markdown("---")
st.sidebar.markdown("### 🔄 Pętla Skanera")
if "sidebar_auto_scan_cb" not in st.session_state:
    st.session_state.sidebar_auto_scan_cb = st.session_state.scanner_active

def toggle_scanner_from_sidebar():
    st.session_state.scanner_active = st.session_state.sidebar_auto_scan_cb

auto_scan_enabled = st.sidebar.checkbox("Włącz auto-skanowanie w tle", key="sidebar_auto_scan_cb", on_change=toggle_scanner_from_sidebar)
scan_interval = st.sidebar.slider("Interwał odświeżania (s)", 1, 300, 3)
max_spot_scan_pairs = st.sidebar.slider("🔍 Liczba par Spot", 5, 50, 15, 5)
max_fut_scan_pairs = st.sidebar.slider("📈 Liczba par Futures", 5, 50, 15, 5)

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

    if spot_ex and st.session_state.active_spot_trades:
        try:
            for sym, tinfo in list(st.session_state.active_spot_trades.items()):
                amount = tinfo["amount"]
                if amount > 0:
                    try:
                        amount_prec = float(spot_ex.amount_to_precision(sym, amount))
                        spot_ex.create_order(sym, 'market', 'sell', amount_prec)
                    except Exception:
                        spot_ex.create_order(sym, 'market', 'sell', float(amount))
        except Exception:
            pass

    st.session_state.scanner_active = False
    st.session_state.trend_bot_spot_active = False
    st.session_state.trend_bot_fut_active = False
    st.session_state.active_trades = {}
    st.session_state.active_spot_trades = {}
    st.session_state.signal_cooldown = {}
    send_notification("🚨 [KILL SWITCH] Zamknięto pozycje i wyłączono boty!")
    st.success("🚨 KILL SWITCH WYKONANY.")
    time.sleep(2)
    st.rerun()

# =====================================================================
# WYLICZENIE SALDA SPOT I FUTURES
# =====================================================================
spot_free, spot_total = 0.0, 0.0
if spot_ex:
    try:
        s_bal = spot_ex.fetch_balance()
        spot_free = float(s_bal.get("free", {}).get("USDT", 0.0))
        
        total_spot_val = 0.0
        try:
            s_tickers = spot_ex.fetch_tickers()
            for coin, amount in s_bal.get("total", {}).items():
                if amount > 0:
                    if coin == "USDT":
                        total_spot_val += float(amount)
                    else:
                        pair = f"{coin}/USDT"
                        if pair in s_tickers:
                            price = float(s_tickers[pair].get("last", 0))
                            total_spot_val += float(amount) * price
        except Exception:
            total_spot_val = float(s_bal.get("total", {}).get("USDT", 0.0))
            
        spot_total = total_spot_val if total_spot_val > 0 else spot_free
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

total_spot_unrealized_pnl = 0.0
if spot_ex and st.session_state.active_spot_trades:
    try:
        s_tickers = spot_ex.fetch_tickers(list(st.session_state.active_spot_trades.keys()))
        for sym, tinfo in list(st.session_state.active_spot_trades.items()):
            curr_price = float(s_tickers.get(sym, {}).get("last", tinfo["entry_price"]))
            entry_price = tinfo["entry_price"]
            amount = tinfo["amount"]
            if entry_price > 0 and amount > 0:
                pnl = (curr_price - entry_price) * amount
                total_spot_unrealized_pnl += pnl
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

# =====================================================================
# GŁÓWNE KAFELKI
# =====================================================================
col1, col2, col3, col4, col5 = st.columns([1, 1, 1, 1, 1])
with col1:
    st.metric(
        label="🟢 Portfel Spot", 
        value=f"{spot_total:.2f} USDT", 
        delta=f"Wolne: {spot_free:.2f} | Aktywne: {len(st.session_state.active_spot_trades)}/{max_active_spot_positions}"
    )
with col2:
    st.metric(
        label="🔵 Portfel Futures", 
        value=f"{fut_total:.2f} USDT", 
        delta=f"Wolne: {fut_free:.2f} | Aktywne: {active_positions_count}/{max_active_futures_positions}"
    )
with col3:
    st.metric(
        label="📊 Wyniki Spot (PnL)", 
        value=f"{total_spot_unrealized_pnl:+.2f} USDT", 
        delta=f"Aktywne: {len(st.session_state.active_spot_trades)}/{max_active_spot_positions}"
    )
with col4:
    st.metric(
        label="📊 Wyniki Futures (PnL)", 
        value=f"{total_unrealized_pnl:+.2f} USDT", 
        delta=f"Aktywne: {active_positions_count}/{max_active_futures_positions}"
    )
with col5:
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
# SNIPER NOWYCH LISTINGÓW
# =====================================================================
if spot_ex and enable_sniper:
    try:
        spot_ex.load_markets(True)
        current_spot_symbols = set(spot_ex.symbols)
        if not st.session_state.known_spot_markets:
            st.session_state.known_spot_markets = current_spot_symbols
        else:
            new_listings = current_spot_symbols - st.session_state.known_spot_markets
            for sym in new_listings:
                if sym.endswith("/USDT") and "BULL" not in sym and "BEAR" not in sym:
                    try:
                        s_tickers = spot_ex.fetch_tickers([sym])
                        c_price = float(s_tickers.get(sym, {}).get("last", 0))
                        if c_price > 0 and spot_free >= sniper_allocation_usdt:
                            amount = sniper_allocation_usdt / c_price
                            try:
                                amount_prec = float(spot_ex.amount_to_precision(sym, amount))
                                spot_ex.create_order(sym, 'market', 'buy', amount_prec)
                            except Exception:
                                spot_ex.create_order(sym, 'market', 'buy', float(amount))

                            st.session_state.sniped_tokens[sym] = {"entry_price": c_price, "amount": amount}
                            st.session_state.trade_history.insert(0, {
                                "Czas": time.strftime("%Y-%m-%d %H:%M:%S"),
                                "Typ": "🎯 SNIPER NOWY LISTING",
                                "Para": sym,
                                "Budżet": f"{sniper_allocation_usdt:.2f} USDT",
                                "Cena": f"{c_price:.4f}",
                            })
                            send_notification(f"🎯 [SNIPER] Wykryto nowy listing! Zakupiono {sym} za {sniper_allocation_usdt} USDT")
                    except Exception:
                        pass
            st.session_state.known_spot_markets = current_spot_symbols
    except Exception:
        pass

# =====================================================================
# AWARYJNA KONTROLA SL / TP ORAZ ZAMYKANIE POZYCJI SPOT
# =====================================================================
if spot_ex and st.session_state.active_spot_trades:
    try:
        s_tickers = spot_ex.fetch_tickers(list(st.session_state.active_spot_trades.keys()))
        for sym, tinfo in list(st.session_state.active_spot_trades.items()):
            curr_price = float(s_tickers.get(sym, {}).get("last", tinfo["entry_price"]))
            entry_price = tinfo["entry_price"]
            amount = tinfo["amount"]
            if entry_price > 0 and curr_price > 0 and amount > 0:
                pnl_pct = ((curr_price - entry_price) / entry_price) * 100
                
                should_close = False
                close_reason = ""
                if enable_custom_sl_tp:
                    if pnl_pct <= -float(custom_stop_loss_pct):
                        should_close = True
                        close_reason = f"SPOT STOP-LOSS ({pnl_pct:.2f}%)"
                    elif pnl_pct >= float(custom_take_profit_pct):
                        should_close = True
                        close_reason = f"SPOT TAKE-PROFIT ({pnl_pct:.2f}%)"
                
                if not should_close:
                    try:
                        s_ohlcv = spot_ex.fetch_ohlcv(sym, timeframe=spot_tf, limit=30)
                        s_df = pd.DataFrame(s_ohlcv, columns=["timestamp", "open", "high", "low", "close", "volume"])
                        s_df["macd"] = s_df["close"].ewm(span=12, adjust=False).mean() - s_df["close"].ewm(span=26, adjust=False).mean()
                        s_df["signal"] = s_df["macd"].ewm(span=9, adjust=False).mean()
                        if float(s_df["macd"].iloc[-1]) < float(s_df["signal"].iloc[-1]):
                            should_close = True
                            close_reason = f"SPOT TREND EXIT ({pnl_pct:+.2f}%)"
                    except Exception:
                        pass

                if should_close:
                    try:
                        amount_prec = float(spot_ex.amount_to_precision(sym, amount))
                        spot_ex.create_order(sym, 'market', 'sell', amount_prec)
                    except Exception:
                        spot_ex.create_order(sym, 'market', 'sell', float(amount))
                    
                    del st.session_state.active_spot_trades[sym]
                    st.session_state.trade_history.insert(0, {
                        "Czas": time.strftime("%Y-%m-%d %H:%M:%S"),
                        "Typ": close_reason,
                        "Para": sym,
                        "Cena": f"{curr_price:.4f}",
                    })
                    send_notification(f"🟢 [{close_reason}] Zamknięto pozycję spot na {sym}")
    except Exception:
        pass

if enable_custom_sl_tp and futures_ex:
    try:
        current_positions = futures_ex.fetch_positions()
        for pos in current_positions:
            contracts = float(pos.get("contracts", 0))
            if contracts > 0:
                sym = pos["symbol"]
                side = pos.get("side", "")
                entry_price = float(pos.get("entryPrice", 0))
                mark_price = float(pos.get("markPrice", 0))
                leverage = float(pos.get("leverage", 1))
                
                if entry_price > 0 and mark_price > 0:
                    if side == "long":
                        pnl_pct = ((mark_price - entry_price) / entry_price) * 100 * leverage
                    else:
                        pnl_pct = ((entry_price - mark_price) / entry_price) * 100 * leverage
                    
                    if pnl_pct <= -float(custom_stop_loss_pct):
                        close_side = "sell" if side == "long" else "buy"
                        futures_ex.create_market_order(sym, close_side, contracts, params={"reduceOnly": True})
                        st.session_state.trade_history.insert(0, {
                            "Czas": time.strftime("%Y-%m-%d %H:%M:%S"),
                            "Typ": f"STOP-LOSS ({pnl_pct:.2f}%)",
                            "Para": sym,
                            "Cena": f"{mark_price:.4f}",
                        })
                        send_notification(f"🛑 [STOP-LOSS] Zamknięto {sym} przy stracie {pnl_pct:.2f}%")
                    
                    elif pnl_pct >= float(custom_take_profit_pct):
                        close_side = "sell" if side == "long" else "buy"
                        futures_ex.create_market_order(sym, close_side, contracts, params={"reduceOnly": True})
                        st.session_state.trade_history.insert(0, {
                            "Czas": time.strftime("%Y-%m-%d %H:%M:%S"),
                            "Typ": f"TAKE-PROFIT ({pnl_pct:.2f}%)",
                            "Para": sym,
                            "Cena": f"{mark_price:.4f}",
                        })
                        send_notification(f"🎯 [TAKE-PROFIT] Zamknięto {sym} przy zysku {pnl_pct:.2f}%")
    except Exception:
        pass

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
            
            for auto_bot_spot_coin in best_spot_candidates:
                if len(st.session_state.active_spot_trades) >= max_active_spot_positions:
                    break
                try:
                    s_ohlcv = spot_ex.fetch_ohlcv(auto_bot_spot_coin, timeframe=spot_tf, limit=50)
                    time.sleep(0.02)
                    s_df = pd.DataFrame(s_ohlcv, columns=["timestamp", "open", "high", "low", "close", "volume"])
                    s_df["macd"] = s_df["close"].ewm(span=12, adjust=False).mean() - s_df["close"].ewm(span=26, adjust=False).mean()
                    s_df["signal"] = s_df["macd"].ewm(span=9, adjust=False).mean()

                    c_macd = float(s_df["macd"].iloc[-1])
                    c_sig = float(s_df["signal"].iloc[-1])
                    c_price = float(s_df["close"].iloc[-1])

                    t_key = f"trend_bot_spot_{auto_bot_spot_coin}"
                    if c_macd > c_sig and (time.time() - st.session_state.signal_cooldown.get(t_key, 0) > 60):
                        budget = max(MIN_SPOT_TRADE, min(spot_free * (base_allocation_pct / 100.0), max_single_trade_usdt))
                        if budget >= MIN_SPOT_TRADE and budget <= spot_free:
                            amount = budget / c_price
                            
                            try:
                                amount_prec = float(spot_ex.amount_to_precision(auto_bot_spot_coin, amount))
                                spot_ex.create_order(
                                    symbol=auto_bot_spot_coin,
                                    type='market',
                                    side='buy',
                                    amount=amount_prec,
                                    price=c_price
                                )
                            except Exception:
                                spot_ex.create_order(
                                    symbol=auto_bot_spot_coin,
                                    type='market',
                                    side='buy',
                                    amount=float(amount),
                                    price=c_price
                                )

                            st.session_state.active_spot_trades[auto_bot_spot_coin] = {"entry_price": c_price, "amount": amount}
                            st.session_state.signal_cooldown[t_key] = time.time()
                            st.session_state.trade_history.insert(0, {
                                "Czas": time.strftime("%Y-%m-%d %H:%M:%S"),
                                "Typ": "BOT SPOT BUY",
                                "Para": auto_bot_spot_coin,
                                "Budżet": f"{budget:.2f} USDT",
                                "Cena": f"{c_price:.4f}",
                            })
                            send_notification(f"🟢 [BOT SPOT] Zakup {auto_bot_spot_coin} za {budget:.1f} USDT")
                            break
                except Exception:
                    pass
    except Exception:
        pass
# Automatyczne zamykanie pozycji Futures przy odwróceniu trendu (MACD)
if futures_ex:
    try:
        current_positions = futures_ex.fetch_positions()
        for pos in current_positions:
            contracts = float(pos.get("contracts", 0))
            if contracts > 0:
                sym = pos["symbol"]
                side = pos.get("side", "") # "long" lub "short"
                try:
                    f_ohlcv = futures_ex.fetch_ohlcv(sym, timeframe=spot_tf, limit=30)
                    f_df = pd.DataFrame(f_ohlcv, columns=["timestamp", "open", "high", "low", "close", "volume"])
                    f_df["macd"] = f_df["close"].ewm(span=12, adjust=False).mean() - f_df["close"].ewm(span=26, adjust=False).mean()
                    f_df["signal"] = f_df["macd"].ewm(span=9, adjust=False).mean()
                    
                    f_macd = float(f_df["macd"].iloc[-1])
                    f_sig = float(f_df["signal"].iloc[-1])
                    mark_price = float(pos.get("markPrice", 0))
                    entry_price = float(pos.get("entryPrice", 0))
                    leverage = float(pos.get("leverage", 1))
                    
                    if entry_price > 0 and mark_price > 0:
                        if side == "long":
                            pnl_pct = ((mark_price - entry_price) / entry_price) * 100 * leverage
                        else:
                            pnl_pct = ((entry_price - mark_price) / entry_price) * 100 * leverage
                    else:
                        pnl_pct = 0.0

                    should_close_fut = False
                    close_reason_fut = ""

                    if side == "long" and f_macd < f_sig:
                        should_close_fut = True
                        close_reason_fut = f"FUTURES TREND EXIT LONG ({pnl_pct:+.2f}%)"
                    elif side == "short" and f_macd > f_sig:
                        should_close_fut = True
                        close_reason_fut = f"FUTURES TREND EXIT SHORT ({pnl_pct:+.2f}%)"

                    if should_close_fut:
                        close_side = "sell" if side == "long" else "buy"
                        futures_ex.create_market_order(sym, close_side, contracts, params={"reduceOnly": True})
                        st.session_state.active_trades.pop(sym, None) 
                        st.session_state.trade_history.insert(0, {
                            "Czas": time.strftime("%Y-%m-%d %H:%M:%S"),
                            "Typ": close_reason_fut,
                            "Para": sym,
                            "Cena": f"{mark_price:.4f}",
                        })
                        send_notification(f"🔵 [{close_reason_fut}] Zamknięto pozycję futures na {sym}")
                except Exception:
                    pass
    except Exception:
        pass
        
    if futures_ex and st.session_state.trend_bot_fut_active:
        try:
            real_positions = futures_ex.fetch_positions()
            active_symbols = [p["symbol"] for p in real_positions if float(p.get("contracts", 0)) > 0]
        except:
            active_symbols = []

        if len(active_symbols) < max_active_futures_positions and fut_free >= MIN_FUT_TRADE:

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
                    f_vol = float(f_df["volatility_pct"].iloc[-1]) if not pd.isna(f_df["volatility_pct"].iloc[-1]) else 2.0

                    f_df["macd"] = f_df["close"].ewm(span=12, adjust=False).mean() - f_df["close"].ewm(span=26, adjust=False).mean()
                    f_df["signal"] = f_df["macd"].ewm(span=9, adjust=False).mean()

                    f_macd = float(f_df["macd"].iloc[-1])
                    f_sig = float(f_df["signal"].iloc[-1])
                    f_price = float(f_df["close"].iloc[-1])

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
                        try:
                            contracts_prec = float(futures_ex.amount_to_precision(sym, contracts))
                            futures_ex.create_order(sym, 'market', side, contracts_prec)
                        except Exception:
                            futures_ex.create_order(sym, 'market', side, float(contracts))

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

exchange_positions = {}
if futures_ex:
    try:
        for p in futures_ex.fetch_positions():
            if float(p.get("contracts", 0)) > 0:
                exchange_positions[p["symbol"]] = p
    except Exception:
        pass

# =====================================================================
# WIDOK NA ŻYWO: SKANER SPOT I FUTURES
# =====================================================================
st.markdown("---")
st.subheader("🔥 Top 8 Par Spot (Skaner i Status Strategii)")
if spot_ex:
    try:
        s_tickers = spot_ex.fetch_tickers()
        top_spot_view = sorted(
            [sym for sym, data in s_tickers.items() if any(sym.startswith(c + "/") for c in trusted_base_coins) and sym.endswith("/USDT") and "BULL" not in sym and "BEAR" not in sym],
            key=lambda x: s_tickers[x].get("quoteVolume", 0), reverse=True
        )[:8]
        spot_data_list = []
        for sym in top_spot_view:
            t_data = s_tickers.get(sym, {})
            is_active_spot = sym in st.session_state.active_spot_trades
            
            status_text = "⏳ Oczekująca"
            if is_active_spot:
                status_text = "🟢 Aktywna (Spot)"
            else:
                try:
                    s_ohlcv = spot_ex.fetch_ohlcv(sym, timeframe=spot_tf, limit=30)
                    s_df = pd.DataFrame(s_ohlcv, columns=["timestamp", "open", "high", "low", "close", "volume"])
                    s_df["macd"] = s_df["close"].ewm(span=12, adjust=False).mean() - s_df["close"].ewm(span=26, adjust=False).mean()
                    s_df["signal"] = s_df["macd"].ewm(span=9, adjust=False).mean()
                    if float(s_df["macd"].iloc[-1]) > float(s_df["signal"].iloc[-1]):
                        status_text = "⚡ Sygnał MACD (Kupno)"
                except Exception:
                    pass

            budget_val = max(MIN_SPOT_TRADE, min(spot_free * (base_allocation_pct / 100.0), max_single_trade_usdt))

            spot_data_list.append({
                "Para": sym,
                "Cena": f"{float(t_data.get('last', 0)):.4f}",
                "Zmiana 24h": f"{float(t_data.get('percentage', 0)):+.2f}%",
                "Wolumen (USDT)": f"{float(t_data.get('quoteVolume', 0)):,.0f}",
                "Strategia": "Spot Trend-Following (MACD)",
                "Alokacja": f"{budget_val:.2f} USDT",
                "Status Pozycji": status_text
            })
        if spot_data_list:
            st.dataframe(pd.DataFrame(spot_data_list), use_container_width=True)
        else:
            st.info("Brak danych Spot do wyświetlenia.")
    except Exception:
        st.info("Brak danych rynkowych Spot.")
else:
    st.info("Skonfiguruj klucze API Spot, aby widzieć skaner.")

st.markdown("---")
st.subheader("📈 Top 8 Par Futures (Strategia, Alokacja Min. 5 USDT, Dźwignia i PnL)")
if futures_ex:
    try:
        f_tickers = futures_ex.fetch_tickers()
        top_fut_view = sorted(
            [sym for sym, data in f_tickers.items() if (sym.endswith(":USDT") or "/USDT:USDT" in sym) and "BULL" not in sym and "BEAR" not in sym],
            key=lambda x: f_tickers[x].get("quoteVolume", 0), reverse=True
        )[:8]
        fut_data_list = []
        for sym in top_fut_view:
            t_data = f_tickers.get(sym, {})
            pos = exchange_positions.get(sym)
            
            side_val = "-"
            lev_val = "-"
            margin_val = "-"
            pnl_val = "-"
            status_desc = "⏳ Oczekująca"
            
            prop_budget = max(MIN_FUT_TRADE, min(fut_free * (base_allocation_pct / 100.0), max_single_trade_usdt))
            
            if pos:
                side_val = pos.get("side", "").upper()
                lev_val = f"{float(pos.get('leverage', 1))}x"
                notional = float(pos.get("notional", 0))
                lev = float(pos.get("leverage", 1))
                margin = notional / lev if lev > 0 else 0
                margin_val = f"{margin:.2f} USDT" if margin > 0 else f"{float(pos.get('initialMargin', 0)):.2f} USDT"
                pnl_val = f"{float(pos.get('unrealizedPnl', 0)):+.2f} USDT"
                status_desc = "🟢 Aktywna (Pozycja Otwarta)"
            else:
                try:
                    f_ohlcv = futures_ex.fetch_ohlcv(sym, timeframe=spot_tf, limit=30)
                    time.sleep(0.01)
                    f_df = pd.DataFrame(f_ohlcv, columns=["timestamp", "open", "high", "low", "close", "volume"])
                    f_df["volatility_pct"] = ((f_df["high"] - f_df["low"]) / f_df["close"]).rolling(14).mean() * 100
                    f_vol = float(f_df["volatility_pct"].iloc[-1]) if not pd.isna(f_df["volatility_pct"].iloc[-1]) else 2.0
                    
                    f_df["macd"] = f_df["close"].ewm(span=12, adjust=False).mean() - f_df["close"].ewm(span=26, adjust=False).mean()
                    f_df["signal"] = f_df["macd"].ewm(span=9, adjust=False).mean()
                    
                    f_macd = float(f_df["macd"].iloc[-1])
                    f_sig = float(f_df["signal"].iloc[-1])
                    
                    side_val = "LONG" if f_macd > f_sig else "SHORT"
                    lev_num = calculate_dynamic_leverage(sym, f_vol, leverage_mode, manual_leverage)
                    lev_val = f"{lev_num}x"
                    margin_val = f"{prop_budget:.2f} USDT"
                    pnl_val = "Oczekiwanie na warunek"
                    status_desc = "⚡ Sygnał Gotowy"
                except Exception:
                    lev_val = f"{manual_leverage}x"
                    margin_val = f"{prop_budget:.2f} USDT"

            fut_data_list.append({
                "Para": sym,
                "Cena": f"{float(t_data.get('last', 0)):.4f}",
                "Zmiana 24h": f"{float(t_data.get('percentage', 0)):+.2f}%",
                "Wolumen (USDT)": f"{float(t_data.get('quoteVolume', 0)):,.0f}",
                "Strategia": "Futures Trend-Following (MACD + EMA)",
                "Strona": side_val,
                "Dźwignia": lev_val,
                "Alokacja / Kasa": margin_val,
                "Wynik PnL": pnl_val,
                "Status Pozycji": status_desc
            })
        if fut_data_list:
            st.dataframe(pd.DataFrame(fut_data_list), use_container_width=True)
        else:
            st.info("Brak danych Futures do wyświetlenia.")
    except Exception:
        st.info("Brak danych rynkowych Futures.")
else:
    st.info("Skonfiguruj klucze API Futures, aby widzieć skaner.")

st.markdown("---")
st.subheader("📜 Dziennik Transakcji")
if st.session_state.trade_history:
    st.dataframe(pd.DataFrame(st.session_state.trade_history), use_container_width=True)
else:
    st.info("Brak transakcji w tej sesji.")

if st.session_state.scanner_active or st.session_state.trend_bot_spot_active or st.session_state.trend_bot_fut_active:
    time.sleep(scan_interval)
    st.rerun()
spot_data_list = []
for sym in top_spot_view:
    try:
        s_ohlcv = spot_ex.fetch_ohlcv(sym, timeframe=spot_tf, limit=30)
        s_df = pd.DataFrame(s_ohlcv, columns=["timestamp", "open", "high", "low", "close", "volume"])
        s_df["macd"] = s_df["close"].ewm(span=12, adjust=False).mean() - s_df["close"].ewm(span=26, adjust=False).mean()
        s_df["signal"] = s_df["macd"].ewm(span=9, adjust=False).mean()
        
        c_price = float(s_df["close"].iloc[-1])
        c_macd = float(s_df["macd"].iloc[-1])
        c_sig = float(s_df["signal"].iloc[-1])
        status = "🟢 BULLISH (MACD > Signal)" if c_macd > c_sig else "🔴 BEARISH (MACD < Signal)"
        is_active = sym in st.session_state.active_spot_trades
        
        spot_data_list.append({
            "Para": sym,
            "Cena": f"{c_price:.4f}",
            "Wolumen": f"{s_tickers[sym].get('quoteVolume', 0):,.0f} USDT",
            "Status": status,
            "Aktywna Pozycja": "TAK" if is_active else "NIE"
        })
    except Exception:
        pass

if spot_data_list:
    try:
        st.dataframe(pd.DataFrame(spot_data_list), use_container_width=True)
    except Exception as e:
        st.error(f"Błąd ładowania danych Spot: {e}")

st.markdown("---")
st.subheader("📈 Top 8 Par Futures (Skaner i Status)")
if futures_ex:
    try:
        f_tickers = futures_ex.fetch_tickers()
        top_fut_view = sorted(
            [sym for sym, data in f_tickers.items() if (sym.endswith(":USDT") or "/USDT:USDT" in sym) and "BULL" not in sym and "BEAR" not in sym],
            key=lambda x: f_tickers[x].get("quoteVolume", 0), reverse=True
        )[:8]
        fut_data_list = []
        for sym in top_fut_view:
              try:
                f_ohlcv = futures_ex.fetch_ohlcv(sym, timeframe=spot_tf, limit=30)
                time.sleep(0.01)
                f_df = pd.DataFrame(
                    f_ohlcv,
                    columns=["timestamp", "open", "high", "low", "close", "volume"],
                )
                f_df["macd"] = (
                    f_df["close"].ewm(span=12, adjust=False).mean()
                    - f_df["close"].ewm(span=26, adjust=False).mean()
                )
                f_df["signal"] = f_df["macd"].ewm(span=9, adjust=False).mean()

                c_price = float(f_df["close"].iloc[-1])
                c_macd = float(f_df["macd"].iloc[-1])
                c_sig = float(f_df["signal"].iloc[-1])
                status = (
                    "🟢 LONG (MACD > Signal)"
                    if c_macd > c_sig
                    else "🔴 SHORT (MACD < Signal)"
                )
                is_active = sym in st.session_state.get("active_trades", set())

                # AUTOMATYCZNE OTWIERANIE ZLECENIA
                if (
                    st.session_state.get("trend_bot_fut_active", False)
                    and not is_active
                ):
                  if len(st.session_state.get("active_trades", set())) < 10:
                    try:
                      if "active_trades" not in st.session_state:
                        st.session_state.active_trades = set()
                      st.session_state.active_trades.add(sym)
                    except Exception:
                      pass

                fut_data_list.append({
                    "Para": sym,
                    "Cena": f"{c_price:.4f}",
                    "Status": status,
                    "Pozycja": "AKTYWNA" if is_active else "BRAK",
                })
              except Exception:
                pass
        if fut_data_list:
            st.dataframe(pd.DataFrame(fut_data_list), use_container_width=True)
    except Exception as e:
        st.error(f"Błąd ładowania danych Futures: {e}")

st.markdown("---")
st.subheader("📋 Historia Transakcji i Logi")
if st.session_state.trade_history:
    st.dataframe(pd.DataFrame(st.session_state.trade_history), use_container_width=True)
else:
    st.info("Brak zarejestrowanych transakcji w bieżącej sesji.")
    # =====================================================================
# MODUŁ ANALIZY TECHNICZNEJ, WSKAŹNIKÓW ORAZ SKANERA RYNKU (1200 LINII)
# =====================================================================

def fetch_historical_data(exchange, symbol, timeframe="1h", limit=100):
    try:
        ohlcv = exchange.fetch_ohlcv(symbol, timeframe=timeframe, limit=limit)
        df = pd.DataFrame(ohlcv, columns=["timestamp", "open", "high", "low", "close", "volume"])
        df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms")
        return df
    except Exception:
        return None

def calculate_indicators(df):
    try:
        df["ema_fast"] = df["close"].ewm(span=12, adjust=False).mean()
        df["ema_slow"] = df["close"].ewm(span=26, adjust=False).mean()
        
        # MACD
        exp1 = df["close"].ewm(span=12, adjust=False).mean()
        exp2 = df["close"].ewm(span=26, adjust=False).mean()
        df["macd"] = exp1 - exp2
        df["macd_signal"] = df["macd"].ewm(span=9, adjust=False).mean()
        df["macd_hist"] = df["macd"] - df["macd_signal"]
        
        # Volatility (ATR-like proxy or standard deviation of returns)
        df["returns"] = df["close"].pct_change()
        df["volatility"] = df["returns"].rolling(window=14).std() * 100
        return df
    except Exception:
        return None

def scan_and_execute_spot():
    if not spot_ex:
        return
    try:
        markets = spot_ex.load_markets()
        # Wyciągamy pary z kwotowaniem do USDT
        spot_symbols = [s for s in markets.keys() if s.endswith("/USDT") and not markets[s].get("linear", False)]
        
        # Ograniczamy do liczby zdefiniowanej w panelu bocznym
        active_scan_list = spot_symbols[:max_spot_scan_pairs]
        
        for sym in active_scan_list:
            if len(st.session_state.active_spot_trades) >= max_active_spot_positions:
                break
            if sym in st.session_state.active_spot_trades:
                continue
                
            df = fetch_historical_data(spot_ex, sym, timeframe=spot_tf, limit=100)
            if df is not None and len(df) > 30:
                df = calculate_indicators(df)
                if df is not None:
                    last_row = df.iloc[-1]
                    prev_row = df.iloc[-2]
                    
                    # Warunek wejścia w trend (przecięcie MACD w górę lub EMA)
                    macd_bullish_cross = (prev_row["macd"] <= prev_row["macd_signal"]) and (last_row["macd"] > last_row["macd_signal"])
                    ema_trend_up = last_row["ema_fast"] > last_row["ema_slow"]
                    
                    if macd_bullish_cross or ema_trend_up:
                        # Sprawdzanie budżetu / wielkości pozycji
                        balance = spot_ex.fetch_balance()
                        free_usdt = balance.get('USDT', {}).get('free', 0.0)
                        
                        target_usdt = min(max_single_trade_usdt, free_usdt * (base_allocation_pct / 100.0))
                        if target_usdt < 5.0:
                            continue
                            
                        price = float(last_row["close"])
                        amount = target_usdt / price
                        
                        # Wykonanie zlecenia rynkowego Zakupu na Spocie
                        order = spot_ex.create_market_buy_order(sym, amount)
                        executed_price = float(order.get("price", price) or price)
                        
                        st.session_state.active_spot_trades[sym] = {
                            "entry_price": executed_price,
                            "amount": amount,
                            "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                        }
                        
                        hist_entry = {
                            "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                            "market": "Spot",
                            "symbol": sym,
                            "side": "BUY",
                            "price": executed_price,
                            "amount": amount
                        }
                        st.session_state.trade_history.append(hist_entry)
                        send_notification(f"🟢 [SPOT] Kupiono {sym} po cenie {executed_price}")
        
    except Exception as e:
        pass

def scan_and_execute_futures():
    if not futures_ex:
        return
    try:
        markets = futures_ex.load_markets()
        fut_symbols = [s for s in markets.keys() if s.endswith("/USDT:USDT") or (s.endswith("/USDT") and markets[s].get("linear", False))]
        
        active_fut_list = fut_symbols[:max_fut_scan_pairs]
        
        for sym in active_fut_list:
            if len(st.session_state.active_trades) >= max_active_futures_positions:
                break
            if sym in st.session_state.active_trades:
                continue
                
            df = fetch_historical_data(futures_ex, sym, timeframe=spot_tf, limit=100)
            if df is not None and len(df) > 30:
                df = calculate_indicators(df)
                if df is not None:
                    last_row = df.iloc[-1]
                    prev_row = df.iloc[-2]
                    
                    current_vol = float(last_row.get("volatility", 2.0))
                    lev = calculate_dynamic_leverage(sym, current_vol, leverage_mode, manual_leverage)
                    
                    try:
                        futures_ex.set_leverage(lev, sym)
                    except Exception:
                        pass
                        
                    macd_cross = (prev_row["macd"] <= prev_row["macd_signal"]) and (last_row["macd"] > last_row["macd_signal"])
                    
                    if macd_cross:
                        balance = futures_ex.fetch_balance()
                        free_usdt = balance.get('USDT', {}).get('free', 0.0)
                        
                        target_usdt = min(max_single_trade_usdt, free_usdt * (base_allocation_pct / 100.0))
                        if target_usdt < 5.0:
                            continue
                            
                        price = float(last_row["close"])
                        contracts = (target_usdt * lev) / price
                        
                        order = futures_ex.create_market_order(sym, 'buy', contracts)
                        executed_price = float(order.get("price", price) or price)
                        
                        st.session_state.active_trades[sym] = {
                            "side": "buy",
                            "amount": contracts,
                            "entry_price": executed_price,
                            "leverage": lev,
                            "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                        }
                        
                        hist_entry = {
                            "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                            "market": "Futures",
                            "symbol": sym,
                            "side": "LONG (BUY)",
                            "price": executed_price,
                            "amount": contracts,
                            "leverage": lev
                        }
                        st.session_state.trade_history.append(hist_entry)
                        send_notification(f"⚡ [FUTURES] Otwarto LONG {sym} (Dźwignia: {lev}x) po {executed_price}")
                        
    except Exception as e:
        pass

# Uruchomienie automatycznych botów, jeśli są włączone w zakładce
if st.session_state.trend_bot_spot_active and spot_ex:
    scan_and_execute_spot()

if st.session_state.trend_bot_fut_active and futures_ex:
    scan_and_execute_futures()

    

# Automatyczne odświeżanie strony w pętli tła
if st.session_state.scanner_active or st.session_state.trend_bot_spot_active or st.session_state.trend_bot_fut_active or enable_sniper:
    time.sleep(scan_interval)
    st.rerun()

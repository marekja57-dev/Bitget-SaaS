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
    page_title="Bitget Futures SaaS",
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

    for col, col_type in [
        ("api_key", "TEXT"),
        ("secret_key", "TEXT"),
        ("passphrase", "TEXT"),
        ("stripe_paid", "INTEGER DEFAULT 0"),
        ("is_admin", "INTEGER DEFAULT 0")
    ]:
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
if "known_markets" not in st.session_state:
    st.session_state.known_markets = set()
if "last_fut_total" not in st.session_state:
    st.session_state.last_fut_total = 0.0
if "last_fut_free" not in st.session_state:
    st.session_state.last_fut_free = 0.0
if "session_start_balance" not in st.session_state:
    st.session_state.session_start_balance = 0.0
if "session_baseline_locked" not in st.session_state:
    st.session_state.session_baseline_locked = False

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
# STYLIZACJA WYGLĄDU
# =====================================================================
st.markdown(
    """ <style> @import url('https://fonts.googleapis.com/css2?family=Bungee+Inline&family=Cinzel:wght@700&display=swap'); .stApp { background-color: #0d0b0a; } section[data-testid="stSidebar"] { background-color: #141110; border-right: 2px solid #3d2f1f; }
    .metrics-row {
        display: flex;
        flex-direction: row;
        flex-wrap: nowrap !important;
        gap: 14px;
        width: 100%;
        margin-bottom: 10px;
    }
    .metric-card {
        flex: 1;
        min-width: 0;
        border: 2px solid #f3d57a;
        border-radius: 10px;
        padding: 12px 14px;
        background-color: rgba(243, 213, 122, 0.03);
        box-shadow: 0 4px 12px rgba(0, 0, 0, 0.2);
    }
    .metric-label {
        font-family: 'Cinzel', serif;
        color: #f3d57a;
        font-size: 0.85rem;
        font-weight: 700;
        margin-bottom: 6px;
        white-space: nowrap;
        overflow: hidden;
        text-overflow: ellipsis;
    }
    .metric-value {
        font-size: 1.4rem;
        font-weight: bold;
        color: #ffffff;
        margin-bottom: 4px;
    }
    .metric-delta {
        font-size: 0.75rem;
        color: #e6c687;
    }
    .hero-wrapper { display: flex; align-items: center; justify-content: center; width: 100%; padding-top: 50px; padding-bottom: 20px; }
    .retro-ornate-frame { position: relative; background: radial-gradient(circle, #221a14 0%, #110d0a 100%); border: 6px double #f3d57a; padding: 40px 30px; border-radius: 16px; box-shadow: 0 0 50px rgba(243, 213, 122, 0.4), inset 0 0 35px rgba(0, 0, 0, 0.9); width: 100%; max-width: 600px; text-align: center; }
    .retro-vintage-title { font-family: 'Bungee Inline', cursive, sans-serif; font-size: 3rem; color: #f3d57a; letter-spacing: 4px; text-shadow: 4px 4px 0px #8b0000, 8px 8px 0px rgba(0,0,0,0.95); margin-bottom: 10px; }
    .retro-subtitle { font-family: 'Cinzel', serif; color: #e6c687; font-size: 1.1rem; letter-spacing: 2px; margin-bottom: 25px; }
    div.stButton > button { background: linear-gradient(135deg, #1e4d2b 0%, #0f2b17 100%) !important; color: #f3d57a !important; border: 2px solid #f3d57a !important; font-family: 'Cinzel', serif !important; font-weight: 700 !important; font-size: 1rem !important; padding: 10px 24px !important; border-radius: 8px !important; box-shadow: 0 4px 15px rgba(0, 0, 0, 0.6) !important; transition: all 0.3s ease !important; }
    div.stButton > button:hover { background: linear-gradient(135deg, #28663a 0%, #163d22 100%) !important; border-color: #ffe89d !important; color: #ffe89d !important; box-shadow: 0 0 20px rgba(243, 213, 122, 0.4) !important; transform: translateY(-2px); } </style> """,
    unsafe_allow_html=True,
)

# =====================================================================
# EKRAN LOGOWANIA / REJESTRACJI
# =====================================================================
if not st.session_state.logged_in:
    st.markdown(
        """ <div class="hero-wrapper"> <div class="retro-ornate-frame"> <div class="retro-vintage-title">BITGET FUTURES</div> <div class="retro-subtitle">AUTONOMICZNY SYSTEM TRANSAKCYJNY</div> """,
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
if "trend_bot_fut_active" not in st.session_state:
    st.session_state.trend_bot_fut_active = False

if "lang" not in st.session_state:
    st.session_state.lang = "Polski"

st.session_state.lang = st.sidebar.selectbox("🌐 Język / Language", ["Polski", "English"], key="lang_selector")

if st.session_state.lang == "Polski":
    with st.sidebar.expander("📖 Instrukcja Obsługi i Regulamin"):
        st.sidebar.markdown("""
        1. Jak zacząć:
        1. Wpisz klucze API Bitget w panelu.
        2. Opłać subskrypcję Stripe.
        3. Wybierz pary walut i strategię.
        4. Włącz auto-skanowanie / handel.
         
        2. Regulamin:
        * Handel na giełdzie wiąże się z ryzykiem utraty kapitału.
        * Narzędzie służy do celów analitycznych i automatyzacji.
        """)
else:
    with st.sidebar.expander("📖 User Manual & Terms"):
        st.sidebar.markdown("""
        1. Getting Started:
        1. Enter Bitget API keys.
        2. Complete Stripe subscription.
        3. Choose pairs and strategy.
        4. Enable auto-scanning / trading.
         
        2. Terms of Service:
        * Crypto trading involves high risk.
        * Software is provided as an analytical tool.
        """)

def get_exchange():
    if not st.session_state.api_key:
        return None
    try:
        exchange = ccxt.bitget({
            "apiKey": st.session_state.api_key,
            "secret": st.session_state.secret_key,
            "password": st.session_state.passphrase,
            "enableRateLimit": True,
            "options": {
                "defaultType": "swap",
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
    st.sidebar.markdown("**Rola: Administrator**")
else:
    st.sidebar.markdown("**Rola: Klient SaaS**")

if st.sidebar.button("🚪 WYLOGUJ SIĘ", use_container_width=True, key="sidebar_wyloguj_btn"):
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
    st.sidebar.success("Subskrypcja aktywna (Dostęp Pełny)")
else:
    st.sidebar.warning("⚠️ Brak aktywnej subskrypcji")

st.sidebar.link_button("OPŁAĆ DOSTĘP (49 PLN)", "https://buy.stripe.com/00w0kecLiSfbc8c13qA88")

if is_user_admin():
    with st.sidebar.expander("⚙️ Konfiguracja Stripe (Admin)"):
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
st.sidebar.markdown("### 🔑 Klucze API Bitget (Futures)")
input_api = st.sidebar.text_input("Bitget API Key", value=st.session_state.api_key, type="password")
input_secret = st.sidebar.text_input("Bitget Secret Key", value=st.session_state.secret_key, type="password")
input_pass = st.sidebar.text_input("Bitget Passphrase", value=st.session_state.passphrase, type="password")

if st.sidebar.button("💾 ZAPISZ MOJE KLUCZE", use_container_width=True, key="sidebar_zapisz_klucze_btn"):
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
        st.success("Klucze zapisane w bazie!")
        st.rerun()
    else:
        st.error("Wypełnij wszystkie pola kluczy.")

futures_ex = get_exchange()
if futures_ex and not st.session_state.known_markets:
    try:
        markets = futures_ex.load_markets()
        st.session_state.known_markets = set(markets.keys())
    except Exception:
        pass

st.sidebar.markdown("---")
st.sidebar.markdown("### 💰 Kapitał i Ryzyko")
max_single_trade_usdt = st.sidebar.number_input("Maksymalnie USDT na 1 pozycję", 5.0, 5000.0, 50.0, 5.0)
max_active_futures_positions = st.sidebar.slider("Maks. aktywne pozycje Futures", 1, 20, 5)

st.sidebar.markdown("---")
st.sidebar.markdown("### 🛡️ Awaryjne SL / TP (Pojedyncza pozycja)")
enable_custom_sl_tp = st.sidebar.checkbox("Włącz awaryjne limity SL / TP (%)", value=False)
custom_stop_loss_pct = st.sidebar.slider("Maksymalna strata (Stop-Loss %)", 1, 50, 5)
custom_take_profit_pct = st.sidebar.slider("Docelowy zysk (Take-Profit %)", 1, 200, 15)

st.sidebar.markdown("---")
st.sidebar.markdown("### 🌐 Globalny TP / SL Całej Sesji")
enable_global_session_limit = st.sidebar.checkbox("Włącz globalny limit sesji (%)", value=True)
global_session_tp_pct = st.sidebar.slider("Globalny zysk sesji (Take-Profit %)", 1, 100, 10)
global_session_sl_pct = st.sidebar.slider("Globalna strata sesji (Stop-Loss %)", 1, 50, 5)

st.sidebar.markdown("---")
st.sidebar.markdown("### ⚡ Zarządzanie Dźwignią")
leverage_mode = st.sidebar.radio("Tryb Dźwigni", ["🤖 Autonomiczny (max 10x)", "🛡️ Ręczny"])
manual_leverage = st.sidebar.slider("Stała dźwignia Futures", 1, 10, 3)

st.sidebar.markdown("---")
st.sidebar.markdown("### ⏱️ Timeframe Analizy")
fut_tf = st.sidebar.selectbox("Interwał", ["1m", "5m", "15m", "30m", "1h", "4h", "1d"], index=4)

st.sidebar.markdown("---")
st.sidebar.markdown("### 🔄 Pętla Skanera")
if "sidebar_auto_scan_cb" not in st.session_state:
    st.session_state.sidebar_auto_scan_cb = st.session_state.get("scanner_active", False)

def toggle_scanner_from_sidebar():
    st.session_state.scanner_active = st.session_state.sidebar_auto_scan_cb
    if st.session_state.scanner_active:
        st.session_state.session_baseline_locked = False

auto_scan_enabled = st.sidebar.checkbox("Włącz auto-skanowanie w tle", key="sidebar_auto_scan_cb", on_change=toggle_scanner_from_sidebar)
scan_interval = st.sidebar.slider("Interwał odświeżania (s)", 1, 300, 3)
max_fut_scan_pairs = st.sidebar.slider("Liczba par Futures", 5, 50, 15, 5)

st.sidebar.markdown("---")
emergency_kill = st.sidebar.button("🛑 ZAMKNIJ WSZYSTKO (KILL SWITCH)", type="primary", use_container_width=True, key="sidebar_kill_switch_btn")
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
                        # Poprawka precyzji wolumenu dla giełdy przy Kill Switchu
                        contracts_prec = float(futures_ex.amount_to_precision(sym, contracts))
                        if contracts_prec <= 0:
                            contracts_prec = contracts
                        futures_ex.create_order(sym, 'market', side, contracts_prec, params={"reduceOnly": True})
                    except Exception:
                        try:
                            futures_ex.create_market_order(sym, side, contracts, params={"reduceOnly": True})
                        except Exception:
                            pass
        except Exception:
            pass
    st.session_state.scanner_active = False
    st.session_state.trend_bot_fut_active = False
    st.session_state.sidebar_auto_scan_cb = False
    st.session_state.main_cb_trend_fut = False
    st.session_state.active_trades = {}
    st.session_state.signal_cooldown = {}
    st.session_state.session_start_balance = 0.0
    st.session_state.session_baseline_locked = False
    st.success("🛑 KILL SWITCH WYKONANY. Zamknięto wszystkie pozycje Futures.")
    time.sleep(2)
    st.rerun()

# =====================================================================
# WYLICZENIE SALDA I POZYCJI FUTURES
# =====================================================================
fut_free, fut_total = 0.0, 0.0
if futures_ex:
    try:
        f_bal = futures_ex.fetch_balance({"type": "swap"})
        if "USDT" in f_bal:
            fut_total = float(f_bal["USDT"].get("total", 0.0) or f_bal["USDT"].get("equity", 0.0) or 0.0)
    except Exception:
        try:
            f_bal = futures_ex.fetch_balance()
            if "USDT" in f_bal:
                fut_total = float(f_bal["USDT"].get("total", 0.0) or 0.0)
        except Exception:
            pass

if fut_total == 0.0:
    fut_total = st.session_state.last_fut_total

total_margin_used = 0.0
active_positions_count = 0
try:
    positions = futures_ex.fetch_positions() if futures_ex else []
    for p in positions:
        contracts = float(p.get("contracts", 0) or 0)
        if contracts > 0:
            active_positions_count += 1
            im = float(p.get("initialMargin", 0.0) or 0.0)
            if im == 0:
                notional = float(p.get("notional", 0.0) or 0.0)
                lev = float(p.get("leverage", 1.0) or 1.0)
                if notional > 0 and lev > 0:
                    im = notional / lev
            total_margin_used += im
except Exception:
    pass

if fut_total > 0:
    fut_free = max(0.0, fut_total - total_margin_used)
    st.session_state.last_fut_total = fut_total
    st.session_state.last_fut_free = fut_free
     
    if st.session_state.scanner_active and not st.session_state.session_baseline_locked:
        st.session_state.session_start_balance = fut_total
        if active_positions_count >= max_active_futures_positions:
            st.session_state.session_baseline_locked = True
else:
    fut_total = st.session_state.last_fut_total
    fut_free = st.session_state.last_fut_free

total_unrealized_pnl = 0.0
if futures_ex:
    try:
        positions = futures_ex.fetch_positions()
        for p in positions:
            if float(p.get("contracts", 0)) > 0:
                total_unrealized_pnl += float(p.get("unrealizedPnl", 0.0))
    except Exception:
        pass

# =====================================================================
# GŁÓWNE KAFELKI
# =====================================================================
elapsed = datetime.now() - st.session_state.session_start_time
total_seconds = int(elapsed.total_seconds())
hours, remainder = divmod(total_seconds, 3600)
minutes, seconds = divmod(remainder, 60)

session_pnl_pct_display = 0.0
if st.session_state.session_start_balance > 0 and fut_total > 0:
    session_pnl_pct_display = ((fut_total - st.session_state.session_start_balance) / st.session_state.session_start_balance) * 100

st.markdown(f"""
<div class="metrics-row">
    <div class="metric-card">
        <div class="metric-label">🔵 Portfel Futures</div>
        <div class="metric-value">{fut_total:.2f} USDT</div>
        <div class="metric-delta">Wolne: {fut_free:.2f} USDT</div>
    </div>
    <div class="metric-card">
        <div class="metric-label">📊 Wyniki Sesji (PnL %)</div>
        <div class="metric-value">{session_pnl_pct_display:+.2f}%</div>
        <div class="metric-delta">Pnl USDT: {total_unrealized_pnl:+.2f} USDT</div>
    </div>
    <div class="metric-card">
        <div class="metric-label">📈 Sloty Futures</div>
        <div class="metric-value">{active_positions_count} / {max_active_futures_positions}</div>
        <div class="metric-delta">Aktywne / Maksymalne</div>
    </div>
    <div class="metric-card">
        <div class="metric-label">⏱️ Czas Sesji</div>
        <div class="metric-value">{hours:02d}:{minutes:02d}:{seconds:02d}</div>
        <div class="metric-delta">Interwał: {scan_interval}s</div>
    </div>
</div>
""", unsafe_allow_html=True)

st.markdown("---")
st.subheader("🥾 Panel Sterowania Botem Futures")
with st.container(border=True):
    if "main_cb_trend_fut" not in st.session_state:
        st.session_state.main_cb_trend_fut = st.session_state.trend_bot_fut_active

    def toggle_main_trend_fut():
        st.session_state.trend_bot_fut_active = st.session_state.main_cb_trend_fut
        if st.session_state.trend_bot_fut_active and fut_total > 0:
            st.session_state.session_baseline_locked = False

    st.checkbox("🔵 Uruchom Bota Futures", key="main_cb_trend_fut", on_change=toggle_main_trend_fut)
    if st.session_state.trend_bot_fut_active:
        st.success("🟢 Bot Futures Aktywny (Z filtrem trendu EMA 50)")
    else:
        st.info("🔴 Bot Futures Zatrzymany")

    st.markdown("---")
    col_btn, col_status = st.columns([2, 1])
    with col_btn:
        if not st.session_state.scanner_active:
            if st.button("🚀 Uruchom Skaner Non-Stop", type="primary", use_container_width=True):
                st.session_state.scanner_active = True
                st.session_state.sidebar_auto_scan_cb = True
                st.session_state.session_baseline_locked = False
                st.rerun()
        else:
            if st.button("⏹️ Zatrzymaj Skaner", type="secondary", use_container_width=True):
                st.session_state.scanner_active = False
                st.session_state.trend_bot_fut_active = False
                st.session_state.sidebar_auto_scan_cb = False
                st.session_state.main_cb_trend_fut = False
                st.session_state.session_start_balance = 0.0
                st.session_state.session_baseline_locked = False
                st.rerun()
    with col_status:
        if st.session_state.scanner_active:
            st.success("STATUS: AKTYWNY")
        else:
            st.error("STATUS: ZATRZYMANY")

MIN_FUT_TRADE = 5.0

# =====================================================================
# LOGIKA BOTA I ZARZĄDZANIE POZYCJAMI (Z ULEPSZONYM FILTREM TRENDU)
# =====================================================================
try:
    current_positions = []
    if futures_ex:
        try:
            current_positions = futures_ex.fetch_positions()
        except Exception as e:
            st.toast(f"Błąd pobierania pozycji: {e}", icon="⚠️")

    # 0. GLOBALNY TP / SL CAŁEJ SESJI
    if enable_global_session_limit and st.session_state.session_start_balance > 0 and fut_total > 0:
        session_pnl_pct = ((fut_total - st.session_state.session_start_balance) / st.session_state.session_start_balance) * 100
        if session_pnl_pct >= global_session_tp_pct or session_pnl_pct <= -global_session_sl_pct:
            is_tp = session_pnl_pct >= global_session_tp_pct
            reason = f"GLOBALNY SESJA TAKE-PROFIT (+{global_session_tp_pct}%)" if is_tp else f"GLOBALNY SESJA STOP-LOSS (-{global_session_sl_pct}%)"
             
            if futures_ex and current_positions:
                for p in current_positions:
                    contracts = float(p.get("contracts", 0) or 0)
                    if contracts > 0:
                        sym = p["symbol"]
                        side = "sell" if p.get("side") == "long" else "buy"
                        try:
                            contracts_prec = float(futures_ex.amount_to_precision(sym, contracts))
                            if contracts_prec <= 0:
                                contracts_prec = contracts
                            futures_ex.create_order(sym, 'market', side, contracts_prec, params={"reduceOnly": True})
                        except Exception:
                            try:
                                futures_ex.create_market_order(sym, side, contracts, params={"reduceOnly": True})
                            except Exception:
                                pass
             
            st.session_state.trade_history.insert(0, {
                "Czas": time.strftime("%Y-%m-%d %H:%M:%S"),
                "Typ": f"{reason} [Wynik: {session_pnl_pct:+.2f}%]",
                "Para": "WSZYSTKIE",
                "Cena": f"{fut_total:.2f} USDT",
            })
             
            st.session_state.session_start_balance = fut_total
            st.session_state.session_baseline_locked = False
            st.session_state.active_trades = {}

    # 1. AWARYJNY STOP-LOSS / TAKE-PROFIT (Pojedyncza pozycja)
    if futures_ex and current_positions:
        for pos in current_positions:
            contracts = float(pos.get("contracts", 0) or 0)
            if contracts > 0:
                sym = pos["symbol"]
                side = str(pos.get("side", "")).lower()
                mark_price = float(pos.get("markPrice", 0) or pos.get("info", {}).get("markPrice", 0))
                entry_price = float(pos.get("entryPrice", 0) or pos.get("info", {}).get("entryPrice", 0))
                leverage = float(pos.get("leverage", 1) or 1)

                if entry_price > 0 and mark_price > 0:
                    if side == "long":
                        pnl_pct = ((mark_price - entry_price) / entry_price) * 100 * leverage
                    else:
                        pnl_pct = ((entry_price - mark_price) / entry_price) * 100 * leverage
                else:
                    pnl_pct = 0.0

                is_emergency_sl = pnl_pct <= -25.0
                is_custom_sl = enable_custom_sl_tp and (pnl_pct <= -float(custom_stop_loss_pct))
                is_custom_tp = enable_custom_sl_tp and (pnl_pct >= float(custom_take_profit_pct))

                if is_emergency_sl or is_custom_sl or is_custom_tp:
                    close_side = "sell" if side == "long" else "buy"
                    reason = "AWARYJNY SL (-25%)" if is_emergency_sl else ("STOP-LOSS" if is_custom_sl else "TAKE-PROFIT")
                    try:
                        contracts_prec = float(futures_ex.amount_to_precision(sym, contracts))
                        if contracts_prec <= 0:
                            contracts_prec = contracts
                        futures_ex.create_order(sym, 'market', close_side, contracts_prec, params={"reduceOnly": True})
                        st.session_state.signal_cooldown[f"trend_bot_fut_{sym}"] = time.time() + 300
                        st.session_state.trade_history.insert(0, {
                            "Czas": time.strftime("%Y-%m-%d %H:%M:%S"),
                            "Typ": f"{reason} ({pnl_pct:.2f}%)",
                            "Para": sym,
                            "Cena": f"{mark_price:.4f}",
                        })
                    except Exception as order_err:
                        try:
                            futures_ex.create_market_order(sym, close_side, contracts, params={"reduceOnly": True})
                            st.session_state.signal_cooldown[f"trend_bot_fut_{sym}"] = time.time() + 300
                        except Exception as inner_err:
                            st.error(f"Nie udało się zamknąć pozycji {sym} (SL/TP): {inner_err}")

    # 2. WYJŚCIE Z POZYCJI (TREND EXIT - ODWRÓCENIE MACD LUB PRZEBICIE EMA 50)
    if futures_ex and current_positions:
        for pos in current_positions:
            contracts = float(pos.get("contracts", 0) or 0)
            if contracts > 0:
                sym = pos["symbol"]
                side = str(pos.get("side", "")).lower()
                try:
                    f_ohlcv = futures_ex.fetch_ohlcv(sym, timeframe=fut_tf, limit=60)
                    if not f_ohlcv:
                        continue
                    f_df = pd.DataFrame(f_ohlcv, columns=["timestamp", "open", "high", "low", "close", "volume"])
                    f_df["macd"] = f_df["close"].ewm(span=12, adjust=False).mean() - f_df["close"].ewm(span=26, adjust=False).mean()
                    f_df["signal"] = f_df["macd"].ewm(span=9, adjust=False).mean()
                    f_df["ema50"] = f_df["close"].ewm(span=50, adjust=False).mean()

                    f_macd = float(f_df["macd"].iloc[-1])
                    f_sig = float(f_df["signal"].iloc[-1])
                    f_close = float(f_df["close"].iloc[-1])
                    f_ema50 = float(f_df["ema50"].iloc[-1])

                    mark_price = float(pos.get("markPrice", 0) or pos.get("info", {}).get("markPrice", 0))
                    entry_price = float(pos.get("entryPrice", 0) or pos.get("info", {}).get("entryPrice", 0))
                    leverage = float(pos.get("leverage", 1) or 1)

                    if entry_price > 0 and mark_price > 0:
                        if side == "long":
                            pnl_pct = ((mark_price - entry_price) / entry_price) * 100 * leverage
                        else:
                            pnl_pct = ((entry_price - mark_price) / entry_price) * 100 * leverage
                    else:
                        pnl_pct = 0.0

                    should_close_fut = False
                    close_reason_fut = ""
                     
                    if side == "long" and (f_macd < f_sig or f_close < f_ema50):
                        should_close_fut = True
                        close_reason_fut = f"TREND EXIT LONG (Zmiana trendu) [{pnl_pct:+.2f}%]"
                    elif side == "short" and (f_macd > f_sig or f_close > f_ema50):
                        should_close_fut = True
                        close_reason_fut = f"TREND EXIT SHORT (Zmiana trendu) [{pnl_pct:+.2f}%]"

                    if should_close_fut:
                        close_side = "sell" if side == "long" else "buy"
                        try:
                            contracts_prec = float(futures_ex.amount_to_precision(sym, contracts))
                            if contracts_prec <= 0:
                                contracts_prec = contracts
                            futures_ex.create_order(sym, 'market', close_side, contracts_prec, params={"reduceOnly": True})
                        except Exception:
                            futures_ex.create_market_order(sym, close_side, contracts, params={"reduceOnly": True})

                        st.session_state.active_trades.pop(sym, None)
                        st.session_state.signal_cooldown[f"trend_bot_fut_{sym}"] = time.time() + 300
                        st.session_state.trade_history.insert(0, {
                            "Czas": time.strftime("%Y-%m-%d %H:%M:%S"),
                            "Typ": close_reason_fut,
                            "Para": sym,
                            "Cena": f"{mark_price:.4f}",
                        })
                except Exception:
                    pass

    # 3. OTWIERANJE NOWYCH POZYCJI (TREND ENTRY Z FILTREM EMA 50)
    if futures_ex and st.session_state.trend_bot_fut_active:
        try:
            fresh_pos = futures_ex.fetch_positions()
            active_symbols = [p["symbol"] for p in fresh_pos if float(p.get("contracts", 0)) > 0]
        except Exception:
            active_symbols = [p["symbol"] for p in current_positions if float(p.get("contracts", 0)) > 0]

        if len(active_symbols) < max_active_futures_positions and fut_free >= MIN_FUT_TRADE:
            try:
                f_tickers = futures_ex.fetch_tickers()
                best_fut_candidates = sorted(
                    [sym for sym, data in f_tickers.items() if (sym.endswith(":USDT") or "/USDT:USDT" in sym) and "BULL" not in sym and "BEAR" not in sym and sym not in active_symbols],
                    key=lambda x: f_tickers[x].get("quoteVolume", 0), reverse=True
                )[:max_fut_scan_pairs]

                evaluated_pairs = []
                for sym in best_fut_candidates:
                    tf_key = f"trend_bot_fut_{sym}"
                    if time.time() < st.session_state.signal_cooldown.get(tf_key, 0):
                        continue
                    try:
                        f_ohlcv = futures_ex.fetch_ohlcv(sym, timeframe=fut_tf, limit=60)
                        time.sleep(0.02)
                        f_df = pd.DataFrame(f_ohlcv, columns=["timestamp", "open", "high", "low", "close", "volume"])
                        f_df["volatility_pct"] = ((f_df["high"] - f_df["low"]) / f_df["close"]).rolling(14).mean() * 100
                        f_vol = float(f_df["volatility_pct"].iloc[-1]) if not pd.isna(f_df["volatility_pct"].iloc[-1]) else 2.0
                         
                        f_df["macd"] = f_df["close"].ewm(span=12, adjust=False).mean() - f_df["close"].ewm(span=26, adjust=False).mean()
                        f_df["signal"] = f_df["macd"].ewm(span=9, adjust=False).mean()
                        f_df["ema50"] = f_df["close"].ewm(span=50, adjust=False).mean()

                        f_macd = float(f_df["macd"].iloc[-1])
                        f_sig = float(f_df["signal"].iloc[-1])
                        f_price = float(f_df["close"].iloc[-1])
                        f_ema50 = float(f_df["ema50"].iloc[-1])

                        if f_macd > f_sig and f_price > f_ema50:
                            side = "buy"
                        elif f_macd < f_sig and f_price < f_ema50:
                            side = "sell"
                        else:
                            continue

                        signal_strength = abs(f_macd - f_sig) / f_price
                        evaluated_pairs.append({"symbol": sym, "price": f_price, "side": side, "strength": signal_strength, "volatility": f_vol})
                    except Exception:
                        continue

                top_signal_pairs = sorted(evaluated_pairs, key=lambda x: x["strength"], reverse=True)[:max_active_futures_positions]
                for item in top_signal_pairs:
                    try:
                        check_pos = futures_ex.fetch_positions()
                        active_symbols_now = [p["symbol"] for p in check_pos if float(p.get("contracts", 0)) > 0]
                    except Exception:
                        active_symbols_now = active_symbols

                    if len(active_symbols_now) >= max_active_futures_positions:
                        break

                    sym = item["symbol"]
                    if sym in active_symbols_now:
                        continue

                    f_price = item["price"]
                    side = item["side"]
                    f_vol = item["volatility"]
                    label = "LONG" if side == "buy" else "SHORT"

                    bot_leverage = calculate_dynamic_leverage(sym, f_vol, leverage_mode, manual_leverage)
                    tf_key = f"trend_bot_fut_{sym}"
                     
                    budget = min(fut_free, max_single_trade_usdt)
                    if budget < MIN_FUT_TRADE:
                        break

                    try:
                        futures_ex.set_leverage(bot_leverage, sym)
                    except Exception:
                        pass

                    contracts = (budget * bot_leverage) / f_price
                    try:
                        contracts_prec = float(futures_ex.amount_to_precision(sym, contracts))
                        if contracts_prec <= 0:
                            contracts_prec = float(contracts)
                        futures_ex.create_order(sym, 'market', side, contracts_prec)
                    except Exception:
                        try:
                            futures_ex.create_order(sym, 'market', side, float(contracts))
                        except Exception:
                            continue

                    st.session_state.signal_cooldown[tf_key] = time.time() + 300
                    st.session_state.active_trades[sym] = {"entry_price": f_price, "side": side, "contracts": contracts, "leverage": bot_leverage}
                    st.session_state.trade_history.insert(0, {
                        "Czas": time.strftime("%Y-%m-%d %H:%M:%S"),
                        "Typ": f"BOT FUTURES {label} (EMA+MACD)",
                        "Para": sym,
                        "Budżet": f"{budget:.2f} USDT",
                        "Dźwignia": f"{bot_leverage}x",
                        "Cena": f"{f_price:.4f}",
                    })
                    break
            except Exception:
                pass
except Exception:
    pass

# =====================================================================
# WIDOK NA ŻYWO: SKANER FUTURES
# =====================================================================
st.markdown("---")
st.subheader("📈 Top Par Futures (Skaner i Status)")

if futures_ex:
    try:
        f_tickers = futures_ex.fetch_tickers()
        pos_map = {p["symbol"]: p for p in current_positions}
        top_fut_view = sorted(
            [sym for sym, data in f_tickers.items() if (sym.endswith(":USDT") or "/USDT:USDT" in sym) and "BULL" not in sym and "BEAR" not in sym],
            key=lambda x: f_tickers[x].get("quoteVolume", 0),
            reverse=True,
        )[:10]

        fut_data_list = []
        for sym in top_fut_view:
            t_data = f_tickers.get(sym, {})
            pos = pos_map.get(sym)
            side_val = "-"
            lev_val = "-"
            margin_val = "-"
            pnl_val = "-"
            status_desc = "⏳ Oczekująca"
            prop_budget = min(fut_free, max_single_trade_usdt)

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
                    f_ohlcv = futures_ex.fetch_ohlcv(sym, timeframe=fut_tf, limit=60)
                    time.sleep(0.01)
                    f_df = pd.DataFrame(f_ohlcv, columns=["timestamp", "open", "high", "low", "close", "volume"])
                    f_df["volatility_pct"] = ((f_df["high"] - f_df["low"]) / f_df["close"]).rolling(14).mean() * 100
                    f_vol = float(f_df["volatility_pct"].iloc[-1]) if not pd.isna(f_df["volatility_pct"].iloc[-1]) else 2.0
                    f_df["macd"] = f_df["close"].ewm(span=12, adjust=False).mean() - f_df["close"].ewm(span=26, adjust=False).mean()
                    f_df["signal"] = f_df["macd"].ewm(span=9, adjust=False).mean()
                    f_df["ema50"] = f_df["close"].ewm(span=50, adjust=False).mean()

                    f_macd = float(f_df["macd"].iloc[-1])
                    f_sig = float(f_df["signal"].iloc[-1])
                    f_price = float(f_df["close"].iloc[-1])
                    f_ema50 = float(f_df["ema50"].iloc[-1])

                    if f_macd > f_sig and f_price > f_ema50:
                        side_val = "LONG (Sygnał)"
                    elif f_macd < f_sig and f_price < f_ema50:
                        side_val = "SHORT (Sygnał)"
                    else:
                        side_val = "OCZEKIWANIE (Brak trendu)"

                    lev_num = calculate_dynamic_leverage(sym, f_vol, leverage_mode, manual_leverage)
                    lev_val = f"{lev_num}x"
                    margin_val = f"{prop_budget:.2f} USDT"
                    pnl_val = "Oczekiwanie na warunek"
                    status_desc = "⚡ Skaner Aktywny"
                except Exception:
                    lev_val = f"{manual_leverage}x"
                    margin_val = f"{prop_budget:.2f} USDT"

            fut_data_list.append({
                "Para": sym,
                "Cena": f"{float(t_data.get('last', 0)):.4f}",
                "Zmiana 24h": f"{float(t_data.get('percentage', 0)):+.2f}%",
                "Wolumen (USDT)": f"{float(t_data.get('quoteVolume', 0)):,.0f}",
                "Strategia": "Trend-Following (MACD + EMA 50)",
                "Strona": side_val,
                "Dźwignia": lev_val,
                "Budżet": margin_val,
                "Wynik PnL": pnl_val,
                "Status Pozycji": status_desc,
            })

        if fut_data_list:
            st.dataframe(pd.DataFrame(fut_data_list), use_container_width=True)
        else:
            st.info("Brak danych Futures do wyświetlenia.")
    except Exception as scanner_err:
        st.error(f"Błąd ładowania danych skanera: {scanner_err}")
else:
    st.info("Skonfiguruj klucze API Futures, aby widzieć skaner.")

st.markdown("---")
st.subheader("📜 Dziennik Transakcji")
if st.session_state.trade_history:
    st.dataframe(pd.DataFrame(st.session_state.trade_history), use_container_width=True)
else:
    st.info("Brak transakcji w tej sesji.")

if st.session_state.scanner_active or st.session_state.trend_bot_fut_active:
    try:
        time.sleep(scan_interval)
    except Exception:
        pass

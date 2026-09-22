from datetime import datetime
import hashlib
import json
import logging
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
# FUNKCJE POMOCNICZE I ADMIN
# =====================================================================
ADMIN_EMAILS = ["marekjas57@wp.pl", "marekja57@wp.pl", "admin@bot-bitget.pl"]

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

# =====================================================================
# INICJALIZACJA STANÓW SESSION STATE
# =====================================================================
defaults = {
    "logged_in": False,
    "user_email": "",
    "is_admin": False,
    "user_id": None,
    "stripe_paid": False,
    "known_markets": set(),
    "last_fut_total": 0.0,
    "last_fut_free": 0.0,
    "session_start_balance": 0.0,
    "session_baseline_locked": False,
    "scanner_active": False,
    "trend_bot_fut_active": False,
    "session_start_time": datetime.now(),
    "trade_history": [],
    "signal_cooldown": {},
    "active_trades": {},
    "lang": "Polski",
    "api_key": "",
    "secret_key": "",
    "passphrase": ""
}

for key, val in defaults.items():
    if key not in st.session_state:
        st.session_state[key] = val

st.session_state.sidebar_auto_scan_cb = st.session_state.scanner_active
st.session_state.main_cb_trend_fut = st.session_state.trend_bot_fut_active

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
# STYLIZACJA WYGLĄDU (CSS)
# =====================================================================
st.markdown(
    """<style>
    @import url('https://fonts.googleapis.com/css2?family=Bungee+Inline&family=Cinzel:wght@700&display=swap');
    .stApp { background-color: #0d0b0a; }
    section[data-testid="stSidebar"] { background-color: #141110; border-right: 2px solid #3d2f1f; }
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
    div.stButton > button:hover { background: linear-gradient(135deg, #28663a 0%, #163d22 100%) !important; border-color: #ffe89d !important; color: #ffe89d !important; box-shadow: 0 0 20px rgba(243, 213, 122, 0.4) !important; transform: translateY(-2px); }
    </style>""",
    unsafe_allow_html=True,
)

# =====================================================================
# EKRAN LOGOWANIA / REJESTRACJI
# =====================================================================
if not st.session_state.logged_in:
    st.markdown(
        """<div class="hero-wrapper">
            <div class="retro-ornate-frame">
                <div class="retro-vintage-title">BITGET FUTURES</div>
                <div class="retro-subtitle">AUTONOMICZNY SYSTEM TRANSAKCYJNY</div>""",
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
st.session_state.lang = st.sidebar.selectbox("🌐 Język / Language", ["Polski", "English"], key="lang_selector")

if st.session_state.lang == "Polski":
    with st.sidebar.expander("📖 Instrukcja Obsługi i Regulamin"):
        st.sidebar.markdown("""
        1. Jak zacząć:
        * Wpisz klucze API Bitget w panelu.
        * Opłać subskrypcję Stripe.
        * Wybierz pary walut i strategię.
        * Włącz auto-skanowanie / handel.

        2. Regulamin:
        * Handel na giełdzie wiąże się z ryzykiem utraty kapitału.
        * Narzędzie służy do celów analitycznych i automatyzacji.
        """)
else:
    with st.sidebar.expander("📖 User Manual & Terms"):
        st.sidebar.markdown("""
        1. Getting Started:
        * Enter Bitget API keys.
        * Complete Stripe subscription.
        * Choose pairs and strategy.
        * Enable auto-scanning / trading.

        2. Terms of Service:
        * Crypto trading involves high risk.
        * Software is provided as an analytical tool.
        """)

def get_exchange():
    if not st.session_state.get("api_key"):
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
input_api = st.sidebar.text_input("Bitget API Key", value=st.session_state.get("api_key", ""), type="password")
input_secret = st.sidebar.text_input("Bitget Secret Key", value=st.session_state.get("secret_key", ""), type="password")
input_pass = st.sidebar.text_input("Bitget Passphrase", value=st.session_state.get("passphrase", ""), type="password")

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
def toggle_scanner_from_sidebar():
    st.session_state.scanner_active = st.session_state.sidebar_auto_scan_cb
    if st.session_state.scanner_active:
        st.session_state.session_baseline_locked = False

auto_scan_enabled = st.sidebar.checkbox("Włącz auto-skanowanie w tle", key="sidebar_auto_scan_cb", on_change=toggle_scanner_from_sidebar)
scan_interval = st.sidebar.slider("Interwał odświeżania (s)", 1, 300, 2)
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
    st.session_state.active_trades = {}
    st.session_state.signal_cooldown = {}
    st.session_state.session_start_balance = 0.0
    st.session_state.session_baseline_locked = False
    st.success("🛑 KILL SWITCH WYKONANY. Zamknięto wszystkie pozycje Futures.")
    time.sleep(2)
    st.rerun()

# ==========================================
# WYLICZENIE SALDA I METRYK FUTURES
# ==========================================
fut_free, fut_total = 0.0, 0.0
active_positions_count = 0
total_pnl = 0.0
total_unrealized_pnl = 0.0

if futures_ex:
    try:
        f_bal = futures_ex.fetch_balance({"type": "swap"})
        if "USDT" in f_bal:
            fut_free = float(f_bal["USDT"].get("free", 0.0))
            fut_total = float(f_bal["USDT"].get("total", 0.0))
            fut_used = float(f_bal["USDT"].get("used", 0.0))
            if fut_used > 0 and fut_free >= fut_total:
                fut_free = fut_total - fut_used
    except Exception:
        try:
            f_bal = futures_ex.fetch_balance()
            if "USDT" in f_bal:
                fut_free = float(f_bal["USDT"].get("free", 0.0))
                fut_total = float(f_bal["USDT"].get("total", 0.0))
        except Exception:
            pass

    try:
        positions = futures_ex.fetch_positions()
        active_pos = [p for p in positions if float(p.get("contracts", 0)) > 0]
        active_positions_count = len(active_pos)
        total_pnl = sum(float(p.get("unrealizedPnl", 0)) for p in active_pos)
        total_unrealized_pnl = total_pnl
        total_margin_used = sum(float(p.get("initialMargin") or p.get("margin", 0) or p.get("info", {}).get("margin", 0)) for p in active_pos)
        if total_margin_used > 0 and (fut_total - fut_free) < 1:
            fut_free = max(0.0, fut_total - total_margin_used)
    except Exception:
        active_positions_count = len(st.session_state.get('active_trades', {}))

if (not st.session_state.session_baseline_locked or st.session_state.session_start_balance == 0.0) and fut_total > 0:
    st.session_state.session_start_balance = fut_total
    st.session_state.session_baseline_locked = True

start_val = st.session_state.get('session_start_time', datetime.now())
try:
    if hasattr(start_val, 'timestamp'):
        session_elapsed = int(time.time() - start_val.timestamp())
    else:
        session_elapsed = int(time.time() - float(start_val))
except Exception:
    session_elapsed = 0

hours, rem = divmod(session_elapsed, 3600)
minutes, seconds = divmod(rem, 60)

session_pnl_pct_display = 0.0
if 'session_start_balance' in st.session_state and st.session_state.session_start_balance > 0 and fut_total > 0:
    session_pnl_pct_display = ((fut_total - st.session_state.session_start_balance) / st.session_state.session_start_balance) * 100
elif fut_total > 0:
    session_pnl_pct_display = (total_pnl / fut_total) * 100

# =====================================================================
# GŁÓWNE KAFELKI METRYK
# =====================================================================
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
        <div class="metric-delta">PnL USDT: {total_unrealized_pnl:+.2f} USDT</div>
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
    def toggle_main_trend_fut():
        st.session_state.trend_bot_fut_active = st.session_state.main_cb_trend_fut
        if st.session_state.trend_bot_fut_active and fut_total > 0:
            st.session_state.session_baseline_locked = False

    st.checkbox("🔵 Uruchom Bota Futures", key="main_cb_trend_fut", on_change=toggle_main_trend_fut)
    if st.session_state.trend_bot_fut_active:
        st.success("🟢 Bot Futures Aktywny (Z filtrem trendu EMA 50 + MACD)")
    else:
        st.info("🔴 Bot Futures Zatrzymany")

    st.markdown("---")
    col_btn, col_status = st.columns([2, 1])
    with col_btn:
        if not st.session_state.scanner_active:
            if st.button("🚀 Uruchom Skaner Non-Stop", type="primary", use_container_width=True):
                st.session_state.scanner_active = True
                st.session_state.session_baseline_locked = False
                st.rerun()
        else:
            if st.button("⏹️ Zatrzymaj Skaner", type="secondary", use_container_width=True):
                st.session_state.scanner_active = False
                st.session_state.trend_bot_fut_active = False
                st.session_state.session_start_balance = 0.0
                st.session_state.session_baseline_locked = False
                st.rerun()
    with col_status:
        if st.session_state.scanner_active:
            st.success("STATUS: AKTYWNY")
        else:
            st.error("STATUS: ZATRZYMANY")

MIN_FUT_TRADE = 5.0

# =====================================
# LOGIKA BOTA I ZARZĄDZANIE POZYCJAMI
# =====================================
def check_fast_strategy_signals(df):
  """Oblicza szybkie wskaźniki (EMA 9 i 21) oraz generuje sygnały wejścia/wyjścia.

  Eliminuje czekanie na makro-trendy i natychmiast tnie straty.
  """
  df['ema9'] = df['close'].ewm(span=9, adjust=False).mean()
  df['ema21'] = df['close'].ewm(span=21, adjust=False).mean()

  curr_ema9 = df['ema9'].iloc[-1]
  curr_ema21 = df['ema21'].iloc[-1]
  prev_ema9 = df['ema9'].iloc[-2]
  prev_ema21 = df['ema21'].iloc[-2]

  current_close = df['close'].iloc[-1]

  # 1. SYGNAŁ WEJŚCIA: Szybkie przecięcie w górę (EMA 9 przecina EMA 21)
  enter_long = (prev_ema9 <= prev_ema21) and (curr_ema9 > curr_ema21)

  # 2. SYGNAŁ WYJŚCIA (NATYCHMIASTOWY): Przecięcie w dół LUB spadek ze szczytu
  recent_peak = df['high'].iloc[-10:].max()
  drop_from_peak = ((recent_peak - current_close) / recent_peak) * 100

  exit_long = ((prev_ema9 >= prev_ema21) and (curr_ema9 < curr_ema21)) or (
      drop_from_peak >= 1.5
  )

  return {
      'enter_long': enter_long,
      'exit_long': exit_long,
      'drop_from_peak': drop_from_peak,
      'current_ema9': curr_ema9,
      'current_ema21': curr_ema21,
  }


# Główna pętla zarządzania pozycjami w Twoim skanerze/bocie:
try:
  if futures_ex:
    current_positions = futures_ex.fetch_positions()
except Exception as e:
  st.toast(f'Błąd pobierania pozycji: {e}', icon='⚠')
  current_positions = []

# 1. ZARZĄDZANIE AKTYWNYMI POZYCJAMI (Zamykanie przy załamaniu / spadku ze szczytu)
try:
  for pos in current_positions:
    contracts_amt = float(pos.get('contracts', 0))
    if contracts_amt > 0:
      sym = pos.get('symbol')
      if sym:
        # Pobieramy świece dla danej aktywnej pary
        ohlcv = futures_ex.fetch_ohlcv(sym, timeframe='1h', limit=50)
        df_pos = pd.DataFrame(
            ohlcv,
            columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'],
        )
        signals = check_fast_strategy_signals(df_pos)

        if signals['exit_long']:
          print(
              f'[{sym}] Wykryto załamanie trendu / spadek ze szczytu'
              f' ({signals["drop_from_peak"]:.2f}%). Zamykam pozycję!'
          )
          futures_ex.create_market_order(
              sym, 'sell', contracts_amt, params={'reduceOnly': True}
          )
          st.session_state.trade_history.append({
              'time': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
              'symbol': sym,
              'action': 'ZAMKNIĘCIE (Szybki Exit / Szczyt)',
              'pnl': pos.get('unrealizedPnl', 0),
          })
except Exception as e:
  print(f'Błąd w zarządzaniu pozycjami: {e}')
                        
# =====================================================================
# WIDOK NA ŻYWO: TABELE AKTUALNYCH POZYCJI I HISTORIA
# =====================================================================
st.markdown("---")
st.subheader("📊 Aktywne Pozycje Futures na Żywo")

if futures_ex:
    try:
        if hasattr(futures_ex, 'timeout'):
            futures_ex.timeout = 8000

        positions = futures_ex.fetch_positions()
        active_pos = [p for p in positions if float(p.get("contracts", 0)) > 0]
        if active_pos:
            pos_data = []
            for p in active_pos:
                sym = p.get("symbol")
                clean_sym = sym.split(':')[0] if ':' in sym else sym
                base_coin = clean_sym.split('/')[0] if '/' in clean_sym else clean_sym
                side = p.get("side")
                contracts = p.get("contracts")
                entry_price = float(p.get("entryPrice") or p.get("info", {}).get("entryPrice", 0))
                mark_price = float(p.get("markPrice") or p.get("info", {}).get("markPrice", 0))
                leverage = float(p.get("leverage") or p.get("info", {}).get("leverage", 1))
                unrealized_pnl = float(p.get("unrealizedPnl", 0))

                active_trades_dict = st.session_state.get('active_trades', {})
                trade_info = active_trades_dict.get(sym, {}) \
                        or active_trades_dict.get(clean_sym, {}) \
                        or active_trades_dict.get(base_coin, {})

                budget_val = trade_info.get("budget") or trade_info.get("amount") or trade_info.get("allocated")
                lev_num = leverage if leverage > 0 else 1.0
                if not budget_val and contracts and entry_price:
                    budget_val = (float(contracts) * entry_price) / lev_num

                allocation_str = f"{float(budget_val):.2f} USDT" if budget_val else f"{(float(contracts or 0) * entry_price / lev_num):.2f} USDT"
                signal_desc = trade_info.get("signal_name") or trade_info.get("Typ") or "EMA + MACD (Potwierdzony)"

                pos_data.append({
                    "Para": clean_sym,
                    "Strona": str(side).upper(),
                    "Sygnał": "TAK (Potwierdzony)",
                    "Typ Sygnału": signal_desc,
                    "Alokacja": allocation_str,
                    "Kontrakty": contracts,
                    "Cena Wejścia": f"{entry_price:.4f}",
                    "Cena Mark": f"{mark_price:.4f}",
                    "Dźwignia": f"{int(leverage)}x",
                    "PnL (USDT)": f"{unrealized_pnl:+.2f}"
                })
            st.dataframe(pd.DataFrame(pos_data), use_container_width=True)
        else:
            st.info("🟢 Skaner aktywny: Brak otwartych pozycji, monitorowanie rynku w toku...")
    except Exception as e:
        st.error(f"Błąd pobierania pozycji: {e}")
else:
    st.warning("Skonfiguruj i zapisz klucze API Bitget w panelu bocznym, aby podglądać pozycje na żywo.")

# ==========================================
# PANEL DIAGNOSTYCZNY SKANERA NA ŻYWO
# ==========================================
st.subheader("🟢 Stan Skanera Rynku na Żywo (Analiza Wskaźników)")
if st.session_state.get("scanner_active", False) and futures_ex:
  with st.spinner("Analizowanie par rynkowych..."):
    try:
      f_tickers = futures_ex.fetch_tickers()
      min_required_volume = 50000000.0 # Twój próg minimalnego wolumenu

      # Pobieramy wszystkie pary o największym wolumenie spełniające kryteria
      top_volume_symbols = sorted(
          [
              sym
              for sym, data in f_tickers.items()
              if (sym.endswith("USDT") or "/USDT:USDT" in sym)
              and "BULL" not in sym
              and "BEAR" not in sym
              and float(data.get("quoteVolume") or 0) >= min_required_volume
          ],
          key=lambda x: float(f_tickers[x].get("quoteVolume") or 0),
          reverse=True,
      )

      scanner_results = []
      for sym in top_volume_symbols:
        try:
          # Pobieramy świece do oceny sygnału
          ohlcv = futures_ex.fetch_ohlcv(sym, timeframe="1h", limit=50)
          df_scan = pd.DataFrame(
              ohlcv,
              columns=["timestamp", "open", "high", "low", "close", "volume"],
          )

          # Sprawdzamy sygnały strategii EMA 9/21 i spadku ze szczytu
          signals = check_fast_strategy_signals(df_scan)

          # ==========================================
          # AUTOMATYCZNY HANDEL FUTURES (Wejście i Wyjście EMA)
          # ==========================================
          if st.session_state.get("trend_bot_fut_active", False):
            pos_check = futures_ex.fetch_positions([sym])
            has_open_pos = any(
                float(p.get("contracts", 0)) > 0 for p in pos_check
            )

            # 1. OTWIERANIE POZYCJI LONG
            if not has_open_pos and signals["enter_long"]:
              target_lev = 10
              cap_per_trade = 30.0

              try:
                futures_ex.set_leverage(target_lev, sym)
              except Exception:
                pass

              notional = cap_per_trade * target_lev
              contracts_amt = notional / df_scan["close"].iloc[-1]

              print(
                  f"[{sym}] 🚀 Szybki sygnał EMA! Otwieram pozycję za"
                  f" {cap_per_trade} USDT (Dźwignia {target_lev}x)"
              )
              futures_ex.create_market_order(sym, "buy", contracts_amt)

              st.session_state.trade_history.append({
                  "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                  "symbol": sym,
                  "action": f"OTWARCIE LONG (Kapitał: {cap_per_trade} USDT)",
                  "pnl": "0.00",
              })

            # 2. ZAMYKANIE POZYCJI LONG (Sygnał wyjścia)
            open_longs = [
                p for p in pos_check if float(p.get("contracts", 0)) > 0
            ]
            if open_longs and signals["exit_long"]:
              for p in open_longs:
                contracts_to_close = float(p.get("contracts", 0))
                print(
                    f"[{sym}] 🔴 Sygnał wyjścia EMA! Zamykam pozycję LONG"
                    f" ({contracts_to_close} kontraktów)"
                )
                futures_ex.create_market_order(sym, "sell", contracts_to_close)

                st.session_state.trade_history.append({
                    "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    "symbol": sym,
                    "action": "ZAMKNIĘCIE LONG (Sygnał wyjścia EMA)",
                    "pnl": "0.00",
                })

          # Status do tabeli na żywo
          if signals["enter_long"]:
            status_text = "🟢 Szybki sygnał wejścia (EMA 9/21)"
          elif signals["exit_long"]:
            status_text = (
                f"🔴 Zagrożenie / Spadek ({signals['drop_from_peak']:.2f}%)"
            )
          else:
            if signals["current_ema9"] > signals["current_ema21"]:
              status_text = "📈 Trend wzrostowy (Szukam korekty)"
            else:
              status_text = "📉 Trend spadkowy (Czekam na zwrot)"

          vol_24h = float(f_tickers[sym].get("quoteVolume") or 0)
          e9 = signals.get("current_ema9", 0.0)
          e21 = signals.get("current_ema21", 0.0)

          scanner_results.append({
              "Symbol": sym,
              "Wolumen 24h": f"{vol_24h:,.0f} USDT",
              "EMA 9 / 21": f"{e9:.4f} / {e21:.4f}",
              "Status Skanera": status_text,
          })
        except Exception as e:
          continue

      if scanner_results:
        st.dataframe(pd.DataFrame(scanner_results), use_container_width=True)
      else:
        st.info("Brak par spełniających kryteria wolumenu.")

    except Exception as e:
      st.error(f"Błąd pobierania danych skanera: {e}")
else:
  st.warning(
      "Skonfiguruj i zapisz klucze API Bitget w panelu bocznym, aby podglądać"
      " rynek."
  )

# ==========================================
# HISTORIA TRANSAKCJI SESJI
# ==========================================
st.markdown("---")
st.subheader("📜 Historia Transakcji Sesji")
trade_history = st.session_state.get('trade_history', [])
if trade_history:
    df_history = pd.DataFrame(trade_history)
    st.dataframe(df_history, use_container_width=True)
else:
    st.info("Brak zarejestrowanych transakcji w bieżącej sesji.")

# =====================================================================
# PĘTLA AUTOMATYCZNEGO ODŚWIEŻANIA (AUTO-REFRESH LOOP)
# =====================================================================
if st.session_state.scanner_active:
    time.sleep(scan_interval)
    st.rerun()

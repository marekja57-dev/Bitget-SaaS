from datetime import datetime
import json
import os
import sqlite3
import time
import ccxt
import pandas as pd
import streamlit as st
import stripe

st.set_page_config(
    page_title="Bitget SAS - System Futures SaaS",
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
# INICJALIZACJA BAZY DANYCH SQLITE (PEŁNA PERSYSTENCJA)
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
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS trade_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            time TEXT,
            type TEXT,
            pair TEXT,
            budget TEXT,
            leverage TEXT,
            price TEXT
        )
    ''')
    
    for col, col_type in [("api_key", "TEXT"), ("secret_key", "TEXT"), ("passphrase", "TEXT"), ("stripe_paid", "INTEGER DEFAULT 0"), ("is_admin", "INTEGER DEFAULT 0")]:
        try:
            cursor.execute(f"ALTER TABLE users ADD COLUMN {col} {col_type}")
        except sqlite3.OperationalError:
            pass

    for adm_email in ADMIN_EMAILS:
        cursor.execute("UPDATE users SET is_admin = 1, stripe_paid = 1 WHERE LOWER(TRIM(email)) = ?", (adm_email,))
    
    conn.commit()
    conn.close()

init_db()

def load_trade_history_from_db(user_id):
    if not user_id:
        return []
    try:
        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()
        cursor.execute("SELECT time, type, pair, budget, leverage, price FROM trade_history WHERE user_id = ? ORDER BY id DESC", (user_id,))
        rows = cursor.fetchall()
        conn.close()
        history = []
        for r in rows:
            history.append({
                "Czas": r[0],
                "Typ": r[1],
                "Para": r[2],
                "Budżet": r[3],
                "Dźwignia": r[4],
                "Cena": r[5]
            })
        return history
    except Exception:
        return []

def save_trade_to_db(user_id, t_item):
    if not user_id:
        return
    try:
        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO trade_history (user_id, time, type, pair, budget, leverage, price) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (user_id, t_item.get("Czas"), t_item.get("Typ"), t_item.get("Para"), t_item.get("Budżet", "-"), t_item.get("Dźwignia", "-"), t_item.get("Cena", "-"))
        )
        conn.commit()
        conn.close()
    except Exception:
        pass

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
try:
    stripe_pk_val = saved_stripe_pk or st.secrets.get("STRIPE_PK", "")
    stripe_sk_val = saved_stripe_sk or st.secrets.get("STRIPE_SK", "")
    stripe_price_id_val = saved_stripe_price_id or st.secrets.get("STRIPE_PRICE_ID", "")
except Exception:
    stripe_pk_val = saved_stripe_pk or ""
    stripe_sk_val = saved_stripe_sk or ""
    stripe_price_id_val = saved_stripe_price_id or ""

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

if "last_fut_total" not in st.session_state:
    st.session_state.last_fut_total = 0.0
if "last_fut_free" not in st.session_state:
    st.session_state.last_fut_free = 0.0

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
    """ <style>
    @import url('https://fonts.googleapis.com/css2?family=Bungee+Inline&family=Cinzel:wght@700&display=swap');
    .stApp { background-color: #0d0b0a; }
    section[data-testid="stSidebar"] { background-color: #141110; border-right: 2px solid #3d2f1f; }
    .hero-wrapper { display: flex; align-items: center; justify-content: center; width: 100%; padding-top: 50px; padding-bottom: 20px; }
    .retro-ornate-frame { position: relative; background: radial-gradient(circle, #221a14 0%, #110d0a 100%); border: 6px double #f3d57a; padding: 40px 30px; border-radius: 16px; box-shadow: 0 0 50px rgba(243, 213, 122, 0.4), inset 0 0 35px rgba(0, 0, 0, 0.9); width: 100%; max-width: 600px; text-align: center; }
    .retro-vintage-title { font-family: 'Bungee Inline', cursive, sans-serif; font-size: 3rem; color: #f3d57a; letter-spacing: 4px; text-shadow: 4px 4px 0px #8b0000, 8px 8px 0px rgba(0,0,0,0.95); margin-bottom: 10px; }
    .retro-subtitle { font-family: 'Cinzel', serif; color: #e6c687; font-size: 1.1rem; letter-spacing: 2px; margin-bottom: 25px; }
    div.stButton > button { background: linear-gradient(135deg, #1e4d2b 0%, #0f2b17 100%) !important; color: #f3d57a !important; border: 2px solid #f3d57a !important; font-family: 'Cinzel', serif !important; font-weight: 700 !important; font-size: 1rem !important; padding: 10px 24px !important; border-radius: 8px !important; box-shadow: 0 4px 15px rgba(0, 0, 0, 0.6) !important; transition: all 0.3s ease !important; }
    div.stButton > button:hover { background: linear-gradient(135deg, #28663a 0%, #163d22 100%) !important; border-color: #ffe89d !important; color: #ffe89d !important; box-shadow: 0 0 20px rgba(243, 213, 122, 0.4) !important; transform: translateY(-2px); }
    div[data-testid="stMetric"] { border: 2px solid #f3d57a; border-radius: 10px; padding: 12px 16px; background-color: rgba(243, 213, 122, 0.03); box-shadow: 0 4px 12px rgba(0, 0, 0, 0.2); height: 105px; display: flex; flex-direction: column; justify-content: center; }
    div[data-testid="stMetric"] label { color: #f3d57a !important; font-size: 0.95rem !important; }
    </style> """,
    unsafe_allow_html=True,
)

# =====================================================================
# EKRAN LOGOWANIA / REJESTRACJI
# =====================================================================
if not st.session_state.logged_in:
    st.markdown(
        """ <div class="hero-wrapper"> <div class="retro-ornate-frame"> <div class="retro-vintage-title">BITGET SAS</div> <div class="retro-subtitle">AUTONOMICZNY SYSTEM FUTURES</div> """,
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
    st.session_state.trade_history = load_trade_history_from_db(st.session_state.user_id)

if "signal_cooldown" not in st.session_state:
    st.session_state.signal_cooldown = {}
if "scanner_active" not in st.session_state:
    st.session_state.scanner_active = False
if "active_trades" not in st.session_state:
    st.session_state.active_trades = {}
if "trend_bot_fut_active" not in st.session_state:
    st.session_state.trend_bot_fut_active = False
if "listing_sniper_active" not in st.session_state:
    st.session_state.listing_sniper_active = False
if "known_markets" not in st.session_state:
    st.session_state.known_markets = set()

def get_futures_exchange():
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
    st.sidebar.markdown("🔴 Rola: Administrator")
else:
    st.sidebar.markdown("🟢 Rola: Klient SaaS")

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

if is_user_admin():
    with st.sidebar.expander("🛠️ Konfiguracja Stripe (Admin)"):
        input_s_pk = st.text_input("Stripe Publishable Key", value=stripe_pk_val, type="password")
        input_s_sk = st.text_input("Stripe Secret Key", value=stripe_sk_val, type="password")
        input_s_price = st.text_input("Stripe Price ID", value=stripe_price_id_val)
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

futures_ex = get_futures_exchange()

# =====================================================================
# USTAWIENIA
# =====================================================================
st.sidebar.markdown("---")
st.sidebar.markdown("### ⚙️ Ustawienia Futures")
max_active_futures_positions = st.sidebar.slider("📈 Maksymalna liczba aktywnych pozycji", 1, 20, 5)

st.sidebar.markdown("---")
st.sidebar.markdown("### 💰 Alokacja Kapitału (Limit Kwotowy)")
position_fixed_budget = st.sidebar.number_input("Maksymalny budżet na 1 pozycję (USDT)", min_value=5.0, max_value=1000.0, value=20.0, step=5.0)
risk_reduction_enabled = st.sidebar.checkbox("🧠 Inteligentna redukcja kapitału przy wysokim ryzyku (zmienności)", value=True)

st.sidebar.markdown("---")
st.sidebar.markdown("### 🛑 Zarządzanie Ryzykiem (SL / TP)")
use_sltp = st.sidebar.checkbox("Włącz ochronę SL / TP", value=True)
stop_loss_pct = st.sidebar.slider("Stop Loss (%)", 0.5, 10.0, 2.0, 0.5)
take_profit_pct = st.sidebar.slider("Take Profit (%)", 1.0, 50.0, 5.0, 0.5)

st.sidebar.markdown("---")
st.sidebar.markdown("### ⚡ Zarządzanie Dźwignią")
leverage_mode = st.sidebar.radio("Tryb Dźwigni", ["🤖 Autonomiczny (max 10x)", "🎛️ Ręczny"])
manual_leverage = st.sidebar.slider("Stała dźwignia Futures", 1, 10, 3)

# =====================================================================
# SNAJPER NOWYCH LISTINGÓW
# =====================================================================
st.sidebar.markdown("---")
st.sidebar.markdown("### 🎯 Snajper Nowych Listingów")
listing_sniper_budget = st.sidebar.number_input("Kapitał na nowy listing (USDT)", min_value=5.0, value=25.0, step=5.0)
listing_sniper_lev = st.sidebar.slider("Dźwignia Snajpera Listingowego", 1, 20, 5)

if "listing_cb" not in st.session_state:
    st.session_state.listing_cb = st.session_state.listing_sniper_active

def toggle_listing_sniper():
    st.session_state.listing_sniper_active = st.session_state.listing_cb
    if st.session_state.listing_sniper_active and futures_ex:
        try:
            mks = futures_ex.fetch_markets()
            st.session_state.known_markets = {m["symbol"] for m in mks}
        except Exception:
            pass

st.sidebar.checkbox("🟢 Aktywuj Auto-Snajper Listingowy", key="listing_cb", on_change=toggle_listing_sniper)

st.sidebar.markdown("---")
st.sidebar.markdown("### 🧠 Interwał Analizy")
spot_tf = st.sidebar.selectbox("Interwał", ["1m", "5m", "15m", "30m", "1h", "4h", "1d"], index=4)

st.sidebar.markdown("---")
st.sidebar.markdown("### 🔄 Pętla Skanera")
if "sidebar_auto_scan_cb" not in st.session_state:
    st.session_state.sidebar_auto_scan_cb = st.session_state.scanner_active

def toggle_scanner_from_sidebar():
    st.session_state.scanner_active = st.session_state.sidebar_auto_scan_cb

auto_scan_enabled = st.sidebar.checkbox("Włącz auto-skanowanie w tle", key="sidebar_auto_scan_cb", on_change=toggle_scanner_from_sidebar)
scan_interval = st.sidebar.slider("Interwał odświeżania (s)", 1, 300, 3)
max_fut_scan_pairs = st.sidebar.slider("📈 Liczba skanowanych par Futures", 5, 50, 15, 5)

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
    st.session_state.trend_bot_fut_active = False
    st.session_state.listing_sniper_active = False
    st.session_state.active_trades = {}
    st.session_state.signal_cooldown = {}
    st.success("🚨 KILL SWITCH WYKONANY. Zamknięto pozycje i wyłączono bota/snajpera.")
    time.sleep(2)
    st.rerun()

# =====================================================================
# POBIERANIE SALDA FUTURES Z PAMIĘCIĄ PODRĘCZNĄ (ANTY-ZEROWANIE)
# =====================================================================
if futures_ex:
    try:
        f_bal = {}
        try:
            f_bal = futures_ex.fetch_balance({"accountType": "usdt-futures"})
        except Exception:
            try:
                f_bal = futures_ex.fetch_balance({"type": "swap"})
            except Exception:
                f_bal = futures_ex.fetch_balance()

        def extract_bal(bal_data):
            t, f = 0.0, 0.0
            if not isinstance(bal_data, dict):
                return 0.0, 0.0
            usdt_entry = bal_data.get("USDT")
            if isinstance(usdt_entry, dict):
                t = float(usdt_entry.get("total", 0.0) or 0.0)
                f = float(usdt_entry.get("free", 0.0) or 0.0)
            if t == 0.0 and isinstance(bal_data.get("total"), dict):
                t = float(bal_data.get("total", {}).get("USDT", 0.0) or 0.0)
            if f == 0.0 and isinstance(bal_data.get("free"), dict):
                f = float(bal_data.get("free", {}).get("USDT", 0.0) or 0.0)
            if t == 0.0 and "info" in bal_data:
                try:
                    info_data = bal_data["info"]
                    if isinstance(info_data, list) and len(info_data) > 0:
                        for row in info_data:
                            if row.get("marginCoin") == "USDT" or row.get("coin") == "USDT":
                                t = float(row.get("equity", row.get("total", row.get("available", 0.0))) or 0.0)
                                f = float(row.get("available", row.get("free", 0.0)) or 0.0)
                    elif isinstance(info_data, dict):
                        data_list = info_data.get("data", info_data.get("list", []))
                        if isinstance(data_list, list):
                            for row in data_list:
                                if isinstance(row, dict) and (row.get("marginCoin") == "USDT" or row.get("coin") == "USDT"):
                                    t = float(row.get("equity", row.get("total", row.get("available", 0.0))) or 0.0)
                                    f = float(row.get("available", row.get("free", 0.0)) or 0.0)
                except Exception:
                    pass
            return f, t

        f_free_fetched, f_total_fetched = extract_bal(f_bal)
        
        if f_total_fetched > 0.0 or f_free_fetched > 0.0:
            st.session_state.last_fut_total = f_total_fetched
            st.session_state.last_fut_free = f_free_fetched
    except Exception:
        pass

fut_total = st.session_state.last_fut_total
fut_free = st.session_state.last_fut_free

total_unrealized_pnl = 0.0
active_positions_count = 0
exchange_positions = {}
if futures_ex:
    try:
        positions = futures_ex.fetch_positions()
        for p in positions:
            if float(p.get("contracts", 0)) > 0:
                active_positions_count += 1
                total_unrealized_pnl += float(p.get("unrealizedPnl", 0.0))
                exchange_positions[p["symbol"]] = p
    except Exception:
        pass

# =====================================================================
# GŁÓWNE KAFELKI
# =====================================================================
col1, col2, col3, col4 = st.columns([1, 1, 1, 1])
with col1:
    st.metric(
        label="🔵 Portfel Futures",
        value=f"{fut_total:.2f} USDT",
        delta=f"Wolne: {fut_free:.2f} USDT"
    )
with col2:
    st.metric(
        label="📊 Aktywne Pozycje",
        value=f"{active_positions_count} / {max_active_futures_positions}",
        delta=f"Wolne sloty: {max(0, max_active_futures_positions - active_positions_count)}"
    )
with col3:
    st.metric(
        label="📈 Wynik Niezrealizowany",
        value=f"{total_unrealized_pnl:+.2f} USDT"
    )
with col4:
    elapsed = datetime.now() - st.session_state.session_start_time
    total_seconds = int(elapsed.total_seconds())
    hours, remainder = divmod(total_seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    st.metric(label="⏰ Czas Sesji", value=f"{hours:02d}:{minutes:02d}:{seconds:02d}", delta=f"Interwał: {scan_interval}s")

st.markdown("---")

# =====================================================================
# PANEL STEROWANIA BOTEM FUTURES
# =====================================================================
st.subheader("🥾 Panel Sterowania Botem Futures i Snajperem")
with st.container(border=True):
    col_b1, col_b2 = st.columns(2)
    with col_b1:
        if "main_cb_trend_fut" not in st.session_state:
            st.session_state.main_cb_trend_fut = st.session_state.trend_bot_fut_active

        def toggle_main_trend_fut():
            st.session_state.trend_bot_fut_active = st.session_state.main_cb_trend_fut

        st.checkbox("🔵 Automatyczny Bot Futures (Ciągły Handlowiec)", key="main_cb_trend_fut", on_change=toggle_main_trend_fut)
    with col_b2:
        if "main_cb_listing" not in st.session_state:
            st.session_state.main_cb_listing = st.session_state.listing_sniper_active

        def toggle_main_listing():
            st.session_state.listing_sniper_active = st.session_state.main_cb_listing

        st.checkbox("🎯 Snajper Nowych Listingów w Tle", key="main_cb_listing", on_change=toggle_main_listing)

st.markdown("---")
col_btn, col_status = st.columns([2, 1])
with col_btn:
    if not st.session_state.scanner_active:
        if st.button("🚀 Uruchom Skaner i Snajpera w Pętli", type="primary", use_container_width=True):
            st.session_state.scanner_active = True
            st.rerun()
    else:
        if st.button("⏹️ Zatrzymaj Skaner i Snajpera", type="secondary", use_container_width=True):
            st.session_state.scanner_active = False
            st.rerun()
with col_status:
    if st.session_state.scanner_active:
        st.success("STATUS: AKTYWNY")
    else:
        st.error("STATUS: ZATRZYMANY")

MIN_FUT_TRADE = 5.0

# =====================================================================
# LOGIKA SNAJPERA NOWYCH LISTINGÓW
# =====================================================================
if futures_ex and st.session_state.listing_sniper_active:
    try:
        current_markets_data = futures_ex.fetch_markets()
        current_market_symbols = {m["symbol"] for m in current_markets_data if ":USDT" in m["symbol"] or "/USDT" in m["symbol"]}
       
        if not st.session_state.known_markets:
            st.session_state.known_markets = current_market_symbols
        else:
            newly_listed = current_market_symbols - st.session_state.known_markets
            if newly_listed:
                for new_sym in newly_listed:
                    if "BULL" in new_sym or "BEAR" in new_sym or new_sym in st.session_state.active_trades:
                        continue
                    try:
                        tickers_chk = futures_ex.fetch_tickers()
                        t_info = tickers_chk.get(new_sym, {})
                        launch_price = float(t_info.get("last", 0))
                       
                        if launch_price > 0 and fut_free >= MIN_FUT_TRADE:
                            actual_budget = min(listing_sniper_budget, fut_free)
                            try:
                                futures_ex.set_leverage(listing_sniper_lev, new_sym)
                            except Exception:
                                pass
                           
                            contracts = (actual_budget * listing_sniper_lev) / launch_price
                            try:
                                contracts_prec = float(futures_ex.amount_to_precision(new_sym, contracts))
                                futures_ex.create_order(new_sym, 'market', 'buy', contracts_prec)
                            except Exception:
                                futures_ex.create_order(new_sym, 'market', 'buy', float(contracts))
                           
                            st.session_state.active_trades[new_sym] = True
                            t_item = {
                                "Czas": time.strftime("%Y-%m-%d %H:%M:%S"),
                                "Typ": "🎯 LISTING SNIPER LONG",
                                "Para": new_sym,
                                "Budżet": f"{actual_budget:.2f} USDT",
                                "Dźwignia": f"{listing_sniper_lev}x",
                                "Cena": f"{launch_price:.4f}",
                            }
                            st.session_state.trade_history.insert(0, t_item)
                            save_trade_to_db(st.session_state.user_id, t_item)
                    except Exception:
                        pass
            st.session_state.known_markets = current_market_symbols
    except Exception:
        pass

# =====================================================================
# CIĄGŁA LOGIKA TRENDU: ZAMYKANIE PRZY ZMIANIE TRENDU + OTWIERANIE W SLOCIE
# =====================================================================
if futures_ex:
    try:
        current_positions = futures_ex.fetch_positions()
        for pos in current_positions:
            contracts = float(pos.get("contracts", 0))
            sym = pos["symbol"]
            if contracts > 0:
                # Upewniamy się, że para jest w aktywnych transakcjach
                st.session_state.active_trades[sym] = True
                side = pos.get("side", "")
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

                    if use_sltp:
                        if pnl_pct <= -stop_loss_pct:
                            should_close_fut = True
                            close_reason_fut = f"STOP LOSS HIT ({pnl_pct:+.2f}%)"
                        elif pnl_pct >= take_profit_pct:
                            should_close_fut = True
                            close_reason_fut = f"TAKE PROFIT HIT ({pnl_pct:+.2f}%)"

                    if not should_close_fut:
                        if side == "long" and f_macd < f_sig:
                            should_close_fut = True
                            close_reason_fut = f"TREND REVERSAL EXIT LONG ({pnl_pct:+.2f}%)"
                        elif side == "short" and f_macd > f_sig:
                            should_close_fut = True
                            close_reason_fut = f"TREND REVERSAL EXIT SHORT ({pnl_pct:+.2f}%)"

                    if should_close_fut:
                        close_side = "sell" if side == "long" else "buy"
                        futures_ex.create_market_order(sym, close_side, contracts, params={"reduceOnly": True})
                        st.session_state.active_trades.pop(sym, None)
                        
                        t_item = {
                            "Czas": time.strftime("%Y-%m-%d %H:%M:%S"),
                            "Typ": close_reason_fut,
                            "Para": sym,
                            "Budżet": "-",
                            "Dźwignia": f"{leverage}x",
                            "Cena": f"{mark_price:.4f}",
                        }
                        st.session_state.trade_history.insert(0, t_item)
                        save_trade_to_db(st.session_state.user_id, t_item)
                except Exception:
                    pass
            else:
                # Jeśli pozycja wynosi 0 kontraktów na giełdzie, usuwamy z lokalnych aktywnych
                st.session_state.active_trades.pop(sym, None)
    except Exception:
        pass

    if st.session_state.trend_bot_fut_active:
        try:
            real_positions = futures_ex.fetch_positions()
            active_symbols = [p["symbol"] for p in real_positions if float(p.get("contracts", 0)) > 0]
            # Synchronizacja lokalnych aktywnych trade'ów z giełdą
            for sym in list(st.session_state.active_trades.keys()):
                if sym not in active_symbols:
                    st.session_state.active_trades.pop(sym, None)
        except Exception:
            active_symbols = []

        current_active_count = len(active_symbols)
        if current_active_count < max_active_futures_positions and fut_free >= MIN_FUT_TRADE:
            slots_available = max_active_futures_positions - current_active_count

            try:
                f_tickers = futures_ex.fetch_tickers()
                best_fut_candidates = sorted(
                    [sym for sym, data in f_tickers.items() if (sym.endswith(":USDT") or "/USDT:USDT" in sym) and "BULL" not in sym and "BEAR" not in sym and sym not in active_symbols and sym not in st.session_state.active_trades],
                    key=lambda x: f_tickers[x].get("quoteVolume", 0), reverse=True
                )[:max_fut_scan_pairs]

                evaluated_pairs = []
                for sym in best_fut_candidates:
                    try:
                        f_ohlcv = futures_ex.fetch_ohlcv(sym, timeframe=spot_tf, limit=50)
                        time.sleep(0.01)
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

                top_signal_pairs = sorted(evaluated_pairs, key=lambda x: x["strength"], reverse=True)[:slots_available]

                for item in top_signal_pairs:
                    sym = item["symbol"]
                    if sym in active_symbols or sym in st.session_state.active_trades:
                        continue

                    f_price = item["price"]
                    side = item["side"]
                    f_vol = item["volatility"]
                    label = "LONG" if side == "buy" else "SHORT"
                   
                    bot_leverage = calculate_dynamic_leverage(sym, f_vol, leverage_mode, manual_leverage)
                    tf_key = f"trend_bot_fut_{sym}"
                   
                    if time.time() - st.session_state.signal_cooldown.get(tf_key, 0) > 120:
                        max_allowed_budget = position_fixed_budget
                       
                        if risk_reduction_enabled:
                            risk_multiplier = max(0.3, min(1.0, 2.0 / f_vol)) if f_vol > 0 else 1.0
                            allocated_budget = max_allowed_budget * risk_multiplier
                        else:
                            allocated_budget = max_allowed_budget

                        budget = max(MIN_FUT_TRADE, allocated_budget)
                        if budget > fut_free:
                            budget = fut_free

                        if budget >= MIN_FUT_TRADE:
                            # Natychmiastowe oznaczenie w pamięci, aby pętla w tej samej sekundzie tego nie powtórzyła
                            st.session_state.active_trades[sym] = True
                            st.session_state.signal_cooldown[tf_key] = time.time()

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

                            t_item = {
                                "Czas": time.strftime("%Y-%m-%d %H:%M:%S"),
                                "Typ": f"BOT FUTURES {label}",
                                "Para": sym,
                                "Budżet": f"{budget:.2f} USDT",
                                "Dźwignia": f"{bot_leverage}x",
                                "Cena": f"{f_price:.4f}",
                            }
                            st.session_state.trade_history.insert(0, t_item)
                            save_trade_to_db(st.session_state.user_id, t_item)
                            
                            current_active_count += 1
                            if current_active_count >= max_active_futures_positions:
                                break
            except Exception:
                pass

# =====================================================================
# WIDOK NA ŻYWO: SKANER PAR FUTURES
# =====================================================================
st.markdown("---")
st.subheader("📈 Skaner Par Futures (Status i Pozycje)")
if futures_ex:
    try:
        f_tickers = futures_ex.fetch_tickers()
        top_fut_view = sorted(
            [sym for sym, data in f_tickers.items() if (sym.endswith(":USDT") or "/USDT:USDT" in sym) and "BULL" not in sym and "BEAR" not in sym],
            key=lambda x: f_tickers[x].get("quoteVolume", 0), reverse=True
        )[:max_fut_scan_pairs]
        fut_data_list = []
        for sym in top_fut_view:
            t_data = f_tickers.get(sym, {})
            pos = exchange_positions.get(sym)
           
            side_val = "-"
            lev_val = "-"
            margin_val = "-"
            pnl_val = "-"
            status_desc = "⏳ Oczekująca"
           
            if pos:
                side_val = pos.get("side", "").upper()
                lev_val = f"{float(pos.get('leverage', 1))}x"
                notional = float(pos.get("notional", 0))
                lev = float(pos.get('leverage', 1))
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
                    margin_val = "-"
                    pnl_val = "Oczekiwanie"
                    status_desc = "⚡ Sygnał Gotowy"
                except Exception:
                    lev_val = f"{manual_leverage}x"

            fut_data_list.append({
                "Para": sym,
                "Cena": f"{float(t_data.get('last', 0)):.4f}",
                "Zmiana 24h": f"{float(t_data.get('percentage', 0)):+.2f}%",
                "Wolumen (USDT)": f"{float(t_data.get('quoteVolume', 0)):,.0f}",
                "Strategia": "Futures Trend + Smart Risk",
                "Strona": side_val,
                "Dźwignia": lev_val,
                "Marża": margin_val,
                "Wynik PnL": pnl_val,
                "Status": status_desc
            })
        if fut_data_list:
            st.dataframe(pd.DataFrame(fut_data_list), use_container_width=True)
        else:
            st.info("Brak danych Futures do wyświetlenia.")
    except Exception:
        st.info("Brak danych rynkowych Futures.")
else:
    st.info("Skonfiguruj klucze API Futures w panelu bocznym i zapisz je, aby widzieć skaner i portfel.")

# =====================================================================
# HISTORIA ZAMKNIĘTYCH POZYCJI I Z/S (Z GIEŁDY BITGET)
# =====================================================================
st.markdown("---")
st.subheader("📜 Dziennik Zamkniętych Pozycji i Zysków/Strat (Z Giełdy)")
if futures_ex:
    try:
        closed_orders = futures_ex.fetch_closed_orders(limit=30)
        closed_data = []
        for o in closed_orders:
            symbol = o.get("symbol")
            side = o.get("side")
            price = o.get("average") or o.get("price") or 0.0
            amount = o.get("amount") or 0.0
            timestamp = o.get("timestamp")
            dt_str = pd.to_datetime(timestamp, unit="ms").strftime("%Y-%m-%d %H:%M:%S") if timestamp else "-"
            
            info = o.get("info", {})
            pnl = info.get("profit", info.get("pnl", "N/A"))
            
            closed_data.append({
                "Czas": dt_str,
                "Para": symbol,
                "Strona": side,
                "Cena Wykonania": f"{float(price):.4f}" if price else "-",
                "Ilość": f"{float(amount):.4f}" if amount else "-",
                "Zysk / Strata (USDT)": str(pnl)
            })
        if closed_data:
            st.dataframe(pd.DataFrame(closed_data), use_container_width=True)
        else:
            st.info("Brak zamkniętych pozycji w historii giełdy.")
    except Exception as e:
        st.info(f"Brak danych lub oczekiwanie na połączenie z API giełdy dla historii: {e}")
else:
    st.info("Skonfiguruj klucze API, aby widzieć historię zamkniętych pozycji.")

# =====================================================================
# DZIENNIK TRANSAKCJI (LOKALNA BAZA)
# =====================================================================
st.markdown("---")
st.subheader("📜 Dziennik Otwartych Transakcji w Sesji (Zapisany w bazie)")
if st.session_state.trade_history:
    st.dataframe(pd.DataFrame(st.session_state.trade_history), use_container_width=True)
else:
    st.info("Brak zarejestrowanych transakcji w bazie.")

if st.session_state.scanner_active or st.session_state.trend_bot_fut_active or st.session_state.listing_sniper_active:
    time.sleep(scan_interval)
    st.rerun()

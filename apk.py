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
    page_title="Bitget Futures - Snajper Nowych Listingów",
    layout="wide",
)

DB_FILE = "users.db"
STRIPE_CONFIG_FILE = "stripe_config.json"

# =====================================================================
# FUNKCJE POMOCNICZE ADMINISTRATORA
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

# =====================================================================
# STAN SESJI (SESSION STATE) - BEZPIECZNA INICJALIZACJA
# =====================================================================
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
if "last_fut_free" not in st.session_state:
    st.session_state.last_fut_free = 0.0
if "last_fut_total" not in st.session_state:
    st.session_state.last_fut_total = 0.0
if "last_exchange_positions" not in st.session_state:
    st.session_state.last_exchange_positions = {}
if "last_active_count" not in st.session_state:
    st.session_state.last_active_count = 0
if "last_unrealized_pnl" not in st.session_state:
    st.session_state.last_unrealized_pnl = 0.0
if "session_start_time" not in st.session_state:
    st.session_state.session_start_time = datetime.now()
if "trade_history" not in st.session_state:
    st.session_state.trade_history = []
if "scanner_active" not in st.session_state:
    st.session_state.scanner_active = False
if "futures_sniper_active" not in st.session_state:
    st.session_state.futures_sniper_active = True

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
    """ <style> @import url('https://fonts.googleapis.com/css2?family=Bungee+Inline&family=Cinzel:wght@700&display=swap'); .stApp { background-color: #0d0b0a; } section[data-testid="stSidebar"] { background-color: #141110; border-right: 2px solid #3d2f1f; } .hero-wrapper { display: flex; align-items: center; justify-content: center; width: 100%; padding-top: 50px; padding-bottom: 20px; } .retro-ornate-frame { position: relative; background: radial-gradient(circle, #221a14 0%, #110d0a 100%); border: 6px double #f3d57a; padding: 40px 30px; border-radius: 16px; box-shadow: 0 0 50px rgba(243, 213, 122, 0.4), inset 0 0 35px rgba(0, 0, 0, 0.9); width: 100%; max-width: 600px; text-align: center; } .retro-vintage-title { font-family: 'Bungee Inline', cursive, sans-serif; font-size: 3rem; color: #f3d57a; letter-spacing: 4px; text-shadow: 4px 4px 0px #8b0000, 8px 8px 0px rgba(0,0,0,0.95); margin-bottom: 10px; } .retro-subtitle { font-family: 'Cinzel', serif; color: #e6c687; font-size: 1.1rem; letter-spacing: 2px; margin-bottom: 25px; } div.stButton > button { background: linear-gradient(135deg, #1e4d2b 0%, #0f2b17 100%) !important; color: #f3d57a !important; border: 2px solid #f3d57a !important; font-family: 'Cinzel', serif !important; font-weight: 700 !important; font-size: 1rem !important; padding: 10px 24px !important; border-radius: 8px !important; box-shadow: 0 4px 15px rgba(0, 0, 0, 0.6) !important; transition: all 0.3s ease !important; } div.stButton > button:hover { background: linear-gradient(135deg, #28663a 0%, #163d22 100%) !important; border-color: #ffe89d !important; color: #ffe89d !important; box-shadow: 0 0 20px rgba(243, 213, 122, 0.4) !important; transform: translateY(-2px); } div[data-testid="stMetric"] { border: 2px solid #f3d57a; border-radius: 10px; padding: 10px 12px; background-color: rgba(243, 213, 122, 0.03); box-shadow: 0 4px 12px rgba(0, 0, 0, 0.2); } div[data-testid="stMetric"] label { color: #f3d57a !important; } </style> """,
    unsafe_allow_html=True,
)

# =====================================================================
# EKRAN LOGOWANIA / REJESTRACJI
# =====================================================================
if not st.session_state.logged_in:
    st.markdown(
        """ <div class="hero-wrapper"> <div class="retro-ornate-frame"> <div class="retro-vintage-title">BITGET FUTURES</div> <div class="retro-subtitle">SNAJPER NOWYCH LISTINGÓW & ZYSKU</div> """,
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
                st.session_state.session_start_time = datetime.now()
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

if futures_ex and not st.session_state.known_markets:
    try:
        markets = futures_ex.load_markets()
        st.session_state.known_markets = set(markets.keys())
    except Exception:
        pass

st.sidebar.markdown("---")
st.sidebar.markdown("### ⚙️ Kapitał i Ryzyko Nowego Listingu")
max_single_trade_usdt = st.sidebar.number_input("🛡️ Kwota USDT na 1 listing", 5.0, 5000.0, 50.0, 5.0)
max_active_futures_positions = st.sidebar.slider("📈 Maks. aktywne pozycje Futures", 1, 20, 5)

st.sidebar.markdown("---")
st.sidebar.markdown("### 🎯 Snajper Szybkiego Zysku (Quick Scalp)")
quick_take_profit_pct = st.sidebar.slider("Zamknij pozycję przy zysku (%)", 0.3, 10.0, 1.0, 0.1)
custom_stop_loss_pct = st.sidebar.slider("Awaryjny Stop-Loss (%)", 1, 30, 5)

st.sidebar.markdown("---")
st.sidebar.markdown("### ⚡ Ustawienia Snajpera Nowych Par")
sniper_leverage = st.sidebar.slider("Dźwignia dla nowych listingów", 1, 20, 5)

st.sidebar.markdown("---")
st.sidebar.markdown("### 🔄 Częstotliwość Nasłuchu")
if "sidebar_auto_scan_cb" not in st.session_state:
    st.session_state.sidebar_auto_scan_cb = st.session_state.scanner_active

def toggle_scanner_from_sidebar():
    st.session_state.scanner_active = st.session_state.sidebar_auto_scan_cb

auto_scan_enabled = st.sidebar.checkbox("Włącz nasłuch nowych par w tle", key="sidebar_auto_scan_cb", on_change=toggle_scanner_from_sidebar)
scan_interval = st.sidebar.slider("Interwał sprawdzania giełdy (s)", 1, 60, 2)

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
    st.session_state.futures_sniper_active = False
    st.session_state.trade_history = []
    st.success("🚨 KILL SWITCH WYKONANY. Zamknięto pozycje futures i wyłączono snajpera.")
    time.sleep(2)
    st.rerun()

# =====================================================================
# POBIERANIE SALDA FUTURES Z PAMIĘCIĄ PODRĘCZNĄ
# =====================================================================
if futures_ex:
    try:
        f_bal = futures_ex.fetch_balance({"accountType": "usdt-futures"})
        temp_free, temp_total = 0.0, 0.0
        if "USDT" in f_bal and isinstance(f_bal["USDT"], dict):
            temp_free = float(f_bal["USDT"].get("free", 0.0))
            temp_total = float(f_bal["USDT"].get("total", 0.0))
        elif "free" in f_bal and "total" in f_bal:
            temp_free = float(f_bal.get("free", {}).get("USDT", 0.0))
            temp_total = float(f_bal.get("total", {}).get("USDT", 0.0))
        
        if temp_total == 0.0 and "info" in f_bal:
            try:
                info_data = f_bal["info"]
                if isinstance(info_data, list) and len(info_data) > 0:
                    for acc in info_data:
                        if acc.get("marginCoin") == "USDT" or acc.get("coin") == "USDT":
                            temp_free = float(acc.get("available", acc.get("usdtAvailable", temp_free)))
                            temp_total = float(acc.get("equity", acc.get("usdtEquity", temp_total)))
            except Exception:
                pass
        
        if temp_total > 0:
            st.session_state.last_fut_free = temp_free
            st.session_state.last_fut_total = temp_total
    except Exception:
        pass

fut_free = st.session_state.get("last_fut_free", 0.0)
fut_total = st.session_state.get("last_fut_total", 0.0)

# =====================================================================
# POBIERANIE POZYCJI Z PAMIĘCIĄ PODRĘCZNĄ
# =====================================================================
total_unrealized_pnl = st.session_state.get("last_unrealized_pnl", 0.0)
active_positions_count = st.session_state.get("last_active_count", 0)
exchange_positions = st.session_state.get("last_exchange_positions", {})

if futures_ex:
    try:
        positions = futures_ex.fetch_positions()
        temp_positions = {}
        temp_count = 0
        temp_pnl = 0.0
        for p in positions:
            contracts = float(p.get("contracts", 0))
            if contracts > 0:
                temp_count += 1
                temp_pnl += float(p.get("unrealizedPnl", 0.0))
                temp_positions[p["symbol"]] = p
        
        st.session_state.last_exchange_positions = temp_positions
        st.session_state.last_active_count = temp_count
        st.session_state.last_unrealized_pnl = temp_pnl

        exchange_positions = temp_positions
        active_positions_count = temp_count
        total_unrealized_pnl = temp_pnl
    except Exception:
        exchange_positions = st.session_state.get("last_exchange_positions", {})
        active_positions_count = st.session_state.get("last_active_count", 0)
        total_unrealized_pnl = st.session_state.get("last_unrealized_pnl", 0.0)

# =====================================================================
# GŁÓWNE KAFELKI METRYK
# =====================================================================
col1, col2, col3, col4 = st.columns([1, 1, 1, 1])
with col1:
    st.metric(
        label="🔵 Portfel Futures", 
        value=f"{fut_total:.2f} USDT", 
        delta=f"Wolne: {fut_free:.2f} | Aktywne: {active_positions_count}/{max_active_futures_positions}"
    )
with col2:
    st.metric(
        label="📊 Wynik PnL Na Żywo", 
        value=f"{total_unrealized_pnl:+.2f} USDT", 
        delta=f"Otwarte pozycje"
    )
with col3:
    session_start = st.session_state.get("session_start_time", datetime.now())
    elapsed = datetime.now() - session_start
    total_seconds = int(elapsed.total_seconds())
    hours, remainder = divmod(total_seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    st.metric(label="⏰ Czas Sesji", value=f"{hours:02d}:{minutes:02d}:{seconds:02d}", delta=f"Nasłuch co: {scan_interval}s")
with col4:
    st.metric(
        label="🎯 Sloty / Pozycje", 
        value=f"{active_positions_count} / {max_active_futures_positions}", 
        delta="Zajęte / Limit slotów"
    )

st.markdown("---")

# =====================================================================
# PANEL STEROWANIA SNAJPEREM NOWYCH LISTINGÓW
# =====================================================================
st.subheader("🎯 Panel Sterowania Snajperem Nowych Par Futures")
with st.container(border=True):
    if "main_cb_sniper_fut" not in st.session_state:
        st.session_state.main_cb_sniper_fut = st.session_state.futures_sniper_active

    def toggle_main_sniper_fut():
        st.session_state.futures_sniper_active = st.session_state.main_cb_sniper_fut

    st.checkbox("🚀 Aktywny Nasłuch Nowych Listingów w Czasie Rzeczywistym", key="main_cb_sniper_fut", on_change=toggle_main_sniper_fut)
    if st.session_state.futures_sniper_active:
        st.success("🟢 Snajper czeka na wylądowanie nowych kontraktów na Bitget!")
    else:
        st.info("🔴 Snajper wstrzymany.")

st.markdown("---")
col_btn, col_status = st.columns([2, 1])
with col_btn:
    if not st.session_state.scanner_active:
        if st.button("🚀 Uruchom Nasłuch Tła", type="primary", use_container_width=True):
            st.session_state.scanner_active = True
            st.rerun()
    else:
        if st.button("⏹️ Zatrzymaj Nasłuch Tła", type="secondary", use_container_width=True):
            st.session_state.scanner_active = False
            st.rerun()
with col_status:
    if st.session_state.scanner_active:
        st.success("STATUS: NASŁUCH AKTYWNY")
    else:
        st.error("STATUS: ZATRZYMANY")

MIN_FUT_TRADE = 5.0

# =====================================================================
# SNAJPER SZYBKIEGO ZYSKU I STOP-LOSS DLA OTWARTYCH POZYCJI
# =====================================================================
if futures_ex:
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
                    
                    close_side = "sell" if side == "long" else "buy"
                    
                    if pnl_pct >= float(quick_take_profit_pct):
                        futures_ex.create_market_order(sym, close_side, contracts, params={"reduceOnly": True})
                        st.session_state.trade_history.insert(0, {
                            "Czas": time.strftime("%Y-%m-%d %H:%M:%S"),
                            "Typ": f"🎯 SNAJPER ZYSKU (+{pnl_pct:.2f}%)",
                            "Para": sym,
                            "Cena": f"{mark_price:.4f}",
                        })
                    elif pnl_pct <= -float(custom_stop_loss_pct):
                        futures_ex.create_market_order(sym, close_side, contracts, params={"reduceOnly": True})
                        st.session_state.trade_history.insert(0, {
                            "Czas": time.strftime("%Y-%m-%d %H:%M:%S"),
                            "Typ": f"🛡️ STOP-LOSS ({pnl_pct:.2f}%)",
                            "Para": sym,
                            "Cena": f"{mark_price:.4f}",
                        })
    except Exception:
        pass

# =====================================================================
# WYKRYWANIE NOWYCH LISTINGÓW I NATYCHMIASTOWY ZAKUP
# =====================================================================
orders_opened_this_tick = 0
active_symbols = list(exchange_positions.keys())

if futures_ex and st.session_state.futures_sniper_active:
    try:
        current_markets = futures_ex.load_markets()
        current_symbols = set(current_markets.keys())
        
        if not st.session_state.known_markets:
            st.session_state.known_markets = current_symbols
        else:
            new_symbols = current_symbols - st.session_state.known_markets
            st.session_state.known_markets = current_symbols
            
            valid_new_symbols = [
                s for s in new_symbols 
                if (s.endswith(":USDT") or "/USDT:USDT" in s) 
                and "BULL" not in s and "BEAR" not in s
            ]
            
            if valid_new_symbols and fut_free >= MIN_FUT_TRADE:
                for sym in valid_new_symbols:
                    if (len(active_symbols) + orders_opened_this_tick) >= max_active_futures_positions:
                        break

                    if sym in active_symbols:
                        continue
                    
                    ticker = futures_ex.fetch_ticker(sym)
                    f_price = float(ticker.get("last", 0))
                    if f_price > 0:
                        budget = max(MIN_FUT_TRADE, min(fut_free, max_single_trade_usdt))

                        try:
                            futures_ex.set_leverage(sniper_leverage, sym)
                        except Exception:
                            pass

                        contracts = (budget * sniper_leverage) / f_price
                        try:
                            contracts_prec = float(futures_ex.amount_to_precision(sym, contracts))
                            futures_ex.create_order(sym, 'market', 'buy', contracts_prec)
                        except Exception:
                            futures_ex.create_order(sym, 'market', 'buy', float(contracts))

                        orders_opened_this_tick += 1
                        st.session_state.trade_history.insert(0, {
                            "Czas": time.strftime("%Y-%m-%d %H:%M:%S"),
                            "Typ": "🚀 NOWY LISTING - SNIPER BUY",
                            "Para": sym,
                            "Budżet": f"{budget:.2f} USDT",
                            "Dźwignia": f"{sniper_leverage}x",
                            "Cena": f"{f_price:.4f}",
                        })
                        break
    except Exception:
        pass

# =====================================================================
# AKTUALNIE OTWARTE POZYCJE (WIDOK)
# =====================================================================
st.markdown("---")
st.subheader("📋 Aktywne Pozycje Na Giełdzie")
if exchange_positions:
    pos_table_data = []
    for sym, pos in exchange_positions.items():
        entry_p = float(pos.get("entryPrice", 0))
        mark_p = float(pos.get("markPrice", 0))
        lev = float(pos.get("leverage", 1))
        side = pos.get("side", "").upper()
        contracts = float(pos.get("contracts", 0))
        unreal_pnl = float(pos.get("unrealizedPnl", 0))
        
        pos_table_data.append({
            "Para": sym,
            "Strona": side,
            "Kontrakty": contracts,
            "Dźwignia": f"{lev}x",
            "Cena Wejścia": f"{entry_p:.4f}",
            "Cena Mark": f"{mark_p:.4f}",
            "PnL (USDT)": f"{unreal_pnl:+.2f} USDT"
        })
    st.dataframe(pd.DataFrame(pos_table_data), use_container_width=True)
else:
    st.info("Brak otwartych pozycji. Snajper czeka na wejście nowych par na giełdę.")

# =====================================================================
# DZIENNIK TRANSAKCJI
# =====================================================================
st.markdown("---")
st.subheader("📜 Dziennik Transakcji Snajpera")
if st.session_state.trade_history:
    st.dataframe(pd.DataFrame(st.session_state.trade_history), use_container_width=True)
else:
    st.info("Brak transakcji w tej sesji.")

# =====================================================================
# PĘTLA ODŚWIEŻANIA TŁA
# =====================================================================
if st.session_state.scanner_active or st.session_state.futures_sniper_active:
    time.sleep(scan_interval)
    st.rerun()

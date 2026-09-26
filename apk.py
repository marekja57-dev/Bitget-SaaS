from datetime import datetime
import hashlib
import json
import logging
import os
import sqlite3
import time
import ccxt
import numpy as np
import pandas as pd
import streamlit as st
import stripe

st.set_page_config(
    page_title="Multi-Exchange Futures SaaS",
    layout="wide",
)

DB_FILE = "users.db"
STRIPE_CONFIG_FILE = "stripe_config.json"

# =====================================================================
# FUNKCJE POMOCNICZE
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
# WSKAŹNIKI TECHNICZNE
# =====================================================================
def calculate_indicators(df, ema_period=50, adx_period=14):
    df["ema50"] = df["close"].ewm(span=ema_period, adjust=False).mean()
    exp1 = df["close"].ewm(span=12, adjust=False).mean()
    exp2 = df["close"].ewm(span=26, adjust=False).mean()
    df["macd"] = exp1 - exp2
    df["signal"] = df["macd"].ewm(span=9, adjust=False).mean()
    df["macd_hist"] = df["macd"] - df["signal"]

    df["tr0"] = abs(df["high"] - df["low"])
    df["tr1"] = abs(df["high"] - df["close"].shift(1))
    df["tr2"] = abs(df["low"] - df["close"].shift(1))
    df["tr"] = df[["tr0", "tr1", "tr2"]].max(axis=1)

    df["up_move"] = df["high"] - df["high"].shift(1)
    df["down_move"] = df["low"].shift(1) - df["low"]

    df["plus_dm"] = np.where(
        (df["up_move"] > df["down_move"]) & (df["up_move"] > 0),
        df["up_move"],
        0,
    )
    df["minus_dm"] = np.where(
        (df["down_move"] > df["up_move"]) & (df["down_move"] > 0),
        df["down_move"],
        0,
    )

    alpha = 1 / adx_period
    df["tr_smooth"] = df["tr"].ewm(alpha=alpha, adjust=False).mean()
    df["plus_di_smooth"] = df["plus_dm"].ewm(alpha=alpha, adjust=False).mean()
    df["minus_di_smooth"] = df["minus_dm"].ewm(alpha=alpha, adjust=False).mean()

    tr_smooth = df["tr_smooth"].replace(0, np.nan)
    df["plus_di"] = 100 * (df["plus_di_smooth"] / tr_smooth)
    df["minus_di"] = 100 * (df["minus_di_smooth"] / tr_smooth)

    di_sum = (df["plus_di"] + df["minus_di"]).replace(0, np.nan)
    df["dx"] = 100 * abs(df["plus_di"] - df["minus_di"]) / di_sum
    df["adx"] = df["dx"].ewm(alpha=alpha, adjust=False).mean()

    delta = df["close"].diff()
    gain = (delta.where(delta > 0, 0)).ewm(span=14, adjust=False).mean()
    loss = (-delta.where(delta < 0, 0)).ewm(span=14, adjust=False).mean()
    rs = gain / loss.replace(0, np.nan)
    df["rsi"] = 100 - (100 / (1 + rs))

    return df

# =====================================================================
# INICJALIZACJA BAZY DANYCH SQLITE
# =====================================================================
def init_db():
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("""
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
    """)
    for col, col_type in [
        ("api_key", "TEXT"),
        ("secret_key", "TEXT"),
        ("passphrase", "TEXT"),
        ("stripe_paid", "INTEGER DEFAULT 0"),
        ("is_admin", "INTEGER DEFAULT 0"),
    ]:
        try:
            cursor.execute(f"ALTER TABLE users ADD COLUMN {col} {col_type}")
        except sqlite3.OperationalError:
            pass

    for adm_email in ADMIN_EMAILS:
        cursor.execute(
            "UPDATE users SET is_admin = 1, stripe_paid = 1 WHERE LOWER(TRIM(email)) = ?",
            (adm_email,),
        )

    cursor.execute(
        "SELECT * FROM users WHERE LOWER(TRIM(email)) = ?",
        ("admin@bot-bitget.pl",),
    )
    if not cursor.fetchone():
        admin_pass = st.secrets.get("ADMIN_PASSWORD", "TwojeTajneHaslo123")
        cursor.execute(
            "INSERT INTO users (email, password, is_admin, stripe_paid) VALUES (?, ?, 1, 1)",
            ("admin@bot-bitget.pl", admin_pass),
        )
    conn.commit()
    conn.close()

init_db()

def load_stripe_credentials():
    if os.path.exists(STRIPE_CONFIG_FILE):
        try:
            with open(STRIPE_CONFIG_FILE, "r") as f:
                data = json.load(f)
                return (
                    data.get("stripe_pk", ""),
                    data.get("stripe_sk", ""),
                    data.get("stripe_price_id", ""),
                )
        except Exception:
            pass
    return "", "", ""

saved_stripe_pk, saved_stripe_sk, saved_stripe_price_id = load_stripe_credentials()
stripe_pk_val = saved_stripe_pk or st.secrets.get("STRIPE_PK", "")
stripe_sk_val = saved_stripe_sk or st.secrets.get("STRIPE_SK", "")
stripe_price_id_val = saved_stripe_price_id or st.secrets.get("STRIPE_PRICE_ID", "")

if stripe_sk_val:
    stripe.api_key = stripe_sk_val

# =====================================================================
# STAN SESJI
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
if "scanner_active" not in st.session_state:
    st.session_state.scanner_active = False
if "trend_bot_fut_active" not in st.session_state:
    st.session_state.trend_bot_fut_active = False
if "session_start_time" not in st.session_state:
    st.session_state.session_start_time = datetime.now()
if "trade_history" not in st.session_state:
    st.session_state.trade_history = []
if "signal_cooldown" not in st.session_state:
    st.session_state.signal_cooldown = {}
if "active_trades" not in st.session_state:
    st.session_state.active_trades = {}
if "scanner_diagnostics" not in st.session_state:
    st.session_state.scanner_diagnostics = []
if "lang" not in st.session_state:
    st.session_state.lang = "Polski"
if "api_key" not in st.session_state:
    st.session_state.api_key = ""
if "secret_key" not in st.session_state:
    st.session_state.secret_key = ""
if "passphrase" not in st.session_state:
    st.session_state.passphrase = ""
if "selected_exchange" not in st.session_state:
    st.session_state.selected_exchange = "Bitget"
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
            cursor.execute(
                "UPDATE users SET stripe_paid = 1 WHERE id = ?",
                (st.session_state.user_id,),
            )
            conn.commit()
            conn.close()
        except Exception:
            pass
    st.success("🎉 Płatność zakończona sukcesem! Twoja subskrypcja została aktywowana.")
    st.query_params.clear()

# =====================================================================
# STYLIZACJA
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
        st.markdown(
            "<p style='color: #f3d57a; font-family: Cinzel, serif;'>Logowanie do Panelu Klienta</p>",
            unsafe_allow_html=True,
        )
        login_email = st.text_input("Adres e-mail", key="log_email")
        login_pass = st.text_input("Hasło", type="password", key="log_pass")
        if st.button("ZALOGUJ SIĘ", use_container_width=True):
            conn = sqlite3.connect(DB_FILE)
            cursor = conn.cursor()
            cursor.execute(
                "SELECT id, email, password, is_admin, stripe_paid, api_key, secret_key, passphrase FROM users WHERE LOWER(TRIM(email)) = ?",
                (login_email.strip().lower(),),
            )
            user_row = cursor.fetchone()
            conn.close()
            if user_row and user_row[2] == login_pass:
                user_email_str = user_row[1].strip().lower()
                is_admin_flag = (
                    True if user_email_str in ADMIN_EMAILS else bool(user_row[3])
                )
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
        st.markdown(
            "<p style='color: #f3d57a; font-family: Cinzel, serif;'>Rejestracja Nowego Konta</p>",
            unsafe_allow_html=True,
        )
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
                        (reg_email.strip(), reg_pass, is_adm, is_paid),
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
# GŁÓWNA APLIKACJA
# =====================================================================
st.session_state.lang = st.sidebar.selectbox(
    "🌐 Język / Language", ["Polski", "English"], key="lang_selector"
)

def get_exchange():
    if not st.session_state.get("api_key"):
        return None
    try:
        ex_id = st.session_state.get("selected_exchange", "Bitget").lower()
        exchange_class = getattr(ccxt, ex_id)
        config = {
            "apiKey": st.session_state.api_key,
            "secret": st.session_state.secret_key,
            "enableRateLimit": True,
            "options": {
                "defaultType": "swap",
                "createOrder": {"createMarketBuyOrderRequiresPrice": False},
            },
        }
        if ex_id in ["bitget", "okx"] and st.session_state.get("passphrase"):
            config["password"] = st.session_state.passphrase

        exchange = exchange_class(config)
        return exchange
    except Exception:
        return None

# =====================================================================
# AUTONOMICZNY, PŁYNNY SYSTEM DOBORU KAPITAŁU I DŹWIGNI (W RAMACH LIMITU)
# =====================================================================
def calculate_dynamic_allocation(free_balance, max_positions, max_single_limit, adx_val=20.0, volume=10_000_000):
    if free_balance <= 0:
        return max_single_limit
    
    safe_balance_pool = free_balance * 0.85
    base_slot_allocation = safe_balance_pool / max(1, max_positions)
    
    adx_clamped = min(max(adx_val, 10.0), 60.0)
    adx_multiplier = 0.75 + (adx_clamped - 10.0) / (50.0 / 0.5)
    
    vol_multiplier = np.log10(max(volume, 1_000_000)) / np.log10(20_000_000)
    vol_multiplier = max(0.8, min(1.2, vol_multiplier))
    
    dynamic_alloc = base_slot_allocation * adx_multiplier * vol_multiplier
    upper_bound = min(max_single_limit, free_balance * 0.95)
    return min(upper_bound, max(10.0, dynamic_alloc))

def get_exchange_max_leverage(exchange, symbol, default_max=15):
    try:
        market = exchange.market(symbol)
        if 'limits' in market and 'leverage' in market['limits']:
            max_lev = market['limits']['leverage'].get('max')
            if max_lev:
                return int(max_lev)
    except Exception:
        pass
    return default_max

def get_smart_leverage(adx_val, exchange_limit, preferred_max=15):
    """
    Płynny dobór dźwigni w zakresie od 1x do preferowanego maksimum (np. 15x),
    nigdy nie przekraczając narzuconego limitu.
    """
    effective_max = min(preferred_max, exchange_limit)
    adx_clamped = min(max(adx_val, 10.0), 55.0)
    ratio = (adx_clamped - 10.0) / (55.0 - 10.0)
    floating_lev = 1.0 + ratio * (effective_max - 1.0)
    return int(round(floating_lev))

# =====================================================================
# PANEL BOCZNY (SIDEBAR)
# =====================================================================
st.sidebar.markdown(f"### 👤 {st.session_state.get('user_email', '')}")
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

st.sidebar.header("⚙️ Ustawienia Giełdy & API")
selected_exchange = st.sidebar.selectbox(
    "Wybierz Giełdę:",
    options=["Bitget", "Binance", "Bybit", "OKX"],
    index=0,
    key="sidebar_selected_exchange_sb"
)
st.session_state["selected_exchange"] = selected_exchange

st.sidebar.markdown("---")
st.sidebar.subheader(f"🔑 Klucze API ({selected_exchange})")

input_api = st.sidebar.text_input(
    f"API Key ({selected_exchange}):",
    value=st.session_state.get("api_key", ""),
    type="password",
    key=f"key_{selected_exchange}"
)
input_secret = st.sidebar.text_input(
    f"API Secret ({selected_exchange}):",
    value=st.session_state.get("secret_key", ""),
    type="password",
    key=f"secret_{selected_exchange}"
)

if selected_exchange in ["Bitget", "OKX"]:
    input_pass = st.sidebar.text_input(
        f"Passphrase ({selected_exchange}):",
        value=st.session_state.get("passphrase", ""),
        type="password",
        key=f"pass_{selected_exchange}"
    )
else:
    input_pass = ""

if st.sidebar.button("💾 ZAPISZ MOJE KLUCZE", use_container_width=True, key="sidebar_zapisz_klucze_btn"):
    if input_api and input_secret:
        st.session_state.api_key = input_api
        st.session_state.secret_key = input_secret
        st.session_state.passphrase = input_pass
        try:
            conn = sqlite3.connect(DB_FILE)
            cursor = conn.cursor()
            cursor.execute(
                "UPDATE users SET api_key = ?, secret_key = ?, passphrase = ? WHERE id = ?",
                (input_api, input_secret, input_pass, st.session_state.get("user_id"))
            )
            conn.commit()
            conn.close()
        except Exception:
            pass
        st.success(f"Zapisano klucze dla {selected_exchange}!")
        st.rerun()
    else:
        st.error("Wypełnij wymagane pola kluczy.")

st.sidebar.markdown("---")
st.sidebar.markdown("### 🛡️ Strefa Subskrypcji")
if is_user_admin() or is_user_paid():
    st.sidebar.success("Subskrypcja aktywna (Dostęp Pełny)")
else:
    st.sidebar.warning("⚠️ Brak aktywnej subskrypcji")
    st.sidebar.link_button(
        "OPŁAĆ DOSTĘP (49 PLN)", "https://buy.stripe.com/00w0kecLiSfbc8c13qA88"
    )

st.sidebar.markdown("---")
st.sidebar.markdown("### 💰 Kapitał i Ryzyko")
max_single_trade_usdt = st.sidebar.number_input("Maksymalnie USDT na 1 pozycję", 5.0, 5000.0, 50.0, 5.0, key="sb_max_single_trade")
max_active_futures_positions = st.sidebar.slider("Maks. aktywne pozycje Futures", 1, 20, 5, key="sb_max_active_pos")

st.sidebar.markdown("---")
st.sidebar.markdown("### 🛑 Zarządzanie Ryzykiem ROE (SL / TP)")
enable_roe_guard = st.sidebar.checkbox("Włącz strażnika SL / TP ROE", value=True, key="enable_roe_guard")

if enable_roe_guard:
    custom_stop_loss_roe = st.sidebar.slider("Stop-Loss ROE (%)", 0.5, 50.0, 4.0, 0.5, key="custom_stop_loss_roe")
    custom_take_profit_roe = st.sidebar.slider("Take-Profit ROE (%)", 1.0, 100.0, 15.0, 0.5, key="custom_take_profit_roe")
else:
    custom_stop_loss_roe = 999.0
    custom_take_profit_roe = 999.0

st.sidebar.markdown("---")
st.sidebar.markdown("### 🛡️ Globalny Stop-Loss / Take-Profit Sesji")
enable_global_session_guard = st.sidebar.checkbox("Włącz globalny SL/TP sesji", value=True, key="enable_global_session_guard")

if enable_global_session_guard:
    global_session_sl_usdt = st.sidebar.slider("Globalny SL sesji (USDT)", min_value=-50.0, max_value=0.0, value=-50.0, step=1.0, key="global_session_sl_usdt")
    global_session_tp_usdt = st.sidebar.slider("Globalny TP sesji (USDT)", min_value=1.0, max_value=100.0, value=100.0, step=1.0, key="global_session_tp_usdt")
else:
    global_session_sl_usdt = -9999.0
    global_session_tp_usdt = 9999.0

st.sidebar.markdown("---")
st.sidebar.markdown("### ⚡ Zarządzanie Dźwignią")
leverage_mode = st.sidebar.radio("Tryb Dźwigni", ["Autonomiczny (płynny w granicach limitu)", "Ręczny"], key="sb_leverage_mode")
max_allowed_leverage = st.sidebar.slider("Maksymalna dozwolona dźwignia", 1, 50, 15, 1, key="sb_max_allowed_leverage")
manual_leverage = st.sidebar.slider("Stała dźwignia Futures", 1, 50, 5, 1, key="sb_manual_leverage")

st.sidebar.markdown("---")
st.sidebar.markdown("### ⏱️ Timeframe Analizy")
fut_tf = st.sidebar.selectbox("Interwał", ["1m", "5m", "15m", "30m", "1h", "4h", "1d"], index=4, key="sb_fut_tf")
ema_fast_val = int(st.sidebar.number_input("Okres EMA Szybka", min_value=1, max_value=200, value=9, key="conf_ema_fast"))
ema_slow_val = int(st.sidebar.number_input("Okres EMA Wolna", min_value=2, max_value=300, value=21, key="conf_ema_slow"))

st.sidebar.markdown("---")
st.sidebar.markdown("### 🤖 Panel Sterowania Botem Futures")
scan_interval = st.sidebar.slider("Interwał odświeżania (s)", 3, 300, 5, key="sb_scan_interval")
max_fut_scan_pairs = st.sidebar.slider("Liczba par Futures", 1, 100, 100, 1, key="sb_max_fut_pairs")

st.sidebar.markdown("---")
emergency_kill = st.sidebar.button(
    "🔴 ZAMKNIJ WSZYSTKO (KILL SWITCH)",
    type="primary",
    use_container_width=True,
    key="sidebar_kill_switch_btn",
)

futures_ex = get_exchange()

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
                        if contracts_prec > 0:
                            futures_ex.create_order(sym, "market", side, contracts_prec, params={"reduceOnly": True})
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
    st.success("🔴 KILL SWITCH WYKONANY. Zamknięto wszystkie pozycje Futures.")
    time.sleep(2)
    st.rerun()

# ==========================================
# SALDO I METRYKI
# ==========================================
fut_free, fut_total = 0.0, 0.0
active_positions_count = 0
total_unrealized_pnl = 0.0
total_margin_used = 0.0

if futures_ex:
    try:
        f_bal = futures_ex.fetch_balance({"type": "swap"})
        usdt_info = f_bal.get("USDT", {})
        fut_total = float(usdt_info.get("total", 0.0) or 0.0)
        if fut_total == 0.0 and "info" in f_bal:
            try:
                for asset in f_bal["info"].get("data", []):
                    if asset.get("marginCoin") == "USDT" or asset.get("coin") == "USDT":
                        fut_total = float(asset.get("equity", asset.get("total", 0.0)) or 0.0)
                        break
            except Exception:
                pass

        current_positions = []
        try:
            current_positions = futures_ex.fetch_positions()
        except Exception:
            pass

        active_pos = [p for p in current_positions if float(p.get("contracts", p.get("amount", 0))) != 0]
        active_positions_count = len(active_pos)
        
        for p in active_pos:
            total_unrealized_pnl += float(p.get("unrealizedPnl", 0) or 0)
            total_margin_used += float(p.get("initialMargin", 0) or p.get("margin", 0) or 0)

        fut_used = float(usdt_info.get("used", 0.0) or 0.0)
        if fut_used == 0.0 and total_margin_used > 0.0:
            fut_used = total_margin_used

        fut_free = float(usdt_info.get("free", 0.0) or 0.0)
        if fut_free == 0.0 or fut_free >= fut_total:
            fut_free = max(0.0, fut_total - fut_used)
    except Exception:
        try:
            f_bal = futures_ex.fetch_balance()
            if "USDT" in f_bal:
                usdt_info = f_bal["USDT"]
                fut_total = float(usdt_info.get("total", 0.0) or 0.0)
                fut_free = float(usdt_info.get("free", 0.0) or usdt_info.get("available", 0.0) or 0.0)
                if fut_free == 0.0 and fut_total > 0.0:
                    fut_used = float(usdt_info.get("used", 0.0) or 0.0)
                    fut_free = max(0.0, fut_total - fut_used)
        except Exception:
            pass

if (not st.session_state.session_baseline_locked or st.session_state.session_start_balance == 0.0) and fut_total > 0:
    st.session_state.session_start_balance = fut_total
    st.session_state.session_baseline_locked = True

start_val = st.session_state.get("session_start_time", datetime.now())
try:
    session_elapsed = int(time.time() - start_val.timestamp())
except Exception:
    session_elapsed = 0

hours, rem = divmod(session_elapsed, 3600)
minutes, seconds = divmod(rem, 60)

session_pnl_pct_display = 0.0
if st.session_state.session_start_balance > 0 and fut_total > 0:
    session_pnl_pct_display = ((fut_total - st.session_state.session_start_balance) / st.session_state.session_start_balance) * 100

st.markdown(
    f"""
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
<div class="metric-delta">Interwał: {scan_interval}s | Wykres: {fut_tf}</div>
</div>
</div>
""",
    unsafe_allow_html=True,
)

st.markdown("---")
st.subheader("🥾 Panel Sterowania Botem Futures")

with st.container(border=True):
    col_btn1, col_btn2 = st.columns(2)
    
    with col_btn1:
        if st.button("🟢 URUCHOM SKANER I BOT HANDLOWY", use_container_width=True, key="btn_start_master"):
            st.session_state.scanner_active = True
            st.session_state.trend_bot_fut_active = True
            if fut_total > 0:
                st.session_state.session_baseline_locked = False
            st.rerun()
            
    with col_btn2:
        if st.button("🔴 ZATRZYMAJ BOT I SKANER", use_container_width=True, key="btn_stop_master"):
            st.session_state.scanner_active = False
            st.session_state.trend_bot_fut_active = False
            st.rerun()

    if st.session_state.get("scanner_active", False):
        st.success(f"🟢 STATUS: SYSTEM AKTYWNY I HANDLUJE (Timeframe: {fut_tf}, SL ROE: {custom_stop_loss_roe}%, TP ROE: {custom_take_profit_roe}%)")
    else:
        st.warning("🔴 STATUS: SYSTEM ZATRZYMANY (Kliknij zielony przycisk powyżej, aby uruchomić)")

# ==========================================
# POBRANIE PAR I SILNIK TRANSAKCYJNY
# ==========================================
selected_symbols = []
tickers_data = {}

try:
    if futures_ex and hasattr(futures_ex, 'load_markets'):
        futures_ex.load_markets()
        tickers_data = futures_ex.fetch_tickers()
        filtered = [s for s, t in tickers_data.items() if (s.endswith('/USDT:USDT') or s.endswith(':USDT')) and (t.get('quoteVolume', 0) or 0) >= 5_000_000]
        selected_symbols = sorted(filtered, key=lambda s: tickers_data.get(s, {}).get('quoteVolume', 0) or 0, reverse=True)[:max_fut_scan_pairs]
except Exception:
    pass

existing_positions_map = {}
existing_positions_amount = {}
real_active_positions_count = 0
try:
    if futures_ex and hasattr(futures_ex, 'fetch_positions'):
        for p in futures_ex.fetch_positions():
            contracts = float(p.get("contracts", p.get("amount", 0)))
            if contracts != 0:
                sym = p.get("symbol")
                side_str = str(p.get("side", "")).lower()
                existing_positions_map[sym] = side_str
                existing_positions_amount[sym] = abs(contracts)
                real_active_positions_count += 1

                # ==========================================
                # TWARDY STRAŻNIK ROE (STOP-LOSS / TAKE-PROFIT)
                # ==========================================
                if st.session_state.get("trend_bot_fut_active", False) and st.session_state.get("enable_roe_guard", True):
                    try:
                        entry_price = float(p.get("entryPrice", 0) or 0)
                        leverage_val = float(p.get("leverage", 1) or 1)
                        mark_price = float(p.get("markPrice", 0) or p.get("lastPrice", 0) or 0)
                        
                        if entry_price > 0 and mark_price > 0:
                            if side_str in ["buy", "long"]:
                                pnl_pct = ((mark_price - entry_price) / entry_price) * 100
                            else:
                                pnl_pct = ((entry_price - mark_price) / entry_price) * 100
                            
                            current_roe = pnl_pct * leverage_val

                            sl_limit = -float(st.session_state.get("custom_stop_loss_roe", 4.0))
                            tp_limit = float(st.session_state.get("custom_take_profit_roe", 15.0))

                            if current_roe <= sl_limit or current_roe >= tp_limit:
                                close_side = "sell" if side_str in ["buy", "long"] else "buy"
                                futures_ex.create_order(sym, "market", close_side, abs(contracts), params={'reduceOnly': True})
                                st.session_state.trade_history.insert(0, {
                                    "Czas": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                                    "Para": sym,
                                    "Typ": f"STRAŻNIK {'SL' if current_roe <= sl_limit else 'TP'}",
                                    "Cena": f"{mark_price:.4f}",
                                    "Ilość": f"{abs(contracts):.4f}",
                                    "Dźwignia": f"{int(leverage_val)}x"
                                })
                    except Exception as e_guard:
                        print(f"[BŁĄD STRAŻNIKA ROE]: {e_guard}")
except Exception:
    pass

scan_results = []
bot_active = st.session_state.get("trend_bot_fut_active", False)

if selected_symbols and futures_ex:
    for symbol in selected_symbols:
        signal_type = "NEUTRALNY"
        current_adx = 20.0
        current_rsi = 50.0
        market_price = 0.0
        trend_is_bullish = False
        trend_is_bearish = False
        sym_volume = 10_000_000

        try:
            t_info = tickers_data.get(symbol, {})
            sym_volume = float(t_info.get("quoteVolume", 10_000_000) or 10_000_000)

            ohlcv = futures_ex.fetch_ohlcv(symbol, timeframe=fut_tf, limit=100)
            if ohlcv and len(ohlcv) > ema_slow_val:
                df_sym = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
                df_sym = calculate_indicators(df_sym, ema_period=ema_fast_val)
                df_sym['EMA_fast'] = df_sym['close'].ewm(span=ema_fast_val, adjust=False).mean()
                df_sym['EMA_slow'] = df_sym['close'].ewm(span=ema_slow_val, adjust=False).mean()

                last_r = df_sym.iloc[-1]
                market_price = float(last_r['close'])

                if 'adx' in last_r and not pd.isna(last_r['adx']):
                    current_adx = float(last_r['adx'])
                
                if 'rsi' in last_r and not pd.isna(last_r['rsi']):
                    current_rsi = float(last_r['rsi'])

                trend_is_bullish = last_r['EMA_fast'] > last_r['EMA_slow']
                trend_is_bearish = last_r['EMA_fast'] < last_r['EMA_slow']

                # =========================================================
                # POPRAWIONY FILTR: Odrzucamy zakupy na górkach i dołkach
                # =========================================================
                min_adx_required = 30.0  
                
                if trend_is_bullish and current_adx >= min_adx_required and current_rsi < 65:
                    signal_type = "LONG"
                elif trend_is_bearish and current_adx >= min_adx_required and current_rsi > 35:
                    signal_type = "SHORT"
                else:
                    signal_type = "NEUTRALNY"
        except Exception:
            pass

        scan_results.append({
            "Para": symbol,
            "Sygnał": signal_type,
            "Wolumen": f"{sym_volume:,.0f}",
            "ADX": f"{current_adx:.1f}",
            "RSI": f"{current_rsi:.1f}",
            "Cena": f"{market_price:.4f}" if market_price > 0 else "Błąd",
            "Status": "Aktywny"
        })

        if bot_active:
            current_pos_side = existing_positions_map.get(symbol, None)
            position_contracts = existing_positions_amount.get(symbol, 0.0)

            # ==========================================
            # ZAMKNIĘCIE POZYCJI PRZY ZMIANIE TRENDU
            # ==========================================
            if current_pos_side and position_contracts > 0:
                is_long = current_pos_side in ["buy", "long"]
                is_short = current_pos_side in ["sell", "short"]

                if (is_long and trend_is_bearish) or (is_short and trend_is_bullish):
                    close_side = "sell" if is_long else "buy"
                    try:
                        futures_ex.create_order(symbol, "market", close_side, position_contracts, params={'reduceOnly': True})
                        existing_positions_map.pop(symbol, None)
                        existing_positions_amount.pop(symbol, None)
                        st.session_state.trade_history.insert(0, {
                            "Czas": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                            "Para": symbol,
                            "Typ": "ZMIANA TRENDU",
                            "Cena": f"{market_price:.4f}",
                            "Ilość": f"{position_contracts:.4f}",
                            "Dźwignia": "-"
                        })
                    except Exception:
                        pass

            elif not current_pos_side and signal_type != "NEUTRALNY":
                cooldown_key = f"trend_bot_fut_{symbol}"
                now_ts = time.time()

                if now_ts > st.session_state.signal_cooldown.get(cooldown_key, 0):
                    if real_active_positions_count < max_active_futures_positions:
                        trade_side = "buy" if signal_type == "LONG" else "sell"
                        try:
                            if market_price <= 0:
                                ticker = futures_ex.fetch_ticker(symbol)
                                market_price = float(ticker.get("last") or ticker.get("close", 0))
                            else:
                                ticker = tickers_data.get(symbol, {})

                            if market_price <= 0:
                                continue

                            exch_max_lev = get_exchange_max_leverage(futures_ex, symbol, default_max=50)
                            
                            if "Autonomiczny" in leverage_mode:
                                lev_to_set = get_smart_leverage(current_adx, exch_max_lev, max_allowed_leverage)
                            else:
                                lev_to_set = min(manual_leverage, exch_max_lev, max_allowed_leverage)

                            base_alloc = calculate_dynamic_allocation(
                                fut_free if fut_free > 0 else 1000.0,
                                max_active_futures_positions,
                                max_single_trade_usdt,
                                current_adx,
                                sym_volume
                            )
                            notional_usdt = base_alloc * lev_to_set
                            amount_contracts = notional_usdt / market_price

                            try:
                                amount_val = float(futures_ex.amount_to_precision(symbol, amount_contracts))
                                if amount_val <= 0:
                                    amount_val = amount_contracts
                            except Exception:
                                amount_val = amount_contracts

                            if (amount_val * market_price) < 5.0:
                                continue

                            futures_ex.set_leverage(lev_to_set, symbol)
                            futures_ex.create_order(symbol, "market", trade_side, amount_val, params={})

                            st.session_state.signal_cooldown[cooldown_key] = now_ts + 120
                            st.session_state.trade_history.insert(0, {
                                "Czas": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                                "Para": symbol,
                                "Typ": signal_type,
                                "Cena": f"{market_price:.4f}",
                                "Ilość": f"{amount_val:.4f}",
                                "Dźwignia": f"{lev_to_set}x"
                            })
                            existing_positions_map[symbol] = "buy" if signal_type == "LONG" else "sell"
                            existing_positions_amount[symbol] = amount_val
                            real_active_positions_count += 1
                        except Exception as e:
                            print(f"[BŁĄD OTWARCIA ZLECENIA]: {e}")
                            pass

st.markdown("---")
st.markdown("### 📊 Wyniki Skanera Rynkowego")
if scan_results:
    st.dataframe(pd.DataFrame(scan_results), use_container_width=True, hide_index=True)
else:
    st.info("Brak danych ze skanera.")

# ==========================================
# SEKCJA TABEL
# ==========================================
col_tab1, col_tab2 = st.columns(2)

with col_tab1:
    st.markdown("### 📈 Aktywne Pozycje Futures")
    raw_pos = []
    try:
        if futures_ex and hasattr(futures_ex, 'fetch_positions'):
            raw_pos = futures_ex.fetch_positions()
    except Exception:
        pass

    parsed_positions = []
    if raw_pos:
        for p in raw_pos:
            contracts = p.get("contracts", p.get("amount", 0))
            if contracts and float(contracts) != 0:
                parsed_positions.append({
                    "Para": p.get("symbol", "-"),
                    "Strona": str(p.get("side", "-")).upper(),
                    "Ilość": float(contracts),
                    "Cena Wejścia": float(p.get("entryPrice", 0)),
                    "Dźwignia": int(p.get("leverage", 1)),
                    "PnL (USDT)": float(p.get("unrealizedPnL", 0))
                })

    if parsed_positions:
        st.dataframe(pd.DataFrame(parsed_positions), use_container_width=True, hide_index=True)
    else:
        st.info("Brak otwartych pozycji futures.")

with col_tab2:
    st.markdown("### 📜 Historia Ostatnich Transakcji")
    if st.session_state.trade_history:
        st.dataframe(pd.DataFrame(st.session_state.trade_history[:15]), use_container_width=True, hide_index=True)
    else:
        st.info("Brak zarejestrowanych transakcji w tej sesji.")

if st.session_state.scanner_active:
    time.sleep(scan_interval)
    st.rerun()

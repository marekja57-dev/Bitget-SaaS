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
import gc

st.set_page_config(
    page_title="Multi-Exchange Futures SaaS",
    layout="wide",
)

DB_FILE = "users.db"
STRIPE_CONFIG_FILE = "stripe_config.json"

TRANSLATIONS = {
    "Polski": {
        "title": "BITGET FUTURES",
        "subtitle": "AUTONOMICZNY SYSTEM TRANSAKCYJNY",
        "login_tab": "🔑 Zaloguj się",
        "register_tab": "📝 Załóż konto",
        "email_label": "Adres e-mail",
        "pass_label": "Hasło",
        "login_btn": "ZALOGUJ SIĘ",
        "register_btn": "ZAREJESTRUJ SIĘ",
        "login_success": "Zalogowano pomyślnie!",
        "login_error": "Nieprawidłowy e-mail lub hasło.",
        "reg_success": "Konto założone! Przejdź do zakładki logowania.",
        "reg_error_exists": "Ten e-mail jest już zarejestrowany.",
        "reg_error_fill": "Wypełnij wszystkie pola.",
        "sidebar_role_admin": "Rola: Administrator",
        "sidebar_role_client": "Rola: Klient SaaS",
        "logout_btn": "🚪 WYLOGUJ SIĘ",
        "exchange_settings": "⚙️ Ustawienia Giełdy & API",
        "select_exchange": "Wybierz Giełdę:",
        "api_keys_header": "Klucze API",
        "save_keys_btn": "💾 ZAPISZ MOJE KLUCZE",
        "keys_saved": "Zapisano klucze dla",
        "keys_error": "Wypełnij wymagane pola kluczy.",
        "sub_zone": "🛡️ Strefa Subskrypcji",
        "sub_active": "Subskrypcja aktywna (Dostęp Pełny)",
        "sub_inactive": "⚠️ Brak aktywnej subskrypcji",
        "pay_btn": "OPŁAĆ DOSTĘP (49 PLN)",
        "capital_risk": "💰 Kapitał i Ryzyko",
        "max_single": "Maksymalnie USDT na 1 pozycję (Bazowo)",
        "max_pos": "Maks. aktywne pozycje Futures",
        "roe_guard": "🛑 Zarządzanie Ryzykiem ROE (SL / TP)",
        "enable_roe": "Włącz strażnika SL / TP ROE",
        "sl_roe": "Stop-Loss ROE (%)",
        "tp_roe": "Take-Profit ROE (%)",
        "leverage_mgmt": "⚡ Zarządzanie Dźwignią",
        "lev_mode": "Tryb Dźwigni",
        "max_allowed_lev": "Maksymalna dozwolona dźwignia",
        "manual_lev": "Stała dźwignia Futures",
        "bot_control": "🤖 Panel Sterowania Botami MTF (Skala kapitału zależna od interwału)",
        "max_pairs": "Liczba par Futures do skanowania",
        "kill_switch": "🔴 ZAMKNIJ WSZYSTKO (KILL SWITCH)",
        "wallet_futures": "🔵 Portfel Futures",
        "free_balance": "Wolne",
        "session_results": "📊 Wyniki Sesji (PnL %)",
        "pnl_usdt": "Pnl USDT",
        "slots_futures": "📈 Sloty Futures",
        "active_max": "Aktywne / Maksymalne",
        "session_time": "⏱️ Czas Sesji",
        "market_scanner_results": "📊 Wyniki Skanera Rynkowego (Aktywne Interwały)",
        "active_positions": "📈 Aktywne Pozycje Futures",
        "trade_history": "📜 Historia Ostatnich Transakcji",
        "no_positions": "Brak otwartych pozycji futures.",
        "no_history": "Brak zarejestrowanych transakcji w tej sesji.",
        "no_scanner": "Brak aktywnych botów MTF lub wyników skanowania. Uruchom przynajmniej jeden bot."
    },
    "English": {
        "title": "BITGET FUTURES",
        "subtitle": "AUTONOMOUS TRADING SYSTEM",
        "login_tab": "🔑 Login",
        "register_tab": "📝 Register",
        "email_label": "Email address",
        "pass_label": "Password",
        "login_btn": "SIGN IN",
        "register_btn": "SIGN UP",
        "login_success": "Logged in successfully!",
        "login_error": "Invalid email or password.",
        "reg_success": "Account created! Go to the login tab.",
        "reg_error_exists": "This email is already registered.",
        "reg_error_fill": "Please fill in all fields.",
        "sidebar_role_admin": "Role: Administrator",
        "sidebar_role_client": "Role: SaaS Client",
        "logout_btn": "🚪 LOG OUT",
        "exchange_settings": "⚙️ Exchange & API Settings",
        "select_exchange": "Select Exchange:",
        "api_keys_header": "API Keys",
        "save_keys_btn": "💾 SAVE MY KEYS",
        "keys_saved": "Keys saved for",
        "keys_error": "Please fill in required key fields.",
        "sub_zone": "🛡️ Subscription Zone",
        "sub_active": "Subscription active (Full Access)",
        "sub_inactive": "⚠️ No active subscription",
        "pay_btn": "PAY ACCESS (49 PLN)",
        "capital_risk": "💰 Capital & Risk",
        "max_single": "Max USDT per position (Base)",
        "max_pos": "Max active Futures positions",
        "roe_guard": "🛑 ROE Risk Management (SL / TP)",
        "enable_roe": "Enable SL / TP ROE guard",
        "sl_roe": "Stop-Loss ROE (%)",
        "tp_roe": "Take-Profit ROE (%)",
        "leverage_mgmt": "⚡ Leverage Management",
        "lev_mode": "Leverage Mode",
        "max_allowed_lev": "Maximum allowed leverage",
        "manual_lev": "Fixed Futures leverage",
        "bot_control": "🤖 Multi-Timeframe Bot Control Panel (Interval-Dependent Capital Scaling)",
        "max_pairs": "Number of Futures pairs to scan",
        "kill_switch": "🔴 CLOSE ALL (KILL SWITCH)",
        "wallet_futures": "🔵 Futures Wallet",
        "free_balance": "Free",
        "session_results": "📊 Session Results (PnL %)",
        "pnl_usdt": "PnL USDT",
        "slots_futures": "📈 Futures Slots",
        "active_max": "Active / Maximum",
        "session_time": "⏱️ Session Time",
        "market_scanner_results": "📊 Market Scanner Results (Active Timeframes)",
        "active_positions": "📈 Active Futures Positions",
        "trade_history": "📜 Recent Trade History",
        "no_positions": "No open futures positions.",
        "no_history": "No recorded trades in this session.",
        "no_scanner": "No active MTF bots or scanner results. Start at least one bot."
    }
}

def t(key):
    lang = st.session_state.get("lang", "Polski")
    return TRANSLATIONS.get(lang, TRANSLATIONS["Polski"]).get(key, key)

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

def calculate_indicators(df, ema_fast=9, ema_slow=21, adx_period=14):
    df["ema_fast"] = df["close"].ewm(span=ema_fast, adjust=False).mean()
    df["ema_slow"] = df["close"].ewm(span=ema_slow, adjust=False).mean()
    
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

def init_db():
    conn = sqlite3.connect(DB_FILE, timeout=30.0)
    cursor = conn.cursor()
    cursor.execute("PRAGMA journal_mode=WAL;")
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
if "session_start_time" not in st.session_state:
    st.session_state.session_start_time = datetime.now()
if "trade_history" not in st.session_state:
    st.session_state.trade_history = []
if "signal_cooldown" not in st.session_state:
    st.session_state.signal_cooldown = {}
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
if "active_mtf_bots" not in st.session_state:
    st.session_state.active_mtf_bots = {}

if st.query_params.get("success") == "true":
    if st.session_state.logged_in and st.session_state.user_id:
        st.session_state.stripe_paid = True
        try:
            conn = sqlite3.connect(DB_FILE, timeout=30.0)
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

if not st.session_state.logged_in:
    st.markdown(
        f"""<div class="hero-wrapper">
<div class="retro-ornate-frame">
<div class="retro-vintage-title">{t("title")}</div>
<div class="retro-subtitle">{t("subtitle")}</div>""",
        unsafe_allow_html=True,
    )
    tab_login, tab_register = st.tabs([t("login_tab"), t("register_tab")])
    with tab_login:
        st.markdown(f"<p style='color: #f3d57a; font-family: Cinzel, serif;'>{t('login_tab')}</p>", unsafe_allow_html=True)
        login_email = st.text_input(t("email_label"), key="log_email")
        login_pass = st.text_input(t("pass_label"), type="password", key="log_pass")
        if st.button(t("login_btn"), use_container_width=True):
            conn = sqlite3.connect(DB_FILE, timeout=30.0)
            cursor = conn.cursor()
            cursor.execute(
                "SELECT id, email, password, is_admin, stripe_paid, api_key, secret_key, passphrase FROM users WHERE LOWER(TRIM(email)) = ?",
                (login_email.strip().lower(),),
            )
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
                st.success(t("login_success"))
                st.rerun()
            else:
                st.error(t("login_error"))

    with tab_register:
        st.markdown(f"<p style='color: #f3d57a; font-family: Cinzel, serif;'>{t('register_tab')}</p>", unsafe_allow_html=True)
        reg_email = st.text_input(t("email_label"), key="reg_email")
        reg_pass = st.text_input(t("pass_label"), type="password", key="reg_pass")
        if st.button(t("register_btn"), use_container_width=True):
            if reg_email and reg_pass:
                try:
                    conn = sqlite3.connect(DB_FILE, timeout=30.0)
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
                    st.success(t("reg_success"))
                except sqlite3.IntegrityError:
                    st.error(t("reg_error_exists"))
            else:
                st.error(t("reg_error_fill"))
    st.markdown("</div></div>", unsafe_allow_html=True)
    st.stop()

st.session_state.lang = st.sidebar.selectbox(
    "🌐 Język / Language", ["Polski", "English"], index=0 if st.session_state.get("lang", "Polski") == "Polski" else 1, key="lang_selector"
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

def calculate_risk_based_allocation(free_balance, entry_price, stop_loss_price, risk_percentage=0.01, leverage=1, max_single_limit=50.0, tf_multiplier=1.0):
    if free_balance <= 0 or entry_price <= 0 or stop_loss_price <= 0:
        return min(max_single_limit * tf_multiplier, max(5.0, free_balance * 0.1 * tf_multiplier))
        
    scaled_single_limit = max_single_limit * tf_multiplier
    max_risk_amount = free_balance * risk_percentage * tf_multiplier
    risk_distance_pct = abs(entry_price - stop_loss_price) / entry_price
    if risk_distance_pct == 0:
        risk_distance_pct = 0.02
        
    position_notional_value = max_risk_amount / risk_distance_pct
    max_allowed_value = min(free_balance * leverage * 0.9, scaled_single_limit * leverage)
    final_notional = min(position_notional_value, max_allowed_value)
    
    return max(5.0 * tf_multiplier, final_notional)

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
    effective_max = min(preferred_max, exchange_limit)
    adx_clamped = min(max(adx_val, 10.0), 55.0)
    ratio = (adx_clamped - 10.0) / (55.0 - 10.0)
    floating_lev = 1.0 + ratio * (effective_max - 1.0)
    return int(round(floating_lev))

st.sidebar.markdown(f"### 👤 {st.session_state.get('user_email', '')}")
if is_user_admin():
    st.sidebar.markdown(f"**{t('sidebar_role_admin')}**")
else:
    st.sidebar.markdown(f"**{t('sidebar_role_client')}**")

if st.sidebar.button(t("logout_btn"), use_container_width=True, key="sidebar_wyloguj_btn"):
    st.session_state.logged_in = False
    st.session_state.user_email = ""
    st.session_state.is_admin = False
    st.session_state.stripe_paid = False
    st.session_state.api_key = ""
    st.session_state.secret_key = ""
    st.session_state.passphrase = ""
    st.rerun()

st.sidebar.header(t("exchange_settings"))
selected_exchange = st.sidebar.selectbox(
    t("select_exchange"),
    options=["Bitget", "Binance", "Bybit", "OKX"],
    index=0,
    key="sidebar_selected_exchange_sb"
)
st.session_state["selected_exchange"] = selected_exchange

st.sidebar.markdown("---")
st.sidebar.subheader(f"🔑 {t('api_keys_header')} ({selected_exchange})")

input_api = st.sidebar.text_input(f"API Key ({selected_exchange}):", value=st.session_state.get("api_key", ""), type="password", key=f"key_{selected_exchange}")
input_secret = st.sidebar.text_input(f"API Secret ({selected_exchange}):", value=st.session_state.get("secret_key", ""), type="password", key=f"secret_{selected_exchange}")

if selected_exchange in ["Bitget", "OKX"]:
    input_pass = st.sidebar.text_input(f"Passphrase ({selected_exchange}):", value=st.session_state.get("passphrase", ""), type="password", key=f"pass_{selected_exchange}")
else:
    input_pass = ""

if st.sidebar.button(t("save_keys_btn"), use_container_width=True, key="sidebar_zapisz_klucze_btn"):
    if input_api and input_secret:
        st.session_state.api_key = input_api
        st.session_state.secret_key = input_secret
        st.session_state.passphrase = input_pass
        try:
            conn = sqlite3.connect(DB_FILE, timeout=30.0)
            cursor = conn.cursor()
            cursor.execute(
                "UPDATE users SET api_key = ?, secret_key = ?, passphrase = ? WHERE id = ?",
                (input_api, input_secret, input_pass, st.session_state.get("user_id"))
            )
            conn.commit()
            conn.close()
        except Exception:
            pass
        st.success(f"{t('keys_saved')} {selected_exchange}!")
        st.rerun()
    else:
        st.error(t("keys_error"))

st.sidebar.markdown("---")
st.sidebar.markdown(f"### {t('sub_zone')}")
if is_user_admin() or is_user_paid():
    st.sidebar.success(t("sub_active"))
else:
    st.sidebar.warning(t("sub_inactive"))
    st.sidebar.link_button(t("pay_btn"), "https://buy.stripe.com/00w0kecLiSfbc8c13qA88")

st.sidebar.markdown("---")
st.sidebar.markdown(f"### {t('capital_risk')}")
max_single_trade_usdt = st.sidebar.number_input(t("max_single"), 5.0, 5000.0, 50.0, 5.0, key="sb_max_single_trade")
max_active_futures_positions = st.sidebar.slider(t("max_pos"), 1, 20, 5, key="sb_max_active_pos")

st.sidebar.markdown("---")
st.sidebar.markdown(f"### {t('roe_guard')}")
enable_roe_guard = st.sidebar.checkbox(t("enable_roe"), value=True, key="enable_roe_guard")

if enable_roe_guard:
    custom_stop_loss_roe = st.sidebar.slider(t("sl_roe"), 0.5, 50.0, 4.0, 0.5, key="custom_stop_loss_roe")
    custom_take_profit_roe = st.sidebar.slider(t("tp_roe"), 1.0, 100.0, 15.0, 0.5, key="custom_take_profit_roe")
else:
    custom_stop_loss_roe = 999.0
    custom_take_profit_roe = 999.0

st.sidebar.markdown("---")
st.sidebar.markdown(f"### {t('leverage_mgmt')}")
leverage_mode = st.sidebar.radio(t("lev_mode"), ["Autonomiczny (płynny w granicach limitu)", "Ręczny"], key="sb_leverage_mode")
max_allowed_leverage = st.sidebar.slider(t("max_allowed_lev"), 1, 50, 15, 1, key="sb_max_allowed_leverage")
manual_leverage = st.sidebar.slider(t("manual_lev"), 1, 50, 5, 1, key="sb_manual_leverage")

st.sidebar.markdown("---")
max_fut_scan_pairs = st.sidebar.slider(t("max_pairs"), 1, 100, 30, 1, key="sb_max_fut_pairs")

st.sidebar.markdown("---")
st.sidebar.subheader("⏱️ Odświeżanie strony / Auto-Refresh")
auto_refresh_seconds = st.sidebar.slider("Częstotliwość odświeżania (sekundy)", 5, 60, 15, 1, key="sb_auto_refresh")

st.sidebar.markdown("---")
emergency_kill = st.sidebar.button(t("kill_switch"), type="primary", use_container_width=True, key="sidebar_kill_switch_btn")

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

    st.session_state.active_mtf_bots = {}
    st.session_state.trade_history = []
    st.success("🔴 KILL SWITCH WYKONANY. Zamknięto wszystkie pozycje Futures i zatrzymano wszystkie boty.")
    time.sleep(2)
    st.rerun()

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
<div class="metric-label">{t("wallet_futures")}</div>
<div class="metric-value">{fut_total:.2f} USDT</div>
<div class="metric-delta">{t("free_balance")}: {fut_free:.2f} USDT</div>
</div>
<div class="metric-card">
<div class="metric-label">{t("session_results")}</div>
<div class="metric-value">{session_pnl_pct_display:+.2f}%</div>
<div class="metric-delta">{t("pnl_usdt")}: {total_unrealized_pnl:+.2f} USDT</div>
</div>
<div class="metric-card">
<div class="metric-label">{t("slots_futures")}</div>
<div class="metric-value">{active_positions_count} / {max_active_futures_positions}</div>
<div class="metric-delta">{t("active_max")}</div>
</div>
<div class="metric-card">
<div class="metric-label">{t("session_time")}</div>
<div class="metric-value">{hours:02d}:{minutes:02d}:{seconds:02d}</div>
<div class="metric-delta">Aktywne boty MTF: {len(st.session_state.active_mtf_bots)}</div>
</div>
</div>
""",
    unsafe_allow_html=True,
)

st.markdown("---")
st.subheader(f"🤖 {t('bot_control')}")
st.text("Każdy interwał posiada własne parametry EMA, ADX oraz MNOŻNIK KAPITAŁU (wyższe interwały handlują większą kwotą).")

available_timeframes = ["1m", "5m", "15m", "30m", "1h", "4h", "1d"]
default_multipliers = {"1m": 0.5, "5m": 0.8, "15m": 1.0, "30m": 1.5, "1h": 2.5, "4h": 4.0, "1d": 6.0}
cols_tf = st.columns(len(available_timeframes))

for idx, tf in enumerate(available_timeframes):
    with cols_tf[idx]:
        st.markdown(f"**📌 {tf}**")
        
        ema_f_val = st.number_input(f"EMA Szybka ({tf})", min_value=1, max_value=200, value=9, key=f"ema_f_{tf}")
        ema_s_val = st.number_input(f"EMA Wolna ({tf})", min_value=2, max_value=300, value=21, key=f"ema_s_{tf}")
        adx_val = st.slider(f"Min ADX ({tf})", 10.0, 50.0, 28.0, 1.0, key=f"adx_{tf}")
        tf_cap_mult = st.number_input(f"Mnożnik kwoty ({tf})", min_value=0.1, max_value=20.0, value=default_multipliers.get(tf, 1.0), step=0.5, key=f"cap_mult_{tf}")

        is_active = tf in st.session_state.active_mtf_bots
        
        if is_active:
            st.success("🟢 AKTYWNY")
            if st.button(f"Zatrzymaj {tf}", key=f"stop_tf_{tf}", use_container_width=True):
                del st.session_state.active_mtf_bots[tf]
                st.rerun()
        else:
            st.warning("🔴 WYŁĄCZONY")
            if st.button(f"Uruchom {tf}", key=f"start_tf_{tf}", use_container_width=True):
                if not st.session_state.api_key or not st.session_state.secret_key:
                    st.error("Najpierw zapisz klucze API w panelu bocznym!")
                else:
                    st.session_state.active_mtf_bots[tf] = {
                        "start_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                        "ema_fast": ema_f_val,
                        "ema_slow": ema_s_val,
                        "min_adx": adx_val,
                        "capital_multiplier": tf_cap_mult
                    }
                    st.success(f"Uruchomiono bota na {tf}!")
                    st.rerun()

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

                if len(st.session_state.active_mtf_bots) > 0 and st.session_state.get("enable_roe_guard", True):
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
                            sl_limit = -float(custom_stop_loss_roe)
                            tp_limit = float(custom_take_profit_roe)

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
except Exception as e_pos_fetch:
    print(f"[BŁĄD POBIERANIA POZYCJI]: {e_pos_fetch}")

all_scan_results = []
tickers_data = {}

try:
    if futures_ex and hasattr(futures_ex, 'load_markets'):
        futures_ex.load_markets()
        tickers_data = futures_ex.fetch_tickers()
except Exception as e_tickers:
    print(f"[BŁĄD TICKERÓW]: {e_tickers}")

active_tf_list = list(st.session_state.active_mtf_bots.keys())

if active_tf_list and tickers_data and futures_ex:
    valid_syms = [s for s, t in tickers_data.items() if (s.endswith('/USDT:USDT') or s.endswith(':USDT')) and (t.get('quoteVolume', 0) or 0) >= 5_000_000]
    selected_symbols = sorted(valid_syms, key=lambda s: tickers_data.get(s, {}).get('quoteVolume', 0) or 0, reverse=True)[:max_fut_scan_pairs]

    for tf in active_tf_list:
        bot_conf = st.session_state.active_mtf_bots[tf]
        e_fast = bot_conf["ema_fast"]
        e_slow = bot_conf["ema_slow"]
        m_adx = bot_conf["min_adx"]
        tf_mult = bot_conf.get("capital_multiplier", 1.0)

        for symbol in selected_symbols:
            signal_type = "NEUTRALNY"
            current_adx = 20.0
            current_rsi = 50.0
            market_price = 0.0
            sym_volume = 10_000_000

            try:
                t_info = tickers_data.get(symbol, {})
                sym_volume = float(t_info.get("quoteVolume", 10_000_000) or 10_000_000)

                limit_val = min(150, max(60, e_slow + 20)) if tf == '1d' else max(100, e_slow + 30)
                ohlcv = futures_ex.fetch_ohlcv(symbol, timeframe=tf, limit=limit_val)
                
                if ohlcv and len(ohlcv) > max(e_fast, 5):
                    df_sym = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
                    df_sym = calculate_indicators(df_sym, ema_fast=e_fast, ema_slow=e_slow, adx_period=14)

                    last_r = df_sym.iloc[-1]
                    prev_r = df_sym.iloc[-2]
                    market_price = float(last_r['close'])

                    if 'adx' in last_r and not pd.isna(last_r['adx']):
                        current_adx = float(last_r['adx'])
                    if 'rsi' in last_r and not pd.isna(last_r['rsi']):
                        current_rsi = float(last_r['rsi'])

                    cross_above_ema = (prev_r['close'] <= prev_r['ema_fast']) and (last_r['close'] > last_r['ema_fast'])
                    trend_is_bullish = (
                        cross_above_ema
                        and last_r['ema_fast'] > last_r['ema_slow']
                        and current_rsi < 65
                    )

                    cross_below_ema = (prev_r['close'] >= prev_r['ema_fast']) and (last_r['close'] < last_r['ema_fast'])
                    trend_is_bearish = (
                        cross_below_ema
                        and last_r['ema_fast'] < last_r['ema_slow']
                        and current_rsi > 35
                    )

                    if trend_is_bullish and current_adx >= m_adx:
                        signal_type = "LONG"
                    elif trend_is_bearish and current_adx >= m_adx:
                        signal_type = "SHORT"

                    all_scan_results.append({
                        "Interwał": tf,
                        "Para": symbol,
                        "Cena": market_price,
                        "ADX": round(current_adx, 2),
                        "RSI": round(current_rsi, 2),
                        "Sygnał": signal_type,
                        "Wolumen": sym_volume
                    })

                    if symbol not in existing_positions_map and real_active_positions_count < max_active_futures_positions:
                        if signal_type in ["LONG", "SHORT"]:
                            cooldown_key = f"{tf}_{symbol}_{signal_type}"
                            last_signal_time = st.session_state.signal_cooldown.get(cooldown_key, 0)
                            if time.time() - last_signal_time > 300:
                                try:
                                    exchange_limit = get_exchange_max_leverage(futures_ex, symbol, default_max=15)
                                    if leverage_mode == "Ręczny":
                                        chosen_lev = min(manual_leverage, exchange_limit)
                                    else:
                                        chosen_lev = get_smart_leverage(current_adx, exchange_limit, preferred_max=max_allowed_leverage)

                                    try:
                                        futures_ex.set_leverage(chosen_lev, symbol)
                                    except Exception:
                                        pass

                                    notional_allocation = calculate_risk_based_allocation(
                                        free_balance=fut_free,
                                        entry_price=market_price,
                                        stop_loss_price=market_price * 0.98 if signal_type == "LONG" else market_price * 1.02,
                                        risk_percentage=0.01,
                                        leverage=chosen_lev,
                                        max_single_limit=max_single_trade_usdt,
                                        tf_multiplier=tf_mult
                                    )

                                    amount_coins = notional_allocation / market_price
                                    amount_prec = float(futures_ex.amount_to_precision(symbol, amount_coins))

                                    if amount_prec > 0:
                                        order_side = "buy" if signal_type == "LONG" else "sell"
                                        futures_ex.create_order(symbol, "market", order_side, amount_prec)
                                        st.session_state.signal_cooldown[cooldown_key] = time.time()
                                        st.session_state.trade_history.insert(0, {
                                            "Czas": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                                            "Para": symbol,
                                            "Typ": f"WEJŚCIE {signal_type} ({tf}, {tf_mult}x)",
                                            "Cena": f"{market_price:.4f}",
                                            "Ilość": f"{amount_prec:.4f}",
                                            "Dźwignia": f"{chosen_lev}x"
                                        })
                                except Exception as e_order:
                                    print(f"[BŁĄD ZLECENIA]: {e_order}")
            except Exception as e_sym:
                all_scan_results.append({
                    "Interwał": tf,
                    "Para": symbol,
                    "Cena": 0.0,
                    "ADX": 0.0,
                    "RSI": 0.0,
                    "Sygnał": "NEUTRALNY",
                    "Wolumen": 0.0
                })

st.markdown("---")
st.subheader(t('market_scanner_results'))

if all_scan_results:
    df_scan = pd.DataFrame(all_scan_results)
    st.dataframe(df_scan, use_container_width=True)
else:
    st.info(t("no_scanner"))

st.markdown("---")
st.subheader(t("active_positions"))

if active_pos:
    df_pos = pd.DataFrame(active_pos)
    st.dataframe(df_pos, use_container_width=True)
else:
    st.info(t("no_positions"))

st.markdown("---")
st.subheader(t("trade_history"))

if st.session_state.trade_history:
    df_hist = pd.DataFrame(st.session_state.trade_history)
    st.dataframe(df_hist, use_container_width=True)
else:
    st.info(t("no_history"))

import gc
gc.collect()

if auto_refresh_seconds > 0:
    refresh_interval_ms = auto_refresh_seconds * 1000
    st.markdown(
        f"""
        <script>
            setTimeout(function() {{
                window.location.reload();
            }}, {refresh_interval_ms});
        </script>
        """,
        unsafe_allow_html=True
    )

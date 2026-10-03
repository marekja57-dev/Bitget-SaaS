from datetime import datetime
import hashlib
import hmac
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

# Przycisk testowej aktywacji dostepu - domyslnie WYLACZONY (zabezpieczenie przed darmowym dostepem).
ALLOW_TEST_ACTIVATION = os.getenv("ALLOW_TEST_ACTIVATION", "0") == "1"

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
        "sub_zone": "🛡 Strefa Subskrypcji",
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
        "bot_control": "🤖 Panel Sterowania Botami MTF (Automatyczny / Ręczny Dobór Parametrów)",
        "max_pairs": "Liczba par Futures do skanowania",
        "kill_switch": "🔴 ZAMKNIJ WSZYSTKO (KILL SWITCH)",
        "wallet_futures": "🔵 Portfel Futures",
        "free_balance": "Wolne",
        "session_results": "📊 Wyniki Sesji (PnL %)",
        "pnl_usdt": "Pnl USDT",
        "slots_futures": "📈 Sloty Futures",
        "active_max": "Aktywne / Maksymalne",
        "session_time": "⏱ Czas Sesji",
        "market_scanner_results": "📊 Wyniki Skanera Rynkowego (Aktywne Interwały)",
        "active_positions": "📈 Aktywne Pozycje Futures",
        "trade_history": "📜 Historia Ostatnich Transakcji",
        "admin_panel": "👑 Panel Administratora (Użytkownicy)",
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
        "bot_control": "🤖 Multi-Timeframe Bot Control Panel (Auto/Manual Parameter Tuning)",
        "max_pairs": "Number of Futures pairs to scan",
        "kill_switch": "🔴 CLOSE ALL (KILL SWITCH)",
        "wallet_futures": "🔵 Futures Wallet",
        "free_balance": "Free",
        "session_results": "📊 Session Results (PnL %)",
        "pnl_usdt": "PnL USDT",
        "slots_futures": "📈 Futures Slots",
        "active_max": "Active / Maximum",
        "session_time": "⏱ Session Time",
        "market_scanner_results": "📊 Market Scanner Results (Active Timeframes)",
        "active_positions": "📈 Active Futures Positions",
        "trade_history": "📜 Recent Trade History",
        "admin_panel": "👑 Admin Panel (Users)",
        "no_positions": "No open futures positions.",
        "no_history": "No recorded trades in this session.",
        "no_scanner": "No active MTF bots or scanner results. Start at least one bot."
    }
}

def t(key):
    lang = st.session_state.get("lang", "Polski")
    return TRANSLATIONS.get(lang, TRANSLATIONS["Polski"]).get(key, key)

ADMIN_EMAILS = ["marekja57@wp.pl", "admin@bot-bitget.pl"]

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

def hash_password(password, salt=None):
    if salt is None:
        salt = os.urandom(16).hex()
    digest = hashlib.sha256((salt + password).encode("utf-8")).hexdigest()
    return f"sha256${salt}${digest}"

def verify_password(password, stored):
    if not stored:
        return False
    if str(stored).startswith("sha256$"):
        try:
            _, salt, _ = str(stored).split("$", 2)
        except ValueError:
            return False
        return hmac.compare_digest(hash_password(password, salt), str(stored))
    return hmac.compare_digest(str(stored), str(password))

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
    df["plus_dm"] = np.where((df["up_move"] > df["down_move"]) & (df["up_move"] > 0), df["up_move"], 0)
    df["minus_dm"] = np.where((df["down_move"] > df["up_move"]) & (df["down_move"] > 0), df["down_move"], 0)
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

def get_optimal_dynamic_parameters(df_recent, tf):
    try:
        closes = df_recent['close'].values
        returns = np.diff(closes) / closes[:-1]
        volatility = np.std(returns) * np.sqrt(len(returns))
        if tf in ["1m", "5m"]:
            if volatility > 0.02:
                return {"ema_fast": 5, "ema_slow": 13, "min_adx": 22.0, "max_rsi": 72.0, "min_rsi": 28.0, "capital_multiplier": 0.6}
            else:
                return {"ema_fast": 9, "ema_slow": 21, "min_adx": 26.0, "max_rsi": 75.0, "min_rsi": 25.0, "capital_multiplier": 0.8}
        elif tf in ["15m", "30m"]:
            if volatility > 0.03:
                return {"ema_fast": 7, "ema_slow": 18, "min_adx": 24.0, "max_rsi": 70.0, "min_rsi": 30.0, "capital_multiplier": 1.0}
            else:
                return {"ema_fast": 10, "ema_slow": 25, "min_adx": 25.0, "max_rsi": 78.0, "min_rsi": 22.0, "capital_multiplier": 1.2}
        else:
            return {"ema_fast": 12, "ema_slow": 26, "min_adx": 20.0, "max_rsi": 80.0, "min_rsi": 20.0, "capital_multiplier": 2.5}
    except Exception:
        return {"ema_fast": 9, "ema_slow": 21, "min_adx": 25.0, "max_rsi": 75.0, "min_rsi": 25.0, "capital_multiplier": 1.0}

def blend_params(base, opt, base_weight=0.5):
    """Laczy wartosci bazowe z suwakow z wynikiem automatycznego optymalizatora.
    base_weight=1.0 -> tylko suwaki (jak tryb Reczny), 0.0 -> tylko optymalizator."""
    w = max(0.0, min(1.0, float(base_weight)))
    return {
        "ema_fast": max(1, int(round(base["ema_fast"] * w + opt["ema_fast"] * (1 - w)))),
        "ema_slow": max(2, int(round(base["ema_slow"] * w + opt["ema_slow"] * (1 - w)))),
        "min_adx": round(base["min_adx"] * w + opt["min_adx"] * (1 - w), 2),
        "max_rsi": round(base["max_rsi"] * w + opt["max_rsi"] * (1 - w), 2),
        "min_rsi": round(base["min_rsi"] * w + opt["min_rsi"] * (1 - w), 2),
        "capital_multiplier": round(base["capital_multiplier"] * w + opt["capital_multiplier"] * (1 - w), 2),
    }

AVAILABLE_TIMEFRAMES = ["1m", "5m", "15m", "30m", "1h", "4h", "1d"]
DEFAULT_TF_MULTIPLIERS = {"1m": 0.5, "5m": 0.8, "15m": 1.0, "30m": 1.5, "1h": 2.5, "4h": 4.0, "1d": 6.0}

def build_bot_config_from_state(state, tf):
    """Buduje konfiguracje bota z AKTUALNYCH wartosci widgetow (session_state).
    Zwraca None, jesli widgety dla tego interwalu nie istnieja jeszcze w sesji."""
    k_f = f"ema_f_{tf}"
    k_s = f"ema_s_{tf}"
    k_adx = f"adx_{tf}"
    k_max_rsi = f"max_rsi_{tf}"
    k_min_rsi = f"min_rsi_{tf}"
    k_cap = f"cap_mult_{tf}"
    k_mode = f"radio_mode_{tf}"
    if k_f not in state or k_s not in state:
        return None
    try:
        ema_f = int(state[k_f])
        ema_s = int(state[k_s])
        adx = float(state[k_adx])
        max_rsi = float(state[k_max_rsi])
        min_rsi = float(state[k_min_rsi])
        cap = float(state[k_cap])
    except (TypeError, ValueError, KeyError):
        return None
    if ema_f >= ema_s:
        ema_f, ema_s = ema_s, ema_f
    return {
        "mode": str(state.get(k_mode, "Automatyczny")),
        "ema_fast": max(1, ema_f),
        "ema_slow": max(2, ema_s),
        "min_adx": min(50.0, max(10.0, adx)),
        "max_rsi": min(95.0, max(50.0, max_rsi)),
        "min_rsi": min(50.0, max(5.0, min_rsi)),
        "capital_multiplier": min(20.0, max(0.1, cap)),
    }

def sync_running_bots_from_widgets(state, timeframes=None):
    """Wpycha biezace wartosci suwakow do WSZYSTKICH uruchomionych botow.
    Wywolywane PRZED petla skanujaca, dlatego zmiana suwaka dziala od razu,
    w tym samym przebiegu skryptu, bez czekania na kolejne odswiezenie."""
    bots = state.get("active_mtf_bots")
    if not isinstance(bots, dict) or not bots:
        return 0
    updated = 0
    for tf in list(bots.keys()):
        cfg = build_bot_config_from_state(state, tf)
        if not cfg:
            continue
        bots[tf].update(cfg)
        updated += 1
    return updated

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
    conn.commit()
    conn.close()

init_db()

def _get_secret(name, default=""):
    """Sekrety pobierane ze zmiennych srodowiskowych lub st.secrets - bez kluczy w kodzie."""
    val = os.getenv(name)
    if val: 
        return val
    try:
        return st.secrets[name]
    except Exception:
        return default

stripe_pk_val = _get_secret("pk_live_51UCp3eKe18kT9JGHZvz9RGblVSUvyuaKfQ49DDvXymKf8IDjIgHyO4wfpaDnqSWQKvcGbXcQ2yhPJx2id6O8wLa800mN6pFhEA","")
stripe_sk_val = _get_secret("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", "")
stripe_price_id_val = _get_secret("price_1UDAQAKe18kT9JGHUGVXkqi8", "")

if stripe_sk_val:
    stripe.api_key = stripe_sk_val

def create_stripe_checkout_session(user_email, price_id):
    fallback_url = "https://buy.stripe.com/8x2dRa4CbdaXfSAf6V3oA03"
    try:
        if not stripe.api_key or not price_id:
            return fallback_url
        session = stripe.checkout.Session.create(
            payment_method_types=['card'],
            line_items=[{
                'price': price_id,
                'quantity': 1,
            }],
            mode='payment',
            success_url='https://bot-bitget.pl/?success=true',
            cancel_url='https://bot-bitget.pl/?success=false',
            customer_email=user_email,
        )
        return session.url if session and session.url else fallback_url
    except Exception:
        return fallback_url

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
if "symbol_cooldown" not in st.session_state:
    st.session_state.symbol_cooldown = {}
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
            if user_row and verify_password(login_pass, user_row[2]):
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
                if not str(user_row[2]).startswith("sha256$"):
                    try:
                        conn_up = sqlite3.connect(DB_FILE, timeout=30.0)
                        cur_up = conn_up.cursor()
                        cur_up.execute("UPDATE users SET password = ? WHERE id = ?", (hash_password(login_pass), user_row[0]))
                        conn_up.commit()
                        conn_up.close()
                    except Exception:
                        pass
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
                        (reg_email.strip(), hash_password(reg_pass), is_adm, is_paid),
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

def get_exchange(api_k="", sec_k="", pass_k="", ex_name="Bitget"):
    if not api_k:
        return None
    try:
        ex_id = ex_name.lower()
        exchange_class = getattr(ccxt, ex_id)
        config = {
            "apiKey": api_k,
            "secret": sec_k,
            "enableRateLimit": True,
            "options": {
                "defaultType": "swap",
                "createOrder": {"createMarketBuyOrderRequiresPrice": False},
            },
        }
        if ex_id in ["bitget", "okx"] and pass_k:
            config["password"] = pass_k
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
    checkout_url = create_stripe_checkout_session(st.session_state.get("user_email", ""), stripe_price_id_val)
    st.sidebar.link_button(t("pay_btn"), checkout_url, use_container_width=True)
    if ALLOW_TEST_ACTIVATION:
        if st.sidebar.button("⚡ [TEST] Aktywuj dostęp natychmiast", use_container_width=True):
            st.session_state.stripe_paid = True
            try:
                conn = sqlite3.connect(DB_FILE, timeout=30.0)
                cursor = conn.cursor()
                cursor.execute("UPDATE users SET stripe_paid = 1 WHERE id = ?", (st.session_state.get("user_id"),))
                conn.commit()
                conn.close()
            except Exception:
                pass
            st.success("Subskrypcja aktywowana testowo!")
            st.rerun()

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
    cooldown_after_sl_tp_minutes = st.sidebar.slider("Czas oddechu po SL/TP (minuty)", 1, 120, 15, 1, key="sb_cooldown_sl_tp")
else:
    custom_stop_loss_roe = 999.0
    custom_take_profit_roe = 999.0
    cooldown_after_sl_tp_minutes = 15

st.sidebar.markdown("---")
st.sidebar.markdown(f"### {t('leverage_mgmt')}")
leverage_mode = st.sidebar.radio(t("lev_mode"), ["Autonomiczny (płynny w granicach limitu)", "Ręczny"], key="sb_leverage_mode")
max_allowed_leverage = st.sidebar.slider(t("max_allowed_lev"), 1, 50, 15, 1, key="sb_max_allowed_leverage")
manual_leverage = st.sidebar.slider(t("manual_lev"), 1, 50, 5, 1, key="sb_manual_leverage")

st.sidebar.markdown("---")
max_fut_scan_pairs = st.sidebar.slider(t("max_pairs"), 1, 100, 30, 1, key="sb_max_fut_pairs")

st.sidebar.markdown("---")
auto_base_influence = st.sidebar.slider(
    "🎚️ Wpływ suwaków bazowych w trybie Auto (%)",
    0, 100, 50, 5,
    key="sb_auto_base_influence",
    help="0% = tylko automatyczny optymalizator, 100% = dokładnie wartości z suwaków (jak tryb Ręczny).",
)

st.sidebar.markdown("---")
st.sidebar.subheader("⏱ Odświeżanie strony / Auto-Refresh")
auto_refresh_seconds = st.sidebar.slider("Częstotliwość odświeżania widoku (sekundy)", 5, 60, 15, 1, key="sb_auto_refresh")

st.sidebar.markdown("---")
emergency_kill = st.sidebar.button(t("kill_switch"), type="primary", use_container_width=True, key="sidebar_kill_switch_btn")

futures_ex = get_exchange(st.session_state.get("api_key"), st.session_state.get("secret_key"), st.session_state.get("passphrase"), st.session_state.get("selected_exchange", "Bitget"))

# --- NAJWAZNIEJSZA POPRAWKA ---
# Streamlit przed uruchomieniem skryptu zapisuje nowa wartosc suwaka do session_state,
# wiec odczyt kluczy widgetow TUTAJ (przed petla skanujaca) oznacza, ze zmiana
# EMA / ADX / RSI wplywa na decyzje bota w tym samym przebiegu. Wczesniej parametry
# byly kopiowane tylko raz, przy kliknieciu "Uruchom", i dlatego suwaki byly "na sztywno".
synced_bots_count = sync_running_bots_from_widgets(st.session_state, AVAILABLE_TIMEFRAMES)

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
    st.session_state.symbol_cooldown = {}
    st.success("🔴 KILL SWITCH WYKONANY. Zamknięto wszystkie pozycje Futures i zatrzymano wszystkie boty.")
    time.sleep(2)
    st.rerun()
scan_results = []
active_pos = []
fut_free, fut_total = 0.0, 0.0
total_unrealized_pnl = 0.0
total_margin_used = 0.0
active_positions_count = 0

if futures_ex:
    try:
        futures_ex.load_markets()
        tickers = futures_ex.fetch_tickers()
    except Exception:
        tickers = {}

    valid_syms = []
    if tickers:
        valid_syms = [s for s, t in tickers.items() if (s.endswith('/USDT:USDT') or s.endswith(':USDT')) and (t.get('quoteVolume', 0) or 0) >= 1_000_000]
    if not valid_syms and futures_ex.markets:
        valid_syms = [s for s, m in futures_ex.markets.items() if m.get('linear') and m.get('quote') == 'USDT' and m.get('active')]

    selected_symbols = sorted(valid_syms, key=lambda s: (tickers.get(s, {}) or {}).get('quoteVolume', 0) or 0, reverse=True)[:max_fut_scan_pairs]

    try:
        current_positions = futures_ex.fetch_positions()
    except Exception:
        current_positions = []

    existing_pos_map = {}
    for p in current_positions:
        contracts = float(p.get("contracts", p.get("amount", 0)))
        if contracts != 0:
            sym = p.get("symbol")
            side_str = str(p.get("side", "")).lower()
            existing_pos_map[sym] = side_str
            active_positions_count += 1
            total_unrealized_pnl += float(p.get("unrealizedPnl", 0) or 0)
            total_margin_used += float(p.get("initialMargin", 0) or p.get("margin", 0) or 0)
            active_pos.append(p)
            if enable_roe_guard:
                try:
                    ep = float(p.get("entryPrice", 0) or 0)
                    lev = float(p.get("leverage", 1) or 1)
                    mp = float(p.get("markPrice", 0) or p.get("lastPrice", 0) or 0)
                    if ep > 0 and mp > 0:
                        pnl_pct = ((mp - ep) / ep) * 100 if side_str in ["buy", "long"] else ((ep - mp) / ep) * 100
                        roe = pnl_pct * lev
                        if roe <= -float(custom_stop_loss_roe) or roe >= float(custom_take_profit_roe):
                            c_side = "sell" if side_str in ["buy", "long"] else "buy"
                            futures_ex.create_order(sym, "market", c_side, abs(contracts), params={'reduceOnly': True})
                            st.session_state.symbol_cooldown[sym] = time.time() + (cooldown_after_sl_tp_minutes * 60)
                            st.session_state.trade_history.insert(0, {
                                "Czas": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                                "Para": sym,
                                "Typ": f"STRAŻNIK {'SL' if roe < 0 else 'TP'}",
                                "Cena": f"{mp:.4f}",
                                "Ilość": f"{abs(contracts):.4f}",
                                "Dźwignia": f"{int(lev)}x"
                            })
                except Exception:
                    pass

    try:
        f_bal = futures_ex.fetch_balance({"type": "swap"})
        usdt_info = f_bal.get("USDT", {})
        fut_total = float(usdt_info.get("total", 0.0) or 0.0)
        if fut_total == 0.0 and "info" in f_bal:
            for asset in f_bal["info"].get("data", []):
                if asset.get("marginCoin") == "USDT" or asset.get("coin") == "USDT":
                    fut_total = float(asset.get("equity", asset.get("total", 0.0)) or 0.0)
                    break
        fut_used = float(usdt_info.get("used", 0.0) or 0.0)
        if fut_used == 0.0 and total_margin_used > 0.0:
            fut_used = total_margin_used
        fut_free = float(usdt_info.get("free", 0.0) or 0.0)
        if fut_free == 0.0 or fut_free >= fut_total:
            fut_free = max(0.0, fut_total - fut_used)
    except Exception:
        pass

    bots = st.session_state.get("active_mtf_bots", {})
    if bots:
        for tf, bot_conf in bots.items():
            for symbol in selected_symbols:
                # WAZNE: parametry sa resetowane dla KAZDEJ pary osobno, zeby wartosci
                # z trybu Auto nie "przeciekaly" z poprzedniego symbolu.
                e_fast = int(bot_conf.get("ema_fast", 9))
                e_slow = int(bot_conf.get("ema_slow", 21))
                m_adx = float(bot_conf.get("min_adx", 28.0))
                max_rsi_limit = float(bot_conf.get("max_rsi", 75.0))
                min_rsi_limit = float(bot_conf.get("min_rsi", 25.0))
                tf_mult = float(bot_conf.get("capital_multiplier", 1.0))

                try:
                    cooldown_until = st.session_state.symbol_cooldown.get(symbol, 0)
                    if time.time() < cooldown_until:
                        continue

                    t_info = tickers.get(symbol, {}) or {}
                    sym_volume = float(t_info.get("quoteVolume", 10_000_000) or 10_000_000)
                    limit_val = min(150, max(60, e_slow + 20)) if tf == '1d' else max(100, e_slow + 30)
                    ohlcv = futures_ex.fetch_ohlcv(symbol, timeframe=tf, limit=limit_val)

                    if ohlcv and len(ohlcv) > max(e_fast, 5):
                        df_sym = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
                        if bot_conf.get("mode") == "Automatyczny":
                            opt = get_optimal_dynamic_parameters(df_sym, tf)
                            blended = blend_params(
                                {
                                    "ema_fast": e_fast,
                                    "ema_slow": e_slow,
                                    "min_adx": m_adx,
                                    "max_rsi": max_rsi_limit,
                                    "min_rsi": min_rsi_limit,
                                    "capital_multiplier": tf_mult,
                                },
                                opt,
                                base_weight=st.session_state.get("sb_auto_base_influence", 50) / 100.0,
                            )
                            e_fast = blended["ema_fast"]
                            e_slow = blended["ema_slow"]
                            m_adx = blended["min_adx"]
                            max_rsi_limit = blended["max_rsi"]
                            min_rsi_limit = blended["min_rsi"]
                            tf_mult = blended["capital_multiplier"]

                        if e_fast >= e_slow:
                            e_fast, e_slow = e_slow, e_fast

                        df_sym = calculate_indicators(df_sym, ema_fast=e_fast, ema_slow=e_slow, adx_period=14)
                        last_r = df_sym.iloc[-1]
                        prev_r = df_sym.iloc[-2]
                        market_price = float(last_r['close'])
                        current_adx = float(last_r['adx']) if 'adx' in last_r and not pd.isna(last_r['adx']) else 20.0
                        current_rsi = float(last_r['rsi']) if 'rsi' in last_r and not pd.isna(last_r['rsi']) else 50.0

                        cross_above = (prev_r['close'] <= prev_r['ema_fast']) and (last_r['close'] > last_r['ema_fast'])
                        trend_bull = cross_above and (last_r['ema_fast'] > last_r['ema_slow']) and (current_rsi < max_rsi_limit)
                        cross_below = (prev_r['close'] >= prev_r['ema_fast']) and (last_r['close'] < last_r['ema_fast'])
                        trend_bear = cross_below and (last_r['ema_fast'] < last_r['ema_slow']) and (current_rsi > min_rsi_limit)

                        signal_type = "NEUTRALNY"
                        if trend_bull and current_adx >= m_adx:
                            signal_type = "LONG"
                        elif trend_bear and current_adx >= m_adx:
                            signal_type = "SHORT"

                        scan_results.append({
                            "Interwał": tf,
                            "Para": symbol,
                            "Cena": market_price,
                            "ADX": round(current_adx, 2),
                            "RSI": round(current_rsi, 2),
                            "Sygnał": signal_type,
                            "Wolumen": sym_volume
                        })

                        current_pos_side = existing_pos_map.get(symbol)
                        if current_pos_side:
                            if (current_pos_side in ["buy", "long"] and signal_type == "SHORT") or \
                               (current_pos_side in ["sell", "short"] and signal_type == "LONG"):
                                try:
                                    matching_p = next((p for p in active_pos if p.get("symbol") == symbol), None)
                                    if matching_p:
                                        contracts_to_close = abs(float(matching_p.get("contracts", matching_p.get("amount", 0))))
                                        close_side = "sell" if current_pos_side in ["buy", "long"] else "buy"
                                        contracts_prec_close = float(futures_ex.amount_to_precision(symbol, contracts_to_close))
                                        if contracts_prec_close > 0:
                                            futures_ex.create_order(symbol, "market", close_side, contracts_prec_close, params={"reduceOnly": True})
                                            st.session_state.trade_history.insert(0, {
                                                "Czas": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                                                "Para": symbol,
                                                "Typ": f"ZMIANA TRENDU -> ZAMKNIĘCIE ({tf})",
                                                "Cena": f"{market_price:.4f}",
                                                "Ilość": f"{contracts_prec_close:.4f}",
                                                "Dźwignia": f"{int(matching_p.get('leverage', 1))}x"
                                            })
                                            existing_pos_map.pop(symbol, None)
                                            active_positions_count = max(0, active_positions_count - 1)
                                except Exception:
                                    pass

                        if symbol not in existing_pos_map and active_positions_count < max_active_futures_positions:
                            if signal_type in ["LONG", "SHORT"]:
                                cooldown_key = f"{tf}_{symbol}_{signal_type}"
                                last_sig = st.session_state.signal_cooldown.get(cooldown_key, 0)
                                if time.time() - last_sig > 300:
                                    try:
                                        ex_lim = get_exchange_max_leverage(futures_ex, symbol, default_max=15)
                                        chosen_lev = min(manual_leverage, ex_lim) if leverage_mode == "Ręczny" else get_smart_leverage(current_adx, ex_lim, preferred_max=max_allowed_leverage)
                                        try:
                                            futures_ex.set_leverage(chosen_lev, symbol)
                                        except Exception:
                                            pass

                                        notional = calculate_risk_based_allocation(
                                            free_balance=fut_free,
                                            entry_price=market_price,
                                            stop_loss_price=market_price * 0.98 if signal_type == "LONG" else market_price * 1.02,
                                            risk_percentage=0.01,
                                            leverage=chosen_lev,
                                            max_single_limit=max_single_trade_usdt,
                                            tf_multiplier=tf_mult
                                        )
                                        amt_coins = notional / market_price
                                        amt_prec = float(futures_ex.amount_to_precision(symbol, amt_coins))
                                        if amt_prec > 0:
                                            o_side = "buy" if signal_type == "LONG" else "sell"
                                            futures_ex.create_order(symbol, "market", o_side, amt_prec)
                                            st.session_state.signal_cooldown[cooldown_key] = time.time()
                                            st.session_state.trade_history.insert(0, {
                                                "Czas": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                                                "Para": symbol,
                                                "Typ": f"WEJŚCIE {signal_type} ({tf})",
                                                "Cena": f"{market_price:.4f}",
                                                "Ilość": f"{amt_prec:.4f}",
                                                "Dźwignia": f"{chosen_lev}x"
                                            })
                                            active_positions_count += 1
                                            existing_pos_map[symbol] = o_side
                                    except Exception:
                                        pass
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
st.text("Suwaki EMA / ADX / RSI działają na żywo. Zmiana wartości natychmiast wpływa na uruchomione boty.")

cols_tf = st.columns(len(AVAILABLE_TIMEFRAMES))

for idx, tf in enumerate(AVAILABLE_TIMEFRAMES):
    with cols_tf[idx]:
        st.markdown(f"**📌 {tf}**")
        prev_conf = st.session_state.active_mtf_bots.get(tf, {})

        # JEDNO ZRODLO PRAWDY: stan poczatkowy ustawiamy raz, potem widget jest wlascicielem
        # swojej wartosci (klucz w session_state). Bez podwojnego stanu wartosci nie "odskakuja".
        if f"radio_mode_{tf}" not in st.session_state:
            st.session_state[f"radio_mode_{tf}"] = prev_conf.get("mode", "Automatyczny")
        if f"ema_f_{tf}" not in st.session_state:
            st.session_state[f"ema_f_{tf}"] = int(min(200, max(1, prev_conf.get("ema_fast", 9))))
        if f"ema_s_{tf}" not in st.session_state:
            st.session_state[f"ema_s_{tf}"] = int(min(300, max(2, prev_conf.get("ema_slow", 21))))
        if f"adx_{tf}" not in st.session_state:
            st.session_state[f"adx_{tf}"] = float(min(50.0, max(10.0, prev_conf.get("min_adx", 28.0))))
        if f"max_rsi_{tf}" not in st.session_state:
            st.session_state[f"max_rsi_{tf}"] = float(min(95.0, max(50.0, prev_conf.get("max_rsi", 75.0))))
        if f"min_rsi_{tf}" not in st.session_state:
            st.session_state[f"min_rsi_{tf}"] = float(min(50.0, max(5.0, prev_conf.get("min_rsi", 25.0))))
        if f"cap_mult_{tf}" not in st.session_state:
            st.session_state[f"cap_mult_{tf}"] = float(min(20.0, max(0.1, prev_conf.get("capital_multiplier", DEFAULT_TF_MULTIPLIERS.get(tf, 1.0)))))

        bot_mode = st.radio(f"Tryb ({tf})", ["Automatyczny", "Ręczny"], key=f"radio_mode_{tf}")

        # Suwaki sa ZAWSZE widoczne i zawsze sluza jako wartosci bazowe.
        ema_f_val = st.number_input(f"EMA Szybka ({tf})", min_value=1, max_value=200, step=1, key=f"ema_f_{tf}")
        ema_s_val = st.number_input(f"EMA Wolna ({tf})", min_value=2, max_value=300, step=1, key=f"ema_s_{tf}")
        if ema_f_val >= ema_s_val:
            st.warning("⚠️ EMA szybka ≥ EMA wolna — używam zamienionych wartości (szybka < wolna).")
            eff_ema_fast, eff_ema_slow = int(ema_s_val), int(ema_f_val)
        else:
            eff_ema_fast, eff_ema_slow = int(ema_f_val), int(ema_s_val)

        adx_val = st.slider(f"Min ADX ({tf})", 10.0, 50.0, step=1.0, key=f"adx_{tf}")
        max_rsi_val = st.slider(f"Max RSI Long ({tf})", 50.0, 95.0, step=1.0, key=f"max_rsi_{tf}")
        min_rsi_val = st.slider(f"Min RSI Short ({tf})", 5.0, 50.0, step=1.0, key=f"min_rsi_{tf}")
        tf_cap_mult = st.number_input(f"Mnożnik kwoty ({tf})", min_value=0.1, max_value=20.0, step=0.5, key=f"cap_mult_{tf}")

        if bot_mode == "Automatyczny":
            st.info(f"⚡ Auto: suwaki to baza (obecnie {st.session_state.get('sb_auto_base_influence', 50)}% wpływu), resztę dobiera optymalizator w locie.")
        else:
            st.caption("🎛️ Ręczny: bot używa dokładnie wartości z suwaków powyżej.")

        # SYNCHRONIZACJA NA ZYWO: przy kazdym przeliczeniu aktualne wartosci suwakow
        # trafiaja do dzialajacego bota - dlatego zmiana suwaka dziala natychmiast.
        if tf in st.session_state.active_mtf_bots:
            st.session_state.active_mtf_bots[tf].update({
                "mode": bot_mode,
                "ema_fast": eff_ema_fast,
                "ema_slow": eff_ema_slow,
                "min_adx": adx_val,
                "max_rsi": max_rsi_val,
                "min_rsi": min_rsi_val,
                "capital_multiplier": tf_cap_mult,
            })

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
                        "mode": bot_mode,
                        "ema_fast": eff_ema_fast,
                        "ema_slow": eff_ema_slow,
                        "min_adx": adx_val,
                        "max_rsi": max_rsi_val,
                        "min_rsi": min_rsi_val,
                        "capital_multiplier": tf_cap_mult
                    }
                    st.success(f"Uruchomiono bota na {tf}!")
                    st.rerun()

st.markdown("---")
st.subheader(t('market_scanner_results'))
if scan_results:
    df_scan = pd.DataFrame(scan_results)
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

if is_user_admin():
    st.markdown("---")
    st.subheader(t("admin_panel"))
    col_u1, col_u2 = st.columns(2)
    with col_u1:
        target_uid = st.number_input("ID użytkownika do nadania subskrypcji", min_value=1, step=1, key="admin_target_uid")
        if st.button("Aktywuj subskrypcję użytkownikowi", use_container_width=True):
            try:
                conn = sqlite3.connect(DB_FILE, timeout=30.0)
                cursor = conn.cursor()
                cursor.execute("UPDATE users SET stripe_paid = 1 WHERE id = ?", (int(target_uid),))
                conn.commit()
                conn.close()
                st.success(f"Aktywowano subskrypcję dla użytkownika ID: {target_uid}")
                st.rerun()
            except Exception as e:
                st.error(f"Błąd: {e}")
    with col_u2:
        st.markdown("##### Usuń użytkownika z bazy")
        conn = sqlite3.connect(DB_FILE, timeout=30.0)
        users_list_df = pd.read_sql_query("SELECT id, email FROM users", conn)
        conn.close()
        if not users_list_df.empty:
            user_options = {f"ID {row['id']} - {row['email']}": row['id'] for _, row in users_list_df.iterrows()}
            selected_user_label = st.selectbox("Wybierz użytkownika do usunięcia", list(user_options.keys()), key="admin_del_select_box")
            target_del_uid = user_options[selected_user_label]
            if st.button("Usuń zaznaczonego użytkownika", use_container_width=True, type="primary"):
                if target_del_uid == st.session_state.get("user_id"):
                    st.error("Nie możesz usunąć samego siebie!")
                else:
                    try:
                        conn_del = sqlite3.connect(DB_FILE, timeout=30.0)
                        cur_del = conn_del.cursor()
                        cur_del.execute("DELETE FROM users WHERE id = ?", (int(target_del_uid),))
                        conn_del.commit()
                        conn_del.close()
                        st.success(f"Usunięto użytkownika o ID: {target_del_uid}")
                        time.sleep(1)
                        st.rerun()
                    except Exception as e:
                        st.error(f"Błąd: {e}")
    try:
        conn = sqlite3.connect(DB_FILE, timeout=30.0)
        df_users = pd.read_sql_query("SELECT id, email, is_admin, stripe_paid FROM users", conn)
        conn.close()
        st.dataframe(df_users, use_container_width=True)
    except Exception:
        pass

gc.collect()

if auto_refresh_seconds > 0:
    time.sleep(auto_refresh_seconds)
    st.rerun()

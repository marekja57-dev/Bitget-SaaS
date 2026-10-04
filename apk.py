import os
import sys
import time
import json
import sqlite3
import hmac
import hashlib
import gc
import ccxt
import numpy as np
import pandas as pd
import streamlit as st
import stripe
from datetime import datetime

# ==============================================================================
# CONFIG & INITIAL SETTINGS
# ==============================================================================
st.set_page_config(
    page_title="Multi-Exchange Futures SaaS",
    layout="wide",
    initial_sidebar_state="expanded"
)

DB_FILE = "users.db"
ALLOW_TEST_ACTIVATION = os.getenv("ALLOW_TEST_ACTIVATION", "0") == "1"

STRIPE_SECRET_KEY = os.getenv("STRIPE_SECRET_KEY", "")
STRIPE_PRICE_ID = os.getenv("STRIPE_PRICE_ID", "")
STRIPE_CHECKOUT_FALLBACK = os.getenv("STRIPE_CHECKOUT_FALLBACK", "")

if not STRIPE_SECRET_KEY:
    try:
        STRIPE_SECRET_KEY = st.secrets.get("STRIPE_SECRET_KEY", "")
        STRIPE_PRICE_ID = st.secrets.get("STRIPE_PRICE_ID", STRIPE_PRICE_ID)
        STRIPE_CHECKOUT_FALLBACK = st.secrets.get("STRIPE_CHECKOUT_FALLBACK", STRIPE_CHECKOUT_FALLBACK)
    except Exception:
        pass

if STRIPE_SECRET_KEY:
    stripe.api_key = STRIPE_SECRET_KEY

ADMIN_EMAILS = [
    "marekja57@wp.pl",
    "admin@bot-bitget.pl",
]

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
        "sub_zone": "💳 Strefa Subskrypcji",
        "sub_active": "Subskrypcja aktywna (Dostęp Pełny)",
        "sub_inactive": "⚠️ Brak aktywnej subskrypcji",
        "pay_btn": "OPŁAĆ DOSTĘP (49 PLN)",
        "capital_risk": "💰 Kapitał i Ryzyko",
        "max_single": "Maksymalnie USDT na 1 pozycję (Bazowo)",
        "max_pos": "Maks. aktywne pozycje Futures",
        "roe_guard": "🛡️ Zarządzanie Ryzykiem ROE (SL / TP)",
        "enable_roe": "Włącz strażnika SL / TP ROE",
        "sl_roe": "Stop-Loss ROE (%)",
        "tp_roe": "Take-Profit ROE (%)",
        "leverage_mgmt": "⚖️ Zarządzanie Dźwignią",
        "lev_mode": "Tryb Dźwigni",
        "max_allowed_lev": "Maksymalna dozwolona dźwignia",
        "manual_lev": "Stała dźwignia Futures",
        "bot_control": "🤖 Panel Sterowania Botami MTF",
        "max_pairs": "Liczba par Futures do skanowania",
        "kill_switch": "🚨 ZAMKNIJ WSZYSTKO (KILL SWITCH)",
        "wallet_futures": "💼 Portfel Futures",
        "free_balance": "Wolne",
        "session_results": "📊 Wyniki Sesji (PnL %)",
        "pnl_usdt": "PnL USDT",
        "slots_futures": "📈 Sloty Futures",
        "active_max": "Aktywne / Maksymalne",
        "session_time": "⏱️ Czas Sesji",
        "market_scanner_results": "📊 Wyniki Skanera Rynkowego",
        "active_positions": "📈 Aktywne Pozycje Futures",
        "trade_history": "📜 Historia Ostatnich Transakcji",
        "admin_panel": "🛠️ Panel Administratora (Użytkownicy)",
        "no_positions": "Brak otwartych pozycji futures.",
        "no_history": "Brak zarejestrowanych transakcji w tej sesji.",
        "no_scanner": "Brak aktywnych botów MTF lub wyników skanowania.",
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
        "sub_zone": "💳 Subscription Zone",
        "sub_active": "Subscription active (Full Access)",
        "sub_inactive": "⚠️ No active subscription",
        "pay_btn": "PAY ACCESS (49 PLN)",
        "capital_risk": "💰 Capital & Risk",
        "max_single": "Max USDT per position (Base)",
        "max_pos": "Max active Futures positions",
        "roe_guard": "🛡️ ROE Risk Management (SL / TP)",
        "enable_roe": "Enable SL / TP ROE guard",
        "sl_roe": "Stop-Loss ROE (%)",
        "tp_roe": "Take-Profit ROE (%)",
        "leverage_mgmt": "⚖️️ Leverage Management",
        "lev_mode": "Leverage Mode",
        "max_allowed_lev": "Maximum allowed leverage",
        "manual_lev": "Fixed Futures leverage",
        "bot_control": "🤖 Multi-Timeframe Bot Control Panel",
        "max_pairs": "Number of Futures pairs to scan",
        "kill_switch": "🚨 CLOSE ALL (KILL SWITCH)",
        "wallet_futures": "💼 Futures Wallet",
        "free_balance": "Free",
        "session_results": "📊 Session Results (PnL %)",
        "pnl_usdt": "PnL USDT",
        "slots_futures": "📈 Futures Slots",
        "active_max": "Active / Maximum",
        "session_time": "⏱️ Session Time",
        "market_scanner_results": "📊 Market Scanner Results",
        "active_positions": "📈 Active Futures Positions",
        "trade_history": "📜 Recent Trade History",
        "admin_panel": "🛠️ Admin Panel (Users)",
        "no_positions": "No open futures positions.",
        "no_history": "No recorded trades in this session.",
        "no_scanner": "No active MTF bots or scanner results.",
    },
}

def t(key):
    lang = st.session_state.get("lang", "Polski")
    return TRANSLATIONS.get(lang, TRANSLATIONS["Polski"]).get(key, key)

# ==============================================================================
# SESSION STATE INITIALIZATION
# ==============================================================================
SESSION_DEFAULTS = {
    "logged_in": False,
    "user_email": "",
    "is_admin": False,
    "user_id": None,
    "stripe_paid": False,
    "session_start_time": datetime.now(),
    "trade_history": [],
    "signal_cooldown": {},
    "symbol_cooldown": {},
    "lang": "Polski",
    "api_key": "",
    "secret_key": "",
    "passphrase": "",
    "selected_exchange": "Bitget",
    "session_start_balance": 0.0,
    "session_baseline_locked": False,
    "active_mtf_bots": {},
    "_mtf_loaded_user_id": None,
}

for key, default_value in SESSION_DEFAULTS.items():
    if key not in st.session_state:
        st.session_state[key] = default_value

AVAILABLE_TIMEFRAMES = ["1m", "5m", "15m", "30m", "1h", "4h", "1d"]
DEFAULT_TF_VALUES = {
    "1m": {"ema_fast": 9, "ema_slow": 21, "adx": 28.0, "max_rsi": 75.0, "min_rsi": 25.0, "cap_mult": 0.5},
    "5m": {"ema_fast": 9, "ema_slow": 21, "adx": 28.0, "max_rsi": 75.0, "min_rsi": 25.0, "cap_mult": 0.8},
    "15m": {"ema_fast": 9, "ema_slow": 21, "adx": 28.0, "max_rsi": 75.0, "min_rsi": 25.0, "cap_mult": 1.0},
    "30m": {"ema_fast": 9, "ema_slow": 21, "adx": 28.0, "max_rsi": 75.0, "min_rsi": 25.0, "cap_mult": 1.5},
    "1h": {"ema_fast": 9, "ema_slow": 21, "adx": 28.0, "max_rsi": 75.0, "min_rsi": 25.0, "cap_mult": 2.5},
    "4h": {"ema_fast": 9, "ema_slow": 21, "adx": 28.0, "max_rsi": 75.0, "min_rsi": 25.0, "cap_mult": 4.0},
    "1d": {"ema_fast": 9, "ema_slow": 21, "adx": 28.0, "max_rsi": 75.0, "min_rsi": 25.0, "cap_mult": 6.0},
}

for tf in AVAILABLE_TIMEFRAMES:
    defaults = DEFAULT_TF_VALUES[tf]
    widget_defaults = {
        f"radio_mode_{tf}": "Automatyczny",
        f"ema_f_{tf}": defaults["ema_fast"],
        f"ema_s_{tf}": defaults["ema_slow"],
        f"adx_{tf}": defaults["adx"],
        f"max_rsi_{tf}": defaults["max_rsi"],
        f"min_rsi_{tf}": defaults["min_rsi"],
        f"cap_mult_{tf}": defaults["cap_mult"],
    }
    for key, value in widget_defaults.items():
        if key not in st.session_state:
            st.session_state[key] = value

# ==============================================================================
# DATABASE & USER AUTH UTILITIES
# ==============================================================================
def is_user_admin():
    email = str(st.session_state.get("user_email", "")).strip().lower()
    return email in ADMIN_EMAILS or bool(st.session_state.get("is_admin", False))

def is_user_paid():
    email = str(st.session_state.get("user_email", "")).strip().lower()
    return email in ADMIN_EMAILS or bool(st.session_state.get("stripe_paid", False))

def hash_password(password, salt=None):
    if salt is None:
        salt = os.urandom(16).hex()
    digest = hashlib.sha256((salt + password).encode("utf-8")).hexdigest()
    return f"sha256${salt}${digest}"

def verify_password(password, stored):
    if not stored:
        return False
    stored = str(stored)
    if stored.startswith("sha256$"):
        try:
            parts = stored.split("$", 2)
            if len(parts) != 3:
                return False
            salt = parts[1]
            expected = parts[2]
            candidate = hashlib.sha256((salt + password).encode("utf-8")).hexdigest()
            return hmac.compare_digest(candidate, expected)
        except Exception:
            return False
    return hmac.compare_digest(stored, str(password))

def init_db():
    conn = sqlite3.connect(DB_FILE, timeout=30.0)
    try:
        cursor = conn.cursor()
        cursor.execute("PRAGMA journal_mode=WAL;")
        cursor.execute(
            """CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT, 
                email TEXT UNIQUE, 
                password TEXT, 
                is_admin INTEGER DEFAULT 0, 
                stripe_paid INTEGER DEFAULT 0, 
                api_key TEXT, 
                secret_key TEXT, 
                passphrase TEXT
            )"""
        )
        cursor.execute(
            """CREATE TABLE IF NOT EXISTS user_mtf_settings (
                user_id INTEGER PRIMARY KEY, 
                settings_json TEXT NOT NULL, 
                updated_at TEXT NOT NULL, 
                FOREIGN KEY(user_id) REFERENCES users(id)
            )"""
        )
        columns = [
            ("api_key", "TEXT"),
            ("secret_key", "TEXT"),
            ("passphrase", "TEXT"),
            ("stripe_paid", "INTEGER DEFAULT 0"),
            ("is_admin", "INTEGER DEFAULT 0"),
        ]
        for col, col_type in columns:
            try:
                cursor.execute(f"ALTER TABLE users ADD COLUMN {col} {col_type}")
            except sqlite3.OperationalError:
                pass
        for adm_email in ADMIN_EMAILS:
            cursor.execute(
                """UPDATE users SET is_admin = 1, stripe_paid = 1 WHERE LOWER(TRIM(email)) = ?""",
                (adm_email,),
            )
        conn.commit()
    finally:
        conn.close()

def mtfdefault_settings():
    return {tf: dict(values) for tf, values in DEFAULT_TF_VALUES.items()}

def load_mtf_settings_for_user(user_id):
    if not user_id:
        return
    settings = mtfdefault_settings()
    try:
        conn = sqlite3.connect(DB_FILE, timeout=30.0)
        row = conn.execute(
            "SELECT settings_json FROM user_mtf_settings WHERE user_id = ?",
            (int(user_id),),
        ).fetchone()
        conn.close()
        if row and row[0]:
            stored = json.loads(row[0])
            if isinstance(stored, dict):
                for tf in AVAILABLE_TIMEFRAMES:
                    if isinstance(stored.get(tf), dict):
                        settings[tf].update(stored[tf])
    except Exception:
        pass
    for tf in AVAILABLE_TIMEFRAMES:
        defaults = settings[tf]
        st.session_state[f"radio_mode_{tf}"] = "Ręczny" if defaults.get("mode") == "Ręczny" else "Automatyczny"
        st.session_state[f"ema_f_{tf}"] = int(defaults.get("ema_fast", 9))
        st.session_state[f"ema_s_{tf}"] = int(defaults.get("ema_slow", 21))
        st.session_state[f"adx_{tf}"] = float(defaults.get("adx", 20.0))
        st.session_state[f"min_rsi_{tf}"] = float(defaults.get("min_rsi", 30.0))
        st.session_state[f"max_rsi_{tf}"] = float(defaults.get("max_rsi", 70.0))
        st.session_state[f"cap_mult_{tf}"] = float(defaults.get("cap_mult", 1.0))
    st.session_state["_mtf_loaded_user_id"] = int(user_id)

def save_mtf_settings_for_user(user_id):
    if not user_id:
        return
    payload = {}
    for tf in AVAILABLE_TIMEFRAMES:
        payload[tf] = {
            "mode": st.session_state.get(f"radio_mode_{tf}", "Automatyczny"),
            "ema_fast": int(st.session_state.get(f"ema_f_{tf}", DEFAULT_TF_VALUES[tf]["ema_fast"])),
            "ema_slow": int(st.session_state.get(f"ema_s_{tf}", DEFAULT_TF_VALUES[tf]["ema_slow"])),
            "adx": float(st.session_state.get(f"adx_{tf}", DEFAULT_TF_VALUES[tf]["adx"])),
            "max_rsi": float(st.session_state.get(f"max_rsi_{tf}", DEFAULT_TF_VALUES[tf]["max_rsi"])),
            "min_rsi": float(st.session_state.get(f"min_rsi_{tf}", DEFAULT_TF_VALUES[tf]["min_rsi"])),
            "cap_mult": float(st.session_state.get(f"cap_mult_{tf}", DEFAULT_TF_VALUES[tf]["cap_mult"])),
        }
    try:
        conn = sqlite3.connect(DB_FILE, timeout=30.0)
        conn.execute(
            """INSERT INTO user_mtf_settings (user_id, settings_json, updated_at) 
               VALUES (?, ?, ?) 
               ON CONFLICT(user_id) DO UPDATE SET 
               settings_json = excluded.settings_json, 
               updated_at = excluded.updated_at""",
            (
                int(user_id),
                json.dumps(payload, ensure_ascii=False),
                datetime.now().isoformat(timespec="seconds"),
            ),
        )
        conn.commit()
        conn.close()
    except Exception:
        pass
    # ==============================================================================
# FINANCIAL & TRADING INDICATOR CALCULATIONS
# ==============================================================================
def get_secret(name, default=""):
    value = os.getenv(name)
    if value:
        return value
    try:
        return st.secrets.get(name, default)
    except Exception:
        return default

def create_stripe_checkout_session(user_email, price_id):
    try:
        if not stripe.api_key or not price_id:
            return STRIPE_CHECKOUT_FALLBACK
        session = stripe.checkout.Session.create(
            payment_method_types=["card"],
            line_items=[{"price": price_id, "quantity": 1}],
            mode="payment",
            success_url="http://localhost:8501/?success=true",
            cancel_url="http://localhost:8501/?canceled=true",
            customer_email=user_email,
        )
        if session and session.url:
            return session.url
    except Exception:
        pass
    return STRIPE_CHECKOUT_FALLBACK

def calculate_indicators(df, ema_fast=9, ema_slow=21, adx_period=14):
    df = df.copy()
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
    df["plus_di_smooth"] = pd.Series(df["plus_dm"], index=df.index).ewm(alpha=alpha, adjust=False).mean()
    df["minus_di_smooth"] = pd.Series(df["minus_dm"], index=df.index).ewm(alpha=alpha, adjust=False).mean()
    
    tr_smooth = df["tr_smooth"].replace(0, np.nan)
    df["plus_di"] = 100 * (df["plus_di_smooth"] / tr_smooth)
    df["minus_di"] = 100 * (df["minus_di_smooth"] / tr_smooth)
    
    di_sum = (df["plus_di"] + df["minus_di"]).replace(0, np.nan)
    df["dx"] = 100 * abs(df["plus_di"] - df["minus_di"]) / di_sum
    df["adx"] = df["dx"].ewm(alpha=alpha, adjust=False).mean()
    
    delta = df["close"].diff()
    gain = delta.where(delta > 0, 0).ewm(span=14, adjust=False).mean()
    loss = -delta.where(delta < 0, 0).ewm(span=14, adjust=False).mean()
    rs = gain / loss.replace(0, np.nan)
    df["rsi"] = 100 - (100 / (1 + rs))
    
    return df

def get_optimal_dynamic_parameters(df_recent, tf):
    try:
        closes = df_recent["close"].astype(float).values
        if len(closes) < 3:
            raise ValueError("Za mało danych do obliczeń zmienności.")
        returns = np.diff(closes) / closes[:-1]
        volatility = np.std(returns) * np.sqrt(len(returns))
        
        if tf in ["1m", "5m"]:
            if volatility > 0.02:
                return {"ema_fast": 5, "ema_slow": 13, "min_adx": 22.0, "max_rsi": 72.0, "min_rsi": 28.0, "capital_multiplier": 0.6}
            return {"ema_fast": 9, "ema_slow": 21, "min_adx": 26.0, "max_rsi": 75.0, "min_rsi": 25.0, "capital_multiplier": 0.8}
        if tf in ["15m", "30m"]:
            if volatility > 0.03:
                return {"ema_fast": 7, "ema_slow": 18, "min_adx": 24.0, "max_rsi": 70.0, "min_rsi": 30.0, "capital_multiplier": 1.0}
            return {"ema_fast": 10, "ema_slow": 25, "min_adx": 25.0, "max_rsi": 78.0, "min_rsi": 22.0, "capital_multiplier": 1.2}
        return {"ema_fast": 12, "ema_slow": 26, "min_adx": 20.0, "max_rsi": 80.0, "min_rsi": 20.0, "capital_multiplier": 2.5}
    except Exception:
        return {"ema_fast": 9, "ema_slow": 21, "min_adx": 25.0, "max_rsi": 75.0, "min_rsi": 25.0, "capital_multiplier": 1.0}

def blend_params(base, opt, base_weight=0.5):
    w = max(0.0, min(1.0, float(base_weight)))
    return {
        "ema_fast": max(1, int(round(base["ema_fast"] * w + opt["ema_fast"] * (1 - w)))),
        "ema_slow": max(2, int(round(base["ema_slow"] * w + opt["ema_slow"] * (1 - w)))),
        "min_adx": round(base["min_adx"] * w + opt["min_adx"] * (1 - w), 2),
        "max_rsi": round(base["max_rsi"] * w + opt["max_rsi"] * (1 - w), 2),
        "min_rsi": round(base["min_rsi"] * w + opt["min_rsi"] * (1 - w), 2),
        "capital_multiplier": round(base["capital_multiplier"] * w + opt["capital_multiplier"] * (1 - w), 2),
    }

# ==============================================================================
# EXCHANGES INTERFACE & RISK MANAGEMENT LOGIC
# ==============================================================================
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
        return exchange_class(config)
    except Exception:
        return None

def calculate_risk_based_allocation(
    free_balance, entry_price, stop_loss_price, risk_percentage=0.01, leverage=1, max_single_limit=50.0, tf_multiplier=1.0
):
    if free_balance <= 0 or entry_price <= 0 or stop_loss_price <= 0:
        return max(5.0 * tf_multiplier, min(max_single_limit * tf_multiplier, free_balance * 0.1 * tf_multiplier))
    
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
        limits = market.get("limits", {})
        leverage_limits = limits.get("leverage", {})
        max_lev = leverage_limits.get("max")
        if max_lev:
            return int(max_lev)
    except Exception:
        pass
    return default_max

def get_smart_leverage(adx_val, exchange_limit, preferred_max=15):
    effective_max = min(preferred_max, exchange_limit)
    adx_clamped = min(max(float(adx_val), 10.0), 55.0)
    ratio = (adx_clamped - 10.0) / (55.0 - 10.0)
    floating_lev = 1.0 + ratio * (effective_max - 1.0)
    return int(round(floating_lev))

# Init Database Execution
init_db()
stripe_price_id_val = get_secret("STRIPE_PRICE_ID", STRIPE_PRICE_ID)
if STRIPE_SECRET_KEY:
    stripe.api_key = STRIPE_SECRET_KEY

# URL Params Stripe Handler
if st.query_params.get("success") == "true":
    if st.session_state.logged_in and st.session_state.user_id:
        st.session_state.stripe_paid = True
        try:
            conn = sqlite3.connect(DB_FILE, timeout=30.0)
            cursor = conn.cursor()
            cursor.execute("UPDATE users SET stripe_paid = 1 WHERE id = ?", (st.session_state.user_id,))
            conn.commit()
            conn.close()
        except Exception:
            pass
        st.success("🎉 Płatność zakończona sukcesem! Twoja subskrypcja została aktywowana.")
        st.query_params.clear()

# Custom UI CSS Rules
st.markdown(
    """<style>
    @import url('https://fonts.googleapis.com/css2?family=Bungee+Inline&family=Cinzel:wght@400;700&display=swap');
    .stApp {background-color: #0d0b0a;}
    section[data-testid="stSidebar"] {background-color: #141110;border-right: 2px solid #3d2f1f;}
    .metrics-row {display: flex;flex-direction: row;flex-wrap: nowrap !important;gap: 14px;width: 100%;margin-bottom: 10px;}
    .metric-card {flex: 1;min-width: 0;border: 2px solid #f3d57a;border-radius: 10px;padding: 12px 14px;background-color: rgba(243, 213, 122, 0.03);box-shadow: 0 4px 12px rgba(0, 0, 0, 0.2);}
    .metric-label {font-family: 'Cinzel', serif;color: #f3d57a;font-size: 0.85rem;font-weight: 700;margin-bottom: 6px;white-space: nowrap;overflow: hidden;text-overflow: ellipsis;}
    .metric-value {font-size: 1.4rem;font-weight: bold;color: #ffffff;margin-bottom: 4px;}
    .metric-delta {font-size: 0.75rem;color: #e6c687;}
    .hero-wrapper {display: flex;align-items: center;justify-content: center;width: 100%;padding-top: 50px;padding-bottom: 20px;}
    .retro-ornate-frame {position: relative;background: radial-gradient(circle, #221a14 0%, #110d0a 100%);border: 6px double #f3d57a;padding: 40px 30px;border-radius: 16px;box-shadow: 0 0 50px rgba(243, 213, 122, 0.4), inset 0 0 35px rgba(0, 0, 0, 0.9);width: 100%;max-width: 600px;text-align: center;}
    .retro-vintage-title {font-family: 'Bungee Inline', cursive, sans-serif;font-size: 3rem;color: #f3d57a;letter-spacing: 4px;text-shadow: 4px 4px 0px #8b0000, 8px 8px 0px rgba(0,0,0,0.95);margin-bottom: 10px;}
    .retro-subtitle {font-family: 'Cinzel', serif;color: #e6c687;font-size: 1.1rem;letter-spacing: 2px;margin-bottom: 25px;}
    div.stButton > button {background: linear-gradient(135deg, #1e4d2b 0%, #0f2b17 100%) !important;color: #f3d57a !important;border: 2px solid #f3d57a !important;font-family: 'Cinzel', serif !important;font-weight: 700 !important;font-size: 1rem !important;padding: 10px 24px !important;border-radius: 8px !important;box-shadow: 0 4px 15px rgba(0, 0, 0, 0.6) !important;transition: all 0.3s ease !important;}
    div.stButton > button:hover {background: linear-gradient(135deg, #28663a 0%, #163d22 100%) !important;border-color: #ffe89d !important;color: #ffe89d !important;box-shadow: 0 0 20px rgba(243, 213, 122, 0.4) !important;transform: translateY(-2px);}
    </style>""",
    unsafe_allow_html=True,
)
# ==============================================================================
# AUTHENTICATION & LOGIN UI
# ==============================================================================
def render_login_register():
    st.markdown('<div class="hero-wrapper">', unsafe_allow_html=True)
    st.markdown(
        f"""
        <div class="retro-ornate-frame">
            <div class="retro-vintage-title">{t("title")}</div>
            <div class="retro-subtitle">{t("subtitle")}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )
    st.markdown('</div>', unsafe_allow_html=True)

    c1, c2, c3 = st.columns([1, 2, 1])
    with c2:
        tab1, tab2 = st.tabs([t("login_tab"), t("register_tab")])

        with tab1:
            login_email = st.text_input(t("email_label"), key="l_email").strip().lower()
            login_pass = st.text_input(t("pass_label"), type="password", key="l_pass")
            
            if st.button(t("login_btn"), use_container_width=True):
                if login_email and login_pass:
                    conn = sqlite3.connect(DB_FILE, timeout=30.0)
                    cursor = conn.cursor()
                    cursor.execute(
                        "SELECT id, email, password, is_admin, stripe_paid, api_key, secret_key, passphrase FROM users WHERE LOWER(TRIM(email)) = ?",
                        (login_email,),
                    )
                    user = cursor.fetchone()
                    conn.close()

                    if user and verify_password(login_pass, user[2]):
                        st.session_state.logged_in = True
                        st.session_state.user_id = user[0]
                        st.session_state.user_email = user[1]
                        st.session_state.is_admin = bool(user[3]) or (login_email in ADMIN_EMAILS)
                        st.session_state.stripe_paid = bool(user[4]) or (login_email in ADMIN_EMAILS)
                        st.session_state.api_key = user[5] or ""
                        st.session_state.secret_key = user[6] or ""
                        st.session_state.passphrase = user[7] or ""
                        
                        load_mtf_settings_for_user(user[0])
                        st.success(t("login_success"))
                        st.rerun()
                    else:
                        st.error(t("login_error"))

        with tab2:
            reg_email = st.text_input(t("email_label"), key="r_email").strip().lower()
            reg_pass = st.text_input(t("pass_label"), type="password", key="r_pass")
            
            if st.button(t("register_btn"), use_container_width=True):
                if reg_email and reg_pass:
                    conn = sqlite3.connect(DB_FILE, timeout=30.0)
                    cursor = conn.cursor()
                    try:
                        hashed = hash_password(reg_pass)
                        is_admin_val = 1 if reg_email in ADMIN_EMAILS else 0
                        stripe_paid_val = 1 if reg_email in ADMIN_EMAILS else 0
                        
                        cursor.execute(
                            "INSERT INTO users (email, password, is_admin, stripe_paid) VALUES (?, ?, ?, ?)",
                            (reg_email, hashed, is_admin_val, stripe_paid_val),
                        )
                        conn.commit()
                        st.success(t("reg_success"))
                    except sqlite3.IntegrityError:
                        st.error(t("reg_error_exists"))
                    finally:
                        conn.close()
                else:
                    st.warning(t("reg_error_fill"))

# Render screen if not logged in
if not st.session_state.logged_in:
    render_login_register()
    st.stop()

# Auto-load MTF Settings for session
if st.session_state.user_id and st.session_state.get("_mtf_loaded_user_id") != st.session_state.user_id:
    load_mtf_settings_for_user(st.session_state.user_id)                                                                                         
# ==============================================================================
# INSTRUKCJA OBSŁUGI I REGULAMIN (ZIELONO-ZŁOTE KAFELKI)
# ==============================================================================
col_inst, col_reg = st.columns(2)

with col_inst:
    with st.expander("📖 INSTRUKCJA OBSŁUGI SYSTEMU"):
        st.markdown("""
        ### 📖 Przewodnik Użytkownika

        1. **Konfiguracja Dostępów:**
           - Przejdź do panelu bocznego (`SAAS PANEL`).
           - Wybierz docelową giełdę (Bitget, Binance, Bybit, OKX).
           - Wklej swoje klucze API (`API Key`, `Secret Key`, `Passphrase`) i zatwierdź przyciskiem **ZAPISZ MOJE KLUCZE**.

        2. **Aktywacja Subskrypcji:**
           - Aby bot mógł automatycznie otwierać pozycje, wymagana jest aktywna subskrypcja (Strefa Subskrypcji w panelu bocznym).

        3. **Zarządzanie Ryzykiem i Kapitałem:**
           - **Maksymalnie USDT na pozycję:** Ustal maksymalną kwotę bazową przydzielaną do jednej transakcji.
           - **Zarządzanie ROE:** Włącz strażnika SL/TP, aby zabezpieczyć pozycje na poziomie giełdy w oparciu o stopę zwrotu z kapitału.
           - **Tryb Dźwigni:** Wybierz dźwignię dynamiczną (obliczaną na podstawie wskaźnika ADX) lub ręczną (stałą).

        4. **Konfiguracja Botów MTF (Multi-Timeframe):**
           - Aktywuj interwały czasowe (np. 5m, 15m, 1h), na których ma pracować algorytm.
           - Wybierz tryb **Automatyczny** (dynamiczne dostosowanie wskaźników do zmienności) lub **Ręczny** (własne progi EMA, ADX, RSI).

        5. **Procedura Awaryjna:**
           - W dowolnym momencie możesz użyć przycisku **🚨 KILL SWITCH**, aby natychmiast zamknąć wszystkie otwarte pozycje rynkowe.
        """)

with col_reg:
    with st.expander("📜 REGULAMIN I ZASTRZEŻENIA PRAWNE"):
        st.markdown("""
        ### 📜 Regulamin Korzystania z Systemu

        1. **Wyłączenie Odpowiedzialności Finansowej:**
           - Handel na rynku instrumentów pochodnych (Futures/Swap) wiąże się z wysokim ryzykiem utraty kapitału.
           - Oprogramowanie ma charakter wyłącznie narzędziowy i wspomagający. Nie stanowi rekomendacji inwestycyjnej w rozumieniu przepisów prawa.
           - Użytkownik ponosi wyłączną i pełną odpowiedzialność za wszelkie decyzje finansowe oraz ewentualne straty wynikające z działania oprogramowania.

        2. **Bezpieczeństwo Kluczy API:**
           - Klucze API użytkownika powinny posiadać uprawnienia wyłącznie do handlu Futures (`Trading`).
           - **NIGDY** nie należy włączać uprawnień do wypłat (`Withdrawal`) dla kluczy API podłączanych do bota.

        3. **Dostępność Usługi:**
           - Dostawca systemu nie odpowiada za opóźnienia, błędy połączenia API po stronie giełd kryptowalutowych ani opóźnienia sieciowe.

        4. **Warunki Subskrypcji:**
           - Dostęp do pełnych funkcji automatycznej egzekucji transakcji przyznawany jest na czas trwania opłaconego okresu subskrypcyjnego.
        """)

# ==============================================================================
# SIDEBAR NAVIGATION & SETTINGS
# ==============================================================================
st.sidebar.title("🎛️ SAAS PANEL")
st.sidebar.text(f"Zalogowano: {st.session_state.user_email}")

if is_user_admin():
    st.sidebar.info(t("sidebar_role_admin"))
else:
    st.sidebar.text(t("sidebar_role_client"))

if st.sidebar.button(t("logout_btn")):
    for k in list(st.session_state.keys()):
        del st.session_state[k]
    st.rerun()

st.sidebar.markdown("---")
st.sidebar.subheader(t("exchange_settings"))
selected_ex = st.sidebar.selectbox(t("select_exchange"), ["Bitget", "Binance", "Bybit", "OKX"])
st.session_state.selected_exchange = selected_ex

st.sidebar.subheader(t("api_keys_header"))
api_key_input = st.sidebar.text_input("API Key", value=st.session_state.api_key, type="password")
secret_key_input = st.sidebar.text_input("Secret Key", value=st.session_state.secret_key, type="password")
passphrase_input = st.sidebar.text_input("Passphrase / Password", value=st.session_state.passphrase, type="password")

if st.sidebar.button(t("save_keys_btn")):
    st.session_state.api_key = api_key_input
    st.session_state.secret_key = secret_key_input
    st.session_state.passphrase = passphrase_input
    
    if st.session_state.user_id:
        conn = sqlite3.connect(DB_FILE, timeout=30.0)
        cursor = conn.cursor()
        cursor.execute(
            "UPDATE users SET api_key = ?, secret_key = ?, passphrase = ? WHERE id = ?",
            (api_key_input, secret_key_input, passphrase_input, st.session_state.user_id),
        )
        conn.commit()
        conn.close()
    st.sidebar.success(f"{t('keys_saved')} {selected_ex}!")

st.sidebar.markdown("---")
st.sidebar.subheader(t("sub_zone"))

if is_user_paid():
    st.sidebar.success(t("sub_active"))
else:
    st.sidebar.error(t("sub_inactive"))
    checkout_url = create_stripe_checkout_session(st.session_state.user_email, stripe_price_id_val)
    if checkout_url:
        st.sidebar.markdown(f'[👉 **{t("pay_btn")}**]({checkout_url})', unsafe_allow_html=True)
    if ALLOW_TEST_ACTIVATION:
        if st.sidebar.button("🧪 Aktywuj Testowo (DEV)"):
            st.session_state.stripe_paid = True
            if st.session_state.user_id:
                conn = sqlite3.connect(DB_FILE, timeout=30.0)
                cursor = conn.cursor()
                cursor.execute("UPDATE users SET stripe_paid = 1 WHERE id = ?", (st.session_state.user_id,))
                conn.commit()
                conn.close()
            st.rerun()

st.sidebar.markdown("---")
st.sidebar.subheader(t("capital_risk"))
max_usdt_per_pos = st.sidebar.number_input(t("max_single"), min_value=5.0, max_value=10000.0, value=50.0, step=5.0)
max_active_positions = st.sidebar.number_input(t("max_pos"), min_value=1, max_value=20, value=3)

st.sidebar.subheader(t("roe_guard"))
enable_roe = st.sidebar.checkbox(t("enable_roe"), value=True)
sl_roe_pct = st.sidebar.number_input(t("sl_roe"), min_value=0.5, max_value=500.0, value=10.0, step=0.5)
tp_roe_pct = st.sidebar.number_input(t("tp_roe"), min_value=0.5, max_value=1000.0, value=25.0, step=0.5)

st.sidebar.subheader(t("leverage_mgmt"))
leverage_mode = st.sidebar.radio(t("lev_mode"), ["Dynamiczna (ADX)", "Ręczna / Stała"], index=0)
max_allowed_leverage = st.sidebar.slider(t("max_allowed_lev"), min_value=1, max_value=125, value=15)
manual_leverage = st.sidebar.number_input(t("manual_lev"), min_value=1, max_value=125, value=5)

# Initialize Exchange Client
exchange = get_exchange(
    st.session_state.api_key,
    st.session_state.secret_key,
    st.session_state.passphrase,
    ex_name=st.session_state.selected_exchange,
)

# Fetch Balance
free_usdt = 0.0
total_usdt = 0.0
if exchange:
    try:
        balance = exchange.fetch_balance({"type": "swap"})
        free_usdt = float(balance.get("USDT", {}).get("free", 0.0) or 0.0)
        total_usdt = float(balance.get("USDT", {}).get("total", 0.0) or 0.0)
        if not st.session_state.session_baseline_locked and total_usdt > 0:
            st.session_state.session_start_balance = total_usdt
            st.session_state.session_baseline_locked = True
    except Exception:
        pass

# ==============================================================================
# MAIN WORKSPACE & MTF BOT CONTROL
# ==============================================================================
st.title(f"🚀 {t('title')} - {st.session_state.selected_exchange.upper()}")

if not is_user_paid():
    st.warning("⚠️ Twój dostęp jest w trybie podglądu. Opłać subskrypcję w panelu bocznym, aby odblokować automatyczną egzekucję pozycji.")

st.markdown(f"### {t('bot_control')}")

max_scan_pairs = st.number_input(t("max_pairs"), min_value=1, max_value=50, value=10, step=1)

# Render Timeframe Modules & Controls
cols = st.columns(len(AVAILABLE_TIMEFRAMES))
for idx, tf in enumerate(AVAILABLE_TIMEFRAMES):
    with cols[idx]:
        st.markdown(f"#### ⏱️ {tf}")
        is_active = st.checkbox(f"Włącz {tf}", key=f"active_tf_{tf}", value=(tf in ["5m", "15m"]))
        st.session_state.active_mtf_bots[tf] = is_active
        
        mode = st.radio("Tryb", ["Automatyczny", "Ręczny"], key=f"radio_mode_{tf}")
        
        if mode == "Ręczny":
            st.number_input("EMA Fast", min_value=1, max_value=100, key=f"ema_f_{tf}")
            st.number_input("EMA Slow", min_value=2, max_value=200, key=f"ema_s_{tf}")
            st.number_input("Min ADX", min_value=0.0, max_value=100.0, key=f"adx_{tf}")
            st.number_input("Max RSI", min_value=50.0, max_value=100.0, key=f"max_rsi_{tf}")
            st.number_input("Min RSI", min_value=0.0, max_value=50.0, key=f"min_rsi_{tf}")
            st.number_input("Mnożnik Kapitału", min_value=0.1, max_value=10.0, key=f"cap_mult_{tf}")

if st.button("💾 ZAPISZ USTAWIENIA BOTÓW MTF"):
    if st.session_state.user_id:
        save_mtf_settings_for_user(st.session_state.user_id)
        st.success("Zapisano konfiguracyjne parametry MTF w bazie danych!")

st.markdown("---")

# Global Actions & Kill Switch
if st.button(t("kill_switch"), use_container_width=True):
    st.warning("🚨 Wyzwalanie procedury KILL SWITCH...")
    if exchange:
        try:
            positions = exchange.fetch_positions()
            for pos in positions:
                size = float(pos.get("contracts", 0) or pos.get("size", 0) or 0)
                if size > 0:
                    sym = pos["symbol"]
                    side = "sell" if pos.get("side") == "long" else "buy"
                    exchange.create_order(sym, "market", side, size, params={"reduceOnly": True})
            st.success("Wszystkie pozycje zostały natychmiast zamknięte!")
        except Exception as e:
            st.error(f"Błąd podczas wykonywania Kill Switch: {e}")

# Metric Cards Display Bar
start_bal = st.session_state.session_start_balance
pnl_val = (total_usdt - start_bal) if start_bal > 0 else 0.0
pnl_pct = ((total_usdt - start_bal) / start_bal * 100) if start_bal > 0 else 0.0

pnl_color = "#00ff88" if pnl_val >= 0 else "#ff4d4d"
session_duration = str(datetime.now() - st.session_state.session_start_time).split(".")[0]

st.markdown(
    f"""
    <div class="metrics-row">
        <div class="metric-card">
            <div class="metric-label">{t("wallet_futures")}</div>
            <div class="metric-value">${total_usdt:.2f}</div>
            <div class="metric-delta">{t("free_balance")}: ${free_usdt:.2f}</div>
        </div>
        <div class="metric-card">
            <div class="metric-label">{t("session_results")}</div>
            <div class="metric-value" style="color: {pnl_color};">{pnl_pct:+.2f}%</div>
            <div class="metric-delta">{t("pnl_usdt")}: ${pnl_val:+.2f}</div>
        </div>
        <div class="metric-card">
            <div class="metric-label">{t("slots_futures")}</div>
            <div class="metric-value">0 / {max_active_positions}</div>
            <div class="metric-delta">{t("active_max")}</div>
        </div>
        <div class="metric-card">
            <div class="metric-label">{t("session_time")}</div>
            <div class="metric-value">{session_duration}</div>
            <div class="metric-delta">Autonomiczny Cykl Transakcyjny</div>
        </div>
    </div>
    """,
    unsafe_allow_html=True,
)

st.markdown("---")

# ==============================================================================
# MAIN SCANNER & EXECUTION LOOP
# ==============================================================================
st.subheader(t("market_scanner_results"))

scanner_rows = []
if exchange and is_user_paid():
    try:
        markets = exchange.load_markets()
        usdt_pairs = [s for s in markets if s.endswith("/USDT:USDT") or s.endswith("/USDT")]
        target_pairs = usdt_pairs[:max_scan_pairs]
        
        for sym in target_pairs:
            for tf, active in st.session_state.active_mtf_bots.items():
                if not active:
                    continue
                try:
                    ohlcv = exchange.fetch_ohlcv(sym, timeframe=tf, limit=100)
                    if len(ohlcv) < 30:
                        continue
                    
                    df = pd.DataFrame(ohlcv, columns=["timestamp", "open", "high", "low", "close", "volume"])
                    
                    if st.session_state.get(f"radio_mode_{tf}") == "Automatyczny":
                        opt_params = get_optimal_dynamic_parameters(df, tf)
                        base_params = {
                            "ema_fast": st.session_state.get(f"ema_f_{tf}", 9),
                            "ema_slow": st.session_state.get(f"ema_s_{tf}", 21),
                            "min_adx": st.session_state.get(f"adx_{tf}", 20.0),
                            "max_rsi": st.session_state.get(f"max_rsi_{tf}", 70.0),
                            "min_rsi": st.session_state.get(f"min_rsi_{tf}", 30.0),
                            "capital_multiplier": st.session_state.get(f"cap_mult_{tf}", 1.0),
                        }
                        params = blend_params(base_params, opt_params, base_weight=0.5)
                    else:
                        params = {
                            "ema_fast": st.session_state.get(f"ema_f_{tf}", 9),
                            "ema_slow": st.session_state.get(f"ema_s_{tf}", 21),
                            "min_adx": st.session_state.get(f"adx_{tf}", 20.0),
                            "max_rsi": st.session_state.get(f"max_rsi_{tf}", 70.0),
                            "min_rsi": st.session_state.get(f"min_rsi_{tf}", 30.0),
                            "capital_multiplier": st.session_state.get(f"cap_mult_{tf}", 1.0),
                        }
                    
                    df = calculate_indicators(df, ema_fast=params["ema_fast"], ema_slow=params["ema_slow"])
                    last_row = df.iloc[-1]
                    
                    signal = "NEUTRALNY"
                    if (last_row["ema_fast"] > last_row["ema_slow"]) and (last_row["adx"] >= params["min_adx"]) and (last_row["rsi"] <= params["max_rsi"]):
                        signal = "LONG 🟢"
                    elif (last_row["ema_fast"] < last_row["ema_slow"]) and (last_row["adx"] >= params["min_adx"]) and (last_row["rsi"] >= params["min_rsi"]):
                        signal = "SHORT 🔴"
                    
                    scanner_rows.append({
                        "Symbol": sym,
                        "Timeframe": tf,
                        "Cena": last_row["close"],
                        "EMA Fast": round(last_row["ema_fast"], 4),
                        "EMA Slow": round(last_row["ema_slow"], 4),
                        "ADX": round(last_row["adx"], 2),
                        "RSI": round(last_row["rsi"], 2),
                        "Sygnał": signal,
                    })
                    # ==========================================================
                    # BEZPOŚREDNIA EGZEKUCJA ZLECEŃ NA GIEŁDZIE (EXECUTION ENGINE)
                    # ==========================================================
                    if signal in ["LONG 🟢", "SHORT 🔴"]:
                        # 1. Sprawdzenie limitu otwartych pozycji
                        current_pos_count = len([p for p in exchange.fetch_positions() if float(p.get("contracts", 0) or p.get("size", 0) or 0) > 0])
                        
                        # 2. Sprawdzenie cooldownu (czy nie otworzyliśmy tej pary w ciągu ostatnich 5 minut)
                        now_ts = time.time()
                        last_trade_ts = st.session_state.symbol_cooldown.get(sym, 0)
                        
                        if current_pos_count < max_active_positions and (now_ts - last_trade_ts > 300):
                            try:
                                # Ustalenie kierunku i dźwigni
                                side = "buy" if "LONG" in signal else "sell"
                                target_leverage = manual_leverage if leverage_mode == "Ręczna / Stała" else get_smart_leverage(last_row["adx"], 15, max_allowed_leverage)
                                
                                # Ustawienie dźwigni na giełdzie dla danej pary
                                try:
                                    exchange.set_leverage(target_leverage, sym)
                                except Exception:
                                    pass # Niektóre giełdy wyrzucają błąd, jeśli dźwignia jest już ustawiona
                                
                                # Wyliczenie wielkości pozycji w monetach (z uwzględnieniem mnożnika interwału)
                                tf_mult = params.get("capital_multiplier", 1.0)
                                allocated_usdt = calculate_risk_based_allocation(
                                    free_balance=free_usdt,
                                    entry_price=last_row["close"],
                                    stop_loss_price=last_row["close"] * (0.98 if side == "buy" else 1.02),
                                    max_single_limit=max_usdt_per_pos,
                                    tf_multiplier=tf_mult
                                )
                                
                                # Obliczenie ilości kontraktów (amount)
                                amount = (allocated_usdt * target_leverage) / last_row["close"]
                                
                                # Sformatowanie ilości zgodnie z precyzją giełdy
                                amount_formatted = float(exchange.amount_to_precision(sym, amount))
                                
                                if amount_formatted > 0:
                                    # ZŁOŻENIE ZLECENIA RYNKOWEGO (MARKET ORDER)
                                    order = exchange.create_order(
                                        symbol=sym,
                                        type="market",
                                        side=side,
                                        amount=amount_formatted
                                    )
                                    
                                    # Zapisanie czasu ostatniej transakcji dla cooldownu
                                    st.session_state.symbol_cooldown[sym] = now_ts
                                    
                                    # Dodanie wpisu do historii transakcji w UI
                                    st.session_state.trade_history.insert(0, {
                                        "Czas": datetime.now().strftime("%H:%M:%S"),
                                        "Symbol": sym,
                                        "Interwał": tf,
                                        "Typ": signal,
                                        "Cena": last_row["close"],
                                        "Ilość": amount_formatted,
                                        "Wartość USDT": round(allocated_usdt * target_leverage, 2)
                                    })
                                    
                                    st.toast(f"🚀 Otwarto pozycję {signal} na {sym} (Ilość: {amount_formatted})!")
                            except Exception as exec_err:
                                st.error(f"❌ Błąd składania zlecenia na {sym}: {exec_err}")
                except Exception:
                    continue
    except Exception as e:
        st.error(f"Błąd podczas skanowania giełdy: {e}")

if scanner_rows:
    st.dataframe(pd.DataFrame(scanner_rows), use_container_width=True)
else:
    st.info(t("no_scanner"))

# ==============================================================================
# POSITIONS MONITOR & TRADE HISTORY
# ==============================================================================
st.subheader(t("active_positions"))
active_positions_found = False

if exchange and is_user_paid():
    try:
        positions = exchange.fetch_positions()
        pos_data = []
        for p in positions:
            size = float(p.get("contracts", 0) or p.get("size", 0) or 0)
            if size > 0:
                active_positions_found = True
                pnl = float(p.get("unrealizedPnl", 0.0) or 0.0)
                entry = float(p.get("entryPrice", 0.0) or 0.0)
                mark = float(p.get("markPrice", 0.0) or 0.0)
                pos_data.append({
                    "Symbol": p.get("symbol"),
                    "Strona": p.get("side", "").upper(),
                    "Wielkość": size,
                    "Cena Wejścia": entry,
                    "Cena Mark": mark,
                    "Niezrealizowany PnL (USDT)": round(pnl, 2),
                })
        if pos_data:
            st.dataframe(pd.DataFrame(pos_data), use_container_width=True)
    except Exception:
        pass

if not active_positions_found:
    st.info(t("no_positions"))

st.subheader(t("trade_history"))
if st.session_state.trade_history:
    st.dataframe(pd.DataFrame(st.session_state.trade_history), use_container_width=True)
else:
    st.info(t("no_history"))

# ==============================================================================
# ADMIN PANEL (FOR MANAGING USERS)
# ==============================================================================
if is_user_admin():
    st.markdown("---")
    st.subheader(t("admin_panel"))
    
    conn = sqlite3.connect(DB_FILE, timeout=30.0)
    users_df = pd.read_sql_query("SELECT id, email, is_admin, stripe_paid FROM users", conn)
    conn.close()
    
    st.dataframe(users_df, use_container_width=True)
    
    col_a1, col_a2 = st.columns(2)
    with col_a1:
        target_user_id = st.number_input("ID Użytkownika do zmiany statusu", min_value=1, step=1)
        new_status = st.selectbox("Status Subskrypcji", [1, 0], format_func=lambda x: "Aktywna (1)" if x == 1 else "Nieaktywna (0)")
        
        if st.button("Zaktualizuj Subskrypcję"):
            conn = sqlite3.connect(DB_FILE, timeout=30.0)
            cursor = conn.cursor()
            cursor.execute("UPDATE users SET stripe_paid = ? WHERE id = ?", (new_status, target_user_id))
            conn.commit()
            conn.close()
            st.success(f"Zaktualizowano status subskrypcji dla użytkownika ID {target_user_id}!")
            st.rerun()

# ==============================================================================
# MEMORY CLEANUP & AUTOMATIC RERUN LOOP
# ==============================================================================
gc.collect()
time.sleep(1)
st.rerun()

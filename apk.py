from datetime import datetime
import hashlib
import hmac
import os
import sqlite3
import time
import gc
import json
import ccxt
import numpy as np
import pandas as pd
import streamlit as st
import stripe

# ============================================================
# KONFIGURACJA
# ============================================================
st.set_page_config(
    page_title="Multi-Exchange Futures SaaS",
    layout="wide",
)
DB_FILE = "users.db"
ALLOW_TEST_ACTIVATION = os.getenv("ALLOW_TEST_ACTIVATION", "0") == "1"

STRIPE_SECRET_KEY = os.getenv("STRIPE_SECRET_KEY", "")
STRIPE_PRICE_ID = os.getenv("STRIPE_PRICE_ID", "")
STRIPE_CHECKOUT_FALLBACK = os.getenv(
    "STRIPE_CHECKOUT_FALLBACK",
    "https://buy.stripe.com/8x2dRa4CbdaXfSAf6V3oA03",
)
if not STRIPE_SECRET_KEY:
    try:
        STRIPE_SECRET_KEY = st.secrets.get("STRIPE_SECRET_KEY", "")
        STRIPE_PRICE_ID = st.secrets.get("STRIPE_PRICE_ID", STRIPE_PRICE_ID)
        STRIPE_CHECKOUT_FALLBACK = st.secrets.get(
            "STRIPE_CHECKOUT_FALLBACK",
            STRIPE_CHECKOUT_FALLBACK,
        )
    except Exception:
        pass
if STRIPE_SECRET_KEY:
    stripe.api_key = STRIPE_SECRET_KEY

ADMIN_EMAILS = [
    "marekja57@wp.pl",
    "admin@bot-bitget.pl",
]

# ============================================================
# TŁUMACZENIA
# ============================================================
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
        "bot_control": "🤖 Panel Sterowania Botami MTF",
        "max_pairs": "Liczba par Futures do skanowania",
        "kill_switch": "🔴 ZAMKNIJ WSZYSTKO (KILL SWITCH)",
        "wallet_futures": "🔵 Portfel Futures",
        "free_balance": "Wolne",
        "session_results": "📊 Wyniki Sesji (PnL %)",
        "pnl_usdt": "PnL USDT",
        "slots_futures": "📈 Sloty Futures",
        "active_max": "Aktywne / Maksymalne",
        "session_time": "⏱ Czas Sesji",
        "market_scanner_results": "📊 Wyniki Skanera Rynkowego",
        "active_positions": "📈 Aktywne Pozycje Futures",
        "trade_history": "📜 Historia Ostatnich Transakcji",
        "admin_panel": "👑 Panel Administratora (Użytkownicy)",
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
        "bot_control": "🤖 Multi-Timeframe Bot Control Panel",
        "max_pairs": "Number of Futures pairs to scan",
        "kill_switch": "🔴 CLOSE ALL (KILL SWITCH)",
        "wallet_futures": "🔵 Futures Wallet",
        "free_balance": "Free",
        "session_results": "📊 Session Results (PnL %)",
        "pnl_usdt": "PnL USDT",
        "slots_futures": "📈 Futures Slots",
        "active_max": "Active / Maximum",
        "session_time": "⏱ Session Time",
        "market_scanner_results": "📊 Market Scanner Results",
        "active_positions": "📈 Active Futures Positions",
        "trade_history": "📜 Recent Trade History",
        "admin_panel": "👑 Admin Panel (Users)",
        "no_positions": "No open futures positions.",
        "no_history": "No recorded trades in this session.",
        "no_scanner": "No active MTF bots or scanner results.",
    },
}

def t(key):
    lang = st.session_state.get("lang", "Polski")
    return TRANSLATIONS.get(lang, TRANSLATIONS["Polski"]).get(key, key)

# ============================================================
# SESSION STATE
# ============================================================
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

# ============================================================
# FUNKCJE POMOCNICZE
# ============================================================
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
            candidate = hashlib.sha256(
                (salt + password).encode("utf-8")
            ).hexdigest()
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
            """ CREATE TABLE IF NOT EXISTS users ( id INTEGER PRIMARY KEY AUTOINCREMENT, email TEXT UNIQUE, password TEXT, is_admin INTEGER DEFAULT 0, stripe_paid INTEGER DEFAULT 0, api_key TEXT, secret_key TEXT, passphrase TEXT ) """
        )
        cursor.execute(
            """ CREATE TABLE IF NOT EXISTS user_mtf_settings ( user_id INTEGER PRIMARY KEY, settings_json TEXT NOT NULL, updated_at TEXT NOT NULL, FOREIGN KEY(user_id) REFERENCES users(id) ) """
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
                cursor.execute(
                    f"ALTER TABLE users ADD COLUMN {col} {col_type}"
                )
            except sqlite3.OperationalError:
                pass
        for adm_email in ADMIN_EMAILS:
            cursor.execute(
                """ UPDATE users SET is_admin = 1, stripe_paid = 1 WHERE LOWER(TRIM(email)) = ? """,
                (adm_email,),
            )
        conn.commit()
    finally:
        conn.close()

def mtfdefault_settings():
    return {
        tf: dict(values)
        for tf, values in DEFAULT_TF_VALUES.items()
    }

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
            "mode": st.session_state.get(
                f"radio_mode_{tf}", "Automatyczny"
            ),
            "ema_fast": int(
                st.session_state.get(
                    f"ema_f_{tf}", DEFAULT_TF_VALUES[tf]["ema_fast"]
                )
            ),
            "ema_slow": int(
                st.session_state.get(
                    f"ema_s_{tf}", DEFAULT_TF_VALUES[tf]["ema_slow"]
                )
            ),
            "adx": float(
                st.session_state.get(
                    f"adx_{tf}", DEFAULT_TF_VALUES[tf]["adx"]
                )
            ),
            "max_rsi": float(
                st.session_state.get(
                    f"max_rsi_{tf}", DEFAULT_TF_VALUES[tf]["max_rsi"]
                )
            ),
            "min_rsi": float(
                st.session_state.get(
                    f"min_rsi_{tf}", DEFAULT_TF_VALUES[tf]["min_rsi"]
                )
            ),
            "cap_mult": float(
                st.session_state.get(
                    f"cap_mult_{tf}", DEFAULT_TF_VALUES[tf]["cap_mult"]
                )
            ),
        }
    try:
        conn = sqlite3.connect(DB_FILE, timeout=30.0)
        conn.execute(
            """ INSERT INTO user_mtf_settings (user_id, settings_json, updated_at) VALUES (?, ?, ?) ON CONFLICT(user_id) DO UPDATE SET settings_json = excluded.settings_json, updated_at = excluded.updated_at """,
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
            line_items=[
                {
                    "price": price_id,
                    "quantity": 1,
                }
            ],
            mode="payment",
            success_url="https://bot-bitget.pl/?success=true",
            cancel_url="https://bot-bitget.pl/?success=false",
            customer_email=user_email,
        )
        if session and session.url:
            return session.url
    except Exception:
        pass
    return STRIPE_CHECKOUT_FALLBACK

def calculate_indicators(df, ema_fast=9, ema_slow=21, adx_period=14):
    df = df.copy()
    df["ema_fast"] = df["close"].ewm(
        span=ema_fast, adjust=False
    ).mean()
    df["ema_slow"] = df["close"].ewm(
        span=ema_slow, adjust=False
    ).mean()
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
    df["tr_smooth"] = df["tr"].ewm(
        alpha=alpha, adjust=False
    ).mean()
    df["plus_di_smooth"] = pd.Series(
        df["plus_dm"], index=df.index
    ).ewm(alpha=alpha, adjust=False).mean()
    df["minus_di_smooth"] = pd.Series(
        df["minus_dm"], index=df.index
    ).ewm(alpha=alpha, adjust=False).mean()
    tr_smooth = df["tr_smooth"].replace(0, np.nan)
    df["plus_di"] = 100 * (
        df["plus_di_smooth"] / tr_smooth
    )
    df["minus_di"] = 100 * (
        df["minus_di_smooth"] / tr_smooth
    )
    di_sum = (
        df["plus_di"] + df["minus_di"]
    ).replace(0, np.nan)
    df["dx"] = (
        100
        * abs(df["plus_di"] - df["minus_di"])
        / di_sum
    )
    df["adx"] = df["dx"].ewm(
        alpha=alpha, adjust=False
    ).mean()
    delta = df["close"].diff()
    gain = (
        delta.where(delta > 0, 0)
        .ewm(span=14, adjust=False)
        .mean()
    )
    loss = (
        -delta.where(delta < 0, 0)
        .ewm(span=14, adjust=False)
        .mean()
    )
    rs = gain / loss.replace(0, np.nan)
    df["rsi"] = 100 - (100 / (1 + rs))
    return df

def get_optimal_dynamic_parameters(df_recent, tf):
    try:
        closes = df_recent["close"].astype(float).values
        if len(closes) < 3:
            raise ValueError("Za mało danych")
        returns = np.diff(closes) / closes[:-1]
        volatility = np.std(returns) * np.sqrt(len(returns))
        if tf in ["1m", "5m"]:
            if volatility > 0.02:
                return {
                    "ema_fast": 5,
                    "ema_slow": 13,
                    "min_adx": 22.0,
                    "max_rsi": 72.0,
                    "min_rsi": 28.0,
                    "capital_multiplier": 0.6,
                }
            return {
                "ema_fast": 9,
                "ema_slow": 21,
                "min_adx": 26.0,
                "max_rsi": 75.0,
                "min_rsi": 25.0,
                "capital_multiplier": 0.8,
            }
        if tf in ["15m", "30m"]:
            if volatility > 0.03:
                return {
                    "ema_fast": 7,
                    "ema_slow": 18,
                    "min_adx": 24.0,
                    "max_rsi": 70.0,
                    "min_rsi": 30.0,
                    "capital_multiplier": 1.0,
                }
            return {
                "ema_fast": 10,
                "ema_slow": 25,
                "min_adx": 25.0,
                "max_rsi": 78.0,
                "min_rsi": 22.0,
                "capital_multiplier": 1.2,
            }
        return {
            "ema_fast": 12,
            "ema_slow": 26,
            "min_adx": 20.0,
            "max_rsi": 80.0,
            "min_rsi": 20.0,
            "capital_multiplier": 2.5,
        }
    except Exception:
        return {
            "ema_fast": 9,
            "ema_slow": 21,
            "min_adx": 25.0,
            "max_rsi": 75.0,
            "min_rsi": 25.0,
            "capital_multiplier": 1.0,
        }

def blend_params(base, opt, base_weight=0.5):
    w = max(0.0, min(1.0, float(base_weight)))
    return {
        "ema_fast": max(
            1,
            int(round(
                base["ema_fast"] * w
                + opt["ema_fast"] * (1 - w)
            )),
        ),
        "ema_slow": max(
            2,
            int(round(
                base["ema_slow"] * w
                + opt["ema_slow"] * (1 - w)
            )),
        ),
        "min_adx": round(
            base["min_adx"] * w
            + opt["min_adx"] * (1 - w),
            2,
        ),
        "max_rsi": round(
            base["max_rsi"] * w
            + opt["max_rsi"] * (1 - w),
            2,
        ),
        "min_rsi": round(
            base["min_rsi"] * w
            + opt["min_rsi"] * (1 - w),
            2,
        ),
        "capital_multiplier": round(
            base["capital_multiplier"] * w
            + opt["capital_multiplier"] * (1 - w),
            2,
        ),
    }

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
                "createOrder": {
                    "createMarketBuyOrderRequiresPrice": False
                },
            },
        }
        if ex_id in ["bitget", "okx"] and pass_k:
            config["password"] = pass_k
        return exchange_class(config)
    except Exception:
        return None

def calculate_risk_based_allocation(
    free_balance,
    entry_price,
    stop_loss_price,
    risk_percentage=0.01,
    leverage=1,
    max_single_limit=50.0,
    tf_multiplier=1.0,
):
    if free_balance <= 0 or entry_price <= 0 or stop_loss_price <= 0:
        return max(
            5.0 * tf_multiplier,
            min(
                max_single_limit * tf_multiplier,
                free_balance * 0.1 * tf_multiplier,
            ),
        )
    scaled_single_limit = max_single_limit * tf_multiplier
    max_risk_amount = free_balance * risk_percentage * tf_multiplier
    risk_distance_pct = abs(entry_price - stop_loss_price) / entry_price
    if risk_distance_pct == 0:
        risk_distance_pct = 0.02
    position_notional_value = max_risk_amount / risk_distance_pct
    max_allowed_value = min(
        free_balance * leverage * 0.9,
        scaled_single_limit * leverage,
    )
    final_notional = min(
        position_notional_value,
        max_allowed_value,
    )
    return max(
        5.0 * tf_multiplier,
        final_notional,
    )

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

# ============================================================
# BAZA DANYCH
# ============================================================
init_db()

# ============================================================
# STRIPE
# ============================================================
stripe_price_id_val = get_secret("STRIPE_PRICE_ID", STRIPE_PRICE_ID)
if STRIPE_SECRET_KEY:
    stripe.api_key = STRIPE_SECRET_KEY

# ============================================================
# AKTYWACJA POWROTU ZE STRIPE
# ============================================================
if st.query_params.get("success") == "true":
    if st.session_state.logged_in and st.session_state.user_id:
        st.session_state.stripe_paid = True
        try:
            conn = sqlite3.connect(DB_FILE, timeout=30.0)
            cursor = conn.cursor()
            cursor.execute(
                """ UPDATE users SET stripe_paid = 1 WHERE id = ? """,
                (st.session_state.user_id,),
            )
            conn.commit()
            conn.close()
        except Exception:
            pass
    st.success("🎉 Płatność zakończona sukcesem! Twoja subskrypcja została aktywowana.")
    st.query_params.clear()

# ============================================================
# CSS
# ============================================================
st.markdown(
    """ <style> @import url('https://fonts.googleapis.com/css2?family=Bungee+Inline&family=Cinzel:wght@700&display=swap'); .stApp { background-color: #0d0b0a; } section[data-testid="stSidebar"] { background-color: #141110; border-right: 2px solid #3d2f1f; } .metrics-row { display: flex; flex-direction: row; flex-wrap: nowrap !important; gap: 14px; width: 100%; margin-bottom: 10px; } .metric-card { flex: 1; min-width: 0; border: 2px solid #f3d57a; border-radius: 10px; padding: 12px 14px; background-color: rgba(243, 213, 122, 0.03); box-shadow: 0 4px 12px rgba(0, 0, 0, 0.2); } .metric-label { font-family: 'Cinzel', serif; color: #f3d57a; font-size: 0.85rem; font-weight: 700; margin-bottom: 6px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; } .metric-value { font-size: 1.4rem; font-weight: bold; color: #ffffff; margin-bottom: 4px; } .metric-delta { font-size: 0.75rem; color: #e6c687; } .hero-wrapper { display: flex; align-items: center; justify-content: center; width: 100%; padding-top: 50px; padding-bottom: 20px; } .retro-ornate-frame { position: relative; background: radial-gradient(circle, #221a14 0%, #110d0a 100%); border: 6px double #f3d57a; padding: 40px 30px; border-radius: 16px; box-shadow: 0 0 50px rgba(243, 213, 122, 0.4), inset 0 0 35px rgba(0, 0, 0, 0.9); width: 100%; max-width: 600px; text-align: center; } .retro-vintage-title { font-family: 'Bungee Inline', cursive, sans-serif; font-size: 3rem; color: #f3d57a; letter-spacing: 4px; text-shadow: 4px 4px 0px #8b0000, 8px 8px 0px rgba(0,0,0,0.95); margin-bottom: 10px; } .retro-subtitle { font-family: 'Cinzel', serif; color: #e6c687; font-size: 1.1rem; letter-spacing: 2px; margin-bottom: 25px; } div.stButton > button { background: linear-gradient( 135deg, #1e4d2b 0%, #0f2b17 100% ) !important; color: #f3d57a !important; border: 2px solid #f3d57a !important; font-family: 'Cinzel', serif !important; font-weight: 700 !important; font-size: 1rem !important; padding: 10px 24px !important; border-radius: 8px !important; box-shadow: 0 4px 15px rgba(0, 0, 0, 0.6) !important; transition: all 0.3s ease !important; } div.stButton > button:hover { background: linear-gradient( 135deg, #28663a 0%, #163d22 100% ) !important; border-color: #ffe89d !important; color: #ffe89d !important; box-shadow: 0 0 20px rgba(243, 213, 122, 0.4) !important; transform: translateY(-2px); } </style> """,
    unsafe_allow_html=True,
)

# ============================================================
# LOGOWANIE / REJESTRACJA
# ============================================================
if not st.session_state.logged_in:
    st.markdown(
        f""" <div class="hero-wrapper"> <div class="retro-ornate-frame"> <div class="retro-vintage-title"> {t("title")} </div> <div class="retro-subtitle"> {t("subtitle")} </div> """,
        unsafe_allow_html=True,
    )
    tab_login, tab_register = st.tabs([t("login_tab"), t("register_tab")])

    with tab_login:
        st.markdown(
            f""" <p style='color:#f3d57a;font-family:Cinzel,serif;'> {t('login_tab')} </p> """,
            unsafe_allow_html=True,
        )
        login_email = st.text_input(t("email_label"), key="log_email")
        login_pass = st.text_input(t("pass_label"), type="password", key="log_pass")
        if st.button(t("login_btn"), use_container_width=True):
            conn = sqlite3.connect(DB_FILE, timeout=30.0)
            cursor = conn.cursor()
            cursor.execute(
                """ SELECT id, email, password, is_admin, stripe_paid, api_key, secret_key, passphrase FROM users WHERE LOWER(TRIM(email)) = ? """,
                (login_email.strip().lower(),),
            )
            user_row = cursor.fetchone()
            conn.close()
            if user_row and verify_password(login_pass, user_row[2]):
                user_email_str = user_row[1].strip().lower()
                is_admin_flag = user_email_str in ADMIN_EMAILS or bool(user_row[3])
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
                        cur_up.execute(
                            """ UPDATE users SET password = ? WHERE id = ? """,
                            (hash_password(login_pass), user_row[0]),
                        )
                        conn_up.commit()
                        conn_up.close()
                    except Exception:
                        pass

                load_mtf_settings_for_user(user_row[0])
                st.success(t("login_success"))
                st.rerun()
            else:
                st.error(t("login_error"))

    with tab_register:
        st.markdown(
            f""" <p style='color:#f3d57a;font-family:Cinzel,serif;'> {t('register_tab')} </p> """,
            unsafe_allow_html=True,
        )
        reg_email = st.text_input(t("email_label"), key="reg_email")
        reg_pass = st.text_input(t("pass_label"), type="password", key="reg_pass")
        if st.button(t("register_btn"), use_container_width=True):
            if reg_email and reg_pass:
                conn = sqlite3.connect(DB_FILE, timeout=30.0)
                cursor = conn.cursor()
                try:
                    cursor.execute(
                        "INSERT INTO users (email, password) VALUES (?, ?)",
                        (reg_email.strip().lower(), hash_password(reg_pass)),
                    )
                    conn.commit()
                    st.success(t("reg_success"))
                except sqlite3.IntegrityError:
                    st.error(t("reg_error_exists"))
                finally:
                    conn.close()
            else:
                st.error(t("reg_error_fill"))

    st.markdown("</div></div>", unsafe_allow_html=True)
    st.stop()  # Zatrzymanie wykonania dla nieautoryzowanych

# ============================================================
# BRAMKA SUBSKRYPCJI (STRIPE GUARD)
# ============================================================
if not is_user_paid():
    st.title(t("sub_zone"))
    st.warning(t("sub_inactive"))

    checkout_url = create_stripe_checkout_session(
        st.session_state.user_email,
        stripe_price_id_val,
    )

    st.markdown(
        """
        <div style="background-color: #141110; border: 2px solid #f3d57a; border-radius: 10px; padding: 25px; text-align: center; margin-top: 20px;">
            <h2 style="color: #f3d57a; font-family: 'Cinzel', serif;">Wymagana Aktywna Subskrypcja</h2>
            <p style="color: #ffffff; font-size: 1.1rem;">Twoje konto nie posiada aktywnego abonamentu na korzystanie z bota Bitget Futures.</p>
        </div>
        <br>
        """,
        unsafe_allow_html=True,
    )

    st.link_button(t("pay_btn"), checkout_url, use_container_width=True)
    st.stop()  # Zatrzymanie wykonania aplikacji dla osób bez subskrypcji

# ============================================================
# TUTAJ ZACZYNA SIĘ GŁÓWNY DASHBOARD BOTA (DLA OPŁACONYCH)
# ============================================================
# ============================================================
# BRAMKA SUBSKRYPCJI (STRIPE GUARD) - DOKOŃCZENIE
# ============================================================
if not is_user_paid():
    st.title(t("sub_zone"))
    st.warning(t("sub_inactive"))

    checkout_url = create_stripe_checkout_session(
        st.session_state.user_email,
        stripe_price_id_val,
    )

    st.markdown(
        f"""
        <div style="background-color: #141110; border: 2px solid #f3d57a; border-radius: 10px; padding: 25px; text-align: center;">
            <h3 style="color: #f3d57a; font-family: 'Cinzel', serif;">{t("sub_inactive")}</h3>
            <p style="color: #ffffff;">Uzyskaj pełny dostęp do autonomicznego bota handlowego Futures, skanera rynkowego oraz modułu zarządzania ryzykiem.</p>
            <a href="{checkout_url}" target="_blank" style="display: inline-block; background: linear-gradient(135deg, #1e4d2b 0%, #0f2b17 100%); color: #f3d57a; border: 2px solid #f3d57a; padding: 12px 30px; text-decoration: none; border-radius: 8px; font-weight: bold; font-family: 'Cinzel', serif; margin-top: 15px;">
                {t("pay_btn")}
            </a>
        </div>
        """,
        unsafe_allow_html=True,
    )

    if ALLOW_TEST_ACTIVATION:
        st.write("")
        if st.button("🧪 Aktywuj konto testowo (Tryb Dev)"):
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
            st.rerun()

    st.stop()

# ============================================================
# PASEK BOCZNY (SIDEBAR) & USTAWIENIA API
# ============================================================
with st.sidebar:
    st.markdown(f"### {t('title')}")
    st.caption(t("subtitle"))
    
    st.session_state.lang = st.selectbox(
        "🌐 Język / Language",
        ["Polski", "English"],
        index=0 if st.session_state.lang == "Polski" else 1,
    )

    st.divider()

    if is_user_admin():
        st.info(t("sidebar_role_admin"))
    else:
        st.success(t("sidebar_role_client"))

    st.write(f"👤 **{st.session_state.user_email}**")

    if st.button(t("logout_btn"), use_container_width=True):
        st.session_state.logged_in = False
        st.session_state.user_id = None
        st.session_state.user_email = ""
        st.session_state.is_admin = False
        st.session_state.stripe_paid = False
        st.rerun()

    st.divider()
    st.subheader(t("exchange_settings"))

    st.session_state.selected_exchange = st.selectbox(
        t("select_exchange"),
        ["Bitget", "Binance", "Bybit", "OKX"],
        index=0,
    )

    api_key_input = st.text_input("API Key", value=st.session_state.api_key, type="password")
    secret_key_input = st.text_input("Secret Key", value=st.session_state.secret_key, type="password")
    passphrase_input = st.text_input("Passphrase / API Password", value=st.session_state.passphrase, type="password")

    if st.button(t("save_keys_btn"), use_container_width=True):
        if api_key_input and secret_key_input:
            st.session_state.api_key = api_key_input
            st.session_state.secret_key = secret_key_input
            st.session_state.passphrase = passphrase_input
            try:
                conn = sqlite3.connect(DB_FILE, timeout=30.0)
                cursor = conn.cursor()
                cursor.execute(
                    """ UPDATE users SET api_key = ?, secret_key = ?, passphrase = ? WHERE id = ? """,
                    (api_key_input, secret_key_input, passphrase_input, st.session_state.user_id),
                )
                conn.commit()
                conn.close()
                st.success(f"{t('keys_saved')} {st.session_state.selected_exchange}")
            except Exception as e:
                st.error(f"Błąd zapisu w bazie: {e}")
        else:
            st.warning(t("keys_error"))

# ============================================================
# INICJALIZACJA POŁĄCZENIA Z GIEŁDĄ I DANYCH SALDA
# ============================================================
exchange = get_exchange(
    st.session_state.api_key,
    st.session_state.secret_key,
    st.session_state.passphrase,
    st.session_state.selected_exchange,
)

free_usdt = 0.0
total_usdt = 0.0
open_positions = []

if exchange:
    try:
        balance = exchange.fetch_balance({"type": "swap"})
        free_usdt = float(balance.get("USDT", {}).get("free", 0.0))
        total_usdt = float(balance.get("USDT", {}).get("total", free_usdt))
        
        if not st.session_state.session_baseline_locked:
            st.session_state.session_start_balance = total_usdt
            st.session_state.session_baseline_locked = True
            
        raw_positions = exchange.fetch_positions()
        open_positions = [
            p for p in raw_positions 
            if float(p.get("contracts", 0) or p.get("size", 0) or 0) > 0
        ]
    except Exception as e:
        st.sidebar.error(f"⚠️ Błąd połączenia z giełdą: {e}")

# ============================================================
# KARTY WSKAŹNIKÓW (METRICS ROW)
# ============================================================
pnl_usdt = total_usdt - st.session_state.session_start_balance
pnl_pct = (pnl_usdt / st.session_state.session_start_balance * 100.0) if st.session_state.session_start_balance > 0 else 0.0
session_duration = str(datetime.now() - st.session_state.session_start_time).split(".")[0]

st.markdown(
    f"""
    <div class="metrics-row">
        <div class="metric-card">
            <div class="metric-label">{t('wallet_futures')}</div>
            <div class="metric-value">${total_usdt:.2f}</div>
            <div class="metric-delta">{t('free_balance')}: ${free_usdt:.2f}</div>
        </div>
        <div class="metric-card">
            <div class="metric-label">{t('session_results')}</div>
            <div class="metric-value" style="color: {'#4caf50' if pnl_usdt >= 0 else '#f44336'};">{pnl_pct:+.2f}%</div>
            <div class="metric-delta">{t('pnl_usdt')}: ${pnl_usdt:+.2f}</div>
        </div>
        <div class="metric-card">
            <div class="metric-label">{t('slots_futures')}</div>
            <div class="metric-value">{len(open_positions)}</div>
            <div class="metric-delta">{t('active_max')}</div>
        </div>
        <div class="metric-card">
            <div class="metric-label">{t('session_time')}</div>
            <div class="metric-value" style="font-size: 1.1rem; margin-top: 6px;">{session_duration}</div>
            <div class="metric-delta">Start: {st.session_state.session_start_time.strftime('%H:%M:%S')}</div>
        </div>
    </div>
    """,
    unsafe_allow_html=True,
)

# ============================================================
# NASTAWY KAPITAŁU, RYZYKA I DŹWIGNI
# ============================================================
st.header(t("capital_risk"))
col_cap1, col_cap2 = st.columns(2)

with col_cap1:
    max_usdt_per_trade = st.number_input(
        t("max_single"),
        min_value=5.0,
        max_value=10000.0,
        value=50.0,
        step=5.0,
    )
    max_active_positions = st.slider(
        t("max_pos"),
        min_value=1,
        max_value=20,
        value=3,
    )

with col_cap2:
    st.subheader(t("roe_guard"))
    enable_roe = st.checkbox(t("enable_roe"), value=True)
    col_roe1, col_roe2 = st.columns(2)
    with col_roe1:
        sl_roe_pct = st.number_input(t("sl_roe"), min_value=1.0, max_value=500.0, value=15.0, step=1.0)
    with col_roe2:
        tp_roe_pct = st.number_input(t("tp_roe"), min_value=1.0, max_value=1000.0, value=30.0, step=1.0)

st.divider()

# Zarządzanie Dźwignią
st.subheader(t("leverage_mgmt"))
col_lev1, col_lev2 = st.columns(2)
with col_lev1:
    lev_mode = st.radio(t("lev_mode"), ["Dynamiczna (ADX Smart)", "Stała (Manualna)"], horizontal=True)
with col_lev2:
    if lev_mode == "Dynamiczna (ADX Smart)":
        max_allowed_lev = st.slider(t("max_allowed_lev"), min_value=2, max_value=125, value=15)
    else:
        manual_lev = st.slider(t("manual_lev"), min_value=1, max_value=125, value=10)

st.divider()

# ============================================================
# PANEL STEROWANIA BOTAMI MULTI-TIMEFRAME (MTF)
# ============================================================
st.header(t("bot_control"))

selected_tf_tabs = st.tabs([f"⏱ {tf}" for tf in AVAILABLE_TIMEFRAMES])

for idx, tf in enumerate(AVAILABLE_TIMEFRAMES):
    with selected_tf_tabs[idx]:
        st.markdown(f"#### Konfiguracja Interwału **{tf}**")
        
        mode_val = st.radio(
            "Tryb parametrów:",
            ["Automatyczny", "Ręczny"],
            key=f"radio_mode_{tf}",
            horizontal=True,
        )
        
        col_tf1, col_tf2, col_tf3 = st.columns(3)
        disabled_flag = (mode_val == "Automatyczny")
        
        with col_tf1:
            st.number_input("EMA Fast", min_value=2, max_value=100, key=f"ema_f_{tf}", disabled=disabled_flag)
            st.number_input("EMA Slow", min_value=5, max_value=200, key=f"ema_s_{tf}", disabled=disabled_flag)
        with col_tf2:
            st.number_input("Min ADX", min_value=5.0, max_value=80.0, key=f"adx_{tf}", disabled=disabled_flag)
            st.number_input("Mnożnik Kapitału", min_value=0.1, max_value=10.0, key=f"cap_mult_{tf}", disabled=disabled_flag)
        with col_tf3:
            st.number_input("Min RSI", min_value=5.0, max_value=50.0, key=f"min_rsi_{tf}", disabled=disabled_flag)
            st.number_input("Max RSI", min_value=50.0, max_value=95.0, key=f"max_rsi_{tf}", disabled=disabled_flag)

if st.button("💾 ZAPISZ DOMYŚLNE NASTAWY STRATEGII MTF", use_container_width=True):
    save_mtf_settings_for_user(st.session_state.user_id)
    st.success("Pomyślnie zapisano preferencje wskaźników MTF!")

st.divider()

# ============================================================
# MODUŁ: DYNAMICZNY SKANER Z SUWAKIEKM (1 - 100 PAR)
# ============================================================
st.divider()
st.header("🔍 Skaner Rynku Live (Pełna Analiza Giełdy)")

if exchange:
    try:
        # 1. Pobranie WSZYSTKICH aktywnych par Futures USDT-M z Bitget
        markets = exchange.load_markets()
        all_usdt_pairs = [
            symbol for symbol, m in markets.items()
            if m.get('swap', False) and m.get('settle') == 'USDT' and m.get('active', True)
        ]
        
        # 2. Suwak wyboru liczby skanowanych par (od 1 do 100)
        max_limit = min(100, len(all_usdt_pairs)) if all_usdt_pairs else 100
        num_pairs = st.slider(
            "Liczba skanowanych par rynkowych (od 1 do 100):",
            min_value=1,
            max_value=max_limit,
            value=20,
            step=1
        )
        
        # Ograniczenie listy skanowania do liczby wybranej na suwaku
        scan_list = all_usdt_pairs[:num_pairs]

        col_scan1, col_scan2, col_scan3 = st.columns(3)
        with col_scan1:
            st.metric(label="Wszystkie Pary USDT-M na Giełdzie", value=f"{len(all_usdt_pairs)} par")
        with col_scan2:
            st.metric(label="Wybranych do Skanowania", value=f"{len(scan_list)} par")
        with col_scan3:
            st.metric(label="Ostatni Skan", value=datetime.now().strftime("%H:%M:%S"))

        scanner_rows = []

        # Sprawdzenie limitu pozycji
        active_positions_count = len(st.session_state.get('active_positions', []))
        max_allowed_slots = st.session_state.get('max_slots', 3)
        has_free_slots = active_positions_count < max_allowed_slots

        for symbol in scan_list:
            try:
                timeframe_scan = "1h"
                ohlcv = exchange.fetch_ohlcv(symbol, timeframe=timeframe_scan, limit=60)
                
                if ohlcv and len(ohlcv) >= 50:
                    df = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
                    
                    last_price = df['close'].iloc[-1]
                    last_vol = df['volume'].iloc[-1]
                    
                    # Średnie EMA
                    ema_fast = df['close'].ewm(span=20).mean().iloc[-1]
                    ema_slow = df['close'].ewm(span=50).mean().iloc[-1]
                    
                    # Wskaźnik RSI
                    delta = df['close'].diff()
                    gain = (delta.where(delta > 0, 0)).rolling(14).mean()
                    loss = (-delta.where(delta < 0, 0)).rolling(14).mean()
                    rs = gain / loss
                    rsi = float((100 - (100 / (1 + rs))).iloc[-1])
                    
                    # Wskaźnik ADX (siła trendu)
                    high_low = df['high'] - df['low']
                    adx_est = (high_low.rolling(14).mean() / df['close'].rolling(14).mean()).iloc[-1] * 1000
                    
                    # Parametry filtrowania bota
                    min_adx_req = 25.0
                    max_rsi_req = 75.0
                    min_rsi_req = 27.0
                    
                    # Diagnoza algorytmu:
                    if not has_free_slots:
                        status_msg = "⏸️ BLOKADA: Limit slotów pozycji osiągnięty"
                    elif rsi > max_rsi_req:
                        status_msg = f"⚠️ ODRZUCONO: RSI za wysokie ({rsi:.1f} > {max_rsi_req})"
                    elif rsi < min_rsi_req:
                        status_msg = f"⚠️ ODRZUCONO: RSI za niskie ({rsi:.1f} < {min_rsi_req})"
                    elif adx_est < min_adx_req:
                        status_msg = f"⏳ BRAK TRENDU: ADX za niski ({adx_est:.1f} < {min_adx_req})"
                    elif ema_fast > ema_slow:
                        status_msg = "🟢 EGZEKUCJA: Warunki LONG spełnione!"
                    elif ema_fast < ema_slow:
                        status_msg = "🔴 EGZEKUCJA: Warunki SHORT spełnione!"
                    else:
                        status_msg = "⚪ NEUTRALNY: Rynek bez sygnału"

                    vol_str = f"{last_vol/1_000_000:.2f}M" if last_vol >= 1_000_000 else f"{last_vol/1_000:.1f}K"

                    scanner_rows.append({
                        "Symbol": symbol,
                        "Cena": f"${last_price:.4f}",
                        "Wolumen": vol_str,
                        "EMA 20/50": "Wzrostowy" if ema_fast > ema_slow else "Spadkowy",
                        "RSI": f"{rsi:.1f}",
                        "ADX": f"{adx_est:.1f}",
                        "Decyzja Algorytmu": status_msg
                    })
            except Exception:
                continue

        if scanner_rows:
            st.dataframe(pd.DataFrame(scanner_rows), use_container_width=True, hide_index=True)
        else:
            st.info("Trwa aktualizacja bazy par giełdowych...")

    except Exception as e:
        st.error(f"Błąd komunikacji z API giełdy: {e}")

# ============================================================
# AKTYWNE POZYCJE I KILL SWITCH
# ============================================================
col_pos_head, col_kill = st.columns([3, 1])
with col_pos_head:
    st.header(t("active_positions"))
with col_kill:
    if st.button(t("kill_switch"), use_container_width=True):
        if exchange and open_positions:
            closed_count = 0
            for pos in open_positions:
                try:
                    sym = pos.get("symbol")
                    side = pos.get("side")
                    amt = float(pos.get("contracts", 0) or pos.get("size", 0))
                    close_side = "sell" if side in ["long", "buy"] else "buy"
                    exchange.create_order(sym, "market", close_side, amt, params={"reduceOnly": True})
                    closed_count += 1
                except Exception as ex:
                    st.error(f"Błąd zamykania pozycji {pos.get('symbol')}: {ex}")
            st.success(f"Zamknięto {closed_count} pozycji!")
            st.rerun()

if open_positions:
    pos_data = []
    for p in open_positions:
        pos_data.append({
            "Symbol": p.get("symbol"),
            "Strona": p.get("side"),
            "Wielkość": p.get("contracts") or p.get("size"),
            "Cena Wejścia": p.get("entryPrice"),
            "Cena Rynkowa": p.get("markPrice"),
            "Unrealized PnL": p.get("unrealizedPnl"),
            "Dźwignia": p.get("leverage"),
        })
    st.dataframe(pd.DataFrame(pos_data), use_container_width=True)
else:
    st.info(t("no_positions"))

st.divider()

# ============================================================
# HISTORIA TRANSAKCJI SESJI
# ============================================================
st.header(t("trade_history"))
if st.session_state.trade_history:
    st.dataframe(pd.DataFrame(st.session_state.trade_history), use_container_width=True)
else:
    st.info(t("no_history"))
# ============================================================
# MODUŁ: INSTRUKCJA OBSŁUGI I REGULAMIN (ELEGANCKE KAFELKI)
# ============================================================
st.divider()

# Stylizacja dla zielono-złotych rozwijanych kafli
st.markdown("""
<style>
/* Ciemnozielone kafelki ze złotym obramowaniem */
div[data-testid="stExpander"] {
    border: 2px solid #f3d57a !important;
    border-radius: 10px !important;
    background: linear-gradient(135deg, #1e4d2b 0%, #0f2b17 100%) !important;
    margin-bottom: 15px !important;
    box-shadow: 0 4px 10px rgba(0, 0, 0, 0.3);
}

/* Styl nagłówka po rozwinęciu/zwinięciu */
div[data-testid="stExpander"] summary {
    color: #f3d57a !important;
    font-weight: bold !important;
    font-size: 1.05rem !important;
    font-family: 'Cinzel', serif, sans-serif !important;
    padding: 12px 18px !important;
}

div[data-testid="stExpander"] summary:hover {
    color: #ffffff !important;
}

/* Wnętrze rozwiniętej kafelki */
div[data-testid="stExpander"] div[role="region"] {
    background-color: #0b1a0e !important;
    color: #e0e0e0 !important;
    padding: 20px !important;
    border-top: 1px solid #f3d57a !important;
    border-bottom-left-radius: 8px !important;
    border-bottom-right-radius: 8px !important;
}
</style>
""", unsafe_allow_html=True)

# ------------------------------------------------------------
# 1. INSTRUKCJA OBSŁUGI (SCHOWANA)
# ------------------------------------------------------------
with st.expander("📖 INSTRUKCJA OBSŁUGI SYSTEMU"):
    st.markdown("""
    #### 1. Autoryzacja i Połączenie z Giełdą
    * **Klucze API:** W panelu bocznym po lewej stronie wybierz odpowiednią giełdę (np. Bitget) i wprowadź dane dostępowe (*API Key*, *Secret Key*, *Passphrase*).
    * **Uprawnienia:** Upewnij się, że wygenerowany klucz API posiada aktywne uprawnienia do **Handlu Futures / Kontraktami Swap**. Ze względów bezpieczeństwa zachowaj wyłączoną opcję wypłat (*Withdrawal*).

    ---

    #### 2. Zarządzanie Kapitałem i Ochrona Portfela
    * **Maksymalny Kapitał na Pozycję:** Wyznacz dokładną kwotę w USDT alokowaną do pojedynczego zlecenia.
    * **Maksymalna Liczba Pozycji:** Ustal dopuszczalny limit jednocześnie otwartych transakcji w danej sesji.
    * **Moduł Ochrony ROE (SL / TP):** Automatyczny strażnik kapitału zamyka pozycję po osiągnięciu zadanego progu zysku (*Take Profit ROE*) lub dopuszczalnej straty (*Stop Loss ROE*).

    ---

    #### 3. Konfiguracja Strategii Multi-Timeframe (MTF)
    * **Wybór Interwałów:** Każda zakładka (od `1m` do `1D`) odpowiada za osobny horyzont czasowy analizy.
    * **Wyłączanie Handlu na Wybranych Interwałach:** Aby wykluczyć szum rynkowy (np. na niskich interwałach `1m`–`30m`), przełącz dany interwał w tryb **Ręczny**, ustaw **Mnożnik Kapitału na `0`** i kliknij **`💾 ZAPISZ DOMYŚLNE NASTAWY STRATEGII MTF`**.
    * **Filtracja Wskaźnikowa:** Algorytm weryfikuje układy średnich kroczących (EMA), wskaźnik siły trendu (ADX) oraz poziomy wyprzedania/przegrzania (RSI) przed złożeniem zlecenia.

    ---

    #### 4. Awaryjne Zamknięcie Pozycji (Kill Switch)
    * Przycisk **`ZAMKNIJ WSZYSTKO (KILL SWITCH)`** natychmiastowo likwiduje wszystkie aktywne pozycje Futures po aktualnej cenie rynkowej. Stosuj go w przypadku gwałtownych zawirowań rynkowych lub potrzeby szybkiego wyjścia z rynku.
    """)

# ------------------------------------------------------------
# 2. REGULAMIN SERWISU (SCHOWANY)
# ------------------------------------------------------------
with st.expander("📜 REGULAMIN SERWISU I NOTA PRAWNA"):
    st.markdown("""
    #### § 1. Charakterystyka Systemu
    1. Niniejsza aplikacja stanowi zaawansowany interfejs analityczno-transakcyjny przeznaczony do automatyzacji i wspomagania egzekucji strategii na rynku instrumentów pochodnych.
    2. System działa w pełni autonomicznie na podstawie parametrów i reguł zdefiniowanych bezpośrednio przez Użytkownika.

    ---

    #### § 2. Ostrzeżenie o Ryzyku Inwestycyjnym
    1. Handel kontraktami terminowymi Futures oraz korzystanie z dźwigni finansowej wiąże się z **wysokim poziomem ryzyka finansowego**, w tym z możliwością utraty całości zaangażowanego kapitału.
    2. Wskaźniki analizy technicznej stanowią jedynie narzędzie wspomagające i nie gwarantują stałej skuteczności w zmiennych warunkach rynkowych.
    3. Wyniki generowane przez system w ujęciu historycznym nie stanowią obietnicy ani gwarancji osiągnięcia analogicznych rezultatów w przyszłości.

    ---

    #### § 3. Wyłączenie Odpowiedzialności
    1. Oprogramowanie dostarczane jest w stanie takim, w jakim się znajduje (*As-Is*). Dostawca nie ponosi odpowiedzialności za:
       * Ewentualne straty finansowe wynikające z decyzji transakcyjnych podjętych przez algorytm.
       * Przerwy w łączności API, poślizgi cenowe (*slippage*) oraz opóźnienia w egzekucji zleceń powstałe po stronie giełdy.
       * Błędy wynikające z nieprawidłowego wprowadzenia kluczy autoryzacyjnych lub niewłaściwego ustawienia parametrów ryzyka.
    2. Treści zawarte w aplikacji nie stanowią rekomendacji inwestycyjnej ani doradztwa finansowego.
    """)

# ============================================================
# PANEL ADMINISTRATORA (ADMIN PANEL)
# ============================================================
if is_user_admin():
    st.divider()
    st.header(t("admin_panel"))
    
    conn = sqlite3.connect(DB_FILE, timeout=30.0)
    users_df = pd.read_sql_query(
        "SELECT id, email, is_admin, stripe_paid, api_key FROM users",
        conn,
    )
    conn.close()
    
    users_df["has_api"] = users_df["api_key"].apply(lambda x: "✅ Tak" if x else "❌ Brak")
    users_df_display = users_df.drop(columns=["api_key"])
    
    st.dataframe(users_df_display, use_container_width=True)
    
    st.subheader("🛠️ Zarządzanie Dostępem Użytkowników")
    col_adm1, col_adm2, col_adm3 = st.columns(3)
    
    with col_adm1:
        target_user_id = st.number_input("ID Użytkownika", min_value=1, step=1)
    with col_adm2:
        action = st.selectbox("Akcja", ["Aktywuj Subskrypcję", "Anuluj Subskrypcję", "Nadaj Admina", "Odbierz Admina"])
    with col_adm3:
        st.write("")
        st.write("")
        if st.button("Wykonaj Akcję"):
            conn = sqlite3.connect(DB_FILE, timeout=30.0)
            cursor = conn.cursor()
            if action == "Aktywuj Subskrypcję":
                cursor.execute("UPDATE users SET stripe_paid = 1 WHERE id = ?", (target_user_id,))
            elif action == "Anuluj Subskrypcję":
                cursor.execute("UPDATE users SET stripe_paid = 0 WHERE id = ?", (target_user_id,))
            elif action == "Nadaj Admina":
                cursor.execute("UPDATE users SET is_admin = 1 WHERE id = ?", (target_user_id,))
            elif action == "Odbierz Admina":
                cursor.execute("UPDATE users SET is_admin = 0 WHERE id = ?", (target_user_id,))
            conn.commit()
            conn.close()
            st.success(f"Pomyślnie zaktualizowano użytkownika ID {target_user_id}!")
            st.rerun()

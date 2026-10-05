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

try:
    STRIPE_SECRET_KEY = STRIPE_SECRET_KEY or st.secrets.get(
        "STRIPE_SECRET_KEY", ""
    )

    STRIPE_PRICE_ID = STRIPE_PRICE_ID or st.secrets.get(
        "STRIPE_PRICE_ID", ""
    )

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
# INTERWAŁY
# ============================================================

AVAILABLE_TIMEFRAMES = [
    "1m",
    "5m",
    "15m",
    "30m",
    "1h",
    "4h",
    "1d",
]


DEFAULT_TF_VALUES = {
    "1m": {
        "ema_fast": 9,
        "ema_slow": 21,
        "adx": 28.0,
        "max_rsi": 75.0,
        "min_rsi": 25.0,
        "cap_mult": 0.5,
    },
    "5m": {
        "ema_fast": 9,
        "ema_slow": 21,
        "adx": 28.0,
        "max_rsi": 75.0,
        "min_rsi": 25.0,
        "cap_mult": 0.8,
    },
    "15m": {
        "ema_fast": 9,
        "ema_slow": 21,
        "adx": 28.0,
        "max_rsi": 75.0,
        "min_rsi": 25.0,
        "cap_mult": 1.0,
    },
    "30m": {
        "ema_fast": 9,
        "ema_slow": 21,
        "adx": 28.0,
        "max_rsi": 75.0,
        "min_rsi": 25.0,
        "cap_mult": 1.5,
    },
    "1h": {
        "ema_fast": 9,
        "ema_slow": 21,
        "adx": 28.0,
        "max_rsi": 75.0,
        "min_rsi": 25.0,
        "cap_mult": 2.5,
    },
    "4h": {
        "ema_fast": 9,
        "ema_slow": 21,
        "adx": 28.0,
        "max_rsi": 75.0,
        "min_rsi": 20.0,
        "cap_mult": 4.0,
    },
    "1d": {
        "ema_fast": 9,
        "ema_slow": 21,
        "adx": 28.0,
        "max_rsi": 75.0,
        "min_rsi": 20.0,
        "cap_mult": 6.0,
    },
}


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

        "kill_switch": "🔴 ZAMKNIJ WSZYSTKO (KILL SWITCH)",

        "wallet_futures": "🔵 Portfel Futures",
        "free_balance": "Wolne",

        "session_results": "📊 Wyniki Sesji (PnL %)",
        "pnl_usdt": "PnL USDT",

        "slots_futures": "📈 Sloty Futures",
        "active_max": "Aktywne / Maksymalne",

        "session_time": "⏱ Czas Sesji",

        "active_positions": "📈 Aktywne Pozycje Futures",
        "trade_history": "📜 Historia Ostatnich Transakcji",

        "no_positions": "Brak otwartych pozycji futures.",
        "no_history": "Brak zarejestrowanych transakcji w tej sesji.",

        "admin_panel": "👑 Panel Administratora (Użytkownicy)",
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

        "kill_switch": "🔴 CLOSE ALL (KILL SWITCH)",

        "wallet_futures": "🔵 Futures Wallet",
        "free_balance": "Free",

        "session_results": "📊 Session Results (PnL %)",
        "pnl_usdt": "PnL USDT",

        "slots_futures": "📈 Futures Slots",
        "active_max": "Active / Maximum",

        "session_time": "⏱ Session Time",

        "active_positions": "📈 Active Futures Positions",
        "trade_history": "📜 Recent Trade History",

        "no_positions": "No open futures positions.",
        "no_history": "No recorded trades in this session.",

        "admin_panel": "👑 Admin Panel (Users)",
    },
}


def t(key):
    lang = st.session_state.get("lang", "Polski")

    return TRANSLATIONS.get(
        lang,
        TRANSLATIONS["Polski"],
    ).get(
        key,
        key,
    )


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


# ============================================================
# BAZA DANYCH
# ============================================================

def init_db():

    conn = sqlite3.connect(
        DB_FILE,
        timeout=30.0,
    )

    try:

        conn.execute(
            "PRAGMA journal_mode=WAL"
        )

        conn.execute(
            """
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
            """
        )

        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS user_mtf_settings (
                user_id INTEGER PRIMARY KEY,
                settings_json TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                FOREIGN KEY(user_id) REFERENCES users(id)
            )
            """
        )

        for email in ADMIN_EMAILS:

            conn.execute(
                """
                UPDATE users
                SET is_admin = 1,
                    stripe_paid = 1
                WHERE LOWER(TRIM(email)) = ?
                """,
                (email,),
            )

        conn.commit()

    finally:
        conn.close()


init_db()


# ============================================================
# HASŁA
# ============================================================

def hash_password(password, salt=None):

    if salt is None:
        salt = os.urandom(16).hex()

    digest = hashlib.sha256(
        (salt + password).encode("utf-8")
    ).hexdigest()

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

            return hmac.compare_digest(
                candidate,
                expected,
            )

        except Exception:

            return False

    return hmac.compare_digest(
        stored,
        str(password),
    )


# ============================================================
# USTAWIENIA MTF
# ============================================================

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

        conn = sqlite3.connect(
            DB_FILE,
            timeout=30.0,
        )

        row = conn.execute(
            """
            SELECT settings_json
            FROM user_mtf_settings
            WHERE user_id = ?
            """,
            (int(user_id),),
        ).fetchone()

        conn.close()

        if row and row[0]:

            stored = json.loads(row[0])

            if isinstance(stored, dict):

                for tf in AVAILABLE_TIMEFRAMES:

                    if isinstance(
                        stored.get(tf),
                        dict,
                    ):
                        settings[tf].update(
                            stored[tf]
                        )

    except Exception:
        pass


    for tf in AVAILABLE_TIMEFRAMES:

        defaults = settings[tf]

        st.session_state[
            f"radio_mode_{tf}"
        ] = (
            "Ręczny"
            if defaults.get("mode") == "Ręczny"
            else "Automatyczny"
        )

        st.session_state[
            f"ema_f_{tf}"
        ] = int(
            defaults.get(
                "ema_fast",
                DEFAULT_TF_VALUES[tf]["ema_fast"],
            )
        )

        st.session_state[
            f"ema_s_{tf}"
        ] = int(
            defaults.get(
                "ema_slow",
                DEFAULT_TF_VALUES[tf]["ema_slow"],
            )
        )

        st.session_state[
            f"adx_{tf}"
        ] = float(
            defaults.get(
                "adx",
                DEFAULT_TF_VALUES[tf]["adx"],
            )
        )

        st.session_state[
            f"min_rsi_{tf}"
        ] = float(
            defaults.get(
                "min_rsi",
                DEFAULT_TF_VALUES[tf]["min_rsi"],
            )
        )

        st.session_state[
            f"max_rsi_{tf}"
        ] = float(
            defaults.get(
                "max_rsi",
                DEFAULT_TF_VALUES[tf]["max_rsi"],
            )
        )

        st.session_state[
            f"cap_mult_{tf}"
        ] = float(
            defaults.get(
                "cap_mult",
                DEFAULT_TF_VALUES[tf]["cap_mult"],
            )
        )


    st.session_state[
        "_mtf_loaded_user_id"
    ] = int(user_id)


def save_mtf_settings_for_user(user_id):

    if not user_id:
        return

    payload = {}

    for tf in AVAILABLE_TIMEFRAMES:

        defaults = DEFAULT_TF_VALUES[tf]

        payload[tf] = {

            "mode": st.session_state.get(
                f"radio_mode_{tf}",
                "Automatyczny",
            ),

            "ema_fast": int(
                st.session_state.get(
                    f"ema_f_{tf}",
                    defaults["ema_fast"],
                )
            ),

            "ema_slow": int(
                st.session_state.get(
                    f"ema_s_{tf}",
                    defaults["ema_slow"],
                )
            ),

            "adx": float(
                st.session_state.get(
                    f"adx_{tf}",
                    defaults["adx"],
                )
            ),

            "max_rsi": float(
                st.session_state.get(
                    f"max_rsi_{tf}",
                    defaults["max_rsi"],
                )
            ),

            "min_rsi": float(
                st.session_state.get(
                    f"min_rsi_{tf}",
                    defaults["min_rsi"],
                )
            ),

            "cap_mult": float(
                st.session_state.get(
                    f"cap_mult_{tf}",
                    defaults["cap_mult"],
                )
            ),
        }


    try:

        conn = sqlite3.connect(
            DB_FILE,
            timeout=30.0,
        )

        conn.execute(
            """
            INSERT INTO user_mtf_settings
            (
                user_id,
                settings_json,
                updated_at
            )
            VALUES (?, ?, ?)

            ON CONFLICT(user_id)
            DO UPDATE SET
                settings_json = excluded.settings_json,
                updated_at = excluded.updated_at
            """,
            (
                int(user_id),
                json.dumps(
                    payload,
                    ensure_ascii=False,
                ),
                datetime.now().isoformat(
                    timespec="seconds"
                ),
            ),
        )

        conn.commit()
        conn.close()

    except Exception:
        pass


# ============================================================
# ADMIN / PŁATNOŚĆ
# ============================================================

def is_user_admin():

    email = str(
        st.session_state.get(
            "user_email",
            "",
        )
    ).strip().lower()

    return (
        email in ADMIN_EMAILS
        or bool(
            st.session_state.get(
                "is_admin",
                False,
            )
        )
    )


def is_user_paid():

    return (
        is_user_admin()
        or bool(
            st.session_state.get(
                "stripe_paid",
                False,
            )
        )
    )


# ============================================================
# STRIPE
# ============================================================

def get_secret(name, default=""):

    value = os.getenv(name)

    if value:
        return value

    try:
        return st.secrets.get(
            name,
            default,
        )

    except Exception:
        return default


def create_stripe_checkout_session(
    user_email,
    price_id,
):

    try:

        if not stripe.api_key or not price_id:
            return STRIPE_CHECKOUT_FALLBACK

        session = stripe.checkout.Session.create(

            payment_method_types=[
                "card"
            ],

            line_items=[
                {
                    "price": price_id,
                    "quantity": 1,
                }
            ],

            mode="payment",

            success_url=(
                "https://bot-bitget.pl/"
                "?success=true"
            ),

            cancel_url=(
                "https://bot-bitget.pl/"
                "?success=false"
            ),

            customer_email=user_email,
        )

        if session and session.url:
            return session.url

    except Exception:
        pass

    return STRIPE_CHECKOUT_FALLBACK


STRIPE_PRICE_ID = get_secret(
    "STRIPE_PRICE_ID",
    STRIPE_PRICE_ID,
)


# ============================================================
# EXCHANGE
# ============================================================

def get_exchange(
    api_k="",
    sec_k="",
    pass_k="",
    ex_name="Bitget",
):

    if not api_k:
        return None

    try:

        ex_id = ex_name.lower()

        exchange_class = getattr(
            ccxt,
            ex_id,
        )

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

        if ex_id in [
            "bitget",
            "okx",
        ] and pass_k:

            config["password"] = pass_k

        return exchange_class(config)

    except Exception:

        return None


# ============================================================
# WSKAŹNIKI
# ============================================================

def calculate_indicators(
    df,
    ema_fast=9,
    ema_slow=21,
    adx_period=14,
):

    df = df.copy()

    # EMA
    df["ema_fast"] = (
        df["close"]
        .ewm(
            span=max(
                1,
                ema_fast,
            ),
            adjust=False,
        )
        .mean()
    )

    df["ema_slow"] = (
        df["close"]
        .ewm(
            span=max(
                2,
                ema_slow,
            ),
            adjust=False,
        )
        .mean()
    )

    # RSI
    delta = df["close"].diff()

    gain = (
        delta.where(
            delta > 0,
            0,
        )
        .ewm(
            span=14,
            adjust=False,
        )
        .mean()
    )

    loss = (
        -delta.where(
            delta < 0,
            0,
        )
        .ewm(
            span=14,
            adjust=False,
        )
        .mean()
    )

    rs = gain / loss.replace(
        0,
        np.nan,
    )

    df["rsi"] = (
        100
        - (
            100
            / (
                1 + rs
            )
        )
    )

    # TR
    tr0 = (
        df["high"]
        - df["low"]
    ).abs()

    tr1 = (
        df["high"]
        - df["close"].shift(1)
    ).abs()

    tr2 = (
        df["low"]
        - df["close"].shift(1)
    ).abs()

    tr = pd.concat(
        [
            tr0,
            tr1,
            tr2,
        ],
        axis=1,
    ).max(axis=1)

    # Directional Movement
    up_move = df["high"].diff()

    down_move = -df["low"].diff()

    plus_dm = pd.Series(
        np.where(
            (
                (up_move > down_move)
                & (up_move > 0)
            ),
            up_move,
            0,
        ),
        index=df.index,
    )

    minus_dm = pd.Series(
        np.where(
            (
                (down_move > up_move)
                & (down_move > 0)
            ),
            down_move,
            0,
        ),
        index=df.index,
    )

    alpha = (
        1
        / max(
            1,
            adx_period,
        )
    )

    tr_smooth = (
        tr
        .ewm(
            alpha=alpha,
            adjust=False,
        )
        .mean()
        .replace(
            0,
            np.nan,
        )
    )

    plus_smooth = (
        plus_dm
        .ewm(
            alpha=alpha,
            adjust=False,
        )
        .mean()
    )

    minus_smooth = (
        minus_dm
        .ewm(
            alpha=alpha,
            adjust=False,
        )
        .mean()
    )

    plus_di = (
        100
        * plus_smooth
        / tr_smooth
    )

    minus_di = (
        100
        * minus_smooth
        / tr_smooth
    )

    di_sum = (
        plus_di
        + minus_di
    ).replace(
        0,
        np.nan,
    )

    dx = (
        100
        * (
            plus_di
            - minus_di
        ).abs()
        / di_sum
    )

    df["adx"] = (
        dx
        .ewm(
            alpha=alpha,
            adjust=False,
        )
        .mean()
    )

    # MACD
    exp1 = (
        df["close"]
        .ewm(
            span=12,
            adjust=False,
        )
        .mean()
    )

    exp2 = (
        df["close"]
        .ewm(
            span=26,
            adjust=False,
        )
        .mean()
    )

    df["macd"] = exp1 - exp2

    df["signal"] = (
        df["macd"]
        .ewm(
            span=9,
            adjust=False,
        )
        .mean()
    )

    return df


# ============================================================
# DYNAMICZNE PARAMETRY
# ============================================================

def get_optimal_dynamic_parameters(
    df_recent,
    tf,
):

    try:

        closes = (
            df_recent["close"]
            .astype(float)
            .to_numpy()
        )

        if len(closes) < 3:
            raise ValueError(
                "Za mało danych"
            )

        returns = (
            np.diff(closes)
            / closes[:-1]
        )

        volatility = (
            np.std(returns)
            * np.sqrt(
                len(returns)
            )
        )

        if tf in [
            "1m",
            "5m",
        ]:

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

        if tf in [
            "15m",
            "30m",
        ]:

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


# ============================================================
# RYZYKO
# ============================================================

def calculate_risk_based_allocation(
    free_balance,
    entry_price,
    stop_loss_price,
    risk_percentage=0.01,
    leverage=1,
    max_single_limit=50.0,
    tf_multiplier=1.0,
):

    if (
        free_balance <= 0
        or entry_price <= 0
        or stop_loss_price <= 0
    ):

        return min(
            max_single_limit
            * tf_multiplier,

            max(
                0.0,
                free_balance
                * 0.1
                * tf_multiplier,
            ),
        )

    scaled_single_limit = (
        max_single_limit
        * tf_multiplier
    )

    max_risk_amount = (
        free_balance
        * risk_percentage
        * tf_multiplier
    )

    risk_distance_pct = (
        abs(
            entry_price
            - stop_loss_price
        )
        / entry_price
    )

    if risk_distance_pct == 0:
        risk_distance_pct = 0.02

    position_notional_value = (
        max_risk_amount
        / risk_distance_pct
    )

    max_allowed_value = min(
        free_balance
        * leverage
        * 0.9,

        scaled_single_limit
        * leverage,
    )

    final_notional = min(
        position_notional_value,
        max_allowed_value,
    )

    return max(
        5.0 * tf_multiplier,
        final_notional,
    )


# ============================================================
# NORMALNE KRYPTOWALUTY — FILTR
# ============================================================

STABLE_BASES = {
    "USDT",
    "USDC",
    "FDUSD",
    "TUSD",
    "DAI",
    "USDE",
    "USDD",
    "BUSD",
    "USD1",
    "USDS",
}


LEVERAGED_MARKERS = (
    "3L",
    "3S",
    "5L",
    "5S",
    "UP",
    "DOWN",
    "BULL",
    "BEAR",
)


def is_normal_usdt_swap(market):

    symbol = str(
        market.get(
            "symbol",
            "",
        )
    )

    base = str(
        market.get(
            "base",
            "",
        )
    ).upper()

    quote = str(
        market.get(
            "quote",
            "",
        )
    ).upper()

    settle = str(
        market.get(
            "settle",
            "",
        )
    ).upper()


    # Tylko Futures / Swap
    if not market.get(
        "swap",
        False,
    ):
        return False


    # Tylko aktywne
    if not market.get(
        "active",
        True,
    ):
        return False


    # Tylko USDT-M
    if settle != "USDT":
        return False

    if quote != "USDT":
        return False


    # Bez stablecoinów jako baza
    if not base:
        return False

    if base in STABLE_BASES:
        return False


    # Bez tokenów lewarowanych
    if any(
        base.endswith(marker)
        or base.startswith(marker)
        for marker in LEVERAGED_MARKERS
    ):
        return False


    # Standard CCXT Futures symbol:
    # BTC/USDT:USDT
    if "/" not in symbol:
        return False

    if ":USDT" not in symbol:
        return False


    return True


# ============================================================
# WOLUMEN
# ============================================================

def ticker_quote_volume(ticker):

    try:

        value = float(
            ticker.get(
                "quoteVolume",
                0,
            )
            or 0
        )

        if value > 0:
            return value

    except Exception:
        pass


    try:

        base_volume = float(
            ticker.get(
                "baseVolume",
                0,
            )
            or 0
        )

        last_price = float(
            ticker.get(
                "last",
                0,
            )
            or 0
        )

        return (
            base_volume
            * last_price
        )

    except Exception:

        return 0.0


def build_volume_ranked_universe(
    exchange,
):

    markets = exchange.load_markets()


    candidates = {

        symbol: market

        for symbol, market
        in markets.items()

        if is_normal_usdt_swap(
            market
        )
    }


    # Najlepiej pobieramy wszystkie tickery naraz.
    try:

        tickers = exchange.fetch_tickers(
            list(
                candidates.keys()
            )
        )

    except Exception:

        tickers = {}

        # Fallback, gdy giełda nie obsługuje fetch_tickers(list)
        for symbol in candidates:

            try:

                tickers[symbol] = (
                    exchange.fetch_ticker(
                        symbol
                    )
                )

            except Exception:

                continue


    ranked = []


    for symbol in candidates:

        ticker = tickers.get(
            symbol,
            {},
        )

        volume = ticker_quote_volume(
            ticker
        )

        if volume > 0:

            ranked.append(
                (
                    symbol,
                    volume,
                )
            )


    # NAJWAŻNIEJSZE:
    # od największego wolumenu do najmniejszego.
    ranked.sort(
        key=lambda x: x[1],
        reverse=True,
    )


    return ranked


def fmt_volume(value):

    value = float(
        value or 0
    )

    if value >= 1_000_000_000:

        return (
            f"{value / 1_000_000_000:.2f}B USDT"
        )

    if value >= 1_000_000:

        return (
            f"{value / 1_000_000:.2f}M USDT"
        )

    if value >= 1_000:

        return (
            f"{value / 1_000:.1f}K USDT"
        )

    return f"{value:.0f} USDT"


# ============================================================
# CSS
# ============================================================

st.markdown(
    """
    <style>

    @import url(
        'https://fonts.googleapis.com/css2?family=Bungee+Inline&family=Cinzel:wght@700&display=swap'
    );

    .stApp {
        background-color: #0d0b0a;
    }

    section[data-testid="stSidebar"] {
        background-color: #141110;
        border-right: 2px solid #3d2f1f;
    }

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
        box-shadow: 0 4px 12px rgba(0,0,0,0.2);
    }

    .metric-card b {
        color: #f3d57a;
    }

    .metric-card span {
        font-size: 1.35rem;
        font-weight: bold;
        color: white;
    }

    .metric-card small {
        color: #e6c687;
    }

    </style>
    """,
    unsafe_allow_html=True,
)


# ============================================================
# POWRÓT STRIPE
# ============================================================

if (
    st.query_params.get("success") == "true"
    and st.session_state.logged_in
    and st.session_state.user_id
):

    st.session_state.stripe_paid = True

    try:

        conn = sqlite3.connect(
            DB_FILE,
            timeout=30.0,
        )

        conn.execute(
            """
            UPDATE users
            SET stripe_paid = 1
            WHERE id = ?
            """,
            (
                st.session_state.user_id,
            ),
        )

        conn.commit()
        conn.close()

    except Exception:
        pass

    st.success(
        "🎉 Płatność zakończona sukcesem! "
        "Twoja subskrypcja została aktywowana."
    )

    st.query_params.clear()


# ============================================================
# LOGOWANIE / REJESTRACJA
# ============================================================

if not st.session_state.logged_in:

    st.markdown(
        f"""
        <div style="
            text-align:center;
            padding:40px;
        ">

        <h1 style="
            color:#f3d57a;
            font-family:'Bungee Inline';
        ">
            {t("title")}
        </h1>

        <p style="
            color:#e6c687;
            font-family:'Cinzel';
        ">
            {t("subtitle")}
        </p>

        </div>
        """,
        unsafe_allow_html=True,
    )


    tab_login, tab_register = st.tabs(
        [
            t("login_tab"),
            t("register_tab"),
        ]
    )


    with tab_login:

        login_email = st.text_input(
            t("email_label"),
            key="log_email",
        )

        login_pass = st.text_input(
            t("pass_label"),
            type="password",
            key="log_pass",
        )


        if st.button(
            t("login_btn"),
            use_container_width=True,
        ):

            conn = sqlite3.connect(
                DB_FILE,
                timeout=30.0,
            )

            row = conn.execute(
                """
                SELECT
                    id,
                    email,
                    password,
                    is_admin,
                    stripe_paid,
                    api_key,
                    secret_key,
                    passphrase
                FROM users
                WHERE LOWER(TRIM(email)) = ?
                """,
                (
                    login_email.strip().lower(),
                ),
            ).fetchone()

            conn.close()


            if row and verify_password(
                login_pass,
                row[2],
            ):

                user_email = (
                    row[1]
                    .strip()
                    .lower()
                )

                admin_flag = (
                    user_email in ADMIN_EMAILS
                    or bool(row[3])
                )

                paid_flag = (
                    admin_flag
                    or bool(row[4])
                )


                st.session_state.logged_in = True
                st.session_state.user_id = row[0]
                st.session_state.user_email = row[1]
                st.session_state.is_admin = admin_flag
                st.session_state.stripe_paid = paid_flag

                st.session_state.api_key = (
                    row[5] or ""
                )

                st.session_state.secret_key = (
                    row[6] or ""
                )

                st.session_state.passphrase = (
                    row[7] or ""
                )


                load_mtf_settings_for_user(
                    row[0]
                )

                st.success(
                    t("login_success")
                )

                st.rerun()

            else:

                st.error(
                    t("login_error")
                )


    with tab_register:

        reg_email = st.text_input(
            t("email_label"),
            key="reg_email",
        )

        reg_pass = st.text_input(
            t("pass_label"),
            type="password",
            key="reg_pass",
        )


        if st.button(
            t("register_btn"),
            use_container_width=True,
        ):

            if not reg_email or not reg_pass:

                st.error(
                    t("reg_error_fill")
                )

            else:

                conn = sqlite3.connect(
                    DB_FILE,
                    timeout=30.0,
                )

                try:

                    conn.execute(
                        """
                        INSERT INTO users
                        (
                            email,
                            password
                        )
                        VALUES (?, ?)
                        """,
                        (
                            reg_email.strip().lower(),
                            hash_password(
                                reg_pass
                            ),
                        ),
                    )

                    conn.commit()

                    st.success(
                        t("reg_success")
                    )

                except sqlite3.IntegrityError:

                    st.error(
                        t("reg_error_exists")
                    )

                finally:

                    conn.close()


    st.stop()


# ============================================================
# AUTOMATYCZNE ŁADOWANIE MTF PO ODŚWIEŻENIU
# ============================================================

if (
    st.session_state.user_id
    and st.session_state.get(
        "_mtf_loaded_user_id"
    )
    != int(
        st.session_state.user_id
    )
):

    load_mtf_settings_for_user(
        st.session_state.user_id
    )


# ============================================================
# BRAMKA SUBSKRYPCJI
# ============================================================

if not is_user_paid():

    st.title(
        t("sub_zone")
    )

    st.warning(
        t("sub_inactive")
    )


    checkout_url = (
        create_stripe_checkout_session(
            st.session_state.user_email,
            STRIPE_PRICE_ID,
        )
    )


    st.link_button(
        t("pay_btn"),
        checkout_url,
        use_container_width=True,
    )


    if (
        ALLOW_TEST_ACTIVATION
        and st.button(
            "🧪 Aktywuj konto testowo"
        )
    ):

        conn = sqlite3.connect(
            DB_FILE,
            timeout=30.0,
        )

        conn.execute(
            """
            UPDATE users
            SET stripe_paid = 1
            WHERE id = ?
            """,
            (
                st.session_state.user_id,
            ),
        )

        conn.commit()
        conn.close()

        st.session_state.stripe_paid = True

        st.rerun()


    st.stop()


# ============================================================
# SIDEBAR
# ============================================================

with st.sidebar:

    st.markdown(
        f"### {t('title')}"
    )

    st.caption(
        t("subtitle")
    )


    st.session_state.lang = st.selectbox(
        "🌐 Język / Language",
        [
            "Polski",
            "English",
        ],
        index=(
            0
            if st.session_state.lang == "Polski"
            else 1
        ),
    )


    st.divider()


    if is_user_admin():

        st.info(
            t("sidebar_role_admin")
        )

    else:

        st.success(
            t("sidebar_role_client")
        )


    st.write(
        f"👤 {st.session_state.user_email}"
    )


    if st.button(
        t("logout_btn"),
        use_container_width=True,
    ):

        st.session_state.logged_in = False
        st.session_state.user_id = None
        st.session_state.user_email = ""
        st.session_state.is_admin = False
        st.session_state.stripe_paid = False
        st.session_state._mtf_loaded_user_id = None

        st.rerun()


    st.divider()


    st.subheader(
        t("exchange_settings")
    )


    exchange_names = [
        "Bitget",
        "Binance",
        "Bybit",
        "OKX",
    ]

    current_exchange = (
        st.session_state.selected_exchange
    )

    if current_exchange not in exchange_names:
        current_exchange = "Bitget"


    st.session_state.selected_exchange = (
        st.selectbox(
            t("select_exchange"),
            exchange_names,
            index=exchange_names.index(
                current_exchange
            ),
        )
    )


    api_key_input = st.text_input(
        "API Key",
        value=st.session_state.api_key,
        type="password",
    )

    secret_key_input = st.text_input(
        "Secret Key",
        value=st.session_state.secret_key,
        type="password",
    )

    passphrase_input = st.text_input(
        "Passphrase / API Password",
        value=st.session_state.passphrase,
        type="password",
    )


    if st.button(
        t("save_keys_btn"),
        use_container_width=True,
    ):

        if (
            api_key_input
            and secret_key_input
        ):

            st.session_state.api_key = (
                api_key_input
            )

            st.session_state.secret_key = (
                secret_key_input
            )

            st.session_state.passphrase = (
                passphrase_input
            )


            try:

                conn = sqlite3.connect(
                    DB_FILE,
                    timeout=30.0,
                )

                conn.execute(
                    """
                    UPDATE users
                    SET
                        api_key = ?,
                        secret_key = ?,
                        passphrase = ?
                    WHERE id = ?
                    """,
                    (
                        api_key_input,
                        secret_key_input,
                        passphrase_input,
                        st.session_state.user_id,
                    ),
                )

                conn.commit()
                conn.close()

                st.success(
                    f"{t('keys_saved')} "
                    f"{st.session_state.selected_exchange}"
                )

            except Exception as e:

                st.error(
                    f"Błąd zapisu w bazie: {e}"
                )

        else:

            st.warning(
                t("keys_error")
            )


# ============================================================
# POŁĄCZENIE Z GIEŁDĄ
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

        balance = exchange.fetch_balance(
            {
                "type": "swap"
            }
        )


        free_usdt = float(
            balance.get(
                "USDT",
                {},
            ).get(
                "free",
                0,
            )
            or 0
        )


        total_usdt = float(
            balance.get(
                "USDT",
                {},
            ).get(
                "total",
                free_usdt,
            )
            or free_usdt
        )


        if not st.session_state.session_baseline_locked:

            st.session_state.session_start_balance = (
                total_usdt
            )

            st.session_state.session_baseline_locked = True


        raw_positions = (
            exchange.fetch_positions()
        )


        open_positions = [

            p

            for p in raw_positions

            if float(
                p.get(
                    "contracts",
                    0,
                )
                or p.get(
                    "size",
                    0,
                )
                or 0
            ) > 0

        ]


    except Exception as e:

        st.sidebar.error(
            f"⚠️ Błąd połączenia z giełdą: {e}"
        )


# ============================================================
# METRYKI
# ============================================================

pnl_usdt = (
    total_usdt
    - st.session_state.session_start_balance
)


if (
    st.session_state.session_start_balance
    > 0
):

    pnl_pct = (
        pnl_usdt
        / st.session_state.session_start_balance
        * 100
    )

else:

    pnl_pct = 0.0


session_duration = str(
    datetime.now()
    - st.session_state.session_start_time
).split(".")[0]


st.markdown(
    f"""
    <div class="metrics-row">

        <div class="metric-card">
            <b>{t('wallet_futures')}</b>
            <br>
            <span>${total_usdt:.2f}</span>
            <br>
            <small>
                {t('free_balance')}: ${free_usdt:.2f}
            </small>
        </div>

        <div class="metric-card">
            <b>{t('session_results')}</b>
            <br>
            <span>{pnl_pct:+.2f}%</span>
            <br>
            <small>
                {t('pnl_usdt')}: ${pnl_usdt:+.2f}
            </small>
        </div>

        <div class="metric-card">
            <b>{t('slots_futures')}</b>
            <br>
            <span>{len(open_positions)}</span>
            <br>
            <small>
                {t('active_max')}
            </small>
        </div>

        <div class="metric-card">
            <b>{t('session_time')}</b>
            <br>
            <span>{session_duration}</span>
        </div>

    </div>
    """,
    unsafe_allow_html=True,
)


# ============================================================
# KAPITAŁ / RYZYKO
# ============================================================

st.header(
    t("capital_risk")
)


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

    st.subheader(
        t("roe_guard")
    )


    enable_roe = st.checkbox(
        t("enable_roe"),
        value=True,
    )


    col_roe1, col_roe2 = st.columns(2)


    with col_roe1:

        sl_roe_pct = st.number_input(
            t("sl_roe"),
            min_value=1.0,
            max_value=500.0,
            value=15.0,
            step=1.0,
        )


    with col_roe2:

        tp_roe_pct = st.number_input(
            t("tp_roe"),
            min_value=1.0,
            max_value=1000.0,
            value=30.0,
            step=1.0,
        )


# ============================================================
# DŹWIGNIA
# ============================================================

st.subheader(
    t("leverage_mgmt")
)


col_lev1, col_lev2 = st.columns(2)


with col_lev1:

    lev_mode = st.radio(
        t("lev_mode"),
        [
            "Dynamiczna (ADX Smart)",
            "Stała (Manualna)",
        ],
        horizontal=True,
    )


with col_lev2:

    if lev_mode == "Dynamiczna (ADX Smart)":

        max_allowed_lev = st.slider(
            t("max_allowed_lev"),
            min_value=2,
            max_value=125,
            value=15,
        )

        manual_lev = 1

    else:

        manual_lev = st.slider(
            t("manual_lev"),
            min_value=1,
            max_value=125,
            value=10,
        )

        max_allowed_lev = manual_lev


# ============================================================
# MTF
# ============================================================

st.header(
    t("bot_control")
)


selected_tf_tabs = st.tabs(
    [
        f"⏱ {tf}"
        for tf in AVAILABLE_TIMEFRAMES
    ]
)


for idx, tf in enumerate(
    AVAILABLE_TIMEFRAMES
):

    with selected_tf_tabs[idx]:

        st.markdown(
            f"#### Konfiguracja Interwału {tf}"
        )


        mode_val = st.radio(
            "Tryb parametrów:",
            [
                "Automatyczny",
                "Ręczny",
            ],
            key=f"radio_mode_{tf}",
            horizontal=True,
        )


        disabled_flag = (
            mode_val == "Automatyczny"
        )


        col_tf1, col_tf2, col_tf3 = (
            st.columns(3)
        )


        with col_tf1:

            st.number_input(
                "EMA Fast",
                min_value=2,
                max_value=100,
                key=f"ema_f_{tf}",
                disabled=disabled_flag,
            )

            st.number_input(
                "EMA Slow",
                min_value=5,
                max_value=200,
                key=f"ema_s_{tf}",
                disabled=disabled_flag,
            )


        with col_tf2:

            st.number_input(
                "Min ADX",
                min_value=5.0,
                max_value=80.0,
                key=f"adx_{tf}",
                disabled=disabled_flag,
            )

            st.number_input(
                "Mnożnik Kapitału",
                min_value=0.0,
                max_value=10.0,
                key=f"cap_mult_{tf}",
                disabled=disabled_flag,
            )


        with col_tf3:

            st.number_input(
                "Min RSI",
                min_value=5.0,
                max_value=50.0,
                key=f"min_rsi_{tf}",
                disabled=disabled_flag,
            )

            st.number_input(
                "Max RSI",
                min_value=50.0,
                max_value=95.0,
                key=f"max_rsi_{tf}",
                disabled=disabled_flag,
            )


if st.button(
    "💾 ZAPISZ NASTAWY STRATEGII MTF",
    use_container_width=True,
):

    save_mtf_settings_for_user(
        st.session_state.user_id
    )

    st.success(
        "Pomyślnie zapisano nastawy MTF."
    )


# ============================================================
# SKANER RYNKU
# ============================================================

st.divider()

st.header(
    "🔍 Skaner Rynku Live — "
    "TOP USDT Futures wg wolumenu"
)


if exchange:

    try:

        # ----------------------------------------------------
        # NAJPIERW BUDUJEMY RANKING WOLUMENU
        # ----------------------------------------------------

        ranked = build_volume_ranked_universe(
            exchange
        )


        if not ranked:

            st.warning(
                "Giełda nie zwróciła wolumenów "
                "dla żadnych normalnych kontraktów USDT-M."
            )

        else:

            max_limit = min(
                100,
                len(ranked),
            )


            num_pairs = st.slider(
                "Liczba skanowanych par — "
                "zawsze od najwyższego wolumenu:",
                min_value=1,
                max_value=max_limit,
                value=min(
                    20,
                    max_limit,
                ),
                step=1,
            )


            # ------------------------------------------------
            # KLUCZOWA ZMIANA:
            # ranked jest już posortowany malejąco
            # ------------------------------------------------

            scan_list = ranked[
                :num_pairs
            ]


            st.caption(
                "Kolejność: 24h wolumen obrotu "
                "USDT od najwyższego do najniższego. "
                "Wykluczono stablecoiny oraz tokeny lewarowane."
            )


            col1, col2, col3 = st.columns(3)


            with col1:

                st.metric(
                    "Normalne USDT Futures",
                    len(ranked),
                )


            with col2:

                st.metric(
                    "Skanowane",
                    len(scan_list),
                )


            with col3:

                st.metric(
                    "Ostatni skan",
                    datetime.now().strftime(
                        "%H:%M:%S"
                    ),
                )


            scanner_rows = []


            progress = st.progress(
                0
            )


            # ------------------------------------------------
            # ANALIZA TOP PAR WG WOLUMENU
            # ------------------------------------------------

            for n, (
                symbol,
                quote_volume,
            ) in enumerate(
                scan_list,
                1,
            ):

                try:

                    # Bazowy skaner 1H.
                    # Ustawienia MTF pozostają osobno zapisane.
                    timeframe_scan = "1h"


                    ohlcv = (
                        exchange.fetch_ohlcv(
                            symbol,
                            timeframe=timeframe_scan,
                            limit=100,
                        )
                    )


                    if (
                        not ohlcv
                        or len(ohlcv) < 60
                    ):
                        continue


                    df = pd.DataFrame(
                        ohlcv,
                        columns=[
                            "timestamp",
                            "open",
                            "high",
                            "low",
                            "close",
                            "volume",
                        ],
                    )


                    indicators = (
                        calculate_indicators(
                            df
                        )
                    )


                    last = (
                        indicators.iloc[-1]
                    )


                    last_price = float(
                        last["close"]
                    )


                    ema_fast = float(
                        last["ema_fast"]
                    )


                    ema_slow = float(
                        last["ema_slow"]
                    )


                    rsi = float(
                        last["rsi"]
                    ) if pd.notna(
                        last["rsi"]
                    ) else

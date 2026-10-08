from __future__ import annotations

import argparse
import gc
import hashlib
import hmac
import json
import logging
import os
import sqlite3
import threading
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

import ccxt
import numpy as np
import pandas as pd
import streamlit as st

try:
    import stripe
except Exception:
    stripe = None


# ============================================================
# CONFIGURATION
# ============================================================

def env_int(name: str, default: int, minimum: int = 0) -> int:
    try:
        return max(minimum, int(os.getenv(name, str(default))))
    except (TypeError, ValueError):
        return max(minimum, int(default))


BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_FILE = os.getenv("DB_FILE", os.path.join(BASE_DIR, "users.db"))
LOG_FILE = os.getenv("BOT_LOG_FILE", os.path.join(BASE_DIR, "trading_bot.log"))

ALLOW_TEST_ACTIVATION = os.getenv("ALLOW_TEST_ACTIVATION", "0") == "1"
ADMIN_EMAILS = ["marekja57@wp.pl", "admin@bot-bitget.pl"]

SUPPORTED_EXCHANGES = ["Bitget", "Binance", "Bybit", "OKX"]
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

STRIPE_SECRET_KEY = os.getenv("STRIPE_SECRET_KEY", "")
STRIPE_PRICE_ID = os.getenv("STRIPE_PRICE_ID", "")
STRIPE_CHECKOUT_FALLBACK = os.getenv(
    "STRIPE_CHECKOUT_FALLBACK",
    "https://buy.stripe.com/8x2dRa4CbdaXfSAf6V3oA03",
)

DEFAULT_STOP_ROE = 4.0
DEFAULT_TAKE_ROE = 15.0
DEFAULT_RISK_PCT = 0.01
DEFAULT_MAX_SINGLE = 50.0
DEFAULT_MAX_POSITIONS = 5
DEFAULT_MAX_LEVERAGE = 15
DEFAULT_MANUAL_LEVERAGE = 5
DEFAULT_MAX_SCAN_PAIRS = 30
MIN_QUOTE_VOLUME = 1_000_000.0

WORKER_POLL_SECONDS = env_int("BOT_POLL_SECONDS", 5, 2)
POSITION_GUARD_SECONDS = env_int("POSITION_GUARD_SECONDS", 3, 1)
SCAN_BATCH_SIZE = env_int("SCAN_BATCH_SIZE", 8, 3)
UI_REFRESH_DEFAULT = env_int("UI_REFRESH_SECONDS", 10, 5)

os.makedirs(os.path.dirname(LOG_FILE) or ".", exist_ok=True)

logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO").upper(),
    format="%(asctime)s | %(levelname)s | %(threadName)s | %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(LOG_FILE, encoding="utf-8"),
    ],
)
log = logging.getLogger("futures_saas")

if stripe is not None and STRIPE_SECRET_KEY:
    stripe.api_key = STRIPE_SECRET_KEY


# ============================================================
# TRANSLATIONS
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
        "sub_zone": "🛡️ Strefa Subskrypcji",
        "sub_active": "Subskrypcja aktywna (Dostęp Pełny)",
        "sub_inactive": "⚠️ Brak aktywnej subskrypcji",
        "pay_btn": "OPŁAĆ DOSTĘP (49 PLN)",
        "capital_risk": "💰 Kapitał i Ryzyko",
        "max_single": "Maksymalnie USDT na 1 pozycję",
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
        "session_results": "📊 Wyniki Sesji",
        "pnl_usdt": "PnL USDT",
        "slots_futures": "📈 Sloty Futures",
        "active_max": "Aktywne / Maksymalne",
        "session_time": "⏱ Czas Sesji",
        "market_scanner_results": "📊 Wyniki Skanera Rynkowego",
        "active_positions": "📈 Aktywne Pozycje Futures",
        "trade_history": "📜 Historia Ostatnich Transakcji",
        "admin_panel": "👑 Panel Administratora",
        "no_positions": "Brak otwartych pozycji futures.",
        "no_history": "Brak zarejestrowanych transakcji.",
        "no_scanner": "Brak danych skanera. Uruchom co najmniej jednego bota MTF.",
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
        "max_single": "Max USDT per position",
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
        "session_results": "📊 Session Results",
        "pnl_usdt": "PnL USDT",
        "slots_futures": "📈 Futures Slots",
        "active_max": "Active / Maximum",
        "session_time": "⏱ Session Time",
        "market_scanner_results": "📊 Market Scanner Results",
        "active_positions": "📈 Active Futures Positions",
        "trade_history": "📜 Recent Trade History",
        "admin_panel": "👑 Admin Panel",
        "no_positions": "No open futures positions.",
        "no_history": "No recorded trades.",
        "no_scanner": "No scanner data. Start at least one MTF bot.",
    },
}


def t(key: str) -> str:
    lang = st.session_state.get("lang", "Polski")
    return TRANSLATIONS.get(lang, TRANSLATIONS["Polski"]).get(key, key)


# ============================================================
# GENERAL HELPERS
# ============================================================

def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def safe_float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None:
            return default
        x = float(value)
        return x if np.isfinite(x) else default
    except Exception:
        return default


def db_connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_FILE, timeout=30.0, check_same_thread=False)
    conn.execute("PRAGMA busy_timeout=30000")
    return conn


def get_secret(name: str, default: str = "") -> str:
    value = os.getenv(name)
    if value:
        return value
    try:
        return st.secrets.get(name, default)
    except Exception:
        return default


# ============================================================
# DATABASE
# ============================================================

def init_db() -> None:
    conn = db_connect()
    try:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute(""" CREATE TABLE IF NOT EXISTS users ( id INTEGER PRIMARY KEY AUTOINCREMENT, email TEXT UNIQUE, password TEXT, is_admin INTEGER DEFAULT 0, stripe_paid INTEGER DEFAULT 0, api_key TEXT DEFAULT '', secret_key TEXT DEFAULT '', passphrase TEXT DEFAULT '', selected_exchange TEXT DEFAULT 'Bitget', settings_json TEXT DEFAULT '{}' ) """)
        conn.execute(""" CREATE TABLE IF NOT EXISTS user_mtf_settings ( user_id INTEGER PRIMARY KEY, settings_json TEXT NOT NULL, updated_at TEXT NOT NULL, FOREIGN KEY(user_id) REFERENCES users(id) ) """)
        conn.execute(""" CREATE TABLE IF NOT EXISTS user_bot_state ( user_id INTEGER PRIMARY KEY, active_bots_json TEXT NOT NULL DEFAULT '{}', updated_at TEXT NOT NULL, FOREIGN KEY(user_id) REFERENCES users(id) ) """)
        conn.execute(""" CREATE TABLE IF NOT EXISTS trade_log ( id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL, created_at TEXT NOT NULL, symbol TEXT, timeframe TEXT, action TEXT, side TEXT, price REAL, amount REAL, order_id TEXT, message TEXT, FOREIGN KEY(user_id) REFERENCES users(id) ) """)
        conn.execute(""" CREATE TABLE IF NOT EXISTS entry_guard ( user_id INTEGER NOT NULL, symbol TEXT NOT NULL, locked_until REAL NOT NULL DEFAULT 0, last_candle INTEGER NOT NULL DEFAULT 0, last_side TEXT DEFAULT '', updated_at TEXT NOT NULL, PRIMARY KEY(user_id, symbol), FOREIGN KEY(user_id) REFERENCES users(id) ) """)
        conn.execute(""" CREATE TABLE IF NOT EXISTS scanner_results ( user_id INTEGER NOT NULL, timeframe TEXT NOT NULL, symbol TEXT NOT NULL, quote_volume REAL DEFAULT 0, price REAL DEFAULT 0, adx REAL DEFAULT 0, rsi REAL DEFAULT 0, ema_fast REAL DEFAULT 0, ema_slow REAL DEFAULT 0, signal TEXT DEFAULT 'NEUTRALNY', candle_ts INTEGER DEFAULT 0, updated_at TEXT NOT NULL, PRIMARY KEY(user_id, timeframe, symbol), FOREIGN KEY(user_id) REFERENCES users(id) ) """)
        conn.execute(""" CREATE TABLE IF NOT EXISTS protection_state ( user_id INTEGER NOT NULL, symbol TEXT NOT NULL, side TEXT NOT NULL, amount REAL NOT NULL, entry_price REAL NOT NULL, leverage REAL NOT NULL, stop_price REAL NOT NULL, take_price REAL NOT NULL, stop_order_id TEXT DEFAULT '', take_order_id TEXT DEFAULT '', updated_at TEXT NOT NULL, PRIMARY KEY(user_id, symbol), FOREIGN KEY(user_id) REFERENCES users(id) ) """)

        cols = {r[1] for r in conn.execute("PRAGMA table_info(users)").fetchall()}
        for name, typ in [
            ("selected_exchange", "TEXT DEFAULT 'Bitget'"),
            ("settings_json", "TEXT DEFAULT '{}'"),
            ("api_key", "TEXT DEFAULT ''"),
            ("secret_key", "TEXT DEFAULT ''"),
            ("passphrase", "TEXT DEFAULT ''"),
            ("is_admin", "INTEGER DEFAULT 0"),
            ("stripe_paid", "INTEGER DEFAULT 0"),
        ]:
            if name not in cols:
                conn.execute(f"ALTER TABLE users ADD COLUMN {name} {typ}")

        for adm in ADMIN_EMAILS:
            conn.execute(
                "UPDATE users SET is_admin=1, stripe_paid=1 WHERE LOWER(TRIM(email))=?",
                (adm.lower(),),
            )
        conn.commit()
    finally:
        conn.close()


def hash_password(password: str, salt: Optional[str] = None) -> str:
    salt = salt or os.urandom(16).hex()
    digest = hashlib.sha256((salt + password).encode()).hexdigest()
    return f"sha256${salt}${digest}"


def verify_password(password: str, stored: str) -> bool:
    if not stored:
        return False
    if str(stored).startswith("sha256$"):
        try:
            _, salt, expected = str(stored).split("$", 2)
            candidate = hashlib.sha256((salt + password).encode()).hexdigest()
            return hmac.compare_digest(candidate, expected)
        except Exception:
            return False
    return hmac.compare_digest(str(stored), password)


# ============================================================
# MTF PERSISTENCE
# ============================================================

def default_mtf_payload() -> Dict[str, Dict[str, Any]]:
    return {
        tf: {
            **vals,
            "mode": "Automatyczny",
            "min_adx": vals["adx"],
            "capital_multiplier": vals["cap_mult"],
            "tf": tf,
        }
        for tf, vals in DEFAULT_TF_VALUES.items()
    }


def normalize_mtf_config(tf: str, cfg: Dict[str, Any]) -> Dict[str, Any]:
    d = DEFAULT_TF_VALUES[tf]
    mode = "Ręczny" if cfg.get("mode") == "Ręczny" else "Automatyczny"
    fast = max(1, int(cfg.get("ema_fast", d["ema_fast"])))
    slow = max(fast + 1, int(cfg.get("ema_slow", d["ema_slow"])))
    adx = min(50.0, max(10.0, safe_float(cfg.get("min_adx", cfg.get("adx", d["adx"])), d["adx"])))
    max_rsi = min(100.0, max(50.0, safe_float(cfg.get("max_rsi", d["max_rsi"]), d["max_rsi"])))
    min_rsi = min(50.0, max(0.0, safe_float(cfg.get("min_rsi", d["min_rsi"]), d["min_rsi"])))
    cap = max(0.1, safe_float(cfg.get("capital_multiplier", cfg.get("cap_mult", d["cap_mult"])), d["cap_mult"]))
    return {
        "mode": mode,
        "ema_fast": fast,
        "ema_slow": slow,
        "min_adx": adx,
        "max_rsi": max_rsi,
        "min_rsi": min_rsi,
        "capital_multiplier": cap,
        "tf": tf,
    }


def load_mtf_settings(user_id: int) -> Dict[str, Dict[str, Any]]:
    payload = default_mtf_payload()
    conn = db_connect()
    try:
        row = conn.execute(
            "SELECT settings_json FROM user_mtf_settings WHERE user_id=?",
            (int(user_id),),
        ).fetchone()
    finally:
        conn.close()

    if row and row[0]:
        try:
            saved = json.loads(row[0])
            if isinstance(saved, dict):
                for tf in AVAILABLE_TIMEFRAMES:
                    if isinstance(saved.get(tf), dict):
                        payload[tf].update(saved[tf])
        except Exception:
            log.exception("Invalid MTF JSON user=%s", user_id)

    return {tf: normalize_mtf_config(tf, payload[tf]) for tf in AVAILABLE_TIMEFRAMES}


def save_mtf_settings(user_id: int, payload: Dict[str, Dict[str, Any]]) -> None:
    normalized = {
        tf: normalize_mtf_config(tf, payload.get(tf, {}))
        for tf in AVAILABLE_TIMEFRAMES
    }
    conn = db_connect()
    try:
        conn.execute(""" INSERT INTO user_mtf_settings(user_id, settings_json, updated_at) VALUES(?,?,?) ON CONFLICT(user_id) DO UPDATE SET settings_json=excluded.settings_json, updated_at=excluded.updated_at """, (int(user_id), json.dumps(normalized, ensure_ascii=False), utc_now()))
        conn.commit()
    finally:
        conn.close()


def current_mtf_payload() -> Dict[str, Dict[str, Any]]:
    payload = {}
    for tf in AVAILABLE_TIMEFRAMES:
        payload[tf] = normalize_mtf_config(tf, {
            "mode": st.session_state.get(f"radio_mode_{tf}", "Automatyczny"),
            "ema_fast": st.session_state.get(f"ema_f_{tf}", 9),
            "ema_slow": st.session_state.get(f"ema_s_{tf}", 21),
            "min_adx": st.session_state.get(f"adx_{tf}", DEFAULT_TF_VALUES[tf]["adx"]),
            "max_rsi": st.session_state.get(f"max_rsi_{tf}", 75.0),
            "min_rsi": st.session_state.get(f"min_rsi_{tf}", 25.0),
            "capital_multiplier": st.session_state.get(f"cap_mult_{tf}", DEFAULT_TF_VALUES[tf]["cap_mult"]),
        })
    return payload


def save_mtf_callback() -> None:
    user_id = st.session_state.get("user_id")
    if user_id:
        try:
            save_mtf_settings(int(user_id), current_mtf_payload())
            st.session_state["_mtf_save_error"] = ""
        except Exception as exc:
            log.exception("MTF save failed user=%s", user_id)
            st.session_state["_mtf_save_error"] = str(exc)


def apply_mtf_to_session(user_id: int, force: bool = False) -> None:
    if not user_id:
        return
    uid = int(user_id)
    if not force and st.session_state.get("_mtf_loaded_user_id") == uid:
        return

    saved = load_mtf_settings(uid)
    for tf in AVAILABLE_TIMEFRAMES:
        d = saved[tf]
        st.session_state[f"radio_mode_{tf}"] = d["mode"]
        st.session_state[f"ema_f_{tf}"] = int(d["ema_fast"])
        st.session_state[f"ema_s_{tf}"] = int(d["ema_slow"])
        st.session_state[f"adx_{tf}"] = float(d["min_adx"])
        st.session_state[f"max_rsi_{tf}"] = float(d["max_rsi"])
        st.session_state[f"min_rsi_{tf}"] = float(d["min_rsi"])
        st.session_state[f"cap_mult_{tf}"] = float(d["capital_multiplier"])
    st.session_state["_mtf_loaded_user_id"] = uid


def load_active_bots(user_id: int) -> Dict[str, Dict[str, Any]]:
    conn = db_connect()
    try:
        row = conn.execute(
            "SELECT active_bots_json FROM user_bot_state WHERE user_id=?",
            (int(user_id),),
        ).fetchone()
    finally:
        conn.close()
    if not row or not row[0]:
        return {}
    try:
        data = json.loads(row[0])
        if not isinstance(data, dict):
            return {}
        return {
            tf: normalize_mtf_config(tf, cfg)
            for tf, cfg in data.items()
            if tf in AVAILABLE_TIMEFRAMES and isinstance(cfg, dict)
        }
    except Exception:
        return {}


def save_active_bots(user_id: int, bots: Dict[str, Dict[str, Any]]) -> None:
    clean = {
        tf: normalize_mtf_config(tf, cfg)
        for tf, cfg in bots.items()
        if tf in AVAILABLE_TIMEFRAMES and isinstance(cfg, dict)
    }
    conn = db_connect()
    try:
        conn.execute(""" INSERT INTO user_bot_state(user_id, active_bots_json, updated_at) VALUES(?,?,?) ON CONFLICT(user_id) DO UPDATE SET active_bots_json=excluded.active_bots_json, updated_at=excluded.updated_at """, (int(user_id), json.dumps(clean, ensure_ascii=False), utc_now()))
        conn.commit()
    finally:
        conn.close()


# ============================================================
# EXCHANGE
# ============================================================

def get_exchange(api_key: str, secret: str, passphrase: str, name: str):
    if not api_key or not secret:
        return None
    try:
        name = name or "Bitget"
        mapping = {
            "Bitget": "bitget",
            "Binance": "binanceusdm",
            "Bybit": "bybit",
            "OKX": "okx",
        }
        ex_id = mapping.get(name, "bitget")
        cls = getattr(ccxt, ex_id)

        config = {
            "apiKey": api_key,
            "secret": secret,
            "enableRateLimit": True,
            "timeout": 30000,
            "options": {
                "defaultType": "swap",
                "defaultSubType": "linear",
            },
        }
        if ex_id in {"bitget", "okx"} and passphrase:
            config["password"] = passphrase

        exchange = cls(config)
        return exchange
    except Exception as exc:
        log.error("Exchange init failed for %s: %s", name, exc)
        return None


def load_markets_safe(exchange) -> bool:
    try:
        exchange.load_markets(reload=False)
        return True
    except Exception as exc:
        log.error("load_markets failed: %s", exc)
        return False


def is_tradeable_usdt_swap(market: Dict[str, Any]) -> bool:
    return bool(
        market.get("active", True)
        and market.get("swap")
        and market.get("linear")
        and str(market.get("quote", "")).upper() == "USDT"
        and str(market.get("settle", "")).upper() == "USDT"
    )


def fetch_futures_tickers(exchange) -> Dict[str, Any]:
    """ Pobiera tylko tickery z liniowych kontraktów USDT Futures. Dla Bitget jawnie wskazujemy USDT-FUTURES. """
    params: Dict[str, Any] = {}
    ex_id = getattr(exchange, "id", "")
    if ex_id == "bitget":
        params = {"productType": "USDT-FUTURES"}
    elif ex_id == "bybit":
        params = {"category": "linear"}
    elif ex_id == "okx":
        params = {"instType": "SWAP"}
    try:
        raw = exchange.fetch_tickers(params=params)
    except TypeError:
        raw = exchange.fetch_tickers()

    result = {}
    for symbol, ticker in raw.items():
        market = exchange.markets.get(symbol) or {}
        if is_tradeable_usdt_swap(market):
            result[symbol] = ticker
    return result


def rank_liquid_symbols(exchange, tickers: Dict[str, Any], max_pairs: int) -> List[Tuple[str, float]]:
    ranked = []
    for symbol, ticker in tickers.items():
        try:
            market = exchange.markets.get(symbol) or {}
            if not is_tradeable_usdt_swap(market):
                continue
            qv = safe_float(ticker.get("quoteVolume"))
            if qv < MIN_QUOTE_VOLUME:
                continue
            ranked.append((symbol, qv))
        except Exception:
            continue
    ranked.sort(key=lambda x: x[1], reverse=True)
    return ranked[:max(1, int(max_pairs))]


def fetch_ohlcv_safe(exchange, symbol: str, timeframe: str, limit: int = 200) -> List[List[Any]]:
    try:
        return exchange.fetch_ohlcv(symbol, timeframe, limit=int(limit))
    except Exception as exc:
        log.debug("OHLCV failed %s %s: %s", symbol, timeframe, exc)
        return []


def fetch_usdt_balance(exchange) -> Dict[str, float]:
    result = {"total": 0.0, "used": 0.0, "free": 0.0}
    if exchange is None:
        return result
    try:
        bal = exchange.fetch_balance({"type": "swap"})
        u = bal.get("USDT", {}) or {}

        def nested(name: str) -> float:
            x = safe_float(u.get(name))
            if x > 0:
                return x
            top = bal.get(name, {}) or {}
            if isinstance(top, dict):
                return safe_float(top.get("USDT"))
            return 0.0

        total, free, used = nested("total"), nested("free"), nested("used")
        if total <= 0 and free > 0:
            total = free + max(0.0, used)
        if used <= 0 and total > 0:
            used = max(0.0, total - free)
        if free <= 0 and total > 0:
            free = max(0.0, total - used)
        result.update(total=max(0, total), used=max(0, used), free=max(0, free))
    except Exception as exc:
        log.warning("USDT balance fetch failed: %s", exc)
    return result


def position_contracts(p: Dict[str, Any]) -> float:
    return abs(safe_float(p.get("contracts", p.get("amount", 0))))


def position_side(p: Dict[str, Any]) -> str:
    return str(p.get("side", "")).lower()


def is_long(p: Dict[str, Any]) -> bool:
    return position_side(p) in {"long", "buy"}


def close_side_for_position(p: Dict[str, Any]) -> str:
    return "sell" if is_long(p) else "buy"


def reduce_only_params(exchange) -> Dict[str, Any]:
    return {"reduceOnly": True}


def fetch_positions_safe(exchange) -> List[Dict[str, Any]]:
    if exchange is None:
        return []
    try:
        return exchange.fetch_positions()
    except Exception as exc:
        log.warning("fetch_positions failed: %s", exc)
        return []


def find_position(positions: List[Dict[str, Any]], symbol: str) -> Optional[Dict[str, Any]]:
    for p in positions:
        if p.get("symbol") == symbol and position_contracts(p) > 0:
            return p
    return None


def close_position(exchange, p: Dict[str, Any], reason: str = "") -> bool:
    symbol = p.get("symbol")
    amount = position_contracts(p)
    if not symbol or amount <= 0:
        return False
    try:
        amount = float(exchange.amount_to_precision(symbol, amount))
        if amount <= 0:
            return False
        order = exchange.create_order(
            symbol, "market", close_side_for_position(p), amount, None,
            reduce_only_params(exchange)
        )
        log.info("Closed %s %s amount=%s reason=%s", symbol, position_side(p), amount, reason)
        return bool(order)
    except Exception as exc:
        log.error("Close position failed %s: %s", symbol, exc)
        return False


def contract_size(exchange, symbol: str) -> float:
    try:
        value = safe_float(exchange.market(symbol).get("contractSize"), 1.0)
        return value if value > 0 else 1.0
    except Exception:
        return 1.0


def base_amount_to_contracts(exchange, symbol: str, base_amount: float) -> float:
    return max(0.0, float(base_amount) / contract_size(exchange, symbol))


def exchange_max_leverage(exchange, symbol: str, fallback: int = 15) -> int:
    try:
        market = exchange.market(symbol)
        max_lev = safe_float((market.get("limits", {}).get("leverage") or {}).get("max"), 0)
        return max(1, int(max_lev)) if max_lev > 0 else max(1, int(fallback))
    except Exception:
        return max(1, int(fallback))


def market_limits(exchange, symbol: str) -> Tuple[float, float]:
    try:
        limits = exchange.market(symbol).get("limits", {})
        return (
            safe_float((limits.get("amount") or {}).get("min")),
            safe_float((limits.get("cost") or {}).get("min")),
        )
    except Exception:
        return 0.0, 0.0


def set_margin_mode_safe(exchange, symbol: str) -> bool:
    try:
        exchange.set_margin_mode("isolated", symbol)
        return True
    except Exception as exc:
        log.debug("set_margin_mode isolated failed %s: %s", symbol, exc)
        return False


def set_leverage_safe(exchange, symbol: str, leverage: int) -> bool:
    try:
        exchange.set_leverage(int(leverage), symbol, {"marginMode": "isolated"})
        return True
    except Exception as first_exc:
        try:
            exchange.set_leverage(int(leverage), symbol)
            return True
        except Exception as second_exc:
            log.warning("set_leverage failed %s %sx: %s / %s", symbol, leverage, first_exc, second_exc)
            return False


# ============================================================
# INDICATORS / SIGNALS
# ============================================================

def calculate_indicators(df: pd.DataFrame, ema_fast: int, ema_slow: int, adx_period: int = 14) -> pd.DataFrame:
    out = df.copy()
    out.columns = [str(c).lower() for c in out.columns]

    for col in ["open", "high", "low", "close", "volume"]:
        if col not in out.columns:
            out[col] = np.nan
        out[col] = pd.to_numeric(out[col], errors="coerce")

    fast = max(1, int(ema_fast))
    slow = max(fast + 1, int(ema_slow))
    period = max(2, int(adx_period))

    out["ema_fast"] = out["close"].ewm(span=fast, adjust=False, min_periods=fast).mean()
    out["ema_slow"] = out["close"].ewm(span=slow, adjust=False, min_periods=slow).mean()

    e12 = out["close"].ewm(span=12, adjust=False, min_periods=12).mean()
    e26 = out["close"].ewm(span=26, adjust=False, min_periods=26).mean()
    out["macd"] = e12 - e26
    out["macd_signal"] = out["macd"].ewm(span=9, adjust=False, min_periods=9).mean()
    out["macd_hist"] = out["macd"] - out["macd_signal"]

    prev_close = out["close"].shift(1)
    tr = pd.concat([
        out["high"] - out["low"],
        (out["high"] - prev_close).abs(),
        (out["low"] - prev_close).abs(),
    ], axis=1).max(axis=1)

    up = out["high"].diff()
    down = -out["low"].diff()
    plus_dm = pd.Series(np.where((up > down) & (up > 0), up, 0.0), index=out.index)
    minus_dm = pd.Series(np.where((down > up) & (down > 0), down, 0.0), index=out.index)

    alpha = 1.0 / period
    tr_s = tr.ewm(alpha=alpha, adjust=False, min_periods=period).mean()
    plus_s = plus_dm.ewm(alpha=alpha, adjust=False, min_periods=period).mean()
    minus_s = minus_dm.ewm(alpha=alpha, adjust=False, min_periods=period).mean()

    tr_safe = tr_s.where(tr_s > 0)
    out["plus_di"] = (100.0 * plus_s / tr_safe).clip(0, 100)
    out["minus_di"] = (100.0 * minus_s / tr_safe).clip(0, 100)
    di_sum = (out["plus_di"] + out["minus_di"]).where((out["plus_di"] + out["minus_di"]) > 0)
    out["dx"] = (100.0 * (out["plus_di"] - out["minus_di"]).abs() / di_sum).clip(0, 100)
    out["adx"] = out["dx"].ewm(alpha=alpha, adjust=False, min_periods=period).mean().clip(0, 100)

    delta = out["close"].diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(alpha=1 / 14, adjust=False, min_periods=14).mean()
    avg_loss = loss.ewm(alpha=1 / 14, adjust=False, min_periods=14).mean()
    rs = avg_gain / avg_loss.where(avg_loss > 0)
    out["rsi"] = 100.0 - 100.0 / (1.0 + rs)
    out.loc[(avg_loss <= 0) & (avg_gain > 0), "rsi"] = 100.0
    out.loc[(avg_gain <= 0) & (avg_loss > 0), "rsi"] = 0.0
    out["rsi"] = out["rsi"].clip(0, 100)

    return out


def get_dynamic_parameters(df: pd.DataFrame, tf: str) -> Dict[str, float]:
    try:
        temp = df.copy()
        temp.columns = [str(c).lower() for c in temp.columns]
        closes = pd.to_numeric(temp["close"], errors="coerce").dropna().values
        if len(closes) < 30:
            raise ValueError("not enough data")
        returns = np.diff(closes) / closes[:-1]
        vol = float(np.std(returns) * np.sqrt(len(returns)))

        if tf in {"1m", "5m"}:
            return {
                "ema_fast": 5 if vol > 0.02 else 9,
                "ema_slow": 13 if vol > 0.02 else 21,
                "min_adx": 22.0 if vol > 0.02 else 26.0,
                "max_rsi": 72.0 if vol > 0.02 else 75.0,
                "min_rsi": 28.0 if vol > 0.02 else 25.0,
                "capital_multiplier": 0.6 if vol > 0.02 else 0.8,
            }
        if tf in {"15m", "30m"}:
            return {
                "ema_fast": 7 if vol > 0.03 else 10,
                "ema_slow": 18 if vol > 0.03 else 25,
                "min_adx": 24.0 if vol > 0.03 else 25.0,
                "max_rsi": 70.0 if vol > 0.03 else 78.0,
                "min_rsi": 30.0 if vol > 0.03 else 22.0,
                "capital_multiplier": 1.0 if vol > 0.03 else 1.2,
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
            "ema_fast": 9, "ema_slow": 21, "min_adx": 25.0,
            "max_rsi": 75.0, "min_rsi": 25.0, "capital_multiplier": 1.0
        }


def signal_from_closed_candle(df: pd.DataFrame, cfg: Dict[str, Any], auto_base_influence: float = 0.5) -> Tuple[str, Dict[str, float]]:
    if df is None or len(df) < 80:
        return "NEUTRALNY", {}

    fast = max(1, int(cfg.get("ema_fast", 9)))
    slow = max(fast + 1, int(cfg.get("ema_slow", 21)))
    min_adx = float(cfg.get("min_adx", cfg.get("adx", 28.0)))
    max_rsi = float(cfg.get("max_rsi", 75.0))
    min_rsi = float(cfg.get("min_rsi", 25.0))
    cap_mult = float(cfg.get("capital_multiplier", cfg.get("cap_mult", 1.0)))

    if cfg.get("mode") == "Automatyczny":
        auto = get_dynamic_parameters(df, cfg.get("tf", "15m"))
        w = max(0.0, min(1.0, float(auto_base_influence)))
        min_adx = min_adx * w + float(auto["min_adx"]) * (1 - w)
        max_rsi = max_rsi * w + float(auto["max_rsi"]) * (1 - w)
        min_rsi = min_rsi * w + float(auto["min_rsi"]) * (1 - w)
        cap_mult = cap_mult * w + float(auto["capital_multiplier"]) * (1 - w)

    ind = calculate_indicators(df, fast, slow, 14)
    if len(ind) < max(80, slow + 30):
        return "NEUTRALNY", {}

    last = ind.iloc[-2]
    prev = ind.iloc[-3]
    required = ["close", "adx", "rsi", "plus_di", "minus_di", "ema_fast", "ema_slow", "macd_hist"]

    for c in required:
        if not np.isfinite(safe_float(last[c], np.nan)):
            return "NEUTRALNY", {}
    for c in ["ema_fast", "ema_slow", "plus_di", "minus_di", "macd_hist"]:
        if not np.isfinite(safe_float(prev[c], np.nan)):
            return "NEUTRALNY", {}

    values = {
        "price": float(last["close"]),
        "adx": float(last["adx"]),
        "rsi": float(last["rsi"]),
        "plus_di": float(last["plus_di"]),
        "minus_di": float(last["minus_di"]),
        "ema_fast": float(last["ema_fast"]),
        "ema_slow": float(last["ema_slow"]),
        "macd_hist": float(last["macd_hist"]),
        "prev_ema_fast": float(prev["ema_fast"]),
        "prev_ema_slow": float(prev["ema_slow"]),
        "capital_multiplier": cap_mult,
        "min_adx": min_adx,
        "max_rsi": max_rsi,
        "min_rsi": min_rsi,
    }

    long_ok = (
        last["ema_fast"] > last["ema_slow"]
        and prev["ema_fast"] > prev["ema_slow"]
        and last["plus_di"] > last["minus_di"]
        and prev["plus_di"] >= prev["minus_di"]
        and last["macd_hist"] > 0
        and prev["macd_hist"] >= 0
        and last["close"] > last["ema_fast"]
        and values["adx"] >= min_adx
        and 50.0 < values["rsi"] < max_rsi
    )
    short_ok = (
        last["ema_fast"] < last["ema_slow"]
        and prev["ema_fast"] < prev["ema_slow"]
        and last["minus_di"] > last["plus_di"]
        and prev["minus_di"] >= prev["plus_di"]
        and last["macd_hist"] < 0
        and prev["macd_hist"] <= 0
        and last["close"] < last["ema_fast"]
        and values["adx"] >= min_adx
        and min_rsi < values["rsi"] < 50.0
    )

    return ("LONG" if long_ok else "SHORT" if short_ok else "NEUTRALNY"), values


# ============================================================
# RISK / ORDERS
# ============================================================

def calculate_risk_allocation( free_balance: float, entry: float, stop_price: float, leverage: int, max_single: float, tf_multiplier: float, ) -> float:
    if free_balance <= 0 or entry <= 0 or stop_price <= 0:
        return 0.0

    risk_amount = free_balance * DEFAULT_RISK_PCT
    distance = max(abs(entry - stop_price) / entry, 0.005)
    risk_notional = risk_amount / distance

    max_notional = min(
        free_balance * max(1, leverage) * 0.90,
        max_single * max(tf_multiplier, 0.1) * max(1, leverage),
    )
    return max(0.0, min(risk_notional, max_notional))


def roe_to_price(entry: float, roe_percent: float, leverage: float, long: bool) -> float:
    move = abs(float(roe_percent)) / max(float(leverage), 1.0) / 100.0
    return entry * (1.0 - move if long else 1.0 + move)


def normalize_price(exchange, symbol: str, price: float) -> float:
    try:
        return float(exchange.price_to_precision(symbol, price))
    except Exception:
        return float(price)


def create_trigger_order(exchange, symbol: str, side: str, amount: float, trigger_price: float, kind: str):
    trigger_price = normalize_price(exchange, symbol, trigger_price)
    amount = float(exchange.amount_to_precision(symbol, amount))
    if amount <= 0 or trigger_price <= 0:
        return None

    params = {"triggerPrice": trigger_price, "reduceOnly": True}
    params["stopLossPrice" if kind == "stop" else "takeProfitPrice"] = trigger_price

    attempts = [
        params,
        {"triggerPrice": trigger_price, "reduceOnly": True},
        {"stopPrice": trigger_price, "reduceOnly": True},
    ]
    for p in attempts:
        try:
            order = exchange.create_order(symbol, "market", side, amount, None, p)
            if order:
                return order
        except Exception as exc:
            log.warning("Protection %s failed %s: %s", kind, symbol, exc)
    return None


def place_entry_with_protection( exchange, symbol: str, signal: str, contracts: float, leverage: int, stop_roe: float, take_roe: float, user_id: int ):
    side = "buy" if signal == "LONG" else "sell"
    try:
        contracts = float(exchange.amount_to_precision(symbol, contracts))
        if contracts <= 0:
            raise ValueError("contracts <= 0")

        set_margin_mode_safe(exchange, symbol)

        try:
            order = exchange.create_order(symbol, "market", side, contracts, None, {})
        except (ccxt.InvalidOrder, ccxt.BadRequest) as first_exc:
            hedge_params = {"posSide": "long" if signal == "LONG" else "short"}
            log.warning("Retrying hedge-mode entry %s: %s", symbol, first_exc)
            order = exchange.create_order(symbol, "market", side, contracts, None, hedge_params)
        except Exception as exc:
            log.error("ENTRY failed %s %s: %s", symbol, signal, exc)
            return None, None, None

        entry = safe_float(order.get("average")) or safe_float(order.get("price"))
        if entry <= 0:
            time.sleep(0.15)
            p = find_position(fetch_positions_safe(exchange), symbol)
            if p:
                entry = safe_float(p.get("entryPrice"))
        if entry <= 0:
            return order, None, None

        long = signal == "LONG"
        stop_price = normalize_price(exchange, symbol, roe_to_price(entry, stop_roe, leverage, long))
        take_price = normalize_price(exchange, symbol, roe_to_price(entry, take_roe, leverage, long))
        close_side = "sell" if long else "buy"

        sl_order = create_trigger_order(exchange, symbol, close_side, contracts, stop_price, "stop")
        tp_order = create_trigger_order(exchange, symbol, close_side, contracts, take_price, "take")

        save_protection_state(
            user_id, symbol, "long" if long else "short", contracts, entry,
            leverage, stop_price, take_price,
            str((sl_order or {}).get("id", "")),
            str((tp_order or {}).get("id", "")),
        )
        return order, stop_price, take_price
    except Exception:
        log.exception("place_entry_with_protection failed %s", symbol)
        return None, None, None


# ============================================================
# PERSISTENT PROTECTION / GUARDS / LOG
# ============================================================

def save_protection_state(user_id: int, symbol: str, side: str, amount: float, entry_price: float, leverage: float, stop_price: float, take_price: float, stop_order_id: str = "", take_order_id: str = "") -> None:
    conn = db_connect()
    try:
        conn.execute(""" INSERT INTO protection_state (user_id,symbol,side,amount,entry_price,leverage,stop_price,take_price,stop_order_id,take_order_id,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(user_id,symbol) DO UPDATE SET side=excluded.side, amount=excluded.amount, entry_price=excluded.entry_price, leverage=excluded.leverage, stop_price=excluded.stop_price, take_price=excluded.take_price, stop_order_id=excluded.stop_order_id, take_order_id=excluded.take_order_id, updated_at=excluded.updated_at """, (user_id, symbol, side, amount, entry_price, leverage, stop_price, take_price,
              stop_order_id, take_order_id, utc_now()))
        conn.commit()
    finally:
        conn.close()


def delete_protection_state(user_id: int, symbol: str) -> None:
    conn = db_connect()
    try:
        conn.execute("DELETE FROM protection_state WHERE user_id=? AND symbol=?", (int(user_id), symbol))
        conn.commit()
    finally:
        conn.close()


def get_entry_guard(user_id: int, symbol: str) -> Dict[str, Any]:
    conn = db_connect()
    try:
        row = conn.execute(
            "SELECT locked_until,last_candle,last_side FROM entry_guard WHERE user_id=? AND symbol=?",
            (int(user_id), symbol)
        ).fetchone()
    finally:
        conn.close()
    if not row:
        return {"locked_until": 0.0, "last_candle": 0, "last_side": ""}
    return {"locked_until": safe_float(row[0]), "last_candle": int(row[1] or 0), "last_side": str(row[2] or "")}


def set_entry_guard(user_id: int, symbol: str, locked_until: float, last_candle: int = 0, last_side: str = "") -> None:
    conn = db_connect()
    try:
        conn.execute(""" INSERT INTO entry_guard(user_id,symbol,locked_until,last_candle,last_side,updated_at) VALUES(?,?,?,?,?,?) ON CONFLICT(user_id,symbol) DO UPDATE SET locked_until=excluded.locked_until, last_candle=excluded.last_candle, last_side=excluded.last_side, updated_at=excluded.updated_at """, (int(user_id), symbol, float(locked_until), int(last_candle), str(last_side), utc_now()))
        conn.commit()
    finally:
        conn.close()


def entry_guard_blocks(user_id: int, symbol: str, candle_ts: int = 0) -> bool:
    guard = get_entry_guard(user_id, symbol)
    return guard["locked_until"] > time.time() or bool(candle_ts and guard["last_candle"] == int(candle_ts))


def log_trade(user_id: int, symbol: str, tf: str, action: str, side: str, price: float = 0.0, amount: float = 0.0, order_id: str = "", message: str = "") -> None:
    conn = db_connect()
    try:
        conn.execute(""" INSERT INTO trade_log (user_id,created_at,symbol,timeframe,action,side,price,amount,order_id,message) VALUES(?,?,?,?,?,?,?,?,?,?) """, (user_id, utc_now(), symbol, tf, action, side, price, amount, order_id, message))
        conn.commit()
    finally:
        conn.close()


# ============================================================
# USER SETTINGS / SCANNER DB
# ============================================================

def get_all_trading_users() -> List[Dict[str, Any]]:
    conn = db_connect()
    try:
        rows = conn.execute(""" SELECT id,email,api_key,secret_key,passphrase,selected_exchange,is_admin,stripe_paid FROM users WHERE api_key<>'' AND secret_key<>'' """).fetchall()
    finally:
        conn.close()
    return [{
        "id": int(r[0]), "email": r[1], "api_key": r[2] or "",
        "secret_key": r[3] or "", "passphrase": r[4] or "",
        "exchange": r[5] or "Bitget", "is_admin": bool(r[6]), "paid": bool(r[7])
    } for r in rows]


def get_user_risk_settings(user_id: int) -> Dict[str, Any]:
    base = {
        "max_single": DEFAULT_MAX_SINGLE,
        "max_positions": DEFAULT_MAX_POSITIONS,
        "enable_roe": True,
        "stop_roe": DEFAULT_STOP_ROE,
        "take_roe": DEFAULT_TAKE_ROE,
        "max_leverage": DEFAULT_MAX_LEVERAGE,
        "manual_leverage": DEFAULT_MANUAL_LEVERAGE,
        "leverage_mode": "Autonomiczny (płynny w granicach limitu)",
        "max_scan_pairs": DEFAULT_MAX_SCAN_PAIRS,
        "auto_base_influence": 50,
        "cooldown_minutes": 15,
    }
    conn = db_connect()
    try:
        row = conn.execute("SELECT settings_json FROM users WHERE id=?", (int(user_id),)).fetchone()
    finally:
        conn.close()
    if row and row[0]:
        try:
            saved = json.loads(row[0])
            if isinstance(saved, dict):
                base.update(saved)
        except Exception:
            pass
    return base


def save_user_risk_settings(user_id: int, settings: Dict[str, Any]) -> None:
    conn = db_connect()
    try:
        conn.execute("UPDATE users SET settings_json=? WHERE id=?", (json.dumps(settings, ensure_ascii=False), int(user_id)))
        conn.commit()
    finally:
        conn.close()


def clear_scanner_rows(user_id: int, timeframe: Optional[str] = None) -> None:
    conn = db_connect()
    try:
        if timeframe:
            conn.execute("DELETE FROM scanner_results WHERE user_id=? AND timeframe=?", (int(user_id), timeframe))
        else:
            conn.execute("DELETE FROM scanner_results WHERE user_id=?", (int(user_id),))
        conn.commit()
    finally:
        conn.close()


def save_scanner_rows(user_id: int, rows: List[Dict[str, Any]]) -> None:
    if not rows:
        return
    conn = db_connect()
    try:
        now = utc_now()
        for row in rows:
            conn.execute(""" INSERT INTO scanner_results (user_id,timeframe,symbol,quote_volume,price,adx,rsi,ema_fast,ema_slow,signal,candle_ts,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(user_id,timeframe,symbol) DO UPDATE SET quote_volume=excluded.quote_volume, price=excluded.price, adx=excluded.adx, rsi=excluded.rsi, ema_fast=excluded.ema_fast, ema_slow=excluded.ema_slow, signal=excluded.signal, candle_ts=excluded.candle_ts, updated_at=excluded.updated_at """, (
                int(user_id), row["timeframe"], row["symbol"], float(row["quote_volume"]),
                float(row["price"]), float(row["adx"]), float(row["rsi"]),
                float(row["ema_fast"]), float(row["ema_slow"]), row["signal"],
                int(row["candle_ts"]), now
            ))
        conn.commit()
    finally:
        conn.close()


def read_scanner_rows(user_id: int, limit: int = 500, active_timeframes: Optional[List[str]] = None) -> pd.DataFrame:
    conn = db_connect()
    try:
        where = [
            "user_id=?",
            "adx >= 0 AND adx <= 100",
            "rsi >= 0 AND rsi <= 100",
            "ema_fast > 0 AND ema_slow > 0",
            "price > 0",
        ]
        params: List[Any] = [int(user_id)]
        if active_timeframes:
            active = [tf for tf in active_timeframes if tf in AVAILABLE_TIMEFRAMES]
            if active:
                placeholders = ",".join("?" for _ in active)
                where.append(f"timeframe IN ({placeholders})")
                params.extend(active)

        query = f""" SELECT timeframe AS Interwał, symbol AS Para, price AS Cena, adx AS ADX, rsi AS RSI, ema_fast AS EMA_Szybka, ema_slow AS EMA_Wolna, signal AS Sygnał, quote_volume AS Wolumen_24h, updated_at AS Aktualizacja FROM scanner_results WHERE {' AND '.join(where)} ORDER BY updated_at DESC, timeframe ASC, quote_volume DESC, symbol ASC LIMIT ? """
        params.append(int(limit))
        return pd.read_sql_query(query, conn, params=params)
    except Exception:
        log.exception("Scanner DB read failed")
        return pd.DataFrame()
    finally:
        conn.close()


# ============================================================
# WORKER
# ============================================================

class UserWorker:
    def __init__(self, user: Dict[str, Any]):
        self.user = user
        self.user_id = int(user["id"])
        self.exchange = get_exchange(user["api_key"], user["secret_key"], user["passphrase"], user["exchange"])
        self.cooldowns: Dict[str, float] = {}
        self.entry_locks: Dict[str, float] = {}
        self.last_protection_check = 0.0
        self.scan_cursor_by_tf: Dict[str, int] = {}
        self.scan_tf_index = 0
        self.last_tickers_at = 0.0
        self.cached_tickers: Dict[str, Any] = {}
        self.last_ranked_at = 0.0
        self.cached_ranked: List[Tuple[str, float]] = []
        self.markets_loaded = False
        self.scanner_initialized = False

    def run_once(self) -> None:
        if self.exchange is None:
            return

        bots = load_active_bots(self.user_id)
        if not bots:
            return

        if not self.scanner_initialized:
            clear_scanner_rows(self.user_id)
            self.scanner_initialized = True

        risk = get_user_risk_settings(self.user_id)

        if not self.markets_loaded:
            if not load_markets_safe(self.exchange):
                return
            self.markets_loaded = True

        now = time.time()

        if now - self.last_tickers_at >= 60 or not self.cached_tickers:
            try:
                self.cached_tickers = fetch_futures_tickers(self.exchange)
                self.last_tickers_at = now
            except Exception:
                log.exception("Futures ticker fetch failed user=%s", self.user_id)
                return

        if not self.cached_tickers:
            return

        tickers = self.cached_tickers
        self.protect_open_positions(risk)

        positions = fetch_positions_safe(self.exchange)
        pos_map = {
            p.get("symbol"): p for p in positions
            if p.get("symbol") and position_contracts(p) > 0
        }
        active_count = len(pos_map)
        free_balance = fetch_usdt_balance(self.exchange)["free"]

        if now - self.last_ranked_at >= 60 or not self.cached_ranked:
            self.cached_ranked = rank_liquid_symbols(
                self.exchange, tickers, int(risk["max_scan_pairs"])
            )
            self.last_ranked_at = now

        ranked = self.cached_ranked[:max(1, int(risk["max_scan_pairs"]))]
        if not ranked:
            return

        tf_priority = ["1h", "4h", "1d", "30m", "15m", "5m", "1m"]
        active_tfs = [tf for tf in tf_priority if tf in bots]
        if not active_tfs:
            return

        if self.scan_tf_index >= len(active_tfs):
            self.scan_tf_index = 0

        tf = active_tfs[self.scan_tf_index]
        cfg = dict(bots[tf])
        cfg["tf"] = tf

        cursor = int(self.scan_cursor_by_tf.get(tf, 0))
        if cursor >= len(ranked):
            cursor = 0

        batch = ranked[cursor:cursor + SCAN_BATCH_SIZE]
        next_cursor = cursor + len(batch)
        finished_tf = next_cursor >= len(ranked)
        self.scan_cursor_by_tf[tf] = 0 if finished_tf else next_cursor
        if finished_tf:
            self.scan_tf_index = (self.scan_tf_index + 1) % len(active_tfs)

        scanner_rows = []

        for symbol, qv in batch:
            try:
                limit = 180 if tf == "1d" else min(180, max(100, int(cfg["ema_slow"]) + 60))
                ohlcv = fetch_ohlcv_safe(self.exchange, symbol, tf, limit)
                if len(ohlcv) < 80:
                    continue

                closed_candle_ts = int(ohlcv[-2][0])
                df = pd.DataFrame(ohlcv, columns=["timestamp", "open", "high", "low", "close", "volume"])

                signal, vals = signal_from_closed_candle(
                    df, cfg, float(risk["auto_base_influence"]) / 100.0
                )
                if not vals:
                    continue

                required = ["price", "adx", "rsi", "ema_fast", "ema_slow"]
                if any(not np.isfinite(safe_float(vals.get(k), np.nan)) for k in required):
                    continue

                # This prevents the old "cosmic" values caused by invalid/default rows.
                closes = pd.to_numeric(df["close"], errors="coerce").dropna()
                if len(closes) < 30:
                    continue

                last_close = float(closes.iloc[-2])
                local_min = float(closes.tail(30).min())
                local_max = float(closes.tail(30).max())
                if not (local_min <= float(vals["ema_fast"]) <= local_max):
                    continue
                if not (local_min <= float(vals["ema_slow"]) <= local_max):
                    continue

                scanner_rows.append({
                    "timeframe": tf,
                    "symbol": symbol,
                    "quote_volume": qv,
                    "price": float(vals["price"]),
                    "adx": float(vals["adx"]),
                    "rsi": float(vals["rsi"]),
                    "ema_fast": float(vals["ema_fast"]),
                    "ema_slow": float(vals["ema_slow"]),
                    "signal": signal,
                    "candle_ts": closed_candle_ts,
                })

                if signal == "NEUTRALNY" or active_count >= int(risk["max_positions"]):
                    continue
                if symbol in pos_map:
                    continue
                if time.time() < self.cooldowns.get(symbol, 0) or time.time() < self.entry_locks.get(symbol, 0):
                    continue
                if entry_guard_blocks(self.user_id, symbol, closed_candle_ts):
                    continue

                max_ex = exchange_max_leverage(self.exchange, symbol, int(risk["max_leverage"]))
                if str(risk["leverage_mode"]).startswith("Ręczny"):
                    lev = min(int(risk["manual_leverage"]), max_ex)
                else:
                    adx = safe_float(vals.get("adx"), 20.0)
                    ratio = min(1.0, max(0.0, (adx - 10.0) / 45.0))
                    lev = max(1, int(round(
                        1 + ratio * (min(int(risk["max_leverage"]), max_ex) - 1)
                    )))

                if not set_leverage_safe(self.exchange, symbol, lev):
                    continue

                entry_hint = safe_float((tickers.get(symbol) or {}).get("last")) or safe_float(vals["price"])
                if entry_hint <= 0:
                    continue

                initial_stop = roe_to_price(entry_hint, float(risk["stop_roe"]), lev, signal == "LONG")
                notional = calculate_risk_allocation(
                    free_balance, entry_hint, initial_stop, lev,
                    float(risk["max_single"]),
                    float(vals.get("capital_multiplier", 1.0)),
                )
                if notional <= 0:
                    continue

                base_amount = notional / entry_hint
                contracts = base_amount_to_contracts(self.exchange, symbol, base_amount)

                min_amt, min_cost = market_limits(self.exchange, symbol)
                if min_amt and contracts < min_amt:
                    contracts = min_amt
                if min_cost:
                    current_quote = contracts * contract_size(self.exchange, symbol) * entry_hint
                    if current_quote < min_cost:
                        contracts = min_cost / entry_hint / contract_size(self.exchange, symbol)

                contracts = float(self.exchange.amount_to_precision(symbol, contracts))
                if contracts <= 0:
                    continue

                lock_seconds = max(300.0, float(risk.get("cooldown_minutes", 15)) * 60)
                self.entry_locks[symbol] = time.time() + 30

                order, sl_price, tp_price = place_entry_with_protection(
                    self.exchange, symbol, signal, contracts, lev,
                    float(risk["stop_roe"]), float(risk["take_roe"]), self.user_id
                )

                if order:
                    active_count += 1
                    pos_map[symbol] = {
                        "symbol": symbol,
                        "contracts": contracts,
                        "side": "long" if signal == "LONG" else "short",
                    }
                    self.cooldowns[symbol] = time.time() + lock_seconds
                    set_entry_guard(self.user_id, symbol, time.time() + lock_seconds, closed_candle_ts, signal)
                    log_trade(
                        self.user_id, symbol, tf, "ENTRY", signal, entry_hint, contracts,
                        str(order.get("id", "")),
                        f"SL={sl_price};TP={tp_price};LEV={lev}"
                    )
            except Exception:
                log.exception("Signal/order failed user=%s tf=%s symbol=%s", self.user_id, tf, symbol)

        if scanner_rows:
            save_scanner_rows(self.user_id, scanner_rows)

    def protect_open_positions(self, risk: Dict[str, Any]) -> None:
        if not bool(risk.get("enable_roe", True)):
            return
        if time.time() - self.last_protection_check < POSITION_GUARD_SECONDS:
            return
        self.last_protection_check = time.time()

        for p in fetch_positions_safe(self.exchange):
            amount = position_contracts(p)
            if amount <= 0:
                continue

            symbol = p.get("symbol", "")
            entry = safe_float(p.get("entryPrice"))
            mark = safe_float(p.get("markPrice")) or safe_float(p.get("lastPrice"))
            lev = safe_float(p.get("leverage"), 1.0)
            if not symbol or entry <= 0 or mark <= 0:
                continue

            raw_move = ((mark - entry) / entry) * 100 if is_long(p) else ((entry - mark) / entry) * 100
            roe = raw_move * max(1.0, lev)

            if roe <= -float(risk["stop_roe"]) or roe >= float(risk["take_roe"]):
                side_tag = "SL" if roe <= -float(risk["stop_roe"]) else "TP"
                if close_position(self.exchange, p, f"ROE {side_tag} {roe:.2f}%"):
                    guard_until = time.time() + float(risk.get("cooldown_minutes", 15)) * 60
                    self.cooldowns[symbol] = guard_until
                    self.entry_locks[symbol] = guard_until
                    set_entry_guard(self.user_id, symbol, guard_until, 0, side_tag)
                    delete_protection_state(self.user_id, symbol)
                    log_trade(
                        self.user_id, symbol, "guard", side_tag, position_side(p),
                        mark, amount, message=f"ROE={roe:.2f}%"
                    )

    def loop(self, stop_event: threading.Event) -> None:
        log.info("Worker started user=%s exchange=%s", self.user_id, self.user.get("exchange"))
        while not stop_event.is_set():
            try:
                self.run_once()
            except Exception:
                log.exception("Worker top-level error user=%s", self.user_id)
            stop_event.wait(WORKER_POLL_SECONDS)
        log.info("Worker stopped user=%s", self.user_id)


def run_worker_mode() -> None:
    init_db()
    stop_event = threading.Event()
    workers: List[UserWorker] = []
    threads: List[threading.Thread] = []

    try:
        while not stop_event.is_set():
            users = get_all_trading_users()
            active_ids = set()

            for user in users:
                uid = int(user["id"])
                bots = load_active_bots(uid)
                if not bots:
                    continue
                active_ids.add(uid)

                existing = next((w for w in workers if w.user_id == uid), None)
                existing_thread = next((t for t in threads if t.name == f"worker-user-{uid}"), None)

                if existing is None or existing_thread is None or not existing_thread.is_alive():
                    worker = UserWorker(user)
                    thread = threading.Thread(
                        target=worker.loop,
                        args=(stop_event,),
                        daemon=True,
                        name=f"worker-user-{uid}",
                    )
                    workers.append(worker)
                    threads.append(thread)
                    thread.start()
                    log.info("Worker process started user=%s", uid)

            # Clean up dead thread references.
            workers = [w for w in workers if w.user_id in active_ids or any(t.name == f"worker-user-{w.user_id}" and t.is_alive() for t in threads)]
            threads = [t for t in threads if t.is_alive()]

            time.sleep(max(2, WORKER_POLL_SECONDS))
    except KeyboardInterrupt:
        log.info("Stopping worker process...")
    finally:
        stop_event.set()
        for thread in threads:
            try:
                thread.join(timeout=5)
            except Exception:
                pass
        gc.collect()


# ============================================================
# AUTH / UI
# ============================================================

SESSION_DEFAULTS = {
    "logged_in": False,
    "user_email": "",
    "is_admin": False,
    "user_id": None,
    "stripe_paid": False,
    "session_start_time": datetime.now(),
    "lang": "Polski",
    "api_key": "",
    "secret_key": "",
    "passphrase": "",
    "selected_exchange": "Bitget",
    "session_start_balance": 0.0,
    "active_mtf_bots": {},
    "_mtf_loaded_user_id": None,
}


def is_user_admin() -> bool:
    email = str(st.session_state.get("user_email", "")).strip().lower()
    return bool(st.session_state.get("is_admin")) or email in {x.lower() for x in ADMIN_EMAILS}


def is_user_paid() -> bool:
    return is_user_admin() or bool(st.session_state.get("stripe_paid"))


def ui_login() -> None:
    st.markdown(
        "<h1 style='text-align:center;'>BITGET FUTURES</h1>"
        "<p style='text-align:center;'>AUTONOMICZNY SYSTEM TRANSAKCYJNY</p>",
        unsafe_allow_html=True,
    )

    tab_login, tab_register = st.tabs([t("login_tab"), t("register_tab")])

    with tab_login:
        email = st.text_input(t("email_label"), key="log_email")
        password = st.text_input(t("pass_label"), type="password", key="log_pass")

        if st.button(t("login_btn"), use_container_width=True):
            conn = db_connect()
            try:
                row = conn.execute(""" SELECT id,email,password,is_admin,stripe_paid,api_key,secret_key,passphrase,selected_exchange FROM users WHERE LOWER(TRIM(email))=? """, (email.strip().lower(),)).fetchone()
            finally:
                conn.close()

            if row and verify_password(password, row[2]):
                st.session_state.logged_in = True
                st.session_state.user_id = int(row[0])
                st.session_state.user_email = row[1]
                st.session_state.is_admin = bool(row[3]) or row[1].strip().lower() in {x.lower() for x in ADMIN_EMAILS}
                st.session_state.stripe_paid = True if st.session_state.is_admin else bool(row[4])
                st.session_state.api_key = row[5] or ""
                st.session_state.secret_key = row[6] or ""
                st.session_state.passphrase = row[7] or ""
                st.session_state.selected_exchange = row[8] or "Bitget"
                st.session_state.active_mtf_bots = load_active_bots(row[0])
                apply_mtf_to_session(row[0], force=True)

                if not str(row[2]).startswith("sha256$"):
                    conn = db_connect()
                    try:
                        conn.execute("UPDATE users SET password=? WHERE id=?", (hash_password(password), row[0]))
                        conn.commit()
                    finally:
                        conn.close()

                st.success(t("login_success"))
                st.rerun()
            else:
                st.error(t("login_error"))

    with tab_register:
        reg_email = st.text_input(t("email_label"), key="reg_email")
        reg_pass = st.text_input(t("pass_label"), type="password", key="reg_pass")

        if st.button(t("register_btn"), use_container_width=True):
            if not reg_email.strip() or not reg_pass:
                st.error(t("reg_error_fill"))
            else:
                conn = db_connect()
                try:
                    try:
                        conn.execute(
                            "INSERT INTO users(email,password) VALUES(?,?)",
                            (reg_email.strip().lower(), hash_password(reg_pass))
                        )
                        conn.commit()
                        st.success(t("reg_success"))
                    except sqlite3.IntegrityError:
                        st.error(t("reg_error_exists"))
                finally:
                    conn.close()


def logout() -> None:
    uid = st.session_state.get("user_id")
    for key in list(st.session_state.keys()):
        del st.session_state[key]
    for key, value in SESSION_DEFAULTS.items():
        st.session_state[key] = value
    if uid:
        st.session_state["_mtf_loaded_user_id"] = None
    st.rerun()


def render_sidebar(user_id: int) -> Dict[str, Any]:
    risk = get_user_risk_settings(user_id)

    with st.sidebar:
        st.markdown(f"**{st.session_state.get('user_email', '')}**")
        st.caption(t("sidebar_role_admin") if is_user_admin() else t("sidebar_role_client"))

        lang = st.selectbox("Język / Language", ["Polski", "English"], key="lang_selector")
        st.session_state.lang = lang

        exchange = st.selectbox(
            t("select_exchange"),
            SUPPORTED_EXCHANGES,
            index=SUPPORTED_EXCHANGES.index(st.session_state.get("selected_exchange", "Bitget"))
            if st.session_state.get("selected_exchange", "Bitget") in SUPPORTED_EXCHANGES else 0,
            key="sidebar_selected_exchange",
        )
        st.session_state.selected_exchange = exchange

        st.subheader(t("exchange_settings"))
        api_key = st.text_input("API Key", value=st.session_state.get("api_key", ""), type="password", key=f"api_{exchange}")
        secret_key = st.text_input("Secret Key", value=st.session_state.get("secret_key", ""), type="password", key=f"secret_{exchange}")
        passphrase = st.text_input("Passphrase", value=st.session_state.get("passphrase", ""), type="password", key=f"pass_{exchange}")

        if st.button(t("save_keys_btn"), use_container_width=True):
            if not api_key or not secret_key:
                st.error(t("keys_error"))
            else:
                conn = db_connect()
                try:
                    conn.execute(""" UPDATE users SET api_key=?, secret_key=?, passphrase=?, selected_exchange=? WHERE id=? """, (api_key, secret_key, passphrase, exchange, int(user_id)))
                    conn.commit()
                    st.session_state.api_key = api_key
                    st.session_state.secret_key = secret_key
                    st.session_state.passphrase = passphrase
                    st.session_state.selected_exchange = exchange
                    st.success(f"{t('keys_saved')} {exchange}")
                finally:
                    conn.close()

        st.subheader(t("sub_zone"))
        st.success(t("sub_active") if is_user_paid() else t("sub_inactive"))

        st.subheader(t("capital_risk"))
        risk["max_single"] = st.number_input(t("max_single"), 1.0, 100000.0, float(risk["max_single"]), 1.0, key="risk_max_single")
        risk["max_positions"] = st.number_input(t("max_pos"), 1, 100, int(risk["max_positions"]), 1, key="risk_max_positions")

        st.subheader(t("roe_guard"))
        risk["enable_roe"] = st.checkbox(t("enable_roe"), bool(risk["enable_roe"]), key="risk_enable_roe")
        risk["stop_roe"] = st.number_input(t("sl_roe"), 0.1, 100.0, float(risk["stop_roe"]), 0.1, key="risk_stop_roe")
        risk["take_roe"] = st.number_input(t("tp_roe"), 0.1, 200.0, float(risk["take_roe"]), 0.1, key="risk_take_roe")

        st.subheader(t("leverage_mgmt"))
        modes = ["Autonomiczny (płynny w granicach limitu)", "Ręczny"]
        current_mode = risk["leverage_mode"] if risk["leverage_mode"] in modes else modes[0]
        risk["leverage_mode"] = st.selectbox(t("lev_mode"), modes, index=modes.index(current_mode), key="risk_leverage_mode")
        risk["max_leverage"] = st.number_input(t("max_allowed_lev"), 1, 125, int(risk["max_leverage"]), 1, key="risk_max_lev")
        risk["manual_leverage"] = st.number_input(t("manual_lev"), 1, 125, int(risk["manual_leverage"]), 1, key="risk_manual_lev")

        risk["max_scan_pairs"] = st.number_input(t("max_pairs"), 1, 200, int(risk["max_scan_pairs"]), 1, key="risk_scan_pairs")
        risk["auto_base_influence"] = st.slider("Wpływ ustawień ręcznych / Manual influence", 0, 100, int(risk["auto_base_influence"]), key="risk_auto_influence")
        risk["cooldown_minutes"] = st.number_input("Cooldown (min)", 1, 1440, int(risk["cooldown_minutes"]), 1, key="risk_cooldown")

        if st.button("💾 ZAPISZ RYZYKO", use_container_width=True):
            save_user_risk_settings(user_id, risk)
            st.success("Zapisano ustawienia ryzyka.")

        if st.button(t("logout_btn"), use_container_width=True):
            logout()

    return risk


def render_mtf_panel(user_id: int, risk: Dict[str, Any]) -> None:
    st.subheader(t("bot_control"))

    if not is_user_paid() and not ALLOW_TEST_ACTIVATION:
        st.warning("Aktywacja botów Futures wymaga aktywnej subskrypcji.")
        return

    active = st.session_state.get("active_mtf_bots", {})
    cols = st.columns(len(AVAILABLE_TIMEFRAMES))

    for i, tf in enumerate(AVAILABLE_TIMEFRAMES):
        with cols[i]:
            st.markdown(f"### {tf}")
            st.radio(
                "Tryb",
                ["Automatyczny", "Ręczny"],
                key=f"radio_mode_{tf}",
                horizontal=False,
                label_visibility="collapsed",
                on_change=save_mtf_callback,
            )
            st.number_input(
                f"EMA Szybka ({tf})", 1, 200,
                key=f"ema_f_{tf}",
                on_change=save_mtf_callback,
            )
            st.number_input(
                f"EMA Wolna ({tf})", 2, 300,
                key=f"ema_s_{tf}",
                on_change=save_mtf_callback,
            )
            st.slider(
                f"Min ADX ({tf})", 10.0, 50.0,
                key=f"adx_{tf}",
                on_change=save_mtf_callback,
            )
            st.slider(
                f"Max RSI ({tf})", 50.0, 100.0,
                key=f"max_rsi_{tf}",
                on_change=save_mtf_callback,
            )
            st.slider(
                f"Min RSI ({tf})", 0.0, 50.0,
                key=f"min_rsi_{tf}",
                on_change=save_mtf_callback,
            )
            st.number_input(
                f"CAP × ({tf})", 0.1, 100.0,
                key=f"cap_mult_{tf}",
                on_change=save_mtf_callback,
            )

            cfg = current_mtf_payload()[tf]

            if tf in active:
                st.success("AKTYWNY")
                if st.button(f"⏹ Wyłącz {tf}", key=f"stop_{tf}", use_container_width=True):
                    active.pop(tf, None)
                    st.session_state.active_mtf_bots = active
                    save_active_bots(user_id, active)
                    st.rerun()
            else:
                st.info("NIEAKTYWNY")
                if st.button(f"▶ Uruchom {tf}", key=f"start_{tf}", use_container_width=True):
                    st.session_state.active_mtf_bots[tf] = cfg
                    save_mtf_settings(user_id, current_mtf_payload())
                    save_active_bots(user_id, st.session_state.active_mtf_bots)
                    st.success(f"Uruchomiono {tf}.")
                    st.rerun()

    if st.session_state.get("_mtf_save_error"):
        st.error("Nie udało się zapisać ustawień MTF do bazy.")


def render_scanner(user_id: int) -> None:
    active_tfs = [tf for tf in AVAILABLE_TIMEFRAMES if tf in st.session_state.get("active_mtf_bots", {})]
    df = read_scanner_rows(user_id, 500, active_tfs)

    st.subheader(t("market_scanner_results"))

    if df.empty:
        st.info(t("no_scanner"))
        return

    # Nigdy nie pokazujemy sztucznych zer / wartości domyślnych.
    numeric = ["Cena", "ADX", "RSI", "EMA_Szybka", "EMA_Wolna", "Wolumen_24h"]
    for c in numeric:
        if c in df.columns:
            df[c] = pd.to_numeric(df[c], errors="coerce")

    df = df[
        df["Cena"].gt(0)
        & df["ADX"].between(0, 100)
        & df["RSI"].between(0, 100)
        & df["EMA_Szybka"].gt(0)
        & df["EMA_Wolna"].gt(0)
    ].copy()

    if df.empty:
        st.info("Brak prawidłowych danych wskaźników.")
        return

    st.dataframe(
        df,
        use_container_width=True,
        hide_index=True,
        column_config={
            "Cena": st.column_config.NumberColumn(format="%.8f"),
            "ADX": st.column_config.NumberColumn(format="%.2f"),
            "RSI": st.column_config.NumberColumn(format="%.2f"),
            "EMA_Szybka": st.column_config.NumberColumn(format="%.8f"),
            "EMA_Wolna": st.column_config.NumberColumn(format="%.8f"),
            "Wolumen_24h": st.column_config.NumberColumn(format="%.0f"),
        },
    )


def render_positions(user_id: int) -> None:
    exchange = get_exchange(
        st.session_state.get("api_key", ""),
        st.session_state.get("secret_key", ""),
        st.session_state.get("passphrase", ""),
        st.session_state.get("selected_exchange", "Bitget"),
    )
    st.subheader(t("active_positions"))
    if exchange is None:
        st.info("Brak poprawnych kluczy API.")
        return
    positions = [p for p in fetch_positions_safe(exchange) if position_contracts(p) > 0]
    if not positions:
        st.info(t("no_positions"))
        return

    rows = []
    for p in positions:
        rows.append({
            "Para": p.get("symbol"),
            "Strona": p.get("side"),
            "Kontrakty": position_contracts(p),
            "Entry": safe_float(p.get("entryPrice")),
            "Mark": safe_float(p.get("markPrice")),
            "Leverage": safe_float(p.get("leverage"), 1),
        })
    st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)


def render_history(user_id: int) -> None:
    st.subheader(t("trade_history"))
    conn = db_connect()
    try:
        df = pd.read_sql_query(""" SELECT created_at AS Czas, timeframe AS Interwał, symbol AS Para, action AS Akcja, side AS Strona, price AS Cena, amount AS Ilość, message AS Informacja FROM trade_log WHERE user_id=? ORDER BY id DESC LIMIT 100 """, conn, params=(int(user_id),))
    finally:
        conn.close()
    if df.empty:
        st.info(t("no_history"))
    else:
        st.dataframe(df, use_container_width=True, hide_index=True)


def kill_switch(user_id: int) -> None:
    exchange = get_exchange(
        st.session_state.get("api_key", ""),
        st.session_state.get("secret_key", ""),
        st.session_state.get("passphrase", ""),
        st.session_state.get("selected_exchange", "Bitget"),
    )
    if exchange:
        for p in fetch_positions_safe(exchange):
            if position_contracts(p) > 0:
                close_position(exchange, p, "KILL SWITCH")
    st.session_state.active_mtf_bots = {}
    save_active_bots(user_id, {})
    clear_scanner_rows(user_id)


def run_streamlit_app() -> None:
    st.set_page_config(page_title="Multi-Exchange Futures SaaS", layout="wide")
    init_db()

    for key, value in SESSION_DEFAULTS.items():
        if key not in st.session_state:
            st.session_state[key] = value

    if not st.session_state.logged_in:
        ui_login()
        st.stop()

    user_id = int(st.session_state.user_id)
    apply_mtf_to_session(user_id)
    st.session_state.active_mtf_bots = load_active_bots(user_id)

    risk = render_sidebar(user_id)

    st.markdown(
        f"<h1>{t('title')}</h1><p>{t('subtitle')}</p>",
        unsafe_allow_html=True,
    )

    if st.button(t("kill_switch"), type="primary", use_container_width=True):
        kill_switch(user_id)
        st.success("Wszystkie pozycje zostały zamknięte.")
        st.rerun()

    render_mtf_panel(user_id, risk)

    c1, c2 = st.columns(2)
    with c1:
        render_positions(user_id)
    with c2:
        render_history(user_id)

    render_scanner(user_id)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--worker", action="store_true")
    args, _ = parser.parse_known_args()

    if args.worker:
        run_worker_mode()
    else:
        run_streamlit_app()


if __name__ == "__main__":
    main()

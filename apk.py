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
# KONFIGURACJA
# ============================================================

def env_int(name: str, default: int, minimum: int = 0) -> int:
    """Read an integer environment variable without crashing the app."""
    try:
        return max(minimum, int(os.getenv(name, str(default))))
    except (TypeError, ValueError):
        return max(minimum, int(default))

DB_FILE = os.getenv("DB_FILE", "users.db")
LOG_FILE = os.getenv("BOT_LOG_FILE", "trading_bot.log")
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
SCAN_CACHE_SECONDS = env_int("SCAN_CACHE_SECONDS", 15, 5)
SCAN_BATCH_SIZE = env_int("SCAN_BATCH_SIZE", 8, 3)
UI_REFRESH_DEFAULT = env_int("UI_REFRESH_SECONDS", 10, 5)

if stripe is not None and STRIPE_SECRET_KEY:
    stripe.api_key = STRIPE_SECRET_KEY

logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO").upper(),
    format="%(asctime)s | %(levelname)s | %(threadName)s | %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(LOG_FILE, encoding="utf-8"),
    ],
)
log = logging.getLogger("futures_saas")


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
        "session_results": "📊 Session Results (PnL %)",
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
# NARZĘDZIA
# ============================================================

def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def safe_float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None:
            return default
        x = float(value)
        if not np.isfinite(x):
            return default
        return x
    except Exception:
        return default


def db_connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_FILE, timeout=30.0, check_same_thread=False)
    conn.execute("PRAGMA busy_timeout=30000")
    return conn


# ============================================================
# BAZA
# ============================================================

def init_db() -> None:
    conn = db_connect()
    try:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute(""" CREATE TABLE IF NOT EXISTS users ( id INTEGER PRIMARY KEY AUTOINCREMENT, email TEXT UNIQUE, password TEXT, is_admin INTEGER DEFAULT 0, stripe_paid INTEGER DEFAULT 0, api_key TEXT DEFAULT '', secret_key TEXT DEFAULT '', passphrase TEXT DEFAULT '', selected_exchange TEXT DEFAULT 'Bitget', settings_json TEXT DEFAULT '{}' ) """)
        conn.execute(""" CREATE TABLE IF NOT EXISTS user_mtf_settings ( user_id INTEGER PRIMARY KEY, settings_json TEXT NOT NULL, updated_at TEXT NOT NULL, FOREIGN KEY(user_id) REFERENCES users(id) ) """)
        conn.execute(""" CREATE TABLE IF NOT EXISTS user_bot_state ( user_id INTEGER PRIMARY KEY, active_bots_json TEXT NOT NULL DEFAULT '{}', updated_at TEXT NOT NULL, FOREIGN KEY(user_id) REFERENCES users(id) ) """)
        conn.execute(""" CREATE TABLE IF NOT EXISTS trade_log ( id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL, created_at TEXT NOT NULL, symbol TEXT, timeframe TEXT, action TEXT, side TEXT, price REAL, amount REAL, order_id TEXT, message TEXT, FOREIGN KEY(user_id) REFERENCES users(id) ) """)
        conn.execute(""" CREATE TABLE IF NOT EXISTS entry_guard ( user_id INTEGER NOT NULL, symbol TEXT NOT NULL, locked_until REAL NOT NULL DEFAULT 0, last_candle INTEGER NOT NULL DEFAULT 0, last_side TEXT DEFAULT '', updated_at TEXT NOT NULL, PRIMARY KEY(user_id, symbol), FOREIGN KEY(user_id) REFERENCES users(id) ) """)
        conn.execute(""" CREATE TABLE IF NOT EXISTS scanner_results ( user_id INTEGER NOT NULL, timeframe TEXT NOT NULL, symbol TEXT NOT NULL, quote_volume REAL DEFAULT 0, price REAL DEFAULT 0, adx REAL DEFAULT 0, rsi REAL DEFAULT 0, ema_fast REAL DEFAULT 0, ema_slow REAL DEFAULT 0, signal TEXT DEFAULT 'NEUTRALNY', candle_ts INTEGER DEFAULT 0, updated_at TEXT NOT NULL, PRIMARY KEY(user_id, timeframe, symbol), FOREIGN KEY(user_id) REFERENCES users(id) ) """)
        conn.execute(""" CREATE TABLE IF NOT EXISTS protection_state ( user_id INTEGER NOT NULL, symbol TEXT NOT NULL, side TEXT NOT NULL, amount REAL NOT NULL, entry_price REAL NOT NULL, leverage REAL NOT NULL, stop_price REAL NOT NULL, take_price REAL NOT NULL, stop_order_id TEXT DEFAULT '', take_order_id TEXT DEFAULT '', updated_at TEXT NOT NULL, PRIMARY KEY(user_id, symbol), FOREIGN KEY(user_id) REFERENCES users(id) ) """)

        cols = {r[1] for r in conn.execute("PRAGMA table_info(users)").fetchall()}
        migrations = [
            ("selected_exchange", "TEXT DEFAULT 'Bitget'"),
            ("settings_json", "TEXT DEFAULT '{}'"),
        ]
        for name, typ in migrations:
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
# USTAWIENIA MTF
# ============================================================

def default_mtf_payload() -> Dict[str, Dict[str, Any]]:
    return {tf: {**vals, "mode": "Automatyczny"} for tf, vals in DEFAULT_TF_VALUES.items()}


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
            log.exception("Invalid MTF JSON for user=%s", user_id)
    return payload


def save_mtf_settings(user_id: int, payload: Dict[str, Dict[str, Any]]) -> None:
    conn = db_connect()
    try:
        conn.execute(""" INSERT INTO user_mtf_settings(user_id,settings_json,updated_at) VALUES(?,?,?) ON CONFLICT(user_id) DO UPDATE SET settings_json=excluded.settings_json, updated_at=excluded.updated_at """, (int(user_id), json.dumps(payload, ensure_ascii=False), utc_now()))
        conn.commit()
    finally:
        conn.close()


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
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def save_active_bots(user_id: int, bots: Dict[str, Dict[str, Any]]) -> None:
    conn = db_connect()
    try:
        conn.execute(""" INSERT INTO user_bot_state(user_id,active_bots_json,updated_at) VALUES(?,?,?) ON CONFLICT(user_id) DO UPDATE SET active_bots_json=excluded.active_bots_json, updated_at=excluded.updated_at """, (int(user_id), json.dumps(bots, ensure_ascii=False), utc_now()))
        conn.commit()
    finally:
        conn.close()


# ============================================================
# GUARDY / LOG
# ============================================================

def get_entry_guard(user_id: int, symbol: str) -> Dict[str, Any]:
    conn = db_connect()
    try:
        row = conn.execute(""" SELECT locked_until,last_candle,last_side FROM entry_guard WHERE user_id=? AND symbol=? """, (int(user_id), symbol)).fetchone()
    finally:
        conn.close()

    if not row:
        return {"locked_until": 0.0, "last_candle": 0, "last_side": ""}
    return {
        "locked_until": safe_float(row[0]),
        "last_candle": int(row[1] or 0),
        "last_side": str(row[2] or ""),
    }


def set_entry_guard( user_id: int, symbol: str, locked_until: float, last_candle: int = 0, last_side: str = "", ) -> None:
    conn = db_connect()
    try:
        conn.execute(""" INSERT INTO entry_guard( user_id,symbol,locked_until,last_candle,last_side,updated_at ) VALUES(?,?,?,?,?,?) ON CONFLICT(user_id,symbol) DO UPDATE SET locked_until=excluded.locked_until, last_candle=excluded.last_candle, last_side=excluded.last_side, updated_at=excluded.updated_at """, (
            int(user_id), symbol, float(locked_until),
            int(last_candle or 0), str(last_side or ""), utc_now()
        ))
        conn.commit()
    finally:
        conn.close()


def entry_guard_blocks(user_id: int, symbol: str, candle_ts: int = 0) -> bool:
    guard = get_entry_guard(user_id, symbol)
    if guard["locked_until"] > time.time():
        return True
    if candle_ts and guard["last_candle"] == int(candle_ts):
        return True
    return False


def log_trade( user_id: int, symbol: str, tf: str, action: str, side: str, price: float = 0.0, amount: float = 0.0, order_id: str = "", message: str = "", ) -> None:
    conn = db_connect()
    try:
        conn.execute(""" INSERT INTO trade_log( user_id,created_at,symbol,timeframe,action,side, price,amount,order_id,message ) VALUES(?,?,?,?,?,?,?,?,?,?) """, (
            user_id, utc_now(), symbol, tf, action, side,
            price, amount, order_id, message
        ))
        conn.commit()
    finally:
        conn.close()


# ============================================================
# OCHRONA POZYCJI — PERSISTENT
# ============================================================

def save_protection_state( user_id: int, symbol: str, side: str, amount: float, entry_price: float, leverage: float, stop_price: float, take_price: float, stop_order_id: str = "", take_order_id: str = "", ) -> None:
    conn = db_connect()
    try:
        conn.execute(""" INSERT INTO protection_state( user_id,symbol,side,amount,entry_price,leverage, stop_price,take_price,stop_order_id,take_order_id,updated_at ) VALUES(?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(user_id,symbol) DO UPDATE SET side=excluded.side, amount=excluded.amount, entry_price=excluded.entry_price, leverage=excluded.leverage, stop_price=excluded.stop_price, take_price=excluded.take_price, stop_order_id=excluded.stop_order_id, take_order_id=excluded.take_order_id, updated_at=excluded.updated_at """, (
            user_id, symbol, side, amount, entry_price, leverage,
            stop_price, take_price, stop_order_id, take_order_id, utc_now()
        ))
        conn.commit()
    finally:
        conn.close()


def delete_protection_state(user_id: int, symbol: str) -> None:
    conn = db_connect()
    try:
        conn.execute(
            "DELETE FROM protection_state WHERE user_id=? AND symbol=?",
            (int(user_id), symbol),
        )
        conn.commit()
    finally:
        conn.close()


# ============================================================
# GIEŁDA
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
        ex_id = mapping.get(name, name.lower())
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

        total = nested("total")
        free = nested("free")
        used = nested("used")

        if total <= 0 and free > 0:
            total = free + max(0.0, used)
        if used <= 0 and total > 0:
            used = max(0.0, total - free)
        if free <= 0 and total > 0:
            free = max(0.0, total - used)

        result.update({
            "total": max(0.0, total),
            "used": max(0.0, used),
            "free": max(0.0, free),
        })
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
            symbol,
            "market",
            close_side_for_position(p),
            amount,
            None,
            reduce_only_params(exchange),
        )
        log.info(
            "Closed %s %s amount=%s reason=%s",
            symbol, position_side(p), amount, reason
        )
        return bool(order)
    except Exception as exc:
        log.error("Close position failed %s: %s", symbol, exc)
        return False


def market_limits(exchange, symbol: str) -> Tuple[float, float, float]:
    market = exchange.market(symbol)
    limits = market.get("limits", {})
    amount_min = safe_float((limits.get("amount") or {}).get("min"), 0.0)
    cost_min = safe_float((limits.get("cost") or {}).get("min"), 0.0)
    max_lev = safe_float((limits.get("leverage") or {}).get("max"), 0.0)
    return amount_min, cost_min, max_lev


def contract_size(exchange, symbol: str) -> float:
    try:
        value = safe_float(exchange.market(symbol).get("contractSize"), 1.0)
        return value if value > 0 else 1.0
    except Exception:
        return 1.0


def base_amount_to_contracts(exchange, symbol: str, base_amount: float) -> float:
    # IMPORTANT:
    # For contract markets CCXT expects number of contracts, not necessarily
    # the base-asset amount. contracts = base_amount / contractSize.
    cs = contract_size(exchange, symbol)
    return max(0.0, float(base_amount) / cs)


def contracts_to_base_amount(exchange, symbol: str, contracts: float) -> float:
    return max(0.0, float(contracts) * contract_size(exchange, symbol))


def exchange_max_leverage(exchange, symbol: str, fallback: int = 15) -> int:
    try:
        _, _, max_lev = market_limits(exchange, symbol)
        if max_lev > 0:
            return max(1, int(max_lev))
    except Exception:
        pass
    return max(1, int(fallback))


def set_margin_mode_safe(exchange, symbol: str) -> bool:
    try:
        exchange.set_margin_mode("isolated", symbol)
        return True
    except Exception as exc:
        # Already isolated / unsupported / open-position mode changes are not
        # fatal. The leverage and order call below can still succeed.
        log.debug("set_margin_mode isolated failed %s: %s", symbol, exc)
        return False


def set_leverage_safe(exchange, symbol: str, leverage: int) -> bool:
    try:
        exchange.set_leverage(
            int(leverage),
            symbol,
            {"marginMode": "isolated"},
        )
        return True
    except Exception as first_exc:
        try:
            exchange.set_leverage(int(leverage), symbol)
            return True
        except Exception as second_exc:
            log.warning(
                "set_leverage failed %s %sx: %s / %s",
                symbol, leverage, first_exc, second_exc
            )
            return False


# ============================================================
# RYNKI / SKANOWANIE
# ============================================================

def is_tradeable_usdt_swap(market: Dict[str, Any]) -> bool:
    return bool(
        market.get("active", True)
        and market.get("swap")
        and market.get("linear")
        and str(market.get("quote", "")).upper() == "USDT"
    )


def rank_liquid_symbols(exchange, tickers: Dict[str, Any], max_pairs: int) -> List[Tuple[str, float]]:
    ranked: List[Tuple[str, float]] = []

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


# ============================================================
# WSKAŹNIKI / SYGNAŁY
# ============================================================
import pandas as pd
import numpy as np
from typing import Dict, Tuple, Any

def calculate_indicators(df: pd.DataFrame, ema_fast: int, ema_slow: int, adx_period: int = 14) -> pd.DataFrame:
    """Calculate real indicators from the supplied OHLCV candles only."""
    out = df.copy()
    
    # Zabezpieczenie: unifikujemy nazwy kolumn do małych liter (obsługuje 'Close', 'CLOSE', 'close' itp.)
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
    out["plus_di"] = (100.0 * plus_s / tr_safe).clip(0.0, 100.0)
    out["minus_di"] = (100.0 * minus_s / tr_safe).clip(0.0, 100.0)

    di_sum = (out["plus_di"] + out["minus_di"]).where(
        (out["plus_di"] + out["minus_di"]) > 0
    )
    out["dx"] = (
        100.0 * (out["plus_di"] - out["minus_di"]).abs() / di_sum
    ).clip(0.0, 100.0)
    out["adx"] = out["dx"].ewm(
        alpha=alpha, adjust=False, min_periods=period
    ).mean().clip(0.0, 100.0)

    delta = out["close"].diff()
    gain = delta.clip(lower=0.0)
    loss = -delta.clip(upper=0.0)
    avg_gain = gain.ewm(alpha=1.0 / 14.0, adjust=False, min_periods=14).mean()
    avg_loss = loss.ewm(alpha=1.0 / 14.0, adjust=False, min_periods=14).mean()
    rs = avg_gain / avg_loss.where(avg_loss > 0)
    out["rsi"] = (100.0 - 100.0 / (1.0 + rs))
    out.loc[(avg_loss <= 0) & (avg_gain > 0), "rsi"] = 100.0
    out.loc[(avg_gain <= 0) & (avg_loss > 0), "rsi"] = 0.0
    out["rsi"] = out["rsi"].clip(0.0, 100.0)

    return out


def get_dynamic_parameters(df: pd.DataFrame, tf: str) -> Dict[str, float]:
    try:
        temp_df = df.copy()
        temp_df.columns = [str(c).lower() for c in temp_df.columns]
        closes = pd.to_numeric(temp_df["close"], errors="coerce").dropna().values
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
            "ema_fast": 9,
            "ema_slow": 21,
            "min_adx": 25.0,
            "max_rsi": 75.0,
            "min_rsi": 25.0,
            "capital_multiplier": 1.0,
        }


def blend_params(base: Dict[str, Any], opt: Dict[str, Any], base_weight: float = 0.5) -> Dict[str, Any]:
    w = max(0.0, min(1.0, float(base_weight)))
    return {
        "ema_fast": max(1, int(round(base["ema_fast"] * w + opt["ema_fast"] * (1 - w)))),
        "ema_slow": max(2, int(round(base["ema_slow"] * w + opt["ema_slow"] * (1 - w)))),
        "min_adx": base["min_adx"] * w + opt["min_adx"] * (1 - w),
        "max_rsi": base["max_rsi"] * w + opt["max_rsi"] * (1 - w),
        "min_rsi": base["min_rsi"] * w + opt["min_rsi"] * (1 - w),
        "capital_multiplier": base["capital_multiplier"] * w + opt["capital_multiplier"] * (1 - w),
    }


def signal_from_closed_candle(df: pd.DataFrame, cfg: Dict[str, Any], auto_base_influence: float = 0.5) -> Tuple[str, Dict[str, float]]:
    """Return signal + real indicator values from the last closed candle."""
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
        min_adx = min_adx * w + float(auto["min_adx"]) * (1.0 - w)
        max_rsi = max_rsi * w + float(auto["max_rsi"]) * (1.0 - w)
        min_rsi = min_rsi * w + float(auto["min_rsi"]) * (1.0 - w)
        cap_mult = cap_mult * w + float(auto["capital_multiplier"]) * (1.0 - w)

    ind = calculate_indicators(df, fast, slow, 14)
    if len(ind) < max(80, slow + 30):
        return "NEUTRALNY", {}

    last = ind.iloc[-2]
    prev = ind.iloc[-3]

    required = [
        "close", "adx", "rsi", "plus_di", "minus_di",
        "ema_fast", "ema_slow", "macd_hist",
    ]
    
    # Bezpieczne sprawdzanie wartości numerycznych
    def safe_float(val, default=0.0):
        try:
            res = float(val)
            return res if np.isfinite(res) else default
        except Exception:
            return default

    if any(not np.isfinite(safe_float(last[c], np.nan)) for c in required):
        return "NEUTRALNY", {}
    if any(not np.isfinite(safe_float(prev[c], np.nan)) for c in [
        "ema_fast", "ema_slow", "plus_di", "minus_di", "macd_hist"
    ]):
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
    }

    if not (0.0 <= values["adx"] <= 100.0 and 0.0 <= values["rsi"] <= 100.0):
        return "NEUTRALNY", {}
    if not (0.0 <= values["plus_di"] <= 100.0 and 0.0 <= values["minus_di"] <= 100.0):
        return "NEUTRALNY", {}
    if values["price"] <= 0 or values["ema_fast"] <= 0 or values["ema_slow"] <= 0:
        return "NEUTRALNY", {}

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

    signal = "LONG" if long_ok else "SHORT" if short_ok else "NEUTRALNY"
    values.update({
        "ema_fast": float(last["ema_fast"]),
        "ema_slow": float(last["ema_slow"]),
        "min_adx": min_adx,
        "max_rsi": max_rsi,
        "min_rsi": min_rsi,
    })
    return signal, values


# ============================================================
# RYZYKO / ZLECENIA
# ============================================================

def calculate_risk_allocation( free_balance: float, entry: float, stop_price: float, leverage: int, max_single: float, tf_multiplier: float, ) -> float:
    if free_balance <= 0 or entry <= 0 or stop_price <= 0:
        return 0.0

    risk_amount = free_balance * DEFAULT_RISK_PCT
    distance = abs(entry - stop_price) / entry
    distance = max(distance, 0.005)

    risk_notional = risk_amount / distance

    max_notional = min(
        free_balance * max(1, leverage) * 0.90,
        max_single * max(tf_multiplier, 0.1) * leverage,
    )

    return max(
        0.0,
        min(risk_notional, max_notional),
    )


def roe_to_price( entry: float, roe_percent: float, leverage: float, long: bool, ) -> float:
    move = (
        abs(float(roe_percent))
        / max(float(leverage), 1.0)
        / 100.0
    )
    return entry * (
        1.0 - move if long else 1.0 + move
    )


def normalize_price(exchange, symbol: str, price: float) -> float:
    try:
        return float(exchange.price_to_precision(symbol, price))
    except Exception:
        return float(price)


def create_trigger_order( exchange, symbol: str, side: str, amount: float, trigger_price: float, kind: str, ) -> Optional[Dict[str, Any]]:
    """Create a reduce-only market trigger using current CCXT semantics."""
    trigger_price = normalize_price(exchange, symbol, trigger_price)
    amount = float(exchange.amount_to_precision(symbol, amount))
    if amount <= 0 or trigger_price <= 0:
        return None

    # Prefer the current unified trigger API. Do not send stopLossPrice and
    # takeProfitPrice together with triggerPrice on the same attempt because
    # some exchanges reject the mixed parameter set.
    params = {"triggerPrice": trigger_price, "reduceOnly": True}
    if kind == "stop":
        params["stopLossPrice"] = trigger_price
    else:
        params["takeProfitPrice"] = trigger_price

    attempts = [params, {"triggerPrice": trigger_price, "reduceOnly": True},
                {"stopPrice": trigger_price, "reduceOnly": True}]

    for p in attempts:
        try:
            order = exchange.create_order(
                symbol, "market", side, amount, None, p
            )
            if order:
                return order
        except Exception as exc:
            log.warning("Protection %s failed %s params=%s: %s", kind, symbol, p, exc)

    # Some CCXT versions expose dedicated helpers.
    try:
        if kind == "stop" and getattr(exchange, "has", {}).get("createStopLossOrder"):
            return exchange.create_stop_loss_order(
                symbol, "market", side, amount, None,
                trigger_price, {"reduceOnly": True}
            )
        if kind == "take" and getattr(exchange, "has", {}).get("createTakeProfitOrder"):
            return exchange.create_take_profit_order(
                symbol, "market", side, amount, None,
                trigger_price, {"reduceOnly": True}
            )
    except Exception as exc:
        log.warning("Dedicated protection %s failed %s: %s", kind, symbol, exc)

    log.error("No working native %s protection for %s", kind, symbol)
    return None


def place_entry_with_protection( exchange, symbol: str, signal: str, contracts: float, leverage: int, stop_roe: float, take_roe: float, user_id: int, ) -> Tuple[Optional[Dict[str, Any]], Optional[float], Optional[float]]:
    side = "buy" if signal == "LONG" else "sell"

    try:
        contracts = float(
            exchange.amount_to_precision(symbol, contracts)
        )
        if contracts <= 0:
            raise ValueError("contracts <= 0")

        set_margin_mode_safe(exchange, symbol)
        try:
            order = exchange.create_order(
                symbol, "market", side, contracts, None, {}
            )
        except (ccxt.InvalidOrder, ccxt.BadRequest) as first_exc:
            # Hedge-mode accounts on some derivatives venues require posSide.
            # Retry only on an order-validation rejection, never on an unknown
            # network/API error that could have created the order already.
            hedge_params = {"posSide": "long" if signal == "LONG" else "short"}
            log.warning("Retrying hedge-mode entry %s with %s: %s", symbol, hedge_params, first_exc)
            order = exchange.create_order(
                symbol, "market", side, contracts, None, hedge_params
            )
    except Exception as exc:
        log.error(
            "ENTRY failed %s %s contracts=%s: %s",
            symbol, signal, contracts, exc
        )
        return None, None, None

    entry = (
        safe_float(order.get("average"))
        or safe_float(order.get("price"))
    )

    if entry <= 0:
        # The order response can omit average/price on some venues. One short
        # position lookup is enough; do not poll the whole account repeatedly.
        time.sleep(0.15)
        p = find_position(fetch_positions_safe(exchange), symbol)
        if p:
            entry = safe_float(p.get("entryPrice"))

    if entry <= 0:
        log.error(
            "Entry price unavailable after successful order %s",
            symbol,
        )
        return order, None, None

    long = signal == "LONG"

    stop_price = normalize_price(
        exchange,
        symbol,
        roe_to_price(
            entry, stop_roe, leverage, long
        ),
    )

    take_price = normalize_price(
        exchange,
        symbol,
        roe_to_price(
            entry, take_roe, leverage, not long
        ),
    )

    close_side = "sell" if long else "buy"

    sl_order = create_trigger_order(
        exchange,
        symbol,
        close_side,
        contracts,
        stop_price,
        "stop",
    )

    tp_order = create_trigger_order(
        exchange,
        symbol,
        close_side,
        contracts,
        take_price,
        "take",
    )

    save_protection_state(
        user_id=user_id,
        symbol=symbol,
        side=("long" if signal == "LONG" else "short"),
        amount=contracts,
        entry_price=entry,
        leverage=leverage,
        stop_price=stop_price,
        take_price=take_price,
        stop_order_id=str(
            (sl_order or {}).get("id", "")
        ),
        take_order_id=str(
            (tp_order or {}).get("id", "")
        ),
    )

    log.info(
        "ENTRY %s %s contracts=%s entry=%s SL=%s TP=%s nativeSL=%s nativeTP=%s",
        symbol,
        signal,
        contracts,
        entry,
        stop_price,
        take_price,
        bool(sl_order),
        bool(tp_order),
    )

    return order, stop_price, take_price


# ============================================================
# USTAWIENIA UŻYTKOWNIKA
# ============================================================

def get_all_trading_users() -> List[Dict[str, Any]]:
    conn = db_connect()
    try:
        rows = conn.execute(""" SELECT id,email,api_key,secret_key,passphrase, selected_exchange,is_admin,stripe_paid FROM users WHERE api_key<>'' AND secret_key<>'' """).fetchall()
    finally:
        conn.close()

    return [{
        "id": int(r[0]),
        "email": r[1],
        "api_key": r[2] or "",
        "secret_key": r[3] or "",
        "passphrase": r[4] or "",
        "exchange": r[5] or "Bitget",
        "is_admin": bool(r[6]),
        "paid": bool(r[7]),
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
        row = conn.execute(
            "SELECT settings_json FROM users WHERE id=?",
            (int(user_id),),
        ).fetchone()
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


def save_user_risk_settings( user_id: int, settings: Dict[str, Any], ) -> None:
    conn = db_connect()
    try:
        conn.execute(
            "UPDATE users SET settings_json=? WHERE id=?",
            (json.dumps(settings, ensure_ascii=False), int(user_id)),
        )
        conn.commit()
    finally:
        conn.close()


# ============================================================
# TRWAŁY SKANER
# ============================================================

def clear_scanner_rows(user_id: int, timeframe: Optional[str] = None) -> None:
    """Delete old scanner rows so the UI never mixes scan generations."""
    conn = db_connect()
    try:
        if timeframe:
            conn.execute(
                "DELETE FROM scanner_results WHERE user_id=? AND timeframe=?",
                (int(user_id), str(timeframe)),
            )
        else:
            conn.execute(
                "DELETE FROM scanner_results WHERE user_id=?",
                (int(user_id),),
            )
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
            conn.execute(""" INSERT INTO scanner_results( user_id,timeframe,symbol,quote_volume,price,adx,rsi, ema_fast,ema_slow,signal,candle_ts,updated_at ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(user_id,timeframe,symbol) DO UPDATE SET quote_volume=excluded.quote_volume, price=excluded.price, adx=excluded.adx, rsi=excluded.rsi, ema_fast=excluded.ema_fast, ema_slow=excluded.ema_slow, signal=excluded.signal, candle_ts=excluded.candle_ts, updated_at=excluded.updated_at """, (
                int(user_id),
                row["timeframe"],
                row["symbol"],
                float(row["quote_volume"]),
                float(row["price"]),
                float(row["adx"]),
                float(row["rsi"]),
                float(row["ema_fast"]),
                float(row["ema_slow"]),
                row["signal"],
                int(row["candle_ts"]),
                now,
            ))
        conn.commit()
    finally:
        conn.close()


def read_scanner_rows( user_id: int, limit: int = 500, active_timeframes: Optional[List[str]] = None, ) -> pd.DataFrame:
    """Read only current, valid scanner snapshots. Old versions could leave rows containing ADX=0, RSI=50 and EMA=price. Those are not real indicator values and must never be displayed again. """
    conn = db_connect()
    try:
        where = [
            "user_id=?",
            "adx IS NOT NULL AND rsi IS NOT NULL",
            "ema_fast IS NOT NULL AND ema_slow IS NOT NULL",
            "adx >= 0 AND rsi >= 0 AND rsi <= 100",
        ]
        params: List[Any] = [int(user_id)]

        if active_timeframes:
            active = [tf for tf in active_timeframes if tf in AVAILABLE_TIMEFRAMES]
            if active:
                placeholders = ",".join("?" for _ in active)
                where.append(f"timeframe IN ({placeholders})")
                params.extend(active)

        tf_order = "CASE timeframe WHEN '1h' THEN 0 WHEN '4h' THEN 1 WHEN '1d' THEN 2 WHEN '30m' THEN 3 WHEN '15m' THEN 4 WHEN '5m' THEN 5 WHEN '1m' THEN 6 ELSE 99 END"
        signal_order = "CASE signal WHEN 'LONG' THEN 0 WHEN 'SHORT' THEN 1 ELSE 2 END"

        query = f""" SELECT timeframe AS Interwał, symbol AS Para, price AS Cena, adx AS ADX, rsi AS RSI, ema_fast AS EMA_Szybka, ema_slow AS EMA_Wolna, signal AS Sygnał, quote_volume AS Wolumen_24h, updated_at AS Aktualizacja FROM scanner_results WHERE {' AND '.join(where)} ORDER BY {tf_order}, {signal_order}, quote_volume DESC, symbol ASC LIMIT ? """
        params.append(int(limit))
        return pd.read_sql_query(query, conn, params=params)
    except Exception:
        return pd.DataFrame()
    finally:
        conn.close()

        # Dodaj te definicje na poziomie modułu (np. nad klasą UserWorker lub w sekcji helperów):
MANAGER = None # lub odpowiednia instancja managera, jeśli jest używana w innych miejscach

def marketlimits(exchange, symbol: str) -> tuple[float, float]:
    """Pobiera minimalną ilość oraz minimalny koszt dla danego symbolu z giełdy."""
    try:
        market = exchange.market(symbol)
        limits = market.get("limits", {})
        min_amount = float(limits.get("amount", {}).get("min") or 0.0)
        min_cost = float(limits.get("cost", {}).get("min") or 0.0)
        return min_amount, min_cost
    except Exception:
        return 0.0, 0.0


class UserWorker:
    def __init__(self, user: dict[str, Any]):
        self.user = user
        self.user_id = int(user["id"])
        self.exchange = get_exchange(
            user["api_key"],
            user["secret_key"],
            user["passphrase"],
            user["exchange"],
        )
        self.cooldowns: dict[str, float] = {}
        self.entry_locks: dict[str, float] = {}
        self.last_protection_check = 0.0
        self.last_scan_by_tf: dict[str, float] = {}
        self.scan_cursor_by_tf: dict[str, int] = {}
        self.scan_round_robin = 0
        self.scan_tf_index = 0
        self.last_successful_scan_at = 0.0
        self.last_error_at = 0.0
        self.markets_loaded = False
        self.last_tickers_at = 0.0
        self.cached_tickers: dict[str, Any] = {}
        self.last_ranked_at = 0.0
        self.cached_ranked: list[tuple[str, float]] = []
        self.scanner_initialized = False

    def run_once(self) -> None:
        if self.exchange is None:
            return

        bots = load_active_bots(self.user_id)
        bots = {
            tf: cfg for tf, cfg in bots.items()
            if tf in AVAILABLE_TIMEFRAMES and isinstance(cfg, dict)
        }
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
        if now - self.last_tickers_at >= 60.0 or not self.cached_tickers:
            try:
                self.cached_tickers = self.exchange.fetch_tickers()
                self.last_tickers_at = now
            except Exception as exc:
                log.warning("Ticker fetch failed user=%s: %s", self.user_id, exc)
                if not self.cached_tickers:
                    return
        tickers = self.cached_tickers

        self.protect_open_positions(risk)

        positions = fetch_positions_safe(self.exchange)
        pos_map = {
            p.get("symbol"): p
            for p in positions
            if p.get("symbol") and position_contracts(p) > 0
        }

        active_count = len(pos_map)
        balance_snapshot = fetch_usdt_balance(self.exchange)
        free_balance = balance_snapshot["free"]

        if now - self.last_ranked_at >= 60.0 or not self.cached_ranked:
            try:
                self.cached_ranked = rank_liquid_symbols(
                    self.exchange, tickers, int(risk["max_scan_pairs"])
                )
                self.last_ranked_at = now
            except Exception as exc:
                self.last_error_at = time.time()
                log.exception("Ranking failed user=%s: %s", self.user_id, exc)
                return
        else:
            self.cached_ranked = self.cached_ranked[:max(1, int(risk["max_scan_pairs"]))]
        ranked = self.cached_ranked

        if not ranked:
            log.warning("No liquid USDT swap symbols for user=%s", self.user_id)
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

        if cursor == 0:
            clear_scanner_rows(self.user_id)

        batch = ranked[cursor:cursor + SCAN_BATCH_SIZE]
        if not batch:
            cursor = 0
            batch = ranked[:SCAN_BATCH_SIZE]

        next_cursor = cursor + len(batch)
        finished_tf = next_cursor >= len(ranked)
        self.scan_cursor_by_tf[tf] = 0 if finished_tf else next_cursor
        self.last_scan_by_tf[tf] = time.time()

        if finished_tf:
            self.scan_tf_index = (self.scan_tf_index + 1) % len(active_tfs)

        scanner_rows: list[dict[str, Any]] = []

        for symbol, qv in batch:
            try:
                limit = (
                    180 if tf == "1d"
                    else min(180, max(100, int(cfg.get("ema_slow", 21)) + 60))
                )

                ohlcv = fetch_ohlcv_safe(self.exchange, symbol, tf, limit)
                min_bars = 70 if tf == "1d" else 60
                if len(ohlcv) < min_bars:
                    continue

                closed_candle_ts = int(ohlcv[-2][0])
                df = pd.DataFrame(
                    ohlcv,
                    columns=["timestamp", "open", "high", "low", "close", "volume"],
                )

                signal, vals = signal_from_closed_candle(
                    df,
                    cfg,
                    float(risk["auto_base_influence"]) / 100.0,
                )

                required = ("price", "adx", "rsi", "ema_fast", "ema_slow")
                if not vals or any(
                    not np.isfinite(safe_float(vals.get(k), np.nan))
                    for k in required
                ):
                    continue

                closes = pd.to_numeric(df["close"], errors="coerce").dropna()
                if len(closes) < 30:
                    continue
                
                last_close = float(closes.iloc[-2])
                local_min = float(closes.tail(30).min())
                local_max = float(closes.tail(30).max())
                ema_fast_val = float(vals["ema_fast"])
                ema_slow_val = float(vals["ema_slow"])

                if not (local_min <= ema_fast_val <= local_max and local_min <= ema_slow_val <= local_max):
                    continue

                if (
                    abs(ema_fast_val - last_close) <= max(1e-12, abs(last_close) * 1e-12)
                    and abs(ema_slow_val - last_close) <= max(1e-12, abs(last_close) * 1e-12)
                    and local_max - local_min > max(1e-12, abs(last_close) * 1e-6)
                ):
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

                if signal == "NEUTRALNY":
                    continue

                if active_count >= int(risk["max_positions"]):
                    break

                if symbol in pos_map:
                    continue

                if time.time() < self.cooldowns.get(symbol, 0) or time.time() < self.entry_locks.get(symbol, 0):
                    continue

                if entry_guard_blocks(self.user_id, symbol, closed_candle_ts):
                    continue

                max_ex = exchange_max_leverage(self.exchange, symbol, int(risk["max_leverage"]))

                if risk["leverage_mode"] == "Ręczny":
                    lev = min(int(risk["manual_leverage"]), max_ex)
                else:
                    adx = safe_float(vals.get("adx"), 20.0)
                    ratio = min(1.0, max(0.0, (adx - 10.0) / 45.0))
                    lev = max(1, int(round(1 + ratio * (min(int(risk["max_leverage"]), max_ex) - 1))))

                if not set_leverage_safe(self.exchange, symbol, lev):
                    continue

                entry_hint = safe_float((tickers.get(symbol) or {}).get("last")) or safe_float(vals.get("price"))
                if entry_hint <= 0:
                    continue

                initial_stop = roe_to_price(entry_hint, float(risk["stop_roe"]), lev, signal == "LONG")
                notional = calculate_risk_allocation(
                    free_balance, entry_hint, initial_stop, lev,
                    float(risk["max_single"]), float(vals.get("capital_multiplier", 1.0))
                )

                if notional <= 0:
                    continue

                base_amount = notional / entry_hint
                contracts = base_amount_to_contracts(self.exchange, symbol, base_amount)
                min_amt, min_cost = marketlimits(self.exchange, symbol)

                if min_amt and contracts < min_amt:
                    contracts = min_amt

                if min_cost:
                    current_quote = contracts * contract_size(self.exchange, symbol) * entry_hint
                    if current_quote < min_cost:
                        contracts = min_cost / entry_hint / contract_size(self.exchange, symbol)

                contracts = float(self.exchange.amount_to_precision(symbol, contracts))
                if contracts <= 0:
                    continue

                lock_seconds = max(300.0, float(risk.get("cooldown_minutes", 15)) * 60.0)
                self.entry_locks[symbol] = time.time() + 30.0

                order, sl_price, tp_price = place_entry_with_protection(
                    self.exchange, symbol, signal, contracts, lev,
                    float(risk["stop_roe"]), float(risk["take_roe"]), self.user_id
                )

                if order:
                    active_count += 1
                    pos_map[symbol] = {"symbol": symbol, "contracts": contracts, "side": "long" if signal == "LONG" else "short"}
                    self.cooldowns[symbol] = time.time() + lock_seconds
                    set_entry_guard(self.user_id, symbol, time.time() + lock_seconds, closed_candle_ts, signal)
                    log_trade(self.user_id, symbol, tf, "ENTRY", signal, entry_hint, contracts, str(order.get("id", "")), f"SL={sl_price};TP={tp_price};LEV={lev};")
                else:
                    retry_lock = max(60.0, min(300.0, float(risk.get("cooldown_minutes", 15)) * 60.0))
                    self.cooldowns[symbol] = time.time() + retry_lock
                    self.entry_locks[symbol] = time.time() + retry_lock
                    log_trade(self.user_id, symbol, tf, "ENTRY_ERROR", signal, entry_hint, contracts, "", "Order rejected")

            except Exception as exc:
                self.last_error_at = time.time()
                log.exception("Signal/order failed user=%s tf=%s symbol=%s: %s", self.user_id, tf, symbol, exc)

        if scanner_rows:
            save_scanner_rows(self.user_id, scanner_rows)
            self.last_successful_scan_at = time.time()

    def protect_open_positions(self, risk: dict[str, Any]) -> None:
        if not bool(risk["enable_roe"]):
            return
        if time.time() - self.last_protection_check < POSITION_GUARD_SECONDS:
            return

        self.last_protection_check = time.time()
        positions = fetch_positions_safe(self.exchange)

        for p in positions:
            amount = position_contracts(p)
            if amount <= 0:
                continue
            symbol = p.get("symbol", "")
            if not symbol:
                continue
            entry = safe_float(p.get("entryPrice"))
            if entry <= 0:
                continue
            mark = safe_float(p.get("markPrice")) or safe_float(p.get("lastPrice"))
            lev = safe_float(p.get("leverage"), 1.0)
            if mark <= 0:
                continue

            raw_move = ((mark - entry) / entry) * 100 if is_long(p) else ((entry - mark) / entry) * 100
            roe = raw_move * max(1.0, lev)

            if roe <= -float(risk["stop_roe"]) or roe >= float(risk["take_roe"]):
                side_tag = "SL" if roe <= -float(risk["stop_roe"]) else "TP"
                if close_position(self.exchange, p, f"ROE {side_tag} {roe:.2f}%"):
                    guard_until = time.time() + float(risk["cooldown_minutes"]) * 60
                    self.cooldowns[symbol] = guard_until
                    self.entry_locks[symbol] = guard_until
                    set_entry_guard(self.user_id, symbol, guard_until, 0, side_tag)
                    delete_protection_state(self.user_id, symbol)
                    log_trade(self.user_id, symbol, "guard", side_tag, position_side(p), mark, amount, message=f"ROE={roe:.2f}%")

    def loop(self, stop_event: threading.Event) -> None:
        log.info("Worker started user=%s exchange=%s", self.user_id, self.user.get("exchange"))
        while not stop_event.is_set():
            try:
                self.run_once()
            except Exception:
                log.exception("Worker top-level error user=%s", self.user_id)
            stop_event.wait(WORKER_POLL_SECONDS)
        log.info("Worker stopped user=%s", self.user_id)



# ============================================================
# WORKER
# ============================================================

class UserWorker:
    def __init__(self, user: Dict[str, Any]):
        self.user = user
        self.user_id = int(user["id"])
        self.exchange = get_exchange(
            user["api_key"],
            user["secret_key"],
            user["passphrase"],
            user["exchange"],
        )
        self.cooldowns: Dict[str, float] = {}
        self.entry_locks: Dict[str, float] = {}
        self.last_protection_check = 0.0
        self.last_scan_by_tf: Dict[str, float] = {}
        self.scan_cursor_by_tf: Dict[str, int] = {}
        self.scan_round_robin = 0
        self.scan_tf_index = 0
        self.last_successful_scan_at = 0.0
        self.last_error_at = 0.0
        self.markets_loaded = False
        self.last_tickers_at = 0.0
        self.cached_tickers: Dict[str, Any] = {}
        self.last_ranked_at = 0.0
        self.cached_ranked: List[Tuple[str, float]] = []
        self.scanner_initialized = False

    def run_once(self) -> None:
        if self.exchange is None:
            return

        bots = load_active_bots(self.user_id)
        bots = {
            tf: cfg for tf, cfg in bots.items()
            if tf in AVAILABLE_TIMEFRAMES and isinstance(cfg, dict)
        }
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
        if now - self.last_tickers_at >= 60.0 or not self.cached_tickers:
            try:
                self.cached_tickers = self.exchange.fetch_tickers()
                self.last_tickers_at = now
            except Exception as exc:
                log.warning("Ticker fetch failed user=%s: %s", self.user_id, exc)
                if not self.cached_tickers:
                    return
        tickers = self.cached_tickers

        self.protect_open_positions(risk)

        positions = fetch_positions_safe(self.exchange)
        pos_map = {
            p.get("symbol"): p
            for p in positions
            if p.get("symbol") and position_contracts(p) > 0
        }

        active_count = len(pos_map)
        balance_snapshot = fetch_usdt_balance(self.exchange)
        free_balance = balance_snapshot["free"]

        if now - self.last_ranked_at >= 60.0 or not self.cached_ranked:
            try:
                self.cached_ranked = rank_liquid_symbols(
                    self.exchange, tickers, int(risk["max_scan_pairs"])
                )
                self.last_ranked_at = now
            except Exception as exc:
                self.last_error_at = time.time()
                log.exception("Ranking failed user=%s: %s", self.user_id, exc)
                return
        else:
            self.cached_ranked = self.cached_ranked[:max(1, int(risk["max_scan_pairs"]))]
        ranked = self.cached_ranked

        if not ranked:
            log.warning("No liquid USDT swap symbols for user=%s", self.user_id)
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

        if cursor == 0:
            clear_scanner_rows(self.user_id)

        batch = ranked[cursor:cursor + SCAN_BATCH_SIZE]
        if not batch:
            cursor = 0
            batch = ranked[:SCAN_BATCH_SIZE]

        next_cursor = cursor + len(batch)
        finished_tf = next_cursor >= len(ranked)
        self.scan_cursor_by_tf[tf] = 0 if finished_tf else next_cursor
        self.last_scan_by_tf[tf] = time.time()

        if finished_tf:
            self.scan_tf_index = (self.scan_tf_index + 1) % len(active_tfs)

        scanner_rows: List[Dict[str, Any]] = []

        for symbol, qv in batch:
            try:
                limit = (
                    180 if tf == "1d"
                    else min(180, max(100, int(cfg.get("ema_slow", 21)) + 60))
                )

                ohlcv = fetch_ohlcv_safe(self.exchange, symbol, tf, limit)
                min_bars = 70 if tf == "1d" else 60
                if len(ohlcv) < min_bars:
                    continue

                closed_candle_ts = int(ohlcv[-2][0])
                df = pd.DataFrame(
                    ohlcv,
                    columns=["timestamp", "open", "high", "low", "close", "volume"],
                )

                signal, vals = signal_from_closed_candle(
                    df,
                    cfg,
                    float(risk["auto_base_influence"]) / 100.0,
                )

                required = ("price", "adx", "rsi", "ema_fast", "ema_slow")
                if not vals or any(
                    not np.isfinite(safe_float(vals.get(k), np.nan))
                    for k in required
                ):
                    continue

                closes = pd.to_numeric(df["close"], errors="coerce").dropna()
                if len(closes) < 30:
                    continue
                
                last_close = float(closes.iloc[-2])
                local_min = float(closes.tail(30).min())
                local_max = float(closes.tail(30).max())
                ema_fast_val = float(vals["ema_fast"])
                ema_slow_val = float(vals["ema_slow"])

                if not (local_min <= ema_fast_val <= local_max and local_min <= ema_slow_val <= local_max):
                    continue

                if (
                    abs(ema_fast_val - last_close) <= max(1e-12, abs(last_close) * 1e-12)
                    and abs(ema_slow_val - last_close) <= max(1e-12, abs(last_close) * 1e-12)
                    and local_max - local_min > max(1e-12, abs(last_close) * 1e-6)
                ):
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

                if signal == "NEUTRALNY":
                    continue

                if active_count >= int(risk["max_positions"]):
                    break

                if symbol in pos_map:
                    continue

                if time.time() < self.cooldowns.get(symbol, 0) or time.time() < self.entry_locks.get(symbol, 0):
                    continue

                if entry_guard_blocks(self.user_id, symbol, closed_candle_ts):
                    continue

                max_ex = exchange_max_leverage(self.exchange, symbol, int(risk["max_leverage"]))

                if risk["leverage_mode"] == "Ręczny":
                    lev = min(int(risk["manual_leverage"]), max_ex)
                else:
                    adx = safe_float(vals.get("adx"), 20.0)
                    ratio = min(1.0, max(0.0, (adx - 10.0) / 45.0))
                    lev = max(1, int(round(1 + ratio * (min(int(risk["max_leverage"]), max_ex) - 1))))

                if not set_leverage_safe(self.exchange, symbol, lev):
                    continue

                entry_hint = safe_float((tickers.get(symbol) or {}).get("last")) or safe_float(vals.get("price"))
                if entry_hint <= 0:
                    continue

                initial_stop = roe_to_price(entry_hint, float(risk["stop_roe"]), lev, signal == "LONG")
                notional = calculate_risk_allocation(
                    free_balance, entry_hint, initial_stop, lev,
                    float(risk["max_single"]), float(vals.get("capital_multiplier", 1.0))
                )

                if notional <= 0:
                    continue

                base_amount = notional / entry_hint
                contracts = base_amount_to_contracts(self.exchange, symbol, base_amount)
                min_amt, min_cost = marketlimits(self.exchange, symbol)

                if min_amt and contracts < min_amt:
                    contracts = min_amt

                if min_cost:
                    current_quote = contracts * contract_size(self.exchange, symbol) * entry_hint
                    if current_quote < min_cost:
                        contracts = min_cost / entry_hint / contract_size(self.exchange, symbol)

                contracts = float(self.exchange.amount_to_precision(symbol, contracts))
                if contracts <= 0:
                    continue

                lock_seconds = max(300.0, float(risk.get("cooldown_minutes", 15)) * 60.0)
                self.entry_locks[symbol] = time.time() + 30.0

                order, sl_price, tp_price = place_entry_with_protection(
                    self.exchange, symbol, signal, contracts, lev,
                    float(risk["stop_roe"]), float(risk["take_roe"]), self.user_id
                )

                if order:
                    active_count += 1
                    pos_map[symbol] = {"symbol": symbol, "contracts": contracts, "side": "long" if signal == "LONG" else "short"}
                    self.cooldowns[symbol] = time.time() + lock_seconds
                    set_entry_guard(self.user_id, symbol, time.time() + lock_seconds, closed_candle_ts, signal)
                    log_trade(self.user_id, symbol, tf, "ENTRY", signal, entry_hint, contracts, str(order.get("id", "")), f"SL={sl_price};TP={tp_price};LEV={lev};")
                else:
                    retry_lock = max(60.0, min(300.0, float(risk.get("cooldown_minutes", 15)) * 60.0))
                    self.cooldowns[symbol] = time.time() + retry_lock
                    self.entry_locks[symbol] = time.time() + retry_lock
                    log_trade(self.user_id, symbol, tf, "ENTRY_ERROR", signal, entry_hint, contracts, "", "Order rejected")

            except Exception as exc:
                self.last_error_at = time.time()
                log.exception("Signal/order failed user=%s tf=%s symbol=%s: %s", self.user_id, tf, symbol, exc)

        if scanner_rows:
            save_scanner_rows(self.user_id, scanner_rows)
            self.last_successful_scan_at = time.time()

    def protect_open_positions(self, risk: Dict[str, Any]) -> None:
        if not bool(risk["enable_roe"]):
            return
        if time.time() - self.last_protection_check < POSITION_GUARD_SECONDS:
            return

        self.last_protection_check = time.time()
        positions = fetch_positions_safe(self.exchange)

        for p in positions:
            amount = position_contracts(p)
            if amount <= 0:
                continue
            symbol = p.get("symbol", "")
            if not symbol:
                continue
            entry = safe_float(p.get("entryPrice"))
            if entry <= 0:
                continue
            mark = safe_float(p.get("markPrice")) or safe_float(p.get("lastPrice"))
            lev = safe_float(p.get("leverage"), 1.0)
            if mark <= 0:
                continue

            raw_move = ((mark - entry) / entry) * 100 if is_long(p) else ((entry - mark) / entry) * 100
            roe = raw_move * max(1.0, lev)

            if roe <= -float(risk["stop_roe"]) or roe >= float(risk["take_roe"]):
                side_tag = "SL" if roe <= -float(risk["stop_roe"]) else "TP"
                if close_position(self.exchange, p, f"ROE {side_tag} {roe:.2f}%"):
                    guard_until = time.time() + float(risk["cooldown_minutes"]) * 60
                    self.cooldowns[symbol] = guard_until
                    self.entry_locks[symbol] = guard_until
                    set_entry_guard(self.user_id, symbol, guard_until, 0, side_tag)
                    delete_protection_state(self.user_id, symbol)
                    log_trade(self.user_id, symbol, "guard", side_tag, position_side(p), mark, amount, message=f"ROE={roe:.2f}%")

    def loop(self, stop_event: threading.Event) -> None:
        log.info("Worker started user=%s exchange=%s", self.user_id, self.user.get("exchange"))
        while not stop_event.is_set():
            try:
                self.run_once()
            except Exception:
                log.exception("Worker top-level error user=%s", self.user_id)
            stop_event.wait(WORKER_POLL_SECONDS)
        log.info("Worker stopped user=%s", self.user_id)


        
# ============================================================
# STREAMLIT
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
    "session_baseline_locked": False,
    "active_mtf_bots": {},
    "_mtf_loaded_user_id": None,
}


def get_secret( name: str, default: str = "", ) -> str:
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


def create_stripe_checkout_session( email: str, price_id: str, ) -> str:
    secret = get_secret(
        "STRIPE_SECRET_KEY",
        STRIPE_SECRET_KEY,
    )

    if (
        stripe is None
        or not secret
        or not price_id
    ):
        return STRIPE_CHECKOUT_FALLBACK

    try:
        stripe.api_key = secret

        session = stripe.checkout.Session.create(
            payment_method_types=["card"],
            line_items=[{
                "price": price_id,
                "quantity": 1,
            }],
            mode="payment",
            success_url=(
                "https://bot-bitget.pl/"
                "?success=true"
            ),
            cancel_url=(
                "https://bot-bitget.pl/"
                "?success=false"
            ),
            customer_email=email,
        )

        return (
            session.url
            if session and session.url
            else STRIPE_CHECKOUT_FALLBACK
        )
    except Exception as exc:
        log.warning(
            "Stripe checkout error: %s",
            exc,
        )
        return STRIPE_CHECKOUT_FALLBACK


def apply_mtf_to_session(user_id: int) -> None:
    if (
        st.session_state.get(
            "_mtf_loaded_user_id"
        )
        == int(user_id)
    ):
        return

    saved = load_mtf_settings(
        int(user_id)
    )

    for tf in AVAILABLE_TIMEFRAMES:
        d = saved[tf]

        st.session_state[
            f"radio_mode_{tf}"
        ] = d.get(
            "mode",
            "Automatyczny",
        )

        st.session_state[
            f"ema_f_{tf}"
        ] = int(
            d.get(
                "ema_fast",
                DEFAULT_TF_VALUES[tf][
                    "ema_fast"
                ],
            )
        )

        st.session_state[
            f"ema_s_{tf}"
        ] = int(
            d.get(
                "ema_slow",
                DEFAULT_TF_VALUES[tf][
                    "ema_slow"
                ],
            )
        )

        st.session_state[
            f"adx_{tf}"
        ] = float(
            d.get(
                "adx",
                DEFAULT_TF_VALUES[tf][
                    "adx"
                ],
            )
        )

        st.session_state[
            f"max_rsi_{tf}"
        ] = float(
            d.get(
                "max_rsi",
                DEFAULT_TF_VALUES[tf][
                    "max_rsi"
                ],
            )
        )

        st.session_state[
            f"min_rsi_{tf}"
        ] = float(
            d.get(
                "min_rsi",
                DEFAULT_TF_VALUES[tf][
                    "min_rsi"
                ],
            )
        )

        st.session_state[
            f"cap_mult_{tf}"
        ] = float(
            d.get(
                "cap_mult",
                DEFAULT_TF_VALUES[tf][
                    "cap_mult"
                ],
            )
        )

    st.session_state.active_mtf_bots = (
        load_active_bots(
            int(user_id)
        )
    )

    st.session_state[
        "_mtf_loaded_user_id"
    ] = int(user_id)


def current_mtf_payload() -> Dict[str, Dict[str, Any]]:
    payload: Dict[str, Dict[str, Any]] = {}

    for tf in AVAILABLE_TIMEFRAMES:
        payload[tf] = {
            "mode": st.session_state.get(
                f"radio_mode_{tf}",
                "Automatyczny",
            ),
            "ema_fast": int(
                st.session_state.get(
                    f"ema_f_{tf}",
                    DEFAULT_TF_VALUES[tf][
                        "ema_fast"
                    ],
                )
            ),
            "ema_slow": int(
                st.session_state.get(
                    f"ema_s_{tf}",
                    DEFAULT_TF_VALUES[tf][
                        "ema_slow"
                    ],
                )
            ),
            "adx": float(
                st.session_state.get(
                    f"adx_{tf}",
                    DEFAULT_TF_VALUES[tf][
                        "adx"
                    ],
                )
            ),
            "max_rsi": float(
                st.session_state.get(
                    f"max_rsi_{tf}",
                    DEFAULT_TF_VALUES[tf][
                        "max_rsi"
                    ],
                )
            ),
            "min_rsi": float(
                st.session_state.get(
                    f"min_rsi_{tf}",
                    DEFAULT_TF_VALUES[tf][
                        "min_rsi"
                    ],
                )
            ),
            "cap_mult": float(
                st.session_state.get(
                    f"cap_mult_{tf}",
                    DEFAULT_TF_VALUES[tf][
                        "cap_mult"
                    ],
                )
            ),
        }

    return payload


def is_user_admin() -> bool:
    email = str(
        st.session_state.get(
            "user_email",
            "",
        )
    ).strip().lower()

    return (
        email in {
            x.lower()
            for x in ADMIN_EMAILS
        }
        or bool(
            st.session_state.get(
                "is_admin"
            )
        )
    )


def is_user_paid() -> bool:
    return (
        is_user_admin()
        or bool(
            st.session_state.get(
                "stripe_paid"
            )
        )
    )


# ============================================================
# LOGIN
# ============================================================

def ui_login() -> None:
    st.markdown(
        """ <div style=" max-width:1000px; margin:30px auto; padding:35px; text-align:center; border:2px solid #d9ad4a; border-radius:18px; background:#0d0b09; box-shadow:0 0 35px rgba(0,0,0,.5); "> """,
        unsafe_allow_html=True,
    )

    st.markdown(
        f""" <div style=" font-size:42px; font-weight:900; color:#f3d57a; letter-spacing:3px; "> {t("title")} </div> <div style=" color:#d4c5aa; margin-top:8px; letter-spacing:2px; "> {t("subtitle")} </div> """,
        unsafe_allow_html=True,
    )

    tab_login, tab_register = st.tabs([
        t("login_tab"),
        t("register_tab"),
    ])

    with tab_login:
        email = st.text_input(
            t("email_label"),
            key="log_email",
        )
        password = st.text_input(
            t("pass_label"),
            type="password",
            key="log_pass",
        )

        if st.button(
            t("login_btn"),
            use_container_width=True,
        ):
            conn = db_connect()
            row = conn.execute(""" SELECT id,email,password,is_admin, stripe_paid,api_key,secret_key, passphrase,selected_exchange FROM users WHERE LOWER(TRIM(email))=? """, (
                email.strip().lower(),
            )).fetchone()
            conn.close()

            if row and verify_password(
                password,
                row[2],
            ):
                st.session_state.logged_in = True
                st.session_state.user_id = row[0]
                st.session_state.user_email = row[1]
                st.session_state.is_admin = (
                    bool(row[3])
                    or row[1].strip().lower()
                    in {
                        x.lower()
                        for x in ADMIN_EMAILS
                    }
                )
                st.session_state.stripe_paid = (
                    True
                    if st.session_state.is_admin
                    else bool(row[4])
                )
                st.session_state.api_key = (
                    row[5] or ""
                )
                st.session_state.secret_key = (
                    row[6] or ""
                )
                st.session_state.passphrase = (
                    row[7] or ""
                )
                st.session_state.selected_exchange = (
                    row[8] or "Bitget"
                )

                apply_mtf_to_session(
                    row[0]
                )

                if not str(row[2]).startswith(
                    "sha256$"
                ):
                    conn = db_connect()
                    conn.execute(
                        "UPDATE users SET password=? WHERE id=?",
                        (
                            hash_password(
                                password
                            ),
                            row[0],
                        ),
                    )
                    conn.commit()
                    conn.close()

                st.success(
                    t("login_success")
                )
                st.rerun()
            else:
                st.error(
                    t("login_error")
                )

    with tab_register:
        email = st.text_input(
            t("email_label"),
            key="reg_email",
        )
        password = st.text_input(
            t("pass_label"),
            type="password",
            key="reg_pass",
        )

        if st.button(
            t("register_btn"),
            use_container_width=True,
        ):
            if not email or not password:
                st.error(
                    t("reg_error_fill")
                )
            else:
                try:
                    clean = email.strip().lower()
                    admin = int(
                        clean
                        in {
                            x.lower()
                            for x in ADMIN_EMAILS
                        }
                    )

                    conn = db_connect()
                    conn.execute(""" INSERT INTO users( email,password,is_admin,stripe_paid ) VALUES(?,?,?,?) """, (
                        clean,
                        hash_password(
                            password
                        ),
                        admin,
                        admin,
                    ))
                    conn.commit()
                    conn.close()

                    st.success(
                        t("reg_success")
                    )
                except sqlite3.IntegrityError:
                    st.error(
                        t("reg_error_exists")
                    )

    st.markdown(
        """ </div> """,
        unsafe_allow_html=True,
    )


# ============================================================
# REGULAMIN + INSTRUKCJA
# ============================================================

def render_rules_and_manual() -> None:
    st.markdown("---")
    st.header("📚 Regulamin, zasady bezpieczeństwa i instrukcja obsługi")

    with st.expander(
        "📜 REGULAMIN KORZYSTANIA Z SYSTEMU",
        expanded=False,
    ):
        st.markdown(""" ### 1. Postanowienia ogólne 1. System jest oprogramowaniem wspomagającym i automatyzującym wykonywanie operacji na rachunku futures użytkownika za pośrednictwem interfejsów API giełd. 2. Użytkownik korzysta z systemu na własną odpowiedzialność i powinien przed uruchomieniem bota zapoznać się z zasadami działania wybranej giełdy, kontraktów futures, dźwigni oraz zleceń warunkowych. 3. System nie jest usługą gwarantującą zysk i nie stanowi indywidualnej porady inwestycyjnej, podatkowej ani prawnej. 4. Wyniki historyczne, symulacje, przykładowe sygnały ani informacje wyświetlane przez skaner nie stanowią obietnicy przyszłych wyników. ### 2. Ryzyko 1. Handel kontraktami futures z wykorzystaniem dźwigni finansowej wiąże się z wysokim ryzykiem utraty części lub całości kapitału. 2. W ekstremalnych warunkach rynkowych cena może przeskoczyć poziom SL, wystąpić poślizg, brak płynności, częściowe wykonanie lub czasowa niedostępność API. 3. Lokalny strażnik SL/TP jest dodatkową warstwą ochrony, a nie gwarancją wykonania po określonej cenie. 4. Użytkownik powinien używać wyłącznie środków, których utrata nie naruszy jego podstawowych potrzeb finansowych. ### 3. API i bezpieczeństwo 1. Klucze API powinny mieć wyłącznie uprawnienia konieczne do działania bota. 2. Nie należy nadawać kluczom API uprawnień do wypłat, jeżeli giełda umożliwia ich wyłączenie. 3. Użytkownik odpowiada za bezpieczeństwo swoich danych dostępowych i za konfigurację konta giełdowego. 4. W przypadku podejrzenia przejęcia klucza należy natychmiast unieważnić go na giełdzie. ### 4. Odpowiedzialność 1. Oprogramowanie jest udostępniane w formule „AS IS”, w zakresie dopuszczalnym przez obowiązujące prawo. 2. Dostawca nie gwarantuje ciągłości działania API giełd, serwerów, Internetu, Streamlit, CCXT ani innych usług zewnętrznych. 3. Użytkownik odpowiada za prawidłowe ustawienie limitów ryzyka, dźwigni, liczby pozycji i zakresu skanowania. 4. Przed użyciem produkcyjnym zaleca się test na koncie demo lub z minimalnym kapitałem. ### 5. Subskrypcja 1. Dostęp do funkcji płatnych zależy od aktualnego statusu konta. 2. Cena i zakres funkcji mogą być określone na stronie płatności lub w aktualnej ofercie. 3. Płatność nie stanowi gwarancji wyniku finansowego. 4. Szczegółowe zasady konsumenckie, reklamacyjne i odstąpienia od umowy powinny zostać dostosowane do właściwego modelu sprzedaży i obowiązującego prawa. ### 6. Postanowienia końcowe Regulamin jest informacyjnym szablonem przeznaczonym do wdrożenia w aplikacji. Przed publikacją komercyjną należy dostosować go do faktycznego operatora usługi, kraju sprzedaży, modelu subskrypcji, polityki prywatności, cookies, zasad reklamacji i obowiązków konsumenckich. """)

    with st.expander(
        "📖 PEŁNA INSTRUKCJA OBSŁUGI",
        expanded=False,
    ):
        st.markdown(""" ### 1. Pierwsze uruchomienie 1. Załóż konto lub zaloguj się. 2. Wybierz giełdę: Bitget, Binance, Bybit albo OKX. 3. Wygeneruj na giełdzie klucz API przeznaczony do handlu futures. 4. Nie włączaj wypłat dla klucza API. 5. Wprowadź API Key, API Secret oraz — jeżeli giełda tego wymaga — Passphrase. 6. Kliknij **ZAPISZ MOJE KLUCZE**. 7. Sprawdź, czy system pokazuje prawidłowy portfel Futures. ### 2. Ustawienia ryzyka **Maksymalnie USDT na 1 pozycję** ogranicza bazową wartość pojedynczej pozycji. **Maksymalna liczba aktywnych pozycji** ogranicza liczbę jednocześnie otwartych pozycji. **SL ROE** określa poziom straty ROE, przy którym lokalny strażnik zamknie pozycję. **TP ROE** określa poziom zysku ROE, przy którym lokalny strażnik zamknie pozycję. **Czas oddechu po SL/TP** blokuje ponowne wejście na danym symbolu przez określony czas. ### 3. Dźwignia Tryb autonomiczny dobiera dźwignię w granicach ustawionego limitu, wykorzystując m.in. siłę trendu ADX. Tryb ręczny pozwala ustawić stałą dźwignię, ale rzeczywisty maksymalny poziom jest ograniczany przez limit dostępny dla danego kontraktu na giełdzie. ### 4. Skaner System najpierw pobiera dostępne rynki futures, wybiera aktywne liniowe kontrakty USDT i sortuje je według wolumenu 24h od najwyższego do najniższego. Nie ma tu sztucznego ograniczenia do kilku „wybranych” monet. Liczba par zależy od ustawienia **Liczba par Futures do skanowania** oraz od minimalnego wymogu płynności. Każdy aktywny interwał zapisuje własne wyniki skanowania do bazy danych. Dzięki temu tabela może być pokazana także wtedy, gdy pojedyncze odświeżenie interfejsu Streamlit nie wykonuje właśnie zapytań do giełdy. ### 5. MTF Każdy interwał działa niezależnie: - 1m - 5m - 15m - 30m - 1h - 4h - 1d Ustawienia EMA, ADX, RSI i CAP są zapisywane w bazie użytkownika. W trybie **Ręczny** system respektuje zapisane parametry. W trybie **Automatyczny** parametry są łączone z dynamiczną oceną zmienności rynku. Suwak wpływu parametrów bazowych pozwala ustalić, jak mocno ustawienia użytkownika wpływają na wynik automatycznej adaptacji. ### 6. Logika sygnału System analizuje zamknięte świece, a nie aktualnie formującą się świecę. Sygnał LONG wymaga potwierdzenia m.in.: - EMA szybka powyżej EMA wolnej, - zgodnego kierunku DI, - ADX powyżej ustalonego minimum, - dodatniego MACD histogramu, - ceny powyżej szybkiej EMA, - RSI w dopuszczalnym zakresie. Sygnał SHORT działa analogicznie w drugą stronę. System nie wymaga już świeżego przecięcia ceny z EMA na jednej konkretnej świecy. Był to zbyt restrykcyjny warunek, który mógł praktycznie wyeliminować transakcje. ### 7. Otwieranie pozycji Po wykryciu sygnału system: 1. sprawdza limit aktywnych pozycji, 2. sprawdza istniejącą pozycję na symbolu, 3. sprawdza blokadę antyduplikacyjną, 4. dobiera dźwignię, 5. oblicza wartość pozycji, 6. przelicza wartość bazową na liczbę kontraktów z uwzględnieniem `contractSize`, 7. zaokrągla ilość do precyzji giełdy, 8. ponownie sprawdza pozycję, 9. blokuje symbol przed ponownym wejściem, 10. wysyła zlecenie market. To przeliczenie kontraktów jest istotne dla futures: liczba kontraktów nie zawsze jest równa ilości bazowej kryptowaluty. ### 8. Stop Loss i Take Profit Po wykonaniu wejścia system pobiera rzeczywistą cenę wejścia z odpowiedzi zlecenia lub z pozycji na giełdzie. Dopiero na tej cenie wyliczane są poziomy SL i TP. System próbuje utworzyć ochronę giełdową poprzez mechanizm trigger/reduce-only. Dodatkowo działa lokalny strażnik ROE w workerze. Jeżeli natywne zlecenie ochronne giełdy nie jest obsługiwane w danym wariancie API, worker nadal monitoruje pozycję i może zamknąć ją rynkowo po osiągnięciu ustawionego poziomu ROE. ### 9. Worker na serwerze Na Hetznerze zalecany jest osobny proces: ```bash python app.py --worker ``` Proces ten nie zależy od otwartej karty przeglądarki. Worker sprawdza aktywne boty zapisane w SQLite, skanuje rynek, zapisuje wyniki i obsługuje pozycje. ### 10. Streamlit Uruchomienie panelu: ```bash streamlit run app.py ``` Panel służy do konfiguracji, podglądu i ręcznego sterowania. Silnik tradingowy może działać jako osobny proces `--worker`. ### 11. Kill Switch Przycisk **ZAMKNIJ WSZYSTKO** próbuje zamknąć wszystkie wykryte pozycje futures przez zlecenia market z `reduceOnly`. Następnie zatrzymuje aktywne boty użytkownika. Po użyciu Kill Switch należy sprawdzić pozycje bezpośrednio na giełdzie. ### 12. Co sprawdzić przed uruchomieniem produkcyjnym - poprawność API, - brak uprawnień do wypłat, - właściwy typ konta futures, - saldo USDT, - minimalną wartość kontraktu, - maksymalną dźwignię, - ustawienia SL/TP, - liczbę pozycji, - liczbę skanowanych par, - log `trading_bot.log`, - pozycje bezpośrednio na giełdzie. ### 13. Diagnostyka Jeżeli skaner nie pokazuje danych: 1. sprawdź, czy bot MTF jest aktywny, 2. sprawdź klucze API, 3. sprawdź saldo Futures, 4. sprawdź `trading_bot.log`, 5. sprawdź, czy giełda zwraca aktywne liniowe swapy USDT, 6. sprawdź, czy wolumen przekracza minimalny filtr. Jeżeli bot widzi sygnały, ale nie składa zleceń: 1. sprawdź liczbę aktywnych pozycji, 2. sprawdź saldo wolne, 3. sprawdź minimalny rozmiar kontraktu, 4. sprawdź `contractSize`, 5. sprawdź limit dźwigni, 6. sprawdź błędy API w logu. ### 14. Ważne Nigdy nie zakładaj, że sam fakt pojawienia się sygnału oznacza, że giełda zaakceptowała zlecenie. Ostatecznym źródłem prawdy dla pozycji, zlecenia i salda jest konto użytkownika na giełdzie. """)


# ============================================================
# GŁÓWNY INTERFEJS
# ============================================================

@st.cache_resource(show_spinner=False)
def get_streamlit_worker_service():
    """Start one non-blocking worker coordinator per Streamlit process. A separate `python app.py --worker` service is still the preferred server deployment. This fallback makes the app actually trade when the user launches only Streamlit, while keeping the UI thread free. """
    stop_event = threading.Event()

    def coordinator():
        log.info("Embedded worker coordinator started")
        while not stop_event.is_set():
            try:
                MANAGER.reconcile()
            except Exception:
                log.exception("Embedded worker reconcile failed")
            stop_event.wait(max(2, WORKER_POLL_SECONDS))

    thread = threading.Thread(target=coordinator, daemon=True, name="embedded-bot-manager")
    thread.start()
    return stop_event, thread


def render_scanner_live(user_id: int, max_scan: int, active_count: int) -> None:
    """Render only the scanner pane; safe to rerun independently from the UI."""
    st.markdown(
        f""" <div class="section-card"> <div class="section-title"> 🔎 {t('market_scanner_results')} <span class="scanner-live" style="float:right">● SKANER W TLE</span> </div> <div style="color:#9d9487;font-size:12px"> Worker skanuje partiami w tle i zapisuje wyniki w SQLite. Panel odświeża tylko ten fragment, bez zatrzymywania silnika. </div> """, unsafe_allow_html=True,
    )

    active_tfs = [
        tf for tf in ["1h", "4h", "1d", "30m", "15m", "5m", "1m"]
        if tf in st.session_state.get("active_mtf_bots", {})
    ]
    scanner_df = read_scanner_rows(
        user_id,
        max(100, max_scan * max(1, active_count)),
        active_tfs,
    )
    # DB is deliberately a live snapshot. If a legacy row from an older
    # generation survives, show only the timeframe with the newest update.
    if not scanner_df.empty and "Aktualizacja" in scanner_df.columns:
        latest_tf = (
            scanner_df.groupby("Interwał")["Aktualizacja"]
            .max()
            .sort_values()
            .index[-1]
        )
        scanner_df = scanner_df[scanner_df["Interwał"] == latest_tf].copy()
    if not scanner_df.empty:
        scanner_df["Wolumen_24h"] = pd.to_numeric(scanner_df["Wolumen_24h"], errors="coerce").fillna(0.0)
        scanner_df["ADX"] = pd.to_numeric(scanner_df["ADX"], errors="coerce").round(2)
        scanner_df["RSI"] = pd.to_numeric(scanner_df["RSI"], errors="coerce").round(2)
        scanner_df = scanner_df.rename(columns={
            "EMA_Szybka": "EMA szybka",
            "EMA_Wolna": "EMA wolna",
            "Wolumen_24h": "Wolumen 24h",
        })
        st.dataframe(scanner_df, use_container_width=True, hide_index=True)
    else:
        st.info(t("no_scanner"))
    st.markdown("</div>", unsafe_allow_html=True)


def run_streamlit_app() -> None:
    st.set_page_config(
        page_title="Multi-Exchange Futures SaaS",
        layout="wide",
    )

    init_db()
    # Non-blocking background trading. No sleep/rerun is performed on the
    # Streamlit request thread.
    MANAGER = get_streamlit_worker_service()

    for key, value in SESSION_DEFAULTS.items():
        if key not in st.session_state:
            st.session_state[key] = value

    st.markdown(""" <style> :root { --bg:#080706; --panel:#11100e; --gold:#d9ad4a; --gold2:#f3d57a; --gold3:#8d6a27; --green:#1fc56b; --red:#e05252; --muted:#9d9487; --text:#f5f0e6; } .stApp { background: radial-gradient(circle at 50% -10%,#292015 0%,#0b0908 35%,#070605 100%); color:var(--text); } [data-testid="stHeader"] { background:rgba(0,0,0,0); } section[data-testid="stSidebar"] { background:linear-gradient(180deg,#15120f,#0b0908); border-right:2px solid var(--gold3); } .block-container { padding-top:1.2rem; max-width:1700px; } h1,h2,h3 { color:var(--gold2)!important; } .section-card { border:1px solid #765b2c; border-radius:15px; padding:15px 17px; background:linear-gradient(145deg,rgba(22,18,13,.96),rgba(10,9,8,.96)); margin:12px 0; box-shadow:0 7px 24px rgba(0,0,0,.28); } .section-title { color:var(--gold2); font-weight:900; font-size:16px; letter-spacing:.8px; margin-bottom:10px; } .metric-grid { display:grid; grid-template-columns:repeat(4,minmax(0,1fr)); gap:12px; margin:8px 0 20px; } .metric-card { min-height:110px; border:1px solid var(--gold); border-radius:14px; padding:15px 17px; background:linear-gradient(145deg,#1a1510,#0e0c0a); } .metric-card.green { border-color:#27b968; } .metric-card.red { border-color:#b84b4b; } .metric-label { font-size:12px; text-transform:uppercase; letter-spacing:1px; color:var(--gold2); font-weight:800; } .metric-value { font-size:25px; font-weight:900; color:#fff; margin-top:8px; } .metric-sub { font-size:12px; color:#a9a092; margin-top:8px; } .mtf-card { border:1px solid var(--gold3); border-radius:13px; background:linear-gradient(180deg,#17120d,#0d0b09); padding:10px; min-height:100%; } .mtf-card.active { border:2px solid #27c96f; box-shadow:0 0 18px rgba(39,201,111,.16), inset 0 0 18px rgba(39,201,111,.04); } /* Premium gold framed Streamlit controls */ div[data-testid="stButton"] > button, div[data-testid="stFormSubmitButton"] > button { border:1.5px solid var(--gold)!important; border-radius:11px!important; background:linear-gradient(145deg,#1d1710,#0d0b09)!important; color:#f7e8bf!important; font-weight:850!important; box-shadow:0 0 0 1px rgba(217,173,74,.08), 0 5px 18px rgba(0,0,0,.25); } div[data-testid="stButton"] > button:hover, div[data-testid="stFormSubmitButton"] > button:hover { border-color:#f3d57a!important; color:#fff4d0!important; transform:translateY(-1px); box-shadow:0 0 18px rgba(217,173,74,.20); } section[data-testid="stSidebar"] div[data-testid="stButton"] > button[kind="primary"] { border:2px solid var(--gold)!important; background:linear-gradient(145deg,#12351f,#0b2114)!important; color:#7dffad!important; box-shadow:0 0 16px rgba(39,201,111,.18), inset 0 0 12px rgba(217,173,74,.08); } section[data-testid="stSidebar"] div[data-testid="stButton"] > button[kind="primary"]:hover { border-color:#f3d57a!important; background:linear-gradient(145deg,#174a2a,#0d2918)!important; } div[data-baseweb="input"], div[data-baseweb="select"], div[data-baseweb="textarea"] { border:1px solid #8d6a27!important; border-radius:9px!important; background:#0e0c0a!important; } div[data-baseweb="input"]:focus-within, div[data-baseweb="select"]:focus-within { border-color:#f3d57a!important; box-shadow:0 0 0 1px rgba(243,213,122,.35)!important; } div[data-testid="stDataFrame"] { border:1px solid #8d6a27!important; border-radius:12px!important; overflow:hidden; box-shadow:0 8px 24px rgba(0,0,0,.22); } div[data-testid="stExpander"] { border:1px solid #8d6a27!important; border-radius:12px!important; background:rgba(15,12,9,.75)!important; } button[role="tab"] { color:#d9ad4a!important; } button[role="tab"][aria-selected="true"] { color:#fff0bf!important; border-bottom:2px solid #d9ad4a!important; } .scanner-live { display:inline-flex; align-items:center; gap:8px; padding:6px 10px; border:1px solid #27c96f; border-radius:999px; color:#75f3a4; background:rgba(25,100,55,.12); font-size:11px; font-weight:800; } @media(max-width:1100px) { .metric-grid { grid-template-columns:repeat(2,minmax(0,1fr)); } } @media(max-width:650px) { .metric-grid { grid-template-columns:1fr; } } </style> """, unsafe_allow_html=True)

    if not st.session_state.logged_in:
        ui_login()
        st.stop()

    apply_mtf_to_session(
        st.session_state.user_id
    )

    # --------------------------------------------------------
    # SIDEBAR
    # --------------------------------------------------------

    st.session_state.lang = st.sidebar.selectbox(
        "🌐 Język / Language",
        ["Polski", "English"],
        index=(
            0
            if st.session_state.lang == "Polski"
            else 1
        ),
        key="lang_selector",
    )

    st.sidebar.markdown(
        f"### 👤 {st.session_state.user_email}"
    )

    st.sidebar.markdown(
        "**"
        + (
            t("sidebar_role_admin")
            if is_user_admin()
            else t("sidebar_role_client")
        )
        + "**"
    )

    if st.sidebar.button(
        t("logout_btn"),
        use_container_width=True,
    ):
        for key in [
            "logged_in",
            "user_email",
            "is_admin",
            "user_id",
            "stripe_paid",
            "api_key",
            "secret_key",
            "passphrase",
        ]:
            st.session_state[key] = (
                SESSION_DEFAULTS[key]
            )

        st.session_state.active_mtf_bots = {}
        st.session_state._mtf_loaded_user_id = None
        st.rerun()

    # --------------------------------------------------------
    # API
    # --------------------------------------------------------

    st.sidebar.header(
        t("exchange_settings")
    )

    selected_exchange = st.sidebar.selectbox(
        t("select_exchange"),
        SUPPORTED_EXCHANGES,
        index=(
            SUPPORTED_EXCHANGES.index(
                st.session_state.selected_exchange
            )
            if st.session_state.selected_exchange
            in SUPPORTED_EXCHANGES
            else 0
        ),
        key="sidebar_selected_exchange",
    )

    st.session_state.selected_exchange = (
        selected_exchange
    )

    api = st.sidebar.text_input(
        f"API Key ({selected_exchange})",
        value=st.session_state.api_key,
        type="password",
        key=f"api_{selected_exchange}",
    )

    secret = st.sidebar.text_input(
        f"API Secret ({selected_exchange})",
        value=st.session_state.secret_key,
        type="password",
        key=f"secret_{selected_exchange}",
    )

    passphrase = (
        st.sidebar.text_input(
            f"Passphrase ({selected_exchange})",
            value=st.session_state.passphrase,
            type="password",
            key=f"pass_{selected_exchange}",
        )
        if selected_exchange in {"Bitget", "OKX"}
        else ""
    )

    if st.sidebar.button(
        t("save_keys_btn"),
        use_container_width=True,
    ):
        if api and secret:
            st.session_state.api_key = api
            st.session_state.secret_key = secret
            st.session_state.passphrase = (
                passphrase
            )

            conn = db_connect()
            conn.execute(""" UPDATE users SET api_key=?, secret_key=?, passphrase=?, selected_exchange=? WHERE id=? """, (
                api,
                secret,
                passphrase,
                selected_exchange,
                st.session_state.user_id,
            ))
            conn.commit()
            conn.close()

            st.success(
                f"{t('keys_saved')} "
                f"{selected_exchange}"
            )
            st.rerun()
        else:
            st.error(
                t("keys_error")
            )

    # --------------------------------------------------------
    # SUBSCRIPTION
    # --------------------------------------------------------

    st.sidebar.markdown("---")
    st.sidebar.markdown(
        f"### {t('sub_zone')}"
    )

    if is_user_paid():
        st.sidebar.success(
            t("sub_active")
        )
    else:
        st.sidebar.warning(
            t("sub_inactive")
        )

    price_id = get_secret(
        "STRIPE_PRICE_ID",
        STRIPE_PRICE_ID,
    )

    st.sidebar.link_button(
        t("pay_btn"),
        create_stripe_checkout_session(
            st.session_state.user_email,
            price_id,
        ),
        use_container_width=True,
    )

    if (
        ALLOW_TEST_ACTIVATION
        and st.sidebar.button(
            "⚡ [TEST] Aktywuj dostęp natychmiast"
        )
    ):
        conn = db_connect()
        conn.execute(
            "UPDATE users SET stripe_paid=1 WHERE id=?",
            (st.session_state.user_id,),
        )
        conn.commit()
        conn.close()

        st.session_state.stripe_paid = True
        st.rerun()

    # --------------------------------------------------------
    # RYZYKO
    # --------------------------------------------------------

    saved_risk = get_user_risk_settings(
        st.session_state.user_id
    )

    st.sidebar.markdown("---")
    st.sidebar.markdown(
        f"### {t('capital_risk')}"
    )

    max_single = st.sidebar.number_input(
        t("max_single"),
        5.0,
        5000.0,
        float(saved_risk["max_single"]),
        5.0,
        key="sb_max_single_trade",
    )

    max_pos = st.sidebar.slider(
        t("max_pos"),
        1,
        20,
        int(saved_risk["max_positions"]),
        key="sb_max_active_pos",
    )

    st.sidebar.markdown("---")
    st.sidebar.markdown(
        f"### {t('roe_guard')}"
    )

    enable_roe = st.sidebar.checkbox(
        t("enable_roe"),
        bool(saved_risk["enable_roe"]),
        key="enable_roe_guard",
    )

    stop_roe = (
        st.sidebar.slider(
            t("sl_roe"),
            0.5,
            50.0,
            float(saved_risk["stop_roe"]),
            0.5,
            key="custom_stop_loss_roe",
        )
        if enable_roe
        else 999.0
    )

    take_roe = (
        st.sidebar.slider(
            t("tp_roe"),
            1.0,
            100.0,
            float(saved_risk["take_roe"]),
            0.5,
            key="custom_take_profit_roe",
        )
        if enable_roe
        else 999.0
    )

    cooldown = st.sidebar.slider(
        "Czas oddechu po SL/TP (minuty)",
        1,
        120,
        int(saved_risk["cooldown_minutes"]),
        key="sb_cooldown_sl_tp",
    )

    st.sidebar.markdown("---")
    st.sidebar.markdown(
        f"### {t('leverage_mgmt')}"
    )

    lev_mode = st.sidebar.radio(
        t("lev_mode"),
        [
            "Autonomiczny (płynny w granicach limitu)",
            "Ręczny",
        ],
        index=(
            0
            if saved_risk["leverage_mode"]
            != "Ręczny"
            else 1
        ),
        key="sb_leverage_mode",
    )

    max_lev = st.sidebar.slider(
        t("max_allowed_lev"),
        1,
        50,
        int(saved_risk["max_leverage"]),
        key="sb_max_allowed_leverage",
    )

    manual_lev = st.sidebar.slider(
        t("manual_lev"),
        1,
        50,
        int(saved_risk["manual_leverage"]),
        key="sb_manual_leverage",
    )

    st.sidebar.markdown("---")

    max_scan = st.sidebar.slider(
        t("max_pairs"),
        1,
        100,
        int(saved_risk["max_scan_pairs"]),
        key="sb_max_fut_pairs",
    )

    auto_influence = st.sidebar.slider(
        "🎚️ Wpływ ustawień bazowych Auto (%)",
        0,
        100,
        int(saved_risk["auto_base_influence"]),
        5,
        key="sb_auto_base_influence",
    )

    refresh = st.sidebar.slider(
        "Częstotliwość odświeżania widoku (sekundy)",
        5,
        60,
        15,
        key="sb_auto_refresh",
    )

    risk_now = {
        "max_single": max_single,
        "max_positions": max_pos,
        "enable_roe": enable_roe,
        "stop_roe": stop_roe,
        "take_roe": take_roe,
        "max_leverage": max_lev,
        "manual_leverage": manual_lev,
        "leverage_mode": lev_mode,
        "max_scan_pairs": max_scan,
        "auto_base_influence": auto_influence,
        "cooldown_minutes": cooldown,
    }

    if risk_now != saved_risk:
        save_user_risk_settings(
            st.session_state.user_id,
            risk_now,
        )

    # --------------------------------------------------------
    # MTF
    # --------------------------------------------------------

    st.markdown(
        """ <div class="section-card"> <div class="section-title"> 🤖 MTF — KONTROLA AUTONOMICZNYCH BOTÓW </div> <div style="color:#9d9487;font-size:12px"> Każdy interwał działa niezależnie. Ustawienia, aktywne boty i wyniki skanera są zapisywane w SQLite. </div> </div> """,
        unsafe_allow_html=True,
    )

    cols = st.columns(
        len(AVAILABLE_TIMEFRAMES)
    )

    for i, tf in enumerate(
        AVAILABLE_TIMEFRAMES
    ):
        with cols[i]:
            active_tf = (
                tf
                in st.session_state.active_mtf_bots
            )

            st.markdown(
                f""" <div class="mtf-card"> <b style="color:#f3d57a"> ⏱ {tf} </b> <br> <span style="color:{'#58e893' if active_tf else '#f07d7d'}"> {'● AKTYWNY' if active_tf else '○ GOTOWY'} </span> """,
                unsafe_allow_html=True,
            )

            mode = st.radio(
                f"Tryb ({tf})",
                [
                    "Automatyczny",
                    "Ręczny",
                ],
                key=f"radio_mode_{tf}",
            )

            f = st.number_input(
                f"EMA Szybka ({tf})",
                1,
                200,
                key=f"ema_f_{tf}",
            )

            s = st.number_input(
                f"EMA Wolna ({tf})",
                2,
                300,
                key=f"ema_s_{tf}",
            )

            adx = st.slider(
                f"Min ADX ({tf})",
                10.0,
                50.0,
                key=f"adx_{tf}",
            )

            maxr = st.slider(
                f"Max RSI Long ({tf})",
                50.0,
                95.0,
                key=f"max_rsi_{tf}",
            )

            minr = st.slider(
                f"Min RSI Short ({tf})",
                5.0,
                50.0,
                key=f"min_rsi_{tf}",
            )

            cap = st.number_input(
                f"CAP x ({tf})",
                0.1,
                10.0,
                float(
                    st.session_state.get(
                        f"cap_mult_{tf}",
                        DEFAULT_TF_VALUES[tf][
                            "cap_mult"
                        ],
                    )
                ),
                0.1,
                key=f"cap_mult_{tf}",
            )

            if f >= s:
                st.warning(
                    "EMA szybka musi być mniejsza od wolnej."
                )

            cfg = {
                "mode": mode,
                "ema_fast": min(
                    int(f),
                    int(s) - 1,
                ),
                "ema_slow": max(
                    int(s),
                    int(f) + 1,
                ),
                "min_adx": float(adx),
                "max_rsi": float(maxr),
                "min_rsi": float(minr),
                "capital_multiplier": float(cap),
                "tf": tf,
            }

            if active_tf:
                st.success(
                    "🟢 AKTYWNY"
                )

                if st.button(
                    f"Zatrzymaj {tf}",
                    key=f"stop_{tf}",
                    use_container_width=True,
                ):
                    st.session_state.active_mtf_bots.pop(
                        tf,
                        None,
                    )

                    save_active_bots(
                        st.session_state.user_id,
                        st.session_state.active_mtf_bots,
                    )

                    st.rerun()
            else:
                if st.button(
                    f"Uruchom {tf}",
                    key=f"start_{tf}",
                    use_container_width=True,
                ):
                    if (
                        not st.session_state.api_key
                        or not st.session_state.secret_key
                    ):
                        st.error(
                            "Najpierw zapisz klucze API."
                        )
                    elif not is_user_paid():
                        st.error(
                            "Wymagana aktywna subskrypcja."
                        )
                    else:
                        st.session_state.active_mtf_bots[
                            tf
                        ] = cfg

                        save_active_bots(
                            st.session_state.user_id,
                            st.session_state.active_mtf_bots,
                        )

                        save_mtf_settings(
                            st.session_state.user_id,
                            current_mtf_payload(),
                        )

                        MANAGER.reconcile()
                        st.rerun()

            st.markdown(
                "</div>",
                unsafe_allow_html=True,
            )

    # Save only after widgets have resolved their values.
    # If a bot is already active, update its runtime configuration too.
    # Previously active_mtf_bots kept the values captured at START time, so
    # changing EMA/ADX/RSI in the UI did not reach the worker.
    mtf_payload = current_mtf_payload()
    save_mtf_settings(st.session_state.user_id, mtf_payload)

    active_changed = False
    for active_tf in list(st.session_state.active_mtf_bots):
        if active_tf in mtf_payload:
            runtime_cfg = dict(mtf_payload[active_tf])
            runtime_cfg["tf"] = active_tf
            if runtime_cfg != st.session_state.active_mtf_bots.get(active_tf):
                st.session_state.active_mtf_bots[active_tf] = runtime_cfg
                active_changed = True
    if active_changed:
        save_active_bots(
            st.session_state.user_id,
            st.session_state.active_mtf_bots,
        )

    # Worker in Streamlit process.
    MANAGER.reconcile()

    # --------------------------------------------------------
    # KILL SWITCH
    # --------------------------------------------------------

    if st.sidebar.button(
        t("kill_switch"),
        type="primary",
        use_container_width=True,
    ):
        ex = get_exchange(
            st.session_state.api_key,
            st.session_state.secret_key,
            st.session_state.passphrase,
            st.session_state.selected_exchange,
        )

        if ex:
            for p in fetch_positions_safe(ex):
                close_position(
                    ex,
                    p,
                    "KILL SWITCH",
                )

        st.session_state.active_mtf_bots = {}

        save_active_bots(
            st.session_state.user_id,
            {},
        )

        MANAGER.reconcile()

        st.success(
            "🔴 KILL SWITCH WYKONANY. "
            "Boty zatrzymane i pozycje zamknięte "
            "w zakresie pozycji wykrytych przez API."
        )

        st.rerun()

    # --------------------------------------------------------
    # DASHBOARD
    # --------------------------------------------------------

    st.markdown(
        f""" <div style=" display:flex; justify-content:space-between; background:#15110c; border:1px solid #8d6a27; border-radius:14px; padding:12px 16px; margin-bottom:14px; "> <b style="color:#f3d57a"> 💠 FUTURES CONTROL CENTER </b> <span> 👤 {st.session_state.user_email} · {st.session_state.selected_exchange} </span> </div> """,
        unsafe_allow_html=True,
    )

    ex = get_exchange(
        st.session_state.api_key,
        st.session_state.secret_key,
        st.session_state.passphrase,
        st.session_state.selected_exchange,
    )

    positions = (
        fetch_positions_safe(ex)
        if ex
        else []
    )

    positions = [
        p
        for p in positions
        if position_contracts(p) > 0
    ]

    total_unreal = sum(
        safe_float(
            p.get("unrealizedPnl")
        )
        for p in positions
    )

    balance_snapshot = (
        fetch_usdt_balance(ex)
        if ex
        else {
            "total": 0.0,
            "used": 0.0,
            "free": 0.0,
        }
    )

    balance = balance_snapshot["total"]
    used = balance_snapshot["used"]
    free = balance_snapshot["free"]

    if (
        not st.session_state.session_baseline_locked
        and balance > 0
    ):
        st.session_state.session_start_balance = balance
        st.session_state.session_baseline_locked = True

    pnl_pct = (
        (
            balance
            - st.session_state.session_start_balance
        )
        / st.session_state.session_start_balance
        * 100
        if st.session_state.session_start_balance > 0
        else 0.0
    )

    elapsed = max(
        0,
        int(
            (
                datetime.now()
                - st.session_state.session_start_time
            ).total_seconds()
        ),
    )

    h, rem = divmod(
        elapsed,
        3600,
    )
    m, sx = divmod(
        rem,
        60,
    )

    pnl_cls = (
        "green"
        if pnl_pct >= 0
        else "red"
    )

    st.markdown(
        f""" <div class="metric-grid"> <div class="metric-card"> <div class="metric-label"> 💰 {t('wallet_futures')} </div> <div class="metric-value"> {balance:.2f} USDT </div> <div class="metric-sub"> Zajęte: <b>{used:.2f}</b> · {t('free_balance')}: <b>{free:.2f}</b> </div> </div> <div class="metric-card {pnl_cls}"> <div class="metric-label"> 📈 {t('session_results')} </div> <div class="metric-value"> {pnl_pct:+.2f}% </div> <div class="metric-sub"> {t('pnl_usdt')}: <b> {total_unreal:+.2f} USDT</b> </div> </div> <div class="metric-card"> <div class="metric-label"> 🎯 {t('slots_futures')} </div> <div class="metric-value"> {len(positions)} / {max_pos} </div> <div class="metric-sub"> Wolne sloty: <b>{max(0,max_pos-len(positions))}</b> </div> </div> <div class="metric-card"> <div class="metric-label"> ⚡ {t('session_time')} </div> <div class="metric-value"> {h:02d}:{m:02d}:{sx:02d} </div> <div class="metric-sub"> Aktywne boty: <b>{len(st.session_state.active_mtf_bots)}</b> </div> </div> </div> """,
        unsafe_allow_html=True,
    )

    # --------------------------------------------------------
    # POZYCJE
    # --------------------------------------------------------

    st.markdown(
        f""" <div class="section-card"> <div class="section-title"> 📈 {t('active_positions')} </div> """,
        unsafe_allow_html=True,
    )

    if positions:
        st.dataframe(
            pd.DataFrame(positions),
            use_container_width=True,
        )
    else:
        st.info(
            t("no_positions")
        )

    st.markdown(
        "</div>",
        unsafe_allow_html=True,
    )

    # --------------------------------------------------------
    # HISTORIA
    # --------------------------------------------------------

    st.markdown(
        f""" <div class="section-card"> <div class="section-title"> 📜 {t('trade_history')} </div> """,
        unsafe_allow_html=True,
    )

    conn = db_connect()

    try:
        hist = pd.read_sql_query(""" SELECT created_at, symbol, timeframe, action, side, price, amount, order_id, message FROM trade_log WHERE user_id=? ORDER BY id DESC LIMIT 200 """, conn, params=(
            st.session_state.user_id,
        ))
    except Exception:
        hist = pd.DataFrame()
    finally:
        conn.close()

    if not hist.empty:
        st.dataframe(
            hist,
            use_container_width=True,
        )
    else:
        st.info(
            t("no_history")
        )

    st.markdown(
        "</div>",
        unsafe_allow_html=True,
    )

    # --------------------------------------------------------
    # SKANER — CZYTA Z BAZY
    # --------------------------------------------------------
    # Streamlit >= 1.37: refresh only the scanner pane. Older Streamlit
    # versions simply render the same persistent SQLite data once per app
    # rerun, so the trading worker is never dependent on fragment support.
    if callable(getattr(st, "fragment", None)):
        st.fragment(run_every=f"{refresh}s")
        def _live_scanner():
            render_scanner_live(
                st.session_state.user_id,
                max_scan,
                len(st.session_state.active_mtf_bots),
            )
        _live_scanner()
    else:
        render_scanner_live(
            st.session_state.user_id,
            max_scan,
            len(st.session_state.active_mtf_bots),
        )

    # --------------------------------------------------------
    # ADMIN
    # --------------------------------------------------------

    if is_user_admin():
        st.markdown(
            f""" <div class="section-card"> <div class="section-title"> 👑 {t('admin_panel')} </div> """,
            unsafe_allow_html=True,
        )

        conn = db_connect()
        try:
            users_df = pd.read_sql_query(""" SELECT id, email, is_admin, stripe_paid, selected_exchange FROM users ORDER BY id DESC """, conn)
        finally:
            conn.close()

        st.dataframe(
            users_df,
            use_container_width=True,
        )

        st.markdown(
            "</div>",
            unsafe_allow_html=True,
        )

    # --------------------------------------------------------
    # REGULAMIN I INSTRUKCJA
    # --------------------------------------------------------

    render_rules_and_manual()

    # Do not sleep or call st.rerun() here. That blocks a Streamlit request
    # and causes unnecessary memory/CPU churn. The trading engine is a
    # background worker; the dashboard reads its persistent SQLite results.

def run_worker_mode() -> None:
                    """Główna funkcja uruchamiająca workery w tle."""
                    # Pobieramy użytkowników bezpośrednio z bazy SQLite używanej w aplikacji
                    try:
                        import sqlite3
                        conn = sqlite3.connect("users.db") # Zmień nazwę pliku bazy, jeśli masz inną
                        conn.row_factory = sqlite3.Row
                        cursor = conn.cursor()
                        cursor.execute("SELECT * FROM users")
                        users = [dict(row) for row in cursor.fetchall()]
                        conn.close()
                    except Exception:
                        users = []

                    if not users:
                        log.warning("No active users found for worker mode.")
                        return

                    stop_event = threading.Event()
                    threads = []

                    for user in users:
                        worker = UserWorker(user)
                        t = threading.Thread(target=worker.loop, args=(stop_event,), daemon=True)
                        t.start()
                        threads.append(t)

                    try:
                        while True:
                            time.sleep(1)
                    except KeyboardInterrupt:
                        log.info("Stopping workers...")
                        stop_event.set()
                        for t in threads:
                            t.join()



# ============================================================
# ENTRY POINT
# ============================================================

if __name__ == "__main__":
    parser = argparse.ArgumentParser()

    parser.add_argument(
        "--worker",
        action="store_true",
        help=(
            "Uruchom autonomiczny silnik "
            "tradingowy bez Streamlit"
        ),
    )

    args, _ = parser.parse_known_args()

    if args.worker:
        run_worker_mode()
    else:
        run_streamlit_app()

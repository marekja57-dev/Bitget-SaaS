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
if stripe is not None and STRIPE_SECRET_KEY:
    stripe.api_key = STRIPE_SECRET_KEY

# Risk defaults. SL/TP are ROE values, while the exchange protection is also
# converted to actual prices after the real entry price is known.
DEFAULT_STOP_ROE = 4.0
DEFAULT_TAKE_ROE = 15.0
DEFAULT_RISK_PCT = 0.01
DEFAULT_MAX_SINGLE = 50.0
DEFAULT_MAX_POSITIONS = 5
DEFAULT_MAX_LEVERAGE = 15
DEFAULT_MANUAL_LEVERAGE = 5
DEFAULT_MAX_SCAN_PAIRS = 30
MIN_QUOTE_VOLUME = 1_000_000.0

# The trading worker is deliberately independent of Streamlit reruns.
WORKER_POLL_SECONDS = max(2, int(os.getenv("BOT_POLL_SECONDS", "5")))
POSITION_GUARD_SECONDS = max(1, int(os.getenv("POSITION_GUARD_SECONDS", "3")))

logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO").upper(),
    format="%(asctime)s | %(levelname)s | %(threadName)s | %(message)s",
    handlers=[logging.StreamHandler(), logging.FileHandler(LOG_FILE, encoding="utf-8")],
)
log = logging.getLogger("futures_saas")

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


def t(key: str) -> str:
    lang = st.session_state.get("lang", "Polski")
    return TRANSLATIONS.get(lang, TRANSLATIONS["Polski"]).get(key, key)


# ============================================================
# DATABASE
# ============================================================

def db_connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_FILE, timeout=30.0, check_same_thread=False)
    conn.execute("PRAGMA busy_timeout=30000")
    return conn


def init_db() -> None:
    conn = db_connect()
    try:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute(
            """CREATE TABLE IF NOT EXISTS users ( id INTEGER PRIMARY KEY AUTOINCREMENT, email TEXT UNIQUE, password TEXT, is_admin INTEGER DEFAULT 0, stripe_paid INTEGER DEFAULT 0, api_key TEXT DEFAULT '', secret_key TEXT DEFAULT '', passphrase TEXT DEFAULT '', selected_exchange TEXT DEFAULT 'Bitget', settings_json TEXT DEFAULT '{}' )"""
        )
        conn.execute(
            """CREATE TABLE IF NOT EXISTS user_mtf_settings ( user_id INTEGER PRIMARY KEY, settings_json TEXT NOT NULL, updated_at TEXT NOT NULL, FOREIGN KEY(user_id) REFERENCES users(id) )"""
        )
        conn.execute(
            """CREATE TABLE IF NOT EXISTS user_bot_state ( user_id INTEGER PRIMARY KEY, active_bots_json TEXT NOT NULL DEFAULT '{}', updated_at TEXT NOT NULL, FOREIGN KEY(user_id) REFERENCES users(id) )"""
        )
        conn.execute(
            """CREATE TABLE IF NOT EXISTS trade_log ( id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL, created_at TEXT NOT NULL, symbol TEXT, timeframe TEXT, action TEXT, side TEXT, price REAL, amount REAL, order_id TEXT, message TEXT, FOREIGN KEY(user_id) REFERENCES users(id) )"""
        )
        # Safe migration for databases from the user's previous version.
        cols = {r[1] for r in conn.execute("PRAGMA table_info(users)").fetchall()}
        for name, typ in [
            ("selected_exchange", "TEXT DEFAULT 'Bitget'"),
            ("settings_json", "TEXT DEFAULT '{}'"),
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
    stored = str(stored)
    if stored.startswith("sha256$"):
        try:
            _, salt, expected = stored.split("$", 2)
            candidate = hashlib.sha256((salt + password).encode()).hexdigest()
            return hmac.compare_digest(candidate, expected)
        except Exception:
            return False
    return hmac.compare_digest(stored, password)


def default_mtf_payload() -> Dict[str, Dict[str, Any]]:
    return {tf: {**vals, "mode": "Automatyczny"} for tf, vals in DEFAULT_TF_VALUES.items()}


def load_mtf_settings(user_id: int) -> Dict[str, Dict[str, Any]]:
    payload = default_mtf_payload()
    conn = db_connect()
    try:
        row = conn.execute(
            "SELECT settings_json FROM user_mtf_settings WHERE user_id=?", (int(user_id),)
        ).fetchone()
    finally:
        conn.close()
    if row and row[0]:
        try:
            saved = json.loads(row[0])
            for tf in AVAILABLE_TIMEFRAMES:
                if isinstance(saved.get(tf), dict):
                    payload[tf].update(saved[tf])
        except Exception:
            log.exception("Invalid MTF JSON for user %s", user_id)
    return payload


def save_mtf_settings(user_id: int, payload: Dict[str, Dict[str, Any]]) -> None:
    conn = db_connect()
    try:
        conn.execute(
            """INSERT INTO user_mtf_settings(user_id,settings_json,updated_at) VALUES(?,?,?) ON CONFLICT(user_id) DO UPDATE SET settings_json=excluded.settings_json,updated_at=excluded.updated_at""",
            (int(user_id), json.dumps(payload, ensure_ascii=False), utc_now()),
        )
        conn.commit()
    finally:
        conn.close()


def load_active_bots(user_id: int) -> Dict[str, Dict[str, Any]]:
    conn = db_connect()
    try:
        row = conn.execute(
            "SELECT active_bots_json FROM user_bot_state WHERE user_id=?", (int(user_id),)
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
        conn.execute(
            """INSERT INTO user_bot_state(user_id,active_bots_json,updated_at) VALUES(?,?,?) ON CONFLICT(user_id) DO UPDATE SET active_bots_json=excluded.active_bots_json,updated_at=excluded.updated_at""",
            (int(user_id), json.dumps(bots, ensure_ascii=False), utc_now()),
        )
        conn.commit()
    finally:
        conn.close()


def log_trade(user_id: int, symbol: str, tf: str, action: str, side: str, price: float = 0.0, amount: float = 0.0, order_id: str = "", message: str = "") -> None:
    conn = db_connect()
    try:
        conn.execute(
            """INSERT INTO trade_log(user_id,created_at,symbol,timeframe,action,side,price,amount,order_id,message) VALUES(?,?,?,?,?,?,?,?,?,?)""",
            (user_id, utc_now(), symbol, tf, action, side, price, amount, order_id, message),
        )
        conn.commit()
    finally:
        conn.close()


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


# ============================================================
# EXCHANGE
# ============================================================

def get_exchange(api_key: str, secret: str, passphrase: str, name: str):
    if not api_key or not secret:
        return None
    try:
        ex_id = name.lower()
        cls = getattr(ccxt, ex_id)
        config = {
            "apiKey": api_key,
            "secret": secret,
            "enableRateLimit": True,
            "timeout": 20000,
            "options": {"defaultType": "swap"},
        }
        if ex_id in {"bitget", "okx"} and passphrase:
            config["password"] = passphrase
        return cls(config)
    except Exception as exc:
        log.error("Exchange init failed for %s: %s", name, exc)
        return None


def safe_float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None or (isinstance(value, float) and np.isnan(value)):
            return default
        return float(value)
    except Exception:
        return default


def position_contracts(p: Dict[str, Any]) -> float:
    return abs(safe_float(p.get("contracts", p.get("amount", 0))))


def position_side(p: Dict[str, Any]) -> str:
    return str(p.get("side", "")).lower()


def is_long(p: Dict[str, Any]) -> bool:
    return position_side(p) in {"long", "buy"}


def close_side_for_position(p: Dict[str, Any]) -> str:
    return "sell" if is_long(p) else "buy"


def reduce_only_params(exchange) -> Dict[str, Any]:
    # reduceOnly is understood by the main USDT perpetual exchanges through CCXT.
    return {"reduceOnly": True}


def fetch_positions_safe(exchange) -> List[Dict[str, Any]]:
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
        log.info("Closed %s %s amount=%s reason=%s", symbol, position_side(p), amount, reason)
        return True
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


def exchange_max_leverage(exchange, symbol: str, fallback: int = 15) -> int:
    try:
        _, _, max_lev = market_limits(exchange, symbol)
        if max_lev > 0:
            return max(1, int(max_lev))
    except Exception:
        pass
    return fallback


def set_leverage_safe(exchange, symbol: str, leverage: int) -> None:
    try:
        exchange.set_leverage(int(leverage), symbol)
    except Exception as exc:
        # Some exchanges require marginMode or position-side params. The actual
        # order can still work with the account's existing leverage.
        log.warning("set_leverage failed for %s at %sx: %s", symbol, leverage, exc)


# ============================================================
# INDICATORS / SIGNALS
# ============================================================

def calculate_indicators(df: pd.DataFrame, ema_fast: int, ema_slow: int, adx_period: int = 14) -> pd.DataFrame:
    df = df.copy()
    for col in ["open", "high", "low", "close", "volume"]:
        df[col] = pd.to_numeric(df[col], errors="coerce")

    df["ema_fast"] = df["close"].ewm(span=max(1, ema_fast), adjust=False).mean()
    df["ema_slow"] = df["close"].ewm(span=max(2, ema_slow), adjust=False).mean()

    exp1 = df["close"].ewm(span=12, adjust=False).mean()
    exp2 = df["close"].ewm(span=26, adjust=False).mean()
    df["macd"] = exp1 - exp2
    df["macd_signal"] = df["macd"].ewm(span=9, adjust=False).mean()
    df["macd_hist"] = df["macd"] - df["macd_signal"]

    prev_close = df["close"].shift(1)
    tr = pd.concat(
        [(df["high"] - df["low"]).abs(),
         (df["high"] - prev_close).abs(),
         (df["low"] - prev_close).abs()], axis=1
    ).max(axis=1)
    up = df["high"].diff()
    down = -df["low"].diff()
    plus_dm = pd.Series(np.where((up > down) & (up > 0), up, 0.0), index=df.index)
    minus_dm = pd.Series(np.where((down > up) & (down > 0), down, 0.0), index=df.index)
    alpha = 1.0 / max(2, adx_period)
    tr_s = tr.ewm(alpha=alpha, adjust=False).mean().replace(0, np.nan)
    plus_s = plus_dm.ewm(alpha=alpha, adjust=False).mean()
    minus_s = minus_dm.ewm(alpha=alpha, adjust=False).mean()
    df["plus_di"] = 100 * plus_s / tr_s
    df["minus_di"] = 100 * minus_s / tr_s
    di_sum = (df["plus_di"] + df["minus_di"]).replace(0, np.nan)
    df["dx"] = 100 * (df["plus_di"] - df["minus_di"]).abs() / di_sum
    df["adx"] = df["dx"].ewm(alpha=alpha, adjust=False).mean()

    delta = df["close"].diff()
    gain = delta.clip(lower=0).ewm(span=14, adjust=False).mean()
    loss = (-delta.clip(upper=0)).ewm(span=14, adjust=False).mean()
    rs = gain / loss.replace(0, np.nan)
    df["rsi"] = 100 - 100 / (1 + rs)
    return df


def get_dynamic_parameters(df: pd.DataFrame, tf: str) -> Dict[str, float]:
    try:
        closes = pd.to_numeric(df["close"], errors="coerce").dropna().values
        if len(closes) < 30:
            raise ValueError("not enough data")
        returns = np.diff(closes) / closes[:-1]
        vol = float(np.std(returns) * np.sqrt(len(returns)))
        if tf in {"1m", "5m"}:
            return {"ema_fast": 5 if vol > 0.02 else 9, "ema_slow": 13 if vol > 0.02 else 21,
                    "min_adx": 22.0 if vol > 0.02 else 26.0, "max_rsi": 72.0 if vol > 0.02 else 75.0,
                    "min_rsi": 28.0 if vol > 0.02 else 25.0, "capital_multiplier": 0.6 if vol > 0.02 else 0.8}
        if tf in {"15m", "30m"}:
            return {"ema_fast": 7 if vol > 0.03 else 10, "ema_slow": 18 if vol > 0.03 else 25,
                    "min_adx": 24.0 if vol > 0.03 else 25.0, "max_rsi": 70.0 if vol > 0.03 else 78.0,
                    "min_rsi": 30.0 if vol > 0.03 else 22.0, "capital_multiplier": 1.0 if vol > 0.03 else 1.2}
        return {"ema_fast": 12, "ema_slow": 26, "min_adx": 20.0, "max_rsi": 80.0,
                "min_rsi": 20.0, "capital_multiplier": 2.5}
    except Exception:
        return {"ema_fast": 9, "ema_slow": 21, "min_adx": 25.0, "max_rsi": 75.0,
                "min_rsi": 25.0, "capital_multiplier": 1.0}


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
    fast = int(cfg.get("ema_fast", 9))
    slow = int(cfg.get("ema_slow", 21))
    if fast >= slow:
        fast, slow = slow, fast
    params = {
        "ema_fast": fast,
        "ema_slow": slow,
        "min_adx": float(cfg.get("min_adx", 28.0)),
        "max_rsi": float(cfg.get("max_rsi", 75.0)),
        "min_rsi": float(cfg.get("min_rsi", 25.0)),
        "capital_multiplier": float(cfg.get("capital_multiplier", 1.0)),
    }
    if cfg.get("mode") == "Automatyczny":
        params = blend_params(params, get_dynamic_parameters(df, cfg.get("tf", "15m")), auto_base_influence)
        if params["ema_fast"] >= params["ema_slow"]:
            params["ema_fast"], params["ema_slow"] = params["ema_slow"], params["ema_fast"]

    ind = calculate_indicators(df, int(params["ema_fast"]), int(params["ema_slow"]), 14)
    # IMPORTANT: use closed candles only. Last OHLCV candle can still be forming.
    if len(ind) < max(50, int(params["ema_slow"]) + 10):
        return "NEUTRALNY", {}
    prev = ind.iloc[-3]
    last = ind.iloc[-2]
    values = {
        "price": safe_float(last["close"]),
        "adx": safe_float(last["adx"]),
        "rsi": safe_float(last["rsi"], 50),
        "plus_di": safe_float(last["plus_di"]),
        "minus_di": safe_float(last["minus_di"]),
        "ema_fast": safe_float(last["ema_fast"]),
        "ema_slow": safe_float(last["ema_slow"]),
        "macd_hist": safe_float(last["macd_hist"]),
    }

    # Trend confirmation is deliberately stricter than the original code:
    # EMA alignment + DI direction + ADX + RSI + MACD direction + crossover.
    long_cross = prev["close"] <= prev["ema_fast"] and last["close"] > last["ema_fast"]
    short_cross = prev["close"] >= prev["ema_fast"] and last["close"] < last["ema_fast"]
    long_trend = (
        last["ema_fast"] > last["ema_slow"]
        and last["plus_di"] > last["minus_di"]
        and last["macd_hist"] > 0
    )
    short_trend = (
        last["ema_fast"] < last["ema_slow"]
        and last["minus_di"] > last["plus_di"]
        and last["macd_hist"] < 0
    )
    long_ok = long_cross and long_trend and values["adx"] >= params["min_adx"] and values["rsi"] < params["max_rsi"]
    short_ok = short_cross and short_trend and values["adx"] >= params["min_adx"] and values["rsi"] > params["min_rsi"]
    return ("LONG" if long_ok else "SHORT" if short_ok else "NEUTRALNY"), {**values, **params}


# ============================================================
# RISK / ORDERS
# ============================================================

def calculate_risk_allocation(free_balance: float, entry: float, stop_price: float, leverage: int, max_single: float, tf_multiplier: float) -> float:
    if free_balance <= 0 or entry <= 0 or stop_price <= 0:
        return 0.0
    risk_amount = free_balance * DEFAULT_RISK_PCT
    distance = abs(entry - stop_price) / entry
    distance = max(distance, 0.005)
    risk_notional = risk_amount / distance
    max_notional = min(free_balance * max(1, leverage) * 0.90, max_single * max(tf_multiplier, 0.1) * leverage)
    return max(0.0, min(risk_notional, max_notional))


def roe_to_price(entry: float, roe_percent: float, leverage: float, long: bool) -> float:
    # Approximate linear ROE relation used for local/exchange protection.
    # Fee/funding are not included; local ROE guard remains the final backstop.
    move = abs(float(roe_percent)) / max(float(leverage), 1.0) / 100.0
    return entry * (1.0 - move if long else 1.0 + move)


def create_protection_order(exchange, symbol: str, side: str, amount: float, trigger_price: float, kind: str) -> Optional[Dict[str, Any]]:
    """Try CCXT unified trigger syntax first. The worker also has a polling guard, so failure of a native trigger order does not silently leave a position unprotected. """
    try:
        params = {"reduceOnly": True, "triggerPrice": trigger_price}
        if kind == "stop":
            params["stopLossPrice"] = trigger_price
        else:
            params["takeProfitPrice"] = trigger_price
        return exchange.create_order(symbol, "market", side, amount, None, params)
    except Exception as exc:
        log.warning("Native %s protection failed for %s: %s", kind, symbol, exc)
        return None


def cancel_order_safe(exchange, order_id: str, symbol: str) -> None:
    if not order_id:
        return
    try:
        exchange.cancel_order(order_id, symbol)
    except Exception:
        pass


def place_entry_with_protection(exchange, symbol: str, signal: str, amount: float, leverage: int, stop_roe: float, take_roe: float) -> Tuple[Optional[Dict[str, Any]], Optional[float], Optional[float]]:
    side = "buy" if signal == "LONG" else "sell"
    try:
        order = exchange.create_order(symbol, "market", side, amount)
    except Exception as exc:
        log.error("ENTRY failed %s %s: %s", symbol, signal, exc)
        return None, None, None

    # Use the exchange-reported average/fill price, never the pre-entry ticker price.
    entry = safe_float(order.get("average")) or safe_float(order.get("price"))
    if entry <= 0:
        try:
            p = find_position(fetch_positions_safe(exchange), symbol)
            entry = safe_float(p.get("entryPrice")) if p else 0.0
        except Exception:
            entry = 0.0
    if entry <= 0:
        log.error("Could not determine real entry price for %s; local guard will use position entry when available", symbol)
        return order, None, None

    long = signal == "LONG"
    stop_price = roe_to_price(entry, stop_roe, leverage, long)
    take_price = roe_to_price(entry, take_roe, leverage, not long)
    close_side = "sell" if long else "buy"
    try:
        amount_prec = float(exchange.amount_to_precision(symbol, amount))
    except Exception:
        amount_prec = amount
    if amount_prec <= 0:
        return order, stop_price, take_price

    sl_order = create_protection_order(exchange, symbol, close_side, amount_prec, stop_price, "stop")
    tp_order = create_protection_order(exchange, symbol, close_side, amount_prec, take_price, "take")
    log.info("Entry %s %s avg=%s SL=%s TP=%s native_sl=%s native_tp=%s", symbol, signal, entry, stop_price, take_price,
             bool(sl_order), bool(tp_order))
    return order, stop_price, take_price


# ============================================================
# USER / WORKER CONFIG
# ============================================================

def get_all_trading_users() -> List[Dict[str, Any]]:
    conn = db_connect()
    try:
        rows = conn.execute(
            "SELECT id,email,api_key,secret_key,passphrase,selected_exchange,is_admin,stripe_paid FROM users WHERE api_key<>'' AND secret_key<>''"
        ).fetchall()
    finally:
        conn.close()
    result = []
    for r in rows:
        result.append({
            "id": int(r[0]), "email": r[1], "api_key": r[2] or "", "secret_key": r[3] or "",
            "passphrase": r[4] or "", "exchange": r[5] or "Bitget", "is_admin": bool(r[6]), "paid": bool(r[7]),
        })
    return result


def get_user_risk_settings(user_id: int) -> Dict[str, Any]:
    conn = db_connect()
    try:
        row = conn.execute("SELECT settings_json FROM users WHERE id=?", (int(user_id),)).fetchone()
    finally:
        conn.close()
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
        conn.execute("UPDATE users SET settings_json=? WHERE id=?", (json.dumps(settings), int(user_id)))
        conn.commit()
    finally:
        conn.close()


# ============================================================
# AUTONOMOUS TRADING WORKER
# ============================================================

class UserWorker:
    def __init__(self, user: Dict[str, Any]):
        self.user = user
        self.user_id = int(user["id"])
        self.exchange = get_exchange(user["api_key"], user["secret_key"], user["passphrase"], user["exchange"])
        self.cooldowns: Dict[str, float] = {}
        self.last_protection_check = 0.0
        self.last_scan = 0.0
        self.last_seen_bots: Dict[str, Any] = {}
        self.markets_loaded = False

    def refresh_credentials(self) -> None:
        users = [u for u in get_all_trading_users() if u["id"] == self.user_id]
        if users:
            self.user = users[0]

    def run_once(self) -> None:
        if self.exchange is None:
            return
        bots = load_active_bots(self.user_id)
        if not bots:
            return
        risk = get_user_risk_settings(self.user_id)
        try:
            if not self.markets_loaded:
                self.exchange.load_markets()
                self.markets_loaded = True
            tickers = self.exchange.fetch_tickers()
        except Exception as exc:
            log.warning("Market/ticker fetch failed for user %s: %s", self.user_id, exc)
            return

        # 1) Protection is checked BEFORE searching for new entries.
        self.protect_open_positions(bots, risk)

        positions = fetch_positions_safe(self.exchange)
        pos_map = {p.get("symbol"): p for p in positions if p.get("symbol") and position_contracts(p) > 0}
        active_count = len(pos_map)
        free_balance = self.fetch_free_balance()

        valid = []
        for symbol, ticker in tickers.items():
            try:
                market = self.exchange.market(symbol)
                qv = safe_float(ticker.get("quoteVolume"))
                if market.get("linear") and market.get("quote") == "USDT" and market.get("active") and qv >= MIN_QUOTE_VOLUME:
                    valid.append((symbol, qv))
            except Exception:
                continue
        valid.sort(key=lambda x: x[1], reverse=True)
        symbols = [s for s, _ in valid[:int(risk["max_scan_pairs"])]]

        # Only one fresh decision per symbol/timeframe per candle. The closed candle
        # is the signal source, avoiding repeated entries on every UI rerun.
        for tf, raw_cfg in list(bots.items()):
            cfg = dict(raw_cfg)
            cfg["tf"] = tf
            for symbol in symbols:
                if active_count >= int(risk["max_positions"]):
                    break
                if time.time() < self.cooldowns.get(symbol, 0):
                    continue
                if symbol in pos_map:
                    continue
                try:
                    limit = min(300, max(100, int(cfg.get("ema_slow", 21)) + 50))
                    ohlcv = self.exchange.fetch_ohlcv(symbol, tf, limit=limit)
                    if not ohlcv:
                        continue
                    df = pd.DataFrame(ohlcv, columns=["timestamp", "open", "high", "low", "close", "volume"])
                    signal, vals = signal_from_closed_candle(df, cfg, float(risk["auto_base_influence"]) / 100.0)
                    if signal == "NEUTRALNY":
                        continue

                    max_ex = exchange_max_leverage(self.exchange, symbol, int(risk["max_leverage"]))
                    if risk["leverage_mode"] == "Ręczny":
                        lev = min(int(risk["manual_leverage"]), max_ex)
                    else:
                        adx = safe_float(vals.get("adx"), 20)
                        ratio = min(1.0, max(0.0, (adx - 10.0) / 45.0))
                        lev = max(1, int(round(1 + ratio * (min(int(risk["max_leverage"]), max_ex) - 1))))
                    set_leverage_safe(self.exchange, symbol, lev)

                    ticker = tickers.get(symbol, {}) or {}
                    entry_hint = safe_float(ticker.get("last")) or safe_float(vals.get("price"))
                    if entry_hint <= 0:
                        continue
                    # Allocation uses a conservative initial stop distance corresponding to ROE/lev.
                    initial_stop = roe_to_price(entry_hint, float(risk["stop_roe"]), lev, signal == "LONG")
                    notional = calculate_risk_allocation(
                        free_balance, entry_hint, initial_stop, lev,
                        float(risk["max_single"]), float(vals.get("capital_multiplier", 1.0)),
                    )
                    if notional <= 0:
                        continue
                    amount = notional / entry_hint
                    min_amt, min_cost, _ = market_limits(self.exchange, symbol)
                    if min_amt and amount < min_amt:
                        amount = min_amt
                    if min_cost and amount * entry_hint < min_cost:
                        amount = min_cost / entry_hint
                    amount = float(self.exchange.amount_to_precision(symbol, amount))
                    if amount <= 0:
                        continue

                    order, sl_price, tp_price = place_entry_with_protection(
                        self.exchange, symbol, signal, amount, lev,
                        float(risk["stop_roe"]), float(risk["take_roe"]),
                    )
                    if order:
                        active_count += 1
                        # Refresh the position map immediately to prevent another TF from entering same symbol.
                        fresh = find_position(fetch_positions_safe(self.exchange), symbol)
                        self.cooldowns[symbol] = time.time() + 300
                        pos_map[symbol] = True
                        if fresh:
                                pos_map[symbol] = fresh

                        log_trade(self.user_id, symbol, tf, "ENTRY", signal, entry_hint, amount,
                                  str(order.get("id", "")), f"SL={sl_price};TP={tp_price}")
                except Exception as exc:
                    log.exception("Signal/order cycle failed user=%s tf=%s symbol=%s: %s", self.user_id, tf, symbol, exc)

    def fetch_free_balance(self) -> float:
        try:
            bal = self.exchange.fetch_balance({"type": "swap"})
            usdt = bal.get("USDT", {}) or {}
            free = safe_float(usdt.get("free"))
            if free > 0:
                return free
            total = safe_float(usdt.get("total"))
            used = safe_float(usdt.get("used"))
            return max(0.0, total - used)
        except Exception:
            return 0.0

    def protect_open_positions(self, bots: Dict[str, Any], risk: Dict[str, Any]) -> None:
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
            entry = safe_float(p.get("entryPrice"))
            if entry <= 0:
                continue
            mark = safe_float(p.get("markPrice")) or safe_float(p.get("lastPrice"))
            lev = safe_float(p.get("leverage"), 1.0)
            if mark <= 0:
                continue
            raw_move = ((mark - entry) / entry) * 100 if is_long(p) else ((entry - mark) / entry) * 100
            roe = raw_move * max(1.0, lev)
            if roe <= -float(risk["stop_roe"]):
                if close_position(self.exchange, p, f"ROE SL {roe:.2f}%"):
                    self.cooldowns[p.get("symbol", "")] = time.time() + float(risk["cooldown_minutes"]) * 60
                    log_trade(self.user_id, p.get("symbol", ""), "guard", "SL", position_side(p), mark, amount, message=f"ROE={roe:.2f}%")
            elif roe >= float(risk["take_roe"]):
                if close_position(self.exchange, p, f"ROE TP {roe:.2f}%"):
                    self.cooldowns[p.get("symbol", "")] = time.time() + float(risk["cooldown_minutes"]) * 60
                    log_trade(self.user_id, p.get("symbol", ""), "guard", "TP", position_side(p), mark, amount, message=f"ROE={roe:.2f}%")

    def loop(self, stop_event: threading.Event) -> None:
        log.info("Worker started for user %s (%s)", self.user_id, self.user.get("email"))
        while not stop_event.is_set():
            try:
                self.run_once()
            except Exception:
                log.exception("Worker top-level error for user %s", self.user_id)
            stop_event.wait(WORKER_POLL_SECONDS)
        log.info("Worker stopped for user %s", self.user_id)


class WorkerManager:
    def __init__(self):
        self.lock = threading.Lock()
        self.workers: Dict[int, Tuple[threading.Thread, threading.Event]] = {}

    def reconcile(self) -> None:
        users = {u["id"]: u for u in get_all_trading_users()}
        active_ids = {uid for uid in users if load_active_bots(uid)}
        with self.lock:
            for uid in active_ids:
                if uid in self.workers and self.workers[uid][0].is_alive():
                    continue
                worker = UserWorker(users[uid])
                event = threading.Event()
                thread = threading.Thread(target=worker.loop, args=(event,), daemon=True, name=f"bot-user-{uid}")
                self.workers[uid] = (thread, event)
                thread.start()
            for uid in list(self.workers):
                if uid not in active_ids:
                    self.workers[uid][1].set()
                    self.workers.pop(uid, None)

    def stop_all(self) -> None:
        with self.lock:
            for _, event in self.workers.values():
                event.set()
            self.workers.clear()


MANAGER = WorkerManager()


def run_worker_mode() -> None:
    init_db()
    log.info("Autonomous worker service started. Poll=%ss", WORKER_POLL_SECONDS)
    try:
        while True:
            MANAGER.reconcile()
            time.sleep(max(2, WORKER_POLL_SECONDS))
    except KeyboardInterrupt:
        MANAGER.stop_all()
        log.info("Worker service stopped")


# ============================================================
# STREAMLIT UI
# ============================================================

SESSION_DEFAULTS = {
    "logged_in": False, "user_email": "", "is_admin": False, "user_id": None, "stripe_paid": False,
    "session_start_time": datetime.now(), "lang": "Polski", "api_key": "", "secret_key": "", "passphrase": "",
    "selected_exchange": "Bitget", "session_start_balance": 0.0, "session_baseline_locked": False,
    "active_mtf_bots": {}, "_mtf_loaded_user_id": None,
}


def get_secret(name: str, default: str = "") -> str:
    value = os.getenv(name)
    if value:
        return value
    try:
        return st.secrets.get(name, default)
    except Exception:
        return default


def create_stripe_checkout_session(email: str, price_id: str) -> str:
    secret = get_secret("STRIPE_SECRET_KEY", STRIPE_SECRET_KEY)
    if stripe is None or not secret or not price_id:
        return STRIPE_CHECKOUT_FALLBACK
    try:
        stripe.api_key = secret
        session = stripe.checkout.Session.create(
            payment_method_types=["card"],
            line_items=[{"price": price_id, "quantity": 1}],
            mode="payment",
            success_url="https://bot-bitget.pl/?success=true",
            cancel_url="https://bot-bitget.pl/?success=false",
            customer_email=email,
        )
        return session.url if session and session.url else STRIPE_CHECKOUT_FALLBACK
    except Exception as exc:
        log.warning("Stripe checkout error: %s", exc)
        return STRIPE_CHECKOUT_FALLBACK


def apply_mtf_to_session(user_id: int) -> None:
    if st.session_state.get("_mtf_loaded_user_id") == int(user_id):
        return
    saved = load_mtf_settings(int(user_id))
    for tf in AVAILABLE_TIMEFRAMES:
        d = saved[tf]
        st.session_state[f"radio_mode_{tf}"] = d.get("mode", "Automatyczny")
        st.session_state[f"ema_f_{tf}"] = int(d.get("ema_fast", DEFAULT_TF_VALUES[tf]["ema_fast"]))
        st.session_state[f"ema_s_{tf}"] = int(d.get("ema_slow", DEFAULT_TF_VALUES[tf]["ema_slow"]))
        st.session_state[f"adx_{tf}"] = float(d.get("adx", DEFAULT_TF_VALUES[tf]["adx"]))
        st.session_state[f"max_rsi_{tf}"] = float(d.get("max_rsi", DEFAULT_TF_VALUES[tf]["max_rsi"]))
        st.session_state[f"min_rsi_{tf}"] = float(d.get("min_rsi", DEFAULT_TF_VALUES[tf]["min_rsi"]))
        st.session_state[f"cap_mult_{tf}"] = float(d.get("cap_mult", DEFAULT_TF_VALUES[tf]["cap_mult"]))
    st.session_state.active_mtf_bots = load_active_bots(int(user_id))
    st.session_state["_mtf_loaded_user_id"] = int(user_id)


def current_mtf_payload() -> Dict[str, Dict[str, Any]]:
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
    return payload


def is_user_admin() -> bool:
    return str(st.session_state.get("user_email", "")).strip().lower() in ADMIN_EMAILS or bool(st.session_state.get("is_admin"))


def is_user_paid() -> bool:
    return is_user_admin() or bool(st.session_state.get("stripe_paid"))


def ui_login() -> None:
    st.markdown("<div class='hero-wrapper'><div class='retro-ornate-frame'>", unsafe_allow_html=True)
    st.markdown(f"<div class='retro-vintage-title'>{t('title')}</div><div class='retro-subtitle'>{t('subtitle')}</div>", unsafe_allow_html=True)
    tab_login, tab_register = st.tabs([t("login_tab"), t("register_tab")])
    with tab_login:
        email = st.text_input(t("email_label"), key="log_email")
        password = st.text_input(t("pass_label"), type="password", key="log_pass")
        if st.button(t("login_btn"), use_container_width=True):
            conn = db_connect()
            row = conn.execute(
                "SELECT id,email,password,is_admin,stripe_paid,api_key,secret_key,passphrase,selected_exchange FROM users WHERE LOWER(TRIM(email))=?",
                (email.strip().lower(),),
            ).fetchone()
            conn.close()
            if row and verify_password(password, row[2]):
                st.session_state.logged_in = True
                st.session_state.user_id = row[0]
                st.session_state.user_email = row[1]
                st.session_state.is_admin = bool(row[3]) or row[1].strip().lower() in ADMIN_EMAILS
                st.session_state.stripe_paid = True if st.session_state.is_admin else bool(row[4])
                st.session_state.api_key = row[5] or ""
                st.session_state.secret_key = row[6] or ""
                st.session_state.passphrase = row[7] or ""
                st.session_state.selected_exchange = row[8] or "Bitget"
                apply_mtf_to_session(row[0])
                if not str(row[2]).startswith("sha256$"):
                    conn = db_connect()
                    conn.execute("UPDATE users SET password=? WHERE id=?", (hash_password(password), row[0]))
                    conn.commit(); conn.close()
                st.success(t("login_success")); st.rerun()
            else:
                st.error(t("login_error"))
    with tab_register:
        email = st.text_input(t("email_label"), key="reg_email")
        password = st.text_input(t("pass_label"), type="password", key="reg_pass")
        if st.button(t("register_btn"), use_container_width=True):
            if not email or not password:
                st.error(t("reg_error_fill"))
            else:
                try:
                    clean = email.strip().lower()
                    admin = 1 if clean in ADMIN_EMAILS else 0
                    conn = db_connect()
                    conn.execute("INSERT INTO users(email,password,is_admin,stripe_paid) VALUES(?,?,?,?)",
                                 (clean, hash_password(password), admin, admin))
                    conn.commit(); conn.close()
                    st.success(t("reg_success"))
                except sqlite3.IntegrityError:
                    st.error(t("reg_error_exists"))
    st.markdown("</div></div>", unsafe_allow_html=True)
    st.markdown("""<div style='margin-top:30px;padding:15px;border:1px solid #3d2f1f;text-align:center;color:#c5a059;font-size:11px'> Handel Futures wiąże się z wysokim ryzykiem utraty kapitału. Oprogramowanie działa w formule As-Is i nie gwarantuje zysku. </div>""", unsafe_allow_html=True)


def run_streamlit_app() -> None:
    st.set_page_config(page_title="Multi-Exchange Futures SaaS", layout="wide")
    init_db()
    for k, v in SESSION_DEFAULTS.items():
        if k not in st.session_state:
            st.session_state[k] = v

    st.markdown("""<style> :root{--bg:#080706;--panel:#11100e;--panel2:#171411;--gold:#d9ad4a;--gold2:#f3d57a;--gold3:#8d6a27;--green:#1fc56b;--green2:#0c6b3a;--red:#e05252;--muted:#9d9487;--text:#f5f0e6} .stApp{background:radial-gradient(circle at 50% -10%,#292015 0%,#0b0908 35%,#070605 100%);color:var(--text)} [data-testid="stHeader"]{background:rgba(0,0,0,0)} section[data-testid='stSidebar']{background:linear-gradient(180deg,#15120f,#0b0908);border-right:2px solid var(--gold3)} section[data-testid='stSidebar'] .stMarkdown,section[data-testid='stSidebar'] label{color:#eee5d5} .block-container{padding-top:1.2rem;max-width:1600px} h1,h2,h3{color:var(--gold2)!important;letter-spacing:.4px} .premium-shell{background:linear-gradient(145deg,rgba(30,25,19,.96),rgba(10,9,8,.98));border:1px solid var(--gold3);box-shadow:0 0 0 1px rgba(243,213,122,.10) inset,0 12px 40px rgba(0,0,0,.45);border-radius:18px;padding:18px;margin-bottom:18px} .hero-wrapper{padding:4px;margin-bottom:18px} .retro-ornate-frame{position:relative;text-align:center;padding:28px 24px;border:2px solid var(--gold);border-radius:18px;background:linear-gradient(135deg,#17120c,#090807 55%,#18120b);box-shadow:0 0 0 5px #0b0907,0 0 0 7px var(--gold3),0 16px 45px rgba(0,0,0,.55)} .retro-ornate-frame:before,.retro-ornate-frame:after{content:'◆';position:absolute;color:var(--gold2);font-size:18px;top:8px}.retro-ornate-frame:before{left:14px}.retro-ornate-frame:after{right:14px} .retro-vintage-title{font-size:clamp(26px,4vw,48px);font-weight:900;letter-spacing:4px;color:var(--gold2);text-shadow:0 2px 16px rgba(243,213,122,.18);text-transform:uppercase} .retro-subtitle{margin-top:7px;color:#d4c5aa;font-size:13px;letter-spacing:2px;text-transform:uppercase} .dashboard-banner{display:flex;align-items:center;justify-content:space-between;gap:12px;background:linear-gradient(90deg,#15110c,#21190e,#15110c);border:1px solid var(--gold3);border-radius:14px;padding:11px 16px;margin:0 0 14px} .dashboard-banner .brand{color:var(--gold2);font-weight:900;letter-spacing:1.5px}.dashboard-banner .user{color:#cfc4b0;font-size:13px} .metric-grid{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:12px;margin:8px 0 20px} .metric-card{min-height:118px;border:1px solid var(--gold);border-radius:14px;padding:15px 17px;background:linear-gradient(145deg,#1a1510,#0e0c0a);box-shadow:0 5px 18px rgba(0,0,0,.35),0 0 0 1px rgba(243,213,122,.08) inset} .metric-card.green{border-color:#27b968;background:linear-gradient(145deg,#10251a,#0a110d)} .metric-card.red{border-color:#b84b4b;background:linear-gradient(145deg,#261313,#100b0b)} .metric-label{font-size:12px;text-transform:uppercase;letter-spacing:1px;color:var(--gold2);font-weight:800}.metric-card.green .metric-label{color:#6ee49b}.metric-card.red .metric-label{color:#f08a8a} .metric-value{font-size:25px;line-height:1.15;font-weight:900;color:#fff;margin-top:8px}.metric-sub{font-size:12px;color:#a9a092;margin-top:8px} .section-card{border:1px solid #765b2c;border-radius:15px;padding:14px 16px;background:linear-gradient(145deg,rgba(22,18,13,.96),rgba(10,9,8,.96));margin:12px 0;box-shadow:0 7px 24px rgba(0,0,0,.28)} .section-title{display:flex;align-items:center;gap:8px;color:var(--gold2);font-weight:900;font-size:16px;letter-spacing:.8px;margin-bottom:10px} .status-pill{display:inline-block;padding:5px 10px;border-radius:999px;font-size:11px;font-weight:900;letter-spacing:.6px}.status-pill.on{background:rgba(31,197,107,.14);border:1px solid #22ad60;color:#58e893}.status-pill.off{background:rgba(224,82,82,.10);border:1px solid #913e3e;color:#f07d7d} .stButton>button{border:1px solid var(--gold3)!important;background:linear-gradient(180deg,#21190e,#100d09)!important;color:#f5e7c6!important;border-radius:9px!important;font-weight:800!important}.stButton>button:hover{border-color:var(--gold2)!important;box-shadow:0 0 14px rgba(243,213,122,.15)!important} .stDataFrame{border:1px solid #5e4926;border-radius:10px;overflow:hidden} .mtf-card{border:1px solid var(--gold3);border-radius:13px;background:linear-gradient(180deg,#17120d,#0d0b09);padding:10px;box-shadow:0 4px 15px rgba(0,0,0,.35);min-height:100%} .mtf-card.active{border-color:#25ba68;box-shadow:0 0 0 1px rgba(37,186,104,.18) inset,0 5px 18px rgba(0,0,0,.4)} .mtf-head{display:flex;justify-content:space-between;align-items:center;color:var(--gold2);font-weight:900;margin-bottom:8px} @media(max-width:1100px){.metric-grid{grid-template-columns:repeat(2,minmax(0,1fr))}} @media(max-width:650px){.metric-grid{grid-template-columns:1fr}.retro-vintage-title{letter-spacing:2px}.dashboard-banner{flex-direction:column;align-items:flex-start}} </style>""", unsafe_allow_html=True)

    if not st.session_state.logged_in:
        ui_login()
        st.stop()

    apply_mtf_to_session(st.session_state.user_id)

    st.session_state.lang = st.sidebar.selectbox("🌐 Język / Language", ["Polski", "English"],
                                                   index=0 if st.session_state.lang == "Polski" else 1,
                                                   key="lang_selector")
    st.sidebar.markdown(f"### 👤 {st.session_state.user_email}")
    st.sidebar.markdown(f"**{t('sidebar_role_admin') if is_user_admin() else t('sidebar_role_client')}**")
    if st.sidebar.button(t("logout_btn"), use_container_width=True):
        for k in ["logged_in","user_email","is_admin","user_id","stripe_paid","api_key","secret_key","passphrase"]:
            st.session_state[k] = SESSION_DEFAULTS[k]
        st.session_state.active_mtf_bots = {}
        st.session_state._mtf_loaded_user_id = None
        st.rerun()

    # Exchange/API
    st.sidebar.header(t("exchange_settings"))
    selected_exchange = st.sidebar.selectbox(t("select_exchange"), SUPPORTED_EXCHANGES,
                                              index=SUPPORTED_EXCHANGES.index(st.session_state.selected_exchange)
                                              if st.session_state.selected_exchange in SUPPORTED_EXCHANGES else 0,
                                              key="sidebar_selected_exchange")
    st.session_state.selected_exchange = selected_exchange
    api = st.sidebar.text_input(f"API Key ({selected_exchange})", value=st.session_state.api_key, type="password", key=f"api_{selected_exchange}")
    secret = st.sidebar.text_input(f"API Secret ({selected_exchange})", value=st.session_state.secret_key, type="password", key=f"secret_{selected_exchange}")
    passphrase = st.sidebar.text_input(f"Passphrase ({selected_exchange})", value=st.session_state.passphrase, type="password", key=f"pass_{selected_exchange}") if selected_exchange in {"Bitget","OKX"} else ""
    if st.sidebar.button(t("save_keys_btn"), use_container_width=True):
        if api and secret:
            st.session_state.api_key, st.session_state.secret_key, st.session_state.passphrase = api, secret, passphrase
            conn = db_connect(); conn.execute("UPDATE users SET api_key=?,secret_key=?,passphrase=?,selected_exchange=? WHERE id=?",
                                              (api, secret, passphrase, selected_exchange, st.session_state.user_id)); conn.commit(); conn.close()
            st.success(f"{t('keys_saved')} {selected_exchange}")
            st.rerun()
        else:
            st.error(t("keys_error"))

    # Subscription
    st.sidebar.markdown("---"); st.sidebar.markdown(f"### {t('sub_zone')}")
    st.sidebar.success(t("sub_active") if is_user_paid() else t("sub_inactive"))
    price_id = get_secret("STRIPE_PRICE_ID", STRIPE_PRICE_ID)
    st.sidebar.link_button(t("pay_btn"), create_stripe_checkout_session(st.session_state.user_email, price_id), use_container_width=True)
    if ALLOW_TEST_ACTIVATION and st.sidebar.button("⚡ [TEST] Aktywuj dostęp natychmiast"):
        conn = db_connect(); conn.execute("UPDATE users SET stripe_paid=1 WHERE id=?", (st.session_state.user_id,)); conn.commit(); conn.close()
        st.session_state.stripe_paid = True; st.rerun()

    # Risk settings are persisted in users.settings_json.
    saved_risk = get_user_risk_settings(st.session_state.user_id)
    st.sidebar.markdown("---"); st.sidebar.markdown(f"### {t('capital_risk')}")
    max_single = st.sidebar.number_input(t("max_single"), 5.0, 5000.0, float(saved_risk["max_single"]), 5.0, key="sb_max_single_trade")
    max_pos = st.sidebar.slider(t("max_pos"), 1, 20, int(saved_risk["max_positions"]), key="sb_max_active_pos")
    st.sidebar.markdown("---"); st.sidebar.markdown(f"### {t('roe_guard')}")
    enable_roe = st.sidebar.checkbox(t("enable_roe"), bool(saved_risk["enable_roe"]), key="enable_roe_guard")
    stop_roe = st.sidebar.slider(t("sl_roe"), 0.5, 50.0, float(saved_risk["stop_roe"]), 0.5, key="custom_stop_loss_roe") if enable_roe else 999.0
    take_roe = st.sidebar.slider(t("tp_roe"), 1.0, 100.0, float(saved_risk["take_roe"]), 0.5, key="custom_take_profit_roe") if enable_roe else 999.0
    cooldown = st.sidebar.slider("Czas oddechu po SL/TP (minuty)", 1, 120, int(saved_risk["cooldown_minutes"]), key="sb_cooldown_sl_tp")
    st.sidebar.markdown("---"); st.sidebar.markdown(f"### {t('leverage_mgmt')}")
    lev_mode = st.sidebar.radio(t("lev_mode"), ["Autonomiczny (płynny w granicach limitu)", "Ręczny"], index=0 if saved_risk["leverage_mode"] != "Ręczny" else 1, key="sb_leverage_mode")
    max_lev = st.sidebar.slider(t("max_allowed_lev"), 1, 50, int(saved_risk["max_leverage"]), key="sb_max_allowed_leverage")
    manual_lev = st.sidebar.slider(t("manual_lev"), 1, 50, int(saved_risk["manual_leverage"]), key="sb_manual_leverage")
    st.sidebar.markdown("---")
    max_scan = st.sidebar.slider(t("max_pairs"), 1, 100, int(saved_risk["max_scan_pairs"]), key="sb_max_fut_pairs")
    auto_influence = st.sidebar.slider("🎚️ Wpływ suwaków bazowych w trybie Auto (%)", 0, 100, int(saved_risk["auto_base_influence"]), 5, key="sb_auto_base_influence")
    refresh = st.sidebar.slider("Częstotliwość odświeżania widoku (sekundy)", 5, 60, 15, key="sb_auto_refresh")

    risk_now = {"max_single": max_single, "max_positions": max_pos, "enable_roe": enable_roe, "stop_roe": stop_roe,
                "take_roe": take_roe, "max_leverage": max_lev, "manual_leverage": manual_lev,
                "leverage_mode": lev_mode, "max_scan_pairs": max_scan, "auto_base_influence": auto_influence,
                "cooldown_minutes": cooldown}
    if risk_now != saved_risk:
        save_user_risk_settings(st.session_state.user_id, risk_now)

    # MTF UI
    st.markdown("<div class='section-card'><div class='section-title'>🤖 MTF — KONTROLA AUTONOMICZNYCH BOTÓW</div><div style='color:#9d9487;font-size:12px'>Każdy interwał działa niezależnie, a ustawienia są zapisywane w bazie użytkownika.</div></div>", unsafe_allow_html=True)
    cols = st.columns(len(AVAILABLE_TIMEFRAMES))
    for i, tf in enumerate(AVAILABLE_TIMEFRAMES):
        with cols[i]:
            active_tf = tf in st.session_state.active_mtf_bots
            st.markdown(f"<div class='mtf-card {'active' if active_tf else ''}'><div class='mtf-head'><span>⏱ {tf}</span><span class='status-pill {'on' if active_tf else 'off'}'>{'● AKTYWNY' if active_tf else '○ GOTOWY'}</span></div>", unsafe_allow_html=True)
            k_mode, k_f, k_s, k_adx, k_max, k_min, k_cap = [f"{p}_{tf}" for p in ["radio_mode","ema_f","ema_s","adx","max_rsi","min_rsi","cap_mult"]]
            mode = st.radio(f"Tryb ({tf})", ["Automatyczny","Ręczny"], key=k_mode)
            f = st.number_input(f"EMA Szybka ({tf})", 1, 200, key=k_f)
            s = st.number_input(f"EMA Wolna ({tf})", 2, 300, key=k_s)
            adx = st.slider(f"Min ADX ({tf})", 10.0, 50.0, key=k_adx)
            maxr = st.slider(f"Max RSI Long ({tf})", 50.0, 95.0, key=k_max)
            minr = st.slider(f"Min RSI Short ({tf})", 5.0, 50.0, key=k_min)
            cap = st.number_input(f"CAP x ({tf})", 0.1, 10.0, float(st.session_state.get(k_cap, DEFAULT_TF_VALUES[tf]["cap_mult"])), 0.1, key=k_cap)
            if f >= s: st.warning("EMA szybka musi być mniejsza od wolnej")
            cfg = {"mode": mode, "ema_fast": min(int(f), int(s)-1), "ema_slow": max(int(s), int(f)+1),
                   "min_adx": float(adx), "max_rsi": float(maxr), "min_rsi": float(minr), "capital_multiplier": float(cap), "tf": tf}
            if tf in st.session_state.active_mtf_bots:
                st.success("🟢 AKTYWNY")
                if st.button(f"Zatrzymaj {tf}", key=f"stop_{tf}", use_container_width=True):
                    st.session_state.active_mtf_bots.pop(tf, None)
                    save_active_bots(st.session_state.user_id, st.session_state.active_mtf_bots)
                    st.rerun()
            else:
                if st.button(f"Uruchom {tf}", key=f"start_{tf}", use_container_width=True):
                    if not st.session_state.api_key or not st.session_state.secret_key:
                        st.error("Najpierw zapisz klucze API w panelu bocznym.")
                    elif not is_user_paid():
                        st.error("Wymagana aktywna subskrypcja.")
                    else:
                        st.session_state.active_mtf_bots[tf] = cfg
                        save_active_bots(st.session_state.user_id, st.session_state.active_mtf_bots)
                        save_mtf_settings(st.session_state.user_id, current_mtf_payload())
                        MANAGER.reconcile()
                        st.rerun()
            st.markdown("</div>", unsafe_allow_html=True)

    # Always persist the MTF sliders after widget values are resolved.
    save_mtf_settings(st.session_state.user_id, current_mtf_payload())

    # Worker mode inside Streamlit process is optional; the recommended Hetzner setup is
    # the separate --worker service. This reconciliation also lets a running UI recover
    # the worker without tying trading logic to browser reruns.
    MANAGER.reconcile()

    # Kill switch
    if st.sidebar.button(t("kill_switch"), type="primary", use_container_width=True):
        ex = get_exchange(st.session_state.api_key, st.session_state.secret_key, st.session_state.passphrase, st.session_state.selected_exchange)
        if ex:
            for p in fetch_positions_safe(ex):
                close_position(ex, p, "KILL SWITCH")
        st.session_state.active_mtf_bots = {}
        save_active_bots(st.session_state.user_id, {})
        MANAGER.reconcile()
        st.success("🔴 KILL SWITCH WYKONANY. Wszystkie pozycje zamknięte, boty zatrzymane.")
        st.rerun()

    # Live dashboard
    st.markdown("<div class='dashboard-banner'><span class='brand'>💠 FUTURES CONTROL CENTER</span><span class='user'>👤 " + str(st.session_state.user_email) + " · " + str(st.session_state.selected_exchange) + "</span></div>", unsafe_allow_html=True)
    ex = get_exchange(st.session_state.api_key, st.session_state.secret_key, st.session_state.passphrase, st.session_state.selected_exchange)
    positions = fetch_positions_safe(ex) if ex else []
    positions = [p for p in positions if position_contracts(p) > 0]
    total_unreal = sum(safe_float(p.get("unrealizedPnl")) for p in positions)
    balance = 0.0; free = 0.0
    if ex:
        try:
            bal = ex.fetch_balance({"type":"swap"}); u = bal.get("USDT",{}) or {}; balance = safe_float(u.get("total")); free = safe_float(u.get("free"))
        except Exception: pass
    if not st.session_state.session_baseline_locked and balance > 0:
        st.session_state.session_start_balance = balance; st.session_state.session_baseline_locked = True
    pnl_pct = ((balance - st.session_state.session_start_balance) / st.session_state.session_start_balance * 100) if st.session_state.session_start_balance > 0 else 0.0
    elapsed = max(0, int((datetime.now() - st.session_state.session_start_time).total_seconds())); h, rem = divmod(elapsed,3600); m,sx = divmod(rem,60)
    pnl_cls = "green" if pnl_pct >= 0 else "red"
    active_cls = "green" if st.session_state.active_mtf_bots else ""
    st.markdown(f"""<div class='metric-grid'> <div class='metric-card'><div class='metric-label'>💰 {t('wallet_futures')}</div><div class='metric-value'>{balance:.2f} USDT</div><div class='metric-sub'>{t('free_balance')}: <b>{free:.2f} USDT</b></div></div> <div class='metric-card {pnl_cls}'><div class='metric-label'>📈 {t('session_results')}</div><div class='metric-value'>{pnl_pct:+.2f}%</div><div class='metric-sub'>{t('pnl_usdt')}: <b>{total_unreal:+.2f} USDT</b></div></div> <div class='metric-card'><div class='metric-label'>🎯 {t('slots_futures')}</div><div class='metric-value'>{len(positions)} / {max_pos}</div><div class='metric-sub'>Wolne sloty: <b>{max(0,max_pos-len(positions))}</b></div></div> <div class='metric-card {active_cls}'><div class='metric-label'>⚡ {t('session_time')}</div><div class='metric-value'>{h:02d}:{m:02d}:{sx:02d}</div><div class='metric-sub'>Aktywne boty: <b>{len(st.session_state.active_mtf_bots)}</b></div></div> </div>""", unsafe_allow_html=True)

    st.markdown(f"<div class='section-card'><div class='section-title'>📊 {t('active_positions')}</div>", unsafe_allow_html=True)
    if positions: st.dataframe(pd.DataFrame(positions), use_container_width=True)
    else: st.info(t("no_positions"))
    st.markdown("</div>", unsafe_allow_html=True)

    st.markdown(f"<div class='section-card'><div class='section-title'>📜 {t('trade_history')}</div>", unsafe_allow_html=True)
    conn = db_connect()
    try:
        hist = pd.read_sql_query("SELECT created_at,symbol,timeframe,action,side,price,amount,order_id,message FROM trade_log WHERE user_id=? ORDER BY id DESC LIMIT 100", conn, params=(st.session_state.user_id,))
    except Exception:
        hist = pd.DataFrame()
    finally:
        conn.close()
    if not hist.empty: st.dataframe(hist, use_container_width=True)
    else: st.info(t("no_history"))
    st.markdown("</div>", unsafe_allow_html=True)

    st.markdown(f"<div class='section-card'><div class='section-title'>🔎 {t('market_scanner_results')}</div>", unsafe_allow_html=True)
    scanner = []
    if ex and st.session_state.active_mtf_bots:
        try:
            ex.load_markets(); tickers = ex.fetch_tickers()
            # IMPORTANT: max_scan is the user's requested scan universe.
            # Never truncate the visible scanner to 20 pairs.
            ranked = sorted(
                [
                    (sym, safe_float(t.get("quoteVolume")))
                    for sym, t in tickers.items()
                    if sym in ex.markets
                    and ex.markets[sym].get("linear")
                    and ex.markets[sym].get("quote") == "USDT"
                    and ex.markets[sym].get("active", True)
                    and safe_float(t.get("quoteVolume")) >= MIN_QUOTE_VOLUME
                ],
                key=lambda x: x[1],
                reverse=True,
            )[:max_scan]

            for tf, cfg in st.session_state.active_mtf_bots.items():
                for sym, qv in ranked:
                    row = {
                        "Interwał": tf,
                        "Para": sym,
                        "Wolumen 24h": qv,
                        "Cena": None,
                        "EMA Trend": "—",
                        "DI Trend": "—",
                        "ADX": None,
                        "RSI": None,
                        "Sygnał": "SKANOWANIE",
                        "Decyzja": "OCZEKUJE",
                    }
                    try:
                        data = ex.fetch_ohlcv(
                            sym,
                            tf,
                            limit=min(200, max(100, int(cfg.get("ema_slow", 21)) + 50)),
                        )
                        if not data:
                            row["Sygnał"] = "BRAK DANYCH"
                            row["Decyzja"] = "POMINIĘTO"
                            scanner.append(row)
                            continue

                        df = pd.DataFrame(
                            data,
                            columns=["timestamp", "open", "high", "low", "close", "volume"],
                        )
                        sig, vals = signal_from_closed_candle(
                            df,
                            {**cfg, "tf": tf},
                            auto_influence / 100.0,
                        )

                        ema_fast = safe_float(vals.get("ema_fast"))
                        ema_slow = safe_float(vals.get("ema_slow"))
                        plus_di = safe_float(vals.get("plus_di"))
                        minus_di = safe_float(vals.get("minus_di"))

                        if ema_fast > ema_slow:
                            ema_trend = "🟢 WZROSTOWY"
                        elif ema_fast < ema_slow:
                            ema_trend = "🔴 SPADKOWY"
                        else:
                            ema_trend = "⚪ BOCZNY"

                        if plus_di > minus_di:
                            di_trend = "🟢 LONG"
                        elif minus_di > plus_di:
                            di_trend = "🔴 SHORT"
                        else:
                            di_trend = "⚪ NEUTRALNY"

                        row.update({
                            "Cena": vals.get("price"),
                            "EMA Trend": ema_trend,
                            "DI Trend": di_trend,
                            "ADX": round(safe_float(vals.get("adx")), 2),
                            "RSI": round(safe_float(vals.get("rsi")), 2),
                            "Sygnał": sig,
                            "Decyzja": (
                                "🟢 WEJŚCIE LONG"
                                if sig == "LONG"
                                else "🔴 WEJŚCIE SHORT"
                                if sig == "SHORT"
                                else "⚪ BRAK WEJŚCIA"
                            ),
                        })
                    except Exception as exc:
                        row["Sygnał"] = "BŁĄD"
                        row["Decyzja"] = f"⚠️ {type(exc).__name__}"
                    scanner.append(row)
        except Exception: pass
    if scanner: st.dataframe(pd.DataFrame(scanner), use_container_width=True)
    else: st.info(t("no_scanner"))
    st.markdown("</div>", unsafe_allow_html=True)

    gc.collect()
    time.sleep(30)
    st.rerun()


# ============================================================
# ENTRY POINT
# ============================================================

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--worker", action="store_true", help="Uruchom autonomiczny silnik tradingowy bez Streamlit")
    args, _ = parser.parse_known_args()
    if args.worker:
        run_worker_mode()
    else:
        run_streamlit_app()

from __future__ import annotations

import argparse
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
# CONFIG
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
    "STRIPE_CHECKOUT_FALLBACK", "https://buy.stripe.com/8x2dRa4CbdaXfSAf6V3oA03"
)
if stripe is not None and STRIPE_SECRET_KEY:
    stripe.api_key = STRIPE_SECRET_KEY

DEFAULT_STOP_ROE = 4.0
DEFAULT_TAKE_ROE = 15.0
DEFAULT_RISK_PCT = 0.01
DEFAULT_MAX_SINGLE = 50.0
DEFAULT_MAX_POSITIONS = 5
DEFAULT_MAX_LEVERAGE = 15
DEFAULT_MANUAL_LEVERAGE = 5
DEFAULT_MAX_SCAN_PAIRS = 30
MIN_QUOTE_VOLUME = 1_000_000.0
WORKER_POLL_SECONDS = max(2, int(os.getenv("BOT_POLL_SECONDS", "5")))
POSITION_GUARD_SECONDS = max(1, int(os.getenv("POSITION_GUARD_SECONDS", "3")))
TF_SECONDS = {"1m": 60, "5m": 300, "15m": 900, "30m": 1800, "1h": 3600, "4h": 14400, "1d": 86400}

logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO").upper(),
    format="%(asctime)s | %(levelname)s | %(threadName)s | %(message)s",
    handlers=[logging.StreamHandler(), logging.FileHandler(LOG_FILE, encoding="utf-8")],
)
log = logging.getLogger("futures_saas")

# ============================================================
# HELPERS
# ============================================================
def safe_float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None:
            return default
        x = float(value)
        return default if not np.isfinite(x) else x
    except Exception:
        return default


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def normalize_symbol(symbol: str) -> str:
    return str(symbol or "").strip()


def is_valid_usdt_linear_market(market: Dict[str, Any]) -> bool:
    return bool(
        market
        and market.get("active", True)
        and market.get("linear") is True
        and str(market.get("quote", "")).upper() == "USDT"
        and market.get("contract") is True
    )


def fetch_tickers_safe(exchange, symbols: Optional[List[str]] = None) -> Dict[str, Dict[str, Any]]:
    """Fetch tickers with bulk->per-symbol fallback. Never silently return an empty scan."""
    if exchange is None:
        return {}
    try:
        data = exchange.fetch_tickers(symbols) if symbols else exchange.fetch_tickers()
        if isinstance(data, dict) and data:
            return data
    except Exception as exc:
        log.warning("fetch_tickers failed (bulk): %s", exc)
    result: Dict[str, Dict[str, Any]] = {}
    if symbols is None:
        try:
            symbols = list(exchange.markets.keys())
        except Exception:
            symbols = []
    for symbol in symbols:
        try:
            ticker = exchange.fetch_ticker(symbol)
            if ticker:
                result[symbol] = ticker
        except Exception as exc:
            log.debug("fetch_ticker failed %s: %s", symbol, exc)
    return result


def rank_usdt_linear_symbols(exchange, max_pairs: int) -> List[Tuple[str, float]]:
    """Return liquid USDT perpetuals ordered strictly by 24h quote volume."""
    if exchange is None:
        return []
    try:
        markets = exchange.load_markets()
    except Exception as exc:
        log.warning("load_markets failed during ranking: %s", exc)
        return []
    candidates = [symbol for symbol, market in markets.items() if is_valid_usdt_linear_market(market)]
    if not candidates:
        return []
    tickers = fetch_tickers_safe(exchange, candidates)
    ranked: List[Tuple[str, float]] = []
    for symbol in candidates:
        ticker = tickers.get(symbol) or {}
        qv = safe_float(ticker.get("quoteVolume"))
        if qv >= MIN_QUOTE_VOLUME:
            ranked.append((symbol, qv))
    ranked.sort(key=lambda item: item[1], reverse=True)
    return ranked[:max(1, int(max_pairs))]

# ============================================================
# TRANSLATIONS
# ============================================================
TRANSLATIONS = {
    "Polski": {
        "title": "BITGET FUTURES", "subtitle": "AUTONOMICZNY SYSTEM TRANSAKCYJNY",
        "login_tab": "🔑 Zaloguj się", "register_tab": "📝 Załóż konto",
        "email_label": "Adres e-mail", "pass_label": "Hasło", "login_btn": "ZALOGUJ SIĘ",
        "register_btn": "ZAREJESTRUJ SIĘ", "login_success": "Zalogowano pomyślnie!",
        "login_error": "Nieprawidłowy e-mail lub hasło.", "reg_success": "Konto założone! Przejdź do zakładki logowania.",
        "reg_error_exists": "Ten e-mail jest już zarejestrowany.", "reg_error_fill": "Wypełnij wszystkie pola.",
        "sidebar_role_admin": "Rola: Administrator", "sidebar_role_client": "Rola: Klient SaaS",
        "logout_btn": "🚪 WYLOGUJ SIĘ", "exchange_settings": "⚙️ Ustawienia Giełdy & API",
        "select_exchange": "Wybierz Giełdę:", "api_keys_header": "Klucze API", "save_keys_btn": "💾 ZAPISZ MOJE KLUCZE",
        "keys_saved": "Zapisano klucze dla", "keys_error": "Wypełnij wymagane pola kluczy.",
        "sub_zone": "🛡 Strefa Subskrypcji", "sub_active": "Subskrypcja aktywna (Dostęp Pełny)",
        "sub_inactive": "⚠️ Brak aktywnej subskrypcji", "pay_btn": "OPŁAĆ DOSTĘP (49 PLN)",
        "capital_risk": "💰 Kapitał i Ryzyko", "max_single": "Maksymalnie USDT na 1 pozycję (Bazowo)",
        "max_pos": "Maks. aktywne pozycje Futures", "roe_guard": "🛑 Zarządzanie Ryzykiem ROE (SL / TP)",
        "enable_roe": "Włącz strażnika SL / TP ROE", "sl_roe": "Stop-Loss ROE (%)", "tp_roe": "Take-Profit ROE (%)",
        "leverage_mgmt": "⚡ Zarządzanie Dźwignią", "lev_mode": "Tryb Dźwigni",
        "max_allowed_lev": "Maksymalna dozwolona dźwignia", "manual_lev": "Stała dźwignia Futures",
        "bot_control": "🤖 Panel Sterowania Botami MTF", "max_pairs": "Liczba par Futures do skanowania",
        "kill_switch": "🔴 ZAMKNIJ WSZYSTKO (KILL SWITCH)", "wallet_futures": "🔵 Portfel Futures",
        "free_balance": "Wolne", "session_results": "📊 Wyniki Sesji (PnL %)", "pnl_usdt": "PnL USDT",
        "slots_futures": "📈 Sloty Futures", "active_max": "Aktywne / Maksymalne", "session_time": "⏱ Czas Sesji",
        "market_scanner_results": "📊 Wyniki Skanera Rynkowego", "active_positions": "📈 Aktywne Pozycje Futures",
        "trade_history": "📜 Historia Ostatnich Transakcji", "admin_panel": "👑 Panel Administratora (Użytkownicy)",
        "no_positions": "Brak otwartych pozycji futures.", "no_history": "Brak zarejestrowanych transakcji w tej sesji.",
        "no_scanner": "Brak aktywnych botów MTF lub wyników skanowania.",
    },
    "English": {
        "title": "BITGET FUTURES", "subtitle": "AUTONOMOUS TRADING SYSTEM", "login_tab": "🔑 Login", "register_tab": "📝 Register",
        "email_label": "Email address", "pass_label": "Password", "login_btn": "SIGN IN", "register_btn": "SIGN UP",
        "login_success": "Logged in successfully!", "login_error": "Invalid email or password.", "reg_success": "Account created! Go to the login tab.",
        "reg_error_exists": "This email is already registered.", "reg_error_fill": "Please fill in all fields.",
        "sidebar_role_admin": "Role: Administrator", "sidebar_role_client": "Role: SaaS Client", "logout_btn": "🚪 LOG OUT",
        "exchange_settings": "⚙️ Exchange & API Settings", "select_exchange": "Select Exchange:", "api_keys_header": "API Keys",
        "save_keys_btn": "💾 SAVE MY KEYS", "keys_saved": "Keys saved for", "keys_error": "Please fill in required key fields.",
        "sub_zone": "🛡️ Subscription Zone", "sub_active": "Subscription active (Full Access)", "sub_inactive": "⚠️ No active subscription",
        "pay_btn": "PAY ACCESS (49 PLN)", "capital_risk": "💰 Capital & Risk", "max_single": "Max USDT per position (Base)",
        "max_pos": "Max active Futures positions", "roe_guard": "🛑 ROE Risk Management (SL / TP)", "enable_roe": "Enable SL / TP ROE guard",
        "sl_roe": "Stop-Loss ROE (%)", "tp_roe": "Take-Profit ROE (%)", "leverage_mgmt": "⚡ Leverage Management", "lev_mode": "Leverage Mode",
        "max_allowed_lev": "Maximum allowed leverage", "manual_lev": "Fixed Futures leverage", "bot_control": "🤖 Multi-Timeframe Bot Control Panel",
        "max_pairs": "Number of Futures pairs to scan", "kill_switch": "🔴 CLOSE ALL (KILL SWITCH)", "wallet_futures": "🔵 Futures Wallet",
        "free_balance": "Free", "session_results": "📊 Session Results (PnL %)", "pnl_usdt": "PnL USDT", "slots_futures": "📈 Futures Slots",
        "active_max": "Active / Maximum", "session_time": "⏱ Session Time", "market_scanner_results": "📊 Market Scanner Results",
        "active_positions": "📈 Active Futures Positions", "trade_history": "📜 Recent Trade History", "admin_panel": "👑 Admin Panel (Users)",
        "no_positions": "No open futures positions.", "no_history": "No recorded trades in this session.", "no_scanner": "No active MTF bots or scanner results.",
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
        conn.execute("""CREATE TABLE IF NOT EXISTS users ( id INTEGER PRIMARY KEY AUTOINCREMENT, email TEXT UNIQUE, password TEXT, is_admin INTEGER DEFAULT 0, stripe_paid INTEGER DEFAULT 0, api_key TEXT DEFAULT '', secret_key TEXT DEFAULT '', passphrase TEXT DEFAULT '', selected_exchange TEXT DEFAULT 'Bitget', settings_json TEXT DEFAULT '{}' )""")
        conn.execute("""CREATE TABLE IF NOT EXISTS user_mtf_settings ( user_id INTEGER PRIMARY KEY, settings_json TEXT NOT NULL, updated_at TEXT NOT NULL, FOREIGN KEY(user_id) REFERENCES users(id) )""")
        conn.execute("""CREATE TABLE IF NOT EXISTS user_bot_state ( user_id INTEGER PRIMARY KEY, active_bots_json TEXT NOT NULL DEFAULT '{}', updated_at TEXT NOT NULL, FOREIGN KEY(user_id) REFERENCES users(id) )""")
        conn.execute("""CREATE TABLE IF NOT EXISTS trade_log ( id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL, created_at TEXT NOT NULL, symbol TEXT, timeframe TEXT, action TEXT, side TEXT, price REAL, amount REAL, order_id TEXT, message TEXT, FOREIGN KEY(user_id) REFERENCES users(id) )""")
        conn.execute("""CREATE TABLE IF NOT EXISTS entry_guard ( user_id INTEGER NOT NULL, symbol TEXT NOT NULL, locked_until REAL NOT NULL DEFAULT 0, last_candle INTEGER NOT NULL DEFAULT 0, last_side TEXT DEFAULT '', updated_at TEXT NOT NULL, PRIMARY KEY(user_id, symbol), FOREIGN KEY(user_id) REFERENCES users(id) )""")
        cols = {r[1] for r in conn.execute("PRAGMA table_info(users)").fetchall()}
        for name, typ in [("selected_exchange", "TEXT DEFAULT 'Bitget'"), ("settings_json", "TEXT DEFAULT '{}'")]:
            if name not in cols:
                conn.execute(f"ALTER TABLE users ADD COLUMN {name} {typ}")
        for adm in ADMIN_EMAILS:
            conn.execute("UPDATE users SET is_admin=1, stripe_paid=1 WHERE LOWER(TRIM(email))=?", (adm.lower(),))
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
        row = conn.execute("SELECT settings_json FROM user_mtf_settings WHERE user_id=?", (int(user_id),)).fetchone()
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
            log.exception("Invalid MTF JSON for user %s", user_id)
    return payload


def save_mtf_settings(user_id: int, payload: Dict[str, Dict[str, Any]]) -> None:
    conn = db_connect()
    try:
        conn.execute("""INSERT INTO user_mtf_settings(user_id,settings_json,updated_at) VALUES(?,?,?) ON CONFLICT(user_id) DO UPDATE SET settings_json=excluded.settings_json,updated_at=excluded.updated_at""",
                     (int(user_id), json.dumps(payload, ensure_ascii=False), utc_now()))
        conn.commit()
    finally:
        conn.close()


def load_active_bots(user_id: int) -> Dict[str, Dict[str, Any]]:
    conn = db_connect()
    try:
        row = conn.execute("SELECT active_bots_json FROM user_bot_state WHERE user_id=?", (int(user_id),)).fetchone()
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
        conn.execute("""INSERT INTO user_bot_state(user_id,active_bots_json,updated_at) VALUES(?,?,?) ON CONFLICT(user_id) DO UPDATE SET active_bots_json=excluded.active_bots_json,updated_at=excluded.updated_at""",
                     (int(user_id), json.dumps(bots, ensure_ascii=False), utc_now()))
        conn.commit()
    finally:
        conn.close()


def get_entry_guard(user_id: int, symbol: str) -> Dict[str, Any]:
    conn = db_connect()
    try:
        row = conn.execute("SELECT locked_until,last_candle,last_side FROM entry_guard WHERE user_id=? AND symbol=?",
                           (int(user_id), symbol)).fetchone()
    finally:
        conn.close()
    if not row:
        return {"locked_until": 0.0, "last_candle": 0, "last_side": ""}
    return {"locked_until": safe_float(row[0]), "last_candle": int(row[1] or 0), "last_side": str(row[2] or "")}


def set_entry_guard(user_id: int, symbol: str, locked_until: float, last_candle: int = 0, last_side: str = "") -> None:
    conn = db_connect()
    try:
        conn.execute("""INSERT INTO entry_guard(user_id,symbol,locked_until,last_candle,last_side,updated_at) VALUES(?,?,?,?,?,?) ON CONFLICT(user_id,symbol) DO UPDATE SET locked_until=excluded.locked_until, last_candle=excluded.last_candle,last_side=excluded.last_side,updated_at=excluded.updated_at""",
                     (int(user_id), symbol, float(locked_until), int(last_candle or 0), str(last_side or ""), utc_now()))
        conn.commit()
    finally:
        conn.close()


def entry_guard_blocks(user_id: int, symbol: str, candle_ts: int = 0) -> bool:
    guard = get_entry_guard(user_id, symbol)
    if guard["locked_until"] > time.time():
        return True
    return bool(candle_ts and guard["last_candle"] == int(candle_ts))


def log_trade(user_id: int, symbol: str, tf: str, action: str, side: str, price: float = 0.0, amount: float = 0.0, order_id: str = "", message: str = "") -> None:
    conn = db_connect()
    try:
        conn.execute("""INSERT INTO trade_log(user_id,created_at,symbol,timeframe,action,side,price,amount,order_id,message) VALUES(?,?,?,?,?,?,?,?,?,?)""", (user_id, utc_now(), symbol, tf, action, side, price, amount, order_id, message))
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
        ex_id = name.lower()
        cls = getattr(ccxt, ex_id)
        config: Dict[str, Any] = {
            "apiKey": api_key,
            "secret": secret,
            "enableRateLimit": True,
            "timeout": 30000,
            "options": {"defaultType": "swap"},
        }
        if ex_id == "bitget":
            config["password"] = passphrase
            config["options"].update({"defaultSubType": "USDT-FUTURES"})
        elif ex_id == "okx" and passphrase:
            config["password"] = passphrase
        return cls(config)
    except Exception as exc:
        log.error("Exchange init failed for %s: %s", name, exc)
        return None


def fetch_usdt_balance(exchange) -> Dict[str, float]:
    result = {"total": 0.0, "used": 0.0, "free": 0.0}
    if exchange is None:
        return result
    try:
        bal = exchange.fetch_balance({"type": "swap"})
        u = bal.get("USDT", {}) or {}
        def val(name: str) -> float:
            x = safe_float(u.get(name))
            if x != 0:
                return x
            top = bal.get(name, {}) or {}
            return safe_float(top.get("USDT")) if isinstance(top, dict) else 0.0
        total, free, used = val("total"), val("free"), val("used")
        if total <= 0 and free > 0:
            total = free + max(0.0, used)
        if used <= 0 and total > 0 and total >= free:
            used = total - free
        if free <= 0 and total > 0 and total >= used:
            free = total - used
        result = {"total": max(0, total), "used": max(0, used), "free": max(0, free)}
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
    symbol, amount = p.get("symbol"), position_contracts(p)
    if not symbol or amount <= 0:
        return False
    try:
        amount = float(exchange.amount_to_precision(symbol, amount))
        if amount <= 0:
            return False
        exchange.create_order(symbol, "market", close_side_for_position(p), amount, None, reduce_only_params(exchange))
        log.info("Closed %s %s amount=%s reason=%s", symbol, position_side(p), amount, reason)
        return True
    except Exception as exc:
        log.error("Close position failed %s: %s", symbol, exc)
        return False


def market_limits(exchange, symbol: str) -> Tuple[float, float, float]:
    market = exchange.market(symbol)
    limits = market.get("limits") or {}
    amount_min = safe_float((limits.get("amount") or {}).get("min"))
    cost_min = safe_float((limits.get("cost") or {}).get("min"))
    max_lev = safe_float((limits.get("leverage") or {}).get("max"))
    return amount_min, cost_min, max_lev


def exchange_max_leverage(exchange, symbol: str, fallback: int = 15) -> int:
    try:
        _, _, max_lev = market_limits(exchange, symbol)
        return max(1, int(max_lev)) if max_lev > 0 else fallback
    except Exception:
        return fallback


def set_leverage_safe(exchange, symbol: str, leverage: int) -> None:
    try:
        exchange.set_leverage(int(leverage), symbol)
    except Exception as exc:
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
    tr = pd.concat([(df["high"] - df["low"]).abs(), (df["high"] - prev_close).abs(), (df["low"] - prev_close).abs()], axis=1).max(axis=1)
    up, down = df["high"].diff(), -df["low"].diff()
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
            return {"ema_fast": 5 if vol > .02 else 9, "ema_slow": 13 if vol > .02 else 21, "min_adx": 22 if vol > .02 else 26, "max_rsi": 72 if vol > .02 else 75, "min_rsi": 28 if vol > .02 else 25, "capital_multiplier": .6 if vol > .02 else .8}
        if tf in {"15m", "30m"}:
            return {"ema_fast": 7 if vol > .03 else 10, "ema_slow": 18 if vol > .03 else 25, "min_adx": 24 if vol > .03 else 25, "max_rsi": 70 if vol > .03 else 78, "min_rsi": 30 if vol > .03 else 22, "capital_multiplier": 1.0 if vol > .03 else 1.2}
        return {"ema_fast": 12, "ema_slow": 26, "min_adx": 20, "max_rsi": 80, "min_rsi": 20, "capital_multiplier": 2.5}
    except Exception:
        return {"ema_fast": 9, "ema_slow": 21, "min_adx": 25, "max_rsi": 75, "min_rsi": 25, "capital_multiplier": 1.0}


def blend_params(base: Dict[str, Any], opt: Dict[str, Any], base_weight: float = .5) -> Dict[str, Any]:
    w = max(0, min(1, float(base_weight)))
    return {
        "ema_fast": max(1, int(round(base["ema_fast"] * w + opt["ema_fast"] * (1-w)))),
        "ema_slow": max(2, int(round(base["ema_slow"] * w + opt["ema_slow"] * (1-w)))),
        "min_adx": base["min_adx"] * w + opt["min_adx"] * (1-w),
        "max_rsi": base["max_rsi"] * w + opt["max_rsi"] * (1-w),
        "min_rsi": base["min_rsi"] * w + opt["min_rsi"] * (1-w),
        "capital_multiplier": base["capital_multiplier"] * w + opt["capital_multiplier"] * (1-w),
    }


def signal_from_closed_candle(df: pd.DataFrame, cfg: Dict[str, Any], auto_base_influence: float = .5) -> Tuple[str, Dict[str, float]]:
    fast, slow = int(cfg.get("ema_fast", 9)), int(cfg.get("ema_slow", 21))
    if fast >= slow:
        fast = max(1, slow - 1)
    params = {
        "ema_fast": fast,
        "ema_slow": slow,
        "min_adx": float(cfg.get("min_adx", cfg.get("adx", 28))),
        "max_rsi": float(cfg.get("max_rsi", 75)),
        "min_rsi": float(cfg.get("min_rsi", 25)),
        "capital_multiplier": float(cfg.get("capital_multiplier", cfg.get("cap_mult", 1.0))),
    }
    if cfg.get("mode") == "Automatyczny":
        params = blend_params(params, get_dynamic_parameters(df, cfg.get("tf", "15m")), auto_base_influence)
    if params["ema_fast"] >= params["ema_slow"]:
        params["ema_fast"] = max(1, params["ema_slow"] - 1)

    ind = calculate_indicators(df, int(params["ema_fast"]), int(params["ema_slow"]), 14)
    if len(ind) < max(60, int(params["ema_slow"]) + 20):
        return "NEUTRALNY", {}

    # Always evaluate the last CLOSED candle. Trading is trend-following rather than
    # waiting for a single EMA crossover, which previously made entries extremely rare.
    last = ind.iloc[-2]
    prev = ind.iloc[-3]
    values = {
        "price": safe_float(last["close"]),
        "adx": safe_float(last["adx"]),
        "rsi": safe_float(last["rsi"], 50),
        "plus_di": safe_float(last["plus_di"]),
        "minus_di": safe_float(last["minus_di"]),
        "ema_fast": safe_float(last["ema_fast"]),
        "ema_slow": safe_float(last["ema_slow"]),
        "macd_hist": safe_float(last["macd_hist"]),
        "prev_ema_fast": safe_float(prev["ema_fast"]),
        "prev_ema_slow": safe_float(prev["ema_slow"]),
    }
    long_trend = (
        values["ema_fast"] > values["ema_slow"]
        and values["plus_di"] > values["minus_di"]
        and values["macd_hist"] > 0
        and values["adx"] >= params["min_adx"]
        and values["rsi"] < params["max_rsi"]
    )
    short_trend = (
        values["ema_fast"] < values["ema_slow"]
        and values["minus_di"] > values["plus_di"]
        and values["macd_hist"] < 0
        and values["adx"] >= params["min_adx"]
        and values["rsi"] > params["min_rsi"]
    )
    signal = "LONG" if long_trend else "SHORT" if short_trend else "NEUTRALNY"
    return signal, {**values, **params}

# ============================================================
# ORDERS / RISK
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
# USER CONFIG / WORKER
# ============================================================
def get_all_trading_users() -> List[Dict[str, Any]]:
    conn = db_connect()
    try:
        rows = conn.execute("""SELECT id,email,api_key,secret_key,passphrase,selected_exchange,is_admin,stripe_paid FROM users WHERE api_key<>'' AND secret_key<>''""").fetchall()
    finally:
        conn.close()
    return [{"id": int(r[0]), "email": r[1], "api_key": r[2] or "", "secret_key": r[3] or "", "passphrase": r[4] or "",
             "exchange": r[5] or "Bitget", "is_admin": bool(r[6]), "paid": bool(r[7])} for r in rows]


def get_user_risk_settings(user_id: int) -> Dict[str, Any]:
    conn = db_connect()
    try:
        row = conn.execute("SELECT settings_json FROM users WHERE id=?", (int(user_id),)).fetchone()
    finally:
        conn.close()
    base = {"max_single": DEFAULT_MAX_SINGLE, "max_positions": DEFAULT_MAX_POSITIONS, "enable_roe": True,
            "stop_roe": DEFAULT_STOP_ROE, "take_roe": DEFAULT_TAKE_ROE, "max_leverage": DEFAULT_MAX_LEVERAGE,
            "manual_leverage": DEFAULT_MANUAL_LEVERAGE, "leverage_mode": "Autonomiczny (płynny w granicach limitu)",
            "max_scan_pairs": DEFAULT_MAX_SCAN_PAIRS, "auto_base_influence": 50, "cooldown_minutes": 15}
    if row and row[0]:
        try:
            saved = json.loads(row[0])
            if isinstance(saved, dict):
                base.update(saved)
        except Exception:
            log.exception("Invalid risk settings for user %s", user_id)
    return base


def save_user_risk_settings(user_id: int, settings: Dict[str, Any]) -> None:
    conn = db_connect()
    try:
        conn.execute("UPDATE users SET settings_json=? WHERE id=?", (json.dumps(settings), int(user_id)))
        conn.commit()
    finally:
        conn.close()


class UserWorker:
    def __init__(self, user: Dict[str, Any]):
        self.user = user
        self.user_id = int(user["id"])
        self.exchange = get_exchange(user["api_key"], user["secret_key"], user["passphrase"], user["exchange"])
        self.cooldowns: Dict[str, float] = {}
        self.entry_locks: Dict[str, float] = {}
        self.last_protection_check = 0.0
        self.markets_loaded = False
        self.markets: Dict[str, Any] = {}
        self.last_candle_by_symbol_tf: Dict[Tuple[str, str], int] = {}

    def refresh_credentials(self) -> None:
        users = [u for u in get_all_trading_users() if u["id"] == self.user_id]
        if users:
            new = users[0]
            if (new["api_key"], new["secret_key"], new["passphrase"], new["exchange"]) != (
                self.user["api_key"], self.user["secret_key"], self.user["passphrase"], self.user["exchange"]):
                self.user = new
                self.exchange = get_exchange(new["api_key"], new["secret_key"], new["passphrase"], new["exchange"])
                self.markets_loaded = False

    def load_markets_safe(self) -> bool:
        if self.exchange is None:
            return False
        try:
            if not self.markets_loaded:
                self.markets = self.exchange.load_markets()
                self.markets_loaded = True
            return True
        except Exception as exc:
            self.markets_loaded = False
            log.warning("load_markets failed user=%s: %s", self.user_id, exc)
            return False

    def get_ranked_symbols(self, max_pairs: int) -> List[Tuple[str, float]]:
        symbols_with_volume = []
        try:
            if not self.markets_loaded or not self.exchange.markets:
                self.exchange.load_markets()
                self.markets_loaded = True
            
            for symbol, market in self.exchange.markets.items():
                if not market.get("active", True):
                    continue
                    
                sym_str = market.get("symbol", symbol)
                if "USDT" not in sym_str:
                    continue
                    
                base = market.get("base", "")
                if base in ["GOOGL", "MSFT", "DELL", "AAPL", "AMZN", "TSLA", "META", "NFLX", "XAU", "XAG", "EURUSD"]:
                    continue
                
                # Zabezpieczenie przed podwójnym sufiksem powodującym błąd API
                clean_symbol = symbol.split(":")[0] if ":" in symbol else symbol
                if "/" not in clean_symbol and base:
                    clean_symbol = f"{base}/USDT"
                    
                info = market.get("info", {})
                raw_val = (
                    info.get("usdtVolume") or 
                    info.get("quoteVolume") or 
                    market.get("quoteVolume") or 
                    0
                )
                try:
                    vol = float(raw_val)
                except (ValueError, TypeError):
                    vol = 0.0
                    
                symbols_with_volume.append((clean_symbol, vol))
            
            unique_dict = {}
            for sym, vol in symbols_with_volume:
                if sym not in unique_dict or vol > unique_dict[sym]:
                    unique_dict[sym] = vol
                    
            sorted_symbols = sorted(unique_dict.items(), key=lambda x: x[1], reverse=True)
            top_symbols = sorted_symbols[:max_pairs]
            
            if top_symbols:
                return top_symbols
        except Exception as e:
            log.error("Error: %s", e)
            
        return []


    def run_once(self) -> None:
        self.refresh_credentials()
        if self.exchange is None:
            return
        bots = load_active_bots(self.user_id)
        if not bots:
            log.info("User %s: no active MTF bots", self.user_id)
            return
        risk = get_user_risk_settings(self.user_id)
        self.protect_open_positions(risk)
        positions = fetch_positions_safe(self.exchange)
        pos_map = {p.get("symbol"): p for p in positions if p.get("symbol") and position_contracts(p) > 0}
        active_count = len(pos_map)
        if active_count >= int(risk["max_positions"]):
            return
        balance = fetch_usdt_balance(self.exchange)
        free_balance = balance["free"]
        ranked = self.get_ranked_symbols(int(risk["max_scan_pairs"]))
        if not ranked:
            log.warning("User %s: scanner returned 0 liquid symbols", self.user_id)
            return
        tickers = fetch_tickers_safe(self.exchange, [s for s, _ in ranked])
        log.info("User %s: scanning %s symbols across %s timeframe bots; free balance=%.4f",
                 self.user_id, len(ranked), list(bots.keys()), free_balance)
        if free_balance <= 0:
            log.warning("User %s: free USDT balance is %.4f; scanning continues but orders are disabled", self.user_id, free_balance)
        for tf, raw_cfg in list(bots.items()):
            if active_count >= int(risk["max_positions"]):
                break
            cfg = dict(raw_cfg)
            cfg["tf"] = tf
            for symbol, _qv in ranked:
                if active_count >= int(risk["max_positions"]):
                    break
                now = time.time()
                if now < self.cooldowns.get(symbol, 0) or now < self.entry_locks.get(symbol, 0):
                    continue
                if symbol in pos_map or entry_guard_blocks(self.user_id, symbol):
                    continue
                try:
                    limit = min(300, max(100, int(cfg.get("ema_slow", 21)) + 50))
                    ohlcv = self.exchange.fetch_ohlcv(symbol, tf, limit=limit)
                    if len(ohlcv) < 3:
                        continue
                    closed_candle_ts = int(ohlcv[-2][0])
                    candle_key = (tf, symbol)
                    if self.last_candle_by_symbol_tf.get(candle_key) == closed_candle_ts:
                        continue
                    self.last_candle_by_symbol_tf[candle_key] = closed_candle_ts
                    if entry_guard_blocks(self.user_id, symbol, closed_candle_ts):
                        continue
                    df = pd.DataFrame(ohlcv, columns=["timestamp", "open", "high", "low", "close", "volume"])
                    signal, vals = signal_from_closed_candle(df, cfg, float(risk["auto_base_influence"]) / 100)
                    if signal == "NEUTRALNY":
                        continue
                    max_ex = exchange_max_leverage(self.exchange, symbol, int(risk["max_leverage"]))
                    if risk["leverage_mode"] == "Ręczny":
                        lev = min(int(risk["manual_leverage"]), max_ex)
                    else:
                        adx = safe_float(vals.get("adx"), 20)
                        ratio = min(1, max(0, (adx - 10) / 45))
                        lev = max(1, int(round(1 + ratio * (min(int(risk["max_leverage"]), max_ex) - 1))))
                    set_leverage_safe(self.exchange, symbol, lev)
                    ticker = tickers.get(symbol, {}) or {}
                    entry_hint = safe_float(ticker.get("last")) or safe_float(vals.get("price"))
                    if entry_hint <= 0:
                        continue
                    initial_stop = roe_to_price(entry_hint, float(risk["stop_roe"]), lev, signal == "LONG")
                    notional = calculate_risk_allocation(free_balance, entry_hint, initial_stop, lev,
                                                         float(risk["max_single"]), float(vals.get("capital_multiplier", 1)))
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
                    # Final race check directly against exchange.
                    latest = find_position(fetch_positions_safe(self.exchange), symbol)
                    if latest:
                        pos_map[symbol] = latest
                        continue
                    lock_seconds = max(300.0, float(risk.get("cooldown_minutes", 15)) * 60)
                    self.entry_locks[symbol] = time.time() + lock_seconds
                    set_entry_guard(self.user_id, symbol, time.time() + lock_seconds, closed_candle_ts, signal)
                    order, sl_price, tp_price = place_entry_with_protection(
                        self.exchange, symbol, signal, amount, lev, float(risk["stop_roe"]), float(risk["take_roe"])
                    )
                    if order:
                        active_count += 1
                        fresh = find_position(fetch_positions_safe(self.exchange), symbol)
                        if fresh:
                            pos_map[symbol] = fresh
                        self.cooldowns[symbol] = time.time() + lock_seconds
                        set_entry_guard(self.user_id, symbol, time.time() + lock_seconds, closed_candle_ts, signal)
                        log_trade(self.user_id, symbol, tf, "ENTRY", signal, safe_float(order.get("average")) or entry_hint,
                                  amount, str(order.get("id", "")), f"SL={sl_price};TP={tp_price}")
                    else:
                        retry_lock = max(30.0, float(risk.get("cooldown_minutes", 15)) * 60)
                        self.cooldowns[symbol] = time.time() + retry_lock
                        self.entry_locks[symbol] = time.time() + retry_lock
                        set_entry_guard(self.user_id, symbol, time.time() + retry_lock, closed_candle_ts, signal)
                except Exception as exc:
                    fail_lock = 30.0
                    self.cooldowns[symbol] = time.time() + fail_lock
                    self.entry_locks[symbol] = time.time() + fail_lock
                    set_entry_guard(self.user_id, symbol, time.time() + fail_lock, locals().get("closed_candle_ts", 0), locals().get("signal", ""))
                    log.exception("Signal/order cycle failed user=%s tf=%s symbol=%s: %s", self.user_id, tf, symbol, exc)

    def protect_open_positions(self, risk: Dict[str, Any]) -> None:
        if not bool(risk["enable_roe"]):
            return
        if time.time() - self.last_protection_check < POSITION_GUARD_SECONDS:
            return
        self.last_protection_check = time.time()
        for p in fetch_positions_safe(self.exchange):
            amount = position_contracts(p)
            if amount <= 0:
                continue
            entry = safe_float(p.get("entryPrice"))
            mark = safe_float(p.get("markPrice")) or safe_float(p.get("lastPrice"))
            lev = safe_float(p.get("leverage"), 1)
            if entry <= 0 or mark <= 0:
                continue
            raw_move = ((mark - entry) / entry) * 100 if is_long(p) else ((entry - mark) / entry) * 100
            roe = raw_move * max(1, lev)
            symbol = p.get("symbol", "")
            reason = None
            action = None
            if roe <= -float(risk["stop_roe"]):
                reason, action = f"ROE SL {roe:.2f}%", "SL"
            elif roe >= float(risk["take_roe"]):
                reason, action = f"ROE TP {roe:.2f}%", "TP"
            if reason and close_position(self.exchange, p, reason):
                guard_until = time.time() + float(risk["cooldown_minutes"]) * 60
                self.cooldowns[symbol] = guard_until
                self.entry_locks[symbol] = guard_until
                set_entry_guard(self.user_id, symbol, guard_until, 0, action or "")
                log_trade(self.user_id, symbol, "guard", action or "CLOSE", position_side(p), mark, amount, message=f"ROE={roe:.2f}%")

    def loop(self, stop_event: threading.Event) -> None:
        log.info("Worker started for user %s (%s)", self.user_id, self.user.get("email"))
        while not stop_event.is_set():
            try:
                self.run_once()
            except Exception:
                log.exception("Worker top-level error for user %s", self.user_id)
                risk_settings = get_user_risk_settings(self.user_id)
            interval = float(risk_settings.get("scan_interval", 30))
            stop_event.wait(interval)
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
                worker, event = UserWorker(users[uid]), threading.Event()
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
# STREAMLIT
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
        session = stripe.checkout.Session.create(payment_method_types=["card"], line_items=[{"price": price_id, "quantity": 1}],
                                                 mode="payment", success_url="https://bot-bitget.pl/?success=true",
                                                 cancel_url="https://bot-bitget.pl/?success=false", customer_email=email)
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
    return {tf: {"mode": st.session_state.get(f"radio_mode_{tf}", "Automatyczny"),
                  "ema_fast": int(st.session_state.get(f"ema_f_{tf}", DEFAULT_TF_VALUES[tf]["ema_fast"])),
                  "ema_slow": int(st.session_state.get(f"ema_s_{tf}", DEFAULT_TF_VALUES[tf]["ema_slow"])),
                  "adx": float(st.session_state.get(f"adx_{tf}", DEFAULT_TF_VALUES[tf]["adx"])),
                  "max_rsi": float(st.session_state.get(f"max_rsi_{tf}", DEFAULT_TF_VALUES[tf]["max_rsi"])),
                  "min_rsi": float(st.session_state.get(f"min_rsi_{tf}", DEFAULT_TF_VALUES[tf]["min_rsi"])),
                  "cap_mult": float(st.session_state.get(f"cap_mult_{tf}", DEFAULT_TF_VALUES[tf]["cap_mult"]))} for tf in AVAILABLE_TIMEFRAMES}


def is_user_admin() -> bool:
    return str(st.session_state.get("user_email", "")).strip().lower() in [x.lower() for x in ADMIN_EMAILS] or bool(st.session_state.get("is_admin"))


def is_user_paid() -> bool:
    return is_user_admin() or bool(st.session_state.get("stripe_paid"))


def ui_login() -> None:
    st.markdown(f"<div class='gold-panel hero'><div class='gold-title'>{t('title')}</div><div class='gold-subtitle'>{t('subtitle')}</div>", unsafe_allow_html=True)
    tab_login, tab_register = st.tabs([t("login_tab"), t("register_tab")])
    with tab_login:
        email = st.text_input(t("email_label"), key="log_email")
        password = st.text_input(t("pass_label"), type="password", key="log_pass")
        if st.button(t("login_btn"), use_container_width=True):
            conn = db_connect()
            row = conn.execute("SELECT id,email,password,is_admin,stripe_paid,api_key,secret_key,passphrase,selected_exchange FROM users WHERE LOWER(TRIM(email))=?", (email.strip().lower(),)).fetchone()
            conn.close()
            if row and verify_password(password, row[2]):
                st.session_state.logged_in = True; st.session_state.user_id = row[0]; st.session_state.user_email = row[1]
                st.session_state.is_admin = bool(row[3]) or row[1].strip().lower() in [x.lower() for x in ADMIN_EMAILS]
                st.session_state.stripe_paid = True if st.session_state.is_admin else bool(row[4])
                st.session_state.api_key, st.session_state.secret_key, st.session_state.passphrase = row[5] or "", row[6] or "", row[7] or ""
                st.session_state.selected_exchange = row[8] or "Bitget"
                apply_mtf_to_session(row[0])
                if not str(row[2]).startswith("sha256$"):
                    conn = db_connect(); conn.execute("UPDATE users SET password=? WHERE id=?", (hash_password(password), row[0])); conn.commit(); conn.close()
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
                    clean = email.strip().lower(); admin = 1 if clean in [x.lower() for x in ADMIN_EMAILS] else 0
                    conn = db_connect(); conn.execute("INSERT INTO users(email,password,is_admin,stripe_paid) VALUES(?,?,?,?)", (clean, hash_password(password), admin, admin)); conn.commit(); conn.close()
                    st.success(t("reg_success"))
                except sqlite3.IntegrityError:
                    st.error(t("reg_error_exists"))
    st.markdown("</div><div class='gold-panel warning-box'>Handel Futures wiąże się z wysokim ryzykiem utraty kapitału. Oprogramowanie działa w formule As-Is i nie gwarantuje zysku.</div>", unsafe_allow_html=True)


def run_streamlit_app() -> None:
    st.set_page_config(page_title="Multi-Exchange Futures SaaS", layout="wide")
    init_db()
    for k, v in SESSION_DEFAULTS.items():
        if k not in st.session_state:
            st.session_state[k] = v
    st.markdown("""<style> :root{--bg:#070605;--panel:#100d09;--panel2:#17120c;--gold:#d7ad4a;--gold2:#f3d57a;--gold3:#8f6a25;--green:#29c66b;--red:#e05252;--text:#f5f0e6;--muted:#aaa092} .stApp{background:radial-gradient(circle at 50% -10%,#2a2115 0%,#0a0806 38%,#050403 100%);color:var(--text)} .block-container{padding-top:1rem;max-width:1600px} h1,h2,h3,h4{color:var(--gold2)!important} .gold-panel,.section-card,.metric-card,.mtf-card{border:1.5px solid var(--gold)!important;border-radius:15px;background:linear-gradient(145deg,#1b150e,#0b0907);box-shadow:0 0 0 1px rgba(243,213,122,.10) inset,0 8px 28px rgba(0,0,0,.38);padding:16px;margin-bottom:16px} .hero{text-align:center;padding:28px}.gold-title{font-size:clamp(28px,5vw,52px);font-weight:900;letter-spacing:4px;color:var(--gold2);text-shadow:0 0 18px rgba(243,213,122,.2)}.gold-subtitle{margin-top:7px;color:#d6c6a7;letter-spacing:2px} .warning-box{font-size:11px;color:#d9c7a4;text-align:center} .section-card{padding:14px}.section-title{color:var(--gold2);font-weight:900;font-size:16px;letter-spacing:.8px;margin-bottom:10px} .metric-grid{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:12px;margin-bottom:18px}.metric-card{min-height:120px}.metric-label{font-size:12px;color:var(--gold2);font-weight:800;text-transform:uppercase;letter-spacing:1px}.metric-value{font-size:25px;font-weight:900;color:#fff;margin-top:8px}.metric-sub{font-size:12px;color:var(--muted);margin-top:8px}.green{border-color:var(--green)!important}.red{border-color:var(--red)!important} .mtf-card{padding:11px}.mtf-card.active{border-color:var(--green)!important}.mtf-head{display:flex;justify-content:space-between;color:var(--gold2);font-weight:900}.status-pill{padding:4px 8px;border-radius:99px;font-size:10px}.status-pill.on{border:1px solid var(--green);color:#61e99a}.status-pill.off{border:1px solid var(--gold);color:var(--gold2)} .stButton>button{border:1.5px solid var(--gold)!important;background:linear-gradient(180deg,#251c10,#100c08)!important;color:#f7e8c4!important;border-radius:9px!important;font-weight:800!important;box-shadow:0 0 0 1px rgba(243,213,122,.08) inset!important}.stButton>button:hover{border-color:var(--gold2)!important;box-shadow:0 0 15px rgba(243,213,122,.22)!important} /* GOLD FRAME — all Streamlit input/control windows, not only cards */ [data-testid='stTextInput'],[data-testid='stNumberInput'],[data-testid='stSelectbox'],[data-testid='stMultiSelect'],[data-testid='stSlider'],[data-testid='stRadio'],[data-testid='stCheckbox'],[data-testid='stToggle'],[data-testid='stDateInput'],[data-testid='stTimeInput'],[data-testid='stTextArea'],[data-testid='stFileUploader'],[data-testid='stColorPicker'],[data-testid='stExpander'],[data-testid='stTabs'],[data-testid='stAlert'],[data-testid='stMetric'],[data-testid='stDataFrame'],[data-testid='stTable'],[data-testid='stStatusWidget'],[data-testid='stVerticalBlockBorderWrapper']{border:1.5px solid var(--gold)!important;border-radius:10px!important;box-shadow:0 0 0 1px rgba(243,213,122,.08) inset,0 4px 14px rgba(0,0,0,.22)!important;background:rgba(16,13,9,.35)} [data-testid='stTextInput']>div,[data-testid='stNumberInput']>div,[data-testid='stSelectbox']>div,[data-testid='stMultiSelect']>div,[data-testid='stTextArea']>div{border-color:var(--gold)!important} input,textarea,[data-baseweb='select']>div,[data-baseweb='input']>div{border:1.5px solid var(--gold)!important;border-radius:8px!important;background:#0d0a07!important;color:var(--text)!important} [data-baseweb='slider'] [role='slider']{border-color:var(--gold2)!important;box-shadow:0 0 8px rgba(243,213,122,.25)!important} [data-baseweb='tab-list']{border-bottom:1.5px solid var(--gold)!important} [data-baseweb='tab']{color:var(--gold2)!important} [data-testid='stExpander'] summary{color:var(--gold2)!important} .stDataFrame{border:1.5px solid var(--gold)!important;border-radius:10px;overflow:hidden} [data-testid='stAlert']{color:var(--text)!important} section[data-testid='stSidebar']{background:linear-gradient(180deg,#15110c,#080706);border-right:1.5px solid var(--gold)} section[data-testid='stSidebar'] [data-testid='stTextInput'],section[data-testid='stSidebar'] [data-testid='stNumberInput'],section[data-testid='stSidebar'] [data-testid='stSelectbox'],section[data-testid='stSidebar'] [data-testid='stSlider'],section[data-testid='stSidebar'] [data-testid='stRadio'],section[data-testid='stSidebar'] [data-testid='stCheckbox']{border:1.5px solid var(--gold)!important;border-radius:10px!important;padding:6px!important;margin-bottom:8px!important} @media(max-width:1100px){.metric-grid{grid-template-columns:repeat(2,minmax(0,1fr))}}@media(max-width:650px){.metric-grid{grid-template-columns:1fr}} </style>""", unsafe_allow_html=True)
    if not st.session_state.logged_in:
        ui_login(); st.stop()
    apply_mtf_to_session(st.session_state.user_id)

    st.sidebar.selectbox("🌐 Language / Język", ["Polski", "English"], index=0 if st.session_state.lang == "Polski" else 1, key="lang_selector")
    st.session_state.lang = st.session_state.lang_selector
    st.sidebar.markdown(f"### 👤 {st.session_state.user_email}")
    st.sidebar.markdown(f"**{t('sidebar_role_admin') if is_user_admin() else t('sidebar_role_client')}**")
    if st.sidebar.button(t("logout_btn"), use_container_width=True):
        for k in ["logged_in","user_email","is_admin","user_id","stripe_paid","api_key","secret_key","passphrase"]: st.session_state[k] = SESSION_DEFAULTS[k]
        st.session_state.active_mtf_bots = {}; st.session_state._mtf_loaded_user_id = None; st.rerun()

    st.sidebar.header(t("exchange_settings"))
    selected_exchange = st.sidebar.selectbox(t("select_exchange"), SUPPORTED_EXCHANGES,
        index=SUPPORTED_EXCHANGES.index(st.session_state.selected_exchange) if st.session_state.selected_exchange in SUPPORTED_EXCHANGES else 0,
        key="sidebar_selected_exchange")
    st.session_state.selected_exchange = selected_exchange
    api = st.sidebar.text_input(f"API Key ({selected_exchange})", value=st.session_state.api_key, type="password", key=f"api_{selected_exchange}")
    secret = st.sidebar.text_input(f"API Secret ({selected_exchange})", value=st.session_state.secret_key, type="password", key=f"secret_{selected_exchange}")
    passphrase = st.sidebar.text_input(f"Passphrase ({selected_exchange})", value=st.session_state.passphrase, type="password", key=f"pass_{selected_exchange}") if selected_exchange in {"Bitget","OKX"} else ""
    if st.sidebar.button(t("save_keys_btn"), use_container_width=True):
        if api and secret:
            st.session_state.api_key, st.session_state.secret_key, st.session_state.passphrase = api, secret, passphrase
            conn = db_connect(); conn.execute("UPDATE users SET api_key=?,secret_key=?,passphrase=?,selected_exchange=? WHERE id=?", (api,secret,passphrase,selected_exchange,st.session_state.user_id)); conn.commit(); conn.close()
            st.success(f"{t('keys_saved')} {selected_exchange}"); st.rerun()
        else: st.error(t("keys_error"))

    st.sidebar.markdown("---"); st.sidebar.markdown(f"### {t('sub_zone')}")
    st.sidebar.success(t("sub_active") if is_user_paid() else t("sub_inactive"))
    price_id = get_secret("STRIPE_PRICE_ID", STRIPE_PRICE_ID)
    st.sidebar.link_button(t("pay_btn"), create_stripe_checkout_session(st.session_state.user_email, price_id), use_container_width=True)
    if ALLOW_TEST_ACTIVATION and st.sidebar.button("⚡ [TEST] Aktywuj dostęp natychmiast"):
        conn=db_connect(); conn.execute("UPDATE users SET stripe_paid=1 WHERE id=?",(st.session_state.user_id,)); conn.commit(); conn.close(); st.session_state.stripe_paid=True; st.rerun()

    saved = get_user_risk_settings(st.session_state.user_id)
    st.sidebar.markdown("---"); st.sidebar.markdown(f"### {t('capital_risk')}")
    max_single = st.sidebar.number_input(t("max_single"), 5.0, 5000.0, float(saved["max_single"]), 5.0, key="sb_max_single_trade")
    max_pos = st.sidebar.slider(t("max_pos"), 1, 20, int(saved["max_positions"]), key="sb_max_active_pos")
    st.sidebar.markdown("---"); st.sidebar.markdown(f"### {t('roe_guard')}")
    enable_roe = st.sidebar.checkbox(t("enable_roe"), bool(saved["enable_roe"]), key="enable_roe_guard")
    stop_roe = st.sidebar.slider(t("sl_roe"), .5, 50., float(saved["stop_roe"]), .5, key="custom_stop_loss_roe") if enable_roe else 999.
    take_roe = st.sidebar.slider(t("tp_roe"), 1., 100., float(saved["take_roe"]), .5, key="custom_take_profit_roe") if enable_roe else 999.
    cooldown = st.sidebar.slider("Cooldown after SL/TP (minutes)", 1, 120, int(saved["cooldown_minutes"]), key="sb_cooldown_sl_tp")
    st.sidebar.markdown("---"); st.sidebar.markdown(f"### {t('leverage_mgmt')}")
    lev_mode = st.sidebar.radio(t("lev_mode"), ["Autonomiczny (płynny w granicach limitu)","Ręczny"], index=0 if saved["leverage_mode"] != "Ręczny" else 1, key="sb_leverage_mode")
    max_lev = st.sidebar.slider(t("max_allowed_lev"),1,50,int(saved["max_leverage"]),key="sb_max_allowed_leverage")
    manual_lev = st.sidebar.slider(t("manual_lev"),1,50,int(saved["manual_leverage"]),key="sb_manual_leverage")
    st.sidebar.markdown("---")
    max_scan = st.sidebar.slider(t("max_pairs"),1,100,int(saved["max_scan_pairs"]),key="sb_max_fut_pairs")
    scan_interval = st.sidebar.slider("Interwał skanowania (sekundy)", 5, 300, int(saved.get("scan_interval", 30)), 5, key="sb_scan_interval")
    auto_influence = st.sidebar.slider("🎚️ Base slider influence in Auto mode (%)",0,100,int(saved["auto_base_influence"]),5,key="sb_auto_base_influence")
    risk_now={"max_single":max_single,"max_positions":max_pos,"enable_roe":enable_roe,"stop_roe":stop_roe,"take_roe":take_roe,"max_leverage":max_lev,"manual_leverage":manual_lev,"leverage_mode":lev_mode,"max_scan_pairs":max_scan,"auto_base_influence":auto_influence,"cooldown_minutes":cooldown}
    if risk_now != saved: save_user_risk_settings(st.session_state.user_id,risk_now)

    st.markdown("<div class='section-card'><div class='section-title'>🤖 MTF — KONTROLA AUTONOMICZNYCH BOTÓW</div><div style='color:#aaa092;font-size:12px'>Każdy interwał działa niezależnie. Ustawienia są zapisywane w SQLite.</div></div>",unsafe_allow_html=True)
    cols=st.columns(len(AVAILABLE_TIMEFRAMES))
    for i,tf in enumerate(AVAILABLE_TIMEFRAMES):
        with cols[i]:
            active_tf=tf in st.session_state.active_mtf_bots
            st.markdown(f"<div class='mtf-card {'active' if active_tf else ''}'><div class='mtf-head'><span>⏱ {tf}</span><span class='status-pill {'on' if active_tf else 'off'}'>{'● AKTYWNY' if active_tf else '○ GOTOWY'}</span></div>",unsafe_allow_html=True)
            k_mode,k_f,k_s,k_adx,k_max,k_min,k_cap=[f"{p}_{tf}" for p in ["radio_mode","ema_f","ema_s","adx","max_rsi","min_rsi","cap_mult"]]
            mode=st.radio(f"Tryb ({tf})",["Automatyczny","Ręczny"],key=k_mode)
            f=st.number_input(f"EMA Szybka ({tf})",1,200,key=k_f); s=st.number_input(f"EMA Wolna ({tf})",2,300,key=k_s)
            adx=st.slider(f"Min ADX ({tf})",10.,50.,key=k_adx); maxr=st.slider(f"Max RSI Long ({tf})",50.,95.,key=k_max); minr=st.slider(f"Min RSI Short ({tf})",5.,50.,key=k_min)
            cap=st.number_input(f"CAP x ({tf})",.1,10.,float(st.session_state.get(k_cap,DEFAULT_TF_VALUES[tf]["cap_mult"])),.1,key=k_cap)
            if f>=s: st.warning("Fast EMA must be lower than slow EMA")
            cfg={"mode":mode,"ema_fast":min(int(f),int(s)-1),"ema_slow":max(int(s),int(f)+1),"min_adx":float(adx),"max_rsi":float(maxr),"min_rsi":float(minr),"capital_multiplier":float(cap),"tf":tf}
            if active_tf:
                st.success("🟢 ACTIVE")
                if st.button(f"Stop {tf}",key=f"stop_{tf}",use_container_width=True):
                    st.session_state.active_mtf_bots.pop(tf,None); save_active_bots(st.session_state.user_id,st.session_state.active_mtf_bots); MANAGER.reconcile(); st.rerun()
            else:
                if st.button(f"Start {tf}",key=f"start_{tf}",use_container_width=True):
                    if not st.session_state.api_key or not st.session_state.secret_key: st.error("Save your API keys in the sidebar first.")
                    elif not is_user_paid(): st.error("An active subscription is required.")
                    else:
                        st.session_state.active_mtf_bots[tf]=cfg; save_active_bots(st.session_state.user_id,st.session_state.active_mtf_bots); save_mtf_settings(st.session_state.user_id,current_mtf_payload()); MANAGER.reconcile(); st.rerun()
            st.markdown("</div>",unsafe_allow_html=True)
    save_mtf_settings(st.session_state.user_id,current_mtf_payload())
    MANAGER.reconcile()

    if st.sidebar.button(t("kill_switch"),type="primary",use_container_width=True):
        ex=get_exchange(st.session_state.api_key,st.session_state.secret_key,st.session_state.passphrase,st.session_state.selected_exchange)
        if ex:
            for p in fetch_positions_safe(ex): close_position(ex,p,"KILL SWITCH")
        st.session_state.active_mtf_bots={}; save_active_bots(st.session_state.user_id,{}); MANAGER.reconcile(); st.success("🔴 KILL SWITCH EXECUTED."); st.rerun()

    st.markdown(f"<div class='gold-panel'><b style='color:#f3d57a'>💠 FUTURES CONTROL CENTER</b> <span style='float:right'>👤 {st.session_state.user_email} · {st.session_state.selected_exchange}</span></div>",unsafe_allow_html=True)
    ex=get_exchange(st.session_state.api_key,st.session_state.secret_key,st.session_state.passphrase,st.session_state.selected_exchange)
    positions=[p for p in fetch_positions_safe(ex) if position_contracts(p)>0] if ex else []
    total_unreal=sum(safe_float(p.get("unrealizedPnl")) for p in positions)
    bal=fetch_usdt_balance(ex) if ex else {"total":0.,"used":0.,"free":0.}
    if not st.session_state.session_baseline_locked and bal["total"]>0: st.session_state.session_start_balance=bal["total"]; st.session_state.session_baseline_locked=True
    pnl_pct=((bal["total"]-st.session_state.session_start_balance)/st.session_state.session_start_balance*100) if st.session_state.session_start_balance>0 else 0
    elapsed=max(0,int((datetime.now()-st.session_state.session_start_time).total_seconds())); h,rem=divmod(elapsed,3600); m,sx=divmod(rem,60)
    st.markdown(f"<div class='metric-grid'><div class='metric-card'><div class='metric-label'>💰 {t('wallet_futures')}</div><div class='metric-value'>{bal['total']:.2f} USDT</div><div class='metric-sub'>Zajęte: {bal['used']:.2f} · {t('free_balance')}: {bal['free']:.2f}</div></div><div class='metric-card {'green' if pnl_pct>=0 else 'red'}'><div class='metric-label'>📈 {t('session_results')}</div><div class='metric-value'>{pnl_pct:+.2f}%</div><div class='metric-sub'>{t('pnl_usdt')}: {total_unreal:+.2f}</div></div><div class='metric-card'><div class='metric-label'>🎯 {t('slots_futures')}</div><div class='metric-value'>{len(positions)} / {max_pos}</div><div class='metric-sub'>Wolne sloty: {max(0,max_pos-len(positions))}</div></div><div class='metric-card'><div class='metric-label'>⚡ {t('session_time')}</div><div class='metric-value'>{h:02d}:{m:02d}:{sx:02d}</div><div class='metric-sub'>Aktywne boty: {len(st.session_state.active_mtf_bots)}</div></div></div>",unsafe_allow_html=True)

    st.markdown(f"<div class='section-card'><div class='section-title'>{t('active_positions')}</div>",unsafe_allow_html=True)
    if positions: st.dataframe(pd.DataFrame(positions),use_container_width=True)
    else: st.info(t("no_positions"))
    st.markdown("</div>",unsafe_allow_html=True)

    st.markdown(f"<div class='section-card'><div class='section-title'>{t('trade_history')}</div>",unsafe_allow_html=True)
    conn=db_connect()
    try: hist=pd.read_sql_query("SELECT created_at,symbol,timeframe,action,side,price,amount,order_id,message FROM trade_log WHERE user_id=? ORDER BY id DESC LIMIT 100",conn,params=(st.session_state.user_id,))
    except Exception: hist=pd.DataFrame()
    finally: conn.close()
    if not hist.empty: st.dataframe(hist,use_container_width=True)
    else: st.info(t("no_history"))
    st.markdown("</div>",unsafe_allow_html=True)

    # Scanner: show every selected liquid pair. If an exchange rejects bulk ticker
    # requests, the fallback fetches individual tickers instead of producing a blank table.
    st.markdown(f"<div class='section-card'><div class='section-title'>{t('market_scanner_results')}</div>",unsafe_allow_html=True)
    scan_now = st.button("🔎 RUN SCAN NOW / URUCHOM SKANOWANIE", use_container_width=True, key="run_scan_now")
    scanner=[]
    ranked=[]
    if ex and st.session_state.active_mtf_bots:
        try:
            ranked = rank_usdt_linear_symbols(ex, max_scan)
            if not ranked:
                st.warning("Scanner found no liquid USDT perpetuals. Check exchange API permissions and market type.")
            else:
                for tf,cfg in st.session_state.active_mtf_bots.items():
                    for sym,qv in ranked:
                        try:
                            data=ex.fetch_ohlcv(sym,tf,limit=min(180,max(100,int(cfg.get("ema_slow",21))+50)))
                            if len(data)<3:
                                scanner.append({"Timeframe":tf,"Pair":sym,"Price":None,"ADX":None,"RSI":None,"Signal":"NO DATA","24h Volume":qv,"Status":"Too little OHLCV data"})
                                continue
                            df=pd.DataFrame(data,columns=["timestamp","open","high","low","close","volume"])
                            sig,vals=signal_from_closed_candle(df,{**cfg,"tf":tf},auto_influence/100)
                            scanner.append({"Timeframe":tf,"Pair":sym,"Price":vals.get("price"),"ADX":round(vals.get("adx",0),2),"RSI":round(vals.get("rsi",0),2),"Signal":sig,"24h Volume":qv,"Status":"OK"})
                        except Exception as exc:
                            scanner.append({"Timeframe":tf,"Pair":sym,"Price":None,"ADX":None,"RSI":None,"Signal":"ERROR","24h Volume":qv,"Status":str(exc)[:160]})
                            log.warning("Scanner %s %s failed: %s",tf,sym,exc)
        except Exception as exc:
            log.exception("Scanner failed: %s",exc)
            st.error(f"Scanner error: {exc}")
    else:
        st.info("Start at least one MTF bot to activate the scanner.")
    if scanner:
        st.dataframe(pd.DataFrame(scanner),use_container_width=True,hide_index=True)
        ok_count=sum(1 for r in scanner if r.get("Status")=="OK")
        long_count=sum(1 for r in scanner if r.get("Signal")=="LONG")
        short_count=sum(1 for r in scanner if r.get("Signal")=="SHORT")
        st.caption(f"Scanned rows: {len(scanner)} · OK: {ok_count} · LONG: {long_count} · SHORT: {short_count} · selected pairs: {len(ranked) if ex and st.session_state.active_mtf_bots else 0}")
    st.markdown("</div>",unsafe_allow_html=True)

    # IMPORTANT: do not use HTML meta-refresh here. A full browser reload can create
    # a new Streamlit session and make a logged-in user appear logged out.
    # The autonomous trading worker runs independently, so the UI does not need
    # to force-refresh the whole page. Use the sidebar refresh button instead.
    if st.sidebar.button("🔄 Refresh view / Odśwież widok", use_container_width=True):
        st.rerun()


if __name__ == "__main__":
    parser=argparse.ArgumentParser()
    parser.add_argument("--worker",action="store_true",help="Uruchom autonomiczny silnik tradingowy bez Streamlit")
    args,_=parser.parse_known_args()
    if args.worker: run_worker_mode()
    else: run_streamlit_app()

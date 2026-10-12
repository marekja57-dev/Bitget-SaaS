import gc
import hashlib
import hmac
import json
import logging
import os
import pathlib
from pathlib import Path
import secrets
import sqlite3
import threading
import time
from datetime import datetime, timezone

import numpy as np
import pandas as pd
import streamlit as st

try:
    import ccxt
except ImportError:
    ccxt = None

st.set_page_config(page_title="Bitget-SaaS Futures", page_icon="📈", layout="wide")

APP_DIR = Path(__file__).resolve().parent
DB_PATH = Path(os.getenv("BITGET_SAAS_DB", str(APP_DIR / "bitget_saas.db")))
LOG_PATH = APP_DIR / "trading.log"

logging.basicConfig(
    filename=str(LOG_PATH),
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)

STRIPE_CHECKOUT_FALLBACK = "https://buy.stripe.com/8x2dRa4CbdaXfSAf6V3oA03"
ADMIN_EMAILS = {"marekja57@wp.pl", "admin@bot-bitget.pl"}
TF_OPTIONS = ["1m", "3m", "5m", "15m", "30m", "1h", "2h", "4h", "1d"]
MIN_ORDER_NOTIONAL_USDT = 10.0

DEFAULT_TF_SETTINGS = {
    "1m": {
        "ema_fast": 9,
        "ema_slow": 21,
        "adx_threshold": 25.0,
        "rsi_period": 14,
        "rsi_long_min": 52.0,
        "rsi_long_max": 68.0,
        "rsi_short_min": 32.0,
        "rsi_short_max": 48.0,
        "rsi_min": 25.0,
        "rsi_max": 75.0,
    },
    "3m": {
        "ema_fast": 9,
        "ema_slow": 21,
        "adx_threshold": 25.0,
        "rsi_period": 14,
        "rsi_long_min": 52.0,
        "rsi_long_max": 68.0,
        "rsi_short_min": 32.0,
        "rsi_short_max": 48.0,
        "rsi_min": 25.0,
        "rsi_max": 75.0,
    },
    "5m": {
        "ema_fast": 9,
        "ema_slow": 21,
        "adx_threshold": 25.0,
        "rsi_period": 14,
        "rsi_long_min": 52.0,
        "rsi_long_max": 68.0,
        "rsi_short_min": 32.0,
        "rsi_short_max": 48.0,
        "rsi_min": 25.0,
        "rsi_max": 75.0,
    },
    "15m": {
        "ema_fast": 9,
        "ema_slow": 21,
        "adx_threshold": 25.0,
        "rsi_period": 14,
        "rsi_long_min": 52.0,
        "rsi_long_max": 68.0,
        "rsi_short_min": 32.0,
        "rsi_short_max": 48.0,
        "rsi_min": 25.0,
        "rsi_max": 75.0,
    },
    "30m": {
        "ema_fast": 9,
        "ema_slow": 21,
        "adx_threshold": 25.0,
        "rsi_period": 14,
        "rsi_long_min": 52.0,
        "rsi_long_max": 68.0,
        "rsi_short_min": 32.0,
        "rsi_short_max": 48.0,
        "rsi_min": 25.0,
        "rsi_max": 75.0,
    },
    "1h": {
        "ema_fast": 12,
        "ema_slow": 26,
        "adx_threshold": 22.0,
        "rsi_period": 14,
        "rsi_long_min": 52.0,
        "rsi_long_max": 68.0,
        "rsi_short_min": 32.0,
        "rsi_short_max": 48.0,
        "rsi_min": 30.0,
        "rsi_max": 70.0,
    },
    "2h": {
        "ema_fast": 12,
        "ema_slow": 26,
        "adx_threshold": 20.0,
        "rsi_period": 14,
        "rsi_long_min": 52.0,
        "rsi_long_max": 68.0,
        "rsi_short_min": 32.0,
        "rsi_short_max": 48.0,
        "rsi_min": 30.0,
        "rsi_max": 70.0,
    },
    "4h": {
        "ema_fast": 9,
        "ema_slow": 21,
        "adx_threshold": 20.0,
        "rsi_period": 14,
        "rsi_long_min": 52.0,
        "rsi_long_max": 68.0,
        "rsi_short_min": 32.0,
        "rsi_short_max": 48.0,
        "rsi_min": 30.0,
        "rsi_max": 70.0,
    },
    "1d": {
        "ema_fast": 20,
        "ema_slow": 50,
        "adx_threshold": 18.0,
        "rsi_period": 14,
        "rsi_long_min": 52.0,
        "rsi_long_max": 68.0,
        "rsi_short_min": 32.0,
        "rsi_short_max": 48.0,
        "rsi_min": 30.0,
        "rsi_max": 70.0,
    },
}

DEFAULTS = {
    "exchange": "bitget",
    "market_type": "swap",
    "candle_limit": 150,
    "refresh_seconds": 30,
    "risk_usdt": 10.0,
    "max_positions": 3,
    "max_leverage": 10,
    "sl_roe": 20.0,
    "tp_roe": 40.0,
    "enable_roe": True,
    "timeframes": ["4h", "1d"],
    "tf_settings": DEFAULT_TF_SETTINGS,
    "auto_refresh": True,
    "auto_trade": False,
    "paper_mode": True,
    "max_notional_usdt": 200.0,
    "cooldown_seconds": 300,
    "allow_short": True,
    "allow_long": True,
    "scan_limit_count": 10,
    "indicator_multiplier": 100,
}

st.markdown(
    """<style> .stApp{background:radial-gradient(ellipse at 40% -20%,#103e78 0%,#071a36 42%,#050e20 100%);color:#eaf3ff} [data-testid="stHeader"]{background:rgba(3,12,29,.96)} [data-testid="stAppViewContainer"] .main .block-container{padding-top:2rem;max-width:1600px} [data-testid="stSidebar"]{background:linear-gradient(180deg,#06152d,#081f42)} .brand{font-weight:900;font-size:30px;color:#eaf5ff;margin:.5rem 0} .metric-card{border:1px solid #d8ad52;border-radius:14px;padding:18px;height:150px;display:flex;flex-direction:column;justify-content:center;background:linear-gradient(145deg,#1b2b44,#061225);overflow:hidden} .metric-label{color:#b9c9df;font-size:12px;font-weight:700;letter-spacing:1px;text-transform:uppercase;margin-bottom:10px} .metric-value{color:#fff2c7;font-size:clamp(20px,1.8vw,29px);font-weight:850;line-height:1.2;overflow-wrap:anywhere} .metric-note{color:#a9bdd7;font-size:12px;margin-top:8px} </style>""",
    unsafe_allow_html=True,
)

# -------------------- Baza danych --------------------

def db():
    con = sqlite3.connect(DB_PATH, timeout=20)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA busy_timeout=20000")
    con.execute("PRAGMA journal_mode=WAL")
    con.execute(
        "CREATE TABLE IF NOT EXISTS settings(k TEXT PRIMARY KEY,v TEXT NOT NULL)"
    )
    con.execute(
        """CREATE TABLE IF NOT EXISTS user_credentials( user_id INTEGER PRIMARY KEY,exchange TEXT,api_key TEXT,secret TEXT,password TEXT)"""
    )
    con.execute(
        "CREATE TABLE IF NOT EXISTS events(id INTEGER PRIMARY KEY AUTOINCREMENT,ts TEXT,level TEXT,message TEXT)"
    )
    con.execute(
        """CREATE TABLE IF NOT EXISTS pair_cooldowns( symbol TEXT PRIMARY KEY, closed_at REAL NOT NULL, reason TEXT NOT NULL )"""
    )
    con.execute(
        """CREATE TABLE IF NOT EXISTS users( id INTEGER PRIMARY KEY AUTOINCREMENT,username TEXT UNIQUE NOT NULL,password TEXT NOT NULL, subscription TEXT,stripe_paid INTEGER NOT NULL DEFAULT 0,email TEXT UNIQUE)"""
    )
    con.commit()
    return con

def password_hash(password, salt=None):
    salt = salt or secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac(
        "sha256", password.encode(), salt.encode(), 240000
    ).hex()
    return f"pbkdf2${salt}${digest}"

def verify_password(stored, password):
    if stored == password:
        return True, True
    try:
        scheme, salt, digest = stored.split("$", 2)
        if scheme != "pbkdf2":
            return False, False
        check = hashlib.pbkdf2_hmac(
            "sha256", password.encode(), salt.encode(), 240000
        ).hex()
        return hmac.compare_digest(check, digest), False
    except Exception:
        return False, False

def load_cfg():
    cfg = json.loads(json.dumps(DEFAULTS))
    try:
        with db() as con:
            row = con.execute("SELECT v FROM settings WHERE k='main'").fetchone()
            if row:
                cfg.update(json.loads(row["v"]))
        merged = json.loads(json.dumps(DEFAULT_TF_SETTINGS))
        for tf, vals in (cfg.get("tf_settings") or {}).items():
            if tf in merged and isinstance(vals, dict):
                merged[tf].update(vals)
        cfg["tf_settings"] = merged
    except Exception:
        logging.exception("Nie udało się wczytać ustawień")
    return cfg

def save_cfg(cfg):
    with db() as con:
        con.execute(
            """INSERT INTO settings(k,v) VALUES('main',?) ON CONFLICT(k) DO UPDATE SET v=excluded.v""",
            (json.dumps(cfg, ensure_ascii=False),),
        )
        con.commit()

def event(level, message):
    message = str(message)[:1500]
    logging.log(getattr(logging, str(level).upper(), logging.INFO), message)
    with db() as con:
        con.execute(
            "INSERT INTO events(ts,level,message) VALUES(?,?,?)",
            (datetime.now(timezone.utc).isoformat(), str(level), message),
        )
        con.commit()

def set_pair_cooldown(symbol, reason, seconds=600):
    if not symbol:
        return
    with db() as con:
        con.execute(
            """INSERT INTO pair_cooldowns(symbol, closed_at, reason) VALUES(?,?,?) ON CONFLICT(symbol) DO UPDATE SET closed_at=excluded.closed_at, reason=excluded.reason""",
            (str(symbol), time.time(), str(reason)),
        )
        con.commit()

def pair_cooldown_remaining(symbol, seconds=600):
    if not symbol:
        return 0
    try:
        with db() as con:
            row = con.execute(
                "SELECT closed_at FROM pair_cooldowns WHERE symbol=?", (str(symbol),)
            ).fetchone()
            if not row:
                return 0
            remaining = int(
                max(0, float(seconds) - (time.time() - float(row["closed_at"])))
            )
            if remaining <= 0:
                with db() as con:
                    con.execute(
                        "DELETE FROM pair_cooldowns WHERE symbol=?", (str(symbol),)
                    )
                con.commit()
            return remaining
    except Exception:
        logging.exception("Nie udało się sprawdzić blokady pary %s", symbol)
        return int(seconds)

def load_creds(user_id):
    if not user_id:
        return ("bitget", "", "", "")
    with db() as con:
        row = con.execute(
            "SELECT exchange,api_key,secret,password FROM user_credentials WHERE user_id=?",
            (user_id,),
        ).fetchone()
        return tuple(row) if row else ("bitget", "", "", "")

def save_creds(user_id, exchange, api_key, secret, passphrase):
    if not user_id:
        return
    with db() as con:
        con.execute(
            """INSERT INTO user_credentials(user_id,exchange,api_key,secret,password) VALUES(?,?,?,?,?) ON CONFLICT(user_id) DO UPDATE SET exchange=excluded.exchange, api_key=excluded.api_key,secret=excluded.secret,password=excluded.password""",
            (user_id, exchange, api_key, secret, passphrase),
        )
        con.commit()

def create_stripe_checkout_url():
    if not STRIPE_CHECKOUT_FALLBACK.startswith("https://buy.stripe.com/"):
        raise ValueError("Ustaw prawidłowy aktywny link płatności Stripe.")
    return STRIPE_CHECKOUT_FALLBACK

# -------------------- Giełda --------------------

@st.cache_resource(show_spinner=False)
def exchange_client(ex_id, api_key, secret, passphrase, market_type):
    if ccxt is None:
        raise RuntimeError("Brak biblioteki ccxt. Zainstaluj: pip install ccxt")
    cls = getattr(ccxt, ex_id, None)
    if cls is None:
        raise ValueError(f"Nieobsługiwana giełda: {ex_id}")
    opts = {
        "enableRateLimit": True,
        "timeout": 25000,
        "options": {"defaultType": market_type, "defaultSubType": "linear"},
    }
    if api_key and secret:
        opts.update(apiKey=api_key, secret=secret)
    if passphrase:
        opts["password"] = passphrase
    return cls(opts)

@st.cache_data(ttl=30, max_entries=20, show_spinner=False)
def get_candles(ex_id, market_type, symbol, timeframe, limit):
    ex = exchange_client(ex_id, "", "", "", market_type)
    rows = ex.fetch_ohlcv(symbol, timeframe=timeframe, limit=int(limit))
    return pd.DataFrame(
        rows, columns=["timestamp", "open", "high", "low", "close", "volume"]
    )

def indicators(df, fast, slow, rsi_period=14):
    d = df.copy()
    for col in ["open", "high", "low", "close", "volume"]:
        d[col] = pd.to_numeric(d[col], errors="coerce")
    d = d.dropna(subset=["high", "low", "close"]).reset_index(drop=True)
    d["ema_fast"] = d["close"].ewm(span=int(fast), adjust=False).mean()
    d["ema_slow"] = d["close"].ewm(span=int(slow), adjust=False).mean()
    delta = d["close"].diff()
    rsi_period = max(2, int(rsi_period))
    gain = delta.clip(lower=0).ewm(alpha=1 / rsi_period, adjust=False).mean()
    loss = (-delta.clip(upper=0)).ewm(alpha=1 / rsi_period, adjust=False).mean()
    rs = gain / loss.replace(0, np.nan)
    d["rsi"] = 100 - 100 / (1 + rs)
    tr = pd.concat(
        [
            (d["high"] - d["low"]).abs(),
            (d["high"] - d["close"].shift()).abs(),
            (d["low"] - d["close"].shift()).abs(),
        ],
        axis=1,
    ).max(axis=1)
    up, down = d["high"].diff(), -d["low"].diff()
    plus = pd.Series(np.where((up > down) & (up > 0), up, 0), index=d.index)
    minus = pd.Series(np.where((down > up) & (down > 0), down, 0), index=d.index)
    atr = tr.ewm(alpha=1 / 14, adjust=False).mean().replace(0, np.nan)
    pdi = 100 * plus.ewm(alpha=1 / 14, adjust=False).mean() / atr
    mdi = 100 * minus.ewm(alpha=1 / 14, adjust=False).mean() / atr
    dx = 100 * (pdi - mdi).abs() / (pdi + mdi).replace(0, np.nan)
    d["adx"] = dx.ewm(alpha=1 / 14, adjust=False).mean()
    return d

def effective_tf_cfg(cfg, tf):
    base = cfg.get("tf_settings", {}).get(
        tf, DEFAULT_TF_SETTINGS.get(tf, DEFAULT_TF_SETTINGS["1h"])
    )
    mult = float(cfg.get("indicator_multiplier", 100)) / 100
    fast = max(2, int(round(float(base["ema_fast"]))))
    slow = max(fast + 1, int(round(float(base["ema_slow"]))))
    rsi_long_min = float(base.get("rsi_long_min", 52.0))
    rsi_long_max = float(base.get("rsi_long_max", 68.0))
    rsi_short_min = float(base.get("rsi_short_min", 32.0))
    rsi_short_max = float(base.get("rsi_short_max", 48.0))
    return {
        "ema_fast": fast,
        "ema_slow": slow,
        "adx_threshold": max(
            2.0, min(90.0, float(base["adx_threshold"]) * mult)
        ),
        "rsi_period": max(2, min(100, int(base.get("rsi_period", 14)))),
        "rsi_long_min": max(0.0, min(100.0, rsi_long_min)),
        "rsi_long_max": max(0.0, min(100.0, rsi_long_max)),
        "rsi_short_min": max(0.0, min(100.0, rsi_short_min)),
        "rsi_short_max": max(0.0, min(100.0, rsi_short_max)),
        "rsi_min": max(0.0, min(100.0, float(base.get("rsi_min", 30.0)))),
        "rsi_max": max(0.0, min(100.0, float(base.get("rsi_max", 70.0)))),
    }

def signal_for_symbol(cfg, symbol, timeframe):
    try:
        t = effective_tf_cfg(cfg, timeframe)
        raw = get_candles(
            cfg["exchange"],
            cfg["market_type"],
            symbol,
            timeframe,
            cfg["candle_limit"],
        )
        d = indicators(raw, t["ema_fast"], t["ema_slow"], t["rsi_period"])
        if len(d) < max(35, t["ema_slow"] + 5, t["rsi_period"] + 5):
            return {
                "symbol": symbol,
                "tf": timeframe,
                "signal": "NEUTRALNY",
                "price": None,
                "adx": None,
                "rsi": None,
                "reason": "Za mało świec",
            }
        r = d.iloc[-2]
        if not all(
            pd.notna(r[x]) and np.isfinite(float(r[x]))
            for x in ["close", "ema_fast", "ema_slow", "adx", "rsi"]
        ):
            return {
                "symbol": symbol,
                "tf": timeframe,
                "signal": "NEUTRALNY",
                "price": asfloat(r["close"]),
                "adx": None,
                "rsi": None,
                "reason": "Brak danych wskaźników",
            }
        trend = r["ema_fast"] > r["ema_slow"]
        adx_ok = r["adx"] >= t["adx_threshold"]
        long_rsi_ok = t["rsi_long_min"] <= float(r["rsi"]) <= t["rsi_long_max"]
        short_rsi_ok = t["rsi_short_min"] <= float(r["rsi"]) <= t["rsi_short_max"]
        long_ok = bool(
            cfg["allow_long"]
            and trend
            and adx_ok
            and long_rsi_ok
            and r["close"] > r["ema_fast"]
        )
        short_ok = bool(
            cfg["allow_short"]
            and not trend
            and adx_ok
            and short_rsi_ok
            and r["close"] < r["ema_fast"]
        )
        return {
            "symbol": symbol,
            "tf": timeframe,
            "signal": "LONG" if long_ok else "SHORT" if short_ok else "NEUTRALNY",
            "price": float(r["close"]),
            "adx": float(r["adx"]),
            "rsi": float(r["rsi"]),
            "reason": "OK",
        }
    except Exception as exc:
        return {
            "symbol": symbol,
            "tf": timeframe,
            "signal": "BŁĄD",
            "price": None,
            "adx": None,
            "rsi": None,
            "reason": str(exc)[:180],
        }
    finally:
        gc.collect()

def trend_direction_for_symbol(cfg, symbol, timeframe="1d"):
    try:
        t = effective_tf_cfg(cfg, timeframe)
        raw = get_candles(
            cfg["exchange"],
            cfg["market_type"],
            symbol,
            timeframe,
            cfg["candle_limit"],
        )
        d = indicators(raw, t["ema_fast"], t["ema_slow"], t["rsi_period"])
        if len(d) < max(35, t["ema_slow"] + 5, t["rsi_period"] + 5):
            return None
        r = d.iloc[-2]
        if pd.isna(r["ema_fast"]) or pd.isna(r["ema_slow"]):
            return None
        if r["ema_fast"] > r["ema_slow"] and r["close"] > r["ema_fast"]:
            return "LONG"
        if r["ema_fast"] < r["ema_slow"] and r["close"] < r["ema_fast"]:
            return "SHORT"
        return None
    except Exception:
        return None
    finally:
        gc.collect()

def asfloat(value):
    try:
        number = float(value)
        return number if np.isfinite(number) else 0.0
    except (TypeError, ValueError):
        return 0.0

def balance_usdt(ex, positions=None):
    balance = ex.fetch_balance() or {}
    row = balance.get("USDT") if isinstance(balance.get("USDT"), dict) else {}
    free_map, used_map, total_map = (
        balance.get("free") or {},
        balance.get("used") or {},
        balance.get("total") or {},
    )
    def number(*values):
        for value in values:
            try:
                if value is not None and value != "":
                    n = float(value)
                    if np.isfinite(n) and n >= 0:
                        return n
            except (TypeError, ValueError):
                pass
        return None

    free = number(row.get("free"), free_map.get("USDT"))
    used = number(row.get("used"), used_map.get("USDT"))
    total = number(row.get("total"), total_map.get("USDT"))
    if free is None:
        free = 0.0
    if total is None:
        total = free + (used or 0.0)
    position_margin = sum(
        max(0.0, asfloat(p.get("initialMargin") or p.get("margin")))
        for p in (positions or [])
    )
    allocated = max(float(used or 0.0), position_margin)
    if total > 0 and free >= total - max(0.01, total * 0.001) and allocated > 0:
        free = max(0.0, total - allocated)
    return max(0.0, free), max(0.0, total)

def active_positions(ex):
    return [
        p for p in (ex.fetch_positions() or []) if abs(asfloat(p.get("contracts"))) > 0
    ]

def market_order(
    ex, symbol, side, qty, reduce_only=False, reference_price=None
):
    qty = float(ex.amount_to_precision(symbol, qty))
    if not np.isfinite(qty) or qty <= 0:
        raise ValueError("Ilość zlecenia jest nieprawidłowa.")
    if not reduce_only:
        price = asfloat(reference_price)
        if price <= 0:
            raise ValueError("Brak prawidłowej ceny do sprawdzenia wartości pozycji.")
        market = ex.market(symbol)
        notional = qty * price * (asfloat(market.get("contractSize")) or 1.0)
        if not np.isfinite(notional) or notional < MIN_ORDER_NOTIONAL_USDT:
            raise ValueError(
                f"Wartość zlecenia {notional:.4f} USDT jest poniżej minimum 10 USDT."
            )
    return ex.create_order(
        symbol,
        "market",
        side,
        qty,
        None,
        {"reduceOnly": True} if reduce_only else {},
    )

def manage_position_exits(ex, positions, cfg):
    sl_roe = max(0.1, float(cfg.get("sl_roe", 20.0)))
    closed = []
    for pos in positions:
        symbol = pos.get("symbol")
        side = str(pos.get("side") or "").lower()
        qty = abs(asfloat(pos.get("contracts")))
        pnl_value = pos.get("unrealizedPnl")
        margin_value = pos.get("initialMargin")
        if margin_value is None or asfloat(margin_value) <= 0:
            margin_value = pos.get("margin")
        margin = asfloat(margin_value)
        if (not symbol or qty <= 0 or side not in ("long", "short") or margin <= 0 or pnl_value is None):
            continue
        roe = asfloat(pnl_value) / margin * 100.0
        reason = None
        if roe <= -sl_roe:
            reason = "STOP LOSS (Ochrona kapitału)"
        else:
            current_trend = trend_direction_for_symbol(cfg, symbol, "4h")
            if current_trend:
                if (side == "long" and current_trend == "SHORT") or (side == "short" and current_trend == "LONG"):
                    if roe > 0:
                        reason = f"MAX ZYSK / ODWRÓCENIE TRENDU (ROE: {roe:.2f}%)"
        if reason is None:
            continue
        close_side = "sell" if side == "long" else "buy"
        try:
            order = market_order(ex, symbol, close_side, qty, reduce_only=True)
            msg = f"{reason}: {side.upper()} {symbol}; ROE={roe:.2f}%; order_id={order.get('id')}"
            event("TRADE", msg)
            set_pair_cooldown(symbol, reason, 600)
            closed.append(msg)
        except Exception as exc:
            event("ERROR", f"{reason}: nie udało się zamknąć {symbol}: {exc}")
    return closed

def calc_qty(ex, symbol, total_usdt, free_usdt, price, cfg, custom_usdt=None):
    price = asfloat(price)
    leverage = max(1, int(cfg.get("max_leverage", 10)))
    risk_budget = (
        float(custom_usdt)
        if custom_usdt is not None
        else min(
            max(0.0, float(cfg.get("risk_usdt", 10.0))), max(0.0, total_usdt) * 0.05
        )
    )
    sl_roe = float(cfg.get("sl_roe", 20.0))
    if price <= 0 or sl_roe <= 0 or free_usdt <= 0:
        return 0.0, 0.0
    stop_fraction = max(0.001, (sl_roe / 100.0) / leverage)
    target = min(
        risk_budget / stop_fraction,
        max(0.0, float(cfg.get("max_notional_usdt", 200.0))),
        free_usdt * leverage * 0.90,
    )
    target = max(MIN_ORDER_NOTIONAL_USDT, target)
    market = ex.market(symbol)
    contract_size = asfloat(market.get("contractSize")) or 1.0
    min_amount = asfloat(
        ((market.get("limits") or {}).get("amount") or {}).get("min")
    )
    qty = float(
        ex.amount_to_precision(symbol, target / (price * contract_size))
    )
    if min_amount > qty:
        qty = float(ex.amount_to_precision(symbol, min_amount))
    notional = qty * price * contract_size
    if not np.isfinite(qty) or qty <= 0 or notional < MIN_ORDER_NOTIONAL_USDT:
        return 0.0, 0.0
    return qty, notional

def ranked_symbols(ex, limit_count):
    now = time.time()
    limit_count = max(1, int(limit_count))
    default_type = ex.options.get("defaultType", "")
    cache_key = f"ranked_symbols:{ex.id}:{default_type}:{limit_count}"
    cached = st.session_state.get(cache_key)
    if cached and now - cached.get("ts", 0) < 180:
        return cached["ranked"]
    markets = ex.load_markets()
    candidates = [
        s
        for s, m in markets.items()
        if m.get("active") is not False
        and m.get("quote") == "USDT"
        and m.get("linear")
        and m.get("swap", False)
    ]
    ranked = []
    for offset in range(0, len(candidates), 40):
        batch = candidates[offset : offset + 40]
        tickers = ex.fetch_tickers(batch)
        for symbol in batch:
            ticker = tickers.get(symbol) or {}
            volume = asfloat(ticker.get("quoteVolume"))
            if volume <= 0:
                volume = asfloat(ticker.get("baseVolume")) * asfloat(
                    ticker.get("last")
                )
            if volume > 0:
                ranked.append((symbol, volume))
    ranked.sort(key=lambda x: x[1], reverse=True)
    ranked = ranked[:limit_count]
    st.session_state[cache_key] = {"ts": now, "ranked": ranked}
    gc.collect()
    return ranked

# -------------------- Wątek Tła (Background Worker 24/7) --------------------
def background_trading_worker():
    while True:
        try:
            cfg = load_cfg()
            if cfg.get("auto_trade") and not cfg.get("paper_mode"):
                with db() as con:
                    creds = con.execute("SELECT user_id, exchange, api_key, secret, password FROM user_credentials WHERE api_key != '' AND secret != '' LIMIT 1").fetchone()
                if creds:
                    ex_id = creds["exchange"]
                    api_key = creds["api_key"]
                    secret = creds["secret"]
                    passphrase = creds["password"]
                    
                    ex = exchange_client(ex_id, api_key, secret, passphrase, cfg["market_type"])
                    active = active_positions(ex)
                    
                    # Zarządzanie wyjściami
                    manage_position_exits(ex, active, cfg)
                    active = active_positions(ex)
                    
                    max_pos = int(cfg.get("max_positions", 3))
                    if len(active) < max_pos:
                        free, total = balance_usdt(ex, active)
                        ranked = ranked_symbols(ex, int(cfg.get("scan_limit_count", 30)))
                        symbols = [x[0] for x in ranked]
                        volume_map = dict(ranked)
                        tfs = [tf for tf in cfg.get("timeframes", ["4h", "1d"]) if tf in TF_OPTIONS]
                        
                        all_signals = []
                        for symbol in symbols:
                            for tf in tfs:
                                res = signal_for_symbol(cfg, symbol, tf)
                                res["volume_24h_usdt"] = volume_map.get(symbol, 0.0)
                                adx_val = res.get("adx") or 0.0
                                res["score"] = adx_val * np.log1p(res["volume_24h_usdt"])
                                all_signals.append(res)
                        
                        valid_signals = [s for s in all_signals if s["signal"] in ("LONG", "SHORT")]
                        valid_signals.sort(key=lambda x: x.get("score", 0), reverse=True)
                        
                        for item in valid_signals:
                            if len(active) >= max_pos:
                                break
                            sym = item["symbol"]
                            sig = item["signal"]
                            price = item["price"]
                            
                            if any(p.get("symbol") == sym for p in active):
                                continue
                            if pair_cooldown_remaining(sym) > 0:
                                continue
                            
                            qty, notional = calc_qty(ex, sym, total, free, price, cfg)
                            if qty > 0:
                                try:
                                    ex.set_leverage(int(cfg["max_leverage"]), sym)
                                except Exception:
                                    pass
                                order_side = "buy" if sig == "LONG" else "sell"
                                ord_res = market_order(ex, sym, order_side, qty, reference_price=price)
                                msg = f"AUTO-TRADE (BG): Otwarto {sig} na {sym} qty={qty} (ID: {ord_res.get('id')})"
                                event("TRADE", msg)
                                set_pair_cooldown(sym, "AUTO_OPEN", cfg.get("cooldown_seconds", 300))
                                active = active_positions(ex)
        except Exception as exc:
            logging.error(f"Błąd w tle (Background Worker): {exc}")
        time.sleep(max(15, int(load_cfg().get("refresh_seconds", 30))))

if "bg_worker_started" not in st.session_state:
    st.session_state["bg_worker_started"] = True
    t = threading.Thread(target=background_trading_worker, daemon=True)
    t.start()

# -------------------- Sesja / logowanie --------------------

for key, default in {
    "authenticated": False,
    "logged_in": False,
    "username": "",
    "user_id": None,
    "stripe_paid": 0,
    "user_email": "",
}.items():
    if key not in st.session_state:
        st.session_state[key] = default

if "session_started_at" not in st.session_state:
    st.session_state["session_started_at"] = time.time()

def is_user_admin():
    return (
        str(st.session_state.get("user_email", "")).strip().lower() in ADMIN_EMAILS
        or str(st.session_state.get("username", "")).strip().lower() == "admin"
    )

def is_user_paid():
    return bool(st.session_state.get("stripe_paid", 0)) or is_user_admin()

if st.query_params.get("success") == "true":
    st.info(
        "Powrót z płatności. Administrator potwierdzi płatność przed aktywacją dostępu."
    )
    st.query_params.clear()

if not st.session_state["authenticated"]:
    st.markdown(
        '<div class="brand" style="text-align:center">Bitget-SaaS</div><div style="text-align:center">AUTONOMICZNY SYSTEM TRANSAKCYJNY</div>',
        unsafe_allow_html=True,
    )
    login_tab, reg_tab = st.tabs(["Zaloguj się", "Załóż konto i subskrypcję"])
    with login_tab:
        with st.form("login_form"):
            login_name = st.text_input("Nazwa użytkownika / e-mail")
            login_pass = st.text_input("Hasło", type="password")
            submit_login = st.form_submit_button("ZALOGUJ SIĘ", use_container_width=True)
            if submit_login:
                with db() as con:
                    row = con.execute(
                        "SELECT id,password,stripe_paid,email,username FROM users WHERE username=? OR email=?",
                        (login_name.strip(), login_name.strip().lower()),
                    ).fetchone()
                valid, legacy = (
                    verify_password(row["password"], login_pass)
                    if row
                    else (False, False)
                )
                if row and valid:
                    if legacy:
                        with db() as con:
                            con.execute(
                                "UPDATE users SET password=? WHERE id=?",
                                (password_hash(login_pass), row["id"]),
                            )
                            con.commit()
                    st.session_state.update(
                        authenticated=True,
                        logged_in=True,
                        user_id=row["id"],
                        stripe_paid=row["stripe_paid"],
                        user_email=(row["email"] or "").lower(),
                        username=row["username"],
                        session_started_at=time.time(),
                    )
                    st.rerun()
                else:
                    st.error("Nieprawidłowy login lub hasło.")
    with reg_tab:
        st.subheader("Rejestracja - 49 PLN / miesiąc")
        with st.form("reg_form"):
            reg_user = st.text_input("Nazwa użytkownika")
            reg_email = st.text_input("Adres e-mail")
            reg_pass = st.text_input("Hasło", type="password")
            reg_plan = st.selectbox(
                "Subskrypcja", ["Pro Trader (49 PLN / miesiąc)", "VIP SaaS (Roczny)"]
            )
            submit_reg = st.form_submit_button(
                "ZAREJESTRUJ SIĘ", use_container_width=True
            )
            if submit_reg:
                if not reg_user.strip() or not reg_pass.strip() or not reg_email.strip():
                    st.error("Uzupełnij login, e-mail i hasło.")
                elif "@" not in reg_email or "." not in reg_email.rsplit("@", 1)[-1]:
                    st.error("Podaj prawidłowy adres e-mail.")
                else:
                    try:
                        with db() as con:
                            con.execute(
                                "INSERT INTO users(username,password,subscription,stripe_paid,email) VALUES(?,?,?,0,?)",
                                (
                                    reg_user.strip(),
                                    password_hash(reg_pass),
                                    reg_plan,
                                    reg_email.strip().lower(),
                                ),
                            )
                            con.commit()
                        st.success(
                            "Konto utworzone. Zaloguj się, a następnie opłać subskrypcję."
                        )
                    except sqlite3.IntegrityError:
                        st.error("Taki login lub adres e-mail już istnieje.")
    st.stop()

cfg = load_cfg()
current_user_id = st.session_state.get("user_id")
ex_id, api_key_saved, secret_saved, passphrase_saved = load_creds(current_user_id)

with st.sidebar:
    st.markdown(
        f'<div class="brand">Bitget-SaaS</div><div>Witaj, {st.session_state["username"]}</div>',
        unsafe_allow_html=True,
    )
    pages = [
        "Automatyczny Skaner i Auto-Handel",
        "Ustawienia Strategii",
        "Połączenie API",
        "Dziennik",
        "Regulamin i Instrukcja",
    ]
    if is_user_admin():
        pages.append("Panel Administratora")
    page = st.radio("NAWIGACJA", pages)
    st.divider()
    if is_user_admin():
        st.success("Administrator - pełny dostęp")
    if is_user_paid():
        st.success("Subskrypcja aktywna")
    else:
        st.warning("Subskrypcja nieopłacona")
        try:
            st.link_button(
                "OPŁAĆ SUBSKRYPCJĘ (49 PLN)",
                create_stripe_checkout_url(),
                use_container_width=True,
            )
        except Exception as exc:
            st.error(f"Błąd linku Stripe: {exc}")
        st.caption("Po płatności administrator potwierdza transakcję.")
    if st.button("Wyloguj", use_container_width=True):
        for key, default in [
            ("authenticated", False),
            ("logged_in", False),
            ("username", ""),
            ("user_id", None),
            ("stripe_paid", 0),
            ("user_email", ""),
        ]:
            st.session_state[key] = default
        st.rerun()
    if st.button("Wyczyść cache danych", use_container_width=True):
       get_candles.clear()
       st.cache_data.clear()
       st.cache_resource.clear()
       st.success("Cache wyczyszczony. Odśwież stronę.")

st.markdown(
    '<div class="brand">Bitget-SaaS Futures</div><div>AUTONOMICZNY SYSTEM TRANSAKCYJNY</div>',
    unsafe_allow_html=True
)

 

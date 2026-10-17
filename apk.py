import gc
from contextlib import contextmanager
import hashlib
import hmac
import json
import logging
import os
import secrets
import sqlite3
import time
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import streamlit as st

try:
    import ccxt
except ImportError:
    ccxt = None

try:
    from cryptography.fernet import Fernet, InvalidToken
except ImportError:
    Fernet = None
    InvalidToken = Exception

st.set_page_config(page_title="Bitget-SaaS Futures", page_icon="📈", layout="wide")

APP_DIR = Path(__file__).resolve().parent
DB_PATH = Path(os.getenv("BITGET_SAAS_DB", str(APP_DIR / "bitget_saas.db")))
LOG_PATH = APP_DIR / "trading.log"
ENCRYPTION_KEY = os.getenv("BITGET_SAAS_ENCRYPTION_KEY", "").strip()

logging.basicConfig(
    filename=str(LOG_PATH),
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)

STRIPE_CHECKOUT_URL = os.getenv(
    "STRIPE_CHECKOUT_URL",
    "https://buy.stripe.com/8x2dRa4CbdaXfSAf6V3oA03",
)
ADMIN_EMAILS = {
    x.strip().lower()
    for x in os.getenv("BITGET_SAAS_ADMIN_EMAILS", "marekja57@wp.pl,admin@bot-bitget.pl").split(",")
    if x.strip()
}
TF_OPTIONS = ["1m", "3m", "5m", "15m", "30m", "1h", "2h", "4h", "1d"]
EXCHANGE_OPTIONS = ["bitget", "binanceusdm", "bybit", "okx"]
MIN_ORDER_NOTIONAL_USDT = 10.0

def get_dynamic_default_tf_settings():
    return {
        tf: {
            "ema_fast": 9,
            "ema_slow": 21,
            "adx_threshold": 20.0,
            "rsi_period": 14,
            "rsi_long_min": 50.0,
            "rsi_long_max": 65.0,
            "rsi_short_min": 35.0,
            "rsi_short_max": 50.0,
            "rsi_min": 25.0,
            "rsi_max": 75.0,
        }
        for tf in TF_OPTIONS
    }

DEFAULTS = {
    "exchange": "bitget",
    "market_type": "swap",
    "candle_limit": 150,
    "refresh_seconds": 30,
    "risk_usdt": 10.0,
    "max_positions": 3,
    "max_leverage": 10,
    "sl_roe": 30.0,
    "tp_roe": 60.0,
    "enable_roe": True,
    "timeframes": ["4h", "1d"],
    "tf_settings": get_dynamic_default_tf_settings(),
    "auto_refresh": True,
    "auto_trade": False,
    "paper_mode": True,
    "max_notional_usdt": 200.0,
    "cooldown_seconds": 900,
    "allow_short": True,
    "allow_long": True,
    "scan_limit_count": 10,
    "indicator_multiplier": 100,
}

st.markdown(
    """<style> 
    .stApp{background:radial-gradient(ellipse at 40% -20%,#103e78 0%,#071a36 42%,#050e20 100%);color:#eaf3ff} 
    [data-testid="stHeader"]{background:rgba(3,12,29,.96)} 
    [data-testid="stAppViewContainer"] .main .block-container{padding-top:2rem;max-width:1600px} 
    [data-testid="stSidebar"]{background:linear-gradient(180deg,#06152d,#081f42)} 
    .brand{font-weight:900;font-size:30px;color:#eaf5ff;margin:.5rem 0} 
    .metric-card{border:1px solid #d8ad52;border-radius:14px;padding:18px;min-height:130px;display:flex;flex-direction:column;justify-content:center;background:linear-gradient(145deg,#1b2b44,#061225);overflow:hidden} 
    .metric-label{color:#b9c9df;font-size:12px;font-weight:700;letter-spacing:1px;text-transform:uppercase;margin-bottom:10px} 
    .metric-value{color:#fff2c7;font-size:clamp(20px,1.8vw,29px);font-weight:850;line-height:1.2;overflow-wrap:anywhere} 
    .metric-note{color:#a9bdd7;font-size:12px;margin-top:8px} 
    </style>""",
    unsafe_allow_html=True,
)

# -------------------- Baza danych --------------------

@contextmanager
def db():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(DB_PATH, timeout=20)
    con.row_factory = sqlite3.Row
    try:
        con.execute("PRAGMA busy_timeout=20000")
        con.execute("PRAGMA journal_mode=WAL")
        con.execute("CREATE TABLE IF NOT EXISTS settings(k TEXT PRIMARY KEY,v TEXT NOT NULL)")
        con.execute(
            """CREATE TABLE IF NOT EXISTS user_credentials(user_id INTEGER PRIMARY KEY, exchange TEXT, api_key TEXT, secret TEXT, password TEXT)"""
        )
        con.execute(
            """CREATE TABLE IF NOT EXISTS events(id INTEGER PRIMARY KEY AUTOINCREMENT,ts TEXT,level TEXT,message TEXT)"""
        )
        con.execute(
            """CREATE TABLE IF NOT EXISTS pair_cooldowns(symbol TEXT PRIMARY KEY, closed_at REAL NOT NULL, reason TEXT NOT NULL)"""
        )
        con.execute(
            """CREATE TABLE IF NOT EXISTS users(id INTEGER PRIMARY KEY AUTOINCREMENT,username TEXT UNIQUE NOT NULL,password TEXT NOT NULL, subscription TEXT,stripe_paid INTEGER NOT NULL DEFAULT 0,email TEXT UNIQUE)"""
        )
        con.commit()
        yield con
        con.commit()
    except Exception:
        con.rollback()
        raise
    finally:
        con.close()

def password_hash(password, salt=None):
    salt = salt or secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt.encode("utf-8"), 240000).hex()
    return f"pbkdf2${salt}${digest}"

def verify_password(stored, password):
    if not stored:
        return False, False
    try:
        scheme, salt, digest = stored.split("$", 2)
        if scheme == "pbkdf2":
            check = hashlib.pbkdf2_hmac(
                "sha256", password.encode("utf-8"), salt.encode("utf-8"), 240000
            ).hex()
            return hmac.compare_digest(check, digest), False
    except (ValueError, AttributeError):
        pass
    return hmac.compare_digest(str(stored), str(password)), True

def _fernet():
    if Fernet is None:
        raise RuntimeError("Do szyfrowania kluczy API zainstaluj cryptography: pip install cryptography")
    if not ENCRYPTION_KEY:
        raise RuntimeError(
            "Brak BITGET_SAAS_ENCRYPTION_KEY. Ustaw klucz Fernet w zmiennej środowiskowej przed zapisaniem API."
        )
    try:
        return Fernet(ENCRYPTION_KEY.encode("ascii"))
    except Exception as exc:
        raise RuntimeError("BITGET_SAAS_ENCRYPTION_KEY nie jest prawidłowym kluczem Fernet.") from exc

def encrypt_secret(value):
    if not value:
        return ""
    return _fernet().encrypt(value.encode("utf-8")).decode("ascii")

def decrypt_secret(value):
    if not value:
        return ""
    try:
        return _fernet().decrypt(value.encode("ascii")).decode("utf-8")
    except Exception as exc:
        raise RuntimeError(
            "Nie można odszyfrować zapisanych kluczy API. Ustaw właściwy klucz BITGET_SAAS_ENCRYPTION_KEY."
        ) from exc

def load_cfg():
    cfg = json.loads(json.dumps(DEFAULTS))
    try:
        with db() as con:
            row = con.execute("SELECT v FROM settings WHERE k='main'").fetchone()
        if row:
            stored = json.loads(row["v"])
            if isinstance(stored, dict):
                cfg.update(stored)
        merged = get_dynamic_default_tf_settings()
        for tf, vals in (cfg.get("tf_settings") or {}).items():
            if tf in merged and isinstance(vals, dict):
                merged[tf].update(vals)
        cfg["tf_settings"] = merged
        cfg["timeframes"] = [tf for tf in cfg.get("timeframes", ["4h", "1d"]) if tf in TF_OPTIONS] or ["4h", "1d"]
        cfg["exchange"] = cfg.get("exchange") if cfg.get("exchange") in EXCHANGE_OPTIONS else "bitget"
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
    try:
        with db() as con:
            con.execute(
                "INSERT INTO events(ts,level,message) VALUES(?,?,?)",
                (datetime.now(timezone.utc).isoformat(), str(level).upper(), message),
            )
            con.commit()
    except Exception:
        logging.exception("Nie udało się zapisać zdarzenia")

def set_pair_cooldown(symbol, reason, seconds=1800):
    if not symbol:
        return
    with db() as con:
        con.execute(
            """INSERT INTO pair_cooldowns(symbol,closed_at,reason) VALUES(?,?,?) ON CONFLICT(symbol) DO UPDATE SET closed_at=excluded.closed_at,reason=excluded.reason""",
            (str(symbol), time.time(), str(reason)),
        )
        con.commit()

def pair_cooldown_remaining(symbol, seconds=1800):
    try:
        with db() as con:
            row = con.execute(
                "SELECT closed_at FROM pair_cooldowns WHERE symbol=?", (str(symbol),)
            ).fetchone()
            if not row:
                return 0
            remaining = max(0, int(seconds - (time.time() - float(row["closed_at"]))))
            if remaining == 0:
                con.execute("DELETE FROM pair_cooldowns WHERE symbol=?", (str(symbol),))
                con.commit()
            return remaining
    except Exception:
        logging.exception("Nie udało się sprawdzić blokady pary %s", symbol)
        return int(seconds)

def load_creds(user_id):
    if not user_id:
        return "bitget", "", "", ""
    with db() as con:
        row = con.execute(
            "SELECT exchange,api_key,secret,password FROM user_credentials WHERE user_id=?",
            (int(user_id),),
        ).fetchone()
    if not row:
        return "bitget", "", "", ""
    try:
        return row["exchange"] or "bitget", decrypt_secret(row["api_key"]), decrypt_secret(row["secret"]), decrypt_secret(row["password"])
    except Exception:
        logging.exception("Nie udało się odczytać zaszyfrowanych kluczy API dla użytkownika %s", user_id)
        return row["exchange"] or "bitget", "", "", ""

def save_creds(user_id, exchange, api_key, secret, passphrase):
    if not user_id:
        raise ValueError("Użytkownik nie jest zalogowany.")
    encrypted = (encrypt_secret(api_key), encrypt_secret(secret), encrypt_secret(passphrase))
    with db() as con:
        con.execute(
            """INSERT INTO user_credentials(user_id,exchange,api_key,secret,password) VALUES(?,?,?,?,?) ON CONFLICT(user_id) DO UPDATE SET exchange=excluded.exchange,api_key=excluded.api_key,secret=excluded.secret,password=excluded.password""",
            (int(user_id), exchange, *encrypted),
        )
        con.commit()

def create_stripe_checkout_url():
    if not STRIPE_CHECKOUT_URL.startswith("https://buy.stripe.com/"):
        raise ValueError("Ustaw prawidłowy link płatności Stripe.")
    return STRIPE_CHECKOUT_URL

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

@st.cache_data(ttl=30, max_entries=300, show_spinner=False)
def get_candles(ex_id, market_type, symbol, timeframe, limit):
    ex = exchange_client(ex_id, "", "", "", market_type)
    rows = ex.fetch_ohlcv(symbol, timeframe=timeframe, limit=int(limit))
    if not rows:
        return pd.DataFrame(columns=["timestamp", "open", "high", "low", "close", "volume"])
    return pd.DataFrame(rows, columns=["timestamp", "open", "high", "low", "close", "volume"])

def indicators(df, fast, slow, rsi_period=14):
    d = df.copy()
    for col in ["open", "high", "low", "close", "volume"]:
        d[col] = pd.to_numeric(d[col], errors="coerce")
    d = d.dropna(subset=["high", "low", "close"]).reset_index(drop=True)
    if d.empty:
        return d
    fast, slow = max(2, int(fast)), max(3, int(slow))
    d["ema_fast"] = d["close"].ewm(span=fast, adjust=False).mean()
    d["ema_slow"] = d["close"].ewm(span=slow, adjust=False).mean()
    delta = d["close"].diff()
    period = max(2, int(rsi_period))
    gain = delta.clip(lower=0).ewm(alpha=1 / period, adjust=False).mean()
    loss = (-delta.clip(upper=0)).ewm(alpha=1 / period, adjust=False).mean()
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
    defaults = get_dynamic_default_tf_settings()
    base = cfg.get("tf_settings", {}).get(tf, defaults.get(tf, defaults["1h"]))
    mult = float(cfg.get("indicator_multiplier", 100)) / 100
    fast = max(2, int(round(float(base.get("ema_fast", 9)))))
    slow = max(fast + 1, int(round(float(base.get("ema_slow", 21)))))
    return {
        "ema_fast": fast,
        "ema_slow": slow,
        "adx_threshold": max(2.0, min(90.0, float(base.get("adx_threshold", 20)) * mult)),
        "rsi_period": max(2, min(100, int(base.get("rsi_period", 14)))),
        "rsi_long_min": max(0.0, min(100.0, float(base.get("rsi_long_min", 50)))),
        "rsi_long_max": max(0.0, min(100.0, float(base.get("rsi_long_max", 65)))),
        "rsi_short_min": max(0.0, min(100.0, float(base.get("rsi_short_min", 35)))),
        "rsi_short_max": max(0.0, min(100.0, float(base.get("rsi_short_max", 50)))),
        "rsi_min": max(0.0, min(100.0, float(base.get("rsi_min", 25)))),
        "rsi_max": max(0.0, min(100.0, float(base.get("rsi_max", 75)))),
    }

def asfloat(value, default=0.0):
    try:
        number = float(value)
        return number if np.isfinite(number) else default
    except (TypeError, ValueError):
        return default

def signal_for_symbol(cfg, symbol, timeframe):
    try:
        t = effective_tf_cfg(cfg, timeframe)
        raw = get_candles(cfg["exchange"], cfg["market_type"], symbol, timeframe, cfg["candle_limit"])
        d = indicators(raw, t["ema_fast"], t["ema_slow"], t["rsi_period"])
        if len(d) < max(35, t["ema_slow"] + 5, t["rsi_period"] + 5):
            return {"symbol": symbol, "tf": timeframe, "signal": "NEUTRALNY", "price": None, "adx": None, "rsi": None, "reason": "Za mało świec"}
        r = d.iloc[-2]
        fields = ["close", "ema_fast", "ema_slow", "adx", "rsi"]
        if not all(pd.notna(r[x]) and np.isfinite(float(r[x])) for x in fields):
            return {"symbol": symbol, "tf": timeframe, "signal": "NEUTRALNY", "price": asfloat(r["close"]), "adx": None, "rsi": None, "reason": "Brak danych wskaźników"}
        trend_up = r["ema_fast"] > r["ema_slow"]
        trend_down = r["ema_fast"] < r["ema_slow"]
        adx_ok = r["adx"] >= t["adx_threshold"]
        rsi = float(r["rsi"])
        
        long_ok = bool(
            cfg["allow_long"] 
            and trend_up 
            and adx_ok 
            and t["rsi_long_min"] <= rsi <= t["rsi_long_max"] 
            and r["close"] >= r["ema_fast"]
        )
        short_ok = bool(
            cfg["allow_short"] 
            and trend_down 
            and adx_ok 
            and t["rsi_short_min"] <= rsi <= t["rsi_short_max"] 
            and r["close"] <= r["ema_fast"]
        )
        return {
            "symbol": symbol, "tf": timeframe,
            "signal": "LONG" if long_ok else "SHORT" if short_ok else "NEUTRALNY",
            "price": float(r["close"]), "adx": float(r["adx"]), "rsi": rsi, "reason": "OK",
        }
    except Exception as exc:
        logging.exception("Błąd sygnału %s %s", symbol, timeframe)
        return {"symbol": symbol, "tf": timeframe, "signal": "BŁĄD", "price": None, "adx": None, "rsi": None, "reason": str(exc)[:180]}
    finally:
        gc.collect()

def balance_usdt(ex, positions=None):
    balance = ex.fetch_balance() or {}
    row = balance.get("USDT") if isinstance(balance.get("USDT"), dict) else {}
    free_map, used_map, total_map = balance.get("free") or {}, balance.get("used") or {}, balance.get("total") or {}

    def number(*values):
        for value in values:
            if value is None or value == "":
                continue
            n = asfloat(value, -1)
            if n >= 0:
                return n
        return None

    free = number(row.get("free"), free_map.get("USDT"))
    used = number(row.get("used"), used_map.get("USDT"))
    total = number(row.get("total"), total_map.get("USDT"))
    free = 0.0 if free is None else free
    if total is None:
        total = free + (used or 0.0)
    return max(0.0, free), max(0.0, total)

def active_positions(ex):
    return [p for p in (ex.fetch_positions() or []) if abs(asfloat(p.get("contracts"))) > 0]

def market_order(ex, symbol, side, qty, reduce_only=False, reference_price=None):
    qty = float(ex.amount_to_precision(symbol, qty))
    if not np.isfinite(qty) or qty <= 0:
        raise ValueError("Ilość zlecenia jest nieprawidłowa.")
    if side not in ("buy", "sell"):
        raise ValueError("Nieprawidłowa strona zlecenia.")
    if not reduce_only:
        price = asfloat(reference_price)
        if price <= 0:
            raise ValueError("Brak prawidłowej ceny do sprawdzenia wartości pozycji.")
        market = ex.market(symbol)
        contract_size = asfloat(market.get("contractSize"), 1.0) or 1.0
        notional = qty * price * contract_size
        limits = market.get("limits") or {}
        minimum = asfloat((limits.get("cost") or {}).get("min"), MIN_ORDER_NOTIONAL_USDT)
        minimum = max(MIN_ORDER_NOTIONAL_USDT, minimum)
        if not np.isfinite(notional) or notional < minimum:
            raise ValueError(f"Wartość zlecenia {notional:.4f} USDT jest poniżej minimum {minimum:.2f} USDT.")
    params = {"reduceOnly": True} if reduce_only else {}
    return ex.create_order(symbol, "market", side, qty, None, params)

def manage_position_exits(ex, positions, cfg):
    closed = []
    if not cfg.get("enable_roe", True):
        return closed
    sl_roe = max(1.0, float(cfg.get("sl_roe", 30)))
    tp_roe = max(1.0, float(cfg.get("tp_roe", 60)))
    for pos in positions:
        symbol = pos.get("symbol")
        side = str(pos.get("side") or "").lower()
        qty = abs(asfloat(pos.get("contracts")))
        if not symbol or qty <= 0 or side not in ("long", "short"):
            continue
        entry = asfloat(pos.get("entryPrice"))
        mark = asfloat(pos.get("markPrice") or pos.get("lastPrice") or entry)
        leverage = max(1.0, asfloat(pos.get("leverage"), cfg.get("max_leverage", 10)))
        if entry <= 0 or mark <= 0:
            margin = asfloat(pos.get("initialMargin") or pos.get("margin"))
            pnl = asfloat(pos.get("unrealizedPnl"))
            if margin <= 0:
                continue
            roe = pnl / margin * 100
        else:
            roe = ((mark - entry) / entry if side == "long" else (entry - mark) / entry) * leverage * 100
        reason = f"STOP LOSS (ROE: {roe:.2f}%)" if roe <= -sl_roe else (
            f"TAKE PROFIT (ROE: {roe:.2f}%)" if roe >= tp_roe else None
        )
        if not reason:
            continue
        try:
            order = market_order(ex, symbol, "sell" if side == "long" else "buy", qty, reduce_only=True)
            msg = f"{reason}: {side.upper()} {symbol}; order_id={order.get('id')}"
            event("TRADE", msg)
            set_pair_cooldown(symbol, reason, int(cfg.get("cooldown_seconds", 900)))
            closed.append(msg)
        except Exception as exc:
            event("ERROR", f"{reason}: nie udało się zamknąć {symbol}: {exc}")
    return closed

def calc_qty(ex, symbol, total_usdt, free_usdt, price, cfg, custom_usdt=None):
    price = asfloat(price)
    leverage = max(1, int(cfg.get("max_leverage", 10)))
    if custom_usdt is None:
        risk_budget = min(max(0.0, float(cfg.get("risk_usdt", 10))), max(0.0, total_usdt) * 0.05)
    else:
        risk_budget = max(0.0, float(custom_usdt))
    sl_roe = max(1.0, float(cfg.get("sl_roe", 30)))
    if price <= 0 or free_usdt <= 0 or risk_budget <= 0:
        return 0.0, 0.0
    stop_fraction = max(0.001, (sl_roe / 100.0) / leverage)
    target = min(
        risk_budget / stop_fraction,
        max(0.0, float(cfg.get("max_notional_usdt", 200))),
        free_usdt * leverage * 0.90,
    )
    if target < MIN_ORDER_NOTIONAL_USDT:
        return 0.0, 0.0
    market = ex.market(symbol)
    contract_size = asfloat(market.get("contractSize"), 1.0) or 1.0
    min_amount = asfloat(((market.get("limits") or {}).get("amount") or {}).get("min"))
    qty = float(ex.amount_to_precision(symbol, target / (price * contract_size)))
    if min_amount > qty:
        qty = float(ex.amount_to_precision(symbol, min_amount))
    notional = qty * price * contract_size
    if not np.isfinite(qty) or qty <= 0 or notional < MIN_ORDER_NOTIONAL_USDT or notional > target * 1.001:
        return 0.0, 0.0
    return qty, notional

def ranked_symbols(ex, limit_count):
    now = time.time()
    limit_count = max(1, min(200, int(limit_count)))
    cache_key = f"ranked_symbols:{ex.id}:{ex.options.get('defaultType', '')}:{limit_count}"
    cached = st.session_state.get(cache_key)
    if cached and now - cached.get("ts", 0) < 180:
        return cached["ranked"]
    markets = ex.load_markets()
    candidates = [
        symbol for symbol, market in markets.items()
        if market.get("active") is not False and market.get("quote") == "USDT"
        and market.get("linear") and market.get("swap", False)
    ]
    ranked = []
    for offset in range(0, len(candidates), 40):
        batch = candidates[offset:offset + 40]
        try:
            tickers = ex.fetch_tickers(batch)
        except Exception:
            logging.exception("Nie udało się pobrać tickerów")
            continue
        for symbol in batch:
            ticker = tickers.get(symbol) or {}
            volume = asfloat(ticker.get("quoteVolume"))
            if volume <= 0:
                volume = asfloat(ticker.get("baseVolume")) * asfloat(ticker.get("last"))
            if volume > 0:
                ranked.append((symbol, volume))
    ranked.sort(key=lambda item: item[1], reverse=True)
    ranked = ranked[:limit_count]
    st.session_state[cache_key] = {"ts": now, "ranked": ranked}
    return ranked

# -------------------- Sesja / logowanie --------------------

for key, default in {
    "authenticated": False, "logged_in": False, "username": "",
    "user_id": None, "stripe_paid": 0, "user_email": "",
}.items():
    if key not in st.session_state:
        st.session_state[key] = default
if "session_started_at" not in st.session_state:
    st.session_state["session_started_at"] = time.time()

def is_user_admin():
    email = str(st.session_state.get("user_email", "")).strip().lower()
    return bool(email) and email in ADMIN_EMAILS

def is_user_paid():
    return bool(st.session_state.get("stripe_paid", 0)) or is_user_admin()

if st.query_params.get("success") == "true":
    st.info("Powrót z płatności nie potwierdza zapłaty. Dostęp aktywuje administrator po sprawdzeniu transakcji.")
    st.query_params.clear()

if not st.session_state["authenticated"]:
    st.markdown('<div class="brand" style="text-align:center">Bitget-SaaS</div><div style="text-align:center">AUTONOMICZNY SYSTEM TRANSAKCYJNY</div>', unsafe_allow_html=True)
    login_tab, reg_tab = st.tabs(["Zaloguj się", "Załóż konto i subskrypcję"])
    with login_tab:
        with st.form("login_form"):
            login_name = st.text_input("Nazwa użytkownika / e-mail")
            login_pass = st.text_input("Hasło", type="password")
            submit_login = st.form_submit_button("ZALOGUJ SIĘ", use_container_width=True)
        if submit_login:
            with db() as con:
                row = con.execute(
                    "SELECT id,password,stripe_paid,email,username FROM users WHERE username=? COLLATE NOCASE OR email=?",
                    (login_name.strip(), login_name.strip().lower()),
                ).fetchone()
            valid, legacy = verify_password(row["password"], login_pass) if row else (False, False)
            if row and valid:
                if legacy:
                    with db() as con:
                        con.execute("UPDATE users SET password=? WHERE id=?", (password_hash(login_pass), row["id"]))
                        con.commit()
                st.session_state.update(
                    authenticated=True, logged_in=True, user_id=row["id"],
                    stripe_paid=row["stripe_paid"], user_email=(row["email"] or "").lower(),
                    username=row["username"], session_started_at=time.time(),
                )
                st.rerun()
            else:
                st.error("Nieprawidłowy login lub hasło.")
    with reg_tab:
        st.subheader("Rejestracja — 49 PLN / miesiąc")
        with st.form("reg_form"):
            reg_user = st.text_input("Nazwa użytkownika")
            reg_email = st.text_input("Adres e-mail")
            reg_pass = st.text_input("Hasło", type="password")
            reg_plan = st.selectbox("Subskrypcja", ["Pro Trader (49 PLN / miesiąc)", "VIP SaaS (Roczny)"])
            submit_reg = st.form_submit_button("ZAREJESTRUJ SIĘ", use_container_width=True)
        if submit_reg:
            if len(reg_user.strip()) < 3 or len(reg_pass) < 10 or not reg_email.strip():
                st.error("Podaj login (min. 3 znaki), e-mail i hasło (min. 10 znaków).")
            elif "@" not in reg_email or "." not in reg_email.rsplit("@", 1)[-1]:
                st.error("Podaj prawidłowy adres e-mail.")
            else:
                try:
                    with db() as con:
                        con.execute(
                            "INSERT INTO users(username,password,subscription,stripe_paid,email) VALUES(?,?,?,0,?)",
                            (reg_user.strip(), password_hash(reg_pass), reg_plan, reg_email.strip().lower()),
                        )
                        con.commit()
                    st.success("Konto utworzone. Zaloguj się, a następnie opłać subskrypcję.")
                except sqlite3.IntegrityError:
                    st.error("Taki login lub adres e-mail już istnieje.")
    st.stop()

# Synchronizacja konfiguracji w sesji
if "cfg" not in st.session_state:
    st.session_state["cfg"] = load_cfg()
cfg = st.session_state["cfg"]

current_user_id = st.session_state.get("user_id")
ex_id, api_key_saved, secret_saved, passphrase_saved = load_creds(current_user_id)

with st.sidebar:
    st.markdown(f'<div class="brand">Bitget-SaaS</div><div>Witaj, {st.session_state["username"]}</div>', unsafe_allow_html=True)
    pages = ["Automatyczny Skaner i Auto-Handel", "Ustawienia Strategii", "Połączenie API", "Dziennik", "Regulamin i Instrukcja"]
    if is_user_admin():
        pages.append("Panel Administratora")
    page = st.radio("NAWIGACJA", pages)
    st.divider()
    if is_user_admin():
        st.success("Administrator — pełny dostęp")
    if is_user_paid():
        st.success("Subskrypcja aktywna")
    else:
        st.warning("Subskrypcja nieopłacona")
        try:
            st.link_button("OPŁAĆ SUBSKRYPCJĘ (49 PLN)", create_stripe_checkout_url(), use_container_width=True)
        except Exception as exc:
            st.error(f"Błąd linku Stripe: {exc}")
        st.caption("Po płatności administrator potwierdza transakcję.")
    if st.button("Wyloguj", use_container_width=True):
        for key, value in [
            ("authenticated", False), ("logged_in", False), ("username", ""),
            ("user_id", None), ("stripe_paid", 0), ("user_email", ""),
        ]:
            st.session_state[key] = value
        st.rerun()
    if st.button("Wyczyść cache danych", use_container_width=True):
        get_candles.clear()
        exchange_client.clear()
        st.cache_data.clear()
        st.success("Cache wyczyszczony.")
    st.markdown('<div class="brand">Bitget-SaaS Futures</div><div>AUTONOMICZNY SYSTEM TRANSAKCYJNY</div>', unsafe_allow_html=True)

# -------------------- Pulpit --------------------

if page == "Automatyczny Skaner i Auto-Handel":
    st.subheader("Główny Pulpit Transakcyjny — podgląd na żywo")
    with st.expander("Ustawienia trybu pracy", expanded=False):
        with st.form("control_form"):
            c1, c2 = st.columns(2)
            with c1:
                auto_trade = st.checkbox("Włącz automatyczny handel", value=bool(cfg["auto_trade"]))
                paper_mode = st.checkbox("Tryb PAPER — bez zleceń na giełdzie", value=bool(cfg["paper_mode"]))
            with c2:
                auto_refresh = st.checkbox("Włącz ciągłe skanowanie", value=bool(cfg["auto_refresh"]))
                refresh_seconds = st.slider("Odstęp odświeżania (s)", 10, 120, int(cfg["refresh_seconds"]))
            save_controls = st.form_submit_button("ZAPISZ USTAWIENIA PRACY", use_container_width=True)
        if save_controls:
            cfg.update(auto_trade=auto_trade, paper_mode=paper_mode, auto_refresh=auto_refresh, refresh_seconds=refresh_seconds)
            save_cfg(cfg)
            st.session_state["cfg"] = cfg
            st.rerun()

    refresh_sec = max(10, int(cfg.get("refresh_seconds", 30)))

    st.fragment(run_every=refresh_sec if cfg.get("auto_refresh", True) else None)
    def render_full_dashboard():
        st.caption(f"Odświeżanie co {refresh_sec} s.")
        total_balance = free_balance = session_pnl = used_margin = 0.0
        active = []
        connected = bool(api_key_saved and secret_saved)
        api_ok = False
        if connected:
            try:
                client = exchange_client(ex_id, api_key_saved, secret_saved, passphrase_saved, cfg["market_type"])
                active = active_positions(client)
                if not cfg.get("paper_mode", True):
                    for msg in manage_position_exits(client, active, cfg):
                        st.warning(msg)
                    active = active_positions(client)
                free_balance, total_balance = balance_usdt(client, active)
                session_pnl = sum(asfloat(p.get("unrealizedPnl")) for p in active)
                used_margin = sum(asfloat(p.get("initialMargin") or p.get("margin")) for p in active)
                api_ok = True
            except Exception as exc:
                st.warning(f"Błąd połączenia z giełdą / pozycjami: {exc}")

        def metric_card(label, value, note=""):
            st.markdown(
                f'<div class="metric-card"><div class="metric-label">{label}</div><div class="metric-value">{value}</div><div class="metric-note">{note}</div></div>',
                unsafe_allow_html=True,
            )

        m1, m2, m3, m4 = st.columns(4, gap="medium")
        with m1:
            metric_card("Saldo / wolne środki", f"{total_balance:.2f} / {free_balance:.2f} USDT", "Saldo całkowite / dostępne")
        with m2:
            metric_card("Niezrealizowany PnL", f"{session_pnl:+.2f} USDT", "Łączny PnL otwartych pozycji")
        with m3:
            metric_card("Otwarte pozycje", f"{len(active)} / {int(cfg['max_positions'])}", f"Margin w użyciu: {used_margin:.2f} USDT")
        with m4:
            elapsed = max(0, int(time.time() - st.session_state["session_started_at"]))
            metric_card("Czas sesji", f"{elapsed//3600:02d}:{(elapsed%3600)//60:02d}:{elapsed%60:02d}", "Czas działania panelu")

        st.divider()
        st.markdown("### Skaner rynkowy multi-timeframe")
        
        try:
            scan_client = exchange_client(ex_id, api_key_saved if connected else "", secret_saved if connected else "", passphrase_saved if connected else "", cfg["market_type"])
            symbols = ranked_symbols(scan_client, cfg["scan_limit_count"])
            timeframes = cfg.get("timeframes", ["4h", "1d"])
            
            scan_rows = []
            for symbol, vol in symbols:
                row_data = {"Symbol": symbol, "Wolumen (USDT)": f"{vol:,.0f}"}
                for tf in timeframes:
                    res = signal_for_symbol(cfg, symbol, tf)
                    sig = res["signal"]
                    pr = res["price"]
                    row_data[f"Sygnał {tf}"] = sig
                    row_data[f"Cena {tf}"] = f"{pr:.4f}" if pr else "-"
                scan_rows.append(row_data)

            if scan_rows:
                df_scan = pd.DataFrame(scan_rows)
                st.dataframe(df_scan, use_container_width=True)
            else:
                st.info("Brak par do skanowania.")
        except Exception as exc:
            st.error(f"Błąd skanera: {exc}")

    render_full_dashboard()

elif page == "Ustawienia Strategii":
    st.subheader("Konfiguracja Strategii i Wskaźników")
    with st.form("strategy_form"):
        c1, c2, c3 = st.columns(3)
        with c1:
            exchange = st.selectbox("Giełda", EXCHANGE_OPTIONS, index=EXCHANGE_OPTIONS.index(cfg["exchange"]) if cfg["exchange"] in EXCHANGE_OPTIONS else 0)
            market_type = st.selectbox("Typ rynku", ["swap", "future"], index=0 if cfg["market_type"] == "swap" else 1)
            candle_limit = st.number_input("Limit świec do analizy", 50, 500, int(cfg["candle_limit"]))
        with c2:
            risk_usdt = st.number_input("Ryzyko na transakcję (USDT)", 1.0, 500.0, float(cfg["risk_usdt"]))
            max_positions = st.number_input("Maksymalnie otwartych pozycji", 1, 20, int(cfg["max_positions"]))
            max_leverage = st.number_input("Maksymalna dźwignia", 1, 125, int(cfg["max_leverage"]))
        with c3:
            sl_roe = st.number_input("Stop Loss ROE (%)", 5.0, 200.0, float(cfg["sl_roe"]))
            tp_roe = st.number_input("Take Profit ROE (%)", 10.0, 500.0, float(cfg["tp_roe"]))
            cooldown_seconds = st.number_input("Cooldown pary po zamknięciu (s)", 60, 86400, int(cfg["cooldown_seconds"]))

        st.divider()
        st.markdown("### Wybór interwałów czasowych")
        selected_tfs = st.multiselect("Interwały do skanowania i handlu", TF_OPTIONS, default=cfg["timeframes"])

        st.markdown("### Parametry wskaźników dla interwałów")
        tf_settings = cfg.get("tf_settings", get_dynamic_default_tf_settings())
        new_tf_settings = {}
        for tf in selected_tfs:
            st.markdown(f"**Interwał: {tf}**")
            defaults_tf = tf_settings.get(tf, get_dynamic_default_tf_settings()[tf])
            tc1, tc2, tc3, tc4 = st.columns(4)
            with tc1:
                ema_fast = st.number_input(f"EMA Szybka [{tf}]", 2, 100, int(defaults_tf.get("ema_fast", 9)), key=f"ema_fast_{tf}")
                ema_slow = st.number_input(f"EMA Wolna [{tf}]", 3, 200, int(defaults_tf.get("ema_slow", 21)), key=f"ema_slow_{tf}")
            with tc2:
                adx_threshold = st.number_input(f"ADX Min [{tf}]", 5.0, 60.0, float(defaults_tf.get("adx_threshold", 20.0)), key=f"adx_threshold_{tf}")
                rsi_period = st.number_input(f"RSI Okres [{tf}]", 2, 50, int(defaults_tf.get("rsi_period", 14)), key=f"rsi_period_{tf}")
            with tc3:
                rsi_long_min = st.number_input(f"RSI Long Min [{tf}]", 0.0, 100.0, float(defaults_tf.get("rsi_long_min", 50.0)), key=f"rsi_long_min_{tf}")
                rsi_long_max = st.number_input(f"RSI Long Max [{tf}]", 0.0, 100.0, float(defaults_tf.get("rsi_long_max", 65.0)), key=f"rsi_long_max_{tf}")
            with tc4:
                rsi_short_min = st.number_input(f"RSI Short Min [{tf}]", 0.0, 100.0, float(defaults_tf.get("rsi_short_min", 35.0)), key=f"rsi_short_min_{tf}")
                rsi_short_max = st.number_input(f"RSI Short Max [{tf}]", 0.0, 100.0, float(defaults_tf.get("rsi_short_max", 50.0)), key=f"rsi_short_max_{tf}")
            
            new_tf_settings[tf] = {
                "ema_fast": ema_fast,
                "ema_slow": ema_slow,
                "adx_threshold": adx_threshold,
                "rsi_period": rsi_period,
                "rsi_long_min": rsi_long_min,
                "rsi_long_max": rsi_long_max,
                "rsi_short_min": rsi_short_min,
                "rsi_short_max": rsi_short_max,
                "rsi_min": defaults_tf.get("rsi_min", 25.0),
                "rsi_max": defaults_tf.get("rsi_max", 75.0),
            }

        submit_strategy = st.form_submit_button("ZAPISZ USTAWIENIA STRATEGII", use_container_width=True)
        if submit_strategy:
            cfg.update(
                exchange=exchange,
                market_type=market_type,
                candle_limit=int(candle_limit),
                risk_usdt=float(risk_usdt),
                max_positions=int(max_positions),
                max_leverage=int(max_leverage),
                sl_roe=float(sl_roe),
                tp_roe=float(tp_roe),
                cooldown_seconds=int(cooldown_seconds),
                timeframes=selected_tfs,
                tf_settings=new_tf_settings,
            )
            save_cfg(cfg)
            st.session_state["cfg"] = cfg
            st.success("Ustawienia strategii zostały zapisane.")
            st.rerun()

elif page == "Połączenie API":
    st.subheader("Bezpieczne zarządzanie kluczami API giełdy")
    st.info("Klucze API są szyfrowane algorytmem Fernet w bazie danych przed zapisem.")
    with st.form("api_form"):
        api_exchange = st.selectbox("Wybierz giełdu", EXCHANGE_OPTIONS, index=EXCHANGE_OPTIONS.index(ex_id) if ex_id in EXCHANGE_OPTIONS else 0)
        api_key_input = st.text_input("API Key", value=api_key_saved, type="default")
        secret_input = st.text_input("Secret Key", value=secret_saved, type="password")
        passphrase_input = st.text_input("Passphrase / Hasło API", value=passphrase_saved, type="password")
        submit_api = st.form_submit_button("ZAPISZ KLUCZE API", use_container_width=True)
    if submit_api:
        try:
            save_creds(current_user_id, api_exchange, api_key_input, secret_input, passphrase_input)
            st.success("Klucze API zostały zaszyfrowane i zapisane pomyślnie.")
            st.rerun()
        except Exception as exc:
            st.error(f"Nie udało się zapisać kluczy: {exc}")

elif page == "Dziennik":
    st.subheader("Dziennik zdarzeń i aktywności systemu")
    try:
        with db() as con:
            rows = con.execute("SELECT ts, level, message FROM events ORDER BY id DESC LIMIT 200").fetchall()
        if rows:
            event_list = [{"Czas": r["ts"], "Poziom": r["level"], "Wiadomość": r["message"]} for r in rows]
            st.dataframe(pd.DataFrame(event_list), use_container_width=True)
        else:
            st.info("Brak zdarzeń w dzienniku.")
    except Exception as exc:
        st.error(f"Błąd ładowania dziennika: {exc}")

elif page == "Regulamin i Instrukcja":
    st.subheader("Regulamin i Instrukcja Użytkowania SaaS")
    st.markdown("""
    ### Witaj w Bitget-SaaS Futures
    1. **Zasady działania**: System automatycznie skanuje rynki kryptowalut na giełdach kontraktów futures (Bitget, Binance, Bybit, OKX) w oparciu o wskaźniki techniczne EMA, RSI oraz ADX.
    2. **Tryb Paper vs Live**: W trybie *Paper* zyczenia są symulowane w pamięci. W trybie *Live* bot wykonuje faktyczne transakcje na Twoim koncie giełdowym przy użyciu podanych kluczy API.
    3. **Ryzyko i odpowiedzialność**: Handel kontraktami futures wiąże się z wysokim ryzykiem strat finansowych. Używaj odpowiednich ustawień dźwigni oraz zarządzania ryzykiem.
    4. **Subskrypcja**: Dostęp do zaawansowanego skanera i auto-handlu wymaga aktywnej subskrypcji opłacanej miesięcznie lub rocznie.
    """)

elif page == "Panel Administratora" and is_user_admin():
    st.subheader("Panel Administratora — Zarządzanie użytkownikami")
    try:
        with db() as con:
            users = con.execute("SELECT id, username, email, subscription, stripe_paid FROM users").fetchall()
        user_rows = []
        for u in users:
            user_rows.append({
                "ID": u["id"],
                "Login": u["username"],
                "E-mail": u["email"],
                "Subskrypcja": u["subscription"],
                "Opłacone": bool(u["stripe_paid"])
            })
        st.dataframe(pd.DataFrame(user_rows), use_container_width=True)

        st.markdown("### Aktywacja subskrypcji użytkownika")
        with st.form("admin_act_form"):
            target_user_id = st.number_input("ID użytkownika", min_value=1, step=1)
            new_status = st.selectbox("Status płatności", [1, 0], format_func=lambda x: "Aktywna (1)" if x == 1 else "Nieaktywna (0)")
            submit_act = st.form_submit_button("ZAKTUALIZUJ STATUS", use_container_width=True)
        if submit_act:
            with db() as con:
                con.execute("UPDATE users SET stripe_paid=? WHERE id=?", (int(new_status), int(target_user_id)))
                con.commit()
            st.success(f"Zaktualizowano status użytkownika ID {target_user_id}.")
            st.rerun()
    except Exception as exc:
        st.error(f"Błąd panelu administratora: {exc}")

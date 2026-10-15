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
            "rsi_long_max": 70.0,
            "rsi_short_min": 30.0,
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
    """<style> .stApp{background:radial-gradient(ellipse at 40% -20%,#103e78 0%,#071a36 42%,#050e20 100%);color:#eaf3ff} [data-testid="stHeader"]{background:rgba(3,12,29,.96)} [data-testid="stAppViewContainer"] .main .block-container{padding-top:2rem;max-width:1600px} [data-testid="stSidebar"]{background:linear-gradient(180deg,#06152d,#081f42)} .brand{font-weight:900;font-size:30px;color:#eaf5ff;margin:.5rem 0} .metric-card{border:1px solid #d8ad52;border-radius:14px;padding:18px;min-height:130px; display:flex;flex-direction:column;justify-content:center;background:linear-gradient(145deg,#1b2b44,#061225);overflow:hidden} .metric-label{color:#b9c9df;font-size:12px;font-weight:700;letter-spacing:1px;text-transform:uppercase;margin-bottom:10px} .metric-value{color:#fff2c7;font-size:clamp(20px,1.8vw,29px);font-weight:850;line-height:1.2;overflow-wrap:anywhere} .metric-note{color:#a9bdd7;font-size:12px;margin-top:8px} </style>""",
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
            """CREATE TABLE IF NOT EXISTS user_credentials( user_id INTEGER PRIMARY KEY, exchange TEXT, api_key TEXT, secret TEXT, password TEXT)"""
        )
        con.execute(
            """CREATE TABLE IF NOT EXISTS events( id INTEGER PRIMARY KEY AUTOINCREMENT,ts TEXT,level TEXT,message TEXT)"""
        )
        con.execute(
            """CREATE TABLE IF NOT EXISTS pair_cooldowns( symbol TEXT PRIMARY KEY, closed_at REAL NOT NULL, reason TEXT NOT NULL)"""
        )
        con.execute(
            """CREATE TABLE IF NOT EXISTS users( id INTEGER PRIMARY KEY AUTOINCREMENT,username TEXT UNIQUE NOT NULL,password TEXT NOT NULL, subscription TEXT,stripe_paid INTEGER NOT NULL DEFAULT 0,email TEXT UNIQUE)"""
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
    # Migracja starszych haseł zapisanych jawnie.
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
    # Starsze wpisy jawne są odrzucane, a nie traktowane jako zaszyfrowane.
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
        "rsi_long_max": max(0.0, min(100.0, float(base.get("rsi_long_max", 70)))),
        "rsi_short_min": max(0.0, min(100.0, float(base.get("rsi_short_min", 30)))),
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
        # Ostatnia świeca może być nadal otwarta; sygnał bazuje na zamkniętej świecy.
        r = d.iloc[-2]
        fields = ["close", "ema_fast", "ema_slow", "adx", "rsi"]
        if not all(pd.notna(r[x]) and np.isfinite(float(r[x])) for x in fields):
            return {"symbol": symbol, "tf": timeframe, "signal": "NEUTRALNY", "price": asfloat(r["close"]), "adx": None, "rsi": None, "reason": "Brak danych wskaźników"}
        trend_up = r["ema_fast"] > r["ema_slow"]
        trend_down = r["ema_fast"] < r["ema_slow"]
        adx_ok = r["adx"] >= t["adx_threshold"]
        rsi = float(r["rsi"])
        long_ok = bool(cfg["allow_long"] and trend_up and adx_ok and t["rsi_long_min"] <= rsi <= t["rsi_long_max"] and r["close"] > r["ema_fast"])
        short_ok = bool(cfg["allow_short"] and trend_down and adx_ok and t["rsi_short_min"] <= rsi <= t["rsi_short_max"] and r["close"] < r["ema_fast"])
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
    # Nie odejmujemy margin ponownie, jeśli giełda już podała free.
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
    # Przybliżenie straty na SL: zmiana ceny = ROE / dźwignia.
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
    # Nie przekraczaj limitu ryzyka/wartości przez automatyczne podbicie do minimum giełdy.
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
    # Rola administratora wynika wyłącznie z jawnej listy dozwolonych adresów e-mail.
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

cfg = load_cfg()
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
            # Tryb live wymaga świadomego przełączenia; PAPER pozostaje domyślny.
            cfg.update(auto_trade=auto_trade, paper_mode=paper_mode, auto_refresh=auto_refresh, refresh_seconds=refresh_seconds)
            save_cfg(cfg)
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
            metric_card("Czas sesji", f"{elapsed//3600:02d}:{(elapsed%3600)//60:02d}:{elapsed%60:02d}", f"Odświeżanie co {refresh_sec}s")

        st.divider()
        st.markdown("### Aktywne pozycje na giełdzie")
        if active:
            st.dataframe(pd.DataFrame([{
                "Symbol": p.get("symbol"), "Strona": str(p.get("side")).upper(),
                "Kontrakty": p.get("contracts"), "Cena wejścia": p.get("entryPrice"),
                "PnL (USDT)": p.get("unrealizedPnl"), "Margin (USDT)": p.get("initialMargin"),
            } for p in active]), use_container_width=True, hide_index=True)
        elif connected and api_ok:
            st.info("Brak otwartych pozycji.")
        else:
            st.warning("Brak poprawnego połączenia API — sprawdź zakładkę Połączenie API.")

        st.divider()
        st.markdown("### 🏆 Skaner rynku i najlepsze okazje")
        try:
            public_ex = exchange_client(cfg["exchange"], "", "", "", cfg["market_type"])
            ranked = ranked_symbols(public_ex, int(cfg.get("scan_limit_count", 10)))
            symbols = [item[0] for item in ranked]
            volume_map = dict(ranked)
            timeframes = [tf for tf in cfg.get("timeframes", ["4h", "1d"]) if tf in TF_OPTIONS]
            all_signals = []
            for symbol in symbols:
                for tf in timeframes:
                    result = signal_for_symbol(cfg, symbol, tf)
                    result["volume_24h_usdt"] = volume_map.get(symbol, 0.0)
                    result["score"] = asfloat(result.get("adx")) * np.log1p(result["volume_24h_usdt"])
                    all_signals.append(result)

            scanner = pd.DataFrame([{
                "Symbol": item["symbol"], "Interwał": item["tf"], "Sygnał": item["signal"],
                "Cena": item["price"], "ADX": round(item["adx"], 1) if item["adx"] is not None else 0.0,
                "RSI": round(item["rsi"], 1) if item["rsi"] is not None else 0.0,
                "Komunikat": item["reason"],
            } for item in all_signals])
            if not scanner.empty:
                st.markdown("#### Pełne zestawienie skanera")
                st.dataframe(scanner, use_container_width=True, hide_index=True)
            else:
                st.info("Giełda nie zwróciła danych do skanowania.")

            if cfg["auto_trade"] and is_user_paid() and not cfg["paper_mode"] and connected and api_ok:
                try:
                    live_client = exchange_client(ex_id, api_key_saved, secret_saved, passphrase_saved, cfg["market_type"])
                    valid = [s for s in all_signals if s["signal"] in ("LONG", "SHORT") and s["price"]]
                    valid.sort(key=lambda item: item.get("score", 0), reverse=True)
                    unique = {}
                    for item in valid:
                        unique.setdefault(item["symbol"], item)
                    for item in unique.values():
                        positions = active_positions(live_client)
                        if len(positions) >= int(cfg.get("max_positions", 3)):
                            break
                        symbol, signal, price = item["symbol"], item["signal"], item["price"]
                        if any(p.get("symbol") == symbol for p in positions) or pair_cooldown_remaining(symbol, int(cfg.get("cooldown_seconds", 900))) > 0:
                            continue
                        free, total = balance_usdt(live_client, positions)
                        qty, notional = calc_qty(live_client, symbol, total, free, price, cfg)
                        if qty <= 0:
                            event("WARN", f"Auto-trade pominięty dla {symbol}: wielkość pozycji poniżej minimum lub brak środków.")
                            continue
                        live_client.set_leverage(int(cfg["max_leverage"]), symbol)
                        order = market_order(live_client, symbol, "buy" if signal == "LONG" else "sell", qty, reference_price=price)
                        msg = f"AUTO-TRADE: Otwarto {signal} na {symbol}, qty={qty}, ID={order.get('id')}"
                        event("TRADE", msg)
                        set_pair_cooldown(symbol, "AUTO_OPEN", int(cfg.get("cooldown_seconds", 900)))
                        st.success(msg)
                except Exception as exc:
                    event("ERROR", f"Błąd w pętli Auto-Trade: {exc}")
                    st.error(f"Błąd w pętli Auto-Trade: {exc}")

            st.markdown("### 🌟 Top 3 najlepsze okazje rynkowe")
            top_three = sorted(
                [s for s in all_signals if s["signal"] in ("LONG", "SHORT") and s["price"]],
                key=lambda item: item.get("score", 0), reverse=True,
            )[:3]
            if top_three:
                for i, item in enumerate(top_three, 1):
                    symbol, signal, price = item["symbol"], item["signal"], item["price"]
                    adx, tf = asfloat(item["adx"]), item["tf"]
                    info_col, button_col = st.columns([3, 1])
                    with info_col:
                        color = "#2ea043" if signal == "LONG" else "#da3633"
                        st.markdown(
                            f'<div style="background:#161b22;border:1px solid #d4af37;padding:12px;border-radius:8px;margin-bottom:8px">'
                            f'<b>#{i} {symbol}</b> [{tf}] | Sygnał: <span style="color:{color};font-weight:bold">{signal}</span> '
                            f'| Cena: <b>{price:.8g}</b> | ADX: <b>{adx:.1f}</b></div>',
                            unsafe_allow_html=True,
                        )
                    with button_col:
                        amount = st.number_input(
                            f"Kwota ryzyka (USDT) — {symbol}", min_value=1.0, max_value=10000.0,
                            value=float(cfg.get("risk_usdt", 10.0)), step=5.0, key=f"invest_amount_{symbol}_{i}",
                        )
                        if st.button(f"🚀 Zainwestuj {signal}", key=f"invest_{symbol}_{i}"):
                            if not is_user_paid():
                                st.error("Musisz posiadać aktywną subskrypcję.")
                            elif not connected:
                                st.error("Brak kluczy API. Uzupełnij je w zakładce Połączenie API.")
                            else:
                                try:
                                    live_client = exchange_client(ex_id, api_key_saved, secret_saved, passphrase_saved, cfg["market_type"])
                                    positions = active_positions(live_client)
                                    if len(positions) >= int(cfg["max_positions"]):
                                        st.error("Osiągnięto maksymalną liczbę otwartych pozycji.")
                                    elif any(p.get("symbol") == symbol for p in positions):
                                        st.error("Pozycja na tej parze już istnieje.")
                                    else:
                                        free, total = balance_usdt(live_client, positions)
                                        qty, notional = calc_qty(live_client, symbol, total, free, price, cfg, custom_usdt=amount)
                                        if qty <= 0:
                                            st.error("Za małe środki lub zlecenie nie spełnia limitów giełdy.")
                                        elif cfg["paper_mode"]:
                                            st.success(f"[PAPER] Symulacja {signal} {symbol}, wartość {notional:.2f} USDT.")
                                            event("TRADE", f"[PAPER] Ręczna inwestycja: {signal} {symbol}, notional={notional:.2f} USDT")
                                        else:
                                            live_client.set_leverage(int(cfg["max_leverage"]), symbol)
                                            order = market_order(live_client, symbol, "buy" if signal == "LONG" else "sell", qty, reference_price=price)
                                            st.success(f"Wysłano zlecenie {signal} {symbol}, ID={order.get('id')}")
                                            event("TRADE", f"Ręczna inwestycja: {signal} {symbol}, qty={qty}, notional={notional:.2f} USDT")
                                except Exception as exc:
                                    st.error(f"Błąd składania zlecenia dla {symbol}: {exc}")
            else:
                st.info("Brak par spełniających kryteria wskaźnikowe.")
        except Exception as exc:
            logging.exception("Błąd analizy rynków")
            st.error(f"Błąd analizy rynków: {exc}")
        finally:
            gc.collect()

    render_full_dashboard()
    st.divider()
    st.markdown("### Awaryjne zamknięcie wszystkich pozycji")
    st.warning("To polecenie wysyła prawdziwe zlecenia rynkowe. Sprawdź tryb konta i pozycje przed użyciem.")
    if st.button("ZAMKNIJ WSZYSTKIE POZYCJE"):
        try:
            if not (api_key_saved and secret_saved):
                raise RuntimeError("Brak kluczy API.")
            client = exchange_client(ex_id, api_key_saved, secret_saved, passphrase_saved, cfg["market_type"])
            outcomes = []
            for pos in active_positions(client):
                qty, symbol = abs(asfloat(pos.get("contracts"))), pos.get("symbol")
                side_pos = str(pos.get("side") or "").lower()
                if qty <= 0 or not symbol or side_pos not in ("long", "short"):
                    continue
                try:
                    order = market_order(client, symbol, "sell" if side_pos == "long" else "buy", qty, reduce_only=True)
                    outcomes.append(f"{symbol}: wysłano zamknięcie; order={order.get('id')}")
                except Exception as exc:
                    outcomes.append(f"{symbol}: BŁĄD: {exc}")
            for line in outcomes:
                event("KILL", line)
            st.write("\n".join(outcomes) if outcomes else "Brak aktywnych pozycji.")
        except Exception as exc:
            st.error(f"Zamknięcie awaryjne nie powiodło się: {exc}")

# -------------------- Ustawienia strategii --------------------

if page == "Ustawienia Strategii":
    st.subheader("Ustawienia strategii i ryzyka")
    
    # Wybór interwału do edycji z użyciem st.selectbox i callbacka / klucza
    selected_tf = st.selectbox(
        "Interwał do edycji", 
        TF_OPTIONS, 
        index=TF_OPTIONS.index(cfg.get("timeframes", ["4h", "1d"])[0] if cfg.get("timeframes") else "1d") if cfg.get("timeframes", ["4h", "1d"])[0] in TF_OPTIONS else 0,
        key="strategy_edit_tf"
    )
    
    defaults = get_dynamic_default_tf_settings()
    # Pobieramy aktualne ustawienia dla wybranego interwału (z uwzględnieniem zapisu w cfg)
    base = cfg.get("tf_settings", {}).get(selected_tf, defaults.get(selected_tf, defaults["1h"]))

    with st.form("cfgform"):
        left, right = st.columns(2)
        with left:
            exchange_name = st.selectbox("Giełda", EXCHANGE_OPTIONS, index=EXCHANGE_OPTIONS.index(cfg["exchange"]) if cfg["exchange"] in EXCHANGE_OPTIONS else 0)
            market_type = st.selectbox("Rynek", ["swap", "future"], index=0 if cfg["market_type"] == "swap" else 1)
            scan_limit = st.slider("Liczba skanowanych par", 5, 200, max(5, min(200, int(cfg.get("scan_limit_count", 10)))))
            timeframes = st.multiselect("Interwały skanowania", TF_OPTIONS, default=cfg.get("timeframes", ["4h", "1d"]))
            multiplier = st.slider("Mnożnik progów ADX (%)", 10, 150, max(10, min(150, int(cfg.get("indicator_multiplier", 100)))))
            candle_limit = st.slider("Liczba świec do analizy", 100, 250, max(100, min(250, int(cfg.get("candle_limit", 150)))))
        with right:
            risk = st.number_input("Maks. ryzyko na pozycję (USDT)", 1.0, 10000.0, float(cfg.get("risk_usdt", 10.0)))
            max_notional = st.number_input("Maks. wartość pozycji (USDT)", 10.0, 100000.0, float(cfg.get("max_notional_usdt", 200.0)))
            max_positions = st.number_input("Maks. liczba otwartych pozycji", 1, 20, int(cfg.get("max_positions", 3)))
            max_leverage = st.number_input("Maksymalna dźwignia", 1, 50, int(cfg.get("max_leverage", 10)))
            enable_roe = st.checkbox("Włącz aktywne zarządzanie TP/SL (ROE)", bool(cfg.get("enable_roe", True)))
            sl_roe = st.slider("Stop Loss — ROE (%)", 5, 95, max(5, min(95, int(cfg.get("sl_roe", 30)))))
            tp_roe = st.slider("Take Profit — ROE (%)", 5, 500, max(5, min(500, int(cfg.get("tp_roe", 60)))))
            allow_long = st.checkbox("Pozwól na LONG", bool(cfg.get("allow_long", True)))
            allow_short = st.checkbox("Pozwól na SHORT", bool(cfg.get("allow_short", True)))

        st.markdown(f"### Parametry wskaźników dla interwału: {selected_tf}")
        c1, c2, c3 = st.columns(3)
        with c1:
            fast = st.slider("EMA szybka", 2, 100, max(2, min(100, int(base.get("ema_fast", 9)))), key=f"form_fast_{selected_tf}")
        with c2:
            slow = st.slider("EMA wolna", 3, 300, max(3, min(300, int(base.get("ema_slow", 21)))), key=f"form_slow_{selected_tf}")
        with c3:
            adx = st.number_input("Minimalny ADX", 0.0, 100.0, float(base.get("adx_threshold", 20.0)), key=f"form_adx_{selected_tf}")

        st.markdown("#### Ustawienia RSI")
        r1, r2, r3 = st.columns(3)
        with r1:
            rsi_period = st.number_input("RSI okres", 2, 100, int(base.get("rsi_period", 14)), 1, key=f"form_rsi_p_{selected_tf}")
        with r2:
            rsi_long_min = st.number_input("RSI LONG — minimum", 0.0, 100.0, float(base.get("rsi_long_min", 50.0)), 1.0, key=f"form_rl_min_{selected_tf}")
        with r3:
            rsi_long_max = st.number_input("RSI LONG — maksimum", 0.0, 100.0, float(base.get("rsi_long_max", 70.0)), 1.0, key=f"form_rl_max_{selected_tf}")

        r4, r5 = st.columns(2)
        with r4:
            rsi_short_min = st.number_input("RSI SHORT — minimum", 0.0, 100.0, float(base.get("rsi_short_min", 30.0)), 1.0, key=f"form_rs_min_{selected_tf}")
        with r5:
            rsi_short_max = st.number_input("RSI SHORT — maksimum", 0.0, 100.0, float(base.get("rsi_short_max", 50.0)), 1.0, key=f"form_rs_max_{selected_tf}")

        save = st.form_submit_button("ZAPISZ USTAWIENIA", use_container_width=True)

    if save:
        if fast >= slow:
            st.error("EMA szybka musi być mniejsza od EMA wolnej.")
        elif rsi_long_min >= rsi_long_max or rsi_short_min >= rsi_short_max:
            st.error("W każdym zakresie RSI minimum musi być mniejsze od maksimum.")
        else:
            # Upewniamy się, że struktura słownika tf_settings istnieje
            if "tf_settings" not in cfg:
                cfg["tf_settings"] = get_dynamic_default_tf_settings()
            
            cfg.update(
                exchange=exchange_name, 
                market_type=market_type, 
                scan_limit_count=scan_limit,
                timeframes=timeframes or ["4h", "1d"], 
                indicator_multiplier=multiplier,
                candle_limit=candle_limit, 
                risk_usdt=risk, 
                max_notional_usdt=max_notional,
                max_positions=int(max_positions), 
                max_leverage=int(max_leverage),
                enable_roe=enable_roe, 
                sl_roe=float(sl_roe), 
                tp_roe=float(tp_roe),
                allow_long=allow_long, 
                allow_short=allow_short,
            )
            
            cfg["tf_settings"][selected_tf] = {
                "ema_fast": int(fast), 
                "ema_slow": int(slow), 
                "adx_threshold": float(adx),
                "rsi_period": int(rsi_period), 
                "rsi_long_min": float(rsi_long_min),
                "rsi_long_max": float(rsi_long_max), 
                "rsi_short_min": float(rsi_short_min),
                "rsi_short_max": float(rsi_short_max), 
                "rsi_min": float(base.get("rsi_min", 25)),
                "rsi_max": float(base.get("rsi_max", 75)),
            }
            
            save_cfg(cfg)
            exchange_client.clear()
            get_candles.clear()
            st.cache_data.clear()
            st.success(f"Zapisano ustawienia dla interwału {selected_tf}.")
            st.rerun()

       
# -------------------- Połączenie API --------------------

if page == "Połączenie API":
    st.subheader("Połączenie z giełdą")
    st.warning("Utwórz klucze API bez uprawnień do wypłat. Zalecane jest ograniczenie kluczy do handlu i adresu IP serwera.")
    with st.form("credentials"):
        exchange_choice = st.selectbox("Giełda", EXCHANGE_OPTIONS, index=EXCHANGE_OPTIONS.index(ex_id) if ex_id in EXCHANGE_OPTIONS else 0)
        api_key_input = st.text_input("API Key", value=api_key_saved, type="password")
        secret_input = st.text_input("Secret Key", value=secret_saved, type="password")
        passphrase_input = st.text_input("Passphrase / Hasło", value=passphrase_saved, type="password")
        submit_creds = st.form_submit_button("ZAPISZ KLUCZE API", use_container_width=True)
    if submit_creds:
        try:
            save_creds(current_user_id, exchange_choice, api_key_input.strip(), secret_input.strip(), passphrase_input.strip())
            exchange_client.clear()
            st.success("Klucze API zapisano w zaszyfrowanej postaci.")
            st.rerun()
        except Exception as exc:
            st.error(f"Nie udało się zapisać kluczy API: {exc}")
    st.caption("Szyfrowanie wymaga zmiennej BITGET_SAAS_ENCRYPTION_KEY. Bez niej klucze nie zostaną zapisane.")

# -------------------- Dziennik --------------------

if page == "Dziennik":
    st.subheader("Dziennik zdarzeń i transakcji bota")
    _, delete_col = st.columns([4, 1])
    with delete_col:
        if st.button("🗑️ Wyczyść dziennik", use_container_width=True):
            with db() as con:
                con.execute("DELETE FROM events")
                con.commit()
            st.success("Wyczyszczono dziennik zdarzeń.")
            st.rerun()
    try:
        with db() as con:
            rows = con.execute("SELECT ts,level,message FROM events ORDER BY id DESC LIMIT 100").fetchall()
        if rows:
            st.dataframe(pd.DataFrame([dict(row) for row in rows]), use_container_width=True, hide_index=True)
        else:
            st.info("Brak wpisów w dzienniku.")
    except Exception as exc:
        st.error(f"Nie udało się wczytać dziennika: {exc}")

# -------------------- Regulamin i Instrukcja --------------------

def show_terms_and_manual():
    st.title("Regulamin i Instrukcja Obsługi")
    st.subheader("Witaj w Bitget-SaaS Futures")
    st.write("System automatycznego handlu kontraktami futures na rynkach kryptowalutowych.")

    st.markdown("---")

    st.subheader("1. Instrukcja Obsługi i Tryby Pracy")
    
    st.markdown("""
    * **Tryb Paper Trading (Symulacja / Demo):**
      * Pozwala bezpiecznie testować sygnały i strategie bez otwierania prawdziwych pozycji na giełdzie.
      * Pozycje są otwierane wirtualnie, co pozwala zweryfikować skuteczność ustawień wskaźników (EMA, RSI, ADX) przed zaangażowaniem kapitału.
    
    * **Tryb Auto-Trade (Handel Rzeczywisty):**
      * Po wyłączeniu trybu Paper Trading i poprawnym skonfigurowaniu kluczy API, bot sam otwiera i zamyka zlecenia bezpośrednio na Twoim koncie giełdowym.
      * Skanning i automatyczna egzekucja odbywają się w oparciu o wykryte trendy na wybranych interwałach czasowych (od 1m do 1d).
    
    * **Zarządzanie Ryzykiem i Ochrona Kapitału:**
      * Automatyczny **Stop Loss** oraz **Take Profit** (w tym funkcja **ROE Guard**) pilnują otwartych pozycji zgodnie z przyjętymi ustawieniami.
      * Możesz elastycznie dostosowywać wielkość dźwigni, maksymalną liczbę otwartych pozycji oraz podział kapitału.
    """)

    st.markdown("---")

    st.subheader("2. Bezpieczeństwo i Konfiguracja API")
    
    st.markdown("""
    * **Uprawnienia Kluczy API:** Do poprawnego działania bota wymagane są klucze API z giełdy z uprawnieniami do **Odczytu (Read)** oraz **Handlu Futures (Trade)**. **Nigdy nie włączaj uprawnień do wypłat (Transfer / Withdrawal)**.
    * **Ochrona Danych:** Twoje dane dostępowe oraz klucze API są szyfrowane i bezpiecznie przechowywane w bazie danych.
    """)

    st.markdown("---")

    st.subheader("3. Regulamin i Wyłączenie Odpowiedzialności (Disclaimer)")
    
    st.markdown("""
    1. **Ostrzeżenie o Ryzyku:** Handel kontraktami pochodnymi (Futures) z użyciem dźwigni finansowej wiąże się z wysokim ryzykiem utraty kapitału. Ceny kryptowalut charakteryzują się wysoką zmiennością.
    2. **Brak Porady Inwestycyjnej:** Oprogramowanie *Bitget-SaaS Futures* jest narzędziem technologicznym i nie stanowi porady inwestycyjnej ani finansowej.
    3. **Odpowiedzialność Użytkownika:** Użytkownik ponosi pełną odpowiedzialność za dobór parametrów handlowych (dźwignia, Stop Loss, wskaźniki) oraz za wszelkie zyski lub straty wynikające z pracy bota.
    4. **Ciągłość Działania:** Twórcy bota nie ponoszą odpowiedzialności za opóźnienia w realizacji zleceń wynikające z prac konserwacyjnych lub awarii po stronie API giełdy.
    """)

# Zmień "Regulamin" w cudzysłowie poniżej na dokładnie taki tekst, jaki masz w menu bocznym (sidebarze) dla tej zakładki:
if page == "Regulamin i Instrukcja":
    show_terms_and_manual()


# -------------------- Panel Administratora --------------------

if page == "Panel Administratora" and is_user_admin():
    st.subheader("Panel administratora — zarządzanie użytkownikami")
    try:
        with db() as con:
            users = con.execute("SELECT id,username,email,stripe_paid,subscription FROM users ORDER BY id").fetchall()
        if users:
            st.dataframe(pd.DataFrame([dict(user) for user in users]), use_container_width=True, hide_index=True)
            user_ids = [int(user["id"]) for user in users]
            selected_uid = st.selectbox("Użytkownik do aktywacji/dezaktywacji", user_ids)
            a, b = st.columns(2)
            with a:
                if st.button("Aktywuj subskrypcję"):
                    with db() as con:
                        con.execute("UPDATE users SET stripe_paid=1 WHERE id=?", (selected_uid,))
                        con.commit()
                    event("ADMIN", f"Administrator aktywował subskrypcję użytkownika ID {selected_uid}")
                    st.success(f"Aktywowano subskrypcję dla ID {selected_uid}.")
                    st.rerun()
            with b:
                if st.button("Dezaktywuj subskrypcję"):
                    with db() as con:
                        con.execute("UPDATE users SET stripe_paid=0 WHERE id=?", (selected_uid,))
                        con.commit()
                    event("ADMIN", f"Administrator dezaktywował subskrypcję użytkownika ID {selected_uid}")
                    st.success(f"Dezaktywowano subskrypcję dla ID {selected_uid}.")
                    st.rerun()
        else:
            st.info("Brak zarejestrowanych użytkowników.")
    except Exception as exc:
        st.error(f"Błąd panelu administratora: {exc}")

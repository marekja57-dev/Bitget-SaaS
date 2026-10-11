import os
import json
import sqlite3
import time
import logging
import hashlib
import hmac
import secrets
import gc
from pathlib import Path
from datetime import datetime, timezone

import pandas as pd
import numpy as np
import streamlit as st

try:
    import ccxt
except ImportError:
    ccxt = None

st.set_page_config(page_title="Bitget-SaaS Futures", page_icon="📈", layout="wide")

APP_DIR = Path(__file__).resolve().parent
DB_PATH = Path(os.getenv("BITGET_SAAS_DB", str(APP_DIR / "bitget_saas.db")))
LOG_PATH = APP_DIR / "trading.log"
logging.basicConfig(filename=str(LOG_PATH), level=logging.INFO,
                    format="%(asctime)s %(levelname)s %(message)s")

STRIPE_CHECKOUT_FALLBACK = "https://buy.stripe.com/8x2dRa4CbdaXfSAf6V3oA03"
ADMIN_EMAILS = {"marekja57@wp.pl", "admin@bot-bitget.pl"}
TF_OPTIONS = ["1m", "3m", "5m", "15m", "30m", "1h", "2h", "4h", "1d"]
MIN_ORDER_NOTIONAL_USDT = 10.0

DEFAULT_TF_SETTINGS = {
    "1m": {"ema_fast": 9, "ema_slow": 21, "adx_threshold": 25., "rsi_min": 25., "rsi_max": 75.},
    "3m": {"ema_fast": 9, "ema_slow": 21, "adx_threshold": 25., "rsi_min": 25., "rsi_max": 75.},
    "5m": {"ema_fast": 9, "ema_slow": 21, "adx_threshold": 25., "rsi_min": 25., "rsi_max": 75.},
    "15m": {"ema_fast": 9, "ema_slow": 21, "adx_threshold": 25., "rsi_min": 25., "rsi_max": 75.},
    "30m": {"ema_fast": 9, "ema_slow": 21, "adx_threshold": 25., "rsi_min": 25., "rsi_max": 75.},
    "1h": {"ema_fast": 12, "ema_slow": 26, "adx_threshold": 22., "rsi_min": 30., "rsi_max": 70.},
    "2h": {"ema_fast": 12, "ema_slow": 26, "adx_threshold": 20., "rsi_min": 30., "rsi_max": 70.},
    "4h": {"ema_fast": 20, "ema_slow": 50, "adx_threshold": 20., "rsi_min": 30., "rsi_max": 70.},
    "1d": {"ema_fast": 40, "ema_slow": 140, "adx_threshold": 15., "rsi_min": 35., "rsi_max": 65.},
}
DEFAULTS = {
    "exchange": "bitget", "market_type": "swap", "candle_limit": 150,
    "refresh_seconds": 30, "risk_usdt": 10., "max_positions": 3,
    "max_leverage": 10, "sl_roe": 20., "tp_roe": 40., "enable_roe": True,
    "timeframes": ["4h", "1d"], "tf_settings": DEFAULT_TF_SETTINGS,
    "auto_refresh": True, "auto_trade": False, "paper_mode": True,
    "max_notional_usdt": 200., "cooldown_seconds": 300,
    "allow_short": True, "allow_long": True, "scan_limit_count": 10,
    "indicator_multiplier": 100,
}

st.markdown("""<style> .stApp{background:radial-gradient(ellipse at 40% -20%,#103e78 0%,#071a36 42%,#050e20 100%);color:#eaf3ff} [data-testid="stHeader"]{background:rgba(3,12,29,.96)} [data-testid="stAppViewContainer"] .main .block-container{padding-top:2rem;max-width:1600px} [data-testid="stSidebar"]{background:linear-gradient(180deg,#06152d,#081f42)} .brand{font-weight:900;font-size:30px;color:#eaf5ff;margin:.5rem 0} .metric-card{border:1px solid #d8ad52;border-radius:14px;padding:18px;height:150px;display:flex;flex-direction:column;justify-content:center;background:linear-gradient(145deg,#1b2b44,#061225);overflow:hidden} .metric-label{color:#b9c9df;font-size:12px;font-weight:700;letter-spacing:1px;text-transform:uppercase;margin-bottom:10px} .metric-value{color:#fff2c7;font-size:clamp(20px,1.8vw,29px);font-weight:850;line-height:1.2;overflow-wrap:anywhere} .metric-note{color:#a9bdd7;font-size:12px;margin-top:8px} </style>""", unsafe_allow_html=True)


# -------------------- Baza danych --------------------
def db():
    con = sqlite3.connect(DB_PATH, timeout=20)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA busy_timeout=20000")
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("CREATE TABLE IF NOT EXISTS settings(k TEXT PRIMARY KEY,v TEXT NOT NULL)")
    con.execute("""CREATE TABLE IF NOT EXISTS user_credentials( user_id INTEGER PRIMARY KEY,exchange TEXT,api_key TEXT,secret TEXT,password TEXT)""")
    con.execute("CREATE TABLE IF NOT EXISTS events(id INTEGER PRIMARY KEY AUTOINCREMENT,ts TEXT,level TEXT,message TEXT)")
    con.execute("""CREATE TABLE IF NOT EXISTS pair_cooldowns( symbol TEXT PRIMARY KEY, closed_at REAL NOT NULL, reason TEXT NOT NULL )""")
    con.execute("""CREATE TABLE IF NOT EXISTS users( id INTEGER PRIMARY KEY AUTOINCREMENT,username TEXT UNIQUE NOT NULL,password TEXT NOT NULL, subscription TEXT,stripe_paid INTEGER NOT NULL DEFAULT 0,email TEXT UNIQUE)""")
    con.commit()
    return con


def password_hash(password, salt=None):
    salt = salt or secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), 240000).hex()
    return f"pbkdf2${salt}${digest}"


def verify_password(stored, password):
    if stored == password:
        return True, True
    try:
        scheme, salt, digest = stored.split("$", 2)
        if scheme != "pbkdf2":
            return False, False
        check = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), 240000).hex()
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
        con.execute("""INSERT INTO settings(k,v) VALUES('main',?) ON CONFLICT(k) DO UPDATE SET v=excluded.v""", (json.dumps(cfg, ensure_ascii=False),))
        con.commit()


def event(level, message):
    message = str(message)[:1500]
    logging.log(getattr(logging, str(level).upper(), logging.INFO), message)
    with db() as con:
        con.execute("INSERT INTO events(ts,level,message) VALUES(?,?,?)",
                    (datetime.now(timezone.utc).isoformat(), str(level), message))
        con.commit()


def set_pair_cooldown(symbol, reason, seconds=600):
    """Zapisuje blokadę ponownego wejścia na parę po zamknięciu SL/TP."""
    if not symbol:
        return
    with db() as con:
        con.execute(
            """INSERT INTO pair_cooldowns(symbol, closed_at, reason) VALUES(?,?,?) ON CONFLICT(symbol) DO UPDATE SET closed_at=excluded.closed_at, reason=excluded.reason""",
            (str(symbol), time.time(), str(reason))
        )
        con.commit()


def pair_cooldown_remaining(symbol, seconds=600):
    """Zwraca liczbę sekund blokady dla pary; 0 oznacza brak aktywnej blokady."""
    if not symbol:
        return 0
    try:
        with db() as con:
            row = con.execute(
                "SELECT closed_at FROM pair_cooldowns WHERE symbol=?",
                (str(symbol),)
            ).fetchone()
        if not row:
            return 0
        remaining = int(max(0, float(seconds) - (time.time() - float(row["closed_at"]))))
        if remaining <= 0:
            with db() as con:
                con.execute("DELETE FROM pair_cooldowns WHERE symbol=?", (str(symbol),))
                con.commit()
        return remaining
    except Exception:
        logging.exception("Nie udało się sprawdzić blokady pary %s", symbol)
        # Fail closed: jeśli nie można sprawdzić blokady, nie otwieraj nowej pozycji.
        return int(seconds)


def load_creds(user_id):
    if not user_id:
        return ("bitget", "", "", "")
    with db() as con:
        row = con.execute("SELECT exchange,api_key,secret,password FROM user_credentials WHERE user_id=?",
                          (user_id,)).fetchone()
    return tuple(row) if row else ("bitget", "", "", "")


def save_creds(user_id, exchange, api_key, secret, passphrase):
    if not user_id:
        return
    with db() as con:
        con.execute("""INSERT INTO user_credentials(user_id,exchange,api_key,secret,password) VALUES(?,?,?,?,?) ON CONFLICT(user_id) DO UPDATE SET exchange=excluded.exchange, api_key=excluded.api_key,secret=excluded.secret,password=excluded.password""",
        (user_id, exchange, api_key, secret, passphrase))
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
    opts = {"enableRateLimit": True, "timeout": 25000,
            "options": {"defaultType": market_type, "defaultSubType": "linear"}}
    if api_key and secret:
        opts.update(apiKey=api_key, secret=secret)
    if passphrase:
        opts["password"] = passphrase
    return cls(opts)


@st.cache_data(ttl=30, max_entries=20, show_spinner=False)
def get_candles(ex_id, market_type, symbol, timeframe, limit):
    ex = exchange_client(ex_id, "", "", "", market_type)
    rows = ex.fetch_ohlcv(symbol, timeframe=timeframe, limit=int(limit))
    return pd.DataFrame(rows, columns=["timestamp", "open", "high", "low", "close", "volume"])


def indicators(df, fast, slow):
    d = df.copy()
    for col in ["open", "high", "low", "close", "volume"]:
        d[col] = pd.to_numeric(d[col], errors="coerce")
    d = d.dropna(subset=["high", "low", "close"]).reset_index(drop=True)
    d["ema_fast"] = d["close"].ewm(span=int(fast), adjust=False).mean()
    d["ema_slow"] = d["close"].ewm(span=int(slow), adjust=False).mean()
    delta = d["close"].diff()
    gain = delta.clip(lower=0).ewm(alpha=1/14, adjust=False).mean()
    loss = (-delta.clip(upper=0)).ewm(alpha=1/14, adjust=False).mean()
    rs = gain / loss.replace(0, np.nan)
    d["rsi"] = 100 - 100 / (1 + rs)
    tr = pd.concat([(d["high"]-d["low"]).abs(),
                    (d["high"]-d["close"].shift()).abs(),
                    (d["low"]-d["close"].shift()).abs()], axis=1).max(axis=1)
    up, down = d["high"].diff(), -d["low"].diff()
    plus = pd.Series(np.where((up > down) & (up > 0), up, 0), index=d.index)
    minus = pd.Series(np.where((down > up) & (down > 0), down, 0), index=d.index)
    atr = tr.ewm(alpha=1/14, adjust=False).mean().replace(0, np.nan)
    pdi = 100 * plus.ewm(alpha=1/14, adjust=False).mean() / atr
    mdi = 100 * minus.ewm(alpha=1/14, adjust=False).mean() / atr
    dx = 100 * (pdi-mdi).abs() / (pdi+mdi).replace(0, np.nan)
    d["adx"] = dx.ewm(alpha=1/14, adjust=False).mean()
    return d


def effective_tf_cfg(cfg, tf):
    base = cfg.get("tf_settings", {}).get(tf, DEFAULT_TF_SETTINGS.get(tf, DEFAULT_TF_SETTINGS["1h"]))
    mult = float(cfg.get("indicator_multiplier", 100)) / 100
    fast = max(2, int(round(float(base["ema_fast"]) * mult)))
    slow = max(fast + 1, int(round(float(base["ema_slow"]) * mult)))
    return {"ema_fast": fast, "ema_slow": slow,
            "adx_threshold": max(2., min(90., float(base["adx_threshold"]) * mult)),
            "rsi_min": max(2., min(45., float(base["rsi_min"]))),
            "rsi_max": max(55., min(98., float(base["rsi_max"])))}


def signal_for_symbol(cfg, symbol, timeframe):
    try:
        t = effective_tf_cfg(cfg, timeframe)
        raw = get_candles(cfg["exchange"], cfg["market_type"], symbol, timeframe, cfg["candle_limit"])
        d = indicators(raw, t["ema_fast"], t["ema_slow"])
        if len(d) < max(35, t["ema_slow"] + 5):
            return {"symbol": symbol, "tf": timeframe, "signal": "NEUTRALNY",
                    "price": None, "adx": None, "rsi": None, "reason": "Za mało świec"}
        r = d.iloc[-1]
        if not all(pd.notna(r[x]) and np.isfinite(float(r[x]))
                   for x in ["close", "ema_fast", "ema_slow", "adx", "rsi"]):
            return {"symbol": symbol, "tf": timeframe, "signal": "NEUTRALNY",
                    "price": asfloat(r["close"]), "adx": None, "rsi": None, "reason": "Brak danych wskaźników"}
        trend = r["ema_fast"] > r["ema_slow"]
        filters = r["adx"] >= t["adx_threshold"] and t["rsi_min"] <= r["rsi"] <= t["rsi_max"]
        long_ok = bool(cfg["allow_long"] and trend and filters and r["close"] > r["ema_fast"])
        short_ok = bool(cfg["allow_short"] and not trend and filters and r["close"] < r["ema_fast"])
        return {"symbol": symbol, "tf": timeframe, "signal": "LONG" if long_ok else "SHORT" if short_ok else "NEUTRALNY",
                "price": float(r["close"]), "adx": float(r["adx"]), "rsi": float(r["rsi"]), "reason": "OK"}
    except Exception as exc:
        return {"symbol": symbol, "tf": timeframe, "signal": "BŁĄD", "price": None,
                "adx": None, "rsi": None, "reason": str(exc)[:180]}
    finally:
        gc.collect()


def asfloat(value):
    try:
        number = float(value)
        return number if np.isfinite(number) else 0.
    except (TypeError, ValueError):
        return 0.


def balance_usdt(ex, positions=None):
    balance = ex.fetch_balance() or {}
    row = balance.get("USDT") if isinstance(balance.get("USDT"), dict) else {}
    free_map, used_map, total_map = balance.get("free") or {}, balance.get("used") or {}, balance.get("total") or {}

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
        free = 0.
    if total is None:
        total = free + (used or 0.)
    position_margin = sum(max(0., asfloat(p.get("initialMargin") or p.get("margin"))) for p in (positions or []))
    allocated = max(float(used or 0.), position_margin)
    if total > 0 and free >= total - max(.01, total*.001) and allocated > 0:
        free = max(0., total-allocated)
    return max(0., free), max(0., total)


def active_positions(ex):
    return [p for p in (ex.fetch_positions() or []) if abs(asfloat(p.get("contracts"))) > 0]


def market_order(ex, symbol, side, qty, reduce_only=False, reference_price=None):
    qty = float(ex.amount_to_precision(symbol, qty))
    if not np.isfinite(qty) or qty <= 0:
        raise ValueError("Ilość zlecenia jest nieprawidłowa.")
    if not reduce_only:
        price = asfloat(reference_price)
        if price <= 0:
            raise ValueError("Brak prawidłowej ceny do sprawdzenia wartości pozycji.")
        market = ex.market(symbol)
        notional = qty * price * (asfloat(market.get("contractSize")) or 1.)
        if not np.isfinite(notional) or notional < MIN_ORDER_NOTIONAL_USDT:
            raise ValueError(f"Wartość zlecenia {notional:.4f} USDT jest poniżej minimum 10 USDT.")
    return ex.create_order(symbol, "market", side, qty, None,
                           {"reduceOnly": True} if reduce_only else {})


def manage_position_exits(ex, positions, cfg):
    """ Monitoruje progi SL/TP w ROE i wysyła zlecenie reduce-only po ich osiągnięciu. Uwaga: to monitoring aplikacji, a nie natywne zlecenia ochronne na giełdzie. """
    sl_roe = max(0.1, float(cfg.get("sl_roe", 20.0)))
    tp_roe = max(0.1, float(cfg.get("tp_roe", 40.0)))
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

        # Bez wiarygodnego PnL i margin nie da się bezpiecznie wyliczyć ROE.
        if (not symbol or qty <= 0 or side not in ("long", "short")
                or margin <= 0 or pnl_value is None):
            continue

        roe = asfloat(pnl_value) / margin * 100.0
        reason = None
        if roe <= -sl_roe:
            reason = "STOP LOSS"
        if roe >= tp_roe:
            reason = "TAKE PROFIT"

        if reason is None:
            continue

        close_side = "sell" if side == "long" else "buy"
        try:
            order = market_order(ex, symbol, close_side, qty, reduce_only=True)
            msg = (
                f"{reason}: {side.upper()} {symbol}; "
                f"ROE={roe:.2f}%; order_id={order.get('id')}"
            )
            event("TRADE", msg)
            set_pair_cooldown(symbol, reason, 600)
            closed.append(msg)
        except Exception as exc:
            event("ERROR", f"{reason}: nie udało się zamknąć {symbol}: {exc}")

    return closed


def calc_qty(ex, symbol, total_usdt, free_usdt, price, cfg):
    price = asfloat(price)
    leverage = max(1, int(cfg.get("max_leverage", 10)))
    risk_budget = min(max(0.0, float(cfg.get("risk_usdt", 10.0))), max(0.0, total_usdt) * 0.05)
    sl_roe = float(cfg.get("sl_roe", 20.))
    if price <= 0 or sl_roe <= 0 or free_usdt <= 0:
        return 0., 0.
    stop_fraction = max(.001, (sl_roe/100.)/leverage)
    target = min(risk_budget/stop_fraction, max(0., float(cfg.get("max_notional_usdt", 200.))),
                 free_usdt*leverage*.90)
    target = max(MIN_ORDER_NOTIONAL_USDT, target)
    market = ex.market(symbol)
    contract_size = asfloat(market.get("contractSize")) or 1.
    min_amount = asfloat(((market.get("limits") or {}).get("amount") or {}).get("min"))
    qty = float(ex.amount_to_precision(symbol, target/(price*contract_size)))
    if min_amount > qty:
        qty = float(ex.amount_to_precision(symbol, min_amount))
    notional = qty*price*contract_size
    if not np.isfinite(qty) or qty <= 0 or notional < MIN_ORDER_NOTIONAL_USDT:
        return 0., 0.
    return qty, notional


def ranked_symbols(ex, limit_count):
    now = time.time()
    limit_count = max(1, int(limit_count))
    cache_key = f"ranked_symbols:{ex.id}:{ex.options.get('defaultType', '')}:{limit_count}"
    cached = st.session_state.get(cache_key)
    if cached and now-cached.get("ts", 0) < 180:
        return cached["ranked"]
    markets = ex.load_markets()
    candidates = [s for s, m in markets.items() if m.get("active") is not False and
                  m.get("quote") == "USDT" and m.get("linear") and m.get("swap", False)]
    ranked = []
    for offset in range(0, len(candidates), 40):
        batch = candidates[offset:offset+40]
        tickers = ex.fetch_tickers(batch)
        for symbol in batch:
            ticker = tickers.get(symbol) or {}
            volume = asfloat(ticker.get("quoteVolume"))
            if volume <= 0:
                volume = asfloat(ticker.get("baseVolume"))*asfloat(ticker.get("last"))
            if volume > 0:
                ranked.append((symbol, volume))
    ranked.sort(key=lambda x: x[1], reverse=True)
    ranked = ranked[:limit_count]
    st.session_state[cache_key] = {"ts": now, "ranked": ranked}
    gc.collect()
    return ranked


# -------------------- Sesja / logowanie --------------------
for key, default in {"authenticated": False, "logged_in": False, "username": "",
                     "user_id": None, "stripe_paid": 0, "user_email": ""}.items():
    if key not in st.session_state:
        st.session_state[key] = default
if "session_started_at" not in st.session_state:
    st.session_state["session_started_at"] = time.time()


def is_user_admin():
    return (str(st.session_state.get("user_email", "")).strip().lower() in ADMIN_EMAILS or
            str(st.session_state.get("username", "")).strip().lower() == "admin")


def is_user_paid():
    return bool(st.session_state.get("stripe_paid", 0)) or is_user_admin()


if st.query_params.get("success") == "true":
    st.info("Powrót z płatności. Administrator potwierdzi płatność przed aktywacją dostępu.")
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
                    row = con.execute("SELECT id,password,stripe_paid,email,username FROM users WHERE username=? OR email=?",
                                      (login_name.strip(), login_name.strip().lower())).fetchone()
                valid, legacy = verify_password(row["password"], login_pass) if row else (False, False)
                if row and valid:
                    if legacy:
                        with db() as con:
                            con.execute("UPDATE users SET password=? WHERE id=?", (password_hash(login_pass), row["id"]))
                            con.commit()
                    st.session_state.update(authenticated=True, logged_in=True, user_id=row["id"],
                                            stripe_paid=row["stripe_paid"], user_email=(row["email"] or "").lower(),
                                            username=row["username"], session_started_at=time.time())
                    st.rerun()
                else:
                    st.error("Nieprawidłowy login lub hasło.")
    with reg_tab:
        st.subheader("Rejestracja - 49 PLN / miesiąc")
        with st.form("reg_form"):
            reg_user = st.text_input("Nazwa użytkownika")
            reg_email = st.text_input("Adres e-mail")
            reg_pass = st.text_input("Hasło", type="password")
            reg_plan = st.selectbox("Subskrypcja", ["Pro Trader (49 PLN / miesiąc)", "VIP SaaS (Roczny)"])
            submit_reg = st.form_submit_button("ZAREJESTRUJ SIĘ", use_container_width=True)
            if submit_reg:
                if not reg_user.strip() or not reg_pass.strip() or not reg_email.strip():
                    st.error("Uzupełnij login, e-mail i hasło.")
                if "@" not in reg_email or "." not in reg_email.rsplit("@", 1)[-1]:
                    st.error("Podaj prawidłowy adres e-mail.")
                else:
                    try:
                        with db() as con:
                            con.execute("INSERT INTO users(username,password,subscription,stripe_paid,email) VALUES(?,?,?,0,?)",
                                        (reg_user.strip(), password_hash(reg_pass), reg_plan, reg_email.strip().lower()))
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
    pages = ["Automatyczny Skaner i Auto-Handel", "Ustawienia Strategii",
             "Połączenie API", "Dziennik", "Regulamin i Instrukcja"]
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
        st.link_button("OPŁAĆ SUBSKRYPCJĘ (49 PLN)", create_stripe_checkout_url(), use_container_width=True)
    except Exception as exc:
        st.error(f"Błąd linku Stripe: {exc}")
    st.caption("Po płatności administrator potwierdza transakcję.")
    if st.button("Wyloguj", use_container_width=True):
        for key, default in [("authenticated", False), ("logged_in", False), ("username", ""),
                             ("user_id", None), ("stripe_paid", 0), ("user_email", "")]:
            st.session_state[key] = default
        st.rerun()
    if st.button("Wyczyść cache danych", use_container_width=True):
        get_candles.clear()
        st.cache_data.clear()
        st.cache_resource.clear()
        st.success("Cache wyczyszczony. Odśwież stronę.")

st.markdown('<div class="brand">Bitget-SaaS Futures</div><div>AUTONOMICZNY SYSTEM TRANSAKCYJNY</div>', unsafe_allow_html=True)


# -------------------- Pulpit --------------------
if page == "Automatyczny Skaner i Auto-Handel":
    st.subheader("Główny Pulpit Transakcyjny - Podgląd na żywo")
    with st.expander("Ustawienia trybu pracy", expanded=False):
        with st.form("control_form"):
            c1, c2 = st.columns(2)
            with c1:
                auto_trade = st.checkbox("Włącz automatyczny handel", value=bool(cfg["auto_trade"]))
                paper_mode = st.checkbox("Tryb PAPER - bez zleceń na giełdzie", value=bool(cfg["paper_mode"]))
            with c2:
                auto_refresh = st.checkbox("Włącz ciągłe skanowanie", value=bool(cfg["auto_refresh"]))
                refresh_seconds = st.slider("Odstęp odświeżania (s)", 10, 120, int(cfg["refresh_seconds"]))
            if st.form_submit_button("ZAPISZ USTAWIENIA PRACY", use_container_width=True):
                cfg.update(auto_trade=auto_trade, paper_mode=paper_mode,
                           auto_refresh=auto_refresh, refresh_seconds=refresh_seconds)
                save_cfg(cfg)
                st.rerun()

    refresh_sec = max(10, int(cfg.get("refresh_seconds", 30)))

    @st.fragment(run_every=refresh_sec if cfg.get("auto_refresh", True) else None)
    def render_full_dashboard():
        st.caption(f"Odświeżanie co {refresh_sec} s.")
        total_balance = free_balance = session_pnl = used_margin = 0.
        active = []
        connected = bool(api_key_saved and secret_saved)
        api_ok = False
        if connected:
            try:
                client = exchange_client(ex_id, api_key_saved, secret_saved, passphrase_saved, cfg["market_type"])
                active = active_positions(client)
                if not cfg.get("paper_mode", True) and active:
                    for msg in manage_position_exits(client, active, cfg):
                        st.warning(msg)
                    active = active_positions(client)
                free_balance, total_balance = balance_usdt(client, active)
                session_pnl = sum(asfloat(p.get("unrealizedPnl")) for p in active)
                used_margin = sum(asfloat(p.get("initialMargin") or p.get("margin")) for p in active)
                api_ok = True
            except Exception as exc:
                st.warning(f"Błąd połączenia z giełdą / pozycjami: {exc}")
                client = None
        else:
            client = None

        def metric_card(label, value, note="", tone=""):
            st.markdown(f'<div class="metric-card"><div class="metric-label">{label}</div>'
                        f'<div class="metric-value">{value}</div><div class="metric-note">{note}</div></div>',
                        unsafe_allow_html=True)

        m1, m2, m3, m4 = st.columns(4, gap="medium")
        with m1:
            metric_card("Saldo / wolne środki", f"{total_balance:.2f} / {free_balance:.2f} USDT", "Saldo całkowite / dostępne")
        with m2:
            metric_card("Niezrealizowany PnL", f"{session_pnl:+.2f} USDT", "Łączny PnL otwartych pozycji")
        with m3:
            metric_card("Otwarte pozycje", f"{len(active)} / {int(cfg['max_positions'])}",
                        f"Margin w użyciu: {used_margin:.2f} USDT")
        with m4:
            elapsed = max(0, int(time.time() - st.session_state["session_started_at"]))
            clock = f"{elapsed//3600:02d}:{(elapsed%3600)//60:02d}:{elapsed%60:02d}"
            metric_card("Czas sesji", clock, f"Odświeżanie co {refresh_sec}s")

        st.divider()
        st.markdown("### Aktywne pozycje na giełdzie")
        if active:
            st.dataframe(pd.DataFrame([{"Symbol": p.get("symbol"), "Strona": str(p.get("side")).upper(),
                "Kontrakty": p.get("contracts"), "Cena wejścia": p.get("entryPrice"),
                "PnL (USDT)": p.get("unrealizedPnl"), "Margin (USDT)": p.get("initialMargin")}
                for p in active]), use_container_width=True, hide_index=True)
        if connected and api_ok:
            st.info("Brak otwartych pozycji.")
        else:
            st.warning("Brak połączenia API - podaj klucze w zakładce Połączenie API.")

        st.divider()
        st.markdown("### Wyniki skanera rynku i sygnały")
        if not is_user_paid():
            st.error("Subskrypcja nieaktywna. Handel LIVE jest zablokowany.")
        try:
            # Skanowanie rynku korzysta z publicznego klienta, niezależnie od kluczy użytkownika.
            ex = exchange_client(cfg["exchange"], "", "", "", cfg["market_type"])
            ranked = ranked_symbols(ex, int(cfg.get("scan_limit_count", 30)))
            symbols = [x[0] for x in ranked]
            volume_map = dict(ranked)
            tfs = [tf for tf in cfg.get("timeframes", ["4h", "1d"]) if tf in TF_OPTIONS]
            st.caption(f"Przeskanowano {len(symbols)} par. Interwały: {', '.join(tfs)}")
            results = []
            for symbol in symbols:
                for tf in tfs:
                    res = signal_for_symbol(cfg, symbol, tf)
                    res["volume_24h_usdt"] = volume_map.get(symbol, 0.)
                    results.append(res)
                    if res["signal"] not in ("LONG", "SHORT"):
                        continue
                    event("INFO", f"Sygnał {res['signal']} {symbol} [{tf}]")
                    if not cfg["auto_trade"] or not is_user_paid() or cfg["paper_mode"]:
                        continue
                    if not (api_key_saved and secret_saved and res.get("price")):
                        continue
                    try:
                        live = exchange_client(ex_id, api_key_saved, secret_saved, passphrase_saved, cfg["market_type"])
                        # Blokada ponownego wejścia na tę samą parę przez 10 minut po SL/TP.
                        cooldown_left = pair_cooldown_remaining(symbol, 600)
                        if cooldown_left > 0:
                            event("INFO", f"Pominięto {symbol}: blokada po SL/TP, pozostało {cooldown_left}s.")
                            continue

                        positions = active_positions(live)
                        current_symbols = {str(p.get("symbol")) for p in positions if p.get("symbol")}
                        if len(positions) >= int(cfg["max_positions"]) or symbol in current_symbols:
                            continue
                        free, total = balance_usdt(live, positions)
                        qty, notional = calc_qty(live, symbol, total, free, res["price"], cfg)
                        if qty <= 0:
                            event("WARNING", f"Pominięto {symbol}: ilość lub wartość poniżej minimum.")
                            continue
                        try:
                            live.set_leverage(int(cfg["max_leverage"]), symbol)
                        except Exception:
                            pass
                        side = "buy" if res["signal"] == "LONG" else "sell"
                        order = market_order(live, symbol, side, qty, reference_price=res["price"])
                        event("TRADE", f"Otwarto {res['signal']} {symbol} qty={qty} notional={notional:.2f} USDT; ID={order.get('id')}")
                    except Exception as exc:
                        event("ERROR", f"Nie otwarto pozycji {symbol}: {exc}")
            if results:
                st.dataframe(pd.DataFrame(results), use_container_width=True, hide_index=True)
            else:
                st.info("Brak wyników skanowania.")
        except Exception as exc:
            st.error(f"Błąd skanowania giełdy: {exc}")
        finally:
            gc.collect()

    render_full_dashboard()
    st.divider()
    st.markdown("### Awaryjne zamknięcie wszystkich pozycji")
    st.warning("To polecenie wysyła prawdziwe zlecenia rynkowe.")
    if st.button("ZAMKNIJ WSZYSTKIE POZYCJE"):
        try:
            if not (api_key_saved and secret_saved):
                raise RuntimeError("Brak kluczy API.")
            client = exchange_client(ex_id, api_key_saved, secret_saved, passphrase_saved, cfg["market_type"])
            outcomes = []
            for pos in active_positions(client):
                qty, symbol = abs(asfloat(pos.get("contracts"))), pos.get("symbol")
                if qty <= 0 or not symbol:
                    continue
                side = "sell" if str(pos.get("side") or "").lower() in ("long", "buy") else "buy"
                try:
                    order = market_order(client, symbol, side, qty, reduce_only=True)
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
    if "selected_tf_edit" not in st.session_state:
        st.session_state["selected_tf_edit"] = "1d"
    selected_tf = st.selectbox("Interwał do edycji", TF_OPTIONS,
                               index=TF_OPTIONS.index(st.session_state["selected_tf_edit"]))
    st.session_state["selected_tf_edit"] = selected_tf
    base = cfg["tf_settings"].get(selected_tf, DEFAULT_TF_SETTINGS[selected_tf])
    with st.form("cfgform"):
        left, right = st.columns(2)
        with left:
            exchange_name = st.selectbox("Giełda", ["bitget", "binanceusdm", "bybit", "okx"],
                index=["bitget", "binanceusdm", "bybit", "okx"].index(cfg["exchange"]) if cfg["exchange"] in ["bitget", "binanceusdm", "bybit", "okx"] else 0)
            market_type = st.selectbox("Rynek", ["swap", "future"], index=0 if cfg["market_type"] == "swap" else 1)
            scan_limit = st.slider("Liczba skanowanych par", 5, 200, int(cfg.get("scan_limit_count", 30)))
            timeframes = st.multiselect("Interwały skanowania", TF_OPTIONS,
                default=[x for x in cfg.get("timeframes", ["4h", "1d"]) if x in TF_OPTIONS])
            multiplier = st.slider("Mnożnik progów ADX (%)", 10, 150, int(cfg.get("indicator_multiplier", 100)))
            candle_limit = st.slider("Liczba świec do analizy", 100, 250, min(250, int(cfg.get("candle_limit", 150))))
        with right:
            risk = st.number_input("Maks. ryzyko na pozycję (USDT)", 1., 10000., float(cfg["risk_usdt"]))
            max_notional = st.number_input("Maks. wartość pozycji (USDT)", 10., 100000., float(cfg["max_notional_usdt"]))
            max_positions = st.number_input("Maks. liczba otwartych pozycji", 1, 20, int(cfg["max_positions"]))
            max_leverage = st.number_input("Maksymalna dźwignia", 1, 50, int(cfg["max_leverage"]))
            sl_roe = st.slider("Stop Loss — ROE (%)", 1, 95, int(cfg["sl_roe"]), 1,
                               help="Próba zamknięcia pozycji przy ROE równym minus tej wartości.")
            tp_roe = st.slider("Take Profit — ROE (%)", 1, 500, int(cfg["tp_roe"]), 1,
                               help="Próba zamknięcia pozycji przy ROE równym tej dodatniej wartości.")
            allow_long = st.checkbox("Pozwól na LONG", bool(cfg["allow_long"]))
            allow_short = st.checkbox("Pozwól na SHORT", bool(cfg["allow_short"]))
        st.markdown(f"### Parametry bazowe dla {selected_tf}")
        c1, c2, c3, c4, c5 = st.columns(5)
        with c1:
            fast = st.number_input("EMA szybka", 2, 100, int(base["ema_fast"]))
        with c2:
            slow = st.number_input("EMA wolna", 3, 300, int(base["ema_slow"]))
        with c3:
            adx = st.number_input("Minimalny ADX", 0., 100., float(base["adx_threshold"]))
        with c4:
            rmin = st.number_input("RSI minimum", 0., 100., float(base["rsi_min"]))
        with c5:
            rmax = st.number_input("RSI maksimum", 0., 100., float(base["rsi_max"]))
        save = st.form_submit_button("ZAPISZ USTAWIENIA", use_container_width=True)
        if save:
            if fast >= slow:
                st.error("EMA szybka musi być mniejsza od EMA wolnej.")
            if rmin >= rmax:
                st.error("RSI minimum musi być mniejsze od RSI maksimum.")
            else:
                cfg.update(exchange=exchange_name, market_type=market_type, scan_limit_count=scan_limit,
                           timeframes=timeframes or ["4h", "1d"], indicator_multiplier=multiplier,
                           candle_limit=candle_limit, risk_usdt=risk, max_notional_usdt=max_notional,
                           max_positions=int(max_positions), max_leverage=int(max_leverage),
                           sl_roe=float(sl_roe), tp_roe=float(tp_roe),
                           allow_long=allow_long, allow_short=allow_short)
                cfg["tf_settings"][selected_tf] = {"ema_fast": int(fast), "ema_slow": int(slow),
                    "adx_threshold": float(adx), "rsi_min": float(rmin), "rsi_max": float(rmax)}
                save_cfg(cfg)
                exchange_client.clear()
                get_candles.clear()
                st.cache_data.clear()
                gc.collect()
                st.success("Zapisano ustawienia.")
                st.rerun()


# -------------------- Połączenie API --------------------
if page == "Połączenie API":
    st.subheader("Połączenie z giełdą")
    with st.form("credentials"):
        exchange_choice = st.selectbox("Giełda", ["bitget", "binanceusdm", "bybit", "okx"],
            index=["bitget", "binanceusdm", "bybit", "okx"].index(ex_id) if ex_id in ["bitget", "binanceusdm", "bybit", "okx"] else 0)
        api_key_input = st.text_input("API Key", value=api_key_saved, type="password")
        secret_input = st.text_input("API Secret", value=secret_saved, type="password")
        pass_input = st.text_input("Passphrase (Bitget/OKX)", value=passphrase_saved, type="password")
        if st.form_submit_button("ZAPISZ DANE API"):
            save_creds(current_user_id, exchange_choice, api_key_input.strip(), secret_input.strip(), pass_input.strip())
            exchange_client.clear()
            st.cache_data.clear()
            gc.collect()
            st.success("Dane API zapisane dla Twojego konta.")
            st.rerun()
    if st.button("Testuj API i pobierz saldo"):
        try:
            client = exchange_client(ex_id, api_key_saved, secret_saved, passphrase_saved, cfg["market_type"])
            free, total = balance_usdt(client)
            st.success("Połączenie działa.")
            c1, c2 = st.columns(2)
            c1.metric("Wolne środki", f"{free:.4f} USDT")
            c2.metric("Saldo Futures", f"{total:.4f} USDT")
        except Exception as exc:
            st.error(f"Błąd API: {exc}")


# -------------------- Dziennik --------------------
if page == "Dziennik":
    st.subheader("Zdarzenia i zlecenia bota")
    with db() as con:
        rows = con.execute("SELECT ts,level,message FROM events ORDER BY id DESC LIMIT 300").fetchall()
    if rows:
        st.dataframe(pd.DataFrame([tuple(r) for r in rows], columns=["Czas UTC", "Poziom", "Wiadomość"]),
                     use_container_width=True, hide_index=True)
    else:
        st.info("Brak zdarzeń.")


# -------------------- Instrukcja i regulamin --------------------
if page == "Regulamin i Instrukcja":
    st.subheader("Instrukcja obsługi i regulamin")
    tab_help, tab_terms = st.tabs(["Instrukcja", "Regulamin"])
    with tab_help:
        st.markdown("""1. Utwórz konto i zaloguj się. 2. Administrator potwierdza płatność i aktywuje dostęp. 3. Utwórz klucz API z uprawnieniami odczytu i handlu Futures. Nie włączaj wypłat. 4. Zapisz dane API w zakładce Połączenie API. 5. Ustaw interwały, wskaźniki, limity pozycji oraz SL/TP. 6. Najpierw testuj w trybie PAPER.""")
    with tab_terms:
        st.markdown("""**Regulamin Bitget-SaaS Futures** 1. Serwis udostępnia narzędzia do analizy rynku i składania zleceń. 2. Użytkownik odpowiada za klucze API i konfigurację ryzyka. 3. Futures wiąże się z ryzykiem utraty kapitału; wyniki nie są gwarantowane. 4. Dostęp płatny kosztuje 49 PLN miesięcznie.""")


# -------------------- Panel administratora --------------------
if page == "Panel Administratora" and is_user_admin():
    st.subheader("Zarządzanie użytkownikami i subskrypcjami")
    with db() as con:
        rows = con.execute("SELECT id,username,email,subscription,stripe_paid FROM users ORDER BY id").fetchall()
    if rows:
        df = pd.DataFrame([tuple(r) for r in rows],
                          columns=["ID", "Użytkownik", "E-mail", "Pakiet", "Opłacone (0/1)"])
        st.dataframe(df, use_container_width=True, hide_index=True)
        with st.form("admin_manage_form"):
            selected_user = st.selectbox("Wybierz użytkownika", df["ID"].tolist())
            action = st.selectbox("Operacja", ["Aktywuj subskrypcję", "Odbierz subskrypcję", "Usuń użytkownika"])
            confirm = st.checkbox("Potwierdzam operację")
            go = st.form_submit_button("WYKONAJ", use_container_width=True)
            if go:
                if not confirm:
                    st.error("Zaznacz potwierdzenie.")
                else:
                    with db() as con:
                        if action == "Aktywuj subskrypcję":
                            con.execute("UPDATE users SET stripe_paid=1 WHERE id=?", (selected_user,))
                        if action == "Odbierz subskrypcję":
                            con.execute("UPDATE users SET stripe_paid=0 WHERE id=?", (selected_user,))
                        else:
                            con.execute("DELETE FROM users WHERE id=?", (selected_user,))
                            con.execute("DELETE FROM user_credentials WHERE user_id=?", (selected_user,))
                        con.commit()
                    event("ADMIN", f"{action}; user_id={selected_user}")
                    st.success("Operacja wykonana.")
                    st.rerun()
    else:
        st.info("Brak użytkowników.")

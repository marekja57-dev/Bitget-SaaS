# -*- coding: utf-8 -*-
"""
Bitget-SaaS Futures - kompletna aplikacja Streamlit.
Uwaga: handel futures wiąże się z ryzykiem utraty kapitału.
Najpierw testuj w trybie PAPER. Klucze API nie powinny mieć uprawnień wypłat.
"""
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


# ========================================================
# KONFIGURACJA APLIKACJI
# ========================================================
st.set_page_config(page_title="Bitget-SaaS Futures", page_icon="📈", layout="wide")

APP_DIR = Path(__file__).resolve().parent
DB_PATH = Path(os.getenv("BITGET_SAAS_DB", str(APP_DIR / "bitget_saas.db")))
LOG_PATH = APP_DIR / "trading.log"
logging.basicConfig(
    filename=str(LOG_PATH),
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s"
)

# Prawidłowy Payment Link ze Stripe
STRIPE_CHECKOUT_FALLBACK = os.getenv(
    "STRIPE_CHECKOUT_FALLBACK",
    "https://buy.stripe.com/8x2dRa4CbdaxfSAF6V3oA03",
)
ADMIN_EMAILS = {"marekja57@wp.pl", "admin@bot-bitget.pl"}

TF_OPTIONS = ["1m", "3m", "5m", "15m", "30m", "1h", "2h", "4h", "1d"]
MIN_ORDER_NOTIONAL_USDT = 10.0
MIN_MARGIN_USDT = 10.0 # Twardy wymóg: minimum 10 USDT czystego depozytu z portfela

DEFAULT_TF_SETTINGS = {
    "1m": {"ema_fast": 9, "ema_slow": 21, "adx_threshold": 25.0, "rsi_min": 25.0, "rsi_max": 75.0},
    "3m": {"ema_fast": 9, "ema_slow": 21, "adx_threshold": 25.0, "rsi_min": 25.0, "rsi_max": 75.0},
    "5m": {"ema_fast": 9, "ema_slow": 21, "adx_threshold": 25.0, "rsi_min": 25.0, "rsi_max": 75.0},
    "15m": {"ema_fast": 9, "ema_slow": 21, "adx_threshold": 25.0, "rsi_min": 25.0, "rsi_max": 75.0},
    "30m": {"ema_fast": 9, "ema_slow": 21, "adx_threshold": 25.0, "rsi_min": 25.0, "rsi_max": 75.0},
    "1h": {"ema_fast": 12, "ema_slow": 26, "adx_threshold": 22.0, "rsi_min": 30.0, "rsi_max": 70.0},
    "2h": {"ema_fast": 12, "ema_slow": 26, "adx_threshold": 20.0, "rsi_min": 30.0, "rsi_max": 70.0},
    "4h": {"ema_fast": 20, "ema_slow": 50, "adx_threshold": 20.0, "rsi_min": 30.0, "rsi_max": 70.0},
    "1d": {"ema_fast": 40, "ema_slow": 140, "adx_threshold": 15.0, "rsi_min": 35.0, "rsi_max": 65.0},
}
DEFAULTS = {
    "exchange": "bitget",
    "market_type": "swap",
    "candle_limit": 180,
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
    "scan_limit_count": 30,
    "indicator_multiplier": 100,
}

CSS = """
<style>
    :root { color-scheme: dark; --gold:#d8ad52; --gold-soft:#f3d88a; }
    .stApp {
        background: radial-gradient(ellipse at 40% -20%, #103e78 0%, #071a36 42%, #050e20 100%);
        color: #eaf3ff;
    }
    [data-testid="stHeader"] { background: rgba(3,12,29,.96); }
    [data-testid="stAppViewContainer"] .main .block-container {
        padding-top: 2rem;
        max-width: 1600px;
    }
    [data-testid="stSidebar"] {
        background: linear-gradient(180deg, #06152d, #081f42);
        border-right: 1px solid #164a84;
    }
    .brand-retro {
        font-weight: 900;
        font-size: 38px;
        letter-spacing: -1px;
        color: #f3c653;
        text-shadow: 2px 2px 4px rgba(0,0,0,.6);
        text-align: center;
        margin-bottom: 0;
        font-family: serif;
    }
    .subbrand-retro {
        color: #7da9d8;
        font-size: 12px;
        letter-spacing: 2px;
        text-transform: uppercase;
        text-align: center;
        margin-bottom: 20px;
    }
    .brand {
        font-weight: 900;
        font-size: clamp(24px, 2.5vw, 34px);
        color: #eaf5ff;
        margin: .5rem 0;
    }
    .brand span { color: #28a8ff; }
    .subbrand {
        color: #7da9d8;
        font-size: 11px;
        letter-spacing: 1.5px;
        margin-bottom: 1.5rem;
    }
    .panel {
        background: linear-gradient(145deg, rgba(12,43,83,.95), rgba(5,24,51,.96));
        border: 1px solid #164a80;
        border-radius: 14px;
        padding: 16px 18px;
        box-shadow: 0 4px 12px rgba(0,0,0,.3);
    }
    .metric-card {
        border: 1px solid var(--gold);
        border-radius: 14px;
        padding: 18px 20px;
        height: 150px;
        box-sizing: border-box;
        display: flex;
        flex-direction: column;
        justify-content: center;
        background: linear-gradient(145deg, rgba(27,43,68,.96), rgba(6,18,37,.98));
        box-shadow: 0 0 0 1px rgba(216,173,82,.12), 0 8px 24px rgba(0,0,0,.24);
        overflow: hidden;
    }
    .metric-card .metric-label {
        color: #b9c9df;
        font-size: 12px;
        font-weight: 700;
        letter-spacing: 1px;
        text-transform: uppercase;
        margin-bottom: 10px;
    }
    .metric-card .metric-value {
        color: #fff2c7;
        font-size: clamp(20px, 1.8vw, 29px);
        font-weight: 850;
        line-height: 1.2;
        overflow-wrap: anywhere;
    }
    .metric-card .metric-note {
        color: #a9bdd7;
        font-size: 12px;
        margin-top: 8px;
    }
    .metric-card.green .metric-value { color: #70e0ae; }
    .metric-card.blue .metric-value { color: #83c7ff; }
    .metric-card.red .metric-value { color: #ff9696; }
    .metric-card.gold .metric-value { color: #fff2c7; }
    div.stButton>button {
        border: 1px solid #278be8;
        border-radius: 8px;
        background: linear-gradient(180deg, #1689ff, #0759c8);
        color: white;
        font-weight: 700;
    }
    hr { border-color: #16416f; }
</style>
"""
st.markdown(CSS, unsafe_allow_html=True)


# ========================================================
# BAZA DANYCH I KONFIGURACJA
# ========================================================
def db():
    con = sqlite3.connect(DB_PATH, timeout=20)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("PRAGMA busy_timeout=20000")
    con.execute("""CREATE TABLE IF NOT EXISTS settings (k TEXT PRIMARY KEY, v TEXT NOT NULL)""")
    con.execute("""CREATE TABLE IF NOT EXISTS credentials (k TEXT PRIMARY KEY, exchange TEXT, api_key TEXT, secret TEXT, password TEXT)""")
    con.execute("""CREATE TABLE IF NOT EXISTS events (id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT, level TEXT, message TEXT)""")
    con.execute("""CREATE TABLE IF NOT EXISTS users (id INTEGER PRIMARY KEY AUTOINCREMENT, username TEXT UNIQUE NOT NULL, password TEXT NOT NULL, subscription TEXT, stripe_paid INTEGER NOT NULL DEFAULT 0, email TEXT UNIQUE)""")
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
    with db() as con:
        row = con.execute("SELECT v FROM settings WHERE k='main'").fetchone()
    if row:
        try:
            saved = json.loads(row["v"])
            cfg.update(saved)
            merged = json.loads(json.dumps(DEFAULT_TF_SETTINGS))
            merged.update(cfg.get("tf_settings", {}))
            cfg["tf_settings"] = merged
        except Exception:
            logging.exception("Nie udało się odczytać ustawień")
    return cfg


def save_cfg(cfg):
    with db() as con:
        con.execute(
            """INSERT INTO settings(k,v) VALUES('main',?) ON CONFLICT(k) DO UPDATE SET v=excluded.v""",
            (json.dumps(cfg, ensure_ascii=False),)
        )
        con.commit()


def event(level, msg):
    logging.log(getattr(logging, str(level).upper(), logging.INFO), str(msg))
    with db() as con:
        con.execute(
            "INSERT INTO events(ts,level,message) VALUES(?,?,?)",
            (datetime.now(timezone.utc).isoformat(), str(level), str(msg)[:1500])
        )
        con.commit()


def load_creds():
    with db() as con:
        row = con.execute("SELECT exchange,api_key,secret,password FROM credentials WHERE k='main'").fetchone()
    return tuple(row) if row else ("bitget", "", "", "")


def save_creds(ex, key, secret, passphrase):
    with db() as con:
        con.execute(
            """INSERT INTO credentials(k,exchange,api_key,secret,password) VALUES('main',?,?,?,?) ON CONFLICT(k) DO UPDATE SET exchange=excluded.exchange,api_key=excluded.api_key, secret=excluded.secret,password=excluded.password""",
            (ex, key, secret, passphrase)
        )
        con.commit()


def create_stripe_checkout_url(email):
    url = STRIPE_CHECKOUT_FALLBACK.strip()
    if not url.startswith("https://buy.stripe.com/"):
        raise ValueError("W STRIPE_CHECKOUT_FALLBACK wstaw dokładny aktywny link https://buy.stripe.com/... z panelu Stripe.")
    return url


# ========================================================
# GIEŁDA / WSKAŹNIKI
# ========================================================
@st.cache_resource(show_spinner=False)
def exchange_client(ex_id, api_key, secret, passphrase, market_type):
    if ccxt is None:
        raise RuntimeError("Brak biblioteki ccxt. Zainstaluj: pip install ccxt")
    cls = getattr(ccxt, ex_id, None)
    if cls is None:
        raise ValueError("Nieobsługiwana giełda: " + str(ex_id))
    opts = {
        "enableRateLimit": True,
        "timeout": 25000,
        "options": {"defaultType": market_type, "defaultSubType": "linear"}
    }
    if api_key and secret:
        opts.update(apiKey=api_key, secret=secret)
    if passphrase:
        opts["password"] = passphrase
    return cls(opts)


@st.cache_data(ttl=20, max_entries=20, show_spinner=False)
def get_candles(ex_id, market_type, symbol, tf, limit):
    ex = exchange_client(ex_id, "", "", "", market_type)
    raw = ex.fetch_ohlcv(symbol, timeframe=tf, limit=int(limit))
    return pd.DataFrame(raw, columns=["timestamp", "open", "high", "low", "close", "volume"])


def indicators(df, fast, slow):
    d = df.copy()
    for col in ["open", "high", "low", "close", "volume"]:
        d[col] = pd.to_numeric(d[col], errors="coerce")
    d = d.dropna(subset=["high", "low", "close"]).reset_index(drop=True)
    d["ema_fast"] = d.close.ewm(span=int(fast), adjust=False).mean()
    d["ema_slow"] = d.close.ewm(span=int(slow), adjust=False).mean()
    delta = d.close.diff()
    gain = delta.clip(lower=0).ewm(alpha=1/14, adjust=False).mean()
    loss = (-delta.clip(upper=0)).ewm(alpha=1/14, adjust=False).mean()
    rs = gain / loss.replace(0, np.nan)
    d["rsi"] = 100 - 100 / (1 + rs)
    tr = pd.concat([
        (d.high - d.low).abs(),
        (d.high - d.close.shift()).abs(),
        (d.low - d.close.shift()).abs()
    ], axis=1).max(axis=1)
    up, down = d.high.diff(), -d.low.diff()
    plus = pd.Series(np.where((up > down) & (up > 0), up, 0), index=d.index)
    minus = pd.Series(np.where((down > up) & (down > 0), down, 0), index=d.index)
    atr = tr.ewm(alpha=1/14, adjust=False).mean().replace(0, np.nan)
    pdi = 100 * plus.ewm(alpha=1/14, adjust=False).mean() / atr
    mdi = 100 * minus.ewm(alpha=1/14, adjust=False).mean() / atr
    dx = 100 * (pdi - mdi).abs() / (pdi + mdi).replace(0, np.nan)
    d["adx"] = dx.ewm(alpha=1/14, adjust=False).mean()
    return d


def get_effective_tf_cfg(cfg, tf):
    base = cfg.get("tf_settings", {}).get(tf, DEFAULT_TF_SETTINGS.get(tf, DEFAULT_TF_SETTINGS["1h"]))
    mult = float(cfg.get("indicator_multiplier", 100)) / 100.0
    return {
        "ema_fast": max(2, int(round(float(base["ema_fast"]) * mult))),
        "ema_slow": max(3, int(round(float(base["ema_slow"]) * mult))),
        "adx_threshold": max(2.0, min(90.0, float(base["adx_threshold"]) * mult)),
        "rsi_min": max(2.0, min(45.0, float(base["rsi_min"]))),
        "rsi_max": max(55.0, min(98.0, float(base["rsi_max"]))),
    }


def signal_for_symbol(cfg, symbol, tf):
    try:
        t = get_effective_tf_cfg(cfg, tf)
        raw = get_candles(cfg["exchange"], cfg["market_type"], symbol, tf, cfg["candle_limit"])
        d = indicators(raw.iloc[:-1].copy(), t["ema_fast"], t["ema_slow"])
        if len(d) < 35:
            return {"symbol": symbol, "tf": tf, "signal": "NEUTRALNY", "reason": "Za mało świec"}
        r = d.iloc[-1]
        long_ok = (
            cfg["allow_long"] and r.ema_fast > r.ema_slow and
            r.adx >= t["adx_threshold"] and t["rsi_min"] <= r.rsi <= t["rsi_max"] and
            r.close > r.ema_fast
        )
        short_ok = (
            cfg["allow_short"] and r.ema_fast < r.ema_slow and
            r.adx >= t["adx_threshold"] and t["rsi_min"] <= r.rsi <= t["rsi_max"] and
            r.close < r.ema_fast
        )
        sig = "LONG" if long_ok else "SHORT" if short_ok else "NEUTRALNY"
        return {
            "symbol": symbol, "tf": tf, "signal": sig, "price": float(r.close),
            "adx": float(r.adx), "rsi": float(r.rsi), "reason": "OK"
        }
    except Exception as exc:
        return {"symbol": symbol, "tf": tf, "signal": "BŁĄD", "reason": str(exc)[:160]}
    finally:
        gc.collect()


def _as_float(value):
    try:
        number = float(value)
        return number if np.isfinite(number) else 0.0
    except (TypeError, ValueError):
        return 0.0


def balance_usdt(ex, positions=None):
    balance = ex.fetch_balance() or {}
    free_map, used_map, total_map = balance.get("free") or {}, balance.get("used") or {}, balance.get("total") or {}
    row = balance.get("USDT") if isinstance(balance.get("USDT"), dict) else {}

    def number(*values):
        for value in values:
            if value is None or value == "":
                continue
            try:
                n = float(value)
                if np.isfinite(n) and n >= 0:
                    return n
            except (TypeError, ValueError):
                continue
        return None

    free = number(row.get("free"), free_map.get("USDT"))
    used = number(row.get("used"), used_map.get("USDT"))
    total = number(row.get("total"), total_map.get("USDT"))
    if free is None:
        free = 0.0
    if total is None:
        total = free + used if used is not None else free
    return max(0.0, float(free)), max(0.0, float(total))


def active_positions(ex):
    positions = ex.fetch_positions() or []
    return [p for p in positions if abs(_as_float(p.get("contracts"))) > 0]


def market_order(ex, symbol, side, qty, reduce_only=False, reference_price=None):
    qty = float(ex.amount_to_precision(symbol, qty))
    if not np.isfinite(qty) or qty <= 0:
        raise ValueError("Ilość zlecenia wynosi zero lub jest nieprawidłowa")

    if not reduce_only:
        price = _as_float(reference_price)
        if price <= 0:
            raise ValueError("Zablokowano otwarcie pozycji: brak prawidłowej ceny do sprawdzenia wartości.")
        market = ex.market(symbol)
        contract_size = _as_float(market.get("contractSize")) or 1.0
        notional = qty * price * contract_size
        if not np.isfinite(notional) or notional < MIN_ORDER_NOTIONAL_USDT:
            raise ValueError(f"Zablokowano zlecenie: wartość wynosi {notional:.4f} USDT, minimum to {MIN_ORDER_NOTIONAL_USDT:.2f} USDT.")

    params = {"reduceOnly": True} if reduce_only else {}
    return ex.create_order(symbol, "market", side, qty, None, params)


def calc_qty(ex, symbol, total_usdt, free_usdt, price, cfg):
    price = _as_float(price)
    total_usdt, free_usdt = max(0.0, _as_float(total_usdt)), max(0.0, _as_float(free_usdt))
    leverage = max(1, int(cfg["max_leverage"]))
    risk_limit, max_notional = max(0.0, float(cfg["risk_usdt"])), max(0.0, float(cfg["max_notional_usdt"]))
    sl_roe = float(cfg["sl_roe"])
    if price <= 0 or sl_roe <= 0:
        return 0.0, 0.0

    risk_budget = min(risk_limit, total_usdt * 0.05)
    stop_fraction = max(0.001, (sl_roe / 100.0) / leverage)
    risk_based_notional = risk_budget / stop_fraction
    margin_budget = free_usdt * 0.90
    
    target = min(risk_based_notional, max_notional, margin_budget * leverage)
    min_required_notional = max(MIN_ORDER_NOTIONAL_USDT, MIN_MARGIN_USDT * leverage)
    
    market = ex.market(symbol)
    contract_size = _as_float(market.get("contractSize")) or 1.0
    limits = market.get("limits") or {}
    min_cost = _as_float((limits.get("cost") or {}).get("min"))
    min_amount = _as_float((limits.get("amount") or {}).get("min"))
    
    required = max(min_required_notional, min_cost)
    if target < required:
        return 0.0, 0.0
        
    qty = float(ex.amount_to_precision(symbol, target / (price * contract_size)))
    if not np.isfinite(qty) or qty <= 0 or qty < min_amount:
        return 0.0, 0.0
        
    actual = qty * price * contract_size
    actual_margin = actual / leverage
    
    if actual < required or actual_margin < MIN_MARGIN_USDT or actual_margin > margin_budget:
        return 0.0, 0.0
        
    return qty, actual


def ranked_symbols(ex, limit_count):
    now = time.time()
    limit_count = max(1, int(limit_count))
    cache_key = f"ranked_symbols:{ex.id}:{ex.options.get('defaultType', '')}:{limit_count}"
    cached = st.session_state.get(cache_key)
    if cached and now - cached.get("ts", 0) < 180:
        return cached["ranked"]

    markets = ex.load_markets()
    candidates = [
        symbol for symbol, market in markets.items()
        if market.get("active") is not False
        and market.get("quote") == "USDT"
        and market.get("linear")
        and market.get("swap", False)
    ]
    if not candidates:
        st.session_state[cache_key] = {"ts": now, "ranked": []}
        return []

    ranked_top = []
    batch_size = 40
    for offset in range(0, len(candidates), batch_size):
        batch = candidates[offset:offset + batch_size]
        tickers = ex.fetch_tickers(batch)
        for symbol in batch:
            ticker = tickers.get(symbol) or {}
            quote_volume = _as_float(ticker.get("quoteVolume"))
            if quote_volume <= 0:
                quote_volume = _as_float(ticker.get("baseVolume")) * _as_float(ticker.get("last"))
            if quote_volume > 0:
                ranked_top.append((symbol, quote_volume))
        ranked_top.sort(key=lambda item: item[1], reverse=True)
        del tickers
        ranked_top = ranked_top[:limit_count]

    st.session_state[cache_key] = {"ts": now, "ranked": ranked_top}
    gc.collect()
    return ranked_top


# ========================================================
# LOGOWANIE I SUBSKRYPCJE
# ========================================================
if "authenticated" not in st.session_state:
    st.session_state.update({"authenticated": False, "logged_in": False,
                             "username": "", "user_id": None,
                             "stripe_paid": 0, "user_email": ""})


def is_user_admin():
    email = str(st.session_state.get("user_email", "")).strip().lower()
    username = str(st.session_state.get("username", "")).strip().lower()
    return email in ADMIN_EMAILS or username == "admin"


def is_user_paid():
    return bool(st.session_state.get("stripe_paid", 0)) or is_user_admin()


if st.query_params.get("success") == "true":
    st.info("Powrót ze strony płatności. Dostęp zostanie aktywowany po potwierdzeniu płatności przez administratora.")
    st.query_params.clear()

if not st.session_state["authenticated"]:
    st.markdown('<div class="brand-retro">Bitget-SaaS</div><div class="subbrand-retro">AUTONOMICZNY SYSTEM TRANSAKCYJNY</div>', unsafe_allow_html=True)
    tab_login, tab_reg = st.tabs(["Zaloguj się", "Załóż konto i subskrypcję"])
    with tab_login:
        st.subheader("Logowanie do systemu")
        with st.form("login_form"):
            l_user = st.text_input("Nazwa użytkownika / E-mail")
            l_pass = st.text_input("Hasło", type="password")
            submit_login = st.form_submit_button("ZALOGUJ SIĘ", use_container_width=True)
        if submit_login:
            with db() as con:
                row = con.execute("""SELECT id,password,stripe_paid,email,username FROM users WHERE username=? OR email=?""", (l_user.strip(), l_user.strip().lower())).fetchone()
            valid, legacy = verify_password(row["password"], l_pass) if row else (False, False)
            if row and valid:
                if legacy:
                    with db() as con:
                        con.execute("UPDATE users SET password=? WHERE id=?", (password_hash(l_pass), row["id"]))
                        con.commit()
                st.session_state.update({"authenticated": True, "logged_in": True,
                    "user_id": row["id"], "stripe_paid": row["stripe_paid"],
                    "user_email": (row["email"] or "").lower(), "username": row["username"]})
                st.rerun()
            else:
                st.error("Nieprawidłowy login lub hasło.")
    with tab_reg:
        st.subheader("Rejestracja użytkownika – 49 PLN / miesiąc")
        with st.form("reg_form"):
            r_user = st.text_input("Nazwa użytkownika")
            r_email = st.text_input("Adres e-mail")
            r_pass = st.text_input("Hasło", type="password")
            r_sub = st.selectbox("Wybierz subskrypcję", ["Pro Trader (49 PLN / miesiąc)", "VIP SaaS (Roczny)"])
            submit_reg = st.form_submit_button("ZAREJESTRUJ SIĘ", use_container_width=True)
        if submit_reg:
            if not r_user.strip() or not r_pass.strip() or not r_email.strip():
                st.error("Uzupełnij login, e-mail i hasło.")
            elif "@" not in r_email or "." not in r_email.rsplit("@", 1)[-1]:
                st.error("Podaj prawidłowy adres e-mail.")
            else:
                try:
                    with db() as con:
                        con.execute("""INSERT INTO users(username,password,subscription,stripe_paid,email) VALUES(?,?,?,0,?)""",
                            (r_user.strip(), password_hash(r_pass), r_sub, r_email.strip().lower()))
                        con.commit()
                    st.success("Konto utworzone. Zaloguj się, a następnie opłać subskrypcję.")
                except sqlite3.IntegrityError:
                    st.error("Taki login lub adres e-mail już istnieje.")
    st.stop()


cfg = load_cfg()
ex_id, key, secret, passphrase = load_creds()

with st.sidebar:
    st.markdown(f'<div class="brand"><span></span> Bitget-SaaS</div><div class="subbrand">Witaj, {st.session_state["username"]}</div>', unsafe_allow_html=True)
    nav_options = ["Automatyczny Skaner i Auto-Handel", "Panel Sesji i Kapitału",
                   "Ustawienia Strategii", "Połączenie API", "Dziennik",
                   "Regulamin & Instrukcja Obsługi"]
    if is_user_admin():
        nav_options.append("Panel Administratora (Subskrybenci)")
    page = st.radio("NAWIGACJA", nav_options)
    st.markdown("---")
    st.markdown("### Status Subskrypcji (49 PLN)")
    if is_user_admin():
        st.success("Administrator (Pełny Dostęp)")
    elif is_user_paid():
        st.success("Subskrypcja aktywna (Pro)")
    else:
        st.warning("Subskrypcja nieopłacona")
    try:
        checkout_url = create_stripe_checkout_url(st.session_state.get("user_email", ""))
        st.link_button("OPŁAĆ SUBSKRYPCJĘ (49 PLN)", checkout_url, use_container_width=True)
    except Exception as exc:
        st.error(f"Nieprawidłowa konfiguracja linku Stripe: {exc}")
    st.caption("Po płatności administrator potwierdza transakcję i aktywuje dostęp.")
    st.divider()
    if st.button("Wyloguj", use_container_width=True):
        for k in ["authenticated", "logged_in", "username", "user_id", "stripe_paid", "user_email"]:
            st.session_state[k] = False if k in ("authenticated", "logged_in") else "" if k in ("username", "user_email") else None if k == "user_id" else 0
        st.rerun()
    if st.button("Wyczyść cache danych", use_container_width=True):
        get_candles.clear()
        st.cache_data.clear()
        st.cache_resource.clear()
        gc.collect()
        st.success("Cache danych wyczyszczony.")

st.markdown('<div class="brand"><span>Bitget</span>-SaaS Futures</div><div class="subbrand">AUTONOMICZNY SYSTEM TRANSAKCYJNY</div>', unsafe_allow_html=True)


# ========================================================
# SKANER
# ========================================================
if page == "Automatyczny Skaner i Auto-Handel":
    st.subheader("Automatyczny Skaner Rynku i Cykliczny Auto-Handel")
    st.write("Bot skanuje wybrane pary i interwały w ustalonych odstępach czasu.")
    with st.form("control_form"):
        auto_trade = st.checkbox("Włącz automatyczny handel (Auto-Trade)", value=bool(cfg["auto_trade"]))
        paper_mode = st.checkbox("Tryb symulacji PAPER (brak zleceń na żywo)", value=bool(cfg["paper_mode"]))
        auto_refresh = st.checkbox("Włącz ciągłe skanowanie", value=bool(cfg.get("auto_refresh", True)))
        refresh_seconds = st.slider("Odstęp czasu między skanami (sekundy)", 10, 300, int(cfg.get("refresh_seconds", 30)))
        submit_ctrl = st.form_submit_button("ZAPISZ TRYB PRACY", use_container_width=True)
    if submit_ctrl:
        cfg.update({"auto_trade": auto_trade, "paper_mode": paper_mode,
                    "auto_refresh": auto_refresh, "refresh_seconds": refresh_seconds})
        save_cfg(cfg)
        st.success("Zapisano tryb pracy.")
        st.rerun()

    st.warning("Handel LIVE może powodować straty. Najpierw sprawdź działanie w trybie PAPER.")
    try:
        ex = exchange_client(ex_id, key, secret, passphrase, cfg["market_type"])
        markets = ex.load_markets()
        symbols = [s for s, m in markets.items()
                   if m.get("quote") == "USDT" and m.get("active") and m.get("linear")]
        symbols = symbols[:int(cfg.get("scan_limit_count", 30))]
        tfs = [tf for tf in cfg.get("timeframes", ["4h", "1d"]) if tf in TF_OPTIONS]
        st.info(f"Skanowanie {len(symbols)} par na interwałach: {', '.join(tfs)}")
        results = []
        free, total = balance_usdt(ex) if not cfg["paper_mode"] and key and secret else (1000.0, 1000.0)
        for symbol in symbols:
            for tf in tfs:
                res = signal_for_symbol(cfg, symbol, tf)
                results.append(res)
                if res["signal"] in ("LONG", "SHORT"):
                    event("INFO", f"Sygnał {res['signal']} {symbol} [{tf}]")
                    if cfg["auto_trade"]:
                        if cfg["paper_mode"]:
                            event("TRADE", f"[PAPER] Sygnał {res['signal']} {symbol} [{tf}]")
                        elif key and secret and res.get("price"):
                            qty, notional = calc_qty(ex, symbol, total, free, res["price"], cfg)
                            if qty > 0:
                                try:
                                    ex.set_leverage(int(cfg["max_leverage"]), symbol)
                                except Exception:
                                    pass
                                order = market_order(ex, symbol, "buy" if res["signal"] == "LONG" else "sell", qty, reference_price=res["price"])
                                event("TRADE", f"Otwarto {res['signal']} {symbol} qty={qty} id={order.get('id')}")
        st.dataframe(pd.DataFrame(results), use_container_width=True, hide_index=True)
    except Exception as exc:
        st.error(f"Błąd podczas skanowania giełdy: {exc}")
    if cfg.get("auto_refresh") and cfg.get("auto_trade"):
        st.warning(f"Odświeżenie za {int(cfg.get('refresh_seconds', 30))} s.")
        time.sleep(int(cfg.get("refresh_seconds", 30)))
        st.rerun()


# ========================================================
# USTAWIENIA STRATEGII
# ========================================================
elif page == "Ustawienia Strategii":
    st.subheader("Ustawienia strategii, adaptacja i ryzyko")
    if "selected_tf_edit" not in st.session_state:
        st.session_state["selected_tf_edit"] = "1d"
    selected_tf = st.selectbox("Wybierz interwał do edycji", TF_OPTIONS,
                               index=TF_OPTIONS.index(st.session_state["selected_tf_edit"]))
    st.session_state["selected_tf_edit"] = selected_tf
    base = cfg["tf_settings"].get(selected_tf, DEFAULT_TF_SETTINGS[selected_tf])
    with st.form("cfgform"):
        a, b = st.columns(2)
        with a:
            exchange_name = st.selectbox("Giełda", ["bitget", "binanceusdm", "bybit", "okx"],
                index=["bitget", "binanceusdm", "bybit", "okx"].index(cfg["exchange"]) if cfg["exchange"] in ["bitget", "binanceusdm", "bybit", "okx"] else 0)
            market_type = st.selectbox("Rynek", ["swap", "future"], index=0 if cfg["market_type"] == "swap" else 1)
            scan_limit = st.slider("Limit skanowanych par", 5, 50, int(cfg.get("scan_limit_count", 30)))
            timeframes = st.multiselect("Interwały do skanowania", TF_OPTIONS,
                default=[x for x in cfg.get("timeframes", ["4h", "1d"]) if x in TF_OPTIONS])
            multiplier = st.slider("Multiplikator wskaźników (%)", 10, 100, int(cfg.get("indicator_multiplier", 60)))
        with b:
            risk = st.number_input("Maks. ryzyko na pozycję (USDT)", 1.0, 10000.0, float(cfg["risk_usdt"]))
            max_positions = st.number_input("Maks. otwarte pozycje", 1, 20, int(cfg["max_positions"]))
            max_leverage = st.number_input("Maksymalna dźwignia", 1, 50, int(cfg["max_leverage"]))
            sl_roe = st.number_input("Stop-loss ROE (%)", 1.0, 95.0, float(cfg["sl_roe"]))
            tp_roe = st.number_input("Take-profit ROE (%)", 1.0, 500.0, float(cfg["tp_roe"]))
            allow_long = st.checkbox("Pozwól na LONG", bool(cfg["allow_long"]))
            allow_short = st.checkbox("Pozwól na SHORT", bool(cfg["allow_short"]))
        st.markdown(f"### Parametry bazowe dla {selected_tf}")
        c1, c2, c3, c4, c5 = st.columns(5)
        with c1: fast = st.number_input("EMA szybka", 2, 100, int(base["ema_fast"]))
        with c2: slow = st.number_input("EMA wolna", 3, 300, int(base["ema_slow"]))
        with c3: adx = st.number_input("Min. ADX", 0.0, 100.0, float(base["adx_threshold"]))
        with c4: rmin = st.number_input("RSI min", 0.0, 100.0, float(base["rsi_min"]))
        with c5: rmax = st.number_input("RSI max", 0.0, 100.0, float(base["rsi_max"]))
        save = st.form_submit_button("ZAPISZ USTAWIENIA", use_container_width=True)
    if save:
        if fast >= slow:
            st.error("EMA szybka powinna być mniejsza od EMA wolnej.")
        elif rmin >= rmax:
            st.error("RSI min musi być mniejsze od RSI max.")
        else:
            cfg.update({"exchange": exchange_name, "market_type": market_type,
                "scan_limit_count": scan_limit, "timeframes": timeframes or ["4h", "1d"],
                "indicator_multiplier": multiplier, "risk_usdt": risk,
                "max_positions": int(max_positions), "max_leverage": int(max_leverage),
                "sl_roe": sl_roe, "tp_roe": tp_roe, "allow_long": allow_long, "allow_short": allow_short})
            cfg["tf_settings"][selected_tf] = {"ema_fast": int(fast), "ema_slow": int(slow),
                "adx_threshold": float(adx), "rsi_min": float(rmin), "rsi_max": float(rmax)}
            save_cfg(cfg)
            st.success("Zapisano ustawienia.")
            st.rerun()


# ========================================================
# API
# ========================================================
elif page == "Połączenie API":
    st.subheader("Połączenie giełdowe")
    with st.form("credentials"):
        ex_choice = st.selectbox("Giełda", ["bitget", "binanceusdm", "bybit", "okx"],
            index=["bitget", "binanceusdm", "bybit", "okx"].index(ex_id) if ex_id in ["bitget", "binanceusdm", "bybit", "okx"] else 0)
        api_key = st.text_input("API Key", value=key, type="password")
        api_secret = st.text_input("API Secret", value=secret, type="password")
        api_pass = st.text_input("Passphrase (Bitget/OKX)", value=passphrase, type="password")
        save_api = st.form_submit_button("ZAPISZ DANE API")
    if save_api:
        save_creds(ex_choice, api_key.strip(), api_secret.strip(), api_pass.strip())
        exchange_client.clear()
        st.success("Dane API zapisane.")
        st.rerun()
    if st.button("Testuj API / pobierz saldo"):
        try:
            client = exchange_client(ex_id, key, secret, passphrase, cfg["market_type"])
            free, total = balance_usdt(client)
            st.success("Połączenie działa")
            x, y = st.columns(2)
            x.metric("USDT dostępne", f"{free:.2f}")
            y.metric("USDT łącznie", f"{total:.2f}")
        except Exception as exc:
            st.error(f"Błąd API: {exc}")


# ========================================================
# DZIENNIK
# ========================================================
elif page == "Dziennik":
    st.subheader("Zdarzenia i zlecenia bota")
    with db() as con:
        rows = con.execute("SELECT ts,level,message FROM events ORDER BY id DESC LIMIT 200").fetchall()
    if rows:
        st.dataframe(pd.DataFrame([tuple(r) for r in rows], columns=["UTC", "Poziom", "Wiadomość"]),
                     use_container_width=True, hide_index=True)
    else:
        st.info("Brak zdarzeń.")


# ========================================================
# INSTRUKCJA I REGULAMIN
# ========================================================
elif page == "Regulamin & Instrukcja Obsługi":
    st.subheader("Regulamin i instrukcja obsługi")
    tab_help, tab_terms = st.tabs(["Instrukcja obsługi", "Regulamin"])
    with tab_help:
        st.markdown("""
        ### Jak skonfigurować Bitget-SaaS?
        1. Załóż konto, zaloguj się i opłać subskrypcję przyciskiem w panelu bocznym.
        2. Administrator sprawdza płatność w panelu Stripe i ręcznie aktywuje dostęp.
        3. Na giełdzie utwórz klucz API z uprawnieniami odczytu i handlu Futures. Nie włączaj wypłat.
        4. Wprowadź API Key, Secret i Passphrase w zakładce **Połączenie API**.
        5. Ustaw ryzyko, interwały oraz wskaźniki w **Ustawieniach Strategii**.
        6. Przed handlem na żywo przetestuj konfigurację w trybie PAPER.
        """)
    with tab_terms:
        st.markdown("""
        ### REGULAMIN BITGET-SAAS FUTURES
        1. Serwis udostępnia narzędzia programowe do analizy rynku i składania zleceń.
        2. Użytkownik odpowiada za klucze API, ustawienia ryzyka i decyzje inwestycyjne.
        3. Handel futures wiąże się z ryzykiem utraty kapitału; wyniki nie są gwarantowane.
        4. Dostęp płatny kosztuje 49 PLN miesięcznie, zgodnie z informacją przedstawioną przy płatności.
        """)


# ========================================================
# PANEL ADMINISTRATORA
# ========================================================
elif page == "Panel Administratora (Subskrybenci)" and is_user_admin():
    st.subheader("Panel zarządzania użytkownikami i subskrypcjami")
    with db() as con:
        rows = con.execute("SELECT id,username,email,subscription,stripe_paid FROM users ORDER BY id").fetchall()
    if rows:
        df = pd.DataFrame([tuple(r) for r in rows],
                          columns=["ID", "Nazwa użytkownika", "E-mail", "Pakiet", "Opłacone (0/1)"])
        st.dataframe(df, use_container_width=True, hide_index=True)
        with st.form("admin_manage_form"):
            user_id = st.selectbox("Wybierz ID użytkownika", df["ID"].tolist())
            action = st.selectbox("Akcja", ["Aktywuj subskrypcję", "Odbierz subskrypcję", "Usuń użytkownika"])
            confirm = st.checkbox("Potwierdzam wykonanie wybranej operacji")
            go = st.form_submit_button("WYKONAJ AKCJĘ", use_container_width=True)
        if go:
            if not confirm:
                st.error("Zaznacz potwierdzenie operacji.")
            else:
                with db() as con:
                    if action == "Aktywuj subskrypcję":
                        con.execute("UPDATE users SET stripe_paid=1 WHERE id=?", (user_id,))
                    elif action == "Odbierz subskrypcję":
                        con.execute("UPDATE users SET stripe_paid=0 WHERE id=?", (user_id,))
                    else:
                        con.execute("DELETE FROM users WHERE id=?", (user_id,))
                    con.commit()
                event("ADMIN", f"{action}; user_id={user_id}")
                st.success("Operacja wykonana.")
                st.rerun()
    else:
        st.info("Brak użytkowników.")


# ========================================================
# PANEL KAPITAŁU
# ========================================================
elif page == "Panel Sesji i Kapitału":
    st.subheader("Panel sesji i analiza kapitału")
    total_bal, free_bal, active_slots, session_pnl, used_margin = 0.0, 0.0, 0, 0.0, 0.0
    connected = bool(key and secret)
    api_ok = False
    
    if connected:
        try:
            client = exchange_client(ex_id, key, secret, passphrase, cfg["market_type"])
            active = active_positions(client)
            free_bal, total_bal = balance_usdt(client, active)
            active_slots = len(active)
            session_pnl = sum(_as_float(p.get("unrealizedPnl")) for p in active)
            used_margin = sum(_as_float(p.get("initialMargin") or p.get("margin")) for p in active)
            api_ok = True
        except Exception as exc:
            st.warning(f"Nie udało się pobrać salda/pozycji: {exc}")
        finally:
            gc.collect()

    max_slots = int(cfg["max_positions"])
    
    def metric_card(label, value, note="", tone=""):
        tone_class = f" {tone}" if tone else ""
        st.markdown(
            f'<div class="metric-card{tone_class}">'
            f'<div class="metric-label">{label}</div>'
            f'<div class="metric-value">{value}</div>'
            f'<div class="metric-note">{note}</div></div>',
            unsafe_allow_html=True,
        )

    terminal_active = bool(api_ok and cfg.get("auto_refresh", True))
    terminal_text = "AKTYWNY" if terminal_active else "NIEAKTYWNY"
    terminal_note = "API działa; ciągłe skanowanie włączone" if terminal_active else "Brak połączenia API lub skanowanie wyłączone"
    
    c1, c2, c3, c4 = st.columns(4, gap="medium")
    with c1:
        metric_card("Saldo / wolne środki", f"{total_bal:.2f} / {free_bal:.2f} USDT",
                    "Saldo całkowite / środki dostępne", "gold")
    with c2:
        metric_card("Niezrealizowany PnL", f"{session_pnl:+.2f} USDT",
                    "Łączny PnL otwartych pozycji", "green" if session_pnl >= 0 else "red")
    with c3:
        metric_card("Otwarte pozycje", f"{active_slots} / {max_slots}",
                    f"Zgłoszony margin: {used_margin:.2f} USDT", "blue")
    with c4:
        metric_card("Terminal", terminal_text, terminal_note,
                    "green" if terminal_active else "red")

    st.divider()
    st.markdown("### Bieżące aktywne pozycje")
    if connected and api_ok:
        try:
            client = exchange_client(ex_id, key, secret, passphrase, cfg["market_type"])
            positions = active_positions(client)
            if positions:
                st.dataframe(pd.DataFrame([{
                    "Symbol": p.get("symbol"), "Strona": p.get("side"),
                    "Kontrakty": p.get("contracts"), "Wejście": p.get("entryPrice"),
                    "PnL (USDT)": p.get("unrealizedPnl"), "Margin": p.get("initialMargin")
                } for p in positions]), use_container_width=True, hide_index=True)
            else:
                st.info("Brak otwartych pozycji.")
        except Exception as exc:
            st.warning(f"Nie udało się pobrać pozycji: {exc}")
    else:
        st.info("Skonfiguruj dane API, aby zobaczyć pozycje.")

    st.divider()
    st.markdown("### Awaryjne zamknięcie wszystkich pozycji")
    st.warning("To polecenie wysyła prawdziwe zlecenia rynkowe zamykające pozycje.")
    if st.button("ZAMKNIJ WSZYSTKIE POZYCJE RYNKOWO", type="secondary"):
        try:
            if not connected:
                raise RuntimeError("Brak kluczy API")
            client = exchange_client(ex_id, key, secret, passphrase, cfg["market_type"])
            positions = active_positions(client)
            outcomes = []
            for pos in positions:
                qty = abs(_as_float(pos.get("contracts")))
                symbol = pos.get("symbol")
                if qty <= 0 or not symbol:
                    continue
                close_side = "sell" if str(pos.get("side") or "").lower() in ("long", "buy") else "buy"
                try:
                    order = market_order(client, symbol, close_side, qty, reduce_only=True)
                    outcomes.append(f"{symbol}: zamknięto {qty}; order={order.get('id')}")
                except Exception as exc:
                    outcomes.append(f"{symbol}: BŁĄD {exc}")
            for line in outcomes:
                event("KILL", line)
            st.write("\n".join(outcomes) if outcomes else "Brak aktywnych pozycji.")
        except Exception as exc:
            st.error(f"Kill switch nie powiódł się: {exc}")
        finally:
            gc.collect()

# -*- coding: utf-8 -*-
import os
import json
import sqlite3
import time
import logging
import hashlib
import hmac
import secrets
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
st.set_page_config(page_title="Bitget-SaaS Futures", page_icon="\U0001f4c8", layout="wide")

APP_DIR = Path(__file__).resolve().parent
DB_PATH = Path(os.getenv("BITGET_SAAS_DB", str(APP_DIR / "bitget_saas.db")))
LOG_PATH = APP_DIR / "trading.log"
logging.basicConfig(filename=str(LOG_PATH), level=logging.INFO,
                    format="%(asctime)s %(levelname)s %(message)s")

# Produkcyjny Stripe Payment Link podany przez u偶ytkownika.
# Celowo nie pobieramy go ze zmiennej 艣rodowiskowej: stara lub pusta
# warto艣膰 STRIPE_CHECKOUT_FALLBACK na serwerze nadpisywa艂a poprawny adres.
STRIPE_CHECKOUT_FALLBACK = "https://buy.stripe.com/8x2dRa4CbdaxfSAF6V3oA03"
ADMIN_EMAILS = {"marekja57@wp.pl", "admin@bot-bitget.pl"}

TF_OPTIONS = ["1m", "3m", "5m", "15m", "30m", "1h", "2h", "4h", "1d"]
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
    "exchange": "bitget", "market_type": "swap", "candle_limit": 180,
    "refresh_seconds": 30, "risk_usdt": 10.0, "max_positions": 3,
    "max_leverage": 10, "sl_roe": 20.0, "tp_roe": 40.0, "enable_roe": True,
    "timeframes": ["4h", "1d"], "tf_settings": DEFAULT_TF_SETTINGS,
    "auto_refresh": True, "auto_trade": False, "paper_mode": True,
    "max_notional_usdt": 50.0, "cooldown_seconds": 300,
    "allow_short": True, "allow_long": True, "scan_limit_count": 30,
    "indicator_multiplier": 60,
}

CSS = """ <style> :root { color-scheme: dark; } .stApp { background: radial-gradient(ellipse at 40% -20%, #103e78 0%, #071a36 42%, #050e20 100%); color: #eaf3ff; } /* Belka Streamlit zostaje nad tre艣ci膮, a panel otrzymuje bezpieczny odst臋p. */ [data-testid="stHeader"] { background: rgba(3, 12, 29, 0.96); z-index: 1000; } [data-testid="stAppViewContainer"] .main .block-container { padding-top: 3.5rem !important; padding-bottom: 2rem !important; max-width: 1600px; overflow: visible; } [data-testid="stSidebar"] { background: linear-gradient(180deg, #06152d, #081f42); border-right: 1px solid #164a84; } /* Nag艂贸wek g艂贸wnego panelu: pe艂ny tekst, bez nachodzenia na g贸rn膮 belk臋. */ .brand { display: block; position: relative; margin-top: 0.5rem; margin-bottom: 0.35rem; padding-top: 0.25rem; font-weight: 900; letter-spacing: -0.7px; font-size: clamp(23px, 2.5vw, 32px); line-height: 1.35; color: #eaf5ff; overflow-wrap: anywhere; } .brand span { color: #28a8ff; } .subbrand { display: block; position: relative; margin-top: 0.2rem; margin-bottom: 1.5rem; color: #7da9d8; font-size: 11px; line-height: 1.6; letter-spacing: 1.5px; text-transform: uppercase; overflow-wrap: anywhere; } /* Nag艂贸wek logowania i rejestracji. */ .brand-retro { display: block; position: relative; padding-top: 0.5rem; margin-top: 0.5rem; margin-bottom: 0.5rem; font-weight: 900; font-size: clamp(27px, 3vw, 38px); line-height: 1.35; letter-spacing: -0.5px; color: #f3c653; text-shadow: 2px 2px 4px rgba(0, 0, 0, 0.6); text-align: center; font-family: serif; overflow-wrap: anywhere; } .subbrand-retro { color: #7da9d8; font-size: 11px; line-height: 1.7; letter-spacing: 1.5px; text-transform: uppercase; text-align: center; margin-bottom: 20px; } .panel { background: linear-gradient(145deg, rgba(12,43,83,.95), rgba(5,24,51,.96)); border: 1px solid #164a80; border-radius: 14px; padding: 16px 18px; box-shadow: 0 4px 12px rgba(0,0,0,.3); } .metric-label { font-size: 12px; color: #90b8e6; text-transform: uppercase; letter-spacing: 1px; } .metric-value { font-size: 24px; font-weight: 800; color: #f1f7ff; margin-top: 5px; } .muted { color: #83a7d0; font-size: 12px; margin-top: 4px; } div.stButton > button { border: 1px solid #278be8; border-radius: 8px; background: linear-gradient(180deg, #1689ff, #0759c8); color: white; font-weight: 700; } hr { border-color: #16416f; } @media (max-width: 768px) { [data-testid="stAppViewContainer"] .main .block-container { padding-top: 2.8rem !important; padding-left: 1rem; padding-right: 1rem; } .brand { font-size: 25px; letter-spacing: -0.4px; } .subbrand { font-size: 10px; letter-spacing: 1px; } } </style> """
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
    con.execute("""CREATE TABLE IF NOT EXISTS credentials ( k TEXT PRIMARY KEY, exchange TEXT, api_key TEXT, secret TEXT, password TEXT)""")
    con.execute("""CREATE TABLE IF NOT EXISTS events ( id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT, level TEXT, message TEXT)""")
    con.execute("""CREATE TABLE IF NOT EXISTS users ( id INTEGER PRIMARY KEY AUTOINCREMENT, username TEXT UNIQUE NOT NULL, password TEXT NOT NULL, subscription TEXT, stripe_paid INTEGER NOT NULL DEFAULT 0, email TEXT UNIQUE)""")
    con.commit()
    return con


def password_hash(password, salt=None):
    salt = salt or secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), 240000).hex()
    return f"pbkdf2${salt}${digest}"


def verify_password(stored, password):
    # Obs\u0142uga r\u00f3wnie\u017c starych kont, kt\u00f3re mia\u0142y has\u0142o zapisane jawnie.
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
            # Uzupe\u0142nij brakuj\u0105ce interwa\u0142y bez kasowania zapisanych warto\u015bci.
            merged = json.loads(json.dumps(DEFAULT_TF_SETTINGS))
            merged.update(cfg.get("tf_settings", {}))
            cfg["tf_settings"] = merged
        except Exception:
            logging.exception("Nie uda\u0142o si\u0119 odczyta\u0107 ustawie\u0144")
    return cfg


def save_cfg(cfg):
    with db() as con:
        con.execute("""INSERT INTO settings(k,v) VALUES('main',?) ON CONFLICT(k) DO UPDATE SET v=excluded.v""",
            (json.dumps(cfg, ensure_ascii=False),))
        con.commit()


def event(level, msg):
    logging.log(getattr(logging, str(level).upper(), logging.INFO), str(msg))
    with db() as con:
        con.execute("INSERT INTO events(ts,level,message) VALUES(?,?,?)",
                    (datetime.now(timezone.utc).isoformat(), str(level), str(msg)[:1500]))
        con.commit()


def load_creds():
    with db() as con:
        row = con.execute("SELECT exchange,api_key,secret,password FROM credentials WHERE k='main'").fetchone()
    return tuple(row) if row else ("bitget", "", "", "")


def save_creds(ex, key, secret, passphrase):
    with db() as con:
        con.execute("""INSERT INTO credentials(k,exchange,api_key,secret,password) VALUES('main',?,?,?,?) ON CONFLICT(k) DO UPDATE SET exchange=excluded.exchange,api_key=excluded.api_key, secret=excluded.secret,password=excluded.password""",
            (ex, key, secret, passphrase))
        con.commit()


def create_stripe_checkout_url(email):
    # Otw\u00f3rz dok\u0142adnie Payment Link skopiowany z panelu Stripe.
    # Nie dopisuj parametr\u00f3w ani znak\u00f3w do adresu \u2014 najpierw potwierd\u017a,
    # \u017ce sam link jest aktywny w panelu Stripe.
    url = STRIPE_CHECKOUT_FALLBACK.strip()
    if not url.startswith("https://buy.stripe.com/"):
        raise ValueError("W STRIPE_CHECKOUT_FALLBACK wstaw dok\u0142adny aktywny link https://buy.stripe.com/... z panelu Stripe.")
    return url


# ========================================================
# GIE\u0141DA / WSKA\u0179NIKI
# ========================================================
@st.cache_resource(show_spinner=False)
def exchange_client(ex_id, api_key, secret, passphrase, market_type):
    if ccxt is None:
        raise RuntimeError("Brak biblioteki ccxt. Zainstaluj: pip install ccxt")
    cls = getattr(ccxt, ex_id, None)
    if cls is None:
        raise ValueError("Nieobs\u0142ugiwana gie\u0142da: " + str(ex_id))
    opts = {"enableRateLimit": True, "timeout": 20000,
            "options": {"defaultType": market_type, "defaultSubType": "linear"}}
    if api_key and secret:
        opts.update(apiKey=api_key, secret=secret)
    if passphrase:
        opts["password"] = passphrase
    return cls(opts)


@st.cache_data(ttl=20, show_spinner=False)
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
    tr = pd.concat([(d.high-d.low).abs(), (d.high-d.close.shift()).abs(),
                    (d.low-d.close.shift()).abs()], axis=1).max(axis=1)
    up, down = d.high.diff(), -d.low.diff()
    plus = pd.Series(np.where((up > down) & (up > 0), up, 0), index=d.index)
    minus = pd.Series(np.where((down > up) & (down > 0), down, 0), index=d.index)
    atr = tr.ewm(alpha=1/14, adjust=False).mean().replace(0, np.nan)
    pdi = 100 * plus.ewm(alpha=1/14, adjust=False).mean() / atr
    mdi = 100 * minus.ewm(alpha=1/14, adjust=False).mean() / atr
    dx = 100 * (pdi-mdi).abs() / (pdi+mdi).replace(0, np.nan)
    d["adx"] = dx.ewm(alpha=1/14, adjust=False).mean()
    return d


def get_effective_tf_cfg(cfg, tf):
    base = cfg.get("tf_settings", {}).get(tf, DEFAULT_TF_SETTINGS.get(tf, DEFAULT_TF_SETTINGS["1h"]))
    mult = float(cfg.get("indicator_multiplier", 60)) / 100.0
    return {
        "ema_fast": max(2, int(round(float(base["ema_fast"]) * mult))),
        "ema_slow": max(3, int(round(float(base["ema_slow"]) * mult))),
        "adx_threshold": max(2.0, min(90.0, float(base["adx_threshold"]) * mult)),
        "rsi_min": max(2.0, min(45.0, float(base["rsi_min"]) * mult)),
        "rsi_max": max(55.0, min(98.0, float(base["rsi_max"]) * mult)),
    }


def signal_for_symbol(cfg, symbol, tf):
    try:
        t = get_effective_tf_cfg(cfg, tf)
        raw = get_candles(cfg["exchange"], cfg["market_type"], symbol, tf, cfg["candle_limit"])
        d = indicators(raw.iloc[:-1].copy(), t["ema_fast"], t["ema_slow"])
        if len(d) < 35:
            return {"symbol": symbol, "tf": tf, "signal": "NEUTRALNY", "reason": "Za ma\u0142o \u015bwiec"}
        r = d.iloc[-1]
        long_ok = (cfg["allow_long"] and r.ema_fast > r.ema_slow and
                   r.adx >= t["adx_threshold"] and t["rsi_min"] <= r.rsi <= t["rsi_max"] and
                   r.close > r.ema_fast)
        short_ok = (cfg["allow_short"] and r.ema_fast < r.ema_slow and
                    r.adx >= t["adx_threshold"] and t["rsi_min"] <= r.rsi <= t["rsi_max"] and
                    r.close < r.ema_fast)
        sig = "LONG" if long_ok else "SHORT" if short_ok else "NEUTRALNY"
        return {"symbol": symbol, "tf": tf, "signal": sig, "price": float(r.close),
                "adx": float(r.adx), "rsi": float(r.rsi), "reason": "OK"}
    except Exception as exc:
        return {"symbol": symbol, "tf": tf, "signal": "B\u0141\u0104D", "reason": str(exc)[:160]}


def market_order(ex, symbol, side, qty, reduce_only=False):
    qty = float(ex.amount_to_precision(symbol, qty))
    if qty <= 0:
        raise ValueError("Ilo\u015b\u0107 zlecenia wynosi zero")
    return ex.create_order(symbol, "market", side, qty, None,
                           {"reduceOnly": True} if reduce_only else {})


def calc_qty(ex, symbol, total_usdt, free_usdt, price, cfg):
    lev = max(1, int(cfg["max_leverage"]))
    auto_risk = max(0.0, float(total_usdt)) * 0.02
    risk = min(float(cfg["risk_usdt"]), auto_risk)
    stop_fraction = max(0.001, (float(cfg["sl_roe"]) / 100.0) / lev)
    notional = min(risk / stop_fraction, float(cfg["max_notional_usdt"]),
                   max(0.0, float(free_usdt)) * lev * 0.90)
    market = ex.market(symbol)
    contract = float(market.get("contractSize") or 1)
    qty = float(ex.amount_to_precision(symbol, notional / max(float(price) * contract, 1e-12)))
    return qty, notional


def _as_float(value):
    try:
        number = float(value)
        return number if np.isfinite(number) else 0.0
    except (TypeError, ValueError):
        return 0.0


def balance_usdt(ex, positions=None):
    """Zwraca (wolne USDT, ca艂kowite USDT). Je艣li gie艂da nie podaje u偶ytego salda, wykorzystuje depozyt otwartych pozycji jako kontrolowany fallback."""
    b = ex.fetch_balance() or {}
    row = b.get("USDT") if isinstance(b.get("USDT"), dict) else {}

    free = row.get("free")
    total = row.get("total")
    used = row.get("used")
    if free is None and isinstance(b.get("free"), dict):
        free = b["free"].get("USDT")
    if total is None and isinstance(b.get("total"), dict):
        total = b["total"].get("USDT")
    if used is None and isinstance(b.get("used"), dict):
        used = b["used"].get("USDT")

    free_value = max(0.0, _as_float(free))
    used_value = max(0.0, _as_float(used))
    position_margin = 0.0
    for pos in positions or []:
        # CCXT ujednolica initialMargin; niekt贸re gie艂dy udost臋pniaj膮 tylko
        # margin lub warto艣膰 w polu info.
        margin = pos.get("initialMargin")
        if margin is None:
            margin = pos.get("margin")
        if margin is None and isinstance(pos.get("info"), dict):
            info = pos["info"]
            margin = info.get("marginSize") or info.get("totalMargin") or info.get("positionIM")
        position_margin += max(0.0, _as_float(margin))

    total_value = max(0.0, _as_float(total)) if total is not None else free_value + used_value
    # Gdy gie艂da zwraca total == free mimo otwartych pozycji, uwzgl臋dnij
    # raportowany used albo depozyt z pozycji. Nie obni偶aj poprawnego total.
    if used is not None:
        total_value = max(total_value, free_value + used_value)
    if position_margin > 0:
        total_value = max(total_value, free_value + used_value, free_value + position_margin)
    if total is None and used is None and position_margin <= 0:
        total_value = free_value

    return free_value, total_value


def active_positions(ex):
    """Zwraca tylko otwarte pozycje. B艂膮d API przerywa pr贸b臋 otwarcia nowych pozycji."""
    positions = ex.fetch_positions() or []
    return [pos for pos in positions if abs(_as_float(pos.get("contracts"))) > 0]


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


# WA\u017bNE: nie aktywuj subskrypcji na podstawie ?success=true.
# Payment Link nie jest potwierdzeniem p\u0142atno\u015bci dla aplikacji. Administrator
# aktywuje dost\u0119p po sprawdzeniu p\u0142atno\u015bci w panelu Stripe.
if st.query_params.get("success") == "true":
    st.info("Powr\u00f3t ze strony p\u0142atno\u015bci. Dost\u0119p zostanie aktywowany po potwierdzeniu p\u0142atno\u015bci przez administratora.")
    st.query_params.clear()

if not st.session_state["authenticated"]:
    st.markdown('<div class="brand-retro">Bitget-SaaS</div><div class="subbrand-retro">AUTONOMICZNY SYSTEM TRANSAKCYJNY</div>', unsafe_allow_html=True)
    tab_login, tab_reg = st.tabs(["Zaloguj si\u0119", "Za\u0142\u00f3\u017c konto i subskrypcj\u0119"])
    with tab_login:
        st.subheader("Logowanie do systemu")
        with st.form("login_form"):
            l_user = st.text_input("Nazwa u\u017cytkownika / E-mail")
            l_pass = st.text_input("Has\u0142o", type="password")
            submit_login = st.form_submit_button("ZALOGUJ SI\u0118", use_container_width=True)
        if submit_login:
            with db() as con:
                row = con.execute("""SELECT id,password,stripe_paid,email,username FROM users WHERE username=? OR email=?""", (l_user.strip(), l_user.strip().lower())).fetchone()
            valid, legacy = verify_password(row["password"], l_pass) if row else (False, False)
            if row and valid:
                if legacy:
                    with db() as con:
                        con.execute("UPDATE users SET password=? WHERE id=?",
                                    (password_hash(l_pass), row["id"]))
                        con.commit()
                st.session_state.update({"authenticated": True, "logged_in": True,
                    "user_id": row["id"], "stripe_paid": row["stripe_paid"],
                    "user_email": (row["email"] or "").lower(), "username": row["username"]})
                st.rerun()
            else:
                st.error("Nieprawid\u0142owy login lub has\u0142o.")
    with tab_reg:
        st.subheader("Rejestracja u\u017cytkownika \u2014 49 PLN / miesi\u0105c")
        with st.form("reg_form"):
            r_user = st.text_input("Nazwa u\u017cytkownika")
            r_email = st.text_input("Adres e-mail")
            r_pass = st.text_input("Has\u0142o", type="password")
            r_sub = st.selectbox("Wybierz subskrypcj\u0119", ["Pro Trader (49 PLN / miesi\u0105c)", "VIP SaaS (Roczny)"])
            submit_reg = st.form_submit_button("ZAREJESTRUJ SI\u0118", use_container_width=True)
        if submit_reg:
            if not r_user.strip() or not r_pass.strip() or not r_email.strip():
                st.error("Uzupe\u0142nij login, e-mail i has\u0142o.")
            elif "@" not in r_email or "." not in r_email.rsplit("@", 1)[-1]:
                st.error("Podaj prawid\u0142owy adres e-mail.")
            else:
                try:
                    with db() as con:
                        con.execute("""INSERT INTO users(username,password,subscription,stripe_paid,email) VALUES(?,?,?,0,?)""",
                            (r_user.strip(), password_hash(r_pass), r_sub, r_email.strip().lower()))
                        con.commit()
                    st.success("Konto utworzone. Zaloguj si\u0119, a nast\u0119pnie op\u0142a\u0107 subskrypcj\u0119.")
                except sqlite3.IntegrityError:
                    st.error("Taki login lub adres e-mail ju\u017c istnieje.")
    st.stop()


cfg = load_cfg()
ex_id, key, secret, passphrase = load_creds()

with st.sidebar:
    st.markdown(f'<div class="brand"><span>\u26a1</span> Bitget-SaaS</div><div class="subbrand">Witaj, {st.session_state["username"]}</div>', unsafe_allow_html=True)
    nav_options = ["Automatyczny Skaner i Auto-Handel", "Panel Sesji i Kapita\u0142u",
                   "Ustawienia Strategii", "Po\u0142\u0105czenie API", "Dziennik",
                   "Regulamin & Instrukcja Obs\u0142ugi"]
    if is_user_admin():
        nav_options.append("Panel Administratora (Subskrybenci)")
    page = st.radio("NAWIGACJA", nav_options)
    st.markdown("---")
    st.markdown("### Status Subskrypcji (49 PLN)")
    if is_user_admin():
        st.success("Administrator (Pe\u0142ny Dost\u0119p)")
    elif is_user_paid():
        st.success("Subskrypcja aktywna (Pro)")
    else:
        st.warning("Subskrypcja nieop\u0142acona")
    try:
        checkout_url = create_stripe_checkout_url(st.session_state.get("user_email", ""))
        st.link_button("OP\u0141A\u0106 SUBSKRYPCJ\u0118 (49 PLN)", checkout_url, use_container_width=True)
    except Exception as exc:
        st.error(f"Nieprawid\u0142owa konfiguracja linku Stripe: {exc}")
    st.caption("Po p\u0142atno\u015bci administrator potwierdza transakcj\u0119 i aktywuje dost\u0119p.")
    st.divider()
    if st.button("Wyloguj", use_container_width=True):
        for k in ["authenticated", "logged_in", "username", "user_id", "stripe_paid", "user_email"]:
            st.session_state[k] = False if k in ("authenticated", "logged_in") else "" if k in ("username", "user_email") else None if k == "user_id" else 0
        st.rerun()
    if st.button("Wyczy\u015b\u0107 cache danych", use_container_width=True):
        get_candles.clear()
        st.success("Cache danych wyczyszczony.")

st.markdown('<div class="brand"><span>Bitget</span>-SaaS Futures</div><div class="subbrand">AUTONOMICZNY SYSTEM TRANSAKCYJNY</div>', unsafe_allow_html=True)


# ========================================================
# SKANER
# ========================================================
if page == "Automatyczny Skaner i Auto-Handel":
    st.subheader("Automatyczny Skaner Rynku i Cykliczny Auto-Handel")
    st.write("Bot skanuje wybrane pary i interwa\u0142y w ustalonych odst\u0119pach czasu.")
    with st.form("control_form"):
        auto_trade = st.checkbox("W\u0142\u0105cz automatyczny handel (Auto-Trade)", value=bool(cfg["auto_trade"]))
        paper_mode = st.checkbox("Tryb symulacji PAPER (brak zlece\u0144 na \u017cywo)", value=bool(cfg["paper_mode"]))
        auto_refresh = st.checkbox("W\u0142\u0105cz ci\u0105g\u0142e skanowanie", value=bool(cfg.get("auto_refresh", True)))
        refresh_seconds = st.slider("Odst\u0119p czasu mi\u0119dzy skanami (sekundy)", 10, 300, int(cfg.get("refresh_seconds", 30)))
        submit_ctrl = st.form_submit_button("ZAPISZ TRYB PRACY", use_container_width=True)
    if submit_ctrl:
        cfg.update({"auto_trade": auto_trade, "paper_mode": paper_mode,
                    "auto_refresh": auto_refresh, "refresh_seconds": refresh_seconds})
        save_cfg(cfg)
        st.success("Zapisano tryb pracy.")
        st.rerun()

    st.warning("Handel LIVE mo\u017ce powodowa\u0107 straty. Najpierw sprawd\u017a dzia\u0142anie w trybie PAPER.")
    try:
        ex = exchange_client(ex_id, key, secret, passphrase, cfg["market_type"])
        markets = ex.load_markets()
        symbols = [s for s, m in markets.items()
                   if m.get("quote") == "USDT" and m.get("active") and m.get("linear")]
        symbols = symbols[:int(cfg.get("scan_limit_count", 30))]
        tfs = [tf for tf in cfg.get("timeframes", ["4h", "1d"]) if tf in TF_OPTIONS]
        st.info(f"Skanowanie {len(symbols)} par na interwa\u0142ach: {', '.join(tfs)}")
        results = []
        max_slots = max(1, int(cfg.get("max_positions", 3)))
        paper_open_symbols = set()
        opened_this_scan = [] # Rezerwacja slot贸w na czas bie偶膮cego skanu.
        for symbol in symbols:
            for tf in tfs:
                res = signal_for_symbol(cfg, symbol, tf)
                results.append(res)
                if res["signal"] not in ("LONG", "SHORT"):
                    continue

                event("INFO", f"Sygna艂 {res['signal']} {symbol} [{tf}]")
                if not cfg["auto_trade"]:
                    continue

                if cfg["paper_mode"]:
                    if symbol in paper_open_symbols:
                        continue
                    if len(paper_open_symbols) >= max_slots:
                        event("WARNING", f"[PAPER] Pomini臋to {symbol}: limit slot贸w {max_slots} osi膮gni臋ty.")
                        continue
                    paper_open_symbols.add(symbol)
                    event("TRADE", f"[PAPER] {res['signal']} {symbol} [{tf}] - slot {len(paper_open_symbols)}/{max_slots}")
                    continue

                if not (key and secret and res.get("price")):
                    event("WARNING", f"Pomini臋to {symbol}: brak kluczy API lub ceny.")
                    continue

                try:
                    # Od艣wie偶 pozycje przed ka偶dym zleceniem. Przy b艂臋dzie API nie handlujemy w ciemno.
                    current_positions = active_positions(ex)
                    current_symbols = {str(pos.get("symbol")) for pos in current_positions if pos.get("symbol")}
                    current_count = len(current_positions)
                    # Nie licz drugi raz pozycji, kt贸re gie艂da zd膮偶y艂a ju偶 zwr贸ci膰.
                    reserved_not_visible = [s for s in opened_this_scan if s not in current_symbols]
                    effective_count = current_count + len(reserved_not_visible)
                    if effective_count >= max_slots:
                        event("WARNING", f"Pomini臋to {symbol}: osi膮gni臋to limit {max_slots} otwartych slot贸w.")
                        continue
                    if symbol in current_symbols or symbol in opened_this_scan:
                        event("INFO", f"Pomini臋to {symbol}: pozycja na tej parze ju偶 istnieje lub zosta艂a otwarta w tym skanie.")
                        continue

                    free, total = balance_usdt(ex)
                    qty, notional = calc_qty(ex, symbol, total, free, res["price"], cfg)
                    if qty <= 0 or notional <= 0:
                        event("WARNING", f"Pomini臋to {symbol}: za ma艂o wolnych 艣rodk贸w na nowe zlecenie.")
                        continue
                    try:
                        ex.set_leverage(int(cfg["max_leverage"]), symbol)
                    except Exception as lev_exc:
                        event("WARNING", f"Nie uda艂o si臋 ustawi膰 d藕wigni dla {symbol}: {lev_exc}")
                    order = market_order(ex, symbol, "buy" if res["signal"] == "LONG" else "sell", qty)
                    opened_this_scan.append(symbol)
                    event("TRADE", f"Otwarto {res['signal']} {symbol} qty={qty} notional={notional:.2f} USDT; slot do {effective_count + 1}/{max_slots}; id={order.get('id')}")
                except Exception as trade_exc:
                    event("ERROR", f"Nie otwarto pozycji {symbol}: {trade_exc}")
                    st.warning(f"Nie otwarto pozycji {symbol}: {trade_exc}")
        st.dataframe(pd.DataFrame(results), use_container_width=True, hide_index=True)
    except Exception as exc:
        st.error(f"B\u0142\u0105d podczas skanowania gie\u0142dy: {exc}")
    if cfg.get("auto_refresh"):
        st.warning(f"Od\u015bwie\u017cenie za {int(cfg.get('refresh_seconds', 30))} s.")
        time.sleep(max(10, int(cfg.get("refresh_seconds", 30))))
        st.rerun()


# ========================================================
# USTAWIENIA STRATEGII
# ========================================================
elif page == "Ustawienia Strategii":
    st.subheader("Ustawienia strategii, adaptacja i ryzyko")
    if "selected_tf_edit" not in st.session_state:
        st.session_state["selected_tf_edit"] = "1d"
    selected_tf = st.selectbox("Wybierz interwa\u0142 do edycji", TF_OPTIONS,
                               index=TF_OPTIONS.index(st.session_state["selected_tf_edit"]))
    st.session_state["selected_tf_edit"] = selected_tf
    base = cfg["tf_settings"].get(selected_tf, DEFAULT_TF_SETTINGS[selected_tf])
    with st.form("cfgform"):
        a, b = st.columns(2)
        with a:
            exchange_name = st.selectbox("Gie\u0142da", ["bitget", "binanceusdm", "bybit", "okx"],
                index=["bitget", "binanceusdm", "bybit", "okx"].index(cfg["exchange"]) if cfg["exchange"] in ["bitget", "binanceusdm", "bybit", "okx"] else 0)
            market_type = st.selectbox("Rynek", ["swap", "future"], index=0 if cfg["market_type"] == "swap" else 1)
            scan_limit = st.slider("Limit skanowanych par", 5, 50, int(cfg.get("scan_limit_count", 30)))
            timeframes = st.multiselect("Interwa\u0142y do skanowania", TF_OPTIONS,
                default=[x for x in cfg.get("timeframes", ["4h", "1d"]) if x in TF_OPTIONS])
            multiplier = st.slider("Multiplikator wska\u017anik\u00f3w (%)", 10, 100, int(cfg.get("indicator_multiplier", 60)))
        with b:
            risk = st.number_input("Maks. ryzyko na pozycj\u0119 (USDT)", 1.0, 10000.0, float(cfg["risk_usdt"]))
            max_positions = st.number_input("Maks. otwarte pozycje", 1, 20, int(cfg["max_positions"]))
            max_leverage = st.number_input("Maksymalna d\u017awignia", 1, 50, int(cfg["max_leverage"]))
            sl_roe = st.number_input("Stop-loss ROE (%)", 1.0, 95.0, float(cfg["sl_roe"]))
            tp_roe = st.number_input("Take-profit ROE (%)", 1.0, 500.0, float(cfg["tp_roe"]))
            allow_long = st.checkbox("Pozw\u00f3l na LONG", bool(cfg["allow_long"]))
            allow_short = st.checkbox("Pozw\u00f3l na SHORT", bool(cfg["allow_short"]))
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
            st.error("EMA szybka powinna by\u0107 mniejsza od EMA wolnej.")
        elif rmin >= rmax:
            st.error("RSI min musi by\u0107 mniejsze od RSI max.")
        else:
            cfg.update({"exchange": exchange_name, "market_type": market_type,
                "scan_limit_count": scan_limit, "timeframes": timeframes or ["4h", "1d"],
                "indicator_multiplier": multiplier, "risk_usdt": risk,
                "max_positions": int(max_positions), "max_leverage": int(max_leverage),
                "sl_roe": sl_roe, "tp_roe": tp_roe, "allow_long": allow_long, "allow_short": allow_short})
            cfg["tf_settings"][selected_tf] = {"ema_fast": int(fast), "ema_slow": int(slow),
                "adx_threshold": float(adx), "rsi_min": float(rmin), "rsi_max": float(rmax)}
            save_cfg(cfg)
            st.success("Zapisano ustawienia. Zostan\u0105 przywr\u00f3cone po ponownym uruchomieniu.")
            st.rerun()


# ========================================================
# API
# ========================================================
elif page == "Po\u0142\u0105czenie API":
    st.subheader("Po\u0142\u0105czenie gie\u0142dowe")
    with st.form("credentials"):
        ex_choice = st.selectbox("Gie\u0142da", ["bitget", "binanceusdm", "bybit", "okx"],
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
            st.success("Po\u0142\u0105czenie dzia\u0142a")
            x, y = st.columns(2)
            x.metric("USDT dost\u0119pne", f"{free:.2f}")
            y.metric("USDT \u0142\u0105cznie", f"{total:.2f}")
        except Exception as exc:
            st.error(f"B\u0142\u0105d API: {exc}")


# ========================================================
# DZIENNIK
# ========================================================
elif page == "Dziennik":
    st.subheader("Zdarzenia i zlecenia bota")
    with db() as con:
        rows = con.execute("SELECT ts,level,message FROM events ORDER BY id DESC LIMIT 200").fetchall()
    if rows:
        st.dataframe(pd.DataFrame([tuple(r) for r in rows], columns=["UTC", "Poziom", "Wiadomo\u015b\u0107"]),
                     use_container_width=True, hide_index=True)
    else:
        st.info("Brak zdarze\u0144.")


# ========================================================
# INSTRUKCJA I REGULAMIN
# ========================================================
elif page == "Regulamin & Instrukcja Obs\u0142ugi":
    st.subheader("Regulamin i instrukcja obs\u0142ugi")
    tab_help, tab_terms = st.tabs(["\U0001f4d6 Instrukcja obs\u0142ugi", "\U0001f4dc Regulamin"])
    with tab_help:
        st.markdown(""" ### Jak skonfigurowa\u0107 Bitget-SaaS? 1. Za\u0142\u00f3\u017c konto, zaloguj si\u0119 i op\u0142a\u0107 subskrypcj\u0119 przyciskiem w panelu bocznym. 2. Administrator sprawdza p\u0142atno\u015b\u0107 w panelu Stripe i r\u0119cznie aktywuje dost\u0119p. 3. Na gie\u0142dzie utw\u00f3rz klucz API z uprawnieniami odczytu i handlu Futures. Nie w\u0142\u0105czaj wyp\u0142at. 4. Wprowad\u017a API Key, Secret i Passphrase w zak\u0142adce **Po\u0142\u0105czenie API**. 5. Ustaw ryzyko, interwa\u0142y oraz wska\u017aniki w **Ustawieniach Strategii**. 6. Przed handlem na \u017cywo przetestuj konfiguracj\u0119 w trybie PAPER. """)
    with tab_terms:
        st.markdown(""" ### REGULAMIN BITGET-SAAS FUTURES 1. Serwis udost\u0119pnia narz\u0119dzia programowe do analizy rynku i sk\u0142adania zlece\u0144. 2. U\u017cytkownik odpowiada za klucze API, ustawienia ryzyka i decyzje inwestycyjne. 3. Handel futures wi\u0105\u017ce si\u0119 z ryzykiem utraty kapita\u0142u; wyniki nie s\u0105 gwarantowane. 4. Dost\u0119p p\u0142atny kosztuje 49 PLN miesi\u0119cznie, zgodnie z informacj\u0105 przedstawion\u0105 przy p\u0142atno\u015bci. """)


# ========================================================
# PANEL ADMINISTRATORA
# ========================================================
elif page == "Panel Administratora (Subskrybenci)" and is_user_admin():
    st.subheader("Panel zarz\u0105dzania u\u017cytkownikami i subskrypcjami")
    with db() as con:
        rows = con.execute("SELECT id,username,email,subscription,stripe_paid FROM users ORDER BY id").fetchall()
    if rows:
        df = pd.DataFrame([tuple(r) for r in rows],
                          columns=["ID", "Nazwa u\u017cytkownika", "E-mail", "Pakiet", "Op\u0142acone (0/1)"])
        st.dataframe(df, use_container_width=True, hide_index=True)
        with st.form("admin_manage_form"):
            user_id = st.selectbox("Wybierz ID u\u017cytkownika", df["ID"].tolist())
            action = st.selectbox("Akcja", ["Aktywuj subskrypcj\u0119", "Odbierz subskrypcj\u0119", "Usu\u0144 u\u017cytkownika"])
            confirm = st.checkbox("Potwierdzam wykonanie wybranej operacji")
            go = st.form_submit_button("WYKONAJ AKCJ\u0118", use_container_width=True)
        if go:
            if not confirm:
                st.error("Zaznacz potwierdzenie operacji.")
            else:
                with db() as con:
                    if action == "Aktywuj subskrypcj\u0119":
                        con.execute("UPDATE users SET stripe_paid=1 WHERE id=?", (user_id,))
                    elif action == "Odbierz subskrypcj\u0119":
                        con.execute("UPDATE users SET stripe_paid=0 WHERE id=?", (user_id,))
                    else:
                        con.execute("DELETE FROM users WHERE id=?", (user_id,))
                    con.commit()
                event("ADMIN", f"{action}; user_id={user_id}")
                st.success("Operacja wykonana.")
                st.rerun()
    else:
        st.info("Brak u\u017cytkownik\u00f3w.")


# ========================================================
# PANEL KAPITA\u0141U
# ========================================================
elif page == "Panel Sesji i Kapita\u0142u":
    st.subheader("Panel sesji i analiza kapita\u0142u")
    total_bal, free_bal, active_slots, session_pnl, used_margin = 0.0, 0.0, 0, 0.0, 0.0
    if key and secret:
        try:
            client = exchange_client(ex_id, key, secret, passphrase, cfg["market_type"])
            active = active_positions(client)
            # Najpierw pobierz otwarte pozycje, aby saldo ca艂kowite nie by艂o
            # b艂臋dnie r贸wne wolnemu, gdy gie艂da nie raportuje pola used.
            free_bal, total_bal = balance_usdt(client, active)
            active_slots = len(active)
            session_pnl = sum(_as_float(p.get("unrealizedPnl")) for p in active)
            used_margin = sum(_as_float(p.get("initialMargin") or p.get("margin")) for p in active)
        except Exception as exc:
            st.warning(f"Nie uda\u0142o si\u0119 pobra\u0107 salda/pozycji: {exc}")
    max_slots = int(cfg["max_positions"])
    free_slots = max(0, max_slots-active_slots)
    c1, c2, c3, c4 = st.columns(4)
    c1.markdown(f'<div class="panel"><div class="metric-label">Saldo ca\u0142kowite</div><div class="metric-value">{total_bal:.2f} USDT</div><div class="muted">Wolne: {free_bal:.2f} USDT</div></div>', unsafe_allow_html=True)
    c2.markdown(f'<div class="panel"><div class="metric-label">Sloty pozycji</div><div class="metric-value">{active_slots} / {max_slots}</div><div class="muted">Wolne sloty: {free_slots}</div></div>', unsafe_allow_html=True)
    pnl_color = "#28a8ff" if session_pnl >= 0 else "#ff4d4d"
    c3.markdown(f'<div class="panel"><div class="metric-label">Niezrealizowany PnL</div><div class="metric-value" style="color:{pnl_color}">{session_pnl:+.2f} USDT</div><div class="muted">U\u017cyty margin: {used_margin:.2f} USDT</div></div>', unsafe_allow_html=True)
    c4.markdown(f'<div class="panel"><div class="metric-label">Autopilot</div><div class="metric-value">{"W\u0141\u0104CZONY" if cfg["auto_trade"] else "WY\u0141\u0104CZONY"}</div><div class="muted">Tryb: {"PAPER" if cfg["paper_mode"] else "LIVE"}</div></div>', unsafe_allow_html=True)
    st.divider()
    st.markdown("### Bie\u017c\u0105ce aktywne pozycje")
    if key and secret:
        try:
            client = exchange_client(ex_id, key, secret, passphrase, cfg["market_type"])
            active = active_positions(client)
            if active:
                st.dataframe(pd.DataFrame([{"Symbol": p.get("symbol"), "Strona": p.get("side"),
                    "Kontrakty": p.get("contracts"), "Wej\u015bcie": p.get("entryPrice"),
                    "PnL (USDT)": p.get("unrealizedPnl")} for p in active]),
                    use_container_width=True, hide_index=True)
            else:
                st.info("Brak otwartych pozycji.")
        except Exception as exc:
            st.warning(f"Nie uda\u0142o si\u0119 pobra\u0107 pozycji: {exc}")
    else:
        st.info("Skonfiguruj dane API, aby zobaczy\u0107 pozycje.")
    st.divider()
    st.markdown("### Awaryjne zamkni\u0119cie wszystkich pozycji")
    if st.button("ZAMKNIJ WSZYSTKIE POZYCJE RYNKOWO", type="secondary"):
        try:
            if not key or not secret:
                raise RuntimeError("Brak kluczy API")
            client = exchange_client(ex_id, key, secret, passphrase, cfg["market_type"])
            positions = active_positions(client)
            outcomes = []
            for pos in positions:
                qty = abs(float(pos.get("contracts") or 0))
                symbol = pos.get("symbol")
                if qty <= 0 or not symbol:
                    continue
                close_side = "sell" if str(pos.get("side") or "").lower() in ("long", "buy") else "buy"
                try:
                    order = market_order(client, symbol, close_side, qty, True)
                    outcomes.append(f"{symbol}: zamkni\u0119to {qty}; order={order.get('id')}")
                except Exception as exc:
                    outcomes.append(f"{symbol}: B\u0141\u0104D {exc}")
            for line in outcomes:
                event("KILL", line)
            st.write("\n".join(outcomes) if outcomes else "Brak aktywnych pozycji.")
        except Exception as exc:
            st.error(f"Kill switch nie powi\u00f3d\u0142 si\u0119: {exc}")

    # Od艣wie偶aj panel salda i pozycji niezale偶nie od tego, czy Auto-Trade jest w艂膮czony.
    if cfg.get("auto_refresh", True):
        refresh_interval = max(10, int(cfg.get("refresh_seconds", 30)))
        st.caption(f"Dane salda i pozycji od艣wie偶膮 si臋 automatycznie za {refresh_interval} s. Ostatnie pobranie: {datetime.now().astimezone().strftime('%H:%M:%S')}")
        time.sleep(refresh_interval)
        st.rerun()

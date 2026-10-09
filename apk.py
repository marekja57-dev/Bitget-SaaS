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
st.set_page_config(page_title="Bitget-SaaS Futures", page_icon="馃搱", layout="wide")

APP_DIR = Path(__file__).resolve().parent
DB_PATH = Path(os.getenv("BITGET_SAAS_DB", str(APP_DIR / "bitget_saas.db")))
LOG_PATH = APP_DIR / "trading.log"
logging.basicConfig(filename=str(LOG_PATH), level=logging.INFO,
                    format="%(asctime)s %(levelname)s %(message)s")

# Produkcyjny Payment Link skopiowany z panelu Stripe ze zdj臋cia.
# Mo偶na go nadpisa膰 zmienn膮 艣rodowiskow膮 STRIPE_CHECKOUT_FALLBACK.
STRIPE_CHECKOUT_FALLBACK = os.getenv(
    "STRIPE_CHECKOUT_FALLBACK",
    "https://buy.stripe.com/8x2dRa4CbdaxfSAF6V3oA03",
)
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

CSS = """ <style> :root { color-scheme: dark; } .stApp { background: radial-gradient(ellipse at 40% -20%, #103e78 0%, #071a36 42%, #050e20 100%); color: #eaf3ff; } [data-testid="stHeader"] { background: rgba(3,12,29,.85); } [data-testid="stSidebar"] { background: linear-gradient(180deg, #06152d, #081f42); border-right: 1px solid #164a84; } .block-container { padding-top: 1.2rem; max-width: 1600px; } .brand-retro { font-weight: 900; font-size: 38px; letter-spacing: -1px; color: #f3c653; text-shadow: 2px 2px 4px rgba(0,0,0,.6); text-align: center; margin-bottom: 0; font-family: serif; } .subbrand-retro { color: #7da9d8; font-size: 12px; letter-spacing: 2px; text-transform: uppercase; text-align: center; margin-bottom: 20px; } .brand { font-weight: 900; letter-spacing: -1px; font-size: 29px; color: #eaf5ff; } .brand span { color: #28a8ff; } .subbrand { color: #7da9d8; font-size: 11px; letter-spacing: 2px; text-transform: uppercase; } .panel { background: linear-gradient(145deg, rgba(12,43,83,.95), rgba(5,24,51,.96)); border: 1px solid #164a80; border-radius: 14px; padding: 16px 18px; box-shadow: 0 4px 12px rgba(0,0,0,.3); } .metric-label { font-size: 12px; color: #90b8e6; text-transform: uppercase; letter-spacing: 1px; } .metric-value { font-size: 24px; font-weight: 800; color: #f1f7ff; margin-top: 5px; } .muted { color: #83a7d0; font-size: 12px; margin-top: 4px; } div.stButton>button { border: 1px solid #278be8; border-radius: 8px; background: linear-gradient(180deg, #1689ff, #0759c8); color: white; font-weight: 700; } hr { border-color: #16416f; } </style> """
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
    # Obs艂uga r贸wnie偶 starych kont, kt贸re mia艂y has艂o zapisane jawnie.
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
            # Uzupe艂nij brakuj膮ce interwa艂y bez kasowania zapisanych warto艣ci.
            merged = json.loads(json.dumps(DEFAULT_TF_SETTINGS))
            merged.update(cfg.get("tf_settings", {}))
            cfg["tf_settings"] = merged
        except Exception:
            logging.exception("Nie uda艂o si臋 odczyta膰 ustawie艅")
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
    # Otw贸rz dok艂adnie Payment Link skopiowany z panelu Stripe.
    # Nie dopisuj parametr贸w ani znak贸w do adresu 鈥� najpierw potwierd藕,
    # 偶e sam link jest aktywny w panelu Stripe.
    url = STRIPE_CHECKOUT_FALLBACK.strip()
    if not url.startswith("https://buy.stripe.com/"):
        raise ValueError("W STRIPE_CHECKOUT_FALLBACK wstaw dok艂adny aktywny link https://buy.stripe.com/... z panelu Stripe.")
    return url


# ========================================================
# GIE艁DA / WSKA殴NIKI
# ========================================================
@st.cache_resource(show_spinner=False)
def exchange_client(ex_id, api_key, secret, passphrase, market_type):
    if ccxt is None:
        raise RuntimeError("Brak biblioteki ccxt. Zainstaluj: pip install ccxt")
    cls = getattr(ccxt, ex_id, None)
    if cls is None:
        raise ValueError("Nieobs艂ugiwana gie艂da: " + str(ex_id))
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
            return {"symbol": symbol, "tf": tf, "signal": "NEUTRALNY", "reason": "Za ma艂o 艣wiec"}
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
        return {"symbol": symbol, "tf": tf, "signal": "B艁膭D", "reason": str(exc)[:160]}


def market_order(ex, symbol, side, qty, reduce_only=False):
    qty = float(ex.amount_to_precision(symbol, qty))
    if qty <= 0:
        raise ValueError("Ilo艣膰 zlecenia wynosi zero")
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


def balance_usdt(ex):
    b = ex.fetch_balance()
    row = b.get("USDT") or {}
    return float(row.get("free") or 0), float(row.get("total") or 0)


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


# WA呕NE: nie aktywuj subskrypcji na podstawie ?success=true.
# Payment Link nie jest potwierdzeniem p艂atno艣ci dla aplikacji. Administrator
# aktywuje dost臋p po sprawdzeniu p艂atno艣ci w panelu Stripe.
if st.query_params.get("success") == "true":
    st.info("Powr贸t ze strony p艂atno艣ci. Dost臋p zostanie aktywowany po potwierdzeniu p艂atno艣ci przez administratora.")
    st.query_params.clear()

if not st.session_state["authenticated"]:
    st.markdown('<div class="brand-retro">Bitget-SaaS</div><div class="subbrand-retro">AUTONOMICZNY SYSTEM TRANSAKCYJNY</div>', unsafe_allow_html=True)
    tab_login, tab_reg = st.tabs(["Zaloguj si臋", "Za艂贸偶 konto i subskrypcj臋"])
    with tab_login:
        st.subheader("Logowanie do systemu")
        with st.form("login_form"):
            l_user = st.text_input("Nazwa u偶ytkownika / E-mail")
            l_pass = st.text_input("Has艂o", type="password")
            submit_login = st.form_submit_button("ZALOGUJ SI臉", use_container_width=True)
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
                st.error("Nieprawid艂owy login lub has艂o.")
    with tab_reg:
        st.subheader("Rejestracja u偶ytkownika 鈥� 49 PLN / miesi膮c")
        with st.form("reg_form"):
            r_user = st.text_input("Nazwa u偶ytkownika")
            r_email = st.text_input("Adres e-mail")
            r_pass = st.text_input("Has艂o", type="password")
            r_sub = st.selectbox("Wybierz subskrypcj臋", ["Pro Trader (49 PLN / miesi膮c)", "VIP SaaS (Roczny)"])
            submit_reg = st.form_submit_button("ZAREJESTRUJ SI臉", use_container_width=True)
        if submit_reg:
            if not r_user.strip() or not r_pass.strip() or not r_email.strip():
                st.error("Uzupe艂nij login, e-mail i has艂o.")
            elif "@" not in r_email or "." not in r_email.rsplit("@", 1)[-1]:
                st.error("Podaj prawid艂owy adres e-mail.")
            else:
                try:
                    with db() as con:
                        con.execute("""INSERT INTO users(username,password,subscription,stripe_paid,email) VALUES(?,?,?,0,?)""",
                            (r_user.strip(), password_hash(r_pass), r_sub, r_email.strip().lower()))
                        con.commit()
                    st.success("Konto utworzone. Zaloguj si臋, a nast臋pnie op艂a膰 subskrypcj臋.")
                except sqlite3.IntegrityError:
                    st.error("Taki login lub adres e-mail ju偶 istnieje.")
    st.stop()


cfg = load_cfg()
ex_id, key, secret, passphrase = load_creds()

with st.sidebar:
    st.markdown(f'<div class="brand"><span>鈿�</span> Bitget-SaaS</div><div class="subbrand">Witaj, {st.session_state["username"]}</div>', unsafe_allow_html=True)
    nav_options = ["Automatyczny Skaner i Auto-Handel", "Panel Sesji i Kapita艂u",
                   "Ustawienia Strategii", "Po艂膮czenie API", "Dziennik",
                   "Regulamin & Instrukcja Obs艂ugi"]
    if is_user_admin():
        nav_options.append("Panel Administratora (Subskrybenci)")
    page = st.radio("NAWIGACJA", nav_options)
    st.markdown("---")
    st.markdown("### Status Subskrypcji (49 PLN)")
    if is_user_admin():
        st.success("Administrator (Pe艂ny Dost臋p)")
    elif is_user_paid():
        st.success("Subskrypcja aktywna (Pro)")
    else:
        st.warning("Subskrypcja nieop艂acona")
    try:
        checkout_url = create_stripe_checkout_url(st.session_state.get("user_email", ""))
        st.link_button("OP艁A膯 SUBSKRYPCJ臉 (49 PLN)", checkout_url, use_container_width=True)
    except Exception as exc:
        st.error(f"Nieprawid艂owa konfiguracja linku Stripe: {exc}")
    st.caption("Po p艂atno艣ci administrator potwierdza transakcj臋 i aktywuje dost臋p.")
    st.divider()
    if st.button("Wyloguj", use_container_width=True):
        for k in ["authenticated", "logged_in", "username", "user_id", "stripe_paid", "user_email"]:
            st.session_state[k] = False if k in ("authenticated", "logged_in") else "" if k in ("username", "user_email") else None if k == "user_id" else 0
        st.rerun()
    if st.button("Wyczy艣膰 cache danych", use_container_width=True):
        get_candles.clear()
        st.success("Cache danych wyczyszczony.")

st.markdown('<div class="brand"><span>Bitget</span>-SaaS Futures</div><div class="subbrand">AUTONOMICZNY SYSTEM TRANSAKCYJNY</div>', unsafe_allow_html=True)


# ========================================================
# SKANER
# ========================================================
if page == "Automatyczny Skaner i Auto-Handel":
    st.subheader("Automatyczny Skaner Rynku i Cykliczny Auto-Handel")
    st.write("Bot skanuje wybrane pary i interwa艂y w ustalonych odst臋pach czasu.")
    with st.form("control_form"):
        auto_trade = st.checkbox("W艂膮cz automatyczny handel (Auto-Trade)", value=bool(cfg["auto_trade"]))
        paper_mode = st.checkbox("Tryb symulacji PAPER (brak zlece艅 na 偶ywo)", value=bool(cfg["paper_mode"]))
        auto_refresh = st.checkbox("W艂膮cz ci膮g艂e skanowanie", value=bool(cfg.get("auto_refresh", True)))
        refresh_seconds = st.slider("Odst臋p czasu mi臋dzy skanami (sekundy)", 10, 300, int(cfg.get("refresh_seconds", 30)))
        submit_ctrl = st.form_submit_button("ZAPISZ TRYB PRACY", use_container_width=True)
    if submit_ctrl:
        cfg.update({"auto_trade": auto_trade, "paper_mode": paper_mode,
                    "auto_refresh": auto_refresh, "refresh_seconds": refresh_seconds})
        save_cfg(cfg)
        st.success("Zapisano tryb pracy.")
        st.rerun()

    st.warning("Handel LIVE mo偶e powodowa膰 straty. Najpierw sprawd藕 dzia艂anie w trybie PAPER.")
    try:
        ex = exchange_client(ex_id, key, secret, passphrase, cfg["market_type"])
        markets = ex.load_markets()
        symbols = [s for s, m in markets.items()
                   if m.get("quote") == "USDT" and m.get("active") and m.get("linear")]
        symbols = symbols[:int(cfg.get("scan_limit_count", 30))]
        tfs = [tf for tf in cfg.get("timeframes", ["4h", "1d"]) if tf in TF_OPTIONS]
        st.info(f"Skanowanie {len(symbols)} par na interwa艂ach: {', '.join(tfs)}")
        results = []
        free, total = balance_usdt(ex) if not cfg["paper_mode"] and key and secret else (1000.0, 1000.0)
        for symbol in symbols:
            for tf in tfs:
                res = signal_for_symbol(cfg, symbol, tf)
                results.append(res)
                if res["signal"] in ("LONG", "SHORT"):
                    event("INFO", f"Sygna艂 {res['signal']} {symbol} [{tf}]")
                    if cfg["auto_trade"]:
                        if cfg["paper_mode"]:
                            event("TRADE", f"[PAPER] Sygna艂 {res['signal']} {symbol} [{tf}]")
                        elif key and secret and res.get("price"):
                            qty, notional = calc_qty(ex, symbol, total, free, res["price"], cfg)
                            if qty > 0:
                                try:
                                    ex.set_leverage(int(cfg["max_leverage"]), symbol)
                                except Exception:
                                    pass
                                order = market_order(ex, symbol, "buy" if res["signal"] == "LONG" else "sell", qty)
                                event("TRADE", f"Otwarto {res['signal']} {symbol} qty={qty} id={order.get('id')}")
        st.dataframe(pd.DataFrame(results), use_container_width=True, hide_index=True)
    except Exception as exc:
        st.error(f"B艂膮d podczas skanowania gie艂dy: {exc}")
    if cfg.get("auto_refresh") and cfg.get("auto_trade"):
        st.warning(f"Od艣wie偶enie za {int(cfg.get('refresh_seconds', 30))} s.")
        time.sleep(int(cfg.get("refresh_seconds", 30)))
        st.rerun()


# ========================================================
# USTAWIENIA STRATEGII
# ========================================================
elif page == "Ustawienia Strategii":
    st.subheader("Ustawienia strategii, adaptacja i ryzyko")
    if "selected_tf_edit" not in st.session_state:
        st.session_state["selected_tf_edit"] = "1d"
    selected_tf = st.selectbox("Wybierz interwa艂 do edycji", TF_OPTIONS,
                               index=TF_OPTIONS.index(st.session_state["selected_tf_edit"]))
    st.session_state["selected_tf_edit"] = selected_tf
    base = cfg["tf_settings"].get(selected_tf, DEFAULT_TF_SETTINGS[selected_tf])
    with st.form("cfgform"):
        a, b = st.columns(2)
        with a:
            exchange_name = st.selectbox("Gie艂da", ["bitget", "binanceusdm", "bybit", "okx"],
                index=["bitget", "binanceusdm", "bybit", "okx"].index(cfg["exchange"]) if cfg["exchange"] in ["bitget", "binanceusdm", "bybit", "okx"] else 0)
            market_type = st.selectbox("Rynek", ["swap", "future"], index=0 if cfg["market_type"] == "swap" else 1)
            scan_limit = st.slider("Limit skanowanych par", 5, 50, int(cfg.get("scan_limit_count", 30)))
            timeframes = st.multiselect("Interwa艂y do skanowania", TF_OPTIONS,
                default=[x for x in cfg.get("timeframes", ["4h", "1d"]) if x in TF_OPTIONS])
            multiplier = st.slider("Multiplikator wska藕nik贸w (%)", 10, 100, int(cfg.get("indicator_multiplier", 60)))
        with b:
            risk = st.number_input("Maks. ryzyko na pozycj臋 (USDT)", 1.0, 10000.0, float(cfg["risk_usdt"]))
            max_positions = st.number_input("Maks. otwarte pozycje", 1, 20, int(cfg["max_positions"]))
            max_leverage = st.number_input("Maksymalna d藕wignia", 1, 50, int(cfg["max_leverage"]))
            sl_roe = st.number_input("Stop-loss ROE (%)", 1.0, 95.0, float(cfg["sl_roe"]))
            tp_roe = st.number_input("Take-profit ROE (%)", 1.0, 500.0, float(cfg["tp_roe"]))
            allow_long = st.checkbox("Pozw贸l na LONG", bool(cfg["allow_long"]))
            allow_short = st.checkbox("Pozw贸l na SHORT", bool(cfg["allow_short"]))
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
            st.error("EMA szybka powinna by膰 mniejsza od EMA wolnej.")
        elif rmin >= rmax:
            st.error("RSI min musi by膰 mniejsze od RSI max.")
        else:
            cfg.update({"exchange": exchange_name, "market_type": market_type,
                "scan_limit_count": scan_limit, "timeframes": timeframes or ["4h", "1d"],
                "indicator_multiplier": multiplier, "risk_usdt": risk,
                "max_positions": int(max_positions), "max_leverage": int(max_leverage),
                "sl_roe": sl_roe, "tp_roe": tp_roe, "allow_long": allow_long, "allow_short": allow_short})
            cfg["tf_settings"][selected_tf] = {"ema_fast": int(fast), "ema_slow": int(slow),
                "adx_threshold": float(adx), "rsi_min": float(rmin), "rsi_max": float(rmax)}
            save_cfg(cfg)
            st.success("Zapisano ustawienia. Zostan膮 przywr贸cone po ponownym uruchomieniu.")
            st.rerun()


# ========================================================
# API
# ========================================================
elif page == "Po艂膮czenie API":
    st.subheader("Po艂膮czenie gie艂dowe")
    with st.form("credentials"):
        ex_choice = st.selectbox("Gie艂da", ["bitget", "binanceusdm", "bybit", "okx"],
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
            st.success("Po艂膮czenie dzia艂a")
            x, y = st.columns(2)
            x.metric("USDT dost臋pne", f"{free:.2f}")
            y.metric("USDT 艂膮cznie", f"{total:.2f}")
        except Exception as exc:
            st.error(f"B艂膮d API: {exc}")


# ========================================================
# DZIENNIK
# ========================================================
elif page == "Dziennik":
    st.subheader("Zdarzenia i zlecenia bota")
    with db() as con:
        rows = con.execute("SELECT ts,level,message FROM events ORDER BY id DESC LIMIT 200").fetchall()
    if rows:
        st.dataframe(pd.DataFrame([tuple(r) for r in rows], columns=["UTC", "Poziom", "Wiadomo艣膰"]),
                     use_container_width=True, hide_index=True)
    else:
        st.info("Brak zdarze艅.")


# ========================================================
# INSTRUKCJA I REGULAMIN
# ========================================================
elif page == "Regulamin & Instrukcja Obs艂ugi":
    st.subheader("Regulamin i instrukcja obs艂ugi")
    tab_help, tab_terms = st.tabs(["馃摉 Instrukcja obs艂ugi", "馃摐 Regulamin"])
    with tab_help:
        st.markdown(""" ### Jak skonfigurowa膰 Bitget-SaaS? 1. Za艂贸偶 konto, zaloguj si臋 i op艂a膰 subskrypcj臋 przyciskiem w panelu bocznym. 2. Administrator sprawdza p艂atno艣膰 w panelu Stripe i r臋cznie aktywuje dost臋p. 3. Na gie艂dzie utw贸rz klucz API z uprawnieniami odczytu i handlu Futures. Nie w艂膮czaj wyp艂at. 4. Wprowad藕 API Key, Secret i Passphrase w zak艂adce **Po艂膮czenie API**. 5. Ustaw ryzyko, interwa艂y oraz wska藕niki w **Ustawieniach Strategii**. 6. Przed handlem na 偶ywo przetestuj konfiguracj臋 w trybie PAPER. """)
    with tab_terms:
        st.markdown(""" ### REGULAMIN BITGET-SAAS FUTURES 1. Serwis udost臋pnia narz臋dzia programowe do analizy rynku i sk艂adania zlece艅. 2. U偶ytkownik odpowiada za klucze API, ustawienia ryzyka i decyzje inwestycyjne. 3. Handel futures wi膮偶e si臋 z ryzykiem utraty kapita艂u; wyniki nie s膮 gwarantowane. 4. Dost臋p p艂atny kosztuje 49 PLN miesi臋cznie, zgodnie z informacj膮 przedstawion膮 przy p艂atno艣ci. """)


# ========================================================
# PANEL ADMINISTRATORA
# ========================================================
elif page == "Panel Administratora (Subskrybenci)" and is_user_admin():
    st.subheader("Panel zarz膮dzania u偶ytkownikami i subskrypcjami")
    with db() as con:
        rows = con.execute("SELECT id,username,email,subscription,stripe_paid FROM users ORDER BY id").fetchall()
    if rows:
        df = pd.DataFrame([tuple(r) for r in rows],
                          columns=["ID", "Nazwa u偶ytkownika", "E-mail", "Pakiet", "Op艂acone (0/1)"])
        st.dataframe(df, use_container_width=True, hide_index=True)
        with st.form("admin_manage_form"):
            user_id = st.selectbox("Wybierz ID u偶ytkownika", df["ID"].tolist())
            action = st.selectbox("Akcja", ["Aktywuj subskrypcj臋", "Odbierz subskrypcj臋", "Usu艅 u偶ytkownika"])
            confirm = st.checkbox("Potwierdzam wykonanie wybranej operacji")
            go = st.form_submit_button("WYKONAJ AKCJ臉", use_container_width=True)
        if go:
            if not confirm:
                st.error("Zaznacz potwierdzenie operacji.")
            else:
                with db() as con:
                    if action == "Aktywuj subskrypcj臋":
                        con.execute("UPDATE users SET stripe_paid=1 WHERE id=?", (user_id,))
                    elif action == "Odbierz subskrypcj臋":
                        con.execute("UPDATE users SET stripe_paid=0 WHERE id=?", (user_id,))
                    else:
                        con.execute("DELETE FROM users WHERE id=?", (user_id,))
                    con.commit()
                event("ADMIN", f"{action}; user_id={user_id}")
                st.success("Operacja wykonana.")
                st.rerun()
    else:
        st.info("Brak u偶ytkownik贸w.")


# ========================================================
# PANEL KAPITA艁U
# ========================================================
elif page == "Panel Sesji i Kapita艂u":
    st.subheader("Panel sesji i analiza kapita艂u")
    total_bal, free_bal, active_slots, session_pnl, used_margin = 0.0, 0.0, 0, 0.0, 0.0
    if key and secret:
        try:
            client = exchange_client(ex_id, key, secret, passphrase, cfg["market_type"])
            free_bal, total_bal = balance_usdt(client)
            positions = client.fetch_positions()
            active = [p for p in positions or [] if abs(float(p.get("contracts") or 0)) > 0]
            active_slots = len(active)
            session_pnl = sum(float(p.get("unrealizedPnl") or 0) for p in active)
            used_margin = sum(float(p.get("initialMargin") or p.get("margin") or 0) for p in active)
        except Exception as exc:
            st.warning(f"Nie uda艂o si臋 pobra膰 salda/pozycji: {exc}")
    max_slots = int(cfg["max_positions"])
    free_slots = max(0, max_slots-active_slots)
    c1, c2, c3, c4 = st.columns(4)
    c1.markdown(f'<div class="panel"><div class="metric-label">Saldo ca艂kowite</div><div class="metric-value">{total_bal:.2f} USDT</div><div class="muted">Wolne: {free_bal:.2f} USDT</div></div>', unsafe_allow_html=True)
    c2.markdown(f'<div class="panel"><div class="metric-label">Sloty pozycji</div><div class="metric-value">{active_slots} / {max_slots}</div><div class="muted">Wolne sloty: {free_slots}</div></div>', unsafe_allow_html=True)
    pnl_color = "#28a8ff" if session_pnl >= 0 else "#ff4d4d"
    c3.markdown(f'<div class="panel"><div class="metric-label">Niezrealizowany PnL</div><div class="metric-value" style="color:{pnl_color}">{session_pnl:+.2f} USDT</div><div class="muted">U偶yty margin: {used_margin:.2f} USDT</div></div>', unsafe_allow_html=True)
    c4.markdown(f'<div class="panel"><div class="metric-label">Autopilot</div><div class="metric-value">{"W艁膭CZONY" if cfg["auto_trade"] else "WY艁膭CZONY"}</div><div class="muted">Tryb: {"PAPER" if cfg["paper_mode"] else "LIVE"}</div></div>', unsafe_allow_html=True)
    st.divider()
    st.markdown("### Bie偶膮ce aktywne pozycje")
    if key and secret:
        try:
            client = exchange_client(ex_id, key, secret, passphrase, cfg["market_type"])
            positions = client.fetch_positions()
            active = [p for p in positions or [] if abs(float(p.get("contracts") or 0)) > 0]
            if active:
                st.dataframe(pd.DataFrame([{"Symbol": p.get("symbol"), "Strona": p.get("side"),
                    "Kontrakty": p.get("contracts"), "Wej艣cie": p.get("entryPrice"),
                    "PnL (USDT)": p.get("unrealizedPnl")} for p in active]),
                    use_container_width=True, hide_index=True)
            else:
                st.info("Brak otwartych pozycji.")
        except Exception as exc:
            st.warning(f"Nie uda艂o si臋 pobra膰 pozycji: {exc}")
    else:
        st.info("Skonfiguruj dane API, aby zobaczy膰 pozycje.")
    st.divider()
    st.markdown("### Awaryjne zamkni臋cie wszystkich pozycji")
    if st.button("ZAMKNIJ WSZYSTKIE POZYCJE RYNKOWO", type="secondary"):
        try:
            if not key or not secret:
                raise RuntimeError("Brak kluczy API")
            client = exchange_client(ex_id, key, secret, passphrase, cfg["market_type"])
            positions = client.fetch_positions()
            outcomes = []
            for pos in positions or []:
                qty = abs(float(pos.get("contracts") or 0))
                symbol = pos.get("symbol")
                if qty <= 0 or not symbol:
                    continue
                close_side = "sell" if str(pos.get("side") or "").lower() in ("long", "buy") else "buy"
                try:
                    order = market_order(client, symbol, close_side, qty, True)
                    outcomes.append(f"{symbol}: zamkni臋to {qty}; order={order.get('id')}")
                except Exception as exc:
                    outcomes.append(f"{symbol}: B艁膭D {exc}")
            for line in outcomes:
                event("KILL", line)
            st.write("\n".join(outcomes) if outcomes else "Brak aktywnych pozycji.")
        except Exception as exc:
            st.error(f"Kill switch nie powi贸d艂 si臋: {exc}")

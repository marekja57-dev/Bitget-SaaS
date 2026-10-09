import os
import json
import sqlite3
import time
import logging
from pathlib import Path
from datetime import datetime, timezone
from urllib.parse import urlencode

import pandas as pd
import numpy as np
import streamlit as st

try:
    import ccxt
except ImportError:
    ccxt = None

try:
    import stripe
except ImportError:
    stripe = None


APP_DIR = Path(__file__).resolve().parent
DB_PATH = Path(os.getenv("BITGET_SAAS_DB", APP_DIR / "bitget_saas.db"))
LOG_PATH = APP_DIR / "trading.log"

logging.basicConfig(
    filename=LOG_PATH,
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)

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
    "tf_settings": {
        "1m": {"ema_fast": 9, "ema_slow": 21, "adx_threshold": 25.0, "rsi_min": 25.0, "rsi_max": 75.0},
        "3m": {"ema_fast": 9, "ema_slow": 21, "adx_threshold": 25.0, "rsi_min": 25.0, "rsi_max": 75.0},
        "5m": {"ema_fast": 9, "ema_slow": 21, "adx_threshold": 25.0, "rsi_min": 25.0, "rsi_max": 75.0},
        "15m": {"ema_fast": 9, "ema_slow": 21, "adx_threshold": 25.0, "rsi_min": 25.0, "rsi_max": 75.0},
        "30m": {"ema_fast": 9, "ema_slow": 21, "adx_threshold": 25.0, "rsi_min": 25.0, "rsi_max": 75.0},
        "1h": {"ema_fast": 12, "ema_slow": 26, "adx_threshold": 22.0, "rsi_min": 30.0, "rsi_max": 70.0},
        "2h": {"ema_fast": 12, "ema_slow": 26, "adx_threshold": 20.0, "rsi_min": 30.0, "rsi_max": 70.0},
        "4h": {"ema_fast": 20, "ema_slow": 50, "adx_threshold": 20.0, "rsi_min": 30.0, "rsi_max": 70.0},
        "1d": {"ema_fast": 40, "ema_slow": 140, "adx_threshold": 15.0, "rsi_min": 35.0, "rsi_max": 65.0},
    },
    "auto_refresh": True,
    "auto_trade": False,
    "paper_mode": True,
    "max_notional_usdt": 50.0,
    "cooldown_seconds": 300,
    "allow_short": True,
    "allow_long": True,
    "scan_limit_count": 30,
    "indicator_multiplier": 60,
}

TF_OPTIONS = ["1m", "3m", "5m", "15m", "30m", "1h", "2h", "4h", "1d"]

STRIPE_SECRET_KEY = os.getenv("STRIPE_SECRET_KEY", "")
STRIPE_PRICE_ID = os.getenv("STRIPE_PRICE_ID", "")
APP_BASE_URL = os.getenv("APP_BASE_URL", "http://localhost:8501").rstrip("/")
STRIPE_WEBHOOK_SECRET = os.getenv("STRIPE_WEBHOOK_SECRET", "")

try:
    STRIPE_SECRET_KEY = st.secrets.get("STRIPE_SECRET_KEY", STRIPE_SECRET_KEY)
    STRIPE_PRICE_ID = st.secrets.get("STRIPE_PRICE_ID", STRIPE_PRICE_ID)
    APP_BASE_URL = st.secrets.get("APP_BASE_URL", APP_BASE_URL).rstrip("/")
    STRIPE_WEBHOOK_SECRET = st.secrets.get("STRIPE_WEBHOOK_SECRET", STRIPE_WEBHOOK_SECRET)
except Exception:
    pass

if stripe and STRIPE_SECRET_KEY:
    stripe.api_key = STRIPE_SECRET_KEY

CSS = """ <style> :root { color-scheme: dark; } .stApp { background: radial-gradient(ellipse at 40% -20%, #103e78 0%, #071a36 42%, #050e20 100%); color: #eaf3ff; } [data-testid="stHeader"] { background: rgba(3,12,29,.85); } [data-testid="stSidebar"] { background: linear-gradient(180deg, #06152d, #081f42); border-right: 1px solid #164a84; } .block-container { padding-top: 1.2rem; max-width: 1600px; } .brand-retro { font-weight: 900; font-size: 38px; letter-spacing: -1px; color: #f3c653; text-shadow: 2px 2px 4px rgba(0,0,0,0.6); text-align: center; margin-bottom: 0px; font-family: serif; } .subbrand-retro { color: #7da9d8; font-size: 12px; letter-spacing: 2px; text-transform: uppercase; text-align: center; margin-bottom: 20px; } .brand { font-weight: 900; letter-spacing: -1px; font-size: 29px; color: #eaf5ff; } .brand span { color: #28a8ff; } .subbrand { color: #7da9d8; font-size: 11px; letter-spacing: 2px; text-transform: uppercase; } .panel { background: linear-gradient(145deg, rgba(12,43,83,.95), rgba(5,24,51,.96)); border: 1px solid #164a80; border-radius: 14px; padding: 16px 18px; box-shadow: 0 4px 12px rgba(0,0,0,0.3); } .metric-label { font-size: 12px; color: #90b8e6; text-transform: uppercase; letter-spacing: 1px; } .metric-value { font-size: 24px; font-weight: 800; color: #f1f7ff; margin-top: 5px; } .muted { color: #83a7d0; font-size: 12px; margin-top: 4px; } div.stButton>button { border: 1px solid #278be8; border-radius: 8px; background: linear-gradient(180deg, #1689ff, #0759c8); color: white; font-weight: 700; } hr { border-color: #16416f; } </style> """

st.set_page_config(page_title="Bitget-SaaS Futures", page_icon="📈", layout="wide")
st.markdown(CSS, unsafe_allow_html=True)


def db():
    conn = sqlite3.connect(DB_PATH, timeout=15)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=15000")
    conn.execute("CREATE TABLE IF NOT EXISTS settings (k TEXT PRIMARY KEY, v TEXT NOT NULL)")
    conn.execute("CREATE TABLE IF NOT EXISTS credentials (k TEXT PRIMARY KEY, exchange TEXT, api_key TEXT, secret TEXT, password TEXT)")
    conn.execute("CREATE TABLE IF NOT EXISTS bot_state (symbol TEXT PRIMARY KEY, side TEXT, entry REAL, amount REAL, opened REAL, sl REAL, tp REAL, order_id TEXT)")
    conn.execute("CREATE TABLE IF NOT EXISTS events (id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT, level TEXT, message TEXT)")
    cur = conn.cursor()
    cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='users'")
    if not cur.fetchone():
        conn.execute("""CREATE TABLE users ( id INTEGER PRIMARY KEY AUTOINCREMENT, username TEXT UNIQUE, password TEXT, subscription TEXT, stripe_paid INTEGER DEFAULT 0, email TEXT, stripe_customer_id TEXT, stripe_subscription_id TEXT )""")
    else:
        cur.execute("PRAGMA table_info(users)")
        columns = [x[1] for x in cur.fetchall()]
        for name, definition in [
            ("email", "TEXT"),
            ("stripe_paid", "INTEGER DEFAULT 0"),
            ("stripe_customer_id", "TEXT"),
            ("stripe_subscription_id", "TEXT"),
        ]:
            if name not in columns:
                conn.execute(f"ALTER TABLE users ADD COLUMN {name} {definition}")
    conn.commit()
    return conn


def load_cfg():
    out = json.loads(json.dumps(DEFAULTS))
    with db() as conn:
        row = conn.execute('SELECT v FROM settings WHERE k="main"').fetchone()
    if row:
        try:
            saved = json.loads(row[0])
            out.update(saved)
            out["tf_settings"] = {**DEFAULTS["tf_settings"], **saved.get("tf_settings", {})}
        except Exception:
            logging.exception("Could not load config")
    return out


def save_cfg(cfg):
    with db() as conn:
        conn.execute(
            "INSERT INTO settings(k,v) VALUES(?,?) ON CONFLICT(k) DO UPDATE SET v=excluded.v",
            ("main", json.dumps(cfg)),
        )


def event(level, msg):
    logging.log(getattr(logging, level, logging.INFO), msg)
    with db() as conn:
        conn.execute(
            "INSERT INTO events(ts,level,message) VALUES(?,?,?)",
            (datetime.now(timezone.utc).isoformat(), level, str(msg)[:1500]),
        )


def load_creds():
    with db() as conn:
        row = conn.execute(
            'SELECT exchange,api_key,secret,password FROM credentials WHERE k="main"'
        ).fetchone()
    return row or ("bitget", "", "", "")


def save_creds(ex, key, secret, pw):
    with db() as conn:
        conn.execute(
            """INSERT INTO credentials(k,exchange,api_key,secret,password) VALUES("main",?,?,?,?) ON CONFLICT(k) DO UPDATE SET exchange=excluded.exchange, api_key=excluded.api_key,secret=excluded.secret,password=excluded.password""",
            (ex, key, secret, pw),
        )


@st.cache_resource(show_spinner=False)
def exchange_client(ex_id, api_key, secret, password, market_type):
    if ccxt is None:
        raise RuntimeError("Brak biblioteki ccxt. Zainstaluj ccxt.")
    cls = getattr(ccxt, ex_id, None)
    if cls is None:
        raise ValueError("Nieobsługiwana giełda: " + ex_id)
    opts = {
        "enableRateLimit": True,
        "timeout": 20000,
        "options": {"defaultType": market_type, "defaultSubType": "linear"},
    }
    if api_key and secret:
        opts.update(apiKey=api_key, secret=secret)
    if password:
        opts["password"] = password
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
    gain = delta.clip(lower=0).ewm(alpha=1 / 14, adjust=False).mean()
    loss = (-delta.clip(upper=0)).ewm(alpha=1 / 14, adjust=False).mean()
    d["rsi"] = 100 - 100 / (1 + gain / loss.replace(0, np.nan))
    tr = pd.concat(
        [(d.high - d.low).abs(), (d.high - d.close.shift()).abs(), (d.low - d.close.shift()).abs()],
        axis=1,
    ).max(axis=1)
    up = d.high.diff()
    down = -d.low.diff()
    plus = pd.Series(np.where((up > down) & (up > 0), up, 0), index=d.index)
    minus = pd.Series(np.where((down > up) & (down > 0), down, 0), index=d.index)
    atr = tr.ewm(alpha=1 / 14, adjust=False).mean().replace(0, np.nan)
    pdi = 100 * plus.ewm(alpha=1 / 14, adjust=False).mean() / atr
    mdi = 100 * minus.ewm(alpha=1 / 14, adjust=False).mean() / atr
    d["adx"] = (100 * (pdi - mdi).abs() / (pdi + mdi).replace(0, np.nan)).ewm(alpha=1 / 14, adjust=False).mean()
    return d


def get_effective_tf_cfg(cfg, tf):
    base = cfg.get("tf_settings", {}).get(
        tf, {"ema_fast": 9, "ema_slow": 21, "adx_threshold": 25.0, "rsi_min": 25.0, "rsi_max": 75.0}
    )
    mult = float(cfg.get("indicator_multiplier", 60)) / 100.0
    return {
        "ema_fast": max(2, int(round(base["ema_fast"] * mult))),
        "ema_slow": max(3, int(round(base["ema_slow"] * mult))),
        "adx_threshold": max(2.0, min(90.0, base["adx_threshold"] * mult)),
        "rsi_min": max(2.0, min(45.0, base["rsi_min"] * mult)),
        "rsi_max": max(55.0, min(98.0, base["rsi_max"] * mult)),
    }


def signal_for_symbol(cfg, symbol, tf):
    try:
        tf_cfg = get_effective_tf_cfg(cfg, tf)
        raw = get_candles(cfg["exchange"], cfg["market_type"], symbol, tf, cfg["candle_limit"])
        d = indicators(raw.iloc[:-1].copy(), tf_cfg["ema_fast"], tf_cfg["ema_slow"])
        if len(d) < 35:
            return {"symbol": symbol, "tf": tf, "signal": "NEUTRALNY", "reason": "Za mało świec"}
        r = d.iloc[-1]
        trend_up = r.ema_fast > r.ema_slow
        trend_down = r.ema_fast < r.ema_slow
        long_ok = (
            cfg["allow_long"] and trend_up and r.adx >= tf_cfg["adx_threshold"]
            and tf_cfg["rsi_min"] <= r.rsi <= tf_cfg["rsi_max"] and r.close > r.ema_fast
        )
        short_ok = (
            cfg["allow_short"] and trend_down and r.adx >= tf_cfg["adx_threshold"]
            and tf_cfg["rsi_min"] <= r.rsi <= tf_cfg["rsi_max"] and r.close < r.ema_fast
        )
        sig = "LONG" if long_ok else "SHORT" if short_ok else "NEUTRALNY"
        return {
            "symbol": symbol, "tf": tf, "signal": sig, "price": float(r.close),
            "adx": float(r.adx), "rsi": float(r.rsi), "reason": "OK",
        }
    except Exception as exc:
        return {"symbol": symbol, "tf": tf, "signal": "BŁĄD", "reason": str(exc)[:100]}


def market_order(ex, symbol, side, qty, reduce_only=False):
    qty = float(ex.amount_to_precision(symbol, qty))
    if qty <= 0:
        raise ValueError("Ilość zerowa")
    params = {"reduceOnly": True} if reduce_only else {}
    return ex.create_order(symbol, "market", side, qty, None, params)


def calc_qty(ex, symbol, total_usdt, free_usdt, price, cfg):
    max_lev = int(cfg["max_leverage"])
    auto_risk = max(0.0, total_usdt) * 0.02
    risk = min(float(cfg["risk_usdt"]), auto_risk)
    stop_fraction = max(0.001, (float(cfg["sl_roe"]) / 100.0) / max_lev)
    notional = min(
        risk / stop_fraction,
        float(cfg["max_notional_usdt"]),
        max(0.0, free_usdt) * max_lev * 0.90,
    )
    market = ex.market(symbol)
    contract = float(market.get("contractSize") or 1)
    qty = notional / max(price * contract, 1e-12)
    qty = float(ex.amount_to_precision(symbol, qty))
    return qty, notional


def balance_usdt(ex):
    balance = ex.fetch_balance()
    row = balance.get("USDT") or {}
    return float(row.get("free") or 0), float(row.get("total") or 0)


def is_user_admin():
    email = str(st.session_state.get("user_email", "")).strip().lower()
    username = str(st.session_state.get("username", "")).strip().lower()
    # Configure an admin email using ADMIN_EMAIL; do not rely on a hard-coded personal address.
    admin_email = os.getenv("ADMIN_EMAIL", "").strip().lower()
    try:
        admin_email = st.secrets.get("ADMIN_EMAIL", admin_email).strip().lower()
    except Exception:
        pass
    return bool(admin_email and email == admin_email) or username == "admin"


def is_user_paid():
    return bool(st.session_state.get("stripe_paid", 0)) or is_user_admin()


def create_stripe_checkout_session(user_id, email):
    if stripe is None:
        raise RuntimeError("Brak biblioteki stripe. Zainstaluj stripe.")
    if not STRIPE_SECRET_KEY:
        raise RuntimeError("Brak STRIPE_SECRET_KEY w konfiguracji.")
    if not STRIPE_PRICE_ID or not STRIPE_PRICE_ID.startswith("price_"):
        raise RuntimeError("STRIPE_PRICE_ID musi być ID ceny cyklicznej price_... .")
    stripe.api_key = STRIPE_SECRET_KEY
    params = {
        "mode": "subscription",
        "line_items": [{"price": STRIPE_PRICE_ID, "quantity": 1}],
        "client_reference_id": str(user_id),
        "metadata": {"user_id": str(user_id)},
        "subscription_data": {"metadata": {"user_id": str(user_id)}},
        "success_url": f"{APP_BASE_URL}/?success=true&session_id={{CHECKOUT_SESSION_ID}}",
        "cancel_url": f"{APP_BASE_URL}/?payment=cancelled",
    }
    if email and "@" in email:
        params["customer_email"] = email
    checkout = stripe.checkout.Session.create(**params)
    return checkout.url


def set_subscription_status(user_id, paid, customer_id=None, subscription_id=None):
    with db() as conn:
        conn.execute(
            """UPDATE users SET stripe_paid = ?, stripe_customer_id = COALESCE(?, stripe_customer_id), stripe_subscription_id = COALESCE(?, stripe_subscription_id) WHERE id = ?""",
            (int(bool(paid)), customer_id, subscription_id, int(user_id)),
        )
    if st.session_state.get("user_id") == int(user_id):
        st.session_state["stripe_paid"] = int(bool(paid))


def verify_checkout_return():
    if st.query_params.get("success") != "true":
        return
    user_id = st.session_state.get("user_id")
    session_id = st.query_params.get("session_id")
    if not (st.session_state.get("logged_in") and user_id and session_id):
        st.warning("Zaloguj się na konto, z którego rozpoczęto płatność, aby sprawdzić jej status.")
        return
    if stripe is None or not STRIPE_SECRET_KEY:
        st.error("Nie można zweryfikować płatności: brak konfiguracji Stripe.")
        return
    try:
        stripe.api_key = STRIPE_SECRET_KEY
        checkout = stripe.checkout.Session.retrieve(session_id)
        metadata = checkout.get("metadata") or {}
        if (
            str(checkout.get("client_reference_id") or "") != str(user_id)
            or str(metadata.get("user_id") or "") != str(user_id)
        ):
            st.error("Ta sesja płatności nie należy do zalogowanego użytkownika.")
            return
        subscription_id = checkout.get("subscription")
        subscription = stripe.Subscription.retrieve(subscription_id) if subscription_id else None
        is_paid = (
            checkout.get("mode") == "subscription"
            and checkout.get("status") == "complete"
            and checkout.get("payment_status") in ("paid", "no_payment_required")
            and subscription is not None
            and subscription.get("status") == "active"
        )
        if is_paid:
            customer = checkout.get("customer")
            set_subscription_status(user_id, True, customer, subscription_id)
            st.success("Płatność zweryfikowana. Subskrypcja jest aktywna.")
        else:
            st.warning("Stripe nie potwierdził aktywnej subskrypcji. Dostęp pozostaje zablokowany.")
    except Exception:
        logging.exception("Stripe checkout verification failed")
        st.error("Nie udało się zweryfikować płatności. Dostęp nie został przyznany.")


def handle_stripe_webhook():
    # Streamlit query params do not receive POST bodies. Webhook needs a separate
    # endpoint/service that reads the raw request body and verifies Stripe-Signature.
    # Do not pretend a browser redirect is a webhook.
    return


if "authenticated" not in st.session_state:
    st.session_state["authenticated"] = False
    st.session_state["username"] = ""
    st.session_state["user_id"] = None
    st.session_state["stripe_paid"] = 0
    st.session_state["user_email"] = ""
    st.session_state["logged_in"] = False

verify_checkout_return()

if not st.session_state["authenticated"]:
    st.markdown(
        '<div class="brand-retro">Bitget-SaaS</div><div class="subbrand-retro">AUTONOMICZNY SYSTEM TRANSAKCYJNY</div>',
        unsafe_allow_html=True,
    )
    tab_login, tab_reg = st.tabs(["Zaloguj się", "Załóż konto i subskrypcję"])
    with tab_login:
        st.subheader("Logowanie do systemu")
        with st.form("login_form"):
            l_user = st.text_input("Nazwa użytkownika / E-mail")
            l_pass = st.text_input("Hasło", type="password")
            submit_login = st.form_submit_button("ZALOGUJ SIĘ", use_container_width=True)
        if submit_login:
            with db() as conn:
                row = conn.execute(
                    "SELECT id, password, stripe_paid, email, username FROM users WHERE username=? OR email=?",
                    (l_user.strip(), l_user.strip()),
                ).fetchone()
            if row and row[1] == l_pass:
                st.session_state.update({
                    "authenticated": True, "logged_in": True, "user_id": row[0],
                    "stripe_paid": row[2], "user_email": row[3] or "",
                    "username": row[4],
                })
                st.success("Zalogowano pomyślnie.")
                st.rerun()
            else:
                st.error("Nieprawidłowy login lub hasło.")
    with tab_reg:
        st.subheader("Rejestracja użytkownika i subskrypcja")
        with st.form("reg_form"):
            r_user = st.text_input("Nazwa użytkownika")
            r_email = st.text_input("Adres e-mail")
            r_pass = st.text_input("Hasło", type="password")
            r_sub = st.selectbox("Wybierz subskrypcję", ["Pro Trader (49 PLN / miesiąc)", "VIP SaaS (Roczny)"])
            submit_reg = st.form_submit_button("ZAREJESTRUJ SIĘ", use_container_width=True)
        if submit_reg:
            if not r_user.strip() or not r_pass.strip() or not r_email.strip():
                st.error("Uzupełnij login, e-mail i hasło.")
            elif len(r_pass) < 10:
                st.error("Hasło musi mieć co najmniej 10 znaków.")
            else:
                try:
                    with db() as conn:
                        conn.execute(
                            "INSERT INTO users(username,password,subscription,stripe_paid,email) VALUES(?,?,?,0,?)",
                            (r_user.strip(), r_pass, r_sub, r_email.strip().lower()),
                        )
                    st.success("Konto utworzone. Zaloguj się, a następnie opłać subskrypcję.")
                except sqlite3.IntegrityError:
                    st.error("Ta nazwa użytkownika jest już zajęta.")
    st.stop()

cfg = load_cfg()
creds = load_creds()
ex_id, key, secret, password = creds

with st.sidebar:
    st.markdown(
        f'<div class="brand"><span>⚡</span> Bitget-SaaS</div><div class="subbrand">Witaj, {st.session_state["username"]}</div>',
        unsafe_allow_html=True,
    )
    all_nav_options = [
        "Automatyczny Skaner i Auto-Handel",
        "Panel Sesji i Kapitału",
        "Ustawienia Strategii",
        "Połączenie API",
        "Dziennik",
        "Regulamin & Instrukcja Obsługi",
    ]
    if is_user_admin():
        all_nav_options.append("Panel Administratora (Subskrybenci)")
    nav_options = all_nav_options if is_user_paid() else [
        "Subskrypcja", "Regulamin & Instrukcja Obsługi"
    ]
    page = st.radio("NAWIGACJA", nav_options)
    st.sidebar.markdown("---")
    st.sidebar.markdown("### Status Subskrypcji")
    if is_user_admin():
        st.sidebar.success("Administrator (pełny dostęp)")
    elif is_user_paid():
        st.sidebar.success("Subskrypcja aktywna")
    else:
        st.sidebar.warning("Subskrypcja nieopłacona")
        try:
            checkout_url = create_stripe_checkout_session(
                st.session_state["user_id"], st.session_state.get("user_email", "")
            )
            st.sidebar.link_button("OPŁAĆ SUBSKRYPCJĘ", checkout_url, use_container_width=True)
        except Exception as exc:
            st.sidebar.error(f"Płatność niedostępna: {exc}")
    st.divider()
    if st.button("Wyloguj", use_container_width=True):
        for k in ["authenticated", "logged_in", "username", "user_id", "stripe_paid", "user_email"]:
            st.session_state[k] = False if k in ("authenticated", "logged_in") else "" if k in ("username", "user_email") else None if k == "user_id" else 0
        st.rerun()
    if st.button("Wyczyść cache danych", use_container_width=True):
        get_candles.clear()
        st.success("Cache danych wyczyszczony.")

# Re-read access from the database on every app run. Browser redirect alone never grants access.
if not is_user_admin():
    with db() as conn:
        access_row = conn.execute(
            "SELECT stripe_paid FROM users WHERE id = ?", (st.session_state.get("user_id"),)
        ).fetchone()
    paid_in_db = bool(access_row and access_row[0])
    st.session_state["stripe_paid"] = int(paid_in_db)
    if not paid_in_db and page != "Regulamin & Instrukcja Obsługi":
        st.subheader("Aktywuj subskrypcję")
        st.warning("Dostęp do funkcji handlowych wymaga potwierdzonej subskrypcji.")
        try:
            url = create_stripe_checkout_session(st.session_state["user_id"], st.session_state.get("user_email", ""))
            st.link_button("Przejdź do płatności", url, use_container_width=True)
        except Exception as exc:
            st.error(f"Nie można uruchomić płatności: {exc}")
        st.stop()

st.markdown(
    '<div class="brand"><span>Bitget</span>-SaaS Futures</div><div class="subbrand">AUTONOMICZNY SYSTEM TRANSAKCYJNY</div>',
    unsafe_allow_html=True,
)

if page == "Subskrypcja":
    st.subheader("Subskrypcja")
    st.write("Opłać subskrypcję, aby odblokować funkcje aplikacji.")
    try:
        url = create_stripe_checkout_session(st.session_state["user_id"], st.session_state.get("user_email", ""))
        st.link_button("Przejdź do płatności", url, use_container_width=True)
    except Exception as exc:
        st.error(f"Konfiguracja płatności wymaga poprawy: {exc}")

elif page == "Automatyczny Skaner i Auto-Handel":
    st.subheader("Automatyczny Skaner Rynku i Cykliczny Auto-Handel")
    st.write("Skanowanie odbywa się podczas działania aplikacji; Streamlit nie jest usługą działającą w tle po zamknięciu sesji.")
    with st.form("control_form"):
        cfg["auto_trade"] = st.checkbox("Włącz automatyczny handel", value=bool(cfg["auto_trade"]))
        cfg["paper_mode"] = st.checkbox("Tryb symulacji PAPER (bez zleceń na żywo)", value=bool(cfg["paper_mode"]))
        cfg["auto_refresh"] = st.checkbox("Włącz cykliczne skanowanie", value=bool(cfg.get("auto_refresh", True)))
        cfg["refresh_seconds"] = st.slider("Odstęp między skanami (sekundy)", 10, 300, int(cfg.get("refresh_seconds", 30)))
        submit_ctrl = st.form_submit_button("ZAPISZ TRYB PRACY", use_container_width=True)
    if submit_ctrl:
        save_cfg(cfg)
        st.success("Zapisano ustawienia.")
        st.rerun()
    st.markdown("---")
    try:
        ex = exchange_client(ex_id, key, secret, password, cfg["market_type"])
        markets = ex.load_markets()
        target_symbols = [
            s for s, m in markets.items()
            if m.get("quote") == "USDT" and m.get("active") and m.get("linear")
        ][:int(cfg.get("scan_limit_count", 30))]
        target_tfs = cfg.get("timeframes", ["4h", "1d"])
        st.info(f"Skanowanie {len(target_symbols)} par na interwałach: {', '.join(target_tfs)}")
        free, total = balance_usdt(ex) if not cfg["paper_mode"] else (1000.0, 1000.0)
        results = []
        for symbol in target_symbols:
            for tf in target_tfs:
                res = signal_for_symbol(cfg, symbol, tf)
                results.append(res)
                sig = res["signal"]
                if sig in ("LONG", "SHORT"):
                    event("INFO", f"Skaner: sygnał {sig} {symbol} [{tf}]")
                    if cfg["auto_trade"]:
                        if cfg["paper_mode"]:
                            event("TRADE", f"[PAPER] Sygnał {sig} {symbol} [{tf}] — zlecenie nie zostało wysłane")
                        elif res.get("price") and res.get("reason") == "OK":
                            qty, notional = calc_qty(ex, symbol, total, free, res["price"], cfg)
                            if qty > 0 and notional > 0:
                                try:
                                    ex.set_leverage(int(cfg["max_leverage"]), symbol)
                                except Exception:
                                    logging.exception("Could not set leverage")
                                side = "buy" if sig == "LONG" else "sell"
                                order = market_order(ex, symbol, side, qty)
                                event("TRADE", f"OTWARTO {sig} {symbol} [{tf}] qty={qty} id={order.get('id')}")
        st.dataframe(pd.DataFrame(results), use_container_width=True, hide_index=True)
    except Exception as exc:
        st.error(f"Błąd skanowania giełdy: {exc}")
    if cfg.get("auto_refresh"):
        sec = int(cfg.get("refresh_seconds", 30))
        st.caption(f"Odświeżenie za {sec} sekund.")
        time.sleep(sec)
        st.rerun()

elif page == "Ustawienia Strategii":
    st.subheader("Ustawienia strategii i ryzyka")
    selected_tf = st.selectbox("Interwał do edycji", TF_OPTIONS, index=TF_OPTIONS.index("1d"))
    base = cfg.get("tf_settings", {}).get(selected_tf, DEFAULTS["tf_settings"]["1d"])
    with st.form("cfgform"):
        c1, c2 = st.columns(2)
        with c1:
            cfg["exchange"] = st.selectbox("Giełda", ["bitget", "binanceusdm", "bybit", "okx"], index=["bitget", "binanceusdm", "bybit", "okx"].index(cfg["exchange"]) if cfg["exchange"] in ["bitget", "binanceusdm", "bybit", "okx"] else 0)
            cfg["market_type"] = st.selectbox("Rynek", ["swap", "future"], index=0 if cfg["market_type"] == "swap" else 1)
            cfg["scan_limit_count"] = st.slider("Limit skanowanych par", 5, 50, int(cfg.get("scan_limit_count", 30)))
            cfg["timeframes"] = st.multiselect("Interwały skanowania", TF_OPTIONS, default=[x for x in cfg.get("timeframes", ["4h", "1d"]) if x in TF_OPTIONS] or ["4h", "1d"])
            cfg["indicator_multiplier"] = st.slider("Mnożnik wskaźników (%)", 10, 100, int(cfg.get("indicator_multiplier", 60)))
        with c2:
            cfg["risk_usdt"] = st.number_input("Maks. ryzyko (USDT)", 1.0, 10000.0, float(cfg["risk_usdt"]))
            cfg["max_positions"] = st.number_input("Maks. otwarte pozycje", 1, 20, int(cfg["max_positions"]))
            cfg["max_leverage"] = st.number_input("Maksymalna dźwignia", 1, 50, int(cfg["max_leverage"]))
            cfg["sl_roe"] = st.number_input("Stop-loss ROE (%)", 1.0, 95.0, float(cfg["sl_roe"]))
            cfg["tp_roe"] = st.number_input("Take-profit ROE (%)", 1.0, 500.0, float(cfg["tp_roe"]))
            cfg["allow_long"] = st.checkbox("Pozwól na LONG", bool(cfg["allow_long"]))
            cfg["allow_short"] = st.checkbox("Pozwól na SHORT", bool(cfg["allow_short"]))
        st.markdown(f"### Parametry dla {selected_tf}")
        a, b, c, d, e = st.columns(5)
        with a: fast = st.number_input("EMA szybka", 2, 100, int(base.get("ema_fast", 9)))
        with b: slow = st.number_input("EMA wolna", 3, 300, int(base.get("ema_slow", 21)))
        with c: adx = st.number_input("Min. ADX", 0.0, 100.0, float(base.get("adx_threshold", 25)))
        with d: rmin = st.number_input("RSI min", 0.0, 100.0, float(base.get("rsi_min", 25)))
        with e: rmax = st.number_input("RSI max", 0.0, 100.0, float(base.get("rsi_max", 75)))
        saved = st.form_submit_button("ZAPISZ USTAWIENIA", use_container_width=True)
    if saved:
        if fast >= slow:
            st.error("EMA szybka powinna być mniejsza od EMA wolnej.")
        elif rmin >= rmax:
            st.error("RSI min musi być mniejsze od RSI max.")
        else:
            cfg["tf_settings"][selected_tf] = {"ema_fast": fast, "ema_slow": slow, "adx_threshold": adx, "rsi_min": rmin, "rsi_max": rmax}
            save_cfg(cfg)
            st.success("Zapisano ustawienia.")
            st.rerun()

elif page == "Połączenie API":
    st.subheader("Połączenie giełdowe")
    with st.form("credentials"):
        ex_choice = st.selectbox("Giełda", ["bitget", "binanceusdm", "bybit", "okx"], index=["bitget", "binanceusdm", "bybit", "okx"].index(ex_id) if ex_id in ["bitget", "binanceusdm", "bybit", "okx"] else 0)
        k = st.text_input("API Key", value=key, type="password")
        sec = st.text_input("API Secret", value=secret, type="password")
        pw = st.text_input("Passphrase (Bitget/OKX)", value=password, type="password")
        save = st.form_submit_button("ZAPISZ DANE API")
    if save:
        save_creds(ex_choice, k.strip(), sec.strip(), pw.strip())
        exchange_client.clear()
        st.success("Dane zapisane.")
        st.rerun()
    if st.button("Testuj API / pobierz saldo"):
        try:
            client = exchange_client(ex_id, key, secret, password, cfg["market_type"])
            free, total = balance_usdt(client)
            st.success("Połączenie działa")
            x, y = st.columns(2)
            x.metric("USDT dostępne", f"{free:.2f}")
            y.metric("USDT łącznie", f"{total:.2f}")
        except Exception as exc:
            st.error(f"Błąd API: {exc}")

elif page == "Dziennik":
    st.subheader("Zdarzenia i zlecenia bota")
    with db() as conn:
        rows = conn.execute("SELECT ts,level,message FROM events ORDER BY id DESC LIMIT 200").fetchall()
    if rows:
        st.dataframe(pd.DataFrame(rows, columns=["UTC", "Poziom", "Wiadomość"]), use_container_width=True, hide_index=True)
    else:
        st.info("Brak zdarzeń.")

elif page == "Regulamin & Instrukcja Obsługi":
    st.subheader("Regulamin i instrukcja obsługi")
    tab_guide, tab_terms = st.tabs(["📖 Instrukcja", "📜 Regulamin"])
    with tab_guide:
        st.markdown(""" ### Jak skonfigurować aplikację? 1. Załóż konto i zaloguj się. 2. Opłać subskrypcję przez Stripe. 3. Utwórz klucz API giełdy z minimalnymi uprawnieniami wymaganymi do handlu. **Nie włączaj wypłat.** 4. Najpierw testuj strategię w trybie PAPER. 5. LIVE trading może powodować utratę środków. Sprawdź działanie i limity przed aktywacją. """)
    with tab_terms:
        st.markdown(""" ### Regulamin — skrót Aplikacja jest narzędziem programowym do odczytu danych i automatyzacji zleceń. Nie stanowi porady inwestycyjnej. Handel instrumentami pochodnymi z dźwignią wiąże się z wysokim ryzykiem, w tym utratą kapitału. Użytkownik odpowiada za konfigurację kluczy API, ryzyko i zgodność z regulaminem giełdy. Warunki subskrypcji i zwrotów należy opublikować przed rozpoczęciem sprzedaży. """)

elif page == "Panel Administratora (Subskrybenci)":
    if not is_user_admin():
        st.error("Brak uprawnień administratora.")
        st.stop()
    st.subheader("Panel zarządzania użytkownikami i subskrypcjami")
    with db() as conn:
        users_rows = conn.execute("SELECT id,username,email,subscription,stripe_paid FROM users ORDER BY id").fetchall()
    if users_rows:
        df = pd.DataFrame(users_rows, columns=["ID", "Nazwa użytkownika", "E-mail", "Pakiet", "Opłacone"])
        st.dataframe(df, use_container_width=True, hide_index=True)
        with st.form("admin_manage_form"):
            selected_id = st.selectbox("Wybierz użytkownika", df["ID"].tolist())
            action = st.selectbox("Akcja", ["Włącz subskrypcję", "Odbierz subskrypcję", "Usuń użytkownika"])
            confirm = st.checkbox("Potwierdzam tę operację")
            go = st.form_submit_button("WYKONAJ AKCJĘ")
        if go:
            if not confirm:
                st.error("Zaznacz potwierdzenie.")
            else:
                with db() as conn:
                    if action == "Włącz subskrypcję":
                        conn.execute("UPDATE users SET stripe_paid=1 WHERE id=?", (selected_id,))
                    elif action == "Odbierz subskrypcję":
                        conn.execute("UPDATE users SET stripe_paid=0 WHERE id=?", (selected_id,))
                    else:
                        conn.execute("DELETE FROM users WHERE id=?", (selected_id,))
                st.success("Wykonano operację.")
                st.rerun()
    else:
        st.info("Brak użytkowników.")

elif page == "Panel Sesji i Kapitału":
    st.subheader("Panel sesji i analiza kapitału")
    total_bal, free_bal, active_slots, session_pnl, used_margin = 1000.0, 1000.0, 0, 0.0, 0.0
    try:
        if key and secret:
            client = exchange_client(ex_id, key, secret, password, cfg["market_type"])
            free_bal, total_bal = balance_usdt(client)
            positions = client.fetch_positions()
            active_pos = [p for p in (positions or []) if abs(float(p.get("contracts") or 0)) > 0]
            active_slots = len(active_pos)
            session_pnl = sum(float(p.get("unrealizedPnl") or 0) for p in active_pos)
            used_margin = sum(float(p.get("initialMargin") or p.get("margin") or 0) for p in active_pos)
    except Exception as exc:
        st.warning(f"Nie udało się pobrać salda: {exc}")
    max_slots = int(cfg["max_positions"])
    free_slots = max(0, max_slots - active_slots)
    cols = st.columns(4)
    cols[0].metric("Saldo całkowite", f"{total_bal:.2f} USDT", help=f"Dostępne: {free_bal:.2f} USDT")
    cols[1].metric("Sloty pozycji", f"{active_slots}/{max_slots}", help=f"Wolne sloty: {free_slots}")
    cols[2].metric("Niezrealizowany PnL", f"{session_pnl:+.2f} USDT")
    cols[3].metric("Autopilot", "WŁĄCZONY" if cfg["auto_trade"] else "WYŁĄCZONY", help="Tryb: PAPER" if cfg["paper_mode"] else "Tryb: LIVE")
    st.divider()
    st.subheader("Aktywne pozycje")
    try:
        if key and secret:
            client = exchange_client(ex_id, key, secret, password, cfg["market_type"])
            positions = client.fetch_positions()
            active_pos = [p for p in (positions or []) if abs(float(p.get("contracts") or 0)) > 0]
            if active_pos:
                st.dataframe(pd.DataFrame([{
                    "Symbol": p.get("symbol"), "Strona": p.get("side"),
                    "Kontrakty": p.get("contracts"), "Wejście": p.get("entryPrice"),
                    "PnL (USDT)": p.get("unrealizedPnl"),
                } for p in active_pos]), use_container_width=True, hide_index=True)
            else:
                st.info("Brak otwartych pozycji.")
        else:
            st.info("Skonfiguruj API, aby wyświetlić pozycje.")
    except Exception as exc:
        st.warning(f"Nie udało się pobrać pozycji: {exc}")
    st.divider()
    st.subheader("Awaryjne zamknięcie pozycji")
    if st.button("ZAMKNIJ WSZYSTKIE POZYCJE RYNKOWO", type="secondary"):
        try:
            if not key or not secret:
                raise RuntimeError("Brak kluczy API")
            client = exchange_client(ex_id, key, secret, password, cfg["market_type"])
            positions = client.fetch_positions()
            outcomes = []
            for p in positions or []:
                qty = abs(float(p.get("contracts") or 0))
                symbol = p.get("symbol")
                if qty <= 0 or not symbol:
                    continue
                close_side = "sell" if str(p.get("side") or "").lower() in ("long", "buy") else "buy"
                try:
                    order = market_order(client, symbol, close_side, qty, True)
                    outcomes.append(f"{symbol}: zamknięto {qty} (order {order.get('id')})")
                except Exception as exc:
                    outcomes.append(f"{symbol}: BŁĄD {exc}")
            for line in outcomes:
                event("KILL", line)
            st.write("\n".join(outcomes) if outcomes else "Brak otwartych pozycji.")
        except Exception as exc:
            st.error(f"Kill switch nie powiódł się: {exc}")

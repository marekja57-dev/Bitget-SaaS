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

st.set_page_config(page_title="Bitget-SaaS Futures", page_icon="", layout="wide")

APP_DIR = Path(__file__).resolve().parent
DB_PATH = Path(os.getenv("BITGET_SAAS_DB", str(APP_DIR / "bitget_saas.db")))
LOG_PATH = APP_DIR / "trading.log"

logging.basicConfig(filename=str(LOG_PATH), level=logging.INFO,
                    format="%(asctime)s %(levelname)s %(message)s")

STRIPE_CHECKOUT_FALLBACK = "https://buy.stripe.com/8x2dRa4CbdaXfSAf6V3oA03"
ADMIN_EMAILS = {"marekja57@wp.pl", "admin@bot-bitget.pl"}
TF_OPTIONS = ["1m", "3m", "5m", "15m", "30m", "1h", "2h", "4h", "1d"]
MIN_ORDER_NOTIONAL_USDT = 10.0
MIN_MARGIN_USDT = 10.0

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
    "exchange": "bitget", "market_type": "swap", "candle_limit": 150,
    "refresh_seconds": 30, "risk_usdt": 10.0, "max_positions": 3,
    "max_leverage": 10, "sl_roe": 20.0, "tp_roe": 40.0, "enable_roe": True,
    "timeframes": ["4h", "1d"], "tf_settings": DEFAULT_TF_SETTINGS,
    "auto_refresh": True, "auto_trade": False, "paper_mode": True,
    "max_notional_usdt": 200.0, "cooldown_seconds": 300,
    "allow_short": True, "allow_long": True, "scan_limit_count": 10,
    "indicator_multiplier": 100,
}

st.markdown(""" <style> .stApp {background: radial-gradient(ellipse at 40% -20%, #103e78 0%, #071a36 42%, #050e20 100%); color:#eaf3ff} [data-testid="stHeader"] {background:rgba(3,12,29,.96)} [data-testid="stAppViewContainer"] .main .block-container {padding-top:2rem;max-width:1600px} [data-testid="stSidebar"] {background:linear-gradient(180deg,#06152d,#081f42)} .brand {font-weight:900;font-size:clamp(24px,2.5vw,34px);color:#eaf5ff;margin:.5rem 0} .brand span {color:#28a8ff} .subbrand {color:#7da9d8;font-size:11px;letter-spacing:1.5px;margin-bottom:1.5rem} div.stButton>button {border:1px solid #278be8;background:linear-gradient(180deg,#1689ff,#0759c8);color:white;font-weight:700} :root { --gold:#d8ad52; --gold-soft:#f3d88a; } .metric-card {border:1px solid var(--gold);border-radius:14px;padding:18px 20px;height:150px;box-sizing:border-box;display:flex;flex-direction:column;justify-content:center;background:linear-gradient(145deg,rgba(27,43,68,.96),rgba(6,18,37,.98));box-shadow:0 0 0 1px rgba(216,173,82,.12),0 8px 24px rgba(0,0,0,.24);overflow:hidden} .metric-card .metric-label {color:#b9c9df;font-size:12px;font-weight:700;letter-spacing:1px;text-transform:uppercase;margin-bottom:10px} .metric-card .metric-value {color:#fff2c7;font-size:clamp(20px,1.8vw,29px);font-weight:850;line-height:1.2;overflow-wrap:anywhere} .metric-card .metric-note {color:#a9bdd7;font-size:12px;margin-top:8px} .metric-card.green .metric-value {color:#70e0ae} .metric-card.blue .metric-value {color:#83c7ff} .metric-card.red .metric-value {color:#ff9696} .metric-card.gold .metric-value {color:#fff2c7} </style> """, unsafe_allow_html=True)

# -------------------- Baza danych --------------------

def db():
    con = sqlite3.connect(DB_PATH, timeout=20)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA busy_timeout=20000")
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("CREATE TABLE IF NOT EXISTS settings (k TEXT PRIMARY KEY, v TEXT NOT NULL)")
    con.execute("""CREATE TABLE IF NOT EXISTS user_credentials ( user_id INTEGER PRIMARY KEY, exchange TEXT, api_key TEXT, secret TEXT, password TEXT)""")
    con.execute("""CREATE TABLE IF NOT EXISTS events ( id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT, level TEXT, message TEXT)""")
    con.execute("""CREATE TABLE IF NOT EXISTS users ( id INTEGER PRIMARY KEY AUTOINCREMENT, username TEXT UNIQUE NOT NULL, password TEXT NOT NULL, subscription TEXT, stripe_paid INTEGER NOT NULL DEFAULT 0, email TEXT UNIQUE)""")
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
                saved = json.loads(row["v"])
                cfg.update(saved)
        merged = json.loads(json.dumps(DEFAULT_TF_SETTINGS))
        for tf, values in (cfg.get("tf_settings") or {}).items():
            if tf in merged and isinstance(values, dict):
                merged[tf].update(values)
        cfg["tf_settings"] = merged
    except Exception:
        logging.exception("Nie udało się wczytać ustawień")
    return cfg

def save_cfg(cfg):
    with db() as con:
        con.execute("""INSERT INTO settings(k,v) VALUES('main',?) ON CONFLICT(k) DO UPDATE SET v=excluded.v""",
                    (json.dumps(cfg, ensure_ascii=False),))
        con.commit()

def event(level, message):
    message = str(message)[:1500]
    logging.log(getattr(logging, str(level).upper(), logging.INFO), message)
    with db() as con:
        con.execute("INSERT INTO events(ts,level,message) VALUES(?,?,?)",
                    (datetime.now(timezone.utc).isoformat(), str(level), message))
        con.commit()

def load_creds(user_id):
    if not user_id:
        return ("bitget", "", "", "")
    with db() as con:
        row = con.execute("SELECT exchange,api_key,secret,password FROM user_credentials WHERE user_id=?", (user_id,)).fetchone()
        return tuple(row) if row else ("bitget", "", "", "")

def save_creds(user_id, exchange, api_key, secret, passphrase):
    if not user_id:
        return
    with db() as con:
        existing = con.execute("SELECT user_id FROM user_credentials WHERE user_id=?", (user_id,)).fetchone()
        if existing:
            con.execute("UPDATE user_credentials SET exchange=?, api_key=?, secret=?, password=? WHERE user_id=?",
                        (exchange, api_key, secret, passphrase, user_id))
        else:
            con.execute("INSERT INTO user_credentials(user_id, exchange, api_key, secret, password) VALUES(?,?,?,?,?)",
                        (user_id, exchange, api_key, secret, passphrase))
        con.commit()

def create_stripe_checkout_url():
    url = STRIPE_CHECKOUT_FALLBACK.strip()
    if not url.startswith("https://buy.stripe.com/"):
        raise ValueError("Ustaw prawidłowy aktywny link płatności Stripe.")
    return url

# -------------------- Giełda i dane rynkowe --------------------

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
    tr = pd.concat([
        (d["high"] - d["low"]).abs(),
        (d["high"] - d["close"].shift()).abs(),
        (d["low"] - d["close"].shift()).abs()
    ], axis=1).max(axis=1)
    up, down = d["high"].diff(), -d["low"].diff()
    plus = pd.Series(np.where((up > down) & (up > 0), up, 0), index=d.index)
    minus = pd.Series(np.where((down > up) & (down > 0), down, 0), index=d.index)
    atr = tr.ewm(alpha=1/14, adjust=False).mean().replace(0, np.nan)
    pdi = 100 * plus.ewm(alpha=1/14, adjust=False).mean() / atr
    mdi = 100 * minus.ewm(alpha=1/14, adjust=False).mean() / atr
    dx = 100 * (pdi - mdi).abs() / (pdi + mdi).replace(0, np.nan)
    d["adx"] = dx.ewm(alpha=1/14, adjust=False).mean()
    return d

def effective_tf_cfg(cfg, tf):
    base = cfg.get("tf_settings", {}).get(tf, DEFAULT_TF_SETTINGS.get(tf, DEFAULT_TF_SETTINGS["1h"]))
    mult = float(cfg.get("indicator_multiplier", 100)) / 100.0
    fast = max(2, int(round(float(base["ema_fast"]) * mult)))
    slow = max(fast + 1, int(round(float(base["ema_slow"]) * mult)))
    return {
        "ema_fast": fast, "ema_slow": slow,
        "adx_threshold": max(2.0, min(90.0, float(base["adx_threshold"]) * mult)),
        "rsi_min": max(2.0, min(45.0, float(base["rsi_min"]))),
        "rsi_max": max(55.0, min(98.0, float(base["rsi_max"]))),
    }

def signal_for_symbol(cfg, symbol, timeframe):
    try:
        t = effective_tf_cfg(cfg, timeframe)
        raw = get_candles(cfg["exchange"], cfg["market_type"], symbol, timeframe, cfg["candle_limit"])
        d = indicators(raw.copy(), t["ema_fast"], t["ema_slow"])
        if len(d) < max(35, t["ema_slow"] + 5):
            return {"symbol": symbol, "tf": timeframe, "signal": "NEUTRALNY", "price": None,
                    "adx": None, "rsi": None, "reason": "Za mało świec"}
        r = d.iloc[-1]
        vals_ok = all(pd.notna(r[x]) and np.isfinite(float(r[x])) for x in ["close", "ema_fast", "ema_slow", "adx", "rsi"])
        if not vals_ok:
            return {"symbol": symbol, "tf": timeframe, "signal": "NEUTRALNY", "price": float(r["close"]),
                    "adx": None, "rsi": None, "reason": "Brak danych wskaźników"}
        trend = r["ema_fast"] > r["ema_slow"]
        filters = r["adx"] >= t["adx_threshold"] and t["rsi_min"] <= r["rsi"] <= t["rsi_max"]
        long_ok = bool(cfg["allow_long"] and trend and filters and r["close"] > r["ema_fast"])
        short_ok = bool(cfg["allow_short"] and not trend and filters and r["close"] < r["ema_fast"])
        signal = "LONG" if long_ok else "SHORT" if short_ok else "NEUTRALNY"
        return {"symbol": symbol, "tf": timeframe, "signal": signal, "price": float(r["close"]),
                "adx": float(r["adx"]), "rsi": float(r["rsi"]), "reason": "OK"}
    except Exception as exc:
        return {"symbol": symbol, "tf": timeframe, "signal": "BŁĄD", "price": None,
                "adx": None, "rsi": None, "reason": str(exc)[:180]}
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
    info = balance.get("info")
    if isinstance(info, dict):
        candidates = []
        data = info.get("data")
        if isinstance(data, list):
            candidates.extend(x for x in data if isinstance(x, dict))
        elif isinstance(data, dict):
            candidates.append(data)
        for key in ("assetList", "assets", "list", "accounts"):
            value = data.get(key)
            if isinstance(value, list):
                candidates.extend(x for x in value if isinstance(x, dict))
            elif isinstance(value, dict):
                candidates.append(value)
        for key in ("assetList", "assets", "list", "accounts"):
            value = info.get(key)
            if isinstance(value, list):
                candidates.extend(x for x in value if isinstance(x, dict))
            elif isinstance(value, dict):
                candidates.append(value)
        for item in candidates:
            coin = str(item.get("marginCoin", item.get("coin", item.get("currency", "")))).upper()
            if coin and coin != "USDT":
                continue
            if free is None:
                free = number(item.get("available"), item.get("availableBalance"), item.get("availableEquity"), item.get("maxAvailable"))
            if total is None:
                total = number(item.get("accountEquity"), item.get("equity"), item.get("totalEquity"), item.get("totalWalletBalance"), item.get("total"))
            if used is None:
                used = number(item.get("locked"), item.get("used"), item.get("frozen"))
            if free is not None and total is not None:
                break
        if free is None:
            free = number(info.get("availableBalance"), info.get("available"), info.get("availableUSDT"), info.get("availableEquity"))
        if total is None:
            total = number(info.get("accountEquity"), info.get("equity"), info.get("totalEquity"), info.get("totalWalletBalance"))
    if free is None:
        free = 0.0
    if total is None:
        total = free + used if used is not None else free
    position_margin = 0.0
    if positions:
        for position in positions:
            margin_value = position.get("initialMargin")
            if margin_value is None:
                margin_value = position.get("margin")
            position_margin += max(0.0, asfloat(margin_value))
    reported_used = max(0.0, float(used or 0.0))
    allocated_margin = max(reported_used, position_margin)
    if total > 0 and free >= total - max(0.01, total * 0.001) and allocated_margin > 0:
        free = max(0.0, float(total) - allocated_margin)
    return max(0.0, float(free)), max(0.0, float(total))

def active_positions(ex):
    positions = ex.fetch_positions() or []
    return [p for p in positions if abs(asfloat(p.get("contracts"))) > 0]

def market_order(ex, symbol, side, qty, reduce_only=False, reference_price=None):
    qty = float(ex.amount_to_precision(symbol, qty))
    if not np.isfinite(qty) or qty <= 0:
        raise ValueError("Ilość zlecenia wynosi zero lub jest nieprawidłowa")
    if not reduce_only:
        price = asfloat(reference_price)
        if price <= 0:
            raise ValueError("Zablokowano otwarcie pozycji: brak prawidłowej ceny do sprawdzenia wartości pozycji.")
        market = ex.market(symbol)
        contract_size = asfloat(market.get("contractSize")) or 1.0
        notional = qty * price * contract_size
        if not np.isfinite(notional) or notional < MIN_ORDER_NOTIONAL_USDT:
            raise ValueError(
                f"Zablokowano zlecenie: wartość po zaokrągleniu ilości wynosi "
                f"{notional:.4f} USDT, a minimum to {MIN_ORDER_NOTIONAL_USDT:.2f} USDT."
            )
    params = {"reduceOnly": True} if reduce_only else {}
    return ex.create_order(symbol, "market", side, qty, None, params)

def calc_qty(ex, symbol, total_usdt, free_usdt, price, cfg):
    price = asfloat(price)
    total_usdt, free_usdt = max(0.0, asfloat(total_usdt)), max(0.0, asfloat(free_usdt))
    leverage = max(1, int(cfg.get("max_leverage", 10)))
    risk_limit = max(0.0, float(cfg.get("risk_usdt", 10.0)))
    max_notional = max(0.0, float(cfg.get("max_notional_usdt", 200.0)))
    sl_roe = float(cfg.get("sl_roe", 20.0))
    if price <= 0 or sl_roe <= 0 or free_usdt <= 0:
        return 0.0, 0.0
    risk_budget = min(risk_limit, total_usdt * 0.05)
    stop_fraction = max(0.001, (sl_roe / 100.0) / leverage)
    risk_based_notional = risk_budget / stop_fraction
    target = min(risk_based_notional, max_notional, free_usdt * leverage * 0.90)
    if target < MIN_ORDER_NOTIONAL_USDT:
        target = MIN_ORDER_NOTIONAL_USDT
    try:
        market = ex.market(symbol)
    except Exception:
        market = {}
    contract_size = asfloat(market.get("contractSize")) or 1.0
    limits = market.get("limits") or {}
    min_amount = asfloat((limits.get("amount") or {}).get("min"))
    raw_qty = target / (price * contract_size)
    try:
        qty = float(ex.amount_to_precision(symbol, raw_qty))
    except Exception:
        qty = round(raw_qty, 4)
    if min_amount > 0 and qty < min_amount:
        qty = min_amount
    if not np.isfinite(qty) or qty <= 0:
        return 0.0, 0.0
    actual_notional = qty * price * contract_size
    if actual_notional < MIN_ORDER_NOTIONAL_USDT:
        return 0.0, 0.0
    return qty, actual_notional

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
            quote_volume = asfloat(ticker.get("quoteVolume"))
            if quote_volume <= 0:
                quote_volume = asfloat(ticker.get("baseVolume")) * asfloat(ticker.get("last"))
            if quote_volume > 0:
                ranked_top.append((symbol, quote_volume))
    ranked_top.sort(key=lambda item: item[1], reverse=True)
    del tickers
    ranked_top = ranked_top[:limit_count]
    st.session_state[cache_key] = {"ts": now, "ranked": ranked_top}
    gc.collect()
    return ranked_top

# -------------------- Logowanie --------------------

for k, default in {"authenticated": False, "logged_in": False, "username": "",
                   "user_id": None, "stripe_paid": 0, "user_email": ""}.items():
    if k not in st.session_state:
        st.session_state[k] = default

def is_user_admin():
    email = str(st.session_state.get("user_email", "")).strip().lower()
    username = str(st.session_state.get("username", "")).strip().lower()
    return email in ADMIN_EMAILS or username == "admin"

def is_user_paid():
    return bool(st.session_state.get("stripe_paid", 0)) or is_user_admin()

if st.query_params.get("success") == "true":
    st.info("Powrót z płatności. Administrator potwierdzi płatność przed aktywacją dostępu.")
    st.query_params.clear()

if not st.session_state["authenticated"]:
    st.markdown('<div class="brand" style="text-align:center">Bitget-SaaS</div><div class="subbrand" style="text-align:center">AUTONOMICZNY SYSTEM TRANSAKCYJNY</div>', unsafe_allow_html=True)
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
                                            stripe_paid=row["stripe_paid"], user_email=(row["email"] or "").lower(), username=row["username"])
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
                elif "@" not in reg_email or "." not in reg_email.rsplit("@", 1)[-1]:
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
    st.markdown(f'<div class="brand"><span></span> Bitget-SaaS</div><div class="subbrand">Witaj, {st.session_state["username"]}</div>', unsafe_allow_html=True)
    pages = ["Automatyczny Skaner i Auto-Handel",
             "Ustawienia Strategii", "Połączenie API", "Dziennik", "Regulamin i Instrukcja"]
    if is_user_admin():
        pages.append("Panel Administratora")
    page = st.radio("NAWIGACJA", pages)
    st.divider()
    if is_user_admin():
        st.success("Administrator - pełny dostęp")
    elif is_user_paid():
        st.success("Subskrypcja aktywna")
    else:
        st.warning("Subskrypcja nieopłacona")
    try:
        st.link_button("OPŁAĆ SUBSKRYPCJĘ (49 PLN)", create_stripe_checkout_url(), use_container_width=True)
    except Exception as exc:
        st.error(f"Błąd linku Stripe: {exc}")
    st.caption("Po płatności administrator potwierdza transakcję.")
    if st.button("Wyloguj", use_container_width=True):
        for key_name, default in [("authenticated", False), ("logged_in", False), ("username", ""),
                                  ("user_id", None), ("stripe_paid", 0), ("user_email", "")]:
            st.session_state[key_name] = default
        st.rerun()
    if st.button("Wyczyść cache danych", use_container_width=True):
        get_candles.clear()
        st.cache_data.clear()
        st.cache_resource.clear()
        st.session_state.clear()
        gc.collect()
        st.success("Cache danych wyczyszczony. Odśwież stronę.")

st.markdown('<div class="brand"><span>Bitget</span>-SaaS Futures</div><div class="subbrand">AUTONOMICZNY SYSTEM TRANSAKCYJNY</div>', unsafe_allow_html=True)

# -------------------- Główny Pulpit Transakcyjny na Żywo --------------------

if page == "Automatyczny Skaner i Auto-Handel":
    st.subheader("Główny Pulpit Transakcyjny - Pełny Podgląd Na Żywo")

    with st.expander("Ustawienia trybu pracy i czyszczenie", expanded=False):
        with st.form("control_form"):
            c_left, c_right = st.columns(2)
            with c_left:
                auto_trade = st.checkbox("Włącz automatyczny handel", value=bool(cfg["auto_trade"]))
                paper_mode = st.checkbox("Tryb PAPER - bez zleceń na giełdzie", value=bool(cfg["paper_mode"]))
            with c_right:
                auto_refresh = st.checkbox("Włącz ciągłe skanowanie na żywo", value=bool(cfg.get("auto_refresh", True)))
                refresh_seconds = st.slider("Odstęp między odświeżeniami (s)", 10, 120, int(cfg.get("refresh_seconds", 30)))
            submit_ctrl = st.form_submit_button("ZAPISZ USTAWIENIA PRACY", use_container_width=True)
            if submit_ctrl:
                cfg.update(auto_trade=auto_trade, paper_mode=paper_mode, auto_refresh=auto_refresh, refresh_seconds=refresh_seconds)
                save_cfg(cfg)
                st.success("Zapisano ustawienia.")
                st.rerun()

    refresh_sec = max(10, int(cfg.get("refresh_seconds", 30)))

    @st.fragment(run_every=refresh_sec if cfg.get("auto_refresh", True) else None)
    def render_full_dashboard():
        st.caption(f"Status: Odświeżanie danych na żywo co {refresh_sec} s.")

        total_balance = free_balance = session_pnl = used_margin = 0.0
        active = []
        connected = bool(api_key_saved and secret_saved)
        api_ok = False
        if connected:
            try:
                client = exchange_client(ex_id, api_key_saved, secret_saved, passphrase_saved, cfg["market_type"])
                active = active_positions(client)
                free_balance, total_balance = balance_usdt(client, active)
                session_pnl = sum(asfloat(p.get("unrealizedPnl")) for p in active)
                used_margin = sum(asfloat(p.get("initialMargin") or p.get("margin")) for p in active)
                api_ok = True
            except Exception as exc:
                st.warning(f"Błąd połączenia z giełdą / pobierania pozycji: {exc}")
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

        m1, m2, m3, m4 = st.columns(4, gap="medium")
        with m1:
            metric_card("Saldo / wolne środki", f"{total_balance:.2f} / {free_balance:.2f} USDT",
                        "Saldo całkowite / dostępne", "gold")
        with m2:
            metric_card("Niezrealizowany PnL", f"{session_pnl:+.2f} USDT",
                        "Łączny PnL otwartych pozycji", "green" if session_pnl >= 0 else "red")
        with m3:
            metric_card("Otwarte pozycje", f"{len(active)} / {max_slots}",
                        f"Margin w użyciu: {used_margin:.2f} USDT", "blue")
        with m4:
            terminal_text = "HANDEL AKTYWNY" if (api_ok and cfg.get("auto_trade")) else "TYLKO SKANER"
            metric_card("Terminal", terminal_text, f"Odświeżanie co {refresh_sec}s", "green" if api_ok else "red")

        st.divider()

        st.markdown("### Aktywne Pozycje na Bitget")
        if active:
            st.dataframe(pd.DataFrame([{
                "Symbol": p.get("symbol"),
                "Strona": str(p.get("side")).upper(),
                "Kontrakty": p.get("contracts"),
                "Cena wejścia": p.get("entryPrice"),
                "PnL (USDT)": p.get("unrealizedPnl"),
                "Margin (USDT)": p.get("initialMargin")
            } for p in active]), use_container_width=True, hide_index=True)
        elif connected and api_ok:
            st.info("Brak otwartych pozycji na giełdzie.")
        else:
            st.warning("Brak połączenia API - podaj klucze w zakładce 'Połączenie API'.")

        st.divider()

        st.markdown("### Wyniki Skanera Rynku i Sygnały")
        if not is_user_paid():
            st.error("Subskrypcja nieaktywna. Skaner działa, ale handel LIVE jest zablokowany.")
        try:
            ex = exchange_client(ex_id, api_key_saved, secret_saved, passphrase_saved, cfg["market_type"])
            scan_limit = int(cfg.get("scan_limit_count", 30))
            ranked = ranked_symbols(ex, scan_limit)
            symbols = [item[0] for item in ranked]
            volume_map = dict(ranked)
            tfs = [tf for tf in cfg.get("timeframes", ["4h", "1d"]) if tf in TF_OPTIONS]

            st.caption(f"Przeskanowano {len(symbols)} par według wolumenu. Interwały: {', '.join(tfs)}")

            results = []
            paper_open_symbols = set()
            for symbol in symbols:
                for tf in tfs:
                    res = signal_for_symbol(cfg, symbol, tf)
                    res["volume_24h_usdt"] = volume_map.get(symbol, 0.0)
                    results.append(res)
                    if res["signal"] not in ("LONG", "SHORT"):
                        continue
                    event("INFO", f"Sygnał {res['signal']} {symbol} [{tf}]")
                    if not cfg["auto_trade"] or not is_user_paid():
                        continue
                    if cfg["paper_mode"]:
                        if symbol in paper_open_symbols or len(paper_open_symbols) >= max_slots:
                            continue
                        paper_open_symbols.add(symbol)
                        event("TRADE", f"[PAPER] {res['signal']} {symbol} [{tf}]")
                        continue
                    if not (api_key_saved and secret_saved and res.get("price")):
                        continue
                    try:
                        positions = active_positions(ex)
                        current_symbols = {str(p.get("symbol")) for p in positions if p.get("symbol")}
                        if len(positions) >= max_slots or symbol in current_symbols:
                            continue
                        free, total = balance_usdt(ex, positions)
                        qty, notional = calc_qty(ex, symbol, total, free, res["price"], cfg)
                        if qty <= 0 or notional < MIN_ORDER_NOTIONAL_USDT:
                            event("WARNING", f"Pominięto {symbol}: depozyt < 10 USDT lub limit ryzyka.")
                            continue
                        leverage_val = int(cfg["max_leverage"])
                        try:
                            ex.set_leverage(leverage_val, symbol)
                        except Exception:
                            pass
                        side = "buy" if res["signal"] == "LONG" else "sell"
                        order = market_order(ex, symbol, side, qty, reference_price=res["price"])
                        event("TRADE", f"Otwarto {res['signal']} {symbol} qty={qty} wartość={notional:.2f} USDT; ID={order.get('id')}")
                    except Exception as trade_exc:
                        event("ERROR", f"Nie otwarto pozycji {symbol}: {trade_exc}")

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
    st.warning("To polecenie wysyła prawdziwe zlecenia rynkowe zamykające pozycje.")
    if st.button("ZAMKNIJ WSZYSTKIE POZYCJE", type="secondary"):
        try:
            connected = bool(api_key_saved and secret_saved)
            if not connected:
                raise RuntimeError("Brak kluczy API.")
            client = exchange_client(ex_id, api_key_saved, secret_saved, passphrase_saved, cfg["market_type"])
            positions = active_positions(client)
            outcomes = []
            for pos in positions:
                qty = abs(asfloat(pos.get("contracts")))
                symbol = pos.get("symbol")
                if qty <= 0 or not symbol:
                    continue
                side = "sell" if str(pos.get("side") or "").lower() in ("long", "buy") else "buy"
                try:
                    order = market_order(client, symbol, side, qty, reduce_only=True)
                    outcomes.append(f"{symbol}: wysłano zamknięcie {qty}; order={order.get('id')}")
                except Exception as exc:
                    outcomes.append(f"{symbol}: BŁĄD: {exc}")
            for line in outcomes:
                event("KILL", line)
            st.write("\n".join(outcomes) if outcomes else "Brak aktywnych pozycji.")
        except Exception as exc:
            st.error(f"Zamknięcie awaryjne nie powiodło się: {exc}")
        finally:
            gc.collect()

# -------------------- Ustawienia strategii --------------------

elif page == "Ustawienia Strategii":
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
            risk = st.number_input("Maks. ryzyko na pozycję (USDT)", 1.0, 10000.0, float(cfg["risk_usdt"]))
            max_notional = st.number_input("Maks. wartość pozycji (USDT)", 10.0, 100000.0, float(cfg["max_notional_usdt"]))
            max_positions = st.number_input("Maks. liczba otwartych pozycji", 1, 20, int(cfg["max_positions"]))
            max_leverage = st.number_input("Maksymalna dźwignia", 1, 50, int(cfg["max_leverage"]))
            sl_roe = st.number_input("Stop-loss ROE (%) - parametr ryzyka", 1.0, 95.0, float(cfg["sl_roe"]))
            tp_roe = st.number_input("Take-profit ROE (%) - parametr", 1.0, 500.0, float(cfg["tp_roe"]))
            allow_long = st.checkbox("Pozwól na LONG", bool(cfg["allow_long"]))
            allow_short = st.checkbox("Pozwól na SHORT", bool(cfg["allow_short"]))
        st.markdown(f"### Parametry bazowe dla {selected_tf}")
        c1, c2, c3, c4, c5 = st.columns(5)
        with c1:
            fast = st.number_input("EMA szybka", 2, 100, int(base["ema_fast"]))
        with c2:
            slow = st.number_input("EMA wolna", 3, 300, int(base["ema_slow"]))
        with c3:
            adx = st.number_input("Minimalny ADX", 0.0, 100.0, float(base["adx_threshold"]))
        with c4:
            rmin = st.number_input("RSI minimum", 0.0, 100.0, float(base["rsi_min"]))
        with c5:
            rmax = st.number_input("RSI maksimum", 0.0, 100.0, float(base["rsi_max"]))
        save = st.form_submit_button("ZAPISZ USTAWIENIA", use_container_width=True)
        if save:
            if fast >= slow:
                st.error("EMA szybka musi być mniejsza od EMA wolnej.")
            elif rmin >= rmax:
                st.error("RSI minimum musi być mniejsze od RSI maksimum.")
            else:
                cfg.update(exchange=exchange_name, market_type=market_type, scan_limit_count=scan_limit,
                           timeframes=timeframes or ["4h", "1d"], indicator_multiplier=multiplier,
                           candle_limit=candle_limit, risk_usdt=risk, max_notional_usdt=max_notional,
                           max_positions=int(max_positions), max_leverage=int(max_leverage),
                           sl_roe=sl_roe, tp_roe=tp_roe, allow_long=allow_long, allow_short=allow_short)
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

elif page == "Połączenie API":
    st.subheader("Połączenie z giełdą")
    with st.form("credentials"):
        exchange_choice = st.selectbox("Giełda", ["bitget", "binanceusdm", "bybit", "okx"],
                                     index=["bitget", "binanceusdm", "bybit", "okx"].index(ex_id) if ex_id in ["bitget", "binanceusdm", "bybit", "okx"] else 0)
        api_key_input = st.text_input("API Key", value=api_key_saved, type="password")
        secret_input = st.text_input("API Secret", value=secret_saved, type="password")
        pass_input = st.text_input("Passphrase (Bitget/OKX)", value=passphrase_saved, type="password")
        save_api = st.form_submit_button("ZAPISZ DANE API")
        if save_api:
            save_creds(current_user_id, exchange_choice, api_key_input.strip(), secret_input.strip(), pass_input.strip())
            exchange_client.clear()
            st.cache_data.clear()
            gc.collect()
            st.success("Dane API zapisane wyłącznie dla Twojego konta.")
            st.rerun()

    if st.button("Testuj API i pobierz saldo"):
        try:
            client = exchange_client(ex_id, api_key_saved, secret_saved, passphrase_saved, cfg["market_type"])
            free, total = balance_usdt(client)
            st.success("Połączenie działa.")
            c1, c2 = st.columns(2, gap="medium")
            with c1:
                st.markdown(f'<div class="metric-card green"><div class="metric-label">Wolne środki</div><div class="metric-value">{free:.4f} USDT</div><div class="metric-note">Dostępne do nowych zleceń</div></div>', unsafe_allow_html=True)
            with c2:
                st.markdown(f'<div class="metric-card"><div class="metric-label">Saldo Futures</div><div class="metric-value">{total:.4f} USDT</div><div class="metric-note">Całkowite saldo raportowane przez giełdę</div></div>', unsafe_allow_html=True)
        except Exception as exc:
            st.error(f"Błąd API: {exc}")
        finally:
            gc.collect()

# -------------------- Dziennik --------------------

elif page == "Dziennik":
    st.subheader("Zdarzenia i zlecenia bota")
    with db() as con:
        rows = con.execute("SELECT ts,level,message FROM events ORDER BY id DESC LIMIT 300").fetchall()
        if rows:
            st.dataframe(pd.DataFrame([tuple(r) for r in rows], columns=["Czas UTC", "Poziom", "Wiadomość"]),
                         use_container_width=True, hide_index=True)
        else:
            st.info("Brak zdarzeń.")

# -------------------- Instrukcja i regulamin --------------------

elif page == "Regulamin i Instrukcja":
    st.subheader("Instrukcja obsługi i regulamin")
    tab_help, tab_terms = st.tabs(["Instrukcja", "Regulamin"])
    with tab_help:
        st.markdown("""1. Utwórz konto i zaloguj się. 2. Administrator potwierdza płatność w panelu Stripe i aktywuje dostęp. 3. Utwórz klucz API giełdy z uprawnieniami odczytu i handlu Futures. Nie włączaj wypłat. 4. Zapisz dane API w zakładce Połączenie API. 5. Ustaw interwały, wskaźniki, limity pozycji i ryzyko. 6. Najpierw testuj w trybie PAPER.""")
    with tab_terms:
        st.markdown("""**Regulamin Bitget-SaaS Futures** 1. Serwis udostępnia narzędzia programowe do analizy rynku i składania zleceń. 2. Użytkownik odpowiada za klucze API, konfigurację ryzyka i decyzje inwestycyjne. 3. Handel futures wiąże się z ryzykiem utraty kapitału. Wyniki nie są gwarantowane. 4. Dostęp płatny kosztuje 49 PLN miesięcznie.""")

# -------------------- Panel administratora --------------------

elif page == "Panel Administratora" and is_user_admin():
    st.subheader("Zarządzanie użytkownikami i subskrypcjami")
    with db() as con:
        rows = con.execute("SELECT id,username,email,subscription,stripe_paid FROM users ORDER BY id").fetchall()
        if rows:
            df = pd.DataFrame([tuple(r) for r in rows], columns=["ID", "Użytkownik", "E-mail", "Pakiet", "Opłacone (0/1)"])
            st.dataframe(df, use_container_width=True, hide_index=True)
            with st.form("admin_manage_form"):
                user_id = st.selectbox("Wybierz użytkownika", df["ID"].tolist())
                action = st.selectbox("Operacja", ["Aktywuj subskrypcję", "Odbierz subskrypcję", "Usuń użytkownika"])
                confirm = st.checkbox("Potwierdzam operację")
                go = st.form_submit_button("WYKONAJ", use_container_width=True)
                if go:
                    if not confirm:
                        st.error("Zaznacz potwierdzenie.")
                    else:
                        with db() as con:
                            if action == "Aktywuj subskrypcję":
                                con.execute("UPDATE users SET stripe_paid=1 WHERE id=?", (user_id,))
                            elif action == "Odbierz subskrypcję":
                                con.execute("UPDATE users SET stripe_paid=0 WHERE id=?", (user_id,))
                            else:
                                con.execute("DELETE FROM users WHERE id=?", (user_id,))
                                con.execute("DELETE FROM user_credentials WHERE user_id=?", (user_id,))
                            con.commit()
                        event("ADMIN", f"{action}; user_id={user_id}")
                        st.success("Operacja wykonana.")
                        st.rerun()
        else:
            st.info("Brak użytkowników.")


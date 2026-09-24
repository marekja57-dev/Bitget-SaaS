from datetime import datetime
import hashlib
import json
import logging
import os
import sqlite3
import time
import ccxt
import numpy as np
import pandas as pd
import streamlit as st
import stripe

st.set_page_config(
    page_title="Multi-Exchange Futures SaaS",
    layout="wide",
)

DB_FILE = "users.db"
STRIPE_CONFIG_FILE = "stripe_config.json"

# =====================================================================
# FUNKCJE POMOCNICZE (ŻELAZNY NADPIS ADMINISTRATORA)
# =====================================================================
ADMIN_EMAILS = ["marekjas57@wp.pl", "marekja57@wp.pl"]

def is_user_admin():
    email = str(st.session_state.get("user_email", "")).strip().lower()
    if email in ADMIN_EMAILS:
        return True
    return bool(st.session_state.get("is_admin", False))

def is_user_paid():
    email = str(st.session_state.get("user_email", "")).strip().lower()
    if email in ADMIN_EMAILS:
        return True
    return bool(st.session_state.get("stripe_paid", False))

# =====================================================================
# WSKAŹNIKI TECHNICZNE Z FILTREM ADX, TRENDU ORAZ OCHRONĄ PRZED SZCZYTAMI/DOŁKAMI
# =====================================================================
def calculate_indicators(df, ema_period=50, adx_period=14):
    df["ema50"] = df["close"].ewm(span=ema_period, adjust=False).mean()
    exp1 = df["close"].ewm(span=12, adjust=False).mean()
    exp2 = df["close"].ewm(span=26, adjust=False).mean()
    df["macd"] = exp1 - exp2
    df["signal"] = df["macd"].ewm(span=9, adjust=False).mean()
    df["macd_hist"] = df["macd"] - df["signal"]

    # ADX (Average Directional Index) do eliminacji boczniaków
    df["tr0"] = abs(df["high"] - df["low"])
    df["tr1"] = abs(df["high"] - df["close"].shift(1))
    df["tr2"] = abs(df["low"] - df["close"].shift(1))
    df["tr"] = df[["tr0", "tr1", "tr2"]].max(axis=1)

    df["up_move"] = df["high"] - df["high"].shift(1)
    df["down_move"] = df["low"].shift(1) - df["low"]

    df["plus_dm"] = np.where(
        (df["up_move"] > df["down_move"]) & (df["up_move"] > 0),
        df["up_move"],
        0,
    )
    df["minus_dm"] = np.where(
        (df["down_move"] > df["up_move"]) & (df["down_move"] > 0),
        df["down_move"],
        0,
    )

    alpha = 1 / adx_period
    df["tr_smooth"] = df["tr"].ewm(alpha=alpha, adjust=False).mean()
    df["plus_di_smooth"] = df["plus_dm"].ewm(alpha=alpha, adjust=False).mean()
    df["minus_di_smooth"] = df["minus_dm"].ewm(alpha=alpha, adjust=False).mean()

    tr_smooth = df["tr_smooth"].replace(0, np.nan)
    df["plus_di"] = 100 * (df["plus_di_smooth"] / tr_smooth)
    df["minus_di"] = 100 * (df["minus_di_smooth"] / tr_smooth)

    di_sum = (df["plus_di"] + df["minus_di"]).replace(0, np.nan)
    df["dx"] = 100 * abs(df["plus_di"] - df["minus_di"]) / di_sum
    df["adx"] = df["dx"].ewm(alpha=alpha, adjust=False).mean()

    # Ochrona przed wejściami na samych szczytach / dołkach (RSI / Momentum exhaustion filter)
    delta = df["close"].diff()
    gain = (delta.where(delta > 0, 0)).ewm(span=14, adjust=False).mean()
    loss = (-delta.where(delta < 0, 0)).ewm(span=14, adjust=False).mean()
    rs = gain / loss.replace(0, np.nan)
    df["rsi"] = 100 - (100 / (1 + rs))

    return df

# =====================================================================
# INICJALIZACJA BAZY DANYCH SQLITE
# =====================================================================
def init_db():
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        email TEXT UNIQUE,
        password TEXT,
        is_admin INTEGER DEFAULT 0,
        stripe_paid INTEGER DEFAULT 0,
        api_key TEXT,
        secret_key TEXT,
        passphrase TEXT
    )
    """)
    for col, col_type in [
        ("api_key", "TEXT"),
        ("secret_key", "TEXT"),
        ("passphrase", "TEXT"),
        ("stripe_paid", "INTEGER DEFAULT 0"),
        ("is_admin", "INTEGER DEFAULT 0"),
    ]:
        try:
            cursor.execute(f"ALTER TABLE users ADD COLUMN {col} {col_type}")
        except sqlite3.OperationalError:
            pass

    for adm_email in ADMIN_EMAILS:
        cursor.execute(
            "UPDATE users SET is_admin = 1, stripe_paid = 1 WHERE LOWER(TRIM(email)) = ?",
            (adm_email,),
        )

    cursor.execute(
        "SELECT * FROM users WHERE LOWER(TRIM(email)) = ?",
        ("admin@bot-bitget.pl",),
    )
    if not cursor.fetchone():
        admin_pass = st.secrets.get("ADMIN_PASSWORD", "TwojeTajneHaslo123")
        cursor.execute(
            "INSERT INTO users (email, password, is_admin, stripe_paid) VALUES (?, ?, 1, 1)",
            ("admin@bot-bitget.pl", admin_pass),
        )
    conn.commit()
    conn.close()

init_db()

def load_stripe_credentials():
    if os.path.exists(STRIPE_CONFIG_FILE):
        try:
            with open(STRIPE_CONFIG_FILE, "r") as f:
                data = json.load(f)
                return (
                    data.get("stripe_pk", ""),
                    data.get("stripe_sk", ""),
                    data.get("stripe_price_id", ""),
                )
        except Exception:
            pass
    return "", "", ""

def save_stripe_credentials(pk, sk, price_id):
    try:
        with open(STRIPE_CONFIG_FILE, "w") as f:
            json.dump(
                {"stripe_pk": pk, "stripe_sk": sk, "stripe_price_id": price_id},
                f,
            )
        return True
    except Exception:
        return False

saved_stripe_pk, saved_stripe_sk, saved_stripe_price_id = (
    load_stripe_credentials()
)
stripe_pk_val = saved_stripe_pk or st.secrets.get("STRIPE_PK", "")
stripe_sk_val = saved_stripe_sk or st.secrets.get("STRIPE_SK", "")
stripe_price_id_val = saved_stripe_price_id or st.secrets.get(
    "STRIPE_PRICE_ID", ""
)

if stripe_sk_val:
    stripe.api_key = stripe_sk_val

# =====================================================================
# INICJALIZACJA STANU SESSION STATE
# =====================================================================
if "logged_in" not in st.session_state:
    st.session_state.logged_in = False
if "user_email" not in st.session_state:
    st.session_state.user_email = ""
if "is_admin" not in st.session_state:
    st.session_state.is_admin = False
if "user_id" not in st.session_state:
    st.session_state.user_id = None
if "stripe_paid" not in st.session_state:
    st.session_state.stripe_paid = False
if "known_markets" not in st.session_state:
    st.session_state.known_markets = set()
if "last_fut_total" not in st.session_state:
    st.session_state.last_fut_total = 0.0
if "last_fut_free" not in st.session_state:
    st.session_state.last_fut_free = 0.0
if "session_start_balance" not in st.session_state:
    st.session_state.session_start_balance = 0.0
if "session_baseline_locked" not in st.session_state:
    st.session_state.session_baseline_locked = False
if "scanner_active" not in st.session_state:
    st.session_state.scanner_active = False
if "trend_bot_fut_active" not in st.session_state:
    st.session_state.trend_bot_fut_active = False
if "session_start_time" not in st.session_state:
    st.session_state.session_start_time = datetime.now()
if "trade_history" not in st.session_state:
    st.session_state.trade_history = []
if "signal_cooldown" not in st.session_state:
    st.session_state.signal_cooldown = {}
if "active_trades" not in st.session_state:
    st.session_state.active_trades = {}
if "scanner_diagnostics" not in st.session_state:
    st.session_state.scanner_diagnostics = []
if "lang" not in st.session_state:
    st.session_state.lang = "Polski"
if "api_key" not in st.session_state:
    st.session_state.api_key = ""
if "secret_key" not in st.session_state:
    st.session_state.secret_key = ""
if "passphrase" not in st.session_state:
    st.session_state.passphrase = ""
if "selected_exchange" not in st.session_state:
    st.session_state.selected_exchange = "Bitget"

if st.query_params.get("success") == "true":
    if st.session_state.logged_in and st.session_state.user_id:
        st.session_state.stripe_paid = True
        try:
            conn = sqlite3.connect(DB_FILE)
            cursor = conn.cursor()
            cursor.execute(
                "UPDATE users SET stripe_paid = 1 WHERE id = ?",
                (st.session_state.user_id,),
            )
            conn.commit()
            conn.close()
        except Exception:
            pass
    st.success(
        "🎉 Płatność zakończona sukcesem! Twoja subskrypcja została aktywowana."
    )
    st.query_params.clear()

# =====================================================================
# STYLIZACJA WYGLĄDU
# =====================================================================
st.markdown(
    """<style>
@import url('https://fonts.googleapis.com/css2?family=Bungee+Inline&family=Cinzel:wght@700&display=swap');
.stApp { background-color: #0d0b0a; }
section[data-testid="stSidebar"] { background-color: #141110; border-right: 2px solid #3d2f1f; }
.metrics-row {
    display: flex;
    flex-direction: row;
    flex-wrap: nowrap !important;
    gap: 14px;
    width: 100%;
    margin-bottom: 10px;
}
.metric-card {
    flex: 1;
    min-width: 0;
    border: 2px solid #f3d57a;
    border-radius: 10px;
    padding: 12px 14px;
    background-color: rgba(243, 213, 122, 0.03);
    box-shadow: 0 4px 12px rgba(0, 0, 0, 0.2);
}
.metric-label {
    font-family: 'Cinzel', serif;
    color: #f3d57a;
    font-size: 0.85rem;
    font-weight: 700;
    margin-bottom: 6px;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
}
.metric-value {
    font-size: 1.4rem;
    font-weight: bold;
    color: #ffffff;
    margin-bottom: 4px;
}
.metric-delta {
    font-size: 0.75rem;
    color: #e6c687;
}
.hero-wrapper { display: flex; align-items: center; justify-content: center; width: 100%; padding-top: 50px; padding-bottom: 20px; }
.retro-ornate-frame { position: relative; background: radial-gradient(circle, #221a14 0%, #110d0a 100%); border: 6px double #f3d57a; padding: 40px 30px; border-radius: 16px; box-shadow: 0 0 50px rgba(243, 213, 122, 0.4), inset 0 0 35px rgba(0, 0, 0, 0.9); width: 100%; max-width: 600px; text-align: center; }
.retro-vintage-title { font-family: 'Bungee Inline', cursive, sans-serif; font-size: 3rem; color: #f3d57a; letter-spacing: 4px; text-shadow: 4px 4px 0px #8b0000, 8px 8px 0px rgba(0,0,0,0.95); margin-bottom: 10px; }
.retro-subtitle { font-family: 'Cinzel', serif; color: #e6c687; font-size: 1.1rem; letter-spacing: 2px; margin-bottom: 25px; }
div.stButton > button { background: linear-gradient(135deg, #1e4d2b 0%, #0f2b17 100%) !important; color: #f3d57a !important; border: 2px solid #f3d57a !important; font-family: 'Cinzel', serif !important; font-weight: 700 !important; font-size: 1rem !important; padding: 10px 24px !important; border-radius: 8px !important; box-shadow: 0 4px 15px rgba(0, 0, 0, 0.6) !important; transition: all 0.3s ease !important; }
div.stButton > button:hover { background: linear-gradient(135deg, #28663a 0%, #163d22 100%) !important; border-color: #ffe89d !important; color: #ffe89d !important; box-shadow: 0 0 20px rgba(243, 213, 122, 0.4) !important; transform: translateY(-2px); }
</style>""",
    unsafe_allow_html=True,
)

# =====================================================================
# EKRAN LOGOWANIA / REJESTRACJI
# =====================================================================
if not st.session_state.logged_in:
    st.markdown(
        """<div class="hero-wrapper">
<div class="retro-ornate-frame">
<div class="retro-vintage-title">BITGET FUTURES</div>
<div class="retro-subtitle">AUTONOMICZNY SYSTEM TRANSAKCYJNY</div>""",
        unsafe_allow_html=True,
    )
    tab_login, tab_register = st.tabs(["🔑 Zaloguj się", "📝 Załóż konto"])
    with tab_login:
        st.markdown(
            "<p style='color: #f3d57a; font-family: Cinzel, serif;'>Logowanie do Panelu Klienta</p>",
            unsafe_allow_html=True,
        )
        login_email = st.text_input("Adres e-mail", key="log_email")
        login_pass = st.text_input("Hasło", type="password", key="log_pass")
        if st.button("ZALOGUJ SIĘ", use_container_width=True):
            conn = sqlite3.connect(DB_FILE)
            cursor = conn.cursor()
            cursor.execute(
                "SELECT id, email, password, is_admin, stripe_paid, api_key, secret_key, passphrase FROM users WHERE LOWER(TRIM(email)) = ?",
                (login_email.strip().lower(),),
            )
            user_row = cursor.fetchone()
            conn.close()
            if user_row and user_row[2] == login_pass:
                user_email_str = user_row[1].strip().lower()
                is_admin_flag = (
                    True if user_email_str in ADMIN_EMAILS else bool(user_row[3])
                )
                stripe_paid_flag = True if is_admin_flag else bool(user_row[4])
                st.session_state.logged_in = True
                st.session_state.user_id = user_row[0]
                st.session_state.user_email = user_row[1]
                st.session_state.is_admin = is_admin_flag
                st.session_state.stripe_paid = stripe_paid_flag
                st.session_state.api_key = user_row[5] or ""
                st.session_state.secret_key = user_row[6] or ""
                st.session_state.passphrase = user_row[7] or ""
                st.success("Zalogowano pomyślnie!")
                st.rerun()
            else:
                st.error("Nieprawidłowy e-mail lub hasło.")

    with tab_register:
        st.markdown(
            "<p style='color: #f3d57a; font-family: Cinzel, serif;'>Rejestracja Nowego Konta</p>",
            unsafe_allow_html=True,
        )
        reg_email = st.text_input("Twój e-mail", key="reg_email")
        reg_pass = st.text_input("Utwórz hasło", type="password", key="reg_pass")
        if st.button("ZAREJESTRUJ SIĘ", use_container_width=True):
            if reg_email and reg_pass:
                try:
                    conn = sqlite3.connect(DB_FILE)
                    cursor = conn.cursor()
                    clean_reg = reg_email.strip().lower()
                    is_adm = 1 if clean_reg in ADMIN_EMAILS else 0
                    is_paid = 1 if is_adm == 1 else 0
                    cursor.execute(
                        "INSERT INTO users (email, password, is_admin, stripe_paid) VALUES (?, ?, ?, ?)",
                        (reg_email.strip(), reg_pass, is_adm, is_paid),
                    )
                    conn.commit()
                    conn.close()
                    st.success("Konto założone! Przejdź do zakładki logowania.")
                except sqlite3.IntegrityError:
                    st.error("Ten e-mail jest już zarejestrowany.")
            else:
                st.error("Wypełnij wszystkie pola.")
    st.markdown("</div></div>", unsafe_allow_html=True)
    st.stop()

# =====================================================================
# GŁÓWNA APLIKACJA (PO ZALOGOWANIU)
# =====================================================================
st.session_state.lang = st.sidebar.selectbox(
    "🌐 Język / Language", ["Polski", "English"], key="lang_selector"
)

if st.session_state.lang == "Polski":
    with st.sidebar.expander("📖 Instrukcja Obsługi i Regulamin"):
        st.sidebar.markdown("""
1. Jak zacząć:
* Wpisz klucze API giełdy w panelu.
* Opłać subskrypcję Stripe.
* Wybierz pary walut i strategię.
* Włącz auto-skanowanie / handel.

2. Regulamin:
* Handel na giełdzie wiąże się z ryzykiem utraty kapitału.
* Narzędzie służy do celów analitycznych i automatyzacji.
""")
else:
    with st.sidebar.expander("📖 User Manual & Terms"):
        st.sidebar.markdown("""
1. Getting Started:
* Enter API keys.
* Complete Stripe subscription.
* Choose pairs and strategy.
* Enable auto-scanning / trading.

2. Terms of Service:
* Crypto trading involves high risk.
* Software is provided as an analytical tool.
""")

def get_exchange():
    if not st.session_state.get("api_key"):
        return None
    try:
        ex_id = st.session_state.get("selected_exchange", "Bitget").lower()
        exchange_class = getattr(ccxt, ex_id)
        config = {
            "apiKey": st.session_state.api_key,
            "secret": st.session_state.secret_key,
            "enableRateLimit": True,
            "options": {
                "defaultType": "swap",
                "createOrder": {"createMarketBuyOrderRequiresPrice": False},
            },
        }
        if ex_id in ["bitget", "okx"] and st.session_state.get("passphrase"):
            config["password"] = st.session_state.passphrase

        exchange = exchange_class(config)
        return exchange
    except Exception:
        return None

def calculate_dynamic_leverage(current_vol, mode, manual_leverage):
    if "Ręczny" in mode:
        return int(manual_leverage)
    if current_vol > 4.0:
        return 2
    elif current_vol > 3.0:
        return 4
    elif current_vol > 2.0:
        return 6
    elif current_vol > 1.0:
        return 8
    else:
        return 10

def calculate_dynamic_allocation(total_balance, max_positions, max_single):
    if total_balance <= 0:
        return max_single
    allocated = total_balance / max(1, max_positions)
    return min(max_single, max(5.0, allocated))

import time
import streamlit as st

# ==========================================
# FUNKCJA MONITORUJĄCA I WYKONUJĄCA SL / TP
# ==========================================
def check_and_execute_sl_tp(exchange):
    """
    Sprawdza otwarte pozycje na giełdzie i porównuje ich wynik procentowy 
    z ustawionym Stop-Loss (SL) oraz Take-Profit (TP).
    """
    if not exchange:
        return

    try:
        positions = exchange.fetch_positions()
        for p in positions:
            contracts = float(p.get("contracts", 0))
            if contracts <= 0:
                continue
                
            sym = p["symbol"]
            side = p.get("side") # 'long' lub 'short'
            entry_price = float(p.get("entryPrice", 0) or 0)
            mark_price = float(p.get("markPrice", 0) or 0)
            
            if entry_price <= 0 or mark_price <= 0:
                continue

            # Obliczanie aktualnego zysku/straty w %
            if side == "long":
                pnl_pct = ((mark_price - entry_price) / entry_price) * 100
            else:  
                pnl_pct = ((entry_price - mark_price) / entry_price) * 100

            # Pobieranie ustawień z sesji Streamlita
            enable_sl_tp = st.session_state.get("enable_custom_sl_tp", False)
            sl_pct = st.session_state.get("custom_stop_loss_pct", 5)     
            tp_pct = st.session_state.get("custom_take_profit_pct", 15)  

            if not enable_sl_tp:
                continue

            close_reason = None
            if pnl_pct <= -sl_pct:
                close_reason = f"STOP-LOSS (Strata: {pnl_pct:.2f}% <= -{sl_pct}%)"
            elif pnl_pct >= tp_pct:
                close_reason = f"TAKE-PROFIT (Zysk: {pnl_pct:.2f}% >= {tp_pct}%)"

            if close_reason:
                close_side = "sell" if side == "long" else "buy"
                try:
                    amount_prec = float(exchange.amount_to_precision(sym, contracts))
                    if amount_prec > 0:
                        try:
                            exchange.create_order(
                                symbol=sym,
                                type="market",
                                side=close_side,
                                amount=amount_prec,
                                params={"reduceOnly": True}
                            )
                        except Exception:
                            exchange.create_market_order(
                                symbol=sym,
                                side=close_side,
                                amount=amount_prec,
                                params={"reduceOnly": True}
                            )
                        st.warning(f"🚨 AUTOMATYCZNE ZAMKNIĘCIE [{sym}]: {close_reason}")
                except Exception as ex_order:
                    st.error(f"Błąd wykonania SL/TP dla {sym}: {ex_order}")
    except Exception:
        pass


# ==========================================
# PANEL BOCZNY (SIDEBAR) + INICJALIZACJA SL/TP
# ==========================================
st.sidebar.markdown(f"### 👤 {st.session_state.get('user_email', '')}")
if 'is_user_admin' in globals() and is_user_admin():
    st.sidebar.markdown("**Rola: Administrator**")
else:
    st.sidebar.markdown("**Rola: Klient SaaS**")

if st.sidebar.button("🚪 WYLOGUJ SIĘ", use_container_width=True, key="sidebar_wyloguj_btn"):
    st.session_state.logged_in = False
    st.session_state.user_email = ""
    st.session_state.is_admin = False
    st.session_state.stripe_paid = False
    st.session_state.api_key = ""
    st.session_state.secret_key = ""
    st.session_state.passphrase = ""
    st.rerun()

st.sidebar.header("⚙️ Ustawienia Giełdy & API")
selected_exchange = st.sidebar.selectbox(
    "Wybierz Giełdę:",
    options=["Bitget", "Binance", "Bybit", "OKX"],
    index=0,
    key="sidebar_selected_exchange_sb"
)
st.session_state["selected_exchange"] = selected_exchange

st.sidebar.markdown("---")
st.sidebar.subheader(f"🔑 Klucze API ({selected_exchange})")

input_api = st.sidebar.text_input(
    f"API Key ({selected_exchange}):",
    value=st.session_state.get("api_key", ""),
    type="password",
    key=f"key_{selected_exchange}"
)
input_secret = st.sidebar.text_input(
    f"API Secret ({selected_exchange}):",
    value=st.session_state.get("secret_key", ""),
    type="password",
    key=f"secret_{selected_exchange}"
)

if selected_exchange in ["Bitget", "OKX"]:
    input_pass = st.sidebar.text_input(
        f"Passphrase ({selected_exchange}):",
        value=st.session_state.get("passphrase", ""),
        type="password",
        key=f"pass_{selected_exchange}"
    )
else:
    input_pass = ""

if st.sidebar.button("💾 ZAPISZ MOJE KLUCZE", use_container_width=True, key="sidebar_zapisz_klucze_btn"):
    if input_api and input_secret:
        st.session_state.api_key = input_api
        st.session_state.secret_key = input_secret
        st.session_state.passphrase = input_pass
        
        try:
            import sqlite3
            conn = sqlite3.connect("trading.db")
            cursor = conn.cursor()
            cursor.execute(
                "UPDATE users SET api_key = ?, secret_key = ?, passphrase = ? WHERE id = ?",
                (input_api, input_secret, input_pass, st.session_state.get("user_id"))
            )
            conn.commit()
            conn.close()
        except Exception:
            pass

        st.success(f"Zapisano klucze dla {selected_exchange}!")
        st.rerun()
    else:
        st.error("Wypełnij wymagane pola kluczy.")

st.sidebar.markdown("---")
st.sidebar.markdown("### 🛡️ Strefa Subskrypcji")
is_admin_flag = is_user_admin() if 'is_user_admin' in globals() else False
is_paid_flag = is_user_paid() if 'is_user_paid' in globals() else False

if is_admin_flag or is_paid_flag:
    st.sidebar.success("Subskrypcja aktywna (Dostęp Pełny)")
else:
    st.sidebar.warning("⚠️ Brak aktywnej subskrypcji")
    st.sidebar.link_button(
        "OPŁAĆ DOSTĘP (49 PLN)", "https://buy.stripe.com/00w0kecLiSfbc8c13qA88"
    )

if is_admin_flag:
    with st.sidebar.expander("⚙️ Konfiguracja Stripe (Admin)"):
        input_s_pk = st.text_input("Stripe Publishable Key", value=str(st.session_state.get("stripe_pk_val", "")), type="password", key="admin_s_pk")
        input_s_sk = st.text_input("Stripe Secret Key", value=str(st.session_state.get("stripe_sk_val", "")), type="password", key="admin_s_sk")
        input_s_price = st.text_input("Stripe Price ID (np. price_...)", value=str(st.session_state.get("stripe_price_id_val", "")), key="admin_s_price")
        if st.button("Zapisz Konfigurację Stripe", key="admin_save_stripe"):
            try:
                if 'save_stripe_credentials' in globals():
                    save_stripe_credentials(input_s_pk, input_s_sk, input_s_price)
                st.success("Zapisano dane Stripe pomyślnie.")
            except Exception:
                st.error("Błąd zapisu.")

# Inicjalizacja giełdy
futures_ex = get_exchange() if 'get_exchange' in globals() else None
if futures_ex and not st.session_state.get("known_markets", False):
    try:
        markets = futures_ex.load_markets()
        st.session_state.known_markets = set(markets.keys())
    except Exception:
        pass

st.sidebar.markdown("---")
st.sidebar.markdown("### 💰 Kapitał i Ryzyko")
max_single_trade_usdt = st.sidebar.number_input("Maksymalnie USDT na 1 pozycję", 5.0, 5000.0, 50.0, 5.0, key="sb_max_single_trade")
max_active_futures_positions = st.sidebar.slider("Maks. aktywne pozycje Futures", 1, 20, 5, key="sb_max_active_pos")

st.sidebar.markdown("---")
st.sidebar.markdown("### 🚨 Awaryjne SL / TP (Pojedyncza pozycja)")

# KLUCZOWE: Zapis do session_state, żeby funkcja wyżej mogła to odczytać
enable_custom_sl_tp = st.sidebar.checkbox("Włącz awaryjne limity SL / TP (%)", value=False, key="enable_custom_sl_tp")
custom_stop_loss_pct = st.sidebar.slider("Maksymalna strata (Stop-Loss %)", 1, 50, 5, key="custom_stop_loss_pct")
custom_take_profit_pct = st.sidebar.slider("Docelowy zysk (Take-Profit %)", 1, 200, 15, key="custom_take_profit_pct")

# AUTOMATYCZNE WYWOŁANIE SPRAWDZANIA SL/TP W KAŻDYM ODŚWIŻENIU BOCZNYM / PĘTLI
if futures_ex and enable_custom_sl_tp:
    check_and_execute_sl_tp(futures_ex)

st.sidebar.markdown("---")
st.sidebar.markdown("### 🌐 Globalny TP / SL Całej Sesji")
enable_global_session_limit = st.sidebar.checkbox("Włącz globalny limit sesji (%)", value=True, key="sb_enable_global_lim")
global_session_tp_pct = st.sidebar.slider("Globalny zysk sesji (Take-Profit %)", 1, 100, 10, key="sb_glb_tp")
global_session_sl_pct = st.sidebar.slider("Globalna strata sesji (Stop-Loss %)", 1, 50, 5, key="sb_glb_sl")

st.sidebar.markdown("---")
st.sidebar.markdown("### ⚡ Zarządzanie Dźwignią")
leverage_mode = st.sidebar.radio("Tryb Dźwigni", ["Autonomiczny (max 10x)", "Ręczny"], key="sb_lev_mode")
manual_leverrage = st.sidebar.slider("Stała dźwignia Futures", 1, 10, 3, key="sb_manual_leverage")

st.sidebar.markdown("---")
st.sidebar.markdown("### ⏱️ Timeframe Analizy")
fut_tf = st.sidebar.selectbox("Interwał", ["1m", "5m", "15m", "30m", "1h", "4h", "1d"], index=4, key="sb_fut_tf")

st.sidebar.markdown("---")
st.sidebar.markdown("### ⚙️ Konfiguracja Skanera i Bota")
timeframe_val = st.selectbox("Interwał czasowy", ["1m", "5m", "15m", "30m", "1h", "4h", "1d"], index=4, key="conf_tf_val")
ema_fast_val = int(st.number_input("Okres EMA Szybka", min_value=1, max_value=200, value=9, key="conf_ema_fast"))
ema_slow_val = int(st.number_input("Okres EMA Wolna", min_value=2, max_value=300, value=21, key="conf_ema_slow"))

st.sidebar.markdown("---")
st.sidebar.markdown("### 🤖 Panel Sterowania Botem Futures")
bot_active = st.sidebar.checkbox("Uruchom Bota Futures (Filtry ADX + EMA50)", value=False, key="sidebar_bot_active_cb")

st.sidebar.markdown("---")
st.sidebar.markdown("### 🔄 Pętla Skanera")

def toggle_scanner_from_sidebar():
    st.session_state.scanner_active = st.session_state.sidebar_auto_scan_cb
    if st.session_state.scanner_active:
        st.session_state.session_baseline_locked = False

auto_scan_enabled = st.sidebar.checkbox(
    "Włącz auto-skanowanie w tle",
    key="sidebar_auto_scan_cb",
    on_change=toggle_scanner_from_sidebar,
)
scan_interval = st.sidebar.slider("Interwał odświeżania (s)", 3, 300, 5, key="sb_scan_interval")
max_fut_scan_pairs = st.sidebar.slider("Liczba par Futures", 5, 100, 30, 5, key="sb_max_fut_pairs")

st.sidebar.markdown("---")
emergency_kill = st.sidebar.button(
    "🔴 ZAMKNIJ WSZYSTKO (KILL SWITCH)",
    type="primary",
    use_container_width=True,
    key="sidebar_kill_switch_btn",
)

if emergency_kill:
    if futures_ex:
        try:
            positions = futures_ex.fetch_positions()
            for p in positions:
                contracts = float(p.get("contracts", 0))
                if contracts > 0:
                    sym = p["symbol"]
                    side = "sell" if p.get("side") == "long" else "buy"
                    try:
                        contracts_prec = float(futures_ex.amount_to_precision(sym, contracts))
                        if contracts_prec > 0:
                            try:
                                futures_ex.create_order(sym, "market", side, contracts_prec, params={"reduceOnly": True})
                            except Exception:
                                futures_ex.create_market_order(sym, side, contracts_prec, params={"reduceOnly": True})
                    except Exception:
                        pass
        except Exception:
            pass

    st.session_state.scanner_active = False
    if 'trend_bot_ft_active' not in st.session_state:
        st.session_state.trend_bot_ft_active = False
    st.session_state.active_trades = {}
    st.session_state.signal_cooldown = {}
    st.session_state.session_start_balance = 0.0
    st.session_state.session_baseline_locked = False
    st.session_state.scanner_diagnostics = []
    st.success("🔴 KILL SWITCH WYKONANY. Zamknięto wszystkie pozycje Futures.")
    time.sleep(2)
    st.rerun()

# ==========================================
# WYLICZENIE SALDA, POZYCJI I METRYK FUTURES
# ==========================================
fut_free, fut_total = 0.0, 0.0
active_positions_count = 0
total_pnl = 0.0
total_unrealized_pnl = 0.0
current_positions = []

if futures_ex:
    try:
        f_bal = futures_ex.fetch_balance({"type": "swap"})
        if "USDT" in f_bal:
            fut_free = float(f_bal["USDT"].get("free", 0.0))
            fut_total = float(f_bal["USDT"].get("total", 0.0))
            fut_used = float(f_bal["USDT"].get("used", 0.0))
            if fut_used > 0 and fut_free >= fut_total:
                fut_free = fut_total - fut_used
    except Exception:
        try:
            f_bal = futures_ex.fetch_balance()
            if "USDT" in f_bal:
                fut_free = float(f_bal["USDT"].get("free", 0.0))
                fut_total = float(f_bal["USDT"].get("total", 0.0))
        except Exception:
            pass

    try:
        current_positions = futures_ex.fetch_positions()
        active_pos = [p for p in current_positions if float(p.get("contracts", 0)) > 0]
        active_positions_count = len(active_pos)
        total_pnl = sum(float(p.get("unrealizedPnl", 0)) for p in active_pos)
        total_unrealized_pnl = total_pnl
        total_margin_used = sum(
            float(
                p.get("initialMargin")
                or p.get("margin", 0)
                or p.get("info", {}).get("margin", 0)
            )
            for p in active_pos
        )
        if total_margin_used > 0 and (fut_total - fut_free) < 1:
            fut_free = max(0.0, fut_total - total_margin_used)
    except Exception:
        active_positions_count = len(st.session_state.get("active_trades", {}))

if (
    not st.session_state.session_baseline_locked
    or st.session_state.session_start_balance == 0.0
) and fut_total > 0:
    st.session_state.session_start_balance = fut_total
    st.session_state.session_baseline_locked = True

start_val = st.session_state.get("session_start_time", datetime.now())
try:
    if hasattr(start_val, "timestamp"):
        session_elapsed = int(time.time() - start_val.timestamp())
    else:
        session_elapsed = int(time.time() - float(start_val))
except Exception:
    session_elapsed = 0

hours, rem = divmod(session_elapsed, 3600)
minutes, seconds = divmod(rem, 60)

session_pnl_pct_display = 0.0
if (
    "session_start_balance" in st.session_state
    and st.session_state.session_start_balance > 0
    and fut_total > 0
):
    session_pnl_pct_display = (
        (fut_total - st.session_state.session_start_balance)
        / st.session_state.session_start_balance
    ) * 100
elif fut_total > 0:
    session_pnl_pct_display = (total_pnl / fut_total) * 100

# =====================================================================
# GŁÓWNE KAFELKI
# =====================================================================
st.markdown(
    f"""
<div class="metrics-row">
<div class="metric-card">
<div class="metric-label">🔵 Portfel Futures</div>
<div class="metric-value">{fut_total:.2f} USDT</div>
<div class="metric-delta">Wolne: {fut_free:.2f} USDT</div>
</div>
<div class="metric-card">
<div class="metric-label">📊 Wyniki Sesji (PnL %)</div>
<div class="metric-value">{session_pnl_pct_display:+.2f}%</div>
<div class="metric-delta">Pnl USDT: {total_unrealized_pnl:+.2f} USDT</div>
</div>
<div class="metric-card">
<div class="metric-label">📈 Sloty Futures</div>
<div class="metric-value">{active_positions_count} / {max_active_futures_positions}</div>
<div class="metric-delta">Aktywne / Maksymalne</div>
</div>
<div class="metric-card">
<div class="metric-label">⏱️ Czas Sesji</div>
<div class="metric-value">{hours:02d}:{minutes:02d}:{seconds:02d}</div>
<div class="metric-delta">Interwał: {scan_interval}s | Wykres: {fut_tf}</div>
</div>
</div>
""",
    unsafe_allow_html=True,
)

st.markdown("---")
st.subheader("🥾 Panel Sterowania Botem Futures")

with st.container(border=True):
    def toggle_main_trend_fut():
        st.session_state.trend_bot_fut_active = (
            st.session_state.main_cb_trend_fut
        )
        if st.session_state.trend_bot_fut_active and fut_total > 0:
            st.session_state.session_baseline_locked = False

    st.checkbox(
        "🔵 Uruchom Bota Futures (Filtry ADX + EMA50 + Ochrona Szczytów/Dołków)",
        value=st.session_state.get("trend_bot_fut_active", False),
        key="main_cb_trend_fut",
        on_change=toggle_main_trend_fut,
    )

    if st.session_state.trend_bot_fut_active:
        st.success(
            f"🟢 Bot Futures Aktywny (Timeframe: {fut_tf}, Filtr ADX >= 18 + EMA 50 + MACD + RSI)"
        )
    else:
        st.info("🔴 Bot Futures Zatrzymany")

    st.markdown("---")
    col_btn, col_status = st.columns([2, 1])
    with col_btn:
        if not st.session_state.scanner_active:
            if st.button(
                "🚀 Uruchom Skaner Non-Stop",
                type="primary",
                use_container_width=True,
            ):
                st.session_state.scanner_active = True
                st.session_state.session_baseline_locked = False
                st.rerun()
        else:
            if st.button(
                "⏹️ Zatrzymaj Skaner",
                type="secondary",
                use_container_width=True,
            ):
                st.session_state.scanner_active = False
            if 'trend_bot_ft_active' not in st.session_state:
                st.session_state.trend_bot_ft_active = False 
                st.session_state.session_start_balance = 0.0
                st.session_state.session_baseline_locked = False
                st.session_state.scanner_diagnostics = []
                st.rerun()

    with col_status:
        if st.session_state.scanner_active:
            st.success("STATUS: AKTYWNY")
        else:
            st.error("STATUS: ZATRZYMANY")

# ==========================================
# POMOCNICZE FUNKCJE DŹWIGNI I GIEŁDY
# ==========================================
def get_exchange_max_leverage(exchange, symbol, default_max=20):
    try:
        market = exchange.market(symbol)
        if 'limits' in market and 'leverage' in market['limits']:
            max_lev = market['limits']['leverage'].get('max')
            if max_lev:
                return int(max_lev)
    except Exception:
        pass
    return default_max

def get_smart_leverage(adx_val, exchange_limit, preferred_max=20):
    effective_max = min(preferred_max, exchange_limit)
    if adx_val < 20:
        return min(3, effective_max)
    elif adx_val < 30:
        return min(5, effective_max)
    elif adx_val < 40:
        return min(10, effective_max)
    elif adx_val < 50:
        return min(15, effective_max)
    else:
        return effective_max
# ==========================================
# POBRANIE PAR, POZYCIJI I SILNIK TRANSAKCYJNY
# ==========================================
try:
    if futures_ex and hasattr(futures_ex, 'load_markets'):
        futures_ex.load_markets()

    # Pobieramy tickery z giełdy używając poprawnej zmiennej futures_ex
    tickers = futures_ex.fetch_tickers()

    # Minimalny dobowy wolumen w USDT (np. 5 milionów USDT)
    MIN_VOLUME_USDT = 5_000_000

    filtered_symbols = []
    for symbol, ticker in tickers.items():
        # Sprawdzamy kontrakty USDT-M i ich wolumen
        if symbol.endswith('/USDT:USDT') or symbol.endswith(':USDT'):
            quote_volume = ticker.get('quoteVolume', 0) or 0
            if quote_volume >= MIN_VOLUME_USDT:
                filtered_symbols.append(symbol)

    # Sortujemy od największego wolumenu i ograniczamy do limitu skanera
    filtered_symbols = sorted(
        filtered_symbols,
        key=lambda s: tickers.get(s, {}).get('quoteVolume', 0) or 0,
        reverse=True,
    )

    selected_symbols = filtered_symbols[:max_fut_scan_pairs]
except Exception as e:
    print(f"[DEBUG BŁĄD RYNKÓW]: {e}")
    selected_symbols = []

existing_positions_map = {}
real_active_positions_count = 0
try:
    if futures_ex and hasattr(futures_ex, 'fetch_positions'):
        raw_pos_check = futures_ex.fetch_positions()
        for p in raw_pos_check:
            if isinstance(p, dict):
                contracts = float(p.get("contracts", p.get("amount", 0)))
                if contracts != 0:
                    sym = p.get("symbol")
                    side = str(p.get("side", "")).lower()
                    existing_positions_map[sym] = side
                    real_active_positions_count += 1
except Exception as e:
    print(f"[DEBUG BŁĄD POZYCJI]: {e}")
    pass

scan_results = []
bot_active = st.session_state.get("trend_bot_fut_active", False)

# Bezpieczne pobranie zmiennej dźwigni dla Pylance i pętli
manual_leverage = st.session_state.get("manual_leverage", st.session_state.get("manual_lev", 10))

if selected_symbols and futures_ex:
    for symbol in selected_symbols:
        signal_type = "NEUTRALNY"
        current_adx = 20.0
        market_price = 0.0

        try:
            ohlcv = futures_ex.fetch_ohlcv(symbol, timeframe=timeframe_val, limit=100)
            if ohlcv and len(ohlcv) > ema_slow_val:
                df_sym = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
                df_sym = calculate_indicators(df_sym, ema_period=ema_fast_val)
                df_sym['EMA_fast'] = df_sym['close'].ewm(span=ema_fast_val, adjust=False).mean()
                df_sym['EMA_slow'] = df_sym['close'].ewm(span=ema_slow_val, adjust=False).mean()

                # Poprawiona, w 100% szczelna kalkulacja RSI (odporna na dzielenie przez zero na pompowanych świecach)
                delta = df_sym['close'].diff()
                gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
                loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
                
                # Zabezpieczenie przed brakiem strat (loss = 0 na pionowych świecach wzrostowych)
                rs = gain / loss.replace(0, 1e-10)
                df_sym['rsi'] = 100 - (100 / (1 + rs))
                df_sym['rsi'] = df_sym['rsi'].fillna(100.0) # Jeśli loss=0, to pełne wykupienie (RSI 100)

                last_r = df_sym.iloc[-1]
                prev_r = df_sym.iloc[-2]
                market_price = float(last_r['close'])

                if 'adx' in last_r and not pd.isna(last_r['adx']):
                    current_adx = float(last_r['adx'])

                # Generowanie sygnału z EMA
                if prev_r['EMA_fast'] <= prev_r['EMA_slow'] and last_r['EMA_fast'] > last_r['EMA_slow']:
                    signal_type = "LONG"
                elif prev_r['EMA_fast'] >= prev_r['EMA_slow'] and last_r['EMA_fast'] < last_r['EMA_slow']:
                    signal_type = "SHORT"

                # BEZLITOSNY FILTR LOKALNYCH GÓREK I DOŁKÓW (RSI)
                rsi_val = float(last_r['rsi']) if 'rsi' in last_r and not pd.isna(last_r['rsi']) else 100.0
                if signal_type == "LONG" and rsi_val > 70:
                    signal_type = "NEUTRALNY"
                    print(f"[DEBUG] Odrzucono LONG dla {symbol}: RSI wynosi {rsi_val:.1f} (lokalna górka / wykupienie).")
                elif signal_type == "SHORT" and rsi_val < 30:
                    signal_type = "NEUTRALNY"
                    print(f"[DEBUG] Odrzucono SHORT dla {symbol}: RSI wynosi {rsi_val:.1f} (lokalny dołek / wyprzedanie).")

        except Exception as e:
            print(f"[DEBUG BŁĄD OHLCV dla {symbol}]: {e}")
            pass

        scan_results.append({
            "Para": symbol,
            "Sygnał": signal_type,
            "Cena": f"{market_price:.4f}" if market_price > 0 else "Błąd",
            "Status": "Aktywny"
        })

        if bot_active and signal_type != "NEUTRALNY":
            current_pos_side = existing_positions_map.get(symbol, None)

            if not current_pos_side:
                cooldown_key = f"trend_bot_fut_{symbol}"
                now_ts = time.time()

                if now_ts > st.session_state.signal_cooldown.get(cooldown_key, 0):
                    if real_active_positions_count < max_active_futures_positions:
                        trade_side = "buy" if signal_type == "LONG" else "sell"
                        try:
                            if market_price <= 0:
                                ticker = futures_ex.fetch_ticker(symbol)
                                market_price = float(ticker.get("last") or ticker.get("close", 0))
                            if market_price <= 0:
                                continue

                            exch_max_lev = get_exchange_max_leverage(futures_ex, symbol, default_max=20)
                            lev_to_set = get_smart_leverage(current_adx, exch_max_lev, 10 if "Autonomiczny" in leverage_mode else manual_leverage)

                            base_alloc = calculate_dynamic_allocation(fut_free if fut_free > 0 else 1000.0, max_active_futures_positions, max_single_trade_usdt)
                            notional_usdt = base_alloc * lev_to_set
                            amount_contracts = notional_usdt / market_price

                            try:
                                amount_str = futures_ex.amount_to_precision(symbol, amount_contracts)
                                amount_val = float(amount_str)
                                if amount_val <= 0:
                                    amount_val = amount_contracts
                            except Exception:
                                amount_val = amount_contracts

                            if (amount_val * market_price) < 5.0:
                                print(f"[DEBUG] Zlecenie dla {symbol} odrzucone: za mała wartość notional (< 5 USDT).")
                                continue

                            print(f"[DEBUG] Wysyłam zlecenie: {symbol} | Strona: {trade_side} | Ilość: {amount_val} | Dźwignia: {lev_to_set}x")
                            
                            # 1. Ustawienie dźwigni
                            futures_ex.set_leverage(lev_to_set, symbol)
                            
                            # 2. Otwarcie pozycji rynkowej
                            futures_ex.create_order(symbol, "market", trade_side, amount_val, params={})

                            # 3. Ustawienie Stop Loss i Take Profit
                            try:
                                sl_pct = 0.02
                                tp_pct = 0.04
                                if trade_side == "buy":
                                    sl_price = market_price * (1.0 - sl_pct)
                                    tp_price = market_price * (1.0 + tp_pct)
                                    sl_side = "sell"
                                    tp_side = "sell"
                                else:
                                    sl_price = market_price * (1.0 + sl_pct)
                                    tp_price = market_price * (1.0 - tp_pct)
                                    sl_side = "buy"
                                    tp_side = "buy"

                                sl_precision = float(futures_ex.price_to_precision(symbol, sl_price))
                                tp_precision = float(futures_ex.price_to_precision(symbol, tp_price))

                                # Stop Loss
                                futures_ex.create_order(
                                    symbol, 'stop_market', sl_side, amount_val, 
                                    params={'triggerPrice': sl_precision, 'stopPrice': sl_precision, 'reduceOnly': True}
                                )
                                print(f"[DEBUG] Ustawiono Stop Loss dla {symbol} na cenie {sl_precision}")

                                # Take Profit
                                futures_ex.create_order(
                                    symbol, 'take_profit_market', tp_side, amount_val, 
                                    params={'triggerPrice': tp_precision, 'stopPrice': tp_precision, 'reduceOnly': True}
                                )
                                print(f"[DEBUG] Ustawiono Take Profit dla {symbol} na cenie {tp_precision}")
                            except Exception as sl_err:
                                print(f"[BŁĄD SL/TP]: Nie udało się ustawić zabezpieczeń dla {symbol}: {sl_err}")

                            st.session_state.signal_cooldown[cooldown_key] = now_ts + 60
                            st.session_state.trade_history.insert(0, {
                                "Czas": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                                "Para": symbol,
                                "Typ": signal_type,
                                "Cena": f"{market_price:.4f}",
                                "Ilość": f"{amount_val:.4f}",
                                "Dźwignia": f"{lev_to_set}x"
                            })
                            existing_positions_map[symbol] = "buy" if signal_type == "LONG" else "sell"
                            real_active_positions_count += 1
                        except Exception as e:
                            print(f"[KRYTYCZNY BŁĄD SKŁADANIA ZLECENIA dla {symbol}]: {e}")
                            pass

st.markdown("---")
st.markdown("### 📊 Wyniki Skanera Rynkowego")

if scan_results:
    st.dataframe(pd.DataFrame(scan_results), use_container_width=True, hide_index=True)
else:
    st.info("Brak danych ze skanera.")

col_tab1, col_tab2 = st.columns(2)

with col_tab1:
    st.markdown("### 📈 Aktywne Pozycje Futures")
    raw_pos = []
    try:
        if futures_ex and hasattr(futures_ex, 'fetch_positions'):
            raw_pos = futures_ex.fetch_positions()
    except Exception:
        raw_pos = []

    parsed_positions = []
    if raw_pos:
        for p in raw_pos:
            if isinstance(p, dict):
                contracts = p.get("contracts", p.get("amount", 0))
                if contracts and float(contracts) != 0:
                    parsed_positions.append({
                        "Para": p.get("symbol", "-"),
                        "Strona": str(p.get("side", "-")).upper(),
                        "Ilość": float(contracts),
                        "Cena Wejścia": float(p.get("entryPrice", 0)),
                        "Dźwignia": int(p.get("leverage", 1)),
                        "PnL (USDT)": float(p.get("unrealizedPnL", 0))
                    })

    if parsed_positions:
        st.dataframe(pd.DataFrame(parsed_positions), use_container_width=True, hide_index=True)
    else:
        st.info("Brak otwartych pozycji futures na giełdzie.")

with col_tab2:
    st.markdown("### 📜 Historia Transakcji Bota")
    if "trade_history" in st.session_state and st.session_state.trade_history:
        st.dataframe(pd.DataFrame(st.session_state.trade_history), use_container_width=True, hide_index=True)
    else:
        st.info("Brak zarejestrowanych transakcji w tej sesji.")

# ==========================================
# PĘTLA AUTOMATYCZNEGO ODŚWIEŻANIA (AUTO-REFRESH)
# ==========================================
if st.session_state.scanner_active:
    time.sleep(scan_interval)
    st.rerun()

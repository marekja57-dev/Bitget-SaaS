from datetime import datetime
import hashlib
import json
import os
import sqlite3
import threading
import time
import ccxt
import pandas as pd
import streamlit as st
import stripe

st.set_page_config(
page_title="Bitget SAS - System Futures SaaS",
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
# INICJALIZACJA BAZY DANYCH SQLITE (PEŁNA SYNCHRONIZACJA PARAMETRÓW)
# =====================================================================
def init_db():
conn = sqlite3.connect(DB_FILE)
cursor = conn.cursor()
cursor.execute('''
CREATE TABLE IF NOT EXISTS users (
id INTEGER PRIMARY KEY AUTOINCREMENT,
email TEXT UNIQUE,
password TEXT,
is_admin INTEGER DEFAULT 0,
stripe_paid INTEGER DEFAULT 0,
api_key TEXT,
secret_key TEXT,
passphrase TEXT,
bot_active INTEGER DEFAULT 0,
sniper_active INTEGER DEFAULT 0,
bot_scan_pairs INTEGER DEFAULT 15,
max_active_positions INTEGER DEFAULT 5,
position_usdt_allocation INTEGER DEFAULT 50,
stop_loss_pct REAL DEFAULT 3.0,
take_profit_pct REAL DEFAULT 6.0,
spot_tf TEXT DEFAULT '1h'
)
''')

columns_to_check = [
("api_key", "TEXT"), ("secret_key", "TEXT"), ("passphrase", "TEXT"),
("stripe_paid", "INTEGER DEFAULT 0"), ("is_admin", "INTEGER DEFAULT 0"),
("bot_active", "INTEGER DEFAULT 0"), ("sniper_active", "INTEGER DEFAULT 0"),
("bot_scan_pairs", "INTEGER DEFAULT 15"), ("max_active_positions", "INTEGER DEFAULT 5"),
("position_usdt_allocation", "INTEGER DEFAULT 50"),
("stop_loss_pct", "REAL DEFAULT 3.0"), ("take_profit_pct", "REAL DEFAULT 6.0"),
("spot_tf", "TEXT DEFAULT '1h'")
]

for col, col_type in columns_to_check:
try:
cursor.execute(f"ALTER TABLE users ADD COLUMN {col} {col_type}")
except sqlite3.OperationalError:
pass

for adm_email in ADMIN_EMAILS:
cursor.execute("UPDATE users SET is_admin = 1, stripe_paid = 1 WHERE LOWER(TRIM(email)) = ?", (adm_email,))

conn.commit()
conn.close()

init_db()

def load_stripe_credentials():
if os.path.exists(STRIPE_CONFIG_FILE):
try:
with open(STRIPE_CONFIG_FILE, "r") as f:
data = json.load(f)
return data.get("stripe_pk", ""), data.get("stripe_sk", ""), data.get("stripe_price_id", "")
except Exception:
pass
return "", "", ""

def save_stripe_credentials(pk, sk, price_id):
try:
with open(STRIPE_CONFIG_FILE, "w") as f:
json.dump({"stripe_pk": pk, "stripe_sk": sk, "stripe_price_id": price_id}, f)
return True
except Exception:
return False

saved_stripe_pk, saved_stripe_sk, saved_stripe_price_id = load_stripe_credentials()
try:
stripe_pk_val = saved_stripe_pk or st.secrets.get("STRIPE_PK", "")
stripe_sk_val = saved_stripe_sk or st.secrets.get("STRIPE_SK", "")
stripe_price_id_val = saved_stripe_price_id or st.secrets.get("STRIPE_PRICE_ID", "")
except Exception:
stripe_pk_val = saved_stripe_pk or ""
stripe_sk_val = saved_stripe_sk or ""
stripe_price_id_val = saved_stripe_price_id or ""

if stripe_sk_val:
stripe.api_key = stripe_sk_val

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
if "seen_symbols" not in st.session_state:
st.session_state.seen_symbols = set()

if st.query_params.get("success") == "true":
if st.session_state.logged_in and st.session_state.user_id:
st.session_state.stripe_paid = True
try:
conn = sqlite3.connect(DB_FILE)
cursor = conn.cursor()
cursor.execute("UPDATE users SET stripe_paid = 1 WHERE id = ?", (st.session_state.user_id,))
conn.commit()
conn.close()
except Exception:
pass
st.success("🎉 Płatność zakończona sukcesem! Twoja subskrypcja została aktywowana.")
st.query_params.clear()

# =====================================================================
# STYLIZACJA WYGLĄDU
# =====================================================================
st.markdown(
""" <style>
@import url('https://fonts.googleapis.com/css2?family=Bungee+Inline&family=Cinzel:wght@700&display=swap');
.stApp { background-color: #0d0b0a; }
section[data-testid="stSidebar"] { background-color: #141110; border-right: 2px solid #3d2f1f; }
.hero-wrapper { display: flex; align-items: center; justify-content: center; width: 100%; padding-top: 50px; padding-bottom: 20px; }
.retro-ornate-frame { position: relative; background: radial-gradient(circle, #221a14 0%, #110d0a 100%); border: 6px double #f3d57a; padding: 40px 30px; border-radius: 16px; box-shadow: 0 0 50px rgba(243, 213, 122, 0.4), inset 0 0 35px rgba(0, 0, 0, 0.9); width: 100%; max-width: 600px; text-align: center; }
.retro-vintage-title { font-family: 'Bungee Inline', cursive, sans-serif; font-size: 3rem; color: #f3d57a; letter-spacing: 4px; text-shadow: 4px 4px 0px #8b0000, 8px 8px 0px rgba(0,0,0,0.95); margin-bottom: 10px; }
.retro-subtitle { font-family: 'Cinzel', serif; color: #e6c687; font-size: 1.1rem; letter-spacing: 2px; margin-bottom: 25px; }
div.stButton > button { background: linear-gradient(135deg, #1e4d2b 0%, #0f2b17 100%) !important; color: #f3d57a !important; border: 2px solid #f3d57a !important; font-family: 'Cinzel', serif !important; font-weight: 700 !important; font-size: 1rem !important; padding: 10px 24px !important; border-radius: 8px !important; box-shadow: 0 4px 15px rgba(0, 0, 0, 0.6) !important; transition: all 0.3s ease !important; }
div.stButton > button:hover { background: linear-gradient(135deg, #28663a 0%, #163d22 100%) !important; border-color: #ffe89d !important; color: #ffe89d !important; box-shadow: 0 0 20px rgba(243, 213, 122, 0.4) !important; transform: translateY(-2px); }

div[data-testid="stMetric"] {
border: 2px solid #f3d57a;
border-radius: 10px;
padding: 8px 12px;
background-color: rgba(243, 213, 122, 0.03);
box-shadow: 0 4px 12px rgba(0, 0, 0, 0.2);
min-height: 95px;
display: flex;
flex-direction: column;
justify-content: center;
}
div[data-testid="stMetric"] label { color: #f3d57a !important; font-size: 0.85rem !important; }
</style> """,
unsafe_allow_html=True,
)

# =====================================================================
# EKRAN LOGOWANIA / REJESTRACJI
# =====================================================================
if not st.session_state.logged_in:
st.markdown(
""" <div class="hero-wrapper"> <div class="retro-ornate-frame"> <div class="retro-vintage-title">BITGET SAS</div> <div class="retro-subtitle">AUTONOMICZNY SYSTEM FUTURES</div> """,
unsafe_allow_html=True,
)

tab_login, tab_register = st.tabs(["🔑 Zaloguj się", "📝 Załóż konto"])

with tab_login:
st.markdown("<p style='color: #f3d57a; font-family: Cinzel, serif;'>Logowanie do Panelu Klienta</p>", unsafe_allow_html=True)
login_email = st.text_input("Adres e-mail", key="log_email")
login_pass = st.text_input("Hasło", type="password", key="log_pass")

if st.button("ZALOGUJ SIĘ", use_container_width=True):
conn = sqlite3.connect(DB_FILE)
cursor = conn.cursor()
cursor.execute("SELECT id, email, password, is_admin, stripe_paid, api_key, secret_key, passphrase, bot_active, sniper_active, bot_scan_pairs, max_active_positions, position_usdt_allocation, stop_loss_pct, take_profit_pct, spot_tf FROM users WHERE LOWER(TRIM(email)) = ?", (login_email.strip().lower(),))
user_row = cursor.fetchone()
conn.close()

if user_row and user_row[2] == login_pass:
user_email_str = user_row[1].strip().lower()
is_admin_flag = True if user_email_str in ADMIN_EMAILS else bool(user_row[3])
stripe_paid_flag = True if is_admin_flag else bool(user_row[4])

st.session_state.logged_in = True
st.session_state.user_id = user_row[0]
st.session_state.user_email = user_row[1]
st.session_state.is_admin = is_admin_flag
st.session_state.stripe_paid = stripe_paid_flag
st.session_state.api_key = user_row[5] or ""
st.session_state.secret_key = user_row[6] or ""
st.session_state.passphrase = user_row[7] or ""
st.session_state.trend_bot_fut_active = bool(user_row[8])
st.session_state.new_listing_sniper_active = bool(user_row[9])
st.session_state.bot_scan_pairs = user_row[10] if user_row[10] is not None else 15
st.session_state.max_active_positions = user_row[11] if user_row[11] is not None else 5
st.session_state.position_usdt_allocation = user_row[12] if user_row[12] is not None else 50
st.session_state.stop_loss_pct = user_row[13] if user_row[13] is not None else 3.0
st.session_state.take_profit_pct = user_row[14] if user_row[14] is not None else 6.0
st.session_state.spot_tf = user_row[15] if user_row[15] is not None else '1h'
st.success("Zalogowano pomyślnie!")
st.rerun()
else:
st.error("Nieprawidłowy e-mail lub hasło.")

with tab_register:
st.markdown("<p style='color: #f3d57a; font-family: Cinzel, serif;'>Rejestracja Nowego Konta</p>", unsafe_allow_html=True)
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
"INSERT INTO users (email, password, is_admin, stripe_paid, position_usdt_allocation, stop_loss_pct, take_profit_pct, spot_tf) VALUES (?, ?, ?, ?, 50, 3.0, 6.0, '1h')",
(reg_email.strip(), reg_pass, is_adm, is_paid)
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
if "session_start_time" not in st.session_state:
st.session_state.session_start_time = datetime.now()
if "trade_history" not in st.session_state:
st.session_state.trade_history = []
if "signal_cooldown" not in st.session_state:
st.session_state.signal_cooldown = {}
if "scanner_active" not in st.session_state:
st.session_state.scanner_active = False
if "active_trades" not in st.session_state:
st.session_state.active_trades = {}
if "trend_bot_fut_active" not in st.session_state:
st.session_state.trend_bot_fut_active = False
if "new_listing_sniper_active" not in st.session_state:
st.session_state.new_listing_sniper_active = False
if "bot_scan_pairs" not in st.session_state:
st.session_state.bot_scan_pairs = 15
if "max_active_positions" not in st.session_state:
st.session_state.max_active_positions = 5
if "position_usdt_allocation" not in st.session_state:
st.session_state.position_usdt_allocation = 50
if "stop_loss_pct" not in st.session_state:
st.session_state.stop_loss_pct = 3.0
if "take_profit_pct" not in st.session_state:
st.session_state.take_profit_pct = 6.0
if "spot_tf" not in st.session_state:
st.session_state.spot_tf = "1h"

try:
conn = sqlite3.connect(DB_FILE)
cursor = conn.cursor()
cursor.execute("SELECT bot_active, sniper_active, bot_scan_pairs, max_active_positions, position_usdt_allocation, stop_loss_pct, take_profit_pct, spot_tf FROM users WHERE id = ?", (st.session_state.user_id,))
r = cursor.fetchone()
conn.close()
if r:
st.session_state.trend_bot_fut_active = bool(r[0])
st.session_state.new_listing_sniper_active = bool(r[1])
st.session_state.bot_scan_pairs = r[2] if r[2] is not None else 15
st.session_state.max_active_positions = r[3] if r[3] is not None else 5
st.session_state.position_usdt_allocation = r[4] if r[4] is not None else 50
st.session_state.stop_loss_pct = r[5] if r[5] is not None else 3.0
st.session_state.take_profit_pct = r[6] if r[6] is not None else 6.0
st.session_state.spot_tf = r[7] if r[7] is not None else "1h"
except Exception:
pass

def get_futures_exchange(api_key, secret_key, passphrase):
if not api_key:
return None
try:
exchange = ccxt.bitget({
"apiKey": api_key,
"secret": secret_key,
"password": passphrase,
"enableRateLimit": True,
"options": {
"defaultType": "swap",
"createOrder": {
"createMarketBuyOrderRequiresPrice": False
}
},
})
return exchange
except Exception:
return None

def calculate_dynamic_leverage(sym, current_vol, mode, manual_lev):
if "Ręczny" in mode:
return int(manual_lev)
if current_vol > 4.0:
return 3
elif current_vol > 2.5:
return 5
elif current_vol > 1.2:
return 8
else:
return 10

# =====================================================================
# WĄTEK TŁA (BACKGROUND WORKER - 24/7 NA HETZNERZE Z TWOIMI PARAMETRAMI)
# =====================================================================
BG_SEEN_SYMBOLS = {}
bg_lock = threading.Lock()

def background_trading_daemon():
while True:
try:
conn = sqlite3.connect(DB_FILE)
cursor = conn.cursor()
cursor.execute("SELECT id, email, api_key, secret_key, passphrase, bot_active, sniper_active, bot_scan_pairs, max_active_positions, position_usdt_allocation, stop_loss_pct, take_profit_pct, spot_tf FROM users WHERE (bot_active = 1 OR sniper_active = 1) AND api_key IS NOT NULL AND api_key != ''")
active_users = cursor.fetchall()
conn.close()

for user in active_users:
u_id, u_email, u_api, u_sec, u_pass, u_bot, u_snip, u_scan_pairs, u_max_pos, u_pos_alloc, u_sl, u_tp, u_tf = user
ex = get_futures_exchange(u_api, u_sec, u_pass)
if not ex:
continue

try:
tickers = ex.fetch_tickers()
current_symbols = set(tickers.keys())

with bg_lock:
if u_id not in BG_SEEN_SYMBOLS:
BG_SEEN_SYMBOLS[u_id] = current_symbols

# --- SNAJPER NOWYCH PAR (NEW LISTING SNIPER) ---
if u_snip:
with bg_lock:
seen_set = BG_SEEN_SYMBOLS[u_id]
new_symbols = [s for s in current_symbols if s not in seen_set and ("USDT" in s) and "BULL" not in s and "BEAR" not in s]
for sym in new_symbols:
try:
snip_lev = 3
ex.set_leverage(snip_lev, sym)
t_data = tickers.get(sym, {})
curr_price = float(t_data.get("last", 0) or t_data.get("close", 0))
if curr_price > 0:
budget = 20.0
contracts = (budget * snip_lev) / curr_price
try:
contracts_prec = float(ex.amount_to_precision(sym, contracts))
ex.create_order(sym, 'market', 'buy', contracts_prec)
except Exception:
ex.create_order(sym, 'market', 'buy', float(contracts))
except Exception:
pass
with bg_lock:
BG_SEEN_SYMBOLS[u_id].update(current_symbols)

# --- BOT TRENDU W TLE (Z UŻYCIEM TWOICH USTAWIEŃ SL/TP I TIMEFRAME) ---
if u_bot:
spot_tf = u_tf if u_tf else "1h"
max_active_pos = u_max_pos if u_max_pos is not None else 5
use_sltp = True
sl_pct = float(u_sl if u_sl is not None else 3.0)
tp_pct = float(u_tp if u_tp is not None else 6.0)
lev_mode = "🤖 Autonomiczny (max 10x)"
man_lev = 3
target_usdt_allocation = float(u_pos_alloc if u_pos_alloc is not None else 50.0)
risk_red = True
min_trade = 5.0
limit_pairs = u_scan_pairs if u_scan_pairs is not None else 15

positions = ex.fetch_positions()
for pos in positions:
contracts = float(pos.get("contracts", 0))
if contracts > 0:
sym = pos["symbol"]
side = pos.get("side", "")
try:
f_ohlcv = ex.fetch_ohlcv(sym, timeframe=spot_tf, limit=35)
f_df = pd.DataFrame(f_ohlcv, columns=["timestamp", "open", "high", "low", "close", "volume"])
f_df["macd"] = f_df["close"].ewm(span=12, adjust=False).mean() - f_df["close"].ewm(span=26, adjust=False).mean()
f_df["signal"] = f_df["macd"].ewm(span=9, adjust=False).mean()

# Weryfikacja zmiany trendu na co najmniej 2 ostatnich świecach, aby unikać fałszywych szumów
f_macd_curr = float(f_df["macd"].iloc[-1])
f_sig_curr = float(f_df["signal"].iloc[-1])
f_macd_prev = float(f_df["macd"].iloc[-2])
f_sig_prev = float(f_df["signal"].iloc[-2])

mark_price = float(pos.get("markPrice", 0))
entry_price = float(pos.get("entryPrice", 0))
leverage = float(pos.get("leverage", 1))

pnl_pct = 0.0
if entry_price > 0 and mark_price > 0:
if side == "long":
pnl_pct = ((mark_price - entry_price) / entry_price) * 100 * leverage
else:
pnl_pct = ((entry_price - mark_price) / entry_price) * 100 * leverage

should_close = False
if use_sltp:
if pnl_pct <= -sl_pct or pnl_pct >= tp_pct:
should_close = True

if not should_close:
# Potwierdzone przecięcie trendu na MACD (zarówno bieżąca jak i poprzednia świeca potwierdzają zmianę kierunku)
if side == "long" and (f_macd_curr < f_sig_curr and f_macd_prev <= f_sig_prev):
should_close = True
elif side == "short" and (f_macd_curr > f_sig_curr and f_macd_prev >= f_sig_prev):
should_close = True

if should_close:
close_side = "sell" if side == "long" else "buy"
ex.create_market_order(sym, close_side, contracts, params={"reduceOnly": True})
except Exception:
pass

f_bal = ex.fetch_balance()
fut_free = float(f_bal.get("free", {}).get("USDT", 0.0))
real_positions = [p for p in positions if float(p.get("contracts", 0)) > 0]
active_symbols = [p["symbol"] for p in real_positions]
current_count = len(active_symbols)

if current_count < max_active_pos and fut_free >= min_trade:
slots_avail = max_active_pos - current_count
best_candidates = sorted(
[s for s, d in tickers.items() if (s.endswith(":USDT") or "/USDT:USDT" in s) and "BULL" not in s and "BEAR" not in s and s not in active_symbols],
key=lambda x: tickers[x].get("quoteVolume", 0), reverse=True
)[:limit_pairs]

evaluated = []
for sym in best_candidates:
try:
f_ohlcv = ex.fetch_ohlcv(sym, timeframe=spot_tf, limit=50)
time.sleep(0.01)
f_df = pd.DataFrame(f_ohlcv, columns=["timestamp", "open", "high", "low", "close", "volume"])
f_df["volatility_pct"] = ((f_df["high"] - f_df["low"]) / f_df["close"]).rolling(14).mean() * 100
f_vol = float(f_df["volatility_pct"].iloc[-1]) if not pd.isna(f_df["volatility_pct"].iloc[-1]) else 2.0

f_df["macd"] = f_df["close"].ewm(span=12, adjust=False).mean() - f_df["close"].ewm(span=26, adjust=False).mean()
f_df["signal"] = f_df["macd"].ewm(span=9, adjust=False).mean()

f_macd = float(f_df["macd"].iloc[-1])
f_sig = float(f_df["signal"].iloc[-1])
f_price = float(f_df["close"].iloc[-1])

strength = abs(f_macd - f_sig) / f_price
side = "buy" if f_macd > f_sig else "sell"
evaluated.append({"symbol": sym, "price": f_price, "side": side, "strength": strength, "volatility": f_vol})
except Exception:
continue

top_signals = sorted(evaluated, key=lambda x: x["strength"], reverse=True)[:slots_avail]
for item in top_signals:
sym = item["symbol"]
if sym in active_symbols:
continue
f_price = item["price"]
side = item["side"]
f_vol = item["volatility"]

bot_lev = calculate_dynamic_leverage(sym, f_vol, lev_mode, man_lev)
max_budget = target_usdt_allocation

if risk_red:
r_mult = max(0.3, min(1.0, 2.0 / f_vol)) if f_vol > 0 else 1.0
budget = max_budget * r_mult
else:
budget = max_budget

budget = max(min_trade, budget)
if budget > fut_free:
budget = fut_free

if budget >= min_trade:
try:
ex.set_leverage(bot_lev, sym)
except Exception:
pass

contracts = (budget * bot_lev) / f_price
try:
contracts_prec = float(ex.amount_to_precision(sym, contracts))
ex.create_order(sym, 'market', side, contracts_prec)
except Exception:
ex.create_order(sym, 'market', side, float(contracts))
current_count += 1
if current_count >= max_active_pos:
break
except Exception:
pass
except Exception:
pass

time.sleep(3)

if "bg_thread_initialized" not in st.session_state:
st.session_state.bg_thread_initialized = True
daemon_thread = threading.Thread(target=background_trading_daemon, daemon=True)
daemon_thread.start()

# =====================================================================
# PANEL BOCZNY (SIDEBAR)
# =====================================================================
st.sidebar.markdown(f"### 👤 {st.session_state.user_email}")
if is_user_admin():
st.sidebar.markdown("🔴 **Rola: Administrator**")
else:
st.sidebar.markdown("🟢 **Rola: Klient SaaS**")

st.sidebar.markdown("---")
st.sidebar.markdown("### 💳 Strefa Subskrypcji")
if is_user_admin() or is_user_paid():
st.sidebar.success("✅ Subskrypcja aktywna (Dostęp Pełny)")
else:
st.sidebar.warning("⚠️ Brak aktywnej subskrypcji")
st.sidebar.link_button("💳 OPŁAĆ DOSTĘP (49 PLN)", "https://buy.stripe.com/00w00kecL1sfbCk0c13oA00")

if st.sidebar.button("🚪 WYLOGUJ SIĘ", use_container_width=True):
st.session_state.logged_in = False
st.session_state.user_email = ""
st.session_state.is_admin = False
st.session_state.stripe_paid = False
st.session_state.api_key = ""
st.session_state.secret_key = ""
st.session_state.passphrase = ""
st.rerun()

if is_user_admin():
with st.sidebar.expander("🛠️ Konfiguracja Stripe (Admin)"):
input_s_pk = st.text_input("Stripe Publishable Key", value=stripe_pk_val, type="password")
input_s_sk = st.text_input("Stripe Secret Key", value=stripe_sk_val, type="password")
input_s_price = st.text_input("Stripe Price ID", value=stripe_price_id_val)
if st.button("💾 Zapisz Konfigurację Stripe"):
if save_stripe_credentials(input_s_pk, input_s_sk, input_s_price):
st.success("Zapisano dane Stripe! Odśwież stronę.")
time.sleep(1)
st.rerun()
else:
st.error("Błąd zapisu pliku konfiguracyjnego.")

st.sidebar.markdown("---")
st.sidebar.markdown("### 🔑 Klucze API Bitget (Futures)")
input_api = st.sidebar.text_input("Bitget API Key", value=st.session_state.api_key, type="password")
input_secret = st.sidebar.text_input("Bitget Secret Key", value=st.session_state.secret_key, type="password")
input_pass = st.sidebar.text_input("Bitget Passphrase", value=st.session_state.passphrase, type="password")

if st.sidebar.button("💾 ZAPISZ MOJE KLUCZE", use_container_width=True):
if input_api and input_secret and input_pass:
st.session_state.api_key = input_api
st.session_state.secret_key = input_secret
st.session_state.passphrase = input_pass
conn = sqlite3.connect(DB_FILE)
cursor = conn.cursor()
cursor.execute(
"UPDATE users SET api_key = ?, secret_key = ?, passphrase = ? WHERE id = ?",
(input_api, input_secret, input_pass, st.session_state.user_id)
)
conn.commit()
conn.close()
st.success("✅ Klucze zapisane w bazie!")
st.rerun()
else:
st.error("Wypełnij wszystkie pola kluczy.")

futures_ex = get_futures_exchange(st.session_state.api_key, st.session_state.secret_key, st.session_state.passphrase)

st.sidebar.markdown("---")
st.sidebar.markdown("### 🔔 Powiadomienia Telegram")
enable_notifications = st.sidebar.checkbox("Włącz powiadomienia", value=True)
telegram_bot_token = st.sidebar.text_input("Telegram Bot Token", type="password")
telegram_chat_id = st.sidebar.text_input("Telegram Chat ID")

st.sidebar.markdown("---")
st.sidebar.markdown("### ⚙️ Ustawienia Futures")
def update_max_positions():
val = st.session_state.slider_max_pos
st.session_state.max_active_positions = val
try:
conn = sqlite3.connect(DB_FILE)
cursor = conn.cursor()
cursor.execute("UPDATE users SET max_active_positions = ? WHERE id = ?", (val, st.session_state.user_id))
conn.commit()
conn.close()
except Exception:
pass

max_active_futures_positions = st.sidebar.slider("📈 Maksymalna liczba aktywnych pozycji", 1, 20, value=st.session_state.max_active_positions, key="slider_max_pos", on_change=update_max_positions)

st.sidebar.markdown("---")
st.sidebar.markdown("### 💰 Alokacja Kapitału (USDT)")
def update_pos_allocation():
val = st.session_state.slider_pos_alloc
st.session_state.position_usdt_allocation = val
try:
conn = sqlite3.connect(DB_FILE)
cursor = conn.cursor()
cursor.execute("UPDATE users SET position_usdt_allocation = ? WHERE id = ?", (val, st.session_state.user_id))
conn.commit()
conn.close()
except Exception:
pass

position_usdt_allocation = st.sidebar.slider("Kwota na 1 pozycję (USDT)", 0, 200, value=st.session_state.position_usdt_allocation, step=5, key="slider_pos_alloc", on_change=update_pos_allocation)
risk_reduction_enabled = st.sidebar.checkbox("🧠 Inteligentna redukcja kapitału przy wysokim ryzyku (zmienności)", value=True)

st.sidebar.markdown("---")
st.sidebar.markdown("### 🛑 Zarządzanie Ryzykiem (SL / TP)")
def update_sltp_settings():
s_val = st.session_state.slider_sl
t_val = st.session_state.slider_tp
st.session_state.stop_loss_pct = s_val
st.session_state.take_profit_pct = t_val
try:
conn = sqlite3.connect(DB_FILE)
cursor = conn.cursor()
cursor.execute("UPDATE users SET stop_loss_pct = ?, take_profit_pct = ? WHERE id = ?", (s_val, t_val, st.session_state.user_id))
conn.commit()
conn.close()
except Exception:
pass

use_sltp = st.sidebar.checkbox("Włącz ochronę SL / TP", value=True)
stop_loss_pct = st.sidebar.slider("Stop Loss (%)", 0.5, 15.0, float(st.session_state.stop_loss_pct), 0.5, key="slider_sl", on_change=update_sltp_settings)
take_profit_pct = st.sidebar.slider("Take Profit (%)", 1.0, 50.0, float(st.session_state.take_profit_pct), 0.5, key="slider_tp", on_change=update_sltp_settings)

st.sidebar.markdown("---")
st.sidebar.markdown("### ⚡ Zarządzanie Dźwignią")
leverage_mode = st.sidebar.radio("Tryb Dźwigni", ["🤖 Autonomiczny (max 10x)", "🎛️ Ręczny"])
manual_leverage = st.sidebar.slider("Stała dźwignia Futures", 1, 10, 3)

# =====================================================================
# SNAJPER NOWYCH PAR (NEW LISTING AUTO-SNIPER)
# =====================================================================
st.sidebar.markdown("---")
st.sidebar.markdown("### 🎯 Snajper Nowych Par (New Listings)")
def toggle_sniper_cb():
new_s = st.session_state.cb_sniper_active
st.session_state.new_listing_sniper_active = new_s
try:
conn = sqlite3.connect(DB_FILE)
cursor = conn.cursor()
cursor.execute("UPDATE users SET sniper_active = ? WHERE id = ?", (1 if new_s else 0, st.session_state.user_id))
conn.commit()
conn.close()
except Exception:
pass

st.sidebar.checkbox("🚀 Auto-Snajper Nowych Tokenów", value=st.session_state.new_listing_sniper_active, key="cb_sniper_active", on_change=toggle_sniper_cb)
sniper_budget = st.sidebar.number_input("Budżet na nowy token (USDT)", min_value=5.0, value=20.0, step=5.0)
sniper_leverage = st.sidebar.slider("Dźwignia Snajpera Nowych Par", 1, 10, 3)

st.sidebar.markdown("---")
st.sidebar.markdown("### 🧠 Interwał Analizy")
def update_tf_setting():
tf_val = st.session_state.sel_tf
st.session_state.spot_tf = tf_val
try:
conn = sqlite3.connect(DB_FILE)
cursor = conn.cursor()
cursor.execute("UPDATE users SET spot_tf = ? WHERE id = ?", (tf_val, st.session_state.user_id))
conn.commit()
conn.close()
except Exception:
pass

tf_options = ["1m", "5m", "15m", "30m", "1h", "4h", "1d"]
default_tf_index = tf_options.index(st.session_state.spot_tf) if st.session_state.spot_tf in tf_options else 4
spot_tf = st.sidebar.selectbox("Interwał", tf_options, index=default_tf_index, key="sel_tf", on_change=update_tf_setting)

st.sidebar.markdown("---")
st.sidebar.markdown("### 🔄 Pętla Skanera w Tle")
scan_interval = st.sidebar.slider("Interwał odświeżania widoku (s)", 1, 300, 3)
max_fut_scan_pairs = st.sidebar.slider("📈 Liczba skanowanych par Futures (Widok)", 5, 50, 15, 5)

def update_bot_scan_pairs():
val = st.session_state.slider_bot_scan_pairs
st.session_state.bot_scan_pairs = val
try:
conn = sqlite3.connect(DB_FILE)
cursor = conn.cursor()
cursor.execute("UPDATE users SET bot_scan_pairs = ? WHERE id = ?", (val, st.session_state.user_id))
conn.commit()
conn.close()
except Exception:
pass

st.sidebar.slider("🤖 Liczba par dla Bota w Tle", 5, 50, value=st.session_state.bot_scan_pairs, step=5, key="slider_bot_scan_pairs", on_change=update_bot_scan_pairs)

st.sidebar.markdown("---")
emergency_kill = st.sidebar.button("🛑 ZAMKNIJ WSZYSTKO (KILL SWITCH)", type="primary", use_container_width=True)

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
futures_ex.create_market_order(sym, side, contracts, params={"reduceOnly": True})
except Exception:
pass
except Exception:
pass

st.session_state.trend_bot_fut_active = False
st.session_state.new_listing_sniper_active = False
try:
conn = sqlite3.connect(DB_FILE)
cursor = conn.cursor()
cursor.execute("UPDATE users SET bot_active = 0, sniper_active = 0 WHERE id = ?", (st.session_state.user_id,))
conn.commit()
conn.close()
except Exception:
pass

st.success("🚨 KILL SWITCH WYKONANY. Boty zatrzymane i pozycje zamknięte.")
time.sleep(2)
st.rerun()

# =====================================================================
# SALDO FUTURES
# =====================================================================
fut_free, fut_total = 0.0, 0.0
if futures_ex:
try:
f_bal = futures_ex.fetch_balance()
fut_free = float(f_bal.get("free", {}).get("USDT", 0.0))
fut_total = float(f_bal.get("total", {}).get("USDT", 0.0))
except Exception:
pass

total_unrealized_pnl = 0.0
active_positions_count = 0
exchange_positions = {}
if futures_ex:
try:
positions = futures_ex.fetch_positions()
for p in positions:
if float(p.get("contracts", 0)) > 0:
active_positions_count += 1
total_unrealized_pnl += float(p.get("unrealizedPnl", 0.0))
exchange_positions[p["symbol"]] = p
except Exception:
pass

# =====================================================================
# GŁÓWNE KAFELKI (4 W JEDNYM RZĘDZIE - WYROWNANE)
# =====================================================================
col1, col2, col3, col4 = st.columns(4)
with col1:
st.metric(
label="🔵 Portfel Futures",
value=f"{fut_total:.2f} USDT",
delta=f"Wolne: {fut_free:.2f} USDT"
)
with col2:
st.metric(
label="📊 Aktywne Pozycje",
value=f"{active_positions_count} / {max_active_futures_positions}",
delta=f"Wolne sloty: {max(0, max_active_futures_positions - active_positions_count)}"
)
with col3:
st.metric(
label="📈 Wynik Niezrealizowany",
value=f"{total_unrealized_pnl:+.2f} USDT",
delta="P/L na żywo"
)
with col4:
elapsed = datetime.now() - st.session_state.session_start_time
total_seconds = int(elapsed.total_seconds())
hours, remainder = divmod(total_seconds, 3600)
minutes, seconds = divmod(remainder, 60)
st.metric(
label="⏰ Czas Sesji",
value=f"{hours:02d}:{minutes:02d}:{seconds:02d}",
delta="Tło: 24/7 Aktywne"
)

st.markdown("---")

# =====================================================================
# PANEL STEROWANIA BOTAMI
# =====================================================================
col_bot1, col_bot2 = st.columns(2)
with col_bot1:
with st.container(border=True):
st.subheader("🥾 Bot Trendu Futures (Tło)")
def toggle_main_trend_fut():
new_state = st.session_state.main_cb_trend_fut
st.session_state.trend_bot_fut_active = new_state
try:
conn = sqlite3.connect(DB_FILE)
cursor = conn.cursor()
cursor.execute("UPDATE users SET bot_active = ? WHERE id = ?", (1 if new_state else 0, st.session_state.user_id))
conn.commit()
conn.close()
except Exception:
pass

st.checkbox("🔵 Ciągły Handlowiec Trendu", value=st.session_state.trend_bot_fut_active, key="main_cb_trend_fut", on_change=toggle_main_trend_fut)
if st.session_state.trend_bot_fut_active:
st.success("🟢 Aktywny w tle (24/7)")
else:
st.info("🔴 Zatrzymany")

with col_bot2:
with st.container(border=True):
st.subheader("🎯 Snajper Nowych Par (New Listings)")
def toggle_main_sniper():
new_state = st.session_state.main_cb_sniper
st.session_state.new_listing_sniper_active = new_state
try:
conn = sqlite3.connect(DB_FILE)
cursor = conn.cursor()
cursor.execute("UPDATE users SET sniper_active = ? WHERE id = ?", (1 if new_state else 0, st.session_state.user_id))
conn.commit()
conn.close()
except Exception:
pass

st.checkbox("🚀 Auto-Snajper Debiutów", value=st.session_state.new_listing_sniper_active, key="main_cb_sniper", on_change=toggle_main_sniper)
if st.session_state.new_listing_sniper_active:
st.success("🟢 Nasłuchuje nowych tokenów (24/7)")
else:
st.info("🔴 Zatrzymany")

st.markdown("---")

# =====================================================================
# CENTRALNY PRZYCISK STEROWANIA SKANEREM
# =====================================================================
col_btn, col_status = st.columns([2, 1])
with col_btn:
if not st.session_state.scanner_active:
if st.button("🚀 Uruchom Skaner w Pętli", type="primary", use_container_width=True):
st.session_state.scanner_active = True
st.rerun()
else:
if st.button("⏹️ Zatrzymaj Skaner", type="secondary", use_container_width=True):
st.session_state.scanner_active = False
st.rerun()
with col_status:
if st.session_state.scanner_active:
st.success("STATUS: SKANER AKTYWNY")
else:
st.error("STATUS: SKANER ZATRZYMANY")

st.markdown("---")

# =====================================================================
# WIDOK NA ŻYWO: SKANER PAR FUTURES
# =====================================================================
st.subheader("📈 Skaner Par Futures (Status i Pozycje)")
if futures_ex:
try:
f_tickers = futures_ex.fetch_tickers()
top_fut_view = sorted(
[sym for sym, data in f_tickers.items() if (sym.endswith(":USDT") or "/USDT:USDT" in sym) and "BULL" not in sym and "BEAR" not in sym],
key=lambda x: f_tickers[x].get("quoteVolume", 0), reverse=True
)[:max_fut_scan_pairs]
fut_data_list = []
for sym in top_fut_view:
t_data = f_tickers.get(sym, {})
pos = exchange_positions.get(sym)

side_val = "-"
lev_val = "-"
margin_val = "-"
pnl_val = "-"
status_desc = "⏳ Oczekująca"

if pos:
side_val = pos.get("side", "").upper()
lev_val = f"{float(pos.get('leverage', 1))}x"
notional = float(pos.get("notional", 0))
lev = float(pos.get('leverage', 1))
margin = notional / lev if lev > 0 else 0
margin_val = f"{margin:.2f} USDT" if margin > 0 else f"{float(pos.get('initialMargin', 0)):.2f} USDT"
pnl_val = f"{float(pos.get('unrealizedPnl', 0)):+.2f} USDT"
status_desc = "🟢 Aktywna (Pozycja Otwarta)"
else:
try:
f_ohlcv = futures_ex.fetch_ohlcv(sym, timeframe=spot_tf, limit=30)
time.sleep(0.01)
f_df = pd.DataFrame(f_ohlcv, columns=["timestamp", "open", "high", "low", "close", "volume"])
f_df["volatility_pct"] = ((f_df["high"] - f_df["low"]) / f_df["close"]).rolling(14).mean() * 100
f_vol = float(f_df["volatility_pct"].iloc[-1]) if not pd.isna(f_df["volatility_pct"].iloc[-1]) else 2.0

f_df["macd"] = f_df["close"].ewm(span=12, adjust=False).mean() - f_df["close"].ewm(span=26, adjust=False).mean()
f_df["signal"] = f_df["macd"].ewm(span=9, adjust=False).mean()

f_macd = float(f_df["macd"].iloc[-1])
f_sig = float(f_df["signal"].iloc[-1])

side_val = "LONG" if f_macd > f_sig else "SHORT"
lev_num = calculate_dynamic_leverage(sym, f_vol, leverage_mode, manual_leverage)
lev_val = f"{lev_num}x"
margin_val = "-"
pnl_val = "Oczekiwanie"
status_desc = "⚡ Sygnał Gotowy"
except Exception:
lev_val = f"{manual_leverage}x"

fut_data_list.append({
"Para": sym,
"Cena": f"{float(t_data.get('last', 0)):.4f}",
"Zmiana 24h": f"{float(t_data.get('percentage', 0)):+.2f}%",
"Wolumen (USDT)": f"{float(t_data.get('quoteVolume', 0)):,.0f}",
"Strategia": "Futures Trend + New Listing Sniper",
"Strona": side_val,
"Dźwignia": lev_val,
"Marża": margin_val,
"Wynik PnL": pnl_val,
"Status": status_desc
})
if fut_data_list:
st.dataframe(pd.DataFrame(fut_data_list), use_container_width=True)
else:
st.info("Brak danych Futures do wyświetlenia.")
except Exception:
st.info("Brak danych rynkowych Futures.")
else:
st.info("Skonfiguruj klucze API Futures, aby widzieć skaner.")

st.markdown("---")
st.subheader("📜 Dziennik Transakcji w Sesji")
if st.session_state.trade_history:
st.dataframe(pd.DataFrame(st.session_state.trade_history), use_container_width=True)
else:
st.info("Brak transakcji zarejestrowanych w tej sesji przeglądarki.")

time.sleep(scan_interval)
st.rerun()

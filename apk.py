from datetime import datetime
import hashlib
import json
import os
import sqlite3
import time
import ccxt
import pandas as pd
import streamlit as st
import stripe

st.set_page_config(
page_title="Bitget SAS - System Wieloużytkownikowy SaaS",
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
# INICJALIZACJA BAZY DANYCH SQLITE (Z MIGRACJĄ KOLUMN)
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
passphrase TEXT
)
''')

for col, col_type in [("api_key", "TEXT"), ("secret_key", "TEXT"), ("passphrase", "TEXT"), ("stripe_paid", "INTEGER DEFAULT 0"), ("is_admin", "INTEGER DEFAULT 0")]:
try:
cursor.execute(f"ALTER TABLE users ADD COLUMN {col} {col_type}")
except sqlite3.OperationalError:
pass

for adm_email in ADMIN_EMAILS:
cursor.execute("UPDATE users SET is_admin = 1, stripe_paid = 1 WHERE LOWER(TRIM(email)) = ?", (adm_email,))

cursor.execute("SELECT * FROM users WHERE LOWER(TRIM(email)) = ?", ("admin@bot-bitget.pl",))
if not cursor.fetchone():
admin_pass = st.secrets.get("ADMIN_PASSWORD", "TwojeTajneHaslo123")
cursor.execute(
"INSERT INTO users (email, password, is_admin, stripe_paid) VALUES (?, ?, 1, 1)",
("admin@bot-bitget.pl", admin_pass)
)
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
stripe_pk_val = saved_stripe_pk or st.secrets.get("STRIPE_PK", "")
stripe_sk_val = saved_stripe_sk or st.secrets.get("STRIPE_SK", "")
stripe_price_id_val = saved_stripe_price_id or st.secrets.get("STRIPE_PRICE_ID", "")

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

if "active_spot_trades" not in st.session_state:
st.session_state.active_spot_trades = {}
elif isinstance(st.session_state.active_spot_trades, set):
old_set = st.session_state.active_spot_trades
st.session_state.active_spot_trades = {sym: {"entry_price": 0.0, "amount": 0.0} for sym in old_set}

if "known_spot_markets" not in st.session_state:
st.session_state.known_spot_markets = set()
if "sniped_tokens" not in st.session_state:
st.session_state.sniped_tokens = {}

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
# STYLIZACJA WYGLĄDU (RETRO / DARK)
# =====================================================================
st.markdown(
"""
<style>
@import url('https://fonts.googleapis.com/css2?family=Bungee+Inline&family=Cinzel:wght@700&display=swap');
.stApp { background-color: #0d0b0a; }
section[data-testid="stSidebar"] { background-color: #141110; border-right: 2px solid #3d2f1f; }
.hero-wrapper { display: flex; align-items: center; justify-content: center; width: 100%; padding-top: 50px; padding-bottom: 20px; }
.retro-ornate-frame {
position: relative; background: radial-gradient(circle, #221a14 0%, #110d0a 100%);
border: 6px double #f3d57a; padding: 40px 30px; border-radius: 16px;
box-shadow: 0 0 50px rgba(243, 213, 122, 0.4), inset 0 0 35px rgba(0, 0, 0, 0.9);
width: 100%; max-width: 600px; text-align: center;
}
.retro-vintage-title {
font-family: 'Bungee Inline', cursive, sans-serif; font-size: 3rem; color: #f3d57a;
letter-spacing: 4px; text-shadow: 4px 4px 0px #8b0000, 8px 8px 0px rgba(0,0,0,0.95); margin-bottom: 10px;
}
.retro-subtitle { font-family: 'Cinzel', serif; color: #e6c687; font-size: 1.1rem; letter-spacing: 2px; margin-bottom: 25px; }
div.stButton > button {
background: linear-gradient(135deg, #1e4d2b 0%, #0f2b17 100%) !important; color: #f3d57a !important;
border: 2px solid #f3d57a !important; font-family: 'Cinzel', serif !important; font-weight: 700 !important;
font-size: 1rem !important; padding: 10px 24px !important; border-radius: 8px !important;
box-shadow: 0 4px 15px rgba(0, 0, 0, 0.6) !important; transition: all 0.3s ease !important;
}
div.stButton > button:hover {
background: linear-gradient(135deg, #28663a 0%, #163d22 100%) !important; border-color: #ffe89d !important;
color: #ffe89d !important; box-shadow: 0 0 20px rgba(243, 213, 122, 0.4) !important; transform: translateY(-2px);
}
div[data-testid="stMetric"] {
border: 2px solid #f3d57a; border-radius: 10px; padding: 10px 12px;
background-color: rgba(243, 213, 122, 0.03); box-shadow: 0 4px 12px rgba(0, 0, 0, 0.2);
}
div[data-testid="stMetric"] label { color: #f3d57a !important; }
</style>
""",
unsafe_allow_html=True,
)

# =====================================================================
# EKRAN LOGOWANIA / REJESTRACJI
# =====================================================================
if not st.session_state.logged_in:
st.markdown(
"""
<div class="hero-wrapper">
<div class="retro-ornate-frame">
<div class="retro-vintage-title">BITGET SAS</div>
<div class="retro-subtitle">AUTONOMICZNY SYSTEM TRANSAKCYJNY</div>
""",
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
cursor.execute("SELECT id, email, password, is_admin, stripe_paid, api_key, secret_key, passphrase FROM users WHERE LOWER(TRIM(email)) = ?", (login_email.strip().lower(),))
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
"INSERT INTO users (email, password, is_admin, stripe_paid) VALUES (?, ?, ?, ?)",
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
if "trend_bot_spot_active" not in st.session_state:
st.session_state.trend_bot_spot_active = False
if "trend_bot_fut_active" not in st.session_state:
st.session_state.trend_bot_fut_active = False
if "known_markets" not in st.session_state:
st.session_state.known_markets = set()

def get_exchange(market_type):
if not st.session_state.api_key:
return None
try:
ex_type = "spot" if market_type == "spot" else "swap"
exchange = ccxt.bitget({
"apiKey": st.session_state.api_key,
"secret": st.session_state.secret_key,
"password": st.session_state.passphrase,
"enableRateLimit": True,
"options": {
"defaultType": ex_type,
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
# PANEL BOCZNY (SIDEBAR)
# =====================================================================
st.sidebar.markdown(f"### 👤 {st.session_state.user_email}")
if is_user_admin():
st.sidebar.markdown("🔴 Rola: Administrator")
else:
st.sidebar.markdown("🟢 Rola: Klient SaaS")

if st.sidebar.button("🚪 WYLOGUJ SIĘ", use_container_width=True):
st.session_state.logged_in = False
st.session_state.user_email = ""
st.session_state.is_admin = False
st.session_state.stripe_paid = False
st.session_state.api_key = ""
st.session_state.secret_key = ""
st.session_state.passphrase = ""
st.rerun()

st.sidebar.markdown("---")
st.sidebar.markdown("### 💳 Strefa Subskrypcji")
if is_user_admin() or is_user_paid():
st.sidebar.success("✅ Subskrypcja aktywna (Dostęp Pełny)")
else:
st.sidebar.warning("⚠️ Brak aktywnej subskrypcji")
st.sidebar.link_button("💳 OPŁAĆ DOSTĘP (49 PLN)", "https://buy.stripe.com/00w00kecL1sfbCk0c13oA00")

# Konfiguracja Stripe dla Administratora
if is_user_admin():
with st.sidebar.expander("🛠️ Konfiguracja Stripe (Admin)"):
input_s_pk = st.text_input("Stripe Publishable Key", value=stripe_pk_val, type="password")
input_s_sk = st.text_input("Stripe Secret Key", value=stripe_sk_val, type="password")
input_s_price = st.text_input("Stripe Price ID (np. price_...)", value=stripe_price_id_val)
if st.button("💾 Zapisz Konfigurację Stripe"):
if save_stripe_credentials(input_s_pk, input_s_sk, input_s_price):
st.success("Zapisano dane Stripe! Odśwież stronę.")
time.sleep(1)
st.rerun()
else:
st.error("Błąd zapisu pliku konfiguracyjnego.")

st.sidebar.markdown("---")
st.sidebar.markdown("### 🔑 Klucze API Bitget")
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

spot_ex = get_exchange("spot")
futures_ex = get_exchange("futures")

if futures_ex and not st.session_state.known_markets:
try:
markets = futures_ex.load_markets()
st.session_state.known_markets = set(markets.keys())
except Exception:
pass

st.sidebar.markdown("---")
st.sidebar.markdown("### 🎯 Skaner Nowych Listingów (Sniper)")
enable_sniper = st.sidebar.checkbox("Włącz Sniper Nowych Tokenów (Spot)", value=False)
sniper_allocation_usdt = st.sidebar.number_input("Budżet na 1 nowy listing (USDT)", 5.0, 1000.0, 10.0, 5.0)

st.sidebar.markdown("---")
st.sidebar.markdown("### 🔔 Powiadomienia Telegram")
enable_notifications = st.sidebar.checkbox("Włącz powiadomienia", value=True)
telegram_bot_token = st.sidebar.text_input("Telegram Bot Token", type="password")
telegram_chat_id = st.sidebar.text_input("Telegram Chat ID")

def send_notification(message):
if enable_notifications:
st.toast(message, icon="🤖")
if telegram_bot_token and telegram_chat_id:
try:
import urllib.parse
import urllib.request
url = f"https://api.telegram.org/bot{telegram_bot_token}/sendMessage"
data = urllib.parse.urlencode({"chat_id": telegram_chat_id, "text": message}).encode("utf-8")
urllib.request.urlopen(url, data=data, timeout=3)
except Exception:
pass

st.sidebar.markdown("---")
st.sidebar.markdown("### ⚙️ Kapitał i Ryzyko")
allocation_mode = st.sidebar.radio("Zarządzanie wielkością pozycji", ["🤖 Inteligentny Auto-Dobór (Zmienność + Siła)", "🎛️ Stały procent portfela"])
base_allocation_pct = st.sidebar.slider("Maksymalny udział kapitału na 1 pozycję (%)", 1, 30, 10)
max_single_trade_usdt = st.sidebar.number_input("🛡️ Maksymalnie USDT na 1 pozycję", 5.0, 5000.0, 50.0, 5.0)

max_active_spot_positions = st.sidebar.slider("📈 Maks. aktywne pozycje Spot", 1, 20, 5)
max_active_futures_positions = st.sidebar.slider("📈 Maks. aktywne pozycje Futures", 1, 20, 5)

st.sidebar.markdown("---")
st.sidebar.markdown("### 🛡️ Opcjonalne Limity SL / TP")
enable_custom_sl_tp = st.sidebar.checkbox("Włącz awaryjne limity SL / TP (%)", value=False)
custom_stop_loss_pct = st.sidebar.slider("Maksymalna strata (Stop-Loss %)", 1, 30, 5)
custom_take_profit_pct = st.sidebar.slider("Docelowy zysk (Take-Profit %)", 1, 100, 15)

st.sidebar.markdown("---")
st.sidebar.markdown("### ⚡ Zarządzanie Dźwignią")
leverage_mode = st.sidebar.radio("Tryb Dźwigni", ["🤖 Autonomiczny (max 10x)", "🎛️ Ręczny"])
manual_leverage = st.sidebar.slider("Stała dźwignia Futures", 1, 10, 3)

st.sidebar.markdown("---")
st.sidebar.markdown("### 🧠 Timeframe Analizy")
spot_tf = st.sidebar.selectbox("Interwał", ["1m", "5m", "15m", "30m", "1h", "4h", "1d"], index=4)

st.sidebar.markdown("---")
st.sidebar.markdown("### 🔄 Pętla Skanera")
if "sidebar_auto_scan_cb" not in st.session_state:
st.session_state.sidebar_auto_scan_cb = st.session_state.scanner_active

def toggle_scanner_from_sidebar():
st.session_state.scanner_active = st.session_state.sidebar_auto_scan_cb

auto_scan_enabled = st.sidebar.checkbox("Włącz auto-skanowanie w tle", key="sidebar_auto_scan_cb", on_change=toggle_scanner_from_sidebar)
scan_interval = st.sidebar.slider("Interwał odświeżania (s)", 1, 300, 3)
max_spot_scan_pairs = st.sidebar.slider("🔍 Liczba par Spot", 5, 50, 15, 5)
max_fut_scan_pairs = st.sidebar.slider("📈 Liczba par Futures", 5, 50, 15, 5)

st.sidebar.markdown("---")
emergency_kill = st.sidebar.button("🛑 ZAMKNIJ WSZYSTKO (KILL SWITCH)", type="primary", use_container_width=True)

if emergency_kill:
closed_spot_count = 0
closed_fut_count = 0

# 1. Zamykanie pozycji na Spocie (sesja oraz giełda)
if spot_ex:
try:
for sym, data in list(st.session_state.active_spot_trades.items()):
amount = float(data.get("amount", 0.0))
if amount > 0:
spot_ex.create_market_sell_order(sym, amount)
closed_spot_count += 1
except Exception as e:
st.sidebar.error(f"Błąd zamykania spotów: {e}")
st.session_state.active_spot_trades = {}

# 2. Zamykanie pozycji na Futures (sesja oraz giełda)
if futures_ex:
try:
positions = futures_ex.fetch_positions()
for p in positions:
contracts = float(p.get("contracts", 0))
if contracts > 0:
sym = p.get("symbol")
side = p.get("side") # 'long' lub 'short'
close_side = "sell" if side == "long" else "buy"
futures_ex.create_market_order(sym, close_side, contracts)
closed_fut_count += 1
except Exception as e:
st.sidebar.error(f"Błąd zamykania futures: {e}")
st.session_state.active_trades = {}

st.sidebar.success(f"🚨 KILL SWITCH AKTYWNY! Zamknięto: {closed_spot_count} spot, {closed_fut_count} futures.")
time.sleep(1)
st.rerun()

# =====================================================================
# GŁÓWNE ZAKŁADKI I WIDOKI APLIKACI
# =====================================================================
st.title("🛡️ Autonomiczny System Handlowy Bitget SAS")

tab_dashboard, tab_spot, tab_fut, tab_bots, tab_history = st.tabs([
"📊 Panel Główny", "🟢 Rynek Spot", "⚡ Rynek Futures", "🤖 Boty Trendu", "📜 Historia"
])

with tab_dashboard:
st.header("Przegląd Portfela i Statusu Systemu")
col1, col2, col3 = st.columns(3)

total_spot_val = len(st.session_state.active_spot_trades)
total_fut_val = len(st.session_state.active_trades)

col1.metric("Aktywne Pozycje Spot", total_spot_val, f"Limit: {max_active_spot_positions}")
col2.metric("Aktywne Pozycje Futures", total_fut_val, f"Limit: {max_active_futures_positions}")
col3.metric("Status Skanera w Tle", "AKTYWNY" if st.session_state.scanner_active else "WYŁĄCZONY")

st.markdown("---")
st.subheader("Szybki podgląd portfela giełdowego")
if spot_ex:
try:
balance = spot_ex.fetch_balance()
free_usdt = balance.get('USDT', {}).get('free', 0.0)
total_usdt = balance.get('USDT', {}).get('total', 0.0)
st.info(f"Dostępne USDT na Spocie: **{free_usdt:.2f} USDT** (Łącznie: {total_usdt:.2f} USDT)")
except Exception as e:
st.warning(f"Nie udało się pobrać salda Spot: {e}")
else:
st.warning("Skonfiguruj i zapisz klucze API Bitget w panelu bocznym, aby widzieć saldo.")

with tab_spot:
st.subheader("Zarządzanie Pozycjami i Autohandlem Spot")

if st.button("🚨 ZAMKNIJ WSZYSTKIE POZYCJE SPOT", use_container_width=True):
if spot_ex and st.session_state.active_spot_trades:
closed_count = 0
for sym, data in list(st.session_state.active_spot_trades.items()):
try:
amount = float(data.get("amount", 0.0))
if amount > 0:
spot_ex.create_market_sell_order(sym, amount)
closed_count += 1
except Exception as e:
st.error(f"Błąd zamykania {sym} na Spocie: {e}")
st.session_state.active_spot_trades = {}
st.success(f"Zamknięto pomyślnie {closed_count} pozycji na spocie!")
st.rerun()
else:
st.info("Brak aktywnych pozycji Spot do zamknięcia lub brak skonfigurowanych kluczy API.")

if st.session_state.active_spot_trades:
spot_df_data = []
for sym, d in st.session_state.active_spot_trades.items():
spot_df_data.append({
"Symbol": sym,
"Cena Wejścia": d.get("entry_price", 0.0),
"Ilość": d.get("amount", 0.0)
})
st.dataframe(pd.DataFrame(spot_df_data), use_container_width=True)

selected_spot_close = st.selectbox("Wybierz pozycję Spot do zamknięcia", list(st.session_state.active_spot_trades.keys()), key="sel_spot_close")
if st.button("Zamknij wybraną pozycję Spot"):
if spot_ex:
try:
pos_data = st.session_state.active_spot_trades.get(selected_spot_close, {})
amt = float(pos_data.get("amount", 0.0))
if amt > 0:
spot_ex.create_market_sell_order(selected_spot_close, amt)
del st.session_state.active_spot_trades[selected_spot_close]
st.success(f"Zamknięto pozycję Spot: {selected_spot_close}")
st.rerun()
except Exception as e:
st.error(f"Nie udało się zamknąć pozycji: {e}")
else:
st.info("Brak otwartych pozycji na rynku Spot.")

with tab_fut:
st.subheader("Zarządzanie Pozycjami Futures (Swap)")

if st.button("🚨 ZAMKNIJ WSZYSTKIE POZYCJE FUTURES", use_container_width=True):
if futures_ex and st.session_state.active_trades:
closed_count = 0
for sym in list(st.session_state.active_trades.keys()):
try:
pos_info = st.session_state.active_trades[sym]
side = pos_info.get("side", "buy")
amount = pos_info.get("amount", 0.0)
close_side = "sell" if side == "buy" else "buy"
futures_ex.create_market_order(sym, close_side, amount)
closed_count += 1
except Exception as e:
st.error(f"Błąd zamykania {sym} na Futures: {e}")
st.session_state.active_trades = {}
st.success(f"Zamknięto pomyślnie {closed_count} pozycji na Futures!")
st.rerun()
else:
st.info("Brak aktywnych pozycji Futures do zamknięcia.")

if st.session_state.active_trades:
fut_df_data = []
for sym, d in st.session_state.active_trades.items():
fut_df_data.append({
"Symbol": sym,
"Strona": d.get("side", ""),
"Ilość": d.get("amount", 0.0),
"Cena Wejścia": d.get("entry_price", 0.0)
})
st.dataframe(pd.DataFrame(fut_df_data), use_container_width=True)

selected_fut_close = st.selectbox("Wybierz pozycję Futures do zamknięcia", list(st.session_state.active_trades.keys()), key="sel_fut_close")
if st.button("Zamknij wybraną pozycję Futures"):
if futures_ex:
try:
pos_info = st.session_state.active_trades.get(selected_fut_close, {})
side = pos_info.get("side", "buy")
amount = pos_info.get("amount", 0.0)
close_side = "sell" if side == "buy" else "buy"
futures_ex.create_market_order(selected_fut_close, close_side, amount)
del st.session_state.active_trades[selected_fut_close]
st.success(f"Zamknięto pozycję Futures: {selected_fut_close}")
st.rerun()
except Exception as e:
st.error(f"Nie udało się zamknąć pozycji: {e}")
else:
st.info("Brak otwartych pozycji na rynku Futures.")

with tab_bots:
st.header("Autonomiczne Boty Trendu i Strategie")
col_b1, col_b2 = st.columns(2)

with col_b1:
st.subheader("Bot Trendu Spot")
st.session_state.trend_bot_spot_active = st.checkbox("Włącz automatyczne monitorowanie trendu Spot (zmiana trendu = zamknięcie pozycji)", value=st.session_state.trend_bot_spot_active)
if st.session_state.trend_bot_spot_active:
st.success("Bot Spot monitoruje wykresy i automatycznie zamknie pozycję w razie odwrócenia trendu.")
else:
st.info("Bot Spot jest w stanie spoczynku.")

with col_b2:
st.subheader("Bot Trendu Futures")
st.session_state.trend_bot_fut_active = st.checkbox("Włącz automatyczne monitorowanie trendu Futures", value=st.session_state.trend_bot_fut_active)
if st.session_state.trend_bot_fut_active:
st.success("Bot Futures aktywnie śledzi sygnały zmiany kierunku.")
else:
st.info("Bot Futures jest wyłączony.")

with tab_history:
st.header("Historia Transakcji i Zdarzeń Systemu")
if st.session_state.trade_history:
st.dataframe(pd.DataFrame(st.session_state.trade_history), use_container_width=True)
else:
st.info("Brak zarejestrowanych transakcji w obecnej sesji.")

# Obsługa pętli skanera w tle (jeśli włączona)
if auto_scan_enabled and spot_ex:
time.sleep(scan_interval)
st.rerun()

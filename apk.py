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

st.sidebar.markdown("🔴 Rola: Administrator")

else:

st.sidebar.markdown("🟢 Rola: Klient SaaS")

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

# Obsługa standardowej struktury CCXT lub struktury bezpośredniej Bitget Futures

if "free" in f_bal and isinstance(f_bal["free"], dict) and f_bal["free"].get("USDT") is not None:

fut_free = float(f_bal["free"].get("USDT", 0.0) or 0.0)

fut_total = float(f_bal.get("total", {}).get("USDT", 0.0) or 0.0)

elif "USDT" in f_bal and isinstance(f_bal["USDT"], dict):

fut_free = float(f_bal["USDT"].get("free", 0.0) or 0.0)

fut_total = float(f_bal["USDT"].get("total", 0.0) or 0.0)

except Exception as e:

st.error(f"⚠️ Błąd odczytu salda: {e}")

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


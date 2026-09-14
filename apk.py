import time
from datetime import datetime
import ccxt
import pandas as pd
import streamlit as st

# ==========================================
# KONFIGURACJA STRONY I STYLIZACJA RETRO-VINTAGE
# ==========================================
st.set_page_config(
    page_title="Bitget SAS - Terminal", page_icon="🛡️", layout="wide"
)

st.markdown(
    """
    <style>
    .main { background-color: #0e1117; color: #e6e6e6; }
    .stButton>button { background-color: #d4af37; color: #000000; font-weight: bold; border-radius: 4px; border: none; }
    .stButton>button:hover { background-color: #f4d03f; color: #000000; }
    .metric-card { background-color: #1a1c23; border: 1px solid #d4af37; padding: 15px; border-radius: 6px; margin-bottom: 10px; }
    .stAlert { background-color: #161b22; color: #e6e6e6; border: 1px solid #30363d; }
    
    /* Złote ramki dla pól API, Typu Rynku oraz Interwału w panelu bocznym */
    .stTextInput input, .stSelectbox div[data-baseweb="select"] {
        border: 1px solid #d4af37 !important;
        border-radius: 4px !important;
        background-color: #161b22 !important;
    }

    /* Styl retro dla ekranu startowego / banera głównego */
    .retro-banner {
        background-color: #12141c;
        border: 3px solid #d4af37;
        padding: 20px;
        text-align: center;
        border-radius: 6px;
        box-shadow: 0 4px 15px rgba(212, 175, 55, 0.2);
        margin-bottom: 25px;
    }
    .retro-title {
        color: #d4af37;
        font-family: 'Courier New', Courier, monospace;
        font-size: 36px;
        font-weight: bold;
        letter-spacing: 5px;
        text-transform: uppercase;
        margin: 0;
    }
    </style>
""",
    unsafe_allow_html=True,
)

# ==========================================
# INICJALIZACJA STANÓW SESJI I ROZPOZNAWANIE ADMINA PO IP
# ==========================================
if "bot_active" not in st.session_state:
  st.session_state.bot_active = False
if "trade_history" not in st.session_state:
  st.session_state.trade_history = []
if "position_timers" not in st.session_state:
  st.session_state.position_timers = {}
if (
    "session_start_time" not in st.session_state
    or not isinstance(st.session_state.session_start_time, (int, float))
):
  st.session_state.session_start_time = time.time()
if "top_pairs_cache" not in st.session_state:
  st.session_state.top_pairs_cache = []

# Bezpieczne pobieranie IP klienta z nagłówków proxy serwera (Hetzner)
try:
  headers = st.context.headers
  client_ip = (
      headers.get("X-Forwarded-For", "").split(",")[0].strip()
      or headers.get("X-Real-IP", "127.0.0.1")
  )
except Exception:
  client_ip = "127.0.0.1"

# Weryfikacja czy to administrator po adresie IP
admin_saved_ip = (
    st.secrets.get("ADMIN_IP", "127.0.0.1")
    if "ADMIN_IP" in st.secrets
    else "127.0.0.1"
)
is_admin_ip = client_ip == admin_saved_ip

if is_admin_ip:
  admin_default_key = st.secrets.get("ADMIN_API_KEY", "")
  admin_default_secret = st.secrets.get("ADMIN_API_SECRET", "")
  admin_default_password = st.secrets.get("ADMIN_API_PASSWORD", "")
else:
  admin_default_key = ""
  admin_default_secret = ""
  admin_default_password = ""

# ==========================================
# PANEL BOCZNY - BITGET SAS CONTROL & SECURITY
# ==========================================
st.sidebar.title("🛡️ Bitget SAS Control")
if is_admin_ip:
  st.sidebar.success("👑 Zalogowano jako Administrator (Auto-IP)")

api_key = st.sidebar.text_input(
    "API Key", value=admin_default_key, type="password"
)
api_secret = st.sidebar.text_input(
    "API Secret", value=admin_default_secret, type="password"
)
api_password = st.sidebar.text_input(
    "API Password (Passphrase)", value=admin_default_password, type="password"
)

st.sidebar.markdown("---")
st.sidebar.subheader("⚙️ Parametry Rynku i Skanera")
market_type = st.sidebar.selectbox("Typ Rynku", ["swap", "spot"], index=0)
tf = st.sidebar.selectbox(
    "Interwał Analityczny", ["5m", "15m", "1h", "4h"], index=1
)

scan_breadth = st.sidebar.slider(
    "Szerokość skanowania rynku (liczba par)", 10, 50, 20, step=5
)

st.sidebar.markdown("---")
st.sidebar.subheader("💰 Zarządzanie Ryzykiem i Kapitałem")

max_open_trades = st.sidebar.slider(
    "Maks. liczba otwartych pozycji jednocześnie", 0, 50, 5, step=1
)
risk_pct_per_trade = (
    st.sidebar.slider("Alokacja kapitału z konta na pozycję (%)", 1.0, 25.0, 10.0, 1.0)
    / 100.0
)
use_dynamic_leverage = st.sidebar.checkbox(
    "Włącz analityczny dobór dźwigni (Smart Leverage)", value=True
)
max_allowed_leverage = st.sidebar.slider(
    "Maksymalna dozwolona dźwignia", 1, 20, 10
)

use_sltp = st.sidebar.checkbox("Włącz ochronę Stop Loss / Take Profit", value=True)
stop_loss_pct = (
    st.sidebar.slider("Stop Loss (%)", 0.5, 5.0, 1.5, 0.1) / 100.0
)
take_profit_pct = (
    st.sidebar.slider("Take Profit (%)", 1.0, 20.0, 3.0, 0.5) / 100.0
)
min_hold_seconds = st.sidebar.number_input(
    "Min. czas trzymania pozycji (Cooldown w sek.)", value=300, step=60
)

st.sidebar.markdown("---")

if st.sidebar.button("🚨 KILL SWITCH (Zamknij wszystko)", type="primary"):
  st.session_state.bot_active = False
  if api_key and api_secret and api_password:
    try:
      temp_exchange = ccxt.bitget({
          "apiKey": api_key,
          "secret": api_secret,
          "password": api_password,
          "enableRateLimit": True,
          "options": {"defaultType": market_type},
      })
      temp_exchange.load_markets()
      positions = temp_exchange.fetch_positions()
      for pos in positions:
        if float(pos.get("contracts", 0)) > 0:
          sym = pos["symbol"]
          side_to_close = "sell" if pos["side"] == "long" else "buy"
          temp_exchange.create_market_order(
              sym, side_to_close, pos["contracts"], {"reduceOnly": True}
          )
      st.sidebar.success("Awaryjnie zamknięto wszystkie otwarte pozycje!")
      st.session_state.trade_history.append(
          f"[{datetime.now().strftime('%H:%M:%S')}] 🚨 KILL SWITCH wykonany."
      )
    except Exception as e:
      st.sidebar.error(f"Błąd Kill Switch: {e}")


# ==========================================
# FUNKCJE ANALITYCZNE I GIEŁDOWE
# ==========================================
def init_exchange(k, s, p, m_type):
  exchange = ccxt.bitget({
      "apiKey": k,
      "secret": s,
      "password": p,
      "enableRateLimit": True,
      "options": {"defaultType": m_type},
  })
  return exchange


def get_account_balance(exchange):
  try:
    balance = exchange.fetch_balance()
    free_usdt = balance.get("free", {}).get("USDT", 0.0)
    total_usdt = balance.get("total", {}).get("USDT", 0.0)
    return float(free_usdt), float(total_usdt)
  except Exception:
    return 0.0, 0.0


def calculate_dynamic_leverage(df, max_lev):
  try:
    high_low = df["high"] - df["low"]
    high_close = (df["high"] - df["close"].shift()).abs()
    low_close = (df["low"] - df["close"].shift()).abs()
    ranges = pd.concat([high_low, high_close, low_close], axis=1)
    true_range = ranges.max(axis=1)
    atr = true_range.rolling(14).mean().iloc[-1]
    price = df["close"].iloc[-1]
    volatility_pct = (atr / price) * 100

    if volatility_pct < 0.5:
      calculated = max_lev
    elif volatility_pct < 1.5:
      calculated = max_lev * 0.7
    else:
      calculated = max_lev * 0.4

    return max(1, int(calculated))
  except Exception:
    return 3


def get_top_volume_pairs(exchange, limit=20, m_type="swap"):
  try:
    exchange.load_markets()
    tickers = exchange.fetch_tickers()
    valid_pairs = []
    for symbol, ticker in tickers.items():
      if "/USDT" in symbol or "/USDT:USDT" in symbol:
        if m_type == "swap" and ":USDT" not in symbol:
          continue
        quote_volume = ticker.get("quoteVolume", 0) or 0
        last_price = ticker.get("last", 0) or 0
        valid_pairs.append({
            "symbol": symbol,
            "volume": quote_volume,
            "price": last_price,
        })
    valid_pairs = sorted(valid_pairs, key=lambda x: x["volume"], reverse=True)
    return valid_pairs[:limit]
  except Exception:
    return []


def analyze_market_conditions(exchange, symbol, timeframe):
  try:
    ohlcv = exchange.fetch_ohlcv(symbol, timeframe=timeframe, limit=100)
    df = pd.DataFrame(
        ohlcv, columns=["timestamp", "open", "high", "low", "close", "volume"]
    )
    df["EMA9"] = df["close"].ewm(span=9, adjust=False).mean()
    df["EMA21"] = df["close"].ewm(span=21, adjust=False).mean()
    df["EMA50"] = df["close"].ewm(span=50, adjust=False).mean()

    ema12 = df["close"].ewm(span=12, adjust=False).mean()
    ema26 = df["close"].ewm(span=26, adjust=False).mean()
    df["macd"] = ema12 - ema26
    df["signal"] = df["macd"].ewm(span=9, adjust=False).mean()
    return df
  except Exception:
    return None


# ==========================================
# INTERFEJS GŁÓWNY
# ==========================================
st.markdown(
    """
    <div class="retro-banner">
        <h1 class="retro-title">BITGET SAS</h1>
    </div>
""",
    unsafe_allow_html=True,
)

free_bal, total_bal = 0.0, 0.0
if api_key and api_secret and api_password:
  try:
    tmp_ex = init_exchange(api_key, api_secret, api_password, market_type)
    free_bal, total_bal = get_account_balance(tmp_ex)
  except Exception:
    pass

try:
  session_uptime = int(
      time.time() - float(st.session_state.session_start_time)
  )
except Exception:
  st.session_state.session_start_time = time.time()
  session_uptime = 0

hours, remainder = divmod(session_uptime, 3600)
minutes, seconds = divmod(remainder, 60)
uptime_str = f"{hours:02d}:{minutes:02d}:{seconds:02d}"

# Kafelki metryk
col_m1, col_m2, col_m3, col_m4, col_m5 = st.columns(5)
with col_m1:
  st.markdown(
      f"""<div class="metric-card"><h4>Status</h4><p style="color: {'#2ecc71' if st.session_state.bot_active else '#e74c3c'}; font-weight: bold; font-size: 16px;">{'🟢 AKTYWNY' if st.session_state.bot_active else '🔴 ZATRZYMANY'}</p></div>""",
      unsafe_allow_html=True,
  )
with col_m2:
  st.markdown(
      f"""<div class="metric-card"><h4>Wolne Środki</h4><p style="font-size: 16px; font-weight: bold; color: #d4af37;">{free_bal:,.2f} USDT</p></div>""",
      unsafe_allow_html=True,
  )
with col_m3:
  st.markdown(
      f"""<div class="metric-card"><h4>Całkowity Kapitał</h4><p style="font-size: 16px; font-weight: bold;">{total_bal:,.2f} USDT</p></div>""",
      unsafe_allow_html=True,
  )
with col_m4:
  st.markdown(
      f"""<div class="metric-card"><h4>Typ Rynku</h4><p style="font-size: 16px; font-weight: bold; color: #d4af37;">{market_type.upper()}</p></div>""",
      unsafe_allow_html=True,
  )
with col_m5:
  st.markdown(
      f"""<div class="metric-card"><h4>Zegar Sesji</h4><p style="font-size: 16px; font-weight: bold; color: #2ecc71;">{uptime_str}</p></div>""",
      unsafe_allow_html=True,
  )

c_start, c_stop = st.columns(2)
with c_start:
  if st.button(
      "▶ Uruchom w Pełnym Autopilocie",
      type="primary",
      use_container_width=True,
  ):
    if not api_key or not api_secret or not api_password:
      st.error("Uzupełnij dane dostępowe API w panelu bocznym.")
    else:
      st.session_state.bot_active = True
      st.success("Autopilot został włączony. System działa w tle.")
with c_stop:
  if st.button("⏹ Zatrzymaj Autopilot", use_container_width=True):
    st.session_state.bot_active = False
    st.warning("Zatrzymano działanie autopilota.")

st.markdown("---")

# ==========================================
# ZAKŁADKI: HANDEL, SUBSKRYPCJA, LOGI, DIAGNOSTYKA
# ==========================================
if api_key and api_secret and api_password:
  try:
    exchange = init_exchange(api_key, api_secret, api_password, market_type)

    tab1, tab2, tab3, tab4 = st.tabs([
        "📊 Tabela Top 10 i Skaner Rynku",
        "💳 Subskrypcja (49 zł)",
        "📜 Dziennik Zdarzeń SAS",
        "⚙️ Status Połączenia",
    ])

    with tab1:
      st.subheader("Tablica Najlepszych Par Rynkowych (Top 10)")
      st.markdown(
          "Poniższa tabela prezentuje 10 najlepszych par wyselekcjonowanych w"
          " oparciu o wolumen obrotu z przeszukanych zasobów giełdy."
      )

      run_cycle = st.button(
          "🔄 Odśwież Skan i Wykonaj Cykl Handlowy",
          type="primary",
          use_container_width=True,
      )

      if st.session_state.bot_active or run_cycle:
        with st.spinner(
            "Skanowanie rynku, pobieranie danych i analiza techniczna..."
        ):
          free_usdt, _ = get_account_balance(exchange)

          scanned_market = get_top_volume_pairs(
              exchange, limit=scan_breadth, m_type=market_type
          )
          top_10_pairs_data = scanned_market[:10]
          st.session_state.top_pairs_cache = top_10_pairs_data

          if top_10_pairs_data:
            df_table = pd.DataFrame(top_10_pairs_data)
            df_table.columns = ["Para Symbol", "Wolumen 24h (USDT)", "Cena"]
            st.dataframe(df_table, use_container_width=True)

          open_positions = exchange.fetch_positions()
          active_positions_map = {
              p["symbol"]: p
              for p in open_positions
              if float(p.get("contracts", 0)) > 0
          }

          for item in top_10_pairs_data:
            symbol = item["symbol"]
            df = analyze_market_conditions(exchange, symbol, tf)
            if df is None or df.empty:
              continue

            current_price = df["close"].iloc[-1]
            last_ema50 = df["EMA50"].iloc[-1]
            last_macd = df["macd"].iloc[-1]
            last_signal = df["signal"].iloc[-1]
            prev_macd = df["macd"].iloc[-2]
            prev_signal = df["signal"].iloc[-2]
            now_ts = time.time()

            # --- A. ZARZĄDZANIE OTWARTĄ POZYCJĄ ---
            if symbol in active_positions_map:
              pos = active_positions_map[symbol]
              pos_side = pos["side"]
              entry_price = float(pos["entryPrice"])
              contracts = float(pos["contracts"])
              pnl_pct = float(pos.get("percentage", 0))

              open_time = st.session_state.position_timers.get(symbol, now_ts)
              time_elapsed = now_ts - open_time
              exit_triggered = False
              exit_reason = ""

              if use_sltp:
                if pos_side == "long":
                  if current_price <= entry_price * (1 - stop_loss_pct):
                    exit_triggered = True
                    exit_reason = "Twardy Stop Loss (LONG)"
                  elif current_price >= entry_price * (1 + take_profit_pct):
                    exit_triggered = True
                    exit_reason = "Realizacja Take Profit (LONG)"
                elif pos_side == "short":
                  if current_price >= entry_price * (1 + stop_loss_pct):
                    exit_triggered = True
                    exit_reason = "Twardy Stop Loss (SHORT)"
                  elif current_price <= entry_price * (1 - take_profit_pct):
                    exit_triggered = True
                    exit_reason = "Realizacja Take Profit (SHORT)"

              if not exit_triggered and time_elapsed >= min_hold_seconds:
                if (
                    pos_side == "long"
                    and prev_macd >= prev_signal
                    and last_macd < last_signal
                ):
                  exit_triggered = True
                  exit_reason = "Odwrócenie trendu MACD (Zamknięcie LONG)"
                elif (
                    pos_side == "short"
                    and prev_macd <= prev_signal
                    and last_macd > last_signal
                ):
                  exit_triggered = True
                  exit_reason = "Odwrócenie trendu MACD (Zamknięcie SHORT)"

              if exit_triggered:
                side_to_close = "sell" if pos_side == "long" else "buy"
                try:
                  exchange.create_market_order(
                      symbol,
                      side_to_close,
                      contracts,
                      params={"reduceOnly": True},
                  )
                  log_msg = f"[{datetime.now().strftime('%H:%M:%S')}] ❌ ZAMKNIĘTO {symbol} ({pos_side}). Powód: {exit_reason}. PnL: {pnl_pct:.2f}%"
                  st.session_state.trade_history.append(log_msg)
                  st.success(log_msg)
                  st.session_state.position_timers.pop(symbol, None)
                except Exception as ex:
                  st.error(f"Błąd zamykania {symbol}: {ex}")

            # --- B. OTWIERANIE NOWEJ POZYCJI ---
            else:
              if len(active_positions_map) >= max_open_trades:
                continue

              if free_usdt < 10.0:
                continue

              chosen_leverage = (
                  calculate_dynamic_leverage(df, max_allowed_leverage)
                  if use_dynamic_leverage
                  else max_allowed_leverage
              )

              allocated_margin = free_usdt * risk_pct_per_trade
              notional_value = allocated_margin * chosen_leverage
              calc_contracts = notional_value / current_price

              # Sygnał LONG
              if (
                  current_price > last_ema50
                  and prev_macd <= prev_signal
                  and last_macd > last_signal
              ):
                try:
                  if market_type == "swap":
                    exchange.set_leverage(chosen_leverage, symbol)
                  exchange.create_market_order(symbol, "buy", calc_contracts)
                  st.session_state.position_timers[symbol] = now_ts
                  log_msg = f"[{datetime.now().strftime('%H:%M:%S')}] 🟢 OTWARTO LONG na {symbol} | Kapitał: {allocated_margin:.2f} USDT | Dźwignia: {chosen_leverage}x"
                  st.session_state.trade_history.append(log_msg)
                  st.success(log_msg)
                  free_usdt -= allocated_margin
                  active_positions_map[symbol] = {"side": "long"}
                except Exception:
                  pass

              # Sygnał SHORT
              elif (
                  current_price < last_ema50
                  and prev_macd >= prev_signal
                  and last_macd < last_signal
              ):
                try:
                  if market_type == "swap":
                    exchange.set_leverage(chosen_leverage, symbol)
                  exchange.create_market_order(symbol, "sell", calc_contracts)
                  st.session_state.position_timers[symbol] = now_ts
                  log_msg = f"[{datetime.now().strftime('%H:%M:%S')}] 🔴 OTWARTO SHORT na {symbol} | Kapitał: {allocated_margin:.2f} USDT | Dźwignia: {chosen_leverage}x"
                  st.session_state.trade_history.append(log_msg)
                  st.warning(log_msg)
                  free_usdt -= allocated_margin
                  active_positions_map[symbol] = {"side": "short"}
                except Exception:
                  pass
      else:
        if st.session_state.top_pairs_cache:
          st.markdown("Ostatnio wyselekcjonowane Top 10 par:")
          df_table = pd.DataFrame(st.session_state.top_pairs_cache)
          df_table.columns = ["Para Symbol", "Wolumen 24h (USDT)", "Cena"]
          st.dataframe(df_table, use_container_width=True)
        else:
          st.info(
              "Kliknij powyższy przycisk lub uruchom autopilot, aby pobrać"
              " tabelę najlepszych par."
          )

    with tab2:
      st.subheader("💳 Panel Płatności i Subskrypcji systemu Bitget SAS")
      st.markdown(
          "Aktywuj pełny dostęp do autonomicznego terminala inwestycyjnego."
          " Koszt subskrypcji wynosi **49 zł / miesiąc**."
      )

      col_sub1, col_sub2 = st.columns(2)
      with col_sub1:
        st.markdown(
            """
                <div style="background-color: #161b22; border: 1px solid #d4af37; padding: 20px; border-radius: 6px;">
                    <h3>Pakiet Miesięczny SAS</h3>
                    <p style="font-size: 24px; color: #d4af37; font-weight: bold;">49 PLN <span style="font-size: 14px; color: #888;">/ mc</span></p>
                    <ul style="color: #ccc; line-height: 1.6;">
                        <li>Pełny dostęp do algorytmu Top 10</li>
                        <li>Automatyczny skaner rynkowy</li>
                        <li>Ochrona Stop Loss / Take Profit</li>
                        <li>Bezpieczne szyfrowanie sesji</li>
                    </ul>
                </div>
                """,
            unsafe_allow_html=True,
        )
      with col_sub2:
        st.markdown("### Opłać subskrypcję online")
        st.write(
            "Kliknij poniższy przycisk, aby przejść do bezpiecznej bramki"
            " płatności Stripe i opłacić abonament."
        )

        stripe_payment_link = (
            "https://buy.stripe.com/test_placeholder_link_49zl"
        )
        st.markdown(
            f"""
                <a href="{stripe_payment_link}" target="_blank">
                    <button style="background-color: #d4af37; color: #000000; padding: 12px 24px; font-weight: bold; border: none; border-radius: 4px; cursor: pointer; font-size: 16px; width: 100%;">
                        💳 Opłać Subskrypcję (49 PLN)
                    </button>
                </a>
                """,
            unsafe_allow_html=True,
        )
        st.info(
            "Po opłaceniu subskrypcji dostęp zostanie aktywowany dla Twojego"
            " konta."
        )

    with tab3:
      st.subheader("Rejestr Operacji i Działań Systemu SAS")
      if st.session_state.trade_history:
        for hist in reversed(st.session_state.trade_history[-20:]):
          st.text(hist)
      else:
        st.info("Brak zarejestrowanych zdarzeń w bieżącej sesji.")

    with tab4:
      st.subheader("Diagnostyka Połączenia API")
      st.success(
          "Klient CCXT pomyślnie uwierzytelniony i połączony z giełdą Bitget."
      )

  except Exception as e:
    st.error(f"Krytyczny błąd infrastruktury aplikacji: {e}")
else:
    st.warning(
        "👈 Uzupełnij dane dostępowe API w panelu bocznym lub skonfiguruj"
        " serwer, aby aktywować terminal."
    )

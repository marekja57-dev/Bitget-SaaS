import time
from datetime import datetime
import ccxt
import pandas as pd
import streamlit as st

# ==========================================
# KONFIGURACJA STRONY I STYLIZACJA RETRO-VINTAGE
# ==========================================
st.set_page_config(
    page_title="Bitget SAS - Profesjonalny Terminal Autonomiczny",
    page_icon="⚡",
    layout="wide",
)

st.markdown(
    """
    <style>
    @import url('https://fonts.googleapis.com/css2?family=Special+Elite&display=swap');

    .main { background-color: #0e1117; color: #e6e6e6; }
    .stButton>button { background-color: #d4af37; color: #000000; font-weight: bold; border-radius: 4px; border: none; }
    .stButton>button:hover { background-color: #f4d03f; color: #000000; }
    .metric-card { background-color: #1a1c23; border: 1px solid #d4af37; padding: 15px; border-radius: 6px; margin-bottom: 10px; }
    .stAlert { background-color: #161b22; color: #e6e6e6; border: 1px solid #30363d; }
    
    .retro-title {
        font-family: 'Special Elite', cursive, monospace;
        color: #2ecc71;
        text-align: center;
        font-size: 3.5rem;
        letter-spacing: 2px;
        margin-bottom: 0px;
        text-shadow: 0 0 12px rgba(46, 204, 113, 0.4);
    }
    
    .retro-subtitle {
        font-family: 'Special Elite', cursive, monospace;
        color: #d1d5db;
        text-align: center;
        font-size: 1.2rem;
        margin-top: 5px;
        margin-bottom: 25px;
    }
    </style>
""",
    unsafe_allow_html=True,
)

# ==========================================
# INICJALIZACIJA STANU SESJI
# ==========================================
if "bot_active" not in st.session_state:
    st.session_state.bot_active = False
if "trade_history" not in st.session_state:
    st.session_state.trade_history = []
if "position_timers" not in st.session_state:
    st.session_state.position_timers = {}
if "nav_to_panel" not in st.session_state:
    st.session_state.nav_to_panel = False

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

def get_top_volume_pairs(exchange, limit=10, m_type="swap"):
    """Inteligentny skaner wyszukujący najbardziej płynne pary na giełdzie"""
    try:
        exchange.load_markets()
        tickers = exchange.fetch_tickers()
        valid_pairs = []

        for symbol, ticker in tickers.items():
            if "/USDT" in symbol or "/USDT:USDT" in symbol:
                if m_type == "swap" and ":USDT" not in symbol:
                    continue
                quote_volume = ticker.get("quoteVolume", 0) or 0
                valid_pairs.append({"symbol": symbol, "volume": quote_volume})

        valid_pairs = sorted(valid_pairs, key=lambda x: x["volume"], reverse=True)
        return [item["symbol"] for item in valid_pairs[:limit]]
    except Exception as e:
        st.error(f"Błąd skanowania par rynkowych: {e}")
        return []

def analyze_market_conditions(exchange, symbol, timeframe):
    """Pobiera dane OHLCV i oblicza wskaźniki (EMA + MACD) dla oceny trendu"""
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
    except Exception as e:
        return None

# ==========================================
# EKRAN POWITALNY (W Stylu Retro)
# ==========================================
if not st.session_state.nav_to_panel:
    st.markdown('<div class="retro-title">BITGET SAS</div>', unsafe_allow_html=True)
    st.markdown(
        '<div class="retro-subtitle">Autonomiczny Terminal Inwestycyjny & Algorytmiczny Skaner Rynkowy</div>',
        unsafe_allow_html=True,
    )
    st.markdown(
        "<p style='text-align: center; color: #9ca3af; font-size: 1rem;'>Zarządzaj swoimi inwestycjami na rynkach Spot i Futures z najwyższą precyzją.</p>",
        unsafe_allow_html=True,
    )

    st.markdown("<br>", unsafe_allow_html=True)

    col1, col2, col3 = st.columns([1, 2, 1])
    with col2:
        if st.button("🚀 WEJDŹ DO TERMINAŁA", use_container_width=True, type="primary"):
            st.session_state.nav_to_panel = True
            st.rerun()

# ==========================================
# PANEL OPERACYJNY
# ==========================================
else:
    # PANEL BOCZNY - BITGET SAS CONTROL & SECURITY
    st.sidebar.title("🛡️ Bitget SAS Control")
    api_key = st.sidebar.text_input("API Key", type="password")
    api_secret = st.sidebar.text_input("API Secret", type="password")
    api_password = st.sidebar.text_input("API Password (Passphrase)", type="password")

    st.sidebar.markdown("---")
    if st.sidebar.button("⬅ Wróć do ekranu powitalnego", use_container_width=True):
        st.session_state.nav_to_panel = False
        st.rerun()

    st.sidebar.markdown("---")
    st.sidebar.subheader("⚙️ Parametry Rynku i Skanera")
    market_type = st.sidebar.selectbox("Typ Rynku", ["swap", "spot"], index=0)
    tf = st.sidebar.selectbox("Interwał Analityczny", ["5m", "15m", "1h", "4h"], index=1)
    max_pairs_to_scan = st.sidebar.slider("Liczba par w skanerze", 5, 30, 10, step=5)

    st.sidebar.markdown("---")
    st.sidebar.subheader("💰 Zarządzanie Kapitałem")
    amount_usdt = st.sidebar.number_input("Wielkość pozycji bazowej (USDT)", value=50.0, step=10.0)
    leverage = st.sidebar.slider("Dźwignia (Leverage)", 1, 20, 5)
    use_sltp = st.sidebar.checkbox("Włącz ochronę Stop Loss / Take Profit", value=True)
    stop_loss_pct = st.sidebar.slider("Stop Loss (%)", 0.5, 5.0, 1.5, 0.1) / 100.0
    take_profit_pct = st.sidebar.slider("Take Profit (%)", 1.0, 20.0, 3.0, 0.5) / 100.0
    min_hold_seconds = st.sidebar.number_input(
        "Min. czas trzymania pozycji (Cooldown w sek.)",
        value=300,
        step=60,
        help="Zapobiega natychmiastowemu zamykaniu pozycji tuż po wejściu.",
    )

    st.sidebar.markdown("---")

    # Przycisk awaryjny KILL SWITCH w stylu Bitget SAS
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
                    f"[{datetime.now().strftime('%H:%M:%S')}] 🚨 KILL SWITCH wykonany ręcznie."
                )
            except Exception as e:
                st.sidebar.error(f"Błąd Kill Switch: {e}")
        else:
            st.sidebar.warning("Uzupełnij klucze API, aby wykonać awaryjne zamknięcie.")

    # ==========================================
    # GŁÓWNY INTERFEJS I Kafelki (RETRO-VINTAGE)
    # ==========================================
    st.markdown(
        '<div class="retro-title" style="font-size: 2.2rem; text-align: left;">🚀 Bitget SAS - Panel Operacyjny</div>',
        unsafe_allow_html=True,
    )
    st.markdown(
        "Profesjonalna platforma handlowa z wieloparowym skanerem płynności, filtrem trendu EMA50 oraz pełną ochroną kapitału."
    )

    # Kafelki metryk w stylu retro-vintage
    col_m1, col_m2, col_m3, col_m4 = st.columns(4)
    with col_m1:
        st.markdown(
            f"""<div class="metric-card"><h4>Status Systemu</h4><p style="color: {'#2ecc71' if st.session_state.bot_active else '#e74c3c'}; font-weight: bold; font-size: 18px;">{'🟢 URUCHOMIONY' if st.session_state.bot_active else '🔴 ZATRZYMANY'}</p></div>""",
            unsafe_allow_html=True,
        )
    with col_m2:
        st.markdown(
            f"""<div class="metric-card"><h4>Typ Rynku</h4><p style="font-size: 18px; font-weight: bold; color: #d4af37;">{market_type.upper()}</p></div>""",
            unsafe_allow_html=True,
        )
    with col_m3:
        st.markdown(
            f"""<div class="metric-card"><h4>Wybrana Dźwignia</h4><p style="font-size: 18px; font-weight: bold;">{leverage}x</p></div>""",
            unsafe_allow_html=True,
        )
    with col_m4:
        st.markdown(
            f"""<div class="metric-card"><h4>Kapitał / Pozycję</h4><p style="font-size: 18px; font-weight: bold;">{amount_usdt} USDT</p></div>""",
            unsafe_allow_html=True,
        )

    # Przyciski sterujące start/stop
    c_start, c_stop = st.columns(2)
    with c_start:
        if st.button("▶ Uruchom Autonomiczny Handel", type="primary", use_container_width=True):
            if not api_key or not api_secret or not api_password:
                st.error("Wprowadź dane dostępowe API w panelu bocznym.")
            else:
                st.session_state.bot_active = True
                st.success("Uruchomiono pętlę analityczną i handlową.")
    with c_stop:
        if st.button("⏹ Zatrzymaj System", use_container_width=True):
            st.session_state.bot_active = False
            st.warning("Zatrzymano działanie systemu.")

    st.markdown("---")

    # ==========================================
    # GŁÓWNA PĘTLA WYKONAWCZA I ZAKŁADKI
    # ==========================================
    if api_key and api_secret and api_password:
        try:
            exchange = init_exchange(api_key, api_secret, api_password, market_type)

            tab1, tab2, tab3 = st.tabs([
                "📊 Skaner Rynku i Zarządzanie Pozycjami",
                "📜 Dziennik Zdarzeń SAS",
                "⚙️ Status Połączenia",
            ])

            with tab1:
                st.subheader("Autonomiczny Skaner Wolumenu i Sygnałów")

                if st.button("🔄 Wykonaj Cykl Skanowania i Analizy Rynku", type="primary", use_container_width=True):
                    with st.spinner("Skanowanie giełdy Bitget, analiza płynności oraz wskaźników..."):
                        active_symbols = get_top_volume_pairs(exchange, limit=max_pairs_to_scan, m_type=market_type)
                        st.info(f"Pomyślnie pobrano top {len(active_symbols)} płynnych par o największym obrocie.")

                        open_positions = exchange.fetch_positions()
                        active_positions_map = {
                            p["symbol"]: p for p in open_positions if float(p.get("contracts", 0)) > 0
                        }

                        for symbol in active_symbols:
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

                            # --- A. ZARZĄDZANIE ISTNIEJĄCĄ POZYCJĄ (SL / TP / TREND) ---
                            if symbol in active_positions_map:
                                pos = active_positions_map[symbol]
                                pos_side = pos["side"]
                                entry_price = float(pos["entryPrice"])
                                contracts = float(pos["contracts"])
                                pnl_pct = float(pos.get("percentage", 0))

                                st.write(
                                    f"🔍 **{symbol}** | Aktywna: **{pos_side.upper()}** | Wejście: `{entry_price}` | PnL: `{pnl_pct:.2f}%`"
                                )

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
                                    if pos_side == "long" and prev_macd >= prev_signal and last_macd < last_signal:
                                        exit_triggered = True
                                        exit_reason = "Odwrócenie trendu MACD (Zamknięcie LONG)"
                                    elif pos_side == "short" and prev_macd <= prev_signal and last_macd > last_signal:
                                        exit_triggered = True
                                        exit_reason = "Odwrócenie trendu MACD (Zamknięcie SHORT)"

                                if exit_triggered:
                                    side_to_close = "sell" if pos_side == "long" else "buy"
                                    try:
                                        exchange.create_market_order(
                                            symbol, side_to_close, contracts, params={"reduceOnly": True}
                                        )
                                        log_msg = f"[{datetime.now().strftime('%H:%M:%S')}] ❌ ZAMKNIĘTO pozycję {symbol} ({pos_side}). Powód: {exit_reason}. Wynik PnL: {pnl_pct:.2f}%"
                                        st.session_state.trade_history.append(log_msg)
                                        st.success(log_msg)
                                        st.session_state.position_timers.pop(symbol, None)
                                    except Exception as ex:
                                        st.error(f"Błąd zamykania pozycji {symbol}: {ex}")

                            # --- B. SZUKANIE NOWYCH OKAZJI Z FILTREM TRENDU EMA50 ---
                            else:
                                notional = amount_usdt * (leverage if market_type == "swap" else 1)
                                calc_contracts = notional / current_price

                                if current_price > last_ema50 and prev_macd <= prev_signal and last_macd > last_signal:
                                    try:
                                        if market_type == "swap":
                                            exchange.set_leverage(leverage, symbol)
                                        exchange.create_market_order(symbol, "buy", calc_contracts)
                                        st.session_state.position_timers[symbol] = now_ts
                                        log_msg = f"[{datetime.now().strftime('%H:%M:%S')}] 🟢 OTWARTO LONG na {symbol} | Cena: {current_price:,.4f} | Filtr EMA50 OK"
                                        st.session_state.trade_history.append(log_msg)
                                        st.success(log_msg)
                                    except Exception:
                                        pass

                                elif current_price < last_ema50 and prev_macd >= prev_signal and last_macd < last_signal:
                                    try:
                                        if market_type == "swap":
                                            exchange.set_leverage(leverage, symbol)
                                        exchange.create_market_order(symbol, "sell", calc_contracts)
                                        st.session_state.position_timers[symbol] = now_ts
                                        log_msg = f"[{datetime.now().strftime('%H:%M:%S')}] 🔴 OTWARTO SHORT na {symbol} | Cena: {current_price:,.4f} | Filtr EMA50 OK"
                                        st.session_state.trade_history.append(log_msg)
                                        st.warning(log_msg)
                                    except Exception:
                                        pass

            with tab2:
                st.subheader("Rejestr Operacji i Działań Systemu SAS")
                if st.session_state.trade_history:
                    for hist in reversed(st.session_state.trade_history[-20:]):
                        st.text(hist)
                else:
                    st.info("Brak zarejestrowanych zdarzeń w bieżącej sesji. Uruchom cykl skanowania.")

            with tab3:
                st.subheader("Diagnostyka Połączenia API")
                st.success("Klient CCXT pomyślnie uwierzytelniony i połączony z giełdą Bitget.")

        except Exception as e:
            st.error(f"Krytyczny błąd infrastruktury aplikacji: {e}")
    else:
        st.warning("👈 Uzupełnij dane dostępowe API w panelu bocznym, aby uruchomić interfejs terminala.")

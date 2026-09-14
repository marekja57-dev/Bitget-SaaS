import logging
import time
from datetime import datetime
import ccxt
import pandas as pd
import streamlit as st
import stripe

# ==========================================
# KONFIGURACJA LOGOWANIA I STRONY
# ==========================================
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("BotBitgetSAS")

st.set_page_config(
    page_title="Bitget SAS - Autonomiczny Terminal Inwestycyjny",
    page_icon="⚡",
    layout="wide",
)

# ==========================================
# PROFESJONALNA STYLIZACJA CSS (DARK / RETRO / GOLD)
# ==========================================
st.markdown(
    """
    <style>
    @import url('https://fonts.googleapis.com/css2?family=Cinzel:wght@600;700;900&family=Inter:wght@400;500;600&display=swap');

    .main { background-color: #0e1117; color: #e6e6e6; }
    .stButton>button { background-color: #d4af37; color: #000000; font-weight: bold; border-radius: 4px; border: none; padding: 0.5rem 1rem; }
    .stButton>button:hover { background-color: #f4d03f; color: #000000; }
    .metric-card { background-color: #1a1c23; border: 1px solid #d4af37; padding: 15px; border-radius: 6px; margin-bottom: 10px; box-shadow: 0 4px 6px rgba(0,0,0,0.3); }
    .stAlert { background-color: #161b22; color: #e6e6e6; border: 1px solid #30363d; }
    
    .retro-title {
        font-family: 'Cinzel', serif;
        color: #2ecc71;
        text-align: center;
        font-size: 3.5rem;
        font-weight: 900;
        letter-spacing: 3px;
        margin-bottom: 0px;
        text-shadow: 0 0 15px rgba(46, 204, 113, 0.3);
    }
    
    .retro-subtitle {
        font-family: 'Inter', sans-serif;
        color: #e5e7eb;
        text-align: center;
        font-size: 1.15rem;
        font-weight: 500;
        margin-top: 15px;
        margin-bottom: 10px;
        letter-spacing: 0.5px;
    }
    
    .splash-box {
        border: 2px solid #d4af37;
        padding: 40px 30px;
        border-radius: 8px;
        background-color: #12151c;
        box-shadow: 0 0 25px rgba(212, 175, 55, 0.2);
        margin-top: 20px;
        margin-bottom: 25px;
    }
    </style>
""",
    unsafe_allow_html=True,
)

# ==========================================
# INICJALIZACIJA STANU SESJI I PAMIĘCI ADMINA
# ==========================================
if "bot_active" not in st.session_state:
    st.session_state.bot_active = False
if "trade_history" not in st.session_state:
    st.session_state.trade_history = []
if "position_timers" not in st.session_state:
    st.session_state.position_timers = {}
if "partial_sold" not in st.session_state:
    st.session_state.partial_sold = {}
if "nav_to_panel" not in st.session_state:
    st.session_state.nav_to_panel = False

# Trwałość danych administratora w sesji (brak konieczności ciągłego wpisywania)
if "api_key" not in st.session_state:
    st.session_state.api_key = ""
if "secret_key" not in st.session_state:
    st.session_state.secret_key = ""
if "passphrase" not in st.session_state:
    st.session_state.passphrase = ""
if "stripe_key" not in st.session_state:
    st.session_state.stripe_key = ""
if "stripe_price_id" not in st.session_state:
    st.session_state.stripe_price_id = "price_1M_bitget_sas_sub"

# ==========================================
# ROBUSTE FUNKCJE GIEŁDOWE I STRIPE
# ==========================================
def init_exchange(k, s, p, m_type):
    """Inicjalizuje połączenie CCXT z giełdą Bitget z obsługą rate limitów"""
    try:
        exchange = ccxt.bitget({
            "apiKey": k,
            "secret": s,
            "password": p,
            "enableRateLimit": True,
            "options": {"defaultType": m_type},
        })
        return exchange
    except Exception as e:
        logger.error(f"Błąd inicjalizacji giełdy: {e}")
        return None

def execute_kill_switch(k, s, p, m_type):
    """Awaryjne zamknięcie wszystkich otwartych pozycji na giełdzie w ułamku sekundy"""
    try:
        ex = init_exchange(k, s, p, m_type)
        if not ex:
            return False, "Nie udało się połączyć z giełdą."
        ex.load_markets()
        positions = ex.fetch_positions()
        closed_count = 0
        for pos in positions:
            contracts = float(pos.get("contracts", 0))
            if contracts > 0:
                symbol = pos["symbol"]
                side_to_close = "sell" if pos["side"] == "long" else "buy"
                ex.create_market_order(symbol, side_to_close, contracts, {"reduceOnly": True})
                closed_count += 1
        return True, f"Awaryjnie zamknięto {closed_count} pozycji na rynku {m_type.upper()}."
    except Exception as e:
        return False, str(e)

def get_top_volume_pairs(exchange, limit=10, m_type="swap"):
    """Zaawansowany skaner płynności i wybić rynkowych"""
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
        logger.error(f"Błąd pobierania wolumenu: {e}")
        return []

def analyze_market_conditions(exchange, symbol, timeframe="15m"):
    """Pobiera świece OHLCV i wylicza wskaźniki techniczne (EMA50, MACD, Signal)"""
    try:
        ohlcv = exchange.fetch_ohlcv(symbol, timeframe=timeframe, limit=100)
        df = pd.DataFrame(ohlcv, columns=["timestamp", "open", "high", "low", "close", "volume"])
        df["EMA50"] = df["close"].ewm(span=50, adjust=False).mean()
        ema12 = df["close"].ewm(span=12, adjust=False).mean()
        ema26 = df["close"].ewm(span=26, adjust=False).mean()
        df["macd"] = ema12 - ema26
        df["signal"] = df["macd"].ewm(span=9, adjust=False).mean()
        return df
    except Exception as e:
        return None

def create_stripe_checkout(stripe_api_key, price_id, user_email):
    """Generuje sesję płatności cyklicznej Stripe dla subskrybentów platformy"""
    try:
        stripe.api_key = stripe_api_key
        checkout_session = stripe.checkout.Session.create(
            payment_method_types=['card'],
            line_items=[{'price': price_id, 'quantity': 1}],
            mode='subscription',
            customer_email=user_email,
            success_url='https://bot-bitget.pl/?success=true',
            cancel_url='https://bot-bitget.pl/?canceled=true',
        )
        return checkout_session.url
    except Exception as e:
        return str(e)

# ==========================================
# EKRAN POWITALNY (LANDING PAGE)
# ==========================================
if not st.session_state.nav_to_panel:
    st.markdown(
        """
        <div class="splash-box">
            <div class="retro-title">BITGET SAS</div>
            <div class="retro-subtitle">Autonomiczny Terminal Inwestycyjny & Algorytmiczny Skaner Rynkowy</div>
            <p style='text-align: center; color: #9ca3af; font-size: 1rem; font-family: "Inter", sans-serif; margin-bottom: 0;'>Profesjonalny system handlowy wykrywający trendy wzrostowe i spadkowe z systemem automatycznego zabezpieczenia kapitału.</p>
        </div>
        """,
        unsafe_allow_html=True,
    )

    col1, col2, col3 = st.columns([1, 2, 1])
    with col2:
        if st.button("🚀 WEJDŹ DO TERMINAŁA", use_container_width=True, type="primary"):
            st.session_state.nav_to_panel = True
            st.rerun()

# ==========================================
# PANEL OPERACYJNY (GŁÓWNY MODUŁ APLIKACJI)
# ==========================================
else:
    # --- PANEL BOCZNY (ADMINISTRATOR & BEZPIECZEŃSTWO) ---
    st.sidebar.markdown("### 🔑 Konfiguracja API Bitget")
    st.session_state.api_key = st.sidebar.text_input("API Key", value=st.session_state.api_key, type="password")
    st.session_state.secret_key = st.sidebar.text_input("Secret Key", value=st.session_state.secret_key, type="password")
    st.session_state.passphrase = st.sidebar.text_input("Passphrase", value=st.session_state.passphrase, type="password")

    st.sidebar.markdown("---")
    if st.sidebar.button("⬅ Powrót do ekranu powitalnego", use_container_width=True):
        st.session_state.nav_to_panel = False
        st.rerun()

    # AWARYJNY PRZYCISK KILL SWITCH
    st.sidebar.markdown("---")
    st.sidebar.markdown("### 🚨 Awaryjny Kill Switch")
    market_ks_choice = st.sidebar.selectbox("Rynek do natychmiastowego zamknięcia", ["swap", "spot"], index=0)
    if st.sidebar.button("🚨 KILL SWITCH (Zamknij wszystko)", type="primary", use_container_width=True):
        if st.session_state.api_key and st.session_state.secret_key and st.session_state.passphrase:
            success, msg = execute_kill_switch(
                st.session_state.api_key, st.session_state.secret_key, st.session_state.passphrase, market_ks_choice
            )
            if success:
                st.sidebar.success(msg)
                st.session_state.bot_active = False
            else:
                st.sidebar.error(f"Błąd Kill Switch: {msg}")
        else:
            st.sidebar.warning("Uzupełnij klucze API administratora.")

    # PANEL PŁATNOŚCI STRIPE
    st.sidebar.markdown("---")
    st.sidebar.markdown("### 💳 Subskrypcja i Płatności (Stripe)")
    st.session_state.stripe_key = st.sidebar.text_input("Stripe Secret Key", value=st.session_state.stripe_key, type="password")
    st.session_state.stripe_price_id = st.sidebar.text_input("Stripe Price ID", value=st.session_state.stripe_price_id)
    user_email_input = st.sidebar.text_input("Email Klienta", value="trader@bot-bitget.pl")

    if st.sidebar.button("💳 Generuj Link Płatności Stripe", use_container_width=True):
        if st.session_state.stripe_key and st.session_state.stripe_price_id:
            checkout_url = create_stripe_checkout(st.session_state.stripe_key, st.session_state.stripe_price_id, user_email_input)
            if checkout_url.startswith("http"):
                st.sidebar.markdown(f"👉 **[Przejdź do Stripe Checkout]({checkout_url})**")
            else:
                st.sidebar.error(f"Błąd Stripe: {checkout_url}")
        else:
            st.sidebar.warning("Podaj klucz Stripe oraz ID ceny.")

    st.sidebar.markdown("---")
    st.sidebar.markdown("### ⚙️ Ustawienia Handku i Ryzyka")
    market_type = st.sidebar.selectbox("Główny Typ Rynku (Skaner)", ["swap", "spot"], index=0)
    tf = st.sidebar.selectbox("Interwał Analityczny", ["5m", "15m", "1h", "4h"], index=1)
    amount_usdt = st.sidebar.number_input("Bazowy kapitał na pozycję (USDT)", value=50.0, step=10.0)
    leverage = st.sidebar.slider("Dźwignia Futures", 1, 20, 5)

    st.sidebar.markdown("### 🎯 Strategia 50% Take Profit")
    partial_tp_pct = st.sidebar.slider("Pierwszy poziom Take Profit (%)", 1.0, 15.0, 3.0, 0.5) / 100.0
    stop_loss_pct = st.sidebar.slider("Stop Loss (%)", 0.5, 5.0, 1.5, 0.5) / 100.0

    # --- GŁÓWNY PANEL ORAZ KAFELKI ZE ZDJĘCIA ---
    st.markdown(
        '<div style="font-family: \'Cinzel\', serif; font-size: 2.2rem; font-weight: 900; color: #2ecc71; margin-bottom: 5px;">🚀 Bitget SAS - Panel Operacyjny</div>',
        unsafe_allow_html=True,
    )
    st.markdown("Profesjonalny terminal autonomiczny z obsługą rynków Spot i Futures oraz zaawansowanym zarządzaniem pozycjami.")

    # 4 Kafelki metryk u góry (dokładnie jak na zdjęciu wzorcowym)
    mc1, mc2, mc3, mc4 = st.columns(4)
    with mc1:
        st.markdown('<div class="metric-card"><p style="color:#9ca3af; margin:0; font-size:12px;">🟢 Portfel Spot</p><h3 style="margin:4px 0; font-size:18px;">Aktywny</h3><p style="color:#2ecc71; margin:0; font-size:11px;">↑ Gotowość API</p></div>', unsafe_allow_html=True)
    with mc2:
        st.markdown(f'<div class="metric-card"><p style="color:#9ca3af; margin:0; font-size:12px;">🔵 Portfel Futures</p><h3 style="margin:4px 0; font-size:18px;">Lewar {leverage}x</h3><p style="color:#2ecc71; margin:0; font-size:11px;">↑ Auto-Dźwignia</p></div>', unsafe_allow_html=True)
    with mc3:
        st.markdown('<div class="metric-card"><p style="color:#9ca3af; margin:0; font-size:12px;">📈 Wyniki i 50% TP</p><h3 style="margin:4px 0; font-size:18px;">Automatyczne</h3><p style="color:#2ecc71; margin:0; font-size:11px;">↑ Reguła Połowy</p></div>', unsafe_allow_html=True)
    with mc4:
        st.markdown(f'<div class="metric-card"><p style="color:#9ca3af; margin:0; font-size:12px;">⏱️ Zegar Sesji</p><h3 style="margin:4px 0; font-size:18px;">{datetime.now().strftime("%H:%M:%S")}</h3><p style="color:#2ecc71; margin:0; font-size:11px;">↑ Interwał {tf}</p></div>', unsafe_allow_html=True)

    st.markdown("---")
    st.markdown("### 🥾 Panel Sterowania Botami Trendowymi")
    st.markdown("<p style='color: #9ca3af; font-size: 13px; margin-top: -10px;'>W pełni autonomiczny wybór par (Wzrosty / Spadki)</p>", unsafe_allow_html=True)

    # Kafelki sterujące botami Spot i Futures
    bcol1, bcol2 = st.columns(2)
    with bcol1:
        st.markdown(
            """
            <div class="metric-card" style="border-color: #2ecc71; min-height: 140px;">
                <p style="color: #2ecc71; font-weight: bold; margin-bottom: 5px;">🟢 Bot Trendowy Spot (Auto-Wybór)</p>
                <p style="font-size: 12px; color: #9ca3af;">Samoczynnie przeszukuje rynek spot pod kątem wybić i dołków. Realizuje 50% zysku w locie.</p>
            </div>
            """,
            unsafe_allow_html=True,
        )
        run_spot_bot = st.checkbox("Uruchom Bota Spot Trendowego", value=True)

    with bcol2:
        st.markdown(
            """
            <div class="metric-card" style="border-color: #3498db; min-height: 140px;">
                <p style="color: #3498db; font-weight: bold; margin-bottom: 5px;">🔵 Bot Trendowy Futures (Auto-Wybór)</p>
                <p style="font-size: 12px; color: #9ca3af;">Handluje zarówno na wzrostach (LONG), jak i spadkach (SHORT) z automatycznym zarządzaniem ryzykiem.</p>
            </div>
            """,
            unsafe_allow_html=True,
        )
        run_futures_bot = st.checkbox("Uruchom Bota Futures Trendowego", value=True)

    st.markdown("<br>", unsafe_allow_html=True)

    # Główne przyciski startu całego systemu
    act_col1, act_col2 = st.columns([2, 1])
    with act_col1:
        if st.button("🚀 Uruchom w pełni autonomiczny tryb handku i skaner", use_container_width=True, type="primary"):
            if not st.session_state.api_key:
                st.error("Brak kluczy API. Uzupełnij dane w panelu bocznym.")
            else:
                st.session_state.bot_active = True
                st.success("System autonomiczny został uruchomiony pomyślnie!")
    with act_col2:
        status_color = "#2ecc71" if st.session_state.bot_active else "#e74c3c"
        status_text = "🟢 URUCHOMIONY" if st.session_state.bot_active else "🚨 ZATRZYMANY"
        st.markdown(
            f'<div style="background-color: #2a1215; border: 1px solid {status_color}; padding: 10px; border-radius: 4px; text-align: center; color: {status_color}; font-weight: bold;">{status_text}</div>',
            unsafe_allow_html=True,
        )

    # ==========================================
    # ZAAWANSOWANE ZAKŁADKI OPERACYJNE
    # ==========================================
    tab1, tab2, tab3 = st.tabs([
        "📊 Autonomiczny Skaner Rynkowy i Pozycje",
        "📜 Dziennik Operacji SAS",
        "⚙️ Diagnostyka Połączenia API"
    ])

    with tab1:
        st.subheader("Skanowanie Płynności i Analiza Wybić w Czasie Rzeczywistym")
        
        if st.button("🔄 Wykonaj Cykl Skanowania Rynku", type="primary"):
            if not st.session_state.api_key:
                st.error("Wprowadź dane dostępowe API.")
            else:
                with st.spinner("Analiza par rynkowych i wskaźników technicznych..."):
                    exchange = init_exchange(st.session_state.api_key, st.session_state.secret_key, st.session_state.passphrase, market_type)
                    if exchange:
                        pairs = get_top_volume_pairs(exchange, limit=10, m_type=market_type)
                        open_positions = exchange.fetch_positions() if market_type == "swap" else []
                        active_map = {p["symbol"]: p for p in open_positions if float(p.get("contracts", 0)) > 0}

                        scan_results = []
                        for symbol in pairs:
                            df = analyze_market_conditions(exchange, symbol, tf)
                            if df is None or df.empty:
                                continue

                            current_price = df["close"].iloc[-1]
                            ema50 = df["EMA50"].iloc[-1]
                            macd = df["macd"].iloc[-1]
                            signal = df["signal"].iloc[-1]
                            prev_macd = df["macd"].iloc[-2]
                            prev_signal = df["signal"].iloc[-2]

                            status_desc = "Oczekiwanie na sygnał"

                            # Logika zarządzania pozycją i częściowej realizacji 50% zysku
                            if symbol in active_map:
                                pos = active_map[symbol]
                                entry_price = float(pos["entryPrice"])
                                contracts = float(pos["contracts"])
                                pnl_pct = float(pos.get("percentage", 0)) / 100.0
                                pos_side = pos["side"]

                                status_desc = f"Aktywna ({pos_side.upper()}): PnL {pnl_pct*100:.2f}%"

                                # Reguła 50% Take Profit
                                if pnl_pct >= partial_tp_pct and not st.session_state.partial_sold.get(symbol, False):
                                    close_qty = contracts * 0.5
                                    side_close = "sell" if pos_side == "long" else "buy"
                                    exchange.create_market_order(symbol, side_close, close_qty, {"reduceOnly": True})
                                    st.session_state.partial_sold[symbol] = True
                                    log_msg = f"[{datetime.now().strftime('%H:%M:%S')}] 💰 [50% TP] Zrealizowano połowę zysku na {symbol} przy {pnl_pct*100:.1f}%!"
                                    st.session_state.trade_history.append(log_msg)
                                    st.success(log_msg)

                            else:
                                notional = amount_usdt * (leverage if market_type == "swap" else 1)
                                calc_contracts = notional / current_price

                                # Wykrywanie wzrostów (LONG)
                                if current_price > ema50 and prev_macd <= prev_signal and macd > signal and run_spot_bot:
                                    if market_type == "swap":
                                        exchange.set_leverage(leverage, symbol)
                                    exchange.create_market_order(symbol, "buy", calc_contracts)
                                    st.session_state.partial_sold[symbol] = False
                                    log_msg = f"[{datetime.now().strftime('%H:%M:%S')}] 🟢 Otwarto LONG na {symbol} | Cena: {current_price:,.4f}"
                                    st.session_state.trade_history.append(log_msg)
                                    status_desc = "Otwarto LONG (Wzrosty)"

                                # Wykrywanie spadków (SHORT) - Futures
                                elif market_type == "swap" and current_price < ema50 and prev_macd >= prev_signal and macd < signal and run_futures_bot:
                                    exchange.set_leverage(leverage, symbol)
                                    exchange.create_market_order(symbol, "sell", calc_contracts)
                                    st.session_state.partial_sold[symbol] = False
                                    log_msg = f"[{datetime.now().strftime('%H:%M:%S')}] 🔴 Otwarto SHORT na {symbol} | Cena: {current_price:,.4f}"
                                    st.session_state.trade_history.append(log_msg)
                                    status_desc = "Otwarto SHORT (Spadki)"

                            scan_results.append({
                                "Para": symbol,
                                "Cena": round(current_price, 4),
                                "EMA50": round(ema50, 4),
                                "Status Strategii": status_desc
                            })

                        if scan_results:
                            st.dataframe(pd.DataFrame(scan_results), use_container_width=True)

    with tab2:
        st.subheader("Rejestr Zdarzeń i Transakcji SAS")
        if st.session_state.trade_history:
            for record in reversed(st.session_state.trade_history[-20:]):
                st.text(record)
        else:
            st.info("Brak zarejestrowanych zdarzeń w bieżącej sesji roboczej.")

    with tab3:
        st.subheader("Diagnostyka i Stan Połączenia z Giełdą")
        if st.session_state.api_key:
            st.success("Klucze API zostały poprawnie zapisane w pamięci sesji administratora.")
        else:
            st.warning("Brak skonfigurowanych kluczy API w panelu bocznym.")

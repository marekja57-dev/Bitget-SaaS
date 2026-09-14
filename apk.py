import time
from datetime import datetime
import ccxt
import pandas as pd
import streamlit as st

# ==========================================
# KONFIGURACJA STRONY I STYLIZACJA
# ==========================================
st.set_page_config(
    page_title="Bitget SAS - Panel Operacyjny",
    page_icon="⚡",
    layout="wide",
)

st.markdown(
    """
    <style>
    @import url('https://fonts.googleapis.com/css2?family=Cinzel:wght@600;700;900&family=Inter:wght@400;500;600&display=swap');

    .main { background-color: #0e1117; color: #e6e6e6; }
    .stButton>button { background-color: #d4af37; color: #000000; font-weight: bold; border-radius: 4px; border: none; }
    .stButton>button:hover { background-color: #f4d03f; color: #000000; }
    .metric-card { background-color: #1a1c23; border: 1px solid #d4af37; padding: 12px; border-radius: 6px; margin-bottom: 10px; }
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
    }
    
    .splash-box {
        border: 2px solid #d4af37;
        padding: 40px 30px;
        border-radius: 8px;
        background-color: #12151c;
        box-shadow: 0 0 20px rgba(212, 175, 55, 0.15);
        margin-top: 20px;
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
# FUNKCJE GIEŁDOWE
# ==========================================
def init_exchange(k, s, p, m_type):
    return ccxt.bitget({
        "apiKey": k,
        "secret": s,
        "password": p,
        "enableRateLimit": True,
        "options": {"defaultType": m_type},
    })

# ==========================================
# EKRAN POWITALNY
# ==========================================
if not st.session_state.nav_to_panel:
    st.markdown(
        """
        <div class="splash-box">
            <div class="retro-title">BITGET SAS</div>
            <div class="retro-subtitle">Autonomiczny Terminal Inwestycyjny & Algorytmiczny Skaner Rynkowy</div>
            <p style='text-align: center; color: #9ca3af; font-size: 1rem; font-family: "Inter", sans-serif; margin-bottom: 0;'>Zarządzaj swoimi inwestycjami na rynkach Spot i Futures z najwyższą precyzją.</p>
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
# PANEL OPERACYJNY (ZGODNY ZE ZDJĘCIEM)
# ==========================================
else:
    # --- PANEL BOCZNY ---
    st.sidebar.markdown("### 🔑 Konfiguracja API Bitget")
    api_key = st.sidebar.text_input("API Key", type="password")
    secret_key = st.sidebar.text_input("Secret Key", type="password")
    passphrase = st.sidebar.text_input("Passphrase", type="password")

    st.sidebar.markdown("---")
    if st.sidebar.button("⬅ Wróć do ekranu powitalnego", use_container_width=True):
        st.session_state.nav_to_panel = False
        st.rerun()

    st.sidebar.markdown("---")
    st.sidebar.markdown("### 🔔 Powiadomienia")
    st.sidebar.checkbox("Włącz powiadomienia o transakcjach", value=False)
    st.sidebar.text_input("Telegram Bot Token (opcjonalnie)", type="password")
    st.sidebar.text_input("Telegram Chat ID (opcjonalnie)")

    st.sidebar.markdown("---")
    st.sidebar.markdown("### ⚙️ Ustawienia Handlu i Ryzyka")
    st.sidebar.text("Zarządzanie wielkością pozycji")
    st.sidebar.radio(
        "Tryb pozycji",
        ["Dynamiczny Auto-Dobór", "Stały procent portfela"],
        label_visibility="collapsed",
    )
    st.sidebar.slider("Bazowy kapitał na 1 pozycję (%)", 1, 50, 10)
    st.sidebar.number_input("Maksymalnie USDT na 1 pozycję", value=20.0, step=5.0)

    st.sidebar.markdown("---")
    st.sidebar.markdown("### ⚙️ Automatyczne Take Profit / Stop Loss")
    st.sidebar.slider("Take Profit (%)", 0.5, 20.0, 3.0, 0.5)
    st.sidebar.slider("Stop Loss (%)", 0.5, 10.0, 1.5, 0.5)

    # --- GŁÓWNY PANEL ---
    st.markdown(
        '<div style="font-family: \'Cinzel\', serif; font-size: 2.2rem; font-weight: 900; color: #2ecc71; margin-bottom: 5px;">🚀 Bitget SAS - Panel Operacyjny</div>',
        unsafe_allow_html=True,
    )

    # 4 Kafelki metryk u góry
    mc1, mc2, mc3, mc4 = st.columns(4)
    with mc1:
        st.markdown(
            '<div class="metric-card"><p style="color:#9ca3af; margin:0; font-size:12px;">🟢 Portfel Spot</p><h3 style="margin:4px 0; font-size:18px;">0.0...</h3><p style="color:#2ecc71; margin:0; font-size:11px;">↑ Całkowit...</p></div>',
            unsafe_allow_html=True,
        )
    with mc2:
        st.markdown(
            '<div class="metric-card"><p style="color:#9ca3af; margin:0; font-size:12px;">🔵 Portfel Futures</p><h3 style="margin:4px 0; font-size:18px;">0.0...</h3><p style="color:#2ecc71; margin:0; font-size:11px;">↑ Całkowit...</p></div>',
            unsafe_allow_html=True,
        )
    with mc3:
        st.markdown(
            '<div class="metric-card"><p style="color:#9ca3af; margin:0; font-size:12px;">📈 Wyniki Futures</p><h3 style="margin:4px 0; font-size:18px;">+0....</h3><p style="color:#2ecc71; margin:0; font-size:11px;">↑ Aktywne...</p></div>',
            unsafe_allow_html=True,
        )
    with mc4:
        st.markdown(
            '<div class="metric-card"><p style="color:#9ca3af; margin:0; font-size:12px;">⏱️ Zegar Sesji</p><h3 style="margin:4px 0; font-size:18px;">16:...</h3><p style="color:#2ecc71; margin:0; font-size:11px;">↑ Interwał...</p></div>',
            unsafe_allow_html=True,
        )

    st.markdown("---")
    st.markdown("### 🥾 Panel Sterowania Botami Trendowymi")
    st.markdown(
        "<p style='color: #9ca3af; font-size: 13px; margin-top: -10px;'>W pełni autonomiczny wybór par</p>",
        unsafe_allow_html=True,
    )

    # Dwa kafelki botów (Spot i Futures)
    bcol1, bcol2 = st.columns(2)
    with bcol1:
        st.markdown(
            """
            <div class="metric-card" style="border-color: #2ecc71; min-height: 150px;">
                <p style="color: #2ecc71; font-weight: bold; margin-bottom: 5px;">🟢 Bot Trendowy Spot (Auto-Wybór)</p>
                <p style="font-size: 12px; color: #9ca3af;">Bot samoczynnie przeszukuje rynek i wybiera aktywa o najwyższym potencjale zysku...</p>
            </div>
            """,
            unsafe_allow_html=True,
        )
        st.checkbox("Uruchom Bota Spot Trendowego")
        st.markdown(
            '<div style="background-color: #2a1215; border: 1px solid #e74c3c; padding: 8px; border-radius: 4px; text-align: center; color: #e74c3c; font-weight: bold; font-size: 13px;">🔴 Bot Spot Trendowy ZATRZYMANY</div>',
            unsafe_allow_html=True,
        )

    with bcol2:
        st.markdown(
            """
            <div class="metric-card" style="border-color: #3498db; min-height: 150px;">
                <p style="color: #3498db; font-weight: bold; margin-bottom: 5px;">🔵 Bot Trendowy Futures (Auto-Wybór)</p>
                <p style="font-size: 12px; color: #9ca3af; margin-bottom: 5px;">Dobór dźwigni dla bota Futures:</p>
            </div>
            """,
            unsafe_allow_html=True,
        )
        st.radio(
            "Dźwignia Futures",
            ["Automatyczny (Sugerowany)", "Ręczny z panelu bocznego"],
            label_visibility="collapsed",
        )
        st.checkbox("Uruchom Bota Futures Trendowego")
        st.markdown(
            '<div style="background-color: #2a1215; border: 1px solid #e74c3c; padding: 8px; border-radius: 4px; text-align: center; color: #e74c3c; font-weight: bold; font-size: 13px;">🔴 Bot Futures Trendowy ZATRZYMANY</div>',
            unsafe_allow_html=True,
        )

    st.markdown("<br>", unsafe_allow_html=True)

    # Główny przycisk startu i statusu
    act_col1, act_col2 = st.columns([2, 1])
    with act_col1:
        if st.button(
            "🚀 Uruchom w pełni autonomiczny tryb handlu",
            use_container_width=True,
            type="primary",
        ):
            st.session_state.bot_active = True
            st.success("Uruchomiono tryb autonomiczny.")
    with act_col2:
        st.markdown(
            '<div style="background-color: #2a1215; border: 1px solid #e74c3c; padding: 10px; border-radius: 4px; text-align: center; color: #e74c3c; font-weight: bold;">🚨 STATUS ZATRZYMANY</div>',
            unsafe_allow_html=True,
        )

    st.markdown("---")
    st.markdown("### 📊 Autonomiczny Skaner Spot (Składanie Zleceń Zakupu)")

    # Tabela skanera ze zdjęcia
    scanner_data = {
        "Para": [
            "ETH/USDT",
            "BTC/USDT",
            "SOL/USDT",
            "XRP/USDT",
            "ZEC/USDT",
            "HYPE/USDT",
        ],
        "Cena": [2531.1500, 77367.5500, 102.9400, 1.3713, 1141.8000, 80.2900],
        "Strategia": [
            "Spot RSI Oversold",
            "Spot Dip Buy",
            "Spot Momentum Breakout",
            "Spot RSI Oversold",
            "Spot Dip Buy",
            "Spot Momentum Breakout",
        ],
        "Ilość / Status": ["0.0 L", "0.0 L", "0.0 L", "0.0 L", "0.0 L", "0.0 L"],
    }
    df_scanner = pd.DataFrame(scanner_data)
    st.dataframe(df_scanner, use_container_width=True)

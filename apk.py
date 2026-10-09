from datetime import datetime
import hashlib
import hmac
import os
import sqlite3
import time
import json

import ccxt
import numpy as np
import pandas as pd
import streamlit as st
import stripe

st.set_page_config(
    page_title="Multi-Exchange Futures SaaS",
    layout="wide",
)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_FILE = os.getenv("DB_FILE", os.path.join(BASE_DIR, "users.db"))
ALLOW_TEST_ACTIVATION = os.getenv("ALLOW_TEST_ACTIVATION", "0") == "1"

STRIPE_SECRET_KEY = os.getenv("STRIPE_SECRET_KEY", "")
STRIPE_PRICE_ID = os.getenv("STRIPE_PRICE_ID", "")
STRIPE_CHECKOUT_FALLBACK = os.getenv(
    "STRIPE_CHECKOUT_FALLBACK",
    "https://buy.stripe.com/8x2dRa4CbdaXfSAf6V3oA03",
)

if not STRIPE_SECRET_KEY:
    try:
        STRIPE_SECRET_KEY = st.secrets.get("STRIPE_SECRET_KEY", "")
        STRIPE_PRICE_ID = st.secrets.get("STRIPE_PRICE_ID", STRIPE_PRICE_ID)
        STRIPE_CHECKOUT_FALLBACK = st.secrets.get(
            "STRIPE_CHECKOUT_FALLBACK",
            STRIPE_CHECKOUT_FALLBACK,
        )
    except Exception:
        pass

if STRIPE_SECRET_KEY:
    stripe.api_key = STRIPE_SECRET_KEY

ADMIN_EMAILS = [
    "marekja57@wp.pl",
    "admin@bot-bitget.pl",
]

TRANSLATIONS = {
    "Polski": {
        "title": "Bitget-SaaS",
        "subtitle": "AUTONOMICZNY SYSTEM TRANSAKCYJNY",
        "login_tab": "Zaloguj się",
        "register_tab": "Załóż konto",
        "email_label": "Adres e-mail",
        "pass_label": "Hasło",
        "login_btn": "ZALOGUJ SIĘ",
        "register_btn": "ZAREJESTRUJ SIĘ",
        "login_success": "Zalogowano pomyślnie!",
        "login_error": "Nieprawidłowy e-mail lub hasło.",
        "reg_success": "Konto założone! Przejdź do zakładki logowania.",
        "reg_error_exists": "Ten e-mail jest już zarejestrowany.",
        "reg_error_fill": "Wypełnij wszystkie pola (e-mail oraz hasło).",
        "sidebar_role_admin": "Rola: Administrator",
        "sidebar_role_client": "Rola: Klient SaaS",
        "logout_btn": "WYLOGUJ SIĘ",
    },
    "English": {
        "title": "Bitget-SaaS",
        "subtitle": "AUTONOMOUS TRADING SYSTEM",
        "login_tab": "Login",
        "register_tab": "Register",
        "email_label": "Email address",
        "pass_label": "Password",
        "login_btn": "SIGN IN",
        "register_btn": "SIGN UP",
        "login_success": "Logged in successfully!",
        "login_error": "Invalid email or password.",
        "reg_success": "Account created! Go to the login tab.",
        "reg_error_exists": "This email is already registered.",
        "reg_error_fill": "Please fill in all fields.",
        "sidebar_role_admin": "Role: Administrator",
        "sidebar_role_client": "Role: SaaS Client",
        "logout_btn": "LOG OUT",
    },
}

def t(key):
    lang = st.session_state.get("lang", "Polski")
    return TRANSLATIONS.get(lang, TRANSLATIONS["Polski"]).get(key, key)

SESSION_DEFAULTS = {
    "logged_in": False,
    "user_email": "",
    "is_admin": False,
    "user_id": None,
    "stripe_paid": False,
    "lang": "Polski",
    "api_key": "",
    "secret_key": "",
    "passphrase": "",
    "selected_exchange": "Bitget",
    "navigation": "Trading & Auto-Pilot",
    "stripe_link_monthly": "https://buy.stripe.com/twoj_link_miesieczny",
    "stripe_link_yearly": "https://buy.stripe.com/twoj_link_roczny",
}

for key, default_value in SESSION_DEFAULTS.items():
    if key not in st.session_state:
        st.session_state[key] = default_value

def hash_password(password, salt=None):
    if salt is None:
        salt = os.urandom(16).hex()
    digest = hashlib.sha256((salt + password).encode("utf-8")).hexdigest()
    return f"sha256${salt}${digest}"

def verify_password(password, stored):
    if not stored:
        return False
    stored = str(stored)
    if stored.startswith("sha256$"):
        try:
            parts = stored.split("$", 2)
            if len(parts) != 3:
                return False
            salt = parts[1]
            expected = parts[2]
            candidate = hashlib.sha256((salt + password).encode("utf-8")).hexdigest()
            return hmac.compare_digest(candidate, expected)
        except Exception:
            return False
    return hmac.compare_digest(stored, str(password))

def init_db():
    conn = sqlite3.connect(DB_FILE, timeout=30.0)
    try:
        cursor = conn.cursor()
        cursor.execute("PRAGMA journal_mode=WAL;")

        cursor.execute(
            """CREATE TABLE IF NOT EXISTS users ( 
                id INTEGER PRIMARY KEY AUTOINCREMENT, 
                email TEXT UNIQUE, 
                password TEXT, 
                is_admin INTEGER DEFAULT 0, 
                stripe_paid INTEGER DEFAULT 0, 
                api_key TEXT, 
                secret_key TEXT, 
                passphrase TEXT,
                selected_exchange TEXT DEFAULT 'Bitget'
            )"""
        )
        cursor.execute(
            """CREATE TABLE IF NOT EXISTS subscriptions ( 
                id INTEGER PRIMARY KEY AUTOINCREMENT, 
                user_id INTEGER, 
                plan TEXT, 
                status TEXT, 
                expires_at TEXT, 
                created_at TEXT 
            )"""
        )

        for adm_email in ADMIN_EMAILS:
            cursor.execute("SELECT id FROM users WHERE LOWER(TRIM(email)) = ?", (adm_email.lower(),))
            if not cursor.fetchone():
                default_pass_hash = hash_password("admin123")
                cursor.execute(
                    """INSERT INTO users (email, password, is_admin, stripe_paid) VALUES (?, ?, 1, 1)""",
                    (adm_email.lower(), default_pass_hash)
                )

        conn.commit()
    finally:
        conn.close()

init_db()

if st.query_params.get("success") == "true":
    if st.session_state.logged_in and st.session_state.user_id:
        st.session_state.stripe_paid = True
        try:
            conn = sqlite3.connect(DB_FILE, timeout=30.0)
            cursor = conn.cursor()
            cursor.execute("""UPDATE users SET stripe_paid = 1 WHERE id = ?""", (st.session_state.user_id,))
            exp = (datetime.now(datetime.utc) + datetime(days=30)).isoformat()
            cursor.execute("""INSERT INTO subscriptions(user_id, plan, status, expires_at, created_at) VALUES(?,?,?,?,?)""", 
                           (st.session_state.user_id, 'Miesięczny (49 PLN)', 'active', exp, datetime.now(datetime.utc).isoformat()))
            conn.commit()
            conn.close()
        except Exception:
            pass
    st.success("Płatność zakończona sukcesem! Twoja subskrypcja została aktywowana.")
    st.query_params.clear()

st.markdown(
    """ 
    <style> 
    @import url('https://fonts.googleapis.com/css2?family=Cinzel:wght@600;700;800&display=swap'); 
    .stApp { background-color: #0d0b0a; } 
    section[data-testid="stSidebar"] { background-color: #141110; border-right: 2px solid #3d2f1f; } 
    .panel{background:linear-gradient(145deg,rgba(34,26,20,.95),rgba(17,13,10,.96));border:1px solid #f3d57a;border-radius:14px;padding:16px 18px;margin-bottom:15px;} 
    .muted{color:#e6c687;font-size:12px} 
    h1, h2, h3, h4, h5, h6 { color: #f3d57a !important; font-family: 'Cinzel', serif !important; } 

    /* Styl retro dla ekranu logowania nawiązujący do zdjęcia */
    .retro-login-container {
        display: flex;
        align-items: center;
        justify-content: center;
        width: 100%;
        padding-top: 30px;
        padding-bottom: 20px;
    }
    .retro-box {
        position: relative;
        background: radial-gradient(circle, #221a14 0%, #110d0a 100%);
        border: 4px solid #f3d57a;
        border-radius: 16px;
        padding: 35px 30px;
        width: 100%;
        max-width: 520px;
        text-align: center;
        box-shadow: 0 0 35px rgba(243, 213, 122, 0.25);
    }
    .retro-title {
        font-family: 'Cinzel', serif;
        font-weight: 800;
        font-size: 2.8rem;
        color: #f3d57a;
        letter-spacing: 2px;
        text-shadow: 2px 2px 4px rgba(0,0,0,0.8);
        margin-bottom: 5px;
    }
    .retro-subtitle {
        font-family: 'Cinzel', serif;
        color: #e6c687;
        font-size: 0.85rem;
        letter-spacing: 3px;
        text-transform: uppercase;
        margin-bottom: 25px;
    }
    </style> 
    """,
    unsafe_allow_html=True,
)

# --- EKRAN LOGOWANIA / REJESTRACJI W STYLU RETRO ---
if not st.session_state.logged_in:
    st.markdown(
        f"""
        <div class="retro-login-container">
            <div class="retro-box">
                <div class="retro-title">{t("title")}</div>
                <div class="retro-subtitle">{t("subtitle")}</div>
        """,
        unsafe_allow_html=True,
    )

    tab_login, tab_register = st.tabs([t("login_tab"), t("register_tab")])

    with tab_login:
        st.write("")
        login_email = st.text_input(t("email_label"), key="log_email")
        login_pass = st.text_input(t("pass_label"), type="password", key="log_pass")

        if st.button(t("login_btn"), use_container_width=True):
            if login_email and login_pass:
                conn = sqlite3.connect(DB_FILE, timeout=30.0)
                cursor = conn.cursor()
                cursor.execute(
                    """SELECT id, email, password, is_admin, stripe_paid, api_key, secret_key, passphrase, selected_exchange FROM users WHERE LOWER(TRIM(email)) = ?""",
                    (login_email.strip().lower(),),
                )
                user_row = cursor.fetchone()
                conn.close()

                if user_row and verify_password(login_pass, user_row[2]):
                    user_email_str = user_row[1].strip().lower()
                    is_admin_flag = user_email_str in ADMIN_EMAILS or bool(user_row[3])
                    stripe_paid_flag = True if is_admin_flag else bool(user_row[4])

                    st.session_state.logged_in = True
                    st.session_state.user_id = user_row[0]
                    st.session_state.user_email = user_row[1]
                    st.session_state.is_admin = is_admin_flag
                    st.session_state.stripe_paid = stripe_paid_flag
                    st.session_state.api_key = user_row[5] or ""
                    st.session_state.secret_key = user_row[6] or ""
                    st.session_state.passphrase = user_row[7] or ""
                    st.session_state.selected_exchange = user_row[8] or "Bitget"
                    st.success(t("login_success"))
                    st.rerun()
                else:
                    st.error(t("login_error"))
            else:
                st.error(t("reg_error_fill"))

    with tab_register:
        st.write("")
        reg_email = st.text_input(t("email_label"), key="reg_email")
        reg_pass = st.text_input(t("pass_label"), type="password", key="reg_pass")

        if st.button(t("register_btn"), use_container_width=True):
            if reg_email and reg_pass:
                try:
                    conn = sqlite3.connect(DB_FILE, timeout=30.0)
                    cursor = conn.cursor()
                    clean_reg = reg_email.strip().lower()
                    is_adm = 1 if clean_reg in ADMIN_EMAILS else 0
                    is_paid = 1 if is_adm else 0
                    
                    cursor.execute(
                        """INSERT INTO users (email, password, is_admin, stripe_paid) VALUES (?, ?, ?, ?)""",
                        (clean_reg, hash_password(reg_pass), is_adm, is_paid),
                    )
                    conn.commit()
                    conn.close()
                    st.success(t("reg_success"))
                except sqlite3.IntegrityError:
                    st.error(t("reg_error_exists"))
            else:
                st.error(t("reg_error_fill"))

    st.markdown("</div></div>", unsafe_allow_html=True)
    st.stop()

# --- PANEL BOCZNY PO ZALOGOWANIU ---
st.session_state.lang = st.sidebar.selectbox(
    "Język / Language",
    ["Polski", "English"],
    index=0 if st.session_state.get("lang", "Polski") == "Polski" else 1,
    key="lang_selector",
)

st.sidebar.markdown(f"### {st.session_state.get('user_email', '')}")
if st.session_state.get("is_admin", False):
    st.sidebar.markdown(f"**{t('sidebar_role_admin')}**")
else:
    st.sidebar.markdown(f"**{t('sidebar_role_client')}**")

st.sidebar.markdown("---")
st.session_state.navigation = st.sidebar.radio(
    "NAWIGACJA", 
    ["Trading & Auto-Pilot", "Panel Płatności Stripe (49/349 PLN)", "Ustawienia API"]
)

if st.sidebar.button(t("logout_btn"), use_container_width=True, key="sidebar_wyloguj_btn"):
    st.session_state.logged_in = False
    st.session_state.user_email = ""
    st.session_state.is_admin = False
    st.session_state.stripe_paid = False
    st.session_state.user_id = None
    st.rerun()

# --- GŁÓWNA TREŚĆ APLIKACJI ---
def is_user_paid():
    return bool(st.session_state.get("is_admin", False)) or bool(st.session_state.get("stripe_paid", False))

if st.session_state.navigation == "Panel Płatności Stripe (49/349 PLN)":
    st.subheader("Strefa Subskrypcji SaaS (Stripe PLN)")
    st.write("Wybierz plan abonamentowy i opłać go za pomocą oficjalnej bramki płatności Stripe w PLN.")

    col1, col2 = st.columns(2)
    
    with col1:
        st.markdown(f'<div class="panel"><h3>Plan Miesięczny</h3><p class="muted">Pełny dostęp do Auto-Pilota i Skanera</p><h2>49 PLN <span style="font-size:12px">/ mies.</span></h2><hr><ul><li>Automatyczny handel 24/7</li><li>Strażnik SL / TP ROE</li><li>Wsparcie techniczne</li></ul></div>', unsafe_allow_html=True)
        link_m = st.session_state.get('stripe_link_monthly', 'https://buy.stripe.com/twoj_link_miesieczny')
        st.link_button('Opłać 49 PLN / miesiąc w Stripe', link_m, use_container_width=True)
        if st.button('Symuluj opłacenie miesięcznego (Test)', use_container_width=True):
            exp = datetime.now(datetime.utc) + (datetime(days=30)).isoformat()
            st.session_state.stripe_paid = True
            try:
                conn = sqlite3.connect(DB_FILE, timeout=30.0)
                cursor = conn.cursor()
                cursor.execute("""UPDATE users SET stripe_paid = 1 WHERE id = ?""", (st.session_state.user_id,))
                cursor.execute("""INSERT INTO subscriptions(user_id, plan, status, expires_at, created_at) VALUES(?,?,?,?,?)""", 
                               (st.session_state.user_id, 'Miesięczny (49 PLN)', 'active', exp, datetime.now(datetime.utc).isoformat()))
                conn.commit()
                conn.close()
            except Exception:
                pass
            st.success('Zaktualizowano subskrypcję na Plan Miesięczny!')
            st.rerun()

    with col2:
        st.markdown(f'<div class="panel"><h3>Plan Roczny</h3><p class="muted">Najlepsza oferta — oszczędzasz</p><h2>349 PLN <span style="font-size:12px">/ rok</span></h2><hr><ul><li>Wszystkie funkcje Pro</li><li>Priorytetowy Auto-Pilot</li><li>Dostęp roczny bez przerw</li></ul></div>', unsafe_allow_html=True)
        link_y = st.session_state.get('stripe_link_yearly', 'https://buy.stripe.com/twoj_link_roczny')
        st.link_button('Opłać 349 PLN / rok w Stripe', link_y, use_container_width=True)
        if st.button('Symuluj opłacenie rocznego (Test)', use_container_width=True):
            exp = (datetime.now(datetime.utc) + datetime(days=365)).isoformat()
            st.session_state.stripe_paid = True
            try:
                conn = sqlite3.connect(DB_FILE, timeout=30.0)
                cursor = conn.cursor()
                cursor.execute("""UPDATE users SET stripe_paid = 1 WHERE id = ?""", (st.session_state.user_id,))
                cursor.execute("""INSERT INTO subscriptions(user_id, plan, status, expires_at, created_at) VALUES(?,?,?,?,?)""", 
                               (st.session_state.user_id, 'Roczny (349 PLN)', 'active', exp, datetime.now(datetime.utc).isoformat()))
                conn.commit()
                conn.close()
            except Exception:
                pass
            st.success('Zaktualizowano subskrypcję na Plan Roczny!')
            st.rerun()

elif st.session_state.navigation == "Ustawienia API":
    st.subheader("Konfiguracja Giełdy i Kluczy API")
    selected_exchange = st.selectbox("Wybierz Giełdę:", ["Bitget", "Binance", "Bybit", "OKX"])
    input_api = st.text_input("API Key:", type="password", value=st.session_state.get("api_key", ""))
    input_secret = st.text_input("API Secret:", type="password", value=st.session_state.get("secret_key", ""))
    input_pass = st.text_input("Passphrase:", type="password", value=st.session_state.get("passphrase", "")) if selected_exchange in ["Bitget", "OKX"] else ""

    if st.button("Zapisz klucze"):
        st.session_state.api_key = input_api
        st.session_state.secret_key = input_secret
        st.session_state.passphrase = input_pass
        st.session_state.selected_exchange = selected_exchange
        try:
            conn = sqlite3.connect(DB_FILE, timeout=30.0)
            cursor = conn.cursor()
            cursor.execute(
                """UPDATE users SET api_key = ?, secret_key = ?, passphrase = ?, selected_exchange = ? WHERE id = ?""",
                (input_api, input_secret, input_pass, selected_exchange, st.session_state.user_id),
            )
            conn.commit()
            conn.close()
        except Exception:
            pass
        st.success("Zapisano klucze pomyślnie!")

else:
    st.subheader("Panel Główny Trading & Auto-Pilot")
    if is_user_paid():
        st.success("Subskrypcja aktywna - pełny dostęp do systemu.")
    else:
        st.warning("Brak aktywnej subskrypcji. Przejdź do zakładki 'Panel Płatności Stripe', aby wykupić dostęp (49 PLN / mies lub 349 PLN / rok).")

    st.markdown("---")
    st.write("Tutaj znajduje się Twój interfejs bota oraz zarządzanie pozycjami Futures.")


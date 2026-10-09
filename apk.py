import os, json, sqlite3, time, math, logging
from pathlib import Path
from datetime import datetime, timezone
import pandas as pd
import numpy as np
import streamlit as st
try:
    import ccxt
except ImportError:
    ccxt = None

APP_DIR = Path(__file__).resolve().parent
DB_PATH = Path(os.getenv('BITGET_SAAS_DB', APP_DIR / 'bitget_saas.db'))
DB_FILE = DB_PATH
LOG_PATH = APP_DIR / 'trading.log'

logging.basicConfig(filename=LOG_PATH, level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')

DEFAULTS = {
    'exchange': 'bitget', 'market_type': 'swap', 'candle_limit': 180,
    'refresh_seconds': 30, 'risk_usdt': 10.0, 'max_positions': 3, 'max_leverage': 10, 'sl_roe': 20.0, 'tp_roe': 40.0, 'enable_roe': True,
    'timeframes': ['4h', '1d'],
    'tf_settings': {
        '1m': {'ema_fast': 9, 'ema_slow': 21, 'adx_threshold': 25.0, 'rsi_min': 25.0, 'rsi_max': 75.0},
        '3m': {'ema_fast': 9, 'ema_slow': 21, 'adx_threshold': 25.0, 'rsi_min': 25.0, 'rsi_max': 75.0},
        '5m': {'ema_fast': 9, 'ema_slow': 21, 'adx_threshold': 25.0, 'rsi_min': 25.0, 'rsi_max': 75.0},
        '15m': {'ema_fast': 9, 'ema_slow': 21, 'adx_threshold': 25.0, 'rsi_min': 25.0, 'rsi_max': 75.0},
        '30m': {'ema_fast': 9, 'ema_slow': 21, 'adx_threshold': 25.0, 'rsi_min': 25.0, 'rsi_max': 75.0},
        '1h': {'ema_fast': 12, 'ema_slow': 26, 'adx_threshold': 22.0, 'rsi_min': 30.0, 'rsi_max': 70.0},
        '2h': {'ema_fast': 12, 'ema_slow': 26, 'adx_threshold': 20.0, 'rsi_min': 30.0, 'rsi_max': 70.0},
        '4h': {'ema_fast': 20, 'ema_slow': 50, 'adx_threshold': 20.0, 'rsi_min': 30.0, 'rsi_max': 70.0},
        '1d': {'ema_fast': 40, 'ema_slow': 140, 'adx_threshold': 15.0, 'rsi_min': 35.0, 'rsi_max': 65.0}
    },
    'auto_refresh': True, 'refresh_seconds': 30, 'auto_trade': False, 'paper_mode': True,
    'max_notional_usdt': 50.0, 'cooldown_seconds': 300, 'allow_short': True, 'allow_long': True, 'scan_limit_count': 30,
    'indicator_multiplier': 60
}

TF_OPTIONS = ['1m', '3m', '5m', '15m', '30m', '1h', '2h', '4h', '1d']
ALLOW_TEST_ACTIVATION = True
STRIPE_PRICE_ID_VAL = "price_1M_49pln_placeholder"

CSS = '''
<style>
:root { color-scheme: dark; }
.stApp { background: radial-gradient(ellipse at 40% -20%, #103e78 0%, #071a36 42%, #050e20 100%); color: #eaf3ff; }
[data-testid="stHeader"] { background: rgba(3,12,29,.85); }
[data-testid="stSidebar"] { background: linear-gradient(180deg, #06152d, #081f42); border-right: 1px solid #164a84; }
.block-container { padding-top: 1.2rem; max-width: 1600px; }

.brand-retro {
    font-weight: 900;
    font-size: 38px;
    letter-spacing: -1px;
    color: #f3c653;
    text-shadow: 2px 2px 4px rgba(0,0,0,0.6);
    text-align: center;
    margin-bottom: 0px;
    font-family: serif;
}
.subbrand-retro {
    color: #7da9d8;
    font-size: 12px;
    letter-spacing: 2px;
    text-transform: uppercase;
    text-align: center;
    margin-bottom: 20px;
}

.brand { font-weight: 900; letter-spacing: -1px; font-size: 29px; color: #eaf5ff; }
.brand span { color: #28a8ff; }
.subbrand { color: #7da9d8; font-size: 11px; letter-spacing: 2px; text-transform: uppercase; }
.panel {
    background: linear-gradient(145deg, rgba(12,43,83,.95), rgba(5,24,51,.96));
    border: 1px solid #164a80;
    border-radius: 14px;
    padding: 16px 18px;
    box-shadow: 0 4px 12px rgba(0,0,0,0.3);
}
.metric-label { font-size: 12px; color: #90b8e6; text-transform: uppercase; letter-spacing: 1px; }
.metric-value { font-size: 24px; font-weight: 800; color: #f1f7ff; margin-top: 5px; }
.muted { color: #83a7d0; font-size: 12px; margin-top: 4px; }
div.stButton>button {
    border: 1px solid #278be8;
    border-radius: 8px;
    background: linear-gradient(180deg, #1689ff, #0759c8);
    color: white;
    font-weight: 700;
}
hr { border-color: #16416f; }
</style>
'''

st.set_page_config(page_title='Bitget-SaaS Futures', page_icon='📈', layout='wide')
st.markdown(CSS, unsafe_allow_html=True)

def db():
    c = sqlite3.connect(DB_PATH, timeout=15)
    c.execute('PRAGMA journal_mode=WAL')
    c.execute('PRAGMA busy_timeout=15000')
    c.execute('CREATE TABLE IF NOT EXISTS settings (k TEXT PRIMARY KEY, v TEXT NOT NULL)')
    c.execute('CREATE TABLE IF NOT EXISTS credentials (k TEXT PRIMARY KEY, exchange TEXT, api_key TEXT, secret TEXT, password TEXT)')
    c.execute('CREATE TABLE IF NOT EXISTS bot_state (symbol TEXT PRIMARY KEY, side TEXT, entry REAL, amount REAL, opened REAL, sl REAL, tp REAL, order_id TEXT)')
    c.execute('CREATE TABLE IF NOT EXISTS events (id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT, level TEXT, message TEXT)')
    
    cursor = c.cursor()
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='users'")
    table_exists = cursor.fetchone()
    
    if not table_exists:
        c.execute('CREATE TABLE users (id INTEGER PRIMARY KEY AUTOINCREMENT, username TEXT UNIQUE, password TEXT, subscription TEXT, stripe_paid INTEGER DEFAULT 0, email TEXT)')
    else:
        cursor.execute("PRAGMA table_info(users)")
        columns = [col[1] for col in cursor.fetchall()]
        if 'id' not in columns:
            cursor.execute("DROP TABLE users")
            c.commit()
            c.execute('CREATE TABLE users (id INTEGER PRIMARY KEY AUTOINCREMENT, username TEXT UNIQUE, password TEXT, subscription TEXT, stripe_paid INTEGER DEFAULT 0, email TEXT)')
        else:
            if 'email' not in columns:
                cursor.execute("ALTER TABLE users ADD COLUMN email TEXT")
            if 'stripe_paid' not in columns:
                cursor.execute("ALTER TABLE users ADD COLUMN stripe_paid INTEGER DEFAULT 0")
    c.commit()
    return c

def load_cfg():
    out = DEFAULTS.copy()
    with db() as c:
        r = c.execute('SELECT v FROM settings WHERE k="main"').fetchone()
    if r:
        try: out.update(json.loads(r[0]))
        except Exception: pass
    return out

def save_cfg(cfg):
    with db() as c:
        c.execute('INSERT INTO settings(k,v) VALUES(?,?) ON CONFLICT(k) DO UPDATE SET v=excluded.v', ('main', json.dumps(cfg)))

def event(level, msg):
    logging.log(getattr(logging, level, logging.INFO), msg)
    with db() as c:
        c.execute('INSERT INTO events(ts,level,message) VALUES(?,?,?)', (datetime.now(timezone.utc).isoformat(), level, msg[:1500]))

def load_creds():
    with db() as c:
        r = c.execute('SELECT exchange,api_key,secret,password FROM credentials WHERE k="main"').fetchone()
    return r or ('bitget', '', '', '')

def save_creds(ex, key, secret, pw):
    with db() as c:
        c.execute('INSERT INTO credentials(k,exchange,api_key,secret,password) VALUES("main",?,?,?,?) ON CONFLICT(k) DO UPDATE SET exchange=excluded.exchange,api_key=excluded.api_key,secret=excluded.secret,password=excluded.password', (ex, key, secret, pw))

@st.cache_resource(show_spinner=False)
def exchange_client(ex_id, api_key, secret, password, market_type):
    if ccxt is None: raise RuntimeError('Brak ccxt.')
    cls = getattr(ccxt, ex_id, None)
    if cls is None: raise ValueError('Nieobsługiwana giełda: ' + ex_id)
    opts = {'enableRateLimit': True, 'timeout': 20000, 'options': {'defaultType': market_type, 'defaultSubType': 'linear'}}
    if api_key and secret: opts.update(apiKey=api_key, secret=secret)
    if password: opts['password'] = password
    return cls(opts)

@st.cache_data(ttl=20, show_spinner=False)
def get_candles(ex_id, market_type, symbol, tf, limit):
    ex = exchange_client(ex_id, '', '', '', market_type)
    raw = ex.fetch_ohlcv(symbol, timeframe=tf, limit=int(limit))
    return pd.DataFrame(raw, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])

def indicators(df, fast, slow):
    d = df.copy()
    for col in ['open', 'high', 'low', 'close', 'volume']: d[col] = pd.to_numeric(d[col], errors='coerce')
    d = d.dropna(subset=['high', 'low', 'close']).reset_index(drop=True)
    d['ema_fast'] = d.close.ewm(span=int(fast), adjust=False).mean()
    d['ema_slow'] = d.close.ewm(span=int(slow), adjust=False).mean()
    delta = d.close.diff(); gain = delta.clip(lower=0).ewm(alpha=1/14, adjust=False).mean(); loss = (-delta.clip(upper=0)).ewm(alpha=1/14, adjust=False).mean()
    d['rsi'] = 100 - 100 / (1 + gain / loss.replace(0, np.nan))
    tr = pd.concat([(d.high - d.low).abs(), (d.high - d.close.shift()).abs(), (d.low - d.close.shift()).abs()], axis=1).max(axis=1)
    up = d.high.diff(); down = -d.low.diff()
    plus = pd.Series(np.where((up > down) & (up > 0), up, 0), index=d.index)
    minus = pd.Series(np.where((down > up) & (down > 0), down, 0), index=d.index)
    atr = tr.ewm(alpha=1/14, adjust=False).mean().replace(0, np.nan)
    pdi = 100 * plus.ewm(alpha=1/14, adjust=False).mean() / atr
    mdi = 100 * minus.ewm(alpha=1/14, adjust=False).mean() / atr
    d['adx'] = (100 * (pdi - mdi).abs() / (pdi + mdi).replace(0, np.nan)).ewm(alpha=1/14, adjust=False).mean()
    return d

def get_effective_tf_cfg(cfg, tf):
    base_tf_cfg = cfg.get('tf_settings', {}).get(tf, {'ema_fast': 9, 'ema_slow': 21, 'adx_threshold': 25.0, 'rsi_min': 25.0, 'rsi_max': 75.0})
    mult = float(cfg.get('indicator_multiplier', 60)) / 100.0
    return {
        'ema_fast': max(2, int(round(base_tf_cfg['ema_fast'] * mult))),
        'ema_slow': max(3, int(round(base_tf_cfg['ema_slow'] * mult))),
        'adx_threshold': max(2.0, min(90.0, base_tf_cfg['adx_threshold'] * mult)),
        'rsi_min': max(2.0, min(45.0, base_tf_cfg['rsi_min'] * mult)),
        'rsi_max': max(55.0, min(98.0, base_tf_cfg['rsi_max'] * mult))
    }

def signal_for_symbol(cfg, symbol, tf):
    try:
        tf_cfg = get_effective_tf_cfg(cfg, tf)
        raw = get_candles(cfg['exchange'], cfg['market_type'], symbol, tf, cfg['candle_limit'])
        d = indicators(raw.iloc[:-1].copy(), tf_cfg['ema_fast'], tf_cfg['ema_slow'])
        if len(d) < max(20, 35): return {'symbol': symbol, 'tf': tf, 'signal': 'NEUTRALNY', 'reason': 'Za mało świec'}
        r = d.iloc[-1]
        trend_up = r.ema_fast > r.ema_slow
        trend_down = r.ema_fast < r.ema_slow
        long_ok = cfg['allow_long'] and trend_up and r.adx >= tf_cfg['adx_threshold'] and tf_cfg['rsi_min'] <= r.rsi <= tf_cfg['rsi_max'] and r.close > r.ema_fast
        short_ok = cfg['allow_short'] and trend_down and r.adx >= tf_cfg['adx_threshold'] and tf_cfg['rsi_min'] <= r.rsi <= tf_cfg['rsi_max'] and r.close < r.ema_fast
        
        if long_ok:
            sig = 'LONG'
        elif short_ok:
            sig = 'SHORT'
        else:
            sig = 'NEUTRALNY'
            
        return {'symbol': symbol, 'tf': tf, 'signal': sig, 'price': float(r.close), 'adx': float(r.adx), 'rsi': float(r.rsi), 'reason': 'OK'}
    except Exception as e:
        return {'symbol': symbol, 'tf': tf, 'signal': 'BŁĄD', 'reason': str(e)[:100]}

def market_order(ex, symbol, side, qty, reduce_only=False):
    qty = float(ex.amount_to_precision(symbol, qty))
    if qty <= 0: raise ValueError('Ilość zerowa')
    params = {'reduceOnly': True} if reduce_only else {}
    return ex.create_order(symbol, 'market', side, qty, None, params)

def calc_qty(ex, symbol, total_usdt, free_usdt, price, cfg):
    max_lev = int(cfg['max_leverage'])
    auto_risk = total_usdt * 0.02
    risk = min(float(cfg['risk_usdt']), auto_risk)
    
    stop_fraction = max(0.001, (float(cfg['sl_roe']) / 100.0) / max_lev)
    notional = min(risk / stop_fraction, float(cfg['max_notional_usdt']), max(0.0, free_usdt) * max_lev * 0.90)
    
    market = ex.market(symbol)
    contract = float(market.get('contractSize') or 1)
    qty = notional / max(price * contract, 1e-12)
    qty = float(ex.amount_to_precision(symbol, qty))
    return qty, notional

def balance_usdt(ex):
    b = ex.fetch_balance()
    row = b.get('USDT') or {}
    return float(row.get('free') or 0), float(row.get('total') or 0)

def is_user_admin():
    email = str(st.session_state.get('user_email', '')).strip().lower()
    uname = str(st.session_state.get('username', '')).strip().lower()
    return email == 'marekja57@wp.pl' or uname == 'admin'

def is_user_paid():
    return bool(st.session_state.get('stripe_paid', 0)) or is_user_admin()

def create_stripe_checkout_session(email, price_id):
    return f"https://checkout.stripe.com/pay/{price_id}?client_reference_id={email}"

if 'authenticated' not in st.session_state:
    st.session_state['authenticated'] = False
    st.session_state['username'] = ''
    st.session_state['user_id'] = None
    st.session_state['stripe_paid'] = 0
    st.session_state['user_email'] = ''
    st.session_state['logged_in'] = False

# ========================================================
# OBSŁUGA POWROTU ZE STRIPE (z Twoich zdjęć)
# ========================================================
if st.query_params.get("success") == "true":
    if st.session_state.get("logged_in") and st.session_state.get("user_id"):
        st.session_state.stripe_paid = True
        try:
            conn = sqlite3.connect(DB_FILE, timeout=30.0)
            cursor = conn.cursor()
            cursor.execute(
                """ UPDATE users SET stripe_paid = 1 WHERE id = ? """,
                (st.session_state.user_id,),
            )
            conn.commit()
            conn.close()
        except Exception:
            pass
        st.success(
            "🎉 Płatność zakończona sukcesem! "
            "Twoja subskrypcja została aktywowana."
        )
        st.query_params.clear()

if not st.session_state['authenticated']:
    st.markdown('<div class="brand-retro">Bitget-SaaS</div><div class="subbrand-retro">AUTONOMICZNY SYSTEM TRANSAKCYJNY</div>', unsafe_allow_html=True)
    
    tab_login, tab_reg = st.tabs(["Zaloguj się", "Załóż konto i subskrypcję"])
    
    with tab_login:
        st.subheader("Logowanie do systemu")
        with st.form("login_form"):
            l_user = st.text_input("Nazwa użytkownika / E-mail")
            l_pass = st.text_input("Hasło", type="password")
            submit_login = st.form_submit_button("ZALOGUJ SIĘ", use_container_width=True)
            if submit_login:
                with db() as c:
                    row = c.execute("SELECT id, password, stripe_paid, email, username FROM users WHERE username=? OR email=?", (l_user, l_user)).fetchone()
                if row and row[1] == l_pass:
                    st.session_state['authenticated'] = True
                    st.session_state['logged_in'] = True
                    st.session_state['user_id'] = row[0]
                    st.session_state['password'] = row[1]
                    st.session_state['stripe_paid'] = row[2]
                    st.session_state['user_email'] = row[3] or f"{l_user}@wp.pl"
                    st.session_state['username'] = row[4]
                    st.success("Zalogowano pomyślnie!")
                    st.rerun()
                else:
                    st.error("Nieprawidłowy login lub hasło.")

    with tab_reg:
        st.subheader("Rejestracja użytkownika i subskrypcja (49 PLN / mies.)")
        with st.form("reg_form"):
            r_user = st.text_input("Nazwa użytkownika")
            r_email = st.text_input("Adres E-mail", value="marekja57@wp.pl")
            r_pass = st.text_input("Hasło", type="password")
            r_sub = st.selectbox("Wybierz subskrypcję", ["Pro Trader (49 PLN / miesiąc)", "VIP SaaS (Roczny)"])
            submit_reg = st.form_submit_button("ZAREJESTRUJ SIĘ", use_container_width=True)
            if submit_reg:
                if not r_user.strip() or not r_pass.strip():
                    st.error("Uzupełnij login i hasło.")
                else:
                    try:
                        with db() as c:
                            c.execute("INSERT INTO users(username, password, subscription, stripe_paid, email) VALUES(?,?,?,0,?)", (r_user.strip(), r_pass.strip(), r_sub, r_email.strip()))
                            c.commit()
                        st.success("Konto utworzone pomyślnie! Możesz się teraz zalogować.")
                    except sqlite3.IntegrityError:
                        st.error("Taki użytkownik już istnieje.")
    st.stop()

cfg = load_cfg()
creds = load_creds()
ex_id, key, secret, password = creds

with st.sidebar:
    st.markdown(f'<div class="brand"><span>⚡</span> Bitget-SaaS</div><div class="subbrand">Witaj, {st.session_state["username"]}</div>', unsafe_allow_html=True)
    page = st.radio('NAWIGACJA', ['Automatyczny Skaner i Auto-Handel', 'Panel Sesji i Kapitału', 'Ustawienia Strategii', 'Połączenie API', 'Dziennik'])
    
    st.sidebar.markdown("---")
    st.sidebar.markdown("### Status Subskrypcji (49 PLN)")
    
    if is_user_admin():
        st.sidebar.success("Administrator (Pełny Dostęp)")
    elif is_user_paid():
        st.sidebar.success("Subskrypcja aktywna (Pro)")
    else:
        st.sidebar.warning("Subskrypcja nieopłacona")
        checkout_url = create_stripe_checkout_session(st.session_state.get("user_email", "user@bitget.local"), STRIPE_PRICE_ID_VAL)
        st.sidebar.link_button("OPŁAĆ SUBSKRYPCJĘ (49 PLN)", checkout_url, use_container_width=True)
    
    if ALLOW_TEST_ACTIVATION and not is_user_admin():
        if st.sidebar.button("⚡ [TEST] Aktywuj dostęp natychmiast", use_container_width=True):
            st.session_state['stripe_paid'] = 1
            try:
                with db() as conn:
                    cursor = conn.cursor()
                    cursor.execute("UPDATE users SET stripe_paid = 1 WHERE id = ?", (st.session_state.user_id,))
                    conn.commit()
            except Exception:
                pass
            st.success("Subskrypcja aktywowana testowo!")
            st.rerun()
            
    st.divider()
    if st.button('Wyloguj', use_container_width=True):
        st.session_state['authenticated'] = False
        st.session_state['logged_in'] = False
        st.session_state['username'] = ''
        st.rerun()
    if st.button('Wyczyść cache danych', use_container_width=True):
        get_candles.clear()
        st.success('Cache danych wyczyszczony.')

st.markdown('<div class="brand"><span>Bitget</span>-SaaS Futures</div><div class="subbrand">AUTONOMICZNY SYSTEM TRANSAKCYJNY</div>', unsafe_allow_html=True)

if page == 'Automatyczny Skaner i Auto-Handel':
    st.subheader('Automatyczny Skaner Rynku i Cykliczny Auto-Handel')
    st.write('Bot samoczynnie w pętli skanuje wybrane pary i interwały w ustalonych odstępach czasu.')
    
    with st.form('control_form'):
        cfg['auto_trade'] = st.checkbox('Włącz automatyczny handel (Auto-Trade)', value=bool(cfg['auto_trade']))
        cfg['paper_mode'] = st.checkbox('Tryb symulacji PAPER (brak zleceń na żywo)', value=bool(cfg['paper_mode']))
        cfg['auto_refresh'] = st.checkbox('Włącz ciągłą pętlę automatycznego skanowania w tle', value=bool(cfg.get('auto_refresh', True)))
        cfg['refresh_seconds'] = st.slider('Odstęp czasu między skanami giełdy (sekundy)', 10, 300, int(cfg.get('refresh_seconds', 30)))
        submit_ctrl = st.form_submit_button('ZAPISZ TRYB PRACY', use_container_width=True)
        if submit_ctrl:
            save_cfg(cfg)
            st.success('Zapisano tryb pracy bota.')
            st.rerun()

    st.markdown('---')
    st.markdown('### Status i uruchomienie skanowania')
    
    try:
        ex = exchange_client(ex_id, key, secret, password, cfg['market_type'])
        markets = ex.load_markets()
        
        all_symbols = [s for s, m in markets.items() if m.get('quote') == 'USDT' and m.get('active') and m.get('linear')]
        target_symbols = all_symbols[:int(cfg.get('scan_limit_count', 30))]
        target_tfs = cfg.get('timeframes', ['4h', '1d'])
        
        st.info(f'Skanowanie {len(target_symbols)} par na interwałach: {", ".join(target_tfs)}...')
        
        results = []
        free, total = balance_usdt(ex) if not cfg['paper_mode'] else (1000.0, 1000.0)
        
        for symbol in target_symbols:
            for tf in target_tfs:
                res = signal_for_symbol(cfg, symbol, tf)
                results.append(res)
                
                sig = res['signal']
                if sig in ('LONG', 'SHORT'):
                    event('INFO', f'Skaner: Sygnał {sig} na {symbol} [{tf}] (ADX: {res["adx"]:.1f}, RSI: {res["rsi"]:.1f})')
                    
                    if cfg['auto_trade']:
                        if cfg['paper_mode']:
                            event('TRADE', f'[PAPER] Automatyczne otwarcie {sig} na {symbol} [{tf}]')
                        else:
                            max_lev = int(cfg['max_leverage'])
                            qty, notional = calc_qty(ex, symbol, total, free, res['price'], cfg)
                            try:
                                ex.set_leverage(min(max_lev, int(cfg['max_leverage'])), symbol)
                            except Exception:
                                pass
                            side = 'buy' if sig == 'LONG' else 'sell'
                            order = market_order(ex, symbol, side, qty, False)
                            event('TRADE', f'AUTOMATYCZNIE OTWARTO {sig} {symbol} [{tf}] qty={qty} id={order.get("id")}')
        
        st.success('Cykl skanowania zakończony pomyślnie!')
        st.dataframe(pd.DataFrame(results), use_container_width=True, hide_index=True)
        
    except Exception as e:
        st.error(f'Błąd podczas skanowania giełdy: {e}')

    if cfg.get('auto_refresh') and cfg.get('auto_trade'):
        sec = int(cfg.get('refresh_seconds', 30))
        st.warning(f'Bot działa w pętli automatycznej. Kolejny skan za {sec} sekund...')
        time.sleep(sec)
        st.rerun()

elif page == 'Ustawienia Strategii':
    st.subheader('Niezależne ustawienia strategii, automatyczna adaptacja i ryzyko')
    
    if 'tf_settings' not in cfg:
        cfg['tf_settings'] = DEFAULTS['tf_settings']
        
    if 'selected_tf_edit' not in st.session_state:
        st.session_state['selected_tf_edit'] = '1d'

    def update_tf_selection():
        st.session_state['selected_tf_edit'] = st.session_state['tf_selectbox_key']

    selected_tf_tab = st.selectbox(
        'Wybierz interwał do edycji parametrów bazowych', 
        TF_OPTIONS, 
        index=TF_OPTIONS.index(st.session_state['selected_tf_edit']) if st.session_state['selected_tf_edit'] in TF_OPTIONS else 8,
        key='tf_selectbox_key',
        on_change=update_tf_selection
    )

    base_tf_cfg = cfg['tf_settings'].get(selected_tf_tab, {'ema_fast': 9, 'ema_slow': 21, 'adx_threshold': 25.0, 'rsi_min': 25.0, 'rsi_max': 75.0})

    with st.form('cfgform'):
        a, b = st.columns(2)
        with a:
            cfg['exchange'] = st.selectbox('Giełda', ['bitget', 'binanceusdm', 'bybit', 'okx'], index=['bitget', 'binanceusdm', 'bybit', 'okx'].index(cfg['exchange']) if cfg['exchange'] in ['bitget', 'binanceusdm', 'bybit', 'okx'] else 0)
            cfg['market_type'] = st.selectbox('Rynek', ['swap', 'future'], index=0 if cfg['market_type'] == 'swap' else 1)
            cfg['scan_limit_count'] = st.slider('Suwak limitu skanowanych par z giełdy', 5, 50, int(cfg.get('scan_limit_count', 30)))
            cfg['timeframes'] = st.multiselect('Interwały do skanowania w tle', TF_OPTIONS, default=[x for x in cfg.get('timeframes', ['4h', '1d']) if x in TF_OPTIONS] or ['4h', '1d'])
            cfg['indicator_multiplier'] = st.slider('Automatyczny multiplikator wskaźników (%)', 0, 100, int(cfg.get('indicator_multiplier', 60)), help="Skala od 0 do 100% określająca stopień automatycznego dostrajania wskaźników przez bota.")
        with b:
            cfg['risk_usdt'] = st.number_input('Maks. ryzyko na pozycję (USDT)', 1.0, 10000.0, float(cfg['risk_usdt']))
            cfg['max_positions'] = st.number_input('Maks. otwarte pozycje (sloty)', 1, 20, int(cfg['max_positions']))
            cfg['max_leverage'] = st.number_input('Maksymalna dźwignia (auto-dopasowanie i limit)', 1, 50, int(cfg['max_leverage']))
            cfg['sl_roe'] = st.number_input('Stop-loss ROE (%)', 1.0, 95.0, float(cfg['sl_roe']))
            cfg['tp_roe'] = st.number_input('Take-profit ROE (%)', 1.0, 500.0, float(cfg['tp_roe']))
            cfg['allow_long'] = st.checkbox('Pozwól na LONG', cfg['allow_long'])
            cfg['allow_short'] = st.checkbox('Pozwól na SHORT', cfg['allow_short'])
        
        st.markdown('---')
        st.markdown(f'### Bazowa konfiguracja dla interwału: {selected_tf_tab}')
        
        c1, c2, c3, c4, c5 = st.columns(5)
        with c1: f_fast = st.number_input(f'EMA szybka ({selected_tf_tab})', 2, 100, int(base_tf_cfg.get('ema_fast', 9)))
        with c2: f_slow = st.number_input(f'EMA wolna ({selected_tf_tab})', 3, 300, int(base_tf_cfg.get('ema_slow', 21)))
        with c3: f_adx = st.number_input(f'Min. ADX ({selected_tf_tab})', 0.0, 100.0, float(base_tf_cfg.get('adx_threshold', 25.0)))
        with c4: f_rmin = st.number_input(f'RSI min ({selected_tf_tab})', 0.0, 100.0, float(base_tf_cfg.get('rsi_min', 25.0)))
        with c5: f_rmax = st.number_input(f'RSI max ({selected_tf_tab})', 0.0, 100.0, float(base_tf_cfg.get('rsi_max', 75.0)))
            
        submitted = st.form_submit_button(f'ZAPISZ USTAWIENIA DLA {selected_tf_tab}', use_container_width=True)
    if submitted:
        cfg['tf_settings'][selected_tf_tab] = {'ema_fast': f_fast, 'ema_slow': f_slow, 'adx_threshold': f_adx, 'rsi_min': f_rmin, 'rsi_max': f_rmax}
        save_cfg(cfg)
        st.success(f'Zapisano parametry dla interwału {selected_tf_tab}!')
        st.rerun()

elif page == 'Połączenie API':
    st.subheader('Połączenie giełdowe')
    with st.form('credentials'):
        ex = st.selectbox('Giełda', ['bitget', 'binanceusdm', 'bybit', 'okx'], index=['bitget', 'binanceusdm', 'bybit', 'okx'].index(ex_id) if ex_id in ['bitget', 'binanceusdm', 'bybit', 'okx'] else 0)
        k = st.text_input('API Key', value=key, type='password')
        s = st.text_input('API Secret', value=secret, type='password')
        pw = st.text_input('Passphrase (Bitget/OKX)', value=password, type='password')
        save = st.form_submit_button('ZAPISZ DANE API')
    if save:
        save_creds(ex, k.strip(), s.strip(), pw.strip())
        exchange_client.clear()
        st.success('Dane zapisane.')
        st.rerun()
    if st.button('Testuj API / pobierz saldo'):
        try:
            ex = exchange_client(ex_id, key, secret, password, cfg['market_type'])
            free, total = balance_usdt(ex)
            st.success('Połączenie działa')
            x, y = st.columns(2)
            x.metric('USDT dostępne', f'{free:.2f}')
            y.metric('USDT łącznie', f'{total:.2f}')
        except Exception as e:
            st.error(f'Błąd API: {e}')

elif page == 'Dziennik':
    st.subheader('Zdarzenia i zlecenia bota')
    with db() as con: rows = con.execute('SELECT ts,level,message FROM events ORDER BY id DESC LIMIT 200').fetchall()
    if rows: st.dataframe(pd.DataFrame(rows, columns=['UTC', 'Poziom', 'Wiadomość']), use_container_width=True, hide_index=True)
    else: st.info('Brak zdarzeń.')

else:
    st.subheader('Panel Sesji i Analiza Kapitału')
    st.write('Statystyki Twoich środków, slotów oraz wynik finansowy bieżącej sesji handlowej.')
    
    total_bal, free_bal, active_slots, session_pnl, used_margin = 1000.0, 1000.0, 0, 0.0, 0.0
    try:
        if key and secret:
            ex = exchange_client(ex_id, key, secret, password, cfg['market_type'])
            _, total_bal = balance_usdt(ex)
            positions = ex.fetch_positions()
            active_pos = [p for p in positions or [] if abs(float(p.get('contracts') or 0)) > 0]
            active_slots = len(active_pos)
            session_pnl = sum(float(p.get('unrealizedPnl') or 0) for p in active_pos)
            used_margin = sum(float(p.get('initialMargin') or p.get('margin') or 0) for p in active_pos)
            free_bal = max(0.0, total_bal - used_margin)
    except Exception:
        pass

    max_slots = int(cfg['max_positions'])
    free_slots = max(0, max_slots - active_slots)

    col1, col2, col3, col4 = st.columns(4)
    with col1:
        st.markdown(f'''
        <div class="panel">
            <div class="metric-label">Kapitał / Saldo Całkowite</div>
            <div class="metric-value">{total_bal:.2f} USDT</div>
            <div class="muted">Wolne: {free_bal:.2f} USDT</div>
        </div>
        ''', unsafe_allow_html=True)
    with col2:
        st.markdown(f'''
        <div class="panel">
            <div class="metric-label">Sloty Pozycji</div>
            <div class="metric-value">{active_slots} / {max_slots}</div>
            <div class="muted">Wolne sloty: {free_slots}</div>
        </div>
        ''', unsafe_allow_html=True)
    with col3:
        pnl_color = "#28a8ff" if session_pnl >= 0 else "#ff4d4d"
        st.markdown(f'''
        <div class="panel">
            <div class="metric-label">Wynik Sesji (PnL)</div>
            <div class="metric-value" style="color: {pnl_color};">{session_pnl:+.2f} USDT</div>
            <div class="muted">Niezrealizowany PnL</div>
        </div>
        ''', unsafe_allow_html=True)
    with col4:
        st.markdown(f'''
        <div class="panel">
            <div class="metric-label">Status Autopilota</div>
            <div class="metric-value">{"WŁĄCZONY" if cfg["auto_trade"] else "WYŁĄCZONY"}</div>
            <div class="muted">Tryb: {"PAPER" if cfg["paper_mode"] else "LIVE"}</div>
        </div>
        ''', unsafe_allow_html=True)

    st.write('')
    st.divider()
    st.markdown('### Bieżące aktywne pozycje na giełdzie')
    try:
        if key and secret:
            ex = exchange_client(ex_id, key, secret, password, cfg['market_type'])
            positions = ex.fetch_positions()
            active_pos = [p for p in positions or [] if abs(float(p.get('contracts') or 0)) > 0]
            if active_pos:
                st.dataframe(pd.DataFrame([{
                    'Symbol': p.get('symbol'),
                    'Strona': p.get('side'),
                    'Kontrakty': p.get('contracts'),
                    'Wejście': p.get('entryPrice'),
                    'PnL (USDT)': p.get('unrealizedPnl')
                } for p in active_pos]), use_container_width=True, hide_index=True)
            else:
                st.info('Brak otwartych pozycji na giełdzie w tej chwili.')
        else:
            st.info('Skonfiguruj dane API, aby podglądać aktywne pozycje na żywo.')
    except Exception as e:
        st.warning(f'Nie udało się pobrać pozycji z giełdy: {e}')

    st.divider()
    st.markdown('### Awaryjne zamknięcie wszystkich pozycji (Kill Switch)')
    if st.button('ZAMKNIJ WSZYSTKIE POZYCJE RYNKOWO', type='secondary'):
        try:
            if not key or not secret: raise RuntimeError('Brak kluczy API')
            ex = exchange_client(ex_id, key, secret, password, cfg['market_type'])
            positions = ex.fetch_positions()
            outcomes = []
            for p in positions or []:
                qty = abs(float(p.get('contracts') or 0))
                symbol = p.get('symbol')
                if qty <= 0 or not symbol: continue
                sideinfo = str(p.get('side') or '').lower()
                close_side = 'sell' if sideinfo in ('long', 'buy') else 'buy'
                try:
                    o = market_order(ex, symbol, close_side, qty, True)
                    outcomes.append(f'{symbol}: zamknięto {qty} ({o.get("id")})')
                except Exception as err: outcomes.append(f'{symbol}: BŁĄD {err}')
            for line in outcomes: event('KILL', line)
            st.write('\n'.join(outcomes) if outcomes else 'Giełda nie zgłasza otwartych pozycji.')
        except Exception as e: st.error(f'Kill switch nie powiódł się: {e}')


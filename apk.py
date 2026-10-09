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
LOG_PATH = APP_DIR / 'trading.log'

logging.basicConfig(filename=LOG_PATH, level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')

DEFAULTS = {
    'exchange': 'bitget', 'market_type': 'swap', 'symbol': 'BTC/USDT:USDT', 'timeframe': '15m', 'candle_limit': 180,
    'refresh_seconds': 30, 'ema_fast': 9, 'ema_slow': 21, 'adx_threshold': 25.0, 'rsi_min': 25.0, 'rsi_max': 75.0,
    'risk_usdt': 10.0, 'max_positions': 3, 'leverage': 2, 'sl_roe': 20.0, 'tp_roe': 40.0, 'enable_roe': True,
    'mtf_enabled': True, 'timeframes': ['5m', '15m', '1h'], 'auto_refresh': False, 'auto_trade': False, 'paper_mode': True,
    'max_notional_usdt': 50.0, 'cooldown_seconds': 300, 'allow_short': True, 'allow_long': True, 'scan_limit_count': 15
}

TF_OPTIONS = ['1m', '3m', '5m', '15m', '30m', '1h', '2h', '4h', '1d']

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
}
.metric-label { font-size: 12px; color: #90b8e6; text-transform: uppercase; letter-spacing: 1px; }
.metric-value { font-size: 25px; font-weight: 800; color: #f1f7ff; margin-top: 5px; }
.muted { color: #83a7d0; font-size: 12px; }
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
    c.execute('CREATE TABLE IF NOT EXISTS users (username TEXT PRIMARY KEY, password TEXT, subscription TEXT)')
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

def signal_for(cfg, tf):
    raw = get_candles(cfg['exchange'], cfg['market_type'], cfg['symbol'], tf, cfg['candle_limit'])
    d = indicators(raw.iloc[:-1].copy(), cfg['ema_fast'], cfg['ema_slow'])
    if len(d) < max(cfg['ema_slow'] + 5, 35): return {'tf': tf, 'signal': 'WAIT', 'reason': 'Za mało zamkniętych świec'}
    r = d.iloc[-1]
    trend_up = r.ema_fast > r.ema_slow
    trend_down = r.ema_fast < r.ema_slow
    long_ok = trend_up and r.adx >= cfg['adx_threshold'] and cfg['rsi_min'] <= r.rsi <= cfg['rsi_max'] and r.close > r.ema_fast
    short_ok = trend_down and r.adx >= cfg['adx_threshold'] and cfg['rsi_min'] <= r.rsi <= cfg['rsi_max'] and r.close < r.ema_fast
    sig = 'LONG' if long_ok else ('SHORT' if short_ok else 'WAIT')
    return {'tf': tf, 'signal': sig, 'price': float(r.close), 'ema_fast': float(r.ema_fast), 'ema_slow': float(r.ema_slow), 'adx': float(r.adx), 'rsi': float(r.rsi), 'timestamp': int(r.timestamp), 'reason': 'EMA + ADX + RSI na zamkniętej świecy'}

def signal_for_symbol(cfg, symbol, tf):
    try:
        raw = get_candles(cfg['exchange'], cfg['market_type'], symbol, tf, cfg['candle_limit'])
        d = indicators(raw.iloc[:-1].copy(), cfg['ema_fast'], cfg['ema_slow'])
        if len(d) < max(cfg['ema_slow'] + 5, 35): return {'symbol': symbol, 'tf': tf, 'signal': 'WAIT', 'reason': 'Za mało świec'}
        r = d.iloc[-1]
        trend_up = r.ema_fast > r.ema_slow
        trend_down = r.ema_fast < r.ema_slow
        long_ok = cfg['allow_long'] and trend_up and r.adx >= cfg['adx_threshold'] and cfg['rsi_min'] <= r.rsi <= cfg['rsi_max'] and r.close > r.ema_fast
        short_ok = cfg['allow_short'] and trend_down and r.adx >= cfg['adx_threshold'] and cfg['rsi_min'] <= r.rsi <= cfg['rsi_max'] and r.close < r.ema_fast
        sig = 'LONG' if long_ok else ('SHORT' if short_ok else 'WAIT')
        return {'symbol': symbol, 'tf': tf, 'signal': sig, 'price': float(r.close), 'adx': float(r.adx), 'rsi': float(r.rsi), 'reason': 'OK'}
    except Exception as e:
        return {'symbol': symbol, 'tf': tf, 'signal': 'ERROR', 'reason': str(e)[:100]}

def read_position(ex, symbol):
    try:
        positions = ex.fetch_positions([symbol])
    except Exception:
        positions = ex.fetch_positions()
    for p in positions or []:
        if p.get('symbol') == symbol and abs(float(p.get('contracts') or p.get('contractSize') or 0)) > 0:
            return p
    return None

def position_qty(p):
    try: return abs(float(p.get('contracts') or 0))
    except Exception: return 0.0

def market_order(ex, symbol, side, qty, reduce_only=False):
    qty = float(ex.amount_to_precision(symbol, qty))
    if qty <= 0: raise ValueError('Ilość po zaokrągleniu jest zerowa')
    params = {'reduceOnly': True} if reduce_only else {}
    return ex.create_order(symbol, 'market', side, qty, None, params)

def calc_qty(ex, symbol, free_usdt, price, cfg, sl_distance):
    risk = max(0.0, float(cfg['risk_usdt']))
    distance = max(float(sl_distance), 0.001)
    notional = min(risk / distance, float(cfg['max_notional_usdt']), max(0.0, free_usdt) * float(cfg['leverage']) * 0.90)
    market = ex.market(symbol)
    contract = float(market.get('contractSize') or 1)
    qty = notional / max(price * contract, 1e-12)
    qty = float(ex.amount_to_precision(symbol, qty))
    return qty, notional

def balance_usdt(ex):
    b = ex.fetch_balance()
    row = b.get('USDT') or {}
    return float(row.get('free') or 0), float(row.get('total') or 0)

# --- PANEL LOGOWANIA I REJESTRACJI ---
if 'authenticated' not in st.session_state:
    st.session_state['authenticated'] = False
    st.session_state['username'] = ''

if not st.session_state['authenticated']:
    st.markdown('<div class="brand-retro">Bitget-SaaS</div><div class="subbrand-retro">AUTONOMICZNY SYSTEM TRANSAKCYJNY</div>', unsafe_allow_html=True)
    
    tab_login, tab_reg = st.tabs(["Zaloguj się", "Załóż konto i subskrypcję"])
    
    with tab_login:
        st.subheader("Logowanie do systemu")
        with st.form("login_form"):
            l_user = st.text_input("Nazwa użytkownika")
            l_pass = st.text_input("Hasło", type="password")
            submit_login = st.form_submit_button("ZALOGUJ SIĘ", use_container_width=True)
            if submit_login:
                with db() as c:
                    row = c.execute("SELECT password FROM users WHERE username=?", (l_user,)).fetchone()
                if row and row[0] == l_pass:
                    st.session_state['authenticated'] = True
                    st.session_state['username'] = l_user
                    st.success("Zalogowano pomyślnie!")
                    st.rerun()
                else:
                    st.error("Nieprawidłowy login lub hasło.")

    with tab_reg:
        st.subheader("Rejestracja użytkownika i subskrypcja")
        with st.form("reg_form"):
            r_user = st.text_input("Nazwa użytkownika")
            r_pass = st.text_input("Hasło", type="password")
            r_sub = st.selectbox("Wybierz subskrypcję", ["Starter (Darmowy)", "Pro Trader (Miesięczny)", "VIP SaaS (Roczny)"])
            submit_reg = st.form_submit_button("ZAREJESTRUJ SIĘ", use_container_width=True)
            if submit_reg:
                if not r_user.strip() or not r_pass.strip():
                    st.error("Uzupełnij login i hasło.")
                else:
                    try:
                        with db() as c:
                            c.execute("INSERT INTO users(username, password, subscription) VALUES(?,?,?)", (r_user.strip(), r_pass.strip(), r_sub))
                            c.commit()
                        st.success("Konto utworzone pomyślnie! Możesz się teraz zalogować.")
                    except sqlite3.IntegrityError:
                        st.error("Taki użytkownik już istnieje.")
    st.stop()

# --- GŁÓWNA APLIKACJA PO ZALOGOWANIU ---
cfg = load_cfg()
creds = load_creds()
ex_id, key, secret, password = creds

with st.sidebar:
    st.markdown(f'<div class="brand"><span>⚡</span> Bitget-SaaS</div><div class="subbrand">Witaj, {st.session_state["username"]}</div>', unsafe_allow_html=True)
    page = st.radio('NAWIGACJA', ['Trading', 'Skaner Regulowany i Auto-Handel', 'Skaner MTF', 'Ustawienia', 'Połączenie API', 'Dziennik'])
    st.divider()
    if st.button('Wyloguj', use_container_width=True):
        st.session_state['authenticated'] = False
        st.session_state['username'] = ''
        st.rerun()
    if st.button('Wyczyść cache danych', use_container_width=True):
        get_candles.clear()
        st.success('Cache danych wyczyszczony.')

st.markdown('<div class="brand"><span>Bitget</span>-SaaS Futures</div><div class="subbrand">AUTONOMICZNY SYSTEM TRANSAKCYJNY</div>', unsafe_allow_html=True)

if page == 'Ustawienia':
    st.subheader('Strategia, MTF i zarządzanie ryzykiem')
    with st.form('cfgform'):
        a, b, c = st.columns(3)
        with a:
            cfg['exchange'] = st.selectbox('Giełda', ['bitget', 'binanceusdm', 'bybit', 'okx'], index=['bitget', 'binanceusdm', 'bybit', 'okx'].index(cfg['exchange']) if cfg['exchange'] in ['bitget', 'binanceusdm', 'bybit', 'okx'] else 0)
            cfg['market_type'] = st.selectbox('Rynek', ['swap', 'future'], index=0 if cfg['market_type'] == 'swap' else 1)
            cfg['symbol'] = st.text_input('Symbol CCXT', cfg['symbol'])
            cfg['timeframe'] = st.selectbox('Główny interwał', TF_OPTIONS, index=TF_OPTIONS.index(cfg['timeframe']) if cfg['timeframe'] in TF_OPTIONS else 3)
            cfg['timeframes'] = st.multiselect('Interwały MTF do potwierdzenia', TF_OPTIONS, default=[x for x in cfg['timeframes'] if x in TF_OPTIONS] or ['5m', '15m', '1h'])
            cfg['mtf_enabled'] = st.checkbox('Wymagaj zgodności MTF', cfg['mtf_enabled'])
        with b:
            cfg['ema_fast'] = st.number_input('EMA szybka', 2, 100, int(cfg['ema_fast']))
            cfg['ema_slow'] = st.number_input('EMA wolna', 3, 300, int(cfg['ema_slow']))
            cfg['adx_threshold'] = st.number_input('Minimalny ADX', 0.0, 100.0, float(cfg['adx_threshold']))
            cfg['rsi_min'] = st.number_input('RSI minimum', 0.0, 100.0, float(cfg['rsi_min']))
            cfg['rsi_max'] = st.number_input('RSI maksimum', 0.0, 100.0, float(cfg['rsi_max']))
            cfg['candle_limit'] = st.select_slider('Świece na interwał', options=[80, 100, 150, 180, 240], value=cfg['candle_limit'] if cfg['candle_limit'] in [80, 100, 150, 180, 240] else 180)
        with c:
            cfg['risk_usdt'] = st.number_input('Maks. ryzyko na pozycję (USDT)', 1.0, 10000.0, float(cfg['risk_usdt']))
            cfg['max_notional_usdt'] = st.number_input('Limit wartości pozycji (USDT)', 5.0, 100000.0, float(cfg['max_notional_usdt']))
            cfg['max_positions'] = st.number_input('Maks. otwarte pozycje', 1, 20, int(cfg['max_positions']))
            cfg['leverage'] = st.number_input('Dźwignia', 1, 50, int(cfg['leverage']))
            cfg['sl_roe'] = st.number_input('Stop-loss ROE (%)', 1.0, 95.0, float(cfg['sl_roe']))
            cfg['tp_roe'] = st.number_input('Take-profit ROE (%)', 1.0, 500.0, float(cfg['tp_roe']))
            cfg['enable_roe'] = st.checkbox('Monitoruj SL/TP ROE', cfg['enable_roe'])
            cfg['allow_long'] = st.checkbox('Pozwól na LONG', cfg['allow_long'])
            cfg['allow_short'] = st.checkbox('Pozwól na SHORT', cfg['allow_short'])
            cfg['refresh_seconds'] = st.number_input('Odstęp cyklu (sek.)', 10, 300, int(cfg['refresh_seconds']))
            cfg['cooldown_seconds'] = st.number_input('Przerwa po zleceniu (sek.)', 0, 86400, int(cfg['cooldown_seconds']))
        submitted = st.form_submit_button('ZAPISZ USTAWIENIA', use_container_width=True)
    if submitted:
        save_cfg(cfg)
        get_candles.clear()
        st.success('Zapisano trwale w SQLite.')
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

elif page == 'Skaner MTF':
    st.subheader('Skaner strategii EMA / ADX / RSI (Wielointerwałowy)')
    tfs = cfg['timeframes'] if cfg['mtf_enabled'] else [cfg['timeframe']]
    if st.button('Skanuj teraz', type='primary'):
        rows = []
        for tf in dict.fromkeys(tfs):
            try: rows.append(signal_for(cfg, tf))
            except Exception as e: rows.append({'tf': tf, 'signal': 'ERROR', 'reason': str(e)[:250]})
        st.session_state['scan_results'] = rows
    rows = st.session_state.get('scan_results', [])
    if rows: st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)
    else: st.info('Kliknij „Skanuj teraz”, aby pobrać zamknięte świece i policzyć wskaźniki.')

elif page == 'Skaner Regulowany i Auto-Handel':
    st.subheader('Skaner kontraktów regulowany suwakiem i Auto-Trade')
    st.write('Sam decydujesz, ile par giełdowych ma być pobranych i przeskanowanych w jednym cyklu przez bot.')
    
    with st.form('scanner_config_form'):
        cfg['scan_limit_count'] = st.slider('Liczba par do przeskanowania z giełdy', 5, 50, int(cfg.get('scan_limit_count', 15)))
        cfg['auto_trade'] = st.checkbox('Włącz automatyczne składanie zleceń', value=bool(cfg['auto_trade']))
        cfg['paper_mode'] = st.checkbox('Tryb symulacji PAPER', value=bool(cfg['paper_mode']))
        submit_scan_cfg = st.form_submit_button('ZAPISZ USTAWIENIA SKANERA', use_container_width=True)
        if submit_scan_cfg:
            save_cfg(cfg)
            st.success('Zapisano ustawienia skanera.')

    if st.button('URUCHOM SKANOWANIE I AUTOMATYCZNY HANDEL', type='primary'):
        try:
            ex = exchange_client(ex_id, key, secret, password, cfg['market_type'])
            markets = ex.load_markets()
            
            all_symbols = [s for s, m in markets.items() if m.get('quote') == 'USDT' and m.get('active') and m.get('linear')]
            target_symbols = all_symbols[:int(cfg['scan_limit_count'])]
            
            st.info(f'Pobrano {len(target_symbols)} par z giełdy do skanowania.')
            
            results = []
            free, _ = balance_usdt(ex) if not cfg['paper_mode'] else (1000.0, 1000.0)
            
            for symbol in target_symbols:
                res = signal_for_symbol(cfg, symbol, cfg['timeframe'])
                results.append(res)
                
                sig = res['signal']
                if sig in ('LONG', 'SHORT'):
                    event('INFO', f'Skaner: Wykryto {sig} na {symbol} (ADX: {res["adx"]:.1f}, RSI: {res["rsi"]:.1f})')
                    
                    if cfg['auto_trade']:
                        if cfg['paper_mode']:
                            event('TRADE', f'[PAPER] Symulowane otwarcie {sig} na {symbol}')
                        else:
                            lev = int(cfg['leverage'])
                            stop_fraction = (float(cfg['sl_roe']) / 100.0) / lev
                            qty, notional = calc_qty(ex, symbol, free, res['price'], cfg, stop_fraction)
                            try:
                                ex.set_leverage(lev, symbol)
                            except Exception:
                                pass
                            side = 'buy' if sig == 'LONG' else 'sell'
                            order = market_order(ex, symbol, side, qty, False)
                            event('TRADE', f'AUTOMATYCZNIE OTWARTO {sig} {symbol} qty={qty} id={order.get("id")}')
            
            st.success('Skanowanie zakończone!')
            st.dataframe(pd.DataFrame(results), use_container_width=True, hide_index=True)
            
        except Exception as e:
            st.error(f'Błąd podczas skanowania: {e}')

elif page == 'Dziennik':
    st.subheader('Zdarzenia i zlecenia')
    with db() as con: rows = con.execute('SELECT ts,level,message FROM events ORDER BY id DESC LIMIT 200').fetchall()
    if rows: st.dataframe(pd.DataFrame(rows, columns=['UTC', 'Poziom', 'Wiadomość']), use_container_width=True, hide_index=True)
    else: st.info('Brak zdarzeń.')

else:
    st.subheader('Panel tradingowy')
    a, b, c, d = st.columns(4)
    for col, title, value, sub in [(a, 'GIEŁDA', cfg['exchange'].upper(), cfg['market_type']), (b, 'PARA', cfg['symbol'], cfg['timeframe']), (c, 'STRATEGIA', f"EMA {cfg['ema_fast']}/{cfg['ema_slow']}", f"ADX ≥ {cfg['adx_threshold']:g}"), (d, 'RYZYKO / POZYCJĘ', f"{cfg['risk_usdt']:g} USDT", f"limit {cfg['max_positions']} pozycji")]:
        col.markdown(f'<div class="panel"><div class="metric-label">{title}</div><div class="metric-value">{value}</div><div class="muted">{sub}</div></div>', unsafe_allow_html=True)
    st.write('')
    left, right = st.columns([1.6, 1])
    with left:
        st.markdown('### Wykres i wskaźniki')
        try:
            raw = get_candles(cfg['exchange'], cfg['market_type'], cfg['symbol'], cfg['timeframe'], cfg['candle_limit'])
            d = indicators(raw, cfg['ema_fast'], cfg['ema_slow'])
            st.line_chart(d.assign(EMA_szybka=d.ema_fast, EMA_wolna=d.ema_slow).set_index(pd.to_datetime(d.timestamp, unit='ms', utc=True))[['close', 'EMA_szybka', 'EMA_wolna']], height=330)
            r = d.iloc[-2] if len(d) > 2 else d.iloc[-1]
            st.caption(f"Zamknięta świeca: {datetime.fromtimestamp(float(r.timestamp)/1000, timezone.utc).isoformat()} · ADX {r.adx:.1f} · RSI {r.rsi:.1f}")
        except Exception as e:
            st.error(f'Nie można pobrać danych publicznych: {e}')
    with right:
        st.markdown('### Silnik zleceń')
        st.write('Tryb paper:', 'WŁĄCZONY' if cfg['paper_mode'] else 'WYŁĄCZONY')
        st.write('Automatyczny handel:', 'WŁĄCZONY' if cfg['auto_trade'] else 'WYŁĄCZONY')
        try:
            sig = signal_for(cfg, cfg['timeframe'])
            st.metric('Sygnał główny', sig['signal'])
            st.caption(sig.get('reason', ''))
        except Exception as e:
            st.caption(f'Sygnał niedostępny: {e}')
    st.divider()
    st.markdown('### Sterowanie botem')
    with st.form('bot_controls'):
        paper = st.checkbox('PAPER / symulacja — nie wysyłaj zleceń', value=bool(cfg['paper_mode']))
        auto = st.checkbox('Włącz wykonywanie sygnałów automatycznie', value=bool(cfg['auto_trade']))
        confirm = st.checkbox('Rozumiem ryzyko i potwierdzam, że testowałem konto oraz tryb pozycji giełdy')
        submitted = st.form_submit_button('ZAPISZ TRYB PRACY')
    if submitted:
        if auto and not paper and not confirm: st.error('Aby włączyć live, zaznacz potwierdzenie ryzyka.')
        else:
            cfg['paper_mode'] = paper
            cfg['auto_trade'] = auto
            save_cfg(cfg)
            st.success('Zapisano tryb pracy.')
            st.rerun()
    if st.button('Wykonaj jeden cykl bota', type='primary'):
        try:
            sigs = []
            tfs = cfg['timeframes'] if cfg['mtf_enabled'] else [cfg['timeframe']]
            for tf in dict.fromkeys(tfs): sigs.append(signal_for(cfg, tf))
            active = [x['signal'] for x in sigs if x['signal'] in ('LONG', 'SHORT')]
            direction = active[0] if active and all(x == active[0] for x in active) and len(active) == len(sigs) else 'WAIT'
            st.dataframe(pd.DataFrame(sigs), use_container_width=True, hide_index=True)
            event('INFO', f'MTF signal={direction}; details={sigs}')
            if direction == 'WAIT': st.info('Brak zgodnego sygnału MTF — bez transakcji.')
            elif not cfg['auto_trade']: st.info(f'Sygnał {direction}, ale wykonywanie jest wyłączone.')
            elif cfg['paper_mode']:
                st.success(f'[PAPER] Symulowany sygnał {direction}; żadne zlecenie nie zostało wysłane.')
            else:
                if not key or not secret: raise RuntimeError('Brak zapisanych kluczy API')
                ex = exchange_client(ex_id, key, secret, password, cfg['market_type'])
                ex.load_markets()
                pos = read_position(ex, cfg['symbol'])
                if pos and position_qty(pos) > 0: st.warning('Istnieje już pozycja dla tego symbolu.')
                else:
                    positions = ex.fetch_positions()
                    open_count = sum(1 for p in positions or [] if abs(float(p.get('contracts') or 0)) > 0)
                    if open_count >= int(cfg['max_positions']): raise RuntimeError(f'Limit pozycji osiągnięty')
                    free, _ = balance_usdt(ex)
                    price = float(sigs[0]['price'])
                    lev = int(cfg['leverage'])
                    stop_fraction = (float(cfg['sl_roe']) / 100.0) / lev
                    qty, notional = calc_qty(ex, cfg['symbol'], free, price, cfg, stop_fraction)
                    try: ex.set_leverage(lev, cfg['symbol'])
                    except Exception as le: event('WARNING', f'Nie udało się ustawić dźwigni: {le}')
                    side = 'buy' if direction == 'LONG' else 'sell'
                    order = market_order(ex, cfg['symbol'], side, qty, False)
                    event('TRADE', f'OPEN {direction} {cfg["symbol"]} qty={qty} order={order.get("id")}')
                    st.success(f'Wysłano zlecenie rynkowe {direction}: ilość {qty}. ID: {order.get("id")}')
        except Exception as e:
            event('ERROR', f'Bot cycle failed: {e}')
            st.error(f'Cykl nie powiódł się: {e}')
    st.divider()
    st.markdown('### Kill switch')
    if st.button('ZAMKNIJ WSZYSTKIE POZYCJE', type='secondary'):
        try:
            if not key or not secret: raise RuntimeError('Brak kluczy API')
            ex = exchange_client(ex_id, key, secret, password, cfg['market_type'])
            positions = ex.fetch_positions()
            outcomes = []
            for p in positions or []:
                qty = position_qty(p)
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

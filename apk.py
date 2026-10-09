import os, json, sqlite3, time, math, logging
from pathlib import Path
from datetime import datetime, timezone, timedelta
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
 'risk_usdt': 10.0, 'max_positions': 2, 'leverage': 2, 'sl_roe': 20.0, 'tp_roe': 40.0, 'enable_roe': True,
 'mtf_enabled': True, 'timeframes': ['5m', '15m', '1h'], 'auto_refresh': True, 'auto_trade': False, 'paper_mode': True,
 'max_notional_usdt': 50.0, 'cooldown_seconds': 300, 'allow_short': True, 'allow_long': True,
 'app_password': 'admin'
}
TF_OPTIONS = ['1m', '3m', '5m', '15m', '30m', '1h', '2h', '4h', '1d']
CSS = '''<style>:root{color-scheme:dark}.stApp{background:radial-gradient(ellipse at 40% -20%,#103e78 0%,#071a36 42%,#050e20 100%);color:#eaf3ff}[data-testid="stHeader"]{background:rgba(3,12,29,.85)}[data-testid="stSidebar"]{background:linear-gradient(180deg,#06152d,#081f42);border-right:1px solid #164a84}.block-container{padding-top:1.2rem;max-width:1600px}.brand{font-weight:900;letter-spacing:-1px;font-size:29px;color:#eaf5ff}.brand span{color:#28a8ff}.subbrand{color:#7da9d8;font-size:11px;letter-spacing:2px;text-transform:uppercase}.panel{background:linear-gradient(145deg,rgba(12,43,83,.95),rgba(5,24,51,.96));border:1px solid #164a80;border-radius:14px;padding:16px 18px}.metric-label{font-size:12px;color:#90b8e6;text-transform:uppercase;letter-spacing:1px}.metric-value{font-size:25px;font-weight:800;color:#f1f7ff;margin-top:5px}.muted{color:#83a7d0;font-size:12px}div.stButton>button{border:1px solid #278be8;border-radius:8px;background:linear-gradient(180deg,#1689ff,#0759c8);color:white;font-weight:700}hr{border-color:#16416f}</style>'''

st.set_page_config(page_title='Bitget-SaaS Auto-Futures & Subskrypcje', page_icon='📈', layout='wide')
st.markdown(CSS, unsafe_allow_html=True)

def db():
    c = sqlite3.connect(DB_PATH, timeout=15)
    c.execute('PRAGMA journal_mode=WAL')
    c.execute('PRAGMA busy_timeout=15000')
    c.execute('CREATE TABLE IF NOT EXISTS settings (k TEXT PRIMARY KEY, v TEXT NOT NULL)')
    c.execute('CREATE TABLE IF NOT EXISTS credentials (k TEXT PRIMARY KEY, exchange TEXT, api_key TEXT, secret TEXT, password TEXT)')
    c.execute('CREATE TABLE IF NOT EXISTS bot_state (symbol TEXT PRIMARY KEY, side TEXT, entry REAL, amount REAL, opened REAL, sl REAL, tp REAL, order_id TEXT)')
    c.execute('CREATE TABLE IF NOT EXISTS events (id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT, level TEXT, message TEXT)')
    c.execute('CREATE TABLE IF NOT EXISTS subscriptions (id INTEGER PRIMARY KEY AUTOINCREMENT, user TEXT, plan TEXT, status TEXT, expires_at TEXT, created_at TEXT)')
    c.commit()
    return c

def load_cfg():
    out = DEFAULTS.copy()
    with db() as c:
        r = c.execute('SELECT v FROM settings WHERE k="main"').fetchone()
    if r:
        try:
            out.update(json.loads(r[0]))
        except Exception:
            pass
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

def get_active_subscription():
    with db() as c:
        r = c.execute('SELECT plan, status, expires_at FROM subscriptions ORDER BY id DESC LIMIT 1').fetchone()
    if not r:
        return {'plan': 'Brak', 'status': 'inactive', 'expires_at': 'Brak'}
    return {'plan': r[0], 'status': r[1], 'expires_at': r[2]}

@st.cache_resource(show_spinner=False)
def exchange_client(ex_id, api_key, secret, password, market_type):
    if ccxt is None:
        raise RuntimeError('Brak ccxt. Uruchom: pip install -r requirements.txt')
    cls = getattr(ccxt, ex_id, None)
    if cls is None:
        raise ValueError('Nieobsługiwana giełda: ' + ex_id)
    opts = {'enableRateLimit': True, 'timeout': 20000, 'options': {'defaultType': market_type, 'defaultSubType': 'linear'}}
    if api_key and secret:
        opts.update(apiKey=api_key, secret=secret)
    if password:
        opts['password'] = password
    return cls(opts)

@st.cache_data(ttl=20, show_spinner=False)
def get_candles(ex_id, market_type, symbol, tf, limit):
    ex = exchange_client(ex_id, '', '', '', market_type)
    raw = ex.fetch_ohlcv(symbol, timeframe=tf, limit=int(limit))
    return pd.DataFrame(raw, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])

def indicators(df, fast, slow):
    d = df.copy()
    for col in ['open', 'high', 'low', 'close', 'volume']:
        d[col] = pd.to_numeric(d[col], errors='coerce')
    d = d.dropna(subset=['high', 'low', 'close']).reset_index(drop=True)
    d['ema_fast'] = d.close.ewm(span=int(fast), adjust=False).mean()
    d['ema_slow'] = d.close.ewm(span=int(slow), adjust=False).mean()
    delta = d.close.diff()
    gain = delta.clip(lower=0).ewm(alpha=1/14, adjust=False).mean()
    loss = (-delta.clip(upper=0)).ewm(alpha=1/14, adjust=False).mean()
    d['rsi'] = 100 - 100 / (1 + gain / loss.replace(0, np.nan))
    tr = pd.concat([(d.high - d.low).abs(), (d.high - d.close.shift()).abs(), (d.low - d.close.shift()).abs()], axis=1).max(axis=1)
    up = d.high.diff()
    down = -d.low.diff()
    plus = pd.Series(np.where((up > down) & (up > 0), up, 0), index=d.index)
    minus = pd.Series(np.where((down > up) & (down > 0), down, 0), index=d.index)
    atr = tr.ewm(alpha=1/14, adjust=False).mean().replace(0, np.nan)
    pdi = 100 * plus.ewm(alpha=1/14, adjust=False).mean() / atr
    mdi = 100 * minus.ewm(alpha=1/14, adjust=False).mean() / atr
    d['adx'] = (100 * (pdi - mdi).abs() / (pdi + mdi).replace(0, np.nan)).ewm(alpha=1/14, adjust=False).mean()
    return d

def signal_for(cfg, symbol, tf):
    raw = get_candles(cfg['exchange'], cfg['market_type'], symbol, tf, cfg['candle_limit'])
    d = indicators(raw.iloc[:-1].copy(), cfg['ema_fast'], cfg['ema_slow'])
    if len(d) < max(cfg['ema_slow'] + 5, 35):
        return {'symbol': symbol, 'tf': tf, 'signal': 'WAIT', 'price': 0.0, 'adx': 0.0, 'rsi': 0.0, 'reason': 'Za mało świec'}
    r = d.iloc[-1]
    trend_up = r.ema_fast > r.ema_slow
    trend_down = r.ema_fast < r.ema_slow
    
    long_allowed = cfg['allow_long']
    short_allowed = cfg['allow_short']

    long_ok = long_allowed and trend_up and r.adx >= cfg['adx_threshold'] and cfg['rsi_min'] <= r.rsi <= cfg['rsi_max'] and r.close > r.ema_fast
    short_ok = short_allowed and trend_down and r.adx >= cfg['adx_threshold'] and cfg['rsi_min'] <= r.rsi <= cfg['rsi_max'] and r.close < r.ema_fast
    
    sig = 'LONG' if long_ok else ('SHORT' if short_ok else 'WAIT')
    return {'symbol': symbol, 'tf': tf, 'signal': sig, 'price': float(r.close), 'adx': float(r.adx), 'rsi': float(r.rsi), 'reason': 'OK'}

def market_order(ex, symbol, side, qty, reduce_only=False):
    qty = float(ex.amount_to_precision(symbol, qty))
    if qty <= 0:
        raise ValueError('Ilość po zaokrągleniu jest zerowa')
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
    if qty <= 0:
        raise ValueError('Wyliczona ilość jest za mała dla minimalnego zlecenia giełdy')
    return qty, notional

def balance_usdt(ex):
    b = ex.fetch_balance()
    row = b.get('USDT') or {}
    return float(row.get('free') or 0), float(row.get('total') or 0)

cfg = load_cfg()
creds = load_creds()
ex_id, key, secret, password = creds

# --- SYSTEM LOGOWANIA ---
if 'authenticated' not in st.session_state:
    st.session_state['authenticated'] = False

if not st.session_state['authenticated']:
    st.markdown('<div class="brand" style="text-align:center; margin-top: 5rem;"><span>⚡</span> Bitget-SaaS</div><div class="subbrand" style="text-align:center;">PANEL LOGOWANIA DO SYSTEMU</div>', unsafe_allow_html=True)
    st.write('')
    col1, col2, col3 = st.columns([1, 1.2, 1])
    with col2:
        with st.form('login_form'):
            entered_password = st.text_input('Hasło dostępu do panelu', type='password')
            submit_login = st.form_submit_button('Zaloguj się', use_container_width=True)
            if submit_login:
                target_pass = cfg.get('app_password', 'admin')
                if entered_password == target_pass:
                    st.session_state['authenticated'] = True
                    st.success('Zalogowano pomyślnie!')
                    st.rerun()
                else:
                    st.error('Błędne hasło! (Domyślne: admin)')
    st.stop()

# --- GŁÓWNA NAWIGACJA Z PŁATNOŚCIAMI ---
with st.sidebar:
    st.markdown('<div class="brand"><span>⚡</span> Bitget-SaaS</div><div class="subbrand">Auto-Pilot · Subskrypcje</div>', unsafe_allow_html=True)
    
    sub_info = get_active_subscription()
    st.info(f"**Pakiet:** {sub_info['plan']}\n\n**Status:** {sub_info['status'].upper()}")
    
    page = st.radio('NAWIGACJA', ['Trading & Auto-Pilot', 'Skaner Top 20', 'Panel Płatności', 'Ustawienia', 'Połączenie API', 'Dziennik'])
    st.divider()
    if st.button('🔒 Wyloguj się', use_container_width=True):
        st.session_state['authenticated'] = False
        st.rerun()

st.markdown('<div class="brand"><span>Bitget</span>-SaaS Futures</div><div class="subbrand">AUTONOMICZNY HANDEL I ZARZĄDZANIE SUBSKRYPCJĄ</div>', unsafe_allow_html=True)

if page == 'Panel Płatności':
    st.subheader('Subskrypcje i Płatności SaaS')
    st.write('Wybierz plan abonamentowy, aby odblokować pełny, ciągły dostęp do Auto-Pilota i automatycznego skanowania giełdy.')

    col1, col2, col3 = st.columns(3)
    
    with col1:
        st.markdown('<div class="panel"><h3>Starter</h3><p class="muted">Do testów i podstawowego handlu</p><h2>19 USD <span style="font-size:12px">/ mies.</span></h2><hr><ul><li>Maks. 2 pozycje</li><li>Skaner Top 10</li><li>Tryb Paper Trading</li></ul></div>', unsafe_allow_html=True)
        if st.button('Wybierz Starter', use_container_width=True):
            exp = (datetime.now(timezone.utc) + timedelta(days=30)).isoformat()
            with db() as c:
                c.execute('INSERT INTO subscriptions(user, plan, status, expires_at, created_at) VALUES(?,?,?,?,?)', ('admin', 'Starter', 'active', exp, datetime.now(timezone.utc).isoformat()))
            st.success('Aktywowano pakiet Starter!')
            st.rerun()

    with col2:
        st.markdown('<div class="panel"><h3>Pro Trader</h3><p class="muted">Dla profesjonalistów (Auto-Pilot)</p><h2>49 USD <span style="font-size:12px">/ mies.</span></h2><hr><ul><li>Maks. 10 pozycji</li><li>Skaner Top 20 Wolumenu</li><li>Pełny Auto-Pilot Live</li></ul></div>', unsafe_allow_html=True)
        if st.button('Wybierz Pro Trader', use_container_width=True):
            exp = (datetime.now(timezone.utc) + timedelta(days=30)).isoformat()
            with db() as c:
                c.execute('INSERT INTO subscriptions(user, plan, status, expires_at, created_at) VALUES(?,?,?,?,?)', ('admin', 'Pro Trader', 'active', exp, datetime.now(timezone.utc).isoformat()))
            st.success('Aktywowano pakiet Pro Trader!')
            st.rerun()

    with col3:
        st.markdown('<div class="panel"><h3>VIP Lifetime</h3><p class="muted">Brak limitów czasowych</p><h2>299 USD <span style="font-size:12px">/ jednorazowo</span></h2><hr><ul><li>Wszystkie funkcje VIP</li><li>Nieograniczone pozycje</li><li>Priorytetowe wsparcie</li></ul></div>', unsafe_allow_html=True)
        if st.button('Wybierz VIP Lifetime', use_container_width=True):
            exp = (datetime.now(timezone.utc) + timedelta(days=3650)).isoformat()
            with db() as c:
                c.execute('INSERT INTO subscriptions(user, plan, status, expires_at, created_at) VALUES(?,?,?,?,?)', ('admin', 'VIP Lifetime', 'active', exp, datetime.now(timezone.utc).isoformat()))
            st.success('Aktywowano pakiet VIP Lifetime!')
            st.rerun()

    st.divider()
    st.markdown('### Historia i status subskrypcji w bazie')
    with db() as con:
        sub_rows = con.execute('SELECT plan, status, expires_at, created_at FROM subscriptions ORDER BY id DESC').fetchall()
    if sub_rows:
        st.dataframe(pd.DataFrame(sub_rows, columns=['Plan', 'Status', 'Wygasa', 'Utworzono']), use_container_width=True, hide_index=True)
    else:
        st.info('Brak zarejestrowanych płatności w bazie.')

elif page == 'Ustawienia':
    st.subheader('Strategia i zarządzanie ryzykiem')
    with st.form('cfgform'):
        a, b, c = st.columns(3)
        with a:
            cfg['exchange'] = st.selectbox('Giełda', ['bitget', 'binanceusdm', 'bybit', 'okx'], index=['bitget', 'binanceusdm', 'bybit', 'okx'].index(cfg['exchange']) if cfg['exchange'] in ['bitget', 'binanceusdm', 'bybit', 'okx'] else 0)
            cfg['market_type'] = st.selectbox('Rynek', ['swap', 'future'], index=0 if cfg['market_type'] == 'swap' else 1)
            cfg['timeframe'] = st.selectbox('Interwał analizy', TF_OPTIONS, index=TF_OPTIONS.index(cfg['timeframe']) if cfg['timeframe'] in TF_OPTIONS else 3)
            cfg['app_password'] = st.text_input('Zmień hasło logowania', value=cfg.get('app_password', 'admin'), type='password')
        with b:
            cfg['ema_fast'] = st.number_input('EMA szybka', 2, 100, int(cfg['ema_fast']))
            cfg['ema_slow'] = st.number_input('EMA wolna', 3, 300, int(cfg['ema_slow']))
            cfg['adx_threshold'] = st.number_input('Minimalny ADX', 0.0, 100.0, float(cfg['adx_threshold']))
            cfg['rsi_min'] = st.number_input('RSI minimum', 0.0, 100.0, float(cfg['rsi_min']))
            cfg['rsi_max'] = st.number_input('RSI maksimum', 0.0, 100.0, float(cfg['rsi_max']))
        with c:
            cfg['risk_usdt'] = st.number_input('Maks. ryzyko na pozycję (USDT)', 1.0, 10000.0, float(cfg['risk_usdt']))
            cfg['max_notional_usdt'] = st.number_input('Limit wartości pozycji (USDT)', 5.0, 100000.0, float(cfg['max_notional_usdt']))
            cfg['max_positions'] = st.number_input('Maks. otwarte pozycje łącznie', 1, 20, int(cfg['max_positions']))
            cfg['leverage'] = st.number_input('Dźwignia', 1, 50, int(cfg['leverage']))
            cfg['allow_long'] = st.checkbox('Pozwól na LONG', cfg['allow_long'])
            cfg['allow_short'] = st.checkbox('Pozwól na SHORT', cfg['allow_short'])
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
        pw = st.text_input('Passphrase', value=password, type='password')
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

elif page == 'Skaner Top 20':
    st.subheader('Skaner Top 20 par według wolumenu 24h')
    if st.button('Skanuj Top 20 Wolumenu', type='primary'):
        with st.spinner('Pobieranie rynków i świec...'):
            try:
                ex = exchange_client(cfg['exchange'], key, secret, password, cfg['market_type'])
                ex.load_markets()
                tickers = ex.fetch_tickers()
                valid_tickers = []
                for sym, t in tickers.items():
                    if 'USDT' in sym and (sym.endswith(':USDT') or cfg['market_type'] == 'swap'):
                        vol = float(t.get('quoteVolume') or t.get('baseVolume') or 0)
                        valid_tickers.append((sym, vol))
                valid_tickers.sort(key=lambda x: x[1], reverse=True)
                top20 = [x[0] for x in valid_tickers[:20]]
                
                results = []
                for sym in top20:
                    try:
                        res = signal_for(cfg, sym, cfg['timeframe'])
                        vol_val = tickers.get(sym, {}).get('quoteVolume', 0)
                        results.append({
                            'Symbol': sym,
                            'Wolumen 24h (USDT)': f"{float(vol_val):,.0f}" if vol_val else '0',
                            'Sygnał': res['signal'],
                            'Cena': res['price'],
                            'ADX': round(res['adx'], 1),
                            'RSI': round(res['rsi'], 1)
                        })
                    except Exception:
                        pass
                st.session_state['top20_results'] = results
                st.success('Skanowanie zakończone!')
            except Exception as e:
                st.error(f'Błąd: {e}')

    rows = st.session_state.get('top20_results', [])
    if rows:
        st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)

elif page == 'Dziennik':
    st.subheader('Dziennik zdarzeń i transakcji')
    with db() as con:
        rows = con.execute('SELECT ts,level,message FROM events ORDER BY id DESC LIMIT 200').fetchall()
    if rows:
        st.dataframe(pd.DataFrame(rows, columns=['UTC', 'Poziom', 'Wiadomość']), use_container_width=True, hide_index=True)
    else:
        st.info('Brak zdarzeń.')

else:
    st.subheader('Panel Trading & Auto-Pilot')
    
    a, b, c, d = st.columns(4)
    a.markdown(f'<div class="panel"><div class="metric-label">TRYB</div><div class="metric-value">{"PAPER" if cfg["paper_mode"] else "LIVE"}</div></div>', unsafe_allow_html=True)
    b.markdown(f'<div class="panel"><div class="metric-label">AUTO-PILOT</div><div class="metric-value">{"WŁĄCZONY" if cfg["auto_trade"] else "WYŁĄCZONY"}</div></div>', unsafe_allow_html=True)
    c.markdown(f'<div class="panel"><div class="metric-label">MAKS. POZYCJE</div><div class="metric-value">{cfg["max_positions"]}</div></div>', unsafe_allow_html=True)
    d.markdown(f'<div class="panel"><div class="metric-label">SUBSKRYPCJA</div><div class="metric-value">{sub_info["plan"]}</div></div>', unsafe_allow_html=True)
    
    st.write('')
    with st.form('autopilot_ctrl'):
        st.markdown('### Konfiguracja sterowania automatycznego')
        paper = st.checkbox('Tryb Paper Trading (symulacja bez ryzyka)', value=bool(cfg['paper_mode']))
        auto = st.checkbox('WŁĄCZ AUTO-PILOTA (automatyczne otwieranie pozycji z Top 20)', value=bool(cfg['auto_trade']))
        confirm = st.checkbox('Potwierdzam gotowość do handlu autonomicznego')
        submitted = st.form_submit_button('ZAPISZ I URUCHOM AUTO-PILOTA')
    
    if submitted:
        cfg['paper_mode'] = paper
        cfg['auto_trade'] = auto
        save_cfg(cfg)
        st.success('Zapisano ustawienia Auto-Pilota.')
        st.rerun()

    st.divider()
    st.markdown('### Cykl Auto-Pilota (Skanowanie Top 20 i handel)')
    
    if st.button('Uruchom pełny cykl Auto-Pilota teraz', type='primary'):
        try:
            ex = exchange_client(ex_id, key, secret, password, cfg['market_type'])
            ex.load_markets()
            
            positions = ex.fetch_positions()
            open_positions = [p for p in positions or [] if abs(float(p.get('contracts') or 0)) > 0]
            current_open_count = len(open_positions)
            active_symbols = [p.get('symbol') for p in open_positions]
            
            st.write(f'Aktywne pozycje na giełdzie: {current_open_count} / limit {cfg["max_positions"]}')
            
            if current_open_count >= int(cfg['max_positions']):
                st.warning('Osiągnięto limit otwartych pozycji.')
            else:
                tickers = ex.fetch_tickers()
                valid_tickers = []
                for sym, t in tickers.items():
                    if 'USDT' in sym and (sym.endswith(':USDT') or cfg['market_type'] == 'swap'):
                        vol = float(t.get('quoteVolume') or t.get('baseVolume') or 0)
                        valid_tickers.append((sym, vol))
                valid_tickers.sort(key=lambda x: x[1], reverse=True)
                top20 = [x[0] for x in valid_tickers[:20]]
                
                executed_trades = 0
                for sym in top20:
                    if current_open_count + executed_trades >= int(cfg['max_positions']):
                        break
                    if sym in active_symbols:
                        continue
                        
                    res = signal_for(cfg, sym, cfg['timeframe'])
                    sig = res['signal']
                    
                    if sig in ('LONG', 'SHORT'):
                        price = res['price']
                        free, _ = balance_usdt(ex)
                        lev = int(cfg['leverage'])
                        stop_fraction = (float(cfg['sl_roe']) / 100.0) / lev
                        qty, notional = calc_qty(ex, sym, free, price, cfg, stop_fraction)
                        
                        if cfg['paper_mode']:
                            event('PAPER', f'[AUTO-PILOT] Zsymulowano wejście {sig} na {sym}')
                            st.success(f'[PAPER] Auto-Pilot znalazł sygnał {sig} dla {sym}!')
                            executed_trades += 1
                        else:
                            if not key or not secret:
                                raise RuntimeError('Brak kluczy API')
                            try:
                                ex.set_leverage(lev, sym)
                            except Exception:
                                pass
                            side = 'buy' if sig == 'LONG' else 'sell'
                            order = market_order(ex, sym, side, qty, False)
                            event('TRADE', f'[AUTO-PILOT] OTWARTO {sig} {sym} id={order.get("id")}')
                            st.success(f'AUTO-PILOT OTWORZYŁ {sig} na {sym}!')
                            executed_trades += 1
                
                if executed_trades == 0:
                    st.info('Przeskanowano Top 20 – brak nowych sygnałów spełniających kryteria.')
        except Exception as e:
            event('ERROR', f'Auto-Pilot error: {e}')
            st.error(f'Błąd cyklu: {e}')

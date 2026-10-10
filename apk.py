import os
import hmac
import json
import time
import math
import sqlite3
import hashlib
import logging
import secrets
from datetime import datetime, timezone
from contextlib import contextmanager

import streamlit as st

try:
    import ccxt
except ImportError:
    ccxt = None

APP_NAME = "Bitget SaaS Futures"
DB_PATH = os.getenv("APP_DB_PATH", "bitget_saas.sqlite3")
LOG_PATH = os.getenv("APP_LOG_PATH", "app.log")
DEFAULT_SYMBOL = "BTC/USDT:USDT"
TIMEFRAMES = ["1m", "5m", "15m", "1h", "4h", "1d"]


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    handlers=[logging.FileHandler(LOG_PATH), logging.StreamHandler()],
)
logger = logging.getLogger(APP_NAME)


def utc_now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@contextmanager
def db():
    conn = sqlite3.connect(DB_PATH, timeout=15)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("PRAGMA foreign_keys=ON")
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db():
    with db() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT NOT NULL UNIQUE COLLATE NOCASE,
                email TEXT NOT NULL UNIQUE COLLATE NOCASE,
                password_hash TEXT NOT NULL,
                role TEXT NOT NULL DEFAULT 'user',
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS settings (
                user_id INTEGER PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
                api_key TEXT NOT NULL DEFAULT '',
                api_secret TEXT NOT NULL DEFAULT '',
                api_passphrase TEXT NOT NULL DEFAULT '',
                sandbox INTEGER NOT NULL DEFAULT 1,
                paper_mode INTEGER NOT NULL DEFAULT 1,
                symbol TEXT NOT NULL DEFAULT 'BTC/USDT:USDT',
                timeframe TEXT NOT NULL DEFAULT '15m',
                risk_pct REAL NOT NULL DEFAULT 0.5,
                leverage INTEGER NOT NULL DEFAULT 2,
                max_notional REAL NOT NULL DEFAULT 100,
                stop_loss_pct REAL NOT NULL DEFAULT 1.0,
                take_profit_pct REAL NOT NULL DEFAULT 2.0,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                created_at TEXT NOT NULL,
                level TEXT NOT NULL,
                message TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS paper_trades (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                created_at TEXT NOT NULL,
                symbol TEXT NOT NULL,
                side TEXT NOT NULL,
                quantity REAL NOT NULL,
                entry_price REAL NOT NULL,
                stop_price REAL NOT NULL,
                target_price REAL NOT NULL,
                status TEXT NOT NULL DEFAULT 'OPEN',
                close_price REAL,
                closed_at TEXT
            );
        """)


def event(user_id, level, message):
    safe_message = str(message)[:1000]

    with db() as conn:
        conn.execute(
            "INSERT INTO events(user_id, created_at, level, message) VALUES(?,?,?,?)",
            (user_id, utc_now(), level, safe_message),
        )

    log_method = (
        level.lower()
        if level.lower() in {"debug", "info", "warning", "error"}
        else "info"
    )
    getattr(logger, log_method)(safe_message)


def hash_password(password, salt=None):
    salt = salt or secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac(
        "sha256", password.encode(), salt.encode(), 310_000
    ).hex()
    return f"pbkdf2_sha256${salt}${digest}"


def verify_password(password, encoded):
    try:
        algorithm, salt, digest = encoded.split("$", 2)

        if algorithm != "pbkdf2_sha256":
            return False

        candidate = hashlib.pbkdf2_hmac(
            "sha256", password.encode(), salt.encode(), 310_000
        ).hex()

        return hmac.compare_digest(candidate, digest)

    except (ValueError, AttributeError):
        return False


def get_user(username):
    with db() as conn:
        return conn.execute(
            "SELECT * FROM users WHERE username=? COLLATE NOCASE",
            (username.strip(),),
        ).fetchone()


def get_settings(user_id):
    with db() as conn:
        row = conn.execute(
            "SELECT * FROM settings WHERE user_id=?", (user_id,)
        ).fetchone()

        if row:
            return dict(row)

        conn.execute(
            "INSERT INTO settings(user_id, updated_at) VALUES(?,?)",
            (user_id, utc_now()),
        )

        row = conn.execute(
            "SELECT * FROM settings WHERE user_id=?", (user_id,)
        ).fetchone()

        return dict(row)


def save_settings(user_id, values):
    with db() as conn:
        conn.execute(
            """
            INSERT INTO settings(
                user_id, api_key, api_secret, api_passphrase,
                sandbox, paper_mode, symbol, timeframe, risk_pct,
                leverage, max_notional, stop_loss_pct,
                take_profit_pct, updated_at
            )
            VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(user_id) DO UPDATE SET
                api_key=excluded.api_key,
                api_secret=excluded.api_secret,
                api_passphrase=excluded.api_passphrase,
                sandbox=excluded.sandbox,
                paper_mode=excluded.paper_mode,
                symbol=excluded.symbol,
                timeframe=excluded.timeframe,
                risk_pct=excluded.risk_pct,
                leverage=excluded.leverage,
                max_notional=excluded.max_notional,
                stop_loss_pct=excluded.stop_loss_pct,
                take_profit_pct=excluded.take_profit_pct,
                updated_at=excluded.updated_at
            """,
            (
                user_id,
                values["api_key"],
                values["api_secret"],
                values["api_passphrase"],
                int(values["sandbox"]),
                int(values["paper_mode"]),
                values["symbol"],
                values["timeframe"],
                values["risk_pct"],
                values["leverage"],
                values["max_notional"],
                values["stop_loss_pct"],
                values["take_profit_pct"],
                utc_now(),
            ),
        )


def make_exchange(settings):
    if ccxt is None:
        raise RuntimeError("Brak biblioteki ccxt. Zainstaluj requirements.txt.")

    if (
        not settings["api_key"]
        or not settings["api_secret"]
        or not settings["api_passphrase"]
    ):
        raise RuntimeError("Uzupełnij API Key, Secret i Passphrase.")

    exchange = ccxt.bitget({
        "apiKey": settings["api_key"],
        "secret": settings["api_secret"],
        "password": settings["api_passphrase"],
        "enableRateLimit": True,
        "timeout": 20000,
        "options": {
            "defaultType": "swap",
        },
    })

    if settings["sandbox"]:
        exchange.set_sandbox_mode(True)

    return exchange


def calc_order_size(
    balance,
    entry_price,
    stop_price,
    risk_pct,
    max_notional,
    leverage,
    free_balance,
):
    """Oblicza ilość bazową i nominał pozycji przed konwersją na kontrakty."""
    vals = [
        balance,
        entry_price,
        stop_price,
        risk_pct,
        max_notional,
        leverage,
        free_balance,
    ]

    try:
        vals = [float(value) for value in vals]
    except (TypeError, ValueError) as exc:
        raise ValueError("Wartości kalkulatora muszą być liczbami.") from exc

    if not all(math.isfinite(value) for value in vals):
        raise ValueError("Wartości liczbowe muszą być skończone.")

    (
        balance,
        entry_price,
        stop_price,
        risk_pct,
        max_notional,
        leverage,
        free_balance,
    ) = vals

    if entry_price <= 0 or stop_price <= 0 or leverage < 1:
        raise ValueError("Cena i dźwignia muszą być większe od zera.")

    if risk_pct <= 0 or max_notional <= 0:
        raise ValueError("Ryzyko i maksymalny nominał muszą być większe od zera.")

    distance = abs(entry_price - stop_price)

    if distance <= 0:
        raise ValueError("Stop-loss nie może być równy cenie wejścia.")

    risk_cash = max(0.0, balance) * risk_pct / 100.0
    risk_based_qty = risk_cash / distance

    notional_cap = min(
        max(0.0, max_notional),
        max(0.0, free_balance) * leverage * 0.90,
    )

    qty = min(risk_based_qty, notional_cap / entry_price)

    if not math.isfinite(qty) or qty <= 0:
        raise ValueError(
            "Wielkość zlecenia wynosi zero; sprawdź saldo, ryzyko i limity."
        )

    return qty, qty * entry_price


def protective_prices(side, entry_price, stop_loss_pct, take_profit_pct):
    """Wylicza poziomy SL/TP dla LONG (buy) i SHORT (sell)."""
    side = str(side).lower()
    entry = float(entry_price)
    sl_pct = float(stop_loss_pct) / 100.0
    tp_pct = float(take_profit_pct) / 100.0

    if side not in {"buy", "sell"}:
        raise ValueError("Kierunek pozycji musi być buy (LONG) albo sell (SHORT).")

    if not math.isfinite(entry) or entry <= 0:
        raise ValueError("Cena wejścia musi być większa od zera.")

    if not math.isfinite(sl_pct) or not math.isfinite(tp_pct):
        raise ValueError("Poziomy SL/TP muszą być skończonymi liczbami.")

    if not (0 < sl_pct < 1) or not (0 < tp_pct < 1):
        raise ValueError(
            "SL i TP muszą być większe od 0% i mniejsze od 100%."
        )

    if side == "buy":
        return entry * (1 - sl_pct), entry * (1 + tp_pct)

    return entry * (1 + sl_pct), entry * (1 - tp_pct)


def place_bitget_protection(
    exchange,
    symbol,
    position_side,
    quantity,
    entry_price,
    stop_loss_pct,
    take_profit_pct,
):
    """
    Składa zlecenie market z dołączonymi SL/TP.

    quantity oznacza tutaj liczbę kontraktów, nie ilość bazową.
    Jeśli giełda odrzuci parametry ochronne, funkcja zgłasza błąd.
    Nie ponawia zlecenia bez ochrony.
    """
    side = str(position_side).lower()

    if side not in {"buy", "sell"}:
        raise ValueError("Kierunek pozycji musi być buy albo sell.")

    market = exchange.market(symbol)

    if not market.get("swap"):
        raise RuntimeError("Wybrany symbol nie jest rynkiem swap/perpetual.")

    contract_size = float(market.get("contractSize") or 1.0)

    if not math.isfinite(contract_size) or contract_size <= 0:
        raise RuntimeError("Giełda zwróciła nieprawidłowy contractSize.")

    qty = float(exchange.amount_to_precision(symbol, float(quantity)))

    if not math.isfinite(qty) or qty <= 0:
        raise ValueError(
            "Ilość kontraktów po zaokrągleniu musi być większa od zera."
        )

    stop_price, target_price = protective_prices(
        side,
        entry_price,
        stop_loss_pct,
        take_profit_pct,
    )

    stop_price = float(exchange.price_to_precision(symbol, stop_price))
    target_price = float(exchange.price_to_precision(symbol, target_price))
    entry_price = float(entry_price)

    if min(stop_price, target_price) <= 0:
        raise ValueError("Ceny SL/TP po zaokrągleniu są nieprawidłowe.")

    if side == "buy" and not (stop_price < entry_price < target_price):
        raise ValueError(
            "Po zaokrągleniu poziomy LONG są nieprawidłowe. "
            "Sprawdź tick size i ustawione procenty."
        )

    if side == "sell" and not (target_price < entry_price < stop_price):
        raise ValueError(
            "Po zaokrągleniu poziomy SHORT są nieprawidłowe. "
            "Sprawdź tick size i ustawione procenty."
        )

    # CCXT na kontraktach może przyjmować amount jako liczbę kontraktów.
    # Nominał w USDT uwzględnia contractSize.
    notional = qty * entry_price * contract_size

    limits = market.get("limits") or {}
    min_amount = (limits.get("amount") or {}).get("min")
    min_cost = (limits.get("cost") or {}).get("min")

    if min_amount is not None and qty < float(min_amount):
        raise ValueError(
            f"Ilość {qty} kontraktów jest mniejsza od minimum giełdy "
            f"{min_amount}."
        )

    if min_cost is not None and notional < float(min_cost):
        raise ValueError(
            f"Nominał {notional:.4f} USDT jest mniejszy od minimum giełdy "
            f"{min_cost}."
        )

    # Te parametry mają być częścią TEGO SAMEGO zlecenia wejściowego.
    # Nie wykonujemy automatycznego ponowienia bez SL/TP.
    params = {
        "stopLoss": {
            "triggerPrice": stop_price,
            "type": "mark_price",
        },
        "takeProfit": {
            "triggerPrice": target_price,
            "type": "mark_price",
        },
    }

    order = exchange.create_order(
        symbol,
        "market",
        side,
        qty,
        None,
        params,
    )

    if not order:
        raise RuntimeError(
            "Giełda nie zwróciła potwierdzenia utworzenia zlecenia."
        )

    return {
        "order": order,
        "stop_price": stop_price,
        "target_price": target_price,
        "quantity": qty,
        "contract_size": contract_size,
        "notional": notional,
    }


def execute_live_trade(user_id, settings, signal, reference_price):
    """Waliduje, wylicza wielkość i składa zlecenie swap z SL/TP."""
    if settings["paper_mode"]:
        raise RuntimeError(
            "Tryb PAPER jest włączony — prawdziwe zlecenie zablokowane."
        )

    if signal not in {"buy", "sell"}:
        raise ValueError("Brak sygnału wejścia buy/sell.")

    exchange = make_exchange(settings)
    exchange.load_markets()

    symbol = settings["symbol"]
    market = exchange.market(symbol)

    if not market.get("swap"):
        raise RuntimeError(
            "Wybrany symbol nie jest rynkiem swap/perpetual."
        )

    contract_size = float(market.get("contractSize") or 1.0)

    if not math.isfinite(contract_size) or contract_size <= 0:
        raise RuntimeError("Nieprawidłowy contractSize dla wybranego rynku.")

    ticker = exchange.fetch_ticker(symbol)
    price = float(ticker.get("last") or reference_price or 0)

    if not math.isfinite(price) or price <= 0:
        raise RuntimeError("Nie udało się pobrać aktualnej ceny.")

    stop, target = protective_prices(
        signal,
        price,
        settings["stop_loss_pct"],
        settings["take_profit_pct"],
    )

    balance_data = exchange.fetch_balance({"type": "swap"})
    usdt = balance_data.get("USDT") or {}

    total = float(usdt.get("total") or 0)
    free = float(usdt.get("free") or 0)

    if not math.isfinite(total) or not math.isfinite(free):
        raise RuntimeError("Giełda zwróciła nieprawidłowe saldo USDT.")

    if total <= 0 or free <= 0:
        raise RuntimeError(
            "Brak dodatniego salda USDT total/free na koncie futures."
        )

    leverage = int(settings["leverage"])

    if leverage < 1:
        raise RuntimeError("Dźwignia musi być większa lub równa 1.")

    try:
        exchange.set_leverage(leverage, symbol)
    except Exception as exc:
        raise RuntimeError(
            f"Nie udało się ustawić dźwigni; zlecenie zablokowane: {exc}"
        ) from exc

    # Najpierw obliczamy wielkość w jednostkach bazowych.
    base_qty, _ = calc_order_size(
        total,
        price,
        stop,
        settings["risk_pct"],
        settings["max_notional"],
        leverage,
        free,
    )

    # Na kontraktach ilość zlecenia może być wyrażona w kontraktach.
    # Dla kontraktu o wielkości 0.001 jednostki bazowej 1 jednostka bazowa
    # odpowiada 1000 kontraktom. Nie wolno wysyłać base_qty wprost.
    contracts_qty = base_qty / contract_size

    result = place_bitget_protection(
        exchange,
        symbol,
        signal,
        contracts_qty,
        price,
        settings["stop_loss_pct"],
        settings["take_profit_pct"],
    )

    order = result["order"] or {}

    event(
        user_id,
        "WARNING",
        f"LIVE {signal.upper()} {symbol} "
        f"contracts={result['quantity']} "
        f"contract_size={result['contract_size']} "
        f"nominał≈{result['notional']:.4f} USDT "
        f"SL={result['stop_price']} TP={result['target_price']} "
        f"order_id={order.get('id')}. "
        "Sprawdź w Bitget, czy pozycja i oba poziomy ochronne są aktywne.",
    )

    return result


def fetch_market_snapshot(exchange, symbol, timeframe, limit=100):
    candles = exchange.fetch_ohlcv(
        symbol,
        timeframe=timeframe,
        limit=limit,
    )

    if not candles or len(candles) < 30:
        raise RuntimeError("Za mało świec do analizy.")

    closes = [float(c[4]) for c in candles]
    volumes = [float(c[5]) for c in candles]

    last = closes[-1]
    previous = closes[-2]
    sma_fast = sum(closes[-10:]) / 10
    sma_slow = sum(closes[-30:]) / 30
    volume_avg = sum(volumes[-20:]) / 20
    volume_ok = volumes[-1] >= volume_avg

    if sma_fast > sma_slow and last > previous and volume_ok:
        signal = "buy"
    elif sma_fast < sma_slow and last < previous and volume_ok:
        signal = "sell"
    else:
        signal = "hold"

    return {
        "price": last,
        "previous": previous,
        "sma_fast": sma_fast,
        "sma_slow": sma_slow,
        "volume": volumes[-1],
        "volume_avg": volume_avg,
        "signal": signal,
        "candles": candles,
    }


def paper_open_trade(user_id, settings, signal, price):
    side = signal.lower()

    if side not in {"buy", "sell"}:
        raise ValueError("Nieprawidłowy kierunek transakcji.")

    stop, target = protective_prices(
        side,
        price,
        settings["stop_loss_pct"],
        settings["take_profit_pct"],
    )

    # Paper mode używa jasno oznaczonego budżetu symulacji.
    budget = min(float(settings["max_notional"]), 100.0)

    if not math.isfinite(price) or price <= 0:
        raise ValueError("Cena paper trade musi być większa od zera.")

    qty = budget / price

    with db() as conn:
        conn.execute(
            """
            INSERT INTO paper_trades(
                user_id, created_at, symbol, side, quantity,
                entry_price, stop_price, target_price, status
            )
            VALUES(?,?,?,?,?,?,?,?, 'OPEN')
            """,
            (
                user_id,
                utc_now(),
                settings["symbol"],
                side,
                qty,
                price,
                stop,
                target,
            ),
        )

    event(
        user_id,
        "INFO",
        f"Paper trade: {side.upper()} {settings['symbol']} @ {price}",
    )

    return qty, stop, target


def update_paper_trades(user_id, symbol, price):
    with db() as conn:
        rows = conn.execute(
            """
            SELECT * FROM paper_trades
            WHERE user_id=? AND symbol=? AND status='OPEN'
            """,
            (user_id, symbol),
        ).fetchall()

        for row in rows:
            hit = None

            if row["side"] == "buy":
                if price <= row["stop_price"]:
                    hit = "STOP"
                elif price >= row["target_price"]:
                    hit = "TARGET"
            else:
                if price >= row["stop_price"]:
                    hit = "STOP"
                elif price <= row["target_price"]:
                    hit = "TARGET"

            if hit:
                conn.execute(
                    """
                    UPDATE paper_trades
                    SET status=?, close_price=?, closed_at=?
                    WHERE id=? AND status='OPEN'
                    """,
                    (hit, price, utc_now(), row["id"]),
                )


def require_login():
    if "user" not in st.session_state:
        st.info("Zaloguj się lub utwórz konto, aby przejść do panelu.")
        st.stop()


def auth_screen():
    st.title(APP_NAME)

    login_tab, register_tab = st.tabs(["Logowanie", "Rejestracja"])

    with login_tab:
        with st.form("login_form"):
            username = st.text_input("Login")
            password = st.text_input("Hasło", type="password")
            submitted = st.form_submit_button(
                "Zaloguj",
                use_container_width=True,
            )

        if submitted:
            user = get_user(username)

            if user and verify_password(password, user["password_hash"]):
                bootstrap_email = (
                    os.getenv("BOOTSTRAP_ADMIN_EMAIL", "").strip().lower()
                )

                if (
                    bootstrap_email
                    and user["email"].lower() == bootstrap_email
                    and user["role"] != "admin"
                ):
                    with db() as conn:
                        conn.execute(
                            "UPDATE users SET role='admin' WHERE id=?",
                            (user["id"],),
                        )

                    user = get_user(username)

                st.session_state["user"] = dict(user)
                event(user["id"], "INFO", "Logowanie zakończone sukcesem")
                st.rerun()

            st.error("Nieprawidłowy login lub hasło.")

    with register_tab:
        with st.form("register_form"):
            new_username = st.text_input("Login", key="reg_username")
            email = st.text_input("E-mail", key="reg_email")
            new_password = st.text_input(
                "Hasło (minimum 12 znaków)",
                type="password",
                key="reg_password",
            )
            confirm = st.text_input(
                "Powtórz hasło",
                type="password",
                key="reg_confirm",
            )
            register = st.form_submit_button(
                "Utwórz konto",
                use_container_width=True,
            )

        if register:
            username_clean = new_username.strip()

            if (
                len(username_clean) < 3
                or not username_clean.replace("_", "").isalnum()
            ):
                st.error(
                    "Login musi mieć co najmniej 3 znaki: "
                    "litery, cyfry lub podkreślenie."
                )

            elif "@" not in email or "." not in email.rsplit("@", 1)[-1]:
                st.error("Podaj poprawny adres e-mail.")

            elif len(new_password) < 12:
                st.error("Hasło musi mieć minimum 12 znaków.")

            elif new_password != confirm:
                st.error("Hasła nie są identyczne.")

            else:
                try:
                    with db() as conn:
                        bootstrap_email = (
                            os.getenv("BOOTSTRAP_ADMIN_EMAIL", "")
                            .strip()
                            .lower()
                        )

                        initial_role = (
                            "admin"
                            if bootstrap_email
                            and email.strip().lower() == bootstrap_email
                            else "user"
                        )

                        conn.execute(
                            """
                            INSERT INTO users(
                                username, email, password_hash, role, created_at
                            )
                            VALUES(?,?,?,?,?)
                            """,
                            (
                                username_clean,
                                email.strip().lower(),
                                hash_password(new_password),
                                initial_role,
                                utc_now(),
                            ),
                        )

                        user_id = conn.execute(
                            "SELECT last_insert_rowid()"
                        ).fetchone()[0]

                        conn.execute(
                            "INSERT INTO settings(user_id, updated_at) VALUES(?,?)",
                            (user_id, utc_now()),
                        )

                    st.success("Konto utworzone. Możesz się zalogować.")

                except sqlite3.IntegrityError:
                    st.error("Ten login lub e-mail jest już zajęty.")


def main():
    st.set_page_config(
        page_title=APP_NAME,
        page_icon="📈",
        layout="wide",
    )

    init_db()

    if "user" not in st.session_state:
        auth_screen()
        return

    user = st.session_state["user"]
    user_id = user["id"]
    settings = get_settings(user_id)

    st.title("📈 Bitget SaaS Futures")
    st.caption(f"Konto: {user['username']} · rola: {user['role']}")

    if st.sidebar.button("Wyloguj"):
        st.session_state.pop("user", None)
        st.rerun()

    pages = [
        "Dashboard",
        "Ustawienia",
        "Historia paper trading",
        "Logi",
    ]

    if user["role"] == "admin":
        pages.append("Administrator")

    page = st.sidebar.radio("Nawigacja", pages)

    if page == "Ustawienia":
        st.subheader("Ustawienia")

        st.warning(
            "Klucze API są przechowywane w lokalnej bazie SQLite. "
            "Na serwerze ogranicz dostęp do pliku bazy, użyj szyfrowania "
            "dysku i kluczy API bez uprawnień wypłat."
        )

        with st.form("settings_form"):
            api_key = st.text_input(
                "Bitget API Key",
                value=settings["api_key"],
            )
            api_secret = st.text_input(
                "Bitget API Secret",
                value=settings["api_secret"],
                type="password",
            )
            api_passphrase = st.text_input(
                "Bitget API Passphrase",
                value=settings["api_passphrase"],
                type="password",
            )
            sandbox = st.checkbox(
                "Tryb demo / sandbox",
                value=bool(settings["sandbox"]),
            )
            paper_mode = st.checkbox(
                "Paper trading (bez prawdziwych zleceń)",
                value=bool(settings["paper_mode"]),
            )
            symbol = st.text_input(
                "Symbol CCXT",
                value=settings["symbol"],
            )
            timeframe = st.selectbox(
                "Interwał",
                TIMEFRAMES,
                index=(
                    TIMEFRAMES.index(settings["timeframe"])
                    if settings["timeframe"] in TIMEFRAMES
                    else 3
                ),
            )
            risk_pct = st.number_input(
                "Ryzyko na transakcję (%)",
                min_value=0.1,
                max_value=2.0,
                value=float(settings["risk_pct"]),
                step=0.1,
            )
            leverage = st.number_input(
                "Dźwignia",
                min_value=1,
                max_value=10,
                value=int(settings["leverage"]),
                step=1,
            )
            max_notional = st.number_input(
                "Maksymalna wartość pozycji w USDT",
                min_value=5.0,
                max_value=100000.0,
                value=float(settings["max_notional"]),
                step=5.0,
            )
            stop_loss_pct = st.number_input(
                "Stop-loss (%)",
                min_value=0.1,
                max_value=20.0,
                value=float(settings["stop_loss_pct"]),
                step=0.1,
            )
            take_profit_pct = st.number_input(
                "Take-profit (%)",
                min_value=0.1,
                max_value=50.0,
                value=float(settings["take_profit_pct"]),
                step=0.1,
            )

            saved = st.form_submit_button(
                "Zapisz ustawienia",
                use_container_width=True,
            )

        if saved:
            if not symbol.strip() or "/" not in symbol:
                st.error(
                    "Podaj symbol w formacie obsługiwanym przez CCXT, "
                    "np. BTC/USDT:USDT."
                )

            else:
                save_settings(
                    user_id,
                    {
                        "api_key": api_key.strip(),
                        "api_secret": api_secret.strip(),
                        "api_passphrase": api_passphrase.strip(),
                        "sandbox": sandbox,
                        "paper_mode": paper_mode,
                        "symbol": symbol.strip(),
                        "timeframe": timeframe,
                        "risk_pct": risk_pct,
                        "leverage": int(leverage),
                        "max_notional": max_notional,
                        "stop_loss_pct": stop_loss_pct,
                        "take_profit_pct": take_profit_pct,
                    },
                )

                event(user_id, "INFO", "Zapisano ustawienia")
                st.success("Ustawienia zapisane.")
                st.rerun()

        if st.button("Testuj połączenie z Bitget", use_container_width=True):
            try:
                exchange = make_exchange(get_settings(user_id))
                markets = exchange.load_markets()

                st.success(
                    f"Połączenie działa. Załadowano {len(markets)} rynków."
                )

            except Exception as exc:
                event(
                    user_id,
                    "ERROR",
                    f"Test połączenia nieudany: {exc}",
                )
                st.error(f"Nie udało się połączyć: {exc}")

    elif page == "Dashboard":
        st.warning(
            "Handel LIVE wysyła zlecenie z dołączonymi parametrami SL/TP. "
            "Przed użyciem na koncie rzeczywistym przetestuj je na koncie "
            "demo Bitget i sprawdź na giełdzie, czy oba poziomy ochronne "
            "są aktywne."
        )

        col1, col2 = st.columns([1, 1])

        with col1:
            st.metric(
                "Tryb",
                "PAPER" if settings["paper_mode"] else "LIVE — wymaga potwierdzenia",
            )
            st.metric("Symbol", settings["symbol"])

        with col2:
            st.metric("Interwał", settings["timeframe"])
            st.metric(
                "Limit wartości pozycji",
                f"{settings['max_notional']:.2f} USDT",
            )

        if st.button(
            "Skanuj rynek",
            type="primary",
            use_container_width=True,
        ):
            try:
                # Dane publiczne rynku nie wymagają kluczy API.
                if ccxt is None:
                    raise RuntimeError(
                        "Brak ccxt. Zainstaluj requirements.txt."
                    )

                exchange = ccxt.bitget({
                    "enableRateLimit": True,
                    "timeout": 20000,
                    "options": {
                        "defaultType": "swap",
                    },
                })

                if settings["sandbox"]:
                    exchange.set_sandbox_mode(True)

                exchange.load_markets()

                snapshot = fetch_market_snapshot(
                    exchange,
                    settings["symbol"],
                    settings["timeframe"],
                )

                update_paper_trades(
                    user_id,
                    settings["symbol"],
                    snapshot["price"],
                )

                st.session_state["last_snapshot"] = snapshot
                st.session_state["last_snapshot_time"] = utc_now()

                st.success("Skanowanie zakończone.")

            except Exception as exc:
                event(
                    user_id,
                    "ERROR",
                    f"Skanowanie nieudane: {exc}",
                )
                st.error(f"Błąd skanowania: {exc}")

        snapshot = st.session_state.get("last_snapshot")

        if snapshot:
            st.subheader("Ostatni odczyt")

            a, b, c = st.columns(3)

            a.metric(
                "Cena",
                f"{snapshot['price']:.8g}",
                f"{snapshot['price'] - snapshot['previous']:.8g}",
            )
            b.metric("SMA 10", f"{snapshot['sma_fast']:.8g}")
            c.metric("SMA 30", f"{snapshot['sma_slow']:.8g}")

            signal = snapshot["signal"]

            st.metric("Sygnał techniczny", signal.upper())

            st.caption(
                f"Odczyt: "
                f"{st.session_state.get('last_snapshot_time', '—')}. "
                "To prosta przykładowa heurystyka, nie gwarancja zysku."
            )

            if signal in {"buy", "sell"}:
                if settings["paper_mode"]:
                    st.info(
                        f"Sygnał {signal.upper()}. "
                        "Tryb PAPER nie wysyła prawdziwych zleceń."
                    )

                    if st.button("Zapisz jako paper trade"):
                        try:
                            qty, stop, target = paper_open_trade(
                                user_id,
                                settings,
                                signal,
                                snapshot["price"],
                            )

                            st.success(
                                f"Zapisano paper trade: ilość {qty:.8g}, "
                                f"SL {stop:.8g}, TP {target:.8g}."
                            )

                        except Exception as exc:
                            st.error(str(exc))

                else:
                    st.error(
                        "LIVE: przycisk poniżej może wysłać prawdziwe "
                        "zlecenie na Bitget."
                    )

                    live_confirm = st.checkbox(
                        f"Potwierdzam otwarcie prawdziwej pozycji "
                        f"{signal.upper()} na {settings['symbol']}",
                        key=(
                            f"live_confirm_{signal}_"
                            f"{st.session_state.get('last_snapshot_time', '')}"
                        ),
                    )

                    if st.button(
                        "OTWÓRZ LIVE Z SL/TP",
                        type="primary",
                        disabled=not live_confirm,
                    ):
                        try:
                            result = execute_live_trade(
                                user_id,
                                settings,
                                signal,
                                snapshot["price"],
                            )

                            order = result["order"] or {}

                            st.success(
                                f"Żądanie zlecenia zostało przyjęte przez "
                                f"interfejs CCXT. ID: {order.get('id', 'brak ID')}; "
                                f"kontrakty: {result['quantity']:.8g}; "
                                f"SL: {result['stop_price']:.8g}; "
                                f"TP: {result['target_price']:.8g}."
                            )

                            st.warning(
                                "To nie jest niezależne potwierdzenie aktywnej "
                                "ochrony. Sprawdź natychmiast na Bitget, czy "
                                "pozycja została otwarta oraz czy oba zlecenia "
                                "ochronne są widoczne i aktywne."
                            )

                        except Exception as exc:
                            event(
                                user_id,
                                "ERROR",
                                f"Zlecenie LIVE odrzucone/błąd: {exc}",
                            )
                            st.error(
                                f"Nie udało się bezpiecznie wysłać zlecenia: {exc}"
                            )

        st.subheader("Kalkulator poziomów SL / TP")

        with st.expander("Sprawdź poziomy dla LONG lub SHORT"):
            test_side = st.selectbox(
                "Kierunek pozycji",
                ["buy", "sell"],
                format_func=lambda x: (
                    "LONG (buy)" if x == "buy" else "SHORT (sell)"
                ),
            )

            test_entry = st.number_input(
                "Cena wejścia do kalkulatora",
                min_value=0.00000001,
                value=60000.0,
                format="%.8f",
                key="protect_entry",
            )

            test_sl = st.number_input(
                "Stop-loss (%)",
                min_value=0.1,
                max_value=99.0,
                value=float(settings["stop_loss_pct"]),
                step=0.1,
                key="protect_sl",
            )

            test_tp = st.number_input(
                "Take-profit (%)",
                min_value=0.1,
                max_value=99.0,
                value=float(settings["take_profit_pct"]),
                step=0.1,
                key="protect_tp",
            )

            if st.button("Wylicz SL / TP", key="protect_calc"):
                try:
                    sl_price, tp_price = protective_prices(
                        test_side,
                        test_entry,
                        test_sl,
                        test_tp,
                    )

                    st.write(f"Stop-loss: **{sl_price:.8g}**")
                    st.write(f"Take-profit: **{tp_price:.8g}**")

                    st.caption(
                        "LONG: SL poniżej wejścia, TP powyżej. "
                        "SHORT: SL powyżej wejścia, TP poniżej."
                    )

                except Exception as exc:
                    st.error(str(exc))

        st.subheader("Bezpieczne obliczenie wielkości pozycji")

        with st.expander("Kalkulator ryzyka"):
            balance = st.number_input(
                "Saldo USDT (do symulacji)",
                min_value=0.0,
                value=1000.0,
                step=100.0,
            )

            entry = st.number_input(
                "Cena wejścia",
                min_value=0.00000001,
                value=60000.0,
                format="%.8f",
            )

            stop = st.number_input(
                "Cena stop-loss",
                min_value=0.00000001,
                value=59400.0,
                format="%.8f",
            )

            free = st.number_input(
                "Wolne saldo USDT",
                min_value=0.0,
                value=1000.0,
                step=100.0,
            )

            if st.button("Oblicz wielkość"):
                try:
                    qty, notional = calc_order_size(
                        balance,
                        entry,
                        stop,
                        settings["risk_pct"],
                        settings["max_notional"],
                        settings["leverage"],
                        free,
                    )

                    st.write(f"Ilość bazowa: **{qty:.8g}**")
                    st.write(f"Nominał: **{notional:.2f} USDT**")

                    st.write(
                        f"Ryzyko nominalne przy SL: "
                        f"**{qty * abs(entry - stop):.2f} USDT**"
                    )

                except Exception as exc:
                    st.error(str(exc))

    elif page == "Historia paper trading":
        st.subheader("Historia paper trading")

        if st.button(
            "Awaryjnie zamknij wszystkie otwarte pozycje PAPER",
            type="secondary",
        ):
            with db() as conn:
                conn.execute(
                    """
                    UPDATE paper_trades
                    SET status='MANUAL_CLOSE', closed_at=?
                    WHERE user_id=? AND status='OPEN'
                    """,
                    (utc_now(), user_id),
                )

            event(
                user_id,
                "WARNING",
                "Awaryjnie zamknięto otwarte pozycje PAPER",
            )

            st.success(
                "Otwarte pozycje paper trading zostały oznaczone jako zamknięte."
            )
            st.rerun()

        with db() as conn:
            trades = conn.execute(
                """
                SELECT * FROM paper_trades
                WHERE user_id=?
                ORDER BY id DESC
                LIMIT 200
                """,
                (user_id,),
            ).fetchall()

        if trades:
            st.dataframe(
                [dict(row) for row in trades],
                use_container_width=True,
                hide_index=True,
            )
        else:
            st.info("Brak transakcji paper trading.")

    elif page == "Logi":
        with db() as conn:
            rows = conn.execute(
                """
                SELECT created_at, level, message
                FROM events
                WHERE user_id=?
                ORDER BY id DESC
                LIMIT 200
                """,
                (user_id,),
            ).fetchall()

        st.dataframe(
            [dict(row) for row in rows],
            use_container_width=True,
            hide_index=True,
        )

    elif page == "Administrator":
        st.subheader("Panel administratora")

        st.caption(
            "Pierwszego administratora ustaw przez zmienną środowiskową "
            "BOOTSTRAP_ADMIN_EMAIL przed uruchomieniem aplikacji."
        )

        with db() as conn:
            users = conn.execute(
                """
                SELECT id, username, email, role, created_at
                FROM users
                ORDER BY id
                """
            ).fetchall()

        st.dataframe(
            [dict(row) for row in users],
            use_container_width=True,
            hide_index=True,
        )

        target_email = (
            os.getenv("BOOTSTRAP_ADMIN_EMAIL", "").strip().lower()
        )

        if (
            target_email
            and user["email"].lower() == target_email
            and user["role"] != "admin"
        ):
            if st.button("Nadaj mi rolę administratora"):
                with db() as conn:
                    conn.execute(
                        "UPDATE users SET role='admin' WHERE id=?",
                        (user_id,),
                    )

                st.session_state["user"]["role"] = "admin"
                st.success("Rola administratora została ustawiona.")
                st.rerun()


if __name__ == "__main__":
    main()

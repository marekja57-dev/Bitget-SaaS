
#!/usr/bin/env python3

import os
import sys
import json
import time
import math
import signal
import sqlite3
import logging
from contextlib import contextmanager
from logging.handlers import RotatingFileHandler

import ccxt
import pandas as pd
from cryptography.fernet import Fernet, InvalidToken


# ============================================================
# KONFIGURACJA
# ============================================================

ROOT = os.path.dirname(os.path.abspath(__file__))

DB_PATH = os.getenv(
    "ENGINE_DB_PATH",
    os.path.join(ROOT, "bitget_saas.db")
)

LOG_PATH = os.getenv(
    "ENGINE_LOG_PATH",
    os.path.join(ROOT, "logs", "engine.log")
)

POLL_SECONDS = max(
    5,
    int(os.getenv("ENGINE_POLL_SECONDS", "20"))
)

# Domyślnie prawdziwy handel jest zablokowany.
ENABLE_LIVE_TRADING = (
    os.getenv("ENABLE_LIVE_TRADING", "false").lower() == "true"
)

STOP = False


# ============================================================
# LOGOWANIE
# ============================================================

os.makedirs(os.path.dirname(LOG_PATH) or ".", exist_ok=True)

logger = logging.getLogger("bitget_engine")
logger.setLevel(logging.INFO)

formatter = logging.Formatter(
    "%(asctime)s %(levelname)s %(message)s"
)

file_handler = RotatingFileHandler(
    LOG_PATH,
    maxBytes=5_000_000,
    backupCount=5
)

console_handler = logging.StreamHandler(sys.stdout)

file_handler.setFormatter(formatter)
console_handler.setFormatter(formatter)

logger.addHandler(file_handler)
logger.addHandler(console_handler)


# ============================================================
# DOMYŚLNE USTAWIENIA KLIENTA
# ============================================================

DEFAULT_CONFIG = {
    "enabled": False,
    "paper_mode": True,

    "exchange": "bitget",
    "market_type": "swap",

    "symbols": [
        "BTC/USDT:USDT"
    ],

    "timeframe": "5m",
    "candle_limit": 120,
    "scan_seconds": 30,

    "risk_usdt": 10.0,
    "max_positions": 1,
    "max_leverage": 2,

    "stop_loss_roe_pct": 20.0,
    "take_profit_roe_pct": 30.0,

    "allow_long": True,
    "allow_short": True,

    "ema_fast": 9,
    "ema_slow": 21,

    "rsi_period": 14,
    "rsi_long_min": 50.0,
    "rsi_short_max": 50.0,

    "adx_period": 14,
    "adx_min": 15.0,

    "cooldown_minutes": 30,
    "max_daily_entries": 10
}


# ============================================================
# BAZA DANYCH
# ============================================================

@contextmanager
def db():
    connection = sqlite3.connect(
        DB_PATH,
        timeout=30
    )

    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA busy_timeout=30000")
    connection.execute("PRAGMA journal_mode=WAL")

    try:
        yield connection
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def init_db():
    with db() as connection:
        connection.executescript("""
        CREATE TABLE IF NOT EXISTS engine_clients (
            client_id TEXT PRIMARY KEY,
            enabled INTEGER NOT NULL DEFAULT 0,
            api_key_enc TEXT NOT NULL,
            secret_enc TEXT NOT NULL,
            passphrase_enc TEXT NOT NULL,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS engine_settings (
            client_id TEXT PRIMARY KEY,
            config_json TEXT NOT NULL,
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS engine_orders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            client_id TEXT NOT NULL,
            symbol TEXT NOT NULL,
            side TEXT NOT NULL,
            status TEXT NOT NULL,
            exchange_order_id TEXT,
            client_order_id TEXT NOT NULL UNIQUE,
            amount REAL,
            entry_price REAL,
            sl_price REAL,
            tp_price REAL,
            mode TEXT NOT NULL,
            detail TEXT,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS engine_cooldowns (
            client_id TEXT NOT NULL,
            symbol TEXT NOT NULL,
            until_ts REAL NOT NULL,
            PRIMARY KEY (client_id, symbol)
        );

        CREATE INDEX IF NOT EXISTS idx_engine_orders_client_status
        ON engine_orders(client_id, status);

        CREATE INDEX IF NOT EXISTS idx_engine_orders_created
        ON engine_orders(created_at);
        """)


# ============================================================
# SZYFROWANIE KLUCZY API
# ============================================================

def get_cipher():
    key = os.getenv("ENGINE_FERNET_KEY", "").strip()

    if not key:
        raise RuntimeError(
            "Brak ENGINE_FERNET_KEY. Ustaw go w pliku .env."
        )

    try:
        return Fernet(key.encode())
    except Exception as exc:
        raise RuntimeError(
            "Nieprawidłowy ENGINE_FERNET_KEY."
        ) from exc


def decrypt_secret(value):
    try:
        return get_cipher().decrypt(
            value.encode()
        ).decode()

    except (InvalidToken, ValueError) as exc:
        raise RuntimeError(
            "Nie można odszyfrować klucza API. "
            "Sprawdź ENGINE_FERNET_KEY."
        ) from exc


# ============================================================
# KLIENCI I ICH USTAWIENIA
# ============================================================

def load_clients():
    with db() as connection:
        rows = connection.execute("""
            SELECT
                c.client_id,
                c.enabled AS client_enabled,
                c.api_key_enc,
                c.secret_enc,
                c.passphrase_enc,
                s.config_json
            FROM engine_clients c
            JOIN engine_settings s
                ON s.client_id = c.client_id
            WHERE c.enabled = 1
        """).fetchall()

    result = []

    for row in rows:
        try:
            config = DEFAULT_CONFIG.copy()
            config.update(
                json.loads(row["config_json"] or "{}")
            )

            if not config.get("enabled", False):
                continue

            result.append({
                "client_id": row["client_id"],
                "apiKey": decrypt_secret(row["api_key_enc"]),
                "secret": decrypt_secret(row["secret_enc"]),
                "password": decrypt_secret(row["passphrase_enc"]),
                "config": config
            })

        except Exception:
            logger.exception(
                "Nie można załadować klienta %s",
                row["client_id"]
            )

    return result


def load_latest_config(client_id):
    """
    Pobiera najnowsze ustawienia bezpośrednio z bazy.
    Pozwala reagować na zmiany ustawień podczas działania silnika.
    """

    with db() as connection:
        row = connection.execute("""
            SELECT c.enabled, s.config_json
            FROM engine_clients c
            JOIN engine_settings s
                ON s.client_id = c.client_id
            WHERE c.client_id = ?
        """, (client_id,)).fetchone()

    if not row or not row["enabled"]:
        return None

    config = DEFAULT_CONFIG.copy()
    config.update(json.loads(row["config_json"] or "{}"))

    if not config.get("enabled", False):
        return None

    return config


# ============================================================
# POŁĄCZENIE Z BITGET
# ============================================================

def create_exchange(client, config):
    exchange_class = getattr(
        ccxt,
        config.get("exchange", "bitget")
    )

    exchange = exchange_class({
        "apiKey": client["apiKey"],
        "secret": client["secret"],
        "password": client["password"],
        "enableRateLimit": True,
        "timeout": 20000,
        "options": {
            "defaultType": "swap"
        }
    })

    exchange.load_markets()

    return exchange


# ============================================================
# WSKAŹNIKI TECHNICZNE
# ============================================================

def calculate_indicators(df, config):
    required = max(
        int(config["ema_slow"]),
        int(config["adx_period"]) * 2,
        int(config["rsi_period"])
    ) + 5

    if len(df) < required:
        return None

    close = df["close"]
    high = df["high"]
    low = df["low"]

    # EMA
    ema_fast = close.ewm(
        span=int(config["ema_fast"]),
        adjust=False
    ).mean()

    ema_slow = close.ewm(
        span=int(config["ema_slow"]),
        adjust=False
    ).mean()

    # RSI
    delta = close.diff()

    gain = delta.clip(lower=0).ewm(
        alpha=1 / int(config["rsi_period"]),
        adjust=False
    ).mean()

    loss = (-delta.clip(upper=0)).ewm(
        alpha=1 / int(config["rsi_period"]),
        adjust=False
    ).mean()

    relative_strength = gain / loss.replace(
        0,
        float("nan")
    )

    rsi = 100 - (
        100 / (1 + relative_strength)
    )

    # ADX
    true_range = pd.concat([
        high - low,
        (high - close.shift()).abs(),
        (low - close.shift()).abs()
    ], axis=1).max(axis=1)

    up = high.diff()
    down = -low.diff()

    plus_dm = up.where(
        (up > down) & (up > 0),
        0.0
    )

    minus_dm = down.where(
        (down > up) & (down > 0),
        0.0
    )

    period = int(config["adx_period"])

    atr = true_range.ewm(
        alpha=1 / period,
        adjust=False
    ).mean()

    plus_di = (
        100 * plus_dm.ewm(
            alpha=1 / period,
            adjust=False
        ).mean() / atr.replace(0, float("nan"))
    )

    minus_di = (
        100 * minus_dm.ewm(
            alpha=1 / period,
            adjust=False
        ).mean() / atr.replace(0, float("nan"))
    )

    dx = (
        100 * (plus_di - minus_di).abs()
        / (plus_di + minus_di).replace(0, float("nan"))
    )

    adx = dx.ewm(
        alpha=1 / period,
        adjust=False
    ).mean()

    # Ostatnia świeca może być jeszcze otwarta.
    # Używamy poprzedniej, zamkniętej świecy.
    i = -2

    values = {
        "price": float(close.iloc[i]),
        "ema_fast": float(ema_fast.iloc[i]),
        "ema_slow": float(ema_slow.iloc[i]),
        "rsi": float(rsi.iloc[i]),
        "adx": float(adx.iloc[i])
    }

    if not all(math.isfinite(v) for v in values.values()):
        return None

    return values


def get_signal(exchange, symbol, config):
    try:
        candles = exchange.fetch_ohlcv(
            symbol,
            timeframe=config["timeframe"],
            limit=int(config["candle_limit"])
        )

        df = pd.DataFrame(
            candles,
            columns=[
                "timestamp",
                "open",
                "high",
                "low",
                "close",
                "volume"
            ]
        )

        indicators = calculate_indicators(df, config)

        if not indicators:
            return None

        if indicators["adx"] < float(config["adx_min"]):
            return None

        long_signal = (
            config["allow_long"]
            and indicators["ema_fast"] > indicators["ema_slow"]
            and indicators["rsi"] >= float(config["rsi_long_min"])
        )

        short_signal = (
            config["allow_short"]
            and indicators["ema_fast"] < indicators["ema_slow"]
            and indicators["rsi"] <= float(config["rsi_short_max"])
        )

        if long_signal:
            return "buy", indicators

        if short_signal:
            return "sell", indicators

    except Exception:
        logger.exception(
            "Błąd sygnału dla %s",
            symbol
        )

    return None


# ============================================================
# LIMITY, POZYCJE I COOLDOWN
# ============================================================

def is_cooling_down(client_id, symbol):
    with db() as connection:
        row = connection.execute("""
            SELECT until_ts
            FROM engine_cooldowns
            WHERE client_id = ? AND symbol = ?
        """, (client_id, symbol)).fetchone()

    return bool(
        row and float(row["until_ts"]) > time.time()
    )


def set_cooldown(client_id, symbol, minutes):
    with db() as connection:
        connection.execute("""
            INSERT INTO engine_cooldowns
                (client_id, symbol, until_ts)
            VALUES (?, ?, ?)
            ON CONFLICT(client_id, symbol)
            DO UPDATE SET until_ts = excluded.until_ts
        """, (
            client_id,
            symbol,
            time.time() + float(minutes) * 60
        ))


def count_active_orders(client_id):
    """
    Sygnały PAPER nie są prawdziwymi otwartymi pozycjami.
    Dzięki temu PAPER nie zablokuje kolejnych skanów.
    """

    with db() as connection:
        return connection.execute("""
            SELECT COUNT(*)
            FROM engine_orders
            WHERE client_id = ?
              AND status IN ('SUBMITTED', 'OPEN', 'UNKNOWN')
        """, (client_id,)).fetchone()[0]


def count_daily_entries(client_id):
    with db() as connection:
        return connection.execute("""
            SELECT COUNT(*)
            FROM engine_orders
            WHERE client_id = ?
              AND created_at >= date('now')
              AND status IN (
                  'PAPER_SIGNAL',
                  'SUBMITTED',
                  'OPEN',
                  'UNKNOWN'
              )
        """, (client_id,)).fetchone()[0]


def exchange_has_position(exchange, symbol):
    """
    Jeśli giełda nie pozwala odczytać pozycji,
    błąd ma zatrzymać otwieranie zlecenia dla tego symbolu.
    """

    positions = exchange.fetch_positions([symbol])

    for position in positions:
        contracts = position.get("contracts")

        if contracts is None:
            info = position.get("info") or {}
            contracts = abs(float(info.get("total", 0) or 0))

        if (
            position.get("symbol") == symbol
            and float(contracts or 0) > 0
        ):
            return True

    return False


# ============================================================
# WIELKOŚĆ POZYCJI
# ============================================================

def calculate_amount(exchange, symbol, price, risk_usdt, leverage):
    """
    risk_usdt jest tu przybliżoną alokacją margin,
    a nie maksymalną stratą na transakcji.
    """

    notional = float(risk_usdt) * int(leverage)

    amount = notional / float(price)

    amount = float(
        exchange.amount_to_precision(symbol, amount)
    )

    market = exchange.market(symbol)

    amount_limits = (
        (market.get("limits") or {}).get("amount") or {}
    )

    minimum = amount_limits.get("min")

    if amount <= 0:
        raise ValueError("Wielkość pozycji musi być większa od zera.")

    if minimum and amount < float(minimum):
        raise ValueError(
            f"Kwota {amount} jest mniejsza od minimum giełdy {minimum}."
        )

    return amount


def calculate_sl_tp(side, price, sl_roe, tp_roe, leverage):
    """
    Przybliżenie ceny SL/TP na podstawie ROE i dźwigni.
    Nie uwzględnia opłat, funding, poślizgu ani maintenance margin.
    """

    sl_move = float(sl_roe) / (100 * leverage)
    tp_move = float(tp_roe) / (100 * leverage)

    if side == "buy":
        sl = price * (1 - sl_move)
        tp = price * (1 + tp_move)
    else:
        sl = price * (1 + sl_move)
        tp = price * (1 - tp_move)

    return sl, tp


# ============================================================
# ZAPIS SYGNAŁU / ZLECENIA
# ============================================================

def submit_trade(client, exchange, symbol, side, indicators, config):
    client_id = client["client_id"]

    if is_cooling_down(client_id, symbol):
        return

    if count_active_orders(client_id) >= int(config["max_positions"]):
        logger.info(
            "client=%s: osiągnięto limit aktywnych zleceń",
            client_id
        )
        return

    if count_daily_entries(client_id) >= int(config["max_daily_entries"]):
        logger.info(
            "client=%s: osiągnięto limit dzienny",
            client_id
        )
        return

    # Sprawdzamy pozycję na giełdzie przed wysłaniem zlecenia.
    if exchange_has_position(exchange, symbol):
        logger.info(
            "client=%s symbol=%s: pozycja już istnieje",
            client_id,
            symbol
        )
        return

    price = float(indicators["price"])
    leverage = max(1, int(config["max_leverage"]))

    amount = calculate_amount(
        exchange,
        symbol,
        price,
        float(config["risk_usdt"]),
        leverage
    )

    sl, tp = calculate_sl_tp(
        side,
        price,
        config["stop_loss_roe_pct"],
        config["take_profit_roe_pct"],
        leverage
    )

    sl = float(exchange.price_to_precision(symbol, sl))
    tp = float(exchange.price_to_precision(symbol, tp))

    # Identyfikator ogranicza duplikaty dla tej samej minuty.
    bucket = int(time.time() // 60)

    safe_symbol = (
        symbol.replace("/", "")
        .replace(":", "")
        .replace("-", "")
    )[:8]

    client_oid = (
        f"eng-{client_id[:7]}-{safe_symbol}-{side}-{bucket}"
    )[:48]

    paper_mode = bool(config.get("paper_mode", True))

    mode = "PAPER" if paper_mode else "REAL"

    # Rejestrujemy identyfikator przed próbą wysłania zlecenia.
    with db() as connection:
        try:
            connection.execute("""
                INSERT INTO engine_orders (
                    client_id,
                    symbol,
                    side,
                    status,
                    client_order_id,
                    amount,
                    entry_price,
                    sl_price,
                    tp_price,
                    mode
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                client_id,
                symbol,
                side,
                "PENDING",
                client_oid,
                amount,
                price,
                sl,
                tp,
                mode
            ))

        except sqlite3.IntegrityError:
            logger.info(
                "client=%s symbol=%s: pominięto duplikat",
                client_id,
                symbol
            )
            return

    # ---------------- PAPER ----------------

    if paper_mode:
        with db() as connection:
            connection.execute("""
                UPDATE engine_orders
                SET status = 'PAPER_SIGNAL',
                    detail = ?
                WHERE client_order_id = ?
            """, (
                "Sygnał symulacyjny. Nie wysłano zlecenia na giełdę.",
                client_oid
            ))

        set_cooldown(
            client_id,
            symbol,
            config["cooldown_minutes"]
        )

        logger.info(
            "PAPER client=%s side=%s symbol=%s amount=%s "
            "price≈%s SL=%s TP=%s",
            client_id,
            side,
            symbol,
            amount,
            price,
            sl,
            tp
        )

        return

    # ---------------- BEZPIECZNIK REAL ----------------

    if not ENABLE_LIVE_TRADING:
        with db() as connection:
            connection.execute("""
                UPDATE engine_orders
                SET status = 'BLOCKED',
                    detail = ?
                WHERE client_order_id = ?
            """, (
                "Handel REAL zablokowany przez ENABLE_LIVE_TRADING=false.",
                client_oid
            ))

        logger.warning(
            "REAL zablokowany dla klienta %s",
            client_id
        )
        return

    # ---------------- PRAWDZIWE ZLECENIE ----------------
    #
    # UWAGA:
    # Parametry SL/TP Bitget muszą zostać zweryfikowane
    # na koncie demo dla Twojego trybu pozycji i wersji CCXT.
    # Nie zakładaj, że zlecenie ochronne zostało przyjęte,
    # dopóki nie potwierdzisz tego na giełdzie.

    try:
        exchange.set_leverage(leverage, symbol)

        params = {
            "clientOid": client_oid,
            "presetStopLossPrice": str(sl),
            "presetStopSurplusPrice": str(tp)
        }

        order = exchange.create_order(
            symbol,
            "market",
            side,
            amount,
            None,
            params
        )

        with db() as connection:
            connection.execute("""
                UPDATE engine_orders
                SET status = 'SUBMITTED',
                    exchange_order_id = ?,
                    detail = ?
                WHERE client_order_id = ?
            """, (
                str(order.get("id") or ""),
                json.dumps(order, default=str),
                client_oid
            ))

        set_cooldown(
            client_id,
            symbol,
            config["cooldown_minutes"]
        )

        logger.warning(
            "REAL wysłano: client=%s symbol=%s side=%s id=%s",
            client_id,
            symbol,
            side,
            order.get("id")
        )

    except Exception as exc:
        # Nie ponawiamy automatycznie zlecenia po timeout.
        # Giełda mogła przyjąć je przed zerwaniem połączenia.
        with db() as connection:
            connection.execute("""
                UPDATE engine_orders
                SET status = 'UNKNOWN',
                    detail = ?
                WHERE client_order_id = ?
            """, (
                str(exc)[:1500],
                client_oid
            ))

        logger.exception(
            "Nieznany wynik zlecenia. Wymagana kontrola giełdy. "
            "client=%s symbol=%s",
            client_id,
            symbol
        )


# ============================================================
# OBSŁUGA JEDNEGO KLIENTA
# ============================================================

def process_client(client):
    exchange = None
    client_id = client["client_id"]

    try:
        config = client["config"]

        exchange = create_exchange(client, config)

        # Sprawdzenie połączenia i uprawnień odczytu.
        exchange.fetch_balance()

        for symbol in config.get("symbols", []):
            if STOP:
                break

            try:
                # Odświeżamy ustawienia przed każdym symbolem.
                latest_config = load_latest_config(client_id)

                if latest_config is None:
                    logger.info(
                        "Klient %s został wyłączony",
                        client_id
                    )
                    break

                signal_result = get_signal(
                    exchange,
                    symbol,
                    latest_config
                )

                if signal_result:
                    side, indicators = signal_result

                    submit_trade(
                        client,
                        exchange,
                        symbol,
                        side,
                        indicators,
                        latest_config
                    )

            except Exception:
                logger.exception(
                    "Błąd klient=%s symbol=%s",
                    client_id,
                    symbol
                )

    except Exception:
        logger.exception(
            "Błąd połączenia lub przetwarzania klienta %s",
            client_id
        )

    finally:
        if exchange:
            try:
                exchange.close()
            except Exception:
                pass


# ============================================================
# GŁÓWNA PĘTLA
# ============================================================

def stop_handler(signum, frame):
    global STOP
    STOP = True

    logger.info(
        "Otrzymano sygnał zatrzymania: %s",
        signum
    )


def main():
    signal.signal(signal.SIGTERM, stop_handler)
    signal.signal(signal.SIGINT, stop_handler)

    init_db()

    logger.info(
        "Silnik uruchomiony. DB=%s LIVE=%s",
        DB_PATH,
        ENABLE_LIVE_TRADING
    )

    while not STOP:
        started = time.time()

        try:
            active_clients = load_clients()

            for client in active_clients:
                if STOP:
                    break

                process_client(client)

        except Exception:
            logger.exception("Błąd głównej pętli")

        elapsed = time.time() - started
        sleep_seconds = max(
            1,
            int(POLL_SECONDS - elapsed)
        )

        for _ in range(sleep_seconds):
            if STOP:
                break
            time.sleep(1)

    logger.info("Silnik zatrzymany")


if __name__ == "__main__":
    main()

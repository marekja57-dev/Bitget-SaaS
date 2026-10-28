#!/usr/bin/env python3

import os
import sys
import time
import json
import logging
import sqlite3
import signal
from pathlib import Path

import ccxt
import pandas as pd

# ============================================================
# CZYSTY SKRYPT SILNIKA W TLE
# ============================================================

ROOT = Path("/opt/bitget-saas")
DB_PATH = ROOT / "bitget_sas.db"
LOG_PATH = ROOT / "logs" / "engine.log"

LOG_PATH.parent.mkdir(parents=True, exist_ok=True)

logging.basicConfig(
    filename=str(LOG_PATH),
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)
logger = logging.getLogger("bitget_engine")

STOP = False

def stop_handler(signum, frame):
    global STOP
    STOP = True
    logger.info("Otrzymano sygnał zatrzymania: %s", signum)

signal.signal(signal.SIGTERM, stop_handler)
signal.signal(signal.SIGINT, stop_handler)

def get_db():
    con = sqlite3.connect(DB_PATH, timeout=20)
    con.row_factory = sqlite3.Row
    return con

def load_config():
    try:
        with get_db() as con:
            row = con.execute("SELECT v FROM settings WHERE k='main'").fetchone()
            if row:
                return json.loads(row["v"])
    except Exception as exc:
        logger.error("Błąd wczytywania konfiguracji z bazy: %s", exc)
    return {}

def run_engine():
    logger.info("Silnik uruchomiony. DB=%s LIVE=False (bezpieczny tryb)", DB_PATH)
    
    while not STOP:
        try:
            cfg = load_config()
            auto_trade = cfg.get("auto_trade", False)
            exchange_id = cfg.get("exchange", "bitget")
            market_type = cfg.get("market_type", "swap")
            
            if auto_trade:
                logger.info("Autohandel jest włączony w bazie. Skanowanie rynku...")
                # Tutaj silnik może wykonywać pętlę sprawdzającą okazje
            else:
                logger.debug("Autohandel wyłączony w konfiguracji. Oczekiwanie...")

        except Exception as exc:
            logger.error("Błąd w pętli silnika: %s", exc)

        for _ in range(30): # Sprawdzaj co 30 sekund
            if STOP:
                break
            time.sleep(1)

    logger.info("Silnik zatrzymany.")

if __name__ == "__main__":
    run_engine()


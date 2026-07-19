"""
🤖 Advanced Crypto Signals Telegram Bot - 4H

الهيكل:
1) جلب حتى 10,000 عملة من CoinGecko.
2) مطابقة الرموز مع Gate.io وKuCoin وMEXC وOKX.
3) اختيار المنصة الأعلى سيولة لكل زوج USDT.
4) جلب شموع 4H من المنصة المختارة.
5) حساب Stoch RSI وMACD ونسبة فوليوم الشمعة.
6) إرسال تنبيه مبكر أو إشارة مؤكدة إلى تيليغرام.
7) متابعة الأهداف ووقف الخسارة وحفظ النتائج.

Python 3.10+
"""

import asyncio
import json
import logging
import math
import os
import sqlite3
import time
from datetime import date, datetime
from typing import Any, Dict, List, Optional

import pytz
import requests
from telegram import Bot
from telegram.constants import ParseMode


# =========================================================
# الإعدادات العامة
# =========================================================

SAUDI_TZ = pytz.timezone("Asia/Riyadh")

TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
TELEGRAM_CHANNEL_ID = os.environ.get("TELEGRAM_CHANNEL_ID", "").strip()

CHECK_INTERVAL = int(os.environ.get("CHECK_INTERVAL", "1800"))
DAILY_SUMMARY_HOUR = int(os.environ.get("DAILY_SUMMARY_HOUR", "0"))

MAX_MARKETS = int(os.environ.get("MAX_MARKETS", "10000"))
CANDLE_LIMIT = int(os.environ.get("CANDLE_LIMIT", "200"))

TIMEFRAME = os.environ.get("TIMEFRAME", "4h").strip().lower()
EXCHANGES = [
    item.strip().lower()
    for item in os.environ.get(
        "EXCHANGES", "gateio,kucoin,mexc,okx"
    ).split(",")
    if item.strip()
]
EXCHANGE_PRIORITY = [
    item.strip().lower()
    for item in os.environ.get(
        "EXCHANGE_PRIORITY", "gateio,kucoin,mexc,okx"
    ).split(",")
    if item.strip()
]
EXCHANGE_SELECTION_MODE = os.environ.get(
    "EXCHANGE_SELECTION_MODE", "highest_volume"
).strip().lower()

REQUEST_TIMEOUT = int(os.environ.get("REQUEST_TIMEOUT", "25"))
REQUEST_RETRIES = int(os.environ.get("REQUEST_RETRIES", "3"))
REQUEST_RETRY_DELAY = float(os.environ.get("REQUEST_RETRY_DELAY", "2"))
COIN_REQUEST_DELAY = float(os.environ.get("COIN_REQUEST_DELAY", "0.20"))

HISTORY_FILE = os.environ.get("HISTORY_FILE", "signals_history.json")
DB_FILE = os.environ.get("DB_FILE", "signals_bot.db")
ALERT_STATE_FILE = os.environ.get("ALERT_STATE_FILE", "alert_state.json")
COINGECKO_CACHE_FILE = os.environ.get(
    "COINGECKO_CACHE_FILE", "coingecko_cache.json"
)

ACCOUNT_BALANCE = float(os.environ.get("ACCOUNT_BALANCE", "1000"))
RISK_PER_TRADE_PCT = float(os.environ.get("RISK_PER_TRADE_PCT", "1"))


# =========================================================
# إعدادات CoinGecko
# =========================================================

COINGECKO_API_KEY = os.environ.get("COINGECKO_API_KEY", "").strip()
COINGECKO_API_MODE = os.environ.get(
    "COINGECKO_API_MODE", "demo"
).strip().lower()

if COINGECKO_API_MODE == "pro":
    COINGECKO_BASE_URL = "https://pro-api.coingecko.com/api/v3"
    COINGECKO_API_HEADER = "x-cg-pro-api-key"
else:
    COINGECKO_BASE_URL = "https://api.coingecko.com/api/v3"
    COINGECKO_API_HEADER = "x-cg-demo-api-key"

COINGECKO_MARKETS_URL = f"{COINGECKO_BASE_URL}/coins/markets"

COINGECKO_MAX_COINS = int(
    os.environ.get("COINGECKO_MAX_COINS", "10000")
)
COINGECKO_PER_PAGE = min(
    max(int(os.environ.get("COINGECKO_PER_PAGE", "250")), 1),
    250,
)
COINGECKO_REFRESH_HOURS = float(
    os.environ.get("COINGECKO_REFRESH_HOURS", "6")
)
COINGECKO_PAGE_DELAY = float(
    os.environ.get("COINGECKO_PAGE_DELAY", "0.70")
)
COINGECKO_ORDER = os.environ.get(
    "COINGECKO_ORDER", "volume_desc"
).strip()

MIN_COINGECKO_VOLUME_24H = float(
    os.environ.get("MIN_COINGECKO_VOLUME_24H", "3000000")
)
MIN_MARKET_CAP_USD = float(
    os.environ.get("MIN_MARKET_CAP_USD", "0")
)
MAX_MARKET_CAP_USD = float(
    os.environ.get("MAX_MARKET_CAP_USD", "0")
)

COINGECKO_CATEGORIES = [
    x.strip()
    for x in os.environ.get("COINGECKO_CATEGORIES", "").split(",")
    if x.strip()
]


# =========================================================
# إعدادات المؤشرات والإشارات
# =========================================================

RSI_PERIOD = int(os.environ.get("RSI_PERIOD", "14"))
STOCH_PERIOD = int(os.environ.get("STOCH_PERIOD", "14"))
STOCH_K_SMOOTH = int(os.environ.get("STOCH_K_SMOOTH", "3"))
STOCH_D_SMOOTH = int(os.environ.get("STOCH_D_SMOOTH", "3"))
MAX_RSI_BUY = float(os.environ.get("MAX_RSI_BUY", "20"))

ENABLE_EARLY_ALERTS = (
    os.environ.get("ENABLE_EARLY_ALERTS", "true").lower() == "true"
)
ENABLE_CONFIRMED_SIGNALS = (
    os.environ.get("ENABLE_CONFIRMED_SIGNALS", "true").lower() == "true"
)
ALLOW_EARLY_STOCH = (
    os.environ.get("ALLOW_EARLY_STOCH", "true").lower() == "true"
)
MAX_STOCH_GAP = float(os.environ.get("MAX_STOCH_GAP", "8"))
REQUIRE_STOCH_RISING = (
    os.environ.get("REQUIRE_STOCH_RISING", "true").lower() == "true"
)

ALLOW_NEGATIVE_MACD = (
    os.environ.get("ALLOW_NEGATIVE_MACD", "true").lower() == "true"
)
REQUIRE_MACD_RISING = (
    os.environ.get("REQUIRE_MACD_RISING", "true").lower() == "true"
)
REQUIRE_CONFIRMED_MACD_POSITIVE = (
    os.environ.get(
        "REQUIRE_CONFIRMED_MACD_POSITIVE", "true"
    ).lower() == "true"
)

MIN_EARLY_CONFIDENCE = int(
    os.environ.get("MIN_EARLY_CONFIDENCE", "75")
)
MIN_CONFIRMED_CONFIDENCE = int(
    os.environ.get("MIN_CONFIRMED_CONFIDENCE", "90")
)

EARLY_ALERT_COOLDOWN_HOURS = float(
    os.environ.get("EARLY_ALERT_COOLDOWN_HOURS", "4")
)
CONFIRMED_SIGNAL_COOLDOWN_HOURS = float(
    os.environ.get("CONFIRMED_SIGNAL_COOLDOWN_HOURS", "12")
)

MAX_24H_CHANGE = float(os.environ.get("MAX_24H_CHANGE", "15"))
MIN_VOLUME_24H = float(
    os.environ.get("MIN_VOLUME_24H", "3000000")
)
MIN_CURRENT_CANDLE_VOLUME_USD = float(
    os.environ.get("MIN_CURRENT_CANDLE_VOLUME_USD", "200000")
)

REQUIRE_VOLUME_RATIO = (
    os.environ.get("REQUIRE_VOLUME_RATIO", "true").lower() == "true"
)
MIN_VOLUME_RATIO = float(
    os.environ.get("MIN_VOLUME_RATIO", "1.0")
)

TP1_PCT = float(os.environ.get("TP1_PCT", "2"))
TP2_PCT = float(os.environ.get("TP2_PCT", "4"))
TP3_PCT = float(os.environ.get("TP3_PCT", "7"))
TP4_PCT = float(os.environ.get("TP4_PCT", "10"))
TP5_PCT = float(os.environ.get("TP5_PCT", "15"))
STOP_LOSS_PCT = float(os.environ.get("STOP_LOSS_PCT", "3.5"))


# =========================================================
# تحويل الفريم حسب كل منصة
# =========================================================

TIMEFRAME_ALIASES = {
    "1m": "1m",
    "3m": "3m",
    "5m": "5m",
    "15m": "15m",
    "30m": "30m",
    "45m": "45m",
    "1h": "1h",
    "2h": "2h",
    "3h": "3h",
    "4h": "4h",
    "6h": "6h",
    "8h": "8h",
    "12h": "12h",
    "1d": "1d",
    "1w": "1w",
}

GATE_TIMEFRAMES = {
    "1m": "1m", "5m": "5m", "15m": "15m", "30m": "30m",
    "1h": "1h", "2h": "2h", "4h": "4h", "8h": "8h",
    "1d": "1d", "1w": "7d",
}

KUCOIN_TIMEFRAMES = {
    "1m": "1min", "3m": "3min", "5m": "5min", "15m": "15min",
    "30m": "30min", "1h": "1hour", "2h": "2hour", "4h": "4hour",
    "6h": "6hour", "8h": "8hour", "12h": "12hour",
    "1d": "1day", "1w": "1week",
}

MEXC_TIMEFRAMES = {
    "1m": "1m", "5m": "5m", "15m": "15m", "30m": "30m",
    "1h": "60m", "4h": "4h", "8h": "8h", "1d": "1d", "1w": "1W",
}

OKX_TIMEFRAMES = {
    "1m": "1m", "3m": "3m", "5m": "5m", "15m": "15m",
    "30m": "30m", "1h": "1H", "2h": "2H", "4h": "4H",
    "6h": "6H", "12h": "12H", "1d": "1D", "1w": "1W",
}


def normalize_exchange_name(name: str) -> str:
    aliases = {
        "gate": "gateio",
        "gate.io": "gateio",
        "gateio": "gateio",
        "kucoin": "kucoin",
        "mexc": "mexc",
        "okx": "okx",
    }
    return aliases.get(name.strip().lower(), name.strip().lower())


EXCHANGES = [normalize_exchange_name(item) for item in EXCHANGES]
EXCHANGE_PRIORITY = [
    normalize_exchange_name(item)
    for item in EXCHANGE_PRIORITY
    if normalize_exchange_name(item) in EXCHANGES
]

if not EXCHANGES:
    raise ValueError("EXCHANGES فارغ. أضف منصة واحدة على الأقل.")

if TIMEFRAME not in TIMEFRAME_ALIASES:
    raise ValueError(
        f"TIMEFRAME غير مدعوم: {TIMEFRAME}. "
        f"الفريمات العامة المتاحة: {', '.join(TIMEFRAME_ALIASES)}"
    )


def exchange_timeframe(exchange: str) -> Optional[str]:
    maps = {
        "gateio": GATE_TIMEFRAMES,
        "kucoin": KUCOIN_TIMEFRAMES,
        "mexc": MEXC_TIMEFRAMES,
        "okx": OKX_TIMEFRAMES,
    }
    return maps.get(exchange, {}).get(TIMEFRAME)


# =========================================================
# روابط المنصات
# =========================================================

KUCOIN_KLINE_URL = "https://api.kucoin.com/api/v1/market/candles"
MEXC_KLINE_URL = "https://api.mexc.com/api/v3/klines"
OKX_KLINE_URL = "https://www.okx.com/api/v5/market/candles"
GATE_KLINE_URL = "https://api.gateio.ws/api/v4/spot/candlesticks"

GATE_TICKERS_URL = "https://api.gateio.ws/api/v4/spot/tickers"
KUCOIN_TICKERS_URL = "https://api.kucoin.com/api/v1/market/allTickers"
MEXC_TICKERS_URL = "https://api.mexc.com/api/v3/ticker/24hr"
OKX_TICKERS_URL = "https://www.okx.com/api/v5/market/tickers"


# =========================================================
# قوائم الاستبعاد
# =========================================================

STABLECOINS = {
    "USDT", "USDC", "BUSD", "DAI", "TUSD", "FRAX", "USDP", "GUSD",
    "USDD", "FDUSD", "UST", "PYUSD", "USDE", "USD0", "USDX",
    "USDY", "SUSD", "LUSD", "EUSD", "CRVUSD", "MIM", "RLUSD",
    "EURC", "EURT",
}

MEME = {
    "DOGE", "SHIB", "PEPE", "FLOKI", "BONK", "WIF", "MEME",
    "BABYDOGE", "DOGS", "NEIRO", "POPCAT", "MOG", "TURBO",
    "BRETT", "TOSHI", "LADYS", "SATS", "RATS", "ELON", "KISHU",
    "AKITA", "HOGE", "SAMO", "CAT", "MONKEY", "CORG", "WOOF",
    "PITBULL", "MOON", "SAFEMOON", "TRUMP",
}

GAMING = {
    "AXS", "SLP", "RON", "SAND", "MANA", "ENJ", "CHZ", "GALA",
    "ILV", "YGG", "MBOX", "GMT", "MAGIC", "IMX", "PIXEL",
    "PORTAL", "BEAM", "XAI",
}

GAMBLING = {"DICE", "FUN", "BET", "LOTTO", "JACK", "SPIN", "SLOT"}
PREDICTION = {
    "POLY", "POLYX", "OMEN", "AUG", "REP", "GNO", "FORE", "OVL", "SX"
}
PRIVACY = {"ZEC", "DASH"}

BLACKLIST = (
    STABLECOINS | MEME | GAMING | GAMBLING | PREDICTION | PRIVACY
)


# =========================================================
# أدوات مساعدة
# =========================================================

SESSION = requests.Session()
SESSION.headers.update({"User-Agent": "CryptoSignalsBot/1.0"})


def safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def valid_usdt_symbol(symbol: str) -> bool:
    symbol = (symbol or "").upper().strip()
    return bool(symbol) and symbol not in BLACKLIST


def request_json(
    url: str,
    *,
    params: Optional[dict] = None,
    headers: Optional[dict] = None,
    timeout: Optional[int] = None,
) -> Any:
    last_error: Optional[Exception] = None

    for attempt in range(1, REQUEST_RETRIES + 1):
        try:
            response = SESSION.get(
                url,
                params=params,
                headers=headers,
                timeout=timeout or REQUEST_TIMEOUT,
            )

            if response.status_code == 429:
                retry_after = safe_float(
                    response.headers.get("Retry-After"), 5.0
                )
                wait_time = max(
                    retry_after,
                    REQUEST_RETRY_DELAY * attempt,
                )
                logging.warning(
                    "Rate limit 429، انتظار %.1f ثانية",
                    wait_time,
                )
                time.sleep(wait_time)
                continue

            response.raise_for_status()
            return response.json()

        except Exception as exc:
            last_error = exc
            if attempt < REQUEST_RETRIES:
                time.sleep(REQUEST_RETRY_DELAY * attempt)

    raise RuntimeError(
        f"Request failed after {REQUEST_RETRIES} attempts: {last_error}"
    )


def fp(price: Optional[float]) -> str:
    if price is None:
        return "-"
    if price < 0.0001:
        return f"{price:.8f}"
    if price < 0.01:
        return f"{price:.6f}"
    if price < 1:
        return f"{price:.4f}"
    if price < 100:
        return f"{price:.3f}"
    return f"{price:,.2f}"


def format_big_number(num: Optional[float]) -> str:
    num = safe_float(num)
    if num >= 1_000_000_000:
        return f"{num / 1_000_000_000:.2f}B"
    if num >= 1_000_000:
        return f"{num / 1_000_000:.2f}M"
    if num >= 1_000:
        return f"{num / 1_000:.2f}K"
    return f"{num:.0f}"


def load_json(path: str, default: Any) -> Any:
    try:
        if not os.path.exists(path):
            return default
        with open(path, "r", encoding="utf-8") as file:
            return json.load(file)
    except Exception as exc:
        logging.error("load_json %s: %s", path, exc)
        return default


def save_json(path: str, value: Any) -> None:
    try:
        temp_path = f"{path}.tmp"
        with open(temp_path, "w", encoding="utf-8") as file:
            json.dump(value, file, ensure_ascii=False, indent=2)
        os.replace(temp_path, path)
    except Exception as exc:
        logging.error("save_json %s: %s", path, exc)


# =========================================================
# حالة التنبيهات
# =========================================================

def alert_key(symbol: str, stage: str) -> str:
    return f"{symbol.upper()}:{stage.upper()}"


def alert_on_cooldown(symbol: str, stage: str) -> bool:
    state = load_json(ALERT_STATE_FILE, {})
    raw = state.get(alert_key(symbol, stage))

    if not raw:
        return False

    try:
        last_time = datetime.fromisoformat(raw)
        if last_time.tzinfo is None:
            last_time = SAUDI_TZ.localize(last_time)

        hours = (
            EARLY_ALERT_COOLDOWN_HOURS
            if stage.upper() == "EARLY"
            else CONFIRMED_SIGNAL_COOLDOWN_HOURS
        )

        elapsed = (
            datetime.now(SAUDI_TZ)
            - last_time.astimezone(SAUDI_TZ)
        ).total_seconds() / 3600

        return elapsed < hours
    except Exception:
        return False


def mark_alert_sent(symbol: str, stage: str) -> None:
    state = load_json(ALERT_STATE_FILE, {})
    state[alert_key(symbol, stage)] = (
        datetime.now(SAUDI_TZ).isoformat()
    )

    if len(state) > 5000:
        state = dict(
            sorted(
                state.items(),
                key=lambda item: item[1],
                reverse=True,
            )[:3000]
        )

    save_json(ALERT_STATE_FILE, state)


# =========================================================
# قاعدة البيانات والتاريخ
# =========================================================

def init_db() -> None:
    with sqlite3.connect(DB_FILE) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS signals (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                symbol TEXT,
                exchange TEXT,
                signal_time TEXT,
                entry_price REAL,
                confidence INTEGER,
                ai_score INTEGER,
                macd_strength TEXT,
                volume_spike INTEGER,
                stoch_k REAL,
                stoch_d REAL,
                change_4h REAL,
                change_24h REAL,
                change_7d REAL,
                target1 REAL,
                target2 REAL,
                target3 REAL,
                target4 REAL,
                target5 REAL,
                stop_loss REAL,
                status TEXT DEFAULT 'OPEN',
                result TEXT DEFAULT 'OPEN',
                result_pct REAL DEFAULT 0,
                close_time TEXT
            )
            """
        )


def db_save_signal(sig: dict) -> None:
    try:
        with sqlite3.connect(DB_FILE) as conn:
            conn.execute(
                """
                INSERT INTO signals (
                    symbol, exchange, signal_time, entry_price,
                    confidence, ai_score, macd_strength,
                    volume_spike, stoch_k, stoch_d,
                    change_4h, change_24h, change_7d,
                    target1, target2, target3, target4, target5,
                    stop_loss, status, result
                )
                VALUES (
                    ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                    ?, ?, ?, ?, ?, ?, 'OPEN', 'OPEN'
                )
                """,
                (
                    sig["symbol"],
                    sig.get("exchange"),
                    datetime.now(SAUDI_TZ).isoformat(),
                    sig["price"],
                    sig["confidence"],
                    sig.get("ai_score", sig["confidence"]),
                    sig.get("macd_strength"),
                    1 if sig.get("volume_spike") else 0,
                    sig.get("stoch_k"),
                    sig.get("stoch_d"),
                    sig.get("change_4h"),
                    sig.get("change_24h"),
                    sig.get("change_7d"),
                    sig.get("target1"),
                    sig.get("target2"),
                    sig.get("target3"),
                    sig.get("target4"),
                    sig.get("target5"),
                    sig.get("stop_loss"),
                ),
            )
    except Exception as exc:
        logging.error("db_save_signal: %s", exc)


def db_update_signal_result(
    symbol: str,
    result: str,
    result_pct: float,
) -> None:
    try:
        with sqlite3.connect(DB_FILE) as conn:
            row = conn.execute(
                """
                SELECT id
                FROM signals
                WHERE symbol = ? AND status = 'OPEN'
                ORDER BY id DESC
                LIMIT 1
                """,
                (symbol,),
            ).fetchone()

            if row:
                status = (
                    "CLOSED"
                    if result in ("TP5", "SL")
                    else "OPEN"
                )
                conn.execute(
                    """
                    UPDATE signals
                    SET result = ?,
                        result_pct = ?,
                        close_time = ?,
                        status = ?
                    WHERE id = ?
                    """,
                    (
                        result,
                        round(result_pct, 2),
                        datetime.now(SAUDI_TZ).isoformat(),
                        status,
                        row[0],
                    ),
                )
    except Exception as exc:
        logging.error("db_update_signal_result: %s", exc)


def db_get_today_winrate() -> dict:
    try:
        today_start = datetime.now(SAUDI_TZ).replace(
            hour=0,
            minute=0,
            second=0,
            microsecond=0,
        ).isoformat()

        with sqlite3.connect(DB_FILE) as conn:
            rows = conn.execute(
                """
                SELECT result, result_pct
                FROM signals
                WHERE result IN (
                    'TP1','TP2','TP3','TP4','TP5','SL'
                )
                AND signal_time >= ?
                """,
                (today_start,),
            ).fetchall()

        if not rows:
            return {
                "total": 0,
                "wins": 0,
                "losses": 0,
                "win_rate": 0.0,
                "avg_result": 0.0,
            }

        wins = [row for row in rows if row[0] != "SL"]
        losses = [row for row in rows if row[0] == "SL"]

        return {
            "total": len(rows),
            "wins": len(wins),
            "losses": len(losses),
            "win_rate": len(wins) / len(rows) * 100,
            "avg_result": (
                sum(safe_float(row[1]) for row in rows)
                / len(rows)
            ),
        }

    except Exception as exc:
        logging.error("db_get_today_winrate: %s", exc)
        return {
            "total": 0,
            "wins": 0,
            "losses": 0,
            "win_rate": 0.0,
            "avg_result": 0.0,
        }


def load_history() -> list:
    value = load_json(HISTORY_FILE, [])
    return value if isinstance(value, list) else []


def save_history(history: list) -> None:
    save_json(HISTORY_FILE, history[-500:])


def save_new_signal_to_history(sig: dict) -> None:
    history = load_history()

    history.append(
        {
            "symbol": sig["symbol"],
            "exchange": sig.get("exchange"),
            "time": datetime.now(SAUDI_TZ).isoformat(),
            "price": sig["price"],
            "confidence": sig["confidence"],
            "macd_strength": sig.get("macd_strength"),
            "volume_spike": sig.get("volume_spike"),
            "stoch_k": sig.get("stoch_k"),
            "stoch_d": sig.get("stoch_d"),
            "change_4h": sig.get("change_4h"),
            "change_24h": sig.get("change_24h"),
            "change_7d": sig.get("change_7d"),
            "current_volume_usd": sig.get(
                "current_volume_usd"
            ),
            "volume_ratio": sig.get("volume_ratio"),
            "result": "OPEN",
            "result_pct": 0,
        }
    )

    save_history(history)


def update_signal_result_in_history(
    symbol: str,
    result: str,
    result_pct: float,
) -> None:
    history = load_history()

    for item in reversed(history):
        if (
            item.get("symbol") == symbol
            and item.get("result") == "OPEN"
        ):
            item["result"] = result
            item["result_pct"] = round(result_pct, 2)
            item["closed_time"] = (
                datetime.now(SAUDI_TZ).isoformat()
            )
            break

    save_history(history)
    db_update_signal_result(symbol, result, result_pct)


# =========================================================
# التتبع اليومي
# =========================================================

class DailyTracker:
    def __init__(self) -> None:
        self.reset()

    def reset(self) -> None:
        self.date = date.today()
        self.buy_signals: List[dict] = []
        self.scans = 0
        self.coins_scanned = 0
        self.summary_sent = False
        self.daily_profit_pct = 0.0

    def add_signal(self, sig: dict) -> None:
        self.buy_signals.append(
            {
                "symbol": sig["symbol"],
                "exchange": sig.get(
                    "exchange", "غير معروف"
                ),
                "price": sig["price"],
                "confidence": sig["confidence"],
                "change_24h": sig["change_24h"],
                "stoch_k": sig.get("stoch_k"),
                "stoch_d": sig.get("stoch_d"),
                "macd_strength": sig.get(
                    "macd_strength"
                ),
                "time": datetime.now(
                    SAUDI_TZ
                ).strftime("%H:%M"),
                "target1": sig["target1"],
                "stop_loss": sig["stop_loss"],
            }
        )

    def new_day(self) -> bool:
        return date.today() > self.date

    @property
    def total_signals(self) -> int:
        return len(self.buy_signals)

    @property
    def top_buy(self) -> list:
        return sorted(
            self.buy_signals,
            key=lambda item: item["confidence"],
            reverse=True,
        )[:5]


tracker = DailyTracker()
active_signals: Dict[str, dict] = {}


# =========================================================
# CoinGecko
# =========================================================

def coingecko_headers() -> dict:
    headers = {"accept": "application/json"}

    if COINGECKO_API_KEY:
        headers[COINGECKO_API_HEADER] = (
            COINGECKO_API_KEY
        )

    return headers


def load_coingecko_cache() -> Optional[list]:
    cache = load_json(COINGECKO_CACHE_FILE, {})

    if not isinstance(cache, dict):
        return None

    updated_at = cache.get("updated_at")
    coins = cache.get("coins")

    if not updated_at or not isinstance(coins, list):
        return None

    try:
        timestamp = datetime.fromisoformat(updated_at)

        if timestamp.tzinfo is None:
            timestamp = SAUDI_TZ.localize(timestamp)

        age_hours = (
            datetime.now(SAUDI_TZ)
            - timestamp.astimezone(SAUDI_TZ)
        ).total_seconds() / 3600

        if age_hours < COINGECKO_REFRESH_HOURS:
            return coins

    except Exception:
        return None

    return None


def save_coingecko_cache(coins: list) -> None:
    save_json(
        COINGECKO_CACHE_FILE,
        {
            "updated_at": datetime.now(
                SAUDI_TZ
            ).isoformat(),
            "coins": coins,
        },
    )


def get_coingecko_universe(
    force_refresh: bool = False,
) -> list:
    if not force_refresh:
        cached = load_coingecko_cache()

        if cached is not None:
            print(
                f"🦎 CoinGecko cache: {len(cached)} عملة"
            )
            return cached[:COINGECKO_MAX_COINS]

    categories = COINGECKO_CATEGORIES or [None]
    collected: Dict[str, dict] = {}

    pages_needed = math.ceil(
        COINGECKO_MAX_COINS / COINGECKO_PER_PAGE
    )

    for category in categories:
        for page in range(1, pages_needed + 1):
            params = {
                "vs_currency": "usd",
                "order": COINGECKO_ORDER,
                "per_page": COINGECKO_PER_PAGE,
                "page": page,
                "sparkline": "false",
                "price_change_percentage": "1h,24h,7d",
                "locale": "en",
                "precision": "full",
            }

            if category:
                params["category"] = category

            try:
                rows = request_json(
                    COINGECKO_MARKETS_URL,
                    params=params,
                    headers=coingecko_headers(),
                    timeout=30,
                )

            except Exception as exc:
                logging.error(
                    "CoinGecko category=%s page=%s: %s",
                    category or "all",
                    page,
                    exc,
                )
                break

            if not isinstance(rows, list) or not rows:
                break

            for item in rows:
                symbol = str(
                    item.get("symbol", "")
                ).upper().strip()

                if not valid_usdt_symbol(symbol):
                    continue

                current_price = safe_float(
                    item.get("current_price")
                )
                market_cap = safe_float(
                    item.get("market_cap")
                )
                total_volume = safe_float(
                    item.get("total_volume")
                )

                if current_price <= 0:
                    continue

                if (
                    total_volume
                    < MIN_COINGECKO_VOLUME_24H
                ):
                    continue

                if (
                    MIN_MARKET_CAP_USD > 0
                    and market_cap < MIN_MARKET_CAP_USD
                ):
                    continue

                if (
                    MAX_MARKET_CAP_USD > 0
                    and market_cap > MAX_MARKET_CAP_USD
                ):
                    continue

                coin = {
                    "coingecko_id": item.get("id"),
                    "symbol": symbol,
                    "name": item.get("name") or symbol,
                    "market_cap": market_cap,
                    "volume_24h": total_volume,
                    "coingecko_price": current_price,
                    "change_1h": safe_float(
                        item.get(
                            "price_change_percentage_1h_in_currency"
                        )
                    ),
                    "change_24h": safe_float(
                        item.get(
                            "price_change_percentage_24h_in_currency"
                        )
                    ),
                    "change_7d": safe_float(
                        item.get(
                            "price_change_percentage_7d_in_currency"
                        )
                    ),
                    "category": category,
                }

                previous = collected.get(symbol)

                if (
                    previous is None
                    or total_volume
                    > previous["volume_24h"]
                ):
                    collected[symbol] = coin

            print(
                f"🦎 CoinGecko {category or 'all'} "
                f"page {page}/{pages_needed} | "
                f"المقبول {len(collected)}"
            )

            if len(rows) < COINGECKO_PER_PAGE:
                break

            time.sleep(COINGECKO_PAGE_DELAY)

    coins = sorted(
        collected.values(),
        key=lambda item: item["volume_24h"],
        reverse=True,
    )[:COINGECKO_MAX_COINS]

    if coins:
        save_coingecko_cache(coins)
    else:
        stale = load_json(
            COINGECKO_CACHE_FILE, {}
        ).get("coins", [])

        if isinstance(stale, list) and stale:
            logging.warning(
                "فشل CoinGecko، سيتم استخدام الكاش القديم"
            )
            return stale[:COINGECKO_MAX_COINS]

    print(
        f"🦎 CoinGecko universe: {len(coins)} عملة"
    )
    return coins


# =========================================================
# أسواق المنصات
# =========================================================

def get_gate_markets() -> list:
    try:
        rows = request_json(GATE_TICKERS_URL)
        markets = []

        for item in rows:
            pair = item.get("currency_pair", "")

            if not pair.endswith("_USDT"):
                continue

            symbol = pair[:-5].upper()

            if not valid_usdt_symbol(symbol):
                continue

            last = safe_float(item.get("last"))
            volume_24h = safe_float(
                item.get("quote_volume")
            )
            change_24h = safe_float(
                item.get("change_percentage")
            )

            if last <= 0 or volume_24h <= 0:
                continue

            markets.append(
                {
                    "symbol": symbol,
                    "exchange": "Gate.io",
                    "price": last,
                    "exchange_volume_24h": volume_24h,
                    "exchange_change_24h": change_24h,
                }
            )

        return markets

    except Exception as exc:
        logging.error("Gate tickers: %s", exc)
        return []


def get_kucoin_markets() -> list:
    try:
        payload = request_json(KUCOIN_TICKERS_URL)
        rows = payload.get(
            "data", {}
        ).get("ticker", [])
        markets = []

        for item in rows:
            pair = item.get("symbol", "")

            if not pair.endswith("-USDT"):
                continue

            symbol = pair[:-5].upper()

            if not valid_usdt_symbol(symbol):
                continue

            last = safe_float(item.get("last"))
            volume_24h = safe_float(
                item.get("volValue")
            )
            change_24h = (
                safe_float(item.get("changeRate")) * 100
            )

            if last <= 0 or volume_24h <= 0:
                continue

            markets.append(
                {
                    "symbol": symbol,
                    "exchange": "KuCoin",
                    "price": last,
                    "exchange_volume_24h": volume_24h,
                    "exchange_change_24h": change_24h,
                }
            )

        return markets

    except Exception as exc:
        logging.error("KuCoin tickers: %s", exc)
        return []


def get_mexc_markets() -> list:
    try:
        rows = request_json(MEXC_TICKERS_URL)
        markets = []

        for item in rows:
            pair = item.get("symbol", "")

            if (
                not pair.endswith("USDT")
                or len(pair) <= 4
            ):
                continue

            symbol = pair[:-4].upper()

            if not valid_usdt_symbol(symbol):
                continue

            last = safe_float(item.get("lastPrice"))
            volume_24h = safe_float(
                item.get("quoteVolume")
            )
            change_24h = safe_float(
                item.get("priceChangePercent")
            )

            if last <= 0 or volume_24h <= 0:
                continue

            markets.append(
                {
                    "symbol": symbol,
                    "exchange": "MEXC",
                    "price": last,
                    "exchange_volume_24h": volume_24h,
                    "exchange_change_24h": change_24h,
                }
            )

        return markets

    except Exception as exc:
        logging.error("MEXC tickers: %s", exc)
        return []


def get_okx_markets() -> list:
    try:
        payload = request_json(
            OKX_TICKERS_URL,
            params={"instType": "SPOT"},
        )
        markets = []

        for item in payload.get("data", []):
            pair = item.get("instId", "")

            if not pair.endswith("-USDT"):
                continue

            symbol = pair[:-5].upper()

            if not valid_usdt_symbol(symbol):
                continue

            last = safe_float(item.get("last"))
            open_24h = safe_float(
                item.get("open24h")
            )
            volume_24h = safe_float(
                item.get("volCcy24h")
            )
            change_24h = (
                (last - open_24h) / open_24h * 100
                if open_24h > 0
                else 0.0
            )

            if last <= 0 or volume_24h <= 0:
                continue

            markets.append(
                {
                    "symbol": symbol,
                    "exchange": "OKX",
                    "price": last,
                    "exchange_volume_24h": volume_24h,
                    "exchange_change_24h": change_24h,
                }
            )

        return markets

    except Exception as exc:
        logging.error("OKX tickers: %s", exc)
        return []


def build_exchange_symbol_maps() -> Dict[str, Dict[str, dict]]:
    loaders = {
        "gateio": ("Gate.io", get_gate_markets),
        "kucoin": ("KuCoin", get_kucoin_markets),
        "mexc": ("MEXC", get_mexc_markets),
        "okx": ("OKX", get_okx_markets),
    }

    sources = {}

    for exchange_key in EXCHANGES:
        if exchange_timeframe(exchange_key) is None:
            logging.warning(
                "سيتم تجاهل %s لأن الفريم %s غير مدعوم عليها",
                exchange_key,
                TIMEFRAME,
            )
            continue

        display_name, loader = loaders[exchange_key]
        sources[display_name] = loader()

    maps: Dict[str, Dict[str, dict]] = {}

    for exchange, rows in sources.items():
        exchange_map: Dict[str, dict] = {}

        for row in rows:
            symbol = row["symbol"]
            previous = exchange_map.get(symbol)

            if (
                previous is None
                or row["exchange_volume_24h"]
                > previous["exchange_volume_24h"]
            ):
                exchange_map[symbol] = row

        maps[exchange] = exchange_map

    print(
        "📥 المنصات | "
        + " | ".join(
            f"{name}: {len(rows)}"
            for name, rows in maps.items()
        )
    )

    return maps


def get_markets_from_coingecko_and_exchanges() -> list:
    coingecko_coins = get_coingecko_universe()
    exchange_maps = build_exchange_symbol_maps()

    matched = []
    unmatched = 0

    for cg_coin in coingecko_coins:
        symbol = cg_coin["symbol"]
        available = []

        for exchange_map in exchange_maps.values():
            row = exchange_map.get(symbol)

            if row:
                available.append(row)

        if not available:
            unmatched += 1
            continue

        if EXCHANGE_SELECTION_MODE == "priority":
            priority_display = {
                "gateio": "Gate.io",
                "kucoin": "KuCoin",
                "mexc": "MEXC",
                "okx": "OKX",
            }
            selected = None

            for exchange_key in EXCHANGE_PRIORITY:
                display_name = priority_display.get(exchange_key)
                selected = next(
                    (
                        row
                        for row in available
                        if row.get("exchange") == display_name
                    ),
                    None,
                )
                if selected:
                    break

            if selected is None:
                selected = max(
                    available,
                    key=lambda row: row.get(
                        "exchange_volume_24h", 0
                    ),
                )
        else:
            selected = max(
                available,
                key=lambda row: row.get(
                    "exchange_volume_24h", 0
                ),
            )

        matched.append(
            {
                **cg_coin,
                "exchange": selected["exchange"],
                "price": selected["price"],
                "exchange_volume_24h": selected[
                    "exchange_volume_24h"
                ],
                "exchange_change_24h": selected[
                    "exchange_change_24h"
                ],
            }
        )

    matched.sort(
        key=lambda item: item.get(
            "exchange_volume_24h", 0
        ),
        reverse=True,
    )

    matched = matched[:MAX_MARKETS]

    print(
        f"🔗 العملات المطابقة: {len(matched)} | "
        f"غير المطابقة: {unmatched}"
    )

    return matched


# =========================================================
# شموع المنصات
# =========================================================

def get_gate_market_data(
    symbol: str,
) -> Optional[dict]:
    try:
        rows = request_json(
            GATE_KLINE_URL,
            params={
                "currency_pair": f"{symbol}_USDT",
                "interval": exchange_timeframe("gateio"),
                "limit": CANDLE_LIMIT,
            },
            timeout=15,
        )

        if not isinstance(rows, list) or not rows:
            return None

        rows = sorted(
            rows,
            key=lambda row: int(row[0]),
        )

        closes = [
            safe_float(row[2])
            for row in rows
        ]
        quote_volumes = [
            safe_float(row[1])
            for row in rows
        ]
        base_volumes = [
            quote / close if close > 0 else 0
            for quote, close in zip(
                quote_volumes, closes
            )
        ]

        return {
            "closes": closes,
            "base_volumes": base_volumes,
            "quote_volumes": quote_volumes,
        }

    except Exception as exc:
        logging.info(
            "Gate candles %s: %s",
            symbol,
            exc,
        )
        return None


def get_kucoin_market_data(
    symbol: str,
) -> Optional[dict]:
    try:
        payload = request_json(
            KUCOIN_KLINE_URL,
            params={
                "symbol": f"{symbol}-USDT",
                "type": exchange_timeframe("kucoin"),
            },
            timeout=15,
        )

        if payload.get("code") != "200000":
            return None

        rows = payload.get("data", [])

        if not rows:
            return None

        rows = list(reversed(rows))[:CANDLE_LIMIT]

        closes = [
            safe_float(row[2])
            for row in rows
        ]
        base_volumes = [
            safe_float(row[5])
            for row in rows
        ]
        quote_volumes = [
            safe_float(row[6])
            for row in rows
        ]

        return {
            "closes": closes,
            "base_volumes": base_volumes,
            "quote_volumes": quote_volumes,
        }

    except Exception as exc:
        logging.info(
            "KuCoin candles %s: %s",
            symbol,
            exc,
        )
        return None


def get_mexc_market_data(
    symbol: str,
) -> Optional[dict]:
    try:
        rows = request_json(
            MEXC_KLINE_URL,
            params={
                "symbol": f"{symbol}USDT",
                "interval": exchange_timeframe("gateio"),
                "limit": CANDLE_LIMIT,
            },
            timeout=15,
        )

        if not isinstance(rows, list) or not rows:
            return None

        closes = [
            safe_float(row[4])
            for row in rows
        ]
        base_volumes = [
            safe_float(row[5])
            for row in rows
        ]
        quote_volumes = [
            (
                safe_float(row[7])
                if len(row) > 7
                else base * close
            )
            for row, base, close in zip(
                rows,
                base_volumes,
                closes,
            )
        ]

        return {
            "closes": closes,
            "base_volumes": base_volumes,
            "quote_volumes": quote_volumes,
        }

    except Exception as exc:
        logging.info(
            "MEXC candles %s: %s",
            symbol,
            exc,
        )
        return None


def get_okx_market_data(
    symbol: str,
) -> Optional[dict]:
    try:
        payload = request_json(
            OKX_KLINE_URL,
            params={
                "instId": f"{symbol}-USDT",
                "bar": exchange_timeframe("okx"),
                "limit": str(CANDLE_LIMIT),
            },
            timeout=15,
        )

        if payload.get("code") != "0":
            return None

        rows = payload.get("data", [])

        if not rows:
            return None

        rows = list(reversed(rows))

        closes = [
            safe_float(row[4])
            for row in rows
        ]
        base_volumes = [
            safe_float(row[5])
            for row in rows
        ]
        quote_volumes = [
            (
                safe_float(row[7])
                if len(row) > 7
                else base * close
            )
            for row, base, close in zip(
                rows,
                base_volumes,
                closes,
            )
        ]

        return {
            "closes": closes,
            "base_volumes": base_volumes,
            "quote_volumes": quote_volumes,
        }

    except Exception as exc:
        logging.info(
            "OKX candles %s: %s",
            symbol,
            exc,
        )
        return None


def get_market_data_for_exchange(
    symbol: str,
    exchange: str,
) -> Optional[dict]:
    exchange_key = {
        "Gate.io": "gateio",
        "KuCoin": "kucoin",
        "MEXC": "mexc",
        "OKX": "okx",
    }.get(exchange)

    if not exchange_key or exchange_timeframe(exchange_key) is None:
        return None

    if exchange == "Gate.io":
        return get_gate_market_data(symbol)

    if exchange == "KuCoin":
        return get_kucoin_market_data(symbol)

    if exchange == "MEXC":
        return get_mexc_market_data(symbol)

    if exchange == "OKX":
        return get_okx_market_data(symbol)

    return None


# =========================================================
# المؤشرات
# =========================================================

def calculate_stoch_rsi(
    closes: list,
    rsi_period: int = 14,
    stoch_period: int = 14,
    smooth_k: int = 3,
    smooth_d: int = 3,
) -> Optional[dict]:
    min_len = (
        rsi_period
        + stoch_period
        + smooth_k
        + smooth_d
        + 10
    )

    if len(closes) < min_len:
        return None

    gains = []
    losses = []

    for index in range(1, len(closes)):
        diff = closes[index] - closes[index - 1]
        gains.append(max(diff, 0))
        losses.append(max(-diff, 0))

    avg_gain = (
        sum(gains[:rsi_period]) / rsi_period
    )
    avg_loss = (
        sum(losses[:rsi_period]) / rsi_period
    )

    rsi_values = []

    for index in range(
        rsi_period,
        len(gains),
    ):
        avg_gain = (
            avg_gain * (rsi_period - 1)
            + gains[index]
        ) / rsi_period

        avg_loss = (
            avg_loss * (rsi_period - 1)
            + losses[index]
        ) / rsi_period

        if avg_loss == 0:
            rsi_values.append(100.0)
        else:
            rs = avg_gain / avg_loss
            rsi_values.append(
                100 - 100 / (1 + rs)
            )

    raw_k = []

    for index in range(
        stoch_period - 1,
        len(rsi_values),
    ):
        window = rsi_values[
            index - stoch_period + 1:index + 1
        ]
        low = min(window)
        high = max(window)

        if high == low:
            raw_k.append(50.0)
        else:
            raw_k.append(
                (
                    rsi_values[index] - low
                )
                / (high - low)
                * 100
            )

    if len(raw_k) < smooth_k:
        return None

    k_values = [
        sum(
            raw_k[
                index - smooth_k + 1:index + 1
            ]
        ) / smooth_k
        for index in range(
            smooth_k - 1,
            len(raw_k),
        )
    ]

    if len(k_values) < smooth_d:
        return None

    d_values = [
        sum(
            k_values[
                index - smooth_d + 1:index + 1
            ]
        ) / smooth_d
        for index in range(
            smooth_d - 1,
            len(k_values),
        )
    ]

    return {
        "k": round(k_values[-1], 2),
        "d": round(d_values[-1], 2),
        "k_prev": round(k_values[-2], 2),
        "d_prev": round(d_values[-2], 2),
    }


def ema_series(
    data: list,
    period: int,
) -> list:
    if len(data) < period:
        return []

    multiplier = 2 / (period + 1)
    value = sum(data[:period]) / period
    series = [value]

    for point in data[period:]:
        value = (
            point * multiplier
            + value * (1 - multiplier)
        )
        series.append(value)

    return series


def calculate_macd(
    prices: list,
) -> Optional[dict]:
    if len(prices) < 40:
        return None

    ema12 = ema_series(prices, 12)
    ema26 = ema_series(prices, 26)

    if not ema12 or not ema26:
        return None

    offset = len(ema12) - len(ema26)

    macd_series = [
        ema12[index + offset] - ema26[index]
        for index in range(len(ema26))
    ]

    signal_series = ema_series(
        macd_series, 9
    )

    if len(signal_series) < 2:
        return None

    macd_now = macd_series[-1]
    macd_prev = macd_series[-2]
    signal_now = signal_series[-1]
    signal_prev = signal_series[-2]

    histogram = macd_now - signal_now
    histogram_prev = (
        macd_prev - signal_prev
    )

    if histogram >= 0:
        color = (
            "rising_green"
            if histogram > histogram_prev
            else "falling_green"
        )
    else:
        color = (
            "rising_red"
            if histogram > histogram_prev
            else "falling_red"
        )

    return {
        "macd": round(macd_now, 10),
        "signal": round(signal_now, 10),
        "histogram": round(histogram, 10),
        "histogram_prev": round(
            histogram_prev, 10
        ),
        "direction": (
            "rising"
            if histogram > histogram_prev
            else "falling"
        ),
        "color": color,
        "switched_to_falling": (
            histogram_prev >= 0
            and histogram < 0
        ),
        "switched_to_rising": (
            histogram_prev <= 0
            and histogram > 0
        ),
    }


def detect_volume_spike(
    market_data: dict,
) -> dict:
    closes = market_data.get("closes", [])
    quote_volumes = market_data.get(
        "quote_volumes", []
    )
    base_volumes = market_data.get(
        "base_volumes", []
    )

    if len(closes) < 2:
        return {
            "spike": False,
            "ratio": 0.0,
            "current_volume_usd": 0.0,
            "previous_volume_usd": 0.0,
            "enough_data": False,
        }

    if len(quote_volumes) >= 2:
        current_usd = safe_float(
            quote_volumes[-1]
        )
        previous_usd = safe_float(
            quote_volumes[-2]
        )

    elif len(base_volumes) >= 2:
        current_usd = (
            safe_float(base_volumes[-1])
            * safe_float(closes[-1])
        )
        previous_usd = (
            safe_float(base_volumes[-2])
            * safe_float(closes[-2])
        )

    else:
        return {
            "spike": False,
            "ratio": 0.0,
            "current_volume_usd": 0.0,
            "previous_volume_usd": 0.0,
            "enough_data": False,
        }

    ratio = (
        current_usd / previous_usd
        if previous_usd > 0
        else 0.0
    )

    return {
        "spike": ratio >= MIN_VOLUME_RATIO,
        "ratio": round(ratio, 2),
        "current_volume_usd": current_usd,
        "previous_volume_usd": previous_usd,
        "enough_data": True,
    }


def classify_macd_histogram(
    histogram: float,
    price: float,
    direction: str,
) -> dict:
    if price <= 0:
        return {
            "label": "غير متوفر",
            "emoji": "⚪",
            "score": 0,
            "ratio": 0,
        }

    ratio = histogram / price

    if histogram <= 0:
        return {
            "label": "سلبي",
            "emoji": "🔴",
            "score": -2,
            "ratio": ratio,
        }

    if direction == "falling":
        return {
            "label": "ضعيف متراجع",
            "emoji": "⚠️",
            "score": 0,
            "ratio": ratio,
        }

    if ratio >= 0.001:
        return {
            "label": "قوي جدًا",
            "emoji": "🔥",
            "score": 4,
            "ratio": ratio,
        }

    if ratio >= 0.0005:
        return {
            "label": "قوي",
            "emoji": "🟢",
            "score": 3,
            "ratio": ratio,
        }

    if ratio >= 0.00015:
        return {
            "label": "متوسط",
            "emoji": "🟡",
            "score": 2,
            "ratio": ratio,
        }

    return {
        "label": "ضعيف",
        "emoji": "⚠️",
        "score": 1,
        "ratio": ratio,
    }


# =========================================================
# التعلم البسيط وإدارة المخاطر
# =========================================================

def get_learning_adjustment(
    sig: dict,
) -> dict:
    closed = [
        item
        for item in load_history()
        if item.get("result")
        in (
            "TP1",
            "TP2",
            "TP3",
            "TP4",
            "TP5",
            "SL",
        )
    ]

    if len(closed) < 10:
        return {
            "adjustment": 0,
            "note": "لا توجد بيانات تعلم كافية بعد",
        }

    similar = [
        item
        for item in closed
        if (
            item.get("macd_strength")
            == sig.get("macd_strength")
            and item.get("volume_spike")
            == sig.get("volume_spike")
        )
    ]

    if len(similar) < 5:
        return {
            "adjustment": 0,
            "note": (
                "بيانات التعلم للحالة "
                "المشابهة غير كافية"
            ),
        }

    recent = similar[-30:]

    wins = [
        item
        for item in recent
        if item.get("result")
        in (
            "TP1",
            "TP2",
            "TP3",
            "TP4",
            "TP5",
        )
    ]

    win_rate = len(wins) / len(recent)

    if win_rate >= 0.70:
        return {
            "adjustment": 8,
            "note": (
                f"هذا النمط ناجح سابقًا "
                f"بنسبة {win_rate * 100:.0f}% 🔥"
            ),
        }

    if win_rate >= 0.60:
        return {
            "adjustment": 5,
            "note": (
                f"هذا النمط جيد سابقًا "
                f"بنسبة {win_rate * 100:.0f}% ✅"
            ),
        }

    if win_rate <= 0.35:
        return {
            "adjustment": -10,
            "note": (
                f"هذا النمط ضعيف سابقًا "
                f"بنسبة نجاح {win_rate * 100:.0f}% ⚠️"
            ),
        }

    if win_rate <= 0.45:
        return {
            "adjustment": -5,
            "note": (
                f"هذا النمط متوسط/ضعيف "
                f"بنسبة نجاح {win_rate * 100:.0f}%"
            ),
        }

    return {
        "adjustment": 0,
        "note": (
            f"أداء النمط متوازن "
            f"بنسبة نجاح {win_rate * 100:.0f}%"
        ),
    }


def calculate_ai_ranking_score(
    score: int,
    macd_strength: str,
    volume_spike: bool,
    learning_adjustment: int,
    change_4h: float,
    change_24h: float,
) -> int:
    ai_score = 50 + score * 4

    if macd_strength in (
        "قوي",
        "قوي جدًا",
    ):
        ai_score += 8

    elif macd_strength == "متوسط":
        ai_score += 4

    elif macd_strength in (
        "ضعيف",
        "ضعيف متراجع",
    ):
        ai_score -= 8

    if volume_spike:
        ai_score += 8

    ai_score += learning_adjustment

    if change_4h > 4:
        ai_score -= 5

    if change_24h > 10:
        ai_score -= 8

    return int(
        max(0, min(ai_score, 100))
    )


def calculate_position_size(
    entry_price: float,
    stop_loss: float,
) -> dict:
    risk_amount = (
        ACCOUNT_BALANCE
        * (RISK_PER_TRADE_PCT / 100)
    )

    risk_per_unit = abs(
        entry_price - stop_loss
    )

    if risk_per_unit <= 0:
        return {
            "risk_amount": risk_amount,
            "position_usd": 0,
            "position_pct": 0,
            "quantity": 0,
        }

    quantity = risk_amount / risk_per_unit
    position_usd = quantity * entry_price

    position_pct = (
        position_usd
        / ACCOUNT_BALANCE
        * 100
        if ACCOUNT_BALANCE > 0
        else 0
    )

    return {
        "risk_amount": round(
            risk_amount, 2
        ),
        "position_usd": round(
            position_usd, 2
        ),
        "position_pct": round(
            position_pct, 1
        ),
        "quantity": round(
            quantity, 8
        ),
    }


# =========================================================
# تحليل الإشارة
# =========================================================

def analyze_signal(
    data: dict,
) -> Optional[dict]:
    price = data["price"]
    change_4h = data["change_4h"]
    change_24h = data["change_24h"]
    change_7d = data["change_7d"]
    volume_24h = data["volume_24h"]

    stoch = data.get("stoch")
    macd = data.get("macd")

    volume_spike = bool(
        data.get("volume_spike")
    )
    current_volume_usd = safe_float(
        data.get("current_volume_usd")
    )
    volume_ratio = safe_float(
        data.get("volume_ratio")
    )
    volume_enough_data = bool(
        data.get("volume_enough_data")
    )

    if stoch is None or macd is None:
        return None

    stoch_k = stoch["k"]
    stoch_d = stoch["d"]
    stoch_k_prev = stoch["k_prev"]
    stoch_d_prev = stoch["d_prev"]

    if (
        stoch_k >= MAX_RSI_BUY
        or stoch_d >= MAX_RSI_BUY
    ):
        return None

    if change_24h > MAX_24H_CHANGE:
        return None

    if volume_24h < MIN_VOLUME_24H:
        return None

    if (
        current_volume_usd
        < MIN_CURRENT_CANDLE_VOLUME_USD
    ):
        return None

    if REQUIRE_VOLUME_RATIO:
        if (
            not volume_enough_data
            or volume_ratio < MIN_VOLUME_RATIO
        ):
            return None

    score = 0
    reasons = []

    if stoch_k < 10 and stoch_d < 10:
        score += 4
        reasons.append(
            f"Stoch RSI K=`{stoch_k}` "
            f"D=`{stoch_d}` — "
            f"تشبع بيع قوي جدًا 🔥"
        )

    elif stoch_k < 15 and stoch_d < 15:
        score += 3
        reasons.append(
            f"Stoch RSI K=`{stoch_k}` "
            f"D=`{stoch_d}` — "
            f"تشبع بيع قوي"
        )

    else:
        score += 2
        reasons.append(
            f"Stoch RSI K=`{stoch_k}` "
            f"D=`{stoch_d}` — "
            f"تشبع بيع"
        )

    stoch_crossed = stoch_k > stoch_d
    stoch_turning_up = (
        stoch_k > stoch_k_prev
    )
    stoch_gap = max(
        stoch_d - stoch_k, 0
    )

    early_stoch = (
        ENABLE_EARLY_ALERTS
        and ALLOW_EARLY_STOCH
        and not stoch_crossed
        and (
            stoch_turning_up
            or not REQUIRE_STOCH_RISING
        )
        and stoch_gap <= MAX_STOCH_GAP
    )

    if (
        not stoch_crossed
        and not early_stoch
    ):
        return None

    if stoch_crossed:
        score += 2
        reasons.append(
            "Stoch RSI: K أعلى من D "
            "— تقاطع شراء 📈"
        )
    else:
        score += 1
        reasons.append(
            f"Stoch RSI ينعكس قبل التقاطع "
            f"— الفارق `{stoch_gap:.2f}`"
        )

    histogram = macd["histogram"]
    histogram_prev = macd[
        "histogram_prev"
    ]
    direction = macd["direction"]

    macd_strength = (
        classify_macd_histogram(
            histogram,
            price,
            direction,
        )
    )

    macd_improving = (
        histogram > histogram_prev
    )

    if (
        REQUIRE_MACD_RISING
        and not macd_improving
    ):
        return None

    if (
        histogram < 0
        and not ALLOW_NEGATIVE_MACD
    ):
        return None

    if histogram > 0:
        score += max(
            macd_strength["score"], 1
        )
        reasons.append(
            "MACD Histogram إيجابي ومتحسن "
            f"— {macd_strength['label']} "
            f"{macd_strength['emoji']}"
        )

        if macd.get(
            "switched_to_rising"
        ):
            score += 1
            reasons.append(
                "MACD تحول من السالب "
                "إلى الموجب للتو 🚀"
            )

    else:
        score += 1
        reasons.append(
            f"MACD سلبي لكنه يتحسن: "
            f"`{histogram_prev}` → "
            f"`{histogram}`"
        )

    confirmed_ready = (
        stoch_crossed
        and (
            histogram > 0
            or not REQUIRE_CONFIRMED_MACD_POSITIVE
        )
    )

    stage = (
        "CONFIRMED"
        if confirmed_ready
        else "EARLY"
    )

    if (
        stage == "EARLY"
        and not ENABLE_EARLY_ALERTS
    ):
        return None

    if (
        stage == "CONFIRMED"
        and not ENABLE_CONFIRMED_SIGNALS
    ):
        return None

    if volume_spike:
        score += 2
        reasons.append(
            f"فوليوم الشمعة أعلى "
            f"من السابقة `{volume_ratio:.2f}x` 🔥"
        )
    else:
        reasons.append(
            f"معدل الفوليوم مستوفٍ "
            f"للحد `{volume_ratio:.2f}x`"
        )

    if -1.5 <= change_4h <= 2:
        score += 1
        reasons.append(
            f"حركة شمعة {TIMEFRAME.upper()} غير متضخمة"
        )

    elif change_4h < -2:
        score += 1
        reasons.append(
            f"هبوط شمعة {TIMEFRAME.upper()} قد يسبق ارتدادًا"
        )

    if -10 <= change_24h <= 4:
        score += 2
        reasons.append(
            "الحركة اليومية مناسبة "
            "للدخول المبكر"
        )

    elif 4 < change_24h <= 8:
        score += 1
        reasons.append(
            "ارتفاع يومي متوسط"
        )

    elif change_24h < -15:
        score -= 1
        reasons.append(
            "هبوط يومي قوي يحتاج حذر"
        )

    if -25 <= change_7d <= 18:
        score += 1
        reasons.append(
            "الاتجاه الأسبوعي غير متضخم"
        )

    elif change_7d > 30:
        score -= 2
        reasons.append(
            "صعود أسبوعي متضخم"
        )

    if score < 3:
        return None

    confidence = min(
        50 + score * 5,
        90,
    )

    if stage == "EARLY":
        confidence = min(
            confidence, 82
        )

    if not volume_spike:
        confidence = min(
            confidence, 78
        )

    if (
        volume_spike
        and histogram > 0
    ):
        confidence = min(
            confidence + 5,
            95,
        )

    learning = get_learning_adjustment(
        {
            "macd_strength": macd_strength[
                "label"
            ],
            "volume_spike": volume_spike,
        }
    )

    confidence += learning["adjustment"]
    confidence = max(
        45,
        min(confidence, 95),
    )

    ai_score = calculate_ai_ranking_score(
        score=score,
        macd_strength=macd_strength[
            "label"
        ],
        volume_spike=volume_spike,
        learning_adjustment=learning[
            "adjustment"
        ],
        change_4h=change_4h,
        change_24h=change_24h,
    )

    confidence = int(
        round(
            confidence * 0.65
            + ai_score * 0.35
        )
    )

    minimum_confidence = (
        MIN_EARLY_CONFIDENCE
        if stage == "EARLY"
        else MIN_CONFIRMED_CONFIDENCE
    )

    if confidence < minimum_confidence:
        return None

    target1 = price * (
        1 + TP1_PCT / 100
    )
    target2 = price * (
        1 + TP2_PCT / 100
    )
    target3 = price * (
        1 + TP3_PCT / 100
    )
    target4 = price * (
        1 + TP4_PCT / 100
    )
    target5 = price * (
        1 + TP5_PCT / 100
    )
    stop_loss = price * (
        1 - STOP_LOSS_PCT / 100
    )

    position = calculate_position_size(
        price,
        stop_loss,
    )

    return {
        "symbol": data["symbol"],
        "name": data["name"],
        "exchange": data.get(
            "exchange", "غير معروف"
        ),
        "type": "BUY",
        "signal_stage": stage,
        "signal_label": (
            "تنبيه ارتداد مبكر"
            if stage == "EARLY"
            else "إشارة شراء مؤكدة"
        ),
        "price": price,
        "target1": round(target1, 8),
        "target2": round(target2, 8),
        "target3": round(target3, 8),
        "target4": round(target4, 8),
        "target5": round(target5, 8),
        "stop_loss": round(stop_loss, 8),
        "confidence": confidence,
        "ai_score": ai_score,
        "position_usd": position[
            "position_usd"
        ],
        "position_pct": position[
            "position_pct"
        ],
        "position_qty": position[
            "quantity"
        ],
        "risk_amount": position[
            "risk_amount"
        ],
        "stoch_k": stoch_k,
        "stoch_d": stoch_d,
        "stoch_k_prev": stoch_k_prev,
        "stoch_d_prev": stoch_d_prev,
        "macd_histogram": histogram,
        "macd_histogram_prev": (
            histogram_prev
        ),
        "macd_direction": direction,
        "macd_color": macd["color"],
        "macd_strength": macd_strength[
            "label"
        ],
        "macd_emoji": macd_strength[
            "emoji"
        ],
        "macd_ratio": macd_strength[
            "ratio"
        ],
        "macd_switched_rising": macd.get(
            "switched_to_rising", False
        ),
        "volume_spike": volume_spike,
        "change_4h": change_4h,
        "change_24h": change_24h,
        "change_7d": change_7d,
        "volume_24h": volume_24h,
        "exchange_volume_24h": data.get(
            "exchange_volume_24h", 0
        ),
        "volume_ratio": volume_ratio,
        "current_volume_usd": (
            current_volume_usd
        ),
        "previous_volume_usd": data.get(
            "previous_volume_usd", 0
        ),
        "learning_note": learning["note"],
        "learning_adjustment": learning[
            "adjustment"
        ],
        "reasons": reasons[:9],
    }


# =========================================================
# متابعة الأهداف
# =========================================================

def register_active_signal(
    sig: dict,
) -> None:
    active_signals[sig["symbol"]] = {
        **sig,
        "signal_time": datetime.now(
            SAUDI_TZ
        ).isoformat(),
        "tp1_hit": False,
        "tp2_hit": False,
        "tp3_hit": False,
        "tp4_hit": False,
        "tp5_hit": False,
        "sl_hit": False,
    }


def add_daily_profit(
    result_pct: float,
) -> None:
    tracker.daily_profit_pct += result_pct


def check_tp_updates(
    symbol: str,
    current_price: float,
) -> list:
    if symbol not in active_signals:
        return []

    sig = active_signals[symbol]

    if sig.get("sl_hit"):
        return []

    updates = []

    targets = [
        ("TP1", "target1", "tp1_hit"),
        ("TP2", "target2", "tp2_hit"),
        ("TP3", "target3", "tp3_hit"),
        ("TP4", "target4", "tp4_hit"),
        ("TP5", "target5", "tp5_hit"),
    ]

    for tp_name, target_key, hit_key in targets:
        if (
            not sig[hit_key]
            and current_price >= sig[target_key]
        ):
            sig[hit_key] = True

            pct = (
                (
                    sig[target_key]
                    - sig["price"]
                )
                / sig["price"]
                * 100
            )

            updates.append(
                (
                    tp_name,
                    sig[target_key],
                    pct,
                )
            )

            update_signal_result_in_history(
                symbol,
                tp_name,
                pct,
            )

            add_daily_profit(pct / 5)

    if current_price <= sig["stop_loss"]:
        sig["sl_hit"] = True

        pct = (
            (
                sig["stop_loss"]
                - sig["price"]
            )
            / sig["price"]
            * 100
        )

        updates.append(
            (
                "SL",
                sig["stop_loss"],
                pct,
            )
        )

        update_signal_result_in_history(
            symbol,
            "SL",
            pct,
        )

        add_daily_profit(pct)
        del active_signals[symbol]

        return updates

    if all(
        sig.get(key)
        for key in (
            "tp1_hit",
            "tp2_hit",
            "tp3_hit",
            "tp4_hit",
            "tp5_hit",
        )
    ):
        del active_signals[symbol]

    return updates


# =========================================================
# تنسيق الرسائل
# =========================================================

def format_signal_message(
    sig: dict,
) -> str:
    reasons = "\n".join(
        f"   • {reason}"
        for reason in sig["reasons"]
    )

    timestamp = datetime.now(
        SAUDI_TZ
    ).strftime("%H:%M | %d/%m/%Y")

    spike_text = (
        "نعم 🔥"
        if sig.get("volume_spike")
        else "لا"
    )

    direction_text = (
        "⬆️ متصاعد"
        if sig.get("macd_direction")
        == "rising"
        else "⬇️ متراجع"
    )

    stage_icon = (
        "🟡"
        if sig.get("signal_stage")
        == "EARLY"
        else "🟢"
    )

    return (
        f"{stage_icon} *{sig['signal_label']} "
        f"{TIMEFRAME.upper()} | {sig['symbol']}/USDT*\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"⏰ *الوقت:* `{timestamp}`\n"
        f"🏦 *المنصة:* "
        f"`{sig.get('exchange', 'غير معروف')}`\n"
        f"💰 *سعر الدخول:* "
        f"`{fp(sig['price'])} $`\n\n"
        f"📉 *Stoch RSI K:* "
        f"`{sig.get('stoch_k')}`\n"
        f"📉 *Stoch RSI D:* "
        f"`{sig.get('stoch_d')}`\n"
        f"📈 *MACD Hist:* "
        f"`{sig.get('macd_histogram')}` — "
        f"*{sig.get('macd_strength')}* "
        f"{sig.get('macd_emoji')} "
        f"{direction_text}\n"
        f"🔥 *Volume Spike:* "
        f"`{spike_text}`\n\n"
        f"📈 *تغيير شمعة {TIMEFRAME.upper()}:* "
        f"`{sig['change_4h']:+.2f}%`\n"
        f"📊 *التغيير 24h:* "
        f"`{sig['change_24h']:+.2f}%`\n"
        f"📆 *التغيير 7d:* "
        f"`{sig['change_7d']:+.2f}%`\n"
        f"💧 *فوليوم CoinGecko 24h:* "
        f"`{format_big_number(sig['volume_24h'])} $`\n"
        f"🏦 *فوليوم المنصة 24h:* "
        f"`{format_big_number(sig.get('exchange_volume_24h', 0))} $`\n"
        f"📊 *معدل فوليوم الشمعة:* "
        f"`{sig.get('volume_ratio', 0):.2f}x`\n"
        f"💧 *فوليوم شمعة {TIMEFRAME.upper()} الحالية:* "
        f"`{format_big_number(sig.get('current_volume_usd', 0))} $`\n"
        f"⏮️ *فوليوم شمعة {TIMEFRAME.upper()} السابقة:* "
        f"`{format_big_number(sig.get('previous_volume_usd', 0))} $`\n\n"
        f"🎯 *الأهداف:*\n"
        f"   ├ TP1: `{fp(sig['target1'])} $` "
        f"`(+{TP1_PCT:g}%)`\n"
        f"   ├ TP2: `{fp(sig['target2'])} $` "
        f"`(+{TP2_PCT:g}%)`\n"
        f"   ├ TP3: `{fp(sig['target3'])} $` "
        f"`(+{TP3_PCT:g}%)`\n"
        f"   ├ TP4: `{fp(sig['target4'])} $` "
        f"`(+{TP4_PCT:g}%)`\n"
        f"   └ TP5: `{fp(sig['target5'])} $` "
        f"`(+{TP5_PCT:g}%)`\n\n"
        f"🛑 *وقف الخسارة:* "
        f"`{fp(sig['stop_loss'])} $` "
        f"`(-{STOP_LOSS_PCT:g}%)`\n\n"
        f"📌 *أسباب الإشارة:*\n"
        f"{reasons}\n\n"
        f"🧠 *الثقة:* "
        f"`{sig['confidence']}%`\n"
        f"🤖 *AI Ranking:* "
        f"`{sig['ai_score']}/100`\n"
        f"🤖 *التعلم الذاتي:* "
        f"`{sig['learning_note']}`\n"
        f"━━━━━━━━━━━━━━━━━━━━"
    )


def format_duration(
    start_iso: Optional[str],
) -> str:
    if not start_iso:
        return "-"

    try:
        start_dt = datetime.fromisoformat(
            start_iso
        )

        if start_dt.tzinfo is None:
            start_dt = SAUDI_TZ.localize(
                start_dt
            )

        diff = (
            datetime.now(SAUDI_TZ)
            - start_dt.astimezone(SAUDI_TZ)
        )

        total_minutes = int(
            diff.total_seconds() // 60
        )

        days = total_minutes // 1440
        hours = (
            total_minutes % 1440
        ) // 60
        minutes = total_minutes % 60

        parts = []

        if days > 0:
            parts.append(f"{days} يوم")

        if hours > 0:
            parts.append(f"{hours} ساعة")

        if minutes > 0:
            parts.append(f"{minutes} دقيقة")

        return (
            " و ".join(parts)
            if parts
            else "أقل من دقيقة"
        )

    except Exception:
        return "-"


def format_tp_update_message(
    sig: dict,
    updates: list,
) -> str:
    timestamp = datetime.now(SAUDI_TZ)
    duration = format_duration(
        sig.get("signal_time")
    )

    lines = []

    for name, price, pct in updates:
        if name == "SL":
            lines.append(
                f"🔴 *وقف الخسارة | "
                f"{sig['symbol']}/USDT*\n"
                f"━━━━━━━━━━━━━━━━━━━━\n"
                f"⏰ *الوقت:* "
                f"`{timestamp.strftime('%H:%M | %d/%m/%Y')}`\n"
                f"💰 *سعر الدخول:* "
                f"`{fp(sig['price'])} $`\n"
                f"⏳ *مدة الصفقة:* "
                f"`{duration}`\n"
                f"🛑 *وقف الخسارة تحقق عند:* "
                f"`{fp(price)} $` "
                f"`({pct:+.2f}%)`\n"
                f"━━━━━━━━━━━━━━━━━━━━"
            )

        else:
            lines.append(
                f"✅ *تحقق {name} | "
                f"{sig['symbol']}/USDT*\n"
                f"━━━━━━━━━━━━━━━━━━━━\n"
                f"⏰ *الوقت:* "
                f"`{timestamp.strftime('%H:%M | %d/%m/%Y')}`\n"
                f"💰 *سعر الدخول:* "
                f"`{fp(sig['price'])} $`\n"
                f"⏳ *مدة تحقيق الهدف:* "
                f"`{duration}`\n"
                f"🎯 *الهدف تحقق عند:* "
                f"`{fp(price)} $`\n"
                f"📈 *نسبة الربح:* "
                f"`{pct:+.2f}%`\n"
                f"━━━━━━━━━━━━━━━━━━━━"
            )

    return "\n\n".join(lines)


def format_daily_summary() -> str:
    today = tracker.date.strftime(
        "%d/%m/%Y"
    )
    total = tracker.total_signals

    avg_confidence = (
        round(
            sum(
                item["confidence"]
                for item in tracker.buy_signals
            )
            / total,
            1,
        )
        if total
        else 0
    )

    stats = db_get_today_winrate()

    lines = [
        f"📋 *ملخص يوم {today}*",
        "━━━━━━━━━━━━━━━━━━━━",
        f"🔍 عمليات فحص: "
        f"`{tracker.scans}`",
        f"💹 عملات محللة: "
        f"`{tracker.coins_scanned}`",
        f"📨 إجمالي الإشارات المؤكدة: "
        f"`{total}`",
        f"🧠 متوسط الثقة: "
        f"`{avg_confidence}%`",
        f"💰 مجموع الربح/الخسارة: "
        f"`{tracker.daily_profit_pct:+.2f}%`",
        f"📊 Win Rate: "
        f"`{stats['win_rate']:.1f}%`",
        f"✅ رابحة: `{stats['wins']}` | "
        f"🔴 خاسرة: `{stats['losses']}` | "
        f"إجمالي: `{stats['total']}`",
        "",
    ]

    if tracker.top_buy:
        lines.append(
            "🟢 *أقوى الإشارات:*"
        )

        for index, item in enumerate(
            tracker.top_buy, 1
        ):
            lines.append(
                f"{index}. `{item['symbol']}` "
                f"| {item.get('exchange')} "
                f"| ثقة `{item['confidence']}%`"
            )

    if total == 0:
        lines.append(
            "😴 لا توجد إشارات مؤكدة اليوم"
        )

    lines.append(
        "━━━━━━━━━━━━━━━━━━━━"
    )

    return "\n".join(lines)


# =========================================================
# إرسال تيليغرام
# =========================================================

async def send_early_alert(
    bot: Bot,
    sig: dict,
) -> None:
    try:
        await bot.send_message(
            chat_id=TELEGRAM_CHANNEL_ID,
            text=format_signal_message(sig),
            parse_mode=ParseMode.MARKDOWN,
        )

        mark_alert_sent(
            sig["symbol"],
            "EARLY",
        )

        print(
            f"🟡 {sig['symbol']} EARLY "
            f"| {sig['exchange']} "
            f"| ثقة {sig['confidence']}%"
        )

    except Exception as exc:
        logging.error(
            "send_early_alert %s: %s",
            sig["symbol"],
            exc,
        )


async def send_confirmed_signal(
    bot: Bot,
    sig: dict,
) -> None:
    try:
        await bot.send_message(
            chat_id=TELEGRAM_CHANNEL_ID,
            text=format_signal_message(sig),
            parse_mode=ParseMode.MARKDOWN,
        )

        tracker.add_signal(sig)
        register_active_signal(sig)
        save_new_signal_to_history(sig)
        db_save_signal(sig)

        mark_alert_sent(
            sig["symbol"],
            "CONFIRMED",
        )

        print(
            f"✅ {sig['symbol']} CONFIRMED "
            f"| {sig['exchange']} "
            f"| ثقة {sig['confidence']}%"
        )

    except Exception as exc:
        logging.error(
            "send_confirmed_signal %s: %s",
            sig["symbol"],
            exc,
        )


async def send_daily_summary(
    bot: Bot,
) -> None:
    try:
        await bot.send_message(
            chat_id=TELEGRAM_CHANNEL_ID,
            text=format_daily_summary(),
            parse_mode=ParseMode.MARKDOWN,
        )

        tracker.summary_sent = True

    except Exception as exc:
        logging.error(
            "send_daily_summary: %s",
            exc,
        )


# =========================================================
# تشغيل البوت
# =========================================================

async def run_bot() -> None:
    init_db()

    if not TELEGRAM_BOT_TOKEN:
        raise ValueError(
            "TELEGRAM_BOT_TOKEN غير موجود"
        )

    if not TELEGRAM_CHANNEL_ID:
        raise ValueError(
            "TELEGRAM_CHANNEL_ID غير موجود"
        )

    bot = Bot(
        token=TELEGRAM_BOT_TOKEN
    )

    try:
        me = await bot.get_me()
        print(
            f"🤖 البوت متصل: @{me.username}"
        )

    except Exception as exc:
        print(
            f"❌ فشل الاتصال بتليغرام: {exc}"
        )
        return

    try:
        await bot.send_message(
            chat_id=TELEGRAM_CHANNEL_ID,
            text=(
                f"🤖 *بوت إشارات {TIMEFRAME.upper()} شغّال الآن!*\n\n"
                f"🦎 يجلب حتى "
                f"*{COINGECKO_MAX_COINS:,}* "
                f"عملة من CoinGecko\n"
                f"🏦 المنصات المفعلة: *{', '.join(EXCHANGES)}*\n"
                f"⏱️ الفريم: *{TIMEFRAME.upper()}*\n"
                "💧 يختار المنصة الأعلى سيولة "
                "لكل زوج USDT\n"
                f"📉 Stoch RSI أقل من "
                f"*{MAX_RSI_BUY}*\n"
                f"💧 أقل فوليوم شمعة: "
                f"*{format_big_number(MIN_CURRENT_CANDLE_VOLUME_USD)}$*\n"
                f"🟡 أقل ثقة مبكرة: "
                f"*{MIN_EARLY_CONFIDENCE}%*\n"
                f"🟢 أقل ثقة مؤكدة: "
                f"*{MIN_CONFIRMED_CONFIDENCE}%*\n"
                f"⏱️ فحص كل "
                f"*{CHECK_INTERVAL // 60} دقيقة*"
            ),
            parse_mode=ParseMode.MARKDOWN,
        )

    except Exception as exc:
        logging.warning(
            "لم تُرسل رسالة البداية: %s",
            exc,
        )

    while True:
        try:
            now = datetime.now(SAUDI_TZ)

            if (
                now.hour == DAILY_SUMMARY_HOUR
                and not tracker.summary_sent
            ):
                await send_daily_summary(bot)

            if tracker.new_day():
                tracker.reset()

            print("=" * 60)
            print(
                f"🔍 [{now.strftime('%H:%M:%S')}] "
                "جلب قائمة CoinGecko والمنصات"
            )

            coins = (
                get_markets_from_coingecko_and_exchanges()
            )

            tracker.scans += 1
            tracker.coins_scanned += len(coins)

            signals_this_round = 0

            for index, coin in enumerate(
                coins, 1
            ):
                print(
                    f"[{index}/{len(coins)}] "
                    f"تحليل {coin['symbol']} "
                    f"على {coin['exchange']} "
                    f"| {TIMEFRAME.upper()}",
                    end="\r",
                )

                market_data = (
                    get_market_data_for_exchange(
                        coin["symbol"],
                        coin["exchange"],
                    )
                )

                if not market_data:
                    await asyncio.sleep(
                        COIN_REQUEST_DELAY
                    )
                    continue

                closes = market_data["closes"]

                if len(closes) < 43:
                    await asyncio.sleep(
                        COIN_REQUEST_DELAY
                    )
                    continue

                current_price = closes[-1]
                coin["price"] = current_price

                coin["change_4h"] = (
                    (
                        closes[-1]
                        - closes[-2]
                    )
                    / closes[-2]
                    * 100
                    if closes[-2]
                    else 0.0
                )

                coin["change_7d"] = (
                    (
                        closes[-1]
                        - closes[-43]
                    )
                    / closes[-43]
                    * 100
                    if closes[-43]
                    else coin.get(
                        "change_7d", 0.0
                    )
                )

                if (
                    coin["symbol"]
                    in active_signals
                ):
                    sig_before = (
                        active_signals.get(
                            coin["symbol"]
                        )
                    )

                    updates = check_tp_updates(
                        coin["symbol"],
                        current_price,
                    )

                    if updates and sig_before:
                        try:
                            await bot.send_message(
                                chat_id=(
                                    TELEGRAM_CHANNEL_ID
                                ),
                                text=(
                                    format_tp_update_message(
                                        sig_before,
                                        updates,
                                    )
                                ),
                                parse_mode=(
                                    ParseMode.MARKDOWN
                                ),
                            )

                        except Exception as exc:
                            logging.error(
                                "TP update %s: %s",
                                coin["symbol"],
                                exc,
                            )

                stoch = calculate_stoch_rsi(
                    closes,
                    RSI_PERIOD,
                    STOCH_PERIOD,
                    STOCH_K_SMOOTH,
                    STOCH_D_SMOOTH,
                )

                macd = calculate_macd(closes)
                volume_data = (
                    detect_volume_spike(
                        market_data
                    )
                )

                if stoch is None or macd is None:
                    await asyncio.sleep(
                        COIN_REQUEST_DELAY
                    )
                    continue

                coin["stoch"] = stoch
                coin["macd"] = macd
                coin["volume_spike"] = (
                    volume_data["spike"]
                )
                coin["volume_ratio"] = (
                    volume_data["ratio"]
                )
                coin["current_volume_usd"] = (
                    volume_data[
                        "current_volume_usd"
                    ]
                )
                coin["previous_volume_usd"] = (
                    volume_data[
                        "previous_volume_usd"
                    ]
                )
                coin["volume_enough_data"] = (
                    volume_data["enough_data"]
                )

                signal = analyze_signal(coin)

                if signal:
                    stage = signal[
                        "signal_stage"
                    ]

                    if stage == "EARLY":
                        if (
                            coin["symbol"]
                            not in active_signals
                            and not alert_on_cooldown(
                                coin["symbol"],
                                "EARLY",
                            )
                        ):
                            await send_early_alert(
                                bot,
                                signal,
                            )
                            signals_this_round += 1
                            await asyncio.sleep(1.5)

                    else:
                        if (
                            coin["symbol"]
                            not in active_signals
                            and not alert_on_cooldown(
                                coin["symbol"],
                                "CONFIRMED",
                            )
                        ):
                            await send_confirmed_signal(
                                bot,
                                signal,
                            )
                            signals_this_round += 1
                            await asyncio.sleep(1.5)

                await asyncio.sleep(
                    COIN_REQUEST_DELAY
                )

            print()
            print(
                f"📬 إشارات الجولة: "
                f"{signals_this_round} | "
                f"المؤكدة اليوم: "
                f"{tracker.total_signals}"
            )
            print(
                f"⏳ الفحص القادم بعد "
                f"{CHECK_INTERVAL // 60} دقيقة"
            )

            await asyncio.sleep(
                CHECK_INTERVAL
            )

        except Exception as exc:
            logging.exception(
                "خطأ في دورة البوت: %s",
                exc,
            )

            await asyncio.sleep(60)


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format=(
            "%(asctime)s — "
            "%(levelname)s — "
            "%(message)s"
        ),
    )

    asyncio.run(run_bot())

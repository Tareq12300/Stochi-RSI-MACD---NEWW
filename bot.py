import os
import time
import threading
from datetime import datetime

import ccxt
import pandas as pd
import requests
from flask import Flask


# =========================
# FLASK FOR RAILWAY
# =========================
app = Flask(__name__)

@app.route("/")
def home():
    return "CMC Multi-Exchange Stoch RSI + MACD Bot is running ✅"


# =========================
# ENV HELPERS
# =========================
def env_str(name, default=""):
    return os.getenv(name, default).strip()

def env_int(name, default):
    try:
        return int(os.getenv(name, str(default)))
    except:
        return default

def env_float(name, default):
    try:
        return float(os.getenv(name, str(default)))
    except:
        return default

def env_bool(name, default):
    return os.getenv(name, str(default)).lower() == "true"


# =========================
# VARIABLES
# =========================
TELEGRAM_BOT_TOKEN = env_str("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHANNEL_ID = env_str("TELEGRAM_CHANNEL_ID")

CHECK_INTERVAL = env_int("CHECK_INTERVAL", 900)
TIMEFRAMES = [x.strip() for x in env_str("TIMEFRAMES", "1h,4h,1d").split(",") if x.strip()]

RSI_LENGTH = env_int("RSI_LENGTH", 14)
STOCH_LENGTH = env_int("STOCH_LENGTH", 14)
K_SMOOTH = env_int("K_SMOOTH", 3)
D_SMOOTH = env_int("D_SMOOTH", 3)

MACD_FAST = env_int("MACD_FAST", 12)
MACD_SLOW = env_int("MACD_SLOW", 26)
MACD_SIGNAL = env_int("MACD_SIGNAL", 9)

MAX_STOCH_RSI = env_float("MAX_STOCH_RSI", 40)

REQUIRE_K_ABOVE_D = env_bool("REQUIRE_K_ABOVE_D", True)
REQUIRE_MACD_POSITIVE = env_bool("REQUIRE_MACD_POSITIVE", True)
REQUIRE_MACD_RISING = env_bool("REQUIRE_MACD_RISING", True)
REQUIRE_MACD_JUST_TURNED_POSITIVE = env_bool("REQUIRE_MACD_JUST_TURNED_POSITIVE", False)

MIN_24H_VOLUME_USD = env_float("MIN_24H_VOLUME_USD", 50000)
MIN_CANDLE_VOLUME_USD = env_float("MIN_CANDLE_VOLUME_USD", 200000)
MIN_VOLUME_RATIO = env_float("MIN_VOLUME_RATIO", 2)

VOLUME_LOOKBACK = env_int("VOLUME_LOOKBACK", 20)

SIGNAL_COOLDOWN_HOURS = env_float("SIGNAL_COOLDOWN_HOURS", 12)

ENABLE_GATE = env_bool("ENABLE_GATE", True)
ENABLE_KUCOIN = env_bool("ENABLE_KUCOIN", True)
ENABLE_OKX = env_bool("ENABLE_OKX", True)
ENABLE_BYBIT = env_bool("ENABLE_BYBIT", True)
ENABLE_BITGET = env_bool("ENABLE_BITGET", True)

USE_CMC_FILTER = env_bool("USE_CMC_FILTER", True)
CMC_API_KEY = env_str("CMC_API_KEY")
CMC_TOP_N = env_int("CMC_TOP_N", 2000)
MIN_MARKET_CAP = env_float("MIN_MARKET_CAP", 0)
MAX_MARKET_CAP = env_float("MAX_MARKET_CAP", 1000000000)

EXCLUDE_STABLES = env_bool("EXCLUDE_STABLES", True)


# =========================
# GLOBALS
# =========================
last_alerts = {}


# =========================
# TELEGRAM
# =========================
def send_telegram(message):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHANNEL_ID:
        print("Telegram variables missing")
        return

    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"

    payload = {
        "chat_id": TELEGRAM_CHANNEL_ID,
        "text": message,
        "parse_mode": "HTML",
        "disable_web_page_preview": True
    }

    try:
        requests.post(url, json=payload, timeout=20)
    except Exception as e:
        print("Telegram error:", e)


# =========================
# COINMARKETCAP
# =========================
STABLE_BASES = {
    "USDT", "USDC", "BUSD", "DAI", "TUSD", "FDUSD", "USDD",
    "USDE", "SUSD", "PYUSD", "USD", "EUR", "TRY", "BRL"
}

def get_cmc_symbols():
    if not USE_CMC_FILTER:
        return set()

    if not CMC_API_KEY:
        print("CMC_API_KEY missing")
        return set()

    url = "https://pro-api.coinmarketcap.com/v1/cryptocurrency/listings/latest"

    headers = {
        "X-CMC_PRO_API_KEY": CMC_API_KEY
    }

    params = {
        "start": 1,
        "limit": min(CMC_TOP_N, 5000),
        "convert": "USD",
        "sort": "market_cap"
    }

    try:
        response = requests.get(url, headers=headers, params=params, timeout=30)
        response.raise_for_status()

        data = response.json().get("data", [])
        symbols = set()

        for coin in data:
            symbol = coin.get("symbol", "").upper()
            quote = coin.get("quote", {}).get("USD", {})
            market_cap = quote.get("market_cap") or 0

            if not symbol:
                continue

            if EXCLUDE_STABLES and symbol in STABLE_BASES:
                continue

            if market_cap < MIN_MARKET_CAP:
                continue

            if MAX_MARKET_CAP > 0 and market_cap > MAX_MARKET_CAP:
                continue

            symbols.add(symbol)

        print(f"CMC symbols loaded: {len(symbols)}")
        return symbols

    except Exception as e:
        print("CMC error:", e)
        return set()


# =========================
# INDICATORS
# =========================
def rma(series, length):
    return series.ewm(alpha=1 / length, adjust=False).mean()

def calculate_rsi(close, length):
    delta = close.diff()

    gain = delta.where(delta > 0, 0)
    loss = -delta.where(delta < 0, 0)

    avg_gain = rma(gain, length)
    avg_loss = rma(loss, length)

    rs = avg_gain / avg_loss
    rsi = 100 - (100 / (1 + rs))

    return rsi

def calculate_stoch_rsi(df):
    rsi = calculate_rsi(df["close"], RSI_LENGTH)

    lowest_rsi = rsi.rolling(STOCH_LENGTH).min()
    highest_rsi = rsi.rolling(STOCH_LENGTH).max()

    stoch = 100 * (rsi - lowest_rsi) / (highest_rsi - lowest_rsi)

    k = stoch.rolling(K_SMOOTH).mean()
    d = k.rolling(D_SMOOTH).mean()

    df["rsi"] = rsi
    df["stoch_k"] = k
    df["stoch_d"] = d

    return df

def calculate_macd(df):
    close = df["close"]

    ema_fast = close.ewm(span=MACD_FAST, adjust=False).mean()
    ema_slow = close.ewm(span=MACD_SLOW, adjust=False).mean()

    macd = ema_fast - ema_slow
    signal = macd.ewm(span=MACD_SIGNAL, adjust=False).mean()
    hist = macd - signal

    df["macd"] = macd
    df["macd_signal"] = signal
    df["macd_hist"] = hist

    return df


# =========================
# EXCHANGES
# =========================
def get_exchanges():
    exchanges = []

    if ENABLE_GATE:
        exchanges.append(("Gate", ccxt.gateio({"enableRateLimit": True})))

    if ENABLE_KUCOIN:
        exchanges.append(("KuCoin", ccxt.kucoin({"enableRateLimit": True})))

    if ENABLE_OKX:
        exchanges.append(("OKX", ccxt.okx({"enableRateLimit": True})))

    if ENABLE_BYBIT:
        exchanges.append(("Bybit", ccxt.bybit({"enableRateLimit": True})))

    if ENABLE_BITGET:
        exchanges.append(("Bitget", ccxt.bitget({"enableRateLimit": True})))

    return exchanges


BAD_KEYWORDS = [
    "UP/", "DOWN/", "BULL/", "BEAR/",
    "3L/", "3S/", "5L/", "5S/"
]

def is_valid_symbol(symbol, cmc_symbols):
    if not symbol.endswith("/USDT"):
        return False

    if any(x in symbol for x in BAD_KEYWORDS):
        return False

    base = symbol.split("/")[0].upper()

    if EXCLUDE_STABLES and base in STABLE_BASES:
        return False

    if USE_CMC_FILTER and cmc_symbols and base not in cmc_symbols:
        return False

    return True

def get_symbols(exchange, cmc_symbols):
    try:
        markets = exchange.load_markets()
        symbols = []

        for symbol, market in markets.items():
            if not market.get("active", True):
                continue

            if is_valid_symbol(symbol, cmc_symbols):
                symbols.append(symbol)

        return symbols

    except Exception as e:
        print("Load markets error:", e)
        return []

def fetch_ohlcv(exchange, symbol, timeframe):
    try:
        candles = exchange.fetch_ohlcv(symbol, timeframe=timeframe, limit=200)

        if not candles or len(candles) < 80:
            return None

        df = pd.DataFrame(
            candles,
            columns=["time", "open", "high", "low", "close", "volume"]
        )

        df["time"] = pd.to_datetime(df["time"], unit="ms")
        df["candle_volume_usd"] = df["close"] * df["volume"]

        avg_volume = df["candle_volume_usd"].rolling(VOLUME_LOOKBACK).mean()
        df["volume_ratio"] = df["candle_volume_usd"] / avg_volume

        return df

    except Exception:
        return None

def fetch_ticker(exchange, symbol):
    try:
        ticker = exchange.fetch_ticker(symbol)

        return {
            "last": ticker.get("last") or 0,
            "quoteVolume": ticker.get("quoteVolume") or 0,
            "percentage": ticker.get("percentage") or 0
        }

    except:
        return {
            "last": 0,
            "quoteVolume": 0,
            "percentage": 0
        }


# =========================
# SIGNAL LOGIC
# =========================
def check_signal(df):
    df = calculate_stoch_rsi(df)
    df = calculate_macd(df)

    latest = df.iloc[-1]
    previous = df.iloc[-2]

    k = latest["stoch_k"]
    d = latest["stoch_d"]

    hist = latest["macd_hist"]
    prev_hist = previous["macd_hist"]

    candle_volume = latest["candle_volume_usd"]
    volume_ratio = latest["volume_ratio"]

    if pd.isna(k) or pd.isna(d) or pd.isna(hist) or pd.isna(prev_hist) or pd.isna(volume_ratio):
        return False, {}

    if k > MAX_STOCH_RSI:
        return False, {}

    if REQUIRE_K_ABOVE_D and not k > d:
        return False, {}

    if REQUIRE_MACD_POSITIVE and not hist > 0:
        return False, {}

    if REQUIRE_MACD_RISING and not hist > prev_hist:
        return False, {}

    if REQUIRE_MACD_JUST_TURNED_POSITIVE and not (prev_hist <= 0 and hist > 0):
        return False, {}

    if candle_volume < MIN_CANDLE_VOLUME_USD:
        return False, {}

    if volume_ratio < MIN_VOLUME_RATIO:
        return False, {}

    data = {
        "k": float(k),
        "d": float(d),
        "macd_hist": float(hist),
        "prev_macd_hist": float(prev_hist),
        "candle_volume": float(candle_volume),
        "volume_ratio": float(volume_ratio),
        "close": float(latest["close"])
    }

    return True, data


def can_alert(exchange_name, symbol):
    key = f"{exchange_name}:{symbol}"
    now = time.time()

    last_time = last_alerts.get(key)

    if last_time is None:
        return True

    cooldown = SIGNAL_COOLDOWN_HOURS * 3600

    return now - last_time >= cooldown

def mark_alert(exchange_name, symbol):
    key = f"{exchange_name}:{symbol}"
    last_alerts[key] = time.time()


# =========================
# FORMAT
# =========================
def format_money(value):
    try:
        value = float(value)

        if value >= 1_000_000_000:
            return f"${value / 1_000_000_000:.2f}B"

        if value >= 1_000_000:
            return f"${value / 1_000_000:.2f}M"

        if value >= 1_000:
            return f"${value / 1_000:.2f}K"

        return f"${value:.2f}"

    except:
        return "$0"

def build_alert_message(exchange_name, symbol, ticker, matched_frames):
    now = datetime.now().strftime("%Y-%m-%d %H:%M")

    price = ticker.get("last") or matched_frames[0]["data"]["close"]
    volume_24h = ticker.get("quoteVolume", 0)
    change_24h = ticker.get("percentage", 0)

    message = f"""
🟢 <b>إشارة شراء | Stoch RSI + MACD</b>
━━━━━━━━━━━━━━
⏰ الوقت: <b>{now}</b>
🏦 المنصة: <b>{exchange_name}</b>
🪙 العملة: <b>{symbol}</b>
💰 السعر: <b>{price}</b>

📊 <b>الفريمات التي تحققت فيها الشروط:</b>
"""

    for item in matched_frames:
        tf = item["timeframe"]
        data = item["data"]

        message += f"""
━━━━━━━━━━━━━━
⏱️ <b>الفريم: {tf}</b>

📈 <b>Stoch RSI</b>
K: <b>{data["k"]:.2f}</b>
D: <b>{data["d"]:.2f}</b>

📊 <b>MACD Histogram</b>
الحالي: <b>{data["macd_hist"]:.8f}</b>
السابق: <b>{data["prev_macd_hist"]:.8f}</b>
الحالة: موجب ويتحسن ✅

💧 <b>Volume</b>
حجم الشمعة: <b>{format_money(data["candle_volume"])}</b>
Volume Ratio: <b>{data["volume_ratio"]:.2f}x</b>
"""

    message += f"""
━━━━━━━━━━━━━━
📊 24H Volume: <b>{format_money(volume_24h)}</b>
📈 تغير 24H: <b>{change_24h:.2f}%</b>

✅ <b>الشروط:</b>
• العملة مأخوذة من CoinMarketCap ✅
• Stoch RSI أقل من {MAX_STOCH_RSI}
• K أعلى من D: {"مطلوب ✅" if REQUIRE_K_ABOVE_D else "غير مطلوب"}
• MACD موجب: {"مطلوب ✅" if REQUIRE_MACD_POSITIVE else "غير مطلوب"}
• MACD متصاعد: {"مطلوب ✅" if REQUIRE_MACD_RISING else "غير مطلوب"}
• Volume Ratio أعلى من {MIN_VOLUME_RATIO}x
• حجم الشمعة أعلى من {format_money(MIN_CANDLE_VOLUME_USD)}

⚠️ تحليل آلي فقط وليس توصية مالية.
"""

    return message.strip()


# =========================
# STARTUP MESSAGE
# =========================
def startup_message():
    enabled_exchanges = []

    if ENABLE_GATE:
        enabled_exchanges.append("Gate")

    if ENABLE_KUCOIN:
        enabled_exchanges.append("KuCoin")

    if ENABLE_OKX:
        enabled_exchanges.append("OKX")

    if ENABLE_BYBIT:
        enabled_exchanges.append("Bybit")

    if ENABLE_BITGET:
        enabled_exchanges.append("Bitget")

    exchanges_text = "\n".join([f"• {x}" for x in enabled_exchanges])

    return f"""
🤖 <b>بوت Stoch RSI + MACD اشتغل بنجاح ✅</b>
━━━━━━━━━━━━━━
📌 المصدر الأساسي للعملات:
CoinMarketCap ✅

🔎 طريقة العمل:
CMC → فلترة Market Cap → البحث في المنصات → فحص 1h / 4h / 1d → إرسال التنبيه

⏱️ الفريمات:
<b>{", ".join(TIMEFRAMES)}</b>

🔁 الفحص كل:
<b>{CHECK_INTERVAL}</b> ثانية

🏦 المنصات المفعلة:
{exchanges_text}

🌐 CoinMarketCap:
• الحالة: {"مفعل ✅" if USE_CMC_FILTER else "غير مفعل"}
• Top N: {CMC_TOP_N}
• Min Market Cap: {format_money(MIN_MARKET_CAP)}
• Max Market Cap: {format_money(MAX_MARKET_CAP)}

📊 Stoch RSI:
• RSI Length: {RSI_LENGTH}
• Stoch Length: {STOCH_LENGTH}
• K Smooth: {K_SMOOTH}
• D Smooth: {D_SMOOTH}
• Max Stoch RSI: {MAX_STOCH_RSI}

📈 MACD:
• Fast: {MACD_FAST}
• Slow: {MACD_SLOW}
• Signal: {MACD_SIGNAL}

🎯 شروط الدخول:
• K أعلى من D: {"مطلوب ✅" if REQUIRE_K_ABOVE_D else "غير مطلوب"}
• MACD موجب: {"مطلوب ✅" if REQUIRE_MACD_POSITIVE else "غير مطلوب"}
• MACD متصاعد: {"مطلوب ✅" if REQUIRE_MACD_RISING else "غير مطلوب"}
• MACD تحول من سلبي إلى موجب: {"مطلوب ✅" if REQUIRE_MACD_JUST_TURNED_POSITIVE else "غير مطلوب"}
• Volume Ratio أعلى من: {MIN_VOLUME_RATIO}x
• حجم الشمعة أقل شيء: {format_money(MIN_CANDLE_VOLUME_USD)}
• 24H Volume أقل شيء: {format_money(MIN_24H_VOLUME_USD)}

✅ سيتم إرسال تنبيه عند تحقق الشروط في أي فريم.
""".strip()


# =========================
# SCANNER
# =========================
def scan_exchange(exchange_name, exchange, cmc_symbols):
    print(f"Scanning {exchange_name}...")

    symbols = get_symbols(exchange, cmc_symbols)

    print(f"{exchange_name} valid symbols: {len(symbols)}")

    for symbol in symbols:
        try:
            ticker = fetch_ticker(exchange, symbol)

            if ticker["quoteVolume"] < MIN_24H_VOLUME_USD:
                continue

            matched_frames = []

            for timeframe in TIMEFRAMES:
                df = fetch_ohlcv(exchange, symbol, timeframe)

                if df is None:
                    continue

                is_signal, data = check_signal(df)

                if is_signal:
                    matched_frames.append({
                        "timeframe": timeframe,
                        "data": data
                    })

            if matched_frames and can_alert(exchange_name, symbol):
                message = build_alert_message(
                    exchange_name,
                    symbol,
                    ticker,
                    matched_frames
                )

                send_telegram(message)
                mark_alert(exchange_name, symbol)

                print(f"Alert sent: {exchange_name} {symbol}")

            time.sleep(0.25)

        except Exception as e:
            print(f"Error scanning {exchange_name} {symbol}:", e)


def scanner_loop():
    send_telegram(startup_message())

    while True:
        cmc_symbols = get_cmc_symbols()

        exchanges = get_exchanges()

        for exchange_name, exchange in exchanges:
            scan_exchange(exchange_name, exchange, cmc_symbols)

        print(f"Sleeping {CHECK_INTERVAL} seconds...")
        time.sleep(CHECK_INTERVAL)


# =========================
# RUN
# =========================
if __name__ == "__main__":
    thread = threading.Thread(target=scanner_loop)
    thread.daemon = True
    thread.start()

    port = int(os.getenv("PORT", 8080))
    app.run(host="0.0.0.0", port=port)

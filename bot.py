import os
import time
import asyncio
import logging
import requests

from telegram.constants import ParseMode
from telegram.ext import ApplicationBuilder

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

BOT_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
CHANNEL_ID = os.environ["TELEGRAM_CHANNEL_ID"]

CHECK_INTERVAL = int(os.getenv("CHECK_INTERVAL", "300"))
STOCH_MAX_K = float(os.getenv("STOCH_MAX_K", "50"))
MIN_VOLUME_USDT = float(os.getenv("MIN_VOLUME_USDT", "50000"))
MIN_CONFIDENCE = int(os.getenv("MIN_CONFIDENCE", "70"))

EXCHANGES = ["gate", "mexc", "okx", "bybit"]

sent_alerts = set()

# ─────────────────────────────────────────────
# INTERVAL MAP
# ─────────────────────────────────────────────

def interval_map(exchange):

    if exchange == "gate":
        return "4h"

    if exchange == "mexc":
        return "4h"

    if exchange == "okx":
        return "4H"

    if exchange == "bybit":
        return "240"

    return "4h"

# ─────────────────────────────────────────────
# REQUEST
# ─────────────────────────────────────────────

def safe_get(url, params=None):

    r = requests.get(url, params=params, timeout=20)
    r.raise_for_status()

    return r.json()

# ─────────────────────────────────────────────
# PAIRS
# ─────────────────────────────────────────────

def get_pairs_gate():

    data = safe_get(
        "https://api.gateio.ws/api/v4/spot/currency_pairs"
    )

    pairs = []

    for x in data:

        if (
            x.get("quote") == "USDT"
            and x.get("trade_status") == "tradable"
        ):
            pairs.append(x["id"])

    return pairs

def get_pairs_mexc():

    data = safe_get(
        "https://api.mexc.com/api/v3/exchangeInfo"
    )

    pairs = []

    for x in data.get("symbols", []):

        if (
            x.get("quoteAsset") == "USDT"
            and x.get("status") == "ENABLED"
        ):
            pairs.append(x["symbol"])

    return pairs

def get_pairs_okx():

    data = safe_get(
        "https://www.okx.com/api/v5/public/instruments",
        {"instType": "SPOT"}
    )

    pairs = []

    for x in data.get("data", []):

        if (
            x.get("quoteCcy") == "USDT"
            and x.get("state") == "live"
        ):
            pairs.append(x["instId"])

    return pairs

def get_pairs_bybit():

    data = safe_get(
        "https://api.bybit.com/v5/market/instruments-info",
        {
            "category": "spot",
            "limit": 1000
        }
    )

    pairs = []

    for x in data.get("result", {}).get("list", []):

        if (
            x.get("quoteCoin") == "USDT"
            and x.get("status") == "Trading"
        ):
            pairs.append(x["symbol"])

    return pairs

# ─────────────────────────────────────────────
# CANDLES
# ─────────────────────────────────────────────

def get_candles_gate(pair):

    data = safe_get(
        "https://api.gateio.ws/api/v4/spot/candlesticks",
        {
            "currency_pair": pair,
            "interval": interval_map("gate"),
            "limit": 100
        }
    )

    candles = []

    for c in data:

        close = float(c[2])
        base_vol = float(c[1])

        candles.append({
            "close": close,
            "volume": base_vol * close
        })

    return candles

def get_candles_mexc(pair):

    data = safe_get(
        "https://api.mexc.com/api/v3/klines",
        {
            "symbol": pair,
            "interval": interval_map("mexc"),
            "limit": 100
        }
    )

    candles = []

    for c in data:

        candles.append({
            "close": float(c[4]),
            "volume": float(c[7])
        })

    return candles

def get_candles_okx(pair):

    data = safe_get(
        "https://www.okx.com/api/v5/market/candles",
        {
            "instId": pair,
            "bar": interval_map("okx"),
            "limit": 100
        }
    )

    candles = []

    for c in data.get("data", []):

        candles.append({
            "close": float(c[4]),
            "volume": float(c[7])
        })

    return candles

def get_candles_bybit(pair):

    data = safe_get(
        "https://api.bybit.com/v5/market/kline",
        {
            "category": "spot",
            "symbol": pair,
            "interval": interval_map("bybit"),
            "limit": 100
        }
    )

    candles = []

    for c in data.get("result", {}).get("list", []):

        candles.append({
            "close": float(c[4]),
            "volume": float(c[6])
        })

    return candles

# ─────────────────────────────────────────────
# RSI
# ─────────────────────────────────────────────

def rsi(values, period=14):

    if len(values) < period + 1:
        return []

    gains = []
    losses = []

    for i in range(1, len(values)):

        diff = values[i] - values[i - 1]

        gains.append(max(diff, 0))
        losses.append(abs(min(diff, 0)))

    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period

    rsis = []

    for i in range(period, len(gains)):

        avg_gain = ((avg_gain * (period - 1)) + gains[i]) / period
        avg_loss = ((avg_loss * (period - 1)) + losses[i]) / period

        if avg_loss == 0:
            rsis.append(100)
        else:
            rs = avg_gain / avg_loss
            rsis.append(100 - (100 / (1 + rs)))

    return rsis

# ─────────────────────────────────────────────
# STOCH RSI
# ─────────────────────────────────────────────

def stoch_rsi(closes):

    rsi_values = rsi(closes)

    if len(rsi_values) < 20:
        return None

    lowest = min(rsi_values[-14:])
    highest = max(rsi_values[-14:])

    if highest == lowest:
        return None

    current = rsi_values[-1]

    k = ((current - lowest) / (highest - lowest)) * 100

    d = sum([
        ((x - lowest) / (highest - lowest)) * 100
        for x in rsi_values[-3:]
    ]) / 3

    return k, d

# ─────────────────────────────────────────────
# ALERT
# ─────────────────────────────────────────────

def build_alert(exchange, pair, price, k, d, volume):

    return (
        f"🟢 *Stoch RSI Alert*\n\n"
        f"🏦 المنصة: *{exchange.upper()}*\n"
        f"🪙 العملة: *{pair}*\n"
        f"💰 السعر: `{price}`\n\n"
        f"📊 K: `{k:.2f}`\n"
        f"📊 D: `{d:.2f}`\n\n"
        f"💧 Volume: `${volume:,.0f}`\n\n"
        f"⚠️ تحليل فقط وليس نصيحة مالية"
    )

# ─────────────────────────────────────────────
# SCANNER
# ─────────────────────────────────────────────

async def scanner(app):

    await asyncio.sleep(5)

    while True:

        try:

            logger.info("🔍 Scanning...")

            exchanges = {
                "gate": (get_pairs_gate, get_candles_gate),
                "mexc": (get_pairs_mexc, get_candles_mexc),
                "okx": (get_pairs_okx, get_candles_okx),
                "bybit": (get_pairs_bybit, get_candles_bybit),
            }

            for exchange, funcs in exchanges.items():

                get_pairs, get_candles = funcs

                pairs = get_pairs()

                logger.info(f"{exchange}: {len(pairs)} pairs")

                for pair in pairs[:300]:

                    try:

                        candles = get_candles(pair)

                        closes = [x["close"] for x in candles]

                        result = stoch_rsi(closes)

                        if not result:
                            continue

                        k, d = result

                        last = candles[-1]

                        volume = last["volume"]
                        price = last["close"]

                        confidence = 0

                        if k > d:
                            confidence += 40

                        if k <= STOCH_MAX_K:
                            confidence += 30

                        if volume >= MIN_VOLUME_USDT:
                            confidence += 30

                        if (
                            k > d
                            and k <= STOCH_MAX_K
                            and volume >= MIN_VOLUME_USDT
                            and confidence >= MIN_CONFIDENCE
                        ):

                            key = f"{exchange}_{pair}"

                            if key in sent_alerts:
                                continue

                            sent_alerts.add(key)

                            await app.bot.send_message(
                                chat_id=CHANNEL_ID,
                                text=build_alert(
                                    exchange,
                                    pair,
                                    price,
                                    k,
                                    d,
                                    volume
                                ),
                                parse_mode=ParseMode.MARKDOWN
                            )

                            await asyncio.sleep(1)

                    except Exception as e:
                        logger.warning(f"{exchange} {pair} error: {e}")

        except Exception as e:
            logger.error(f"Scanner Error: {e}")

        await asyncio.sleep(CHECK_INTERVAL)

# ─────────────────────────────────────────────
# STARTUP
# ─────────────────────────────────────────────

async def startup(app):

    await app.bot.send_message(
        chat_id=CHANNEL_ID,
        text="🚀 البوت شغّال — Stoch RSI 4H"
    )

    asyncio.create_task(scanner(app))

# ─────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────

def main():

    app = ApplicationBuilder().token(BOT_TOKEN).build()

    app.post_init = startup

    logger.info("🚀 البوت شغّال!")

    app.run_polling()

if __name__ == "__main__":
    main()
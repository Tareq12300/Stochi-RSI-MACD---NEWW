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
STOCH_MAX_K = float(os.getenv("STOCH_MAX_K", "30"))
MIN_VOLUME_USDT = float(os.getenv("MIN_VOLUME_USDT", "50000"))
MIN_VOLUME_RATIO = float(os.getenv("MIN_VOLUME_RATIO", "1.2"))
MIN_CONFIDENCE = int(os.getenv("MIN_CONFIDENCE", "70"))

REQUIRE_MACD_POSITIVE = os.getenv("REQUIRE_MACD_POSITIVE", "false").lower() == "true"

EXCLUDE_KEYWORDS = os.getenv(
    "EXCLUDE_KEYWORDS",
    "USDC,USDT,FDUSD,TUSD,USDE,DAI,BUSD,USDP,USDD,BABAON,NVDAX,UP,DOWN,3L,3S,BULL,BEAR"
).split(",")

sent_alerts = set()


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


def safe_get(url, params=None):
    r = requests.get(url, params=params, timeout=20)
    r.raise_for_status()
    return r.json()


def should_skip_pair(pair):
    pair_upper = pair.upper()

    for keyword in EXCLUDE_KEYWORDS:
        keyword = keyword.strip().upper()
        if keyword and keyword in pair_upper:
            return True

    return False


def get_pairs_gate():
    data = safe_get("https://api.gateio.ws/api/v4/spot/currency_pairs")
    return [
        x["id"] for x in data
        if x.get("quote") == "USDT"
        and x.get("trade_status") == "tradable"
        and not should_skip_pair(x["id"])
    ]


def get_pairs_mexc():
    data = safe_get("https://api.mexc.com/api/v3/exchangeInfo")
    return [
        x["symbol"] for x in data.get("symbols", [])
        if x.get("quoteAsset") == "USDT"
        and x.get("status") == "ENABLED"
        and not should_skip_pair(x["symbol"])
    ]


def get_pairs_okx():
    data = safe_get(
        "https://www.okx.com/api/v5/public/instruments",
        {"instType": "SPOT"}
    )
    return [
        x["instId"] for x in data.get("data", [])
        if x.get("quoteCcy") == "USDT"
        and x.get("state") == "live"
        and not should_skip_pair(x["instId"])
    ]


def get_pairs_bybit():
    data = safe_get(
        "https://api.bybit.com/v5/market/instruments-info",
        {"category": "spot", "limit": 1000}
    )
    return [
        x["symbol"] for x in data.get("result", {}).get("list", [])
        if x.get("quoteCoin") == "USDT"
        and x.get("status") == "Trading"
        and not should_skip_pair(x["symbol"])
    ]


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

    return [
        {
            "close": float(c[4]),
            "volume": float(c[7])
        }
        for c in data
    ]


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

    return list(reversed(candles))


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

    return list(reversed(candles))


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

    d_values = []
    for x in rsi_values[-3:]:
        d_values.append(((x - lowest) / (highest - lowest)) * 100)

    d = sum(d_values) / len(d_values)

    return k, d


def ema(values, period):
    if len(values) < period:
        return None

    multiplier = 2 / (period + 1)
    ema_value = sum(values[:period]) / period

    for price in values[period:]:
        ema_value = (price - ema_value) * multiplier + ema_value

    return ema_value


def macd_histogram(closes):
    if len(closes) < 35:
        return 0

    ema12 = ema(closes, 12)
    ema26 = ema(closes, 26)

    if ema12 is None or ema26 is None:
        return 0

    macd_line = ema12 - ema26

    macd_values = []

    for i in range(26, len(closes)):
        part = closes[:i + 1]
        e12 = ema(part, 12)
        e26 = ema(part, 26)

        if e12 is not None and e26 is not None:
            macd_values.append(e12 - e26)

    signal = ema(macd_values, 9)

    if signal is None:
        return 0

    return macd_line - signal


def volume_ratio(candles):
    if len(candles) < 21:
        return 0

    current_volume = candles[-1]["volume"]
    avg_volume = sum(x["volume"] for x in candles[-20:-1]) / 19

    if avg_volume <= 0:
        return 0

    return current_volume / avg_volume


def build_alert(exchange, pair, price, k, d, macd_hist, volume, vol_ratio, confidence):
    return (
        f"🟢 *Stoch RSI Alert*\n\n"
        f"🏦 المنصة: *{exchange.upper()}*\n"
        f"🪙 العملة: *{pair}*\n"
        f"💰 السعر: `{price}`\n\n"
        f"📊 Stoch RSI K: `{k:.2f}`\n"
        f"📊 Stoch RSI D: `{d:.2f}`\n"
        f"📈 MACD Histogram: `{macd_hist:.6f}`\n\n"
        f"💧 Volume: `${volume:,.0f}`\n"
        f"🔥 Volume Ratio: `{vol_ratio:.2f}X`\n"
        f"⏰ الفريم: *4H*\n"
        f"🎯 الثقة: *{confidence}%*\n\n"
        f"✅ K أعلى من D\n"
        f"✅ Stoch RSI أقل من {STOCH_MAX_K}\n"
        f"✅ Volume قوي\n"
        f"✅ Volume Ratio أعلى من {MIN_VOLUME_RATIO}X\n"
        f"{'✅ MACD إيجابي' if macd_hist > 0 else '⚠️ MACD سلبي'}\n\n"
        f"⚠️ تحليل فقط وليس نصيحة مالية"
    )


async def scanner(app):
    await asyncio.sleep(5)

    exchanges = {
        "gate": (get_pairs_gate, get_candles_gate),
        "mexc": (get_pairs_mexc, get_candles_mexc),
        "okx": (get_pairs_okx, get_candles_okx),
        "bybit": (get_pairs_bybit, get_candles_bybit),
    }

    while True:
        try:
            logger.info("🔍 Scanning 4H Stoch RSI...")

            for exchange, funcs in exchanges.items():
                get_pairs, get_candles = funcs
                pairs = get_pairs()

                logger.info(f"{exchange}: {len(pairs)} pairs")

                for pair in pairs:
                    try:
                        candles = get_candles(pair)

                        if len(candles) < 50:
                            continue

                        closes = [x["close"] for x in candles]
                        result = stoch_rsi(closes)

                        if not result:
                            continue

                        k, d = result
                        last = candles[-1]

                        price = last["close"]
                        volume = last["volume"]
                        vol_ratio = volume_ratio(candles)
                        macd_hist = macd_histogram(closes)

                        confidence = 0

                        if k > d:
                            confidence += 35

                        if k <= STOCH_MAX_K:
                            confidence += 25

                        if volume >= MIN_VOLUME_USDT:
                            confidence += 20

                        if vol_ratio >= MIN_VOLUME_RATIO:
                            confidence += 20

                        if (
                            k > d
                            and k <= STOCH_MAX_K
                            and volume >= MIN_VOLUME_USDT
                            and vol_ratio >= MIN_VOLUME_RATIO
                            and confidence >= MIN_CONFIDENCE
                            and (not REQUIRE_MACD_POSITIVE or macd_hist > 0)
                        ):
                            key = f"{exchange}_{pair}_{int(time.time() // 14400)}"

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
                                    macd_hist,
                                    volume,
                                    vol_ratio,
                                    confidence
                                ),
                                parse_mode=ParseMode.MARKDOWN
                            )

                            await asyncio.sleep(1)

                    except Exception as e:
                        logger.warning(f"{exchange} {pair} error: {e}")

        except Exception as e:
            logger.error(f"Scanner Error: {e}")

        await asyncio.sleep(CHECK_INTERVAL)


async def startup(app):
    await app.bot.send_message(
        chat_id=CHANNEL_ID,
        text="🚀 البوت شغّال — Stoch RSI 4H"
    )

    asyncio.create_task(scanner(app))


def main():
    app = ApplicationBuilder().token(BOT_TOKEN).build()
    app.post_init = startup
    logger.info("🚀 البوت شغّال!")
    app.run_polling()


if __name__ == "__main__":
    main()

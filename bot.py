import os
import logging
from datetime import datetime

import httpx
from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
)
from telegram.constants import ParseMode
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    CallbackQueryHandler,
    ContextTypes,
)

# ─────────────────────────────────────────────
# LOGGING
# ─────────────────────────────────────────────

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s"
)

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────
# ENV
# ─────────────────────────────────────────────

CMC_KEY = os.environ["CMC_API_KEY"]
BOT_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]

# ضع يوزر القناة أو ID القناة
CHANNEL_ID = os.getenv("TELEGRAM_CHANNEL_ID")

CMC_URL = "https://pro-api.coinmarketcap.com/v1/cryptocurrency/listings/latest"

# ─────────────────────────────────────────────
# FETCH COINS
# ─────────────────────────────────────────────

async def fetch_coins(limit=1000, start=1):

    params = {
        "limit": limit,
        "start": start,
        "convert": "USD",
        "sort": "market_cap",
    }

    headers = {
        "X-CMC_PRO_API_KEY": CMC_KEY,
        "Accept": "application/json",
    }

    async with httpx.AsyncClient(timeout=30) as client:

        response = await client.get(
            CMC_URL,
            params=params,
            headers=headers
        )

        response.raise_for_status()

        return response.json()["data"]

# ─────────────────────────────────────────────
# ANALYSIS
# ─────────────────────────────────────────────

def enrich(coins):

    result = []

    for c in coins:

        q = c.get("quote", {}).get("USD", {})

        h1 = q.get("percent_change_1h") or 0
        h24 = q.get("percent_change_24h") or 0
        d7 = q.get("percent_change_7d") or 0

        vol = q.get("volume_24h") or 0
        mcap = q.get("market_cap") or 1
        price = q.get("price") or 0

        rsi_raw = 50 + (h24 * 2) + (d7 * 0.5)
        rsi = max(5, min(95, rsi_raw))

        macd = h24 - (d7 / 7)

        vol_ratio = (vol / mcap) * 10 if mcap else 0

        result.append({
            "rank": c.get("cmc_rank", 0),
            "name": c.get("name"),
            "symbol": c.get("symbol"),
            "price": price,
            "h1": h1,
            "h24": h24,
            "d7": d7,
            "vol": vol,
            "mcap": mcap,
            "rsi": rsi,
            "macd": macd,
            "vol_ratio": vol_ratio,
        })

    return result

# ─────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────

def fmt_price(p):

    if p >= 1000:
        return f"${p:,.0f}"

    if p >= 1:
        return f"${p:.2f}"

    if p >= 0.01:
        return f"${p:.4f}"

    return f"${p:.8f}"

def fmt_num(n):

    if n >= 1e9:
        return f"${n/1e9:.2f}B"

    if n >= 1e6:
        return f"${n/1e6:.2f}M"

    if n >= 1e3:
        return f"${n/1e3:.2f}K"

    return f"${n:.2f}"

def pct(n):

    arrow = "🟢" if n >= 0 else "🔴"
    sign = "+" if n >= 0 else ""

    return f"{arrow} {sign}{n:.2f}%"

def rsi_label(r):

    if r < 30:
        return "ذروة بيع 🟢"

    if r > 70:
        return "ذروة شراء 🔴"

    return "محايد ⚪"

def vol_label(v):

    if v > 3:
        return "🚀 ضخم جداً"

    if v > 2:
        return "🔥 مرتفع"

    if v > 1.5:
        return "📈 جيد"

    return "⚪ طبيعي"

def coin_card(c):

    return (
        f"*#{c['rank']} {c['name']} ({c['symbol']})*\n"
        f"💰 السعر: `{fmt_price(c['price'])}`\n"
        f"⏱ 1H: {pct(c['h1'])}\n"
        f"📅 24H: {pct(c['h24'])}\n"
        f"📆 7D: {pct(c['d7'])}\n"
        f"📊 RSI: `{c['rsi']:.0f}` — {rsi_label(c['rsi'])}\n"
        f"📈 MACD: `{c['macd']:+.2f}`\n"
        f"💧 Volume: {fmt_num(c['vol'])}\n"
        f"🔥 Volume Ratio: `{c['vol_ratio']:.2f}x`\n"
        f"🏦 Market Cap: {fmt_num(c['mcap'])}"
    )

# ─────────────────────────────────────────────
# STARTUP MESSAGE
# ─────────────────────────────────────────────

async def send_startup_message(app):

    if CHANNEL_ID:

        await app.bot.send_message(
            chat_id=CHANNEL_ID,
            text=(
                "🚀 *تم تشغيل بوت كريبتو سكانر بنجاح*\n\n"
                "✅ البوت متصل الآن ويعمل\n\n"
                "📌 الأوامر:\n"
                "🔍 /scan\n"
                "📉 /oversold\n"
                "🔥 /volume\n"
                "🔎 /find BTC\n\n"
                "⚡ جاهز لتحليل العملات"
            ),
            parse_mode=ParseMode.MARKDOWN
        )

# ─────────────────────────────────────────────
# COMMANDS
# ─────────────────────────────────────────────

async def cmd_scan(update: Update, ctx: ContextTypes.DEFAULT_TYPE):

    msg = await update.message.reply_text(
        "⏳ جاري تحليل 1000 عملة..."
    )

    try:

        raw = await fetch_coins(1000)

        coins = enrich(raw)

        best = [
            c for c in coins
            if c["rsi"] < 40
            and c["macd"] > 0
            and c["vol_ratio"] > 1.2
        ]

        best = sorted(
            best,
            key=lambda x: x["vol_ratio"],
            reverse=True
        )[:10]

        now = datetime.now().strftime("%H:%M:%S")

        text = (
            f"🔍 *سكانر الفرص — {now}*\n"
            "_RSI منخفض + MACD إيجابي + حجم مرتفع_\n\n"
        )

        text += "\n\n━━━━━━━━━━━━━━━\n\n".join(
            coin_card(c)
            for c in best[:5]
        )

        keyboard = [[
            InlineKeyboardButton(
                "🔄 تحديث",
                callback_data="scan"
            )
        ]]

        await msg.edit_text(
            text,
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=InlineKeyboardMarkup(keyboard)
        )

    except Exception as e:

        await msg.edit_text(f"❌ خطأ: {e}")

async def cmd_oversold(update: Update, ctx: ContextTypes.DEFAULT_TYPE):

    msg = await update.message.reply_text(
        "⏳ جاري البحث عن ذروة البيع..."
    )

    try:

        raw = await fetch_coins(1000)

        coins = enrich(raw)

        oversold = [
            c for c in coins
            if c["rsi"] < 30
        ]

        oversold = sorted(
            oversold,
            key=lambda x: x["rsi"]
        )[:10]

        text = "📉 *ذروة البيع*\n\n"

        text += "\n\n━━━━━━━━━━━━━━━\n\n".join(
            coin_card(c)
            for c in oversold[:5]
        )

        await msg.edit_text(
            text,
            parse_mode=ParseMode.MARKDOWN
        )

    except Exception as e:

        await msg.edit_text(f"❌ خطأ: {e}")

async def cmd_volume(update: Update, ctx: ContextTypes.DEFAULT_TYPE):

    msg = await update.message.reply_text(
        "⏳ جاري تحليل الأحجام..."
    )

    try:

        raw = await fetch_coins(1000)

        coins = enrich(raw)

        top = sorted(
            coins,
            key=lambda x: x["vol_ratio"],
            reverse=True
        )[:10]

        text = "🔥 *أعلى حجم تداول*\n\n"

        text += "\n\n━━━━━━━━━━━━━━━\n\n".join(
            coin_card(c)
            for c in top[:5]
        )

        await msg.edit_text(
            text,
            parse_mode=ParseMode.MARKDOWN
        )

    except Exception as e:

        await msg.edit_text(f"❌ خطأ: {e}")

# ─────────────────────────────────────────────
# CALLBACK
# ─────────────────────────────────────────────

CALLBACK_MAP = {
    "scan": cmd_scan,
}

async def handle_callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE):

    query = update.callback_query

    await query.answer()

    update.message = query.message

    handler = CALLBACK_MAP.get(query.data)

    if handler:
        await handler(update, ctx)

# ─────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────

def main():

    app = ApplicationBuilder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("scan", cmd_scan))
    app.add_handler(CommandHandler("oversold", cmd_oversold))
    app.add_handler(CommandHandler("volume", cmd_volume))

    app.add_handler(
        CallbackQueryHandler(handle_callback)
    )

    app.post_init = send_startup_message

    logger.info("🚀 البوت شغّال!")

    app.run_polling()

if __name__ == "__main__":
    main()

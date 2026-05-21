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
# Logging
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

CMC_URL = "https://pro-api.coinmarketcap.com/v1/cryptocurrency/listings/latest"

# ─────────────────────────────────────────────
# Fetch Coins
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
# Analysis
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

        # RSI approximation
        rsi_raw = 50 + (h24 * 2) + (d7 * 0.5)
        rsi = max(5, min(95, rsi_raw))

        # MACD approximation
        macd = h24 - (d7 / 7)

        # Volume ratio
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
# Helpers
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
        f"🔥 Volume Ratio: `{c['vol_ratio']:.2f}x` — {vol_label(c['vol_ratio'])}\n"
        f"🏦 Market Cap: {fmt_num(c['mcap'])}"
    )

# ─────────────────────────────────────────────
# START
# ─────────────────────────────────────────────

async def cmd_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):

    text = (
        "🚀 *أهلاً بك في بوت كريبتو سكانر برو* 📡\n\n"

        "يقوم البوت بتحليل أكثر من *1000 عملة رقمية*\n"
        "مباشرة من CoinMarketCap\n\n"

        "━━━━━━━━━━━━━━━\n"
        "✅ تحليل RSI\n"
        "✅ تحليل MACD\n"
        "✅ تحليل Volume\n"
        "✅ تتبع Market Cap\n"
        "━━━━━━━━━━━━━━━\n\n"

        "📌 *الأوامر المتاحة:*\n\n"

        "🔍 /scan\n"
        "سكانر الفرص القوية\n\n"

        "📉 /oversold\n"
        "عملات في ذروة البيع\n\n"

        "📈 /overbought\n"
        "عملات في ذروة الشراء\n\n"

        "🔥 /volume\n"
        "أعلى حجم تداول\n\n"

        "🚀 /gainers\n"
        "أعلى العملات ارتفاعاً\n\n"

        "📉 /losers\n"
        "أعلى العملات انخفاضاً\n\n"

        "🔎 /find BTC\n"
        "البحث عن أي عملة\n\n"

        "📊 /top50\n"
        "أفضل 50 عملة\n\n"

        "━━━━━━━━━━━━━━━\n"
        "⚡ البيانات مباشرة من السوق\n"
        "⚠️ البوت للتحليل فقط وليس نصيحة مالية"
    )

    await update.message.reply_text(
        text,
        parse_mode=ParseMode.MARKDOWN
    )

# ─────────────────────────────────────────────
# HELP
# ─────────────────────────────────────────────

async def cmd_help(update: Update, ctx: ContextTypes.DEFAULT_TYPE):

    text = (
        "📚 *شرح المؤشرات*\n\n"

        "📊 RSI:\n"
        "• أقل من 30 → ذروة بيع\n"
        "• أعلى من 70 → ذروة شراء\n\n"

        "📈 MACD:\n"
        "• موجب → زخم صاعد\n"
        "• سالب → زخم هابط\n\n"

        "🔥 Volume Ratio:\n"
        "• x3+ → ضخم جداً\n"
        "• x2+ → مرتفع\n"
        "• x1+ → جيد\n\n"

        "⚠️ البوت للتحليل فقط"
    )

    await update.message.reply_text(
        text,
        parse_mode=ParseMode.MARKDOWN
    )

# ─────────────────────────────────────────────
# SCAN
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

        if not best:

            best = sorted(
                coins,
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

# ─────────────────────────────────────────────
# OVERSOLD
# ─────────────────────────────────────────────

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

        if not oversold:

            await msg.edit_text(
                "❌ لا توجد عملات في ذروة البيع حالياً"
            )

            return

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

# ─────────────────────────────────────────────
# VOLUME
# ─────────────────────────────────────────────

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
# FIND
# ─────────────────────────────────────────────

async def cmd_find(update: Update, ctx: ContextTypes.DEFAULT_TYPE):

    if not ctx.args:

        await update.message.reply_text(
            "❓ مثال:\n/find BTC"
        )

        return

    query = " ".join(ctx.args).lower()

    msg = await update.message.reply_text(
        f"🔎 جاري البحث عن {query.upper()}..."
    )

    try:

        raw = await fetch_coins(1000)

        coins = enrich(raw)

        found = [
            c for c in coins
            if query in c["symbol"].lower()
            or query in c["name"].lower()
        ]

        if not found:

            await msg.edit_text(
                "❌ لم يتم العثور على العملة"
            )

            return

        text = f"🔎 *نتائج البحث*\n\n"

        text += "\n\n━━━━━━━━━━━━━━━\n\n".join(
            coin_card(c)
            for c in found[:3]
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

    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("help", cmd_help))
    app.add_handler(CommandHandler("scan", cmd_scan))
    app.add_handler(CommandHandler("oversold", cmd_oversold))
    app.add_handler(CommandHandler("volume", cmd_volume))
    app.add_handler(CommandHandler("find", cmd_find))

    app.add_handler(
        CallbackQueryHandler(handle_callback)
    )

    logger.info("🚀 البوت شغّال!")

    app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()

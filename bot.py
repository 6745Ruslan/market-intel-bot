import os
import json
import logging
import anthropic
import base64
from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    filters,
    ContextTypes,
)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

HISTORY_FILE = "market_history.json"

SYSTEM_PROMPT = """Ты — аналитик нефтехимического рынка СНГ.
Анализируешь цены на ПП, ПЭ, газовый конденсат.
Отвечай кратко на русском. Используй цифры."""


def load_history():
    if os.path.exists(HISTORY_FILE):
        with open(HISTORY_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {"reports": [], "user_notes": []}


def save_history(history):
    with open(HISTORY_FILE, "w", encoding="utf-8") as f:
        json.dump(history, f, ensure_ascii=False, indent=2)


def build_context(history):
    if not history["reports"]:
        return "История пуста."
    ctx = f"ИСТОРИЯ ({len(history['reports'])} недель):\n\n"
    for i, r in enumerate(history["reports"][-4:], 1):
        ctx += f"Отчёт {i} ({r.get('date','?')}):\n{r.get('summary','')[:300]}\n\n"
    return ctx


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    history = load_history()
    await update.message.reply_text(
        f"👋 Привет! Я аналитик рынка.\n\n"
        f"📊 В памяти: {len(history['reports'])} отчётов\n\n"
        f"Пришлите PDF или задайте вопрос!\n\n"
        f"/summary — последний отчёт\n"
        f"/trend — тренды\n"
        f"/forecast — прогноз\n"
        f"/history — история\n"
        f"/clear — очистить"
    )


async def summary(update: Update, context: ContextTypes.DEFAULT_TYPE):
    history = load_history()
    if not history["reports"]:
        await update.message.reply_text("📭 Отчётов нет. Пришлите PDF!")
        return
    last = history["reports"][-1]
    await update.message.reply_text(
        f"📊 Последний ({last.get('date','')}):\n\n{last.get('summary','')[:3500]}"
    )


async def trend(update: Update, context: ContextTypes.DEFAULT_TYPE):
    history = load_history()
    if len(history["reports"]) < 2:
        await update.message.reply_text("Нужно минимум 2 отчёта.")
        return
    await update.message.reply_text("⏳ Анализирую тренды...")
    try:
        client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
        response = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=500,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": f"{build_context(history)}\n\nКратко покажи тренды цен за все недели. Максимум 10 строк."}]
        )
        await update.message.reply_text("📈 ТРЕНДЫ\n\n" + response.content[0].text)
    except Exception as e:
        await update.message.reply_text(f"❌ Ошибка: {str(e)[:200]}")


async def forecast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    history = load_history()
    if not history["reports"]:
        await update.message.reply_text("📭 Отчётов нет. Пришлите PDF!")
        return
    await update.message.reply_text("⏳ Готовлю прогноз...")
    try:
        client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
        response = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=500,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": f"{build_context(history)}\n\nКраткий прогноз на следующую неделю и сигнал. Максимум 8 строк."}]
        )
        await update.message.reply_text("🔮 ПРОГНОЗ\n\n" + response.content[0].text)
    except Exception as e:
        await update.message.reply_text(f"❌ Ошибка: {str(e)[:200]}")


async def history_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    history = load_history()
    if not history["reports"]:
        await update.message.reply_text("📭 История пуста.")
        return
    text = f"📅 ИСТОРИЯ ({len(history['reports'])} отчётов)\n\n"
    for i, r in enumerate(history["reports"], 1):
        text += f"{i}. {r.get('date','?')} — {r.get('source','?')}\n"
    await update.message.reply_text(text)


async def clear(update: Update, context: ContextTypes.DEFAULT_TYPE):
    save_history({"reports": [], "user_notes": []})
    await update.message.reply_text("🗑️ История очищена!")


async def handle_document(update: Update, context: ContextTypes.DEFAULT_TYPE):
    doc = update.message.document
    if doc.mime_type != "application/pdf":
        await update.message.reply_text("⚠️ Только PDF файлы.")
        return
    await update.message.reply_text(f"📥 Получил: {doc.file_name}\n⏳ Анализирую...")
    try:
        file = await context.bot.get_file(doc.file_id)
        file_bytes = await file.download_as_bytearray()
        history = load_history()
        client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
        pdf_b64 = base64.b64encode(bytes(file_bytes)).decode()
        response = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=500,
            system="Ты аналитик рынка СНГ. Отвечай кратко на русском.",
            messages=[{"role": "user", "content": [
                {"type": "document", "source": {"type": "base64", "media_type": "application/pdf", "data": pdf_b64}},
                {"type": "text", "text": "Кратко (максимум 15 строк):\n1) Дата и источник\n2) Топ-5 цен с изменениями за неделю\n3) Главное событие\n4) Тренд\n5) Сигнал: купить/держать/ждать"}
            ]}]
        )
        analysis = response.content[0].text
        history["reports"].append({
            "date": "авто",
            "source": doc.file_name,
            "filename": doc.file_name,
            "summary": analysis
        })
        save_history(history)
        num = len(history["reports"])
        await update.message.reply_text(f"✅ Отчёт #{num} сохранён\n\n{analysis}")
    except Exception as e:
        await update.message.reply_text(f"❌ Ошибка: {str(e)[:200]}")


async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    history = load_history()
    if any(k in text.lower() for k in ["запомни", "запомнить", "отметь", "сохрани"]):
        history["user_notes"].append(text)
        save_history(history)
        await update.message.reply_text(f"✅ Запомнил!\n«{text}»")
        return
    await update.message.reply_text("💭 Думаю...")
    try:
        client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
        response = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=500,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": f"{build_context(history)}\n\nВопрос: {text}"}]
        )
        await update.message.reply_text(response.content[0].text)
    except Exception as e:
        await update.message.reply_text(f"❌ Ошибка: {str(e)[:200]}")


def main():
    token = os.environ["TELEGRAM_TOKEN"]
    app = Application.builder().token(token).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("summary", summary))
    app.add_handler(CommandHandler("trend", trend))
    app.add_handler(CommandHandler("forecast", forecast))
    app.add_handler(CommandHandler("history", history_cmd))
    app.add_handler(CommandHandler("clear", clear))
    app.add_handler(MessageHandler(filters.Document.ALL, handle_document))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    logger.info("Бот запущен!")
    app.run_polling()


if __name__ == "__main__":
    main()

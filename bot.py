import os
import json
import logging
import anthropic
import base64
from telegram import Update
from telegram.ext import (
    ApplicationBuilder, CommandHandler, MessageHandler,
    filters, ContextTypes
)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

HISTORY_FILE = "market_history.json"

SYSTEM_PROMPT = """Ты — персональный аналитик нефтехимического рынка СНГ.
У тебя есть доступ к истории еженедельных отчётов пользователя.
Ты анализируешь цены на полипропилен (ПП), полиэтилен (ПЭ),
газовый конденсат и другие продукты.

При анализе отчёта извлекай:
- Все цены с изменениями за неделю
- Ключевые события рынка
- Тренды по продуктам
- Прогноз на следующую неделю
- Торговый сигнал (купить/держать/ждать)

Отвечай на русском языке. Будь конкретным, используй цифры.
Помни контекст всей истории загруженных отчётов."""


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
        return "История отчётов пуста. Это первый отчёт."
    context = f"ИСТОРИЯ ОТЧЁТОВ ({len(history['reports'])} недель):\n\n"
    for i, report in enumerate(history["reports"][-8:], 1):
        context += f"Отчёт {i} ({report.get('date', '?')}):\n"
        context += report.get("summary", "") + "\n\n"
    if history["user_notes"]:
        context += "\nЗАМЕТКИ ПОЛЬЗОВАТЕЛЯ:\n"
        for note in history["user_notes"]:
            context += f"• {note}\n"
    return context


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    history = load_history()
    count = len(history["reports"])
    text = f"""👋 Привет! Я ваш персональный аналитик рынка.

📊 В памяти: {count} отчётов

Что я умею:
• Анализировать PDF отчёты
• Отслеживать тренды цен по неделям
• Давать прогнозы и торговые сигналы
• Отвечать на любые вопросы о рынке

Просто пришлите PDF отчёт или задайте вопрос! 🚀"""
    await update.message.reply_text(text)


async def summary(update: Update, context: ContextTypes.DEFAULT_TYPE):
    history = load_history()
    if not history["reports"]:
        await update.message.reply_text("📭 Отчётов пока нет. Пришлите PDF!")
        return
    last = history["reports"][-1]
    await update.message.reply_text(
        f"📊 Последний отчёт ({last.get('date', '')}):\n\n{last.get('summary', 'Нет данных')}"
    )


async def trend(update: Update, context: ContextTypes.DEFAULT_TYPE):
    history = load_history()
    if len(history["reports"]) < 2:
        await update.message.reply_text(
            f"📈 Нужно минимум 2 отчёта.\nСейчас: {len(history['reports'])}"
        )
        return
    await update.message.reply_text("⏳ Анализирую тренды...")
    client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    ctx = build_context(history)
    response = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=1000,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": f"{ctx}\n\nПокажи тренды цен за все недели. По каждому продукту: изменение в % и направление."}]
    )
    await update.message.reply_text("📈 ТРЕНДЫ\n\n" + response.content[0].text)


async def forecast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    history = load_history()
    if not history["reports"]:
        await update.message.reply_text("📭 Отчётов пока нет. Пришлите PDF!")
        return
    await update.message.reply_text("⏳ Готовлю прогноз...")
    client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    ctx = build_context(history)
    response = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=1000,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": f"{ctx}\n\nДай прогноз на следующую неделю и торговый сигнал."}]
    )
    await update.message.reply_text("🔮 ПРОГНОЗ\n\n" + response.content[0].text)


async def history_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    history = load_history()
    if not history["reports"]:
        await update.message.reply_text("📭 История пуста.")
        return
    text = f"📅 ИСТОРИЯ ({len(history['reports'])} отчётов)\n\n"
    for i, report in enumerate(history["reports"], 1):
        text += f"{i}. {report.get('date', '?')} — {report.get('source', 'отчёт')}\n"
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
    file = await context.bot.get_file(doc.file_id)
    file_bytes = await file.download_as_bytearray()
    history = load_history()
    ctx = build_context(history)
    client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    pdf_base64 = base64.b64encode(bytes(file_bytes)).decode("utf-8")
    response = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=1000,
        system=SYSTEM_PROMPT,
        messages=[{
            "role": "user",
            "content": [
                {"type": "document", "source": {"type": "base64", "media_type": "application/pdf", "data": pdf_base64}},
                {"type": "text", "text": f"КОНТЕКСТ:\n{ctx}\n\nПроанализируй отчёт: цены, события, тренд, прогноз, торговый сигнал."}
            ]
        }]
    )
    analysis = response.content[0].text
    meta = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=100,
        messages=[{
            "role": "user",
            "content": [
                {"type": "document", "source": {"type": "base64", "media_type": "application/pdf", "data": pdf_base64}},
                {"type": "text", "text": "Только дата и источник: ДАТА: дд.мм.гггг | ИСТОЧНИК: название"}
            ]
        }]
    ).content[0].text
    date, source = "?", doc.file_name
    if "ДАТА:" in meta:
        parts = meta.split("|")
        date = parts[0].replace("ДАТА:", "").strip()
        if len(parts) > 1:
            source = parts[1].replace("ИСТОЧНИК:", "").strip()
    history["reports"].append({"date": date, "source": source, "filename": doc.file_name, "summary": analysis})
    save_history(history)
    num = len(history["reports"])
    full = f"✅ Отчёт #{num} сохранён\n📅 {date} · {source}\n🧠 В памяти: {num} отчётов\n\n{analysis}"
    if len(full) > 4000:
        await update.message.reply_text(full[:4000])
        await update.message.reply_text(full[4000:8000])
    else:
        await update.message.reply_text(full)


async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_text = update.message.text
    history = load_history()
    if any(kw in user_text.lower() for kw in ["запомни", "запомнить", "отметь", "сохрани"]):
        history["user_notes"].append(user_text)
        save_history(history)
        await update.message.reply_text(f"✅ Запомнил!\n\n«{user_text}»")
        return
    await update.message.reply_text("💭 Думаю...")
    client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    ctx = build_context(history)
    response = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=1000,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": f"{ctx}\n\nВопрос: {user_text}"}]
    )
    await update.message.reply_text(response.content[0].text)


def main():
    token = os.environ["TELEGRAM_TOKEN"]
    app = ApplicationBuilder().token(token).build()
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

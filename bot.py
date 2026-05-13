import os
import json
import logging
import anthropic
from telegram import Update
from telegram.ext import (
    Application, CommandHandler, MessageHandler, 
    filters, ContextTypes
)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Файл для хранения истории
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
    """Загрузить историю отчётов"""
    if os.path.exists(HISTORY_FILE):
        with open(HISTORY_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {"reports": [], "user_notes": []}


def save_history(history):
    """Сохранить историю отчётов"""
    with open(HISTORY_FILE, "w", encoding="utf-8") as f:
        json.dump(history, f, ensure_ascii=False, indent=2)


def build_context(history):
    """Собрать контекст из истории для Claude"""
    if not history["reports"]:
        return "История отчётов пуста. Это первый отчёт."
    
    context = f"ИСТОРИЯ ОТЧЁТОВ ({len(history['reports'])} недель):\n\n"
    for i, report in enumerate(history["reports"][-8:], 1):
        context += f"Отчёт {i} ({report.get('date', 'дата неизвестна')}):\n"
        context += report.get("summary", "") + "\n\n"
    
    if history["user_notes"]:
        context += "\nЗАМЕТКИ ПОЛЬЗОВАТЕЛЯ:\n"
        for note in history["user_notes"]:
            context += f"• {note}\n"
    
    return context


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда /start"""
    history = load_history()
    count = len(history["reports"])
    
    text = f"""👋 Привет! Я ваш персональный аналитик рынка.

📊 В памяти: {count} отчётов

Что я умею:
• Анализировать PDF отчёты (Маркет Репорт, Argus, Platts)
• Отслеживать тренды цен по неделям
• Давать прогнозы и торговые сигналы
• Отвечать на любые вопросы о рынке

Просто пришлите PDF отчёт или задайте вопрос! 🚀"""
    
    await update.message.reply_text(text)


async def summary(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда /summary — резюме последнего отчёта"""
    history = load_history()
    
    if not history["reports"]:
        await update.message.reply_text(
            "📭 Отчётов пока нет. Пришлите PDF!"
        )
        return
    
    last = history["reports"][-1]
    await update.message.reply_text(
        f"📊 Последний отчёт ({last.get('date', '')}):\n\n"
        f"{last.get('summary', 'Нет данных')}"
    )


async def trend(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда /trend — тренды за все недели"""
    history = load_history()
    
    if len(history["reports"]) < 2:
        await update.message.reply_text(
            "📈 Нужно минимум 2 отчёта для анализа тренда.\n"
            f"Сейчас загружено: {len(history['reports'])}"
        )
        return
    
    await update.message.reply_text("⏳ Анализирую тренды...")
    
    client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    ctx = build_context(history)
    
    response = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=1000,
        system=SYSTEM_PROMPT,
        messages=[{
            "role": "user",
            "content": f"{ctx}\n\nПокажи тренды цен за все недели. "
                      f"По каждому продукту: изменение в % и направление. "
                      f"Что выросло больше всего? Что снизилось?"
        }]
    )
    
    await update.message.reply_text(
        "📈 ТРЕНДЫ\n\n" + response.content[0].text
    )


async def forecast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда /forecast — прогноз"""
    history = load_history()
    
    if not history["reports"]:
        await update.message.reply_text(
            "📭 Отчётов пока нет. Пришлите PDF!"
        )
        return
    
    await update.message.reply_text("⏳ Готовлю прогноз...")
    
    client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    ctx = build_context(history)
    
    response = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=1000,
        system=SYSTEM_PROMPT,
        messages=[{
            "role": "user", 
            "content": f"{ctx}\n\nДай прогноз на следующую неделю. "
                      f"По каждому продукту: направление цены и причина. "
                      f"Торговый сигнал: купить/держать/ждать."
        }]
    )
    
    await update.message.reply_text(
        "🔮 ПРОГНОЗ\n\n" + response.content[0].text
    )


async def history_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда /history — хронология"""
    history = load_history()
    
    if not history["reports"]:
        await update.message.reply_text(
            "📭 История пуста. Пришлите PDF!"
        )
        return
    
    text = f"📅 ИСТОРИЯ ({len(history['reports'])} отчётов)\n\n"
    for i, report in enumerate(history["reports"], 1):
        text += f"{i}. {report.get('date', '?')} — "
        text += f"{report.get('source', 'отчёт')}\n"
        # Добавляем первые 100 символов резюме
        summary_text = report.get('summary', '')[:100]
        if summary_text:
            text += f"   {summary_text}...\n"
        text += "\n"
    
    await update.message.reply_text(text)


async def clear(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда /clear — очистить историю"""
    save_history({"reports": [], "user_notes": []})
    await update.message.reply_text(
        "🗑️ История очищена. Загрузите новые отчёты!"
    )


async def handle_document(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка PDF файлов"""
    doc = update.message.document
    
    if not doc.mime_type == "application/pdf":
        await update.message.reply_text(
            "⚠️ Поддерживаются только PDF файлы."
        )
        return
    
    await update.message.reply_text(
        f"📥 Получил файл: {doc.file_name}\n⏳ Анализирую..."
    )
    
    # Скачиваем файл
    file = await context.bot.get_file(doc.file_id)
    file_bytes = await file.download_as_bytearray()
    
    # Загружаем историю
    history = load_history()
    ctx = build_context(history)
    
    # Отправляем в Claude
    client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    
    import base64
    pdf_base64 = base64.b64encode(bytes(file_bytes)).decode("utf-8")
    
    response = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=1000,
        system=SYSTEM_PROMPT,
        messages=[{
            "role": "user",
            "content": [
                {
                    "type": "document",
                    "source": {
                        "type": "base64",
                        "media_type": "application/pdf",
                        "data": pdf_base64
                    }
                },
                {
                    "type": "text",
                    "text": f"КОНТЕКСТ ПРЕДЫДУЩИХ ОТЧЁТОВ:\n{ctx}\n\n"
                           f"Проанализируй этот новый отчёт. Извлеки:\n"
                           f"1. Источник и дату отчёта\n"
                           f"2. Все цены с изменениями за неделю\n"
                           f"3. Ключевые события\n"
                           f"4. Сравнение с предыдущими неделями\n"
                           f"5. Тренд и прогноз\n"
                           f"6. Торговый сигнал"
                }
            ]
        }]
    )
    
    analysis = response.content[0].text
    
    # Извлекаем метаданные
    meta_response = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=200,
        messages=[{
            "role": "user",
            "content": [
                {
                    "type": "document", 
                    "source": {
                        "type": "base64",
                        "media_type": "application/pdf",
                        "data": pdf_base64
                    }
                },
                {
                    "type": "text",
                    "text": "Извлеки только: дату отчёта (формат ДД.ММ.ГГГГ) "
                           "и источник (название издания). "
                           "Ответь строго в формате: ДАТА: xx.xx.xxxx | ИСТОЧНИК: название"
                }
            ]
        }]
    )
    
    meta = meta_response.content[0].text
    date = "неизвестно"
    source = doc.file_name
    
    if "ДАТА:" in meta:
        parts = meta.split("|")
        if len(parts) >= 1:
            date = parts[0].replace("ДАТА:", "").strip()
        if len(parts) >= 2:
            source = parts[1].replace("ИСТОЧНИК:", "").strip()
    
    # Сохраняем в историю
    history["reports"].append({
        "date": date,
        "source": source,
        "filename": doc.file_name,
        "summary": analysis
    })
    save_history(history)
    
    # Отправляем ответ
    report_num = len(history["reports"])
    header = f"✅ Отчёт #{report_num} сохранён\n"
    header += f"📅 {date} · {source}\n"
    header += f"🧠 В памяти: {report_num} отчётов\n\n"
    
    full_text = header + analysis
    
    # Telegram лимит 4096 символов
    if len(full_text) > 4000:
        await update.message.reply_text(full_text[:4000] + "...")
        await update.message.reply_text(full_text[4000:8000] if len(full_text) > 4000 else "")
    else:
        await update.message.reply_text(full_text)


async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка текстовых сообщений — разговор с ботом"""
    user_text = update.message.text
    
    # Проверяем — это заметка для запоминания?
    remember_keywords = ["запомни", "запомнить", "отметь", "сохрани"]
    is_note = any(kw in user_text.lower() for kw in remember_keywords)
    
    history = load_history()
    
    if is_note:
        history["user_notes"].append(user_text)
        save_history(history)
        await update.message.reply_text(
            f"✅ Запомнил!\n\n«{user_text}»\n\n"
            f"Буду учитывать при анализе."
        )
        return
    
    # Обычный вопрос — отвечаем с контекстом истории
    await update.message.reply_text("💭 Думаю...")
    
    ctx = build_context(history)
    client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    
    response = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=1000,
        system=SYSTEM_PROMPT,
        messages=[{
            "role": "user",
            "content": f"{ctx}\n\nВопрос пользователя: {user_text}"
        }]
    )
    
    await update.message.reply_text(response.content[0].text)


def main():
    """Запуск бота"""
    token = os.environ["TELEGRAM_TOKEN"]
    
    app = Application.builder().token(token).build()
    
    # Команды
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("summary", summary))
    app.add_handler(CommandHandler("trend", trend))
    app.add_handler(CommandHandler("forecast", forecast))
    app.add_handler(CommandHandler("history", history_cmd))
    app.add_handler(CommandHandler("clear", clear))
    
    # Файлы и текст
    app.add_handler(MessageHandler(filters.Document.ALL, handle_document))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    
    logger.info("Бот запущен!")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()

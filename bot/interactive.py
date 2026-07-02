import os
import json
import time
import logging
import requests
from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.environ["BOT_TOKEN"]
CHANNEL_ID = os.environ["CHANNEL_ID"]
ANTHROPIC_API_KEY = os.environ["ANTHROPIC_API_KEY"]

API_URL = f"https://api.telegram.org/bot{BOT_TOKEN}"

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
log = logging.getLogger(__name__)

TOV = """
Ты редактор Telegram-канала о вине «Шепот виноградной лозы». Пишешь посты для российской аудитории любителей вина.

Голос: экспертный, живой, без пафоса. Пишет человек, который знает предмет и не пытается этим давить.

Структура поста:
- Начало с конкретного факта, события, места. Не с определения, не с общей фразы
- Технические детали как факты, без педагогики
- Акцент на вкус и аромат: что конкретно почувствуешь в бокале
- Текст просто заканчивается, без вывода-морали

Пунктуация:
- В конце абзаца ничего (ни точки, ни скобки)
- Тире (—) не использовать. Вместо него двоеточие, новое предложение или запятая
- Многоточие только если задумчивость или незавершённость мысли

Запрещено:
- AI-штампы: «по сути», «в целом», «фактически», «стоит отметить», «важно понимать», «на самом деле» как вводное
- Канцелярит
- Call-to-action в конце
- Финальные афоризмы
- Антитезы и противопоставления: «если X — это мощь, то Y — это элегантность»
- Восторженные прилагательные без контекста

Формат: 500–900 символов, без эмодзи, без хэштегов.
"""

# Хранилище состояний: {chat_id: {"variants": [...], "idea": "..."}}
state: dict = {}


def tg(method: str, **kwargs) -> dict:
    resp = requests.post(f"{API_URL}/{method}", json=kwargs, timeout=10)
    return resp.json()


def generate_variants(idea: str) -> list[str]:
    prompt = f"""Напиши три варианта поста для Telegram-канала о вине на тему: «{idea}»

Каждый вариант должен быть написан в разной манере (например: один более фактический, один через конкретный опыт, один через сравнение с другим вином/регионом), но все три в одном ToV.

Верни ровно три варианта, разделённых строкой "---".
Никаких заголовков, нумерации и пояснений — только тексты постов."""

    resp = requests.post(
        "https://api.anthropic.com/v1/messages",
        headers={
            "x-api-key": ANTHROPIC_API_KEY,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        },
        json={
            "model": "claude-sonnet-4-6",
            "max_tokens": 2000,
            "system": TOV,
            "messages": [{"role": "user", "content": prompt}],
        },
        timeout=60,
    )
    text = resp.json()["content"][0]["text"]
    variants = [v.strip() for v in text.split("---") if v.strip()]
    return variants[:3]


def send_variants(chat_id: int, variants: list[str]) -> None:
    for i, text in enumerate(variants, 1):
        tg("sendMessage", chat_id=chat_id, text=f"Вариант {i}:\n\n{text}")
        time.sleep(0.5)

    keyboard = {
        "inline_keyboard": [
            [
                {"text": "Вариант 1", "callback_data": "pick_0"},
                {"text": "Вариант 2", "callback_data": "pick_1"},
                {"text": "Вариант 3", "callback_data": "pick_2"},
            ],
            [{"text": "Написать ещё раз", "callback_data": "retry"}],
        ]
    }
    tg(
        "sendMessage",
        chat_id=chat_id,
        text="Выбери вариант для публикации или попроси написать заново:",
        reply_markup=keyboard,
    )


def publish(text: str) -> bool:
    resp = requests.post(
        f"{API_URL}/sendMessage",
        json={"chat_id": CHANNEL_ID, "text": text, "parse_mode": "HTML"},
        timeout=10,
    )
    return resp.ok


def handle_message(msg: dict) -> None:
    chat_id = msg["chat"]["id"]
    text = msg.get("text", "").strip()

    if not text or text.startswith("/"):
        if text == "/start":
            tg("sendMessage", chat_id=chat_id, text="Привет! Напиши идею поста, и я предложу три варианта.")
        return

    log.info(f"Идея от {chat_id}: {text}")
    tg("sendMessage", chat_id=chat_id, text="Генерирую три варианта...")

    try:
        variants = generate_variants(text)
        state[chat_id] = {"idea": text, "variants": variants}
        send_variants(chat_id, variants)
    except Exception as e:
        log.error(f"Ошибка генерации: {e}")
        tg("sendMessage", chat_id=chat_id, text="Что-то пошло не так. Попробуй ещё раз.")


def handle_callback(cb: dict) -> None:
    chat_id = cb["message"]["chat"]["id"]
    data = cb["data"]
    callback_id = cb["id"]

    tg("answerCallbackQuery", callback_query_id=callback_id)

    if data == "retry":
        idea = state.get(chat_id, {}).get("idea")
        if not idea:
            tg("sendMessage", chat_id=chat_id, text="Напиши идею заново.")
            return
        tg("sendMessage", chat_id=chat_id, text="Генерирую новые варианты...")
        try:
            variants = generate_variants(idea)
            state[chat_id]["variants"] = variants
            send_variants(chat_id, variants)
        except Exception as e:
            log.error(f"Ошибка генерации: {e}")
            tg("sendMessage", chat_id=chat_id, text="Что-то пошло не так. Попробуй ещё раз.")
        return

    if data.startswith("pick_"):
        idx = int(data.split("_")[1])
        variants = state.get(chat_id, {}).get("variants", [])
        if idx >= len(variants):
            tg("sendMessage", chat_id=chat_id, text="Вариант не найден.")
            return

        chosen = variants[idx]
        if publish(chosen):
            tg("sendMessage", chat_id=chat_id, text=f"Опубликовано в канал!")
            log.info(f"Опубликован вариант {idx + 1} от {chat_id}")
            state.pop(chat_id, None)
        else:
            tg("sendMessage", chat_id=chat_id, text="Ошибка публикации. Попробуй ещё раз.")


def main() -> None:
    log.info("Бот запущен")
    offset = 0

    while True:
        try:
            resp = tg("getUpdates", offset=offset, timeout=30)
            updates = resp.get("result", [])

            for update in updates:
                offset = update["update_id"] + 1
                if "message" in update:
                    handle_message(update["message"])
                elif "callback_query" in update:
                    handle_callback(update["callback_query"])

        except Exception as e:
            log.error(f"Ошибка polling: {e}")
            time.sleep(5)


if __name__ == "__main__":
    main()

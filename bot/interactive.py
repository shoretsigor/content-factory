import os
import time
import logging
import shutil
from pathlib import Path
from datetime import date

import requests
from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.environ["BOT_TOKEN"]
CHANNEL_ID = os.environ["CHANNEL_ID"]
ANTHROPIC_API_KEY = os.environ["ANTHROPIC_API_KEY"]

API_URL = f"https://api.telegram.org/bot{BOT_TOKEN}"
POSTS_DIR = Path(__file__).parent.parent / "posts"
PUBLISHED_DIR = Path(__file__).parent.parent / "published"

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

# State per chat_id
# mode: "idle" | "review" | "awaiting_edit" | "awaiting_idea"
# current_post: str
# current_file: Path | None
# variants: list[str]
state: dict = {}


def tg(method: str, **kwargs) -> dict:
    http_timeout = kwargs.get("timeout", 10) + 5
    resp = requests.post(f"{API_URL}/{method}", json=kwargs, timeout=http_timeout)
    return resp.json()


def get_next_post() -> tuple[str, Path] | tuple[None, None]:
    """Find the next ready post file sorted by date."""
    files = sorted(POSTS_DIR.glob("*.md"))
    today = date.today().isoformat()
    for f in files:
        content = f.read_text()
        if "status: ready" in content:
            name = f.stem
            post_date = name[:10]
            if post_date <= today:
                body = content.split("---", 2)[-1].strip()
                return body, f
    # If no past/today posts, return nearest future one
    for f in files:
        content = f.read_text()
        if "status: ready" in content:
            body = content.split("---", 2)[-1].strip()
            return body, f
    return None, None


def apply_edits(original: str, edits: str) -> str:
    """Use Claude to apply user's edit instructions to the post."""
    resp = requests.post(
        "https://api.anthropic.com/v1/messages",
        headers={
            "x-api-key": ANTHROPIC_API_KEY,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        },
        json={
            "model": "claude-sonnet-4-6",
            "max_tokens": 1500,
            "system": TOV,
            "messages": [
                {
                    "role": "user",
                    "content": f"Вот пост:\n\n{original}\n\nВнеси следующие правки: {edits}\n\nВерни только исправленный текст поста, без пояснений.",
                }
            ],
        },
        timeout=60,
    )
    return resp.json()["content"][0]["text"].strip()


def generate_variants(idea: str) -> list[str]:
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
            "messages": [
                {
                    "role": "user",
                    "content": f"Напиши три варианта поста для Telegram-канала о вине на тему: «{idea}»\n\nКаждый вариант в разной манере, но все три в одном ToV.\n\nВерни ровно три варианта, разделённых строкой \"---\".\nНикаких заголовков, нумерации и пояснений — только тексты постов.",
                }
            ],
        },
        timeout=60,
    )
    text = resp.json()["content"][0]["text"]
    variants = [v.strip() for v in text.split("---") if v.strip()]
    return variants[:3]


def send_review_keyboard(chat_id: int, text: str) -> None:
    keyboard = {
        "inline_keyboard": [
            [
                {"text": "Опубликовать", "callback_data": "publish"},
                {"text": "Редактировать", "callback_data": "edit"},
            ]
        ]
    }
    tg("sendMessage", chat_id=chat_id, text=text, reply_markup=keyboard)


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
            [{"text": "Написать заново", "callback_data": "retry"}],
        ]
    }
    tg("sendMessage", chat_id=chat_id, text="Выбери вариант:", reply_markup=keyboard)


def publish_post(text: str, post_file: Path | None) -> bool:
    resp = requests.post(
        f"{API_URL}/sendMessage",
        json={"chat_id": CHANNEL_ID, "text": text, "parse_mode": "HTML"},
        timeout=10,
    )
    if resp.ok and post_file and post_file.exists():
        content = post_file.read_text()
        content = content.replace("status: ready", "status: published")
        dest = PUBLISHED_DIR / post_file.name
        PUBLISHED_DIR.mkdir(exist_ok=True)
        dest.write_text(content)
        post_file.unlink()
        log.info(f"Опубликован и перемещён: {post_file.name}")
    return resp.ok


def handle_message(msg: dict) -> None:
    chat_id = msg["chat"]["id"]
    text = msg.get("text", "").strip()
    s = state.setdefault(chat_id, {"mode": "idle"})

    if text == "/start":
        tg(
            "sendMessage",
            chat_id=chat_id,
            text="Привет!\n\n/next — следующий пост из контент-плана\n/idea — написать пост по идее",
        )
        return

    if text == "/next":
        tg("sendMessage", chat_id=chat_id, text="Ищу следующий пост...")
        post_text, post_file = get_next_post()
        if not post_text:
            tg("sendMessage", chat_id=chat_id, text="Нет постов со статусом ready.")
            return
        s["mode"] = "review"
        s["current_post"] = post_text
        s["current_file"] = post_file
        send_review_keyboard(chat_id, post_text)
        return

    if text == "/idea":
        s["mode"] = "awaiting_idea"
        tg("sendMessage", chat_id=chat_id, text="Напиши идею поста:")
        return

    if s["mode"] == "awaiting_edit":
        tg("sendMessage", chat_id=chat_id, text="Применяю правки...")
        try:
            updated = apply_edits(s["current_post"], text)
            s["current_post"] = updated
            s["mode"] = "review"
            send_review_keyboard(chat_id, updated)
        except Exception as e:
            log.error(f"Ошибка правки: {e}")
            tg("sendMessage", chat_id=chat_id, text="Что-то пошло не так. Попробуй ещё раз.")
        return

    if s["mode"] == "awaiting_idea":
        tg("sendMessage", chat_id=chat_id, text="Генерирую три варианта...")
        try:
            variants = generate_variants(text)
            s["variants"] = variants
            s["current_file"] = None
            s["mode"] = "idle"
            send_variants(chat_id, variants)
        except Exception as e:
            log.error(f"Ошибка генерации: {e}")
            tg("sendMessage", chat_id=chat_id, text="Что-то пошло не так. Попробуй ещё раз.")
        return


def handle_callback(cb: dict) -> None:
    chat_id = cb["message"]["chat"]["id"]
    data = cb["data"]
    tg("answerCallbackQuery", callback_query_id=cb["id"])

    s = state.setdefault(chat_id, {"mode": "idle"})

    if data == "publish":
        post_text = s.get("current_post")
        post_file = s.get("current_file")
        if not post_text:
            tg("sendMessage", chat_id=chat_id, text="Нет поста для публикации.")
            return
        if publish_post(post_text, post_file):
            tg("sendMessage", chat_id=chat_id, text="Опубликовано!")
            state[chat_id] = {"mode": "idle"}
        else:
            tg("sendMessage", chat_id=chat_id, text="Ошибка публикации.")
        return

    if data == "edit":
        s["mode"] = "awaiting_edit"
        tg("sendMessage", chat_id=chat_id, text="Напиши правки, и я применю их к тексту:")
        return

    if data == "retry":
        idea = s.get("idea")
        if not idea:
            s["mode"] = "awaiting_idea"
            tg("sendMessage", chat_id=chat_id, text="Напиши идею заново:")
            return
        tg("sendMessage", chat_id=chat_id, text="Генерирую новые варианты...")
        try:
            variants = generate_variants(idea)
            s["variants"] = variants
            send_variants(chat_id, variants)
        except Exception as e:
            log.error(e)
            tg("sendMessage", chat_id=chat_id, text="Что-то пошло не так.")
        return

    if data.startswith("pick_"):
        idx = int(data.split("_")[1])
        variants = s.get("variants", [])
        if idx >= len(variants):
            tg("sendMessage", chat_id=chat_id, text="Вариант не найден.")
            return
        chosen = variants[idx]
        s["current_post"] = chosen
        s["mode"] = "review"
        send_review_keyboard(chat_id, f"Выбран вариант {idx + 1}:\n\n{chosen}")
        return


def main() -> None:
    log.info("Бот запущен")
    deleted = tg("deleteWebhook", drop_pending_updates=False)
    if not deleted.get("ok"):
        log.error(f"Не удалось снять webhook: {deleted}")

    offset = 0
    while True:
        try:
            resp = tg("getUpdates", offset=offset, timeout=30)
            if not resp.get("ok"):
                log.error(f"Telegram API вернул ошибку: {resp}")
                time.sleep(5)
                continue
            for update in resp.get("result", []):
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

import os
import re
import shutil
from datetime import date, datetime
from pathlib import Path

import requests
import yaml
from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.environ["BOT_TOKEN"]
CHANNEL_ID = os.environ["CHANNEL_ID"]

ROOT = Path(__file__).parent.parent
POSTS_DIR = ROOT / "posts"
PUBLISHED_DIR = ROOT / "published"
CONFIG_PATH = ROOT / "channel.yml"

IMAGE_EXTENSIONS = (".jpg", ".jpeg", ".png", ".webp")
SLOTS = ("main", "companion")

# Лимиты Telegram: подпись к фото сильно короче обычного сообщения, а посты
# по редполитике длиннее подписи, поэтому фото и текст уходят раздельно.
TEXT_LIMIT = 4096
CAPTION_LIMIT = 1024


def load_config() -> dict:
    return yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8"))


def get_slot() -> str:
    slot = os.environ.get("SLOT")
    if slot not in SLOTS:
        raise ValueError(f"SLOT должен быть main или companion, получено: {slot!r}")
    return slot


def get_date() -> date:
    override = os.environ.get("DATE")
    if override:
        return datetime.strptime(override, "%Y-%m-%d").date()
    return date.today()


def is_active_day(day: date, config: dict) -> bool:
    delta = (day - config["start_date"]).days
    return delta >= 0 and delta % config["publication_day_interval"] == 0


def parse_post(path: Path) -> tuple[str, dict]:
    text = path.read_text(encoding="utf-8")
    match = re.match(r"^---\n(.*?)\n---\n", text, flags=re.DOTALL)
    if not match:
        raise ValueError(f"Нет frontmatter: {path.name}")
    return text[match.end():].strip(), yaml.safe_load(match.group(1)) or {}


def find_image(post_path: Path) -> Path | None:
    for ext in IMAGE_EXTENSIONS:
        img = post_path.with_suffix(ext)
        if img.exists():
            return img
    return None


def api(method: str, **kwargs) -> dict | None:
    resp = requests.post(
        f"https://api.telegram.org/bot{BOT_TOKEN}/{method}", timeout=30, **kwargs
    )
    if resp.ok:
        return resp.json().get("result", {})
    print(f"✗ Telegram {method}: {resp.status_code} {resp.text[:300]}")
    return None


def send_message(text: str, image: Path | None) -> dict | None:
    if len(text) > TEXT_LIMIT:
        print(f"✗ Текст {len(text)} знаков, лимит Telegram {TEXT_LIMIT}")
        return None

    if image is None:
        return api("sendMessage", json={"chat_id": CHANNEL_ID, "text": text, "parse_mode": "HTML"})

    with image.open("rb") as f:
        if len(text) <= CAPTION_LIMIT:
            return api(
                "sendPhoto",
                data={"chat_id": CHANNEL_ID, "caption": text, "parse_mode": "HTML"},
                files={"photo": f},
            )
        if api("sendPhoto", data={"chat_id": CHANNEL_ID}, files={"photo": f}) is None:
            return None
    return api("sendMessage", json={"chat_id": CHANNEL_ID, "text": text, "parse_mode": "HTML"})


def record_publication(path: Path, result: dict) -> None:
    """Пишет факт публикации обратно во frontmatter: published/ служит журналом канала."""
    content = path.read_text(encoding="utf-8")
    content = content.replace("status: ready", "status: published", 1)
    stamp = (
        f"published_at: {datetime.now().astimezone().isoformat(timespec='seconds')}\n"
        f"published_message_id: {result.get('message_id')}\n"
    )
    content = re.sub(r"\n---\n", f"\n{stamp}---\n", content, count=1)
    path.write_text(content, encoding="utf-8")


def archive(post_path: Path, image: Path | None) -> None:
    PUBLISHED_DIR.mkdir(exist_ok=True)
    shutil.move(str(post_path), str(PUBLISHED_DIR / post_path.name))
    if image:
        shutil.move(str(image), str(PUBLISHED_DIR / image.name))


def main():
    config = load_config()
    slot = get_slot()
    day = get_date()

    if not is_active_day(day, config):
        print(f"{day} — не публикационный день, пропускаем")
        return

    post_path = POSTS_DIR / f"{day}-{slot}.md"
    if not post_path.exists():
        if slot == "companion":
            print(f"Дополнения на {day} нет — штатный пропуск")
        else:
            print(f"✗ Нет основного поста на {day}: {post_path.name}")
        return

    body, meta = parse_post(post_path)
    if meta.get("status") != "ready":
        print(f"Статус {meta.get('status')!r}, не публикуем: {post_path.name}")
        return

    image = find_image(post_path)
    result = send_message(body, image)
    if result is None:
        print(f"✗ Ошибка публикации: {post_path.name}")
        exit(1)

    record_publication(post_path, result)
    archive(post_path, image)
    print(f"✓ Опубликован {slot} {day}: {meta.get('wine', '?')} ({len(body)} знаков)")


if __name__ == "__main__":
    main()

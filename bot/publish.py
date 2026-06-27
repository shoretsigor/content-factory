import os
import re
import shutil
from datetime import date, datetime, timezone
from pathlib import Path

import requests
from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.environ["BOT_TOKEN"]
CHANNEL_ID = os.environ["CHANNEL_ID"]
POSTS_DIR = Path(__file__).parent.parent / "posts"
PUBLISHED_DIR = Path(__file__).parent.parent / "published"

IMAGE_EXTENSIONS = (".jpg", ".jpeg", ".png", ".webp")


def get_slot() -> str:
    """Определяет слот по переменной окружения или текущему UTC-часу."""
    slot = os.environ.get("SLOT")
    if slot in ("1", "2"):
        return slot
    hour = datetime.now(timezone.utc).hour
    return "2" if hour >= 10 else "1"


def parse_post(path: Path) -> tuple[str, dict]:
    text = path.read_text(encoding="utf-8")
    body = re.sub(r"^---\n.*?---\n", "", text, flags=re.DOTALL).strip()
    meta = {}
    for line in re.findall(r"^(\w+):\s*(.+)$", text[:200], re.MULTILINE):
        meta[line[0]] = line[1].strip()
    return body, meta


def find_image(post_path: Path) -> Path | None:
    for ext in IMAGE_EXTENSIONS:
        img = post_path.with_suffix(ext)
        if img.exists():
            return img
    return None


def send_message(text: str, image: Path | None = None) -> bool:
    if image:
        url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendPhoto"
        with image.open("rb") as f:
            resp = requests.post(
                url,
                data={"chat_id": CHANNEL_ID, "caption": text, "parse_mode": "HTML"},
                files={"photo": f},
                timeout=30,
            )
    else:
        url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
        resp = requests.post(url, json={"chat_id": CHANNEL_ID, "text": text, "parse_mode": "HTML"}, timeout=30)
    return resp.ok


def update_status(path: Path) -> None:
    content = path.read_text(encoding="utf-8")
    content = content.replace("status: ready", "status: published")
    path.write_text(content, encoding="utf-8")


def archive(post_path: Path, image: Path | None) -> None:
    PUBLISHED_DIR.mkdir(exist_ok=True)
    shutil.move(str(post_path), str(PUBLISHED_DIR / post_path.name))
    if image:
        shutil.move(str(image), str(PUBLISHED_DIR / image.name))


def main():
    today = date.today().isoformat()
    slot = get_slot()
    filename = f"{today}-{slot}.md"
    post_path = POSTS_DIR / filename

    if not post_path.exists():
        print(f"Нет поста для слота {slot}: {filename}")
        return

    body, meta = parse_post(post_path)
    if meta.get("status") != "ready":
        print(f"Статус не ready: {filename}")
        return
    image = find_image(post_path)

    if send_message(body, image):
        update_status(post_path)
        archive(post_path, image)
        label = f"с фото ({image.name})" if image else "без фото"
        print(f"✓ Опубликован слот {slot} {label}: {filename}")
    else:
        print(f"✗ Ошибка публикации: {filename}")
        exit(1)


if __name__ == "__main__":
    main()

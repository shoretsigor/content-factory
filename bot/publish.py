import os
import re
import shutil
from pathlib import Path
from datetime import date

import requests
from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.environ["BOT_TOKEN"]
CHANNEL_ID = os.environ["CHANNEL_ID"]
POSTS_DIR = Path(__file__).parent.parent / "posts"
PUBLISHED_DIR = Path(__file__).parent.parent / "published"

IMAGE_EXTENSIONS = (".jpg", ".jpeg", ".png", ".webp")


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
            )
    else:
        url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
        resp = requests.post(url, json={"chat_id": CHANNEL_ID, "text": text, "parse_mode": "HTML"})
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
    candidates = sorted(POSTS_DIR.glob("*.md"))

    published = 0
    for post_path in candidates:
        _, meta = parse_post(post_path)
        if meta.get("status") != "ready":
            continue
        if meta.get("date", "") > today:
            continue

        body, _ = parse_post(post_path)
        image = find_image(post_path)

        if send_message(body, image):
            update_status(post_path)
            archive(post_path, image)
            label = f"с фото ({image.name})" if image else "без фото"
            print(f"✓ Опубликован {label}: {post_path.name}")
            published += 1
        else:
            print(f"✗ Ошибка публикации: {post_path.name}")

    if published == 0:
        print("Нет постов со статусом ready для публикации сегодня.")


if __name__ == "__main__":
    main()

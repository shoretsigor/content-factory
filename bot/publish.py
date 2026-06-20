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


def parse_post(path: Path) -> tuple[str, dict]:
    text = path.read_text(encoding="utf-8")
    # Strip YAML frontmatter
    body = re.sub(r"^---\n.*?---\n", "", text, flags=re.DOTALL).strip()
    meta = {}
    for line in re.findall(r"^(\w+):\s*(.+)$", text[:200], re.MULTILINE):
        meta[line[0]] = line[1].strip()
    return body, meta


def send_message(text: str) -> bool:
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    resp = requests.post(url, json={"chat_id": CHANNEL_ID, "text": text, "parse_mode": "HTML"})
    return resp.ok


def update_status(path: Path) -> None:
    content = path.read_text(encoding="utf-8")
    content = content.replace("status: ready", "status: published")
    path.write_text(content, encoding="utf-8")


def archive(path: Path) -> None:
    PUBLISHED_DIR.mkdir(exist_ok=True)
    shutil.move(str(path), str(PUBLISHED_DIR / path.name))


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
        if send_message(body):
            update_status(post_path)
            archive(post_path)
            print(f"✓ Опубликован: {post_path.name}")
            published += 1
        else:
            print(f"✗ Ошибка публикации: {post_path.name}")

    if published == 0:
        print("Нет постов со статусом ready для публикации сегодня.")


if __name__ == "__main__":
    main()

"""Проверка готовых постов перед выпуском. Запускать: python bot/check.py"""
import re
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).parent.parent
REQUIRED = ("date", "slot", "status", "rubric", "wine", "wine_id", "wine_raw", "sources", "sensory_basis")
STATUSES = ("ready", "needs_input", "needs_sources", "publication_blocked", "published")
ALLOWED_TAGS = {"b", "i", "u", "s", "a", "code", "pre", "blockquote", "tg-spoiler"}
BANNED = ("уникальн", "изысканн", "танец вкус", "в каждом глотке", "это не просто вино",
          "важно отметить", "стоит подчеркнуть", "погрузимся", "понравится всем",
          "беспроигрышн", "легендарн", "культов", "роскошн")
FAKE_SENSORY = (r"\bя\s+(открыл|попробовал|пил|почувствовал)", r"на вкус мне", r"мы пробовали")


def main() -> int:
    catalogue = yaml.safe_load((ROOT / "sources" / "wines.yml").read_text(encoding="utf-8"))["wines"]
    by_id = {w["id"]: w for w in catalogue}
    problems = []

    for path in sorted((ROOT / "posts").glob("*.md")):
        text = path.read_text(encoding="utf-8")
        match = re.match(r"^---\n(.*?)\n---\n", text, flags=re.DOTALL)
        if not match:
            problems.append(f"{path.name}: нет frontmatter")
            continue
        meta = yaml.safe_load(match.group(1)) or {}
        body = text[match.end():].strip()

        for key in REQUIRED:
            if key not in meta:
                problems.append(f"{path.name}: нет поля {key}")
        if meta.get("status") not in STATUSES:
            problems.append(f"{path.name}: неизвестный статус {meta.get('status')!r}")
        if meta.get("slot") != ("companion" if "companion" in path.stem else "main"):
            problems.append(f"{path.name}: slot не совпадает с именем файла")

        # бутылка должна существовать в каталоге, а строка прайса — совпадать дословно
        ids = str(meta.get("wine_id", "")).split("+")
        expected = " | ".join(by_id[i]["raw"] for i in ids if i in by_id)
        for i in ids:
            if i not in by_id:
                problems.append(f"{path.name}: {i} нет в каталоге")
        if expected and meta.get("wine_raw") != expected:
            problems.append(f"{path.name}: wine_raw разошёлся с каталогом")

        if "**" in body or "__" in body:
            problems.append(f"{path.name}: markdown-разметка не работает при parse_mode HTML")
        tags = re.findall(r"</?([a-z-]+)[^>]*>", body)
        for t in set(tags) - ALLOWED_TAGS:
            problems.append(f"{path.name}: тег <{t}> Telegram не поддерживает")
        if len(re.findall(r"<b>", body)) != len(re.findall(r"</b>", body)):
            problems.append(f"{path.name}: теги <b> не парные")

        for word in BANNED:
            if word in body.lower():
                problems.append(f"{path.name}: запрещённый оборот «{word}»")
        for pattern in FAKE_SENSORY:
            if re.search(pattern, body.lower()):
                problems.append(f"{path.name}: дегустация от первого лица")
        if meta.get("sensory_basis") == "none" and meta.get("status") == "ready":
            pass  # допустимо: пост без сенсорного блока

        print(f"{path.stem}  {len(body):>5} зн.  {meta.get('status')}")

    print()
    if problems:
        print(f"Проблем: {len(problems)}")
        for p in problems:
            print("  •", p)
        return 1
    print("Проверка пройдена")
    return 0


if __name__ == "__main__":
    sys.exit(main())

"""Проверка нового недельного графика без обращения к Telegram."""

import os
import unittest
from datetime import date, datetime, timezone

import yaml

os.environ.setdefault("BOT_TOKEN", "test-token")
os.environ.setdefault("CHANNEL_ID", "test-channel")

from bot import publish  # noqa: E402


class PublishScheduleTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.config = yaml.safe_load(publish.CONFIG_PATH.read_text(encoding="utf-8"))

    def test_only_tuesday_saturday_are_active(self):
        days = [date(2026, 10, day) for day in range(12, 19)]
        active = [day for day in days if publish.is_active_day(day, self.config)]
        self.assertEqual(active, [date(2026, 10, 17)])

    def test_main_slot_starts_at_1405_moscow(self):
        early = datetime(2026, 10, 17, 11, 4, tzinfo=timezone.utc)
        on_time = datetime(2026, 10, 17, 11, 5, tzinfo=timezone.utc)
        self.assertEqual(publish.due_slots(self.config, early), [])
        self.assertEqual(publish.due_slots(self.config, on_time), ["main"])

    def test_current_date_is_moscow_date(self):
        after_midnight_moscow = datetime(2026, 10, 13, 21, 30, tzinfo=timezone.utc)
        self.assertEqual(publish.get_date(self.config, after_midnight_moscow), date(2026, 10, 14))

    def test_github_workflow_runs_at_1405_and_retries(self):
        workflow = yaml.load(
            (publish.ROOT / ".github" / "workflows" / "publish.yml").read_text(encoding="utf-8"),
            Loader=yaml.BaseLoader,
        )
        self.assertEqual(workflow["on"]["schedule"], [{
            "cron": "5 14-23 * * 2,6", "timezone": "Europe/Moscow"
        }])

    def test_queued_posts_and_catalogue_follow_weekdays(self):
        posts = sorted(publish.POSTS_DIR.glob("*-main.md"))
        self.assertEqual(len(posts), 17)
        self.assertEqual(posts[0].name, "2026-10-17-main.md")
        self.assertEqual(posts[-1].name, "2026-12-12-main.md")
        catalogue = yaml.safe_load((publish.ROOT / "sources" / "wines.yml").read_text(encoding="utf-8"))
        by_id = {wine["id"]: wine for wine in catalogue["wines"]}
        for path in posts:
            meta = yaml.safe_load(path.read_text(encoding="utf-8").split("---", 2)[1])
            day = meta["date"]
            with self.subTest(post=path.name):
                self.assertEqual(path.name[:10], day.isoformat())
                self.assertTrue(publish.is_active_day(day, self.config))
                self.assertEqual(by_id[meta["wine_id"]]["used"], day.isoformat())


if __name__ == "__main__":
    unittest.main()

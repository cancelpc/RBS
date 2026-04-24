import unittest
from datetime import datetime

from pydantic import ValidationError
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base
from app.models import MediaItem, ScheduleRule
from app.schemas import PlaylistItemInput, ScheduleCreate
from app.services import ensure_media_code, window_matches


class CoreBehaviorTests(unittest.TestCase):
    def test_media_codes_are_assigned_before_duplicate_blank_codes_can_conflict(self):
        engine = create_engine(
            "sqlite:///:memory:",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        try:
            Base.metadata.create_all(bind=engine)
            SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)

            with SessionLocal() as db:
                first = MediaItem(media_code="", title="First", source_url="https://example.com/first.mp4")
                db.add(first)
                db.flush()
                ensure_media_code(db, first)

                second = MediaItem(media_code="", title="Second", source_url="https://example.com/second.mp4")
                db.add(second)
                db.flush()
                ensure_media_code(db, second)
                db.commit()

                self.assertEqual(first.media_code, "first-1")
                self.assertEqual(second.media_code, "second-2")
        finally:
            engine.dispose()

    def test_playlist_item_rejects_invalid_ids_and_positions(self):
        with self.assertRaises(ValidationError):
            PlaylistItemInput(media_id=0, position=1)
        with self.assertRaises(ValidationError):
            PlaylistItemInput(media_id=1, position=0)

    def test_schedule_rejects_invalid_weekdays_times_and_dates(self):
        valid_payload = {
            "name": "daily",
            "playlist_id": 1,
            "weekdays": [0, 1, 2],
            "start_time": "08:00",
            "end_time": "18:00",
        }

        with self.assertRaises(ValidationError):
            ScheduleCreate(**{**valid_payload, "weekdays": [0, 7]})
        with self.assertRaises(ValidationError):
            ScheduleCreate(**{**valid_payload, "weekdays": []})
        with self.assertRaises(ValidationError):
            ScheduleCreate(**{**valid_payload, "start_time": "24:00"})
        with self.assertRaises(ValidationError):
            ScheduleCreate(**{**valid_payload, "end_time": "12:60"})
        with self.assertRaises(ValidationError):
            ScheduleCreate(**{**valid_payload, "start_date": "2026-05-05", "end_date": "2026-05-04"})

        schedule = ScheduleCreate(**{**valid_payload, "weekdays": [2, 1, 1, 0]})
        self.assertEqual(schedule.weekdays, [0, 1, 2])
        self.assertEqual(schedule.start_date, "1970-01-01")
        self.assertIsNone(schedule.end_date)

    def test_schedule_window_respects_start_and_optional_end_dates(self):
        schedule = ScheduleRule(
            schedule_code="date-window-1",
            name="date-window",
            playlist_id=1,
            weekdays="0,1,2,3,4,5,6",
            start_date="2026-05-05",
            end_date="2027-05-10",
            start_time="00:00",
            end_time="23:59",
        )

        self.assertFalse(window_matches(datetime(2026, 5, 4, 12, 0), schedule))
        self.assertTrue(window_matches(datetime(2026, 5, 5, 12, 0), schedule))
        self.assertTrue(window_matches(datetime(2027, 5, 10, 12, 0), schedule))
        self.assertFalse(window_matches(datetime(2027, 5, 11, 12, 0), schedule))

        schedule.end_date = None
        self.assertTrue(window_matches(datetime(2027, 5, 11, 12, 0), schedule))


if __name__ == "__main__":
    unittest.main()

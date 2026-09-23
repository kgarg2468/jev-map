import hashlib
import json
from unittest.mock import patch

from benchmarks.archive import publish_no_replace, staged_round
from support import TemporaryRepository


class ArchiveTest(TemporaryRepository):
    def test_success_publishes_complete_manifest(self):
        destination = self.root / "round"
        with staged_round(destination) as staging:
            (staging / "result.json").write_text("{}\n")
            self.assertFalse(destination.exists())
        receipt = json.loads((destination / "completion.json").read_text())
        self.assertEqual(receipt["status"], "complete")
        self.assertEqual(receipt["files"]["result.json"], hashlib.sha256(b"{}\n").hexdigest())

    def test_failure_does_not_reserve_or_publish_destination(self):
        destination = self.root / "round"
        with self.assertRaisesRegex(RuntimeError, "interrupted"):
            with staged_round(destination) as staging:
                (staging / "partial.json").write_text("{}\n")
                raise RuntimeError("interrupted")
        self.assertFalse(destination.exists())
        self.assertEqual(list(self.root.iterdir()), [])
        with staged_round(destination) as staging:
            (staging / "result.json").write_text("{}\n")
        with self.assertRaises(FileExistsError):
            with staged_round(destination):
                self.fail("Existing archive must not be opened")

    def test_concurrent_completed_round_is_not_replaced(self):
        destination = self.root / "round"
        with self.assertRaises(FileExistsError):
            with staged_round(destination) as staging:
                (staging / "ours.json").write_text("{}\n")
                destination.mkdir()
                (destination / "other.json").write_text("preserve me")
        self.assertEqual((destination / "other.json").read_text(), "preserve me")
        self.assertFalse((destination / "ours.json").exists())

    def test_empty_destination_created_at_publish_is_not_replaced(self):
        destination = self.root / "round"
        def concurrent_creation(source, target):
            target.mkdir()
            publish_no_replace(source, target)
        with patch("benchmarks.archive.publish_no_replace", side_effect=concurrent_creation):
            with self.assertRaises(FileExistsError):
                with staged_round(destination) as staging:
                    (staging / "ours.json").write_text("{}\n")
        self.assertTrue(destination.is_dir())
        self.assertEqual(list(destination.iterdir()), [])

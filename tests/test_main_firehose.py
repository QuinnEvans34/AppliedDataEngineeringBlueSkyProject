from __future__ import annotations

import types
import unittest
from pathlib import Path

from bluesky_pipeline.main_firehose import _validate_live_firehose_dependencies


class MainFirehoseDependencyValidationTests(unittest.TestCase):
    def _ok_importer(self, module_path: str):
        modules = {
            "websockets.sync.client": types.SimpleNamespace(connect=object()),
            "atproto_firehose.client": types.SimpleNamespace(
                _get_message_frame_from_bytes_or_raise=object()
            ),
            "atproto_firehose.models": types.SimpleNamespace(MessageFrame=object()),
            "atproto_firehose": types.SimpleNamespace(parse_subscribe_repos_message=object()),
            "atproto_core.car": types.SimpleNamespace(CAR=object()),
            "certifi": types.SimpleNamespace(where=lambda: "/tmp/certifi.pem"),
        }
        if module_path not in modules:
            raise ModuleNotFoundError(module_path)
        return modules[module_path]

    def test_skips_live_validation_in_mock_mode(self) -> None:
        called = {"count": 0}

        def importer(module_path: str):
            called["count"] += 1
            raise AssertionError(f"Importer should not be called in mock mode: {module_path}")

        checked = _validate_live_firehose_dependencies(
            mock_frames_path=Path("mock_frames.jsonl"),
            import_module=importer,
        )

        self.assertFalse(checked)
        self.assertEqual(called["count"], 0)

    def test_raises_clear_error_when_dependency_missing(self) -> None:
        def importer(module_path: str):
            if module_path == "websockets.sync.client":
                raise ModuleNotFoundError("No module named websockets")
            return self._ok_importer(module_path)

        with self.assertRaises(RuntimeError) as ctx:
            _validate_live_firehose_dependencies(
                mock_frames_path=None,
                import_module=importer,
            )

        message = str(ctx.exception)
        self.assertIn("Live firehose dependency check failed", message)
        self.assertIn("websockets.sync.client.connect", message)
        self.assertIn("pip install -r requirements.txt", message)

    def test_passes_when_all_live_dependencies_available(self) -> None:
        checked = _validate_live_firehose_dependencies(
            mock_frames_path=None,
            import_module=self._ok_importer,
        )
        self.assertTrue(checked)


if __name__ == "__main__":
    unittest.main()

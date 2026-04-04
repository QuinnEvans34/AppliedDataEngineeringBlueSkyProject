from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from snowflake_loader.config import build_loader_config
from snowflake_loader.manifest import DATASET_FAMILIES


class SnowflakeLoaderConfigTests(unittest.TestCase):
    def test_build_loader_config_exposes_pipe_names_for_all_families(self) -> None:
        with tempfile.TemporaryDirectory() as tempdir:
            run_root = Path(tempdir) / "run_config"
            run_root.mkdir(parents=True, exist_ok=True)

            config = build_loader_config(
                run_root=run_root,
                state_db_path=None,
                dry_run=True,
                maturity_hours=0,
            )

        self.assertEqual(set(config.objects.pipe_names), set(DATASET_FAMILIES))


if __name__ == "__main__":
    unittest.main()

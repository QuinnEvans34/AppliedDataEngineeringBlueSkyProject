"""Filesystem manifest discovery for finalized run output files."""

from __future__ import annotations

import gzip
from dataclasses import dataclass
from pathlib import Path

DATASET_FAMILIES: tuple[str, ...] = (
    "raw_posts",
    "hydrated_posts",
    "hydration_misses",
    "actor_profiles",
    "trend_matches",
)

BUSINESS_KEY_BY_FAMILY: dict[str, str] = {
    "raw_posts": "uri",
    "hydrated_posts": "uri",
    "hydration_misses": "uri",
    "actor_profiles": "did",
    "trend_matches": "post_uri",
}


@dataclass(frozen=True, slots=True)
class ManifestFile:
    """One finalized file discovered under a run root."""

    dataset_family: str
    run_id: str
    local_path: Path
    row_count: int
    byte_size: int


@dataclass(frozen=True, slots=True)
class RunManifest:
    """Filesystem manifest grouped by dataset family."""

    run_root: Path
    run_tag: str
    files_by_family: dict[str, tuple[ManifestFile, ...]]

    def files_for_family(self, dataset_family: str) -> tuple[ManifestFile, ...]:
        return self.files_by_family.get(dataset_family, ())

    def run_ids_for_family(self, dataset_family: str) -> set[str]:
        return {item.run_id for item in self.files_for_family(dataset_family)}

    def total_file_count(self, dataset_family: str) -> int:
        return len(self.files_for_family(dataset_family))

    def total_row_count(self, dataset_family: str) -> int:
        return sum(item.row_count for item in self.files_for_family(dataset_family))


def discover_run_manifest(run_root: Path | str) -> RunManifest:
    """Discover finalized `.jsonl.gz` files under one run root."""

    root = Path(run_root)
    if not root.exists() or not root.is_dir():
        raise FileNotFoundError(f"Run root does not exist or is not a directory: {root}")

    files_by_family: dict[str, tuple[ManifestFile, ...]] = {}

    for dataset_family in DATASET_FAMILIES:
        family_dir = root / dataset_family
        if not family_dir.exists():
            files_by_family[dataset_family] = ()
            continue

        discovered: list[ManifestFile] = []
        for path in sorted(family_dir.rglob("*.jsonl.gz")):
            # Canonical source: finalized files only.
            if path.name.endswith(".tmp"):
                continue

            run_id = path.parent.name
            discovered.append(
                ManifestFile(
                    dataset_family=dataset_family,
                    run_id=run_id,
                    local_path=path.resolve(),
                    row_count=count_jsonl_gz_rows(path),
                    byte_size=path.stat().st_size,
                )
            )

        files_by_family[dataset_family] = tuple(discovered)

    return RunManifest(
        run_root=root.resolve(),
        run_tag=root.name,
        files_by_family=files_by_family,
    )


def count_jsonl_gz_rows(path: Path) -> int:
    """Count non-empty lines in a gzip JSONL file."""

    count = 0
    with gzip.open(path, mode="rt", encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                count += 1
    return count

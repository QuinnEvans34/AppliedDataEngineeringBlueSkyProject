"""
inspect_labels.py
-----------------
Reads all .jsonl.gz files from data/test_data/raw_posts and any
hydrated post files it can find, then prints the exact structure
of the labels field so we can validate the Snowflake FLATTEN fix.

Usage:
    python inspect_labels.py

No dependencies beyond the standard library.
Nothing is written or modified.
"""

import gzip
import json
from pathlib import Path

RAW_DIRS = [
    Path("data/test_data/raw_posts"),
    Path("data/test_data"),
    Path("data/raw_posts"),
]

HYDRATED_DIRS = [
    Path("data/test_data/hydrated_posts"),
    Path("data/hydrated_posts"),
]

SEPARATOR = "─" * 70


def read_jsonl_gz(path: Path):
    """Yield parsed JSON objects from a gzip JSONL file."""
    with gzip.open(path, "rt", encoding="utf-8") as f:
        for i, line in enumerate(f):
            line = line.strip()
            if not line:
                continue
            try:
                yield i, json.loads(line)
            except json.JSONDecodeError as e:
                print(f"  ⚠️  Could not parse line {i} in {path.name}: {e}")


def find_gz_files(dirs: list[Path]) -> list[Path]:
    found = []
    for d in dirs:
        if d.exists():
            found.extend(sorted(d.rglob("*.jsonl.gz")))
            found.extend(sorted(d.rglob("*.gz")))
    # Deduplicate
    seen = set()
    result = []
    for f in found:
        if f not in seen:
            seen.add(f)
            result.append(f)
    return result


def inspect_labels_field(records: list[dict], source_label: str):
    """
    Find every unique labels structure across all records.
    Print raw JSON for each unique structure type found.
    """
    print(f"\n{SEPARATOR}")
    print(f"  SOURCE: {source_label}")
    print(SEPARATOR)

    total = len(records)
    with_labels = [r for r in records if r.get("labels") not in (None, [], "")]
    print(f"  Total records:          {total}")
    print(f"  Records with labels:    {len(with_labels)}")

    if not with_labels:
        print("\n  ⚠️  NO LABELED RECORDS FOUND in this source.")
        print("  Cannot validate the FLATTEN fix from this data.")
        return

    print(f"\n  Printing raw labels structure for first 5 labeled records:\n")
    for i, record in enumerate(with_labels[:5]):
        labels_raw = record.get("labels")
        print(f"  --- Record {i+1} ---")
        print(f"  labels field type: {type(labels_raw).__name__}")
        print(f"  labels raw value:")
        print(f"  {json.dumps(labels_raw, indent=4)}")
        print()

    # Structural analysis
    print(f"\n{SEPARATOR}")
    print("  STRUCTURAL ANALYSIS")
    print(SEPARATOR)

    bare_string_count = 0
    object_with_val_count = 0
    object_without_val_count = 0
    other_structure_count = 0
    all_keys_seen = set()

    for record in with_labels:
        labels = record.get("labels")
        if isinstance(labels, list):
            for item in labels:
                if isinstance(item, str):
                    bare_string_count += 1
                elif isinstance(item, dict):
                    all_keys_seen.update(item.keys())
                    if "val" in item:
                        object_with_val_count += 1
                    else:
                        object_without_val_count += 1
                else:
                    other_structure_count += 1
        elif isinstance(labels, str):
            bare_string_count += 1

    print(f"  Label items as bare strings:       {bare_string_count}")
    print(f"  Label items as objects WITH 'val': {object_with_val_count}")
    print(f"  Label items as objects WITHOUT 'val': {object_without_val_count}")
    print(f"  Other structure:                   {other_structure_count}")
    if all_keys_seen:
        print(f"  All keys seen in label objects:    {sorted(all_keys_seen)}")

    print(f"\n{SEPARATOR}")
    print("  VERDICT")
    print(SEPARATOR)

    if object_with_val_count > 0 and bare_string_count == 0:
        print("""
  ✅  VERDICT A: Fix is CORRECT.
  Labels are objects with a 'val' key.
  The FLATTEN pattern f.value:val::STRING will work.
  ARRAY_CONTAINS against bare strings would have ALWAYS returned FALSE.
  The fix was necessary and is correctly implemented.
        """)
    elif bare_string_count > 0 and object_with_val_count == 0:
        print("""
  ❌  VERDICT B: Fix is WRONG.
  Labels are bare strings, not objects.
  The original ARRAY_CONTAINS pattern would have worked.
  The FLATTEN fix is unnecessary and will fail.

  Correct SQL (revert to original):
  COALESCE(
    ARRAY_CONTAINS('porn'::VARIANT,          h.labels)
    OR ARRAY_CONTAINS('sexual'::VARIANT,     h.labels)
    OR ARRAY_CONTAINS('nudity'::VARIANT,     h.labels)
    OR ARRAY_CONTAINS('graphic-media'::VARIANT, h.labels),
    FALSE
  ) AS is_adult_content
        """)
    elif object_without_val_count > 0 and object_with_val_count == 0:
        key_list = sorted(all_keys_seen)
        print(f"""
  ❌  VERDICT B: Fix is WRONG — different key name.
  Labels are objects but the key is NOT 'val'.
  Keys found: {key_list}

  Update the FLATTEN fix to use the correct key, e.g.:
  WHERE f.value:{key_list[0]}::STRING IN ('porn', 'sexual', 'nudity', 'graphic-media')
        """)
    elif object_with_val_count > 0 and bare_string_count > 0:
        print("""
  ⚠️  MIXED STRUCTURE: Some labels are objects with 'val',
  some are bare strings. The FLATTEN fix handles objects
  but not bare strings. A combined approach may be needed.
        """)
    else:
        print("""
  ⚠️  VERDICT C: Cannot determine from this data.
  No clear label structure identified. Check raw output above.
        """)


def main():
    print("=" * 70)
    print("  LABEL STRUCTURE VALIDATION")
    print("  Checking Bluesky labels to validate Snowflake FLATTEN fix")
    print("  Read-only. Nothing modified.")
    print("=" * 70)

    # --- RAW POSTS ---
    raw_files = find_gz_files(RAW_DIRS)
    if not raw_files:
        print("\n  ❌ No .gz files found in raw post directories.")
        print("  Checked:", [str(d) for d in RAW_DIRS])
    else:
        print(f"\n  Found {len(raw_files)} raw file(s):")
        for f in raw_files:
            print(f"    {f}")

        raw_records = []
        for path in raw_files:
            for _, record in read_jsonl_gz(path):
                raw_records.append(record)

        inspect_labels_field(raw_records, "RAW POSTS")

    # --- HYDRATED POSTS ---
    hydrated_files = find_gz_files(HYDRATED_DIRS)
    if not hydrated_files:
        print(f"\n  ⚠️  No hydrated post files found.")
        print("  Checked:", [str(d) for d in HYDRATED_DIRS])
        print("  Note: labels on hydrated posts are what the SQL fix")
        print("  actually reads. Raw post labels may differ.")
    else:
        print(f"\n  Found {len(hydrated_files)} hydrated file(s):")
        for f in hydrated_files:
            print(f"    {f}")

        hydrated_records = []
        for path in hydrated_files:
            for _, record in read_jsonl_gz(path):
                hydrated_records.append(record)

        inspect_labels_field(hydrated_records, "HYDRATED POSTS")

    print("\n" + "=" * 70)
    print("  Done. No files were modified.")
    print("=" * 70)


if __name__ == "__main__":
    main()
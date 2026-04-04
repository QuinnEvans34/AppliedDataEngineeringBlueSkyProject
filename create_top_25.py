import gzip
from pathlib import Path
import pandas as pd

input_file1 = Path(r"snowflake_package - Copy/actor_profiles/act_20260402T182221Z_1784be30/actor_profiles_000001.jsonl.gz")
json_output1 = Path(r"snowflake_package - Copy/actor_profiles/act_20260402T182221Z_1784be30/actor_profiles_top25.json")
gz_output1 = Path(r"data/test_data/raw_profiles/actor_profiles_top25.jsonl.gz")

input_file2 = Path(r"snowflake_package - Copy/hydrated_posts/hyd_20260402T181936Z_5cf8bb07/hydrated_posts_000002.jsonl.gz")
json_output2 = Path(r"snowflake_package - Copy/hydrated_posts/hyd_20260402T181936Z_5cf8bb07/hydrated_posts_top25.json")
gz_output2 = Path(r"data/test_data/raw_interactions/hydrated_posts_top25.jsonl.gz")

input_file3 = Path(r"snowflake_package - Copy/raw_posts/cap_20260402T181311Z_f98d0c5f/raw_posts_000001.jsonl.gz")
json_output3 = Path(r"snowflake_package - Copy/raw_posts/cap_20260402T181311Z_f98d0c5f/raw_posts_top25.json")
gz_output3 = Path(r"data/test_data/raw_posts/raw_posts_top25.jsonl.gz")




def save_top25_json_and_jsonl_gz(input_file: Path, json_output: Path, gz_output: Path) -> None:
    # Read gzipped JSONL file
    df = pd.read_json(input_file, lines=True, compression="gzip")

    # Keep only top 25 rows
    top25 = df.head(25)

    # Save normal JSON array for inspection
    top25.to_json(json_output, orient="records", indent=2, force_ascii=False)

    # Save back to gzipped JSONL for Snowflake
    with gzip.open(gz_output, "wt", encoding="utf-8") as f:
        top25.to_json(f, orient="records", lines=True, force_ascii=False)

    print(top25)
    print(f"Saved {len(top25)} rows to:")
    print(f"  JSON:    {json_output}")
    print(f"  JSONL.GZ: {gz_output}")


save_top25_json_and_jsonl_gz(input_file1, json_output1, gz_output1)
save_top25_json_and_jsonl_gz(input_file2, json_output2, gz_output2)
save_top25_json_and_jsonl_gz(input_file3, json_output3, gz_output3)
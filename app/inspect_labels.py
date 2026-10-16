
from pathlib import Path
import duckdb

ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT.parent / "NFPC-Phase-1" / "EDA-Phase-1"

con = duckdb.connect(":memory:")

for filename, title in [
    ("train_labels.csv", "TRAIN LABELS"),
    ("accounts.csv", "ACCOUNT METADATA"),
]:
    path = DATA_DIR / filename

    print(f"\n{'=' * 20} {title} {'=' * 20}")
    print("File:", path)

    if not path.exists():
        print("ERROR: File not found")
        continue

    safe_path = path.as_posix().replace("'", "''")

    schema = con.execute(
        f"DESCRIBE SELECT * FROM read_csv_auto('{safe_path}')"
    ).df()

    print("\nColumns:")
    print(schema[["column_name", "column_type"]].to_string(index=False))

    print("\nSample rows:")
    sample = con.execute(
        f"SELECT * FROM read_csv_auto('{safe_path}') LIMIT 5"
    ).df()

    print(sample.to_string(index=False))

con.close()

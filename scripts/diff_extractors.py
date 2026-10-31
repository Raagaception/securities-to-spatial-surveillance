#!/usr/bin/env python3
"""Compare the two extractors row by row and write outputs/extraction/diff.csv.

All paths are resolved relative to the REPOSITORY ROOT (the parent directory of
scripts/), via pathlib. Run it from the repository root:

    python scripts/diff_extractors.py

or from anywhere by its full path; the working directory does not matter and no
absolute or machine-specific paths are used. Run the two extractors first.

This script deliberately does NOT adjudicate. It never decides which extractor
is right, never rewrites a value, and never drops a disagreement. Its only job
is to say, precisely, where the two reads differ so a human can look.

Matching rule: a record is identified by (annexure, sn_raw, zone). If that key
appears more than once in either file the key cannot be matched reliably, so a
single "duplicate key" line is written and the key is skipped entirely.

Comparison rule: every field except `extractor` (which differs by definition) is
compared cell by cell as text. Two missing values count as equal; a missing
value against a present one does not.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import yaml

PROJECT_ROOT = Path(__file__).resolve().parent.parent

# The key that identifies the same site in both files.
KEY_FIELDS = ["annexure", "sn_raw", "zone"]

# `extractor` is the only field excluded from comparison: it is the label of
# which script produced the row, so it can never agree.
COMPARED_FIELDS = [
    "annexure", "zone", "station_raw", "section_heading", "scope_tag",
    "sn_raw", "location_raw", "lat_raw", "lon_raw", "category_raw",
    "fixed", "ptz", "anpr", "poles", "total_reported", "go_live_raw",
    "pdf_page", "row_index_on_page",
    "location_original", "geo_raw", "geo_flag", "station_source",
]

DIFF_COLUMNS = ["record_key", "field", "extractor1_value", "extractor2_value",
                "pdf_page", "diff_type"]


def read_config() -> dict:
    with open(PROJECT_ROOT / "config" / "extraction.yml", encoding="utf-8") as handle:
        return yaml.safe_load(handle)


def load_sites(path: Path) -> pd.DataFrame:
    """Read a site CSV as text.

    dtype=str with keep_default_na=False keeps a missing cell as an empty string
    instead of turning it into NaN, so "missing" is unambiguous and no value is
    reformatted on the way in.
    """
    frame = pd.read_csv(path, dtype=str, keep_default_na=False)
    for field in COMPARED_FIELDS:
        if field not in frame.columns:
            frame[field] = ""
    return frame


def make_key(row) -> str:
    """Stable text key for reporting; parts are joined with '|'."""
    return "|".join(str(row[field]) for field in KEY_FIELDS)


def index_by_key(frame: pd.DataFrame):
    """Return {key: row} plus the set of keys that occur more than once."""
    seen = {}
    duplicates = set()
    for _, row in frame.iterrows():
        key = make_key(row)
        if key in seen:
            duplicates.add(key)
        else:
            seen[key] = row
    return seen, duplicates


def compare_field(field: str, row1, row2, key: str, page: str) -> dict | None:
    """Return a diff record when the two values disagree, else None.

    Two empty strings are treated as equal: both extractors failed to read the
    same cell, which is not a disagreement about content.
    """
    value1 = "" if row1 is None else str(row1[field])
    value2 = "" if row2 is None else str(row2[field])
    if value1 == value2:
        return None
    return {
        "record_key": key,
        "field": field,
        "extractor1_value": value1,
        "extractor2_value": value2,
        "pdf_page": page,
        "diff_type": "value_differs",
    }


def main() -> int:
    config = read_config()
    path1 = PROJECT_ROOT / config["outputs"]["sites_pdfplumber"]
    path2 = PROJECT_ROOT / config["outputs"]["sites_pymupdf"]

    sites1 = load_sites(path1)
    sites2 = load_sites(path2)

    index1, duplicates1 = index_by_key(sites1)
    index2, duplicates2 = index_by_key(sites2)

    diff_rows = []

    # Duplicate keys are reported once each and excluded from field comparison,
    # because there is no single pairing that could be called correct.
    all_duplicates = sorted(duplicates1 | duplicates2)
    for key in all_duplicates:
        where = "extractor1" if key in duplicates1 else ""
        where += "+extractor2" if key in duplicates2 else ""
        diff_rows.append({
            "record_key": key,
            "field": "<key>",
            "extractor1_value": f"duplicate in {where}" if key in duplicates1 else "",
            "extractor2_value": f"duplicate in {where}" if key in duplicates2 else "",
            "pdf_page": "",
            "diff_type": "duplicate_key",
        })

    keys1 = set(index1) - duplicates1
    keys2 = set(index2) - duplicates2

    # Keys present in only one file: one line each, no field-by-field noise.
    for key in sorted(keys1 - keys2):
        page = str(index1[key]["pdf_page"])
        diff_rows.append({
            "record_key": key, "field": "<row>",
            "extractor1_value": "present", "extractor2_value": "missing",
            "pdf_page": page, "diff_type": "missing_in_2",
        })
    for key in sorted(keys2 - keys1):
        page = str(index2[key]["pdf_page"])
        diff_rows.append({
            "record_key": key, "field": "<row>",
            "extractor1_value": "missing", "extractor2_value": "present",
            "pdf_page": page, "diff_type": "missing_in_1",
        })

    # Keys in both files: compare every field.
    for key in sorted(keys1 & keys2):
        row1 = index1[key]
        row2 = index2[key]
        page = str(row1["pdf_page"]) or str(row2["pdf_page"])
        for field in COMPARED_FIELDS:
            record = compare_field(field, row1, row2, key, page)
            if record is not None:
                diff_rows.append(record)

    diff_frame = pd.DataFrame(diff_rows, columns=DIFF_COLUMNS)
    out_path = PROJECT_ROOT / config["outputs"]["diff"]
    out_path.parent.mkdir(parents=True, exist_ok=True)
    diff_frame.to_csv(out_path, index=False, encoding="utf-8")

    # ------------------------------------------------------------------
    # Report
    # ------------------------------------------------------------------
    print("=" * 78)
    print("DIFF: extractor 1 (pdfplumber) vs extractor 2 (PyMuPDF)")
    print("=" * 78)
    print(f"rows in extractor 1: {len(sites1)}")
    print(f"rows in extractor 2: {len(sites2)}")
    print(f"matched keys: {len(keys1 & keys2)}")
    print(f"duplicate keys: {len(all_duplicates)}")
    print(f"diff lines: {len(diff_frame)}")

    if not diff_frame.empty:
        print("\ndiff lines by type:")
        for diff_type, count in diff_frame["diff_type"].value_counts().sort_index().items():
            print(f"  {diff_type}: {count}")
        print("\ndiff lines by field (top 15):")
        for field, count in diff_frame["field"].value_counts().head(15).items():
            print(f"  {field}: {count}")
        print(f"\nsee {out_path.relative_to(PROJECT_ROOT)} for row-level detail")

    return 0


if __name__ == "__main__":
    sys.exit(main())

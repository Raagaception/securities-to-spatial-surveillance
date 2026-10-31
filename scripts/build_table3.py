#!/usr/bin/env python3
"""Build Table 3: ward-level camera allocation by 2011 SC+ST quintile.

The table answers one question at ward scale: how are the tender-recorded
cameras distributed across wards grouped by the 2011 Scheduled Caste and
Scheduled Tribe share of their population? It is descriptive. It does not
measure installation, operation or intent, and the ward frame covers Pune
Municipal Corporation only.

Inputs
------
* The joined ward layer, ``outputs/figures/2011census_wards-with-cameras-all.gpkg``
  (layer ``joined_layer``), which carries the 144 wards, the Census 2011
  demographic columns and the two camera sums produced by the QGIS spatial
  join. This is the durable, committed input.
* ``outputs/extraction/sites_pymupdf.csv``, used only for the Pune-scope
  control totals (1,077 existing and 2,886 proposed cameras) and for the
  count of sites with no usable coordinate. The ward layer holds the 963
  existing and 2,146 proposed cameras that fall inside the 144 wards; the
  difference is the outside row.
* Optionally, the QGIS attribute export
  ``data/processed/QGIS_2011wards-cameras-final.csv``. When present it is
  cross-checked cell by cell against the GeoPackage, so the delivered table
  cannot silently rest on a stale export.

Outputs (all under ``outputs/tables/``)
---------------------------------------
* ``table3_scst_allocation.csv``  machine-readable table, one row per class
  plus the outside row.
* ``table3_scst_allocation.md``   manuscript-ready table with caption, source
  note and the pre-specified ratio verdict.
* ``table3_summary.json``         full-precision values, class breaks, checks,
  input hashes and the script hash.
* ``SHA256SUMS``                  standard manifest for the three files above.

Method
------
Classes are quintiles of ``(P_SC + P_ST) / TOT_P`` over the 144 wards, using
the type-7 (linear interpolation) definition that QGIS uses for its quantile
classification. The five class labels in the manuscript table are rounded to
two decimals; the exact breaks are written to the JSON and the Markdown note.

Percentages use the Pune-scope totals, not the ward-layer totals, so that the
outside row completes the city total. Cameras per 1,000 residents uses
inside-ward cameras only. The camera-weighted SC+ST share is
``sum(cameras x ward share) / sum(cameras)`` over the 144 wards; the outside
cameras carry no ward share and are excluded from numerator and denominator.

The ratio rule was fixed before the table was read: for each class divide its
share of cameras by its share of residents; call it a gradient only if the
ratio rises at every step or falls at every step, otherwise call it mixed.

Provenance
----------
The table inherits, rather than recomputes, the QGIS spatial join that writes
``outputs/figures/2011census_wards-with-cameras-all.gpkg`` (layer
``joined_layer``). The join inputs, fields and control totals are documented in
``metadata/output-schema.md`` (section ``joined_layer``) and in
``outputs/figures/README.md`` (section ``Ward layer used by the maps and
Table 3``). This script, its outputs and its checks are documented in
``outputs/tables/README.md``; the column definitions are in
``metadata/output-schema.md`` (section ``table3_scst_allocation.csv``).

Usage
-----
    python scripts/build_table3.py
    python scripts/build_table3.py --wards data/processed/QGIS_2011wards-cameras-final.csv
    python scripts/build_table3.py --no-crosscheck

Run it from the repository root or from anywhere else; paths are resolved
against the repository root, the same convention the extraction scripts use.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import sqlite3
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent

DEFAULT_WARDS = PROJECT_ROOT / "outputs" / "figures" / "2011census_wards-with-cameras-all.gpkg"
DEFAULT_SITES = PROJECT_ROOT / "outputs" / "extraction" / "sites_pymupdf.csv"
DEFAULT_QGIS_CSV = PROJECT_ROOT / "data" / "processed" / "QGIS_2011wards-cameras-final.csv"
DEFAULT_OUT_DIR = PROJECT_ROOT / "outputs" / "tables"

# Documented type-7 quintile breaks, carried here as a regression check against
# outputs/figures/README.md. The script recomputes them from the data and fails
# if they drift.
EXPECTED_BREAKS = (
    0.008683068017366,
    0.066268410601744,
    0.100785145359672,
    0.146206619489227,
    0.225284429587565,
    0.531341256366723,
)
EXPECTED_BREAK_TOLERANCE = 1e-9

# Manuscript labels. The bounds are rounded for display; the exact bounds are
# in EXPECTED_BREAKS and in the JSON.
CLASS_LABELS = (
    "Q1 (0.01\u20130.07)",
    "Q2 (0.07\u20130.10)",
    "Q3 (0.10\u20130.15)",
    "Q4 (0.15\u20130.23)",
    "Q5 (0.23\u20130.55)",
)
OUTSIDE_LABEL = "Outside the 144 wards"
EN_DASH = "\u2013"

# Pune-scope control totals, from the tender annexures through the PyMuPDF
# extractor. The ward layer must reconcile to these exactly.
EXPECTED_TOTALS = {
    "population": 3_124_458,
    "sc": 419_396,
    "st": 34_025,
    "existing_pune": 1_077,
    "proposed_pune": 2_886,
    "existing_inside": 963,
    "proposed_inside": 2_146,
    "existing_outside": 114,
    "proposed_outside": 740,
}
EXPECTED_CLASS_COUNTS = (29, 29, 28, 29, 29)

CSV_COLUMNS = (
    "scst_class",
    "wards",
    "residents",
    "residents_pct",
    "existing_cameras",
    "existing_pct",
    "proposed_cameras",
    "proposed_pct",
    "cameras_per_1000_residents",
)

CHECKS: list[dict[str, object]] = []


def check(name: str, expected: object, observed: object, ok: bool) -> None:
    """Record one assertion in the run log and the JSON."""
    CHECKS.append(
        {
            "name": name,
            "expected": expected,
            "observed": observed,
            "status": "pass" if ok else "fail",
        }
    )
    if not ok:
        raise SystemExit(
            f"[table3] check failed: {name}: expected {expected!r}, observed {observed!r}"
        )


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def resolve(path: str) -> Path:
    candidate = Path(path)
    return candidate if candidate.is_absolute() else (PROJECT_ROOT / candidate)


def relpath(path: Path) -> str:
    """Path relative to the repository root when possible, else the path itself."""
    try:
        return str(path.relative_to(PROJECT_ROOT))
    except ValueError:
        return str(path)


def write_lf(path: Path, text: str) -> None:
    """Write UTF-8 with LF endings so the bytes do not depend on the platform."""
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        handle.write(text)


def as_int(value: object) -> int:
    text = str(value or "").strip().replace(",", "")
    if text in ("", "0"):
        return 0
    return int(float(text))


def read_gpkg(path: Path) -> list[dict[str, object]]:
    """Read the 144-ward joined layer without modifying it."""
    uri = f"file:{path}?mode=ro"
    connection = sqlite3.connect(uri, uri=True)
    connection.row_factory = sqlite3.Row
    try:
        rows = connection.execute(
            """
            SELECT wardnum,
                   "census2011_Ward Name" AS name,
                   census2011_TOT_P AS population,
                   census2011_P_SC AS sc,
                   census2011_P_ST AS st,
                   camera_count_sum AS existing,
                   camera_count_sum_2 AS proposed
            FROM joined_layer
            ORDER BY wardnum
            """
        ).fetchall()
    finally:
        connection.close()

    wards = []
    for row in rows:
        population = as_int(row["population"])
        sc = as_int(row["sc"])
        st = as_int(row["st"])
        if population <= 0:
            raise SystemExit(f"[table3] ward {row['wardnum']} has no population")
        wards.append(
            {
                "ward": as_int(row["wardnum"]),
                "name": str(row["name"] or "").strip(),
                "population": population,
                "sc": sc,
                "st": st,
                "scst_share": (sc + st) / population,
                "existing": as_int(row["existing"]),
                "proposed": as_int(row["proposed"]),
            }
        )
    return wards


def read_csv_wards(path: Path) -> list[dict[str, object]]:
    """Read the QGIS attribute export.

    Blank camera cells mean zero cameras, not a missing ward; QGIS writes NULL
    for a ward with none. Population, SC and ST must be present.
    """
    with path.open(newline="", encoding="utf-8-sig") as handle:
        rows = list(csv.DictReader(handle))

    wards = []
    for row in rows:
        population = as_int(row["census2011_TOT_P"])
        sc = as_int(row["census2011_P_SC"])
        st = as_int(row["census2011_P_ST"])
        if population <= 0:
            raise SystemExit(f"[table3] ward {row['wardnum']} has no population")
        wards.append(
            {
                "ward": as_int(row["wardnum"]),
                "name": str(row["census2011_Ward Name"] or "").strip(),
                "population": population,
                "sc": sc,
                "st": st,
                "scst_share": (sc + st) / population,
                "existing": as_int(row["camera_count_sum"]),
                "proposed": as_int(row["camera_count_sum_2"]),
            }
        )
    return sorted(wards, key=lambda ward: int(ward["ward"]))

def read_sites(path: Path) -> dict[str, int]:
    """Pune-scope site and camera totals, plus ungeocoded sites."""
    totals = {
        "sites_existing": 0,
        "sites_proposed": 0,
        "cameras_existing": 0,
        "cameras_proposed": 0,
        "ungeocoded_sites": 0,
        "ungeocoded_cameras": 0,
    }
    with path.open(newline="", encoding="utf-8-sig") as handle:
        for row in csv.DictReader(handle):
            if (row.get("scope_tag") or "").strip() != "PUNE":
                continue
            annexure = (row.get("annexure") or "").strip()
            cameras = sum(
                as_int(row.get(field)) for field in ("fixed", "ptz", "anpr")
            )
            if annexure == "annexure_a":
                totals["sites_existing"] += 1
                totals["cameras_existing"] += cameras
            elif annexure == "annexure_b":
                totals["sites_proposed"] += 1
                totals["cameras_proposed"] += cameras
            else:
                raise SystemExit(f"[table3] unknown annexure {annexure!r} in {path}")

            if not (row.get("lat_raw") or "").strip() or not (row.get("lon_raw") or "").strip():
                totals["ungeocoded_sites"] += 1
                totals["ungeocoded_cameras"] += cameras
    return totals


def quantile(sorted_values: list[float], q: float) -> float:
    """Type-7 quantile, the definition QGIS uses for quantile classification."""
    if not sorted_values:
        raise ValueError("quantile of an empty sequence")
    if len(sorted_values) == 1:
        return sorted_values[0]
    position = (len(sorted_values) - 1) * q
    lower = int(position)
    upper = min(lower + 1, len(sorted_values) - 1)
    fraction = position - lower
    return sorted_values[lower] + fraction * (sorted_values[upper] - sorted_values[lower])


def class_index(share: float, breaks: tuple[float, ...]) -> int:
    """Left-closed, right-open classes; the top class closes at the maximum."""
    index = 0
    for boundary in breaks[1:-1]:
        if share >= boundary:
            index += 1
    return index


def ratio_rule(values: list[float]) -> dict[str, object]:
    rising = all(later > earlier for earlier, later in zip(values, values[1:]))
    falling = all(later < earlier for earlier, later in zip(values, values[1:]))
    if rising:
        verdict = "rises at every step"
    elif falling:
        verdict = "falls at every step"
    else:
        verdict = "mixed"
    return {"ratios": values, "verdict": verdict, "gradient": rising or falling}


def build(wards: list[dict[str, object]], sites: dict[str, int]) -> dict[str, object]:
    check("ward_count", 144, len(wards), len(wards) == 144)
    ward_numbers = [int(ward["ward"]) for ward in wards]
    check(
        "ward_numbers_complete",
        "1-144, no gaps or duplicates",
        f"{min(ward_numbers)}-{max(ward_numbers)}, {len(set(ward_numbers))} unique",
        ward_numbers == list(range(1, 145)),
    )

    population = sum(int(ward["population"]) for ward in wards)
    sc = sum(int(ward["sc"]) for ward in wards)
    st = sum(int(ward["st"]) for ward in wards)
    existing_inside = sum(int(ward["existing"]) for ward in wards)
    proposed_inside = sum(int(ward["proposed"]) for ward in wards)

    check("population_total", EXPECTED_TOTALS["population"], population,
          population == EXPECTED_TOTALS["population"])
    check("sc_total", EXPECTED_TOTALS["sc"], sc, sc == EXPECTED_TOTALS["sc"])
    check("st_total", EXPECTED_TOTALS["st"], st, st == EXPECTED_TOTALS["st"])
    check("existing_inside", EXPECTED_TOTALS["existing_inside"], existing_inside,
          existing_inside == EXPECTED_TOTALS["existing_inside"])
    check("proposed_inside", EXPECTED_TOTALS["proposed_inside"], proposed_inside,
          proposed_inside == EXPECTED_TOTALS["proposed_inside"])

    check("pune_existing_sites", 358, sites["sites_existing"],
          sites["sites_existing"] == 358)
    check("pune_proposed_sites", 1007, sites["sites_proposed"],
          sites["sites_proposed"] == 1007)
    check("pune_existing_cameras", EXPECTED_TOTALS["existing_pune"],
          sites["cameras_existing"], sites["cameras_existing"] == EXPECTED_TOTALS["existing_pune"])
    check("pune_proposed_cameras", EXPECTED_TOTALS["proposed_pune"],
          sites["cameras_proposed"], sites["cameras_proposed"] == EXPECTED_TOTALS["proposed_pune"])

    existing_outside = sites["cameras_existing"] - existing_inside
    proposed_outside = sites["cameras_proposed"] - proposed_inside
    check("existing_outside", EXPECTED_TOTALS["existing_outside"], existing_outside,
          existing_outside == EXPECTED_TOTALS["existing_outside"])
    check("proposed_outside", EXPECTED_TOTALS["proposed_outside"], proposed_outside,
          proposed_outside == EXPECTED_TOTALS["proposed_outside"])

    shares = sorted(float(ward["scst_share"]) for ward in wards)
    breaks = tuple(quantile(shares, q) for q in (0.0, 0.2, 0.4, 0.6, 0.8, 1.0))
    max_break_drift = max(abs(a - b) for a, b in zip(breaks, EXPECTED_BREAKS))
    check("class_breaks", f"max drift < {EXPECTED_BREAK_TOLERANCE:.0e}",
          f"{max_break_drift:.3e}",
          max_break_drift <= EXPECTED_BREAK_TOLERANCE)

    grouped: list[list[dict[str, object]]] = [[] for _ in range(5)]
    for ward in wards:
        grouped[class_index(float(ward["scst_share"]), breaks)].append(ward)
    class_counts = tuple(len(group) for group in grouped)
    check("class_counts", list(EXPECTED_CLASS_COUNTS), list(class_counts),
          class_counts == EXPECTED_CLASS_COUNTS)

    rows = []
    for index, group in enumerate(grouped):
        residents = sum(int(ward["population"]) for ward in group)
        existing = sum(int(ward["existing"]) for ward in group)
        proposed = sum(int(ward["proposed"]) for ward in group)
        rows.append(
            {
                "class": CLASS_LABELS[index],
                "wards": len(group),
                "residents": residents,
                "residents_pct": residents / population * 100.0,
                "existing": existing,
                "existing_pct": existing / sites["cameras_existing"] * 100.0,
                "proposed": proposed,
                "proposed_pct": proposed / sites["cameras_proposed"] * 100.0,
                "per_1000": (existing + proposed) / residents * 1000.0,
                "lower": breaks[index],
                "upper": breaks[index + 1],
            }
        )

    outside = {
        "class": OUTSIDE_LABEL,
        "wards": None,
        "residents": None,
        "residents_pct": None,
        "existing": existing_outside,
        "existing_pct": existing_outside / sites["cameras_existing"] * 100.0,
        "proposed": proposed_outside,
        "proposed_pct": proposed_outside / sites["cameras_proposed"] * 100.0,
        "per_1000": None,
    }

    # Percentages must close at 100, including the outside row.
    existing_pct_total = sum(row["existing_pct"] for row in rows) + outside["existing_pct"]
    proposed_pct_total = sum(row["proposed_pct"] for row in rows) + outside["proposed_pct"]
    residents_pct_total = sum(row["residents_pct"] for row in rows)
    check("existing_pct_total", 100.0, round(existing_pct_total, 6),
          abs(existing_pct_total - 100.0) < 1e-6)
    check("proposed_pct_total", 100.0, round(proposed_pct_total, 6),
          abs(proposed_pct_total - 100.0) < 1e-6)
    check("residents_pct_total", 100.0, round(residents_pct_total, 6),
          abs(residents_pct_total - 100.0) < 1e-6)

    # Camera-weighted SC+ST share, computed over the 144 wards only.
    def weighted(camera_key: str) -> float:
        denominator = sum(int(ward[camera_key]) for ward in wards)
        numerator = sum(
            int(ward[camera_key]) * float(ward["scst_share"]) for ward in wards
        )
        return numerator / denominator

    weighted_existing = weighted("existing")
    weighted_proposed = weighted("proposed")
    weighted_both = (
        sum(
            (int(ward["existing"]) + int(ward["proposed"])) * float(ward["scst_share"])
            for ward in wards
        )
        / (existing_inside + proposed_inside)
    )
    resident_weighted = (sc + st) / population

    # The combined share uses the combined camera total, not the mean of the
    # two phase shares.
    total_both = existing_inside + proposed_inside
    ratios = {
        "existing": [row["existing_pct"] / row["residents_pct"] for row in rows],
        "proposed": [row["proposed_pct"] / row["residents_pct"] for row in rows],
        "both": [
            ((row["existing"] + row["proposed"]) / total_both * 100.0)
            / row["residents_pct"]
            for row in rows
        ],
    }

    rules = {name: ratio_rule(values) for name, values in ratios.items()}

    return {
        "rows": rows,
        "outside": outside,
        "breaks": breaks,
        "class_counts": list(class_counts),
        "totals": {
            "population": population,
            "sc": sc,
            "st": st,
            "existing_inside": existing_inside,
            "proposed_inside": proposed_inside,
            "existing_pune": sites["cameras_existing"],
            "proposed_pune": sites["cameras_proposed"],
            "existing_outside": existing_outside,
            "proposed_outside": proposed_outside,
        },
        "weighted_shares": {
            "existing": weighted_existing,
            "proposed": weighted_proposed,
            "both": weighted_both,
            "resident_weighted": resident_weighted,
            "existing_denominator": existing_inside,
            "proposed_denominator": proposed_inside,
            "both_denominator": existing_inside + proposed_inside,
        },
        "ratio_rule": rules,
        "sites": sites,
    }


def write_csv(path: Path, result: dict[str, object]) -> None:
    rows = list(result["rows"]) + [result["outside"]]
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle, lineterminator="\n")
        writer.writerow(CSV_COLUMNS)
        for row in rows:
            writer.writerow(
                [
                    row["class"],
                    "" if row["wards"] is None else row["wards"],
                    "" if row["residents"] is None else row["residents"],
                    "" if row["residents_pct"] is None else f'{row["residents_pct"]:.2f}',
                    row["existing"],
                    f'{row["existing_pct"]:.2f}',
                    row["proposed"],
                    f'{row["proposed_pct"]:.2f}',
                    "" if row["per_1000"] is None else f'{row["per_1000"]:.2f}',
                ]
            )


def write_markdown(path: Path, result: dict[str, object]) -> None:
    rows = result["rows"]
    outside = result["outside"]
    breaks = result["breaks"]
    weighted = result["weighted_shares"]
    rules = result["ratio_rule"]
    verdicts = {name: rule["verdict"] for name, rule in rules.items()}
    if all(verdict == "mixed" for verdict in verdicts.values()):
        rule_note = (
            "Under the rule fixed before reading the table, none rises or falls at "
            "every step: all three measures are mixed."
        )
    else:
        rule_note = (
            "Under the rule fixed before reading the table, the existing measure "
            f"{verdicts['existing']}, the proposed measure {verdicts['proposed']}, "
            f"and the combined measure {verdicts['both']}."
        )

    def cell_pct(count: object, pct: object) -> str:
        return f"{int(count):,} ({float(pct):.1f}%)"

    lines = [
        "**Table 3. Ward-level allocation of tender-recorded cameras by 2011 SC+ST quintile, Pune.**",
        "",
        "| SC+ST class | Wards | Residents (% of city) | Existing cameras (% of city) | Proposed cameras (% of city) | Cameras per 1,000 residents |",
        "| --- | ---: | ---: | ---: | ---: | ---: |",
    ]
    for row in rows:
        lines.append(
            "| {cls} | {wards} | {res} | {ex} | {pr} | {per} |".format(
                cls=row["class"],
                wards=row["wards"],
                res=cell_pct(row["residents"], row["residents_pct"]),
                ex=cell_pct(row["existing"], row["existing_pct"]),
                pr=cell_pct(row["proposed"], row["proposed_pct"]),
                per=f'{row["per_1000"]:.2f}',
            )
        )
    lines.append(
        "| {cls} | {dash} | {dash} | {ex} | {pr} | {dash} |".format(
            cls=outside["class"],
            dash=EN_DASH,
            ex=cell_pct(outside["existing"], outside["existing_pct"]),
            pr=cell_pct(outside["proposed"], outside["proposed_pct"]),
        )
    )
    lines.extend(
        [
            "",
            (
                "Sources: RFP Volume 2, Annexure III, pp. 83\u2013166 (Pune-scope rows); "
                "Census 2011 ward demographics for the 144 pre-2012 prabhags. Counts are "
                "cameras recorded at tender sites, not verified installations. Percentages "
                "use the Pune-scope totals (1,077 existing; 2,886 proposed), so the outside "
                "row completes the city total; the ward layer holds 963 existing and 2,146 "
                "proposed cameras inside the 144 wards. Cameras per 1,000 residents uses "
                "inside-ward cameras only."
            ),
            "",
            (
                "Classes are quintiles of (P_SC + P_ST) / TOT_P, with type-7 breaks at "
                + ", ".join(f"{value:.6f}" for value in breaks)
                + ". The class labels round those breaks for display."
            ),
            "",
            (
                "Camera share divided by resident share, by class: existing "
                + ", ".join(f"{value:.2f}" for value in rules["existing"]["ratios"])
                + "; proposed "
                + ", ".join(f"{value:.2f}" for value in rules["proposed"]["ratios"])
                + "; both phases "
                + ", ".join(f"{value:.2f}" for value in rules["both"]["ratios"])
                + ". "
                + rule_note
            ),
            "",
            (
                "Camera-weighted SC+ST share (inside the 144 wards): existing "
                f"{weighted['existing'] * 100:.1f}%, proposed "
                f"{weighted['proposed'] * 100:.1f}%, both "
                f"{weighted['both'] * 100:.1f}%; resident-weighted city share "
                f"{weighted['resident_weighted'] * 100:.1f}%. The "
                f"{int(outside['existing']):,} existing and {int(outside['proposed']):,} "
                "proposed cameras outside the wards carry no ward share and are excluded "
                "from both numerator and denominator."
            ),
            "",
        ]
    )
    write_lf(path, "\n".join(lines))


def write_json(path: Path, result: dict[str, object], inputs: list[dict[str, object]],
               script_hash: str) -> None:
    payload = {
        "table": "table3_scst_allocation",
        "script": "scripts/build_table3.py",
        "script_sha256": script_hash,
        "inputs": inputs,
        "class_breaks": list(result["breaks"]),
        "class_counts": result["class_counts"],
        "rows": [
            {
                "class": row["class"],
                "wards": row["wards"],
                "residents": row["residents"],
                "residents_pct": row["residents_pct"],
                "existing_cameras": row["existing"],
                "existing_pct": row["existing_pct"],
                "proposed_cameras": row["proposed"],
                "proposed_pct": row["proposed_pct"],
                "cameras_per_1000_residents": row["per_1000"],
                "lower_exact": row["lower"],
                "upper_exact": row["upper"],
            }
            for row in result["rows"]
        ],
        "outside": {
            "existing_cameras": result["outside"]["existing"],
            "existing_pct": result["outside"]["existing_pct"],
            "proposed_cameras": result["outside"]["proposed"],
            "proposed_pct": result["outside"]["proposed_pct"],
        },
        "totals": result["totals"],
        "weighted_shares": result["weighted_shares"],
        "ratio_rule": result["ratio_rule"],
        "sites": result["sites"],
        "checks": CHECKS,
    }
    write_lf(path, json.dumps(payload, indent=2, sort_keys=True) + "\n")


def write_manifest(directory: Path, names: list[str]) -> None:
    """Write a root-relative manifest, matching outputs/figures/SHA256SUMS."""
    lines = []
    for name in sorted(names):
        path = directory / name
        lines.append(f"{sha256_file(path)}  {relpath(path)}")
    write_lf(directory / "SHA256SUMS", "\n".join(lines) + "\n")


def crosscheck(csv_path: Path, gpkg_path: Path) -> dict[str, object]:
    """Compare the QGIS CSV export with the tracked GeoPackage, ward by ward.

    This is a quality check on the input, not a source of table values, so it
    does not write into the deterministic summary JSON. It fails the build if
    the export is stale, incomplete or disagrees with the GeoPackage.
    """
    csv_wards = {int(ward["ward"]): ward for ward in read_csv_wards(csv_path)}
    gpkg_wards = {int(ward["ward"]): ward for ward in read_gpkg(gpkg_path)}
    if sorted(csv_wards) != sorted(gpkg_wards):
        raise SystemExit(
            f"[table3] cross-check failed: ward sets differ "
            f"(csv {len(csv_wards)}, gpkg {len(gpkg_wards)})"
        )

    fields = ("population", "sc", "st", "existing", "proposed")
    mismatches = []
    for ward in sorted(gpkg_wards):
        for field in fields:
            if gpkg_wards[ward][field] != csv_wards[ward][field]:
                mismatches.append(
                    {
                        "ward": ward,
                        "field": field,
                        "gpkg": gpkg_wards[ward][field],
                        "csv": csv_wards[ward][field],
                    }
                )
    if mismatches:
        first = mismatches[0]
        raise SystemExit(
            f"[table3] cross-check failed: {len(mismatches)} mismatched cells; "
            f"first ward {first['ward']} field {first['field']} "
            f"(gpkg {first['gpkg']!r}, csv {first['csv']!r})"
        )

    max_share_drift = max(
        abs(float(csv_wards[ward]["scst_share"]) - float(gpkg_wards[ward]["scst_share"]))
        for ward in gpkg_wards
    )
    # The QGIS export stores scst_share rounded to four decimals, so a small
    # positive drift is expected; a larger one means the export is stale.
    if max_share_drift >= 1e-4:
        raise SystemExit(
            f"[table3] cross-check failed: scst_share drift {max_share_drift:.3e}"
        )

    return {
        "path": relpath(csv_path),
        "sha256": sha256_file(csv_path),
        "wards": len(csv_wards),
        "mismatches": len(mismatches),
        "max_scst_share_drift": max_share_drift,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--wards", default=str(DEFAULT_WARDS),
                        help="joined ward layer (.gpkg or .csv); default: the tracked GeoPackage")
    parser.add_argument("--sites", default=str(DEFAULT_SITES),
                        help="site extractor CSV used for Pune-scope totals")
    parser.add_argument("--crosscheck-csv", default=str(DEFAULT_QGIS_CSV),
                        help="QGIS attribute export checked against the GeoPackage; "
                             "ignored when --wards is a CSV")
    parser.add_argument("--no-crosscheck", action="store_true",
                        help="skip the CSV/GeoPackage cross-check")
    parser.add_argument("--out-dir", default=str(DEFAULT_OUT_DIR),
                        help="output directory (default: outputs/tables)")
    args = parser.parse_args()

    wards_path = resolve(args.wards)
    sites_path = resolve(args.sites)
    out_dir = resolve(args.out_dir)
    crosscheck_path = resolve(args.crosscheck_csv)

    if not wards_path.exists():
        raise SystemExit(f"[table3] ward layer not found: {wards_path}")
    if not sites_path.exists():
        raise SystemExit(f"[table3] site table not found: {sites_path}")

    print("=" * 78)
    print("TABLE 3: ward-level camera allocation by 2011 SC+ST quintile")
    print("=" * 78)

    if wards_path.suffix.lower() == ".gpkg":
        wards = read_gpkg(wards_path)
        ward_input = {"path": relpath(wards_path),
                      "sha256": sha256_file(wards_path), "format": "gpkg"}
    elif wards_path.suffix.lower() == ".csv":
        wards = read_csv_wards(wards_path)
        ward_input = {"path": relpath(wards_path),
                      "sha256": sha256_file(wards_path), "format": "csv"}
    else:
        raise SystemExit(f"[table3] unsupported ward input: {wards_path}")

    sites = read_sites(sites_path)
    result = build(wards, sites)

    inputs = [ward_input, {"path": relpath(sites_path),
                           "sha256": sha256_file(sites_path), "format": "csv"}]

    # Cross-check the QGIS export against the tracked GeoPackage (or the other
    # way round if the export was passed as --wards).
    wards_csv = wards_path if wards_path.suffix.lower() == ".csv" else crosscheck_path
    wards_gpkg = wards_path if wards_path.suffix.lower() == ".gpkg" else DEFAULT_WARDS
    if args.no_crosscheck:
        print("[table3] cross-check skipped by request")
    elif wards_csv.exists() and wards_gpkg.exists():
        crosscheck_result = crosscheck(wards_csv, wards_gpkg)
        print(f"[table3] cross-check: {crosscheck_result['wards']} wards, "
              f"{crosscheck_result['mismatches']} mismatches, "
              f"max share drift {crosscheck_result['max_scst_share_drift']:.1e}")
    else:
        missing = wards_csv if not wards_csv.exists() else wards_gpkg
        print(f"[table3] cross-check skipped: {missing} not found")

    out_dir.mkdir(parents=True, exist_ok=True)
    csv_path = out_dir / "table3_scst_allocation.csv"
    md_path = out_dir / "table3_scst_allocation.md"
    json_path = out_dir / "table3_summary.json"

    write_csv(csv_path, result)
    write_markdown(md_path, result)
    write_json(json_path, result, inputs, sha256_file(Path(__file__)))
    write_manifest(out_dir, [csv_path.name, md_path.name, json_path.name])

    print(f"wards: {len(wards)}")
    print(f"population: {result['totals']['population']:,}")
    print(f"inside cameras: {result['totals']['existing_inside']:,} existing, "
          f"{result['totals']['proposed_inside']:,} proposed")
    print(f"outside cameras: {result['totals']['existing_outside']:,} existing, "
          f"{result['totals']['proposed_outside']:,} proposed")
    print("class counts: " + " / ".join(str(count) for count in result["class_counts"]))
    print("weighted SC+ST share: "
          f"existing {result['weighted_shares']['existing'] * 100:.2f}%, "
          f"proposed {result['weighted_shares']['proposed'] * 100:.2f}%, "
          f"resident {result['weighted_shares']['resident_weighted'] * 100:.2f}%")
    print("ratio rule: " + "; ".join(
        f"{name} {rule['verdict']}" for name, rule in result["ratio_rule"].items()))
    print(f"\nwrote {relpath(csv_path)}")
    print(f"wrote {relpath(md_path)}")
    print(f"wrote {relpath(json_path)}")
    print(f"wrote {relpath(out_dir / 'SHA256SUMS')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
"""Extractor 1: pdfplumber, ruled-table ("lines") strategy.

All paths are resolved relative to the REPOSITORY ROOT (the parent directory of
scripts/), via pathlib. Run it from the repository root:

    python scripts/extract_pdfplumber.py

or from anywhere by its full path; the working directory does not matter and no
absolute or machine-specific paths are used.

This script reads three regions of the tender PDF and writes CSV files:

  * pages 81-82   control table "Existing CCTV Count as a part of PCS Project"
  * pages 83-99   Annexure A, existing locations
  * pages 100-166 Annexure B, proposed locations, stopping at "Grand Total"

It does NOT share any row-building code with extract_pymupdf.py. Both writers are
deliberately independent so that diff_extractors.py can compare them.

Design rules, all of which are intentional:

  * Nothing is corrected, imputed or dropped. Blank counts stay missing (pd.NA)
    and are never turned into zero.
  * Every site row is kept, including the Pimpri-Chinchwad rows. Whether a row
    belongs to Pune or PCMC is recorded in scope_tag, never by filtering.
  * Counts are stored as pandas nullable Int64, so a blank cell stays <NA>
    rather than becoming 0 or raising a dtype error.
  * Coordinates are kept as text in lat_raw / lon_raw. They are never parsed to
    float and never reordered, because the document's formatting is the
    evidence.
  * Any row that is not a site (zone heading, area heading, station subtotal,
    grand total) is written to the controls file, not to the site rows.
"""

from __future__ import annotations

import bisect
import csv
import re
import sys
from pathlib import Path

import pandas as pd
import pdfplumber
import yaml

# --------------------------------------------------------------------------
# Project layout
# --------------------------------------------------------------------------

PROJECT_ROOT = Path(__file__).resolve().parent.parent

# Field order for each ruled table, matching the column_bounds entries in
# config/extraction.yml. len(fields) + 1 == len(bounds) for every list.
CONTROL_FIELDS = ["text", "count"]
ANNEXURE_A_FIELDS = ["sn", "location", "geo", "anpr", "fixed", "ptz", "total", "go_live"]
ANNEXURE_B_FIELDS = ["sn", "station", "spot", "lat", "long", "category",
                     "poles", "fixed", "ptz", "anpr"]

# Columns of the site output. The first block is the requested schema; the
# second block holds the raw material the schema asks to be preserved.
SITE_COLUMNS = [
    "annexure", "zone", "station_raw", "section_heading", "scope_tag",
    "sn_raw", "location_raw", "lat_raw", "lon_raw", "category_raw",
    "fixed", "ptz", "anpr", "poles", "total_reported", "go_live_raw",
    "pdf_page", "row_index_on_page", "extractor",
    "location_original", "location_original_raw",
    "geo_raw", "geo_flag", "station_source",
]

CONTROL_COLUMNS = [
    "annexure", "control_type", "pdf_page", "row_index_on_page", "text",
    "count_raw", "anpr", "fixed", "ptz", "total_reported", "go_live_raw",
    "zone", "section_heading", "extractor",
]

# Count columns that must end up as nullable integers.
INT_COLUMNS = ["fixed", "ptz", "anpr", "poles", "total_reported"]

# A cell whose text is entirely digits is an integer count. Anything else
# (blank, stray punctuation) becomes pd.NA rather than being guessed at.
DIGITS_RE = re.compile(r"^\d+$")

# Zone headings read "Zone 1" ... "Zone 5"; compared after squashing whitespace.
ZONE_RE = re.compile(r"^zone\d+$")


# --------------------------------------------------------------------------
# Small text helpers
# --------------------------------------------------------------------------

def squash(text: str) -> str:
    """Lowercase and remove ALL whitespace.

    Used only for recognising structural labels (headers, "Zone 1", "Grand
    Total"). Removing every space makes the test insensitive to the line breaks
    and stray spaces that PDF extraction introduces.
    """
    return re.sub(r"\s+", "", text).lower()


def normalise_station(text: str) -> str:
    """Normalise a station name for the lookup file.

    Rule (as specified): lowercase, strip, and collapse repeated internal
    spaces to one. Nothing else: no punctuation stripping, no fuzzy matching.
    """
    return re.sub(r"\s+", " ", text.strip().lower())


def join_lines(text: str) -> str:
    """Join a multi-line cell with single spaces.

    Each line is stripped first, so a line break never turns into a double
    space. Empty lines are ignored for the joined form; the untouched original
    is kept separately in location_original.
    """
    if text is None:
        return ""
    parts = [part.strip() for part in text.split("\n")]
    return " ".join(part for part in parts if part)


def collapse_whitespace(text: str) -> str:
    """Collapse every run of whitespace to one space.

    Normalise internal whitespace for comparison; does not affect counts or
    coordinates. The two PDF libraries disagree only about spacing inside
    justified text, so this makes location text comparable while leaving
    lat_raw/lon_raw, counts and station names untouched.
    """
    if text is None:
        return ""
    return re.sub(r"\s+", " ", text).strip()


def first_number_for_control(texts: list[str]) -> str:
    """Return the last run of digits in a control row.

    The control table has a dedicated count column, but some rows draw their
    border as a merged cell, so the fallback takes the right-most number on the
    row. Nothing is summed or inferred.
    """
    numbers = re.findall(r"\d+", " ".join(texts))
    return numbers[-1] if numbers else ""


def as_int64(text: str):
    """Convert a count cell to a Python int, or pd.NA when it is not a plain
    non-negative integer. A blank cell therefore stays missing, never 0."""
    stripped = (text or "").strip()
    if DIGITS_RE.match(stripped):
        return int(stripped)
    return pd.NA


# --------------------------------------------------------------------------
# Configuration
# --------------------------------------------------------------------------

def load_config() -> dict:
    with open(PROJECT_ROOT / "config" / "extraction.yml", encoding="utf-8") as handle:
        config = yaml.safe_load(handle)
    # Allow the PDF path and output paths to be given relative to the project.
    if not Path(config["pdf_path"]).is_absolute():
        config["pdf_path"] = str(PROJECT_ROOT / config["pdf_path"])
    return config


def page_range(config: dict, key: str) -> range:
    """Inclusive printed page range from the config."""
    spec = config["pages"][key]
    return range(spec["start"], spec["end"] + 1)


# --------------------------------------------------------------------------
# pdfplumber table access
# --------------------------------------------------------------------------

TABLE_SETTINGS = {
    # "lines" uses the drawn ruling lines, which is what this document has.
    "vertical_strategy": "lines",
    "horizontal_strategy": "lines",
}


def table_rows_with_boxes(table):
    """Yield, for one pdfplumber table, a list of (cell_box, text) pairs per row.

    pdfplumber exposes the same grid twice: table.rows[i].cells holds the box of
    each cell, and table.extract() holds the text of each cell. They are aligned
    by column index, so zipping them gives text plus geometry.
    """
    extracted = table.extract()
    rows = []
    for row_index, row in enumerate(table.rows):
        texts = extracted[row_index] if row_index < len(extracted) else []
        pairs = []
        for column_index, box in enumerate(row.cells):
            if box is None:
                continue
            text = texts[column_index] if column_index < len(texts) else None
            if text is None or not str(text).strip():
                continue
            pairs.append((box, str(text)))
        rows.append(pairs)
    return rows


def assign_fields(pairs, bounds, field_names) -> dict:
    """Assign each non-empty cell to a logical field by its horizontal centre.

    The table's internal column indices differ from page to page (a stray
    interior rule can split one logical column into two boxes), so cells are
    bucketed by x-position instead of by index. Cells landing in the same
    bucket are joined with newlines, preserving the original line structure.
    """
    buckets = {name: [] for name in field_names}
    for box, text in pairs:
        centre = (box[0] + box[2]) / 2.0
        index = bisect.bisect_right(bounds, centre) - 1
        if index < 0 or index >= len(field_names):
            # Outside the configured grid: never invent a column for it.
            continue
        cleaned = text.strip()
        if cleaned:
            buckets[field_names[index]].append(cleaned)
    return {name: "\n".join(values) for name, values in buckets.items()}


def ordered_texts(pairs) -> list[str]:
    """Non-empty cell texts in left-to-right order.

    Used to identify the row's leading label (the first cell that has any
    text). A row label is always the leftmost text on the row, including for
    merged zone rows where the single cell spans the whole table.
    """
    ordered = sorted(pairs, key=lambda pair: pair[0][0])
    return [text.strip() for _, text in ordered if text.strip()]


# Exact labels that appear when the header of a table is drawn as several
# separate boxes. On this document the bordered header is sometimes detected as
# a small extra table per header cell, so "Police", "Station", "Spot", "Total"
# and "Cameras" arrive as rows of their own. They are header material, not data:
# a row whose entire text is one of these labels is dropped.
HEADER_FRAGMENTS = {
    "sn", "police", "station", "policestation", "spot",
    "proposedlocation", "proposedlocationspot", "locationname",
    "geolocation", "anpr", "fixed", "ptz", "poles", "lat", "long",
    "category", "total", "totalcameras", "cameras", "golive",
    "locationgo", "live",
}


def is_header_row(pairs) -> bool:
    """True for the repeated page-header rows.

    Rule: a header row carries the column labels and no digits at all. Site
    rows always carry an SN or a coordinate, and every heading row carries a
    subtotal, so both are excluded by the "no digits" part.

    Two shapes are recognised, both by exact match after squashing whitespace:
      * the full header line, which contains the long labels; and
      * a single header fragment such as "Police", "Station" or "Cameras",
        which is what is left when a header cell is detected as its own table.
    """
    text = " ".join(text for _, text in pairs)
    if re.search(r"\d", text):
        return False
    squashed = squash(text)
    if squashed in HEADER_FRAGMENTS:
        return True
    return ("locationname" in squashed
            or "geolocation" in squashed
            or "proposedlocation" in squashed
            or "countofcameras" in squashed
            or ("policestation" in squashed and "sn" in squashed)
            or ("cameras" in squashed and "golive" in squashed))


# --------------------------------------------------------------------------
# Station scope lookup
# --------------------------------------------------------------------------

def load_station_scope(config: dict) -> dict:
    """Read config/station_scope.csv into {normalised station: (standard, tag)}."""
    path = PROJECT_ROOT / config["station_scope_path"]
    lookup = {}
    with open(path, newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            key = normalise_station(row["station_raw"])
            lookup[key] = (row["station_standard"], row["scope_tag"].strip().upper())
    return lookup


class ScopeResolver:
    """Resolve a station name to a scope_tag, recording everything unmatched.

    Exact-match only after normalisation. A miss is never repaired and never
    guessed: it is tagged UNKNOWN and remembered so it can be added to the
    lookup file by hand.
    """

    def __init__(self, lookup: dict):
        self.lookup = lookup
        self.unmatched = {}  # normalised name -> {"raw": raw, "rows": n, "annexures": set}

    def resolve(self, station_raw, section_heading=pd.NA) -> str:
        if station_raw is None or (isinstance(station_raw, float)) or not str(station_raw).strip():
            # No station was ever established for this row; tagging it UNKNOWN
            # would be a guess, so it is left untagged.
            return pd.NA
        key = normalise_station(str(station_raw))
        if key in self.lookup:
            # An explicit entry in config/station_scope.csv always wins over the
            # heading fallback below.
            return self.lookup[key][1]

        # Heading fallback, applied only when the lookup has no entry:
        #   * a row whose section heading is exactly "Zone 1".."Zone 5" is Pune;
        #   * a row whose section heading mentions Pimpri Chinchwad is PCMC.
        # This infers scope from where the row sits in the document, never from
        # the station's spelling, so it cannot invent a match.
        heading = "" if section_heading is pd.NA else str(section_heading).strip()
        if heading in {"Zone 1", "Zone 2", "Zone 3", "Zone 4", "Zone 5"}:
            return "PUNE"
        if "pimpri chinchwad" in heading.lower():
            return "PCMC"

        # Neither the lookup nor the heading rules could place this row.
        return "UNKNOWN"

    def note(self, station_raw, annexure: str) -> None:
        """Remember an unmatched raw name, with a row count for the report."""
        if station_raw is None or not str(station_raw).strip():
            return
        key = normalise_station(str(station_raw))
        if key in self.lookup:
            return
        entry = self.unmatched.setdefault(
            key, {"raw": join_lines(str(station_raw)), "rows": 0, "annexures": set()}
        )
        entry["rows"] += 1
        entry["annexures"].add(annexure)


# --------------------------------------------------------------------------
# Calibration
# --------------------------------------------------------------------------

def cluster_positions(values, tolerance: float = 12.0) -> list[float]:
    """Collapse near-duplicate x-coordinates into one boundary per cluster.

    The document draws each cell border as several lines a few points apart.
    Walking the sorted values and starting a new cluster when the gap exceeds
    `tolerance` reduces them to one representative position per real border.
    """
    clusters = []
    current = []
    for value in sorted(values):
        if current and value - current[-1] > tolerance:
            clusters.append(sum(current) / len(current))
            current = []
        current.append(value)
    if current:
        clusters.append(sum(current) / len(current))
    return clusters


def print_calibration(pdf, config: dict) -> None:
    """Print the detected column x-positions for the calibration page.

    This is the calibration step: if the printed positions drift away from the
    configured bounds, the column map in config/extraction.yml is stale and the
    extraction should not be trusted.
    """
    page_number = config["calibration_page"]
    page = pdf.pages[page_number - 1]
    tables = page.find_tables(table_settings=TABLE_SETTINGS)
    print(f"calibration page: {page_number}")
    print(f"  page size: {page.width:.1f} x {page.height:.1f} pt")
    print(f"  tables detected: {len(tables)}")
    if not tables:
        print("  WARNING: no tables detected on the calibration page")
        return
    top, bottom = tables[0].bbox[1], tables[0].bbox[3]
    xs = [edge["x0"] for edge in page.vertical_edges
          if tables[0].bbox[0] - 2 <= edge["x0"] <= tables[0].bbox[2] + 2
          and top - 2 <= edge["top"] <= bottom + 2]
    detected = cluster_positions(xs)
    print(f"  detected column x-positions: {[round(v, 1) for v in detected]}")
    print(f"  configured bounds (annexure_a): {config['column_bounds']['annexure_a']}")
    for bound in config["column_bounds"]["annexure_a"]:
        nearest = min(detected, key=lambda value: abs(value - bound)) if detected else None
        if nearest is None or abs(nearest - bound) > 6:
            print(f"  WARNING: configured bound {bound} has no edge within 6pt")
    print()


# --------------------------------------------------------------------------
# Control table, pages 81-82
# --------------------------------------------------------------------------

def extract_control_table(pdf, config: dict, resolver: ScopeResolver) -> list[dict]:
    """Read the small control table and return one dict per control row.

    Every row is kept here (including per-station counts), because this table is
    a control, not a site list.
    """
    bounds = config["column_bounds"]["control_table"]
    rows_out = []
    zone = pd.NA
    section = pd.NA

    for page_number in page_range(config, "control_table"):
        page = pdf.pages[page_number - 1]
        tables = sorted(page.find_tables(table_settings=TABLE_SETTINGS),
                        key=lambda table: table.bbox[1])
        row_index = 0
        for table in tables:
            for pairs in table_rows_with_boxes(table):
                if not pairs:
                    continue
                texts = ordered_texts(pairs)
                if not texts:
                    continue
                joined = " ".join(texts)
                squashed = squash(joined)

                # The repeated column header is dropped, never treated as data.
                if is_header_row(pairs):
                    continue

                # The table's own title row.
                if "existingcctvcount" in squashed:
                    rows_out.append({
                        "annexure": "control_table", "control_type": "table_title",
                        "pdf_page": page_number, "row_index_on_page": row_index,
                        "text": join_lines(joined), "count_raw": "",
                        "anpr": pd.NA, "fixed": pd.NA, "ptz": pd.NA,
                        "total_reported": pd.NA, "go_live_raw": pd.NA,
                        "zone": pd.NA, "section_heading": pd.NA,
                        "extractor": "pdfplumber",
                    })
                    row_index += 1
                    continue

                fields = assign_fields(pairs, bounds, CONTROL_FIELDS)
                label = join_lines(fields["text"]) or join_lines(texts[0])
                label_squashed = squash(label)

                if ZONE_RE.match(label_squashed):
                    zone = label
                    control_type = "zone_heading"
                elif "area" in label_squashed:
                    # e.g. "Pimpri Chinchwad Area": starts a new area block.
                    section = label
                    control_type = "area_heading"
                elif "grandtotal" in label_squashed:
                    control_type = "grand_total"
                else:
                    control_type = "station_count"

                count_cell = fields["count"].strip()
                count_raw = count_cell if DIGITS_RE.match(count_cell) else first_number_for_control(texts)

                rows_out.append({
                    "annexure": "control_table", "control_type": control_type,
                    "pdf_page": page_number, "row_index_on_page": row_index,
                    "text": label, "count_raw": count_raw,
                    "anpr": pd.NA, "fixed": pd.NA, "ptz": pd.NA,
                    "total_reported": as_int64(count_raw), "go_live_raw": pd.NA,
                    "zone": zone, "section_heading": section,
                    "extractor": "pdfplumber",
                })
                row_index += 1
    return rows_out


# --------------------------------------------------------------------------
# Annexure A, pages 83-99
# --------------------------------------------------------------------------

def split_geo(geo_text: str):
    """Split an Annexure A Geo Location cell into (lat, lon, raw, flag).

    The cell must contain exactly one comma: "lat,lon". If it does not, the raw
    string is preserved and both coordinates stay missing, with a flag saying
    so. Nothing is repaired, reformatted or reordered.
    """
    raw = join_lines(geo_text)
    if not raw:
        return pd.NA, pd.NA, pd.NA, "missing_geo"
    parts = raw.split(",")
    if len(parts) != 2 or not parts[0].strip() or not parts[1].strip():
        return pd.NA, pd.NA, raw, "not_single_pair"
    return parts[0].strip(), parts[1].strip(), pd.NA, pd.NA


def extract_annexure_a(pdf, config: dict, resolver: ScopeResolver):
    """Read Annexure A into site rows plus control rows."""
    bounds = config["column_bounds"]["annexure_a"]
    site_rows = []
    control_rows = []
    dropped_headers = []

    zone = pd.NA
    section = pd.NA
    station = None          # last station sub-header actually seen

    for page_number in page_range(config, "annexure_a"):
        page = pdf.pages[page_number - 1]
        tables = sorted(page.find_tables(table_settings=TABLE_SETTINGS),
                        key=lambda table: table.bbox[1])
        dropped_on_page = 0
        row_index = 0

        for table in tables:
            for pairs in table_rows_with_boxes(table):
                if not pairs:
                    continue
                texts = ordered_texts(pairs)
                if not texts:
                    continue

                # Rule: repeated page headers are dropped by exact label match.
                if is_header_row(pairs):
                    dropped_on_page += 1
                    continue

                fields = assign_fields(pairs, bounds, ANNEXURE_A_FIELDS)
                first_text = texts[0]
                first_squashed = squash(first_text)
                sn_raw = fields["sn"].strip()

                # Grand total: belongs in the controls file, not in the sites.
                if "grandtotal" in first_squashed or "grandtotal" in squash(fields["location"]):
                    control_rows.append({
                        "annexure": "annexure_a", "control_type": "grand_total",
                        "pdf_page": page_number, "row_index_on_page": row_index,
                        "text": first_text, "count_raw": "",
                        "anpr": as_int64(fields["anpr"]),
                        "fixed": as_int64(fields["fixed"]),
                        "ptz": as_int64(fields["ptz"]),
                        "total_reported": as_int64(fields["total"]),
                        "go_live_raw": fields["go_live"] or pd.NA,
                        "zone": zone, "section_heading": section,
                        "extractor": "pdfplumber",
                    })
                    row_index += 1
                    continue

                # A row with no SN is a heading of some kind, never a site.
                if not sn_raw:
                    if ZONE_RE.match(first_squashed):
                        zone = first_text
                        # section_heading is the nearest zone OR area heading,
                        # so Pune rows carry their zone and PCMC rows carry the
                        # "Pimpri Chinchwad area" heading that follows.
                        section = first_text
                        station = None   # a station block never spans zones
                        control_rows.append({
                            "annexure": "annexure_a", "control_type": "zone_heading",
                            "pdf_page": page_number, "row_index_on_page": row_index,
                            "text": first_text, "count_raw": "",
                            "anpr": as_int64(fields["anpr"]),
                            "fixed": as_int64(fields["fixed"]),
                            "ptz": as_int64(fields["ptz"]),
                            "total_reported": as_int64(fields["total"]),
                            "go_live_raw": fields["go_live"] or pd.NA,
                            "zone": zone, "section_heading": section,
                            "extractor": "pdfplumber",
                        })
                    elif "area" in first_squashed:
                        # Area heading, e.g. "Pimpri Chinchwad area". Sets the
                        # section for the Pune/PCMC split.
                        section = first_text
                        station = None
                        control_rows.append({
                            "annexure": "annexure_a", "control_type": "area_heading",
                            "pdf_page": page_number, "row_index_on_page": row_index,
                            "text": first_text, "count_raw": "",
                            "anpr": as_int64(fields["anpr"]),
                            "fixed": as_int64(fields["fixed"]),
                            "ptz": as_int64(fields["ptz"]),
                            "total_reported": as_int64(fields["total"]),
                            "go_live_raw": fields["go_live"] or pd.NA,
                            "zone": zone, "section_heading": section,
                            "extractor": "pdfplumber",
                        })
                    elif first_squashed == "total":
                        # The Pune-area subtotal printed just before the Pimpri
                        # Chinchwad block. It is a control row, not a station, so
                        # it must not become the current station for later rows.
                        control_rows.append({
                            "annexure": "annexure_a", "control_type": "section_total",
                            "pdf_page": page_number, "row_index_on_page": row_index,
                            "text": join_lines(first_text), "count_raw": "",
                            "anpr": as_int64(fields["anpr"]),
                            "fixed": as_int64(fields["fixed"]),
                            "ptz": as_int64(fields["ptz"]),
                            "total_reported": as_int64(fields["total"]),
                            "go_live_raw": fields["go_live"] or pd.NA,
                            "zone": zone, "section_heading": section,
                            "extractor": "pdfplumber",
                        })
                    elif any(as_int64(fields[key]) is not pd.NA
                             for key in ("anpr", "fixed", "ptz", "total")):
                        # Station sub-header: carries the block subtotal and is
                        # the only legitimate source of a station name here.
                        # Requiring an actual number is the safety net: a row of
                        # header debris has no counts, so it can never become the
                        # station for the rows below it.
                        station = join_lines(first_text)
                        control_rows.append({
                            "annexure": "annexure_a", "control_type": "station_subtotal",
                            "pdf_page": page_number, "row_index_on_page": row_index,
                            "text": station, "count_raw": "",
                            "anpr": as_int64(fields["anpr"]),
                            "fixed": as_int64(fields["fixed"]),
                            "ptz": as_int64(fields["ptz"]),
                            "total_reported": as_int64(fields["total"]),
                            "go_live_raw": fields["go_live"] or pd.NA,
                            "zone": zone, "section_heading": section,
                            "extractor": "pdfplumber",
                        })
                    else:
                        # Text-only row that is not a numbered heading. Recorded
                        # as a control and deliberately left unable to change the
                        # current station.
                        control_rows.append({
                            "annexure": "annexure_a", "control_type": "unclassified",
                            "pdf_page": page_number, "row_index_on_page": row_index,
                            "text": join_lines(first_text), "count_raw": "",
                            "anpr": pd.NA, "fixed": pd.NA, "ptz": pd.NA,
                            "total_reported": pd.NA, "go_live_raw": pd.NA,
                            "zone": zone, "section_heading": section,
                            "extractor": "pdfplumber",
                        })
                    row_index += 1
                    continue

                # A numeric SN may still belong to a subtotal row if extraction
                # failed to isolate the label, so require the row to look like a
                # site: an SN and either a location or a geo cell.
                location_raw = collapse_whitespace(fields["location"])
                location_original_raw = fields["location"] or pd.NA
                if not location_raw and not fields["geo"].strip():
                    control_rows.append({
                        "annexure": "annexure_a", "control_type": "unclassified",
                        "pdf_page": page_number, "row_index_on_page": row_index,
                        "text": join_lines(" ".join(texts)), "count_raw": "",
                        "anpr": as_int64(fields["anpr"]),
                        "fixed": as_int64(fields["fixed"]),
                        "ptz": as_int64(fields["ptz"]),
                        "total_reported": as_int64(fields["total"]),
                        "go_live_raw": fields["go_live"] or pd.NA,
                        "zone": zone, "section_heading": section,
                        "extractor": "pdfplumber",
                    })
                    row_index += 1
                    continue

                lat_raw, lon_raw, geo_raw, geo_flag = split_geo(fields["geo"])
                station_raw = station if station else pd.NA
                # Heading fallback is allowed only when the lookup misses, and
                # the heading is passed in for exactly that decision.
                scope_tag = resolver.resolve(station_raw, section)
                resolver.note(station_raw, "annexure_a")

                site_rows.append({
                    "annexure": "annexure_a",
                    "zone": zone,
                    "station_raw": station_raw,
                    "section_heading": section,
                    "scope_tag": scope_tag,
                    "sn_raw": sn_raw,
                    "location_raw": location_raw,
                    "lat_raw": lat_raw,
                    "lon_raw": lon_raw,
                    "category_raw": pd.NA,           # Annexure A has no category
                    "fixed": as_int64(fields["fixed"]),
                    "ptz": as_int64(fields["ptz"]),
                    "anpr": as_int64(fields["anpr"]),
                    "poles": pd.NA,                  # Annexure A has no poles
                    "total_reported": as_int64(fields["total"]),
                    "go_live_raw": fields["go_live"] or pd.NA,
                    "pdf_page": page_number,
                    "row_index_on_page": row_index,
                    "extractor": "pdfplumber",
                    "location_original": collapse_whitespace(fields["location"]) or pd.NA,
                    "location_original_raw": location_original_raw,
                    "geo_raw": geo_raw,
                    "geo_flag": geo_flag,
                    # Annexure A has no station column: every station here comes
                    # from a sub-header that was actually seen.
                    "station_source": "inherited_from_header" if station else pd.NA,
                })
                row_index += 1

        if dropped_on_page:
            dropped_headers.append({
                "pdf_page": page_number, "annexure": "annexure_a",
                "dropped_rows": dropped_on_page, "extractor": "pdfplumber",
            })
    return site_rows, control_rows, dropped_headers


# --------------------------------------------------------------------------
# Annexure B, pages 100-166
# --------------------------------------------------------------------------

def extract_annexure_b(pdf, config: dict, resolver: ScopeResolver):
    """Read Annexure B into site rows plus control rows.

    Stops at the first row whose text contains "Grand Total". Annexure C begins
    immediately after that row on page 166 and is never read.
    """
    bounds = config["column_bounds"]["annexure_b"]
    stop_text = squash(config["stop"]["annexure_b_stop_text"])
    site_rows = []
    control_rows = []
    dropped_headers = []

    zone = pd.NA
    station_seen = None      # last station actually printed in a station cell
    stopped = False
    pages_read = 0

    for page_number in page_range(config, "annexure_b"):
        if stopped:
            break
        pages_read += 1
        page = pdf.pages[page_number - 1]
        tables = sorted(page.find_tables(table_settings=TABLE_SETTINGS),
                        key=lambda table: table.bbox[1])
        dropped_on_page = 0
        row_index = 0

        for table in tables:
            if stopped:
                break
            for pairs in table_rows_with_boxes(table):
                if not pairs:
                    continue
                texts = ordered_texts(pairs)
                if not texts:
                    continue

                if is_header_row(pairs):
                    dropped_on_page += 1
                    continue

                fields = assign_fields(pairs, bounds, ANNEXURE_B_FIELDS)
                first_text = texts[0]
                first_squashed = squash(first_text)
                row_squashed = squash(" ".join(texts))
                sn_raw = fields["sn"].strip()

                # Stop rule: the first row containing the stop text ends the
                # annexure. It is recorded as a control, then reading stops
                # immediately; nothing after it is touched.
                if stop_text in row_squashed:
                    control_rows.append({
                        "annexure": "annexure_b", "control_type": "grand_total",
                        "pdf_page": page_number, "row_index_on_page": row_index,
                        "text": join_lines(" ".join(texts)), "count_raw": "",
                        "anpr": as_int64(fields["anpr"]),
                        "fixed": as_int64(fields["fixed"]),
                        "ptz": as_int64(fields["ptz"]),
                        "total_reported": pd.NA,
                        "go_live_raw": pd.NA,
                        "zone": zone, "section_heading": zone,
                        "extractor": "pdfplumber",
                    })
                    stopped = True
                    break

                # A merged zone row has one wide cell whose text is just the
                # zone label; it sets the zone for the rows below it.
                if ZONE_RE.match(first_squashed):
                    zone = first_text
                    station_seen = None
                    control_rows.append({
                        "annexure": "annexure_b", "control_type": "zone_heading",
                        "pdf_page": page_number, "row_index_on_page": row_index,
                        "text": first_text, "count_raw": "",
                        "anpr": pd.NA, "fixed": pd.NA, "ptz": pd.NA,
                        "total_reported": pd.NA, "go_live_raw": pd.NA,
                        "zone": zone, "section_heading": zone,
                        "extractor": "pdfplumber",
                    })
                    row_index += 1
                    continue

                if not sn_raw:
                    # Not a site and not a zone heading: keep it as a control so
                    # nothing is silently lost.
                    control_rows.append({
                        "annexure": "annexure_b", "control_type": "unclassified",
                        "pdf_page": page_number, "row_index_on_page": row_index,
                        "text": join_lines(" ".join(texts)), "count_raw": "",
                        "anpr": as_int64(fields["anpr"]),
                        "fixed": as_int64(fields["fixed"]),
                        "ptz": as_int64(fields["ptz"]),
                        "total_reported": pd.NA, "go_live_raw": pd.NA,
                        "zone": zone, "section_heading": zone,
                        "extractor": "pdfplumber",
                    })
                    row_index += 1
                    continue

                # Station name: use the cell when it is printed. When it is
                # blank the value is inherited from the block's station cell,
                # but only if such a cell was actually seen for this block.
                station_cell = join_lines(fields["station"])
                if station_cell:
                    station_seen = station_cell
                    station_raw = station_cell
                    station_source = "cell"
                elif station_seen is not None:
                    station_raw = station_seen
                    station_source = "inherited_from_header"
                else:
                    station_raw = pd.NA
                    station_source = pd.NA

                # Heading fallback uses the zone heading that governs this row.
                scope_tag = resolver.resolve(station_raw, zone)
                resolver.note(station_raw, "annexure_b")

                site_rows.append({
                    "annexure": "annexure_b",
                    "zone": zone,
                    "station_raw": station_raw,
                    "section_heading": zone,        # Annexure B has no area headings
                    "scope_tag": scope_tag,
                    "sn_raw": sn_raw,
                    "location_raw": collapse_whitespace(fields["spot"]),
                    "lat_raw": join_lines(fields["lat"]) or pd.NA,
                    "lon_raw": join_lines(fields["long"]) or pd.NA,
                    "category_raw": join_lines(fields["category"]) or pd.NA,
                    "fixed": as_int64(fields["fixed"]),
                    "ptz": as_int64(fields["ptz"]),
                    "anpr": as_int64(fields["anpr"]),
                    "poles": as_int64(fields["poles"]),
                    "total_reported": pd.NA,        # Annexure B has no total column
                    "go_live_raw": pd.NA,           # Annexure B has no go-live column
                    "pdf_page": page_number,
                    "row_index_on_page": row_index,
                    "extractor": "pdfplumber",
                    "location_original": collapse_whitespace(fields["spot"]) or pd.NA,
                    "location_original_raw": fields["spot"] or pd.NA,
                    "geo_raw": pd.NA,               # Annexure B has separate lat/long
                    "geo_flag": pd.NA,              # flags apply to Annexure A only
                    "station_source": station_source,
                })
                row_index += 1

        if dropped_on_page:
            dropped_headers.append({
                "pdf_page": page_number, "annexure": "annexure_b",
                "dropped_rows": dropped_on_page, "extractor": "pdfplumber",
            })

    # Stop-rule assertions. These are checks on what was read, not corrections.
    assert stopped, "Annexure B stop text was never found; reading did not stop as expected"
    assert pages_read <= config["pages"]["annexure_b"]["end"] - config["pages"]["annexure_b"]["start"] + 1
    assert not any("annexurec" in squash(row["location_raw"] or "")
                   for row in site_rows), "Annexure C content leaked into site rows"
    return site_rows, control_rows, dropped_headers, pages_read


# --------------------------------------------------------------------------
# Writing and reporting
# --------------------------------------------------------------------------

def to_frame(rows: list[dict], columns: list[str]) -> pd.DataFrame:
    """Build a DataFrame with a fixed column order and nullable integer counts."""
    frame = pd.DataFrame(rows, columns=columns)
    for column in INT_COLUMNS:
        if column in frame.columns:
            # pd.array keeps <NA> and produces dtype Int64 even when the whole
            # column is empty.
            frame[column] = pd.array(list(frame[column]), dtype="Int64")
    return frame


def write_csv(frame: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    frame.to_csv(path, index=False, encoding="utf-8")


def write_unmatched(resolver: ScopeResolver, path: Path, extractor: str) -> int:
    """Write every station name that was not found in the lookup file."""
    rows = []
    for key, entry in sorted(resolver.unmatched.items()):
        rows.append({
            "station_raw": entry["raw"],
            "station_normalised": key,
            "row_count": entry["rows"],
            "annexures": ";".join(sorted(entry["annexures"])),
            "extractor": extractor,
        })
    frame = pd.DataFrame(rows, columns=["station_raw", "station_normalised",
                                        "row_count", "annexures", "extractor"])
    write_csv(frame, path)
    return len(rows)


def print_summary(site_frame: pd.DataFrame, control_frame: pd.DataFrame,
                  unmatched_count: int, dropped_count: int) -> None:
    print("=" * 78)
    print("EXTRACTOR 1 (pdfplumber, lines)")
    print("=" * 78)
    print(f"site rows: {len(site_frame)}")
    print("\nrows per annexure:")
    for annexure, count in site_frame["annexure"].value_counts().sort_index().items():
        print(f"  {annexure}: {count}")
    print("\nrows per scope_tag:")
    for tag, count in site_frame["scope_tag"].fillna("<NA>").value_counts().sort_index().items():
        print(f"  {tag}: {count}")
    print("\nrows per scope_tag within annexure:")
    grouped = site_frame.groupby(["annexure", site_frame["scope_tag"].fillna("<NA>")],
                                 dropna=False).size()
    for (annexure, tag), count in grouped.items():
        print(f"  {annexure} / {tag}: {count}")
    print(f"\ncontrol rows: {len(control_frame)}")
    print(f"unmatched station names: {unmatched_count}")
    print(f"flagged rows (geo_flag set): {int(site_frame['geo_flag'].notna().sum())}")
    print(f"rows dropped as repeated page headers: {dropped_count}")
    print(f"count column dtypes: "
          f"{ {column: str(site_frame[column].dtype) for column in INT_COLUMNS} }")
    print(f"rows with station inherited from a sub-header: "
          f"{int((site_frame['station_source'] == 'inherited_from_header').sum())}")
    print(f"rows with station from a cell: "
          f"{int((site_frame['station_source'] == 'cell').sum())}")


def main() -> int:
    config = load_config()
    resolver = ScopeResolver(load_station_scope(config))

    with pdfplumber.open(config["pdf_path"]) as pdf:
        print_calibration(pdf, config)

        control_rows = extract_control_table(pdf, config, resolver)
        a_sites, a_controls, a_dropped = extract_annexure_a(pdf, config, resolver)
        b_sites, b_controls, b_dropped, pages_read = extract_annexure_b(pdf, config, resolver)

    print(f"Annexure B pages actually read: {pages_read} "
          f"(stopped at '{config['stop']['annexure_b_stop_text']}')")
    print()

    site_rows = a_sites + b_sites
    site_frame = to_frame(site_rows, SITE_COLUMNS)
    control_frame = to_frame(control_rows + a_controls + b_controls, CONTROL_COLUMNS)
    dropped = a_dropped + b_dropped

    write_csv(site_frame, PROJECT_ROOT / config["outputs"]["sites_pdfplumber"])
    write_csv(control_frame, PROJECT_ROOT / config["outputs"]["controls"])
    write_csv(pd.DataFrame(dropped, columns=["pdf_page", "annexure", "dropped_rows", "extractor"]),
              PROJECT_ROOT / config["outputs"]["dropped_headers"])
    unmatched_count = write_unmatched(resolver, PROJECT_ROOT / config["outputs"]["unmatched"],
                                      "pdfplumber")

    print_summary(site_frame, control_frame, unmatched_count,
                  sum(row["dropped_rows"] for row in dropped))
    return 0


if __name__ == "__main__":
    sys.exit(main())

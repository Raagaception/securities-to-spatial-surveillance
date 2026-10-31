#!/usr/bin/env python3
"""Extractor 2: PyMuPDF (page.find_tables()).

All paths are resolved relative to the REPOSITORY ROOT (the parent directory of
scripts/), via pathlib. Run it from the repository root:

    python scripts/extract_pymupdf.py

or from anywhere by its full path; the working directory does not matter and no
absolute or machine-specific paths are used.

Independent implementation of the same three regions as extract_pdfplumber.py. It
shares no row-building code with that script on purpose: every helper below is
written separately, so that diff_extractors.py compares two genuinely different
reads of the document rather than one read twice.

The grid (which cell sits where) comes from PyMuPDF's find_tables(). The text
inside a cell is taken with page.get_text("text", clip=cell_rect) rather than
from Table.extract(), because Table.extract() joins words with its own spacing
rules and produced damaged strings such as "Vish ramb/aug" and "Z one 1" on
this document. Clipping the normal text layer to the cell rectangle returns
"Vishrambaug" and "Zone 1" instead.

The same invariants as extractor 1 hold: nothing is corrected, imputed or
dropped; blanks stay pd.NA; coordinates stay text; every site row is kept and
classified only through scope_tag.
"""

from __future__ import annotations

import csv
import re
import sys
from pathlib import Path

import pandas as pd
import pymupdf
import yaml

PROJECT_ROOT = Path(__file__).resolve().parent.parent

CONTROL_FIELDS = ["text", "count"]
ANNEXURE_A_FIELDS = ["sn", "location", "geo", "anpr", "fixed", "ptz", "total", "go_live"]
ANNEXURE_B_FIELDS = ["sn", "station", "spot", "lat", "long", "category",
                     "poles", "fixed", "ptz", "anpr"]

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

INT_COLUMNS = ["fixed", "ptz", "anpr", "poles", "total_reported"]

ONLY_DIGITS = re.compile(r"^\d+$")
ZONE_LABEL = re.compile(r"^zone\d+$")


# --------------------------------------------------------------------------
# Text helpers (own implementations)
# --------------------------------------------------------------------------

def squeeze(value: str) -> str:
    """Lowercase with all whitespace removed, for structural label tests only."""
    out = []
    for character in value.lower():
        if not character.isspace():
            out.append(character)
    return "".join(out)


def station_key(value: str) -> str:
    """Lookup key: lowercase, trimmed, internal whitespace runs collapsed."""
    words = value.lower().split()
    return " ".join(words)


def one_line(value: str) -> str:
    """Collapse a multi-line cell into one line separated by single spaces."""
    if value is None:
        return ""
    collected = []
    for piece in value.splitlines():
        stripped = piece.strip()
        if stripped:
            collected.append(stripped)
    return " ".join(collected)


def tight_space(value: str) -> str:
    """Reduce any run of whitespace to a single space.

    Normalise internal whitespace for comparison; does not affect counts or
    coordinates. Only location text goes through this: coordinates, counts and
    station names are passed through exactly as read.
    """
    if value is None:
        return ""
    return " ".join(value.split())


def integer_or_na(value: str):
    """Return int for a digits-only cell, else pd.NA. A blank never becomes 0."""
    text = (value or "").strip()
    if ONLY_DIGITS.match(text):
        return int(text)
    return pd.NA


def trailing_number(texts) -> str:
    """Right-most run of digits on a control row (fallback for merged borders)."""
    found = []
    for text in texts:
        found.extend(re.findall(r"\d+", text))
    if not found:
        return ""
    return found[-1]


# --------------------------------------------------------------------------
# Configuration and scope lookup
# --------------------------------------------------------------------------

def read_config() -> dict:
    with open(PROJECT_ROOT / "config" / "extraction.yml", encoding="utf-8") as handle:
        config = yaml.safe_load(handle)
    if not Path(config["pdf_path"]).is_absolute():
        config["pdf_path"] = str(PROJECT_ROOT / config["pdf_path"])
    return config


def pages_of(config: dict, name: str):
    spec = config["pages"][name]
    return list(range(spec["start"], spec["end"] + 1))


def read_scope_file(config: dict) -> dict:
    """station_key -> (standard name, scope tag). Exact match only, no fuzzing."""
    mapping = {}
    path = PROJECT_ROOT / config["station_scope_path"]
    with open(path, newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        for record in reader:
            mapping[station_key(record["station_raw"])] = (
                record["station_standard"],
                record["scope_tag"].strip().upper(),
            )
    return mapping


class Tagger:
    """Assign scope tags and remember names that the lookup file does not cover."""

    def __init__(self, mapping: dict):
        self.mapping = mapping
        self.misses = {}

    def tag_for(self, station_raw, section_heading=pd.NA):
        if station_raw is None:
            return pd.NA
        if isinstance(station_raw, float) and pd.isna(station_raw):
            return pd.NA
        text = str(station_raw).strip()
        if not text:
            return pd.NA
        key = station_key(text)
        if key in self.mapping:
            # An explicit row in config/station_scope.csv is always decisive;
            # the heading fallback below is consulted only on a miss.
            return self.mapping[key][1]

        # Heading fallback for stations the lookup does not cover:
        #   "Zone 1".."Zone 5" as the section heading  -> PUNE
        #   section heading mentioning Pimpri Chinchwad -> PCMC
        # This reads scope from the row's position in the document, not from the
        # station's spelling, so it cannot manufacture a name match.
        heading = "" if section_heading is pd.NA else str(section_heading).strip()
        zone_labels = ("Zone 1", "Zone 2", "Zone 3", "Zone 4", "Zone 5")
        if heading in zone_labels:
            return "PUNE"
        if "pimpri chinchwad" in heading.lower():
            return "PCMC"

        # Nothing in the lookup and nothing in the heading: still unknown.
        return "UNKNOWN"

    def remember(self, station_raw, annexure: str) -> None:
        if station_raw is None or isinstance(station_raw, float):
            return
        text = str(station_raw).strip()
        if not text:
            return
        key = station_key(text)
        if key in self.mapping:
            return
        record = self.misses.setdefault(key, {"raw": one_line(text), "rows": 0, "where": set()})
        record["rows"] += 1
        record["where"].add(annexure)


# --------------------------------------------------------------------------
# Grid access
# --------------------------------------------------------------------------

def cell_rects(row):
    """Cell rectangles of one PyMuPDF table row, skipping cells that do not exist."""
    return [cell for cell in row.cells if cell is not None]


def cell_text(page, rect) -> str:
    """Text of one cell, taken from the text layer clipped to the cell box.

    clip() restricts the extraction to glyphs inside the rectangle, which keeps
    columns from bleeding into each other while preserving real line breaks.
    """
    rectangle = pymupdf.Rect(rect)
    return page.get_text("text", clip=rectangle) or ""


def field_for_x(centre: float, bounds, names) -> str | None:
    """Return the field whose interval contains this x centre.

    bounds[i] .. bounds[i+1] is the interval of names[i]. A centre outside the
    outer bounds belongs to no column and is ignored rather than forced into the
    nearest one.
    """
    for index, name in enumerate(names):
        left = bounds[index]
        right = bounds[index + 1]
        if left <= centre < right:
            return name
    return None


def build_fields(page, row, bounds, names) -> dict:
    """Collect the text of every cell into its logical field.

    Several boxes can land in the same field when a page draws an extra interior
    rule; their texts are stacked with newlines so the original line structure
    survives.
    """
    collected = {name: [] for name in names}
    for rect in cell_rects(row):
        text = cell_text(page, rect)
        if not text.strip():
            continue
        centre = (rect[0] + rect[2]) / 2.0
        name = field_for_x(centre, bounds, names)
        if name is None:
            continue
        collected[name].append(text.strip())
    return {name: "\n".join(chunks) for name, chunks in collected.items()}


def labels_left_to_right(page, row):
    """Non-empty cell texts ordered by their left edge."""
    items = []
    for rect in cell_rects(row):
        text = cell_text(page, rect).strip()
        if text:
            items.append((rect[0], text))
    items.sort(key=lambda item: item[0])
    return [text for _, text in items]


# A header cell can be detected as its own little table, so a single label such
# as "Police", "Station", "Spot", "Total" or "Cameras" can arrive as a row.
# These are header material, not data, and are dropped by exact match.
HEADER_FRAGMENTS = {
    "sn", "police", "station", "policestation", "spot",
    "proposedlocation", "proposedlocationspot", "locationname",
    "geolocation", "anpr", "fixed", "ptz", "poles", "lat", "long",
    "category", "total", "totalcameras", "cameras", "golive",
    "locationgo", "live",
}


def looks_like_page_header(page, row) -> bool:
    """Repeated page header: carries column labels and no digits at all.

    Site rows always contain an SN or a coordinate, and heading rows always
    contain a subtotal, so any row with a digit is excluded. The label test
    distinguishes the header from other text-only rows, and recognises both the
    full header line and the single-label fragments described above.
    """
    joined = " ".join(cell_text(page, rect) for rect in cell_rects(row))
    if re.search(r"\d", joined):
        return False
    squashed = squeeze(joined)
    if squashed in HEADER_FRAGMENTS:
        return True
    markers = (
        "locationname",
        "geolocation",
        "proposedlocation",
    )
    if any(marker in squashed for marker in markers):
        return True
    if "policestation" in squashed and "sn" in squashed:
        return True
    if "countofcameras" in squashed:
        return True
    if "cameras" in squashed and "golive" in squashed:
        return True
    return False


def table_rows(page):
    """All rows of all tables on a page, top to bottom, with their table index."""
    finder = page.find_tables()
    tables = sorted(finder.tables, key=lambda table: table.bbox[1])
    for table_index, table in enumerate(tables):
        for row in table.rows:
            yield table_index, row


# --------------------------------------------------------------------------
# Control table, pages 81-82
# --------------------------------------------------------------------------

def read_control_table(doc, config: dict, tagger: Tagger) -> list[dict]:
    bounds = config["column_bounds"]["control_table"]
    produced = []
    zone = pd.NA
    section = pd.NA

    for page_number in pages_of(config, "control_table"):
        page = doc[page_number - 1]
        position = 0
        for _, row in table_rows(page):
            labels = labels_left_to_right(page, row)
            if not labels:
                continue
            joined = " ".join(labels)
            squashed = squeeze(joined)

            if looks_like_page_header(page, row):
                continue

            if "existingcctvcount" in squashed:
                produced.append({
                    "annexure": "control_table", "control_type": "table_title",
                    "pdf_page": page_number, "row_index_on_page": position,
                    "text": one_line(joined), "count_raw": "",
                    "anpr": pd.NA, "fixed": pd.NA, "ptz": pd.NA,
                    "total_reported": pd.NA, "go_live_raw": pd.NA,
                    "zone": pd.NA, "section_heading": pd.NA,
                    "extractor": "pymupdf",
                })
                position += 1
                continue

            fields = build_fields(page, row, bounds, CONTROL_FIELDS)
            label = one_line(fields["text"]) or one_line(labels[0])
            label_squashed = squeeze(label)

            if ZONE_LABEL.match(label_squashed):
                zone = label
                control_type = "zone_heading"
            elif "area" in label_squashed:
                section = label
                control_type = "area_heading"
            elif "grandtotal" in label_squashed:
                control_type = "grand_total"
            else:
                control_type = "station_count"

            count_value = fields["count"].strip()
            if not ONLY_DIGITS.match(count_value):
                count_value = trailing_number(labels)

            produced.append({
                "annexure": "control_table", "control_type": control_type,
                "pdf_page": page_number, "row_index_on_page": position,
                "text": label, "count_raw": count_value,
                "anpr": pd.NA, "fixed": pd.NA, "ptz": pd.NA,
                "total_reported": integer_or_na(count_value), "go_live_raw": pd.NA,
                "zone": zone, "section_heading": section,
                "extractor": "pymupdf",
            })
            position += 1
    return produced


# --------------------------------------------------------------------------
# Annexure A, pages 83-99
# --------------------------------------------------------------------------

def split_coordinates(text: str):
    """Split "lat,lon" into its two halves.

    Exactly one comma is required. Otherwise the raw text is returned untouched
    and both coordinates stay missing, flagged so a human can look at it.
    """
    raw = one_line(text)
    if not raw:
        return pd.NA, pd.NA, pd.NA, "missing_geo"
    halves = raw.split(",")
    if len(halves) != 2:
        return pd.NA, pd.NA, raw, "not_single_pair"
    left, right = halves[0].strip(), halves[1].strip()
    if not left or not right:
        return pd.NA, pd.NA, raw, "not_single_pair"
    return left, right, pd.NA, pd.NA


def read_annexure_a(doc, config: dict, tagger: Tagger):
    bounds = config["column_bounds"]["annexure_a"]
    sites = []
    controls = []
    header_drops = []

    zone = pd.NA
    section = pd.NA
    station = None

    for page_number in pages_of(config, "annexure_a"):
        page = doc[page_number - 1]
        dropped_here = 0
        position = 0

        for _, row in table_rows(page):
            labels = labels_left_to_right(page, row)
            if not labels:
                continue

            if looks_like_page_header(page, row):
                dropped_here += 1
                continue

            fields = build_fields(page, row, bounds, ANNEXURE_A_FIELDS)
            lead = labels[0]
            lead_squashed = squeeze(lead)
            sn_raw = fields["sn"].strip()

            if "grandtotal" in lead_squashed or "grandtotal" in squeeze(fields["location"]):
                controls.append({
                    "annexure": "annexure_a", "control_type": "grand_total",
                    "pdf_page": page_number, "row_index_on_page": position,
                    "text": lead, "count_raw": "",
                    "anpr": integer_or_na(fields["anpr"]),
                    "fixed": integer_or_na(fields["fixed"]),
                    "ptz": integer_or_na(fields["ptz"]),
                    "total_reported": integer_or_na(fields["total"]),
                    "go_live_raw": fields["go_live"] or pd.NA,
                    "zone": zone, "section_heading": section,
                    "extractor": "pymupdf",
                })
                position += 1
                continue

            if not sn_raw:
                if ZONE_LABEL.match(lead_squashed):
                    zone = lead
                    # Nearest zone OR area heading, so the Pune/PCMC split can
                    # be read straight off this column.
                    section = lead
                    station = None
                    control_type = "zone_heading"
                elif "area" in lead_squashed:
                    section = lead
                    station = None
                    control_type = "area_heading"
                elif lead_squashed == "total":
                    # Pune-area subtotal before the Pimpri Chinchwad block: a
                    # control row, and not a station for the rows that follow.
                    control_type = "section_total"
                elif any(integer_or_na(fields[key]) is not pd.NA
                         for key in ("anpr", "fixed", "ptz", "total")):
                    # A station sub-header must actually carry a subtotal; that
                    # number is what separates a station block header from a row
                    # of header debris, which can then never set the station for
                    # the rows below it.
                    station = one_line(lead)
                    control_type = "station_subtotal"
                else:
                    # Text-only row that is not a numbered heading: kept as a
                    # control, and it does not change the current station.
                    control_type = "unclassified"

                controls.append({
                    "annexure": "annexure_a", "control_type": control_type,
                    "pdf_page": page_number, "row_index_on_page": position,
                    "text": one_line(lead), "count_raw": "",
                    "anpr": integer_or_na(fields["anpr"]),
                    "fixed": integer_or_na(fields["fixed"]),
                    "ptz": integer_or_na(fields["ptz"]),
                    "total_reported": integer_or_na(fields["total"]),
                    "go_live_raw": fields["go_live"] or pd.NA,
                    "zone": zone, "section_heading": section,
                    "extractor": "pymupdf",
                })
                position += 1
                continue

            location = tight_space(fields["location"])
            location_original_raw = fields["location"] or pd.NA
            if not location and not fields["geo"].strip():
                controls.append({
                    "annexure": "annexure_a", "control_type": "unclassified",
                    "pdf_page": page_number, "row_index_on_page": position,
                    "text": one_line(" ".join(labels)), "count_raw": "",
                    "anpr": integer_or_na(fields["anpr"]),
                    "fixed": integer_or_na(fields["fixed"]),
                    "ptz": integer_or_na(fields["ptz"]),
                    "total_reported": integer_or_na(fields["total"]),
                    "go_live_raw": fields["go_live"] or pd.NA,
                    "zone": zone, "section_heading": section,
                    "extractor": "pymupdf",
                })
                position += 1
                continue

            lat_raw, lon_raw, geo_raw, geo_flag = split_coordinates(fields["geo"])
            station_raw = station if station else pd.NA
            # Heading fallback is consulted only if the lookup misses.
            scope_tag = tagger.tag_for(station_raw, section)
            tagger.remember(station_raw, "annexure_a")

            sites.append({
                "annexure": "annexure_a",
                "zone": zone,
                "station_raw": station_raw,
                "section_heading": section,
                "scope_tag": scope_tag,
                "sn_raw": sn_raw,
                "location_raw": location,
                "lat_raw": lat_raw,
                "lon_raw": lon_raw,
                "category_raw": pd.NA,
                "fixed": integer_or_na(fields["fixed"]),
                "ptz": integer_or_na(fields["ptz"]),
                "anpr": integer_or_na(fields["anpr"]),
                "poles": pd.NA,
                "total_reported": integer_or_na(fields["total"]),
                "go_live_raw": fields["go_live"] or pd.NA,
                "pdf_page": page_number,
                "row_index_on_page": position,
                "extractor": "pymupdf",
                "location_original": tight_space(fields["location"]) or pd.NA,
                "location_original_raw": location_original_raw,
                "geo_raw": geo_raw,
                "geo_flag": geo_flag,
                "station_source": "inherited_from_header" if station else pd.NA,
            })
            position += 1

        if dropped_here:
            header_drops.append({
                "pdf_page": page_number, "annexure": "annexure_a",
                "dropped_rows": dropped_here, "extractor": "pymupdf",
            })
    return sites, controls, header_drops


# --------------------------------------------------------------------------
# Annexure B, pages 100-166
# --------------------------------------------------------------------------

def read_annexure_b(doc, config: dict, tagger: Tagger):
    bounds = config["column_bounds"]["annexure_b"]
    stop_marker = squeeze(config["stop"]["annexure_b_stop_text"])
    sites = []
    controls = []
    header_drops = []

    zone = pd.NA
    station_seen = None
    stopped = False
    pages_read = 0

    for page_number in pages_of(config, "annexure_b"):
        if stopped:
            break
        pages_read += 1
        page = doc[page_number - 1]
        dropped_here = 0
        position = 0

        for _, row in table_rows(page):
            if stopped:
                break
            labels = labels_left_to_right(page, row)
            if not labels:
                continue

            if looks_like_page_header(page, row):
                dropped_here += 1
                continue

            fields = build_fields(page, row, bounds, ANNEXURE_B_FIELDS)
            lead = labels[0]
            lead_squashed = squeeze(lead)
            whole_row = squeeze(" ".join(labels))
            sn_raw = fields["sn"].strip()

            # Stop rule, checked before anything else so no row past it is used.
            if stop_marker in whole_row:
                controls.append({
                    "annexure": "annexure_b", "control_type": "grand_total",
                    "pdf_page": page_number, "row_index_on_page": position,
                    "text": one_line(" ".join(labels)), "count_raw": "",
                    "anpr": integer_or_na(fields["anpr"]),
                    "fixed": integer_or_na(fields["fixed"]),
                    "ptz": integer_or_na(fields["ptz"]),
                    "total_reported": pd.NA, "go_live_raw": pd.NA,
                    "zone": zone, "section_heading": zone,
                    "extractor": "pymupdf",
                })
                stopped = True
                break

            if ZONE_LABEL.match(lead_squashed):
                zone = lead
                station_seen = None
                controls.append({
                    "annexure": "annexure_b", "control_type": "zone_heading",
                    "pdf_page": page_number, "row_index_on_page": position,
                    "text": lead, "count_raw": "",
                    "anpr": pd.NA, "fixed": pd.NA, "ptz": pd.NA,
                    "total_reported": pd.NA, "go_live_raw": pd.NA,
                    "zone": zone, "section_heading": zone,
                    "extractor": "pymupdf",
                })
                position += 1
                continue

            if not sn_raw:
                controls.append({
                    "annexure": "annexure_b", "control_type": "unclassified",
                    "pdf_page": page_number, "row_index_on_page": position,
                    "text": one_line(" ".join(labels)), "count_raw": "",
                    "anpr": integer_or_na(fields["anpr"]),
                    "fixed": integer_or_na(fields["fixed"]),
                    "ptz": integer_or_na(fields["ptz"]),
                    "total_reported": pd.NA, "go_live_raw": pd.NA,
                    "zone": zone, "section_heading": zone,
                    "extractor": "pymupdf",
                })
                position += 1
                continue

            station_cell = one_line(fields["station"])
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

            # Annexure B's governing heading is the zone row above these sites.
            scope_tag = tagger.tag_for(station_raw, zone)
            tagger.remember(station_raw, "annexure_b")

            sites.append({
                "annexure": "annexure_b",
                "zone": zone,
                "station_raw": station_raw,
                "section_heading": zone,
                "scope_tag": scope_tag,
                "sn_raw": sn_raw,
                "location_raw": tight_space(fields["spot"]),
                "lat_raw": one_line(fields["lat"]) or pd.NA,
                "lon_raw": one_line(fields["long"]) or pd.NA,
                "category_raw": one_line(fields["category"]) or pd.NA,
                "fixed": integer_or_na(fields["fixed"]),
                "ptz": integer_or_na(fields["ptz"]),
                "anpr": integer_or_na(fields["anpr"]),
                "poles": integer_or_na(fields["poles"]),
                "total_reported": pd.NA,
                "go_live_raw": pd.NA,
                "pdf_page": page_number,
                "row_index_on_page": position,
                "extractor": "pymupdf",
                "location_original": tight_space(fields["spot"]) or pd.NA,
                "location_original_raw": fields["spot"] or pd.NA,
                "geo_raw": pd.NA,
                "geo_flag": pd.NA,
                "station_source": station_source,
            })
            position += 1

        if dropped_here:
            header_drops.append({
                "pdf_page": page_number, "annexure": "annexure_b",
                "dropped_rows": dropped_here, "extractor": "pymupdf",
            })

    assert stopped, "stop text not found; Annexure B reading did not terminate as expected"
    assert not any("annexurec" in squeeze(str(row["location_raw"] or "")) for row in sites), \
        "Annexure C content leaked into site rows"
    return sites, controls, header_drops, pages_read


# --------------------------------------------------------------------------
# Output
# --------------------------------------------------------------------------

def frame_of(rows, columns) -> pd.DataFrame:
    frame = pd.DataFrame(rows, columns=columns)
    for column in INT_COLUMNS:
        if column in frame.columns:
            frame[column] = pd.array(list(frame[column]), dtype="Int64")
    return frame


def save(frame: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    frame.to_csv(path, index=False, encoding="utf-8")


def save_misses(tagger: Tagger, path: Path) -> int:
    rows = []
    for key in sorted(tagger.misses):
        record = tagger.misses[key]
        rows.append({
            "station_raw": record["raw"],
            "station_normalised": key,
            "row_count": record["rows"],
            "annexures": ";".join(sorted(record["where"])),
            "extractor": "pymupdf",
        })
    save(pd.DataFrame(rows, columns=["station_raw", "station_normalised",
                                     "row_count", "annexures", "extractor"]), path)
    return len(rows)


def report(site_frame: pd.DataFrame, control_frame: pd.DataFrame,
           miss_count: int, drop_count: int) -> None:
    print("=" * 78)
    print("EXTRACTOR 2 (PyMuPDF find_tables)")
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
    print(f"unmatched station names: {miss_count}")
    print(f"flagged rows (geo_flag set): {int(site_frame['geo_flag'].notna().sum())}")
    print(f"rows dropped as repeated page headers: {drop_count}")
    print(f"count column dtypes: "
          f"{ {column: str(site_frame[column].dtype) for column in INT_COLUMNS} }")


def main() -> int:
    config = read_config()
    tagger = Tagger(read_scope_file(config))
    doc = pymupdf.open(config["pdf_path"])

    try:
        control_rows = read_control_table(doc, config, tagger)
        a_sites, a_controls, a_drops = read_annexure_a(doc, config, tagger)
        b_sites, b_controls, b_drops, pages_read = read_annexure_b(doc, config, tagger)
    finally:
        doc.close()

    print(f"Annexure B pages actually read: {pages_read} "
          f"(stopped at '{config['stop']['annexure_b_stop_text']}')\n")

    site_frame = frame_of(a_sites + b_sites, SITE_COLUMNS)
    control_frame = frame_of(control_rows + a_controls + b_controls, CONTROL_COLUMNS)
    drops = a_drops + b_drops

    save(site_frame, PROJECT_ROOT / config["outputs"]["sites_pymupdf"])
    save(control_frame, PROJECT_ROOT / config["outputs"]["controls_pymupdf"])
    save(pd.DataFrame(drops, columns=["pdf_page", "annexure", "dropped_rows", "extractor"]),
         PROJECT_ROOT / config["outputs"]["dropped_headers_pymupdf"])
    miss_count = save_misses(tagger, PROJECT_ROOT / config["outputs"]["unmatched_pymupdf"])

    report(site_frame, control_frame, miss_count, sum(item["dropped_rows"] for item in drops))
    return 0


if __name__ == "__main__":
    sys.exit(main())

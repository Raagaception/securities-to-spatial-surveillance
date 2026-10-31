# Output schema

Extraction files are written to `outputs/extraction/`; the derived Table 3 is
written to `outputs/tables/`; the joined ward layer is
`outputs/figures/2011census_wards-with-cameras-all.gpkg`. All columns are stored
as text in the CSV. During extraction the count columns are pandas nullable
integers (`Int64`), so a blank cell is missing rather than zero.

## sites_pdfplumber.csv, sites_pymupdf.csv

One row per site. 1444 rows in each file: 437 from Annexure A and 1007 from
Annexure B. The two files have identical columns and differ in two cells only,
both on SN 215.

| column | type | meaning |
| --- | --- | --- |
| `annexure` | text | `annexure_a` for existing cameras, `annexure_b` for proposed ones |
| `zone` | text | police zone, `Zone 1` to `Zone 5` |
| `station_raw` | text | police station exactly as printed, so spellings vary between annexures |
| `section_heading` | text | nearest zone or area heading above the row |
| `scope_tag` | text | `PUNE`, `PCMC` or `UNKNOWN`, from the lookup plus the heading fallback |
| `sn_raw` | text | serial number as printed; 1 to 437 in A, 1 to 1007 in B |
| `location_raw` | text | site description on one line, whitespace collapsed |
| `lat_raw` | text | latitude, not converted to a number |
| `lon_raw` | text | longitude, not converted to a number |
| `category_raw` | text | Annexure B only: `New Location`, `Addl Poles and Cameras`, `Addl Cameras only`, `Clubbed Location` |
| `fixed` | integer | fixed cameras |
| `ptz` | integer | pan-tilt-zoom cameras |
| `anpr` | integer | ANPR cameras |
| `poles` | integer | Annexure B only; poles are not cameras |
| `total_reported` | integer | Annexure A only; the total the document prints for the row |
| `go_live_raw` | text | Annexure A only; date as printed, dd/mm/yyyy |
| `pdf_page` | integer | printed page number, which equals the PDF page index |
| `row_index_on_page` | integer | position of the row on its page, counted from zero |
| `extractor` | text | `pdfplumber` or `pymupdf` |
| `location_original` | text | location text after whitespace normalisation; same as `location_raw` |
| `location_original_raw` | text | location text exactly as extracted, line breaks intact |
| `geo_raw` | text | the raw coordinate cell when it could not be split into two numbers |
| `geo_flag` | text | `missing_geo` or `not_single_pair` when the cell was unusable |
| `station_source` | text | `cell` when the station was printed on the row, `inherited_from_header` when it came from the block heading |

## controls.csv, controls_pymupdf.csv

Rows that are not sites: zone headings, area headings, station subtotals, the
section total and the grand total, plus the whole of the pages 81 and 82
control table. 101 rows each.

Columns: `annexure`, `control_type`, `pdf_page`, `row_index_on_page`, `text`,
`count_raw`, `anpr`, `fixed`, `ptz`, `total_reported`, `go_live_raw`, `zone`,
`section_heading`, `extractor`.

`control_type` takes the values `zone_heading`, `area_heading`,
`station_subtotal`, `station_count`, `section_total`, `grand_total`,
`table_title` and `unclassified`. Rows typed `unclassified` are header debris
that could not be attributed; there are four, all in Annexure A.

Use this file to check the extracted sites against the totals the document
prints. The station subtotals sum to the grand total, and the control table on
pages 81 and 82 agrees with them.

## diff.csv

One line per disagreement between the two extractors.

| column | meaning |
| --- | --- |
| `record_key` | `annexure|sn_raw|zone` |
| `field` | column that disagrees |
| `extractor1_value` | value from pdfplumber |
| `extractor2_value` | value from PyMuPDF |
| `pdf_page` | page the row came from |
| `diff_type` | `value_differs`, `missing_in_1`, `missing_in_2` or `duplicate_key` |

The file never says which extractor is right. At present it holds two lines,
both for SN 215, where pdfplumber read the coordinate cell as spaced characters
(`1 8 . 5 0 8 5 0 0`) and PyMuPDF read it as `18.508500`. Prefer the PyMuPDF
table for coordinates.

## unmatched_stations.csv

Station names in the sites table that have no row in `config/station_scope.csv`,
with a row count and the annexures they appear in. The file is empty at present,
which means every station resolves through the lookup.

## dropped_headers.csv

Repeated page headers removed during extraction, counted per page and annexure.
The counts differ between extractors because pdfplumber detects more of the
header as separate small tables; this is expected and does not affect the site
rows.

## joined_layer (GeoPackage)

`outputs/figures/2011census_wards-with-cameras-all.gpkg`, layer `joined_layer`.
144 rows, one per pre-2012 PMC ward. It is the durable output of the QGIS
spatial join and the input to Table 3 and to the population-share map.

Provenance:

- ward geometry from `data/raw/pune-pre-2012-144-ward-boundaries_nikhilvj.geojson`
  (`wardnum` 1-144);
- census columns from `data/raw/pune-pmc-census2011-ward-demographics.csv`,
  after keeping integer ward numbers and dropping `Total` rows and
  `Yewalewadi`; joined on `wardnum` = `Census Ward Number`, 144 of 144 matched;
- camera sums from the Pune-scope rows of
  `outputs/extraction/sites_pymupdf.csv`: `camera_count = fixed + ptz + anpr`,
  joined to the wards by location and summed per ward. `camera_count_sum` is
  Annexure A (existing), `camera_count_sum_2` is Annexure B (proposed).

| column | type | meaning |
| --- | --- | --- |
| `fid`, `geom` | integer, polygon | GeoPackage feature id and ward polygon |
| `wardnum` | integer | ward number 1-144, the census join key |
| `scst_share` | real | `(P_SC + P_ST) / TOT_P`, stored rounded to four decimals as a convenience; Table 3 recomputes it from the counts |
| `census2011_Ward Name` | text | ward-office name from the census CSV; several wards share a name |
| `census2011_TOT_P` | integer | 2011 total population |
| `census2011_P_SC`, `census2011_P_ST` | integer | 2011 Scheduled Caste and Scheduled Tribe population |
| `camera_count_sum` | real | existing cameras summed from Annexure A sites inside the ward |
| `camera_count_sum_2` | real | proposed cameras summed from Annexure B sites inside the ward |

The remaining `census2011_*` columns are carried through from the census CSV
for completeness and are not used by Table 3. `cam_all` is **not** stored in
the GeoPackage; it is a QGIS virtual field in the `.qgz` with the expression
`coalesce("camera_count_sum",0) + coalesce("camera_count_sum_2",0)`.

Control totals: 144 rows, population 3,124,458, SC 419,396, ST 34,025,
963 existing and 2,146 proposed cameras inside the wards. The QGIS join is the
one manual step in the chain; `outputs/figures/README.md` records its inputs and
the independent points-in-polygons check that reproduced the 963/2,146 sums.

## table3_scst_allocation.csv

The derived table in `outputs/tables/`. Six rows: five SC+ST quintiles and one
row for cameras outside the 144 wards. Nine columns. Percentages are stored to
two decimals; the companion `table3_summary.json` keeps full precision, the
exact class breaks and the run's checks.

| column | type | meaning |
| --- | --- | --- |
| `scst_class` | text | quintile label with bounds rounded for display (`Q1 (0.01-0.07)` to `Q5 (0.23-0.55)`), or `Outside the 144 wards` |
| `wards` | integer | wards in the class; blank for the outside row |
| `residents` | integer | 2011 population in the class; blank for the outside row |
| `residents_pct` | decimal | residents as a percentage of 3 124 458; blank for the outside row |
| `existing_cameras` | integer | Annexure A cameras recorded at sites in the class, or outside the wards |
| `existing_pct` | decimal | existing cameras as a percentage of the Pune total, 1 077 |
| `proposed_cameras` | integer | Annexure B cameras recorded at sites in the class, or outside the wards |
| `proposed_pct` | decimal | proposed cameras as a percentage of the Pune total, 2 886 |
| `cameras_per_1000_residents` | decimal | (existing + proposed) / residents x 1 000, inside-ward cameras only; blank for the outside row |

A blank cell is not zero. In the outside row, `wards`, `residents`,
`residents_pct` and `cameras_per_1000_residents` are undefined because the row
has no resident denominator; the camera counts and percentages are complete.
In the ward readers, a blank camera cell in the QGIS export is read as zero,
because QGIS writes NULL for a ward with no cameras.

The class labels round the exact type-7 breaks (0.008683, 0.066268, 0.100785,
0.146207, 0.225284, 0.531341) to two decimals. Classify from the exact breaks,
not from the labels: the rounded bounds would move wards that sit close to a
boundary.

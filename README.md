# securities-to-spatial-surveillance

Code, data and protocol for a spatial audit of planned AI-CCTV deployment in
Pune, carried out against the Allied Digital Safe City contract.

**Credit:** Raagaception.

**Status:** preliminary. The analysis is unfinished and this repository should
not be cited until the accompanying paper has a DOI.

## What is here

| path | contents |
| --- | --- |
| `data/raw/` | source files, exactly as downloaded |
| `config/` | extraction settings and the station-to-scope lookup |
| `scripts/` | download verifier, extraction pipeline and Table 3 builder |
| `outputs/extraction/` | extracted site tables, control rows and extractor diff |
| `outputs/figures/` | final maps for section 4.2, with the QGIS project, documentation and checksums |
| `outputs/tables/` | Table 3 for section 5.2, with machine-readable companions, documentation and checksums |
| `metadata/` | provenance, checksums and output schema |
| `protocol/` | analysis plan |
| `manuscript/` | paper drafts |

## Provenance and workflow

The repository keeps four stages separate so that every artefact can be checked
against the stage before it.

```
data/raw/  (tender PDF, census CSV, ward GeoJSON)
  |  scripts/extract_pdfplumber.py, scripts/extract_pymupdf.py, scripts/diff_extractors.py
  v
outputs/extraction/  (1,444 site rows, control rows, extractor diff)
  |  QGIS: filter scope_tag = PUNE; camera_count = fixed + ptz + anpr;
  |        join by location to the 144 wards and sum; join census by ward number
  v
outputs/figures/2011census_wards-with-cameras-all.gpkg  (joined_layer, 144 rows)
  |-- scripts/build_table3.py --> outputs/tables/  (Table 3, checks, manifest)
  `-- QGIS layouts -----------> outputs/figures/*.png
```

| stage | artefact | where it is documented |
| --- | --- | --- |
| raw sources | `data/raw/` | `metadata/sources.csv`, `DATA-LICENCES.md` |
| extraction | `outputs/extraction/` | `metadata/output-schema.md`, `config/extraction.yml`, "Extracting the tender tables" below |
| ward join | `2011census_wards-with-cameras-all.gpkg` | `outputs/figures/README.md` ("Ward layer used by the maps and Table 3"), `metadata/output-schema.md` |
| table | `outputs/tables/` | `outputs/tables/README.md`, `metadata/tables.csv` |
| maps | `outputs/figures/*.png` | `outputs/figures/README.md`, `metadata/figures.csv` |

The only stage not performed by a Python script in this repository is the QGIS
spatial join that writes the ward layer. Its inputs, join fields and control
totals are documented in the two files above, and the committed GeoPackage is
the result. If that layer is regenerated, rebuild Table 3 and the figure
manifest in the same change.

## Data

Nine source files sit in `data/raw/`. For each one, `metadata/sources.csv`
records the download URL, the access date, the SHA-256, the licence and a note
on what the file is used for. Read that file before using anything here.

Most of the data is committed. The exception is
`western-zone-261024.osm.pbf`, a 212 MB OpenStreetMap extract that exceeds
GitHub's 100 MiB per-file limit and is therefore ignored by Git. A clone
therefore arrives without it. To fetch it, run:

```
python scripts/fetch_data.py
```

That command reads `metadata/sources.csv`, downloads anything missing, and
refuses to write a file whose SHA-256 does not match the recorded value. Pass
`--all` to re-verify the committed files as well, `--check` to verify without
network access, or `--force` to replace a file that has drifted.

## Integrity

`metadata/SHA256SUMS` covers every file in `data/raw/`. Verify it with:

```
sha256sum -c metadata/SHA256SUMS
```

Files under `data/` are stored byte for byte. `.gitattributes` disables text
conversion and diffing for that tree, so a checkout cannot alter line endings
and invalidate a recorded hash. The CSVs in `outputs/extraction/` are kept the
same way, as binary blobs, so that a regenerated table either matches the
committed one exactly or shows up as a changed object.

The maps in `outputs/figures/` are covered by their own manifest,
`outputs/figures/SHA256SUMS`, because they are deliverables rather than derived
tables. Verify them from the repository root with:

```
sha256sum -c outputs/figures/SHA256SUMS
```

Each PNG is a lossless export stored exactly as delivered; do not re-encode,
optimise or resave one, because that changes the hash and breaks the comparison
with the published figure.

## Extracting the tender tables

The tender document, `data/raw/Tendernotice_2-PuneCCTVVOLII.pdf`, contains two
tabulated annexures. The pipeline reads the control table on pages 81 and 82,
Annexure A on pages 83 to 99, and Annexure B on pages 100 to 166, stopping at
the first row that contains "Grand Total" so that Annexure C is never read.

Two extractors run over the same pages with independent code: one drives
pdfplumber with the ruled-line strategy, the other drives PyMuPDF's
`find_tables`. They share no row-building logic. A third script compares the
two outputs cell by cell and reports every disagreement without deciding which
side is correct.

```
python scripts/extract_pdfplumber.py
python scripts/extract_pymupdf.py
python scripts/diff_extractors.py
```

`scripts/run_pipeline.sh` runs all three in order. Page ranges, file paths and
column coordinates live in `config/extraction.yml`, not in the code, and every
path in that file is relative to the repository root. The scripts resolve their
own location, so they work from any working directory.

## Output files

All extraction output goes to `outputs/extraction/`:

| file | contents |
| --- | --- |
| `sites_pdfplumber.csv` | one row per site, 1444 rows |
| `sites_pymupdf.csv` | the same schema from the second extractor |
| `controls.csv`, `controls_pymupdf.csv` | zone headings, station subtotals, totals |
| `diff.csv` | cells where the two extractors disagree |
| `unmatched_stations.csv` | station names absent from the scope lookup |
| `dropped_headers.csv` | repeated page headers removed, counted per page |

Column definitions for the site tables are in `metadata/output-schema.md`.
Counts are pandas nullable integers, so a blank cell stays missing and is never
read as zero. Coordinates stay as text.

## Figures

Section 4.2 maps live in `outputs/figures/`, together with the QGIS project that
produced them:

| file | contents |
| --- | --- |
| `Map1_SCST-share.png` | quintiles of the SC+ST share of 2011 ward population, with tender camera sites overlaid |
| `Map2_population.png` | quintiles of absolute 2011 ward population, with the same camera sites |
| `Map3_camera-relative-pop-density.png` | ward share of tender-recorded cameras divided by ward share of 2011 population; a population-share ratio, not a density measure |
| `pune_cctv_2011census_maps.qgz` | QGIS project with the three delivery layouts and the layer styles |
| `2011census_wards-with-cameras-all.gpkg` | joined ward layer (`joined_layer`, 144 rows) used by the maps and Table 3 |

`outputs/figures/README.md` documents each map's expression, class breaks,
symbology, export settings and the checks run against it. The three maps read
the joined ward layer from the GeoPackage. Map 3's filename is historical and
says `pop-density`, but the map is the population-share ratio used in section
5.2. The same information is machine-readable in `metadata/figures.csv`.

## Tables

Table 3 for section 5.2 lives in `outputs/tables/`:

| file | contents |
| --- | --- |
| `table3_scst_allocation.csv` | one row per SC+ST quintile and one outside row, with counts and percentages |
| `table3_scst_allocation.md` | manuscript-ready table, caption, source note and ratio verdict |
| `table3_summary.json` | full-precision values, exact class breaks, totals, 18 checks and input hashes |
| `SHA256SUMS` | manifest for the three files above |

The table groups the 144 wards by the 2011 SC+ST share of their population and
sums the tender-recorded cameras in each group. It is built from the tracked
ward GeoPackage and the site extractor:

```
python scripts/build_table3.py
```

The script also accepts the QGIS attribute export
(`--wards data/processed/QGIS_2011wards-cameras-final.csv`), cross-checks it
against the GeoPackage, and refuses to write a table if the two disagree.
Percentages use the Pune-scope totals (1,077 existing, 2,886 proposed cameras),
so the outside row completes the city total; the ward layer holds 963 existing
and 2,146 proposed cameras inside the 144 wards. `outputs/tables/README.md`
records the method, the checks and the limitations, and the same information is
machine-readable in `metadata/tables.csv`.

## Environment

`environment.yml` defines the analysis environment (Python 3.11, geopandas,
libpysal, esda and related packages). The extraction pipeline needs much less.
Its exact versions are pinned in `requirements-extraction.txt`, and they are the
versions that produced the committed outputs.

## Known limitations

These affect how the extracted tables can be used, not whether they are correct.

The proposed-location table is a tender schedule, so it records what was
planned in 2024, not what was installed. Annexure A records cameras already in
service under the earlier project.

Roughly a quarter of the geocoded sites fall outside Pune Municipal Corporation
limits: the Pimpri-Chinchwad sites, sites in the Pune and Khadki cantonment
areas, and peripheral villages. Any ward-level analysis has to decide what to do
with them rather than letting a spatial join drop them silently. The ward
boundaries in `data/raw/` cover PMC only.

The 144-ward boundary file is a community publication, not an official survey
product. Its author states that the 2011 Census geography corresponds to the
pre-2012 144 prabhags, and that statement has not been independently validated.
See `DATA-LICENCES.md` for the licensing consequence.

Annexure B's pole counts sum to 1239 while its own Grand Total prints 1238. The
difference is in the source document and is left uncorrected.

Four Annexure A rows have no usable coordinate. Three are flagged in the
`geo_flag` column; the fourth, SN 215, is the single cell where the two
extractors disagree, because pdfplumber read the cell as spaced characters.
Use the PyMuPDF table for coordinates, or patch that one row by hand.

## Licence

Code and scripts are MIT. The data files carry their own licences, which differ
from each other and from MIT. `DATA-LICENCES.md` lists them file by file.

## Citation

`CITATION.cff` holds the machine-readable citation. Please cite the paper once
it is published, and this repository alongside it.

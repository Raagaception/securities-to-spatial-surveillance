# metadata/

Four files record where the data, figures and derived tables came from and what
state they are in.

## sources.csv

One row per file in `data/raw/`, in the order the files were added.

| column | meaning |
| --- | --- |
| `filename` | name of the file inside `data/raw/` |
| `url` | where it was downloaded from, or `local-user-supplied` when there is no public URL |
| `download_date` | date the copy in this repository was obtained (ISO 8601) |
| `sha256` | SHA-256 of the file as stored here |
| `licence` | licence as stated by the publisher, with a note where the terms are unclear |
| `use` | what the file is for, what it must not be mistaken for, and any processing it needs first |

The `use` column is the place to look before using a dataset. Several entries
record a required filter or a provenance caveat, and one records a licence that
is not settled. Those notes are not optional reading.

## SHA256SUMS

A standard `sha256sum` manifest covering every file in `data/raw/`. Verify it
from the repository root:

```
sha256sum -c metadata/SHA256SUMS
```

Each line reports `OK`, or a mismatch, or a missing file. A missing file is
expected for `western-zone-261024.osm.pbf` on a fresh clone, because that file
is too large for Git. Run `python scripts/fetch_data.py` to obtain it.

Figures, the QGIS project and the joined ward layer are covered by a separate
manifest, `outputs/figures/SHA256SUMS`, because they are deliverables rather
than source data:

```
sha256sum -c outputs/figures/SHA256SUMS
```

Derived tables are covered by their own manifest for the same reason:

```
sha256sum -c outputs/tables/SHA256SUMS
```

## figures.csv

One row per delivered map figure in `outputs/figures/`.

| column | meaning |
| --- | --- |
| `path` | path to the file, relative to the repository root |
| `title` | title as it appears on the figure, or `None` if the layout has no title |
| `layout` | layout name inside `pune_cctv_2011census_maps.qgz` |
| `figure_type` | choropleth or point overlay |
| `shows` | what is mapped and at what unit |
| `method` | the expression or variable that is classified |
| `class_breaks` | class limits, lowest first (`;` separated) |
| `width_px`, `height_px`, `dpi` | export geometry |
| `bytes`, `sha256` | size and hash of the stored file |
| `notes` | symbology caveats, known drift or provenance gaps |

Read the `notes` column before reusing a figure: it records symbology caveats,
naming quirks and provenance gaps.

## tables.csv

One row per delivered table in `outputs/tables/`.

| column | meaning |
| --- | --- |
| `path` | path to the table file, relative to the repository root |
| `title` | table caption as it appears in the manuscript |
| `table_type` | cross-tabulation, summary or register |
| `rows`, `columns` | data rows (the header is not counted) and columns |
| `inputs` | files the table was built from |
| `method` | the classification and aggregation applied |
| `denominators` | the city totals used for the percentage columns |
| `class_breaks` | class limits, lowest first (`;` separated) |
| `bytes`, `sha256` | size and hash of the stored CSV |
| `notes` | companion files, caveats and provenance gaps |

Read the `notes` column before reusing a table: it records which companion
files carry the full-precision values and the checks, and whether the counts
describe planned or installed infrastructure.

## Do not edit these files by hand

`sources.csv` and `SHA256SUMS` describe bytes that are already on disk. If you
replace a source file, record the new hash in both places in the same change,
otherwise `sha256sum -c` will fail and the provenance chain is broken.

`figures.csv` and `outputs/figures/SHA256SUMS` work the same way: if a figure is
re-exported, update its hash in both the CSV and the manifest, and record why in
`outputs/figures/README.md`.

`tables.csv` and `outputs/tables/SHA256SUMS` follow the same rule: if
`scripts/build_table3.py` changes and the table is regenerated, update the byte
count and hash in both places, and record the reason in
`outputs/tables/README.md`.

## Related

`metadata/output-schema.md` documents the columns of the extracted tables, the
joined ward layer and the derived table in `outputs/tables/`.
`outputs/figures/README.md` documents the maps, the ward layer, export settings
and the checks run against them.
`outputs/tables/README.md` documents Table 3, its inputs, method and checks.
`DATA-LICENCES.md` at the repository root spells out the licensing of each
source file.

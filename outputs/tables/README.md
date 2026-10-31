# outputs/tables/

Table 3 for section 5.2, with its machine-readable companions and checksums.
The CSV and Markdown files are the delivered artefacts: they are stored byte
for byte and must not be edited by hand. Regenerate them with
`scripts/build_table3.py`, then update the hash in `SHA256SUMS` and in
`metadata/tables.csv` in the same change.

Verify the stored bytes from the repository root:

```
sha256sum -c outputs/tables/SHA256SUMS
```

## Files

| file | contents | bytes |
| --- | --- | ---: |
| `table3_scst_allocation.csv` | the table, one row per SC+ST quintile plus the outside row | 463 |
| `table3_scst_allocation.md` | manuscript-ready table with caption, source note and the ratio verdict | 1 935 |
| `table3_summary.json` | full-precision values, exact class breaks, totals, 18 checks and input hashes | 6 860 |
| `SHA256SUMS` | standard manifest for the three files above | - |

The CSV rounds percentages to two decimals and cameras per 1,000 residents to
two decimals. The Markdown rounds percentages to one decimal, the form used in
the manuscript. The JSON keeps full precision.

## Provenance chain

```
data/raw/Tendernotice_2-PuneCCTVVOLII.pdf  (Annexure III, pp. 83-166)
  -> scripts/extract_pymupdf.py -> outputs/extraction/sites_pymupdf.csv
data/raw/pune-pmc-census2011-ward-demographics.csv
data/raw/pune-pre-2012-144-ward-boundaries_nikhilvj.geojson
  -> QGIS spatial join -> outputs/figures/2011census_wards-with-cameras-all.gpkg
                          (layer joined_layer, 144 rows)
sites_pymupdf.csv + joined_layer -> scripts/build_table3.py -> this directory
```

The join step, as performed in QGIS:

1. Load the 144 ward polygons and the cleaned census CSV; join on
   `wardnum` = `Census Ward Number` (144 of 144 matched).
2. Load `sites_pymupdf.csv` twice, filtered to `scope_tag = 'PUNE'` and to
   Annexure A or B; add `camera_count = fixed + ptz + anpr`.
3. Join attributes by location (summary), summing `camera_count` onto the
   wards: `camera_count_sum` for Annexure A, `camera_count_sum_2` for B.
4. Save as `joined_layer` in
   `outputs/figures/2011census_wards-with-cameras-all.gpkg`.

The GeoPackage is committed; the join is not a script. `scripts/build_table3.py`
therefore reproduces the table from the committed join, but it does not re-run
the point-in-polygon step. That step is documented in
`outputs/figures/README.md` ("Ward layer used by the maps and Table 3") and
`metadata/output-schema.md` ("joined_layer"). The independent ray-casting check
reported there reproduces the 963 existing and 2,146 proposed in-ward sums.

## What the table shows

The unit is the ward. The 144 wards of the pre-2012 Pune Municipal Corporation
frame are grouped into quintiles of the 2011 Scheduled Caste and Scheduled
Tribe share of their population. For each quintile the table reports the number
of wards, residents, existing cameras and proposed cameras, each as a count and
as a percentage of the city total, plus cameras per 1,000 residents.

The camera counts are cameras recorded at tender sites, not verified
installations. Existing cameras come from Annexure A of the tender; proposed
cameras from Annexure B. Fixed, PTZ and ANPR units are counted equally. Poles
are not cameras and are not counted.

## Inputs

| input | role | SHA-256 |
| --- | --- | --- |
| `outputs/figures/2011census_wards-with-cameras-all.gpkg`, layer `joined_layer` | 144 wards, Census 2011 columns and the two inside-ward camera sums; the durable, committed input | `9d21d7a406deee8173cb5d940a02045350bc0135397e21243b205d6539967126` |
| `outputs/extraction/sites_pymupdf.csv` | Pune-scope control totals (1 077 existing, 2 886 proposed cameras; 358 and 1 007 sites) and the ungeocoded-site count | `90b40a5dff24a9a7a1ba0e92592246bd5b460bac298307f3d49942fa4f7999ff` |
| `data/processed/QGIS_2011wards-cameras-final.csv` | QGIS attribute export of the ward layer, used only for the cross-check; not committed because `data/processed/` is ignored | `b76e49808a83074e2c919b7198b6e0502fad6cac6aaa10fe9db1ef5a7d05967e` |

The default run reads the GeoPackage, so a fresh clone can rebuild the table
without the untracked QGIS export. When the export is present, the script
cross-checks it against the GeoPackage cell by cell and fails the build on any
difference.

## Method

Ward share:

```
scst_share = (P_SC + P_ST) / TOT_P
```

Classes are quintiles of that share over the 144 wards, using the type-7
(linear interpolation) definition that QGIS uses for quantile classification.
Exact breaks:

```
0.008683  0.066268  0.100785  0.146207  0.225284  0.531341
```

Classes are left-closed and right-open, so a ward exactly on a break falls in
the upper class. The manuscript labels round the bounds to two decimals:
Q1 0.01-0.07, Q2 0.07-0.10, Q3 0.10-0.15, Q4 0.15-0.23, Q5 0.23-0.55.

Percentages use the Pune-scope totals, not the ward-layer totals:

```
residents %  = residents in class / 3 124 458 x 100
existing %   = existing cameras in class / 1 077 x 100
proposed %   = proposed cameras in class / 2 886 x 100
```

Those denominators are why the outside row is needed. The ward layer holds 963
existing and 2 146 proposed cameras inside the 144 wards. The remainder,
114 existing and 740 proposed, falls outside the ward polygons or has no
usable coordinate (three Annexure A sites, 14 existing cameras). The outside
row completes the city total.

Cameras per 1,000 residents is computed on inside-ward cameras only:

```
(existing + proposed in class) / residents in class x 1000
```

The outside row has no resident denominator and is left blank.

The camera-weighted SC+ST share is:

```
sum(cameras in ward x ward scst_share) / sum(cameras in ward)
```

over the 144 wards, separately for existing cameras, proposed cameras and both.
The outside cameras carry no ward share and are excluded from numerator and
denominator, so the figure describes the in-ward network only. The
resident-weighted city share is `(P_SC + P_ST) / TOT_P` over all 144 wards.

The ratio rule was fixed before the table was read. For each class, divide its
share of cameras by its share of residents. Call the result a gradient only if
the ratio rises at every step Q1 to Q5 or falls at every step; otherwise call
it mixed. The script computes the ratio for existing, proposed and combined
cameras and writes the verdict into the Markdown note. All three are mixed on
the current data.

## Checks performed

The script fails rather than writing a table if any check does not hold. The
18 checks in `table3_summary.json` cover:

- 144 wards, ward numbers 1-144 with no gaps or duplicates;
- population 3 124 458, SC 419 396, ST 34 025;
- 963 existing and 2 146 proposed cameras inside the wards;
- 358 and 1 007 Pune sites, with 1 077 and 2 886 Pune cameras;
- outside row of 114 existing and 740 proposed cameras;
- class counts 29 / 29 / 28 / 29 / 29;
- class breaks within 3.4e-16 of the documented values;
- residents, existing and proposed percentages each closing at 100.

Additional checks, recorded here rather than in the JSON:

- **Cross-check against the QGIS export.** 144 wards, 0 mismatched cells,
  0.0 share drift. The export stores `scst_share` rounded to four decimals, so
  a small drift is tolerated; anything above 1e-4 fails.
- **Determinism.** Two consecutive runs produced byte-identical CSV, Markdown
  and JSON.
- **Input equivalence.** Building from the GeoPackage and building from the
  QGIS CSV produced byte-identical CSV and Markdown. The JSON differs between
  the two runs only in the recorded input path and hash.

## Reproduction

```
python scripts/build_table3.py
python scripts/build_table3.py --wards data/processed/QGIS_2011wards-cameras-final.csv
python scripts/build_table3.py --no-crosscheck
sha256sum -c outputs/tables/SHA256SUMS
```

The script resolves paths against the repository root and works from any
working directory. It reads the GeoPackage in SQLite read-only mode and writes
only under `outputs/tables/`.

## Limitations

- The table describes planned tender positions, not installed or operating
  cameras. It records co-location, not causation, purpose or effect.
- Denominators are 2011 Census counts. Ward populations at the urban edge have
  changed since; the table cannot say in which direction.
- The frame is PMC only. Sites in Pimpri-Chinchwad, the cantonment areas and
  peripheral villages are outside the 144 wards and appear only in the outside
  row.
- The outside row has no resident denominator, so its cameras per 1,000
  residents is undefined, not zero.
- Ward averages conceal clustering below ward scale. A mixed ward-scale result
  does not rule out a pattern within wards.
- Quintiles give each class the same number of wards, so class numbers are not
  equal intervals and cannot be read as a continuous scale.
- The camera count weights fixed, PTZ and ANPR units equally and ignores
  capability differences.

## Provenance

The GeoPackage is the durable input because it is committed under
`outputs/figures/`. The QGIS export in `data/processed/` is ignored by Git and
exists only on the machine that produced it; the cross-check therefore runs
when that file is present and is skipped, with a message, when it is not. The
committed JSON was produced from the tracked GeoPackage and the tracked site
table, so it is reproducible from a fresh clone.

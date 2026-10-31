# outputs/figures/

Three final map figures for section 4.2 (GIS spatial overlay), plus the QGIS
project that produced them and the joined ward layer they read. The PNGs are the
delivered artefacts: they are stored byte for byte and must not be re-encoded
(no `optipng`, `pngquant`, `magick -strip` or resaving from an image editor).
Any re-export changes the SHA-256 and should be treated as a new version,
recorded in the manifest and in `metadata/figures.csv`.

Verify the stored bytes from the repository root:

```
sha256sum -c outputs/figures/SHA256SUMS
```

## Files

| file | layout in `pune_cctv_2011census_maps.qgz` | pixels | export | bytes |
| --- | --- | --- | --- | --- |
| `Map1_SCST-share.png` | `Map1_SCST` | 7015 x 4960 | A4 landscape, 600 dpi | 15 467 914 |
| `Map2_population.png` | `Map2_Pop` | 7015 x 4960 | A4 landscape, 600 dpi | 14 313 865 |
| `Map3_camera-relative-pop-density.png` | `Map3_CamDensityShare` | 7015 x 4960 | A4 landscape, 600 dpi | 15 666 324 |
| `pune_cctv_2011census_maps.qgz` | three delivery layouts | - | QGIS project, zipped | 160 699 |
| `2011census_wards-with-cameras-all.gpkg` | - | - | GeoPackage, layer `joined_layer` | 823 296 |

The three PNGs are the delivered map set, and the `.qgz` contains exactly the
three layouts that produced them.

Map 3's filename is historical: it carries the old `pop-density` name, but the
map is the population-share ratio, not a density measure. The caption and the
QGIS expression both use population share. See "Map 3" below.

## Common inputs

All three maps use the same study frame and the same camera point layers:

| input | use |
| --- | --- |
| `data/raw/pune-pre-2012-144-ward-boundaries_nikhilvj.geojson` | 144 ward polygons, attribute `wardnum` 1-144, EPSG:4326 (community file; see `metadata/sources.csv`) |
| `data/raw/pune-pmc-census2011-ward-demographics.csv` | ward demographics, read as UTF-8 with BOM (`utf-8-sig`) |
| `outputs/extraction/sites_pymupdf.csv` | geocoded tender sites; `xField=lon_raw`, `yField=lat_raw`, EPSG:4326 |

The census layer carries a subset filter that reproduces the documented
cleaning rule:

```
"Census Ward Number" NOT ILIKE '%Total%' AND "Ward Name" NOT ILIKE '%Yewalewadi%'
```

The two point layers are subsets of the same CSV:

```
"scope_tag" = 'PUNE' AND "annexure" = 'annexure_a'   -- existing, red
"scope_tag" = 'PUNE' AND "annexure" = 'annexure_b'   -- proposed, amber
```

`scope_tag = 'PUNE'` excludes the 79 PCMC Annexure A rows. Sites outside the
144 wards are still drawn; they are not clipped to the PMC frame.

Each site row carries `camera_count = "fixed" + "ptz" + "anpr"`, computed per
row. The point symbol size is data-defined:

```
0.1 + "camera_count" * 0.40     (millimetres)
```

so circle area grows with the number of cameras recorded at that location, not
with the number of sites.

## Ward layer used by the maps and Table 3

`2011census_wards-with-cameras-all.gpkg`, layer `joined_layer`, is the durable
output of the spatial join and the input to Table 3. It has 144 rows and the
following fields: `wardnum`, the census columns, `scst_share` (stored rounded
to four decimals), and two camera sums.

Build steps, as performed in QGIS:

1. Load the 144 ward polygons; load the census CSV with the filter above; join
   `wardnum` to `Census Ward Number` (144 of 144 matched).
2. Load `sites_pymupdf.csv` twice with the two scope filters; add
   `camera_count = "fixed" + "ptz" + "anpr"`.
3. Join attributes by location (summary) each point layer to the wards, summing
   `camera_count`; name the Annexure A sum `camera_count_sum` and the Annexure B
   sum `camera_count_sum_2`.
4. Save the joined layer as `joined_layer` in the GeoPackage.

`cam_all` is not a stored column. It is a virtual field in the `.qgz`:

```
coalesce("camera_count_sum",0) + coalesce("camera_count_sum_2",0)
```

Control totals: 963 existing and 2,146 proposed cameras inside the 144 wards,
against Pune-scope totals of 1,077 and 2,886. The join is the one manual step in
the chain; `scripts/build_table3.py` reads the committed result and does not
re-run the point-in-polygon assignment. The independent ray-casting check under
"Checks performed" reproduces the in-ward sums.

## Map 1 - SC+ST population share

`Map1_SCST-share.png`, layout `Map1_SCST`.

Ward shading is the combined Scheduled Caste and Scheduled Tribe share of the
2011 ward population:

```
scst_share = ("census2011_P_SC" + "census2011_P_ST") / "census2011_TOT_P"
```

Five quantile classes over the 144 wards (QGIS quantile, linear interpolation,
i.e. the type-7 definition), with class breaks:

| class | range | colour (RGBA) |
| --- | --- | --- |
| 1 | 0.008683 - 0.066268 | 125,139,143,**26** (10 % alpha grey) |
| 2 | 0.066268 - 0.100785 | 200,220,240 (opaque) |
| 3 | 0.100785 - 0.146207 | 115,178,216 (opaque) |
| 4 | 0.146207 - 0.225284 | 41,121,185 (opaque) |
| 5 | 0.225284 - 0.531341 | 15,88,197 (opaque) |

Wards per class: 29 / 29 / 28 / 29 / 29. Camera share per class:
23.4 / 19.0 / 21.8 / 22.7 / 13.1 per cent.

The lowest class is deliberately drawn at 10 % opacity, so its printed colour
is the basemap showing through, not the swatch colour. This is easy to misread
as "no data": if the maps are reproduced, either keep that choice consistent or
replace it with an opaque pale tint.

## Map 2 - total population

`Map2_population.png`, layout `Map2_Pop`.

Ward shading is absolute 2011 ward population (`census2011_TOT_P`), again in
five quantile classes:

| class | range | colour (RGBA) |
| --- | --- | --- |
| 1 | 10 752 - 15 031.8 | 125,139,143,**26** (10 % alpha grey) |
| 2 | 15 031.8 - 17 714.8 | 201,234,194 (opaque) |
| 3 | 17 714.8 - 20 308.6 | 123,199,124 (opaque) |
| 4 | 20 308.6 - 26 367 | 42,146,75 (opaque) |
| 5 | 26 367 - 49 363 | 0,108,43 (opaque) |

Class breaks are printed in the figure rounded to whole people (10 752 - 15 032
and so on). Wards per class: 29 / 29 / 28 / 29 / 29. Camera share per class:
28.4 / 15.4 / 15.8 / 16.5 / 23.8 per cent.

Population is a baseline, not a provision measure: the classes are quintiles of
ward totals, which is why the top class covers 44 % of the mapped ward area but
only 23.8 % of the cameras.

## Map 3 - camera share relative to population share

`Map3_camera-relative-pop-density.png`, layout `Map3_CamDensityShare`, 7015 x
4960 at 600 dpi. The filename predates the correction and says "pop-density";
the map is a population-share ratio, not a density measure.

Ward shading is the ratio of a ward's share of tender-recorded cameras to its
share of the 2011 ward population:

```
("cam_all" / sum("cam_all")) / ("census2011_TOT_P" / sum("census2011_TOT_P"))
```

where `cam_all` is the virtual field defined above. A value of 1 means the ward
holds the same share of the city's cameras as of its residents; 2 means twice
that share; 0.5, half. The five classes are 0-0.5, 0.5-1, 1-2, 2-3.5 and
3.5-5.5. The maximum ratio is 5.39; the fixed classes hold 33 / 53 / 40 / 11 / 7
wards. 18 wards exceed 2, 33 fall below 0.5, and 23 of the 29 Q5 wards lie
between 0.5 and 2. Two wards (92 and 114) have no cameras inside them, so their
ratio is 0.

Map 3 is a choropleth only: its legend lists the ward layer alone and no camera
points are drawn. This differs from Maps 1 and 2 and matches the section text,
which describes Map 3 as a ward-scale ratio map. The caption reads "2011
population-share camera allocation, shaded by the ward's share of
tender-recorded cameras divided by its share of city-wide population."

## Layout and export settings

All three delivered maps are A4 landscape, 297 x 210 mm, with the map item
filling the page, exported at 600 dpi to 7015 x 4960 px. They share the extent
73.764111 E to 73.945316 E, 18.447701 N to 18.597287 N. Each layout has a map, a
legend, a scale bar in kilometres, and a title/description label in 10 pt
Adwaita Sans on the right-hand side. PNG, lossless, sRGB, 8 bit per channel.

## Provenance gaps

1. **The QGIS join is manual.** The committed
   `2011census_wards-with-cameras-all.gpkg` is the authority for the per-ward
   camera sums. `scripts/build_table3.py` reads that join but does not re-run
   the point-in-polygon assignment. The join inputs and control totals are
   documented above.
2. **`cam_all` is a virtual field.** It is defined in the `.qgz` as
   `coalesce("camera_count_sum",0) + coalesce("camera_count_sum_2",0)` and is
   not stored in the GeoPackage. A reader who opens the GeoPackage alone will
   not see it.
3. **The filename is historical.** `Map3_camera-relative-pop-density.png` says
   "pop-density"; the map is a population-share ratio. The caption and the
   expression are correct; the filename is retained because it is the delivered
   path. Do not rename the file without updating the manifest, `figures.csv` and
   the manuscript's figure call.

## Checks performed on the delivered files

The figures were checked against the raw data independently of QGIS:

- **Census filter and control totals.** Filtering the 160-row CSV to integer
  ward numbers, excluding "Total" rows and Yewalewadi, yields exactly 144 wards
  and reproduces the documented control totals: population 3 124 458, SC 419 396,
  ST 34 025, households 742 602.
- **Map 1 and Map 2 breaks.** Recomputing the quintile breaks from the cleaned
  CSV reproduces every break in the project to floating-point precision
  (largest relative difference 1.6e-14), confirming both the formula and the
  quantile method.
- **Map 3 ratio and classes.** Recomputing the ratio from the committed join
  gives a maximum of 5.39 and class counts 33 / 53 / 40 / 11 / 7. The same
  calculation gives 18 wards above 2, 33 below 0.5, and 23 of the 29 Q5 wards
  between 0.5 and 2. `scripts/build_table3.py` records 18 checks over the same
  ward layer and the Table 3 totals.
- **Camera accounting.** The PUNE-scope point layers contain 1 365 sites and
  3 963 cameras (Annexure A: 358 sites, 1 077 cameras; Annexure B: 1 007 sites,
  2 886 cameras). 1 078 sites (3 109 cameras) fall inside the 144 wards; 284
  geocoded sites (854 cameras) fall outside, and 3 sites (14 cameras) have no
  usable coordinate. The ward frame is PMC-only by design.

## Known limitations

Carried over from the data documentation, and relevant to how these figures may
be read:

- Demographics are 2011 Census; camera locations are 2024 tender schedules, not
  installed assets. The maps show co-location, not causation.
- The 144-ward boundary file is a community publication; its correspondence to
  Census geography is the author's statement, not an official product. See
  `metadata/sources.csv` and `DATA-LICENCES.md`.
- About a fifth of geocoded sites (284 of 1,365) lie outside PMC, so the
  choropleths describe only the in-PMC subset while the point layers still show
  the rest.
- Maps 1 and 2 are quintiles; Map 3 uses fixed ratio classes. The three legends
  are not interchangeable and cannot be compared class by class.
- Legend symbols for the camera points are fixed-size; the legend does not show
  the size scale (`0.1 + 0.4 x camera_count` mm), so circle sizes cannot be read
  quantitatively from the legend alone.
- Map 3 counts residents only. A ward with commercial, administrative or
  transport functions and few residents can score high without holding many
  cameras in absolute terms.

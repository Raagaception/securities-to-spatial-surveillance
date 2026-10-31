# Licensing of the data

The MIT licence in `LICENSE` covers the code in `scripts/`. It does not cover
the files in `data/raw/`, which were published by other people under their own
terms. Each file keeps the licence recorded for it in `metadata/sources.csv`;
this page spells those out and notes what each one requires of you.

No single licence covers the whole repository. A blanket statement such as
"data: CC BY 4.0" would be wrong for several of these files.

| file | licence | what it requires |
| --- | --- | --- |
| `western-zone-261024.osm.pbf` | ODbL 1.0 | attribution to OpenStreetMap contributors; share-alike for derived databases |
| `pune-electoral-wards_2012.geojson` | CC BY 4.0 | attribution |
| `pune-electoral-wards_2017.geojson` | CC BY 4.0 | attribution |
| `pune-electoral-wards_2022.geojson` | CC BY 4.0 | attribution |
| `DDW_PCA2725_2011_MDDS_with_UI.xlsx` | unverified | check with Census of India before redistribution |
| `Tendernotice_2-PuneCCTVVOLII.pdf` | government tender document | no open licence asserted; treat as a published government record |
| `tender-details-DGP176162-PuneCCTV-2024_DGPMU_1017794_1.pdf` | government tender document | as above |
| `pune-pmc-census2011-ward-demographics.csv` | public domain | none |
| `pune-pre-2012-144-ward-boundaries_nikhilvj.geojson` | GPL-3.0, unverified | see below before redistributing |

## OpenStreetMap extract

The `.pbf` is an OpenStreetMap extract, so ODbL 1.0 applies. Maps and figures
made from it need the credit line "© OpenStreetMap contributors". A derived
database that is publicly used may need to be shared under the same licence.
Consult the ODbL text if you plan to publish processed OSM data rather than a
rendered map.

## Ward boundaries from DataMeet

The 2012, 2017 and 2022 ward files come from the DataMeet `Municipal_Spatial_Data`
repository and are published under CC BY 4.0. Attribution to DataMeet and to the
Municipal Corporation is appropriate. Cite the files as they are recorded in
`metadata/sources.csv`.

## Census Primary Census Abstract

The licence of the Census workbook is recorded as unverified because the Census
of India catalogue does not state one clearly. Indian government data is
generally published for public use, but the exact terms are not settled here.
Verify before republishing the file itself.

## Tender documents

The two PDFs were issued by Pune Police through the Maharashtra e-tendering
portal. They are public records. Extracting and quoting from them is normal
research practice; redistributing the PDFs in this repository relies on that
being acceptable for a public tender document, which is recorded as a
government tender document rather than as an open licence.

## Ward-level Census table

The OpenCity catalogue lists this file as "Other (Public Domain)". Public domain
status is open in the sense used by the Open Definition 2.1, so no conditions
attach. Attribution is courteous but not required.

## Pre-2012 144-ward boundaries

This is the one file that needs care.

It is a community publication by Nikhil VJ (DataMeet Pune chapter), not an
official survey product. The repository that hosts it carries GPL-3.0, and how
that licence applies to this particular geometry, and to the upstream boundary
rights, has not been established. Do not describe the file as official Census
ward boundaries, and do not relicense it under CC BY on the strength of
DataMeet's general practice for other datasets.

For redistribution beyond this repository, ask the author first. The contact
address published on the documentation page is nikhil.js@gmail.com. The file's
own documentation is at https://answerquest.github.io/pune_07-12-17_sync.html.

## Extracted tables in `outputs/extraction/`

Those CSVs are derived from the tender document and from the ward and Census
files. They carry the terms of whatever they were derived from, which in
practice means the tender document for the site tables. The repository authors
claim no additional rights over them.

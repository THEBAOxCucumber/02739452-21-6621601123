# Reference data

`country_centroids.csv` — ISO 3166-1 alpha-3 code → approximate country centre (lat, lon).

Derived from `countries.json` of [mledoze/countries](https://github.com/mledoze/countries)
tag `v4.1.1` (fields `cca3`, `name.common`, `latlng`), licensed under the
[Open Database License (ODbL) v1.0](https://opendatacommons.org/licenses/odbl/1-0/).
This derived table is likewise available under ODbL.

Used only to place ReliefWeb disasters (which the ReliefWeb API reports per country, without
coordinates) on the map. Rows positioned this way have
`raw_data.location_precision = "country_centroid"`.

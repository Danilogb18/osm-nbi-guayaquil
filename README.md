# Caracterización socioeconómica de vecindarios urbanos de Guayaquil con OpenStreetMap

Código y datos del proyecto de Metodología de Investigación en Computación (ESPOL).
El objetivo es construir una tipología de las zonas censales urbanas de Guayaquil a partir de indicadores del entorno construido calculados con OpenStreetMap (OSM), y describir cada tipo con la pobreza por Necesidades Básicas Insatisfechas (NBI) del Censo 2022.

El resultado actual es el dataset analítico: **una fila por zona censal urbana (698 zonas, 693 en el análisis)**, con 10 variables de agrupamiento calculadas con OSM, 3 variables de control de completitud de OSM y la pobreza por NBI con sus cinco dimensiones.
La regla central del diseño es que el NBI no interviene en la construcción de los tipos ni en la selección de variables; solo se usa para describirlos y validarlos.

## Estructura

```
scripts/                  código, numerado en orden de ejecución
datos/
  fuentes/                datos originales (no se suben; ver datos/fuentes/README.md)
  intermedios/            salidas de un paso que alimentan al siguiente
  final/                  dataset analítico, diccionario y descriptivos
resultados/
  diagnosticos/           evidencia de decisiones (escala, descarte de variables)
docs/                     notas metodológicas
```

## Qué hace cada script

| Script | Qué hace | Entradas | Salidas |
|---|---|---|---|
| `01_extraer_guayaquil.py` | Lee por partes los CSV nacionales del censo y conserva solo el cantón Guayaquil (`I01 = 09`, `I02 = 01`) | Los 3 CSV nacionales (vivienda, hogar, población) | `gye_vivienda.csv`, `gye_hogar.csv`, `gye_poblacion.csv`, y `muestra_*.csv` (solo para explorar) |
| `02_nbi_dimensiones.py` | Reconstruye las 5 dimensiones del NBI por hogar, valida contra el NBI oficial (100 % de coincidencia en 810.592 hogares) y agrega por sector | `gye_*.csv` | `nbi_hogares.csv` (auditoría), `nbi_sectores.csv` |
| `03_recortar_sectores.py` | Lista las capas de la capa nacional de sectores del INEC y recorta el cantón Guayaquil | `sectores_anonimizados.gpkg` | `sectores_guayaquil.gpkg` |
| `04_osm_por_sector.py` | Primer intento: indicadores OSM por **sector** censal | `.osm.pbf`, `sectores_guayaquil.gpkg`, `nbi_sectores.csv` | `osm_sectores.csv`, `tabla_final.csv` |
| `05_diagnostico_osm.py` | Diagnóstico de cobertura de OSM por sector y por quintil de pobreza; justificó pasar de sector a zona | `tabla_final.csv` | Solo imprime en pantalla |
| `06_zonas_osm.py` | **Script central.** Funde los sectores en zonas, calcula los indicadores OSM (conteos, longitudes, áreas y distancias ponderadas por población), agrega el NBI y diagnostica cobertura, sesgo de completitud y redundancia | `.osm.pbf`, `sectores_guayaquil.gpkg`, `nbi_sectores.csv` | `tabla_zonas.csv` (698 × 76), `correlaciones_zonas.csv` |
| `07_armar_dataset.py` | Selecciona y ordena las columnas del dataset analítico y lo documenta. No transforma los valores | `tabla_zonas.csv` | `dataset_zonas.csv`, `dataset_zonas.xlsx`, `diccionario_variables.csv`, `descriptivos.csv` |

Los scripts 04 y 05 no alimentan el dataset final, pero son la evidencia de la decisión de trabajar por zona censal: a escala de sector, el 42,7 % de los sectores no tiene ningún punto de interés en OSM.

Los siguientes pasos (preparación de la matriz, agrupamiento, perfil NBI por tipo y validación espacial) se agregarán como `08_...` en adelante.

## Datos incluidos en el repositorio

| Carpeta | Archivo | Por qué está |
|---|---|---|
| `datos/intermedios/` | `sectores_guayaquil.gpkg` | Polígonos de los sectores del cantón (7 MB); evita descargar la capa nacional de 688 MB |
| | `nbi_sectores.csv` | NBI y sus 5 dimensiones por sector (6.648 sectores); evita procesar los microdatos del censo |
| | `tabla_zonas.csv` | Todos los indicadores candidatos por zona (698 × 76) |
| `datos/final/` | `dataset_zonas.csv` y `.xlsx` | Dataset analítico (698 × 29) |
| | `diccionario_variables.csv` | Qué es cada columna, unidad y uso |
| | `descriptivos.csv` | Estadísticos por variable, incluida la asimetría |
| `resultados/diagnosticos/` | `correlaciones_zonas.csv` | Spearman entre variables candidatas; justifica los descartes por redundancia |
| | `osm_sectores.csv`, `tabla_final.csv` | Resultados a escala de sector; evidencia de la decisión de escala |

**No incluidos** (por tamaño; se regeneran con los scripts): las fuentes originales, los `gye_*.csv` (hasta 700 MB), `nbi_hogares.csv` (90 MB) y los `muestra_*.csv`.
Con lo que sí está incluido se puede ejecutar desde el paso 06 en adelante descargando solo el extracto de OSM.

## Cómo reproducir

Requisitos: Python 3.9 o superior y `pip install -r requirements.txt`.
Primero hay que descargar las fuentes en `datos/fuentes/` (ver `datos/fuentes/README.md`).

Cada paso se ejecuta desde la carpeta donde deben quedar sus salidas, porque los scripts escriben en la carpeta actual.

```bash
# Rama A: pobreza por NBI desde el censo (el paso 01 tarda varios minutos)
cd datos/fuentes
python3 ../../scripts/01_extraer_guayaquil.py
mv gye_*.csv ../intermedios/
rm muestra_*.csv
cd ../intermedios
python3 ../../scripts/02_nbi_dimensiones.py gye_vivienda.csv gye_hogar.csv gye_poblacion.csv

# Rama B: polígonos de los sectores
python3 ../../scripts/03_recortar_sectores.py ../fuentes/sectores_anonimizados.gpkg

# Unión por zona censal (unos 30 s) y dataset final
python3 ../../scripts/06_zonas_osm.py ../fuentes/ecuador-latest.osm.pbf sectores_guayaquil.gpkg nbi_sectores.csv
mv correlaciones_zonas.csv ../../resultados/diagnosticos/
cd ../final
python3 ../../scripts/07_armar_dataset.py ../intermedios/tabla_zonas.csv

# Opcional: evidencia de la decisión de escala (sector)
cd ../../resultados/diagnosticos
python3 ../../scripts/04_osm_por_sector.py ../../datos/fuentes/ecuador-latest.osm.pbf ../../datos/intermedios/sectores_guayaquil.gpkg ../../datos/intermedios/nbi_sectores.csv
python3 ../../scripts/05_diagnostico_osm.py tabla_final.csv
```

El script 01 busca los CSV nacionales por nombre (`CPV_2022_Vivienda_Sector.csv`, `CPV_2022_Hogar_Sector.csv`, `CPV_2022_Poblacion_Sector.csv`); si los archivos descargados tienen otro nombre, hay que ajustarlo al inicio del script.

## Decisiones principales

- **Área de estudio:** parroquia urbana de Guayaquil (código 090150), solo sectores amanzanados: 6.371 sectores, 310 km².
- **Unidad de análisis:** zona censal (sectores que comparten los 9 primeros dígitos del código): 698 zonas; se excluyen 1 con menos de 50 hogares y 4 que no son contiguas al área urbana (poblados aislados cerca de la vía a la Costa, a entre 11 y 28 km de la ciudad). Quedan 693 en el análisis; el motivo de cada exclusión está en la columna `motivo_exclusion`.
- **Variables de agrupamiento (10):** densidad vial, proporción de vías sin pavimentar, distancia a vía principal, comercio cotidiano, comercio formal, servicios sociales y recreación (por 1.000 habitantes), y distancias a salud, escuela y mercado (ponderadas por población).
- **Selección:** justificación teórica, cobertura, redundancia (|ρ de Spearman| ≥ 0,8) y nunca según la correlación con el NBI.
- **Completitud de OSM:** tres variables de control (POIs totales, edificios mapeados, cobertura de la etiqueta `surface`) que no entran al agrupamiento.

## Advertencias conocidas

- GDAL muestra avisos "Non closed ring detected" al leer el `.pbf`; vienen de multipolígonos mal cerrados en OSM y no afectan los resultados.
- En `04_osm_por_sector.py`, el mensaje en pantalla "Sectores sin ningún POI" cuenta de menos porque su filtro de columnas incluye `km_via_sin_pavimento`. Los CSV generados están bien.

## Fuentes de datos

- INEC, Censo de Población y Vivienda 2022, bases a nivel de sector.
- INEC, capa de sectores censales anonimizados (Geoportal).
- OpenStreetMap, extracto de Ecuador distribuido por Geofabrik, descargado el 5 de noviembre de 2026. Datos © colaboradores de OpenStreetMap, licencia ODbL.

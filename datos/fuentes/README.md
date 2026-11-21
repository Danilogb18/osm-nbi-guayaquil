# Fuentes de datos (no incluidas en el repositorio)

Estos archivos son demasiado grandes para GitHub. Hay que descargarlos y guardarlos en esta carpeta con estos nombres.

| Archivo | Tamaño aprox. | De dónde se obtiene |
|---|---|---|
| `CPV_2022_Vivienda_Sector.csv` | 650 MB | INEC, Censo de Población y Vivienda 2022, bases de datos a nivel de sector (https://www.censoecuador.gob.ec/) |
| `CPV_2022_Hogar_Sector.csv` | 780 MB | Misma fuente |
| `CPV_2022_Poblacion_Sector.csv` | 4,4 GB | Misma fuente |
| `sectores_anonimizados.gpkg` | 690 MB | Geoportal del INEC, botón "Descargar nueva capa de sectores anonimizados" (no el "Marco Geoestadístico Cantonal") |
| `ecuador-latest.osm.pbf` | 125 MB | Geofabrik: https://download.geofabrik.de/south-america/ecuador.html (el proyecto usó el extracto descargado el 5 de noviembre de 2026; uno más reciente puede dar cifras ligeramente distintas) |

Documentos de apoyo para el NBI: libro metodológico del INEC "¿Cómo se mide la pobreza en Ecuador a partir de los censos? El método NBI explicado" (Cuadro 1), sintaxis REDATAM del NBI 2010 y diccionario de variables del censo a nivel de sector.

Si solo se quiere reproducir desde el paso 06, basta con descargar `ecuador-latest.osm.pbf`: los demás insumos de ese paso ya están en `datos/intermedios/`.

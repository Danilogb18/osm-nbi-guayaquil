"""
Arma el DATASET ANALÍTICO del proyecto: una fila por zona censal, con los
indicadores de OpenStreetMap en valores originales (sin logaritmo ni
estandarización) a la izquierda y el NBI a la derecha.

Uso:
    python3 armar_dataset.py tabla_zonas.csv

Entrada:
    tabla_zonas.csv  (salida de zonas_osm.py, 698 filas x 76 columnas)

Salidas:
    dataset_zonas.csv          el dataset: 698 filas, columnas ordenadas por bloque
                               (693 en análisis; ver en_analisis y motivo_exclusion)
    diccionario_variables.csv  qué es cada columna, unidad, fuente y para qué se usa
    descriptivos.csv           estadísticos de cada variable (solo zonas en análisis)
    dataset_zonas.xlsx         lo mismo en un Excel de tres hojas (si hay openpyxl)

Bloques de columnas, de izquierda a derecha:
    identificación -> 10 variables de agrupamiento (OSM) -> control de
    completitud (OSM) -> NBI (salida).
Las transformaciones (log, estandarización) NO se hacen aquí: se aplican en el
script de agrupamiento, sobre una copia, para que este archivo siga siendo
legible y verificable.
"""
import sys
import pandas as pd

MIN_HOGARES = 50   # zonas con menos hogares quedan marcadas fuera del análisis

# Zonas amanzanadas de la parroquia urbana 090150 que NO son contiguas al área
# urbana continua de Guayaquil: son poblados aislados cerca de la vía a la Costa,
# a entre 11 y 28 km de la zona más cercana de la ciudad (distancia entre
# polígonos medida con sectores_guayaquil.gpkg, EPSG:32717; revisado en mapa el
# 25 nov. 2026). Sus distancias a servicios miden aislamiento geográfico, no
# condiciones de un vecindario urbano. Se excluyen por su ubicación, sin mirar el NBI.
ZONAS_NO_CONTIGUAS = ["090150931", "090150944", "090150946", "090150948"]

# (columna, bloque, descripción, unidad, fuente, decimales)
DICCIONARIO = [
    # --- Identificación y denominadores ---
    ("zona", "Identificación",
     "Código de zona censal: primeros 9 dígitos del código de sector (provincia 2, cantón 2, parroquia 2, zona 3)",
     "código", "INEC, capa de sectores anonimizados", None),
    ("en_analisis", "Identificación",
     f"Verdadero si la zona entra al análisis (al menos {MIN_HOGARES} hogares y contigua al área urbana)",
     "sí/no", "Derivado", None),
    ("motivo_exclusion", "Identificación",
     "Por qué la zona queda fuera del análisis (vacío si entra)",
     "texto", "Derivado", None),
    ("n_sectores", "Identificación", "Sectores censales amanzanados que forman la zona",
     "sectores", "INEC, capa de sectores", 0),
    ("area_km2", "Identificación", "Área de la zona", "km²", "INEC, capa de sectores", 4),
    ("pob_t", "Identificación", "Población censal de la zona (suma de pob_t de sus sectores)",
     "personas", "INEC, capa de sectores (Censo 2022)", 0),

    # --- 10 variables candidatas al agrupamiento ---
    ("dens_vial_km_km2", "Agrupamiento: red vial",
     "Longitud de vías vehiculares (principales, secundarias, residenciales y caminos) por km² de zona",
     "km/km²", "OSM (highway)", 2),
    ("prop_sin_pavimento", "Agrupamiento: red vial",
     "Proporción de los km vehiculares sin pavimentar (surface = unpaved, dirt, gravel...; o highway=track sin surface)",
     "proporción 0-1", "OSM (highway, surface)", 4),
    ("dist_via_principal_m", "Agrupamiento: red vial",
     "Distancia a la vía principal o secundaria más cercana, desde cada sector, promediada por población",
     "m", "OSM (highway)", 0),
    ("comercio_cotidiano_x1000hab", "Agrupamiento: servicios y comercio",
     "Tiendas de barrio, comida y mercados por 1.000 habitantes",
     "por 1.000 hab.", "OSM (shop, amenity) + población INEC", 3),
    ("comercio_formal_x1000hab", "Agrupamiento: servicios y comercio",
     "Supermercados, bancos y cajeros, y oficinas por 1.000 habitantes",
     "por 1.000 hab.", "OSM (shop, amenity, office) + población INEC", 3),
    ("servicios_sociales_x1000hab", "Agrupamiento: servicios y comercio",
     "Salud, educación y servicios públicos por 1.000 habitantes",
     "por 1.000 hab.", "OSM (amenity, healthcare) + población INEC", 3),
    ("recreacion_x1000hab", "Agrupamiento: servicios y comercio",
     "Parques, canchas, juegos infantiles y centros deportivos por 1.000 habitantes",
     "por 1.000 hab.", "OSM (leisure) + población INEC", 3),
    ("dist_salud_m", "Agrupamiento: accesibilidad",
     "Distancia al hospital, clínica o consultorio más cercano, desde cada sector, promediada por población",
     "m", "OSM (amenity, healthcare)", 0),
    ("dist_escuela_m", "Agrupamiento: accesibilidad",
     "Distancia a la escuela o centro de educación inicial más cercano, promediada por población",
     "m", "OSM (amenity)", 0),
    ("dist_mercado_m", "Agrupamiento: accesibilidad",
     "Distancia al mercado o supermercado más cercano, promediada por población",
     "m", "OSM (amenity, shop)", 0),

    # --- Control de completitud: NO entran al agrupamiento ---
    ("poi_total", "Control de completitud",
     "Total de puntos de interés clasificados en la zona (todas las categorías)",
     "conteo", "OSM", 0),
    ("n_edificios_osm", "Control de completitud", "Edificios dibujados en OSM dentro de la zona",
     "conteo", "OSM (building)", 0),
    ("cobertura_superficie", "Control de completitud",
     "Proporción de los km vehiculares que tienen la etiqueta surface (cuánto creerle a prop_sin_pavimento)",
     "proporción 0-1", "OSM (surface)", 4),

    # --- Salida: NBI (no entra al agrupamiento) ---
    ("n_hogares", "Salida: NBI", "Hogares de la zona con datos de NBI", "hogares",
     "Censo 2022, microdatos", 0),
    ("n_personas", "Salida: NBI", "Personas en esos hogares", "personas",
     "Censo 2022, microdatos", 0),
    ("p_nbi_personas", "Salida: NBI",
     "Proporción de personas pobres por NBI (variable principal; comparable con el 28,7 % cantonal)",
     "proporción 0-1", "Censo 2022, reconstrucción validada", 4),
    ("p_nbi", "Salida: NBI", "Proporción de hogares pobres por NBI (al menos una carencia)",
     "proporción 0-1", "Censo 2022, reconstrucción validada", 4),
    ("prom_carencias", "Salida: NBI", "Número medio de carencias por hogar (0 a 5)",
     "carencias", "Censo 2022, reconstrucción validada", 3),
    ("p_vivienda", "Salida: NBI", "Proporción de hogares con vivienda de materiales deficitarios",
     "proporción 0-1", "Censo 2022, reconstrucción validada", 4),
    ("p_servicios", "Salida: NBI", "Proporción de hogares sin servicios básicos adecuados",
     "proporción 0-1", "Censo 2022, reconstrucción validada", 4),
    ("p_hacin", "Salida: NBI", "Proporción de hogares en hacinamiento crítico",
     "proporción 0-1", "Censo 2022, reconstrucción validada", 4),
    ("p_ninos", "Salida: NBI", "Proporción de hogares con niños de 6 a 12 años que no asisten a clases",
     "proporción 0-1", "Censo 2022, reconstrucción validada", 4),
    ("p_depend", "Salida: NBI", "Proporción de hogares con alta dependencia económica",
     "proporción 0-1", "Censo 2022, reconstrucción validada", 4),
]


def main(ruta):
    t = pd.read_csv(ruta, dtype={"zona": str})
    pocos_hogares = t["n_hogares"].fillna(0) < MIN_HOGARES
    no_contigua = t["zona"].isin(ZONAS_NO_CONTIGUAS)
    t["motivo_exclusion"] = ""
    t.loc[pocos_hogares, "motivo_exclusion"] = f"menos de {MIN_HOGARES} hogares"
    t.loc[no_contigua, "motivo_exclusion"] = "no contigua al área urbana"
    t["en_analisis"] = t["motivo_exclusion"] == ""
    no_encontradas = set(ZONAS_NO_CONTIGUAS) - set(t["zona"])
    if no_encontradas:
        sys.exit(f"Zonas no contiguas que no aparecen en {ruta}: {sorted(no_encontradas)}")

    cols = [c for c, *_ in DICCIONARIO]
    faltan = [c for c in cols if c not in t.columns]
    if faltan:
        sys.exit(f"Faltan columnas en {ruta}: {faltan}. ¿Es la salida de zonas_osm.py?")

    ds = t[cols].copy()
    for c, _, _, _, _, dec in DICCIONARIO:
        if dec is not None:
            ds[c] = ds[c].round(dec)
            if dec == 0:
                ds[c] = ds[c].astype("Int64")
    ds = ds.sort_values("zona").reset_index(drop=True)
    ds.to_csv("dataset_zonas.csv", index=False)

    dic = pd.DataFrame(DICCIONARIO, columns=["columna", "bloque", "descripcion", "unidad",
                                             "fuente", "decimales"]).drop(columns="decimales")
    dic.insert(0, "n", range(1, len(dic) + 1))
    dic.to_csv("diccionario_variables.csv", index=False)

    # Descriptivos en valores originales (lo que se reporta en el paper)
    num = [c for c, b, *_ in DICCIONARIO if b != "Identificación" or c in ("area_km2", "pob_t", "n_sectores")]
    base = ds[ds["en_analisis"]][num].astype(float)
    desc = pd.DataFrame({
        "bloque": dic.set_index("columna").loc[num, "bloque"],
        "n": base.notna().sum(),
        "media": base.mean(),
        "desv_est": base.std(),
        "min": base.min(),
        "p25": base.quantile(.25),
        "mediana": base.median(),
        "p75": base.quantile(.75),
        "max": base.max(),
        "pct_ceros": (base == 0).mean() * 100,
        "asimetria": base.skew(),
    }).round(3)
    desc.index.name = "variable"
    desc.to_csv("descriptivos.csv")

    try:
        with pd.ExcelWriter("dataset_zonas.xlsx") as xw:
            ds.to_excel(xw, sheet_name="datos", index=False)
            dic.to_excel(xw, sheet_name="diccionario", index=False)
            desc.to_excel(xw, sheet_name="descriptivos")
        excel = "dataset_zonas.xlsx (hojas: datos, diccionario, descriptivos)"
    except ImportError:
        excel = "no se generó el .xlsx (falta openpyxl: pip3 install openpyxl)"

    n_ok = int(ds["en_analisis"].sum())
    fuera = ds.loc[~ds["en_analisis"], ["zona", "motivo_exclusion", "n_hogares", "pob_t", "area_km2"]]
    print(f"dataset_zonas.csv: {len(ds):,} filas x {ds.shape[1]} columnas "
          f"({n_ok:,} en análisis)")
    if len(fuera):
        print("Fuera del análisis:")
        print(fuera.to_string(index=False))
    print(f"diccionario_variables.csv: {len(dic)} columnas descritas")
    print(f"descriptivos.csv: {len(desc)} variables")
    print(excel)
    print("\nDescriptivos de las 10 variables de agrupamiento:")
    pd.set_option("display.width", 160)
    print(desc[desc["bloque"].str.startswith("Agrupamiento")]
          .drop(columns=["bloque", "n"]).to_string())
    print("\nAsimetría > 1 indica una cola larga a la derecha: candidata a log(1 + x).")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "tabla_zonas.csv")
"""
Indicadores de OpenStreetMap por ZONA censal de Guayaquil, unión con el NBI
y diagnóstico para escoger las variables del agrupamiento.

Uso:
    python3 zonas_osm.py ecuador-latest.osm.pbf sectores_guayaquil.gpkg nbi_sectores.csv

Entradas:
    - .osm.pbf de Ecuador (Geofabrik). También acepta un .osm (XML).
    - sectores_guayaquil.gpkg (campos sec_anm y pob_t)
    - nbi_sectores.csv (salida de nbi_dimensiones.py)

Salidas:
    tabla_zonas.csv          una fila por zona: indicadores OSM + NBI agregado
    correlaciones_zonas.csv  Spearman entre las variables candidatas
    En pantalla, el diagnóstico:
      1. tamaño de las zonas (¿hay zonas con muy pocos hogares?)
      2. cobertura de cada variable candidata
      3. sesgo de completitud: ¿las zonas pobres están peor mapeadas?
      4. pares de variables redundantes

Regla de diseño: las columnas del NBI NO entran al agrupamiento ni se usan
para escoger variables. Solo se cruzan con las variables de CONTROL de
completitud (bloque 3), nunca con las candidatas.

Solo necesita geopandas, pyogrio y shapely 2 (GDAL trae lector de OSM).
"""
import re
import sys
import time

import numpy as np
import pandas as pd
import geopandas as gpd
import pyogrio
import shapely

CRS_METROS = 32717          # UTM 17S: metros y m²
MARGEN_M = 3000             # margen de lectura para que las distancias vean servicios fuera del borde
UMBRAL_REDUNDANCIA = 0.8    # |Spearman| a partir del cual dos variables se consideran redundantes
NORMALIZACION_POI = "x1000hab"   # "x1000hab" (oferta por residente) o "por_km2" (intensidad)

# ---------------------------------------------------------------------------
# 1. Definiciones (PROPUESTA para el grupo; editables sin tocar el resto)
#    Cada regla es (clave OSM, {valores} o None = cualquier valor).
#    Un elemento queda en la PRIMERA categoría cuyas reglas cumple.
# ---------------------------------------------------------------------------
CATEGORIAS_POI = {
    "mercado":        [("amenity", {"marketplace"})],
    "comida":         [("amenity", {"restaurant", "fast_food", "cafe", "bar", "pub",
                                    "ice_cream", "food_court"})],
    "finanzas":       [("amenity", {"bank", "atm", "bureau_de_change"})],
    "salud":          [("amenity", {"hospital", "clinic", "doctors", "dentist", "pharmacy"}),
                       ("healthcare", None)],
    "educacion":      [("amenity", {"school", "kindergarten", "college", "university",
                                    "library"})],
    "culto":          [("amenity", {"place_of_worship"})],
    "servicio_publico": [("amenity", {"police", "fire_station", "townhall",
                                      "post_office", "community_centre"})],
    "transporte":     [("amenity", {"fuel", "bus_station", "parking"}),
                       ("highway", {"bus_stop"})],
    "supermercado":   [("shop", {"supermarket", "mall", "department_store"})],
    "tienda_barrio":  [("shop", {"convenience", "general", "kiosk", "bakery", "butcher",
                                 "greengrocer", "variety_store"})],
    "comercio_otro":  [("shop", None)],
    "recreacion":     [("leisure", {"park", "playground", "sports_centre", "pitch",
                                    "fitness_centre", "swimming_pool", "garden"})],
    "turismo":        [("tourism", {"hotel", "guest_house", "hostel", "attraction",
                                    "museum"})],
    "oficina":        [("office", None)],
}

# Categorías finas fusionadas en grupos con sentido teórico.
GRUPOS_POI = {
    "comercio_cotidiano": ["tienda_barrio", "comida", "mercado"],
    "comercio_formal":    ["supermercado", "finanzas", "oficina"],
    "servicios_sociales": ["salud", "educacion", "servicio_publico"],
    "recreacion":         ["recreacion"],
}

# Red vial VEHICULAR. Se excluyen 'service' (pasillos de parqueadero, accesos
# privados) y las peatonales, que inflan la densidad y las intersecciones.
VIAS_VEHICULARES = {
    "principal":     {"motorway", "motorway_link", "trunk", "trunk_link",
                      "primary", "primary_link"},
    "secundaria":    {"secondary", "secondary_link", "tertiary", "tertiary_link"},
    "residencial":   {"residential", "living_street", "unclassified"},
    "sin_pavimento": {"track"},
}
SUPERFICIE_SIN_PAVIMENTO = {"unpaved", "dirt", "ground", "earth", "gravel", "fine_gravel",
                            "compacted", "sand", "mud", "grass", "rock", "pebblestone"}

# Destinos para distancias (desde cada sector, ponderadas por población).
DESTINOS = {
    "dist_salud_m":   [("amenity", {"hospital", "clinic", "doctors"}),
                       ("healthcare", {"hospital", "clinic", "centre", "doctor"})],
    "dist_escuela_m": [("amenity", {"school", "kindergarten"})],
    "dist_mercado_m": [("amenity", {"marketplace"}), ("shop", {"supermarket"})],
}

CATEGORIAS_SUELO = {
    "suelo_residencial": [("landuse", {"residential"})],
    "suelo_comercial":   [("landuse", {"commercial", "retail"})],
    "suelo_industrial":  [("landuse", {"industrial"})],
    "suelo_verde":       [("leisure", {"park", "garden", "recreation_ground"}),
                          ("landuse", {"grass", "forest", "meadow", "recreation_ground"}),
                          ("natural", {"wood", "scrub", "grassland"})],
}

# ---------------------------------------------------------------------------
# 2. Utilidades
# ---------------------------------------------------------------------------
def expandir_tags(df, claves):
    """GDAL deja muchas etiquetas en 'other_tags' como texto "k"=>"v",...
    Las convierte en columnas, sin pisar las que ya existen."""
    otros = df.get("other_tags")
    for k in claves:
        if k in df.columns:
            continue
        if otros is None:
            df[k] = None
            continue
        patron = re.compile(r'"' + re.escape(k) + r'"=>"((?:[^"\\]|\\.)*)"')
        df[k] = otros.str.extract(patron, expand=False)
    return df


def clasificar(df, reglas_por_cat):
    """Asigna la PRIMERA categoría cuyas reglas cumple cada fila (o NaN)."""
    cat = pd.Series(np.nan, index=df.index, dtype=object)
    for nombre, reglas in reglas_por_cat.items():
        ok = pd.Series(False, index=df.index)
        for clave, valores in reglas:
            col = df[clave]
            ok |= col.notna() if valores is None else col.isin(valores)
        cat = cat.where(cat.notna() | ~ok, nombre)
    return cat


def leer_capa(pbf, capa, bbox, claves):
    gdf = pyogrio.read_dataframe(pbf, layer=capa, bbox=bbox)
    gdf = expandir_tags(gdf, claves)
    gdf = gdf[gdf.geometry.notna()]
    return gdf.to_crs(CRS_METROS).reset_index(drop=True)


def contar(puntos, zonas, col):
    """Cuántos puntos de cada categoría caen dentro de cada zona."""
    j = gpd.sjoin(puntos[[col, "geometry"]], zonas[["zona", "geometry"]], predicate="within")
    return pd.crosstab(j["zona"], j[col])


def medir(geoms, cats, zonas, medida):
    """Corta líneas/polígonos en el borde de cada zona y suma longitud o área."""
    g = gpd.GeoDataFrame({"cat": np.asarray(cats, dtype=object)},
                         geometry=np.asarray(geoms), crs=CRS_METROS)
    g = g[g["cat"].notna()]
    if g.empty:
        return pd.DataFrame(index=pd.Index([], name="zona"))
    pares = gpd.sjoin(g, zonas[["zona", "geometry"]], predicate="intersects")
    corte = shapely.intersection(np.asarray(pares.geometry.values),
                                 np.asarray(zonas.geometry.values)[pares["index_right"].values])
    pares["valor"] = shapely.length(corte) if medida == "length" else shapely.area(corte)
    return pares.pivot_table(index="zona", columns="cat", values="valor",
                             aggfunc="sum", fill_value=0)


def intersecciones(lineas):
    """Puntos donde se cruzan 3 o más tramos de vía.
    union_all 'nodifica' la red: corta cada línea en cada cruce. Luego se
    cuentan los extremos de los tramos: grado 1 = calle sin salida, grado 2 =
    una vía que continúa, grado >= 3 = intersección.
    Limitación conocida: un paso a desnivel sin rampa cuenta como cruce."""
    red = shapely.union_all(np.asarray(lineas))
    seg = shapely.get_parts(red)
    seg = seg[shapely.get_type_id(seg) == 1]                      # LineString
    extremos = np.vstack([shapely.get_coordinates(shapely.get_point(seg, 0)),
                          shapely.get_coordinates(shapely.get_point(seg, -1))])
    nodos, grado = np.unique(np.round(extremos, 1), axis=0, return_counts=True)
    return nodos[grado >= 3], int((grado == 1).sum())


def media_ponderada(df, cols, peso, por):
    """Promedio por grupo ponderado por 'peso'. Si un grupo suma 0, promedio simple."""
    w = df[peso].astype(float)
    w = w.where(df.groupby(por)[peso].transform("sum") > 0, 1.0)
    w = w.where(df[cols].notna().all(axis=1), 0.0)
    num = df[cols].mul(w, axis=0).groupby(df[por]).sum(min_count=1)
    return num.div(w.groupby(df[por]).sum().replace(0, np.nan), axis=0)


# ---------------------------------------------------------------------------
# 3. Programa principal
# ---------------------------------------------------------------------------
def main(pbf, ruta_sectores, ruta_nbi):
    t0 = time.time()

    def paso(msg):
        print(f"[{time.time() - t0:5.0f} s] {msg}", flush=True)

    # --- Zonas: se arman disolviendo los sectores del área de estudio ---
    sect = gpd.read_file(ruta_sectores).to_crs(CRS_METROS)
    sect = sect[(sect.sec_anm.str[:6] == "090150") & (sect.sec_anm.str[6:9] != "999")].copy()
    sect["zona"] = sect.sec_anm.str[:9]
    sect["pob_t"] = pd.to_numeric(sect["pob_t"], errors="coerce").fillna(0)
    sect = sect.reset_index(drop=True)

    zonas = sect[["zona", "pob_t", "geometry"]].dissolve(by="zona", aggfunc="sum").reset_index()
    zonas["area_km2"] = zonas.area / 1e6
    zonas["n_sectores"] = zonas["zona"].map(sect.groupby("zona").size())
    paso(f"Sectores: {len(sect):,} -> zonas: {len(zonas):,}")

    minx, miny, maxx, maxy = zonas.total_bounds
    caja = shapely.box(minx - MARGEN_M, miny - MARGEN_M, maxx + MARGEN_M, maxy + MARGEN_M)
    bbox = tuple(gpd.GeoSeries([caja], crs=CRS_METROS).to_crs(4326).total_bounds)

    out = zonas.set_index("zona")[["n_sectores", "area_km2", "pob_t"]].copy()

    # --- Lectura de OSM ---
    claves_poi = ["amenity", "shop", "leisure", "tourism", "office", "healthcare", "highway"]
    pts = leer_capa(pbf, "points", bbox, claves_poi)
    paso(f"Puntos leídos: {len(pts):,}")
    pol = leer_capa(pbf, "multipolygons", bbox, claves_poi + ["landuse", "natural", "building"])
    paso(f"Polígonos leídos: {len(pol):,}")
    lin = leer_capa(pbf, "lines", bbox, ["highway", "surface"])
    paso(f"Líneas leídas: {len(lin):,}")

    # --- Puntos de interés (nodos + polígonos convertidos a un punto interior) ---
    pois = pd.concat([pts[claves_poi + ["geometry"]],
                      gpd.GeoDataFrame(pol[claves_poi].copy(),
                                       geometry=pol.representative_point().values,
                                       crs=CRS_METROS)],
                     ignore_index=True)
    pois = gpd.GeoDataFrame(pois, geometry="geometry", crs=CRS_METROS)
    pois["cat"] = clasificar(pois, CATEGORIAS_POI)

    conteo = contar(pois[pois["cat"].notna()], zonas, "cat")
    conteo = conteo.reindex(columns=list(CATEGORIAS_POI), fill_value=0)
    out = out.join(conteo.add_prefix("n_")).fillna(0)
    cols_n = [f"n_{c}" for c in CATEGORIAS_POI]
    out["poi_total"] = out[cols_n].sum(axis=1)
    for g, cats in GRUPOS_POI.items():
        out[f"n_g_{g}"] = out[[f"n_{c}" for c in cats]].sum(axis=1)

    # Diversidad: entropía de Shannon normalizada (0 = un solo tipo, 1 = todos por igual)
    p = out[cols_n].div(out["poi_total"].replace(0, np.nan), axis=0)
    h = -(p * np.log(p.where(p > 0))).sum(axis=1, min_count=1)
    out["diversidad_poi"] = (h / np.log(len(cols_n))).where(out["poi_total"] > 0)
    paso(f"POIs clasificados dentro de las zonas: {int(out['poi_total'].sum()):,}")

    # --- Red vial vehicular ---
    tipo = pd.Series(np.nan, index=lin.index, dtype=object)
    for nombre, valores in VIAS_VEHICULARES.items():
        tipo[lin["highway"].isin(valores)] = nombre
    veh = lin[tipo.notna()].copy()
    veh["tipo"] = tipo[tipo.notna()]
    sup = veh["surface"]
    veh["pav"] = np.where(sup.isin(SUPERFICIE_SIN_PAVIMENTO), "sin_pav",
                 np.where(sup.notna(), "pav",
                 np.where(veh["tipo"] == "sin_pavimento", "sin_pav", "desconocido")))

    veh["etiquetada"] = np.where(sup.notna(), "con_surface", None)
    km_tipo = medir(veh.geometry, veh["tipo"], zonas, "length") / 1000
    km_pav = medir(veh.geometry, veh["pav"], zonas, "length") / 1000
    km_etq = medir(veh.geometry, veh["etiquetada"], zonas, "length") / 1000
    out = out.join(km_tipo.add_prefix("km_")).join(km_pav.add_prefix("km_")) \
             .join(km_etq.add_prefix("km_"))
    for c in ["km_principal", "km_secundaria", "km_residencial", "km_sin_pavimento",
              "km_sin_pav", "km_pav", "km_desconocido", "km_con_surface"]:
        if c not in out:
            out[c] = 0.0
    out = out.fillna({c: 0 for c in out.columns if c.startswith("km_")})
    km_veh = out[["km_principal", "km_secundaria", "km_residencial", "km_sin_pavimento"]].sum(axis=1)
    out["km_vehicular"] = km_veh
    out["dens_vial_km_km2"] = km_veh / out["area_km2"]
    out["prop_vias_jerarquicas"] = (out["km_principal"] + out["km_secundaria"]) / km_veh.replace(0, np.nan)
    out["prop_sin_pavimento"] = out["km_sin_pav"] / km_veh.replace(0, np.nan)
    # Proporción de km vehiculares con etiqueta 'surface': dice cuánto creerle a prop_sin_pavimento
    out["cobertura_superficie"] = out["km_con_surface"] / km_veh.replace(0, np.nan)
    paso(f"Vías vehiculares: {len(veh):,} tramos, {km_veh.sum():,.0f} km dentro de las zonas")

    nodos, n_sin_salida = intersecciones(veh.geometry)
    pts_int = gpd.GeoDataFrame(geometry=shapely.points(nodos), crs=CRS_METROS)
    pts_int["tipo"] = "interseccion"
    n_int = contar(pts_int, zonas, "tipo")
    out["n_intersecciones"] = n_int.get("interseccion", pd.Series(dtype=float))
    out["n_intersecciones"] = out["n_intersecciones"].fillna(0)
    out["dens_intersecciones_km2"] = out["n_intersecciones"] / out["area_km2"]
    paso(f"Intersecciones: {len(nodos):,} en el área leída ({n_sin_salida:,} extremos sin salida)")

    # --- Distancias desde cada sector, promediadas por zona según población ---
    ps = gpd.GeoDataFrame(sect[["zona", "pob_t"]].copy(),
                          geometry=sect.representative_point().values, crs=CRS_METROS)
    destinos = dict()
    for nombre, reglas in DESTINOS.items():
        destinos[nombre] = pois[clasificar(pois, {nombre: reglas}).notna()][["geometry"]]
    principales = veh[veh["tipo"].isin(["principal", "secundaria"])][["geometry"]]
    destinos["dist_via_principal_m"] = principales.reset_index(drop=True)
    for nombre, obj in destinos.items():
        if obj.empty:
            ps[nombre] = np.nan
            continue
        d = gpd.sjoin_nearest(ps[["geometry"]], obj.reset_index(drop=True),
                              how="left", distance_col="_d")
        ps[nombre] = d.loc[~d.index.duplicated(), "_d"]
    cols_dist = list(destinos)
    out = out.join(media_ponderada(ps, cols_dist, "pob_t", "zona"))
    paso("Distancias calculadas: " + ", ".join(f"{k} ({len(v):,} destinos)" for k, v in destinos.items()))

    # --- Uso del suelo ---
    suelo = medir(pol.geometry.buffer(0), clasificar(pol, CATEGORIAS_SUELO), zonas, "area")
    suelo = suelo.reindex(columns=list(CATEGORIAS_SUELO), fill_value=0)
    out = out.join(suelo.div(1e6).add_prefix("km2_")).fillna(
        {f"km2_{c}": 0 for c in CATEGORIAS_SUELO})
    for c in CATEGORIAS_SUELO:
        out[f"pct_{c}"] = out[f"km2_{c}"] / out["area_km2"]
    out["pct_suelo_comercial_industrial"] = out["pct_suelo_comercial"] + out["pct_suelo_industrial"]
    out["pct_con_uso_suelo"] = out[[f"pct_{c}" for c in CATEGORIAS_SUELO]].sum(axis=1).clip(upper=1)

    # --- Edificaciones de OSM (sirven sobre todo como CONTROL de completitud) ---
    edif = pol[pol["building"].notna()]
    cent = gpd.GeoDataFrame({"m2": edif.area.values, "tipo": "edificio"},
                            geometry=edif.representative_point().values, crs=CRS_METROS)
    e = gpd.sjoin(cent, zonas[["zona", "geometry"]], predicate="within") \
           .groupby("zona")["m2"].agg(n_edificios_osm="size", m2_construidos_osm="sum")
    out = out.join(e).fillna({"n_edificios_osm": 0, "m2_construidos_osm": 0})
    out["dens_edificios_osm_km2"] = out["n_edificios_osm"] / out["area_km2"]
    out["pct_construido_osm"] = out["m2_construidos_osm"] / (out["area_km2"] * 1e6)
    out["area_media_edificio_m2"] = out["m2_construidos_osm"] / out["n_edificios_osm"].replace(0, np.nan)
    paso(f"Edificios OSM dentro de las zonas: {int(out['n_edificios_osm'].sum()):,}")

    # --- Normalización de los grupos de POIs ---
    for g in GRUPOS_POI:
        out[f"{g}_x1000hab"] = out[f"n_g_{g}"] / out["pob_t"].replace(0, np.nan) * 1000
        out[f"{g}_por_km2"] = out[f"n_g_{g}"] / out["area_km2"]

    # --- NBI por zona (agregado exacto: ponderado por hogares o por personas) ---
    nbi = pd.read_csv(ruta_nbi, dtype={"sector": str})
    nbi["zona"] = nbi["sector"].str[:9]
    nbi = nbi[nbi["zona"].isin(out.index)]
    dims_hog = ["p_nbi", "prom_carencias", "p_vivienda", "p_servicios", "p_hacin",
                "p_ninos", "p_depend"]
    z_nbi = nbi.groupby("zona")[["n_hogares", "n_personas"]].sum()
    z_nbi = z_nbi.join(media_ponderada(nbi, dims_hog, "n_hogares", "zona"))
    z_nbi = z_nbi.join(media_ponderada(nbi, ["p_nbi_personas"], "n_personas", "zona"))
    out = out.join(z_nbi)

    out = out.reset_index()
    out.to_csv("tabla_zonas.csv", index=False)
    paso(f"tabla_zonas.csv: {out.shape[0]:,} filas x {out.shape[1]} columnas")

    diagnostico(out)


# ---------------------------------------------------------------------------
# 4. Diagnóstico
# ---------------------------------------------------------------------------
def diagnostico(df):
    n = NORMALIZACION_POI
    candidatas = [
        "dens_vial_km_km2", "prop_vias_jerarquicas", "prop_sin_pavimento",
        "dens_intersecciones_km2",
        f"comercio_cotidiano_{n}", f"comercio_formal_{n}", f"servicios_sociales_{n}",
        f"recreacion_{n}", "diversidad_poi",
        "dist_salud_m", "dist_escuela_m", "dist_mercado_m", "dist_via_principal_m",
        "pct_suelo_verde", "pct_suelo_comercial_industrial", "area_media_edificio_m2",
    ]
    control = ["poi_total", "dens_edificios_osm_km2", "pct_construido_osm",
               "cobertura_superficie", "pct_con_uso_suelo"]
    pd.set_option("display.width", 140)

    con_nbi = df[df["n_hogares"].fillna(0) > 0].copy()

    print("\n== 1. Tamaño de las zonas ==")
    print(f"Zonas: {len(df):,} | con hogares: {len(con_nbi):,}")
    print("Hogares por zona (percentiles):")
    print(con_nbi["n_hogares"].quantile([.01, .05, .25, .5, .75, .95]).round(0).to_string())
    for u in (50, 100, 200):
        print(f"Zonas con menos de {u} hogares: {(con_nbi['n_hogares'] < u).sum()}")
    print("Área por zona en km² (percentiles):")
    print(df["area_km2"].quantile([.05, .25, .5, .75, .95]).round(3).to_string())

    print("\n== 2. Cobertura de las variables candidatas ==")
    filas = []
    for c in candidatas:
        s = con_nbi[c]
        filas.append({"variable": c,
                      "% zonas > 0": round(100 * (s > 0).mean(), 1),
                      "% sin dato": round(100 * s.isna().mean(), 1),
                      "mediana": s.median(),
                      "p90": s.quantile(.9)})
    t = pd.DataFrame(filas).set_index("variable")
    print(t.to_string(float_format=lambda v: f"{v:,.3f}"))
    print(f"\nMediana de cobertura de la etiqueta 'surface' en vías vehiculares: "
          f"{con_nbi['cobertura_superficie'].median():.1%}")

    print("\n== 3. Sesgo de completitud (solo variables de CONTROL frente al NBI) ==")
    et = ["Q1 menos pobre", "Q2", "Q3", "Q4", "Q5 más pobre"]
    con_nbi["quintil"] = pd.qcut(con_nbi["p_nbi_personas"].rank(method="first"), 5, labels=et)
    tab = con_nbi.groupby("quintil", observed=True).agg(
        nbi_medio=("p_nbi_personas", "mean"),
        con_edificios=("n_edificios_osm", lambda s: (s > 0).mean()),
        construido_med=("pct_construido_osm", "median"),
        poi_mediana=("poi_total", "median"),
        superficie_med=("cobertura_superficie", "median"),
        uso_suelo_med=("pct_con_uso_suelo", "median"),
    )
    print(tab.round(3).to_string())
    print("\nSpearman con % de personas pobres por NBI:")
    for c in control:
        print(f"  {c:<26} {con_nbi[c].corr(con_nbi['p_nbi_personas'], method='spearman'):+.2f}")

    print(f"\n== 4. Redundancia entre candidatas (|Spearman| >= {UMBRAL_REDUNDANCIA}) ==")
    corr = con_nbi[candidatas].corr(method="spearman")
    corr.to_csv("correlaciones_zonas.csv")
    pares = [(a, b, corr.loc[a, b]) for i, a in enumerate(candidatas)
             for b in candidatas[i + 1:] if abs(corr.loc[a, b]) >= UMBRAL_REDUNDANCIA]
    if not pares:
        print("Ningún par supera el umbral.")
    for a, b, r in sorted(pares, key=lambda x: -abs(x[2])):
        print(f"  {a:<32} {b:<32} {r:+.2f}")
    medios = [(a, b, corr.loc[a, b]) for i, a in enumerate(candidatas)
              for b in candidatas[i + 1:] if 0.6 <= abs(corr.loc[a, b]) < UMBRAL_REDUNDANCIA]
    print(f"Pares entre 0,6 y {UMBRAL_REDUNDANCIA} (a vigilar): {len(medios)}")
    for a, b, r in sorted(medios, key=lambda x: -abs(x[2])):
        print(f"  {a:<32} {b:<32} {r:+.2f}")
    print("\nMatriz completa: correlaciones_zonas.csv")


if __name__ == "__main__":
    if len(sys.argv) != 4:
        sys.exit(__doc__)
    main(*sys.argv[1:4])
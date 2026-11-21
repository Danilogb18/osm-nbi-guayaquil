"""
Cuenta y mide lo que hay en OpenStreetMap dentro de cada sector censal de Guayaquil.
 
Uso:
    python osm_por_sector.py ecuador-latest.osm.pbf sectores_guayaquil.gpkg [nbi_sectores.csv]
 
Entradas:
    - .osm.pbf de Ecuador (Geofabrik): https://download.geofabrik.de/south-america/ecuador.html
    - sectores_guayaquil.gpkg (polígonos de sectores, campo sec_anm)
    - opcional: nbi_sectores.csv; si se da, también se genera la tabla final unida.
 
Salidas:
    osm_sectores.csv  -> una fila por sector con indicadores OSM
    tabla_final.csv   -> osm_sectores + columnas del NBI (si se pasó nbi_sectores.csv)
 
Solo necesita geopandas y pyogrio: GDAL trae un lector de OSM incorporado.
"""
import re
import sys
import numpy as np
import pandas as pd
import geopandas as gpd
import pyogrio
import shapely
 
CRS_METROS = 32717  # UTM 17S: distancias en metros, áreas en m²
 
# ---------------------------------------------------------------------------
# 1. Categorías. Esto es una PROPUESTA para discutir en grupo: se puede editar
#    sin tocar el resto del código. Cada regla es (clave OSM, {valores} o None=todos).
# ---------------------------------------------------------------------------
CATEGORIAS_POI = {
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
    "comercio_otro":  [("shop", None)],          # cualquier otra tienda
    "recreacion":     [("leisure", {"park", "playground", "sports_centre", "pitch",
                                    "fitness_centre", "swimming_pool", "garden"})],
    "turismo":        [("tourism", {"hotel", "guest_house", "hostel", "attraction",
                                    "museum"})],
    "oficina":        [("office", None)],
}
 
CATEGORIAS_VIA = {
    "via_principal":   {"motorway", "motorway_link", "trunk", "trunk_link",
                        "primary", "primary_link"},
    "via_secundaria":  {"secondary", "secondary_link", "tertiary", "tertiary_link"},
    "via_residencial": {"residential", "living_street", "unclassified"},
    "via_servicio":    {"service"},
    "via_peatonal":    {"footway", "pedestrian", "path", "steps", "cycleway"},
    "via_sin_pavimento": {"track"},
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
_TAG = re.compile(r'"((?:[^"\\]|\\.)*)"=>"((?:[^"\\]|\\.)*)"')
 
def expandir_tags(df, claves):
    """GDAL deja muchas etiquetas en 'other_tags' como texto "k"=>"v",...
    Esta función las convierte en columnas, sin pisar las que ya existen."""
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
    return gdf.to_crs(CRS_METROS)
 
def medir_por_sector(geoms, cats, sectores, medida):
    """Corta líneas/polígonos en el borde de cada sector y suma longitud o área.
    Usa sjoin para hallar pares candidatos y luego intersección vectorizada."""
    g = gpd.GeoDataFrame({"cat": cats.values}, geometry=geoms.values, crs=CRS_METROS)
    g = g[g.cat.notna()]
    pares = gpd.sjoin(g, sectores[["sec_anm", "geometry"]], predicate="intersects")
    corte = shapely.intersection(pares.geometry.values,
                                 sectores.geometry.loc[pares.index_right].values)
    pares["valor"] = shapely.length(corte) if medida == "length" else shapely.area(corte)
    return pares.pivot_table(index="sec_anm", columns="cat", values="valor",
                             aggfunc="sum", fill_value=0)
 
# ---------------------------------------------------------------------------
# 3. Programa principal
# ---------------------------------------------------------------------------
def main(pbf, ruta_sectores, ruta_nbi=None):
    sect = gpd.read_file(ruta_sectores).to_crs(CRS_METROS)
    # Área de estudio PROPUESTA: sectores amanzanados de la parroquia urbana
    sect = sect[(sect.sec_anm.str[:6] == "090150") & (sect.sec_anm.str[6:9] != "999")]
    sect = sect.reset_index(drop=True)
    sect["area_km2"] = sect.area / 1e6
    print(f"Sectores en el área de estudio: {len(sect):,}")
 
    bbox = tuple(sect.to_crs(4326).total_bounds)       # recorte rápido al leer el .pbf
    out = sect[["sec_anm", "area_km2", "pob_t"]].set_index("sec_anm")
 
    # --- Puntos de interés: nodos + polígonos (edificios con amenity, etc.) ---
    claves_poi = ["amenity", "shop", "leisure", "tourism", "office", "healthcare", "highway"]
    pts = leer_capa(pbf, "points", bbox, claves_poi)
    pol = leer_capa(pbf, "multipolygons", bbox, claves_poi + ["landuse", "natural", "building"])
    pois = pd.concat([pts[claves_poi + ["geometry"]],
                      gpd.GeoDataFrame(pol[claves_poi], geometry=pol.representative_point(),
                                       crs=CRS_METROS)], ignore_index=True)
    pois["cat"] = clasificar(pois, CATEGORIAS_POI)
    pois = gpd.GeoDataFrame(pois[pois.cat.notna()], geometry="geometry", crs=CRS_METROS)
    print(f"POIs clasificados en la zona: {len(pois):,}")
    en_sector = gpd.sjoin(pois, sect[["sec_anm", "geometry"]], predicate="within")
    conteo = en_sector.pivot_table(index="sec_anm", columns="cat", values="index_right",
                                   aggfunc="size", fill_value=0)
    out = out.join(conteo.add_prefix("n_"))
 
    # --- Vías: km por tipo ---
    lin = leer_capa(pbf, "lines", bbox, ["highway"])
    tipo_via = pd.Series(np.nan, index=lin.index, dtype=object)
    for nombre, valores in CATEGORIAS_VIA.items():
        tipo_via[lin.highway.isin(valores)] = nombre
    km = medir_por_sector(lin.geometry, tipo_via, sect, "length") / 1000
    out = out.join(km.add_prefix("km_"))
 
    # --- Uso del suelo: proporción del área del sector ---
    suelo = medir_por_sector(pol.geometry.buffer(0), clasificar(pol, CATEGORIAS_SUELO),
                             sect, "area")
    out = out.join(suelo.add_prefix("m2_"))
 
    # --- Edificaciones: cantidad y área construida ---
    edif = pol[pol.building.notna()]
    cent = gpd.GeoDataFrame(geometry=edif.representative_point(), crs=CRS_METROS)
    cent["area_m2"] = edif.area.values
    e = gpd.sjoin(cent, sect[["sec_anm", "geometry"]], predicate="within") \
           .groupby("sec_anm").area_m2.agg(n_edificios="size", m2_construidos="sum")
    out = out.join(e)
 
    out = out.fillna(0)
 
    # --- Normalización ---
    for c in [c for c in out.columns if c.startswith("n_")]:
        out[c.replace("n_", "dens_", 1)] = out[c] / out.area_km2          # por km²
        out[c.replace("n_", "x1000hab_", 1)] = out[c] / out.pob_t.replace(0, np.nan) * 1000
    for c in [c for c in out.columns if c.startswith("km_")]:
        out[c + "_por_km2"] = out[c] / out.area_km2
    for c in [c for c in out.columns if c.startswith("m2_")]:
        out[c.replace("m2_", "pct_", 1)] = out[c] / (out.area_km2 * 1e6)
    out["area_media_edificio_m2"] = out.m2_construidos / out.n_edificios.replace(0, np.nan)
 
    out = out.reset_index().rename(columns={"sec_anm": "sector"})
    out.to_csv("osm_sectores.csv", index=False)
    print(f"osm_sectores.csv: {out.shape[0]:,} filas x {out.shape[1]} columnas")
    print(f"Sectores sin ningún POI: {(out.filter(like='n_').drop(columns='n_edificios', errors='ignore').sum(axis=1) == 0).sum():,}")
 
    if ruta_nbi:
        nbi = pd.read_csv(ruta_nbi, dtype={"sector": str})
        final = out.merge(nbi, on="sector", how="left", validate="1:1")
        print(f"Sectores sin datos NBI: {final.p_nbi.isna().sum()}")
        final.to_csv("tabla_final.csv", index=False)
        print(f"tabla_final.csv: {final.shape[0]:,} filas x {final.shape[1]} columnas")
 
if __name__ == "__main__":
    main(*sys.argv[1:4])
 
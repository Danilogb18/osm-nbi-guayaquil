"""
Paso 1: lista las capas y campos de sectores_anonimizados.gpkg.
Paso 2: recorta los sectores del cantón Guayaquil (código que empieza con 0901)
        y los guarda en un archivo pequeño.

Uso:
    python recortar_sectores.py sectores_anonimizados.gpkg
"""
import sys
import pyogrio
import geopandas as gpd

ruta = sys.argv[1]

# --- Paso 1: inventario ---
capas = pyogrio.list_layers(ruta)
for nombre, tipo in capas:
    info = pyogrio.read_info(ruta, layer=nombre)
    print(f"\nCAPA: {nombre} | {tipo} | {info['features']:,} elementos | CRS: {info['crs']}")
    print("  campos:", list(info["fields"]))
    muestra = pyogrio.read_dataframe(ruta, layer=nombre, max_features=3, read_geometry=False)
    print(muestra.to_string())

# --- Paso 2: recorte de Guayaquil ---
# Busca el campo que contiene el código de sector (texto de 12 caracteres)
capa = capas[0][0]
cab = pyogrio.read_dataframe(ruta, layer=capa, max_features=200, read_geometry=False)
campo = next(c for c in cab.columns
             if cab[c].astype(str).str.fullmatch(r"\d{12}").mean() > 0.9)
print(f"\nCampo de código de sector detectado: {campo}")

gdf = gpd.read_file(ruta, layer=capa, where=f"{campo} LIKE '0901%'")
print(f"Sectores del cantón Guayaquil: {len(gdf):,}")
gdf.to_file("sectores_guayaquil.gpkg", driver="GPKG")
print("Guardado: sectores_guayaquil.gpkg")
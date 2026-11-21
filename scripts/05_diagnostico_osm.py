"""
Diagnóstico de cobertura de OSM por sector censal (Guayaquil).

Uso:
    python3 diagnostico_osm.py tabla_final.csv

Responde tres preguntas antes de decidir la escala de análisis:
  1. ¿Cuántos sectores tienen POIs, y de qué categorías?
  2. ¿Las otras capas (vías, edificaciones, uso del suelo) cubren mejor?
  3. ¿La falta de datos se concentra en los sectores más pobres?
     (si sí, hay que separar escasez real de falta de mapeo)
  4. ¿Cómo quedaría la cobertura si se agrega a zona censal?
"""
import sys
import pandas as pd

ruta = sys.argv[1] if len(sys.argv) > 1 else "tabla_final.csv"
df = pd.read_csv(ruta, dtype={"sector": str})
df = df[df.p_nbi_personas.notna()].copy()      # quita los 2 sectores sin hogares
print(f"Sectores con NBI: {len(df):,}\n")

# ---------------------------------------------------------------------------
# 1. Puntos de interés
#    Las columnas de conteo empiezan con "n_", pero n_edificios (OSM) y
#    n_hogares / n_personas (NBI) no son POIs.
# ---------------------------------------------------------------------------
no_poi = {"n_edificios", "n_hogares", "n_personas"}
cols_poi = [c for c in df.columns if c.startswith("n_") and c not in no_poi]
df["poi_total"] = df[cols_poi].sum(axis=1)

print("== 1. Puntos de interés ==")
print(f"Sectores con 0 POIs: {(df.poi_total == 0).mean():.1%}")
print("POIs por sector (percentiles):")
print(df.poi_total.quantile([.25, .5, .75, .9, .99]).round(1).to_string())

cob = pd.DataFrame({
    "total": df[cols_poi].sum().astype(int),
    "% sectores con >0": (df[cols_poi] > 0).mean().mul(100).round(1),
})
print("\nPor categoría:")
print(cob.sort_values("total", ascending=False).to_string())

# ---------------------------------------------------------------------------
# 2. Otras capas
# ---------------------------------------------------------------------------
cols_km = [c for c in df.columns if c.startswith("km_") and not c.endswith("_por_km2")]
cols_suelo = [c for c in df.columns if c.startswith("m2_suelo")]
df["km_total"] = df[cols_km].sum(axis=1)
df["pct_construido"] = df.m2_construidos / (df.area_km2 * 1e6)

print("\n== 2. Otras capas ==")
print(f"Sectores con alguna vía:            {(df.km_total > 0).mean():.1%}")
print(f"Sectores con edificios mapeados:    {(df.n_edificios > 0).mean():.1%}")
print(f"Sectores con algún uso de suelo:    {(df[cols_suelo].sum(axis=1) > 0).mean():.1%}")
print(f"Mediana de área construida mapeada: {df.pct_construido.median():.1%} del sector")

# ---------------------------------------------------------------------------
# 3. ¿La falta de datos se relaciona con la pobreza?
#    Quintiles de % de personas pobres. Se usa el rango para que los muchos
#    sectores con 0 % no generen cortes duplicados.
# ---------------------------------------------------------------------------
etiquetas = ["Q1 menos pobre", "Q2", "Q3", "Q4", "Q5 más pobre"]
df["quintil_nbi"] = pd.qcut(df.p_nbi_personas.rank(method="first"), 5, labels=etiquetas)

tab = df.groupby("quintil_nbi", observed=True).agg(
    nbi_medio=("p_nbi_personas", "mean"),
    sin_poi=("poi_total", lambda s: (s == 0).mean()),
    poi_mediana=("poi_total", "median"),
    con_edificios=("n_edificios", lambda s: (s > 0).mean()),
    construido_med=("pct_construido", "median"),
)
print("\n== 3. Cobertura según pobreza (proporciones) ==")
print(tab.round(3).to_string())

dens_poi = df.poi_total / df.area_km2
print(f"\nSpearman densidad de POIs  vs % pobres: "
      f"{dens_poi.corr(df.p_nbi_personas, method='spearman'):+.2f}")
print(f"Spearman % área construida vs % pobres: "
      f"{df.pct_construido.corr(df.p_nbi_personas, method='spearman'):+.2f}")

# ---------------------------------------------------------------------------
# 4. Agregación a zona censal (primeros 9 dígitos del código)
# ---------------------------------------------------------------------------
df["zona"] = df.sector.str[:9]
z = df.groupby("zona").agg(n_sectores=("sector", "size"),
                           poi_total=("poi_total", "sum"),
                           n_edificios=("n_edificios", "sum"))
print("\n== 4. Si se agrega a zona censal ==")
print(f"Zonas: {len(z):,} | mediana de sectores por zona: {z.n_sectores.median():.0f}")
print(f"Zonas con 0 POIs: {(z.poi_total == 0).mean():.1%}")
print("POIs por zona (percentiles):")
print(z.poi_total.quantile([.25, .5, .75]).round(1).to_string())
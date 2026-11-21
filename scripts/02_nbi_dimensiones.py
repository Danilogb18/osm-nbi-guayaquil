"""
Reconstruye las 5 dimensiones del NBI (Censo 2022, base nivel sector) por hogar
y las agrega por sector censal.

Uso:
    python nbi_dimensiones.py gye_vivienda.csv gye_hogar.csv gye_poblacion.csv

Salidas:
    nbi_hogares.csv  -> una fila por hogar con las 5 dimensiones (0/1) y el NBI
    nbi_sectores.csv -> una fila por sector con proporciones por dimensión

Umbrales: INEC (2025), "¿Cómo se mide la pobreza en Ecuador a partir de los
censos? El método NBI explicado", Cuadro 1, y sintaxis REDATAM NBI 2010 del INEC.
Validado contra la variable NBI oficial: 949/949 hogares coinciden en la muestra.
"""
import sys
import numpy as np
import pandas as pd

ruta_viv, ruta_hog, ruta_per = sys.argv[1:4]

def num(s):
    return pd.to_numeric(s, errors="coerce")

# --- 1. Cargar solo las columnas necesarias (todo como texto para no perder ceros) ---
viv = pd.read_csv(ruta_viv, dtype=str,
                  usecols=["ID_VIV", "V05", "V07", "V09", "V10", "V11"])
hog = pd.read_csv(ruta_hog, dtype=str,
                  usecols=["I01", "I02", "I03", "I04", "I05", "ID_VIV", "ID_HOG",
                           "H01", "H1303", "HAC", "NBI"])
per = pd.read_csv(ruta_per, dtype=str,
                  usecols=["ID_HOG", "P01", "P03", "P15", "P22", "ESCOLA"])

# Universo del NBI: hogares en viviendas particulares ocupadas (NBI no vacío)
hog = hog[hog.NBI.notna()].copy()

for c in ["V05", "V07", "V09", "V10", "V11"]:
    viv[c] = num(viv[c])
for c in ["P01", "P03", "P15", "P22", "ESCOLA"]:
    per[c] = num(per[c])
hog = hog.merge(viv, on="ID_VIV", how="left")

# --- 2. Las cinco dimensiones (1 = hogar con carencia) ---

# D1 Características físicas: piso de tierra u otro (V07 7,8)
#    o paredes de caña no revestida u otro (V05 7,8)
hog["d_vivienda"] = (hog.V07.isin([7, 8]) | hog.V05.isin([7, 8])).astype(int)

# D2 Servicios básicos: excretas inadecuadas (V11 4-7: pozo ciego, descarga directa,
#    letrina, no tiene) o agua de pozo/tanquero/otras (V10 3-5)
#    o agua que no llega por tubería dentro de la vivienda (V09 2-4)
hog["d_servicios"] = (hog.V11.isin([4, 5, 6, 7])
                      | hog.V10.isin([3, 4, 5])
                      | hog.V09.isin([2, 3, 4])).astype(int)

# D3 Hacinamiento: más de 3 personas por dormitorio (0 dormitorios cuenta como 1)
tot = num(hog.H1303)
hog["d_hacin"] = (tot / num(hog.H01).clip(lower=1) > 3).astype(int)

# D4 Niños de 6 a 12 años que no asisten a educación regular (P15 = 2)
con_ninos = per.loc[per.P03.between(6, 12) & (per.P15 == 2), "ID_HOG"].unique()
hog["d_ninos"] = hog.ID_HOG.isin(con_ninos).astype(int)

# D5 Dependencia económica: jefe con 3 o menos años de escolaridad
#    Y (más de 3 personas por ocupado, o ningún ocupado).
#    Ocupado = de 10 años o más que trabajó de alguna forma la semana pasada (P22 1-6).
#    Nota: CONDACT1 no sirve aquí; excluye a quien hizo labores agrícolas para
#    autoconsumo, pero el NBI oficial sí los cuenta como ocupados.
ocupados = per[per.P22.between(1, 6) & (per.P03 >= 10)].groupby("ID_HOG").size()
esc_jefe = per[per.P01 == 1].drop_duplicates("ID_HOG").set_index("ID_HOG").ESCOLA
n_ocu = hog.ID_HOG.map(ocupados).fillna(0)
razon_alta = (n_ocu == 0) | (tot / n_ocu.replace(0, np.nan) > 3)
hog["d_depend"] = ((hog.ID_HOG.map(esc_jefe) <= 3) & razon_alta).astype(int)

DIMS = ["d_vivienda", "d_servicios", "d_hacin", "d_ninos", "d_depend"]
hog["n_carencias"] = hog[DIMS].sum(axis=1)
hog["pobre_rec"] = (hog.n_carencias >= 1).astype(int)
hog["pobre_oficial"] = (hog.NBI == "1").astype(int)

# --- 3. Validación contra el NBI oficial ---
coinc = (hog.pobre_rec == hog.pobre_oficial).mean()
print(f"Hogares: {len(hog):,} | coincidencia con NBI oficial: {coinc:.4%}")
print(pd.crosstab(hog.pobre_oficial, hog.pobre_rec,
                  rownames=["oficial"], colnames=["reconstruido"]))
print(f"Hacinamiento vs HAC oficial: {((hog.d_hacin == 1) == (hog.HAC == '1')).mean():.4%}")

# --- 4. Agregación por sector ---
enmasc = (hog.I04 == "888") | (hog.I05 == "888")
print(f"Hogares con zona/sector enmascarado (excluidos): {enmasc.sum():,}")
hog = hog[~enmasc].copy()
hog["sector"] = hog.I01 + hog.I02 + hog.I03 + hog.I04 + hog.I05
hog["personas"] = tot.loc[hog.index]

hog.to_csv("nbi_hogares.csv", index=False)

agg = {"n_hogares": ("ID_HOG", "size"),
       "n_personas": ("personas", "sum"),
       "p_nbi": ("pobre_oficial", "mean"),
       "prom_carencias": ("n_carencias", "mean")}
agg.update({f"p_{d[2:]}": (d, "mean") for d in DIMS})
sect = hog.groupby("sector").agg(**agg).reset_index()

# % de personas pobres (así reporta el INEC), ponderando por tamaño del hogar
w = hog.assign(pp=hog.personas * hog.pobre_oficial).groupby("sector")[["pp", "personas"]].sum()
sect["p_nbi_personas"] = sect.sector.map(w.pp / w.personas)

sect.to_csv("nbi_sectores.csv", index=False)
print(f"Sectores: {len(sect):,} -> nbi_sectores.csv")
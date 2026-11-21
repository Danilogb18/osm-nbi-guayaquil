import pandas as pd

archivos = {
    "vivienda": "CPV_2022_Vivienda_Sector.csv",
    "hogar": "CPV_2022_Hogar_Sector.csv",
    "poblacion": "CPV_2022_Poblacion_Sector.csv",   # ajusta el nombre real
}

for nombre, ruta in archivos.items():
    # Detectar el separador (puede ser coma o punto y coma)
    with open(ruta, encoding="utf-8", errors="replace") as f:
        sep = ";" if f.readline().count(";") > 0 else ","

    partes = []
    for chunk in pd.read_csv(ruta, sep=sep, dtype=str, chunksize=500_000,
                             encoding="utf-8", encoding_errors="replace"):
        partes.append(chunk[(chunk.I01 == "09") & (chunk.I02 == "01")])
    gye = pd.concat(partes)

    gye.head(3000).to_csv(f"muestra_{nombre}.csv", index=False)   # para adjuntarme
    gye.to_csv(f"gye_{nombre}.csv", index=False)                   # Guayaquil completo, guárdalo
    print(nombre, gye.shape)
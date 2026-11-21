# Reconstrucción de las 5 dimensiones del NBI (Censo 2022, nivel sector)

Implementada en `scripts/02_nbi_dimensiones.py`.
Validación con todo el cantón Guayaquil: los 810.592 hogares coinciden con la variable `NBI` oficial (620.127 no pobres y 190.465 pobres, sin desacuerdos), y el hacinamiento coincide al 100 % con la variable oficial `HAC`.
El porcentaje de personas pobres del cantón resultante es 28,7 %, igual al informe oficial del INEC.

Fuentes de los umbrales: INEC (2025), "El método NBI explicado", Cuadro 1; sintaxis REDATAM del NBI 2010 del INEC.

| Dimensión | El hogar tiene la carencia si... | Tabla |
|---|---|---|
| Características físicas de la vivienda | piso de tierra u otro (`V07` ∈ {7, 8}) o paredes de caña no revestida u otro (`V05` ∈ {7, 8}) | Vivienda |
| Servicios básicos | `V11` ∈ {4, 5, 6, 7} o `V10` ∈ {3, 4, 5} o `V09` ∈ {2, 3, 4} | Vivienda |
| Hacinamiento crítico | `H1303 / max(H01, 1) > 3` (igual a `HAC` oficial) | Hogar |
| Niños de 6 a 12 años sin escuela | algún miembro con `P03` entre 6 y 12 y `P15 = 2` | Población |
| Alta dependencia económica | escolaridad del jefe (`P01 = 1`) `ESCOLA ≤ 3` **y** (ocupados = 0 o `H1303` / ocupados > 3); ocupado = `P22` entre 1 y 6 y `P03 ≥ 10` | Población |

Un hogar es pobre por NBI si tiene al menos una carencia.
Universo: hogares con `NBI` no vacío (viviendas particulares ocupadas).

Detalles importantes:

- No usar `CONDACT1` para contar ocupados: excluye las labores agrícolas de autoconsumo y rompe la coincidencia con el NBI oficial.
- Uniones: vivienda ↔ hogar por `ID_VIV`; hogar ↔ población por `ID_HOG`.
- Código de sector = `I01 + I02 + I03 + I04 + I05` (12 dígitos). Se excluyen los 60 hogares con zona o sector enmascarado (`888`).
- Agregación por sector: % de hogares con cada carencia ponderado por hogares; % de personas pobres ponderado por el tamaño del hogar, como reporta el INEC.

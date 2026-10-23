# Diferencial de suriaX 0.4.1: esquema 1 frente a 2 del HIR, y compilador V0 frente a V1

> Generado por `dev/diff/run_diff.py`; no editar a mano. Cómo replicarlo: [README.md](README.md). Datos crudos: [results.json](results.json).

Hay DOS comparaciones distintas, y no hay que confundirlas:

1. **Esquema 1 frente a esquema 2 del HIR** (la principal). El mismo compilador (la V0) emite el `.phir` con `--hir-schema 1` (el esquema inicial: cada tipo escrito inline en su nodo) y con `--hir-schema 2` (el de hoy: un pool de tipos, `Module.types`, y los nodos con un índice). Los tres targets leen y ejecutan los dos. Ver [schema/README.md](schema/README.md).
2. **Compilador V0 frente a compilador V1** (apartado aparte). La V0 (Python) y la V1 (escrita en suriaX, corriendo en la VM) compilan el mismo programa, las dos al esquema 2, y se compara su `.phir` byte a byte y su ejecución.

Cada celda es **OK** (misma salida, tras normalizar el fin de línea, y mismo código que la referencia), **NOT SUPPORTED** (un compilador o un target RECHAZA de forma explícita algo que aún no soporta, con su código: `WEBxxx`, `VMxxx`, o la V1 con un error de sintaxis que no conoce) o **ERROR** (una divergencia de verdad al ejecutar: un trap, otra salida, otro código, o una salida que no es la que exige la semántica documentada). La **referencia** es el intérprete ejecutando el HIR del esquema 2 emitido por la V0.

## Resumen

### Recuento de celdas (HIR × target)

| HIR | OK | NOT SUPPORTED | ERROR | Emisión: OK / NOT SUPPORTED / ERROR |
|---|---|---|---|---|
| esquema 1 (compilador V0, `--hir-schema 1`) | 29 | 2 | 2 | 11 / 0 / 0 |
| esquema 2 (compilador V0, `--hir-schema 2`) | 29 | 2 | 2 | 11 / 0 / 0 |
| compilador V1 (esquema 2) | 27 | 4 | 2 | 10 / 1 / 0 |
| **Total** | **85** | **8** | **6** | |

11 programas × 3 targets por HIR. Cuando un compilador no emite (NOT SUPPORTED), sus tres celdas cuentan con el mismo estado.

### Esquema 2 frente a esquema 1 (compilador V0)

Cambio al pasar del esquema 1 al 2. Tamaño: negativo = el 2 ocupa menos. Tiempos: mediana del 1 → mediana del 2, el cambio relativo y los RIC de cada uno. **Criterio de ruido** (simple, no es una prueba estadística): si los rangos intercuartílicos [Q1, Q3] de los dos se solapan, la diferencia se marca "dentro del ruido".

| Programa | `.phir` del programa (1 → 2) | Todas las unidades (1 → 2) | Emisión |
|---|---|---|---|
| `01_hola.srcx` | 288 → 293 B (+1.7 %) | 1618 → 1582 B (-2.2 %) | 266 → 264 ms (-0.9 %; RIC 15.3 / 6.7) dentro del ruido |
| `02_aritmetica.srcx` | 4102 → 3797 B (-7.4 %) | 5432 → 5086 B (-6.4 %) | 278 → 275 ms (-0.9 %; RIC 6.8 / 20.7) dentro del ruido |
| `03_control.srcx` | 2655 → 2461 B (-7.3 %) | 3985 → 3750 B (-5.9 %) | 273 → 272 ms (-0.1 %; RIC 9.8 / 9.8) dentro del ruido |
| `04_vector.srcx` | 2207 → 1959 B (-11.2 %) | 28693 → 24553 B (-14.4 %) | 353 → 322 ms (-8.8 %; RIC 8.3 / 13.8) **mejor** |
| `05_funciones.srcx` | 3002 → 2788 B (-7.1 %) | 4332 → 4077 B (-5.9 %) | 279 → 272 ms (-2.5 %; RIC 10.9 / 7.5) dentro del ruido |
| `06_sintetico_10.srcx` | 3566 → 3289 B (-7.8 %) | 4896 → 4578 B (-6.5 %) | 280 → 276 ms (-1.5 %; RIC 9.8 / 5.9) dentro del ruido |
| `06_sintetico_1000.srcx` | 124002 → 110892 B (-10.6 %) | 125332 → 112181 B (-10.5 %) | 602 → 426 ms (-29.1 %; RIC 19.2 / 11.4) **mejor** |
| `06_sintetico_10000.srcx` | 1176402 → 1054049 B (-10.4 %) | 1177732 → 1055338 B (-10.4 %) | 3999 → 1933 ms (-51.7 %; RIC 37.1 / 36.3) **mejor** |
| `07_division_cero.srcx` | 565 → 553 B (-2.1 %) | 1895 → 1842 B (-2.8 %) | 270 → 267 ms (-0.8 %; RIC 10.7 / 15.6) dentro del ruido |
| `08_desbordamiento.srcx` | 2433 → 2264 B (-6.9 %) | 3763 → 3553 B (-5.6 %) | 276 → 274 ms (-0.7 %; RIC 14.8 / 6.5) dentro del ruido |
| `09_structs.srcx` | 1474 → 1366 B (-7.3 %) | 2804 → 2655 B (-5.3 %) | 273 → 270 ms (-1.1 %; RIC 12.4 / 9.1) dentro del ruido |

Tamaño (medido, es exacto, sin ruido): el `.phir` del programa ocupa con el esquema 2 entre el 89 % y el 102 % del esquema 1 (mediana 93 %); contando todas las unidades, entre el 86 % y el 98 % (mediana 94 %).

**Lectura** (ms), esquema 1 → 2:

| Programa | intérprete (Python) | VM (C++) | web (WebAssembly) |
|---|---|---|---|
| `01_hola.srcx` | 63.9 → 64.1 ms (+0.4 %; RIC 3.0 / 3.7) dentro del ruido | 7.6 → 7.6 ms (-0.4 %; RIC 0.5 / 0.2) dentro del ruido | 120 → 119 ms (-0.8 %; RIC 6.5 / 5.5) dentro del ruido |
| `02_aritmetica.srcx` | 68.8 → 67.3 ms (-2.2 %; RIC 2.6 / 2.0) **mejor** | 7.7 → 7.7 ms (+0.3 %; RIC 0.4 / 0.5) dentro del ruido | 119 → 119 ms (-0.7 %; RIC 7.5 / 4.1) dentro del ruido |
| `03_control.srcx` | 67.4 → 67.4 ms (-0.1 %; RIC 2.8 / 3.2) dentro del ruido | 7.8 → 7.7 ms (-1.6 %; RIC 0.6 / 0.5) dentro del ruido | 116 → 122 ms (+5.1 %; RIC 6.8 / 10.2) dentro del ruido |
| `04_vector.srcx` | 90.6 → 80.4 ms (-11.2 %; RIC 4.5 / 3.5) **mejor** | 8.9 → 8.1 ms (-9.1 %; RIC 0.4 / 0.5) **mejor** | 119 → 119 ms (+0.3 %; RIC 8.3 / 8.9) dentro del ruido — rechazado |
| `05_funciones.srcx` | 66.7 → 66.9 ms (+0.4 %; RIC 5.1 / 3.8) dentro del ruido | 7.4 → 7.5 ms (+1.9 %; RIC 0.6 / 0.8) dentro del ruido | 119 → 119 ms (-0.4 %; RIC 3.5 / 8.6) dentro del ruido |
| `06_sintetico_10.srcx` | 68.4 → 65.6 ms (-4.1 %; RIC 4.2 / 3.3) dentro del ruido | 7.5 → 7.2 ms (-3.3 %; RIC 0.5 / 0.5) dentro del ruido | 120 → 118 ms (-2.1 %; RIC 7.1 / 4.3) dentro del ruido |
| `06_sintetico_1000.srcx` | 200 → 145 ms (-27.2 %; RIC 7.1 / 5.4) **mejor** | 11.6 → 10.7 ms (-8.4 %; RIC 0.6 / 0.5) **mejor** | 125 → 121 ms (-3.3 %; RIC 6.7 / 6.2) dentro del ruido |
| `06_sintetico_10000.srcx` | 1585 → 988 ms (-37.7 %; RIC 13.2 / 19.9) **mejor** | 49.2 → 34.9 ms (-29.0 %; RIC 3.0 / 1.5) **mejor** | 174 → 152 ms (-12.9 %; RIC 7.4 / 7.6) **mejor** |
| `07_division_cero.srcx` | 67.2 → 64.7 ms (-3.7 %; RIC 4.1 / 4.6) dentro del ruido | 7.4 → 7.5 ms (+1.0 %; RIC 0.6 / 0.4) dentro del ruido | 121 → 117 ms (-2.8 %; RIC 7.3 / 7.4) dentro del ruido |
| `08_desbordamiento.srcx` | 67.7 → 68.5 ms (+1.1 %; RIC 4.8 / 7.3) dentro del ruido | 7.5 → 8.0 ms (+6.3 %; RIC 0.6 / 0.9) dentro del ruido | 121 → 117 ms (-3.0 %; RIC 16.3 / 2.5) dentro del ruido |
| `09_structs.srcx` | 65.9 → 64.5 ms (-2.2 %; RIC 3.9 / 4.1) dentro del ruido | 7.6 → 7.4 ms (-2.6 %; RIC 0.6 / 0.5) dentro del ruido | 119 → 118 ms (-0.2 %; RIC 10.5 / 3.9) dentro del ruido — rechazado |

**Ejecución** (ms), esquema 1 → 2:

| Programa | intérprete (Python) | VM (C++) | web (WebAssembly) |
|---|---|---|---|
| `01_hola.srcx` | 116 → 118 ms (+1.8 %; RIC 6.4 / 6.4) dentro del ruido | 7.9 → 8.0 ms (+2.1 %; RIC 0.5 / 0.6) dentro del ruido | 150 → 148 ms (-1.0 %; RIC 7.0 / 4.1) dentro del ruido |
| `02_aritmetica.srcx` | 122 → 120 ms (-1.1 %; RIC 5.5 / 7.6) dentro del ruido | 8.1 → 8.1 ms (-0.3 %; RIC 0.3 / 0.4) dentro del ruido | 152 → 153 ms (+0.6 %; RIC 8.5 / 6.3) dentro del ruido |
| `03_control.srcx` | 120 → 120 ms (-0.3 %; RIC 6.7 / 3.8) dentro del ruido | 8.1 → 8.2 ms (+1.2 %; RIC 0.4 / 0.4) dentro del ruido | 149 → 154 ms (+3.2 %; RIC 7.9 / 6.4) dentro del ruido |
| `04_vector.srcx` | 147 → 135 ms (-8.2 %; RIC 7.0 / 3.8) **mejor** | 10.1 → 9.0 ms (-10.7 %; RIC 0.7 / 0.7) **mejor** | 151 → 151 ms (+0.3 %; RIC 7.5 / 11.6) dentro del ruido — rechazado |
| `05_funciones.srcx` | 693 → 698 ms (+0.7 %; RIC 13.9 / 9.4) dentro del ruido | 11.1 → 11.4 ms (+2.4 %; RIC 0.7 / 0.4) dentro del ruido | 152 → 153 ms (+0.3 %; RIC 8.8 / 6.9) dentro del ruido |
| `06_sintetico_10.srcx` | 124 → 122 ms (-1.8 %; RIC 6.4 / 6.3) dentro del ruido | 8.4 → 7.5 ms (-10.5 %; RIC 0.5 / 0.5) **mejor** | 153 → 152 ms (-0.5 %; RIC 6.3 / 8.1) dentro del ruido |
| `06_sintetico_1000.srcx` | 283 → 225 ms (-20.3 %; RIC 14.9 / 7.2) **mejor** | 13.8 → 13.5 ms (-1.7 %; RIC 0.4 / 0.8) dentro del ruido | 197 → 192 ms (-2.3 %; RIC 10.0 / 8.1) dentro del ruido |
| `06_sintetico_10000.srcx` | 1927 → 1327 ms (-31.1 %; RIC 28.6 / 13.9) **mejor** | 85.2 → 68.5 ms (-19.5 %; RIC 5.1 / 2.9) **mejor** | 449 → 400 ms (-10.9 %; RIC 28.2 / 13.6) **mejor** |
| `07_division_cero.srcx` | 121 → 118 ms (-2.1 %; RIC 4.9 / 4.7) dentro del ruido | 7.8 → 7.8 ms (-0.2 %; RIC 0.4 / 0.6) dentro del ruido | 150 → 149 ms (-0.5 %; RIC 6.6 / 7.3) dentro del ruido |
| `08_desbordamiento.srcx` | 125 → 123 ms (-1.2 %; RIC 6.0 / 7.9) dentro del ruido | 7.8 → 8.4 ms (+7.3 %; RIC 0.3 / 0.7) **peor** | 155 → 154 ms (-1.1 %; RIC 9.7 / 6.8) dentro del ruido |
| `09_structs.srcx` | 121 → 118 ms (-3.0 %; RIC 6.1 / 8.2) dentro del ruido | 8.5 → 8.0 ms (-5.3 %; RIC 0.6 / 0.6) dentro del ruido | 146 → 146 ms (-0.2 %; RIC 12.9 / 5.2) dentro del ruido — rechazado |

**En cuántos programas el esquema 2 es mejor, peor o no se distingue** (las celdas rechazadas no cuentan):

| Medida | mejor | peor | dentro del ruido |
|---|---|---|---|
| emisión | 3 | 0 | 8 |
| lectura interp | 4 | 0 | 7 |
| lectura vm | 3 | 0 | 8 |
| lectura web | 1 | 0 | 8 |
| ejecución interp | 3 | 0 | 8 |
| ejecución vm | 3 | 1 | 7 |
| ejecución web | 1 | 0 | 8 |

### Pruebas estadísticas: esquema 1 frente a esquema 2

El criterio de ruido de arriba describe; estas pruebas contrastan. Salen de los mismos datos, sin volver a medir; son bilaterales y con α = 0.05.

**Tamaño del `.phir` del programa**: Wilcoxon de rangos con signo, pareada por programa (el mismo programa con los dos esquemas). El tamaño es exacto, así que aquí no hay ruido que separar: la prueba dice si el cambio va en la misma dirección en los programas más de lo que daría el azar.

- 11 programas: el esquema 2 es más pequeño en 10, más grande en 1 e igual en 0 (los iguales no entran en la prueba).
- W+ = 1, W− = 65, n = 11; p = 0.002 (exacta); correlación biserial de rangos -0.97 (−1: todas las diferencias a favor del esquema 2).
- Con α = 0.05 se rechaza la hipótesis nula (las diferencias se reparten simétricas alrededor de 0).

**Lectura** (cargar, decodificar y ligar): U de Mann-Whitney por celda (programa × target), las corridas del esquema 1 contra las del 2. Los p-valores van corregidos con Holm sobre todas las celdas comparadas (las rechazadas no cuentan, como arriba). **P(2 < 1)** es la probabilidad de que una corrida del esquema 2 tarde menos que una del 1: 0.5 es que no hay diferencia; 1, que siempre es más rápido. En negrita, lo significativo.

| Programa | intérprete (Python) | VM (C++) | web (WebAssembly) |
|---|---|---|---|
| `01_hola.srcx` | p 1.000 · P(2 < 1) 0.45 | p 1.000 · P(2 < 1) 0.52 | p 1.000 · P(2 < 1) 0.48 |
| `02_aritmetica.srcx` | **p 0.004** · P(2 < 1) 0.79 | p 1.000 · P(2 < 1) 0.53 | p 1.000 · P(2 < 1) 0.58 |
| `03_control.srcx` | p 1.000 · P(2 < 1) 0.53 | p 1.000 · P(2 < 1) 0.55 | p 0.167 · P(2 < 1) 0.30 |
| `04_vector.srcx` | **p < 0.001** · P(2 < 1) 0.94 | **p < 0.001** · P(2 < 1) 0.92 | — |
| `05_funciones.srcx` | p 1.000 · P(2 < 1) 0.53 | p 1.000 · P(2 < 1) 0.48 | p 1.000 · P(2 < 1) 0.51 |
| `06_sintetico_10.srcx` | **p < 0.001** · P(2 < 1) 0.81 | p 0.753 · P(2 < 1) 0.65 | p 0.408 · P(2 < 1) 0.67 |
| `06_sintetico_1000.srcx` | **p < 0.001** · P(2 < 1) 1.00 | **p < 0.001** · P(2 < 1) 0.90 | p 0.102 · P(2 < 1) 0.71 |
| `06_sintetico_10000.srcx` | **p < 0.001** · P(2 < 1) 1.00 | **p < 0.001** · P(2 < 1) 1.00 | **p < 0.001** · P(2 < 1) 1.00 |
| `07_division_cero.srcx` | p 0.118 · P(2 < 1) 0.71 | p 1.000 · P(2 < 1) 0.45 | p 0.141 · P(2 < 1) 0.70 |
| `08_desbordamiento.srcx` | p 1.000 · P(2 < 1) 0.48 | **p 0.015** · P(2 < 1) 0.24 | **p 0.026** · P(2 < 1) 0.75 |
| `09_structs.srcx` | p 1.000 · P(2 < 1) 0.57 | p 0.244 · P(2 < 1) 0.69 | — |

Con α = 0.05 tras Holm, el esquema 2 lee más rápido en 10 de 31 celdas, más lento en 1 y sin diferencia significativa en 20.

**Límites de estas pruebas** (se leen con ellas):

- Los programas se eligieron a mano, por cobertura del lenguaje, no al azar: la Wilcoxon habla de ESTOS programas, no de cualquier programa de suriaX.
- Mann-Whitney supone corridas independientes. Aquí son consecutivas, en una sola máquina, y todas las del esquema 1 de un programa se hacen ANTES que las del 2 (el orden no se alterna): una deriva de la máquina (temperatura, caché, otro proceso) puede pasar por efecto del esquema. Los p-valores son, por eso, optimistas.
- Los tiempos incluyen arrancar el proceso (ver los arranques en "Cómo se mide"): en los programas pequeños el arranque domina y la diferencia del esquema queda diluida.

## Entorno

| | |
|---|---|
| Versión de suriaX (`version.py`) | 0.4.1 |
| Fecha | 2026-10-18T03:15:50-05:00 |
| SO | Windows-11-10.0.26300-SP0 |
| CPU | AMD Ryzen 7 7445HS w/ Radeon 740M Graphics (12 núcleos lógicos) |
| Carga de la CPU | antes: 13 % de uso de CPU (Win32_Processor.LoadPercentage); después: 9 % de uso de CPU (Win32_Processor.LoadPercentage) |
| Python | Python 3.14.7 |
| node | node v24.21.0 |
| pyyaml (lo usa la V0 para leer `.suriaX_config.yaml`) | 6.0.3 |
| Compilador C++ (VM) | MSVC 19.51.36257.0 (build Release, Ninja) |
| VM | build/bin/suriax-hir.exe (sha256 be81957b92ab3086…) |
| Commit | `94aebd4f4cfbe56d49a05276c2eabb5ba6519b30` + **194 archivos con cambios sin commit** (sha256 de `git diff HEAD`: ad50f3b82a0bc681…) |
| Reloj | `time.perf_counter_ns` — namespace(implementation='QueryPerformanceCounter()', monotonic=True, adjustable=False, resolution=1e-07) |
| Repeticiones | 30 por medida, la 1.ª descartada (calentamiento); presupuesto por celda 1200 s |
| Duración de la corrida | 28.2 min |

## Cómo se mide

- Tiempos en **milisegundos de pared** por corrida, medidos por el arnés alrededor del proceso hijo: **mediana** [mínimo–máximo] y RIC (Q3 − Q1) de las corridas que quedan tras descartar la primera.
- **Emisión**: esquema 1: `python V0/main.py prog.srcx --emit-hir s1/prog.srcx.phir --hir-schema 1`; esquema 2: lo mismo con `s2/` y `--hir-schema 2`; compilador V1: `suriax-hir work/v1/dumps/main.srcx.phir --run --quiet --pasos 0 -- prog.srcx v1/prog.srcx.phir --stdlib <repo>/lib`. Los tres emiten el `.phir` del programa Y el de cada librería en su carpeta, y cada HIR se ejecuta con SUS unidades.
- **Lectura** (cargar, decodificar y ligar, sin ejecutar): intérprete `python dev/diff/read_interp.py x.phir`; VM `suriax-hir x.phir --link`; web `node dev/diff/read_web.ts x.phir`. Con el esquema 1, la lectura incluye normalizarlo al pool de tipos.
- **Ejecución**: intérprete `python runtime/interpreter/main.py x.phir --exec`; VM `suriax-hir x.phir --run --quiet` (incluye leer, resolver, bajar a MIR y verificar); web `node web/main.ts x.phir --run` (incluye leer, contener, DCE, generar el WebAssembly y ejecutarlo).
- **Tamaño**: el `.phir` del programa / la suma de todas las unidades.

Lo que cuesta solo ARRANCAR cada proceso (incluido en todos los tiempos):

| Proceso | Comando | Tiempo (ms) |
|---|---|---|
| Python | `python -c pass` | **50.7** [44.8–89.5] RIC 7.7 |
| node | `node -e 0` | **40.4** [38.0–45.2] RIC 1.9 |
| VM | `suriax-hir.exe --help` | **7.2** [6.6–8.2] RIC 0.7 |

## 1. Esquema 1 frente a esquema 2: detalle por programa

### `01_hola.srcx`

| | Esquema 1 | Esquema 2 |
|---|---|---|
| Emisión (ms) | **266** [245–335] RIC 15.3 | **264** [255–288] RIC 6.7 |
| Tamaño `.phir` (programa / todas) | 288 / 1618 B (4 unidades) | 293 / 1582 B (4 unidades) |

| HIR | Target | Lectura (ms) | Ejecución (ms) | Estado | Código |
|---|---|---|---|---|---|
| esquema 1 | intérprete (Python) | **63.9** [59.5–70.8] RIC 3.0 | **116** [109–153] RIC 6.4 | OK | 0 |
| esquema 1 | VM (C++) | **7.6** [6.9–10.7] RIC 0.5 | **7.9** [7.1–9.0] RIC 0.5 | OK | 0 |
| esquema 1 | web (WebAssembly) | **120** [111–132] RIC 6.5 | **150** [139–197] RIC 7.0 | OK (formato: `\n` en vez de `\r\n`; marca `[wasm] main() -> N` en stderr) | 0 |
| esquema 2 | intérprete (Python) | **64.1** [60.2–69.8] RIC 3.7 | **118** [112–139] RIC 6.4 | OK | 0 |
| esquema 2 | VM (C++) | **7.6** [6.9–8.8] RIC 0.2 | **8.0** [7.3–10.9] RIC 0.6 | OK | 0 |
| esquema 2 | web (WebAssembly) | **119** [108–173] RIC 5.5 | **148** [138–160] RIC 4.1 | OK (formato: `\n` en vez de `\r\n`; marca `[wasm] main() -> N` en stderr) | 0 |

<details><summary>Salida de referencia (intérprete, esquema 2)</summary>

```text
hola mundo
```

</details>

### `02_aritmetica.srcx`

| | Esquema 1 | Esquema 2 |
|---|---|---|
| Emisión (ms) | **278** [263–327] RIC 6.8 | **275** [254–330] RIC 20.7 |
| Tamaño `.phir` (programa / todas) | 4102 / 5432 B (4 unidades) | 3797 / 5086 B (4 unidades) |

| HIR | Target | Lectura (ms) | Ejecución (ms) | Estado | Código |
|---|---|---|---|---|---|
| esquema 1 | intérprete (Python) | **68.8** [65.9–72.9] RIC 2.6 | **122** [116–139] RIC 5.5 | OK | 0 |
| esquema 1 | VM (C++) | **7.7** [7.1–10.3] RIC 0.4 | **8.1** [7.6–9.3] RIC 0.3 | OK | 0 |
| esquema 1 | web (WebAssembly) | **119** [111–149] RIC 7.5 | **152** [143–176] RIC 8.5 | OK (formato: `\n` en vez de `\r\n`; marca `[wasm] main() -> N` en stderr) | 0 |
| esquema 2 | intérprete (Python) | **67.3** [63.1–71.8] RIC 2.0 | **120** [109–172] RIC 7.6 | OK | 0 |
| esquema 2 | VM (C++) | **7.7** [7.2–8.7] RIC 0.5 | **8.1** [7.7–9.4] RIC 0.4 | OK | 0 |
| esquema 2 | web (WebAssembly) | **119** [111–132] RIC 4.1 | **153** [141–176] RIC 6.3 | OK (formato: `\n` en vez de `\r\n`; marca `[wasm] main() -> N` en stderr) | 0 |

Salida esperada por la semántica documentada: `dev/diff/programs/02_aritmetica.expected` (cuenta en el estado: si no coincide, la celda es ERROR).

<details><summary>Salida de referencia (intérprete, esquema 2)</summary>

```text
precedencia 2 + 3 * 4 = 14
parentesis (2 + 3) * 4 = 20
resta asociativa 10 - 4 - 3 = 3
division asociativa 100 / 10 / 5 = 2
7 / 2 = 3
7 % 2 = 1
-7 / 2 = -3
-7 % 2 = -1
7 / -2 = -3
7 % -2 = 1
-7 / -2 = 3
-7 % -2 = -1
-1 / 3 = 0
-1 % 3 = -1
-9 % 3 = 0
unario -a * -b = 14
float 7.0 / 2.0 = 3.5
float -7.0 / 2.0 = -3.5
float 0.1 + 0.2 = 0.30000000000000004
float 1.0 / 3.0 = 0.3333333333333333
float 1e16 + 1.0 = 1e+16
mezcla (a * 3 - b) % 5 = 4
```

</details>

### `03_control.srcx`

| | Esquema 1 | Esquema 2 |
|---|---|---|
| Emisión (ms) | **273** [258–304] RIC 9.8 | **272** [252–316] RIC 9.8 |
| Tamaño `.phir` (programa / todas) | 2655 / 3985 B (4 unidades) | 2461 / 3750 B (4 unidades) |

| HIR | Target | Lectura (ms) | Ejecución (ms) | Estado | Código |
|---|---|---|---|---|---|
| esquema 1 | intérprete (Python) | **67.4** [61.9–72.5] RIC 2.8 | **120** [111–153] RIC 6.7 | OK | 0 |
| esquema 1 | VM (C++) | **7.8** [7.1–10.4] RIC 0.6 | **8.1** [7.5–9.1] RIC 0.4 | OK | 0 |
| esquema 1 | web (WebAssembly) | **116** [111–133] RIC 6.8 | **149** [142–171] RIC 7.9 | OK (formato: `\n` en vez de `\r\n`; marca `[wasm] main() -> N` en stderr) | 0 |
| esquema 2 | intérprete (Python) | **67.4** [63.1–85.3] RIC 3.2 | **120** [113–141] RIC 3.8 | OK | 0 |
| esquema 2 | VM (C++) | **7.7** [7.0–10.6] RIC 0.5 | **8.2** [7.4–9.6] RIC 0.4 | OK | 0 |
| esquema 2 | web (WebAssembly) | **122** [113–147] RIC 10.2 | **154** [144–182] RIC 6.4 | OK (formato: `\n` en vez de `\r\n`; marca `[wasm] main() -> N` en stderr) | 0 |

<details><summary>Salida de referencia (intérprete, esquema 2)</summary>

```text
clasifica(-3) = -1
clasifica(-2) = -1
clasifica(-1) = -1
clasifica(0) = 0
clasifica(1) = 1
clasifica(2) = 1
clasifica(3) = 1
suma de pares 1..20 = 110
fila 1: 1
fila 2: 6
fila 3: 18
fila 4: 40
pasos = 5, listo = true
```

</details>

### `04_vector.srcx`

| | Esquema 1 | Esquema 2 |
|---|---|---|
| Emisión (ms) | **353** [332–369] RIC 8.3 | **322** [300–341] RIC 13.8 |
| Tamaño `.phir` (programa / todas) | 2207 / 28693 B (7 unidades) | 1959 / 24553 B (7 unidades) |

| HIR | Target | Lectura (ms) | Ejecución (ms) | Estado | Código |
|---|---|---|---|---|---|
| esquema 1 | intérprete (Python) | **90.6** [85.5–99.3] RIC 4.5 | **147** [136–169] RIC 7.0 | OK | 0 |
| esquema 1 | VM (C++) | **8.9** [8.3–11.8] RIC 0.4 | **10.1** [9.1–12.3] RIC 0.7 | OK | 0 |
| esquema 1 | web (WebAssembly) | **119** [109–130] RIC 8.3 | **151** [138–205] RIC 7.5 | **NOT SUPPORTED** (web: WEB002, WEB003, WEB006, WEB103) | 1 |
| esquema 2 | intérprete (Python) | **80.4** [75.6–107] RIC 3.5 | **135** [126–144] RIC 3.8 | OK | 0 |
| esquema 2 | VM (C++) | **8.1** [7.4–8.9] RIC 0.5 | **9.0** [8.4–11.3] RIC 0.7 | OK | 0 |
| esquema 2 | web (WebAssembly) | **119** [114–153] RIC 8.9 | **151** [141–191] RIC 11.6 | **NOT SUPPORTED** (web: WEB002, WEB003, WEB006, WEB103) | 1 |

<details><summary>Salida de referencia (intérprete, esquema 2)</summary>

```text
len = 10
primero = 1, ultimo = 100
suma de cuadrados 1..10 = 385
```

</details>

### `05_funciones.srcx`

| | Esquema 1 | Esquema 2 |
|---|---|---|
| Emisión (ms) | **279** [261–317] RIC 10.9 | **272** [254–304] RIC 7.5 |
| Tamaño `.phir` (programa / todas) | 3002 / 4332 B (4 unidades) | 2788 / 4077 B (4 unidades) |

| HIR | Target | Lectura (ms) | Ejecución (ms) | Estado | Código |
|---|---|---|---|---|---|
| esquema 1 | intérprete (Python) | **66.7** [62.0–74.5] RIC 5.1 | **693** [687–718] RIC 13.9 | OK | 0 |
| esquema 1 | VM (C++) | **7.4** [6.8–8.7] RIC 0.6 | **11.1** [10.6–13.3] RIC 0.7 | OK | 0 |
| esquema 1 | web (WebAssembly) | **119** [112–158] RIC 3.5 | **152** [141–183] RIC 8.8 | OK (formato: `\n` en vez de `\r\n`; marca `[wasm] main() -> N` en stderr) | 0 |
| esquema 2 | intérprete (Python) | **66.9** [62.0–74.0] RIC 3.8 | **698** [687–757] RIC 9.4 | OK | 0 |
| esquema 2 | VM (C++) | **7.5** [6.9–8.6] RIC 0.8 | **11.4** [10.9–15.0] RIC 0.4 | OK | 0 |
| esquema 2 | web (WebAssembly) | **119** [114–140] RIC 8.6 | **153** [146–201] RIC 6.9 | OK (formato: `\n` en vez de `\r\n`; marca `[wasm] main() -> N` en stderr) | 0 |

<details><summary>Salida de referencia (intérprete, esquema 2)</summary>

```text
factorial(10) = 3628800
factorial(20) = 2432902008176640000
fib(20) = 6765
mcd(1071, 462) = 21
ackermann(2, 3) = 9
es_par(31) = false
```

</details>

### `07_division_cero.srcx`

| | Esquema 1 | Esquema 2 |
|---|---|---|
| Emisión (ms) | **270** [250–378] RIC 10.7 | **267** [252–315] RIC 15.6 |
| Tamaño `.phir` (programa / todas) | 565 / 1895 B (4 unidades) | 553 / 1842 B (4 unidades) |

| HIR | Target | Lectura (ms) | Ejecución (ms) | Estado | Código |
|---|---|---|---|---|---|
| esquema 1 | intérprete (Python) | **67.2** [61.4–72.1] RIC 4.1 | **121** [111–151] RIC 4.9 | OK | 70 |
| esquema 1 | VM (C++) | **7.4** [7.0–10.3] RIC 0.6 | **7.8** [7.1–8.7] RIC 0.4 | OK (formato: otro texto en stderr: `error de ejecucion: excepción no capturada — EXC001: división por cero (11:17)`) | 70 |
| esquema 1 | web (WebAssembly) | **121** [115–139] RIC 7.3 | **150** [144–164] RIC 6.6 | **ERROR** (trap de wasm sin traducir (`RuntimeError: divide by zero`); antes imprime iguales 1 de 1 líneas; código 1 en vez de 70) | 1 |
| esquema 2 | intérprete (Python) | **64.7** [59.7–71.2] RIC 4.6 | **118** [110–165] RIC 4.7 | OK | 70 |
| esquema 2 | VM (C++) | **7.5** [7.2–10.9] RIC 0.4 | **7.8** [7.1–8.7] RIC 0.6 | OK (formato: otro texto en stderr: `error de ejecucion: excepción no capturada — EXC001: división por cero (11:17)`) | 70 |
| esquema 2 | web (WebAssembly) | **117** [112–135] RIC 7.4 | **149** [139–167] RIC 7.3 | **ERROR** (trap de wasm sin traducir (`RuntimeError: divide by zero`); antes imprime iguales 1 de 1 líneas; código 1 en vez de 70) | 1 |

<details><summary>Salida de referencia (intérprete, esquema 2) y stderr</summary>

```text
antes de dividir
```

```text
excepción no capturada — EXC001: división por cero (11:17)
```

</details>

### `08_desbordamiento.srcx`

| | Esquema 1 | Esquema 2 |
|---|---|---|
| Emisión (ms) | **276** [257–307] RIC 14.8 | **274** [257–337] RIC 6.5 |
| Tamaño `.phir` (programa / todas) | 2433 / 3763 B (4 unidades) | 2264 / 3553 B (4 unidades) |

| HIR | Target | Lectura (ms) | Ejecución (ms) | Estado | Código |
|---|---|---|---|---|---|
| esquema 1 | intérprete (Python) | **67.7** [63.1–87.5] RIC 4.8 | **125** [118–160] RIC 6.0 | OK | 0 |
| esquema 1 | VM (C++) | **7.5** [7.0–10.9] RIC 0.6 | **7.8** [7.2–10.4] RIC 0.3 | OK | 0 |
| esquema 1 | web (WebAssembly) | **121** [114–177] RIC 16.3 | **155** [144–171] RIC 9.7 | **ERROR** (trap de wasm sin traducir (`RuntimeError: divide result unrepresentable`); antes imprime iguales 12 de 13 líneas; código 1 en vez de 0) | 1 |
| esquema 2 | intérprete (Python) | **68.5** [59.3–101] RIC 7.3 | **123** [113–134] RIC 7.9 | OK | 0 |
| esquema 2 | VM (C++) | **8.0** [7.3–12.6] RIC 0.9 | **8.4** [7.8–10.4] RIC 0.7 | OK | 0 |
| esquema 2 | web (WebAssembly) | **117** [113–130] RIC 2.5 | **154** [142–181] RIC 6.8 | **ERROR** (trap de wasm sin traducir (`RuntimeError: divide result unrepresentable`); antes imprime iguales 12 de 13 líneas; código 1 en vez de 0) | 1 |

Salida esperada por la semántica documentada: `dev/diff/programs/08_desbordamiento.expected` (cuenta en el estado: si no coincide, la celda es ERROR).

<details><summary>Salida de referencia (intérprete, esquema 2)</summary>

```text
max = 9223372036854775807
min = -9223372036854775808
max + 1 = -9223372036854775808
min - 1 = 9223372036854775807
max * 2 = -2
max * max = 1
-min = -9223372036854775808
min * -1 = -9223372036854775808
min % -1 = 0
3^70 envuelto = 2293070008301402073
2^62 + 2^62 = -9223372036854775808
2^53 + 1 = 9007199254740993
min / -1 = -9223372036854775808
```

</details>

### `09_structs.srcx`

| | Esquema 1 | Esquema 2 |
|---|---|---|
| Emisión (ms) | **273** [257–301] RIC 12.4 | **270** [254–320] RIC 9.1 |
| Tamaño `.phir` (programa / todas) | 1474 / 2804 B (4 unidades) | 1366 / 2655 B (4 unidades) |

| HIR | Target | Lectura (ms) | Ejecución (ms) | Estado | Código |
|---|---|---|---|---|---|
| esquema 1 | intérprete (Python) | **65.9** [60.1–73.9] RIC 3.9 | **121** [112–168] RIC 6.1 | OK | 0 |
| esquema 1 | VM (C++) | **7.6** [7.1–8.5] RIC 0.6 | **8.5** [7.7–9.3] RIC 0.6 | OK | 0 |
| esquema 1 | web (WebAssembly) | **119** [112–139] RIC 10.5 | **146** [135–175] RIC 12.9 | **NOT SUPPORTED** (web: WEB100, WEB101) | 1 |
| esquema 2 | intérprete (Python) | **64.5** [59.3–86.8] RIC 4.1 | **118** [110–160] RIC 8.2 | OK | 0 |
| esquema 2 | VM (C++) | **7.4** [6.9–9.9] RIC 0.5 | **8.0** [7.4–9.2] RIC 0.6 | OK | 0 |
| esquema 2 | web (WebAssembly) | **118** [114–136] RIC 3.9 | **146** [135–159] RIC 5.2 | **NOT SUPPORTED** (web: WEB100, WEB101) | 1 |

<details><summary>Salida de referencia (intérprete, esquema 2)</summary>

```text
x=1 y=5.0 visible=false tag=p
x=2 y=10.0 visible=true tag=p
x=4 y=20.0 visible=false tag=p
```

</details>

### `06_sintetico_10.srcx`

| | Esquema 1 | Esquema 2 |
|---|---|---|
| Emisión (ms) | **280** [264–339] RIC 9.8 | **276** [259–299] RIC 5.9 |
| Tamaño `.phir` (programa / todas) | 3566 / 4896 B (4 unidades) | 3289 / 4578 B (4 unidades) |

| HIR | Target | Lectura (ms) | Ejecución (ms) | Estado | Código |
|---|---|---|---|---|---|
| esquema 1 | intérprete (Python) | **68.4** [63.6–89.5] RIC 4.2 | **124** [114–149] RIC 6.4 | OK | 0 |
| esquema 1 | VM (C++) | **7.5** [6.9–8.4] RIC 0.5 | **8.4** [7.7–11.2] RIC 0.5 | OK | 0 |
| esquema 1 | web (WebAssembly) | **120** [115–161] RIC 7.1 | **153** [139–172] RIC 6.3 | OK (formato: `\n` en vez de `\r\n`; marca `[wasm] main() -> N` en stderr) | 0 |
| esquema 2 | intérprete (Python) | **65.6** [60.6–73.8] RIC 3.3 | **122** [113–151] RIC 6.3 | OK | 0 |
| esquema 2 | VM (C++) | **7.2** [6.7–9.9] RIC 0.5 | **7.5** [7.0–9.3] RIC 0.5 | OK | 0 |
| esquema 2 | web (WebAssembly) | **118** [113–139] RIC 4.3 | **152** [144–185] RIC 8.1 | OK (formato: `\n` en vez de `\r\n`; marca `[wasm] main() -> N` en stderr) | 0 |

<details><summary>Salida de referencia (intérprete, esquema 2)</summary>

```text
b0 i1=342
b0 i0=87
b0 i0=87
total = 342
```

</details>

### `06_sintetico_1000.srcx`

| | Esquema 1 | Esquema 2 |
|---|---|---|
| Emisión (ms) | **602** [566–638] RIC 19.2 | **426** [409–463] RIC 11.4 |
| Tamaño `.phir` (programa / todas) | 124002 / 125332 B (4 unidades) | 110892 / 112181 B (4 unidades) |

| HIR | Target | Lectura (ms) | Ejecución (ms) | Estado | Código |
|---|---|---|---|---|---|
| esquema 1 | intérprete (Python) | **200** [187–243] RIC 7.1 | **283** [263–309] RIC 14.9 | OK | 0 |
| esquema 1 | VM (C++) | **11.6** [10.6–15.4] RIC 0.6 | **13.8** [12.9–15.9] RIC 0.4 | OK | 0 |
| esquema 1 | web (WebAssembly) | **125** [119–156] RIC 6.7 | **197** [185–253] RIC 10.0 | OK (formato: `\n` en vez de `\r\n`; marca `[wasm] main() -> N` en stderr) | 0 |
| esquema 2 | intérprete (Python) | **145** [134–170] RIC 5.4 | **225** [211–260] RIC 7.2 | OK | 0 |
| esquema 2 | VM (C++) | **10.7** [9.8–13.5] RIC 0.5 | **13.5** [12.5–16.1] RIC 0.8 | OK | 0 |
| esquema 2 | web (WebAssembly) | **121** [112–179] RIC 6.2 | **192** [178–215] RIC 8.1 | OK (formato: `\n` en vez de `\r\n`; marca `[wasm] main() -> N` en stderr) | 0 |

<details><summary>Salida de referencia (intérprete, esquema 2)</summary>

```text
b0 i0=38
b0 i10=3 c4=y s8=par
b1 i0=243 f1=144.5
b1 s2=zeta f1=144.5 i0=528
b1 c5=p s2=zeta i0=528
b1 c4=x i0=528 f1=73.5
b1 f1=601.5 i0=528 b7=false
b1 f1=302.0 b11=true c13=y
b2 c4=y f1=-8.600000000000001 i0=920
b2 i0=920 f1=-8.600000000000001 c4=y
b2 i3=846316 c4=y f1=-8.600000000000001
b2 c4=y f1=307.4 i0=542661
b2 f9=34.15555555555555 b13=false c4=y
b3 i5=27841 c8=y f1=668.3
b3 c8=y i5=27841 f1=668.3
b3 c8=y i4=44 f1=668.3
b3 f11=421.75 i7=1574 c8=y
b4 i0=748
b4 i0=748
b4 i0=743
b4 b5=true c2=y i4=348
b4 c2=y i0=121 b5=true
b5 i0=980
b5 s3=theta i2=7238
b5 i0=1040 s4=par
b5 f6=0.0 i0=1057 s4=par
b5 f6=0.0 s3=theta i1=0
b5 s4=par i1=0 f6=0.0
b5 f7=0.0 s8=impar i9=-58
b5 i0=1076 f7=0.0 s4=par
… (84 líneas más)
```

</details>

### `06_sintetico_10000.srcx`

| | Esquema 1 | Esquema 2 |
|---|---|---|
| Emisión (ms) | **3999** [3930–4208] RIC 37.1 | **1933** [1863–2005] RIC 36.3 |
| Tamaño `.phir` (programa / todas) | 1176402 / 1177732 B (4 unidades) | 1054049 / 1055338 B (4 unidades) |

| HIR | Target | Lectura (ms) | Ejecución (ms) | Estado | Código |
|---|---|---|---|---|---|
| esquema 1 | intérprete (Python) | **1585** [1555–1896] RIC 13.2 | **1927** [1903–1981] RIC 28.6 | OK | 0 |
| esquema 1 | VM (C++) | **49.2** [47.9–55.7] RIC 3.0 | **85.2** [79.8–127] RIC 5.1 | OK | 0 |
| esquema 1 | web (WebAssembly) | **174** [162–191] RIC 7.4 | **449** [421–516] RIC 28.2 | OK (formato: `\n` en vez de `\r\n`; marca `[wasm] main() -> N` en stderr) | 0 |
| esquema 2 | intérprete (Python) | **988** [968–1038] RIC 19.9 | **1327** [1286–1355] RIC 13.9 | OK | 0 |
| esquema 2 | VM (C++) | **34.9** [33.6–38.5] RIC 1.5 | **68.5** [62.8–77.7] RIC 2.9 | OK | 0 |
| esquema 2 | web (WebAssembly) | **152** [139–164] RIC 7.6 | **400** [363–458] RIC 13.6 | OK (formato: `\n` en vez de `\r\n`; marca `[wasm] main() -> N` en stderr) | 0 |

<details><summary>Salida de referencia (intérprete, esquema 2)</summary>

```text
b0 i0=12 b1=false
b0 b1=false i0=42
b0 i2=48 b1=false
b0 i0=42 b1=false
b0 i0=218 b1=false
b0 i2=188 b1=false
b1 i0=274
b1 i0=274
b1 i0=274
b1 i0=274
b1 s6=zeta b9=true i10=27
b1 b9=true s6=zeta i5=686
b1 c14=p b15=true i10=27
b2 i0=295
b2 i1=86933
b2 i0=332
b2 i5=0
b2 i1=85
b2 b8=false i1=85 s9=alfa
b3 i0=450 f6=7.267857142857143
b3 i0=450 f6=7.267857142857143
b3 f6=7.267857142857143 i7=174
b3 f6=7.267857142857143 c8=x i7=174
b4 c1=d i3=28126
b4 i8=57393 f12=14.25 c1=d
b5 i0=956
b5 i0=956
b5 i3=29676 s8=par
b6 s7=par f1=40.25 i0=282
b6 s7=par f1=40.25 i11=9233
… (1122 líneas más)
```

</details>

### Los sintéticos, de un vistazo

Generados por `dev/diff/gen_synthetic.py` (semilla fija): funciones de ~40 sentencias con int, float, bool, str, char y un enum sin datos; aritmética, comparaciones, `if`, `while`, llamadas, `match` y `println` de resultados intermedios. **Sin structs**, porque el web los rechaza (ver `09_structs.srcx`).

| Sentencias | Fuente | `.phir` esq. 1 → 2 | Emisión esq. 1 → 2 (ms) | Ejecución intérprete (Python) esq. 1 → 2 (ms) | Ejecución VM (C++) esq. 1 → 2 (ms) | Ejecución web (WebAssembly) esq. 1 → 2 (ms) |
|---|---|---|---|---|---|---|
| 10 | 1570 B | 3566 → 3289 B (-7.8 %) | 280 → 276 | 124 → 122 | 8.4 → 7.5 | 153 → 152 |
| 1000 | 38377 B | 124002 → 110892 B (-10.6 %) | 602 → 426 | 283 → 225 | 13.8 → 13.5 | 197 → 192 |
| 10000 | 362646 B | 1176402 → 1054049 B (-10.4 %) | 3999 → 1933 | 1927 → 1327 | 85.2 → 68.5 | 449 → 400 |

## 2. Compilador V0 frente a compilador V1

Los dos emiten el esquema 2. "Compilador V0" es el `.phir` del esquema 2 de la sección anterior; "compilador V1" es el que emite la V1 corriendo en la VM, ejecutado con las unidades de librería que emitió ella misma.

| Programa | Emisión V0 (ms) | Emisión V1 (ms) | Estado de la emisión V1 | `.phir` V0 = V1 (byte a byte) | Celdas del compilador V1 (OK / NS / ERROR) |
|---|---|---|---|---|---|
| `01_hola.srcx` | **264** [255–288] RIC 6.7 | **100** [92.9–122] RIC 4.3 | OK | sí (4/4 unidades) | 3 / 0 / 0 |
| `02_aritmetica.srcx` | **275** [254–330] RIC 20.7 | **145** [141–185] RIC 6.0 | OK | **NO** (02_aritmetica.srcx.phir) | 3 / 0 / 0 |
| `03_control.srcx` | **272** [252–316] RIC 9.8 | **131** [124–143] RIC 4.8 | OK | **NO** (03_control.srcx.phir) | 3 / 0 / 0 |
| `04_vector.srcx` | **322** [300–341] RIC 13.8 | **128** [119–161] RIC 6.4 | **NOT SUPPORTED** (PAR003, PAR023, SEM010) | — | 0 / 3 / 0 |
| `05_funciones.srcx` | **272** [254–304] RIC 7.5 | **130** [123–154] RIC 3.9 | OK | **NO** (05_funciones.srcx.phir) | 3 / 0 / 0 |
| `06_sintetico_10.srcx` | **276** [259–299] RIC 5.9 | **138** [130–158] RIC 5.0 | OK | sí (4/4 unidades) | 3 / 0 / 0 |
| `06_sintetico_1000.srcx` | **426** [409–463] RIC 11.4 | **1520** [1477–1658] RIC 38.7 | OK | sí (4/4 unidades) | 3 / 0 / 0 |
| `06_sintetico_10000.srcx` | **1933** [1863–2005] RIC 36.3 | **13521** [13213–15733] RIC 228 | OK | sí (4/4 unidades) | 3 / 0 / 0 |
| `07_division_cero.srcx` | **267** [252–315] RIC 15.6 | **106** [101–119] RIC 5.1 | OK | sí (4/4 unidades) | 2 / 0 / 1 |
| `08_desbordamiento.srcx` | **274** [257–337] RIC 6.5 | **125** [117–133] RIC 4.7 | OK | **NO** (08_desbordamiento.srcx.phir) | 2 / 0 / 1 |
| `09_structs.srcx` | **270** [254–320] RIC 9.1 | **116** [110–133] RIC 5.6 | OK | sí (4/4 unidades) | 2 / 1 / 0 |

Detalle de las celdas del compilador V1 (lectura y ejecución de su `.phir`):

#### `01_hola.srcx`

| HIR | Target | Lectura (ms) | Ejecución (ms) | Estado | Código |
|---|---|---|---|---|---|
| compilador V1 | intérprete (Python) | **66.9** [61.0–83.4] RIC 3.9 | **115** [109–124] RIC 4.7 | OK | 0 |
| compilador V1 | VM (C++) | **8.0** [7.3–10.7] RIC 1.0 | **8.8** [7.7–15.8] RIC 1.9 | OK | 0 |
| compilador V1 | web (WebAssembly) | **117** [112–130] RIC 5.0 | **151** [141–179] RIC 8.4 | OK (formato: `\n` en vez de `\r\n`; marca `[wasm] main() -> N` en stderr) | 0 |

#### `02_aritmetica.srcx`

| HIR | Target | Lectura (ms) | Ejecución (ms) | Estado | Código |
|---|---|---|---|---|---|
| compilador V1 | intérprete (Python) | **67.7** [62.9–74.3] RIC 4.6 | **117** [108–150] RIC 6.6 | OK | 0 |
| compilador V1 | VM (C++) | **7.9** [7.2–10.5] RIC 0.4 | **10.6** [7.8–14.8] RIC 4.2 | OK | 0 |
| compilador V1 | web (WebAssembly) | **121** [113–145] RIC 11.3 | **152** [142–175] RIC 10.5 | OK (formato: `\n` en vez de `\r\n`; marca `[wasm] main() -> N` en stderr) | 0 |

#### `03_control.srcx`

| HIR | Target | Lectura (ms) | Ejecución (ms) | Estado | Código |
|---|---|---|---|---|---|
| compilador V1 | intérprete (Python) | **66.7** [63.4–81.5] RIC 7.3 | **117** [107–152] RIC 7.2 | OK | 0 |
| compilador V1 | VM (C++) | **7.8** [6.9–8.6] RIC 0.4 | **8.1** [7.6–11.5] RIC 0.5 | OK | 0 |
| compilador V1 | web (WebAssembly) | **117** [111–125] RIC 5.1 | **155** [142–188] RIC 14.0 | OK (formato: `\n` en vez de `\r\n`; marca `[wasm] main() -> N` en stderr) | 0 |

#### `04_vector.srcx`

| HIR | Target | Lectura (ms) | Ejecución (ms) | Estado | Código |
|---|---|---|---|---|---|
| compilador V1 | intérprete (Python) | — | — | **NOT SUPPORTED** (no hay `.phir`: PAR003, PAR023, SEM010) | — |
| compilador V1 | VM (C++) | — | — | **NOT SUPPORTED** (no hay `.phir`: PAR003, PAR023, SEM010) | — |
| compilador V1 | web (WebAssembly) | — | — | **NOT SUPPORTED** (no hay `.phir`: PAR003, PAR023, SEM010) | — |

#### `05_funciones.srcx`

| HIR | Target | Lectura (ms) | Ejecución (ms) | Estado | Código |
|---|---|---|---|---|---|
| compilador V1 | intérprete (Python) | **67.8** [61.4–74.6] RIC 5.4 | **698** [690–719] RIC 11.9 | OK | 0 |
| compilador V1 | VM (C++) | **7.5** [6.8–9.3] RIC 0.7 | **11.4** [10.5–13.5] RIC 0.7 | OK | 0 |
| compilador V1 | web (WebAssembly) | **117** [113–147] RIC 7.6 | **151** [141–169] RIC 7.2 | OK (formato: `\n` en vez de `\r\n`; marca `[wasm] main() -> N` en stderr) | 0 |

#### `06_sintetico_10.srcx`

| HIR | Target | Lectura (ms) | Ejecución (ms) | Estado | Código |
|---|---|---|---|---|---|
| compilador V1 | intérprete (Python) | **66.3** [60.7–76.0] RIC 4.2 | **121** [110–176] RIC 5.5 | OK | 0 |
| compilador V1 | VM (C++) | **7.3** [6.9–10.6] RIC 0.5 | **7.8** [7.2–8.7] RIC 0.5 | OK | 0 |
| compilador V1 | web (WebAssembly) | **121** [112–205] RIC 14.6 | **160** [141–206] RIC 23.7 | OK (formato: `\n` en vez de `\r\n`; marca `[wasm] main() -> N` en stderr) | 0 |

#### `06_sintetico_1000.srcx`

| HIR | Target | Lectura (ms) | Ejecución (ms) | Estado | Código |
|---|---|---|---|---|---|
| compilador V1 | intérprete (Python) | **145** [135–189] RIC 7.6 | **228** [211–259] RIC 9.4 | OK | 0 |
| compilador V1 | VM (C++) | **10.2** [9.4–14.2] RIC 0.5 | **13.1** [12.3–14.4] RIC 0.8 | OK | 0 |
| compilador V1 | web (WebAssembly) | **123** [117–143] RIC 4.2 | **195** [177–247] RIC 12.4 | OK (formato: `\n` en vez de `\r\n`; marca `[wasm] main() -> N` en stderr) | 0 |

#### `06_sintetico_10000.srcx`

| HIR | Target | Lectura (ms) | Ejecución (ms) | Estado | Código |
|---|---|---|---|---|---|
| compilador V1 | intérprete (Python) | **989** [971–1036] RIC 19.7 | **1326** [1299–1369] RIC 13.4 | OK | 0 |
| compilador V1 | VM (C++) | **34.0** [31.7–37.8] RIC 2.9 | **69.6** [66.7–102] RIC 3.7 | OK | 0 |
| compilador V1 | web (WebAssembly) | **153** [140–182] RIC 6.8 | **394** [359–473] RIC 29.7 | OK (formato: `\n` en vez de `\r\n`; marca `[wasm] main() -> N` en stderr) | 0 |

#### `07_division_cero.srcx`

| HIR | Target | Lectura (ms) | Ejecución (ms) | Estado | Código |
|---|---|---|---|---|---|
| compilador V1 | intérprete (Python) | **65.8** [58.9–90.2] RIC 7.5 | **119** [113–142] RIC 5.1 | OK | 70 |
| compilador V1 | VM (C++) | **8.4** [6.8–10.7] RIC 1.8 | **7.8** [7.1–11.4] RIC 0.6 | OK (formato: otro texto en stderr: `error de ejecucion: excepción no capturada — EXC001: división por cero (11:17)`) | 70 |
| compilador V1 | web (WebAssembly) | **118** [112–135] RIC 5.9 | **151** [141–175] RIC 9.2 | **ERROR** (trap de wasm sin traducir (`RuntimeError: divide by zero`); antes imprime iguales 1 de 1 líneas; código 1 en vez de 70) | 1 |

#### `08_desbordamiento.srcx`

| HIR | Target | Lectura (ms) | Ejecución (ms) | Estado | Código |
|---|---|---|---|---|---|
| compilador V1 | intérprete (Python) | **65.0** [59.9–102] RIC 7.4 | **121** [111–139] RIC 8.2 | OK | 0 |
| compilador V1 | VM (C++) | **7.9** [7.1–10.7] RIC 0.6 | **8.2** [7.7–9.3] RIC 0.6 | OK | 0 |
| compilador V1 | web (WebAssembly) | **118** [112–138] RIC 4.9 | **152** [143–172] RIC 7.4 | **ERROR** (trap de wasm sin traducir (`RuntimeError: divide result unrepresentable`); antes imprime iguales 12 de 13 líneas; código 1 en vez de 0) | 1 |

#### `09_structs.srcx`

| HIR | Target | Lectura (ms) | Ejecución (ms) | Estado | Código |
|---|---|---|---|---|---|
| compilador V1 | intérprete (Python) | **64.5** [60.2–102] RIC 6.7 | **120** [115–135] RIC 4.2 | OK | 0 |
| compilador V1 | VM (C++) | **7.7** [7.1–10.5] RIC 0.4 | **8.4** [7.6–11.5] RIC 0.7 | OK | 0 |
| compilador V1 | web (WebAssembly) | **118** [114–133] RIC 6.1 | **145** [138–168] RIC 9.9 | **NOT SUPPORTED** (web: WEB100, WEB101) | 1 |

## NOT SUPPORTED y ERROR: qué y por qué

Todo sale de la salida capturada (medido). Donde una causa va más allá de la salida, su texto dice qué parte es inferida.

### ERROR (10 celdas, emisiones o comparaciones de compiladores)

| Programa | Dónde | Detalle / causa |
|---|---|---|
| `02_aritmetica.srcx` | compilador V0 frente a V1 | `.phir` distintos (02_aritmetica.srcx.phir): primer byte distinto: 315 (de 3797 y 3797 B); en la vista `--text` difieren 66 líneas, p. ej. `col: 49` (V0) contra `col: 45` (V1), `col: 49` (V0) contra `col: 45` (V1), `col: 53` (V0) contra `col: 45` (V1). Medido: TODAS son columnas (`col`), en las líneas 11, 12, 13, 14, 15, 16, 17, 18, 19, 20, 21, 22, 23, 24, 25, 26, 29, 30, 31, 32, 33, 34 del fuente (todas con f-strings); el árbol es el mismo. Reproducción mínima en el README §10 |
| `03_control.srcx` | compilador V0 frente a V1 | `.phir` distintos (03_control.srcx.phir): primer byte distinto: 616 (de 2461 y 2461 B); en la vista `--text` difieren 1 líneas, p. ej. `col: 52` (V0) contra `col: 42` (V1). Medido: TODAS son columnas (`col`), en las líneas 17 del fuente (todas con f-strings); el árbol es el mismo. Reproducción mínima en el README §10 |
| `05_funciones.srcx` | compilador V0 frente a V1 | `.phir` distintos (05_funciones.srcx.phir): primer byte distinto: 1985 (de 2788 y 2788 B); en la vista `--text` difieren 8 líneas, p. ej. `col: 47` (V0) contra `col: 37` (V1), `col: 47` (V0) contra `col: 37` (V1), `col: 35` (V0) contra `col: 31` (V1). Medido: TODAS son columnas (`col`), en las líneas 50, 51, 52, 53, 54, 55 del fuente (todas con f-strings); el árbol es el mismo. Reproducción mínima en el README §10 |
| `07_division_cero.srcx` | compilador V1 × web (WebAssembly) | trap de wasm sin traducir (`RuntimeError: divide by zero`); antes imprime iguales 1 de 1 líneas; código 1 en vez de 70 |
| `07_division_cero.srcx` | esquema 1 × web (WebAssembly) | trap de wasm sin traducir (`RuntimeError: divide by zero`); antes imprime iguales 1 de 1 líneas; código 1 en vez de 70 |
| `07_division_cero.srcx` | esquema 2 × web (WebAssembly) | trap de wasm sin traducir (`RuntimeError: divide by zero`); antes imprime iguales 1 de 1 líneas; código 1 en vez de 70 |
| `07_division_cero.srcx` | causa | División entera por cero: en wasm es un trap; el web no lo convierte en `EXC001` (código 70) como el intérprete y la VM, y node sale con 1 y su pila. Medido: mensaje y código. Inferido: el codegen emite `i64.div_s` sin comprobar el divisor. |
| `08_desbordamiento.srcx` | compilador V0 frente a V1 | `.phir` distintos (08_desbordamiento.srcx.phir): primer byte distinto: 557 (de 2264 y 2264 B); en la vista `--text` difieren 10 líneas, p. ej. `col: 37` (V0) contra `col: 31` (V1), `col: 37` (V0) contra `col: 31` (V1), `col: 37` (V0) contra `col: 31` (V1). Medido: TODAS son columnas (`col`), en las líneas 11, 12, 13, 14, 15, 16, 17, 26, 27, 30 del fuente (todas con f-strings); el árbol es el mismo. Reproducción mínima en el README §10 |
| `08_desbordamiento.srcx` | compilador V1 × web (WebAssembly) | trap de wasm sin traducir (`RuntimeError: divide result unrepresentable`); antes imprime iguales 12 de 13 líneas; código 1 en vez de 0 |
| `08_desbordamiento.srcx` | esquema 1 × web (WebAssembly) | trap de wasm sin traducir (`RuntimeError: divide result unrepresentable`); antes imprime iguales 12 de 13 líneas; código 1 en vez de 0 |
| `08_desbordamiento.srcx` | esquema 2 × web (WebAssembly) | trap de wasm sin traducir (`RuntimeError: divide result unrepresentable`); antes imprime iguales 12 de 13 líneas; código 1 en vez de 0 |
| `08_desbordamiento.srcx` | causa | `MIN / -1`: en wasm es un trap; el intérprete y la VM ENVUELVEN y dan `MIN`, como manda la documentación. Medido: el mensaje del trap. Inferido: el codegen emite `i64.div_s` sin el caso especial. |

### NOT SUPPORTED (6 celdas, emisiones o comparaciones de compiladores)

| Programa | Dónde | Detalle / causa |
|---|---|---|
| `04_vector.srcx` | emisión compilador V1 | PAR003, PAR023, SEM010: `<repo>/lib/array/vector.libsrx:275:15: PAR003 se esperaba GREATER, se encontro COLON ⏎ <repo>/lib/array/vector.libsrx:358:44: PAR023 se esperaba un tipo, se encontro FUNCTION ⏎ <repo>/lib/array/vector.libsrx:490:32: PAR023 se esperaba un tipo, se encontro FUNCTION ⏎ 04_vector.srcx:3:1: SEM010 la librería 'vector' (vector.libsrx) no compila: 3 error(es) léxico(s)/sintáctico(s), cada uno con su posición en ese archivo` |
| `04_vector.srcx` | esquema 1 × web (WebAssembly) | web: WEB002, WEB003, WEB006, WEB103 |
| `04_vector.srcx` | esquema 2 × web (WebAssembly) | web: WEB002, WEB003, WEB006, WEB103 |
| `04_vector.srcx` | causa | La V1 no compila `lib/array/vector.libsrx` de hoy: su parser no acepta la cota `T: Ord` ni los tipos función `fn(...) -> ...`. Medido: PAR003 en 275:15 (`@impl Vector<T: Ord> {`); PAR023 en 358:44 (`fn sort_by(Vector<T> ptr mutable self, fn(T ptr, T ptr) -> int cmp) -> void {`); PAR023 en 490:32 (`fn any(Vector<T> ptr self, fn(T ptr) -> bool pred) -> bool {`) |
| `04_vector.srcx` | causa | El web rechaza `Vector`: su implementación usa punteros (WEB002, WEB003), `move` (WEB006) y funciones como valores (WEB103). Medido: códigos WEB002, WEB003, WEB006, WEB103, el primero en `<stdlib>/array/vector.libsrx`. |
| `09_structs.srcx` | compilador V1 × web (WebAssembly) | web: WEB100, WEB101 |
| `09_structs.srcx` | esquema 1 × web (WebAssembly) | web: WEB100, WEB101 |
| `09_structs.srcx` | esquema 2 × web (WebAssembly) | web: WEB100, WEB101 |
| `09_structs.srcx` | causa | El codegen web no representa structs (WEB100/WEB101: "un struct o un puntero, no"). Medido en el diagnóstico. |

Diferencias que NO cuentan como error (la celda es OK y se anota en ella): en Windows el intérprete y la VM escriben `\r\n` y node `\n`; el CLI del web escribe `[wasm] main() -> N` en stderr; ante un error de ejecución, la VM antepone `error de ejecucion: ` al mensaje del intérprete.

## Reducciones de repeticiones

Ninguna: todas las celdas hicieron las corridas pedidas.

## Límites de la medición

- **Cada tiempo incluye arrancar el proceso** (Python, node o la VM; ver la línea base). En programas pequeños el arranque domina, y eso diluye cualquier diferencia entre esquemas: el cambio de esquema solo afecta a leer el `.phir`, no a arrancar.
- La **lectura** es la operación más cercana a "solo cargar" que expone cada target, pero no son idénticas (la VM con `--link` además imprime las unidades).
- La **ejecución** del web incluye generar el WebAssembly; la de la VM, bajar a MIR y verificar; la del intérprete, ligar las unidades. Los CLI no permiten separarlo.
- El **criterio de ruido** (solapamiento de los RIC) es una regla simple, no una prueba de hipótesis; con 29 muestras por lado y sin aislamiento de CPU, diferencias de pocos por ciento no se pueden afirmar.
- Resolución del reloj: namespace(implementation='QueryPerformanceCounter()', monotonic=True, adjustable=False, resolution=1e-07); mucho más fina que los tiempos medidos.
- **Sin aislamiento de CPU** (ni afinidad, ni prioridad, ni frecuencia fija). 12 núcleos lógicos, en uso normal (carga antes: 13 % de uso de CPU (Win32_Processor.LoadPercentage); después: 9 % de uso de CPU (Win32_Processor.LoadPercentage)). En la corrida publicada había **carga de fondo**: otro agente trabajando en paralelo y procesos del mantenedor (un servidor de lenguaje `--lsp` y `playground/server.py`). Corridas secuenciales; cada celda hace sus corridas seguidas, sin intercalar, así que una deriva lenta afecta más a unas celdas que a otras.
- Se descarta la primera corrida de cada medida (caché de disco, `.pyc`).
- El esquema 1 que se mide es el **adaptado a hoy** (`--hir-schema 1`), no un `.phir` escrito por el compilador de agosto de 2026: ver `schema/README.md`.
- Salidas capturadas por tubería. En Linux las tres escribirían `\n`.
- El web corre en node (V8), no en un navegador. Un solo equipo, una sola corrida.
- Que los targets coincidan con la referencia dice que son CONSISTENTES; para 02 y 08 hay además una salida esperada (`.expected`) calculada aparte con la semántica documentada (dividir truncando hacia cero, envolver a 64 bits).

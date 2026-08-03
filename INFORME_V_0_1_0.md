# Informe: estado de RBMM y move-semantics

> Fecha: 2026-07-30 · version del proyecto en publico: Pre-Alpha (V.0.0.1)
> version a lanzar al publico: Pre-Alpha(V.0.1.0): frontend Python + intérprete + backend de memoria C++

Este informe responde a "RBMM y move-semantics no funcionan del todo bien":
separa lo que **está roto** de lo que **no está implementado a propósito** en
la version actual, documenta el fix aplicado y los falsos negativos que quedan por resolver

---

## 1. Resumen ejecutivo

| area | veredicto |
|---|---|
| **move-semantics (variable completa)** | Funciona (compilación y runtime) |
| **move-semantics (campo/path `o.it`)** |  Era **falso negativo** se **corrigio** |
| **punteros / `&` / const-correctness** | Robusto  |
| **backend de memoria C++ nativo** |  cumple `move`/`free`/aliasing en runtime |
| **RBMM (regiones)** | **No es completamente funcional en la vesion actual**, se esta usando myrscX para probar edge cases y demas posibilidades que puedan existir y colapsar compilacion |

La conclusión clave: **RBMM no está "roto" del todo, hay muchos edge cases existentes que toca observar y manejar**
*(el HIR lo rechaza con `HIR005` y la semántica con `SEM012`, errores reales en lugar de silencios)*

---

## 2. move-semantics: casos verificados

Probados de punta a punta con interprete:

| Caso | Antes | Ahora |
|---|---|---|
| `move a; var b = a;` (use-after-move) | `SEM004` | `SEM004`  |
| `move a; move a;` (doble move) | `SEM005`  | `SEM005`  |
| `move a; a = …; b = a;` (revive por reasignación) | valido  | valido  |
| move en bucle usado en la 2ª vuelta | `RT001` en runtime  | `RT001`  |
| aliasing: `p = &a; move a; p.v` | `RT001` (via nativo)  | `RT001`  |
| **`move o.it; … o.it.v`** (use-after-move de CAMPO) |  **sin error** (falso negativo) |  **`SEM004`** |
| **`move o; … o.it.v`** (usar campo de var movida) | `SEM004`  | `SEM004`  |
| `move p.a; … p.b.v` (hermano no afectado) | valido  | valido (sin falsos positivos que "simulen" para validar) |
| `move o.it; o.it = …; o.it.v` (revive el campo) | valido  | valido  |

### El bug corregido

`V0/src/frontend/semantic/memory_check.py` rastreaba solo **nombres simples**:
un `move o.it` caía en la rama compuesta que verificaba lecturas pero **no
marcaba el campo como movido**. Resultado: usar `o.it` después no daba error ni
en compilación ni en runtime (confirmado: imprimía el valor como si nada).

**Fix**: el conjunto `moved` ahora indexa **rutas estáticas** (`o.it`,
`o.it.v`), no solo nombres. Reglas:

- mover `o.it` invalida `o.it` y todo lo que cuelga (`o.it.v`), pero **no** el
  padre `o` ni los hermanos (`o.other`);
- mover la variable completa `o` invalida también sus campos;
- reasignar `o.it` (o `o` entero) lo **revive** junto con sus descendientes;
- el indexado `a[i]` **no** se rastrea (es dinámico; distinguir `a[0]` de
  `a[1]` estáticamente daría falsos positivos) — queda para el MIR.

Blindado con tests de regresión en `test/negative_tests/test_diagnostics.py`
(`test_use_after_move_de_un_campo`, `..._por_mover_la_variable`, y tres
`test_valido_*` que garantizan cero falsos positivos).

---

## 3. Falsos negativos que quedan por resolver 

Coherentes con `semantic/ARQUITECTURA.md`: la pasada de memoria es lineal, sin punto fijo ni análisis inter-función

**Nunca rechaza un programa válido** a cambio deja pasar lo que el MIR (backend C++) verificará de forma definitiva:

- **move en una iteración anterior de un `while`**: una sola pasada del cuerpo, lo atrapa el runtime (`RT001`), no la semántica.
- **escape/move inter-función**: no se sigue el valor a través de llamadas.
- **leer el PADRE de un campo movido** (`move o.it; … usar o` entero): no se marca dirección conservadora (evita falsos positivos por movimiento parcial). Usar `o.it` sí se marca; usar `o` completo no.

Estos son límites de diseño, no defectos: el objetivo educativo prioriza diagnósticos claros y cero falsos positivos sobre exhaustividad estática que, podria llegar a romper un programa.

---

## 4. RBMM (regiones) decisiones de diseño:

Todas las formas de RBMM se **rechazan fail-fast, sin crashes ni tracebacks**:

| Forma | Resultado |
|---|---|
| `region r { … }` | `HIR005`: 'region' no viaja en el HIR v1 |
| `new(shrd region r);` | `HIR005` |
| `delete(region r);` | `SEM012`: región no declarada |
| `in region r: …` | `SEM012` |
| `expr at r` | `SEM012` |
| `move region a -> region b;` | `SEM012` |

El HIR reserva los tags para reintroducir RBMM sin romper el esquema
(explicado en `ROADMAP.md` Fase 5 y `docs/hir.md`).

`make` dejó de ser keyword; la construcción en región vendrá con HIR + arenas por región en el runtime(`runtime/interpreter/memory/`) en la **V.0.2.0**

**Para reponer RBMM (futura version)**: devolver `region`/`make`/`at` al HIR (quitar el rechazo `HIR005`), sin añadir un nuevo token, añadir arenas por región en el intérprete y la verificación definitiva de lifetimes en el MIR/C++.

---

## 5. Punteros, `&` y const-correctness (contexto)

Verificacion robusta (modelo de memoria sobre el que se apoya move/RBMM):

| Caso | Resultado |
|---|---|
| `&` de un temporal/literal (`&5`, `&(a+1)`) | `SEM013`  |
| escritura por `ptr T` (no mutable) | `SEM015`  |
| `free` sobre un no-puntero | `SEM014`  |
| `&const` → `ptr mutable` (init/arg) | `AST006`  (cierra una fuga de `const`) |
| deref de `null` | `RT004` en runtime  |
| use-after-free vía alias | `RT003` (backend nativo)  |
| indexado fuera de rango (`buf[9]` en `[0,4)`) | `RT013`  |

> Nota relacionada (type-checker): en esta misma version se cerró un hueco por el que los **tipos de argumento** de una llamada no se verificaban al pasar `int` a un `str`, o `&Other` donde se espera `Box ptr`, compilaba y explotaba en runtime, Ahora es error de tipos en compilación (`AST006`). Es distinto del RBMM/move pero afecta la solidez del modelo de punteros (permitía mutar un `const` a través de un parámetro `ptr mutable`).

---

## 6. Backend de memoria C++ (`runtime/logic_mem`)

- Core puro `include/mem_core.hpp`: máquina de estados `LIVE/MOVED/FREED`, handles monotónicos, códigos de estado (no excepciones) agnóstico del target.

- Binding pybind11 `cxx_entry.cpp` → módulo `memory_c`. Carga y funciona (100/100 e2e con `SURIAX_NATIVE_MEM=1`) permitiendo usar punteros **no simulados**.
  
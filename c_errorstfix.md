# Informe de errores y riesgos visibles en el repositorio

**INFORME DE LA VERSION PUBLICA 0.2.0**

Este documento resume los problemas y riesgos que se observan actualmente en
el proyecto: lo que hay que corregir en la proxima version.

**importante**: cada version lanzada al publico puede venir con errores; los
mas importantes salen en este resumen. Lo que ya se corrigio se queda escrito
al final, para que quien venia de la 0.1.4 sepa que ya no tiene que esquivar.

## Resumen general

El frontend (lexer → parser → AST tipado → Semantica → HIR) y el interprete
tree-walk estan completos y se ejercitan de punta a punta. El backend nativo
(MIR → VM/JIT) **no existe todavia**: es lo unico que separa a suriaX de
poder compilar a un binario. El target web (`.phir` → WIR → JS/WASM) ejecuta
un subconjunto declarado del lenguaje.

No es una version estable. Es una pre-alpha que ya hace lo que dice hacer.

---

## Problemas abiertos

### 1. Literales de cadena adyacentes no se concatenan

```srcx
stdp.println(f"parte uno " f"parte dos");   // PAR003
```

En C, C++ y Python dos literales pegados forman uno solo, y es como se parte
una cadena larga en varias lineas. Aqui hay que escribir `+`, que funciona
pero obliga a una operacion en tiempo de ejecucion donde deberia bastar una
decision del lexer.

**Se noto** escribiendo `b.srcx`, el ejercicio de inventario del repositorio:
un mensaje largo no cabia en una linea y no habia forma natural de partirlo.

#### solucion propuesta

Concatenar en el **lexer**, que es donde no cuesta nada. Requiere decidir
antes que pasa al pegar una `f""` con una `""`: la interpolacion tiene que
sobrevivir a la union o la regla confunde mas de lo que ayuda.

### 2. `internal` no se comprueba, `private` si

La visibilidad entre paquetes esta aplicada: importar un `private` de otro
paquete es `SEM019`. Lo que **no** se comprueba es `internal`, que promete
"visible solo dentro de su archivo" y hoy no lo hace cumplir nadie.

El riesgo no es que rompa algo, es peor: una promesa escrita que el
compilador no sostiene, y codigo que se apoya en ella sin saberlo.

#### solucion propuesta

O se comprueba, o se retira del lenguaje. Un modificador que no restringe
nada gasta una palabra del presupuesto (42 de 50 usadas) sin dar nada.

### 3. Backend nativo: MIR, VM y JIT

Sigue siendo el hueco grande. El HIR cruza al lado C++ como contrato, pero
no hay lector, ni lowering a MIR, ni VM.

Decidido en esta version: **el target nativo es una VM de bytecode con JIT,
no LLVM**. El MIR ya es un IR de registros con CFG; meter LLVM en medio
anadia una dependencia enorme y un segundo modelo de memoria que verificar.

#### pospuesto para V.0.4.0

### 4. La libreria de vectores no es generica todavia

Los genericos existen y se comprueban (`struct { ... } Vector<T>;`, con
sustitucion real al instanciar), pero `lib/array/vector.libsrx` sigue siendo
monomorfico sobre `int`. Quien quiera un vector de otra cosa lo copia.

#### solucion propuesta

Migrar la libreria al generico ya implementado. Es trabajo de libreria, no
de compilador.

### 5. Sin inferencia de tipos, por decision

`var int x = 1;` no se puede escribir `var x = 1;`. **Es deliberado**: menos
complejidad, mejores diagnosticos. El registro de la decision esta en
[la documentacion](documentation/source/inference_decision.rst).

Se anota aqui porque a quien viene de otro lenguaje le parece un error, y no
lo es.

### 6. El paquete nativo necesita pybind11

El modelo de memoria del interprete tiene un lado C++ (`runtime/logic_mem/`)
que se construye con pybind11. El frontend entero corre sin el —y sin
protobuf, y sin pyyaml—, pero distribuir un binario nativo no es trivial.

#### recomendacion

Para un uso sin dependencias nativas, no usar punteros (`ptr`, `&`). El
compilador diagnostica lo que le falta en vez de reventar: `--check` lo dice
antes de empezar.

---

## Corregido desde la 0.1.4

- **Las librerias de `lib/` compilan todas.** El error de sintaxis en
  `lib/math/basic.libsrx` ("se esperaba `;` y se encontro `fn`") ya no
  ocurre; hay una prueba que compila cada `.libsrx` del repositorio.
- **El despacho cross-modulo funciona.** Un dunder sobre un tipo de otra
  libreria se encuentra y se llama (ver [lib/HOOKS.md](lib/HOOKS.md)).
- **El modelo por regiones se retiro.** No podia verificarse; en su lugar hay
  **ownership** con drop automatico al cerrar el ambito. Se liberaron 8
  palabras reservadas. El registro esta en
  [la decision de memoria](documentation/source/memory_decision.rst).
- **La version tiene una sola fuente.** `version.py` en la raiz: lo leen
  CMake, la documentacion publicada, `suriaX --version`, el contrato del LSP
  y el release. Antes el README decia 0.1.4, `README_ES.md` 0.1.5 y la
  documentacion publicaba 0.2.0, los tres para el mismo commit.
- **La documentacion desalineada.** Los documentos que el sitio publica y
  viven junto al codigo ya disparan su reconstruccion; antes se editaban y la
  pagina seguia mostrando lo viejo.

*happy coding : )*

## src y v0?

si haz revisado los contenidos del repositorio notaras algo "extraño": **/v0** contiene todos los archivos del compilador mientras que **/src** contiene otros archivos, esto se debe a que, en suriaX uno de los objetivos a largo plazo es el **bootsraping**, motivo por el cual v0 contendra la arquitectura general de la version 0 del compilador 

en la **V1**, la cual estara creada en suriaX y libsrX exclusivamente **/src** sera el directorio propuesto y el directorio **/config** tendra configuraciones generales del compilador e interacciones con el tooling el cual no se menciona pero es otra integracion planeada

*happy coding : )*

## La V1 hoy

```bash
python V0/main.py src/main.srcx --emit-hir     # la V0 compila la V1
mkdir -p salida                                # la V1 no crea la carpeta de salida
suriax-hir dumps/main.srcx.phir --run -- programa.srcx salida/programa.phir --stdlib lib
```

La V1 escribe el `.phir` del programa y, en la misma carpeta, el
`<unidad>.phir` de cada librería que carga, como la V0. La stdlib le llega
por `--stdlib` o por `SURIAX_STDLIB` (la V0 la deduce de dónde está
instalada; la V1 es un `.phir` y no tiene forma de saberlo). `-O0` es el
defecto; `-O1`/`-O2` están reservados: la V1 no optimiza (su meta es generar
el mismo programa que la V0); las optimizaciones llegan con la V3.

(`src/main.srcx` importa sus paquetes como librerías: el proyecto que la
compila tiene `frontend/`, `semantica/` y `hir/` dentro de su `lib/`. Así la
arma la prueba, `test/bootstrap/test_bootstrap_v1.py`.)

| paquete | qué hace | en la V0 |
|---|---|---|
| [`frontend/`](frontend/readme.md) | lexer y parser: el árbol, idéntico al de la V0 | `V0/src/frontend/lexer`, `parser` |
| `semantica/` | el universo de tipos, la tabla de símbolos, el tipo de cada expresión y la propiedad (qué se destruye) | `semantic/`, `typed_ast.py` |
| `hir/` | el `.phir`: el emisor y el formato de bytes de protobuf | `V0/src/HIR/emmit_IR.py`, `wire.py` |
| `semantica/enlazador.libsrx` | buscar y leer librerías; lo que comparten las unidades de una compilación | `V0/src/linker_p/` |
| `main.srcx` | el compilador: fuente -> `.phir` | `V0/main.py` |

**El punto fijo está alcanzado** (lote 19): la V1 compila su propio fuente
y sus 30 unidades (la V1 y cada librería que importa) son idénticas, byte a
byte, a las de la V0; compilada por sí misma, da otra vez lo mismo. Las tres
etapas:

```bash
python V0/main.py main.srcx --emit-hir                    # 1. la V0 compila la V1: A (dumps/)
mkdir -p etapa2 etapa3                                    # la V1 no crea carpetas
suriax-hir dumps/main.srcx.phir --run --pasos 0 -- \
    main.srcx etapa2/main.srcx.phir --stdlib <lib>        # 2. A compila la V1: B == A
suriax-hir etapa2/main.srcx.phir --run --pasos 0 -- \
    main.srcx etapa3/main.srcx.phir --stdlib <lib>        # 3. B compila la V1: C == B
```

Lo comprueba `test/bootstrap/test_punto_fijo.py` en cada corrida de la
suite. Medido en la VM (Windows, compilación Release): unos 11 s por etapa,
8,8 millones de objetos creados y todos liberados, y un pico de 21 MB de
memoria del programa (`--memoria`). Se llegó por rebanadas: cada lote llevó
un subconjunto del lenguaje de punta a punta y el siguiente lo ensanchó (ver
la Fase 11 de [ROADMAP.md](../ROADMAP.md)).

**Lo que cubre:**

- lote 14: funciones, variables del módulo, `int`, `float`, `bool`, `str`,
  `char`, `var`/`const`, aritmética, comparaciones, lógica,
  `if`/`else if`/`else`, `while`, llamadas y `return`;
- lote 15: `struct`, `enum` (con payload), `match`, punteros y `&`, acceso a
  campos, índices, `cast`, `move`, `free`, `hook fn`, f-strings (con formato),
  `len`, `break`/`continue` y la PROPIEDAD con tipos del propio módulo: lo que
  se destruye al cerrar cada bloque, los temporales, `transfers` y
  `drops_old`;
- lote 16: el LINKER. `#import` y `#from` (archivos, paquetes, submódulos,
  el hermano de un paquete que se carga), la visibilidad (`internal` no
  sale de su archivo, `private` solo dentro del paquete), los hooks de las
  librerías fusionados en el importador, los nombres canónicos de los tipos
  (`punto.Punto`) y una unidad por `.phir`, con la ruta absoluta de cada
  librería calculada como la calcula Python (`sistema.rutas`);
- lote 17a: los GENÉRICOS. Structs y funciones con parámetros de tipo
  (`Caja<T>`, `fn make<T>`), instancias anidadas (`Caja<Caja<int>>`), campos
  y llamadas vistos desde la instancia (sustituidos), argumentos de tipo
  escritos o deducidos, y la propiedad dentro de un genérico (un `T` se
  destruye por su tipo). Con esto la V1 compila `mem`, la librería genérica
  de la stdlib que no usa `@impl`;
- lote 17b: los MÉTODOS (`@impl`, `dunder fn`, también los de una
  librería), los hooks con receptor genérico (`v[i]`, `v[i] = x`),
  `print`/`len`/`hash` sobre un tipo, `throw`/`try`/`catch`/`finally` y el
  `with`. Con esto la V1 compila, idénticas, TODAS las librerías que ella
  misma importa (`array.vector`, `collections.dictionary`, `sistema.*`,
  `text`, `excepciones`, `io`, `mem`).

Sobre esos programas el `.phir` de la V1 es idéntico al de la V0
(`test/bootstrap/v1/`), y sobre cada proyecto con librerías, cada una de sus
unidades (`test/bootstrap/v1_proyectos/`). Qué emite la V0 y por qué, regla por regla, está en
[`hir/contrato.md`](hir/contrato.md). Supone un programa válido: la V1
todavía no da diagnósticos semánticos (y por eso no necesita la verificación
de memoria de la V0, que solo diagnostica).

Cómo resuelve lo que el lenguaje no tiene:

- **Tipos recursivos:** un tipo de la V0 contiene a otros (`ptr int`). Aquí
  los tipos viven en una arena y se nombran por su índice
  (`semantica/tipos.libsrx`), con cada forma una sola vez: comparar dos tipos
  es comparar dos enteros.
- **Varias unidades sin copiar tipos:** todas las unidades de una compilación
  comparten UN universo de tipos, así que un tipo de librería es el mismo
  índice en el programa y en la librería. Lo que exporta cada librería vive
  en una sola tabla (`Contexto.exportes`) y el importador copia lo que ve.
- **El orden de los bytes:** el pool de tipos del HIR se numera en el orden
  en que la V0 recorre el árbol, pero los campos se escriben en orden de
  número. El emisor hace dos pasadas (`hir/emisor.libsrx`).

Límites conocidos:

- La V1 no lee el `.suriaX_config.yaml`: busca las librerías con la ruta por
  defecto (`./lib` del proyecto) y la stdlib. Un proyecto que declare otras
  `libsrx_paths` compila distinto en la V1.
- Fuera del subconjunto (la V1 no los usa): `const type`, `sizeof`,
  `min`/`max` de un tipo, `#extern`, traits y las conversiones `__cast__`.
- Compilarse a sí misma pasa del límite de pasos POR DEFECTO de la VM (100
  millones): se corre con `--pasos 0`.
- Sin diagnósticos: supone un programa válido (lote 18).

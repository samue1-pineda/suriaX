# Errores conocidos de suriaX

**VERSIÓN 0.3.1**

La biblia de los errores de la **versión publicada** (la de
[`version.py`](version.py)): todo lo que se sabe que falla. Si algo está
roto y no aparece aquí, lo que está incompleto es este documento. Solo lista
lo que **sigue abierto**; cuando algo se corrige, sale de aquí y queda en
[CHANGELOG.md](CHANGELOG.md).

Cada versión lanzada al público puede traer errores; aquí van TODOS los
conocidos, no solo los grandes.

## Estado general

- **Frontend** (lexer → parser → AST tipado → Semántica) y **HIR**: completos.
  El compilador entero —incluida la ejecución— corre **solo con la
  biblioteca estándar de Python**.
- **Intérprete tree-walk**: completo. Es el target `interp` y el oráculo de
  las pruebas diferenciales.
- **Backend C++** (`backend/`): lowering a MIR, VM de registros y
  verificación de propiedad. Da la misma salida que el intérprete en todo el
  corpus del repositorio, incluido el bootstrap, y es unas 150 veces más
  rápida. Falta el JIT y cualquier binario nativo, y hay construcciones que
  todavía no baja (ver 1).
- **Target web** (`.phir` → WIR → JS/WASM): ejecuta un subconjunto declarado.
- **Bootstrap** (`src/`, el compilador escrito en suriaX): se compila a sí
  mismo con resultados idénticos a los de la V0 (el punto fijo). Todavía no
  da diagnósticos (supone un programa válido), no lee el
  `.suriaX_config.yaml` (busca las librerías en `./lib` y la stdlib) y no
  crea la carpeta de salida: escribir en `salida/x.phir` sin que exista es
  `EXC003` (la V0 sí la crea).

Es una pre-alpha: hace lo que dice hacer, con los límites de abajo.

---

## 1. Backend nativo (C++)

- **Sin JIT ni binario**: la VM interpreta el MIR; no genera `.exe` ni `.o`.
  Decidido: el target nativo será una VM con JIT, no LLVM (pospuesto para
  la 0.4.0).
- **Un programa que aborta no libera lo que tenía vivo**: una excepción que
  nadie atrapa, un `RT` o `salir()` terminan el proceso sin cerrar sus
  ámbitos, como en C++.
- **La verificación de préstamos es local a un bloque**: prestar en una rama
  y transferir en otra no se cruza.
- **`#extern cpp` en la VM** tiene tres límites que el intérprete no tiene
  igual:
  - hasta 6 parámetros por función;
  - la llamada se arma con una firma de enteros de 64 bits y doubles, que es
    correcta en las ABI de 64 bits (x86-64 de Linux y de Windows, AArch64)
    y no en una de 32;
  - `suriax-hir` no lee el `.suriaX_config.yaml`: el compilador y las
    banderas salen de `$CXX` y `SURIAX_CPP_FLAGS` (y de los `requires(...)`
    de los bloques).

  En los dos motores, una excepción de C++ que cruza la frontera termina el
  proceso: el contrato es `extern "C"`.
- **El recolector de cadenas de la VM es conservador**: un registro que
  todavía guarda el índice de una cadena vieja la mantiene viva un rato más.
  `--memoria-max` recoge antes de rendirse, pero puede cortar con algo más de
  memoria de la que el programa usa de verdad.
- **La posición de una excepción de `sistema`** (`e.linea`) es la de la
  llamada DENTRO de la librería, no la del programa que llamó a
  `sis.leer(...)`. Es el mismo problema que los errores `RT` sin archivo
  (sección 3).

## 2. Propiedad y memoria

- **Un préstamo de `at` que sobrevive a su elemento** (`var R ptr p =
  v.at(0); v.set(0, ...); p.id`): la VM da `RT003` (el elemento murió) y el
  intérprete lee el elemento NUEVO de la misma celda. Es un programa
  incorrecto en los dos, pero solo uno lo dice.
- **Leer una celda que se sacó con `mem.take`**: el intérprete da `RT001`
  (movida) y la VM lee `0`, porque no lleva el estado de cada celda de un
  bloque (tampoco el de una celda sin escribir).
- **`&b[i]` de un escalar** (`int`, `float`...) lo acepta el frontend y es
  `RT011` en los dos motores: necesitaría un puntero al interior del bloque
  (bloque + desplazamiento). El de un objeto funciona (es lo que usa
  `Vector.at`). El frontend debería rechazar el de un escalar al compilar.
- **`Vector<void>` compila y no significa nada.**

## 2b. Target web

- **`byte` y el formato de un f-string (`!r`, `:08b`) no bajan al target
  web**: se rechazan con un `WEB` explícito (`CODEGEN_TYPE`,
  `CODEGEN_STRING`), no se ignoran. Los cambios del web de este lote no se
  compilaron en la máquina donde se hicieron (no había `node`): los verifica
  la CI.

## 3. Diagnósticos que confunden

- **Los errores de ejecución no dicen en qué ARCHIVO ocurrieron**: un `throw`
  desde una librería sale como `RT020: throw ... (102:30)`, y esa línea es de
  la librería.
- **`frontend OK: ...` se imprime aunque haya errores**, justo encima de
  ellos.
- **Un programa que se llama como una librería que importa se importa a sí
  mismo**: `excepciones.srcx` con `#import excepciones` encuentra primero su
  propio archivo (la carpeta del fuente es la primera ruta de búsqueda) y el
  error dice `SEM010: 'excepciones.srcx' no termina en '#export ...'`, que
  no nombra la causa.
- **Una f-string partida en dos líneas ubica sus interpolaciones en una
  posición mezclada**: en `f"a{x}"` seguido en la línea siguiente de
  `f"b{y}"`, la `y` queda en la línea de la PRIMERA cadena con la columna de
  la segunda. Un error dentro de esa interpolación apunta a un sitio que no
  es. (El parser del bootstrap reproduce lo mismo, a propósito, para poder
  compararse.)
- **Dentro de una interpolación, todas las expresiones llevan la MISMA
  posición.** En `f"{doble(mas_uno(3))}"` las dos llamadas salen en la
  columna de la interpolación. Un error en cualquiera de ellas apunta al
  mismo sitio.

  El backend C++ confundía las dos llamadas por eso, y ahora identifica cada
  sitio por su nodo. La causa sigue en el frontend.
- **Errores en cascada tras la recuperación del parser**: `var int xs[3];` da
  `PAR023` (correcto) y además un `PAR012` falso sobre el `};` de cierre.
- **`error` es palabra reservada y el diagnóstico no lo dice**: un campo
  `int error;` da `PAR003: se esperaba un nombre ..., se encontro ERRORTYPE`
  y arrastra un `SEM001`.
- **`--check` marca `protobuf` y `pybind11` como `[FALTA]`**, pero son
  opcionales. `V0/driver/artifacts.py` culpa a protobuf de cualquier fallo al
  importar el emisor.
- **Dos sitios descartan la causa de un fallo**:
  - `semantic/hooks.py` (`except Exception: real = None`: el diagnóstico sale
    con `<?>`);
  - `semantic/extensions.py` (`except Exception: return None`).

## 4. Windows

- **Imprimir caracteres fuera de cp1252 con la salida redirigida es un
  ICE000** (el UB-1, abajo). La suite no lo ve porque corre en modo UTF-8.
- **El `linker` autodetectado puede ser el `link.EXE` de Git** (coreutils,
  no un enlazador); `--init-config` lo escribe en el yaml. El mismo problema
  aparece al construir el backend con un `clang++` suelto: la guía
  [`CMake/README.md`](CMake/README.md) explica cómo usar MSVC.
- La suite solo corre en Ubuntu en la CI (el build sí corre en los tres
  sistemas): lo específico de Windows no lo ve un workflow. En esta máquina
  la suite pasa entera sin variables de entorno.

## 5. Repositorio

- **Faltan dos archivos que se citan**: el `Procfile` (el playground dice
  desplegarse con él) y `docs/propuesta_vm_bytecode.md` (la arquitectura del
  intérprete lo llama "regla no negociable").
- **Una carpeta que no describe el código**: `V0/src/backend/` (planes de un
  backend LLVM que no existe).
- **Los ejemplos de `docs/examples/*.md` no los verifica ninguna prueba.**
- **`test_escalado_lineal_del_frontend` se omite sola a menudo**: si su
  medición dura menos de 10 ms la declara no fiable, y en una máquina rápida
  pasa la mitad de las veces. Su umbral es frágil.
- **`.suriaX_config.yaml` está en `.gitignore`** y una prueba habla de "la
  configuración que se distribuye": hoy se omite diciéndolo.

## 6. Límites del lenguaje que parecen errores

No son fallos: son cosas que el lenguaje todavía no tiene. Se listan porque
quien las encuentra suele pensar que algo se rompió.

- `.name` de un enum solo vale sobre un item escrito (`TType.PLUS.name`), no
  sobre una variable.
- No hay funciones como valores (ni punteros a función ni callbacks), ni
  subcadenas, ni tablas Unicode (ver `src/frontend/readme.md`).
- No hay bucle `for`: todo bucle es un `while`.
- **El parámetro de un genérico se deduce solo si el argumento lo nombra
  ENTERO**: `primero(1)` deduce `T=int` en `fn primero<T>(T a)`, pero con
  `fn f<T>(Caja<T> c)` o `T ptr` hay que escribirlo (`f<int>(c)`). El error
  dice que se esperaba `Caja<T>`, que es exactamente lo que falta escribir.
- **Un bloque de `mem` guardado en un campo es del struct que lo guarda**
  (se copia y se libera con él, como el buffer de un `std::vector`). Un
  struct no puede PRESTAR un bloque ajeno en un campo: para prestar está un
  parámetro `ptr`.
- **Copiar un struct copia todo lo suyo**, incluido el almacenamiento de sus
  vectores. `var vec.Vector<int> b = a;` cuesta O(n); para no copiar se usa
  `move` o un `ptr`.
- No hay literales de arreglo (`[1, 2, 3]`) ni arreglos nativos
  (`int xs[3]`); `int vec.Vector v[5];` sí existe.
- Un `-/` dentro de un comentario de bloque lo cierra (no se anidan).
- No hay tipos recursivos (un árbol se guarda en una arena, enlazado por
  índices), ni una
  forma de sacar un valor de un campo dejando otro en su lugar (lo que en
  Rust es `mem::replace`).
- Agotar la pila (`RT019`) no se puede atrapar: un programa recursivo no
  puede recuperarse de un anidamiento demasiado profundo en su entrada.
- **Un `int?` no se puede desenvolver**: se guarda, se compara (`== 7`,
  `== null`) y se escribe, pero no hay forma de sacar el `int` (ni `cast`,
  ni `match`, ni estrechamiento tras `!= null`). Ordenarlo (`a < 7`) es
  `AST006`.
- **Los operadores de bits no los tiene el target web** (`WEB100`), ni
  `hash(x)`.

## Comportamiento indefinido conocido (UB → ICE000)

Un **ICE000** (error interno del compilador, exit 6) es un comportamiento
indefinido: el compilador no sabía qué hacer con ese programa. Cada caso
conocido se anota aquí con el programa que lo provoca y lo que DEBERÍA
pasar. Cuando recibe su propio error, o deja de fallar, sale de la tabla. La
meta es que se vacíe.

| UB | Programa que lo provoca | Hoy | Debería |
|---|---|---|---|
| UB-1 | En Windows, con la salida redirigida (`> archivo`): `stdp.println("listo ✓");` (cualquier carácter fuera de cp1252) | ICE000: `UnicodeEncodeError` en el intrínseco `__write__` (`runtime/interpreter/intrinsics.py`) | Escribir el texto (UTF-8), sin error |

Si encuentras un ICE000 que no está aquí, es un UB nuevo: anótalo con el
programa mínimo que lo reproduce.

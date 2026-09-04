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

### 1. Backend nativo: MIR, VM y JIT

Sigue siendo el hueco grande, aunque ya no entero: el **lector de HIR en C++
existe** (`backend/`, con su diferencial contra el lector de Python). Lo que
falta es el lowering a MIR y la VM.

Decidido en esta version: **el target nativo es una VM de bytecode con JIT,
no LLVM**. El MIR ya es un IR de registros con CFG; meter LLVM en medio
anadia una dependencia enorme y un segundo modelo de memoria que verificar.

#### pospuesto para V.0.4.0

### 2. La libreria de vectores no es generica todavia

Los genericos de TIPO existen y se comprueban (`struct { ... } Vector<T>;`,
con sustitucion real al instanciar), pero `lib/array/vector.libsrx` sigue
siendo monomorfico sobre `int`. Quien quiera un vector de otra cosa lo copia.

**No es trabajo de libreria: esta bloqueado.** Migrarla exige genericos de
FUNCION (`fn make<T>() -> Vector<T>`, `fn push<T>(Vector<T> ptr v, T x)`),
que no existen. El tipo puede ser generico; su fabrica y sus metodos, no.

#### solucion propuesta

Primero genericos de funcion, y despues la migracion, que entonces si es
trabajo de libreria. El diseño de los genericos de funcion NO esta en duda:
la instanciacion es EXPLICITA en el sitio de llamada (`make<int>()`), porque
el lenguaje no tiene inferencia por decision registrada y `ROADMAP.md` ya
fija `type_args` como "regla compartida para futuros genericos de libreria".
Lo que falta es el trabajo: parser, semantica, un campo nuevo en `hir.proto`,
los TRES lectores y el interprete.

### 3. Literales de arreglo: son un TIPO nuevo, no sintaxis

`[1, 2, 3]` y `int xs[3]` no existen, y se aplazan a proposito junto con los
genericos de funcion. Lo que se midio al evaluarlos:

- `TypeKind` tiene 12 variantes y ninguna es un arreglo. Un literal necesita
  un tipo, asi que hace falta `TypeKind.ARRAY` **con tamaño** (`int[3]` y
  `int[4]` son tipos distintos, igual que `Vector<int>` y `Vector<str>`).
- Eso cruza la frontera: campo nuevo en `hir.proto` y los **tres** lectores
  (interprete, web, C++) mas el emisor.
- El indexado de hoy (`Index`) solo despacha `__index__` sobre nominales;
  un arreglo nativo necesita su propio camino.
- **Choca con el modelo de memoria**: `Drop.path` es una lista de NOMBRES de
  campo y no admite indices, asi que un arreglo de un tipo con `__free__` no
  se puede destruir. Habria que rechazarlo, igual que `SEM029` rechaza un
  payload con destructor.

Y empuja contra el principio central del proyecto —*antes de añadir sintaxis,
la pregunta es si puede ser una libreria mas un hook*—: la respuesta natural
es `Vector<T>`, que vuelve a depender de genericos de funcion. Los dos huecos
estan bloqueados por la MISMA pieza que falta.

### 4. Sin inferencia de tipos, por decision

`var int x = 1;` no se puede escribir `var x = 1;`. **Es deliberado**: menos
complejidad, mejores diagnosticos. El registro de la decision esta en
[la documentacion](documentation/source/inference_decision.rst).

Se anota aqui porque a quien viene de otro lenguaje le parece un error, y no
lo es.

### 5. El paquete nativo necesita pybind11

El modelo de memoria del interprete tiene un lado C++ (`runtime/logic_mem/`)
que se construye con pybind11. El frontend entero corre sin el —y sin
protobuf, y sin pyyaml—, pero distribuir un binario nativo no es trivial.

#### recomendacion

Para un uso sin dependencias nativas, no usar punteros (`ptr`, `&`). El
compilador diagnostica lo que le falta en vez de reventar: `--check` lo dice
antes de empezar.

---

## Corregido desde la 0.2.0

- **Los literales de cadena adyacentes se concatenan.** `"parte uno "
  "parte dos"` es un solo literal, como en C, C++ y Python, y los funde el
  lexer — antes era `PAR003` y habia que escribir `+`, pagando en ejecucion
  algo que se sabe al leer el archivo. La regla del caso dudoso: cada literal
  conserva la SUYA, asi que `f"a{x}" "{y}"` interpola `{x}` y no `{y}`.
- **El lector de HIR en C++ existe** (`backend/`). No ejecuta nada todavia
  —el MIR sigue pendiente— pero congela el contrato de la frontera: sus
  vistas son byte-identicas a las de Python y hay un diferencial que las
  compara sobre un programa que toca cada forma del esquema.
- **`--hir-pretty` ya no revienta con `try`/`catch`.** La vista seguia
  leyendo `catch_name`/`catch_block`, tags `reserved` desde que `TryStmt`
  paso a N ramas filtradas por tipo.
- **La notacion de un tipo no pierde informacion.** `error int` se escribia
  `error` y `Vector<int>` se escribia `Vector`; ademas la clave de tipos del
  indice de conversiones ignoraba los argumentos del generico, asi que
  `Vector<int>` y `Vector<str>` compartian entrada (en el interprete y en el
  target web, que ni siquiera decodificaba el campo).
- **La destruccion que inserta el compilador se ve.** Los `drop` de ambito y
  de campo, el `⟨transfiere⟩` de un retorno que cede la propiedad y el
  `⟨temporal …⟩` del valor que nadie recibe viajaban en el HIR y ninguna
  vista los mostraba.
- **`match` avisa cuando no es exhaustivo** (`SEM030`). Un `match` que no
  encaja con nada no hacia nada, en silencio, y añadir una variante a un
  `enum` dejaba incompletos todos los `match` del proyecto sin que nada lo
  dijera. Es un AVISO y no un rechazo: un `match` parcial es un programa
  valido con significado definido, y el lenguaje no tiene comodin con el que
  decir "el resto me da igual". Solo avisa donde SABE — una rama que el
  analisis no puede leer como variante concreta lo calla entero.
- **Un aviso ya no detiene la compilacion.** La escala de `Severity`
  prometia desde el principio que un WARNING deja continuar, y el pipeline
  no lo cumplia: cualquier diagnostico acumulado ponia el codigo de salida en
  error y el HIR no se emitia. Declarar algo como aviso no servia de nada, y
  por eso no habia ni uno en todo el compilador.
- **Un `struct` es un VALOR.** `var Caja b = a;` daba dos nombres al MISMO
  valor: `b.v = 99` cambiaba tambien `a`, y pasar un struct por valor a una
  funcion dejaba que el llamado mutara al llamador. Con eso la regla de
  punteros no significaba nada — escribir por un `ptr` de solo lectura es
  `SEM015`, pero bastaba pasar el struct por valor. Ahora ligar copia; un
  parametro declarado `ptr` NO se copia, que es lo que permite a un hook o a
  un metodo mutar su receptor.
- **`move` tambien es una EXPRESION** (`var Buffer b = move origen;`). La
  documentacion del modelo de memoria la usaba desde el principio y el parser
  no la tenia: sin ella no habia forma de ligar a otro nombre un valor que
  posee recursos, y ligarlo a secas dejaba DOS duenos y su destructor corria
  dos veces. Ligar sin `move` algo con destructor es ahora `SEM032`.
- **El `int` envuelve a 64 bits.** Python no tiene ese limite, asi que el
  interprete daba `9223372036854775808` donde el target web daba el minimo
  negativo: dos consumidores del MISMO programa con numeros distintos. Y
  guardar ese valor reventaba el backend nativo de memoria con un error de
  pybind11, porque ahi una celda es un `int64_t` de verdad.
- **Dividir por cero es `RT016`**, no un traceback de Python sin posicion.
- **Caerse por el final de una funcion es `RT017`.** Antes devolvia `null` en
  silencio: un valor que no es un `int` en un lenguaje sin coerciones ni
  inferencia, y el fallo aparecia a tres funciones de distancia.
- **Indexar un primitivo es `SEM031`.** `texto[i]` compilaba y moria en
  ejecucion con `RT014`; ahora lo dice el sistema de tipos al leer el
  programa. **El indexado de cadenas sigue sin existir**: es la limitacion
  mas visible al escribir texto sin librerias.
- **La sustitucion de genericos llega a la DESTRUCCION.** El campo de un
  generico se declara como `T`, y `T` no resuelve a nada: sin sustituir,
  `Caja<R>` no poseia nada aunque `R` tuviera `__free__`, asi que su
  destructor **no se ejecutaba nunca**. Lo mismo tapaba los ciclos de tamano
  infinito que pasan por un generico (`struct { Caja<S> c; } S;` se
  aceptaba). Cada pregunta que baja a los campos sustituye primero.
- **La guarda contra recursion del analisis de tamano estaba mal puesta**:
  comparaba el nombre de un TIPO contra la lista de nombres de CAMPO
  recorridos, asi que un ciclo ajeno al tipo consultado (`A` -> `B` -> `C` ->
  `B`) no la disparaba y el recorrido no terminaba.
- **`internal` SI se comprueba.** El informe de la 0.2.0 lo daba por no
  aplicado; en realidad se filtra en el linker de librerias y el consumidor
  recibe `SEM011`. Hay tres pruebas que lo cubren.

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

# Principios de diseño de suriaX

Los principios que guían el diseño del lenguaje y del compilador. Para el
pipeline interno ver [ARCHITECTURE.md](ARCHITECTURE.md); para lo que viene,
[ROADMAP.md](ROADMAP.md) y [FUTURO.md](FUTURO.md).

> **Base para completar.** Cada sección recoge lo que ya está decidido. Las
> marcas **«Por escribir»** señalan dónde falta la explicación del
> mantenedor: el porqué con sus palabras, ejemplos o matices. Cuando una
> sección esté completa, se quita su marca.

---

## 1. Visualización del compilador (objetivo central)

suriaX existe para que estudiantes, docentes y entusiastas **vean qué entrega
cada etapa** del compilador. Cada fase (lexer, parser, AST, AST-tipado,
semántica, HIR, MIR, backend) debe poder inspeccionarse de forma aislada. La
directiva `#test <fase>` y la bandera `--emit-stage` usan este principio:
orquestan una fase y vuelcan su salida. El playground y el depurador (que
muestra el estado de propiedad de cada variable) son la misma idea en otra
forma.

## 2. Paradigma: imperativo con herramientas funcionales y programación genérica

suriaX es un lenguaje **imperativo** de sistemas, con propiedad (`move`,
`free`, préstamos). De lo funcional toma lo que no rompe la propiedad:

- funciones como valores (`fn(A) -> R`);
- tipos algebraicos (enums con datos y `match`);
- `map`, `filter` y `fold`;
- inmutabilidad opcional (`const`);
- lambdas que no escapan.

No toma la inmutabilidad por defecto, que todo sea una expresión, las
clausuras que escapan ni la herencia.

Usa **programación genérica**, más cerca de Ada que de la STL de C++. De los
templates toma lo que no cuesta seguridad de tipos:

- la deducción de los argumentos de tipo desde los argumentos de la llamada;
- cotas al estilo de los conceptos (`<T: Ord + Contrato>`).

No toma la especialización, SFINAE ni la metaprogramación.

> **Por escribir:** por qué este paradigma y no otro, y qué se espera que
> alguien haga con él.

## 3. Seguridad de tipos primero

Ante una duda de diseño, gana la opción que detecta el error **al
compilar**. Lo que fallaría siempre al ejecutar no debería compilar: así se
convirtieron en errores de compilación, por ejemplo, `sizeof` de un tipo sin
`__sizeof__`, prestar un escalar de un bloque o escribir en un `str`.

Cuando una regla segura estorba, la salida no es aflojarla en silencio. Hoy,
por ejemplo, un parámetro de tipo función es **prestado** (solo se llama o se
pasa a otro); para guardar una función se escribe `(fn(...) -> R)?`. A
futuro habrá un **modo no seguro**, como el `unsafe` de Rust, para lo que
convenga hacer fuera de las reglas, con una regla explícita de qué conviene
hacer así (ver [FUTURO.md](FUTURO.md)).

> **Por escribir:** dónde está el límite entre "seguro" y "demasiado
> restrictivo" para un lenguaje educativo.

## 4. Tipado estático, fuerte, nominal y sin inferencia

Los tipos se verifican en compilación. El tipado es **nominal** (la identidad
del tipo viene de su nombre o declaración, no de su forma) y **fuerte** (sin
conversiones implícitas: toda conversión es un `cast<T>(x)` explícito, salvo
un literal con rango comprobado).

**Sin inferencia**: el tipo de una variable, de un parámetro y de un retorno
se escribe siempre, y un binding o parámetro sin anotación es un error.
Hindley-Milner se descartó por su complejidad, su choque con el modelo de
memoria y su distancia del objetivo educativo.

La **deducción** de los argumentos de tipo de una llamada genérica es otra
cosa, y sí existe: el tipo ya está escrito en el argumento y solo se lee de
ahí (`mayor(3, 9)` liga `T = int`), sin conversiones.

## 5. Filosofía libsrX: pocos tokens reservados

Inspirado en C, el núcleo del lenguaje mantiene un **conjunto reducido de
palabras reservadas**; la mayor parte de la funcionalidad llega vía
**librerías nativas** (`.libsrx`). Algunas consecuencias:

- funciones como `println` **no** son keywords: son identificadores resueltos
  contra una librería;
- una `.libsrx` se expone con la directiva `#export <alias>` al final y se
  consume con `#import <lib> [as <alias>]`; si el compilador no identifica la
  directiva, la librería no puede ser llamada;
- añadir capacidades al lenguaje rara vez implica añadir tokens;
- lo que el lenguaje no puede hacer por sí mismo lo pone el **host** (el
  motor que ejecuta), a través de prototipos sin cuerpo: archivos, procesos,
  la entrada estándar, el tiempo (ver [lib/LLAMADAS_AL_HOST.md](lib/LLAMADAS_AL_HOST.md)).

## 6. Sintaxis amigable

Basada en Python y C++, la sintaxis prioriza la legibilidad: bloques con `{}`,
`fn` para funciones, `match`/`case`, `lambda` para las funciones anónimas y el
`;` como terminador de sentencia **obligatorio**. Los errores típicos de quien
viene de otro lenguaje (`&&`, `||`, `!`, el ternario) dan una pista de cómo se
escribe en suriaX.

> **Por escribir:** la revisión de la notación prefija/postfija pensando en
> quien viene de C++ (anotada en [FUTURO.md](FUTURO.md)).

## 7. Modelo de memoria: ownership + drop

> **Cambio de diseño (v0.2.0):** el modelo por regiones (*region-based*) fue
> retirado. Su seguridad dependía por completo de un análisis de no-escape que
> a su vez exigía polimorfismo de región en las firmas —un sistema de tipos que
> nunca se llegó a definir—, y mientras tanto el modelo no era *incompleto*
> sino *inseguro*. El razonamiento entero está en
> [el registro de la decisión](documentation/source/memory_decision.rst).

Ideas centrales:

- **Propiedad única (*ownership*):** todo valor con recursos tiene un dueño y
  solo uno: la variable que lo nombra. No hay aliasing con propiedad
  compartida, así que no hay dobles liberaciones que detectar.
- **Move-semantics (`move x`):** la propiedad se transfiere explícitamente;
  tras un `move` el origen deja de ser usable.
- **Drop determinista:** al cerrar el ámbito que posee un valor, el compilador
  invoca el `__free__` de su tipo. El punto de destrucción es visible en el
  fuente; no hay recolector de basura. Las globales también se destruyen al
  terminar el programa.
- **Liberación anticipada (`free x;`):** destruye antes del cierre del ámbito
  cuando el ámbito dura mucho más que el valor. A partir de ahí el valor queda
  inutilizable, igual que tras un `move`.
- **Copiar es explícito en su costo:** devolver o asignar un valor lo copia
  entero; para no copiar están `move` y los punteros.
- **Punteros y nulabilidad:** `T ptr`, el operador de dirección `&` y el tipo
  nullable `T?` son **préstamos**: no transfieren propiedad. Un `T ptr` sin
  `mutable` es de solo lectura.
- **Arenas (pendiente):** el patrón «reservar mucho, liberar de golpe» que
  hacía atractivas a las regiones se conservará como **tipo de librería**, no
  como sintaxis: un valor con dueño que se destruye con las reglas de
  siempre. Todavía no existe.

La **verificación** ocurre en dos niveles: la etapa **semántica** valida la
propiedad sobre el flujo del cuerpo (uso tras `move`, doble `move`) y el
**MIR** (en C++) la repite sobre el grafo de control de flujo, por **todos**
los caminos que llegan a cada punto. Los tiempos de vida de los préstamos se
siguen, por ahora, dentro de un bloque (ver [docs/mir.md](docs/mir.md)).

Por qué este modelo y no otro: ownership **degrada bien**. Sin su verificador
de préstamos sigue siendo seguro —restrictivo, pero nunca acepta un programa
mal— mientras que las regiones sin análisis de escape aceptaban punteros
colgantes en silencio.

## 8. Interoperabilidad con C++

C++ se integra con el bloque `#extern cpp{ ... }`, cuyo cuerpo el lexer
captura **crudo** (token `RAW_BLOCK`) sin tokenizarlo: el C++ no sigue las
reglas léxicas de suriaX. Una función se liga con un prototipo tipado
(`fn foo(int a) -> int;`) y el contrato es `extern "C"`. El intérprete la
llama con `ctypes` y la VM, con su propia frontera, sin bindings.

> **Por escribir:** qué papel tiene la interoperabilidad en el nicho (el
> enlazado dentro de otro programa está aparcado en [FUTURO.md](FUTURO.md)).

## 9. El sistema de tipos no es una fase

El *type system* **no es una caja en el pipeline**, sino un servicio que
opera sobre varias representaciones (AST, AST-tipado, semántica) y también
informa el lowering a MIR (donde se comprueban los moves y los tiempos de
vida de los préstamos).

La **tabla de símbolos** es, por esto, un **estado persistente del
compilador**, no de una sola fase:

```
Symbol Table = Nombres → Bindings
                       + Info de tipos
                       + Mutabilidad
                       + Propiedad (dueño, préstamos, lifetime)
```

Se crea en el frontend, se enriquece a lo largo de las fases de Python, viaja
**serializada dentro del HIR (protobuf)** y se reconstruye parcialmente en C++
para el MIR. Este enfoque permite conservar la semántica a través de
diferentes representaciones intermedias.

## 10. El HIR es la frontera, y está versionado

El HIR (protobuf) es la **única** frontera entre el frontend y quien ejecuta:
el intérprete, la VM y el target web consumen el mismo `.phir`. Por eso:

- lleva un **`schema_version`** explícito, y un lector rechaza la versión que
  no conoce en vez de malinterpretarla;
- un cambio que no rompe a nadie es **aditivo**: campos nuevos, ningún tag
  reasignado;
- un motor que no sabe ejecutar algo lo **rechaza con su código** (`VM0xx`,
  `WEBxxx`), nunca hace otra cosa en silencio.

> **Por escribir:** qué demuestra el diferencial de esquemas
> ([dev/diff/](dev/diff/)) sobre el valor de versionar.

## 11. Lo nuevo se construye primero en la V0

El lenguaje crece primero en la **V0** (el compilador en Python) y en el
**intérprete**, que es el oráculo de las pruebas. La VM, el target web y la
V1 (el compilador escrito en suriaX) se ponen al día después. Mientras
tanto, lo que no conocen lo rechazan con su código, y el atraso de cada uno
está listado en [c_errorstfix.md](c_errorstfix.md).

> **Por escribir:** el objetivo de desacoplar suriaX de Python (la V1
> compilando y la VM ejecutando) y en qué orden se piensa recorrer.

## 12. Nicho: herramientas que analizan código o texto

suriaX no pretende reemplazar a nada: se apoya en un hueco que otros
lenguajes cubren de forma superficial. Es el de las **herramientas de línea
de comandos que analizan código o texto**: linters, formateadores,
verificadores y scripts de build. Las prioridades de la librería y del
lenguaje se miden contra ese nicho: manejo de texto, recorrer archivos,
argumentos y códigos de salida, lanzar otros programas.

> **Por escribir:** por qué este nicho y qué lo diferencia de usar Python o
> un shell.

## 13. Rendimiento y modularidad como ejes constantes

Dos atributos guían cada decisión del frontend:

- **Rendimiento:** el lexer tokeniza en una sola pasada, con tablas de
  búsqueda O(1) y conteo de líneas y columnas perezoso. Esta decisión es
  esencial, porque el HIR y el MIR penalizan duramente un frontend lento.
- **Modularidad:** el lexer y muchas de las etapas son módulos
  independientes orquestados por un módulo padre, y cada fase tiene fronteras
  y errores propios. Esto facilita crecer (nuevos scanners, nuevas fases) sin
  reescribir enormes cantidades de código.

## 14. Errores con códigos estables, y nunca en silencio

Cada fase define su jerarquía de errores con códigos estables y serializables
(`LEXxxx`, `PARxxx`, `ASTxxx`, `SEMxxx`, `HIRxxx`, `RTxxx`, `EXCxxx`,
`VMxxx`, `WEBxxx`...), derivados de `CompilerError`. Permiten reportes
uniformes, pruebas y trazabilidad a lo largo del pipeline (ver
[errors.rst](documentation/source/errors.rst)).

Un fallo **del compilador** no se mezcla con los del programa: es `ICE000`,
con su propio código de salida (`6`) y el traceback de la excepción original.
Decirle a un estudiante "tu programa tiene un error" cuando el que falló es el
compilador le hace buscar un fallo que no existe. Cada `ICE000` conocido es
un comportamiento indefinido anotado en [c_errorstfix.md](c_errorstfix.md),
con la meta de que esa tabla se vacíe.

Y ningún error es **silencioso**: un resultado incorrecto sin aviso es el
peor fallo posible, peor que un rechazo.

## 15. Nombres en inglés, documentación en español

Los identificadores del código nuevo (librerías, funciones, excepciones, la
V1) se escriben en **inglés**, para quien llegue desde otros lenguajes. La
documentación y los comentarios siguen en **español**. Los nombres que ya
existen en español se renombran en un solo lote más adelante (ver
[FUTURO.md](FUTURO.md)).

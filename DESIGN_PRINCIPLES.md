# Principios de diseño de suriaX

Los principios que guían el diseño del lenguaje y del compilador. Para el
pipeline interno ver [ARCHITECTURE.md](ARCHITECTURE.md)

---

## 1. Visualización del compilador (objetivo central)

suriaX existe para que estudiantes, docentes y entusiastas **vean qué entrega
cada etapa** del compilador. Cada fase (lexer, parser, AST, AST-tipado,
semántica, HIR, MIR, backend) debe poder inspeccionarse de forma aislada. La
directiva `#test <fase>` usa este principio: orquesta
una fase y vuelca su salida.

## 2. Filosofía libsrX: pocos tokens reservados

Inspirado en C, el núcleo del lenguaje mantiene un **conjunto reducido de
palabras reservadas**; la mayor parte de la funcionalidad llega vía **librerías
nativas** (`.libsrx`),algunas consecuencias de esta filosofia son:

- funciones como `printf` **no** son keywords: son identificadores resueltos
  contra una librería;
- una `.libsrx` se expone con la directiva `#export <alias>` al final; se
  consume con `#import <lib> [as <alias>]`, si el compilador no identifica la directiva la libreria no podra ser llamada.
- añadir capacidades al lenguaje rara vez implica añadir tokens
  


## 3. Sintaxis amigable

Basada en Python y C++, la sintaxis prioriza la legibilidad: bloques con `{}`,
`fn` para funciones, `match`/`case`, y el `;` como terminador de sentencia
**obligatorio**.

## 4. Tipado estático fuerte y nominal

Los tipos se verifican en compilación. El tipado es **nominal** (la identidad
del tipo viene de su nombre/declaración, no de su forma) y **fuerte** (sin
conversiones implícitas inseguras). Un binding o parámetro sin anotación de tipo
es un error.

## 5. Modelo de memoria: ownership + drop + arenas

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
  fuente; no hay recolector de basura.
- **Liberación anticipada (`free x;`):** destruye antes del cierre del ámbito
  cuando el ámbito dura mucho más que el valor. A partir de ahí el valor queda
  inutilizable, igual que tras un `move`.
- **Arenas explícitas:** el patrón «reservar mucho, liberar de golpe» que hacía
  atractivas a las regiones se conserva, pero como **tipo de librería**, no
  como sintaxis. Una arena es un valor con dueño y se destruye con las reglas
  de siempre — sin análisis especial.
- **Punteros y nulabilidad:** `ptr T`, el operador de dirección `&` y el tipo
  nullable `T?` son **préstamos**: no transfieren propiedad.

La **verificación** ocurre en dos niveles: la etapa **semántica** valida la
propiedad sobre el flujo del cuerpo (uso-tras-move, doble move) y el
**lowering a MIR** (en C++) hará la verificación final, incluidos los tiempos
de vida de los préstamos.

Por qué este modelo y no otro: ownership **degrada bien**. Sin su verificador
de préstamos sigue siendo seguro —restrictivo, pero nunca acepta un programa
mal— mientras que las regiones sin análisis de escape aceptaban punteros
colgantes en silencio.

## 6. Interoperabilidad con C++

C++ se integra mediante *bindings* (pybind11) y el bloque `#extern cpp{ ... }`,
cuyo cuerpo el lexer captura **crudo** (token `RAW_BLOCK`) sin tokenizarlo: el
C++ no sigue las reglas léxicas de suriaX. La compilación de ese C++ es tarea del
backend.


## 7. El sistema de tipos no es una fase

Un aclaracion importante: el *type system* **no es una caja en el
pipeline**, sino un servicio que opera sobre varias representaciones (AST,
AST-tipado, semántica) y también informa el lowering a MIR (donde se
comprueban los moves y los tiempos de vida de los préstamos).

La **tabla de símbolos** es, por esto, un **estado persistente del compilador**,
no de una sola fase:

```
Symbol Table = Nombres → Bindings
                       + Info de tipos
                       + Mutabilidad
                       + Región / propiedad (lifetime)
```

Se crea en el frontend, se enriquece a lo largo de las fases de Python, viaja
**serializada dentro del HIR (protobuf)** y se reconstruye parcialmente en C++
para el MIR. el desarollo de este enfoque permite conservar la semantica atraves de diferentes representaciones interemedias.  

## 8. Rendimiento y modularidad como ejes constantes

Dos atributos guían cada decisión del frontend:

- **Rendimiento:** el lexer tokeniza en una sola pasada, con tablas de búsqueda
  O(1) y conteo de líneas/columnas perezoso. Esta decision es esencial ya que el HIR/MIR penalizan duramente un
  frontend lento.
- **Modularidad:** el lexer y muchas de las etapas de el se  independientes orquestados por un módulo padre. cada fase tiene fronteras y errores propios. Esto facilita
  crecer (nuevos scanners, nuevas fases) sin reescribir enormes cantidades de codigo 

## 9. Errores con códigos estables

Cada fase define su jerarquía de errores con códigos estables y serializables
(`LEXxxx`, `PARxxx`, `ASTxxx`, `HIRxxx`, ...) derivados de `CompilerError`.
Permiten reportes uniformes, tests y trazabilidad a lo largo del
pipeline.

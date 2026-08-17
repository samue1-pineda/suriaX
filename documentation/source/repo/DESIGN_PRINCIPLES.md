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

## 5. Modelo de memoria: region-based + move-semantics

> **Cambio de diseño:** el modelo anterior (RAII + tipos afines + typestate) fue
> reemplazado por **memoria basada en regiones (region-based) combinada con
> move-semantics**, esto gracias a la facilidad del modelo. 

Ideas centrales:

- **Regiones (`region r { ... }`):** las asignaciones se agrupan en una región;
  al cerrarse la región, **toda** su memoria se libera de una vez (no objeto por
  objeto). Esto da liberación barata, y lifetimes claros.
- **Asociación a región (`make T in r`, `x at r`):** un valor se ubica
  explícitamente en una región concreta.
- **Move-semantics (`move x`):** la propiedad de un valor se transfiere, tras un
  `move` el origen deja de ser usable. Evita aliasing accidental y dobles
  liberaciones.
- **Punteros y nulabilidad:** `ptr T`, el operador de dirección `&` y el tipo
  nullable `T?` siguen disponibles, se pueden usar en paralelo al modelo de regiones.
- **Gestión explícita puntual:** `make` / `alloc` / `free` existen como keywords
  para casos que lo requieran, pero la vía recomendada son las regiones.

La **verificación** de este modelo (lifetimes de región, validez de un `move`,
escapes de región) la corrección semántica 
ocurre en la etapa **semántica** y, sobre todo, en el **lowering a MIR** (en C++).

## 6. Interoperabilidad con C++

C++ se integra mediante *bindings* (pybind11) y el bloque `#extern cpp{ ... }`,
cuyo cuerpo el lexer captura **crudo** (token `RAW_BLOCK`) sin tokenizarlo: el
C++ no sigue las reglas léxicas de suriaX. La compilación de ese C++ es tarea del
backend.


## 7. El sistema de tipos no es una fase

Un aclaracion importante: el *type system* **no es una caja en el
pipeline**, sino un servicio que opera sobre varias representaciones (AST,
AST-tipado, semántica) y, en el modelo de regiones, también informa el lowering
a MIR (donde se comprueban lifetimes y moves).

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

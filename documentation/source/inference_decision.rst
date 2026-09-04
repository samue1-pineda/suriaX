.. _decision-inferencia:

Lo que no hace falta adivinar
==============================

*Hindley-Milner, duck typing y por qué suriaX hoy no quiere ninguno de los dos*

Este documento no describe nada que exista: es el registro de una decisión
sobre lo que **no** se va a construir todavía, y de qué habría que ver para
cambiarla. Para el sistema de tipos que sí hay, ver :doc:`type_system`.

Las dos preguntas se hacen juntas y son distintas. *Duck typing* es sobre
**qué hace iguales a dos tipos**; Hindley-Milner es sobre **quién escribe las
anotaciones**. La primera está cerrada por la arquitectura; la segunda no, y
por eso ocupa la mayor parte de este texto.

.. _decision-duck:

Duck typing: la puerta ya está cerrada
---------------------------------------

``DESIGN_PRINCIPLES.md`` §4 dice que el tipado es **nominal**: la identidad de
un tipo viene de su nombre, no de su forma. Duck typing dice exactamente lo
contrario. No es una preferencia que se pueda revisar sin tocar nada — es la
suposición sobre la que están construidas tres piezas del compilador:

Despacho de hooks
   La tabla de hooks se indexa por la terna ``(nombre del tipo dueño, clase,
   nombre)``. Un tipo estructural no tiene nombre bajo el que registrarse, así
   que ``print(x)`` no tendría a qué preguntarle qué hacer.

Tabla de conversiones
   ``SymbolTable.casts`` tiene por clave el par ``(origen, destino)`` de
   ``Type``, que es un dataclass *frozen* y hashable. Dos tipos estructurales
   iguales tendrían que colapsar a la misma clave, y dos "formas compatibles
   pero no iguales" a claves distintas — la relación deja de ser una igualdad
   y una tabla hash deja de servir.

Pool de tipos del HIR
   El HIR v2 deduplica tipos por identidad para que el ``.phir`` no repita el
   mismo ``Type`` decenas de miles de veces. La deduplicación estructural es
   la que hay; lo que se perdería es el *nombre*, que es justo lo que el
   intérprete y el backend usan para volver a enlazar los hooks.

Hay además una razón de destino: suriaX compila por delante a una VM/JIT
(``ROADMAP.md``). Duck typing empuja el despacho a ejecución o exige
monomorfizar el programa entero.

Y hay una razón mejor: **lo que se suele querer de duck typing, suriaX ya lo
tiene con otro nombre.** "Que valga cualquier cosa que sepa hacer *esto*" es
un :ref:`trait <traits>` — una obligación estructural, verificada
nominalmente:

.. code-block:: srcx
   :class: fragmento

   @trait { fn __len__(self ptr s) -> int; } Medible;

   @impl(Medible) struct { int n; } Bolsa;

La diferencia con duck typing no es la expresividad: es **cuándo se entera el
programa** de que el tipo no cumplía. Con el trait, al compilar y señalando la
declaración; con duck typing, al ejecutar y señalando la llamada.

.. _decision-hm:

Hindley-Milner: la mitad que sobra y la que falta
--------------------------------------------------

Aquí la respuesta no es "no encaja" sino **"hoy pagaría por algo que suriaX no
usa"**, y conviene ser preciso sobre qué es HM, porque no es sinónimo de
"inferencia de tipos".

HM completo trae cuatro cosas: variables de tipo con unificación, *tipos
principales* (cada expresión tiene un tipo más general y es único),
*let-polymorphism* (generalizar en cada binding) y el *occurs check*. Su
propuesta de valor es exactamente **las anotaciones que no escribes**.

Y ahí está el problema: en suriaX las anotaciones son **obligatorias**. Un
binding o un parámetro sin tipo escrito es un error, por decisión de diseño
(``DESIGN_PRINCIPLES.md`` §4), y es la misma decisión que hace que el lenguaje
se pueda leer sin ejecutar el compilador en la cabeza. Con esa regla en pie,
HM completo llega a un lenguaje donde ya no queda casi nada que inferir.

Lo que sí falta, y es una sola cosa
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Los :ref:`genéricos <genericos>` existen y se instancian escribiendo sus
argumentos. Lo que todavía no existe son los genéricos de **función**, y ahí
sí hay un hueco real:

.. code-block:: text

   var Vector<int> v = vec.make(6);     // ¿de dónde sale la T de 'make'?

Resolverlo pide una cosa muy concreta: **unificar el tipo de retorno declarado
con el tipo esperado en esa posición**. Eso es un fragmento diminuto de HM —
unificación local contra un tipo esperado, sin generalización, sin tipos
principales y sin let-polymorphism. Se puede tener sin traer el resto, y es lo
único que hoy se echa en falta.

Lo que costaría el resto
~~~~~~~~~~~~~~~~~~~~~~~~~

Tres costes, y el tercero es el que decide:

``Type`` dejaría de ser una clave
   Es ``frozen`` y hashable, y se usa como clave en la tabla de conversiones y
   en el pool de tipos del HIR. Una variable de tipo con *union-find* es
   mutable por definición: o se resuelven todas antes de emitir (posible, pero
   entonces el HIR nunca las ve y no eran del sistema de tipos "de verdad"), o
   el esquema del HIR cambia.

Un motor de unificación es infraestructura, no una función
   Sustituciones, propagación, y los diagnósticos correspondientes. La
   arquitectura ya reserva el sitio —``type_service.py`` existe para que la
   implementación se pueda reemplazar sin tocar a ningún llamador— así que el
   coste es real pero está acotado y previsto.

El contrato de la fase se invertiría
   Este es el importante. Hoy la Semántica promete **cero falsos positivos**:
   lo que no sabe, lo deja pasar (``type_service.es_desconocido``). HM no
   tiene ese modo — unifica o falla. Adoptarlo convierte cada hueco actual del
   frontend en un error reportado al usuario, de golpe y sin gradualidad. No
   es un problema del algoritmo; es que la migración no se puede hacer por
   partes.

.. _decision-inferencia-final:

La decisión
------------

**suriaX no va a tener inferencia de tipos.** Ni Hindley-Milner, ni una
versión recortada, ni duck typing. No es un "todavía no": es la forma que el
lenguaje elige tener.

El argumento no es que la inferencia sea mala, sino que aquí **compra poco y
cuesta permanentemente**. Compra poco porque las anotaciones son obligatorias
por diseño y no van a dejar de serlo, así que no hay un cuerpo de anotaciones
que ahorrar. Cuesta permanentemente porque un motor de unificación no es una
función que se escribe una vez: es una pieza que toda regla de tipos futura
tiene que respetar, y cada característica nueva del lenguaje pasa a costar
"además, cómo unifica".

Y hay un tercer coste que es el que decide, porque no se paga en líneas sino
en el carácter del compilador: la Semántica promete hoy **cero falsos
positivos** —lo que no sabe, lo deja pasar. La inferencia no tiene ese modo:
unifica o falla. Adoptarla convierte cada hueco actual del frontend en un
error reportado al usuario, de golpe, sin una migración gradual posible.

.. admonition:: El principio detrás
   :class: important

   **Menos complejidad, mejores resultados.** Un compilador que se entiende
   entero es más fácil de hacer correcto que uno que infiere bien. Escribir el
   tipo es barato para quien escribe el programa y elimina una fase completa
   para quien escribe el compilador.

Lo que se hace en su lugar
~~~~~~~~~~~~~~~~~~~~~~~~~~~

Todo lo que la inferencia habría resuelto se resuelve **escribiéndolo**:

* el tipo de un binding y de un parámetro: anotados, siempre;
* los argumentos de un genérico: ``Vector<int>``, en la anotación y en el
  literal;
* los de una llamada genérica: ``vec.make<int>(6)`` — salvo cuando el
  parámetro aparece en un argumento y se deduce de él;
* convertir entre tipos: ``cast<T>(x)``, nunca implícito — salvo un literal
  con :ref:`rango comprobado <rango-literal>`, que es la única excepción y
  está acotada.

Y donde el compilador de verdad no sabe el tipo —el valor de un ``catch`` sin
filtro—, la respuesta no es inferirlo: es decir que es **desconocido** y
tratarlo como tal.

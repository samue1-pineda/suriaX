.. _decision-memoria:

Dejando las arenas movedizas sin dueño
=======================================

*Por qué suriaX abandona la gestión de memoria por regiones —* **v0.2.0**

Hasta la versión 0.1.4, suriaX declaraba un modelo de memoria **basado en
regiones** (*region-based memory management*, RBMM) combinado con
move-semantics. Este documento explica por qué ese modelo se retira, qué lo
reemplaza y qué se gana y se pierde en el cambio.

No es un documento de referencia: es el registro de una decisión. Para saber
cómo se gestiona la memoria hoy, ver :ref:`modelo-memoria`.

.. _decision-que-prometia:

Lo que RBMM prometía
---------------------

El modelo era atractivo, y sigue siéndolo en abstracto. Una **región** es un
bloque de memoria con nombre y con un alcance léxico:

.. code-block:: text

   region r {
       Nodo ptr n = make Nodo in r;
       procesar(n);
   }                                 // aquí muere TODA la región, de golpe

Sus tres promesas eran reales:

Liberación en bloque
   No se libera objeto por objeto. Al cerrar el bloque cae la región entera,
   en una operación, sin recorrer nada. Para un compilador —que asigna miles
   de nodos de AST y los descarta juntos— es exactamente el patrón correcto.

Nada que recordar
   El programador no escribe una sola liberación. La estructura del código
   *es* la estructura de la memoria.

Enseñable
   Una región se dibuja en un pizarrón. Para un lenguaje cuyo propósito es
   que se **vea** lo que hace el compilador, eso pesa.

La sintaxis llegó a estar completa: modificadores componibles
(``shrd``, ``mutable``, ``na``), colocación (``make T in r``, ``expr at r``),
transferencia entre regiones (``move region a -> region b``) y control manual
del ciclo de vida (``new(region r)``, ``delete(region r)``).

.. _decision-por-que-no:

Por qué no se pudo pagar
-------------------------

El costo no estaba donde uno lo buscaría primero. No fue el análisis de
escape, ni el rendimiento: fue **cuánto lenguaje ocupaba el modelo**.

Lo que costaba en vocabulario
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

suriaX tiene una filosofía fundacional —**libsrX**— que dice reservar pocas
palabras y delegar el resto en librerías. No hay ``print`` en el lenguaje: hay
una librería que lo publica. Contra esa regla, el modelo por regiones pedía:

.. table::
   :widths: auto

   ==================================  =====================================
   Recurso del lenguaje                Lo que se llevaban las regiones
   ==================================  =====================================
   Palabras reservadas                 ``region``, ``shrd``, ``na``, ``in``,
                                       ``at``, ``new``, ``delete``, ``make``
                                       — **8 de 50**, el 16 %
   Hooks del vocabulario fijo          ``__make__``, cuyo único disparador
                                       era ``make T in r``
   Modificadores componibles           tres, con orden libre entre sí
   ==================================  =====================================

Un sexto del vocabulario reservado del lenguaje, y un hook intrínseco entero,
dedicados a **un** subsistema. Para un lenguaje cuyo argumento de venta es que
reserva poco, eso no es un detalle de presupuesto: es una contradicción con su
propia premisa.

Lo que costaba en los contratos
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

El problema se agrava donde el modelo toca a los **traits**. Un trait
verifica firmas sustituyendo el placeholder ``self`` por el tipo que
implementa, recursivamente a través de ``ptr``, ``?`` y ``error``
(``semantic/traits.py``). Todo lo que el modelo de memoria meta **dentro del
tipo** se propaga por ahí: si un tipo carga su región, entonces cada firma de
trait tiene que ser polimórfica en regiones para que dos tipos alojados en
regiones distintas puedan implementar el mismo contrato.

Es la misma presión, un nivel más abajo: las regiones no se quedaban en su
subsistema. Empujaban hacia afuera —al léxico, a los hooks, a los traits— y
cada empujón pedía una vuelta de tuerca más en un lenguaje que no estaba
construido para darla.

Lo que costaba en el sistema de tipos
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Esto era, en comparación, lo de menos — pero el ROADMAP lo venía admitiendo
desde la fase 3:

   *Type-system óptimo para region-based + move-semantics:* **todavía no
   definido**

Verificar que ninguna referencia sobreviva a su región (*no-escape*) exige que
las regiones aparezcan en el tipo de cada función que las toca: *polimorfismo
de región*, con un sistema de efectos detrás. Es la complejidad que hizo
pesado a Cyclone, el lenguaje que llevó RBMM más lejos que nadie.

Y mientras tanto la verificación se fue difiriendo:

* el escape **inter-función** quedó diferido al MIR, un backend que todavía no
  existe (fase 6, sin empezar);
* el HIR v1 ya **rechazaba** ``region``, ``shrd``, ``make T in r`` y ``x at r``
  con ``HIR005``, y el esquema v2 dejó sus tags en ``reserved``;
* el runtime se construyó explícitamente **sin RBMM**;
* las arenas por región seguían sin implementar.

La sintaxis existía en el frontend y **ninguna** de las capas de abajo la
había implementado nunca. No era una funcionalidad a medias: era una que nunca
empezó, ocupando el 16 % del vocabulario mientras tanto.

.. _decision-argumento:

El argumento que decidió
-------------------------

Se podría haber pagado el pagaré: definir el polimorfismo de región, escribir
el análisis de escape, terminar el MIR. Lo que inclinó la decisión no fue el
costo, sino **cómo se comporta cada modelo mientras está incompleto**.

.. table::
   :widths: auto

   ==========  ====================================================
   Modelo      Cómo se comporta MIENTRAS le falta su verificador
   ==========  ====================================================
   Ownership   Es **seguro**. Si la única forma de llevar un valor a
               otro sitio es ``move``, nunca hay dos dueños. Resulta
               restrictivo —cuesta escribir ciertos programas— pero
               ninguno de los que compilan está mal.
   RBMM        Es **inseguro**. Una referencia sobrevive a su
               región, queda colgante, y el compilador no dice nada.
               El programa compila y está mal.
   ==========  ====================================================

Esa asimetría es la decisión completa. **Ownership degrada a restrictivo;
RBMM degrada a inseguro.** Un modelo que se puede entregar a medias y otro
que no.

Para un proyecto cuyo público es educativo, la diferencia es todavía más
grande: un lenguaje que rechaza un programa válido enseña algo (le muestra al
estudiante dónde está la regla); un lenguaje que acepta un programa con un
puntero colgante le enseña lo contrario de lo que quería enseñar.

.. _decision-reemplazo:

Qué lo reemplaza
-----------------

**Ownership + drop + arenas explícitas**, con *reference counting* como
extensión futura. La referencia completa está en :ref:`modelo-memoria`; en
resumen:

Ownership
   Cada valor tiene un dueño único; ``move`` transfiere la propiedad y deja
   inválido el origen.

Drop
   Al cerrar el ámbito que posee un valor, el compilador invoca su
   destructor. ``free`` sigue existiendo para destruir antes de tiempo.

Arenas
   Son un **tipo de librería**, no una construcción del lenguaje: un valor que
   reserva un bloque grande y lo libera entero cuando su dueño lo suelta.

Lo notable de la sustitución es cuánto **ya estaba construido**:
``move`` con su verificación de uso-tras-move y doble-move,
``free`` con detección de uso-tras-liberación en ejecución,
punteros con mutabilidad resuelta y el hook ``__free__`` con exactamente la
firma que necesita un destructor. El lenguaje ya tenía move-semantics
funcionando **sin el modelo de propiedad que le da sentido**: ownership no
agrega un concepto nuevo, le pone nombre al que ya estaba operando.

Y las arenas conservan la promesa que hacía atractivo a RBMM —liberar mucho de
una vez— sin ninguna de sus consecuencias: no necesitan sintaxis, no aparecen
en las firmas, no exigen análisis de escape. La diferencia es que ahora una
arena es un valor con dueño, y el dueño sí se verifica.

.. _decision-perdidas:

Qué se pierde
--------------

Conviene ser explícito, porque no todo el cambio es ganancia:

* **La liberación en bloque deja de ser una garantía del lenguaje** y pasa a
  ser una propiedad de una librería. Quien quiera el patrón tiene que usar una
  arena a propósito; antes lo obtenía por escribir un bloque.
* **Se pierde la sintaxis dedicada.** ``region r { ... }`` se leía muy bien.
  Una arena de librería es una llamada más.
* **Los préstamos quedan verificados en ejecución** por ahora
  (``RT001``/``RT002``/``RT003``), no al compilar. La verificación estática se
  hará sobre el MIR, igual que se planeaba para el escape de regiones — pero
  con la diferencia de que hasta entonces el modelo es seguro, no solo
  incompleto.
* **Desaparecen palabras reservadas**: ``region``, ``shrd``, ``na``, ``in``,
  ``at``, ``new`` y ``delete``. Cualquier programa que las use deja de
  compilar.

.. note::

   Los tags del esquema HIR siguen en ``reserved``. Si en el futuro el sistema
   de tipos crece hasta poder sostener regiones con seguridad, reintroducirlas
   no rompería el formato. La decisión de hoy es sobre lo que se puede
   sostener hoy, no sobre lo que es posible en abstracto.

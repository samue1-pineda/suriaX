6. HIR: el puente entre fases
==============================

El **HIR** (*high-level intermediate representation*) es la frontera del
compilador: todo lo que el frontend sabe de un programa se serializa una vez,
y de ahí en adelante cada backend lee lo mismo. Un archivo ``.phir`` es esa
serialización.

.. code-block:: text

   .srcx  →  frontend (Python)  →  .phir  →  intérprete
                                          →  backend C++   (MIR → VM / LLVM)
                                          →  target web    (WIR → WebAssembly)

Está escrito en **protobuf**, que aporta tres cosas concretas: un formato
binario compacto, un esquema versionado y lectores en cualquier lenguaje sin
reimplementar el frontend.

.. _que-viaja:

Qué contiene un ``.phir``
--------------------------

.. table::
   :widths: auto

   ====================  =====================================================
   Campo                 Contenido
   ====================  =====================================================
   ``schema_version``    Versión del **esquema**, no del compilador.
   ``source_file``       Ruta del fuente, para los diagnósticos.
   ``symbols``           Tabla de símbolos global: tipos, valores, hooks y
                         conversiones.
   ``items``             El programa validado, en orden.
   ``libraries``         Las unidades importadas, por alias y archivo.
   ``types``             **Pool de tipos**: cada tipo distinto una sola vez;
                         los nodos lo referencian por índice.
   ====================  =====================================================

Cada expresión viaja con **su tipo ya resuelto** y cada nodo con **su línea y
columna**. Un backend nunca tiene que inferir un tipo ni adivinar una
posición: si el HIR no lo trae, no existe.

.. _pool-de-tipos:

El pool de tipos (esquema 2)
-----------------------------

Que cada expresión lleve su tipo no significa que cada expresión lleve una
*copia* de él. En un programa de 47 000 tokens el mismo ``int`` aparecía
21 065 veces sobre **43 formas distintas** — un 20 % del archivo dedicado a
repetir cuarenta y tres cosas.

Desde el esquema 2 los tipos viven una sola vez en ``Module.types`` y los
nodos guardan un índice (``type_id``); el ``0`` significa "sin tipo anotado".
Resolverlo es un acceso a lista, así que el lector no paga nada: se midió, y
el tiempo de lectura no cambió. Lo que sí cambió es el archivo (un 10 % más
pequeño) y el tiempo de emisión (un 16 % menos, porque el emisor construye
veinte mil submensajes menos).

La tabla de símbolos **no** participa del pool a propósito: es el 4 % de los
bytes y la parte que una persona lee cuando inspecciona un ``.phir``.

El pool no se ve al leer el HIR: ``--hir-pretty`` lo resuelve y escribe
``Punto ptr mutable``, no ``#7``.

.. _reproducible:

El mismo programa, los mismos bytes
------------------------------------

Un ``.phir`` es **reproducible**: compilar dos veces el mismo fuente produce
artefactos idénticos, en cualquier máquina. No siempre fue así — las entradas
de un ``map`` de protobuf se escriben en un orden que la especificación no
fija, y el orden real lo decidía la tabla *hash* del proceso.

Importa más de lo que parece: sin esa garantía no se pueden comparar
artefactos, ni cachear un build por su *hash*, ni demostrar que un cambio del
compilador no alteró la salida.

.. _una-unidad-un-phir:

Una unidad, un archivo
-----------------------

Cada ``.srcx`` y cada ``.libsrx`` compila a **su propio** ``.phir``. El módulo
principal no reembebe el contenido de sus librerías: las **referencia** por
alias y archivo.

.. code-block:: console

   $ python V0/main.py programa.srcx --emit-hir
   HIR (1.4 kB) generado en: dumps/programa.srcx.phir
     unidad 'IO.stdp':  924 bytes -> dumps/IO.stdp.phir
     unidad 'IO':        75 bytes -> dumps/IO.phir

El consumidor resuelve cada referencia **relativa al archivo que la
referencia** y liga las unidades. La consecuencia práctica: los ``.phir``
viajan juntos, como los objetos de un enlazado.

.. _versionado:

Versionado y fail-fast
-----------------------

``schema_version`` se compara **antes de tocar el contenido**. Un lector que
encuentra una versión que no conoce se detiene con un mensaje accionable, en
vez de interpretar bytes con un layout desconocido y fallar más tarde en otro
sitio.

Es la misma disciplina en los tres lectores: el intérprete, el target web y el
backend C++ comparten el criterio, no solo el formato.

.. _hooks-hir:

Cómo viajan los hooks
----------------------

Un hook está en dos sitios a la vez, y a propósito:

En la tabla
   ``symbols.hooks`` guarda la entrada completa: tipo dueño, clase de hook y
   el símbolo con su firma.

En el nodo
   El nodo que lo dispara (una llamada, un ``free``, un ``sizeof``) lleva una
   **referencia** ``(dueño, clase)``, no una copia del símbolo.

Así el símbolo no se duplica en cada uso y el lector reconstruye el índice en
una pasada. Las conversiones ``__cast__`` viajan igual: en una lista, con el
par origen-destino derivable de cada firma.

.. _alcance-hir:

Alcance de la versión 1
------------------------

El HIR v1 transporta el lenguaje completo salvo el modelo de regiones
(``region``, ``new``/``delete``, ``in region``, ``x at r``). El emisor lo
rechaza con ``HIR005`` en su posición, y los identificadores de esos campos
quedan **reservados** en el esquema, de modo que reintroducirlos no romperá a
ningún lector existente.

Move-semantics **sí** viaja: la sentencia ``move`` y la línea del movimiento
anotada en el símbolo, para que el runtime haga cumplir lo que el análisis
estático conservador no ve.

.. _ver-el-hir:

Ver el HIR
-----------

Dos vistas, para dos preguntas distintas. Para leer el **programa**:

.. code-block:: console

   $ python V0/main.py programa.srcx --hir-pretty
   $ cat dumps/programa.srcx.phir.pretty

Para depurar el **formato** (qué tag lleva qué), el árbol crudo del protobuf:

.. code-block:: console

   $ python V0/main.py programa.srcx --emit-hir --hir-text
   $ cat dumps/programa.srcx.phir.txt

Y sobre un ``.phir`` que ya existe, sin recompilar:

.. code-block:: console

   $ python runtime/interpreter/main.py dumps/programa.srcx.phir --pretty

O directamente por pantalla, sin escribir archivos:

.. code-block:: console

   $ python V0/main.py programa.srcx --emit-stage hir

Un fragmento del resultado:

.. code-block:: text

   schema_version: 2
   source_file: "programa.srcx"
   types { }                     # 0 = "sin tipo"
   types { kind: INT }           # 1
   items {
     ln: 3
     col: 1
     function {
       name: "suma"
       params { name: "a" type_id: 1 }
       params { name: "b" type_id: 1 }
       return_type_id: 1
       body {
         statements {
           ln: 4
           return_stmt {
             value {
               type_id: 1
               binary { op: "+" ... }
             }
           }
         }
       }
     }
   }

Ese es el *formato*. Para leer el **programa** —una línea por sentencia, con
los tipos ya resueltos a su nombre— está ``--hir-pretty``:

.. code-block:: text

   unit programa.srcx   schema 2 · 1 items · 1 símbolos · 1 tipos

   types
     #1   int

   fn suma(int a, int b) -> int                                    @3:1
     return (a:int + b:int):int                                    @4:5

.. _el-phir-como-entrada:

El ``.phir`` como entrada
--------------------------

Un ``.phir`` es autosuficiente: no necesita el fuente para ejecutarse ni para
compilarse a otro target.

.. code-block:: console

   $ node web/main.ts dumps/programa.srcx.phir --run

Esa propiedad es la que permite que el playground compile en el servidor y
ejecute en el navegador, y la que hace comparables al intérprete y al
WebAssembly: mismo archivo, distintos ejecutores, misma salida.

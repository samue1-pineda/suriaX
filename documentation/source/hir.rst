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
   ====================  =====================================================

Cada expresión viaja con **su tipo ya resuelto** y cada nodo con **su línea y
columna**. Un backend nunca tiene que inferir un tipo ni adivinar una
posición: si el HIR no lo trae, no existe.

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

En texto, junto al binario:

.. code-block:: console

   $ python V0/main.py programa.srcx --emit-hir --hir-text
   $ cat dumps/programa.srcx.phir.txt

O directamente por pantalla, sin escribir archivos:

.. code-block:: console

   $ python V0/main.py programa.srcx --emit-stage hir

Un fragmento del resultado:

.. code-block:: text

   schema_version: 1
   source_file: "programa.srcx"
   items {
     ln: 3
     col: 1
     function {
       name: "suma"
       params { type { kind: INT } name: "a" }
       params { type { kind: INT } name: "b" }
       return_type { kind: INT }
       body {
         statements {
           ln: 4
           return_stmt {
             value {
               restype { kind: INT }
               binary { op: "+" ... }
             }
           }
         }
       }
     }
   }

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

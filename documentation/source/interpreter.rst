7. Intérprete
==============

El intérprete ejecuta un ``.phir`` recorriendo su árbol (*tree-walk*). Es el
consumidor de referencia del HIR: cuando hay que decidir qué significa una
construcción, lo que hace el intérprete es la respuesta.

.. code-block:: console

   $ python V0/main.py programa.srcx --run

.. _imagen:

La imagen ejecutable
---------------------

Antes de ejecutar nada, el *loader* monta una **imagen**: el ``.phir``
principal más todas las unidades que referencia, cargadas una sola vez y
ligadas entre sí.

Sobre esa imagen se construyen los índices que el evaluador consulta en tiempo
constante:

.. table::
   :widths: auto

   ===================  ====================================================
   Índice               Clave
   ===================  ====================================================
   Funciones            nombre
   Hooks                (tipo dueño, clase de hook)
   Conversiones         (tipo origen, tipo destino)
   Métodos dunder       (tipo dueño, nombre)
   Items de enum        (enum, item)
   ===================  ====================================================

Si una unidad referenciada no está junto al archivo principal, el loader se
detiene diciendo cuál falta y de dónde venía la referencia.

.. _ejecucion:

Ejecución
----------

El punto de entrada es ``main``. Las sentencias de nivel de módulo se ejecutan
**antes**, en orden de aparición, de modo que un programa sin ``main`` que solo
tiene código suelto también hace algo.

.. code-block:: srcx

   #from io #import stdp

   stdp.println("esto se ejecuta primero");

   fn main() -> int {
       stdp.println("y esto después");
       return 0;
   }

El valor que devuelve ``main`` es el código de salida del proceso.

.. _memoria-runtime:

Modelo de memoria
------------------

Los punteros no son una simulación con diccionarios: hay un administrador de
memoria con celdas reales, escrito en C++, y el intérprete lo usa a través de
*bindings*.

Cada celda tiene una **máquina de estados**:

.. code-block:: text

   crear ──▶ LIVE ──move──▶ MOVED
              │
              └──free──▶ FREED

Leer una celda movida es ``RT001``; usar una liberada, ``RT002``; liberar dos
veces, ``RT003``. Los tres traen la línea y la columna de la operación que los
provocó, porque el HIR las transporta.

El mismo core lo enlazarán la VM de bytecode y el backend LLVM: la lógica de
memoria vive en un solo sitio y es agnóstica del target.

.. table::
   :widths: auto

   =========================  ===============================================
   Variable de entorno        Efecto
   =========================  ===============================================
   ``SURIAX_NATIVE_MEM=1``    Exige el backend nativo; error si no carga.
   ``SURIAX_NATIVE_MEM=0``    Fuerza la implementación en Python puro.
   =========================  ===============================================

Sin la variable, se usa el nativo si está compilado y se cae al de Python si
no. Las dos implementaciones tienen la misma interfaz y la suite comprueba que
den resultados idénticos.

.. _despacho:

Despacho de hooks
------------------

Cuando el evaluador encuentra una llamada con un hook enlazado, no busca nada:
la referencia ``(dueño, clase)`` que trae el nodo se resuelve contra el índice
de la imagen y ejecuta el cuerpo, con los globales de **su** unidad.

.. code-block:: srcx

   struct { str texto; int largo; } Cadena;

   hook fn __print__(Cadena ptr c) -> void {
       __write__(c.texto);
   }

   fn main() -> int {
       var Cadena c = Cadena{ texto: "hola", largo: 4 };
       print(&c);        // despacha a __print__
       return len(&c);   // despacha a __len__ si está declarado
   }

.. _trazas:

Trazas
-------

.. code-block:: console

   $ python V0/main.py programa.srcx --run --trace-exec
   $ python V0/main.py programa.srcx --run --trace-memory

``--trace-exec`` muestra llamadas y retornos anidados; ``--trace-memory``
muestra cada operación sobre celdas (``&``, ``move``, ``free``) con su
posición. Con ``--debug``, ambas trazas se acumulan en el reporte en vez de
imprimirse.

.. _bloques-test:

Bloques ``test``
-----------------

Un bloque ``test`` es una declaración de primer nivel, no una función: no se
invoca ni tiene firma.

.. code-block:: srcx

   fn doble(int x) -> int { return x + x; }

   test "doble multiplica por dos" {
       var int r = doble(21);
   }

Viajan en el HIR y el intérprete los reconoce como unidades ejecutables
separadas del programa: una compilación normal los transporta y los valida,
pero no los ejecuta junto a ``main``.

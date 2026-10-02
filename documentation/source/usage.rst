1. Instalación y uso
=====================

.. _requisitos:

Requisitos
-----------

El compilador de suriaX es Python puro: el frontend, el HIR (que se serializa
con un codec propio) y el intérprete corren solo con la biblioteca estándar.
El resto es opcional y solo hace falta para el componente que lo usa.

.. list-table:: Dependencias por componente
   :header-rows: 1
   :widths: 25 35 40

   * - Componente
     - Necesario para
     - Cómo se instala
   * - Python 3.10+
     - compilar, emitir el HIR y ejecutar (``--run``)
     - ``python --version``
   * - ``pyyaml``
     - leer un ``.suriaX_config.yaml`` propio y ``--init-config``
     - ``pip install pyyaml``
   * - ``pybind11`` + CMake
     - memoria nativa del intérprete (opcional: sin ella corre en Python)
     - ``pip install pybind11``
   * - compilador de C++ (``g++``/``clang++``)
     - ejecutar programas con ``#extern cpp{}``
     - el del sistema
   * - CMake 3.20+ y un compilador de C++20
     - la VM ``suriax-hir`` (MIR y VM); no usa protobuf
     - el del sistema; en Windows, MSVC (ver ``how_to_run.md``)
   * - Node 22+
     - target web (WebAssembly)
     - gestor de paquetes del sistema
   * - ``protobuf`` (pip) + ``protoc``
     - solo la prueba cruzada del codec del HIR
     - ``pip install protobuf``

LLVM no se usa ni se detecta: el target nativo es una VM, no LLVM.

Para comprobar qué hay disponible en la máquina actual:

.. code-block:: console

   $ python V0/main.py --check

.. _instalacion:

Instalación
------------

Desde el repositorio
~~~~~~~~~~~~~~~~~~~~~

.. code-block:: console

   $ git clone https://github.com/samue1-pineda/suriaX.git
   $ cd suriaX
   $ pip install -r requirements.txt    # opcional: nada de esto hace falta para compilar
   $ pip install -e .                   # opcional: instala el comando 'suri'
   $ suri hola.srcx                     # = python main.py hola.srcx (compila y ejecuta)

Desde un *release*
~~~~~~~~~~~~~~~~~~~

Descarga el paquete de tu plataforma en la
`página de releases <https://github.com/samue1-pineda/suriaX/releases>`_,
descomprímelo y ejecuta ``pip install -r requirements.txt`` dentro.

Memoria nativa (opcional)
~~~~~~~~~~~~~~~~~~~~~~~~~~

El intérprete usa un administrador de memoria escrito en C++ cuando está
compilado, y cae a la implementación en Python puro cuando no. Para
compilarlo:

.. code-block:: console

   $ cmake -S . -B build
   $ cmake --build build -j

El ``.so`` queda en ``runtime/logic_mem/build/``, que es donde el runtime lo
busca. Con ``SURIAX_NATIVE_MEM=0`` se fuerza el backend de Python y con
``SURIAX_NATIVE_MEM=1`` se exige el nativo (error si no carga).

.. _hola-mundo:

Tu primer programa
-------------------

Crea ``hola.srcx``:

.. code-block:: srcx

   #from io #import stdp

   fn main() -> int {
       stdp.println("hola, suriaX");
       return 0;
   }

Y ejecútalo:

.. code-block:: console

   $ python V0/main.py hola.srcx --run
   frontend OK: 23 tokens, 2 items, 2 simbolos globales, 0 hooks, 0 casts
   HIR (306 bytes) generado en: dumps/hola.srcx.phir
     unidad 'IO.stdpf': 349 bytes -> dumps/IO.stdpf.phir
     unidad 'IO.stdp': 956 bytes -> dumps/IO.stdp.phir
     unidad 'IO': 145 bytes -> dumps/IO.phir
   hola, suriaX

``--run`` emite el HIR y lo ejecuta en el motor que pide el ``target`` del
``.suriaX_config.yaml``: ``native`` (el defecto) es la VM compilada
(``suriax-hir``) e ``interp`` el intérprete; ``--run compiler`` y
``--run interpreter`` lo fuerzan. Si la VM no está construida, se ejecuta en
el intérprete con un aviso. El valor que devuelve ``main`` es el código de
salida del compilador, así que ``echo $?`` lo muestra.

.. important::
   El fuente tiene que estar donde el linker de librerías pueda encontrar
   ``lib/``: busca junto al archivo y en ``<directorio>/lib``. Compilar desde
   la raíz del repositorio siempre funciona.

.. _viendo-las-fases:

Ver qué entrega cada fase
--------------------------

Es el objetivo del proyecto, y hay dos formas de pedirlo.

Desde la línea de comandos con ``--emit-stage``:

.. code-block:: console

   $ python V0/main.py hola.srcx --emit-stage lexer
   $ python V0/main.py hola.srcx --emit-stage ast
   $ python V0/main.py hola.srcx --emit-stage sem
   $ python V0/main.py hola.srcx --emit-stage hir
   $ python V0/main.py hola.srcx --emit-stage desugar

``desugar`` es el HIR legible con el AZÚCAR señalado: encima de cada
sentencia, la línea del fuente como se escribió, y en cada construcción que
el compilador reescribe (``x += v``, ``x++``, ``with``, ``.campo``, la
declaración de un vector, el ``move`` de un ``throw``, el ``cast`` de un
literal) en qué la convirtió.

Desde el propio archivo, con la directiva ``#test`` en la primera línea: el
compilador vuelca esa fase y termina, sin seguir el pipeline.

.. code-block:: srcx

   #test lexer

   int x = 1;

Las fases disponibles son ``lexer``, ``parser``, ``ast``, ``sem`` y ``hir``.

.. _cli:

Referencia de la línea de comandos
-----------------------------------

.. code-block:: text

   python V0/main.py [archivo.srcx] [opciones]

Volcados
~~~~~~~~~

.. list-table::
   :header-rows: 1
   :widths: 35 65

   * - Opción
     - Qué produce
   * - ``--emit-tokens [ARCHIVO]``
     - El arreglo de tokens como texto.
   * - ``--emit-ast-json [ARCHIVO]``
     - El AST-tipado en JSON, con el tipo de cada expresión.
   * - ``--emit-hir [ARCHIVO]``
     - El HIR serializado (``.phir``) tras una compilación limpia.
   * - ``--hir-text``
     - Además del binario, el **árbol crudo** del protobuf (``.phir.txt``):
       para depurar el *formato*, no para leer el programa.
   * - ``--hir-pretty [ARCHIVO]``
     - La vista **legible** del HIR (``.phir.pretty``): una línea por
       sentencia, cada expresión con su tipo resuelto, los hooks que enlazó
       la Semántica y la posición del fuente al margen. Es la forma de ver
       *qué le llegó al intérprete*.
   * - ``--dump-symbols-table [ARCHIVO]``
     - La tabla de símbolos como diagrama de clases UML (Mermaid).
   * - ``--emit-stage FASE``
     - Vuelca UNA fase a la salida estándar, sin tocar el archivo.

Sin ``ARCHIVO``, el volcado va a ``<dumps_dir>/<fuente>.<extensión>``.

Ejecución
~~~~~~~~~~

.. table::
   :widths: auto

   ====================  ===================================================================
   Opción                Efecto
   ====================  ===================================================================
   ``--run``             Emite el HIR y lo ejecuta (en la VM o en el intérprete, según el ``target``).
   ``--trace-exec``      Traza llamadas y retornos anidados durante la ejecución.
   ``--trace-memory``    Traza las instrucciones de memoria (``&``, ``move``, ``free``).
   ``--time``            Tiempo de cada fase, en milisegundos.
   ``--debug``           Reporte completo: entorno, métricas, tokens, AST, símbolos,
                         traza y tiempos, todo en un archivo. Implica
                         ``--time`` y ``--hir-pretty``.
   ====================  ===================================================================

Integración con editores
~~~~~~~~~~~~~~~~~~~~~~~~~

.. list-table::
   :header-rows: 1
   :widths: 30 70

   * - Opción
     - Para qué
   * - ``--emit-diagnostics``
     - Todos los diagnósticos en JSON (código, mensaje, línea, columna, rango,
       fase). Sale con código 0 aunque haya errores: el cliente los lee del
       JSON, no del *exit code*.
   * - ``--emit-index``
     - Los diagnósticos **más** el índice del archivo: cada símbolo con su
       tipo, su firma (con los nombres de los parámetros), su posición, el
       comentario de encima y, si es de una librería, su archivo; cada uso de
       cada símbolo; y qué va después de un ``.`` en cada tipo. Es lo que
       necesita un editor para *hover*, ir a la definición y completar.
   * - ``--stdin``
     - Lee el fuente de la entrada estándar; el argumento de archivo sigue
       anclando la resolución de librerías. Permite analizar un buffer sin
       guardar.
   * - ``--emit-lang-info``
     - La especificación del lenguaje en JSON: palabras clave por categoría,
       tokens, directivas, hooks, códigos de error, la sintaxis para
       colorear (comentarios, escapes, literales, formato de los f-strings)
       y los *snippets* de cada construcción. Trae también
       ``compiler_version``, para que el cliente sepa contra qué compilador
       está hablando y no atribuya a un error suyo un vocabulario viejo.
   * - ``--emit-extensions``
     - Las extensiones del proyecto en JSON (HTIMS): el nombre del proyecto,
       cada hook declarado con su firma y su posición, y las líneas
       equivalentes para el ``.suriaX_config.yaml``. **No importa ni ejecuta**
       el ``.py`` del usuario: lo lee con ``ast.parse``.

Entorno
~~~~~~~~

.. table::
   :widths: auto

   ==================  ==========================================================
   Opción              Efecto
   ==================  ==========================================================
   ``--version``       Imprime ``suriaX <versión>`` y termina.
   ``--check``         Verifica las dependencias y muestra qué falta.
   ``--init-config``   Genera un ``.suriaX_config.yaml`` por defecto.
   ==================  ==========================================================

.. _configuracion:

El archivo de configuración
----------------------------

``.suriaX_config.yaml`` se busca **subiendo** desde el directorio del fuente,
así que compilar desde cualquier punto del proyecto encuentra la misma
configuración.

.. code-block:: yaml

   version: 1
   target: interp            # interp | native | web
   platform: linux
   optimization: O0
   toolchain:
     llvm_required_major: 22
     llvm_config: /usr/bin/llvm-config
     linker: /usr/bin/ld.lld
   codegen:
     triple: x86_64-pc-linux-gnu
     artifact: o
     wasm:
       enabled: false
   libraries:
     libsrx_paths:
       - ./lib
       - ./libsrx
   paths:
     output: out
   flags:
     is_web: false

Con ``target: interp`` el compilador ejecuta el programa sin necesidad de
``--run``. ``libraries.libsrx_paths`` añade directorios donde buscar las
librerías ``.libsrx``.

.. _ejecutar-en-wasm:

Ejecutar en WebAssembly
------------------------

El target web consume el mismo ``.phir``:

.. code-block:: console

   $ python V0/main.py hola.srcx --emit-hir
   $ node web/main.ts dumps/hola.srcx.phir --run
   hola, suriaX

Y genera los artefactos por separado:

.. code-block:: console

   $ node web/main.ts dumps/hola.srcx.phir \
       --emit-wasm hola.wasm --emit-wat hola.wat --emit-js hola.mjs

El módulo ``.mjs`` embebe el binario y no depende de nada: ``node hola.mjs``
o un ``<script type="module">`` lo ejecutan igual. Ver :doc:`web_target`.

.. _suite:

Ejecutar las pruebas
---------------------

.. code-block:: console

   $ python test/main.py              # todas las categorías
   $ python test/main.py unit e2e     # solo algunas

Las categorías son ``unit``, ``grammar``, ``negative_tests``, ``snapshot``,
``e2e`` y ``fuzz``. La suite incluye las pruebas del target web y una
comparación **diferencial** entre el intérprete y el WebAssembly generado.

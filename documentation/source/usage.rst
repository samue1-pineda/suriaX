1. Instalación y uso
=====================

.. _requisitos:

Requisitos
-----------

El frontend de suriaX es Python puro; el resto son opcionales y solo hacen
falta para la fase que los usa.

.. list-table:: Dependencias por fase
   :header-rows: 1
   :widths: 25 35 40

   * - Componente
     - Necesario para
     - Cómo se instala
   * - Python 3.10+
     - lexer, parser, semántica
     - ``python --version``
   * - ``pyyaml``
     - leer ``.suriaX_config.yaml``
     - ``pip install pyyaml``
   * - ``protobuf``
     - emitir el HIR (``--emit-hir``)
     - ``pip install protobuf``
   * - ``protoc``
     - generar los stubs del HIR
     - ``apt install protobuf-compiler``
   * - ``pybind11`` + CMake
     - memoria nativa del runtime
     - ``pip install pybind11``
   * - Node 22+
     - target web (WebAssembly)
     - gestor de paquetes del sistema
   * - LLVM 22
     - backend nativo
     - ``llvm-config --version``

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
   $ pip install -r requirements.txt

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
   frontend OK: 15 tokens, 2 items, 2 simbolos globales, 0 hooks, 0 casts
   HIR (312 bytes) generado en: dumps/hola.srcx.phir
   hola, suriaX

``--run`` emite el HIR y se lo entrega al intérprete **en el mismo proceso**.
El valor que devuelve ``main`` es el código de salida del compilador, así que
``echo $?`` lo muestra.

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
     - Además del binario, la vista de texto ``.phir.txt``.
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
   ``--run``             Emite el HIR y lo ejecuta con el intérprete.
   ``--trace-exec``      Traza llamadas y retornos anidados durante la ejecución.
   ``--trace-memory``    Traza las instrucciones de memoria (``&``, ``move``, ``free``).
   ``--time``            Tiempo de cada fase, en milisegundos.
   ``--debug``           Reporte completo: entorno, métricas, tokens, AST, símbolos,
                         HIR en texto, traza y tiempos, todo en un archivo.
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
   * - ``--stdin``
     - Lee el fuente de la entrada estándar; el argumento de archivo sigue
       anclando la resolución de librerías. Permite analizar un buffer sin
       guardar.
   * - ``--emit-lang-info``
     - La especificación del lenguaje en JSON: palabras clave por categoría,
       tokens, directivas, hooks y códigos de error.

Entorno
~~~~~~~~

.. table::
   :widths: auto

   ==================  ==========================================================
   Opción              Efecto
   ==================  ==========================================================
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

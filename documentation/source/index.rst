Documentación de suriaX
=======================

`suriaX <https://github.com/samue1-pineda/suriaX>`_ es un compilador cuyo
objetivo principal es que estudiantes, docentes y curiosos **vean qué entrega
cada etapa del compilador**, sin renunciar al rigor de la teoría.

.. code-block:: srcx

   #from io #import stdp

   fn main() -> int {
       stdp.println("hola, suriaX");
       return 0;
   }

.. code-block:: console

   $ python V0/main.py hola.srcx --run
   hola, suriaX

El pipeline, de principio a fin:

.. code-block:: text

   .srcx → lexer → parser → AST-tipado → semántica → HIR (protobuf)
                                                      ├→ intérprete (Python)
                                                      ├→ backend C++  → MIR → VM / LLVM
                                                      └→ target web   → WIR → WebAssembly

.. toctree::
   :maxdepth: 2
   :caption: Empezar

   usage
   examples

.. toctree::
   :maxdepth: 2
   :caption: El lenguaje

   grammar
   type_system
   libsrx

.. toctree::
   :maxdepth: 2
   :caption: Dentro del compilador

   lexical_analysis
   sintactic_analysis
   semantic_analysis
   hir
   interpreter
   web_target
   errors

.. toctree::
   :maxdepth: 1
   :caption: Diseño del proyecto

   repo/ARCHITECTURE
   repo/DESIGN_PRINCIPLES
   repo/ROADMAP
   repo/CONTRIBUTING

.. toctree::
   :maxdepth: 1
   :caption: Referencia técnica

   repo/protobuf_bridge
   repo/interpreter_internals
   repo/web_backend

Índices
-------

* :ref:`genindex`
* :ref:`search`

11. Ejemplos
=============

Programas completos, agrupados por lo que enseñan. Todos se ejecutan igual:

.. code-block:: console

   $ python V0/main.py ejemplo.srcx --run

Y todos sirven para mirar dentro del compilador, que es de lo que va el
proyecto:

.. code-block:: console

   $ python V0/main.py ejemplo.srcx --emit-tokens
   $ python V0/main.py ejemplo.srcx --emit-ast-json
   $ python V0/main.py ejemplo.srcx --dump-symbols-table
   $ python V0/main.py ejemplo.srcx --emit-hir --hir-text

.. toctree::
   :maxdepth: 2

   basics
   control
   types
   hooks
   libraries

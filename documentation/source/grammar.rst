Gramática (EBNF)
================

La gramática de suriaX se mantiene en un único archivo,
``docs/gramar/grammar.ebnf``, y describe el lenguaje que acepta el parser
(``V0/src/frontend/parser/``, y su réplica en suriaX, ``src/frontend/``).

Cómo leerla
-----------

Primero van las reglas **sintácticas**, de ``program`` hacia abajo (las
declaraciones, las sentencias, las expresiones de menor a mayor precedencia
y los tipos), y después las **léxicas**, agrupadas por categoría de token
(palabras reservadas, palabras contextuales, operadores, puntuación,
identificadores, literales, directivas y comentarios).

Se escribió a partir del parser real, regla por regla, y una prueba
(``test/unit/test_docs_al_dia.py``) comprueba que no use ninguna regla sin
definir y que nombre exactamente las palabras reservadas del lexer.

Notación::

   =        definición            |    alternativa
   { }      cero o más            [ ]  opcional
   ( )      agrupación            "x"  terminal literal
   ?...?    descripción informal de un terminal léxico

Los terminales en MAYÚSCULAS son **tipos de token**: el vocabulario completo
está en :doc:`repo/t_types` y en el :doc:`capítulo del lexer
<lexical_analysis>`; su definición ejecutable, en ``V0/include/t_types.py``.

.. tip::
   Los tokens que produce el lexer para un archivo concreto se pueden ver con
   ``python V0/main.py archivo.srcx --emit-tokens``, y el AST resultante con
   ``--emit-ast-json``. La gramática dice qué *debería* pasar; esos volcados
   dicen qué pasó.

.. literalinclude:: repo/grammar.ebnf
   :language: text
   :linenos:

.. toctree::
   :hidden:

   repo/t_types

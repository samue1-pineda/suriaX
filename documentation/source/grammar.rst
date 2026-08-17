Gramática (EBNF)
================

La gramática de suriaX se mantiene en un único archivo,
``docs/gramar/grammar.ebnf``, y es la **fuente de verdad sintáctica** del
lenguaje: el parser (``V0/src/frontend/parser/grammar/``) implementa estas
reglas, un módulo por grupo.

Cómo leerla
-----------

Cada regla lleva una marca de **estado**, porque el lenguaje avanza por
partes y una gramática sin estado engaña:

``[OK]``
   Implementada de punta a punta: el parser la reconoce, la semántica la
   valida y viaja en el HIR.

``[HIR-]``
   El parser la reconoce y la semántica la valida, pero **no cruza al HIR
   v1**: el emisor la rechaza con ``HIR005`` (hoy, todo RBMM). Se conserva en
   la gramática porque el lenguaje la define y volverá.

``[TBD]``
   Sintaxis diseñada, aún no implementada.

Notación::

   =        definición            |    alternativa
   { }      cero o más            [ ]  opcional
   ( )      agrupación            "x"  terminal literal
   ?...?    descripción informal de un terminal léxico

Los terminales son **tipos de token**: el vocabulario completo está en
:doc:`repo/t_types` y en el :doc:`capítulo del lexer <lexical_analysis>`; su
definición ejecutable, en ``V0/include/t_types.py``.

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

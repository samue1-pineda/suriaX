3. Análisis sintáctico
=======================

El parser recibe la lista de tokens del :doc:`lexer <lexical_analysis>` y
construye el **AST** (*abstract syntax tree*): el árbol que representa la
estructura del programa, sin los detalles que ya no importan (espacios,
comentarios, paréntesis de agrupación).

Estrategia
-----------

suriaX usa **descenso recursivo** para las declaraciones y las sentencias, y
un **parser de Pratt** para las expresiones.

Descenso recursivo
   Cada regla de la gramática es una función. ``parse_function_decl`` sabe
   leer una función, llama a ``parse_block``, que llama a ``parse_statement``,
   y así. El código se lee igual que la gramática: la estructura del parser
   *es* la estructura del lenguaje.

Pratt
   Las expresiones tienen precedencia y asociatividad, y escribirlas con
   descenso recursivo obliga a una función por nivel (``term`` llama a
   ``factor``, que llama a ``unary``...). Pratt asocia a cada token una
   función y una **potencia de enlace**, y resuelve la precedencia con un
   bucle. Añadir un operador es añadir una entrada a una tabla.

La organización del código sigue esa división:

.. table::
   :widths: auto

   ==============================  =========================================
   Módulo                          Responsabilidad
   ==============================  =========================================
   ``parser/cursor.py``            Avanzar, mirar y consumir tokens.
   ``parser/context.py``           Estado de la pasada y errores acumulados.
   ``parser/pratt.py``             Bucle de expresiones por precedencia.
   ``parser/precedence.py``        Potencias de enlace de cada operador.
   ``parser/expressions/nud.py``   Qué hace un token al **empezar** una expresión.
   ``parser/expressions/led.py``   Qué hace un token **dentro** de una expresión.
   ``parser/grammar/``             Una regla por módulo: funciones, structs,
                                   enums, control de flujo, directivas, tipos.
   ``parser/recovery.py``          Resincronización tras un error.
   ``parser/typed_ast.py``         Anotación de tipos sobre el AST.
   ==============================  =========================================

.. _precedencia:

Precedencia de operadores
--------------------------

De menor a mayor fuerza de enlace. Todos los binarios son asociativos por la
izquierda.

.. table::
   :widths: auto

   ======  ============================  ==========================================
   Nivel   Operadores                    Ejemplo
   ======  ============================  ==========================================
   1       ``or``                        ``a or b``
   2       ``and``                       ``a and b``
   3       ``==``  ``!=``                 ``x == y``
   4       ``<``  ``<=``  ``>``  ``>=``   ``x < y``
   5       ``+``  ``-``                   ``a + b``
   6       ``*``  ``/``                   ``a * b``
   7       ``not``  ``-``  ``&``          ``not activo``, ``-x``, ``&x``
   8       ``.``  ``(...)``  ``[...]``    ``obj.campo``, ``f(1)``, ``v[i]``
   ======  ============================  ==========================================

``and`` y ``or`` **cortocircuitan**: el lado derecho solo se evalúa si el
resultado no está decidido. Es una propiedad de la evaluación, no de la
sintaxis, pero condiciona a los backends.

``&`` no es un operador unario cualquiera: produce un **nodo propio**
(``AddrOf``) porque sus reglas —exige un *lvalue*, y la mutabilidad del
puntero resultante se hereda del binding— son suyas, no del operador genérico.

.. _ast:

El árbol resultante
--------------------

Los nodos viven en ``V0/include/ast_nodes.py`` y se agrupan en tres familias:

Declaraciones
   ``FunctionDecl``, ``StructDecl``, ``EnumDecl``, ``TestDecl``,
   ``ExternBlock``, ``ImportDirective``, ``ExportDirective``,
   ``FromDirective``, ``DecoratorDecl``, ``TraitDecl``.

Sentencias
   ``Block``, ``VarDecl``, ``TypeDecl``, ``IfStmt``, ``WhileStmt``,
   ``MatchStmt``, ``ReturnStmt``, ``BreakStmt``, ``ContinueStmt``,
   ``MoveStmt``, ``FreeStmt``, ``ThrowStmt``, ``TryStmt``, ``ExprStmt``,
   ``ImportBinding``.

Expresiones
   ``Literal``, ``InterpolatedString``, ``Identifier``, ``UnaryOp``,
   ``BinaryOp``, ``Assignment``, ``Call``, ``Index``, ``MemberAccess``,
   ``AddrOf``, ``CastExpr``, ``SizeofExpr``, ``StructLiteral``.

Todo nodo lleva su **línea y columna**. Esa posición viaja hasta el final: un
diagnóstico del target web sobre un programa compilado ayer sigue apuntando a
la columna exacta del fuente.

Para ver el árbol de un archivo:

.. code-block:: console

   $ python V0/main.py programa.srcx --emit-ast-json

.. _recuperacion:

Recuperación de errores
------------------------

El parser **no se detiene en el primer error**. Trabaja en modo pánico:
anota el diagnóstico, salta tokens hasta un punto de sincronización (un ``;``,
una llave de cierre, el comienzo de una declaración) y sigue analizando.

Así una compilación reporta todos los errores de sintaxis de una vez, en vez
de obligar a arreglarlos de uno en uno. El precio es que el AST resultante es
"el mejor esfuerzo posible": lo que la recuperación se tragó no está en el
árbol.

Por eso **las fases que leen ese AST solo corren si el parseo fue limpio**. Un
token suelto puede haberse comido una declaración entera, y sin esta regla
cada uso de esa declaración se reportaría como símbolo no declarado: un error
real produciría veinte falsos.

.. _profundidad:

Límite de anidamiento
----------------------

Las expresiones se analizan recursivamente, así que un programa con
anidamiento extremo agotaría la pila del intérprete de Python. El compilador
sube el límite de recursión y convierte el desbordamiento en un diagnóstico
controlado, ``PAR025`` (``ExpressionTooDeepError``), con su posición — nunca
en un *traceback*.

.. _directivas-parser:

Directivas
-----------

Las directivas empiezan por ``#`` y las resuelve el parser antes que nada:

.. code-block:: srcx

   #import io                    // liga el módulo bajo su alias
   #import io.stdp as salida     // con alias explícito
   #from io #import stdp         // trae un miembro concreto
   #export as milib              // cierra una librería .libsrx
   #export package as IO         // archivo padre de un paquete

``#import`` y ``#from`` disparan el **linker de librerías**, que resuelve el
nombre contra archivos ``.libsrx`` y paquetes, y cachea el resultado por
ruta. Ver :doc:`libsrx`.

``#extern cpp { ... }`` es distinto: el lexer captura el cuerpo **crudo**, sin
tokenizarlo con las reglas de suriaX, y viaja intacto hasta el backend.

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

De menor a mayor fuerza de enlace (la fuente es
``parser/precedence.py``). Los binarios son asociativos por la izquierda,
salvo la asignación y ``??``, que asocian por la **derecha**: ``a = b = c`` es
``a = (b = c)`` y ``a ?? b ?? c`` es ``a ?? (b ?? c)``.

.. table::
   :widths: auto

   ======  ======================================  ==========================================
   Nivel   Operadores                              Ejemplo
   ======  ======================================  ==========================================
   1       ``=``  ``+=``  ``-=`` ... ``>>=``       ``x = y``  (derecha)
   2       ``??``                                  ``x ?? 0``  (derecha)
   3       ``or``                                  ``a or b``
   4       ``and``                                 ``a and b``
   5       ``==``  ``!=``                          ``x == y``
   6       ``<``  ``<=``  ``>``  ``>=``            ``x < y``
   7       ``|``                                   ``a | b``
   8       ``^``                                   ``a ^ b``
   9       ``&``                                   ``a & b``
   10      ``<<``  ``>>``                          ``a << 3``
   11      ``+``  ``-``                            ``a + b``
   12      ``*``  ``/``  ``%``                     ``a * b``
   13      ``not``  ``-``  ``~``  ``&``            ``not activo``, ``-x``, ``&x``
   14      ``.``  ``(...)``  ``[...]``             ``obj.campo``, ``f(1)``, ``v[i]``
   ======  ======================================  ==========================================

``??`` (desenvolver un ``T?`` con un valor por defecto, ver :ref:`el sistema
de tipos <desenvolver-opcional>`) va donde lo ponen C# y Swift: por debajo de
``or``, así que ``x ?? a or b`` es ``x ?? (a or b)``. No es un token del
lexer: como ``>>``, son dos ``?`` **pegados** que el parser junta en posición
de operador, y por eso ``int??`` sigue siendo un tipo.

``and``, ``or`` y ``??`` **cortocircuitan**: el lado derecho solo se evalúa si el
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

Una declaración puede anidar hasta **500 niveles** en su árbol. Lo que anida
de más es ``PAR025`` (``ExpressionTooDeepError``), con la posición del primer
nodo que se pasa, y la declaración entera se descarta: las demás del archivo
se siguen analizando.

Cuenta todo lo que deja un nodo dentro de otro: un bloque dentro de un bloque
(dos niveles por cada ``if`` anidado, el ``if`` y su bloque), una llamada
dentro de una llamada, y también una **cadena de operadores**. ``a + b + c``
no anida al escribirse, pero se analiza como ``(a + b) + c``: un nivel por
operador. Una suma de unos 496 términos cabe; una de 600, no.

El límite es del lenguaje y no de la máquina que compila: el árbol lo
recorren después pasadas recursivas y el HIR lo guarda como mensajes
anidados, que cada lector acota a su vez. Sin él, una expresión larga pasaba
el parser y acababa en un fallo interno más adelante, a una profundidad que
dependía de quién llamase al compilador.

Los paréntesis no dejan nodo, así que no cuentan; pero el parser los lee de
forma recursiva, y miles de ellos anidados agotarían la pila de Python. Ese
desbordamiento se convierte en el mismo ``PAR025`` — nunca en un *traceback*.

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

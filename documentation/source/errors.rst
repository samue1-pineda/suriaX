10. Catálogo de errores
========================

Cada fase del compilador tiene su familia de códigos, y el prefijo dice **dónde**
se detectó el problema. Todos comparten forma: código, mensaje, archivo, línea y
columna.

.. table:: Familias
   :widths: auto

   ==========  ====================  ============================================================================
   Prefijo     Fase                    Momento
   ==========  ====================  ============================================================================
   ``EXT``     Extensiones (HTIMS)    Antes del léxico, al leer ``extends.srcx``y las declaraciones del proyecto.
   ``LEX``     Lexer                  Al formar los tokens.
   ``PAR``     Parser                 Al construir el árbol.
   ``AST``     AST-tipado             Al resolver los tipos.
   ``SEM``     Semántica              Al validar nombres, reglas y contratos.
   ``HIR``     Emisor del HIR         Al serializar el programa validado.
   ``RT``      Intérprete             Durante la ejecución.
   ``WEB``     Target web             Al preparar y generar WebAssembly.
   ==========  ====================  ============================================================================

Ninguna fase se detiene en el primer problema: acumula todo lo que encuentra y
lo devuelve junto. Para obtenerlos en JSON, con rango y severidad:

.. code-block:: console

   $ python V0/main.py programa.srcx --emit-diagnostics

.. _lex-errores:

LEX — análisis léxico
----------------------

.. _LEX001-def:
.. _LEX002-def:
.. _LEX003-def:
.. _LEX004-def:
.. _LEX005-def:
.. _LEX006-def:
.. _LEX007-def:
.. _LEX008-def:
.. _LEX009-def:
.. _LEX010-def:
.. _LEX011-def:
.. _LEX012-def:
.. _LEX013-def:
.. _LEX014-def:


.. table::
   :widths: auto

   ==========  ================================  ==================================================
   Código      Nombre                            Cuándo
   ==========  ================================  ==================================================
   ``LEX001``  UnexpectedCharacterError          Un carácter que no pertenece al alfabeto.
   ``LEX002``  InvalidTokenError                 Una secuencia que no forma ningún token válido.
   ``LEX003``  UnterminatedStringError           Una cadena que no cierra antes del fin de línea.
   ``LEX004``  UnterminatedCommentError          Un comentario de bloque sin ``-/``.
   ``LEX005``  InvalidEscapeSequenceError        Un escape que no existe.
   ``LEX006``  NumericLiteralOverflowError       Un número fuera del rango representable.
   ``LEX007``  InvalidNumberFormatError          Un literal numérico mal formado.
   ``LEX008``  InvalidUnicodeCharacterError      Un *code point* no válido.
   ``LEX009``  UnexpectedEOFError                El archivo termina a mitad de un token.
   ``LEX010``  InvalidDirectiveError             Un ``#`` seguido de algo que no es una directiva.
   ``LEX011``  InvalidIdentifierError            Un identificador que no cumple las reglas Unicode.
   ``LEX012``  InvalidCharacterLiteralError      Un literal de carácter vacío o con más de uno.
   ``LEX013``  InvalidDecoratorError             Un ``@`` sin nombre válido detrás.
   ``LEX014``  UnterminatedExternBlockError      Un ``#extern cpp{`` sin llave de cierre.
   ==========  ================================  ==================================================

.. _par-errores:

PAR — análisis sintáctico
--------------------------

.. _PAR001-def:
.. _PAR002-def:
.. _PAR003-def:
.. _PAR004-def:
.. _PAR005-def:
.. _PAR006-def:
.. _PAR007-def:
.. _PAR008-def:
.. _PAR009-def:
.. _PAR010-def:
.. _PAR011-def:
.. _PAR012-def:
.. _PAR013-def:
.. _PAR014-def:
.. _PAR015-def:
.. _PAR016-def:
.. _PAR017-def:
.. _PAR018-def:
.. _PAR019-def:
.. _PAR020-def:
.. _PAR021-def:
.. _PAR022-def:
.. _PAR023-def:
.. _PAR024-def:
.. _PAR025-def:
.. _PAR026-def:


.. table::
   :widths: auto

   ==========  ================================  ==================================================
   Código      Nombre                            Cuándo
   ==========  ================================  ==================================================
   ``PAR001``  SyntaxError                       Error de sintaxis genérico.
   ``PAR002``  UnexpectedTokenError              Un token que no encaja en esta posición.
   ``PAR003``  ExpectedTokenError                Faltaba un token concreto.
   ``PAR004``  MissingSemicolonError             Falta el ``;`` que cierra la sentencia.
   ``PAR005``  MissingCommaError                 Falta una coma en una lista.
   ``PAR006``  UnexpectedCommaError              Una coma de más.
   ``PAR007``  MissingColonError                 Falta el ``:`` de un brazo o de un campo.
   ``PAR008``  UnexpectedColonError              Un ``:`` fuera de sitio.
   ``PAR009``  UnclosedParenthesisError          Un ``(`` sin cerrar.
   ``PAR010``  UnclosedBracketError              Un ``[`` sin cerrar.
   ``PAR011``  UnclosedBraceError                Un ``{`` sin cerrar.
   ``PAR012``  InvalidExpressionError            Algo que no puede ser una expresión.
   ``PAR013``  InvalidStatementError             Algo que no puede ser una sentencia.
   ``PAR014``  UnexpectedEOFError                El archivo termina a media construcción.
   ``PAR015``  DuplicatedModifierError           Un modificador repetido.
   ``PAR016``  InvalidTypeDeclarationError       Una declaración de tipo mal formada.
   ``PAR017``  InvalidFunctionSignatureError     Una firma de función mal formada.
   ``PAR018``  InvalidMatchArmError              Un brazo de ``match`` mal formado.
   ``PAR019``  InvalidDecoratorTargetError       Un decorador sobre algo que no lo admite.
   ``PAR020``  UnknownDirectiveError             Una directiva que el compilador no conoce.
   ``PAR021``  InvalidMemoryQualifierError       Un cualificador de memoria mal usado.
   ``PAR022``  InvalidRegionDeclarationError     Una declaración de región mal formada.
   ``PAR023``  MissingTypeAnnotationError        Falta la anotación de tipo obligatoria.
   ``PAR024``  InvalidExternBlockError           Un ``#extern`` mal formado.
   ``PAR025``  ExpressionTooDeepError            Anidamiento por encima del límite.
   ``PAR026``  InvalidLibraryNameError           Un nombre de librería mal formado.
   ==========  ================================  ==================================================

.. _ast-errores:

AST — tipos
------------

.. _AST001-def:
.. _AST002-def:
.. _AST003-def:
.. _AST004-def:
.. _AST005-def:
.. _AST006-def:
.. _AST007-def:
.. _AST008-def:
.. _AST009-def:
.. _AST010-def:
.. _AST011-def:
.. _AST012-def:


.. table::
   :widths: auto

   ==========  ==============================  ====================================================
   Código      Nombre                          Cuándo
   ==========  ==============================  ====================================================
   ``AST001``  InvalidASTNodeError             Un nodo inválido en el árbol.
   ``AST002``  MissingASTNodeError             Falta un nodo obligatorio.
   ``AST003``  UnexpectedASTStructureError     El árbol no tiene la forma esperada.
   ``AST004``  ASTConstructionError            No se pudo construir el nodo.
   ``AST005``  UnknownTypeError                Un tipo que no existe.
   ``AST006``  TypeMismatchError               Los tipos no coinciden.
   ``AST007``  CannotInferTypeError            No se puede determinar el tipo.
   ``AST008``  InvalidCastError                Una conversión que no es válida.
   ``AST009``  AmbiguousTypeError              Más de un tipo posible.
   ``AST010``  GenericTypeMismatchError        Argumentos de tipo incompatibles.
   ``AST011``  InvalidTypeArgumentError        Un argumento de tipo inválido.
   ``AST012``  InvalidReturnTypeError          El retorno no encaja con la firma.
   ==========  ==============================  ====================================================

.. _sem-errores:

SEM — semántica
----------------

.. _SEM001-def:
.. _SEM002-def:
.. _SEM003-def:
.. _SEM004-def:
.. _SEM005-def:
.. _SEM006-def:
.. _SEM007-def:
.. _SEM008-def:
.. _SEM009-def:
.. _SEM010-def:
.. _SEM011-def:
.. _SEM012-def:
.. _SEM013-def:
.. _SEM014-def:
.. _SEM015-def:
.. _SEM016-def:
.. _SEM017-def:
.. _SEM018-def:
.. _SEM019-def:
.. _SEM020-def:
.. _SEM021-def:
.. _SEM022-def:


.. table::
   :widths: auto

   ==========  ==============================  ====================================================
   Código      Nombre                          Cuándo
   ==========  ==============================  ====================================================
   ``SEM001``  UndefinedSymbolError            Un nombre que no está declarado.
   ``SEM002``  DuplicateSymbolError            Dos declaraciones del mismo nombre en un ámbito.
   ``SEM003``  ImmutableAssignmentError        Asignación a un binding ``const``.
   ``SEM004``  UseAfterMoveError               Uso de un valor ya movido.
   ``SEM005``  DoubleMoveError                 Dos ``move`` sobre el mismo valor.
   ``SEM006``  InvalidHookSignatureError       Un hook cuya firma no cumple la convención.
   ``SEM007``  DuplicateHookError              Dos hooks de la misma clase para un tipo.
   ``SEM008``  CallArityError                  Número de argumentos distinto al de la firma.
   ``SEM009``  LibraryNotFoundError            No se encontró la librería importada.
   ``SEM010``  InvalidLibraryError             El archivo no es una unidad válida.
   ``SEM011``  UnknownLibraryMemberError       El miembro no existe en esa librería.
   ``SEM012``  UndefinedRegionError            Una región que no está declarada.
   ``SEM013``  InvalidAddressOfError           ``&`` sobre algo que no es un *lvalue*.
   ``SEM014``  InvalidFreeTargetError          ``free`` sobre algo que no es un puntero.
   ``SEM015``  ReadOnlyPointerWriteError       Escritura a través de un ``ptr`` no mutable.
   ``SEM016``  InvalidCastError                Conversión sin regla ni hook que la implemente.
   ``SEM017``  ExpressionTooDeepError          Anidamiento por encima del límite.
   ``SEM018``  UnknownHookError                Un ``__x__`` marcado como hook que no es del conjunto.
   ``SEM019``  VisibilityViolationError        Acceso a algo fuera de su visibilidad.
   ``SEM020``  InvalidDeleteError              ``delete`` mal formado o sobre algo inválido.
   ``SEM021``  TraitNotSatisfiedError          El tipo no cumple el contrato del trait.
   ``SEM022``  InvalidDunderSignatureError     Un método dunder con firma inválida.
   ==========  ==============================  ====================================================

.. _hir-errores:

HIR — serialización
--------------------

.. _HIR001-def:
.. _HIR002-def:
.. _HIR003-def:
.. _HIR004-def:
.. _HIR005-def:
.. _HIR006-def:
.. _HIR007-def:
.. _HIR008-def:
.. _HIR009-def:
.. _HIR010-def:


.. table::
   :widths: auto

   ==========  ================================  ==================================================
   Código      Nombre                            Cuándo
   ==========  ================================  ==================================================
   ``HIR001``  HIRMessageBuildError              No se pudo construir el mensaje.
   ``HIR002``  HIRFieldMissingError              Falta un campo obligatorio.
   ``HIR003``  HIRTypeMismatchError              Un tipo que no encaja con el esquema.
   ``HIR004``  HIRSchemaMismatchError            La versión del esquema no coincide.
   ``HIR005``  HIRUnsupportedInstructionError    Una construcción que no viaja en esta versión.
   ``HIR006``  HIRConversionError                No se pudo convertir un nodo.
   ``HIR007``  HIRSerializationError             Falló la escritura del binario.
   ``HIR008``  HIRSymbolResolutionError          Un símbolo que no se pudo resolver.
   ``HIR009``  HIRNameCollisionError             Dos símbolos con el mismo nombre.
   ``HIR010``  HIRInvalidNodeError               Un nodo inválido para el esquema.
   ==========  ================================  ==================================================

.. _rt-errores:

RT — ejecución
---------------

.. _RT001-def:
.. _RT002-def:
.. _RT003-def:
.. _RT004-def:
.. _RT005-def:
.. _RT006-def:
.. _RT007-def:
.. _RT008-def:
.. _RT009-def:
.. _RT010-def:
.. _RT011-def:
.. _RT012-def:
.. _RT013-def:
.. _RT014-def:
.. _RT015-def:


.. table::
   :widths: auto

   ==========  ==============================  ====================================================
   Código      Nombre                          Cuándo
   ==========  ==============================  ====================================================
   ``RT001``   UseAfterMoveError               Lectura de una celda cuyo valor se transfirió.
   ``RT002``   DoubleMoveError                 ``move`` sobre una celda ya movida.
   ``RT003``   UseAfterFreeError               Acceso a una celda liberada.
   ``RT004``   NullDereferenceError            Acceso a miembro o índice de un ``null``.
   ``RT005``   InvalidFreeError                ``free`` sobre algo que no es un puntero vivo.
   ``RT006``   UndefinedNameError              Un nombre no ligado en el entorno.
   ``RT007``   NotCallableError                Llamada sobre algo que no es invocable.
   ``RT008``   MissingIntrinsicError           Un prototipo sin implementación del host.
   ``RT009``   MissingEntryError               La función de entrada no existe.
   ``RT010``   StepLimitError                  Se alcanzó el límite de pasos de ejecución.
   ``RT011``   UnsupportedNodeError            Un nodo que el intérprete aún no ejecuta.
   ``RT012``   InvalidCastRuntimeError         Conversión sin par registrado en runtime.
   ``RT013``   IndexOutOfRangeError            Índice fuera de rango.
   ``RT014``   NotIndexableError               Indexación sobre algo que no la admite.
   ``RT015``   CorruptMemoryHandleError        El backend de memoria recibió un handle inválido.
   ==========  ==============================  ====================================================

.. _web-errores:

WEB — target web
-----------------

Dos rangos con significados distintos: ``WEB0xx`` dice que el target **no puede
ejecutar** esa construcción; ``WEB1xx``, que el generador **todavía no la
traduce**.

.. list-table::
   :header-rows: 1
   :widths: 18 52 30

   * - Código
     - Construcción
     - Rango
   * - ``WEB001``
     - ``#extern cpp { }``
     - Contención
   * - ``WEB002``
     - Tipo puntero
     - Contención
   * - ``WEB003``
     - ``&x``
     - Contención
   * - ``WEB004``
     - ``free x;``
     - Contención
   * - ``WEB005``
     - Hooks del modelo de memoria
     - Contención
   * - ``WEB006``
     - ``move x;``
     - Contención
   * - ``WEB007``
     - Librería fuera de la lista permitida
     - Contención
   * - ``WEB008``
     - ``sizeof(T)``
     - Contención
   * - ``WEB100``
     - Construcción fuera del subconjunto que traduce el generador
     - Generador
   * - ``WEB101``
     - Tipo que el IR de WebAssembly no representa
     - Generador
   * - ``WEB102``
     - Cadena que no es un literal directo en un ``print``
     - Generador
   * - ``WEB900``
     - ``.phir`` ilegible o esquema no soportado
     - Lector
   * - ``WEB901``
     - Nodo del HIR sin variante
     - Lector

.. _severidad:

Severidad
----------

.. table::
   :widths: auto

   ==============  ==========================================================
   Severidad       Significado
   ==============  ==========================================================
   ``critical``    Impide continuar con el resultado de esa fase.
   ``warning``     No detiene la compilación.
   ``note``        Información: el linker resolvió algo, un archivo se cargó.
   ``panic``       Error interno del compilador.
   ==============  ==========================================================

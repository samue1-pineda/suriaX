10. Catálogo de errores
========================

Cada fase del compilador tiene su familia de códigos, y el prefijo dice **dónde**
se detectó el problema. Todos comparten forma: código, mensaje, archivo, línea y
columna.

.. table:: Familias
   :widths: auto

   ==========  ====================  =============================================================================
   Prefijo     Fase                    Momento
   ==========  ====================  =============================================================================
   ``CFG``     Configuración          Lo primero de todo, al leer ``.suriaX_config.yaml``.
   ``EXT``     Extensiones (HTIMS)    Antes del léxico, al leer ``extends.srcx`` y las declaraciones del proyecto.
   ``LEX``     Lexer                  Al formar los tokens.
   ``PAR``     Parser                 Al construir el árbol.
   ``AST``     AST-tipado             Al resolver los tipos.
   ``SEM``     Semántica              Al validar nombres, reglas y contratos.
   ``HIR``     Emisor del HIR         Al serializar el programa validado.
   ``RT``      Intérprete             Durante la ejecución.
   ``EXC``     Runtime                Durante la ejecución: una excepción que el programa puede atrapar (``try``/``catch``).
   ``VM``      Backend nativo (VM)    Al ligar el ``.phir`` para resolverlo, bajarlo al MIR y ejecutarlo.
   ``WEB``     Target web             Al preparar y generar WebAssembly.
   ``ICE``     Interno                En cualquier fase: el que falló es el **compilador**, no el programa.
   ==========  ====================  =============================================================================

Ninguna fase se detiene en el primer problema: acumula todo lo que encuentra y
lo devuelve junto. Para obtenerlos en JSON, con rango y severidad:

.. code-block:: console

   $ python V0/main.py programa.srcx --emit-diagnostics

.. _cfg-errores:

CFG — configuración
--------------------

Se leen antes que nada, porque el resto del pipeline resuelve rutas contra la
configuración: seguir con unos ajustes que ya se rechazaron sería compilar
contra algo que el usuario no escribió. Un ``.suriaX_config.yaml`` inválido
termina con el código de salida ``5``.

Antes, un archivo mal escrito se descartaba **en silencio** y el síntoma
aparecía mucho después, en otro sitio —"no se encontró la librería X"— sin
ninguna pista de que la configuración nunca llegó a aplicarse.

.. _CFG001-def:
.. _CFG002-def:
.. _CFG003-def:
.. _CFG004-def:
.. _CFG005-def:
.. _CFG006-def:
.. _CFG007-def:

.. table::
   :widths: auto

   ==========  ==============================  ====================================================
   Código      Clase                           Cuándo
   ==========  ==============================  ====================================================
   ``CFG001``  ConfigError                     El archivo existe pero no se pudo leer (I/O, no UTF-8).
   ``CFG002``  ConfigError                     YAML malformado; el mensaje trae la línea del parser.
   ``CFG003``  ConfigError                     La raíz del documento no es un mapa ``clave: valor``.
   ``CFG004``  ConfigError                     Clave desconocida. Sugiere la más parecida, que es
                                               lo que arregla un typo (``libsrx_path`` →
                                               ``libsrx_paths``).
   ``CFG005``  ConfigError                     El valor no es del tipo que la clave espera.
   ``CFG006``  ConfigError                     El valor no está entre los admitidos (``target``,
                                               ``optimization``, ``platform``...).
   ``CFG007``  ConfigError                     Hay un yaml pero falta ``pyyaml`` para leerlo. Es
                                               una **advertencia**, no un error: el frontend corre
                                               con la librería estándar, pero la configuración no
                                               se está aplicando y hay que saberlo.
   ==========  ==============================  ====================================================

El esquema no se escribe a mano: se **deriva** del que genera
``--init-config``, así que una clave nueva del formato queda validada sola.

.. _ext-errores:

EXT — extensiones del proyecto (HTIMS)
---------------------------------------

Se leen justo después de la configuración y antes del léxico: un proyecto
puede DECLARAR hooks propios (``extends.srcx`` + los ``.py`` que nombra), y
ese vocabulario tiene que existir antes de que la Semántica valide nada que
lo use. Ver :doc:`repo/htims`.

Toda la familia es **crítica**: un manifiesto malformado o un directorio que
no existe es un proyecto mal configurado, no una advertencia que se pueda
arrastrar.

.. _EXT001-def:
.. _EXT002-def:
.. _EXT003-def:
.. _EXT004-def:
.. _EXT005-def:
.. _EXT006-def:
.. _EXT007-def:
.. _EXT010-def:
.. _EXT011-def:
.. _EXT012-def:
.. _EXT020-def:
.. _EXT021-def:
.. _EXT022-def:
.. _EXT023-def:
.. _EXT024-def:
.. _EXT025-def:
.. _EXT026-def:
.. _EXT027-def:
.. _EXT028-def:
.. _EXT029-def:

.. table::
   :widths: auto

   ==========  ==============================  ====================================================
   Código      Nombre                          Cuándo
   ==========  ==============================  ====================================================
   ``EXT001``  ExtensionError                  El manifiesto existe pero no se pudo leer (I/O, no UTF-8).
   ``EXT002``  ExtensionError                  Línea malformada: no es ``clave: valor`` ni comentario.
   ``EXT003``  ExtensionError                  Un directorio declarado no existe.
   ``EXT004``  ExtensionError                  Clave desconocida en el manifiesto.
   ``EXT005``  ExtensionError                  Clave duplicada.
   ``EXT006``  ExtensionError                  Valor vacío.
   ``EXT007``  ExtensionError                  Falta una clave obligatoria.
   ``EXT010``  ExtensionError                  El ``.py`` declarado no existe o no se puede leer.
   ``EXT011``  ExtensionError                  El ``.py`` no es Python válido (``SyntaxError``).
   ``EXT012``  ExtensionError                  El nombre de proyecto se declara dos veces con
                                               valores distintos.
   ``EXT020``  ExtensionError                  El nombre del hook no tiene la forma ``__x__``.
   ``EXT021``  ExtensionError                  Falta ``owner``, o no es un identificador válido.
   ``EXT022``  ExtensionError                  Falta ``returns``.
   ``EXT023``  ExtensionError                  ``params`` no es una lista de cadenas.
   ``EXT024``  ExtensionError                  El par (dueño, nombre) se declara dos veces.
   ``EXT025``  ExtensionError                  Argumento no literal: el escaneo **no ejecuta**
                                               el código de la extensión, así que solo admite
                                               literales.
   ``EXT026``  ExtensionError                  Argumento desconocido en el decorador.
   ``EXT027``  ExtensionError                  Colisión con el vocabulario fijo del compilador.
   ``EXT028``  ExtensionError                  Una firma PURA (``@signature``) pide lógica nativa.
                                               Bajar a C++ está negado por defecto: se declara con
                                               ``@signature_extends(..., cxx=True)``.
   ``EXT029``  ExtensionError                  El contrato con C++ está incompleto: falta
                                               ``cxx=True`` (el opt-in se escribe) o falta
                                               ``logic``, el símbolo que ``logic_dir`` implementará.
   ==========  ==============================  ====================================================

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
   ``LEX001``  UnexpectedCharacterError          Un carácter que no pertenece al alfabeto. Un
                                                 ``!`` suelto dice que la negación es ``not``.
   ``LEX002``  InvalidTokenError                 Una secuencia que no forma ningún token válido.
   ``LEX003``  UnterminatedStringError           Una cadena que no cierra antes del fin de línea.
   ``LEX004``  UnterminatedCommentError          Un comentario de bloque sin ``-/``.
   ``LEX005``  InvalidEscapeSequenceError        Un escape que no existe, o un ``\`` dentro de una
                                                 interpolación (``f"{len(\"ab\")}"``): ahí va código
                                                 y sus literales no se escapan (``f"{len("ab")}"``).
   ``LEX006``  NumericLiteralOverflowError       Un número fuera del rango representable
                                                 (un ``float`` que no cabe: ``1e400``).
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
.. _PAR023-def:
.. _PAR024-def:
.. _PAR025-def:
.. _PAR026-def:
.. _PAR027-def:
.. _PAR028-def:
.. _PAR029-def:


.. table::
   :widths: auto

   ==========  ================================  ==================================================
   Código      Nombre                            Cuándo
   ==========  ================================  ==================================================
   ``PAR001``  SyntaxError                       Error de sintaxis genérico.
   ``PAR002``  UnexpectedTokenError              Un token que no encaja en esta posición.
   ``PAR003``  ExpectedTokenError                Faltaba un token concreto. Si en el sitio de un
                                                 nombre hay una palabra reservada (``int error;``),
                                                 el mensaje lo dice.
   ``PAR004``  MissingSemicolonError             Falta el ``;`` que cierra la sentencia.
   ``PAR005``  MissingCommaError                 Falta una coma en una lista.
   ``PAR006``  UnexpectedCommaError              Una coma de más.
   ``PAR007``  MissingColonError                 Falta el ``:`` de un brazo o de un campo.
   ``PAR008``  UnexpectedColonError              Un ``:`` fuera de sitio.
   ``PAR009``  UnclosedParenthesisError          Un ``(`` sin cerrar.
   ``PAR010``  UnclosedBracketError              Un ``[`` sin cerrar.
   ``PAR011``  UnclosedBraceError                Un ``{`` sin cerrar.
   ``PAR012``  InvalidExpressionError            Algo que no puede ser una expresión. También un
                                                 operador de otro lenguaje, con lo que se escribe
                                                 en suriaX: el ternario ``c ? a : b`` (``if``/``else``),
                                                 ``&&`` (``and``) y ``||`` (``or``).
   ``PAR013``  InvalidStatementError             Algo que no puede ser una sentencia: ``break`` o
                                                 ``continue`` fuera de un bucle, ``expect`` fuera de
                                                 un ``test``. Dentro de una lambda el mensaje dice
                                                 que la lambda corta el bucle o el ``test`` de fuera.
   ``PAR014``  UnexpectedEOFError                El archivo termina a media construcción.
   ``PAR015``  DuplicatedModifierError           Un modificador repetido.
   ``PAR016``  InvalidTypeDeclarationError       Una declaración de tipo mal formada.
   ``PAR017``  InvalidFunctionSignatureError     Una firma de función mal formada.
   ``PAR018``  InvalidMatchArmError              Un brazo de ``match`` mal formado.
   ``PAR019``  InvalidDecoratorTargetError       Un decorador sobre algo que no lo admite.
   ``PAR020``  UnknownDirectiveError             Una directiva que el compilador no conoce.
   ``PAR021``  InvalidMemoryQualifierError       Un cualificador de memoria mal usado.
   ``PAR023``  MissingTypeAnnotationError        Falta la anotación de tipo obligatoria.
   ``PAR024``  InvalidExternBlockError           Un ``#extern`` mal formado.
   ``PAR025``  ExpressionTooDeepError            Anidamiento por encima del límite; el mensaje
                                                 dice si son bloques, una cadena de operadores o
                                                 expresiones anidadas.
   ``PAR026``  InvalidLibraryNameError           Un nombre de librería mal formado.
   ``PAR027``  ExitFromFinallyError              ``return``, o ``break``/``continue`` que salen de un
                                                 ``finally``: reemplazarían la salida en curso.
   ``PAR028``  WithReceiverError                 ``.campo`` sin un ``with`` de UN valor alrededor
                                                 (fuera de un ``with``, o en uno con varios).
   ``PAR029``  TestWithoutExpectError            Un ``test`` sin ningún ``expect``: no comprueba
                                                 nada y pasaría siempre.
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
   ``AST006``  TypeMismatchError               Los tipos no coinciden. También ``x ?? d`` con ``x``
                                               que no es un ``T?``, o con ``d`` que no es EXACTAMENTE
                                               su ``T`` (sin conversiones, ni ``null``), y un patrón
                                               de otra instancia de un enum genérico
                                               (``case Res<str, int>.Ok(x)`` sobre un ``Res<int, str>``).
                                               Y el índice de ``v[i]``/``v[i] = x`` que no es del tipo
                                               del 2.º parámetro de ``__index__``/``__index_set__``
                                               (``v["a"]`` sobre un ``Vector``), o el de ``s[i]`` sobre
                                               un ``str`` que no es ``int``.
   ``AST007``  CannotInferTypeError            Los argumentos de tipo de una llamada a un genérico
                                               (o a un método genérico) no se pueden deducir: un
                                               parámetro que solo aparece en el retorno, del que
                                               solo llega ``null`` o cuyo argumento no tiene su
                                               forma (``T``, ``T ptr``, ``T?``, ``Nombre<..T..>``,
                                               ``fn(..T..) -> R``, sin conversiones); o dos
                                               argumentos dan tipos distintos para el mismo ``T``.
                                               Dice por qué y cómo se escriben (todos o ninguno).
   ``AST008``  InvalidCastError                Una conversión que no es válida.
   ``AST009``  AmbiguousTypeError              Más de un tipo posible.
   ``AST010``  GenericTypeMismatchError        Argumentos de tipo incompatibles.
   ``AST011``  InvalidTypeArgumentError        Un argumento de tipo inválido.
   ``AST012``  InvalidReturnTypeError          El retorno no encaja con la firma.
   ==========  ==============================  ====================================================

.. _sem-errores:

SEM — semántica
----------------

.. _SEM000-def:
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
.. _SEM013-def:
.. _SEM014-def:
.. _SEM015-def:
.. _SEM016-def:
.. _SEM017-def:
.. _SEM018-def:
.. _SEM019-def:
.. _SEM021-def:
.. _SEM022-def:
.. _SEM023-def:
.. _SEM024-def:
.. _SEM025-def:
.. _SEM026-def:
.. _SEM027-def:
.. _SEM028-def:
.. _SEM030-def:
.. _SEM031-def:
.. _SEM032-def:
.. _SEM033-def:
.. _SEM034-def:
.. _SEM035-def:
.. _SEM036-def:
.. _SEM037-def:
.. _SEM038-def:
.. _SEM039-def:
.. _SEM040-def:
.. _SEM041-def:
.. _SEM042-def:
.. _SEM043-def:
.. _SEM044-def:
.. _SEM045-def:
.. _SEM046-def:
.. _SEM047-def:
.. _SEM048-def:
.. _SEM049-def:
.. _SEM050-def:
.. _SEM051-def:


.. table::
   :widths: auto

   ==========  ==============================  ====================================================
   Código      Nombre                          Cuándo
   ==========  ==============================  ====================================================
   ``SEM000``  MissingHandlerError             Un nodo del AST sin handler: fallo del compilador.
   ``SEM001``  UndefinedSymbolError            Un nombre que no está declarado. También
                                               ``print(x)``/``len(x)`` sobre un tipo que no puede
                                               tener ``__print__``/``__len__`` (``len(3)``,
                                               ``print(p)`` con ``p`` un ``int ptr``; ``print(5)``
                                               escribe el primitivo desde la 0.4.1), y
                                               ``hash`` de un tipo sin ``__hash__``, también en cada
                                               instancia de un genérico (un ``Dictionary``).
   ``SEM002``  DuplicateSymbolError            Dos declaraciones del mismo nombre en un ámbito,
                                               o un patrón que liga el mismo nombre dos veces
                                               (``case Par(x, x)``). También ``case v`` sobre un
                                               ``T?`` con ``v`` ya declarado (¿ligar o comparar?) y
                                               un parámetro de tipo repetido (``Par<T, T>``). Y
                                               declarar en una rama un nombre que liga su patrón
                                               (``case v { var str v = ...; }``), como en un
                                               ``catch``.
   ``SEM003``  ImmutableAssignmentError        Modificar un ``const``: reasignarlo, escribir un
                                               campo a cualquier profundidad (``c.n = 5``,
                                               ``d.c.n = 5``) o llamar sobre él a un método cuyo
                                               receptor es ``ptr mutable`` (``k.sube()``). También
                                               asignar, mover, liberar o modificar algo que
                                               captura una lambda (la captura es de solo lectura).
   ``SEM004``  UseAfterMoveError               Uso de un valor ya movido.
   ``SEM005``  DoubleMoveError                 Dos ``move`` sobre el mismo valor.
   ``SEM006``  InvalidHookSignatureError       Un hook cuya firma no cumple la convención
                                               (``__eq__`` y ``__cmp__``: dos ``T ptr`` del mismo
                                               tipo dueño).
   ``SEM007``  DuplicateHookError              Dos hooks de la misma clase para un tipo.
   ``SEM008``  CallArityError                  Número de argumentos distinto al de la firma.
                                               También en un método (``v.push(1, 2)``): antes
                                               una llamada a un método no se comprobaba. Y las
                                               nativas: ``print()`` sin argumentos, ``print(a, b)``
                                               dentro de una expresión (es variádico solo como
                                               sentencia), ``len`` y ``hash`` con otro número que uno.
   ``SEM009``  LibraryNotFoundError            No se encontró la librería importada.
   ``SEM010``  InvalidLibraryError             El archivo no es una unidad válida.
   ``SEM011``  UnknownLibraryMemberError       El miembro no existe en esa librería.
   ``SEM013``  InvalidAddressOfError           ``&`` sobre algo que no es un *lvalue*, o sobre un
                                               elemento ESCALAR de un bloque (``&b[i]`` con ``b``
                                               un ``int ptr``): ningún motor presta el interior de
                                               un bloque. En un genérico (``Vector.at``,
                                               ``at_mut``) se decide en cada instancia.
   ``SEM014``  InvalidFreeTargetError          ``free`` sobre algo que no es un puntero.
   ``SEM015``  ReadOnlyPointerWriteError       Escritura a través de un ``T ptr`` no mutable, a
                                               cualquier profundidad, o llamar a través de él a un
                                               método que modifica su receptor (``v.push(3)`` con
                                               ``v`` un ``Vector<int> ptr``). También a través de
                                               un puntero que captura una lambda, aunque sea
                                               ``ptr mutable``.
   ``SEM016``  InvalidCastError                Conversión sin regla ni hook que la implemente.
   ``SEM017``  ExpressionTooDeepError          Anidamiento por encima del límite.
   ``SEM018``  UnknownHookError                Un ``__x__`` marcado como hook que no es del conjunto.
   ``SEM019``  VisibilityViolationError        Acceso a algo fuera de su visibilidad.
   ``SEM021``  TraitNotSatisfiedError          El tipo no cumple el contrato del trait. También
                                               una cota ``<T: X>`` cuyo ``X`` no es un trait de
                                               este archivo ni un concepto (``Eq``, ``Ord``,
                                               ``Hash``, ``Print``), y una instancia de una cota
                                               de trait con un tipo que no declara ``@impl(X)``.
   ``SEM022``  InvalidDunderSignatureError     Un método dunder con firma inválida.
   ``SEM023``  UseAfterFreeError               Uso de un valor destruido con ``free``.
   ``SEM024``  DoubleFreeError                 ``free`` sobre un valor ya destruido.
   ``SEM025``  InvalidValueTypeError           ``void`` como tipo de un valor (solo vale como retorno),
                                               también como argumento de tipo (``Vector<void>``).
   ``SEM026``  InfiniteSizeTypeError           Un ``struct`` que se contiene a sí mismo por valor.
   ``SEM027``  TypeArityError                  Un genérico usado con un número de argumentos que no es el suyo.
                                               También la variante de un enum genérico sin sus
                                               argumentos (``Res.Ok(5)``, ``Ok(5)``, ``Vacio``).
   ``SEM028``  IncompleteStructLiteralError    Un literal de struct que deja campos sin valor.
   ``SEM030``  NonExhaustiveMatchError         **Aviso**: un ``match`` sobre un ``enum`` deja variantes sin cubrir.
                                               También sobre un ``T?`` sin ``case null`` (o, si ``T``
                                               es un enum, sin una variante y sin ``case v``), y
                                               sobre un ``E ptr``, que se desreferencia solo.
   ``SEM031``  NotIndexableError               ``x[i]`` sobre un primitivo, que nunca puede declarar
                                               ``__index__``; o ``s[i] = c`` sobre un ``str``, que se
                                               lee por índice pero es inmutable.
   ``SEM032``  ImplicitOwnershipCopyError      Ligar a otro nombre —un ``var``, un parámetro por
                                               valor, una asignación o el campo de un literal— un
                                               valor con destructor sin ``move``. También
                                               ``return g;`` / ``throw g;`` con ``g`` una global
                                               con destructor: entregaría una copia y la global
                                               seguiría siendo dueña (``return move g;``). Y
                                               ``x ?? d`` con un contenido con destructor (se
                                               desenvuelve con ``match``, que presta).
   ``SEM033``  ContainerOverflowError          Mas ``push`` seguidos que espacios reservados en la
                                               declaracion (``int vec.Vector v[2];``). Solo cuando la
                                               cuenta no depende de la ejecucion; el resto sigue
                                               fallando en ejecucion.
   ``SEM034``  ThrowInDestructorError          Un ``throw`` escrito dentro de un ``__free__``: un
                                               destructor nunca puede lanzar (ver ``RT021``).
   ``SEM035``  LiteralDivisionByZeroError      ``x / 0`` o ``x % 0`` con un cero entero literal. Un
                                               divisor que vale cero al ejecutar es ``EXC001``.
   ``SEM036``  MoveOutOfBorrowError            Ceder (``move``, ``return``, ``throw``) algo con
                                               destructor a través de un puntero (o un elemento de
                                               un bloque): es de otro y se destruiría dos veces. Se
                                               lee con ``&``; un elemento se saca con ``mem.take``.
                                               También lo que liga un patrón (``case E.A(x)``,
                                               ``case v`` sobre un ``T?``): es del sujeto. Y lo
                                               que captura una lambda (``return x`` dentro de
                                               ella): es un préstamo.
   ``SEM037``  DanglingAddressError            ``return &x`` (o ``&x.campo``) con ``x`` local: muere
                                               al salir y el llamador recibiría un puntero a nada.
   ``SEM038``  GenericOwnerCopyError           Un genérico que COPIA su ``T`` (``Vector.get``,
                                               ``v[i]``, ``v.filter``, ``func.map``, ``func.fold``)
                                               instanciado con un tipo con destructor: la
                                               copia y el original serían dos dueños. Sale en la
                                               llamada y dice dónde copia; se usa ``at`` (préstamo)
                                               o ``take``.
   ``SEM039``  GenericNotOrderableError        Un genérico que ORDENA su ``T`` (``a < b``,
                                               ``Vector.sort``) instanciado con un tipo que no se
                                               ordena (un struct sin ``__cmp__``, ``bool``, un
                                               ``T?``). Sale en la llamada y dice dónde ordena.
                                               También una cota ``Ord`` que la instancia no cumple
                                               (en la llamada o en la anotación ``Par<P, int>``),
                                               diciendo qué cota y desde qué argumento.
   ``SEM040``  UninitializedVariableError      ``var T x;`` sin valor, en cualquier ámbito: valdría
                                               ``null`` aunque ``T`` no lo admita. Se escribe el
                                               valor inicial (``var int x = 0;``), o ``T?`` y
                                               ``= null``. ``const type T;`` no es una variable.
   ``SEM041``  TemporaryMutationError          Escribir en una COPIA temporal: ``v[i].n = 5`` o
                                               ``v[i].push(x)`` con ``__index__`` (devuelve por
                                               valor), o ``f().n = 5``. El cambio se perdería; se
                                               pide el elemento prestado y mutable
                                               (``v.at_mut(i)``).
   ``SEM042``  NotCallableError                Llamar a algo que no es una función: ``n(3)`` con ``n``
                                               un ``int``, ``p.noexiste()``, un campo que no es
                                               ``fn(...)``, un módulo. Se llama a una función
                                               declarada, a un valor ``fn(...) -> R`` o a un método.
                                               También un método o un campo sobre un PRIMITIVO
                                               (``s.len()``, ``n.abs()``, ``s.length``), con la
                                               pista de suriaX (``len(s)``, ``text.upper(s)``).
   ``SEM043``  UnboundedGenericMemberError     Un método, un campo o ``[]`` sobre un valor de un
                                               parámetro de tipo que ninguna cota promete
                                               (``f.aplica(x)`` con ``f: F`` sin un trait que lo
                                               pida). Lo que el lenguaje hace solo (``==``, ``<``,
                                               ``hash``, copiar, destruir, f-string) sigue
                                               valiendo. También un parámetro de tipo sin la cota
                                               que pide lo que recibe (``area_of<T: Forma>(x)`` con
                                               ``x: U`` sin ``U: Forma``, o ``Par<U>`` con
                                               ``Par<K: Print>``). ``Ord`` y ``Hash`` que el
                                               parámetro no promete se comprueban por instancia
                                               dentro de una función (``Par<U>`` con ``Par<K: Ord>``
                                               en ``fn f<U>``); en la declaración de otro tipo, no.
   ``SEM044``  InvalidFunctionValueError       Un nombre que no puede ser un valor función: un
                                               prototipo (host / ``#extern``), una genérica, un
                                               dunder, un método genérico o de un tipo genérico, o uno con
                                               receptor por valor que tiene destructor.
   ``SEM045``  GlobalUsedTooEarlyError         El valor inicial de una global (o una sentencia de
                                               nivel superior) usa una global declarada MÁS ABAJO:
                                               el nivel superior se ejecuta en orden. Era ``RT006``.
                                               A través de una función llamada ahí sigue siendo
                                               ``RT006``.
   ``SEM046``  DuplicateCaseError              Dos ramas de un ``match`` con el mismo patrón (el mismo
                                               literal, la misma variante o el mismo nombre): gana
                                               la primera y la otra no se ejecuta nunca. También una
                                               rama detrás de ``case v`` sobre un ``T?`` (salvo
                                               ``case null``).
   ``SEM047``  ExpressionWithoutEffectError    Una sentencia que solo calcula un valor y lo tira:
                                               ``f;`` (la función sin llamar), ``a == b;``, un nombre
                                               o un literal sueltos.
   ``SEM048``  UnreachableCodeWarning          **Aviso**: sentencias detrás de un ``return``,
                                               ``throw``, ``break`` o ``continue`` del mismo bloque.
   ``SEM049``  NarrowerTypeInSignatureWarning  **Aviso**: una función de una librería se ve más que
                                               un tipo de su firma (``fn f() -> P`` con ``private
                                               struct P``): quien la llama no puede nombrar ``P``.
   ``SEM050``  LambdaOutOfPlaceError           Una ``lambda`` fuera del único sitio donde vale: el
                                               argumento de una llamada cuyo parámetro está escrito
                                               ``fn(...) -> R``. En una variable, un campo, un
                                               ``return``, un ``==``, un f-string, un parámetro
                                               ``T`` o ``(fn...)?``, una variante o un prototipo
                                               escaparía. Se usa una función con nombre.
   ``SEM051``  FunctionParameterEscapeError    Un parámetro de tipo ``fn(...) -> R`` usado de otra
                                               forma que llamarlo o pasarlo a otro parámetro de
                                               tipo función (guardarlo, devolverlo, compararlo,
                                               pasarlo a un ``T``): es prestado, puede ser una
                                               lambda. Para guardarlo, ``(fn(...) -> R)?``.
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
.. _RT016-def:
.. _RT017-def:
.. _RT018-def:
.. _RT019-def:
.. _RT020-def:
.. _RT021-def:
.. _RT022-def:
.. _RT023-def:

Un error ``RT`` indica un programa ROTO o una máquina que no puede seguir:
**siempre** termina el programa (código de salida 70) y **no** se puede
atrapar con ``catch``. Lo que tiene arreglo dentro del propio programa es una
excepción ``EXC`` (abajo).


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
   ``RT013``   —                               Retirado: ahora es ``EXC002``.
   ``RT014``   NotIndexableError               Indexación sobre algo que no la admite.
   ``RT015``   CorruptMemoryHandleError        El backend de memoria recibió un handle inválido.
   ``RT016``   —                               Retirado: ahora es ``EXC001``.
   ``RT017``   MissingReturnError              Una función con tipo de retorno terminó sin devolver un valor.
   ``RT019``   StackOverflowError              Desbordamiento de pila: demasiadas llamadas anidadas
                                               (casi siempre, una recursión sin caso base). El límite
                                               lo pone la pila de Python y depende de cuánto anida
                                               cada función.
   ``RT020``   UncaughtThrowError              Un ``throw`` escapó de todo ``try``/``catch`` y terminó el
                                               programa, con el valor lanzado.
   ``RT021``   DestructorThrewError            Un ``__free__`` lanzó (casi siempre llamando a algo
                                               que lanza): un destructor nunca puede lanzar. Si ya
                                               había un ``throw`` subiendo, habría dos a la vez.
   ``RT022``   FinallyThrewError               Un ``finally`` lanzó mientras ya subía otra excepción:
                                               habría dos a la vez y la primera se perdería. Sin otra
                                               en vuelo, un ``throw`` en el ``finally`` es uno más.
   ``RT023``   MemoryLimitError                El programa pasó la memoria máxima que se le dio a la VM
                                               (``suriax-hir --memoria-max``): sus objetos, bloques y
                                               cadenas, contados por la VM, después de recoger las
                                               cadenas que ya nadie usa. El intérprete no tiene ese
                                               límite.
   ==========  ==============================  ====================================================

.. _exc-errores:

EXC — excepciones del runtime (se pueden atrapar)
--------------------------------------------------

.. _EXC001-def:
.. _EXC002-def:
.. _EXC003-def:
.. _EXC004-def:
.. _EXC005-def:

Una operación sin resultado posible no mata el programa: el runtime **lanza**
un valor, y el ``try`` más cercano lo recibe igual que un ``throw`` del
usuario. Los tipos están en la librería estándar ``excepciones``, y cada uno
trae ``mensaje``, ``linea`` y ``columna``:

.. code-block:: srcx

   #from io #import stdp
   #import excepciones as exc

   fn main() -> int {
       var int cero = 0;
       try { stdp.println(f"{10 / cero}"); }
       catch (exc.DivisionPorCero e) { stdp.println(e.mensaje); };
       return 0;
   }

La misma librería es el **repertorio** de excepciones de suriaX, como el de
Python: además de las que lanza el runtime trae las de uso general, para que
el programa las lance sin inventar un tipo por cada error común —
``ValorInvalido`` (``ValueError``), ``NoEncontrado`` (``KeyError``),
``NoImplementado`` (``NotImplementedError``) y ``EstadoInvalido``
(``RuntimeError``)—. Estas solo llevan ``mensaje``:
``throw exc.ValorInvalido{ mensaje: "edad negativa" };``.

``catch (e)`` sin tipo también las atrapa, sin importar la librería. Si nadie
las atrapa, el programa termina con ``excepción no capturada — EXCxxx`` y el
código de salida 70. La serie ``test/e2e/excepciones/`` (programas 13 y 14)
las muestra en uso.

.. table::
   :widths: auto

   ==========  ========================================  ================================================
   Código      Tipo que se atrapa                        Cuándo
   ==========  ========================================  ================================================
   ``EXC001``  ``excepciones.DivisionPorCero``           ``a / b`` o ``a % b`` entre enteros con ``b``
                                                         igual a cero al ejecutar (con ``float`` no:
                                                         IEEE-754 da ``inf``/``nan``). Antes ``RT016``.
   ``EXC002``  ``excepciones.IndiceFueraDeRango``        ``v[i]`` o un acceso a memoria con ``i`` fuera
                                                         de ``[0, tamaño)``. Se comprueba antes de
                                                         acceder: el programa puede seguir. Antes
                                                         ``RT013``.
   ``EXC003``  ``excepciones.ErrorDeArchivo``            Una operación de archivo de ``sistema`` que no
                                                         se pudo hacer: no existe, es una carpeta, no es
                                                         UTF-8, falta permiso. El mensaje nombra la ruta
                                                         y es el mismo en todas las máquinas.
   ``EXC004``  ``excepciones.ConversionInvalida``        Un texto que no se puede convertir:
                                                         ``text.parse_int("12a")``,
                                                         ``text.parse_float(".5")``, un número que no
                                                         cabe, o unos bytes que no son UTF-8
                                                         (``text.from_bytes``).
   ``EXC005``  ``excepciones.DesplazamientoInvalido``    ``x << n`` o ``x >> n`` con ``n`` fuera de
                                                         ``[0, 64)``: con 64 bits no hay resultado.
   ==========  ========================================  ================================================

.. _vm-errores:

VM — backend nativo
--------------------

``suriax-hir`` da la misma salida y los mismos códigos ``RT``/``EXC`` que el
intérprete. Los ``VM`` son lo contrario: un programa **correcto** que la VM
todavía no sabe ejecutar. Los detecta el lowering a MIR, con su posición, y
salen como las demás construcciones que el MIR no cubre (``--check-mir``,
``--run``, ``--mir``), antes de ejecutar nada; las vistas (``--summary``,
``--pretty``, ``--verify``) siguen leyendo el ``.phir``. ``suri --run
compiler`` consulta ``--check-mir`` antes de elegir motor: ante un ``VM``
avisa y lo ejecuta el intérprete.

.. _VM001-def:
.. _VM002-def:
.. _VM003-def:
.. _VM004-def:
.. _VM005-def:

.. table::
   :widths: auto

   ==========  ====================================================================================
   Código      Cuándo
   ==========  ====================================================================================
   ``VM001``   El programa usa funciones como valores: una función suya recibe, devuelve o guarda
               un ``fn(A) -> R`` (también dentro de un ``?`` o de un genérico), o una expresión
               lo produce (``aplica(doble, 2)``, ``v.sort_by(compara)``). Sale en la posición de
               la función o de la expresión, con el fuente y el tipo, y dice cómo ejecutarlo:
               ``python V0/main.py <fuente>.srcx --run interpreter``. Una función de una
               LIBRERÍA así (``Vector.sort_by``) no impide correr el programa: se baja a un
               cuerpo que da ``VM001`` como error de ejecución si se llega a llamar.
   ``VM002``   El programa desenvuelve un ``T?`` (``case v`` en un ``match``, una variante sobre un
               sujeto ``E?``, ``x ?? d``) o declara un enum genérico (``enum Res<T, E>``), en
               cualquier unidad cargada. Sale en la posición del patrón, del operador o de la
               declaración, con el fuente, y dice cómo ejecutarlo:
               ``python V0/main.py <fuente>.srcx --run interpreter``.
   ``VM003``   El programa llama a algo que promete una COTA y no un tipo: ``print(x)`` con
               ``T: Print`` o un método de un trait con ``T: Forma``. Su destino depende de la
               instancia y la VM todavía no despacha por ella. Sale en la posición de la llamada,
               con el fuente y el parámetro, y dice cómo ejecutarlo:
               ``python V0/main.py <fuente>.srcx --run interpreter``.
   ``VM004``   El programa usa una ``lambda``: la VM no tiene ni el valor ni el marco que lee. Sale
               en la posición de la lambda (antes que ``VM001``), con el fuente, y dice cómo
               ejecutarlo: ``python V0/main.py <fuente>.srcx --run interpreter``.
   ``VM005``   El programa escribe un primitivo con ``print(x)`` (``print(5)``): la VM no tiene
               cómo escribir sin el ``__write__`` de ``io``. Sale en la posición de la llamada, con
               el fuente y el tipo; se escribe con un f-string (``stdp.print(f"{x}")``) o se
               ejecuta con el intérprete.
   ==========  ====================================================================================

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
   * - ``WEB103``
     - Función usada como valor (``fn(A) -> R``). Se reporta en la
       contención, una vez por línea y con **cualquier** política: no es una
       capacidad que un perfil pueda habilitar. La ejecuta el intérprete
     - Generador
   * - ``WEB104``
     - Una ``lambda``. Como ``WEB103``, en la contención y con **cualquier**
       política, en la posición de la lambda (y en lugar de ``WEB103`` ahí).
       La ejecuta el intérprete
     - Generador
   * - ``WEB900``
     - ``.phir`` ilegible o esquema no soportado
     - Lector
   * - ``WEB901``
     - Nodo del HIR sin variante
     - Lector

.. _ice-errores:

ICE — error interno del compilador
-----------------------------------

Todos los demás códigos dicen que el **programa** está mal. ``ICE000`` dice lo
contrario: el programa pudo estar bien y el que falló es el compilador —una
excepción de Python que ninguna fase esperaba—. Mezclar los dos es el peor
error posible en un compilador educativo: quien aprende buscaría en su código
un fallo que no existe.

Por eso tiene su propio **código de salida, 6** (distinto del ``1`` de "hay
errores"), y se muestra como lo mostraría Python: primero el traceback de la
excepción original —dónde falló dentro del compilador y por qué— y después la
fase y el archivo que se procesaba. No señala una línea del fuente, porque no
ocurrió en ninguna.

.. code-block:: text

   Traceback (most recent call last):
     File ".../V0/src/frontend/semantic/scope_resolver.py", line 812, in visit_expr
       tipo = self.tabla[nombre]
              ~~~~~~~~~~^^^^^^^^
   KeyError: 'x'

   ICE000: error interno del compilador en la fase 'semantica'
     procesando: prog.srcx
     esto es un fallo del compilador, no de tu programa

.. _ICE000-def:

.. table::
   :widths: auto

   ==========  ==============================  ====================================================
   Código      Clase                           Cuándo
   ==========  ==============================  ====================================================
   ``ICE000``  InternalCompilerError           El compilador lanzó una excepción que ninguna fase
                                               esperaba. Es un bug: repórtalo con el archivo y la
                                               traza (``--debug`` la guarda en ``dumps/``).
   ==========  ==============================  ====================================================

**Un ICE es un comportamiento indefinido (UB) del compilador.** Cada programa
que se sabe que hoy termina en ``ICE000`` se documenta en el catálogo de UB de
``c_errorstfix.md`` (en la raíz del repositorio), junto al error propio que
debería producir. Cuando ese error existe, el caso sale del catálogo: el
objetivo es que la lista de ICE conocidos se vaya vaciando. Así pasó con la
recursión infinita, que era un ICE y hoy es ``RT019``.

En el canal del editor (``--emit-diagnostics``) llega como un diagnóstico más,
en la línea 1, con la excepción y el sitio del compilador en el mensaje;
``SURIAX_ICE_TRACEBACK=1`` añade la traza completa.

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
   ``panic``       Violaciones de memoria (use-after-free/move, doble free/move) y
                   errores internos del compilador (``ICE000``).
   ==============  ==========================================================

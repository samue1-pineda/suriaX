2. Lexical analysis
====================

el compilador de suriaX luego de recibir el codigo en .srcx o .libsrx pasa por esta fase para tokenizar todo el codigo facilitando la entrada del parser.

el analizador lexico o tambien llamado 'lexer' determina la manera en la que el texto esta codificado(UTF-8 generalmente) y decodifica el texto en caracteres unicode

luego, el lexer usa el texto en unicode para generar un conjunto de tokens. el tipo de token generado generalmente depende en el siguiente caracter unicode generado a procesar
asi, tambien existen algunos comportamientos especiales en el lexer que, dependen del primer unicode que no ha sido procesado


la siguiente lista muestra el conjunto de unicodes con referencias que contienen mas informacion.

.. _unicode-ref:

.. table:: Soporte Unicode del compilador
    :width: 100%
    :widths: auto
    :align: center

    +--------------------------------------+------------------------------+-----------------------------------------------------------+
    | Elemento                             | Unicode                      | Descripción                                               |
    +======================================+==============================+===========================================================+
    | Codificación del código fuente       | UTF-8 → Unicode              | El archivo fuente se decodifica a Unicode antes del       |
    |                                      |                              | análisis léxico.                                          |
    +--------------------------------------+------------------------------+-----------------------------------------------------------+
    | Unidad de procesamiento              | U+0000 – U+10FFFF            | El lexer procesa puntos de código Unicode en lugar de     |
    |                                      |                              | bytes individuales.                                       |
    +--------------------------------------+------------------------------+-----------------------------------------------------------+
    | Espacios en blanco                   | White_Space                  | Se reconocen los caracteres Unicode clasificados como     |
    |                                      |                              | espacios en blanco definidos por Unicode.                 |
    +--------------------------------------+------------------------------+-----------------------------------------------------------+
    | Saltos de línea                      | LF, CR, CRLF                 | Se reconocen las distintas representaciones de fin de     |
    |                                      |                              | línea durante el análisis léxico.                         |
    +--------------------------------------+------------------------------+-----------------------------------------------------------+
    | Identificadores                      | XID_Start / XID_Continue     | Los identificadores pueden utilizar caracteres válidos    |
    |                                      |                              | definidos por Unicode.                                    |
    +--------------------------------------+------------------------------+-----------------------------------------------------------+
    | Literales de cadena                  | Todos los code points válidos| Las cadenas almacenan texto Unicode sin pérdida de        |
    |                                      |                              | información.                                              |
    +--------------------------------------+------------------------------+-----------------------------------------------------------+
    | Literales de carácter                | Un code point Unicode        | Un literal de carácter representa exactamente un punto    |
    |                                      |                              | de código Unicode.                                        |
    +--------------------------------------+------------------------------+-----------------------------------------------------------+
    | Secuencias de escape                 | \uXXXX, \UXXXXXXXX *(futuro)*| Permitirá representar caracteres Unicode mediante         |
    |                                      |                              | secuencias de escape.                                     |
    +--------------------------------------+------------------------------+-----------------------------------------------------------+
    | Comentarios                          | —                            | Son reconocidos y descartados por el analizador léxico;   |
    |                                      |                              | no generan tokens.                                        |
    +--------------------------------------+------------------------------+-----------------------------------------------------------+
    | Caracteres inválidos                 | Fuera de Unicode válido      | Se genera ``InvalidUnicodeCharacterError`` (LEX007)       |
    |                                      |                              | cuando se encuentra un punto de código no válido.         |
    +--------------------------------------+------------------------------+-----------------------------------------------------------+

.. _whitespace:

whitespace
-----------

.. _identificadores:

identificadores
----------------------


.. _comentarios:

comentarios
------------

los comentarios no son parte de los string literals por lo cual, todo el texto que se encuentre comentado
sera ignorado por el compilador, existen 2 formas de crear comentarios: 

* "**//**"  para comentarios de una sola linea.

* " **/ -** " y " **- /** "  para comentarios multi linea.

ejemplo de codigo:

.. code-block:: text
   :linenos:
   :emphasize-lines: 1,3,4

   //comentario de una sola linea, ignorado por el compilador
   /-   
   comentario multi linea
   ignorado por el compilador
   -/

.. _palabras reservadas:

palabras reservadas
--------------------

las palabras reservadas son lexemas con un significado fijo dentro de suriaX y no pueden ser usadas como
:ref:`identificadores <identificadores>`. el lexer las reconoce a partir de una secuencia válida de
``XID_Start`` / ``XID_Continue`` (ver :ref:`tabla unicode <unicode-ref>`) que coincide exactamente con una
de las entradas de esta tabla; en caso contrario el lexema se clasifica como
:ref:`IDENTIFIER <identifier-def>`.

.. table:: Palabras reservadas de control y declaración
    :width: 100%
    :widths: auto
    :align: center

    +---------------------------------+------------+--------------------------------------------------------+
    | Token                           | Lexema     | Descripción                                            |
    +=================================+============+========================================================+
    | :ref:`FUNCTION <function-def>`  | ``fn``     | Declara una función.                                   |
    +---------------------------------+------------+--------------------------------------------------------+
    | :ref:`RETURN <return-def>`      | ``return`` | Devuelve el control y, opcionalmente, un valor.        |
    +---------------------------------+------------+--------------------------------------------------------+
    | :ref:`IF <if-def>`              | ``if``     | Ejecuta condicionalmente un bloque.                    |
    +---------------------------------+------------+--------------------------------------------------------+
    | :ref:`ELSE <else-def>`          | ``else``   | Rama alternativa de un :ref:`if <if-def>`.             |
    +---------------------------------+------------+--------------------------------------------------------+
    | :ref:`WHILE <while-def>`        | ``while``  | Bucle controlado por condición.                        |
    +---------------------------------+------------+--------------------------------------------------------+
    | :ref:`MATCH <match-def>`        | ``match``  | Selección estructural por patrones.                    |
    +---------------------------------+------------+--------------------------------------------------------+
    | :ref:`CASE <case-def>`          | ``case``   | Rama de un :ref:`match <match-def>`.                   |
    +---------------------------------+------------+--------------------------------------------------------+
    | :ref:`BREAK <break-def>`        | ``break``  | Interrumpe el bucle o ``match`` actual.                |
    +---------------------------------+------------+--------------------------------------------------------+
    | :ref:`STRUCT <struct-def>`      | ``struct`` | Declara un tipo compuesto por campos.                  |
    +---------------------------------+------------+--------------------------------------------------------+
    | :ref:`ENUM <enum-def>`          | ``enum``   | Declara un tipo enumerado.                             |
    +---------------------------------+------------+--------------------------------------------------------+
    | :ref:`TYPE <type-def>`          | ``type``   | Define un alias a partir de un                         |
    |                                 |            | :ref:`struct <struct-def>`.                            |
    +---------------------------------+------------+--------------------------------------------------------+
    | :ref:`CONST <const-def>`        | ``const``  | Declara un binding inmutable.                          |
    +---------------------------------+------------+--------------------------------------------------------+
    | :ref:`MUTABLE <mutable-def>`    | ``mutable``| Marca un binding como mutable.                         |
    +---------------------------------+------------+--------------------------------------------------------+
    | :ref:`SHARED <shared-def>`      | ``shrd``   | Marca un valor como compartido (ver sección            |
    |                                 |            | :ref:`propiedad y memoria <propiedad y memoria>`).     |
    +---------------------------------+------------+--------------------------------------------------------+
    | :ref:`SIZEOF <sizeof-def>`      | ``sizeof`` | Devuelve el tamaño de un tipo o valor.                 |
    +---------------------------------+------------+--------------------------------------------------------+
    | :ref:`AS <as-def-kw>`           | ``as``     | Conversión o aliasing (ver la directiva                |
    |                                 |            | :ref:`as <as-def>`).                                   |
    +---------------------------------+------------+--------------------------------------------------------+
    | :ref:`TEST <test_fn-def>`       | ``test``   | Función nativa de prueba. NO confundir con             |
    |                                 |            | la directiva :ref:`#test <test_directive-def>`.        |
    +---------------------------------+------------+--------------------------------------------------------+

.. _function-def:

FUNCTION (``fn``)
~~~~~~~~~~~~~~~~~~

declara una función. el lexer emite el token ``FUNCTION`` al reconocer el lexema ``fn``; la firma completa
es responsabilidad del :doc:`parser <sintactic_analysis>`.

.. code-block:: text
   :linenos:
   :emphasize-lines: 1

   fn suma(int a, int b) -> int {
       return a + b
   }

.. _return-def:

RETURN (``return``)
~~~~~~~~~~~~~~~~~~~~~

finaliza la ejecución de una :ref:`función <function-def>` y, opcionalmente, devuelve un valor.

.. code-block:: text
   :linenos:
   :emphasize-lines: 2

   fn cuadrado(int x) -> int {
       return x * x
   }

.. _if-def:

IF (``if``)
~~~~~~~~~~~~

ejecuta un bloque solo si la condición se evalúa como :ref:`TRUE <true-def>`.

.. code-block:: text
   :linenos:
   :emphasize-lines: 1

   if x > 0 {
       IO.printf("positivo")
   }

.. _else-def:

ELSE (``else``)
~~~~~~~~~~~~~~~~

rama alternativa asociada a un :ref:`if <if-def>`; se ejecuta cuando la condición es :ref:`FALSE <false-def>`.

.. code-block:: text
   :linenos:
   :emphasize-lines: 3

   if x > 0 {
       IO.printf("positivo")
   } else {
       IO.printf("no positivo")
   }

.. _while-def:

WHILE (``while``)
~~~~~~~~~~~~~~~~~~

repite un bloque mientras la condición se mantenga :ref:`TRUE <true-def>`.

.. code-block:: text
   :linenos:
   :emphasize-lines: 1

   while i < 10 {
       i = i + 1
   }

.. _match-def:

MATCH (``match``)
~~~~~~~~~~~~~~~~~~

selección estructural por patrones. cada rama se introduce con :ref:`case <case-def>`.

.. code-block:: text
   :linenos:
   :emphasize-lines: 1,2,3

   match estado {
       case 0: IO.printf("cero")
       case 1: IO.printf("uno")
   }

.. _case-def:

CASE (``case``)
~~~~~~~~~~~~~~~~

introduce una rama dentro de un :ref:`match <match-def>`.

.. code-block:: text
   :linenos:
   :emphasize-lines: 2

   match x {
       case 1: return true
   }

.. _break-def:

BREAK (``break``)
~~~~~~~~~~~~~~~~~~

interrumpe el bucle o :ref:`match <match-def>` más interno.

.. note::
   en ``t_types.py`` el valor numérico de ``BREAK`` coincide con el de ``COPY`` (ambos ``60``); esta colisión
   debe resolverse en la definición del :class:`TokenType` antes de fijar la documentación de
   :ref:`COPY <copy-def>`.

.. code-block:: text
   :linenos:
   :emphasize-lines: 3

   while true {
       if salir {
           break
       }
   }

.. _struct-def:

STRUCT (``struct``)
~~~~~~~~~~~~~~~~~~~~~

declara un tipo compuesto por campos. suele combinarse con :ref:`type <type-def>` para nombrar el tipo
resultante.

.. code-block:: text
   :linenos:
   :emphasize-lines: 1,2,3,4

   struct {
       str text
       int len
   } string;

.. _enum-def:

ENUM (``enum``)
~~~~~~~~~~~~~~~~

declara un tipo enumerado.

.. code-block:: text
   :linenos:
   :emphasize-lines: 1

   enum Color {
       Rojo, Verde, Azul
   }

.. _type-def:

TYPE (``type``)
~~~~~~~~~~~~~~~~

define un tipo construido a partir de un :ref:`struct <struct-def>` u otro tipo existente.

.. code-block:: text
   :linenos:
   :emphasize-lines: 1

   type Punto = struct { int x int y }

.. _const-def:

CONST (``const``)
~~~~~~~~~~~~~~~~~~

declara un binding inmutable. es el complemento de :ref:`mutable <mutable-def>`.

.. code-block:: text
   :linenos:
   :emphasize-lines: 1

   const IO = #import IO

.. _mutable-def:

MUTABLE (``mutable``)
~~~~~~~~~~~~~~~~~~~~~~~

marca un binding como mutable, permitiendo reasignaciones posteriores.

.. code-block:: text
   :linenos:
   :emphasize-lines: 1

   mutable int contador = 0

.. _shared-def:

SHARED (``shrd``)
~~~~~~~~~~~~~~~~~~

marca un valor como compartido. se relaciona con el modelo de
:ref:`propiedad y memoria <propiedad y memoria>` y puede combinarse con :ref:`@owner <owner-def>`
(p. ej. ``@owner(shrd)``).

.. code-block:: text
   :linenos:
   :emphasize-lines: 1

   shrd int recurso = 0

.. _sizeof-def:

SIZEOF (``sizeof``)
~~~~~~~~~~~~~~~~~~~~~

operador que devuelve el tamaño en memoria de un tipo o de un valor.

.. code-block:: text
   :linenos:
   :emphasize-lines: 1

   int n = sizeof(int)

.. _as-def-kw:

AS (``as``)
~~~~~~~~~~~~

realiza conversión de tipos o aliasing. también aparece en la directiva
:ref:`#import ... as ... <import-def>`.

.. code-block:: text
   :linenos:
   :emphasize-lines: 1

   float f = entero as float

.. _test_fn-def:

TEST (``test``)
~~~~~~~~~~~~~~~~

función nativa de prueba. **NO** debe confundirse con la directiva
:ref:`#test <test_directive-def>`: ``test`` sin ``#`` es una función, mientras que ``#test`` es una
directiva del compilador (ver :ref:`directivas <directivas>`).

.. code-block:: text
   :linenos:
   :emphasize-lines: 1

   test "suma basica" {
       assert(suma(2, 3) == 5)
   }

.. _tipos de datos:

tipos de datos
---------------

los tipos de datos primitivos son palabras reservadas que identifican el tipo de un binding o el tipo de
retorno de una :ref:`función <function-def>`. los literales correspondientes (numéricos, de
:ref:`cadena <string-def>` y de :ref:`carácter <char-def>`) se decodifican según la
:ref:`tabla unicode <unicode-ref>`.

.. table:: Tipos de datos primitivos
    :width: 100%
    :widths: auto
    :align: center

    +----------------------------+------------+-------------------------------------------------------------+
    | Token                      | Lexema     | Descripción                                                 |
    +============================+============+=============================================================+
    | :ref:`INT <int-def>`       | ``int``    | Entero.                                                     |
    +----------------------------+------------+-------------------------------------------------------------+
    | :ref:`FLOAT <float-def>`   | ``float``  | Número en coma flotante.                                    |
    +----------------------------+------------+-------------------------------------------------------------+
    | :ref:`CHAR <char-def>`     | ``char``   | Un único code point Unicode.                                |
    +----------------------------+------------+-------------------------------------------------------------+
    | :ref:`STRING <string-def>` | ``str``    | Secuencia de code points Unicode.                           |
    +----------------------------+------------+-------------------------------------------------------------+
    | :ref:`BOOL <bool-def>`     | ``bool``   | Valor lógico (:ref:`true <true-def>` /                      |
    |                            |            | :ref:`false <false-def>`).                                  |
    +----------------------------+------------+-------------------------------------------------------------+
    | :ref:`VOID <void-def>`     | ``void``   | Ausencia de tipo / valor.                                   |
    +----------------------------+------------+-------------------------------------------------------------+
    | :ref:`NULL <null-def>`     | ``null``   | Valor nulo (ver :ref:`NULLABLE <nullable-def>`).            |
    +----------------------------+------------+-------------------------------------------------------------+
    | :ref:`TRUE <true-def>`     | ``true``   | Literal booleano verdadero.                                 |
    +----------------------------+------------+-------------------------------------------------------------+
    | :ref:`FALSE <false-def>`   | ``false``  | Literal booleano falso.                                     |
    +----------------------------+------------+-------------------------------------------------------------+

.. _int-def:

INT (``int``)
~~~~~~~~~~~~~~

tipo entero. un literal entero mal formado o fuera de rango produce
:ref:`LEX005 <LEX005-def>` / :ref:`LEX006 <LEX006-def>`.

.. code-block:: text
   :linenos:
   :emphasize-lines: 1

   int edad = 25

.. _float-def:

FLOAT (``float``)
~~~~~~~~~~~~~~~~~~

número en coma flotante. múltiples puntos decimales generan :ref:`LEX006 <LEX006-def>`.

.. code-block:: text
   :linenos:
   :emphasize-lines: 1

   float pi = 3.1416

.. _char-def:

CHAR (``char``)
~~~~~~~~~~~~~~~~

representa exactamente un :ref:`code point Unicode <unicode-ref>`. un literal vacío o con más de un
carácter produce :ref:`LEX011 <LEX011-def>`.

.. code-block:: text
   :linenos:
   :emphasize-lines: 1

   char inicial = 'A'

.. _string-def:

STRING (``str``)
~~~~~~~~~~~~~~~~~

secuencia de code points Unicode almacenada sin pérdida (ver :ref:`tabla unicode <unicode-ref>`). una
cadena sin cierre produce :ref:`LEX002 <LEX002-def>`.

.. code-block:: text
   :linenos:
   :emphasize-lines: 1

   str saludo = "hola!"

.. _bool-def:

BOOL (``bool``)
~~~~~~~~~~~~~~~~

valor lógico cuyos literales son :ref:`true <true-def>` y :ref:`false <false-def>`.

.. code-block:: text
   :linenos:
   :emphasize-lines: 1

   bool activo = true

.. _void-def:

VOID (``void``)
~~~~~~~~~~~~~~~~

ausencia de tipo; se usa típicamente como tipo de retorno de funciones sin valor.

.. code-block:: text
   :linenos:
   :emphasize-lines: 1

   fn log(str msg) -> void { IO.printf(msg) }

.. _null-def:

NULL (``null``)
~~~~~~~~~~~~~~~~

valor nulo. se relaciona con el modificador :ref:`NULLABLE <nullable-def>` (``?``).

.. code-block:: text
   :linenos:
   :emphasize-lines: 1

   int? valor = null

.. _true-def:

TRUE (``true``)
~~~~~~~~~~~~~~~~

literal booleano verdadero (ver :ref:`BOOL <bool-def>`).

.. code-block:: text
   :linenos:
   :emphasize-lines: 1

   bool listo = true

.. _false-def:

FALSE (``false``)
~~~~~~~~~~~~~~~~~~

literal booleano falso (ver :ref:`BOOL <bool-def>`).

.. code-block:: text
   :linenos:
   :emphasize-lines: 1

   bool listo = false

.. _operator:

operator
---------

los operadores son tokens de uno o dos caracteres reconocidos por el lexer. los operadores de dos
caracteres (``==``, ``!=``, ``<=``, ``>=``) requieren mirar el siguiente code point antes de decidir el
token, tal como se describe en la introducción de este capítulo.

operadores aritméticos
~~~~~~~~~~~~~~~~~~~~~~~~~

.. table:: Operadores aritméticos
    :width: 90%
    :widths: auto
    :align: center

    +-------------------------------+--------+--------------------------------+
    | Token                         | Lexema | Descripción                    |
    +===============================+========+================================+
    | :ref:`ASSIGN <assign-def>`    | ``=``  | Asignación.                    |
    +-------------------------------+--------+--------------------------------+
    | :ref:`PLUS <plus-def>`        | ``+``  | Suma.                          |
    +-------------------------------+--------+--------------------------------+
    | :ref:`MINUS <minus-def>`      | ``-``  | Resta.                         |
    +-------------------------------+--------+--------------------------------+
    | :ref:`MULTIPLY <multiply-def>`| ``*``  | Multiplicación.                |
    +-------------------------------+--------+--------------------------------+
    | :ref:`DIVIDE <divide-def>`    | ``/``  | División.                      |
    +-------------------------------+--------+--------------------------------+

.. _assign-def:

ASSIGN (``=``)
^^^^^^^^^^^^^^^

asigna un valor a un binding. no debe confundirse con :ref:`EQUAL <equal-def>` (``==``).

.. code-block:: text
   :linenos:
   :emphasize-lines: 1

   x = 10

.. _plus-def:

PLUS (``+``)
^^^^^^^^^^^^^

.. code-block:: text
   :linenos:

   int total = a + b

.. _minus-def:

MINUS (``-``)
^^^^^^^^^^^^^^

.. note::
   el lexer debe distinguir ``-`` (``MINUS``) de las secuencias :ref:`T_OWNER <t-owner-def>` (``->``) y de
   los delimitadores de comentario multilínea (ver :ref:`comentarios <comentarios>`).

.. code-block:: text
   :linenos:

   int dif = a - b

.. _multiply-def:

MULTIPLY (``*``)
^^^^^^^^^^^^^^^^^

.. code-block:: text
   :linenos:

   int area = base * altura

.. _divide-def:

DIVIDE (``/``)
^^^^^^^^^^^^^^^

.. note::
   ``/`` requiere mirar el siguiente code point para distinguir la división de los
   :ref:`comentarios <comentarios>` (``//`` y ``/-``).

.. code-block:: text
   :linenos:

   float r = a / b

operadores de comparación
~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. table:: Operadores de comparación
    :width: 90%
    :widths: auto
    :align: center

    +-------------------------------------------+--------+---------------------------+
    | Token                                     | Lexema | Descripción               |
    +===========================================+========+===========================+
    | :ref:`EQUAL <equal-def>`                  | ``==`` | Igualdad.                 |
    +-------------------------------------------+--------+---------------------------+
    | :ref:`NOT_EQUAL <not-equal-def>`          | ``!=`` | Desigualdad.              |
    +-------------------------------------------+--------+---------------------------+
    | :ref:`LESS <less-def>`                    | ``<``  | Menor que.                |
    +-------------------------------------------+--------+---------------------------+
    | :ref:`LESS_EQUAL <less-equal-def>`        | ``<=`` | Menor o igual.            |
    +-------------------------------------------+--------+---------------------------+
    | :ref:`GREATER <greater-def>`              | ``>``  | Mayor que.                |
    +-------------------------------------------+--------+---------------------------+
    | :ref:`GREATER_EQUAL <greater-equal-def>`  | ``>=`` | Mayor o igual.            |
    +-------------------------------------------+--------+---------------------------+

.. _equal-def:

EQUAL (``==``)
^^^^^^^^^^^^^^^

compara igualdad; no confundir con :ref:`ASSIGN <assign-def>` (``=``).

.. code-block:: text
   :linenos:

   if a == b { }

.. _not-equal-def:

NOT_EQUAL (``!=``)
^^^^^^^^^^^^^^^^^^^

.. code-block:: text
   :linenos:

   if a != b { }

.. _less-def:

LESS (``<``)
^^^^^^^^^^^^^

.. note::
   ``<`` debe distinguirse de :ref:`LESS_EQUAL <less-equal-def>` (``<=``) y de
   :ref:`R_OWNER <r-owner-def>` (``<-``).

.. code-block:: text
   :linenos:

   if a < b { }

.. _less-equal-def:

LESS_EQUAL (``<=``)
^^^^^^^^^^^^^^^^^^^^

.. code-block:: text
   :linenos:

   if a <= b { }

.. _greater-def:

GREATER (``>``)
^^^^^^^^^^^^^^^^

.. code-block:: text
   :linenos:

   if a > b { }

.. _greater-equal-def:

GREATER_EQUAL (``>=``)
^^^^^^^^^^^^^^^^^^^^^^^^

.. code-block:: text
   :linenos:

   if a >= b { }

operadores lógicos
~~~~~~~~~~~~~~~~~~~~

estos operadores son palabras reservadas (no símbolos) y se reconocen igual que el resto de
:ref:`palabras reservadas <palabras reservadas>`.

.. table:: Operadores lógicos
    :width: 90%
    :widths: auto
    :align: center

    +----------------------------+----------+--------------------------------+
    | Token                      | Lexema   | Descripción                    |
    +============================+==========+================================+
    | :ref:`AND <and-def>`       | ``and``  | Conjunción lógica.             |
    +----------------------------+----------+--------------------------------+
    | :ref:`OR <or-def>`         | ``or``   | Disyunción lógica.             |
    +----------------------------+----------+--------------------------------+
    | :ref:`NOT <not-def>`       | ``not``  | Negación lógica.               |
    +----------------------------+----------+--------------------------------+

.. _and-def:

AND (``and``)
^^^^^^^^^^^^^^

.. code-block:: text
   :linenos:

   if a > 0 and b > 0 { }

.. _or-def:

OR (``or``)
^^^^^^^^^^^^

.. code-block:: text
   :linenos:

   if a > 0 or b > 0 { }

.. _not-def:

NOT (``not``)
^^^^^^^^^^^^^^

.. code-block:: text
   :linenos:

   if not activo { }

.. _propiedad y memoria:

propiedad y memoria
--------------------

suriaX expone un modelo explícito de propiedad y gestión de memoria. los siguientes tokens marcan
ownership, punteros, direcciones y nulabilidad. la semántica completa (move, borrow, lifetimes) se valida
en etapas posteriores del compilador, no en el lexer.

.. table:: Tokens de propiedad y memoria
    :width: 100%
    :widths: auto
    :align: center

    +--------------------------------+-----------+-------------------------------------------------+
    | Token                          | Lexema    | Descripción                                     |
    +================================+===========+=================================================+
    | :ref:`OWNER <owner-def>`       | ``@owner``| Anotación de propiedad; combinable, p. ej.      |
    |                                |           | ``@owner(shrd)``.                               |
    +--------------------------------+-----------+-------------------------------------------------+
    | :ref:`POINTER <pointer-def>`   | ``ptr``   | Tipo puntero.                                   |
    +--------------------------------+-----------+-------------------------------------------------+
    | :ref:`ADDRESS <address-def>`   | ``&``     | Operador de dirección.                          |
    +--------------------------------+-----------+-------------------------------------------------+
    | :ref:`NULLABLE <nullable-def>` | ``?``     | Marca un tipo como nulable (admite              |
    |                                |           | :ref:`null <null-def>`).                        |
    +--------------------------------+-----------+-------------------------------------------------+
    | :ref:`T_OWNER <t-owner-def>`   | ``->``    | Transferencia de propiedad / tipo de retorno.   |
    +--------------------------------+-----------+-------------------------------------------------+
    | :ref:`R_OWNER <r-owner-def>`   | ``<-``    | Recepción de propiedad.                         |
    +--------------------------------+-----------+-------------------------------------------------+

.. note::
   los lexemas ``COPY``, ``DELETE``, ``FREE``, ``ALLOC`` y ``MAKE`` existen en :class:`TokenType` pero su
   sintaxis y semántica todavía no están especificadas en el diseño del lenguaje; se documentarán cuando se
   fijen. la entrada :ref:`COPY <copy-def>` depende además de resolver la colisión de valor con
   :ref:`BREAK <break-def>`.

.. _owner-def:

OWNER (``@owner``)
~~~~~~~~~~~~~~~~~~~

anotación de propiedad escrita con ``@``. puede combinarse con otros modificadores, por ejemplo
``@owner(shrd)`` para propiedad compartida (ver :ref:`SHARED <shared-def>`). no debe confundirse con
:ref:`DECORATOR <decorator-def>`, que usa el mismo ``@`` pero se coloca encima de la función. una sintaxis
inválida de ``@`` produce :ref:`LEX012 <LEX012-def>`.

.. code-block:: text
   :linenos:
   :emphasize-lines: 1

   @owner(shrd) ptr int recurso

.. _pointer-def:

POINTER (``ptr``)
~~~~~~~~~~~~~~~~~~

declara un tipo puntero.

.. code-block:: text
   :linenos:
   :emphasize-lines: 1

   ptr int p = &valor

.. _address-def:

ADDRESS (``&``)
~~~~~~~~~~~~~~~~

obtiene la dirección de un valor.

.. code-block:: text
   :linenos:
   :emphasize-lines: 1

   ptr int p = &valor

.. _nullable-def:

NULLABLE (``?``)
~~~~~~~~~~~~~~~~~

marca un tipo como nulable, permitiendo el valor :ref:`null <null-def>`.

.. code-block:: text
   :linenos:
   :emphasize-lines: 1

   int? opcional = null

.. _t-owner-def:

T_OWNER (``->``)
~~~~~~~~~~~~~~~~~

indica transferencia de propiedad y también el tipo de retorno de una :ref:`función <function-def>`. el
lexer debe distinguir ``->`` de :ref:`MINUS <minus-def>` (``-``).

.. code-block:: text
   :linenos:
   :emphasize-lines: 1

   fn crear() -> ptr int { }

.. _r-owner-def:

R_OWNER (``<-``)
~~~~~~~~~~~~~~~~~

indica recepción de propiedad. el lexer debe distinguir ``<-`` de :ref:`LESS <less-def>` (``<``).

.. code-block:: text
   :linenos:
   :emphasize-lines: 1

   destino <- origen

.. _delimitadores:

delimitadores
----------------

los delimitadores son tokens de un único carácter que estructuran el código (agrupación, bloques,
listas y separadores). cada uno se reconoce de forma directa a partir de su code point.

.. table:: Delimitadores
    :width: 100%
    :widths: auto
    :align: center

    +-------------------------------------+--------+--------------------------------------------------+
    | Token                               | Lexema | Descripción                                      |
    +=====================================+========+==================================================+
    | :ref:`L_PAREN <l-paren-def>`        | ``(``  | Paréntesis de apertura.                          |
    +-------------------------------------+--------+--------------------------------------------------+
    | :ref:`R_PAREN <r-paren-def>`        | ``)``  | Paréntesis de cierre.                            |
    +-------------------------------------+--------+--------------------------------------------------+
    | :ref:`L_BRACE <l-brace-def>`        | ``{``  | Llave de apertura (bloque).                      |
    +-------------------------------------+--------+--------------------------------------------------+
    | :ref:`R_BRACE <r-brace-def>`        | ``}``  | Llave de cierre (bloque).                        |
    +-------------------------------------+--------+--------------------------------------------------+
    | :ref:`L_BRACKET <l-bracket-def>`    | ``[``  | Corchete de apertura.                            |
    +-------------------------------------+--------+--------------------------------------------------+
    | :ref:`R_BRACKET <r-bracket-def>`    | ``]``  | Corchete de cierre.                              |
    +-------------------------------------+--------+--------------------------------------------------+
    | :ref:`DOT <dot-def>`                | ``.``  | Acceso a miembro.                                |
    +-------------------------------------+--------+--------------------------------------------------+
    | :ref:`COMMA <comma-def>`            | ``,``  | Separador de elementos.                          |
    +-------------------------------------+--------+--------------------------------------------------+
    | :ref:`SEMICOLON <semicolon-def>`    | ``;``  | Terminador / separador de sentencia.             |
    +-------------------------------------+--------+--------------------------------------------------+
    | :ref:`COLON <colon-def>`            | ``:``  | Anotación / asociación.                          |
    +-------------------------------------+--------+--------------------------------------------------+

.. _l-paren-def:

L_PAREN (``(``) y R_PAREN (``)``)
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. _r-paren-def:

agrupan expresiones y delimitan las listas de argumentos de una :ref:`función <function-def>`.

.. code-block:: text
   :linenos:

   IO.printf("hola")

.. _l-brace-def:

L_BRACE (``{``) y R_BRACE (``}``)
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. _r-brace-def:

delimitan bloques de código y cuerpos de :ref:`struct <struct-def>`.

.. code-block:: text
   :linenos:

   if x > 0 { return x }

.. _l-bracket-def:

L_BRACKET (``[``) y R_BRACKET (``]``)
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. _r-bracket-def:

indexación y literales de colección.

.. code-block:: text
   :linenos:

   int x = lista[0]

.. _dot-def:

DOT (``.``)
~~~~~~~~~~~~

acceso a miembro o método. el lexer lo distingue del punto decimal de un :ref:`FLOAT <float-def>`.

.. code-block:: text
   :linenos:

   IO.printf("hola")

.. _comma-def:

COMMA (``,``)
~~~~~~~~~~~~~~

separa elementos en listas, argumentos o campos.

.. code-block:: text
   :linenos:

   fn suma(int a, int b) -> int { return a + b }

.. _semicolon-def:

SEMICOLON (``;``)
~~~~~~~~~~~~~~~~~~

terminador / separador de sentencia (p. ej. tras la definición de un :ref:`struct <struct-def>` con nombre).

.. code-block:: text
   :linenos:

   struct { int x } punto;

.. _colon-def:

COLON (``:``)
~~~~~~~~~~~~~~

asocia un nombre con un tipo o una definición.

.. code-block:: text
   :linenos:

   __print__ : fn -> str

.. _especiales:

tokens especiales
------------------

los tokens especiales no encajan en las categorías anteriores: incluyen identificadores, decoradores,
métodos dunder, el token de error y el marcador de fin de archivo.

.. table:: Tokens especiales
    :width: 100%
    :widths: auto
    :align: center

    +-------------------------------------+------------+--------------------------------------------------+
    | Token                               | Lexema     | Descripción                                      |
    +=====================================+============+==================================================+
    | :ref:`IDENTIFIER <identifier-def>`  | nombre     | Nombre definido por el usuario.                  |
    +-------------------------------------+------------+--------------------------------------------------+
    | :ref:`DECORATOR <decorator-def>`    | ``@``      | Decorador colocado encima de una función.        |
    +-------------------------------------+------------+--------------------------------------------------+
    | :ref:`DUNDER <dunder-def>`          | ``__foo__``| Método/identificador especial.                   |
    +-------------------------------------+------------+--------------------------------------------------+
    | :ref:`DIRECTIVE <directive-def>`    | ``#``      | Inicio de directiva (ver                         |
    |                                     |            | :ref:`directivas <directivas>`).                 |
    +-------------------------------------+------------+--------------------------------------------------+
    | :ref:`ERROR <error-def>`            | —          | Token sintético emitido ante un error léxico.    |
    +-------------------------------------+------------+--------------------------------------------------+
    | :ref:`EOF <eof-def>`                | —          | Marcador de fin de archivo.                      |
    +-------------------------------------+------------+--------------------------------------------------+

.. _identifier-def:

IDENTIFIER
~~~~~~~~~~~

nombre definido por el usuario. se forma con caracteres ``XID_Start`` / ``XID_Continue``
(ver :ref:`identificadores <identificadores>` y :ref:`tabla unicode <unicode-ref>`). un identificador mal
formado produce :ref:`LEX010 <LEX010-def>`.

.. code-block:: text
   :linenos:

   int contador = 0

.. _decorator-def:

DECORATOR (``@``)
~~~~~~~~~~~~~~~~~~

decorador escrito con ``@`` y colocado encima de la función, de forma análoga a Python. usa el mismo
carácter que :ref:`OWNER <owner-def>`, pero su posición y sintaxis los diferencian. una sintaxis inválida
produce :ref:`LEX012 <LEX012-def>`.

.. code-block:: text
   :linenos:
   :emphasize-lines: 1

   @test
   fn caso() -> void { }

.. _dunder-def:

DUNDER (``__foo__``)
~~~~~~~~~~~~~~~~~~~~~~

identificador especial rodeado por dobles guiones bajos. en librerías, los métodos dunder pueden invocarse
sin los ``__`` (ver :ref:`libsrx <libsrx>`).

.. code-block:: text
   :linenos:

   __print__ : fn -> str

.. _directive-def:

DIRECTIVE (``#``)
~~~~~~~~~~~~~~~~~~

inicia una directiva. el lexer emite el token ``DIRECTIVE`` al encontrar ``#``; la directiva concreta se
identifica en el parser (ver :ref:`directivas <directivas>`). una directiva no reconocida produce
:ref:`LEX009 <LEX009-def>`.

.. code-block:: text
   :linenos:

   #import IO as InputOutput

.. _error-def:

ERROR
~~~~~~

token sintético que el lexer emite cuando encuentra una entrada inválida, acompañado del
:ref:`error léxico <erores lexicos>` correspondiente (``LEX001``–``LEX012``).

.. _eof-def:

EOF
~~~~

marca el fin del archivo de entrada. es el último token de todo flujo y permite al
:doc:`parser <sintactic_analysis>` detectar el final de manera segura; un final inesperado produce
:ref:`LEX008 <LEX008-def>`.

.. _copy-def:

COPY / DELETE / FREE / ALLOC / MAKE
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. warning::
   estos lexemas existen en :class:`TokenType` pero todavía no tienen sintaxis ni semántica definida en el
   diseño del lenguaje. se documentarán cuando se especifiquen. ``COPY`` comparte además el valor numérico
   ``60`` con :ref:`BREAK <break-def>`; esa colisión debe resolverse primero.

.. _directivas:

directivas
-----------

.. _import-def:

.. _extern-def:

.. _export-def:

.. _from-def:

.. _as-def:

.. _test_directive-def:


para inicializar una direciva se indica ``#``,nativamente existen las siguientes directivas:

* ``Import``: importa una libreria, el compilador verifica si esta libreria existe y si es posible usarla

*Todas las librerias deben finalizar con un* : ``#export as ...`` 

.. code-block:: text
   :linenos:
   :emphasize-lines: 3,9,15

    //forma 1

    #import IO

    IO.printf("hola!")

    //forma 2

    const IO=#import IO

    IO.printf("hola numero 2!")

    //tambien puedes añadir un alias de la siguiente forma

    #import IO as InputOutput
    
    InputOutput.printf("hola numero 3!")

* :ref:`export <export-def>`: permite que una libreria o modulo sea exportado y usando globalmente en otros archivos

*export siempre debe tener un alias y esta directiva es obligatoria en archivos:* :ref:`.libsrx <libsrx>`.

.. code-block:: text
   :linenos:
   :emphasize-lines: 12

   //IO.libsrx

    struct{
    str text
    int len
    }string;

   __print__:fn-string//los metodos dunder pueden ser llamados sin __ en librerias
   __printf__:fn->string
   __toString__:fn->string

    #export as IO

si no existe la libreria se arroja un :ref:`LEX003<LEX003-def>`

* :ref:`test<test_directive-def>`: permite probar una etapa del compilador, una generacion o en el caso del HIR/MIR/Backend

probar diferentes IRs y passes usando el mismo front, NO CONFUNDIR CON :ref:`test<test_fn-def>` sin ``#`` el cual es una funcion nativa




.. _erores lexicos:

errores lexicos
-----------------

.. table:: Errores léxicos
    :width: 90%
    :widths: auto
    :align: center


    +-------------------------------+----------------------------+--------------------------------------------------------+
    | nombre                        | codigo                     | descripcion                                            |
    +===============================+============================+========================================================+
    |                               |                            | Se encontró un carácter que no pertenece               |
    | UnexpectedCharacterError      | LEX001                     | al alfabeto del lenguaje o que no puede                |
    |                               |                            | formar parte de ningún token válido.                   |
    +-------------------------------+----------------------------+--------------------------------------------------------+
    |                               |                            | Se alcanzó el final de la línea o del                  |
    | UnterminatedStringError       | LEX002                     | archivo antes de encontrar el delimitador              |
    |                               |                            | de cierre de una cadena.                               |
    +-------------------------------+----------------------------+--------------------------------------------------------+
    |                               |                            | Se alcanzó el final del archivo antes                  |
    | UnterminatedCommentError      | LEX003                     | de encontrar el delimitador de cierre                  |
    |                               |                            | de un comentario de bloque.                            |
    +-------------------------------+----------------------------+--------------------------------------------------------+
    |                               |                            | Se encontró una secuencia de escape                    |
    | InvalidEscapeSequenceError    | LEX004                     | no reconocida dentro de un literal                     |
    |                               |                            | de cadena o de carácter.                               |
    +-------------------------------+----------------------------+--------------------------------------------------------+
    |                               |                            | El valor del literal numérico excede                   |
    | NumericLiteralOverflowError   | LEX005                     | el rango permitido para el tipo                        |
    |                               |                            | correspondiente.                                       |
    +-------------------------------+----------------------------+--------------------------------------------------------+
    |                               |                            | El formato del literal numérico es                     |
    | InvalidNumberFormatError      | LEX006                     | inválido (múltiples puntos, caracteres                 |
    |                               |                            | no permitidos, etc.).                                  |
    +-------------------------------+----------------------------+--------------------------------------------------------+
    |                               |                            | Se encontró un carácter Unicode                        |
    | InvalidUnicodeCharacterError  | LEX007                     | no permitido o una secuencia Unicode                   |
    |                               |                            | mal formada.                                           |
    +-------------------------------+----------------------------+--------------------------------------------------------+
    |                               |                            | Se alcanzó el final del archivo                        |
    | UnexpectedEOFError            | LEX008                     | mientras se esperaba completar                         |
    |                               |                            | un token válido.                                       |
    +-------------------------------+----------------------------+--------------------------------------------------------+
    |                               |                            | La directiva iniciada con ``#``                        |
    | InvalidDirectiveError         | LEX009                     | no es reconocida o presenta                            |
    |                               |                            | una sintaxis inválida.                                 |
    +-------------------------------+----------------------------+--------------------------------------------------------+
    |                               |                            | El identificador no cumple las                         |
    | InvalidIdentifierError        | LEX010                     | reglas de formación del lenguaje                       |
    |                               |                            | (inicio o caracteres inválidos).                       |
    +-------------------------------+----------------------------+--------------------------------------------------------+
    |                               |                            | El literal de carácter está vacío,                     |
    | InvalidCharacterLiteralError  | LEX011                     | contiene más de un carácter o carece                   |
    |                               |                            | de delimitador de cierre.                              |
    +-------------------------------+----------------------------+--------------------------------------------------------+
    |                               |                            | El decorador iniciado con ``@``                        |
    | InvalidDecoratorError         | LEX012                     | no cumple la sintaxis esperada                         |
    |                               |                            | o utiliza un identificador inválido.                   |
    +-------------------------------+----------------------------+--------------------------------------------------------+
    
puedes encontrar el resto de errores documentados en :doc:`errores del compilador<errors>`


.. _end marker:

end marker
-----------


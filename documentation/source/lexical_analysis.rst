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

El conjunto ejecutable es ``KEYWORDS`` en ``V0/include/t_types.py``; esta
tabla lo cubre entero. En la v0.2.0 dejaron de ser palabras reservadas
``region``, ``shrd``, ``na``, ``in``, ``at``, ``new``, ``delete`` y ``make``:
pertenecían al modelo por regiones, retirado con él (ver
:ref:`decision-memoria`). Hoy son identificadores corrientes.

.. table:: Palabras reservadas de control y declaración
    :width: 100%
    :widths: auto
    :align: center

    ==============  ==========================================================
    Lexema          Significado
    ==============  ==========================================================
    ``fn``          Declara una función (:ref:`FUNCTION <function-def>`).
    ``lambda``      Una función sin nombre, como argumento de una llamada
                    (``lambda (int x) -> bool: x > 3``; ver
                    :ref:`lambdas <lambdas>`).
    ``return``      Devuelve el control y, opcionalmente, un valor.
    ``if``          Ejecuta condicionalmente un bloque.
    ``else``        Rama alternativa de un ``if``.
    ``while``       Bucle controlado por condición.
    ``match``       Selección por valor; cada rama es un ``case``.
    ``case``        Rama de un ``match``.
    ``break``       Interrumpe el bucle actual.
    ``continue``    Salta a la siguiente vuelta del bucle.
    ``struct``      Declara un tipo compuesto por campos.
    ``enum``        Declara un tipo enumerado.
    ``type``        Declara un tipo nominal opaco, y es el metatipo.
    ``const``       Binding inmutable.
    ``var``         Binding mutable (es el valor por defecto).
    ``mutable``     Mutabilidad de un puntero, dentro del tipo
                    (``T ptr mutable``). NO califica variables.
    ``ptr``         Tipo puntero, **postfijo** (``int ptr``).
    ``sizeof``      Tamaño de un tipo o valor.
    ``cast``        Conversión explícita: ``cast<T>(x)``.
    ``hook``        Declara un hook del conjunto fijo (``hook fn __print__``).
    ``dunder``      Declara un método especial libre (``dunder fn __x__``).
    ``test``        Bloque de prueba de primer nivel.
    ``throw``       Lanza un error.
    ``try``         Bloque que captura errores.
    ``catch``       Rama que recibe el error de un ``try``.
    ``finally``     Bloque que corre al salir del ``try`` por cualquier camino.
    ``with``        Un recurso, un guardián o un receptor con ámbito.
    ``error``       Tipo unión valor-o-error (``error int``).
    ``public``      Visible para quien importe la librería (por defecto).
    ``private``     Visible dentro del mismo paquete.
    ``internal``    Visible solo dentro del mismo archivo.
    ``free``        Libera una celda a través de su puntero.
    ``move``        Transfiere la propiedad e invalida el origen.
    ==============  ==========================================================

.. table:: Palabras reservadas de tipo y literal
    :width: 100%
    :widths: auto
    :align: center

    ==============  ==========================================================
    Lexema          Significado
    ==============  ==========================================================
    ``int``         Entero con signo (:ref:`INT <int-def>`).
    ``float``       Coma flotante (:ref:`FLOAT <float-def>`).
    ``bool``        Lógico (:ref:`BOOL <bool-def>`).
    ``char``        Un code point Unicode (:ref:`CHAR <char-def>`).
    ``str``         Cadena Unicode (:ref:`STRING <string-def>`).
    ``void``        Ausencia de valor (:ref:`VOID <void-def>`).
    ``true``        Literal booleano verdadero.
    ``false``       Literal booleano falso.
    ``null``        Valor nulo (ver :ref:`NULLABLE <nullable-def>`).
    ``and``         Conjunción lógica.
    ``or``          Disyunción lógica.
    ``not``         Negación lógica.
    ==============  ==========================================================

.. note::
   ``as`` **no** es palabra reservada: solo tiene significado dentro de una
   directiva (``#import io as es``), y fuera de ahí es un identificador
   corriente. Tampoco es un operador de conversión — la única conversión es
   :ref:`cast\<T\>(x) <conversiones>`.

Las secciones siguientes desarrollan las de control y declaración.

.. _function-def:

FUNCTION (``fn``)
~~~~~~~~~~~~~~~~~~

declara una función. el lexer emite el token ``FUNCTION`` al reconocer el lexema ``fn``; la firma completa
es responsabilidad del :doc:`parser <sintactic_analysis>`.

.. code-block:: srcx
   :linenos:
   :emphasize-lines: 1

   fn suma(int a, int b) -> int {
       return a + b;
   }

.. _return-def:

RETURN (``return``)
~~~~~~~~~~~~~~~~~~~~~

finaliza la ejecución de una :ref:`función <function-def>` y, opcionalmente, devuelve un valor.

.. code-block:: srcx
   :linenos:
   :emphasize-lines: 2

   fn cuadrado(int x) -> int {
       return x * x;
   }

.. _if-def:

IF (``if``)
~~~~~~~~~~~~

ejecuta un bloque solo si la condición se evalúa como :ref:`TRUE <true-def>`.

.. code-block:: srcx
   :linenos:
   :emphasize-lines: 4

   #from io #import stdp

   int x = 1;
   if (x > 0) {
       stdp.println("positivo");
   }

.. _else-def:

ELSE (``else``)
~~~~~~~~~~~~~~~~

rama alternativa asociada a un :ref:`if <if-def>`; se ejecuta cuando la condición es :ref:`FALSE <false-def>`.

.. code-block:: srcx
   :linenos:
   :emphasize-lines: 3

   #from io #import stdp

   int x = 1;
   if (x > 0) {
       stdp.println("positivo");
   } else {
       stdp.println("no positivo");
   }

.. _while-def:

WHILE (``while``)
~~~~~~~~~~~~~~~~~~

repite un bloque mientras la condición se mantenga :ref:`TRUE <true-def>`.

.. code-block:: srcx
   :linenos:
   :emphasize-lines: 1

   int i = 0;
   while (i < 10) {
       i = i + 1;
   }

.. _match-def:

MATCH (``match``)
~~~~~~~~~~~~~~~~~~

selección estructural por patrones. cada rama se introduce con :ref:`case <case-def>`.

.. code-block:: srcx
   :linenos:
   :emphasize-lines: 4,5,6

   #from io #import stdp

   int estado = 0;
   match (estado) {
       case 0 { stdp.println("cero"); }
       case 1 { stdp.println("uno"); }
   }

.. _case-def:

CASE (``case``)
~~~~~~~~~~~~~~~~

introduce una rama dentro de un :ref:`match <match-def>`.

.. code-block:: srcx
   :linenos:
   :emphasize-lines: 2

   fn es_uno(int x) -> bool {
       match (x) {
           case 1 { return true; }
       }
       return false;
   }

.. _break-def:

BREAK (``break``)
~~~~~~~~~~~~~~~~~~

interrumpe el bucle o :ref:`match <match-def>` más interno.

.. code-block:: srcx
   :linenos:
   :emphasize-lines: 3

   bool salir = true;
   while (true) {
       if (salir) {
           break;
       }
   }

.. _struct-def:

STRUCT (``struct``)
~~~~~~~~~~~~~~~~~~~~~

declara un tipo compuesto por campos. suele combinarse con :ref:`type <type-def>` para nombrar el tipo
resultante.

.. code-block:: srcx
   :linenos:
   :emphasize-lines: 1,2,3,4

   struct {
       str text;
       int len;
   } Cadena;

.. _enum-def:

ENUM (``enum``)
~~~~~~~~~~~~~~~~

declara un tipo enumerado.

.. code-block:: srcx
   :linenos:
   :emphasize-lines: 1

   enum Color {
       Rojo, Verde, Azul
   };

.. _type-def:

TYPE (``type``)
~~~~~~~~~~~~~~~~

define un tipo construido a partir de un :ref:`struct <struct-def>` u otro tipo existente.

.. code-block:: srcx
   :linenos:
   :emphasize-lines: 1

   const type int8;

.. _const-def:

CONST (``const``)
~~~~~~~~~~~~~~~~~~

declara un binding inmutable. es el complemento de :ref:`mutable <mutable-def>`.

.. code-block:: srcx
   :linenos:
   :emphasize-lines: 1

   const es = #import io;

.. _mutable-def:

MUTABLE (``mutable``)
~~~~~~~~~~~~~~~~~~~~~~~

marca un binding como mutable, permitiendo reasignaciones posteriores.

.. code-block:: srcx
   :linenos:
   :emphasize-lines: 1

   int valor = 0;
   int ptr mutable p = &valor;

.. _sizeof-def:

SIZEOF (``sizeof``)
~~~~~~~~~~~~~~~~~~~~~

operador que devuelve el tamaño en memoria de un tipo o de un valor. El
tamaño lo aporta el hook ``__sizeof__`` del tipo: los primitivos no lo
declaran —su layout es cosa de cada motor— así que ``sizeof(int)`` no
compila (:ref:`SEM001 <SEM001-def>`), igual que ``sizeof`` de un tipo propio
sin el hook o de una función. Dentro de un genérico, ``sizeof`` de su ``T``
lo decide cada instancia, en la llamada. Para un tamaño fijo están los tipos
de ``d_types`` (``sizeof(dt.int32)``).

Entre los paréntesis va un **tipo** o el **nombre de un valor**; se escriben
igual y cuál es lo decide la Semántica, que es la única que sabe en qué
namespace vive ese nombre. Un valor aporta el tamaño de *su* tipo, que es lo
que hace posible preguntar por un tamaño sin saber ya el tipo — y por tanto
imprimirlo:

.. code-block:: srcx
   :linenos:
   :emphasize-lines: 5,6

   #from d_types #import dt_variables as dt
   #from io #import stdpf

   const dt.int32 n = 0;
   int del_tipo  = sizeof(dt.int32);   // 4
   int del_valor = sizeof(n);          // 4, el mismo

   stdpf.printf(cast<str>(sizeof(n)));

.. _test_fn-def:

TEST (``test``)
~~~~~~~~~~~~~~~~

función nativa de prueba. **NO** debe confundirse con la directiva
:ref:`#test <test_directive-def>`: ``test`` sin ``#`` es una función, mientras que ``#test`` es una
directiva del compilador (ver :ref:`directivas <directivas>`).

.. code-block:: srcx
   :linenos:
   :emphasize-lines: 1

   fn suma(int a, int b) -> int { return a + b; }

   test "suma basica" {
       var int r = suma(2, 3);
       expect (r == 5);
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
    | :ref:`BYTE <byte-def>`     | ``byte``   | Entero sin signo de 8 bits (0..255): un octeto.             |
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

tipo entero de 64 bits con signo. un literal se escribe en decimal o, con
prefijo, en hexadecimal (``0xFF``), binario (``0b1010``) u octal (``0o755``),
como en Python; ``_`` separa dígitos (``1_000_000``), solo ENTRE dos. un
literal con prefijo es un **patrón de bits** (la regla de Java): puede usar los
64 bits, y con el bit 63 encendido el valor es negativo
(``0xFFFFFFFFFFFFFFFF`` vale ``-1``). uno mal formado (``0x``, ``0b102``,
``1__0``) o que no cabe en 64 bits produce :ref:`LEX007 <LEX007-def>`.

.. code-block:: srcx
   :linenos:
   :emphasize-lines: 1

   int edad = 25;
   int mascara = 0xFF_00;

.. _float-def:

FLOAT (``float``)
~~~~~~~~~~~~~~~~~~

número en coma flotante: una parte decimal (``3.25``), un exponente
(``1e3``, ``2.5e-3``, ``1E+10``) o los dos. con exponente el literal es
SIEMPRE ``float`` (``1e3`` vale ``1000.0`` y no entra en un ``int``); un
literal con base no lleva exponente (``0x1e3`` es el entero hexadecimal). el
valor es el ``double`` más cercano al decimal escrito, el mismo que da
``text.parse_float`` con el mismo texto. múltiples puntos decimales o un
exponente sin dígitos (``1e+``) generan :ref:`LEX007 <LEX007-def>`; un valor
que no cabe en un ``float`` (``1e400``), :ref:`LEX006 <LEX006-def>`, y
también uno distinto de cero tan pequeño que quedaría en ``0.0``
(``1e-400``): casi seguro es una errata, y si se quiere un cero se escribe
``0.0``. ``text.parse_float`` en cambio da ``0.0`` con ese texto, porque lee
datos y no código.

.. code-block:: srcx
   :linenos:
   :emphasize-lines: 1

   float pi = 3.1416;
   float mil = 1e3;

.. _byte-def:

BYTE (``byte``)
~~~~~~~~~~~~~~~~

un entero SIN signo de 8 bits (0..255): un octeto de un archivo o de un
protocolo. un literal entero que cabe entra donde se espera un ``byte``
(``var byte b = 0xFF;``, ``b == 10``); uno que no cabe es un error. se compara
y se enmascara (``& | ^ ~``); sumar o desplazar se hace en ``int``
(``cast<int>(b)``), y ``cast<byte>(n)`` trunca (módulo 256). en la VM un
bloque de ``byte`` ocupa un byte por celda.

.. code-block:: srcx
   :linenos:
   :emphasize-lines: 1

   byte b = 0x0F;
   byte alto = ~b & 0xF0;

.. _char-def:

CHAR (``char``)
~~~~~~~~~~~~~~~~

representa exactamente un :ref:`code point Unicode <unicode-ref>`. un literal vacío o con más de un
carácter produce :ref:`LEX011 <LEX011-def>`.

.. code-block:: srcx
   :linenos:
   :emphasize-lines: 1

   char inicial = 'A';

.. _string-def:

STRING (``str``)
~~~~~~~~~~~~~~~~~

secuencia de code points Unicode almacenada sin pérdida (ver :ref:`tabla unicode <unicode-ref>`). una
cadena sin cierre produce :ref:`LEX003 <LEX003-def>`.

una f-string (``f"..."``) interpola ``{expresion}``. lo que va entre ``{`` y
``}`` es CÓDIGO, como en Python 3.12 y C#: un literal dentro se escribe tal
cual, sin escapar sus comillas (``f"{len("ab")}"``, ``f"{'}'}"``), y sus
comillas y llaves no cierran nada. un ``\`` fuera de un literal dentro de la
interpolación es :ref:`LEX005 <LEX005-def>`, con la forma correcta en el
mensaje. la interpolación no cruza un salto de línea, y un error dentro de
ella apunta a su línea y columna reales.

.. code-block:: srcx
   :linenos:
   :emphasize-lines: 1

   str saludo = "hola!";
   str largo = f"{len("hola")} letras";

.. _bool-def:

BOOL (``bool``)
~~~~~~~~~~~~~~~~

valor lógico cuyos literales son :ref:`true <true-def>` y :ref:`false <false-def>`.

.. code-block:: srcx
   :linenos:
   :emphasize-lines: 1

   bool activo = true;

.. _void-def:

VOID (``void``)
~~~~~~~~~~~~~~~~

ausencia de tipo; se usa típicamente como tipo de retorno de funciones sin valor.

.. code-block:: srcx
   :linenos:
   :emphasize-lines: 3

   #from io #import stdp

   fn log(str msg) -> void { stdp.println(msg); }

.. _null-def:

NULL (``null``)
~~~~~~~~~~~~~~~~

valor nulo. se relaciona con el modificador :ref:`NULLABLE <nullable-def>` (``?``).

.. code-block:: srcx
   :linenos:
   :emphasize-lines: 1

   int? valor = null;

.. _true-def:

TRUE (``true``)
~~~~~~~~~~~~~~~~

literal booleano verdadero (ver :ref:`BOOL <bool-def>`).

.. code-block:: srcx
   :linenos:
   :emphasize-lines: 1

   bool listo = true;

.. _false-def:

FALSE (``false``)
~~~~~~~~~~~~~~~~~~

literal booleano falso (ver :ref:`BOOL <bool-def>`).

.. code-block:: srcx
   :linenos:
   :emphasize-lines: 1

   bool listo = false;

.. _operator:

operator
---------

los operadores son tokens de uno o dos caracteres reconocidos por el lexer. los operadores de dos
caracteres (``==``, ``!=``, ``<=``, ``>=``, ``->``, ``+=``, ``-=``, ``*=``, ``/=``, ``%=``, ``++``,
``--``) requieren mirar el siguiente code point antes de decidir el token, y se prueban **antes** que
los de uno, tal como se describe en la introducción de este capítulo.

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
    | :ref:`MODULO <modulo-def>`    | ``%``  | Resto de la división entera.   |
    +-------------------------------+--------+--------------------------------+
    | :ref:`compuestos <compuesto-def>` | ``+=`` | Azúcar de ``x = x op v``.  |
    |                               | ``-=`` |                                |
    |                               | ``*=`` |                                |
    |                               | ``/=`` |                                |
    |                               | ``%=`` |                                |
    +-------------------------------+--------+--------------------------------+
    | :ref:`INCREMENT <compuesto-def>` | ``++`` | Suma 1 (sentencia).         |
    |                               | ``--`` | Resta 1 (sentencia).           |
    +-------------------------------+--------+--------------------------------+

.. _assign-def:

ASSIGN (``=``)
^^^^^^^^^^^^^^^

asigna un valor a un binding. no debe confundirse con :ref:`EQUAL <equal-def>` (``==``).

.. code-block:: srcx
   :linenos:
   :emphasize-lines: 1

   int x = 0;
   x = 10;

.. _plus-def:

PLUS (``+``)
^^^^^^^^^^^^^

.. code-block:: srcx
   :linenos:

   int a = 1;
   int b = 2;
   int total = a + b;

.. _minus-def:

MINUS (``-``)
^^^^^^^^^^^^^^

.. note::
   el lexer debe distinguir ``-`` (``MINUS``) de la secuencia
   :ref:`ARROW <t-owner-def>` (``->``) y de los delimitadores de comentario
   multilínea (ver :ref:`comentarios <comentarios>`).

.. code-block:: srcx
   :linenos:

   int a = 3;
   int b = 1;
   int dif = a - b;

.. _multiply-def:

MULTIPLY (``*``)
^^^^^^^^^^^^^^^^^

.. code-block:: srcx
   :linenos:

   int base = 3;
   int altura = 4;
   int area = base * altura;

.. _divide-def:

DIVIDE (``/``)
^^^^^^^^^^^^^^^

.. note::
   ``/`` requiere mirar el siguiente code point para distinguir la división de los
   :ref:`comentarios <comentarios>` (``//`` y ``/-``).

.. code-block:: srcx
   :linenos:

   float a = 6.0;
   float b = 3.0;
   float r = a / b;

.. _modulo-def:

MODULO (``%``)
^^^^^^^^^^^^^^^

resto de la división entera.

.. code-block:: srcx
   :linenos:

   int total = 17;
   int cajas = total / 5;
   int sueltas = total % 5;

.. important::

   El resto lleva el signo del **dividendo**, como en C y no como en Python:
   ``-7 % 3`` es ``-1``, no ``2``. El backend nativo baja a la instrucción de
   resto del hardware, que hace exactamente eso; si el intérprete usara otra
   convención, el mismo programa daría números distintos según el target.

.. _compuesto-def:

asignación compuesta (``+=``) e incremento (``++``)
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

``x op= v`` es **azúcar** de ``x = x op v``, y ``x++`` de ``x = x + 1``. No hay
un nodo propio en el AST: el parser los expande, así que ni la Semántica, ni el
HIR, ni el intérprete saben que existen.

.. code-block:: srcx
   :linenos:

   int n = 10;
   n += 5;
   n %= 4;
   n++;

Dos consecuencias de que sean azúcar, y las dos son deliberadas:

**El incremento es una SENTENCIA, no una expresión.** ``n++`` termina en ``;``
y su valor se descarta. Como expresión habría que decidir si vale el valor
viejo o el nuevo —la distinción entre ``i++`` y ``++i``—, y esa distinción es
una fuente conocida de errores que no compra nada.

**El destino tiene que poder evaluarse dos veces.** La expansión lo nombra dos
veces, así que ``v[f()] += 1`` llamaría a ``f`` dos veces. Se rechaza con un
error que dice cómo escribirlo completo, en vez de hacerlo en silencio.

operadores de bits
~~~~~~~~~~~~~~~~~~~~~

Solo sobre ``int`` (64 bits con signo); sobre cualquier otro tipo son ``AST006``.
``&`` es el mismo token que la dirección (``ADDRESS``): en posición de prefijo
toma la dirección, entre dos operandos es el *y* de bits.

.. table:: Operadores de bits
    :width: 90%
    :widths: auto
    :align: center

    +---------------------+------------------+--------------------------------------------------+
    | Token               | Lexema           | Descripción                                      |
    +=====================+==================+==================================================+
    | ``ADDRESS`` (infijo)| ``&``            | *Y* de bits.                                     |
    +---------------------+------------------+--------------------------------------------------+
    | ``PIPE``            | ``|``            | *O* de bits.                                     |
    +---------------------+------------------+--------------------------------------------------+
    | ``CARET``           | ``^``            | *O exclusivo* de bits.                           |
    +---------------------+------------------+--------------------------------------------------+
    | ``TILDE``           | ``~``            | Complemento (prefijo): ``~x`` es ``-x - 1``.     |
    +---------------------+------------------+--------------------------------------------------+
    | ``SHIFT_LEFT``      | ``<<``           | Desplaza a la izquierda; envuelve a 64 bits.     |
    +---------------------+------------------+--------------------------------------------------+
    | ``SHIFT_RIGHT``     | ``>>``           | Desplaza a la derecha conservando el signo.      |
    +---------------------+------------------+--------------------------------------------------+
    | compuestos          | ``&=`` ``|=``    | Azúcar de ``x = x op v``.                        |
    |                     | ``^=`` ``<<=``   |                                                  |
    |                     | ``>>=``          |                                                  |
    +---------------------+------------------+--------------------------------------------------+

Tres decisiones:

- **La precedencia es la de Python y Rust, no la de C**: los de bits ligan más
  que las comparaciones, así que ``a & b == c`` es ``(a & b) == c``. De menor a
  mayor: ``|`` < ``^`` < ``&`` < ``<<``/``>>`` < ``+``/``-``.
- **El lexer no emite** ``>>``: son dos ``>``, y el parser los junta cuando van
  **pegados** y en posición de operador. Así ``Vector<Vector<int>>`` cierra dos
  genéricos sin partir ningún token (el problema que tuvo C++ hasta C++11), y
  ``a > > b`` no es un desplazamiento. ``SHIFT_RIGHT`` y ``SHIFT_RIGHT_ASSIGN``
  existen como tokens, pero solo los arma el parser. Lo mismo ``??``
  (``NULL_COALESCE``, desenvolver un ``T?``): dos ``?`` pegados en posición de
  operador, para que ``int??`` siga siendo un tipo.
- **Un desplazamiento fuera de** ``[0, 64)`` **es una excepción**
  (``excepciones.DesplazamientoInvalido``, ``EXC005``): en C es comportamiento
  indefinido y en Python da un entero de otro tamaño.

.. code-block:: srcx
   :class: fragmento
   :linenos:

   var int flags = 0;
   flags |= 1 << 3;              // enciende el bit 3
   var bool puesto = flags & (1 << 3) != 0;
   h = (h ^ c) * 1099511628211;     // un paso de FNV-1a


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

.. code-block:: srcx
   :linenos:

   int a = 1;
   int b = 2;
   if (a == b) { }

.. _not-equal-def:

NOT_EQUAL (``!=``)
^^^^^^^^^^^^^^^^^^^

.. code-block:: srcx
   :linenos:

   int a = 1;
   int b = 2;
   if (a != b) { }

.. _less-def:

LESS (``<``)
^^^^^^^^^^^^^

.. note::
   ``<`` debe distinguirse de :ref:`LESS_EQUAL <less-equal-def>` (``<=``).
   ``<-`` **no** es un token: sale como ``<`` seguido de ``-``.

.. code-block:: srcx
   :linenos:

   int a = 1;
   int b = 2;
   if (a < b) { }

.. _less-equal-def:

LESS_EQUAL (``<=``)
^^^^^^^^^^^^^^^^^^^^

.. code-block:: srcx
   :linenos:

   int a = 1;
   int b = 2;
   if (a <= b) { }

.. _greater-def:

GREATER (``>``)
^^^^^^^^^^^^^^^^

.. code-block:: srcx
   :linenos:

   int a = 1;
   int b = 2;
   if (a > b) { }

.. _greater-equal-def:

GREATER_EQUAL (``>=``)
^^^^^^^^^^^^^^^^^^^^^^^^

.. code-block:: srcx
   :linenos:

   int a = 1;
   int b = 2;
   if (a >= b) { }

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

.. code-block:: srcx
   :linenos:

   int a = 1;
   int b = 2;
   if (a > 0 and b > 0) { }

.. _or-def:

OR (``or``)
^^^^^^^^^^^^

.. code-block:: srcx
   :linenos:

   int a = 1;
   int b = 2;
   if (a > 0 or b > 0) { }

.. _not-def:

NOT (``not``)
^^^^^^^^^^^^^^

.. code-block:: srcx
   :linenos:

   bool activo = true;
   if (not activo) { }

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
    | :ref:`POINTER <pointer-def>`   | ``ptr``   | Tipo puntero, **postfijo** (``int ptr``).       |
    +--------------------------------+-----------+-------------------------------------------------+
    | :ref:`ADDRESS <address-def>`   | ``&``     | Operador de dirección.                          |
    +--------------------------------+-----------+-------------------------------------------------+
    | :ref:`NULLABLE <nullable-def>` | ``?``     | Marca un tipo como nulable (admite              |
    |                                |           | :ref:`null <null-def>`).                        |
    +--------------------------------+-----------+-------------------------------------------------+
    | :ref:`ARROW <t-owner-def>`     | ``->``    | Tipo de retorno de una función.                 |
    +--------------------------------+-----------+-------------------------------------------------+

.. note::
   La propiedad **no** se escribe con anotaciones: ``@owner`` no existe como
   token (un ``@nombre`` cualquiera lo lexa :ref:`DECORATOR <decorator-def>`,
   y el parser solo interpreta los decoradores que conoce), y ``<-`` tampoco
   —se lexa como :ref:`LESS <less-def>` seguido de :ref:`MINUS <minus-def>`.
   La transferencia se escribe con ``move`` y la destrucción anticipada con
   ``free`` (ver :doc:`memory_model`).

.. _pointer-def:

POINTER (``ptr``)
~~~~~~~~~~~~~~~~~~

declara un tipo puntero.

.. code-block:: srcx
   :linenos:
   :emphasize-lines: 1

   int valor = 42;
   int ptr mutable p = &valor;

.. _address-def:

ADDRESS (``&``)
~~~~~~~~~~~~~~~~

obtiene la dirección de un valor.

.. code-block:: srcx
   :linenos:
   :emphasize-lines: 1

   int valor = 42;
   int ptr mutable p = &valor;

.. _nullable-def:

NULLABLE (``?``)
~~~~~~~~~~~~~~~~~

marca un tipo como nulable, permitiendo el valor :ref:`null <null-def>`.

.. code-block:: srcx
   :linenos:
   :emphasize-lines: 1

   int? opcional = null;

.. _t-owner-def:

ARROW (``->``)
~~~~~~~~~~~~~~~

marca el tipo de retorno de una :ref:`función <function-def>`. el lexer debe
distinguir ``->`` de :ref:`MINUS <minus-def>` (``-``): decide mirando el
siguiente code point, como con ``==`` o ``<=``.

.. code-block:: srcx
   :linenos:
   :emphasize-lines: 1

   fn direccion_de(int ptr mutable p) -> int ptr mutable { return p; }

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

.. code-block:: srcx
   :linenos:

   #from io #import stdp

   stdp.println("hola");

.. _l-brace-def:

L_BRACE (``{``) y R_BRACE (``}``)
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. _r-brace-def:

delimitan bloques de código y cuerpos de :ref:`struct <struct-def>`.

.. code-block:: srcx
   :linenos:

   fn f(int x) -> int {
       if (x > 0) { return x; }
       return 0;
   }

.. _l-bracket-def:

L_BRACKET (``[``) y R_BRACKET (``]``)
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. _r-bracket-def:

indexación y literales de colección.

.. code-block:: srcx
   :linenos:

   int x = 0;

.. _dot-def:

DOT (``.``)
~~~~~~~~~~~~

acceso a miembro o método. el lexer lo distingue del punto decimal de un :ref:`FLOAT <float-def>`.

.. code-block:: srcx
   :linenos:

   #from io #import stdp

   stdp.println("hola");

.. _comma-def:

COMMA (``,``)
~~~~~~~~~~~~~~

separa elementos en listas, argumentos o campos.

.. code-block:: srcx
   :linenos:

   fn suma(int a, int b) -> int { return a + b; }

.. _semicolon-def:

SEMICOLON (``;``)
~~~~~~~~~~~~~~~~~~

terminador / separador de sentencia (p. ej. tras la definición de un :ref:`struct <struct-def>` con nombre).

.. code-block:: srcx
   :linenos:

   struct { int x; } Punto;

.. _colon-def:

COLON (``:``)
~~~~~~~~~~~~~~

separa el campo de su valor en un literal de struct, y la etiqueta del cuerpo
en una rama de :ref:`case <case-def>` cuando ese cuerpo no es un bloque.
Delante de un bloque **sobra**, pero escribirlo se acepta: ``case 1: { ... }``
es la costumbre de C y rechazarlo solo producía un error que ni siquiera
mencionaba el ``case``.

.. code-block:: srcx
   :linenos:

   struct { int x; int y; } Punto;

   var Punto p = Punto{ x: 1, y: 2 };

   match (p.x) {
       case 1: return;
   }

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

.. code-block:: srcx
   :linenos:

   int contador = 0;

.. _decorator-def:

DECORATOR (``@``)
~~~~~~~~~~~~~~~~~~

decorador escrito con ``@`` y colocado encima de la declaración, de forma
análoga a Python. El lexer produce un ``DECORATOR`` para cualquier ``@nombre``;
qué decoradores tienen significado (``@trait``, ``@impl``, ``@test``) lo decide
el :doc:`parser <sintactic_analysis>`. una sintaxis inválida produce
:ref:`LEX012 <LEX012-def>`.

.. code-block:: srcx
   :linenos:
   :emphasize-lines: 1

   @test
   fn caso() -> void { }

.. _dunder-def:

DUNDER (``__foo__``)
~~~~~~~~~~~~~~~~~~~~~~

identificador rodeado por dobles guiones bajos. El lexer solo lo clasifica;
quien le da significado es el parser, y hacen falta dos declaraciones
distintas: ``hook fn`` para el conjunto fijo del lenguaje y ``dunder fn``
para un método especial libre, despachado por ``(tipo, nombre)``.

.. code-block:: srcx
   :linenos:

   struct { int cur; int max; } Contador;

   dunder fn __siguiente__(Contador ptr c) -> int { return c.cur; }

Lo que se invoca **sin** escribir el nombre del hook son los del conjunto
fijo: ``print(x)`` dispara ``__print__`` y ``len(x)`` dispara ``__len__``
(ver :doc:`repo/hooks`). Un ``dunder`` se llama por su nombre:
``c.__siguiente__()``.

.. _directive-def:

DIRECTIVE (``#``)
~~~~~~~~~~~~~~~~~~

inicia una directiva. el lexer emite el token ``DIRECTIVE`` al encontrar ``#``; la directiva concreta se
identifica en el parser (ver :ref:`directivas <directivas>`). una directiva no reconocida produce
:ref:`LEX009 <LEX009-def>`.

.. code-block:: srcx
   :linenos:

   #import io as entrada_salida;

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

FREE (``free``)
~~~~~~~~~~~~~~~~

``free`` destruye un valor a través de su puntero antes de que el ámbito lo
haga, y dispara el hook ``__free__`` del tipo apuntado si existe (ver
:doc:`memory_model`).

``delete``, ``make``, ``copy`` y ``alloc`` **no** existen: ``delete`` y
``make`` pertenecían al modelo por regiones y se retiraron con él, ``alloc``
dejó de ser parte del lenguaje —la reserva la aporta una librería— y ``copy``
nunca llegó a definirse.

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

.. code-block:: srcx
   :linenos:
   :emphasize-lines: 1

   // un miembro concreto del paquete
   #from io #import stdp

   fn main() -> int {
       stdp.println("hola");
       return 0;
   }

Las otras formas de traer el mismo módulo (son **alternativas**: importarlo
dos veces en el mismo archivo es ``SEM002``):

.. code-block:: srcx
   :class: fragmento

   #import io                  // el modulo entero, bajo su alias
   #import io as entrada_salida // con otro nombre local
   const es = #import io;      // ligado a un nombre con 'const'

* :ref:`export <export-def>`: permite que una libreria o modulo sea exportado y usando globalmente en otros archivos

*export siempre debe tener un alias y esta directiva es obligatoria en archivos:* :ref:`.libsrx <libsrx>`.

.. code-block:: srcx
   :linenos:
   :emphasize-lines: 12

   // cadena.libsrx
   #from io #import stdp

   public struct {
       str text;
       int len;
   } Cadena;

   public hook fn __print__(Cadena ptr c) -> void { stdp.print(c.text); }
   public hook fn __len__(Cadena ptr c) -> int { return c.len; }

   #export as cadena

si no existe la libreria se arroja un :ref:`SEM009<SEM009-def>`, que dice en qué rutas se buscó

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


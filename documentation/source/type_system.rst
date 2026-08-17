4. Sistema de tipos
====================

El sistema de tipos de suriaX es **estático**, **fuerte** y **nominal**, y no
es una fase del pipeline: es transversal. Anota el AST, participa en la
semántica y viaja serializado dentro del HIR, de modo que todos los backends
ven exactamente los mismos tipos.

Estático
   Los tipos se resuelven al compilar. Cada expresión queda anotada con su
   tipo (``restype``) antes de que la semántica empiece a trabajar.

Fuerte
   No hay conversiones implícitas. Un ``int`` no se vuelve ``float`` porque el
   contexto lo pida; hay que escribir la conversión.

Nominal
   Dos tipos con la misma forma son tipos distintos si tienen nombres
   distintos. Un ``struct { int x; int y; } Punto;`` y un
   ``struct { int x; int y; } Vector;`` no son intercambiables.

.. _tipos-primitivos:

Tipos primitivos
-----------------

.. table::
   :widths: auto

   =========  ==========================================================
   Tipo       Descripción
   =========  ==========================================================
   ``int``    Entero con signo de 64 bits.
   ``float``  Punto flotante de 64 bits (IEEE-754).
   ``bool``   ``true`` o ``false``.
   ``char``   Un único *code point* Unicode.
   ``str``    Cadena de texto Unicode.
   ``void``   Ausencia de valor; solo como tipo de retorno.
   =========  ==========================================================

.. code-block:: srcx

   int edad = 30;
   float altura = 1.75;
   bool activo = true;
   char inicial = 'S';
   str nombre = "suriaX";

.. _tipos-compuestos:

Tipos compuestos
-----------------

Struct
~~~~~~~

El nombre va **al final**, al estilo del ``typedef`` de C:

.. code-block:: srcx

   struct {
       int x;
       int y;
   } Punto;

Se instancia con un **literal de struct**, que es la vía nativa de construir
un valor:

.. code-block:: srcx

   var Punto p = Punto{ x: 10, y: 20 };
   var int suma = p.x + p.y;

Si el struct lo publica una librería, el literal se escribe cualificado
(``geom.Punto{ x: 1, y: 2 }``) igual que la anotación de tipo.

Enum
~~~~~

.. code-block:: srcx

   enum Color {
       ROJO,
       VERDE = 5,
       AZUL,
   };

Los valores se numeran solos desde cero, y un literal explícito reancla la
cuenta: aquí ``ROJO`` vale 0, ``VERDE`` 5 y ``AZUL`` 6. Los items se leen
cualificados: ``Color.VERDE``.

Tipo nominal opaco
~~~~~~~~~~~~~~~~~~~

Declara un tipo **con nombre y sin representación escrita en suriaX**: su
layout lo aportan sus hooks o el backend. Es la forma en que una librería
publica tipos que el lenguaje no trae de fábrica.

.. code-block:: srcx

   const type int8;
   const type float16;

``const`` liga el nombre a ese tipo para siempre; sin cualificador es
redefinible. El inicializador opcional es una expresión que **produzca** un
tipo, porque ``type`` es un tipo de primera clase:

.. code-block:: srcx

   const type Bloque = _definir_bloque(4);

.. _modificadores-de-tipo:

Modificadores de tipo
----------------------

Los sufijos se aplican de izquierda a derecha, así que el orden desambigua.

Punteros
~~~~~~~~~

El puntero es **postfijo**: ``char ptr`` es el ``char *`` de C.

.. code-block:: srcx

   var int valor = 42;
   int ptr mutable p = &valor;      // se puede escribir a través de p
   int ptr solo_lectura = &valor;   // no se puede

La mutabilidad **forma parte del tipo**: ``int ptr`` e ``int ptr mutable`` son
tipos distintos. La única conversión segura es **soltar** mutabilidad
(``ptr mutable T`` → ``ptr T``), nunca ganarla. Escribir a través de un
puntero de solo lectura es un error de semántica (``SEM015``).

El operador ``&`` exige un *lvalue* y hereda la mutabilidad del binding: sobre
una variable ``var`` produce ``ptr mutable``, sobre una ``const`` produce
``ptr``.

Nullable
~~~~~~~~~

``T?`` es "un ``T``, o ``null``":

.. code-block:: srcx

   int? cantidad = null;

El orden de los sufijos importa: ``char ptr?`` es un puntero que puede ser
nulo, y ``char? ptr`` es un puntero a un ``char`` que puede serlo.

Tipo error
~~~~~~~~~~~

``error T`` es "un ``T``, o un error"; ``error`` a secas es solo el error. En
la ruta de éxito el tipo es **transparente**: un ``error int`` se usa como un
``int``, porque el fallo no viaja en el valor sino por ``throw``/``catch``.

.. code-block:: srcx

   fn dividir(int a, int b) -> error int {
       if (b == 0) {
           throw "division por cero";
       }
       return a / b;
   }

.. _conversiones:

Conversiones
-------------

La **única** vía de conversión es ``cast<T>(x)``. No hay coerciones
implícitas en ninguna dirección.

.. code-block:: srcx

   var int n = 7;
   var float f = cast<float>(n);

Entre primitivos la conversión la ejecuta el backend. Cuando hay un tipo
nominal de por medio, la aporta el hook ``__cast__`` del tipo:

.. code-block:: srcx

   hook fn __cast__(int n) -> Celsius {
       return Celsius{ grados: n };
   }

Un tipo puede declarar **varias** conversiones (``int`` → ``int8``, ``str`` →
``Estado``...). El par origen-destino se deriva de la firma —origen es el
primer parámetro, destino el retorno— así que no hace falta declararlo dos
veces. Todas viajan en la tabla de conversiones del HIR.

La sintaxis ``<...>`` es la posición compartida de **argumentos de tipo**: hoy
la usa ``cast``, y los genéricos de librería (``vec<int>``) la reutilizarán.

.. _metatipo:

``type`` como valor
--------------------

``type`` es el tipo de un tipo. Una función puede devolver un tipo, y el
resultado se liga con ``type_decl``:

.. code-block:: srcx

   fn entero_de(int bits) -> type;

   const type int8 = entero_de(8);
   const int8 pequeno = 100;

Es lo que permite que una librería construya tipos en vez de enumerarlos.

.. _inferencia:

Alcance de la inferencia
-------------------------

La anotación de tipos es explícita en declaraciones, parámetros y retornos.
La inferencia opera sobre literales y sobre la composición de expresiones: de
``a + b`` sale el tipo de sus operandos, de una llamada sale el retorno
declarado, y de un literal su tipo natural.

El algoritmo general de inferencia todavía se está definiendo. Hindley-Milner
quedó descartado por su complejidad, por su fricción con el modelo de memoria
y por la distancia entre su maquinaria y el objetivo de que cada fase sea
legible.

Cuando el tipo de una expresión no se puede determinar, el compilador lo dice
con ``AST007`` en vez de suponer.

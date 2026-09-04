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

   El nombre incluye **de qué unidad viene**: un tipo declarado en una
   librería se identifica como ``<alias>.<Nombre>``. Dos librerías que
   declaren cada una un ``Node`` declaran dos tipos distintos, aunque dentro
   de cada una se siga escribiendo ``Node`` a secas::

      #import a
      #import b
      var a.Node n = b.haz();   // error: 'a.Node' no admite un 'b.Node'

   Esto vale también para lo que se indexa POR tipo —hooks, conversiones
   (``__cast__``), dunders y el filtro de ``catch``—, así que el ``__free__``
   que corre sobre un valor es siempre el de su librería. Los mensajes de
   error, en cambio, nombran el tipo como se puede escribir desde donde está
   el error (``dt.float32``, no el canónico), porque una sugerencia que no se
   puede teclear no ayuda.

.. _tipos-primitivos:

Tipos primitivos
-----------------

.. table::
   :widths: auto

   =========  ==========================================================
   Tipo       Descripción
   =========  ==========================================================
   ``int``    Entero con signo de 64 bits (envuelve al desbordar).
   ``float``  Punto flotante de 64 bits (IEEE-754).
   ``bool``   ``true`` o ``false``.
   ``char``   Un único *code point* Unicode.
   ``str``    Cadena de texto Unicode.
   ``void``   Ausencia de valor; solo como tipo de retorno.
   =========  ==========================================================

No hay veracidad
~~~~~~~~~~~~~~~~

La condición de un ``if`` o un ``while`` es de tipo ``bool``, y solo ``bool``.
Un ``int`` no es "verdadero por no ser cero" ni una cadena "verdadera por no
estar vacía": aceptar ``if (1)`` sería una conversión implícita, y la única
vía de conversión del lenguaje es ``cast<T>(x)``.

.. code-block:: srcx

   if (n != 0) { ... }      // así
   if (n) { ... }           // error: la condición es 'int'

Aritmética entera
~~~~~~~~~~~~~~~~~

La división y el resto **truncan hacia cero**, como en C y como la
instrucción ``i64.div_s`` de WebAssembly: ``-7 / 2`` es ``-3`` (no ``-4``) y
``-7 % 2`` es ``-1`` (no ``1``). Las dos convenciones van juntas a propósito,
porque se sostienen mutuamente: con ellas se cumple la identidad

.. code-block:: text

   (a / b) * b + a % b == a

Mezclarlas —cociente hacia abajo y resto con el signo del dividendo— la rompe.
La regla vale para **todos los ejecutores**: intérprete, target web y backend
nativo dan el mismo número para el mismo programa.

Dividir por cero **entre enteros** no tiene respuesta: es un error de
ejecución (``RT016``). Entre ``float`` sí la tiene y es la de IEEE-754
(``1.0 / 0.0`` es ``+inf``, ``0.0 / 0.0`` es ``NaN``), así que ahí no hay
error que reportar.

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
   :class: fragmento

   var Punto p = Punto{ x: 10, y: 20 };
   var int suma = p.x + p.y;

Un ``struct`` tiene que tener **tamaño finito**, así que no puede contenerse a
sí mismo por valor —ni directamente ni a través de otros—: cada instancia
contendría otra, sin fondo. La recursión legítima se escribe con un puntero,
que se *refiere* en vez de contener:

.. code-block:: srcx
   :class: fragmento

   struct { Nodo ptr sig; int v; } Nodo;    // lista enlazada: correcto
   struct { Nodo sig;     int v; } Nodo;    // SEM026: tamaño infinito

Es la misma distinción que decide la propiedad (:ref:`tipos-con-dueno`): un
puntero no contiene, apunta.

.. _genericos:

Tipos genéricos
~~~~~~~~~~~~~~~~

Un tipo puede tener **parámetros de tipo**. Van con el nombre, al final, que
es donde suriaX pone siempre lo que identifica una declaración:

.. code-block:: srcx
   :class: fragmento

   struct {
       T ptr mutable datos;
       int len;
   } Vector<T>;

   const type Caja<T>;          // también un tipo opaco puede serlo

Y se usan escribiendo los argumentos entre ángulos — la misma posición que
estrenó ``cast<T>(x)``:

.. code-block:: srcx
   :class: fragmento

   fn suma(Vector<int> v) -> int { return v[0] + v[1]; }

**Dos instancias distintas son tipos distintos.** ``Vector<int>`` y
``Vector<str>`` no unifican, ni entre sí ni con ``Vector`` a secas; ahí está
toda la garantía. Y porque los parámetros se escriben, la **aridad** es
comprobable: usar un genérico con un número de argumentos que no es el suyo
—o pasarle argumentos a un tipo corriente— es ``SEM027``.

Dentro del genérico todo se declara hablando del parámetro; visto desde una
instancia concreta, vale su **sustitución**:

.. table::
   :widths: auto

   ==========================  ==========================  ====================
   Declarado en ``Vector<T>``  Visto en ``Vector<int>``    Visto en ``Vector<str>``
   ==========================  ==========================  ====================
   campo ``T ptr mutable``     ``int ptr mutable``         ``str ptr mutable``
   ``__index__`` -> ``T``      ``v[0]`` es ``int``         ``v[0]`` es ``str``
   método ``get`` -> ``T``     ``v.get(0)`` es ``int``     ``v.get(0)`` es ``str``
   ==========================  ==========================  ====================

Los genéricos anidan (``Vector<Vector<int>>``) y sus argumentos viajan en el
HIR, así que el intérprete y el backend nativo ven exactamente los mismos
tipos.

Para **construir** uno, el literal lleva sus argumentos:

.. code-block:: srcx
   :class: fragmento

   struct { T valor; int n; } Caja<T>;

   var Caja<int> a = Caja<int>{ valor: 7, n: 1 };
   var Caja<str> b = Caja<str>{ valor: "hola", n: 2 };

Escribir ``Caja{ ... }`` sobre un genérico es ``SEM027``, la misma regla de
aridad que en una anotación: sin argumentos el tipo del literal no diría de
qué ``Caja`` se trata.

.. note::

   El literal de un genérico es la **única** posición del lenguaje donde
   ``<`` es ambiguo: ``a < b`` es una comparación y ``Caja<int>{...}`` no. Se
   resuelve mirando — solo son argumentos de tipo si tras el ``>`` viene un
   ``{``. En cualquier otro caso el parser retrocede y el ``<`` sigue siendo
   el operador de siempre.

Y ningún campo puede ser ``void``, porque ``void`` significa *no hay valor*:
solo es válido como tipo de retorno (``SEM025``). Lo mismo vale para
variables y parámetros — se comprueba en un único punto, así que ninguna de
las tres posiciones se queda sin cubrir. Un ``void ptr`` sí es legítimo: es
una dirección sin tipo, no un valor de tipo ``void``.

Si el struct lo publica una librería, el literal se escribe cualificado
(``geom.Punto{ x: 1, y: 2 }``) igual que la anotación de tipo.

Un literal nombra **todos** los campos. No hay valores por defecto: un campo
que el literal no escribe no existe en el valor construido, así que omitirlo
es ``SEM028`` — antes compilaba y reventaba al leer el campo, en ejecución y
lejos de la causa. Y el valor de cada campo tiene que ser de su tipo, ya
sustituido si el struct es genérico.

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
cualificados (``Color.VERDE``) y también pelados (``VERDE``).

.. _enum-suma:

Variantes con datos: el enum como tipo suma
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

Una variante puede llevar **valores propios**. Entonces el enum deja de ser un
conjunto de enteros con nombre y pasa a describir *una de estas formas, y cada
una lleva lo suyo*:

.. code-block:: srcx
   :class: fragmento

   enum Movimiento {
       Entrada(int),
       Salida(int),
       Ajuste(int, str),
       Recuento,
   };

Se construye **invocando** la variante, y se abre **desestructurando** en un
``case``:

.. code-block:: srcx
   :class: fragmento

   var Movimiento m = Movimiento.Ajuste(-2, "rotura");

   match (m) {
       case Movimiento.Entrada(n)     { return n; }
       case Movimiento.Salida(n)      { return 0 - n; }
       case Movimiento.Ajuste(d, por) { return d; }
       case Movimiento.Recuento       { return 0; }
   };

El patrón tiene **la misma forma** que la construcción, así que no hizo falta
inventar una sintaxis de patrones aparte. Lo que cambia es quién liga: al
construir, ``d`` es un valor que se lee; en el ``case``, un nombre que se
declara — y vive solo en el cuerpo de esa rama.

El sujeto del ``match`` se **desreferencia solo**, igual que ``.campo``. Es lo
que hace escribible el caso que motiva todo esto, un árbol:

.. code-block:: srcx
   :class: fragmento

   enum Expr {
       Num(int),
       Suma(Expr ptr, Expr ptr),
   };

   fn evaluar(Expr ptr e) -> int {
       match (e) {
           case Expr.Num(n)     { return n; }
           case Expr.Suma(a, b) { return evaluar(a) + evaluar(b); }
       };
       return 0;
   }

Reglas, y cada una tiene su diagnóstico:

* la aridad y los tipos del constructor se verifican como los de cualquier
  función (``SEM008`` / ``AST006``), y los del patrón también;
* un patrón liga **nombres**, no expresiones;
* una variante no puede contenerse a sí misma por valor (``SEM026``): la
  recursión va por puntero, que se refiere en vez de contener;
* ``void`` no puede ser un payload (``SEM025``);
* un payload **no puede poseer recursos** todavía (``SEM029``) — destruirlo
  exigiría decidir en ejecución qué variante se está destruyendo, y eso no
  existe. Un puntero sí vale: no posee.

En cuanto **una** variante lleva payload, el enum entero es un tipo suma. Un
enum de solo variantes unidad sigue siendo exactamente lo de antes: enteros
con nombre, asignables a ``int``.

Tipo nominal opaco
~~~~~~~~~~~~~~~~~~~

Declara un tipo **con nombre y sin representación escrita en suriaX**: su
layout lo aportan sus hooks o el backend. Es la forma en que una librería
publica tipos que el lenguaje no trae de fábrica.

.. code-block:: srcx

   const type int8;
   const type float16;

``const`` liga el nombre a ese tipo para siempre; sin cualificador es
redefinible. Se puede declarar en el nivel superior o **dentro de una
función**, donde vive solo en su ámbito (ver
:ref:`ámbitos <scopes>`). El inicializador opcional es una expresión que
**produzca** un tipo, porque ``type`` es un tipo de primera clase:

.. code-block:: srcx
   :class: solo-compila

   fn definir_bloque(int bits) -> type;

   const type Bloque = definir_bloque(4);

El inicializador pasa por la semántica como cualquier otra expresión: un
nombre que no existe es ``SEM001``, y uno que no produce un ``type`` es
``AST006``.

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

El valor que liga un ``catch (e)`` tiene tipo ``error`` a secas, y eso
significa **desconocido**, no "un tipo con el que no se puede hacer nada":
``throw`` acepta cualquier valor, así que lo único que se sabe de ``e`` es
por dónde llegó. Se puede ligar, pasar, operar y convertir como cualquier
valor cuyo tipo esta fase todavía no conoce:

.. code-block:: srcx
   :class: fragmento

   try {
       var int r = dividir(1, 0);
   } catch (e) {
       var int codigo = e;          // se liga
       var int doble  = codigo * 2; // se opera
       registrar(e);                // se pasa
   }

.. _catch-tipado:

Ramas ``catch`` filtradas por tipo
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Una rama puede declarar **qué** atrapa. Entonces liga la variable ya tipada, y
lo que no encaja no se lo queda:

.. code-block:: srcx
   :class: fragmento

   try {
       aplicar(&articulo, movimiento);
   } catch (SinStock s) {
       stdpf.printf(f"faltan {s.piden - s.hay} de {s.articulo}\n");
   } catch (DatoInvalido d) {
       stdpf.printf(f"campo invalido: {d.campo}\n");
   } catch (e) {
       stdpf.printf(f"fallo inesperado: {e}\n");
   };

Las ramas se prueban **en orden** y gana la primera cuyo tipo encaje. Una rama
sin tipo atrapa cualquier cosa, así que suele ir al final.

Lo importante es qué pasa cuando **ninguna** encaja: el valor **sigue
propagándose** hacia el ``try`` de más afuera. Eso es lo que hace útil filtrar
—un ``catch`` que no sabe manejar un fallo no se lo queda— y es la diferencia
con capturar todo y volver a lanzar a mano.

El filtro es una pregunta que se resuelve en **ejecución**: ``throw`` acepta
cualquier valor, así que el tipo dinámico de lo lanzado es lo único que hay
para decidir. Funciona con structs, con enums y con primitivos.

.. _conversiones:

Conversiones
-------------

La vía general de conversión es ``cast<T>(x)``. No hay coerciones implícitas
salvo la de un **literal** con rango comprobado, que tiene su propia sección
más abajo.

.. code-block:: srcx

   var int n = 7;
   var float f = cast<float>(n);
   var str  s = cast<str>(n);      // todo primitivo tiene forma de texto

Entre primitivos la conversión la ejecuta el backend. Convertir a ``str`` es
el único par que **no puede fallar** —es la misma representación que
interpola un f-string— así que es nativo para ``int``, ``float``, ``bool`` y
``char``. La vuelta no lo es: ``str`` → ``int`` puede fallar, y una
conversión que falla necesita decir cómo.

Cuando hay un tipo nominal de por medio, la conversión la aporta el hook
``__cast__`` del tipo:

.. code-block:: srcx
   :class: fragmento

   hook fn __cast__(int n) -> Celsius {
       return Celsius{ grados: n };
   }

Un tipo puede declarar **varias** conversiones (``int`` → ``int8``, ``str`` →
``Estado``...). El par origen-destino se deriva de la firma —origen es el
primer parámetro, destino el retorno— así que no hace falta declararlo dos
veces. Todas viajan en la tabla de conversiones del HIR.

Un ``__cast__`` puede ser un :ref:`prototipo <prototipos>`, y entonces la
conversión la ejecuta el host. Es lo que da ancho REAL a los tipos de
``d_types`` —``cast<dt.int8>(300)`` es ``44``, no ``300``— sin cablear
ningún tipo de librería en el compilador (ver :ref:`ancho fijo <ancho-fijo>`).

La sintaxis ``<...>`` es la posición compartida de **argumentos de tipo**: la
usan ``cast``, las anotaciones de un :ref:`genérico <genericos>` y su literal.

.. _rango-literal:

Literales y tipos numéricos de librería
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

``const dt.int8 a = 10;`` funciona, y no es una excepción a la regla: es la
única coerción implícita del lenguaje, y solo existe porque se puede
**comprobar**.

Un tipo de ancho fijo es un nominal opaco. El compilador sabe por
``__sizeof__`` que ``int8`` mide un byte, pero un byte va de −128 a 127 o de
0 a 255 y la firma no dice cuál — así que no puede decidir si el ``10`` cabe.
Con :ref:`__min__/__max__ <hooks-semantica>` el tipo publica su rango, el compilador
lee esos dos literales en compilación (no ejecuta nada) y entonces la
pregunta tiene respuesta exacta:

.. code-block:: srcx
   :class: fragmento

   const dt.int8 a = 10;      // cabe: se inserta la conversión declarada
   const dt.int8 b = 300;     // AST006: no cabe en 'int8' (rango [-128, 127])

Vale en las cuatro posiciones de escritura —inicialización, asignación, campo
de un literal de struct y argumento— porque son la misma pregunta.

.. important::

   La asimetría con ``cast<T>(x)`` es deliberada: el literal **implícito**
   tiene que caber, el ``cast`` **explícito** trunca. ``cast<dt.int8>(300)``
   sigue valiendo ``44``. Son dos operaciones distintas, no una laxa y una
   estricta.

Un tipo que no publica su rango no admite literales sin convertir. El
diagnóstico entonces nombra la salida: si hay una conversión declarada, dice
cuál y cómo escribirla.

.. _metatipo:

``type`` como valor
--------------------

``type`` es el tipo de un tipo. Una función puede devolver un tipo, y el
resultado se liga con ``type_decl``:

.. code-block:: srcx
   :class: solo-compila

   fn entero_de(int bits) -> type;

   const type int8 = entero_de(8);
   const int8 pequeno;

Es lo que permite que una librería construya tipos en vez de enumerarlos.

Un tipo nominal opaco no tiene literales propios: ``const int8 x = 100;`` es
``AST006``, porque ``100`` es un ``int`` y no hay coerciones implícitas. El
valor lo aporta un ``__cast__`` del tipo (:ref:`conversiones <conversiones>`).

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

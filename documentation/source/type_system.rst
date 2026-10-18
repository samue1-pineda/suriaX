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
   :class: fragmento

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

Dividir por cero **entre enteros** no tiene respuesta. Si el cero está
escrito (``x / 0``), el programa no compila (``SEM035``); si el divisor vale
cero al ejecutar, es una excepción que se puede atrapar
(``excepciones.DivisionPorCero``, ``EXC001``). Entre ``float`` sí hay
respuesta y es la de IEEE-754 (``1.0 / 0.0`` es ``+inf``, ``0.0 / 0.0`` es
``NaN``), así que ahí no hay error que reportar.

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

**El cuerpo de un genérico no le pide nada a su** ``T`` **por su nombre.**
Se comprueba una sola vez, sin saber con qué se instanciará, y un ``T`` sin
cota no promete ningún método, ningún campo ni ningún ``__index__``. Por eso
``x.aplica(1)``, ``x.campo`` o ``x[i]`` con ``x: T`` (o ``T ptr``) son
``SEM043``. Antes se aceptaban y cada instancia fallaba a su manera: ``RT011``
al ejecutar con un tipo que no lo tenía, o —peor— el tipo equivocado pasaba
en silencio. Lo que el **lenguaje** hace por su cuenta con un ``T`` sigue
valiendo, porque cada instancia lo comprueba con su tipo concreto: ``==``,
``<`` (``SEM039``), ``hash``, copiarlo (``SEM038``), destruirlo y escribirlo
en un f-string. Indexar un **bloque** (``T ptr``) también: es memoria, no un
método de ``T``. Para pedirle más a ``T`` está la :ref:`cota <cotas>`
(``<T: Contrato>``), que dice qué tiene y se comprueba en la definición; o
se le pasa el comportamiento como una :ref:`función <funciones-como-valores>`.

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

En un f-string un enum se escribe por el **nombre** de su variante:
``f"{c}"`` con ``c = Color.VERDE`` da ``VERDE``, no ``5``, y una variante con
payload da ``Circulo(2.5)``. En ejecución un enum sin payload es un entero, así
que el nombre sale del tipo que el compilador ya conoce; un entero que no es
ninguna variante (el de un ``cast``) se escribe como número.

El formato de una interpolación es el de Python: ``{x!r}`` pide la
**representación** —una cadena con sus comillas y escapes (``"hola
"``), un
``char`` entre apóstrofes, un enum con su tipo (``Color.VERDE``,
``Figura.Circulo(2.5)``)— y ``{x:espec}`` un especificador
``[0][ancho][.precisión][tipo]``: ``d x X b o`` para un ``int`` o un ``byte``
(``{n:08b}``, ``{n:x}``), ``f`` con su precisión para un ``float``
(``{x:.2f}``), y el ancho para cualquier valor (un número se alinea a la
derecha, lo demás a la izquierda). Un formato que no corresponde al tipo es un
error de compilación. Un struct se escribe con sus campos,
``Punto{x: 1, y: 2}``; si lleva un puntero, su representación podría no
terminar y se rechaza.

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
que hace escribible el caso que motiva todo esto, un árbol cuyos nodos se
reservan con ``mem``:

.. code-block:: srcx

   #from io #import stdp
   #import mem

   enum Expr {
       Num(int),
       Suma(Expr ptr, Expr ptr),
       Por(Expr ptr, Expr ptr),
   };

   fn nodo(Expr e) -> Expr ptr mutable {
       var Expr ptr mutable b = mem.reserve<Expr>(1);
       b[0] = e;
       return b;
   }

   fn evaluar(Expr ptr e) -> int {
       match (e) {
           case Expr.Num(n)     { return n; }
           case Expr.Suma(a, b) { return evaluar(a) + evaluar(b); }
           case Expr.Por(a, b)  { return evaluar(a) * evaluar(b); }
       };
       return 0;
   }

   fn main() -> int {
       // (2 + 3) * 4
       var Expr ptr mutable dos = nodo(Expr.Num(2));
       var Expr ptr mutable tres = nodo(Expr.Num(3));
       var Expr ptr mutable cuatro = nodo(Expr.Num(4));
       var Expr ptr mutable suma = nodo(Expr.Suma(dos, tres));
       var Expr raiz = Expr.Por(suma, cuatro);
       stdp.println(f"valor = {evaluar(&raiz)}");   // valor = 20
       mem.release<Expr>(suma);
       mem.release<Expr>(cuatro);
       mem.release<Expr>(tres);
       mem.release<Expr>(dos);
       return 0;
   }

Un ``Expr ptr`` llega de dos formas y las dos valen lo mismo: el préstamo de
una celda (``&raiz``, ``&b[0]``) y el **bloque** que entrega ``mem.reserve``,
que es su elemento 0. Hasta la 0.3.x el ``match`` solo seguía el préstamo: con
un bloque no entraba en ninguna rama, no decía nada y este árbol calculaba
``0``. Leer un campo a través del bloque (``b.x``) también es leer el del
elemento 0.

Reglas, y cada una tiene su diagnóstico:

* la aridad y los tipos del constructor se verifican como los de cualquier
  función (``SEM008`` / ``AST006``), y los del patrón también;
* un patrón liga **nombres**, no expresiones;
* una variante no puede contenerse a sí misma por valor (``SEM026``): la
  recursión va por puntero, que se refiere en vez de contener;
* ``void`` no puede ser un payload (``SEM025``);
* un payload **puede poseer recursos**: el valor se destruye con él, por la
  variante que tenga al morir (destruir por tipo; hasta la 0.4.1 era
  ``SEM029``). Lo que liga ``case Nodo.A(x)`` es el payload **prestado**:
  sigue siendo del enum, así que cederlo (``move x``, ``return x``) es
  ``SEM036``. Un payload puntero no posee.

En cuanto **una** variante lleva payload, el enum entero es un tipo suma. Un
enum de solo variantes unidad sigue siendo exactamente lo de antes: enteros
con nombre, asignables a ``int``.

.. _enum-generico:

Enums genéricos
^^^^^^^^^^^^^^^^

Un enum también puede tener :ref:`parámetros de tipo <genericos>`. Como su
nombre va delante de las llaves, los parámetros van pegados a él (igual que en
``fn f<T>``), y una variante se escribe **siempre con los argumentos** de su
enum, al construirla y en un ``case``:

.. code-block:: srcx

   #from io #import stdp

   enum Res<T, E> {
       Ok(T),
       Err(E),
       Vacio,
   };

   fn divide(int a, int b) -> Res<int, str> {
       if (b == 0) { return Res<int, str>.Err("division por cero"); }
       return Res<int, str>.Ok(a / b);
   }

   fn texto(Res<int, str> r) -> str {
       match (r) {
           case Res<int, str>.Ok(v)  { return f"ok {v}"; }     // 'v' es un 'int'
           case Res<int, str>.Err(m) { return f"error: {m}"; }  // 'm' es un 'str'
           case Res<int, str>.Vacio  { return "vacio"; }
       };
       return "?";
   }

   fn main() -> int {
       stdp.println(texto(divide(10, 2)));   // ok 5
       stdp.println(texto(divide(1, 0)));    // error: division por cero
       return 0;
   }

``Res<int, str>.Ok(5)`` construye un ``Res<int, str>`` con un payload ``int``:
el payload ``T`` se **sustituye** por el argumento, como un campo de
``Caja<T>``. Las reglas son las de los genéricos y las del enum suma, sin
ninguna nueva:

* los argumentos se escriben **siempre**, y no se deducen: ``Res.Ok(5)``, la
  variante pelada (``Ok(5)``, ``Vacio``) o un número de argumentos que no es
  el suyo es ``SEM027``; y argumentos a un enum que no es genérico, también;
* dos instancias son dos tipos: un ``Res<str, int>`` no entra en un
  ``Res<int, str>`` (``AST006``), ni un patrón de una sobre un sujeto de la
  otra;
* el ``match`` se comprueba como el de cualquier enum (``SEM030``) y lo que
  liga un patrón es el payload prestado;
* la propiedad se decide con el payload sustituido: ``Res<R, int>`` destruye
  su ``R``; ``Res<int, int>`` se copia libremente;
* en un f-string el payload se escribe como el tipo que lo sustituye
  (``Ok(VERDE)`` para un ``Res<Color, str>``).

``Res<int, str>.Ok`` es la tercera lectura de ``<`` tras un nombre, junto al
literal (``Caja<int>{...}``) y la llamada (``maximo<int>(...)``): son
argumentos de tipo si tras el ``>`` viene un ``.``, y si no, el ``<`` es una
comparación como siempre.

.. note::

   Hoy los enums genéricos son del **intérprete**: el HIR lleva sus
   parámetros (``EnumDecl.type_params``), la VM rechaza el programa con
   ``VM002`` en la declaración y el target web, que no traduce ningún enum
   con payload, con ``WEB100``.

.. _igualdad-y-orden:

Igualdad y orden
~~~~~~~~~~~~~~~~~

``==`` y ``<`` responden dos preguntas distintas, y cada tipo responde las dos
a su manera.

**Igualdad: ``==`` compara valores.** Un ``struct`` es un valor —ligarlo a otro
nombre lo copia—, así que dos structs son iguales si lo son sus campos, uno a
uno. Un enum con datos, si son la misma variante con el mismo payload. Es
recursivo: cada campo se compara con *su* igualdad.

.. code-block:: srcx
   :class: fragmento

   var Punto a = Punto{ x: 1, y: 2 };
   var Punto b = a;                       // una copia
   a == b                                 // true
   a == Punto{ x: 1, y: 3 }               // false
   Forma.Circulo(3) == Forma.Circulo(3)   // true

Un tipo que necesite otra noción de igual declara ``__eq__`` y manda él —en
el propio tipo y en cualquier campo de ese tipo dentro de otro—; ``a != b`` es
siempre la negación de ``a == b``.

Antes, sin ``__eq__`` se comparaba la **identidad**: ``b = a; a == b``
daba ``false`` justo cuando ``b`` era una copia exacta. Era un comportamiento
del intérprete, no una decisión: comparaba dos objetos de Python.

Dos decisiones tomadas, con su porqué:

Un puntero se compara por su **dirección**
   ``&n == &n`` es ``true``; dos punteros a dos variables que valen lo mismo
   son distintos. Es el valor del puntero —un préstamo de *esa* celda—, y
   seguirlo para comparar lo apuntado podría no terminar (una lista circular)
   o declarar iguales dos préstamos de cosas distintas. Vale igual dentro de
   un campo.

Un tipo que guarda recursos no tiene regla aparte
   Sus recursos se alcanzan por punteros, y los punteros se comparan por
   dirección; así que dos dueños distintos de dos bloques distintos son
   distintos aunque guarden lo mismo. El intérprete no puede hacerlo mejor:
   no sabe cuántas celdas de un bloque están en uso (eso lo lleva otro campo,
   por convención). El tipo que sí lo sabe declara ``__eq__``:
   ``array.Vector`` lo hace (mismo ``len`` y elementos iguales), y por eso una
   copia de un vector es igual a su original.

**Orden: ``<`` lo da el tipo.** ``<``, ``<=``, ``>`` y ``>=`` ordenan, de forma
nativa, los números, ``char`` y ``str`` (por sus puntos de código), ``byte`` y
los enums **sin datos** (son enteros: por el valor de su variante). Un tipo
propio se ordena declarando **un** hook:

.. code-block:: srcx
   :class: fragmento

   struct { int clave; str nombre; } Item;

   // negativo: 'a' va antes; 0: empatan; positivo: va después
   hook fn __cmp__(Item ptr a, Item ptr b) -> int {
       return a.clave - b.clave;
   }

Los cuatro operadores salen del mismo entero; por eso es un hook y no cuatro
(``__lt__``, ``__le__``…), que podrían contradecirse. Sin ``__cmp__``,
ordenar un tipo propio es ``AST006``, igual que ordenar un ``bool``. Un enum
sin datos **no** puede declarar ``__eq__``, ``__cmp__`` ni ``__hash__``
(``SEM006``): al ejecutar es un entero, y el hook no se llamaría nunca.

**En un genérico.** Dentro de ``fn menor<T>(T a, T b)``, ``a < b`` no se puede
decidir: depende de con qué se instancie. El cuerpo se acepta y queda
anotado que *ordena su* ``T``; lo que se comprueba es **cada instancia**, con
el tipo concreto. ``menor<int>`` y ``menor<Item>`` compilan; ``menor<Punto>``
—sin ``__cmp__``— es ``SEM039`` en la llamada, y el mensaje dice dónde
ordena el genérico. El requisito viaja: un genérico que llama a otro que
ordena su ``T`` también lo ordena. Es la misma maquinaria que decide qué
instancias copiarían un dueño (``SEM038``). Con la :ref:`cota <cotas>`
``fn menor<T: Ord>`` el ``<`` se comprueba en la definición y el requisito
queda escrito en la firma: la instancia lo cumple en su llamada (también
``SEM039``, diciendo qué cota falta).

``==`` sobre un ``T`` no exige nada: con igualdad de valor, todo tipo tiene
una.

``array.Vector`` es el primer consumidor: ``v.sort()`` ordena con ``<`` de
forma **estable** (mezcla de abajo hacia arriba) y sirve para cualquier ``T``
que se ordene.

.. note::

   Hoy esto es del **intérprete**. La VM todavía no despacha ``__cmp__`` ni
   compara por valor (compara identidades), y el target web no se revisó.
   ``c_errorstfix.md`` lo lleva.

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

.. _funciones-como-valores:

Funciones como valores
~~~~~~~~~~~~~~~~~~~~~~~

Una función con nombre es un **valor**: se guarda en una variable, un campo o
un vector, se pasa, se devuelve y se llama. Su tipo se escribe con la misma
palabra que la declara, seguida de un paréntesis en vez de un nombre:

.. code-block:: srcx

   #from io #import stdp

   fn doble(int x) -> int { return x * 2; }
   fn triple(int x) -> int { return x * 3; }

   fn aplica(fn(int) -> int f, int x) -> int { return f(x); }

   fn elige(bool rapido) -> fn(int) -> int {
       if (rapido) { return doble; }
       return triple;
   }

   fn main() -> int {
       var fn(int) -> int g = doble;
       stdp.println(f"{g(5)} {aplica(triple, 5)} {elige(false)(2)}");  // 10 15 6
       stdp.println(f"{g} {g == doble}");                             // <fn doble> true
       return 0;
   }

**Qué es un valor.** Una función del módulo (``doble``), una de una librería
(``stdp.println``) y un método de ``@impl`` escrito ``Tipo.metodo``: su
receptor ya es explícito en la declaración, así que ``Punto.distancia`` es un
``fn(Punto ptr) -> int`` y se llama pasándole el receptor
(``Punto.distancia(&p)``). **No** lo son, y es ``SEM044``: un hook o un
dunder (los invoca el lenguaje), un **prototipo** sin cuerpo (lo pone el host
o un ``#extern``, distinto en cada motor), una función **genérica** —ni
siquiera instanciada: ``maximo<int>`` sin llamarla es ``PAR012``—, un método
de un tipo genérico y un método cuyo receptor se recibe por valor y tiene
destructor. Una genérica se pasa envolviéndola en una función con los tipos
escritos.

**Sin capturas.** El valor es la función y nada más: no se lleva variables de
donde se nombró. Por eso no tiene destructor y se copia libremente. Lo que
SÍ lee el entorno es una :ref:`lambda <lambdas>`, y por eso solo vive
dentro de la llamada que la recibe; la contrapartida es que un
**parámetro** de tipo ``fn(...) -> R`` es prestado: se llama o se pasa,
pero no se guarda ni se devuelve (``SEM051``).

**Llamar a través de un valor** se comprueba exactamente como una llamada
directa: la aridad (``SEM008``), el tipo de cada argumento (``AST006``) y la
propiedad — pasar algo con destructor a un ``fn(R) -> int`` exige ``move``
(``SEM032``), porque el parámetro es su nuevo dueño. Llamar a algo que no es
una función (``n(3)`` con ``n`` un ``int``, ``p.noexiste()``) es ``SEM042``;
antes pasaba sin decir nada.

**El tipo.** ``fn(A, B) -> R``; sin flecha, el retorno es ``void``, igual que
al declarar. Lo que sigue a la flecha es un tipo completo, con sus sufijos:
``fn(int) -> int?`` **devuelve** un ``int?``. Una función que puede faltar se
escribe entre paréntesis, ``(fn(int) -> int)?``, y se puede llamar: si vale
``null`` es un error de ejecución (``RT004``), como leer un campo por un
puntero nulo. Un tipo función solo es asignable a **sí mismo**: sin varianza
ni conversiones.

**Lo que se puede hacer con uno.** ``==`` / ``!=`` comparan **identidad** (la
misma función). Un f-string lo escribe ``<fn nombre>`` (``<fn Punto.distancia>``
para un método); ``print(g)`` no, porque despacharía a un ``__print__`` que no
existe. No tiene orden (``<`` es ``AST006``) ni **hash** (``AST006``): no
puede ser clave de un diccionario. Ni aritmética, ni ``[]``, ni métodos.

**Genéricos.** Los argumentos de tipo se :ref:`deducen <deduccion>` también a
través de un tipo función: ``func.map(&v, texto)`` liga ``T`` desde
``Vector<T> ptr`` y ``U`` desde ``fn(T ptr) -> U``, y la forma escrita
(``func.map<int, str>(&v, texto)``) sigue valiendo. La librería lo usa en
``Vector.sort_by``, ``Vector.filter``, ``func.map`` y ``func.fold``. Dentro de
un genérico, ``fn(T) -> R`` es la forma de pasarle comportamiento a ``T``.

.. note::

   Hoy esto es del **intérprete**. El HIR lo transporta con un ``TypeKind``
   nuevo (``FUNCTION_TYPE``, ver ``hir.proto``); la VM y el target web todavía no
   lo ejecutan y lo **rechazan** con su código, nunca hacen otra cosa:

   - la VM, al bajar al MIR cada función que lo usa, con ``VM001`` y su
     posición (``suri --run compiler`` lo ejecuta entonces en el
     intérprete). Una librería que lo declara (``Vector.sort_by``) no impide
     correr un programa que no la llama. Sus vistas (``--pretty``,
     ``--summary``) sí lo leen y lo escriben ``fn(A) -> R``, igual que
     ``--hir-pretty``;
   - el target web, en la contención, con ``WEB103`` en cada línea que lo
     usa, sea cual sea la política (ni ``--unrestricted`` lo deja pasar).

   Para ejecutarlo: ``python V0/main.py prog.srcx --run interpreter``.

.. _lambdas:

Lambdas
~~~~~~~

Una **lambda** es una función sin nombre, escrita donde se usa, con **todos**
sus tipos escritos —los parámetros y el retorno: no hay inferencia—. Tiene
dos formas: la **corta**, con una expresión tras ``:``, y la **de bloque**,
con sentencias y ``return``:

.. code-block:: srcx

   #from io #import stdp
   #import array.vector as vec
   #import func

   struct { str nombre; int edad; } P;

   fn main() -> int {
       var vec.Vector<P> gente = vec.dynamic<P>(3);
       gente.push(P{ nombre: "ana", edad: 30 });
       gente.push(P{ nombre: "bea", edad: 20 });
       gente.push(P{ nombre: "cris", edad: 25 });
       gente.sort_by(lambda (P ptr a, P ptr b) -> int: a.edad - b.edad);

       var int umbral = 22;
       var vec.Vector<P> mayores = gente.filter(lambda (P ptr p) -> bool: p.edad > umbral);

       var vec.Vector<str> nombres = func.map(&mayores, lambda (P ptr p) -> str {
           var str n = p.nombre;
           return f"{n}({p.edad})";
       });
       stdp.println(f"{gente.at(0).nombre} {mayores.len()} {nombres.get(0)}");
       return 0;   // bea 2 cris(25)
   }

**Dónde vale: solo como argumento.** Una lambda solo puede ser el
**argumento** de una llamada cuyo parámetro está **escrito** como
``fn(...) -> R`` (una función, un método, un valor función, el método de una
cota). En cualquier otro sitio es ``SEM050``, con lo que hay que escribir en
su lugar —una función con nombre—: guardarla en una variable, un campo o un
vector; devolverla; compararla con ``==``; escribirla en un f-string;
pasarla a un parámetro ``T`` (aunque ``T`` se instanciara con un tipo
función, el cuerpo del genérico puede guardarlo), a uno ``(fn(...) -> R)?``,
a una variante de un enum (que la guarda) o a un **prototipo** (su cuerpo lo
pone el host, que podría guardarla). Es lo que la hace segura: **no escapa**
de la llamada que la recibe (ver abajo).

**Su tipo** es ``fn(A) -> R``, lo escrito, y se comprueba contra el
parámetro como el de una función con nombre: la aridad y los tipos exactos,
sin conversiones (``AST006``). Con un parámetro genérico participa en la
:ref:`deducción <deduccion>` con sus tipos escritos:
``func.map(&mayores, lambda (P ptr p) -> str: ...)`` liga ``T=P`` y
``U=str``.

**El cuerpo es el de una función.** Los nombres resuelven primero a sus
parámetros y sus locales, y después al entorno. ``return`` devuelve **de la
lambda** (y se comprueba contra su retorno, ``AST012``), no de la función
que la contiene; ``break`` y ``continue`` no la cruzan (``PAR013``: dentro
de la lambda no hay un bucle de fuera) y ``expect`` no vale. La forma corta
es azúcar de ``{ return e; }`` —o ``{ e; }`` con ``-> void``— y su expresión
llega tan lejos como puede, como en Python: ``lambda (int x) -> bool: x == y``
compara dentro del cuerpo, y dentro de un f-string va entre paréntesis
(``{(lambda ...)}``), porque el ``:`` sería el del formato.

**Lo que lee del entorno, lo lee prestado.** Una lambda puede leer los
locales y los parámetros de quien la escribe —sus **capturas**— sin
escribir nada: la captura es **implícita** y **de solo lectura**. No es una
copia tomada al escribirla: lee la variable viva, con el valor que tiene
cuando se la llama. Una global no es una captura (la ve igual cualquier
función, y la puede asignar como cualquier función). Lo capturado no se
modifica, con los códigos de siempre:

- asignarlo, moverlo o liberarlo, o llamar a un método que modifica su
  receptor, es ``SEM003``;
- escribir a través de un puntero capturado —aunque sea ``ptr mutable``— es
  ``SEM015``; dentro de la lambda un ``ptr mutable`` capturado se ve como
  ``ptr``, y ``&x`` de algo capturado da un ``ptr``, así que tampoco se
  entrega a quien escribiría (``AST006``);
- cederlo (``return x``, ``throw x``) si tiene destructor es ``SEM036``,
  como ceder algo a lo que se llega por un puntero; leer algo capturado que
  ya se movió es ``SEM004``.

Sus **propios** parámetros y locales son suyos: se asignan y se mueven, y
los que poseen recursos mueren al terminar **cada** llamada (ver
:ref:`la captura <memoria-lambdas>` en el modelo de memoria).

**Por qué no escapa: un parámetro función es prestado.** Que la lambda solo
vaya a un parámetro ``fn(...) -> R`` no basta si la función que la recibe
pudiera guardarla (en un campo, una global, un vector) o devolverla. Por eso
un **parámetro** de tipo ``fn(...) -> R`` —de una función, de un método o de
otra lambda— es **prestado**, como un ``ptr``: solo se **llama**
(``f(x)``) o se **pasa** a otro parámetro de tipo función. Guardarlo,
devolverlo, compararlo, escribirlo o pasarlo a un ``T`` es ``SEM051``:

.. code-block:: srcx
   :class: fragmento

   struct { fn(int) -> int f; } Caja;
   fn guarda(fn(int) -> int f) -> Caja { return Caja{ f: f }; }      // SEM051
   fn dos_veces(fn(int) -> int f, int x) -> int { return f(f(x)); }  // vale

Con eso, todo lo que recibe una lambda la usa durante la llamada y nada más
(``Vector.sort_by``, ``Vector.filter``, ``func.map`` y ``func.fold`` ya lo
cumplían: solo llaman a su función). Una función **con nombre** sigue siendo
un valor como cualquier otro —no captura nada—, y quien necesite **guardar**
una función que recibe declara el parámetro ``(fn(...) -> R)?``: ese no
admite lambdas, así que sí se puede guardar (y se desenvuelve con ``match``
o ``??`` antes de llamarlo).

.. note::

   Hoy las lambdas son del **intérprete**: el valor es el cuerpo más el
   marco donde se escribió, y las capturas se leen de ahí. El HIR las
   transporta con un nodo aditivo (``LambdaExpr``: la firma, el cuerpo y
   la lista de lo que lee, ver ``hir.proto``); ``--hir-pretty`` escribe la
   firma en la línea y, debajo, ``cuerpo de la lambda ⟨lee: umbral⟩`` con
   sus sentencias. La VM la **rechaza** al bajar a MIR con ``VM004`` (y su
   posición) y el target web en la contención con ``WEB104``, sea cual sea
   la política; ninguno hace otra cosa.

.. _cotas:

Cotas y conceptos
~~~~~~~~~~~~~~~~~~

Una **cota** dice qué tiene un parámetro de tipo. Se escribe junto al
parámetro, con ``:`` y, si son varias, unidas con ``+``, en cualquier
declaración genérica: una función, un struct, un enum, un ``const type`` o
un bloque ``@impl``.

.. code-block:: srcx

   #from io #import stdp

   @trait struct {
       fn area(self ptr s) -> int;
   } Forma;

   @impl(Forma) struct { int r; } Circulo;
   @impl Circulo { fn area(Circulo ptr self) -> int { return self.r * self.r * 3; } }

   @impl(Forma) struct { int l; } Cuadrado;
   @impl Cuadrado { fn area(Cuadrado ptr self) -> int { return self.l * self.l; } }

   fn mayor<T: Forma>(T ptr a, T ptr b) -> int {
       if (a.area() < b.area()) { return b.area(); }
       return a.area();
   }

   fn menor<T: Ord>(T a, T b) -> T {
       if (a < b) { return a; }
       return b;
   }

   fn main() -> int {
       var Circulo c = Circulo{ r: 2 };
       var Circulo d = Circulo{ r: 1 };
       var Cuadrado q = Cuadrado{ l: 5 };
       stdp.println(f"{mayor(&c, &d)} {mayor(&q, &q)} {menor(3, 9)} {menor("b", "a")}");
       return 0;    // 12 25 3 a
   }

**Dentro del cuerpo**, ``T`` ofrece lo que sus cotas prometen, y nada más:
con ``T: Forma``, ``a.area()`` se comprueba ahí, en la **definición**, con la
firma del trait (``self`` es ``T``); un método que ninguna cota promete sigue
siendo ``SEM043``. Con ``T: Ord`` el ``<`` también se comprueba en la
definición, sin la comprobación por instancia.

**En cada instancia** el argumento de tipo tiene que cumplir sus cotas, y si
no, el error sale en la **llamada**, diciendo qué cota falta y, si el tipo se
dedujo, desde qué argumento. El código es el de la operación que falta, el
mismo que daba la comprobación por instancia: ``SEM039`` si no se ordena,
``AST006``/``SEM001`` si no tiene hash, ``SEM001`` si no tiene
``__print__`` y ``SEM021`` si no declara el trait. Un parámetro de tipo del
llamador cumple lo que el llamador promete; si no lo promete, ``Ord`` y
``Hash`` se siguen comprobando por instancia (como sin cotas), y lo demás es
``SEM043``.

**Sin cota todo sigue como antes**: ``SEM043`` para métodos, campos y ``[]``,
y la comprobación por instancia de ``<``, ``hash``, la copia y ``sizeof``.

Una cota nombra una de dos cosas:

Un trait del usuario
   Un ``@trait`` de este archivo (ver :ref:`traits <traits>`). Se cumple de
   forma **explícita**: el tipo lo declara con ``@impl(Forma)``. Un trait
   puede pedir dunders y también métodos de un bloque ``@impl``.

Un concepto nativo
   ``Eq``, ``Ord``, ``Hash`` y ``Print``. Se cumplen **solos**, con las reglas
   que el lenguaje ya aplica a un tipo concreto:

   .. table::
      :widths: auto

      =========  ==================================================================
      Concepto   Lo cumplen
      =========  ==================================================================
      ``Eq``     todos los tipos (``==`` es igualdad de valor; ``__eq__`` la cambia)
      ``Ord``    los números, ``char``, ``str``, ``byte``, los enums sin datos y
                 los tipos con ``__cmp__``
      ``Hash``   ``int``, ``bool``, ``char``, ``str``, ``byte``, los enums sin
                 datos y los tipos con ``__hash__`` (no ``float`` ni funciones)
      ``Print``  los primitivos y los tipos con ``__print__``; no un enum sin
                 datos, que al ejecutar es un entero y su ``__print__`` no se
                 llamaría dentro del genérico
      =========  ==================================================================

   ``print(x)`` con ``T: Print`` despacha al ``__print__`` del tipo de la
   instancia, y un primitivo se escribe como en un f-string, sin salto de
   línea. Fuera de un genérico pasa lo mismo: ``print(5)`` escribe ``5``
   (antes de la 0.4.1 era ``SEM001``); ``len(3)`` sigue siendo un error, y un
   puntero a un primitivo no es un primitivo (``print(p)`` es ``SEM001``).

   ``print`` es **variádico**: ``print(a, b, c)`` escribe cada argumento
   separado por **un** espacio, sin salto de línea al final, y cada uno
   tiene que cumplir ``Print`` (el error, si no, es el de un ``print`` de un
   argumento y señala ese argumento). Los argumentos se evalúan y se
   escriben **en orden**, uno tras otro: si el segundo lanza, el primero ya
   se escribió. Vale como **sentencia** (también la suelta de un script y el
   cuerpo corto de una lambda ``void``); dentro de una expresión, y
   ``print()`` sin argumentos, es ``SEM008``. ``len`` y ``hash`` llevan
   exactamente un argumento (``SEM008`` si no). Una ``fn print`` del
   programa manda sobre la nativa, con su propia aridad. En el HIR no hay
   nada nuevo: la semántica lo descompone en ``print`` de un argumento y
   ``print(" ")`` entre ellos (``--emit-stage desugar`` lo muestra).

   .. code-block:: suriax

      fn main() -> int {
          var int n = 42;
          print("total:", n, 1.5, true);   // total: 42 1.5 true
          return 0;
      }

**Dónde viven los nombres de los conceptos.** No en una librería: un
concepto no se puede escribir en suriaX (no hay cómo decir "se cumple solo"),
y obligaría a importar algo para escribir ``T: Ord``. Son nombres
**predefinidos que solo existen en posición de cota**: no son palabras
reservadas ni ocupan el espacio de tipos ni el de valores, y un trait del
archivo con el mismo nombre manda (la regla de una ``fn print`` del usuario
frente al hook). Un trait de otra librería todavía no se puede usar como cota
(``SEM021``).

**Cotas de un tipo.** ``struct { K k; V v; } Par<K: Ord, V>;`` exige que todo
``Par<X, ...>`` escrito —una anotación, un literal— tenga ``X: Ord``. Los
métodos y los hooks de ``Par<K, V>`` no repiten la cota: solo se llaman sobre
un ``Par`` que existe, y no existe ninguno cuya ``K`` no se ordene. Una
cota en un ``@impl`` hace que sus métodos pidan algo a la instancia: así
``array.Vector`` declara ``sort`` en un ``@impl Vector<T: Ord>`` aparte, y
``v.sort()`` sobre un vector de un tipo sin orden es ``SEM039`` en la
llamada.

Escribir un tipo acotado **dentro de una función genérica** con un parámetro
que no promete la cota (``Box<U>`` con ``struct { T v; } Box<T: Ord>;`` en
``fn boxed<U>(U a)``, en el cuerpo o en la firma) sigue la regla de las
funciones acotadas: ``Ord`` y ``Hash`` se comprueban **por instancia**
(``boxed(3)`` compila; ``boxed(true)`` es ``SEM039`` en la llamada), y
``Print`` y los traits son ``SEM043`` ahí mismo. En la declaración de otro
tipo (``struct { Box<U> b; } Outer<U>;``) no hay una instancia de función
que lo decida, y cualquier cota que falte es ``SEM043``.

.. code-block:: suriax

   struct { T v; } Box<T: Ord>;

   fn boxed<U>(U a) -> int {
       var Box<U> b = Box<U>{ v: a };   // Ord se comprueba en cada instancia
       return 1;
   }

   fn main() -> int {
       var int x = boxed(3);            // vale; boxed(true) es SEM039
       return 0;
   }

.. _deduccion:

Deducción de argumentos de tipo
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Los argumentos de tipo de una llamada se escriben (``menor<int>(3, 9)``) o se
**deducen** de los argumentos. Es un subconjunto de la deducción de los
templates de C++ (``[temp.deduct.call]``, ISO/IEC 14882), sin su
complejidad:

- de cada argumento con tipo ``A`` contra su parámetro ``P``, solo en las
  formas ``T``, ``T ptr``, ``T?``, ``Nombre<..T..>`` (también anidado) y
  ``fn(..T..) -> R``;
- **sin conversiones**: ``A`` tiene que tener la misma forma que ``P``. Un
  ``int`` no liga el ``T`` de un ``T?``; un ``int ptr mutable`` sí liga el de
  un ``T ptr`` (con ``T=int``), porque la mutabilidad es del puntero y que
  pueda pasarse ahí lo decide la comprobación de siempre;
- dos argumentos que dan tipos distintos para el mismo ``T`` son ``AST007``:
  no se elige uno;
- un parámetro que solo aparece en el retorno, o del que solo llega un
  ``null``, no se deduce (``AST007``): se escribe;
- **o se escriben todos o ninguno** (``SEM027`` si no son tantos como
  parámetros);
- las cotas se comprueban **después** de deducir.

.. code-block:: srcx

   #from io #import stdp
   #import array.vector as vec
   #import func

   fn etiqueta(int ptr x) -> str { return f"<{x[0]}>"; }
   fn suma(int acc, int ptr x) -> int { return acc + x[0]; }

   fn main() -> int {
       var vec.Vector<int> v = vec.dynamic<int>(4);
       v.push(1);
       v.push(2);
       var vec.Vector<str> e = func.map(&v, etiqueta);   // T=int, U=str
       stdp.println(f"{e.get(1)} {func.fold(&v, 0, suma)}");   // <2> 3
       return 0;
   }

No es inferencia de tipos: el tipo ya está escrito en el argumento y solo se
lee de ahí (ver :ref:`alcance de la inferencia <inferencia>`).

.. _metodos-genericos:

Métodos genéricos
~~~~~~~~~~~~~~~~~~

Un método de un ``@impl`` puede tener sus **propios** parámetros de tipo (y
cotas), además de los del tipo. Se escriben o se deducen como los de una
función; no pueden repetir los del ``@impl`` (``SEM002``) y, como una función
genérica, no son un valor (``SEM044``).

.. code-block:: srcx

   #from io #import stdp

   struct { T v; } Caja<T>;

   @impl Caja<T> {
       fn map<U>(Caja<T> ptr self, fn(T) -> U f) -> Caja<U> {
           return Caja<U>{ v: f(self.v) };
       }
   }

   fn doble(int x) -> str { return f"{x * 2}"; }

   fn main() -> int {
       var Caja<int> c = Caja<int>{ v: 21 };
       var Caja<str> d = c.map(doble);           // U se deduce: str
       stdp.println(d.v);                        // 42
       return 0;
   }

Con esto ``func.map`` y ``func.fold`` podrían ser métodos de ``Vector``; de
momento siguen en ``func``.

.. note::

   La deducción, las cotas y los métodos genéricos son del frontend: el HIR
   no cambia y la VM los ejecuta como antes. Lo único nuevo al ejecutar es
   lo que despacha una cota (``print(x)`` con ``T: Print``, ``x.area()`` con
   ``T: Forma``): viaja como un ``HookRef`` cuyo dueño es el parámetro
   (``T``), igual que ``hash(x)``. El intérprete lo despacha con el tipo del
   valor; la VM lo **rechaza** con ``VM003`` al bajar a MIR, y el target web
   no representa valores de tipo ``T`` (``WEB101``/``WEB102``).

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

``null`` solo es un valor de ``T?``, y por eso **toda variable se declara con
su valor**: ``var int x;`` es ``SEM040``, en una función o en el nivel
superior. Antes se aceptaba y ``x`` valía ``null`` aunque fuera un ``int``
(``x + 1`` fallaba al ejecutar y un ``bool`` así tomaba la rama falsa en
silencio). No se inventa un valor por defecto porque esconde el olvido: se
escribe con qué empieza (``var int x = 0;``) y, si "todavía no hay valor" es
un estado legítimo, se dice en el tipo: ``var int? x = null;``. ``const type
T;`` no es una variable (declara un tipo) y sigue siendo válido.

.. _desenvolver-opcional:

Desenvolver un ``T?``
^^^^^^^^^^^^^^^^^^^^^^

Un ``T?`` no es un ``T``: no se suma, no se ordena, no se pasa donde se
espera un ``T``. Para llegar al ``T`` de dentro hay dos formas, y ninguna más:

.. code-block:: srcx

   #from io #import stdp

   struct { int? edad; } Persona;

   fn busca(int clave) -> int? {
       if (clave > 0) { return clave * 10; }
       return null;
   }

   fn describe(int? x) -> str {
       match (x) {
           case null { return "nada"; }
           case v    { return f"vale {v + 1}"; }    // 'v' es un 'int'
       };
       return "?";
   }

   fn main() -> int {
       var Persona p = Persona{ edad: null };
       stdp.println(describe(busca(4)));            // vale 41
       stdp.println(describe(p.edad));              // nada
       var int edad = p.edad ?? 18;                 // 18
       var int total = busca(-1) ?? busca(2) ?? 0;  // 20
       stdp.println(f"{edad} {total}");
       return 0;
   }

**``match`` con ``case null`` y ``case v``.** Sobre un sujeto ``T?`` —una
variable, un campo, el resultado de una llamada—, ``case null`` encaja con
``null`` y ``case v`` con cualquier otro valor: dentro de esa rama ``v`` es el
**contenido**, de tipo ``T``, y no existe fuera de ella. Si ``T`` es un enum,
sus variantes también son patrones (``case Forma.Circulo(r)``) y solo encajan
si el sujeto no es ``null``. Las demás ramas siguen siendo lo de siempre:
``case 7`` compara.

* ``case v`` liga un nombre **nuevo**. Si ``v`` ya existe es ``SEM002``: en un
  ``match`` sobre un ``int`` ``case v`` *compara* con la variable ``v``, y aquí
  la taparía; antes de elegir una lectura en silencio, el compilador pide
  otro nombre.
* Lo que no entra en ninguna rama es ``SEM030`` (aviso), la misma regla que
  el ``match`` sobre un enum: si falta ``case null``, ``null`` no hace nada,
  y si ``T`` es un enum, también cada variante que no se nombra (o un
  ``case v`` que las cubra). Los valores de un ``int?`` no se exigen, igual
  que en un ``match`` sobre un ``int``. Si no hay nada que hacer con ``null``,
  se dice: ``case null { }``.
* Una rama **detrás** de ``case v`` no se ejecuta nunca (``SEM046``), salvo
  ``case null``.
* **Propiedad**: ``v`` es el contenido MISMO, **prestado**, igual que el
  payload que liga ``case E.A(x)`` (ver :ref:`propiedad del patrón
  <prestamo-de-patron>`): no se copia, no se reasigna (``SEM003``), se
  modifica solo si el sujeto se puede modificar, y cederlo (``move v``,
  ``return v``) es ``SEM036``. Al cerrar la rama no se destruye: sigue siendo
  del sujeto.
* Sobre un ``T ptr?``, ``case null`` mira el **puntero** (no lo
  desreferencia) y ``case p`` liga el ``T ptr``. Un puntero a un opcional
  (``T? ptr``) no es un opcional: el ``match`` lo desreferencia y compara
  como siempre.

**``x ?? d``** vale el contenido de ``x`` si no es ``null``, y si lo es, ``d``.
``d`` **solo se evalúa si hace falta** (cortocircuito, como ``or``).

* ``x`` tiene que ser un ``T?`` y ``d`` **exactamente** un ``T``; el resultado
  es un ``T`` (``AST006`` si no). Exactamente quiere decir sin conversiones:
  ni la de un literal a un tipo de rango (``b ?? 0`` con ``b: byte?`` necesita
  ``cast<byte>(0)``), ni soltar ``mutable`` (``q ?? &n`` con ``q: int ptr?`` y
  ``n`` un ``var``), ni un ``T?`` como defecto (para eso se encadena:
  ``a ?? b ?? 0``).
* **Precedencia**: por debajo de ``or`` y por encima de la asignación, y
  asocia a la **derecha**, como en C# y en Swift: ``a ?? b ?? c`` es
  ``a ?? (b ?? c)`` y ``x ?? a or b`` es ``x ?? (a or b)``. Ver la
  :ref:`tabla de precedencias <precedencia>`.
* **Propiedad**: el resultado es una **copia** del contenido, como cualquier
  lectura. Si ``T`` tiene destructor, el original y la copia serían dos
  dueños: ``SEM032``, la misma regla que ``var R b = a;``. Para un ``T`` así,
  ``match``, que presta. Dentro de un genérico lo decide cada instancia
  (``SEM038``).
* ``??`` no es un token: son dos ``?`` **pegados** en posición de operador,
  igual que ``>>``. Por eso ``int??`` sigue siendo un tipo.

**No hay estrechamiento.** Después de ``if (x != null)`` el tipo de ``x``
sigue siendo ``T?``: el compilador no deduce el tipo de una variable por el
camino que tomó el programa (es la decisión de no inferir, ver
:ref:`la inferencia <inferencia>`). Desenvolver se escribe.

.. note::

   Hoy esto es del **intérprete**. La VM lo **rechaza** al bajar a MIR, con
   ``VM002`` y su posición (``case v``, una variante sobre un sujeto ``E?`` y
   ``??``), y ``suri --run compiler`` lo ejecuta entonces en el intérprete.
   El target web no representa un ``T?`` (``WEB101``) ni el operador ``??``
   (``WEB100``). Ninguno de los dos ejecuta otra cosa.

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

El filtro compara **tipos**, no valores: cada ``throw`` lleva el tipo
**estático** de su expresión —el que decidió el compilador— y una rama encaja
si su tipo es exactamente ese, con su nombre completo. Por eso ``char`` y un
``str`` de un carácter no se confunden, y ``catch (b.Error e)`` no atrapa el
``Error`` homónimo de otra librería ``a``. Funciona con structs, con enums y
con primitivos, igual en el intérprete que en la VM.

El valor lanzado pasa a manos del ``catch`` que lo atrapa, que lo destruye al
cerrar su bloque. Igual que ``return r;``, un ``throw r;`` **cede** ``r`` sin
escribir ``move``: después del ``throw`` la variable no puede volver a usarse,
así que el ``move`` no diría nada nuevo. El compilador lo inserta y el HIR lo
muestra (``throw move r``). Un ``__free__`` nunca puede lanzar (``SEM034`` si
está escrito, ``RT021`` si ocurre al ejecutar). La serie ``test/e2e/excepciones/`` tiene un programa
comentado por cada aspecto (propagación, filtros, relanzar, control de flujo,
destrucción durante el desenrollado, librerías, un ``throw`` no capturado,
``finally``).

.. _finally:

``finally``: lo que corre por cualquier salida
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Un ``try`` puede terminar con un bloque ``finally`` (con o sin ramas
``catch``). Corre **siempre** que el control sale del ``try`` o de un
``catch``: al terminar normalmente, con un ``return``, con un ``break`` o
``continue`` que lo atraviesa, y con una excepción que nadie atrapó —que,
después del ``finally``, sigue subiendo—.

.. code-block:: srcx
   :class: fragmento

   fn guarda(str ruta) -> void {
       try {
           escribe(ruta);
       } catch (ErrorDeArchivo e) {
           stdp.println(e.mensaje);
       } finally {
           stdp.println("cerrando");    // en los tres caminos
       };
   }

Reglas:

- El valor de un ``return`` se calcula **antes** del ``finally``: cambiar la
  variable dentro de él no cambia lo devuelto.
- Lo declarado dentro del ``try`` se destruye (corre su ``__free__``)
  **antes** del ``finally``. Un ``finally`` anidado corre antes que el de
  afuera.
- Del ``finally`` no se sale con ``return``, ni con un ``break``/``continue``
  que salga de él (``PAR027``): reemplazaría la salida que ya estaba en curso
  y, si viajaba una excepción, se la tragaría en silencio (la regla de PEP 765
  en Python). Un bucle **dentro** del ``finally`` sí puede usarlos.
- Si el ``finally`` lanza mientras ya sube otra excepción, habría dos a la
  vez: el programa termina con ``RT022``, como un destructor que lanza. Sin
  otra en vuelo, un ``throw`` en el ``finally`` es uno más.

Para liberar un recurso **no hace falta** ``finally``: su ``__free__`` ya
corre en toda salida del ámbito. ``finally`` es para lo que no es de un
valor (un mensaje, un contador, restaurar un estado). En un ``try`` no hay una
variante que corra solo al fallar (el ``errdefer`` de Zig): eso ya lo dice un
``catch`` que relanza. La hay en un ``test`` (``errfinally``), porque ahí un
``expect`` que falla no pasa por ningún ``catch``; ver el intérprete.

.. _with:

``with``: un recurso, un guardián o un receptor con ámbito
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

``with`` abre un bloque con uno o más valores que viven hasta que el bloque
termina, por cualquier camino. No hay un protocolo nuevo (el
``__enter__``/``__exit__`` de Python): lo que pasa al salir es el
``__free__`` de cada valor, en orden inverso. Es azúcar: el parser lo convierte
en un bloque con sus declaraciones.

.. code-block:: srcx
   :class: fragmento

   // un RECURSO con nombre (varios, separados por coma)
   with (var arch.File f = arch.open("notas.txt", "w")) {
       f.write("hola\n");
   };                                  // aquí se cierra

   // lo mismo, con la declaración como primer argumento de la llamada
   with arch.open(var arch.File f, "notas.txt", "r") {
       stdp.println(f.read());
   };

   // un GUARDIÁN sin nombre: su __free__ deshace el cambio al salir
   with (cambiar_idioma("en")) {
       imprimir_reporte();
   };

   // un RECEPTOR: '.campo' es un campo (o un método) del valor del with
   with (ventana) {
       .ancho = 900;
       .alto = 600;
       .show();
   };

Reglas:

- ``with f(var T x, a, b)`` es exactamente ``with (var T x = f(a, b))``, con
  cualquier función.
- Un valor sin nombre que es un **lugar** (``ventana``, ``a.b``) es el receptor
  tal cual: no se copia (un struct es un valor, y cambiar una copia no cambiaría
  la ventana) y el ``with`` no lo destruye, porque no es suyo. Uno que es un
  **temporal** (``cambiar_idioma("en")``) vive hasta el final del bloque. Es el
  único binding del lenguaje sin tipo escrito: no hay nombre que anotar.
- ``.campo`` exige un ``with`` de **un** valor alrededor (``PAR028``). Con el
  punto delante, un campo del receptor no se confunde con una variable: el
  ``with`` de nombres pelados de Pascal (y de JavaScript) cambiaba de
  significado en silencio cuando aparecía un local con el mismo nombre.

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
   const int8? pequeno = null;     // todavía sin valor: lo dice el tipo

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

Eso es todo lo que hay, y no va a crecer: suriaX no tiene inferencia de
tipos. El tipo de una variable, de un parámetro y de un retorno se escribe
siempre.

Otra cosa es la **deducción** de los argumentos de una llamada genérica: el
tipo ya está escrito en el argumento y solo se lee de ahí, como en los
templates de C++: de ``T``, ``T ptr``, ``T?``, ``Caja<T>`` y ``fn(T) -> R``,
sin conversiones (ver :ref:`la deducción <deduccion>`). Hindley-Milner quedó
descartado por su
complejidad, por su fricción con el modelo de memoria y por la distancia
entre su maquinaria y el objetivo de que cada fase sea legible.

Cuando el tipo de una expresión no se puede determinar, el compilador lo dice
con ``AST007`` en vez de suponer.

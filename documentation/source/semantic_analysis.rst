5. Análisis semántico
======================

La semántica recibe el AST ya anotado con tipos y responde a las preguntas que
la sintaxis no puede: ¿existe este nombre?, ¿se puede escribir en él?, ¿esta
función se llama con los argumentos que declara?, ¿este puntero apunta a algo
que sigue vivo?

Produce dos cosas, y son exactamente las que viaja el HIR: el **AST validado**
y la **tabla de símbolos**.

.. _tabla-de-simbolos:

Tabla de símbolos
------------------

La tabla es persistente y tiene **dos espacios de nombres separados**, de modo
que un tipo y una variable pueden llamarse igual sin pisarse:

Tipos
   ``struct``, ``enum`` y los tipos nominales opacos.

Valores
   funciones, variables, items de enum e imports.

Cada símbolo guarda su nombre, su clase, su posición, su tipo, si es mutable,
los tipos de sus parámetros y sus miembros. Aparte viven los **hooks**
(indexados por tipo dueño y clase de hook) y la **tabla de conversiones**.

Para verla como diagrama:

.. code-block:: console

   $ python V0/main.py programa.srcx --dump-symbols-table

.. _scopes:

Ámbitos
--------

Los ámbitos se anidan: global, función, bloque. Un nombre se busca del más
interno al más externo, y el primero que aparece gana.

.. code-block:: srcx

   var int x = 1;          // global

   fn f() -> int {
       var int x = 2;      // sombrea al global dentro de f
       if (true) {
           var int x = 3;  // y este dentro del bloque
           return x;       // 3
       }
       return x;           // 2
   }

Solo el ámbito **global** sobrevive a esta fase: los de bloque son derivables
recorriendo los cuerpos, así que no se serializan.

Declarar dos veces el mismo nombre en el mismo ámbito es ``SEM002``; usar uno
que no existe, ``SEM001``.

.. _mutabilidad:

Mutabilidad
------------

.. code-block:: srcx

   const int limite = 10;
   var int contador = 0;

   contador = contador + 1;   // correcto
   limite = 20;               // SEM003: asignación a un binding inmutable

Sin cualificador, un binding es ``var``. ``mutable`` no califica variables:
solo punteros, como parte del tipo (ver :doc:`type_system`).

.. _visibilidad:

Visibilidad
------------

Tres niveles, aplicables a declaraciones de nivel superior:

.. table::
   :widths: auto

   ==============  ==========================================================
   Modificador     Quién puede verlo
   ==============  ==========================================================
   ``public``      Cualquiera que importe la librería. Es el valor por defecto.
   ``private``     El mismo paquete.
   ``internal``    El mismo archivo.
   ==============  ==========================================================

.. code-block:: srcx

   public fn api(int x) -> int { return interna(x); }
   private fn interna(int x) -> int { return x + 1; }

Acceder a algo fuera de su alcance es ``SEM019``, y el mensaje dice dónde se
declaró y con qué visibilidad.

.. _move:

Move-semantics
---------------

``move`` transfiere la propiedad de un valor e **invalida el origen**:

.. code-block:: srcx

   var Punto a = Punto{ x: 1, y: 2 };
   move a;              // 'a' queda inválida a partir de aquí
   var int z = a.x;     // SEM004: uso tras move

Mover dos veces el mismo valor es ``SEM005``.

El análisis es **lineal e intra-función**: recorre el cuerpo en orden y marca
lo que se movió. Es deliberadamente conservador — no persigue todos los
caminos posibles a través de condicionales y bucles. Los casos que ese
análisis no ve los hace cumplir el runtime, que conoce el estado real de cada
celda; por eso ``move`` viaja en el HIR, con la línea del movimiento estático
anotada en el símbolo.

.. _punteros-semantica:

Punteros
---------

Tres reglas, verificadas aquí:

1. ``&x`` exige un *lvalue*: una variable, un campo, un elemento (``SEM013``).
2. ``free x;`` exige que ``x`` sea un puntero (``SEM014``).
3. Escribir a través de un ``ptr`` no mutable es ``SEM015``.

.. code-block:: srcx

   var int n = 5;
   int ptr mutable p = &n;
   free p;

Si el tipo apuntado declara ``__free__``, la semántica **enlaza el hook** en
el nodo, de modo que el runtime no tiene que buscarlo.

.. _hooks-semantica:

Enlace de hooks
----------------

Un hook es un método especial que el compilador **dispara solo**: el
consumidor nunca escribe ``__print__``, escribe ``print(x)``.

.. list-table::
   :header-rows: 1
   :widths: 22 43 35

   * - Hook
     - Firma
     - Se dispara con
   * - ``__print__``
     - ``fn __print__(T ptr x) -> void``
     - ``print(x)`` · ``x.print()``
   * - ``__len__``
     - ``fn __len__(T ptr x) -> int``
     - ``len(x)`` · ``x.len()``
   * - ``__free__``
     - ``fn __free__(T ptr x) -> void``
     - ``free x;``
   * - ``__sizeof__``
     - ``fn __sizeof__(T ptr x) -> int``
     - ``sizeof(T)``
   * - ``__cast__``
     - ``fn __cast__(X x) -> T``
     - ``cast<T>(x)``
   * - ``__index__``
     - ``fn __index__(T ptr x, int i) -> E``
     - ``v[i]``
   * - ``__index_set__``
     - ``fn __index_set__(T ptr mutable x, int i, E v) -> void``
     - ``v[i] = x``
   * - ``__eq__``
     - ``fn __eq__(T ptr a, T ptr b) -> bool``
     - ``a == b``
   * - ``__make__``
     - ``fn __make__(...) -> T ptr``
     - construcción del tipo

El tipo dueño sale del **primer parámetro** (desenvuelto hasta su nominal),
salvo en ``__make__``, que se asocia por su tipo de retorno porque todavía no
existe la instancia, y en ``__cast__``, cuyo dueño es el lado nominal de la
firma.

.. code-block:: srcx

   struct { str texto; int largo; } Cadena;

   hook fn __print__(Cadena ptr c) -> void {
       __write__(c.texto);
   }

   hook fn __len__(Cadena ptr c) -> int {
       return c.largo;
   }

Una firma que no cumple la convención es ``SEM006``; dos hooks de la misma
clase para el mismo tipo, ``SEM007``.

Junto a los hooks existen los **métodos dunder** libres: ``dunder fn
__loquesea__(T ptr self, ...)``, que no pertenecen al conjunto fijo y se
despachan por ``(tipo, nombre)`` al escribir ``x.__loquesea__()``. Son la base
de los traits.

.. _traits:

Traits
-------

Un trait es un **contrato**: un conjunto de firmas que un tipo debe proveer.

.. code-block:: srcx

   @trait struct {
       dunder fn __siguiente__(self) -> int;
       dunder fn __fin__(self) -> bool;
   } Iterable;

   @impl(Iterable)
   struct { int actual; int tope; } Contador;

   dunder fn __siguiente__(Contador ptr c) -> int { return c.actual; }
   dunder fn __fin__(Contador ptr c) -> bool { return c.actual >= c.tope; }

El compilador verifica la conformidad al ver ``@impl``: si falta un método o
su firma no encaja, es ``SEM021``. ``self`` en un prototipo de trait es el
tipo que hará la implementación.

.. _llamadas:

Llamadas
---------

Se comprueba que la función exista y que el número de argumentos coincida con
la firma (``SEM008``). ``print`` y ``len`` no son palabras reservadas: son
identificadores que, si no resuelven a una función declarada, despachan al
hook del tipo de su primer argumento. Una función propia llamada ``print``
tiene prioridad sobre el hook.

.. _librerias-semantica:

Resolución de librerías
------------------------

``#import`` y ``#from`` los resuelve el linker de librerías, que busca el
nombre entre los archivos ``.libsrx`` y los paquetes de las rutas
configuradas, verifica que la unidad se cierre con el ``#export`` correcto y
cachea el resultado por ruta.

De cada import salen **tres nombres distintos**, y ninguno se deriva de otro:
lo que se escribió (``io.stdp``), la unidad resuelta (``IO.stdp``) y el nombre
local al que quedó ligada (``stdp``). Los tres viajan en el HIR, de modo que
ningún consumidor tiene que repetir la resolución.

Los errores son ``SEM009`` (no se encontró), ``SEM010`` (la unidad no es
válida) y ``SEM011`` (el miembro no existe en esa librería).

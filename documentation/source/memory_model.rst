.. _modelo-memoria:

11. Modelo de memoria
======================

suriaX gestiona la memoria con **propiedad única** (*ownership*),
**destrucción determinista** (*drop*) y **arenas explícitas** para el trabajo
por lotes. No hay recolector de basura y no hay recuento de referencias: en
todo punto del programa, cada valor con recursos tiene exactamente un dueño, y
la destrucción ocurre en un lugar que se puede señalar en el código fuente.

.. note::

   Este modelo reemplaza a la gestión por regiones (RBMM) que declaraban las
   versiones hasta la 0.1.4. El razonamiento completo del cambio está en
   :ref:`decision-memoria`. Las palabras ``region``, ``shrd``, ``na``, ``in``,
   ``at``, ``new`` y ``delete`` **ya no forman parte del lenguaje**.

Las tres reglas
----------------

Propiedad única
   Todo valor que posee recursos tiene un dueño y solo uno. El dueño es la
   variable que lo nombra.

Transferencia explícita
   La propiedad no se copia por accidente: se transfiere con ``move``, y el
   origen queda inutilizable a partir de ahí.

Destrucción determinista
   Cuando el dueño sale de ámbito, el valor se destruye. El punto exacto es
   visible: es la llave que cierra.

.. _memoria-estado:

Estado de la implementación
----------------------------

El modelo está decidido; sus partes no llegaron todas a la vez. Esta tabla
dice qué se puede usar hoy, para que la referencia no prometa de más.

.. table::
   :widths: auto

   =========================================  =========  ==========================
   Parte                                      Estado     Dónde se verifica
   =========================================  =========  ==========================
   ``move`` y transferencia de propiedad      completo   semántica + ejecución
   Uso tras ``move`` / doble ``move``         completo   ``SEM004`` / ``SEM005``
   ``free`` explícito sobre punteros          completo   ``SEM014``
   Uso tras ``free`` / doble ``free``         completo   ``SEM023`` / ``SEM024``
   Punteros de solo lectura vs ``mutable``    completo   ``SEM015``
   Qué tipos tienen que destruirse            completo   sistema de tipos
   Drop automático al cerrar el ámbito        completo   semántica + ejecución
   Destruir por tipo (genéricos, bloques)     completo   semántica + ejecución
   Destruir las globales al terminar          parcial    intérprete (la VM no)
   Arenas como tipo de librería               pendiente  —
   Préstamos verificados al compilar          parcial    MIR (fase 6)
   Captura de solo lectura de una lambda      completo   ``SEM003``/``SEM015``/``SEM036``
   Recuento de referencias                    futuro     —
   =========================================  =========  ==========================

Propiedad y transferencia
--------------------------

Un valor pertenece a la variable que lo nombra. Un ``struct`` (y un ``enum``
con datos) es un **valor**:
ligarlo a otro nombre lo copia, y mutar la copia no toca el original — el
único tipo que refiere a otro sitio es ``ptr``. Pero copiar algo que tiene
**obligación de destrucción** no duplica el recurso: duplica al dueño, y su
destructor correría dos veces. Por eso llevarlo a otro sitio es **moverlo**, y
ligarlo sin ``move`` es ``SEM032``:

.. code-block:: srcx
   :class: fragmento

   Buffer ptr origen = crear_buffer(1024);
   Buffer ptr destino = move origen;

   // 'origen' ya no es utilizable: su valor vive ahora en 'destino'

Leer ``origen`` después del ``move`` es un error de compilación
(``SEM004``); volver a moverlo, también (``SEM005``). La verificación estática
es **intra-función y lineal**: recorre el cuerpo una vez y, en un ``if`` o un
``match``, une conservadoramente las ramas — movido en alguna rama significa
movido después. No hay falsos positivos: si el compilador acepta el programa,
el uso es correcto.

Volver a asignar un nombre lo **revive**: un valor nuevo no está movido.

.. code-block:: srcx
   :class: fragmento

   Buffer ptr b = crear_buffer(64);
   consumir(move b);
   b = crear_buffer(128);      // válido: 'b' vuelve a tener dueño
   usar(b);

Pasar un valor a una función
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Un parámetro **por valor** es el **dueño** de lo que recibe: si al terminar la
función no lo transfirió a otro sitio (``move``, ``return``), lo destruye. Por
eso pasar por valor algo con destructor exige ``move`` en la llamada —la misma
regla que un ``var``, y el mismo código, ``SEM032``—. Para solo leer o
modificar el valor sin quedárselo, el parámetro se declara ``ptr`` y se pasa
``&x``:

.. code-block:: srcx
   :class: fragmento

   fn consumir(Buffer b) -> void { ... }      // dueño: lo destruye al salir
   fn leer(Buffer ptr b) -> int { ... }       // préstamo: no destruye nada

   consumir(move buf);      // cede la propiedad
   consumir(buf);           // SEM032: dejaría dos dueños del mismo recurso
   leer(&buf);              // presta: 'buf' sigue siendo del llamador
   consumir(crear(64));     // un temporal no necesita 'move': nadie más lo tiene

Hay tres excepciones, porque ahí nadie puede escribir ``move``. En los tres
casos el parámetro recibe una copia prestada y **no** la destruye:

- los **hooks** que invoca el compilador (``cast<T>(x)`` → ``__cast__``,
  ``v[i] = x`` → ``__index_set__``);
- el **receptor** de un método (``x.metodo()``);
- un parámetro declarado con un **parámetro de tipo** (``T``) en una función
  genérica. Los drops se deciden por declaración, no por instancia: es un
  límite conocido.

Antes de la 0.4.1, pasar por nombre dejaba al llamador como dueño y
``consumir(move b)`` no dejaba a nadie: el recurso no se destruía nunca.

En ejecución, el intérprete hace cumplir lo mismo sobre las celdas: leer una
celda movida es ``RT001`` y volver a moverla ``RT002``. Los dos niveles
existen a propósito — el estático rechaza antes de ejecutar, el dinámico cubre
lo que el análisis lineal no alcanza a ver.

Destrucción
------------

Cuando el dueño de un valor sale de ámbito, el compilador invoca el destructor
de su tipo. **No hay sintaxis para esto**: el punto de destrucción es la llave
que cierra. Un tipo declara su destructor con el hook ``__free__``:

.. code-block:: srcx
   :class: fragmento

   struct {
       int ptr datos;
       int  largo;
   } Buffer;

   fn __free__(Buffer ptr b) -> void {
       free b.datos;
   }

El consumidor **nunca escribe** ``__free__``: lo llama el compilador, igual
que con el resto de los hooks. Ver :doc:`repo/hooks` para el vocabulario
completo.

.. code-block:: srcx
   :class: fragmento

   fn procesar() -> void {
       var Buffer a = crear(1024);
       var Buffer b = crear(2048);
       usar(a);
   }   // aquí muere 'b', y después 'a'

El orden es **inverso al de declaración**: lo último que nace es lo primero
que muere, para que un valor pueda depender de otro declarado antes.

Y el bloque se cierra igual por un ``return`` anticipado, un ``break``, un
``continue`` o un ``throw``: si la destrucción solo ocurriera al llegar al
final, cualquier salida temprana sería una fuga.

Las globales mueren al terminar el programa
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Una variable global es dueña de su valor igual que un local, y su "llave que
cierra" es el **final del programa**: cuando ``main`` vuelve (después de que
mueran sus locales), o al terminar un guion sin ``main``. Mueren en orden
**inverso al de declaración**, como las de un bloque, y las de las librerías
**después** que las del programa: las librerías se inicializaron primero, así
que un global del programa puede depender de uno suyo y no al revés.

.. code-block:: srcx
   :class: fragmento

   var arch.File registro = arch.open("salida.txt", "w");
   var Buffer cache = crear(64);

   fn main() -> int {
       registro.write("hola\n");
       return 0;
   }   // mueren los locales de main; después 'cache' y luego 'registro'
       // (que así llega a escribirse en el disco)

Una global movida (``return move g;``) ya no es de nadie y no se destruye. Si
el destructor de una global lee otra que ya murió, es un uso tras ``free``
(``RT003``), no un valor muerto leído en silencio. Un destructor que lanza es
``RT021``, como en cualquier otro sitio.

Las destruye toda terminación que no sea ``sistema.proceso.salir``: la
**normal** y la de un error que nadie atrapó, sea un ``throw``, una excepción
``EXCxxx`` o un error de ejecución (``RT``). Cualquiera de ellos ya
desenrolló la pila destruyendo los locales de cada marco, y las globales son
lo único que quedaba vivo (un ``File`` global se vuelca). El error se escribe
primero; si un destructor falla después, se dice además, y no se vuelve a
intentar. A diferencia de C++, un ``RT`` no es un ``std::abort``: el
intérprete sigue vigilando el estado, así que un destructor que choca con
algo roto da su propio error en vez de comportarse de forma indefinida.
``sistema.proceso.salir`` no las destruye (es ``std::_Exit``/``os._exit``).
Con ``--test``, cada prueba tiene sus propias globales: se inician antes de
ella y mueren al terminarla, con la misma regla.

Hoy esto lo hace el **intérprete**. El HIR no lleva la lista de lo que muere
al terminar (lo decide el intérprete mirando el valor: lo que no tiene ningún
``__free__`` dentro no tiene nada que correr), así que no se ve en
``--hir-pretty``; ``--trace-memory`` sí lo muestra (``drop global``). La VM
todavía no destruye las globales.

Lo que ya no es suyo no se destruye
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

El compilador decide **qué** puede necesitar destruirse —eso lo dice el tipo,
y es estático—, pero **si** hace falta se resuelve al ejecutar:

.. code-block:: srcx
   :class: fragmento

   fn f(bool c) -> void {
       var Buffer b = crear(64);
       if (c) { move b; }
   }   // se destruye 'b' solo si el 'if' no corrió

Las dos ramas comparten la misma lista de destrucciones. Lo que cambia es el
estado del valor, y ese estado ya existía: es el mismo que hace cumplir el
uso-tras-move. Por eso no hace falta ningún análisis de flujo en el
compilador ni ningún dato nuevo en ejecución.

Devolver un valor **transfiere su propiedad**, así que tampoco se destruye al
salir: pasa a morir cuando muera quien lo recibió. Y vale igual para un campo:
``return p.a;`` entrega ese campo y deja que el resto de ``p`` muera normal.

Devolver por valor entrega una copia
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Lo que una función devuelve **por valor** le llega al llamador como una
**copia**, igual que al ligarlo a una variable o pasarlo por parámetro: mutar
el resultado no toca aquello de donde salió.

.. code-block:: srcx
   :class: fragmento

   var Caja g = Caja{ n: 1 };
   fn dame() -> Caja { return g; }

   dame().sube();        // sube una copia: 'g.n' sigue en 1
   var Caja c = dame();  // 'c' es otra copia
   c.n = 5;              // 'g.n' sigue en 1

Devolver un **local** no copia nada: el local muere al salir, así que
devolverlo lo **mueve** (lo de arriba). Pero una **global** sigue viva y
sigue siendo dueña, así que devolverla por valor deja dos copias. Con un tipo
sin destructor no pasa nada; con uno que lo tiene serían dos dueños del mismo
recurso, y ``return g;`` (o ``throw g;``) es ``SEM032``, la misma regla que
``var R x = g;``. Para entregarla: ``return move g;`` (la global queda movida
y ya no se destruye al terminar el programa); para dejarla leer, la función
devuelve un puntero (``R ptr``) y ``return &g;``.

Antes de la 0.4.1 el resultado quedaba **enlazado** al original: ``dame().n =
5`` cambiaba ``g`` y ``v.get(0).push(8)`` el vector guardado dentro de ``v``.

Valores que nadie recibe
~~~~~~~~~~~~~~~~~~~~~~~~~

Un valor puede nacer sin que nadie se quede con él:

.. code-block:: srcx
   :class: fragmento

   procesar(Buffer{ largo: 64 });   // nadie lo nombra
   crear_buffer(128);               // el resultado se descarta

Esos **temporales** mueren al terminar la sentencia que los creó. Sin esa
regla serían una fuga silenciosa: no hay ninguna variable que los posea, así
que ningún cierre de ámbito los alcanzaría.

Lo que **no** es un temporal es un valor que sí encuentra dueño: el
inicializador de un ``var``, el lado derecho de una asignación, lo que
devuelve un ``return``, y —importante— **un literal dentro de otro literal**.
En ``Caja{ b: Buffer{...} }`` el ``Buffer`` pasa a ser el campo ``b``: su
dueño es la caja, y destruirlo al cerrar la sentencia lo mataría recién
nacido.

Un tipo que posee recursos **solo por sus campos** —un ``struct`` que
contiene un ``Buffer`` pero no declara su propio ``__free__``— se destruye
bajando a esos campos, uno por uno. La regla que decide es de quién es la
responsabilidad: si el tipo declara ``__free__``, **ese** destructor se hace
cargo de todo lo suyo y el compilador no toca sus campos; si no lo declara, el
compilador destruye los campos que poseen.

Destruir por tipo
~~~~~~~~~~~~~~~~~

Hay valores cuyo tipo el compilador no conoce en el punto donde decide qué
destruir: el ``T`` de un genérico (``fn toma<T>(T x)`` se escribe una vez y se
usa con ``int`` y con ``Buffer``), lo atrapado por un ``catch (e)`` sin tipo,
y los elementos de un bloque de ``mem``. Esos se destruyen **por su tipo
concreto**, con la misma regla de arriba aplicada donde el tipo se conoce (en
ejecución, o al monomorfizar): si declara ``__free__``, ese; si no, sus campos
que poseen, del último al primero.

Con eso, un **contenedor es dueño de sus elementos**:

- un bloque de ``mem`` posee sus celdas no vacías, y soltarlo
  (``mem.release``) las destruye. Para sacar un valor sin destruirlo están
  ``mem.take`` (una celda) y ``mem.transfer`` (un tramo): la celda queda
  vacía y el valor, con un solo dueño;
- un campo ``R ptr`` de un struct es su bloque y **posee si** ``R`` **posee**:
  ``Vector<Buffer>`` destruye sus buffers al morir y ``Vector<int>`` no tiene
  nada que destruir (y se sigue copiando sin ``move``);
- reasignar un dueño destruye el valor que tenía: ``v.set(0, move b)`` o
  ``a = Buffer{...}``.

Lo que **copiaría** un elemento —``v.get(0)``, ``v[0]``— no se puede con un
elemento que tiene destructor: la copia y el elemento serían dos dueños. El
error (``SEM038``) sale en la llamada y dice dónde copia el genérico. Para
leerlo sin copiarlo, ``v.at(0)`` lo **presta** (un puntero); para quedárselo,
``v.take(0)`` lo **saca**:

.. code-block:: srcx
   :class: fragmento

   var vec.Vector<Buffer> v = vec.dynamic<Buffer>(4);
   v.push(crear_buffer(64));          // el vector es el dueño
   usar(v.at(0));                     // prestado: sigue en el vector
   var Buffer b = v.take(0);          // sacado: ahora es de 'b'
   // al cerrar el ámbito: 'b' se destruye, y el vector con lo que tenga

Modificar un elemento en su sitio
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Como ``v.get(i)`` y ``v[i]`` entregan una **copia**, escribir en ellas no
cambiaría el vector: la copia muere al terminar la sentencia. Por eso hacerlo
es un error de compilación, ``SEM041``, y no un programa que corre sin hacer
nada. Para modificar el elemento guardado se pide **prestado y mutable**, de
forma explícita, con ``at_mut`` (``Dictionary`` tiene el mismo método, por
clave):

.. code-block:: srcx
   :class: fragmento

   v.at_mut(0).n = 5;          // un 'Caja ptr mutable' al elemento 0
   vv.at_mut(0).push(8);       // 'vv' es un Vector<Vector<int>>
   d.at_mut("clave").push(1);  // el valor guardado bajo "clave"
   v[0] = Caja{ n: 5 };        // reemplazar el elemento entero sí vale
   v[0].n = 5;                 // SEM041: cambiaría una copia
   vv[0].push(8);              // SEM041: igual, 'push' modifica su receptor

El préstamo es un puntero al **interior** del contenedor, y deja de valer en
cuanto el contenedor mueve sus elementos: un ``push`` que lo hace crecer, un
``put`` que redistribuye las casillas, sacar el elemento o destruir el
contenedor. Usarlo después es ``RT003``. Se pide justo antes de usarlo, no se
guarda.

Llamar a un método que modifica sobre el **resultado de una llamada**
(``abrir(...).write(...)``) sí se acepta: ese valor es nuevo, no la copia de
algo guardado, y el método puede tener otros efectos (escribir un archivo).
Lo que no se acepta es **asignar** a un campo de ese resultado (``f().n = 5``):
eso no puede tener ningún efecto.

Liberar antes de tiempo
~~~~~~~~~~~~~~~~~~~~~~~~

``free`` destruye un valor sin esperar al cierre del ámbito:

.. code-block:: srcx
   :class: fragmento

   fn procesar() -> void {
       Buffer ptr b = crear_buffer(1024);
       usar(b);
       free b;                 // se destruye aquí, no al final
       trabajo_largo();        // ...y la memoria ya está devuelta
   }

Es el escape para el caso en que el ámbito dura mucho más que el valor. A
partir del ``free``, ``b`` queda inutilizable exactamente igual que tras un
``move``, y el compilador no vuelve a destruirlo al cerrar el ámbito.

``free`` exige un puntero: aplicarlo a otra cosa es ``SEM014``.

Un valor solo se suelta una vez
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

``move`` y ``free`` son las dos formas que tiene el lenguaje de **terminar
una propiedad**: la primera la transfiere, la segunda la destruye. Las
verifica la misma pasada, con las mismas garantías —lineal, intra-función,
cero falsos positivos—, y lo que decide el diagnóstico es *por qué* murió el
valor, no la operación que lo encontró:

.. table::
   :widths: auto

   ==================  =========================  =========================
   Operación           sobre algo movido          sobre algo liberado
   ==================  =========================  =========================
   leerlo              ``SEM004``                 ``SEM023``
   ``move``            ``SEM005`` (doble move)    ``SEM023``
   ``free``            ``SEM004``                 ``SEM024`` (doble free)
   ==================  =========================  =========================

La distinción importa porque los dos errores se arreglan distinto: de un
``move`` el valor se recupera —vive en su nuevo dueño—, de un ``free`` no.
Por eso liberar algo ya movido se reporta como uso-tras-move y no como doble
free: el problema no es que lo liberes dos veces, es que **ya no es tuyo**.

Igual que con ``move``, un valor nuevo en el mismo nombre lo revive, y en un
``if`` la unión es conservadora: liberado en alguna rama significa liberado
después.

.. note::

   La verificación al compilar **nunca rechaza un programa válido**, y eso
   tiene un precio conocido: hay casos que deja pasar. El más claro es
   ``try``/``catch`` —soltar un valor dentro del ``try`` y usarlo en el
   ``catch`` no se reporta, porque el ``catch`` se analiza como un camino
   alternativo desde la entrada, no desde el punto donde saltó la excepción.
   Preferir el falso negativo al falso positivo es deliberado; lo que el
   análisis deja pasar lo caza el intérprete en ejecución (``RT001``,
   ``RT003``).

.. _tipos-con-dueno:

Qué tipos hay que destruir
---------------------------

No todo valor necesita destruirse: un ``int`` se descarta y ya está. El
compilador tiene que saber **cuáles sí**, y lo decide por el tipo, con tres
reglas:

Lo declara
   Un tipo nominal tiene una obligación de destrucción si declara
   ``__free__``. Vale igual para un tipo **opaco** de una librería
   (``const type T;``): sus campos no se ven desde fuera, pero su ``__free__``
   es su contrato de destrucción completo.

Lo contiene
   Un ``struct`` la tiene si algún campo **por valor** la tiene, aunque él no
   declare nada. Contener un dueño es ser dueño, y es transitivo.

Un ``ptr`` no
   Un puntero es un **préstamo**: apunta a algo cuyo dueño está en otra parte.
   Destruirlo al salir de ámbito destruiría el valor de otro.

.. code-block:: srcx
   :class: fragmento

   struct { int ptr datos; int largo; } Buffer;
   fn __free__(Buffer ptr b) -> void { free b.datos; }

   struct { Buffer b;     int n; } Caja;    // destruye: contiene un Buffer
   struct { Buffer ptr p; int n; } Vista;   // NO: solo lo tiene prestado

Esa tercera regla es también lo que hace que la pregunta **termine**. Los
tipos recursivos del lenguaje se cierran sobre sí mismos a través de punteros
—``struct { Nodo ptr sig; int v; } Nodo;``— y ahí la respuesta es "no" sin
seguir mirando.

``T?`` y ``error T`` son envoltorios: heredan la respuesta de lo que envuelven.
Al ejecutar, un ``R?`` que **vale** ``null`` no tiene nada que destruir: su
``__free__`` no se llama (ni al cerrar el ámbito, ni como temporal, ni con
``free``), y lo mismo vale para un campo ``R?``, el payload de una variante o
un elemento de un ``Vector<R?>`` que valen ``null``. El ``__free__`` siempre
recibe un ``R`` de verdad.

Un ``enum`` suma la tiene si el payload de alguna variante la tiene, y en un
enum **genérico** se mira el payload ya sustituido: ``Res<R, int>`` destruye
su ``Ok(R)``, ``Res<int, int>`` no tiene nada que destruir y se copia
libremente.

Un **valor función** (``fn(int) -> int``, ver
:ref:`funciones como valores <funciones-como-valores>`) nunca tiene que
destruirse: no captura nada, así que se copia libremente. Lo que sí cuenta es
lo que se le PASA al llamarlo: un argumento con destructor hacia un parámetro
por valor exige ``move`` (``SEM032``), igual que en una llamada directa.

.. _memoria-lambdas:

Lo que lee una lambda es un préstamo
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Una :ref:`lambda <lambdas>` lee los locales y los parámetros de quien la
escribe (sus **capturas**) sin copiarlos ni moverlos: los lee en su sitio,
vivos. Para la propiedad, una captura es un **préstamo de solo lectura**,
igual que lo que se lee a través de un ``ptr`` o lo que liga un patrón:

- no se modifica: asignarlo, llamar a un método que modifica su receptor,
  moverlo o liberarlo es ``SEM003``, y escribir a través de un puntero
  capturado es ``SEM015`` (un ``ptr mutable`` capturado se ve como ``ptr``);
- no se cede: ``return x`` o ``throw x`` con ``x`` capturado y con
  destructor es ``SEM036`` —serían dos dueños—, y ligarlo a un nombre nuevo
  (``var R r = x;``) es ``SEM032``;
- no se destruye al terminar la lambda: lo destruye su dueño, una vez, en la
  llave que cierra **su** ámbito.

**Por qué es seguro sin un análisis de vidas.** Un préstamo es peligroso
cuando puede vivir más que lo prestado. Una lambda no puede: solo existe como
argumento de una llamada (``SEM050``), y la función que la recibe solo puede
llamarla o pasarla a otro parámetro de tipo función (``SEM051``), nunca
guardarla ni devolverla. Así que la lambda muere **antes de que termine la
llamada** que la recibe, y esa llamada está dentro del ámbito de quien la
escribió: todo lo que captura sigue vivo mientras la lambda pueda correr. Es
la misma garantía que da un ``ptr`` a un local pasado a una función que no lo
guarda, pero aquí la comprueba el compilador con dos reglas locales, sin
seguir vidas entre funciones.

El riesgo que cierra ``SEM051`` es concreto: si una función pudiera guardar
su parámetro ``fn(...) -> R`` en un campo o en una global, una lambda que
llega por él sobreviviría a la llamada, y leería después los locales de un
marco que ya terminó (y que pudieron destruirse). Por eso el parámetro es
prestado, y quien necesite guardar una función que recibe la declara
``(fn(...) -> R)?``, que no admite lambdas.

Lo que la regla **no** cubre, como el resto de los préstamos (ver
`Punteros y préstamos`_): mientras la lambda corre, la función que la recibe
puede estar modificando lo mismo que ella lee —``v.sort_by(...)`` con una
lambda que lee ``v``—. Leer una celda que el ordenamiento sacó un momento es
un error de ejecución (``RT001``), no un valor equivocado.

Lo que la lambda **posee** es suyo, como en una función: un parámetro por
valor con destructor se lo cede quien la llama (con ``move``, ``SEM032``) y
muere al terminar **cada** llamada a la lambda, salvo que ella lo ceda; y sus
locales mueren en la llave que cierra su cuerpo.

Punteros y préstamos
---------------------

Un ``ptr T`` **no** es dueño: es un préstamo. Tomar la dirección de un valor
con ``&`` no transfiere nada, y la mutabilidad viaja en el tipo:

.. code-block:: srcx
   :class: fragmento

   int         n = 10;
   ptr int         solo_lectura = &n;     // no puede escribir
   ptr mutable int escritura    = &n;     // sí puede

Escribir a través de un puntero de solo lectura es ``SEM015``. ``&`` requiere
un *lvalue* —un nombre, un campo o un índice—, porque un temporal no tiene
dirección estable: aplicarlo a otra cosa es ``SEM013``.

Hoy la validez del préstamo se comprueba **en ejecución**: acceder a través de
un puntero cuyo destino ya se liberó es ``RT003``. La verificación estática de
tiempos de vida se hará sobre el MIR, cuando exista (fase 6 del
:doc:`repo/ROADMAP`). Hasta entonces el modelo es seguro pero conservador: sin
préstamos verificados al compilar, la forma garantizada de llevar un valor a
otro sitio es moverlo.

.. _prestamo-de-patron:

Lo que liga un patrón es prestado
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Un ``match`` no saca nada de su sujeto: lo que liga un patrón es **lo de
dentro, prestado**. Vale igual para el payload de ``case Nodo.A(x)`` y para el
contenido de ``case v`` sobre un ``T?``
(:ref:`desenvolver un opcional <desenvolver-opcional>`):

- no se copia: modificar un campo de ``v`` (``v.n = 1``) modifica el del
  sujeto, y solo se puede si el sujeto se puede modificar (``SEM003``);
- no se reasigna (``v = otra``, ``SEM003``);
- no se cede: ``move v`` o ``return v`` dejarían dos dueños, y es ``SEM036``
  —el mismo error que ceder algo a lo que se llega por un puntero—; ligarlo a
  un nombre nuevo con destructor (``var R r = v;``) es ``SEM032``;
- al cerrar la rama **no se destruye**: lo destruye el sujeto, una vez.

``x ?? d``, en cambio, es una lectura: entrega una **copia** del contenido de
``x`` (o ``d``). Por eso, si el contenido tiene destructor, es ``SEM032``: la
copia y el original serían dos dueños del mismo recurso. Un opcional con
destructor se desenvuelve con ``match``.

Arenas
-------

Una **arena** reserva un bloque grande de una vez y entrega memoria dentro de
él; al destruirse, lo devuelve entero sin recorrer lo que contiene. Es el
patrón que hace rápido a un compilador: miles de nodos que nacen juntos y
mueren juntos.

En suriaX una arena **no es una construcción del lenguaje**: es un tipo
nominal publicado por una librería, con las mismas reglas que cualquier otro
valor con dueño.

.. code-block:: srcx
   :class: fragmento

   #from mem #import arena

   fn compilar() -> void {
       arena.Arena a = arena.crear(64 * 1024);

       Nodo ptr raiz = arena.nodo(a, 1);
       Nodo ptr hijo = arena.nodo(a, 2);
       construir(raiz, hijo);

   }   // se destruye 'a': cae el bloque entero, de una vez

Que sea una librería y no sintaxis tiene una consecuencia importante: la arena
está sujeta a las reglas de propiedad como cualquier otro valor. Tiene un
dueño, se puede mover, y se destruye cuando ese dueño sale de ámbito. No hace
falta ningún análisis especial para saber cuándo muere — es la misma regla de
siempre.

Lo que no hay
--------------

Recolector de basura
   Nunca. La destrucción es determinista y está en el código.

Regiones
   Retiradas en 0.2.0. Ver :ref:`decision-memoria`.

Recuento de referencias
   Todavía no. Cuando llegue será *propiedad compartida* —un tipo de librería
   que reparte la propiedad entre varios dueños—, no un modelo alternativo:
   se apoya en ownership en lugar de competir con él.

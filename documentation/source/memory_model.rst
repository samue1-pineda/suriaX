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
   Arenas como tipo de librería               pendiente  —
   Préstamos verificados al compilar          parcial    MIR (fase 6)
   Recuento de referencias                    futuro     —
   =========================================  =========  ==========================

Propiedad y transferencia
--------------------------

Un valor pertenece a la variable que lo nombra. Un ``struct`` es un **valor**:
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

Antes de la 0.3.1, pasar por nombre dejaba al llamador como dueño y
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

7. Intérprete
==============

El intérprete ejecuta un ``.phir`` recorriendo su árbol (*tree-walk*). Es el
consumidor de referencia del HIR: cuando hay que decidir qué significa una
construcción, lo que hace el intérprete es la respuesta.

.. code-block:: console

   $ python V0/main.py programa.srcx --run

.. _imagen:

La imagen ejecutable
---------------------

Antes de ejecutar nada, el *loader* monta una **imagen**: el ``.phir``
principal más todas las unidades que referencia, cargadas una sola vez y
ligadas entre sí.

Sobre esa imagen se construyen los índices que el evaluador consulta en tiempo
constante:

.. table::
   :widths: auto

   ===================  ====================================================
   Índice               Clave
   ===================  ====================================================
   Funciones            nombre
   Hooks                (tipo dueño, clase de hook)
   Conversiones         (tipo origen, tipo destino)
   Métodos dunder       (tipo dueño, nombre)
   Items de enum        (enum, item)
   ===================  ====================================================

Si una unidad referenciada no está junto al archivo principal, el loader se
detiene diciendo cuál falta y de dónde venía la referencia.

.. _ejecucion:

Ejecución
----------

El punto de entrada es ``main``. Las sentencias de nivel de módulo se ejecutan
**antes**, en orden de aparición, de modo que un programa sin ``main`` que solo
tiene código suelto también hace algo.

.. code-block:: srcx

   #from io #import stdp

   stdp.println("esto se ejecuta primero");

   fn main() -> int {
       stdp.println("y esto después");
       return 0;
   }

El valor que devuelve ``main`` es el código de salida del proceso.

Cuando ``main`` vuelve (o se acaba un programa sin ``main``), mueren las
variables **globales**: en orden inverso al de declaración, primero las del
programa y después las de las librerías (ver :ref:`modelo-memoria`). También
mueren si el programa termina con un ``throw`` o una excepción ``EXCxxx`` que
nadie atrapó (una terminación controlada: ya destruyó los locales al subir).
Un ``RT`` (el programa está roto) o ``sistema.proceso.salir`` terminan sin
destruirlas. Si un destructor falla aquí, el código de salida es 70.

Un error de ejecución dice su posición como ``(línea:columna)``; si ocurrió
dentro de una **librería**, con su archivo delante, como un error de
compilación dentro de ella: ``RT020: throw 7 (lib/falla.libsrx:2:5)`` o
``(<stdlib>/array/vector.libsrx:167:13)``. La ruta es la pública de la unidad
(relativa a la raíz del proyecto, o ``<stdlib>/...``), la misma que viaja en
el ``.phir``.

Una **excepción** (un ``throw`` o una ``EXCxxx``) que nace dentro de la
**stdlib** es distinta: lleva la posición de la LLAMADA del programa que
entró en la stdlib, no una línea de dentro de ella. Es lo que promete
``excepciones`` ("la posición de la operación que falló"), y para quien
escribió ``arch.leer(ruta)`` o ``v.get(9)`` la operación es esa llamada.
Vale para ``e.linea``/``e.columna`` al atraparla y para el mensaje si nadie
la atrapa:

.. code-block:: text

   excepción no capturada — EXC002: índice 9 fuera de rango [0, 1) (9:17)

El ``IndiceFueraDeRango`` que lanza ``Vector`` sale así, con su código
``EXC002``, igual que el del acceso a un bloque: es el mismo tipo. Lo que
falla en código del usuario llamado DESDE la stdlib (la lambda de un
``filter``) conserva su propia posición, y una librería del proyecto sigue
nombrando su archivo. Un ``RT`` dentro de la stdlib también: es un fallo de
la librería, no del llamador. (La VM todavía da la posición de dentro de la
librería, o ``0:0`` en ``Vector``.)

.. _valores-runtime:

Cómo se representa un valor
----------------------------

Un ``int``, ``float``, ``bool`` o ``str`` es el nativo de Python (un ``char``
es un ``str`` de un carácter). Un struct es un objeto con sus campos en
celdas; una variante de un enum **suma** (uno con alguna variante con datos)
también, con su payload en celdas. La variante **sin** datos de un enum suma
(``Forma.Punto``) es un valor del enum como sus hermanas, sin campos: por eso
``==``, ``hash`` y ``<`` llaman a los ``__eq__``/``__hash__``/``__cmp__`` del
enum también con ella, y ``Vector.at`` la presta. Un ``match`` la reconoce
por su variante, no por ``__eq__``.

Un item de un enum **estilo C** (sin datos) sigue siendo un entero —se
compara, se ordena y se hashea como uno, igual que en la VM— pero sabe de
qué enum es y cómo se llama. Con eso un f-string dentro de un genérico
(``f"{x}"`` con ``x: T``) escribe lo mismo que con el tipo concreto: el
cuerpo de un genérico es uno solo, ``T`` no nombra ningún tipo, y el texto lo
decide el **valor** (``P{x: 3, s: "hi"}``, ``Punto``, ``VERDE``,
``Ok(ROJO)``). Lo único que el valor no distingue es un ``str`` de un
``char``: ``{x!r}`` de un ``T`` primitivo sale sin comillas.

.. _memoria-runtime:

Modelo de memoria
------------------

Los punteros no son una simulación con diccionarios: hay un administrador de
memoria con celdas reales, escrito en C++, y el intérprete lo usa a través de
*bindings*.

Cada celda tiene una **máquina de estados**:

.. code-block:: text

   crear ──▶ LIVE ──move──▶ MOVED
              │
              └──free──▶ FREED

Leer una celda movida es ``RT001``; volver a moverla, ``RT002``; acceder a una
liberada, ``RT003``. Los tres traen la línea y la columna de la operación que
los provocó, porque el HIR las transporta.

El mismo core lo enlazará el backend nativo (hoy la VM de registros usa su propio modelo de memoria, en ``backend/src/vm.cpp``): la lógica de
memoria vive en un solo sitio y es agnóstica del target.

.. table::
   :widths: auto

   =========================  ===============================================
   Variable de entorno        Efecto
   =========================  ===============================================
   ``SURIAX_NATIVE_MEM=1``    Exige el backend nativo; error si no carga.
   ``SURIAX_NATIVE_MEM=0``    Fuerza la implementación en Python puro.
   =========================  ===============================================

Sin la variable, se usa el nativo si está compilado y se cae al de Python si
no. Las dos implementaciones tienen la misma interfaz y la suite comprueba que
den resultados idénticos.

.. _despacho:

Despacho de hooks
------------------

Cuando el evaluador encuentra una llamada con un hook enlazado, no busca nada:
la referencia ``(dueño, clase)`` que trae el nodo se resuelve contra el índice
de la imagen y ejecuta el cuerpo, con los globales de **su** unidad.

.. code-block:: srcx

   #from io #import stdp

   struct { str texto; int largo; } Cadena;

   hook fn __print__(Cadena ptr c) -> void {
       stdp.print(c.texto);
   }

   hook fn __len__(Cadena ptr c) -> int {
       return c.largo;
   }

   fn main() -> int {
       var Cadena c = Cadena{ texto: "hola", largo: 4 };
       print(&c);        // despacha a __print__
       return len(&c);   // despacha a __len__
   }

.. _trazas:

Trazas
-------

.. code-block:: console

   $ python V0/main.py programa.srcx --run --trace-exec
   $ python V0/main.py programa.srcx --run --trace-memory

``--trace-exec`` muestra llamadas y retornos anidados; ``--trace-memory``
muestra cada operación sobre celdas (``&``, ``move``, ``free``) con su
posición. Con ``--debug``, ambas trazas se acumulan en el reporte en vez de
imprimirse.

.. _bloques-test:

Bloques ``test``
-----------------

Un bloque ``test`` es una declaración de primer nivel, no una función: no se
invoca ni tiene firma.

.. code-block:: srcx

   fn doble(int x) -> int { return x + x; }

   test "doble multiplica por dos" {
       var int r = doble(21);
       expect (r == 42);
   }

Viajan en el HIR y el intérprete los reconoce como unidades ejecutables
separadas del programa: una compilación normal los transporta y los valida,
pero no los ejecuta junto a ``main``. Se corren con ``--test``:

.. code-block:: console

   $ python V0/main.py programa.srcx --test
     PASS  doble multiplica por dos

   tests: 1 pasaron, 0 fallaron

El código de salida es 1 si alguna prueba falla. Las pruebas corren en el
intérprete (la VM todavía no las corre). Cada prueba corre **aislada**: con
sus globales recién iniciadas (las del programa y las de sus librerías: se
vuelve a correr el nivel de módulo) y destruidas al terminarla, así que el
resultado no depende del orden. Si iniciarlas o destruirlas falla, la prueba
falla y lo dice. Se destruyen también si la prueba termina con un ``RT``
(la misma regla que al ejecutar). Las líneas ``PASS`` y ``FAIL`` salen por
la **salida estándar**, en el orden en que corren las pruebas.

``expect``: la comprobación
~~~~~~~~~~~~~~~~~~~~~~~~~~~

``expect (condición);`` comprueba algo dentro de una prueba. Si la condición
se cumple, la prueba sigue; si no, **termina ahí** como fallida, y el reporte
cita la condición como se escribió y, si es una comparación, los dos lados:

.. code-block:: console

     FAIL  total  (expect falló: total == 10  (izquierda: 7, derecha: 10)  [3:5])

- La condición es ``bool``, como la de un ``if``.
- Puede llevar un bloque, que corre solo si se cumplió:
  ``expect (r == 42) { ... }``. Lo normal es no necesitarlo: el camino de
  éxito es la sentencia siguiente.
- Solo vale dentro del cuerpo de un ``test`` (``PAR013`` fuera).
- Una prueba tiene al menos un ``expect`` (``PAR029``): sin ninguno pasaría
  siempre, sin haber comprobado nada.
- Un ``expect`` que falla **no es una excepción**: ningún ``catch`` lo atrapa.
  Una prueba no puede rescatarse de su propia comprobación. Los ``finally``
  de los ``try`` que atraviesa sí corren, y los valores con destructor que
  estaban vivos se destruyen.

Una prueba también falla si un ``throw`` sale de ella sin que nadie lo
atrape, o si ocurre un error de ejecución.

``errfinally`` y ``finally``
~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Después del cuerpo, una prueba puede llevar dos cláusulas, las dos
opcionales y en este orden:

.. code-block:: srcx
   :class: fragmento

   test "guarda el archivo" {
       expect (guardar("datos.txt"));
   } errfinally {
       stdp.println("fallo: revisar permisos");   // solo si la prueba falló
   } finally {
       borrar("datos.txt");                        // siempre
   }

- ``errfinally`` corre **solo si la prueba falló**. Existe solo aquí: en un
  ``try`` lo mismo ya lo dice un ``catch`` que relanza, pero un ``expect``
  fallido no pasa por ningún ``catch``.
- ``finally`` corre **siempre**, y después del ``errfinally``.
- Cada cláusula es un bloque con su propio ámbito: no ve los locales del
  cuerpo, que ya murieron.
- De una cláusula no se sale con ``return``/``break`` (``PAR027``), y dentro
  no vale ``expect``.

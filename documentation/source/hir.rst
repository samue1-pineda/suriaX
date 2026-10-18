6. HIR: el puente entre fases
==============================

El **HIR** (*high-level intermediate representation*) es la frontera del
compilador: todo lo que el frontend sabe de un programa se serializa una vez,
y de ahí en adelante cada backend lee lo mismo. Un archivo ``.phir`` es esa
serialización.

.. code-block:: text

   .srcx  →  frontend (Python)  →  .phir  →  intérprete
                                          →  backend C++   (MIR → VM / JIT)
                                          →  target web    (WIR → WebAssembly)

Está escrito en **protobuf**, que aporta tres cosas concretas: un formato
binario compacto, un esquema versionado y lectores en cualquier lenguaje sin
reimplementar el frontend.

.. _que-viaja:

Qué contiene un ``.phir``
--------------------------

.. table::
   :widths: auto

   ====================  =====================================================
   Campo                 Contenido
   ====================  =====================================================
   ``schema_version``    Versión del **esquema**, no del compilador.
   ``source_file``       Ruta del fuente, para los diagnósticos.
   ``symbols``           Tabla de símbolos global: tipos, valores, hooks y
                         conversiones.
   ``items``             El programa validado, en orden.
   ``libraries``         Las unidades importadas, por alias y archivo.
   ``types``             **Pool de tipos**: cada tipo distinto una sola vez;
                         los nodos lo referencian por índice. Solo en el
                         esquema 2 (ver :ref:`rollback-esquema-1`).
   ====================  =====================================================

Cada expresión viaja con **su tipo ya resuelto** y cada nodo con **su línea y
columna**. Un backend nunca tiene que inferir un tipo ni adivinar una
posición: si el HIR no lo trae, no existe.

.. _pool-de-tipos:

El pool de tipos (esquema 2)
-----------------------------

Que cada expresión lleve su tipo no significa que cada expresión lleve una
*copia* de él. En un programa de 47 000 tokens el mismo ``int`` aparecía
21 065 veces sobre **43 formas distintas** — un 20 % del archivo dedicado a
repetir cuarenta y tres cosas.

Desde el esquema 2 los tipos viven una sola vez en ``Module.types`` y los
nodos guardan un índice (``type_id``); el ``0`` significa "sin tipo anotado".
Resolverlo es un acceso a lista, así que el lector no paga nada: se midió, y
el tiempo de lectura no cambió. Lo que sí cambió es el archivo (un 10 % más
pequeño) y el tiempo de emisión (un 16 % menos, porque el emisor construye
veinte mil submensajes menos).

La tabla de símbolos **no** participa del pool a propósito: es el 4 % de los
bytes y la parte que una persona lee cuando inspecciona un ``.phir``.

El pool no se ve al leer el HIR: ``--hir-pretty`` lo resuelve y escribe
``Punto ptr mutable``, no ``#7``.

.. _reproducible:

El mismo programa, los mismos bytes
------------------------------------

Un ``.phir`` es **reproducible**: compilar dos veces el mismo fuente produce
artefactos idénticos, en cualquier máquina. No siempre fue así — las entradas
de un ``map`` de protobuf se escriben en un orden que la especificación no
fija, y el orden real lo decidía la tabla *hash* del proceso.

Importa más de lo que parece: sin esa garantía no se pueden comparar
artefactos, ni cachear un build por su *hash*, ni demostrar que un cambio del
compilador no alteró la salida.

.. _una-unidad-un-phir:

Una unidad, un archivo
-----------------------

Cada ``.srcx`` y cada ``.libsrx`` compila a **su propio** ``.phir``. El módulo
principal no reembebe el contenido de sus librerías: las **referencia** por
alias y archivo.

.. code-block:: console

   $ python V0/main.py programa.srcx --emit-hir
   HIR (1255 bytes) generado en: dumps/programa.srcx.phir
     unidad 'IO.stdpf': 349 bytes -> dumps/IO.stdpf.phir
     unidad 'IO.stdp': 956 bytes -> dumps/IO.stdp.phir
     unidad 'IO': 145 bytes -> dumps/IO.phir

El consumidor resuelve cada referencia **relativa al archivo que la
referencia** y liga las unidades. La consecuencia práctica: los ``.phir``
viajan juntos, como los objetos de un enlazado.

.. _versionado:

Versionado y fail-fast
-----------------------

``schema_version`` se compara **antes de tocar el contenido**. Un lector que
encuentra una versión que no conoce se detiene con un mensaje accionable, en
vez de interpretar bytes con un layout desconocido y fallar más tarde en otro
sitio.

Es la misma disciplina en los tres lectores: el intérprete, el target web y el
backend C++ comparten el criterio, no solo el formato. Hoy los tres aceptan
las versiones **1 y 2**; cualquier otra (``0``, ``3``…) se rechaza.

.. _rollback-esquema-1:

El esquema 1 sigue funcionando (rollback)
------------------------------------------

Versionar el esquema no es solo poder rechazar lo que no se conoce: es poder
seguir leyendo lo que **sí** se conoce. Entre el esquema 1 y el 2 cambió una
sola cosa, el :ref:`pool de tipos <pool-de-tipos>`. En el 1 cada nodo llevaba
su tipo **inline** (``Expr.restype``, ``VarDecl.type``…); en el 2 lleva un
índice al pool.

El emisor de hoy puede escribir cualquiera de los dos:

.. code-block:: console

   $ python V0/main.py programa.srcx --emit-hir                  # esquema 2
   $ python V0/main.py programa.srcx --emit-hir --hir-schema 1   # esquema 1

Con ``--hir-schema 1`` el ``.phir`` (y el de cada librería) lleva
``schema_version: 1``, **no** lleva ``Module.types`` y cada tipo va en su
nodo. El emisor construye siempre el 2 y despliega el pool en un paso aparte:
no hay dos emisores que puedan divergir.

Al leer, los tres lectores **normalizan** un esquema 1 a la forma de hoy:
construyen el pool desde los tipos inline y rellenan los índices. Desde ahí
el camino es el mismo que con el 2 — el intérprete, el MIR y la VM, el WIR y
el WebAssembly no saben qué esquema llegó. Un archivo que mezcla los dos (un
1 con pool o con índices) está mal formado y se rechaza.

Cómo se hizo sin romper nada:

- los campos inline del esquema 1 volvieron **con su número de campo y su
  significado originales** (al pasar al 2 habían quedado *reservados*, así
  que ningún lector los leyó nunca como otra cosa): ``Expr.restype = 3``,
  ``VarDecl.type = 2``, ``Parameter.type = 1``,
  ``FunctionDecl.return_type = 3`` y ``Field.type = 1``;
- los campos de tipo que nacieron **después** del esquema 1 tienen un gemelo
  inline con un número **nuevo**: ``LambdaExpr.return_type = 5`` y
  ``EnumItem.payload_types = 4``. Por eso lo que se emite es el esquema 1
  *adaptado a hoy*: expresa todo el lenguaje actual sin pool. El esquema 1
  tal como era se conserva en ``dev/diff/schema/hir_v1_original.proto``.

Qué se comprobó (``test/unit/test_hir_schema_v1.py``,
``test/e2e/test_hir_schema_v1.py``, ``test/web/schema_v1.test.ts``,
``test/backend/test_backend_cpp_schema_v1.py``): el mismo programa da la
misma ejecución en los dos esquemas en el intérprete y en la VM y el mismo
WebAssembly en el target web; normalizar el ``.phir`` v1 da, byte a byte, el
v2 (salvo ``schema_version``); y un ``.phir`` v2 sale idéntico al de antes de
existir la bandera.

Y por qué el 2 sigue siendo el de por defecto: el mismo programa ocupa más en
el 1. El compilador V1 (``src/main.srcx``, 33 unidades) son 969 336 bytes en
el esquema 2 y 1 280 188 en el 1 (un 32 % más).

.. _hooks-hir:

Cómo viajan los hooks
----------------------

Un hook está en dos sitios a la vez, y a propósito:

En la tabla
   ``symbols.hooks`` guarda la entrada completa: tipo dueño, clase de hook y
   el símbolo con su firma.

En el nodo
   El nodo que lo dispara (una llamada, un ``free``, un ``sizeof``) lleva una
   **referencia** ``(dueño, clase)``, no una copia del símbolo.

Así el símbolo no se duplica en cada uso y el lector reconstruye el índice en
una pasada. Las conversiones ``__cast__`` viajan igual: en una lista, con el
par origen-destino derivable de cada firma.

.. _alcance-hir:

Alcance de la versión 1
------------------------

El HIR transporta el lenguaje completo. El modelo de regiones —lo único que
nunca viajó— se retiró del lenguaje en la v0.2.0 (ver :ref:`decision-memoria`);
los identificadores de sus campos quedan **reservados** en el esquema, así que
nada de lo que un lector existente conoce cambió de significado.

Un nodo del AST sin correspondencia en el esquema se rechaza con ``HIR005`` y
su posición, en vez de degradarse en silencio: es el fail-fast que garantiza
que todo lo que la Semántica acepta, o viaja al HIR, o dice por qué no.

Move-semantics **sí** viaja: la sentencia ``move`` y la línea del movimiento
anotada en el símbolo, para que el runtime haga cumplir lo que el análisis
estático conservador no ve.

.. _ver-el-hir:

Ver el HIR
-----------

Dos vistas, para dos preguntas distintas. Para leer el **programa**:

.. code-block:: console

   $ python V0/main.py programa.srcx --hir-pretty
   $ cat dumps/programa.srcx.phir.pretty

Para depurar el **formato** (qué tag lleva qué), el árbol crudo del protobuf:

.. code-block:: console

   $ python V0/main.py programa.srcx --emit-hir --hir-text
   $ cat dumps/programa.srcx.phir.txt

Y sobre un ``.phir`` que ya existe, sin recompilar:

.. code-block:: console

   $ python runtime/interpreter/main.py dumps/programa.srcx.phir --pretty

O directamente por pantalla, sin escribir archivos:

.. code-block:: console

   $ python V0/main.py programa.srcx --emit-stage hir

Un fragmento del resultado:

.. code-block:: text

   schema_version: 2
   source_file: "programa.srcx"
   types { }                     # 0 = "sin tipo"
   types { kind: INT }           # 1
   items {
     ln: 3
     col: 1
     function {
       name: "suma"
       params { name: "a" type_id: 1 }
       params { name: "b" type_id: 1 }
       return_type_id: 1
       body {
         statements {
           ln: 4
           return_stmt {
             value {
               type_id: 1
               binary { op: "+" ... }
             }
           }
         }
       }
     }
   }

Ese es el *formato*. Para leer el **programa** —una línea por sentencia, con
los tipos ya resueltos a su nombre— está ``--hir-pretty``:

.. code-block:: text

   unit programa.srcx   schema 2 · 1 items · 1 símbolos · 1 tipos

   types
     #1   int

   fn suma(int a, int b) -> int                                    @3:1
     return (a:int + b:int):int                                    @4:5

.. _el-phir-como-entrada:

El ``.phir`` como entrada
--------------------------

Un ``.phir`` es autosuficiente: no necesita el fuente para ejecutarse ni para
compilarse a otro target.

.. code-block:: console

   $ node web/main.ts dumps/programa.srcx.phir --run

Esa propiedad es la que permite que el playground compile en el servidor y
ejecute en el navegador, y la que hace comparables al intérprete y al
WebAssembly: mismo archivo, distintos ejecutores, misma salida.

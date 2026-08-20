.. _libsrx:

9. Librerías nativas (``.libsrx``)
===================================

suriaX reserva pocas palabras y delega el resto en librerías. No hay
``print`` en el lenguaje: hay una librería que lo publica. Esa es la filosofía
**libsrX**, y estas son sus reglas.

Una librería es un archivo ``.libsrx`` que declara cosas y se cierra
publicándose con un nombre:

.. code-block:: srcx

   // matematica.libsrx

   public fn cuadrado(int x) -> int {
       return x * x;
   }

   private fn ayuda(int x) -> int {
       return x + 1;
   }

   #export as mate

El ``#export`` final es obligatorio: es lo que convierte un archivo en una
unidad importable, y su alias es el nombre con el que se importa.

.. _importar:

Importar
---------

.. code-block:: srcx
   :class: fragmento

   #import mate                 // el módulo entero, bajo su alias
   #import mate as m            // con otro nombre local
   #from mate #import cuadrado  // un miembro concreto

   fn main() -> int {
       return mate.cuadrado(4);
   }

El nombre puede ser punteado para llegar a un submódulo: ``#import io.stdp``.

.. _paquetes:

Paquetes
---------

Una carpeta con varios ``.libsrx`` es un paquete. El archivo ``main.libsrx``
es su **padre** y lo cierra con la forma ``package``:

.. code-block:: text

   lib/io/
   ├── main.libsrx      #export package as IO
   ├── stdp.libsrx      #export as stdp
   └── stdpf.libsrx     #export as stdpf

Los submódulos se descubren solos: no hace falta importarlos en el padre.
Desde fuera se llega a ellos calificando:

.. code-block:: srcx
   :class: fragmento

   #import IO             // IO.stdp.println("...")
   #import IO.stdp        // stdp.println("...")
   #from IO #import stdp  // stdp.println("...")

Cada submódulo es una **unidad propia**: compila a su propio ``.phir`` y se
carga una sola vez aunque varias librerías lo importen.

.. _visibilidad-libsrx:

Visibilidad
------------

.. table::
   :widths: auto

   ==============  ===========================================================
   Modificador     Alcance
   ==============  ===========================================================
   ``public``      Visible para quien importe la librería. Es el valor por
                   defecto: sin modificador, una declaración es pública.
   ``private``     Visible dentro del mismo paquete.
   ``internal``    Visible solo dentro del mismo archivo.
   ==============  ===========================================================

Es lo que permite que una librería tenga cocina: un ``__write__`` interno que
nadie de fuera puede llamar, y una API pública que sí.

.. code-block:: srcx

   internal fn __write__(str s) -> void;   // primitiva del host, sin cuerpo

   public fn print(str s) -> void {
       __write__(s);
   }

   public fn println(str s) -> void {
       __write__(s);
       __write__("\n");
   }

   #export as stdp

.. _prototipos:

Prototipos
-----------

Una función declarada con ``;`` en vez de cuerpo es un **prototipo**: su firma
existe para el compilador, y la implementación la aporta el backend o el host.
Es como una librería declara lo que no puede escribir en suriaX.

.. code-block:: srcx

   internal fn __write__(str s) -> void;

.. _tipos-de-libreria:

Tipos publicados por una librería
----------------------------------

Una librería puede publicar structs, enums y tipos nominales opacos. Se usan
igual que los nativos, calificados por el alias del módulo:

.. code-block:: srcx

   // d_types/dt_variables.libsrx
   public const type int8;
   public const type float16;
   #export as dt_variables

.. code-block:: srcx

   #from d_types #import dt_variables as dt

   fn main() -> int {
       const dt.int8 pequeno = cast<dt.int8>(300);   // 44
       return sizeof(dt.int8);                        // 1
   }

.. _ancho-fijo:

Un tipo de librería con ancho real
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

``int8`` no es un primitivo con otro nombre: es un tipo nominal que publica
``d_types``, y su **ancho** lo aplica de verdad la conversión. El ancho no se
puede escribir en suriaX —haría falta aritmética de bits sobre un entero que
ya es de 64—, así que la librería declara el ``__cast__`` como
:ref:`prototipo <prototipos>` y el cuerpo lo pone el host, igual que
``__write__``:

.. code-block:: srcx
   :class: fragmento

   hook fn __cast__(int n) -> int8;      // el ancho lo aplica el host
   hook fn __cast__(int8 v) -> int;      // y la vuelta al primitivo

Los enteros **truncan como C** (complemento a dos) y los flotantes
**redondean** al formato IEEE-754 de su ancho:

.. table::
   :widths: auto

   =========================  ============  =========================
   Conversión                 Resultado     Regla
   =========================  ============  =========================
   ``cast<dt.int8>(300)``     ``44``        trunca a 8 bits con signo
   ``cast<dt.int8>(128)``     ``-128``      complemento a dos
   ``cast<dt.int16>(70000)``  ``4464``      trunca a 16 bits
   ``cast<dt.float16>(pi)``   ``3.140625``  redondeo binary16
   =========================  ============  =========================

El ancho que aplica el host y el ``sizeof`` que declara la librería son la
misma cifra, y la suite lo comprueba: si divergieran, el tipo estaría
mintiendo sobre su tamaño.

Y también hooks, con lo que un tipo de librería se comporta como uno nativo:

.. code-block:: srcx

   #from io #import stdp

   public struct { str texto; int largo; } Cadena;

   public hook fn __print__(Cadena ptr c) -> void { stdp.print(c.texto); }
   public hook fn __len__(Cadena ptr c) -> int { return c.largo; }

Desde fuera, ``print(x)`` y ``len(x)`` funcionan sin que nadie escriba el
nombre del hook.

Los nueve hooks del vocabulario, los métodos propios (*dunders*) y los
contratos (*traits*) tienen su capítulo con el glosario completo:
:doc:`repo/hooks`.

.. _rutas:

Dónde se buscan
----------------

El linker busca, en este orden:

1. junto al archivo que hace el ``#import``;
2. en ``<directorio del archivo>/lib``;
3. en las rutas de ``libraries.libsrx_paths`` del
   :ref:`archivo de configuración <configuracion>`.

Los resultados se cachean por ruta, de modo que un paquete importado desde
diez sitios se resuelve una vez.

.. _libreria-io:

La librería de entrada/salida
------------------------------

El paquete ``io`` es el que trae la impresión:

.. table::
   :widths: auto

   ================  ===========================================================
   Unidad            API
   ================  ===========================================================
   ``IO.stdp``       ``print(str)``, ``println(str)`` y los hooks de ``Cadena``.
   ``IO.stdpf``      ``printf(str)``: escribe sin salto de línea, pensado para
                     f-strings ya interpolados.
   ================  ===========================================================

.. code-block:: srcx

   #from io #import stdp
   #from io #import stdpf

   fn main() -> int {
       var int n = 21;
       stdp.println("empezando");
       stdpf.printf(f"n vale {n}\n");
       return 0;
   }

La interpolación la aportan los f-strings (``f"..."``), no la función: para el
lenguaje, ``printf`` recibe una cadena ya formada.

.. _emitir-libreria:

Compilar una librería
----------------------

No hay comando aparte: al compilar un programa que la importa, cada unidad
emite su propio ``.phir`` junto al del programa.

.. code-block:: console

   $ python V0/main.py programa.srcx --emit-hir
   HIR (1255 bytes) generado en: dumps/programa.srcx.phir
     unidad 'IO.stdpf': 349 bytes -> dumps/IO.stdpf.phir
     unidad 'IO.stdp': 956 bytes -> dumps/IO.stdp.phir
     unidad 'IO': 145 bytes -> dumps/IO.phir

Los archivos viajan juntos: el consumidor resuelve cada referencia relativa al
``.phir`` que la contiene.

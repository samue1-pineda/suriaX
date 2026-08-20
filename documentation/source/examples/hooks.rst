Hooks y errores
===============

Cómo un tipo propio se comporta como uno nativo, y cómo viaja un fallo.

.. _ej-hooks:

Un tipo con hooks
-----------------

.. code-block:: srcx

   #from io #import stdp

   struct {
       str texto;
       int largo;
   } Cadena;

   hook fn __print__(Cadena ptr c) -> void {
       stdp.print(c.texto);
   }

   hook fn __len__(Cadena ptr c) -> int {
       return c.largo;
   }

   fn main() -> int {
       var Cadena c = Cadena{ texto: "hola", largo: 4 };
       print(&c);          // despacha a __print__
       return len(&c);     // despacha a __len__
   }

Quien usa el tipo escribe ``print(x)`` y ``len(x)``; el nombre del hook no
aparece nunca en el código del consumidor.

.. _ej-errores:

Errores
-------

.. code-block:: srcx

   #from io #import stdp

   fn dividir(int a, int b) -> error int {
       if (b == 0) {
           throw "division por cero";
       }
       return a / b;
   }

   fn main() -> int {
       try {
           var int r = dividir(10, 0);
           stdp.println("no llega aqui");
       } catch (e) {
           stdp.println("error capturado");
       }
       return 0;
   }

En la ruta de éxito, un ``error int`` se usa como un ``int``: el fallo viaja
por ``throw``, no dentro del valor.

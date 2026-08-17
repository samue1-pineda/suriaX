Librerías y pruebas
===================

Publicar código para que otro programa lo use, y comprobar que sigue
funcionando.

.. _ej-libreria:

Una librería propia
====================

.. code-block:: srcx

   // lib/geometria/main.libsrx
   #export package as geo

.. code-block:: srcx

   // lib/geometria/formas.libsrx
   public struct { int ancho; int alto; } Rect;

   public fn area(Rect ptr r) -> int {
       return escalar(r.ancho) * r.alto;
   }

   private fn escalar(int v) -> int {
       return v;
   }

   #export as formas

.. code-block:: srcx

   // programa.srcx
   #from geo #import formas

   fn main() -> int {
       var formas.Rect r = formas.Rect{ ancho: 3, alto: 7 };
       return formas.area(&r);
   }

``escalar`` es ``private``: existe para la librería, y llamarla desde fuera es
``SEM019``.

.. _ej-test:

Bloques ``test``
=================

.. code-block:: srcx

   fn doble(int x) -> int {
       return x + x;
   }

   test "doble multiplica por dos" {
       var int r = doble(21);
   }

   fn main() -> int {
       return doble(21);
   }

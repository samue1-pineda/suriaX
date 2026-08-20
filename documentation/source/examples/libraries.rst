Librerías y pruebas
===================

Publicar código para que otro programa lo use, y comprobar que sigue
funcionando.

.. _ej-libreria:

Una librería propia
-------------------

.. code-block:: srcx

   // lib/geo/main.libsrx
   #export package as geo

.. code-block:: srcx

   // lib/geo/formas.libsrx
   public struct { int ancho; int alto; } Rect;

   public fn area(Rect ptr r) -> int {
       return escalar(r.ancho) * r.alto;
   }

   private fn escalar(int v) -> int {
       return v;
   }

   #export as formas

.. code-block:: srcx
   :class: fragmento

   // programa.srcx
   #from geo #import formas

   fn main() -> int {
       var formas.Rect r = formas.Rect{ ancho: 3, alto: 7 };
       return formas.area(&r);
   }

``escalar`` es ``private``: existe para la librería, y llamarla desde fuera es
``SEM019``.

.. important::
   La carpeta de un paquete tiene que llamarse **como su alias** (salvo por
   mayúsculas): el linker la busca por nombre y después comprueba que el
   ``#export`` coincida. Una carpeta ``geometria/`` que exporte ``geo`` no la
   encuentra ningún import — ``geo`` da ``SEM009`` y ``geometria``, ``SEM010``.

.. _ej-test:

Bloques ``test``
----------------

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

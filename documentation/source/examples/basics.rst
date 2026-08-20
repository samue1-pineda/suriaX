Primeros programas
==================

Lo mínimo para tener algo corriendo: imprimir, declarar variables y
llamar funciones.

.. _ej-hola:

Hola, mundo
-----------

.. code-block:: srcx

   #from io #import stdp

   fn main() -> int {
       stdp.println("hola, suriaX");
       return 0;
   }

El ``#from`` trae el submódulo de impresión y lo liga al nombre ``stdp``. El
valor que devuelve ``main`` es el código de salida.

.. _ej-variables:

Variables y aritmética
----------------------

.. code-block:: srcx

   #from io #import stdp

   fn suma(int a, int b) -> int {
       return a + b;
   }

   fn area(float base, float altura) -> float {
       return base * altura / 2.0;
   }

   fn main() -> int {
       var int a = 20;
       const int b = 22;
       var int total = suma(a, b);

       total = total + suma(1, 1);
       stdp.println("calculado");
       return total;
   }

``var`` es mutable y ``const`` no; sin cualificador, un binding es ``var``.
Los tipos no se mezclan solos: sumar un ``int`` y un ``float`` exige un
``cast<T>``.

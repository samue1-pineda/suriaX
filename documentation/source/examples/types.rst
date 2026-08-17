Tipos compuestos y memoria
==========================

Structs, enums, punteros y transferencia de propiedad.

.. _ej-struct:

Structs y enums
================

.. code-block:: srcx

   #from io #import stdp

   struct {
       int x;
       int y;
   } Punto;

   enum Estado {
       INACTIVO,
       ACTIVO = 5,
       PAUSADO,
   };

   fn distancia_cuadrada(Punto ptr p) -> int {
       return p.x * p.x + p.y * p.y;
   }

   fn main() -> int {
       var Punto p = Punto{ x: 3, y: 4 };
       var int d = distancia_cuadrada(&p);

       match (d) {
           case 25 {
               stdp.println("distancia conocida");
           }
           case 0: stdp.println("origen");
       }
       return d;
   }

El nombre del struct va **al final**. En un ``match``, el ``:`` solo hace
falta cuando el cuerpo no es un bloque.

.. _ej-punteros:

Punteros y ``move``
====================

.. code-block:: srcx

   fn incrementar(int ptr mutable p) -> void {
       // escribir a través de un 'ptr' sin 'mutable' sería SEM015
   }

   fn main() -> int {
       var int n = 41;
       int ptr mutable p = &n;

       var Punto a = Punto{ x: 1, y: 2 };
       var Punto b = a;
       move a;              // 'a' queda inválida a partir de aquí

       free p;
       return n;
   }

``&`` hereda la mutabilidad del binding: sobre un ``var`` produce
``ptr mutable``, sobre un ``const`` produce ``ptr``.

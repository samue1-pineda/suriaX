Condicionales y bucles
======================

El control de flujo del lenguaje, incluidos los saltos dentro de un
bucle.

.. _ej-control:

Condicionales y bucles
=======================

.. code-block:: srcx

   #from io #import stdp

   fn clasificar(int n) -> int {
       if (n < 0) {
           return -1;
       } else if (n == 0) {
           return 0;
       } else {
           return 1;
       }
   }

   fn suma_hasta(int n) -> int {
       var int total = 0;
       var int i = 1;
       while (i <= n) {
           total = total + i;
           i = i + 1;
       }
       return total;
   }

   fn main() -> int {
       var int s = suma_hasta(10);
       if (s > 50 and s < 100) {
           stdp.println("en rango");
       } else {
           stdp.println("fuera de rango");
       }
       return clasificar(s);
   }

``and`` y ``or`` cortocircuitan: si la primera condición decide el resultado,
la segunda no se evalúa.

.. _ej-break:

``break`` y ``continue``
=========================

.. code-block:: srcx

   fn suma_impares(int tope) -> int {
       var int total = 0;
       var int i = 0;
       while (true) {
           i = i + 1;
           if (i > tope) {
               break;
           }
           var int resto = i - (i / 2) * 2;
           if (resto == 0) {
               continue;
           }
           total = total + i;
       }
       return total;
   }

   fn main() -> int {
       return suma_impares(6);   // 1 + 3 + 5
   }

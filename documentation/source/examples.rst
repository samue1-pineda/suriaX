11. Ejemplos
=============

Programas completos, en orden de dificultad. Todos se ejecutan igual:

.. code-block:: console

   $ python V0/main.py ejemplo.srcx --run

.. _ej-hola:

Hola, mundo
------------

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
-----------------------

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

.. _ej-control:

Condicionales y bucles
-----------------------

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
-------------------------

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

.. _ej-struct:

Structs y enums
----------------

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
--------------------

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

.. _ej-hooks:

Un tipo con hooks
------------------

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
--------

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

.. _ej-libreria:

Una librería propia
--------------------

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
-----------------

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

.. _ej-fases:

Ver las fases de un ejemplo
----------------------------

Cualquiera de estos programas sirve para mirar dentro del compilador:

.. code-block:: console

   $ python V0/main.py ejemplo.srcx --emit-tokens
   $ python V0/main.py ejemplo.srcx --emit-ast-json
   $ python V0/main.py ejemplo.srcx --dump-symbols-table
   $ python V0/main.py ejemplo.srcx --emit-hir --hir-text
   $ python V0/main.py ejemplo.srcx --time --debug

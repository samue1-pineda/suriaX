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

``escalar`` es ``private``: existe para la librería, no para quien la importa
desde otro paquete. ``formas.escalar(2)`` en ``programa.srcx`` es ``SEM011`` (el
mensaje dice que es ``private``), e importarla por su nombre
(``#from geo.formas #import escalar``) es ``SEM019``.

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
       expect (r == 42);
   }

   fn main() -> int {
       return doble(21);
   }

.. _ej-funciones-vector:

Ordenar, filtrar y transformar un vector
----------------------------------------

El comportamiento se pasa como una **función con nombre** (ver
:ref:`funciones como valores <funciones-como-valores>`): una del programa, una de una
librería o un método escrito ``Tipo.metodo``. Cada elemento llega como
puntero (``T ptr``): un ``int`` se lee con ``x[0]`` y un struct por sus
campos.

.. code-block:: srcx

   #from io #import stdp
   #import array.vector as vec
   #import func

   struct { str name; int age; } Person;

   @impl Person {
       fn compare_age(Person ptr self, Person ptr other) -> int {
           return self.age - other.age;
       }
       fn is_adult(Person ptr self) -> bool { return self.age >= 18; }
   }

   fn descending(int ptr a, int ptr b) -> int { return b[0] - a[0]; }
   fn is_even(int ptr x) -> bool { return x[0] % 2 == 0; }
   fn label(int ptr x) -> str { return f"<{x[0]}>"; }
   fn add(int acc, int ptr x) -> int { return acc + x[0]; }

   fn main() -> int {
       var vec.Vector<int> v = vec.dynamic<int>(4);
       v.push(3); v.push(8); v.push(1); v.push(6);

       v.sort_by(descending);                               // 8 6 3 1
       var vec.Vector<int> evens = v.filter(is_even);       // 8 6 (copias)
       var vec.Vector<str> labels = func.map<int, str>(&v, label);  // <8> <6> <3> <1>
       var int total = func.fold<int, int>(&v, 0, add);     // 18
       stdp.println(f"{evens.len()} {labels.get(0)} {total}");      // 2 <8> 18

       var vec.Vector<Person> ps = vec.dynamic<Person>(2);
       ps.push(Person{ name: "ana", age: 30 });
       ps.push(Person{ name: "luis", age: 12 });
       ps.push(Person{ name: "eva", age: 30 });
       ps.sort_by(Person.compare_age);      // luis ana eva: estable, los 30 no se cruzan
       var vec.Vector<Person> adults = ps.filter(Person.is_adult);  // ana eva
       stdp.println(f"{ps.at(0).name} {adults.len()}");             // luis 2
       return 0;
   }

- ``v.sort_by(cmp)`` ordena con ``cmp: fn(T ptr, T ptr) -> int`` (negativo,
  cero o positivo, como ``__cmp__``). Es **estable** y mueve los elementos sin
  copiarlos, así que sirve también para un ``T`` con destructor.
- ``v.filter(keep)`` con ``keep: fn(T ptr) -> bool`` devuelve un vector
  **nuevo** (dinámico) con **copias** de los que cumplen; el original no
  cambia. Con un ``T`` con destructor es ``SEM038``, como ``get``.
- ``func.map<T, U>(&v, f)`` con ``f: fn(T ptr) -> U`` y
  ``func.fold<T, A>(&v, inicial, f)`` con ``f: fn(A, T ptr) -> A`` viven en
  el paquete ``func`` porque cambian el tipo del elemento. Los argumentos
  de tipo se deducen de ``v`` y de ``f`` (``func.map(&v, texto)``); la
  forma escrita (``map<int, str>``) sigue valiendo. ``f`` recibe un puntero a una copia del
  elemento, así que, por ahora, con un ``T`` con destructor también son
  ``SEM038``.

Un argumento de otro tipo es ``AST006`` y uno de más o de menos, ``SEM008``,
como en cualquier llamada.

.. note::

   Es del **intérprete**, como todas las funciones como valores
   (``--run interpreter``).

.. _ej-predicados-vector:

Preguntar a un vector
---------------------

``any``, ``all``, ``count_if`` y ``find`` preguntan por los elementos con un
predicado ``fn(T ptr) -> bool``: una función con nombre o una
:ref:`lambda <lambdas>`, que puede leer los locales de quien la escribe.

.. code-block:: srcx

   #from io #import stdp
   #import array.vector as vec

   struct { str name; int age; } Person;

   fn is_even(int ptr x) -> bool { return x[0] % 2 == 0; }

   fn main() -> int {
       var vec.Vector<int> v = vec.dynamic<int>(4);
       v.push(3); v.push(8); v.push(1); v.push(6);

       var int limit = 5;
       stdp.println(f"{v.any(is_even)} {v.all(is_even)}");          // true false
       stdp.println(f"{v.count_if(lambda (int ptr x) -> bool: x[0] > limit)}");   // 2
       stdp.println(f"{v.find(is_even) ?? -1}");                     // 1

       var vec.Vector<Person> ps = vec.dynamic<Person>(2);
       ps.push(Person{ name: "ana", age: 30 });
       ps.push(Person{ name: "luis", age: 12 });
       match (ps.find(lambda (Person ptr p) -> bool: p.age < 18)) {
           case null { stdp.println("all adults"); }
           case i    { stdp.println(f"{ps.at(i).name} is a minor"); }  // luis is a minor
       };
       return 0;
   }

- ``v.any(p)``: ¿alguno cumple? Se detiene en el primero que cumple.
- ``v.all(p)``: ¿todos cumplen? Se detiene en el primero que no. Con el
  vector vacío es ``true``.
- ``v.count_if(p)``: cuántos cumplen.
- ``v.find(p)``: el **índice** del primero que cumple, como un ``int?``:
  ``null`` si ninguno. Se desenvuelve con ``??`` o con ``match`` (ver
  :ref:`desenvolver un T? <desenvolver-opcional>`).

Ninguna cambia el vector. El predicado recibe un puntero a una **copia** del
elemento, como en ``filter``: con un ``T`` con destructor las cuatro son
``SEM038`` (se recorre con ``at``). No hay ``for_each``: lo que lee una
lambda lo lee prestado y no lo puede modificar, y para acumular está
``func.fold``.

.. _ej-contar-palabras:

Contar palabras: ``get_or`` e ``items``
---------------------------------------

``d.get_or(k, d0)`` da el valor de ``k`` o ``d0`` si no está, sin lanzar y
sin agregar la clave. ``d.items()`` da las claves **con** sus valores, como un
``Vector<Pair<K, V>>`` (``collections.pair``), que se puede ordenar con
``sort_by``:

.. code-block:: srcx

   #from io #import stdp
   #import array.vector as vec
   #import collections.dictionary as dic
   #import collections.pair as pr
   #import text

   fn main() -> int {
       var vec.Vector<str> words = text.split_whitespace("to be or not to be that is it");
       var dic.Dictionary<str, int> counts = dic.make<str, int>(8);
       var int i = 0;
       while (i < words.len()) {
           var str w = words.get(i);
           counts.put(w, counts.get_or(w, 0) + 1);
           i = i + 1;
       }

       // de más a menos veces; a igual cuenta, por orden alfabético
       var vec.Vector<pr.Pair<str, int>> top = counts.items();
       top.sort_by(lambda (pr.Pair<str, int> ptr a, pr.Pair<str, int> ptr b) -> int {
           if (a.value != b.value) { return b.value - a.value; }
           if (a.key < b.key) { return -1; }
           return 1;
       });
       var int k = 0;
       while (k < 3) {
           stdp.println(f"{top.get(k).key} {top.get(k).value}");   // be 2 / to 2 / is 1
           k = k + 1;
       }
       return 0;
   }

``items()`` lleva **copias**, en el orden de ``keys()`` (el de las casillas,
no el de inserción): cambiar un par del vector no toca el diccionario. Con un
valor con destructor, ``get_or`` e ``items()`` son ``SEM038``, como ``get`` y
``values()``: se lee con ``at`` y se saca con ``take``.

.. _ej-result:

Una función que puede fallar: ``Result``
----------------------------------------

``result.Result<T, E>`` es un enum genérico con dos variantes, ``Ok(T)`` y
``Err(E)``: el tipo de retorno dice que la función puede fallar, y el
``match`` obliga a tratar los dos casos (``SEM030`` si falta uno). Los
argumentos de tipo se escriben siempre, al construir y en cada ``case``.

.. code-block:: srcx

   #from io #import stdp
   #import excepciones as exc
   #import result as res
   #import text

   // un puerto TCP: un número entre 1 y 65535
   fn parse_port(str s) -> res.Result<int, str> {
       var int n = 0;
       try {
           n = text.parse_int(s);
       } catch (exc.ConversionInvalida e) {
           return res.Result<int, str>.Err(f"'{s}' is not a number");
       };
       if (n < 1 or n > 65535) {
           return res.Result<int, str>.Err(f"{n} is out of range");
       }
       return res.Result<int, str>.Ok(n);
   }

   fn main() -> int {
       match (parse_port("8080")) {
           case res.Result<int, str>.Ok(port) { stdp.println(f"port {port}"); }   // port 8080
           case res.Result<int, str>.Err(why) { stdp.println(f"error: {why}"); }
       };
       var res.Result<int, str> bad = parse_port("http");
       stdp.println(f"{bad}");                                // Err('http' is not a number)
       stdp.println(f"{bad.is_ok()} {bad.unwrap_or(80)}");    // false 80
       stdp.println(f"{parse_port("70000")}");                // Err(70000 is out of range)
       return 0;
   }

``r.is_ok()`` y ``r.unwrap_or(d)`` (el valor de un ``Ok``, o ``d``) son sus
dos ayudas; ``unwrap_or`` copia, así que con un ``T`` con destructor es
``SEM038`` y se usa ``match``, que presta. ``Result`` vive en su propio
paquete y no en uno común con ``Pair``: los enums genéricos son del
intérprete, y la VM rechaza (``VM002``) todo programa que **cargue** uno.

.. note::

   Los tres ejemplos son del **intérprete** (``--run interpreter``): usan
   funciones como valores o lambdas, y el último un enum genérico.

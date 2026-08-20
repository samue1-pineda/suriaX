8. Target web (WebAssembly)
============================

El target web consume el mismo ``.phir`` que el intérprete y produce
**WebAssembly**, con un módulo **JavaScript** que lo hospeda. No hay LLVM en
medio: el HIR baja a WebAssembly por su propio IR.

.. code-block:: console

   $ python V0/main.py programa.srcx --emit-hir
   $ node web/main.ts dumps/programa.srcx.phir --run

.. _tuberia-web:

La tubería
-----------

.. code-block:: text

   .phir ─▶ decodificar ─▶ ligar ─▶ contener ─▶ optimizar ─▶ WIR ─▶ .wasm
                                                                  ├▶ host .js
                                                                  └▶ .wat

Decodificar
   Un lector propio del formato binario de protobuf, con el mismo control de
   versión de esquema que los demás consumidores.

Ligar
   Las unidades referenciadas se cargan y se indexan igual que en el
   intérprete: mismos hooks, mismas conversiones, mismos nombres.

Contener
   Qué puede ejecutar el navegador se decide **aquí**, sobre el HIR, antes de
   generar una sola instrucción. Ver :ref:`contencion`.

Optimizar
   Elimina declaraciones inalcanzables, código tras un terminador,
   expresiones sin efectos y variables nunca leídas.

Bajar al WIR
   Nombres a índices, tipos nominales a tipos de máquina, librerías a
   primitivas del host.

Emitir
   El binario, el módulo host que lo ejecuta y la vista textual.

.. _wir:

El WIR
-------

El WIR es el IR de WebAssembly. Su forma la dicta la máquina objetivo:
WebAssembly es una máquina de **pila** con control de flujo **estructurado**.

En una máquina de pila no hay destinos: cada instrucción consume lo que hay
encima y deja su resultado. Por eso el código de una expresión **es su
recorrido en post-orden**:

.. code-block:: text

   a + b * 2   ►   local.get $a
                   local.get $b
                   i64.const 2
                   i64.mul
                   i64.add

El WIR guarda las expresiones como árbol con el tipo resuelto en cada nodo, así
que emitir es recorrerlo: sin registros, sin temporales, sin decisiones. Y
como WebAssembly no admite saltos arbitrarios —solo ``block``, ``loop`` e
``if`` anidados—, el control de flujo se conserva estructurado de punta a
punta, en vez de aplanarse a bloques básicos y tener que reconstruirse
después.

Lo que el descenso al WIR resuelve, de una vez y para todos los emisores:

.. table::
   :widths: auto

   ==========================  =========================================
   HIR                         WIR
   ==========================  =========================================
   nombres y ámbitos           índices de local
   tipos nominales             ``i32`` / ``i64`` / ``f64``
   llamadas por nombre         índices de función
   librería de impresión       primitivas del host
   tipo opcional en un nodo    tipo resuelto en **todos**
   ==========================  =========================================

.. _tipos-web:

Correspondencia de tipos
-------------------------

.. list-table::
   :header-rows: 1
   :widths: 20 20 60

   * - suriaX
     - WebAssembly
     - Nota
   * - ``int``
     - ``i64``
     - 64 bits de verdad, con la misma envoltura al desbordar en los dos
       emisores.
   * - ``float``
     - ``f64``
     - IEEE-754 de doble precisión.
   * - ``bool``
     - ``i32``
     - ``0`` o ``1``.
   * - ``void``
     - —
     - Sin valor de retorno.

.. _artefactos:

Artefactos
-----------

.. code-block:: console

   $ node web/main.ts programa.phir --emit-wasm out.wasm \
                                    --emit-wat out.wat \
                                    --emit-js out.mjs

``out.wasm``
   El binario, escrito sección a sección: tipos, importaciones, funciones,
   memoria, exportaciones, cuerpos y datos.

``out.mjs``
   Un módulo ES **autosuficiente**: embebe el binario, lo instancia, aporta la
   salida y exporta ``run()``. Funciona igual en el navegador y en Node.

   .. code-block:: javascript

      import run from "./out.mjs";
      const salida = [];
      const valor = await run({ write: (t) => salida.push(t) });

``out.wat``
   El mismo módulo en formato textual, para leerlo:

   .. code-block:: wat

      (func $suma
        (export "suma")
        (param $a i64)
        (param $b i64)
        (result i64)
        local.get $a
        local.get $b
        i64.add
        return
      )

.. _control-flujo-web:

Control de flujo
-----------------

Un ``while`` se emite con el patrón canónico de WebAssembly: un ``block``
externo que es el destino de ``break``, y un ``loop`` interno que es el de
``continue``.

.. code-block:: text

   block          ;; salida — destino de 'break'
     loop         ;; cuerpo — destino de 'continue'
       <condición>
       i32.eqz
       br_if 1    ;; condición falsa -> salida
       <cuerpo>
       br 0       ;; otra vuelta
     end
   end

Los saltos se expresan por **profundidad relativa**, no por nombre, así que el
emisor lleva la cuenta de las etiquetas abiertas y la calcula: un ``break``
dentro de dos ``if`` anidados no salta a la misma profundidad que uno suelto.

``and`` y ``or`` cortocircuitan, y en una máquina de pila eso no es un
operador sino una rama: se emiten como un ``if`` que devuelve ``i32``. Con
``i32.and`` se evaluarían siempre los dos lados.

.. _contencion:

Contención de capacidades
--------------------------

El target web todavía no ejecuta todo el lenguaje. Lo que no puede se rechaza
**antes** de generar código, con un código y una posición:

.. table::
   :widths: auto

   ==========  ==========================================  =========================================
   Código      Construcción                                Motivo
   ==========  ==========================================  =========================================
   ``WEB001``  ``#extern cpp { }``                         No hay toolchain C++ en el navegador.
   ``WEB002``  ``ptr T``, ``ptr mutable T``                JavaScript no expone direcciones.
   ``WEB003``  ``&x``                                      Produce un puntero.
   ``WEB004``  ``free x;``                                 La memoria la gestiona el runtime de JS.
   ``WEB005``  ``__free__``, ``__sizeof__``                Dependen del modelo de memoria nativo.
   ``WEB006``  ``move x;``                                 Exige invalidación en tiempo de ejecución.
   ``WEB007``  Librería fuera de la lista permitida        Decisión del target.
   ``WEB008``  ``sizeof(T)``                               Depende del layout nativo.
   ==========  ==========================================  =========================================

Los códigos ``WEB1xx`` son distintos: dicen que el generador **todavía no
traduce** esa construcción, no que el target no pueda ejecutarla.

La contención corre antes que la optimización a propósito. Si corriera
después, la optimización podría eliminar la función que contenía la
construcción no soportada, y el mismo programa se aceptaría o se rechazaría
según el nivel de optimización.

.. _librerias-web:

Librerías en el navegador
--------------------------

La librería de impresión se ejecuta como **primitiva del host**: su cuerpo no
se traduce, el texto va a la memoria lineal del módulo y una función importada
lo escribe donde corresponda —la consola del navegador, la salida del
proceso o el panel de una página.

.. code-block:: srcx

   #from io #import stdp

   fn main() -> int {
       stdp.println("hola desde WebAssembly");
       return 0;
   }

.. _dos-emisores:

Dos emisores, un resultado
---------------------------

Del mismo WIR salen el WebAssembly y una implementación equivalente en
JavaScript puro:

.. code-block:: console

   $ node web/main.ts programa.phir --run       # WebAssembly
   $ node web/main.ts programa.phir --run-js    # JavaScript

Node ejecuta el ``.ts`` borrando los tipos: nativo desde la **v23**, y en la
**v22** tras la bandera ``--experimental-strip-types``. Con una versión
anterior no hay forma de correrlo y la suite se salta estos tests con aviso.

Los dos tienen que dar la misma salida y el mismo valor de retorno, y la
suite lo comprueba en cada corrida — contra el intérprete además de entre
ellos. Tres ejecutores para un solo comportamiento: cuando dos difieren, el
error está localizado antes de empezar a buscarlo.

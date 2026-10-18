.. _decision-vm:

Una máquina para el MIR
========================

*Por qué suriaX ejecuta en una VM de registros además del intérprete, y qué
dijo la medición* — **v0.4.1**

suriaX tiene dos formas de ejecutar un programa:

- el **intérprete tree-walk** en Python, que recorre el HIR nodo por nodo;
- la **VM de registros** en C++, que baja el HIR a un MIR y lo ejecuta.

Este documento registra por qué existe la segunda, qué alternativas se
descartaron, cómo se midió y qué enseñó la medición. No es la referencia de
la VM. Para eso están ``backend/README.md`` y ``docs/mir.md``.

.. _decision-vm-problema:

El problema: el oráculo es lento
---------------------------------

El intérprete es la **referencia** del lenguaje: toda prueba diferencial lo
usa como oráculo, y su valor está en ser simple y evidentemente correcto.
Pero recorre un árbol en Python, y cada nodo paga el despacho dinámico del
intérprete de Python.

El problema aparece con el bootstrap. El frontend de suriaX escrito en
suriaX (``src/frontend/``) es el primer programa grande del proyecto, y con
el intérprete:

- tokenizar ``lexer.libsrx`` (510 líneas) tarda casi **5 segundos**;
- analizar sintácticamente ``expresiones.libsrx`` (598 líneas) tarda casi
  **14 segundos**.

Un compilador que tarda eso en leer 600 líneas no sirve para compilarse a sí
mismo. La velocidad dejó de ser una comodidad y pasó a decidir si el
autocompilado es posible.

.. _decision-vm-alternativas:

Las alternativas
-----------------

Optimizar el intérprete
   Tiene un techo: el costo por nodo lo pone CPython, no el código de
   suriaX. Además, cada optimización (cachés, atajos, especializaciones)
   vuelve menos obvio al oráculo. Un oráculo rápido y difícil de leer deja de
   ser una referencia. **Se descartó** precisamente para proteger su papel.

Una VM de pila
   Es la opción clásica (JVM, CPython, WebAssembly): instrucciones
   compactas y un compilador sencillo. Pero el MIR de suriaX **ya** es un IR
   de registros con un grafo de control explícito. Sobre él trabajan la
   verificación de propiedad y trabajará el JIT. Una VM de pila exigía un
   segundo IR, o que la verificación reconstruyera el flujo de datos
   desde la pila. Hay además un argumento de rendimiento conocido:
   Shi, Casey, Ertl y Gregg [#showdown]_ tradujeron la JVM a registros y
   midieron cerca de un 47 % menos de instrucciones ejecutadas, a cambio de
   un código más grande. Lua cambió a registros en su versión 5.0 por la
   misma razón [#lua5]_. **Se descartó.**

Compilar a código nativo con LLVM
   Da el mejor código, pero con una dependencia enorme y un segundo modelo de
   máquina, antes de tener el primero funcionando. Choca además con una
   regla del proyecto: el compilador corre sin dependencias externas.
   **Quedó fuera del plan.**

Una VM de registros sobre el MIR, con un JIT después
   Reutiliza el MIR tal como está. Es un consumidor más del HIR y se compara
   contra el oráculo con la misma maquinaria que el target web. Deja al JIT
   como una optimización sobre la misma representación, no como un
   rediseño. **Es la elegida.**

.. _decision-vm-arquitectura:

Cómo es la máquina
-------------------

.. code-block:: text

   .phir ──▶ leer ──▶ resolver ──▶ bajar al MIR ──▶ verificar ──▶ ejecutar
            (modelo    (a qué       (registros +      (propiedad    (VM de
            generado)   llama cada   CFG explícito)    sobre el      registros)
                        sitio)                         grafo)

Las decisiones que más pesan:

Un registro, un valor de 64 bits
   Un ``int``, un ``float``, un ``bool`` o un ``char`` caben en un registro.
   Un ``struct`` es un **handle**: el índice de su objeto en el montón. Una
   cadena es el índice de su texto en una tabla. Así cualquier valor se copia
   como un entero y ninguna instrucción necesita conocer el tamaño de un tipo.

El control de flujo es un grafo
   Cada bloque termina en exactamente un salto, rama, retorno o ``throw``.
   Un ``throw`` es **una arista más**: cada bloque dice a dónde va si algo
   lanza dentro de él (su *handler*). El ``catch`` se decide comparando
   etiquetas enteras, no preguntando el tipo de un valor al ejecutar.

La propiedad se compila a banderas
   Cada local con destructor lleva una bandera de "vivo". ``move`` y ``free``
   la apagan, y el cierre de un ámbito destruye solo lo que sigue vivo. Es
   como lo resuelve cualquier IR de registros: la alternativa sería etiquetar
   cada valor al ejecutar para responder algo que el flujo ya decide.

Los errores del programa son los mismos
   La VM lanza las mismas excepciones del runtime que el intérprete
   (``EXC001``, ``EXC002``) y da los mismos errores fatales (``RT001``,
   ``RT019``, ``RT021``…). Un programa no puede notar en qué motor corre.

Sin dependencias
   El HIR se lee con un modelo C++ generado desde el mismo ``.proto``. Todo
   el proyecto compila con un único estándar, C++20, fijado en
   ``version.py``.

.. _decision-vm-metodologia:

Metodología
------------

El banco es ``dev/bench_vm.py`` y se repite con un comando::

   python dev/bench_vm.py --repeticiones 5 --json medida.json

- **El mismo archivo en los dos motores.** El frontend compila cada programa
  una vez a ``.phir``, y los dos ejecutan ese archivo. Se compara la
  ejecución, no el compilador.
- **De punta a punta, como lo ve un usuario.** Cuenta arrancar el proceso,
  leer el ``.phir`` y sus librerías, ligar y ejecutar. La VM además baja al
  MIR y lo verifica en cada corrida.
- **El costo fijo se resta.** El programa ``vacio`` mide el arranque de cada
  motor. La columna *neto* es el tiempo total menos ese arranque, y la
  aceleración se calcula sobre el neto.
- **La mediana de cinco corridas.** En Windows una sola corrida mide también
  al antivirus y al planificador.
- **Primero se comprueba la salida.** Si los dos motores no imprimen
  exactamente lo mismo, el banco reporta un error en vez de un número. Un
  tiempo de un programa que calculó otra cosa no significa nada.

Los programas miden cosas distintas a propósito:

========= ===========================================================
programa  qué ejercita
========= ===========================================================
bucle     aritmética entera en un ``while`` (300 000 vueltas)
fib       llamadas: Fibonacci recursivo de 24 (~150 000 llamadas)
criba     memoria cruda: criba de Eratóstenes hasta 100 000 en ``mem``
cadenas   construir una cadena de 15 000 caracteres y recorrerla
vector    structs en ``Vector<Punto>`` de la librería (20 000)
lexer     el lexer del bootstrap tokenizando ``lexer.libsrx``
parser    el parser del bootstrap analizando ``expresiones.libsrx``
========= ===========================================================

**Entorno:**
- Windows 11 sobre un procesador AMD x86-64 (familia 25, modelo 124);
- Python 3.14.7;
- la VM compilada con MSVC 14.51 en ``Release``.

.. _decision-vm-resultados:

Resultados
-----------

Tiempos en segundos (mediana de 5). *Frontend* es lo que tarda en compilar
el programa a ``.phir``, fuera de la comparación:

========= ======== ========== ======= ========== ======== ============
programa  frontend intérprete VM      neto int.  neto VM  aceleración
========= ======== ========== ======= ========== ======== ============
vacio     0.060    0.086      0.007   —          —        —
bucle     0.071    7.664      0.032   7.578      0.025    303×
fib       0.088    3.665      0.032   3.579      0.025    143×
criba     0.072    8.329      0.033   8.243      0.026    319×
cadenas   0.067    0.697      0.078   0.612      0.071    9×
vector    0.076    3.016      0.027   2.931      0.020    146×
lexer     0.329    4.798      0.042   4.712      0.036    132×
parser    0.536    13.430     0.105   13.344     0.099    135×
========= ======== ========== ======= ========== ======== ============

Los tiempos netos de la VM son de centésimas de segundo, así que la
aceleración de un programa corto varía entre corridas: en una medición
anterior idéntica ``fib`` dio 124× y ``parser`` 121×. Lo estable es el orden
de magnitud y el orden entre programas, no la segunda cifra.

Con la VM, el bootstrap pasa de "no usable" a instantáneo: el parser del
compilador escrito en suriaX lee 600 líneas en una décima de segundo.

La aceleración depende de la forma del programa:

- **Aritmética y memoria (300×).** Es el caso ideal de una máquina de
  registros: cada vuelta son pocas instrucciones sobre enteros, y el
  intérprete paga por cada nodo lo mismo que por una llamada.
- **Llamadas (~140×).** Cada llamada de la VM crea un marco con dos
  vectores y copia los argumentos. Es el primer candidato del JIT.
- **Cadenas (9×).** Concatenar repetidamente es cuadrático en los dos
  motores, porque cada ``+`` copia la cadena entera. La VM además calcula el
  hash de cada cadena nueva para no guardarla dos veces. Una representación
  por cuerdas (*ropes*) o un constructor de cadenas cambiaría este número;
  el motor no.

.. _decision-vm-leccion:

Lo que enseñó la medición
--------------------------

La **primera** medición (una sola corrida) no se parecía a la tabla de arriba:

========= ================== ==================
programa  primera medición   después
========= ================== ==================
cadenas   0.8× (más lenta)   9×
lexer     1.7×               132×
parser    3.5×               135×
========= ================== ==================

En aritmética la VM ya era 300 veces más rápida. Con cadenas era **más
lenta que el intérprete**. Había dos defectos, los dos cuadráticos y los dos
invisibles en programas pequeños:

1. **Cada** ``s[i]`` **decodificaba la cadena UTF-8 entera** para encontrar
   su carácter ``i``. Un lexer recorre su fuente carácter a carácter: n
   accesos por n de decodificación.
2. **Cada cadena nueva se buscaba entre todas las anteriores** (para no
   guardarla dos veces), con una búsqueda lineal. Cada ``+`` y cada f-string
   costaba tanto como cadenas llevaba creadas el programa.

La corrección fue una caché de code points por cadena, con vía rápida para
ASCII, y un índice hash. Son unas treinta líneas.

La lección para el diseño de un compilador: **elegir una VM no hace rápido a
un programa; lo hace la representación de los datos**. La decisión de
arquitectura (registros contra pila, contra un árbol) se notó en los
programas aritméticos. En los que importaban, los del bootstrap, mandaba
una estructura de datos. Tampoco lo encontró un perfilador: lo encontró un
banco que mide programas **reales** junto a programas sintéticos, y que
separa los casos por forma.

.. _decision-vm-correccion:

Rápida y correcta: el diferencial
----------------------------------

Un motor rápido que calcula otra cosa no vale nada. La VM se prueba contra
el intérprete programa por programa (``test/backend/test_vm_diferencial_*.py``):
salida, código de salida y códigos de error. El corpus incluye:

- la serie de excepciones;
- los programas de fuego;
- un proyecto de varios archivos;
- el lexer y el parser del bootstrap;
- una regresión por cada construcción que la VM aprendió.

Llevar el diferencial de 0 a 22 programas iguales encontró **más de diez
errores** que ninguna prueba de la VM por separado veía. Tres ejemplos:

- **Dos llamadas anidadas en un f-string llamaban a la misma función.** El
  sitio de una llamada se identificaba por su posición, y dentro de un
  f-string todas las expresiones comparten la del f-string. Ahora se
  identifica por su nodo.
- **``return t;`` destruía** ``t`` **antes de entregarla**, y el llamador
  recibía un valor ya destruido.
- **El tipo del dueño de un hook se leía en la tabla de tipos de otra
  unidad**, así que ``sizeof(dt.int8)`` daba 2.

La mayoría eran de **semántica compartida**: propiedad, unidades,
posiciones. No eran errores de la máquina en sí. Es el argumento a favor de
mantener un oráculo simple: la segunda implementación del lenguaje es la
que obliga a que la primera sea precisa.

.. _decision-vm-costos:

Qué se paga
------------

- **Dos implementaciones de la semántica.** Cada regla nueva del lenguaje
  se escribe dos veces (Python y C++). El diferencial convierte ese costo en
  una red de seguridad, pero no lo elimina.
- **La VM no recoge memoria.** Ni el montón ni las cadenas se liberan
  mientras corre. Para un compilador que lee un archivo y termina no
  importa; para un programa que corre horas, sí.
- **Hay construcciones que el MIR todavía no baja**, por ejemplo un
  ``int?`` o ``%`` entre flotantes. Se rechazan con su posición, nunca se
  bajan mal (ver ``c_errorstfix.md``).
- **El costo por instrucción no es el mínimo posible.** Cada instrucción
  devuelve un estado y cada llamada reserva sus vectores. Quedan para el JIT
  y no se optimizaron antes de tiempo.

.. _decision-vm-cuando-revisar:

Cuándo revisar esta decisión
-----------------------------

- **Si el JIT no mejora las llamadas.** Si ``fib`` no pasa claramente de ~140×
  con el JIT, el cuello está en el modelo de marcos y habría que revisarlo.
- **Si mantener dos semánticas empieza a frenar el lenguaje.** Se nota en
  que las reglas nuevas lleguen a un motor y no al otro. Entonces el
  intérprete podría quedar como oráculo congelado de un subconjunto.
- **Si aparece un programa real donde la memoria sin recoger importe.**
  Entonces hace falta un recolector, o regiones de librería.

.. rubric:: Referencias

.. [#showdown] Y. Shi, K. Casey, M. A. Ertl y D. Gregg, "Virtual Machine
   Showdown: Stack Versus Registers", *ACM Transactions on Architecture and
   Code Optimization* 4(4), 2008.

.. [#lua5] R. Ierusalimschy, L. H. de Figueiredo y W. Celes, "The
   Implementation of Lua 5.0", *Journal of Universal Computer Science*
   11(7), 2005.

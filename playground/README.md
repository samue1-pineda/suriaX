# `playground/` — cada fase del compilador, sobre tu propio código

Una página que enseña lo que el compilador entrega en **cada fase**: los
tokens, el AST, el AST-tipado, la tabla de símbolos, el HIR y el WebAssembly.

```
  navegador                     playground/server.py            el compilador
 ┌──────────┐  POST /api/compile ┌──────────────────┐  import   ┌──────────────┐
 │ index.html│ ─────────────────▶ │ http.server      │ ────────▶ │ V0/driver/   │
 │ app.js   │      fases (JSON)  │ (stdlib, sin     │           │  artifacts   │
 │ style.css│ ◀───────────────── │  dependencias)   │           └──────────────┘
 └──────────┘                    │                  │  proceso  ┌──────────────┐
                                 │                  │ ────────▶ │ web/ (TS)    │
                                 └──────────────────┘   .wat    └──────────────┘
```

## Por qué hay servidor

Porque el compilador es Python y las fases las produce **él**. La alternativa
—reimplementar lexer, parser y semántica en TypeScript para que corrieran en
el navegador— sería un segundo compilador que mantener sincronizado con este,
y el proyecto ya sabe lo que cuesta tener dos respuestas para la misma
pregunta (ver el diferencial entre consumidores del HIR).

El servidor no añade dependencias: `http.server` de la biblioteca estándar.
Lo único que invoca por proceso es el backend web (TypeScript) para el `.wat`,
y si node no está, ese panel lo dice en vez de quedarse vacío.

## Usarlo en tu máquina

### Qué necesitas

| | Versión | Para qué | Sin ello |
|---|---|---|---|
| **Python** | 3.10 o superior | El servidor y el compilador. | No arranca. |
| **node** | 22 o superior | La pestaña de WebAssembly (el target web es TypeScript y node lo ejecuta borrando los tipos). | Todo lo demás funciona; esa pestaña dice que falta node. |
| un navegador | cualquiera actual | La página. | — |

**No hay nada que instalar con `pip` ni con `npm`.** El servidor usa solo la
biblioteca estándar de Python y el target web no tiene paquetes. Comprobado
con un Python recién creado, sin ningún paquete, sobre una copia del
repositorio con solo los archivos versionados: las pruebas del playground
pasan todas. (La versión comprobada es la 3.14; 3.10 es el mínimo que declara
[`pyproject.toml`](../pyproject.toml).)

El diagrama de la pestaña *Símbolos* carga Mermaid desde internet
(`cdn.jsdelivr.net`, versión fija `11.17.2`) la primera vez que se abre. Es
lo único que la página trae de fuera. Sin conexión, esa vista no se dibuja;
la tabla de símbolos sí.

### Pasos

```bash
git clone https://github.com/samue1-pineda/suriaX
cd suriaX
python playground/server.py --check     # ¿está todo?
python playground/server.py             # http://localhost:8000
```

`--check` no levanta nada: dice qué tiene el entorno y qué le falta, y sale
con 0 solo si está completo.

```
compilador  ok
target web  no_disponible  (el backend web (TypeScript) necesita node 22 o superior; ...)
escucharía en http://127.0.0.1:8000
```

Para pararlo, `Ctrl+C`.

Si `--check` dice que falta node y lo acabas de instalar, abre una terminal
nueva: la que ya estaba abierta no ve el `PATH` actualizado.

### Configuración

El servidor lee **variables de entorno**, que es como las inyecta cualquier
plataforma. Para no exportarlas a mano hay un cargador de `.env` (copia
[`.env.example`](../.env.example) a `.env` en la raíz). **Lo que ya viene del
entorno gana** sobre el `.env`: un `.env` olvidado no puede cambiar dónde
escucha una plataforma que define `PORT`. Un valor que no sea un número no
arranca con el de por defecto: el servidor se niega a arrancar y dice cuál es.

| Variable | Por defecto | Qué hace |
|---|---|---|
| `HOST` | `127.0.0.1` | Dónde escucha. Por defecto **solo esta máquina**; `0.0.0.0` lo publica en la red. |
| `PORT` | `8000` | Puerto. |
| `SURIAX_MAX_SOURCE_BYTES` | `65536` | Tamaño máximo del fuente que se acepta. |
| `SURIAX_WEB_TIMEOUT` | `120` | Segundos que puede tardar el target web. |
| `SURIAX_WEB_CONCURRENCY` | `2` | Cuántos procesos de node pueden correr a la vez. |
| `SURIAX_CLIENT_TIMEOUT` | `30` | Segundos que se espera a un cliente que no termina de enviar. |
| `SURIAX_CORS_ORIGIN` | *(vacío)* | Un origen (`https://otro.sitio`) al que se le permite llamar a la API desde su propia página. Vacío: solo la página del playground. |

## Publicarlo

El playground es **un proceso** que se configura **por variables de entorno**
y no guarda nada: cualquier plataforma que sepa correr un comando o una imagen
sirve. Lo único que cambia respecto a tu máquina es `HOST=0.0.0.0`.

**Con un `Procfile`** (Railway, Render, Heroku y parecidas). Está en la raíz:

```
web: HOST=0.0.0.0 python playground/server.py
```

Conectas el repositorio a la plataforma y ella pone `PORT`. Estas plataformas
suelen detectar un proyecto de Python y **no instalar node**: el playground
funciona, pero la pestaña de WebAssembly dirá que falta. Para tenerla hay que
pedirle node 22 a la plataforma (cada una tiene su forma) o usar la imagen.

**Con la imagen** (cualquier sitio que corra contenedores). El
[`Dockerfile`](../Dockerfile) de la raíz trae Python y node, corre sin
privilegios y no instala paquetes:

```bash
docker build -t suriax-playground .
docker run --rm -p 8000:8000 suriax-playground
```

> El `Dockerfile` está escrito pero **todavía no se ha construido**: al
> escribirlo, Docker no estaba en marcha en la máquina de desarrollo. Hasta
> que se construya una vez, trátalo como sin probar.

**Después de publicar**, `GET /api/health` dice si el entorno quedó completo:
`"status": "ok"` es que están el compilador y el target web.

**Lo que conviene saber antes de exponerlo:**

- No ejecuta programas: compila y enseña fases. No hay cuentas ni datos que
  guardar.
- Compila **de uno en uno** (el compilador guarda estado global). Con varias
  personas a la vez las peticiones hacen cola; no se corrompen.
- Los límites son los de la tabla de arriba. No hay límite de peticiones por
  cliente: si lo necesitas, ponlo en el proxy o en la plataforma.
- No termina TLS: `https` lo pone la plataforma o un proxy delante.

## Qué puede usar un programa

El playground compila para el **target web**, así que hereda lo que ese
target no ejecuta, y añade una lista de librerías. Las dos cosas están en un
solo sitio, como datos: [`web/src/target/policy.ts`](../web/src/target/policy.ts)
(perfil `playground`).

| | En el playground | Por qué |
|---|---|---|
| El lenguaje sin punteros: funciones, control, `struct`, `enum`, cadenas, f-strings | **Sí**, hasta donde llega el codegen del target (lo que falta sale como `WEB1xx`) | — |
| `io` (`stdp`, `stdpf`), `math`, `excepciones` | **Sí** | El target sabe ejecutarlas. |
| `sistema` (archivos, procesos, rutas) | **No, nunca** | El playground no tiene sistema de archivos ni procesos. |
| `text`, `array`, `collections`, `mem` | **Todavía no** | Su implementación usa punteros. |
| `d_types` | **Todavía no** | Sus tipos declaran `__sizeof__`. |
| Punteros, `&x`, `free`, `move`, `sizeof`, `__free__`/`__sizeof__` | **No** (`WEB002`–`WEB008`) | Los contiene el target web. |
| `#extern cpp` | **No** (`WEB001`) | No hay toolchain de C++ en el navegador. |
| Importar archivos propios | **No** | Un programa del playground es un solo archivo. |

Una librería denegada da **un** diagnóstico (`WEB007`) en su `#import`, que
dice si es "nunca" o "todavía no". Las fases del compilador (léxico, AST,
símbolos, HIR, enlace) se enseñan igual: lo que no pasa es la bajada a
WebAssembly.

Además, del lado del servidor: el fuente no puede pasar de 64 KB, los
mensajes se publican sin las rutas de la máquina y el programa **no se
ejecuta** en el servidor.

## Conectarse desde otra herramienta

La página es un cliente más. Todo lo que hace lo hace por HTTP, y esa API
está descrita en [`openapi.json`](openapi.json) (OpenAPI 3.1), que el propio
servidor publica en `GET /api/openapi.json`.

| Ruta | Qué da |
|---|---|
| `POST /api/compile` | Todas las fases de un fuente. |
| `POST /api/lex` | Solo los tokens (para colorear). |
| `GET /api/language` | Categorías de token, catálogo de errores, palabras clave. |
| `GET /api/health` | El estado del compilador y del target web. |
| `GET /api/openapi.json` | La descripción de la API. |

```bash
curl -s http://127.0.0.1:8000/api/compile \
     -H "Content-Type: application/json" \
     -d '{"source": "fn main() -> int { return 0; }"}'
```

Tres reglas bastan para leer una respuesta:

1. **Un 200 significa "te atendí"**, no "tu programa compila". Un programa
   con errores es un 200 con sus `diagnostics`.
2. **`status` dice cómo fue**, con cuatro valores, y `providers` dice de
   quién es la culpa:

   | `status` | Significa | Lo arregla |
   |---|---|---|
   | `ok` | Todo se produjo. | — |
   | `error_del_programa` | El programa no compila. | Quien lo escribió. |
   | `no_disponible` | Al entorno le falta algo (node), o no había nada que procesar. | Quien instaló el entorno. |
   | `error_interno` | Falló el compilador o el target web. | Quien los mantiene. |

   El de la respuesta es el peor de los de `providers.compiler` y
   `providers.web`. Cada fase de `phases` lleva también el suyo, y si no
   tiene artefacto lleva `reason`.
3. **Un 4xx o 5xx significa "no pude atenderte"** y llega con la forma de la
   RFC 9457 (`title`, `status`, `detail`).

El cuerpo se envía como `application/json`; con otro tipo responde 415. Desde
una página de **otro origen** el navegador solo deja llamar si el servidor se
arrancó con `SURIAX_CORS_ORIGIN` igual a ese origen.

Quien use Python y no quiera HTTP puede importar la misma función que usa el
servidor:

```python
import sys
sys.path.insert(0, "playground")
from capas.aplicacion import compile_source

datos = compile_source("fn main() -> int { return 0; }")
datos["status"], datos["phases"]["hir"]["pretty"]
```

Cómo está hecho por dentro, y por qué: [`ARQUITECTURA.md`](ARQUITECTURA.md).

## Qué se ve en cada fase

| Fase | Forma | Por qué esa |
|---|---|---|
| **Léxico** | un token por **fila**, en columnas | Posición, clase, lexema y valor alineados: un token es una fila de datos y se lee comparándolo con los de al lado. El **valor** solo sale cuando no es el lexema —`f"x {a}"` vale `"x " + {a}`—, que es la otra mitad del trabajo del lexer. Pasar el ratón **subraya su línea** en el fuente: la pregunta de esta fase es *¿de dónde salió esto?*, y la posición viaja en el token. |
| **AST** | **grafo** de cajas conectadas | Un árbol indentado esconde justo lo que uno mira en un AST: su **forma** — cuánto se ramifica y dónde está el peso del programa. Con pan, zoom y nodos plegables ([`static/grafo.js`](static/grafo.js)). |
| **AST-tipado** | el mismo grafo | Con el `restype` que anota la Semántica: la única diferencia con el anterior, y verlos con la misma forma es lo que la hace evidente. |
| **Símbolos** | **tabla** + **diagrama** | La *tabla* es el árbol de scopes, las entradas y el **inspector** de una: dónde nació cada nombre, de qué tipo es, si es mutable y **en qué líneas se usa**. Esas referencias cruzadas las anota la Semántica al resolver cada nombre —es el único sitio que sabe a qué símbolo apunta un `x`—, no un segundo barrido del fuente. El *diagrama* (Mermaid) contesta la otra mitad: qué tipos hay y cómo se relacionan; incluye las funciones libres (`<<module>>`), las globales (`<<scope global>>`), **cada import con lo que expone** y las conversiones (`<<__cast__>>`). |
| **HIR** | **legible** + **protobuf** | La legible (`--hir-pretty`) es una línea por sentencia, con tipos, hooks y la destrucción que inserta el compilador. La de protobuf dice qué tag lleva qué. |
| **Enlace** | **lo que trajo** cada unidad, símbolo a símbolo | *Esto no es magia*: `print` no está en el lenguaje. Se ve que `IO.stdp` aporta `println`, que debajo hay un prototipo `__write__` cuyo cuerpo pone quien ejecuta —de ahí sale el `host` del WebAssembly— y que un hook viaja con su dueño para que `print(x)` sepa a quién llamar. Decir "se resolvió el import" no explica nada; verlo, sí. |
| **WebAssembly** | **legible** + **wat** | La legible imprime el WIR con las expresiones en línea (`total = 40 + 2`); el `.wat` muestra el post-orden real de la pila. |
| **Depuración** | tiempos y métricas | Solo con el botón *Depurar*: la misma compilación, contada. No se enseña una pestaña vacía a quien no la usa. |

## El target manda

El programa va **directo** hacia el backend web. Si el target no soporta algo,
eso **no es "una fase que no produjo nada": es que el programa no compila para
ese target** — y así se reporta, como un diagnóstico con su posición y en la
cuenta de errores. Enseñarlo como un hueco invitaba a pensar que el intérprete
lo salvaría, y por ese camino el intérprete no pasa.

Los dos motivos se distinguen porque dicen cosas distintas y sugieren acciones
distintas:

| | Código | Significa |
|---|---|---|
| **NO SOPORTADO** | `WEB0xx` | El target **decidió** no ejecutarlo (`#extern cpp` no tiene toolchain en el navegador). Es definitivo. |
| **NO SE PUDO COMPILAR** | `WEB1xx` | El codegen **todavía no llega** (un `struct`, un `try`, una cadena calculada). Es trabajo pendiente del compilador, no una prohibición. |

**Las fases con dos vistas** siguen la misma regla: una para **leer el
programa** y otra para **depurar el formato**. Son preguntas distintas y un
solo volcado no responde bien a ninguna — es el mismo motivo por el que
`--hir-pretty` existe junto a `--hir-text`.

**Cada fase se entrega aunque las anteriores hayan fallado.** Un programa con
un error de sintaxis igual tiene tokens, y verlos es lo que explica el error.
Lo que no se pudo producir dice **por qué** — nunca aparece un panel vacío que
parezca un artefacto válido.

## Los errores

"La compilación falló" no dice nada. Un diagnóstico se enseña **en la pestaña
de su fase**, con las cuatro cosas que el proyecto exige de un error:

- **qué falló** — el mensaje del compilador;
- **dónde** — la línea del fuente, con una marca bajo la columna exacta;
- **por qué** y **qué hacer** — del catálogo del compilador, que publica el
  **docstring de cada clase de error**. Ese docstring ya existía y ya se
  exigía que estuviera bien escrito: publicarlo no cuesta mantenerlo, y es
  justo donde el proyecto explicaba por qué existe cada diagnóstico.

Las pestañas cuyas fases traen diagnósticos se marcan con ● antes de abrirlas.

## Los colores

**También en el editor**, con los mismos colores que las pestañas y por el
mismo camino: mientras se escribe, el editor pide los tokens a
`POST /api/lex` —solo el lexer, una pasada, menos de un milisegundo— y pinta
con ellos. Un resaltador propio volvería a decidir qué es cada palabra, y
entonces habría **dos respuestas para la misma pregunta**: el editor pintando
`move` como un identificador y el compilador leyéndolo como una transferencia.

Los tokens se colorean por la **categoría que declara el compilador**
(`lang_info.token_categories`), no por una heurística de la página. Aquí hubo
una expresión regular que decidía si `INT` era un tipo o un literal, y se
equivocaba; `lang_info` existe precisamente *"para que la extensión coloree
sin reimplementar la gramática"*, y un segundo consumidor con sus propias
reglas volvería a inventar la respuesta.

Las categorías son las **del lenguaje** —`memory`, `error_handling`,
`declaration`— y no las genéricas de un resaltador cualquiera, así que el
color enseña algo de suriaX: `move` y `free` se ven como lo que son.

## El diseño

Colores **planos**: ni un degradado, ni una animación, ni un icono dibujado.
Lo que separa una zona de otra es una línea y un fondo sólido, que es como se
ven las herramientas que uno usa ocho horas seguidas. La jerarquía la marcan
el tamaño y el peso del texto.

El color se reserva para lo que **significa** algo: la severidad de un
diagnóstico y la clase de un token. Si todo tuviera color, el color no diría
nada.

## Los enlaces de la barra

- **Documentación** → el sitio de Sphinx en GitHub Pages.
- **Teoría** → decisiones al crear un compilador, estructuras de datos y sus
  justificaciones. Todavía no existe: el enlace apunta a su ruta final y va
  marcado como *próximamente*, para que se vea planeado y no roto. El día que
  se publique, funciona sin tocar nada.

## Lo que no hace

No ejecuta el programa. El intérprete corre en el servidor y ejecutar código
de cualquiera en un servidor público es otra decisión, con su aislamiento y
sus límites; el playground **muestra fases**, que es lo que se le pidió.

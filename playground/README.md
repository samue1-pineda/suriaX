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

## Correr

```bash
python playground/server.py          # http://localhost:8000
PORT=3000 python playground/server.py
```

En **Railway** el puerto lo pone la plataforma en `PORT`. El despliegue usaba
un `Procfile` en la raíz con el comando, que **se perdió en el rescate de la
0.3.0** (ver [c_errorstfix.md](../c_errorstfix.md)): hasta reponerlo, el
comando es `python playground/server.py`. Los volcados del backend web van a `.web/`, que es su
carpeta de artefactos generados (ignorada por git, como `dumps/`).

### Configuración

El servidor lee **variables de entorno**, que es como las inyecta cualquier
plataforma. Para correrlo en otro sitio sin exportar nada a mano, hay un
cargador de `.env` (copia [`.env.example`](../.env.example)):

| Variable | Qué hace |
|---|---|
| `PORT` | Puerto donde escucha (8000 por defecto). |
| `SURIAX_MAX_SOURCE_BYTES` | Tamaño máximo del fuente que se acepta compilar. |
| `SURIAX_WEB_TIMEOUT` | Segundos que puede tardar el backend web. |

**Lo que ya viene del entorno gana** sobre el `.env`: si mañana esto corre en
una plataforma que define `PORT`, un `.env` olvidado en el repositorio no
puede cambiar dónde escucha.

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

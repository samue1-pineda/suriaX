# Arquitectura del playground

Cómo está partido el playground, qué reglas sigue y cuáles todavía no. Para
usarlo, publicarlo o conectarse, ver el [README](README.md).

## El problema que resuelve

El playground junta tres piezas que no tienen por qué fallar juntas: una
página, el compilador (Python) y el target web (TypeScript, ejecutado por
node). Antes estaban en un solo archivo y un fallo de cualquiera se llevaba a
las demás: si node tardaba de más, el servidor respondía un 500 y la página
perdía también las fases que el compilador sí había producido.

La regla de diseño es una: **cada pieza responde por lo suyo, y lo dice con
el mismo vocabulario**.

## Capas y adaptadores

```
 presentación   static/            la página: pide por HTTP y dibuja
 ───────────────────────────────────────────────────────────────── HTTP + JSON
 transporte     server.py          rutas, cabeceras, límites, errores HTTP
 aplicación     capas/aplicacion   a quién se le pide qué y cómo se junta
 adaptadores    capas/compilador   el compilador ── import ──▶ V0/driver
                capas/web          el target web ── proceso ─▶ node web/main.ts
```

Es una arquitectura de **capas**: una capa solo conoce a la de debajo. El
transporte no sabe qué es un `.phir`; un adaptador no sabe qué es una
cabecera.

A las capas se les añade una cosa, que es la que da el desacoplamiento: los
dos proveedores de abajo (compilador y target web) están detrás de
**adaptadores** que **no se conocen entre sí**. Lo único que comparten es el
vocabulario de [`capas/estados.py`](capas/estados.py). Con capas solas, el
target web quedaría "debajo" del compilador y su fallo subiría por él; con
adaptadores, la aplicación le pregunta a cada uno por separado.

| Pieza | Responsabilidad | No hace |
|---|---|---|
| [`static/`](static/) | Dibujar lo que llega. | Clasificar tokens, explicar errores, decidir si algo compila. |
| [`server.py`](server.py) | HTTP: validar la petición, límites, cabeceras, errores de transporte. | Compilar. |
| [`capas/aplicacion.py`](capas/aplicacion.py) | Orquestar: compilar, pasarle el `.phir` al target, juntar la respuesta. | Hablar HTTP, lanzar procesos. |
| [`capas/compilador.py`](capas/compilador.py) | Llamar al compilador de uno en uno y convertir su fallo en un estado. | Saber del target web. |
| [`capas/web.py`](capas/web.py) | Lanzar node, leer su informe y convertir cada forma de fallar en un estado. | Saber del compilador de Python. |
| [`capas/config.py`](capas/config.py) | Leer la configuración una vez. | — |

Lo que cruza entre el compilador y el target web es **un archivo** (`.phir`)
y lo que vuelve es **un informe en JSON**: el mismo contrato que tiene quien
ejecute `node web/main.ts programa.phir --json` a mano. Por eso cada uno
funciona sin el otro y sin el playground: el compilador es la CLI de siempre
y el target web es un programa de línea de comandos.

## Los cuatro estados

Un `ok` booleano no distingue "tu programa tiene un error" de "al compilador
se le rompió algo". Cada proveedor responde con uno de cuatro estados, porque
piden acciones distintas:

| Estado | Significa | Lo arregla |
|---|---|---|
| `ok` | Se produjo todo. | — |
| `error_del_programa` | El programa no compila (o no compila para ese target). | Quien lo escribió. |
| `no_disponible` | Falta algo en el entorno (node) o no había nada que procesar (sin HIR no se llama al target). | Quien instaló el entorno. |
| `error_interno` | Falló el proveedor. | Quien lo mantiene. |

Cómo se llega a `error_interno` en el target web: no respondió a tiempo, no
se pudo lanzar, terminó sin informe legible, o entregó un informe sin
artefacto y sin diagnósticos. En ninguno se le atribuye nada al programa, y
la salida de error de node se conserva (sin las rutas de la máquina).

Un fallo interno **no añade diagnósticos**: un diagnóstico es un error del
programa, con posición, y esto no lo es.

## Qué pasa cuando algo falla

| Falla | La página | La API |
|---|---|---|
| El target web | Las pestañas del compilador, intactas. La de WebAssembly dice que falló por dentro. | 200, `providers.web.status = error_interno`. |
| El compilador | Se sirve y responde. Cada pestaña dice que el compilador falló por dentro. | 200, `providers.compiler.status = error_interno`, las siete fases presentes con su motivo. |
| No hay node | Todo menos WebAssembly, que dice qué falta. | 200, `providers.web.status = no_disponible`. |
| La petición es inválida | — | 4xx con la forma de la RFC 9457. |
| El servidor | — | 500 con la forma de la RFC 9457. |

La columna de la API tiene una prueba por fila en
[`test/e2e/test_playground.py`](../test/e2e/test_playground.py), que simula el
fallo cambiando la función que lanza el proceso: se prueban también donde
node no está. La columna de la página se comprobó **a mano en Chrome sin
ventana**, manejado por su protocolo de depuración: cada fila, más un
programa válido, uno con errores y uno con una librería denegada, sin una
sola queja del navegador (consola, excepciones, política de contenido). Esa
comprobación no está en la suite: no hay prueba automática de la página.

## Normas

Qué se sigue, en qué, y qué falta. "Seguir" aquí es adoptar lo que aplica a
un servicio de este tamaño; ninguna de estas es una certificación.

| Norma | Para qué | Estado |
|---|---|---|
| **HTTP — RFC 9110** | Que los códigos y métodos signifiquen lo que dicen. | Seguida: 200 solo si se atendió; 400, 404, 405 con `Allow`, 411, 413, 415, 500. |
| **Problem Details — RFC 9457** | Un formato de error que una herramienta puede leer. | Seguida en todos los 4xx/5xx de la API. |
| **OpenAPI 3.1** | Describir la API de forma que se pueda generar un cliente. | [`openapi.json`](openapi.json); una prueba compara sus rutas, estados y campos obligatorios con las respuestas de verdad. No se ha pasado por un validador de OpenAPI externo. |
| **OWASP (Top 10 y cabeceras)** | No abrir huecos conocidos. | Parcial; ver abajo. |
| **WCAG 2.2 nivel AA** y **WAI-ARIA** | Que la página se pueda usar con teclado y lector de pantalla. | **Parcial.** Hecho: las pestañas siguen el patrón de WAI-ARIA (`tablist`/`tab`/`tabpanel`, flechas del teclado), el estado se anuncia (`role="status"`), los botones sin texto tienen nombre. Sin evaluar: contraste de color, orden de foco completo, el editor y el grafo del AST con lector de pantalla. |
| **Twelve-Factor** | Que se pueda desplegar sin tocar el código. | Seguido en lo que aplica: configuración por entorno, un proceso sin estado, registro por la salida de error, escucha en un puerto. |
| **ISO/IEC 25010** | Vocabulario para hablar de calidad. | Usado como guía en la sección siguiente, no como evaluación. |

### Seguridad: lo hecho y lo que falta

Hecho, cada punto con su prueba:

- Escucha **solo en esta máquina** por defecto; publicarlo es una decisión.
- Solo se sirven archivos de `static/` (un `..` no sale del directorio).
- Cota de tamaño del fuente, de tiempo y de procesos simultáneos del target
  web, y de espera a un cliente lento.
- El cuerpo debe ser `application/json`: una página ajena no puede poner a
  compilar a un servidor local con un formulario.
- Ningún otro origen puede llamar a la API salvo el que se configure (CORS),
  y es uno, no `*`.
- `X-Content-Type-Options: nosniff` y `Referrer-Policy: no-referrer` en todo;
  `Cache-Control: no-store` y una política de contenido cerrada en la API.
- No se anuncia la versión de Python, y los fallos internos se publican sin
  trazas ni rutas (la traza queda en el registro del servidor).
- Sin dependencias de terceros en el servidor ni en el target web.

- La página lleva su política de contenido (CSP): todo de este servidor,
  salvo los scripts de `cdn.jsdelivr.net` (Mermaid) y los estilos en línea
  (los escribe Mermaid dentro del SVG). Sin `eval` ni scripts en línea.
- Mermaid se carga con la **versión exacta** (`11.17.2`), no con un rango.
- Los mensajes del compilador se publican sin las rutas de la máquina
  (`SEM009` enumeraba las carpetas donde buscó).
- El target web se invoca con el perfil `playground`: lista blanca de
  librerías (ver "Qué puede usar un programa" en el README).

Falta:

- **Mermaid sigue siendo código de un tercero servido por un CDN.** Fijar la
  versión impide que cambie sin aviso, pero no comprueba su contenido: un
  `import()` dinámico no admite suma de integridad. Lo estricto es servir una
  copia propia, revisada.
- **Un programa puede importar lo que haya en la carpeta desde la que se
  arrancó el servidor** (`.libsrx`, paquetes o `.srcx`), porque el compilador
  busca primero junto al fuente y el del playground no tiene carpeta propia.
  Hoy no hay nada importable en la raíz del repositorio, y lo importado
  tampoco pasaría la lista blanca del target; pero sus firmas sí se verían en
  la pestaña de enlace.
- **Límite de peticiones por cliente.** No hay; se delega en la plataforma.
- **Aislamiento del compilador.** Corre en el proceso del servidor: una
  compilación que no termine retiene el candado y nadie más compila. Lo acota
  el tamaño del fuente; lo resolvería correrlo en un proceso aparte.

## Calidad

Con el vocabulario de la ISO/IEC 25010, lo que el diseño busca y cómo se
comprueba:

| Atributo | Qué se hizo | Cómo se sabe |
|---|---|---|
| **Fiabilidad** (tolerancia a fallos) | El fallo de un proveedor no se lleva al otro ni al servidor. | Pruebas que simulan cada fallo. |
| **Fiabilidad** (madurez) | El compilador se llama de uno en uno. | Medido: sin el candado, 10 de 90 compilaciones en paralelo daban un resultado distinto al de la serie; con él, la prueba de concurrencia pasa. |
| **Mantenibilidad** (modularidad) | Capas y adaptadores; cada archivo tiene una responsabilidad. | La tabla de arriba. |
| **Mantenibilidad** (capacidad de prueba) | Cada adaptador tiene un punto donde se sustituye al proveedor. | Las pruebas no necesitan node. |
| **Compatibilidad** (interoperabilidad) | API descrita y versionada (`api`). | Prueba que ata la descripción a las respuestas. |
| **Portabilidad** (instalabilidad) | Sin dependencias; configuración por entorno. | Pruebas pasadas con un Python sin paquetes sobre una copia limpia. |
| **Seguridad** | Lo de la sección anterior. | Pruebas por punto. |
| **Usabilidad** (accesibilidad) | Pestañas con teclado, estado anunciado, nombres en los botones. | Comprobado a mano en Chrome; sin evaluación completa. |
| **Usabilidad** (protección ante errores) | Un fallo interno se rotula como tal y no como error del programa; una librería denegada da un diagnóstico, no cuarenta. | Pruebas del perfil; la página, a mano. |
| **Eficiencia** | No se ha medido nada del servidor. | — |

## Versionado de la API

El campo `api` de cada respuesta y `info.version` de la descripción valen lo
mismo. Sube cuando un campo cambia de significado o desaparece. **Añadir
campos no la sube**: quien consume debe ignorar los que no conozca. Los
nombres de los cuatro estados son parte del contrato.

# Futuras implementaciones de suriaX

La **única lista de ideas** para después de la versión en curso. El
[ROADMAP](ROADMAP.md) cuenta las fases y lo que ya se hizo; lo que falla hoy
está en [c_errorstfix.md](c_errorstfix.md). Aquí va lo que todavía no se
construye, con su estado:

- **idea**: el mantenedor quiere recordarla; no está decidido qué ni cómo.
- **decidida**: se hará; el qué está claro y el cuándo no.
- **en curso**: alguien trabaja en ella.

Cuando una idea se construye, sale de aquí y queda en el CHANGELOG. Este
documento no lleva fechas.

---

## Lenguaje

| Idea | Estado | Notas |
|---|---|---|
| Bucle `for` con un concepto de recorrido (iterador o rango) | decidida | Completa la programación genérica: los algoritmos se separan de los contenedores. Va junto con la visibilidad de campos. |
| Análisis de flujo | decidida | Falta de `return`, `move` en bucles y en `try` → `catch`, punteros a locales que escapan, globales leídas antes de tiempo a través de una función. Ver `c_errorstfix.md` §5. |
| Modo "no seguro" | idea | Formas de escapar de las reglas de propiedad y de préstamo donde convenga, como el `unsafe` de Rust, con una regla de qué conviene hacer "no seguro" (como en su momento "na regions"). Hoy manda el tipado seguro: un parámetro `fn` es prestado (`SEM051`). Se discute qué y cómo. |
| Revisión de la notación prefija/postfija | idea | Pensando en quien viene de C++ (por ejemplo, los punteros). El tipo puntero ya es postfijo como en C (`char ptr`); hay que preguntar qué construcciones se quieren cambiar. |
| Sobrecarga de funciones | idea | Sin decidir; quedó fuera de la decisión sobre templates. |
| Parámetros de tipo que no son tipos (`<int N>`) y argumentos de tipo por defecto | decidida (aplazada) | De los templates de C++, después del recorrido. |

## Librería y nombres

| Idea | Estado | Notas |
|---|---|---|
| Nombres en inglés | decidida | Librerías, funciones, excepciones y la V1, en un solo lote; la documentación sigue en español. El código nuevo ya se escribe en inglés. |

## Herramientas y desacople de Python

| Idea | Estado | Notas |
|---|---|---|
| Build tool (o helper) escrito en suriaX | idea | Para desacoplar suriaX de Python. Su orden se decide en la charla de cierre de la 0.4.1. Lo que lo condiciona: corriendo en el intérprete sigue dependiendo de Python; el desacople real es la V1 compilando y la VM ejecutando, y las dos tienen que estar al día con la 0.4.1. Además, el lote de nombres en inglés obligaría a reescribirlo. |
| Build system suriniX | idea | Del ROADMAP (Fase 10). |
| Syscalls de suriniX escritas en suriaX | idea | Una capa de llamadas al sistema en suriaX sobre las llamadas al host. |
| Publicar la extensión de VS Code | decidida | Le faltan un identificador de publicador y un icono, y probarla dentro del editor. |
| `Dockerfile` del playground construido y probado | decidida | Existe pero nunca se ha construido. |

## Motores

| Idea | Estado | Notas |
|---|---|---|
| JIT de la VM | decidida | En una versión posterior. La medición de los hot spots está en el ROADMAP (Fase 6). |
| Target web al día con la 0.4.1 | decidida | Hoy rechaza lo nuevo con su código. |

## Aparcado (no planificar sin que el mantenedor lo reabra)

| Idea | Estado | Notas |
|---|---|---|
| Enlazar suriaX dentro de otro programa (embedding, como Lua) | idea | `#extern` para C/C++ es la semilla; necesita una interfaz binaria estable. |
| Operar sobre otro proyecto, más allá de leer sus archivos | idea | |
| GUI mínima | idea | No una aplicación grande. |
| Depuradores y sanitizadores para otros lenguajes | idea | Necesitan llamadas al host o APIs del sistema que el lenguaje no tiene. |

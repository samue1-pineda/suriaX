# `src/aritmetica/` — las dos primeras etapas, escritas en suriaX

Un **lexer y un parser de verdad** sobre expresiones enteras con precedencia,
escritos en el lenguaje. Es la primera pieza de la V1 (ver
[`src/readme.md`](../readme.md)): el compilador empezando a escribirse a sí
mismo.

```
"12 + 34 * 2"  ->  tokens  ->  descenso recursivo  ->  80
```

```bash
suri src/aritmetica/calc.srcx     # necesita lib/ y este paquete al alcance
```

| archivo | qué es |
|---|---|
| `frontend.libsrx` | `enum TType`, `struct Token`, `tokenizar`, y el parser (`expresion` / `termino` / `factor`) |
| `calc.srcx` | el conductor: expresiones válidas, errores y un volcado de tokens |
| `main.libsrx` | cierra el paquete |

No lleva pruebas del suite a propósito: es código de la V1, no del compilador
que la compila.

## Qué demostró

Lo que **sí** aguanta el lenguaje, tal como está:

- `enum` con valores explícitos como clases de token, comparables con `==` y
  con `match`, y `cast<int>` para agrupar por familia (`t / 10`);
- `struct` con campos de tipos distintos como registro de token;
- `Vector<Token>` — un contenedor genérico de un tipo del usuario;
- recorrer una cadena con `s[i]` y `len(s)`, en **code points**;
- estado mutable compartido por niveles con `Parser ptr mutable`, que es el
  `self` de un método escrito a mano;
- recursión mutua entre `expresion`, `termino` y `factor`;
- diagnósticos con posición: qué se esperaba, qué llegó y en qué columna.

## Qué le faltó

Encontrado escribiéndolo, no leyendo el compilador:

| límite | consecuencia aquí |
|---|---|
| **Un submódulo no puede importar a un hermano de su paquete** | El linker lo ve como import circular al re-entrar en el paquete que está cargando. Por eso `tokens`, `scanner` y `parser` están en **un solo archivo** en vez de en tres, que es como los tiene la V0. Es el límite que más pesa para el bootstrapping. |
| **`error` es palabra reservada** | El campo del parser se llama `fallo`. Razonable —`error T` es un tipo—, pero el diagnóstico dice *"se esperaba un nombre, se encontro ERRORTYPE"* y no que el nombre esté reservado. |
| **`.name` de un enum es constante** | Se resuelve al compilar, así que vale sobre `TType.PLUS.name` pero no sobre una variable: `nombre_de` tiene que escribir el `match` de diez ramas. |
| **Sin punteros a función** | Una tabla de precedencias dirigida por datos no se puede escribir; la precedencia queda codificada en qué nivel llama a cuál (que aquí es legible, pero no escala a un lenguaje entero). |
| **Sin E/S de ficheros** | El fuente a analizar se escribe en el programa. Leer un `.srcx` desde disco todavía no es posible. |

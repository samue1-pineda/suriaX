# Llamadas al host

Lo que un programa de suriaX le pide a la máquina en la que corre: escribir,
leer un archivo, la hora, lanzar otro programa. No son palabras del lenguaje
ni *syscalls*: son funciones **sin cuerpo** declaradas en la librería, cuya
implementación pone quien ejecuta.

```srcx
// lib/sistema/tiempo.libsrx
internal fn __ahora_ms__() -> int;        // sin cuerpo: lo pone el host

public fn ahora() -> int {               // lo que usa el programa
    return __ahora_ms__();
}
```

Este documento es el **contrato**: la lista completa, con la firma de cada
una y qué motor la cumple. Una prueba
([`test/unit/test_llamadas_al_host.py`](../test/unit/test_llamadas_al_host.py))
lo compara con la librería, con el intérprete, con la VM y con el target web:
si alguno no dice lo mismo que esta tabla, falla.

## Las reglas que valen para todas

- **El mismo resultado en cualquier motor y en cualquier máquina.** Un texto
  se lee y se escribe como UTF-8, sin traducir los fines de línea; una
  lista de archivos sale ordenada; una ruta se compone con las reglas de la
  plataforma, que son las del compilador.
- **Un fallo es una excepción del programa, con un mensaje que nombra lo que
  falló**, nunca un fallo interno: `excepciones.ErrorDeArchivo` (`EXC003`)
  para todo lo que toca el sistema, `IndiceFueraDeRango` (`EXC002`) para un
  índice, `ConversionInvalida` (`EXC004`) para un texto que no se convierte.
- **El programa usa la función pública, no la llamada.** Las llamadas son
  `internal`: solo las ve su archivo. Así una librería puede cambiar cómo
  usa al host sin que cambie su interfaz.
- **Un argumento que el host no sabe recibir no se le pasa.** Un `Vector` se
  entrega como su bloque y su longitud (`__unir__`, `__ejecutar__`), y lo que
  el host produce de varias partes se pide por partes (`__ejecutar__` y luego
  `__salida_ejecutada__`), en vez de que el host fabrique un `struct` de la
  librería.

## Añadir una

1. La función sin cuerpo y la pública que la usa, en la unidad de la
   librería que corresponda (un área nueva de `sistema` es un archivo nuevo
   en `lib/sistema/`).
2. Su implementación en el intérprete: una entrada en `REGISTRY`
   (`runtime/interpreter/intrinsics.py`).
3. Su fila aquí. La VM y el target web pueden llegar después: la tabla dice
   dónde está y dónde no, y la prueba lo comprueba.

Una llamada que solo existe en el intérprete compila igual en cualquier
motor; ejecutada en la VM es `RT008`, que la nombra.

## La lista

`no` en una columna = ese motor no la tiene todavía. El target web solo
tiene `__write__` (la salida de la página): no hay archivos, procesos ni
reloj en un navegador.

### `io/stdp.libsrx`

| Llamada | Firma | Intérprete | VM | Web |
|---|---|---|---|---|
| `__write__` | `(str s) -> void` | sí | sí | sí |

### `mem/main.libsrx`

| Llamada | Firma | Intérprete | VM | Web |
|---|---|---|---|---|
| `__reserve__` | `<T>(int n) -> T ptr mutable` | sí | sí | no |
| `__copy__` | `<T>(T ptr mutable dst, T ptr src, int n) -> void` | sí | sí | no |
| `__release__` | `<T>(T ptr mutable bloque) -> void` | sí | sí | no |
| `__take__` | `<T>(T ptr mutable bloque, int i) -> T` | sí | sí | no |
| `__move__` | `<T>(T ptr mutable dst, T ptr mutable src, int n) -> void` | sí | sí | no |
| `__bits_de_float__` | `(float x) -> int` | sí | sí | no |
| `__float_de_bits__` | `(int bits) -> float` | sí | sí | no |

### `sistema/archivos.libsrx`

| Llamada | Firma | Intérprete | VM | Web |
|---|---|---|---|---|
| `__leer_archivo__` | `(str ruta) -> str` | sí | sí | no |
| `__escribir_archivo__` | `(str ruta, str texto) -> void` | sí | sí | no |
| `__existe__` | `(str ruta) -> bool` | sí | sí | no |
| `__crear_carpeta__` | `(str ruta) -> void` | sí | sí | no |
| `__borrar__` | `(str ruta) -> void` | sí | no | no |
| `__renombrar__` | `(str origen, str destino) -> void` | sí | no | no |
| `__modificado__` | `(str ruta) -> int` | sí | no | no |
| `__entradas__` | `(str ruta) -> int` | sí | sí | no |
| `__entrada__` | `(str ruta, int i) -> str` | sí | sí | no |
| `__tamano__` | `(str ruta) -> int` | sí | sí | no |
| `__leer_bytes__` | `(str ruta, byte ptr mutable destino, int n) -> void` | sí | sí | no |
| `__escribir_bytes__` | `(str ruta, byte ptr datos, int n) -> void` | sí | sí | no |
| `__escribir_error__` | `(str texto) -> void` | sí | sí | no |

### `sistema/comandos.libsrx`

| Llamada | Firma | Intérprete | VM | Web |
|---|---|---|---|---|
| `__ejecutar__` | `(str ptr argumentos, int n, str entrada) -> int` | sí | no | no |
| `__salida_ejecutada__` | `() -> str` | sí | no | no |
| `__errores_ejecutados__` | `() -> str` | sí | no | no |

### `sistema/entrada.libsrx`

| Llamada | Firma | Intérprete | VM | Web |
|---|---|---|---|---|
| `__entrada_terminada__` | `() -> bool` | sí | no | no |
| `__leer_linea__` | `() -> str` | sí | no | no |
| `__leer_entrada__` | `() -> str` | sí | no | no |

### `sistema/proceso.libsrx`

| Llamada | Firma | Intérprete | VM | Web |
|---|---|---|---|---|
| `__argumentos__` | `() -> int` | sí | sí | no |
| `__argumento__` | `(int i) -> str` | sí | sí | no |
| `__salir__` | `(int codigo) -> void` | sí | sí | no |

### `sistema/rutas.libsrx`

| Llamada | Firma | Intérprete | VM | Web |
|---|---|---|---|---|
| `__directorio_actual__` | `() -> str` | sí | sí | no |
| `__entorno__` | `(str nombre) -> str` | sí | sí | no |
| `__separador__` | `() -> str` | sí | sí | no |
| `__absoluta__` | `(str ruta) -> str` | sí | sí | no |
| `__normaliza__` | `(str ruta) -> str` | sí | sí | no |
| `__une__` | `(str a, str b) -> str` | sí | sí | no |
| `__carpeta_de__` | `(str ruta) -> str` | sí | sí | no |
| `__nombre_de__` | `(str ruta) -> str` | sí | sí | no |
| `__es_carpeta__` | `(str ruta) -> bool` | sí | sí | no |
| `__es_archivo__` | `(str ruta) -> bool` | sí | sí | no |

### `sistema/tiempo.libsrx`

| Llamada | Firma | Intérprete | VM | Web |
|---|---|---|---|---|
| `__ahora_ms__` | `() -> int` | sí | no | no |
| `__reloj_ns__` | `() -> int` | sí | no | no |
| `__dormir_ms__` | `(int ms) -> void` | sí | no | no |

### `text/main.libsrx`

| Llamada | Firma | Intérprete | VM | Web |
|---|---|---|---|---|
| `__trozo__` | `(str s, int desde, int hasta) -> str` | sí | sí | no |
| `__buscar__` | `(str s, str parte, int desde) -> int` | sí | sí | no |
| `__empieza__` | `(str s, str prefijo) -> bool` | sí | sí | no |
| `__termina__` | `(str s, str sufijo) -> bool` | sí | sí | no |
| `__unir__` | `(str ptr partes, int n, str separador) -> str` | sí | sí | no |
| `__entero_de__` | `(str s) -> int` | sí | sí | no |
| `__flotante_de__` | `(str s) -> float` | sí | sí | no |
| `__utf8_largo__` | `(str s) -> int` | sí | sí | no |
| `__utf8_a_bytes__` | `(str s, byte ptr mutable destino, int n) -> void` | sí | sí | no |
| `__utf8_de_bytes__` | `(byte ptr datos, int n) -> str` | sí | sí | no |
| `__minusculas__` | `(str s) -> str` | sí | no | no |
| `__mayusculas__` | `(str s) -> str` | sí | no | no |
| `__es_digito__` | `(char c) -> bool` | sí | no | no |
| `__es_letra__` | `(char c) -> bool` | sí | no | no |
| `__es_alfanumerico__` | `(char c) -> bool` | sí | no | no |
| `__es_espacio__` | `(char c) -> bool` | sí | no | no |
| `__es_mayuscula__` | `(char c) -> bool` | sí | no | no |
| `__es_minuscula__` | `(char c) -> bool` | sí | no | no |
| `__cuenta_partes__` | `(str s, str separador) -> int` | sí | no | no |
| `__partir__` | `(str s, str separador, str ptr mutable destino, int n) -> void` | sí | no | no |
| `__cuenta_palabras__` | `(str s) -> int` | sí | no | no |
| `__palabras__` | `(str s, str ptr mutable destino, int n) -> void` | sí | no | no |
| `__cuenta_lineas__` | `(str s) -> int` | sí | no | no |
| `__lineas__` | `(str s, str ptr mutable destino, int n) -> void` | sí | no | no |
| `__recorta__` | `(str s) -> str` | sí | no | no |
| `__recorta_inicio__` | `(str s) -> str` | sí | no | no |
| `__recorta_final__` | `(str s) -> str` | sí | no | no |
| `__apariciones__` | `(str s, str parte) -> int` | sí | no | no |
| `__buscar_ultimo__` | `(str s, str parte) -> int` | sí | no | no |

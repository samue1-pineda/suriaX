# `src/classlib/` — una clase de OOP, sin sintaxis nueva

`cuenta.srcx` es una **clase completa** —estado, encapsulación, constructor,
métodos, destructor, `toString` e invariantes— escrita **sin una sola
construcción que suriaX no tuviera ya por otros motivos**.

```
ahorro: 120
saque 30, 2 movimientos
error: fondos insuficientes
[cierre de ahorro]
```

| lo que en otro lenguaje sería… | aquí es |
|---|---|
| `class` + campos | un `struct` |
| `constructor` | una `fn` que devuelve el valor ya válido (y `throw` si no lo es) |
| métodos | un bloque `@impl` con receptor explícito (`self`) |
| `destructor` / `finally` | el hook `__free__`, que corre **solo**, en toda salida del ámbito |
| `toString` | el hook `__print__` |
| `equals` | el hook `__eq__` |
| miembros estáticos | constantes del módulo |

Es el argumento de fondo de `DESIGN_PRINCIPLES`: un `struct` con hooks cubre
lo que una `class` da, y lo hace con piezas que ya existían para otra cosa.

## Lo que NO hay, a propósito

**Herencia y polimorfismo.** Para que el comportamiento varíe en ejecución,
un `enum` y un `match`: el compilador comprueba que las ramas estén cubiertas
(`SEM030`) y no hace falta una tabla de despacho en memoria. Componer y
delegar cubre lo que la herencia sin polimorfismo daba.

## Qué destapó

Escribirlo encontró dos fallos reales del modelo de propiedad, los dos
silenciosos, y los dos ya corregidos:

1. Un `struct` que declara `__free__` **se hace cargo también de sus campos**
   (el compilador deja de bajar a ellos). Olvidar uno era una fuga que nada
   reportaba → ahora avisa con `NOTE002`.
2. Y cumplir esa regla *parecía imposible*: `free c.r` se rechazaba sin decir
   que la salida es `free &c.r` → ahora el diagnóstico escribe la línea.

Es la razón de que este ejemplo esté aquí: un `struct` mal programado no
avisa por sí solo, y la forma de encontrar esos huecos es escribir con él
algo que se parezca a lo que la gente escribe.

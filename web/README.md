# Backend web de suriaX

Target **WebAssembly**, con el módulo **JS/TS** como host. A diferencia del
backend C++ —que baja el HIR a MIR y lo ejecuta en una VM de registros— este consume el
**mismo `.phir`** y baja a WASM por su propio IR. No hay LLVM en medio: el HIR
es la única frontera compartida.

```
  frontend Python              backend web (este paquete)
 ┌────────────────┐   .phir   ┌──────────────────────────────────────────┐
 │ lexer → parser │ ────────▶ │ decodificar   src/hir/                   │
 │ → AST-tipado   │ protobuf  │ ligar         src/hir/link.ts            │
 │ → semántica    │           │ contener      src/target/    WEB0xx      │
 │ → HIR          │ ◀──────── │ optimizar     src/opt/                   │
 └────────────────┘ re-serial │ bajar a WIR   src/wir/       WEB1xx      │
                              │ emitir        src/codegen/               │
                              └───────┬──────────┬───────────┬───────────┘
                                    .wasm      host.js      .wat
```

## Qué hay hoy

| Pieza | Archivo | Qué hace |
|---|---|---|
| Lector de wire-format | [`src/hir/wire.ts`](src/hir/wire.ts) | Decodifica protobuf sin dependencias: varint, 64 bits, UTF-8, campos desconocidos, tope de anidamiento. |
| Escritor de wire-format | [`src/hir/write.ts`](src/hir/write.ts) | La contraparte: omite defectos de proto3, conserva los `oneof`. |
| Modelo del HIR | [`src/hir/schema.ts`](src/hir/schema.ts) | Espejo 1:1 de `hir.proto`; cada `oneof` es una unión discriminada. |
| Deserializador | [`src/hir/decode.ts`](src/hir/decode.ts) | `.phir` → `Module`, con fail-fast de `schema_version`. |
| Re-serializador | [`src/hir/encode.ts`](src/hir/encode.ts) | `Module` → `.phir`. Cierra el ciclo: permite cachear el HIR optimizado y validar el lector contra el protobuf real. |
| Linker de unidades | [`src/hir/link.ts`](src/hir/link.ts) | `Unit`/`Image` e índices de hooks, casts y dunders (espejo del intérprete). |
| Política del target | [`src/target/policy.ts`](src/target/policy.ts) | **Qué** no puede correr el web, como datos. |
| Contención | [`src/target/restrictions.ts`](src/target/restrictions.ts) | La hace cumplir sobre el HIR, con diagnósticos `WEB0xx` posicionados. |
| DCE | [`src/opt/dce.ts`](src/opt/dce.ts) | Elimina código muerto (declaraciones, sentencias, variables). |
| **WIR** | [`src/wir/`](src/wir/) | El IR de WebAssembly: nombres→índices, tipos→i32/i64/f64, librerías→intrínsecos. |
| Backends | [`src/codegen/`](src/codegen/) | `wasm.ts` (binario), `js.ts` (JS puro + host), `wat.ts` (texto legible). |
| Pipeline | [`src/index.ts`](src/index.ts) | `prepare()` y `compile()`: de bytes a artefactos. |
| CLI | [`main.ts`](main.ts) | Inspeccionar, emitir y **ejecutar** desde la terminal. |

## Uso

```bash
node web/main.ts dumps/a.srcx.phir              # resumen + contención + DCE + codegen
node web/main.ts dumps/a.srcx.phir --run        # ejecuta el WebAssembly generado
node web/main.ts dumps/a.srcx.phir --run-js     # ejecuta el backend JS puro
node web/main.ts prog.phir --emit-wasm out.wasm --emit-wat out.wat --emit-js out.mjs
node web/main.ts prog.phir --reencode copia.phir     # re-serializa el HIR
node web/main.ts prog.phir --json                    # para otra herramienta
node web/main.ts prog.phir --no-dce --unrestricted   # sin optimizar, sin contener
```

`--run` respeta el MISMO contrato que `python V0/main.py --run`: por stdout
sale solo lo que el programa imprime y el valor de `main` es el código de
salida. Por eso las dos ejecuciones se pueden comparar byte a byte, que es lo
que hace [`test/e2e/test_web_wasm.py`](../test/e2e/test_web_wasm.py).

Desde código (navegador o node):

```ts
import { prepare, WEB_V1_POLICY } from "./web/src/index.ts";

const result = prepare(bytes, "programa.phir", resolver, { policy: WEB_V1_POLICY });
if (result.image === null) {
  for (const d of result.diagnostics) console.error(d.code, d.message, d.line);
} else {
  // ...codegen
}
```

`resolver` es cómo se consiguen las unidades `.libsrx` referenciadas
(`fetch`, `IndexedDB`, un `Map`, `fs`…): `src/` **no toca el sistema de
archivos**, para que el mismo código corra en el navegador. El único
archivo que usa `node:fs` es el CLI.

## La contención (`WEB_V1_POLICY`)

El target web todavía no ejecuta todo el lenguaje. La lista vive en un solo
sitio ([`policy.ts`](src/target/policy.ts)) y se hace cumplir **antes** del
codegen, no en runtime:

| Código | Construcción | Por qué |
|---|---|---|
| `WEB001` | `#extern cpp { }` | No hay toolchain C++ en el navegador. |
| `WEB002` | `ptr T`, `ptr mutable T` | JS no tiene direcciones. |
| `WEB003` | `&x` | Produce un puntero. |
| `WEB004` | `free x;` | La memoria la gestiona el runtime de JS. |
| `WEB005` | `__free__`, `__sizeof__` | Dependen del runtime nativo. |
| `WEB006` | `move x;` | Exige invalidación en runtime, aún no implementada. |
| `WEB007` | Una librería fuera de la allowlist | Solo si la política declara una; `WEB_V1_POLICY` permite cualquiera y contiene por capacidad. |
| `WEB008` | `sizeof(T)` | Depende del layout nativo. |
| `WEB900`/`WEB901` | `.phir` ilegible / nodo malformado | Errores del lector. |

### Imprimir un valor calculado

`stdp.println(f"total {x}")` **funciona**. No se construye una cadena: el
f-string se convierte en una secuencia de escrituras —texto literal, valor,
texto literal— y cada valor va a la primitiva del host que corresponde a su
tipo (`__write_int__`, `__write_float__`, `__write_bool__`, `__write_char__`),
que es **quien lo formatea**.

Formatear en WebAssembly habría exigido escribir a mano la conversión de
`double` a texto con las reglas de CPython (representación más corta que hace
round-trip, punto decimal siempre presente, exponente de dos dígitos), y una
diferencia de un dígito rompe la comparación con el intérprete. Con el
formateo en el host hay **un solo sitio** que decide cómo se ve un valor
([`src/codegen/runtime.ts`](src/codegen/runtime.ts)), compartido por el
backend JS y por el host del WASM.

Los textos contiguos se funden antes de emitir, así que `println("hola")`
sigue siendo **una** escritura de `"hola\n"`, igual que antes, y los imports
del host se declaran solo si se usan: un programa que únicamente imprime
literales importa una función, no cinco.

Lo que sigue sin soporte es la cadena como **valor** (`var str s = a + b;`,
`cast<str>(x)`): eso sí necesita un runtime de cadenas —memoria dinámica y
concatenación— y da `WEB102` con su posición.

Las construcciones de región no aparecen porque **ya no existen**: se
retiraron del lenguaje en la v0.2.0. El target web no conoce el modelo de
memoria — recibe el HIR ya resuelto.

### Librerías: cualquiera que el target sepa traducir

El lowering baja la **imagen entera** —la unidad principal y sus librerías—,
así que una librería de funciones corrientes (`math`) se traduce como
cualquier otro código y se ejecuta.

Antes solo corría `IO`, y no porque el target no pudiera traducir las demás:
`lowerImage` devolvía `lowerModule(image.main.module)` y las unidades se
tiraban antes de llegar al WIR. Con eso, `WEB007` rechazaba por identidad
("esta librería no") algo que en realidad nunca se había intentado.

Ahora decide la **capacidad**: una librería que usa punteros se rechaza por
`WEB002` señalando la línea exacta, no por llamarse como se llama. `lib/math`
funciona; `lib/mem` y `array.vector` siguen fuera porque usan punteros, y
`d_types` porque declara `__sizeof__`.

`IO` sigue siendo un caso aparte: es una unidad **confiable**, su
implementación la aporta el host (la primitiva `__write__` es la salida del
playground), así que su HIR no se traduce ni se revisa. Por eso `IO.stdp`
puede declarar `fn __print__(String ptr s)` —un puntero— sin violar `WEB002`.
Lo que sí se revisa de una librería confiable son sus propios imports.

Las funciones de una librería viajan al WIR con el nombre **cualificado**
(`math.basic.add`): dos unidades pueden declarar `max`, y el nombre acaba
siendo el del export de WebAssembly, donde repetirlo produce un módulo
inválido. Un identificador de suriaX no puede llevar `.`, así que cualificar
basta para no chocar nunca con un nombre del usuario.

### Habilitar algo

Cuando una capacidad entre en soporte, se deriva la política; no se edita el
verificador:

```ts
const conPunteros = withCapabilities(WEB_V1_POLICY, [Capability.POINTERS]);
const conMath = withUnits(WEB_V1_POLICY, [{ alias: "MATH", hostPrimitives: [] }]);
```

## El WIR (y por qué no es el MIR)

El MIR es del backend **C++** (VM bytecode/JIT): un IR de **registros**, para
una máquina de registros. WebAssembly es otra máquina: una de **pila** con
control de flujo **estructurado**. Dos objetivos distintos piden dos IR
distintos, y forzar uno solo habría dejado a los dos a medias.

```
            HIR (protobuf)
           /              \
    MIR (C++)              WIR (TypeScript)
 registros, CFG            pila, control estructurado
      │                          │
 VM JIT / LLVM             wasm · js · wat
```

Que WASM sea de pila es la razón de la forma del WIR: una función no tiene
destinos, cada instrucción consume lo que hay encima y deja su resultado. Así
que `a + b * 2` **es** su recorrido en post-orden:

```wat
local.get $a   local.get $b   i64.const 2   i64.mul   i64.add
```

Por eso el WIR guarda las expresiones como árbol tipado: emitir es recorrerlo
—sin registros, sin temporales, sin decidir nada—. Aplanarlo a tripletas como
haría un MIR solo serviría para tener que reconstruirlo. Y por eso el control
de flujo, cuando llegue, será `loop`/`if` estructurados y no bloques básicos:
un IR de CFG obligaría a reconstruir la estructura al emitir (*relooping*).

Lo que el lowering resuelve de una vez, para todos los backends:

| HIR | WIR |
|---|---|
| nombres y scopes | índices de local (parámetros primero, como WASM) |
| tipos nominales | `i32` / `i64` / `f64` |
| llamadas por nombre | índices de función |
| librería `IO` | intrínsecos del host (`__write__`) |
| `restype` opcional | tipo resuelto en **todo** nodo |

De ahí salen tres artefactos del mismo árbol: el **binario `.wasm`**, un
**módulo JS host** que lo embebe en base64 y lo instancia, y el **WAT**
legible. El backend de **JS puro** existe además como oráculo: sale del mismo
WIR, así que tiene que dar exactamente el mismo resultado — y la suite lo
comprueba ejecutando los dos.

### Alcance del codegen

Hoy: **variables (locales y de módulo), aritmética, comparaciones, llamadas,
`if`/`else`/`else if`, `while` con `break`/`continue`, `and`/`or`/`not`,
`match`, `cast` entre numéricos, `enum` sin payload, `str` constante como
valor e impresión.** Lo demás da `WEB100`/`WEB101`/`WEB102` con su posición y
**no se emite nada**.

Lo que sigue fuera, y por qué: `struct` y punteros (harían falta memoria
lineal y un asignador, y el target web se declaró **sin gestión de memoria**),
`try`/`catch`/`throw` (necesitan una representación del error), y toda cadena
CALCULADA (concatenar o `cast<str>` piden un runtime de cadenas).

Detalles deliberados:

- Un **`enum` sin payload es un entero con nombre**, así que su item es una
  constante y `match` es una cadena de comparaciones — no un `br_table`, que
  es *denso*: `ROJO = 1, AZUL = 400` habría generado cuatrocientas entradas
  para tres casos. El item CON payload (`Numero(int)`) no se traduce: el enum
  deja de ser un entero y representarlo como tal perdería el dato.
- El **sujeto del `match` se evalúa una vez** y se guarda en un local: es el
  único local que este lowering inventa, y sin él `match (siguiente())`
  llamaría a `siguiente` una vez por caso.
- **`float` -> `int` satura** (`i64.trunc_sat_f64_s`): el `trunc` que trapea
  aborta el módulo entero ante un NaN, y un `cast` no debería poder matar al
  programa. El backend JS hace lo mismo a mano para no discrepar.
- Una **cadena constante es el ÍNDICE de su constante**, no un puntero: así
  cabe en una variable, en un parámetro y en un retorno sin memoria dinámica.
  Como se internan por texto, `==` contesta bien; el ORDEN (`a < b`) no, y por
  eso se rechaza: los índices van por orden de aparición, no alfabético.
- Una **variable de módulo es una global de WASM**, no un local de
  `__module_init`: un local muere con su función y ninguna otra la vería. Un
  `const` del programa sale **inmutable en el binario** —el validador impide
  reasignarla— salvo cuando su valor hay que calcularlo (`const int DOBLE =
  BASE * 2`): WASM solo admite constantes como inicializador, así que arranca
  a cero y `__module_init` se lo asigna.

- `int` es **i64** de verdad (y `BigInt` con envoltura explícita en el backend
  JS): `9007199254740992 + 1` da el valor exacto en los dos.
- **`and`/`or` cortocircuitan de verdad.** En una máquina de pila eso no es un
  operador sino una rama: se emiten como `if (result i32)`. Traducirlos a
  `i32.and` habría evaluado siempre los dos lados y `a() and b()` se
  comportaría distinto que en el intérprete.
- **`while` usa el patrón `block` + `loop`**: el `block` externo es el destino
  de `break` y el `loop` el de `continue`. WASM salta por PROFUNDIDAD
  RELATIVA, no por nombre, así que el emisor lleva una pila de etiquetas y la
  calcula — escribirla a mano falla en cuanto hay un `if` de por medio.
- **Los locales se inicializan explícitamente.** WASM pone a cero los locales
  al entrar en la función, pero un `var` declarado dentro de un bucle se
  declara en cada vuelta: sin un `local.set` explícito conservaría el valor de
  la iteración anterior.
- Las sentencias de nivel de módulo van a un `__module_init` sintético que el
  host llama antes de `main`, para que el orden de ejecución sea el mismo que
  en el intérprete.
- `stdp.println("…")` no compila el cuerpo de la librería (esa unidad es del
  host): pone la cadena en el *data segment* y llama a `__write__(ptr, len)`,
  el mismo contrato de `lib/io/stdp.libsrx`.

Los tres emisores llevan una **guarda de exhaustividad**: si el WIR gana una
variante y algún backend no la traduce, falla en voz alta. Se añadió después
de que `logical` llegara al WIR y a dos de los tres emisores — el binario
salía mal formado y ningún `switch` de casos `void` se quejaba.

## El DCE

Cuatro eliminaciones, todas conservadoras:

1. **declaraciones inalcanzables** desde las raíces (entrada, sentencias de
   módulo, hooks, exports usados por otras unidades);
2. **código tras un terminador** (`return`/`break`/`continue`/`throw`);
3. **expresiones-sentencia sin efectos** (`x + 1;`);
4. **variables locales nunca leídas** con inicializador puro.

Se repite hasta punto fijo. Lo que **no** hace: plegar condiciones
constantes, ni suponer pureza. Toda llamada es impura, y también lo es todo
lo que pueda despachar un hook de usuario (`v[i]` → `__index__`, `a == b`
entre nominales → `__eq__`, `cast<T>` con `__cast__`). Un DCE equivocado no
"optimiza de más": borra un `print`.

Entre unidades, las raíces son **nombres** (una llamada es `stdp.println`),
así que dos funciones homónimas en unidades distintas se conservan juntas.
Sobra código, no falta.

La contención corre **antes** del DCE a propósito: si corriera después, el
DCE podría borrar la función que contenía la construcción no soportada y el
mismo programa se aceptaría o rechazaría según el nivel de optimización.

## Pruebas

```bash
cd web && node --test "test/*.test.ts"     # 81 pruebas
cd web && tsc --noEmit                     # verificación de tipos
python test/main.py                        # las corre también desde la suite del repo
```

Tres niveles, y cada uno cubre lo que los otros no pueden:

1. **`test/web/`** — el lector contra `.phir` reales, la ida y vuelta del
   re-serializador, y el codegen **ejecutando** lo que genera (el propio motor
   de WebAssembly es el mejor validador de un binario).
2. **`test/unit/test_web_backend.py`** — engancha la suite de TS a la del repo
   y valida el re-serializador contra el `google.protobuf` **real**: allí el
   escritor y el lector son míos y podrían compartir un malentendido; el
   descriptor generado del `.proto` no.
3. **`test/e2e/test_web_wasm.py`** — prueba **diferencial**: el mismo programa
   ejecutado por el intérprete, por el WebAssembly y por el JS tiene que dar
   la misma salida y el mismo valor. Ya encontró dos fallos reales.

Los `.phir` de [`test/web/fixtures/`](../test/web/fixtures/) son **bytes reales**
emitidos por el compilador Python a partir de
[`prog.srcx`](../test/web/fixtures/prog.srcx); se regeneran con
`python V0/main.py prog.srcx --emit-hir`. Probar el lector solo contra un
codificador propio no demostraría nada: los fixtures son la prueba de que
entiende el formato de verdad.

## Restricciones del paquete

- **Cero dependencias.** Sin `package.json`, sin `npm install`. `node`
  ejecuta los `.ts` borrando los tipos; `tsc` solo verifica.
- **`src/` no importa nada de node** (lo vigila un test de la suite Python).
- **Nada de sintaxis no borrable**: sin `enum`, sin `namespace`, sin
  parameter properties — `erasableSyntaxOnly` lo impone.
- `web/node.d.ts` declara a mano lo poquito que el CLI y las pruebas usan de
  node, en vez de arrastrar `@types/node`.
- `.web/` (en la raíz, ignorada por git) es para dumps y caché del compilador web, no para código.

# HTIMS — *hooks / traits / intrinsics management system*

La capa que corre **antes del análisis léxico** y responde una sola pregunta:
*¿este proyecto extiende el lenguaje, y con qué?*

Su razón de ser, en una frase: **que los hooks dejen de ser funciones
especiales creadas por el compilador y pasen a ser vocabulario que declara el
usuario.** Hoy `__print__`, `__len__` o `__cast__` existen porque están
escritos en `V0/src/frontend/semantic/hooks.py`; con HTIMS, `__gravity__`
existe porque *tu proyecto* lo declara.

```
config (.suriaX_config.yaml, define _root)
        │
        ▼
   ┌──────────┐   extends.srcx  ──►  calls_dir/*.py   (ast.parse, NUNCA import)
   │  HTIMS   │                 ──►  logic_dir/*.cpp  (llega con la VM+JIT)
   └──────────┘
        │  ExtensionSet
        ▼
  source_reader ──► Lexer ──► Parser ──► Semántica ──► HIR ──► { intérprete | MIR }
```

## Estado

**Funciona de punta a punta para hooks.** Un hook declarado por el proyecto se
descubre, **amplía el vocabulario de la Semántica**, se valida contra la firma
que prometió la extensión, viaja en el `.phir` con su nombre y su procedencia,
y el intérprete lo ejecuta:

```srcx
// juego.srcx — con extensions/calls/physics.py declarando __gravity__
hook fn __gravity__(Body ptr mutable b, int dt) -> void {
    b.vy = b.vy - 10 * dt;
}

fn main() -> int {
    var Body b = Body{ vy: 20 };
    b.__gravity__(1);     // ejecuta, y la mutación se propaga
    return b.vy;          // 10
}
```

El **mismo archivo en un proyecto sin esa extensión no compila** (`SEM018`):
el vocabulario es del proyecto, no del compilador. Y si la firma no coincide
con la declarada, el diagnóstico dice exactamente en qué y quién la prometió.

Lo que aún no ejecuta es la **lógica C++** de `logic_dir`: hoy el cuerpo del
hook se escribe en suriaX. Ligar `logic="gravity_cpp"` a su símbolo nativo
llega con la VM+JIT (ver *Qué falta*).

## El manifiesto: `extends.srcx`

Vive en la **raíz del proyecto**, junto al `.suriaX_config.yaml`. Si no
existe, el proyecto no tiene extensiones: la capa cuesta un `stat` y no dice
nada.

```
# extends.srcx
project:   MiJuego
logic_dir: extensions/logic     # C++: la LÓGICA
calls_dir: extensions/calls     # Python: las DECLARACIONES
```

| clave | obligatoria | qué es |
|---|---|---|
| `calls_dir` | sí | directorio con los `.py` que **declaran** los hooks |
| `logic_dir` | no | directorio con la **lógica** C++ que los implementará |
| `project` | no | respaldo del nombre si ningún `.py` lo declara |

`logic_dir` es opcional a propósito: la lógica nativa solo puede existir
cuando exista la VM+JIT, y un proyecto que ya declara sin implementar tiene
que poder compilar.

**Es un formato de configuración, no código suriaX** — la extensión `.srcx`
es cosmética. Lo lee `manifest.py` con un parser propio de ~100 líneas, no el
`Lexer` del lenguaje: esta capa corre *antes* del léxico, así que usarlo sería
circular, y las tres claves no justifican meter directivas nuevas en la
gramática. A cambio, cada diagnóstico sale con línea y columna reales.

## La declaración: Python que no se ejecuta

```python
# extensions/calls/physics.py
from htims import signature

PROJECT = "MiJuego"

@signature("__gravity__", owner="Body",
           params=["Body ptr mutable", "float"], returns="void")
def gravity(body, dt):
    body.vy = body.vy - 9.8 * dt      # implementación de referencia
```

## Dos decoradores: bajar a C++ se escribe

La línea que los separa es una sola pregunta: **¿el hook necesita salir del
proceso?** `@signature` declara el que se resuelve dentro del lenguaje —opera
sobre valores de suriaX y su cuerpo Python es la referencia—; pedirle lógica
nativa es `EXT028`.

`@signature_extends` declara el que sí la necesita (una ventana, un descriptor
del sistema, memoria cruda) y **exige decirlo**: `cxx=True` no tiene valor por
defecto, y sin él la declaración se rechaza (`EXT029`).

```python
@signature_extends("__win_open__", owner="Ventana",
                   params=["int", "int"], returns="Ventana ptr mutable",
                   cxx=True, logic="win_open_cpp")
def win_open(w, h):
    raise NotImplementedError("lo implementa logic_dir/win_open.cpp")
```

El opt-in **es** la verificación. Un hook que baja a C++ deja de ser
comprobable por el compilador —su cuerpo vive fuera de su alcance—, así que
sacarlo del lenguaje tiene que ser una decisión escrita y no lo que ocurre al
copiar una declaración de otro sitio. Por eso `logic` sin `cxx=True` no es un
descuido que se perdone: es un error con su posición.

`@hook` es el nombre anterior de `@signature` y sigue importando para no
romper extensiones ya escritas. Se escanea con las reglas nuevas, así que
tampoco por ahí se cuela un C++ implícito.

El compilador **nunca importa este archivo**: lo lee con `ast.parse` y mira la
forma del decorador (`declarations.py`). Compilar un `.srcx` no debe ejecutar
el `.py` de nadie — está fijado por dos tests (uno unitario y uno por la CLI
real) que ponen un efecto secundario en el archivo y comprueban que no ocurre.

Corolario: **todo argumento del decorador es un literal**. `owner=NOMBRE`
calculado no es declarable (`EXT025`); no es una limitación del parser, es la
condición para no ejecutar nada.

La firma se escribe en tipos del **lenguaje** (`"Body ptr mutable"`), no de
Python, porque su destinatario es la Semántica de suriaX: es la firma que
tendrá que validar contra el `hook fn __gravity__(...)` escrito en `.srcx`.
Aquí solo se comprueba que esté presente y sea una cadena — parsear el tipo es
del frontend, que es quien tiene la gramática.

Los decoradores existen de verdad (`decl.py`) para que el archivo sea Python
legítimo: importable, comprobable por un linter y ejecutable por los tests del
propio usuario. No registran nada en ninguna tabla global; solo anotan la
función. El registro real pertenece a la VM+JIT.

## Configuración a mano

Las extensiones también se declaran sin manifiesto, directamente en el yaml:

```yaml
# .suriaX_config.yaml
project: "MiJuego"
extensions:
  - path: "plugins/physics.py"
```

Ambas fuentes se validan igual y se funden en un solo `ExtensionSet` (el mismo
archivo por las dos vías cuenta una sola vez). El **nombre del proyecto lo
declara la extensión** (`PROJECT` en su `.py`, no el nombre de los archivos);
el manifiesto es el respaldo y el yaml el último recurso, para proyectos que
no declaran ninguna.

El compilador **no reescribe tu yaml**: completa la configuración en memoria.
`python V0/main.py --emit-extensions` muestra las líneas exactas que puedes
copiar si las quieres fijadas en el archivo.

## Consultar lo descubierto

```
python V0/main.py --emit-extensions            # raíz = directorio actual
python V0/main.py juego.srcx --emit-extensions # raíz = la del proyecto del .srcx
```

Emite en stdout un JSON con el proyecto, los módulos, cada hook con su firma y
su posición, y las `config_entries` equivalentes. Sin extensiones emite un
objeto vacío, no un error.

## Severidad: todo `EXT0xx` es crítico

Un manifiesto malformado o un directorio que no existe **detiene la
compilación** (exit code `4`) antes de tokenizar una línea. El vocabulario del
lenguaje depende de esto: compilar contra un conjunto de extensiones a medias
reportaría en el `.srcx` errores que en realidad son del manifiesto, y el
usuario buscaría el problema en el sitio equivocado.

La única excepción es el canal del editor (`--emit-diagnostics`), que reporta
los `EXT0xx` con la ruta del manifiesto **y sigue analizando el buffer**:
apagarle los diagnósticos a alguien que está justo arreglando algo sería
hostil.

| código | causa |
|---|---|
| `EXT001` | el manifiesto no se pudo leer (I/O, no UTF-8) |
| `EXT002` | línea malformada (no es `clave: valor` ni comentario) |
| `EXT003` | un directorio declarado no existe |
| `EXT004` · `EXT005` · `EXT006` | clave desconocida · duplicada · sin valor |
| `EXT007` | falta una clave obligatoria |
| `EXT010` · `EXT011` | el `.py` no existe · no es Python válido |
| `EXT012` | dos `PROJECT` con valores distintos |
| `EXT020`–`EXT023` | nombre, `owner`, `returns` o `params` mal declarados |
| `EXT024` | el mismo `(dueño, hook)` declarado dos veces |
| `EXT025` | argumento no literal (el escaneo no ejecuta código) |
| `EXT026` | argumento desconocido en el decorador |
| `EXT027` | colisión con el vocabulario fijo del compilador |
| `EXT028` | una firma PURA pide lógica nativa (C++ negado por defecto) |
| `EXT029` | contrato con C++ incompleto: falta `cxx=True` o falta `logic` |

## Fronteras

Son la parte del diseño que más conviene respetar:

- **`htims/` no importa nada de `V0/` ni de `config/`.** Sobrevive a un
  rediseño del frontend, y el frontend compila igual sin este paquete. La
  comprueba un test sobre el propio código fuente
  (`test_htims_no_importa_el_frontend`).
- **Sus diagnósticos no heredan de `error_handler`**: reproducen su contrato
  (`.code`, `.message`, `.loc`, `.to_dict()`), así que el log, la consola y el
  canal del LSP los tratan igual sin que exista la dependencia.
- **El vocabulario fijo está duplicado** en `declarations.RESERVED_HOOKS` —
  importarlo cruzaría la frontera. Un test compara esa tupla contra
  `HOOK_SPECS` y falla si alguien añade un hook y olvida este archivo: la
  frontera la paga el test, no el módulo.
- **El backend web no conoce ni llama esta capa.** Los campos que el HIR gana
  son aditivos y su decodificador ya salta los tags que no conoce.
- **El nombre del proyecto y la lista de extensiones no viajan en el `.phir`.**
  Describen el proyecto, no la unidad, y no hacen falta para ejecutar ni para
  bajar a MIR. Lo único que el HIR necesita de un hook de usuario es su
  identidad.

## Cómo se dispara un hook de usuario

Los hooks del vocabulario fijo los dispara la SINTAXIS (`print(x)`, `x[i]`,
`a == b`). Uno declarado por tu proyecto no puede: el compilador no sabe qué
significa `__gravity__`, así que no hay sintaxis que reservarle. Se invoca
**como un método**, por su nombre:

```srcx
b.__gravity__(dt);
```

Es la misma forma que un `dunder`, y la diferencia está en lo que el
compilador hace con ella: un `dunder` es un método libre que nadie verifica;
un hook declarado tiene un **contrato** —la firma que prometió la extensión—
y el compilador lo hace cumplir. Cuando exista la VM+JIT, esa misma llamada
podrá ligarse a la lógica de `logic_dir` sin tocar el `.srcx`.

## Cómo viaja un hook de usuario en el HIR

El vocabulario fijo cabía en un `enum` (`HookKind`); un nombre que nadie
conoce al compilar el esquema, no. Por eso:

- `HookKind.EXTENDED = 100` marca «el nombre manda», y `hook_name` lo lleva;
- la clave de despacho pasa de `(dueño, kind)` a `(dueño, kind, nombre)`, con
  `nombre == ""` en **todo** hook del vocabulario fijo;
- `HookEntry.extension` guarda de qué extensión salió, para que un diagnóstico
  pueda decirlo.

Es **aditivo**: ningún tag reasignado, `schema_version` sigue en 1, y un
`.phir` emitido antes se indexa exactamente igual. La clave la construye un
único sitio (`runtime/interpreter/hook/dispatch.hook_key`), que es lo que
permitió ampliarla sin revisar cada lectura del evaluator.

## Qué falta

En orden de dependencia:

1. ~~**Sembrar el vocabulario de la Semántica**~~ ✅ hecho. El vocabulario
   dejó de ser una constante de módulo: lo construye `SemanticContext` para
   CADA compilación (`semantic/extensions.py`), así que dos proyectos abiertos
   a la vez no se contaminan. La firma declarada se **parsea con la gramática
   real** del lenguaje y se compara tipo a tipo, no como texto.
   Queda un fleco: `--emit-lang-info` sigue publicando solo el vocabulario
   fijo, así que el LSP no autocompleta los hooks del proyecto.
2. **Traits e intrínsecos declarados** (la *T* y la *I* de HTIMS). Un trait
   declarado en Python evita tener que escribir el contrato en un `.libsrx`;
   un intrínseco declarado aquí es la vía uniforme a lo que hoy se registra a
   mano en `runtime/interpreter/intrinsics.py`.
3. **`logic_dir` compilado de verdad**: descubrir sus `.cpp` con
   `suriax_add_native_module()` (el descubrimiento por convención de
   `CMake/SuriaXDiscover.cmake` ya hace exactamente esto para `runtime/`) y
   ligar `logic="gravity_cpp"` a su símbolo nativo.
4. **Registro en runtime**, cuando exista la VM+JIT: importar la extensión y
   ligar el callable —o su lógica C++— al despacho. Es el único paso que
   ejecuta código del usuario, y ocurrirá en tiempo de *ejecución*, no de
   compilación.

## Mapa del módulo

| archivo | responsabilidad |
|---|---|
| `manifest.py` | parser de `extends.srcx` con línea/columna |
| `declarations.py` | escaneo `ast.parse` de los `.py` → `HookDecl` |
| `registry.py` | `ExtensionSet`: fusión de fuentes, índices, serialización |
| `decl.py` | los decoradores `@signature` / `@signature_extends` |
| `utils/` | herramientas para quien ESCRIBE hooks (ver su `readme.md`) |
| `errors.py` | familia `EXT0xx` |
| `__init__.py` | `discover(config)` — la puerta que usa el compilador |

Pruebas: `test/unit/test_htims_manifest.py`, `test_htims_declarations.py`,
`test_htims_registry.py`, `test_hook_dispatch_key.py` y
`test/e2e/test_extensions.py`.

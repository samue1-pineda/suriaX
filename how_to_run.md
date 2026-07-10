# Cómo ejecutar un archivo

Guía de cómo se ejecuta un archivo `.srcx`(Pre-Alpha) y cómo se
ejecutará a futuro. Para la arquitectura interna ver
[ARCHITECTURE.md](ARCHITECTURE.md).

---

## 1. Estado actual (Pre-Alpha)

Hoy lo único funcional es el **front-end léxico**. El compilador puede leer un
`.srcx`, tokenizarlo y volcar los tokens. No hay aún parser/AST/HIR/backend.

### Requisitos

- **Python 3.10+** 
- Para *solo lexar* **NO** hace falta ninguna dependencia externa (ni LLVM, ni
  protobuf, ni pyyaml)

### Entrypoint: `V0/main.py`

```bash
# tokenizar un archivo .srcx
python V0/main.py archivo.srcx

# verificar las dependencias del compilador (no aborta)
python V0/main.py --check

# generar el formato de compilación por defecto (.suriaX_config.yaml)
python V0/main.py --init-config
```

`main.py`:

1. añade `V0/` a `sys.path` (no necesitas configurar `PYTHONPATH`);
2. verifica las dependencias que la **fase actual** necesita (hoy: ninguna
   obligatoria para lexar) y **aborta con un mensaje claro** si falta algo;
3. decodifica el `.srcx` a Unicode → tokeniza → si el archivo empieza con
   `#test lexer`, vuelca los tokens; si no, los vuelca en modo directo;
4. reporta los errores léxicos recuperados al final.

**NOTA:* *este paso a paso se guarda para **futuro** ya que *la version actual esta incompleta* 

Códigos de salida: `0` ok · `1` errores léxicos · `2` archivo no encontrado ·
`3` dependencia faltante.

### Alternativa: el script de prueba del lexer

```bash
python V0/test/lexer/run_lexer.py [archivo.srcx]   # usa sample.srcx por defecto
```

Equivalente a `main.py` para un `.srcx`, pensado como banco de pruebas del
lexer. Ver [V0/test/lexer/README.md](V0/test/lexer/README.md).

### La directiva `#test lexer`

Si un `.srcx` empieza con `#test lexer`, el parser (que hoy *solo recibe
tokens*) vuelca el arreglo completo de tokens a consola:

```
#test lexer
int a = 10;
printf("hola{a}");
```

→ `DIRECTIVE('test')` `IDENTIFIER('lexer')` `INT('int')` `IDENTIFIER('a')`
`ASSIGN` `INT_LIT(10)` `SEMICOLON` `IDENTIFIER('printf')` `L_PAREN`
`STRING_LIT(Str(['hola', Interp('a')]))` `R_PAREN` `SEMICOLON` `EOF`

> **NOTA**: `printf` **no** es una palabra reservada. Por la filosofía libsrX
> (pocos tokens, casi todo viene de librerías nativas) es un `IDENTIFIER`. El
> `;` es el terminador de sentencia obligatorio.
>
> Ojo con la distinción **tipo vs literal**: `int` (la palabra clave de tipo) es
> el token `INT`, mientras que `10` (el literal) es `INT_LIT`. Igual para
> `float`/`FLOAT_LIT`, `char`/`CHAR_LIT` y `str`/`STRING_LIT`.

---

## 2. Cómo se ejecutará a futuro (compilador completo)

A futuro, `V0/main.py` (o el binario distribuido `suriaX`) orquestará el
pipeline completo descrito en [ARCHITECTURE.md](ARCHITECTURE.md)

### Selección de target

El backend C++ consulta `compilerconfig` y emite el artefacto según la
plataforma/flag:

| Flag        | Target | Artefacto | Paso final |
|-------------|--------|-----------|------------|
| `IS_WEB`    | wasm   | `.wasm`   | (playground) |
| `IS_WIN32`  | native | `.exe`    | linker      |
| `IS_LINUX`  | native | `.o`      | **linker** → ejecutable |

> En Linux el backend produce un `.o`; un paso de **linker** (etapa final dentro
> del backend C++) lo enlaza para generar el ejecutable. `compilerconfig` aporta
> las rutas/flags del linker.

### Forma de invocación prevista

```bash
# compilar a nativo (según plataforma)
suriaX build archivo.srcx -o programa

# compilar a WebAssembly (playground / target web)
suriaX build archivo.srcx --target wasm

# visualizar la salida de una etapa concreta (objetivo educativo del lenguaje)
suriaX inspect archivo.srcx --stage hir
```

*(La CLI definitiva puede cambiar; esto refleja la intención de diseño.)*

### Configuración de compilación: `.suriaX_config.yaml`

El formato de compilación es un YAML con la información que el backend necesita
para compilar de verdad. Genéralo con `python V0/main.py --init-config`. Esquema
actual:

```yaml
version: 1
target: native              # native | wasm
platform: linux             # win32 | linux | macos
optimization: O0            # O0 | O1 | O2 | O3

toolchain:                  # rutas que el backend C++ usa para compilar/enlazar
  llvm_required_major: 22
  llvm_path: ""             # o la env var LLVM_PATH
  llvm_config: ""           # detectado vía 'llvm-config'
  llvm_include: ""          # headers de LLVM
  linker: ""                # ld.lld / lld / link ... (detectado)
  sysroot: ""               # o la env var SURIAX_SYSROOT

codegen:                    # target detallado
  triple: x86_64-unknown-linux-gnu
  arch: x86_64
  artifact: o               # o | exe | wasm
  wasm:
    enabled: false
    stack_size: 1048576
    export_all: false

visualization:              # objetivo educativo: qué etapas volcar
  stages: []                # tokens | ast | hir | mir | llvm-ir
  format: text              # text | json | dot
  output_dir: viz

libraries:                  # búsqueda de .libsrx y bindings C++
  libsrx_paths: ["./lib", "./libsrx"]
  extern_cpp_include: []
  bindings: []

paths:
  input: ""
  output: out
flags:
  is_web: false
```

> Muchos campos (`llvm_config`, `llvm_include`, `linker`, `triple`, `arch`) se
> **autodetectan** al generar el archivo; puedes sobreescribirlos a mano.

---

## 3. Dependencias del compilador (build desde fuente)

El **usuario final no las necesita** el binario distribuido las trae resueltas.
Importan al construir/ejecutar el compilador desde el código:

| Dependencia | Uso | Instalación |
|-------------|----------|-------------|
| **LLVM-22** | backend / generación de LLVM IR | gestor del sistema (apt/pacman/brew) o `LLVM_PATH`; se detecta con `llvm-config` |
| **protobuf** | serialización del HIR (Python ↔ C++) | `pip install protobuf` |
| **pybind11** | bindings C++ (incl. `#extern cpp{}`) | `pip install pybind11` |
| **pyyaml** | formato de compilación `.suriaX_config.yaml` | `pip install pyyaml` |

Instalación conjunta:

```bash
pip install -r V0/requirements.txt
```

Verificación:

```bash
python V0/main.py --check
#tambien 
python V0/compilerconfig.py
```

Si falta una dependencia **necesaria para la operación solicitada**, el
compilador aborta con un mensaje que indica qué falta y cómo instalarlo. Las
fases que no la necesitan (p. ej. el lexer, que no usa LLVM) siguen funcionando.

> **Nota sobre LLVM:** se exige exactamente **LLVM-22**. `--check` valida la
> versión vía `llvm-config --version`; si tienes otra (p. ej. 21 o 23), lo
> reportará como incompatible aunque LLVM esté instalado.

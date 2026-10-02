# `CMake/` — cómo se compila el lado nativo de suriaX

Guía de todo lo que se construye con CMake: qué objetivos hay, cómo
compilarlos en Linux, macOS y Windows, qué reglas no se negocian y cómo
añadir un binario nuevo sin romperlas.

El compilador en sí (frontend, intérprete, target web) es Python y
TypeScript y **no necesita CMake**. CMake construye dos cosas opcionales:

| Objetivo | Qué es | Para qué |
|---|---|---|
| `suriax-hir` | Ejecutable del **backend C++**: lee el `.phir`, lo resuelve, lo baja al MIR, lo verifica y lo ejecuta en la VM de registros | `suriax-hir prog.phir --run`, el diferencial VM ↔ intérprete, el banco de medida |
| `suriax_hir` | Librería estática con todo lo anterior | La enlaza el CLI; la enlazará el JIT |
| `suriax-native` | Módulos de **Python** en C++ (pybind11) de `runtime/*/` (hoy `memory_c`) | Memoria nativa del intérprete |
| `suriax-test` | Compila lo anterior y corre `test/main.py` | La suite desde CMake |

---

## 1. Compilar

### Lo mínimo

```bash
cmake -S . -B build -DSURIAX_BUILD_NATIVE=OFF
cmake --build build --target suriax-hir
./build/bin/suriax-hir --help
```

El backend **no tiene dependencias**: solo un compilador de C++20 y CMake
3.20 o más. `SURIAX_BUILD_NATIVE=OFF` apaga los módulos de Python, que sí
necesitan Python con pybind11; sin esa opción CMake los busca y, si no están,
lo dice y sigue.

Después, para que las pruebas usen ese binario:

```bash
python test/main.py backend      # el diferencial; busca build/bin/suriax-hir
SURIAX_HIR_BIN=/otra/ruta/suriax-hir python test/main.py backend
```

### Linux y macOS

```bash
cmake -S . -B build -G Ninja -DCMAKE_BUILD_TYPE=Release
cmake --build build -j
```

GCC 10+, Clang 12+ o Apple Clang 13+. Sin `-G Ninja` usa Make, igual de
válido.

### Windows

La combinación que funciona es **MSVC + Ninja desde un entorno de
Visual Studio**. `cl.exe` no está en el `PATH` de una terminal normal: hay
que cargar el entorno antes, con la *Developer PowerShell* o con
`vcvars64.bat`:

```bat
call "C:\Program Files\Microsoft Visual Studio\<versión>\Community\VC\Auxiliary\Build\vcvars64.bat"
cmake -S . -B build -G Ninja -DCMAKE_CXX_COMPILER=cl -DCMAKE_BUILD_TYPE=Release -DSURIAX_BUILD_NATIVE=OFF
cmake --build build --target suriax-hir
build\bin\suriax-hir.exe --help
```

Trampas conocidas, todas vistas en la práctica:

- **Un `clang++` suelto en el `PATH`** (el de LLVM para Windows, sin
  configurar) apunta por defecto a `i686-pc-windows-msvc`, 32 bits, y
  enlaza con el `link.exe` que encuentre primero, que puede ser **el de
  Git** (una herramienta de Unix que no tiene nada que ver). El síntoma es
  un error de enlace incomprensible. Usar `cl` desde `vcvars64`, o pasar
  `--target=x86_64-pc-windows-msvc` a Clang a propósito.
- **La pila del proceso.** Windows da 1 MB a la pila principal y la VM
  ejecuta cada llamada de suriaX como una llamada de C++: sin más espacio,
  una recursión de unos 790 niveles tumbaba el proceso con `0xC00000FD` en
  vez de dar el error controlado (`RT019`, a 4096 marcos). El objetivo
  `suriax-hir` se enlaza con 16 MB (`/STACK:16777216` en MSVC). Un binario
  nuevo que ejecute código de suriaX necesita lo mismo (ver §3).
- **Enlaces simbólicos.** Crear uno exige un privilegio que un usuario
  normal no tiene (WinError 1314). Las pruebas copian `lib/` cuando no
  pueden enlazarla; un script nuevo tiene que hacer lo mismo.
- El **código de salida** de un proceso es de 32 bits en Windows y de 8 en
  POSIX: `main` devolviendo 671 sale como 671 en uno y como 159 en el otro.

### Opciones

| Opción | Por defecto | Qué hace |
|---|---|---|
| `SURIAX_BUILD_BACKEND` | `ON` | Construye el backend C++ (`suriax-hir`) |
| `SURIAX_BUILD_NATIVE` | `ON` | Construye los módulos de Python de `runtime/*/` |
| `SURIAX_SANITIZE` | — | Instrumenta el backend: `address`, `undefined` o `address;undefined` (ver abajo) |
| `SURIAX_SKIP_MODULES` | — | Carpetas de `runtime/` que no se construyen (`-DSURIAX_SKIP_MODULES=logic_mem`) |
| `SURIAX_NATIVE_OUTPUT_IN_MODULE_DIR` | `ON` | Deja cada `.so`/`.pyd` en `runtime/<módulo>/build/`, donde lo busca `runtime/cxx_api.py` |
| `CMAKE_BUILD_TYPE` | `RelWithDebInfo` | Si no se da uno, se elige este y se avisa: sin tipo, CMake compila sin optimizar |
| `Python3_EXECUTABLE` | el del venv, si hay | El Python con el que se construyen los módulos (tiene que ser el mismo que los importa) |

Al configurar, CMake imprime un resumen con lo que va a construir y lo que
omitió, y por qué.

### Un build de diagnóstico: sanitizadores

Un error de memoria en la VM puede dar la salida correcta por casualidad y
pasar todas las pruebas. Un build instrumentado lo convierte en un aborto con
la línea exacta:

```bash
# Linux / macOS (GCC o Clang): ASan + UBSan
cmake -S . -B build-asan -DCMAKE_BUILD_TYPE=Debug -DSURIAX_BUILD_NATIVE=OFF \
      -DSURIAX_SANITIZE="address;undefined"
cmake --build build-asan --target suriax-hir
SURIAX_HIR_BIN=build-asan/bin/suriax-hir python test/main.py backend
```

```bat
:: Windows (MSVC, desde vcvars64): ASan + los iteradores verificados de Debug
cmake -S . -B build-asan -G Ninja -DCMAKE_CXX_COMPILER=cl -DCMAKE_BUILD_TYPE=Debug ^
      -DSURIAX_BUILD_NATIVE=OFF -DSURIAX_SANITIZE=address
cmake --build build-asan --target suriax-hir
set SURIAX_HIR_BIN=build-asan\bin\suriax-hir.exe
python test\main.py e2e
```

```bat
:: Windows: UBSan con Clang (MSVC no lo tiene). Sin el runtime de UBSan para
:: x64, SURIAX_SANITIZE_TRAP=ON detiene el programa sin decir qué regla rompió.
cmake -S . -B build-ubsan -G Ninja -DCMAKE_CXX_COMPILER=clang++ ^
      -DCMAKE_CXX_FLAGS=--target=x86_64-pc-windows-msvc -DCMAKE_LINKER_TYPE=MSVC ^
      -DCMAKE_BUILD_TYPE=Debug -DSURIAX_BUILD_NATIVE=OFF ^
      -DSURIAX_SANITIZE=undefined -DSURIAX_SANITIZE_TRAP=ON
cmake --build build-ubsan --target suriax-hir
```

Lo mismo, automatizado y con su informe:
`python docs/quality/tools/quality.py sanitizers` (ver
[docs/quality/normas/cpp.md](../docs/quality/normas/cpp.md)).

- **UBSan aborta** ante el primer hallazgo (`-fno-sanitize-recover=all`). Un
  aviso en stderr con la prueba en verde no probó nada.
- **MSVC no tiene UBSan.** Se avisa al configurar. Su build Debug trae los
  **iteradores verificados** de la STL, que atrapan un índice fuera de rango
  en un `std::vector`. El `/RTC1` de Debug se quita porque no convive con
  ASan.
- **En Windows** la DLL de ASan (`clang_rt.asan_*_dynamic-x86_64.dll`) está
  en el `PATH` solo dentro del entorno de `vcvars64`. Hay que correr las
  pruebas desde ahí.
- **ASan agranda cada marco de pila.** En Linux, `ulimit -s 65536` antes de
  correr, igual que la CI.
- **La CI tiene un job `sanitizadores`** que corre las pruebas e2e contra
  este build en cada cambio.

### El editor (clangd, VS Code)

La configuración exporta `compile_commands.json` en el directorio de build
(`build/compile_commands.json`). Sin él, clangd no sabe dónde están los
headers y marca errores que no existen ("`suriax/hir/view.hpp` no
encontrado"). Hay que decirle dónde está, con
`--compile-commands-dir=build` o con un enlace en la raíz. El generador de
Visual Studio (`-G "Visual Studio 17 2022"`) **no** lo exporta; Ninja y Make
sí.

---

## 2. Reglas que no se negocian

### Un solo estándar de C++: C++20

Todo lo que se compila en el proyecto usa el **mismo** estándar:
- el backend;
- los módulos de Python;
- los bloques `#extern cpp` que compila el intérprete al vuelo.

La fuente única es `CXX_STANDARD` en [`version.py`](../version.py). De ahí lo
leen dos consumidores:

- **El `CMakeLists.txt` raíz** lo aplica con `CMAKE_CXX_STANDARD`,
  `CMAKE_CXX_STANDARD_REQUIRED ON` y `CMAKE_CXX_EXTENSIONS OFF`. Sin
  extensiones, `gnu++20` no cuenta como C++20, y GCC, Clang y MSVC compilan
  el mismo lenguaje.
- **[`runtime/extern_cpp.py`](../runtime/extern_cpp.py)** lo pasa como
  `-std=c++20`.

No es una opción. Si se pasa `-DSURIAX_CXX_STANDARD=23`, la configuración se
detiene con un error.

Dos estándares en el mismo proceso es un conflicto que **compila** y falla
después, lejos de su causa. Por ejemplo, un `std::string` o un
`std::optional` con otra disposición al cruzar de un módulo a otro. Migrar el
proyecto entero a otro estándar se hace cambiando `version.py`, en un único
commit, con la suite completa en verde.

### Sin dependencias externas en el backend

El backend lee el HIR con un modelo C++ **generado** desde el `.proto`,
[`backend/include/suriax/hir/hir_modelo.hpp`](../backend/include/suriax/hir/hir_modelo.hpp).
Lo genera
[`backend/tools/gen_hir_cpp.py`](../backend/tools/gen_hir_cpp.py) y **se
guarda en el repositorio**, así que construir no necesita ni `protoc` ni
Python.

- Cuando cambia `V0/src/HIR/proto/hir.proto`, se regenera y se hace commit de
  los dos juntos:

  ```bash
  python backend/tools/gen_hir_cpp.py           # regenera
  python backend/tools/gen_hir_cpp.py --check   # ¿está al día? (lo usa la suite)
  ```

- Si el `.proto` es más nuevo que el modelo, CMake avisa al configurar.
- La prueba `test/unit/test_modelo_hir_cpp.py` regenera el modelo en memoria
  y lo compara con el guardado byte a byte. No necesita compilador.

Antes el backend enlazaba `libprotobuf`. En Windows no se conseguía fácil y
el backend quedaba sin construir, así que las 35 pruebas de la VM se
omitían en silencio.

### Avisos a la vista

- **GCC y Clang:** `-Wall -Wextra -Wswitch`.
- **MSVC:** `/W4 /utf-8 /permissive-`.
  - `/utf-8` es obligatorio: las fuentes tienen comentarios en español, y sin
    esa opción MSVC las lee con la página de códigos del sistema (aviso
    C4819).
  - `/permissive-` hace que MSVC rechace lo que GCC rechaza.

Un aviso nuevo se arregla, no se apaga.

---

## 3. Construir un binario nuevo

Los binarios que vienen son el JIT, un banco de medida en C++ y
herramientas sobre el MIR. Todos siguen el mismo patrón, y ninguno necesita
un `CMakeLists.txt` propio.

### Estructura

Toda la lógica de CMake vive en este directorio. En la raíz hay **un solo**
`CMakeLists.txt`, y no hay más en el repositorio: cuando cada módulo traía el
suyo, tres módulos eran tres sitios donde arreglar el mismo bug.

```
CMakeLists.txt (raíz)  ── incluye ──▶  CMake/SuriaXOptions.cmake       opciones, estándar, avisos
                                       CMake/SuriaXPython.cmake        Python3 + pybind11, una vez
                                       CMake/SuriaXNativeModule.cmake  el patrón de un módulo pybind11
                                       CMake/SuriaXDiscover.cmake      descubre runtime/*/
                                       CMake/SuriaXBackend.cmake       backend/: suriax_hir + suriax-hir
```

### Un ejecutable del backend (una herramienta, un banco)

Va en `backend/tools/<nombre>.cpp`, y se registra dentro de
`suriax_add_backend()` en
[`SuriaXBackend.cmake`](SuriaXBackend.cmake), junto a `suriax-hir`:

```cmake
add_executable(suriax-mi-herramienta "${ARG_ROOT}/tools/mi_herramienta.cpp")
target_link_libraries(suriax-mi-herramienta PRIVATE suriax_hir)
set_target_properties(suriax-mi-herramienta PROPERTIES
    RUNTIME_OUTPUT_DIRECTORY "${CMAKE_BINARY_DIR}/bin")
```

- **Enlazar `suriax_hir`** le da el estándar, los `include` y, en MSVC, los
  avisos, porque la librería los declara `PUBLIC`. No hay que repetirlos.
- **La salida va a `build/bin/`**, donde la buscan las pruebas y los
  scripts.
- **Si ejecuta código de suriaX** (usa la VM), copia también la opción de la
  pila de `suriax-hir`: `/STACK:16777216` (MSVC, y Clang con el ABI de MSVC
  vía `LINKER:`) o `-Wl,--stack,16777216` (MinGW). Sin
  ella, en Windows una recursión profunda mata el proceso en vez de dar
  `RT019`.
- **Todo binario del backend lleva su prueba** en `test/e2e/`, que usa
  `helpers.omitir` cuando el binario no está construido.

### Una librería nueva del backend (el JIT)

Una pieza con entidad propia es una librería aparte que **depende** de
`suriax_hir`, no se mezcla con ella. Por ejemplo, el JIT. Así el que solo
quiere la VM no la compila.

```cmake
add_library(suriax_jit STATIC "${ARG_ROOT}/src/jit.cpp")
target_link_libraries(suriax_jit PUBLIC suriax_hir)
target_include_directories(suriax_jit PUBLIC "${ARG_ROOT}/include")
```

- **Si puede no estar disponible** (una arquitectura sin soporte), lleva su
  `option(SURIAX_BUILD_JIT ...)` en `SuriaXOptions.cmake` y una línea en el
  resumen de `suriax_print_summary`. Lo que no se construye se **dice** al
  configurar, no se descubre cuando falla una prueba.
- **Sus headers** van en `backend/include/suriax/<área>/`, con el mismo
  espacio de nombres `suriax::<área>`.

### Un módulo de Python en C++

No se toca ningún archivo de CMake. Se crea la carpeta y ya:

```
runtime/mi_modulo/
├── mi_entry.cpp        # con PYBIND11_MODULE(mi_modulo_c, m) { ... }
└── include/            # opcional; se añade al include path si existe
```

- **El nombre del módulo** sale del propio `PYBIND11_MODULE(...)` y no de la
  carpeta, porque es ahí donde ya estaba definido: `runtime/logic_mem`
  produce `memory_c`.
- **El `.so`/`.pyd`** va a `runtime/<módulo>/build/`, donde lo busca
  [`runtime/cxx_api.py`](../runtime/cxx_api.py).
- **Con `-DSURIAX_NATIVE_OUTPUT_IN_MODULE_DIR=OFF`** va a `build/lib/`, que
  sirve para empaquetar, pero entonces hay que registrar la ruta:
  `api.add_search_dir("build/lib")`.

### Lista de comprobación

- [ ] Compila sin avisos con MSVC (`/W4`) y con GCC o Clang (`-Wall -Wextra`).
- [ ] No añade una dependencia externa. Si de verdad hace falta, es una
      decisión del proyecto y se discute antes.
- [ ] No fija su propio estándar de C++ ni sus propias opciones de
      compilación: las hereda.
- [ ] Su salida está en `build/bin/` (ejecutables) o enlazada por un
      objetivo que ya existe (librerías).
- [ ] Tiene su prueba, que se omite con `helpers.omitir` sin el binario.
- [ ] El resumen de configuración dice si se construye o no.
- [ ] La CI (`.github/workflows/tests.yml`) lo construye.

---

## 4. Árboles de build antiguos

Cuando cada módulo tenía su propio `CMakeLists.txt`, se compilaba desde
`runtime/logic_mem/build/`. Esa carpeta puede seguir teniendo un
`CMakeCache.txt` que apunta a un archivo que ya no existe. El build nuevo
avisa al configurar y escribe el `.so` ahí igualmente. Borrar su
`CMakeCache.txt` y su `CMakeFiles/` no pierde nada.

Los directorios de build (`build/`, `build-*/`) están en `.gitignore`. Un
build dentro del propio repositorio (`cmake -S . -B .`) se rechaza al
configurar.

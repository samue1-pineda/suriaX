# `CMake/` — automatización del build nativo

Aquí vive **toda** la lógica de CMake del proyecto. En la raíz hay un único
[`CMakeLists.txt`](../CMakeLists.txt) y no hay ninguno más: los módulos de
este directorio son los que hacen el trabajo que antes se copiaba en un
archivo por carpeta.

```
CMakeLists.txt (raíz)  ── incluye ──▶  CMake/SuriaXOptions.cmake
                                       CMake/SuriaXPython.cmake
                                       CMake/SuriaXNativeModule.cmake
                                       CMake/SuriaXDiscover.cmake
                                                  │
                                       descubre runtime/*/  ──▶  memory_c
```

| Módulo | Responsabilidad |
|---|---|
| `SuriaXOptions.cmake` | Opciones (`SURIAX_BUILD_NATIVE`, `SURIAX_CXX_STANDARD`…), estándar de C++, `compile_commands.json`, tipo de build por defecto, guardas (build in-source, cachés viejas) y el resumen final. |
| `SuriaXPython.cmake` | Python3 (venv primero) y pybind11, **una vez para todos** los módulos. Localiza pybind11 preguntándole al propio intérprete, y si falta da el `pip install` exacto. |
| `SuriaXNativeModule.cmake` | `suriax_add_native_module()`: el patrón completo de un módulo pybind11 (target, `include/` local, salida en `runtime/<mod>/build/`). |
| `SuriaXDiscover.cmake` | Recorre `runtime/*/`, y de cada carpeta con `.cpp` saca el nombre del módulo leyendo su `PYBIND11_MODULE(...)`. |

## Uso

```bash
cmake -S . -B build            # configurar (detecta Python, pybind11 y módulos)
cmake --build build -j         # compilar todos los módulos nativos
cmake --build build --target suriax-native   # solo los nativos
cmake --build build --target suriax-test     # compila y corre test/main.py
```

Opciones útiles:

```bash
cmake -S . -B build -DSURIAX_BUILD_NATIVE=OFF        # sin C++ (solo el target 'suriax-test')
cmake -S . -B build -DSURIAX_CXX_STANDARD=23
cmake -S . -B build -DSURIAX_SKIP_MODULES=logic_mem  # excluir una carpeta
cmake -S . -B build -DPython3_EXECUTABLE=$(which python3.12)
```

## Añadir un módulo nativo

No se toca ningún archivo de CMake. Se crea la carpeta y ya:

```
runtime/mi_modulo/
├── mi_entry.cpp        # con PYBIND11_MODULE(mi_modulo_c, m) { ... }
└── include/            # opcional; se añade al include path si existe
```

El nombre del módulo de Python sale del propio `PYBIND11_MODULE(...)` —no de
la carpeta— porque es ahí donde ya estaba definido: `runtime/logic_mem`
produce `memory_c`, y derivarlo del nombre de la carpeta habría roto la carga
en `runtime/cxx_api.py`.

## Dónde quedan los artefactos

El `.so` va a `runtime/<modulo>/build/`, que es exactamente donde
[`runtime/cxx_api.py`](../runtime/cxx_api.py) busca los módulos nativos
(`runtime/*/build`). El árbol de build de CMake queda aparte, en `build/`.

Con `-DSURIAX_NATIVE_OUTPUT_IN_MODULE_DIR=OFF` los artefactos van a
`build/lib/` (útil para empaquetar), pero entonces hay que registrar esa ruta
en el runtime:

```python
from runtime.cxx_api import api
api.add_search_dir("build/lib")
```

## Nota sobre los árboles de build antiguos

Cuando cada módulo tenía su propio `CMakeLists.txt`, se compilaba desde
`runtime/logic_mem/build/`. Esa carpeta puede seguir teniendo un
`CMakeCache.txt` que apunta a un archivo que ya no existe: el build nuevo
avisa al configurar y escribe el `.so` ahí igualmente. Borrar su
`CMakeCache.txt` y su `CMakeFiles/` no pierde nada.

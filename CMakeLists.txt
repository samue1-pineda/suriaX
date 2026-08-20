# =============================================================================
# suriaX — build ÚNICO del lado nativo (C++/pybind11).
#
# Este es el ÚNICO CMakeLists.txt del repositorio, a propósito. Antes cada
# módulo nativo traía el suyo (`runtime/logic_mem/CMakeLists.txt`) con su
# propio `project()`, su propio `find_package(pybind11)` y su propia copia de
# las mismas seis líneas de configuración: tres módulos serían tres sitios
# donde arreglar el mismo bug, y el `runtime/` va a crecer (la VM de
# bytecode, el lector HIR en C++, el lowering a LLVM).
#
# La lógica reutilizable vive en `CMake/` como módulos:
#
#   CMake/SuriaXOptions.cmake        opciones y ajustes comunes
#   CMake/SuriaXPython.cmake         Python3 + pybind11, UNA sola vez
#   CMake/SuriaXNativeModule.cmake   suriax_add_native_module(): el patrón
#   CMake/SuriaXDiscover.cmake       descubre los módulos de runtime/
#
# Añadir un módulo nativo nuevo NO exige tocar ningún archivo de CMake:
# basta con crear `runtime/<lo_que_sea>/` con sus `.cpp` (y su `include/` si
# lo tiene). El nombre del módulo Python sale del propio
# `PYBIND11_MODULE(<nombre>, m)`, que es donde ya estaba definido.
#
# Uso:
#   cmake -S . -B build
#   cmake --build build -j
#   cmake --build build --target suriax-test     # la suite del repo
#
# Los artefactos van a `runtime/<modulo>/build/`, que es donde
# `runtime/cxx_api.py` los busca — el árbol de build de CMake se queda en
# `build/` y no ensucia el runtime.
# =============================================================================

cmake_minimum_required(VERSION 3.20)

# La version se LEE de 'version.py' (raiz del repo), que es su fuente unica.
# Estaba escrita aqui a mano y decia 0.1.4 mientras la documentacion publicaba
# 0.2.0: dos numeros para el mismo commit, y ninguna forma de saber cual
# mentia. Se lee con una regex y no importando Python porque CMake corre antes
# de que haya ningun interprete garantizado.
file(READ "${CMAKE_CURRENT_SOURCE_DIR}/version.py" _suriax_version_py)
string(REGEX MATCH "VERSION[ \t]*=[ \t]*\"([0-9]+\.[0-9]+\.[0-9]+)\""
       _suriax_version_match "${_suriax_version_py}")
if(NOT CMAKE_MATCH_1)
    message(FATAL_ERROR
        "no se pudo leer VERSION de version.py: es la fuente unica de la "
        "version del proyecto y su formato tiene que ser VERSION = \"X.Y.Z\"")
endif()
set(SURIAX_VERSION "${CMAKE_MATCH_1}")
unset(_suriax_version_py)

project(suriaX
    VERSION ${SURIAX_VERSION}
    DESCRIPTION "Lado nativo de suriaX: backend de memoria y futuros consumidores del HIR"
    LANGUAGES CXX
)

list(APPEND CMAKE_MODULE_PATH "${CMAKE_CURRENT_SOURCE_DIR}/CMake")

include(SuriaXOptions)
include(SuriaXNativeModule)
include(SuriaXDiscover)

# Python + pybind11 se resuelven una vez para TODOS los módulos (buscarlos por
# módulo era el mayor coste de configuración del esquema anterior).
if(SURIAX_BUILD_NATIVE)
    include(SuriaXPython)
endif()

# ---------------------------------------------------------------------------
# módulos nativos: convención sobre configuración
# ---------------------------------------------------------------------------
suriax_discover_native_modules(
    ROOT "${CMAKE_CURRENT_SOURCE_DIR}/runtime"
    OUT_TARGETS suriax_native_targets
)

# Un solo objetivo para construirlos todos ('cmake --build build --target
# suriax-native'), que es lo que el intérprete necesita antes de correr con
# memoria nativa.
add_custom_target(suriax-native)
if(suriax_native_targets)
    add_dependencies(suriax-native ${suriax_native_targets})
endif()

# ---------------------------------------------------------------------------
# suite de pruebas del repo (frontend Python + backend web) desde CMake
# ---------------------------------------------------------------------------
if(Python3_EXECUTABLE)
    add_custom_target(suriax-test
        COMMAND "${Python3_EXECUTABLE}" "${CMAKE_CURRENT_SOURCE_DIR}/test/main.py"
        WORKING_DIRECTORY "${CMAKE_CURRENT_SOURCE_DIR}"
        COMMENT "suriaX: ejecutando la suite completa (test/main.py)"
        USES_TERMINAL
    )
    if(suriax_native_targets)
        # con memoria nativa disponible, la suite la ejercita: compilar antes.
        add_dependencies(suriax-test suriax-native)
    endif()
endif()

suriax_print_summary("${suriax_native_targets}")

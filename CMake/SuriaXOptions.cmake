# =============================================================================
# SuriaXOptions — opciones y ajustes comunes a todo el lado nativo.
#
# Lo que antes se repetía en cada CMakeLists.txt de módulo (estándar de C++,
# export de compile_commands, tipo de build por defecto) vive aquí y se aplica
# una vez.
# =============================================================================

include_guard(GLOBAL)

# --- opciones del usuario ---------------------------------------------------

option(SURIAX_BUILD_NATIVE
    "Compilar los módulos nativos (C++/pybind11) de runtime/" ON)

option(SURIAX_NATIVE_OUTPUT_IN_MODULE_DIR
    "Dejar cada .so en runtime/<modulo>/build/, que es donde lo busca cxx_api.py" ON)

set(SURIAX_CXX_STANDARD "20" CACHE STRING
    "Estándar de C++ para los módulos nativos")

# --- ajustes comunes --------------------------------------------------------

set(CMAKE_CXX_STANDARD ${SURIAX_CXX_STANDARD})
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)

# Posición independiente: todo módulo de Python es una biblioteca compartida.
set(CMAKE_POSITION_INDEPENDENT_CODE ON)

# compile_commands.json para clangd/el IDE: sin esto, los headers de pybind11
# aparecen como errores falsos en el editor (era el motivo del ajuste en el
# CMakeLists de logic_mem).
set(CMAKE_EXPORT_COMPILE_COMMANDS ON)

# Sin tipo de build explícito, CMake compila SIN optimizar y sin símbolos: el
# backend de memoria se nota. Se elige uno por defecto y se avisa.
if(NOT CMAKE_BUILD_TYPE AND NOT CMAKE_CONFIGURATION_TYPES)
    set(CMAKE_BUILD_TYPE "RelWithDebInfo" CACHE STRING
        "Tipo de build (Debug, Release, RelWithDebInfo, MinSizeRel)" FORCE)
    message(STATUS "suriaX: CMAKE_BUILD_TYPE no estaba definido -> RelWithDebInfo")
endif()

# Un build in-source mezclaría los artefactos con el código y rompería el
# .gitignore (que ignora 'build/', no la raíz).
if(CMAKE_SOURCE_DIR STREQUAL CMAKE_BINARY_DIR)
    message(FATAL_ERROR
        "suriaX: no compiles dentro del propio repositorio.\n"
        "  -> cmake -S . -B build && cmake --build build")
endif()

# Restos del esquema anterior (un build tree por módulo): su caché apunta a un
# CMakeLists.txt que ya no existe, así que un 'cmake ..' ahí dentro fallaría
# con un mensaje que no explica nada. Mejor decirlo al configurar.
file(GLOB _suriax_stale_caches "${CMAKE_SOURCE_DIR}/runtime/*/build/CMakeCache.txt")
foreach(_cache IN LISTS _suriax_stale_caches)
    get_filename_component(_dir "${_cache}" DIRECTORY)
    message(WARNING
        "suriaX: '${_dir}' trae un árbol de build antiguo (de cuando cada módulo "
        "tenía su propio CMakeLists.txt). El .so nuevo se escribirá ahí igual, "
        "pero puedes borrar su CMakeCache.txt y CMakeFiles/ sin perder nada.")
endforeach()
unset(_suriax_stale_caches)

# --- resumen ----------------------------------------------------------------

function(suriax_print_summary targets)
    message(STATUS "")
    message(STATUS "=== suriaX ${PROJECT_VERSION} ===")
    message(STATUS "  build            : ${CMAKE_BUILD_TYPE}")
    message(STATUS "  C++              : ${SURIAX_CXX_STANDARD}")
    if(NOT SURIAX_BUILD_NATIVE)
        message(STATUS "  módulos nativos  : desactivados (SURIAX_BUILD_NATIVE=OFF)")
    elseif(targets)
        message(STATUS "  módulos nativos  : ${targets}")
        message(STATUS "  Python           : ${Python3_EXECUTABLE} (${Python3_VERSION})")
        message(STATUS "  pybind11         : ${pybind11_VERSION}")
    else()
        message(STATUS "  módulos nativos  : ninguno encontrado en runtime/")
    endif()
    message(STATUS "")
endfunction()

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

option(SURIAX_BUILD_BACKEND
    "Compilar el backend C++ (HIR, MIR, VM); solo necesita un compilador de C++20" ON)

# Sanitizadores para el backend C++: "" (ninguno), "address", "undefined" o
# "address;undefined". Es un build de DIAGNÓSTICO, no de uso: más lento y
# con otros límites de pila. Ver suriax_aplicar_sanitizadores().
set(SURIAX_SANITIZE "" CACHE STRING
    "Sanitizadores del backend C++: address, undefined o address;undefined")

# UBSan en modo TRAMPA: un comportamiento indefinido detiene el programa con
# una instruccion ilegal en vez de llamar al runtime de UBSan. No dice QUE
# regla se rompio (eso lo da el runtime), pero no lo necesita: sirve donde el
# runtime no existe (clang para Windows x64 sin compiler-rt de UBSan). Solo
# GCC/Clang. Lo usa 'docs/quality/tools/sanitizers.py'.
option(SURIAX_SANITIZE_TRAP
    "UBSan sin runtime (-fsanitize-trap=undefined): detiene en vez de informar" OFF)

# MSVC: /RTC1 (el chequeo de pila de Debug) no convive con /fsanitize=address.
# Se quita aquí, a nivel de directorio: las banderas por configuración se leen
# al final del directorio y cambiarlas dentro de una función no llega.
if(MSVC AND "address" IN_LIST SURIAX_SANITIZE)
    string(REPLACE "/RTC1" "" CMAKE_CXX_FLAGS_DEBUG "${CMAKE_CXX_FLAGS_DEBUG}")
endif()

# El estándar de C++ NO es una opción: lo fija 'version.py' (CXX_STANDARD)
# y lo lee el CMakeLists.txt raíz antes de llegar aquí (SURIAX_CXX_STANDARD).

# --- ajustes comunes --------------------------------------------------------

# Exactamente ese estándar (REQUIRED), sin extensiones del compilador
# (gnu++20 no es C++20): así GCC, Clang y MSVC compilan el MISMO lenguaje.
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

# --- sanitizadores -----------------------------------------------------------

#[[
  suriax_aplicar_sanitizadores(<objetivo>...)

  Instrumenta los objetivos con lo que pida SURIAX_SANITIZE. Con GCC y Clang:
  AddressSanitizer (desbordes, uso tras liberar) y UBSan (desborde con signo,
  corrimientos, conversiones, alineación), y cualquier hallazgo de UBSan
  ABORTA en vez de seguir (-fno-sanitize-recover): una prueba que pasa con un
  aviso en stderr no probó nada.

  MSVC trae AddressSanitizer (/fsanitize=address) pero no UBSan: se avisa al
  configurar en vez de fingir que se instrumentó. Con MSVC, además, ASan no
  convive con /RTC1 (el chequeo de pila de Debug), así que se quita.
]]
function(suriax_aplicar_sanitizadores)
    if(NOT SURIAX_SANITIZE)
        return()
    endif()
    set(pide_asan FALSE)
    set(pide_ubsan FALSE)
    foreach(s IN LISTS SURIAX_SANITIZE)
        if(s STREQUAL "address")
            set(pide_asan TRUE)
        elseif(s STREQUAL "undefined")
            set(pide_ubsan TRUE)
        else()
            message(FATAL_ERROR "SURIAX_SANITIZE: '${s}' no es un sanitizador "
                                "conocido (address, undefined)")
        endif()
    endforeach()

    foreach(objetivo IN LISTS ARGN)
        if(MSVC)
            if(pide_asan)
                target_compile_options(${objetivo} PRIVATE /fsanitize=address /Zi)
                target_link_options(${objetivo} PRIVATE /INCREMENTAL:NO /DEBUG)
            endif()
        else()
            set(banderas "")
            if(pide_asan)
                list(APPEND banderas -fsanitize=address)
            endif()
            if(pide_ubsan AND SURIAX_SANITIZE_TRAP)
                list(APPEND banderas -fsanitize=undefined -fsanitize-trap=undefined)
            elseif(pide_ubsan)
                list(APPEND banderas -fsanitize=undefined -fno-sanitize-recover=all)
            endif()
            target_compile_options(${objetivo} PRIVATE ${banderas}
                                   -fno-omit-frame-pointer -g)
            target_link_options(${objetivo} PRIVATE ${banderas})
        endif()
    endforeach()

    if(MSVC)
        if(pide_ubsan)
            message(WARNING
                "suriaX: MSVC no tiene UBSan; 'undefined' se ignora. En un build "
                "Debug los iteradores verificados de la STL atrapan parte de lo "
                "mismo (índices fuera de rango en contenedores). Para UBSan "
                "completo: GCC o Clang con compiler-rt (la CI de Linux).")
        endif()
    endif()
    message(STATUS "suriaX: sanitizadores del backend -> ${SURIAX_SANITIZE}")
endfunction()

# --- resumen ----------------------------------------------------------------

function(suriax_print_summary targets)
    message(STATUS "")
    message(STATUS "=== suriaX ${PROJECT_VERSION} ===")
    message(STATUS "  build            : ${CMAKE_BUILD_TYPE}")
    message(STATUS "  C++              : ${SURIAX_CXX_STANDARD}")
    if(TARGET suriax-hir)
        message(STATUS "  backend C++      : HIR, MIR y VM (objetivo 'suriax-hir')")
    elseif(NOT SURIAX_BUILD_BACKEND)
        message(STATUS "  backend C++      : desactivado (SURIAX_BUILD_BACKEND=OFF)")
    else()
        message(STATUS "  backend C++      : omitido (ver los avisos de arriba)")
    endif()
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

# =============================================================================
# SuriaXPython — Python3 + pybind11, resueltos UNA vez para todo el repo.
#
# Regla que ya seguía el módulo de memoria y que aquí se vuelve global: el
# módulo nativo tiene que compilarse con el MISMO intérprete que lo importará
# (`runtime/cxx_api.py` carga un `.so` compilado para una versión concreta de
# CPython; si no coinciden, no carga y el intérprete cae al backend de Python
# puro sin decir por qué).
#
# Por eso el entorno virtual activo manda: `Python3_FIND_VIRTUALENV FIRST`.
# Y por eso los errores de aquí traen el comando exacto que los arregla —
# quien compila esto no tiene por qué saber de CMake.
#
# Nota: se evalúa `nanobind` como alternativa a pybind11 (bindings más
# ligeros y rápidos de compilar). Cuando se decida, el cambio es local a este
# archivo y a `suriax_add_native_module`; ningún módulo lo nota.
# =============================================================================

include_guard(GLOBAL)

set(Python3_FIND_VIRTUALENV FIRST)
find_package(Python3 REQUIRED COMPONENTS Interpreter Development.Module)

# pybind11 se instala normalmente con pip, y entonces su config de CMake vive
# dentro del paquete: se le pregunta al propio intérprete dónde está en vez de
# exigir que el usuario exporte CMAKE_PREFIX_PATH a mano.
if(NOT pybind11_DIR)
    execute_process(
        COMMAND "${Python3_EXECUTABLE}" -m pybind11 --cmakedir
        OUTPUT_VARIABLE _suriax_pybind11_dir
        OUTPUT_STRIP_TRAILING_WHITESPACE
        ERROR_QUIET
        RESULT_VARIABLE _suriax_pybind11_found
    )
    if(_suriax_pybind11_found EQUAL 0 AND EXISTS "${_suriax_pybind11_dir}")
        set(pybind11_DIR "${_suriax_pybind11_dir}" CACHE PATH
            "Config de CMake de pybind11 (detectada vía el intérprete)" FORCE)
        message(STATUS "suriaX: pybind11 detectado en ${pybind11_DIR}")
    endif()
    unset(_suriax_pybind11_dir)
    unset(_suriax_pybind11_found)
endif()

find_package(pybind11 CONFIG QUIET)
if(NOT pybind11_FOUND)
    message(FATAL_ERROR
        "suriaX: no se encontró pybind11 para '${Python3_EXECUTABLE}'.\n"
        "  -> ${Python3_EXECUTABLE} -m pip install pybind11\n"
        "  (o instálalo con tu gestor de paquetes y reconfigura con "
        "-Dpybind11_DIR=<ruta>)")
endif()

message(STATUS
    "suriaX: Python ${Python3_VERSION} (${Python3_EXECUTABLE}) + pybind11 ${pybind11_VERSION}")

# =============================================================================
# SuriaXDiscover — descubre los módulos nativos de runtime/ sin registro manual.
#
# La automatización que sustituye a "un CMakeLists.txt por carpeta": se
# recorren las subcarpetas de `runtime/`, y cada una con fuentes C++ en su
# nivel superior se convierte en un módulo.
#
# El NOMBRE del módulo no se inventa desde el de la carpeta —`logic_mem`
# produce `memory_c`, y adivinarlo habría roto la carga en `cxx_api.py`—: se
# lee de `PYBIND11_MODULE(<nombre>, m)`, que es donde el nombre está definido
# de verdad. Una fuente única, igual que en el resto del proyecto.
# =============================================================================

include_guard(GLOBAL)

#[[
  suriax_module_name_from_sources(<var> <fuente>...)

  Devuelve el nombre declarado en PYBIND11_MODULE(...), o "" si no aparece
  (ese caso no es un módulo de Python: puede ser una librería auxiliar).
]]
function(suriax_module_name_from_sources out_var)
    foreach(source IN LISTS ARGN)
        file(STRINGS "${source}" matches
             REGEX "PYBIND11_MODULE[ \t]*\\([ \t]*[A-Za-z_][A-Za-z0-9_]*")
        foreach(line IN LISTS matches)
            if(line MATCHES "PYBIND11_MODULE[ \t]*\\([ \t]*([A-Za-z_][A-Za-z0-9_]*)")
                set(${out_var} "${CMAKE_MATCH_1}" PARENT_SCOPE)
                return()
            endif()
        endforeach()
    endforeach()
    set(${out_var} "" PARENT_SCOPE)
endfunction()

#[[
  suriax_discover_native_modules(ROOT <dir> [OUT_TARGETS <var>])

  Un módulo es cualquier subcarpeta de ROOT que traiga .cpp en su raíz. Se
  ignoran las carpetas de artefactos y las de Python (`interpreter/`,
  `__pycache__/`, `build/`...), que no tienen fuentes C++ y por tanto se
  descartan solas: no hace falta mantener una lista de exclusiones.

  Para excluir una carpeta con C++ a propósito, basta con ponerla en
  SURIAX_SKIP_MODULES (lista de nombres de carpeta).
]]
function(suriax_discover_native_modules)
    cmake_parse_arguments(ARG "" "ROOT;OUT_TARGETS" "" ${ARGN})
    if(NOT ARG_ROOT)
        message(FATAL_ERROR "suriax_discover_native_modules: falta ROOT")
    endif()

    set(targets "")
    file(GLOB entries RELATIVE "${ARG_ROOT}" "${ARG_ROOT}/*")
    list(SORT entries)  # orden determinista entre máquinas

    foreach(entry IN LISTS entries)
        set(dir "${ARG_ROOT}/${entry}")
        if(NOT IS_DIRECTORY "${dir}")
            continue()
        endif()
        if(entry IN_LIST SURIAX_SKIP_MODULES)
            message(STATUS "suriaX: '${entry}' omitido (SURIAX_SKIP_MODULES)")
            continue()
        endif()

        file(GLOB sources CONFIGURE_DEPENDS "${dir}/*.cpp" "${dir}/*.cc")
        if(NOT sources)
            continue()
        endif()

        suriax_module_name_from_sources(module_name ${sources})
        if(NOT module_name)
            message(WARNING
                "suriaX: '${dir}' tiene C++ pero ningún PYBIND11_MODULE(...); "
                "no se puede saber qué módulo de Python produce, se omite.")
            continue()
        endif()

        suriax_add_native_module(NAME "${module_name}" DIR "${dir}" SOURCES ${sources})
        if(TARGET ${module_name})
            list(APPEND targets ${module_name})
        endif()
    endforeach()

    if(ARG_OUT_TARGETS)
        set(${ARG_OUT_TARGETS} "${targets}" PARENT_SCOPE)
    endif()
endfunction()

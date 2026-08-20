# =============================================================================
# SuriaXNativeModule — el patrón "módulo nativo de suriaX", una sola vez.
#
# `suriax_add_native_module()` es lo que antes era un CMakeLists.txt entero
# por carpeta: el target de pybind11, el estándar de C++, el `include/` local
# y el directorio de salida que espera `runtime/cxx_api.py`.
# =============================================================================

include_guard(GLOBAL)

#[[
  suriax_add_native_module(
      NAME    <nombre del módulo Python>   # el de PYBIND11_MODULE(...)
      DIR     <carpeta del módulo>         # runtime/<algo>
      [SOURCES ...]                        # por defecto: los *.cpp de DIR
      [INCLUDE_DIRS ...]                   # además de <DIR>/include si existe
      [OUTPUT_DIR <ruta>]                  # por defecto: <DIR>/build
  )

  El .so va a `<DIR>/build/` porque es donde `cxx_api.py` busca
  (`runtime/<modulo>/build`). Cambiar eso exigiría tocar el runtime, el
  intérprete y sus tests para no ganar nada: la convención se respeta.
]]
function(suriax_add_native_module)
    cmake_parse_arguments(ARG "" "NAME;DIR;OUTPUT_DIR" "SOURCES;INCLUDE_DIRS" ${ARGN})

    if(NOT ARG_NAME OR NOT ARG_DIR)
        message(FATAL_ERROR "suriax_add_native_module: NAME y DIR son obligatorios")
    endif()
    if(NOT SURIAX_BUILD_NATIVE)
        return()
    endif()

    set(sources ${ARG_SOURCES})
    if(NOT sources)
        # solo el nivel superior del módulo: los .cpp de 'build/' son basura
        # generada y los de subcarpetas los declara el propio módulo.
        file(GLOB sources CONFIGURE_DEPENDS "${ARG_DIR}/*.cpp" "${ARG_DIR}/*.cc")
    endif()
    if(NOT sources)
        message(WARNING "suriaX: '${ARG_DIR}' no tiene fuentes C++; se omite")
        return()
    endif()

    if(TARGET ${ARG_NAME})
        message(FATAL_ERROR
            "suriaX: dos módulos nativos declaran el mismo nombre '${ARG_NAME}'. "
            "El nombre sale de PYBIND11_MODULE(...): dos módulos de Python no "
            "pueden compartirlo.")
    endif()

    pybind11_add_module(${ARG_NAME} ${sources})
    target_compile_features(${ARG_NAME} PRIVATE cxx_std_${SURIAX_CXX_STANDARD})

    if(EXISTS "${ARG_DIR}/include")
        target_include_directories(${ARG_NAME} PRIVATE "${ARG_DIR}/include")
    endif()
    if(ARG_INCLUDE_DIRS)
        target_include_directories(${ARG_NAME} PRIVATE ${ARG_INCLUDE_DIRS})
    endif()

    set(output_dir "${ARG_OUTPUT_DIR}")
    if(NOT output_dir)
        if(SURIAX_NATIVE_OUTPUT_IN_MODULE_DIR)
            set(output_dir "${ARG_DIR}/build")
        else()
            set(output_dir "${CMAKE_BINARY_DIR}/lib")
        endif()
    endif()
    file(MAKE_DIRECTORY "${output_dir}")
    set_target_properties(${ARG_NAME} PROPERTIES LIBRARY_OUTPUT_DIRECTORY "${output_dir}")
    # generadores multi-config (MSVC, Xcode) meten un subdirectorio por
    # configuración si no se fija también la variante por config.
    foreach(config IN LISTS CMAKE_CONFIGURATION_TYPES)
        string(TOUPPER "${config}" config_upper)
        set_target_properties(${ARG_NAME} PROPERTIES
            LIBRARY_OUTPUT_DIRECTORY_${config_upper} "${output_dir}")
    endforeach()

    get_filename_component(module_folder "${ARG_DIR}" NAME)
    message(STATUS "suriaX: módulo nativo '${ARG_NAME}' (runtime/${module_folder}) -> ${output_dir}")
endfunction()

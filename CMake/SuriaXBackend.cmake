# =============================================================================
# SuriaXBackend — el mundo C++ del backend: lector del HIR, MIR y VM.
#
# Es la segunda ruta de build del repositorio, y existe porque la primera no
# servia: `SuriaXDiscover` arma modulos de Python (pybind11) y deduce su
# nombre de `PYBIND11_MODULE(...)`. El lector del HIR no es un modulo de
# Python — es una libreria C++ y un ejecutable — asi que forzarlo por ahi
# habria significado inventarle un binding que nadie usa.
#
# No tiene dependencias externas: el HIR se lee con un modelo GENERADO desde
# el `.proto` (backend/tools/gen_hir_cpp.py), igual que Python y el target web
# lo leen con su propio decodificador. Antes enlazaba libprotobuf, que en
# Windows no se consigue facil y dejaba el backend sin construir.
#
# Sigue siendo OPCIONAL (SURIAX_BUILD_BACKEND=OFF): el resto del repositorio
# (frontend, interprete, target web) no depende de este lado.
# =============================================================================

include_guard(GLOBAL)

#[[
  suriax_add_backend(ROOT <dir del backend> PROTO <archivo .proto>)

  Deja dos objetivos:
    suriax_hir      libreria estatica: lector + vistas
    suriax-hir      CLI que la ejercita (y que usa el test diferencial)
]]
function(suriax_add_backend)
    cmake_parse_arguments(ARG "" "ROOT;PROTO" "" ${ARGN})
    if(NOT ARG_ROOT OR NOT ARG_PROTO)
        message(FATAL_ERROR "suriax_add_backend: ROOT y PROTO son obligatorios")
    endif()
    if(NOT SURIAX_BUILD_BACKEND)
        return()
    endif()

    # El modelo del HIR (backend/include/suriax/hir/hir_modelo.hpp) se GENERA
    # desde el .proto con backend/tools/gen_hir_cpp.py y se guarda en el
    # repositorio: construir no necesita ni protoc ni Python. Si el .proto es
    # mas nuevo que el modelo, se avisa (la prueba 'test_modelo_hir_cpp' lo
    # comprueba de verdad, byte a byte).
    set(modelo "${ARG_ROOT}/include/suriax/hir/hir_modelo.hpp")
    if("${ARG_PROTO}" IS_NEWER_THAN "${modelo}")
        message(WARNING
            "suriaX: ${ARG_PROTO} es mas nuevo que el modelo C++ del HIR. "
            "Regeneralo: python backend/tools/gen_hir_cpp.py")
    endif()

    add_library(suriax_hir STATIC
        "${ARG_ROOT}/src/loader.cpp"
        "${ARG_ROOT}/src/view.cpp"
        "${ARG_ROOT}/src/resolve.cpp"
        "${ARG_ROOT}/src/mir.cpp"
        "${ARG_ROOT}/src/vm.cpp"
        "${ARG_ROOT}/src/verify.cpp"
        "${ARG_ROOT}/src/externo.cpp"
        "${ARG_ROOT}/src/rutas.cpp"
    )
    target_include_directories(suriax_hir PUBLIC "${ARG_ROOT}/include")
    target_compile_features(suriax_hir PUBLIC cxx_std_${SURIAX_CXX_STANDARD})
    # '#extern cpp' compila el C++ del programa con el MISMO estandar que el
    # resto del proyecto (version.py), y carga la biblioteca con dlopen
    target_compile_definitions(suriax_hir PRIVATE
        SURIAX_CXX_ESTANDAR="${SURIAX_CXX_STANDARD}")
    target_link_libraries(suriax_hir PUBLIC ${CMAKE_DL_LIBS})

    # Avisos como los del resto del proyecto: un warning es informacion, no
    # ruido que apagar. GCC/Clang: -Wall -Wextra; MSVC: /W4, y /utf-8 porque
    # las fuentes tienen comentarios en espanol (sin el, MSVC las lee en la
    # pagina de codigos del sistema y avisa C4819).
    if(MSVC)
        target_compile_options(suriax_hir PUBLIC /W4 /utf-8 /permissive-)
    else()
        target_compile_options(suriax_hir PRIVATE -Wall -Wextra -Wswitch)
    endif()

    add_executable(suriax-hir "${ARG_ROOT}/tools/suriax_hir.cpp")
    target_link_libraries(suriax-hir PRIVATE suriax_hir)
    # La VM ejecuta cada llamada de suriaX como una llamada de C++, y su tope
    # es de 4096 marcos (kMaxDepth en vm.cpp). La pila por defecto de Windows
    # es de 1 MB y se agotaba a unos 790: el proceso moria con 0xC00000FD en
    # vez de dar el error controlado. Con 16 MB el tope de la VM llega antes
    # que el del sistema (en Linux la pila principal ya es de 8 MB).
    if(MSVC)
        target_link_options(suriax-hir PRIVATE /STACK:16777216)
    elseif(WIN32 AND CMAKE_CXX_SIMULATE_ID STREQUAL "MSVC")
        # clang con el ABI de MSVC (--target=*-windows-msvc) enlaza con
        # link.exe o lld-link: la opcion es la de MSVC, no la de GNU ld
        target_link_options(suriax-hir PRIVATE "LINKER:/STACK:16777216")
    elseif(WIN32)
        # MinGW (GNU ld)
        target_link_options(suriax-hir PRIVATE -Wl,--stack,16777216)
    endif()
    set_target_properties(suriax-hir PROPERTIES
        RUNTIME_OUTPUT_DIRECTORY "${CMAKE_BINARY_DIR}/bin")
    # build de diagnostico: -DSURIAX_SANITIZE=address (ver SuriaXOptions)
    suriax_aplicar_sanitizadores(suriax_hir suriax-hir)

    message(STATUS "suriaX: backend C++ (HIR, MIR, VM) -> ${CMAKE_BINARY_DIR}/bin/suriax-hir")
    set(SURIAX_BACKEND_ENABLED TRUE PARENT_SCOPE)
endfunction()

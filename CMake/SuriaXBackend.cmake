# =============================================================================
# SuriaXBackend — el mundo C++ del backend: hoy, el lector del HIR.
#
# Es la segunda ruta de build del repositorio, y existe porque la primera no
# servia: `SuriaXDiscover` arma modulos de Python (pybind11) y deduce su
# nombre de `PYBIND11_MODULE(...)`. El lector del HIR no es un modulo de
# Python — es una libreria C++ y un ejecutable — asi que forzarlo por ahi
# habria significado inventarle un binding que nadie usa.
#
# La dependencia nueva es protobuf (libprotobuf + protoc), y es la del
# esquema: el `.proto` sigue siendo la fuente unica y los stubs C++ se
# generan EN BUILD, igual que los de Python en `V0/src/HIR/stubs.py`. No se
# commitean.
#
# El backend es OPCIONAL: sin protobuf de C++ se desactiva con un aviso y el
# resto del repositorio (frontend, interprete, target web) sigue compilando y
# pasando su suite. El frontend en Python no depende de este lado.
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

    # protobuf del lado C++. Se busca en modo CONFIG primero porque desde la
    # v22 es como upstream lo distribuye (y trae los targets con sus
    # dependencias de abseil ya resueltas).
    find_package(Protobuf CONFIG QUIET)
    if(NOT Protobuf_FOUND)
        find_package(Protobuf QUIET)
    endif()
    if(NOT Protobuf_FOUND)
        message(STATUS
            "suriaX: backend C++ omitido — no se encontro protobuf para C++.\n"
            "        -> instalalo con tu gestor de paquetes (apt: "
            "libprotobuf-dev protobuf-compiler; pacman: protobuf; brew: protobuf)")
        return()
    endif()

    # protoc: el ejecutable puede venir como target importado o como ruta.
    if(TARGET protobuf::protoc)
        set(protoc_exe "$<TARGET_FILE:protobuf::protoc>")
    elseif(Protobuf_PROTOC_EXECUTABLE)
        set(protoc_exe "${Protobuf_PROTOC_EXECUTABLE}")
    else()
        message(STATUS "suriaX: backend C++ omitido — no se encontro 'protoc'")
        return()
    endif()

    get_filename_component(proto_dir "${ARG_PROTO}" DIRECTORY)
    get_filename_component(proto_name "${ARG_PROTO}" NAME_WE)
    set(generated_dir "${CMAKE_BINARY_DIR}/generated/hir")
    set(generated_sources
        "${generated_dir}/${proto_name}.pb.cc"
        "${generated_dir}/${proto_name}.pb.h")

    # Los stubs se regeneran cuando el .proto cambia, no en cada build: el
    # esquema es la fuente unica y esta es su otra salida.
    add_custom_command(
        OUTPUT ${generated_sources}
        COMMAND "${CMAKE_COMMAND}" -E make_directory "${generated_dir}"
        COMMAND "${protoc_exe}"
                "--proto_path=${proto_dir}"
                "--cpp_out=${generated_dir}"
                "${ARG_PROTO}"
        DEPENDS "${ARG_PROTO}"
        COMMENT "suriaX: generando los stubs C++ del HIR desde ${proto_name}.proto"
        VERBATIM
    )
    add_custom_target(suriax_hir_proto DEPENDS ${generated_sources})

    add_library(suriax_hir STATIC
        "${ARG_ROOT}/src/loader.cpp"
        "${ARG_ROOT}/src/view.cpp"
        "${ARG_ROOT}/src/resolve.cpp"
        "${ARG_ROOT}/src/mir.cpp"
        "${ARG_ROOT}/src/vm.cpp"
        "${ARG_ROOT}/src/verify.cpp"
        "${generated_dir}/${proto_name}.pb.cc"
    )
    add_dependencies(suriax_hir suriax_hir_proto)
    target_include_directories(suriax_hir PUBLIC
        "${ARG_ROOT}/include"
        "${generated_dir}"
    )
    target_compile_features(suriax_hir PUBLIC cxx_std_${SURIAX_CXX_STANDARD})
    target_link_libraries(suriax_hir PUBLIC protobuf::libprotobuf)

    # Avisos como los del resto del proyecto: un warning es informacion, no
    # ruido que apagar. Solo sobre NUESTRAS fuentes — el .pb.cc generado no
    # es codigo del proyecto y sus avisos no los puede arreglar nadie aqui.
    if(NOT MSVC)
        set_source_files_properties(
            "${ARG_ROOT}/src/loader.cpp" "${ARG_ROOT}/src/view.cpp"
            "${ARG_ROOT}/src/resolve.cpp"
        "${ARG_ROOT}/src/mir.cpp" "${ARG_ROOT}/src/vm.cpp"
            "${ARG_ROOT}/src/verify.cpp"
            "${ARG_ROOT}/tools/suriax_hir.cpp"
            PROPERTIES COMPILE_OPTIONS "-Wall;-Wextra;-Wswitch"
        )
    endif()

    add_executable(suriax-hir "${ARG_ROOT}/tools/suriax_hir.cpp")
    target_link_libraries(suriax-hir PRIVATE suriax_hir)
    set_target_properties(suriax-hir PROPERTIES
        RUNTIME_OUTPUT_DIRECTORY "${CMAKE_BINARY_DIR}/bin")

    message(STATUS "suriaX: backend C++ (lector del HIR) -> ${CMAKE_BINARY_DIR}/bin/suriax-hir")
    set(SURIAX_BACKEND_ENABLED TRUE PARENT_SCOPE)
endfunction()

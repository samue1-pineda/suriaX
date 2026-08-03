cmake_minimum_required(VERSION 3.20)

project(memory_c LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 20)
set(CMAKE_CXX_STANDARD_REQUIRED ON)

# Exporta compile_commands.json para que clangd/el IDE encuentre los headers
# de pybind11 y deje de marcar errores falsos en cxx_entry.c++.
set(CMAKE_EXPORT_COMPILE_COMMANDS ON)

# Forzar a CMake a buscar en el entorno virtual activo
set(Python3_FIND_VIRTUALENV FIRST)
find_package(Python3 REQUIRED COMPONENTS Interpreter Development.Module)

# Buscar pybind11 instalado en el py_env
find_package(pybind11 REQUIRED CONFIG)

set(SOURCES
    cxx_entry.cpp
)

# Generar el módulo de Python
pybind11_add_module(memory_c ${SOURCES})

# Incluir carpeta include local si existe
if(EXISTS "${CMAKE_CURRENT_SOURCE_DIR}/include")
    target_include_directories(memory_c PRIVATE include)
endif()

target_compile_features(memory_c PRIVATE cxx_std_20)
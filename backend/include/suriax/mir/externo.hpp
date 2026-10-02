// '#extern cpp' en la VM: construir el C++ del programa, cargarlo y llamarlo.
//
// Es el mismo contrato que cumple el interprete ('runtime/extern_cpp.py'):
// un prototipo sin cuerpo ('fn suma(int ptr d, int n) -> int;') lo cumple la
// funcion 'extern "C"' del mismo nombre que traen los bloques '#extern cpp'
// de la imagen. Cambia el mecanismo, no el contrato:
//
//   - construir: el MISMO compilador (CXX, g++ o clang++), las mismas
//     banderas ('requires(...)' de los bloques + SURIAX_CPP_FLAGS) y la misma
//     regla de cache (no se recompila si el fuente generado no cambio). La
//     configuracion del '.suriaX_config.yaml' ('toolchain.*') la lee el
//     driver de Python, no esta herramienta: aqui manda el entorno;
//   - llamar: sin ctypes ni libffi. Un valor de la VM ya es de maquina —un
//     entero de 64 bits o un double—, asi que basta con una llamada tipada,
//     y las firmas posibles son pocas (ver 'llamar_externo');
//   - la memoria: un bloque de 'int' o 'float' de la VM ES un buffer
//     contiguo de 8 bytes por celda, asi que C++ recibe el puntero real y no
//     una copia. Lo que escribe se ve al volver, como en el interprete, y sin
//     la copia de ida y vuelta.
#pragma once

#include <cstdint>
#include <string>
#include <utility>
#include <vector>

#include "suriax/hir/view.hpp"
#include "suriax/mir/mir.hpp"
#include "suriax/mir/vm.hpp"

namespace suriax::mir {

// Una biblioteca compartida cargada. Se descarga al destruirse.
class Externo {
public:
    // Un simbolo de C. Se guarda con el tipo 'void (*)()', que es el que se
    // puede convertir a cualquier otro puntero a funcion sin perder nada.
    using Funcion = void (*)();

    Externo() = default;
    ~Externo();
    Externo(const Externo&) = delete;
    Externo& operator=(const Externo&) = delete;

    // Carga 'ruta'. false, con el porque en 'error', si no se pudo (una
    // biblioteca de 32 bits en una VM de 64 es el caso tipico).
    bool cargar(const std::string& ruta, std::string& error);
    // El simbolo exportado con ese nombre, o nullptr.
    Funcion simbolo(const std::string& nombre) const;

private:
    void* manejador_ = nullptr;
};

// Lo que paso al construir. Nunca lanza: se informa y quien llama decide.
struct ReporteExterno {
    bool hubo_bloques = false;
    std::string biblioteca;   // la construida (o la de la cache)
    std::string error;        // por que no hay biblioteca
};

// Construye la biblioteca de los '#extern cpp' de 'image' en 'carpeta'.
// 'prototipos' son los nombres que el programa declara sin cuerpo: con un
// toolchain de ABI de MSVC son los que se exportan (ver 'definidos_coff').
ReporteExterno construir_externo(const hir::Image& image, const std::string& carpeta,
                                 const std::vector<std::string>& prototipos);

// Liga cada primitiva del programa ('Program::hosts') a su simbolo de C++,
// si 'externo' lo exporta y su firma cruza la frontera. El resultado es
// paralelo a 'hosts' (nullptr = no ligada: la cumple la VM, o nadie).
std::vector<Externo::Funcion> ligar_externo(
    const Program& program, const Externo& externo,
    std::vector<std::string>& ligados,
    std::vector<std::pair<std::string, std::string>>& omitidos);

// Tope de parametros de una funcion de C++. Hasta 6 todos van en registros
// en las ABI de 64 bits que importan (System V y AArch64), y en la de
// Windows los que no caben van en ranuras de 8 bytes: con ese tope una
// llamada tipada con enteros de 64 bits y doubles es correcta aunque C++
// declare 'bool', 'uint32_t' o un puntero.
constexpr std::size_t kMaxParamsExterno = 6;

// Un argumento ya convertido a la frontera: un entero de 64 bits (que
// tambien lleva un bool, un char o un puntero) o un double.
struct Crudo {
    std::int64_t i = 0;
    double f = 0.0;
    bool flotante = false;
};

// Llama a 'f' con 'args' y devuelve lo que devuelva segun 'retorno'.
Value llamar_externo(Externo::Funcion f, Abi retorno, const std::vector<Crudo>& args);

// Los simbolos EXTERNOS que define un objeto COFF (el '.obj' de Windows).
// Es la misma lectura que 'definidos_coff' de 'runtime/extern_cpp.py'.
std::vector<std::string> definidos_coff(const std::string& contenido);

}  // namespace suriax::mir

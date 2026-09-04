// RESOLUCION del HIR: pasar de leerlo a entenderlo.
//
// 'view.hpp' demuestra que el lector RECORRE todo lo que el emisor escribe;
// esto demuestra que lo ENTIENDE. Son preguntas distintas: imprimir
// 'foo(2, 3)' no exige saber a que 'foo' se llama, si tiene cuerpo o si la
// aridad cuadra — y eso es exactamente lo que un MIR necesita antes de poder
// bajar nada.
//
// Lo que se resuelve, y por que cada cosa:
//
//   * cada FUNCION de la imagen, con sus SLOTS (parametros y locales
//     numerados en un solo espacio, como los numera WebAssembly). Es lo
//     primero que un MIR asigna, y numerarlos aqui evita que cada backend
//     invente su propia numeracion;
//   * cada SITIO DE LLAMADA, con a QUE se resuelve: una funcion de una
//     unidad concreta, un prototipo que aporta el host, un hook, o nada. Un
//     'no se a que llama esto' es un agujero del backend y tiene que verse;
//   * cada DESTRUCCION de bloque, con el hook ya ligado a su funcion. El
//     frontend decidio DONDE muere cada valor; aqui se comprueba que el
//     destructor que nombra existe de verdad en la imagen.
//
// El resultado NO es un arbol nuevo: apunta al de protobuf, que la 'Image'
// mantiene vivo. Materializar un modelo paralelo seria una tercera
// definicion del mismo esquema que mantener sincronizada con el '.proto'
// (mismo motivo que da 'loader.hpp' para trabajar sobre los mensajes).
//
// Errores por LISTA y no por excepciones, como el resto del backend: lo que
// no se pudo resolver se acumula con su posicion y el llamador decide.
#pragma once

#include <cstdint>
#include <ostream>
#include <string>
#include <unordered_map>
#include <vector>

#include "suriax/hir/loader.hpp"

namespace suriax::hir {

// A que se resolvio un sitio de llamada.
enum class CallTarget {
    // funcion con cuerpo en alguna unidad de la imagen: 'index' la nombra.
    Function,
    // prototipo sin cuerpo ('fn __write__(str) -> void;'): lo aporta quien
    // ejecuta. No es un fallo — es el contrato de la frontera con el host.
    Host,
    // llamada que despacha por hook ('print(x)', 'x[i]'): el nodo trae su
    // 'HookRef' ya resuelto contra la tabla de la imagen.
    Hook,
    // metodo de un tipo ('v.push(x)'): un 'dunder' de nombre llano, indexado
    // por (dueno, nombre) igual que en el interprete.
    Method,
    // hook NATIVO de un primitivo ('len(s)', 's[i]'): su dueno es 'str', y
    // ninguna unidad puede declararlo (SEM006 prohibe colgarle hooks a un
    // primitivo). Lo implementa el backend, no la imagen — por eso no esta en
    // la tabla y no es un agujero.
    Native,
    // constructor de una variante de enum con payload ('Nodo.Literal(5)').
    Variant,
    // no se pudo decidir: es un agujero, y por eso tiene su propia categoria
    // en vez de confundirse con 'Host'.
    Unresolved,
};

const char* to_string(CallTarget target);

// Un slot del marco de una funcion: parametros primero y locales despues, en
// un solo espacio de indices — como los numera WebAssembly, y como los
// numerara el MIR.
struct Slot {
    std::string name;
    std::uint32_t type_id = 0;
    bool parameter = false;
};

// Un sitio de llamada ya decidido.
struct Call {
    std::uint32_t line = 0;
    std::uint32_t col = 0;
    std::string name;               // como se escribio ('stdp.println')
    CallTarget target = CallTarget::Unresolved;
    // indice en 'Program::functions' cuando 'target' es Function; -1 si no.
    int index = -1;
    std::string detail;             // por que, cuando no se resolvio
};

// Una destruccion que el frontend inserto al cerrar un bloque.
struct Drop {
    std::string path;               // 'caja.dentro'
    // el hook que la ejecuta, como se lee: 'R.__free__'. El nombre suelto no
    // sirve — viaja VACIO en todo hook del vocabulario fijo, que son
    // justamente los destructores.
    std::string hook;
    bool bound = false;             // ¿esta en la tabla de la imagen?
};

// Una funcion de la imagen, con lo que un MIR necesita saber de ella.
struct Function {
    std::string unit;               // alias de la unidad ('IO.stdp'); "" = main
    std::string name;
    const pb::FunctionDecl* decl = nullptr;   // propiedad de la Unit
    // posicion de la DECLARACION. Vive en el 'Decl' que la envuelve, no en
    // el 'FunctionDecl', asi que se copia aqui: sin ella una etapa posterior
    // no puede decir DONDE esta la funcion que no supo bajar.
    std::uint32_t line = 0;
    std::uint32_t col = 0;
    std::vector<Slot> slots;
    std::uint32_t result_type = 0;
    bool prototype = false;         // sin cuerpo: lo aporta el host
    std::vector<Call> calls;
    std::vector<Drop> drops;
};

// La imagen entendida.
struct Program {
    std::vector<Function> functions;
    // 'unidad::nombre' -> indice en 'functions'. La clave la construye un
    // solo sitio ('key'), igual que en el interprete.
    std::unordered_map<std::string, std::size_t> index;
    // '(dueno, metodo)' -> indice. Un metodo no se puede buscar por nombre a
    // secas: dos tipos pueden declarar 'get', y el dueno es lo que los
    // separa — la misma clave que 'SymbolTable.dunders'.
    std::unordered_map<std::string, std::size_t> methods;
    // entrada del programa, o -1 si la imagen no declara 'main'.
    int entry = -1;
    // lo que no se pudo resolver, con su posicion. Vacia = el backend
    // entiende la imagen entera.
    std::vector<Call> unresolved;

    static std::string key(const std::string& unit, const std::string& name);
};

// Recorre la imagen y devuelve el programa resuelto.
//
// No falla: lo que no se entiende queda en 'unresolved' con su posicion, que
// es mas util que abortar en el primer nodo raro.
Program resolve(const Image& image);

// El programa resuelto, en texto: una linea por funcion con sus slots, sus
// llamadas y sus destrucciones. Es la forma de comprobar a ojo (y en un
// test) que el backend entendio lo mismo que el resto de consumidores.
void write_resolved(const Program& program, std::ostream& out);

}  // namespace suriax::hir

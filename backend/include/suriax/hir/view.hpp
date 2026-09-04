// Vistas del HIR ya leido: la LEGIBLE y el RESUMEN.
//
// No son adornos del CLI: son la unica forma de demostrar que el lector C++
// entendio lo mismo que los otros consumidores. La vista legible es
// byte-identica a la que produce 'V0/src/HIR/pretty.py' (--hir-pretty) y el
// resumen a 'runtime/interpreter/loader.summarize', asi que compararlas es
// el diferencial ENTRE CONSUMIDORES que pide 'compiler-ir-testing': el mismo
// '.phir' tiene que significar lo mismo para todo el que lo lee.
//
// Esa identidad byte a byte es una decision, no una casualidad. Una vista
// "parecida" no prueba nada — el diferencial solo sirve mientras la
// comparacion sea exacta. Si el formato de 'pretty.py' cambia, este archivo
// cambia con el y el test lo dice el mismo dia.
//
// El recorrido tambien es el 'switch' exhaustivo por 'oneof' que congela el
// contrato: cada caso que el esquema declara tiene su rama, y un nodo cuyo
// caso el lector no conoce se ANOTA con su posicion en vez de saltarse
// (espejo de '_error_unsupported' del emisor). Sin ese fail-fast, una
// construccion nueva del lenguaje cruzaria la frontera en silencio.
#pragma once

#include <cstdint>
#include <ostream>
#include <string>
#include <vector>

#include "suriax/hir/loader.hpp"

namespace suriax::hir {

// Un nodo que el lector no supo interpretar, con la posicion del fuente.
// Que la lista quede vacia es la prueba de que el despacho esta completo.
struct Unknown {
    std::string what;  // 'Expr' | 'Stmt' | 'Decl'
    std::string node;  // el caso del oneof, o "vacio" si no habia ninguno
    std::uint32_t line = 0;
    std::uint32_t col = 0;
};

// 'Type' -> notacion de suriaX ('int ptr mutable', 'T?', 'error int',
// 'Vector<int>'). Fuente unica de la notacion en este lado, igual que
// 'V0/src/HIR/pretty.format_type' lo es en Python — la definicion de
// referencia, que este archivo y 'web/src/hir/schema.ts' copian.
//
// Se escribe TODO lo que participa de la identidad del tipo. Que no fuera
// asi costaba informacion en las dos preguntas que mas se hacen al depurar:
// 'error int' se veia como 'error' y 'Vector<int>' como 'Vector'.
std::string format_type(const pb::Type& type);

// Identidad ESTRUCTURAL de un tipo, como cadena canonica. Espejo de
// 'runtime/interpreter/hook/dispatch.type_key': es la clave con la que se
// indexan las conversiones, y no la notacion, porque un indice no puede
// depender de que dos tipos distintos nunca se escriban igual.
std::string type_key(const pb::Type& type);

// Escribe la vista LEGIBLE del modulo en 'out', en streaming (nunca arma la
// cadena completa en memoria: el texto de protobuf llegaba a 24 MB en los
// programas mas grandes del repositorio, y ese fue el motivo de esta vista).
// Los nodos no reconocidos se acumulan en 'unknown'.
void write_pretty(const pb::Module& module, std::ostream& out,
                  std::vector<Unknown>& unknown);

// Escribe el RESUMEN del modulo: simbolos, hooks e items, sin ejecutarlo.
void write_summary(const pb::Module& module, std::ostream& out);

// Un bloque '#extern cpp{ ... }' que cruzo la frontera.
struct ExternBlock {
    std::string unit;    // alias de la unidad de la que salio ("" = el main)
    std::string source;  // el .srcx de esa unidad, para el '#line'
    std::string target;  // hoy solo "cpp"
    std::string raw;     // el C++ tal cual lo capturo el lexer
    std::uint32_t line = 0;
    std::uint32_t col = 0;
};

// Recoge los bloques '#extern' de TODAS las unidades de la imagen, en el
// orden en que aparecen (main al final, como los inicializa el interprete).
std::vector<ExternBlock> collect_extern(const Image& image);

// Escribe los bloques como UNA unidad de traduccion de C++.
//
// Es donde el '#extern cpp' aterriza de verdad: el lexer lo capturo crudo, la
// Semantica no lo miro y el HIR lo transporto intacto — aqui se convierte en
// un archivo que un compilador de C++ puede leer. Compilarlo y enlazarlo es
// del backend nativo, que todavia no existe; producirlo ya no.
//
// Cada bloque va precedido de un '#line': asi los errores del compilador de
// C++ apuntan al '.srcx' del usuario y no a un archivo generado que nadie
// escribio. Es la trazabilidad que evita depurar codegen a ciegas.
//
// Devuelve false (y escribe el porque en 'error') si algun bloque declara un
// target que este backend no conoce.
bool write_extern_cpp(const std::vector<ExternBlock>& blocks, std::ostream& out,
                      std::string& error);

}  // namespace suriax::hir

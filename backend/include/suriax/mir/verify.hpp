// Verificacion de PROPIEDAD y PRESTAMOS sobre el MIR.
//
// Es la comprobacion que el ROADMAP (Fase 6) pone en esta etapa y no antes, y
// la razon es el CFG: las preguntas que responde —¿este valor ya se
// transfirio cuando se lee?, ¿este puntero sigue apuntando a algo vivo?— son
// preguntas sobre CAMINOS, y el HIR no tiene caminos, tiene arboles. Sobre un
// arbol solo se puede contestar "hay un move en algun sitio"; sobre el grafo
// se contesta "en este punto, por todos los caminos que llegan aqui, el valor
// ya no es suyo".
//
// El frontend ya rechaza lo que se puede rechazar mirando una sentencia, y el
// interprete caza en EJECUCION lo que se le escapa (RT001). Esto es lo que
// falta entre las dos: un error de propiedad no deberia depender de que la
// rama que lo contiene llegue a ejecutarse.
//
// Analisis de flujo hacia ADELANTE con un reticulo de tres valores por slot:
//
//     NoInicializado  ->  Vivo  ->  Movido
//                          \        /
//                           QuizaMovido      (la union de Vivo y Movido)
//
// Unir dos caminos toma el peor de los dos: si por uno llega vivo y por otro
// movido, leerlo es un error igual, porque el programa no sabe por cual vino.
// Es la unica respuesta honesta sin ejecutar.
//
// LO QUE TODAVIA NO MIRA, dicho aqui para que no se confunda con lo que sí:
// el seguimiento de préstamos es local a un bloque. Prestar en una rama y
// transferir en otra no se cruza — hacerlo pide llevar el conjunto de
// préstamos vivos por el mismo punto fijo que el estado de los slots, y eso
// es la extensión natural de esto, no un remiendo. La propiedad (mover y
// leer) sí cruza el grafo entero, que es donde estaban los errores que este
// análisis existe para encontrar.
//
// No lanza: los hallazgos salen por lista, como en todo el backend.
#pragma once

#include <cstdint>
#include <ostream>
#include <string>
#include <vector>

#include "suriax/mir/mir.hpp"

namespace suriax::mir {

// Un problema encontrado, ya redactado. 'certain' distingue "pasa siempre"
// de "pasa por algun camino": las dos son errores, pero decirlo cambia como
// se lee el mensaje.
struct Finding {
    std::string function;
    std::string what;
    std::uint32_t line = 0;
    std::uint32_t col = 0;
    bool certain = true;
};

// Recorre el programa entero. Lista vacia = el MIR respeta la propiedad.
std::vector<Finding> verify(const Program& program);

void write_findings(const std::vector<Finding>& findings, std::ostream& out);

}  // namespace suriax::mir

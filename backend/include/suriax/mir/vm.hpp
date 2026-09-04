// La VM que ejecuta el MIR: el target NATIVO empezando a correr.
//
// Es un interprete de REGISTROS, no de pila, porque el MIR lo es (ver
// 'mir.hpp'). Cada marco lleva sus slots y sus registros virtuales en dos
// vectores planos, y ejecutar es recorrer bloques hasta un 'Return'.
//
// Sobre el JIT: esta VM es su requisito, no su sustituto. Un JIT compila lo
// que la VM ya sabe ejecutar —necesita el mismo modelo de marco, la misma
// semantica de cada instruccion y algo con lo que comparar sus resultados—,
// asi que tenerla correcta primero es lo que permite que el JIT sea una
// optimizacion y no un segundo lenguaje.
//
// Semantica: la MISMA que el interprete de Python, y eso es una obligacion,
// no una coincidencia. Los enteros son de 64 bits y ENVUELVEN; la division
// entera trunca hacia cero; dividir por cero entre enteros es un error y
// entre flotantes da el infinito de IEEE-754. Un backend que discrepe en
// cualquiera de esas ejecuta otro programa, y el diferencial contra el
// interprete es lo que lo caza.
//
// Errores por CODIGO de estado y no por excepciones, como el resto del
// backend: la VM la enlazara codigo que quiza no tenga runtime de
// excepciones.
#pragma once

#include <cstdint>
#include <string>

#include "suriax/mir/mir.hpp"

namespace suriax::mir {

// Un valor de la VM. Sin etiqueta: el MIR ya es tipado (hay 'AddI' y 'AddF'),
// asi que cada instruccion sabe que mitad mirar. Etiquetarlo costaria una
// comprobacion por operacion para responder algo que ya se sabe al compilar.
union Value {
    std::int64_t i;
    double f;
};

// Como termino la ejecucion.
struct RunStatus {
    bool ok = true;
    std::string error;        // que fallo, ya redactado para un humano
    std::uint32_t line = 0;   // y donde
    std::uint32_t col = 0;
    std::int64_t exit = 0;    // el valor que devolvio la entrada
    // Una excepcion que sigue subiendo. No es '!ok': un 'throw' es control de
    // flujo del programa —lo puede atrapar el llamador— y solo se convierte
    // en fallo si nadie lo hace.
    bool thrown = false;
    std::int64_t thrown_value = 0;
    std::int64_t thrown_tag = -1;

    static RunStatus failure(std::string message, std::uint32_t ln,
                             std::uint32_t col) {
        return RunStatus{false, std::move(message), ln, col, 0};
    }
};

// Limite de PASOS: un programa que no termina no puede colgar al que lo
// ejecuta. Cero = sin limite.
inline constexpr std::uint64_t kDefaultStepLimit = 100'000'000;

// Ejecuta 'program' desde su entrada. No lanza.
RunStatus run(const Program& program,
              std::uint64_t step_limit = kDefaultStepLimit);

}  // namespace suriax::mir

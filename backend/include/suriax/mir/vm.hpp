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

#include <iosfwd>

#include <cstdint>
#include <map>
#include <string>
#include <vector>

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
// ejecuta. Cero = sin limite ('suriax-hir --pasos N').
inline constexpr std::uint64_t kDefaultStepLimit = 100'000'000;

// Limite de MEMORIA del programa, en bytes ('suriax-hir --memoria-max'): lo
// que la VM contabiliza de lo que el PROGRAMA crea —los campos de sus
// objetos y bloques (8 bytes cada uno), los bloques de 'byte' (uno por
// celda) y el texto de las cadenas que crea al ejecutar—. No es la memoria
// del proceso: lo que la VM usa para si misma no cuenta, y por eso el limite
// es el mismo en todos los sistemas. Cero = sin limite (el defecto). Es para
// maquinas con poca memoria: cortar con un error que dice donde, en vez de
// que el sistema mate el proceso.
inline constexpr std::uint64_t kSinLimiteDeMemoria = 0;

// Lo que la VM sabe de su memoria al terminar ('suriax-hir --run --memoria').
// Un programa que libera todo lo que crea termina con 'vivos == 0'.
struct Memoria {
    std::uint64_t creados = 0;
    std::uint64_t liberados = 0;
    std::uint64_t vivos = 0;
    std::uint64_t maximo = 0;       // el pico de objetos vivos a la vez
    // los BYTES del programa (ver 'kSinLimiteDeMemoria'): los vivos al
    // terminar y el pico
    std::uint64_t bytes = 0;
    std::uint64_t bytes_maximo = 0;
    // los que quedaron vivos, por tipo ("vector.Vector<int>", "bloque de
    // Punto", "objeto"): es lo que dice DONDE esta una fuga
    std::map<std::string, std::uint64_t> vivos_por_tipo;
    // las CADENAS que el programa crea al ejecutar (concatenar, interpolar,
    // leer un archivo); las constantes del fuente no cuentan
    std::uint64_t cadenas_creadas = 0;
    std::uint64_t cadenas_recogidas = 0;
    std::uint64_t cadenas_vivas = 0;
};

// Ejecuta 'program' desde su entrada. No lanza.
//
// 'traza': si no es nulo, cada llamada y cada retorno se escriben ahi
// ("[call] f (profundidad)" / "[ret ] f"), lo mismo que '--trace-exec' en el
// interprete. Es lo que permite ver POR DONDE va una ejecucion que diverge.
//
// 'argumentos': lo que ve 'sistema.argumento(i)'. El 0 es el archivo que se
// ejecuta, como en el interprete.
// 'externos': paralelo a 'program.hosts', el simbolo de C++ que cumple
// cada primitiva ('#extern cpp', ver 'externo.hpp'); nullptr = la cumple la
// VM. Sin tabla, ninguna la cumple C++.
using FuncionExterna = void (*)();
RunStatus run(const Program& program,
              std::uint64_t step_limit = kDefaultStepLimit,
              std::ostream* traza = nullptr,
              std::vector<std::string> argumentos = {},
              Memoria* memoria = nullptr,
              const std::vector<FuncionExterna>* externos = nullptr,
              std::uint64_t limite_bytes = kSinLimiteDeMemoria);

}  // namespace suriax::mir

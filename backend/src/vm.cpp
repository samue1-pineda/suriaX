#include "suriax/mir/vm.hpp"
#include "suriax/mir/externo.hpp"
#include "suriax/mir/rutas.hpp"

#include <algorithm>
#include <charconv>
#include <cmath>
#include <cstdlib>
#include <cstring>
#include <deque>
#include <filesystem>
#include <fstream>
#include <cstdint>
#include <cstdio>
#include <limits>
#include <iomanip>
#include <sstream>
#include <string>
#include <string_view>
#include <unordered_map>
#include <vector>

namespace suriax::mir {
namespace {

// Profundidad maxima de llamadas. Una recursion sin caso base agotaria la
// pila del PROCESO y se llevaria por delante al que ejecuta; con un limite
// se convierte en un error con posicion, que es lo que hace el interprete.
constexpr std::size_t kMaxDepth = 4096;

// Un marco: los slots del programa y los registros virtuales del MIR. Dos
// vectores planos y no un mapa — los indices son densos y consecutivos, que
// es justo la propiedad por la que el MIR usa registros numerados.
struct Frame {
    std::vector<Value> slots;
    std::vector<Value> regs;
    // un byte por slot, solo si la funcion mueve o libera algun local:
    // 0 vivo, 1 movido, 2 liberado (el 'CellState' del interprete)
    std::vector<std::uint8_t> estado;
    const Function* fn = nullptr;
};

// Los CODE POINTS de una cadena UTF-8. El 'char' de suriaX es un punto de
// codigo, no un byte: 'len' cuenta puntos y 's[i]' devuelve el i-esimo, y las
// dos preguntas tienen que contar lo mismo.
std::vector<std::uint32_t> puntos_de_codigo(const std::string& texto) {
    std::vector<std::uint32_t> salida;
    for (std::size_t i = 0; i < texto.size();) {
        const unsigned char c = static_cast<unsigned char>(texto[i]);
        std::size_t largo = 1;
        std::uint32_t punto = c;
        if ((c & 0xE0u) == 0xC0u) { largo = 2; punto = c & 0x1Fu; }
        else if ((c & 0xF0u) == 0xE0u) { largo = 3; punto = c & 0x0Fu; }
        else if ((c & 0xF8u) == 0xF0u) { largo = 4; punto = c & 0x07u; }
        for (std::size_t j = 1; j < largo && i + j < texto.size(); ++j) {
            punto = (punto << 6) |
                    (static_cast<unsigned char>(texto[i + j]) & 0x3Fu);
        }
        salida.push_back(punto);
        i += largo;
    }
    return salida;
}

// 'cast<int8>(300)' -> 44: se queda con los bits bajos y reinterpreta la
// mitad alta como negativa (complemento a dos, como C). En aritmetica sin
// signo, que es donde el desborde esta definido.
std::int64_t angosta_entero(std::int64_t valor, std::int64_t bits) {
    const std::uint64_t modulo = std::uint64_t{1} << bits;
    const std::uint64_t bajos = static_cast<std::uint64_t>(valor) & (modulo - 1);
    if (bajos >= (modulo >> 1)) {
        return -static_cast<std::int64_t>(modulo - bajos);
    }
    return static_cast<std::int64_t>(bajos);
}

// Redondeo a IEEE-754 binary32, con el desborde a infinito explicito: en C++
// convertir a 'float' un valor fuera de rango es indefinido, y un 'cast' no
// puede depender de eso. El umbral es el punto medio entre FLT_MAX y 2^128.
double a_binary32(double x) {
    if (!std::isfinite(x)) return x;
    const double umbral = std::ldexp(2.0 - std::ldexp(1.0, -24), 127);
    if (std::fabs(x) >= umbral) return std::copysign(HUGE_VAL, x);
    return static_cast<double>(static_cast<float>(x));
}

// Redondeo a IEEE-754 binary16 (11 bits de significando, exponente minimo
// -14, subnormales hasta 2^-24), al par mas cercano como 'struct.pack("e")'.
// C++20 no trae 'std::float16_t', asi que se hace a mano: dividir por el
// cuanto del binade es exacto (potencia de dos) y 'nearbyint' redondea al par.
double a_binary16(double x) {
    if (!std::isfinite(x) || x == 0.0) return x;
    const double magnitud = std::fabs(x);
    if (magnitud >= 65520.0) return std::copysign(HUGE_VAL, x);   // > 65504
    int exponente = 0;
    // magnitud = m * 2^exponente, m en [0.5, 1): solo interesa el exponente
    static_cast<void>(std::frexp(magnitud, &exponente));
    const int cuanto = std::max(exponente - 11, -24);
    const double redondeado =
        std::ldexp(std::nearbyint(std::ldexp(magnitud, -cuanto)), cuanto);
    return std::copysign(redondeado, x);
}

// Un float escrito EXACTAMENTE como 'str(x)' de Python, que es lo que hace
// el interprete: los MENOS digitos que reproducen el valor ('0.1', no
// '0.10000000000000001'), notacion cientifica si el exponente es < -4 o
// >= 16 ('1e+16', '1.5e-05'), y siempre con parte decimal ('4.0').
// 'setprecision(17)' daba 17 digitos fijos: PI salia '3.1415926535897931'.
std::string flotante_como_python(double x) {
    if (std::isnan(x)) return "nan";
    if (std::isinf(x)) return x > 0 ? "inf" : "-inf";
    char buf[64];
    // 'scientific' sin precision = los digitos mas cortos que ida y vuelta
    // dan el mismo double (C++17)
    const auto r = std::to_chars(buf, buf + sizeof buf, x, std::chars_format::scientific);
    std::string s(buf, r.ptr);
    const bool negativo = !s.empty() && s[0] == '-';
    if (negativo) s.erase(0, 1);
    const std::size_t e = s.find('e');
    const int exponente = std::stoi(s.substr(e + 1));
    std::string digitos;
    for (std::size_t i = 0; i < e; ++i) {
        if (s[i] != '.') digitos += s[i];
    }
    std::string salida;
    if (exponente >= -4 && exponente < 16) {
        if (exponente >= 0) {
            const auto enteros = static_cast<std::size_t>(exponente) + 1;
            if (digitos.size() <= enteros) {
                salida = digitos + std::string(enteros - digitos.size(), '0') + ".0";
            } else {
                salida = digitos.substr(0, enteros) + "." + digitos.substr(enteros);
            }
        } else {
            salida = "0." + std::string(static_cast<std::size_t>(-exponente - 1), '0') +
                     digitos;
        }
    } else {
        salida = digitos.substr(0, 1);
        if (digitos.size() > 1) salida += "." + digitos.substr(1);
        char exp[8];
        std::snprintf(exp, sizeof exp, "e%c%02d", exponente < 0 ? '-' : '+',
                      exponente < 0 ? -exponente : exponente);
        salida += exp;
    }
    return negativo ? "-" + salida : salida;
}

// Una cadena vista como code points (ver 'Machine::puntos_').
struct Puntos {
    bool ascii = true;
    std::size_t largo = 0;
    std::vector<std::uint32_t> puntos;   // vacio si 'ascii'
};

// Un objeto del monton: los campos de un struct (o las celdas de un bloque de
// 'mem'), por indice.
//
// El valor de un objeto es un HANDLE, no el objeto: asi cabe en un registro y
// se pasa como un entero. El handle son dos mitades:
//
//     bits 0..31   el indice del objeto en el monton
//     bits 32..62  su GENERACION
//
// Liberar un objeto devuelve su hueco a una lista y sube su generacion, asi
// que el hueco se reutiliza sin que un handle viejo lo alcance: el objeto
// nuevo tiene otra generacion y el acceso por el handle viejo es RT003 (uso
// despues de liberar), no una lectura del objeto de otro. La generacion
// empieza en 1: ningun handle vale 0 (una celda sin usar) ni -1 (un campo
// cedido, un 'null'), y un entero pequeno nunca parece un handle.
//
// No hay recolector: cada objeto tiene UN dueno —ligar copia— y muere donde
// muere su dueno. Es el modelo de propiedad del lenguaje; la VM solo cumple
// lo que el MIR le dice ('Free', 'Copy').
struct Objeto {
    std::vector<Value> campos;
    // Un bloque de 'byte' guarda sus celdas AQUI, una por byte, y no en
    // 'campos' (8 bytes cada una): es lo que hace que un archivo de 1 MB
    // ocupe 1 MB. Es tambien el 'uint8_t*' que ve un '#extern cpp'.
    std::vector<std::uint8_t> octetos;
    std::uint32_t generacion = 1;
    std::int32_t layout = -1;        // su FORMA (Program::layouts)
    std::int32_t elem_layout = -1;   // bloque: la forma de sus celdas
    bool vivo = false;
    bool bloque = false;
    bool de_bytes = false;           // bloque de 'byte': las celdas son 'octetos'

    std::size_t celdas() const { return de_bytes ? octetos.size() : campos.size(); }
};


// La division entera TRUNCA HACIA CERO (como C y como 'i64.div_s'), no hacia
// abajo. Va junto al resto porque las dos operaciones se sostienen: con este
// cociente y aquel resto se cumple '(a/b)*b + a%b == a'.
std::int64_t div_trunc(std::int64_t a, std::int64_t b) {
    // INT_MIN / -1 desborda: en complemento a dos el resultado no cabe. Se
    // envuelve, que es lo que hace la maquina y lo que hace el interprete.
    if (a == std::numeric_limits<std::int64_t>::min() && b == -1) return a;
    return a / b;
}

std::int64_t rem_trunc(std::int64_t a, std::int64_t b) {
    if (a == std::numeric_limits<std::int64_t>::min() && b == -1) return 0;
    return a % b;
}

class Machine {
public:
    Machine(const Program& program, std::uint64_t limite, std::ostream* traza,
            std::vector<std::string> argumentos,
            const std::vector<FuncionExterna>* externos = nullptr,
            std::uint64_t limite_bytes = kSinLimiteDeMemoria)
        : program_(program), limite_(limite), limite_bytes_(limite_bytes),
          traza_(traza), argumentos_(std::move(argumentos)), externos_(externos) {
        globales_.assign(program.globals.size(), Value{0});
        for (const std::string& texto : program.strings) {
            textos_.push_back(texto);
            muerta_.push_back(0);
            indice_de_texto_.emplace(textos_.back(),
                                     static_cast<std::int64_t>(textos_.size() - 1));
        }
        constantes_ = textos_.size();
    }

    RunStatus call(std::size_t indice, const std::vector<Value>& args,
                   Value& salida) {
        const Function& fn = program_.functions[indice];
        if (depth_ >= kMaxDepth) {
            // las mismas palabras que el interprete: nombra la funcion
            return RunStatus::failure(
                "RT019: desbordamiento de pila al llamar a '" + fn.name + "': " +
                    std::to_string(depth_) + " llamadas anidadas (¿una recursión "
                    "sin caso base?)", 0, 0);
        }
        if (fn.blocks.empty()) {
            return RunStatus::failure(
                "la funcion '" + fn.name + "' no tiene cuerpo en el MIR" +
                    (fn.prototype ? " (es un prototipo: lo aporta el host, y "
                                    "la VM todavia no liga prototipos)" : ""),
                0, 0);
        }

        Frame frame;
        frame.fn = &fn;
        frame.slots.assign(fn.slots.size(), Value{0});
        frame.regs.assign(fn.regs, Value{0});
        if (fn.vigila_estado) frame.estado.assign(fn.slots.size(), 0);
        for (std::size_t i = 0; i < args.size() && i < fn.params; ++i) {
            frame.slots[i] = args[i];
        }

        if (traza_ != nullptr) {
            *traza_ << "[call] " << fn.name << " (" << depth_ << ")\n";
        }
        ++depth_;
        marcos_.push_back(&frame);
        const RunStatus status = ejecutar(fn, frame, salida);
        marcos_.pop_back();
        --depth_;
        if (traza_ != nullptr) {
            *traza_ << "[ret ] " << fn.name
                    << (status.thrown ? "  (lanza)" : "") << "\n";
        }
        return status;
    }

private:
    RunStatus ejecutar(const Function& fn, Frame& frame, Value& salida) {
        BlockId actual = 0;
        while (true) {
            // el inicio de un bloque es un punto SEGURO para recoger
            // cadenas: ninguna instruccion esta a medias con un puntero a
            // una cadena en la mano
            if (barrido_pendiente_) barrer_cadenas();
            if (actual >= fn.blocks.size()) {
                return RunStatus::failure("salto a un bloque que no existe",
                                          0, 0);
            }
            const Block& bloque = fn.blocks[actual];
            bool atrapada = false;
            for (const Inst& inst : bloque.insts) {
                if (limite_ != 0 && ++pasos_ > limite_) {
                    return RunStatus::failure(
                        "RT010: limite de pasos alcanzado (" +
                            std::to_string(limite_) + "): el programa no "
                            "termina o hace falta subir el limite",
                        inst.line, inst.col);
                }
                RunStatus status = ejecutar_inst(inst, frame);
                // la instruccion que se paso de la memoria es la que se
                // reporta: es la que reservo (o concateno) de mas. Antes se
                // RECOGEN las cadenas que ya nadie usa (como una JVM antes de
                // un OutOfMemoryError): sin eso, un programa correcto fallaria
                // por basura que el barrido todavia no paso a buscar. Entre
                // dos instrucciones todo valor vivo esta en un marco, una
                // global o un campo; si la instruccion LANZO, el valor viaja
                // en 'status' y no se barre: se vuelve a mirar en la siguiente.
                if (excedida_ && status.ok && !status.thrown) {
                    barrer_cadenas();
                    if (memoria_.bytes <= limite_bytes_) excedida_ = false;
                }
                if (excedida_ && status.ok && !status.thrown) {
                    return RunStatus::failure(
                        "RT023: memoria maxima alcanzada (" +
                            std::to_string(limite_bytes_) + " bytes): el programa "
                            "llego a usar " + std::to_string(memoria_.bytes) +
                            "; sube --memoria-max o revisa que no acumule",
                        inst.line, inst.col);
                }
                if (status.thrown) {
                    // una llamada lanzo: si este bloque esta protegido, el
                    // control salta a su pad con el valor y su etiqueta.
                    if (bloque.handler < 0) return status;
                    frame.slots[static_cast<std::size_t>(fn.throw_slot)]
                        .i = status.thrown_value;
                    frame.slots[static_cast<std::size_t>(fn.tag_slot)]
                        .i = status.thrown_tag;
                    atrapada = true;
                    break;
                }
                if (!status.ok) return status;
            }

            if (atrapada) {
                actual = static_cast<BlockId>(bloque.handler);
                continue;
            }

            switch (bloque.term) {
                case Term::Jump:
                    actual = bloque.target;
                    break;
                case Term::Branch:
                    actual = frame.regs[bloque.cond].i != 0 ? bloque.target
                                                            : bloque.otherwise;
                    break;
                case Term::Return:
                    salida = bloque.has_value ? frame.regs[bloque.value]
                                              : Value{0};
                    return RunStatus{};
                case Term::Throw: {
                    const std::int64_t valor = frame.regs[bloque.value].i;
                    // -1 = relanzar lo que ya viajaba: la etiqueta original,
                    // no la del sitio que lo vuelve a soltar.
                    const std::int64_t tag =
                        bloque.tag >= 0
                            ? bloque.tag
                            : frame.slots[static_cast<std::size_t>(
                                  fn.tag_slot)].i;
                    if (bloque.handler >= 0) {
                        frame.slots[static_cast<std::size_t>(fn.throw_slot)]
                            .i = valor;
                        frame.slots[static_cast<std::size_t>(fn.tag_slot)]
                            .i = tag;
                        actual = static_cast<BlockId>(bloque.handler);
                        break;
                    }
                    RunStatus fuera;
                    fuera.thrown = true;
                    fuera.thrown_value = valor;
                    fuera.thrown_tag = tag;
                    return fuera;
                }
                case Term::Unreachable:
                    return RunStatus::failure(
                        "se alcanzo un bloque sin terminador: el lowering "
                        "dejo el grafo abierto", 0, 0);
            }
        }
    }

    RunStatus ejecutar_inst(const Inst& inst, Frame& frame) {
        const auto reg = [&frame](Reg r) -> Value& { return frame.regs[r]; };

        switch (inst.op) {
            case Op::ConstI: reg(inst.dst).i = inst.imm; return RunStatus{};
            case Op::ConstF: reg(inst.dst).f = inst.fimm; return RunStatus{};
            // una cadena es el INDICE de su constante: comparar dos cadenas
            // constantes es comparar dos enteros, y da la respuesta correcta
            // porque se internan por texto.
            case Op::ConstStr: reg(inst.dst).i = inst.imm; return RunStatus{};
            case Op::LoadGlobal:
                reg(inst.dst) = globales_[inst.slot];
                return RunStatus{};
            case Op::StoreGlobal:
                globales_[inst.slot] = reg(inst.a);
                return RunStatus{};

            case Op::IntToFloat:
                reg(inst.dst).f = static_cast<double>(reg(inst.a).i);
                return RunStatus{};
            case Op::NarrowI:
                reg(inst.dst).i = angosta_entero(reg(inst.a).i, inst.imm);
                return RunStatus{};
            case Op::NarrowF:
                reg(inst.dst).f = inst.imm == 16 ? a_binary16(reg(inst.a).f)
                                                 : a_binary32(reg(inst.a).f);
                return RunStatus{};
            case Op::FloatToInt: {
                // SATURA en vez de desbordar: convertir un NaN o un infinito
                // con 'static_cast' es comportamiento indefinido en C++, y un
                // 'cast' no deberia poder producir basura. Es la misma
                // decision que el target web ('i64.trunc_sat_f64_s').
                const double v = reg(inst.a).f;
                if (std::isnan(v)) reg(inst.dst).i = 0;
                else if (v >= 9223372036854775808.0) {
                    reg(inst.dst).i = std::numeric_limits<std::int64_t>::max();
                } else if (v <= -9223372036854775808.0) {
                    reg(inst.dst).i = std::numeric_limits<std::int64_t>::min();
                } else {
                    reg(inst.dst).i = static_cast<std::int64_t>(v);
                }
                return RunStatus{};
            }

            case Op::Alloc:
                reg(inst.dst).i = nuevo_objeto(static_cast<std::size_t>(inst.imm),
                                               inst.layout);
                return RunStatus{};
            case Op::GetField: {
                Objeto* obj = nullptr;
                RunStatus estado = valida_campo(inst, reg(inst.a).i, obj);
                if (!estado.ok) return estado;
                reg(inst.dst) = obj->campos[static_cast<std::size_t>(inst.imm)];
                return RunStatus{};
            }
            case Op::SetField: {
                Objeto* obj = nullptr;
                RunStatus estado = valida_campo(inst, reg(inst.a).i, obj);
                if (!estado.ok) return estado;
                obj->campos[static_cast<std::size_t>(inst.imm)] = reg(inst.b);
                return RunStatus{};
            }
            case Op::Copy: {
                const std::int64_t origen = reg(inst.a).i;
                // copiar un 'T?' que vale null da null: no hay objeto
                if (origen == -1) {
                    reg(inst.dst).i = -1;
                    return RunStatus{};
                }
                if (objeto(origen) == nullptr) {
                    return no_es_objeto(inst, origen, "copiar");
                }
                reg(inst.dst).i = copiar(origen);
                return RunStatus{};
            }
            case Op::Free:
                liberar(reg(inst.a).i);
                return RunStatus{};
            case Op::Fallar: {
                const std::string* texto = cadena(inst.imm);
                return RunStatus::failure(texto != nullptr ? *texto : "fallo",
                                          inst.line, inst.col);
            }
            case Op::FreeLanzado: {
                const std::int64_t valor = reg(inst.a).i;
                if (es_objeto_lanzado(valor, reg(inst.b).i)) liberar(valor);
                return RunStatus{};
            }
            case Op::Destruir: {
                const std::int64_t valor = reg(inst.a).i;
                if (inst.b != kNoReg && !es_objeto_lanzado(valor, reg(inst.b).i)) {
                    return RunStatus{};
                }
                if (inst.imm == 1) {
                    const Objeto* obj = objeto(valor);
                    if (obj == nullptr || !obj->bloque) return RunStatus{};
                }
                return destruir(valor, inst);
            }

            case Op::GetIndex: {
                Objeto* obj = nullptr;
                RunStatus estado = valida_celda(inst, reg(inst.a).i,
                                                reg(inst.b).i, obj);
                if (!estado.ok || estado.thrown) return estado;
                const auto i = static_cast<std::size_t>(reg(inst.b).i);
                if (obj->de_bytes) {
                    reg(inst.dst).i = obj->octetos[i];
                } else {
                    reg(inst.dst) = obj->campos[i];
                }
                return RunStatus{};
            }
            case Op::SetIndex: {
                Objeto* obj = nullptr;
                RunStatus estado = valida_celda(inst, reg(inst.a).i,
                                                reg(inst.b).i, obj);
                if (!estado.ok || estado.thrown) return estado;
                const auto i = static_cast<std::size_t>(reg(inst.b).i);
                if (obj->de_bytes) {
                    obj->octetos[i] = static_cast<std::uint8_t>(reg(inst.c).i & 0xFF);
                } else {
                    obj->campos[i] = reg(inst.c);
                }
                return RunStatus{};
            }

            case Op::CallHost:
                return llamada_host(inst, frame);
            case Op::Move: reg(inst.dst) = reg(inst.a); return RunStatus{};
            case Op::LoadLocal:
                if (!frame.estado.empty() && frame.estado[inst.slot] != 0 &&
                    !inst.synthetic) {
                    return uso_invalido(frame, inst, "se usa");
                }
                reg(inst.dst) = frame.slots[inst.slot];
                return RunStatus{};
            case Op::StoreLocal:
                if (!frame.estado.empty()) {
                    if (frame.estado[inst.slot] == 2 && !inst.synthetic) {
                        return uso_invalido(frame, inst, "se escribe");
                    }
                    // escribir REVIVE un slot movido: un valor nuevo no esta
                    // movido (la regla de 'Cell.write')
                    frame.estado[inst.slot] = 0;
                }
                frame.slots[inst.slot] = reg(inst.a);
                return RunStatus{};

            // Los enteros ENVUELVEN. En C++ el desbordamiento con signo es
            // comportamiento indefinido, asi que se hace la cuenta en el tipo
            // SIN signo —donde envolver esta definido— y se vuelve. Sin esto
            // el compilador podria optimizar asumiendo que no desborda, y el
            // resultado dejaria de coincidir con el del interprete.
            case Op::AddI:
                reg(inst.dst).i = static_cast<std::int64_t>(
                    static_cast<std::uint64_t>(reg(inst.a).i) +
                    static_cast<std::uint64_t>(reg(inst.b).i));
                return RunStatus{};
            case Op::SubI:
                reg(inst.dst).i = static_cast<std::int64_t>(
                    static_cast<std::uint64_t>(reg(inst.a).i) -
                    static_cast<std::uint64_t>(reg(inst.b).i));
                return RunStatus{};
            case Op::MulI:
                reg(inst.dst).i = static_cast<std::int64_t>(
                    static_cast<std::uint64_t>(reg(inst.a).i) *
                    static_cast<std::uint64_t>(reg(inst.b).i));
                return RunStatus{};
            case Op::DivI:
                if (reg(inst.b).i == 0) {
                    return excepcion("DivisionPorCero", "EXC001",
                                     "división por cero", inst.line, inst.col);
                }
                reg(inst.dst).i = div_trunc(reg(inst.a).i, reg(inst.b).i);
                return RunStatus{};
            case Op::RemI:
                if (reg(inst.b).i == 0) {
                    return excepcion("DivisionPorCero", "EXC001",
                                     "resto de una división por cero",
                                     inst.line, inst.col);
                }
                reg(inst.dst).i = rem_trunc(reg(inst.a).i, reg(inst.b).i);
                return RunStatus{};

            // Entre FLOTANTES dividir por cero NO es un error: IEEE-754 dice
            // '+inf', y eso es lo que hace la FPU y lo que hace el interprete.
            case Op::AddF: reg(inst.dst).f = reg(inst.a).f + reg(inst.b).f; return RunStatus{};
            case Op::SubF: reg(inst.dst).f = reg(inst.a).f - reg(inst.b).f; return RunStatus{};
            case Op::MulF: reg(inst.dst).f = reg(inst.a).f * reg(inst.b).f; return RunStatus{};
            case Op::DivF: reg(inst.dst).f = reg(inst.a).f / reg(inst.b).f; return RunStatus{};
            // el resto de C ('fmod'): lo que hace el interprete. Con divisor
            // cero da NaN, como IEEE-754, y no lanza.
            case Op::RemF: reg(inst.dst).f = std::fmod(reg(inst.a).f, reg(inst.b).f); return RunStatus{};

            case Op::EqI: reg(inst.dst).i = reg(inst.a).i == reg(inst.b).i; return RunStatus{};
            case Op::NeI: reg(inst.dst).i = reg(inst.a).i != reg(inst.b).i; return RunStatus{};
            case Op::LtI: reg(inst.dst).i = reg(inst.a).i < reg(inst.b).i; return RunStatus{};
            case Op::LeI: reg(inst.dst).i = reg(inst.a).i <= reg(inst.b).i; return RunStatus{};
            case Op::GtI: reg(inst.dst).i = reg(inst.a).i > reg(inst.b).i; return RunStatus{};
            case Op::GeI: reg(inst.dst).i = reg(inst.a).i >= reg(inst.b).i; return RunStatus{};

            case Op::EqF: reg(inst.dst).i = reg(inst.a).f == reg(inst.b).f; return RunStatus{};
            case Op::NeF: reg(inst.dst).i = reg(inst.a).f != reg(inst.b).f; return RunStatus{};
            case Op::LtF: reg(inst.dst).i = reg(inst.a).f < reg(inst.b).f; return RunStatus{};
            case Op::LeF: reg(inst.dst).i = reg(inst.a).f <= reg(inst.b).f; return RunStatus{};
            case Op::GtF: reg(inst.dst).i = reg(inst.a).f > reg(inst.b).f; return RunStatus{};
            case Op::GeF: reg(inst.dst).i = reg(inst.a).f >= reg(inst.b).f; return RunStatus{};

            case Op::AndI: reg(inst.dst).i = reg(inst.a).i & reg(inst.b).i; return RunStatus{};
            case Op::OrI: reg(inst.dst).i = reg(inst.a).i | reg(inst.b).i; return RunStatus{};
            case Op::XorI: reg(inst.dst).i = reg(inst.a).i ^ reg(inst.b).i; return RunStatus{};
            case Op::NotI: reg(inst.dst).i = ~reg(inst.a).i; return RunStatus{};
            case Op::ShlI:
            case Op::ShrI: {
                const std::int64_t n = reg(inst.b).i;
                if (n < 0 || n > 63) {
                    return excepcion("DesplazamientoInvalido", "EXC005",
                                     "desplazamiento de " + std::to_string(n) +
                                         " bits fuera de [0, 64)",
                                     inst.line, inst.col);
                }
                // '<<' sobre el sin signo: envuelve sin comportamiento
                // indefinido. '>>' de un con signo es aritmetico desde C++20.
                reg(inst.dst).i = inst.op == Op::ShlI
                    ? static_cast<std::int64_t>(static_cast<std::uint64_t>(reg(inst.a).i) << n)
                    : reg(inst.a).i >> n;
                return RunStatus{};
            }
            case Op::NegI:
                reg(inst.dst).i = static_cast<std::int64_t>(
                    0u - static_cast<std::uint64_t>(reg(inst.a).i));
                return RunStatus{};
            case Op::NegF: reg(inst.dst).f = -reg(inst.a).f; return RunStatus{};
            case Op::Not: reg(inst.dst).i = reg(inst.a).i == 0; return RunStatus{};

            // 'len(s)' y 's[i]': una cadena es el indice de su constante, y
            // sus caracteres se cuentan en CODE POINTS y no en bytes — es lo
            // que cuenta 'len' en el interprete, y contar dos cosas distintas
            // con la misma cadena habria sido la trampa.
            case Op::LenStr: {
                const std::string* texto = cadena(reg(inst.a).i);
                if (texto == nullptr) {
                    return RunStatus::failure(
                        "'len' sobre algo que no es una cadena del programa",
                        inst.line, inst.col);
                }
                reg(inst.dst).i = static_cast<std::int64_t>(
                    puntos_de(reg(inst.a).i, *texto).largo);
                return RunStatus{};
            }
            case Op::IndexStr: {
                const std::string* texto = cadena(reg(inst.a).i);
                if (texto == nullptr) {
                    return RunStatus::failure(
                        "indexar algo que no es una cadena del programa",
                        inst.line, inst.col);
                }
                const Puntos& puntos = puntos_de(reg(inst.a).i, *texto);
                const std::int64_t i = reg(inst.b).i;
                if (i < 0 || static_cast<std::size_t>(i) >= puntos.largo) {
                    // la misma excepcion del programa que el interprete
                    return excepcion("IndiceFueraDeRango", "EXC002",
                                     "indice " + std::to_string(i) +
                                         " fuera de la cadena (longitud " +
                                         std::to_string(puntos.largo) + ")",
                                     inst.line, inst.col);
                }
                const auto k = static_cast<std::size_t>(i);
                reg(inst.dst).i = puntos.ascii
                    ? static_cast<unsigned char>((*texto)[k])
                    : puntos.puntos[k];
                return RunStatus{};
            }
            case Op::ConcatStr: {
                const std::string* a = cadena(reg(inst.a).i);
                const std::string* b = cadena(reg(inst.b).i);
                if (a == nullptr || b == nullptr) {
                    return RunStatus::failure(
                        "concatenar algo que no es una cadena", inst.line,
                        inst.col);
                }
                reg(inst.dst).i = interna(*a + *b);
                return RunStatus{};
            }
            case Op::ToStr: {
                std::string texto;
                RunStatus estado = escribir(reg(inst.a), inst.imm, inst, texto);
                if (!estado.ok) return estado;
                reg(inst.dst).i = interna(texto);
                return RunStatus{};
            }
            case Op::Formatear: {
                if (inst.imm < 0 ||
                    static_cast<std::size_t>(inst.imm) >= program_.formatos.size()) {
                    return RunStatus::failure("formato desconocido", inst.line, inst.col);
                }
                const Formato& f = program_.formatos[static_cast<std::size_t>(inst.imm)];
                std::string texto;
                RunStatus estado = escribir(reg(inst.a), f.modo, inst, texto, f.repr);
                if (!estado.ok) return estado;
                reg(inst.dst).i = interna(con_formato(reg(inst.a), f, std::move(texto)));
                return RunStatus{};
            }
            case Op::Hash: {
                reg(inst.dst).i = hash_de(reg(inst.a), inst.imm);
                return RunStatus{};
            }
            case Op::EqStr:
            case Op::NeStr: {
                const std::string* a = cadena(reg(inst.a).i);
                const std::string* b = cadena(reg(inst.b).i);
                if (a == nullptr || b == nullptr) {
                    return RunStatus::failure(
                        "comparar algo que no es una cadena", inst.line,
                        inst.col);
                }
                const bool iguales = *a == *b;
                reg(inst.dst).i =
                    (inst.op == Op::EqStr ? iguales : !iguales) ? 1 : 0;
                return RunStatus{};
            }
            case Op::LtStr:
            case Op::LeStr:
            case Op::GtStr:
            case Op::GeStr: {
                const std::string* a = cadena(reg(inst.a).i);
                const std::string* b = cadena(reg(inst.b).i);
                if (a == nullptr || b == nullptr) {
                    return RunStatus::failure(
                        "ordenar algo que no es una cadena", inst.line,
                        inst.col);
                }
                // char_traits<char> compara como 'unsigned char': el orden de
                // los bytes UTF-8 es el de los puntos de codigo
                const int c = a->compare(*b);
                bool r = false;
                switch (inst.op) {
                    case Op::LtStr: r = c < 0; break;
                    case Op::LeStr: r = c <= 0; break;
                    case Op::GtStr: r = c > 0; break;
                    default: r = c >= 0; break;
                }
                reg(inst.dst).i = r ? 1 : 0;
                return RunStatus{};
            }
            case Op::EqCaja: {
                const std::int64_t a = reg(inst.a).i;
                const std::int64_t b = reg(inst.b).i;
                if (a == -1 || b == -1) {
                    reg(inst.dst).i = a == b ? 1 : 0;
                    return RunStatus{};
                }
                const Objeto* x = objeto(a);
                const Objeto* y = objeto(b);
                if (x == nullptr || x->campos.empty()) return no_es_objeto(inst, a, "comparar");
                if (y == nullptr || y->campos.empty()) return no_es_objeto(inst, b, "comparar");
                reg(inst.dst).i = inst.imm == 1
                    ? (x->campos[0].f == y->campos[0].f ? 1 : 0)
                    : (x->campos[0].i == y->campos[0].i ? 1 : 0);
                return RunStatus{};
            }
            // La transferencia no mueve nada en ejecucion: el valor ya esta
            // donde esta. Lo unico que cambia es que su ambito deja de
            // destruirlo.
            case Op::MarkMoved:
                if (!frame.estado.empty()) {
                    const std::uint8_t antes = frame.estado[inst.slot];
                    const std::string nombre = nombre_de_slot(frame, inst.slot);
                    if (antes == 2) {
                        return RunStatus::failure(
                            std::string("RT003: ") +
                                (inst.libera ? "doble 'free' sobre '"
                                             : "'move' sobre '") +
                                nombre + (inst.libera ? "'" : "' ya liberado"),
                            inst.line, inst.col);
                    }
                    if (antes == 1 && !inst.libera) {
                        return RunStatus::failure(
                            "RT002: '" + nombre + "' ya fue movido",
                            inst.line, inst.col);
                    }
                    frame.estado[inst.slot] = inst.libera ? 2 : 1;
                }
                if (inst.imm >= 0) {
                    frame.slots[static_cast<std::size_t>(inst.imm)].i = 0;
                }
                return RunStatus{};
            case Op::Borrow:
                if (!frame.estado.empty() && frame.estado[inst.slot] != 0 &&
                    !inst.synthetic) {
                    return uso_invalido(frame, inst, "se usa");
                }
                reg(inst.dst) = frame.slots[inst.slot];
                return RunStatus{};
            case Op::Call: {
                if (inst.func < 0 ||
                    static_cast<std::size_t>(inst.func) >=
                        program_.functions.size()) {
                    return RunStatus::failure("llamada a una funcion que no "
                                              "esta en el programa",
                                              inst.line, inst.col);
                }
                std::vector<Value> args;
                args.reserve(inst.args.size());
                for (Reg r : inst.args) args.push_back(frame.regs[r]);
                // Un destructor sobre algo que YA se destruyo no corre: un
                // 'free p' por un puntero destruye el objeto, y su dueño,
                // al cerrar su ambito, ya no tiene nada que destruir (el
                // interprete tampoco lo repite)
                if (inst.destructor && !args.empty() && objeto(args[0].i) == nullptr) {
                    return RunStatus{};
                }
                Value salida{0};
                RunStatus status =
                    call(static_cast<std::size_t>(inst.func), args, salida);
                // Un destructor que lanza TERMINA el programa: si subiera,
                // durante un desenrollado habria dos excepciones en vuelo y el
                // 'catch' se quedaria con la segunda. Es la regla de C++ y la
                // del interprete ('_destruir').
                if (status.thrown && inst.destructor) {
                    const Function& destructor =
                        program_.functions[static_cast<std::size_t>(inst.func)];
                    return RunStatus::failure(
                        "RT021: el " + destructor.name +
                            (destructor.unit.empty() ? std::string()
                                                     : " de '" + destructor.unit + "'") +
                            " lanzo: un destructor nunca puede lanzar. Si "
                            "liberar puede fallar, registra el fallo y deja "
                            "que el __free__ termine normalmente",
                        inst.line, inst.col);
                }
                // una excepcion del callee sube tal cual: quien decide si se
                // atrapa es el BLOQUE, que sabe si hay un 'try' alrededor.
                if (status.thrown) return status;
                if (!status.ok) {
                    // la posicion del sitio de LLAMADA si el fallo no traia
                    // una suya: sin ella el error apunta al vacio.
                    if (status.line == 0) {
                        status.line = inst.line;
                        status.col = inst.col;
                    }
                    return status;
                }
                if (inst.dst != kNoReg) reg(inst.dst) = salida;
                return RunStatus{};
            }
        }
        return RunStatus::failure("instruccion desconocida", inst.line,
                                  inst.col);
    }

    static std::string nombre_de_slot(const Frame& frame, std::uint32_t slot) {
        if (frame.fn == nullptr || slot >= frame.fn->slot_names.size()) {
            return "slot" + std::to_string(slot);
        }
        return frame.fn->slot_names[slot];
    }

    // RT001 (movido) o RT003 (liberado), con el mensaje de 'Cell.read'.
    static RunStatus uso_invalido(const Frame& frame, const Inst& inst,
                                  const char* verbo) {
        const std::string nombre = nombre_de_slot(frame, inst.slot);
        if (frame.estado[inst.slot] == 1) {
            return RunStatus::failure("RT001: '" + nombre + "' " + verbo +
                                          " despues de 'move' (detectado en "
                                          "runtime)",
                                      inst.line, inst.col);
        }
        return RunStatus::failure("RT003: '" + nombre + "' " + verbo +
                                      " despues de 'free'",
                                  inst.line, inst.col);
    }

    const Puntos& puntos_de(std::int64_t indice, const std::string& texto) {
        const auto it = puntos_.find(indice);
        if (it != puntos_.end()) return it->second;
        Puntos p;
        p.ascii = std::all_of(texto.begin(), texto.end(), [](char c) {
            return static_cast<unsigned char>(c) < 0x80u;
        });
        if (p.ascii) {
            p.largo = texto.size();
        } else {
            p.puntos = puntos_de_codigo(texto);
            p.largo = p.puntos.size();
        }
        return puntos_.emplace(indice, std::move(p)).first->second;
    }

    // La cadena que nombra un indice, o nullptr si no lo es.
    const std::string* cadena(std::int64_t indice) const {
        if (indice < 0 ||
            static_cast<std::size_t>(indice) >= textos_.size() ||
            muerta_[static_cast<std::size_t>(indice)] != 0) {
            return nullptr;
        }
        return &textos_[static_cast<std::size_t>(indice)];
    }

    // Una cadena NUEVA entra en la tabla y devuelve su indice. Se deduplica
    // por texto para que la tabla no crezca sin freno en un bucle que
    // construye siempre lo mismo.
    // Una EXCEPCION DEL PROGRAMA (EXCxxx): la operacion no tiene resultado y
    // el runtime LANZA un valor, igual que un 'throw'. Es el mismo objeto que
    // construye el interprete —'excepciones.<tipo>{mensaje, linea, columna}'—
    // y viaja con la etiqueta de ese tipo, asi que un 'catch
    // (exc.DivisionPorCero e)' lo atrapa por la maquinaria de siempre. Si el
    // programa no nombra ese tipo en ningun 'catch', no hay etiqueta (-1) y
    // solo un 'catch (e)' sin tipo lo atrapa.
    RunStatus excepcion(const std::string& tipo, const char* codigo,
                        const std::string& mensaje, std::uint32_t ln,
                        std::uint32_t col) {
        const std::string clave = "9:excepciones." + tipo + ":0:():[]";
        std::int64_t etiqueta = -1;
        for (std::size_t i = 0; i < program_.tags.size(); ++i) {
            if (program_.tags[i] == clave) etiqueta = static_cast<std::int64_t>(i);
        }
        const std::int64_t texto = interna(mensaje);
        const std::int64_t handle = nuevo_objeto(3, -1);
        Objeto* valor = objeto(handle);
        valor->campos[0].i = texto;
        valor->campos[1].i = static_cast<std::int64_t>(ln);
        valor->campos[2].i = static_cast<std::int64_t>(col);
        excepciones_[handle] = std::string(codigo) + ": " + mensaje + " (" +
                               std::to_string(ln) + ":" + std::to_string(col) + ")";
        RunStatus lanzada;
        lanzada.thrown = true;
        lanzada.thrown_value = handle;
        lanzada.thrown_tag = etiqueta;
        return lanzada;
    }

public:
    // Si 'handle' es una excepcion del runtime, su descripcion ("EXC001: ...").
    // Lo que se escribe de un valor lanzado que nadie atrapo: su texto si es
    // un primitivo (la etiqueta dice de que tipo es), como 'format_value'.
    std::string describe_lanzado(std::int64_t valor, std::int64_t etiqueta) {
        Value v{};
        v.i = valor;
        if (etiqueta >= 0 && static_cast<std::size_t>(etiqueta) < program_.tags_texto.size()) {
            const std::int64_t modo = program_.tags_texto[static_cast<std::size_t>(etiqueta)];
            std::string texto;
            Inst sin_posicion;
            if (modo >= 0 && escribir(v, modo, sin_posicion, texto).ok) return texto;
        }
        return std::to_string(valor);
    }

    bool describe_excepcion(std::int64_t handle, std::string& texto) const {
        const auto it = excepciones_.find(handle);
        if (it == excepciones_.end()) return false;
        texto = it->second;
        return true;
    }

private:
    // Una cadena NUEVA entra en la tabla; una que ya estaba devuelve su
    // indice. La busqueda es por hash: antes era LINEAL sobre todas las
    // cadenas que el programa habia creado, y cada '+' o f-string costaba
    // O(cadenas vivas) — un lexer que arma lexemas se volvia cuadratico.
    std::int64_t interna(std::string texto) {
        const auto it = indice_de_texto_.find(texto);
        if (it != indice_de_texto_.end()) return it->second;
        std::size_t i = 0;
        if (!huecos_texto_.empty()) {
            i = huecos_texto_.back();
            huecos_texto_.pop_back();
            textos_[i] = std::move(texto);
            muerta_[i] = 0;
        } else {
            textos_.push_back(std::move(texto));
            muerta_.push_back(0);
            i = textos_.size() - 1;
        }
        const auto indice = static_cast<std::int64_t>(i);
        indice_de_texto_.emplace(textos_[i], indice);
        ++memoria_.cadenas_creadas;
        suma_bytes(textos_[i].size());
        if (++cadenas_nuevas_ >= umbral_cadenas_) barrido_pendiente_ = true;
        return indice;
    }

    // RECOGER CADENAS. Una cadena no tiene un solo dueño —'var str b = a'
    // comparte el indice, y la tabla deduplica— asi que no muere con nadie:
    // se barre. Es CONSERVADOR: se marca todo valor de los marcos activos,
    // de las globales y de los campos de los objetos vivos que PUEDA ser el
    // indice de una cadena; un entero que coincide por casualidad solo la
    // mantiene viva un rato mas, nunca libera una que se usa. Las constantes
    // del programa no se recogen.
    //
    // Se hace cuando se crearon tantas cadenas como hay vivas (o 4096), asi
    // que el costo es amortizado: cada barrido paga las que se crearon.
    void barrer_cadenas() {
        barrido_pendiente_ = false;
        std::vector<std::uint8_t> viva(textos_.size(), 0);
        const auto marcar = [&](const Value& v) {
            if (v.i >= 0 && static_cast<std::uint64_t>(v.i) < viva.size()) {
                viva[static_cast<std::size_t>(v.i)] = 1;
            }
        };
        for (const Frame* f : marcos_) {
            for (const Value& v : f->slots) marcar(v);
            for (const Value& v : f->regs) marcar(v);
        }
        for (const Value& v : globales_) marcar(v);
        for (const Objeto& obj : monton_) {
            if (!obj.vivo) continue;
            for (const Value& v : obj.campos) marcar(v);
        }
        std::uint64_t vivas = 0;
        for (std::size_t i = constantes_; i < textos_.size(); ++i) {
            if (muerta_[i] != 0) continue;
            if (viva[i] != 0) {
                ++vivas;
                continue;
            }
            indice_de_texto_.erase(std::string_view(textos_[i]));
            puntos_.erase(static_cast<std::int64_t>(i));
            resta_bytes(textos_[i].size());
            std::string().swap(textos_[i]);
            muerta_[i] = 1;
            huecos_texto_.push_back(i);
            ++memoria_.cadenas_recogidas;
        }
        cadenas_nuevas_ = 0;
        umbral_cadenas_ = std::max<std::uint64_t>(4096, vivas + memoria_.vivos);
    }

public:
    // Al terminar: ya no hay marcos activos, asi que lo que no alcanzan las
    // globales ni los objetos vivos es basura. Es lo que hace que "vivas al
    // terminar" diga si el programa pierde cadenas.
    // Las globales que son duenas de un objeto, cuando 'main' vuelve: su
    // memoria, sin destructor (el interprete no corre '__free__' al salir).
    // De la ultima a la primera, como se destruiria un ambito.
    void liberar_globales() {
        for (std::size_t i = globales_.size(); i > 0; --i) {
            if (!program_.globals[i - 1].propia) continue;
            liberar(globales_[i - 1].i);
            globales_[i - 1].i = -1;
        }
    }

    void barrido_final() {
        if (marcos_.empty()) barrer_cadenas();
    }

private:

    // Un texto como se escribiria en el fuente: entre 'comilla', con los
    // escapes que acepta el lexer (los de '_cadena_repr' del interprete).
    static void con_escapes(const std::string& texto, char comilla, std::string& out) {
        out += comilla;
        for (const char c : texto) {
            switch (c) {
                case '\\': out += "\\\\"; break;
                case '\n': out += "\\n"; break;
                case '\t': out += "\\t"; break;
                case '\r': out += "\\r"; break;
                case '\0': out += "\\0"; break;
                default:
                    if (c == comilla) out += '\\';
                    out += c;
            }
        }
        out += comilla;
    }

    static std::string corto(const std::string& nombre) {
        const auto punto = nombre.rfind('.');
        return punto == std::string::npos ? nombre : nombre.substr(punto + 1);
    }

    // El especificador '[0][ancho][.precision][tipo]' sobre el 'texto' de 'v'.
    // El MISMO algoritmo que '_con_formato' del interprete: 'd x X b o' en
    // esa base con el signo delante, 'f' con la precision (6 si no), y el
    // ancho rellena a la izquierda un numero y a la derecha lo demas.
    static std::string con_formato(Value v, const Formato& f, std::string texto) {
        const std::int64_t base = f.modo & 7;
        const bool nulable = (f.modo & kTextoNulable) != 0;
        if (!nulable && f.clase != 0) {
            if (f.clase == 'd') {
                texto = std::to_string(v.i);
            } else if (f.clase == 'x' || f.clase == 'X' || f.clase == 'b' || f.clase == 'o') {
                const int radix = f.clase == 'b' ? 2 : f.clase == 'o' ? 8 : 16;
                const char* digitos = f.clase == 'X' ? "0123456789ABCDEF" : "0123456789abcdef";
                // el valor absoluto sin desbordar (el minimo de 64 bits no tiene opuesto)
                std::uint64_t u = v.i < 0 ? 0 - static_cast<std::uint64_t>(v.i)
                                          : static_cast<std::uint64_t>(v.i);
                std::string al_reves;
                do {
                    al_reves += digitos[u % static_cast<std::uint64_t>(radix)];
                    u /= static_cast<std::uint64_t>(radix);
                } while (u != 0);
                texto = v.i < 0 ? "-" : "";
                texto.append(al_reves.rbegin(), al_reves.rend());
            } else if (f.clase == 'f') {
                const double x = v.f;
                if (std::isnan(x)) texto = "nan";
                else if (std::isinf(x)) texto = x > 0 ? "inf" : "-inf";
                else {
                    const int p = f.precision < 0 ? 6 : f.precision;
                    const int n = std::snprintf(nullptr, 0, "%.*f", p, x);
                    std::string s(static_cast<std::size_t>(n) + 1, '\0');
                    std::snprintf(s.data(), s.size(), "%.*f", p, x);
                    s.resize(static_cast<std::size_t>(n));
                    texto = std::move(s);
                }
            }
        }
        const auto ancho = static_cast<std::size_t>(f.ancho);
        const std::size_t largo = puntos_de_codigo(texto).size();
        if (f.ancho <= 0 || largo >= ancho) return texto;
        const bool numero = !nulable && (base == 0 || base == 1);
        if (numero && f.cero) {
            const bool signo = !texto.empty() && texto[0] == '-';
            std::string salida = signo ? "-" : "";
            salida.append(ancho - largo, '0');
            salida += signo ? texto.substr(1) : texto;
            return salida;
        }
        if (numero) return std::string(ancho - largo, ' ') + texto;
        return texto + std::string(ancho - largo, ' ');
    }

    // 'ToStr' completo: los escalares (texto_de), la cadena, la CAJA de un
    // 'T?' (null o su valor), un enum suma ('Nodo(3, x)', recursivo en su
    // payload) y un struct ('Punto{x: 1, y: 2}', sus campos en su
    // representacion). Con 'repr' ('{x!r}'), una cadena y un char van con sus
    // comillas y un enum con su tipo ('Color.Verde'). Lo mismo que '_texto'
    // del interprete.
    RunStatus escribir(Value v, std::int64_t imm, const Inst& inst, std::string& out,
                       bool repr = false) {
        const std::int64_t modo = imm & 7;
        if ((imm & kTextoNulable) != 0) {
            if (v.i == -1) {
                out += "null";
                return RunStatus{};
            }
            // un escalar anulable viene en su celda
            if (modo <= 3) {
                const Objeto* caja = objeto(v.i);
                if (caja == nullptr || caja->campos.empty()) {
                    return no_es_objeto(inst, v.i, "escribir");
                }
                v = caja->campos[0];
            }
        }
        if (modo == 6) {
            const auto tabla = static_cast<std::size_t>(imm >> 4);
            if (tabla < program_.enums.size()) {
                for (const auto& [valor, nombre] : program_.enums[tabla].items) {
                    if (valor == v.i) {
                        if (repr) out += corto(program_.enums[tabla].nombre) + ".";
                        out += nombre;
                        return RunStatus{};
                    }
                }
            }
            // un entero que no es ninguna variante (un cast): su numero
            out += std::to_string(v.i);
            return RunStatus{};
        }
        if (modo == 4) {
            const std::string* s = cadena(v.i);
            if (s == nullptr) {
                return RunStatus::failure("escribir algo que no es una cadena",
                                          inst.line, inst.col);
            }
            if (repr) con_escapes(*s, '"', out);
            else out += *s;
            return RunStatus{};
        }
        if (modo == 3 && repr) {
            con_escapes(texto_de(v, 3), '\'', out);
            return RunStatus{};
        }
        if (modo == 7) return escribir_struct(v, inst, out);
        if (modo != 5) {
            out += texto_de(v, modo);
            return RunStatus{};
        }
        const Objeto* obj = objeto(v.i);
        if (obj == nullptr || obj->campos.empty() || obj->layout < 0 ||
            static_cast<std::size_t>(obj->layout) >= program_.layouts.size()) {
            return no_es_objeto(inst, v.i, "escribir");
        }
        const Layout& forma = program_.layouts[static_cast<std::size_t>(obj->layout)];
        if (repr) out += corto(forma.nombre) + ".";
        const auto etiqueta = static_cast<std::size_t>(obj->campos[0].i);
        if (etiqueta >= forma.variantes.size() || etiqueta >= forma.textos.size()) {
            return RunStatus::failure("escribir un enum sin su forma", inst.line, inst.col);
        }
        const std::vector<std::int32_t>& modos = forma.textos[etiqueta];
        out += forma.variantes[etiqueta];
        if (modos.empty()) return RunStatus{};
        out += "(";
        // se copian los valores antes de recursar: escribir no crea objetos,
        // pero no hace falta apostar a que el puntero siga valiendo
        const std::vector<Value> campos = obj->campos;
        for (std::size_t k = 0; k < modos.size(); ++k) {
            if (k) out += ", ";
            if (k + 1 >= campos.size() || modos[k] < 0) {
                return RunStatus::failure("el payload de '" + forma.variantes[etiqueta] +
                                              "' no se sabe escribir",
                                          inst.line, inst.col);
            }
            RunStatus estado = escribir(campos[k + 1], modos[k], inst, out, repr);
            if (!estado.ok) return estado;
        }
        out += ")";
        return RunStatus{};
    }

    // 'Punto{x: 1, nombre: "a"}': los campos en el orden declarado, cada uno
    // en su representacion.
    RunStatus escribir_struct(Value v, const Inst& inst, std::string& out) {
        const Objeto* obj = objeto(v.i);
        if (obj == nullptr || obj->layout < 0 ||
            static_cast<std::size_t>(obj->layout) >= program_.layouts.size()) {
            return no_es_objeto(inst, v.i, "escribir");
        }
        const Layout& forma = program_.layouts[static_cast<std::size_t>(obj->layout)];
        std::string nombre = forma.nombre;
        const auto generico = nombre.find('<');   // 'Caja<int>' se escribe 'Caja'
        if (generico != std::string::npos) nombre.resize(generico);
        out += corto(nombre) + "{";
        const std::vector<Value> campos = obj->campos;
        const std::vector<std::int32_t> modos =
            forma.textos.empty() ? std::vector<std::int32_t>{} : forma.textos[0];
        for (std::size_t k = 0; k < forma.campos.size(); ++k) {
            if (k) out += ", ";
            out += forma.campos[k] + ": ";
            if (k >= campos.size() || k >= modos.size() || modos[k] < 0) {
                return RunStatus::failure("el campo '" + forma.campos[k] +
                                              "' no se sabe escribir",
                                          inst.line, inst.col);
            }
            RunStatus estado = escribir(campos[k], modos[k], inst, out, true);
            if (!estado.ok) return estado;
        }
        out += "}";
        return RunStatus{};
    }

    // 'hash(x)' de un primitivo: el MISMO numero que el interprete ('_hash'
    // de evaluator.py), porque de el depende el orden de un diccionario.
    std::int64_t hash_de(Value v, std::int64_t modo) const {
        if (modo == 0) {
            std::uint64_t z = static_cast<std::uint64_t>(v.i) + 0x9E3779B97F4A7C15ull;
            z = (z ^ (z >> 30)) * 0xBF58476D1CE4E5B9ull;
            z = (z ^ (z >> 27)) * 0x94D049BB133111EBull;
            return static_cast<std::int64_t>(z ^ (z >> 31));
        }
        std::string texto;
        if (modo == 2) {
            texto = texto_de(v, 3);   // el char en UTF-8
        } else if (const std::string* s = cadena(v.i)) {
            texto = *s;
        }
        std::uint64_t h = 0xCBF29CE484222325ull;
        for (const char c : texto) {
            h = (h ^ static_cast<unsigned char>(c)) * 0x100000001B3ull;
        }
        return static_cast<std::int64_t>(h);
    }

    // Un valor escrito como texto. Tiene que dar EXACTAMENTE lo mismo que
    // 'format_value' del interprete: es lo que acaba en la salida del
    // programa, y el diferencial compara salidas.
    std::string texto_de(Value v, std::int64_t modo) const {
        switch (modo) {
            case 0: return std::to_string(v.i);
            case 1: return flotante_como_python(v.f);
            case 2: return v.i != 0 ? "true" : "false";
            case 3: {
                // un char es un punto de codigo: se escribe en UTF-8
                std::string s;
                const std::uint32_t c = static_cast<std::uint32_t>(v.i);
                if (c < 0x80u) s += static_cast<char>(c);
                else if (c < 0x800u) {
                    s += static_cast<char>(0xC0u | (c >> 6));
                    s += static_cast<char>(0x80u | (c & 0x3Fu));
                } else if (c < 0x10000u) {
                    s += static_cast<char>(0xE0u | (c >> 12));
                    s += static_cast<char>(0x80u | ((c >> 6) & 0x3Fu));
                    s += static_cast<char>(0x80u | (c & 0x3Fu));
                } else {
                    s += static_cast<char>(0xF0u | (c >> 18));
                    s += static_cast<char>(0x80u | ((c >> 12) & 0x3Fu));
                    s += static_cast<char>(0x80u | ((c >> 6) & 0x3Fu));
                    s += static_cast<char>(0x80u | (c & 0x3Fu));
                }
                return s;
            }
            default: return "";
        }
    }

    // '__copy__(dst, src, n)': POR VALOR, celda a celda. Si las celdas son
    // objetos, cada una se copia en profundidad: despues de crecer, el bloque
    // viejo se suelta con sus objetos, y el nuevo tiene que tener los suyos.
    RunStatus copia_de_bloques(const Inst& inst, Frame& frame) {
        const std::int64_t destino = frame.regs[inst.args[0]].i;
        const std::int64_t origen = frame.regs[inst.args[1]].i;
        const std::int64_t n = frame.regs[inst.args[2]].i;
        if (objeto(destino) == nullptr) return no_es_objeto(inst, destino, "'__copy__' hacia");
        if (objeto(origen) == nullptr) return no_es_objeto(inst, origen, "'__copy__' desde");
        const std::size_t largo_origen = objeto(origen)->celdas();
        const std::size_t largo_destino = objeto(destino)->celdas();
        if (n < 0 || static_cast<std::size_t>(n) > largo_origen ||
            static_cast<std::size_t>(n) > largo_destino) {
            return excepcion("IndiceFueraDeRango", "EXC002",
                             "__copy__ de " + std::to_string(n) +
                                 " elementos excede el tamaño de origen (" +
                                 std::to_string(largo_origen) + ") o destino (" +
                                 std::to_string(largo_destino) + ")",
                             inst.line, inst.col);
        }
        if (objeto(origen)->de_bytes && objeto(destino)->de_bytes) {
            std::copy_n(objeto(origen)->octetos.begin(), static_cast<std::size_t>(n), objeto(destino)->octetos.begin());
            if (inst.dst != kNoReg) frame.regs[inst.dst].i = 0;
            return RunStatus{};
        }
        const bool objetos = objeto(origen)->elem_layout >= 0;
        for (std::size_t i = 0; i < static_cast<std::size_t>(n); ++i) {
            // 'objeto()' se vuelve a pedir en cada vuelta: copiar un objeto
            // puede hacer crecer el monton y mover los que ya estaban
            Value v = objeto(origen)->campos[i];
            if (objetos) {
                liberar(objeto(destino)->campos[i].i);
                if (objeto(v.i) != nullptr) v.i = copiar(v.i);
            }
            objeto(destino)->campos[i] = v;
        }
        if (inst.dst != kNoReg) frame.regs[inst.dst].i = 0;
        return RunStatus{};
    }

    // Un acceso por INDICE: el bloque tiene que existir y el indice caer
    // dentro. El mensaje nombra el tamano porque un "fuera de rango" sin el
    // no dice que rango era.
    RunStatus valida_celda(const Inst& inst, std::int64_t handle,
                           std::int64_t indice, Objeto*& obj) {
        obj = objeto(handle);
        if (obj == nullptr) return no_es_objeto(inst, handle, "indexar");
        if (indice < 0 || static_cast<std::size_t>(indice) >= obj->celdas()) {
            const std::size_t largo = obj->celdas();
            return excepcion("IndiceFueraDeRango", "EXC002",
                             "índice " + std::to_string(indice) +
                                 " fuera de rango [0, " +
                                 std::to_string(largo) + ")",
                             inst.line, inst.col);
        }
        return RunStatus{};
    }

    RunStatus valida_campo(const Inst& inst, std::int64_t handle, Objeto*& obj) {
        obj = objeto(handle);
        if (obj == nullptr) return no_es_objeto(inst, handle, "leer o escribir un campo de");
        if (inst.imm < 0 ||
            static_cast<std::size_t>(inst.imm) >= obj->campos.size()) {
            return RunStatus::failure(
                "el objeto no tiene el campo " + std::to_string(inst.imm),
                inst.line, inst.col);
        }
        return RunStatus{};
    }

    // ------------------------------------------------------------------ //
    // el MONTON: objetos con generacion, huecos reutilizables
    // ------------------------------------------------------------------ //
    static std::uint32_t indice_de(std::int64_t handle) {
        return static_cast<std::uint32_t>(static_cast<std::uint64_t>(handle) &
                                          0xFFFFFFFFu);
    }
    static std::uint32_t generacion_de(std::int64_t handle) {
        return static_cast<std::uint32_t>(static_cast<std::uint64_t>(handle) >> 32);
    }

    // El objeto VIVO que nombra 'handle', o nullptr.
    Objeto* objeto(std::int64_t handle) {
        if (handle <= 0) return nullptr;
        const std::uint32_t i = indice_de(handle);
        if (i >= monton_.size()) return nullptr;
        Objeto& obj = monton_[i];
        if (!obj.vivo || obj.generacion != generacion_de(handle)) return nullptr;
        return &obj;
    }

    // Por que 'handle' no es un objeto: uno que YA SE LIBERO (RT003, la
    // misma clase que el interprete) o algo que nunca lo fue.
    RunStatus no_es_objeto(const Inst& inst, std::int64_t handle, const char* que) {
        if (handle > 0) {
            const std::uint32_t i = indice_de(handle);
            if (i < monton_.size() && generacion_de(handle) != 0 &&
                generacion_de(handle) <= monton_[i].generacion) {
                return RunStatus::failure(std::string("RT003: ") + que +
                                              " un objeto que ya se libero",
                                          inst.line, inst.col);
            }
        }
        return RunStatus::failure(std::string(que) + " algo que no es un objeto",
                                  inst.line, inst.col);
    }

    // La memoria del PROGRAMA (ver 'kSinLimiteDeMemoria'): cada reserva suma,
    // cada liberacion resta. Pasarse del limite no corta aqui —esta funcion
    // no puede devolver un error— sino al terminar la instruccion en curso.
    void suma_bytes(std::uint64_t n) {
        memoria_.bytes += n;
        memoria_.bytes_maximo = std::max(memoria_.bytes_maximo, memoria_.bytes);
        if (limite_bytes_ != 0 && memoria_.bytes > limite_bytes_) excedida_ = true;
    }

    void resta_bytes(std::uint64_t n) {
        memoria_.bytes = n > memoria_.bytes ? 0 : memoria_.bytes - n;
    }

    std::int64_t nuevo_objeto(std::size_t campos, std::int32_t layout) {
        std::uint32_t i = 0;
        if (!huecos_.empty()) {
            i = huecos_.back();
            huecos_.pop_back();
        } else {
            i = static_cast<std::uint32_t>(monton_.size());
            monton_.emplace_back();
        }
        Objeto& obj = monton_[i];
        obj.campos.assign(campos, Value{0});
        suma_bytes(campos * sizeof(Value));
        obj.layout = layout;
        obj.elem_layout = -1;
        obj.bloque = false;
        obj.de_bytes = false;
        obj.vivo = true;
        ++memoria_.creados;
        ++memoria_.vivos;
        memoria_.maximo = std::max(memoria_.maximo, memoria_.vivos);
        return static_cast<std::int64_t>(
            (static_cast<std::uint64_t>(obj.generacion) << 32) | i);
    }

    // Los indices de los campos PROPIOS de un objeto, segun su forma (los
    // objetos, o los punteros que pueden guardar un bloque suyo).
    const std::vector<std::uint32_t>* de_la_forma(
        const Objeto& obj,
        std::vector<std::vector<std::uint32_t>> Layout::*lista) const {
        if (obj.layout < 0 ||
            static_cast<std::size_t>(obj.layout) >= program_.layouts.size()) {
            return nullptr;
        }
        const Layout& forma = program_.layouts[static_cast<std::size_t>(obj.layout)];
        const auto& listas = forma.*lista;
        if (!forma.suma) return listas.empty() ? nullptr : &listas[0];
        if (obj.campos.empty()) return nullptr;
        const auto etiqueta = static_cast<std::size_t>(obj.campos[0].i);
        return etiqueta < listas.size() ? &listas[etiqueta] : nullptr;
    }
    const std::vector<std::uint32_t>* propios_de(const Objeto& obj) const {
        return de_la_forma(obj, &Layout::propios);
    }

    // ¿El campo 'c' de 'obj' guarda un BLOQUE que es suyo?
    bool bloque_propio(const Objeto& obj, std::uint32_t c) {
        const auto* lista = de_la_forma(obj, &Layout::bloques);
        if (lista == nullptr || c >= obj.campos.size()) return false;
        if (std::find(lista->begin(), lista->end(), c) == lista->end()) return false;
        const Objeto* b = objeto(obj.campos[c].i);
        return b != nullptr && b->bloque;
    }

    // Lo atrapado por un 'catch (e)' SIN tipo: ¿es un objeto? Si su etiqueta
    // es la de un tipo objeto, o si es una excepcion del runtime (EXCxxx).
    bool es_objeto_lanzado(std::int64_t valor, std::int64_t etiqueta) const {
        const bool objeto_por_tipo =
            etiqueta >= 0 &&
            static_cast<std::size_t>(etiqueta) < program_.tags_objeto.size() &&
            program_.tags_objeto[static_cast<std::size_t>(etiqueta)] != 0;
        return objeto_por_tipo || excepciones_.count(valor) != 0;
    }

    // DESTRUIR POR TIPO ('drop glue'): 'raiz' muere, y lo que corre lo dice
    // su FORMA. Es la misma regla con que el frontend aplana los drops de un
    // tipo que conoce, y la del interprete ('_destruir_por_tipo'):
    //   - si el tipo declara '__free__', corre ese, y se hace cargo de sus
    //     campos;
    //   - si no, sus campos propios y sus bloques, del ultimo al primero;
    //   - un bloque, sus celdas no vacias, de la ultima a la primera.
    // Despues libera la memoria de todo ('liberar'). Con una PILA, como
    // 'liberar': una lista enlazada de bloques no agota la de C++.
    RunStatus destruir(std::int64_t raiz, const Inst& inst) {
        std::vector<std::int64_t> pendientes{raiz};
        std::vector<std::uint32_t> campos;
        while (!pendientes.empty()) {
            const std::int64_t h = pendientes.back();
            pendientes.pop_back();
            // se vuelve a pedir en cada vuelta: un '__free__' crea objetos y
            // puede mover el monton
            const Objeto* obj = objeto(h);
            if (obj == nullptr) continue;
            if (obj->bloque) {
                if (obj->elem_layout < 0) continue;   // celdas escalares
                // apiladas en orden: la ULTIMA sale primero
                for (const Value& celda : obj->campos) pendientes.push_back(celda.i);
                continue;
            }
            if (obj->layout >= 0 &&
                static_cast<std::size_t>(obj->layout) < program_.layouts.size()) {
                const std::int32_t hook =
                    program_.layouts[static_cast<std::size_t>(obj->layout)].destructor;
                if (hook >= 0) {
                    RunStatus estado = llamar_destructor(hook, h, inst);
                    if (!estado.ok) return estado;
                    continue;
                }
            }
            campos.clear();
            if (const auto* propios = propios_de(*obj)) {
                campos.insert(campos.end(), propios->begin(), propios->end());
            }
            if (const auto* bloques = de_la_forma(*obj, &Layout::bloques)) {
                for (std::uint32_t c : *bloques) {
                    if (bloque_propio(*obj, c)) campos.push_back(c);
                }
            }
            std::sort(campos.begin(), campos.end());
            for (std::uint32_t c : campos) {
                if (c < obj->campos.size()) pendientes.push_back(obj->campos[c].i);
            }
        }
        liberar(raiz);
        return RunStatus{};
    }

    // Un '__free__' que corre la VM (no el MIR). Si lanza, el programa
    // termina: RT021, como el 'Call' marcado 'destructor'.
    RunStatus llamar_destructor(std::int32_t func, std::int64_t valor, const Inst& inst) {
        Value salida{0};
        Value v{};
        v.i = valor;
        RunStatus status = call(static_cast<std::size_t>(func), {v}, salida);
        if (status.thrown) {
            const Function& destructor = program_.functions[static_cast<std::size_t>(func)];
            return RunStatus::failure(
                "RT021: el " + destructor.name +
                    (destructor.unit.empty() ? std::string()
                                             : " de '" + destructor.unit + "'") +
                    " lanzo: un destructor nunca puede lanzar. Si liberar puede "
                    "fallar, registra el fallo y deja que el __free__ termine "
                    "normalmente",
                inst.line, inst.col);
        }
        if (!status.ok && status.line == 0) {
            status.line = inst.line;
            status.col = inst.col;
        }
        return status;
    }

    // '__move__(dst, src, n)': como '__copy__', pero las celdas de origen
    // quedan VACIAS (0: ningun objeto) y el valor no se copia: cada uno sigue
    // con un solo dueño, ahora el bloque nuevo.
    RunStatus mover_bloques(const Inst& inst, Frame& frame) {
        const std::int64_t destino = frame.regs[inst.args[0]].i;
        const std::int64_t origen = frame.regs[inst.args[1]].i;
        const std::int64_t n = frame.regs[inst.args[2]].i;
        if (objeto(destino) == nullptr) return no_es_objeto(inst, destino, "'__move__' hacia");
        if (objeto(origen) == nullptr) return no_es_objeto(inst, origen, "'__move__' desde");
        const std::size_t largo_origen = objeto(origen)->celdas();
        const std::size_t largo_destino = objeto(destino)->celdas();
        if (n < 0 || static_cast<std::size_t>(n) > largo_origen ||
            static_cast<std::size_t>(n) > largo_destino) {
            return excepcion("IndiceFueraDeRango", "EXC002",
                             "__move__ de " + std::to_string(n) +
                                 " elementos excede el tamaño de origen (" +
                                 std::to_string(largo_origen) + ") o destino (" +
                                 std::to_string(largo_destino) + ")",
                             inst.line, inst.col);
        }
        if (objeto(origen)->de_bytes && objeto(destino)->de_bytes) {
            Objeto* o = objeto(origen);
            std::copy_n(o->octetos.begin(), static_cast<std::size_t>(n), objeto(destino)->octetos.begin());
            std::fill_n(o->octetos.begin(), static_cast<std::size_t>(n), std::uint8_t{0});
            if (inst.dst != kNoReg) frame.regs[inst.dst].i = 0;
            return RunStatus{};
        }
        const bool objetos = objeto(origen)->elem_layout >= 0;
        for (std::size_t i = 0; i < static_cast<std::size_t>(n); ++i) {
            if (objetos) liberar(objeto(destino)->campos[i].i);
            objeto(destino)->campos[i] = objeto(origen)->campos[i];
            objeto(origen)->campos[i].i = 0;
        }
        if (inst.dst != kNoReg) frame.regs[inst.dst].i = 0;
        return RunStatus{};
    }

    // Libera 'handle' y todo lo que es suyo. Iterativo: una lista enlazada
    // larga no agota la pila de C++. Un handle que no es un objeto vivo no
    // hace nada (ver 'Op::Free').
    void liberar(std::int64_t handle) {
        std::vector<std::int64_t> pendientes{handle};
        while (!pendientes.empty()) {
            const std::int64_t h = pendientes.back();
            pendientes.pop_back();
            Objeto* obj = objeto(h);
            if (obj == nullptr) continue;
            if (obj->bloque && obj->elem_layout >= 0) {
                for (const Value& celda : obj->campos) pendientes.push_back(celda.i);
            } else if (!obj->bloque) {
                if (const auto* propios = propios_de(*obj)) {
                    for (std::uint32_t c : *propios) {
                        if (c < obj->campos.size()) pendientes.push_back(obj->campos[c].i);
                    }
                }
                // el almacenamiento de un contenedor muere con el
                if (const auto* bloques = de_la_forma(*obj, &Layout::bloques)) {
                    for (std::uint32_t c : *bloques) {
                        if (bloque_propio(*obj, c)) pendientes.push_back(obj->campos[c].i);
                    }
                }
            }
            obj->vivo = false;
            resta_bytes(obj->campos.size() * sizeof(Value) + obj->octetos.size());
            ++obj->generacion;
            if (obj->generacion == 0x80000000u) obj->generacion = 1;  // 31 bits
            std::vector<Value>().swap(obj->campos);   // devuelve la memoria
            std::vector<std::uint8_t>().swap(obj->octetos);
            huecos_.push_back(indice_de(h));
            excepciones_.erase(h);
            ++memoria_.liberados;
            --memoria_.vivos;
        }
    }

    // Una copia NUEVA de 'handle', profunda en sus objetos propios.
    std::int64_t copiar(std::int64_t handle) {
        const Objeto* origen = objeto(handle);
        if (origen == nullptr) return handle;
        const std::size_t n = origen->campos.size();
        const std::int32_t layout = origen->layout;
        const std::int32_t elem = origen->elem_layout;
        const bool bloque = origen->bloque;
        const std::int64_t nuevo = nuevo_objeto(n, layout);
        // 'nuevo_objeto' puede mover el monton: se vuelve a pedir todo
        objeto(nuevo)->campos = objeto(handle)->campos;
        objeto(nuevo)->octetos = objeto(handle)->octetos;
        // los campos ya los conto 'nuevo_objeto' (los mismos que el origen)
        suma_bytes(objeto(nuevo)->octetos.size());
        objeto(nuevo)->de_bytes = objeto(handle)->de_bytes;
        objeto(nuevo)->elem_layout = elem;
        objeto(nuevo)->bloque = bloque;
        std::vector<std::uint32_t> propios;
        if (bloque && elem >= 0) {
            for (std::uint32_t i = 0; i < n; ++i) propios.push_back(i);
        } else if (!bloque) {
            if (const auto* p = propios_de(*objeto(nuevo))) propios = *p;
            // copiar un contenedor copia su almacenamiento: dos vectores, no
            // dos nombres para el mismo bloque
            if (const auto* bl = de_la_forma(*objeto(nuevo), &Layout::bloques)) {
                for (std::uint32_t c : *bl) {
                    if (bloque_propio(*objeto(nuevo), c)) propios.push_back(c);
                }
            }
        }
        for (std::uint32_t c : propios) {
            if (c >= n) continue;
            const std::int64_t hijo = objeto(nuevo)->campos[c].i;
            if (objeto(hijo) == nullptr) continue;
            const std::int64_t copia = copiar(hijo);
            objeto(nuevo)->campos[c].i = copia;
        }
        return nuevo;
    }

public:
    Memoria memoria() const {
        Memoria m = memoria_;
        for (std::size_t i = constantes_; i < textos_.size(); ++i) {
            if (muerta_[i] == 0) ++m.cadenas_vivas;
        }
        for (const Objeto& obj : monton_) {
            if (!obj.vivo) continue;
            std::string tipo = "objeto";
            if (obj.bloque && obj.de_bytes) {
                tipo = "bloque de byte";
            } else if (obj.bloque) {
                tipo = obj.elem_layout >= 0
                    ? "bloque de " + program_.layouts[static_cast<std::size_t>(
                          obj.elem_layout)].nombre
                    : "bloque";
            } else if (obj.layout >= 0) {
                tipo = program_.layouts[static_cast<std::size_t>(obj.layout)].nombre;
            }
            ++m.vivos_por_tipo[tipo];
        }
        return m;
    }

private:

    // Las primitivas del host. La VM cumple las que puede sin salir del
    // proceso; el resto se reportan por su NOMBRE, que es lo que el backend
    // nativo enlazara y lo que el usuario declaro.
    RunStatus llamada_host(const Inst& inst, Frame& frame) {
        if (inst.func < 0 ||
            static_cast<std::size_t>(inst.func) >= program_.hosts.size()) {
            return RunStatus::failure("primitiva del host desconocida",
                                      inst.line, inst.col);
        }
        const std::string& nombre = program_.hosts[
            static_cast<std::size_t>(inst.func)];
        // lo que cumple el C++ del programa ('#extern cpp') va primero: es lo
        // que el programa declaro, como en el interprete
        if (externos_ != nullptr &&
            static_cast<std::size_t>(inst.func) < externos_->size() &&
            (*externos_)[static_cast<std::size_t>(inst.func)] != nullptr) {
            return llamar_cpp(inst, frame);
        }
        if (nombre == "__write__" && inst.args.size() == 1) {
            const std::string* texto = cadena(frame.regs[inst.args[0]].i);
            if (texto == nullptr) {
                return RunStatus::failure(
                    "'__write__' recibio algo que no es una cadena",
                    inst.line, inst.col);
            }
            std::fputs(texto->c_str(), stdout);
            if (inst.dst != kNoReg) frame.regs[inst.dst].i = 0;
            return RunStatus{};
        }
        // Las primitivas de MEMORIA ('lib/mem'). La VM es el host aqui, y su
        // monton es el asignador: un bloque de n celdas es un objeto de n
        // campos, el mismo que usa un struct. No son instrucciones del MIR a
        // proposito — ver 'GetIndex' en 'mir.hpp'.
        if (nombre == "__reserve__" && inst.args.size() == 1) {
            const std::int64_t n = frame.regs[inst.args[0]].i;
            if (n < 0) {
                return excepcion("IndiceFueraDeRango", "EXC002",
                                 "__reserve__ requiere un tamaño entero >= 0 "
                                 "(recibió " + std::to_string(n) + ")",
                                 inst.line, inst.col);
            }
            const bool de_bytes = inst.imm == 1;
            const std::int64_t bloque = nuevo_objeto(de_bytes ? 0 : static_cast<std::size_t>(n), -1);
            objeto(bloque)->bloque = true;
            objeto(bloque)->elem_layout = inst.layout;
            if (de_bytes) {
                objeto(bloque)->de_bytes = true;
                objeto(bloque)->octetos.assign(static_cast<std::size_t>(n), 0);
                suma_bytes(static_cast<std::uint64_t>(n));
            }
            if (inst.dst != kNoReg) frame.regs[inst.dst].i = bloque;
            return RunStatus{};
        }
        if (nombre == "__copy__" && inst.args.size() == 3) {
            return copia_de_bloques(inst, frame);
        }
        if (nombre == "__release__" && inst.args.size() == 1) {
            const std::int64_t bloque = frame.regs[inst.args[0]].i;
            if (objeto(bloque) == nullptr) {
                return no_es_objeto(inst, bloque, "'__release__' sobre");
            }
            // Soltar el bloque DESTRUYE lo que tiene (sus celdas no vacias,
            // por su tipo) y lo libera. Un acceso posterior por el mismo
            // puntero es RT003, como en el interprete, que marca sus celdas
            // liberadas.
            RunStatus estado = destruir(bloque, inst);
            if (!estado.ok) return estado;
            if (inst.dst != kNoReg) frame.regs[inst.dst].i = 0;
            return RunStatus{};
        }
        // '__take__(bloque, i)': SACA el valor de la celda; queda vacia (0)
        if (nombre == "__take__" && inst.args.size() == 2) {
            Objeto* obj = nullptr;
            const std::int64_t bloque = frame.regs[inst.args[0]].i;
            const std::int64_t i = frame.regs[inst.args[1]].i;
            RunStatus estado = valida_celda(inst, bloque, i, obj);
            if (!estado.ok || estado.thrown) return estado;
            Value v{};
            if (obj->de_bytes) {
                v.i = obj->octetos[static_cast<std::size_t>(i)];
                obj->octetos[static_cast<std::size_t>(i)] = 0;
            } else {
                v = obj->campos[static_cast<std::size_t>(i)];
                obj->campos[static_cast<std::size_t>(i)].i = 0;
            }
            if (inst.dst != kNoReg) frame.regs[inst.dst] = v;
            return RunStatus{};
        }
        if (nombre == "__move__" && inst.args.size() == 3) {
            return mover_bloques(inst, frame);
        }
        if (RunStatus status; llamada_de_texto(nombre, inst, frame, status)) {
            return status;
        }
        if (RunStatus status; llamada_al_sistema(nombre, inst, frame, status)) {
            return status;
        }
        return RunStatus::failure(
            "RT008: la VM no cumple la primitiva '" + nombre + "': es un prototipo, "
            "y quien ejecuta tiene que aportarlo (el C++ de un '#extern cpp', o la "
            "propia VM)", inst.line, inst.col);
    }

    // Una llamada a C++. Cada argumento cruza segun la firma que calculo el
    // MIR: los escalares tal cual (un valor de la VM ya es de maquina), una
    // cadena como su 'const char*' y un bloque como el puntero a sus celdas
    // —la memoria de la VM, no una copia: 'Value' mide 8 bytes, asi que un
    // bloque de 'int' ES un 'int64_t[]'—.
    RunStatus llamar_cpp(const Inst& inst, Frame& frame) {
        static_assert(sizeof(Value) == 8, "un bloque cruza a C++ como un buffer de 8 bytes por celda");
        const std::size_t h = static_cast<std::size_t>(inst.func);
        const Firma& firma = program_.firmas_host[h];
        std::vector<Crudo> args;
        args.reserve(inst.args.size());
        for (std::size_t k = 0; k < inst.args.size() && k < firma.params.size(); ++k) {
            const Value v = frame.regs[inst.args[k]];
            Crudo c;
            switch (firma.params[k]) {
                case Abi::Flotante:
                    c.f = v.f;
                    c.flotante = true;
                    break;
                case Abi::Cadena: {
                    const std::string* s = cadena(v.i);
                    if (s == nullptr) {
                        return RunStatus::failure("pasar a C++ algo que no es una cadena",
                                                  inst.line, inst.col);
                    }
                    c.i = static_cast<std::int64_t>(reinterpret_cast<std::intptr_t>(s->c_str()));
                    break;
                }
                case Abi::Bloque: {
                    Objeto* obj = objeto(v.i);
                    if (obj == nullptr) return no_es_objeto(inst, v.i, "pasar a C++");
                    c.i = static_cast<std::int64_t>(
                        reinterpret_cast<std::intptr_t>(obj->campos.data()));
                    break;
                }
                case Abi::BloqueDeBytes: {
                    // el buffer compacto de la VM: C++ escribe en los MISMOS bytes
                    Objeto* obj = objeto(v.i);
                    if (obj == nullptr) return no_es_objeto(inst, v.i, "pasar a C++");
                    if (!obj->de_bytes) {
                        return RunStatus::failure("pasar a C++ como 'byte ptr' algo que "
                                                  "no es un bloque de 'byte'",
                                                  inst.line, inst.col);
                    }
                    c.i = static_cast<std::int64_t>(
                        reinterpret_cast<std::intptr_t>(obj->octetos.data()));
                    break;
                }
                case Abi::BloqueSinMaquina:
                    return RunStatus::failure(
                        "RT018: este bloque de memoria no puede cruzar a '#extern cpp': "
                        "sus elementos no tienen representacion de maquina (solo 'int', "
                        "'float' y 'byte' cruzan como buffer)", inst.line, inst.col);
                default:
                    c.i = v.i;
                    break;
            }
            args.push_back(c);
        }
        // lo que la VM ya escribio sale antes que lo que escriba C++
        std::fflush(stdout);
        const Value salida = llamar_externo((*externos_)[h], firma.retorno, args);
        if (inst.dst != kNoReg) frame.regs[inst.dst] = salida;
        return RunStatus{};
    }

    // Las llamadas al HOST de 'lib/sistema': archivos, argumentos y salida.
    // El contrato es el del interprete ('runtime/interpreter/intrinsics.py'),
    // letra por letra, porque un programa no puede notar en que motor corre:
    //   - UTF-8 sin traducir los fines de linea (modo binario);
    //   - mensajes de error CANONICOS, no los del sistema;
    //   - una carpeta se lista ordenada por nombre.
    // Devuelve false si 'nombre' no es una de ellas.
    // El desplazamiento en BYTES del code point 'cp' de un texto UTF-8 (el
    // largo si 'cp' es el final). Un indice de suriaX cuenta caracteres.
    static std::size_t byte_de(const std::string& s, std::size_t cp) {
        std::size_t i = 0;
        std::size_t visto = 0;
        while (i < s.size() && visto < cp) {
            ++i;
            while (i < s.size() && (static_cast<unsigned char>(s[i]) & 0xC0u) == 0x80u) ++i;
            ++visto;
        }
        return i;
    }

    // Cuantos code points hay en los primeros 'bytes' bytes.
    static std::size_t caracteres_hasta(const std::string& s, std::size_t bytes) {
        std::size_t n = 0;
        for (std::size_t i = 0; i < bytes && i < s.size(); ++i) {
            if ((static_cast<unsigned char>(s[i]) & 0xC0u) != 0x80u) ++n;
        }
        return n;
    }

    // Las primitivas de 'lib/text'. El contrato es el del interprete
    // ('runtime/interpreter/intrinsics.py'): indices en CARACTERES, y los
    // mismos mensajes en las mismas excepciones.
    bool llamada_de_texto(const std::string& nombre, const Inst& inst,
                          Frame& frame, RunStatus& status) {
        const auto arg = [&](std::size_t i) -> Value { return frame.regs[inst.args[i]]; };
        const auto texto = [&](std::size_t i) -> std::string {
            const std::string* t = cadena(arg(i).i);
            return t == nullptr ? std::string() : *t;
        };
        const auto devolver = [&](std::int64_t v) {
            if (inst.dst != kNoReg) frame.regs[inst.dst].i = v;
        };
        status = RunStatus{};
        if (nombre == "__trozo__" && inst.args.size() == 3) {
            const std::string s = texto(0);
            const std::size_t largo = puntos_de(arg(0).i, s).largo;
            const std::int64_t desde = arg(1).i;
            const std::int64_t hasta = arg(2).i;
            if (desde < 0 || desde > hasta || static_cast<std::size_t>(hasta) > largo) {
                status = excepcion("IndiceFueraDeRango", "EXC002",
                                   "el trozo [" + std::to_string(desde) + ", " +
                                       std::to_string(hasta) + ") no cabe en una cadena de " +
                                       std::to_string(largo) + " caracteres",
                                   inst.line, inst.col);
                return true;
            }
            const std::size_t a = byte_de(s, static_cast<std::size_t>(desde));
            const std::size_t b = byte_de(s, static_cast<std::size_t>(hasta));
            devolver(interna(s.substr(a, b - a)));
            return true;
        }
        if (nombre == "__buscar__" && inst.args.size() == 3) {
            const std::string s = texto(0);
            const std::size_t largo = puntos_de(arg(0).i, s).largo;
            const std::int64_t desde = arg(2).i;
            if (desde < 0 || static_cast<std::size_t>(desde) > largo) {
                status = excepcion("IndiceFueraDeRango", "EXC002",
                                   "buscar desde " + std::to_string(desde) +
                                       " en una cadena de " + std::to_string(largo) +
                                       " caracteres",
                                   inst.line, inst.col);
                return true;
            }
            const std::size_t pos = s.find(texto(1), byte_de(s, static_cast<std::size_t>(desde)));
            devolver(pos == std::string::npos
                         ? -1 : static_cast<std::int64_t>(caracteres_hasta(s, pos)));
            return true;
        }
        if (nombre == "__empieza__" && inst.args.size() == 2) {
            const std::string s = texto(0);
            const std::string p = texto(1);
            devolver(s.size() >= p.size() && s.compare(0, p.size(), p) == 0 ? 1 : 0);
            return true;
        }
        if (nombre == "__termina__" && inst.args.size() == 2) {
            const std::string s = texto(0);
            const std::string p = texto(1);
            devolver(s.size() >= p.size() &&
                     s.compare(s.size() - p.size(), p.size(), p) == 0 ? 1 : 0);
            return true;
        }
        if (nombre == "__unir__" && inst.args.size() == 3) {
            const Objeto* bloque = objeto(arg(0).i);
            const std::int64_t n = arg(1).i;
            if (bloque == nullptr || n < 0 || static_cast<std::size_t>(n) > bloque->celdas()) {
                status = excepcion("IndiceFueraDeRango", "EXC002",
                                   "unir " + std::to_string(n) +
                                       " partes de un bloque que no las tiene",
                                   inst.line, inst.col);
                return true;
            }
            const std::string separador = texto(2);
            std::string salida;
            for (std::int64_t i = 0; i < n; ++i) {
                if (i != 0) salida += separador;
                // se vuelve a pedir: 'cadena' no mueve el monton, pero no cuesta
                const std::string* parte = cadena(objeto(arg(0).i)->campos[static_cast<std::size_t>(i)].i);
                if (parte != nullptr) salida += *parte;
            }
            devolver(interna(std::move(salida)));
            return true;
        }
        if (nombre == "__entero_de__" && inst.args.size() == 1) {
            const std::string s = texto(0);
            std::size_t i = (!s.empty() && (s[0] == '+' || s[0] == '-')) ? 1 : 0;
            bool bien = i < s.size();
            for (std::size_t k = i; k < s.size(); ++k) {
                if (s[k] < '0' || s[k] > '9') bien = false;
            }
            if (!bien) {
                status = excepcion("ConversionInvalida", "EXC004",
                                   "'" + s + "' no es un entero", inst.line, inst.col);
                return true;
            }
            // acumulado en negativo: el minimo de 64 bits cabe, su opuesto no
            const bool negativo = s[0] == '-';
            std::int64_t v = 0;
            for (std::size_t k = i; k < s.size(); ++k) {
                const int d = s[k] - '0';
                if (v < (std::numeric_limits<std::int64_t>::min() + d) / 10) {
                    status = excepcion("ConversionInvalida", "EXC004",
                                       "'" + s + "' no cabe en un int", inst.line, inst.col);
                    return true;
                }
                v = v * 10 - d;
            }
            if (!negativo) {
                if (v == std::numeric_limits<std::int64_t>::min()) {
                    status = excepcion("ConversionInvalida", "EXC004",
                                       "'" + s + "' no cabe en un int", inst.line, inst.col);
                    return true;
                }
                v = -v;
            }
            devolver(v);
            return true;
        }
        if (nombre == "__flotante_de__" && inst.args.size() == 1) {
            // la gramatica de 'text.parse_float' (la misma que el interprete),
            // y despues 'strtod': el 'double' mas cercano, como 'float()' de
            // Python. La VM no llama a 'setlocale': el punto decimal es '.'.
            const std::string s = texto(0);
            std::size_t i = 0;
            const auto cifras = [&]() {
                const std::size_t desde = i;
                while (i < s.size() && s[i] >= '0' && s[i] <= '9') ++i;
                return i > desde;
            };
            if (i < s.size() && (s[i] == '+' || s[i] == '-')) ++i;
            bool bien = cifras();
            if (bien && i < s.size() && s[i] == '.') {
                ++i;
                bien = cifras();
            }
            if (bien && i < s.size() && (s[i] == 'e' || s[i] == 'E')) {
                ++i;
                if (i < s.size() && (s[i] == '+' || s[i] == '-')) ++i;
                bien = cifras();
            }
            if (!bien || i != s.size()) {
                status = excepcion("ConversionInvalida", "EXC004",
                                   "'" + s + "' no es un float", inst.line, inst.col);
                return true;
            }
            const double x = std::strtod(s.c_str(), nullptr);
            if (std::isinf(x)) {
                status = excepcion("ConversionInvalida", "EXC004",
                                   "'" + s + "' no cabe en un float", inst.line, inst.col);
                return true;
            }
            if (inst.dst != kNoReg) frame.regs[inst.dst].f = x;
            return true;
        }
        if (nombre == "__bits_de_float__" && inst.args.size() == 1) {
            const double x = arg(0).f;
            std::int64_t bits = 0;
            std::memcpy(&bits, &x, sizeof bits);
            devolver(bits);
            return true;
        }
        if (nombre == "__float_de_bits__" && inst.args.size() == 1) {
            const std::int64_t bits = arg(0).i;
            double x = 0;
            std::memcpy(&x, &bits, sizeof x);
            if (inst.dst != kNoReg) frame.regs[inst.dst].f = x;
            return true;
        }
        if (nombre == "__utf8_largo__" && inst.args.size() == 1) {
            devolver(static_cast<std::int64_t>(texto(0).size()));
            return true;
        }
        if (nombre == "__utf8_a_bytes__" && inst.args.size() == 3) {
            const std::string s = texto(0);
            Objeto* destino = objeto(arg(1).i);
            const std::int64_t n = arg(2).i;
            if (destino == nullptr || !destino->de_bytes ||
                static_cast<std::size_t>(n) != s.size() || s.size() > destino->octetos.size()) {
                status = excepcion("IndiceFueraDeRango", "EXC002",
                                   std::to_string(n) + " bytes no caben en el bloque",
                                   inst.line, inst.col);
                return true;
            }
            std::copy(s.begin(), s.end(), destino->octetos.begin());
            devolver(0);
            return true;
        }
        if (nombre == "__utf8_de_bytes__" && inst.args.size() == 2) {
            const Objeto* datos = objeto(arg(0).i);
            const std::int64_t n = arg(1).i;
            if (datos == nullptr || !datos->de_bytes || n < 0 ||
                static_cast<std::size_t>(n) > datos->octetos.size()) {
                status = excepcion("IndiceFueraDeRango", "EXC002",
                                   std::to_string(n) + " bytes de un bloque que no los tiene",
                                   inst.line, inst.col);
                return true;
            }
            std::string s(datos->octetos.begin(), datos->octetos.begin() + n);
            if (!es_utf8(s)) {
                status = excepcion("ConversionInvalida", "EXC004",
                                   "los bytes no son UTF-8 valido", inst.line, inst.col);
                return true;
            }
            devolver(interna(std::move(s)));
            return true;
        }
        return false;
    }

    bool llamada_al_sistema(const std::string& nombre, const Inst& inst,
                            Frame& frame, RunStatus& status) {
        namespace fs = std::filesystem;
        const auto arg = [&](std::size_t i) -> Value {
            return frame.regs[inst.args[i]];
        };
        const auto texto = [&](std::size_t i) -> std::string {
            const std::string* t = cadena(arg(i).i);
            return t == nullptr ? std::string() : *t;
        };
        const auto devolver = [&](std::int64_t v) {
            if (inst.dst != kNoReg) frame.regs[inst.dst].i = v;
        };
        const auto fallo = [&](const std::string& mensaje) {
            status = excepcion("ErrorDeArchivo", "EXC003", mensaje, inst.line,
                               inst.col);
            return true;
        };
        status = RunStatus{};

        // lib/sistema/rutas: 'os.path' tal cual (ver suriax/mir/rutas.hpp)
        if (nombre == "__directorio_actual__" && inst.args.empty()) {
            devolver(interna(rutas::directorio_actual()));
            return true;
        }
        if (nombre == "__separador__" && inst.args.empty()) {
            devolver(interna(rutas::separador()));
            return true;
        }
        if (inst.args.size() == 1) {
            if (nombre == "__entorno__") { devolver(interna(rutas::entorno(texto(0)))); return true; }
            if (nombre == "__absoluta__") { devolver(interna(rutas::absoluta(texto(0)))); return true; }
            if (nombre == "__normaliza__") { devolver(interna(rutas::normaliza(texto(0)))); return true; }
            if (nombre == "__carpeta_de__") { devolver(interna(rutas::carpeta_de(texto(0)))); return true; }
            if (nombre == "__nombre_de__") { devolver(interna(rutas::nombre_de(texto(0)))); return true; }
            if (nombre == "__es_carpeta__") { devolver(rutas::es_carpeta(texto(0)) ? 1 : 0); return true; }
            if (nombre == "__es_archivo__") { devolver(rutas::es_archivo(texto(0)) ? 1 : 0); return true; }
        }
        if (nombre == "__une__" && inst.args.size() == 2) {
            devolver(interna(rutas::une(texto(0), texto(1))));
            return true;
        }

        if (nombre == "__leer_archivo__" && inst.args.size() == 1) {
            const std::string ruta = texto(0);
            const fs::path p = ruta_de(ruta);
            std::error_code ec;
            if (fs::is_directory(p, ec)) {
                return fallo("'" + ruta + "' es una carpeta, no un archivo");
            }
            if (!fs::exists(p, ec)) return fallo("no existe el archivo '" + ruta + "'");
            std::ifstream archivo(p, std::ios::binary);
            if (!archivo) return fallo("no se pudo leer '" + ruta + "'");
            std::ostringstream contenido;
            contenido << archivo.rdbuf();
            if (archivo.bad()) return fallo("no se pudo leer '" + ruta + "'");
            std::string leido = contenido.str();
            if (!es_utf8(leido)) return fallo("'" + ruta + "' no es texto UTF-8");
            devolver(interna(std::move(leido)));
            return true;
        }
        if (nombre == "__escribir_archivo__" && inst.args.size() == 2) {
            const std::string ruta = texto(0);
            std::ofstream archivo(ruta_de(ruta), std::ios::binary | std::ios::trunc);
            const std::string contenido = texto(1);
            if (archivo) archivo.write(contenido.data(),
                                       static_cast<std::streamsize>(contenido.size()));
            if (!archivo) return fallo("no se pudo escribir '" + ruta + "'");
            devolver(0);
            return true;
        }
        if (nombre == "__tamano__" && inst.args.size() == 1) {
            const std::string ruta = texto(0);
            const fs::path p = ruta_de(ruta);
            std::error_code ec;
            if (fs::is_directory(p, ec)) {
                return fallo("'" + ruta + "' es una carpeta, no un archivo");
            }
            if (!fs::exists(p, ec)) return fallo("no existe el archivo '" + ruta + "'");
            const auto tamano = fs::file_size(p, ec);
            if (ec) return fallo("no se pudo leer '" + ruta + "'");
            devolver(static_cast<std::int64_t>(tamano));
            return true;
        }
        if (nombre == "__leer_bytes__" && inst.args.size() == 3) {
            // directo al buffer compacto del bloque: sin pasar por celdas
            const std::string ruta = texto(0);
            Objeto* bloque = objeto(arg(1).i);
            const std::int64_t n = arg(2).i;
            if (bloque == nullptr || !bloque->de_bytes || n < 0 ||
                static_cast<std::size_t>(n) > bloque->octetos.size()) {
                return fallo("no se pudo leer '" + ruta + "'");
            }
            std::ifstream archivo(ruta_de(ruta), std::ios::binary);
            if (!archivo) return fallo("no existe el archivo '" + ruta + "'");
            archivo.read(reinterpret_cast<char*>(bloque->octetos.data()),
                         static_cast<std::streamsize>(n));
            if (archivo.gcount() != n) return fallo("no se pudo leer '" + ruta + "'");
            devolver(0);
            return true;
        }
        if (nombre == "__escribir_bytes__" && inst.args.size() == 3) {
            const std::string ruta = texto(0);
            const Objeto* bloque = objeto(arg(1).i);
            const std::int64_t n = arg(2).i;
            if (bloque == nullptr || !bloque->de_bytes || n < 0 ||
                static_cast<std::size_t>(n) > bloque->octetos.size()) {
                return fallo("no se pudo escribir '" + ruta + "'");
            }
            std::ofstream archivo(ruta_de(ruta), std::ios::binary | std::ios::trunc);
            if (archivo) archivo.write(reinterpret_cast<const char*>(bloque->octetos.data()),
                                       static_cast<std::streamsize>(n));
            if (!archivo) return fallo("no se pudo escribir '" + ruta + "'");
            devolver(0);
            return true;
        }
        if (nombre == "__existe__" && inst.args.size() == 1) {
            std::error_code ec;
            devolver(fs::exists(ruta_de(texto(0)), ec) ? 1 : 0);
            return true;
        }
        if (nombre == "__crear_carpeta__" && inst.args.size() == 1) {
            // 'mkdir -p': si ya existe, nada; un archivo con ese nombre, o
            // una ruta que no se puede crear, es ErrorDeArchivo (el mismo
            // mensaje que el interprete)
            const std::string ruta = texto(0);
            std::error_code ec;
            const fs::path p = ruta_de(ruta);
            if (ruta.empty()) return fallo("no se pudo crear la carpeta '" + ruta + "'");
            fs::create_directories(p, ec);
            if (ec || !fs::is_directory(p, ec)) {
                return fallo("no se pudo crear la carpeta '" + ruta + "'");
            }
            devolver(0);
            return true;
        }
        if (nombre == "__entradas__" && inst.args.size() == 1) {
            const std::string ruta = texto(0);
            std::string problema;
            if (!listar(ruta, problema)) return fallo(problema);
            devolver(static_cast<std::int64_t>(listado_.size()));
            return true;
        }
        if (nombre == "__entrada__" && inst.args.size() == 2) {
            const std::string ruta = texto(0);
            std::string problema;
            if (ruta != carpeta_listada_ && !listar(ruta, problema)) {
                return fallo(problema);
            }
            const std::int64_t i = arg(1).i;
            if (i < 0 || static_cast<std::size_t>(i) >= listado_.size()) {
                status = excepcion("IndiceFueraDeRango", "EXC002",
                                   "entrada " + std::to_string(i) +
                                       " fuera de rango [0, " +
                                       std::to_string(listado_.size()) + ")",
                                   inst.line, inst.col);
                return true;
            }
            devolver(interna(listado_[static_cast<std::size_t>(i)]));
            return true;
        }
        if (nombre == "__argumentos__" && inst.args.empty()) {
            devolver(static_cast<std::int64_t>(argumentos_.size()));
            return true;
        }
        if (nombre == "__argumento__" && inst.args.size() == 1) {
            const std::int64_t i = arg(0).i;
            if (i < 0 || static_cast<std::size_t>(i) >= argumentos_.size()) {
                status = excepcion("IndiceFueraDeRango", "EXC002",
                                   "argumento " + std::to_string(i) +
                                       " fuera de rango [0, " +
                                       std::to_string(argumentos_.size()) + ")",
                                   inst.line, inst.col);
                return true;
            }
            devolver(interna(argumentos_[static_cast<std::size_t>(i)]));
            return true;
        }
        if (nombre == "__escribir_error__" && inst.args.size() == 1) {
            const std::string t = texto(0);
            std::fputs(t.c_str(), stderr);
            devolver(0);
            return true;
        }
        if (nombre == "__salir__" && inst.args.size() == 1) {
            // AHORA, sin desenrollar: los '__free__' pendientes no corren
            // (como 'std::exit'). Lo ya escrito se vuelca antes.
            std::fflush(stdout);
            std::fflush(stderr);
            std::exit(static_cast<int>(arg(0).i));
        }
        return false;
    }

    // Lista 'ruta' ORDENADA en 'listado_'. Si no puede, deja el mensaje
    // canonico en 'problema'.
    bool listar(const std::string& ruta, std::string& problema) {
        namespace fs = std::filesystem;
        const fs::path p = ruta_de(ruta);
        std::error_code ec;
        carpeta_listada_.clear();
        listado_.clear();
        if (!fs::exists(p, ec)) {
            problema = "no existe la carpeta '" + ruta + "'";
            return false;
        }
        if (!fs::is_directory(p, ec)) {
            problema = "'" + ruta + "' no es una carpeta";
            return false;
        }
        for (fs::directory_iterator it(p, ec), fin; !ec && it != fin; it.increment(ec)) {
            const std::u8string nombre = it->path().filename().u8string();
            listado_.emplace_back(nombre.begin(), nombre.end());
        }
        if (ec) {
            listado_.clear();
            problema = "no se pudo listar '" + ruta + "'";
            return false;
        }
        // 'std::string' compara bytes sin signo, y en UTF-8 el orden de los
        // bytes es el de los code points: el mismo que 'sorted' en Python
        std::sort(listado_.begin(), listado_.end());
        carpeta_listada_ = ruta;
        return true;
    }

    // Una ruta de suriaX (UTF-8) como ruta del sistema. En Windows un
    // 'std::string' se leeria en la pagina de codigos del sistema y una 'ñ'
    // apuntaria a otro archivo.
    static std::filesystem::path ruta_de(const std::string& ruta) {
        return std::filesystem::path(std::u8string(ruta.begin(), ruta.end()));
    }

    // ¿Es UTF-8 valido? Estricto como el decodificador de Python: sin formas
    // largas, sin sustitutos (U+D800..U+DFFF) y nada por encima de U+10FFFF.
    static bool es_utf8(const std::string& s) {
        std::size_t i = 0;
        const std::size_t n = s.size();
        while (i < n) {
            const auto c = static_cast<unsigned char>(s[i]);
            if (c < 0x80u) { ++i; continue; }
            std::size_t largo = 0;
            std::uint32_t punto = 0;
            std::uint32_t minimo = 0;
            if ((c & 0xE0u) == 0xC0u) { largo = 2; punto = c & 0x1Fu; minimo = 0x80u; }
            else if ((c & 0xF0u) == 0xE0u) { largo = 3; punto = c & 0x0Fu; minimo = 0x800u; }
            else if ((c & 0xF8u) == 0xF0u) { largo = 4; punto = c & 0x07u; minimo = 0x10000u; }
            else return false;
            if (i + largo > n) return false;
            for (std::size_t j = 1; j < largo; ++j) {
                const auto k = static_cast<unsigned char>(s[i + j]);
                if ((k & 0xC0u) != 0x80u) return false;
                punto = (punto << 6) | (k & 0x3Fu);
            }
            if (punto < minimo || punto > 0x10FFFFu ||
                (punto >= 0xD800u && punto <= 0xDFFFu)) {
                return false;
            }
            i += largo;
        }
        return true;
    }

    const Program& program_;
    std::uint64_t limite_;
    std::uint64_t pasos_ = 0;
    std::size_t depth_ = 0;
    std::ostream* traza_ = nullptr;
    //: los argumentos del programa ('sistema.argumento')
    std::vector<std::string> argumentos_;
    //: la ultima carpeta listada ('__entradas__'), para no releerla en cada
    //: '__entrada__'
    std::string carpeta_listada_;
    std::vector<std::string> listado_;
    std::vector<Value> globales_;
    const std::vector<FuncionExterna>* externos_ = nullptr;
    //: la tabla de cadenas VIVA: arranca con las del programa y crece
    // 'deque' y no 'vector': crecer no mueve las cadenas que ya estan, asi
    // que las claves del indice (vistas sobre ellas) siguen validas.
    std::deque<std::string> textos_;
    //: 1 si el indice es un HUECO (una cadena recogida)
    std::vector<std::uint8_t> muerta_;
    std::vector<std::size_t> huecos_texto_;
    //: las primeras 'constantes_' son del programa y no se recogen
    std::size_t constantes_ = 0;
    std::uint64_t cadenas_nuevas_ = 0;
    std::uint64_t umbral_cadenas_ = 4096;
    bool barrido_pendiente_ = false;
    //: los marcos de las llamadas en curso: las RAICES del barrido
    std::vector<const Frame*> marcos_;
    std::unordered_map<std::string_view, std::int64_t> indice_de_texto_;
    // Los code points de las cadenas que se indexan o se miden, por indice.
    // Una cadena es inmutable, asi que se decodifica UNA vez: decodificarla
    // en cada 's[i]' volvia cuadratico a un lexer que recorre su fuente
    // caracter a caracter. Una cadena ASCII no guarda nada: su byte i ES su
    // caracter i.
    std::unordered_map<std::int64_t, Puntos> puntos_;
    std::vector<Objeto> monton_;
    //: los indices de los objetos liberados, para reutilizarlos
    std::vector<std::uint32_t> huecos_;
    Memoria memoria_;
    //: el limite de memoria del programa (0 = sin limite) y si se paso
    std::uint64_t limite_bytes_ = 0;
    bool excedida_ = false;
    //: las excepciones que lanzo el runtime (EXCxxx), para reportarlas si
    //: nadie las atrapa
    std::unordered_map<std::int64_t, std::string> excepciones_;
};

}  // namespace

RunStatus run(const Program& program, std::uint64_t step_limit,
              std::ostream* traza, std::vector<std::string> argumentos,
              Memoria* memoria, const std::vector<FuncionExterna>* externos,
              std::uint64_t limite_bytes) {
    if (program.entry < 0) {
        return RunStatus::failure("el programa no declara 'main'", 0, 0);
    }
    Machine machine(program, step_limit, traza, std::move(argumentos), externos,
                    limite_bytes);
    // las estadisticas de memoria salen por TODAS las salidas de 'run'
    struct AlSalir {
        Machine& m;
        Memoria* destino;
        ~AlSalir() {
            if (destino == nullptr) return;
            m.barrido_final();
            *destino = m.memoria();
        }
    } al_salir{machine, memoria};
    Value salida{0};
    // La INICIALIZACION de las globales corre antes de la entrada: es lo que
    // hace el interprete, y sin ella una global calculada valdria cero.
    if (program.init >= 0 &&
        !program.functions[static_cast<std::size_t>(program.init)]
             .blocks.empty()) {
        Value ignorado{0};
        const RunStatus init = machine.call(
            static_cast<std::size_t>(program.init), {}, ignorado);
        if (!init.ok) return init;
    }
    RunStatus status =
        machine.call(static_cast<std::size_t>(program.entry), {}, salida);
    if (status.thrown) {
        // escapo de todo 'try': el interprete lo llama asi y sale con 70.
        std::string excepcion;
        if (machine.describe_excepcion(status.thrown_value, excepcion)) {
            return RunStatus::failure("excepción no capturada — " + excepcion, 0, 0);
        }
        return RunStatus::failure(
            "error no capturado — RT020: throw " +
                machine.describe_lanzado(status.thrown_value, status.thrown_tag),
            0, 0);
    }
    if (status.ok) {
        status.exit = salida.i;
        machine.liberar_globales();
    }
    return status;
}

}  // namespace suriax::mir

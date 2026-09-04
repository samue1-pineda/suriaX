#include "suriax/mir/vm.hpp"

#include <cmath>
#include <cstdio>
#include <limits>
#include <iomanip>
#include <sstream>
#include <string>
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

// Un objeto del monton: los campos de un struct, por indice.
//
// El valor de un struct es un HANDLE (el indice en este vector), no el objeto:
// asi cabe en un registro y se pasa como un entero. El monton crece y no se
// recoge — la VM ejecuta un programa y termina, y un recolector aqui seria
// resolver un problema que el modelo de PROPIEDAD del lenguaje ya resuelve
// (cuando el MIR baje las destrucciones, cada objeto muere donde su dueno).
using Object = std::vector<Value>;

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
    Machine(const Program& program, std::uint64_t limite)
        : program_(program), limite_(limite) {
        globales_.assign(program.globals.size(), Value{0});
        textos_ = program.strings;
    }

    RunStatus call(std::size_t indice, const std::vector<Value>& args,
                   Value& salida) {
        if (depth_ >= kMaxDepth) {
            return RunStatus::failure(
                "recursion demasiado profunda (limite " +
                    std::to_string(kMaxDepth) + " marcos)", 0, 0);
        }
        const Function& fn = program_.functions[indice];
        if (fn.blocks.empty()) {
            return RunStatus::failure(
                "la funcion '" + fn.name + "' no tiene cuerpo en el MIR" +
                    (fn.prototype ? " (es un prototipo: lo aporta el host, y "
                                    "la VM todavia no liga prototipos)" : ""),
                0, 0);
        }

        Frame frame;
        frame.slots.assign(fn.slots.size(), Value{0});
        frame.regs.assign(fn.regs, Value{0});
        for (std::size_t i = 0; i < args.size() && i < fn.params; ++i) {
            frame.slots[i] = args[i];
        }

        ++depth_;
        const RunStatus status = ejecutar(fn, frame, salida);
        --depth_;
        return status;
    }

private:
    RunStatus ejecutar(const Function& fn, Frame& frame, Value& salida) {
        BlockId actual = 0;
        while (true) {
            if (actual >= fn.blocks.size()) {
                return RunStatus::failure("salto a un bloque que no existe",
                                          0, 0);
            }
            const Block& bloque = fn.blocks[actual];
            bool atrapada = false;
            for (const Inst& inst : bloque.insts) {
                if (limite_ != 0 && ++pasos_ > limite_) {
                    return RunStatus::failure(
                        "limite de pasos alcanzado (" +
                            std::to_string(limite_) + "): el programa no "
                            "termina o hace falta subir el limite",
                        inst.line, inst.col);
                }
                RunStatus status = ejecutar_inst(inst, frame);
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
                monton_.emplace_back(static_cast<std::size_t>(inst.imm),
                                     Value{0});
                reg(inst.dst).i =
                    static_cast<std::int64_t>(monton_.size() - 1);
                return RunStatus{};
            case Op::GetField: {
                RunStatus estado = valida_campo(inst, reg(inst.a).i);
                if (!estado.ok) return estado;
                reg(inst.dst) = monton_[static_cast<std::size_t>(reg(inst.a).i)]
                                    [static_cast<std::size_t>(inst.imm)];
                return RunStatus{};
            }
            case Op::SetField: {
                RunStatus estado = valida_campo(inst, reg(inst.a).i);
                if (!estado.ok) return estado;
                monton_[static_cast<std::size_t>(reg(inst.a).i)]
                       [static_cast<std::size_t>(inst.imm)] = reg(inst.b);
                return RunStatus{};
            }
            case Op::Copy: {
                const std::int64_t origen = reg(inst.a).i;
                if (origen < 0 ||
                    static_cast<std::size_t>(origen) >= monton_.size()) {
                    return RunStatus::failure("copia de un objeto que no "
                                              "existe", inst.line, inst.col);
                }
                monton_.push_back(monton_[static_cast<std::size_t>(origen)]);
                reg(inst.dst).i =
                    static_cast<std::int64_t>(monton_.size() - 1);
                return RunStatus{};
            }

            case Op::GetIndex: {
                RunStatus estado = valida_celda(inst, reg(inst.a).i,
                                                reg(inst.b).i);
                if (!estado.ok) return estado;
                reg(inst.dst) = monton_[static_cast<std::size_t>(reg(inst.a).i)]
                                       [static_cast<std::size_t>(reg(inst.b).i)];
                return RunStatus{};
            }
            case Op::SetIndex: {
                RunStatus estado = valida_celda(inst, reg(inst.a).i,
                                                reg(inst.b).i);
                if (!estado.ok) return estado;
                monton_[static_cast<std::size_t>(reg(inst.a).i)]
                       [static_cast<std::size_t>(reg(inst.b).i)] = reg(inst.c);
                return RunStatus{};
            }

            case Op::CallHost:
                return llamada_host(inst, frame);
            case Op::Move: reg(inst.dst) = reg(inst.a); return RunStatus{};
            case Op::LoadLocal:
                reg(inst.dst) = frame.slots[inst.slot];
                return RunStatus{};
            case Op::StoreLocal:
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
                    return RunStatus::failure("division por cero", inst.line,
                                              inst.col);
                }
                reg(inst.dst).i = div_trunc(reg(inst.a).i, reg(inst.b).i);
                return RunStatus{};
            case Op::RemI:
                if (reg(inst.b).i == 0) {
                    return RunStatus::failure("resto de una division por cero",
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
                    puntos_de_codigo(*texto).size());
                return RunStatus{};
            }
            case Op::IndexStr: {
                const std::string* texto = cadena(reg(inst.a).i);
                if (texto == nullptr) {
                    return RunStatus::failure(
                        "indexar algo que no es una cadena del programa",
                        inst.line, inst.col);
                }
                const std::vector<std::uint32_t> puntos =
                    puntos_de_codigo(*texto);
                const std::int64_t i = reg(inst.b).i;
                if (i < 0 || static_cast<std::size_t>(i) >= puntos.size()) {
                    return RunStatus::failure(
                        "indice " + std::to_string(i) + " fuera de la cadena "
                        "(longitud " + std::to_string(puntos.size()) + ")",
                        inst.line, inst.col);
                }
                reg(inst.dst).i = puntos[static_cast<std::size_t>(i)];
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
            case Op::ToStr:
                reg(inst.dst).i = interna(texto_de(reg(inst.a), inst.imm));
                return RunStatus{};
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
            // La transferencia no mueve nada en ejecucion: el valor ya esta
            // donde esta. Lo unico que cambia es que su ambito deja de
            // destruirlo.
            case Op::MarkMoved:
                if (inst.imm >= 0) {
                    frame.slots[static_cast<std::size_t>(inst.imm)].i = 0;
                }
                return RunStatus{};
            case Op::Borrow:
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
                Value salida{0};
                RunStatus status =
                    call(static_cast<std::size_t>(inst.func), args, salida);
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

    // La cadena que nombra un indice, o nullptr si no lo es.
    const std::string* cadena(std::int64_t indice) const {
        if (indice < 0 ||
            static_cast<std::size_t>(indice) >= textos_.size()) {
            return nullptr;
        }
        return &textos_[static_cast<std::size_t>(indice)];
    }

    // Una cadena NUEVA entra en la tabla y devuelve su indice. Se deduplica
    // por texto para que la tabla no crezca sin freno en un bucle que
    // construye siempre lo mismo.
    std::int64_t interna(std::string texto) {
        for (std::size_t i = 0; i < textos_.size(); ++i) {
            if (textos_[i] == texto) return static_cast<std::int64_t>(i);
        }
        textos_.push_back(std::move(texto));
        return static_cast<std::int64_t>(textos_.size() - 1);
    }

    // Un valor escrito como texto. Tiene que dar EXACTAMENTE lo mismo que
    // 'format_value' del interprete: es lo que acaba en la salida del
    // programa, y el diferencial compara salidas.
    std::string texto_de(Value v, std::int64_t modo) const {
        switch (modo) {
            case 0: return std::to_string(v.i);
            case 1: {
                // Python escribe '3.5' y '4.0': un flotante siempre lleva
                // parte decimal, y nunca ceros de relleno.
                std::ostringstream os;
                os << std::setprecision(17) << v.f;
                std::string s = os.str();
                if (s.find_first_of(".eEni") == std::string::npos) s += ".0";
                return s;
            }
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

    RunStatus copia_de_bloques(const Inst& inst, Frame& frame) {
        const std::int64_t destino = frame.regs[inst.args[0]].i;
        const std::int64_t origen = frame.regs[inst.args[1]].i;
        const std::int64_t n = frame.regs[inst.args[2]].i;
        if (destino < 0 || origen < 0 ||
            static_cast<std::size_t>(destino) >= monton_.size() ||
            static_cast<std::size_t>(origen) >= monton_.size()) {
            return RunStatus::failure("'__copy__' entre bloques que no "
                                      "existen", inst.line, inst.col);
        }
        const Object fuente = monton_[static_cast<std::size_t>(origen)];
        Object& hacia = monton_[static_cast<std::size_t>(destino)];
        if (n < 0 || static_cast<std::size_t>(n) > fuente.size() ||
            static_cast<std::size_t>(n) > hacia.size()) {
            return RunStatus::failure(
                "'__copy__' de " + std::to_string(n) + " elementos excede el "
                "tamano de origen (" + std::to_string(fuente.size()) +
                ") o destino (" + std::to_string(hacia.size()) + ")",
                inst.line, inst.col);
        }
        for (std::size_t i = 0; i < static_cast<std::size_t>(n); ++i) {
            hacia[i] = fuente[i];
        }
        if (inst.dst != kNoReg) frame.regs[inst.dst].i = 0;
        return RunStatus{};
    }

    // Un acceso por INDICE: el bloque tiene que existir y el indice caer
    // dentro. El mensaje nombra el tamano porque un "fuera de rango" sin el
    // no dice que rango era.
    RunStatus valida_celda(const Inst& inst, std::int64_t handle,
                           std::int64_t indice) const {
        if (handle < 0 || static_cast<std::size_t>(handle) >= monton_.size()) {
            return RunStatus::failure("acceso por indice a un bloque que no "
                                      "existe", inst.line, inst.col);
        }
        const Object& obj = monton_[static_cast<std::size_t>(handle)];
        if (indice < 0 || static_cast<std::size_t>(indice) >= obj.size()) {
            return RunStatus::failure(
                "indice " + std::to_string(indice) + " fuera de rango [0, " +
                    std::to_string(obj.size()) + ")", inst.line, inst.col);
        }
        return RunStatus{};
    }

    RunStatus valida_campo(const Inst& inst, std::int64_t handle) const {
        if (handle < 0 || static_cast<std::size_t>(handle) >= monton_.size()) {
            return RunStatus::failure(
                "acceso a un campo de algo que no es un objeto", inst.line,
                inst.col);
        }
        const Object& obj = monton_[static_cast<std::size_t>(handle)];
        if (inst.imm < 0 ||
            static_cast<std::size_t>(inst.imm) >= obj.size()) {
            return RunStatus::failure(
                "el objeto no tiene el campo " + std::to_string(inst.imm),
                inst.line, inst.col);
        }
        return RunStatus{};
    }

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
                return RunStatus::failure(
                    "'__reserve__' requiere un tamano >= 0 (recibio " +
                        std::to_string(n) + ")", inst.line, inst.col);
            }
            monton_.emplace_back(static_cast<std::size_t>(n), Value{0});
            if (inst.dst != kNoReg) {
                frame.regs[inst.dst].i =
                    static_cast<std::int64_t>(monton_.size() - 1);
            }
            return RunStatus{};
        }
        if (nombre == "__copy__" && inst.args.size() == 3) {
            return copia_de_bloques(inst, frame);
        }
        if (nombre == "__release__" && inst.args.size() == 1) {
            const std::int64_t bloque = frame.regs[inst.args[0]].i;
            if (bloque < 0 ||
                static_cast<std::size_t>(bloque) >= monton_.size()) {
                return RunStatus::failure("'__release__' sobre un bloque que "
                                          "no existe", inst.line, inst.col);
            }
            // Liberar es VACIAR el objeto: cualquier acceso posterior falla
            // por limites en vez de leer lo que hubiera quedado, que es la
            // deteccion de uso-despues-de-liberar que hace el interprete
            // marcando sus celdas. Devolver el hueco al asignador es cosa
            // del backend nativo, no de la VM.
            monton_[static_cast<std::size_t>(bloque)].clear();
            if (inst.dst != kNoReg) frame.regs[inst.dst].i = 0;
            return RunStatus{};
        }
        return RunStatus::failure(
            "la VM no cumple la primitiva '" + nombre + "': es un prototipo, "
            "y quien ejecuta tiene que aportarlo", inst.line, inst.col);
    }

    const Program& program_;
    std::uint64_t limite_;
    std::uint64_t pasos_ = 0;
    std::size_t depth_ = 0;
    std::vector<Value> globales_;
    //: la tabla de cadenas VIVA: arranca con las del programa y crece
    std::vector<std::string> textos_;
    std::vector<Object> monton_;
};

}  // namespace

RunStatus run(const Program& program, std::uint64_t step_limit) {
    if (program.entry < 0) {
        return RunStatus::failure("el programa no declara 'main'", 0, 0);
    }
    Machine machine(program, step_limit);
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
        return RunStatus::failure(
            "error no capturado — throw " + std::to_string(status.thrown_value),
            0, 0);
    }
    if (status.ok) status.exit = salida.i;
    return status;
}

}  // namespace suriax::mir

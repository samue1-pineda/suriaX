#include "suriax/mir/verify.hpp"

#include <algorithm>
#include <map>
#include <queue>

namespace suriax::mir {
namespace {

// El estado de un slot en un punto del programa. El orden importa: unir dos
// caminos se queda con el MAYOR, y por eso 'QuizaMovido' esta por encima de
// los dos estados que lo producen.
enum class Estado : std::uint8_t {
    NoInicializado = 0,
    Vivo = 1,
    Movido = 2,
    QuizaMovido = 3,
};

Estado unir(Estado a, Estado b) {
    if (a == b) return a;
    // no inicializado no contradice a nada: es "todavia no dice nada"
    if (a == Estado::NoInicializado) return b;
    if (b == Estado::NoInicializado) return a;
    if ((a == Estado::Vivo && b == Estado::Movido) ||
        (a == Estado::Movido && b == Estado::Vivo)) {
        return Estado::QuizaMovido;
    }
    return std::max(a, b);
}

using Mapa = std::vector<Estado>;

bool unir_en(Mapa& destino, const Mapa& origen) {
    bool cambio = false;
    for (std::size_t i = 0; i < destino.size() && i < origen.size(); ++i) {
        const Estado nuevo = unir(destino[i], origen[i]);
        if (nuevo != destino[i]) {
            destino[i] = nuevo;
            cambio = true;
        }
    }
    return cambio;
}

// De que slot viene cada registro que sostiene un prestamo. Se lleva por
// bloque igual que el estado: un 'ptr' que nace en una rama no presta nada en
// la otra.
using Prestamos = std::map<Reg, std::uint32_t>;

class Verificador {
public:
    Verificador(const Function& fn, std::vector<Finding>& salida)
        : fn_(fn), salida_(salida) {}

    void run() {
        if (fn_.blocks.empty()) return;
        const std::size_t n = fn_.blocks.size();
        entradas_.assign(n, Mapa(fn_.slots.size(), Estado::NoInicializado));
        visitado_.assign(n, false);

        // los PARAMETROS llegan vivos: los trajo el llamador
        for (std::size_t i = 0; i < fn_.params && i < fn_.slots.size(); ++i) {
            entradas_[0][i] = Estado::Vivo;
        }

        // Punto fijo por lista de trabajo. Termina porque el reticulo tiene
        // altura 3 y el estado de un slot solo puede SUBIR.
        std::queue<BlockId> pendientes;
        pendientes.push(0);
        visitado_[0] = true;
        while (!pendientes.empty()) {
            const BlockId id = pendientes.front();
            pendientes.pop();
            Mapa estado = entradas_[id];
            Prestamos prestamos;
            recorrer(id, estado, prestamos);
            for (BlockId sucesor : sucesores(id)) {
                if (sucesor >= fn_.blocks.size()) continue;
                const bool cambio = unir_en(entradas_[sucesor], estado);
                if (cambio || !visitado_[sucesor]) {
                    visitado_[sucesor] = true;
                    pendientes.push(sucesor);
                }
            }
        }
    }

private:
    std::vector<BlockId> sucesores(BlockId id) const {
        const Block& b = fn_.blocks[id];
        std::vector<BlockId> salida;
        switch (b.term) {
            case Term::Jump: salida.push_back(b.target); break;
            case Term::Branch:
                salida.push_back(b.target);
                salida.push_back(b.otherwise);
                break;
            case Term::Return:
            case Term::Throw:
            case Term::Unreachable:
                break;
        }
        // la arista de EXCEPCION es una arista: sin ella el pad de un 'try'
        // se analizaria como codigo muerto y no se verificaria nada dentro.
        if (b.handler >= 0) salida.push_back(static_cast<BlockId>(b.handler));
        return salida;
    }

    void recorrer(BlockId id, Mapa& estado, Prestamos& prestamos) {
        const Block& b = fn_.blocks[id];
        for (const Inst& inst : b.insts) {
            // lo que puso el lowering no es codigo del programa: verificarlo
            // seria pedirle cuentas al destructor por destruir.
            if (inst.synthetic) continue;
            switch (inst.op) {
                case Op::StoreLocal:
                    // reasignar REVIVE: 'x = otro' despues de 'move x' vuelve
                    // a hacerlo suyo, y prohibirlo seria prohibir reutilizar
                    // una variable.
                    if (inst.slot < estado.size()) {
                        estado[inst.slot] = Estado::Vivo;
                    }
                    break;
                case Op::LoadLocal:
                    leer(inst, estado);
                    break;
                case Op::MarkMoved:
                    if (inst.slot < estado.size()) {
                        avisar_prestamo_colgado(inst, prestamos);
                        estado[inst.slot] = Estado::Movido;
                    }
                    break;
                case Op::Borrow:
                    leer(inst, estado);
                    if (inst.dst != kNoReg) prestamos[inst.dst] = inst.slot;
                    break;
                default:
                    // un prestamo que se copia sigue prestando lo mismo
                    if (inst.op == Op::Move && inst.dst != kNoReg) {
                        const auto origen = prestamos.find(inst.a);
                        if (origen != prestamos.end()) {
                            prestamos[inst.dst] = origen->second;
                        }
                    }
                    break;
            }
        }
    }

    // Como nombrar un slot en un mensaje. El indice no le dice nada a quien
    // escribio el programa.
    std::string nombre_de(std::uint32_t slot) const {
        if (slot < fn_.slot_names.size() && !fn_.slot_names[slot].empty()) {
            return "'" + fn_.slot_names[slot] + "'";
        }
        return "el slot " + std::to_string(slot);
    }

    void leer(const Inst& inst, const Mapa& estado) {
        if (inst.slot >= estado.size()) return;
        const Estado e = estado[inst.slot];
        if (e != Estado::Movido && e != Estado::QuizaMovido) return;
        salida_.push_back(Finding{
            fn_.name,
            "se usa " + nombre_de(inst.slot) + " despues de " +
                (e == Estado::Movido ? "haberlo transferido ('move' o 'free')"
                                     : "que ALGUN camino lo transfiriera"),
            inst.line, inst.col, e == Estado::Movido});
    }

    // Prestar algo y luego transferirlo deja el puntero apuntando a un valor
    // que ya no es de nadie: es el tiempo de vida que la Fase 6 pone aqui.
    void avisar_prestamo_colgado(const Inst& inst,
                                 const Prestamos& prestamos) {
        for (const auto& par : prestamos) {
            if (par.second != inst.slot) continue;
            salida_.push_back(Finding{
                fn_.name,
                nombre_de(inst.slot) + " se transfiere mientras un "
                "puntero sigue apuntando a el",
                inst.line, inst.col, true});
            return;
        }
    }

private:
    const Function& fn_;
    std::vector<Finding>& salida_;
    std::vector<Mapa> entradas_;
    std::vector<bool> visitado_;
};

}  // namespace

std::vector<Finding> verify(const Program& program) {
    std::vector<Finding> salida;
    for (const Function& fn : program.functions) {
        if (fn.blocks.empty()) continue;
        Verificador v(fn, salida);
        v.run();
    }
    return salida;
}

void write_findings(const std::vector<Finding>& findings, std::ostream& out) {
    out << findings.size() << " problema(s) de propiedad\n";
    for (const Finding& f : findings) {
        out << "  " << f.line << ":" << f.col << "  [" << f.function << "] "
            << f.what << (f.certain ? "" : "  (por algun camino)") << "\n";
    }
}

}  // namespace suriax::mir

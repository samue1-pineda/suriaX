#include "suriax/hir/resolve.hpp"

#include <algorithm>
#include <utility>

namespace suriax::hir {
namespace {

// El nombre ESCRITO de un callee: 'foo', 'stdp.println', 'Nodo.Literal'.
// Vacio si el callee no es un nombre (el resultado de otra llamada, p. ej.),
// que es justo el caso que no se puede resolver estaticamente.
std::string callee_name(const pb::Expr& callee) {
    switch (callee.node_case()) {
        case pb::Expr::kIdentifier:
            return callee.identifier().name();
        case pb::Expr::kMember: {
            const std::string base = callee_name(callee.member().obj());
            if (base.empty()) return std::string();
            return base + "." + callee.member().member();
        }
        default:
            return std::string();
    }
}

// ¿El dueno de un hook es un tipo PRIMITIVO? Entonces el hook es nativo del
// lenguaje: ninguna unidad puede declararlo y ninguna tabla lo contiene.
bool is_primitive(const std::string& owner) {
    return owner == "str" || owner == "int" || owner == "float" ||
           owner == "bool" || owner == "char";
}

// El nominal 'nucleo' de un tipo, desenvolviendo 'ptr'/'?': es la identidad
// que usan los hooks y los metodos ('__free__(T ptr)' aplica a 'T'). Espejo
// de 'scope_resolver._nominal_name'.
std::string owner_of(const pb::Module& module, std::uint32_t type_id) {
    const pb::Type* type = type_id < static_cast<std::uint32_t>(module.types_size())
                               ? &module.types(static_cast<int>(type_id))
                               : nullptr;
    // cota dura: desenvuelve punteros y nullables anidados sin poder colgarse
    // si el pool trae un ciclo.
    for (int depth = 0; type != nullptr && depth < 8; ++depth) {
        if (type->kind() != pb::POINTER && type->kind() != pb::NULLABLE) break;
        if (!type->has_inner()) return std::string();
        type = &type->inner();
    }
    return type != nullptr && type->kind() == pb::NOMINAL ? type->name()
                                                          : std::string();
}

// Recolector: recorre un cuerpo y anota lo que encuentra. Vive aqui y no en
// 'Program' porque su estado (la funcion en curso) muere con el recorrido.
// nombre local -> alias de la unidad que nombra. Es la resolucion que la
// Semantica YA hizo y que viaja en el HIR ('ImportDirective.binding'/'unit'),
// no una que el backend re-decida: dos consumidores que ligan nombres
// distintos ejecutan programas distintos. Espejo de
// 'interpreter._run_module_level' y de 'web/wir/lower.#collectBindings'.
using Bindings = std::unordered_map<std::string, std::string>;

Bindings bindings_of(const Unit& unit) {
    Bindings out;
    for (const pb::Decl& decl : unit.module().items()) {
        if (decl.node_case() == pb::Decl::kImportDirective) {
            const pb::ImportDirective& d = decl.import_directive();
            const std::string local =
                !d.binding().empty() ? d.binding()
                                     : (!d.alias().empty() ? d.alias() : d.lib());
            if (!local.empty()) {
                out[local] = d.unit().empty() ? d.lib() : d.unit();
            }
        } else if (decl.node_case() == pb::Decl::kFromDirective) {
            // '#from io #import stdp': lo ligado es el SUBMODULO 'IO.stdp',
            // no la unidad 'IO' — la misma regla que hace funcionar los
            // paquetes en el interprete.
            const pb::FromDirective& d = decl.from_directive();
            const std::string local = !d.alias().empty() ? d.alias() : d.name();
            const std::string from = d.unit().empty() ? d.lib() : d.unit();
            if (!local.empty()) out[local] = from + "." + d.name();
        }
    }
    return out;
}

class Walker {
public:
    Walker(const Image& image, Program& program, Function& fn,
           const Bindings& bindings)
        : image_(image), program_(program), fn_(fn), bindings_(bindings) {}

    void block(const pb::Block& b) {
        for (const pb::Stmt& s : b.statements()) stmt(s);
        for (const pb::Drop& d : b.drops()) drop(d);
    }

private:
    void drop(const pb::Drop& d) {
        std::string path;
        for (const std::string& part : d.path()) {
            if (!path.empty()) path += ".";
            path += part;
        }
        const pb::Symbol* bound = image_.hook(d.hook());
        std::string nombre = d.hook().owner_type() + "." +
                             pb::HookKind_Name(d.hook().kind());
        if (!d.hook().hook_name().empty()) {
            nombre += ":" + d.hook().hook_name();
        }
        fn_.drops.push_back(Drop{std::move(path), std::move(nombre),
                                 bound != nullptr});
    }

    void stmt(const pb::Stmt& s) {
        switch (s.node_case()) {
            case pb::Stmt::kBlock:
                block(s.block());
                break;
            case pb::Stmt::kVarDecl:
                if (s.var_decl().has_value()) expr(s.var_decl().value());
                break;
            case pb::Stmt::kIfStmt:
                if_stmt(s.if_stmt());
                break;
            case pb::Stmt::kWhileStmt:
                expr(s.while_stmt().condition());
                block(s.while_stmt().body());
                break;
            case pb::Stmt::kMatchStmt:
                expr(s.match_stmt().subject());
                for (const pb::CaseArm& arm : s.match_stmt().cases()) {
                    expr(arm.pattern());
                    stmt(arm.body());
                }
                break;
            case pb::Stmt::kReturnStmt:
                if (s.return_stmt().has_value()) expr(s.return_stmt().value());
                break;
            case pb::Stmt::kExprStmt:
                expr(s.expr_stmt().expr());
                break;
            case pb::Stmt::kMoveStmt:
                expr(s.move_stmt().target());
                break;
            case pb::Stmt::kFreeStmt:
                expr(s.free_stmt().target());
                break;
            case pb::Stmt::kThrowStmt:
                expr(s.throw_stmt().value());
                break;
            case pb::Stmt::kTryStmt:
                block(s.try_stmt().try_block());
                for (const pb::CatchClause& c : s.try_stmt().catches()) {
                    block(c.block());
                }
                break;
            default:
                // 'break'/'continue'/'import'/'type_decl' no llaman a nada y
                // no abren bloques: no hay nada que resolver en ellos. Un
                // caso nuevo del esquema cae aqui y lo reporta 'view.cpp',
                // que es el que tiene la guarda de exhaustividad.
                break;
        }
    }

    void if_stmt(const pb::IfStmt& node) {
        expr(node.condition());
        block(node.then_block());
        switch (node.else_branch_case()) {
            case pb::IfStmt::kElseBlock:
                block(node.else_block());
                break;
            case pb::IfStmt::kElseIf:
                if_stmt(node.else_if());
                break;
            default:
                break;
        }
    }

    void expr(const pb::Expr& e) {
        switch (e.node_case()) {
            case pb::Expr::kCall:
                call(e);
                break;
            case pb::Expr::kUnary:
                expr(e.unary().operand());
                break;
            case pb::Expr::kBinary:
                expr(e.binary().left());
                expr(e.binary().right());
                break;
            case pb::Expr::kAssignment:
                expr(e.assignment().target());
                expr(e.assignment().value());
                break;
            case pb::Expr::kIndex:
                expr(e.index().obj());
                expr(e.index().index());
                break;
            case pb::Expr::kMember:
                expr(e.member().obj());
                break;
            case pb::Expr::kAddrOf:
                expr(e.addr_of().operand());
                break;
            case pb::Expr::kMoveExpr:
                expr(e.move_expr().operand());
                break;
            case pb::Expr::kCastExpr:
                expr(e.cast_expr().value());
                break;
            case pb::Expr::kInterp:
                for (const pb::InterpolatedString::Part& part :
                         e.interp().parts()) {
                    if (part.has_expr()) expr(part.expr());
                }
                break;
            case pb::Expr::kStructLiteral:
                for (const pb::Expr& value : e.struct_literal().values()) {
                    expr(value);
                }
                break;
            default:
                // literales, identificadores y 'sizeof' no contienen
                // llamadas.
                break;
        }
    }

    // El corazon: decidir a QUE llama cada llamada.
    void call(const pb::Expr& e) {
        const pb::Call& node = e.call();
        expr(node.callee());
        for (const pb::Expr& arg : node.args()) expr(arg);

        Call site;
        site.line = e.ln();
        site.col = e.col();
        site.name = callee_name(node.callee());

        // 1) despacho por HOOK: el nodo ya trae la referencia resuelta por la
        //    Semantica ('print(x)' -> '__print__' del tipo de x).
        if (node.has_hook() && node.hook().kind() != pb::HOOK_UNSPECIFIED) {
            if (image_.hook(node.hook()) != nullptr) {
                site.target = CallTarget::Hook;
                record(std::move(site));
                return;
            }
            // Un hook cuyo dueno es un PRIMITIVO no lo declara nadie y no
            // puede estar en la tabla: 'len(s)' y 's[i]' sobre 'str' son
            // nativos del lenguaje (SEM006 prohibe colgarle hooks a un
            // primitivo). Los implementa el backend, asi que no son un
            // agujero — pero se marcan, porque el backend tiene que saber
            // que le tocan a el.
            if (is_primitive(node.hook().owner_type())) {
                site.target = CallTarget::Native;
                record(std::move(site));
                return;
            }
            site.detail = "el hook que nombra no esta en la tabla de la imagen";
            record(std::move(site));
            return;
        }

        // 2) METODO de un tipo ('v.push(x)'): el nodo trae el dueno en su
        //    'HookRef' (aunque el 'kind' venga vacio: un metodo de nombre
        //    llano no es del vocabulario fijo) y el nombre en el callee. Se
        //    resuelve por (dueno, nombre), que es la clave con la que el
        //    frontend los indexo — buscarlo solo por nombre confundiria el
        //    'get' de dos tipos distintos.
        if (node.callee().node_case() == pb::Expr::kMember &&
            !node.hook().owner_type().empty()) {
            const int found = method(node.hook().owner_type(),
                                     node.callee().member().member());
            if (found >= 0) {
                site.index = found;
                site.target = CallTarget::Method;
                record(std::move(site));
                return;
            }
        }

        if (site.name.empty()) {
            site.detail = "el destino no es un nombre";
            record(std::move(site));
            return;
        }

        // 2) una funcion de la imagen. Un nombre PUNTEADO nombra la unidad
        //    por su alias local ('fe.evaluar'), y ese alias solo lo conoce la
        //    unidad que hizo el import: sin traducirlo, 'fe.evaluar' acababa
        //    en la 'evaluar' del main, que es otra funcion con el mismo
        //    nombre. Un backend que confunde dos funciones no entiende el
        //    programa: genera llamadas al sitio equivocado.
        const std::size_t dot = site.name.rfind('.');
        int found = -1;
        if (dot != std::string::npos) {
            const auto binding = bindings_.find(site.name.substr(0, dot));
            if (binding != bindings_.end()) {
                found = lookup(binding->second, site.name.substr(dot + 1));
            }
        } else {
            // un nombre pelado se busca en ESTA unidad primero: una funcion
            // propia gana sobre lo que se importo, que es la regla del
            // frontend.
            found = lookup(fn_.unit, site.name);
            if (found < 0) found = lookup(std::string(), site.name);
        }
        if (found >= 0) {
            site.index = found;
            site.target =
                program_.functions[static_cast<std::size_t>(found)].prototype
                    ? CallTarget::Host
                    : CallTarget::Function;
            record(std::move(site));
            return;
        }

        // 3) constructor de una variante con payload ('Nodo.Literal(5)'): el
        //    nombre punteado nombra un enum y su item, no una funcion.
        if (is_variant(site.name)) {
            site.target = CallTarget::Variant;
            record(std::move(site));
            return;
        }

        site.detail = "ninguna unidad de la imagen declara '" + site.name + "'";
        record(std::move(site));
    }

    bool is_variant(const std::string& name) const {
        const std::size_t dot = name.rfind('.');
        if (dot == std::string::npos) return false;
        const std::string owner = name.substr(0, dot);
        const std::string item = name.substr(dot + 1);
        for (const std::unique_ptr<Unit>& unit : image_.units()) {
            if (unit->variant_arity(owner, item) >= 0) return true;
        }
        return image_.main().variant_arity(owner, item) >= 0;
    }

    int method(const std::string& owner, const std::string& name) const {
        const auto found = program_.methods.find(owner + "." + name);
        return found == program_.methods.end() ? -1
                                               : static_cast<int>(found->second);
    }

    int lookup(const std::string& unit, const std::string& name) const {
        const auto found = program_.index.find(Program::key(unit, name));
        return found == program_.index.end() ? -1
                                             : static_cast<int>(found->second);
    }

    void record(Call site) {
        if (site.target == CallTarget::Unresolved) {
            program_.unresolved.push_back(site);
        }
        fn_.calls.push_back(std::move(site));
    }

    const Image& image_;
    Program& program_;
    Function& fn_;
    const Bindings& bindings_;
};

// Los slots de una funcion: parametros primero, luego las variables que su
// cuerpo declara, en el orden en que aparecen.
void collect_slots(const pb::FunctionDecl& decl, std::vector<Slot>& out);

void collect_slots_block(const pb::Block& b, std::vector<Slot>& out) {
    for (const pb::Stmt& s : b.statements()) {
        switch (s.node_case()) {
            case pb::Stmt::kVarDecl:
                out.push_back(Slot{s.var_decl().name(), s.var_decl().type_id(),
                                   false});
                break;
            case pb::Stmt::kBlock:
                collect_slots_block(s.block(), out);
                break;
            case pb::Stmt::kIfStmt: {
                const pb::IfStmt* node = &s.if_stmt();
                while (node != nullptr) {
                    collect_slots_block(node->then_block(), out);
                    if (node->else_branch_case() == pb::IfStmt::kElseBlock) {
                        collect_slots_block(node->else_block(), out);
                    }
                    node = node->else_branch_case() == pb::IfStmt::kElseIf
                               ? &node->else_if()
                               : nullptr;
                }
                break;
            }
            case pb::Stmt::kWhileStmt:
                collect_slots_block(s.while_stmt().body(), out);
                break;
            case pb::Stmt::kTryStmt:
                collect_slots_block(s.try_stmt().try_block(), out);
                for (const pb::CatchClause& c : s.try_stmt().catches()) {
                    collect_slots_block(c.block(), out);
                }
                break;
            case pb::Stmt::kMatchStmt:
                for (const pb::CaseArm& arm : s.match_stmt().cases()) {
                    if (arm.body().node_case() == pb::Stmt::kBlock) {
                        collect_slots_block(arm.body().block(), out);
                    }
                }
                break;
            default:
                break;
        }
    }
}

void collect_slots(const pb::FunctionDecl& decl, std::vector<Slot>& out) {
    for (const pb::Parameter& p : decl.params()) {
        out.push_back(Slot{p.name(), p.type_id(), true});
    }
    if (decl.has_body()) collect_slots_block(decl.body(), out);
}

// Las funciones de una unidad, en el orden en que las declara.
void declare(const Unit& unit, bool is_main, Program& program) {
    for (const pb::Decl& decl : unit.module().items()) {
        if (decl.node_case() != pb::Decl::kFunction) continue;
        const pb::FunctionDecl& fn = decl.function();
        Function entry;
        entry.unit = is_main ? std::string() : unit.alias();
        entry.name = fn.name();
        entry.decl = &fn;
        entry.line = decl.ln();
        entry.col = decl.col();
        entry.result_type = fn.return_type_id();
        entry.prototype = !fn.has_body();
        collect_slots(fn, entry.slots);
        program.index.emplace(Program::key(entry.unit, entry.name),
                              program.functions.size());
        // un 'dunder' de nombre llano es un METODO: su dueno es el nominal de
        // su receptor, igual que lo decide el frontend.
        if (!fn.dunder().empty() && fn.params_size() > 0) {
            const std::string owner =
                owner_of(unit.module(), fn.params(0).type_id());
            if (!owner.empty()) {
                program.methods.emplace(owner + "." + fn.dunder(),
                                        program.functions.size());
            }
        }
        if (is_main && fn.name() == "main") {
            program.entry = static_cast<int>(program.functions.size());
        }
        program.functions.push_back(std::move(entry));
    }
}

}  // namespace

const char* to_string(CallTarget target) {
    switch (target) {
        case CallTarget::Function: return "fn";
        case CallTarget::Host: return "host";
        case CallTarget::Hook: return "hook";
        case CallTarget::Method: return "metodo";
        case CallTarget::Native: return "nativo";
        case CallTarget::Variant: return "variante";
        case CallTarget::Unresolved: return "SIN RESOLVER";
    }
    return "?";
}

std::string Program::key(const std::string& unit, const std::string& name) {
    return unit.empty() ? name : unit + "::" + name;
}

Program resolve(const Image& image) {
    Program program;

    // 1) TODAS las funciones antes de mirar ningun cuerpo: una funcion puede
    //    llamar a otra declarada mas abajo, o de otra unidad.
    declare(image.main(), true, program);
    for (const std::unique_ptr<Unit>& unit : image.units()) {
        declare(*unit, false, program);
    }

    // 2) como liga los nombres cada unidad, ANTES de mirar ningun cuerpo.
    std::unordered_map<std::string, Bindings> bindings;
    bindings.emplace(std::string(), bindings_of(image.main()));
    for (const std::unique_ptr<Unit>& unit : image.units()) {
        bindings.emplace(unit->alias(), bindings_of(*unit));
    }

    // 3) los cuerpos, ya con el indice y las ligaduras completos.
    const Bindings vacio;
    for (std::size_t i = 0; i < program.functions.size(); ++i) {
        Function& fn = program.functions[i];
        if (fn.decl == nullptr || !fn.decl->has_body()) continue;
        const auto found = bindings.find(fn.unit);
        Walker walker(image, program, fn,
                      found == bindings.end() ? vacio : found->second);
        walker.block(fn.decl->body());
    }
    return program;
}

void write_resolved(const Program& program, std::ostream& out) {
    out << "programa resuelto — " << program.functions.size()
        << " funciones, entrada: "
        << (program.entry < 0
                ? std::string("(ninguna)")
                : program.functions[static_cast<std::size_t>(program.entry)].name)
        << "\n";

    for (const Function& fn : program.functions) {
        out << "\nfn " << Program::key(fn.unit, fn.name);
        if (fn.prototype) out << "   (prototipo: lo aporta el host)";
        out << "\n";
        for (std::size_t i = 0; i < fn.slots.size(); ++i) {
            const Slot& slot = fn.slots[i];
            out << "  slot " << i << "  " << (slot.parameter ? "param" : "var  ")
                << " " << slot.name << "  tipo#" << slot.type_id << "\n";
        }
        for (const Call& site : fn.calls) {
            out << "  llama " << site.name << " -> " << to_string(site.target);
            if (site.index >= 0) {
                out << " #" << site.index;
            }
            if (!site.detail.empty()) out << "  (" << site.detail << ")";
            out << "   @" << site.line << ":" << site.col << "\n";
        }
        for (const Drop& drop : fn.drops) {
            out << "  destruye " << drop.path << " con " << drop.hook
                << (drop.bound ? "" : "  (NO LIGADO)") << "\n";
        }
    }

    out << "\n" << program.unresolved.size() << " llamada(s) sin resolver\n";
    for (const Call& site : program.unresolved) {
        out << "  " << site.line << ":" << site.col << "  " << site.name
            << "  " << site.detail << "\n";
    }
}

}  // namespace suriax::hir

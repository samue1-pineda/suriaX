#include "suriax/hir/view.hpp"

#include <algorithm>
#include <array>
#include <charconv>
#include <cctype>
#include <cmath>
#include <cstdio>
#include <sstream>
#include <string_view>

namespace suriax::hir {
namespace {

// columna donde se alinean las posiciones '@ln:col' (espejo de _POS_COL).
constexpr std::size_t kPosCol = 66;

// Longitud en PUNTOS DE CODIGO, no en bytes. La alineacion la calcula Python
// sobre 'str', asi que un identificador o un literal con acentos —que el
// lenguaje admite— desalinearia la columna si aqui se contaran bytes.
std::size_t codepoints(std::string_view text) {
    std::size_t count = 0;
    for (unsigned char byte : text) {
        if ((byte & 0xC0) != 0x80) ++count;  // no es byte de continuacion
    }
    return count;
}

// 'repr(float)' de Python, que es lo que imprime la vista de referencia.
//
// No es 'el double como salga': Python usa la representacion mas corta que
// vuelve al mismo valor, con punto decimal siempre presente en notacion fija
// y exponente de al menos dos digitos. Reproducirlo es parte de la identidad
// byte a byte de la vista; aproximarlo la rompe en el primer literal float.
std::string python_repr_double(double value) {
    if (std::isnan(value)) return "nan";
    if (std::isinf(value)) return value < 0 ? "-inf" : "inf";

    const bool negative = std::signbit(value);
    const double magnitude = negative ? -value : value;

    // digitos significativos mas cortos que hacen round-trip, en notacion
    // cientifica ('to_chars' garantiza esa propiedad).
    std::array<char, 64> buffer{};
    auto [end, ec] = std::to_chars(buffer.data(), buffer.data() + buffer.size(),
                                   magnitude, std::chars_format::scientific);
    std::string_view scientific(buffer.data(),
                                static_cast<std::size_t>(end - buffer.data()));

    const std::size_t exponent_pos = scientific.find('e');
    std::string digits(scientific.substr(0, exponent_pos));
    digits.erase(std::remove(digits.begin(), digits.end(), '.'), digits.end());
    int exponent = 0;
    std::from_chars(scientific.data() + exponent_pos + 1,
                    scientific.data() + scientific.size(), exponent);

    // 'decpt': el punto decimal va tras 'decpt' digitos (valor = 0.D * 10^decpt).
    const int decpt = exponent + 1;
    const int size = static_cast<int>(digits.size());

    std::string out;
    if (decpt <= -4 || decpt > 16) {  // misma frontera que CPython
        out += digits[0];
        if (size > 1) {
            out += '.';
            out += digits.substr(1);
        }
        char tail[8];
        std::snprintf(tail, sizeof(tail), "e%+.2d", decpt - 1);
        out += tail;
    } else if (decpt <= 0) {
        out += "0.";
        out.append(static_cast<std::size_t>(-decpt), '0');
        out += digits;
    } else if (decpt >= size) {
        out += digits;
        out.append(static_cast<std::size_t>(decpt - size), '0');
        out += ".0";  // Py_DTSF_ADD_DOT_0: un float siempre se ve como float
    } else {
        out += digits.substr(0, static_cast<std::size_t>(decpt));
        out += '.';
        out += digits.substr(static_cast<std::size_t>(decpt));
    }
    return negative ? "-" + out : out;
}

std::string lowercase(std::string text) {
    std::transform(text.begin(), text.end(), text.begin(),
                   [](unsigned char c) { return static_cast<char>(std::tolower(c)); });
    return text;
}

std::string hook_kind_name(pb::HookKind kind) {
    return "__" + lowercase(pb::HookKind_Name(kind)) + "__";
}

// Recorrido del modulo: una linea por sentencia, expresiones en linea con su
// tipo resuelto y la posicion del fuente al margen.
class Printer {
public:
    Printer(const pb::Module& module, std::ostream& out,
            std::vector<Unknown>& unknown)
        : module_(module), out_(out), unknown_(unknown) {
        // el pool se resuelve UNA vez a texto: cada nodo lo consulta por
        // indice y no vuelve a formatear el mismo tipo. Es el mismo motivo
        // por el que el pool existe en el artefacto.
        types_.reserve(static_cast<std::size_t>(module.types_size()));
        for (const pb::Type& type : module.types()) types_.push_back(format_type(type));
    }

    void run();

private:
    // -- utilidades ------------------------------------------------------ //
    std::string type_of(std::uint32_t type_id) const {
        if (type_id > 0 && type_id < types_.size()) return types_[type_id];
        return "";
    }

    void line(const std::string& text, std::uint32_t ln = 0, std::uint32_t col = 0,
              int indent = 0) {
        std::string body(static_cast<std::size_t>(indent) * 2, ' ');
        body += text;
        if (ln != 0) {
            const std::size_t width = codepoints(body);
            const std::size_t pad = width >= kPosCol ? 1 : kPosCol - width;
            body.append(pad, ' ');
            body += "@" + std::to_string(ln) + ":" + std::to_string(col);
        }
        out_ << body << "\n";
    }

    void unknown(const char* what, const std::string& node, std::uint32_t ln,
                 std::uint32_t col) {
        unknown_.push_back(Unknown{what, node.empty() ? "vacio" : node, ln, col});
    }

    // -- expresiones ----------------------------------------------------- //
    std::string expr(const pb::Expr& e);
    std::string expr_text(const pb::Expr& e);
    std::string literal(const pb::Literal& lit);
    std::string hook(const pb::HookRef& ref);
    std::string temp_drop(const pb::HookRef& ref);

    // -- sentencias y declaraciones -------------------------------------- //
    void block(const pb::Block& b, int indent);
    void stmt(const pb::Stmt& s, int indent);
    void if_stmt(const pb::IfStmt& node, int indent, std::uint32_t ln,
                 std::uint32_t col);
    void if_tail(const pb::IfStmt& node, int indent);
    void decl(const pb::Decl& d);
    void function(const pb::FunctionDecl& fn, std::uint32_t ln, std::uint32_t col);

    const pb::Module& module_;
    std::ostream& out_;
    std::vector<Unknown>& unknown_;
    std::vector<std::string> types_;
};

std::string Printer::expr(const pb::Expr& e) {
    const std::string text = expr_text(e);
    const std::string type = type_of(e.type_id());
    // El sufijo ':tipo' solo aparece donde APORTA: en un literal el tipo es
    // evidente y ensucia; en una llamada o una variable es la informacion que
    // uno vino a buscar.
    const auto kind = e.node_case();
    if (!type.empty() && kind != pb::Expr::kLiteral &&
        kind != pb::Expr::kStructLiteral && kind != pb::Expr::kIdentifier) {
        return text + ":" + type;
    }
    return text;
}

std::string Printer::expr_text(const pb::Expr& e) {
    switch (e.node_case()) {
        case pb::Expr::kLiteral:
            return literal(e.literal());
        case pb::Expr::kIdentifier: {
            const std::string type = type_of(e.type_id());
            return type.empty() ? e.identifier().name()
                                : e.identifier().name() + ":" + type;
        }
        case pb::Expr::kBinary:
            return "(" + expr(e.binary().left()) + " " + e.binary().op() + " " +
                   expr(e.binary().right()) + ")";
        case pb::Expr::kUnary:
            return "(" + e.unary().op() + " " + expr(e.unary().operand()) + ")";
        case pb::Expr::kAssignment:
            return expr(e.assignment().target()) + " = " +
                   expr(e.assignment().value());
        case pb::Expr::kCall: {
            std::string args;
            for (int i = 0; i < e.call().args_size(); ++i) {
                if (i != 0) args += ", ";
                args += expr(e.call().args(i));
            }
            return expr(e.call().callee()) + "(" + args + ")" +
                   hook(e.call().hook()) + temp_drop(e.call().temp_drop());
        }
        case pb::Expr::kIndex:
            return expr(e.index().obj()) + "[" + expr(e.index().index()) + "]";
        case pb::Expr::kMember:
            return expr(e.member().obj()) + "." + e.member().member();
        case pb::Expr::kCastExpr:
            return "cast<" + format_type(e.cast_expr().type()) + ">(" +
                   expr(e.cast_expr().value()) + ")" + hook(e.cast_expr().hook());
        case pb::Expr::kSizeof:
            return "sizeof(" + format_type(e.sizeof_().type()) + ")" +
                   hook(e.sizeof_().hook());
        case pb::Expr::kMoveExpr:
            return "move " + expr(e.move_expr().operand());
        case pb::Expr::kAddrOf:
            return (e.addr_of().mut() ? "&mut " : "&") + expr(e.addr_of().operand());
        case pb::Expr::kStructLiteral: {
            std::string fields;
            for (int i = 0; i < e.struct_literal().values_size(); ++i) {
                if (i != 0) fields += ", ";
                fields += e.struct_literal().field_names(i) + ": " +
                          expr(e.struct_literal().values(i));
            }
            return e.struct_literal().type_name() + "{" + fields + "}" +
                   temp_drop(e.struct_literal().temp_drop());
        }
        case pb::Expr::kInterp: {
            std::string parts;
            for (const pb::InterpolatedString::Part& part : e.interp().parts()) {
                if (part.part_case() == pb::InterpolatedString::Part::kText) {
                    parts += part.text();
                } else {
                    parts += "{" + expr(part.expr()) + "}";
                }
            }
            return "f\"" + parts + "\"";
        }
        case pb::Expr::NODE_NOT_SET:
            unknown("Expr", "", e.ln(), e.col());
            return "<vacio>";
    }
    // Un caso del 'oneof' que este lector no conoce: se ANOTA con su posicion
    // en vez de saltarse, que es lo que impide que una construccion nueva
    // cruce la frontera en silencio.
    unknown("Expr", std::to_string(static_cast<int>(e.node_case())), e.ln(), e.col());
    return "<desconocido>";
}

std::string Printer::literal(const pb::Literal& lit) {
    switch (lit.value_case()) {
        case pb::Literal::kStrValue:
            return lit.kind() == "str" ? "\"" + lit.str_value() + "\""
                                       : "'" + lit.str_value() + "'";
        case pb::Literal::kIntValue:
            return std::to_string(lit.int_value());
        case pb::Literal::kFloatValue:
            return python_repr_double(lit.float_value());
        case pb::Literal::kBoolValue:
            return lit.bool_value() ? "true" : "false";
        case pb::Literal::VALUE_NOT_SET:
            break;  // 'null': ningun campo del oneof presente
    }
    return "null";
}

std::string Printer::hook(const pb::HookRef& ref) {
    // La anotacion del hook enlazado: la decision que tomo la Semantica y que
    // el consumidor ejecuta sin volver a decidirla.
    if (ref.owner_type().empty()) return "";
    const std::string name =
        ref.hook_name().empty() ? hook_kind_name(ref.kind()) : ref.hook_name();
    return "  ⟨hook " + name + " de " + ref.owner_type() + "⟩";
}

std::string Printer::temp_drop(const pb::HookRef& ref) {
    // El '__free__' de un valor que POSEE recursos y que nadie recibe: el
    // frontend lo ata a la expresion para que muera al terminar la sentencia.
    // Se marca distinto del hook que dispara la sintaxis porque responde a
    // otra pregunta.
    if (ref.owner_type().empty()) return "";
    const std::string name =
        ref.hook_name().empty() ? hook_kind_name(ref.kind()) : ref.hook_name();
    return "  ⟨temporal " + name + " de " + ref.owner_type() + "⟩";
}

void Printer::block(const pb::Block& b, int indent) {
    for (const pb::Stmt& statement : b.statements()) stmt(statement, indent);
    // Los drops los INSERTA el compilador al cerrar el bloque: nadie los
    // escribe. Verlos es la unica forma de contestar "que decidio el frontend
    // que hay que destruir aqui" sin leer el protobuf crudo.
    for (const pb::Drop& d : b.drops()) {
        std::string path;
        for (int i = 0; i < d.path_size(); ++i) {
            if (i != 0) path += ".";
            path += d.path(i);
        }
        line("drop " + path + hook(d.hook()), 0, 0, indent);
    }
}

void Printer::stmt(const pb::Stmt& s, int indent) {
    const std::uint32_t ln = s.ln();
    const std::uint32_t col = s.col();

    switch (s.node_case()) {
        case pb::Stmt::kVarDecl: {
            const pb::VarDecl& v = s.var_decl();
            const std::string type = type_of(v.type_id());
            std::string head = (v.qualifier().empty() ? "var" : v.qualifier());
            head += " ";
            if (!type.empty()) head += type + " ";
            head += v.name();
            if (v.has_value()) {
                line(head + " = " + expr(v.value()), ln, col, indent);
            } else {
                line(head, ln, col, indent);
            }
            break;
        }
        case pb::Stmt::kExprStmt:
            line(expr(s.expr_stmt().expr()), ln, col, indent);
            break;
        case pb::Stmt::kReturnStmt: {
            const std::string value = s.return_stmt().has_value()
                                          ? " " + expr(s.return_stmt().value())
                                          : std::string();
            // 'transfers': la propiedad pasa al llamador y el ambito que lo
            // tenia NO debe destruirlo. Sin verlo, los drops de arriba
            // parecen incompletos.
            const std::string mark =
                s.return_stmt().transfers() ? "  ⟨transfiere⟩" : "";
            line("return" + value + mark, ln, col, indent);
            break;
        }
        case pb::Stmt::kIfStmt:
            if_stmt(s.if_stmt(), indent, ln, col);
            break;
        case pb::Stmt::kWhileStmt:
            line("while " + expr(s.while_stmt().condition()), ln, col, indent);
            block(s.while_stmt().body(), indent + 1);
            break;
        case pb::Stmt::kMatchStmt:
            line("match " + expr(s.match_stmt().subject()), ln, col, indent);
            for (const pb::CaseArm& arm : s.match_stmt().cases()) {
                line("case " + expr(arm.pattern()), 0, 0, indent + 1);
                stmt(arm.body(), indent + 2);
            }
            break;
        case pb::Stmt::kBlock:
            line("{", ln, col, indent);
            block(s.block(), indent + 1);
            line("}", 0, 0, indent);
            break;
        case pb::Stmt::kBreakStmt:
            line("break", ln, col, indent);
            break;
        case pb::Stmt::kContinueStmt:
            line("continue", ln, col, indent);
            break;
        case pb::Stmt::kMoveStmt:
            line("move " + expr(s.move_stmt().target()), ln, col, indent);
            break;
        case pb::Stmt::kFreeStmt:
            line("free " + expr(s.free_stmt().target()) + hook(s.free_stmt().hook()),
                 ln, col, indent);
            break;
        case pb::Stmt::kThrowStmt:
            line("throw " + expr(s.throw_stmt().value()), ln, col, indent);
            break;
        case pb::Stmt::kTryStmt: {
            line("try", ln, col, indent);
            block(s.try_stmt().try_block(), indent + 1);
            // las ramas se prueban EN ORDEN y el filtro es opcional: sin
            // 'type' la rama atrapa cualquier valor. El tipo se imprime
            // porque es lo que decide cual gana.
            for (const pb::CatchClause& arm : s.try_stmt().catches()) {
                const std::string filter =
                    arm.has_type() ? format_type(arm.type()) + " " : std::string();
                line("catch (" + filter + arm.name() + ")", 0, 0, indent);
                block(arm.block(), indent + 1);
            }
            break;
        }
        case pb::Stmt::kTypeDecl: {
            const pb::TypeDecl& t = s.type_decl();
            const std::string value =
                t.has_value() ? " = " + expr(t.value()) : std::string();
            line((t.qualifier().empty() ? "const" : t.qualifier()) + " type " +
                     t.name() + value,
                 ln, col, indent);
            break;
        }
        case pb::Stmt::kImportBinding: {
            const pb::ImportBinding& b = s.import_binding();
            const std::string member =
                b.member().empty() ? std::string() : "." + b.member();
            line("bind " + b.name() + " <- " + b.lib() + member, ln, col, indent);
            break;
        }
        case pb::Stmt::NODE_NOT_SET:
            // Sin caso puesto: el productor escribio un tag que este lector no
            // conoce y protobuf lo dejo en los campos desconocidos. Se ANOTA
            // con su posicion en vez de saltarse. El caso contrario —un caso
            // NUEVO del oneof— no llega hasta aqui: sin 'default', anadirlo al
            // esquema rompe la compilacion de este switch, que es la
            // exhaustividad verificable por el compilador que promete
            // PROTOBUF_BRIDGE.md.
            unknown("Stmt", "", ln, col);
            line("<vacio>", ln, col, indent);
            break;
    }
}

void Printer::if_stmt(const pb::IfStmt& node, int indent, std::uint32_t ln,
                      std::uint32_t col) {
    line("if " + expr(node.condition()), ln, col, indent);
    block(node.then_block(), indent + 1);
    if_tail(node, indent);
}

void Printer::if_tail(const pb::IfStmt& node, int indent) {
    switch (node.else_branch_case()) {
        case pb::IfStmt::kElseBlock:
            line("else", 0, 0, indent);
            block(node.else_block(), indent + 1);
            break;
        case pb::IfStmt::kElseIf:
            line("else if " + expr(node.else_if().condition()), 0, 0, indent);
            block(node.else_if().then_block(), indent + 1);
            if_tail(node.else_if(), indent);
            break;
        case pb::IfStmt::ELSE_BRANCH_NOT_SET:
            break;  // un 'if' sin else es lo normal, no una ausencia que anotar
    }
}

void Printer::decl(const pb::Decl& d) {
    switch (d.node_case()) {
        case pb::Decl::kFunction:
            function(d.function(), d.ln(), d.col());
            break;
        case pb::Decl::kStructDecl: {
            std::string fields;
            for (int i = 0; i < d.struct_decl().fields_size(); ++i) {
                if (i != 0) fields += ", ";
                const pb::Field& f = d.struct_decl().fields(i);
                fields += type_of(f.type_id()) + " " + f.name();
            }
            line("struct " + d.struct_decl().name() + " { " + fields + " }", d.ln(),
                 d.col());
            out_ << "\n";
            break;
        }
        case pb::Decl::kEnumDecl: {
            std::string items;
            for (int i = 0; i < d.enum_decl().items_size(); ++i) {
                if (i != 0) items += ", ";
                const pb::EnumItem& item = d.enum_decl().items(i);
                items += item.name();
                // Una variante con PAYLOAD no es un entero sino un
                // constructor que se invoca. Sin sus tipos, las dos formas
                // del enum se leen igual — que es justo lo que el esquema
                // evita.
                if (item.payload_type_ids_size() > 0) {
                    items += "(";
                    for (int j = 0; j < item.payload_type_ids_size(); ++j) {
                        if (j != 0) items += ", ";
                        items += type_of(item.payload_type_ids(j));
                    }
                    items += ")";
                } else if (item.has_value()) {
                    items += " = " + expr(item.value());
                }
            }
            line("enum " + d.enum_decl().name() + " { " + items + " }", d.ln(),
                 d.col());
            out_ << "\n";
            break;
        }
        case pb::Decl::kImportDirective: {
            const pb::ImportDirective& i = d.import_directive();
            const std::string alias =
                i.alias().empty() ? std::string() : " as " + i.alias();
            line("import " + i.lib() + alias + "   -> unidad '" + i.unit() +
                     "', liga '" + i.binding() + "'",
                 d.ln(), d.col());
            break;
        }
        case pb::Decl::kFromDirective: {
            const pb::FromDirective& f = d.from_directive();
            const std::string alias =
                f.alias().empty() ? std::string() : " as " + f.alias();
            line("from " + f.lib() + " import " + f.name() + alias +
                     "   -> unidad '" + f.unit() + "'",
                 d.ln(), d.col());
            break;
        }
        case pb::Decl::kExportDirective: {
            const pb::ExportDirective& e = d.export_directive();
            line("export " + std::string(e.package() ? "package " : "") + "as " +
                     e.alias(),
                 d.ln(), d.col());
            break;
        }
        case pb::Decl::kExternBlock: {
            const std::string& raw = d.extern_block().raw();
            const auto lines =
                std::count(raw.begin(), raw.end(), '\n') + 1;
            line("extern " + d.extern_block().target() + " { … " +
                     std::to_string(lines) + " líneas }",
                 d.ln(), d.col());
            break;
        }
        case pb::Decl::kTestDecl:
            line("test \"" + d.test_decl().name() + "\"", d.ln(), d.col());
            block(d.test_decl().body(), 1);
            out_ << "\n";
            break;
        case pb::Decl::kStatement:
            stmt(d.statement(), 0);
            break;
        case pb::Decl::NODE_NOT_SET:
            unknown("Decl", "", d.ln(), d.col());
            line("<vacio>", d.ln(), d.col());
            break;
    }
}

void Printer::function(const pb::FunctionDecl& fn, std::uint32_t ln,
                       std::uint32_t col) {
    std::string params;
    for (int i = 0; i < fn.params_size(); ++i) {
        if (i != 0) params += ", ";
        const pb::Parameter& p = fn.params(i);
        params += type_of(p.type_id()) + " " + p.name();
    }
    std::string ret = type_of(fn.return_type_id());
    if (ret.empty()) ret = "void";

    std::string mark;
    if (!fn.decorator().empty()) mark += "@" + fn.decorator() + " ";
    if (!fn.dunder().empty()) mark += "dunder ";

    if (!fn.has_body()) {
        line(mark + "fn " + fn.name() + "(" + params + ") -> " + ret +
                 ";   (prototipo: lo aporta el host)",
             ln, col);
        out_ << "\n";
        return;
    }
    line(mark + "fn " + fn.name() + "(" + params + ") -> " + ret, ln, col);
    block(fn.body(), 1);
    out_ << "\n";
}

void Printer::run() {
    const pb::SymbolTable& symbols = module_.symbols();
    const int symbol_count = symbols.types_size() + symbols.values_size();

    out_ << "unit "
         << (module_.source_file().empty() ? "<sin nombre>" : module_.source_file())
         << "   schema " << module_.schema_version() << " · "
         << module_.items_size() << " items · " << symbol_count
         << " símbolos · " << std::max(module_.types_size() - 1, 0)
         << " tipos";
    if (module_.libraries_size() > 0) {
        out_ << " · " << module_.libraries_size() << " librerías";
    }
    out_ << "\n\n";

    // el POOL de tipos, que es lo que hace legible todo lo de abajo
    if (module_.types_size() > 1) {
        out_ << "types\n";
        for (std::size_t i = 1; i < types_.size(); ++i) {
            std::string index = "#" + std::to_string(i);
            if (index.size() < 4) index.append(4 - index.size(), ' ');
            out_ << "  " << index << " " << types_[i] << "\n";
        }
        out_ << "\n";
    }

    if (module_.libraries_size() > 0) {
        out_ << "libs\n";
        for (const pb::LibraryRef& lib : module_.libraries()) {
            out_ << "  " << lib.alias() << " -> " << lib.phir() << "\n";
        }
        out_ << "\n";
    }

    if (symbols.hooks_size() > 0 || symbols.casts_size() > 0) {
        out_ << "hooks\n";
        for (const pb::HookEntry& h : symbols.hooks()) {
            const std::string name =
                h.hook_name().empty() ? hook_kind_name(h.kind()) : h.hook_name();
            out_ << "  " << name << " de " << h.owner_type();
            if (!h.extension().empty()) {
                out_ << "   (extensión '" << h.extension() << "')";
            }
            out_ << "\n";
        }
        for (const pb::Symbol& c : symbols.casts()) {
            const std::string from = c.param_types_size() > 0
                                         ? format_type(c.param_types(0))
                                         : "<?>";
            out_ << "  __cast__ " << from << " -> " << format_type(c.type()) << "\n";
        }
        out_ << "\n";
    }

    for (const pb::Decl& d : module_.items()) decl(d);
}

}  // namespace

std::string format_type(const pb::Type& type) {
    switch (type.kind()) {
        case pb::POINTER:
            return format_type(type.inner()) + (type.mut() ? " ptr mutable" : " ptr");
        case pb::NULLABLE:
            return format_type(type.inner()) + "?";
        case pb::ERROR:
            // 'error' sola (sin inner) es un tipo legitimo: solo error.
            return type.has_inner() ? "error " + format_type(type.inner()) : "error";
        case pb::NOMINAL: {
            if (type.args_size() == 0) return type.name();
            std::string args;
            for (int i = 0; i < type.args_size(); ++i) {
                if (i != 0) args += ", ";
                args += format_type(type.args(i));
            }
            return type.name() + "<" + args + ">";
        }
        case pb::TYPE_UNSPECIFIED:
            return "<?>";
        default:
            return lowercase(pb::TypeKind_Name(type.kind()));
    }
}

std::string type_key(const pb::Type& type) {
    // Espejo de 'runtime/interpreter/hook/dispatch.type_key': la identidad
    // ESTRUCTURAL del tipo, no su notacion. Se indexa por esto y no por
    // 'format_type' porque la notacion es para leer — dos tipos distintos con
    // la misma notacion (un nominal que se llamara como un primitivo)
    // colisionarian en el indice, y un indice no puede depender de que eso no
    // pase nunca.
    std::string key = std::to_string(static_cast<int>(type.kind())) + ":" +
                      type.name() + ":" + (type.mut() ? "1" : "0") + ":(";
    if (type.has_inner()) key += type_key(type.inner());
    key += "):[";
    for (int i = 0; i < type.args_size(); ++i) {
        if (i != 0) key += ",";
        key += type_key(type.args(i));
    }
    key += "]";
    return key;
}

void write_pretty(const pb::Module& module, std::ostream& out,
                  std::vector<Unknown>& unknown) {
    Printer printer(module, out, unknown);
    printer.run();
}

std::vector<ExternBlock> collect_extern(const Image& image) {
    std::vector<ExternBlock> blocks;
    auto recoger = [&blocks](const Unit& unit) {
        const pb::Module& module = unit.module();
        for (const pb::Decl& decl : module.items()) {
            if (decl.node_case() != pb::Decl::kExternBlock) continue;
            blocks.push_back(ExternBlock{
                unit.alias(), module.source_file(), decl.extern_block().target(),
                decl.extern_block().raw(), decl.ln(), decl.col()});
        }
    };
    // librerias primero y el main al final: el mismo orden en el que el
    // interprete inicializa las unidades, para que dos backends que compilen
    // esto no discrepen sobre que definicion vio antes el compilador de C++.
    for (const auto& unit : image.units()) recoger(*unit);
    recoger(image.main());
    return blocks;
}

bool write_extern_cpp(const std::vector<ExternBlock>& blocks, std::ostream& out,
                      std::string& error) {
    for (const ExternBlock& block : blocks) {
        if (block.target != "cpp") {
            error = "el bloque '#extern " + block.target + "' de la unidad '" +
                    (block.unit.empty() ? "<principal>" : block.unit) +
                    "' declara un target que este backend no conoce (solo "
                    "'cpp'), en " + std::to_string(block.line) + ":" +
                    std::to_string(block.col);
            return false;
        }
    }

    out << "// Generado por suriaX: los bloques '#extern cpp' del programa.\n"
           "// No se edita a mano — se regenera con 'suriax-hir --emit-cpp'.\n"
           "//\n"
           "// Los '#line' hacen que los errores del compilador de C++ apunten\n"
           "// al .srcx del usuario y no a este archivo.\n";
    for (const ExternBlock& block : blocks) {
        out << "\n// unidad '" << (block.unit.empty() ? "<principal>" : block.unit)
            << "'\n";
        // '#line N' numera la linea SIGUIENTE como N, y lo siguiente a la
        // directiva es lo que queda de la linea del '#extern' (el lexer captura
        // el salto que va tras la llave). Por eso la linea del propio bloque,
        // sin sumar: asi el contenido cae en el numero que tiene en el .srcx,
        // tanto si el bloque ocupa varias lineas como si cabe en una.
        out << "#line " << block.line << " \"" << block.source << "\"\n";
        out << block.raw;
        if (!block.raw.empty() && block.raw.back() != '\n') out << "\n";
    }
    return true;
}

void write_summary(const pb::Module& module, std::ostream& out) {
    const pb::SymbolTable& symbols = module.symbols();

    out << "HIR schema v" << module.schema_version() << " — "
        << module.source_file() << "\n";
    out << "  items de nivel superior: " << module.items_size() << "\n";

    if (symbols.types_size() > 0) {
        std::vector<std::string> names;
        names.reserve(static_cast<std::size_t>(symbols.types_size()));
        for (const auto& [name, _] : symbols.types()) names.push_back(name);
        std::sort(names.begin(), names.end());

        out << "  tipos (" << symbols.types_size() << "):\n";
        for (const std::string& name : names) {
            const pb::Symbol& symbol = symbols.types().at(name);
            std::string kind = lowercase(pb::SymbolKind_Name(symbol.kind()));
            if (kind.size() < 8) kind.append(8 - kind.size(), ' ');

            std::string detail;
            if (!symbol.members().empty()) {
                std::vector<std::string> members;
                members.reserve(static_cast<std::size_t>(symbol.members().size()));
                for (const auto& [member, _] : symbol.members()) {
                    members.push_back(member);
                }
                std::sort(members.begin(), members.end());
                detail = " { ";
                for (std::size_t i = 0; i < members.size(); ++i) {
                    if (i != 0) detail += ", ";
                    detail += format_type(symbol.members().at(members[i]).type()) +
                              " " + members[i];
                }
                detail += " }";
            }
            out << "    " << kind << " " << name << detail << "\n";
        }
    }

    std::vector<std::string> functions;
    std::vector<std::string> others;
    {
        std::vector<std::string> names;
        names.reserve(static_cast<std::size_t>(symbols.values_size()));
        for (const auto& [name, _] : symbols.values()) names.push_back(name);
        std::sort(names.begin(), names.end());
        for (const std::string& name : names) {
            if (symbols.values().at(name).kind() == pb::FUNCTION) {
                functions.push_back(name);
            } else {
                others.push_back(name);
            }
        }
    }

    if (!functions.empty()) {
        out << "  funciones (" << functions.size() << "):\n";
        for (const std::string& name : functions) {
            const pb::Symbol& symbol = symbols.values().at(name);
            std::string params;
            for (int i = 0; i < symbol.param_types_size(); ++i) {
                if (i != 0) params += ", ";
                params += format_type(symbol.param_types(i));
            }
            out << "    fn " << name << "(" << params << ") -> "
                << format_type(symbol.type()) << "\n";
        }
    }
    if (!others.empty()) {
        out << "  otros valores (" << others.size() << "): ";
        for (std::size_t i = 0; i < others.size(); ++i) {
            if (i != 0) out << ", ";
            out << others[i];
        }
        out << "\n";
    }

    if (symbols.hooks_size() > 0) {
        out << "  hooks (" << symbols.hooks_size() << "):\n";
        for (const pb::HookEntry& h : symbols.hooks()) {
            out << "    " << hook_kind_name(h.kind()) << " de " << h.owner_type()
                << "\n";
        }
    }
}

}  // namespace suriax::hir

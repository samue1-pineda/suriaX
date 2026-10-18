// Normalizacion del ESQUEMA 1 del HIR (tipos inline, sin pool) a la forma de
// hoy (pool 'Module.types' + indices 'type_id'). Espejo de
// 'V0/src/HIR/schema_v1.normalize_v1': mismo resultado, mismo orden del pool.
//
// Por que existe: el esquema esta VERSIONADO, y el 1 tiene que poder seguir
// ejecutandose (ver la cabecera de hir.proto). El lector lo NORMALIZA al
// cargar y desde ahi la VM, el MIR y las vistas tienen un solo camino, el del
// esquema 2: nada de lo que viene despues sabe que existio el 1.
//
// El ORDEN del pool es el del emisor: el tipo de cada nodo entra antes que el
// de sus hijos, y en una funcion/lambda los parametros, luego el retorno y
// luego el cuerpo. No cambia lo que el programa significa (un indice es una
// direccion en una tabla), pero hace que el pool salga igual que el del
// emisor y que las vistas ('--pretty', '--summary') de un v1 coincidan con
// las de Python sobre el mismo archivo.
//
// El recorrido es EXPLICITO, con un 'switch' sin 'default' por cada 'oneof'
// (regla A-3): un nodo nuevo que no se anada aqui es un aviso del compilador
// de C++, no un tipo que se queda sin normalizar en silencio.
#include <string>
#include <unordered_map>

#include "suriax/hir/loader.hpp"
#include "suriax/hir/view.hpp"

namespace suriax::hir {
namespace {

class Normalizer {
public:
    explicit Normalizer(pb::Module& module) : module_(module) {}

    bool run(std::string& error) {
        if (module_.types_size() != 0) {
            error = "un .phir del esquema 1 no lleva pool de tipos "
                    "('Module.types', " + std::to_string(module_.types_size()) +
                    " entradas): el archivo mezcla los dos esquemas";
            return false;
        }
        // 0 = sin tipo: el tipo VACIO, igual que en el emisor
        const pb::Type& vacio = *module_.add_types();
        ids_.emplace(type_key(vacio), 0);
        for (int i = 0; i < module_.items_size(); ++i) decl(*module_.mutable_items(i));
        if (!error_.empty()) {
            error = error_;
            return false;
        }
        return true;
    }

private:
    std::uint32_t intern(const pb::Type& type) {
        const std::string key = type_key(type);
        auto it = ids_.find(key);
        if (it != ids_.end()) return it->second;
        const auto id = static_cast<std::uint32_t>(module_.types_size());
        *module_.add_types() = type;
        ids_.emplace(key, id);
        return id;
    }

    void mixed(const char* field) {
        if (error_.empty()) {
            error_ = std::string("un .phir del esquema 1 no lleva indices de tipo, y '") +
                     field + "' trae uno: el archivo mezcla los dos esquemas";
        }
    }

    // un campo de tipo singular: el inline pasa al pool y su indice al nodo
    template <class M>
    void fold(M& msg, std::uint32_t current_id, const char* field) {
        if (current_id != 0) {
            mixed(field);
            return;
        }
        if (!msg.has_type()) return;
        const std::uint32_t id = intern(msg.type());
        msg.clear_type();
        msg.set_type_id(id);
    }

    void expr(pb::Expr& e) {
        if (e.type_id() != 0) {
            mixed("Expr.type_id");
        } else if (e.has_restype()) {
            const std::uint32_t id = intern(e.restype());
            e.clear_restype();
            e.set_type_id(id);
        }
        switch (e.node_case()) {
            case pb::Expr::kLiteral:
            case pb::Expr::kIdentifier:
            case pb::Expr::kSizeof:   // su 'type' siempre fue inline
            case pb::Expr::NODE_NOT_SET:
                break;
            case pb::Expr::kInterp: {
                pb::InterpolatedString& interp = *e.mutable_interp();
                for (int i = 0; i < interp.parts_size(); ++i) {
                    pb::InterpolatedString_Part& part = *interp.mutable_parts(i);
                    if (part.has_expr()) expr(*part.mutable_expr());
                }
                break;
            }
            case pb::Expr::kUnary:
                if (e.unary().has_operand()) expr(*e.mutable_unary()->mutable_operand());
                break;
            case pb::Expr::kBinary: {
                pb::BinaryOp& b = *e.mutable_binary();
                if (b.has_left()) expr(*b.mutable_left());
                if (b.has_right()) expr(*b.mutable_right());
                break;
            }
            case pb::Expr::kAssignment: {
                pb::Assignment& a = *e.mutable_assignment();
                if (a.has_target()) expr(*a.mutable_target());
                if (a.has_value()) expr(*a.mutable_value());
                break;
            }
            case pb::Expr::kCall: {
                pb::Call& c = *e.mutable_call();
                if (c.has_callee()) expr(*c.mutable_callee());
                for (int i = 0; i < c.args_size(); ++i) expr(*c.mutable_args(i));
                break;
            }
            case pb::Expr::kIndex: {
                pb::Index& x = *e.mutable_index();
                if (x.has_obj()) expr(*x.mutable_obj());
                if (x.has_index()) expr(*x.mutable_index());
                break;
            }
            case pb::Expr::kMember:
                if (e.member().has_obj()) expr(*e.mutable_member()->mutable_obj());
                break;
            case pb::Expr::kAddrOf:
                if (e.addr_of().has_operand()) expr(*e.mutable_addr_of()->mutable_operand());
                break;
            case pb::Expr::kCastExpr:   // su 'type' siempre fue inline
                if (e.cast_expr().has_value()) expr(*e.mutable_cast_expr()->mutable_value());
                break;
            case pb::Expr::kStructLiteral: {
                pb::StructLiteral& s = *e.mutable_struct_literal();
                for (int i = 0; i < s.values_size(); ++i) expr(*s.mutable_values(i));
                break;
            }
            case pb::Expr::kMoveExpr:
                if (e.move_expr().has_operand()) expr(*e.mutable_move_expr()->mutable_operand());
                break;
            case pb::Expr::kLambdaExpr: {
                // el orden del emisor: parametros, retorno, cuerpo
                pb::LambdaExpr& l = *e.mutable_lambda_expr();
                for (int i = 0; i < l.params_size(); ++i) {
                    pb::Parameter& p = *l.mutable_params(i);
                    fold(p, p.type_id(), "Parameter.type_id");
                }
                if (l.return_type_id() != 0) {
                    mixed("LambdaExpr.return_type_id");
                } else if (l.has_return_type()) {
                    const std::uint32_t id = intern(l.return_type());
                    l.clear_return_type();
                    l.set_return_type_id(id);
                }
                if (l.has_body()) block(*l.mutable_body());
                break;
            }
        }
    }

    void block(pb::Block& b) {
        for (int i = 0; i < b.statements_size(); ++i) stmt(*b.mutable_statements(i));
    }

    void if_stmt(pb::IfStmt& s) {
        if (s.has_condition()) expr(*s.mutable_condition());
        if (s.has_then_block()) block(*s.mutable_then_block());
        if (s.has_else_block()) block(*s.mutable_else_block());
        if (s.has_else_if()) if_stmt(*s.mutable_else_if());
    }

    void stmt(pb::Stmt& s) {
        switch (s.node_case()) {
            case pb::Stmt::kBreakStmt:
            case pb::Stmt::kContinueStmt:
            case pb::Stmt::kImportBinding:
            case pb::Stmt::NODE_NOT_SET:
                break;
            case pb::Stmt::kBlock:
                block(*s.mutable_block());
                break;
            case pb::Stmt::kVarDecl: {
                pb::VarDecl& v = *s.mutable_var_decl();
                fold(v, v.type_id(), "VarDecl.type_id");
                if (v.has_value()) expr(*v.mutable_value());
                break;
            }
            case pb::Stmt::kIfStmt:
                if_stmt(*s.mutable_if_stmt());
                break;
            case pb::Stmt::kWhileStmt: {
                pb::WhileStmt& w = *s.mutable_while_stmt();
                if (w.has_condition()) expr(*w.mutable_condition());
                if (w.has_body()) block(*w.mutable_body());
                break;
            }
            case pb::Stmt::kMatchStmt: {
                pb::MatchStmt& m = *s.mutable_match_stmt();
                if (m.has_subject()) expr(*m.mutable_subject());
                for (int i = 0; i < m.cases_size(); ++i) {
                    pb::CaseArm& arm = *m.mutable_cases(i);
                    if (arm.has_pattern()) expr(*arm.mutable_pattern());
                    if (arm.has_body()) stmt(*arm.mutable_body());
                }
                break;
            }
            case pb::Stmt::kReturnStmt:
                if (s.return_stmt().has_value()) expr(*s.mutable_return_stmt()->mutable_value());
                break;
            case pb::Stmt::kMoveStmt:
                if (s.move_stmt().has_target()) expr(*s.mutable_move_stmt()->mutable_target());
                break;
            case pb::Stmt::kFreeStmt:
                if (s.free_stmt().has_target()) expr(*s.mutable_free_stmt()->mutable_target());
                break;
            case pb::Stmt::kExprStmt:
                if (s.expr_stmt().has_expr()) expr(*s.mutable_expr_stmt()->mutable_expr());
                break;
            case pb::Stmt::kTypeDecl:
                if (s.type_decl().has_value()) expr(*s.mutable_type_decl()->mutable_value());
                break;
            case pb::Stmt::kThrowStmt:
                if (s.throw_stmt().has_value()) expr(*s.mutable_throw_stmt()->mutable_value());
                break;
            case pb::Stmt::kTryStmt: {
                pb::TryStmt& t = *s.mutable_try_stmt();
                if (t.has_try_block()) block(*t.mutable_try_block());
                for (int i = 0; i < t.catches_size(); ++i) {
                    // 'CatchClause.type' siempre fue inline
                    pb::CatchClause& c = *t.mutable_catches(i);
                    if (c.has_block()) block(*c.mutable_block());
                }
                if (t.has_finally_block()) block(*t.mutable_finally_block());
                break;
            }
            case pb::Stmt::kExpectStmt: {
                pb::ExpectStmt& x = *s.mutable_expect_stmt();
                if (x.has_condition()) expr(*x.mutable_condition());
                if (x.has_body()) block(*x.mutable_body());
                break;
            }
        }
    }

    void decl(pb::Decl& d) {
        switch (d.node_case()) {
            case pb::Decl::kExternBlock:
            case pb::Decl::kImportDirective:
            case pb::Decl::kExportDirective:
            case pb::Decl::kFromDirective:
            case pb::Decl::NODE_NOT_SET:
                break;
            case pb::Decl::kFunction: {
                // el orden del emisor: parametros, retorno, cuerpo
                pb::FunctionDecl& f = *d.mutable_function();
                for (int i = 0; i < f.params_size(); ++i) {
                    pb::Parameter& p = *f.mutable_params(i);
                    fold(p, p.type_id(), "Parameter.type_id");
                }
                if (f.return_type_id() != 0) {
                    mixed("FunctionDecl.return_type_id");
                } else if (f.has_return_type()) {
                    const std::uint32_t id = intern(f.return_type());
                    f.clear_return_type();
                    f.set_return_type_id(id);
                }
                if (f.has_body()) block(*f.mutable_body());
                break;
            }
            case pb::Decl::kStructDecl: {
                pb::StructDecl& s = *d.mutable_struct_decl();
                for (int i = 0; i < s.fields_size(); ++i) {
                    pb::Field& f = *s.mutable_fields(i);
                    fold(f, f.type_id(), "Field.type_id");
                }
                break;
            }
            case pb::Decl::kEnumDecl: {
                pb::EnumDecl& en = *d.mutable_enum_decl();
                for (int i = 0; i < en.items_size(); ++i) {
                    pb::EnumItem& item = *en.mutable_items(i);
                    if (item.has_value()) expr(*item.mutable_value());
                    if (item.payload_type_ids_size() != 0) {
                        mixed("EnumItem.payload_type_ids");
                        continue;
                    }
                    for (const pb::Type& t : item.payload_types()) {
                        item.add_payload_type_ids(intern(t));
                    }
                    item.clear_payload_types();
                }
                break;
            }
            case pb::Decl::kStatement:
                stmt(*d.mutable_statement());
                break;
            case pb::Decl::kTestDecl: {
                pb::TestDecl& t = *d.mutable_test_decl();
                if (t.has_body()) block(*t.mutable_body());
                if (t.has_errfinally()) block(*t.mutable_errfinally());
                if (t.has_finally_block()) block(*t.mutable_finally_block());
                break;
            }
        }
    }

    pb::Module& module_;
    std::unordered_map<std::string, std::uint32_t> ids_;
    std::string error_;
};

}  // namespace

bool normalize_schema_v1(pb::Module& module, std::string& error) {
    if (module.schema_version() != 1) {
        error = "solo se normaliza un Module del esquema 1 (llego schema_version " +
                std::to_string(module.schema_version()) + ")";
        return false;
    }
    Normalizer normalizer(module);
    return normalizer.run(error);
}

}  // namespace suriax::hir

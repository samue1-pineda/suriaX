// ============================================================================
// GENERADO por backend/tools/gen_hir_cpp.py desde V0/src/HIR/proto/hir.proto.
// NO EDITAR A MANO: cambia el .proto y vuelve a correr el script. Una prueba
// (test_backend_cpp) falla si este archivo no es lo que el script genera.
//
// El modelo del HIR en C++, sin libprotobuf: la misma API que genera protoc
// (x(), has_x(), x(i), x_size(), node_case()...) y un lector del formato de
// protobuf que hace lo mismo que V0/src/HIR/wire.py.
// ============================================================================
#pragma once

#include <bit>
#include <cstddef>
#include <cstdint>
#include <istream>
#include <iterator>
#include <map>
#include <memory>
#include <stdexcept>
#include <string>
#include <utility>
#include <vector>

namespace suriax::hir::v0 {

// --- enums (sin ámbito, al nivel del paquete: como los de protoc) ----------

enum TypeKind : int {
    TYPE_UNSPECIFIED = 0,
    VOID = 1,
    BOOL = 2,
    INT = 3,
    FLOAT = 4,
    CHAR = 5,
    STR = 6,
    POINTER = 7,
    NULLABLE = 8,
    NOMINAL = 9,
    META = 10,
    ERROR = 11,
    BYTE = 12,
};

inline std::string TypeKind_Name(int valor) {
    switch (valor) {
        case 0: return "TYPE_UNSPECIFIED";
        case 1: return "VOID";
        case 2: return "BOOL";
        case 3: return "INT";
        case 4: return "FLOAT";
        case 5: return "CHAR";
        case 6: return "STR";
        case 7: return "POINTER";
        case 8: return "NULLABLE";
        case 9: return "NOMINAL";
        case 10: return "META";
        case 11: return "ERROR";
        case 12: return "BYTE";
        default: return std::string();
    }
}

enum SymbolKind : int {
    SYMBOL_UNSPECIFIED = 0,
    FUNCTION = 1,
    STRUCT = 2,
    ENUM = 3,
    ENUM_ITEM = 4,
    PARAM = 5,
    VAR = 6,
    FIELD = 7,
    IMPORT = 8,
    HOOK = 10,
    TYPE = 11,
};

inline std::string SymbolKind_Name(int valor) {
    switch (valor) {
        case 0: return "SYMBOL_UNSPECIFIED";
        case 1: return "FUNCTION";
        case 2: return "STRUCT";
        case 3: return "ENUM";
        case 4: return "ENUM_ITEM";
        case 5: return "PARAM";
        case 6: return "VAR";
        case 7: return "FIELD";
        case 8: return "IMPORT";
        case 10: return "HOOK";
        case 11: return "TYPE";
        default: return std::string();
    }
}

enum HookKind : int {
    HOOK_UNSPECIFIED = 0,
    FREE = 1,
    SIZEOF = 3,
    PRINT = 4,
    LEN = 5,
    CAST = 6,
    INDEX = 7,
    INDEX_SET = 8,
    EQ = 9,
    MIN = 10,
    MAX = 11,
    HASH = 12,
    EXTENDED = 100,
};

inline std::string HookKind_Name(int valor) {
    switch (valor) {
        case 0: return "HOOK_UNSPECIFIED";
        case 1: return "FREE";
        case 3: return "SIZEOF";
        case 4: return "PRINT";
        case 5: return "LEN";
        case 6: return "CAST";
        case 7: return "INDEX";
        case 8: return "INDEX_SET";
        case 9: return "EQ";
        case 10: return "MIN";
        case 11: return "MAX";
        case 12: return "HASH";
        case 100: return "EXTENDED";
        default: return std::string();
    }
}

// --- infraestructura: lectura del formato y contenedores ---------------------

namespace detalle {

// Lee el formato de protobuf (varints, 64/32 bits fijos, bloques con longitud).
// Todas las lecturas comprueban el límite: un .phir truncado o corrupto hace
// fallar la lectura, nunca lee fuera del búfer.
class Lector {
 public:
    Lector(const unsigned char* datos, std::size_t largo) : datos_(datos), largo_(largo) {}

    std::size_t pos() const { return pos_; }

    bool varint(std::uint64_t& valor) {
        valor = 0;
        for (int corrimiento = 0; corrimiento < 64; corrimiento += 7) {
            if (pos_ >= largo_) return false;
            const unsigned char byte = datos_[pos_++];
            valor |= static_cast<std::uint64_t>(byte & 0x7F) << corrimiento;
            if ((byte & 0x80) == 0) return true;
        }
        return false;
    }

    bool fijo64(std::uint64_t& valor) {
        if (largo_ - pos_ < 8) return false;
        valor = 0;
        for (int i = 0; i < 8; ++i) {
            valor |= static_cast<std::uint64_t>(datos_[pos_ + static_cast<std::size_t>(i)]) << (8 * i);
        }
        pos_ += 8;
        return true;
    }

    bool fijo32(std::uint32_t& valor) {
        if (largo_ - pos_ < 4) return false;
        valor = 0;
        for (int i = 0; i < 4; ++i) {
            valor |= static_cast<std::uint32_t>(datos_[pos_ + static_cast<std::size_t>(i)]) << (8 * i);
        }
        pos_ += 4;
        return true;
    }

    // Un bloque con longitud: deja en 'hasta' dónde termina (sin pasar de 'fin').
    bool largo(std::size_t& hasta, std::size_t fin) {
        std::uint64_t n;
        if (!varint(n) || n > fin - pos_) return false;
        hasta = pos_ + static_cast<std::size_t>(n);
        return true;
    }

    bool texto(std::string& destino, std::size_t fin) {
        std::size_t hasta;
        if (!largo(hasta, fin)) return false;
        destino.assign(reinterpret_cast<const char*>(datos_ + pos_), hasta - pos_);
        pos_ = hasta;
        return true;
    }

    // Un campo que el esquema no conoce: se salta, no se inventa (wire.py hace
    // lo mismo). Un tipo de wire desconocido es un archivo corrupto.
    bool salta(int tipo) {
        std::uint64_t basura;
        switch (tipo) {
            case 0: return varint(basura);
            case 1: return fijo64(basura);
            case 5: { std::uint32_t b32; return fijo32(b32); }
            case 2: {
                std::size_t hasta;
                if (!largo(hasta, largo_)) return false;
                pos_ = hasta;
                return true;
            }
            default: return false;
        }
    }

 private:
    const unsigned char* datos_;
    std::size_t largo_;
    std::size_t pos_ = 0;
};

// Un mensaje singular: puede faltar. Se copia en profundidad (los mensajes son
// valores, como en protoc) y permite tipos recursivos (Expr dentro de Expr).
template <class T>
class Caja {
 public:
    Caja() = default;
    Caja(const Caja& otra) : p_(otra.p_ ? std::make_unique<T>(*otra.p_) : nullptr) {}
    Caja& operator=(const Caja& otra) {
        if (this != &otra) p_ = otra.p_ ? std::make_unique<T>(*otra.p_) : nullptr;
        return *this;
    }
    Caja(Caja&&) noexcept = default;
    Caja& operator=(Caja&&) noexcept = default;
    ~Caja() = default;

    bool hay() const { return p_ != nullptr; }
    const T& valor() const { return *p_; }
    T& crea() {
        if (!p_) p_ = std::make_unique<T>();
        return *p_;
    }

 private:
    std::unique_ptr<T> p_;
};

// map<string, M>: claves en orden (determinista, a diferencia de protobuf, cuyo
// orden de iteración no está definido). Guarda los valores en un vector para
// admitir tipos recursivos (Symbol dentro de Symbol).
template <class V>
class Mapa {
 public:
    using value_type = std::pair<const std::string&, const V&>;

    class iterator {
     public:
        using iterator_category = std::forward_iterator_tag;
        using difference_type = std::ptrdiff_t;
        using value_type = Mapa::value_type;
        using pointer = void;
        using reference = value_type;

        struct Flecha {
            value_type par;
            const value_type* operator->() const { return &par; }
        };

        iterator(const Mapa* mapa, std::map<std::string, std::size_t>::const_iterator it)
            : mapa_(mapa), it_(it) {}
        value_type operator*() const { return {it_->first, mapa_->valores_[it_->second]}; }
        Flecha operator->() const { return Flecha{**this}; }
        iterator& operator++() { ++it_; return *this; }
        iterator operator++(int) { iterator copia = *this; ++it_; return copia; }
        bool operator==(const iterator& otro) const { return it_ == otro.it_; }
        bool operator!=(const iterator& otro) const { return it_ != otro.it_; }

     private:
        const Mapa* mapa_;
        std::map<std::string, std::size_t>::const_iterator it_;
    };
    using const_iterator = iterator;

    bool empty() const { return indice_.empty(); }
    std::size_t size() const { return indice_.size(); }
    iterator begin() const { return iterator(this, indice_.begin()); }
    iterator end() const { return iterator(this, indice_.end()); }
    iterator find(const std::string& clave) const { return iterator(this, indice_.find(clave)); }
    std::size_t count(const std::string& clave) const { return indice_.count(clave); }
    bool contains(const std::string& clave) const { return indice_.count(clave) != 0; }
    const V& at(const std::string& clave) const {
        const auto it = indice_.find(clave);
        if (it == indice_.end()) throw std::out_of_range("clave ausente en el mapa del HIR: " + clave);
        return valores_[it->second];
    }

    // Para el lector: la entrada de 'clave' (una clave repetida: gana la última,
    // como en protobuf).
    V& inserta(const std::string& clave) {
        const auto it = indice_.find(clave);
        if (it != indice_.end()) return valores_[it->second];
        indice_.emplace(clave, valores_.size());
        return valores_.emplace_back();
    }

 private:
    std::map<std::string, std::size_t> indice_;
    std::vector<V> valores_;
};

}  // namespace detalle

class Module;
class LibraryRef;
class Type;
class Symbol;
class HookEntry;
class SymbolTable;
class HookRef;
class Expr;
class Literal;
class InterpolatedString;
class InterpolatedString_Part;
class Identifier;
class UnaryOp;
class BinaryOp;
class Assignment;
class AddrOf;
class Call;
class MoveExpr;
class Index;
class MemberAccess;
class SizeofExpr;
class CastExpr;
class StructLiteral;
class Stmt;
class Drop;
class Block;
class VarDecl;
class TypeDecl;
class IfStmt;
class WhileStmt;
class CaseArm;
class MatchStmt;
class ReturnStmt;
class BreakStmt;
class ContinueStmt;
class MoveStmt;
class ThrowStmt;
class CatchClause;
class TryStmt;
class FreeStmt;
class ExprStmt;
class ImportBinding;
class Decl;
class TestDecl;
class Parameter;
class FunctionDecl;
class Field;
class StructDecl;
class EnumItem;
class EnumDecl;
class ExternBlock;
class ImportDirective;
class ExportDirective;
class FromDirective;

class Module {
 public:
    Module();
    Module(const Module&);
    Module& operator=(const Module&);
    Module(Module&&) noexcept;
    Module& operator=(Module&&) noexcept;
    ~Module();
    static const Module& default_instance();
    bool ParseFromString(const std::string& datos);
    bool ParseFromArray(const void* datos, int largo);
    bool ParseFromIstream(std::istream* entrada);
    bool _lee(detalle::Lector& lector, std::size_t fin);
    std::uint32_t schema_version() const;
    void set_schema_version(std::uint32_t valor);
    const std::string& source_file() const;
    void set_source_file(std::string valor);
    bool has_symbols() const;
    const SymbolTable& symbols() const;
    SymbolTable* mutable_symbols();
    const std::vector<Decl>& items() const;
    const Decl& items(int i) const;
    int items_size() const;
    Decl* add_items();
    const std::vector<LibraryRef>& libraries() const;
    const LibraryRef& libraries(int i) const;
    int libraries_size() const;
    LibraryRef* add_libraries();
    const std::vector<Type>& types() const;
    const Type& types(int i) const;
    int types_size() const;
    Type* add_types();
 private:
    std::uint32_t m_schema_version{};
    std::string m_source_file{};
    detalle::Caja<SymbolTable> m_symbols;
    std::vector<Decl> m_items;
    std::vector<LibraryRef> m_libraries;
    std::vector<Type> m_types;
};

class LibraryRef {
 public:
    LibraryRef();
    LibraryRef(const LibraryRef&);
    LibraryRef& operator=(const LibraryRef&);
    LibraryRef(LibraryRef&&) noexcept;
    LibraryRef& operator=(LibraryRef&&) noexcept;
    ~LibraryRef();
    static const LibraryRef& default_instance();
    bool ParseFromString(const std::string& datos);
    bool ParseFromArray(const void* datos, int largo);
    bool ParseFromIstream(std::istream* entrada);
    bool _lee(detalle::Lector& lector, std::size_t fin);
    const std::string& alias() const;
    void set_alias(std::string valor);
    const std::string& phir() const;
    void set_phir(std::string valor);
 private:
    std::string m_alias{};
    std::string m_phir{};
};

class Type {
 public:
    Type();
    Type(const Type&);
    Type& operator=(const Type&);
    Type(Type&&) noexcept;
    Type& operator=(Type&&) noexcept;
    ~Type();
    static const Type& default_instance();
    bool ParseFromString(const std::string& datos);
    bool ParseFromArray(const void* datos, int largo);
    bool ParseFromIstream(std::istream* entrada);
    bool _lee(detalle::Lector& lector, std::size_t fin);
    TypeKind kind() const;
    void set_kind(TypeKind valor);
    const std::string& name() const;
    void set_name(std::string valor);
    bool has_inner() const;
    const Type& inner() const;
    Type* mutable_inner();
    bool mut() const;
    void set_mut(bool valor);
    const std::vector<Type>& args() const;
    const Type& args(int i) const;
    int args_size() const;
    Type* add_args();
 private:
    int m_kind = 0;
    std::string m_name{};
    detalle::Caja<Type> m_inner;
    bool m_mut{};
    std::vector<Type> m_args;
};

class Symbol {
 public:
    Symbol();
    Symbol(const Symbol&);
    Symbol& operator=(const Symbol&);
    Symbol(Symbol&&) noexcept;
    Symbol& operator=(Symbol&&) noexcept;
    ~Symbol();
    static const Symbol& default_instance();
    bool ParseFromString(const std::string& datos);
    bool ParseFromArray(const void* datos, int largo);
    bool ParseFromIstream(std::istream* entrada);
    bool _lee(detalle::Lector& lector, std::size_t fin);
    const std::string& name() const;
    void set_name(std::string valor);
    SymbolKind kind() const;
    void set_kind(SymbolKind valor);
    std::uint32_t ln() const;
    void set_ln(std::uint32_t valor);
    std::uint32_t col() const;
    void set_col(std::uint32_t valor);
    bool has_type() const;
    const Type& type() const;
    Type* mutable_type();
    bool mutable_() const;
    void set_mutable(bool valor);
    std::uint32_t moved_at() const;
    void set_moved_at(std::uint32_t valor);
    const std::vector<Type>& param_types() const;
    const Type& param_types(int i) const;
    int param_types_size() const;
    Type* add_param_types();
    const detalle::Mapa<Symbol>& members() const;
    int members_size() const;
    HookKind hook_kind() const;
    void set_hook_kind(HookKind valor);
    const std::string& hook_owner() const;
    void set_hook_owner(std::string valor);
    const std::string& hook_name() const;
    void set_hook_name(std::string valor);
 private:
    std::string m_name{};
    int m_kind = 0;
    std::uint32_t m_ln{};
    std::uint32_t m_col{};
    detalle::Caja<Type> m_type;
    bool m_mutable{};
    std::uint32_t m_moved_at{};
    std::vector<Type> m_param_types;
    detalle::Mapa<Symbol> m_members;
    int m_hook_kind = 0;
    std::string m_hook_owner{};
    std::string m_hook_name{};
};

class HookEntry {
 public:
    HookEntry();
    HookEntry(const HookEntry&);
    HookEntry& operator=(const HookEntry&);
    HookEntry(HookEntry&&) noexcept;
    HookEntry& operator=(HookEntry&&) noexcept;
    ~HookEntry();
    static const HookEntry& default_instance();
    bool ParseFromString(const std::string& datos);
    bool ParseFromArray(const void* datos, int largo);
    bool ParseFromIstream(std::istream* entrada);
    bool _lee(detalle::Lector& lector, std::size_t fin);
    const std::string& owner_type() const;
    void set_owner_type(std::string valor);
    HookKind kind() const;
    void set_kind(HookKind valor);
    bool has_symbol() const;
    const Symbol& symbol() const;
    Symbol* mutable_symbol();
    const std::string& hook_name() const;
    void set_hook_name(std::string valor);
    const std::string& extension() const;
    void set_extension(std::string valor);
 private:
    std::string m_owner_type{};
    int m_kind = 0;
    detalle::Caja<Symbol> m_symbol;
    std::string m_hook_name{};
    std::string m_extension{};
};

class SymbolTable {
 public:
    SymbolTable();
    SymbolTable(const SymbolTable&);
    SymbolTable& operator=(const SymbolTable&);
    SymbolTable(SymbolTable&&) noexcept;
    SymbolTable& operator=(SymbolTable&&) noexcept;
    ~SymbolTable();
    static const SymbolTable& default_instance();
    bool ParseFromString(const std::string& datos);
    bool ParseFromArray(const void* datos, int largo);
    bool ParseFromIstream(std::istream* entrada);
    bool _lee(detalle::Lector& lector, std::size_t fin);
    const detalle::Mapa<Symbol>& types() const;
    int types_size() const;
    const detalle::Mapa<Symbol>& values() const;
    int values_size() const;
    const std::vector<HookEntry>& hooks() const;
    const HookEntry& hooks(int i) const;
    int hooks_size() const;
    HookEntry* add_hooks();
    const std::vector<Symbol>& casts() const;
    const Symbol& casts(int i) const;
    int casts_size() const;
    Symbol* add_casts();
 private:
    detalle::Mapa<Symbol> m_types;
    detalle::Mapa<Symbol> m_values;
    std::vector<HookEntry> m_hooks;
    std::vector<Symbol> m_casts;
};

class HookRef {
 public:
    HookRef();
    HookRef(const HookRef&);
    HookRef& operator=(const HookRef&);
    HookRef(HookRef&&) noexcept;
    HookRef& operator=(HookRef&&) noexcept;
    ~HookRef();
    static const HookRef& default_instance();
    bool ParseFromString(const std::string& datos);
    bool ParseFromArray(const void* datos, int largo);
    bool ParseFromIstream(std::istream* entrada);
    bool _lee(detalle::Lector& lector, std::size_t fin);
    const std::string& owner_type() const;
    void set_owner_type(std::string valor);
    HookKind kind() const;
    void set_kind(HookKind valor);
    const std::string& hook_name() const;
    void set_hook_name(std::string valor);
 private:
    std::string m_owner_type{};
    int m_kind = 0;
    std::string m_hook_name{};
};

class Expr {
 public:
    Expr();
    Expr(const Expr&);
    Expr& operator=(const Expr&);
    Expr(Expr&&) noexcept;
    Expr& operator=(Expr&&) noexcept;
    ~Expr();
    static const Expr& default_instance();
    bool ParseFromString(const std::string& datos);
    bool ParseFromArray(const void* datos, int largo);
    bool ParseFromIstream(std::istream* entrada);
    bool _lee(detalle::Lector& lector, std::size_t fin);
    enum NodeCase : int {
        kLiteral = 10,
        kInterp = 11,
        kIdentifier = 12,
        kUnary = 13,
        kBinary = 14,
        kAssignment = 15,
        kCall = 17,
        kIndex = 18,
        kMember = 19,
        kSizeof = 22,
        kAddrOf = 23,
        kCastExpr = 24,
        kStructLiteral = 25,
        kMoveExpr = 26,
        NODE_NOT_SET = 0,
    };
    NodeCase node_case() const;
    std::uint32_t ln() const;
    void set_ln(std::uint32_t valor);
    std::uint32_t col() const;
    void set_col(std::uint32_t valor);
    std::uint32_t type_id() const;
    void set_type_id(std::uint32_t valor);
    bool has_literal() const;
    const Literal& literal() const;
    Literal* mutable_literal();
    bool has_interp() const;
    const InterpolatedString& interp() const;
    InterpolatedString* mutable_interp();
    bool has_identifier() const;
    const Identifier& identifier() const;
    Identifier* mutable_identifier();
    bool has_unary() const;
    const UnaryOp& unary() const;
    UnaryOp* mutable_unary();
    bool has_binary() const;
    const BinaryOp& binary() const;
    BinaryOp* mutable_binary();
    bool has_assignment() const;
    const Assignment& assignment() const;
    Assignment* mutable_assignment();
    bool has_call() const;
    const Call& call() const;
    Call* mutable_call();
    bool has_index() const;
    const Index& index() const;
    Index* mutable_index();
    bool has_member() const;
    const MemberAccess& member() const;
    MemberAccess* mutable_member();
    bool has_sizeof_() const;
    const SizeofExpr& sizeof_() const;
    SizeofExpr* mutable_sizeof_();
    bool has_addr_of() const;
    const AddrOf& addr_of() const;
    AddrOf* mutable_addr_of();
    bool has_cast_expr() const;
    const CastExpr& cast_expr() const;
    CastExpr* mutable_cast_expr();
    bool has_struct_literal() const;
    const StructLiteral& struct_literal() const;
    StructLiteral* mutable_struct_literal();
    bool has_move_expr() const;
    const MoveExpr& move_expr() const;
    MoveExpr* mutable_move_expr();
 private:
    int node_caso_ = 0;
    std::uint32_t m_ln{};
    std::uint32_t m_col{};
    std::uint32_t m_type_id{};
    detalle::Caja<Literal> m_literal;
    detalle::Caja<InterpolatedString> m_interp;
    detalle::Caja<Identifier> m_identifier;
    detalle::Caja<UnaryOp> m_unary;
    detalle::Caja<BinaryOp> m_binary;
    detalle::Caja<Assignment> m_assignment;
    detalle::Caja<Call> m_call;
    detalle::Caja<Index> m_index;
    detalle::Caja<MemberAccess> m_member;
    detalle::Caja<SizeofExpr> m_sizeof;
    detalle::Caja<AddrOf> m_addr_of;
    detalle::Caja<CastExpr> m_cast_expr;
    detalle::Caja<StructLiteral> m_struct_literal;
    detalle::Caja<MoveExpr> m_move_expr;
};

class Literal {
 public:
    Literal();
    Literal(const Literal&);
    Literal& operator=(const Literal&);
    Literal(Literal&&) noexcept;
    Literal& operator=(Literal&&) noexcept;
    ~Literal();
    static const Literal& default_instance();
    bool ParseFromString(const std::string& datos);
    bool ParseFromArray(const void* datos, int largo);
    bool ParseFromIstream(std::istream* entrada);
    bool _lee(detalle::Lector& lector, std::size_t fin);
    enum ValueCase : int {
        kIntValue = 2,
        kFloatValue = 3,
        kStrValue = 4,
        kBoolValue = 5,
        VALUE_NOT_SET = 0,
    };
    ValueCase value_case() const;
    const std::string& kind() const;
    void set_kind(std::string valor);
    std::int64_t int_value() const;
    void set_int_value(std::int64_t valor);
    bool has_int_value() const;
    double float_value() const;
    void set_float_value(double valor);
    bool has_float_value() const;
    const std::string& str_value() const;
    void set_str_value(std::string valor);
    bool has_str_value() const;
    bool bool_value() const;
    void set_bool_value(bool valor);
    bool has_bool_value() const;
 private:
    int value_caso_ = 0;
    std::string m_kind{};
    std::int64_t m_int_value{};
    double m_float_value{};
    std::string m_str_value{};
    bool m_bool_value{};
};

class InterpolatedString {
 public:
    using Part = InterpolatedString_Part;
    InterpolatedString();
    InterpolatedString(const InterpolatedString&);
    InterpolatedString& operator=(const InterpolatedString&);
    InterpolatedString(InterpolatedString&&) noexcept;
    InterpolatedString& operator=(InterpolatedString&&) noexcept;
    ~InterpolatedString();
    static const InterpolatedString& default_instance();
    bool ParseFromString(const std::string& datos);
    bool ParseFromArray(const void* datos, int largo);
    bool ParseFromIstream(std::istream* entrada);
    bool _lee(detalle::Lector& lector, std::size_t fin);
    const std::vector<InterpolatedString_Part>& parts() const;
    const InterpolatedString_Part& parts(int i) const;
    int parts_size() const;
    InterpolatedString_Part* add_parts();
 private:
    std::vector<InterpolatedString_Part> m_parts;
};

class InterpolatedString_Part {
 public:
    InterpolatedString_Part();
    InterpolatedString_Part(const InterpolatedString_Part&);
    InterpolatedString_Part& operator=(const InterpolatedString_Part&);
    InterpolatedString_Part(InterpolatedString_Part&&) noexcept;
    InterpolatedString_Part& operator=(InterpolatedString_Part&&) noexcept;
    ~InterpolatedString_Part();
    static const InterpolatedString_Part& default_instance();
    bool ParseFromString(const std::string& datos);
    bool ParseFromArray(const void* datos, int largo);
    bool ParseFromIstream(std::istream* entrada);
    bool _lee(detalle::Lector& lector, std::size_t fin);
    enum PartCase : int {
        kText = 1,
        kExpr = 2,
        PART_NOT_SET = 0,
    };
    PartCase part_case() const;
    const std::string& text() const;
    void set_text(std::string valor);
    bool has_text() const;
    bool has_expr() const;
    const Expr& expr() const;
    Expr* mutable_expr();
    bool repr() const;
    void set_repr(bool valor);
    const std::string& spec() const;
    void set_spec(std::string valor);
 private:
    int part_caso_ = 0;
    std::string m_text{};
    detalle::Caja<Expr> m_expr;
    bool m_repr{};
    std::string m_spec{};
};

class Identifier {
 public:
    Identifier();
    Identifier(const Identifier&);
    Identifier& operator=(const Identifier&);
    Identifier(Identifier&&) noexcept;
    Identifier& operator=(Identifier&&) noexcept;
    ~Identifier();
    static const Identifier& default_instance();
    bool ParseFromString(const std::string& datos);
    bool ParseFromArray(const void* datos, int largo);
    bool ParseFromIstream(std::istream* entrada);
    bool _lee(detalle::Lector& lector, std::size_t fin);
    const std::string& name() const;
    void set_name(std::string valor);
 private:
    std::string m_name{};
};

class UnaryOp {
 public:
    UnaryOp();
    UnaryOp(const UnaryOp&);
    UnaryOp& operator=(const UnaryOp&);
    UnaryOp(UnaryOp&&) noexcept;
    UnaryOp& operator=(UnaryOp&&) noexcept;
    ~UnaryOp();
    static const UnaryOp& default_instance();
    bool ParseFromString(const std::string& datos);
    bool ParseFromArray(const void* datos, int largo);
    bool ParseFromIstream(std::istream* entrada);
    bool _lee(detalle::Lector& lector, std::size_t fin);
    const std::string& op() const;
    void set_op(std::string valor);
    bool has_operand() const;
    const Expr& operand() const;
    Expr* mutable_operand();
 private:
    std::string m_op{};
    detalle::Caja<Expr> m_operand;
};

class BinaryOp {
 public:
    BinaryOp();
    BinaryOp(const BinaryOp&);
    BinaryOp& operator=(const BinaryOp&);
    BinaryOp(BinaryOp&&) noexcept;
    BinaryOp& operator=(BinaryOp&&) noexcept;
    ~BinaryOp();
    static const BinaryOp& default_instance();
    bool ParseFromString(const std::string& datos);
    bool ParseFromArray(const void* datos, int largo);
    bool ParseFromIstream(std::istream* entrada);
    bool _lee(detalle::Lector& lector, std::size_t fin);
    const std::string& op() const;
    void set_op(std::string valor);
    bool has_left() const;
    const Expr& left() const;
    Expr* mutable_left();
    bool has_right() const;
    const Expr& right() const;
    Expr* mutable_right();
 private:
    std::string m_op{};
    detalle::Caja<Expr> m_left;
    detalle::Caja<Expr> m_right;
};

class Assignment {
 public:
    Assignment();
    Assignment(const Assignment&);
    Assignment& operator=(const Assignment&);
    Assignment(Assignment&&) noexcept;
    Assignment& operator=(Assignment&&) noexcept;
    ~Assignment();
    static const Assignment& default_instance();
    bool ParseFromString(const std::string& datos);
    bool ParseFromArray(const void* datos, int largo);
    bool ParseFromIstream(std::istream* entrada);
    bool _lee(detalle::Lector& lector, std::size_t fin);
    bool has_target() const;
    const Expr& target() const;
    Expr* mutable_target();
    bool has_value() const;
    const Expr& value() const;
    Expr* mutable_value();
    bool drops_old() const;
    void set_drops_old(bool valor);
 private:
    detalle::Caja<Expr> m_target;
    detalle::Caja<Expr> m_value;
    bool m_drops_old{};
};

class AddrOf {
 public:
    AddrOf();
    AddrOf(const AddrOf&);
    AddrOf& operator=(const AddrOf&);
    AddrOf(AddrOf&&) noexcept;
    AddrOf& operator=(AddrOf&&) noexcept;
    ~AddrOf();
    static const AddrOf& default_instance();
    bool ParseFromString(const std::string& datos);
    bool ParseFromArray(const void* datos, int largo);
    bool ParseFromIstream(std::istream* entrada);
    bool _lee(detalle::Lector& lector, std::size_t fin);
    bool has_operand() const;
    const Expr& operand() const;
    Expr* mutable_operand();
    bool mut() const;
    void set_mut(bool valor);
 private:
    detalle::Caja<Expr> m_operand;
    bool m_mut{};
};

class Call {
 public:
    Call();
    Call(const Call&);
    Call& operator=(const Call&);
    Call(Call&&) noexcept;
    Call& operator=(Call&&) noexcept;
    ~Call();
    static const Call& default_instance();
    bool ParseFromString(const std::string& datos);
    bool ParseFromArray(const void* datos, int largo);
    bool ParseFromIstream(std::istream* entrada);
    bool _lee(detalle::Lector& lector, std::size_t fin);
    bool has_callee() const;
    const Expr& callee() const;
    Expr* mutable_callee();
    const std::vector<Expr>& args() const;
    const Expr& args(int i) const;
    int args_size() const;
    Expr* add_args();
    bool has_hook() const;
    const HookRef& hook() const;
    HookRef* mutable_hook();
    bool has_temp_drop() const;
    const HookRef& temp_drop() const;
    HookRef* mutable_temp_drop();
    bool temp_by_type() const;
    void set_temp_by_type(bool valor);
 private:
    detalle::Caja<Expr> m_callee;
    std::vector<Expr> m_args;
    detalle::Caja<HookRef> m_hook;
    detalle::Caja<HookRef> m_temp_drop;
    bool m_temp_by_type{};
};

class MoveExpr {
 public:
    MoveExpr();
    MoveExpr(const MoveExpr&);
    MoveExpr& operator=(const MoveExpr&);
    MoveExpr(MoveExpr&&) noexcept;
    MoveExpr& operator=(MoveExpr&&) noexcept;
    ~MoveExpr();
    static const MoveExpr& default_instance();
    bool ParseFromString(const std::string& datos);
    bool ParseFromArray(const void* datos, int largo);
    bool ParseFromIstream(std::istream* entrada);
    bool _lee(detalle::Lector& lector, std::size_t fin);
    bool has_operand() const;
    const Expr& operand() const;
    Expr* mutable_operand();
 private:
    detalle::Caja<Expr> m_operand;
};

class Index {
 public:
    Index();
    Index(const Index&);
    Index& operator=(const Index&);
    Index(Index&&) noexcept;
    Index& operator=(Index&&) noexcept;
    ~Index();
    static const Index& default_instance();
    bool ParseFromString(const std::string& datos);
    bool ParseFromArray(const void* datos, int largo);
    bool ParseFromIstream(std::istream* entrada);
    bool _lee(detalle::Lector& lector, std::size_t fin);
    bool has_obj() const;
    const Expr& obj() const;
    Expr* mutable_obj();
    bool has_index() const;
    const Expr& index() const;
    Expr* mutable_index();
 private:
    detalle::Caja<Expr> m_obj;
    detalle::Caja<Expr> m_index;
};

class MemberAccess {
 public:
    MemberAccess();
    MemberAccess(const MemberAccess&);
    MemberAccess& operator=(const MemberAccess&);
    MemberAccess(MemberAccess&&) noexcept;
    MemberAccess& operator=(MemberAccess&&) noexcept;
    ~MemberAccess();
    static const MemberAccess& default_instance();
    bool ParseFromString(const std::string& datos);
    bool ParseFromArray(const void* datos, int largo);
    bool ParseFromIstream(std::istream* entrada);
    bool _lee(detalle::Lector& lector, std::size_t fin);
    bool has_obj() const;
    const Expr& obj() const;
    Expr* mutable_obj();
    const std::string& member() const;
    void set_member(std::string valor);
 private:
    detalle::Caja<Expr> m_obj;
    std::string m_member{};
};

class SizeofExpr {
 public:
    SizeofExpr();
    SizeofExpr(const SizeofExpr&);
    SizeofExpr& operator=(const SizeofExpr&);
    SizeofExpr(SizeofExpr&&) noexcept;
    SizeofExpr& operator=(SizeofExpr&&) noexcept;
    ~SizeofExpr();
    static const SizeofExpr& default_instance();
    bool ParseFromString(const std::string& datos);
    bool ParseFromArray(const void* datos, int largo);
    bool ParseFromIstream(std::istream* entrada);
    bool _lee(detalle::Lector& lector, std::size_t fin);
    bool has_type() const;
    const Type& type() const;
    Type* mutable_type();
    bool has_hook() const;
    const HookRef& hook() const;
    HookRef* mutable_hook();
 private:
    detalle::Caja<Type> m_type;
    detalle::Caja<HookRef> m_hook;
};

class CastExpr {
 public:
    CastExpr();
    CastExpr(const CastExpr&);
    CastExpr& operator=(const CastExpr&);
    CastExpr(CastExpr&&) noexcept;
    CastExpr& operator=(CastExpr&&) noexcept;
    ~CastExpr();
    static const CastExpr& default_instance();
    bool ParseFromString(const std::string& datos);
    bool ParseFromArray(const void* datos, int largo);
    bool ParseFromIstream(std::istream* entrada);
    bool _lee(detalle::Lector& lector, std::size_t fin);
    bool has_type() const;
    const Type& type() const;
    Type* mutable_type();
    bool has_value() const;
    const Expr& value() const;
    Expr* mutable_value();
    bool has_hook() const;
    const HookRef& hook() const;
    HookRef* mutable_hook();
 private:
    detalle::Caja<Type> m_type;
    detalle::Caja<Expr> m_value;
    detalle::Caja<HookRef> m_hook;
};

class StructLiteral {
 public:
    StructLiteral();
    StructLiteral(const StructLiteral&);
    StructLiteral& operator=(const StructLiteral&);
    StructLiteral(StructLiteral&&) noexcept;
    StructLiteral& operator=(StructLiteral&&) noexcept;
    ~StructLiteral();
    static const StructLiteral& default_instance();
    bool ParseFromString(const std::string& datos);
    bool ParseFromArray(const void* datos, int largo);
    bool ParseFromIstream(std::istream* entrada);
    bool _lee(detalle::Lector& lector, std::size_t fin);
    const std::string& type_name() const;
    void set_type_name(std::string valor);
    const std::vector<std::string>& field_names() const;
    const std::string& field_names(int i) const;
    int field_names_size() const;
    const std::vector<Expr>& values() const;
    const Expr& values(int i) const;
    int values_size() const;
    Expr* add_values();
    bool has_temp_drop() const;
    const HookRef& temp_drop() const;
    HookRef* mutable_temp_drop();
    bool temp_by_type() const;
    void set_temp_by_type(bool valor);
 private:
    std::string m_type_name{};
    std::vector<std::string> m_field_names;
    std::vector<Expr> m_values;
    detalle::Caja<HookRef> m_temp_drop;
    bool m_temp_by_type{};
};

class Stmt {
 public:
    Stmt();
    Stmt(const Stmt&);
    Stmt& operator=(const Stmt&);
    Stmt(Stmt&&) noexcept;
    Stmt& operator=(Stmt&&) noexcept;
    ~Stmt();
    static const Stmt& default_instance();
    bool ParseFromString(const std::string& datos);
    bool ParseFromArray(const void* datos, int largo);
    bool ParseFromIstream(std::istream* entrada);
    bool _lee(detalle::Lector& lector, std::size_t fin);
    enum NodeCase : int {
        kBlock = 10,
        kVarDecl = 11,
        kIfStmt = 13,
        kWhileStmt = 14,
        kMatchStmt = 15,
        kReturnStmt = 16,
        kBreakStmt = 17,
        kContinueStmt = 18,
        kMoveStmt = 19,
        kFreeStmt = 20,
        kExprStmt = 21,
        kImportBinding = 22,
        kTypeDecl = 23,
        kThrowStmt = 24,
        kTryStmt = 25,
        NODE_NOT_SET = 0,
    };
    NodeCase node_case() const;
    std::uint32_t ln() const;
    void set_ln(std::uint32_t valor);
    std::uint32_t col() const;
    void set_col(std::uint32_t valor);
    bool has_block() const;
    const Block& block() const;
    Block* mutable_block();
    bool has_var_decl() const;
    const VarDecl& var_decl() const;
    VarDecl* mutable_var_decl();
    bool has_if_stmt() const;
    const IfStmt& if_stmt() const;
    IfStmt* mutable_if_stmt();
    bool has_while_stmt() const;
    const WhileStmt& while_stmt() const;
    WhileStmt* mutable_while_stmt();
    bool has_match_stmt() const;
    const MatchStmt& match_stmt() const;
    MatchStmt* mutable_match_stmt();
    bool has_return_stmt() const;
    const ReturnStmt& return_stmt() const;
    ReturnStmt* mutable_return_stmt();
    bool has_break_stmt() const;
    const BreakStmt& break_stmt() const;
    BreakStmt* mutable_break_stmt();
    bool has_continue_stmt() const;
    const ContinueStmt& continue_stmt() const;
    ContinueStmt* mutable_continue_stmt();
    bool has_move_stmt() const;
    const MoveStmt& move_stmt() const;
    MoveStmt* mutable_move_stmt();
    bool has_free_stmt() const;
    const FreeStmt& free_stmt() const;
    FreeStmt* mutable_free_stmt();
    bool has_expr_stmt() const;
    const ExprStmt& expr_stmt() const;
    ExprStmt* mutable_expr_stmt();
    bool has_import_binding() const;
    const ImportBinding& import_binding() const;
    ImportBinding* mutable_import_binding();
    bool has_type_decl() const;
    const TypeDecl& type_decl() const;
    TypeDecl* mutable_type_decl();
    bool has_throw_stmt() const;
    const ThrowStmt& throw_stmt() const;
    ThrowStmt* mutable_throw_stmt();
    bool has_try_stmt() const;
    const TryStmt& try_stmt() const;
    TryStmt* mutable_try_stmt();
 private:
    int node_caso_ = 0;
    std::uint32_t m_ln{};
    std::uint32_t m_col{};
    detalle::Caja<Block> m_block;
    detalle::Caja<VarDecl> m_var_decl;
    detalle::Caja<IfStmt> m_if_stmt;
    detalle::Caja<WhileStmt> m_while_stmt;
    detalle::Caja<MatchStmt> m_match_stmt;
    detalle::Caja<ReturnStmt> m_return_stmt;
    detalle::Caja<BreakStmt> m_break_stmt;
    detalle::Caja<ContinueStmt> m_continue_stmt;
    detalle::Caja<MoveStmt> m_move_stmt;
    detalle::Caja<FreeStmt> m_free_stmt;
    detalle::Caja<ExprStmt> m_expr_stmt;
    detalle::Caja<ImportBinding> m_import_binding;
    detalle::Caja<TypeDecl> m_type_decl;
    detalle::Caja<ThrowStmt> m_throw_stmt;
    detalle::Caja<TryStmt> m_try_stmt;
};

class Drop {
 public:
    Drop();
    Drop(const Drop&);
    Drop& operator=(const Drop&);
    Drop(Drop&&) noexcept;
    Drop& operator=(Drop&&) noexcept;
    ~Drop();
    static const Drop& default_instance();
    bool ParseFromString(const std::string& datos);
    bool ParseFromArray(const void* datos, int largo);
    bool ParseFromIstream(std::istream* entrada);
    bool _lee(detalle::Lector& lector, std::size_t fin);
    const std::vector<std::string>& path() const;
    const std::string& path(int i) const;
    int path_size() const;
    bool has_hook() const;
    const HookRef& hook() const;
    HookRef* mutable_hook();
    bool by_type() const;
    void set_by_type(bool valor);
 private:
    std::vector<std::string> m_path;
    detalle::Caja<HookRef> m_hook;
    bool m_by_type{};
};

class Block {
 public:
    Block();
    Block(const Block&);
    Block& operator=(const Block&);
    Block(Block&&) noexcept;
    Block& operator=(Block&&) noexcept;
    ~Block();
    static const Block& default_instance();
    bool ParseFromString(const std::string& datos);
    bool ParseFromArray(const void* datos, int largo);
    bool ParseFromIstream(std::istream* entrada);
    bool _lee(detalle::Lector& lector, std::size_t fin);
    const std::vector<Stmt>& statements() const;
    const Stmt& statements(int i) const;
    int statements_size() const;
    Stmt* add_statements();
    const std::vector<Drop>& drops() const;
    const Drop& drops(int i) const;
    int drops_size() const;
    Drop* add_drops();
 private:
    std::vector<Stmt> m_statements;
    std::vector<Drop> m_drops;
};

class VarDecl {
 public:
    VarDecl();
    VarDecl(const VarDecl&);
    VarDecl& operator=(const VarDecl&);
    VarDecl(VarDecl&&) noexcept;
    VarDecl& operator=(VarDecl&&) noexcept;
    ~VarDecl();
    static const VarDecl& default_instance();
    bool ParseFromString(const std::string& datos);
    bool ParseFromArray(const void* datos, int largo);
    bool ParseFromIstream(std::istream* entrada);
    bool _lee(detalle::Lector& lector, std::size_t fin);
    const std::string& qualifier() const;
    void set_qualifier(std::string valor);
    const std::string& name() const;
    void set_name(std::string valor);
    bool has_value() const;
    const Expr& value() const;
    Expr* mutable_value();
    std::uint32_t type_id() const;
    void set_type_id(std::uint32_t valor);
 private:
    std::string m_qualifier{};
    std::string m_name{};
    detalle::Caja<Expr> m_value;
    std::uint32_t m_type_id{};
};

class TypeDecl {
 public:
    TypeDecl();
    TypeDecl(const TypeDecl&);
    TypeDecl& operator=(const TypeDecl&);
    TypeDecl(TypeDecl&&) noexcept;
    TypeDecl& operator=(TypeDecl&&) noexcept;
    ~TypeDecl();
    static const TypeDecl& default_instance();
    bool ParseFromString(const std::string& datos);
    bool ParseFromArray(const void* datos, int largo);
    bool ParseFromIstream(std::istream* entrada);
    bool _lee(detalle::Lector& lector, std::size_t fin);
    const std::string& qualifier() const;
    void set_qualifier(std::string valor);
    const std::string& name() const;
    void set_name(std::string valor);
    bool has_value() const;
    const Expr& value() const;
    Expr* mutable_value();
 private:
    std::string m_qualifier{};
    std::string m_name{};
    detalle::Caja<Expr> m_value;
};

class IfStmt {
 public:
    IfStmt();
    IfStmt(const IfStmt&);
    IfStmt& operator=(const IfStmt&);
    IfStmt(IfStmt&&) noexcept;
    IfStmt& operator=(IfStmt&&) noexcept;
    ~IfStmt();
    static const IfStmt& default_instance();
    bool ParseFromString(const std::string& datos);
    bool ParseFromArray(const void* datos, int largo);
    bool ParseFromIstream(std::istream* entrada);
    bool _lee(detalle::Lector& lector, std::size_t fin);
    enum ElseBranchCase : int {
        kElseBlock = 3,
        kElseIf = 4,
        ELSE_BRANCH_NOT_SET = 0,
    };
    ElseBranchCase else_branch_case() const;
    bool has_condition() const;
    const Expr& condition() const;
    Expr* mutable_condition();
    bool has_then_block() const;
    const Block& then_block() const;
    Block* mutable_then_block();
    bool has_else_block() const;
    const Block& else_block() const;
    Block* mutable_else_block();
    bool has_else_if() const;
    const IfStmt& else_if() const;
    IfStmt* mutable_else_if();
 private:
    int else_branch_caso_ = 0;
    detalle::Caja<Expr> m_condition;
    detalle::Caja<Block> m_then_block;
    detalle::Caja<Block> m_else_block;
    detalle::Caja<IfStmt> m_else_if;
};

class WhileStmt {
 public:
    WhileStmt();
    WhileStmt(const WhileStmt&);
    WhileStmt& operator=(const WhileStmt&);
    WhileStmt(WhileStmt&&) noexcept;
    WhileStmt& operator=(WhileStmt&&) noexcept;
    ~WhileStmt();
    static const WhileStmt& default_instance();
    bool ParseFromString(const std::string& datos);
    bool ParseFromArray(const void* datos, int largo);
    bool ParseFromIstream(std::istream* entrada);
    bool _lee(detalle::Lector& lector, std::size_t fin);
    bool has_condition() const;
    const Expr& condition() const;
    Expr* mutable_condition();
    bool has_body() const;
    const Block& body() const;
    Block* mutable_body();
 private:
    detalle::Caja<Expr> m_condition;
    detalle::Caja<Block> m_body;
};

class CaseArm {
 public:
    CaseArm();
    CaseArm(const CaseArm&);
    CaseArm& operator=(const CaseArm&);
    CaseArm(CaseArm&&) noexcept;
    CaseArm& operator=(CaseArm&&) noexcept;
    ~CaseArm();
    static const CaseArm& default_instance();
    bool ParseFromString(const std::string& datos);
    bool ParseFromArray(const void* datos, int largo);
    bool ParseFromIstream(std::istream* entrada);
    bool _lee(detalle::Lector& lector, std::size_t fin);
    bool has_pattern() const;
    const Expr& pattern() const;
    Expr* mutable_pattern();
    bool has_body() const;
    const Stmt& body() const;
    Stmt* mutable_body();
 private:
    detalle::Caja<Expr> m_pattern;
    detalle::Caja<Stmt> m_body;
};

class MatchStmt {
 public:
    MatchStmt();
    MatchStmt(const MatchStmt&);
    MatchStmt& operator=(const MatchStmt&);
    MatchStmt(MatchStmt&&) noexcept;
    MatchStmt& operator=(MatchStmt&&) noexcept;
    ~MatchStmt();
    static const MatchStmt& default_instance();
    bool ParseFromString(const std::string& datos);
    bool ParseFromArray(const void* datos, int largo);
    bool ParseFromIstream(std::istream* entrada);
    bool _lee(detalle::Lector& lector, std::size_t fin);
    bool has_subject() const;
    const Expr& subject() const;
    Expr* mutable_subject();
    const std::vector<CaseArm>& cases() const;
    const CaseArm& cases(int i) const;
    int cases_size() const;
    CaseArm* add_cases();
 private:
    detalle::Caja<Expr> m_subject;
    std::vector<CaseArm> m_cases;
};

class ReturnStmt {
 public:
    ReturnStmt();
    ReturnStmt(const ReturnStmt&);
    ReturnStmt& operator=(const ReturnStmt&);
    ReturnStmt(ReturnStmt&&) noexcept;
    ReturnStmt& operator=(ReturnStmt&&) noexcept;
    ~ReturnStmt();
    static const ReturnStmt& default_instance();
    bool ParseFromString(const std::string& datos);
    bool ParseFromArray(const void* datos, int largo);
    bool ParseFromIstream(std::istream* entrada);
    bool _lee(detalle::Lector& lector, std::size_t fin);
    bool has_value() const;
    const Expr& value() const;
    Expr* mutable_value();
    bool transfers() const;
    void set_transfers(bool valor);
 private:
    detalle::Caja<Expr> m_value;
    bool m_transfers{};
};

class BreakStmt {
 public:
    BreakStmt();
    BreakStmt(const BreakStmt&);
    BreakStmt& operator=(const BreakStmt&);
    BreakStmt(BreakStmt&&) noexcept;
    BreakStmt& operator=(BreakStmt&&) noexcept;
    ~BreakStmt();
    static const BreakStmt& default_instance();
    bool ParseFromString(const std::string& datos);
    bool ParseFromArray(const void* datos, int largo);
    bool ParseFromIstream(std::istream* entrada);
    bool _lee(detalle::Lector& lector, std::size_t fin);
 private:
};

class ContinueStmt {
 public:
    ContinueStmt();
    ContinueStmt(const ContinueStmt&);
    ContinueStmt& operator=(const ContinueStmt&);
    ContinueStmt(ContinueStmt&&) noexcept;
    ContinueStmt& operator=(ContinueStmt&&) noexcept;
    ~ContinueStmt();
    static const ContinueStmt& default_instance();
    bool ParseFromString(const std::string& datos);
    bool ParseFromArray(const void* datos, int largo);
    bool ParseFromIstream(std::istream* entrada);
    bool _lee(detalle::Lector& lector, std::size_t fin);
 private:
};

class MoveStmt {
 public:
    MoveStmt();
    MoveStmt(const MoveStmt&);
    MoveStmt& operator=(const MoveStmt&);
    MoveStmt(MoveStmt&&) noexcept;
    MoveStmt& operator=(MoveStmt&&) noexcept;
    ~MoveStmt();
    static const MoveStmt& default_instance();
    bool ParseFromString(const std::string& datos);
    bool ParseFromArray(const void* datos, int largo);
    bool ParseFromIstream(std::istream* entrada);
    bool _lee(detalle::Lector& lector, std::size_t fin);
    bool has_target() const;
    const Expr& target() const;
    Expr* mutable_target();
 private:
    detalle::Caja<Expr> m_target;
};

class ThrowStmt {
 public:
    ThrowStmt();
    ThrowStmt(const ThrowStmt&);
    ThrowStmt& operator=(const ThrowStmt&);
    ThrowStmt(ThrowStmt&&) noexcept;
    ThrowStmt& operator=(ThrowStmt&&) noexcept;
    ~ThrowStmt();
    static const ThrowStmt& default_instance();
    bool ParseFromString(const std::string& datos);
    bool ParseFromArray(const void* datos, int largo);
    bool ParseFromIstream(std::istream* entrada);
    bool _lee(detalle::Lector& lector, std::size_t fin);
    bool has_value() const;
    const Expr& value() const;
    Expr* mutable_value();
 private:
    detalle::Caja<Expr> m_value;
};

class CatchClause {
 public:
    CatchClause();
    CatchClause(const CatchClause&);
    CatchClause& operator=(const CatchClause&);
    CatchClause(CatchClause&&) noexcept;
    CatchClause& operator=(CatchClause&&) noexcept;
    ~CatchClause();
    static const CatchClause& default_instance();
    bool ParseFromString(const std::string& datos);
    bool ParseFromArray(const void* datos, int largo);
    bool ParseFromIstream(std::istream* entrada);
    bool _lee(detalle::Lector& lector, std::size_t fin);
    const std::string& name() const;
    void set_name(std::string valor);
    bool has_block() const;
    const Block& block() const;
    Block* mutable_block();
    bool has_type() const;
    const Type& type() const;
    Type* mutable_type();
 private:
    std::string m_name{};
    detalle::Caja<Block> m_block;
    detalle::Caja<Type> m_type;
};

class TryStmt {
 public:
    TryStmt();
    TryStmt(const TryStmt&);
    TryStmt& operator=(const TryStmt&);
    TryStmt(TryStmt&&) noexcept;
    TryStmt& operator=(TryStmt&&) noexcept;
    ~TryStmt();
    static const TryStmt& default_instance();
    bool ParseFromString(const std::string& datos);
    bool ParseFromArray(const void* datos, int largo);
    bool ParseFromIstream(std::istream* entrada);
    bool _lee(detalle::Lector& lector, std::size_t fin);
    bool has_try_block() const;
    const Block& try_block() const;
    Block* mutable_try_block();
    const std::vector<CatchClause>& catches() const;
    const CatchClause& catches(int i) const;
    int catches_size() const;
    CatchClause* add_catches();
    bool has_finally_block() const;
    const Block& finally_block() const;
    Block* mutable_finally_block();
 private:
    detalle::Caja<Block> m_try_block;
    std::vector<CatchClause> m_catches;
    detalle::Caja<Block> m_finally_block;
};

class FreeStmt {
 public:
    FreeStmt();
    FreeStmt(const FreeStmt&);
    FreeStmt& operator=(const FreeStmt&);
    FreeStmt(FreeStmt&&) noexcept;
    FreeStmt& operator=(FreeStmt&&) noexcept;
    ~FreeStmt();
    static const FreeStmt& default_instance();
    bool ParseFromString(const std::string& datos);
    bool ParseFromArray(const void* datos, int largo);
    bool ParseFromIstream(std::istream* entrada);
    bool _lee(detalle::Lector& lector, std::size_t fin);
    bool has_target() const;
    const Expr& target() const;
    Expr* mutable_target();
    bool has_hook() const;
    const HookRef& hook() const;
    HookRef* mutable_hook();
 private:
    detalle::Caja<Expr> m_target;
    detalle::Caja<HookRef> m_hook;
};

class ExprStmt {
 public:
    ExprStmt();
    ExprStmt(const ExprStmt&);
    ExprStmt& operator=(const ExprStmt&);
    ExprStmt(ExprStmt&&) noexcept;
    ExprStmt& operator=(ExprStmt&&) noexcept;
    ~ExprStmt();
    static const ExprStmt& default_instance();
    bool ParseFromString(const std::string& datos);
    bool ParseFromArray(const void* datos, int largo);
    bool ParseFromIstream(std::istream* entrada);
    bool _lee(detalle::Lector& lector, std::size_t fin);
    bool has_expr() const;
    const Expr& expr() const;
    Expr* mutable_expr();
 private:
    detalle::Caja<Expr> m_expr;
};

class ImportBinding {
 public:
    ImportBinding();
    ImportBinding(const ImportBinding&);
    ImportBinding& operator=(const ImportBinding&);
    ImportBinding(ImportBinding&&) noexcept;
    ImportBinding& operator=(ImportBinding&&) noexcept;
    ~ImportBinding();
    static const ImportBinding& default_instance();
    bool ParseFromString(const std::string& datos);
    bool ParseFromArray(const void* datos, int largo);
    bool ParseFromIstream(std::istream* entrada);
    bool _lee(detalle::Lector& lector, std::size_t fin);
    const std::string& qualifier() const;
    void set_qualifier(std::string valor);
    const std::string& name() const;
    void set_name(std::string valor);
    const std::string& lib() const;
    void set_lib(std::string valor);
    const std::string& member() const;
    void set_member(std::string valor);
 private:
    std::string m_qualifier{};
    std::string m_name{};
    std::string m_lib{};
    std::string m_member{};
};

class Decl {
 public:
    Decl();
    Decl(const Decl&);
    Decl& operator=(const Decl&);
    Decl(Decl&&) noexcept;
    Decl& operator=(Decl&&) noexcept;
    ~Decl();
    static const Decl& default_instance();
    bool ParseFromString(const std::string& datos);
    bool ParseFromArray(const void* datos, int largo);
    bool ParseFromIstream(std::istream* entrada);
    bool _lee(detalle::Lector& lector, std::size_t fin);
    enum NodeCase : int {
        kFunction = 10,
        kStructDecl = 11,
        kEnumDecl = 12,
        kExternBlock = 13,
        kStatement = 14,
        kImportDirective = 15,
        kExportDirective = 16,
        kFromDirective = 17,
        kTestDecl = 18,
        NODE_NOT_SET = 0,
    };
    NodeCase node_case() const;
    std::uint32_t ln() const;
    void set_ln(std::uint32_t valor);
    std::uint32_t col() const;
    void set_col(std::uint32_t valor);
    bool has_function() const;
    const FunctionDecl& function() const;
    FunctionDecl* mutable_function();
    bool has_struct_decl() const;
    const StructDecl& struct_decl() const;
    StructDecl* mutable_struct_decl();
    bool has_enum_decl() const;
    const EnumDecl& enum_decl() const;
    EnumDecl* mutable_enum_decl();
    bool has_extern_block() const;
    const ExternBlock& extern_block() const;
    ExternBlock* mutable_extern_block();
    bool has_statement() const;
    const Stmt& statement() const;
    Stmt* mutable_statement();
    bool has_import_directive() const;
    const ImportDirective& import_directive() const;
    ImportDirective* mutable_import_directive();
    bool has_export_directive() const;
    const ExportDirective& export_directive() const;
    ExportDirective* mutable_export_directive();
    bool has_from_directive() const;
    const FromDirective& from_directive() const;
    FromDirective* mutable_from_directive();
    bool has_test_decl() const;
    const TestDecl& test_decl() const;
    TestDecl* mutable_test_decl();
 private:
    int node_caso_ = 0;
    std::uint32_t m_ln{};
    std::uint32_t m_col{};
    detalle::Caja<FunctionDecl> m_function;
    detalle::Caja<StructDecl> m_struct_decl;
    detalle::Caja<EnumDecl> m_enum_decl;
    detalle::Caja<ExternBlock> m_extern_block;
    detalle::Caja<Stmt> m_statement;
    detalle::Caja<ImportDirective> m_import_directive;
    detalle::Caja<ExportDirective> m_export_directive;
    detalle::Caja<FromDirective> m_from_directive;
    detalle::Caja<TestDecl> m_test_decl;
};

class TestDecl {
 public:
    TestDecl();
    TestDecl(const TestDecl&);
    TestDecl& operator=(const TestDecl&);
    TestDecl(TestDecl&&) noexcept;
    TestDecl& operator=(TestDecl&&) noexcept;
    ~TestDecl();
    static const TestDecl& default_instance();
    bool ParseFromString(const std::string& datos);
    bool ParseFromArray(const void* datos, int largo);
    bool ParseFromIstream(std::istream* entrada);
    bool _lee(detalle::Lector& lector, std::size_t fin);
    const std::string& name() const;
    void set_name(std::string valor);
    bool has_body() const;
    const Block& body() const;
    Block* mutable_body();
 private:
    std::string m_name{};
    detalle::Caja<Block> m_body;
};

class Parameter {
 public:
    Parameter();
    Parameter(const Parameter&);
    Parameter& operator=(const Parameter&);
    Parameter(Parameter&&) noexcept;
    Parameter& operator=(Parameter&&) noexcept;
    ~Parameter();
    static const Parameter& default_instance();
    bool ParseFromString(const std::string& datos);
    bool ParseFromArray(const void* datos, int largo);
    bool ParseFromIstream(std::istream* entrada);
    bool _lee(detalle::Lector& lector, std::size_t fin);
    const std::string& name() const;
    void set_name(std::string valor);
    std::uint32_t type_id() const;
    void set_type_id(std::uint32_t valor);
 private:
    std::string m_name{};
    std::uint32_t m_type_id{};
};

class FunctionDecl {
 public:
    FunctionDecl();
    FunctionDecl(const FunctionDecl&);
    FunctionDecl& operator=(const FunctionDecl&);
    FunctionDecl(FunctionDecl&&) noexcept;
    FunctionDecl& operator=(FunctionDecl&&) noexcept;
    ~FunctionDecl();
    static const FunctionDecl& default_instance();
    bool ParseFromString(const std::string& datos);
    bool ParseFromArray(const void* datos, int largo);
    bool ParseFromIstream(std::istream* entrada);
    bool _lee(detalle::Lector& lector, std::size_t fin);
    const std::string& name() const;
    void set_name(std::string valor);
    const std::vector<Parameter>& params() const;
    const Parameter& params(int i) const;
    int params_size() const;
    Parameter* add_params();
    std::uint32_t return_type_id() const;
    void set_return_type_id(std::uint32_t valor);
    bool has_body() const;
    const Block& body() const;
    Block* mutable_body();
    const std::string& dunder() const;
    void set_dunder(std::string valor);
    const std::string& decorator() const;
    void set_decorator(std::string valor);
    const std::vector<std::string>& type_params() const;
    const std::string& type_params(int i) const;
    int type_params_size() const;
 private:
    std::string m_name{};
    std::vector<Parameter> m_params;
    std::uint32_t m_return_type_id{};
    detalle::Caja<Block> m_body;
    std::string m_dunder{};
    std::string m_decorator{};
    std::vector<std::string> m_type_params;
};

class Field {
 public:
    Field();
    Field(const Field&);
    Field& operator=(const Field&);
    Field(Field&&) noexcept;
    Field& operator=(Field&&) noexcept;
    ~Field();
    static const Field& default_instance();
    bool ParseFromString(const std::string& datos);
    bool ParseFromArray(const void* datos, int largo);
    bool ParseFromIstream(std::istream* entrada);
    bool _lee(detalle::Lector& lector, std::size_t fin);
    const std::string& name() const;
    void set_name(std::string valor);
    std::uint32_t type_id() const;
    void set_type_id(std::uint32_t valor);
 private:
    std::string m_name{};
    std::uint32_t m_type_id{};
};

class StructDecl {
 public:
    StructDecl();
    StructDecl(const StructDecl&);
    StructDecl& operator=(const StructDecl&);
    StructDecl(StructDecl&&) noexcept;
    StructDecl& operator=(StructDecl&&) noexcept;
    ~StructDecl();
    static const StructDecl& default_instance();
    bool ParseFromString(const std::string& datos);
    bool ParseFromArray(const void* datos, int largo);
    bool ParseFromIstream(std::istream* entrada);
    bool _lee(detalle::Lector& lector, std::size_t fin);
    const std::string& name() const;
    void set_name(std::string valor);
    const std::vector<Field>& fields() const;
    const Field& fields(int i) const;
    int fields_size() const;
    Field* add_fields();
    const std::vector<std::string>& type_params() const;
    const std::string& type_params(int i) const;
    int type_params_size() const;
 private:
    std::string m_name{};
    std::vector<Field> m_fields;
    std::vector<std::string> m_type_params;
};

class EnumItem {
 public:
    EnumItem();
    EnumItem(const EnumItem&);
    EnumItem& operator=(const EnumItem&);
    EnumItem(EnumItem&&) noexcept;
    EnumItem& operator=(EnumItem&&) noexcept;
    ~EnumItem();
    static const EnumItem& default_instance();
    bool ParseFromString(const std::string& datos);
    bool ParseFromArray(const void* datos, int largo);
    bool ParseFromIstream(std::istream* entrada);
    bool _lee(detalle::Lector& lector, std::size_t fin);
    const std::string& name() const;
    void set_name(std::string valor);
    bool has_value() const;
    const Expr& value() const;
    Expr* mutable_value();
    const std::vector<std::uint32_t>& payload_type_ids() const;
    std::uint32_t payload_type_ids(int i) const;
    int payload_type_ids_size() const;
 private:
    std::string m_name{};
    detalle::Caja<Expr> m_value;
    std::vector<std::uint32_t> m_payload_type_ids;
};

class EnumDecl {
 public:
    EnumDecl();
    EnumDecl(const EnumDecl&);
    EnumDecl& operator=(const EnumDecl&);
    EnumDecl(EnumDecl&&) noexcept;
    EnumDecl& operator=(EnumDecl&&) noexcept;
    ~EnumDecl();
    static const EnumDecl& default_instance();
    bool ParseFromString(const std::string& datos);
    bool ParseFromArray(const void* datos, int largo);
    bool ParseFromIstream(std::istream* entrada);
    bool _lee(detalle::Lector& lector, std::size_t fin);
    const std::string& name() const;
    void set_name(std::string valor);
    const std::vector<EnumItem>& items() const;
    const EnumItem& items(int i) const;
    int items_size() const;
    EnumItem* add_items();
 private:
    std::string m_name{};
    std::vector<EnumItem> m_items;
};

class ExternBlock {
 public:
    ExternBlock();
    ExternBlock(const ExternBlock&);
    ExternBlock& operator=(const ExternBlock&);
    ExternBlock(ExternBlock&&) noexcept;
    ExternBlock& operator=(ExternBlock&&) noexcept;
    ~ExternBlock();
    static const ExternBlock& default_instance();
    bool ParseFromString(const std::string& datos);
    bool ParseFromArray(const void* datos, int largo);
    bool ParseFromIstream(std::istream* entrada);
    bool _lee(detalle::Lector& lector, std::size_t fin);
    const std::string& target() const;
    void set_target(std::string valor);
    const std::string& raw() const;
    void set_raw(std::string valor);
    const std::vector<std::string>& requires_() const;
    const std::string& requires_(int i) const;
    int requires_size() const;
 private:
    std::string m_target{};
    std::string m_raw{};
    std::vector<std::string> m_requires;
};

class ImportDirective {
 public:
    ImportDirective();
    ImportDirective(const ImportDirective&);
    ImportDirective& operator=(const ImportDirective&);
    ImportDirective(ImportDirective&&) noexcept;
    ImportDirective& operator=(ImportDirective&&) noexcept;
    ~ImportDirective();
    static const ImportDirective& default_instance();
    bool ParseFromString(const std::string& datos);
    bool ParseFromArray(const void* datos, int largo);
    bool ParseFromIstream(std::istream* entrada);
    bool _lee(detalle::Lector& lector, std::size_t fin);
    const std::string& lib() const;
    void set_lib(std::string valor);
    const std::string& alias() const;
    void set_alias(std::string valor);
    const std::string& unit() const;
    void set_unit(std::string valor);
    const std::string& binding() const;
    void set_binding(std::string valor);
 private:
    std::string m_lib{};
    std::string m_alias{};
    std::string m_unit{};
    std::string m_binding{};
};

class ExportDirective {
 public:
    ExportDirective();
    ExportDirective(const ExportDirective&);
    ExportDirective& operator=(const ExportDirective&);
    ExportDirective(ExportDirective&&) noexcept;
    ExportDirective& operator=(ExportDirective&&) noexcept;
    ~ExportDirective();
    static const ExportDirective& default_instance();
    bool ParseFromString(const std::string& datos);
    bool ParseFromArray(const void* datos, int largo);
    bool ParseFromIstream(std::istream* entrada);
    bool _lee(detalle::Lector& lector, std::size_t fin);
    const std::string& alias() const;
    void set_alias(std::string valor);
    bool package() const;
    void set_package(bool valor);
 private:
    std::string m_alias{};
    bool m_package{};
};

class FromDirective {
 public:
    FromDirective();
    FromDirective(const FromDirective&);
    FromDirective& operator=(const FromDirective&);
    FromDirective(FromDirective&&) noexcept;
    FromDirective& operator=(FromDirective&&) noexcept;
    ~FromDirective();
    static const FromDirective& default_instance();
    bool ParseFromString(const std::string& datos);
    bool ParseFromArray(const void* datos, int largo);
    bool ParseFromIstream(std::istream* entrada);
    bool _lee(detalle::Lector& lector, std::size_t fin);
    const std::string& lib() const;
    void set_lib(std::string valor);
    const std::string& name() const;
    void set_name(std::string valor);
    const std::string& alias() const;
    void set_alias(std::string valor);
    const std::string& unit() const;
    void set_unit(std::string valor);
 private:
    std::string m_lib{};
    std::string m_name{};
    std::string m_alias{};
    std::string m_unit{};
};

// --- definiciones: DESPUÉS de todas las clases, para que ningún contenedor se
// use con un tipo todavía incompleto (lo que C++ exige para vector y compañía)

inline Module::Module() = default;
inline Module::Module(const Module&) = default;
inline Module& Module::operator=(const Module&) = default;
inline Module::Module(Module&&) noexcept = default;
inline Module& Module::operator=(Module&&) noexcept = default;
inline Module::~Module() = default;
inline const Module& Module::default_instance() { static const Module vacio; return vacio; }
inline bool Module::ParseFromString(const std::string& datos) {
    return ParseFromArray(datos.data(), static_cast<int>(datos.size()));
}
inline bool Module::ParseFromArray(const void* datos, int largo) {
    *this = Module();
    detalle::Lector lector(static_cast<const unsigned char*>(datos),
                           static_cast<std::size_t>(largo));
    return _lee(lector, static_cast<std::size_t>(largo));
}
inline bool Module::ParseFromIstream(std::istream* entrada) {
    std::string datos((std::istreambuf_iterator<char>(*entrada)),
                      std::istreambuf_iterator<char>());
    if (entrada->bad()) return false;
    return ParseFromString(datos);
}
inline std::uint32_t Module::schema_version() const { return m_schema_version; }
inline void Module::set_schema_version(std::uint32_t valor) { m_schema_version = std::move(valor); }
inline const std::string& Module::source_file() const { return m_source_file; }
inline void Module::set_source_file(std::string valor) { m_source_file = std::move(valor); }
inline bool Module::has_symbols() const { return m_symbols.hay(); }
inline const SymbolTable& Module::symbols() const { return m_symbols.hay() ? m_symbols.valor() : SymbolTable::default_instance(); }
inline SymbolTable* Module::mutable_symbols() { return &m_symbols.crea(); }
inline const std::vector<Decl>& Module::items() const { return m_items; }
inline const Decl& Module::items(int i) const { return m_items.at(static_cast<std::size_t>(i)); }
inline int Module::items_size() const { return static_cast<int>(m_items.size()); }
inline Decl* Module::add_items() { return &m_items.emplace_back(); }
inline const std::vector<LibraryRef>& Module::libraries() const { return m_libraries; }
inline const LibraryRef& Module::libraries(int i) const { return m_libraries.at(static_cast<std::size_t>(i)); }
inline int Module::libraries_size() const { return static_cast<int>(m_libraries.size()); }
inline LibraryRef* Module::add_libraries() { return &m_libraries.emplace_back(); }
inline const std::vector<Type>& Module::types() const { return m_types; }
inline const Type& Module::types(int i) const { return m_types.at(static_cast<std::size_t>(i)); }
inline int Module::types_size() const { return static_cast<int>(m_types.size()); }
inline Type* Module::add_types() { return &m_types.emplace_back(); }
inline bool Module::_lee(detalle::Lector& lector, std::size_t fin) {
    while (lector.pos() < fin) {
        std::uint64_t etiqueta;
        if (!lector.varint(etiqueta)) return false;
        const int tipo = static_cast<int>(etiqueta & 7);
        switch (etiqueta >> 3) {
        case 1: {
            if (tipo != 0) { if (!lector.salta(tipo)) return false; break; }
            std::uint64_t v; if (!lector.varint(v)) return false; m_schema_version = static_cast<std::uint32_t>(v);
            break;
        }
        case 2: {
            if (tipo != 2) { if (!lector.salta(tipo)) return false; break; }
            if (!lector.texto(m_source_file, fin)) return false;
            break;
        }
        case 3: {
            if (tipo != 2) { if (!lector.salta(tipo)) return false; break; }
            std::size_t hasta;
            if (!lector.largo(hasta, fin)) return false;
            if (!m_symbols.crea()._lee(lector, hasta)) return false;
            break;
        }
        case 4: {
            if (tipo != 2) { if (!lector.salta(tipo)) return false; break; }
            std::size_t hasta;
            if (!lector.largo(hasta, fin)) return false;
            if (!m_items.emplace_back()._lee(lector, hasta)) return false;
            break;
        }
        case 5: {
            if (tipo != 2) { if (!lector.salta(tipo)) return false; break; }
            std::size_t hasta;
            if (!lector.largo(hasta, fin)) return false;
            if (!m_libraries.emplace_back()._lee(lector, hasta)) return false;
            break;
        }
        case 6: {
            if (tipo != 2) { if (!lector.salta(tipo)) return false; break; }
            std::size_t hasta;
            if (!lector.largo(hasta, fin)) return false;
            if (!m_types.emplace_back()._lee(lector, hasta)) return false;
            break;
        }
        default:
            if (!lector.salta(tipo)) return false;
        }
    }
    return lector.pos() == fin;
}

inline LibraryRef::LibraryRef() = default;
inline LibraryRef::LibraryRef(const LibraryRef&) = default;
inline LibraryRef& LibraryRef::operator=(const LibraryRef&) = default;
inline LibraryRef::LibraryRef(LibraryRef&&) noexcept = default;
inline LibraryRef& LibraryRef::operator=(LibraryRef&&) noexcept = default;
inline LibraryRef::~LibraryRef() = default;
inline const LibraryRef& LibraryRef::default_instance() { static const LibraryRef vacio; return vacio; }
inline bool LibraryRef::ParseFromString(const std::string& datos) {
    return ParseFromArray(datos.data(), static_cast<int>(datos.size()));
}
inline bool LibraryRef::ParseFromArray(const void* datos, int largo) {
    *this = LibraryRef();
    detalle::Lector lector(static_cast<const unsigned char*>(datos),
                           static_cast<std::size_t>(largo));
    return _lee(lector, static_cast<std::size_t>(largo));
}
inline bool LibraryRef::ParseFromIstream(std::istream* entrada) {
    std::string datos((std::istreambuf_iterator<char>(*entrada)),
                      std::istreambuf_iterator<char>());
    if (entrada->bad()) return false;
    return ParseFromString(datos);
}
inline const std::string& LibraryRef::alias() const { return m_alias; }
inline void LibraryRef::set_alias(std::string valor) { m_alias = std::move(valor); }
inline const std::string& LibraryRef::phir() const { return m_phir; }
inline void LibraryRef::set_phir(std::string valor) { m_phir = std::move(valor); }
inline bool LibraryRef::_lee(detalle::Lector& lector, std::size_t fin) {
    while (lector.pos() < fin) {
        std::uint64_t etiqueta;
        if (!lector.varint(etiqueta)) return false;
        const int tipo = static_cast<int>(etiqueta & 7);
        switch (etiqueta >> 3) {
        case 1: {
            if (tipo != 2) { if (!lector.salta(tipo)) return false; break; }
            if (!lector.texto(m_alias, fin)) return false;
            break;
        }
        case 2: {
            if (tipo != 2) { if (!lector.salta(tipo)) return false; break; }
            if (!lector.texto(m_phir, fin)) return false;
            break;
        }
        default:
            if (!lector.salta(tipo)) return false;
        }
    }
    return lector.pos() == fin;
}

inline Type::Type() = default;
inline Type::Type(const Type&) = default;
inline Type& Type::operator=(const Type&) = default;
inline Type::Type(Type&&) noexcept = default;
inline Type& Type::operator=(Type&&) noexcept = default;
inline Type::~Type() = default;
inline const Type& Type::default_instance() { static const Type vacio; return vacio; }
inline bool Type::ParseFromString(const std::string& datos) {
    return ParseFromArray(datos.data(), static_cast<int>(datos.size()));
}
inline bool Type::ParseFromArray(const void* datos, int largo) {
    *this = Type();
    detalle::Lector lector(static_cast<const unsigned char*>(datos),
                           static_cast<std::size_t>(largo));
    return _lee(lector, static_cast<std::size_t>(largo));
}
inline bool Type::ParseFromIstream(std::istream* entrada) {
    std::string datos((std::istreambuf_iterator<char>(*entrada)),
                      std::istreambuf_iterator<char>());
    if (entrada->bad()) return false;
    return ParseFromString(datos);
}
inline TypeKind Type::kind() const { return static_cast<TypeKind>(m_kind); }
inline void Type::set_kind(TypeKind valor) { m_kind = valor; }
inline const std::string& Type::name() const { return m_name; }
inline void Type::set_name(std::string valor) { m_name = std::move(valor); }
inline bool Type::has_inner() const { return m_inner.hay(); }
inline const Type& Type::inner() const { return m_inner.hay() ? m_inner.valor() : Type::default_instance(); }
inline Type* Type::mutable_inner() { return &m_inner.crea(); }
inline bool Type::mut() const { return m_mut; }
inline void Type::set_mut(bool valor) { m_mut = std::move(valor); }
inline const std::vector<Type>& Type::args() const { return m_args; }
inline const Type& Type::args(int i) const { return m_args.at(static_cast<std::size_t>(i)); }
inline int Type::args_size() const { return static_cast<int>(m_args.size()); }
inline Type* Type::add_args() { return &m_args.emplace_back(); }
inline bool Type::_lee(detalle::Lector& lector, std::size_t fin) {
    while (lector.pos() < fin) {
        std::uint64_t etiqueta;
        if (!lector.varint(etiqueta)) return false;
        const int tipo = static_cast<int>(etiqueta & 7);
        switch (etiqueta >> 3) {
        case 1: {
            if (tipo != 0) { if (!lector.salta(tipo)) return false; break; }
            std::uint64_t v; if (!lector.varint(v)) return false; m_kind = static_cast<int>(v);
            break;
        }
        case 2: {
            if (tipo != 2) { if (!lector.salta(tipo)) return false; break; }
            if (!lector.texto(m_name, fin)) return false;
            break;
        }
        case 3: {
            if (tipo != 2) { if (!lector.salta(tipo)) return false; break; }
            std::size_t hasta;
            if (!lector.largo(hasta, fin)) return false;
            if (!m_inner.crea()._lee(lector, hasta)) return false;
            break;
        }
        case 4: {
            if (tipo != 0) { if (!lector.salta(tipo)) return false; break; }
            std::uint64_t v; if (!lector.varint(v)) return false; m_mut = v != 0;
            break;
        }
        case 5: {
            if (tipo != 2) { if (!lector.salta(tipo)) return false; break; }
            std::size_t hasta;
            if (!lector.largo(hasta, fin)) return false;
            if (!m_args.emplace_back()._lee(lector, hasta)) return false;
            break;
        }
        default:
            if (!lector.salta(tipo)) return false;
        }
    }
    return lector.pos() == fin;
}

inline Symbol::Symbol() = default;
inline Symbol::Symbol(const Symbol&) = default;
inline Symbol& Symbol::operator=(const Symbol&) = default;
inline Symbol::Symbol(Symbol&&) noexcept = default;
inline Symbol& Symbol::operator=(Symbol&&) noexcept = default;
inline Symbol::~Symbol() = default;
inline const Symbol& Symbol::default_instance() { static const Symbol vacio; return vacio; }
inline bool Symbol::ParseFromString(const std::string& datos) {
    return ParseFromArray(datos.data(), static_cast<int>(datos.size()));
}
inline bool Symbol::ParseFromArray(const void* datos, int largo) {
    *this = Symbol();
    detalle::Lector lector(static_cast<const unsigned char*>(datos),
                           static_cast<std::size_t>(largo));
    return _lee(lector, static_cast<std::size_t>(largo));
}
inline bool Symbol::ParseFromIstream(std::istream* entrada) {
    std::string datos((std::istreambuf_iterator<char>(*entrada)),
                      std::istreambuf_iterator<char>());
    if (entrada->bad()) return false;
    return ParseFromString(datos);
}
inline const std::string& Symbol::name() const { return m_name; }
inline void Symbol::set_name(std::string valor) { m_name = std::move(valor); }
inline SymbolKind Symbol::kind() const { return static_cast<SymbolKind>(m_kind); }
inline void Symbol::set_kind(SymbolKind valor) { m_kind = valor; }
inline std::uint32_t Symbol::ln() const { return m_ln; }
inline void Symbol::set_ln(std::uint32_t valor) { m_ln = std::move(valor); }
inline std::uint32_t Symbol::col() const { return m_col; }
inline void Symbol::set_col(std::uint32_t valor) { m_col = std::move(valor); }
inline bool Symbol::has_type() const { return m_type.hay(); }
inline const Type& Symbol::type() const { return m_type.hay() ? m_type.valor() : Type::default_instance(); }
inline Type* Symbol::mutable_type() { return &m_type.crea(); }
inline bool Symbol::mutable_() const { return m_mutable; }
inline void Symbol::set_mutable(bool valor) { m_mutable = std::move(valor); }
inline std::uint32_t Symbol::moved_at() const { return m_moved_at; }
inline void Symbol::set_moved_at(std::uint32_t valor) { m_moved_at = std::move(valor); }
inline const std::vector<Type>& Symbol::param_types() const { return m_param_types; }
inline const Type& Symbol::param_types(int i) const { return m_param_types.at(static_cast<std::size_t>(i)); }
inline int Symbol::param_types_size() const { return static_cast<int>(m_param_types.size()); }
inline Type* Symbol::add_param_types() { return &m_param_types.emplace_back(); }
inline const detalle::Mapa<Symbol>& Symbol::members() const { return m_members; }
inline int Symbol::members_size() const { return static_cast<int>(m_members.size()); }
inline HookKind Symbol::hook_kind() const { return static_cast<HookKind>(m_hook_kind); }
inline void Symbol::set_hook_kind(HookKind valor) { m_hook_kind = valor; }
inline const std::string& Symbol::hook_owner() const { return m_hook_owner; }
inline void Symbol::set_hook_owner(std::string valor) { m_hook_owner = std::move(valor); }
inline const std::string& Symbol::hook_name() const { return m_hook_name; }
inline void Symbol::set_hook_name(std::string valor) { m_hook_name = std::move(valor); }
inline bool Symbol::_lee(detalle::Lector& lector, std::size_t fin) {
    while (lector.pos() < fin) {
        std::uint64_t etiqueta;
        if (!lector.varint(etiqueta)) return false;
        const int tipo = static_cast<int>(etiqueta & 7);
        switch (etiqueta >> 3) {
        case 1: {
            if (tipo != 2) { if (!lector.salta(tipo)) return false; break; }
            if (!lector.texto(m_name, fin)) return false;
            break;
        }
        case 2: {
            if (tipo != 0) { if (!lector.salta(tipo)) return false; break; }
            std::uint64_t v; if (!lector.varint(v)) return false; m_kind = static_cast<int>(v);
            break;
        }
        case 3: {
            if (tipo != 0) { if (!lector.salta(tipo)) return false; break; }
            std::uint64_t v; if (!lector.varint(v)) return false; m_ln = static_cast<std::uint32_t>(v);
            break;
        }
        case 4: {
            if (tipo != 0) { if (!lector.salta(tipo)) return false; break; }
            std::uint64_t v; if (!lector.varint(v)) return false; m_col = static_cast<std::uint32_t>(v);
            break;
        }
        case 5: {
            if (tipo != 2) { if (!lector.salta(tipo)) return false; break; }
            std::size_t hasta;
            if (!lector.largo(hasta, fin)) return false;
            if (!m_type.crea()._lee(lector, hasta)) return false;
            break;
        }
        case 6: {
            if (tipo != 0) { if (!lector.salta(tipo)) return false; break; }
            std::uint64_t v; if (!lector.varint(v)) return false; m_mutable = v != 0;
            break;
        }
        case 8: {
            if (tipo != 0) { if (!lector.salta(tipo)) return false; break; }
            std::uint64_t v; if (!lector.varint(v)) return false; m_moved_at = static_cast<std::uint32_t>(v);
            break;
        }
        case 9: {
            if (tipo != 2) { if (!lector.salta(tipo)) return false; break; }
            std::size_t hasta;
            if (!lector.largo(hasta, fin)) return false;
            if (!m_param_types.emplace_back()._lee(lector, hasta)) return false;
            break;
        }
        case 10: {
            if (tipo != 2) { if (!lector.salta(tipo)) return false; break; }
            std::size_t hasta;
            if (!lector.largo(hasta, fin)) return false;
            std::string clave;
            Symbol valor;
            while (lector.pos() < hasta) {
                std::uint64_t et;
                if (!lector.varint(et)) return false;
                const int ti = static_cast<int>(et & 7);
                if ((et >> 3) == 1 && ti == 2) { if (!lector.texto(clave, hasta)) return false; }
                else if ((et >> 3) == 2 && ti == 2) {
                    std::size_t h2;
                    if (!lector.largo(h2, hasta) || !valor._lee(lector, h2)) return false;
                }
                else if (!lector.salta(ti)) return false;
            }
            m_members.inserta(clave) = std::move(valor);
            break;
        }
        case 11: {
            if (tipo != 0) { if (!lector.salta(tipo)) return false; break; }
            std::uint64_t v; if (!lector.varint(v)) return false; m_hook_kind = static_cast<int>(v);
            break;
        }
        case 12: {
            if (tipo != 2) { if (!lector.salta(tipo)) return false; break; }
            if (!lector.texto(m_hook_owner, fin)) return false;
            break;
        }
        case 14: {
            if (tipo != 2) { if (!lector.salta(tipo)) return false; break; }
            if (!lector.texto(m_hook_name, fin)) return false;
            break;
        }
        default:
            if (!lector.salta(tipo)) return false;
        }
    }
    return lector.pos() == fin;
}

inline HookEntry::HookEntry() = default;
inline HookEntry::HookEntry(const HookEntry&) = default;
inline HookEntry& HookEntry::operator=(const HookEntry&) = default;
inline HookEntry::HookEntry(HookEntry&&) noexcept = default;
inline HookEntry& HookEntry::operator=(HookEntry&&) noexcept = default;
inline HookEntry::~HookEntry() = default;
inline const HookEntry& HookEntry::default_instance() { static const HookEntry vacio; return vacio; }
inline bool HookEntry::ParseFromString(const std::string& datos) {
    return ParseFromArray(datos.data(), static_cast<int>(datos.size()));
}
inline bool HookEntry::ParseFromArray(const void* datos, int largo) {
    *this = HookEntry();
    detalle::Lector lector(static_cast<const unsigned char*>(datos),
                           static_cast<std::size_t>(largo));
    return _lee(lector, static_cast<std::size_t>(largo));
}
inline bool HookEntry::ParseFromIstream(std::istream* entrada) {
    std::string datos((std::istreambuf_iterator<char>(*entrada)),
                      std::istreambuf_iterator<char>());
    if (entrada->bad()) return false;
    return ParseFromString(datos);
}
inline const std::string& HookEntry::owner_type() const { return m_owner_type; }
inline void HookEntry::set_owner_type(std::string valor) { m_owner_type = std::move(valor); }
inline HookKind HookEntry::kind() const { return static_cast<HookKind>(m_kind); }
inline void HookEntry::set_kind(HookKind valor) { m_kind = valor; }
inline bool HookEntry::has_symbol() const { return m_symbol.hay(); }
inline const Symbol& HookEntry::symbol() const { return m_symbol.hay() ? m_symbol.valor() : Symbol::default_instance(); }
inline Symbol* HookEntry::mutable_symbol() { return &m_symbol.crea(); }
inline const std::string& HookEntry::hook_name() const { return m_hook_name; }
inline void HookEntry::set_hook_name(std::string valor) { m_hook_name = std::move(valor); }
inline const std::string& HookEntry::extension() const { return m_extension; }
inline void HookEntry::set_extension(std::string valor) { m_extension = std::move(valor); }
inline bool HookEntry::_lee(detalle::Lector& lector, std::size_t fin) {
    while (lector.pos() < fin) {
        std::uint64_t etiqueta;
        if (!lector.varint(etiqueta)) return false;
        const int tipo = static_cast<int>(etiqueta & 7);
        switch (etiqueta >> 3) {
        case 1: {
            if (tipo != 2) { if (!lector.salta(tipo)) return false; break; }
            if (!lector.texto(m_owner_type, fin)) return false;
            break;
        }
        case 2: {
            if (tipo != 0) { if (!lector.salta(tipo)) return false; break; }
            std::uint64_t v; if (!lector.varint(v)) return false; m_kind = static_cast<int>(v);
            break;
        }
        case 3: {
            if (tipo != 2) { if (!lector.salta(tipo)) return false; break; }
            std::size_t hasta;
            if (!lector.largo(hasta, fin)) return false;
            if (!m_symbol.crea()._lee(lector, hasta)) return false;
            break;
        }
        case 4: {
            if (tipo != 2) { if (!lector.salta(tipo)) return false; break; }
            if (!lector.texto(m_hook_name, fin)) return false;
            break;
        }
        case 5: {
            if (tipo != 2) { if (!lector.salta(tipo)) return false; break; }
            if (!lector.texto(m_extension, fin)) return false;
            break;
        }
        default:
            if (!lector.salta(tipo)) return false;
        }
    }
    return lector.pos() == fin;
}

inline SymbolTable::SymbolTable() = default;
inline SymbolTable::SymbolTable(const SymbolTable&) = default;
inline SymbolTable& SymbolTable::operator=(const SymbolTable&) = default;
inline SymbolTable::SymbolTable(SymbolTable&&) noexcept = default;
inline SymbolTable& SymbolTable::operator=(SymbolTable&&) noexcept = default;
inline SymbolTable::~SymbolTable() = default;
inline const SymbolTable& SymbolTable::default_instance() { static const SymbolTable vacio; return vacio; }
inline bool SymbolTable::ParseFromString(const std::string& datos) {
    return ParseFromArray(datos.data(), static_cast<int>(datos.size()));
}
inline bool SymbolTable::ParseFromArray(const void* datos, int largo) {
    *this = SymbolTable();
    detalle::Lector lector(static_cast<const unsigned char*>(datos),
                           static_cast<std::size_t>(largo));
    return _lee(lector, static_cast<std::size_t>(largo));
}
inline bool SymbolTable::ParseFromIstream(std::istream* entrada) {
    std::string datos((std::istreambuf_iterator<char>(*entrada)),
                      std::istreambuf_iterator<char>());
    if (entrada->bad()) return false;
    return ParseFromString(datos);
}
inline const detalle::Mapa<Symbol>& SymbolTable::types() const { return m_types; }
inline int SymbolTable::types_size() const { return static_cast<int>(m_types.size()); }
inline const detalle::Mapa<Symbol>& SymbolTable::values() const { return m_values; }
inline int SymbolTable::values_size() const { return static_cast<int>(m_values.size()); }
inline const std::vector<HookEntry>& SymbolTable::hooks() const { return m_hooks; }
inline const HookEntry& SymbolTable::hooks(int i) const { return m_hooks.at(static_cast<std::size_t>(i)); }
inline int SymbolTable::hooks_size() const { return static_cast<int>(m_hooks.size()); }
inline HookEntry* SymbolTable::add_hooks() { return &m_hooks.emplace_back(); }
inline const std::vector<Symbol>& SymbolTable::casts() const { return m_casts; }
inline const Symbol& SymbolTable::casts(int i) const { return m_casts.at(static_cast<std::size_t>(i)); }
inline int SymbolTable::casts_size() const { return static_cast<int>(m_casts.size()); }
inline Symbol* SymbolTable::add_casts() { return &m_casts.emplace_back(); }
inline bool SymbolTable::_lee(detalle::Lector& lector, std::size_t fin) {
    while (lector.pos() < fin) {
        std::uint64_t etiqueta;
        if (!lector.varint(etiqueta)) return false;
        const int tipo = static_cast<int>(etiqueta & 7);
        switch (etiqueta >> 3) {
        case 1: {
            if (tipo != 2) { if (!lector.salta(tipo)) return false; break; }
            std::size_t hasta;
            if (!lector.largo(hasta, fin)) return false;
            std::string clave;
            Symbol valor;
            while (lector.pos() < hasta) {
                std::uint64_t et;
                if (!lector.varint(et)) return false;
                const int ti = static_cast<int>(et & 7);
                if ((et >> 3) == 1 && ti == 2) { if (!lector.texto(clave, hasta)) return false; }
                else if ((et >> 3) == 2 && ti == 2) {
                    std::size_t h2;
                    if (!lector.largo(h2, hasta) || !valor._lee(lector, h2)) return false;
                }
                else if (!lector.salta(ti)) return false;
            }
            m_types.inserta(clave) = std::move(valor);
            break;
        }
        case 2: {
            if (tipo != 2) { if (!lector.salta(tipo)) return false; break; }
            std::size_t hasta;
            if (!lector.largo(hasta, fin)) return false;
            std::string clave;
            Symbol valor;
            while (lector.pos() < hasta) {
                std::uint64_t et;
                if (!lector.varint(et)) return false;
                const int ti = static_cast<int>(et & 7);
                if ((et >> 3) == 1 && ti == 2) { if (!lector.texto(clave, hasta)) return false; }
                else if ((et >> 3) == 2 && ti == 2) {
                    std::size_t h2;
                    if (!lector.largo(h2, hasta) || !valor._lee(lector, h2)) return false;
                }
                else if (!lector.salta(ti)) return false;
            }
            m_values.inserta(clave) = std::move(valor);
            break;
        }
        case 3: {
            if (tipo != 2) { if (!lector.salta(tipo)) return false; break; }
            std::size_t hasta;
            if (!lector.largo(hasta, fin)) return false;
            if (!m_hooks.emplace_back()._lee(lector, hasta)) return false;
            break;
        }
        case 4: {
            if (tipo != 2) { if (!lector.salta(tipo)) return false; break; }
            std::size_t hasta;
            if (!lector.largo(hasta, fin)) return false;
            if (!m_casts.emplace_back()._lee(lector, hasta)) return false;
            break;
        }
        default:
            if (!lector.salta(tipo)) return false;
        }
    }
    return lector.pos() == fin;
}

inline HookRef::HookRef() = default;
inline HookRef::HookRef(const HookRef&) = default;
inline HookRef& HookRef::operator=(const HookRef&) = default;
inline HookRef::HookRef(HookRef&&) noexcept = default;
inline HookRef& HookRef::operator=(HookRef&&) noexcept = default;
inline HookRef::~HookRef() = default;
inline const HookRef& HookRef::default_instance() { static const HookRef vacio; return vacio; }
inline bool HookRef::ParseFromString(const std::string& datos) {
    return ParseFromArray(datos.data(), static_cast<int>(datos.size()));
}
inline bool HookRef::ParseFromArray(const void* datos, int largo) {
    *this = HookRef();
    detalle::Lector lector(static_cast<const unsigned char*>(datos),
                           static_cast<std::size_t>(largo));
    return _lee(lector, static_cast<std::size_t>(largo));
}
inline bool HookRef::ParseFromIstream(std::istream* entrada) {
    std::string datos((std::istreambuf_iterator<char>(*entrada)),
                      std::istreambuf_iterator<char>());
    if (entrada->bad()) return false;
    return ParseFromString(datos);
}
inline const std::string& HookRef::owner_type() const { return m_owner_type; }
inline void HookRef::set_owner_type(std::string valor) { m_owner_type = std::move(valor); }
inline HookKind HookRef::kind() const { return static_cast<HookKind>(m_kind); }
inline void HookRef::set_kind(HookKind valor) { m_kind = valor; }
inline const std::string& HookRef::hook_name() const { return m_hook_name; }
inline void HookRef::set_hook_name(std::string valor) { m_hook_name = std::move(valor); }
inline bool HookRef::_lee(detalle::Lector& lector, std::size_t fin) {
    while (lector.pos() < fin) {
        std::uint64_t etiqueta;
        if (!lector.varint(etiqueta)) return false;
        const int tipo = static_cast<int>(etiqueta & 7);
        switch (etiqueta >> 3) {
        case 1: {
            if (tipo != 2) { if (!lector.salta(tipo)) return false; break; }
            if (!lector.texto(m_owner_type, fin)) return false;
            break;
        }
        case 2: {
            if (tipo != 0) { if (!lector.salta(tipo)) return false; break; }
            std::uint64_t v; if (!lector.varint(v)) return false; m_kind = static_cast<int>(v);
            break;
        }
        case 3: {
            if (tipo != 2) { if (!lector.salta(tipo)) return false; break; }
            if (!lector.texto(m_hook_name, fin)) return false;
            break;
        }
        default:
            if (!lector.salta(tipo)) return false;
        }
    }
    return lector.pos() == fin;
}

inline Expr::Expr() = default;
inline Expr::Expr(const Expr&) = default;
inline Expr& Expr::operator=(const Expr&) = default;
inline Expr::Expr(Expr&&) noexcept = default;
inline Expr& Expr::operator=(Expr&&) noexcept = default;
inline Expr::~Expr() = default;
inline const Expr& Expr::default_instance() { static const Expr vacio; return vacio; }
inline bool Expr::ParseFromString(const std::string& datos) {
    return ParseFromArray(datos.data(), static_cast<int>(datos.size()));
}
inline bool Expr::ParseFromArray(const void* datos, int largo) {
    *this = Expr();
    detalle::Lector lector(static_cast<const unsigned char*>(datos),
                           static_cast<std::size_t>(largo));
    return _lee(lector, static_cast<std::size_t>(largo));
}
inline bool Expr::ParseFromIstream(std::istream* entrada) {
    std::string datos((std::istreambuf_iterator<char>(*entrada)),
                      std::istreambuf_iterator<char>());
    if (entrada->bad()) return false;
    return ParseFromString(datos);
}
inline Expr::NodeCase Expr::node_case() const { return static_cast<NodeCase>(node_caso_); }
inline std::uint32_t Expr::ln() const { return m_ln; }
inline void Expr::set_ln(std::uint32_t valor) { m_ln = std::move(valor); }
inline std::uint32_t Expr::col() const { return m_col; }
inline void Expr::set_col(std::uint32_t valor) { m_col = std::move(valor); }
inline std::uint32_t Expr::type_id() const { return m_type_id; }
inline void Expr::set_type_id(std::uint32_t valor) { m_type_id = std::move(valor); }
inline bool Expr::has_literal() const { return node_caso_ == kLiteral; }
inline const Literal& Expr::literal() const {
    return node_caso_ == kLiteral && m_literal.hay() ? m_literal.valor() : Literal::default_instance();
}
inline Literal* Expr::mutable_literal() { node_caso_ = kLiteral; return &m_literal.crea(); }
inline bool Expr::has_interp() const { return node_caso_ == kInterp; }
inline const InterpolatedString& Expr::interp() const {
    return node_caso_ == kInterp && m_interp.hay() ? m_interp.valor() : InterpolatedString::default_instance();
}
inline InterpolatedString* Expr::mutable_interp() { node_caso_ = kInterp; return &m_interp.crea(); }
inline bool Expr::has_identifier() const { return node_caso_ == kIdentifier; }
inline const Identifier& Expr::identifier() const {
    return node_caso_ == kIdentifier && m_identifier.hay() ? m_identifier.valor() : Identifier::default_instance();
}
inline Identifier* Expr::mutable_identifier() { node_caso_ = kIdentifier; return &m_identifier.crea(); }
inline bool Expr::has_unary() const { return node_caso_ == kUnary; }
inline const UnaryOp& Expr::unary() const {
    return node_caso_ == kUnary && m_unary.hay() ? m_unary.valor() : UnaryOp::default_instance();
}
inline UnaryOp* Expr::mutable_unary() { node_caso_ = kUnary; return &m_unary.crea(); }
inline bool Expr::has_binary() const { return node_caso_ == kBinary; }
inline const BinaryOp& Expr::binary() const {
    return node_caso_ == kBinary && m_binary.hay() ? m_binary.valor() : BinaryOp::default_instance();
}
inline BinaryOp* Expr::mutable_binary() { node_caso_ = kBinary; return &m_binary.crea(); }
inline bool Expr::has_assignment() const { return node_caso_ == kAssignment; }
inline const Assignment& Expr::assignment() const {
    return node_caso_ == kAssignment && m_assignment.hay() ? m_assignment.valor() : Assignment::default_instance();
}
inline Assignment* Expr::mutable_assignment() { node_caso_ = kAssignment; return &m_assignment.crea(); }
inline bool Expr::has_call() const { return node_caso_ == kCall; }
inline const Call& Expr::call() const {
    return node_caso_ == kCall && m_call.hay() ? m_call.valor() : Call::default_instance();
}
inline Call* Expr::mutable_call() { node_caso_ = kCall; return &m_call.crea(); }
inline bool Expr::has_index() const { return node_caso_ == kIndex; }
inline const Index& Expr::index() const {
    return node_caso_ == kIndex && m_index.hay() ? m_index.valor() : Index::default_instance();
}
inline Index* Expr::mutable_index() { node_caso_ = kIndex; return &m_index.crea(); }
inline bool Expr::has_member() const { return node_caso_ == kMember; }
inline const MemberAccess& Expr::member() const {
    return node_caso_ == kMember && m_member.hay() ? m_member.valor() : MemberAccess::default_instance();
}
inline MemberAccess* Expr::mutable_member() { node_caso_ = kMember; return &m_member.crea(); }
inline bool Expr::has_sizeof_() const { return node_caso_ == kSizeof; }
inline const SizeofExpr& Expr::sizeof_() const {
    return node_caso_ == kSizeof && m_sizeof.hay() ? m_sizeof.valor() : SizeofExpr::default_instance();
}
inline SizeofExpr* Expr::mutable_sizeof_() { node_caso_ = kSizeof; return &m_sizeof.crea(); }
inline bool Expr::has_addr_of() const { return node_caso_ == kAddrOf; }
inline const AddrOf& Expr::addr_of() const {
    return node_caso_ == kAddrOf && m_addr_of.hay() ? m_addr_of.valor() : AddrOf::default_instance();
}
inline AddrOf* Expr::mutable_addr_of() { node_caso_ = kAddrOf; return &m_addr_of.crea(); }
inline bool Expr::has_cast_expr() const { return node_caso_ == kCastExpr; }
inline const CastExpr& Expr::cast_expr() const {
    return node_caso_ == kCastExpr && m_cast_expr.hay() ? m_cast_expr.valor() : CastExpr::default_instance();
}
inline CastExpr* Expr::mutable_cast_expr() { node_caso_ = kCastExpr; return &m_cast_expr.crea(); }
inline bool Expr::has_struct_literal() const { return node_caso_ == kStructLiteral; }
inline const StructLiteral& Expr::struct_literal() const {
    return node_caso_ == kStructLiteral && m_struct_literal.hay() ? m_struct_literal.valor() : StructLiteral::default_instance();
}
inline StructLiteral* Expr::mutable_struct_literal() { node_caso_ = kStructLiteral; return &m_struct_literal.crea(); }
inline bool Expr::has_move_expr() const { return node_caso_ == kMoveExpr; }
inline const MoveExpr& Expr::move_expr() const {
    return node_caso_ == kMoveExpr && m_move_expr.hay() ? m_move_expr.valor() : MoveExpr::default_instance();
}
inline MoveExpr* Expr::mutable_move_expr() { node_caso_ = kMoveExpr; return &m_move_expr.crea(); }
inline bool Expr::_lee(detalle::Lector& lector, std::size_t fin) {
    while (lector.pos() < fin) {
        std::uint64_t etiqueta;
        if (!lector.varint(etiqueta)) return false;
        const int tipo = static_cast<int>(etiqueta & 7);
        switch (etiqueta >> 3) {
        case 1: {
            if (tipo != 0) { if (!lector.salta(tipo)) return false; break; }
            std::uint64_t v; if (!lector.varint(v)) return false; m_ln = static_cast<std::uint32_t>(v);
            break;
        }
        case 2: {
            if (tipo != 0) { if (!lector.salta(tipo)) return false; break; }
            std::uint64_t v; if (!lector.varint(v)) return false; m_col = static_cast<std::uint32_t>(v);
            break;
        }
        case 4: {
            if (tipo != 0) { if (!lector.salta(tipo)) return false; break; }
            std::uint64_t v; if (!lector.varint(v)) return false; m_type_id = static_cast<std::uint32_t>(v);
            break;
        }
        case 10: {
            if (tipo != 2) { if (!lector.salta(tipo)) return false; break; }
            std::size_t hasta;
            if (!lector.largo(hasta, fin)) return false;
            node_caso_ = kLiteral;
            if (!m_literal.crea()._lee(lector, hasta)) return false;
            break;
        }
        case 11: {
            if (tipo != 2) { if (!lector.salta(tipo)) return false; break; }
            std::size_t hasta;
            if (!lector.largo(hasta, fin)) return false;
            node_caso_ = kInterp;
            if (!m_interp.crea()._lee(lector, hasta)) return false;
            break;
        }
        case 12: {
            if (tipo != 2) { if (!lector.salta(tipo)) return false; break; }
            std::size_t hasta;
            if (!lector.largo(hasta, fin)) return false;
            node_caso_ = kIdentifier;
            if (!m_identifier.crea()._lee(lector, hasta)) return false;
            break;
        }
        case 13: {
            if (tipo != 2) { if (!lector.salta(tipo)) return false; break; }
            std::size_t hasta;
            if (!lector.largo(hasta, fin)) return false;
            node_caso_ = kUnary;
            if (!m_unary.crea()._lee(lector, hasta)) return false;
            break;
        }
        case 14: {
            if (tipo != 2) { if (!lector.salta(tipo)) return false; break; }
            std::size_t hasta;
            if (!lector.largo(hasta, fin)) return false;
            node_caso_ = kBinary;
            if (!m_binary.crea()._lee(lector, hasta)) return false;
            break;
        }
        case 15: {
            if (tipo != 2) { if (!lector.salta(tipo)) return false; break; }
            std::size_t hasta;
            if (!lector.largo(hasta, fin)) return false;
            node_caso_ = kAssignment;
            if (!m_assignment.crea()._lee(lector, hasta)) return false;
            break;
        }
        case 17: {
            if (tipo != 2) { if (!lector.salta(tipo)) return false; break; }
            std::size_t hasta;
            if (!lector.largo(hasta, fin)) return false;
            node_caso_ = kCall;
            if (!m_call.crea()._lee(lector, hasta)) return false;
            break;
        }
        case 18: {
            if (tipo != 2) { if (!lector.salta(tipo)) return false; break; }
            std::size_t hasta;
            if (!lector.largo(hasta, fin)) return false;
            node_caso_ = kIndex;
            if (!m_index.crea()._lee(lector, hasta)) return false;
            break;
        }
        case 19: {
            if (tipo != 2) { if (!lector.salta(tipo)) return false; break; }
            std::size_t hasta;
            if (!lector.largo(hasta, fin)) return false;
            node_caso_ = kMember;
            if (!m_member.crea()._lee(lector, hasta)) return false;
            break;
        }
        case 22: {
            if (tipo != 2) { if (!lector.salta(tipo)) return false; break; }
            std::size_t hasta;
            if (!lector.largo(hasta, fin)) return false;
            node_caso_ = kSizeof;
            if (!m_sizeof.crea()._lee(lector, hasta)) return false;
            break;
        }
        case 23: {
            if (tipo != 2) { if (!lector.salta(tipo)) return false; break; }
            std::size_t hasta;
            if (!lector.largo(hasta, fin)) return false;
            node_caso_ = kAddrOf;
            if (!m_addr_of.crea()._lee(lector, hasta)) return false;
            break;
        }
        case 24: {
            if (tipo != 2) { if (!lector.salta(tipo)) return false; break; }
            std::size_t hasta;
            if (!lector.largo(hasta, fin)) return false;
            node_caso_ = kCastExpr;
            if (!m_cast_expr.crea()._lee(lector, hasta)) return false;
            break;
        }
        case 25: {
            if (tipo != 2) { if (!lector.salta(tipo)) return false; break; }
            std::size_t hasta;
            if (!lector.largo(hasta, fin)) return false;
            node_caso_ = kStructLiteral;
            if (!m_struct_literal.crea()._lee(lector, hasta)) return false;
            break;
        }
        case 26: {
            if (tipo != 2) { if (!lector.salta(tipo)) return false; break; }
            std::size_t hasta;
            if (!lector.largo(hasta, fin)) return false;
            node_caso_ = kMoveExpr;
            if (!m_move_expr.crea()._lee(lector, hasta)) return false;
            break;
        }
        default:
            if (!lector.salta(tipo)) return false;
        }
    }
    return lector.pos() == fin;
}

inline Literal::Literal() = default;
inline Literal::Literal(const Literal&) = default;
inline Literal& Literal::operator=(const Literal&) = default;
inline Literal::Literal(Literal&&) noexcept = default;
inline Literal& Literal::operator=(Literal&&) noexcept = default;
inline Literal::~Literal() = default;
inline const Literal& Literal::default_instance() { static const Literal vacio; return vacio; }
inline bool Literal::ParseFromString(const std::string& datos) {
    return ParseFromArray(datos.data(), static_cast<int>(datos.size()));
}
inline bool Literal::ParseFromArray(const void* datos, int largo) {
    *this = Literal();
    detalle::Lector lector(static_cast<const unsigned char*>(datos),
                           static_cast<std::size_t>(largo));
    return _lee(lector, static_cast<std::size_t>(largo));
}
inline bool Literal::ParseFromIstream(std::istream* entrada) {
    std::string datos((std::istreambuf_iterator<char>(*entrada)),
                      std::istreambuf_iterator<char>());
    if (entrada->bad()) return false;
    return ParseFromString(datos);
}
inline Literal::ValueCase Literal::value_case() const { return static_cast<ValueCase>(value_caso_); }
inline const std::string& Literal::kind() const { return m_kind; }
inline void Literal::set_kind(std::string valor) { m_kind = std::move(valor); }
inline bool Literal::has_int_value() const { return value_caso_ == kIntValue; }
inline std::int64_t Literal::int_value() const { return value_caso_ == kIntValue ? m_int_value : std::int64_t{}; }
inline void Literal::set_int_value(std::int64_t valor) { value_caso_ = kIntValue; m_int_value = std::move(valor); }
inline bool Literal::has_float_value() const { return value_caso_ == kFloatValue; }
inline double Literal::float_value() const { return value_caso_ == kFloatValue ? m_float_value : double{}; }
inline void Literal::set_float_value(double valor) { value_caso_ = kFloatValue; m_float_value = std::move(valor); }
inline bool Literal::has_str_value() const { return value_caso_ == kStrValue; }
inline const std::string& Literal::str_value() const { static const std::string vacio; return value_caso_ == kStrValue ? m_str_value : vacio; }
inline void Literal::set_str_value(std::string valor) { value_caso_ = kStrValue; m_str_value = std::move(valor); }
inline bool Literal::has_bool_value() const { return value_caso_ == kBoolValue; }
inline bool Literal::bool_value() const { return value_caso_ == kBoolValue ? m_bool_value : bool{}; }
inline void Literal::set_bool_value(bool valor) { value_caso_ = kBoolValue; m_bool_value = std::move(valor); }
inline bool Literal::_lee(detalle::Lector& lector, std::size_t fin) {
    while (lector.pos() < fin) {
        std::uint64_t etiqueta;
        if (!lector.varint(etiqueta)) return false;
        const int tipo = static_cast<int>(etiqueta & 7);
        switch (etiqueta >> 3) {
        case 1: {
            if (tipo != 2) { if (!lector.salta(tipo)) return false; break; }
            if (!lector.texto(m_kind, fin)) return false;
            break;
        }
        case 2: {
            if (tipo != 0) { if (!lector.salta(tipo)) return false; break; }
            value_caso_ = kIntValue;
            std::uint64_t v; if (!lector.varint(v)) return false; m_int_value = static_cast<std::int64_t>(v);
            break;
        }
        case 3: {
            if (tipo != 1) { if (!lector.salta(tipo)) return false; break; }
            value_caso_ = kFloatValue;
            std::uint64_t bits; if (!lector.fijo64(bits)) return false; m_float_value = std::bit_cast<double>(bits);
            break;
        }
        case 4: {
            if (tipo != 2) { if (!lector.salta(tipo)) return false; break; }
            value_caso_ = kStrValue;
            if (!lector.texto(m_str_value, fin)) return false;
            break;
        }
        case 5: {
            if (tipo != 0) { if (!lector.salta(tipo)) return false; break; }
            value_caso_ = kBoolValue;
            std::uint64_t v; if (!lector.varint(v)) return false; m_bool_value = v != 0;
            break;
        }
        default:
            if (!lector.salta(tipo)) return false;
        }
    }
    return lector.pos() == fin;
}

inline InterpolatedString::InterpolatedString() = default;
inline InterpolatedString::InterpolatedString(const InterpolatedString&) = default;
inline InterpolatedString& InterpolatedString::operator=(const InterpolatedString&) = default;
inline InterpolatedString::InterpolatedString(InterpolatedString&&) noexcept = default;
inline InterpolatedString& InterpolatedString::operator=(InterpolatedString&&) noexcept = default;
inline InterpolatedString::~InterpolatedString() = default;
inline const InterpolatedString& InterpolatedString::default_instance() { static const InterpolatedString vacio; return vacio; }
inline bool InterpolatedString::ParseFromString(const std::string& datos) {
    return ParseFromArray(datos.data(), static_cast<int>(datos.size()));
}
inline bool InterpolatedString::ParseFromArray(const void* datos, int largo) {
    *this = InterpolatedString();
    detalle::Lector lector(static_cast<const unsigned char*>(datos),
                           static_cast<std::size_t>(largo));
    return _lee(lector, static_cast<std::size_t>(largo));
}
inline bool InterpolatedString::ParseFromIstream(std::istream* entrada) {
    std::string datos((std::istreambuf_iterator<char>(*entrada)),
                      std::istreambuf_iterator<char>());
    if (entrada->bad()) return false;
    return ParseFromString(datos);
}
inline const std::vector<InterpolatedString_Part>& InterpolatedString::parts() const { return m_parts; }
inline const InterpolatedString_Part& InterpolatedString::parts(int i) const { return m_parts.at(static_cast<std::size_t>(i)); }
inline int InterpolatedString::parts_size() const { return static_cast<int>(m_parts.size()); }
inline InterpolatedString_Part* InterpolatedString::add_parts() { return &m_parts.emplace_back(); }
inline bool InterpolatedString::_lee(detalle::Lector& lector, std::size_t fin) {
    while (lector.pos() < fin) {
        std::uint64_t etiqueta;
        if (!lector.varint(etiqueta)) return false;
        const int tipo = static_cast<int>(etiqueta & 7);
        switch (etiqueta >> 3) {
        case 1: {
            if (tipo != 2) { if (!lector.salta(tipo)) return false; break; }
            std::size_t hasta;
            if (!lector.largo(hasta, fin)) return false;
            if (!m_parts.emplace_back()._lee(lector, hasta)) return false;
            break;
        }
        default:
            if (!lector.salta(tipo)) return false;
        }
    }
    return lector.pos() == fin;
}

inline InterpolatedString_Part::InterpolatedString_Part() = default;
inline InterpolatedString_Part::InterpolatedString_Part(const InterpolatedString_Part&) = default;
inline InterpolatedString_Part& InterpolatedString_Part::operator=(const InterpolatedString_Part&) = default;
inline InterpolatedString_Part::InterpolatedString_Part(InterpolatedString_Part&&) noexcept = default;
inline InterpolatedString_Part& InterpolatedString_Part::operator=(InterpolatedString_Part&&) noexcept = default;
inline InterpolatedString_Part::~InterpolatedString_Part() = default;
inline const InterpolatedString_Part& InterpolatedString_Part::default_instance() { static const InterpolatedString_Part vacio; return vacio; }
inline bool InterpolatedString_Part::ParseFromString(const std::string& datos) {
    return ParseFromArray(datos.data(), static_cast<int>(datos.size()));
}
inline bool InterpolatedString_Part::ParseFromArray(const void* datos, int largo) {
    *this = InterpolatedString_Part();
    detalle::Lector lector(static_cast<const unsigned char*>(datos),
                           static_cast<std::size_t>(largo));
    return _lee(lector, static_cast<std::size_t>(largo));
}
inline bool InterpolatedString_Part::ParseFromIstream(std::istream* entrada) {
    std::string datos((std::istreambuf_iterator<char>(*entrada)),
                      std::istreambuf_iterator<char>());
    if (entrada->bad()) return false;
    return ParseFromString(datos);
}
inline InterpolatedString_Part::PartCase InterpolatedString_Part::part_case() const { return static_cast<PartCase>(part_caso_); }
inline bool InterpolatedString_Part::has_text() const { return part_caso_ == kText; }
inline const std::string& InterpolatedString_Part::text() const { static const std::string vacio; return part_caso_ == kText ? m_text : vacio; }
inline void InterpolatedString_Part::set_text(std::string valor) { part_caso_ = kText; m_text = std::move(valor); }
inline bool InterpolatedString_Part::has_expr() const { return part_caso_ == kExpr; }
inline const Expr& InterpolatedString_Part::expr() const {
    return part_caso_ == kExpr && m_expr.hay() ? m_expr.valor() : Expr::default_instance();
}
inline Expr* InterpolatedString_Part::mutable_expr() { part_caso_ = kExpr; return &m_expr.crea(); }
inline bool InterpolatedString_Part::repr() const { return m_repr; }
inline void InterpolatedString_Part::set_repr(bool valor) { m_repr = std::move(valor); }
inline const std::string& InterpolatedString_Part::spec() const { return m_spec; }
inline void InterpolatedString_Part::set_spec(std::string valor) { m_spec = std::move(valor); }
inline bool InterpolatedString_Part::_lee(detalle::Lector& lector, std::size_t fin) {
    while (lector.pos() < fin) {
        std::uint64_t etiqueta;
        if (!lector.varint(etiqueta)) return false;
        const int tipo = static_cast<int>(etiqueta & 7);
        switch (etiqueta >> 3) {
        case 1: {
            if (tipo != 2) { if (!lector.salta(tipo)) return false; break; }
            part_caso_ = kText;
            if (!lector.texto(m_text, fin)) return false;
            break;
        }
        case 2: {
            if (tipo != 2) { if (!lector.salta(tipo)) return false; break; }
            std::size_t hasta;
            if (!lector.largo(hasta, fin)) return false;
            part_caso_ = kExpr;
            if (!m_expr.crea()._lee(lector, hasta)) return false;
            break;
        }
        case 3: {
            if (tipo != 0) { if (!lector.salta(tipo)) return false; break; }
            std::uint64_t v; if (!lector.varint(v)) return false; m_repr = v != 0;
            break;
        }
        case 4: {
            if (tipo != 2) { if (!lector.salta(tipo)) return false; break; }
            if (!lector.texto(m_spec, fin)) return false;
            break;
        }
        default:
            if (!lector.salta(tipo)) return false;
        }
    }
    return lector.pos() == fin;
}

inline Identifier::Identifier() = default;
inline Identifier::Identifier(const Identifier&) = default;
inline Identifier& Identifier::operator=(const Identifier&) = default;
inline Identifier::Identifier(Identifier&&) noexcept = default;
inline Identifier& Identifier::operator=(Identifier&&) noexcept = default;
inline Identifier::~Identifier() = default;
inline const Identifier& Identifier::default_instance() { static const Identifier vacio; return vacio; }
inline bool Identifier::ParseFromString(const std::string& datos) {
    return ParseFromArray(datos.data(), static_cast<int>(datos.size()));
}
inline bool Identifier::ParseFromArray(const void* datos, int largo) {
    *this = Identifier();
    detalle::Lector lector(static_cast<const unsigned char*>(datos),
                           static_cast<std::size_t>(largo));
    return _lee(lector, static_cast<std::size_t>(largo));
}
inline bool Identifier::ParseFromIstream(std::istream* entrada) {
    std::string datos((std::istreambuf_iterator<char>(*entrada)),
                      std::istreambuf_iterator<char>());
    if (entrada->bad()) return false;
    return ParseFromString(datos);
}
inline const std::string& Identifier::name() const { return m_name; }
inline void Identifier::set_name(std::string valor) { m_name = std::move(valor); }
inline bool Identifier::_lee(detalle::Lector& lector, std::size_t fin) {
    while (lector.pos() < fin) {
        std::uint64_t etiqueta;
        if (!lector.varint(etiqueta)) return false;
        const int tipo = static_cast<int>(etiqueta & 7);
        switch (etiqueta >> 3) {
        case 1: {
            if (tipo != 2) { if (!lector.salta(tipo)) return false; break; }
            if (!lector.texto(m_name, fin)) return false;
            break;
        }
        default:
            if (!lector.salta(tipo)) return false;
        }
    }
    return lector.pos() == fin;
}

inline UnaryOp::UnaryOp() = default;
inline UnaryOp::UnaryOp(const UnaryOp&) = default;
inline UnaryOp& UnaryOp::operator=(const UnaryOp&) = default;
inline UnaryOp::UnaryOp(UnaryOp&&) noexcept = default;
inline UnaryOp& UnaryOp::operator=(UnaryOp&&) noexcept = default;
inline UnaryOp::~UnaryOp() = default;
inline const UnaryOp& UnaryOp::default_instance() { static const UnaryOp vacio; return vacio; }
inline bool UnaryOp::ParseFromString(const std::string& datos) {
    return ParseFromArray(datos.data(), static_cast<int>(datos.size()));
}
inline bool UnaryOp::ParseFromArray(const void* datos, int largo) {
    *this = UnaryOp();
    detalle::Lector lector(static_cast<const unsigned char*>(datos),
                           static_cast<std::size_t>(largo));
    return _lee(lector, static_cast<std::size_t>(largo));
}
inline bool UnaryOp::ParseFromIstream(std::istream* entrada) {
    std::string datos((std::istreambuf_iterator<char>(*entrada)),
                      std::istreambuf_iterator<char>());
    if (entrada->bad()) return false;
    return ParseFromString(datos);
}
inline const std::string& UnaryOp::op() const { return m_op; }
inline void UnaryOp::set_op(std::string valor) { m_op = std::move(valor); }
inline bool UnaryOp::has_operand() const { return m_operand.hay(); }
inline const Expr& UnaryOp::operand() const { return m_operand.hay() ? m_operand.valor() : Expr::default_instance(); }
inline Expr* UnaryOp::mutable_operand() { return &m_operand.crea(); }
inline bool UnaryOp::_lee(detalle::Lector& lector, std::size_t fin) {
    while (lector.pos() < fin) {
        std::uint64_t etiqueta;
        if (!lector.varint(etiqueta)) return false;
        const int tipo = static_cast<int>(etiqueta & 7);
        switch (etiqueta >> 3) {
        case 1: {
            if (tipo != 2) { if (!lector.salta(tipo)) return false; break; }
            if (!lector.texto(m_op, fin)) return false;
            break;
        }
        case 2: {
            if (tipo != 2) { if (!lector.salta(tipo)) return false; break; }
            std::size_t hasta;
            if (!lector.largo(hasta, fin)) return false;
            if (!m_operand.crea()._lee(lector, hasta)) return false;
            break;
        }
        default:
            if (!lector.salta(tipo)) return false;
        }
    }
    return lector.pos() == fin;
}

inline BinaryOp::BinaryOp() = default;
inline BinaryOp::BinaryOp(const BinaryOp&) = default;
inline BinaryOp& BinaryOp::operator=(const BinaryOp&) = default;
inline BinaryOp::BinaryOp(BinaryOp&&) noexcept = default;
inline BinaryOp& BinaryOp::operator=(BinaryOp&&) noexcept = default;
inline BinaryOp::~BinaryOp() = default;
inline const BinaryOp& BinaryOp::default_instance() { static const BinaryOp vacio; return vacio; }
inline bool BinaryOp::ParseFromString(const std::string& datos) {
    return ParseFromArray(datos.data(), static_cast<int>(datos.size()));
}
inline bool BinaryOp::ParseFromArray(const void* datos, int largo) {
    *this = BinaryOp();
    detalle::Lector lector(static_cast<const unsigned char*>(datos),
                           static_cast<std::size_t>(largo));
    return _lee(lector, static_cast<std::size_t>(largo));
}
inline bool BinaryOp::ParseFromIstream(std::istream* entrada) {
    std::string datos((std::istreambuf_iterator<char>(*entrada)),
                      std::istreambuf_iterator<char>());
    if (entrada->bad()) return false;
    return ParseFromString(datos);
}
inline const std::string& BinaryOp::op() const { return m_op; }
inline void BinaryOp::set_op(std::string valor) { m_op = std::move(valor); }
inline bool BinaryOp::has_left() const { return m_left.hay(); }
inline const Expr& BinaryOp::left() const { return m_left.hay() ? m_left.valor() : Expr::default_instance(); }
inline Expr* BinaryOp::mutable_left() { return &m_left.crea(); }
inline bool BinaryOp::has_right() const { return m_right.hay(); }
inline const Expr& BinaryOp::right() const { return m_right.hay() ? m_right.valor() : Expr::default_instance(); }
inline Expr* BinaryOp::mutable_right() { return &m_right.crea(); }
inline bool BinaryOp::_lee(detalle::Lector& lector, std::size_t fin) {
    while (lector.pos() < fin) {
        std::uint64_t etiqueta;
        if (!lector.varint(etiqueta)) return false;
        const int tipo = static_cast<int>(etiqueta & 7);
        switch (etiqueta >> 3) {
        case 1: {
            if (tipo != 2) { if (!lector.salta(tipo)) return false; break; }
            if (!lector.texto(m_op, fin)) return false;
            break;
        }
        case 2: {
            if (tipo != 2) { if (!lector.salta(tipo)) return false; break; }
            std::size_t hasta;
            if (!lector.largo(hasta, fin)) return false;
            if (!m_left.crea()._lee(lector, hasta)) return false;
            break;
        }
        case 3: {
            if (tipo != 2) { if (!lector.salta(tipo)) return false; break; }
            std::size_t hasta;
            if (!lector.largo(hasta, fin)) return false;
            if (!m_right.crea()._lee(lector, hasta)) return false;
            break;
        }
        default:
            if (!lector.salta(tipo)) return false;
        }
    }
    return lector.pos() == fin;
}

inline Assignment::Assignment() = default;
inline Assignment::Assignment(const Assignment&) = default;
inline Assignment& Assignment::operator=(const Assignment&) = default;
inline Assignment::Assignment(Assignment&&) noexcept = default;
inline Assignment& Assignment::operator=(Assignment&&) noexcept = default;
inline Assignment::~Assignment() = default;
inline const Assignment& Assignment::default_instance() { static const Assignment vacio; return vacio; }
inline bool Assignment::ParseFromString(const std::string& datos) {
    return ParseFromArray(datos.data(), static_cast<int>(datos.size()));
}
inline bool Assignment::ParseFromArray(const void* datos, int largo) {
    *this = Assignment();
    detalle::Lector lector(static_cast<const unsigned char*>(datos),
                           static_cast<std::size_t>(largo));
    return _lee(lector, static_cast<std::size_t>(largo));
}
inline bool Assignment::ParseFromIstream(std::istream* entrada) {
    std::string datos((std::istreambuf_iterator<char>(*entrada)),
                      std::istreambuf_iterator<char>());
    if (entrada->bad()) return false;
    return ParseFromString(datos);
}
inline bool Assignment::has_target() const { return m_target.hay(); }
inline const Expr& Assignment::target() const { return m_target.hay() ? m_target.valor() : Expr::default_instance(); }
inline Expr* Assignment::mutable_target() { return &m_target.crea(); }
inline bool Assignment::has_value() const { return m_value.hay(); }
inline const Expr& Assignment::value() const { return m_value.hay() ? m_value.valor() : Expr::default_instance(); }
inline Expr* Assignment::mutable_value() { return &m_value.crea(); }
inline bool Assignment::drops_old() const { return m_drops_old; }
inline void Assignment::set_drops_old(bool valor) { m_drops_old = std::move(valor); }
inline bool Assignment::_lee(detalle::Lector& lector, std::size_t fin) {
    while (lector.pos() < fin) {
        std::uint64_t etiqueta;
        if (!lector.varint(etiqueta)) return false;
        const int tipo = static_cast<int>(etiqueta & 7);
        switch (etiqueta >> 3) {
        case 1: {
            if (tipo != 2) { if (!lector.salta(tipo)) return false; break; }
            std::size_t hasta;
            if (!lector.largo(hasta, fin)) return false;
            if (!m_target.crea()._lee(lector, hasta)) return false;
            break;
        }
        case 2: {
            if (tipo != 2) { if (!lector.salta(tipo)) return false; break; }
            std::size_t hasta;
            if (!lector.largo(hasta, fin)) return false;
            if (!m_value.crea()._lee(lector, hasta)) return false;
            break;
        }
        case 3: {
            if (tipo != 0) { if (!lector.salta(tipo)) return false; break; }
            std::uint64_t v; if (!lector.varint(v)) return false; m_drops_old = v != 0;
            break;
        }
        default:
            if (!lector.salta(tipo)) return false;
        }
    }
    return lector.pos() == fin;
}

inline AddrOf::AddrOf() = default;
inline AddrOf::AddrOf(const AddrOf&) = default;
inline AddrOf& AddrOf::operator=(const AddrOf&) = default;
inline AddrOf::AddrOf(AddrOf&&) noexcept = default;
inline AddrOf& AddrOf::operator=(AddrOf&&) noexcept = default;
inline AddrOf::~AddrOf() = default;
inline const AddrOf& AddrOf::default_instance() { static const AddrOf vacio; return vacio; }
inline bool AddrOf::ParseFromString(const std::string& datos) {
    return ParseFromArray(datos.data(), static_cast<int>(datos.size()));
}
inline bool AddrOf::ParseFromArray(const void* datos, int largo) {
    *this = AddrOf();
    detalle::Lector lector(static_cast<const unsigned char*>(datos),
                           static_cast<std::size_t>(largo));
    return _lee(lector, static_cast<std::size_t>(largo));
}
inline bool AddrOf::ParseFromIstream(std::istream* entrada) {
    std::string datos((std::istreambuf_iterator<char>(*entrada)),
                      std::istreambuf_iterator<char>());
    if (entrada->bad()) return false;
    return ParseFromString(datos);
}
inline bool AddrOf::has_operand() const { return m_operand.hay(); }
inline const Expr& AddrOf::operand() const { return m_operand.hay() ? m_operand.valor() : Expr::default_instance(); }
inline Expr* AddrOf::mutable_operand() { return &m_operand.crea(); }
inline bool AddrOf::mut() const { return m_mut; }
inline void AddrOf::set_mut(bool valor) { m_mut = std::move(valor); }
inline bool AddrOf::_lee(detalle::Lector& lector, std::size_t fin) {
    while (lector.pos() < fin) {
        std::uint64_t etiqueta;
        if (!lector.varint(etiqueta)) return false;
        const int tipo = static_cast<int>(etiqueta & 7);
        switch (etiqueta >> 3) {
        case 1: {
            if (tipo != 2) { if (!lector.salta(tipo)) return false; break; }
            std::size_t hasta;
            if (!lector.largo(hasta, fin)) return false;
            if (!m_operand.crea()._lee(lector, hasta)) return false;
            break;
        }
        case 2: {
            if (tipo != 0) { if (!lector.salta(tipo)) return false; break; }
            std::uint64_t v; if (!lector.varint(v)) return false; m_mut = v != 0;
            break;
        }
        default:
            if (!lector.salta(tipo)) return false;
        }
    }
    return lector.pos() == fin;
}

inline Call::Call() = default;
inline Call::Call(const Call&) = default;
inline Call& Call::operator=(const Call&) = default;
inline Call::Call(Call&&) noexcept = default;
inline Call& Call::operator=(Call&&) noexcept = default;
inline Call::~Call() = default;
inline const Call& Call::default_instance() { static const Call vacio; return vacio; }
inline bool Call::ParseFromString(const std::string& datos) {
    return ParseFromArray(datos.data(), static_cast<int>(datos.size()));
}
inline bool Call::ParseFromArray(const void* datos, int largo) {
    *this = Call();
    detalle::Lector lector(static_cast<const unsigned char*>(datos),
                           static_cast<std::size_t>(largo));
    return _lee(lector, static_cast<std::size_t>(largo));
}
inline bool Call::ParseFromIstream(std::istream* entrada) {
    std::string datos((std::istreambuf_iterator<char>(*entrada)),
                      std::istreambuf_iterator<char>());
    if (entrada->bad()) return false;
    return ParseFromString(datos);
}
inline bool Call::has_callee() const { return m_callee.hay(); }
inline const Expr& Call::callee() const { return m_callee.hay() ? m_callee.valor() : Expr::default_instance(); }
inline Expr* Call::mutable_callee() { return &m_callee.crea(); }
inline const std::vector<Expr>& Call::args() const { return m_args; }
inline const Expr& Call::args(int i) const { return m_args.at(static_cast<std::size_t>(i)); }
inline int Call::args_size() const { return static_cast<int>(m_args.size()); }
inline Expr* Call::add_args() { return &m_args.emplace_back(); }
inline bool Call::has_hook() const { return m_hook.hay(); }
inline const HookRef& Call::hook() const { return m_hook.hay() ? m_hook.valor() : HookRef::default_instance(); }
inline HookRef* Call::mutable_hook() { return &m_hook.crea(); }
inline bool Call::has_temp_drop() const { return m_temp_drop.hay(); }
inline const HookRef& Call::temp_drop() const { return m_temp_drop.hay() ? m_temp_drop.valor() : HookRef::default_instance(); }
inline HookRef* Call::mutable_temp_drop() { return &m_temp_drop.crea(); }
inline bool Call::temp_by_type() const { return m_temp_by_type; }
inline void Call::set_temp_by_type(bool valor) { m_temp_by_type = std::move(valor); }
inline bool Call::_lee(detalle::Lector& lector, std::size_t fin) {
    while (lector.pos() < fin) {
        std::uint64_t etiqueta;
        if (!lector.varint(etiqueta)) return false;
        const int tipo = static_cast<int>(etiqueta & 7);
        switch (etiqueta >> 3) {
        case 1: {
            if (tipo != 2) { if (!lector.salta(tipo)) return false; break; }
            std::size_t hasta;
            if (!lector.largo(hasta, fin)) return false;
            if (!m_callee.crea()._lee(lector, hasta)) return false;
            break;
        }
        case 2: {
            if (tipo != 2) { if (!lector.salta(tipo)) return false; break; }
            std::size_t hasta;
            if (!lector.largo(hasta, fin)) return false;
            if (!m_args.emplace_back()._lee(lector, hasta)) return false;
            break;
        }
        case 3: {
            if (tipo != 2) { if (!lector.salta(tipo)) return false; break; }
            std::size_t hasta;
            if (!lector.largo(hasta, fin)) return false;
            if (!m_hook.crea()._lee(lector, hasta)) return false;
            break;
        }
        case 4: {
            if (tipo != 2) { if (!lector.salta(tipo)) return false; break; }
            std::size_t hasta;
            if (!lector.largo(hasta, fin)) return false;
            if (!m_temp_drop.crea()._lee(lector, hasta)) return false;
            break;
        }
        case 5: {
            if (tipo != 0) { if (!lector.salta(tipo)) return false; break; }
            std::uint64_t v; if (!lector.varint(v)) return false; m_temp_by_type = v != 0;
            break;
        }
        default:
            if (!lector.salta(tipo)) return false;
        }
    }
    return lector.pos() == fin;
}

inline MoveExpr::MoveExpr() = default;
inline MoveExpr::MoveExpr(const MoveExpr&) = default;
inline MoveExpr& MoveExpr::operator=(const MoveExpr&) = default;
inline MoveExpr::MoveExpr(MoveExpr&&) noexcept = default;
inline MoveExpr& MoveExpr::operator=(MoveExpr&&) noexcept = default;
inline MoveExpr::~MoveExpr() = default;
inline const MoveExpr& MoveExpr::default_instance() { static const MoveExpr vacio; return vacio; }
inline bool MoveExpr::ParseFromString(const std::string& datos) {
    return ParseFromArray(datos.data(), static_cast<int>(datos.size()));
}
inline bool MoveExpr::ParseFromArray(const void* datos, int largo) {
    *this = MoveExpr();
    detalle::Lector lector(static_cast<const unsigned char*>(datos),
                           static_cast<std::size_t>(largo));
    return _lee(lector, static_cast<std::size_t>(largo));
}
inline bool MoveExpr::ParseFromIstream(std::istream* entrada) {
    std::string datos((std::istreambuf_iterator<char>(*entrada)),
                      std::istreambuf_iterator<char>());
    if (entrada->bad()) return false;
    return ParseFromString(datos);
}
inline bool MoveExpr::has_operand() const { return m_operand.hay(); }
inline const Expr& MoveExpr::operand() const { return m_operand.hay() ? m_operand.valor() : Expr::default_instance(); }
inline Expr* MoveExpr::mutable_operand() { return &m_operand.crea(); }
inline bool MoveExpr::_lee(detalle::Lector& lector, std::size_t fin) {
    while (lector.pos() < fin) {
        std::uint64_t etiqueta;
        if (!lector.varint(etiqueta)) return false;
        const int tipo = static_cast<int>(etiqueta & 7);
        switch (etiqueta >> 3) {
        case 1: {
            if (tipo != 2) { if (!lector.salta(tipo)) return false; break; }
            std::size_t hasta;
            if (!lector.largo(hasta, fin)) return false;
            if (!m_operand.crea()._lee(lector, hasta)) return false;
            break;
        }
        default:
            if (!lector.salta(tipo)) return false;
        }
    }
    return lector.pos() == fin;
}

inline Index::Index() = default;
inline Index::Index(const Index&) = default;
inline Index& Index::operator=(const Index&) = default;
inline Index::Index(Index&&) noexcept = default;
inline Index& Index::operator=(Index&&) noexcept = default;
inline Index::~Index() = default;
inline const Index& Index::default_instance() { static const Index vacio; return vacio; }
inline bool Index::ParseFromString(const std::string& datos) {
    return ParseFromArray(datos.data(), static_cast<int>(datos.size()));
}
inline bool Index::ParseFromArray(const void* datos, int largo) {
    *this = Index();
    detalle::Lector lector(static_cast<const unsigned char*>(datos),
                           static_cast<std::size_t>(largo));
    return _lee(lector, static_cast<std::size_t>(largo));
}
inline bool Index::ParseFromIstream(std::istream* entrada) {
    std::string datos((std::istreambuf_iterator<char>(*entrada)),
                      std::istreambuf_iterator<char>());
    if (entrada->bad()) return false;
    return ParseFromString(datos);
}
inline bool Index::has_obj() const { return m_obj.hay(); }
inline const Expr& Index::obj() const { return m_obj.hay() ? m_obj.valor() : Expr::default_instance(); }
inline Expr* Index::mutable_obj() { return &m_obj.crea(); }
inline bool Index::has_index() const { return m_index.hay(); }
inline const Expr& Index::index() const { return m_index.hay() ? m_index.valor() : Expr::default_instance(); }
inline Expr* Index::mutable_index() { return &m_index.crea(); }
inline bool Index::_lee(detalle::Lector& lector, std::size_t fin) {
    while (lector.pos() < fin) {
        std::uint64_t etiqueta;
        if (!lector.varint(etiqueta)) return false;
        const int tipo = static_cast<int>(etiqueta & 7);
        switch (etiqueta >> 3) {
        case 1: {
            if (tipo != 2) { if (!lector.salta(tipo)) return false; break; }
            std::size_t hasta;
            if (!lector.largo(hasta, fin)) return false;
            if (!m_obj.crea()._lee(lector, hasta)) return false;
            break;
        }
        case 2: {
            if (tipo != 2) { if (!lector.salta(tipo)) return false; break; }
            std::size_t hasta;
            if (!lector.largo(hasta, fin)) return false;
            if (!m_index.crea()._lee(lector, hasta)) return false;
            break;
        }
        default:
            if (!lector.salta(tipo)) return false;
        }
    }
    return lector.pos() == fin;
}

inline MemberAccess::MemberAccess() = default;
inline MemberAccess::MemberAccess(const MemberAccess&) = default;
inline MemberAccess& MemberAccess::operator=(const MemberAccess&) = default;
inline MemberAccess::MemberAccess(MemberAccess&&) noexcept = default;
inline MemberAccess& MemberAccess::operator=(MemberAccess&&) noexcept = default;
inline MemberAccess::~MemberAccess() = default;
inline const MemberAccess& MemberAccess::default_instance() { static const MemberAccess vacio; return vacio; }
inline bool MemberAccess::ParseFromString(const std::string& datos) {
    return ParseFromArray(datos.data(), static_cast<int>(datos.size()));
}
inline bool MemberAccess::ParseFromArray(const void* datos, int largo) {
    *this = MemberAccess();
    detalle::Lector lector(static_cast<const unsigned char*>(datos),
                           static_cast<std::size_t>(largo));
    return _lee(lector, static_cast<std::size_t>(largo));
}
inline bool MemberAccess::ParseFromIstream(std::istream* entrada) {
    std::string datos((std::istreambuf_iterator<char>(*entrada)),
                      std::istreambuf_iterator<char>());
    if (entrada->bad()) return false;
    return ParseFromString(datos);
}
inline bool MemberAccess::has_obj() const { return m_obj.hay(); }
inline const Expr& MemberAccess::obj() const { return m_obj.hay() ? m_obj.valor() : Expr::default_instance(); }
inline Expr* MemberAccess::mutable_obj() { return &m_obj.crea(); }
inline const std::string& MemberAccess::member() const { return m_member; }
inline void MemberAccess::set_member(std::string valor) { m_member = std::move(valor); }
inline bool MemberAccess::_lee(detalle::Lector& lector, std::size_t fin) {
    while (lector.pos() < fin) {
        std::uint64_t etiqueta;
        if (!lector.varint(etiqueta)) return false;
        const int tipo = static_cast<int>(etiqueta & 7);
        switch (etiqueta >> 3) {
        case 1: {
            if (tipo != 2) { if (!lector.salta(tipo)) return false; break; }
            std::size_t hasta;
            if (!lector.largo(hasta, fin)) return false;
            if (!m_obj.crea()._lee(lector, hasta)) return false;
            break;
        }
        case 2: {
            if (tipo != 2) { if (!lector.salta(tipo)) return false; break; }
            if (!lector.texto(m_member, fin)) return false;
            break;
        }
        default:
            if (!lector.salta(tipo)) return false;
        }
    }
    return lector.pos() == fin;
}

inline SizeofExpr::SizeofExpr() = default;
inline SizeofExpr::SizeofExpr(const SizeofExpr&) = default;
inline SizeofExpr& SizeofExpr::operator=(const SizeofExpr&) = default;
inline SizeofExpr::SizeofExpr(SizeofExpr&&) noexcept = default;
inline SizeofExpr& SizeofExpr::operator=(SizeofExpr&&) noexcept = default;
inline SizeofExpr::~SizeofExpr() = default;
inline const SizeofExpr& SizeofExpr::default_instance() { static const SizeofExpr vacio; return vacio; }
inline bool SizeofExpr::ParseFromString(const std::string& datos) {
    return ParseFromArray(datos.data(), static_cast<int>(datos.size()));
}
inline bool SizeofExpr::ParseFromArray(const void* datos, int largo) {
    *this = SizeofExpr();
    detalle::Lector lector(static_cast<const unsigned char*>(datos),
                           static_cast<std::size_t>(largo));
    return _lee(lector, static_cast<std::size_t>(largo));
}
inline bool SizeofExpr::ParseFromIstream(std::istream* entrada) {
    std::string datos((std::istreambuf_iterator<char>(*entrada)),
                      std::istreambuf_iterator<char>());
    if (entrada->bad()) return false;
    return ParseFromString(datos);
}
inline bool SizeofExpr::has_type() const { return m_type.hay(); }
inline const Type& SizeofExpr::type() const { return m_type.hay() ? m_type.valor() : Type::default_instance(); }
inline Type* SizeofExpr::mutable_type() { return &m_type.crea(); }
inline bool SizeofExpr::has_hook() const { return m_hook.hay(); }
inline const HookRef& SizeofExpr::hook() const { return m_hook.hay() ? m_hook.valor() : HookRef::default_instance(); }
inline HookRef* SizeofExpr::mutable_hook() { return &m_hook.crea(); }
inline bool SizeofExpr::_lee(detalle::Lector& lector, std::size_t fin) {
    while (lector.pos() < fin) {
        std::uint64_t etiqueta;
        if (!lector.varint(etiqueta)) return false;
        const int tipo = static_cast<int>(etiqueta & 7);
        switch (etiqueta >> 3) {
        case 1: {
            if (tipo != 2) { if (!lector.salta(tipo)) return false; break; }
            std::size_t hasta;
            if (!lector.largo(hasta, fin)) return false;
            if (!m_type.crea()._lee(lector, hasta)) return false;
            break;
        }
        case 2: {
            if (tipo != 2) { if (!lector.salta(tipo)) return false; break; }
            std::size_t hasta;
            if (!lector.largo(hasta, fin)) return false;
            if (!m_hook.crea()._lee(lector, hasta)) return false;
            break;
        }
        default:
            if (!lector.salta(tipo)) return false;
        }
    }
    return lector.pos() == fin;
}

inline CastExpr::CastExpr() = default;
inline CastExpr::CastExpr(const CastExpr&) = default;
inline CastExpr& CastExpr::operator=(const CastExpr&) = default;
inline CastExpr::CastExpr(CastExpr&&) noexcept = default;
inline CastExpr& CastExpr::operator=(CastExpr&&) noexcept = default;
inline CastExpr::~CastExpr() = default;
inline const CastExpr& CastExpr::default_instance() { static const CastExpr vacio; return vacio; }
inline bool CastExpr::ParseFromString(const std::string& datos) {
    return ParseFromArray(datos.data(), static_cast<int>(datos.size()));
}
inline bool CastExpr::ParseFromArray(const void* datos, int largo) {
    *this = CastExpr();
    detalle::Lector lector(static_cast<const unsigned char*>(datos),
                           static_cast<std::size_t>(largo));
    return _lee(lector, static_cast<std::size_t>(largo));
}
inline bool CastExpr::ParseFromIstream(std::istream* entrada) {
    std::string datos((std::istreambuf_iterator<char>(*entrada)),
                      std::istreambuf_iterator<char>());
    if (entrada->bad()) return false;
    return ParseFromString(datos);
}
inline bool CastExpr::has_type() const { return m_type.hay(); }
inline const Type& CastExpr::type() const { return m_type.hay() ? m_type.valor() : Type::default_instance(); }
inline Type* CastExpr::mutable_type() { return &m_type.crea(); }
inline bool CastExpr::has_value() const { return m_value.hay(); }
inline const Expr& CastExpr::value() const { return m_value.hay() ? m_value.valor() : Expr::default_instance(); }
inline Expr* CastExpr::mutable_value() { return &m_value.crea(); }
inline bool CastExpr::has_hook() const { return m_hook.hay(); }
inline const HookRef& CastExpr::hook() const { return m_hook.hay() ? m_hook.valor() : HookRef::default_instance(); }
inline HookRef* CastExpr::mutable_hook() { return &m_hook.crea(); }
inline bool CastExpr::_lee(detalle::Lector& lector, std::size_t fin) {
    while (lector.pos() < fin) {
        std::uint64_t etiqueta;
        if (!lector.varint(etiqueta)) return false;
        const int tipo = static_cast<int>(etiqueta & 7);
        switch (etiqueta >> 3) {
        case 1: {
            if (tipo != 2) { if (!lector.salta(tipo)) return false; break; }
            std::size_t hasta;
            if (!lector.largo(hasta, fin)) return false;
            if (!m_type.crea()._lee(lector, hasta)) return false;
            break;
        }
        case 2: {
            if (tipo != 2) { if (!lector.salta(tipo)) return false; break; }
            std::size_t hasta;
            if (!lector.largo(hasta, fin)) return false;
            if (!m_value.crea()._lee(lector, hasta)) return false;
            break;
        }
        case 3: {
            if (tipo != 2) { if (!lector.salta(tipo)) return false; break; }
            std::size_t hasta;
            if (!lector.largo(hasta, fin)) return false;
            if (!m_hook.crea()._lee(lector, hasta)) return false;
            break;
        }
        default:
            if (!lector.salta(tipo)) return false;
        }
    }
    return lector.pos() == fin;
}

inline StructLiteral::StructLiteral() = default;
inline StructLiteral::StructLiteral(const StructLiteral&) = default;
inline StructLiteral& StructLiteral::operator=(const StructLiteral&) = default;
inline StructLiteral::StructLiteral(StructLiteral&&) noexcept = default;
inline StructLiteral& StructLiteral::operator=(StructLiteral&&) noexcept = default;
inline StructLiteral::~StructLiteral() = default;
inline const StructLiteral& StructLiteral::default_instance() { static const StructLiteral vacio; return vacio; }
inline bool StructLiteral::ParseFromString(const std::string& datos) {
    return ParseFromArray(datos.data(), static_cast<int>(datos.size()));
}
inline bool StructLiteral::ParseFromArray(const void* datos, int largo) {
    *this = StructLiteral();
    detalle::Lector lector(static_cast<const unsigned char*>(datos),
                           static_cast<std::size_t>(largo));
    return _lee(lector, static_cast<std::size_t>(largo));
}
inline bool StructLiteral::ParseFromIstream(std::istream* entrada) {
    std::string datos((std::istreambuf_iterator<char>(*entrada)),
                      std::istreambuf_iterator<char>());
    if (entrada->bad()) return false;
    return ParseFromString(datos);
}
inline const std::string& StructLiteral::type_name() const { return m_type_name; }
inline void StructLiteral::set_type_name(std::string valor) { m_type_name = std::move(valor); }
inline const std::vector<std::string>& StructLiteral::field_names() const { return m_field_names; }
inline const std::string& StructLiteral::field_names(int i) const { return m_field_names.at(static_cast<std::size_t>(i)); }
inline int StructLiteral::field_names_size() const { return static_cast<int>(m_field_names.size()); }
inline const std::vector<Expr>& StructLiteral::values() const { return m_values; }
inline const Expr& StructLiteral::values(int i) const { return m_values.at(static_cast<std::size_t>(i)); }
inline int StructLiteral::values_size() const { return static_cast<int>(m_values.size()); }
inline Expr* StructLiteral::add_values() { return &m_values.emplace_back(); }
inline bool StructLiteral::has_temp_drop() const { return m_temp_drop.hay(); }
inline const HookRef& StructLiteral::temp_drop() const { return m_temp_drop.hay() ? m_temp_drop.valor() : HookRef::default_instance(); }
inline HookRef* StructLiteral::mutable_temp_drop() { return &m_temp_drop.crea(); }
inline bool StructLiteral::temp_by_type() const { return m_temp_by_type; }
inline void StructLiteral::set_temp_by_type(bool valor) { m_temp_by_type = std::move(valor); }
inline bool StructLiteral::_lee(detalle::Lector& lector, std::size_t fin) {
    while (lector.pos() < fin) {
        std::uint64_t etiqueta;
        if (!lector.varint(etiqueta)) return false;
        const int tipo = static_cast<int>(etiqueta & 7);
        switch (etiqueta >> 3) {
        case 1: {
            if (tipo != 2) { if (!lector.salta(tipo)) return false; break; }
            if (!lector.texto(m_type_name, fin)) return false;
            break;
        }
        case 2: {
            if (tipo != 2) { if (!lector.salta(tipo)) return false; break; }
            if (!lector.texto(m_field_names.emplace_back(), fin)) return false;
            break;
        }
        case 3: {
            if (tipo != 2) { if (!lector.salta(tipo)) return false; break; }
            std::size_t hasta;
            if (!lector.largo(hasta, fin)) return false;
            if (!m_values.emplace_back()._lee(lector, hasta)) return false;
            break;
        }
        case 4: {
            if (tipo != 2) { if (!lector.salta(tipo)) return false; break; }
            std::size_t hasta;
            if (!lector.largo(hasta, fin)) return false;
            if (!m_temp_drop.crea()._lee(lector, hasta)) return false;
            break;
        }
        case 5: {
            if (tipo != 0) { if (!lector.salta(tipo)) return false; break; }
            std::uint64_t v; if (!lector.varint(v)) return false; m_temp_by_type = v != 0;
            break;
        }
        default:
            if (!lector.salta(tipo)) return false;
        }
    }
    return lector.pos() == fin;
}

inline Stmt::Stmt() = default;
inline Stmt::Stmt(const Stmt&) = default;
inline Stmt& Stmt::operator=(const Stmt&) = default;
inline Stmt::Stmt(Stmt&&) noexcept = default;
inline Stmt& Stmt::operator=(Stmt&&) noexcept = default;
inline Stmt::~Stmt() = default;
inline const Stmt& Stmt::default_instance() { static const Stmt vacio; return vacio; }
inline bool Stmt::ParseFromString(const std::string& datos) {
    return ParseFromArray(datos.data(), static_cast<int>(datos.size()));
}
inline bool Stmt::ParseFromArray(const void* datos, int largo) {
    *this = Stmt();
    detalle::Lector lector(static_cast<const unsigned char*>(datos),
                           static_cast<std::size_t>(largo));
    return _lee(lector, static_cast<std::size_t>(largo));
}
inline bool Stmt::ParseFromIstream(std::istream* entrada) {
    std::string datos((std::istreambuf_iterator<char>(*entrada)),
                      std::istreambuf_iterator<char>());
    if (entrada->bad()) return false;
    return ParseFromString(datos);
}
inline Stmt::NodeCase Stmt::node_case() const { return static_cast<NodeCase>(node_caso_); }
inline std::uint32_t Stmt::ln() const { return m_ln; }
inline void Stmt::set_ln(std::uint32_t valor) { m_ln = std::move(valor); }
inline std::uint32_t Stmt::col() const { return m_col; }
inline void Stmt::set_col(std::uint32_t valor) { m_col = std::move(valor); }
inline bool Stmt::has_block() const { return node_caso_ == kBlock; }
inline const Block& Stmt::block() const {
    return node_caso_ == kBlock && m_block.hay() ? m_block.valor() : Block::default_instance();
}
inline Block* Stmt::mutable_block() { node_caso_ = kBlock; return &m_block.crea(); }
inline bool Stmt::has_var_decl() const { return node_caso_ == kVarDecl; }
inline const VarDecl& Stmt::var_decl() const {
    return node_caso_ == kVarDecl && m_var_decl.hay() ? m_var_decl.valor() : VarDecl::default_instance();
}
inline VarDecl* Stmt::mutable_var_decl() { node_caso_ = kVarDecl; return &m_var_decl.crea(); }
inline bool Stmt::has_if_stmt() const { return node_caso_ == kIfStmt; }
inline const IfStmt& Stmt::if_stmt() const {
    return node_caso_ == kIfStmt && m_if_stmt.hay() ? m_if_stmt.valor() : IfStmt::default_instance();
}
inline IfStmt* Stmt::mutable_if_stmt() { node_caso_ = kIfStmt; return &m_if_stmt.crea(); }
inline bool Stmt::has_while_stmt() const { return node_caso_ == kWhileStmt; }
inline const WhileStmt& Stmt::while_stmt() const {
    return node_caso_ == kWhileStmt && m_while_stmt.hay() ? m_while_stmt.valor() : WhileStmt::default_instance();
}
inline WhileStmt* Stmt::mutable_while_stmt() { node_caso_ = kWhileStmt; return &m_while_stmt.crea(); }
inline bool Stmt::has_match_stmt() const { return node_caso_ == kMatchStmt; }
inline const MatchStmt& Stmt::match_stmt() const {
    return node_caso_ == kMatchStmt && m_match_stmt.hay() ? m_match_stmt.valor() : MatchStmt::default_instance();
}
inline MatchStmt* Stmt::mutable_match_stmt() { node_caso_ = kMatchStmt; return &m_match_stmt.crea(); }
inline bool Stmt::has_return_stmt() const { return node_caso_ == kReturnStmt; }
inline const ReturnStmt& Stmt::return_stmt() const {
    return node_caso_ == kReturnStmt && m_return_stmt.hay() ? m_return_stmt.valor() : ReturnStmt::default_instance();
}
inline ReturnStmt* Stmt::mutable_return_stmt() { node_caso_ = kReturnStmt; return &m_return_stmt.crea(); }
inline bool Stmt::has_break_stmt() const { return node_caso_ == kBreakStmt; }
inline const BreakStmt& Stmt::break_stmt() const {
    return node_caso_ == kBreakStmt && m_break_stmt.hay() ? m_break_stmt.valor() : BreakStmt::default_instance();
}
inline BreakStmt* Stmt::mutable_break_stmt() { node_caso_ = kBreakStmt; return &m_break_stmt.crea(); }
inline bool Stmt::has_continue_stmt() const { return node_caso_ == kContinueStmt; }
inline const ContinueStmt& Stmt::continue_stmt() const {
    return node_caso_ == kContinueStmt && m_continue_stmt.hay() ? m_continue_stmt.valor() : ContinueStmt::default_instance();
}
inline ContinueStmt* Stmt::mutable_continue_stmt() { node_caso_ = kContinueStmt; return &m_continue_stmt.crea(); }
inline bool Stmt::has_move_stmt() const { return node_caso_ == kMoveStmt; }
inline const MoveStmt& Stmt::move_stmt() const {
    return node_caso_ == kMoveStmt && m_move_stmt.hay() ? m_move_stmt.valor() : MoveStmt::default_instance();
}
inline MoveStmt* Stmt::mutable_move_stmt() { node_caso_ = kMoveStmt; return &m_move_stmt.crea(); }
inline bool Stmt::has_free_stmt() const { return node_caso_ == kFreeStmt; }
inline const FreeStmt& Stmt::free_stmt() const {
    return node_caso_ == kFreeStmt && m_free_stmt.hay() ? m_free_stmt.valor() : FreeStmt::default_instance();
}
inline FreeStmt* Stmt::mutable_free_stmt() { node_caso_ = kFreeStmt; return &m_free_stmt.crea(); }
inline bool Stmt::has_expr_stmt() const { return node_caso_ == kExprStmt; }
inline const ExprStmt& Stmt::expr_stmt() const {
    return node_caso_ == kExprStmt && m_expr_stmt.hay() ? m_expr_stmt.valor() : ExprStmt::default_instance();
}
inline ExprStmt* Stmt::mutable_expr_stmt() { node_caso_ = kExprStmt; return &m_expr_stmt.crea(); }
inline bool Stmt::has_import_binding() const { return node_caso_ == kImportBinding; }
inline const ImportBinding& Stmt::import_binding() const {
    return node_caso_ == kImportBinding && m_import_binding.hay() ? m_import_binding.valor() : ImportBinding::default_instance();
}
inline ImportBinding* Stmt::mutable_import_binding() { node_caso_ = kImportBinding; return &m_import_binding.crea(); }
inline bool Stmt::has_type_decl() const { return node_caso_ == kTypeDecl; }
inline const TypeDecl& Stmt::type_decl() const {
    return node_caso_ == kTypeDecl && m_type_decl.hay() ? m_type_decl.valor() : TypeDecl::default_instance();
}
inline TypeDecl* Stmt::mutable_type_decl() { node_caso_ = kTypeDecl; return &m_type_decl.crea(); }
inline bool Stmt::has_throw_stmt() const { return node_caso_ == kThrowStmt; }
inline const ThrowStmt& Stmt::throw_stmt() const {
    return node_caso_ == kThrowStmt && m_throw_stmt.hay() ? m_throw_stmt.valor() : ThrowStmt::default_instance();
}
inline ThrowStmt* Stmt::mutable_throw_stmt() { node_caso_ = kThrowStmt; return &m_throw_stmt.crea(); }
inline bool Stmt::has_try_stmt() const { return node_caso_ == kTryStmt; }
inline const TryStmt& Stmt::try_stmt() const {
    return node_caso_ == kTryStmt && m_try_stmt.hay() ? m_try_stmt.valor() : TryStmt::default_instance();
}
inline TryStmt* Stmt::mutable_try_stmt() { node_caso_ = kTryStmt; return &m_try_stmt.crea(); }
inline bool Stmt::_lee(detalle::Lector& lector, std::size_t fin) {
    while (lector.pos() < fin) {
        std::uint64_t etiqueta;
        if (!lector.varint(etiqueta)) return false;
        const int tipo = static_cast<int>(etiqueta & 7);
        switch (etiqueta >> 3) {
        case 1: {
            if (tipo != 0) { if (!lector.salta(tipo)) return false; break; }
            std::uint64_t v; if (!lector.varint(v)) return false; m_ln = static_cast<std::uint32_t>(v);
            break;
        }
        case 2: {
            if (tipo != 0) { if (!lector.salta(tipo)) return false; break; }
            std::uint64_t v; if (!lector.varint(v)) return false; m_col = static_cast<std::uint32_t>(v);
            break;
        }
        case 10: {
            if (tipo != 2) { if (!lector.salta(tipo)) return false; break; }
            std::size_t hasta;
            if (!lector.largo(hasta, fin)) return false;
            node_caso_ = kBlock;
            if (!m_block.crea()._lee(lector, hasta)) return false;
            break;
        }
        case 11: {
            if (tipo != 2) { if (!lector.salta(tipo)) return false; break; }
            std::size_t hasta;
            if (!lector.largo(hasta, fin)) return false;
            node_caso_ = kVarDecl;
            if (!m_var_decl.crea()._lee(lector, hasta)) return false;
            break;
        }
        case 13: {
            if (tipo != 2) { if (!lector.salta(tipo)) return false; break; }
            std::size_t hasta;
            if (!lector.largo(hasta, fin)) return false;
            node_caso_ = kIfStmt;
            if (!m_if_stmt.crea()._lee(lector, hasta)) return false;
            break;
        }
        case 14: {
            if (tipo != 2) { if (!lector.salta(tipo)) return false; break; }
            std::size_t hasta;
            if (!lector.largo(hasta, fin)) return false;
            node_caso_ = kWhileStmt;
            if (!m_while_stmt.crea()._lee(lector, hasta)) return false;
            break;
        }
        case 15: {
            if (tipo != 2) { if (!lector.salta(tipo)) return false; break; }
            std::size_t hasta;
            if (!lector.largo(hasta, fin)) return false;
            node_caso_ = kMatchStmt;
            if (!m_match_stmt.crea()._lee(lector, hasta)) return false;
            break;
        }
        case 16: {
            if (tipo != 2) { if (!lector.salta(tipo)) return false; break; }
            std::size_t hasta;
            if (!lector.largo(hasta, fin)) return false;
            node_caso_ = kReturnStmt;
            if (!m_return_stmt.crea()._lee(lector, hasta)) return false;
            break;
        }
        case 17: {
            if (tipo != 2) { if (!lector.salta(tipo)) return false; break; }
            std::size_t hasta;
            if (!lector.largo(hasta, fin)) return false;
            node_caso_ = kBreakStmt;
            if (!m_break_stmt.crea()._lee(lector, hasta)) return false;
            break;
        }
        case 18: {
            if (tipo != 2) { if (!lector.salta(tipo)) return false; break; }
            std::size_t hasta;
            if (!lector.largo(hasta, fin)) return false;
            node_caso_ = kContinueStmt;
            if (!m_continue_stmt.crea()._lee(lector, hasta)) return false;
            break;
        }
        case 19: {
            if (tipo != 2) { if (!lector.salta(tipo)) return false; break; }
            std::size_t hasta;
            if (!lector.largo(hasta, fin)) return false;
            node_caso_ = kMoveStmt;
            if (!m_move_stmt.crea()._lee(lector, hasta)) return false;
            break;
        }
        case 20: {
            if (tipo != 2) { if (!lector.salta(tipo)) return false; break; }
            std::size_t hasta;
            if (!lector.largo(hasta, fin)) return false;
            node_caso_ = kFreeStmt;
            if (!m_free_stmt.crea()._lee(lector, hasta)) return false;
            break;
        }
        case 21: {
            if (tipo != 2) { if (!lector.salta(tipo)) return false; break; }
            std::size_t hasta;
            if (!lector.largo(hasta, fin)) return false;
            node_caso_ = kExprStmt;
            if (!m_expr_stmt.crea()._lee(lector, hasta)) return false;
            break;
        }
        case 22: {
            if (tipo != 2) { if (!lector.salta(tipo)) return false; break; }
            std::size_t hasta;
            if (!lector.largo(hasta, fin)) return false;
            node_caso_ = kImportBinding;
            if (!m_import_binding.crea()._lee(lector, hasta)) return false;
            break;
        }
        case 23: {
            if (tipo != 2) { if (!lector.salta(tipo)) return false; break; }
            std::size_t hasta;
            if (!lector.largo(hasta, fin)) return false;
            node_caso_ = kTypeDecl;
            if (!m_type_decl.crea()._lee(lector, hasta)) return false;
            break;
        }
        case 24: {
            if (tipo != 2) { if (!lector.salta(tipo)) return false; break; }
            std::size_t hasta;
            if (!lector.largo(hasta, fin)) return false;
            node_caso_ = kThrowStmt;
            if (!m_throw_stmt.crea()._lee(lector, hasta)) return false;
            break;
        }
        case 25: {
            if (tipo != 2) { if (!lector.salta(tipo)) return false; break; }
            std::size_t hasta;
            if (!lector.largo(hasta, fin)) return false;
            node_caso_ = kTryStmt;
            if (!m_try_stmt.crea()._lee(lector, hasta)) return false;
            break;
        }
        default:
            if (!lector.salta(tipo)) return false;
        }
    }
    return lector.pos() == fin;
}

inline Drop::Drop() = default;
inline Drop::Drop(const Drop&) = default;
inline Drop& Drop::operator=(const Drop&) = default;
inline Drop::Drop(Drop&&) noexcept = default;
inline Drop& Drop::operator=(Drop&&) noexcept = default;
inline Drop::~Drop() = default;
inline const Drop& Drop::default_instance() { static const Drop vacio; return vacio; }
inline bool Drop::ParseFromString(const std::string& datos) {
    return ParseFromArray(datos.data(), static_cast<int>(datos.size()));
}
inline bool Drop::ParseFromArray(const void* datos, int largo) {
    *this = Drop();
    detalle::Lector lector(static_cast<const unsigned char*>(datos),
                           static_cast<std::size_t>(largo));
    return _lee(lector, static_cast<std::size_t>(largo));
}
inline bool Drop::ParseFromIstream(std::istream* entrada) {
    std::string datos((std::istreambuf_iterator<char>(*entrada)),
                      std::istreambuf_iterator<char>());
    if (entrada->bad()) return false;
    return ParseFromString(datos);
}
inline const std::vector<std::string>& Drop::path() const { return m_path; }
inline const std::string& Drop::path(int i) const { return m_path.at(static_cast<std::size_t>(i)); }
inline int Drop::path_size() const { return static_cast<int>(m_path.size()); }
inline bool Drop::has_hook() const { return m_hook.hay(); }
inline const HookRef& Drop::hook() const { return m_hook.hay() ? m_hook.valor() : HookRef::default_instance(); }
inline HookRef* Drop::mutable_hook() { return &m_hook.crea(); }
inline bool Drop::by_type() const { return m_by_type; }
inline void Drop::set_by_type(bool valor) { m_by_type = std::move(valor); }
inline bool Drop::_lee(detalle::Lector& lector, std::size_t fin) {
    while (lector.pos() < fin) {
        std::uint64_t etiqueta;
        if (!lector.varint(etiqueta)) return false;
        const int tipo = static_cast<int>(etiqueta & 7);
        switch (etiqueta >> 3) {
        case 1: {
            if (tipo != 2) { if (!lector.salta(tipo)) return false; break; }
            if (!lector.texto(m_path.emplace_back(), fin)) return false;
            break;
        }
        case 2: {
            if (tipo != 2) { if (!lector.salta(tipo)) return false; break; }
            std::size_t hasta;
            if (!lector.largo(hasta, fin)) return false;
            if (!m_hook.crea()._lee(lector, hasta)) return false;
            break;
        }
        case 3: {
            if (tipo != 0) { if (!lector.salta(tipo)) return false; break; }
            std::uint64_t v; if (!lector.varint(v)) return false; m_by_type = v != 0;
            break;
        }
        default:
            if (!lector.salta(tipo)) return false;
        }
    }
    return lector.pos() == fin;
}

inline Block::Block() = default;
inline Block::Block(const Block&) = default;
inline Block& Block::operator=(const Block&) = default;
inline Block::Block(Block&&) noexcept = default;
inline Block& Block::operator=(Block&&) noexcept = default;
inline Block::~Block() = default;
inline const Block& Block::default_instance() { static const Block vacio; return vacio; }
inline bool Block::ParseFromString(const std::string& datos) {
    return ParseFromArray(datos.data(), static_cast<int>(datos.size()));
}
inline bool Block::ParseFromArray(const void* datos, int largo) {
    *this = Block();
    detalle::Lector lector(static_cast<const unsigned char*>(datos),
                           static_cast<std::size_t>(largo));
    return _lee(lector, static_cast<std::size_t>(largo));
}
inline bool Block::ParseFromIstream(std::istream* entrada) {
    std::string datos((std::istreambuf_iterator<char>(*entrada)),
                      std::istreambuf_iterator<char>());
    if (entrada->bad()) return false;
    return ParseFromString(datos);
}
inline const std::vector<Stmt>& Block::statements() const { return m_statements; }
inline const Stmt& Block::statements(int i) const { return m_statements.at(static_cast<std::size_t>(i)); }
inline int Block::statements_size() const { return static_cast<int>(m_statements.size()); }
inline Stmt* Block::add_statements() { return &m_statements.emplace_back(); }
inline const std::vector<Drop>& Block::drops() const { return m_drops; }
inline const Drop& Block::drops(int i) const { return m_drops.at(static_cast<std::size_t>(i)); }
inline int Block::drops_size() const { return static_cast<int>(m_drops.size()); }
inline Drop* Block::add_drops() { return &m_drops.emplace_back(); }
inline bool Block::_lee(detalle::Lector& lector, std::size_t fin) {
    while (lector.pos() < fin) {
        std::uint64_t etiqueta;
        if (!lector.varint(etiqueta)) return false;
        const int tipo = static_cast<int>(etiqueta & 7);
        switch (etiqueta >> 3) {
        case 1: {
            if (tipo != 2) { if (!lector.salta(tipo)) return false; break; }
            std::size_t hasta;
            if (!lector.largo(hasta, fin)) return false;
            if (!m_statements.emplace_back()._lee(lector, hasta)) return false;
            break;
        }
        case 2: {
            if (tipo != 2) { if (!lector.salta(tipo)) return false; break; }
            std::size_t hasta;
            if (!lector.largo(hasta, fin)) return false;
            if (!m_drops.emplace_back()._lee(lector, hasta)) return false;
            break;
        }
        default:
            if (!lector.salta(tipo)) return false;
        }
    }
    return lector.pos() == fin;
}

inline VarDecl::VarDecl() = default;
inline VarDecl::VarDecl(const VarDecl&) = default;
inline VarDecl& VarDecl::operator=(const VarDecl&) = default;
inline VarDecl::VarDecl(VarDecl&&) noexcept = default;
inline VarDecl& VarDecl::operator=(VarDecl&&) noexcept = default;
inline VarDecl::~VarDecl() = default;
inline const VarDecl& VarDecl::default_instance() { static const VarDecl vacio; return vacio; }
inline bool VarDecl::ParseFromString(const std::string& datos) {
    return ParseFromArray(datos.data(), static_cast<int>(datos.size()));
}
inline bool VarDecl::ParseFromArray(const void* datos, int largo) {
    *this = VarDecl();
    detalle::Lector lector(static_cast<const unsigned char*>(datos),
                           static_cast<std::size_t>(largo));
    return _lee(lector, static_cast<std::size_t>(largo));
}
inline bool VarDecl::ParseFromIstream(std::istream* entrada) {
    std::string datos((std::istreambuf_iterator<char>(*entrada)),
                      std::istreambuf_iterator<char>());
    if (entrada->bad()) return false;
    return ParseFromString(datos);
}
inline const std::string& VarDecl::qualifier() const { return m_qualifier; }
inline void VarDecl::set_qualifier(std::string valor) { m_qualifier = std::move(valor); }
inline const std::string& VarDecl::name() const { return m_name; }
inline void VarDecl::set_name(std::string valor) { m_name = std::move(valor); }
inline bool VarDecl::has_value() const { return m_value.hay(); }
inline const Expr& VarDecl::value() const { return m_value.hay() ? m_value.valor() : Expr::default_instance(); }
inline Expr* VarDecl::mutable_value() { return &m_value.crea(); }
inline std::uint32_t VarDecl::type_id() const { return m_type_id; }
inline void VarDecl::set_type_id(std::uint32_t valor) { m_type_id = std::move(valor); }
inline bool VarDecl::_lee(detalle::Lector& lector, std::size_t fin) {
    while (lector.pos() < fin) {
        std::uint64_t etiqueta;
        if (!lector.varint(etiqueta)) return false;
        const int tipo = static_cast<int>(etiqueta & 7);
        switch (etiqueta >> 3) {
        case 1: {
            if (tipo != 2) { if (!lector.salta(tipo)) return false; break; }
            if (!lector.texto(m_qualifier, fin)) return false;
            break;
        }
        case 3: {
            if (tipo != 2) { if (!lector.salta(tipo)) return false; break; }
            if (!lector.texto(m_name, fin)) return false;
            break;
        }
        case 4: {
            if (tipo != 2) { if (!lector.salta(tipo)) return false; break; }
            std::size_t hasta;
            if (!lector.largo(hasta, fin)) return false;
            if (!m_value.crea()._lee(lector, hasta)) return false;
            break;
        }
        case 5: {
            if (tipo != 0) { if (!lector.salta(tipo)) return false; break; }
            std::uint64_t v; if (!lector.varint(v)) return false; m_type_id = static_cast<std::uint32_t>(v);
            break;
        }
        default:
            if (!lector.salta(tipo)) return false;
        }
    }
    return lector.pos() == fin;
}

inline TypeDecl::TypeDecl() = default;
inline TypeDecl::TypeDecl(const TypeDecl&) = default;
inline TypeDecl& TypeDecl::operator=(const TypeDecl&) = default;
inline TypeDecl::TypeDecl(TypeDecl&&) noexcept = default;
inline TypeDecl& TypeDecl::operator=(TypeDecl&&) noexcept = default;
inline TypeDecl::~TypeDecl() = default;
inline const TypeDecl& TypeDecl::default_instance() { static const TypeDecl vacio; return vacio; }
inline bool TypeDecl::ParseFromString(const std::string& datos) {
    return ParseFromArray(datos.data(), static_cast<int>(datos.size()));
}
inline bool TypeDecl::ParseFromArray(const void* datos, int largo) {
    *this = TypeDecl();
    detalle::Lector lector(static_cast<const unsigned char*>(datos),
                           static_cast<std::size_t>(largo));
    return _lee(lector, static_cast<std::size_t>(largo));
}
inline bool TypeDecl::ParseFromIstream(std::istream* entrada) {
    std::string datos((std::istreambuf_iterator<char>(*entrada)),
                      std::istreambuf_iterator<char>());
    if (entrada->bad()) return false;
    return ParseFromString(datos);
}
inline const std::string& TypeDecl::qualifier() const { return m_qualifier; }
inline void TypeDecl::set_qualifier(std::string valor) { m_qualifier = std::move(valor); }
inline const std::string& TypeDecl::name() const { return m_name; }
inline void TypeDecl::set_name(std::string valor) { m_name = std::move(valor); }
inline bool TypeDecl::has_value() const { return m_value.hay(); }
inline const Expr& TypeDecl::value() const { return m_value.hay() ? m_value.valor() : Expr::default_instance(); }
inline Expr* TypeDecl::mutable_value() { return &m_value.crea(); }
inline bool TypeDecl::_lee(detalle::Lector& lector, std::size_t fin) {
    while (lector.pos() < fin) {
        std::uint64_t etiqueta;
        if (!lector.varint(etiqueta)) return false;
        const int tipo = static_cast<int>(etiqueta & 7);
        switch (etiqueta >> 3) {
        case 1: {
            if (tipo != 2) { if (!lector.salta(tipo)) return false; break; }
            if (!lector.texto(m_qualifier, fin)) return false;
            break;
        }
        case 2: {
            if (tipo != 2) { if (!lector.salta(tipo)) return false; break; }
            if (!lector.texto(m_name, fin)) return false;
            break;
        }
        case 3: {
            if (tipo != 2) { if (!lector.salta(tipo)) return false; break; }
            std::size_t hasta;
            if (!lector.largo(hasta, fin)) return false;
            if (!m_value.crea()._lee(lector, hasta)) return false;
            break;
        }
        default:
            if (!lector.salta(tipo)) return false;
        }
    }
    return lector.pos() == fin;
}

inline IfStmt::IfStmt() = default;
inline IfStmt::IfStmt(const IfStmt&) = default;
inline IfStmt& IfStmt::operator=(const IfStmt&) = default;
inline IfStmt::IfStmt(IfStmt&&) noexcept = default;
inline IfStmt& IfStmt::operator=(IfStmt&&) noexcept = default;
inline IfStmt::~IfStmt() = default;
inline const IfStmt& IfStmt::default_instance() { static const IfStmt vacio; return vacio; }
inline bool IfStmt::ParseFromString(const std::string& datos) {
    return ParseFromArray(datos.data(), static_cast<int>(datos.size()));
}
inline bool IfStmt::ParseFromArray(const void* datos, int largo) {
    *this = IfStmt();
    detalle::Lector lector(static_cast<const unsigned char*>(datos),
                           static_cast<std::size_t>(largo));
    return _lee(lector, static_cast<std::size_t>(largo));
}
inline bool IfStmt::ParseFromIstream(std::istream* entrada) {
    std::string datos((std::istreambuf_iterator<char>(*entrada)),
                      std::istreambuf_iterator<char>());
    if (entrada->bad()) return false;
    return ParseFromString(datos);
}
inline IfStmt::ElseBranchCase IfStmt::else_branch_case() const { return static_cast<ElseBranchCase>(else_branch_caso_); }
inline bool IfStmt::has_condition() const { return m_condition.hay(); }
inline const Expr& IfStmt::condition() const { return m_condition.hay() ? m_condition.valor() : Expr::default_instance(); }
inline Expr* IfStmt::mutable_condition() { return &m_condition.crea(); }
inline bool IfStmt::has_then_block() const { return m_then_block.hay(); }
inline const Block& IfStmt::then_block() const { return m_then_block.hay() ? m_then_block.valor() : Block::default_instance(); }
inline Block* IfStmt::mutable_then_block() { return &m_then_block.crea(); }
inline bool IfStmt::has_else_block() const { return else_branch_caso_ == kElseBlock; }
inline const Block& IfStmt::else_block() const {
    return else_branch_caso_ == kElseBlock && m_else_block.hay() ? m_else_block.valor() : Block::default_instance();
}
inline Block* IfStmt::mutable_else_block() { else_branch_caso_ = kElseBlock; return &m_else_block.crea(); }
inline bool IfStmt::has_else_if() const { return else_branch_caso_ == kElseIf; }
inline const IfStmt& IfStmt::else_if() const {
    return else_branch_caso_ == kElseIf && m_else_if.hay() ? m_else_if.valor() : IfStmt::default_instance();
}
inline IfStmt* IfStmt::mutable_else_if() { else_branch_caso_ = kElseIf; return &m_else_if.crea(); }
inline bool IfStmt::_lee(detalle::Lector& lector, std::size_t fin) {
    while (lector.pos() < fin) {
        std::uint64_t etiqueta;
        if (!lector.varint(etiqueta)) return false;
        const int tipo = static_cast<int>(etiqueta & 7);
        switch (etiqueta >> 3) {
        case 1: {
            if (tipo != 2) { if (!lector.salta(tipo)) return false; break; }
            std::size_t hasta;
            if (!lector.largo(hasta, fin)) return false;
            if (!m_condition.crea()._lee(lector, hasta)) return false;
            break;
        }
        case 2: {
            if (tipo != 2) { if (!lector.salta(tipo)) return false; break; }
            std::size_t hasta;
            if (!lector.largo(hasta, fin)) return false;
            if (!m_then_block.crea()._lee(lector, hasta)) return false;
            break;
        }
        case 3: {
            if (tipo != 2) { if (!lector.salta(tipo)) return false; break; }
            std::size_t hasta;
            if (!lector.largo(hasta, fin)) return false;
            else_branch_caso_ = kElseBlock;
            if (!m_else_block.crea()._lee(lector, hasta)) return false;
            break;
        }
        case 4: {
            if (tipo != 2) { if (!lector.salta(tipo)) return false; break; }
            std::size_t hasta;
            if (!lector.largo(hasta, fin)) return false;
            else_branch_caso_ = kElseIf;
            if (!m_else_if.crea()._lee(lector, hasta)) return false;
            break;
        }
        default:
            if (!lector.salta(tipo)) return false;
        }
    }
    return lector.pos() == fin;
}

inline WhileStmt::WhileStmt() = default;
inline WhileStmt::WhileStmt(const WhileStmt&) = default;
inline WhileStmt& WhileStmt::operator=(const WhileStmt&) = default;
inline WhileStmt::WhileStmt(WhileStmt&&) noexcept = default;
inline WhileStmt& WhileStmt::operator=(WhileStmt&&) noexcept = default;
inline WhileStmt::~WhileStmt() = default;
inline const WhileStmt& WhileStmt::default_instance() { static const WhileStmt vacio; return vacio; }
inline bool WhileStmt::ParseFromString(const std::string& datos) {
    return ParseFromArray(datos.data(), static_cast<int>(datos.size()));
}
inline bool WhileStmt::ParseFromArray(const void* datos, int largo) {
    *this = WhileStmt();
    detalle::Lector lector(static_cast<const unsigned char*>(datos),
                           static_cast<std::size_t>(largo));
    return _lee(lector, static_cast<std::size_t>(largo));
}
inline bool WhileStmt::ParseFromIstream(std::istream* entrada) {
    std::string datos((std::istreambuf_iterator<char>(*entrada)),
                      std::istreambuf_iterator<char>());
    if (entrada->bad()) return false;
    return ParseFromString(datos);
}
inline bool WhileStmt::has_condition() const { return m_condition.hay(); }
inline const Expr& WhileStmt::condition() const { return m_condition.hay() ? m_condition.valor() : Expr::default_instance(); }
inline Expr* WhileStmt::mutable_condition() { return &m_condition.crea(); }
inline bool WhileStmt::has_body() const { return m_body.hay(); }
inline const Block& WhileStmt::body() const { return m_body.hay() ? m_body.valor() : Block::default_instance(); }
inline Block* WhileStmt::mutable_body() { return &m_body.crea(); }
inline bool WhileStmt::_lee(detalle::Lector& lector, std::size_t fin) {
    while (lector.pos() < fin) {
        std::uint64_t etiqueta;
        if (!lector.varint(etiqueta)) return false;
        const int tipo = static_cast<int>(etiqueta & 7);
        switch (etiqueta >> 3) {
        case 1: {
            if (tipo != 2) { if (!lector.salta(tipo)) return false; break; }
            std::size_t hasta;
            if (!lector.largo(hasta, fin)) return false;
            if (!m_condition.crea()._lee(lector, hasta)) return false;
            break;
        }
        case 2: {
            if (tipo != 2) { if (!lector.salta(tipo)) return false; break; }
            std::size_t hasta;
            if (!lector.largo(hasta, fin)) return false;
            if (!m_body.crea()._lee(lector, hasta)) return false;
            break;
        }
        default:
            if (!lector.salta(tipo)) return false;
        }
    }
    return lector.pos() == fin;
}

inline CaseArm::CaseArm() = default;
inline CaseArm::CaseArm(const CaseArm&) = default;
inline CaseArm& CaseArm::operator=(const CaseArm&) = default;
inline CaseArm::CaseArm(CaseArm&&) noexcept = default;
inline CaseArm& CaseArm::operator=(CaseArm&&) noexcept = default;
inline CaseArm::~CaseArm() = default;
inline const CaseArm& CaseArm::default_instance() { static const CaseArm vacio; return vacio; }
inline bool CaseArm::ParseFromString(const std::string& datos) {
    return ParseFromArray(datos.data(), static_cast<int>(datos.size()));
}
inline bool CaseArm::ParseFromArray(const void* datos, int largo) {
    *this = CaseArm();
    detalle::Lector lector(static_cast<const unsigned char*>(datos),
                           static_cast<std::size_t>(largo));
    return _lee(lector, static_cast<std::size_t>(largo));
}
inline bool CaseArm::ParseFromIstream(std::istream* entrada) {
    std::string datos((std::istreambuf_iterator<char>(*entrada)),
                      std::istreambuf_iterator<char>());
    if (entrada->bad()) return false;
    return ParseFromString(datos);
}
inline bool CaseArm::has_pattern() const { return m_pattern.hay(); }
inline const Expr& CaseArm::pattern() const { return m_pattern.hay() ? m_pattern.valor() : Expr::default_instance(); }
inline Expr* CaseArm::mutable_pattern() { return &m_pattern.crea(); }
inline bool CaseArm::has_body() const { return m_body.hay(); }
inline const Stmt& CaseArm::body() const { return m_body.hay() ? m_body.valor() : Stmt::default_instance(); }
inline Stmt* CaseArm::mutable_body() { return &m_body.crea(); }
inline bool CaseArm::_lee(detalle::Lector& lector, std::size_t fin) {
    while (lector.pos() < fin) {
        std::uint64_t etiqueta;
        if (!lector.varint(etiqueta)) return false;
        const int tipo = static_cast<int>(etiqueta & 7);
        switch (etiqueta >> 3) {
        case 1: {
            if (tipo != 2) { if (!lector.salta(tipo)) return false; break; }
            std::size_t hasta;
            if (!lector.largo(hasta, fin)) return false;
            if (!m_pattern.crea()._lee(lector, hasta)) return false;
            break;
        }
        case 2: {
            if (tipo != 2) { if (!lector.salta(tipo)) return false; break; }
            std::size_t hasta;
            if (!lector.largo(hasta, fin)) return false;
            if (!m_body.crea()._lee(lector, hasta)) return false;
            break;
        }
        default:
            if (!lector.salta(tipo)) return false;
        }
    }
    return lector.pos() == fin;
}

inline MatchStmt::MatchStmt() = default;
inline MatchStmt::MatchStmt(const MatchStmt&) = default;
inline MatchStmt& MatchStmt::operator=(const MatchStmt&) = default;
inline MatchStmt::MatchStmt(MatchStmt&&) noexcept = default;
inline MatchStmt& MatchStmt::operator=(MatchStmt&&) noexcept = default;
inline MatchStmt::~MatchStmt() = default;
inline const MatchStmt& MatchStmt::default_instance() { static const MatchStmt vacio; return vacio; }
inline bool MatchStmt::ParseFromString(const std::string& datos) {
    return ParseFromArray(datos.data(), static_cast<int>(datos.size()));
}
inline bool MatchStmt::ParseFromArray(const void* datos, int largo) {
    *this = MatchStmt();
    detalle::Lector lector(static_cast<const unsigned char*>(datos),
                           static_cast<std::size_t>(largo));
    return _lee(lector, static_cast<std::size_t>(largo));
}
inline bool MatchStmt::ParseFromIstream(std::istream* entrada) {
    std::string datos((std::istreambuf_iterator<char>(*entrada)),
                      std::istreambuf_iterator<char>());
    if (entrada->bad()) return false;
    return ParseFromString(datos);
}
inline bool MatchStmt::has_subject() const { return m_subject.hay(); }
inline const Expr& MatchStmt::subject() const { return m_subject.hay() ? m_subject.valor() : Expr::default_instance(); }
inline Expr* MatchStmt::mutable_subject() { return &m_subject.crea(); }
inline const std::vector<CaseArm>& MatchStmt::cases() const { return m_cases; }
inline const CaseArm& MatchStmt::cases(int i) const { return m_cases.at(static_cast<std::size_t>(i)); }
inline int MatchStmt::cases_size() const { return static_cast<int>(m_cases.size()); }
inline CaseArm* MatchStmt::add_cases() { return &m_cases.emplace_back(); }
inline bool MatchStmt::_lee(detalle::Lector& lector, std::size_t fin) {
    while (lector.pos() < fin) {
        std::uint64_t etiqueta;
        if (!lector.varint(etiqueta)) return false;
        const int tipo = static_cast<int>(etiqueta & 7);
        switch (etiqueta >> 3) {
        case 1: {
            if (tipo != 2) { if (!lector.salta(tipo)) return false; break; }
            std::size_t hasta;
            if (!lector.largo(hasta, fin)) return false;
            if (!m_subject.crea()._lee(lector, hasta)) return false;
            break;
        }
        case 2: {
            if (tipo != 2) { if (!lector.salta(tipo)) return false; break; }
            std::size_t hasta;
            if (!lector.largo(hasta, fin)) return false;
            if (!m_cases.emplace_back()._lee(lector, hasta)) return false;
            break;
        }
        default:
            if (!lector.salta(tipo)) return false;
        }
    }
    return lector.pos() == fin;
}

inline ReturnStmt::ReturnStmt() = default;
inline ReturnStmt::ReturnStmt(const ReturnStmt&) = default;
inline ReturnStmt& ReturnStmt::operator=(const ReturnStmt&) = default;
inline ReturnStmt::ReturnStmt(ReturnStmt&&) noexcept = default;
inline ReturnStmt& ReturnStmt::operator=(ReturnStmt&&) noexcept = default;
inline ReturnStmt::~ReturnStmt() = default;
inline const ReturnStmt& ReturnStmt::default_instance() { static const ReturnStmt vacio; return vacio; }
inline bool ReturnStmt::ParseFromString(const std::string& datos) {
    return ParseFromArray(datos.data(), static_cast<int>(datos.size()));
}
inline bool ReturnStmt::ParseFromArray(const void* datos, int largo) {
    *this = ReturnStmt();
    detalle::Lector lector(static_cast<const unsigned char*>(datos),
                           static_cast<std::size_t>(largo));
    return _lee(lector, static_cast<std::size_t>(largo));
}
inline bool ReturnStmt::ParseFromIstream(std::istream* entrada) {
    std::string datos((std::istreambuf_iterator<char>(*entrada)),
                      std::istreambuf_iterator<char>());
    if (entrada->bad()) return false;
    return ParseFromString(datos);
}
inline bool ReturnStmt::has_value() const { return m_value.hay(); }
inline const Expr& ReturnStmt::value() const { return m_value.hay() ? m_value.valor() : Expr::default_instance(); }
inline Expr* ReturnStmt::mutable_value() { return &m_value.crea(); }
inline bool ReturnStmt::transfers() const { return m_transfers; }
inline void ReturnStmt::set_transfers(bool valor) { m_transfers = std::move(valor); }
inline bool ReturnStmt::_lee(detalle::Lector& lector, std::size_t fin) {
    while (lector.pos() < fin) {
        std::uint64_t etiqueta;
        if (!lector.varint(etiqueta)) return false;
        const int tipo = static_cast<int>(etiqueta & 7);
        switch (etiqueta >> 3) {
        case 1: {
            if (tipo != 2) { if (!lector.salta(tipo)) return false; break; }
            std::size_t hasta;
            if (!lector.largo(hasta, fin)) return false;
            if (!m_value.crea()._lee(lector, hasta)) return false;
            break;
        }
        case 2: {
            if (tipo != 0) { if (!lector.salta(tipo)) return false; break; }
            std::uint64_t v; if (!lector.varint(v)) return false; m_transfers = v != 0;
            break;
        }
        default:
            if (!lector.salta(tipo)) return false;
        }
    }
    return lector.pos() == fin;
}

inline BreakStmt::BreakStmt() = default;
inline BreakStmt::BreakStmt(const BreakStmt&) = default;
inline BreakStmt& BreakStmt::operator=(const BreakStmt&) = default;
inline BreakStmt::BreakStmt(BreakStmt&&) noexcept = default;
inline BreakStmt& BreakStmt::operator=(BreakStmt&&) noexcept = default;
inline BreakStmt::~BreakStmt() = default;
inline const BreakStmt& BreakStmt::default_instance() { static const BreakStmt vacio; return vacio; }
inline bool BreakStmt::ParseFromString(const std::string& datos) {
    return ParseFromArray(datos.data(), static_cast<int>(datos.size()));
}
inline bool BreakStmt::ParseFromArray(const void* datos, int largo) {
    *this = BreakStmt();
    detalle::Lector lector(static_cast<const unsigned char*>(datos),
                           static_cast<std::size_t>(largo));
    return _lee(lector, static_cast<std::size_t>(largo));
}
inline bool BreakStmt::ParseFromIstream(std::istream* entrada) {
    std::string datos((std::istreambuf_iterator<char>(*entrada)),
                      std::istreambuf_iterator<char>());
    if (entrada->bad()) return false;
    return ParseFromString(datos);
}
inline bool BreakStmt::_lee(detalle::Lector& lector, std::size_t fin) {
    while (lector.pos() < fin) {
        std::uint64_t etiqueta;
        if (!lector.varint(etiqueta)) return false;
        const int tipo = static_cast<int>(etiqueta & 7);
        if (!lector.salta(tipo)) return false;
    }
    return lector.pos() == fin;
}

inline ContinueStmt::ContinueStmt() = default;
inline ContinueStmt::ContinueStmt(const ContinueStmt&) = default;
inline ContinueStmt& ContinueStmt::operator=(const ContinueStmt&) = default;
inline ContinueStmt::ContinueStmt(ContinueStmt&&) noexcept = default;
inline ContinueStmt& ContinueStmt::operator=(ContinueStmt&&) noexcept = default;
inline ContinueStmt::~ContinueStmt() = default;
inline const ContinueStmt& ContinueStmt::default_instance() { static const ContinueStmt vacio; return vacio; }
inline bool ContinueStmt::ParseFromString(const std::string& datos) {
    return ParseFromArray(datos.data(), static_cast<int>(datos.size()));
}
inline bool ContinueStmt::ParseFromArray(const void* datos, int largo) {
    *this = ContinueStmt();
    detalle::Lector lector(static_cast<const unsigned char*>(datos),
                           static_cast<std::size_t>(largo));
    return _lee(lector, static_cast<std::size_t>(largo));
}
inline bool ContinueStmt::ParseFromIstream(std::istream* entrada) {
    std::string datos((std::istreambuf_iterator<char>(*entrada)),
                      std::istreambuf_iterator<char>());
    if (entrada->bad()) return false;
    return ParseFromString(datos);
}
inline bool ContinueStmt::_lee(detalle::Lector& lector, std::size_t fin) {
    while (lector.pos() < fin) {
        std::uint64_t etiqueta;
        if (!lector.varint(etiqueta)) return false;
        const int tipo = static_cast<int>(etiqueta & 7);
        if (!lector.salta(tipo)) return false;
    }
    return lector.pos() == fin;
}

inline MoveStmt::MoveStmt() = default;
inline MoveStmt::MoveStmt(const MoveStmt&) = default;
inline MoveStmt& MoveStmt::operator=(const MoveStmt&) = default;
inline MoveStmt::MoveStmt(MoveStmt&&) noexcept = default;
inline MoveStmt& MoveStmt::operator=(MoveStmt&&) noexcept = default;
inline MoveStmt::~MoveStmt() = default;
inline const MoveStmt& MoveStmt::default_instance() { static const MoveStmt vacio; return vacio; }
inline bool MoveStmt::ParseFromString(const std::string& datos) {
    return ParseFromArray(datos.data(), static_cast<int>(datos.size()));
}
inline bool MoveStmt::ParseFromArray(const void* datos, int largo) {
    *this = MoveStmt();
    detalle::Lector lector(static_cast<const unsigned char*>(datos),
                           static_cast<std::size_t>(largo));
    return _lee(lector, static_cast<std::size_t>(largo));
}
inline bool MoveStmt::ParseFromIstream(std::istream* entrada) {
    std::string datos((std::istreambuf_iterator<char>(*entrada)),
                      std::istreambuf_iterator<char>());
    if (entrada->bad()) return false;
    return ParseFromString(datos);
}
inline bool MoveStmt::has_target() const { return m_target.hay(); }
inline const Expr& MoveStmt::target() const { return m_target.hay() ? m_target.valor() : Expr::default_instance(); }
inline Expr* MoveStmt::mutable_target() { return &m_target.crea(); }
inline bool MoveStmt::_lee(detalle::Lector& lector, std::size_t fin) {
    while (lector.pos() < fin) {
        std::uint64_t etiqueta;
        if (!lector.varint(etiqueta)) return false;
        const int tipo = static_cast<int>(etiqueta & 7);
        switch (etiqueta >> 3) {
        case 1: {
            if (tipo != 2) { if (!lector.salta(tipo)) return false; break; }
            std::size_t hasta;
            if (!lector.largo(hasta, fin)) return false;
            if (!m_target.crea()._lee(lector, hasta)) return false;
            break;
        }
        default:
            if (!lector.salta(tipo)) return false;
        }
    }
    return lector.pos() == fin;
}

inline ThrowStmt::ThrowStmt() = default;
inline ThrowStmt::ThrowStmt(const ThrowStmt&) = default;
inline ThrowStmt& ThrowStmt::operator=(const ThrowStmt&) = default;
inline ThrowStmt::ThrowStmt(ThrowStmt&&) noexcept = default;
inline ThrowStmt& ThrowStmt::operator=(ThrowStmt&&) noexcept = default;
inline ThrowStmt::~ThrowStmt() = default;
inline const ThrowStmt& ThrowStmt::default_instance() { static const ThrowStmt vacio; return vacio; }
inline bool ThrowStmt::ParseFromString(const std::string& datos) {
    return ParseFromArray(datos.data(), static_cast<int>(datos.size()));
}
inline bool ThrowStmt::ParseFromArray(const void* datos, int largo) {
    *this = ThrowStmt();
    detalle::Lector lector(static_cast<const unsigned char*>(datos),
                           static_cast<std::size_t>(largo));
    return _lee(lector, static_cast<std::size_t>(largo));
}
inline bool ThrowStmt::ParseFromIstream(std::istream* entrada) {
    std::string datos((std::istreambuf_iterator<char>(*entrada)),
                      std::istreambuf_iterator<char>());
    if (entrada->bad()) return false;
    return ParseFromString(datos);
}
inline bool ThrowStmt::has_value() const { return m_value.hay(); }
inline const Expr& ThrowStmt::value() const { return m_value.hay() ? m_value.valor() : Expr::default_instance(); }
inline Expr* ThrowStmt::mutable_value() { return &m_value.crea(); }
inline bool ThrowStmt::_lee(detalle::Lector& lector, std::size_t fin) {
    while (lector.pos() < fin) {
        std::uint64_t etiqueta;
        if (!lector.varint(etiqueta)) return false;
        const int tipo = static_cast<int>(etiqueta & 7);
        switch (etiqueta >> 3) {
        case 1: {
            if (tipo != 2) { if (!lector.salta(tipo)) return false; break; }
            std::size_t hasta;
            if (!lector.largo(hasta, fin)) return false;
            if (!m_value.crea()._lee(lector, hasta)) return false;
            break;
        }
        default:
            if (!lector.salta(tipo)) return false;
        }
    }
    return lector.pos() == fin;
}

inline CatchClause::CatchClause() = default;
inline CatchClause::CatchClause(const CatchClause&) = default;
inline CatchClause& CatchClause::operator=(const CatchClause&) = default;
inline CatchClause::CatchClause(CatchClause&&) noexcept = default;
inline CatchClause& CatchClause::operator=(CatchClause&&) noexcept = default;
inline CatchClause::~CatchClause() = default;
inline const CatchClause& CatchClause::default_instance() { static const CatchClause vacio; return vacio; }
inline bool CatchClause::ParseFromString(const std::string& datos) {
    return ParseFromArray(datos.data(), static_cast<int>(datos.size()));
}
inline bool CatchClause::ParseFromArray(const void* datos, int largo) {
    *this = CatchClause();
    detalle::Lector lector(static_cast<const unsigned char*>(datos),
                           static_cast<std::size_t>(largo));
    return _lee(lector, static_cast<std::size_t>(largo));
}
inline bool CatchClause::ParseFromIstream(std::istream* entrada) {
    std::string datos((std::istreambuf_iterator<char>(*entrada)),
                      std::istreambuf_iterator<char>());
    if (entrada->bad()) return false;
    return ParseFromString(datos);
}
inline const std::string& CatchClause::name() const { return m_name; }
inline void CatchClause::set_name(std::string valor) { m_name = std::move(valor); }
inline bool CatchClause::has_block() const { return m_block.hay(); }
inline const Block& CatchClause::block() const { return m_block.hay() ? m_block.valor() : Block::default_instance(); }
inline Block* CatchClause::mutable_block() { return &m_block.crea(); }
inline bool CatchClause::has_type() const { return m_type.hay(); }
inline const Type& CatchClause::type() const { return m_type.hay() ? m_type.valor() : Type::default_instance(); }
inline Type* CatchClause::mutable_type() { return &m_type.crea(); }
inline bool CatchClause::_lee(detalle::Lector& lector, std::size_t fin) {
    while (lector.pos() < fin) {
        std::uint64_t etiqueta;
        if (!lector.varint(etiqueta)) return false;
        const int tipo = static_cast<int>(etiqueta & 7);
        switch (etiqueta >> 3) {
        case 1: {
            if (tipo != 2) { if (!lector.salta(tipo)) return false; break; }
            if (!lector.texto(m_name, fin)) return false;
            break;
        }
        case 2: {
            if (tipo != 2) { if (!lector.salta(tipo)) return false; break; }
            std::size_t hasta;
            if (!lector.largo(hasta, fin)) return false;
            if (!m_block.crea()._lee(lector, hasta)) return false;
            break;
        }
        case 3: {
            if (tipo != 2) { if (!lector.salta(tipo)) return false; break; }
            std::size_t hasta;
            if (!lector.largo(hasta, fin)) return false;
            if (!m_type.crea()._lee(lector, hasta)) return false;
            break;
        }
        default:
            if (!lector.salta(tipo)) return false;
        }
    }
    return lector.pos() == fin;
}

inline TryStmt::TryStmt() = default;
inline TryStmt::TryStmt(const TryStmt&) = default;
inline TryStmt& TryStmt::operator=(const TryStmt&) = default;
inline TryStmt::TryStmt(TryStmt&&) noexcept = default;
inline TryStmt& TryStmt::operator=(TryStmt&&) noexcept = default;
inline TryStmt::~TryStmt() = default;
inline const TryStmt& TryStmt::default_instance() { static const TryStmt vacio; return vacio; }
inline bool TryStmt::ParseFromString(const std::string& datos) {
    return ParseFromArray(datos.data(), static_cast<int>(datos.size()));
}
inline bool TryStmt::ParseFromArray(const void* datos, int largo) {
    *this = TryStmt();
    detalle::Lector lector(static_cast<const unsigned char*>(datos),
                           static_cast<std::size_t>(largo));
    return _lee(lector, static_cast<std::size_t>(largo));
}
inline bool TryStmt::ParseFromIstream(std::istream* entrada) {
    std::string datos((std::istreambuf_iterator<char>(*entrada)),
                      std::istreambuf_iterator<char>());
    if (entrada->bad()) return false;
    return ParseFromString(datos);
}
inline bool TryStmt::has_try_block() const { return m_try_block.hay(); }
inline const Block& TryStmt::try_block() const { return m_try_block.hay() ? m_try_block.valor() : Block::default_instance(); }
inline Block* TryStmt::mutable_try_block() { return &m_try_block.crea(); }
inline const std::vector<CatchClause>& TryStmt::catches() const { return m_catches; }
inline const CatchClause& TryStmt::catches(int i) const { return m_catches.at(static_cast<std::size_t>(i)); }
inline int TryStmt::catches_size() const { return static_cast<int>(m_catches.size()); }
inline CatchClause* TryStmt::add_catches() { return &m_catches.emplace_back(); }
inline bool TryStmt::has_finally_block() const { return m_finally_block.hay(); }
inline const Block& TryStmt::finally_block() const { return m_finally_block.hay() ? m_finally_block.valor() : Block::default_instance(); }
inline Block* TryStmt::mutable_finally_block() { return &m_finally_block.crea(); }
inline bool TryStmt::_lee(detalle::Lector& lector, std::size_t fin) {
    while (lector.pos() < fin) {
        std::uint64_t etiqueta;
        if (!lector.varint(etiqueta)) return false;
        const int tipo = static_cast<int>(etiqueta & 7);
        switch (etiqueta >> 3) {
        case 1: {
            if (tipo != 2) { if (!lector.salta(tipo)) return false; break; }
            std::size_t hasta;
            if (!lector.largo(hasta, fin)) return false;
            if (!m_try_block.crea()._lee(lector, hasta)) return false;
            break;
        }
        case 4: {
            if (tipo != 2) { if (!lector.salta(tipo)) return false; break; }
            std::size_t hasta;
            if (!lector.largo(hasta, fin)) return false;
            if (!m_catches.emplace_back()._lee(lector, hasta)) return false;
            break;
        }
        case 5: {
            if (tipo != 2) { if (!lector.salta(tipo)) return false; break; }
            std::size_t hasta;
            if (!lector.largo(hasta, fin)) return false;
            if (!m_finally_block.crea()._lee(lector, hasta)) return false;
            break;
        }
        default:
            if (!lector.salta(tipo)) return false;
        }
    }
    return lector.pos() == fin;
}

inline FreeStmt::FreeStmt() = default;
inline FreeStmt::FreeStmt(const FreeStmt&) = default;
inline FreeStmt& FreeStmt::operator=(const FreeStmt&) = default;
inline FreeStmt::FreeStmt(FreeStmt&&) noexcept = default;
inline FreeStmt& FreeStmt::operator=(FreeStmt&&) noexcept = default;
inline FreeStmt::~FreeStmt() = default;
inline const FreeStmt& FreeStmt::default_instance() { static const FreeStmt vacio; return vacio; }
inline bool FreeStmt::ParseFromString(const std::string& datos) {
    return ParseFromArray(datos.data(), static_cast<int>(datos.size()));
}
inline bool FreeStmt::ParseFromArray(const void* datos, int largo) {
    *this = FreeStmt();
    detalle::Lector lector(static_cast<const unsigned char*>(datos),
                           static_cast<std::size_t>(largo));
    return _lee(lector, static_cast<std::size_t>(largo));
}
inline bool FreeStmt::ParseFromIstream(std::istream* entrada) {
    std::string datos((std::istreambuf_iterator<char>(*entrada)),
                      std::istreambuf_iterator<char>());
    if (entrada->bad()) return false;
    return ParseFromString(datos);
}
inline bool FreeStmt::has_target() const { return m_target.hay(); }
inline const Expr& FreeStmt::target() const { return m_target.hay() ? m_target.valor() : Expr::default_instance(); }
inline Expr* FreeStmt::mutable_target() { return &m_target.crea(); }
inline bool FreeStmt::has_hook() const { return m_hook.hay(); }
inline const HookRef& FreeStmt::hook() const { return m_hook.hay() ? m_hook.valor() : HookRef::default_instance(); }
inline HookRef* FreeStmt::mutable_hook() { return &m_hook.crea(); }
inline bool FreeStmt::_lee(detalle::Lector& lector, std::size_t fin) {
    while (lector.pos() < fin) {
        std::uint64_t etiqueta;
        if (!lector.varint(etiqueta)) return false;
        const int tipo = static_cast<int>(etiqueta & 7);
        switch (etiqueta >> 3) {
        case 1: {
            if (tipo != 2) { if (!lector.salta(tipo)) return false; break; }
            std::size_t hasta;
            if (!lector.largo(hasta, fin)) return false;
            if (!m_target.crea()._lee(lector, hasta)) return false;
            break;
        }
        case 2: {
            if (tipo != 2) { if (!lector.salta(tipo)) return false; break; }
            std::size_t hasta;
            if (!lector.largo(hasta, fin)) return false;
            if (!m_hook.crea()._lee(lector, hasta)) return false;
            break;
        }
        default:
            if (!lector.salta(tipo)) return false;
        }
    }
    return lector.pos() == fin;
}

inline ExprStmt::ExprStmt() = default;
inline ExprStmt::ExprStmt(const ExprStmt&) = default;
inline ExprStmt& ExprStmt::operator=(const ExprStmt&) = default;
inline ExprStmt::ExprStmt(ExprStmt&&) noexcept = default;
inline ExprStmt& ExprStmt::operator=(ExprStmt&&) noexcept = default;
inline ExprStmt::~ExprStmt() = default;
inline const ExprStmt& ExprStmt::default_instance() { static const ExprStmt vacio; return vacio; }
inline bool ExprStmt::ParseFromString(const std::string& datos) {
    return ParseFromArray(datos.data(), static_cast<int>(datos.size()));
}
inline bool ExprStmt::ParseFromArray(const void* datos, int largo) {
    *this = ExprStmt();
    detalle::Lector lector(static_cast<const unsigned char*>(datos),
                           static_cast<std::size_t>(largo));
    return _lee(lector, static_cast<std::size_t>(largo));
}
inline bool ExprStmt::ParseFromIstream(std::istream* entrada) {
    std::string datos((std::istreambuf_iterator<char>(*entrada)),
                      std::istreambuf_iterator<char>());
    if (entrada->bad()) return false;
    return ParseFromString(datos);
}
inline bool ExprStmt::has_expr() const { return m_expr.hay(); }
inline const Expr& ExprStmt::expr() const { return m_expr.hay() ? m_expr.valor() : Expr::default_instance(); }
inline Expr* ExprStmt::mutable_expr() { return &m_expr.crea(); }
inline bool ExprStmt::_lee(detalle::Lector& lector, std::size_t fin) {
    while (lector.pos() < fin) {
        std::uint64_t etiqueta;
        if (!lector.varint(etiqueta)) return false;
        const int tipo = static_cast<int>(etiqueta & 7);
        switch (etiqueta >> 3) {
        case 1: {
            if (tipo != 2) { if (!lector.salta(tipo)) return false; break; }
            std::size_t hasta;
            if (!lector.largo(hasta, fin)) return false;
            if (!m_expr.crea()._lee(lector, hasta)) return false;
            break;
        }
        default:
            if (!lector.salta(tipo)) return false;
        }
    }
    return lector.pos() == fin;
}

inline ImportBinding::ImportBinding() = default;
inline ImportBinding::ImportBinding(const ImportBinding&) = default;
inline ImportBinding& ImportBinding::operator=(const ImportBinding&) = default;
inline ImportBinding::ImportBinding(ImportBinding&&) noexcept = default;
inline ImportBinding& ImportBinding::operator=(ImportBinding&&) noexcept = default;
inline ImportBinding::~ImportBinding() = default;
inline const ImportBinding& ImportBinding::default_instance() { static const ImportBinding vacio; return vacio; }
inline bool ImportBinding::ParseFromString(const std::string& datos) {
    return ParseFromArray(datos.data(), static_cast<int>(datos.size()));
}
inline bool ImportBinding::ParseFromArray(const void* datos, int largo) {
    *this = ImportBinding();
    detalle::Lector lector(static_cast<const unsigned char*>(datos),
                           static_cast<std::size_t>(largo));
    return _lee(lector, static_cast<std::size_t>(largo));
}
inline bool ImportBinding::ParseFromIstream(std::istream* entrada) {
    std::string datos((std::istreambuf_iterator<char>(*entrada)),
                      std::istreambuf_iterator<char>());
    if (entrada->bad()) return false;
    return ParseFromString(datos);
}
inline const std::string& ImportBinding::qualifier() const { return m_qualifier; }
inline void ImportBinding::set_qualifier(std::string valor) { m_qualifier = std::move(valor); }
inline const std::string& ImportBinding::name() const { return m_name; }
inline void ImportBinding::set_name(std::string valor) { m_name = std::move(valor); }
inline const std::string& ImportBinding::lib() const { return m_lib; }
inline void ImportBinding::set_lib(std::string valor) { m_lib = std::move(valor); }
inline const std::string& ImportBinding::member() const { return m_member; }
inline void ImportBinding::set_member(std::string valor) { m_member = std::move(valor); }
inline bool ImportBinding::_lee(detalle::Lector& lector, std::size_t fin) {
    while (lector.pos() < fin) {
        std::uint64_t etiqueta;
        if (!lector.varint(etiqueta)) return false;
        const int tipo = static_cast<int>(etiqueta & 7);
        switch (etiqueta >> 3) {
        case 1: {
            if (tipo != 2) { if (!lector.salta(tipo)) return false; break; }
            if (!lector.texto(m_qualifier, fin)) return false;
            break;
        }
        case 2: {
            if (tipo != 2) { if (!lector.salta(tipo)) return false; break; }
            if (!lector.texto(m_name, fin)) return false;
            break;
        }
        case 3: {
            if (tipo != 2) { if (!lector.salta(tipo)) return false; break; }
            if (!lector.texto(m_lib, fin)) return false;
            break;
        }
        case 4: {
            if (tipo != 2) { if (!lector.salta(tipo)) return false; break; }
            if (!lector.texto(m_member, fin)) return false;
            break;
        }
        default:
            if (!lector.salta(tipo)) return false;
        }
    }
    return lector.pos() == fin;
}

inline Decl::Decl() = default;
inline Decl::Decl(const Decl&) = default;
inline Decl& Decl::operator=(const Decl&) = default;
inline Decl::Decl(Decl&&) noexcept = default;
inline Decl& Decl::operator=(Decl&&) noexcept = default;
inline Decl::~Decl() = default;
inline const Decl& Decl::default_instance() { static const Decl vacio; return vacio; }
inline bool Decl::ParseFromString(const std::string& datos) {
    return ParseFromArray(datos.data(), static_cast<int>(datos.size()));
}
inline bool Decl::ParseFromArray(const void* datos, int largo) {
    *this = Decl();
    detalle::Lector lector(static_cast<const unsigned char*>(datos),
                           static_cast<std::size_t>(largo));
    return _lee(lector, static_cast<std::size_t>(largo));
}
inline bool Decl::ParseFromIstream(std::istream* entrada) {
    std::string datos((std::istreambuf_iterator<char>(*entrada)),
                      std::istreambuf_iterator<char>());
    if (entrada->bad()) return false;
    return ParseFromString(datos);
}
inline Decl::NodeCase Decl::node_case() const { return static_cast<NodeCase>(node_caso_); }
inline std::uint32_t Decl::ln() const { return m_ln; }
inline void Decl::set_ln(std::uint32_t valor) { m_ln = std::move(valor); }
inline std::uint32_t Decl::col() const { return m_col; }
inline void Decl::set_col(std::uint32_t valor) { m_col = std::move(valor); }
inline bool Decl::has_function() const { return node_caso_ == kFunction; }
inline const FunctionDecl& Decl::function() const {
    return node_caso_ == kFunction && m_function.hay() ? m_function.valor() : FunctionDecl::default_instance();
}
inline FunctionDecl* Decl::mutable_function() { node_caso_ = kFunction; return &m_function.crea(); }
inline bool Decl::has_struct_decl() const { return node_caso_ == kStructDecl; }
inline const StructDecl& Decl::struct_decl() const {
    return node_caso_ == kStructDecl && m_struct_decl.hay() ? m_struct_decl.valor() : StructDecl::default_instance();
}
inline StructDecl* Decl::mutable_struct_decl() { node_caso_ = kStructDecl; return &m_struct_decl.crea(); }
inline bool Decl::has_enum_decl() const { return node_caso_ == kEnumDecl; }
inline const EnumDecl& Decl::enum_decl() const {
    return node_caso_ == kEnumDecl && m_enum_decl.hay() ? m_enum_decl.valor() : EnumDecl::default_instance();
}
inline EnumDecl* Decl::mutable_enum_decl() { node_caso_ = kEnumDecl; return &m_enum_decl.crea(); }
inline bool Decl::has_extern_block() const { return node_caso_ == kExternBlock; }
inline const ExternBlock& Decl::extern_block() const {
    return node_caso_ == kExternBlock && m_extern_block.hay() ? m_extern_block.valor() : ExternBlock::default_instance();
}
inline ExternBlock* Decl::mutable_extern_block() { node_caso_ = kExternBlock; return &m_extern_block.crea(); }
inline bool Decl::has_statement() const { return node_caso_ == kStatement; }
inline const Stmt& Decl::statement() const {
    return node_caso_ == kStatement && m_statement.hay() ? m_statement.valor() : Stmt::default_instance();
}
inline Stmt* Decl::mutable_statement() { node_caso_ = kStatement; return &m_statement.crea(); }
inline bool Decl::has_import_directive() const { return node_caso_ == kImportDirective; }
inline const ImportDirective& Decl::import_directive() const {
    return node_caso_ == kImportDirective && m_import_directive.hay() ? m_import_directive.valor() : ImportDirective::default_instance();
}
inline ImportDirective* Decl::mutable_import_directive() { node_caso_ = kImportDirective; return &m_import_directive.crea(); }
inline bool Decl::has_export_directive() const { return node_caso_ == kExportDirective; }
inline const ExportDirective& Decl::export_directive() const {
    return node_caso_ == kExportDirective && m_export_directive.hay() ? m_export_directive.valor() : ExportDirective::default_instance();
}
inline ExportDirective* Decl::mutable_export_directive() { node_caso_ = kExportDirective; return &m_export_directive.crea(); }
inline bool Decl::has_from_directive() const { return node_caso_ == kFromDirective; }
inline const FromDirective& Decl::from_directive() const {
    return node_caso_ == kFromDirective && m_from_directive.hay() ? m_from_directive.valor() : FromDirective::default_instance();
}
inline FromDirective* Decl::mutable_from_directive() { node_caso_ = kFromDirective; return &m_from_directive.crea(); }
inline bool Decl::has_test_decl() const { return node_caso_ == kTestDecl; }
inline const TestDecl& Decl::test_decl() const {
    return node_caso_ == kTestDecl && m_test_decl.hay() ? m_test_decl.valor() : TestDecl::default_instance();
}
inline TestDecl* Decl::mutable_test_decl() { node_caso_ = kTestDecl; return &m_test_decl.crea(); }
inline bool Decl::_lee(detalle::Lector& lector, std::size_t fin) {
    while (lector.pos() < fin) {
        std::uint64_t etiqueta;
        if (!lector.varint(etiqueta)) return false;
        const int tipo = static_cast<int>(etiqueta & 7);
        switch (etiqueta >> 3) {
        case 1: {
            if (tipo != 0) { if (!lector.salta(tipo)) return false; break; }
            std::uint64_t v; if (!lector.varint(v)) return false; m_ln = static_cast<std::uint32_t>(v);
            break;
        }
        case 2: {
            if (tipo != 0) { if (!lector.salta(tipo)) return false; break; }
            std::uint64_t v; if (!lector.varint(v)) return false; m_col = static_cast<std::uint32_t>(v);
            break;
        }
        case 10: {
            if (tipo != 2) { if (!lector.salta(tipo)) return false; break; }
            std::size_t hasta;
            if (!lector.largo(hasta, fin)) return false;
            node_caso_ = kFunction;
            if (!m_function.crea()._lee(lector, hasta)) return false;
            break;
        }
        case 11: {
            if (tipo != 2) { if (!lector.salta(tipo)) return false; break; }
            std::size_t hasta;
            if (!lector.largo(hasta, fin)) return false;
            node_caso_ = kStructDecl;
            if (!m_struct_decl.crea()._lee(lector, hasta)) return false;
            break;
        }
        case 12: {
            if (tipo != 2) { if (!lector.salta(tipo)) return false; break; }
            std::size_t hasta;
            if (!lector.largo(hasta, fin)) return false;
            node_caso_ = kEnumDecl;
            if (!m_enum_decl.crea()._lee(lector, hasta)) return false;
            break;
        }
        case 13: {
            if (tipo != 2) { if (!lector.salta(tipo)) return false; break; }
            std::size_t hasta;
            if (!lector.largo(hasta, fin)) return false;
            node_caso_ = kExternBlock;
            if (!m_extern_block.crea()._lee(lector, hasta)) return false;
            break;
        }
        case 14: {
            if (tipo != 2) { if (!lector.salta(tipo)) return false; break; }
            std::size_t hasta;
            if (!lector.largo(hasta, fin)) return false;
            node_caso_ = kStatement;
            if (!m_statement.crea()._lee(lector, hasta)) return false;
            break;
        }
        case 15: {
            if (tipo != 2) { if (!lector.salta(tipo)) return false; break; }
            std::size_t hasta;
            if (!lector.largo(hasta, fin)) return false;
            node_caso_ = kImportDirective;
            if (!m_import_directive.crea()._lee(lector, hasta)) return false;
            break;
        }
        case 16: {
            if (tipo != 2) { if (!lector.salta(tipo)) return false; break; }
            std::size_t hasta;
            if (!lector.largo(hasta, fin)) return false;
            node_caso_ = kExportDirective;
            if (!m_export_directive.crea()._lee(lector, hasta)) return false;
            break;
        }
        case 17: {
            if (tipo != 2) { if (!lector.salta(tipo)) return false; break; }
            std::size_t hasta;
            if (!lector.largo(hasta, fin)) return false;
            node_caso_ = kFromDirective;
            if (!m_from_directive.crea()._lee(lector, hasta)) return false;
            break;
        }
        case 18: {
            if (tipo != 2) { if (!lector.salta(tipo)) return false; break; }
            std::size_t hasta;
            if (!lector.largo(hasta, fin)) return false;
            node_caso_ = kTestDecl;
            if (!m_test_decl.crea()._lee(lector, hasta)) return false;
            break;
        }
        default:
            if (!lector.salta(tipo)) return false;
        }
    }
    return lector.pos() == fin;
}

inline TestDecl::TestDecl() = default;
inline TestDecl::TestDecl(const TestDecl&) = default;
inline TestDecl& TestDecl::operator=(const TestDecl&) = default;
inline TestDecl::TestDecl(TestDecl&&) noexcept = default;
inline TestDecl& TestDecl::operator=(TestDecl&&) noexcept = default;
inline TestDecl::~TestDecl() = default;
inline const TestDecl& TestDecl::default_instance() { static const TestDecl vacio; return vacio; }
inline bool TestDecl::ParseFromString(const std::string& datos) {
    return ParseFromArray(datos.data(), static_cast<int>(datos.size()));
}
inline bool TestDecl::ParseFromArray(const void* datos, int largo) {
    *this = TestDecl();
    detalle::Lector lector(static_cast<const unsigned char*>(datos),
                           static_cast<std::size_t>(largo));
    return _lee(lector, static_cast<std::size_t>(largo));
}
inline bool TestDecl::ParseFromIstream(std::istream* entrada) {
    std::string datos((std::istreambuf_iterator<char>(*entrada)),
                      std::istreambuf_iterator<char>());
    if (entrada->bad()) return false;
    return ParseFromString(datos);
}
inline const std::string& TestDecl::name() const { return m_name; }
inline void TestDecl::set_name(std::string valor) { m_name = std::move(valor); }
inline bool TestDecl::has_body() const { return m_body.hay(); }
inline const Block& TestDecl::body() const { return m_body.hay() ? m_body.valor() : Block::default_instance(); }
inline Block* TestDecl::mutable_body() { return &m_body.crea(); }
inline bool TestDecl::_lee(detalle::Lector& lector, std::size_t fin) {
    while (lector.pos() < fin) {
        std::uint64_t etiqueta;
        if (!lector.varint(etiqueta)) return false;
        const int tipo = static_cast<int>(etiqueta & 7);
        switch (etiqueta >> 3) {
        case 1: {
            if (tipo != 2) { if (!lector.salta(tipo)) return false; break; }
            if (!lector.texto(m_name, fin)) return false;
            break;
        }
        case 2: {
            if (tipo != 2) { if (!lector.salta(tipo)) return false; break; }
            std::size_t hasta;
            if (!lector.largo(hasta, fin)) return false;
            if (!m_body.crea()._lee(lector, hasta)) return false;
            break;
        }
        default:
            if (!lector.salta(tipo)) return false;
        }
    }
    return lector.pos() == fin;
}

inline Parameter::Parameter() = default;
inline Parameter::Parameter(const Parameter&) = default;
inline Parameter& Parameter::operator=(const Parameter&) = default;
inline Parameter::Parameter(Parameter&&) noexcept = default;
inline Parameter& Parameter::operator=(Parameter&&) noexcept = default;
inline Parameter::~Parameter() = default;
inline const Parameter& Parameter::default_instance() { static const Parameter vacio; return vacio; }
inline bool Parameter::ParseFromString(const std::string& datos) {
    return ParseFromArray(datos.data(), static_cast<int>(datos.size()));
}
inline bool Parameter::ParseFromArray(const void* datos, int largo) {
    *this = Parameter();
    detalle::Lector lector(static_cast<const unsigned char*>(datos),
                           static_cast<std::size_t>(largo));
    return _lee(lector, static_cast<std::size_t>(largo));
}
inline bool Parameter::ParseFromIstream(std::istream* entrada) {
    std::string datos((std::istreambuf_iterator<char>(*entrada)),
                      std::istreambuf_iterator<char>());
    if (entrada->bad()) return false;
    return ParseFromString(datos);
}
inline const std::string& Parameter::name() const { return m_name; }
inline void Parameter::set_name(std::string valor) { m_name = std::move(valor); }
inline std::uint32_t Parameter::type_id() const { return m_type_id; }
inline void Parameter::set_type_id(std::uint32_t valor) { m_type_id = std::move(valor); }
inline bool Parameter::_lee(detalle::Lector& lector, std::size_t fin) {
    while (lector.pos() < fin) {
        std::uint64_t etiqueta;
        if (!lector.varint(etiqueta)) return false;
        const int tipo = static_cast<int>(etiqueta & 7);
        switch (etiqueta >> 3) {
        case 2: {
            if (tipo != 2) { if (!lector.salta(tipo)) return false; break; }
            if (!lector.texto(m_name, fin)) return false;
            break;
        }
        case 3: {
            if (tipo != 0) { if (!lector.salta(tipo)) return false; break; }
            std::uint64_t v; if (!lector.varint(v)) return false; m_type_id = static_cast<std::uint32_t>(v);
            break;
        }
        default:
            if (!lector.salta(tipo)) return false;
        }
    }
    return lector.pos() == fin;
}

inline FunctionDecl::FunctionDecl() = default;
inline FunctionDecl::FunctionDecl(const FunctionDecl&) = default;
inline FunctionDecl& FunctionDecl::operator=(const FunctionDecl&) = default;
inline FunctionDecl::FunctionDecl(FunctionDecl&&) noexcept = default;
inline FunctionDecl& FunctionDecl::operator=(FunctionDecl&&) noexcept = default;
inline FunctionDecl::~FunctionDecl() = default;
inline const FunctionDecl& FunctionDecl::default_instance() { static const FunctionDecl vacio; return vacio; }
inline bool FunctionDecl::ParseFromString(const std::string& datos) {
    return ParseFromArray(datos.data(), static_cast<int>(datos.size()));
}
inline bool FunctionDecl::ParseFromArray(const void* datos, int largo) {
    *this = FunctionDecl();
    detalle::Lector lector(static_cast<const unsigned char*>(datos),
                           static_cast<std::size_t>(largo));
    return _lee(lector, static_cast<std::size_t>(largo));
}
inline bool FunctionDecl::ParseFromIstream(std::istream* entrada) {
    std::string datos((std::istreambuf_iterator<char>(*entrada)),
                      std::istreambuf_iterator<char>());
    if (entrada->bad()) return false;
    return ParseFromString(datos);
}
inline const std::string& FunctionDecl::name() const { return m_name; }
inline void FunctionDecl::set_name(std::string valor) { m_name = std::move(valor); }
inline const std::vector<Parameter>& FunctionDecl::params() const { return m_params; }
inline const Parameter& FunctionDecl::params(int i) const { return m_params.at(static_cast<std::size_t>(i)); }
inline int FunctionDecl::params_size() const { return static_cast<int>(m_params.size()); }
inline Parameter* FunctionDecl::add_params() { return &m_params.emplace_back(); }
inline std::uint32_t FunctionDecl::return_type_id() const { return m_return_type_id; }
inline void FunctionDecl::set_return_type_id(std::uint32_t valor) { m_return_type_id = std::move(valor); }
inline bool FunctionDecl::has_body() const { return m_body.hay(); }
inline const Block& FunctionDecl::body() const { return m_body.hay() ? m_body.valor() : Block::default_instance(); }
inline Block* FunctionDecl::mutable_body() { return &m_body.crea(); }
inline const std::string& FunctionDecl::dunder() const { return m_dunder; }
inline void FunctionDecl::set_dunder(std::string valor) { m_dunder = std::move(valor); }
inline const std::string& FunctionDecl::decorator() const { return m_decorator; }
inline void FunctionDecl::set_decorator(std::string valor) { m_decorator = std::move(valor); }
inline const std::vector<std::string>& FunctionDecl::type_params() const { return m_type_params; }
inline const std::string& FunctionDecl::type_params(int i) const { return m_type_params.at(static_cast<std::size_t>(i)); }
inline int FunctionDecl::type_params_size() const { return static_cast<int>(m_type_params.size()); }
inline bool FunctionDecl::_lee(detalle::Lector& lector, std::size_t fin) {
    while (lector.pos() < fin) {
        std::uint64_t etiqueta;
        if (!lector.varint(etiqueta)) return false;
        const int tipo = static_cast<int>(etiqueta & 7);
        switch (etiqueta >> 3) {
        case 1: {
            if (tipo != 2) { if (!lector.salta(tipo)) return false; break; }
            if (!lector.texto(m_name, fin)) return false;
            break;
        }
        case 2: {
            if (tipo != 2) { if (!lector.salta(tipo)) return false; break; }
            std::size_t hasta;
            if (!lector.largo(hasta, fin)) return false;
            if (!m_params.emplace_back()._lee(lector, hasta)) return false;
            break;
        }
        case 4: {
            if (tipo != 2) { if (!lector.salta(tipo)) return false; break; }
            std::size_t hasta;
            if (!lector.largo(hasta, fin)) return false;
            if (!m_body.crea()._lee(lector, hasta)) return false;
            break;
        }
        case 5: {
            if (tipo != 2) { if (!lector.salta(tipo)) return false; break; }
            if (!lector.texto(m_dunder, fin)) return false;
            break;
        }
        case 6: {
            if (tipo != 2) { if (!lector.salta(tipo)) return false; break; }
            if (!lector.texto(m_decorator, fin)) return false;
            break;
        }
        case 7: {
            if (tipo != 0) { if (!lector.salta(tipo)) return false; break; }
            std::uint64_t v; if (!lector.varint(v)) return false; m_return_type_id = static_cast<std::uint32_t>(v);
            break;
        }
        case 8: {
            if (tipo != 2) { if (!lector.salta(tipo)) return false; break; }
            if (!lector.texto(m_type_params.emplace_back(), fin)) return false;
            break;
        }
        default:
            if (!lector.salta(tipo)) return false;
        }
    }
    return lector.pos() == fin;
}

inline Field::Field() = default;
inline Field::Field(const Field&) = default;
inline Field& Field::operator=(const Field&) = default;
inline Field::Field(Field&&) noexcept = default;
inline Field& Field::operator=(Field&&) noexcept = default;
inline Field::~Field() = default;
inline const Field& Field::default_instance() { static const Field vacio; return vacio; }
inline bool Field::ParseFromString(const std::string& datos) {
    return ParseFromArray(datos.data(), static_cast<int>(datos.size()));
}
inline bool Field::ParseFromArray(const void* datos, int largo) {
    *this = Field();
    detalle::Lector lector(static_cast<const unsigned char*>(datos),
                           static_cast<std::size_t>(largo));
    return _lee(lector, static_cast<std::size_t>(largo));
}
inline bool Field::ParseFromIstream(std::istream* entrada) {
    std::string datos((std::istreambuf_iterator<char>(*entrada)),
                      std::istreambuf_iterator<char>());
    if (entrada->bad()) return false;
    return ParseFromString(datos);
}
inline const std::string& Field::name() const { return m_name; }
inline void Field::set_name(std::string valor) { m_name = std::move(valor); }
inline std::uint32_t Field::type_id() const { return m_type_id; }
inline void Field::set_type_id(std::uint32_t valor) { m_type_id = std::move(valor); }
inline bool Field::_lee(detalle::Lector& lector, std::size_t fin) {
    while (lector.pos() < fin) {
        std::uint64_t etiqueta;
        if (!lector.varint(etiqueta)) return false;
        const int tipo = static_cast<int>(etiqueta & 7);
        switch (etiqueta >> 3) {
        case 2: {
            if (tipo != 2) { if (!lector.salta(tipo)) return false; break; }
            if (!lector.texto(m_name, fin)) return false;
            break;
        }
        case 3: {
            if (tipo != 0) { if (!lector.salta(tipo)) return false; break; }
            std::uint64_t v; if (!lector.varint(v)) return false; m_type_id = static_cast<std::uint32_t>(v);
            break;
        }
        default:
            if (!lector.salta(tipo)) return false;
        }
    }
    return lector.pos() == fin;
}

inline StructDecl::StructDecl() = default;
inline StructDecl::StructDecl(const StructDecl&) = default;
inline StructDecl& StructDecl::operator=(const StructDecl&) = default;
inline StructDecl::StructDecl(StructDecl&&) noexcept = default;
inline StructDecl& StructDecl::operator=(StructDecl&&) noexcept = default;
inline StructDecl::~StructDecl() = default;
inline const StructDecl& StructDecl::default_instance() { static const StructDecl vacio; return vacio; }
inline bool StructDecl::ParseFromString(const std::string& datos) {
    return ParseFromArray(datos.data(), static_cast<int>(datos.size()));
}
inline bool StructDecl::ParseFromArray(const void* datos, int largo) {
    *this = StructDecl();
    detalle::Lector lector(static_cast<const unsigned char*>(datos),
                           static_cast<std::size_t>(largo));
    return _lee(lector, static_cast<std::size_t>(largo));
}
inline bool StructDecl::ParseFromIstream(std::istream* entrada) {
    std::string datos((std::istreambuf_iterator<char>(*entrada)),
                      std::istreambuf_iterator<char>());
    if (entrada->bad()) return false;
    return ParseFromString(datos);
}
inline const std::string& StructDecl::name() const { return m_name; }
inline void StructDecl::set_name(std::string valor) { m_name = std::move(valor); }
inline const std::vector<Field>& StructDecl::fields() const { return m_fields; }
inline const Field& StructDecl::fields(int i) const { return m_fields.at(static_cast<std::size_t>(i)); }
inline int StructDecl::fields_size() const { return static_cast<int>(m_fields.size()); }
inline Field* StructDecl::add_fields() { return &m_fields.emplace_back(); }
inline const std::vector<std::string>& StructDecl::type_params() const { return m_type_params; }
inline const std::string& StructDecl::type_params(int i) const { return m_type_params.at(static_cast<std::size_t>(i)); }
inline int StructDecl::type_params_size() const { return static_cast<int>(m_type_params.size()); }
inline bool StructDecl::_lee(detalle::Lector& lector, std::size_t fin) {
    while (lector.pos() < fin) {
        std::uint64_t etiqueta;
        if (!lector.varint(etiqueta)) return false;
        const int tipo = static_cast<int>(etiqueta & 7);
        switch (etiqueta >> 3) {
        case 1: {
            if (tipo != 2) { if (!lector.salta(tipo)) return false; break; }
            if (!lector.texto(m_name, fin)) return false;
            break;
        }
        case 2: {
            if (tipo != 2) { if (!lector.salta(tipo)) return false; break; }
            std::size_t hasta;
            if (!lector.largo(hasta, fin)) return false;
            if (!m_fields.emplace_back()._lee(lector, hasta)) return false;
            break;
        }
        case 3: {
            if (tipo != 2) { if (!lector.salta(tipo)) return false; break; }
            if (!lector.texto(m_type_params.emplace_back(), fin)) return false;
            break;
        }
        default:
            if (!lector.salta(tipo)) return false;
        }
    }
    return lector.pos() == fin;
}

inline EnumItem::EnumItem() = default;
inline EnumItem::EnumItem(const EnumItem&) = default;
inline EnumItem& EnumItem::operator=(const EnumItem&) = default;
inline EnumItem::EnumItem(EnumItem&&) noexcept = default;
inline EnumItem& EnumItem::operator=(EnumItem&&) noexcept = default;
inline EnumItem::~EnumItem() = default;
inline const EnumItem& EnumItem::default_instance() { static const EnumItem vacio; return vacio; }
inline bool EnumItem::ParseFromString(const std::string& datos) {
    return ParseFromArray(datos.data(), static_cast<int>(datos.size()));
}
inline bool EnumItem::ParseFromArray(const void* datos, int largo) {
    *this = EnumItem();
    detalle::Lector lector(static_cast<const unsigned char*>(datos),
                           static_cast<std::size_t>(largo));
    return _lee(lector, static_cast<std::size_t>(largo));
}
inline bool EnumItem::ParseFromIstream(std::istream* entrada) {
    std::string datos((std::istreambuf_iterator<char>(*entrada)),
                      std::istreambuf_iterator<char>());
    if (entrada->bad()) return false;
    return ParseFromString(datos);
}
inline const std::string& EnumItem::name() const { return m_name; }
inline void EnumItem::set_name(std::string valor) { m_name = std::move(valor); }
inline bool EnumItem::has_value() const { return m_value.hay(); }
inline const Expr& EnumItem::value() const { return m_value.hay() ? m_value.valor() : Expr::default_instance(); }
inline Expr* EnumItem::mutable_value() { return &m_value.crea(); }
inline const std::vector<std::uint32_t>& EnumItem::payload_type_ids() const { return m_payload_type_ids; }
inline std::uint32_t EnumItem::payload_type_ids(int i) const { return m_payload_type_ids.at(static_cast<std::size_t>(i)); }
inline int EnumItem::payload_type_ids_size() const { return static_cast<int>(m_payload_type_ids.size()); }
inline bool EnumItem::_lee(detalle::Lector& lector, std::size_t fin) {
    while (lector.pos() < fin) {
        std::uint64_t etiqueta;
        if (!lector.varint(etiqueta)) return false;
        const int tipo = static_cast<int>(etiqueta & 7);
        switch (etiqueta >> 3) {
        case 1: {
            if (tipo != 2) { if (!lector.salta(tipo)) return false; break; }
            if (!lector.texto(m_name, fin)) return false;
            break;
        }
        case 2: {
            if (tipo != 2) { if (!lector.salta(tipo)) return false; break; }
            std::size_t hasta;
            if (!lector.largo(hasta, fin)) return false;
            if (!m_value.crea()._lee(lector, hasta)) return false;
            break;
        }
        case 3: {
            if (tipo == 2) {   // empaquetado (lo normal en proto3)
                std::size_t hasta;
                if (!lector.largo(hasta, fin)) return false;
                while (lector.pos() < hasta) {
                    std::uint64_t v;
                    if (!lector.varint(v)) return false;
                    m_payload_type_ids.push_back(static_cast<std::uint32_t>(v));
                }
                if (lector.pos() != hasta) return false;
            } else if (tipo == 0) {
                std::uint64_t v;
                if (!lector.varint(v)) return false;
                m_payload_type_ids.push_back(static_cast<std::uint32_t>(v));
            } else if (!lector.salta(tipo)) {
                return false;
            }
            break;
        }
        default:
            if (!lector.salta(tipo)) return false;
        }
    }
    return lector.pos() == fin;
}

inline EnumDecl::EnumDecl() = default;
inline EnumDecl::EnumDecl(const EnumDecl&) = default;
inline EnumDecl& EnumDecl::operator=(const EnumDecl&) = default;
inline EnumDecl::EnumDecl(EnumDecl&&) noexcept = default;
inline EnumDecl& EnumDecl::operator=(EnumDecl&&) noexcept = default;
inline EnumDecl::~EnumDecl() = default;
inline const EnumDecl& EnumDecl::default_instance() { static const EnumDecl vacio; return vacio; }
inline bool EnumDecl::ParseFromString(const std::string& datos) {
    return ParseFromArray(datos.data(), static_cast<int>(datos.size()));
}
inline bool EnumDecl::ParseFromArray(const void* datos, int largo) {
    *this = EnumDecl();
    detalle::Lector lector(static_cast<const unsigned char*>(datos),
                           static_cast<std::size_t>(largo));
    return _lee(lector, static_cast<std::size_t>(largo));
}
inline bool EnumDecl::ParseFromIstream(std::istream* entrada) {
    std::string datos((std::istreambuf_iterator<char>(*entrada)),
                      std::istreambuf_iterator<char>());
    if (entrada->bad()) return false;
    return ParseFromString(datos);
}
inline const std::string& EnumDecl::name() const { return m_name; }
inline void EnumDecl::set_name(std::string valor) { m_name = std::move(valor); }
inline const std::vector<EnumItem>& EnumDecl::items() const { return m_items; }
inline const EnumItem& EnumDecl::items(int i) const { return m_items.at(static_cast<std::size_t>(i)); }
inline int EnumDecl::items_size() const { return static_cast<int>(m_items.size()); }
inline EnumItem* EnumDecl::add_items() { return &m_items.emplace_back(); }
inline bool EnumDecl::_lee(detalle::Lector& lector, std::size_t fin) {
    while (lector.pos() < fin) {
        std::uint64_t etiqueta;
        if (!lector.varint(etiqueta)) return false;
        const int tipo = static_cast<int>(etiqueta & 7);
        switch (etiqueta >> 3) {
        case 1: {
            if (tipo != 2) { if (!lector.salta(tipo)) return false; break; }
            if (!lector.texto(m_name, fin)) return false;
            break;
        }
        case 2: {
            if (tipo != 2) { if (!lector.salta(tipo)) return false; break; }
            std::size_t hasta;
            if (!lector.largo(hasta, fin)) return false;
            if (!m_items.emplace_back()._lee(lector, hasta)) return false;
            break;
        }
        default:
            if (!lector.salta(tipo)) return false;
        }
    }
    return lector.pos() == fin;
}

inline ExternBlock::ExternBlock() = default;
inline ExternBlock::ExternBlock(const ExternBlock&) = default;
inline ExternBlock& ExternBlock::operator=(const ExternBlock&) = default;
inline ExternBlock::ExternBlock(ExternBlock&&) noexcept = default;
inline ExternBlock& ExternBlock::operator=(ExternBlock&&) noexcept = default;
inline ExternBlock::~ExternBlock() = default;
inline const ExternBlock& ExternBlock::default_instance() { static const ExternBlock vacio; return vacio; }
inline bool ExternBlock::ParseFromString(const std::string& datos) {
    return ParseFromArray(datos.data(), static_cast<int>(datos.size()));
}
inline bool ExternBlock::ParseFromArray(const void* datos, int largo) {
    *this = ExternBlock();
    detalle::Lector lector(static_cast<const unsigned char*>(datos),
                           static_cast<std::size_t>(largo));
    return _lee(lector, static_cast<std::size_t>(largo));
}
inline bool ExternBlock::ParseFromIstream(std::istream* entrada) {
    std::string datos((std::istreambuf_iterator<char>(*entrada)),
                      std::istreambuf_iterator<char>());
    if (entrada->bad()) return false;
    return ParseFromString(datos);
}
inline const std::string& ExternBlock::target() const { return m_target; }
inline void ExternBlock::set_target(std::string valor) { m_target = std::move(valor); }
inline const std::string& ExternBlock::raw() const { return m_raw; }
inline void ExternBlock::set_raw(std::string valor) { m_raw = std::move(valor); }
inline const std::vector<std::string>& ExternBlock::requires_() const { return m_requires; }
inline const std::string& ExternBlock::requires_(int i) const { return m_requires.at(static_cast<std::size_t>(i)); }
inline int ExternBlock::requires_size() const { return static_cast<int>(m_requires.size()); }
inline bool ExternBlock::_lee(detalle::Lector& lector, std::size_t fin) {
    while (lector.pos() < fin) {
        std::uint64_t etiqueta;
        if (!lector.varint(etiqueta)) return false;
        const int tipo = static_cast<int>(etiqueta & 7);
        switch (etiqueta >> 3) {
        case 1: {
            if (tipo != 2) { if (!lector.salta(tipo)) return false; break; }
            if (!lector.texto(m_target, fin)) return false;
            break;
        }
        case 2: {
            if (tipo != 2) { if (!lector.salta(tipo)) return false; break; }
            if (!lector.texto(m_raw, fin)) return false;
            break;
        }
        case 3: {
            if (tipo != 2) { if (!lector.salta(tipo)) return false; break; }
            if (!lector.texto(m_requires.emplace_back(), fin)) return false;
            break;
        }
        default:
            if (!lector.salta(tipo)) return false;
        }
    }
    return lector.pos() == fin;
}

inline ImportDirective::ImportDirective() = default;
inline ImportDirective::ImportDirective(const ImportDirective&) = default;
inline ImportDirective& ImportDirective::operator=(const ImportDirective&) = default;
inline ImportDirective::ImportDirective(ImportDirective&&) noexcept = default;
inline ImportDirective& ImportDirective::operator=(ImportDirective&&) noexcept = default;
inline ImportDirective::~ImportDirective() = default;
inline const ImportDirective& ImportDirective::default_instance() { static const ImportDirective vacio; return vacio; }
inline bool ImportDirective::ParseFromString(const std::string& datos) {
    return ParseFromArray(datos.data(), static_cast<int>(datos.size()));
}
inline bool ImportDirective::ParseFromArray(const void* datos, int largo) {
    *this = ImportDirective();
    detalle::Lector lector(static_cast<const unsigned char*>(datos),
                           static_cast<std::size_t>(largo));
    return _lee(lector, static_cast<std::size_t>(largo));
}
inline bool ImportDirective::ParseFromIstream(std::istream* entrada) {
    std::string datos((std::istreambuf_iterator<char>(*entrada)),
                      std::istreambuf_iterator<char>());
    if (entrada->bad()) return false;
    return ParseFromString(datos);
}
inline const std::string& ImportDirective::lib() const { return m_lib; }
inline void ImportDirective::set_lib(std::string valor) { m_lib = std::move(valor); }
inline const std::string& ImportDirective::alias() const { return m_alias; }
inline void ImportDirective::set_alias(std::string valor) { m_alias = std::move(valor); }
inline const std::string& ImportDirective::unit() const { return m_unit; }
inline void ImportDirective::set_unit(std::string valor) { m_unit = std::move(valor); }
inline const std::string& ImportDirective::binding() const { return m_binding; }
inline void ImportDirective::set_binding(std::string valor) { m_binding = std::move(valor); }
inline bool ImportDirective::_lee(detalle::Lector& lector, std::size_t fin) {
    while (lector.pos() < fin) {
        std::uint64_t etiqueta;
        if (!lector.varint(etiqueta)) return false;
        const int tipo = static_cast<int>(etiqueta & 7);
        switch (etiqueta >> 3) {
        case 1: {
            if (tipo != 2) { if (!lector.salta(tipo)) return false; break; }
            if (!lector.texto(m_lib, fin)) return false;
            break;
        }
        case 2: {
            if (tipo != 2) { if (!lector.salta(tipo)) return false; break; }
            if (!lector.texto(m_alias, fin)) return false;
            break;
        }
        case 3: {
            if (tipo != 2) { if (!lector.salta(tipo)) return false; break; }
            if (!lector.texto(m_unit, fin)) return false;
            break;
        }
        case 4: {
            if (tipo != 2) { if (!lector.salta(tipo)) return false; break; }
            if (!lector.texto(m_binding, fin)) return false;
            break;
        }
        default:
            if (!lector.salta(tipo)) return false;
        }
    }
    return lector.pos() == fin;
}

inline ExportDirective::ExportDirective() = default;
inline ExportDirective::ExportDirective(const ExportDirective&) = default;
inline ExportDirective& ExportDirective::operator=(const ExportDirective&) = default;
inline ExportDirective::ExportDirective(ExportDirective&&) noexcept = default;
inline ExportDirective& ExportDirective::operator=(ExportDirective&&) noexcept = default;
inline ExportDirective::~ExportDirective() = default;
inline const ExportDirective& ExportDirective::default_instance() { static const ExportDirective vacio; return vacio; }
inline bool ExportDirective::ParseFromString(const std::string& datos) {
    return ParseFromArray(datos.data(), static_cast<int>(datos.size()));
}
inline bool ExportDirective::ParseFromArray(const void* datos, int largo) {
    *this = ExportDirective();
    detalle::Lector lector(static_cast<const unsigned char*>(datos),
                           static_cast<std::size_t>(largo));
    return _lee(lector, static_cast<std::size_t>(largo));
}
inline bool ExportDirective::ParseFromIstream(std::istream* entrada) {
    std::string datos((std::istreambuf_iterator<char>(*entrada)),
                      std::istreambuf_iterator<char>());
    if (entrada->bad()) return false;
    return ParseFromString(datos);
}
inline const std::string& ExportDirective::alias() const { return m_alias; }
inline void ExportDirective::set_alias(std::string valor) { m_alias = std::move(valor); }
inline bool ExportDirective::package() const { return m_package; }
inline void ExportDirective::set_package(bool valor) { m_package = std::move(valor); }
inline bool ExportDirective::_lee(detalle::Lector& lector, std::size_t fin) {
    while (lector.pos() < fin) {
        std::uint64_t etiqueta;
        if (!lector.varint(etiqueta)) return false;
        const int tipo = static_cast<int>(etiqueta & 7);
        switch (etiqueta >> 3) {
        case 1: {
            if (tipo != 2) { if (!lector.salta(tipo)) return false; break; }
            if (!lector.texto(m_alias, fin)) return false;
            break;
        }
        case 2: {
            if (tipo != 0) { if (!lector.salta(tipo)) return false; break; }
            std::uint64_t v; if (!lector.varint(v)) return false; m_package = v != 0;
            break;
        }
        default:
            if (!lector.salta(tipo)) return false;
        }
    }
    return lector.pos() == fin;
}

inline FromDirective::FromDirective() = default;
inline FromDirective::FromDirective(const FromDirective&) = default;
inline FromDirective& FromDirective::operator=(const FromDirective&) = default;
inline FromDirective::FromDirective(FromDirective&&) noexcept = default;
inline FromDirective& FromDirective::operator=(FromDirective&&) noexcept = default;
inline FromDirective::~FromDirective() = default;
inline const FromDirective& FromDirective::default_instance() { static const FromDirective vacio; return vacio; }
inline bool FromDirective::ParseFromString(const std::string& datos) {
    return ParseFromArray(datos.data(), static_cast<int>(datos.size()));
}
inline bool FromDirective::ParseFromArray(const void* datos, int largo) {
    *this = FromDirective();
    detalle::Lector lector(static_cast<const unsigned char*>(datos),
                           static_cast<std::size_t>(largo));
    return _lee(lector, static_cast<std::size_t>(largo));
}
inline bool FromDirective::ParseFromIstream(std::istream* entrada) {
    std::string datos((std::istreambuf_iterator<char>(*entrada)),
                      std::istreambuf_iterator<char>());
    if (entrada->bad()) return false;
    return ParseFromString(datos);
}
inline const std::string& FromDirective::lib() const { return m_lib; }
inline void FromDirective::set_lib(std::string valor) { m_lib = std::move(valor); }
inline const std::string& FromDirective::name() const { return m_name; }
inline void FromDirective::set_name(std::string valor) { m_name = std::move(valor); }
inline const std::string& FromDirective::alias() const { return m_alias; }
inline void FromDirective::set_alias(std::string valor) { m_alias = std::move(valor); }
inline const std::string& FromDirective::unit() const { return m_unit; }
inline void FromDirective::set_unit(std::string valor) { m_unit = std::move(valor); }
inline bool FromDirective::_lee(detalle::Lector& lector, std::size_t fin) {
    while (lector.pos() < fin) {
        std::uint64_t etiqueta;
        if (!lector.varint(etiqueta)) return false;
        const int tipo = static_cast<int>(etiqueta & 7);
        switch (etiqueta >> 3) {
        case 1: {
            if (tipo != 2) { if (!lector.salta(tipo)) return false; break; }
            if (!lector.texto(m_lib, fin)) return false;
            break;
        }
        case 2: {
            if (tipo != 2) { if (!lector.salta(tipo)) return false; break; }
            if (!lector.texto(m_name, fin)) return false;
            break;
        }
        case 3: {
            if (tipo != 2) { if (!lector.salta(tipo)) return false; break; }
            if (!lector.texto(m_alias, fin)) return false;
            break;
        }
        case 4: {
            if (tipo != 2) { if (!lector.salta(tipo)) return false; break; }
            if (!lector.texto(m_unit, fin)) return false;
            break;
        }
        default:
            if (!lector.salta(tipo)) return false;
        }
    }
    return lector.pos() == fin;
}

}  // namespace suriax::hir::v0

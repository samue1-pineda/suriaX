#include "suriax/hir/view.hpp"
#include "suriax/mir/mir.hpp"

#include <algorithm>
#include <deque>
#include <unordered_set>
#include <map>
#include <set>
#include <unordered_map>
#include <memory>
#include <utility>

namespace suriax::mir {
namespace {

// VM002: desenvolver un 'T?' ('case v' en un 'match', 'x ?? d', una variante
// sobre un sujeto 'E?') y los enums GENERICOS ('enum Res<T, E>'). Los ejecuta
// el interprete; la VM los RECHAZA al bajar a MIR, con su posicion, nunca
// ejecuta otra cosa: leido sin su campo 'binds', 'case v' seria comparar con
// un slot 'v' sin valor (no entraria nunca, en silencio), y el payload 'T' de
// un enum generico se bajaria con el ancho de un entero sin sustituir.
const char kOptionCode[] = "VM002";

std::string option_message(const std::string& source, const std::string& what) {
    return std::string(kOptionCode) + ": '" + source + "' " + what +
           ": la VM todavia no lo ejecuta. Ejecutalo con el interprete: "
           "python V0/main.py <fuente>.srcx --run interpreter";
}

// VM003: una llamada que la Semantica comprobo contra una COTA y no contra un
// tipo ('print(x)' con 'T: Print', 'x.area()' con 'T: Forma'). El HIR la
// marca con un HookRef cuyo dueño es el PARAMETRO de tipo ('T'), igual que
// 'hash(x)': el destino depende de la instancia. El interprete la despacha
// con el tipo del valor; la VM todavia no, y la RECHAZA al bajar a MIR con su
// posicion. Sin esto salia como una llamada 'SIN RESOLVER', sin codigo.
const char kBoundCallCode[] = "VM003";

// VM004: una LAMBDA ('lambda (int x) -> bool: x > k'). La ejecuta el
// interprete, con un cuerpo que ve el marco donde se escribio (sus capturas);
// la VM todavia no tiene ni el valor ni ese marco, y la RECHAZA al bajar a
// MIR con su posicion. Va ANTES que VM001: su tipo es un 'fn(A) -> R', pero
// lo que falta no es solo el valor funcion sino la captura.
const char kLambdaCode[] = "VM004";

std::string lambda_message(const std::string& source) {
    return std::string(kLambdaCode) + ": '" + source + "' usa una lambda: la "
           "VM todavia no las ejecuta (ni el valor funcion ni lo que lee de su "
           "entorno). Ejecutalo con el interprete: python V0/main.py "
           "<fuente>.srcx --run interpreter";
}

// VM005: 'print(x)' con 'x' un PRIMITIVO ('print(5)'). El interprete y el
// target web lo escriben como un f-string escribe '{x}'; la VM no tiene una
// instruccion que escriba sin pasar por '__write__' de 'io', que el programa
// puede no importar, y lo RECHAZA al bajar a MIR con su posicion. Antes
// salia sin codigo ('el unico nativo que baja al MIR es len...').
const char kPrintPrimitiveCode[] = "VM005";

std::string print_primitive_message(const std::string& source, const std::string& type) {
    return std::string(kPrintPrimitiveCode) + ": '" + source + "' escribe un '" +
           type + "' con 'print(x)': la VM todavia no lo ejecuta. Usa un "
           "f-string ('stdp.print(f\"{x}\")') o ejecutalo con el interprete: "
           "python V0/main.py <fuente>.srcx --run interpreter";
}

std::string bound_call_message(const std::string& source, const std::string& owner) {
    return std::string(kBoundCallCode) + ": '" + source + "' llama a algo que "
           "promete una cota de '" + owner + "' (un 'print' de 'Print' o un "
           "metodo de un trait): la VM todavia no despacha por el tipo de la "
           "instancia. Ejecutalo con el interprete: python V0/main.py "
           "<fuente>.srcx --run interpreter";
}

// ¿'name' es un PARAMETRO de tipo de alguna declaracion del modulo ('T' de
// 'fn f<T>', de un '@impl Caja<T>' o de 'struct ... Caja<T>')?
bool declares_type_param(const pb::Module& module, const std::string& name) {
    const auto has = [&](const auto& params) {
        for (const std::string& p : params) {
            if (p == name) return true;
        }
        return false;
    };
    for (const pb::Decl& decl : module.items()) {
        if (decl.node_case() == pb::Decl::kFunction && has(decl.function().type_params())) {
            return true;
        }
        if (decl.node_case() == pb::Decl::kStructDecl &&
            has(decl.struct_decl().type_params())) {
            return true;
        }
        if (decl.node_case() == pb::Decl::kEnumDecl && has(decl.enum_decl().type_params())) {
            return true;
        }
    }
    return false;
}

// TypeKind del esquema -> tipo del MIR. Solo importa el ANCHO: 'bool', 'char'
// y un 'enum' sin payload son enteros en la maquina, y la distincion del
// lenguaje ya la verifico el frontend.
bool tipo_de(const pb::Type& t, Type& out) {
    switch (t.kind()) {
        case pb::VOID: out = Type::Void; return true;
        case pb::BOOL:
        case pb::INT:
        case pb::CHAR:
        case pb::BYTE:
            out = Type::I64;
            return true;
        case pb::FLOAT: out = Type::F64; return true;
        // Un NOMINAL cabe en un registro: un enum sin payload ES un entero y
        // un struct viaja como el HANDLE de su objeto. Una cadena, como el
        // indice de su constante. Un puntero, como el handle al que apunta.
        case pb::NOMINAL:
        case pb::STR:
        case pb::POINTER:
            out = Type::I64;
            return true;
        // 'T?' de algo que ya es un HANDLE (struct, puntero, cadena) cabe en
        // el mismo registro: 'null' es -1, que ningun handle ni indice de
        // constante vale. Un 'int?' o un 'float?' NO: -1 es un entero valido
        // y el MIR necesitaria un bit aparte; se rechaza con su nombre.
        //
        // Un 'int?' (o 'float?', 'bool?', 'char?') no cabe asi: -1 es un
        // entero valido. Se guarda en una CELDA del monton —un objeto de un
        // campo— y el registro lleva su handle, con el mismo -1 para null.
        case pb::NULLABLE:
            if (!t.has_inner()) break;
            switch (t.inner().kind()) {
                case pb::NOMINAL:
                case pb::STR:
                case pb::POINTER:
                case pb::INT:
                case pb::FLOAT:
                case pb::BOOL:
                case pb::CHAR:
                case pb::BYTE:
                    out = Type::I64;
                    return true;
                default:
                    break;
            }
            break;
        // 'error T' es "T, o lanza": el error viaja por el unwinding, no por
        // el valor, asi que en la maquina es el tipo de adentro. 'error' solo
        // no devuelve nada.
        case pb::ERROR:
            if (!t.has_inner()) {
                out = Type::Void;
                return true;
            }
            return tipo_de(t.inner(), out);
        default:
            break;
    }
    out = Type::I64;
    return false;
}

bool tipo_de(const pb::Module& module, std::uint32_t type_id, Type& out) {
    if (type_id >= static_cast<std::uint32_t>(module.types_size())) {
        out = Type::I64;
        return false;
    }
    return tipo_de(module.types(static_cast<int>(type_id)), out);
}

// Un escalar del lenguaje: vive en un registro, no en el monton.
bool es_escalar(const pb::Type& t) {
    return t.kind() == pb::INT || t.kind() == pb::FLOAT ||
           t.kind() == pb::BOOL || t.kind() == pb::CHAR || t.kind() == pb::BYTE;
}

// 'T?' de un escalar: su valor es una CELDA (o -1, null).
bool es_caja(const pb::Type& t) {
    return t.kind() == pb::NULLABLE && t.has_inner() && es_escalar(t.inner());
}

// El primer code point de un texto UTF-8 (0 si esta vacio).
std::uint32_t primer_punto(const std::string& texto) {
    if (texto.empty()) return 0;
    const unsigned char c = static_cast<unsigned char>(texto[0]);
    std::size_t largo = 1;
    std::uint32_t punto = c;
    if ((c & 0xE0u) == 0xC0u) { largo = 2; punto = c & 0x1Fu; }
    else if ((c & 0xF0u) == 0xE0u) { largo = 3; punto = c & 0x0Fu; }
    else if ((c & 0xF8u) == 0xF0u) { largo = 4; punto = c & 0x07u; }
    for (std::size_t j = 1; j < largo && j < texto.size(); ++j) {
        punto = (punto << 6) | (static_cast<unsigned char>(texto[j]) & 0x3Fu);
    }
    return punto;
}

// Una SUSTITUCION de parametros de tipo: 'T' -> 'Punto'. Vacia fuera de un
// generico. Es lo que hace concreta una instancia (ver 'Instancias').
using Sustitucion = std::map<std::string, pb::Type>;

// 'T' -> su tipo concreto, en profundidad ('T ptr mutable' -> 'Punto ptr
// mutable', 'Vector<T>' -> 'Vector<Punto>'). Los nombres del HIR ya son
// CANONICOS —los de una libreria llevan su unidad ('punto.Punto') y los del
// programa van sueltos— asi que un tipo sustituido se puede usar en
// cualquier unidad sin reescribirlo.
pb::Type sustituir(const pb::Type& t, const Sustitucion& s) {
    if (t.kind() == pb::NOMINAL && t.args_size() == 0) {
        const auto it = s.find(t.name());
        if (it != s.end()) return it->second;
    }
    pb::Type r;
    r.set_kind(t.kind());
    r.set_name(t.name());
    r.set_mut(t.mut());
    if (t.has_inner()) *r.mutable_inner() = sustituir(t.inner(), s);
    for (const pb::Type& a : t.args()) *r.add_args() = sustituir(a, s);
    return r;
}

// ¿El alias de una unidad ('array.vector') nombra la unidad 'prefijo'
// ('vector')? Se compara el ultimo tramo: la identidad de un tipo la pone el
// '#export' de su archivo, sin el paquete que lo contiene.
bool alias_es(const std::string& alias, const std::string& prefijo) {
    if (alias == prefijo) return true;
    return alias.size() > prefijo.size() &&
           alias.compare(alias.size() - prefijo.size(), prefijo.size(), prefijo) == 0 &&
           alias[alias.size() - prefijo.size() - 1] == '.';
}

// El catalogo de FORMAS de la imagen: para cada tipo CONCRETO, que campos de
// sus objetos son objetos propios (ver 'Layout'). Uno solo para todo el
// programa: la forma de 'Vector<Punto>' es la misma desde cualquier funcion.
class Formas {
public:
    Formas(const hir::Image& image, Program& program)
        : image_(image), program_(program) {}

    // La declaracion de un tipo nominal por su nombre canonico. Suelto = del
    // programa principal; 'unidad.Nombre' = de esa libreria.
    struct Declaracion {
        const pb::Module* modulo = nullptr;
        const pb::StructDecl* estructura = nullptr;
        const pb::EnumDecl* enumeracion = nullptr;
    };

    Declaracion declaracion(const std::string& nombre) const {
        const std::size_t punto = nombre.rfind('.');
        const std::string suelto =
            punto == std::string::npos ? nombre : nombre.substr(punto + 1);
        const auto mirar = [&](const pb::Module& m) -> Declaracion {
            Declaracion d;
            for (const pb::Decl& decl : m.items()) {
                if (decl.node_case() == pb::Decl::kStructDecl &&
                    decl.struct_decl().name() == suelto) {
                    d.modulo = &m;
                    d.estructura = &decl.struct_decl();
                    return d;
                }
                if (decl.node_case() == pb::Decl::kEnumDecl &&
                    decl.enum_decl().name() == suelto) {
                    d.modulo = &m;
                    d.enumeracion = &decl.enum_decl();
                    return d;
                }
            }
            return d;
        };
        if (punto == std::string::npos) return mirar(image_.main().module());
        const std::string prefijo = nombre.substr(0, punto);
        for (const std::unique_ptr<hir::Unit>& u : image_.units()) {
            if (!alias_es(u->alias(), prefijo)) continue;
            Declaracion d = mirar(u->module());
            if (d.modulo != nullptr) return d;
        }
        return {};
    }

    // Un campo ESCALAR al que alguien le toma la direccion ('&p.x') guarda
    // una CELDA en todas las instancias de su struct: leerlo y escribirlo
    // pasa por ella, y es un objeto propio del struct (se copia y se libera
    // con el). Se decide para todo el programa antes de bajar nada.
    void marcar_celda(const pb::StructDecl* st, int campo) {
        celdas_.emplace(st, campo);
    }
    bool campo_en_celda(const pb::StructDecl* st, int campo) const {
        return celdas_.count({st, campo}) != 0;
    }

    static bool es_suma(const pb::EnumDecl& en) {
        for (const pb::EnumItem& it : en.items()) {
            if (it.payload_type_ids_size() > 0) return true;
        }
        return false;
    }

    // ¿Un valor de este tipo es un OBJETO PROPIO (un handle del que alguien
    // es dueno)? Un struct por valor o un enum suma, tambien envueltos en '?'
    // o en 'error'. Un puntero es un prestamo, una cadena se recoge aparte y
    // un parametro de tipo sin sustituir no se sabe (no se trata como propio:
    // no copiarlo ni liberarlo es lo que ya hacia la VM).
    bool propio(const pb::Type& t) const {
        switch (t.kind()) {
            case pb::NOMINAL: {
                const Declaracion d = declaracion(t.name());
                if (d.estructura != nullptr) return true;
                return d.enumeracion != nullptr && es_suma(*d.enumeracion);
            }
            // la celda de un 'int?' es suya: se copia y se libera con el
            case pb::NULLABLE:
                return t.has_inner() && (es_escalar(t.inner()) || propio(t.inner()));
            case pb::ERROR:
                return t.has_inner() && propio(t.inner());
            default:
                return false;
        }
    }

    // La forma de los objetos de un tipo concreto, o -1 si no es un objeto
    // propio o ninguno de sus campos lo es.
    std::int32_t forma(const pb::Type& t) {
        // la CELDA de un 'int?': un objeto de un campo sin nada propio. Tiene
        // forma para que un bloque de ellas ('Vector<int?>') sepa que sus
        // celdas son objetos, y para que '--memoria' diga de que son.
        if (es_caja(t)) {
            const std::string clave = hir::type_key(t);
            const auto hecha = memo_.find(clave);
            if (hecha != memo_.end()) return hecha->second;
            const auto id = static_cast<std::int32_t>(program_.layouts.size());
            memo_.emplace(clave, id);
            program_.layouts.push_back(Layout{hir::format_type(t), false, {}, {}, {}, {}, {}});
            tipos_.push_back(t);
            return id;
        }
        if (t.kind() == pb::NULLABLE || t.kind() == pb::ERROR) {
            return t.has_inner() ? forma(t.inner()) : -1;
        }
        if (t.kind() != pb::NOMINAL) return -1;
        const std::string clave = hir::type_key(t);
        const auto hecha = memo_.find(clave);
        if (hecha != memo_.end()) return hecha->second;
        const Declaracion d = declaracion(t.name());
        if (d.estructura == nullptr &&
            (d.enumeracion == nullptr || !es_suma(*d.enumeracion))) {
            return -1;
        }
        // se reserva el indice ANTES de mirar los campos: un tipo puede
        // nombrarse a si mismo a traves de un nullable
        const auto id = static_cast<std::int32_t>(program_.layouts.size());
        memo_.emplace(clave, id);
        program_.layouts.push_back(Layout{hir::format_type(t), d.enumeracion != nullptr, {}, {}, {}, {}, {}});
        tipos_.push_back(t);
        std::vector<std::vector<std::uint32_t>> propios;
        std::vector<std::vector<std::uint32_t>> bloques;
        if (d.estructura != nullptr) {
            Sustitucion s;
            const pb::StructDecl& st = *d.estructura;
            for (int i = 0; i < st.type_params_size() && i < t.args_size(); ++i) {
                s.emplace(st.type_params(i), t.args(i));
            }
            propios.emplace_back();
            bloques.emplace_back();
            {
                // los nombres y modos de 'ToStr' de sus campos, para escribirlo
                std::vector<std::string> nombres;
                std::vector<std::int32_t> modos;
                for (int i = 0; i < st.fields_size(); ++i) {
                    nombres.push_back(st.fields(i).name());
                    const pb::Type* campo = tipo_en(*d.modulo, st.fields(i).type_id());
                    std::int32_t m = campo == nullptr ? -1 : modo_texto(sustituir(*campo, s));
                    if (m >= 0 && campo_en_celda(d.estructura, i)) {
                        m = static_cast<std::int32_t>(m | kTextoNulable);
                    }
                    modos.push_back(m);
                }
                Layout& forma_struct = program_.layouts[static_cast<std::size_t>(id)];
                forma_struct.campos = std::move(nombres);
                forma_struct.textos.clear();
                forma_struct.textos.push_back(std::move(modos));
            }
            for (int i = 0; i < st.fields_size(); ++i) {
                const pb::Type* campo = tipo_en(*d.modulo, st.fields(i).type_id());
                if (campo == nullptr) continue;
                if (propio(sustituir(*campo, s)) || campo_en_celda(d.estructura, i)) {
                    propios[0].push_back(static_cast<std::uint32_t>(i));
                } else if (campo->kind() == pb::POINTER) {
                    bloques[0].push_back(static_cast<std::uint32_t>(i));
                }
            }
        } else {
            Layout& forma_enum = program_.layouts[static_cast<std::size_t>(id)];
            for (const pb::EnumItem& it : d.enumeracion->items()) {
                propios.emplace_back();
                bloques.emplace_back();
                forma_enum.variantes.push_back(it.name());
                forma_enum.textos.emplace_back();
                for (int k = 0; k < it.payload_type_ids_size(); ++k) {
                    const pb::Type* p = tipo_en(*d.modulo, it.payload_type_ids(k));
                    // se lee otra vez: 'forma()' de un payload puede crecer
                    // el vector de formas
                    program_.layouts[static_cast<std::size_t>(id)].textos.back().push_back(
                        p == nullptr ? -1 : modo_texto(*p));
                    if (p == nullptr) continue;
                    if (propio(*p)) {
                        propios.back().push_back(static_cast<std::uint32_t>(k + 1));
                    } else if (p->kind() == pb::POINTER) {
                        bloques.back().push_back(static_cast<std::uint32_t>(k + 1));
                    }
                }
            }
        }
        bool alguno = false;
        for (const auto& lista : propios) alguno = alguno || !lista.empty();
        program_.layouts[static_cast<std::size_t>(id)].propios = std::move(propios);
        program_.layouts[static_cast<std::size_t>(id)].bloques = std::move(bloques);
        (void)alguno;   // una forma sin propios sigue sirviendo para leer el MIR
        return id;
    }

    static const pb::Type* tipo_en(const pb::Module& m, std::uint32_t id) {
        if (id >= static_cast<std::uint32_t>(m.types_size())) return nullptr;
        return &m.types(static_cast<int>(id));
    }

    // El modo de 'ToStr' de un tipo (ver 'Op::ToStr'), o -1 si no se sabe
    // escribir. Un enum SIN payload es un entero con nombre y se escribe como
    // su numero (lo que hace el interprete); uno con payload, 'Nodo(3, x)'.
    // 'error T' se escribe como T: si hubo error, el valor nunca llego.
    //
    // Un enum se escribe por el NOMBRE de su variante ('Verde', 'OK',
    // 'Circulo(2.5)'), como en el interprete.
    int modo_texto(const pb::Type& t) {
        switch (t.kind()) {
            case pb::INT: case pb::BYTE: return 0;
            case pb::FLOAT: return 1;
            case pb::BOOL: return 2;
            case pb::CHAR: return 3;
            case pb::STR: return 4;
            case pb::NOMINAL: {
                const Declaracion d = declaracion(t.name());
                // un struct se escribe con sus campos (su forma los nombra)
                if (d.estructura != nullptr) return 7;
                if (d.enumeracion == nullptr) return -1;
                if (es_suma(*d.enumeracion)) return 5;
                return static_cast<int>(modo_de_texto(6, false, nombres(t.name(), *d.enumeracion)));
            }
            case pb::NULLABLE: {
                if (!t.has_inner()) return -1;
                const int dentro = modo_texto(t.inner());
                // null es -1: un escalar viaja en su celda, una cadena o un
                // enum suma ya son un indice o un handle, y un enum sin
                // payload es un entero que (salvo que declare -1) no lo vale
                return dentro < 0 ? -1 : dentro | static_cast<int>(kTextoNulable);
            }
            case pb::ERROR: return t.has_inner() ? modo_texto(t.inner()) : -1;
            default: return -1;
        }
    }

    // La tabla de nombres de un enum sin payload (ver 'NombresEnum'), una
    // por enum. Los valores se numeran como en el interprete: seguidos, y un
    // valor escrito ('OK = 200') reinicia la cuenta.
    std::int64_t nombres(const std::string& canonico, const pb::EnumDecl& en) {
        const auto hecha = nombres_.find(canonico);
        if (hecha != nombres_.end()) return hecha->second;
        NombresEnum tabla;
        tabla.nombre = canonico;
        std::int64_t siguiente = 0;
        for (const pb::EnumItem& it : en.items()) {
            std::int64_t actual = siguiente;
            if (it.has_value() && it.value().node_case() == pb::Expr::kLiteral &&
                it.value().literal().kind() == "int") {
                actual = it.value().literal().int_value();
            }
            tabla.items.emplace_back(actual, it.name());
            siguiente = actual + 1;
        }
        const auto id = static_cast<std::int64_t>(program_.enums.size());
        program_.enums.push_back(std::move(tabla));
        nombres_.emplace(canonico, id);
        return id;
    }

    // El tipo concreto de la forma 'id' (una copia: el vector crece).
    bool tipo_de_forma(std::size_t id, pb::Type& out) const {
        if (id >= tipos_.size()) return false;
        out = tipos_[id];
        return true;
    }

private:
    const hir::Image& image_;
    Program& program_;
    //: paralelo a 'Program::layouts': el tipo de cada forma
    std::vector<pb::Type> tipos_;
    std::unordered_map<std::string, std::int32_t> memo_;
    std::unordered_map<std::string, std::int64_t> nombres_;
    std::set<std::pair<const pb::StructDecl*, int>> celdas_;
};

// La unidad (y su modulo) de una funcion resuelta.
const pb::Module* modulo_de_unidad(const hir::Image& image, const std::string& alias) {
    if (alias.empty()) return &image.main().module();
    for (const std::unique_ptr<hir::Unit>& u : image.units()) {
        if (u->alias() == alias) return &u->module();
    }
    return nullptr;
}

// MONOMORFIZACION: cada funcion generica se baja una vez por cada juego de
// tipos concretos con que se la llama ('Vector<Punto>.push' y
// 'Vector<int>.push' son dos funciones del MIR), como en C++ y en Rust.
//
// Es lo que deja saber, al compilar, si un 'T' es un objeto propio —que hay
// que copiar al guardarlo y liberar al soltarlo— o un escalar. Sin esto la
// VM bajaba una sola version para todo 'T' y no podia liberar nada de lo que
// un 'Vector<Punto>' guardaba.
//
// Los tipos concretos no viajan en la llamada: se DEDUCEN unificando la
// firma de la funcion con los tipos que el HIR anota en los argumentos y en
// el resultado ('vec.dynamic<C>(4)' devuelve 'Vector<C>', luego T = C).
class Instancias {
public:
    Instancias(const hir::Image& image, const hir::Program& resolved,
               Program& program, Formas& formas)
        : image_(image), resolved_(resolved), program_(program), formas_(formas) {}

    struct Pendiente {
        std::size_t base = 0;
        std::size_t indice = 0;
        Sustitucion sustitucion;
    };

    // Los parametros de tipo de una funcion: los declarados ('fn f<T>', los
    // del '@impl Vector<T>') y los que su firma usa sin declarar (un hook
    // como '__index__(Vector<T> ptr self, ...)' toma 'T' del receptor).
    const std::vector<std::string>& parametros(std::size_t base) {
        const auto hecho = parametros_.find(base);
        if (hecho != parametros_.end()) return hecho->second;
        std::vector<std::string> ps;
        const hir::Function& f = resolved_.functions[base];
        const pb::Module* m = modulo_de_unidad(image_, f.unit);
        if (f.decl != nullptr && m != nullptr) {
            for (const std::string& p : f.decl->type_params()) agregar(ps, p);
            const auto recorrer = [&](const pb::Type& t, auto&& yo) -> void {
                if (t.kind() == pb::NOMINAL && t.args_size() == 0 &&
                    t.name().find('.') == std::string::npos &&
                    formas_.declaracion(t.name()).modulo == nullptr) {
                    agregar(ps, t.name());
                }
                if (t.has_inner()) yo(t.inner(), yo);
                for (const pb::Type& a : t.args()) yo(a, yo);
            };
            for (const pb::Parameter& p : f.decl->params()) {
                if (const pb::Type* t = Formas::tipo_en(*m, p.type_id())) recorrer(*t, recorrer);
            }
            if (const pb::Type* t = Formas::tipo_en(*m, f.decl->return_type_id())) {
                recorrer(*t, recorrer);
            }
        }
        return parametros_.emplace(base, std::move(ps)).first->second;
    }

    // El indice de la funcion a llamar: la instancia de 'base' para estos
    // tipos concretos, o 'base' si no es generica o si algun parametro no se
    // pudo deducir (entonces se baja como antes: sin copiar ni liberar 'T').
    int para(int base, const std::vector<const pb::Type*>& args,
             const pb::Type* resultado) {
        if (base < 0 || static_cast<std::size_t>(base) >= resolved_.functions.size()) {
            return base;
        }
        const auto b = static_cast<std::size_t>(base);
        const std::vector<std::string>& ps = parametros(b);
        if (ps.empty()) return base;
        const hir::Function& f = resolved_.functions[b];
        const pb::Module* m = modulo_de_unidad(image_, f.unit);
        if (f.decl == nullptr || m == nullptr || f.prototype) return base;
        Sustitucion s;
        for (std::size_t i = 0; i < args.size() &&
                                static_cast<int>(i) < f.decl->params_size(); ++i) {
            const pb::Type* patron =
                Formas::tipo_en(*m, f.decl->params(static_cast<int>(i)).type_id());
            if (patron != nullptr && args[i] != nullptr) unificar(*patron, *args[i], ps, s);
        }
        if (resultado != nullptr) {
            if (const pb::Type* patron = Formas::tipo_en(*m, f.decl->return_type_id())) {
                unificar(*patron, *resultado, ps, s);
            }
        }
        for (const std::string& p : ps) {
            // no se pudo deducir, o lo deducido es a su vez un parametro sin
            // resolver (se esta bajando la BASE de otro generico): se llama a
            // la base
            const auto it = s.find(p);
            if (it == s.end() || tiene_parametro(it->second)) return base;
        }
        std::string clave = std::to_string(b);
        std::string nombre = f.name + "<";
        for (std::size_t i = 0; i < ps.size(); ++i) {
            clave += "|" + ps[i] + "=" + hir::type_key(s.at(ps[i]));
            nombre += (i ? ", " : "") + hir::format_type(s.at(ps[i]));
        }
        nombre += ">";
        const auto hecha = por_clave_.find(clave);
        if (hecha != por_clave_.end()) return static_cast<int>(hecha->second);
        if (por_clave_.size() >= kMaxInstancias) return base;
        const std::size_t indice = program_.functions.size() + nuevas_.size();
        Function fn;
        fn.unit = f.unit;
        fn.name = nombre;
        nuevas_.push_back(std::move(fn));
        por_clave_.emplace(clave, indice);
        base_de_.emplace(indice, b);
        sustitucion_de_.emplace(indice, s);
        pendientes_.push_back(Pendiente{b, indice, std::move(s)});
        return static_cast<int>(indice);
    }

    // Los tipos concretos de una instancia (nullptr si no es una).
    const Sustitucion* sustitucion_de(std::size_t indice) const {
        const auto it = sustitucion_de_.find(indice);
        return it == sustitucion_de_.end() ? nullptr : &it->second;
    }

    // La funcion base (la del HIR) de un indice del programa.
    std::size_t base_de(std::size_t indice) const {
        const auto it = base_de_.find(indice);
        return it == base_de_.end() ? indice : it->second;
    }

    // Las instancias pedidas pasan al programa. Se hace ENTRE funciones y
    // nunca a mitad de una: el lowering tiene una referencia a la funcion
    // que baja, y hacer crecer el vector la dejaria colgando.
    void volcar() {
        for (Function& fn : nuevas_) program_.functions.push_back(std::move(fn));
        nuevas_.clear();
    }

    bool hay_pendientes() const { return !pendientes_.empty(); }
    Pendiente siguiente() {
        Pendiente p = std::move(pendientes_.front());
        pendientes_.pop_front();
        return p;
    }

private:
    // ¿Queda en 't' un nombre suelto que ninguna unidad declara (un 'T')?
    bool tiene_parametro(const pb::Type& t) const {
        if (t.kind() == pb::NOMINAL && t.name().find('.') == std::string::npos &&
            formas_.declaracion(t.name()).modulo == nullptr) {
            return true;
        }
        if (t.has_inner() && tiene_parametro(t.inner())) return true;
        for (const pb::Type& a : t.args()) {
            if (tiene_parametro(a)) return true;
        }
        return false;
    }

    static void agregar(std::vector<std::string>& ps, const std::string& p) {
        if (std::find(ps.begin(), ps.end(), p) == ps.end()) ps.push_back(p);
    }

    // Casa 'patron' (con parametros) contra un tipo concreto y anota lo que
    // deduce. Tolera el prestamo implicito del receptor ('Vector<T> ptr'
    // contra 'Vector<C>') y el nullable ('T?' contra 'C').
    static void unificar(const pb::Type& patron, const pb::Type& concreto,
                         const std::vector<std::string>& ps, Sustitucion& s) {
        if (patron.kind() == pb::NOMINAL && patron.args_size() == 0 &&
            std::find(ps.begin(), ps.end(), patron.name()) != ps.end()) {
            s.emplace(patron.name(), concreto);
            return;
        }
        if (patron.kind() != concreto.kind()) {
            if ((patron.kind() == pb::POINTER || patron.kind() == pb::NULLABLE ||
                 patron.kind() == pb::ERROR) && patron.has_inner()) {
                unificar(patron.inner(), concreto, ps, s);
            }
            return;
        }
        if (patron.has_inner() && concreto.has_inner()) {
            unificar(patron.inner(), concreto.inner(), ps, s);
        }
        for (int i = 0; i < patron.args_size() && i < concreto.args_size(); ++i) {
            unificar(patron.args(i), concreto.args(i), ps, s);
        }
    }

    // Tope de instancias: una recursion polimorfica ('f<T>' que llama a
    // 'f<Caja<T>>') no termina nunca; al llegar aqui se baja la base.
    static constexpr std::size_t kMaxInstancias = 4096;

    const hir::Image& image_;
    const hir::Program& resolved_;
    Program& program_;
    Formas& formas_;
    std::unordered_map<std::size_t, std::vector<std::string>> parametros_;
    std::unordered_map<std::string, std::size_t> por_clave_;
    std::unordered_map<std::size_t, std::size_t> base_de_;
    std::unordered_map<std::size_t, Sustitucion> sustitucion_de_;
    std::vector<Function> nuevas_;
    std::deque<Pendiente> pendientes_;
};

// El '__free__' que declara el tipo 'dueno' (la funcion BASE, sin instanciar),
// o -1. El hook da el nombre; el dueño —el tipo de su primer parametro, en el
// pool de SU unidad— desempata entre dos tipos que declaran el suyo.
int destructor_de(const hir::Image& image, const hir::Program& resolved,
                  const std::string& dueno) {
    pb::HookRef ref;
    ref.set_owner_type(dueno);
    ref.set_kind(pb::FREE);
    const pb::Symbol* simbolo = image.hook(ref);
    if (simbolo == nullptr) return -1;
    for (std::size_t i = 0; i < resolved.functions.size(); ++i) {
        const hir::Function& f = resolved.functions[i];
        if (f.name != simbolo->name() || f.decl == nullptr || f.decl->params_size() == 0) {
            continue;
        }
        const pb::Module* m = modulo_de_unidad(image, f.unit);
        if (m == nullptr) continue;
        const pb::Type* t = Formas::tipo_en(*m, f.decl->params(0).type_id());
        while (t != nullptr && (t->kind() == pb::POINTER || t->kind() == pb::NULLABLE) &&
               t->has_inner()) {
            t = &t->inner();
        }
        if (t != nullptr && t->name() == dueno) return static_cast<int>(i);
    }
    return -1;
}

// Como cruza a C++ un tipo de la frontera, o el porque de que no cruce
// (las palabras de '_SIN_ABI' de 'runtime/extern_cpp.py').
bool abi_de(const pb::Type& t, Abi& out, std::string& porque) {
    switch (t.kind()) {
        case pb::VOID: out = Abi::Nada; return true;
        case pb::INT: out = Abi::Entero; return true;
        case pb::FLOAT: out = Abi::Flotante; return true;
        case pb::BOOL: out = Abi::Logico; return true;
        case pb::CHAR: out = Abi::Caracter; return true;
        case pb::BYTE: out = Abi::Byte; return true;
        case pb::STR: out = Abi::Cadena; return true;
        case pb::POINTER: {
            const auto dentro = t.has_inner() ? t.inner().kind() : pb::VOID;
            if (dentro == pb::BYTE) {
                out = Abi::BloqueDeBytes;
                return true;
            }
            out = dentro == pb::INT || dentro == pb::FLOAT || dentro == pb::BOOL
                ? Abi::Bloque : Abi::BloqueSinMaquina;
            return true;
        }
        case pb::NULLABLE:
            porque = "un nullable: cómo viaja el nulo a C++ todavía no está fijado";
            return false;
        case pb::NOMINAL:
            porque = "un tipo nominal: su layout en C++ lo decidirá el backend nativo";
            return false;
        case pb::ERROR:
            porque = "un 'error T': el acarreo del error a C++ no está fijado";
            return false;
        default:
            porque = "un 'type' de primera clase";
            return false;
    }
}


Firma firma_de_prototipo(const hir::Image& image, const hir::Function& f) {
    Firma firma;
    const pb::Module* modulo = modulo_de_unidad(image, f.unit);
    if (f.decl == nullptr || modulo == nullptr) {
        firma.sin_abi = "no se conoce su firma";
        return firma;
    }
    const pb::Module& m = *modulo;
    for (const pb::Parameter& p : f.decl->params()) {
        const pb::Type* t = Formas::tipo_en(m, p.type_id());
        Abi abi = Abi::Nada;
        std::string porque = "tipo desconocido";
        if (t == nullptr || !abi_de(*t, abi, porque) || abi == Abi::Nada) {
            firma.sin_abi = "el parametro '" + p.name() + "' es " + porque;
            return firma;
        }
        firma.params.push_back(abi);
    }
    const pb::Type* r = Formas::tipo_en(m, f.decl->return_type_id());
    std::string porque = "tipo desconocido";
    if (r == nullptr || !abi_de(*r, firma.retorno, porque)) {
        firma.sin_abi = "el retorno es " + porque;
    } else if (firma.retorno == Abi::Cadena) {
        firma.sin_abi = "devuelve 'str': quien libera ese buffer es una pregunta de "
                        "propiedad todavia sin decidir";
    } else if (firma.retorno == Abi::Bloque || firma.retorno == Abi::BloqueSinMaquina ||
               firma.retorno == Abi::BloqueDeBytes) {
        firma.sin_abi = "devuelve un puntero de C++: de quien es esa memoria todavia "
                        "no esta decidido";
    }
    return firma;
}

// Una region con 'finally' (el cuerpo de un 'try' o uno de sus 'catch'): una
// salida anticipada que la atraviesa corre su 'finally'.
struct Finalizador {
    const pb::Block* bloque = nullptr;
    std::size_t ambitos = 0;   // el ambito del try/catch es este indice
    int fuera = -1;            // el manejador de AFUERA del 'try'
    // donde se cita un RT022: la primera sentencia del 'finally' (un bloque
    // no tiene posicion propia) o, si esta vacio, el 'try'
    std::uint32_t line = 0;
    std::uint32_t col = 0;
};

// Baja el cuerpo de UNA funcion. Vive en una clase porque el lowering lleva
// estado —el bloque en curso, el siguiente registro, los bucles abiertos— y
// pasarlo por parametro a cada metodo seria escribirlo quince veces.
class Lowering {
public:
    Lowering(const pb::Module& module, const hir::Program& resolved,
             Function& fn, Program& program, const hir::Image& image,
             std::string unidad, Formas& formas, Instancias& instancias,
             const Sustitucion* sustitucion = nullptr)
        : module_(module), resolved_(resolved), fn_(fn), program_(program),
          image_(image), fallos_(program.unsupported),
          formas_(formas), instancias_(instancias), sustitucion_(sustitucion),
          unidad_(std::move(unidad)) {
        if (const hir::Unit* u = unidad_de(unidad_)) {
            enlaces_ = hir::bindings_of(*u);
        }
    }

    // Devuelve false si algo no se pudo bajar: la funcion queda sin bloques
    // en vez de a medias, que es lo unico honesto — un cuerpo incompleto se
    // ejecutaria y daria otro programa.
    bool run(const pb::FunctionDecl& decl,
             const std::vector<hir::Slot>& slots,
             std::uint32_t ln, std::uint32_t col,
             const std::vector<std::string>& direcciones = {}) {
        // VM001 antes que nada: un slot o un retorno de tipo funcion no es un
        // tipo que falte representar, es una construccion que la VM no
        // ejecuta todavia, y el mensaje lo tiene que decir asi.
        //
        // En el PROGRAMA se rechaza al bajar (y 'suri --run compiler' lo
        // ejecuta en el interprete). En una LIBRERIA no: 'array.vector'
        // declara 'sort_by(fn(T ptr, T ptr) -> int cmp)' y todo programa que
        // usa un Vector la importa. La funcion se baja a un cuerpo que FALLA
        // con VM001 si alguien la llama —y quien la llame desde el programa
        // ya se rechazo al bajar, porque le pasa un valor funcion—.
        const pb::Type* function_type = nullptr;
        for (const hir::Slot& slot : slots) {
            function_type = function_type_of(slot.type_id);
            if (function_type != nullptr) break;
        }
        if (function_type == nullptr) function_type = function_type_of(decl.return_type_id());
        if (function_type != nullptr) {
            if (unidad_.empty()) {
                fallo(hir::function_values_message(module_.source_file(), *function_type),
                      ln, col);
                return false;
            }
            trap_function_value(decl, slots, *function_type, ln, col);
            return true;
        }
        for (const hir::Slot& slot : slots) {
            Type tipo;
            if (!tipo_de(module_, slot.type_id, tipo)) {
                fallo("el slot '" + slot.name + "' es de tipo " +
                          notacion(slot.type_id) + " y el MIR no lo "
                          "representa todavia" + porque(slot.type_id),
                      ln, col);
                return false;
            }
            fn_.slots.push_back(tipo);
            fn_.slot_names.push_back(slot.name);
            const auto indice = static_cast<std::uint32_t>(fn_.slots.size() - 1);
            tipo_slot_[indice] = slot.type_id;
            if (slot.parameter) {
                fn_.params++;
                nombres_[slot.name] = indice;
                tipos_[slot.name] = slot.type_id;
            } else {
                // Una local es visible desde SU declaracion, y cada
                // declaracion tiene su slot: dos 'var' homonimas en ambitos
                // distintos (un 'str nombre' en un 'if' y un 'Token nombre'
                // despues) compartian el primero, con su tipo. 'resolve'
                // entrega los slots en el orden en que 'var_decl' los va a
                // encontrar.
                pendientes_[slot.name].push_back(Pendiente{indice, slot.type_id});
            }
        }
        // Un escalar al que se le toma la direccion vive en una CELDA: el
        // slot guarda su handle, leerlo es leer la celda y '&n' es el handle.
        // Es la celda la que se libera al cerrar su ambito, como un objeto
        // propio (por eso entra en 'slot_propio_' y tiene bandera).
        for (std::size_t i = 0; i < fn_.slots.size(); ++i) {
            const auto indice = static_cast<std::uint32_t>(i);
            if (std::find(direcciones.begin(), direcciones.end(), fn_.slot_names[i]) ==
                direcciones.end()) {
                continue;
            }
            const auto tipo = tipo_slot_.find(indice);
            if (tipo == tipo_slot_.end() ||
                tipo->second >= static_cast<std::uint32_t>(module_.types_size())) {
                continue;
            }
            const pb::Type t = concreto(module_.types(static_cast<int>(tipo->second)));
            // un enum SIN payload es un entero: con su direccion tomada vive
            // en una celda, como un 'int' (antes '&e' daba el valor y 'p[0]'
            // fallaba solo en la VM)
            if (es_escalar(t) || t.kind() == pb::STR ||
                (t.kind() == pb::NOMINAL && es_enum_simple(t.name()))) {
                celdas_.insert(indice);
            }
        }

        // Una BANDERA por local destruible. Se crean aqui, con el resto de
        // los slots, porque un slot que naciera a mitad del lowering
        // invalidaria los indices ya emitidos.
        std::vector<std::string> destruibles;
        recoger_destruibles(decl.body(), destruibles);
        recoger_drops(decl.body());
        const std::size_t declarados = fn_.slots.size();
        for (std::size_t i = 0; i < declarados; ++i) {
            const std::string nombre = fn_.slot_names[i];
            if (std::find(destruibles.begin(), destruibles.end(), nombre) ==
                destruibles.end()) {
                continue;
            }
            fn_.slots.push_back(Type::I64);
            fn_.slot_names.push_back("<vivo:" + nombre + ">");
            banderas_.emplace(static_cast<std::uint32_t>(i),
                              static_cast<std::uint32_t>(fn_.slots.size() - 1));
        }

        // ...y una por slot cuyo valor es un OBJETO PROPIO (aunque no tenga
        // destructor): su memoria se libera al morir su dueño
        for (std::size_t i = 0; i < declarados; ++i) {
            const auto indice = static_cast<std::uint32_t>(i);
            const auto tipo = tipo_slot_.find(indice);
            if (tipo == tipo_slot_.end() ||
                tipo->second >= static_cast<std::uint32_t>(module_.types_size())) {
                continue;
            }
            if (celdas_.count(indice) == 0 &&
                !formas_.propio(concreto(module_.types(static_cast<int>(tipo->second))))) {
                continue;
            }
            slot_propio_.insert(indice);
            if (banderas_.count(indice) == 0) {
                fn_.slots.push_back(Type::I64);
                fn_.slot_names.push_back("<vivo:" + fn_.slot_names[i] + ">");
                banderas_.emplace(indice, static_cast<std::uint32_t>(fn_.slots.size() - 1));
            }
        }

        if (decl.return_type_id() < static_cast<std::uint32_t>(module_.types_size())) {
            retorno_ = concreto(module_.types(static_cast<int>(decl.return_type_id())));
        }
        if (!tipo_de(module_, decl.return_type_id(), fn_.result)) {
            fallo("el retorno de '" + decl.name() + "' es de tipo " +
                      notacion(decl.return_type_id()) + " y el MIR no lo "
                      "representa todavia" + porque(decl.return_type_id()),
                  ln, col);
            return false;
        }

        actual_ = nuevo_bloque();
        // Un parametro por valor ES dueño de lo que recibe desde que empieza
        // el cuerpo (la regla de la 0.3.1): su bandera nace ENCENDIDA. Una
        // local la enciende su declaracion; un parametro no tiene
        // declaracion en el cuerpo, y sin esto su 'drop' no corria nunca.
        for (std::uint32_t i = 0; i < fn_.params; ++i) {
            const auto bandera = banderas_.find(i);
            if (bandera != banderas_.end()) encender_bandera(bandera->second);
        }
        // un parametro escalar al que se le toma la direccion pasa a su celda
        for (std::uint32_t i = 0; i < fn_.params; ++i) {
            if (celdas_.count(i) == 0) continue;
            Reg valor = cargar_slot(i, ln, col);
            Reg celda = celda_con(valor, ln, col);
            guardar_en_slot(i, celda, ln, col);
        }
        if (!bloque(decl.body())) return false;
        // los parametros propios mueren al salir (por el final del cuerpo;
        // 'return' los suelta por su cuenta)
        if (!cerrado()) liberar_parametros();
        // Un cuerpo que se acaba sin 'return': si la funcion devuelve algo, es
        // RT017 al llegar ahi (como en el interprete; antes el llamador recibia
        // un registro sin escribir). Si el camino no se recorre nunca —el
        // bloque de despues de un 'if' cuyas dos ramas devuelven—, no cuesta
        // nada.
        if (fn_.blocks[actual_].term == Term::Unreachable && fn_.result != Type::Void) {
            Inst fallar;
            fallar.op = Op::Fallar;
            fallar.imm = interna("RT017: la función '" + decl.name() + "' terminó sin "
                                 "devolver un valor y su tipo de retorno no es 'void'");
            fallar.line = ln;
            fallar.col = col;
            emitir(std::move(fallar));
        }
        if (fn_.blocks[actual_].term == Term::Unreachable) {
            fn_.blocks[actual_].term = Term::Return;
            fn_.blocks[actual_].has_value = false;
        }
        return limpieza_de_la_funcion();
    }

    // El DESENROLLADO: una excepcion que sale de la funcion sin que nadie la
    // atrape tiene que destruir lo que la funcion deja vivo, igual que el
    // interprete (cuyos bloques destruyen en un 'finally'). Sin esto la VM
    // saltaba al 'catch' del llamador con los locales de aqui sin destruir:
    // el orden de salida difería y, si nadie atrapaba, no se destruian nunca.
    //
    // Es UN bloque por funcion: destruye (con sus banderas, en orden inverso
    // de declaracion) todo slot destruible que siga vivo y relanza. Todo
    // bloque que no este dentro de un 'try' manda sus excepciones aqui.
    bool limpieza_de_la_funcion() {
        std::vector<std::uint32_t> destruibles;
        for (const auto& [slot, bandera] : banderas_) destruibles.push_back(slot);
        if (destruibles.empty()) return true;
        std::sort(destruibles.begin(), destruibles.end());
        if (fn_.throw_slot < 0) {
            fn_.throw_slot = static_cast<int>(slot_nuevo(Type::I64, "<lanzado>"));
            fn_.tag_slot = static_cast<int>(slot_nuevo(Type::I64, "<etiqueta>"));
        }
        const std::size_t antes = fn_.blocks.size();
        const int previo = protegido_;
        protegido_ = -1;
        const BlockId limpieza = nuevo_bloque();
        actual_ = limpieza;
        for (auto it = destruibles.rbegin(); it != destruibles.rend(); ++it) {
            if (!destruir_slot(*it)) return false;
        }
        relanzar_lo_que_viaja();
        protegido_ = previo;
        // los bloques de ANTES de la limpieza que no tenian 'try' que los
        // atrapara: su excepcion pasa por aqui
        for (std::size_t i = 0; i < antes; ++i) {
            Block& b = fn_.blocks[i];
            if (b.handler < 0) b.handler = static_cast<int>(limpieza);
        }
        return true;
    }

    // Termina el bloque en curso relanzando lo que esta en <lanzado> con la
    // etiqueta que trae (-1 = la de <etiqueta>).
    void relanzar_lo_que_viaja() {
        if (cerrado()) return;
        Reg valor = nuevo_reg();
        Inst leer;
        leer.op = Op::LoadLocal;
        leer.dst = valor;
        leer.slot = static_cast<std::uint32_t>(fn_.throw_slot);
        leer.synthetic = true;
        emitir(std::move(leer));
        Block& b = bloque_actual();
        b.term = Term::Throw;
        b.value = valor;
        b.has_value = true;
        b.tag = -1;
    }

    // Destruye el slot 'indice' (si su bandera dice que sigue vivo) con las
    // destrucciones que el frontend anoto para su NOMBRE. El nombre se liga
    // a ESE slot mientras tanto: dos locales homonimas tienen slots distintos.
    bool destruir_slot(std::uint32_t indice) {
        if (temporal_hook_.count(indice) != 0) return destruir_temporal(indice);
        const std::string nombre = fn_.slot_names[indice];
        const auto drops = drops_por_nombre_.find(nombre);
        if (drops == drops_por_nombre_.end()) {
            liberar_si_vivo(indice);   // sin destructor: solo su memoria
            return true;
        }
        const auto antes = nombres_.find(nombre);
        const bool habia = antes != nombres_.end();
        const std::uint32_t slot_previo = habia ? antes->second : 0;
        const auto tipo_antes = tipos_.find(nombre);
        const bool tenia_tipo = tipo_antes != tipos_.end();
        const std::uint32_t tipo_previo = tenia_tipo ? tipo_antes->second : 0;
        nombres_[nombre] = indice;
        const auto tipo = tipo_slot_.find(indice);
        if (tipo != tipo_slot_.end()) tipos_[nombre] = tipo->second;
        bool ok = true;
        for (const pb::Drop* d : drops->second) {
            if (!destruccion(*d)) { ok = false; break; }
        }
        if (habia) nombres_[nombre] = slot_previo; else nombres_.erase(nombre);
        if (tenia_tipo) tipos_[nombre] = tipo_previo; else tipos_.erase(nombre);
        if (ok) liberar_si_vivo(indice);
        return ok;
    }

    // Las destrucciones de cada nombre en todos los bloques de la funcion.
    void recoger_drops(const pb::Block& b) {
        for (const pb::Drop& d : b.drops()) {
            if (d.path_size() == 0) continue;
            auto& lista = drops_por_nombre_[d.path(0)];
            bool repetida = false;
            for (const pb::Drop* otra : lista) {
                if (otra->path_size() != d.path_size()) continue;
                bool igual = true;
                for (int i = 0; i < d.path_size(); ++i) {
                    if (otra->path(i) != d.path(i)) { igual = false; break; }
                }
                if (igual) { repetida = true; break; }
            }
            if (!repetida) lista.push_back(&d);
        }
        const auto sub = [this](const pb::Block& x) { recoger_drops(x); };
        for (const pb::Stmt& st : b.statements()) {
            switch (st.node_case()) {
                case pb::Stmt::kBlock: sub(st.block()); break;
                case pb::Stmt::kIfStmt: {
                    const pb::IfStmt* n = &st.if_stmt();
                    while (n != nullptr) {
                        sub(n->then_block());
                        if (n->has_else_block()) { sub(n->else_block()); n = nullptr; }
                        else if (n->has_else_if()) n = &n->else_if();
                        else n = nullptr;
                    }
                    break;
                }
                case pb::Stmt::kWhileStmt: sub(st.while_stmt().body()); break;
                case pb::Stmt::kMatchStmt:
                    for (const pb::CaseArm& arm : st.match_stmt().cases()) {
                        if (arm.body().node_case() == pb::Stmt::kBlock) sub(arm.body().block());
                    }
                    break;
                case pb::Stmt::kTryStmt:
                    sub(st.try_stmt().try_block());
                    for (const pb::CatchClause& c : st.try_stmt().catches()) sub(c.block());
                    if (st.try_stmt().has_finally_block()) sub(st.try_stmt().finally_block());
                    break;
                default: break;
            }
        }
    }

    // Las sentencias de nivel de MODULO de una unidad, acumuladas en la
    // funcion de inicializacion. Se llama una vez por unidad, asi que el
    // bloque en curso se conserva entre llamadas.
    bool nivel_de_modulo(const pb::Module& modulo) {
        if (fn_.blocks.empty()) actual_ = nuevo_bloque();
        else actual_ = static_cast<BlockId>(fn_.blocks.size() - 1);
        for (const pb::Decl& decl : modulo.items()) {
            if (decl.node_case() != pb::Decl::kStatement) continue;
            const pb::Stmt& stmt = decl.statement();
            if (stmt.node_case() != pb::Stmt::kVarDecl) continue;
            const int g = global(stmt.var_decl().name());
            if (g < 0) continue;
            pb::Type declarado;
            const bool con_tipo = tipo_por_id(stmt.var_decl().type_id(), declarado);
            Reg valor = kNoReg;
            const bool celda = program_.globals[static_cast<std::size_t>(g)].celda;
            if (!stmt.var_decl().has_value()) {
                // una global arranca en cero, salvo un 'T?': null. Una en
                // celda necesita su celda aunque valga cero.
                if (con_tipo && declarado.kind() == pb::NULLABLE) {
                    valor = constante_i(-1, stmt.ln(), stmt.col());
                } else if (celda) {
                    valor = nuevo_reg();
                    Inst cero;
                    cero.op = program_.globals[static_cast<std::size_t>(g)].type == Type::F64
                        ? Op::ConstF : Op::ConstI;
                    cero.dst = valor;
                    emitir(std::move(cero));
                } else {
                    continue;
                }
            } else {
                if (!expresion(stmt.var_decl().value(), valor, false)) return false;
                if (con_tipo) encajar(declarado, stmt.var_decl().value(), valor);
                consumir(valor);
            }
            if (celda) valor = celda_con(valor, stmt.ln(), stmt.col());
            Inst store;
            store.op = Op::StoreGlobal;
            store.slot = static_cast<std::uint32_t>(g);
            store.a = valor;
            store.line = stmt.ln();
            store.col = stmt.col();
            emitir(std::move(store));
        }
        return true;   // NO se cierra aqui: faltan las demas unidades
    }

    // Cierra la funcion de inicializacion, una vez recorridas TODAS las
    // unidades. Cerrarla por unidad dejaba las globales de la segunda detras
    // de un 'return', o sea sin ejecutar.
    void cerrar_inicializacion() {
        if (fn_.blocks.empty()) actual_ = nuevo_bloque();
        if (fn_.blocks[actual_].term == Term::Unreachable) {
            fn_.blocks[actual_].term = Term::Return;
            fn_.blocks[actual_].has_value = false;
        }
    }

private:
    BlockId nuevo_bloque() {
        fn_.blocks.emplace_back();
        // hereda el 'try' que este abierto: un bloque que nace protegido lo
        // esta desde su primera instruccion, y el de un 'try' anidado gana
        // porque 'protegido_' ya es el suyo.
        fn_.blocks.back().handler = protegido_;
        return static_cast<BlockId>(fn_.blocks.size() - 1);
    }

    Reg nuevo_reg() { return fn_.regs++; }

    Block& bloque_actual() { return fn_.blocks[actual_]; }

    // ¿Este bloque ya termino? Entonces lo que sigue es inalcanzable y no se
    // emite: un 'return' a mitad de un bloque lo cierra.
    bool cerrado() const { return fn_.blocks[actual_].term != Term::Unreachable; }

    void emitir(Inst inst) {
        if (cerrado()) return;
        if (!frescos_.empty() && puede_lanzar(inst.op)) guardar_frescos();
        fn_.blocks[actual_].insts.push_back(std::move(inst));
    }

    // ¿Puede esta instruccion lanzar una excepcion que el programa atrapa?
    // (Un RT no: termina el programa y no hay nada que liberar.)
    static bool puede_lanzar(Op op) {
        switch (op) {
            case Op::Call: case Op::CallHost:
            case Op::DivI: case Op::RemI:
            case Op::GetIndex: case Op::SetIndex:
            case Op::ShlI: case Op::ShrI:
                return true;
            default:
                return false;
        }
    }

    // Un temporal recien hecho vive en un REGISTRO, y el desenrollado solo
    // sabe liberar SLOTS. Si algo puede lanzar mientras un temporal espera a
    // su dueño ('usa(C{...}, falla())', 'File{ contenido: leer(r) }'), el
    // temporal pasa a un slot con bandera: asi lo libera el 'catch' de su
    // 'try' o la limpieza de la funcion. En el caso comun —nadie lanza en
    // medio— no cuesta nada.
    //
    // El guardado se escribe DONDE NACIO el temporal, no donde se descubre
    // que hacia falta: entre los dos puede haber ramas (las de un 'match'
    // sobre el temporal, el lado derecho de un 'and'), y guardarlo en una
    // sola dejaba la bandera apagada en las demas —y el temporal sin liberar—.
    void guardar_frescos() {
        for (const Reg r : frescos_) {
            if (fresco_slot_.count(r) != 0) continue;
            const auto origen = origen_fresco_.find(r);
            if (origen == origen_fresco_.end()) continue;
            const Origen donde = origen->second;
            const std::uint32_t slot = slot_nuevo(Type::I64, "<fresco>");
            const std::uint32_t bandera = slot_nuevo(Type::I64, "<vivo:<fresco>>");
            banderas_.emplace(slot, bandera);
            slot_propio_.insert(slot);
            // un temporal que el camino de una excepcion suelta nunca llego a
            // su dueño: se destruye POR SU TIPO (su '__free__' tambien)
            por_tipo_.insert(slot);
            // solo lo libera el 'catch' de un 'try' que YA estaba abierto
            // cuando nacio: uno abierto despues (dentro de una rama del
            // 'match' sobre el temporal) no es su dueño
            if (donde.en_try > 0 && donde.en_try <= en_try_.size()) {
                en_try_[donde.en_try - 1].push_back(slot);
            }
            fresco_slot_.emplace(r, slot);
            Reg uno = nuevo_reg();
            std::vector<Inst> guardar(3);
            guardar[0].op = Op::StoreLocal;
            guardar[0].slot = slot;
            guardar[0].a = r;
            guardar[0].synthetic = true;
            guardar[1].op = Op::ConstI;
            guardar[1].dst = uno;
            guardar[1].imm = 1;
            guardar[2].op = Op::StoreLocal;
            guardar[2].slot = bandera;
            guardar[2].a = uno;
            guardar[2].synthetic = true;
            std::vector<Inst>& insts = fn_.blocks[donde.bloque].insts;
            const std::size_t pos = std::min(donde.pos, insts.size());
            insts.insert(insts.begin() + static_cast<std::ptrdiff_t>(pos),
                         std::make_move_iterator(guardar.begin()),
                         std::make_move_iterator(guardar.end()));
            // los demas puntos de nacimiento del mismo bloque se corren
            for (auto& [otro, o] : origen_fresco_) {
                if (otro != r && o.bloque == donde.bloque && o.pos >= pos) o.pos += 3;
            }
        }
    }

    void fallo(const std::string& que, std::uint32_t ln, std::uint32_t col) {
        fallos_.push_back(Unsupported{que, ln, col});
        ok_ = false;
    }

    void saltar(BlockId destino) {
        if (cerrado()) return;
        Block& b = fn_.blocks[actual_];
        b.term = Term::Jump;
        b.target = destino;
    }

    void ramificar(Reg cond, BlockId si, BlockId no) {
        if (cerrado()) return;
        Block& b = fn_.blocks[actual_];
        b.term = Term::Branch;
        b.cond = cond;
        b.target = si;
        b.otherwise = no;
    }

    // ------------------------------------------------------------------ //
    // sentencias
    // ------------------------------------------------------------------ //
    bool bloque(const pb::Block& b) {
        ambitos_.push_back(&b);
        // lo que el bloque recibe ya vivo (el binding de un 'catch') es suyo
        // y muere con el, tambien por 'return' o 'break'
        propios_.push_back(std::move(propios_al_entrar_));
        propios_al_entrar_.clear();
        restauraciones_.emplace_back();
        for (const pb::Stmt& s : b.statements()) {
            if (!sentencia(s)) return false;
        }
        // La salida NORMAL del bloque. Las otras (return, break, continue)
        // destruyen por su cuenta antes de saltar: en un CFG cada arista que
        // abandona el ambito tiene que pasar por sus destructores, y un drop
        // que solo corriera al caer por el final seria una fuga en cuanto
        // hubiera un 'return' temprano.
        const bool ok = destruir(b);
        if (!cerrado()) liberar_propios(propios_.size() - 1);
        ambitos_.pop_back();
        propios_.pop_back();
        // lo declarado aqui deja de verse: si tapaba un nombre de afuera, ese
        // nombre vuelve (en orden inverso, por si se declaro dos veces)
        std::vector<Restauracion> deshacer = std::move(restauraciones_.back());
        restauraciones_.pop_back();
        for (auto it = deshacer.rbegin(); it != deshacer.rend(); ++it) {
            if (it->habia) {
                nombres_[it->nombre] = it->slot;
                tipos_[it->nombre] = it->tipo;
            } else {
                nombres_.erase(it->nombre);
                tipos_.erase(it->nombre);
            }
        }
        return ok;
    }

    // Los locales que ALGUN bloque de la funcion destruye, por su nombre
    // base. Hace falta antes de bajar nada: son los que necesitan bandera.
    void recoger_destruibles(const pb::Block& b,
                             std::vector<std::string>& salida) const {
        for (const pb::Drop& d : b.drops()) {
            if (d.path_size() > 0) salida.push_back(d.path(0));
        }
        for (const pb::Stmt& s : b.statements()) {
            switch (s.node_case()) {
                case pb::Stmt::kBlock:
                    recoger_destruibles(s.block(), salida);
                    break;
                case pb::Stmt::kIfStmt:
                    recoger_destruibles(s.if_stmt().then_block(), salida);
                    if (s.if_stmt().has_else_block()) {
                        recoger_destruibles(s.if_stmt().else_block(), salida);
                    }
                    break;
                case pb::Stmt::kWhileStmt:
                    recoger_destruibles(s.while_stmt().body(), salida);
                    break;
                case pb::Stmt::kMatchStmt:
                    for (const pb::CaseArm& arm : s.match_stmt().cases()) {
                        if (arm.body().node_case() == pb::Stmt::kBlock) {
                            recoger_destruibles(arm.body().block(), salida);
                        }
                    }
                    break;
                case pb::Stmt::kTryStmt:
                    recoger_destruibles(s.try_stmt().try_block(), salida);
                    for (const pb::CatchClause& c : s.try_stmt().catches()) {
                        recoger_destruibles(c.block(), salida);
                    }
                    if (s.try_stmt().has_finally_block()) {
                        recoger_destruibles(s.try_stmt().finally_block(), salida);
                    }
                    break;
                default:
                    break;
            }
        }
    }

    // ------------------------------------------------------------------ //
    // excepciones
    // ------------------------------------------------------------------ //
    // La identidad de un tipo, deduplicada. Es la MISMA clave estructural que
    // usa el despacho de hooks ('type_key'), no su notacion: dos escrituras
    // del mismo tipo tienen que atrapar lo mismo.
    int etiqueta(const pb::Type& tipo) {
        std::string clave = hir::type_key(tipo);
        for (std::size_t i = 0; i < program_.tags.size(); ++i) {
            if (program_.tags[i] == clave) return static_cast<int>(i);
        }
        program_.tags.push_back(std::move(clave));
        program_.tags_objeto.push_back(formas_.propio(tipo) ? 1 : 0);
        program_.tags_texto.push_back(formas_.modo_texto(tipo));
        return static_cast<int>(program_.tags.size() - 1);
    }

    int etiqueta_de_id(std::uint32_t id) {
        if (id >= static_cast<std::uint32_t>(module_.types_size())) return -1;
        return etiqueta(concreto(module_.types(static_cast<int>(id))));
    }

    // ------------------------------------------------------------------ //
    // FINALLY. En un grafo sin subrutinas, el bloque 'finally' se EMITE en
    // cada salida del 'try': al final del try y de cada catch, en cada
    // 'return'/'break'/'continue' que lo atraviesa y en el camino de la
    // excepcion que sigue de largo. Cada copia lleva el manejador que le toca:
    // en una salida normal, el de afuera (lo que lance el 'finally' sube);
    // con una excepcion EN VUELO, uno que termina el programa (RT022).
    //
    // Las copias no pueden compartir los slots de las variables del 'finally'
    // (cada declaracion del HIR tiene UNO): cada copia recibe slots nuevos, y
    // los originales se consumen al terminar el 'try' sin emitir nada.
    // ------------------------------------------------------------------ //
    // Las declaraciones de un bloque en el ORDEN en que 'resolve' les dio
    // slot (collect_slots_block).
    static void declaraciones_en(const pb::Block& b, std::vector<const pb::VarDecl*>& out) {
        for (const pb::Stmt& s : b.statements()) {
            switch (s.node_case()) {
                case pb::Stmt::kVarDecl: out.push_back(&s.var_decl()); break;
                case pb::Stmt::kBlock: declaraciones_en(s.block(), out); break;
                case pb::Stmt::kIfStmt: {
                    const pb::IfStmt* n = &s.if_stmt();
                    while (n != nullptr) {
                        declaraciones_en(n->then_block(), out);
                        if (n->else_branch_case() == pb::IfStmt::kElseBlock) {
                            declaraciones_en(n->else_block(), out);
                        }
                        n = n->else_branch_case() == pb::IfStmt::kElseIf ? &n->else_if()
                                                                         : nullptr;
                    }
                    break;
                }
                case pb::Stmt::kWhileStmt: declaraciones_en(s.while_stmt().body(), out); break;
                case pb::Stmt::kTryStmt:
                    declaraciones_en(s.try_stmt().try_block(), out);
                    for (const pb::CatchClause& c : s.try_stmt().catches()) {
                        declaraciones_en(c.block(), out);
                    }
                    if (s.try_stmt().has_finally_block()) {
                        declaraciones_en(s.try_stmt().finally_block(), out);
                    }
                    break;
                case pb::Stmt::kMatchStmt:
                    for (const pb::CaseArm& arm : s.match_stmt().cases()) {
                        if (arm.body().node_case() == pb::Stmt::kBlock) {
                            declaraciones_en(arm.body().block(), out);
                        }
                    }
                    break;
                default: break;
            }
        }
    }

    // Slots NUEVOS para las declaraciones de 'b', puestos al frente de sus
    // colas: la proxima bajada de 'b' los usa a ellos.
    void inyectar_slots(const pb::Block& b) {
        std::vector<const pb::VarDecl*> decls;
        declaraciones_en(b, decls);
        std::vector<Pendiente> nuevos;
        for (const pb::VarDecl* v : decls) {
            Type forma = Type::I64;
            tipo_de(module_, v->type_id(), forma);
            const std::uint32_t slot = slot_nuevo(forma, v->name());
            tipo_slot_[slot] = v->type_id();
            const bool propio =
                v->type_id() < static_cast<std::uint32_t>(module_.types_size()) &&
                formas_.propio(concreto(module_.types(static_cast<int>(v->type_id()))));
            if (propio) slot_propio_.insert(slot);
            if (propio || drops_por_nombre_.count(v->name()) != 0) {
                banderas_.emplace(slot, slot_nuevo(Type::I64, "<vivo:" + v->name() + ">"));
            }
            nuevos.push_back(Pendiente{slot, v->type_id()});
        }
        for (std::size_t i = decls.size(); i > 0; --i) {
            pendientes_[decls[i - 1]->name()].push_front(nuevos[i - 1]);
        }
    }

    // Consume los slots ORIGINALES de las declaraciones de 'b' (nunca se
    // usan: cada copia del 'finally' tiene los suyos).
    void consumir_slots(const pb::Block& b) {
        std::vector<const pb::VarDecl*> decls;
        declaraciones_en(b, decls);
        for (const pb::VarDecl* v : decls) {
            auto cola = pendientes_.find(v->name());
            if (cola != pendientes_.end() && !cola->second.empty()) cola->second.pop_front();
        }
    }

    // Una copia del 'finally' de 'r'. 'en_vuelo': hay una excepcion saliendo
    // (esta en <lanzado>/<etiqueta>); se guarda aparte —un 'try' dentro del
    // 'finally' los pisaria— y lo que lance el 'finally' es RT022.
    bool emitir_finally(const Finalizador& r, bool en_vuelo) {
        if (cerrado()) return true;
        const int previo = protegido_;
        std::uint32_t valor_guardado = 0;
        std::uint32_t etiqueta_guardada = 0;
        if (en_vuelo) {
            valor_guardado = slot_nuevo(Type::I64, "<en_vuelo>");
            etiqueta_guardada = slot_nuevo(Type::I64, "<en_vuelo_etiqueta>");
            copiar_slot(static_cast<std::uint32_t>(fn_.throw_slot), valor_guardado);
            copiar_slot(static_cast<std::uint32_t>(fn_.tag_slot), etiqueta_guardada);
            const BlockId aborta = nuevo_bloque();
            const BlockId sigue = actual_;
            actual_ = aborta;
            Inst fallar;
            fallar.op = Op::Fallar;
            fallar.imm = interna("RT022: el 'finally' lanzó mientras ya viajaba otra "
                                 "excepción: un 'finally' no puede lanzar durante un "
                                 "desenrollado. Si limpiar puede fallar, registra el "
                                 "fallo y deja que el 'finally' termine");
            fallar.line = r.line;
            fallar.col = r.col;
            emitir(std::move(fallar));
            bloque_actual().term = Term::Return;   // nunca se llega: Fallar termina
            actual_ = sigue;
            protegido_ = static_cast<int>(aborta);
        } else {
            protegido_ = r.fuera;
        }
        // el finally en su propio bloque, con el manejador que le toca
        const BlockId entrada = nuevo_bloque();
        saltar(entrada);
        actual_ = entrada;
        inyectar_slots(*r.bloque);
        const bool ok = bloque(*r.bloque);
        protegido_ = previo;
        if (!ok) return false;
        // lo que sigue vuelve al manejador de antes
        const BlockId despues = nuevo_bloque();
        saltar(despues);
        actual_ = despues;
        if (en_vuelo) {
            copiar_slot(valor_guardado, static_cast<std::uint32_t>(fn_.throw_slot));
            copiar_slot(etiqueta_guardada, static_cast<std::uint32_t>(fn_.tag_slot));
        }
        return true;
    }

    void copiar_slot(std::uint32_t desde, std::uint32_t hacia) {
        Reg r = nuevo_reg();
        Inst leer;
        leer.op = Op::LoadLocal;
        leer.dst = r;
        leer.slot = desde;
        leer.synthetic = true;
        emitir(std::move(leer));
        Inst guardar_v;
        guardar_v.op = Op::StoreLocal;
        guardar_v.slot = hacia;
        guardar_v.a = r;
        guardar_v.synthetic = true;
        emitir(std::move(guardar_v));
    }

    bool lanzar(const pb::Stmt& s) {
        Reg valor = kNoReg;
        if (!expresion(s.throw_stmt().value(), valor, false)) return false;
        consumir(valor);   // lo lanzado es del 'catch' que lo atrape
        // lanzar un local propio lo cede (el frontend inserta el 'move' solo
        // para lo que tiene destructor)
        if (es_local_propio(s.throw_stmt().value()) &&
            !mover(s.throw_stmt().value())) {
            return false;
        }
        if (cerrado()) return true;
        // 'catch (e) { ...; throw e; }': 'e' no tiene tipo al compilar, pero
        // el valor LLEGO con una etiqueta. Se relanza con esa (como 'raise'
        // en Python), no con la del tipo desconocido: si no, un 'catch (T x)'
        // de mas arriba no lo reconocia. Mismo arreglo que en el interprete.
        const pb::Expr& lanzado = s.throw_stmt().value();
        int etiqueta_fija = etiqueta_de_id(tipo_id_de(lanzado));
        if (lanzado.node_case() == pb::Expr::kIdentifier) {
            const auto llego = etiqueta_de_binding_.find(lanzado.identifier().name());
            if (llego != etiqueta_de_binding_.end()) {
                Reg etiqueta_original = nuevo_reg();
                Inst leer;
                leer.op = Op::LoadLocal;
                leer.dst = etiqueta_original;
                leer.slot = llego->second;
                leer.synthetic = true;
                emitir(std::move(leer));
                Inst guardar;
                guardar.op = Op::StoreLocal;
                guardar.slot = static_cast<std::uint32_t>(fn_.tag_slot);
                guardar.a = etiqueta_original;
                guardar.synthetic = true;
                emitir(std::move(guardar));
                etiqueta_fija = -1;   // -1 = la que esta en <etiqueta>
            }
        }
        Block& b = bloque_actual();
        b.term = Term::Throw;
        b.value = valor;
        b.has_value = true;
        b.tag = etiqueta_fija;
        return true;
    }

    // Un slot del marco creado por el MIR y no por el frontend (el aterrizaje
    // de una excepcion, el binding de un 'catch'). Se anade al final: los
    // indices ya emitidos no se mueven.
    std::uint32_t slot_nuevo(Type tipo, const std::string& nombre) {
        fn_.slots.push_back(tipo);
        fn_.slot_names.push_back(nombre);
        return static_cast<std::uint32_t>(fn_.slots.size() - 1);
    }

    bool intentar(const pb::Stmt& s) {
        const pb::TryStmt& nodo = s.try_stmt();
        if (fn_.throw_slot < 0) {
            fn_.throw_slot =
                static_cast<int>(slot_nuevo(Type::I64, "<lanzado>"));
            fn_.tag_slot =
                static_cast<int>(slot_nuevo(Type::I64, "<etiqueta>"));
        }

        const BlockId pad = nuevo_bloque();
        const BlockId fin = nuevo_bloque();

        // el cuerpo protegido: TODO bloque que nazca aqui dentro manda sus
        // excepciones al pad
        const int previo = protegido_;
        protegido_ = static_cast<int>(pad);
        const BlockId inicio = nuevo_bloque();
        saltar(inicio);
        actual_ = inicio;
        en_try_.emplace_back();
        const bool con_finally = nodo.has_finally_block();
        Finalizador region{con_finally ? &nodo.finally_block() : nullptr,
                           ambitos_.size(), previo, s.ln(), s.col()};
        if (con_finally && nodo.finally_block().statements_size() > 0) {
            region.line = nodo.finally_block().statements(0).ln();
            region.col = nodo.finally_block().statements(0).col();
        }
        if (con_finally) finales_.push_back(region);
        const bool ok = bloque(nodo.try_block());
        if (con_finally) finales_.pop_back();
        std::vector<std::uint32_t> declarados = std::move(en_try_.back());
        en_try_.pop_back();
        // lo declarado en este try tambien esta dentro del de afuera
        if (!en_try_.empty()) {
            en_try_.back().insert(en_try_.back().end(), declarados.begin(),
                                  declarados.end());
        }
        protegido_ = previo;
        if (!ok) return false;
        // la salida normal del try pasa por el 'finally'
        if (con_finally && !emitir_finally(region, false)) return false;
        saltar(fin);
        // Con 'finally', lo que sale de un 'catch' por una excepcion —y lo que
        // ninguna rama atrapa— pasa por 'pad_catch': destruye lo del catch,
        // corre el 'finally' y relanza hacia afuera.
        const BlockId pad_catch = con_finally ? nuevo_bloque() : 0;

        // el pad. Primero el DESENROLLADO del bloque protegido: lo que se
        // declaro dentro y sigue vivo se destruye antes de que corra el
        // 'catch', como en el interprete. Despues decide QUE rama atrapa,
        // comparando etiquetas.
        actual_ = pad;
        for (auto it = declarados.rbegin(); it != declarados.rend(); ++it) {
            if (banderas_.count(*it) != 0 && !destruir_slot(*it)) return false;
        }
        Reg etiqueta_viva = nuevo_reg();
        Inst carga;
        carga.op = Op::LoadLocal;
        carga.dst = etiqueta_viva;
        carga.slot = static_cast<std::uint32_t>(fn_.tag_slot);
        emitir(std::move(carga));

        if (con_finally) {
            protegido_ = static_cast<int>(pad_catch);
            en_try_.emplace_back();
        }
        for (const pb::CatchClause& rama : nodo.catches()) {
            const BlockId cuerpo = nuevo_bloque();
            BlockId siguiente = cuerpo;
            if (rama.has_type()) {
                siguiente = nuevo_bloque();
                Reg esperada = nuevo_reg();
                Inst cte;
                cte.op = Op::ConstI;
                cte.dst = esperada;
                cte.imm = etiqueta(rama.type());
                emitir(std::move(cte));
                Reg igual = nuevo_reg();
                Inst cmp;
                cmp.op = Op::EqI;
                cmp.dst = igual;
                cmp.a = etiqueta_viva;
                cmp.b = esperada;
                emitir(std::move(cmp));
                ramificar(igual, cuerpo, siguiente);
            } else {
                saltar(cuerpo);
            }

            actual_ = cuerpo;
            // El binding vive SOLO en el ambito de su rama: si tapa un
            // nombre de fuera, ese nombre vuelve al salir. Sin restaurarlo,
            // un 'catch (x)' se llevaba por delante la 'x' del resto de la
            // funcion.
            const bool tapaba = nombres_.count(rama.name()) != 0;
            const std::uint32_t previo_slot =
                tapaba ? nombres_[rama.name()] : 0;
            const auto tipo_previo = tipos_.find(rama.name());
            const bool tenia_tipo = tipo_previo != tipos_.end();
            const std::uint32_t tipo_anterior = tenia_tipo ? tipo_previo->second : 0;
            // El binding de una rama con tipo ES de ese tipo: anotarlo es lo
            // que deja escribirlo en un f-string ('{e}') o leer sus campos.
            // Sin tipo ('catch (e)') queda desconocido, como en la Semantica.
            const std::uint32_t tipo_rama =
                rama.has_type() ? id_de_tipo(rama.type()) : 0;
            Type forma = Type::I64;
            if (tipo_rama != 0) tipo_de(module_, tipo_rama, forma);
            const std::uint32_t slot = slot_nuevo(forma, rama.name());
            nombres_[rama.name()] = slot;
            if (tipo_rama != 0) tipos_[rama.name()] = tipo_rama;
            else tipos_.erase(rama.name());
            // el tipo ESCRITO de la rama, por si no esta en el pool de la
            // unidad (un 'catch (cu.Error e)' que nada mas de la unidad usa)
            const auto escrito_previo = escritos_.find(rama.name());
            const pb::Type* escrito_anterior =
                escrito_previo != escritos_.end() ? escrito_previo->second : nullptr;
            if (rama.has_type()) escritos_[rama.name()] = &rama.type();
            else escritos_.erase(rama.name());
            Reg atrapado = nuevo_reg();
            Inst leer;
            leer.op = Op::LoadLocal;
            leer.dst = atrapado;
            leer.slot = static_cast<std::uint32_t>(fn_.throw_slot);
            emitir(std::move(leer));
            Inst guardar_val;
            guardar_val.op = Op::StoreLocal;
            guardar_val.slot = slot;
            guardar_val.a = atrapado;
            emitir(std::move(guardar_val));
            const auto etiqueta_previa = etiqueta_de_binding_.find(rama.name());
            const bool tenia_etiqueta = etiqueta_previa != etiqueta_de_binding_.end();
            const std::uint32_t etiqueta_anterior =
                tenia_etiqueta ? etiqueta_previa->second : 0;
            if (!rama.has_type()) {
                const std::uint32_t guarda = slot_nuevo(Type::I64,
                                                        "<etiqueta:" + rama.name() + ">");
                Reg viva = nuevo_reg();
                Inst leer_et;
                leer_et.op = Op::LoadLocal;
                leer_et.dst = viva;
                leer_et.slot = static_cast<std::uint32_t>(fn_.tag_slot);
                leer_et.synthetic = true;
                emitir(std::move(leer_et));
                Inst guardar_et;
                guardar_et.op = Op::StoreLocal;
                guardar_et.slot = guarda;
                guardar_et.a = viva;
                guardar_et.synthetic = true;
                emitir(std::move(guardar_et));
                etiqueta_de_binding_[rama.name()] = guarda;
            } else {
                etiqueta_de_binding_.erase(rama.name());
            }
            // El 'catch' es DUEÑO de lo que atrapa y lo destruye al cerrar su
            // bloque (el frontend anota ese drop). Su slot nace aqui, asi que
            // su bandera tambien: sin ella el valor lanzado no se destruia.
            // Lo atrapado es del 'catch'. Con tipo, si es un objeto propio;
            // sin tipo, quiza (lo decide la etiqueta al ejecutar).
            const bool sin_tipo = !rama.has_type();
            const bool propio = sin_tipo || formas_.propio(concreto(rama.type()));
            if (propio) {
                slot_propio_.insert(slot);
                if (sin_tipo) etiqueta_de_slot_[slot] = etiqueta_de_binding_.at(rama.name());
                propios_al_entrar_.push_back(slot);
            }
            if ((drops_por_nombre_.count(rama.name()) != 0 || propio) &&
                banderas_.count(slot) == 0) {
                const std::uint32_t bandera = slot_nuevo(Type::I64,
                                                         "<vivo:" + rama.name() + ">");
                banderas_.emplace(slot, bandera);
                encender_bandera(bandera);
            }
            if (con_finally) {
                en_try_.back().push_back(slot);
                finales_.push_back(region);
            }
            const bool bien = bloque(rama.block());
            if (con_finally) finales_.pop_back();
            if (!bien) return false;
            if (tapaba) nombres_[rama.name()] = previo_slot;
            else nombres_.erase(rama.name());
            if (tenia_tipo) tipos_[rama.name()] = tipo_anterior;
            else tipos_.erase(rama.name());
            if (escrito_anterior != nullptr) escritos_[rama.name()] = escrito_anterior;
            else escritos_.erase(rama.name());
            if (tenia_etiqueta) etiqueta_de_binding_[rama.name()] = etiqueta_anterior;
            else etiqueta_de_binding_.erase(rama.name());
            // la salida normal del catch tambien pasa por el 'finally'
            if (con_finally && !emitir_finally(region, false)) return false;
            saltar(fin);
            actual_ = siguiente;
        }

        if (con_finally) {
            // ninguna rama lo atrapo: el 'finally' corre y la excepcion sigue
            saltar(pad_catch);
            protegido_ = previo;
            std::vector<std::uint32_t> del_catch = std::move(en_try_.back());
            en_try_.pop_back();
            if (!en_try_.empty()) {
                en_try_.back().insert(en_try_.back().end(), del_catch.begin(),
                                      del_catch.end());
            }
            actual_ = pad_catch;
            for (auto it = del_catch.rbegin(); it != del_catch.rend(); ++it) {
                if (banderas_.count(*it) != 0 && !destruir_slot(*it)) return false;
            }
            if (!emitir_finally(region, true)) return false;
            if (!cerrado()) {
                Reg valor = nuevo_reg();
                Inst leer;
                leer.op = Op::LoadLocal;
                leer.dst = valor;
                leer.slot = static_cast<std::uint32_t>(fn_.throw_slot);
                emitir(std::move(leer));
                Block& b = bloque_actual();
                b.term = Term::Throw;
                b.value = valor;
                b.has_value = true;
                b.tag = -1;   // se relanza con la etiqueta que ya traia
            }
            // sus declaraciones originales ya no se usan: cada copia tuvo las suyas
            consumir_slots(nodo.finally_block());
            actual_ = fin;
            return true;
        }

        // ninguna rama sabe manejarlo: sigue propagandose. Es lo que hace util
        // filtrar por tipo — un 'catch' que no entiende el fallo no se lo
        // queda.
        if (!cerrado()) {
            Reg valor = nuevo_reg();
            Inst leer;
            leer.op = Op::LoadLocal;
            leer.dst = valor;
            leer.slot = static_cast<std::uint32_t>(fn_.throw_slot);
            emitir(std::move(leer));
            Block& b = bloque_actual();
            b.term = Term::Throw;
            b.value = valor;
            b.has_value = true;
            b.tag = -1;   // se relanza con la etiqueta que ya traia
        }

        actual_ = fin;
        return true;
    }

    // ------------------------------------------------------------------ //
    // destrucciones
    // ------------------------------------------------------------------ //
    // Las destrucciones de UN ambito, cada una guardada por su bandera de
    // vivo.
    //
    // La lista es estatica pero el drop NO es incondicional: un valor movido
    // o liberado ya no se destruye. El interprete lo sabe porque su celda
    // lleva el estado; aqui ese estado es una BANDERA por local —un slot de
    // 0/1 que se pone al inicializar y se quita al mover o liberar—, que es
    // como lo resuelve cualquier IR de registros: la alternativa seria
    // etiquetar cada valor en ejecucion para responder algo que el flujo ya
    // decide.
    bool destruir(const pb::Block& b) {
        for (const pb::Drop& d : b.drops()) {
            if (cerrado()) break;   // tras un 'return' no queda nada que morir
            if (!destruccion(d)) return false;
        }
        return true;
    }

    bool destruccion(const pb::Drop& d) {
        if (d.path_size() == 0) return true;
        const std::string& base = d.path(0);
        const auto vigente = nombres_.find(base);
        if (vigente == nombres_.end()) return true;   // no vive en este marco
        const auto bandera = banderas_.find(vigente->second);
        if (bandera == banderas_.end()) return true;  // no se destruye

        int destino = -1;
        if (d.by_type()) {
            // por su TIPO: solo si lo que hay puede tener algo que destruir
            if (!destruible_por_tipo(d, vigente->second)) return true;
        } else if (!funcion_del_hook(d.hook(), destino)) {
            // el hook no esta ligado: el frontend ya lo dijo, y bajar una
            // llamada a nada seria peor que no bajarla.
            return true;
        }

        // Los indices del camino ANTES de emitir nada: cada tramo es un campo
        // del tipo del tramo ANTERIOR ('e.c.b' busca 'b' en el struct de
        // 'c', no en el de 'e'). Antes se buscaba siempre en el de la base, y
        // si no estaba se salia con un bloque abierto: el destructor de un
        // campo anidado no corria nunca.
        std::vector<int> indices;
        {
            // un 'catch (e)' sin tipo no tiene tipo anotado: sin camino que bajar
            const auto con_tipo = tipos_.find(base);
            const pb::Type* actual = con_tipo == tipos_.end() ? nullptr
                                                               : nominal_de(con_tipo->second);
            if (actual == nullptr && d.path_size() > 1) return true;
            pb::Type concreto_actual;
            if (actual != nullptr) concreto_actual = concreto(*actual);
            for (int i = 1; i < d.path_size(); ++i) {
                if (actual == nullptr) return true;
                const Formas::Declaracion decl = formas_.declaracion(concreto_actual.name());
                if (decl.estructura == nullptr) return true;
                int indice = -1;
                for (int k = 0; k < decl.estructura->fields_size(); ++k) {
                    if (decl.estructura->fields(k).name() == d.path(i)) { indice = k; break; }
                }
                if (indice < 0) return true;
                indices.push_back(indice);
                const pb::Type* campo = Formas::tipo_en(
                    *decl.modulo, decl.estructura->fields(indice).type_id());
                if (campo == nullptr) { actual = nullptr; continue; }
                Sustitucion sus;
                for (int k = 0; k < decl.estructura->type_params_size() &&
                                k < concreto_actual.args_size(); ++k) {
                    sus.emplace(decl.estructura->type_params(k), concreto_actual.args(k));
                }
                pb::Type siguiente = sustituir(*campo, sus);
                while ((siguiente.kind() == pb::POINTER || siguiente.kind() == pb::NULLABLE) &&
                       siguiente.has_inner()) {
                    pb::Type dentro = siguiente.inner();
                    siguiente = std::move(dentro);
                }
                concreto_actual = siguiente;
                actual = siguiente.kind() == pb::NOMINAL ? &concreto_actual : nullptr;
            }
        }

        // if (bandera) { __free__(valor); bandera = 0; }
        Reg viva = nuevo_reg();
        Inst carga;
        carga.op = Op::LoadLocal;
        carga.dst = viva;
        carga.slot = bandera->second;
        carga.synthetic = true;
        emitir(std::move(carga));

        const BlockId cuerpo = nuevo_bloque();
        const BlockId sigue = nuevo_bloque();
        ramificar(viva, cuerpo, sigue);
        actual_ = cuerpo;

        // el valor a destruir: el local, y despues los campos del camino
        Reg valor = nuevo_reg();
        Inst leer;
        leer.op = Op::LoadLocal;
        leer.dst = valor;
        leer.slot = nombres_.at(base);
        leer.synthetic = true;
        emitir(std::move(leer));
        for (const int indice : indices) {
            Reg campo = nuevo_reg();
            Inst get;
            get.op = Op::GetField;
            get.dst = campo;
            get.a = valor;
            get.imm = indice;
            get.synthetic = true;
            emitir(std::move(get));
            valor = campo;
        }
        if (d.path_size() > 1) {
            // un campo cedido ('move c.dentro') quedo en -1: ya no es de 'c'
            Reg vacio = nuevo_reg();
            Inst menos_uno;
            menos_uno.op = Op::ConstI;
            menos_uno.dst = vacio;
            menos_uno.imm = -1;
            menos_uno.synthetic = true;
            emitir(std::move(menos_uno));
            Reg cedido = nuevo_reg();
            Inst cmp;
            cmp.op = Op::EqI;
            cmp.dst = cedido;
            cmp.a = valor;
            cmp.b = vacio;
            cmp.synthetic = true;
            emitir(std::move(cmp));
            const BlockId destruye = nuevo_bloque();
            ramificar(cedido, sigue, destruye);
            actual_ = destruye;
        }

        if (d.by_type()) {
            // 'Destruir' corre el glue y ya libera la memoria de lo que
            // destruye. Un 'catch (e)' sin tipo pasa su etiqueta: lo lanzado
            // puede no ser un objeto ('throw 7').
            Reg etiqueta = kNoReg;
            const auto sin_tipo = etiqueta_de_slot_.find(vigente->second);
            if (d.path_size() == 1 && sin_tipo != etiqueta_de_slot_.end()) {
                etiqueta = cargar_slot(sin_tipo->second, 0, 0);
            }
            emitir_destruir(valor, etiqueta, d.path_size() > 1);
            if (d.path_size() == 1) apagar_bandera(bandera->second);
            saltar(sigue);
            actual_ = sigue;
            return true;
        }
        Inst llamar;
        llamar.op = Op::Call;
        llamar.func = destino;
        llamar.args.push_back(valor);
        llamar.synthetic = true;
        llamar.destructor = true;
        emitir(std::move(llamar));
        // La destruccion de la RAIZ la deja muerta: su memoria se libera y su
        // bandera se apaga. La de un CAMPO ('c.dentro') solo corre el
        // destructor del campo: la raiz sigue viva hasta que la libera su
        // ambito (con el campo dentro), y apagar su bandera aqui se saltaba
        // los demas campos y la raiz.
        if (d.path_size() == 1) {
            if (es_slot_propio(nombres_.at(base))) emitir_free(valor);
            apagar_bandera(bandera->second);
        }
        saltar(sigue);
        actual_ = sigue;
        return true;
    }

    // ¿Un drop POR TIPO tiene algo que destruir? Un 'catch (e)' sin tipo, si
    // (lo decide su etiqueta al ejecutar); un campo puntero, si (lo decide si
    // es un bloque); un local, si su tipo concreto es un objeto propio —un
    // 'T' instanciado con 'int' no tiene nada—.
    bool destruible_por_tipo(const pb::Drop& d, std::uint32_t slot) const {
        if (d.path_size() > 1) return true;
        if (etiqueta_de_slot_.count(slot) != 0) return true;
        const auto con_tipo = tipos_.find(d.path(0));
        if (con_tipo == tipos_.end() || con_tipo->second == 0 ||
            con_tipo->second >= static_cast<std::uint32_t>(module_.types_size())) {
            return false;
        }
        return formas_.propio(concreto(module_.types(static_cast<int>(con_tipo->second))));
    }

    void emitir_destruir(Reg r, Reg etiqueta = kNoReg, bool solo_bloque = false) {
        Inst d;
        d.op = Op::Destruir;
        d.a = r;
        d.b = etiqueta;
        d.imm = solo_bloque ? 1 : 0;
        d.synthetic = true;
        emitir(std::move(d));
    }

    // ------------------------------------------------------------------ //
    // LIBERAR MEMORIA. Cada objeto tiene un dueño y muere con el:
    //   - un slot propio (local, parametro, binding de 'catch') al cerrar su
    //     ambito o al salir de la funcion, si su bandera dice que sigue vivo;
    //   - un objeto RECIEN HECHO que nadie toma ('f().x', 'crear();') al
    //     cerrar su expresion completa;
    //   - el valor viejo de un lugar al asignarle otro.
    // 'Free' es profundo (se lleva los objetos propios de sus campos), asi
    // que liberar la raiz basta.
    // ------------------------------------------------------------------ //
    bool es_slot_propio(std::uint32_t slot) const {
        return slot_propio_.count(slot) != 0;
    }

    void emitir_free(Reg r) {
        Inst f;
        f.op = Op::Free;
        f.a = r;
        f.synthetic = true;
        emitir(std::move(f));
    }

    // if (vivo) { Free(slot); vivo = 0; } — 'Destruir' si se destruye POR SU
    // TIPO (el valor viejo de una asignacion que lo pide, un temporal que el
    // camino de una excepcion suelta).
    void liberar_si_vivo(std::uint32_t slot, bool por_tipo = false) {
        if (!es_slot_propio(slot) || cerrado()) return;
        const auto bandera = banderas_.find(slot);
        if (bandera == banderas_.end()) return;
        Reg viva = nuevo_reg();
        Inst carga;
        carga.op = Op::LoadLocal;
        carga.dst = viva;
        carga.slot = bandera->second;
        carga.synthetic = true;
        emitir(std::move(carga));
        const BlockId cuerpo = nuevo_bloque();
        const BlockId sigue = nuevo_bloque();
        ramificar(viva, cuerpo, sigue);
        actual_ = cuerpo;
        Reg valor = nuevo_reg();
        Inst leer;
        leer.op = Op::LoadLocal;
        leer.dst = valor;
        leer.slot = slot;
        leer.synthetic = true;
        emitir(std::move(leer));
        const auto sin_tipo = etiqueta_de_slot_.find(slot);
        if (por_tipo || por_tipo_.count(slot) != 0) {
            emitir_destruir(valor, sin_tipo == etiqueta_de_slot_.end()
                                       ? kNoReg : cargar_slot(sin_tipo->second, 0, 0));
        } else if (sin_tipo == etiqueta_de_slot_.end()) {
            emitir_free(valor);
        } else {
            Reg etiqueta = nuevo_reg();
            Inst leer_et;
            leer_et.op = Op::LoadLocal;
            leer_et.dst = etiqueta;
            leer_et.slot = sin_tipo->second;
            leer_et.synthetic = true;
            emitir(std::move(leer_et));
            Inst f;
            f.op = Op::FreeLanzado;
            f.a = valor;
            f.b = etiqueta;
            f.synthetic = true;
            emitir(std::move(f));
        }
        apagar_bandera(bandera->second);
        saltar(sigue);
        actual_ = sigue;
    }

    // Los slots propios que declaro el ambito 'nivel', del ultimo al primero.
    void liberar_propios(std::size_t nivel) {
        if (nivel >= propios_.size()) return;
        const std::vector<std::uint32_t>& lista = propios_[nivel];
        for (auto it = lista.rbegin(); it != lista.rend(); ++it) liberar_si_vivo(*it);
    }

    // Los parametros propios, al salir de la funcion.
    void liberar_parametros() {
        for (std::uint32_t i = fn_.params; i > 0; --i) liberar_si_vivo(i - 1);
    }

    // ¿'e' nombra un local (o parametro) cuyo valor es un objeto propio?
    bool es_local_propio(const pb::Expr& e) const {
        if (e.node_case() != pb::Expr::kIdentifier) return false;
        const auto slot = nombres_.find(e.identifier().name());
        return slot != nombres_.end() && es_slot_propio(slot->second) &&
               !es_celda(slot->second);
    }

    // ¿El valor de 'e' es un objeto propio?
    bool es_valor_propio(const pb::Expr& e) const {
        pb::Type t;
        return tipo_concreto_de(e, t) && formas_.propio(t);
    }

    // --- CELDAS ---------------------------------------------------------- //
    // Un escalar que tiene que vivir en el MONTON es un objeto de UN campo:
    // el de un local al que se le toma la direccion ('&n', y 'p[0]' lo lee)
    // y el valor de un 'T?' de un escalar (-1 sigue siendo null).
    Reg constante_i(std::int64_t v, std::uint32_t ln, std::uint32_t col) {
        Reg r = nuevo_reg();
        Inst c;
        c.op = Op::ConstI;
        c.dst = r;
        c.imm = v;
        c.line = ln;
        c.col = col;
        emitir(std::move(c));
        return r;
    }

    Reg cargar_slot(std::uint32_t slot, std::uint32_t ln, std::uint32_t col) {
        Reg r = nuevo_reg();
        Inst load;
        load.op = Op::LoadLocal;
        load.dst = r;
        load.slot = slot;
        load.line = ln;
        load.col = col;
        emitir(std::move(load));
        return r;
    }

    void guardar_en_slot(std::uint32_t slot, Reg v, std::uint32_t ln, std::uint32_t col) {
        Inst store;
        store.op = Op::StoreLocal;
        store.slot = slot;
        store.a = v;
        store.line = ln;
        store.col = col;
        emitir(std::move(store));
    }

    Reg celda_con(Reg valor, std::uint32_t ln, std::uint32_t col,
                  std::int32_t layout = -1) {
        Reg celda = nuevo_reg();
        Inst alloc;
        alloc.op = Op::Alloc;
        alloc.dst = celda;
        alloc.imm = 1;
        alloc.layout = layout;
        alloc.line = ln;
        alloc.col = col;
        emitir(std::move(alloc));
        escribir_celda(celda, valor, ln, col);
        return celda;
    }

    Reg leer_celda(Reg celda, std::uint32_t ln, std::uint32_t col) {
        Reg cero = constante_i(0, ln, col);
        Reg r = nuevo_reg();
        Inst get;
        get.op = Op::GetIndex;
        get.dst = r;
        get.a = celda;
        get.b = cero;
        get.line = ln;
        get.col = col;
        emitir(std::move(get));
        return r;
    }

    void escribir_celda(Reg celda, Reg valor, std::uint32_t ln, std::uint32_t col) {
        Reg cero = constante_i(0, ln, col);
        Inst set;
        set.op = Op::SetIndex;
        set.a = celda;
        set.b = cero;
        set.c = valor;
        set.line = ln;
        set.col = col;
        emitir(std::move(set));
    }

    bool es_celda(std::uint32_t slot) const { return celdas_.count(slot) != 0; }

    // ¿El campo 'indice' del objeto de 'acceso' guarda una celda?
    bool es_campo_celda(const pb::Expr& acceso, int indice) const {
        const pb::Type* tipo = nominal_de(tipo_id_de(acceso.member().obj()));
        if (tipo == nullptr) return false;
        const Formas::Declaracion d = formas_.declaracion(concreto(*tipo).name());
        return d.estructura != nullptr && formas_.campo_en_celda(d.estructura, indice);
    }

    // Un escalar que entra donde se espera un 'T?' de un escalar se ENCAJA
    // en una celda nueva, que queda fresca: quien la toma la consume. El
    // literal 'null' ya es -1 y un 'T?' ya es una celda.
    void encajar(const pb::Type& destino, const pb::Expr& origen, Reg& r) {
        if (!es_caja(destino) || cerrado()) return;
        if (origen.node_case() == pb::Expr::kLiteral) {
            if (origen.literal().kind() == "null") return;
        } else {
            pb::Type t;
            if (!tipo_concreto_de(origen, t) || !es_escalar(t)) return;
        }
        r = celda_con(r, origen.ln(), origen.col(), formas_.forma(destino));
        fresco(r);
    }

    // El tipo concreto de un id del pool de esta unidad.
    bool tipo_por_id(std::uint32_t id, pb::Type& out) const {
        if (id == 0 || id >= static_cast<std::uint32_t>(module_.types_size())) return false;
        out = concreto(module_.types(static_cast<int>(id)));
        return true;
    }

    // Un objeto recien hecho: si nadie lo toma antes de que termine su
    // expresion completa, muere ahi (como un temporal de C++).
    void fresco(Reg r) {
        if (r == kNoReg) return;
        origen_fresco_[r] = Origen{actual_, fn_.blocks[actual_].insts.size(), en_try_.size()};
        frescos_.push_back(r);
    }

    // Alguien se quedo con 'r' (un binding, una asignacion, un parametro por
    // valor, un 'return', un campo): ya no es un temporal.
    void consumir(Reg r) {
        for (auto it = frescos_.rbegin(); it != frescos_.rend(); ++it) {
            if (*it == r) {
                frescos_.erase(std::next(it).base());
                // estaba en un slot por si algo lanzaba: ahora tiene dueño
                const auto guardado = fresco_slot_.find(r);
                if (guardado != fresco_slot_.end()) {
                    apagar_bandera(banderas_.at(guardado->second));
                    fresco_slot_.erase(guardado);
                }
                return;
            }
        }
    }

    // Libera un temporal: por su registro, o por su slot si tuvo que
    // guardarse (con su bandera, que un camino de excepcion ya pudo apagar).
    void soltar_fresco(Reg r) {
        const auto guardado = fresco_slot_.find(r);
        if (guardado != fresco_slot_.end()) {
            liberar_si_vivo(guardado->second);
        } else {
            emitir_free(r);
        }
    }

    void soltar_frescos(std::size_t marca) {
        while (frescos_.size() > marca) {
            const Reg r = frescos_.back();
            frescos_.pop_back();
            if (!cerrado()) soltar_fresco(r);
            fresco_slot_.erase(r);
        }
    }

    // Una salida anticipada suelta los frescos vivos sin desapilarlos: el
    // camino que no salta todavia los tiene.
    void soltar_frescos_al_salir(std::size_t desde) {
        for (std::size_t i = frescos_.size(); i > desde; --i) {
            if (cerrado()) break;
            soltar_fresco(frescos_[i - 1]);
        }
    }

    // ------------------------------------------------------------------ //
    // TEMPORALES: un valor que posee recursos y que nadie recibe
    // ('recibe(R{...})' no le da dueño a nadie) muere al terminar la
    // SENTENCIA que lo produjo, tambien si sale por una excepcion. Es la
    // regla del interprete ('exec_stmt' con su 'finally').
    //
    // Cada temporal es un slot sintetico con su BANDERA, igual que una
    // local: asi el desenrollado (la limpieza de la funcion y los pads de
    // 'try') lo destruye con la misma maquinaria, sin un camino aparte.
    // ------------------------------------------------------------------ //
    void registrar_temporal(Reg valor, const pb::HookRef& hook) {
        if (hook.owner_type().empty()) return;
        int destino = -1;
        if (!funcion_del_hook(hook, destino)) return;   // el frontend ya lo dijo
        consumir(valor);   // lo suelta este camino (con su destructor)
        const std::uint32_t slot = slot_nuevo(
            Type::I64, "<temporal:" + std::to_string(fn_.slots.size()) + ">");
        const std::uint32_t bandera = slot_nuevo(
            Type::I64, "<vivo:temporal:" + std::to_string(slot) + ">");
        banderas_.emplace(slot, bandera);
        temporal_hook_.emplace(slot, destino);
        Inst guardar;
        guardar.op = Op::StoreLocal;
        guardar.slot = slot;
        guardar.a = valor;
        guardar.synthetic = true;
        emitir(std::move(guardar));
        encender_bandera(bandera);
        temporales_.push_back(slot);
        if (!en_try_.empty()) en_try_.back().push_back(slot);
    }

    // Un temporal que se destruye POR SU TIPO ('temp_by_type'): posee sin
    // declarar '__free__', o es un 'T'. Mismo slot con bandera que uno con
    // hook; al morir, 'Destruir'.
    void registrar_temporal_por_tipo(Reg valor) {
        consumir(valor);
        const std::uint32_t slot = slot_nuevo(
            Type::I64, "<temporal:" + std::to_string(fn_.slots.size()) + ">");
        const std::uint32_t bandera = slot_nuevo(
            Type::I64, "<vivo:temporal:" + std::to_string(slot) + ">");
        banderas_.emplace(slot, bandera);
        temporal_hook_.emplace(slot, -1);
        Inst guardar;
        guardar.op = Op::StoreLocal;
        guardar.slot = slot;
        guardar.a = valor;
        guardar.synthetic = true;
        emitir(std::move(guardar));
        encender_bandera(bandera);
        temporales_.push_back(slot);
        if (!en_try_.empty()) en_try_.back().push_back(slot);
    }

    // Destruye los temporales apilados desde 'marca', del ultimo al primero.
    bool soltar_temporales(std::size_t marca) {
        while (temporales_.size() > marca) {
            const std::uint32_t slot = temporales_.back();
            temporales_.pop_back();
            if (cerrado()) continue;   // tras un 'return' ya los solto la salida
            if (!destruir_temporal(slot)) return false;
        }
        return true;
    }

    // if (vivo) { __free__(temporal); vivo = 0; }
    bool destruir_temporal(std::uint32_t slot) {
        const std::uint32_t bandera = banderas_.at(slot);
        Reg viva = nuevo_reg();
        Inst carga;
        carga.op = Op::LoadLocal;
        carga.dst = viva;
        carga.slot = bandera;
        carga.synthetic = true;
        emitir(std::move(carga));
        const BlockId cuerpo = nuevo_bloque();
        const BlockId sigue = nuevo_bloque();
        ramificar(viva, cuerpo, sigue);
        actual_ = cuerpo;
        Reg valor = nuevo_reg();
        Inst leer;
        leer.op = Op::LoadLocal;
        leer.dst = valor;
        leer.slot = slot;
        leer.synthetic = true;
        emitir(std::move(leer));
        if (temporal_hook_.at(slot) < 0) {
            emitir_destruir(valor);    // por su tipo (ya libera la memoria)
        } else {
            Inst llamar;
            llamar.op = Op::Call;
            llamar.func = temporal_hook_.at(slot);
            llamar.args.push_back(valor);
            llamar.synthetic = true;
            llamar.destructor = true;
            emitir(std::move(llamar));
            emitir_free(valor);
        }
        apagar_bandera(bandera);
        saltar(sigue);
        actual_ = sigue;
        return true;
    }

    // Las destrucciones de los ambitos abiertos, de dentro hacia fuera, hasta
    // 'hasta' sin incluirlo. Es lo que corre una salida ANTICIPADA.
    bool destruir_hasta(std::size_t hasta) {
        for (std::size_t i = ambitos_.size(); i > hasta; --i) {
            if (!destruir(*ambitos_[i - 1])) return false;
            liberar_propios(i - 1);
            // salir del ambito de un try/catch con 'finally' lo corre
            for (auto r = finales_.rbegin(); r != finales_.rend(); ++r) {
                if (r->ambitos == i - 1 && !emitir_finally(*r, false)) return false;
            }
        }
        return true;
    }

    void apagar_bandera(std::uint32_t slot) {
        Reg cero = nuevo_reg();
        Inst c;
        c.op = Op::ConstI;
        c.dst = cero;
        c.imm = 0;
        emitir(std::move(c));
        Inst st;
        st.op = Op::StoreLocal;
        st.slot = slot;
        st.a = cero;
        st.synthetic = true;
        emitir(std::move(st));
    }

    void encender_bandera(std::uint32_t slot) {
        Reg uno = nuevo_reg();
        Inst c;
        c.op = Op::ConstI;
        c.dst = uno;
        c.imm = 1;
        emitir(std::move(c));
        Inst st;
        st.op = Op::StoreLocal;
        st.slot = slot;
        st.a = uno;
        st.synthetic = true;
        emitir(std::move(st));
    }

    // La funcion que implementa un hook, por indice en el programa.
    //
    // El simbolo del hook da el NOMBRE; la unidad la decide el tipo dueno,
    // porque dos tipos pueden declarar cada uno su '__free__' y el nombre
    // suelto no distingue.
    bool funcion_del_hook(const pb::HookRef& ref, int& indice) const {
        const pb::Symbol* simbolo = image_.hook(ref);
        if (simbolo == nullptr) return false;
        int unico = -1;
        int candidatos = 0;
        for (std::size_t i = 0; i < resolved_.functions.size(); ++i) {
            if (resolved_.functions[i].name != simbolo->name()) continue;
            ++candidatos;
            if (unico < 0) unico = static_cast<int>(i);
            // desempate por el DUENO: el primer parametro de un hook es el
            // valor sobre el que actua. Su 'type_id' es del pool de la unidad
            // que DECLARA el hook, no de la que lo llama: leerlo en el pool
            // propio daba otro tipo, y 'sizeof(dt.int8)' caia en el de int16.
            const pb::FunctionDecl* decl = resolved_.functions[i].decl;
            if (decl == nullptr || decl->params_size() == 0) continue;
            const hir::Unit* suya = unidad_de(resolved_.functions[i].unit);
            if (suya == nullptr) continue;
            const pb::Type* dueno = nominal_de(
                suya->module(), decl->params(0).type_id());
            if (dueno != nullptr && dueno->name() == ref.owner_type()) {
                indice = static_cast<int>(i);
                return true;
            }
        }
        if (candidatos == 1) {
            indice = unico;
            return true;
        }
        return false;
    }

    // Los temporales que produzca la sentencia mueren al terminarla.
    bool sentencia(const pb::Stmt& s) {
        const std::size_t marca = temporales_.size();
        const std::size_t marca_frescos = frescos_.size();
        if (!sentencia_sola(s)) return false;
        soltar_frescos(marca_frescos);
        return soltar_temporales(marca);
    }

    // Una salida ANTICIPADA ('return', 'break') suelta los temporales que
    // siguen vivos desde 'desde' sin desapilarlos: el camino que NO salta
    // todavia los tiene y los suelta al cerrar su sentencia (la bandera
    // impide que mueran dos veces).
    bool soltar_temporales_al_salir(std::size_t desde) {
        for (std::size_t i = temporales_.size(); i > desde; --i) {
            if (cerrado()) break;
            if (!destruir_temporal(temporales_[i - 1])) return false;
        }
        return true;
    }

    bool sentencia_sola(const pb::Stmt& s) {
        switch (s.node_case()) {
            case pb::Stmt::kBlock:
                return bloque(s.block());
            case pb::Stmt::kVarDecl:
                return var_decl(s);
            case pb::Stmt::kMoveStmt:
                return mover(s.move_stmt().target());
            case pb::Stmt::kFreeStmt:
                return liberar(s);
            // Ninguna de las dos produce codigo: 'const type T;' nombra un
            // tipo (y los tipos no llegan a la ejecucion) y un binding de
            // import ya lo resolvio el enlazado de la imagen.
            case pb::Stmt::kTypeDecl:
            case pb::Stmt::kImportBinding:
                return true;
            case pb::Stmt::kThrowStmt:
                return lanzar(s);
            case pb::Stmt::kTryStmt:
                return intentar(s);
            case pb::Stmt::kExprStmt: {
                Reg descartado = kNoReg;
                return expresion(s.expr_stmt().expr(), descartado, true);
            }
            case pb::Stmt::kReturnStmt:
                return retorno(s);
            case pb::Stmt::kIfStmt:
                return condicional(s.if_stmt());
            case pb::Stmt::kWhileStmt:
                return bucle(s);
            case pb::Stmt::kBreakStmt:
            case pb::Stmt::kContinueStmt:
                return salto_de_bucle(s);
            case pb::Stmt::kMatchStmt:
                return seleccion(s);
            default:
                fallo("la sentencia '" + std::to_string(
                          static_cast<int>(s.node_case())) +
                      "' no se baja todavia al MIR", s.ln(), s.col());
                return false;
        }
    }

    bool var_decl(const pb::Stmt& s) {
        const pb::VarDecl& v = s.var_decl();
        auto cola = pendientes_.find(v.name());
        if (cola != pendientes_.end() && !cola->second.empty()) {
            const Pendiente propio = cola->second.front();
            cola->second.pop_front();
            if (!restauraciones_.empty()) {
                Restauracion r;
                r.nombre = v.name();
                const auto antes = nombres_.find(v.name());
                r.habia = antes != nombres_.end();
                if (r.habia) {
                    r.slot = antes->second;
                    r.tipo = tipos_.count(v.name()) ? tipos_[v.name()] : 0;
                }
                restauraciones_.back().push_back(std::move(r));
            }
            nombres_[v.name()] = propio.slot;
            tipos_[v.name()] = propio.tipo;
            if (!en_try_.empty()) en_try_.back().push_back(propio.slot);
        }
        const auto slot = nombres_.find(v.name());
        if (slot == nombres_.end()) {
            fallo("la variable '" + v.name() + "' no tiene slot", s.ln(), s.col());
            return false;
        }
        Reg valor = kNoReg;
        pb::Type declarado;
        const bool con_tipo = tipo_por_id(v.type_id(), declarado);
        if (v.has_value()) {
            if (!expresion(v.value(), valor, false)) return false;
            copia_si_es_lugar(v.value(), valor);
            if (con_tipo) encajar(declarado, v.value(), valor);
            consumir(valor);
        } else if (con_tipo && declarado.kind() == pb::NULLABLE) {
            // un 'T?' sin inicializador vale null (el interprete le da None)
            valor = constante_i(-1, s.ln(), s.col());
        } else {
            // Sin inicializador se emite el CERO explicito: un marco no
            // garantiza nada y un 'var' dentro de un bucle se declara en
            // cada vuelta.
            valor = nuevo_reg();
            Inst cero;
            cero.op = fn_.slots[slot->second] == Type::F64 ? Op::ConstF
                                                           : Op::ConstI;
            cero.dst = valor;
            cero.line = s.ln();
            cero.col = s.col();
            emitir(std::move(cero));
        }
        if (es_celda(slot->second)) valor = celda_con(valor, s.ln(), s.col());
        Inst store;
        store.op = Op::StoreLocal;
        store.slot = slot->second;
        store.a = valor;
        store.line = s.ln();
        store.col = s.col();
        emitir(std::move(store));
        // desde aqui el local POSEE algo: su destructor tiene que correr
        const auto bandera = banderas_.find(slot->second);
        if (bandera != banderas_.end()) encender_bandera(bandera->second);
        if (es_slot_propio(slot->second) && !propios_.empty()) {
            propios_.back().push_back(slot->second);
        }
        return true;
    }

    // 'move x': el valor cambia de dueno, asi que este ambito deja de
    // destruirlo. En ejecucion no mueve NADA —el valor ya esta donde esta—;
    // lo unico que ocurre es que la bandera se apaga. Que la lectura ilegal
    // posterior sea un error lo decide el frontend, no la VM.
    bool mover(const pb::Expr& objetivo, bool libera = false) {
        if (objetivo.node_case() == pb::Expr::kMember) return mover_campo(objetivo);
        if (objetivo.node_case() != pb::Expr::kIdentifier) return true;
        const auto slot = nombres_.find(objetivo.identifier().name());
        if (slot == nombres_.end()) return true;
        const auto bandera = banderas_.find(slot->second);
        fn_.vigila_estado = true;
        Inst marca;
        marca.op = Op::MarkMoved;
        marca.slot = slot->second;
        marca.libera = libera;
        // mover un escalar no se lleva su celda: la celda muere con su ambito
        marca.imm = bandera == banderas_.end() || es_celda(slot->second)
            ? -1 : static_cast<std::int64_t>(bandera->second);
        marca.line = objetivo.ln();
        marca.col = objetivo.col();
        emitir(std::move(marca));
        return true;
    }

    // 'free p': llama al destructor AHORA y apaga la bandera, para que el
    // cierre del ambito no lo destruya otra vez.
    bool liberar(const pb::Stmt& s) {
        const pb::FreeStmt& nodo = s.free_stmt();
        Reg valor = kNoReg;
        if (!expresion(nodo.target(), valor, false)) return false;
        int destino = -1;
        // 'free &x' libera lo que es de 'x' y deja a 'x' LIBERADO: el '&' es
        // la forma de nombrarlo, no otra cosa que liberar. Sin desenvolverlo,
        // 'x' seguia vivo: su destructor podia volver a correr al cerrar el
        // ambito y usarlo despues no era RT003.
        const pb::Expr& liberado = nodo.target().node_case() == pb::Expr::kAddrOf
            ? nodo.target().addr_of().operand()
            : nodo.target();
        // 'free p' con 'p' un PUNTERO destruye lo apuntado: su memoria tambien
        // (antes solo se marcaba 'p', y usar despues el dueño no era RT003)
        pb::Type tipo_liberado;
        const bool por_puntero = tipo_concreto_de(liberado, tipo_liberado) &&
                                 tipo_liberado.kind() == pb::POINTER;
        const bool propio = es_valor_propio(liberado) || por_puntero;
        if (nodo.hook().owner_type().empty() ||
            !funcion_del_hook(nodo.hook(), destino)) {
            // sin '__free__' ligado 'free' solo invalida (y suelta la
            // memoria): no hay destructor que llamar.
            if (propio) emitir_free(valor);
            return mover(liberado, true);
        }
        Inst llamar;
        llamar.op = Op::Call;
        llamar.func = destino;
        llamar.args.push_back(valor);
        llamar.line = s.ln();
        llamar.col = s.col();
        llamar.destructor = true;
        emitir(std::move(llamar));
        if (propio) emitir_free(valor);
        return mover(liberado, true);
    }

    bool retorno(const pb::Stmt& s) {
        Reg valor = kNoReg;
        bool trae = s.return_stmt().has_value();
        if (trae && !expresion(s.return_stmt().value(), valor, false)) {
            return false;
        }
        // devolver un CAMPO o una CELDA entrega una copia (el objeto sigue
        // siendo de quien lo tenia); devolver un local lo cede ('transfers')
        if (trae) {
            const pb::Expr& v = s.return_stmt().value();
            const bool local = v.node_case() == pb::Expr::kIdentifier &&
                               nombres_.count(v.identifier().name()) != 0;
            if (!local) copia_si_es_lugar(v, valor);
            encajar(retorno_, v, valor);
            consumir(valor);
        }
        // 'return t' de un local que POSEE recursos: su propiedad pasa al
        // llamador (el frontend lo marca en 'transfers'), asi que el ambito
        // ya no lo destruye. Sin esto 't' moria aqui y el llamador recibia
        // un valor ya destruido, que volvia a destruir.
        // El frontend marca 'transfers' en lo que tiene DESTRUCTOR; para la
        // memoria, cualquier objeto propio devuelto desde un local cambia de
        // dueño igual (si no, se liberaba aqui y el llamador recibia un
        // objeto muerto).
        if (trae && (s.return_stmt().transfers() ||
                     es_local_propio(s.return_stmt().value())) &&
            !ceder_al_devolver(s.return_stmt().value())) {
            return false;
        }
        // los ambitos abiertos mueren ANTES de devolver: el valor ya esta
        // calculado, asi que destruir no se lo lleva por delante.
        if (!soltar_temporales_al_salir(0)) return false;
        soltar_frescos_al_salir(0);
        if (!destruir_hasta(0)) return false;
        liberar_parametros();
        if (cerrado()) return true;
        Block& b = bloque_actual();
        b.term = Term::Return;
        b.value = valor;
        b.has_value = trae;
        return true;
    }

    bool ceder_al_devolver(const pb::Expr& valor) {
        if (valor.node_case() == pb::Expr::kMember) return mover_campo(valor);
        // un temporal o un 'move x' ya no tienen dueño en este marco
        if (valor.node_case() != pb::Expr::kIdentifier) return true;
        const auto slot = nombres_.find(valor.identifier().name());
        if (slot == nombres_.end()) return true;
        const auto bandera = banderas_.find(slot->second);
        if (bandera != banderas_.end()) apagar_bandera(bandera->second);
        return true;
    }

    bool condicional(const pb::IfStmt& nodo) {
        Reg cond = kNoReg;
        const std::size_t marca = frescos_.size();
        const std::size_t marca_temporales = temporales_.size();
        if (!expresion(nodo.condition(), cond, false)) return false;
        soltar_frescos(marca);   // la condicion ya dio su bool
        if (!soltar_temporales(marca_temporales)) return false;

        const BlockId entonces = nuevo_bloque();
        const bool hay_else =
            nodo.else_branch_case() != pb::IfStmt::ELSE_BRANCH_NOT_SET;
        const BlockId si_no = hay_else ? nuevo_bloque() : 0;
        const BlockId despues = nuevo_bloque();
        ramificar(cond, entonces, hay_else ? si_no : despues);

        actual_ = entonces;
        if (!bloque(nodo.then_block())) return false;
        saltar(despues);

        if (hay_else) {
            actual_ = si_no;
            if (nodo.else_branch_case() == pb::IfStmt::kElseBlock) {
                if (!bloque(nodo.else_block())) return false;
            } else {
                if (!condicional(nodo.else_if())) return false;
            }
            saltar(despues);
        }
        actual_ = despues;
        return true;
    }

    bool bucle(const pb::Stmt& s) {
        const BlockId cabecera = nuevo_bloque();
        const BlockId cuerpo = nuevo_bloque();
        const BlockId salida = nuevo_bloque();
        saltar(cabecera);

        actual_ = cabecera;
        Reg cond = kNoReg;
        const std::size_t marca = frescos_.size();
        const std::size_t marca_temporales = temporales_.size();
        if (!expresion(s.while_stmt().condition(), cond, false)) return false;
        soltar_frescos(marca);   // una vez por vuelta, no al salir del bucle
        // lo mismo con los temporales con destructor: mueren al terminar la
        // condicion, como en C++ al final de la expresion completa (antes el
        // slot se pisaba en cada vuelta y solo moria el de la ultima)
        if (!soltar_temporales(marca_temporales)) return false;
        ramificar(cond, cuerpo, salida);

        actual_ = cuerpo;
        bucles_.push_back({cabecera, salida, ambitos_.size(), temporales_.size()});
        const bool bien = bloque(s.while_stmt().body());
        bucles_.pop_back();
        if (!bien) return false;
        saltar(cabecera);

        actual_ = salida;
        return true;
    }

    // 'match' -> el sujeto en un slot y una cadena de comparaciones.
    //
    // No una tabla de saltos: 'br_table' es DENSA (una entrada por cada valor
    // entre el minimo y el maximo) y un enum con valores explicitos
    // ('OK = 200, ROTO = 500') generaria trescientas entradas para dos casos.
    // La cadena no tiene ese problema y sale del 'Branch' que ya existe.
    //
    // El sujeto se evalua UNA vez: 'match (siguiente())' no puede llamar a
    // 'siguiente' una vez por caso.
    bool seleccion(const pb::Stmt& s) {
        const pb::MatchStmt& nodo = s.match_stmt();
        // VM002 antes de bajar nada: 'case v' (binds) LIGA el contenido de un
        // 'T?', y una variante sobre un sujeto 'E?' tendria que saltarse el
        // null antes de leer la etiqueta. Ninguna de las dos se baja todavia.
        pb::Type tipo_sujeto;
        const bool opcional = tipo_concreto_de(nodo.subject(), tipo_sujeto) &&
                              tipo_sujeto.kind() == pb::NULLABLE;
        for (const pb::CaseArm& arm : nodo.cases()) {
            // una variante con payload ('E.A(x)', tambien pelada: 'A(x)') o
            // una variante unidad de un enum SUMA ('E.Nada')
            std::string variante;
            const bool es_variante =
                opcional &&
                (arm.pattern().node_case() == pb::Expr::kCall ||
                 suma_de_miembro(arm.pattern(), variante) != nullptr);
            if (arm.binds() || es_variante) {
                fallo(option_message(module_.source_file(),
                                     arm.binds() ? "desenvuelve un 'T?' con 'case v'"
                                                 : "compara una variante con un sujeto 'E?'"),
                      arm.pattern().ln(), arm.pattern().col());
                return false;
            }
        }
        Reg sujeto = kNoReg;
        if (!expresion(nodo.subject(), sujeto, false)) return false;
        // el sujeto se DESREFERENCIA solo: un puntero a un objeto ya es el
        // objeto (su handle), pero uno a un escalar o a un enum sin payload
        // es una celda, y se compara lo que guarda (antes no coincidia nunca)
        bool flotante = es_flotante(nodo.subject());
        pb::Type apuntado;
        if (tipo_concreto_de(nodo.subject(), apuntado) && apuntado.kind() == pb::POINTER &&
            apuntado.has_inner() &&
            (es_escalar(apuntado.inner()) ||
             (apuntado.inner().kind() == pb::NOMINAL && es_enum_simple(apuntado.inner().name())))) {
            sujeto = leer_celda(sujeto, s.ln(), s.col());
            flotante = apuntado.inner().kind() == pb::FLOAT;
        }
        const std::uint32_t slot = slot_nuevo(flotante ? Type::F64 : Type::I64, "<sujeto>");
        Inst store;
        store.op = Op::StoreLocal;
        store.slot = slot;
        store.a = sujeto;
        store.line = s.ln();
        store.col = s.col();
        emitir(std::move(store));

        const BlockId despues = nuevo_bloque();
        for (const pb::CaseArm& arm : nodo.cases()) {
            // Un patron que DESESTRUCTURA no se evalua: sus argumentos son
            // nombres que se van a ligar, no valores que leer. Se compara la
            // etiqueta y el payload entra en slots de la rama.
            std::string item;
            const pb::EnumDecl* suma = nullptr;
            if (arm.pattern().node_case() == pb::Expr::kCall) {
                suma = suma_de_miembro(arm.pattern().call().callee(), item);
            } else {
                suma = suma_de_miembro(arm.pattern(), item);
            }

            Reg leido = nuevo_reg();
            Inst load;
            load.op = Op::LoadLocal;
            load.dst = leido;
            load.slot = slot;
            load.line = s.ln();
            load.col = s.col();
            emitir(std::move(load));

            Reg igual = kNoReg;
            if (suma != nullptr) {
                const int etiqueta = indice_de_variante(*suma, item);
                if (etiqueta < 0) {
                    fallo("'" + suma->name() + "' no declara la variante '" +
                              item + "'", arm.pattern().ln(),
                          arm.pattern().col());
                    return false;
                }
                Reg suya = nuevo_reg();
                Inst get;
                get.op = Op::GetField;
                get.dst = suya;
                get.a = leido;
                get.imm = 0;
                get.line = s.ln();
                get.col = s.col();
                emitir(std::move(get));
                Reg esperada = nuevo_reg();
                Inst cte;
                cte.op = Op::ConstI;
                cte.dst = esperada;
                cte.imm = etiqueta;
                cte.line = s.ln();
                cte.col = s.col();
                emitir(std::move(cte));
                igual = nuevo_reg();
                Inst cmp;
                cmp.op = Op::EqI;
                cmp.dst = igual;
                cmp.a = suya;
                cmp.b = esperada;
                cmp.line = s.ln();
                cmp.col = s.col();
                emitir(std::move(cmp));
            } else {
                Reg patron = kNoReg;
                if (!expresion(arm.pattern(), patron, false)) return false;
                igual = nuevo_reg();
                Inst cmp;
                cmp.op = es_flotante(nodo.subject()) ? Op::EqF : Op::EqI;
                cmp.dst = igual;
                cmp.a = leido;
                cmp.b = patron;
                cmp.line = s.ln();
                cmp.col = s.col();
                emitir(std::move(cmp));
            }

            const BlockId cuerpo = nuevo_bloque();
            const BlockId siguiente = nuevo_bloque();
            ramificar(igual, cuerpo, siguiente);
            actual_ = cuerpo;
            // el payload se liga DENTRO de la rama: fuera de ella el nombre
            // no existe, igual que en el interprete
            std::vector<Restauracion> tapados;
            if (suma != nullptr &&
                arm.pattern().node_case() == pb::Expr::kCall) {
                const pb::Call& patron = arm.pattern().call();
                // la variante del patron y la unidad que declara el enum: los
                // 'payload_type_ids' son indices del pool de ESA unidad
                const pb::EnumItem* variante_patron =
                    item_de_suma(*suma, patron.callee());
                const pb::Module* dueno = modulo_con_enum(suma);
                for (int i = 0; i < patron.args_size(); ++i) {
                    if (patron.args(i).node_case() !=
                        pb::Expr::kIdentifier) {
                        continue;
                    }
                    const std::string& nombre =
                        patron.args(i).identifier().name();
                    // lo que el binding TAPA vuelve al salir de la rama (antes
                    // un nombre de afuera quedaba apuntando al payload)
                    Restauracion r;
                    r.nombre = nombre;
                    const auto antes = nombres_.find(nombre);
                    r.habia = antes != nombres_.end();
                    if (r.habia) {
                        r.slot = antes->second;
                        r.tipo = tipos_.count(nombre) ? tipos_[nombre] : 0;
                    }
                    tapados.push_back(std::move(r));
                    // el TIPO del payload: da el ancho del slot (un float no
                    // cabe en uno entero) y deja escribirlo o leer sus campos
                    const pb::Type* tipo_payload = nullptr;
                    if (variante_patron != nullptr && dueno != nullptr &&
                        i < variante_patron->payload_type_ids_size()) {
                        const std::uint32_t pid = variante_patron->payload_type_ids(i);
                        if (pid < static_cast<std::uint32_t>(dueno->types_size())) {
                            tipo_payload = &dueno->types(static_cast<int>(pid));
                        }
                    }
                    Type forma = Type::I64;
                    std::uint32_t id_local = 0;
                    if (tipo_payload != nullptr) {
                        if (tipo_payload->kind() == pb::FLOAT) forma = Type::F64;
                        id_local = dueno == &module_
                            ? variante_patron->payload_type_ids(i)
                            : id_de_tipo(*tipo_payload);
                        escritos_[nombre] = tipo_payload;
                    }
                    const std::uint32_t destino = slot_nuevo(forma, nombre);
                    nombres_[nombre] = destino;
                    if (id_local != 0) tipos_[nombre] = id_local;
                    else tipos_.erase(nombre);
                    Reg campo = nuevo_reg();
                    Inst get;
                    get.op = Op::GetField;
                    get.dst = campo;
                    get.a = leido;
                    get.imm = i + 1;
                    get.line = s.ln();
                    get.col = s.col();
                    emitir(std::move(get));
                    Inst guarda;
                    guarda.op = Op::StoreLocal;
                    guarda.slot = destino;
                    guarda.a = campo;
                    guarda.line = s.ln();
                    guarda.col = s.col();
                    emitir(std::move(guarda));
                }
            }
            if (!sentencia(arm.body())) return false;
            // el payload ligado no existe fuera de su rama
            for (auto it = tapados.rbegin(); it != tapados.rend(); ++it) {
                escritos_.erase(it->nombre);
                if (it->habia) {
                    nombres_[it->nombre] = it->slot;
                    if (it->tipo != 0) tipos_[it->nombre] = it->tipo;
                    else tipos_.erase(it->nombre);
                } else {
                    nombres_.erase(it->nombre);
                    tipos_.erase(it->nombre);
                }
            }
            saltar(despues);
            actual_ = siguiente;
        }
        // Ningun caso encajo: se sale. No se inserta un 'default' — la
        // exhaustividad la comprueba la Semantica (SEM030), y ponerlo aqui
        // seria taparle el trabajo.
        saltar(despues);
        actual_ = despues;
        return true;
    }

    bool salto_de_bucle(const pb::Stmt& s) {
        if (bucles_.empty()) {
            // el frontend ya lo rechaza; aqui es defensa en profundidad,
            // porque sin bucle no hay bloque al que saltar.
            fallo("'break'/'continue' fuera de un bucle", s.ln(), s.col());
            return false;
        }
        const Bucle& b = bucles_.back();
        // salir del bucle destruye lo que nacio DENTRO de el
        if (!soltar_temporales_al_salir(b.temporales)) return false;
        if (!destruir_hasta(b.ambitos)) return false;
        saltar(s.node_case() == pb::Stmt::kBreakStmt ? b.salida : b.cabecera);
        // lo que siga en este bloque es inalcanzable: se abre uno nuevo para
        // que el codigo posterior tenga donde vivir sin colgar del grafo.
        actual_ = nuevo_bloque();
        return true;
    }

    // ------------------------------------------------------------------ //
    // expresiones
    // ------------------------------------------------------------------ //
    bool expresion(const pb::Expr& e, Reg& dst, bool descartar) {
        if (e.node_case() == pb::Expr::kLambdaExpr) {
            fallo(lambda_message(module_.source_file()), e.ln(), e.col());
            return false;
        }
        // una funcion NOMBRADA como valor ('aplica(doble, 2)') o una llamada a
        // traves de un valor no tienen un slot propio que lo delate
        if (reject_function_value(e.type_id(), e.ln(), e.col())) return false;
        if (e.node_case() == pb::Expr::kCall &&
            reject_function_value(e.call().callee().type_id(), e.ln(), e.col())) {
            return false;
        }
        switch (e.node_case()) {
            case pb::Expr::kLiteral:
                return literal(e, dst);
            case pb::Expr::kIdentifier:
                return identificador(e, dst);
            case pb::Expr::kCastExpr:
                return conversion(e, dst);
            case pb::Expr::kMember:
                return miembro(e, dst);
            case pb::Expr::kStructLiteral:
                if (!literal_struct(e, dst)) return false;
                if (e.struct_literal().has_temp_drop()) {
                    registrar_temporal(dst, e.struct_literal().temp_drop());
                } else if (e.struct_literal().temp_by_type()) {
                    registrar_temporal_por_tipo(dst);
                }
                return true;
            case pb::Expr::kInterp:
                return interpolada(e, dst);
            case pb::Expr::kSizeof:
                return tamano(e, dst);
            case pb::Expr::kBinary:
                return binaria(e, dst);
            case pb::Expr::kUnary:
                return unaria(e, dst);
            case pb::Expr::kAssignment:
                return asignacion(e, dst);
            case pb::Expr::kCall:
                return llamada(e, dst, descartar);
            case pb::Expr::kAddrOf:
                return direccion(e, dst);
            case pb::Expr::kIndex:
                return indexado(e, dst);
            case pb::Expr::kMoveExpr:
                // el ORDEN importa: se lee y luego se cede. Al reves la
                // bandera apagada no cambiaria nada, pero el dia que la
                // verificacion mire el flujo veria la lectura despues del
                // movimiento, que es justo lo que prohibe.
                if (!expresion(e.move_expr().operand(), dst, false)) {
                    return false;
                }
                return mover(e.move_expr().operand());
            default:
                fallo("la expresion '" + std::to_string(
                          static_cast<int>(e.node_case())) +
                      "' no se baja todavia al MIR", e.ln(), e.col());
                return false;
        }
    }

    bool literal(const pb::Expr& e, Reg& dst) {
        const pb::Literal& lit = e.literal();
        Inst inst;
        inst.line = e.ln();
        inst.col = e.col();
        if (lit.kind() == "int") {
            inst.op = Op::ConstI;
            inst.imm = lit.int_value();
        } else if (lit.kind() == "bool") {
            inst.op = Op::ConstI;
            inst.imm = lit.bool_value() ? 1 : 0;
        } else if (lit.kind() == "char") {
            // un 'char' es UN code point: su valor es ese entero. El HIR lo
            // trae en UTF-8, asi que 'ñ' son dos bytes y hay que decodificarlos;
            // tomar el primer byte daba 0xC3 en vez de 0xF1.
            inst.op = Op::ConstI;
            inst.imm = static_cast<std::int64_t>(primer_punto(lit.str_value()));
        } else if (lit.kind() == "float") {
            inst.op = Op::ConstF;
            inst.fimm = lit.float_value();
        } else if (lit.kind() == "str") {
            // una cadena constante es el INDICE de su constante: cabe en un
            // registro y se compara como un entero.
            inst.op = Op::ConstStr;
            inst.imm = interna(lit.str_value());
        } else if (lit.kind() == "null") {
            // 'null' solo existe para los 'T?' que son un handle (ver tipo_de):
            // -1 no es ningun handle ni ningun indice de constante.
            inst.op = Op::ConstI;
            inst.imm = -1;
        } else {
            fallo("el literal '" + lit.kind() + "' no baja al MIR todavia",
                  e.ln(), e.col());
            return false;
        }
        dst = nuevo_reg();
        inst.dst = dst;
        emitir(std::move(inst));
        return true;
    }

    // ¿Es de coma flotante? Se decide por el tipo ESTATICO que el HIR anota,
    // no por la forma del nodo: '1 + x' con x float es una suma de floats.
    bool es_flotante(const pb::Expr& e) const {
        const std::uint32_t id = e.type_id();
        if (id >= static_cast<std::uint32_t>(module_.types_size())) return false;
        return module_.types(static_cast<int>(id)).kind() == pb::FLOAT;
    }

    bool binaria(const pb::Expr& e, Reg& dst) {
        const pb::BinaryOp& nodo = e.binary();
        const std::string& op = nodo.op();

        // 'and'/'or' CORTOCIRCUITAN: no son una instruccion sino una rama, y
        // aqui se ve por que el CFG explicito paga. El resultado se acumula
        // en un local temporal porque el MIR no tiene phi.
        if (op == "and" || op == "or") return logica(e, dst);
        if (op == "??") {
            fallo(option_message(module_.source_file(),
                                 "desenvuelve un 'T?' con '?\?'"),
                  e.ln(), e.col());
            return false;
        }

        Reg izq = kNoReg;
        Reg der = kNoReg;
        if (!expresion(nodo.left(), izq, false)) return false;
        if (!expresion(nodo.right(), der, false)) return false;

        // 'a == b' con un 'T?' de un escalar: se comparan los VALORES de las
        // celdas (el escalar del otro lado se encaja, y la celda fresca muere
        // al terminar la expresion). Comparar handles diria "distintos" a dos
        // celdas con el mismo numero.
        if (op == "==" || op == "!=") {
            pb::Type ti;
            pb::Type td;
            const bool hay_i = tipo_concreto_de(nodo.left(), ti);
            const bool hay_d = tipo_concreto_de(nodo.right(), td);
            const bool caja_i = hay_i && es_caja(ti);
            if (caja_i || (hay_d && es_caja(td))) {
                const pb::Type caja = caja_i ? ti : td;
                encajar(caja, nodo.left(), izq);
                encajar(caja, nodo.right(), der);
                dst = nuevo_reg();
                Inst eq;
                eq.op = Op::EqCaja;
                eq.dst = dst;
                eq.a = izq;
                eq.b = der;
                eq.imm = caja.inner().kind() == pb::FLOAT ? 1 : 0;
                eq.line = e.ln();
                eq.col = e.col();
                emitir(std::move(eq));
                if (op == "!=") {
                    Reg no = nuevo_reg();
                    Inst neg;
                    neg.op = Op::Not;
                    neg.dst = no;
                    neg.a = dst;
                    neg.line = e.ln();
                    neg.col = e.col();
                    emitir(std::move(neg));
                    dst = no;
                }
                return true;
            }
        }

        // 'a == b' entre structs con '__eq__': lo decide el hook, como en el
        // interprete. Sin hook es identidad, que es la comparacion de
        // handles de abajo (cada copia es un objeto nuevo en los dos lados).
        if (op == "==" || op == "!=") {
            bool hecho = false;
            if (!igualdad_por_hook(e, izq, der, dst, hecho)) return false;
            if (hecho) return true;
        }

        // el ancho lo dan los OPERANDOS: en 'a < b' el resultado es bool
        // pero la instruccion depende de si a y b son enteros o flotantes.
        const bool flotante = es_flotante(nodo.left()) || es_flotante(nodo.right());
        // Una cadena no es un entero por mas que viaje como uno: '+' las pega
        // y '==' compara su texto. Con las instrucciones de entero saldrian
        // sumas e igualdades de INDICES, que es lo que hacia falta evitar.
        const bool cadena = como_texto(tipo_id_de(nodo.left())) == 4 &&
                            como_texto(tipo_id_de(nodo.right())) == 4;
        Op codigo;
        if (cadena && op == "+") codigo = Op::ConcatStr;
        else if (cadena && op == "==") codigo = Op::EqStr;
        else if (cadena && op == "!=") codigo = Op::NeStr;
        else if (cadena && op == "<") codigo = Op::LtStr;
        else if (cadena && op == "<=") codigo = Op::LeStr;
        else if (cadena && op == ">") codigo = Op::GtStr;
        else if (cadena && op == ">=") codigo = Op::GeStr;
        else if (cadena) {
            fallo("el operador '" + op + "' entre cadenas no baja al MIR",
                  e.ln(), e.col());
            return false;
        }
        else if (op == "+") codigo = flotante ? Op::AddF : Op::AddI;
        else if (op == "-") codigo = flotante ? Op::SubF : Op::SubI;
        else if (op == "*") codigo = flotante ? Op::MulF : Op::MulI;
        else if (op == "/") codigo = flotante ? Op::DivF : Op::DivI;
        else if (op == "%") codigo = flotante ? Op::RemF : Op::RemI;
        else if (op == "&") codigo = Op::AndI;
        else if (op == "|") codigo = Op::OrI;
        else if (op == "^") codigo = Op::XorI;
        else if (op == "<<") codigo = Op::ShlI;
        else if (op == ">>") codigo = Op::ShrI;
        else if (op == "==") codigo = flotante ? Op::EqF : Op::EqI;
        else if (op == "!=") codigo = flotante ? Op::NeF : Op::NeI;
        else if (op == "<") codigo = flotante ? Op::LtF : Op::LtI;
        else if (op == "<=") codigo = flotante ? Op::LeF : Op::LeI;
        else if (op == ">") codigo = flotante ? Op::GtF : Op::GtI;
        else if (op == ">=") codigo = flotante ? Op::GeF : Op::GeI;
        else {
            fallo("el operador '" + op + "' no baja al MIR todavia",
                  e.ln(), e.col());
            return false;
        }

        dst = nuevo_reg();
        Inst inst;
        inst.op = codigo;
        inst.dst = dst;
        inst.a = izq;
        inst.b = der;
        inst.line = e.ln();
        inst.col = e.col();
        emitir(std::move(inst));
        return true;
    }

    // 'a and b' -> "si a, vale b; si no, 0". El lado derecho SOLO se evalua
    // si hace falta, que es lo que significa cortocircuitar.
    bool logica(const pb::Expr& e, Reg& dst) {
        const pb::BinaryOp& nodo = e.binary();
        const bool es_and = nodo.op() == "and";

        // el resultado vive en un SLOT y no en un registro porque llega por
        // dos caminos distintos del grafo, y sin phi un registro solo puede
        // definirse en uno.
        const std::uint32_t slot = slot_nuevo(Type::I64, "<corto>");

        Reg izq = kNoReg;
        if (!expresion(nodo.left(), izq, false)) return false;

        const BlockId evaluar = nuevo_bloque();
        const BlockId corto = nuevo_bloque();
        const BlockId despues = nuevo_bloque();
        ramificar(izq, es_and ? evaluar : corto, es_and ? corto : evaluar);

        actual_ = evaluar;
        Reg der = kNoReg;
        const std::size_t marca = frescos_.size();
        if (!expresion(nodo.right(), der, false)) return false;
        soltar_frescos(marca);   // solo existen en este camino
        guardar(slot, der, e);
        saltar(despues);

        actual_ = corto;
        Reg constante = nuevo_reg();
        Inst cte;
        cte.op = Op::ConstI;
        cte.dst = constante;
        cte.imm = es_and ? 0 : 1;
        cte.line = e.ln();
        cte.col = e.col();
        emitir(std::move(cte));
        guardar(slot, constante, e);
        saltar(despues);

        actual_ = despues;
        dst = nuevo_reg();
        Inst load;
        load.op = Op::LoadLocal;
        load.dst = dst;
        load.slot = slot;
        load.line = e.ln();
        load.col = e.col();
        emitir(std::move(load));
        return true;
    }

    void guardar(std::uint32_t slot, Reg valor, const pb::Expr& e) {
        Inst store;
        store.op = Op::StoreLocal;
        store.slot = slot;
        store.a = valor;
        store.line = e.ln();
        store.col = e.col();
        emitir(std::move(store));
    }

    // valor & 0xFF: un 'byte' son los 8 bits de abajo
    Reg enmascarar_byte(Reg valor, const pb::Expr& e) {
        Reg mascara = constante_i(0xFF, e.ln(), e.col());
        Reg r = nuevo_reg();
        Inst y;
        y.op = Op::AndI;
        y.dst = r;
        y.a = valor;
        y.b = mascara;
        y.line = e.ln();
        y.col = e.col();
        emitir(std::move(y));
        return r;
    }

    bool unaria(const pb::Expr& e, Reg& dst) {
        const pb::UnaryOp& nodo = e.unary();
        Reg operando = kNoReg;
        if (!expresion(nodo.operand(), operando, false)) return false;
        Op codigo;
        if (nodo.op() == "not" || nodo.op() == "!") codigo = Op::Not;
        else if (nodo.op() == "~") codigo = Op::NotI;
        else if (nodo.op() == "-") {
            codigo = es_flotante(nodo.operand()) ? Op::NegF : Op::NegI;
        } else {
            fallo("el operador unario '" + nodo.op() + "' no baja al MIR",
                  e.ln(), e.col());
            return false;
        }
        dst = nuevo_reg();
        Inst inst;
        inst.op = codigo;
        inst.dst = dst;
        inst.a = operando;
        inst.line = e.ln();
        inst.col = e.col();
        emitir(std::move(inst));
        // '~' de un 'byte' no tiene signo: los 8 bits de abajo
        pb::Type tipo;
        if (codigo == Op::NotI && tipo_concreto_de(nodo.operand(), tipo) &&
            tipo.kind() == pb::BYTE) {
            dst = enmascarar_byte(dst, e);
        }
        return true;
    }

    bool asignacion(const pb::Expr& e, Reg& dst) {
        const pb::Assignment& nodo = e.assignment();

        // 'p.x = v': escritura de campo. El indice del campo lo da el struct
        // que declara el tipo del objeto, no el nombre — los nombres no
        // llegan al MIR.
        if (nodo.target().node_case() == pb::Expr::kMember) {
            Reg objeto = kNoReg;
            if (!expresion(nodo.target().member().obj(), objeto, false)) {
                return false;
            }
            int indice = 0;
            if (!campo_de(nodo.target(), indice)) return false;
            Reg valor = kNoReg;
            if (!expresion(nodo.value(), valor, false)) return false;
            copia_si_es_lugar(nodo.value(), valor);
            pb::Type destino;
            if (tipo_concreto_de(nodo.target(), destino)) encajar(destino, nodo.value(), valor);
            consumir(valor);
            if (es_campo_celda(nodo.target(), indice)) {
                // la celda del campo sigue: cambia lo que guarda
                Reg celda = nuevo_reg();
                Inst get;
                get.op = Op::GetField;
                get.dst = celda;
                get.a = objeto;
                get.imm = indice;
                get.line = e.ln();
                get.col = e.col();
                emitir(std::move(get));
                escribir_celda(celda, valor, e.ln(), e.col());
                dst = valor;
                return true;
            }
            if (es_valor_propio(nodo.target())) {
                // el objeto que habia en el campo era del struct: muere (por
                // su tipo, si el frontend lo pide: su '__free__' tambien)
                Reg viejo = nuevo_reg();
                Inst get;
                get.op = Op::GetField;
                get.dst = viejo;
                get.a = objeto;
                get.imm = indice;
                get.synthetic = true;
                emitir(std::move(get));
                if (nodo.drops_old()) emitir_destruir(viejo);
                else emitir_free(viejo);
            }
            Inst set;
            set.op = Op::SetField;
            set.a = objeto;
            set.b = valor;
            set.imm = indice;
            set.line = e.ln();
            set.col = e.col();
            emitir(std::move(set));
            dst = valor;
            return true;
        }

        if (nodo.target().node_case() == pb::Expr::kIndex) {
            return asignar_indice(e, dst);
        }

        if (nodo.target().node_case() != pb::Expr::kIdentifier) {
            fallo("asignar a algo que no es una variable ni un campo no baja "
                  "al MIR", e.ln(), e.col());
            return false;
        }
        const std::string& nombre = nodo.target().identifier().name();
        Reg valor = kNoReg;
        const auto slot = nombres_.find(nombre);
        pb::Type destino;
        const bool con_destino = tipo_concreto_de(e, destino);
        if (slot != nombres_.end()) {
            if (!expresion(nodo.value(), valor, false)) return false;
            copia_si_es_lugar(nodo.value(), valor);
            if (con_destino) encajar(destino, nodo.value(), valor);
            consumir(valor);
            if (es_celda(slot->second)) {
                // la celda sigue: cambia lo que guarda
                Reg celda = cargar_slot(slot->second, e.ln(), e.col());
                escribir_celda(celda, valor, e.ln(), e.col());
                dst = valor;
                return true;
            }
            liberar_si_vivo(slot->second, nodo.drops_old());   // el valor viejo muere
            guardar(slot->second, valor, e);
            // ...y el local vuelve a ser dueño de algo (tambien despues de un
            // 'move': antes la bandera quedaba apagada y su destructor ya no
            // corria)
            const auto bandera = banderas_.find(slot->second);
            if (bandera != banderas_.end()) encender_bandera(bandera->second);
            dst = valor;
            return true;
        }
        const int g = global(nombre);
        if (g < 0) {
            fallo("'" + nombre + "' no esta en alcance", e.ln(), e.col());
            return false;
        }
        if (!expresion(nodo.value(), valor, false)) return false;
        copia_si_es_lugar(nodo.value(), valor);
        if (con_destino) encajar(destino, nodo.value(), valor);
        consumir(valor);
        if (global_en_celda(g)) {
            Reg celda = nuevo_reg();
            Inst load;
            load.op = Op::LoadGlobal;
            load.dst = celda;
            load.slot = static_cast<std::uint32_t>(g);
            load.line = e.ln();
            load.col = e.col();
            emitir(std::move(load));
            escribir_celda(celda, valor, e.ln(), e.col());
            dst = valor;
            return true;
        }
        if (es_valor_propio(nodo.target())) {
            Reg viejo = nuevo_reg();
            Inst load;
            load.op = Op::LoadGlobal;
            load.dst = viejo;
            load.slot = static_cast<std::uint32_t>(g);
            load.synthetic = true;
            emitir(std::move(load));
            if (nodo.drops_old()) emitir_destruir(viejo);
            else emitir_free(viejo);
        }
        Inst store;
        store.op = Op::StoreGlobal;
        store.slot = static_cast<std::uint32_t>(g);
        store.a = valor;
        store.line = e.ln();
        store.col = e.col();
        emitir(std::move(store));
        dst = valor;
        return true;
    }

    // ------------------------------------------------------------------ //
    // nombres, conversiones y agregados
    // ------------------------------------------------------------------ //
    bool identificador(const pb::Expr& e, Reg& dst) {
        const std::string& nombre = e.identifier().name();
        const auto slot = nombres_.find(nombre);
        if (slot != nombres_.end()) {
            dst = nuevo_reg();
            Inst load;
            load.op = Op::LoadLocal;
            load.dst = dst;
            load.slot = slot->second;
            load.line = e.ln();
            load.col = e.col();
            emitir(std::move(load));
            if (es_celda(slot->second)) dst = leer_celda(dst, e.ln(), e.col());
            return true;
        }
        const int g = global(nombre);
        if (g >= 0) {
            dst = nuevo_reg();
            Inst load;
            load.op = Op::LoadGlobal;
            load.dst = dst;
            load.slot = static_cast<std::uint32_t>(g);
            load.line = e.ln();
            load.col = e.col();
            emitir(std::move(load));
            if (global_en_celda(g)) dst = leer_celda(dst, e.ln(), e.col());
            return true;
        }
        // Un item de enum PELADO ('ROJO') es una constante: el enum sin
        // payload es un entero con nombre.
        std::int64_t valor = 0;
        if (item_de_enum(nombre, valor)) {
            dst = nuevo_reg();
            Inst cte;
            cte.op = Op::ConstI;
            cte.dst = dst;
            cte.imm = valor;
            cte.line = e.ln();
            cte.col = e.col();
            emitir(std::move(cte));
            return true;
        }
        fallo("'" + nombre + "' no esta en alcance", e.ln(), e.col());
        return false;
    }

    // 'cast<T>(x)' entre numericos: en una maquina no es la misma operacion
    // en los dos sentidos, asi que el par viaja en la instruccion.
    bool conversion(const pb::Expr& e, Reg& dst) {
        const pb::CastExpr& nodo = e.cast_expr();
        Type destino = Type::I64;
        if (nodo.has_type() && nodo.type().kind() == pb::STR) {
            // 'cast<str>(x)': la misma escritura que un f-string ('{x}'),
            // con la misma instruccion. Una cadena ya es una cadena.
            Reg valor = kNoReg;
            if (!expresion(nodo.value(), valor, false)) return false;
            const int modo = como_texto_de(nodo.value());
            if (modo < 0) {
                fallo("un 'cast<str>' desde ese tipo no baja al MIR todavia",
                      e.ln(), e.col());
                return false;
            }
            if (modo == 4) {
                dst = valor;
                return true;
            }
            dst = nuevo_reg();
            Inst texto;
            texto.op = Op::ToStr;
            texto.dst = dst;
            texto.a = valor;
            texto.imm = modo;
            texto.line = e.ln();
            texto.col = e.col();
            emitir(std::move(texto));
            return true;
        }
        // Con un tipo NOMINAL de algun lado, manda la TABLA de conversiones
        // de la imagen: el par (origen estatico, destino), igual que en el
        // interprete. Antes el MIR dejaba pasar el valor intacto y
        // 'cast<dt.int8>(300)' daba 300 en vez de 44, sin avisar.
        if (nodo.has_type()) {
            const std::uint32_t origen = tipo_id_de(nodo.value());
            // un enum SIN payload ya es un entero: 'cast<int>(e)' no pasa
            // por ninguna tabla
            const bool origen_nominal =
                origen < static_cast<std::uint32_t>(module_.types_size()) &&
                module_.types(static_cast<int>(origen)).kind() == pb::NOMINAL &&
                !es_enum_simple(module_.types(static_cast<int>(origen)).name());
            if (nodo.type().kind() == pb::NOMINAL || origen_nominal) {
                return conversion_por_tabla(e, dst);
            }
        }
        if (nodo.has_type()) {
            switch (nodo.type().kind()) {
                case pb::FLOAT: destino = Type::F64; break;
                case pb::INT: case pb::CHAR: case pb::BOOL: case pb::BYTE:
                    destino = Type::I64; break;
                default:
                    fallo("un 'cast' hacia ese tipo no baja al MIR todavia",
                          e.ln(), e.col());
                    return false;
            }
        }
        Reg valor = kNoReg;
        if (!expresion(nodo.value(), valor, false)) return false;
        const bool origen_flotante = es_flotante(nodo.value());
        if (nodo.has_type() && nodo.type().kind() == pb::BYTE) {
            // hacia 'byte': los 8 bits de abajo (modulo 256), como el
            // interprete. De un 'byte' ya estan en rango y no cuesta nada.
            pb::Type origen;
            if (tipo_concreto_de(nodo.value(), origen) && origen.kind() == pb::BYTE) {
                dst = valor;
                return true;
            }
            dst = enmascarar_byte(valor, e);
            return true;
        }
        if ((destino == Type::F64) == origen_flotante) {
            dst = valor;   // mismo ancho: no hay nada que convertir
            return true;
        }
        dst = nuevo_reg();
        Inst inst;
        inst.op = destino == Type::F64 ? Op::IntToFloat : Op::FloatToInt;
        inst.dst = dst;
        inst.a = valor;
        inst.line = e.ln();
        inst.col = e.col();
        emitir(std::move(inst));
        return true;
    }

    // 'hecho' = true si el '==' / '!=' lo resolvio un '__eq__'.
    bool igualdad_por_hook(const pb::Expr& e, Reg izq, Reg der, Reg& dst,
                           bool& hecho) {
        const pb::BinaryOp& nodo = e.binary();
        // el tipo CONCRETO: en una instancia de un generico, 'x == y' con
        // 'T' = un struct con '__eq__' es ese '__eq__' (antes se comparaban
        // los handles y dos claves iguales daban distinto). Tambien de una
        // celda ('self.keys[i] == k'), que el HIR no anota.
        pb::Type tipo;
        if (!tipo_concreto_de(nodo.left(), tipo)) return true;
        if (tipo.kind() != pb::NOMINAL || es_enum_simple(tipo.name())) return true;
        pb::HookRef ref;
        ref.set_owner_type(tipo.name());
        ref.set_kind(pb::EQ);
        if (image_.hook(ref) == nullptr) return true;
        int destino = -1;
        if (!funcion_del_hook(ref, destino)) {
            fallo("el '__eq__' de '" + tipo.name() + "' no esta ligado a ninguna "
                  "funcion de la imagen", e.ln(), e.col());
            return false;
        }
        destino = instancia_de_hook(destino, tipo);
        Reg igual = nuevo_reg();
        Inst llamar;
        llamar.op = Op::Call;
        llamar.dst = igual;
        llamar.func = static_cast<std::uint32_t>(destino);
        llamar.args = {izq, der};
        llamar.line = e.ln();
        llamar.col = e.col();
        emitir(std::move(llamar));
        dst = igual;
        if (nodo.op() == "!=") {
            dst = nuevo_reg();
            Inst no;
            no.op = Op::Not;
            no.dst = dst;
            no.a = igual;
            no.line = e.ln();
            no.col = e.col();
            emitir(std::move(no));
        }
        hecho = true;
        return true;
    }

    // 'cast<T>(x)' con un nominal en el par. En orden:
    //   1) un ENUM sin payload como destino: el valor ya ES el entero;
    //   2) el '__cast__' que la imagen registra para (origen, destino): si
    //      tiene cuerpo, una llamada; si es PROTOTIPO, lo pone la maquina
    //      (ancho fijo) o no hace nada (vuelta a un primitivo, que ya cabe);
    //   3) si no hay ninguno, falla con su nombre: el frontend no deberia
    //      dejarlo pasar, y un valor sin convertir seria otro programa.
    bool conversion_por_tabla(const pb::Expr& e, Reg& dst) {
        const pb::CastExpr& nodo = e.cast_expr();
        const pb::Type& hacia = nodo.type();
        if (hacia.kind() == pb::NOMINAL && es_enum_simple(hacia.name())) {
            return expresion(nodo.value(), dst, false);
        }
        const std::uint32_t origen = tipo_id_de(nodo.value());
        if (origen >= static_cast<std::uint32_t>(module_.types_size())) {
            fallo("el origen de este 'cast' no tiene tipo en el HIR", e.ln(), e.col());
            return false;
        }
        const std::string desde = hir::type_key(module_.types(static_cast<int>(origen)));
        const pb::Symbol* simbolo = image_.cast(desde, hir::type_key(hacia));
        if (simbolo == nullptr) {
            fallo("no hay un '__cast__' registrado de " + notacion(origen) +
                  " a '" + hir::format_type(hacia) + "'", e.ln(), e.col());
            return false;
        }
        const int funcion = funcion_del_cast(*simbolo);
        if (funcion < 0) {
            fallo("el '__cast__' de este 'cast' (" + simbolo->name() + " @" +
                  std::to_string(simbolo->ln()) + ") no esta entre las "
                  "funciones de la imagen", e.ln(), e.col());
            return false;
        }
        Reg valor = kNoReg;
        if (!expresion(nodo.value(), valor, false)) return false;
        if (!resolved_.functions[static_cast<std::size_t>(funcion)].prototype) {
            dst = nuevo_reg();
            Inst llamar;
            llamar.op = Op::Call;
            llamar.dst = dst;
            llamar.func = static_cast<std::uint32_t>(funcion);
            llamar.args.push_back(valor);
            llamar.line = e.ln();
            llamar.col = e.col();
            emitir(std::move(llamar));
            return true;
        }
        if (hacia.kind() != pb::NOMINAL) {
            dst = valor;   // vuelta al primitivo: el valor ya cabe
            return true;
        }
        // el nombre SIMPLE: el host aporta "un entero de 8 bits", no "el
        // int8 de tal libreria" (misma regla que 'intrinsics.lookup_cast')
        const std::string& completo = hacia.name();
        const std::size_t punto = completo.rfind('.');
        const std::string simple =
            punto == std::string::npos ? completo : completo.substr(punto + 1);
        Op op = Op::NarrowI;
        std::int64_t bits = 0;
        if (simple == "int8") bits = 8;
        else if (simple == "int16") bits = 16;
        else if (simple == "int32") bits = 32;
        else if (simple == "float16") { op = Op::NarrowF; bits = 16; }
        else if (simple == "float32") { op = Op::NarrowF; bits = 32; }
        else if (simple == "float64") {
            dst = valor;   // ya es un binary64
            return true;
        } else {
            fallo("el host no trae la conversion nativa a '" + completo + "'",
                  e.ln(), e.col());
            return false;
        }
        dst = nuevo_reg();
        Inst angosta;
        angosta.op = op;
        angosta.dst = dst;
        angosta.a = valor;
        angosta.imm = bits;
        angosta.line = e.ln();
        angosta.col = e.col();
        emitir(std::move(angosta));
        return true;
    }

    // ¿'nombre' es un enum SIN payload de esta unidad? Lo dice la tabla de
    // simbolos que viaja en el HIR, igual que en el interprete.
    bool es_enum_simple(const std::string& nombre) const {
        const auto& tipos = module_.symbols().types();
        if (!tipos.contains(nombre)) return false;
        if (tipos.at(nombre).kind() != pb::ENUM) return false;
        for (const pb::Decl& d : module_.items()) {
            if (d.node_case() != pb::Decl::kEnumDecl) continue;
            if (d.enum_decl().name() != nombre) continue;
            for (const pb::EnumItem& it : d.enum_decl().items()) {
                if (it.payload_type_ids_size() > 0) return false;
            }
            return true;
        }
        return true;
    }

    // La funcion de la imagen que implementa ese '__cast__'. Los overloads
    // comparten nombre, asi que se distinguen por la FIRMA (origen, destino),
    // leida en el pool de la unidad que declara cada uno. No sirve buscar la
    // unidad duena del simbolo: un paquete que re-exporta ('d_types') lleva
    // COPIAS de los simbolos de su submodulo, y la tabla de la imagen puede
    // apuntar a la copia.
    int funcion_del_cast(const pb::Symbol& simbolo) const {
        if (simbolo.param_types_size() == 0) return -1;
        const std::string desde = hir::type_key(simbolo.param_types(0));
        const std::string hacia = hir::type_key(simbolo.type());
        for (std::size_t i = 0; i < resolved_.functions.size(); ++i) {
            const hir::Function& f = resolved_.functions[i];
            if (f.name != simbolo.name() || f.decl == nullptr) continue;
            if (f.decl->params_size() == 0) continue;
            const hir::Unit* suya = unidad_de(f.unit);
            if (suya == nullptr) continue;
            const pb::Module& m = suya->module();
            const std::uint32_t p0 = f.decl->params(0).type_id();
            const std::uint32_t r = f.decl->return_type_id();
            if (p0 >= static_cast<std::uint32_t>(m.types_size()) ||
                r >= static_cast<std::uint32_t>(m.types_size())) {
                continue;
            }
            if (hir::type_key(m.types(static_cast<int>(p0))) == desde &&
                hir::type_key(m.types(static_cast<int>(r))) == hacia) {
                return static_cast<int>(i);
            }
        }
        return -1;
    }

    // El tipo escrito como se lee, para un diagnostico. Un mensaje que solo
    // diga "un tipo que no represento" no le sirve a quien tiene que decidir
    // si eso importa.
    // VM001: ¿el tipo 'type_id' del pool de esta unidad es, o contiene, un
    // tipo funcion ('fn(A) -> R', tambien dentro de un '?' o de los
    // argumentos de un generico)? Entonces se rechaza con su posicion: las
    // funciones como valores solo las ejecuta el interprete. Se mira AQUI, al
    // bajar cada funcion, y no al cargar la imagen: una libreria puede
    // declarar 'sort_by(fn(T ptr, T ptr) -> int cmp)' y un programa que no la
    // usa tiene que seguir corriendo en la VM.
    bool reject_function_value(std::uint32_t type_id, std::uint32_t ln,
                               std::uint32_t col) {
        const pb::Type* found = function_type_of(type_id);
        if (found == nullptr) return false;
        fallo(hir::function_values_message(module_.source_file(), *found), ln, col);
        return true;
    }

    // El primer tipo funcion dentro del tipo 'type_id' del pool, o nullptr.
    const pb::Type* function_type_of(std::uint32_t type_id) const {
        if (type_id == 0 || type_id >= static_cast<std::uint32_t>(module_.types_size())) {
            return nullptr;
        }
        return hir::find_function_type(module_.types(static_cast<int>(type_id)));
    }

    // El cuerpo de una funcion de LIBRERIA que recibe o devuelve un valor
    // funcion: los mismos parametros (para que la llamada cuadre) y una
    // sola instruccion que falla con VM001 en su posicion. Explicito al
    // EJECUTARLA, nunca otro comportamiento; y si nadie la llama, no cuesta
    // nada.
    void trap_function_value(const pb::FunctionDecl& decl,
                             const std::vector<hir::Slot>& slots,
                             const pb::Type& found, std::uint32_t ln, std::uint32_t col) {
        for (const hir::Slot& slot : slots) {
            if (!slot.parameter) continue;
            Type tipo = Type::I64;  // un valor funcion nunca llega: basta el ancho
            tipo_de(module_, slot.type_id, tipo);
            fn_.slots.push_back(tipo);
            fn_.slot_names.push_back(slot.name);
            fn_.params++;
        }
        if (!tipo_de(module_, decl.return_type_id(), fn_.result)) fn_.result = Type::I64;
        actual_ = nuevo_bloque();
        Inst fallar;
        fallar.op = Op::Fallar;
        fallar.imm = interna(hir::function_values_message(module_.source_file(), found));
        fallar.line = ln;
        fallar.col = col;
        emitir(std::move(fallar));
        fn_.blocks[actual_].term = Term::Return;
        fn_.blocks[actual_].has_value = false;
    }

    std::string notacion(std::uint32_t id) const {
        if (id >= static_cast<std::uint32_t>(module_.types_size())) {
            return "desconocido";
        }
        // 'format_type' y no 'type_key': la clave estructural sirve para
        // indexar hooks, no para leerla un humano.
        return "'" + hir::format_type(module_.types(static_cast<int>(id))) +
               "'";
    }

    // Por que ese tipo no baja, cuando hay algo que explicar.
    std::string porque(std::uint32_t id) const {
        if (id >= static_cast<std::uint32_t>(module_.types_size())) return "";
        if (module_.types(static_cast<int>(id)).kind() != pb::NULLABLE) {
            return "";
        }
        return ": un escalar que puede ser nulo tiene que vivir en el monton "
               "para que el nulo se distinga de un valor cualquiera, y eso es "
               "lo mismo que le falta a '&' sobre un escalar";
    }

    // El tipo de una expresion.
    //
    // Un IDENTIFICADOR no lleva 'type_id' en el HIR (el emisor solo anota las
    // expresiones DERIVADAS), asi que su tipo es el que se declaro al abrir
    // el slot o la global. Sin esto 'p.x' no sabia sobre que struct estaba.
    // El 'type_id' de un tipo ESCRITO (el de una rama 'catch'), buscandolo
    // por su clave en el pool de la unidad; 0 si el pool no lo tiene.
    std::uint32_t id_de_tipo(const pb::Type& tipo) const {
        const std::string clave = hir::type_key(tipo);
        for (int i = 1; i < module_.types_size(); ++i) {
            if (hir::type_key(module_.types(i)) == clave) {
                return static_cast<std::uint32_t>(i);
            }
        }
        return 0;
    }

    std::uint32_t tipo_id_de(const pb::Expr& e) const {
        if (e.node_case() != pb::Expr::kIdentifier) return e.type_id();
        const auto conocido = tipos_.find(e.identifier().name());
        if (conocido != tipos_.end()) return conocido->second;
        return tipo_id_global(e.identifier().name());
    }

    // El tipo declarado de una global: se busca en las sentencias de nivel de
    // modulo de la imagen entera, porque una global puede venir de otra unidad.
    std::uint32_t tipo_id_global(const std::string& nombre) const {
        std::vector<const pb::Module*> modulos{&module_};
        for (const std::unique_ptr<hir::Unit>& u : image_.units()) {
            modulos.push_back(&u->module());
        }
        modulos.push_back(&image_.main().module());
        for (const pb::Module* m : modulos) {
            for (const pb::Decl& decl : m->items()) {
                if (decl.node_case() != pb::Decl::kStatement) continue;
                const pb::Stmt& stmt = decl.statement();
                if (stmt.node_case() != pb::Stmt::kVarDecl) continue;
                if (stmt.var_decl().name() == nombre) {
                    // el id es del pool de SU unidad: se traduce al propio
                    const std::uint32_t id = stmt.var_decl().type_id();
                    if (m == &module_) return id;
                    if (id >= static_cast<std::uint32_t>(m->types_size())) return 0;
                    return id_de_tipo(m->types(static_cast<int>(id)));
                }
            }
        }
        return 0;
    }

    // El tipo con NOMBRE al que se llega desde 'id', atravesando los punteros
    // que haya por medio. 'nullptr' si no se llega a ninguno.
    const pb::Type* nominal_de(std::uint32_t id) const {
        return nominal_de(module_, id);
    }

    static const pb::Type* nominal_de(const pb::Module& modulo, std::uint32_t id) {
        if (id >= static_cast<std::uint32_t>(modulo.types_size())) {
            return nullptr;
        }
        const pb::Type* tipo = &modulo.types(static_cast<int>(id));
        for (int i = 0; i < 8 && tipo != nullptr &&
                        (tipo->kind() == pb::POINTER ||
                         tipo->kind() == pb::NULLABLE); ++i) {
            tipo = tipo->has_inner() ? &tipo->inner() : nullptr;
        }
        if (tipo == nullptr || tipo->kind() != pb::NOMINAL) return nullptr;
        return tipo;
    }

    // La variante que nombra el callee de un patron ('Fig.Circulo' o
    // 'fig.Figura.Circulo'): por el ultimo tramo.
    static const pb::EnumItem* item_de_suma(const pb::EnumDecl& en,
                                            const pb::Expr& callee) {
        std::string nombre;
        if (callee.node_case() == pb::Expr::kMember) nombre = callee.member().member();
        else if (callee.node_case() == pb::Expr::kIdentifier) nombre = callee.identifier().name();
        for (const pb::EnumItem& it : en.items()) {
            if (it.name() == nombre) return &it;
        }
        return nullptr;
    }

    // La unidad cuyo modulo declara 'en' (por su direccion), o nullptr.
    const pb::Module* modulo_con_enum(const pb::EnumDecl* en) const {
        const auto contiene = [en](const pb::Module& m) {
            for (const pb::Decl& d : m.items()) {
                if (d.node_case() == pb::Decl::kEnumDecl && &d.enum_decl() == en) return true;
            }
            return false;
        };
        if (contiene(module_)) return &module_;
        for (const std::unique_ptr<hir::Unit>& u : image_.units()) {
            if (contiene(u->module())) return &u->module();
        }
        if (contiene(image_.main().module())) return &image_.main().module();
        return nullptr;
    }

    // El codigo de 'ToStr' de una expresion: por su 'type_id' y, si el pool
    // de la unidad no lo tiene, por el tipo ESCRITO del binding.
    int como_texto_de(const pb::Expr& e) const {
        const int modo = como_texto(tipo_id_de(e));
        if (modo >= 0) return modo;
        if (e.node_case() == pb::Expr::kIndex) {
            // 'p[i]' de un 'T ptr' es un T, y 's[i]' de una cadena es un char:
            // se deduce del objeto cuando el HIR no anota el elemento.
            const std::uint32_t id = tipo_id_de(e.index().obj());
            if (id >= static_cast<std::uint32_t>(module_.types_size())) return -1;
            const pb::Type& obj = module_.types(static_cast<int>(id));
            if (obj.kind() == pb::STR) return 3;
            if (obj.kind() == pb::POINTER && obj.has_inner()) {
                return como_texto(obj.inner());
            }
            return -1;
        }
        if (e.node_case() != pb::Expr::kIdentifier) return modo;
        const auto it = escritos_.find(e.identifier().name());
        if (it == escritos_.end()) return -1;
        switch (it->second->kind()) {
            case pb::INT: case pb::BYTE: return 0;
            case pb::FLOAT: return 1;
            case pb::BOOL: return 2;
            case pb::CHAR: return 3;
            case pb::STR: return 4;
            default: return -1;
        }
    }

    // --- SEMANTICA DE VALOR -------------------------------------------- //
    // Un struct es un VALOR: guardarlo en otro dueno (ligar, asignar, pasar
    // por valor, meterlo en un campo) lo COPIA, y la copia es profunda en sus
    // objetos propios. Es la regla del interprete ('copy_on_bind'). Solo se
    // copia lo que sale de un LUGAR —una variable, un campo, una celda—: un
    // valor recien hecho ('C{...}', 'f()', 'move x') ya no es de nadie y se
    // entrega tal cual.

    // El tipo concreto de un tipo del pool de esta unidad (con la
    // sustitucion de la instancia, si la hay).
    pb::Type concreto(const pb::Type& t) const {
        return sustitucion_ == nullptr ? t : sustituir(t, *sustitucion_);
    }

    // El tipo concreto de una expresion, o false si no se sabe.
    //
    // El HIR no anota el tipo del DESTINO de una asignacion ('e.dentro = c'):
    // entonces se deduce de lo que lo contiene —el campo de su struct, la
    // celda de su puntero—, que es lo que hace falta para liberar lo que
    // habia ahi.
    bool tipo_concreto_de(const pb::Expr& e, pb::Type& out) const {
        const std::uint32_t id = tipo_id_de(e);
        if (id != 0 && id < static_cast<std::uint32_t>(module_.types_size())) {
            out = concreto(module_.types(static_cast<int>(id)));
            return true;
        }
        if (e.node_case() == pb::Expr::kIndex) {
            pb::Type base;
            if (!tipo_concreto_de(e.index().obj(), base)) return false;
            if (base.kind() != pb::POINTER || !base.has_inner()) return false;
            out = base.inner();
            return true;
        }
        if (e.node_case() == pb::Expr::kMember) {
            pb::Type base;
            if (!tipo_concreto_de(e.member().obj(), base)) return false;
            while ((base.kind() == pb::POINTER || base.kind() == pb::NULLABLE) &&
                   base.has_inner()) {
                pb::Type dentro = base.inner();
                base = std::move(dentro);
            }
            if (base.kind() != pb::NOMINAL) return false;
            const Formas::Declaracion d = formas_.declaracion(base.name());
            if (d.estructura == nullptr) return false;
            Sustitucion s;
            for (int i = 0; i < d.estructura->type_params_size() && i < base.args_size(); ++i) {
                s.emplace(d.estructura->type_params(i), base.args(i));
            }
            for (const pb::Field& f : d.estructura->fields()) {
                if (f.name() != e.member().member()) continue;
                const pb::Type* t = Formas::tipo_en(*d.modulo, f.type_id());
                if (t == nullptr) return false;
                out = sustituir(*t, s);
                return true;
            }
        }
        return false;
    }

    // El tipo concreto del campo 'orden' del struct que construye 'e'.
    bool tipo_de_campo(const pb::Expr& e, int orden, pb::Type& out) const {
        pb::Type t;
        if (!tipo_concreto_de(e, t) || t.kind() != pb::NOMINAL) return false;
        const Formas::Declaracion d = formas_.declaracion(t.name());
        if (d.estructura == nullptr || orden < 0 || orden >= d.estructura->fields_size()) {
            return false;
        }
        const pb::Type* campo = Formas::tipo_en(*d.modulo, d.estructura->fields(orden).type_id());
        if (campo == nullptr) return false;
        Sustitucion s;
        for (int i = 0; i < d.estructura->type_params_size() && i < t.args_size(); ++i) {
            s.emplace(d.estructura->type_params(i), t.args(i));
        }
        out = sustituir(*campo, s);
        return true;
    }

    // El tipo concreto del campo 'k' del payload de la variante 'item' del
    // enum que construye 'e'.
    bool tipo_de_payload(const pb::Expr& e, const std::string& item, int k,
                         pb::Type& out) const {
        pb::Type t;
        if (!tipo_concreto_de(e, t) || t.kind() != pb::NOMINAL) return false;
        const Formas::Declaracion d = formas_.declaracion(t.name());
        if (d.enumeracion == nullptr) return false;
        for (const pb::EnumItem& it : d.enumeracion->items()) {
            if (it.name() != item || k >= it.payload_type_ids_size()) continue;
            const pb::Type* p = Formas::tipo_en(*d.modulo, it.payload_type_ids(k));
            if (p == nullptr) return false;
            out = *p;
            return true;
        }
        return false;
    }

    // El tipo concreto del parametro 'i' de la funcion que llama 'inst' (con
    // la sustitucion de su instancia, si es una).
    bool tipo_del_parametro(const Inst& inst, std::size_t i, pb::Type& out) const {
        if (inst.op != Op::Call || inst.func < 0) return false;
        const auto indice = static_cast<std::size_t>(inst.func);
        const std::size_t base = instancias_.base_de(indice);
        if (base >= resolved_.functions.size()) return false;
        const hir::Function& f = resolved_.functions[base];
        if (f.decl == nullptr || static_cast<int>(i) >= f.decl->params_size()) return false;
        const hir::Unit* suya = unidad_de(f.unit);
        if (suya == nullptr) return false;
        const pb::Type* t = Formas::tipo_en(suya->module(),
                                            f.decl->params(static_cast<int>(i)).type_id());
        if (t == nullptr) return false;
        const Sustitucion* s = instancias_.sustitucion_de(indice);
        out = s == nullptr ? *t : sustituir(*t, *s);
        return true;
    }

    static bool es_lugar(const pb::Expr& e) {
        return e.node_case() == pb::Expr::kIdentifier ||
               e.node_case() == pb::Expr::kMember ||
               e.node_case() == pb::Expr::kIndex;
    }

    // Si 'e' es un lugar de un tipo con objeto propio, 'r' pasa a ser una
    // copia nueva de lo que habia ahi.
    void copia_si_es_lugar(const pb::Expr& e, Reg& r) {
        if (!es_lugar(e)) return;
        // 'Orden.Seguir' tiene forma de campo pero construye un valor NUEVO:
        // lo recien hecho no es un lugar, se entrega tal cual
        if (std::find(frescos_.begin(), frescos_.end(), r) != frescos_.end()) return;
        pb::Type t;
        if (!tipo_concreto_de(e, t) || !formas_.propio(t)) return;
        Reg copia = nuevo_reg();
        Inst inst;
        inst.op = Op::Copy;
        inst.dst = copia;
        inst.a = r;
        inst.line = e.ln();
        inst.col = e.col();
        emitir(std::move(inst));
        r = copia;
        fresco(copia);   // la copia no es de nadie hasta que alguien la consume
    }

    // La forma de los objetos del tipo de 'e' (-1 si no son objetos).
    std::int32_t forma_de(const pb::Expr& e) {
        pb::Type t;
        if (!tipo_concreto_de(e, t)) return -1;
        return formas_.forma(t);
    }

    // 'move c.dentro' (y el 'throw c.dentro' que el frontend convierte en
    // eso): el CAMPO cede su valor, no la variable entera. Se marca el campo
    // con -1 ("sin valor": ningun handle vale -1) y su destruccion lo salta.
    // Sin esto, al destruir 'c' se destruia tambien lo que ya se habia
    // cedido, antes de que el nuevo dueño lo usara.
    bool mover_campo(const pb::Expr& objetivo) {
        std::vector<std::string> tramos;
        if (!ruta_de(objetivo, tramos) || tramos.size() < 2) return true;
        if (nombres_.count(tramos[0]) == 0) return true;   // solo de un local
        Reg objeto = kNoReg;
        if (!expresion(objetivo.member().obj(), objeto, false)) return false;
        int indice = 0;
        if (!campo_de(objetivo, indice)) return false;
        Reg vacio = nuevo_reg();
        Inst menos_uno;
        menos_uno.op = Op::ConstI;
        menos_uno.dst = vacio;
        menos_uno.imm = -1;
        menos_uno.synthetic = true;
        emitir(std::move(menos_uno));
        Inst set;
        set.op = Op::SetField;
        set.a = objeto;
        set.b = vacio;
        set.imm = indice;
        set.synthetic = true;
        emitir(std::move(set));
        return true;
    }

    // El nominal del tipo ESCRITO de un binding de 'catch' (atravesando
    // punteros y nullables), o nullptr.
    const pb::Type* nominal_escrito(const pb::Expr& e) const {
        if (e.node_case() != pb::Expr::kIdentifier) return nullptr;
        const auto it = escritos_.find(e.identifier().name());
        if (it == escritos_.end()) return nullptr;
        const pb::Type* t = it->second;
        for (int i = 0; i < 8 && t != nullptr &&
                        (t->kind() == pb::POINTER || t->kind() == pb::NULLABLE); ++i) {
            t = t->has_inner() ? &t->inner() : nullptr;
        }
        return t != nullptr && t->kind() == pb::NOMINAL ? t : nullptr;
    }

    // El indice del campo que nombra un 'MemberAccess', segun el struct que
    // declara el tipo del objeto.
    bool campo_de(const pb::Expr& acceso, int& indice) {
        const std::uint32_t id = tipo_id_de(acceso.member().obj());
        const pb::Type* tipo = nominal_de(id);
        if (tipo == nullptr) tipo = nominal_escrito(acceso.member().obj());
        if (tipo == nullptr) {
            fallo("el acceso a miembro solo baja sobre un tipo con nombre",
                  acceso.ln(), acceso.col());
            return false;
        }
        int encontrado = orden_del_campo(tipo->name(),
                                         acceso.member().member());
        if (encontrado < 0) {
            fallo("'" + tipo->name() + "' no declara el campo '" +
                      acceso.member().member() + "'",
                  acceso.ln(), acceso.col());
            return false;
        }
        indice = encontrado;
        return true;
    }

    // El ORDEN de un campo dentro de su struct. Es el orden de declaracion:
    // el mismo que ve el interprete y el que vera el layout nativo.
    int orden_del_campo(const std::string& tipo, const std::string& campo) const {
        // El TIPO llega con su identidad completa ('vector.Vector'), pero el
        // 'StructDecl' guarda el nombre con el que se ESCRIBIO la
        // declaracion ('Vector') — dentro de su propia unidad nadie se
        // califica a si mismo. Aqui se cruzan los dos: el nombre suelto
        // decide que declaracion es, y el prefijo, en que unidad buscarla.
        //
        // El prefijo se compara contra el ULTIMO tramo del alias de la
        // unidad porque son dos formas del mismo nombre: la identidad la
        // pone el '#export' de la libreria ('vector') y el alias de la
        // imagen lleva ademas su paquete ('array.vector').
        const std::size_t punto = tipo.rfind('.');
        const std::string nombre =
            punto == std::string::npos ? tipo : tipo.substr(punto + 1);
        const std::string prefijo =
            punto == std::string::npos ? "" : tipo.substr(0, punto);

        const auto buscar = [&](const pb::Module& m) -> int {
            for (const pb::Decl& decl : m.items()) {
                if (decl.node_case() != pb::Decl::kStructDecl) continue;
                if (decl.struct_decl().name() != nombre) continue;
                for (int i = 0; i < decl.struct_decl().fields_size(); ++i) {
                    if (decl.struct_decl().fields(i).name() == campo) return i;
                }
            }
            return -1;
        };

        if (const int aqui = buscar(module_); aqui >= 0) return aqui;
        for (const std::unique_ptr<hir::Unit>& u : image_.units()) {
            if (!prefijo.empty() && !unidad_es(u->alias(), prefijo)) continue;
            if (const int alli = buscar(u->module()); alli >= 0) return alli;
        }
        return -1;
    }

    //: ¿el alias de una unidad ('array.vector') nombra la unidad 'prefijo'
    //: ('vector')? Se compara el ultimo tramo: la identidad de un tipo la
    //: pone el '#export' de su archivo, sin el paquete que lo contiene.
    static bool unidad_es(const std::string& alias,
                          const std::string& prefijo) {
        if (alias == prefijo) return true;
        return alias.size() > prefijo.size() &&
               alias.compare(alias.size() - prefijo.size(), prefijo.size(),
                             prefijo) == 0 &&
               alias[alias.size() - prefijo.size() - 1] == '.';
    }

    bool miembro(const pb::Expr& e, Reg& dst) {
        // 'tk.TType.PLUS' o 'constants.PI': algo de OTRA unidad nombrado por
        // el alias de su import. El objeto no es un valor (el alias no vive
        // en ningun slot), asi que se resuelve la RUTA entera.
        switch (ruta_a_otra_unidad(e, dst)) {
            case Ruta::Resuelta: return true;
            case Ruta::Fallo: return false;
            case Ruta::NoEsRuta: break;
        }
        // 'Dato.Vacio' de un enum SUMA: un objeto con su etiqueta.
        std::string item;
        if (const pb::EnumDecl* en = suma_de_miembro(e, item)) {
            return variante(*en, item, {}, e, dst);
        }
        // 'Color.ROJO': un item de enum es una constante, no una lectura.
        if (e.member().obj().node_case() == pb::Expr::kIdentifier) {
            std::int64_t valor = 0;
            if (item_de_enum_de(e.member().obj().identifier().name(),
                                e.member().member(), valor)) {
                dst = nuevo_reg();
                Inst cte;
                cte.op = Op::ConstI;
                cte.dst = dst;
                cte.imm = valor;
                cte.line = e.ln();
                cte.col = e.col();
                emitir(std::move(cte));
                return true;
            }
        }
        Reg objeto = kNoReg;
        if (!expresion(e.member().obj(), objeto, false)) return false;
        int indice = 0;
        if (!campo_de(e, indice)) return false;
        dst = nuevo_reg();
        Inst get;
        get.op = Op::GetField;
        get.dst = dst;
        get.a = objeto;
        get.imm = indice;
        get.line = e.ln();
        get.col = e.col();
        emitir(std::move(get));
        if (es_campo_celda(e, indice)) dst = leer_celda(dst, e.ln(), e.col());
        return true;
    }

    // '&lvalue'.
    //
    // El valor de un tipo con NOMBRE ya es el handle de su objeto en el
    // monton, asi que su direccion es ese mismo handle: pasarlo a una funcion
    // le da acceso al MISMO objeto, que es exactamente el aliasing que hace
    // el interprete con sus celdas. No hace falta representar la referencia
    // aparte.
    //
    // Sobre un ESCALAR no vale el truco —el valor esta en el registro, no en
    // el monton— y por eso se rechaza aqui en vez de bajarse mal. Hoy el
    // frontend no deja hacer casi nada con un 'ptr int' (ni desreferenciarlo
    // ni operarlo), asi que lo que no baja tampoco se puede escribir.
    bool direccion(const pb::Expr& e, Reg& dst) {
        const pb::Expr& operando = e.addr_of().operand();
        // un escalar en su celda: la direccion es el handle de la celda
        if (operando.node_case() == pb::Expr::kIdentifier) {
            const auto slot = nombres_.find(operando.identifier().name());
            if (slot != nombres_.end() && es_celda(slot->second)) {
                dst = nuevo_reg();
                Inst inst;
                inst.op = Op::Borrow;
                inst.dst = dst;
                inst.slot = slot->second;
                inst.line = e.ln();
                inst.col = e.col();
                emitir(std::move(inst));
                return true;
            }
            const int g = slot == nombres_.end() ? global(operando.identifier().name()) : -1;
            if (g >= 0 && global_en_celda(g)) {
                dst = nuevo_reg();
                Inst load;
                load.op = Op::LoadGlobal;
                load.dst = dst;
                load.slot = static_cast<std::uint32_t>(g);
                load.line = e.ln();
                load.col = e.col();
                emitir(std::move(load));
                return true;
            }
        }
        // un campo escalar en celda: su direccion es el handle de la celda
        if (operando.node_case() == pb::Expr::kMember) {
            int indice = 0;
            if (nominal_de(tipo_id_de(operando.member().obj())) != nullptr &&
                campo_de(operando, indice) && es_campo_celda(operando, indice)) {
                Reg objeto = kNoReg;
                if (!expresion(operando.member().obj(), objeto, false)) return false;
                dst = nuevo_reg();
                Inst get;
                get.op = Op::GetField;
                get.dst = dst;
                get.a = objeto;
                get.imm = indice;
                get.line = e.ln();
                get.col = e.col();
                emitir(std::move(get));
                return true;
            }
        }
        // '&b[i]': el PRESTAMO de un elemento. Si el elemento es un OBJETO,
        // su handle ya es el prestamo (lo que usa 'Vector.at'). La direccion
        // de un escalar necesitaria un puntero interior (bloque +
        // desplazamiento): falla al EJECUTARLA con RT011, como en el
        // interprete.
        if (operando.node_case() == pb::Expr::kIndex) {
            if (es_puntero(tipo_id_de(operando.index().obj())) && es_valor_propio(operando)) {
                Reg base = kNoReg;
                if (!expresion(operando.index().obj(), base, false)) return false;
                Reg indice = kNoReg;
                if (!expresion(operando.index().index(), indice, false)) return false;
                dst = nuevo_reg();
                Inst get;
                get.op = Op::GetIndex;
                get.dst = dst;
                get.a = base;
                get.b = indice;
                get.line = e.ln();
                get.col = e.col();
                emitir(std::move(get));
                return true;
            }
            Inst fallar;
            fallar.op = Op::Fallar;
            fallar.imm = interna("RT011: '&' sobre un elemento que no es un objeto: la "
                                 "dirección de un escalar dentro de un bloque no tiene "
                                 "soporte de ejecución");
            fallar.line = e.ln();
            fallar.col = e.col();
            emitir(std::move(fallar));
            dst = constante_i(0, e.ln(), e.col());
            return true;
        }
        if (nominal_de(tipo_id_de(operando)) == nullptr) {
            fallo("'&' sobre este escalar no baja al MIR: solo sobre una "
                  "variable, un parametro, una global o un campo",
                  e.ln(), e.col());
            return false;
        }
        if (operando.node_case() == pb::Expr::kIdentifier) {
            const auto slot = nombres_.find(operando.identifier().name());
            if (slot != nombres_.end()) {
                dst = nuevo_reg();
                Inst inst;
                inst.op = Op::Borrow;
                inst.dst = dst;
                inst.slot = slot->second;
                inst.line = e.ln();
                inst.col = e.col();
                emitir(std::move(inst));
                return true;
            }
        }
        return expresion(operando, dst, false);
    }

    bool literal_struct(const pb::Expr& e, Reg& dst) {
        const pb::StructLiteral& nodo = e.struct_literal();
        const int campos = nodo.values_size();
        // Los campos se calculan ANTES de reservar el objeto: si uno lanza,
        // mueren los ya calculados (frescos, cada uno por su tipo) y no un
        // objeto a medias. Un objeto a medias no es un valor de su tipo, y
        // correrle su '__free__' seria destruir algo que nunca existio (C++
        // tampoco lo hace); es lo que hace el interprete.
        std::vector<std::pair<int, Reg>> escritos;
        for (int i = 0; i < campos; ++i) {
            Reg valor = kNoReg;
            if (!expresion(nodo.values(i), valor, false)) return false;
            if (nodo.values(i).node_case() == pb::Expr::kMoveExpr &&
                es_valor_propio(nodo.values(i))) {
                fresco(valor);
            }
            copia_si_es_lugar(nodo.values(i), valor);
            // el literal escribe los campos EN EL ORDEN DECLARADO, no en el
            // que se escribieron: 'P{ y: 2, x: 1 }' tiene que dar lo mismo.
            const int orden = i < nodo.field_names_size()
                ? orden_del_campo(nodo.type_name(), nodo.field_names(i))
                : i;
            pb::Type campo;
            if (tipo_de_campo(e, orden < 0 ? i : orden, campo)) {
                encajar(campo, nodo.values(i), valor);
            }
            // se consume al escribirse en el objeto, al final
            {
                pb::Type t;
                if (tipo_concreto_de(e, t) && t.kind() == pb::NOMINAL) {
                    const Formas::Declaracion d = formas_.declaracion(t.name());
                    if (d.estructura != nullptr &&
                        formas_.campo_en_celda(d.estructura, orden < 0 ? i : orden)) {
                        valor = celda_con(valor, e.ln(), e.col());
                        fresco(valor);
                    }
                }
            }
            escritos.emplace_back(orden < 0 ? i : orden, valor);
        }
        dst = nuevo_reg();
        Inst alloc;
        alloc.op = Op::Alloc;
        alloc.dst = dst;
        alloc.imm = campos;
        alloc.layout = forma_de(e);
        alloc.line = e.ln();
        alloc.col = e.col();
        emitir(std::move(alloc));
        for (const auto& [campo, valor] : escritos) {
            Inst set;
            set.op = Op::SetField;
            set.a = dst;
            set.b = valor;
            set.imm = campo;
            set.line = e.ln();
            set.col = e.col();
            emitir(std::move(set));
            consumir(valor);
        }
        fresco(dst);
        return true;
    }

    // El 'enum' que se llama asi, SI alguna de sus variantes lleva payload.
    //
    // La distincion importa porque los dos se representan distinto y no es
    // un capricho: un enum de variantes unidad ES un entero (y por eso
    // 'cast<int>' funciona sobre el), mientras que uno con payload lleva
    // valores dentro y tiene que ser un objeto. Mezclarlos obligaria a que el
    // enum mas simple del lenguaje pagara una asignacion de monton.
    const pb::EnumDecl* enum_suma_de(const std::string& nombre) const {
        if (const pb::EnumDecl* d = enum_suma_en(module_, nombre)) return d;
        for (const std::unique_ptr<hir::Unit>& u : image_.units()) {
            if (const pb::EnumDecl* d = enum_suma_en(u->module(), nombre)) return d;
        }
        return nullptr;
    }

    // El enum SUMA (con alguna variante con payload) 'nombre' de 'm'.
    static const pb::EnumDecl* enum_suma_en(const pb::Module& m,
                                            const std::string& nombre) {
        for (const pb::Decl& decl : m.items()) {
            if (decl.node_case() != pb::Decl::kEnumDecl) continue;
            if (decl.enum_decl().name() != nombre) continue;
            for (const pb::EnumItem& it : decl.enum_decl().items()) {
                if (it.payload_type_ids_size() > 0) return &decl.enum_decl();
            }
            return nullptr;
        }
        return nullptr;
    }

    // La ETIQUETA de una variante: su posicion de declaracion. Es lo que
    // compara un 'match', y basta con que sea estable dentro del enum.
    int indice_de_variante(const pb::EnumDecl& en,
                           const std::string& item) const {
        for (int i = 0; i < en.items_size(); ++i) {
            if (en.items(i).name() == item) return i;
        }
        return -1;
    }

    // 'E.X' de un enum suma: un objeto de un campo con la etiqueta. Una
    // variante SIN payload sigue siendo un objeto, porque el 'match' lee
    // siempre el campo 0 y no puede depender de con cual se construyo.
    bool variante(const pb::EnumDecl& en, const std::string& item,
                  const std::vector<Reg>& payload, const pb::Expr& e,
                  Reg& dst) {
        const int etiqueta = indice_de_variante(en, item);
        if (etiqueta < 0) {
            fallo("'" + en.name() + "' no declara la variante '" + item + "'",
                  e.ln(), e.col());
            return false;
        }
        dst = nuevo_reg();
        Inst alloc;
        alloc.op = Op::Alloc;
        alloc.dst = dst;
        alloc.imm = 1 + static_cast<std::int64_t>(payload.size());
        alloc.layout = forma_de(e);
        alloc.line = e.ln();
        alloc.col = e.col();
        emitir(std::move(alloc));
        Reg tag = nuevo_reg();
        Inst cte;
        cte.op = Op::ConstI;
        cte.dst = tag;
        cte.imm = etiqueta;
        cte.line = e.ln();
        cte.col = e.col();
        emitir(std::move(cte));
        Inst set;
        set.op = Op::SetField;
        set.a = dst;
        set.b = tag;
        set.imm = 0;
        set.line = e.ln();
        set.col = e.col();
        emitir(std::move(set));
        for (std::size_t i = 0; i < payload.size(); ++i) {
            Inst campo;
            campo.op = Op::SetField;
            campo.a = dst;
            campo.b = payload[i];
            campo.imm = static_cast<std::int64_t>(i) + 1;
            campo.line = e.ln();
            campo.col = e.col();
            emitir(std::move(campo));
        }
        fresco(dst);   // una variante recien hecha no es de nadie todavia
        return true;
    }

    // El enum y la variante que nombra 'E.X', si es de un enum suma.
    const pb::EnumDecl* suma_de_miembro(const pb::Expr& acceso,
                                        std::string& item) const {
        if (acceso.node_case() != pb::Expr::kMember) return nullptr;
        item = acceso.member().member();
        const pb::Expr& dueno = acceso.member().obj();
        if (dueno.node_case() == pb::Expr::kIdentifier) {
            return enum_suma_de(dueno.identifier().name());
        }
        // 'fig.Figura.Circulo': el enum vive en la unidad que nombra el alias
        std::vector<std::string> tramos;
        if (!ruta_de(dueno, tramos) || tramos.size() != 2) return nullptr;
        const auto enlace = enlaces_.find(tramos[0]);
        if (enlace == enlaces_.end()) return nullptr;
        const hir::Unit* unidad = unidad_de(enlace->second);
        if (unidad == nullptr) return nullptr;
        return enum_suma_en(unidad->module(), tramos[1]);
    }

    // ¿'nombre' es un item de enum de alguna unidad? Devuelve su entero.
    bool item_de_enum(const std::string& nombre, std::int64_t& valor) const {
        return busca_item("", nombre, valor);
    }

    bool item_de_enum_de(const std::string& enum_nombre,
                         const std::string& item, std::int64_t& valor) const {
        return busca_item(enum_nombre, item, valor);
    }

    bool busca_item(const std::string& enum_nombre, const std::string& item,
                    std::int64_t& valor) const {
        if (busca_item_en(module_, enum_nombre, item, valor)) return true;
        for (const std::unique_ptr<hir::Unit>& u : image_.units()) {
            if (busca_item_en(u->module(), enum_nombre, item, valor)) return true;
        }
        return false;
    }

    static bool busca_item_en(const pb::Module& modulo, const std::string& enum_nombre,
                              const std::string& item, std::int64_t& valor) {
        const auto mirar = [&](const pb::Module& m) -> bool {
            for (const pb::Decl& decl : m.items()) {
                if (decl.node_case() != pb::Decl::kEnumDecl) continue;
                const pb::EnumDecl& en = decl.enum_decl();
                if (!enum_nombre.empty() && en.name() != enum_nombre) continue;
                std::int64_t siguiente = 0;
                for (const pb::EnumItem& it : en.items()) {
                    if (it.payload_type_ids_size() > 0) return false;
                    std::int64_t actual = siguiente;
                    if (it.has_value() &&
                        it.value().node_case() == pb::Expr::kLiteral &&
                        it.value().literal().kind() == "int") {
                        actual = it.value().literal().int_value();
                    }
                    if (it.name() == item) {
                        valor = actual;
                        return true;
                    }
                    siguiente = actual + 1;
                }
            }
            return false;
        };
        return mirar(modulo);
    }

    bool llamada(const pb::Expr& e, Reg& dst, bool descartar) {
        // A que llama esto ya lo decidio 'hir/resolve': aqui no se vuelve a
        // buscar. Esa es la razon de que resolve exista antes que el MIR.
        const hir::Call* sitio = resolved_.site_of(e);
        if (sitio == nullptr) {
            fallo("esta llamada no se resolvio", e.ln(), e.col());
            return false;
        }
        // VM003: el dueño del hook es un PARAMETRO de tipo de esta unidad, no
        // un tipo: la llamada la prometio una cota (ver 'bound_call_message')
        const std::string& dueno_hook = e.call().hook().owner_type();
        if (sitio->target == hir::CallTarget::Unresolved && !dueno_hook.empty() &&
            declares_type_param(module_, dueno_hook)) {
            fallo(bound_call_message(module_.source_file(), dueno_hook), e.ln(), e.col());
            return false;
        }
        Inst inst;
        if (sitio->target == hir::CallTarget::Function) {
            inst.op = Op::Call;
            inst.func = sitio->index;
        } else if (sitio->target == hir::CallTarget::Host) {
            // Un PROTOTIPO lo cumple quien ejecuta. El MIR guarda su nombre y
            // no su cuerpo: es la misma costura que usa el interprete, y la
            // que hara que el backend nativo enlace el simbolo de verdad.
            inst.op = Op::CallHost;
            inst.func = host(resolved_.functions[
                static_cast<std::size_t>(sitio->index)]);
        } else if (sitio->target == hir::CallTarget::Method) {
            // un metodo es una funcion corriente con el receptor de primer
            // argumento; quien es ya lo decidio 'resolve' por (dueno, nombre)
            inst.op = Op::Call;
            inst.func = sitio->index;
        } else if (sitio->target == hir::CallTarget::Hook) {
            int destino = -1;
            if (!funcion_del_hook(e.call().hook(), destino)) {
                fallo("el hook de esta llamada no esta ligado a ninguna "
                      "funcion de la imagen", e.ln(), e.col());
                return false;
            }
            inst.op = Op::Call;
            inst.func = destino;
        } else if (sitio->target == hir::CallTarget::Native) {
            return nativa(e, dst);
        } else if (sitio->target == hir::CallTarget::Variant) {
            std::string item;
            const pb::EnumDecl* en = suma_de_miembro(e.call().callee(), item);
            if (en == nullptr) {
                fallo("no se encontro el enum de la variante '" +
                          sitio->name + "'", e.ln(), e.col());
                return false;
            }
            std::vector<Reg> payload;
            for (const pb::Expr& arg : e.call().args()) {
                Reg reg = kNoReg;
                if (!expresion(arg, reg, false)) return false;
                if (arg.node_case() == pb::Expr::kMoveExpr && es_valor_propio(arg)) {
                    fresco(reg);
                }
                copia_si_es_lugar(arg, reg);
                pb::Type destino;
                if (tipo_de_payload(e, item, static_cast<int>(payload.size()), destino)) {
                    encajar(destino, arg, reg);
                }
                payload.push_back(reg);
            }
            // la variante es su dueña cuando existe, no antes (ver las llamadas)
            for (const Reg r : payload) consumir(r);
            if (!variante(*en, item, payload, e, dst)) return false;
            // descartada ('E.V(R{...});'): muere al cerrar la sentencia
            if (e.call().temp_by_type()) registrar_temporal_por_tipo(dst);
            return true;
        } else {
            fallo(std::string("esta llamada se resolvio a '") +
                      hir::to_string(sitio->target) +
                      "', que el MIR no baja todavia", e.ln(), e.col());
            return false;
        }
        inst.line = e.ln();
        inst.col = e.col();
        if (inst.op == Op::Call) {
            // la instancia para los tipos concretos de ESTA llamada
            std::vector<pb::Type> tipos;
            std::vector<bool> hay;
            const auto anotar = [&](const pb::Expr& x) {
                pb::Type t;
                hay.push_back(tipo_concreto_de(x, t));
                tipos.push_back(std::move(t));
            };
            if (sitio->target == hir::CallTarget::Method) {
                anotar(e.call().callee().member().obj());
            }
            for (const pb::Expr& arg : e.call().args()) anotar(arg);
            std::vector<const pb::Type*> args;
            for (std::size_t i = 0; i < tipos.size(); ++i) {
                args.push_back(hay[i] ? &tipos[i] : nullptr);
            }
            pb::Type resultado;
            const bool con_resultado = tipo_concreto_de(e, resultado);
            inst.func = instancias_.para(inst.func, args,
                                         con_resultado ? &resultado : nullptr);
        } else if (inst.op == Op::CallHost &&
                   resolved_.functions[static_cast<std::size_t>(sitio->index)].name ==
                       "__reserve__") {
            // un bloque de objetos: sus celdas son de quien lo reserva, y se
            // copian y se sueltan con el
            pb::Type bloque;
            if (tipo_concreto_de(e, bloque) && bloque.has_inner() &&
                formas_.propio(bloque.inner())) {
                inst.layout = formas_.forma(bloque.inner());
            }
            // un bloque de 'byte' es COMPACTO: un byte por celda (imm = 1)
            if (tipo_concreto_de(e, bloque) && bloque.has_inner() &&
                bloque.inner().kind() == pb::BYTE) {
                inst.imm = 1;
            }
        }
        // 'p.doble()' pasa 'p' de primer argumento: el receptor no viaja en
        // 'args', viaja en el callee.
        if (sitio->target == hir::CallTarget::Method) {
            Reg receptor = kNoReg;
            const pb::Expr& objeto = e.call().callee().member().obj();
            // un receptor 'T ptr' que vive en una celda (un enum sin
            // payload) recibe el PRESTAMO de la celda, no su valor: como
            // '&e', y como el interprete
            bool prestado = false;
            if (parametro_es_puntero(inst, 0) && objeto.node_case() == pb::Expr::kIdentifier) {
                const auto slot = nombres_.find(objeto.identifier().name());
                if (slot != nombres_.end() && es_celda(slot->second)) {
                    receptor = nuevo_reg();
                    Inst borrow;
                    borrow.op = Op::Borrow;
                    borrow.dst = receptor;
                    borrow.slot = slot->second;
                    borrow.line = objeto.ln();
                    borrow.col = objeto.col();
                    emitir(std::move(borrow));
                    prestado = true;
                }
            }
            if (!prestado && !expresion(objeto, receptor, false)) return false;
            inst.args.push_back(receptor);
        }
        // El parametro por valor es el nuevo dueño de su argumento, pero
        // recien cuando la llamada ocurre: si un argumento POSTERIOR lanza
        // ('usa(C{...}, falla())'), los anteriores siguen siendo temporales
        // y se liberan por el camino de la excepcion.
        std::vector<Reg> por_consumir;
        for (const pb::Expr& arg : e.call().args()) {
            Reg reg = kNoReg;
            if (!expresion(arg, reg, false)) return false;
            // 'move x' deja el valor sin dueño hasta que la llamada ocurre: si
            // un argumento posterior lanza, muere por el camino de la excepcion
            if (arg.node_case() == pb::Expr::kMoveExpr && es_valor_propio(arg)) fresco(reg);
            if (!parametro_es_puntero(inst, inst.args.size())) {
                copia_si_es_lugar(arg, reg);
                pb::Type destino;
                if (tipo_del_parametro(inst, inst.args.size(), destino)) {
                    encajar(destino, arg, reg);
                }
                por_consumir.push_back(reg);
            }
            inst.args.push_back(reg);
        }
        for (const Reg r : por_consumir) consumir(r);
        // un resultado que posee recursos se guarda aunque se descarte: es
        // justo el temporal que hay que destruir al cerrar la sentencia
        const bool temporal = e.call().has_temp_drop() &&
                              !e.call().temp_drop().owner_type().empty();
        const bool propio = inst.op == Op::Call && es_valor_propio(e);
        if (!descartar || temporal || propio) {
            dst = nuevo_reg();
            inst.dst = dst;
        }
        emitir(std::move(inst));
        if (temporal) registrar_temporal(dst, e.call().temp_drop());
        else if (propio && e.call().temp_by_type()) registrar_temporal_por_tipo(dst);
        else if (propio) fresco(dst);
        return true;
    }

    // La instancia de un HOOK para el tipo concreto de su receptor (el
    // primer argumento) y, si se sabe, de su resultado.
    int instancia_de_hook(int destino, const pb::Expr& receptor, const pb::Expr* llamada) {
        pb::Type r;
        if (!tipo_concreto_de(receptor, r)) return destino;
        pb::Type resultado;
        const bool con = llamada != nullptr && tipo_concreto_de(*llamada, resultado);
        return instancias_.para(destino, {&r}, con ? &resultado : nullptr);
    }

    // La instancia de un hook cuyo receptor es un tipo ya conocido (un
    // destructor al cerrar un ambito).
    int instancia_de_hook(int destino, const pb::Type& receptor) {
        return instancias_.para(destino, {&receptor}, nullptr);
    }

    // ¿El parametro 'i' de la funcion que llama 'inst' es un puntero? Un
    // puntero es un prestamo: pasarle un lugar no copia nada.
    bool parametro_es_puntero(const Inst& inst, std::size_t i) const {
        if (inst.op != Op::Call || inst.func < 0) return false;
        const std::size_t base = instancias_.base_de(static_cast<std::size_t>(inst.func));
        if (base >= resolved_.functions.size()) return false;
        const hir::Function& f = resolved_.functions[base];
        if (f.decl == nullptr || static_cast<int>(i) >= f.decl->params_size()) return false;
        const hir::Unit* suya = unidad_de(f.unit);
        if (suya == nullptr) return false;
        const pb::Type* t = Formas::tipo_en(suya->module(),
                                            f.decl->params(static_cast<int>(i)).type_id());
        return t != nullptr && t->kind() == pb::POINTER;
    }

    // El codigo de 'ToStr' que le toca a un tipo (ver 'Formas::modo_texto'),
    // o -1 si no se sabe escribir.
    int como_texto(std::uint32_t id) const {
        if (id >= static_cast<std::uint32_t>(module_.types_size())) return -1;
        return como_texto(concreto(module_.types(static_cast<int>(id))));
    }

    int como_texto(const pb::Type& t) const { return formas_.modo_texto(t); }

    // f"a{x}b": los trozos se van pegando de izquierda a derecha. El primero
    // no concatena con nada — arrancar de la cadena vacia costaria una
    // instruccion y una entrada de tabla por cada f-string.
    // El indice de un formato en 'Program::formatos' (deduplicado). El
    // especificador ya lo valido el frontend: '[0][ancho][.precision][tipo]'.
    std::int64_t formato(int modo, bool repr, const std::string& spec) {
        Formato f;
        f.modo = modo;
        f.repr = repr;
        std::size_t i = 0;
        if (i < spec.size() && spec[i] == '0') { f.cero = true; ++i; }
        while (i < spec.size() && spec[i] >= '0' && spec[i] <= '9') {
            f.ancho = f.ancho * 10 + (spec[i] - '0');
            ++i;
        }
        if (i < spec.size() && spec[i] == '.') {
            ++i;
            f.precision = 0;
            while (i < spec.size() && spec[i] >= '0' && spec[i] <= '9') {
                f.precision = f.precision * 10 + (spec[i] - '0');
                ++i;
            }
        }
        if (i < spec.size()) f.clase = spec[i];
        std::vector<Formato>& todos = program_.formatos;
        for (std::size_t k = 0; k < todos.size(); ++k) {
            const Formato& o = todos[k];
            if (o.modo == f.modo && o.repr == f.repr && o.cero == f.cero &&
                o.ancho == f.ancho && o.precision == f.precision && o.clase == f.clase) {
                return static_cast<std::int64_t>(k);
            }
        }
        todos.push_back(f);
        return static_cast<std::int64_t>(todos.size() - 1);
    }

    bool interpolada(const pb::Expr& e, Reg& dst) {
        bool primero = true;
        for (const pb::InterpolatedString::Part& parte : e.interp().parts()) {
            Reg trozo = kNoReg;
            if (parte.part_case() ==
                pb::InterpolatedString::Part::kText) {
                trozo = nuevo_reg();
                Inst cte;
                cte.op = Op::ConstStr;
                cte.dst = trozo;
                cte.imm = interna(parte.text());
                cte.line = e.ln();
                cte.col = e.col();
                emitir(std::move(cte));
            } else {
                Reg valor = kNoReg;
                if (!expresion(parte.expr(), valor, false)) return false;
                const int modo = como_texto_de(parte.expr());
                if (modo < 0) {
                    fallo("el MIR no sabe escribir este valor dentro de un "
                          "f-string", parte.expr().ln(), parte.expr().col());
                    return false;
                }
                if (parte.repr() || !parte.spec().empty()) {
                    trozo = nuevo_reg();
                    Inst texto;
                    texto.op = Op::Formatear;
                    texto.dst = trozo;
                    texto.a = valor;
                    texto.imm = formato(modo, parte.repr(), parte.spec());
                    texto.line = e.ln();
                    texto.col = e.col();
                    emitir(std::move(texto));
                } else if (modo == 4) {
                    trozo = valor;
                } else {
                    trozo = nuevo_reg();
                    Inst texto;
                    texto.op = Op::ToStr;
                    texto.dst = trozo;
                    texto.a = valor;
                    texto.imm = modo;
                    texto.line = e.ln();
                    texto.col = e.col();
                    emitir(std::move(texto));
                }
            }
            if (primero) {
                dst = trozo;
                primero = false;
                continue;
            }
            Reg unido = nuevo_reg();
            Inst pega;
            pega.op = Op::ConcatStr;
            pega.dst = unido;
            pega.a = dst;
            pega.b = trozo;
            pega.line = e.ln();
            pega.col = e.col();
            emitir(std::move(pega));
            dst = unido;
        }
        if (primero) {   // f"" — una cadena vacia sigue siendo una cadena
            dst = nuevo_reg();
            Inst cte;
            cte.op = Op::ConstStr;
            cte.dst = dst;
            cte.imm = interna("");
            emitir(std::move(cte));
        }
        return true;
    }

    // 'sizeof(T)': lo contesta el '__sizeof__' del tipo, que es una funcion
    // como cualquier otra. Sin hook no hay respuesta que dar — el interprete
    // tampoco la tiene.
    bool tamano(const pb::Expr& e, Reg& dst) {
        int destino = -1;
        if (e.sizeof_().hook().owner_type().empty() ||
            !funcion_del_hook(e.sizeof_().hook(), destino)) {
            // lo mismo que el interprete: un error al EJECUTARLO (RT011), no
            // un programa que no compila. La VM tampoco tiene un layout
            // nativo que contestar: un struct es un handle.
            Inst fallar;
            fallar.op = Op::Fallar;
            fallar.imm = interna("RT011: sizeof sin '__sizeof__' declarado: el "
                                 "layout nativo es del backend");
            fallar.line = e.ln();
            fallar.col = e.col();
            emitir(std::move(fallar));
            dst = constante_i(0, e.ln(), e.col());
            return true;
        }
        // el hook recibe un valor del tipo y no lo mira: le basta con su
        // firma. Se le pasa cero, igual que el interprete le pasa 'None'.
        Reg falso = nuevo_reg();
        Inst cero;
        cero.op = Op::ConstI;
        cero.dst = falso;
        cero.imm = 0;
        emitir(std::move(cero));
        dst = nuevo_reg();
        Inst llamar;
        llamar.op = Op::Call;
        llamar.func = destino;
        llamar.dst = dst;
        llamar.args.push_back(falso);
        llamar.line = e.ln();
        llamar.col = e.col();
        emitir(std::move(llamar));
        return true;
    }

    // 'len(s)' y compania: los primitivos no tienen hooks que llamar, asi
    // que su operacion ES una instruccion.
    bool nativa(const pb::Expr& e, Reg& dst) {
        const pb::HookRef& ref = e.call().hook();
        if (ref.kind() == pb::HASH) return hash_de(e, dst);
        if (ref.kind() == pb::PRINT) {
            fallo(print_primitive_message(module_.source_file(), ref.owner_type()),
                  e.ln(), e.col());
            return false;
        }
        if (ref.kind() != pb::LEN || e.call().args_size() != 1) {
            fallo("el unico nativo que baja al MIR es 'len' de una cadena",
                  e.ln(), e.col());
            return false;
        }
        Reg cadena = kNoReg;
        if (!expresion(e.call().args(0), cadena, false)) return false;
        dst = nuevo_reg();
        Inst inst;
        inst.op = Op::LenStr;
        inst.dst = dst;
        inst.a = cadena;
        inst.line = e.ln();
        inst.col = e.col();
        emitir(std::move(inst));
        return true;
    }

    // 'hash(x)' con el tipo CONCRETO de 'x': en una instancia de un generico
    // ('Dictionary<str, V>') es donde por fin se sabe.
    bool hash_de(const pb::Expr& e, Reg& dst) {
        const pb::Expr& arg = e.call().args_size() == 1
            ? e.call().args(0) : e.call().callee().member().obj();
        Reg valor = kNoReg;
        if (!expresion(arg, valor, false)) return false;
        pb::Type t;
        if (!tipo_concreto_de(arg, t)) {
            fallo("el tipo de lo que se pasa a 'hash' no se conoce", e.ln(), e.col());
            return false;
        }
        while (t.kind() == pb::ERROR && t.has_inner()) {
            pb::Type dentro = t.inner();
            t = std::move(dentro);
        }
        int modo = -1;
        if (t.kind() == pb::INT || t.kind() == pb::BOOL || t.kind() == pb::BYTE) modo = 0;
        else if (t.kind() == pb::STR) modo = 1;
        else if (t.kind() == pb::CHAR) modo = 2;
        else if (t.kind() == pb::NOMINAL && es_enum_simple(t.name())) modo = 0;
        if (modo >= 0) {
            dst = nuevo_reg();
            Inst h;
            h.op = Op::Hash;
            h.dst = dst;
            h.a = valor;
            h.imm = modo;
            h.line = e.ln();
            h.col = e.col();
            emitir(std::move(h));
            return true;
        }
        std::string sin_hash = "un 'float' no tiene hash: NaN no es igual a si mismo";
        if (t.kind() == pb::NOMINAL) {
            pb::HookRef ref;
            ref.set_owner_type(t.name());
            ref.set_kind(pb::HASH);
            int destino = -1;
            if (image_.hook(ref) != nullptr && funcion_del_hook(ref, destino)) {
                dst = nuevo_reg();
                Inst llamar;
                llamar.op = Op::Call;
                llamar.dst = dst;
                llamar.func = instancia_de_hook(destino, t);
                llamar.args = {valor};
                llamar.line = e.ln();
                llamar.col = e.col();
                emitir(std::move(llamar));
                return true;
            }
            sin_hash = "'" + t.name() + "' no define '__hash__'";
        }
        // lo mismo que el interprete: un error al EJECUTARLO (RT011)
        Inst fallar;
        fallar.op = Op::Fallar;
        fallar.imm = interna("RT011: " + sin_hash);
        fallar.line = e.ln();
        fallar.col = e.col();
        emitir(std::move(fallar));
        dst = constante_i(0, e.ln(), e.col());
        return true;
    }

    // 's[i]'. Sobre una cadena es nativo; sobre un tipo con nombre lo cumple
    // su '__index__', que es una funcion como cualquier otra.
    bool indexado(const pb::Expr& e, Reg& dst) {
        Reg base = kNoReg;
        if (!expresion(e.index().obj(), base, false)) return false;
        Reg indice = kNoReg;
        if (!expresion(e.index().index(), indice, false)) return false;

        // El nodo 'Index' no lleva HookRef: la clave se arma con el tipo
        // ESTATICO del objeto, que es la misma que uso el frontend para
        // indexar el hook (dueno + INDEX).
        int destino = -1;
        const pb::Type* dueno = nominal_de(tipo_id_de(e.index().obj()));
        pb::HookRef ref;
        if (dueno != nullptr) {
            ref.set_owner_type(dueno->name());
            ref.set_kind(pb::INDEX);
        }
        // igual que al escribir: el hook manda, y si no lo hay se indexa el
        // bloque crudo
        if (dueno != nullptr && funcion_del_hook(ref, destino)) {
            destino = instancia_de_hook(destino, e.index().obj(), &e);
            dst = nuevo_reg();
            Inst llamar;
            llamar.op = Op::Call;
            llamar.func = destino;
            llamar.dst = dst;
            llamar.args.push_back(base);
            llamar.args.push_back(indice);
            llamar.line = e.ln();
            llamar.col = e.col();
            emitir(std::move(llamar));
            if (es_valor_propio(e)) fresco(dst);   // '__index__' devuelve una copia
            return true;
        }

        // Sobre un PUNTERO es el indexado crudo de un bloque, no el de una
        // cadena: son dos cosas distintas que se escriben igual, y bajar la
        // una como la otra leeria una tabla de constantes en vez de memoria.
        dst = nuevo_reg();
        Inst inst;
        inst.op = es_puntero(tipo_id_de(e.index().obj())) ? Op::GetIndex
                                                          : Op::IndexStr;
        inst.dst = dst;
        inst.a = base;
        inst.b = indice;
        inst.line = e.ln();
        inst.col = e.col();
        emitir(std::move(inst));
        return true;
    }

    bool es_puntero(std::uint32_t id) const {
        if (id >= static_cast<std::uint32_t>(module_.types_size())) return false;
        return module_.types(static_cast<int>(id)).kind() == pb::POINTER;
    }

    // 'v[i] = x'. Sobre un tipo con nombre lo cumple su '__index_set__';
    // sobre un puntero es la escritura cruda en el bloque.
    bool asignar_indice(const pb::Expr& e, Reg& dst) {
        const pb::Expr& objetivo = e.assignment().target();
        Reg base = kNoReg;
        if (!expresion(objetivo.index().obj(), base, false)) return false;
        Reg indice = kNoReg;
        if (!expresion(objetivo.index().index(), indice, false)) return false;
        Reg valor = kNoReg;
        if (!expresion(e.assignment().value(), valor, false)) return false;
        copia_si_es_lugar(e.assignment().value(), valor);
        consumir(valor);

        // Primero el hook, y si no lo hay, el bloque crudo. Es el orden del
        // interprete, y hace falta que sea el mismo: 'self.datos[i]' dentro
        // de un vector generico apunta a 'T', que es una VARIABLE de tipo y
        // no declara ningun hook — ahi la escritura es cruda.
        int destino = -1;
        const pb::Type* dueno = nominal_de(tipo_id_de(objetivo.index().obj()));
        if (dueno != nullptr) {
            pb::HookRef ref;
            ref.set_owner_type(dueno->name());
            ref.set_kind(pb::INDEX_SET);
            if (funcion_del_hook(ref, destino)) {
                destino = instancia_de_hook(destino, objetivo.index().obj(), nullptr);
                Inst llamar;
                llamar.op = Op::Call;
                llamar.func = destino;
                llamar.args.push_back(base);
                llamar.args.push_back(indice);
                llamar.args.push_back(valor);
                llamar.line = e.ln();
                llamar.col = e.col();
                emitir(std::move(llamar));
                dst = valor;
                return true;
            }
        }

        if (!es_puntero(tipo_id_de(objetivo.index().obj()))) {
            fallo("escribir por indice solo baja sobre un bloque o sobre un "
                  "tipo con '__index_set__'", e.ln(), e.col());
            return false;
        }
        if (es_valor_propio(objetivo)) {
            // la celda era dueña de lo que tenia: muere (una celda sin usar
            // vale 0, que no es ningun objeto)
            Reg viejo = nuevo_reg();
            Inst get;
            get.op = Op::GetIndex;
            get.dst = viejo;
            get.a = base;
            get.b = indice;
            get.line = e.ln();
            get.col = e.col();
            get.synthetic = true;
            emitir(std::move(get));
            if (e.assignment().drops_old()) emitir_destruir(viejo);
            else emitir_free(viejo);
        }
        Inst inst;
        inst.op = Op::SetIndex;
        inst.a = base;
        inst.b = indice;
        inst.c = valor;
        inst.line = e.ln();
        inst.col = e.col();
        emitir(std::move(inst));
        dst = valor;
        return true;
    }

    // El sitio de llamada que 'resolve' anoto para esta posicion. La posicion
    // es la clave porque es lo unico que comparten los dos recorridos, y dos
    // llamadas no pueden empezar en la misma linea y columna.
    // La llamada que 'resolve' registro en (ln, col). Una posicion solo
    // identifica una llamada DENTRO DE SU ARCHIVO: sin filtrar por la unidad,
    // '__write__(s)' en stdp.libsrx:30:5 se confundia con un 'stdp.println'
    // del programa en la misma linea y columna, y println se llamaba a si
    // mismo hasta reventar la pila.
    struct Bucle {
        BlockId cabecera;
        BlockId salida;
        //: cuantos ambitos habia abiertos al entrar: los de mas adentro son
        //: los que un 'break' o un 'continue' tiene que destruir
        std::size_t ambitos = 0;
        //: cuantos temporales habia vivos al entrar (idem)
        std::size_t temporales = 0;
    };

    // --- constantes y tablas del PROGRAMA ------------------------------ //
    // Las cadenas se internan por TEXTO: dos literales iguales comparten
    // indice, y eso es lo que hace que comparar dos 'str' constantes con
    // '==' de la respuesta correcta comparando enteros.
    std::int64_t interna(const std::string& texto) {
        for (std::size_t i = 0; i < program_.strings.size(); ++i) {
            if (program_.strings[i] == texto) {
                return static_cast<std::int64_t>(i);
            }
        }
        program_.strings.push_back(texto);
        return static_cast<std::int64_t>(program_.strings.size() - 1);
    }

    int host(const hir::Function& f) {
        for (std::size_t i = 0; i < program_.hosts.size(); ++i) {
            if (program_.hosts[i] == f.name) return static_cast<int>(i);
        }
        program_.hosts.push_back(f.name);
        program_.firmas_host.push_back(firma_de(f));
        return static_cast<int>(program_.hosts.size() - 1);
    }

    Firma firma_de(const hir::Function& f) const { return firma_de_prototipo(image_, f); }

    // Una global de ESTA unidad por su nombre suelto. Una de otra unidad se
    // nombra por su ruta ('constants.PI', ver 'ruta_a_otra_unidad'): buscarla
    // por el nombre solo confundia dos globales homonimas de dos librerias.
    int global(const std::string& nombre) const {
        return global_de(unidad_, nombre);
    }

    bool global_en_celda(int g) const {
        return g >= 0 && program_.globals[static_cast<std::size_t>(g)].celda;
    }

    int global_de(const std::string& unidad, const std::string& nombre) const {
        for (std::size_t i = 0; i < program_.globals.size(); ++i) {
            if (program_.globals[i].name == nombre &&
                program_.globals[i].unit == unidad) {
                return static_cast<int>(i);
            }
        }
        return -1;
    }

    // La unidad de la imagen con ese alias ('' = el main), o nullptr.
    const hir::Unit* unidad_de(const std::string& alias) const {
        if (alias.empty()) return &image_.main();
        for (const std::unique_ptr<hir::Unit>& u : image_.units()) {
            if (u->alias() == alias) return u.get();
        }
        return nullptr;
    }

    // 'a.b.c' si 'e' es una cadena de accesos sobre un nombre; si no, false.
    static bool ruta_de(const pb::Expr& e, std::vector<std::string>& tramos) {
        if (e.node_case() == pb::Expr::kIdentifier) {
            tramos.push_back(e.identifier().name());
            return true;
        }
        if (e.node_case() != pb::Expr::kMember) return false;
        if (!ruta_de(e.member().obj(), tramos)) return false;
        tramos.push_back(e.member().member());
        return true;
    }

    enum class Ruta { NoEsRuta, Resuelta, Fallo };

    // 'alias.NOMBRE' (una global de esa unidad) o 'alias.Enum.ITEM' (un item
    // de un enum sin payload de esa unidad). El primer tramo tiene que ser
    // un import de ESTA unidad y no una variable que lo tape. Con un paquete
    // importado entero la unidad son VARIOS tramos ('math.constants.PI' con
    // '#import math'): se busca la unidad mas larga que nombre un prefijo.
    Ruta ruta_a_otra_unidad(const pb::Expr& e, Reg& dst) {
        std::vector<std::string> tramos;
        if (!ruta_de(e, tramos) || tramos.size() < 2) return Ruta::NoEsRuta;
        if (nombres_.count(tramos[0]) != 0 || global(tramos[0]) >= 0) {
            return Ruta::NoEsRuta;
        }
        const auto enlace = enlaces_.find(tramos[0]);
        if (enlace == enlaces_.end()) return Ruta::NoEsRuta;
        for (std::size_t fin = tramos.size() - 1; fin >= 1; --fin) {
            std::string alias = enlace->second;
            for (std::size_t i = 1; i < fin; ++i) alias += "." + tramos[i];
            const hir::Unit* otra = unidad_de(alias);
            if (otra == nullptr) continue;
            const std::size_t resto = tramos.size() - fin;
            if (resto == 1) {
                const int g = global_de(alias, tramos[fin]);
                if (g < 0) return Ruta::NoEsRuta;
                dst = nuevo_reg();
                Inst load;
                load.op = Op::LoadGlobal;
                load.dst = dst;
                load.slot = static_cast<std::uint32_t>(g);
                load.line = e.ln();
                load.col = e.col();
                emitir(std::move(load));
                if (global_en_celda(g)) dst = leer_celda(dst, e.ln(), e.col());
                return Ruta::Resuelta;
            }
            if (resto == 2) {
                std::int64_t valor = 0;
                if (!busca_item_en(otra->module(), tramos[fin], tramos[fin + 1], valor)) {
                    return Ruta::NoEsRuta;
                }
                dst = nuevo_reg();
                Inst cte;
                cte.op = Op::ConstI;
                cte.dst = dst;
                cte.imm = valor;
                cte.line = e.ln();
                cte.col = e.col();
                emitir(std::move(cte));
                return Ruta::Resuelta;
            }
            return Ruta::NoEsRuta;
        }
        return Ruta::NoEsRuta;
    }

    const pb::Module& module_;
    const hir::Program& resolved_;
    Function& fn_;
    Program& program_;
    const hir::Image& image_;
    std::vector<Unsupported>& fallos_;
    // los slots de escalares que viven en una CELDA ('&n')
    std::unordered_set<std::uint32_t> celdas_;
    // el tipo de retorno concreto: un 'return 5' en un '-> int?' se encaja
    pb::Type retorno_;
    //: el catalogo de formas de la imagen y, en una instancia de un
    //: generico, que tipo concreto es cada parametro
    Formas& formas_;
    Instancias& instancias_;
    const Sustitucion* sustitucion_ = nullptr;
    //: la unidad de lo que se baja ('' = el main) y sus imports
    std::string unidad_;
    hir::Bindings enlaces_;
    std::unordered_map<std::string, std::uint32_t> nombres_;
    //: los bloques HIR abiertos, para saber que muere en una salida anticipada
    std::vector<const pb::Block*> ambitos_;
    //: el pad de aterrizaje activo (-1 = fuera de todo 'try')
    int protegido_ = -1;
    //: la bandera de vivo de cada slot que alguien destruye (por SLOT: dos
    //: locales homonimas tienen cada una la suya)
    std::unordered_map<std::uint32_t, std::uint32_t> banderas_;
    //: los slots cuyo valor es un OBJETO PROPIO (hay que liberarlo al morir)
    std::unordered_set<std::uint32_t> slot_propio_;
    //: por ambito abierto (alineado con 'ambitos_'), los slots propios que
    //: declaro, en orden
    std::vector<std::vector<std::uint32_t>> propios_;
    //: registros con un objeto RECIEN HECHO que todavia nadie tomo; lo que
    //: quede al cerrar la expresion completa se libera (ver 'fresco')
    std::vector<Reg> frescos_;
    //: slots que, al morir, se destruyen POR SU TIPO ('Destruir') y no solo
    //: se liberan: los temporales guardados por si algo lanzaba
    std::set<std::uint32_t> por_tipo_;
    // los temporales que tuvieron que guardarse en un slot (ver 'guardar_frescos')
    std::unordered_map<Reg, std::uint32_t> fresco_slot_;
    // donde nacio cada temporal: el bloque, la instruccion siguiente y
    // cuantos 'try' estaban abiertos
    struct Origen {
        BlockId bloque = 0;
        std::size_t pos = 0;
        std::size_t en_try = 0;
    };
    std::unordered_map<Reg, Origen> origen_fresco_;
    //: las regiones con 'finally' abiertas (del 'try' y de sus 'catch'): una
    //: salida anticipada que las atraviesa corre su 'finally'
    std::vector<Finalizador> finales_;
    //: slots propios que el PROXIMO bloque recibe ya vivos
    std::vector<std::uint32_t> propios_al_entrar_;
    //: binding de 'catch (e)' sin tipo -> el slot con la etiqueta con que llego
    std::unordered_map<std::uint32_t, std::uint32_t> etiqueta_de_slot_;
    //: los temporales vivos de las sentencias abiertas (slots), en orden
    std::vector<std::uint32_t> temporales_;
    //: slot de temporal -> la funcion que lo destruye
    std::unordered_map<std::uint32_t, int> temporal_hook_;
    //: los slots de las locales que todavia no se declararon, por nombre y en
    //: el orden en que aparecen
    struct Pendiente { std::uint32_t slot; std::uint32_t tipo; };
    std::unordered_map<std::string, std::deque<Pendiente>> pendientes_;
    //: por bloque abierto: que nombre tapo cada declaracion, para devolverlo
    struct Restauracion {
        std::string nombre;
        bool habia = false;
        std::uint32_t slot = 0;
        std::uint32_t tipo = 0;
    };
    std::vector<std::vector<Restauracion>> restauraciones_;
    //: el 'type_id' de cada slot declarado (por indice)
    std::unordered_map<std::uint32_t, std::uint32_t> tipo_slot_;
    //: las destrucciones que el frontend anoto para cada nombre
    std::unordered_map<std::string, std::vector<const pb::Drop*>> drops_por_nombre_;
    //: por 'try' abierto: los slots declarados dentro de su bloque protegido
    std::vector<std::vector<std::uint32_t>> en_try_;
    //: bindings de 'catch' SIN tipo -> el slot con la etiqueta con que llego
    std::unordered_map<std::string, std::uint32_t> etiqueta_de_binding_;
    //: el tipo ESCRITO de los bindings de 'catch' vigentes
    std::unordered_map<std::string, const pb::Type*> escritos_;
    //: el tipo DECLARADO de cada slot, que el identificador no lleva encima
    std::unordered_map<std::string, std::uint32_t> tipos_;
    std::vector<Bucle> bucles_;
    BlockId actual_ = 0;
    bool ok_ = true;
};

// El pool de tipos es el de la UNIDAD de la funcion: un 'type_id' no
// significa lo mismo en dos unidades distintas, y bajar con el pool
// equivocado produciria un MIR con los tipos cambiados.
const pb::Module& modulo_de(const hir::Image& image, const std::string& unit) {
    if (unit.empty()) return image.main().module();
    for (const std::unique_ptr<hir::Unit>& u : image.units()) {
        if (u->alias() == unit) return u->module();
    }
    return image.main().module();
}

}  // namespace

const char* to_string(Type type) {
    switch (type) {
        case Type::I64: return "i64";
        case Type::F64: return "f64";
        case Type::Void: return "void";
    }
    return "?";
}

const char* to_string(Term term) {
    switch (term) {
        case Term::Jump: return "jump";
        case Term::Branch: return "branch";
        case Term::Return: return "return";
        case Term::Throw: return "throw";
        case Term::Unreachable: return "unreachable";
    }
    return "?";
}

const char* to_string(Op op) {
    switch (op) {
        case Op::ConstI: return "const.i";
        case Op::ConstF: return "const.f";
        case Op::Move: return "move";
        case Op::LoadLocal: return "load";
        case Op::StoreLocal: return "store";
        case Op::AddI: return "add.i";
        case Op::SubI: return "sub.i";
        case Op::MulI: return "mul.i";
        case Op::DivI: return "div.i";
        case Op::RemI: return "rem.i";
        case Op::AddF: return "add.f";
        case Op::SubF: return "sub.f";
        case Op::MulF: return "mul.f";
        case Op::DivF: return "div.f";
        case Op::RemF: return "rem.f";
        case Op::EqI: return "eq.i";
        case Op::NeI: return "ne.i";
        case Op::LtI: return "lt.i";
        case Op::LeI: return "le.i";
        case Op::GtI: return "gt.i";
        case Op::GeI: return "ge.i";
        case Op::EqF: return "eq.f";
        case Op::NeF: return "ne.f";
        case Op::LtF: return "lt.f";
        case Op::LeF: return "le.f";
        case Op::GtF: return "gt.f";
        case Op::GeF: return "ge.f";
        case Op::NegI: return "neg.i";
        case Op::NegF: return "neg.f";
        case Op::Not: return "not";
        case Op::AndI: return "and.i";
        case Op::OrI: return "or.i";
        case Op::XorI: return "xor.i";
        case Op::ShlI: return "shl.i";
        case Op::ShrI: return "shr.i";
        case Op::NotI: return "not.i";
        case Op::ConstStr: return "const.s";
        case Op::LoadGlobal: return "load.g";
        case Op::StoreGlobal: return "store.g";
        case Op::IntToFloat: return "i2f";
        case Op::FloatToInt: return "f2i";
        case Op::NarrowI: return "narrow.i";
        case Op::NarrowF: return "narrow.f";
        case Op::Alloc: return "alloc";
        case Op::GetField: return "get";
        case Op::SetField: return "set";
        case Op::Copy: return "copy";
        case Op::Free: return "free";
        case Op::FreeLanzado: return "free.lanzado";
        case Op::Destruir: return "destruir";
        case Op::Fallar: return "fallar";
        case Op::CallHost: return "call.host";
        case Op::GetIndex: return "get.idx";
        case Op::SetIndex: return "set.idx";
        case Op::LenStr: return "len.str";
        case Op::ConcatStr: return "concat.str";
        case Op::EqStr: return "eq.str";
        case Op::NeStr: return "ne.str";
        case Op::Hash: return "hash";
        case Op::LtStr: return "lt.str";
        case Op::LeStr: return "le.str";
        case Op::GtStr: return "gt.str";
        case Op::GeStr: return "ge.str";
        case Op::EqCaja: return "eq.caja";
        case Op::Formatear: return "formatear";
        case Op::ToStr: return "to.str";
        case Op::IndexStr: return "index.str";
        case Op::MarkMoved: return "mark.moved";
        case Op::Borrow: return "borrow";
        case Op::Call: return "call";
    }
    return "?";
}

// Las variables de nivel de MODULO de toda la imagen. Se recogen ANTES de
// bajar ningun cuerpo porque una funcion puede leer una global declarada mas
// abajo, o de otra unidad.
void recoger_globales(const hir::Image& image, const hir::Program& resolved,
                      Program& program, const Formas& formas) {
    // (unidad, nombre) de todo lo que alguna funcion toma por direccion
    std::set<std::pair<std::string, std::string>> direcciones;
    for (const hir::Function& f : resolved.functions) {
        for (const std::string& n : f.direcciones) direcciones.emplace(f.unit, n);
    }
    const auto de = [&](const pb::Module& m, const std::string& unidad) {
        for (const pb::Decl& decl : m.items()) {
            if (decl.node_case() != pb::Decl::kStatement) continue;
            const pb::Stmt& stmt = decl.statement();
            if (stmt.node_case() != pb::Stmt::kVarDecl) continue;
            Type tipo = Type::I64;
            tipo_de(m, stmt.var_decl().type_id(), tipo);
            const pb::Type* t = Formas::tipo_en(m, stmt.var_decl().type_id());
            const bool celda = t != nullptr && (es_escalar(*t) || t->kind() == pb::STR) &&
                               direcciones.count({unidad, stmt.var_decl().name()}) != 0;
            program.globals.push_back(Global{stmt.var_decl().name(), tipo, unidad,
                                             celda || (t != nullptr && formas.propio(*t)),
                                             celda});
        }
    };
    de(image.main().module(), "");
    for (const std::unique_ptr<hir::Unit>& u : image.units()) de(u->module(), u->alias());
}

// El tipo NOMINAL (sin 'ptr' ni '?') del objeto de un '&obj.campo', antes
// de bajar nada. Dentro de un '&' el HIR no anota el tipo del objeto, asi que
// un nombre se busca en los slots de su funcion (o en las globales de su
// unidad) y 'a.b' baja por el campo 'b' que declara el struct de 'a'.
const pb::Type* tipo_del_objeto(const pb::Expr& e, const hir::Function& f,
                                const pb::Module& m, const Formas& formas) {
    const auto desnudo = [](const pb::Type* t) -> const pb::Type* {
        while (t != nullptr && (t->kind() == pb::POINTER || t->kind() == pb::NULLABLE)) {
            t = t->has_inner() ? &t->inner() : nullptr;
        }
        return t != nullptr && t->kind() == pb::NOMINAL ? t : nullptr;
    };
    if (e.type_id() != 0) return desnudo(Formas::tipo_en(m, e.type_id()));
    if (e.node_case() == pb::Expr::kIdentifier) {
        const std::string& nombre = e.identifier().name();
        for (const hir::Slot& s : f.slots) {
            if (s.name != nombre) continue;
            if (const pb::Type* t = desnudo(Formas::tipo_en(m, s.type_id))) return t;
        }
        for (const pb::Decl& d : m.items()) {
            if (d.node_case() == pb::Decl::kStatement &&
                d.statement().node_case() == pb::Stmt::kVarDecl &&
                d.statement().var_decl().name() == nombre) {
                return desnudo(Formas::tipo_en(m, d.statement().var_decl().type_id()));
            }
        }
        return nullptr;
    }
    if (e.node_case() == pb::Expr::kMember) {
        const pb::Type* base = tipo_del_objeto(e.member().obj(), f, m, formas);
        if (base == nullptr) return nullptr;
        const Formas::Declaracion d = formas.declaracion(base->name());
        if (d.estructura == nullptr) return nullptr;
        for (const pb::Field& campo : d.estructura->fields()) {
            if (campo.name() == e.member().member()) {
                return desnudo(Formas::tipo_en(*d.modulo, campo.type_id()));
            }
        }
    }
    return nullptr;
}

Program lower(const hir::Image& image, const hir::Program& resolved) {
    Program program;
    // VM002: un enum GENERICO ('enum Res<T, E> { Ok(T), Err(E) }') lleva
    // payloads de tipo 'T' que la VM no sustituye (el ancho, la destruccion y
    // el texto saldrian del 'T' sin ligar). Se rechaza donde se declara, en
    // cualquier unidad cargada.
    {
        std::vector<const hir::Unit*> todas;
        for (const std::unique_ptr<hir::Unit>& u : image.units()) todas.push_back(u.get());
        todas.push_back(&image.main());
        for (const hir::Unit* unidad : todas) {
            for (const pb::Decl& d : unidad->module().items()) {
                if (d.node_case() != pb::Decl::kEnumDecl ||
                    d.enum_decl().type_params_size() == 0) {
                    continue;
                }
                program.unsupported.push_back(Unsupported{
                    option_message(unidad->module().source_file(),
                                   "declara el enum generico '" +
                                       d.enum_decl().name() + "'"),
                    d.ln(), d.col()});
            }
        }
    }
    Formas formas(image, program);
    Instancias instancias(image, resolved, program, formas);
    program.entry = resolved.entry;
    recoger_globales(image, resolved, program, formas);
    // los campos escalares tomados por direccion, ANTES de calcular ninguna
    // forma: la forma de su struct los cuenta como propios
    for (const hir::Function& f : resolved.functions) {
        if (f.direcciones_de_campo.empty()) continue;
        const pb::Module& m = modulo_de(image, f.unit);
        for (const pb::Expr* acceso : f.direcciones_de_campo) {
            const pb::Type* t = tipo_del_objeto(acceso->member().obj(), f, m, formas);
            if (t == nullptr) continue;
            const Formas::Declaracion d = formas.declaracion(t->name());
            if (d.estructura == nullptr) continue;
            for (int i = 0; i < d.estructura->fields_size(); ++i) {
                if (d.estructura->fields(i).name() != acceso->member().member()) continue;
                const pb::Type* campo = Formas::tipo_en(*d.modulo, d.estructura->fields(i).type_id());
                if (campo != nullptr && (es_escalar(*campo) || campo->kind() == pb::STR)) {
                    formas.marcar_celda(d.estructura, i);
                }
            }
        }
    }

    for (const hir::Function& origen : resolved.functions) {
        Function fn;
        fn.unit = origen.unit;
        fn.name = origen.name;
        fn.prototype = origen.prototype;
        program.index.emplace(hir::Program::key(fn.unit, fn.name),
                              program.functions.size());
        program.functions.push_back(std::move(fn));
    }

    // Las sentencias de nivel de MODULO -> una funcion sintetica que la VM
    // corre antes de la entrada. Librerias primero y el main al final: el
    // MISMO orden que el interprete, porque una global puede depender de otra
    // de otra unidad.
    //
    // Sin esto las globales existian pero nadie las inicializaba: 'const int
    // DOBLE = BASE * 2' valia cero.
    {
        Function init;
        init.name = "__module_init";
        init.result = Type::Void;
        program.init = static_cast<int>(program.functions.size());
        program.functions.push_back(std::move(init));
    }

    for (std::size_t i = 0; i < resolved.functions.size(); ++i) {
        const hir::Function& origen = resolved.functions[i];
        if (origen.decl == nullptr || origen.prototype) continue;
        Function& destino = program.functions[i];
        // El pool de tipos es el de la UNIDAD de la funcion: un 'type_id' no
        // significa lo mismo en dos unidades distintas.
        const pb::Module& module = modulo_de(image, origen.unit);
        Lowering lowering(module, resolved, destino, program, image, origen.unit,
                          formas, instancias);
        if (!lowering.run(*origen.decl, origen.slots, origen.line,
                          origen.col, origen.direcciones)) {
            destino.blocks.clear();
        }
        instancias.volcar();
    }

    if (program.init >= 0) {
        Function& init = program.functions[
            static_cast<std::size_t>(program.init)];
        std::vector<const hir::Unit*> unidades;
        for (const std::unique_ptr<hir::Unit>& u : image.units()) {
            unidades.push_back(u.get());
        }
        unidades.push_back(&image.main());
        bool ok = true;
        for (const hir::Unit* unidad : unidades) {
            Lowering lowering(unidad->module(), resolved, init, program, image,
                              unidad == &image.main() ? std::string() : unidad->alias(),
                              formas, instancias);
            if (!lowering.nivel_de_modulo(unidad->module())) ok = false;
            if (unidad == unidades.back()) lowering.cerrar_inicializacion();
        }
        if (!ok) init.blocks.clear();
        instancias.volcar();
    }

    // Las INSTANCIAS de los genericos, hasta que no quede ninguna pedida:
    // bajar una puede pedir otras ('dynamic<C>' llama a 'reserve<C>').
    const auto bajar_instancias = [&]() {
        while (instancias.hay_pendientes()) {
            const Instancias::Pendiente p = instancias.siguiente();
            const hir::Function& origen = resolved.functions[p.base];
            Function& destino = program.functions[p.indice];
            destino.prototype = false;
            const pb::Module& module = modulo_de(image, origen.unit);
            Lowering lowering(module, resolved, destino, program, image, origen.unit,
                              formas, instancias, &p.sustitucion);
            if (!lowering.run(*origen.decl, origen.slots, origen.line, origen.col,
                              origen.direcciones)) {
                destino.blocks.clear();
            }
            instancias.volcar();
        }
    };
    bajar_instancias();
    // Cada FORMA sabe su '__free__': la instancia para su tipo concreto
    // ('Caja<R>' corre el '__free__' de 'Caja' instanciado con 'R'). Lo usa
    // 'Destruir'. Pedir una instancia puede bajar funciones que crean formas
    // nuevas: hasta que no quede ninguna sin mirar.
    for (std::size_t hecha = 0;;) {
        for (; hecha < program.layouts.size(); ++hecha) {
            pb::Type tipo;
            if (!formas.tipo_de_forma(hecha, tipo) || tipo.kind() != pb::NOMINAL) continue;
            const int base = destructor_de(image, resolved, tipo.name());
            if (base >= 0) {
                program.layouts[hecha].destructor = instancias.para(base, {&tipo}, nullptr);
            }
        }
        instancias.volcar();
        if (!instancias.hay_pendientes()) break;
        bajar_instancias();
    }
    // Todo PROTOTIPO de la imagen es una primitiva, aunque nadie lo llame:
    // '#extern cpp' dice de cada uno si se liga o por que no, como el
    // interprete (que los recorre todos al ligar).
    for (const hir::Function& f : resolved.functions) {
        if (!f.prototype || f.decl == nullptr) continue;
        if (std::find(program.hosts.begin(), program.hosts.end(), f.name) != program.hosts.end()) {
            continue;
        }
        program.hosts.push_back(f.name);
        program.firmas_host.push_back(firma_de_prototipo(image, f));
    }
    return program;
}

void write_mir(const Program& program, std::ostream& out) {
    out << "MIR — " << program.functions.size() << " funciones, entrada: "
        << (program.entry < 0
                ? std::string("(ninguna)")
                : program.functions[static_cast<std::size_t>(program.entry)].name)
        << "\n";

    if (!program.globals.empty()) {
        out << "\nglobales\n";
        for (std::size_t i = 0; i < program.globals.size(); ++i) {
            out << "  g" << i << " " << to_string(program.globals[i].type)
                << " " << program.globals[i].name << "\n";
        }
    }
    if (!program.strings.empty()) {
        out << "\ncadenas\n";
        for (std::size_t i = 0; i < program.strings.size(); ++i) {
            out << "  s" << i << " \"" << program.strings[i] << "\"\n";
        }
    }
    if (!program.hosts.empty()) {
        out << "\nhost   (lo aporta quien ejecuta)\n";
        for (std::size_t i = 0; i < program.hosts.size(); ++i) {
            out << "  h" << i << " " << program.hosts[i] << "\n";
        }
    }

    for (const Function& fn : program.functions) {
        out << "\nfn " << hir::Program::key(fn.unit, fn.name) << " -> "
            << to_string(fn.result);
        if (fn.prototype) out << "   (prototipo)";
        else if (fn.blocks.empty()) out << "   (sin bajar)";
        out << "\n";
        for (std::size_t i = 0; i < fn.slots.size(); ++i) {
            out << "  slot " << i << " " << to_string(fn.slots[i]);
            if (i < fn.slot_names.size() && !fn.slot_names[i].empty()) {
                out << "  " << fn.slot_names[i];
            }
            out << (i < fn.params ? "  (param)" : "") << "\n";
        }
        for (std::size_t b = 0; b < fn.blocks.size(); ++b) {
            const Block& bloque = fn.blocks[b];
            out << "  bb" << b << ":\n";
            for (const Inst& inst : bloque.insts) {
                out << "    ";
                if (inst.dst != kNoReg) out << "r" << inst.dst << " = ";
                out << to_string(inst.op);
                switch (inst.op) {
                    case Op::ConstI: out << " " << inst.imm; break;
                    case Op::ConstF: out << " " << inst.fimm; break;
                    case Op::LoadLocal:
                    case Op::Borrow:
                        out << " slot" << inst.slot;
                        break;
                    case Op::MarkMoved:
                        out << " slot" << inst.slot;
                        if (inst.libera) out << "  (free)";
                        if (inst.imm >= 0) out << "  (apaga slot" << inst.imm << ")";
                        break;
                    case Op::StoreLocal:
                        out << " slot" << inst.slot << ", r" << inst.a;
                        break;
                    case Op::ConstStr: out << " s" << inst.imm; break;
                    case Op::LoadGlobal: out << " g" << inst.slot; break;
                    case Op::StoreGlobal:
                        out << " g" << inst.slot << ", r" << inst.a;
                        break;
                    case Op::Alloc:
                        out << " " << inst.imm << " campos";
                        if (inst.layout >= 0) {
                            out << "  (" << program.layouts[
                                static_cast<std::size_t>(inst.layout)].nombre << ")";
                        }
                        break;
                    case Op::NarrowI:
                    case Op::NarrowF:
                        out << " r" << inst.a << ", " << inst.imm << " bits";
                        break;
                    case Op::GetField:
                        out << " r" << inst.a << "[" << inst.imm << "]";
                        break;
                    case Op::SetField:
                        out << " r" << inst.a << "[" << inst.imm << "], r"
                            << inst.b;
                        break;
                    case Op::CallHost:
                        out << " h" << inst.func << "(";
                        for (std::size_t k = 0; k < inst.args.size(); ++k) {
                            if (k > 0) out << ", ";
                            out << "r" << inst.args[k];
                        }
                        out << ")";
                        if (inst.layout >= 0) {
                            out << "  (celdas " << program.layouts[
                                static_cast<std::size_t>(inst.layout)].nombre << ")";
                        }
                        break;
                    case Op::Call:
                        out << " #" << inst.func << "(";
                        for (std::size_t k = 0; k < inst.args.size(); ++k) {
                            if (k > 0) out << ", ";
                            out << "r" << inst.args[k];
                        }
                        out << ")";
                        if (inst.destructor) out << "  (destructor)";
                        break;
                    default:
                        if (inst.a != kNoReg) out << " r" << inst.a;
                        if (inst.b != kNoReg) out << ", r" << inst.b;
                        break;
                }
                out << "\n";
            }
            out << "    " << to_string(bloque.term);
            switch (bloque.term) {
                case Term::Jump: out << " bb" << bloque.target; break;
                case Term::Branch:
                    out << " r" << bloque.cond << " ? bb" << bloque.target
                        << " : bb" << bloque.otherwise;
                    break;
                case Term::Return:
                    if (bloque.has_value) out << " r" << bloque.value;
                    break;
                case Term::Throw:
                    out << " r" << bloque.value;
                    if (bloque.tag >= 0 &&
                        bloque.tag < static_cast<int>(program.tags.size())) {
                        out << " : " << program.tags[bloque.tag];
                    } else {
                        out << " (relanza)";
                    }
                    break;
                case Term::Unreachable: break;
            }
            // la arista de excepcion, que es la que no se ve en el orden de
            // los bloques
            if (bloque.handler >= 0) out << "   [lanza -> bb" << bloque.handler << "]";
            out << "\n";
        }
    }

    out << "\n" << program.unsupported.size()
        << " construccion(es) sin bajar\n";
    for (const Unsupported& fallo : program.unsupported) {
        out << "  " << fallo.line << ":" << fallo.col << "  " << fallo.what
            << "\n";
    }
}

}  // namespace suriax::mir

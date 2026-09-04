#include "suriax/hir/view.hpp"
#include "suriax/mir/mir.hpp"

#include <memory>
#include <utility>

namespace suriax::mir {
namespace {

// TypeKind del esquema -> tipo del MIR. Solo importa el ANCHO: 'bool', 'char'
// y un 'enum' sin payload son enteros en la maquina, y la distincion del
// lenguaje ya la verifico el frontend.
bool tipo_de(const pb::Module& module, std::uint32_t type_id, Type& out) {
    if (type_id >= static_cast<std::uint32_t>(module.types_size())) {
        out = Type::I64;
        return false;
    }
    switch (module.types(static_cast<int>(type_id)).kind()) {
        case pb::VOID: out = Type::Void; return true;
        case pb::BOOL:
        case pb::INT:
        case pb::CHAR:
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
        default:
            out = Type::I64;
            return false;
    }
}

// Baja el cuerpo de UNA funcion. Vive en una clase porque el lowering lleva
// estado —el bloque en curso, el siguiente registro, los bucles abiertos— y
// pasarlo por parametro a cada metodo seria escribirlo quince veces.
class Lowering {
public:
    Lowering(const pb::Module& module, const hir::Program& resolved,
             Function& fn, Program& program, const hir::Image& image)
        : module_(module), resolved_(resolved), fn_(fn), program_(program),
          image_(image), fallos_(program.unsupported) {}

    // Devuelve false si algo no se pudo bajar: la funcion queda sin bloques
    // en vez de a medias, que es lo unico honesto — un cuerpo incompleto se
    // ejecutaria y daria otro programa.
    bool run(const pb::FunctionDecl& decl,
             const std::vector<hir::Slot>& slots,
             std::uint32_t ln, std::uint32_t col) {
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
            if (slot.parameter) fn_.params++;
            nombres_.emplace(slot.name,
                             static_cast<std::uint32_t>(fn_.slots.size() - 1));
            tipos_.emplace(slot.name, slot.type_id);
        }
        // Una BANDERA por local destruible. Se crean aqui, con el resto de
        // los slots, porque un slot que naciera a mitad del lowering
        // invalidaria los indices ya emitidos.
        std::vector<std::string> destruibles;
        recoger_destruibles(decl.body(), destruibles);
        for (const std::string& nombre : destruibles) {
            if (nombres_.find(nombre) == nombres_.end()) continue;
            if (banderas_.count(nombre) != 0) continue;
            fn_.slots.push_back(Type::I64);
            fn_.slot_names.push_back("<vivo:" + nombre + ">");
            banderas_.emplace(
                nombre, static_cast<std::uint32_t>(fn_.slots.size() - 1));
        }

        if (!tipo_de(module_, decl.return_type_id(), fn_.result)) {
            fallo("el retorno de '" + decl.name() + "' es de tipo " +
                      notacion(decl.return_type_id()) + " y el MIR no lo "
                      "representa todavia" + porque(decl.return_type_id()),
                  ln, col);
            return false;
        }

        actual_ = nuevo_bloque();
        if (!bloque(decl.body())) return false;
        // Un cuerpo que se acaba sin 'return' cierra devolviendo nada. El
        // frontend ya rechaza que falte un valor donde hace falta (RT017 lo
        // caza en ejecucion); aqui solo hay que dejar el grafo cerrado.
        if (fn_.blocks[actual_].term == Term::Unreachable) {
            fn_.blocks[actual_].term = Term::Return;
            fn_.blocks[actual_].has_value = false;
        }
        return true;
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
            if (!stmt.var_decl().has_value()) continue;
            const int g = global(stmt.var_decl().name());
            if (g < 0) continue;
            Reg valor = kNoReg;
            if (!expresion(stmt.var_decl().value(), valor, false)) return false;
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
        fn_.blocks[actual_].insts.push_back(std::move(inst));
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
        for (const pb::Stmt& s : b.statements()) {
            if (!sentencia(s)) return false;
        }
        // La salida NORMAL del bloque. Las otras (return, break, continue)
        // destruyen por su cuenta antes de saltar: en un CFG cada arista que
        // abandona el ambito tiene que pasar por sus destructores, y un drop
        // que solo corriera al caer por el final seria una fuga en cuanto
        // hubiera un 'return' temprano.
        const bool ok = destruir(b);
        ambitos_.pop_back();
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
        return static_cast<int>(program_.tags.size() - 1);
    }

    int etiqueta_de_id(std::uint32_t id) {
        if (id >= static_cast<std::uint32_t>(module_.types_size())) return -1;
        return etiqueta(module_.types(static_cast<int>(id)));
    }

    bool lanzar(const pb::Stmt& s) {
        Reg valor = kNoReg;
        if (!expresion(s.throw_stmt().value(), valor, false)) return false;
        if (cerrado()) return true;
        Block& b = bloque_actual();
        b.term = Term::Throw;
        b.value = valor;
        b.has_value = true;
        b.tag = etiqueta_de_id(tipo_id_de(s.throw_stmt().value()));
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
        const bool ok = bloque(nodo.try_block());
        protegido_ = previo;
        if (!ok) return false;
        saltar(fin);

        // el pad: decide QUE rama atrapa, comparando etiquetas
        actual_ = pad;
        Reg etiqueta_viva = nuevo_reg();
        Inst carga;
        carga.op = Op::LoadLocal;
        carga.dst = etiqueta_viva;
        carga.slot = static_cast<std::uint32_t>(fn_.tag_slot);
        emitir(std::move(carga));

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
            const std::uint32_t slot = slot_nuevo(Type::I64, rama.name());
            nombres_[rama.name()] = slot;
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
            if (!bloque(rama.block())) return false;
            if (tapaba) nombres_[rama.name()] = previo_slot;
            else nombres_.erase(rama.name());
            saltar(fin);
            actual_ = siguiente;
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
        const auto bandera = banderas_.find(base);
        if (bandera == banderas_.end()) return true;  // no vive en este marco

        int destino = -1;
        if (!funcion_del_hook(d.hook(), destino)) {
            // el hook no esta ligado: el frontend ya lo dijo, y bajar una
            // llamada a nada seria peor que no bajarla.
            return true;
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
        for (int i = 1; i < d.path_size(); ++i) {
            const pb::Type* tipo = nominal_de(tipos_.at(base));
            const int indice = tipo == nullptr
                ? -1 : orden_del_campo(tipo->name(), d.path(i));
            if (indice < 0) return true;
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

        Inst llamar;
        llamar.op = Op::Call;
        llamar.func = destino;
        llamar.args.push_back(valor);
        llamar.synthetic = true;
        emitir(std::move(llamar));
        apagar_bandera(bandera->second);
        saltar(sigue);
        actual_ = sigue;
        return true;
    }

    // Las destrucciones de los ambitos abiertos, de dentro hacia fuera, hasta
    // 'hasta' sin incluirlo. Es lo que corre una salida ANTICIPADA.
    bool destruir_hasta(std::size_t hasta) {
        for (std::size_t i = ambitos_.size(); i > hasta; --i) {
            if (!destruir(*ambitos_[i - 1])) return false;
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
            // valor sobre el que actua.
            const pb::FunctionDecl* decl = resolved_.functions[i].decl;
            if (decl == nullptr || decl->params_size() == 0) continue;
            const pb::Type* dueno = nominal_de(
                decl->params(0).type_id());
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

    bool sentencia(const pb::Stmt& s) {
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
        const auto slot = nombres_.find(v.name());
        if (slot == nombres_.end()) {
            fallo("la variable '" + v.name() + "' no tiene slot", s.ln(), s.col());
            return false;
        }
        Reg valor = kNoReg;
        if (v.has_value()) {
            if (!expresion(v.value(), valor, false)) return false;
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
        Inst store;
        store.op = Op::StoreLocal;
        store.slot = slot->second;
        store.a = valor;
        store.line = s.ln();
        store.col = s.col();
        emitir(std::move(store));
        // desde aqui el local POSEE algo: su destructor tiene que correr
        const auto bandera = banderas_.find(v.name());
        if (bandera != banderas_.end()) encender_bandera(bandera->second);
        return true;
    }

    // 'move x': el valor cambia de dueno, asi que este ambito deja de
    // destruirlo. En ejecucion no mueve NADA —el valor ya esta donde esta—;
    // lo unico que ocurre es que la bandera se apaga. Que la lectura ilegal
    // posterior sea un error lo decide el frontend, no la VM.
    bool mover(const pb::Expr& objetivo) {
        if (objetivo.node_case() != pb::Expr::kIdentifier) return true;
        const auto slot = nombres_.find(objetivo.identifier().name());
        if (slot == nombres_.end()) return true;
        const auto bandera = banderas_.find(objetivo.identifier().name());
        Inst marca;
        marca.op = Op::MarkMoved;
        marca.slot = slot->second;
        marca.imm = bandera == banderas_.end()
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
        if (nodo.hook().owner_type().empty() ||
            !funcion_del_hook(nodo.hook(), destino)) {
            // sin '__free__' ligado 'free' solo invalida: no hay destructor
            // que llamar, y llamar a nada no es lo mismo que no llamar.
            return mover(nodo.target());
        }
        Inst llamar;
        llamar.op = Op::Call;
        llamar.func = destino;
        llamar.args.push_back(valor);
        llamar.line = s.ln();
        llamar.col = s.col();
        emitir(std::move(llamar));
        return mover(nodo.target());
    }

    bool retorno(const pb::Stmt& s) {
        Reg valor = kNoReg;
        bool trae = s.return_stmt().has_value();
        if (trae && !expresion(s.return_stmt().value(), valor, false)) {
            return false;
        }
        // los ambitos abiertos mueren ANTES de devolver: el valor ya esta
        // calculado, asi que destruir no se lo lleva por delante.
        if (!destruir_hasta(0)) return false;
        if (cerrado()) return true;
        Block& b = bloque_actual();
        b.term = Term::Return;
        b.value = valor;
        b.has_value = trae;
        return true;
    }

    bool condicional(const pb::IfStmt& nodo) {
        Reg cond = kNoReg;
        if (!expresion(nodo.condition(), cond, false)) return false;

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
        if (!expresion(s.while_stmt().condition(), cond, false)) return false;
        ramificar(cond, cuerpo, salida);

        actual_ = cuerpo;
        bucles_.push_back({cabecera, salida, ambitos_.size()});
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
        Reg sujeto = kNoReg;
        if (!expresion(nodo.subject(), sujeto, false)) return false;
        const std::uint32_t slot = slot_nuevo(
            es_flotante(nodo.subject()) ? Type::F64 : Type::I64, "<sujeto>");
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
            std::vector<std::string> tapados;
            if (suma != nullptr &&
                arm.pattern().node_case() == pb::Expr::kCall) {
                const pb::Call& patron = arm.pattern().call();
                for (int i = 0; i < patron.args_size(); ++i) {
                    if (patron.args(i).node_case() !=
                        pb::Expr::kIdentifier) {
                        continue;
                    }
                    const std::string& nombre =
                        patron.args(i).identifier().name();
                    if (nombres_.count(nombre) == 0) tapados.push_back(nombre);
                    const std::uint32_t destino =
                        slot_nuevo(Type::I64, nombre);
                    nombres_[nombre] = destino;
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
            for (const std::string& nombre : tapados) nombres_.erase(nombre);
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
                return literal_struct(e, dst);
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
            // un 'char' es UN code point: su valor es ese entero.
            inst.op = Op::ConstI;
            inst.imm = lit.str_value().empty()
                           ? 0
                           : static_cast<std::int64_t>(
                                 static_cast<unsigned char>(lit.str_value()[0]));
        } else if (lit.kind() == "float") {
            inst.op = Op::ConstF;
            inst.fimm = lit.float_value();
        } else if (lit.kind() == "str") {
            // una cadena constante es el INDICE de su constante: cabe en un
            // registro y se compara como un entero.
            inst.op = Op::ConstStr;
            inst.imm = interna(lit.str_value());
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

        Reg izq = kNoReg;
        Reg der = kNoReg;
        if (!expresion(nodo.left(), izq, false)) return false;
        if (!expresion(nodo.right(), der, false)) return false;

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
        else if (cadena) {
            fallo("el operador '" + op + "' entre cadenas no baja al MIR",
                  e.ln(), e.col());
            return false;
        }
        else if (op == "+") codigo = flotante ? Op::AddF : Op::AddI;
        else if (op == "-") codigo = flotante ? Op::SubF : Op::SubI;
        else if (op == "*") codigo = flotante ? Op::MulF : Op::MulI;
        else if (op == "/") codigo = flotante ? Op::DivF : Op::DivI;
        else if (op == "%") { if (flotante) { fallo("'%' entre flotantes no baja al MIR", e.ln(), e.col()); return false; } codigo = Op::RemI; }
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
        if (!expresion(nodo.right(), der, false)) return false;
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

    bool unaria(const pb::Expr& e, Reg& dst) {
        const pb::UnaryOp& nodo = e.unary();
        Reg operando = kNoReg;
        if (!expresion(nodo.operand(), operando, false)) return false;
        Op codigo;
        if (nodo.op() == "not" || nodo.op() == "!") codigo = Op::Not;
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
        if (slot != nombres_.end()) {
            if (!expresion(nodo.value(), valor, false)) return false;
            guardar(slot->second, valor, e);
            dst = valor;
            return true;
        }
        const int g = global(nombre);
        if (g < 0) {
            fallo("'" + nombre + "' no esta en alcance", e.ln(), e.col());
            return false;
        }
        if (!expresion(nodo.value(), valor, false)) return false;
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
        if (nodo.has_type()) {
            switch (nodo.type().kind()) {
                case pb::FLOAT: destino = Type::F64; break;
                case pb::INT: case pb::CHAR: case pb::BOOL:
                    destino = Type::I64; break;
                case pb::NOMINAL:
                    // hacia un ENUM sin payload la conversion no transforma
                    // nada: el valor ya es el entero.
                    destino = Type::I64;
                    break;
                default:
                    fallo("un 'cast' hacia ese tipo no baja al MIR todavia",
                          e.ln(), e.col());
                    return false;
            }
        }
        Reg valor = kNoReg;
        if (!expresion(nodo.value(), valor, false)) return false;
        const bool origen_flotante = es_flotante(nodo.value());
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

    // El tipo escrito como se lee, para un diagnostico. Un mensaje que solo
    // diga "un tipo que no represento" no le sirve a quien tiene que decidir
    // si eso importa.
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
                    return stmt.var_decl().type_id();
                }
            }
        }
        return 0;
    }

    // El tipo con NOMBRE al que se llega desde 'id', atravesando los punteros
    // que haya por medio. 'nullptr' si no se llega a ninguno.
    const pb::Type* nominal_de(std::uint32_t id) const {
        if (id >= static_cast<std::uint32_t>(module_.types_size())) {
            return nullptr;
        }
        const pb::Type* tipo = &module_.types(static_cast<int>(id));
        for (int i = 0; i < 8 && tipo != nullptr &&
                        (tipo->kind() == pb::POINTER ||
                         tipo->kind() == pb::NULLABLE); ++i) {
            tipo = tipo->has_inner() ? &tipo->inner() : nullptr;
        }
        if (tipo == nullptr || tipo->kind() != pb::NOMINAL) return nullptr;
        return tipo;
    }

    // El indice del campo que nombra un 'MemberAccess', segun el struct que
    // declara el tipo del objeto.
    bool campo_de(const pb::Expr& acceso, int& indice) {
        const std::uint32_t id = tipo_id_de(acceso.member().obj());
        const pb::Type* tipo = nominal_de(id);
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
        if (nominal_de(tipo_id_de(operando)) == nullptr) {
            fallo("'&' solo baja al MIR sobre un valor de tipo con nombre: el "
                  "de un escalar no vive en el monton y no hay a que apuntar",
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
        dst = nuevo_reg();
        Inst alloc;
        alloc.op = Op::Alloc;
        alloc.dst = dst;
        alloc.imm = campos;
        alloc.line = e.ln();
        alloc.col = e.col();
        emitir(std::move(alloc));
        for (int i = 0; i < campos; ++i) {
            Reg valor = kNoReg;
            if (!expresion(nodo.values(i), valor, false)) return false;
            // el literal escribe los campos EN EL ORDEN DECLARADO, no en el
            // que se escribieron: 'P{ y: 2, x: 1 }' tiene que dar lo mismo.
            const int orden = i < nodo.field_names_size()
                ? orden_del_campo(nodo.type_name(), nodo.field_names(i))
                : i;
            Inst set;
            set.op = Op::SetField;
            set.a = dst;
            set.b = valor;
            set.imm = orden < 0 ? i : orden;
            set.line = e.ln();
            set.col = e.col();
            emitir(std::move(set));
        }
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
        const auto mirar = [&](const pb::Module& m) -> const pb::EnumDecl* {
            for (const pb::Decl& decl : m.items()) {
                if (decl.node_case() != pb::Decl::kEnumDecl) continue;
                if (decl.enum_decl().name() != nombre) continue;
                for (const pb::EnumItem& it : decl.enum_decl().items()) {
                    if (it.payload_type_ids_size() > 0) {
                        return &decl.enum_decl();
                    }
                }
                return nullptr;
            }
            return nullptr;
        };
        if (const pb::EnumDecl* d = mirar(module_)) return d;
        for (const std::unique_ptr<hir::Unit>& u : image_.units()) {
            if (const pb::EnumDecl* d = mirar(u->module())) return d;
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
        return true;
    }

    // El enum y la variante que nombra 'E.X', si es de un enum suma.
    const pb::EnumDecl* suma_de_miembro(const pb::Expr& acceso,
                                        std::string& item) const {
        if (acceso.node_case() != pb::Expr::kMember) return nullptr;
        if (acceso.member().obj().node_case() != pb::Expr::kIdentifier) {
            return nullptr;
        }
        item = acceso.member().member();
        return enum_suma_de(acceso.member().obj().identifier().name());
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
        if (mirar(module_)) return true;
        for (const std::unique_ptr<hir::Unit>& u : image_.units()) {
            if (mirar(u->module())) return true;
        }
        return false;
    }

    bool llamada(const pb::Expr& e, Reg& dst, bool descartar) {
        // A que llama esto ya lo decidio 'hir/resolve': aqui no se vuelve a
        // buscar. Esa es la razon de que resolve exista antes que el MIR.
        const hir::Call* sitio = sitio_de(e.ln(), e.col());
        if (sitio == nullptr) {
            fallo("esta llamada no se resolvio", e.ln(), e.col());
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
                static_cast<std::size_t>(sitio->index)].name);
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
                payload.push_back(reg);
            }
            return variante(*en, item, payload, e, dst);
        } else {
            fallo(std::string("esta llamada se resolvio a '") +
                      hir::to_string(sitio->target) +
                      "', que el MIR no baja todavia", e.ln(), e.col());
            return false;
        }
        inst.line = e.ln();
        inst.col = e.col();
        // 'p.doble()' pasa 'p' de primer argumento: el receptor no viaja en
        // 'args', viaja en el callee.
        if (sitio->target == hir::CallTarget::Method) {
            Reg receptor = kNoReg;
            if (!expresion(e.call().callee().member().obj(), receptor, false)) {
                return false;
            }
            inst.args.push_back(receptor);
        }
        for (const pb::Expr& arg : e.call().args()) {
            Reg reg = kNoReg;
            if (!expresion(arg, reg, false)) return false;
            inst.args.push_back(reg);
        }
        if (!descartar) {
            dst = nuevo_reg();
            inst.dst = dst;
        }
        emitir(std::move(inst));
        return true;
    }

    // El codigo de 'ToStr' que le toca a un tipo, o -1 si escribirlo no esta
    // decidido (un enum se imprime por su NOMBRE en el interprete, y el MIR
    // ya no tiene el nombre: bajarlo daria el numero, que es otra cosa).
    int como_texto(std::uint32_t id) const {
        if (id >= static_cast<std::uint32_t>(module_.types_size())) return -1;
        switch (module_.types(static_cast<int>(id)).kind()) {
            case pb::INT: return 0;
            case pb::FLOAT: return 1;
            case pb::BOOL: return 2;
            case pb::CHAR: return 3;
            case pb::STR: return 4;
            default: return -1;
        }
    }

    // f"a{x}b": los trozos se van pegando de izquierda a derecha. El primero
    // no concatena con nada — arrancar de la cadena vacia costaria una
    // instruccion y una entrada de tabla por cada f-string.
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
                const int modo = como_texto(tipo_id_de(parte.expr()));
                if (modo < 0) {
                    fallo("el MIR no sabe escribir este valor dentro de un "
                          "f-string", parte.expr().ln(), parte.expr().col());
                    return false;
                }
                if (modo == 4) {
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
            fallo("'sizeof' solo baja si el tipo declara '__sizeof__'",
                  e.ln(), e.col());
            return false;
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
    const hir::Call* sitio_de(std::uint32_t ln, std::uint32_t col) const {
        for (const hir::Function& f : resolved_.functions) {
            for (const hir::Call& c : f.calls) {
                if (c.line == ln && c.col == col) return &c;
            }
        }
        return nullptr;
    }

    struct Bucle {
        BlockId cabecera;
        BlockId salida;
        //: cuantos ambitos habia abiertos al entrar: los de mas adentro son
        //: los que un 'break' o un 'continue' tiene que destruir
        std::size_t ambitos = 0;
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

    int host(const std::string& nombre) {
        for (std::size_t i = 0; i < program_.hosts.size(); ++i) {
            if (program_.hosts[i] == nombre) return static_cast<int>(i);
        }
        program_.hosts.push_back(nombre);
        return static_cast<int>(program_.hosts.size() - 1);
    }

    int global(const std::string& nombre) const {
        for (std::size_t i = 0; i < program_.globals.size(); ++i) {
            if (program_.globals[i].name == nombre) return static_cast<int>(i);
        }
        return -1;
    }

    const pb::Module& module_;
    const hir::Program& resolved_;
    Function& fn_;
    Program& program_;
    const hir::Image& image_;
    std::vector<Unsupported>& fallos_;
    std::unordered_map<std::string, std::uint32_t> nombres_;
    //: los bloques HIR abiertos, para saber que muere en una salida anticipada
    std::vector<const pb::Block*> ambitos_;
    //: el pad de aterrizaje activo (-1 = fuera de todo 'try')
    int protegido_ = -1;
    //: la bandera de vivo de cada local que alguien destruye
    std::unordered_map<std::string, std::uint32_t> banderas_;
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
        case Op::ConstStr: return "const.s";
        case Op::LoadGlobal: return "load.g";
        case Op::StoreGlobal: return "store.g";
        case Op::IntToFloat: return "i2f";
        case Op::FloatToInt: return "f2i";
        case Op::Alloc: return "alloc";
        case Op::GetField: return "get";
        case Op::SetField: return "set";
        case Op::Copy: return "copy";
        case Op::CallHost: return "call.host";
        case Op::GetIndex: return "get.idx";
        case Op::SetIndex: return "set.idx";
        case Op::LenStr: return "len.str";
        case Op::ConcatStr: return "concat.str";
        case Op::EqStr: return "eq.str";
        case Op::NeStr: return "ne.str";
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
void recoger_globales(const hir::Image& image, Program& program) {
    const auto de = [&](const pb::Module& m) {
        for (const pb::Decl& decl : m.items()) {
            if (decl.node_case() != pb::Decl::kStatement) continue;
            const pb::Stmt& stmt = decl.statement();
            if (stmt.node_case() != pb::Stmt::kVarDecl) continue;
            Type tipo = Type::I64;
            tipo_de(m, stmt.var_decl().type_id(), tipo);
            program.globals.push_back(Global{stmt.var_decl().name(), tipo});
        }
    };
    de(image.main().module());
    for (const std::unique_ptr<hir::Unit>& u : image.units()) de(u->module());
}

Program lower(const hir::Image& image, const hir::Program& resolved) {
    Program program;
    program.entry = resolved.entry;
    recoger_globales(image, program);

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
        Lowering lowering(module, resolved, destino, program, image);
        if (!lowering.run(*origen.decl, origen.slots, origen.line,
                          origen.col)) {
            destino.blocks.clear();
        }
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
            Lowering lowering(unidad->module(), resolved, init, program, image);
            if (!lowering.nivel_de_modulo(unidad->module())) ok = false;
            if (unidad == unidades.back()) lowering.cerrar_inicializacion();
        }
        if (!ok) init.blocks.clear();
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
                    case Op::Alloc: out << " " << inst.imm << " campos"; break;
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
                        break;
                    case Op::Call:
                        out << " #" << inst.func << "(";
                        for (std::size_t k = 0; k < inst.args.size(); ++k) {
                            if (k > 0) out << ", ";
                            out << "r" << inst.args[k];
                        }
                        out << ")";
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

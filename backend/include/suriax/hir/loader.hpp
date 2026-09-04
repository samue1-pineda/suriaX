// Lector del HIR en C++ — la ENTRADA del backend nativo.
//
// Es el paso 3 de 'V0/src/HIR/PROTOBUF_BRIDGE.md' secc. 4: un lector que
// valide 'schema_version', reconstruya la tabla de simbolos y recorra el
// arbol con un 'switch' exhaustivo por 'oneof'. Su proposito no es ejecutar
// nada — eso es del MIR y de la VM, que no existen todavia — sino CONGELAR
// el contrato de la frontera: mientras exista un consumidor C++ que lee
// todo lo que el emisor escribe, el HIR no puede derivar sin que se note.
//
// Espejo deliberado de 'runtime/interpreter/loader.py': mismas piezas
// (load_module / Unit / Image / load_image), mismos indices y la misma
// regla de resolucion de rutas. Dos lectores del mismo contrato que no se
// parecen son dos contratos.
//
// Sobre el modelo de objetos: este lector trabaja DIRECTAMENTE sobre los
// mensajes que genera protoc, sin materializar un AST paralelo en C++. Es
// lo que hacen los otros dos consumidores del HIR que ya existen (el
// interprete y 'pretty.py'); el backend web tiene su propio modelo solo
// porque escribio a mano el decodificador del wire format, cosa que aqui no
// hace falta. Un modelo paralelo seria una tercera definicion del mismo
// esquema que mantener sincronizada con '.proto'.
//
// Errores por CODIGO de estado, no por excepciones — misma convencion que
// 'runtime/logic_mem/include/mem_core.hpp': el lector lo enlazara la VM, y
// acoplar el ABI al runtime de excepciones no compra nada.
#pragma once

#include <cstdint>
#include <map>
#include <memory>
#include <string>
#include <unordered_map>
#include <utility>
#include <vector>

#include "hir.pb.h"

namespace suriax::hir {

namespace pb = ::suriax::hir::v0;

// Versiones de esquema que este lector sabe interpretar. Una version que no
// esta aqui se RECHAZA antes de tocar el contenido: interpretar bytes con
// un layout desconocido no es "casi correcto", es leer otra cosa.
//
// Tiene que moverse a la vez que 'runtime/interpreter/loader.py' y
// 'web/src/hir/decode.ts' — son los tres lectores vivos del contrato.
inline constexpr std::uint32_t kSupportedSchemaVersions[] = {2};

bool schema_supported(std::uint32_t version);

// Resultado de una carga. 'ok' falso trae el porque en 'error', ya redactado
// para un humano: que fallo, donde y que hacer.
struct LoadStatus {
    bool ok = true;
    std::string error;

    static LoadStatus failure(std::string message) {
        return LoadStatus{false, std::move(message)};
    }
};

// Clave de despacho de un hook. Desde HTIMS el vocabulario dejo de ser
// cerrado, asi que la identidad es la TERNA (dueno, clase, nombre) y no el
// par (dueno, clase) — 'hook_name' viaja vacio en todo hook del vocabulario
// fijo. Misma clave que 'runtime/interpreter/hook/dispatch.hook_key'.
struct HookKey {
    std::string owner;
    pb::HookKind kind = pb::HOOK_UNSPECIFIED;
    std::string name;

    bool operator==(const HookKey& other) const noexcept {
        return kind == other.kind && owner == other.owner && name == other.name;
    }
};

struct HookKeyHash {
    std::size_t operator()(const HookKey& key) const noexcept;
};

// Clave de la tabla de conversiones: el par (origen, destino) que la firma
// del '__cast__' ya lleva ('origen' = param_types[0], 'destino' = type). Se
// indexa por la identidad ESTRUCTURAL del tipo ('view.hpp::type_key'), la
// misma que usa el interprete — no por su notacion, que es para leer.
struct CastKey {
    std::string from;
    std::string to;

    bool operator==(const CastKey& other) const noexcept {
        return from == other.from && to == other.to;
    }
};

struct CastKeyHash {
    std::size_t operator()(const CastKey& key) const noexcept;
};

// Una unidad HIR cargada (el main o una '.libsrx') con sus indices locales.
//
// La unidad es DUENA de su 'Module': el arbol se recorre por referencia
// durante toda la vida de la imagen, asi que copiarlo por cada consulta
// seria copiar el programa entero.
class Unit {
public:
    Unit(std::string alias, std::string path, std::unique_ptr<pb::Module> module);

    const std::string& alias() const noexcept { return alias_; }
    const std::string& path() const noexcept { return path_; }
    const pb::Module& module() const noexcept { return *module_; }

    // nombre -> FunctionDecl. Un dunder tambien es invocable por nombre: un
    // dunder que no es hook reconocido es una funcion corriente.
    const pb::FunctionDecl* function(const std::string& name) const;
    // (nombre, linea) -> FunctionDecl: los overloads de '__cast__' comparten
    // nombre y solo se distinguen por su posicion, igual que en el
    // interprete.
    const pb::FunctionDecl* dunder(const std::string& name, std::uint32_t line) const;
    // enum -> {item -> valor}. Solo variantes UNIDAD: una variante con
    // payload no es un entero sino un constructor, y su aridad la da
    // 'payload_type_ids'.
    const std::unordered_map<std::string, std::int64_t>* enum_values(
        const std::string& name) const;
    // aridad de una variante con payload, o -1 si no es una.
    int variant_arity(const std::string& enum_name, const std::string& item) const;

    const std::vector<const pb::TestDecl*>& tests() const noexcept { return tests_; }

private:
    void index();

    std::string alias_;
    std::string path_;
    std::unique_ptr<pb::Module> module_;
    std::unordered_map<std::string, const pb::FunctionDecl*> functions_;
    std::map<std::pair<std::string, std::uint32_t>, const pb::FunctionDecl*> dunders_;
    std::unordered_map<std::string, std::unordered_map<std::string, std::int64_t>>
        enum_values_;
    std::unordered_map<std::string, std::unordered_map<std::string, int>> variants_;
    std::vector<const pb::TestDecl*> tests_;
};

// main + librerias ligadas: lo que el lowering a MIR recibira.
//
// Los indices se construyen UNA vez sobre todas las unidades, que es lo que
// convierte cada 'HookRef' del arbol en un lookup O(1) — la propiedad por la
// que los hooks viajan como referencia y no como Symbol embebido.
class Image {
public:
    const Unit& main() const noexcept { return *main_; }
    const std::vector<std::unique_ptr<Unit>>& units() const noexcept { return units_; }

    // resuelve un 'HookRef' del arbol contra la tabla de la imagen.
    const pb::Symbol* hook(const pb::HookRef& ref) const;
    // '__cast__' por par (origen -> destino), con las claves estructurales
    // que devuelve 'type_key'.
    const pb::Symbol* cast(const std::string& from, const std::string& to) const;
    // busca una funcion por nombre en el main y, si no esta, en las unidades.
    const pb::FunctionDecl* function(const std::string& name) const;

    std::size_t hook_count() const noexcept { return hooks_.size(); }
    std::size_t cast_count() const noexcept { return casts_.size(); }

    friend LoadStatus load_image(const std::string& main_path, Image& out);

private:
    void index();

    std::unique_ptr<Unit> main_;
    std::vector<std::unique_ptr<Unit>> units_;  // el main NO esta aqui
    std::unordered_map<HookKey, const pb::Symbol*, HookKeyHash> hooks_;
    std::unordered_map<CastKey, const pb::Symbol*, CastKeyHash> casts_;
};

// Lee 'path' y devuelve el Module validado.
//
// Fail-fast en dos puntos, en este orden: los bytes tienen que parsear como
// un Module, y la 'schema_version' tiene que estar soportada. Nunca se
// interpreta un artefacto cuya version no se conoce.
LoadStatus load_module(const std::string& path, std::unique_ptr<pb::Module>& out);

// Carga el '.phir' principal y TODAS las unidades que referencia,
// transitivamente y una sola vez por alias. Cada 'LibraryRef.phir' se
// resuelve RELATIVO al directorio del archivo que lo referencia — misma
// regla que 'loader.load_image', porque las unidades viajan juntas.
LoadStatus load_image(const std::string& main_path, Image& out);

}  // namespace suriax::hir

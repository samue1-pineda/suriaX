#include "suriax/hir/loader.hpp"

#include <algorithm>
#include <filesystem>
#include <fstream>
#include <sstream>
#include <unordered_set>

#include "suriax/hir/view.hpp"

namespace suriax::hir {
namespace {

namespace fs = std::filesystem;

std::string supported_versions_text() {
    std::ostringstream out;
    bool first = true;
    for (std::uint32_t version : kSupportedSchemaVersions) {
        if (!first) out << ", ";
        out << version;
        first = false;
    }
    return out.str();
}

void hash_combine(std::size_t& seed, std::size_t value) noexcept {
    seed ^= value + 0x9e3779b97f4a7c15ULL + (seed << 6) + (seed >> 2);
}

}  // namespace

bool schema_supported(std::uint32_t version) {
    for (std::uint32_t supported : kSupportedSchemaVersions) {
        if (supported == version) return true;
    }
    return false;
}

std::size_t HookKeyHash::operator()(const HookKey& key) const noexcept {
    std::size_t seed = std::hash<std::string>{}(key.owner);
    hash_combine(seed, std::hash<int>{}(static_cast<int>(key.kind)));
    hash_combine(seed, std::hash<std::string>{}(key.name));
    return seed;
}

std::size_t CastKeyHash::operator()(const CastKey& key) const noexcept {
    std::size_t seed = std::hash<std::string>{}(key.from);
    hash_combine(seed, std::hash<std::string>{}(key.to));
    return seed;
}

// -------------------------------------------------------------------------- //
// carga de una unidad
// -------------------------------------------------------------------------- //

LoadStatus load_module(const std::string& path, std::unique_ptr<pb::Module>& out) {
    std::ifstream file(path, std::ios::binary);
    if (!file) {
        return LoadStatus::failure("no se pudo leer '" + path + "'");
    }

    auto module = std::make_unique<pb::Module>();
    if (!module->ParseFromIstream(&file)) {
        return LoadStatus::failure(
            "'" + path + "' no contiene un Module HIR valido: los bytes no "
            "parsean como protobuf. Regeneralo con "
            "'python V0/main.py <fuente>.srcx --emit-hir'.");
    }

    // Fail-fast de esquema ANTES de mirar el contenido: un '.phir' de otra
    // version no es "casi correcto", es un artefacto cuyo significado cambio.
    if (!schema_supported(module->schema_version())) {
        return LoadStatus::failure(
            "schema_version " + std::to_string(module->schema_version()) +
            " no soportada por este lector (soportadas: " +
            supported_versions_text() +
            "). Regenera el .phir con un frontend compatible o actualiza el "
            "lector.");
    }

    out = std::move(module);
    return LoadStatus{};
}

// -------------------------------------------------------------------------- //
// Unit: indices locales de una unidad
// -------------------------------------------------------------------------- //

Unit::Unit(std::string alias, std::string path, std::unique_ptr<pb::Module> module)
    : alias_(std::move(alias)), path_(std::move(path)), module_(std::move(module)) {
    index();
}

void Unit::index() {
    for (const pb::Decl& decl : module_->items()) {
        switch (decl.node_case()) {
            case pb::Decl::kFunction: {
                const pb::FunctionDecl& fn = decl.function();
                functions_[fn.name()] = &fn;
                if (!fn.dunder().empty()) {
                    // ...y ademas resoluble como CUERPO de hook por (nombre,
                    // linea): es como se enlazan los HookRef, porque los
                    // overloads de '__cast__' comparten nombre.
                    dunders_[{fn.name(), decl.ln()}] = &fn;
                }
                break;
            }
            case pb::Decl::kTestDecl:
                tests_.push_back(&decl.test_decl());
                break;
            case pb::Decl::kEnumDecl: {
                const pb::EnumDecl& enum_decl = decl.enum_decl();
                auto& values = enum_values_[enum_decl.name()];
                auto& variants = variants_[enum_decl.name()];
                std::int64_t next = 0;
                for (const pb::EnumItem& item : enum_decl.items()) {
                    if (item.payload_type_ids_size() > 0) {
                        // variante con PAYLOAD: no es un entero sino algo que
                        // se invoca. La aridad la da el esquema, asi que el
                        // consumidor no consulta la declaracion otra vez.
                        variants[item.name()] = item.payload_type_ids_size();
                        continue;
                    }
                    if (item.has_value() &&
                        item.value().node_case() == pb::Expr::kLiteral) {
                        next = item.value().literal().int_value();
                    }
                    values[item.name()] = next;
                    ++next;
                }
                break;
            }
            default:
                break;  // el resto no necesita indice local
        }
    }
}

const pb::FunctionDecl* Unit::function(const std::string& name) const {
    auto it = functions_.find(name);
    return it == functions_.end() ? nullptr : it->second;
}

const pb::FunctionDecl* Unit::dunder(const std::string& name,
                                     std::uint32_t line) const {
    auto it = dunders_.find({name, line});
    return it == dunders_.end() ? nullptr : it->second;
}

const std::unordered_map<std::string, std::int64_t>* Unit::enum_values(
    const std::string& name) const {
    auto it = enum_values_.find(name);
    return it == enum_values_.end() ? nullptr : &it->second;
}

int Unit::variant_arity(const std::string& enum_name,
                        const std::string& item) const {
    auto enum_it = variants_.find(enum_name);
    if (enum_it == variants_.end()) return -1;
    auto item_it = enum_it->second.find(item);
    return item_it == enum_it->second.end() ? -1 : item_it->second;
}

// -------------------------------------------------------------------------- //
// Image: N unidades ligadas
// -------------------------------------------------------------------------- //

void Image::index() {
    auto index_unit = [this](const Unit& unit) {
        const pb::SymbolTable& symbols = unit.module().symbols();
        for (const pb::HookEntry& entry : symbols.hooks()) {
            hooks_[{entry.owner_type(), entry.kind(), entry.hook_name()}] =
                &entry.symbol();
        }
        // La clave del cast es DERIVABLE de la firma (origen =
        // param_types[0], destino = type): el esquema no la repite y cada
        // lector reconstruye su indice en O(n).
        for (const pb::Symbol& cast : symbols.casts()) {
            if (cast.param_types_size() == 0) continue;
            casts_[{type_key(cast.param_types(0)), type_key(cast.type())}] = &cast;
        }
    };

    index_unit(*main_);
    for (const auto& unit : units_) index_unit(*unit);
}

const pb::Symbol* Image::hook(const pb::HookRef& ref) const {
    auto it = hooks_.find({ref.owner_type(), ref.kind(), ref.hook_name()});
    return it == hooks_.end() ? nullptr : it->second;
}

const pb::Symbol* Image::cast(const std::string& from,
                              const std::string& to) const {
    auto it = casts_.find({from, to});
    return it == casts_.end() ? nullptr : it->second;
}

const pb::FunctionDecl* Image::function(const std::string& name) const {
    if (const pb::FunctionDecl* fn = main_->function(name)) return fn;
    for (const auto& unit : units_) {
        if (const pb::FunctionDecl* fn = unit->function(name)) return fn;
    }
    return nullptr;
}

LoadStatus load_image(const std::string& main_path, Image& out) {
    std::unique_ptr<pb::Module> main_module;
    if (LoadStatus status = load_module(main_path, main_module); !status.ok) {
        return status;
    }
    out.main_ = std::make_unique<Unit>("", main_path, std::move(main_module));
    out.units_.clear();

    // worklist con vistos por alias: una libreria compartida por dos
    // consumidores se carga UNA vez.
    std::unordered_set<std::string> seen;
    std::vector<std::pair<std::string, const pb::LibraryRef*>> pending;
    for (const pb::LibraryRef& ref : out.main_->module().libraries()) {
        pending.emplace_back(main_path, &ref);
    }

    while (!pending.empty()) {
        auto [base_path, ref] = pending.back();
        pending.pop_back();
        if (!seen.insert(ref->alias()).second) continue;

        // relativo al directorio del archivo que la referencia: las unidades
        // '.phir' viajan juntas, y esa es la regla que lo hace cierto.
        const fs::path unit_path =
            fs::absolute(fs::path(base_path)).parent_path() / ref->phir();
        if (!fs::is_regular_file(unit_path)) {
            return LoadStatus::failure(
                "la unidad '" + ref->alias() + "' referencia '" + ref->phir() +
                "' y no existe junto a '" +
                fs::path(base_path).filename().string() +
                "' — se emitio con --emit-hir? (las unidades .phir viajan "
                "juntas)");
        }

        std::unique_ptr<pb::Module> module;
        if (LoadStatus status = load_module(unit_path.string(), module);
            !status.ok) {
            return status;
        }
        auto unit = std::make_unique<Unit>(ref->alias(), unit_path.string(),
                                           std::move(module));
        for (const pb::LibraryRef& sub : unit->module().libraries()) {
            pending.emplace_back(unit_path.string(), &sub);
        }
        out.units_.push_back(std::move(unit));
    }

    out.index();
    return LoadStatus{};
}

}  // namespace suriax::hir

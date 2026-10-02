// suriax-hir — CLI del lector de HIR en C++.
//
// La forma de ver, desde el lado nativo, que le llego al backend. No ejecuta
// nada: el MIR y la VM no existen todavia. Lo que si hace es demostrar que
// este consumidor entiende el mismo '.phir' que los otros dos, y por eso sus
// dos vistas son byte-identicas a las de Python:
//
//   --pretty   ==  python V0/main.py <fuente> --emit-hir --hir-pretty
//   --summary  ==  python runtime/interpreter/main.py <archivo>.phir
//
// Compararlas es el diferencial ENTRE CONSUMIDORES de 'test/backend/test_backend_cpp_*.py'.

#include <cstdint>
#include <cstring>
#include <filesystem>
#include <memory>
#include <fstream>
#include <iostream>
#include <sstream>
#include <string>
#include <vector>

#include "suriax/hir/loader.hpp"
#include "suriax/hir/resolve.hpp"
#include "suriax/mir/externo.hpp"
#include "suriax/mir/mir.hpp"
#include "suriax/mir/verify.hpp"
#include "suriax/mir/vm.hpp"
#include "suriax/hir/view.hpp"

namespace {

// Un entero sin signo escrito entero (sin signo, sin espacios, sin sufijo).
bool leer_entero(const std::string& texto, std::uint64_t& n, std::string& error) {
    if (texto.empty() || texto.size() > 19) {
        error = "se esperaba un entero entre 0 y 10^19 ('" + texto + "')";
        return false;
    }
    n = 0;
    for (const char c : texto) {
        if (c < '0' || c > '9') {
            error = "se esperaba un entero, no '" + texto + "'";
            return false;
        }
        n = n * 10 + static_cast<std::uint64_t>(c - '0');
    }
    return true;
}

// Un tamano en bytes: un entero con un sufijo opcional K, M o G (potencias de
// 1024, como 'ulimit' y 'make'). '512M', '2G', '65536'.
bool leer_tamano(const std::string& texto, std::uint64_t& n, std::string& error) {
    std::string cifras = texto;
    std::uint64_t factor = 1;
    if (!cifras.empty()) {
        const char ultimo = cifras.back();
        if (ultimo == 'K' || ultimo == 'k') factor = 1024ULL;
        else if (ultimo == 'M' || ultimo == 'm') factor = 1024ULL * 1024;
        else if (ultimo == 'G' || ultimo == 'g') factor = 1024ULL * 1024 * 1024;
        if (factor != 1) cifras.pop_back();
    }
    if (!leer_entero(cifras, n, error) || cifras.size() > 12) {
        error = "se esperaba un tamano como 512M, 2G o 65536 (bytes), no '" + texto + "'";
        return false;
    }
    n *= factor;
    return true;
}

constexpr char kUsage[] =
    "uso: suriax-hir <archivo.phir> [opciones]\n"
    "\n"
    "Lee un .phir emitido por el frontend (python V0/main.py <fuente> "
    "--emit-hir),\n"
    "valida su esquema fail-fast y muestra que contiene.\n"
    "\n"
    "opciones:\n"
    "  --summary   resumen de la unidad: simbolos, hooks e items (por defecto)\n"
    "  --pretty    vista legible: una linea por sentencia, con tipos y posiciones\n"
    "  --link      liga las unidades referenciadas y reporta los indices\n"
    "  --verify    recorre el arbol entero y falla si hay un nodo sin handler\n"
    "  --resolve   RESUELVE la imagen: funciones con sus slots, a que se\n"
    "              resuelve cada llamada y que destruye cada bloque. Falla si\n"
    "              queda una llamada sin resolver. Liga la imagen\n"
    "  --mir       baja la imagen al MIR (registros + CFG explicito) y lo\n"
    "              imprime: una linea por instruccion, agrupadas por bloque,\n"
    "              seguido de la verificacion de propiedad y prestamos\n"
    "  --run       EJECUTA el MIR en la VM y devuelve lo que devuelva 'main'\n"
    "  --trace     con --run: escribe en stderr cada llamada y cada retorno\n"
    "              ([call] / [ret ]), para seguir la ejecucion a mano\n"
    "  --memoria   con --run: al terminar, escribe en stderr cuantos objetos\n"
    "              creo y libero la VM, cuantos quedaron vivos y el pico de\n"
    "              memoria del programa en bytes\n"
    "  --pasos <N> con --run: el limite de pasos de la VM (por defecto\n"
    "              100000000); 0 = sin limite. Pasarlo es RT010\n"
    "  --memoria-max <tam>\n"
    "              con --run: la memoria maxima del PROGRAMA (sus objetos,\n"
    "              bloques y cadenas), en bytes o con K/M/G (512M, 2G); 0 =\n"
    "              sin limite (el defecto). Pasarla es RT023\n"
    "  -- ARGS...  con --run: lo que sigue es del PROGRAMA\n"
    "              (sistema.proceso.argumento(i); el 0 es el .phir)\n"
    "  --quiet     con --run: solo lo que escribe el programa (sin la linea\n"
    "              '[vm] main() -> N'): es como la corre 'suri --run compiler'\n"
    "  --arg0 <nombre>\n"
    "              con --run: el argumento 0 del programa (por defecto, el .phir)\n"
    "  --check-mir baja la imagen al MIR y termina: 0 si lo cubre entero,\n"
    "              1 (y que falta) si no. Sin ejecutar nada\n"
    "  --extern <biblioteca>\n"
    "              con --run: liga los prototipos a esa biblioteca de C++ ya\n"
    "              construida. Sin ella, si el programa trae '#extern cpp',\n"
    "              se construye junto al .phir (extern/extern_cpp_vm.*) con\n"
    "              $CXX, g++ o clang++ y las banderas de SURIAX_CPP_FLAGS\n"
    "  --emit-cpp <archivo>\n"
    "              escribe los bloques '#extern cpp' del programa como una\n"
    "              unidad de traduccion de C++ (con '#line' al .srcx). Liga\n"
    "              la imagen: recoge tambien los de las librerias\n"
    "  --help      esta ayuda\n";

int fail(const std::string& message) {
    std::cerr << message << "\n";
    return 1;
}

}  // namespace

int main(int argc, char** argv) {
    std::string path;
    std::string emit_cpp;
    std::string extern_dada;
    std::string arg0;
    bool silencioso = false;
    bool solo_mir = false;
    bool pretty = false;
    bool summary = false;
    bool link = false;
    bool verify = false;
    bool resolve = false;
    bool mir = false;
    bool ejecutar = false;
    bool traza = false;
    bool memoria = false;
    // los limites de --run (ver 'vm.hpp'): pasos y memoria del programa
    std::uint64_t pasos = suriax::mir::kDefaultStepLimit;
    std::uint64_t memoria_max = suriax::mir::kSinLimiteDeMemoria;
    // lo que va despues del primer '--' es del PROGRAMA ('sistema.argumento');
    // el 0 es el archivo que se ejecuta
    std::vector<std::string> argumentos_del_programa;
    int fin_de_opciones = argc;
    for (int i = 1; i < argc; ++i) {
        if (std::string(argv[i]) == "--") {
            fin_de_opciones = i;
            for (int j = i + 1; j < argc; ++j) argumentos_del_programa.emplace_back(argv[j]);
            break;
        }
    }

    for (int i = 1; i < fin_de_opciones; ++i) {
        const std::string arg = argv[i];
        if (arg == "--emit-cpp") {
            if (i + 1 >= argc) {
                std::cerr << "--emit-cpp necesita un archivo de salida\n";
                return 2;
            }
            emit_cpp = argv[++i];
            continue;
        }
        if (arg == "--pasos" || arg == "--memoria-max") {
            if (i + 1 >= fin_de_opciones) {
                std::cerr << arg << " necesita un valor\n";
                return 2;
            }
            const std::string valor = argv[++i];
            std::uint64_t n = 0;
            std::string error;
            if (!(arg == "--pasos" ? leer_entero(valor, n, error)
                                   : leer_tamano(valor, n, error))) {
                std::cerr << arg << ": " << error << "\n";
                return 2;
            }
            (arg == "--pasos" ? pasos : memoria_max) = n;
            continue;
        }
        if (arg == "--arg0") {
            if (i + 1 >= fin_de_opciones) {
                std::cerr << "--arg0 necesita un nombre\n";
                return 2;
            }
            arg0 = argv[++i];
            continue;
        }
        if (arg == "--quiet") {
            silencioso = true;
            continue;
        }
        if (arg == "--check-mir") {
            solo_mir = true;
            continue;
        }
        if (arg == "--extern") {
            if (i + 1 >= fin_de_opciones) {
                std::cerr << "--extern necesita la ruta de una biblioteca\n";
                return 2;
            }
            extern_dada = argv[++i];
            continue;
        }
        if (arg == "--help" || arg == "-h") {
            std::cout << kUsage;
            return 0;
        }
        if (arg == "--pretty") {
            pretty = true;
        } else if (arg == "--summary") {
            summary = true;
        } else if (arg == "--link") {
            link = true;
        } else if (arg == "--verify") {
            verify = true;
        } else if (arg == "--resolve") {
            resolve = true;
        } else if (arg == "--mir") {
            mir = true;
        } else if (arg == "--run") {
            ejecutar = true;
        } else if (arg == "--trace") {
            traza = true;
        } else if (arg == "--memoria") {
            memoria = true;
        } else if (!arg.empty() && arg[0] == '-') {
            std::cerr << "opcion desconocida: " << arg << "\n\n" << kUsage;
            return 2;
        } else if (path.empty()) {
            path = arg;
        } else {
            std::cerr << "solo se lee un .phir por invocacion\n\n" << kUsage;
            return 2;
        }
    }

    if (path.empty()) {
        std::cerr << kUsage;
        return 2;
    }
    // '--emit-cpp' necesita la imagen: los bloques de una libreria tambien
    // son C++ que el backend tendra que compilar.
    if (!emit_cpp.empty()) link = true;
    // resolver exige la imagen ENTERA: una llamada a una libreria no se puede
    // decidir mirando solo el main.
    if (resolve) link = true;
    // bajar y ejecutar exigen la imagen ENTERA: una llamada a una libreria no
    // se puede bajar mirando solo el main.
    if (mir || ejecutar || solo_mir) link = true;
    if (!pretty && !link && !verify && !resolve && !mir && !ejecutar && !solo_mir) {
        summary = true;
    }

    namespace hir = suriax::hir;

    // '--link' carga la imagen completa (main + librerias, transitivas); el
    // resto trabaja sobre la unidad sola, que es lo que pide el caso normal.
    hir::Image image;
    std::unique_ptr<hir::pb::Module> single;
    const hir::pb::Module* module = nullptr;

    if (link) {
        if (hir::LoadStatus status = hir::load_image(path, image); !status.ok) {
            return fail(status.error);
        }
        module = &image.main().module();
    } else {
        if (hir::LoadStatus status = hir::load_module(path, single); !status.ok) {
            return fail(status.error);
        }
        module = single.get();
    }

    if (summary) hir::write_summary(*module, std::cout);

    // La vista legible es tambien el recorrido exhaustivo del arbol, asi que
    // '--verify' la produce y descarta el texto: un solo recorrido, una sola
    // definicion de que significa "entender el nodo".
    if (pretty || verify) {
        std::vector<hir::Unknown> unknown;
        if (pretty) {
            hir::write_pretty(*module, std::cout, unknown);
        } else {
            std::ostringstream discarded;
            hir::write_pretty(*module, discarded, unknown);
        }
        if (!unknown.empty()) {
            std::cerr << "el lector no entendio " << unknown.size()
                      << " nodo(s) del HIR:\n";
            for (const hir::Unknown& node : unknown) {
                std::cerr << "  " << node.what << " '" << node.node << "' en "
                          << node.line << ":" << node.col << "\n";
            }
            std::cerr << "es un nodo que el emisor escribe y este lector no "
                         "conoce: actualiza el lector o revisa el esquema.\n";
            return 1;
        }
    }

    if (!emit_cpp.empty()) {
        const std::vector<hir::ExternBlock> blocks = hir::collect_extern(image);
        std::ofstream out(emit_cpp, std::ios::binary);
        if (!out) return fail("no se pudo escribir '" + emit_cpp + "'");
        std::string error;
        if (!hir::write_extern_cpp(blocks, out, error)) return fail(error);
        std::cerr << "bloques '#extern cpp': " << blocks.size() << " -> "
                  << emit_cpp << "\n";
    }

    if (resolve) {
        const hir::Program program = hir::resolve(image);
        hir::write_resolved(program, std::cout);
        if (!program.unresolved.empty()) {
            std::cerr << "\nel backend no supo a que llaman "
                      << program.unresolved.size()
                      << " sitio(s): no puede bajar a MIR lo que no entiende.\n";
            return 1;
        }
    }

    if (solo_mir && !mir && !ejecutar) {
        const hir::Program resuelto = hir::resolve(image);
        const suriax::mir::Program programa = suriax::mir::lower(image, resuelto);
        for (const suriax::mir::Unsupported& fallo : programa.unsupported) {
            std::cerr << fallo.line << ":" << fallo.col << "  " << fallo.what << "\n";
        }
        return programa.unsupported.empty() ? 0 : 1;
    }

    if (mir || ejecutar) {
        const hir::Program resuelto = hir::resolve(image);
        const suriax::mir::Program programa =
            suriax::mir::lower(image, resuelto);
        if (mir) {
            suriax::mir::write_mir(programa, std::cout);
            // La verificacion de propiedad y prestamos va con el MIR y no
            // aparte: es la comprobacion que solo se puede hacer sobre el
            // CFG, y verla junto al grafo del que sale es lo que la hace
            // comprobable.
            const std::vector<suriax::mir::Finding> hallazgos =
                suriax::mir::verify(programa);
            std::cout << "\n";
            suriax::mir::write_findings(hallazgos, std::cout);
        }
        if (!programa.unsupported.empty()) {
            std::cerr << "\nel MIR no cubre " << programa.unsupported.size()
                      << " construccion(es):\n";
            for (const suriax::mir::Unsupported& fallo : programa.unsupported) {
                std::cerr << "  " << fallo.line << ":" << fallo.col << "  "
                          << fallo.what << "\n";
            }
            if (ejecutar) return 1;
        }
        if (ejecutar) {
            std::vector<std::string> argumentos{arg0.empty() ? path : arg0};
            argumentos.insert(argumentos.end(), argumentos_del_programa.begin(),
                              argumentos_del_programa.end());
            // '#extern cpp': el C++ del programa cumple sus prototipos. Un
            // fallo se AVISA y no detiene, como en el interprete: si de
            // verdad falta una primitiva, la llamada lo dice con su posicion.
            suriax::mir::Externo externo;
            std::vector<suriax::mir::FuncionExterna> externos;
            std::string biblioteca = extern_dada;
            if (biblioteca.empty()) {
                const std::string carpeta =
                    (std::filesystem::path(path).parent_path() / "extern").string();
                const suriax::mir::ReporteExterno r =
                    suriax::mir::construir_externo(image, carpeta, programa.hosts);
                if (!r.error.empty()) std::cerr << "#extern cpp: " << r.error << "\n";
                biblioteca = r.biblioteca;
            }
            if (!biblioteca.empty()) {
                std::string error;
                if (!externo.cargar(biblioteca, error)) {
                    std::cerr << "#extern cpp: " << error << "\n";
                } else {
                    std::vector<std::string> ligados;
                    std::vector<std::pair<std::string, std::string>> omitidos;
                    externos = suriax::mir::ligar_externo(programa, externo, ligados, omitidos);
                    if (!ligados.empty()) {
                        std::cerr << "#extern cpp: " << ligados.size()
                                  << " prototipo(s) ligado(s) a C++ (";
                        for (std::size_t k = 0; k < ligados.size(); ++k) {
                            std::cerr << (k ? ", " : "") << ligados[k];
                        }
                        std::cerr << ")\n";
                    }
                    for (const auto& [nombre, motivo] : omitidos) {
                        std::cerr << "#extern cpp: '" << nombre << "' no se pudo ligar — "
                                  << motivo << "\n";
                    }
                }
            }
            suriax::mir::Memoria usada;
            const suriax::mir::RunStatus status = suriax::mir::run(
                programa, pasos,
                traza ? &std::cerr : nullptr, std::move(argumentos), &usada,
                externos.empty() ? nullptr : &externos, memoria_max);
            if (memoria) {
                std::cerr << "[memoria] objetos creados " << usada.creados
                          << ", liberados " << usada.liberados
                          << ", vivos al terminar " << usada.vivos
                          << ", pico " << usada.maximo << std::endl;
                std::cerr << "[memoria] bytes del programa: pico " << usada.bytes_maximo
                          << ", vivos al terminar " << usada.bytes << std::endl;
                std::cerr << "[memoria] cadenas creadas " << usada.cadenas_creadas
                          << ", recogidas " << usada.cadenas_recogidas
                          << ", vivas al terminar " << usada.cadenas_vivas << std::endl;
                for (const auto& [tipo, n] : usada.vivos_por_tipo) {
                    std::cerr << "[memoria]   vivo: " << n << " x " << tipo << '\n';
                }
            }
            if (!status.ok) {
                std::cerr << "error de ejecucion";
                if (status.line != 0) {
                    std::cerr << " (" << status.line << ":" << status.col << ")";
                }
                std::cerr << ": " << status.error << "\n";
                // 70 y no 1: es el mismo codigo con el que sale el interprete
                // ante un fallo de ejecucion, y el diferencial compara
                // codigos de salida.
                return 70;
            }
            if (!silencioso) std::cout << "[vm] main() -> " << status.exit << "\n";
            // el valor ENTERO: POSIX se queda con 8 bits por su cuenta y Windows
            // conserva 32, igual que el proceso del interprete
            return static_cast<int>(status.exit);
        }
    }

    if (link) {
        std::cout << "imagen ligada: " << image.units().size() + 1
                  << " unidad(es), " << image.hook_count() << " hooks, "
                  << image.cast_count() << " conversiones\n";
        for (const auto& unit : image.units()) {
            std::cout << "  " << unit->alias() << " <- " << unit->path() << "\n";
        }
    }

    return 0;
}

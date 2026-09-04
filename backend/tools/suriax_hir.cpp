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
// Compararlas es el diferencial ENTRE CONSUMIDORES de 'test/e2e/test_backend_cpp.py'.

#include <cstring>
#include <fstream>
#include <iostream>
#include <sstream>
#include <string>
#include <vector>

#include "suriax/hir/loader.hpp"
#include "suriax/hir/resolve.hpp"
#include "suriax/mir/mir.hpp"
#include "suriax/mir/verify.hpp"
#include "suriax/mir/vm.hpp"
#include "suriax/hir/view.hpp"

namespace {

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
    bool pretty = false;
    bool summary = false;
    bool link = false;
    bool verify = false;
    bool resolve = false;
    bool mir = false;
    bool ejecutar = false;

    for (int i = 1; i < argc; ++i) {
        const std::string arg = argv[i];
        if (arg == "--emit-cpp") {
            if (i + 1 >= argc) {
                std::cerr << "--emit-cpp necesita un archivo de salida\n";
                return 2;
            }
            emit_cpp = argv[++i];
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
    if (mir || ejecutar) link = true;
    if (!pretty && !link && !verify && !resolve && !mir && !ejecutar) {
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
            const suriax::mir::RunStatus status = suriax::mir::run(programa);
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
            std::cout << "[vm] main() -> " << status.exit << "\n";
            return static_cast<int>(status.exit & 0xFF);
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

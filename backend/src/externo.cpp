#include "suriax/mir/externo.hpp"

#include <algorithm>
#include <cstdlib>
#include <cstring>
#include <filesystem>
#include <fstream>
#include <sstream>

#ifdef _WIN32
#ifndef WIN32_LEAN_AND_MEAN
#define WIN32_LEAN_AND_MEAN
#endif
#ifndef NOMINMAX
#define NOMINMAX
#endif
#include <windows.h>
#else
#include <dlfcn.h>
#endif

#ifndef SURIAX_CXX_ESTANDAR
#error "SURIAX_CXX_ESTANDAR lo define CMake desde version.py (CXX_STANDARD)"
#endif

namespace suriax::mir {

namespace fs = std::filesystem;

namespace {
// una ruta en UTF-8 -> path ('u8path' es obsoleto en C++20)
fs::path ruta_utf8(const std::string& s) {
    return fs::path(std::u8string(s.begin(), s.end()));
}
}  // namespace

// ------------------------------------------------------------------------ //
// cargar
// ------------------------------------------------------------------------ //

Externo::~Externo() {
    if (manejador_ == nullptr) return;
#ifdef _WIN32
    FreeLibrary(static_cast<HMODULE>(manejador_));
#else
    dlclose(manejador_);
#endif
}

bool Externo::cargar(const std::string& ruta, std::string& error) {
#ifdef _WIN32
    HMODULE m = LoadLibraryW(ruta_utf8(ruta).wstring().c_str());
    if (m == nullptr) {
        const DWORD codigo = GetLastError();
        error = "no se pudo cargar '" + ruta + "' (error " + std::to_string(codigo) + ")";
        // ERROR_BAD_EXE_FORMAT: la biblioteca es de otra arquitectura
        if (codigo == 193) {
            error += ": es de otra arquitectura que la VM (una de 32 bits en una VM de "
                     "64?); compila con -m64 (SURIAX_CPP_FLAGS)";
        }
        return false;
    }
    manejador_ = m;
#else
    manejador_ = dlopen(ruta.c_str(), RTLD_NOW | RTLD_LOCAL);
    if (manejador_ == nullptr) {
        const char* porque = dlerror();
        error = "no se pudo cargar '" + ruta + "': " + (porque != nullptr ? porque : "?");
        return false;
    }
#endif
    return true;
}

Externo::Funcion Externo::simbolo(const std::string& nombre) const {
    if (manejador_ == nullptr) return nullptr;
#ifdef _WIN32
    return reinterpret_cast<Funcion>(
        GetProcAddress(static_cast<HMODULE>(manejador_), nombre.c_str()));
#else
    return reinterpret_cast<Funcion>(dlsym(manejador_, nombre.c_str()));
#endif
}

// ------------------------------------------------------------------------ //
// ligar
// ------------------------------------------------------------------------ //

std::vector<Externo::Funcion> ligar_externo(
    const Program& program, const Externo& externo,
    std::vector<std::string>& ligados,
    std::vector<std::pair<std::string, std::string>>& omitidos) {
    std::vector<Externo::Funcion> tabla(program.hosts.size(), nullptr);
    for (std::size_t i = 0; i < program.hosts.size(); ++i) {
        const std::string& nombre = program.hosts[i];
        // la biblioteca no lo exporta: puede ser una primitiva de la VM
        // ('__write__'), asi que no es un error de nadie
        Externo::Funcion f = externo.simbolo(nombre);
        if (f == nullptr) continue;
        const Firma* firma = i < program.firmas_host.size() ? &program.firmas_host[i] : nullptr;
        if (firma == nullptr) {
            omitidos.emplace_back(nombre, "no se conoce su firma");
            continue;
        }
        if (!firma->sin_abi.empty()) {
            omitidos.emplace_back(nombre, firma->sin_abi);
            continue;
        }
        if (firma->params.size() > kMaxParamsExterno) {
            omitidos.emplace_back(nombre, "tiene mas de " + std::to_string(kMaxParamsExterno) +
                                              " parametros, el tope de la frontera de la VM");
            continue;
        }
        tabla[i] = f;
        ligados.push_back(nombre);
    }
    return tabla;
}

// ------------------------------------------------------------------------ //
// llamar
// ------------------------------------------------------------------------ //

namespace {

// Arma la llamada tipada de a un parametro por vez: cada uno es un entero de
// 64 bits o un double, asi que para n parametros hay 2^n firmas y con el tope
// de 6 son 127 por tipo de retorno, todas generadas al compilar. Es lo que
// hace libffi en general, reducido a lo que la frontera admite.
//
// Llamar por un puntero a funcion de otro tipo que el declarado no esta
// definido por el estandar de C++; lo que lo hace correcto es la ABI (ver
// 'kMaxParamsExterno'): un 'bool' o un 'uint32_t' viajan en el mismo
// registro que un entero de 64 bits, y quien los recibe mira solo su parte.
template <typename R, typename... A>
R invocar(Externo::Funcion f, const Crudo* args, std::size_t n, A... hechos) {
    if constexpr (sizeof...(A) < kMaxParamsExterno) {
        constexpr std::size_t i = sizeof...(A);
        if (i < n) {
            if (args[i].flotante) return invocar<R>(f, args, n, hechos..., args[i].f);
            return invocar<R>(f, args, n, hechos..., args[i].i);
        }
    }
    return reinterpret_cast<R (*)(A...)>(f)(hechos...);
}

}  // namespace

Value llamar_externo(Externo::Funcion f, Abi retorno, const std::vector<Crudo>& args) {
    const Crudo* a = args.data();
    const std::size_t n = args.size();
    Value v{};
    v.i = 0;
    switch (retorno) {
        case Abi::Entero: v.i = invocar<std::int64_t>(f, a, n); break;
        case Abi::Flotante: v.f = invocar<double>(f, a, n); break;
        // el retorno SI se lee con su tipo: de un 'bool' solo vale el byte
        // bajo del registro, el resto es basura
        case Abi::Logico: v.i = invocar<bool>(f, a, n) ? 1 : 0; break;
        case Abi::Caracter: v.i = static_cast<std::int64_t>(invocar<std::uint32_t>(f, a, n)); break;
        case Abi::Byte: v.i = static_cast<std::int64_t>(invocar<std::uint8_t>(f, a, n)); break;
        default: invocar<void>(f, a, n); break;
    }
    return v;
}

// ------------------------------------------------------------------------ //
// COFF
// ------------------------------------------------------------------------ //

namespace {

template <typename T>
bool leer(const std::string& s, std::size_t en, T& out) {
    if (en + sizeof(T) > s.size()) return false;
    std::memcpy(&out, s.data() + en, sizeof(T));   // COFF es little-endian
    return true;
}

}  // namespace

std::vector<std::string> definidos_coff(const std::string& c) {
    std::vector<std::string> salida;
    std::uint16_t firma1 = 0;
    std::uint16_t firma2 = 0;
    if (!leer(c, 0, firma1) || !leer(c, 2, firma2)) return salida;
    std::uint16_t maquina = 0;
    std::uint32_t tabla = 0;
    std::uint32_t cuantos = 0;
    std::size_t tam = 18;
    const bool grande = firma1 == 0 && firma2 == 0xFFFF;   // '/bigobj'
    if (grande) {
        if (!leer(c, 6, maquina) || !leer(c, 48, tabla) || !leer(c, 52, cuantos)) return salida;
        tam = 20;
    } else {
        maquina = firma1;
        if (!leer(c, 8, tabla) || !leer(c, 12, cuantos)) return salida;
    }
    const std::size_t cadenas = tabla + static_cast<std::size_t>(cuantos) * tam;
    for (std::uint32_t i = 0; i < cuantos;) {
        const std::size_t base = tabla + static_cast<std::size_t>(i) * tam;
        if (base + tam > c.size()) break;
        std::int32_t seccion = 0;
        if (grande) {
            leer(c, base + 12, seccion);
        } else {
            std::int16_t corta = 0;
            leer(c, base + 12, corta);
            seccion = corta;
        }
        const std::uint8_t clase = static_cast<std::uint8_t>(c[base + tam - 2]);
        const std::uint8_t aux = static_cast<std::uint8_t>(c[base + tam - 1]);
        // EXTERNO (clase 2) y DEFINIDO (con seccion)
        if (clase == 2 && seccion > 0) {
            std::string nombre;
            std::uint32_t ceros = 0;
            leer(c, base, ceros);
            if (ceros == 0) {
                std::uint32_t desplazamiento = 0;
                leer(c, base + 4, desplazamiento);
                const std::size_t desde = cadenas + desplazamiento;
                if (desde < c.size()) {
                    const std::size_t fin = c.find('\0', desde);
                    nombre = c.substr(desde, fin == std::string::npos ? std::string::npos : fin - desde);
                }
            } else {
                nombre = c.substr(base, 8);
                const std::size_t fin = nombre.find('\0');
                if (fin != std::string::npos) nombre.resize(fin);
            }
            // en 32 bits el nombre de C lleva un '_' delante
            if (maquina == 0x14C && !nombre.empty() && nombre[0] == '_') nombre.erase(0, 1);
            if (!nombre.empty()) salida.push_back(nombre);
        }
        i += 1u + aux;
    }
    return salida;
}

// ------------------------------------------------------------------------ //
// construir
// ------------------------------------------------------------------------ //

namespace {

std::string entorno(const char* nombre) {
#ifdef _MSC_VER
    char* valor = nullptr;
    std::size_t largo = 0;
    if (_dupenv_s(&valor, &largo, nombre) != 0 || valor == nullptr) return {};
    std::string s(valor);
    std::free(valor);
    return s;
#else
    const char* valor = std::getenv(nombre);
    return valor != nullptr ? std::string(valor) : std::string();
#endif
}

// 'nombre' en el PATH (o tal cual si ya es una ruta), o "".
std::string en_el_path(const std::string& nombre) {
    std::error_code ec;
    if (fs::path(nombre).has_parent_path()) {
        return fs::exists(nombre, ec) ? nombre : std::string();
    }
#ifdef _WIN32
    const char separador = ';';
    const std::vector<std::string> extensiones{"", ".exe"};
#else
    const char separador = ':';
    const std::vector<std::string> extensiones{""};
#endif
    std::stringstream path(entorno("PATH"));
    std::string dir;
    while (std::getline(path, dir, separador)) {
        if (dir.empty()) continue;
        for (const std::string& ext : extensiones) {
            const fs::path candidato = fs::path(dir) / (nombre + ext);
            if (fs::is_regular_file(candidato, ec)) return candidato.string();
        }
    }
    return {};
}

// El orden del interprete: $CXX (tal cual, sin caer en otro si no existe) y
// si no, g++ o clang++.
std::string compilador() {
    const std::string cxx = entorno("CXX");
    if (!cxx.empty()) return en_el_path(cxx);
    for (const char* nombre : {"g++", "clang++"}) {
        std::string ruta = en_el_path(nombre);
        if (!ruta.empty()) return ruta;
    }
    return {};
}

std::string comillas(const std::string& s) { return "\"" + s + "\""; }

// Corre 'orden' con su salida a 'registro'. Devuelve su codigo.
int ejecutar(const std::string& orden, const fs::path& registro) {
    std::string completa = orden + " > " + comillas(registro.string()) + " 2>&1";
#ifdef _WIN32
    // cmd /c quita las comillas de los extremos: se envuelve todo una vez mas
    completa = "\"" + completa + "\"";
#endif
    return std::system(completa.c_str());
}

std::string leer_archivo(const fs::path& ruta) {
    std::ifstream in(ruta, std::ios::binary);
    std::ostringstream s;
    s << in.rdbuf();
    return s.str();
}

std::vector<std::string> palabras(const std::string& texto) {
    std::vector<std::string> salida;
    std::istringstream in(texto);
    std::string p;
    while (in >> p) salida.push_back(p);
    return salida;
}

}  // namespace

ReporteExterno construir_externo(const hir::Image& image, const std::string& carpeta,
                                 const std::vector<std::string>& prototipos) {
    ReporteExterno r;
    const std::vector<hir::ExternBlock> bloques = hir::collect_extern(image);
    if (bloques.empty()) return r;
    r.hubo_bloques = true;

    // las banderas: primero las que traen los bloques, despues las de esta
    // maquina (la ultima palabra la tiene quien compila)
    std::vector<std::string> banderas;
    for (const hir::ExternBlock& b : bloques) {
        for (const std::string& f : b.banderas) {
            if (std::find(banderas.begin(), banderas.end(), f) == banderas.end()) {
                banderas.push_back(f);
            }
        }
    }
    for (const std::string& f : palabras(entorno("SURIAX_CPP_FLAGS"))) banderas.push_back(f);

    const std::string cxx = compilador();
    if (cxx.empty()) {
        r.error = "no hay compilador de C++ que usar: exporta $CXX o instala g++/clang++. "
                  "El bloque '#extern cpp' viaja igual, pero sin compilador no se puede "
                  "construir";
        return r;
    }

    std::error_code ec;
    const fs::path dir = ruta_utf8(carpeta);
    fs::create_directories(dir, ec);
    const fs::path registro = dir / "extern_cpp_vm.log";

    // para que maquina produce: con la ABI de MSVC hay que exportar a mano,
    // y un clang de Windows produce 32 bits si nadie dice otra cosa
    std::string objetivo;
    if (ejecutar(comillas(cxx) + " -dumpmachine", registro) == 0) {
        objetivo = leer_archivo(registro);
        while (!objetivo.empty() && (objetivo.back() == '\n' || objetivo.back() == '\r')) {
            objetivo.pop_back();
        }
    }
    const bool explicito = std::any_of(banderas.begin(), banderas.end(), [](const std::string& f) {
        return f == "-m32" || f == "-m64" || f.rfind("--target", 0) == 0;
    });
    const bool de_32 = objetivo.rfind("i386", 0) == 0 || objetivo.rfind("i486", 0) == 0 ||
                       objetivo.rfind("i586", 0) == 0 || objetivo.rfind("i686", 0) == 0;
    if (!explicito && de_32 && sizeof(void*) == 8) banderas.insert(banderas.begin(), "-m64");
    const bool msvc = objetivo.find("msvc") != std::string::npos;

    // la unidad de traduccion, con el compilador y las banderas en su
    // cabecera: cambiarlas cambia el archivo, y la cache se invalida sola
    std::ostringstream fuente;
    fuente << "// compilador: " << cxx << "\n// banderas:";
    for (const std::string& f : banderas) fuente << ' ' << f;
    fuente << "\n";
    std::string error;
    if (!hir::write_extern_cpp(bloques, fuente, error)) {
        r.error = error;
        return r;
    }

    const fs::path cpp = dir / "extern_cpp_vm.cpp";
#ifdef _WIN32
    const fs::path lib = dir / "extern_cpp_vm.dll";
#else
    const fs::path lib = dir / "extern_cpp_vm.so";
#endif
    const std::string texto = fuente.str();
    if (fs::exists(cpp, ec) && leer_archivo(cpp) == texto) {
        if (fs::exists(lib, ec) && fs::last_write_time(lib, ec) >= fs::last_write_time(cpp, ec)) {
            r.biblioteca = lib.string();
            return r;
        }
    } else {
        std::ofstream out(cpp, std::ios::binary);
        out << texto;
    }

    std::string resto;
    for (const std::string& f : banderas) resto += " " + comillas(f);
    const std::string estandar = " -std=c++" SURIAX_CXX_ESTANDAR;
    int codigo = 0;
    if (msvc) {
        // primero el objeto, para saber que define; despues la DLL exportando
        // justo los prototipos que existen ('/EXPORT' de uno que no existe
        // rompe el enlazado)
        const fs::path obj = dir / "extern_cpp_vm.obj";
        codigo = ejecutar(comillas(cxx) + " -c" + estandar + " -O1 " + comillas(cpp.string()) +
                              " -o " + comillas(obj.string()) + resto,
                          registro);
        if (codigo == 0) {
            const std::vector<std::string> definidos = definidos_coff(leer_archivo(obj));
            std::string exportar;
            for (const std::string& p : prototipos) {
                if (std::find(definidos.begin(), definidos.end(), p) != definidos.end()) {
                    exportar += " " + comillas("-Wl,/EXPORT:" + p);
                }
            }
            codigo = ejecutar(comillas(cxx) + " -shared " + comillas(obj.string()) + " -o " +
                                  comillas(lib.string()) + resto + exportar,
                              registro);
        }
    } else {
#ifdef _WIN32
        const std::string pic;   // '-fPIC' es de ELF
#else
        const std::string pic = " -fPIC";
#endif
        codigo = ejecutar(comillas(cxx) + " -shared" + pic + estandar + " -O1 " +
                              comillas(cpp.string()) + " -o " + comillas(lib.string()) + resto,
                          registro);
    }
    if (codigo != 0) {
        // el fuente queda: la proxima vez se reintenta
        fs::remove(lib, ec);
        r.error = "el bloque '#extern cpp' no compila:\n" + leer_archivo(registro);
        return r;
    }
    r.biblioteca = lib.string();
    return r;
}

}  // namespace suriax::mir

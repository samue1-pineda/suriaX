// 'lib/sistema/rutas' en la VM: los algoritmos de 'ntpath' y 'posixpath'.
// Ver 'suriax/mir/rutas.hpp'.

#include "suriax/mir/rutas.hpp"

#include <cstdlib>
#include <filesystem>
#include <string>
#include <system_error>
#include <utility>
#include <vector>

#ifdef _WIN32
#ifndef WIN32_LEAN_AND_MEAN
#define WIN32_LEAN_AND_MEAN
#endif
#ifndef NOMINMAX
#define NOMINMAX
#endif
#include <windows.h>
#else
#include <unistd.h>
#endif

namespace suriax::rutas {

namespace {

// Una ruta del sistema de archivos a partir de UTF-8 (como la VM las guarda).
std::filesystem::path ruta_de(const std::string& ruta) {
    return std::filesystem::path(std::u8string(ruta.begin(), ruta.end()));
}

std::vector<std::string> parte(const std::string& s, char sep) {
    std::vector<std::string> tramos;
    std::string actual;
    for (const char c : s) {
        if (c == sep) {
            tramos.push_back(actual);
            actual.clear();
        } else {
            actual.push_back(c);
        }
    }
    tramos.push_back(actual);
    return tramos;
}

std::string junta(const std::vector<std::string>& tramos, const std::string& sep) {
    std::string r;
    for (std::size_t i = 0; i < tramos.size(); ++i) {
        if (i > 0) r += sep;
        r += tramos[i];
    }
    return r;
}

struct Raiz {
    std::string unidad;  // 'C:' o '\\servidor\recurso' ('' en POSIX)
    std::string raiz;    // el separador de la raiz ('\', '/' o '//')
    std::string resto;
};

#ifdef _WIN32

// ---- UTF-8 <-> UTF-16 (las llamadas del sistema de Windows son 'W') ----

std::wstring ancho(const std::string& s) {
    if (s.empty()) return std::wstring();
    const int n = MultiByteToWideChar(CP_UTF8, 0, s.data(), static_cast<int>(s.size()),
                                      nullptr, 0);
    std::wstring w(static_cast<std::size_t>(n), L'\0');
    MultiByteToWideChar(CP_UTF8, 0, s.data(), static_cast<int>(s.size()), w.data(), n);
    return w;
}

std::string estrecho(const std::wstring& w) {
    if (w.empty()) return std::string();
    const int n = WideCharToMultiByte(CP_UTF8, 0, w.data(), static_cast<int>(w.size()),
                                      nullptr, 0, nullptr, nullptr);
    std::string s(static_cast<std::size_t>(n), '\0');
    WideCharToMultiByte(CP_UTF8, 0, w.data(), static_cast<int>(w.size()), s.data(), n,
                        nullptr, nullptr);
    return s;
}

bool es_sep(char c) { return c == '\\' || c == '/'; }

std::string mayusculas(std::string s) {
    for (char& c : s) {
        if (c >= 'a' && c <= 'z') c = static_cast<char>(c - 'a' + 'A');
    }
    return s;
}

// ntpath.splitroot: los tramos salen de la ruta ORIGINAL; la busqueda se hace
// sobre la ruta con '/' pasado a '\'.
Raiz separa_raiz(const std::string& p) {
    std::string normp = p;
    for (char& c : normp) {
        if (c == '/') c = '\\';
    }
    if (!normp.empty() && normp[0] == '\\') {
        if (normp.size() > 1 && normp[1] == '\\') {
            // UNC ('\\servidor\recurso', '\\?\UNC\servidor\recurso') o
            // dispositivo ('\\.\dispositivo', '\\?\dispositivo')
            const std::size_t inicio =
                mayusculas(normp.substr(0, 8)) == "\\\\?\\UNC\\" ? 8 : 2;
            const std::size_t i = normp.find('\\', inicio);
            if (i == std::string::npos) return {p, "", ""};
            const std::size_t j = normp.find('\\', i + 1);
            if (j == std::string::npos) return {p, "", ""};
            return {p.substr(0, j), p.substr(j, 1), p.substr(j + 1)};
        }
        return {"", p.substr(0, 1), p.substr(1)};  // '\Windows'
    }
    if (normp.size() > 1 && normp[1] == ':') {
        if (normp.size() > 2 && normp[2] == '\\') {
            return {p.substr(0, 2), p.substr(2, 1), p.substr(3)};  // 'X:\Windows'
        }
        return {p.substr(0, 2), "", p.substr(2)};  // 'X:Windows'
    }
    return {"", "", p};
}

std::string normaliza_nt(const std::string& original) {
    std::string ruta = original;
    for (char& c : ruta) {
        if (c == '/') c = '\\';
    }
    const Raiz r = separa_raiz(ruta);
    const std::string prefijo = r.unidad + r.raiz;
    std::vector<std::string> tramos = parte(r.resto, '\\');
    std::size_t i = 0;
    while (i < tramos.size()) {
        if (tramos[i].empty() || tramos[i] == ".") {
            tramos.erase(tramos.begin() + static_cast<std::ptrdiff_t>(i));
        } else if (tramos[i] == "..") {
            if (i > 0 && tramos[i - 1] != "..") {
                tramos.erase(tramos.begin() + static_cast<std::ptrdiff_t>(i - 1),
                             tramos.begin() + static_cast<std::ptrdiff_t>(i + 1));
                --i;
            } else if (i == 0 && !r.raiz.empty()) {
                tramos.erase(tramos.begin() + static_cast<std::ptrdiff_t>(i));
            } else {
                ++i;
            }
        } else {
            ++i;
        }
    }
    if (prefijo.empty() && tramos.empty()) tramos.push_back(".");
    return prefijo + junta(tramos, "\\");
}

std::string une_nt(const std::string& a, const std::string& b) {
    Raiz res = separa_raiz(a);
    const Raiz p = separa_raiz(b);
    if (!p.raiz.empty()) {
        // la segunda es absoluta
        if (!p.unidad.empty() || res.unidad.empty()) res.unidad = p.unidad;
        res.raiz = p.raiz;
        res.resto = p.resto;
    } else if (!p.unidad.empty() && p.unidad != res.unidad) {
        if (mayusculas(p.unidad) != mayusculas(res.unidad)) {
            // otra unidad: se descarta la primera ruta
            return p.unidad + p.raiz + p.resto;
        }
        res.unidad = p.unidad;  // la misma unidad, escrita distinto
        if (!res.resto.empty() && !es_sep(res.resto.back())) res.resto += '\\';
        res.resto += p.resto;
    } else {
        if (!res.resto.empty() && !es_sep(res.resto.back())) res.resto += '\\';
        res.resto += p.resto;
    }
    // un separador entre un UNC y una ruta relativa
    if (!res.resto.empty() && res.raiz.empty() && !res.unidad.empty()) {
        const char ultimo = res.unidad.back();
        if (ultimo != ':' && !es_sep(ultimo)) return res.unidad + "\\" + res.resto;
    }
    return res.unidad + res.raiz + res.resto;
}

std::pair<std::string, std::string> separa_nt(const std::string& p) {
    const Raiz r = separa_raiz(p);
    std::size_t i = r.resto.size();
    while (i > 0 && !es_sep(r.resto[i - 1])) --i;
    std::string cabeza = r.resto.substr(0, i);
    const std::string cola = r.resto.substr(i);
    while (!cabeza.empty() && es_sep(cabeza.back())) cabeza.pop_back();
    return {r.unidad + r.raiz + cabeza, cola};
}

std::string actual_nt() {
    const DWORD n = GetCurrentDirectoryW(0, nullptr);
    if (n == 0) return std::string();
    std::wstring w(static_cast<std::size_t>(n), L'\0');
    const DWORD escritos = GetCurrentDirectoryW(n, w.data());
    w.resize(escritos);
    return estrecho(w);
}

bool es_absoluta_nt(const std::string& s) {
    std::string t = s.substr(0, 3);
    for (char& c : t) {
        if (c == '/') c = '\\';
    }
    return (t.size() >= 3 && t[1] == ':' && t[2] == '\\') ||
           (t.size() >= 2 && t[0] == '\\' && t[1] == '\\');
}

// ntpath.abspath: 'GetFullPathNameW' sobre la ruta normalizada; si falla, el
// camino de reserva de Python (unir con el directorio actual y normalizar).
std::string absoluta_nt(const std::string& ruta) {
    const std::wstring w = ancho(normaliza_nt(ruta));
    const DWORD n = GetFullPathNameW(w.c_str(), 0, nullptr, nullptr);
    if (n > 0) {
        std::wstring salida(static_cast<std::size_t>(n), L'\0');
        const DWORD escritos = GetFullPathNameW(w.c_str(), n, salida.data(), nullptr);
        if (escritos > 0 && escritos < n) {
            salida.resize(escritos);
            return estrecho(salida);
        }
    }
    if (es_absoluta_nt(ruta)) return normaliza_nt(ruta);
    return normaliza_nt(une_nt(actual_nt(), ruta));
}

#else  // POSIX

Raiz separa_raiz(const std::string& p) {
    if (p.empty() || p[0] != '/') return {"", "", p};
    if (p.size() < 2 || p[1] != '/' || (p.size() > 2 && p[2] == '/')) {
        return {"", "/", p.substr(1)};
    }
    return {"", "//", p.substr(2)};  // POSIX deja pasar exactamente dos '/'
}

std::string normaliza_posix(const std::string& ruta) {
    if (ruta.empty()) return ".";
    const Raiz r = separa_raiz(ruta);
    std::vector<std::string> nuevos;
    for (const std::string& t : parte(r.resto, '/')) {
        if (t.empty() || t == ".") continue;
        if (t != ".." || (r.raiz.empty() && nuevos.empty()) ||
            (!nuevos.empty() && nuevos.back() == "..")) {
            nuevos.push_back(t);
        } else if (!nuevos.empty()) {
            nuevos.pop_back();
        }
    }
    const std::string salida = r.raiz + junta(nuevos, "/");
    return salida.empty() ? "." : salida;
}

std::string une_posix(const std::string& a, const std::string& b) {
    if (!b.empty() && b[0] == '/') return b;
    if (a.empty() || a.back() == '/') return a + b;
    return a + "/" + b;
}

std::pair<std::string, std::string> separa_posix(const std::string& p) {
    const std::size_t i = p.rfind('/') == std::string::npos ? 0 : p.rfind('/') + 1;
    std::string cabeza = p.substr(0, i);
    const std::string cola = p.substr(i);
    if (!cabeza.empty() && cabeza.find_first_not_of('/') != std::string::npos) {
        while (!cabeza.empty() && cabeza.back() == '/') cabeza.pop_back();
    }
    return {cabeza, cola};
}

std::string actual_posix() {
    std::string buffer(4096, '\0');
    if (getcwd(buffer.data(), buffer.size()) == nullptr) return std::string();
    buffer.resize(std::char_traits<char>::length(buffer.c_str()));
    return buffer;
}

#endif

}  // namespace

std::string directorio_actual() {
#ifdef _WIN32
    return actual_nt();
#else
    return actual_posix();
#endif
}

std::string entorno(const std::string& nombre) {
#ifdef _WIN32
    const std::wstring w = ancho(nombre);
    const DWORD n = GetEnvironmentVariableW(w.c_str(), nullptr, 0);
    if (n == 0) return std::string();
    std::wstring valor(static_cast<std::size_t>(n), L'\0');
    const DWORD escritos = GetEnvironmentVariableW(w.c_str(), valor.data(), n);
    valor.resize(escritos);
    return estrecho(valor);
#else
    const char* valor = std::getenv(nombre.c_str());
    return valor == nullptr ? std::string() : std::string(valor);
#endif
}

std::string separador() {
#ifdef _WIN32
    return "\\";
#else
    return "/";
#endif
}

std::string absoluta(const std::string& ruta) {
#ifdef _WIN32
    return absoluta_nt(ruta);
#else
    const std::string completa = (!ruta.empty() && ruta[0] == '/')
                                     ? ruta
                                     : une_posix(actual_posix(), ruta);
    return normaliza_posix(completa);
#endif
}

std::string normaliza(const std::string& ruta) {
#ifdef _WIN32
    return normaliza_nt(ruta);
#else
    return normaliza_posix(ruta);
#endif
}

std::string une(const std::string& a, const std::string& b) {
#ifdef _WIN32
    return une_nt(a, b);
#else
    return une_posix(a, b);
#endif
}

std::string carpeta_de(const std::string& ruta) {
#ifdef _WIN32
    return separa_nt(ruta).first;
#else
    return separa_posix(ruta).first;
#endif
}

std::string nombre_de(const std::string& ruta) {
#ifdef _WIN32
    return separa_nt(ruta).second;
#else
    return separa_posix(ruta).second;
#endif
}

bool es_carpeta(const std::string& ruta) {
    std::error_code ec;
    return std::filesystem::is_directory(ruta_de(ruta), ec);
}

bool es_archivo(const std::string& ruta) {
    std::error_code ec;
    return std::filesystem::is_regular_file(ruta_de(ruta), ec);
}

}  // namespace suriax::rutas

"""Genera ``backend/include/suriax/hir/hir_modelo.hpp`` desde ``hir.proto``.

El backend C++ leía el HIR con las clases que genera ``protoc`` y enlazaba
``libprotobuf``: una dependencia que en Windows no se consigue fácil y que
dejaba la VM sin construir (y sus pruebas omitidas). Python y el target web ya
la habían soltado con un decodificador propio; este script hace lo mismo para
C++, pero GENERANDO el decodificador en vez de escribirlo a mano:

- ``hir.proto`` sigue siendo la fuente única. El esquema se lee con el mismo
  lector que usa el decodificador de Python (``V0/src/HIR/schema.py``), así
  que los dos lados entienden exactamente el mismo subconjunto de proto3.
- La API es la de ``protoc`` (``x()``, ``has_x()``, ``x(i)``, ``x_size()``,
  ``node_case()``, ``kLiteral``...): el código del backend no cambia.
- El resultado se GUARDA en el repositorio: construir el backend no necesita
  Python ni ``protoc``, solo CMake y un compilador de C++20. Una prueba
  (``test_backend_cpp``) comprueba que el archivo guardado es exactamente lo
  que este script genera, así que no puede desincronizarse del ``.proto``.

Uso::

    python backend/tools/gen_hir_cpp.py            # regenera el encabezado
    python backend/tools/gen_hir_cpp.py --check    # falla si está desactualizado
"""

from __future__ import annotations

import importlib.util
import os
import re
import sys

_REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_PROTO = os.path.join(_REPO, "V0", "src", "HIR", "proto", "hir.proto")
_SALIDA = os.path.join(_REPO, "backend", "include", "suriax", "hir", "hir_modelo.hpp")


def _cargar_esquema():
    """``V0/src/HIR/schema.py`` cargado por su RUTA (sin importar el paquete
    del HIR, que arrastra medio frontend)."""
    ruta = os.path.join(_REPO, "V0", "src", "HIR", "schema.py")
    spec = importlib.util.spec_from_file_location("_hir_schema", ruta)
    modulo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modulo)
    with open(_PROTO, encoding="utf-8") as fh:
        texto = fh.read()
    return modulo, modulo.parse(texto), texto


# palabras reservadas de C++20 que pueden aparecer como nombre de campo: protoc
# les añade un '_' al accesor ('sizeof' -> 'sizeof_()'), y aquí igual.
_RESERVADAS = {
    "alignas", "alignof", "and", "asm", "auto", "bool", "break", "case", "catch",
    "char", "class", "concept", "const", "consteval", "constexpr", "constinit",
    "continue", "co_await", "co_return", "co_yield", "decltype", "default",
    "delete", "do", "double", "else", "enum", "explicit", "export", "extern",
    "false", "float", "for", "friend", "goto", "if", "inline", "int", "long",
    "mutable", "namespace", "new", "noexcept", "not", "nullptr", "operator",
    "or", "private", "protected", "public", "register", "requires", "return",
    "short", "signed", "sizeof", "static", "struct", "switch", "template",
    "this", "throw", "true", "try", "typedef", "typeid", "typename", "union",
    "unsigned", "using", "virtual", "void", "volatile", "while", "xor",
}

_CPP_ESCALAR = {
    "uint32": "std::uint32_t", "int32": "std::int32_t", "int64": "std::int64_t",
    "uint64": "std::uint64_t", "bool": "bool", "double": "double",
    "float": "float", "string": "std::string",
}


def _accesor(nombre: str) -> str:
    return nombre + "_" if nombre in _RESERVADAS else nombre


def _camel(nombre: str) -> str:
    return "".join(p[:1].upper() + p[1:] for p in nombre.split("_"))


def _anidados(texto: str) -> dict:
    """Mensaje anidado -> su padre (``Part`` -> ``InterpolatedString``)."""
    padres, pila = {}, []
    for linea in texto.splitlines():
        linea = linea.split("//")[0].strip()
        m = re.match(r"^(message|enum|oneof)\s+(\w+)\s*\{(.*)$", linea)
        if m:
            tipo, nombre, resto = m.groups()
            if tipo == "message" and pila:
                padres[nombre] = pila[-1][1]
            if not resto.rstrip().endswith("}"):
                pila.append((tipo, nombre))
            continue
        if linea == "}" and pila:
            pila.pop()
    return {hijo: padre for hijo, padre in padres.items()}


def generar() -> str:
    sch, esquema, texto = _cargar_esquema()
    anidados = _anidados(texto)

    def clase(nombre: str) -> str:
        """El nombre C++ de un mensaje (los anidados se aplanan con '_')."""
        return f"{anidados[nombre]}_{nombre}" if nombre in anidados else nombre

    def es_enum(t: str) -> bool:
        return t in esquema.enums

    def es_mensaje(t: str) -> bool:
        return t in esquema.messages

    def tipo_cpp(t: str) -> str:
        if es_enum(t):
            return t
        if es_mensaje(t):
            return clase(t)
        return _CPP_ESCALAR[t]

    s: list = []
    w = s.append
    w("// ============================================================================")
    w("// GENERADO por backend/tools/gen_hir_cpp.py desde V0/src/HIR/proto/hir.proto.")
    w("// NO EDITAR A MANO: cambia el .proto y vuelve a correr el script. Una prueba")
    w("// (test_backend_cpp) falla si este archivo no es lo que el script genera.")
    w("//")
    w("// El modelo del HIR en C++, sin libprotobuf: la misma API que genera protoc")
    w("// (x(), has_x(), x(i), x_size(), node_case()...) y un lector del formato de")
    w("// protobuf que hace lo mismo que V0/src/HIR/wire.py.")
    w("// ============================================================================")
    w("#pragma once")
    w("")
    for inc in ("bit", "cstddef", "cstdint", "istream", "iterator", "map", "memory",
                "stdexcept", "string", "utility", "vector"):
        w(f"#include <{inc}>")
    w("")
    w("namespace suriax::hir::v0 {")
    w("")

    # --- enums ----------------------------------------------------------------
    w("// --- enums (sin ámbito, al nivel del paquete: como los de protoc) ----------")
    w("")
    for nombre, items in esquema.enums.items():
        w(f"enum {nombre} : int {{")
        for item, valor in items.items():
            w(f"    {item} = {valor},")
        w("};")
        w("")
        w(f"inline std::string {nombre}_Name(int valor) {{")
        w("    switch (valor) {")
        for item, valor in items.items():
            w(f"        case {valor}: return \"{item}\";")
        w("        default: return std::string();")
        w("    }")
        w("}")
        w("")

    # --- infraestructura --------------------------------------------------------
    w(_INFRAESTRUCTURA)

    # --- declaraciones adelantadas ----------------------------------------------
    for nombre in esquema.messages:
        w(f"class {clase(nombre)};")
    w("")

    # --- clases -------------------------------------------------------------------
    definiciones: list = []
    d = definiciones.append
    for nombre, msg in esquema.messages.items():
        c = clase(nombre)
        hijos = [h for h, p in anidados.items() if p == nombre]
        w(f"class {c} {{")
        w(" public:")
        for h in hijos:
            w(f"    using {h} = {clase(h)};")
        w(f"    {c}();")
        w(f"    {c}(const {c}&);")
        w(f"    {c}& operator=(const {c}&);")
        w(f"    {c}({c}&&) noexcept;")
        w(f"    {c}& operator=({c}&&) noexcept;")
        w(f"    ~{c}();")
        w(f"    static const {c}& default_instance();")
        w("    bool ParseFromString(const std::string& datos);")
        w("    bool ParseFromArray(const void* datos, int largo);")
        w("    bool ParseFromIstream(std::istream* entrada);")
        w("    bool _lee(detalle::Lector& lector, std::size_t fin);")
        d(f"inline {c}::{c}() = default;")
        d(f"inline {c}::{c}(const {c}&) = default;")
        d(f"inline {c}& {c}::operator=(const {c}&) = default;")
        d(f"inline {c}::{c}({c}&&) noexcept = default;")
        d(f"inline {c}& {c}::operator=({c}&&) noexcept = default;")
        d(f"inline {c}::~{c}() = default;")
        d(f"inline const {c}& {c}::default_instance() {{ static const {c} vacio; return vacio; }}")
        d(f"inline bool {c}::ParseFromString(const std::string& datos) {{")
        d("    return ParseFromArray(datos.data(), static_cast<int>(datos.size()));")
        d("}")
        d(f"inline bool {c}::ParseFromArray(const void* datos, int largo) {{")
        d(f"    *this = {c}();")
        d("    detalle::Lector lector(static_cast<const unsigned char*>(datos),")
        d("                           static_cast<std::size_t>(largo));")
        d("    return _lee(lector, static_cast<std::size_t>(largo));")
        d("}")
        d(f"inline bool {c}::ParseFromIstream(std::istream* entrada) {{")
        d("    std::string datos((std::istreambuf_iterator<char>(*entrada)),")
        d("                      std::istreambuf_iterator<char>());")
        d("    if (entrada->bad()) return false;")
        d("    return ParseFromString(datos);")
        d("}")

        miembros: list = []
        casos_de_lectura: list = []
        # oneofs: enum de caso y campo discriminante
        for oneof, campos in msg.oneofs.items():
            en = _camel(oneof) + "Case"
            w(f"    enum {en} : int {{")
            for campo in campos:
                f = msg.fields[campo]
                w(f"        k{_camel(campo)} = {f.number},")
            w(f"        {oneof.upper()}_NOT_SET = 0,")
            w("    };")
            w(f"    {en} {oneof}_case() const;")
            d(f"inline {c}::{en} {c}::{oneof}_case() const {{ return static_cast<{en}>({oneof}_caso_); }}")
            miembros.append(f"    int {oneof}_caso_ = 0;")

        for fname, f in msg.fields.items():
            a = _accesor(fname)
            t = tipo_cpp(f.type)
            m = f"m_{fname}"   # nunca choca con el accesor ('sizeof_()')
            if f.is_map:
                w(f"    const detalle::Mapa<{t}>& {a}() const;")
                d(f"inline const detalle::Mapa<{t}>& {c}::{a}() const {{ return {m}; }}")
                w(f"    int {fname}_size() const;")
                d(f"inline int {c}::{fname}_size() const {{ return static_cast<int>({m}.size()); }}")
                miembros.append(f"    detalle::Mapa<{t}> {m};")
                casos_de_lectura.append((f.number, f"""        case {f.number}: {{
            if (tipo != 2) {{ if (!lector.salta(tipo)) return false; break; }}
            std::size_t hasta;
            if (!lector.largo(hasta, fin)) return false;
            std::string clave;
            {t} valor;
            while (lector.pos() < hasta) {{
                std::uint64_t et;
                if (!lector.varint(et)) return false;
                const int ti = static_cast<int>(et & 7);
                if ((et >> 3) == 1 && ti == 2) {{ if (!lector.texto(clave, hasta)) return false; }}
                else if ((et >> 3) == 2 && ti == 2) {{
                    std::size_t h2;
                    if (!lector.largo(h2, hasta) || !valor._lee(lector, h2)) return false;
                }}
                else if (!lector.salta(ti)) return false;
            }}
            {m}.inserta(clave) = std::move(valor);
            break;
        }}"""))
                continue
            if f.repeated:
                ref = f"const {t}&" if es_mensaje(f.type) or f.type == "string" else t
                w(f"    const std::vector<{t}>& {a}() const;")
                w(f"    {ref} {a}(int i) const;")
                w(f"    int {fname}_size() const;")
                d(f"inline const std::vector<{t}>& {c}::{a}() const {{ return {m}; }}")
                d(f"inline {ref} {c}::{a}(int i) const {{ return {m}.at(static_cast<std::size_t>(i)); }}")
                d(f"inline int {c}::{fname}_size() const {{ return static_cast<int>({m}.size()); }}")
                if es_mensaje(f.type):
                    w(f"    {t}* add_{fname}();")
                    d(f"inline {t}* {c}::add_{fname}() {{ return &{m}.emplace_back(); }}")
                miembros.append(f"    std::vector<{t}> {m};")
                casos_de_lectura.append((f.number, _leer_repetido(f, t, m, es_mensaje(f.type),
                                                                  es_enum(f.type))))
                continue
            caso = f.oneof
            if es_mensaje(f.type):
                w(f"    bool has_{a}() const;")
                w(f"    const {t}& {a}() const;")
                w(f"    {t}* mutable_{a}();")
                if caso:
                    k = f"k{_camel(fname)}"
                    d(f"inline bool {c}::has_{a}() const {{ return {caso}_caso_ == {k}; }}")
                    d(f"inline const {t}& {c}::{a}() const {{")
                    d(f"    return {caso}_caso_ == {k} && {m}.hay() ? {m}.valor() : {t}::default_instance();")
                    d("}")
                    d(f"inline {t}* {c}::mutable_{a}() {{ {caso}_caso_ = {k}; return &{m}.crea(); }}")
                else:
                    d(f"inline bool {c}::has_{a}() const {{ return {m}.hay(); }}")
                    d(f"inline const {t}& {c}::{a}() const {{ return {m}.hay() ? {m}.valor() : {t}::default_instance(); }}")
                    d(f"inline {t}* {c}::mutable_{a}() {{ return &{m}.crea(); }}")
                miembros.append(f"    detalle::Caja<{t}> {m};")
                marca = f"            {caso}_caso_ = k{_camel(fname)};\n" if caso else ""
                casos_de_lectura.append((f.number, f"""        case {f.number}: {{
            if (tipo != 2) {{ if (!lector.salta(tipo)) return false; break; }}
            std::size_t hasta;
            if (!lector.largo(hasta, fin)) return false;
{marca}            if (!{m}.crea()._lee(lector, hasta)) return false;
            break;
        }}"""))
                continue
            # escalar o enum singular
            if es_enum(f.type):
                w(f"    {t} {a}() const;")
                w(f"    void set_{fname}({t} valor);")
                miembros.append(f"    int {m} = 0;")
                if caso:
                    k = f"k{_camel(fname)}"
                    d(f"inline {t} {c}::{a}() const {{ return static_cast<{t}>({caso}_caso_ == {k} ? {m} : 0); }}")
                    d(f"inline void {c}::set_{fname}({t} valor) {{ {caso}_caso_ = {k}; {m} = valor; }}")
                else:
                    d(f"inline {t} {c}::{a}() const {{ return static_cast<{t}>({m}); }}")
                    d(f"inline void {c}::set_{fname}({t} valor) {{ {m} = valor; }}")
            else:
                ret = "const std::string&" if f.type == "string" else t
                w(f"    {ret} {a}() const;")
                w(f"    void set_{fname}({t} valor);")
                miembros.append(f"    {t} {m}{{}};")
                if caso:
                    k = f"k{_camel(fname)}"
                    w(f"    bool has_{a}() const;")
                    d(f"inline bool {c}::has_{a}() const {{ return {caso}_caso_ == {k}; }}")
                    if f.type == "string":
                        d(f"inline {ret} {c}::{a}() const {{ static const std::string vacio; return {caso}_caso_ == {k} ? {m} : vacio; }}")
                    else:
                        d(f"inline {ret} {c}::{a}() const {{ return {caso}_caso_ == {k} ? {m} : {t}{{}}; }}")
                    d(f"inline void {c}::set_{fname}({t} valor) {{ {caso}_caso_ = {k}; {m} = std::move(valor); }}")
                else:
                    d(f"inline {ret} {c}::{a}() const {{ return {m}; }}")
                    d(f"inline void {c}::set_{fname}({t} valor) {{ {m} = std::move(valor); }}")
            marca = f"            {caso}_caso_ = k{_camel(fname)};\n" if caso else ""
            casos_de_lectura.append((f.number, _leer_escalar(f, m, es_enum(f.type), marca)))

        w(" private:")
        for linea in miembros:
            w(linea)
        w("};")
        w("")

        d(f"inline bool {c}::_lee(detalle::Lector& lector, std::size_t fin) {{")
        d("    while (lector.pos() < fin) {")
        d("        std::uint64_t etiqueta;")
        d("        if (!lector.varint(etiqueta)) return false;")
        d("        const int tipo = static_cast<int>(etiqueta & 7);")
        if casos_de_lectura:
            d("        switch (etiqueta >> 3) {")
            for _, cuerpo in sorted(casos_de_lectura):
                d(cuerpo)
            d("        default:")
            d("            if (!lector.salta(tipo)) return false;")
            d("        }")
        else:
            d("        if (!lector.salta(tipo)) return false;")
        d("    }")
        d("    return lector.pos() == fin;")
        d("}")
        d("")

    w("// --- definiciones: DESPUÉS de todas las clases, para que ningún contenedor se")
    w("// use con un tipo todavía incompleto (lo que C++ exige para vector y compañía)")
    w("")
    s.extend(definiciones)
    w("}  // namespace suriax::hir::v0")
    w("")
    return "\n".join(s)


def _leer_escalar(f, m: str, es_enum: bool, marca: str) -> str:
    if f.type == "string":
        cuerpo = f"if (!lector.texto({m}, fin)) return false;"
        esperado = 2
    elif f.type == "double":
        cuerpo = (f"std::uint64_t bits; if (!lector.fijo64(bits)) return false; "
                  f"{m} = std::bit_cast<double>(bits);")
        esperado = 1
    elif f.type == "float":
        cuerpo = (f"std::uint32_t bits; if (!lector.fijo32(bits)) return false; "
                  f"{m} = std::bit_cast<float>(bits);")
        esperado = 5
    else:
        conv = "static_cast<int>(v)" if es_enum else (
            "v != 0" if f.type == "bool" else f"static_cast<{_CPP_ESCALAR[f.type]}>(v)")
        cuerpo = f"std::uint64_t v; if (!lector.varint(v)) return false; {m} = {conv};"
        esperado = 0
    return f"""        case {f.number}: {{
            if (tipo != {esperado}) {{ if (!lector.salta(tipo)) return false; break; }}
{marca}            {cuerpo}
            break;
        }}"""


def _leer_repetido(f, t: str, m: str, es_msg: bool, es_enum: bool) -> str:
    if es_msg:
        return f"""        case {f.number}: {{
            if (tipo != 2) {{ if (!lector.salta(tipo)) return false; break; }}
            std::size_t hasta;
            if (!lector.largo(hasta, fin)) return false;
            if (!{m}.emplace_back()._lee(lector, hasta)) return false;
            break;
        }}"""
    if f.type == "string":
        return f"""        case {f.number}: {{
            if (tipo != 2) {{ if (!lector.salta(tipo)) return false; break; }}
            if (!lector.texto({m}.emplace_back(), fin)) return false;
            break;
        }}"""
    if f.type in ("double", "float"):
        raise SystemExit(f"repetido de {f.type} no soportado (campo {f.name})")
    conv = "static_cast<int>(v)" if es_enum else (
        "v != 0" if f.type == "bool" else f"static_cast<{_CPP_ESCALAR[f.type]}>(v)")
    elemento = "int" if es_enum else _CPP_ESCALAR[f.type]
    if es_enum:
        conv = f"static_cast<{t}>(v)"
        elemento = t
    return f"""        case {f.number}: {{
            if (tipo == 2) {{   // empaquetado (lo normal en proto3)
                std::size_t hasta;
                if (!lector.largo(hasta, fin)) return false;
                while (lector.pos() < hasta) {{
                    std::uint64_t v;
                    if (!lector.varint(v)) return false;
                    {m}.push_back({conv});
                }}
                if (lector.pos() != hasta) return false;
            }} else if (tipo == 0) {{
                std::uint64_t v;
                if (!lector.varint(v)) return false;
                {m}.push_back({conv});
            }} else if (!lector.salta(tipo)) {{
                return false;
            }}
            break;
        }}"""


_INFRAESTRUCTURA = r"""// --- infraestructura: lectura del formato y contenedores ---------------------

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
"""


def main(argv) -> int:
    texto = generar()
    if "--check" in argv:
        actual = ""
        if os.path.isfile(_SALIDA):
            with open(_SALIDA, encoding="utf-8") as fh:
                actual = fh.read()
        if actual != texto:
            print(f"{_SALIDA} esta desactualizado: corre 'python backend/tools/gen_hir_cpp.py'",
                  file=sys.stderr)
            return 1
        return 0
    with open(_SALIDA, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(texto)
    print(f"generado {_SALIDA}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

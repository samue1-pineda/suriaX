// Binding pybind11 del core de memoria (mem_core.hpp). Es el ADAPTADOR
// Python del backend: convierte objetos de Python <-> Value del core y guarda
// lo NO primitivo (str, struct, puntero...) en un "extern store" propio del
// binding, para que el core siga siendo C++ puro (agnostico del target).
//
// Contrato con el interprete (runtime/interpreter/memory/native.py):
//   create(obj)      -> handle
//   read(handle)     -> (status, value)   status 0 = OK
//   write(handle,obj)-> status
//   move_out(handle) -> (status, value)
//   free_cell(handle)-> status
//   peek(handle)     -> value (crudo, sin chequear estado; para reprs)
//   state(handle)    -> 0 LIVE / 1 MOVED / 2 FREED / -1 handle invalido
//   total/live_count/reset
//
// Los codigos de estado (no excepciones) los traduce el lado Python a los
// errores de runtime RT001/RT002/RT003 con su linea/columna.

#include <pybind11/pybind11.h>

#include <string>
#include <vector>

#include "mem_core.hpp"

namespace py = pybind11;
using namespace suriax_mem;

std::string banner() {
    return "[memory_c] backend de memoria real activo — agnostico del target "
           "(interprete / VM-JIT / LLVM-WASM) via pybind11";
}

// Manager con estado, expuesto como clase de Python. El interprete crea una
// instancia por proceso y la 'reset'-ea al empezar cada run.
class Memory {
public:
    Handle create(const py::object& v) { return mm_.create(to_value(v)); }

    py::tuple read(Handle h) {
        Read r = mm_.read(h);
        return py::make_tuple(r.status,
                              r.status == OK ? from_value(r.value) : py::none());
    }

    int32_t write(Handle h, const py::object& v) {
        return mm_.write(h, to_value(v));
    }

    py::tuple move_out(Handle h) {
        Read r = mm_.move_out(h);
        return py::make_tuple(r.status,
                              r.status == OK ? from_value(r.value) : py::none());
    }

    int32_t free_cell(Handle h) { return mm_.free_cell(h); }

    py::object peek(Handle h) { return from_value(mm_.peek(h)); }

    int32_t state(Handle h) { return mm_.state_of(h); }

    std::size_t total() { return mm_.total(); }
    std::size_t live_count() { return mm_.live_count(); }

    void reset() {
        mm_.reset();
        extern_.clear();
    }

    // celdas totales del core + objetos externos retenidos (introspeccion/tests).
    std::size_t extern_count() { return extern_.size(); }

private:
    Manager mm_;
    // objetos de Python NO primitivos, referenciados por id desde el core.
    // Monotonico durante un run (como los handles); 'reset' lo vacia.
    std::vector<py::object> extern_;

    Value to_value(const py::object& o) {
        if (o.is_none()) return Value{T_NULL, 0, 0.0};
        // bool ANTES que int: en Python bool es subclase de int.
        if (py::isinstance<py::bool_>(o))
            return Value{T_BOOL, static_cast<int64_t>(o.cast<bool>()), 0.0};
        if (py::isinstance<py::int_>(o))
            return Value{T_INT, o.cast<int64_t>(), 0.0};
        if (py::isinstance<py::float_>(o))
            return Value{T_FLOAT, 0, o.cast<double>()};
        // cualquier otra cosa (str/char, struct, puntero, namespace...) es
        // opaca para el core: se guarda tal cual y se referencia por id.
        extern_.push_back(o);
        return Value{T_EXTERN, static_cast<int64_t>(extern_.size() - 1), 0.0};
    }

    py::object from_value(const Value& v) {
        switch (v.tag) {
            case T_NULL: return py::none();
            case T_BOOL: return py::bool_(v.i != 0);
            case T_INT: return py::int_(v.i);
            case T_FLOAT: return py::float_(v.f);
            case T_EXTERN: return extern_[static_cast<std::size_t>(v.i)];
        }
        return py::none();
    }
};

PYBIND11_MODULE(memory_c, m, py::mod_gil_not_used()) {
    m.doc() =
        "Backend de memoria real de suriaX (punteros, &, move-semantics). "
        "Agnostico del target: lo consumen el interprete, la VM/JIT y "
        "LLVM IR/WASM por igual.";

    m.def("banner", &banner,
          "Devuelve un mensaje de confirmacion del backend nativo de memoria");

    py::class_<Memory>(m, "Memory")
        .def(py::init<>())
        .def("create", &Memory::create)
        .def("read", &Memory::read)
        .def("write", &Memory::write)
        .def("move_out", &Memory::move_out)
        .def("free_cell", &Memory::free_cell)
        .def("peek", &Memory::peek)
        .def("state", &Memory::state)
        .def("total", &Memory::total)
        .def("live_count", &Memory::live_count)
        .def("extern_count", &Memory::extern_count)
        .def("reset", &Memory::reset);
}

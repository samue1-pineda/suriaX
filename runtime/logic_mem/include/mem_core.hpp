// Core de memoria logica de suriaX — C++ PURO, sin pybind11 ni Python.
//
// Es la pieza AGNOSTICA DEL TARGET y DESACOPLADA que pide el diseño: no
// depende de nadie, asi que el interprete (via pybind11), la VM de bytecode y
// el backend LLVM/WASM la pueden enlazar por igual SIN "depende de X y no se
// encontro". Aqui vive la LOGICA: la maquina de estados de cada celda
// (LIVE/MOVED/FREED), los punteros (una celda + permiso) y las move-semantics.
// El valor concreto es un `Value` etiquetado (primitivos + un id EXTERN opaco
// que el host —p. ej. el binding de Python— usa para lo que no es primitivo);
// el core NUNCA toca objetos de Python.
//
// Regiones (RBMM) NO estan aqui todavia: primero se valida que punteros/&/move
// funcionen de verdad desde este backend; las regiones se construyen ENCIMA.
#pragma once

#include <cstddef>
#include <cstdint>
#include <vector>

namespace suriax_mem {

// etiqueta del valor almacenado en una celda.
enum Tag : int32_t {
    T_NULL = 0,
    T_INT = 1,     // usa 'i'
    T_FLOAT = 2,   // usa 'f'
    T_BOOL = 3,    // usa 'i' (0/1)
    T_EXTERN = 4,  // usa 'i' como id opaco del host (str/struct/puntero/...)
};

// estado de una celda (mismas semanticas que memory/pointer.py::CellState).
enum State : int32_t {
    S_LIVE = 0,   // legible / escribible
    S_MOVED = 1,  // su valor fue transferido con 'move'
    S_FREED = 2,  // liberada con 'free'
};

// codigo de resultado de una operacion. Se devuelve por VALOR (no excepciones)
// para no acoplar el ABI: la VM/WASM chequean el codigo sin depender del
// runtime de excepciones de C++.
enum Status : int32_t {
    OK = 0,
    USE_AFTER_MOVE = 1,  // leer/mover una celda MOVED
    USE_AFTER_FREE = 2,  // acceder a una celda FREED
    DOUBLE_MOVE = 3,     // 'move' sobre una ya MOVED
    DOUBLE_FREE = 4,     // 'free' sobre una ya FREED
    BAD_HANDLE = 5,      // handle fuera de rango (nunca deberia pasar)
};

struct Value {
    int32_t tag = T_NULL;
    int64_t i = 0;
    double f = 0.0;
};

struct Cell {
    Value value;
    int32_t state = S_LIVE;
};

struct Read {
    int32_t status;
    Value value;
};

// Handle = indice en el slab. Monotonico (no se reutiliza durante un run): un
// run de tree-walk crea un numero ACOTADO de celdas y el proceso las libera al
// terminar; 'reset()' recicla todo entre runs. Sin reuso -> imposible un
// "stale handle". La reclamacion fina por celda llegara con las REGIONES (su
// proposito es justo liberar en bloque), no antes.
using Handle = uint64_t;

class Manager {
public:
    Handle create(const Value& v) {
        cells_.push_back(Cell{v, S_LIVE});
        return static_cast<Handle>(cells_.size() - 1);
    }

    Read read(Handle h) const {
        if (h >= cells_.size()) return {BAD_HANDLE, Value{}};
        const Cell& c = cells_[h];
        if (c.state == S_MOVED) return {USE_AFTER_MOVE, Value{}};
        if (c.state == S_FREED) return {USE_AFTER_FREE, Value{}};
        return {OK, c.value};
    }

    // 'write' REVIVE una celda MOVED (un valor nuevo no esta movido — misma
    // regla que memory_check aplica estaticamente al reasignar). FREED no.
    int32_t write(Handle h, const Value& v) {
        if (h >= cells_.size()) return BAD_HANDLE;
        Cell& c = cells_[h];
        if (c.state == S_FREED) return USE_AFTER_FREE;
        c.value = v;
        c.state = S_LIVE;
        return OK;
    }

    Read move_out(Handle h) {
        if (h >= cells_.size()) return {BAD_HANDLE, Value{}};
        Cell& c = cells_[h];
        if (c.state == S_MOVED) return {DOUBLE_MOVE, Value{}};
        if (c.state == S_FREED) return {USE_AFTER_FREE, Value{}};
        Value v = c.value;
        c.value = Value{};
        c.state = S_MOVED;
        return {OK, v};
    }

    int32_t free_cell(Handle h) {
        if (h >= cells_.size()) return BAD_HANDLE;
        Cell& c = cells_[h];
        if (c.state == S_FREED) return DOUBLE_FREE;
        c.value = Value{};
        c.state = S_FREED;
        return OK;
    }

    // lectura CRUDA (ignora el estado): para reprs/trazas, no es una
    // instruccion del lenguaje. Devuelve Null si el handle es invalido.
    Value peek(Handle h) const {
        return h < cells_.size() ? cells_[h].value : Value{};
    }

    int32_t state_of(Handle h) const {
        return h < cells_.size() ? cells_[h].state : -1;
    }

    std::size_t total() const { return cells_.size(); }

    std::size_t live_count() const {
        std::size_t n = 0;
        for (const Cell& c : cells_) if (c.state == S_LIVE) ++n;
        return n;
    }

    void reset() { cells_.clear(); }

private:
    std::vector<Cell> cells_;
};

}  // namespace suriax_mem

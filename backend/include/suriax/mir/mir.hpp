// MIR: la representacion que el backend nativo EJECUTA.
//
// Es la etapa que sigue a 'hir/resolve.hpp'. Aquel demuestra que el backend
// ENTIENDE el HIR (a que llama cada llamada, que slots tiene cada marco);
// este convierte ese entendimiento en algo que una maquina puede correr.
//
// Dos decisiones vienen del ROADMAP (Fase 6) y no de aqui:
//
//   * **registros, no pila**. Un IR de registros hace explicito el flujo de
//     datos —cada instruccion dice de donde lee y donde escribe—, que es lo
//     que necesita el JIT para asignar registros de verdad y lo que necesita
//     la verificacion de PRESTAMOS para seguir el tiempo de vida de un 'ptr'.
//     Una pila esconde ambas cosas detras del orden de evaluacion.
//   * **CFG explicito**. El HIR tiene 'if'/'while' anidados; aqui hay
//     BLOQUES con un terminador. El control de flujo deja de estar implicito
//     en la forma del arbol y pasa a ser un grafo que se puede recorrer, que
//     es la unica forma de hacer analisis de flujo (y de dibujarlo, ver
//     ROADMAP Fase 7).
//
// Los registros son VIRTUALES e ilimitados: cada valor intermedio estrena el
// suyo. Asignarlos a registros de maquina es trabajo del JIT, y hacerlo aqui
// seria decidir dos veces.
//
// Los LOCALES no son registros: viven en el marco y se leen/escriben con
// 'LoadLocal'/'StoreLocal'. Separarlos es lo que permite que un local tenga
// direccion (un 'ptr' apunta a el) sin que cada valor intermedio la tenga.
//
// Errores por LISTA y no por excepciones, igual que el resto del backend.
#pragma once

#include <cstdint>
#include <ostream>
#include <string>
#include <unordered_map>
#include <vector>

#include "suriax/hir/resolve.hpp"

namespace suriax::mir {

namespace pb = ::suriax::hir::pb;

//: Registro virtual. 'kNoReg' = la instruccion no produce valor.
using Reg = std::uint32_t;
inline constexpr Reg kNoReg = 0xFFFFFFFFu;

//: Indice de bloque dentro de una funcion.
using BlockId = std::uint32_t;

// Tipo de un valor en el MIR. Solo tres: el ancho de maquina es lo unico que
// la ejecucion necesita saber, y las distinciones del lenguaje (bool vs char,
// enum vs int) ya las verifico el frontend.
enum class Type : std::uint8_t { I64, F64, Void };

const char* to_string(Type type);

enum class Op : std::uint8_t {
    ConstI,      // dst <- imm
    ConstF,      // dst <- fimm
    ConstStr,    // dst <- indice de la constante 'imm' en Program::strings
    Move,        // dst <- a
    LoadLocal,   // dst <- marco[slot]
    StoreLocal,  // marco[slot] <- a
    LoadGlobal,  // dst <- globales[slot]
    StoreGlobal, // globales[slot] <- a

    AddI, SubI, MulI, DivI, RemI,
    AddF, SubF, MulF, DivF,

    EqI, NeI, LtI, LeI, GtI, GeI,
    EqF, NeF, LtF, LeF, GtF, GeF,

    NegI, NegF, Not,

    // conversiones entre anchos ('cast<float>(x)'). El par ORIGEN->DESTINO
    // va en la instruccion porque en una maquina no es la misma operacion en
    // los dos sentidos.
    IntToFloat,
    FloatToInt,

    // AGREGADOS. Un struct es un objeto de N campos en el monton de la VM y
    // su valor es un HANDLE: cabe en un registro, se copia como un entero y
    // el campo se alcanza por INDICE, que es lo que el frontend ya resolvio
    // (los nombres no llegan hasta aqui).
    Alloc,       // dst <- objeto de 'imm' campos
    // Indexado CRUDO de un bloque: el indice es un valor, no una constante.
    // Es lo que separa un bloque de un struct — los campos de un struct los
    // nombra el fuente y se resuelven al compilar; los de un bloque los
    // calcula el programa.
    //
    // Reservar y liberar ese bloque NO son instrucciones: son primitivas del
    // host ('__reserve__', '__copy__', '__release__' de 'lib/mem'), por la
    // misma razon que lo es '__write__'. Meterlas aqui obligaria a cada
    // consumidor del MIR a implementar el asignador, que es justo lo que el
    // patron prototipo+intrinseco existe para evitar.
    GetIndex,    // dst <- bloque(a)[b]
    SetIndex,    // bloque(a)[b] <- c
    GetField,    // dst <- objeto(a).campo[imm]
    SetField,    // objeto(a).campo[imm] <- b
    Copy,        // dst <- COPIA superficial de objeto(a) (semantica de valor)

    // NATIVOS de un primitivo. No son hooks (SEM006 prohibe colgarle uno a
    // un primitivo) ni prototipos del host: los implementa el backend, y por
    // eso son instrucciones y no llamadas.
    LenStr,      // dst <- longitud de la cadena(a), en caracteres
    IndexStr,    // dst <- cadena(a)[b], como char
    ConcatStr,   // dst <- cadena(a) ++ cadena(b)
    // Comparar dos cadenas es comparar su TEXTO, no su indice: dos cadenas
    // calculadas por caminos distintos son iguales y sus indices no.
    EqStr, NeStr,
    ToStr,       // dst <- el valor 'a' escrito como texto, segun 'imm':
                 //        0 int | 1 float | 2 bool | 3 char

    // 'move x' / 'free x': el local del slot deja de ser suyo. No calcula
    // nada —el valor sigue donde estaba— pero es la unica huella que deja la
    // TRANSFERENCIA en el MIR, y sin ella la verificacion de propiedad
    // tendria que adivinarla mirando escrituras de banderas.
    //
    // 'imm' = slot de la bandera de vivo que hay que apagar, o -1 si el tipo
    // no se destruye.
    MarkMoved,

    // '&x': el registro pasa a REFERIRSE al local del slot. Como el valor de
    // un tipo con nombre ya es su handle, no hay nada que calcular; lo que
    // deja es la marca de que existe un prestamo, que es lo que la
    // verificacion de tiempos de vida necesita seguir.
    Borrow,      // dst <- marco[slot], anotado como prestamo

    Call,        // dst <- funcs[func](args...)
    CallHost,    // dst <- host[func](args...): un prototipo, lo cumple el host
};

const char* to_string(Op op);

// Una instruccion. 'args' solo lo usa 'Call'; lo demas cabe en 'a'/'b'.
struct Inst {
    Op op = Op::Move;
    Reg dst = kNoReg;
    Reg a = kNoReg;
    Reg b = kNoReg;
    //: tercer operando. Solo lo usa la instruccion que escribe en un sitio
    //: CALCULADO ('SetIndex'): con dos registros no caben a la vez el
    //: bloque, el indice y el valor.
    Reg c = kNoReg;
    std::int64_t imm = 0;
    double fimm = 0.0;
    std::uint32_t slot = 0;
    int func = -1;                 // indice en Program::functions
    std::vector<Reg> args;
    // posicion en el fuente: un fallo en ejecucion tiene que poder decir
    // DONDE, y despues del lowering el arbol ya no esta.
    std::uint32_t line = 0;
    std::uint32_t col = 0;
    // La puso el LOWERING, no el programa (el epilogo de un drop, una
    // bandera). La verificacion de propiedad no la mira: un destructor lee su
    // valor justamente porque puede estar movido, y de eso ya responde la
    // bandera que lo guarda. Sin esta marca cada drop se denunciaria a si
    // mismo.
    bool synthetic = false;
};

// Como termina un bloque. Todo bloque termina, y termina en UNA de estas:
// sin terminador no hay grafo, hay una lista.
enum class Term : std::uint8_t {
    Jump,        // -> target
    Branch,      // cond ? target : otherwise
    Return,      // devuelve 'value' (o nada si '!has_value')
    Throw,       // lanza 'value', etiquetado con el tipo 'tag'
    Unreachable, // el lowering no supo cerrar: es un error, no un caso
};

const char* to_string(Term term);

struct Block {
    std::vector<Inst> insts;
    Term term = Term::Unreachable;
    Reg cond = kNoReg;
    BlockId target = 0;
    BlockId otherwise = 0;
    Reg value = kNoReg;
    bool has_value = false;
    // Un 'throw' es una ARISTA como cualquier otra, y esta es su salida: a
    // donde va el control si algo lanza aqui dentro —el propio terminador o
    // una llamada—. -1 = no hay 'try' alrededor y la excepcion sale de la
    // funcion.
    //
    // Va en el bloque y no en la instruccion porque un 'try' protege una
    // REGION, no una llamada suelta; asi el CFG sigue siendo dibujable y el
    // JIT tiene una sola pregunta que hacer por bloque.
    int handler = -1;
    // etiqueta del tipo lanzado (indice en Program::tags), solo si
    // 'term == Throw'. -1 = se relanza lo que ya viajaba.
    int tag = -1;
};

struct Function {
    std::string unit;              // "" = unidad principal
    std::string name;
    std::vector<Type> slots;       // parametros primero, como en 'resolve'
    // Como se llamaban. La EJECUCION no los usa —un slot es un indice— pero
    // un diagnostico que diga "el slot 3" no le sirve a nadie, y quien lee el
    // MIR necesita reconocer su programa. Los slots que inventa el lowering
    // (banderas, aterrizajes) van con nombre entre '<>' para que se vea que
    // no los escribio el usuario.
    std::vector<std::string> slot_names;
    std::uint32_t params = 0;
    Type result = Type::Void;
    std::vector<Block> blocks;
    std::uint32_t regs = 0;        // cuantos registros virtuales usa
    bool prototype = false;        // sin cuerpo: lo aporta el host
    // Donde aterriza una excepcion atrapada: el valor y la etiqueta de su
    // tipo. Los pone quien lanza y los lee el pad, que es lo que permite que
    // el filtro del 'catch' se decida con una comparacion de enteros en vez
    // de preguntando el tipo de un valor en ejecucion.
    int throw_slot = -1;
    int tag_slot = -1;
};

// Algo que el lowering no supo bajar, con su posicion. Que la lista quede
// vacia es la prueba de que el MIR cubre el programa entero.
struct Unsupported {
    std::string what;
    std::uint32_t line = 0;
    std::uint32_t col = 0;
};

// Una variable de nivel de modulo. Vive mientras vive el programa y la ve
// cualquier funcion, que es justo lo que un slot no puede hacer.
struct Global {
    std::string name;
    Type type = Type::I64;
};

struct Program {
    std::vector<Function> functions;
    std::unordered_map<std::string, std::size_t> index;
    // Constantes de cadena, deduplicadas por texto. Una 'str' es su INDICE
    // aqui: asi cabe en un registro y no hace falta memoria dinamica para
    // pasarla, compararla o devolverla. Es la misma decision que tomo el
    // target web, y por el mismo motivo.
    // El texto de una 'str' es el indice de su entrada aqui. En ejecucion la
    // tabla CRECE: concatenar o interpolar produce una cadena que no estaba
    // en el fuente, y darle un indice nuevo la deja pasar por registro como
    // cualquier otra. Esto es la tabla INICIAL, con las del programa.
    std::vector<std::string> strings;
    // Primitivas que aporta QUIEN EJECUTA ('__write__'). Son los prototipos
    // sin cuerpo: el MIR guarda su nombre y la VM decide como cumplirlos.
    std::vector<std::string> hosts;
    std::vector<Global> globals;
    // Identidad de los tipos que se lanzan y se atrapan, deduplicada. Un
    // 'catch (E e)' filtra por TIPO, y el tipo de lo lanzado solo se sabe en
    // ejecucion: viaja como el indice de su clave aqui.
    std::vector<std::string> tags;
    // El bloque de inicializacion de las globales, si alguna necesita
    // calcularse. -1 = ninguna.
    int init = -1;
    int entry = -1;
    std::vector<Unsupported> unsupported;
};

// HIR resuelto -> MIR. No lanza: lo que no se pudo bajar queda en
// 'unsupported' con su posicion, y esa funcion se deja sin bloques.
Program lower(const hir::Image& image, const hir::Program& resolved);

// El MIR en texto: una linea por instruccion, agrupadas por bloque. Es la
// vista que hace verificable el lowering — y la que dibuja el CFG.
void write_mir(const Program& program, std::ostream& out);

}  // namespace suriax::mir

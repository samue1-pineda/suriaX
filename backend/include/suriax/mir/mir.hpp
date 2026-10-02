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
    RemF,        // fmod: el signo es el del dividendo, como C (y NaN si b es 0)

    EqI, NeI, LtI, LeI, GtI, GeI,
    EqF, NeF, LtF, LeF, GtF, GeF,

    NegI, NegF, Not,

    // BITS, entre enteros de 64 bits con signo. '<<' envuelve y '>>' es
    // aritmetico (conserva el signo); un desplazamiento fuera de [0, 64) es
    // la excepcion EXC005, como en el interprete.
    AndI, OrI, XorI, ShlI, ShrI, NotI,

    // conversiones entre anchos ('cast<float>(x)'). El par ORIGEN->DESTINO
    // va en la instruccion porque en una maquina no es la misma operacion en
    // los dos sentidos.
    IntToFloat,
    FloatToInt,
    // hacia un tipo de ANCHO FIJO de libreria ('cast<dt.int8>(300)'). Son el
    // cuerpo que el host pone a los '__cast__' PROTOTIPO de 'dt_variables':
    // el ancho no se puede escribir en suriaX, asi que lo aplica la maquina.
    NarrowI,     // dst <- a truncado a 'imm' bits CON SIGNO (8/16/32), como C
    NarrowF,     // dst <- a redondeado a IEEE-754 de 'imm' bits (16/32)

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
    Copy,        // dst <- COPIA de objeto(a) (semantica de valor): nueva, y
                 //        PROFUNDA en los campos que son objetos propios
    // Libera objeto(a) y, en profundidad, los objetos propios de sus campos
    // (y las celdas de un bloque cuyo elemento es un objeto). Un handle que
    // no es un objeto vivo (-1 de un campo cedido, 0 de una celda sin usar)
    // no hace nada: es lo que deja liberar sin preguntar antes.
    Free,
    // Lo atrapado por un 'catch (e)' SIN tipo: al compilar no se sabe si es
    // un objeto (un 'throw 7' no lo es). Se libera solo si la etiqueta con
    // que llego ('b') es la de un tipo objeto, o si es una excepcion del
    // runtime (EXCxxx).
    FreeLanzado,
    // DESTRUIR POR TIPO ('drop glue'): destruye objeto(a) segun su FORMA
    // —su '__free__' si lo declara (y ese se hace cargo de sus campos); si
    // no, sus campos propios y sus bloques, del ultimo al primero; un bloque,
    // sus celdas no vacias— y despues libera su memoria como 'Free'. Es lo
    // que el frontend no pudo aplanar ('Drop.by_type', 'drops_old'): un 'T',
    // un 'catch (e)' sin tipo, el valor viejo de una asignacion.
    //   'b' (si hay): la etiqueta de un 'catch (e)' sin tipo; como en
    //       'FreeLanzado', solo se destruye si es la de un tipo objeto.
    //   'imm' = 1: solo si objeto(a) es un BLOQUE (el de un campo puntero,
    //       que puede apuntar a un valor ajeno y ese no se toca).
    Destruir,
    // Termina el programa con un error fatal: el texto es la cadena 'imm'.
    // Lo usa un 'finally' que lanza mientras ya viajaba otra excepcion
    // (RT022): no hay 'catch' que pueda recibir dos.
    Fallar,

    // NATIVOS de un primitivo. No son hooks (SEM006 prohibe colgarle uno a
    // un primitivo) ni prototipos del host: los implementa el backend, y por
    // eso son instrucciones y no llamadas.
    LenStr,      // dst <- longitud de la cadena(a), en caracteres
    IndexStr,    // dst <- cadena(a)[b], como char
    ConcatStr,   // dst <- cadena(a) ++ cadena(b)
    // Comparar dos cadenas es comparar su TEXTO, no su indice: dos cadenas
    // calculadas por caminos distintos son iguales y sus indices no.
    EqStr, NeStr,
    // 'hash(x)' de un primitivo, igual que el interprete: 'imm' 0 = entero
    // (splitmix64 de sus 64 bits), 1 = cadena (FNV-1a de 64 bits sobre su
    // UTF-8), 2 = char (el FNV-1a de su texto: igual que un 'str' de un
    // caracter, que en el interprete es el mismo valor)
    Hash,
    // Ordenar dos cadenas: por punto de codigo, que en UTF-8 es comparar los
    // bytes sin signo (lo mismo que Python).
    LtStr, LeStr, GtStr, GeStr,
    ToStr,       // dst <- el valor 'a' escrito como texto, segun 'imm'
                 //        (ver 'modo_de_texto'): los 3 bits bajos dicen QUE
                 //        es —0 int | 1 float | 2 bool | 3 char | 4 cadena
                 //        | 5 enum suma (su forma dice los nombres) | 6 enum
                 //        sin payload | 7 struct (su forma dice los campos:
                 //        'Punto{x: 1}')—, el bit 3 que puede ser null (-1; un
                 //        escalar viene en su CAJA) y lo de arriba, en un
                 //        enum sin payload, su tabla en 'Program::enums'
    // 'a == b' entre dos 'T?' de un escalar (CAJAS: -1 = null): iguales si
    // los dos son null o si los dos tienen el mismo valor. 'imm' = 1 si el
    // escalar es un float (se compara como float: 0.0 == -0.0, NaN != NaN).
    EqCaja,
    // dst <- el valor 'a' escrito con el FORMATO 'Program::formatos[imm]'
    // ('{x!r}', '{n:08b}', '{f:.2f}'): su modo de 'ToStr', si es la
    // representacion, y el especificador ya partido
    Formatear,

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
    // 'Call' a un '__free__': si el destructor lanza, el programa termina
    // (RT021) en vez de que la excepcion suba — habria dos en vuelo.
    bool destructor = false;
    // 'MarkMoved' que viene de un 'free' y no de un 'move': el slot queda
    // LIBERADO (RT003 al volver a usarlo) en vez de movido (RT001).
    bool libera = false;
    // 'Alloc': la FORMA del objeto nuevo (indice en Program::layouts, -1 =
    // ningun campo es un objeto propio). 'CallHost' a '__reserve__': la forma
    // de sus celdas si el elemento es un objeto (-1 = escalares).
    std::int32_t layout = -1;
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
    // Hay algun 'move'/'free' de un local: la VM lleva un byte de ESTADO por
    // slot (vivo/movido/liberado) para dar RT001/RT002/RT003 como el
    // interprete. Una funcion sin ninguno no paga ni el byte.
    bool vigila_estado = false;
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
    // la unidad que la declara ('' = el main): dos librerias pueden tener una
    // global con el mismo nombre, y el nombre solo no dice cual es
    std::string unit;
    // su valor es un objeto propio: la VM lo libera cuando 'main' vuelve
    // (sin su '__free__': el interprete tampoco lo corre al salir)
    bool propia = false;
    // un escalar al que se le toma la direccion ('&contador'): la global
    // guarda el handle de su CELDA, como un local en el mismo caso
    bool celda = false;
};

// La FORMA de un objeto del monton: que campos son objetos PROPIOS (un
// struct por valor, un enum con payload), que hay que copiar al copiar el
// objeto y liberar al liberarlo. Un escalar, una cadena o un puntero no son
// propios: un puntero es un prestamo, y una cadena se recoge aparte.
//
// Un struct tiene una sola lista; un enum SUMA, una por variante (indexada
// por la etiqueta), porque cada variante lleva otro payload. Los indices son
// posiciones en el objeto (en una suma, el campo 0 es la etiqueta).
//
// Un BLOQUE de 'mem' guardado en un campo (el almacenamiento de un Vector) es
// del struct que lo guarda: se copia y se libera con el, como el buffer de
// un std::vector. 'bloques' son los campos de tipo puntero; en ejecucion
// cuentan solo si lo que guardan es un bloque (un puntero a un struct con
// nombre sigue siendo un prestamo).
struct Layout {
    std::string nombre;             // el tipo, para leer el MIR
    bool suma = false;
    std::vector<std::vector<std::uint32_t>> propios;
    std::vector<std::vector<std::uint32_t>> bloques;
    // Solo de un enum SUMA, para escribirlo en un f-string ('Nodo(3, x)'):
    // el nombre de cada variante y, por variante, el modo de 'ToStr' de cada
    // campo de su payload (-1 = no se sabe escribir).
    std::vector<std::string> variantes;
    std::vector<std::vector<std::int32_t>> textos;
    // Solo de un STRUCT, para escribirlo ('Punto{x: 1, y: 2}'): el nombre de
    // cada campo, en orden; sus modos de 'ToStr' van en 'textos[0]' (con el
    // bit de null si el campo guarda una celda).
    std::vector<std::string> campos;
    // El '__free__' de este tipo concreto (indice en Program::functions: la
    // instancia, si el hook es de un generico), o -1. Lo usa 'Destruir'.
    std::int32_t destructor = -1;
};

// Como cruza un valor a C++ en un '#extern cpp'. Es la tabla de
// 'runtime/extern_cpp.py' (y la de 'htims/utils/cxx.py', que genera el
// prototipo que el usuario implementa): 'int' es int64, 'float' double,
// 'char' un code point (uint32), 'str' un 'const char*' UTF-8 y un puntero
// el buffer de sus celdas.
enum class Abi : std::uint8_t {
    Nada,              // 'void' (solo de retorno)
    Entero,
    Flotante,
    Logico,
    Caracter,
    Cadena,            // solo de parametro
    Bloque,            // 'int ptr' / 'float ptr' (o 'bool ptr'): el buffer real
    BloqueSinMaquina,  // un puntero a algo sin representacion de maquina: RT018 al llamar
    Byte,              // 'byte': un uint8_t
    BloqueDeBytes,     // 'byte ptr': el buffer compacto de la VM, un uint8_t*
};

// Los NOMBRES de un enum sin payload, para escribirlo en un f-string: en
// ejecucion es un entero ('Http.OK' vale 200) y el entero solo no dice que
// variante es. Tambien las variantes sin payload de un enum suma se escriben
// por su nombre, pero esas estan en su 'Layout'.
struct NombresEnum {
    std::string nombre;
    std::vector<std::pair<std::int64_t, std::string>> items;
};

// Un '{x!r:08b}' de un f-string, ya partido (ver 'Op::Formatear').
struct Formato {
    std::int64_t modo = 0;       // el de 'ToStr'
    bool repr = false;           // '!r': comillas en una cadena, 'Color.Verde'...
    bool cero = false;           // '0': rellenar con ceros un numero
    std::int32_t ancho = 0;      // 0 = sin ancho
    std::int32_t precision = -1; // solo con 'f'; -1 = la de siempre (6)
    char clase = 0;              // 'd' 'x' 'X' 'b' 'o' 'f', o 0
};

// El modo de 'ToStr' partido en sus tres piezas.
constexpr std::int64_t kTextoNulable = 8;
inline std::int64_t modo_de_texto(std::int64_t base, bool nulable, std::int64_t tabla = 0) {
    return base | (nulable ? kTextoNulable : 0) | (tabla << 4);
}

// La firma de una primitiva vista desde C++.
struct Firma {
    std::vector<Abi> params;
    Abi retorno = Abi::Nada;
    // por que no cruza la frontera ("" = cruza), con las palabras del interprete
    std::string sin_abi;
};

struct Program {
    std::vector<Function> functions;
    std::vector<Layout> layouts;
    // los nombres de cada enum sin payload que alguien escribe (ver 'ToStr')
    std::vector<NombresEnum> enums;
    // los formatos de los f-strings ('Op::Formatear'), deduplicados
    std::vector<Formato> formatos;
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
    // paralelo a 'hosts': como cruza cada una a C++ ('#extern cpp')
    std::vector<Firma> firmas_host;
    std::vector<Global> globals;
    // Identidad de los tipos que se lanzan y se atrapan, deduplicada. Un
    // 'catch (E e)' filtra por TIPO, y el tipo de lo lanzado solo se sabe en
    // ejecucion: viaja como el indice de su clave aqui.
    std::vector<std::string> tags;
    // paralelo a 'tags': 1 si los valores de ese tipo son objetos propios
    std::vector<std::uint8_t> tags_objeto;
    // paralelo a 'tags': como se escribe un valor de ese tipo ('ToStr', -1 =
    // no se sabe); con esto un 'throw' que nadie atrapa dice QUE lanzo
    std::vector<std::int64_t> tags_texto;
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

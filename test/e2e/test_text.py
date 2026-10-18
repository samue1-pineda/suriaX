"""e2e/text — la librería 'text' para herramientas que analizan texto.

Partir ('split', 'split_whitespace', 'lines'), recortar ('trim*'), buscar
('contains', 'count', 'rfind'), armar ('replace', 'repeat', 'pad_*') y
Unicode ('lower', 'upper', 'is_*'), ejecutados de punta a punta en el
intérprete con la salida EXACTA que se espera.

Cada caso fija una decisión de la librería (separadores en los extremos,
qué es un fin de línea, qué cuenta como dígito) y no solo el caso feliz: si
alguien cambia la decisión, una de estas pruebas tiene que fallar. Los
caracteres invisibles o raros (U+00A0, U+2028, un acento combinante) se
arman con 'cast<char>(codigo)' en vez de escribirlos en la fuente, para que
se vea cuál es cada uno.
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from helpers import run_source  # noqa: E402

#: lo que comparten los programas: 'show' escribe un Vector<str> con cada
#: parte entre comillas (así se ve una parte vacía) y 'ch' arma el carácter
#: de un código.
_PRELUDIO = """#from io #import stdp
#import array.vector as vec
#import text
#import excepciones as exc

fn show(vec.Vector<str> ptr v) -> str {
    var vec.Vector<str> q = vec.dynamic<str>(1);
    var int i = 0;
    while (i < v.len()) { q.push(f"{v.get(i)!r}"); i = i + 1; }
    return f"{v.len()}" + "[" + text.join(&q, ", ") + "]";
}

fn ch(int cp) -> str {
    return f"{cast<char>(cp)}";
}

"""


#: el informe del compilador antes de ejecutar ("frontend OK: ...", "HIR
#: (... bytes) generado en: ...", "  unidad 'text': ...")
_DEL_COMPILADOR = ("frontend OK:", "HIR (", "  unidad '")


def _run(cuerpo: str, esperado: str) -> None:
    """Ejecuta 'cuerpo' dentro de 'main' en el intérprete (las llamadas
    nuevas de 'text' solo las tiene él) y exige la salida EXACTA del
    programa: se quitan solo las líneas con que el compilador informa de lo
    que generó, que van a la misma salida."""
    fuente = _PRELUDIO + "fn main() -> int {\n" + cuerpo + "\n    return 0;\n}\n"
    code, crudo, err = run_source(fuente, args=["--run", "interpreter"])
    out = "".join(l for l in crudo.splitlines(keepends=True)
                  if not l.startswith(_DEL_COMPILADOR))
    assert code == 0 and out == esperado, (
        f"\n  esperado: {esperado!r}\n  stdout:   {out!r}\n  código:   {code}"
        f"\n  stderr:   {err[-2000:]!r}")


def test_split_sigue_a_str_split_de_python():
    """Una parte más que separadores: vacías en los extremos y entre dos
    separadores seguidos; sin solaparse; separador de varios caracteres o
    fuera del plano básico (los índices son code points)."""
    _run('    var vec.Vector<str> a = text.split("a,b,c", ",");\n'
         '    var vec.Vector<str> b = text.split(",a,,b,", ",");\n'
         '    var vec.Vector<str> c = text.split("", ",");\n'
         '    var vec.Vector<str> d = text.split("abc", ",");\n'
         '    var vec.Vector<str> e = text.split("a<->b<->", "<->");\n'
         '    var vec.Vector<str> f = text.split("ñ😀ñ😀", "😀");\n'
         '    var vec.Vector<str> g = text.split("aaa", "aa");\n'
         '    stdp.println(show(&a));\n    stdp.println(show(&b));\n'
         '    stdp.println(show(&c));\n    stdp.println(show(&d));\n'
         '    stdp.println(show(&e));\n    stdp.println(show(&f));\n'
         '    stdp.println(show(&g));',
         '3["a", "b", "c"]\n'
         '5["", "a", "", "b", ""]\n'
         '1[""]\n'
         '1["abc"]\n'
         '3["a", "b", ""]\n'
         '3["ñ", "ñ", ""]\n'
         '2["", "a"]\n')


def test_split_y_join_son_inversas_y_el_vector_crece():
    """'join(split(s, sep), sep) == s', y el Vector que devuelve es uno
    normal: se le puede hacer 'push' aunque haya salido vacío o lleno."""
    _run('    var str s = ";;x;ñ;;";\n'
         '    var vec.Vector<str> p = text.split(s, ";");\n'
         '    stdp.println(f"{text.join(&p, ";") == s} {p.len()}");\n'
         '    p.push("nuevo"); p.push("otro");\n'
         '    stdp.println(show(&p));\n'
         '    var vec.Vector<str> w = text.split_whitespace("   ");\n'
         '    w.push("a"); w.push("b");\n'
         '    stdp.println(show(&w));',
         'true 6\n'
         '8["", "", "x", "ñ", "", "", "nuevo", "otro"]\n'
         '2["a", "b"]\n')


def test_argumentos_sin_respuesta_son_valor_invalido():
    """Separador vacío, contar o reemplazar "" y repetir un número negativo
    de veces: 'excepciones.ValorInvalido', que se puede atrapar."""
    _run('    try { text.split("abc", ""); } catch (exc.ValorInvalido e) { stdp.println(e.mensaje); };\n'
         '    try { text.count("abc", ""); } catch (exc.ValorInvalido e) { stdp.println(e.mensaje); };\n'
         '    try { text.replace("abc", "", "x"); } catch (exc.ValorInvalido e) { stdp.println(e.mensaje); };\n'
         '    try { text.repeat("ab", -1); } catch (exc.ValorInvalido e) { stdp.println(e.mensaje); };\n'
         '    stdp.println("sigue");',
         'text.split: el separador no puede ser vacío\n'
         'text.count: la parte que se cuenta no puede ser vacía\n'
         'text.replace: el texto que se reemplaza no puede ser vacío\n'
         'text.repeat: no se puede repetir -1 veces\n'
         'sigue\n')


def test_split_whitespace_corta_por_espacios_de_unicode():
    """Cualquier tira de 'is_space' separa (tab, salto, U+00A0, U+3000,
    U+2028); los extremos no dan partes vacías. U+200B (espacio de ancho
    cero) NO es espacio: queda dentro de la palabra."""
    _run('    var vec.Vector<str> a = text.split_whitespace("  uno \\t dos\\n\\r tres  ");\n'
         '    var vec.Vector<str> b = text.split_whitespace("");\n'
         '    var vec.Vector<str> c = text.split_whitespace(" \\t\\n ");\n'
         '    var vec.Vector<str> d = text.split_whitespace("a" + ch(0xA0) + "b" + ch(0x3000) + "c" + ch(0x2028) + "d");\n'
         '    var vec.Vector<str> e = text.split_whitespace("a" + ch(0x200B) + "b c");\n'
         '    stdp.println(show(&a));\n    stdp.println(show(&b));\n'
         '    stdp.println(show(&c));\n    stdp.println(show(&d));\n'
         '    stdp.println(f"{e.len()} {len(e.get(0))} {e.get(1)}");',
         '3["uno", "dos", "tres"]\n'
         '0[]\n'
         '0[]\n'
         '4["a", "b", "c", "d"]\n'
         '2 3 c\n')


def test_lines_corta_en_lf_y_crlf_y_nada_mas():
    """Fin de línea = "\\n" o "\\r\\n" (como 'sistema.entrada'). El último no
    abre una línea vacía; un "\\r" suelto, '\\f' o U+2028 no cortan."""
    _run('    var vec.Vector<str> a = text.lines("a\\nb");\n'
         '    var vec.Vector<str> b = text.lines("a\\nb\\n");\n'
         '    var vec.Vector<str> c = text.lines("a\\n\\nb");\n'
         '    var vec.Vector<str> d = text.lines("");\n'
         '    var vec.Vector<str> e = text.lines("\\n");\n'
         '    var vec.Vector<str> f = text.lines("uno\\r\\ndos\\r\\n\\r\\n");\n'
         '    var vec.Vector<str> g = text.lines("a\\rb\\n");\n'
         '    var vec.Vector<str> h = text.lines("a\\r\\r\\nb\\r");\n'
         '    var vec.Vector<str> i = text.lines("x" + ch(0x2028) + "y" + ch(12) + "z\\nñ😀");\n'
         '    stdp.println(show(&a));\n    stdp.println(show(&b));\n'
         '    stdp.println(show(&c));\n    stdp.println(show(&d));\n'
         '    stdp.println(show(&e));\n    stdp.println(show(&f));\n'
         '    stdp.println(show(&g));\n    stdp.println(show(&h));\n'
         '    stdp.println(f"{i.len()} {len(i.get(0))} {i.get(1)}");',
         '2["a", "b"]\n'
         '2["a", "b"]\n'
         '3["a", "", "b"]\n'
         '0[]\n'
         '1[""]\n'
         '3["uno", "dos", ""]\n'
         '1["a\\rb"]\n'
         '2["a\\r", "b\\r"]\n'
         '2 5 ñ😀\n')


def test_trim_quita_lo_mismo_que_is_space():
    """Recorta los extremos (con espacios de Unicode) y deja el interior;
    U+200B no se recorta porque no es 'is_space'."""
    _run('    stdp.println(f"[{text.trim("  hola mundo \\n")}] [{text.trim_start(" \\t x ")}] '
         '[{text.trim_end(" x \\r\\n")}]");\n'
         '    stdp.println(f"[{text.trim("")}] [{text.trim(" \\t\\n ")}] [{text.trim_start("")}] [{text.trim_end("   ")}]");\n'
         '    var str raro = ch(0xA0) + ch(0x3000) + "ñ" + ch(0x2028) + ch(0x85);\n'
         '    stdp.println(f"[{text.trim(raro)}] {len(text.trim_start(raro))} {len(text.trim_end(raro))}");\n'
         '    var str zw = ch(0x200B) + "a" + ch(0x200B);\n'
         '    stdp.println(f"{len(text.trim(zw))} {text.is_space(cast<char>(0x200B))} {text.is_space(cast<char>(0x3000))}");',
         '[hola mundo] [x ] [ x]\n'
         '[] [] [] []\n'
         '[ñ] 3 3\n'
         '3 false true\n')


def test_replace():
    """Sin solaparse, de izquierda a derecha; 'new' vacío borra; con
    caracteres fuera del ASCII y del plano básico."""
    _run('    stdp.println(text.replace("a-b-c", "-", "+"));\n'
         '    stdp.println(text.replace("aaaa", "aa", "b"));\n'
         '    stdp.println(text.replace("-a-", "-", "<->"));\n'
         '    stdp.println(text.replace("a-b", "-", ""));\n'
         '    stdp.println(text.replace("abc", "x", "y"));\n'
         '    stdp.println(text.replace("ñandú 😀 ñu", "ñ", "n"));\n'
         '    stdp.println(text.replace("😀😀", "😀", "ok"));\n'
         '    stdp.println(f"[{text.replace("", "a", "b")}]");',
         'a+b+c\nbb\n<->a<->\nab\nabc\nnandú 😀 nu\nokok\n[]\n')


def test_contains_count_rfind():
    """'count' no solapa; 'rfind' devuelve la ÚLTIMA aparición aunque se
    solape con otra, en code points, y 'len(s)' para la parte vacía."""
    _run('    stdp.println(f"{text.contains("abc", "")} {text.contains("ñandú", "dú")} '
         '{text.contains("abc", "x")} {text.contains("", "")} {text.contains("", "a")}");\n'
         '    stdp.println(f"{text.count("aaaa", "aa")} {text.count("a,b,,c", ",")} '
         '{text.count("", "a")} {text.count("😀x😀", "😀")} {text.count("abc", "abcd")}");\n'
         '    stdp.println(f"{text.rfind("a/b/c", "/")} {text.rfind("abc", "x")} '
         '{text.rfind("abc", "")} {text.rfind("aaa", "aa")} {text.rfind("😀a😀b", "😀")} '
         '{text.rfind("", "")} {text.rfind("abc", "abc")}");',
         'true true false true false\n'
         '2 3 0 2 0\n'
         '3 -1 3 1 2 0 0\n')


def test_repeat_por_duplicacion():
    """Cada bit de 'n' (1, 2, 3, 5, 7, 8, 13) y los bordes: 0 veces, cadena
    vacía, caracteres de varios bytes; uno grande no tarda (es por
    duplicación, no un '+' por copia)."""
    _run('    stdp.println(f"[{text.repeat("ab", 0)}] [{text.repeat("", 5)}] [{text.repeat("ñ", 1)}] '
         '[{text.repeat("ab", 2)}] [{text.repeat("ab", 3)}]");\n'
         '    stdp.println(f"{text.repeat("ab", 5)} {text.repeat("x", 7)} {text.repeat("😀", 8)}");\n'
         '    stdp.println(f"{len(text.repeat("xyz", 13))} {len(text.repeat("-", 1000000))} '
         '{text.repeat("ab", 13) == "ababababababababababababab"}");',
         '[] [] [ñ] [abab] [ababab]\n'
         'ababababab xxxxxxx 😀😀😀😀😀😀😀😀\n'
         '39 1000000 true\n')


def test_pad_left_y_pad_right():
    """Rellenan hasta 'width' caracteres; si ya tiene ese largo (o 'width'
    es negativo) vuelve tal cual, sin cortar."""
    _run('    stdp.println(f"{text.pad_left("7", 3, \'0\')} {text.pad_left("1234", 3, \'0\')} '
         '[{text.pad_left("", 2, \' \')}] {text.pad_left("ñ", 3, \'·\')} {text.pad_left("x", -1, \'.\')}");\n'
         '    stdp.println(f"{text.pad_right("ab", 4, \'.\')} {text.pad_right("abc", 3, \'.\')} '
         '{text.pad_right("a", 3, \'😀\')} [{text.pad_right("", 0, \'.\')}] '
         '{text.pad_right("abc", 2, \'.\')} {text.pad_right("x", -1, \'.\')}");',
         '007 1234 [  ] ··ñ x\n'
         'ab.. abc a😀😀 [] abc x\n')


def test_lower_y_upper_con_unicode():
    """Reglas de Unicode sin idioma: 'ß' -> "SS" (cambia el largo), 'İ'
    -> 'i' + punto combinante, sigma final, un acento combinante se
    conserva, y lo que no tiene caso queda igual."""
    _run('    stdp.println(f"{text.lower("ÁRBOL Ñandú ΟΔΟΣ")} {text.upper("straße ñ")} {len(text.upper("ß"))}");\n'
         '    var str i_punto = text.lower("İ");\n'
         '    stdp.println(f"{len(i_punto)} {i_punto[0]} {cast<int>(i_punto[1])} {text.lower("I")}");\n'
         '    var str e_acento = "e" + ch(0x301);\n'
         '    var str E = text.upper(e_acento);\n'
         '    stdp.println(f"{len(E)} {E[0]} {cast<int>(E[1])} {text.upper("😀 123 中")} [{text.lower("")}]");',
         'árbol ñandú οδος STRASSE Ñ 2\n'
         '2 i 775 i\n'
         '2 E 769 😀 123 中 []\n')


def test_clases_de_caracteres():
    """La tabla de decisiones: dígito DECIMAL de cualquier escritura (sí
    '٣', no '²' ni '½'), 'is_alnum' = 'is_alpha or is_digit', letras de
    cualquier alfabeto (también fuera del plano básico), y lo que no es
    letra ni dígito: '_', un acento combinante suelto, un emoji."""
    casos = [
        # (código, digit, alpha, alnum, space, upper, lower)
        (ord("7"), 1, 0, 1, 0, 0, 0),
        (0x0663, 1, 0, 1, 0, 0, 0),    # ٣ dígito árabe-índico
        (0x00B2, 0, 0, 0, 0, 0, 0),    # ² superíndice
        (0x00BD, 0, 0, 0, 0, 0, 0),    # ½
        (ord("a"), 0, 1, 1, 0, 0, 1),
        (ord("Ñ"), 0, 1, 1, 0, 1, 0),
        (ord("ß"), 0, 1, 1, 0, 0, 1),
        (ord("λ"), 0, 1, 1, 0, 0, 1),
        (ord("Ω"), 0, 1, 1, 0, 1, 0),
        (ord("中"), 0, 1, 1, 0, 0, 0),
        (ord("_"), 0, 0, 0, 0, 0, 0),
        (ord(" "), 0, 0, 0, 1, 0, 0),
        (ord("\t"), 0, 0, 0, 1, 0, 0),
        (ord("\r"), 0, 0, 0, 1, 0, 0),
        (0x00A0, 0, 0, 0, 1, 0, 0),    # espacio duro
        (0x2028, 0, 0, 0, 1, 0, 0),    # separador de línea
        (0x200B, 0, 0, 0, 0, 0, 0),    # espacio de ancho cero: NO es espacio
        (0x0301, 0, 0, 0, 0, 0, 0),    # acento agudo combinante
        (0x1F600, 0, 0, 0, 0, 0, 0),   # 😀
        (0x1D400, 0, 1, 1, 0, 1, 0),   # 𝐀 (matemática, fuera del plano básico)
        (0x01C5, 0, 1, 1, 0, 0, 0),    # ǅ: titlecase, ni mayúscula ni minúscula
    ]
    cuerpo = []
    for cp, *_ in casos:
        c = f"cast<char>({cp})"
        cuerpo.append(
            f'    stdp.println(f"{{cast<int>(text.is_digit({c}))}}{{cast<int>(text.is_alpha({c}))}}'
            f'{{cast<int>(text.is_alnum({c}))}}{{cast<int>(text.is_space({c}))}}'
            f'{{cast<int>(text.is_upper({c}))}}{{cast<int>(text.is_lower({c}))}}");')
    esperado = "".join("".join(str(b) for b in banderas) + "\n" for _, *banderas in casos)
    _run("\n".join(cuerpo), esperado)


def test_un_analizador_de_verdad():
    """Lo que la librería existe para hacer: leer un texto, partirlo en
    líneas, saltar las vacías y los comentarios, y contar palabras e
    identificadores. Usa casi todo junto."""
    _run('    var str fuente = "# config\\r\\n\\r\\n  nombre = Ñandú  \\r\\n\\tedad=7\\r\\n# fin\\r\\n";\n'
         '    var vec.Vector<str> ls = text.lines(fuente);\n'
         '    var int i = 0;\n'
         '    while (i < ls.len()) {\n'
         '        var str l = text.trim(ls.get(i));\n'
         '        if (len(l) > 0 and not text.starts_with(l, "#")) {\n'
         '            var vec.Vector<str> kv = text.split(l, "=");\n'
         '            var str clave = text.upper(text.trim(kv.get(0)));\n'
         '            var str valor = text.trim(kv.get(1));\n'
         '            var str tipo = "texto";\n'
         '            if (text.is_digit(valor[0])) { tipo = "numero"; };\n'
         '            stdp.println(f"{i + 1}: {text.pad_right(clave, 7, \'.\')}{text.pad_left(valor, 6, \' \')} ({tipo})");\n'
         '        };\n'
         '        i = i + 1;\n'
         '    }',
         '3: NOMBRE. Ñandú (texto)\n'
         '4: EDAD...     7 (numero)\n')

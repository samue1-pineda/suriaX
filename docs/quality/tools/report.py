"""Genera los documentos de cumplimiento (``docs/quality/cumplimiento/``) a
partir de lo medido (``docs/quality/reports/*.json``).

Reglas del informe:

- un porcentaje sale de una medida; lo que no se midió dice NO MEDIDO y no
  entra en ningún promedio;
- cada documento dice con qué herramienta y versión se midió;
- sin fechas (la fecha la da el historial de git de estos archivos).
"""

from __future__ import annotations

import os
import re
from typing import Iterable, List, Optional, Sequence, Tuple

import assessments
from common import COMPLIANCE, ROOT, load_report, percent

_HEADER = (
    "> Documento GENERADO por `docs/quality/tools/quality.py` a partir de "
    "`docs/quality/reports/`. No se edita a mano: se vuelve a medir.\n"
)
NM = "NO MEDIDO"


def _pct(value: Optional[float]) -> str:
    return NM if value is None else f"{value:.1f} %"


def _num(value) -> str:
    return NM if value is None else str(value)


def _table(headers: Sequence[str], rows: Iterable[Sequence]) -> str:
    lines = ["| " + " | ".join(headers) + " |", "|" + "---|" * len(headers)]
    for row in rows:
        lines.append("| " + " | ".join(str(c).replace("|", "\\|") for c in row) + " |")
    return "\n".join(lines) + "\n"


def _write(name: str, title: str, body: str) -> str:
    os.makedirs(COMPLIANCE, exist_ok=True)
    path = os.path.join(COMPLIANCE, name)
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(f"# {title}\n\n{_HEADER}\n{body.rstrip()}\n")
    return path


def _mean(values: Iterable[Optional[float]]) -> Optional[float]:
    measured = [v for v in values if v is not None]
    return round(sum(measured) / len(measured), 1) if measured else None


def _top(counter: dict, n: int = 12) -> List[Tuple[str, int]]:
    return list(counter.items())[:n]


# --------------------------------------------------------------------------- #
# medidas derivadas
# --------------------------------------------------------------------------- #


def _category_pass(suite: Optional[dict], category: str) -> Optional[float]:
    """% de pruebas de una categoría que pasaron, de las ejecutadas."""
    if not suite or not suite.get("measured"):
        return None
    info = suite.get("per_category", {}).get(category)
    if not info or category not in suite.get("categories", []):
        return None
    failed = sum(1 for f in suite.get("failures", []) if f.startswith(f"{category}/"))
    skipped = suite.get("skipped_by_category", {}).get(category, 0)
    executed = info["tests"] - skipped
    return percent(executed - failed, executed) if executed > 0 else None


def _documented_error_codes() -> Tuple[Optional[float], int, int]:
    """% de los códigos de error del compilador con su entrada en
    ``documentation/source/errors.rst``.

    Usa la MISMA definición que la prueba ``test_docs_al_dia`` (qué códigos
    emite el compilador y cuáles documenta el catálogo): dos recuentos
    distintos de lo mismo darían dos números distintos."""
    import importlib.util

    path = os.path.join(ROOT, "test", "unit", "test_docs_al_dia.py")
    try:
        spec = importlib.util.spec_from_file_location("_docs_al_dia", path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        # pylint: disable=protected-access  # son los helpers de esa prueba
        codes = module._codigos_del_compilador()
        documented = codes & module._codigos_documentados()
    except (OSError, ImportError, AttributeError) as exc:
        print(f"  aviso: no se pudo contar los códigos documentados ({exc})")
        return None, 0, 0
    return percent(len(documented), len(codes)), len(documented), len(codes)


def _roadmap_completeness() -> Tuple[Optional[float], int, int, int]:
    """Lo planificado en ``ROADMAP.md`` que está hecho: ``[x]`` cuenta 1,
    ``[ / ]`` medio. Se excluye la fase del playground web (fuera del alcance)."""
    path = os.path.join(ROOT, "ROADMAP.md")
    if not os.path.isfile(path):
        return None, 0, 0, 0
    done = partial = pending = 0
    in_web = False
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            if line.startswith("## "):
                in_web = "Playground" in line or "web" in line.lower()
            if in_web:
                continue
            done += len(re.findall(r"\[x\]", line, flags=re.IGNORECASE))
            partial += len(re.findall(r"\[ ?/ ?\]", line))
            pending += len(re.findall(r"\[ \]", line))
    total = done + partial + pending
    return percent(done + 0.5 * partial, total), done, partial, pending


# --------------------------------------------------------------------------- #
# Python
# --------------------------------------------------------------------------- #


def _python_section(name: str, data: dict) -> Tuple[str, dict]:
    flake, fmt, lint = data["flake8"], data["black"], data["pylint"]
    docs, zen = data["pep257"], data["pep20"]
    pep8 = flake.get("pep8", {}) if flake.get("measured") else {}
    score = lint.get("score") if lint.get("measured") else None
    score = None if score is None else round(score, 2)
    score_pct = None if score is None else max(0.0, round(score * 10, 1))
    silent = zen["errors_should_never_pass_silently"]
    simple = zen["simple_is_better_than_complex"]
    form = docs.get("form", {})
    metrics = {
        "pep8_clean_files_pct": pep8.get("clean_files_pct"),
        "black_formatted_pct": fmt.get("formatted_pct") if fmt.get("measured") else None,
        "pylint_score_pct": score_pct,
        "pep257_documented_pct": docs.get("documented_pct"),
        "pep20_simple_pct": simple.get("within_pct"),
        "pep20_not_silent_pct": silent.get("not_silent_pct"),
    }
    body = f"## {name}: `{'`, `'.join(data['scope'])}`\n\n"
    body += _table(
        ["Norma", "Indicador", "Valor", "Cumplimiento"],
        [
            (
                "PEP 8",
                "archivos sin violaciones de pycodestyle (E/W)",
                f"{_num(pep8.get('clean_files'))} de {_num(flake.get('files'))}",
                _pct(metrics["pep8_clean_files_pct"]),
            ),
            ("PEP 8", "violaciones por cada 1000 líneas", _num(pep8.get("per_kloc")), "—"),
            (
                "(informativo)",
                "archivos con el formato de black (más estricto que PEP 8)",
                f"{_num(fmt.get('formatted'))} de {_num(fmt.get('files'))}",
                _pct(metrics["black_formatted_pct"]) + " (fuera del promedio)",
            ),
            ("PEP 8 / PEP 20", "nota de pylint (sobre 10)", _num(score), _pct(score_pct)),
            (
                "PEP 257",
                "definiciones públicas con docstring",
                f"{_num(docs.get('documented'))} de {_num(docs.get('public_definitions'))}",
                _pct(metrics["pep257_documented_pct"]),
            ),
            (
                "PEP 257",
                "violaciones de forma por docstring (pydocstyle, D2xx-D4xx)",
                _num(form.get("per_docstring")),
                "—",
            ),
            (
                "PEP 20",
                "funciones con complejidad ciclomática ≤ 15",
                f"{_num(simple.get('functions'))} funciones, "
                f"{_num(simple.get('over_complexity_limit'))} por encima",
                _pct(metrics["pep20_simple_pct"]),
            ),
            (
                "PEP 20",
                "`except` que no se tragan el error",
                f"{_num(silent.get('silent_handlers'))} silenciosos de "
                f"{_num(silent.get('except_handlers'))}",
                _pct(metrics["pep20_not_silent_pct"]),
            ),
            (
                "PEP 20",
                "importaciones con `*`",
                _num(zen["explicit_is_better_than_implicit"].get("wildcard_imports")),
                "—",
            ),
            (
                "PEP 20",
                "bloques de código duplicado (pylint)",
                _num(zen["there_should_be_one_obvious_way"].get("duplicate_code_blocks")),
                "—",
            ),
            (
                "—",
                "errores lógicos de pyflakes (F)",
                _num(flake.get("pyflakes", {}).get("violations")),
                "—",
            ),
        ],
    )
    # black no es una norma: es UN formato canónico entre los que PEP 8 admite.
    # Se muestra, pero no entra en el cumplimiento de los lineamientos.
    norms = [v for k, v in metrics.items() if k != "black_formatted_pct"]
    body += (
        f"\n**Cumplimiento medio de los PEP:** {_pct(_mean(norms))} "
        "(black se reporta aparte: no es una norma)\n\n"
    )
    if pep8.get("by_code"):
        body += "Violaciones de PEP 8 más frecuentes:\n\n"
        body += _table(["Código", "Cantidad"], _top(pep8["by_code"]))
    if lint.get("measured"):
        body += "\nMensajes de pylint por categoría:\n\n"
        body += _table(["Categoría", "Cantidad"], sorted(lint["by_category"].items()))
        body += "\nMensajes de pylint más frecuentes:\n\n"
        body += _table(["Mensaje", "Cantidad"], _top(lint["by_symbol"]))
    if form.get("by_code"):
        body += "\nViolaciones de forma de PEP 257 más frecuentes:\n\n"
        body += _table(["Código", "Cantidad"], _top(form["by_code"]))
    flakes = [v for v in flake.get("violations", []) if v["code"].startswith("F")]
    if flakes:
        body += "\nHallazgos de pyflakes (revisar uno por uno):\n\n"
        body += "".join(
            f"- `{v['file']}:{v['line']}` {v['code']} {v['message']}\n" for v in flakes[:60]
        )
    errors = [m for m in lint.get("messages", []) if m["id"][0] in "EF"]
    if errors:
        body += "\nErrores de pylint (E/F; revisar uno por uno, pueden ser falsos positivos):\n\n"
        body += "".join(f"- `{m['file']}:{m['line']}` {m['id']} {m['symbol']}\n" for m in errors)
    if silent.get("where_silent"):
        body += "\n`except` silenciosos (revisar uno por uno: alguno puede ser legítimo):\n\n"
        body += "".join(f"- `{w}`\n" for w in silent["where_silent"][:40])
    if simple.get("over_complexity_limit"):
        body += "\nFunciones por encima del límite de complejidad:\n\n"
        body += "".join(f"- `{w}`\n" for w in flake["complexity"]["functions"][:40])
    return body, metrics


def python_document(data: Optional[dict]) -> Tuple[str, dict]:
    """``cumplimiento/python.md`` y sus porcentajes (compilador y suite)."""
    if not data:
        return (
            _write(
                "python.md",
                "Cumplimiento: Python (PEP 8, PEP 20, PEP 257)",
                f"{NM}: corre `quality.py python`.\n",
            ),
            {},
        )
    tools = []
    for key in ("flake8", "black", "pylint"):
        info = data["compiler"][key]
        tool = info.get("tool", "").replace("python -m ", "").split(" CPython")[0]
        if tool and not tool.lower().startswith(key):
            tool = f"{key} {tool}"
        tools.append(tool or f"{key}: {info.get('reason', NM)}")
    form = data["compiler"]["pep257"].get("form", {})
    tools.append(form.get("tool") or f"pydocstyle: {form.get('reason', NM)}")
    body = "Herramientas: " + "; ".join(f"`{t}`" for t in tools) + "\n\n"
    body += (
        "Configuración: `.flake8` y `pyproject.toml` (largo de línea 99 en las tres "
        "herramientas). Qué mide cada fila y por qué: `docs/quality/normas/python.md`.\n\n"
    )
    metrics = {}
    for name, label in (("compiler", "Compilador"), ("tests", "Suite de pruebas")):
        if name in data:
            section, m = _python_section(label, data[name])
            body += section + "\n"
            metrics[name] = m
    return _write("python.md", "Cumplimiento: Python (PEP 8, PEP 20, PEP 257)", body), metrics


# --------------------------------------------------------------------------- #
# C++
# --------------------------------------------------------------------------- #


def cpp_document(data: Optional[dict], sanitizers: Optional[dict]) -> Tuple[str, dict]:
    """``cumplimiento/cpp.md``: Core Guidelines, cppcheck y sanitizadores."""
    title = "Cumplimiento: C++ (Core Guidelines, cppcheck, sanitizadores)"
    metrics: dict = {}
    body = ""
    tidy = (data or {}).get("clang_tidy", {})
    check = (data or {}).get("cppcheck", {})
    if tidy.get("measured"):
        core = tidy["core_guidelines"]
        metrics["core_rules_pct"] = core["rules_compliance_pct"]
        metrics["core_clean_files_pct"] = core["clean_files_pct"]
        body += "## C++ Core Guidelines (clang-tidy)\n\n"
        body += (
            f"Herramienta: `{tidy['tool']}`, configuración `.clang-tidy`, compilación "
            f"según `{tidy['compile_database']}/compile_commands.json` "
            f"({len(tidy['translation_units'])} unidades, {tidy['lines']} líneas).\n\n"
        )
        body += _table(
            ["Indicador", "Valor", "Cumplimiento"],
            [
                (
                    "reglas de las Core Guidelines sin ningún hallazgo",
                    f"{core['rules_without_findings']} de {core['rules']}",
                    _pct(core["rules_compliance_pct"]),
                ),
                (
                    "archivos sin hallazgos de las Core Guidelines",
                    "—",
                    _pct(core["clean_files_pct"]),
                ),
                ("hallazgos de las Core Guidelines", core["findings"], "—"),
                ("hallazgos por cada 1000 líneas", core["per_kloc"], "—"),
                *[(f"otros grupos: `{g}*`", n, "—") for g, n in tidy["other_groups"].items()],
            ],
        )
        if tidy.get("not_analyzed"):
            body += (
                "\nNo analizado por clang-tidy (no está en la base de compilación; lo cubre "
                "cppcheck): " + ", ".join(f"`{f}`" for f in tidy["not_analyzed"]) + "\n"
            )
        body += "\nReglas con hallazgos:\n\n"
        body += _table(["Regla", "Hallazgos"], core["violated_rules"].items())
    else:
        reason = tidy.get("reason", "corre `quality.py cpp`")
        body += f"## C++ Core Guidelines (clang-tidy)\n\n{NM}: {reason}\n"
    body += "\n## cppcheck\n\n"
    if check.get("measured"):
        metrics["cppcheck_clean_files_pct"] = check["clean_files_pct"]
        body += (
            f"Herramienta: `{check['tool']}` ({check['files']} archivos, "
            f"{check['lines']} líneas).\n\n"
        )
        body += _table(
            ["Indicador", "Valor", "Cumplimiento"],
            [
                (
                    "archivos sin hallazgos",
                    f"{check['clean_files']} de {check['files']}",
                    _pct(check["clean_files_pct"]),
                ),
                ("hallazgos", check["findings"], "—"),
                ("hallazgos por cada 1000 líneas", check["per_kloc"], "—"),
                *[(f"severidad `{s}`", n, "—") for s, n in sorted(check["by_severity"].items())],
            ],
        )
        body += "\nHallazgos por tipo:\n\n" + _table(["Id", "Cantidad"], check["by_id"].items())
        serious = [i for i in check["items"] if i["severity"] in ("error", "warning")]
        if serious:
            body += "\nErrores y avisos (revisar uno por uno):\n\n"
            body += "".join(
                f"- `{i['file']}:{i['line']}` [{i['id']}] {i['message']}\n" for i in serious
            )
    else:
        body += f"{NM}: {check.get('reason', 'corre `quality.py cpp`')}\n"
    body += "\n## Sanitizadores (la suite de la VM instrumentada)\n\n"
    rows = []
    for kind, label in (("asan", "AddressSanitizer"), ("ubsan", "UndefinedBehaviorSanitizer")):
        info = (sanitizers or {}).get(kind)
        if not info or not info.get("measured"):
            rows.append(
                (label, NM, (info or {}).get("reason", "corre `quality.py sanitizers`"), NM)
            )
            continue
        metrics[f"{kind}_clean_pct"] = info["clean_pct"]
        rows.append(
            (
                label,
                f"{info['passed']} de {info['passed'] + info['failed']} "
                f"({info['skipped']} omitidas)",
                "; ".join(info.get("notes", [])) or f"`{info['binary']}`",
                _pct(info["clean_pct"]),
            )
        )
    body += _table(["Sanitizador", "Pruebas limpias", "Notas", "Cumplimiento"], rows)
    for kind in ("asan", "ubsan"):
        info = (sanitizers or {}).get(kind) or {}
        if info.get("failures"):
            body += f"\nFallos con {kind}:\n\n" + "".join(f"- `{f}`\n" for f in info["failures"])
        if info.get("sanitizer_reports"):
            body += (
                f"\nInformes de {kind}:\n\n```\n"
                + "\n".join(info["sanitizer_reports"])
                + "\n```\n"
            )
    body += f"\n**Cumplimiento medio:** {_pct(_mean(metrics.values()))}\n"
    return _write("cpp.md", title, body), metrics


# --------------------------------------------------------------------------- #
# pruebas: suite, cobertura, portabilidad
# --------------------------------------------------------------------------- #


def tests_document(suite, coverage, portability) -> Tuple[str, dict]:
    """``cumplimiento/pruebas.md``: la suite, su cobertura y su portabilidad."""
    metrics: dict = {}
    body = "## La suite (`test/main.py`)\n\n"
    if suite and suite.get("measured"):
        metrics["pass_pct"] = suite["pass_pct_of_executed"]
        metrics["executed_pct"] = suite["executed_pct"]
        body += _table(
            ["Indicador", "Valor", "Porcentaje"],
            [
                (
                    "pruebas que pasan (de las ejecutadas)",
                    f"{suite['passed']} de {suite['passed'] + suite['failed']}",
                    _pct(suite["pass_pct_of_executed"]),
                ),
                (
                    "pruebas ejecutadas (del total)",
                    f"{suite['passed'] + suite['failed']} de {suite['total']}",
                    _pct(suite["executed_pct"]),
                ),
                ("módulos", suite["modules"], "—"),
                ("categorías corridas", ", ".join(suite["categories"]), "—"),
            ],
        )
        if suite["failures"]:
            body += "\nFallos:\n\n" + "".join(f"- {f}\n" for f in suite["failures"])
        if suite["skip_reasons"]:
            body += "\nOmitidas (no se ejecutaron: falta algo en la máquina, no es un fallo):\n\n"
            body += _table(["Motivo", "Pruebas"], suite["skip_reasons"].items())
        body += "\nPruebas por categoría (cuenta estática):\n\n"
        body += _table(
            ["Categoría", "Módulos", "Pruebas"],
            [(c, i["modules"], i["tests"]) for c, i in suite["per_category"].items()],
        )
    else:
        body += f"{NM}: corre `quality.py suite`.\n"
    body += "\n## Cobertura (coverage.py)\n\n"
    if coverage and coverage.get("measured"):
        metrics["line_pct"] = coverage["line_pct"]
        metrics["branch_pct"] = coverage["branch_pct"]
        body += (
            f"Herramienta: `{coverage['tool']}`, configuración `[tool.coverage]` de "
            "`pyproject.toml` (subprocesos incluidos).\n\n"
        )
        body += _table(
            ["Indicador", "Valor", "Porcentaje"],
            [
                (
                    "líneas del compilador ejecutadas por la suite",
                    f"{coverage['covered_lines']} de {coverage['statements']}",
                    _pct(coverage["line_pct"]),
                ),
                (
                    "ramas ejecutadas",
                    f"{_num(coverage['covered_branches'])} de {_num(coverage['branches'])}",
                    _pct(coverage["branch_pct"]),
                ),
            ],
        )
        body += "\nPor paquete:\n\n" + _table(
            ["Paquete", "Sentencias", "Cubiertas", "Porcentaje"],
            [
                (p, i["statements"], i["covered"], _pct(i["pct"]))
                for p, i in sorted(coverage["by_package"].items())
            ],
        )
    else:
        body += f"{NM}: {(coverage or {}).get('reason', 'corre `quality.py coverage`')}\n"
    body += "\n## Portabilidad (dependencias del sistema operativo)\n\n"
    if portability:
        rows = []
        for scope, label in (("compiler", "compilador"), ("tests", "suite de pruebas")):
            info = portability[scope]
            metrics[f"portability_{scope}_pct"] = info["clean_pct"]
            rows.append(
                (
                    label,
                    f"{info['clean_files']} de {info['files']}",
                    len(info["findings"]),
                    _pct(info["clean_pct"]),
                )
            )
        body += (
            "Lo que busca `docs/quality/tools/portability.py`: APIs solo de POSIX, `open()` y "
            "subprocesos sin codificación, `shell=True`, rutas y ejecutables escritos a mano, "
            "enlaces simbólicos sin alternativa.\n\n"
        )
        body += _table(["Alcance", "Archivos sin hallazgos", "Hallazgos", "Porcentaje"], rows)
        for scope in ("compiler", "tests"):
            findings = portability[scope]["findings"]
            if findings:
                body += f"\nHallazgos ({scope}):\n\n" + "".join(
                    f"- `{f['file']}:{f['line']}` [{f['rule']}] {f['message']}\n"
                    for f in findings[:60]
                )
    else:
        body += f"{NM}: corre `quality.py portability`.\n"
    return _write("pruebas.md", "Cumplimiento: pruebas, cobertura y portabilidad", body), metrics


# --------------------------------------------------------------------------- #
# autoevaluaciones de proceso (12207, 29119)
# --------------------------------------------------------------------------- #


def _assessment_document(
    name: str, title: str, norm: str, rows: list
) -> Tuple[str, Optional[float]]:
    table = []
    score = applicable = 0.0
    for clause, group, process, status, evidence, why in rows:
        shown = status
        notes = []
        missing = [e for e in evidence if not os.path.exists(os.path.join(ROOT, e))]
        if missing:
            notes.append("evidencia que ya no existe: " + ", ".join(missing))
            if status == assessments.APPLIED:
                shown = assessments.PARTIAL
        local = [e for e in evidence if e.startswith("audit/")]
        if local:
            notes.append("`audit/` es local: no se versiona")
        if shown != assessments.NOT_APPLICABLE:
            applicable += 1
            score += assessments.WEIGHT[shown]
        table.append(
            (
                clause,
                group,
                process,
                shown,
                ", ".join(f"`{e}`" for e in evidence) or "—",
                why + (f" ({'; '.join(notes)})" if notes else ""),
            )
        )
    pct = percent(score, applicable)
    body = (
        f"Autoevaluación contra {norm}: NO la mide una herramienta. Los estados y sus "
        "evidencias están en `docs/quality/tools/assessments.py`; el porcentaje se calcula "
        "como (aplicado + ½·parcial) / procesos aplicables. Por qué se usa esta norma y "
        f"cómo se adaptó: `docs/quality/normas/`.\n\n"
    )
    body += _table(["Cláusula", "Grupo", "Proceso", "Estado", "Evidencia", "Justificación"], table)
    counts = {
        s: sum(1 for r in table if r[3] == s)
        for s in (
            assessments.APPLIED,
            assessments.PARTIAL,
            assessments.PENDING,
            assessments.NOT_APPLICABLE,
        )
    }
    body += "\n" + _table(["Estado", "Procesos"], counts.items())
    body += (
        f"\n**Grado de aplicación (autoevaluado):** {_pct(pct)} de {int(applicable)} aplicables\n"
    )
    return _write(name, title, body), pct


# --------------------------------------------------------------------------- #
# ISO/IEC 25010
# --------------------------------------------------------------------------- #


def iso25010_document(py: dict, cpp: dict, tests: dict, suite, sanitizers) -> Tuple[str, dict]:
    """``cumplimiento/iso_iec_25010.md``: cada característica con sus indicadores."""
    compiler = py.get("compiler", {})
    docs_pct, documented, total_codes = _documented_error_codes()
    road_pct, done, partial, pending = _roadmap_completeness()
    ubsan = (sanitizers or {}).get("ubsan") or {}
    asan = (sanitizers or {}).get("asan") or {}
    characteristics = [
        (
            "Adecuación funcional",
            [
                (
                    "Corrección funcional",
                    "pruebas que pasan, de las ejecutadas",
                    tests.get("pass_pct"),
                ),
                (
                    "Completitud funcional",
                    f"hoja de ruta hecha ({done} hechas, {partial} a medias, "
                    f"{pending} pendientes; sin la fase web)",
                    road_pct,
                ),
            ],
        ),
        (
            "Eficiencia de desempeño",
            [
                (
                    "Comportamiento temporal",
                    "sin medida automática (hay un benchmark manual: " "`dev/bench_vm.py`)",
                    None,
                ),
            ],
        ),
        (
            "Compatibilidad",
            [
                (
                    "Interoperabilidad",
                    "el HIR que emite Python lo ejecuta la VM de C++ igual que el "
                    "intérprete (categoría `backend`)",
                    _category_pass(suite, "backend"),
                ),
            ],
        ),
        (
            "Capacidad de interacción",
            [
                (
                    "Reconocibilidad / aprendizaje",
                    f"códigos de error documentados ({documented} de " f"{total_codes})",
                    docs_pct,
                ),
            ],
        ),
        (
            "Fiabilidad",
            [
                ("Ausencia de fallos", "suite de la VM limpia bajo UBSan", ubsan.get("clean_pct")),
                (
                    "Tolerancia a fallos",
                    "pruebas aleatorias y de estrés (categoría `fuzz`)",
                    _category_pass(suite, "fuzz"),
                ),
            ],
        ),
        (
            "Seguridad",
            [
                ("Integridad (memoria)", "suite de la VM limpia bajo ASan", asan.get("clean_pct")),
                (
                    "Integridad (análisis estático)",
                    "archivos C++ sin hallazgos de cppcheck",
                    cpp.get("cppcheck_clean_files_pct"),
                ),
            ],
        ),
        (
            "Mantenibilidad",
            [
                (
                    "Analizabilidad",
                    "archivos Python sin violaciones de PEP 8",
                    compiler.get("pep8_clean_files_pct"),
                ),
                (
                    "Analizabilidad",
                    "definiciones públicas documentadas (PEP 257)",
                    compiler.get("pep257_documented_pct"),
                ),
                (
                    "Analizabilidad",
                    "reglas de las C++ Core Guidelines sin hallazgos",
                    cpp.get("core_rules_pct"),
                ),
                (
                    "Modificabilidad",
                    "funciones con complejidad ≤ 15",
                    compiler.get("pep20_simple_pct"),
                ),
                ("Modificabilidad", "nota de pylint × 10", compiler.get("pylint_score_pct")),
                (
                    "Capacidad de ser probado",
                    "líneas del compilador cubiertas por la suite",
                    tests.get("line_pct"),
                ),
            ],
        ),
        (
            "Flexibilidad",
            [
                (
                    "Adaptabilidad",
                    "compilador sin dependencias del sistema operativo",
                    tests.get("portability_compiler_pct"),
                ),
                (
                    "Adaptabilidad",
                    "suite sin dependencias del sistema operativo",
                    tests.get("portability_tests_pct"),
                ),
            ],
        ),
        ("Protección (safety)", None),
    ]
    rows = []
    summary = {}
    for name, indicators in characteristics:
        if indicators is None:
            rows.append(
                (
                    name,
                    "—",
                    "no aplica: el compilador no controla un sistema que pueda "
                    "dañar personas o bienes",
                    "—",
                )
            )
            summary[name] = None
            continue
        for sub, text, value in indicators:
            rows.append((name, sub, text, _pct(value)))
        summary[name] = _mean(v for _, _, v in indicators)
    body = (
        "Modelo de calidad de producto de ISO/IEC 25010:2023. La norma define las "
        "características; los INDICADORES y la forma de agregarlos son del proyecto (la "
        "norma no fija porcentajes): cada característica es el promedio de sus indicadores "
        "medidos. Qué significa cada uno y por qué se eligió: "
        "`docs/quality/normas/iso_iec_25010.md`.\n\n"
    )
    body += _table(["Característica", "Subcaracterística", "Indicador", "Valor"], rows)
    body += "\n## Por característica\n\n"
    body += _table(
        ["Característica", "Cumplimiento"],
        [(n, "no aplica" if n.startswith("Protección") else _pct(v)) for n, v in summary.items()],
    )
    measured = [v for n, v in summary.items() if v is not None]
    body += (
        f"\n**Cumplimiento global (promedio de las características medidas):** "
        f"{_pct(_mean(measured))} — {len(measured)} de "
        f"{sum(1 for n in summary if not n.startswith('Protección'))} características "
        "aplicables tienen al menos un indicador medido.\n"
    )
    return (
        _write("iso_iec_25010.md", "Cumplimiento: ISO/IEC 25010 (calidad del producto)", body),
        summary,
    )


# --------------------------------------------------------------------------- #


def generate() -> List[str]:
    """Todos los documentos de ``cumplimiento/`` con lo medido hasta ahora."""
    python = load_report("python")
    cpp = load_report("cpp")
    sanitizers = load_report("sanitizers")
    suite = load_report("suite")
    coverage = load_report("coverage")
    portability = load_report("portability")

    paths = []
    path, py_metrics = python_document(python)
    paths.append(path)
    path, cpp_metrics = cpp_document(cpp, sanitizers)
    paths.append(path)
    path, test_metrics = tests_document(suite, coverage, portability)
    paths.append(path)
    path, p12207 = _assessment_document(
        "iso_iec_12207.md",
        "Cumplimiento: ISO/IEC/IEEE 12207 (procesos del ciclo de vida)",
        "ISO/IEC/IEEE 12207:2017",
        assessments.ISO_12207,
    )
    paths.append(path)
    path, p29119 = _assessment_document(
        "iso_iec_ieee_29119.md",
        "Cumplimiento: ISO/IEC/IEEE 29119 (pruebas de software)",
        "ISO/IEC/IEEE 29119 (partes 2 a 5)",
        assessments.ISO_29119,
    )
    paths.append(path)
    path, summary = iso25010_document(py_metrics, cpp_metrics, test_metrics, suite, sanitizers)
    paths.append(path)

    compiler = py_metrics.get("compiler", {})
    rows = [
        (
            "ISO/IEC 25010 (producto)",
            "medido",
            _pct(_mean(v for v in summary.values() if v is not None)),
            "[iso_iec_25010.md](iso_iec_25010.md)",
        ),
        (
            "ISO/IEC/IEEE 12207 (ciclo de vida)",
            "autoevaluado",
            _pct(p12207),
            "[iso_iec_12207.md](iso_iec_12207.md)",
        ),
        (
            "ISO/IEC/IEEE 29119 (pruebas)",
            "autoevaluado",
            _pct(p29119),
            "[iso_iec_ieee_29119.md](iso_iec_ieee_29119.md)",
        ),
        (
            "PEP 8 (archivos limpios, compilador)",
            "medido",
            _pct(compiler.get("pep8_clean_files_pct")),
            "[python.md](python.md)",
        ),
        (
            "PEP 20 (complejidad ≤ 15)",
            "medido",
            _pct(compiler.get("pep20_simple_pct")),
            "[python.md](python.md)",
        ),
        (
            "PEP 20 (errores no silenciados)",
            "medido",
            _pct(compiler.get("pep20_not_silent_pct")),
            "[python.md](python.md)",
        ),
        (
            "PEP 257 (lo público documentado)",
            "medido",
            _pct(compiler.get("pep257_documented_pct")),
            "[python.md](python.md)",
        ),
        (
            "pylint (nota × 10)",
            "medido",
            _pct(compiler.get("pylint_score_pct")),
            "[python.md](python.md)",
        ),
        (
            "black (archivos con su formato; informativo, no es una norma)",
            "medido",
            _pct(compiler.get("black_formatted_pct")),
            "[python.md](python.md)",
        ),
        (
            "C++ Core Guidelines (reglas sin hallazgos)",
            "medido",
            _pct(cpp_metrics.get("core_rules_pct")),
            "[cpp.md](cpp.md)",
        ),
        (
            "cppcheck (archivos sin hallazgos)",
            "medido",
            _pct(cpp_metrics.get("cppcheck_clean_files_pct")),
            "[cpp.md](cpp.md)",
        ),
        (
            "ASan (suite de la VM limpia)",
            "medido",
            _pct(cpp_metrics.get("asan_clean_pct")),
            "[cpp.md](cpp.md)",
        ),
        (
            "UBSan (suite de la VM limpia)",
            "medido",
            _pct(cpp_metrics.get("ubsan_clean_pct")),
            "[cpp.md](cpp.md)",
        ),
        (
            "Suite (pasan, de las ejecutadas)",
            "medido",
            _pct(test_metrics.get("pass_pct")),
            "[pruebas.md](pruebas.md)",
        ),
        (
            "Cobertura de líneas",
            "medido",
            _pct(test_metrics.get("line_pct")),
            "[pruebas.md](pruebas.md)",
        ),
        (
            "Portabilidad de la suite",
            "medido",
            _pct(test_metrics.get("portability_tests_pct")),
            "[pruebas.md](pruebas.md)",
        ),
    ]
    body = (
        'Porcentaje de cumplimiento de cada norma y lineamiento. "Medido" sale de una '
        'herramienta; "autoevaluado" es un juicio con evidencias (12207 y 29119 son normas '
        "de PROCESO: no hay herramienta que las mida). El target web está fuera del alcance "
        "(ver `docs/quality/normas/alcance.md`).\n\n"
    )
    body += _table(["Norma / lineamiento", "Cómo", "Cumplimiento", "Detalle"], rows)
    paths.append(_write("README.md", "Resumen de cumplimiento", body))
    return paths

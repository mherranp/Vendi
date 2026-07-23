"""Candado: ningún identificador de BaseSaaS sobrevive en el CÓDIGO cosechado.

## Por qué este test existe y no un `grep` pelado

El criterio de integración (4) de la Etapa 3 lo pide así:

    grep -rn 'base_saas\\|search_path\\|tenant_slug' backend/libs frontend/projects/libs  → vacío

Ese grep no puede dar vacío, y no debe. El criterio (5) de la MISMA etapa exige
lo contrario: registrar «qué archivo vino de dónde y con qué cambio». La frase
que cumple el criterio (5) —«cosechado de `base_saas.audit.models`; `tenant_slug`
pasa a `tenant_id`»— es literalmente lo que el criterio (4) prohíbe. Borrarla
para que el grep dé vacío destruiría el artefacto más valioso de la cosecha:
saber de dónde salió cada cosa y por qué cambió.

Lo que el criterio (4) quiere decir de verdad es «no queda **código** que
referencie el mundo anterior»: ni un import de `base_saas`, ni una columna
`tenant_slug`, ni un `SET search_path`. Eso es lo que comprueba este test.

## Cómo distingue código de prosa

Tokeniza cada `.py` con el módulo `tokenize` de la stdlib y descarta los tokens
`COMMENT` y `STRING` — es decir, comentarios y docstrings. Lo que queda son
identificadores, palabras clave y operadores: código de verdad.

Las cadenas se descartan también, así que un SQL en un literal se le escaparía.
Por eso hay una segunda pasada, más tosca, que sí mira las cadenas y busca los
patrones que solo pueden ser SQL o rutas de módulo, nunca prosa
(`SET search_path`, `import base_saas`, `"tenant_slug"`).
"""

from __future__ import annotations

import io
import pathlib
import re
import tokenize

RAIZ = pathlib.Path(__file__).resolve().parents[1]
ARBOLES = [RAIZ / "libs", RAIZ / "services", RAIZ / "tests"]

# Identificadores del mundo anterior. En código, cualquiera de ellos es un
# resto de la cosecha que no se terminó.
IDENTIFICADORES_PROHIBIDOS = {"base_saas", "basesaas", "tenant_slug", "tenant_schema"}

# Patrones que dentro de una CADENA solo pueden ser código (SQL o un import),
# nunca prosa explicando la cosecha.
PATRONES_EN_CADENAS = [
    re.compile(r"\bSET\s+search_path\b", re.I),
    re.compile(r"\bRESET\s+search_path\b", re.I),
    re.compile(r"\bfrom\s+base_saas\b"),
    re.compile(r"\bimport\s+base_saas\b"),
    # Una columna o clave `tenant_slug` citada: SELECT tenant_slug, "tenant_slug": ...
    re.compile(r"""["']tenant_slug["']"""),
    re.compile(r"\btenant_slug\s*[,=)]"),
]


def _archivos_python() -> list[pathlib.Path]:
    archivos: list[pathlib.Path] = []
    for arbol in ARBOLES:
        if not arbol.exists():
            continue
        for ruta in arbol.rglob("*.py"):
            partes = set(ruta.parts)
            if partes & {"__pycache__", ".venv", ".ruff_cache", ".pytest_cache"}:
                continue
            # Este mismo archivo nombra los identificadores prohibidos por
            # definición: es el candado, no el candidato.
            if ruta.name == pathlib.Path(__file__).name:
                continue
            archivos.append(ruta)
    return archivos


def test_ningun_identificador_de_basesaas_en_el_codigo():
    hallazgos: list[str] = []
    for ruta in _archivos_python():
        fuente = ruta.read_text(encoding="utf-8")
        try:
            tokens = list(tokenize.generate_tokens(io.StringIO(fuente).readline))
        except tokenize.TokenError as exc:  # pragma: no cover - archivo roto
            hallazgos.append(f"{ruta}: no se pudo tokenizar ({exc})")
            continue
        for tok in tokens:
            if tok.type in (tokenize.COMMENT, tokenize.STRING):
                continue
            if tok.string in IDENTIFICADORES_PROHIBIDOS:
                hallazgos.append(f"{ruta.relative_to(RAIZ)}:{tok.start[0]}: identificador {tok.string!r}")
    assert not hallazgos, "Quedan identificadores de BaseSaaS en el código (no en comentarios):\n  " + "\n  ".join(
        hallazgos
    )


def test_ninguna_cadena_con_sql_o_imports_del_mundo_anterior():
    hallazgos: list[str] = []
    for ruta in _archivos_python():
        fuente = ruta.read_text(encoding="utf-8")
        try:
            tokens = list(tokenize.generate_tokens(io.StringIO(fuente).readline))
        except tokenize.TokenError:  # pragma: no cover
            continue
        for tok in tokens:
            if tok.type != tokenize.STRING:
                continue
            for patron in PATRONES_EN_CADENAS:
                if patron.search(tok.string):
                    hallazgos.append(f"{ruta.relative_to(RAIZ)}:{tok.start[0]}: cadena con {patron.pattern!r}")
    assert not hallazgos, "Quedan cadenas con SQL o imports de BaseSaaS:\n  " + "\n  ".join(hallazgos)


def test_ninguna_metrica_de_prometheus_conserva_el_prefijo_basesaas():
    """Las métricas son contrato con Grafana y con las alertas, no código interno.

    Una serie `basesaas_audit_write_failed_total` en producción significa que
    los dashboards heredados apuntan a un nombre y el código emite otro — o
    peor, que emiten el mismo y nadie sabe de qué producto son los datos.
    """
    hallazgos: list[str] = []
    for ruta in _archivos_python():
        for numero, linea in enumerate(ruta.read_text(encoding="utf-8").splitlines(), 1):
            if re.search(r'"basesaas_\w+"', linea):
                hallazgos.append(f"{ruta.relative_to(RAIZ)}:{numero}: {linea.strip()}")
    assert not hallazgos, "Métricas con prefijo basesaas_:\n  " + "\n  ".join(hallazgos)

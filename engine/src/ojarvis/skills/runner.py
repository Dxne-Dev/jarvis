"""Les tests et les appels d'un skill, toujours dans le bac à sable.

Le code du skill n'est jamais exécuté dans le moteur. Un petit programme d'accueil le
charge dans le bac à sable (sans réseau, sans tes fichiers), lance les tests ou l'outil
demandé, et rend le résultat sur une ligne marquée d'un jeton tiré pour chaque exécution.
"""

from __future__ import annotations

import json
import secrets
from dataclasses import dataclass, field
from typing import Any

from ojarvis.sandbox.runner import SandboxResult, SandboxRunner, SandboxUnavailableError
from ojarvis.skills.models import SkillDefinition

TESTS_TIMEOUT_S = 20.0
CALL_TIMEOUT_S = 10.0
MAX_RESULT = 20_000

_PRELUDE = """
import contextlib, io, linecache, traceback
D = DATA

def source(name, text):
    # Sans fichier sur le disque, une trace n'affiche pas la ligne fautive : on la donne.
    linecache.cache[name] = (len(text), None, text.splitlines(True), name)
    return compile(text, name, "exec")

def emit(payload):
    text = json.dumps(payload, ensure_ascii=False, default=str)
    if len(text) > D["max"]:
        text = json.dumps({"error": "Résultat trop long."})
    print(D["mark"] + text, flush=True)

def why(exc):
    return "".join(traceback.format_exception_only(exc)).strip()[:500]

ns = {"__name__": "skill"}
try:
    exec(source("skill.py", D["code"]), ns)
except BaseException as exc:
    emit({"error": "Le code ne se charge pas : " + why(exc)})
    raise SystemExit(0)
missing = [n for n in D["tools"] if not callable(ns.get(n))]
if missing:
    emit({"error": "Fonction absente du code : " + ", ".join(missing)})
    raise SystemExit(0)
"""

_TESTS = """
tns = dict(ns)
try:
    exec(source("test_skill.py", D["tests"]), tns)
except BaseException as exc:
    emit({"error": "Les tests ne se chargent pas : " + why(exc)})
    raise SystemExit(0)
cases = []
for name, fn in list(tns.items()):
    if not name.startswith("test_") or not callable(fn) or name in ns:
        continue
    try:
        with contextlib.redirect_stdout(io.StringIO()):
            fn()
        cases.append({"name": name, "ok": True})
    except AssertionError as exc:
        frames = traceback.extract_tb(exc.__traceback__)
        line = (frames[-1].line or "") if frames else ""
        cases.append({"name": name, "ok": False, "detail": (str(exc) or line)[:300]})
    except BaseException as exc:
        cases.append({"name": name, "ok": False, "detail": why(exc)})
emit({"cases": cases})
"""

_CALL = """
try:
    with contextlib.redirect_stdout(io.StringIO()):
        result = ns[D["tool"]](**D["args"])
    emit({"ok": True, "result": result})
except BaseException as exc:
    emit({"ok": False, "error": why(exc)})
"""


@dataclass(frozen=True)
class TestCase:
    __test__ = False  # pas une classe de test pour pytest

    name: str
    ok: bool
    detail: str = ""


@dataclass(frozen=True)
class TestReport:
    __test__ = False

    ok: bool
    cases: list[TestCase] = field(default_factory=list)
    error: str | None = None
    backend: str | None = None
    duration_ms: float = 0.0

    def summary(self) -> str:
        if self.error:
            return f"échec : {self.error}"
        passed = sum(1 for c in self.cases if c.ok)
        return f"{passed}/{len(self.cases)} tests réussis"

    def to_json(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "cases": [{"name": c.name, "ok": c.ok, "detail": c.detail} for c in self.cases],
            "error": self.error,
            "backend": self.backend,
            "duration_ms": self.duration_ms,
            "summary": self.summary(),
        }

    @classmethod
    def from_json(cls, data: dict[str, Any]) -> TestReport:
        return cls(
            ok=bool(data.get("ok")),
            cases=[TestCase(c["name"], bool(c["ok"]), c.get("detail", "")) for c in data["cases"]],
            error=data.get("error"),
            backend=data.get("backend"),
            duration_ms=float(data.get("duration_ms", 0.0)),
        )


class SkillCallError(RuntimeError):
    """L'outil du skill a échoué (erreur Python, temps dépassé, bac à sable absent)."""


def _script(body: str, data: dict[str, Any]) -> str:
    # Les données arrivent comme une chaîne JSON littérale : aucun code n'est assemblé à partir
    # de ce que le skill ou le modèle a écrit.
    return f"import json\nDATA = json.loads({json.dumps(data)!r})\n{_PRELUDE}{body}"


def _mark() -> str:
    # Jeton ASCII simple : `str.splitlines()` couperait sur certains caractères de contrôle.
    return f"@@ojarvis-{secrets.token_hex(8)}@@"


def _payload(result: SandboxResult, mark: str) -> dict[str, Any] | None:
    for line in reversed(result.stdout.split("\n")):
        if line.startswith(mark):
            try:
                payload: dict[str, Any] = json.loads(line[len(mark) :])
            except json.JSONDecodeError:
                return None
            return payload
    return None


def _silence(result: SandboxResult) -> str:
    if result.timed_out:
        return "temps d'exécution dépassé"
    last = result.stderr.strip().splitlines()[-1:] if result.stderr.strip() else []
    return f"aucun résultat ({last[0][:200]})" if last else "aucun résultat"


class SkillRunner:
    def __init__(self, sandbox: SandboxRunner) -> None:
        self._sandbox = sandbox

    async def test(self, skill: SkillDefinition) -> TestReport:
        mark = _mark()
        data = {
            "mark": mark,
            "max": MAX_RESULT,
            "code": skill.code,
            "tests": skill.tests,
            "tools": [t.nom for t in skill.outils],
        }
        try:
            result = await self._sandbox.run_python(
                _script(_TESTS, data), timeout_s=TESTS_TIMEOUT_S
            )
        except SandboxUnavailableError as exc:
            return TestReport(ok=False, error=f"bac à sable indisponible ({exc})")
        payload = _payload(result, mark)
        if payload is None:
            return TestReport(
                ok=False,
                error=_silence(result),
                backend=result.backend,
                duration_ms=result.duration_ms,
            )
        if "error" in payload:
            return TestReport(
                ok=False,
                error=str(payload["error"]),
                backend=result.backend,
                duration_ms=result.duration_ms,
            )
        cases = [
            TestCase(str(c["name"]), bool(c["ok"]), str(c.get("detail", "")))
            for c in payload.get("cases", [])
        ]
        if not cases:
            return TestReport(
                ok=False,
                error="aucun test trouvé",
                backend=result.backend,
                duration_ms=result.duration_ms,
            )
        return TestReport(
            ok=all(c.ok for c in cases),
            cases=cases,
            backend=result.backend,
            duration_ms=result.duration_ms,
        )

    async def call(self, skill: SkillDefinition, tool: str, args: dict[str, Any]) -> Any:
        mark = _mark()
        data = {
            "mark": mark,
            "max": MAX_RESULT,
            "code": skill.code,
            "tools": [tool],
            "tool": tool,
            "args": args,
        }
        try:
            result = await self._sandbox.run_python(_script(_CALL, data), timeout_s=CALL_TIMEOUT_S)
        except SandboxUnavailableError as exc:
            raise SkillCallError(f"bac à sable indisponible ({exc})") from exc
        payload = _payload(result, mark)
        if payload is None:
            raise SkillCallError(_silence(result))
        if "error" in payload:
            raise SkillCallError(str(payload["error"]))
        return payload["result"]

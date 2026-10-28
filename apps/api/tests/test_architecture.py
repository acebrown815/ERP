"""Module boundary rule (docs/architecture.md, Section 3.3): a module may import another module only
through that module's public facade, `app.modules.<name>.api`."""

import ast
from pathlib import Path

MODULES_DIR = Path(__file__).resolve().parent.parent / "app" / "modules"


def _imports(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    names: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            names.append(node.module)
            names.extend(f"{node.module}.{a.name}" for a in node.names)
        elif isinstance(node, ast.Import):
            names.extend(a.name for a in node.names)
    return names


def test_modules_only_use_each_others_facades() -> None:
    violations = []
    for path in MODULES_DIR.rglob("*.py"):
        own = path.relative_to(MODULES_DIR).parts[0]
        for name in _imports(path):
            parts = name.split(".")
            if parts[:2] != ["app", "modules"] or len(parts) < 4:
                continue
            other, sub = parts[2], parts[3]
            if other != own and sub != "api" and not (len(parts) == 4 and parts[3] == "api"):
                # `from app.modules.x import api` yields "app.modules.x.api" -> allowed
                violations.append(f"{path.relative_to(MODULES_DIR)} imports {name}")
    assert not violations, "\n".join(sorted(set(violations)))

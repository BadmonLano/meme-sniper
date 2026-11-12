"""Closed-world import check: every import in the drop resolves to stdlib, requirements.txt or a drop file."""
import ast
import re
import sys
from pathlib import Path

# pip name -> import name, where they differ
PIP_TO_IMPORT = {"pillow": "PIL", "python-dotenv": "dotenv"}


def _req_imports(root: Path) -> set:
    out = set()
    rq = root / "requirements.txt"
    if rq.exists():
        for ln in rq.read_text(encoding="utf-8-sig").splitlines():
            m = re.match(r"^\s*([A-Za-z0-9_.-]+)", ln.split("#", 1)[0])
            if m:
                n = m.group(1).lower()
                out.add(PIP_TO_IMPORT.get(n, n.replace("-", "_")))
    return out


def _local_names(root: Path) -> set:
    names = set()
    for p in (root / "bots").rglob("*.py"):
        names.add(p.stem)
        names.update(d.name for d in p.relative_to(root / "bots").parents if d.name)   # packages and namespace folders
    return names


def check(root) -> dict:
    """Returns {"checked": n_files, "unresolved": [(file, line, module)]}."""
    root = Path(root)
    ok = set(sys.stdlib_module_names) | _req_imports(root) | _local_names(root) | {"__future__"}
    bad, n = [], 0
    for p in sorted((root / "bots").rglob("*.py")):
        if "__pycache__" in p.parts:
            continue
        n += 1
        try:
            tree = ast.parse(p.read_text(encoding="utf-8-sig"))
        except SyntaxError as e:
            bad.append((str(p.relative_to(root)), e.lineno or 0, "<syntax error>"))
            continue
        for node in ast.walk(tree):
            mods = []
            if isinstance(node, ast.Import):
                mods = [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                mods = [node.module]
            elif (isinstance(node, ast.Call) and getattr(node.func, "attr", getattr(node.func, "id", "")) in ("import_module", "__import__")
                  and node.args and isinstance(node.args[0], ast.Constant) and isinstance(node.args[0].value, str)
                  and not node.args[0].value.startswith(".")):
                mods = [node.args[0].value]
            for m in mods:
                if m.split(".")[0] not in ok:
                    bad.append((str(p.relative_to(root)).replace("\\", "/"), node.lineno, m))
    return {"checked": n, "unresolved": bad}


if __name__ == "__main__":
    r = check(Path(__file__).resolve().parent.parent)
    for f, ln, m in r["unresolved"]:
        print(f"{f}:{ln}: {m}")
    print(f"imports: {r['checked']} files, unresolved {len(r['unresolved'])}")
    sys.exit(1 if r["unresolved"] else 0)

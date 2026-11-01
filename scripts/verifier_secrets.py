"""Bloque tout commit ou push qui contiendrait une clé d'API ou un fichier .env.

python scripts/verifier_secrets.py           : fichiers suivis par git (utilisé par GitHub Actions)
python scripts/verifier_secrets.py --staged  : fichiers prêts à être commités (crochet pre-commit)
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

PATTERNS = [re.compile(r"sk-ant-[A-Za-z0-9_\-]{12,}"), re.compile(r"ANTHROPIC_API_KEY\s*=\s*['\"]?sk-")]
FORBIDDEN_NAMES = {".env", "save.json"}


def files(staged: bool) -> list[str]:
    command = ["git", "diff", "--cached", "--name-only", "--diff-filter=ACM"] if staged else ["git", "ls-files"]
    return [f for f in subprocess.run(command, capture_output=True, text=True, check=True).stdout.splitlines() if f]


def main() -> int:
    problems = []
    for name in files("--staged" in sys.argv):
        path = Path(name)
        if path.name in FORBIDDEN_NAMES:
            problems.append(f"{name} : ce fichier ne doit jamais être publié")
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        if any(p.search(text) for p in PATTERNS):
            problems.append(f"{name} : contient ce qui ressemble à une clé d'API")
    if problems:
        print("Secret détecté, rien n'est envoyé :\n  " + "\n  ".join(problems))
        return 1
    print("Aucun secret détecté.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

"""main.py n'est importé par aucun autre test : on vérifie au moins qu'il se compile."""

from pathlib import Path


def test_main_se_compile():
    source = Path("main.py").read_text(encoding="utf-8")
    compile(source, "main.py", "exec")

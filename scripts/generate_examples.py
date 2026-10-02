"""Generate the synthetic test PDFs without downloading fonts or documents."""
from __future__ import annotations

import argparse
import importlib.util
from pathlib import Path


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description="Genera PDFs sintéticos para PDF Modder")
    parser.add_argument("--output", type=Path, default=root / "examples")
    args = parser.parse_args()
    spec = importlib.util.spec_from_file_location("pdf_modder_corpus", root / "tests" / "corpus.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    paths = module.make_corpus(args.output)
    for name, path in paths.items():
        print(f"{name}: {path}")
    print(f"Geometrías y contenido esperado: {args.output.resolve() / 'expected.json'}")


if __name__ == "__main__":
    main()

"""Fail a release when the built wheel or sdist contains unexpected files."""

from __future__ import annotations

import sys
import tarfile
import zipfile
from pathlib import Path

MODULES = {
    "__init__.py",
    "app.py",
    "audit_stream.py",
    "compatibility.py",
    "from_decision_card.py",
    "models.py",
    "registry.py",
}
ROOT_FILES = {"README.md", "LICENSE", "pyproject.toml", "PKG-INFO", ".gitignore"}


def verify_wheel(path: Path, version: str) -> None:
    with zipfile.ZipFile(path) as archive:
        names = set(archive.namelist())
    package = {f"data_contract_registry/{name}" for name in MODULES}
    info = f"data_contract_registry-{version}.dist-info/"
    metadata = {f"{info}{name}" for name in ("METADATA", "WHEEL", "RECORD", "licenses/LICENSE")}
    expected = package | metadata
    if names != expected:
        raise ValueError(
            f"wheel contents differ: missing={sorted(expected - names)} extra={sorted(names - expected)}"
        )


def verify_sdist(path: Path, version: str) -> None:
    root = f"data_contract_registry-{version}/"
    with tarfile.open(path) as archive:
        names = {name.removeprefix(root) for name in archive.getnames()}
    expected = {
        *ROOT_FILES,
        "examples/contract.yaml",
        "examples/contract.json",
        "examples/contract-number-enum.json",
        *(f"src/data_contract_registry/{name}" for name in MODULES),
        *(
            f"tests/{name}"
            for name in (
                "__init__.py",
                "conftest.py",
                "test_app.py",
                "test_audit_stream.py",
                "test_compatibility.py",
                "test_from_decision_card.py",
                "test_models.py",
                "test_registry.py",
            )
        ),
    }
    if names != expected:
        raise ValueError(
            f"sdist contents differ: missing={sorted(expected - names)} extra={sorted(names - expected)}"
        )


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit("usage: verify_dist.py VERSION")
    version = sys.argv[1]
    wheel = Path("dist") / f"data_contract_registry-{version}-py3-none-any.whl"
    sdist = Path("dist") / f"data_contract_registry-{version}.tar.gz"
    for path in (wheel, sdist):
        if not path.is_file():
            raise FileNotFoundError(path)
    verify_wheel(wheel, version)
    verify_sdist(sdist, version)
    print(f"distribution contents verified for {version}: wheel and sdist")


if __name__ == "__main__":
    main()

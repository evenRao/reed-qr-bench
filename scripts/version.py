"""Keep release metadata synchronized with VERSION without invoking version control."""

import argparse
import json
import re
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VERSION_PATTERN = r"(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)"


def validate_version(value):
    if not re.fullmatch(VERSION_PATTERN, value):
        raise ValueError("Use a stable semantic version such as 0.2.0")
    return value


def check(root=ROOT, tag=None):
    version = validate_version((root / "VERSION").read_text("utf-8").strip())
    project = tomllib.loads((root / "pyproject.toml").read_text("utf-8"))["project"]
    tools = tomllib.loads((root / "packages/reed-qr-tools/pyproject.toml").read_text("utf-8"))[
        "project"
    ]
    web = json.loads((root / "web/package.json").read_text("utf-8"))
    web_lock = json.loads((root / "web/package-lock.json").read_text("utf-8"))
    lock = tomllib.loads((root / "uv.lock").read_text("utf-8"))
    tools_init = (root / "packages/reed-qr-tools/src/reed_qr_tools/__init__.py").read_text("utf-8")
    tools_version = re.search(r'^__version__ = "([^"]+)"$', tools_init, re.MULTILINE)
    values = {
        "pyproject.toml": project["version"],
        "packages/reed-qr-tools/pyproject.toml": tools["version"],
        "reed_qr_tools.__version__": tools_version[1] if tools_version else None,
        "web/package.json": web["version"],
        "web/package-lock.json": web_lock["version"],
        "web/package-lock.json packages root": web_lock["packages"][""]["version"],
    }
    for name in ("reed-qr-bench", "reed-qr-tools"):
        packages = [p for p in lock["package"] if p["name"] == name]
        values[f"uv.lock {name}"] = packages[0]["version"] if len(packages) == 1 else None
    errors = [
        f"{name}: {value!r} != {version}" for name, value in values.items() if value != version
    ]
    if f"reed-qr-tools=={version}" not in project["dependencies"]:
        errors.append("The local reed-qr-tools dependency must match VERSION")
    if (
        "reed-qr"
        in tomllib.loads((root / "pyproject.toml").read_text("utf-8"))["tool"]["uv"]["sources"]
    ):
        errors.append("The SDK must resolve from the registry for a portable release")
    if tag is not None and tag != f"v{version}":
        errors.append(f"Release tag {tag!r} must be v{version}")
    if errors:
        raise ValueError("Version checks failed:\n" + "\n".join(errors))
    return version


def set_version(value, root=ROOT):
    value = validate_version(value)
    previous = check(root)
    for relative in ("pyproject.toml", "packages/reed-qr-tools/pyproject.toml"):
        path = root / relative
        content = path.read_text("utf-8")
        content = re.sub(
            r'^version = "[^"]+"$', f'version = "{value}"', content, count=1, flags=re.MULTILINE
        )
        if relative == "pyproject.toml":
            content = content.replace(f"reed-qr-tools=={previous}", f"reed-qr-tools=={value}")
        path.write_text(content, "utf-8", newline="\n")
    path = root / "packages/reed-qr-tools/src/reed_qr_tools/__init__.py"
    path.write_text(
        re.sub(
            r'^__version__ = "[^"]+"$',
            f'__version__ = "{value}"',
            path.read_text("utf-8"),
            flags=re.MULTILINE,
        ),
        "utf-8",
        newline="\n",
    )
    for relative in ("web/package.json", "web/package-lock.json"):
        path = root / relative
        content = json.loads(path.read_text("utf-8"))
        content["version"] = value
        if "packages" in content:
            content["packages"][""]["version"] = value
        path.write_text(json.dumps(content, indent=2) + "\n", "utf-8", newline="\n")
    path = root / "uv.lock"
    path.write_text(
        re.sub(
            r'(name = "reed-qr-(?:bench|tools)"\nversion = ")[^"]+("\n)',
            lambda match: match[1] + value + match[2],
            path.read_text("utf-8"),
        ),
        "utf-8",
        newline="\n",
    )
    (root / "VERSION").write_text(value + "\n", "utf-8", newline="\n")
    return check(root)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--check", action="store_true", help="Validate all version metadata")
    mode.add_argument("--set", metavar="VERSION", help="Update all local release metadata")
    parser.add_argument("--tag", help="Require this release tag to match VERSION")
    args = parser.parse_args()
    if args.set and args.tag:
        parser.error("--tag is only valid when checking a release")
    version = set_version(args.set) if args.set else check(tag=args.tag)
    print(f"Version metadata is consistent: {version}")


if __name__ == "__main__":
    main()

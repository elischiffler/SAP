#!/usr/bin/env python3
"""Package the deployable SAP application without local runtime data or credentials."""

import argparse
import gzip
import hashlib
import io
import stat
import tarfile
from pathlib import Path
from tempfile import NamedTemporaryFile

ROOT = Path(__file__).resolve().parent.parent
RELEASE_FILES = (
    ".dockerignore",
    "Dockerfile",
    "compose.yaml",
    "requirements.lock",
    "deploy/Caddyfile",
    "deploy/Caddyfile.shared-host",
    "deploy/Caddyfile.ec2-site",
    "deploy/compose.shared-host.yaml",
    "web/app.js",
    "web/index.html",
    "web/styles.css",
)
PYTHON_PACKAGES = ("contracts", "intelligence", "server")
SHOWCASE_FILES = (
    "index.html", "styles.css", "pitch.css", "brand.css", "brand.js",
    "showcase.js", "pager-motion.js", "brand-motion.js", "presentation.js",
    "pitch-motion.js", "ambient-motion.js", "product-flow.js", "survey.js",
    "assets/mark.svg", "assets/openai-symbol.svg", "assets/openai-symbol-source.md",
    "assets/pager-graphite-unbranded.png", "assets/yikyak-screen-time-poll.jpg",
    "assets/fonts/manrope.ttf", "assets/fonts/inter.ttf", "assets/fonts/spacegrotesk.ttf",
    "assets/fonts/manrope-OFL.txt", "assets/fonts/inter-OFL.txt", "assets/fonts/spacegrotesk-OFL.txt",
)


def release_paths() -> list[Path]:
    paths = [Path(name) for name in RELEASE_FILES]
    for directory in PYTHON_PACKAGES:
        paths.extend(path.relative_to(ROOT) for path in (ROOT / directory).glob("*.py"))
    paths.extend(path.relative_to(ROOT) for path in (ROOT / "prompts").glob("*.md"))
    # Ship the presentation runtime, excluding drafts, QA screenshots and notes.
    paths.extend(Path("web/showcase") / name for name in SHOWCASE_FILES)
    return sorted(paths)


def package(output: Path) -> str:
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with NamedTemporaryFile(dir=output.parent, prefix=".sap-release-", delete=False) as stream:
            temporary = Path(stream.name)
            with gzip.GzipFile(filename="", mode="wb", fileobj=stream, mtime=0) as compressed:
                with tarfile.open(
                    fileobj=compressed, mode="w", format=tarfile.USTAR_FORMAT
                ) as archive:
                    for relative in release_paths():
                        source = ROOT / relative
                        if not stat.S_ISREG(source.lstat().st_mode) or source.resolve() != source:
                            raise ValueError(
                                f"Release input must be a regular file inside the tree: {relative}"
                            )
                        if output.resolve() == source:
                            raise ValueError(f"Release output would replace an input: {relative}")
                        content = source.read_bytes()
                        entry = tarfile.TarInfo(relative.as_posix())
                        entry.size = len(content)
                        entry.mode = 0o644
                        archive.addfile(entry, io.BytesIO(content))
        checksum = hashlib.sha256(temporary.read_bytes()).hexdigest()
        temporary.replace(output)
        return checksum
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path, help="path for the release .tar.gz file")
    args = parser.parse_args()
    try:
        checksum = package(args.output)
    except (OSError, ValueError) as error:
        parser.exit(1, f"{error}\n")
    print(f"{checksum}  {args.output}")


if __name__ == "__main__":
    main()

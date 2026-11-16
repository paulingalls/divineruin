"""Inspect the production server image payload."""

import pathlib
import re
import tarfile


def image_sources(h, image):
    container = h.command(["docker", "create", image], capture=True)
    h.exports.append(container)
    archive = h.tmp / "image.tar"
    h.command(["docker", "export", "-o", str(archive), container])
    with tarfile.open(archive) as tree:
        paths = [entry.name.removeprefix("./") for entry in tree]
    assert "app/apps/server/src/index.ts" in paths and "app/packages/shared/src/index.ts" in paths
    bad = []
    for path in paths:
        parts = pathlib.PurePosixPath(path).parts
        if any(p == ".env" or p.startswith(".env.") or p == ".git" for p in parts):
            bad.append(path)
        if (
            path.startswith("app/")
            and "node_modules" not in parts
            and re.search(
                r"(^|/)(tests?|__tests__|fixtures|test-fixtures|mocks|__mocks__|mobile)(/|$)|[.]test[.]|/(test-env|activities-test-mock|test-util)[.]",
                path,
            )
        ):
            bad.append(path)
    assert not bad, f"image contains forbidden sources: {bad[:8]}"
    archive.unlink()
    h.command(["docker", "rm", container])
    h.exports.remove(container)

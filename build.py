"""Build against the pinned, unobfuscated Minecraft 26.3 dedicated server."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import urllib.request
import zipfile

ROOT = Path(__file__).resolve().parent
BUNDLE_SHA1 = "33680f5f2ac32864d6d7cf5e56a705fdb3e05f4c"
GAME_SHA256 = "a362163eec5d1612d520772bc16e5b39c09e3b234fdc045f56bf544284ee8ae6"
MAVEN = "https://maven.fabricmc.net/"
LOADER = "net/fabricmc/fabric-loader/0.20.1/fabric-loader-0.20.1.jar"
MIXIN = "net/fabricmc/sponge-mixin/0.17.5+mixin.0.8.7/sponge-mixin-0.17.5+mixin.0.8.7.jar"
LOADER_FILES = {
    "loader.jar": (LOADER, "d0c5a082e07410aaff9de7ab196aa6b4236002870f9ba3ad5c1260fcce5110ad"),
    "sponge-mixin.jar": (MIXIN, "03f0065023bfc3045d71bfb99872451d9ad5a0800a5a0dac34ab8c7d5c134f5d"),
}
ASM_HASHES = {
    "asm": "ed825d10ab1399c8c0cb669e688cf0c8c82629b4c8399b58352b68e92ca10fcb",
    "asm-analysis": "dede75a21306b65974ecd8f87114ff6970f09fb794157a4ca09ab25c888c2bfc",
    "asm-commons": "6d0abefb7cbf972ea16edb37ec14835372505063a45f976ab7ea889ed9497895",
    "asm-tree": "3dfb0d5b6a106cd40b5b250e39935fbf2f927f4477546a5369a3ac609cf0506b",
    "asm-util": "1bb99d091fba2597dc6d51193e9bbcf0d8447e7ed96bd8f0198b18152f09655c",
}


def digest(file: Path, algorithm: str = "sha256") -> str:
    with file.open("rb") as stream:
        return hashlib.file_digest(stream, algorithm).hexdigest()


def download(path: Path, url: str, expected: str, algorithm: str = "sha256") -> Path:
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=path.parent) as temporary:
            staging = Path(temporary) / path.name
            urllib.request.urlretrieve(url, staging)
            if digest(staging, algorithm) != expected:
                raise ValueError(f"Download hash mismatch for {path.name}")
            staging.replace(path)
    if digest(path, algorithm) != expected:
        raise ValueError(f"Cached hash mismatch for {path.name}")
    return path


def prepare_runtime(cache: Path) -> Path:
    bundle = download(cache / "minecraft-26.3-server.jar",
                      f"https://piston-data.mojang.com/v1/objects/{BUNDLE_SHA1}/server.jar", BUNDLE_SHA1, "sha1")
    runtime_dir = cache / "runtime-26.3"
    hashes = {}
    with zipfile.ZipFile(bundle) as archive:
        for group in ("versions", "libraries"):
            entries = archive.read(f"META-INF/{group}.list").decode().splitlines()
            if group == "versions" and len(entries) != 1:
                raise ValueError("Expected one game jar")
            for number, row in enumerate(entries):
                expected, _, member = row.split("\t")
                relative = "game.jar" if group == "versions" else f"lib/{number:04d}.jar"
                target = runtime_dir / relative
                content = archive.read(f"META-INF/{group}/{member}")
                if hashlib.sha256(content).hexdigest() != expected:
                    raise ValueError(f"Server bundle hash mismatch for {member}")
                target.parent.mkdir(parents=True, exist_ok=True)
                if not target.exists():
                    target.write_bytes(content)
                hashes[relative] = expected
    (runtime_dir / "runtime.json").write_text(
        json.dumps({"minecraft_version": "26.3", "artifacts": hashes}, indent=2), encoding="utf-8")
    return runtime_dir


def classpath(runtime: Path, cache: Path) -> str:
    manifest = json.loads((runtime / "runtime.json").read_text(encoding="utf-8-sig"))
    game = runtime / "game.jar"
    jars = sorted((runtime / "lib").glob("*.jar"))
    if manifest["minecraft_version"] != "26.3" or digest(game) != GAME_SHA256 or not jars:
        raise ValueError("Expected the exact Minecraft 26.3 server and libraries")
    declared_libraries = {name for name in manifest["artifacts"] if name.startswith("lib/")}
    if declared_libraries != {jar.relative_to(runtime).as_posix() for jar in jars}:
        raise ValueError("Library inventory does not match the runtime manifest")
    for jar in jars:
        if digest(jar) != manifest["artifacts"][jar.relative_to(runtime).as_posix()]:
            raise ValueError(f"Runtime library hash mismatch for {jar.name}")
    dependencies = dict(LOADER_FILES)
    for artifact, expected in ASM_HASHES.items():
        dependencies[f"{artifact}.jar"] = (f"org/ow2/asm/{artifact}/9.10.1/{artifact}-9.10.1.jar", expected)
    loader_files = [download(cache / name, MAVEN + path, expected)
                    for name, (path, expected) in dependencies.items()]
    return os.pathsep.join(map(str, [game, *jars, *loader_files]))


def package(source_set: str, javac: Path, cp: str) -> Path:
    sources = ROOT / "src" / source_set
    resources = sources / "resources"
    meta = json.loads((resources / "fabric.mod.json").read_text(encoding="utf-8"))
    output = ROOT / "build/libs" / f"{meta['id']}-{meta['version']}.jar"
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=output.parent) as directory:
        work = Path(directory)
        classes = work / "classes"
        classes.mkdir()
        java_sources = sorted((sources / "java").rglob("*.java"))
        args = ["--release", "25", "-encoding", "UTF-8", "-proc:none", "-g:source,lines",
                "-cp", cp, "-d", str(classes), *map(str, java_sources)]
        argfile = work / "javac.args"
        argfile.write_text("\n".join(json.dumps(arg.replace("\\", "/"), ensure_ascii=False) for arg in args), encoding="utf-8")
        subprocess.run([str(javac), "@" + str(argfile)], check=True)
        staged = work / "mod.jar"
        entries = [(file.relative_to(base).as_posix(), file)
                   for base in (classes, resources)
                   for file in sorted(base.rglob("*")) if file.is_file()]
        if source_set == "main":
            entries.append(("LICENSE", ROOT / "LICENSE"))
        with zipfile.ZipFile(staged, "w") as archive:
            for name, file in entries:
                info = zipfile.ZipInfo(name, date_time=(2026, 1, 1, 0, 0, 0))
                info.compress_type = zipfile.ZIP_DEFLATED
                info.external_attr = 0o100644 << 16
                archive.writestr(info, file.read_bytes())
        staged.replace(output)
    print(f"{output}\nSHA-256 {digest(output)}", flush=True)
    return output


def run_fixture(args, runtime: Path, cp: str, java: Path, production: Path, harness: Path) -> None:
    # Fresh directory and synthetic flat world. No working server or world is reused.
    output = ROOT / "local/fixtures"
    output.mkdir(parents=True, exist_ok=True)
    fixture = Path(tempfile.mkdtemp(prefix=args.fixture + "-", dir=output))
    mods = fixture / "mods"
    mods.mkdir()
    installed = [harness, *map(Path.resolve, args.extra_mod)]
    if args.fixture == "enabled":
        installed.append(production)
    if len({file.name for file in installed}) != len(installed):
        raise ValueError("Fixture contains duplicate JAR file names")
    for file in installed:
        shutil.copy2(file, mods / file.name)
    (fixture / "eula.txt").write_text("eula=true\n", encoding="utf-8")
    generator = {"biome": "minecraft:plains", "layers": [
        {"block": "minecraft:bedrock", "height": 1},
        {"block": "minecraft:dirt", "height": 2},
        {"block": "minecraft:grass_block", "height": 1},
    ]}
    properties = {
        "server-ip": "127.0.0.1", "server-port": str(args.port), "white-list": "true",
        "enable-query": "false", "enable-rcon": "false", "enable-status": "false", "online-mode": "true",
        "pause-when-empty-seconds": "0", "level-name": "fixture-26.3", "level-seed": "263", "level-type": "minecraft:flat",
        "generator-settings": json.dumps(generator, separators=(",", ":")), "generate-structures": "false",
        "difficulty": "normal", "view-distance": "3", "simulation-distance": "3",
    }
    (fixture / "server.properties").write_text(
        "".join(f"{key}={value}\n" for key, value in properties.items()), encoding="utf-8")
    command = [str(java), "-Xms256M", "-Xmx1536M", "-Dfile.encoding=UTF-8",
               f"-Dfabric.gameJarPath={runtime / 'game.jar'}", f"-Ddev.sqeedys.fixture={args.fixture}",
               "-cp", cp, "net.fabricmc.loader.impl.launch.knot.KnotServer", "nogui"]
    log = fixture / "result.log"
    print(f"Dedicated fixture log {log}", flush=True)
    with log.open("w", encoding="utf-8") as stream:
        result = subprocess.run(command, cwd=fixture, stdin=subprocess.DEVNULL, stdout=stream,
                                stderr=subprocess.STDOUT, timeout=240)
    receipt = fixture / "receipt.txt"
    passed = receipt.read_text(encoding="utf-8") if receipt.exists() else ""
    if result.returncode or not passed.startswith(f"PASS {args.fixture}\n"):
        raise SystemExit(f"Fixture failed. See {log}")
    print(passed, end="")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--java-home", required=True, type=Path)
    runtime_options = parser.add_mutually_exclusive_group(required=True)
    runtime_options.add_argument("--runtime", type=Path)
    runtime_options.add_argument("--prepare-runtime", action="store_true")
    parser.add_argument("--cache", type=Path, default=ROOT / "local/cache")
    parser.add_argument("--fixture", choices=["control", "enabled"])
    parser.add_argument("--port", type=int, default=26130)
    parser.add_argument("--accept-eula", action="store_true")
    parser.add_argument("--extra-mod", type=Path, action="append", default=[])
    args = parser.parse_args()
    if args.fixture and (not args.accept_eula or not 1024 <= args.port <= 65535):
        parser.error("A fixture requires --accept-eula and an unprivileged --port")
    if args.extra_mod and not args.fixture:
        parser.error("--extra-mod requires --fixture")
    suffix = ".exe" if os.name == "nt" else ""
    bin_dir = args.java_home.resolve() / "bin"
    javac = bin_dir / ("javac" + suffix)
    java = bin_dir / ("java" + suffix)
    version = subprocess.run([str(javac), "-version"], check=True, capture_output=True, text=True)
    if not re.match(r"javac 25(?:[.\s]|$)", version.stdout + version.stderr):
        parser.error("JDK 25 is required")
    cache = args.cache.resolve()
    runtime = args.runtime.resolve() if args.runtime else prepare_runtime(cache)
    cp = classpath(runtime, cache)
    production = package("main", javac, cp)
    if args.fixture:
        harness = package("fixture", javac, cp)
        run_fixture(args, runtime, cp, java, production, harness)


if __name__ == "__main__":
    main()

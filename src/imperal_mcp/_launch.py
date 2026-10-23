"""The `imperal-mcp` command on any Python from 3.7.

imperal-mcp needs Python 3.10+ -- its dependencies do (the MCP SDK, pydantic 2). On 3.10+ this
hands straight to the server. On an older Python pip installs imperal-mcp without those
dependencies, and this command runs the SAME release on a Python 3.12 it sets up once with uv
in its own folder: the client gets the whole server, never a reduced one. Everything it says
goes to stderr -- stdout is the MCP channel.

Kept to Python 3.7 syntax and the standard library: it is the only module an old interpreter
ever runs. webbee carries the same launcher (webbee/_launch.py)."""
import hashlib
import io
import os
import platform
import shutil
import subprocess
import sys
import tarfile
import urllib.request
import zipfile

DIST = "imperal-mcp"
ENTRY_MODULE, ENTRY_FUNC = "imperal_mcp.server", "main"
NATIVE = (3, 10)                 # the Python the dependencies need
RUNTIME_PYTHON = "3.12"
SPEC_ENV = "IMPERAL_MCP_RUNTIME_SPEC"     # what to install instead of DIST==version (tests, mirrors)
HOME_ENV = "IMPERAL_MCP_RUNTIME_HOME"
_WINDOWS = os.name == "nt"


def _version():
    """This install's release (the light install on an old Python and its runtime are one
    release). importlib.metadata is 3.8+; on 3.7 read our own dist-info next to the package."""
    try:
        from importlib.metadata import version
        return version(DIST)
    except ImportError:
        pass
    site = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    for name in os.listdir(site):
        if name.startswith("imperal_mcp-") and name.endswith(".dist-info"):
            return name[len("imperal_mcp-"):-len(".dist-info")]
    raise RuntimeError("cannot tell which imperal-mcp release this is")


def _home():
    if os.environ.get(HOME_ENV):
        return os.environ[HOME_ENV]
    if _WINDOWS:
        base = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
    else:
        base = os.environ.get("XDG_DATA_HOME") or os.path.join(os.path.expanduser("~"), ".local", "share")
    return os.path.join(base, DIST, "runtime")


def _say(msg):
    sys.stderr.write(msg + "\n")
    sys.stderr.flush()


def _bin(prefix, name):
    if _WINDOWS:
        return os.path.join(prefix, "Scripts", name + ".exe")
    return os.path.join(prefix, "bin", name)


def _find_uv(home):
    """uv from the pip-installed `uv` package (Python 3.8+), PATH, the usual install folders,
    or our own earlier bootstrap -- else None."""
    try:
        import uv  # noqa: F401  -- the PyPI `uv` package ships the binary
        found = uv.find_uv_bin()
        if found and os.path.exists(found):
            return found
    except Exception:
        pass
    name = "uv.exe" if _WINDOWS else "uv"
    candidates = [shutil.which("uv"), os.path.join(home, "uv", name)]
    for d in (os.path.join("~", ".local", "bin"), os.path.join("~", ".cargo", "bin")):
        candidates.append(os.path.join(os.path.expanduser(d), name))
    for c in candidates:
        if c and os.path.exists(c):
            return c
    return None


UV_RELEASES = "https://github.com/astral-sh/uv/releases/latest/download/"


def _uv_target():
    """uv's release name for this machine, e.g. x86_64-unknown-linux-gnu."""
    machine = platform.machine().lower()
    arch = {"x86_64": "x86_64", "amd64": "x86_64", "aarch64": "aarch64", "arm64": "aarch64",
            "i686": "i686", "i386": "i686", "armv7l": "armv7", "ppc64le": "powerpc64le",
            "s390x": "s390x"}.get(machine)
    if arch is None:
        raise RuntimeError("no uv build for a %s machine" % machine)
    if sys.platform == "darwin":
        return arch + "-apple-darwin"
    if _WINDOWS:
        return arch + "-pc-windows-msvc"
    libc = platform.libc_ver()[0]
    if arch == "armv7":
        return "armv7-unknown-linux-" + ("gnueabihf" if libc == "glibc" else "musleabihf")
    return arch + "-unknown-linux-" + ("gnu" if libc == "glibc" else "musl")


def _fetch(url):
    req = urllib.request.Request(url, headers={"User-Agent": DIST + "-launcher"})
    with urllib.request.urlopen(req, timeout=120) as r:
        return r.read()


def _install_uv(home):
    """Python 3.7 has no `uv` wheel: download uv's release build for this machine from GitHub,
    check it against the published SHA-256 and unpack it into our own folder. Standard library
    only -- no curl, no installer script, no PATH or shell-profile changes."""
    target = _uv_target()
    archive = "uv-" + target + (".zip" if _WINDOWS else ".tar.gz")
    _say("Fetching uv (it brings the Python %s %s runs on)..." % (RUNTIME_PYTHON, DIST))
    data = _fetch(UV_RELEASES + archive)
    expected = _fetch(UV_RELEASES + archive + ".sha256").decode().split()[0].lower()
    if hashlib.sha256(data).hexdigest() != expected:
        raise RuntimeError("uv download does not match its published SHA-256")
    dest = os.path.join(home, "uv")
    shutil.rmtree(dest, ignore_errors=True)
    os.makedirs(dest)
    name = "uv.exe" if _WINDOWS else "uv"
    if _WINDOWS:
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            member = next(m for m in z.namelist() if m.rsplit("/", 1)[-1] == name)
            with open(os.path.join(dest, name), "wb") as f:
                f.write(z.read(member))
    else:
        with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as t:
            member = next(m for m in t.getmembers() if m.isfile() and m.name.rsplit("/", 1)[-1] == name)
            with open(os.path.join(dest, name), "wb") as f:
                f.write(t.extractfile(member).read())
        os.chmod(os.path.join(dest, name), 0o755)
    return os.path.join(dest, name)


class _Lock(object):
    """One setup at a time when two clients start the server together."""

    def __init__(self, path):
        self.path, self.f = path, None

    def __enter__(self):
        self.f = open(self.path, "a+")
        try:
            if _WINDOWS:
                import msvcrt
                msvcrt.locking(self.f.fileno(), msvcrt.LK_LOCK, 1)
            else:
                import fcntl
                fcntl.flock(self.f.fileno(), fcntl.LOCK_EX)
        except Exception:
            pass                         # no lock beats no start
        return self

    def __exit__(self, *exc):
        self.f.close()


def runtime(version):
    """Path of the `DIST` command in a Python 3.12 environment holding this exact release;
    set up on the first call, reused after."""
    home = _home()
    os.makedirs(home, exist_ok=True)
    prefix = os.path.join(home, "py" + RUNTIME_PYTHON + "-" + version)
    exe = _bin(prefix, DIST)
    ready = os.path.join(prefix, ".ready")
    if os.path.exists(ready) and os.path.exists(exe):
        return exe
    with _Lock(os.path.join(home, ".setup.lock")):
        if os.path.exists(ready) and os.path.exists(exe):
            return exe                   # the other terminal finished it meanwhile
        _say("Python %d.%d is older than %s needs (%d.%d): setting up %s %s on Python %s "
             "once, in %s ..." % (sys.version_info[0], sys.version_info[1], DIST, NATIVE[0], NATIVE[1],
                                  DIST, version, RUNTIME_PYTHON, prefix))
        uv = _find_uv(home) or _install_uv(home)
        shutil.rmtree(prefix, ignore_errors=True)   # a half-made one from an interrupted setup
        subprocess.check_call([uv, "venv", "--quiet", "--python", RUNTIME_PYTHON, prefix],
                              stdout=sys.stderr)
        spec = os.environ.get(SPEC_ENV) or "%s==%s" % (DIST, version)
        subprocess.check_call([uv, "pip", "install", "--quiet", "--python", _bin(prefix, "python"), spec],
                              stdout=sys.stderr)
        if not os.path.exists(exe):
            raise RuntimeError("%s is missing after the install" % exe)
        open(ready, "w").close()
        for name in os.listdir(home):    # earlier releases' environments
            old = os.path.join(home, name)
            if name.startswith("py") and old != prefix and os.path.isdir(old):
                shutil.rmtree(old, ignore_errors=True)
        _say("Done -- next starts are immediate.")
    return exe


def main():
    if sys.version_info >= NATIVE:
        import importlib
        return getattr(importlib.import_module(ENTRY_MODULE), ENTRY_FUNC)()
    try:
        exe = runtime(_version())
    except Exception as e:
        _say("Could not set up %s on Python %s: %s\n"
             "Install it with uv instead (it brings its own Python):\n"
             "  curl -LsSf https://astral.sh/uv/install.sh | sh && uv tool install %s"
             % (DIST, RUNTIME_PYTHON, e, DIST))
        sys.exit(1)
    argv = [exe] + sys.argv[1:]
    if _WINDOWS:                         # no exec on Windows: run it and pass its exit code on
        sys.exit(subprocess.call(argv))
    os.execv(exe, argv)

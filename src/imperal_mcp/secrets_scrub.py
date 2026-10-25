"""Verbatim port of imperal_kernel/core/repo_memory.py ``scrub_secrets`` (SOURCE OF TRUTH: the kernel) -- the same
redaction the kernel applies before it persists a note, applied here before anything a shell hook saw leaves this
machine (final review C1). Keep the regexes IN SYNC with the kernel."""
from __future__ import annotations

import re


_SECRET_URI_USERINFO_RE = re.compile(r"(?i)(?<![a-z0-9+.-])[a-z][a-z0-9+.-]{0,31}://[^\s:@/]*:[^\s@/]+@")
# a private key is masked whole -- header, body, footer -- by one forward scan (``_mask_pem``: linear)
_SECRET_PEM_BEGIN = re.compile(r"-----BEGIN [A-Z0-9 ]{0,40}PRIVATE KEY-----")
_SECRET_PEM_END = re.compile(r"-----END [A-Z0-9 ]{0,40}PRIVATE KEY-----")


def _mask_pem(s: str) -> str:
    out, at = [], 0
    while True:
        b = _SECRET_PEM_BEGIN.search(s, at)
        if not b:
            return "".join(out) + s[at:]
        e = _SECRET_PEM_END.search(s, b.end())
        out.append(s[at:b.start()] + "[REDACTED PRIVATE KEY]")
        if not e:
            return "".join(out)            # no footer: the rest of the text is the key
        at = e.end()
# the credential after an auth scheme (``Authorization: Basic dXNl...``), not just the scheme word
_SECRET_AUTH_HEADER_RE = re.compile(r"(?i)\b((?:proxy-)?authorization[\"']?\s*[:=]\s*[\"']?)"
                                    r"(?:(?:basic|bearer|token|digest|negotiate)\s+)?[^\s\"',;]+")
# Frame v5 R5 (live 2026-10-20: ``DB_PASS: <value>`` in a WORLD fact): a key NAMED like a secret --
# ``DB_PASS``, ``PGPASSWORD``, ``MYSQL_PWD``, ``client_secret``, ``spring.datasource.password``,
# ``AUTH_TOKEN``, ``api-key`` -- keeps its name and loses its value. Linear: the match is anchored on the secret
# word with a bounded name around it, so a non-secret pair is never consumed (``a_key=1&password=x``). ``pass``/``pwd`` count only as a whole part of the name
# (``bypass``, ``repo_key``, ``input_tokens`` stay). Fail closed: the only values kept are code that cannot
# be a literal secret -- a call or a subscript of a name (``f(...)``, ``os.environ[...]``) or the key's own
# name (``token = token``).
_SECRET_NAME = (r"(?:api[_-]?key|private[_-]?key|access[_-]?key|secret|token(?![a-z])|passw(?:or)?d|authorization"
                r"|bearer|credentials?|(?<![a-z])pass(?![a-z])|(?<![a-z])pwd(?![a-z]))")
_SECRET_KEYWORD_RE = re.compile(
    r"""(?i)(?<![A-Za-z0-9_.-])([A-Za-z0-9_.-]{0,48}?""" + _SECRET_NAME + r"""[A-Za-z0-9_.-]{0,48})"""
    r"""(["']?[ \t]*[:=][ \t]*["']?)([^\s"']+)""")
_CODE_VALUE_RE = re.compile(r"^[A-Za-z_][\w.]{0,128}[(\[][^&;=,]*$")      # the WHOLE value is a call/subscript


def _keyword_redact(m: "re.Match", code: bool = False) -> str:
    key, sep, val = m.group(1), m.group(2), m.group(3)
    quoted = sep.rstrip().endswith(("'", '"'))
    if not quoted and (code or _CODE_VALUE_RE.match(val) or val.lower() == re.split(r"[_.-]", key)[-1].lower()):
        # source code (``code``): only a quoted literal is a secret -- ``password: str``, ``token=self.token``
        # stay as written, so an edit copied from the frame still matches the file
        return m.group(0)
    return f"{key}{sep}[REDACTED]"
_SECRET_BEARER_RE = re.compile(r"(?i)bearer\s+[A-Za-z0-9._-]{10,}")
_SECRET_JWT_RE = re.compile(r"eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+")
_SECRET_PREFIXED_KEY_RE = re.compile(r"\b(?:sk|rk|pk)_(?:live|test)_[A-Za-z0-9]{10,}")
_SECRET_GCP_KEY_RE = re.compile(r"\bAIza[0-9A-Za-z_-]{35}\b")
# Original fixed-shape rules — kept as-is, except the `sk-` shape (2026-08-22):
# it required 20+ CONSECUTIVE alphanumerics after `sk-`, so a modern
# hyphen-segmented vendor key (sk-ant-api03-..., sk-proj-...) broke the run at
# its first hyphen and passed through UNREDACTED into 90-day storage. Hyphen
# and underscore are now allowed inside the body. Over-redacting is safe here;
# under-redacting persists a live credential.
_SECRET_RE = re.compile(
    r"AKIA[0-9A-Z]{16}|-----BEGIN[ A-Z]+PRIVATE KEY-----|gh[pousr]_[A-Za-z0-9]{20,}"
    r"|xox[baprs]-[A-Za-z0-9-]{10,}|\bsk-[A-Za-z0-9_-]{20,}")



# imperal-mcp addition (security review; to be synced into the kernel): a token alone as URL user-info
# (``https://ghp_x@github.com``) -- a user name before ``@`` with no password is redacted too
_SECRET_URI_USER_ONLY_RE = re.compile(r"(?i)(?<![a-z0-9+.-])([a-z][a-z0-9+.-]{0,31}://)[^\s/@:]{8,}@")


def scrub_secrets(text: str, code: bool = False) -> str:
    """Redact common secret/token shapes. ``code``: the text is source code -- a secret-named key keeps an unquoted
    value (an identifier, a type, an expression)."""
    s = str(text or "")
    s = _mask_pem(s)
    s = _SECRET_URI_USERINFO_RE.sub("[REDACTED]@", s)
    s = _SECRET_URI_USER_ONLY_RE.sub(lambda m: m.group(1) + "[REDACTED]@", s)
    s = _SECRET_AUTH_HEADER_RE.sub(lambda m: f"{m.group(1)}[REDACTED]", s)
    s = _SECRET_BEARER_RE.sub("[REDACTED]", s)
    s = _SECRET_KEYWORD_RE.sub(lambda m: _keyword_redact(m, code), s)
    s = _SECRET_JWT_RE.sub("[REDACTED]", s)
    s = _SECRET_PREFIXED_KEY_RE.sub("[REDACTED]", s)
    s = _SECRET_GCP_KEY_RE.sub("[REDACTED]", s)
    s = _SECRET_RE.sub("[REDACTED]", s)
    return s


_CODE_EXT = frozenset({"py", "pyi", "js", "jsx", "mjs", "cjs", "ts", "tsx", "go", "rs", "java", "kt", "kts", "scala",
                       "rb", "php", "c", "h", "cc", "cpp", "hpp", "cs", "swift", "m", "mm", "dart", "lua", "vue",
                       "svelte", "ex", "exs", "erl", "clj", "hs", "ml", "fs", "r", "jl", "pl", "pm"})


def is_code_path(path: str) -> bool:
    name = str(path or "").replace("\\", "/").rsplit("/", 1)[-1].lower()
    return "." in name and not name.startswith(".env") and name.rsplit(".", 1)[-1] in _CODE_EXT

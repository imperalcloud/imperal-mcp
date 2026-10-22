from imperal_mcp.core import (
    CancellationToken,
    StreamEmitter,
    SchemaValidator,
    ICNLIComponent,
)

# One source of truth: the version in pyproject.toml (the installed package's metadata).
try:
    from importlib.metadata import PackageNotFoundError, version as _pkg_version

    __version__ = _pkg_version("imperal-mcp")
except PackageNotFoundError:  # a source checkout that is not installed
    __version__ = "0.0.0+unknown"

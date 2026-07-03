"""Inter-extension IPC — direct in-process calls, kernel-mediated."""
from imperal_sdk.extensions.client import ExtensionsClient, CircularCallError

__all__ = ["ExtensionsClient", "CircularCallError"]

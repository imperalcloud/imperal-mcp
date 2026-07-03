# Copyright (c) 2026 Imperal, Inc., Valentin Scerbacov, and contributors
# Licensed under the Apache-2.0 License. See LICENSE file for details.
from imperal_sdk.auth.client import ImperalAuth, AuthError

# Note: User/Tenant relocated to imperal_sdk.types.identity in v3.0.0 (W1).
__all__ = ["ImperalAuth", "AuthError"]

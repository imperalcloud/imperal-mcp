"""Secret-related SDK exceptions. Federal rule: NEVER embed plaintext in messages."""


class SecretNotDeclaredError(Exception):
    """ctx.secrets.* called with a name not in the manifest's secrets[].

    Manifest is the single source of truth for what an extension may touch
    (I-SECRETS-CONTRACT-DECLARED).
    """


class SecretWriteForbidden(Exception):
    """ctx.secrets.set() called for a secret with manifest write_mode='user'.

    Only the Panel UI (user-attributable session) can write 'user'-mode
    secrets. Extension code can write secrets declared with
    write_mode='extension' or write_mode='both'.
    """


class SecretVaultUnavailable(Exception):
    """auth-gw returned 503; Vault transit endpoint is down.

    Per I-SECRETS-VAULT-DEPENDENCY, the SDK fails closed — no fallback
    decryption, no cached plaintext.
    """


class SecretValueTooLarge(Exception):
    """Written value exceeds the manifest's max_bytes for this secret."""


class SecretDeclarationConflict(Exception):
    """@ext.secret declared the same name twice for one Extension."""

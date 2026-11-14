"""Encrypts what the platform keeps secret in its database: the model providers' API keys.
The master key stays outside the database (ADA_SECRET_KEY)."""

from typing import Protocol


class SecretUnreadable(Exception):
    """A stored secret cannot be decrypted: the master key changed or is not set."""


class SecretBox(Protocol):
    @property
    def available(self) -> bool:
        """False when no master key is set: nothing can be encrypted or decrypted."""
        ...

    def encrypt(self, text: str) -> str:
        """A token to store in place of `text`. Only called when available."""
        ...

    def decrypt(self, token: str) -> str:
        """The text of a token. Raises SecretUnreadable when the master key cannot read it
        (another key made it) or no master key is set."""
        ...

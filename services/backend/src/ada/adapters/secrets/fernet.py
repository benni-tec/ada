"""SecretBox with Fernet (the `cryptography` package): authenticated encryption under a
master key from ADA_SECRET_KEY.

The master key may hold several Fernet keys separated by commas. The first encrypts; all
of them decrypt, so a key is rotated by putting the new one in front, and the old one can
go once every stored secret has been saved again.
"""

from cryptography.fernet import Fernet, InvalidToken, MultiFernet

from ada.core.ports.secrets import SecretBox, SecretUnreadable


class InvalidMasterKey(ValueError):
    """ADA_SECRET_KEY is set but is not a Fernet key. Stops the start: a key that was meant
    to be used must not be silently ignored."""


class FernetSecretBox(SecretBox):
    def __init__(self, master_key: str | None) -> None:
        keys = [key.strip() for key in (master_key or "").split(",") if key.strip()]
        try:
            self._fernet = MultiFernet([Fernet(key) for key in keys]) if keys else None
        except ValueError as error:
            raise InvalidMasterKey(
                "ADA_SECRET_KEY is not a Fernet key (32 bytes, urlsafe base64), or a list of "
                "them separated by commas. Generate one with: python -c 'from "
                "cryptography.fernet import Fernet; print(Fernet.generate_key().decode())'"
            ) from error

    @property
    def available(self) -> bool:
        return self._fernet is not None

    def encrypt(self, text: str) -> str:
        if self._fernet is None:
            raise SecretUnreadable("No master key is set (ADA_SECRET_KEY)")
        return self._fernet.encrypt(text.encode()).decode()

    def decrypt(self, token: str) -> str:
        if self._fernet is None:
            raise SecretUnreadable("No master key is set (ADA_SECRET_KEY)")
        try:
            return self._fernet.decrypt(token.encode()).decode()
        except InvalidToken as error:
            raise SecretUnreadable("The master key cannot decrypt this secret") from error

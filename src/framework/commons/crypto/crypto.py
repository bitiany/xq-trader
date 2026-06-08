import base64
import hashlib
import os

from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

from framework.commons.exceptions import BusinessException
from framework.commons.logger import get_logger

logger = get_logger("CRYPTO")

_DEFAULT_SALT = b"finqat_gateway_salt"
_DEFAULT_ITERATIONS = 480000


class CryptoUtils:

    @staticmethod
    def generate_key(secret: str | None = None, salt: bytes = _DEFAULT_SALT) -> bytes:
        if secret is None:
            secret = os.environ.get("FINQAT_CRYPTO_SECRET", "finqat.vuca.com")
        kdf = PBKDF2HMAC(
            algorithm=hashes.SHA256(),
            length=32,
            salt=salt,
            iterations=_DEFAULT_ITERATIONS,
        )
        return base64.urlsafe_b64encode(kdf.derive(secret.encode()))

    @staticmethod
    def encrypt(plaintext: str, secret: str | None = None) -> str:
        key = CryptoUtils.generate_key(secret)
        f = Fernet(key)
        encrypted = f.encrypt(plaintext.encode())
        return encrypted.decode()

    @staticmethod
    def decrypt(ciphertext: str, secret: str | None = None) -> str:
        key = CryptoUtils.generate_key(secret)
        f = Fernet(key)
        decrypted = f.decrypt(ciphertext.encode())
        return decrypted.decode()

    @staticmethod
    def is_encrypted(value: str) -> bool:
        if not value:
            return False
        return value.strip().startswith("${ENC:") and value.strip().endswith("}")

    @staticmethod
    def extract_encrypted_value(value: str) -> str:
        stripped = value.strip()
        inner = stripped[6:-1]
        return inner.strip()

    @staticmethod
    def decrypt_if_encrypted(value: str | None, secret: str | None = None) -> str | None:
        if value is None:
            return None
        if not CryptoUtils.is_encrypted(value):
            return value
        encrypted_part = CryptoUtils.extract_encrypted_value(value)
        try:
            return CryptoUtils.decrypt(encrypted_part, secret)
        except Exception as e:
            logger.error(f"解密失败: {e}", exc_info=True)
            raise BusinessException(f"密码解密失败，请检查密文或加密密钥: {e}")

    @staticmethod
    def hash_sha256(value: str) -> str:
        return hashlib.sha256(value.encode()).hexdigest()

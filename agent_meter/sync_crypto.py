"""Cloud-sync key derivation and pairing crypto, byte-compatible with the Mac.

The service only ever stores ciphertext. This module is the one place that
turns a 32-byte master key into the keys the service never sees, and it must
match `SyncKeys` / `PairingCrypto` in the Swift client exactly:

* HKDF-SHA256, same salt and info strings;
* HMAC-SHA256 bearer token, standard base64 with padding;
* ChaCha20-Poly1305 in CryptoKit's "combined" layout (12-byte nonce first).

Nothing here prints, logs or stores key material. Callers pass bytes in and
get bytes out.
"""

import base64
import hashlib
import hmac
import secrets

SPACE_RE = r"^[0-9a-f]{32}$"
MASTER_KEY_BYTES = 32
PAIR_WRAP_INFO = b"agentmeter-pair-wrap-v1"
PAIR_SAS_INFO = b"agentmeter-pair-sas-v1"
SYNC_SALT_LABEL = b"agentmeter-sync-salt-v1"
SYNC_ENC_INFO = b"agentmeter-sync-enc-v1"
AUTH_LABEL = b"agentmeter-auth-v1:"
NONCE_BYTES = 12


class SyncCryptoError(ValueError):
    """Key material or a ciphertext did not have the expected shape."""


def _require(condition, code="invalid_key_material"):
    if not condition:
        raise SyncCryptoError(code)


def is_space_id(value):
    """32 lowercase ASCII hex characters, the only shape the service takes."""
    if not isinstance(value, str) or len(value) != 32:
        return False
    return all("0" <= ch <= "9" or "a" <= ch <= "f" for ch in value)


def random_identifier():
    """A non-secret device/space label: 16 random bytes as 32 lowercase hex."""
    return secrets.token_hex(16)


def random_master_key():
    return secrets.token_bytes(MASTER_KEY_BYTES)


def b64url_encode(data):
    """Unpadded base64url, as the pairing endpoints store."""
    return base64.urlsafe_b64encode(data).decode("ascii").rstrip("=")


def b64url_decode(value):
    if not isinstance(value, str):
        return None
    try:
        raw = base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))
    except (ValueError, TypeError):
        return None
    return raw


def b64_standard_encode(data):
    return base64.b64encode(data).decode("ascii")


def b64_standard_decode(value):
    if not isinstance(value, str):
        return None
    try:
        return base64.b64decode(value, validate=True)
    except (ValueError, TypeError):
        return None


def _hkdf(ikm, salt, info, length):
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.kdf.hkdf import HKDF

    return HKDF(algorithm=hashes.SHA256(), length=length, salt=salt, info=info).derive(ikm)


def _chacha():
    from cryptography.hazmat.primitives.ciphers.aead import ChaCha20Poly1305

    return ChaCha20Poly1305


class SyncKeys:
    """The per-space key material, derived from a master key and a space id."""

    __slots__ = ("master_key", "space_id", "_encryption_key", "_auth_token", "_salt")

    def __init__(self, master_key, space_id):
        _require(isinstance(master_key, (bytes, bytearray)) and len(master_key) == MASTER_KEY_BYTES, "invalid_master_key")
        _require(is_space_id(space_id), "invalid_space_id")
        self.master_key = bytes(master_key)
        self.space_id = space_id
        self._salt = hashlib.sha256(SYNC_SALT_LABEL + space_id.encode("ascii")).digest()
        self._encryption_key = None
        self._auth_token = None

    @property
    def salt(self):
        return self._salt

    @property
    def encryption_key(self):
        if self._encryption_key is None:
            self._encryption_key = _hkdf(self.master_key, self._salt, SYNC_ENC_INFO, 32)
        return self._encryption_key

    @property
    def auth_token(self):
        """Bearer token; standard base64, padded, exactly like the Mac."""
        if self._auth_token is None:
            digest = hmac.new(self.master_key, AUTH_LABEL + self.space_id.encode("ascii"),
                              hashlib.sha256).digest()
            self._auth_token = b64_standard_encode(digest)
        return self._auth_token

    @property
    def auth_hash(self):
        """What the service stores instead of the token."""
        return hashlib.sha256(self.auth_token.encode("utf-8")).hexdigest()

    def seal(self, plaintext):
        _require(isinstance(plaintext, (bytes, bytearray)), "invalid_plaintext")
        chacha = _chacha()(self.encryption_key)
        nonce = secrets.token_bytes(NONCE_BYTES)
        sealed = chacha.encrypt(nonce, bytes(plaintext), None)
        return nonce + sealed

    def open(self, ciphertext):
        _require(isinstance(ciphertext, (bytes, bytearray)), "invalid_ciphertext")
        blob = bytes(ciphertext)
        _require(len(blob) >= NONCE_BYTES + 16, "invalid_ciphertext")
        try:
            return _chacha()(self.encryption_key).decrypt(blob[:NONCE_BYTES], blob[NONCE_BYTES:], None)
        except Exception:
            raise SyncCryptoError("crypto_failed") from None


class PairingCode:
    """A six-digit code, handled as ASCII digits only."""

    @staticmethod
    def normalize(raw):
        if not isinstance(raw, str):
            return None
        digits = "".join(ch for ch in raw if "0" <= ch <= "9")
        return digits if len(digits) == 6 else None

    @staticmethod
    def is_valid(code):
        return isinstance(code, str) and PairingCode.normalize(code) == code

    @staticmethod
    def grouped(code):
        return code[:3] + " " + code[3:] if PairingCode.is_valid(code) else code


def _parse_json(raw):
    import json

    try:
        value = json.loads(raw)
    except (ValueError, UnicodeDecodeError):
        return None
    return value if isinstance(value, dict) else None


def _dumps_json(value):
    import json

    return json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


class PairingCrypto:
    """X25519, HKDF and ChaCha20-Poly1305 for the pairing handoff."""

    @staticmethod
    def new_key_pair():
        from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey

        private = X25519PrivateKey.generate()
        from cryptography.hazmat.primitives import serialization

        public = private.public_key().public_bytes(serialization.Encoding.Raw,
                                                   serialization.PublicFormat.Raw)
        private_raw = private.private_bytes(serialization.Encoding.Raw,
                                            serialization.PrivateFormat.Raw,
                                            serialization.NoEncryption())
        return private_raw, public

    @staticmethod
    def public_from_private(private_raw):
        from cryptography.hazmat.primitives import serialization
        from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey

        private = X25519PrivateKey.from_private_bytes(private_raw)
        return private.public_key().public_bytes(serialization.Encoding.Raw,
                                                 serialization.PublicFormat.Raw)

    @staticmethod
    def shared_secret(private_raw, peer_public):
        _require(isinstance(private_raw, (bytes, bytearray)) and len(private_raw) == 32, "crypto_failed")
        _require(isinstance(peer_public, (bytes, bytearray)) and len(peer_public) == 32, "crypto_failed")
        from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey, X25519PublicKey

        try:
            peer = X25519PublicKey.from_public_bytes(bytes(peer_public))
            private = X25519PrivateKey.from_private_bytes(bytes(private_raw))
            return private.exchange(peer)
        except Exception:
            raise SyncCryptoError("crypto_failed") from None

    @staticmethod
    def wrap_key(shared, slot_id):
        _require(isinstance(shared, (bytes, bytearray)) and len(shared) == 32, "crypto_failed")
        _require(isinstance(slot_id, str) and slot_id, "crypto_failed")
        return _hkdf(bytes(shared), slot_id.encode("utf-8"), PAIR_WRAP_INFO, 32)

    @staticmethod
    def sas(shared, slot_id):
        _require(isinstance(shared, (bytes, bytearray)) and len(shared) == 32, "crypto_failed")
        _require(isinstance(slot_id, str) and slot_id, "crypto_failed")
        key = _hkdf(bytes(shared), slot_id.encode("utf-8"), PAIR_SAS_INFO, 8)
        return f"{int.from_bytes(key[:4], 'big') % 1_000_000:06d}"

    @staticmethod
    def seal(space_id, master_key, key):
        """JSON {space_id, master_key} in CryptoKit combined layout."""
        _require(is_space_id(space_id), "crypto_failed")
        _require(isinstance(master_key, (bytes, bytearray)) and len(master_key) == 32, "crypto_failed")
        _require(isinstance(key, (bytes, bytearray)) and len(key) == 32, "crypto_failed")
        plain = _dumps_json({"space_id": space_id,
                             "master_key": b64url_encode(bytes(master_key))})
        nonce = secrets.token_bytes(NONCE_BYTES)
        return nonce + _chacha()(bytes(key)).encrypt(nonce, plain, None)

    @staticmethod
    def open(ciphertext, key):
        _require(isinstance(ciphertext, (bytes, bytearray)), "crypto_failed")
        _require(isinstance(key, (bytes, bytearray)) and len(key) == 32, "crypto_failed")
        blob = bytes(ciphertext)
        _require(len(blob) >= NONCE_BYTES + 16, "crypto_failed")
        try:
            plain = _chacha()(bytes(key)).decrypt(blob[:NONCE_BYTES], blob[NONCE_BYTES:], None)
        except Exception:
            raise SyncCryptoError("crypto_failed") from None
        payload = _parse_json(plain)
        if not payload:
            raise SyncCryptoError("crypto_failed")
        space_id = payload.get("space_id")
        master = b64url_decode(payload.get("master_key"))
        if not is_space_id(space_id) or master is None or len(master) != 32:
            raise SyncCryptoError("crypto_failed")
        return space_id, master

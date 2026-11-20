"""Sync crypto vectors and pairing handoff, independent of any server."""
import base64
import unittest

from agent_meter.sync_crypto import (PairingCode, PairingCrypto, SyncCryptoError, SyncKeys,
                                     b64_standard_decode, b64_standard_encode, b64url_decode,
                                     b64url_encode)

SPACE = "0123456789abcdef0123456789abcdef"
MASTER = bytes(range(32))
# Produced by CryptoKit with the same inputs. Byte-for-byte compatibility is
# the point: a Windows key that derives a different token cannot join a Mac
# space.
SWIFT_TOKEN = "TH14GvDazboxTka1eillAGvumzzn4Lw5meO4jUmYlnQ="
SWIFT_HASH = "61c14706199816e73b268cd4070c962702d1b6adcad7a505d0cf144725492d77"
SWIFT_ENC = "4091b4527dd2aee54bb6f36f6850dd86bbdf3f8445d602f309dc1d83bd5d9fb9"
# CryptoKit ChaChaPoly.seal(b"agentmeter-vector").combined, standard base64.
SWIFT_CIPHERTEXT = "TAW9PCyOFXkTbDcqYulgyTMB6q8lfK/Kn8gJjFCwGWldn0xSXC2537PdwQau"


class KeyDerivationTests(unittest.TestCase):
    def test_swift_vector(self):
        keys = SyncKeys(MASTER, SPACE)
        self.assertEqual(keys.auth_token, SWIFT_TOKEN)
        self.assertEqual(keys.auth_hash, SWIFT_HASH)
        self.assertEqual(keys.encryption_key.hex(), SWIFT_ENC)

    def test_opens_cryptokit_ciphertext(self):
        keys = SyncKeys(MASTER, SPACE)
        self.assertEqual(keys.open(base64.b64decode(SWIFT_CIPHERTEXT)), b"agentmeter-vector")

    def test_seal_roundtrip_and_tamper(self):
        keys = SyncKeys(MASTER, SPACE)
        sealed = keys.seal(b"hello")
        self.assertEqual(keys.open(sealed), b"hello")
        changed = bytearray(sealed)
        changed[-1] ^= 1
        with self.assertRaises(SyncCryptoError):
            keys.open(bytes(changed))

    def test_shape_validation(self):
        with self.assertRaises(SyncCryptoError):
            SyncKeys(b"short", SPACE)
        with self.assertRaises(SyncCryptoError):
            SyncKeys(MASTER, SPACE.upper())
        with self.assertRaises(SyncCryptoError):
            SyncKeys(MASTER, SPACE[:-1])

    def test_standard_and_url_base64_are_distinct(self):
        raw = b"\xfb\xff"
        self.assertEqual(b64_standard_encode(raw), "+/8=")
        self.assertEqual(b64url_encode(raw), "-_8")
        self.assertEqual(b64_standard_decode("+/8="), raw)
        self.assertEqual(b64url_decode("-_8"), raw)


class PairingTests(unittest.TestCase):
    def test_sas_and_sealed_key(self):
        private_a, public_a = PairingCrypto.new_key_pair()
        private_b, public_b = PairingCrypto.new_key_pair()
        shared_a = PairingCrypto.shared_secret(private_a, public_b)
        shared_b = PairingCrypto.shared_secret(private_b, public_a)
        self.assertEqual(shared_a, shared_b)
        self.assertEqual(PairingCrypto.sas(shared_a, "slot-1"),
                         PairingCrypto.sas(shared_b, "slot-1"))
        self.assertRegex(PairingCrypto.sas(shared_a, "slot-1"), r"^[0-9]{6}$")
        wrap = PairingCrypto.wrap_key(shared_b, "slot-1")
        sealed = PairingCrypto.seal(SPACE, MASTER, wrap)
        opened = PairingCrypto.open(sealed, PairingCrypto.wrap_key(shared_a, "slot-1"))
        self.assertEqual(opened, (SPACE, MASTER))

    def test_wrong_slot_does_not_open(self):
        private_a, public_a = PairingCrypto.new_key_pair()
        private_b, public_b = PairingCrypto.new_key_pair()
        shared_a = PairingCrypto.shared_secret(private_a, public_b)
        shared_b = PairingCrypto.shared_secret(private_b, public_a)
        sealed = PairingCrypto.seal(SPACE, MASTER, PairingCrypto.wrap_key(shared_b, "slot-1"))
        with self.assertRaises(SyncCryptoError):
            PairingCrypto.open(sealed, PairingCrypto.wrap_key(shared_a, "slot-2"))

    def test_code_normalization(self):
        self.assertEqual(PairingCode.normalize("123 456"), "123456")
        self.assertEqual(PairingCode.normalize("123-456"), "123456")
        self.assertIsNone(PairingCode.normalize("12345"))
        self.assertIsNone(PairingCode.normalize("1234567"))
        self.assertIsNone(PairingCode.normalize("１２３４５６"))
        self.assertEqual(PairingCode.grouped("123456"), "123 456")


if __name__ == "__main__":
    unittest.main()

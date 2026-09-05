from __future__ import annotations

import base64
import binascii
import ctypes
import hashlib
import json
import os
import uuid
from pathlib import Path
from typing import Any


class SecureCredentialError(RuntimeError):
    """Base error for protected credential storage."""


class SecureStorageUnavailable(SecureCredentialError):
    """Raised when the required operating-system credential protection is unavailable."""


class SecureCredentialCorrupt(SecureCredentialError):
    """Raised when a protected credential envelope cannot be safely decoded."""


_MAX_CREDENTIAL_BYTES = 1024 * 1024
_MAX_ENVELOPE_BYTES = 2 * 1024 * 1024
_ENVELOPE_VERSION = 1
_PROTECTION_SCHEME = "windows-dpapi-current-user"


def secure_storage_available() -> bool:
    """Return whether this process can use the required no-fallback storage scheme."""
    return os.name == "nt" and hasattr(ctypes, "WinDLL")


def _purpose_entropy(purpose: str) -> bytes:
    normalized = str(purpose).strip()
    if not normalized or len(normalized) > 200:
        raise SecureCredentialError("A bounded credential-storage purpose is required")
    return hashlib.sha256(f"PayProof secure credential|{normalized}".encode("utf-8")).digest()


def _dpapi_transform(value: bytes, purpose: str, *, protect: bool) -> bytes:
    if not secure_storage_available():
        raise SecureStorageUnavailable(
            "OS-protected credential storage is unavailable; plaintext storage is disabled"
        )
    if not value or len(value) > _MAX_CREDENTIAL_BYTES:
        raise SecureCredentialError("Credential data must be between 1 byte and 1 MB")

    from ctypes import wintypes

    class DataBlob(ctypes.Structure):
        _fields_ = [
            ("cbData", wintypes.DWORD),
            ("pbData", ctypes.POINTER(ctypes.c_ubyte)),
        ]

    def make_blob(data: bytes) -> tuple[Any, DataBlob]:
        buffer = (ctypes.c_ubyte * len(data)).from_buffer_copy(data)
        return buffer, DataBlob(
            len(data), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_ubyte))
        )

    entropy = _purpose_entropy(purpose)
    input_buffer, input_blob = make_blob(value)
    entropy_buffer, entropy_blob = make_blob(entropy)
    output_blob = DataBlob()
    crypt32 = ctypes.WinDLL("crypt32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    crypt32.CryptProtectData.argtypes = [
        ctypes.POINTER(DataBlob),
        wintypes.LPCWSTR,
        ctypes.POINTER(DataBlob),
        ctypes.c_void_p,
        ctypes.c_void_p,
        wintypes.DWORD,
        ctypes.POINTER(DataBlob),
    ]
    crypt32.CryptProtectData.restype = wintypes.BOOL
    crypt32.CryptUnprotectData.argtypes = [
        ctypes.POINTER(DataBlob),
        ctypes.POINTER(wintypes.LPWSTR),
        ctypes.POINTER(DataBlob),
        ctypes.c_void_p,
        ctypes.c_void_p,
        wintypes.DWORD,
        ctypes.POINTER(DataBlob),
    ]
    crypt32.CryptUnprotectData.restype = wintypes.BOOL
    kernel32.LocalFree.argtypes = [ctypes.c_void_p]
    kernel32.LocalFree.restype = ctypes.c_void_p

    try:
        if protect:
            succeeded = crypt32.CryptProtectData(
                ctypes.byref(input_blob),
                "PayProof protected credential",
                ctypes.byref(entropy_blob),
                None,
                None,
                0x1,  # CRYPTPROTECT_UI_FORBIDDEN
                ctypes.byref(output_blob),
            )
        else:
            succeeded = crypt32.CryptUnprotectData(
                ctypes.byref(input_blob),
                None,
                ctypes.byref(entropy_blob),
                None,
                None,
                0x1,
                ctypes.byref(output_blob),
            )
        if not succeeded:
            error_code = ctypes.get_last_error()
            raise SecureCredentialError(
                f"Windows credential protection failed (error {error_code})"
            )
        try:
            return ctypes.string_at(output_blob.pbData, output_blob.cbData)
        finally:
            if output_blob.pbData:
                kernel32.LocalFree(ctypes.cast(output_blob.pbData, ctypes.c_void_p))
    finally:
        ctypes.memset(input_buffer, 0, len(value))
        ctypes.memset(entropy_buffer, 0, len(entropy))


def protect_text(plaintext: str, purpose: str) -> str:
    protected = _dpapi_transform(plaintext.encode("utf-8"), purpose, protect=True)
    envelope = {
        "ciphertext": base64.b64encode(protected).decode("ascii"),
        "protection": _PROTECTION_SCHEME,
        "version": _ENVELOPE_VERSION,
    }
    return json.dumps(envelope, sort_keys=True, separators=(",", ":"))


def unprotect_text(envelope_text: str, purpose: str) -> str:
    if len(envelope_text.encode("utf-8")) > _MAX_ENVELOPE_BYTES:
        raise SecureCredentialCorrupt("The protected credential envelope is too large")
    try:
        envelope = json.loads(envelope_text)
        if not isinstance(envelope, dict):
            raise ValueError("not an object")
        if envelope.get("version") != _ENVELOPE_VERSION:
            raise ValueError("unsupported version")
        if envelope.get("protection") != _PROTECTION_SCHEME:
            raise ValueError("unsupported protection scheme")
        encoded = envelope.get("ciphertext")
        if not isinstance(encoded, str) or not encoded:
            raise ValueError("missing ciphertext")
        protected = base64.b64decode(encoded.encode("ascii"), validate=True)
        plaintext = _dpapi_transform(protected, purpose, protect=False)
        return plaintext.decode("utf-8")
    except SecureCredentialError:
        raise
    except (UnicodeError, ValueError, TypeError, json.JSONDecodeError, binascii.Error) as exc:
        raise SecureCredentialCorrupt("The protected credential envelope is invalid") from exc


def write_protected_text(path: Path, plaintext: str, purpose: str) -> None:
    """Atomically persist ciphertext only; plaintext is never written to a file."""
    envelope = protect_text(plaintext, purpose)
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary.write_text(envelope, encoding="utf-8")
        os.replace(temporary, path)
    except OSError as exc:
        raise SecureCredentialError("The protected credential could not be saved") from exc
    finally:
        try:
            temporary.unlink(missing_ok=True)
        except OSError:
            pass


def read_protected_text(path: Path, purpose: str) -> str:
    try:
        size = path.stat().st_size
        if size <= 0 or size > _MAX_ENVELOPE_BYTES:
            raise SecureCredentialCorrupt("The protected credential envelope has an invalid size")
        envelope = path.read_text(encoding="utf-8")
    except SecureCredentialError:
        raise
    except (OSError, UnicodeError) as exc:
        raise SecureCredentialCorrupt("The protected credential could not be read") from exc
    return unprotect_text(envelope, purpose)

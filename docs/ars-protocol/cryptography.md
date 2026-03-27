# Cryptography

ARS uses Ed25519 digital signatures for authentication and SHA-256 hashing for content addressing. Every participant is identified by an Ed25519 public key, and every action is signed before the server accepts it.

## Ed25519 Signing

Every event in the protocol is wrapped in a `SignedActionEnvelope` containing:

- `type`: the event type string
- `job_id`: the job identifier
- `agreement_hash`: SHA-256 hash of the canonical agreement
- `payload`: event-specific data
- `actor`: the signer's hex-encoded Ed25519 public key
- `timestamp`: ISO 8601 UTC timestamp
- `signature`: hex-encoded 64-byte Ed25519 signature

The signing process:

1. Construct the envelope body (all fields except `signature`).
2. Canonicalize the body using deterministic JSON serialization.
3. Sign the canonical bytes with the actor's Ed25519 private key.
4. Attach the hex-encoded signature.

The server verifies every signature before accepting an event. Failed verification returns HTTP 401.

## RFC 8785 Canonicalization

To ensure the same data always produces the same signature, ARS uses a subset of RFC 8785 JSON Canonicalization Scheme (JCS). For the data types used in ARS (strings, integers, booleans, null, nested dicts and lists), sorted-key JSON with minimal whitespace is sufficient:

```python
json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
```

This produces deterministic byte sequences regardless of the original key ordering or whitespace in the input JSON.

## Agreement Hashing

Every action after job creation must reference the SHA-256 hash of the canonicalized agreement. This hash is computed when the job is created or when a proposal is submitted, and it binds all subsequent events to that specific agreement version.

```python
agreement_hash = hashlib.sha256(canonicalize(agreement_dict)).hexdigest()
```

If an envelope's `agreement_hash` does not match the stored hash, the server rejects it with HTTP 400. This prevents actors from submitting events against a stale or modified agreement.

## Key Generation

Participants generate Ed25519 keypairs using PyNaCl:

```python
from nacl.signing import SigningKey

sk = SigningKey.generate()
public_key_hex = sk.verify_key.encode().hex()
```

The public key (32 bytes, hex-encoded to 64 characters) is shared and used to identify the participant in agreements. The private key (also 32 bytes) is kept secret and used for signing.

## Mandate Signing (AP2)

AP2-ARS extends the base signing for Verifiable Digital Credentials (VDCs). Each mandate (IntentMandate, CartMandate, PaymentMandate) is signed using the same Ed25519 + canonical JSON pattern, but the signable portion is the mandate body with the `signature` field excluded:

1. Serialize the mandate to a dict.
2. Remove the `signature` field.
3. Canonicalize and sign the remaining fields.
4. Patch the real signature back into the mandate.

Mandate hashes (used for cross-referencing, e.g., PaymentMandate references CartMandate) are SHA-256 of the canonicalized claims (excluding signature).

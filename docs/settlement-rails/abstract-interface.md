# Abstract Settlement Interface

The settlement abstractions live in `src/ars/escrow.py` and `src/ars/settlement.py`. They define the contract that any concrete implementation must fulfill.

## EscrowClient ABC

`EscrowClient` is the base escrow abstraction. All methods are async.

```python
class EscrowClient(ABC):
    async def record_deposit(self, job_id, deposit_type, payer, payee, amount) -> str
    async def release(self, job_id, deposit_type) -> str
    async def refund(self, job_id, deposit_type) -> str
    async def slash(self, job_id, treasury) -> str
    async def get_deposit(self, job_id, deposit_type) -> Optional[DepositInfo]
```

**record_deposit** tags a deposit after funds have been transferred. It takes the job ID, deposit type (FEE, COLLATERAL, or PRINCIPAL), payer address, payee address, and amount. Returns a transaction hash or reference.

**release** sends funds from the deposit to the payee. Used when a deliverable passes evaluation (fee) or when principal release is approved.

**refund** returns funds to the payer. Used when a deliverable fails evaluation.

**slash** seizes collateral and sends it to a treasury address. Used when the business agent fails to deliver after locking collateral.

**get_deposit** queries the current status of a deposit (LOCKED, RELEASED, REFUNDED, or SLASHED).

## Deposit Types and Statuses

```python
class DepositType(IntEnum):
    FEE = 0
    COLLATERAL = 1
    PRINCIPAL = 2

class DepositStatus(IntEnum):
    LOCKED = 0
    RELEASED = 1
    REFUNDED = 2
    SLASHED = 3
```

## SettlementLayer ABC

`SettlementLayer` composes escrow operations into the seven operations the server needs:

```python
class SettlementLayer(ABC):
    async def lock_fee(self, job_id, amount, currency, payer_addr, payee_addr, payment_payload=None) -> LockResult
    async def release_fee(self, job_id) -> SettleActionResult
    async def refund_fee(self, job_id) -> SettleActionResult
    async def lock_collateral(self, job_id, amount, currency, payer_addr, payment_payload=None) -> LockResult
    async def slash_collateral(self, job_id, treasury) -> SettleActionResult
    async def unlock_collateral(self, job_id) -> SettleActionResult
    async def release_principal(self, job_id, amount, currency, destination, payment_payload=None) -> SettleActionResult
```

The optional `payment_payload` parameter allows live implementations to include rail-specific transfer data (e.g., an x402 payment authorization). Mock implementations ignore it.

Note that `unlock_collateral` and `slash_collateral` are called automatically by the server during fee settlement. When the fee is settled with `release` (pass verdict), the server calls `unlock_collateral` to return funds to the business agent. When settled with `refund` (fail verdict), the server calls `slash_collateral` to seize funds to a treasury. No client action is required for collateral resolution.

## Result Types

```python
@dataclass
class LockResult:
    x402_tx: Optional[str]   # Payment rail transaction (if any)
    escrow_tx: str            # Escrow record transaction
    ref: str                  # Reference for tracking (e.g., "lock:job-123")

@dataclass
class SettleActionResult:
    tx_hash: str              # Settlement transaction hash
    ref: str                  # Reference (e.g., "settle:job-123:release")
```

## MockEscrowClient

The mock implementation stores deposits in an in-memory dict keyed by `"{job_id}:{deposit_type.name}"`. It enforces basic invariants (no double deposits, can only release/refund LOCKED deposits) and returns deterministic references for testing.

## MockSettlementLayer

The mock settlement layer composes `MockEscrowClient` and skips payment rail transfers. It produces deterministic `lock_ref`, `settlement_ref`, `collateral_ref`, and `transfer_ref` values that tests can assert against.

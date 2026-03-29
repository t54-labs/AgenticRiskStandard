# Abstract Settlement Interface

The settlement abstractions live in `src/abstract_ars/vaults.py` and `src/abstract_ars/settlement.py`. They define the contract that any concrete implementation must fulfill.

## Vault ABCs

Two separate vault abstractions handle the two types of conditional fund-holding. All methods are async.

### FeeEscrow

Holds fee funds in trust. Released to the payee (merchant) on pass, refunded to the payer (requestor) on fail.

```python
class FeeEscrow(ABC):
    async def lock(self, job_id, payer, payee, amount) -> str
    async def release(self, job_id) -> str
    async def refund(self, job_id) -> str
    async def get_status(self, job_id) -> Optional[DepositInfo]
```

### CollateralVault

Holds a delivery guarantee bond from the merchant. Returned on successful delivery, slashed to the harmed party (requestor) on failure.

```python
class CollateralVault(ABC):
    async def lock(self, job_id, payer, amount) -> str
    async def unlock(self, job_id) -> str
    async def slash(self, job_id, recipient) -> str
    async def get_status(self, job_id) -> Optional[DepositInfo]
```

Note that collateral `slash` sends funds to `recipient` — the requestor (the harmed party who didn't receive goods), not a generic treasury.

## Deposit Status

```python
class DepositStatus(IntEnum):
    LOCKED = 0
    RELEASED = 1
    REFUNDED = 2
    SLASHED = 3
```

## SettlementLayer ABC

`SettlementLayer` composes vault operations plus premium and principal transfers into the eight operations the server needs:

```python
class SettlementLayer(ABC):
    # Fee escrow
    async def lock_fee(self, job_id, amount, currency, payer_addr, payee_addr, payment_payload=None) -> LockResult
    async def release_fee(self, job_id) -> SettleActionResult
    async def refund_fee(self, job_id) -> SettleActionResult
    # Collateral vault
    async def lock_collateral(self, job_id, amount, currency, payer_addr, payment_payload=None) -> LockResult
    async def slash_collateral(self, job_id, recipient) -> SettleActionResult
    async def unlock_collateral(self, job_id) -> SettleActionResult
    # Premium (direct transfer from requestor to underwriter)
    async def pay_premium(self, job_id, amount, currency, payer_addr, payee_addr) -> SettleActionResult
    # Principal (direct transfer, not escrowed)
    async def release_principal(self, job_id, amount, currency, destination, payment_payload=None) -> SettleActionResult
```

The optional `payment_payload` parameter allows live implementations to include rail-specific transfer data (e.g., an x402 payment authorization). Mock implementations ignore it.

**Automatic collateral handling:** `unlock_collateral` and `slash_collateral` are called automatically by the server during fee settlement. When the fee is settled with `release` (pass verdict), the server calls `unlock_collateral` to return funds to the merchant. When settled with `refund` (fail verdict), the server calls `slash_collateral` to send funds to the requestor. No client action is required for collateral resolution.

**Premium** is a direct transfer from the requestor to the underwriter. It does not go through a vault — there is no hold period or conditional release.

**Principal** is a direct transfer to the destination account. It does not go through a vault — once conditions are met (coverage satisfied or override accepted), the funds are transferred immediately.

## Result Types

```python
@dataclass
class LockResult:
    escrow_tx: str            # Escrow record transaction
    ref: str                  # Reference for tracking (e.g., "lock:job-123")

@dataclass
class SettleActionResult:
    tx_hash: str              # Settlement transaction hash
    ref: str                  # Reference (e.g., "settle:job-123:release")
```

## Mock Implementations

`MockFeeEscrow` and `MockCollateralVault` store deposits in in-memory dicts keyed by job ID. They enforce basic invariants (no double deposits, can only release/refund LOCKED deposits) and return deterministic references for testing.

`MockSettlementLayer` composes `MockFeeEscrow` + `MockCollateralVault` and skips payment rail transfers. It produces deterministic `lock_ref`, `settlement_ref`, `collateral_ref`, `premium_ref`, and `transfer_ref` values that tests can assert against.

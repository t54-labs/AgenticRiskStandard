# ARSEscrow Smart Contract

ARSEscrow.sol is a Solidity smart contract that provides on-chain escrow for ARS jobs. It holds USDC deposits conditionally and releases, refunds, or slashes them based on protocol outcomes.

## Why a Contract

The x402 payment rail can transfer USDC between wallets, but it cannot hold funds conditionally. It cannot say "hold this USDC and release it to the merchant only if the evaluator says pass." That conditional logic requires a smart contract that sits between the payer and payee, holding funds until the protocol determines the outcome.

## Contract Functions

**recordDeposit(jobId, type, payer, payee, amount)** tags a deposit after x402 has transferred USDC into the contract. The deposit is keyed by `(jobId, type)` where type is FEE (0), COLLATERAL (1), or PRINCIPAL (2). A job can have up to three deposits: one of each type.

**release(jobId, type)** sends the deposited USDC to the payee. Used when a deliverable passes evaluation (for fee deposits) or when principal becomes releasable.

**refund(jobId, type)** returns the deposited USDC to the payer. Used when a deliverable fails evaluation or when collateral is unlocked after successful delivery.

**slash(jobId, recipient)** seizes collateral and sends it to the recipient (typically the requestor, the harmed party). Used when the business agent fails to deliver after posting collateral. Only applies to COLLATERAL deposits.

**getDeposit(jobId, type)** is a read-only query that returns the current status of a deposit (payer, payee, amount, status).

## Deposit Lifecycle

```
[USDC transferred via x402] → recordDeposit → LOCKED
                                                 ↓
                                    release → RELEASED (to payee)
                                    refund  → REFUNDED (to payer)
                                    slash   → SLASHED  (to recipient)
```

Each deposit can only transition once from LOCKED. Attempting to release an already-released deposit will revert.

## Operator Role

The contract uses an OPERATOR_ROLE for access control. Only the operator (the ARS server's signing key) can call `recordDeposit`, `release`, `refund`, and `slash`. This prevents unauthorized parties from manipulating deposits.

## LiveFeeEscrow and LiveCollateralVault

The Python interface to the contract is split into `LiveFeeEscrow` and `LiveCollateralVault` in `src/ap2/server/vaults.py`. Both extend the abstract ABCs from `abstract_ars/vaults.py` and share a common `_LiveEscrowBase` for web3.py setup:

```python
from ap2.server.vaults import LiveFeeEscrow, LiveCollateralVault

contract_args = dict(
    rpc_url="https://mainnet.base.org",
    contract_address="<deployed-address>",
    abi=abi,
    operator_key="<operator-private-key>",
)
fee_escrow = LiveFeeEscrow(**contract_args)
collateral_vault = LiveCollateralVault(**contract_args)
```

`LiveFeeEscrow` maps `lock/release/refund` to the contract's `recordDeposit/release/refund` with `DepositType.FEE`. `LiveCollateralVault` maps `lock/unlock/slash` to the same contract functions with `DepositType.COLLATERAL`.

The client encodes job IDs as `keccak256(job_id_string)` for the contract's bytes32 parameter. All methods are async (though the underlying web3 calls are synchronous, wrapped for API consistency).

## Supported Chains

The contract can be deployed on any EVM-compatible chain. The reference deployment targets Base (Coinbase L2) for low gas fees and fast finality. Base Sepolia is used for testing.

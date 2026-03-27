// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

import "@openzeppelin/contracts/token/ERC20/IERC20.sol";
import "@openzeppelin/contracts/access/AccessControl.sol";

/**
 * @title ARSEscrow
 * @notice Holds USDC for ARS fee escrow, collateral, and principal deposits.
 *         x402 transfers USDC *into* this contract; authorised operators then
 *         release, refund, or slash based on off-chain ARS state transitions.
 */
contract ARSEscrow is AccessControl {
    bytes32 public constant OPERATOR_ROLE = keccak256("OPERATOR_ROLE");

    enum DepositType { FEE, COLLATERAL, PRINCIPAL }
    enum DepositStatus { LOCKED, RELEASED, REFUNDED, SLASHED }

    struct Deposit {
        bytes32 jobId;
        address payer;
        address payee;
        uint256 amount;
        DepositType depositType;
        DepositStatus status;
    }

    IERC20 public immutable usdc;
    mapping(bytes32 => Deposit) public deposits; // keccak256(jobId, depositType) => Deposit

    event Deposited(bytes32 indexed jobId, DepositType depositType, uint256 amount, address payer, address payee);
    event Released(bytes32 indexed jobId, DepositType depositType, uint256 amount, address payee);
    event Refunded(bytes32 indexed jobId, DepositType depositType, uint256 amount, address payer);
    event Slashed(bytes32 indexed jobId, DepositType depositType, uint256 amount, address treasury);

    constructor(address _usdc, address _admin) {
        usdc = IERC20(_usdc);
        _grantRole(DEFAULT_ADMIN_ROLE, _admin);
        _grantRole(OPERATOR_ROLE, _admin);
    }

    /// @notice Record a deposit after x402 has transferred USDC to this contract.
    function recordDeposit(
        bytes32 jobId,
        DepositType depositType,
        address payer,
        address payee,
        uint256 amount
    ) external onlyRole(OPERATOR_ROLE) {
        bytes32 key = keccak256(abi.encodePacked(jobId, depositType));
        require(deposits[key].amount == 0, "Already deposited");
        require(usdc.balanceOf(address(this)) >= amount, "Insufficient balance");
        deposits[key] = Deposit(jobId, payer, payee, amount, depositType, DepositStatus.LOCKED);
        emit Deposited(jobId, depositType, amount, payer, payee);
    }

    /// @notice Release locked funds to the payee.
    function release(bytes32 jobId, DepositType depositType) external onlyRole(OPERATOR_ROLE) {
        bytes32 key = keccak256(abi.encodePacked(jobId, depositType));
        Deposit storage d = deposits[key];
        require(d.status == DepositStatus.LOCKED, "Not locked");
        d.status = DepositStatus.RELEASED;
        require(usdc.transfer(d.payee, d.amount), "Transfer failed");
        emit Released(jobId, depositType, d.amount, d.payee);
    }

    /// @notice Refund locked funds to the payer.
    function refund(bytes32 jobId, DepositType depositType) external onlyRole(OPERATOR_ROLE) {
        bytes32 key = keccak256(abi.encodePacked(jobId, depositType));
        Deposit storage d = deposits[key];
        require(d.status == DepositStatus.LOCKED, "Not locked");
        d.status = DepositStatus.REFUNDED;
        require(usdc.transfer(d.payer, d.amount), "Transfer failed");
        emit Refunded(jobId, depositType, d.amount, d.payer);
    }

    /// @notice Slash collateral to a protocol treasury.
    function slash(bytes32 jobId, address treasury) external onlyRole(OPERATOR_ROLE) {
        bytes32 key = keccak256(abi.encodePacked(jobId, DepositType.COLLATERAL));
        Deposit storage d = deposits[key];
        require(d.status == DepositStatus.LOCKED, "Not locked");
        d.status = DepositStatus.SLASHED;
        require(usdc.transfer(treasury, d.amount), "Transfer failed");
        emit Slashed(jobId, DepositType.COLLATERAL, d.amount, treasury);
    }

    /// @notice Query deposit status.
    function getDeposit(bytes32 jobId, DepositType depositType) external view returns (Deposit memory) {
        return deposits[keccak256(abi.encodePacked(jobId, depositType))];
    }
}

"""
Transfer USDC.e and native USDC from old Polymarket proxy to new Gnosis Safe.

Usage:
    conda activate tflow
    python src/scripts/transfer_proxy_to_safe.py <GNOSIS_SAFE_ADDRESS>

    # Dry-run first (default):
    python src/scripts/transfer_proxy_to_safe.py 0xYourGnosisSafeAddress

    # Execute for real:
    python src/scripts/transfer_proxy_to_safe.py 0xYourGnosisSafeAddress --send
"""

import sys
import os
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from dotenv import load_dotenv
load_dotenv()

from web3 import Web3
from web3.middleware import geth_poa_middleware

# ---------------------------------------------------------------------------
# Addresses
# ---------------------------------------------------------------------------
FACTORY = "0xaB45c5A4B0c941a2F231C04C3f49182e1A254052"
OLD_PROXY = "0xCFf8CF2403De4d9e2D739B248b91599071Ba9E0B"
USDC_E = "0x2791Bca1f2de4661ED88A30C99A7a9449Aa84174"
NATIVE_USDC = "0x3c499c542cEF5E3811e1192ce70d8cC03d5c3359"

# ERC-20 ABI (balanceOf + transfer)
ERC20_ABI = [
    {"inputs": [{"name": "account", "type": "address"}], "name": "balanceOf",
     "outputs": [{"type": "uint256"}], "stateMutability": "view", "type": "function"},
    {"inputs": [{"name": "to", "type": "address"}, {"name": "amount", "type": "uint256"}],
     "name": "transfer", "outputs": [{"type": "bool"}], "stateMutability": "nonpayable", "type": "function"},
    {"inputs": [], "name": "decimals",
     "outputs": [{"type": "uint8"}], "stateMutability": "view", "type": "function"},
]

# Factory ABI — proxy() function
# Tuple: (uint8 operation, address to, uint256 value, bytes data)
# Polymarket convention: operation=1 means CALL (not standard Gnosis Safe order)
FACTORY_ABI = [
    {
        "inputs": [
            {
                "components": [
                    {"name": "operation", "type": "uint8"},
                    {"name": "to", "type": "address"},
                    {"name": "value", "type": "uint256"},
                    {"name": "data", "type": "bytes"},
                ],
                "name": "_calls",
                "type": "tuple[]",
            }
        ],
        "name": "proxy",
        "outputs": [],
        "stateMutability": "nonpayable",
        "type": "function",
    }
]

# Operation constants (Polymarket convention)
OP_CALL = 1


def main():
    if len(sys.argv) < 2:
        print("Usage: python transfer_proxy_to_safe.py <GNOSIS_SAFE_ADDRESS> [--send]")
        sys.exit(1)

    gnosis_safe = sys.argv[1]
    do_send = "--send" in sys.argv

    private_key = os.getenv("POLYMARKET_PRIVATE_KEY")
    if not private_key:
        print("ERROR: POLYMARKET_PRIVATE_KEY not set in .env")
        sys.exit(1)

    # Connect to Polygon
    w3 = Web3(Web3.HTTPProvider("https://polygon.drpc.org"))
    w3.middleware_onion.inject(geth_poa_middleware, layer=0)

    if not w3.is_connected():
        print("ERROR: Cannot connect to Polygon RPC")
        sys.exit(1)

    from eth_account import Account
    eoa = Account.from_key(private_key)
    print(f"EOA:         {eoa.address}")
    print(f"Old Proxy:   {OLD_PROXY}")
    print(f"Gnosis Safe: {gnosis_safe}")
    print()

    gnosis_safe = w3.to_checksum_address(gnosis_safe)

    # Check balances
    usdc_e_contract = w3.eth.contract(address=w3.to_checksum_address(USDC_E), abi=ERC20_ABI)
    native_usdc_contract = w3.eth.contract(address=w3.to_checksum_address(NATIVE_USDC), abi=ERC20_ABI)

    bal_e = usdc_e_contract.functions.balanceOf(w3.to_checksum_address(OLD_PROXY)).call()
    bal_u = native_usdc_contract.functions.balanceOf(w3.to_checksum_address(OLD_PROXY)).call()
    pol_bal = w3.eth.get_balance(w3.to_checksum_address(eoa.address))

    print(f"Proxy USDC.e balance: {bal_e / 1e6:.6f} ({bal_e} raw)")
    print(f"Proxy USDC balance:   {bal_u / 1e6:.6f} ({bal_u} raw)")
    print(f"EOA POL balance:      {pol_bal / 1e18:.6f}")
    print()

    if bal_e == 0 and bal_u == 0:
        print("Nothing to transfer — both balances are 0")
        sys.exit(0)

    # Build transfer calldata for each token
    # transfer(address,uint256) selector = 0xa9059cbb
    transfer_selector = bytes.fromhex("a9059cbb")
    calls = []

    if bal_e > 0:
        transfer_data_e = transfer_selector + w3.codec.encode(
            ["address", "uint256"], [gnosis_safe, bal_e]
        )
        calls.append((OP_CALL, w3.to_checksum_address(USDC_E), 0, transfer_data_e))
        print(f"  Transfer {bal_e / 1e6:.6f} USDC.e -> {gnosis_safe}")

    if bal_u > 0:
        transfer_data_u = transfer_selector + w3.codec.encode(
            ["address", "uint256"], [gnosis_safe, bal_u]
        )
        calls.append((OP_CALL, w3.to_checksum_address(NATIVE_USDC), 0, transfer_data_u))
        print(f"  Transfer {bal_u / 1e6:.6f} USDC   -> {gnosis_safe}")

    print(f"\nTotal calls: {len(calls)}")

    factory = w3.eth.contract(address=w3.to_checksum_address(FACTORY), abi=FACTORY_ABI)

    if not do_send:
        print("\n*** DRY RUN — add --send to execute ***")
        try:
            gas_est = factory.functions.proxy(calls).estimate_gas({"from": eoa.address})
            print(f"Gas estimate: {gas_est}")
            print("Dry run PASSED — call would succeed on-chain")
        except Exception as e:
            print(f"Dry run FAILED — estimate_gas error: {e}")
        return

    # Build and send transaction
    nonce = w3.eth.get_transaction_count(eoa.address)
    tx = factory.functions.proxy(calls).build_transaction({
        "from": eoa.address,
        "nonce": nonce,
        "gas": 200000,
        "maxFeePerGas": w3.to_wei(50, "gwei"),
        "maxPriorityFeePerGas": w3.to_wei(30, "gwei"),
    })

    signed = eoa.sign_transaction(tx)
    tx_hash = w3.eth.send_raw_transaction(signed.raw_transaction)
    print(f"\nTransaction sent: {tx_hash.hex()}")
    print(f"Polygonscan: https://polygonscan.com/tx/{tx_hash.hex()}")

    print("Waiting for confirmation...")
    receipt = w3.eth.wait_for_transaction_receipt(tx_hash, timeout=120)
    print(f"Status: {'SUCCESS' if receipt['status'] == 1 else 'FAILED'}")
    print(f"Gas used: {receipt['gasUsed']}")

    if receipt["status"] == 1:
        # Verify destination balances
        new_bal_e = usdc_e_contract.functions.balanceOf(gnosis_safe).call()
        new_bal_u = native_usdc_contract.functions.balanceOf(gnosis_safe).call()
        print(f"\nGnosis Safe USDC.e: {new_bal_e / 1e6:.6f}")
        print(f"Gnosis Safe USDC:   {new_bal_u / 1e6:.6f}")
        print(f"Total: ${(new_bal_e + new_bal_u) / 1e6:.2f}")


if __name__ == "__main__":
    main()

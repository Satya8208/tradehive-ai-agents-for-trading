# 🌙 TradeHive's Extended Exchange Integration

Complete guide to using Extended Exchange (X10) with TradeHive's trading system.

---

## 📋 Table of Contents

1. [Overview](#overview)
2. [What is Extended Exchange?](#what-is-extended-exchange)
3. [Setup & Configuration](#setup--configuration)
4. [Environment Variables](#environment-variables)
5. [Available Functions](#available-functions)
6. [Using with Trading Agent](#using-with-trading-agent)
7. [Testing Your Setup](#testing-your-setup)
8. [Key Differences from Other Exchanges](#key-differences-from-other-exchanges)
9. [Troubleshooting](#troubleshooting)

---

## Overview

Extended Exchange (X10) is a decentralized perpetual futures exchange built on StarkNet. This integration allows you to trade crypto perpetual futures with up to 20x leverage directly from the TradeHive trading system.

**Files:**
- **`src/nice_funcs_extended.py`** - Extended Exchange trading functions (850+ lines)
- **`src/scripts/test_extended.py`** - Comprehensive test script
- **`src/scripts/debug_extended_position.py`** - Debug utility for positions

---

## What is Extended Exchange?

Extended Exchange (X10) is a StarkNet-based perpetual futures DEX offering:

- **Leverage Trading**: Up to 20x leverage on BTC, ETH, SOL and more
- **StarkNet Security**: Built on StarkNet L2 for secure, decentralized trading
- **Low Fees**: Competitive maker/taker fees
- **API Access**: Full programmatic trading via Python SDK

**Official Links:**
- Website: https://extended.exchange
- API Docs: https://api.starknet.extended.exchange
- SDK: https://github.com/x10xchange/python_sdk

---

## Setup & Configuration

### Step 1: Install Extended Exchange SDK

The Extended integration requires the `x10-perpetual-sdk` package:

```bash
# Make sure you're in the tflow conda environment
conda activate tflow

# Install Extended Exchange SDK
pip install x10-perpetual-sdk

# Update requirements.txt
pip freeze > requirements.txt
```

### Step 2: Get Your API Credentials

1. **Sign up** at https://extended.exchange
2. **Create an account** and complete KYC if required
3. **Generate API credentials**:
   - Go to Account Settings → API Keys
   - Create a new API key with trading permissions
   - Save your credentials securely:
     - API Key
     - Private Key (StarkNet wallet key)
     - Public Key (StarkNet wallet address)
     - Vault ID (your trading vault identifier)

⚠️ **Important**: Keep your private key secure! Never share it or commit it to git.

### Step 3: Configure Environment Variables

Add your Extended credentials to `.env`:

```bash
# Extended Exchange (X10) Configuration
X10_API_KEY=your_api_key_here
X10_PRIVATE_KEY=your_starknet_private_key_here
X10_PUBLIC_KEY=your_starknet_public_key_here
X10_VAULT_ID=110198
```

**Where to find these:**
- `X10_API_KEY`: Generated in Extended dashboard
- `X10_PRIVATE_KEY`: Your StarkNet wallet private key
- `X10_PUBLIC_KEY`: Your StarkNet wallet public address
- `X10_VAULT_ID`: Displayed in your account dashboard

---

## Environment Variables

Extended Exchange uses 4 environment variables for authentication:

| Variable | Description | Example | Required |
|----------|-------------|---------|----------|
| `X10_API_KEY` | Extended API authentication key | `ext_abc123...` | Yes |
| `X10_PRIVATE_KEY` | StarkNet wallet private key | `0x123abc...` | Yes |
| `X10_PUBLIC_KEY` | StarkNet wallet public address | `0x456def...` | Yes |
| `X10_VAULT_ID` | Your trading vault ID | `110198` | Yes |

Add these to your `.env` file (use `.env_example` as a template).

---

## Available Functions

All functions in `nice_funcs_extended.py` are compatible with the trading_agent's function signatures.

### Trading Functions

#### Market Orders
```python
from src import nice_funcs_extended as extended

# Market buy $100 of BTC with 10x leverage
extended.market_buy("BTC", usd_amount=100, leverage=10)

# Market sell $100 of BTC
extended.market_sell("BTC", usd_amount=100, leverage=10)

# Open long position
extended.open_long("BTC", usd_amount=500, leverage=20)

# Open short position
extended.open_short("ETH", usd_amount=500, leverage=15)
```

#### Limit Orders
```python
# Buy limit order at specific price
extended.limit_buy("BTC", usd_amount=100, limit_price=95000, leverage=10)

# Sell limit order at specific price
extended.limit_sell("BTC", usd_amount=100, limit_price=98000, leverage=10)
```

#### Position Management
```python
# Get current position
position = extended.get_position("BTC")
if position:
    print(f"Size: {position['position_amount']}")
    print(f"Entry: ${position['entry_price']:,.2f}")
    print(f"PnL: {position['pnl_percentage']:.2f}%")
    print(f"Direction: {'LONG' if position['is_long'] else 'SHORT'}")

# Close position (market order)
extended.close_position("BTC")

# Chunk kill (close with maker orders, loops until fully closed)
extended.chunk_kill("BTC")
```

#### Order Management
```python
# Get open orders
orders = extended.get_open_orders("BTC")
for order in orders:
    print(f"{order['side']} {order['quantity']} @ ${order['price']}")

# Cancel all orders
extended.cancel_all_orders("BTC")
```

### Account & Market Data Functions

```python
# Get account balance
balance = extended.get_account_balance()
print(f"Equity: ${balance['equity']:,.2f}")

# Get ticker data (bid, ask, mark price)
ticker = extended.get_ticker("BTC")
print(f"Bid: ${ticker['bid']:,.2f}")
print(f"Ask: ${ticker['ask']:,.2f}")
print(f"Mark: ${ticker['mark_price']:,.2f}")

# Get current price
price = extended.get_current_price("BTC")
print(f"Current BTC price: ${price:,.2f}")
```

### Symbol Format

🌙 **TradeHive Note**: Extended Exchange uses `BTC-USD` format internally, but all functions auto-convert!

```python
# All of these work the same:
extended.get_position("BTC")       # Auto-converts to BTC-USD
extended.get_position("BTC-USD")   # Direct format
extended.market_buy("ETH", 100)    # Auto-converts to ETH-USD
```

The `format_symbol_for_extended()` function handles conversion automatically.

---

## Using with Trading Agent

The trading_agent.py supports Extended Exchange through the exchange selector at the top of the file.

### Option 1: Set Extended as Default Exchange

Edit `src/agents/trading_agent.py`:

```python
# Exchange Configuration
EXCHANGE = "extended"  # Options: "hyperliquid", "birdeye", "extended"
```

### Option 2: Import Functions Directly

```python
from src import nice_funcs_extended as extended

# Use Extended functions directly
position = extended.get_position("BTC")
extended.market_buy("BTC", 100, leverage=15)
```

### Unified Trading Agent Interface

The trading agent uses exchange-agnostic code:

```python
# In trading_agent.py, this code works with ALL exchanges:
from src import config

if config.EXCHANGE == "extended":
    from src import nice_funcs_extended as nf
elif config.EXCHANGE == "hyperliquid":
    from src import nice_funcs_hl as nf
# ... etc

# Now use unified interface:
position = nf.get_position(symbol)
nf.market_buy(symbol, usd_amount, leverage=20)
nf.close_position(symbol)
```

---

## Testing Your Setup

Extended comes with a comprehensive test script that verifies all functionality.

### Run the Test Script

```bash
conda activate tflow
python src/scripts/test_extended.py
```

### What the Test Does

The test script performs an 8-step verification:

1. ✅ **Check Position & Balance** - Verifies API connection
2. ✅ **Place Limit Orders** - Tests order placement (won't fill)
3. ✅ **View Open Orders** - Confirms orders appear
4. ✅ **Cancel Orders** - Tests order cancellation
5. ✅ **Market Buy $10** - Opens small test position
6. ✅ **Verify Position** - Confirms position opened
7. ✅ **Test Leverage** - Opens short with 5x leverage
8. ✅ **Close Position** - Closes all positions

**Expected Output:**
```
🌙 TradeHive's Extended Exchange Test Starting! 🚀

================================================================
  📊 STEP 1: Check Initial Position & Balance
================================================================

💰 Getting account balance...
✅ Account Equity: $1,234.56 USD

📈 Checking BTC position...
✅ No open position for BTC

[... continues through all 8 steps ...]

✨ TradeHive's Extended Exchange Test Complete! ✨

All functionality tested:
  ✅ Get position
  ✅ Get balance
  ✅ Get ticker (bid/ask)
  ✅ Place limit orders
  ✅ Get open orders
  ✅ Cancel orders
  ✅ Market buy
  ✅ Close position

🌙 Extended Exchange is fully functional! 🚀
```

### Debug Position Issues

If you're having position-related issues, use the debug script:

```bash
python src/scripts/debug_extended_position.py
```

This script shows detailed position information including:
- Raw API response
- All position fields
- Position direction detection
- PnL calculations

---

## Key Differences from Other Exchanges

### Extended vs Hyperliquid

| Feature | Extended Exchange | Hyperliquid |
|---------|------------------|-------------|
| **Blockchain** | StarkNet L2 | Custom L1 |
| **Symbol Format** | `BTC-USD` | `BTC` |
| **Price Format** | Integer prices | Float prices |
| **Leverage** | Up to 20x | Up to 50x |
| **Order Types** | Limit (post-only), Market | Limit, Market, Stop |
| **Position Side** | Explicit `side` field | Inferred from size |

### Extended vs BirdEye (Solana)

| Feature | Extended Exchange | BirdEye |
|---------|------------------|---------|
| **Asset Type** | Perpetual futures | Spot tokens |
| **Blockchain** | StarkNet | Solana |
| **Leverage** | Yes (up to 20x) | No (spot only) |
| **Markets** | BTC, ETH, SOL, majors | All Solana tokens |
| **Use Case** | Leveraged trading | Token analytics & spot |

### Important Implementation Notes

1. **Integer Prices**: Extended requires integer prices for BTC-USD (rounds automatically)
2. **Position Direction**: Uses explicit `side` field ('LONG' or 'SHORT') instead of size sign
3. **Async Operations**: Uses async/await with event loop (handled internally)
4. **StarkNet Wallet**: Requires StarkNet-compatible wallet and keys
5. **Maker-First**: Prefers post-only orders for better fees

---

## Troubleshooting

### Common Issues

#### 1. SDK Import Error
```
ImportError: No module named 'x10'
```
**Solution**: Install the SDK
```bash
pip install x10-perpetual-sdk
```

#### 2. Authentication Failed
```
ValueError: Extended Exchange credentials not found in environment!
```
**Solution**: Check your `.env` file has all 4 credentials:
- X10_API_KEY
- X10_PRIVATE_KEY
- X10_PUBLIC_KEY
- X10_VAULT_ID

#### 3. Position Direction Wrong
```python
# Position shows negative size when it should be positive (or vice versa)
```
**Solution**: Extended uses the `side` field for direction, not size sign. The integration handles this automatically - if you see issues, check `get_position()` in nice_funcs_extended.py line 191.

#### 4. Invalid Quantity Error
```
❌ Invalid quantity calculated: 0
```
**Solution**: Your USD amount might be too small for the asset. Minimum sizes:
- BTC: 0.001 BTC (~$98)
- ETH: 0.0001 ETH (~$3)
- SOL: 0.01 SOL (~$2)

#### 5. Order Placement Fails
```
REST API Error: 400 Bad Request
```
**Solution**:
- Check your leverage is set correctly (1-20x)
- Verify you have sufficient balance
- Ensure symbol format is correct (use "BTC" not "BTCUSD")

### Getting Help

If you encounter issues:

1. **Run the test script**: `python src/scripts/test_extended.py`
2. **Use debug script**: `python src/scripts/debug_extended_position.py`
3. **Check the logs**: Look for colored terminal output
4. **Verify credentials**: Ensure all 4 Extended env vars are set
5. **Join Discord**: Get help from the TradeHive community

---

## Configuration Options

### Leverage Settings

Default leverage is 20x (set in `nice_funcs_extended.py:66`):

```python
DEFAULT_LEVERAGE = 20  # Default leverage for Extended Exchange
```

Change per-trade:
```python
extended.market_buy("BTC", 100, leverage=10)  # Use 10x instead
```

### Testnet vs Mainnet

By default, Extended uses **mainnet**. To use testnet:

Edit `nice_funcs_extended.py:67`:
```python
USE_TESTNET = True  # Set to True for testnet
```

⚠️ **Warning**: Testnet funds are not real! Only use testnet for development.

---

## Example: Complete Trading Flow

Here's a complete example of using Extended Exchange:

```python
"""
🌙 TradeHive's Extended Trading Example
"""
from src import nice_funcs_extended as extended
from termcolor import cprint

# 1. Check balance
balance = extended.get_account_balance()
cprint(f"💰 Balance: ${balance['equity']:,.2f}", "green")

# 2. Check if we have a position
position = extended.get_position("BTC")
if position:
    cprint(f"📊 Current Position:", "yellow")
    cprint(f"   Size: {position['position_amount']}", "white")
    cprint(f"   Entry: ${position['entry_price']:,.2f}", "white")
    cprint(f"   PnL: {position['pnl_percentage']:.2f}%", "white")
else:
    cprint(f"📊 No position", "yellow")

# 3. Get current market price
ticker = extended.get_ticker("BTC")
cprint(f"📈 Market: Bid ${ticker['bid']:,.0f} | Ask ${ticker['ask']:,.0f}", "cyan")

# 4. Open a long position with 15x leverage
if not position:
    cprint(f"🚀 Opening $100 BTC long @ 15x leverage", "green")
    extended.open_long("BTC", usd_amount=100, leverage=15)

    # Wait a moment for position to settle
    import time
    time.sleep(2)

    # Verify position opened
    new_position = extended.get_position("BTC")
    if new_position:
        cprint(f"✅ Position opened!", "green")
        cprint(f"   Entry: ${new_position['entry_price']:,.2f}", "white")
        cprint(f"   Size: {new_position['position_amount']}", "white")

# 5. Place a take-profit limit order
if position:
    tp_price = position['entry_price'] * 1.02  # 2% profit target
    cprint(f"🎯 Setting take-profit at ${tp_price:,.0f}", "cyan")
    extended.limit_sell("BTC", usd_amount=100, limit_price=int(tp_price))

# 6. Close position when ready
# extended.chunk_kill("BTC")  # Close with maker orders
# extended.close_position("BTC")  # Close with market order

cprint(f"\n🌙 TradeHive's trading flow complete!", "green")
```

---

## Additional Resources

- **Extended Exchange Docs**: https://docs.extended.exchange
- **Python SDK**: https://github.com/x10xchange/python_sdk
- **StarkNet Docs**: https://docs.starknet.io
- **TradeHive YouTube**: Weekly trading system updates
- **Discord**: Join for community support

---

## Summary

Extended Exchange integration provides:

✅ **Full Trading API**: Market, limit, position management
✅ **High Leverage**: Up to 20x on major pairs
✅ **StarkNet Security**: Decentralized L2 infrastructure
✅ **Trading Agent Compatible**: Works seamlessly with trading_agent.py
✅ **Thoroughly Tested**: Comprehensive test suite included
✅ **Auto Symbol Conversion**: Use simple "BTC" format everywhere

**Quick Start:**
1. `pip install x10-perpetual-sdk`
2. Add credentials to `.env`
3. `python src/scripts/test_extended.py`
4. Set `EXCHANGE = "extended"` in trading_agent.py
5. Start trading! 🚀

---

**Built with 🌙 by TradeHive**

*"Never over-engineer, always ship real trading systems."*

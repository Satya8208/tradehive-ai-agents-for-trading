"""
🌙 TradeHive's Market Data Downloader
Downloads OHLCV data for multiple assets and timeframes using CCXT

Built with love by TradeHive 🚀

FEATURES:
- Downloads crypto data from Binance (reliable, free, no API key needed)
- Multiple assets: BTC, ETH, SOL, MATIC, AVAX, LINK, UNI, DOGE, ARB, OP
- Multiple timeframes: 5m, 15m, 1h, 4h, 1d
- 2 years of historical data
- Saves to organized folder structure
- Progress tracking and error handling
- Skips already downloaded files

USAGE:
    python src/scripts/download_market_data.py

OUTPUT STRUCTURE:
    src/data/market_data/
        binance/
            BTCUSDT/
                BTC-USDT-5m.csv
                BTC-USDT-15m.csv
                BTC-USDT-1h.csv
                ...
            ETHUSDT/
                ETH-USDT-5m.csv
                ...
"""

import ccxt
import pandas as pd
from pathlib import Path
from datetime import datetime, timedelta
from termcolor import cprint
import time
import sys

# Configuration
EXCHANGE = 'binance'
ASSETS = [
    'BTC/USDT',
    'ETH/USDT',
    'SOL/USDT',
    'MATIC/USDT',
    'AVAX/USDT',
    'LINK/USDT',
    'UNI/USDT',
    'DOGE/USDT',
    'ARB/USDT',
    'OP/USDT'
]

TIMEFRAMES = ['5m', '15m', '1h', '4h', '1d']

# Download 2 years of data
DAYS_BACK = 730

# Output directory
OUTPUT_DIR = Path(__file__).parent.parent / 'data' / 'market_data' / EXCHANGE

# Rate limiting
RATE_LIMIT_DELAY = 0.5  # seconds between requests


def create_exchange():
    """Initialize CCXT exchange"""
    try:
        exchange = ccxt.binance({
            'enableRateLimit': True,
            'options': {'defaultType': 'spot'}
        })
        cprint(f"✅ Connected to {EXCHANGE.upper()}", "green")
        return exchange
    except Exception as e:
        cprint(f"❌ Failed to connect to exchange: {e}", "red")
        sys.exit(1)


def download_ohlcv(exchange, symbol, timeframe, days_back):
    """Download OHLCV data for a symbol and timeframe"""
    try:
        # Calculate start time
        end_time = datetime.now()
        start_time = end_time - timedelta(days=days_back)
        since = int(start_time.timestamp() * 1000)

        cprint(f"  Downloading {symbol} {timeframe}...", "cyan")

        # Fetch all candles
        all_candles = []
        current_since = since

        while True:
            candles = exchange.fetch_ohlcv(symbol, timeframe, since=current_since, limit=1000)

            if not candles:
                break

            all_candles.extend(candles)

            # Update since to last candle timestamp + 1
            current_since = candles[-1][0] + 1

            # If we've reached current time, stop
            if current_since >= int(end_time.timestamp() * 1000):
                break

            # Rate limiting
            time.sleep(RATE_LIMIT_DELAY)

        if not all_candles:
            cprint(f"  ⚠️  No data returned for {symbol} {timeframe}", "yellow")
            return None

        # Convert to DataFrame
        df = pd.DataFrame(all_candles, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
        df['datetime'] = pd.to_datetime(df['timestamp'], unit='ms')
        df = df[['datetime', 'open', 'high', 'low', 'close', 'volume']]

        cprint(f"  ✅ Downloaded {len(df)} candles from {df['datetime'].min()} to {df['datetime'].max()}", "green")

        return df

    except Exception as e:
        cprint(f"  ❌ Error downloading {symbol} {timeframe}: {e}", "red")
        return None


def save_dataframe(df, symbol, timeframe):
    """Save DataFrame to CSV file"""
    # Clean symbol for filename (remove /)
    clean_symbol = symbol.replace('/', '')

    # Create directory structure
    symbol_dir = OUTPUT_DIR / clean_symbol
    symbol_dir.mkdir(parents=True, exist_ok=True)

    # Create filename: BTC-USDT-1h.csv
    filename = f"{symbol.replace('/', '-')}-{timeframe}.csv"
    filepath = symbol_dir / filename

    # Save to CSV
    df.to_csv(filepath, index=False)
    cprint(f"  💾 Saved to {filepath}", "green")

    return filepath


def main():
    """Main download loop"""
    cprint("🌙 TradeHive's Market Data Downloader Starting...", "cyan", attrs=["bold"])
    cprint(f"Exchange: {EXCHANGE.upper()}", "white")
    cprint(f"Assets: {len(ASSETS)}", "white")
    cprint(f"Timeframes: {TIMEFRAMES}", "white")
    cprint(f"History: {DAYS_BACK} days", "white")
    cprint(f"Output: {OUTPUT_DIR}", "white")
    print()

    # Create exchange
    exchange = create_exchange()

    # Stats
    total_downloads = len(ASSETS) * len(TIMEFRAMES)
    completed = 0
    failed = 0
    skipped = 0

    # Download loop
    for symbol in ASSETS:
        cprint(f"\n{'='*60}", "cyan")
        cprint(f"📊 Processing {symbol}", "cyan", attrs=["bold"])
        cprint(f"{'='*60}", "cyan")

        for timeframe in TIMEFRAMES:
            # Check if file already exists
            clean_symbol = symbol.replace('/', '')
            filename = f"{symbol.replace('/', '-')}-{timeframe}.csv"
            filepath = OUTPUT_DIR / clean_symbol / filename

            if filepath.exists():
                cprint(f"  ⏭️  Skipping {symbol} {timeframe} (already exists)", "yellow")
                skipped += 1
                continue

            # Download data
            df = download_ohlcv(exchange, symbol, timeframe, DAYS_BACK)

            if df is not None and not df.empty:
                save_dataframe(df, symbol, timeframe)
                completed += 1
            else:
                failed += 1

            # Progress
            progress = completed + failed + skipped
            cprint(f"  📈 Progress: {progress}/{total_downloads} ({progress/total_downloads*100:.1f}%)", "white")

            # Rate limiting
            time.sleep(RATE_LIMIT_DELAY)

    # Final summary
    print()
    cprint("="*60, "cyan")
    cprint("📊 DOWNLOAD SUMMARY", "cyan", attrs=["bold"])
    cprint("="*60, "cyan")
    cprint(f"✅ Completed: {completed}", "green")
    cprint(f"⏭️  Skipped: {skipped}", "yellow")
    cprint(f"❌ Failed: {failed}", "red")
    cprint(f"📁 Total files: {completed + skipped}", "white")
    cprint(f"💾 Saved to: {OUTPUT_DIR}", "white")

    print()
    cprint("🎉 Download complete! Ready for backtesting!", "green", attrs=["bold"])


if __name__ == "__main__":
    main()

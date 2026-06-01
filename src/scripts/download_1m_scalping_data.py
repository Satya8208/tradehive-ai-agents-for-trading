"""
🌙 TradeHive's 1-Minute Scalping Data Downloader
Downloads 1m OHLCV data from Binance for scalping strategies

Built with love by TradeHive 🚀

USAGE:
    python src/scripts/download_1m_scalping_data.py

DOWNLOADS:
    - 9 assets: BTC, ETH, SOL, MATIC, AVAX, LINK, UNI, ARB, OP
    - 1-minute timeframe only
    - Last 30 days of data (~43,200 bars per asset)
    - Perfect for high-frequency scalping backtests

OUTPUT:
    src/data/market_data/binance/{ASSET}/{ASSET}-1m.csv
"""

import ccxt
import pandas as pd
from datetime import datetime, timedelta
from pathlib import Path
import time

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
    'ARB/USDT',
    'OP/USDT'
]
TIMEFRAME = '1m'
DAYS_BACK = 30  # 30 days for scalping (manageable file size)

# Output directory
PROJECT_ROOT = Path(__file__).parent.parent
OUTPUT_DIR = PROJECT_ROOT / 'data' / 'market_data' / EXCHANGE

def download_ohlcv(exchange, symbol, timeframe, days_back):
    """Download OHLCV data from exchange"""
    print(f"\n📥 Downloading {symbol} {timeframe} data...")

    # Calculate start time
    since = exchange.milliseconds() - (days_back * 24 * 60 * 60 * 1000)

    all_ohlcv = []

    try:
        while True:
            ohlcv = exchange.fetch_ohlcv(symbol, timeframe, since=since, limit=1000)

            if not ohlcv:
                break

            all_ohlcv.extend(ohlcv)

            # Update since to get next batch
            since = ohlcv[-1][0] + 1

            # Rate limiting
            time.sleep(exchange.rateLimit / 1000)

            # Check if we've reached current time
            if ohlcv[-1][0] >= exchange.milliseconds():
                break

        print(f"✅ Downloaded {len(all_ohlcv)} {timeframe} bars")
        return all_ohlcv

    except Exception as e:
        print(f"❌ Error downloading {symbol}: {e}")
        return None

def save_to_csv(ohlcv_data, output_path):
    """Convert OHLCV data to DataFrame and save as CSV"""
    if not ohlcv_data:
        print(f"⚠️ No data to save")
        return False

    # Convert to DataFrame
    df = pd.DataFrame(
        ohlcv_data,
        columns=['timestamp', 'open', 'high', 'low', 'close', 'volume']
    )

    # Convert timestamp to datetime
    df['datetime'] = pd.to_datetime(df['timestamp'], unit='ms')

    # Reorder columns
    df = df[['datetime', 'open', 'high', 'low', 'close', 'volume']]

    # Save to CSV
    output_path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(output_path, index=False)

    print(f"💾 Saved to: {output_path}")
    print(f"📊 Date range: {df['datetime'].min()} to {df['datetime'].max()}")

    return True

def main():
    """Main download process"""
    print("="*60)
    print("🌙 TRADEHIVE'S 1-MINUTE SCALPING DATA DOWNLOADER")
    print("="*60)
    print(f"\n📊 Downloading 1m data for {len(ASSETS)} assets")
    print(f"📅 Last {DAYS_BACK} days")
    print(f"🎯 For high-frequency scalping strategies\n")

    # Initialize exchange
    exchange = getattr(ccxt, EXCHANGE)({
        'enableRateLimit': True,
    })

    successful = 0
    failed = 0

    for symbol in ASSETS:
        # Create output path
        symbol_clean = symbol.replace('/', '')
        output_dir = OUTPUT_DIR / symbol_clean
        filename = f"{symbol.replace('/', '-')}-{TIMEFRAME}.csv"
        output_path = output_dir / filename

        # Download data
        ohlcv_data = download_ohlcv(exchange, symbol, TIMEFRAME, DAYS_BACK)

        # Save to CSV
        if ohlcv_data and save_to_csv(ohlcv_data, output_path):
            successful += 1
        else:
            failed += 1
            print(f"❌ Failed to save {symbol}")

        # Delay between assets to avoid rate limiting
        time.sleep(2)

    # Summary
    print("\n" + "="*60)
    print("📊 DOWNLOAD SUMMARY")
    print("="*60)
    print(f"✅ Successful: {successful}/{len(ASSETS)}")
    print(f"❌ Failed: {failed}/{len(ASSETS)}")
    print(f"📁 Output directory: {OUTPUT_DIR}")
    print("="*60)

    if successful > 0:
        print("\n🎉 Data ready for scalping backtests!")
        print("\nNext steps:")
        print("1. Copy BTC 1m data to RBI directory:")
        print(f"   cp {OUTPUT_DIR}/BTCUSDT/BTC-USDT-1m.csv {PROJECT_ROOT}/data/rbi/BTC-USD-1m.csv")
        print("\n2. Run Strategy Lab in Scalping Mode:")
        print("   python src/scripts/ai_strategy_lab.py")
        print("\n3. Generate scalping strategies and backtest!")

if __name__ == "__main__":
    main()

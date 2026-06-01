"""
🌙 TradeHive's EMA Crossover Scalper
Fast EMA(5) / Slow EMA(13) crossover strategy for scalping
Tight stops, quick entries/exits
"""

from backtesting import Strategy
import pandas_ta as ta

class EMA_Crossover_Scalper(Strategy):
    # Parameters
    fast_ema = 5
    slow_ema = 13
    stop_loss = 0.005  # 0.5%
    take_profit = 0.010  # 1.0%

    def init(self):
        # Calculate EMAs
        close = self.data.Close
        self.fast = self.I(ta.ema, close, length=self.fast_ema)
        self.slow = self.I(ta.ema, close, length=self.slow_ema)

    def next(self):
        price = self.data.Close[-1]

        # Entry: Fast EMA crosses above Slow EMA
        if not self.position:
            if self.fast[-1] > self.slow[-1] and self.fast[-2] <= self.slow[-2]:
                # Buy with tight stops
                self.buy(
                    sl=price * (1 - self.stop_loss),
                    tp=price * (1 + self.take_profit)
                )

        # Exit: Fast EMA crosses below Slow EMA
        else:
            if self.fast[-1] < self.slow[-1] and self.fast[-2] >= self.slow[-2]:
                self.position.close()


# ============= TRADEHIVE TESTING ZONE =============

if __name__ == "__main__":
    from backtesting import Backtest
    import pandas as pd

    print("\n🌙 TradeHive's EMA Crossover Scalper Test")
    print("=" * 60)

    # Load 1-minute data
    data = pd.read_csv('src/data/rbi/BTC-USD-15m.csv', index_col=0, parse_dates=True)
    print(f"📊 Testing on: {len(data)} bars")
    print(f"📅 Period: {data.index[0]} to {data.index[-1]}")

    # Run backtest
    bt = Backtest(data, EMA_Crossover_Scalper, cash=10000, commission=0.001)
    stats = bt.run()

    print("\n📈 Results:")
    print(f"  Return: {stats['Return [%]']:.2f}%")
    print(f"  Trades: {stats['# Trades']}")
    print(f"  Win Rate: {stats['Win Rate [%]']:.2f}%")
    print(f"  Max Drawdown: {stats['Max. Drawdown [%]']:.2f}%")
    print(f"  Sharpe: {stats['Sharpe Ratio']:.2f}")

    # Test multi-data validation
    print("\n🔄 Testing on all 46 datasets...")

    # Read this file's source code to pass to multi_data_tester
    with open(__file__, 'r') as f:
        strategy_code = f.read()

    from src.utils.multi_data_tester import test_on_all_data
    results = test_on_all_data(strategy_code, 'EMA_Crossover_Scalper', verbose=False)

    print("\n✨ Multi-data test complete!")
    print(f"📊 Tested on {len(results)} datasets")
    profitable = sum(1 for r in results if r['return'] > 0)
    print(f"💰 Profitable on {profitable}/{len(results)} datasets ({profitable/len(results)*100:.1f}%)")

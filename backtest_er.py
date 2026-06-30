import os
import sqlite3
import argparse
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
from datetime import datetime

# Define database path
DEFAULT_DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "futures_data.db")

def load_data(db_path, symbol, timeframe):
    """
    Load daily or 2h K-line data for a given symbol from the SQLite database.
    """
    if not os.path.exists(db_path):
        raise FileNotFoundError(f"Database file not found at: {db_path}")
        
    conn = sqlite3.connect(db_path)
    
    if timeframe.lower() == '2h':
        query = f"""
        SELECT datetime, open, high, low, close, volume, open_interest 
        FROM kline_2h 
        WHERE symbol = ? AND is_continuous = 1
        ORDER BY datetime ASC
        """
        df = pd.read_sql_query(query, conn, params=(symbol.upper(),))
        df.rename(columns={'datetime': 'timestamp'}, inplace=True)
    else:
        query = f"""
        SELECT date, open, high, low, close, volume, open_interest 
        FROM kline_daily 
        WHERE symbol = ? AND is_continuous = 1
        ORDER BY date ASC
        """
        df = pd.read_sql_query(query, conn, params=(symbol.upper(),))
        df.rename(columns={'date': 'timestamp'}, inplace=True)
        
    # Load multiplier and tick size from metadata
    meta_query = "SELECT multiplier, tick_size FROM contract_metadata WHERE symbol = ?"
    meta = conn.execute(meta_query, (symbol.upper(),)).fetchone()
    
    conn.close()
    
    if df.empty:
        raise ValueError(f"No data found for symbol '{symbol}' with timeframe '{timeframe}'")
        
    multiplier = meta[0] if meta else 10.0
    tick_size = meta[1] if meta else 1.0
    
    return df, multiplier, tick_size

def calculate_er(close, period):
    """
    Calculate Kaufman's Efficiency Ratio (ER).
    ER = Absolute value of net price change over period / Sum of absolute 1-period changes
    """
    net_change = (close - close.shift(period)).abs()
    abs_diff = (close - close.shift(1)).abs()
    vol_sum = abs_diff.rolling(window=period).sum()
    
    # Avoid division by zero
    er = np.where(vol_sum > 0, net_change / vol_sum, 0.0)
    return pd.Series(er, index=close.index)

def calculate_ma(close, period, ma_type='ema'):
    """
    Calculate EMA or SMA.
    """
    if ma_type.lower() == 'ema':
        return close.ewm(span=period, adjust=False).mean()
    else:
        return close.rolling(window=period).mean()

def run_backtest(df, multiplier, tick_size, fast_ma_p, slow_ma_p, ma_type, er_p, er_threshold, fee_rate, slippage_ticks):
    """
    Run backtest comparison between:
    1. Benchmark: Pure Moving Average Crossover
    2. Filtered: Moving Average Crossover + Kaufman's ER Filter (Option 1)
    """
    # 1. Calculate indicators
    df['fast_ma'] = calculate_ma(df['close'], fast_ma_p, ma_type)
    df['slow_ma'] = calculate_ma(df['close'], slow_ma_p, ma_type)
    df['er_long'] = calculate_er(df['close'], er_p)
    df['er_short'] = calculate_er(df['close'], 5)  # Plot short term ER as requested
    
    # 2. Generate Signals
    # Trend Signal: 1 (Long) if fast_ma > slow_ma, -1 (Short) if fast_ma < slow_ma
    df['trend_signal'] = np.where(df['fast_ma'] > df['slow_ma'], 1, -1)
    
    # ER Filter: 1 (Trade) if er_long > er_threshold, 0 (Flat) if er_long <= er_threshold
    df['er_filter'] = np.where(df['er_long'] > er_threshold, 1, 0)
    
    # Position targets (generated at close of bar t, executed at open of t+1)
    df['pos_bench'] = df['trend_signal']
    df['pos_filtered'] = df['trend_signal'] * df['er_filter']
    
    # 3. Simulate close-to-close returns
    # Daily/Bar raw return: (Close[t] - Close[t-1]) / Close[t-1]
    df['bar_return'] = df['close'].pct_change()
    
    # Position held during bar t is pos[t-1]
    df['pos_bench_held'] = df['pos_bench'].shift(1).fillna(0).astype(int)
    df['pos_filtered_held'] = df['pos_filtered'].shift(1).fillna(0).astype(int)
    
    # Raw strategy returns
    df['ret_bench_raw'] = df['pos_bench_held'] * df['bar_return']
    df['ret_filtered_raw'] = df['pos_filtered_held'] * df['bar_return']
    
    # Transaction cost factor (slippage + commission as fraction of entry price)
    # Executed when position changes: from pos_held[t-1] to pos_held[t]
    # which corresponds to pos[t-2] to pos[t-1]
    df['bench_change'] = (df['pos_bench_held'] - df['pos_bench_held'].shift(1)).abs().fillna(0)
    df['filtered_change'] = (df['pos_filtered_held'] - df['pos_filtered_held'].shift(1)).abs().fillna(0)
    
    slippage_cost_pct = (slippage_ticks * tick_size) / df['close'].shift(1)
    # Total cost percentage per trade size of 1
    df['cost_pct'] = fee_rate + slippage_cost_pct
    
    df['cost_bench'] = df['bench_change'] * df['cost_pct']
    df['cost_filtered'] = df['filtered_change'] * df['cost_pct']
    
    # Net returns
    df['ret_bench_net'] = df['ret_bench_raw'] - df['cost_bench']
    df['ret_filtered_net'] = df['ret_filtered_raw'] - df['cost_filtered']
    
    # Cumulative returns (compounded equity curve, starting at 1.0)
    df['cum_bench'] = (1 + df['ret_bench_net'].fillna(0)).cumprod()
    df['cum_filtered'] = (1 + df['ret_filtered_net'].fillna(0)).cumprod()
    
    return df

def analyze_trades(df, multiplier, tick_size, fee_rate, slippage_ticks, position_col):
    """
    Extract individual trades to calculate trade-level statistics.
    """
    trades = []
    current_pos = 0
    
    # Align position held to trace trades
    pos_series = df[position_col].values
    close_series = df['close'].values
    time_series = df['timestamp'].values
    
    entry_price = close_series[0] if pos_series[0] != 0 else 0.0
    entry_idx = 0 if pos_series[0] != 0 else -1
    entry_time = time_series[0] if pos_series[0] != 0 else None
    
    for i in range(1, len(df)):
        prev_pos = pos_series[i-1]
        pos = pos_series[i]
        
        # Position change detection
        if pos != prev_pos:
            # If we had a position, we close/reduce it first
            if prev_pos != 0:
                exit_price = close_series[i]  # Assume execution at close of signal bar
                # Calculate trade return
                if entry_price > 0:
                    pnl_pct = prev_pos * (exit_price - entry_price) / entry_price
                    # Transaction cost for entry + exit
                    cost_pct = 2.0 * (fee_rate + (slippage_ticks * tick_size) / entry_price)
                    net_pnl_pct = pnl_pct - cost_pct
                else:
                    net_pnl_pct = 0.0
                
                trades.append({
                    'direction': 'Long' if prev_pos > 0 else 'Short',
                    'entry_time': entry_time,
                    'exit_time': time_series[i],
                    'entry_price': entry_price,
                    'exit_price': exit_price,
                    'net_pnl_pct': net_pnl_pct
                })
            
            # If new position is not flat, we record new entry
            if pos != 0:
                entry_price = close_series[i]
                entry_idx = i
                entry_time = time_series[i]
                
    return pd.DataFrame(trades)

def calculate_performance_metrics(df, trades, col_prefix):
    """
    Calculate standard trading performance metrics based on daily values.
    """
    # 1. Aggregate to Daily Equity for Sharpe and Max Drawdown
    df['date_only'] = df['timestamp'].str.slice(0, 10)
    daily_equity = df.groupby('date_only')[f'cum_{col_prefix}'].last()
    
    daily_returns = daily_equity.pct_change().dropna()
    
    # Total Return
    total_return = daily_equity.iloc[-1] - 1.0
    
    # Days in trade
    start_date = datetime.strptime(daily_equity.index[0], "%Y-%m-%d")
    end_date = datetime.strptime(daily_equity.index[-1], "%Y-%m-%d")
    years = (end_date - start_date).days / 365.25
    if years <= 0:
        years = 1.0
        
    # Annualized Return
    annualized_return = (daily_equity.iloc[-1]) ** (1.0 / years) - 1.0
    
    # Sharpe Ratio (daily-based, annualized)
    std = daily_returns.std()
    mean = daily_returns.mean()
    sharpe = (mean / std * np.sqrt(250)) if std > 0 else 0.0
    
    # Max Drawdown
    running_max = daily_equity.cummax()
    drawdown = (daily_equity - running_max) / running_max
    max_dd = drawdown.min()
    
    # Trade-level statistics
    num_trades = len(trades)
    if num_trades > 0:
        win_trades = trades[trades['net_pnl_pct'] > 0]
        win_rate = len(win_trades) / num_trades
        
        gross_profits = trades[trades['net_pnl_pct'] > 0]['net_pnl_pct'].sum()
        gross_losses = trades[trades['net_pnl_pct'] <= 0]['net_pnl_pct'].sum()
        profit_factor = (gross_profits / abs(gross_losses)) if gross_losses != 0 else float('inf')
        
        avg_pnl_pct = trades['net_pnl_pct'].mean()
    else:
        win_rate = 0.0
        profit_factor = 0.0
        avg_pnl_pct = 0.0
        
    return {
        'total_return': total_return,
        'annualized_return': annualized_return,
        'sharpe_ratio': sharpe,
        'max_drawdown': max_dd,
        'num_trades': num_trades,
        'win_rate': win_rate,
        'profit_factor': profit_factor,
        'avg_pnl_pct': avg_pnl_pct
    }

def main():
    parser = argparse.ArgumentParser(description="Kaufman ER Filter Backtesting System")
    parser.add_argument("--symbol", type=str, default="RB", help="Futures contract symbol (e.g. RB)")
    parser.add_argument("--timeframe", type=str, default="2h", choices=["daily", "2h"], help="Timeframe (daily or 2h)")
    parser.add_argument("--fast-ma", type=int, default=10, help="Fast moving average period")
    parser.add_argument("--slow-ma", type=int, default=30, help="Slow moving average period")
    parser.add_argument("--ma-type", type=str, default="ema", choices=["ema", "sma"], help="Moving average type (ema or sma)")
    parser.add_argument("--er-period", type=int, default=20, help="Kaufman ER period")
    parser.add_argument("--er-threshold", type=float, default=0.4, help="ER threshold to allow trading")
    parser.add_argument("--fee-rate", type=float, default=0.0001, help="Transaction fee rate (e.g. 0.0001 = 0.01%)")
    parser.add_argument("--slippage-ticks", type=float, default=1.0, help="Slippage in ticks per side")
    
    args = parser.parse_args()
    
    print("=" * 60)
    print(f"  Kaufman ER Filter Backtest Engine")
    print("=" * 60)
    print(f"Target Symbol  : {args.symbol}")
    print(f"Timeframe      : {args.timeframe}")
    print(f"Trend Signal   : {args.ma_type.upper()}({args.fast_ma}) vs {args.ma_type.upper()}({args.slow_ma})")
    print(f"ER Filter      : ER({args.er_period}) > {args.er_threshold}")
    print(f"Transaction Cost: Fee={args.fee_rate * 100:.3f}%, Slippage={args.slippage_ticks} ticks")
    print("-" * 60)
    
    # 1. Load Data
    try:
        df, multiplier, tick_size = load_data(DEFAULT_DB_PATH, args.symbol, args.timeframe)
        print(f"Loaded {len(df)} bars of K-line data.")
        print(f"Symbol Multiplier: {multiplier}, Tick Size: {tick_size}")
    except Exception as e:
        print(f"Error loading data: {e}")
        return
        
    # 2. Run Backtest
    df = run_backtest(df, multiplier, tick_size, 
                      args.fast_ma, args.slow_ma, args.ma_type,
                      args.er_period, args.er_threshold,
                      args.fee_rate, args.slippage_ticks)
                      
    # 3. Analyze Trades
    trades_bench = analyze_trades(df, multiplier, tick_size, args.fee_rate, args.slippage_ticks, 'pos_bench')
    trades_filtered = analyze_trades(df, multiplier, tick_size, args.fee_rate, args.slippage_ticks, 'pos_filtered')
    
    # 4. Performance Metrics
    perf_bench = calculate_performance_metrics(df, trades_bench, 'bench')
    perf_filtered = calculate_performance_metrics(df, trades_filtered, 'filtered')
    
    # 5. Output Report
    print("\n" + "=" * 25 + " PERFORMANCE REPORT " + "=" * 25)
    metrics_names = [
        ('Total Return', 'total_return', '{:.2%}'),
        ('Annualized Return', 'annualized_return', '{:.2%}'),
        ('Sharpe Ratio', 'sharpe_ratio', '{:.2f}'),
        ('Max Drawdown', 'max_drawdown', '{:.2%}'),
        ('Number of Trades', 'num_trades', '{}'),
        ('Trade Win Rate', 'win_rate', '{:.2%}'),
        ('Profit Factor', 'profit_factor', '{:.2f}'),
        ('Avg Return/Trade', 'avg_pnl_pct', '{:.2%}')
    ]
    
    print(f"{'Metric':<25}{'Benchmark (No Filter)':<25}{'ER Filtered':<25}")
    print("-" * 75)
    for label, key, fmt in metrics_names:
        val_bench = fmt.format(perf_bench[key])
        val_filtered = fmt.format(perf_filtered[key])
        print(f"{label:<25}{val_bench:<25}{val_filtered:<25}")
    print("=" * 70)
    
    # 6. Plotting
    plt.figure(figsize=(12, 8))
    
    # Subplot 1: Price and MAs
    plt.subplot(3, 1, 1)
    plt.plot(df['close'], label='Close Price', color='#b0b0b0', alpha=0.7)
    plt.plot(df['fast_ma'], label=f'Fast MA ({args.fast_ma})', color='#ff7f0e', alpha=0.9)
    plt.plot(df['slow_ma'], label=f'Slow MA ({args.slow_ma})', color='#1f77b4', alpha=0.9)
    plt.title(f"{args.symbol} {args.timeframe.upper()} Backtest Results")
    plt.ylabel('Price')
    plt.legend(loc='upper left')
    plt.grid(True, linestyle='--', alpha=0.5)
    
    # Subplot 2: Kaufman ER Long & Short
    plt.subplot(3, 1, 2)
    plt.plot(df['er_long'], label=f'ER Long ({args.er_period})', color='red', linewidth=1.5)
    plt.plot(df['er_short'], label='ER Short (5)', color='blue', alpha=0.6, linewidth=1.0)
    plt.axhline(args.er_threshold, color='gray', linestyle='--', label=f'Threshold ({args.er_threshold})')
    plt.axhline(0.3, color='lightgray', linestyle=':', label='Low Thr (0.3)')
    plt.axhline(0.6, color='lightgray', linestyle=':', label='High Thr (0.6)')
    plt.ylabel('Efficiency Ratio')
    plt.ylim(-0.05, 1.05)
    plt.legend(loc='upper left')
    plt.grid(True, linestyle='--', alpha=0.5)
    
    # Subplot 3: Equity Curve
    plt.subplot(3, 1, 3)
    plt.plot(df['cum_bench'], label='Benchmark (No Filter)', color='gray', alpha=0.8)
    plt.plot(df['cum_filtered'], label='ER Filtered', color='green', linewidth=2.0)
    plt.ylabel('Equity (Base 1.0)')
    plt.xlabel('Bar Index')
    plt.legend(loc='upper left')
    plt.grid(True, linestyle='--', alpha=0.5)
    
    plt.tight_layout()
    plot_path = "backtest_er.png"
    plt.savefig(plot_path, dpi=300)
    print(f"\n[Success] Results plot saved to: {os.path.abspath(plot_path)}")
    plt.close()

if __name__ == "__main__":
    main()

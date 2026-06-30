import os
import sqlite3
import argparse
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
from datetime import datetime

DEFAULT_DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "futures_data.db")

def load_all_symbols(db_path, timeframe):
    """
    Get all unique symbols from the specified timeframe table.
    """
    conn = sqlite3.connect(db_path)
    table_name = "kline_2h" if timeframe.lower() == '2h' else "kline_daily"
    query = f"SELECT DISTINCT symbol FROM {table_name}"
    symbols = [row[0] for row in conn.execute(query).fetchall()]
    conn.close()
    return symbols

def load_symbol_data(db_path, symbol, timeframe):
    """
    Load K-line data and metadata for a specific symbol.
    """
    conn = sqlite3.connect(db_path)
    if timeframe.lower() == '2h':
        query = """
        SELECT symbol, datetime, open, high, low, close, volume, open_interest 
        FROM kline_2h 
        WHERE symbol = ? AND is_continuous = 1
        ORDER BY datetime ASC
        """
        df = pd.read_sql_query(query, conn, params=(symbol.upper(),))
        df.rename(columns={'datetime': 'timestamp'}, inplace=True)
    else:
        query = """
        SELECT symbol, date, open, high, low, close, volume, open_interest 
        FROM kline_daily 
        WHERE symbol = ? AND is_continuous = 1
        ORDER BY date ASC
        """
        df = pd.read_sql_query(query, conn, params=(symbol.upper(),))
        df.rename(columns={'date': 'timestamp'}, inplace=True)
        
    meta_query = "SELECT multiplier, tick_size FROM contract_metadata WHERE symbol = ?"
    meta = conn.execute(meta_query, (symbol.upper(),)).fetchone()
    conn.close()
    
    multiplier = meta[0] if meta else 10.0
    tick_size = meta[1] if meta else 1.0
    
    return df, multiplier, tick_size

def wenhua_sma(series, n, m):
    """
    Simulate Wenhua MyLanguage SMA(X, N, M):
    Y_t = (M * X_t + (N - M) * Y_{t-1}) / N
    This is equivalent to pandas ewm with alpha = M / N and adjust=False.
    """
    alpha = m / n
    return series.ewm(alpha=alpha, adjust=False).mean()

def run_quant_sniper_strategy(df, multiplier, tick_size, fee_rate, slippage_ticks):
    """
    Translate Wenhua WH6/WH8 '阶梯防守型趋势追踪器' to Python.
    """
    if len(df) < 65:
        df['ret_net'] = 0.0
        df['position'] = 0
        df['timestamp_dt'] = pd.to_datetime(df['timestamp'])
        df['date_only'] = df['timestamp'].str.slice(0, 10)
        return df, []
        
    close = df['close']
    open_p = df['open']
    high = df['high']
    low = df['low']
    volume = df['volume']
    
    # 1. Big MA (N1 = 60)
    ma_big = close.rolling(60).mean()
    
    # 2. Structural shapes
    h2 = high.shift(2)
    l2 = low.shift(2)
    c2 = close.shift(2)
    
    ycdt = ((high > h2) & (low > l2)) | ((high > h2) & (close > c2))
    yckt = ((low < l2) & (high < h2)) | ((low < l2) & (close < c2))
    
    # 3. Triggers
    duo_raw = ycdt & ycdt.shift(1) & (close > ma_big)
    kong_raw = yckt & yckt.shift(1) & (close < ma_big)
    
    # 4. State Machine Loop
    positions = np.zeros(len(df))
    sl_l_arr = np.full(len(df), np.nan)
    sl_s_arr = np.full(len(df), np.nan)
    
    in_long = False
    in_short = False
    sl_l = 0.0
    sl_s = 0.0
    
    close_series = close.values
    high_series = high.values
    low_series = low.values
    time_series = df['timestamp'].values
    
    duo_raw_vals = duo_raw.values
    kong_raw_vals = kong_raw.values
    
    trades = []
    entry_price = 0.0
    entry_time = None
    
    for i in range(2, len(df)):
        dr = duo_raw_vals[i]
        kr = kong_raw_vals[i]
        
        # Check entries and update stop levels
        if dr:
            sl_l = min(low_series[i], low_series[i-1])
            in_long = True
            in_short = False
        if kr:
            sl_s = max(high_series[i], high_series[i-1])
            in_short = True
            in_long = False
            
        # Check exits
        if in_long:
            if close_series[i] < sl_l or kr:
                in_long = False
        elif in_short:
            if close_series[i] > sl_s or dr:
                in_short = False
                
        positions[i] = 1 if in_long else (-1 if in_short else 0)
        sl_l_arr[i] = sl_l if in_long else np.nan
        sl_s_arr[i] = sl_s if in_short else np.nan
        
    df['position'] = positions
    df['pos_held'] = df['position'].shift(1).fillna(0).astype(int)
    
    # 5. Returns & Cost calculation
    df['bar_return'] = close.pct_change()
    df['ret_raw'] = df['pos_held'] * df['bar_return']
    
    df['pos_change'] = (df['pos_held'] - df['pos_held'].shift(1)).abs().fillna(0)
    slippage_cost_pct = (slippage_ticks * tick_size) / close.shift(1)
    df['cost_pct'] = fee_rate + slippage_cost_pct
    df['cost'] = df['pos_change'] * df['cost_pct']
    df['ret_net'] = df['ret_raw'] - df['cost']
    
    df['timestamp_dt'] = pd.to_datetime(df['timestamp'])
    df['date_only'] = df['timestamp'].str.slice(0, 10)
    
    # Extract trades
    pos_series = df['pos_held'].values
    entry_price = close_series[0] if pos_series[0] != 0 else 0.0
    entry_time = time_series[0] if pos_series[0] != 0 else None
    
    for i in range(1, len(df)):
        prev_pos = pos_series[i-1]
        pos = pos_series[i]
        
        if pos != prev_pos:
            if prev_pos != 0:
                exit_price = close_series[i]
                if entry_price > 0:
                    pnl_pct = prev_pos * (exit_price - entry_price) / entry_price
                    cost_pct = 2.0 * (fee_rate + (slippage_ticks * tick_size) / entry_price)
                    net_pnl_pct = pnl_pct - cost_pct
                else:
                    net_pnl_pct = 0.0
                    
                trades.append({
                    'symbol': df['symbol'].iloc[0],
                    'direction': 'Long' if prev_pos > 0 else 'Short',
                    'entry_time': entry_time,
                    'exit_time': time_series[i],
                    'entry_price': entry_price,
                    'exit_price': exit_price,
                    'net_pnl_pct': net_pnl_pct
                })
            if pos != 0:
                entry_price = close_series[i]
                entry_time = time_series[i]
                
    return df, trades

def calculate_portfolio_performance(returns_df, all_trades_df):
    """
    Calculate portfolio-level performance metrics based on the daily returns dataframe.
    """
    # Equally-weighted portfolio daily returns
    portfolio_daily_returns = returns_df.mean(axis=1)
    portfolio_equity = (1 + portfolio_daily_returns).cumprod()
    
    total_return = portfolio_equity.iloc[-1] - 1.0
    
    start_date = datetime.strptime(returns_df.index[0], "%Y-%m-%d")
    end_date = datetime.strptime(returns_df.index[-1], "%Y-%m-%d")
    years = (end_date - start_date).days / 365.25
    if years <= 0:
        years = 1.0
        
    annualized_return = (portfolio_equity.iloc[-1]) ** (1.0 / years) - 1.0
    
    std = portfolio_daily_returns.std()
    mean = portfolio_daily_returns.mean()
    sharpe = (mean / std * np.sqrt(250)) if std > 0 else 0.0
    
    running_max = portfolio_equity.cummax()
    drawdown = (portfolio_equity - running_max) / running_max
    max_dd = drawdown.min()
    
    num_trades = len(all_trades_df)
    if num_trades > 0:
        win_trades = all_trades_df[all_trades_df['net_pnl_pct'] > 0]
        win_rate = len(win_trades) / num_trades
        
        gross_profits = all_trades_df[all_trades_df['net_pnl_pct'] > 0]['net_pnl_pct'].sum()
        gross_losses = all_trades_df[all_trades_df['net_pnl_pct'] <= 0]['net_pnl_pct'].sum()
        profit_factor = (gross_profits / abs(gross_losses)) if gross_losses != 0 else float('inf')
        
        avg_pnl_pct = all_trades_df['net_pnl_pct'].mean()
    else:
        win_rate = 0.0
        profit_factor = 0.0
        avg_pnl_pct = 0.0
        
    return {
        'portfolio_equity': portfolio_equity,
        'portfolio_daily_returns': portfolio_daily_returns,
        'metrics': {
            'total_return': total_return,
            'annualized_return': annualized_return,
            'sharpe_ratio': sharpe,
            'max_drawdown': max_dd,
            'num_trades': num_trades,
            'win_rate': win_rate,
            'profit_factor': profit_factor,
            'avg_pnl_pct': avg_pnl_pct
        }
    }

def main():
    parser = argparse.ArgumentParser(description="Wenhua Quant Wave Sniper - Portfolio Backtest Engine")
    parser.add_argument("--timeframe", type=str, default="2h", choices=["daily", "2h"], help="Timeframe (daily or 2h)")
    parser.add_argument("--fee-rate", type=float, default=0.0001, help="Transaction fee rate (e.g. 0.0001 = 0.01%)")
    parser.add_argument("--slippage-ticks", type=float, default=1.0, help="Slippage in ticks per side")
    
    args = parser.parse_args()
    
    print("=" * 70)
    print(f"  Wenhua Quant Wave Sniper - Portfolio Backtest Engine")
    print("=" * 70)
    print(f"Timeframe      : {args.timeframe.upper()}")
    print(f"Transaction Cost: Fee={args.fee_rate * 100:.3f}%, Slippage={args.slippage_ticks} ticks")
    
    # 1. Get symbols
    try:
        symbols = load_all_symbols(DEFAULT_DB_PATH, args.timeframe)
        print(f"Found {len(symbols)} symbols in database for {args.timeframe.upper()} table.")
        print(f"Symbols list: {symbols}")
    except Exception as e:
        print(f"Error loading symbols: {e}")
        return
        
    if not symbols:
        print("No symbols to backtest. Aborting.")
        return
        
    # 2. Run strategy for each symbol
    all_daily_returns = {}
    all_trades = []
    symbol_reports = []
    
    print("\nRunning backtests for individual symbols...")
    print("-" * 70)
    for sym in symbols:
        try:
            df, multiplier, tick_size = load_symbol_data(DEFAULT_DB_PATH, sym, args.timeframe)
            if len(df) < 65:
                print(f"  Symbol {sym:<6}: SKIPPED (Not enough data: {len(df)} bars)")
                continue
                
            df, trades = run_quant_sniper_strategy(df, multiplier, tick_size, args.fee_rate, args.slippage_ticks)
            all_trades.extend(trades)
            
            # Aggregate to daily return
            daily_ret = df.groupby('date_only')['ret_net'].sum()
            all_daily_returns[sym] = daily_ret
            
            # Simple individual metrics
            cum_ret = (1 + df['ret_net']).cumprod()
            tot_ret = cum_ret.iloc[-1] - 1.0 if not cum_ret.empty else 0.0
            
            # Max Drawdown
            running_max = cum_ret.cummax()
            drawdown = (cum_ret - running_max) / running_max
            m_dd = drawdown.min() if not drawdown.empty else 0.0
            
            num_t = len(trades)
            win_r = len([t for t in trades if t['net_pnl_pct'] > 0]) / num_t if num_t > 0 else 0.0
            
            symbol_reports.append({
                'symbol': sym,
                'bars': len(df),
                'total_return': tot_ret,
                'max_dd': m_dd,
                'trades': num_t,
                'win_rate': win_r
            })
            print(f"  Symbol {sym:<6}: Bars={len(df):<5} Trades={num_t:<4} WinRate={win_r:6.1%} Return={tot_ret:7.2%} MaxDD={m_dd:6.1%}")
            
        except Exception as e:
            print(f"  Symbol {sym:<6}: FAILED due to error: {e}")
            
    if not all_daily_returns:
        print("\nNo symbols were successfully backtested. Aborting.")
        return
        
    # 3. Create combined returns DataFrame
    returns_df = pd.DataFrame(all_daily_returns)
    returns_df.sort_index(inplace=True)
    # Fill NaN values with 0.0 (no return on days when symbol had no data or was closed)
    returns_df.fillna(0.0, inplace=True)
    
    # 4. Calculate Portfolio stats
    all_trades_df = pd.DataFrame(all_trades)
    port_results = calculate_portfolio_performance(returns_df, all_trades_df)
    
    # 5. Output Portfolio Report
    pm = port_results['metrics']
    print("\n" + "=" * 20 + " PORTFOLIO PERFORMANCE SUMMARY " + "=" * 20)
    print(f"Total Portfolio Return   : {pm['total_return']:.2%}")
    print(f"Annualized Portfolio Ret : {pm['annualized_return']:.2%}")
    print(f"Annualized Sharpe Ratio  : {pm['sharpe_ratio']:.2f}")
    print(f"Max Portfolio Drawdown   : {pm['max_drawdown']:.2%}")
    print(f"Total Trades Across All  : {pm['num_trades']}")
    print(f"Combined Trade Win Rate  : {pm['win_rate']:.2%}")
    print(f"Combined Profit Factor   : {pm['profit_factor']:.2f}")
    print(f"Average Profit per Trade : {pm['avg_pnl_pct']:.2%}")
    print("=" * 71)
    
    # Output individual table sorted by return
    print("\nIndividual Symbol Breakdown (Sorted by Total Return):")
    print("-" * 75)
    print(f"{'Symbol':<10}{'Bars':<10}{'Trades':<10}{'Win Rate':<15}{'Total Return':<15}{'Max Drawdown':<15}")
    print("-" * 75)
    for rep in sorted(symbol_reports, key=lambda x: x['total_return'], reverse=True):
        print(f"{rep['symbol']:<10}{rep['bars']:<10}{rep['trades']:<10}{rep['win_rate']:13.1%}{rep['total_return']:13.2%}{rep['max_dd']:13.2%}")
    print("-" * 75)
    
    # 6. Plotting Portfolio Equity
    plt.figure(figsize=(12, 6))
    plt.plot(port_results['portfolio_equity'], color='blue', linewidth=2.0, label='Portfolio Equity Curve (Equal Weight)')
    plt.axhline(1.0, color='gray', linestyle='--')
    plt.title(f"Quant Wave Sniper Portfolio Equity Curve ({args.timeframe.upper()} Timeframe)")
    plt.ylabel('Equity (Base 1.0)')
    plt.xlabel('Date')
    plt.grid(True, linestyle='--', alpha=0.5)
    plt.legend()
    
    plot_path = "portfolio_results.png"
    plt.savefig(plot_path, dpi=300)
    print(f"\n[Success] Portfolio equity plot saved to: {os.path.abspath(plot_path)}")
    plt.close()

if __name__ == "__main__":
    main()

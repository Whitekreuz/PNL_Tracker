import os
import sqlite3
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import matplotlib.dates as mdates

DEFAULT_DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "futures_data.db")

def wenhua_sma(series, n, m):
    alpha = m / n
    return series.ewm(alpha=alpha, adjust=False).mean()

def run_strategy_with_cooldown(df, K_cooldown, fee_rate=0.0001, slippage_ticks=1.0, multiplier=10.0, tick_size=1.0):
    """
    Run backtest for TA with a specific cooling-off period K_cooldown.
    If K_cooldown > 0, entering in the same direction is blocked for K_cooldown bars
    after a stop loss or breakeven exit.
    """
    close = df['close']
    open_p = df['open']
    high = df['high']
    low = df['low']
    volume = df['volume']
    
    # 1. Base Indicators
    MA55 = close.rolling(55).mean()
    MA144 = close.rolling(144).mean()
    MA233 = close.rolling(233).mean()
    
    MAMAX = pd.concat([MA55, MA144, MA233], axis=1).max(axis=1)
    MAMIN = pd.concat([MA55, MA144, MA233], axis=1).min(axis=1)
    
    MASQ = (MAMAX - MAMIN) / MAMIN < 0.015
    BULLB = (close > MA144) & (close > MA233)
    BEARB = (close < MA144) & (close < MA233)
    
    # KDJ
    llv_low_9 = low.rolling(9).min()
    hhv_high_9 = high.rolling(9).max()
    denom = hhv_high_9 - llv_low_9
    rsv = np.where(denom > 0, (close - llv_low_9) / denom * 100, 50.0)
    rsv = pd.Series(rsv, index=df.index)
    
    K_val = wenhua_sma(rsv, 3, 1)
    D_val = wenhua_sma(K_val, 3, 1)
    J_val = 3 * K_val - 2 * D_val
    
    # MACD
    diff = close.ewm(span=12, adjust=False).mean() - close.ewm(span=26, adjust=False).mean()
    dea = diff.ewm(span=9, adjust=False).mean()
    macd = 2 * (diff - dea)
    
    # K-line Shape
    body = (close - open_p).abs()
    ushadow = high - pd.concat([close, open_p], axis=1).max(axis=1)
    lshadow = pd.concat([close, open_p], axis=1).min(axis=1) - low
    vol2x = volume >= volume.shift(1) * 2
    biasval = (close - MA55) / MA55 * 100
    
    # Long/Short/Exit Signals
    issup = ((low <= MA144) & (close >= MA144)) | ((low <= MA233) & (close >= MA233))
    lpin = BULLB & (lshadow > body * 2) & (lshadow > ushadow) & issup
    
    mhookup = (macd < 0) & (macd > macd.shift(1)) & (macd.shift(1) < macd.shift(2))
    mdpit = macd.shift(1) < macd.rolling(20).min().shift(2)
    pnolow = low > low.rolling(20).min().shift(2)
    lhid = BULLB & mhookup & mdpit & pnolow & (low <= MA55 * 1.03)
    
    lkdj = BULLB & (low <= MA55 * 1.005) & (close >= MA55) & (J_val < 20) & (J_val > J_val.shift(1))
    
    lbrk = MASQ.shift(1) & (close.shift(1) <= MAMAX.shift(1)) & (close > MAMAX) & vol2x & (close > open_p)
    
    nlow = low < low.rolling(8).min().shift(1)
    ldiv = nlow & (biasval < -6.0) & (close < MA55) & (macd < 0) & (macd > macd.shift(1))
    
    long_entry = lpin | lhid | lkdj | lbrk | ldiv
    
    spin = BEARB & (ushadow > body * 2) & (ushadow > lshadow) & (high >= MA55 * 0.995) & (close <= MA55)
    
    mhookdn = (macd > 0) & (macd < macd.shift(1)) & (macd.shift(1) > macd.shift(2))
    mhill = macd.shift(1) > macd.rolling(20).max().shift(2)
    pnohigh = high < high.rolling(20).max().shift(2)
    shid = BEARB & mhookdn & mhill & pnohigh & (high >= MA55 * 0.97)
    
    skdj = BEARB & (high >= MA55 * 0.995) & (close <= MA55) & (J_val > 80) & (J_val < J_val.shift(1))
    
    sbrk = MASQ.shift(1) & (close.shift(1) >= MAMIN.shift(1)) & (close < MAMIN) & vol2x & (close < open_p)
    
    nhigh = high > high.rolling(8).max().shift(1)
    sdiv = nhigh & (biasval > 6.0) & (close > MA55) & (macd > 0) & (macd < macd.shift(1))
    
    short_entry = spin | shid | skdj | sbrk | sdiv
    
    ma55_dn = MA55 < MA55.shift(1)
    ma55_up = MA55 > MA55.shift(1)
    
    exlbrk = (close.shift(1) >= MA144.shift(1)) & (close < MA144)
    exlmom = (close.shift(1) >= MA55.shift(1)) & (close < MA55) & ma55_dn
    exlcrs = (MA55.shift(1) >= MA144.shift(1)) & (MA55 < MA144)
    exlall = exlbrk | exlmom | exlcrs
    
    exsbrk = (close.shift(1) <= MA144.shift(1)) & (close > MA144)
    exsmom = (close.shift(1) <= MA55.shift(1)) & (close > MA55) & ma55_up
    exscrs = (MA55.shift(1) <= MA144.shift(1)) & (MA55 > MA144)
    exsall = exsbrk | exsmom | exscrs

    # Calculate ATR
    high_low = high - low
    high_prev_close = (high - close.shift(1)).abs()
    low_prev_close = (low - close.shift(1)).abs()
    tr = pd.concat([high_low, high_prev_close, low_prev_close], axis=1).max(axis=1)
    df['atr'] = tr.rolling(window=14).mean().bfill().fillna(0.0)
    
    positions = np.zeros(len(df))
    ret_net = np.zeros(len(df))
    ret_raw = np.zeros(len(df))
    cost_series = np.zeros(len(df))
    
    # Detail markers for plotting
    stop_prices = np.full(len(df), np.nan)
    long_entry_markers = np.full(len(df), np.nan)
    short_entry_markers = np.full(len(df), np.nan)
    stop_exit_markers = np.full(len(df), np.nan)
    normal_exit_markers = np.full(len(df), np.nan)
    
    pos = 0
    entry_price = 0.0
    entry_atr = 0.0
    current_stop = 0.0
    breakeven_triggered = False
    
    # Cooldown markers
    long_cooldown_until = 0
    short_cooldown_until = 0
    
    trades = []
    entry_time = None
    
    close_series = close.values
    high_series = high.values
    low_series = low.values
    atr_series = df['atr'].values
    time_series = df['timestamp'].values
    
    le_vals = long_entry.values
    se_vals = short_entry.values
    lx_vals = exlall.values
    sx_vals = exsall.values
    
    for i in range(1, len(df)):
        pos_held = pos
        prev_pos_held = positions[i-1] if i > 1 else 0
        
        pos_change = abs(pos_held - prev_pos_held)
        if pos_change > 0:
            cost_pct = fee_rate + (slippage_ticks * tick_size) / close_series[i-1]
            entry_cost = pos_change * cost_pct
        else:
            entry_cost = 0.0
            
        stopped_out = False
        exit_price = 0.0
        
        if pos_held == 1:
            if not breakeven_triggered:
                if high_series[i] >= entry_price + 1.5 * entry_atr:
                    breakeven_triggered = True
                    current_stop = entry_price
            
            stop_prices[i] = current_stop
            
            if low_series[i] <= current_stop:
                stopped_out = True
                exit_price = current_stop
                
        elif pos_held == -1:
            if not breakeven_triggered:
                if low_series[i] <= entry_price - 1.5 * entry_atr:
                    breakeven_triggered = True
                    current_stop = entry_price
            
            stop_prices[i] = current_stop
            
            if high_series[i] >= current_stop:
                stopped_out = True
                exit_price = current_stop
                
        if stopped_out:
            if pos_held == 1:
                raw_ret = (exit_price - close_series[i-1]) / close_series[i-1]
                # Set cooling period for long
                long_cooldown_until = i + K_cooldown
            else:
                raw_ret = (close_series[i-1] - exit_price) / close_series[i-1]
                # Set cooling period for short
                short_cooldown_until = i + K_cooldown
                
            exit_cost = fee_rate + (slippage_ticks * tick_size) / exit_price
            
            ret_raw[i] = raw_ret
            cost_series[i] = entry_cost + exit_cost
            ret_net[i] = raw_ret - entry_cost - exit_cost
            
            stop_exit_markers[i] = exit_price
            
            if entry_price > 0:
                pnl_pct = pos_held * (exit_price - entry_price) / entry_price
                cost_pct = 2.0 * (fee_rate + (slippage_ticks * tick_size) / entry_price)
                net_pnl_pct = pnl_pct - cost_pct
            else:
                net_pnl_pct = 0.0
                
            trades.append({
                'symbol': df['symbol'].iloc[0],
                'direction': 'Long' if pos_held > 0 else 'Short',
                'entry_time': entry_time,
                'exit_time': time_series[i],
                'entry_price': entry_price,
                'exit_price': exit_price,
                'net_pnl_pct': net_pnl_pct,
                'exit_reason': 'Stop Loss / Breakeven'
            })
            
            pos = 0
            positions[i] = 0
            entry_price = 0.0
            entry_time = None
            
        else:
            raw_ret = pos_held * (close_series[i] - close_series[i-1]) / close_series[i-1]
            ret_raw[i] = raw_ret
            cost_series[i] = entry_cost
            ret_net[i] = raw_ret - entry_cost
            
            le = le_vals[i]
            se = se_vals[i]
            lx = lx_vals[i]
            sx = sx_vals[i]
            
            prev_pos = pos
            if pos == 0:
                # Check cooldown blocks before entering new position
                if le and not se and i > long_cooldown_until:
                    pos = 1
                elif se and not le and i > short_cooldown_until:
                    pos = -1
            elif pos == 1:
                if se:
                    pos = -1
                elif lx:
                    pos = 0
            elif pos == -1:
                if le:
                    pos = 1
                elif sx:
                    pos = 0
                    
            positions[i] = pos
            
            if pos != prev_pos:
                if prev_pos != 0:
                    exit_p = close_series[i]
                    normal_exit_markers[i] = exit_p
                    if entry_price > 0:
                        pnl_pct = prev_pos * (exit_p - entry_price) / entry_price
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
                        'exit_price': exit_p,
                        'net_pnl_pct': net_pnl_pct,
                        'exit_reason': 'Normal Signal'
                    })
                    
                if pos != 0:
                    entry_price = close_series[i]
                    entry_atr = atr_series[i]
                    entry_time = time_series[i]
                    breakeven_triggered = False
                    if pos == 1:
                        initial_stop = entry_price - 1.5 * entry_atr
                        long_entry_markers[i] = entry_price
                    else:
                        initial_stop = entry_price + 1.5 * entry_atr
                        short_entry_markers[i] = entry_price
                    current_stop = initial_stop
                    
    df['position'] = positions
    df['pos_held'] = pd.Series(positions, index=df.index).shift(1).fillna(0).astype(int)
    df['ret_net'] = ret_net
    df['cum_ret'] = (1 + ret_net).cumprod()
    
    df['stop_price'] = stop_prices
    df['long_entry'] = long_entry_markers
    df['short_entry'] = short_entry_markers
    df['stop_exit'] = stop_exit_markers
    df['normal_exit'] = normal_exit_markers
    
    df['MA55'] = MA55
    df['MA144'] = MA144
    df['MA233'] = MA233
    
    return df, trades

def main():
    conn = sqlite3.connect(DEFAULT_DB_PATH)
    
    # Load TA metadata
    meta = conn.execute("SELECT multiplier, tick_size FROM contract_metadata WHERE symbol = 'TA'").fetchone()
    multiplier = meta[0] if meta else 5.0  # PTA multiplier is 5
    tick_size = meta[1] if meta else 2.0   # PTA tick size is 2
    
    # Load TA 2H K-lines
    query = """
    SELECT symbol, datetime, open, high, low, close, volume, open_interest 
    FROM kline_2h 
    WHERE symbol = 'TA' AND is_continuous = 1
    ORDER BY datetime ASC
    """
    df = pd.read_sql_query(query, conn)
    df.rename(columns={'datetime': 'timestamp'}, inplace=True)
    conn.close()
    
    print(f"Loaded {len(df)} bars of PTA (TA) 2H K-line data.")
    
    # Run optimization for K_cooldown from 0 to 40
    cooldown_tests = [0, 5, 10, 15, 20, 25, 30, 40, 50]
    results = []
    
    print("\nOptimizing Cooldown Period (K)...")
    print("-" * 65)
    print(f"{'K (Bars)':<10}{'Trades':<10}{'Win Rate':<12}{'Total Return':<15}{'Max Drawdown':<15}")
    print("-" * 65)
    
    best_k = 0
    best_return = -999.0
    best_df = None
    best_trades = None
    
    for k in cooldown_tests:
        df_copy = df.copy()
        res_df, trades_list = run_strategy_with_cooldown(df_copy, k, fee_rate=0.0001, slippage_ticks=1.0, multiplier=multiplier, tick_size=tick_size)
        
        cum_ret = res_df['cum_ret'].iloc[-1] - 1.0 if not res_df['cum_ret'].empty else 0.0
        
        # Max Drawdown
        running_max = res_df['cum_ret'].cummax()
        drawdown = (res_df['cum_ret'] - running_max) / running_max
        max_dd = drawdown.min() if not drawdown.empty else 0.0
        
        num_t = len(trades_list)
        win_r = len([t for t in trades_list if t['net_pnl_pct'] > 0]) / num_t if num_t > 0 else 0.0
        
        print(f"{k:<10}{num_t:<10}{win_r:<12.1%}{cum_ret:<15.2%}{max_dd:<15.2%}")
        
        results.append({
            'k': k,
            'trades': num_t,
            'win_rate': win_r,
            'total_return': cum_ret,
            'max_dd': max_dd
        })
        
        if cum_ret > best_return:
            best_return = cum_ret
            best_k = k
            best_df = res_df
            best_trades = trades_list
            
    print("-" * 65)
    print(f"Optimal Cooldown Period K: {best_k} bars")
    print(f"Optimal Net Return: {best_return:.2%}")
    print("=" * 65)
    
    # Print Trades for best K
    if best_trades:
        best_trades_df = pd.DataFrame(best_trades)
        best_trades_df['net_pnl_pct_fmt'] = best_trades_df['net_pnl_pct'].map(lambda x: f"{x:.2%}")
        print(f"\nAll Trades for PTA (TA) with Optimal Cooldown K={best_k}:")
        print(best_trades_df[['direction', 'entry_time', 'exit_time', 'entry_price', 'exit_price', 'net_pnl_pct_fmt', 'exit_reason']])
        
    # Plotting detailed chart for optimal K
    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(15, 12), sharex=False, gridspec_kw={'height_ratios': [3, 1]})
    timestamps_dt = pd.to_datetime(best_df['timestamp'])
    
    # Subplot 1: Price and markers
    ax1.plot(timestamps_dt, best_df['close'], label='Close Price', color='#7f7f7f', alpha=0.5, linewidth=1.5)
    ax1.plot(timestamps_dt, best_df['MA55'], label='MA55', color='red', alpha=0.8, linewidth=1.0)
    ax1.plot(timestamps_dt, best_df['MA144'], label='MA144', color='magenta', alpha=0.8, linewidth=1.0)
    ax1.plot(timestamps_dt, best_df['MA233'], label='MA233', color='cyan', alpha=0.8, linewidth=1.0)
    
    # Plot active stop loss line
    ax1.plot(timestamps_dt, best_df['stop_price'], label='Active Stop Price', color='#d62728', linestyle='--', linewidth=1.5)
    
    # Plot Entry markers
    long_entries = best_df[best_df['long_entry'].notna()]
    ax1.scatter(pd.to_datetime(long_entries['timestamp']), long_entries['long_entry'], 
                label='Long Entry', color='green', marker='^', s=100, zorder=5)
                
    short_entries = best_df[best_df['short_entry'].notna()]
    ax1.scatter(pd.to_datetime(short_entries['timestamp']), short_entries['short_entry'], 
                label='Short Entry', color='red', marker='v', s=100, zorder=5)
                
    # Plot Exit markers
    stop_exits = best_df[best_df['stop_exit'].notna()]
    ax1.scatter(pd.to_datetime(stop_exits['timestamp']), stop_exits['stop_exit'], 
                label='Stop Loss Exit', color='blue', marker='x', s=120, linewidth=2.0, zorder=5)
                
    normal_exits = best_df[best_df['normal_exit'].notna()]
    ax1.scatter(pd.to_datetime(normal_exits['timestamp']), normal_exits['normal_exit'], 
                label='Normal Exit', color='purple', marker='s', s=80, zorder=5)
                
    ax1.set_title(f"PTA (TA) 2H K-line: Strategy with Optimal Cooldown K={best_k} Bars", fontsize=14)
    ax1.set_ylabel("Price (RMB/Ton)", fontsize=12)
    ax1.legend(loc='upper left', frameon=True, facecolor='white', edgecolor='lightgray')
    ax1.grid(True, linestyle='--', alpha=0.5)
    
    # Formatting dates
    ax1.xaxis.set_major_formatter(mdates.DateFormatter('%Y-%m-%d'))
    ax1.xaxis.set_major_locator(mdates.DayLocator(interval=15))
    fig.autofmt_xdate()
    
    # Subplot 2: Cumulative Return
    ax2.plot(timestamps_dt, best_df['cum_ret'], label=f'Cooldown K={best_k} Net Return', color='green', linewidth=2.0)
    
    # Compare with K=0 (benchmark stop loss without cooldown)
    _, trades_k0 = run_strategy_with_cooldown(df.copy(), 0, fee_rate=0.0001, slippage_ticks=1.0, multiplier=multiplier, tick_size=tick_size)
    df_k0_cum = (1 + df.copy().assign(ret_net=run_strategy_with_cooldown(df.copy(), 0, fee_rate=0.0001, slippage_ticks=1.0, multiplier=multiplier, tick_size=tick_size)[0]['ret_net'])['ret_net']).cumprod()
    ax2.plot(timestamps_dt, df_k0_cum, label='No Cooldown (K=0) Net Return', color='gray', alpha=0.7, linestyle=':')
    
    ax2.axhline(1.0, color='gray', linestyle='--')
    ax2.set_title(f"PTA (TA) Cumulative Net Return Comparison", fontsize=12)
    ax2.set_ylabel("Equity", fontsize=12)
    ax2.set_xlabel("Date", fontsize=12)
    ax2.legend(loc='upper left')
    ax2.grid(True, linestyle='--', alpha=0.5)
    
    # Formatting dates
    ax2.xaxis.set_major_formatter(mdates.DateFormatter('%Y-%m-%d'))
    ax2.xaxis.set_major_locator(mdates.DayLocator(interval=15))
    
    plt.tight_layout()
    plot_path = "ta_details.png"
    plt.savefig(plot_path, dpi=300)
    print(f"\n[Success] PTA detailed plot saved to: {os.path.abspath(plot_path)}")
    plt.close()

if __name__ == "__main__":
    main()

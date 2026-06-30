import os
import sqlite3
import pandas as pd
import numpy as np

DEFAULT_DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "futures_data.db")

def calculate_cross_sectional_rps(timeframe="2h", lookback_periods=[60, 120, 250]):
    """
    Calculate cross-sectional Relative Price Strength (RPS) for all commodities
    in the database for a given timeframe.
    Saves the computed RPS to a SQLite table 'symbol_rps'.
    """
    conn = sqlite3.connect(DEFAULT_DB_PATH)
    
    # 1. Fetch continuous contract data for all symbols
    table_name = "kline_2h" if timeframe == "2h" else "kline_daily"
    date_col = "datetime" if timeframe == "2h" else "date"
    
    query = f"""
    SELECT symbol, {date_col} as timestamp, close 
    FROM {table_name} 
    WHERE is_continuous = 1
    ORDER BY symbol, timestamp ASC
    """
    df = pd.read_sql_query(query, conn)
    
    if df.empty:
        print(f"No data found in {table_name}.")
        conn.close()
        return None
        
    print(f"Loaded {len(df)} price records across all symbols.")
    
    # Pivot to get a wide table of close prices: index=timestamp, columns=symbol
    price_pivot = df.pivot(index='timestamp', columns='symbol', values='close')
    price_pivot.sort_index(inplace=True)
    # Forward fill to handle days where some symbols might not have traded, then bfill
    price_pivot = price_pivot.ffill().bfill()
    
    all_rps_data = []
    
    # Calculate ROC and RPS at each timestamp
    # We do a rolling calculation to get the historical RPS series
    print(f"Calculating rolling RPS for periods: {lookback_periods}...")
    
    # Pre-calculate ROC dataframes to speed up computation
    roc_dfs = {}
    for period in lookback_periods:
        roc_dfs[period] = price_pivot.pct_change(periods=period)
        
    # We loop over timestamps
    timestamps = price_pivot.index
    symbols = price_pivot.columns
    
    # To store rows for the database
    rps_records = []
    
    for i, ts in enumerate(timestamps):
        # We only calculate if we have enough history for the largest period
        max_period = max(lookback_periods)
        if i < max_period:
            continue
            
        row_data = {'timestamp': ts}
        
        # Calculate RPS for each period at this timestamp
        for period in lookback_periods:
            roc_series = roc_dfs[period].iloc[i]  # Series of ROC for all symbols at ts
            # Drop NaN symbols (not yet trading)
            valid_roc = roc_series.dropna()
            
            if len(valid_roc) < 2:
                continue
                
            # Rank from 1 (lowest ROC) to N (highest ROC)
            ranks = valid_roc.rank(method='min')
            n_symbols = len(valid_roc)
            
            # Convert to percentile (0 to 100)
            # RPS = (Rank - 1) / (N - 1) * 100
            for sym, rank in ranks.items():
                rps_val = (rank - 1) / (n_symbols - 1) * 100 if n_symbols > 1 else 100.0
                rps_records.append({
                    'timestamp': ts,
                    'symbol': sym,
                    'period': period,
                    'roc': valid_roc[sym],
                    'rps': rps_val
                })
                
    # Convert records to DataFrame
    rps_df = pd.DataFrame(rps_records)
    
    if rps_df.empty:
        print("No RPS records generated.")
        conn.close()
        return None
        
    # 2. Save to SQLite database
    print("Writing RPS data to database table 'symbol_rps'...")
    # Create index to speed up subsequent queries
    conn.execute("DROP TABLE IF EXISTS symbol_rps")
    rps_df.to_sql("symbol_rps", conn, if_exists="replace", index=False)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_symbol_rps ON symbol_rps (timestamp, symbol, period)")
    conn.commit()
    conn.close()
    
    print("[Success] Completed Relative Price Strength (RPS) calculations.")
    return rps_df

def print_latest_rps_rankings(rps_df, period=120):
    """
    Print the latest RPS rankings for a specific lookback period.
    """
    if rps_df is None or rps_df.empty:
        return
        
    # Get latest timestamp
    latest_ts = rps_df['timestamp'].max()
    latest_df = rps_df[(rps_df['timestamp'] == latest_ts) & (rps_df['period'] == period)]
    latest_df = latest_df.sort_values(by='rps', ascending=False)
    
    print("\n" + "=" * 15 + f" LATEST RPS {period} RANKINGS (As of {latest_ts}) " + "=" * 15)
    print(f"{'Rank':<8}{'Symbol':<12}{'RPS Value':<15}{'Return (ROC)':<15}")
    print("-" * 55)
    for idx, (_, row) in enumerate(latest_df.iterrows(), 1):
        print(f"{idx:<8}{row['symbol']:<12}{row['rps']:<15.1f}{row['roc']:<15.2%}")
    print("=" * 55)

if __name__ == "__main__":
    # Calculate for 2H timeframe with default lookbacks of 60, 120, 250 bars
    # 120 bars in 2H is approximately 20 trading days (1 month)
    # 250 bars is approximately 2 months
    rps_data = calculate_cross_sectional_rps(timeframe="2h", lookback_periods=[60, 120, 250])
    
    if rps_data is not None:
        # Print the latest rankings for 120-bar lookback
        print_latest_rps_rankings(rps_data, period=120)

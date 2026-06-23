import sqlite3
import datetime
import os
import time
import pandas as pd
import akshare as ak
import sys

# Ensure UTF-8 encoding for standard output to avoid console display issues
sys.stdout.reconfigure(encoding='utf-8')

DEFAULT_DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "futures_data.db")

# 1. Sector categorization mapping
SECTOR_MAP = {
    # 黑色建材
    'RB': '黑色建材', 'HC': '黑色建材', 'I': '黑色建材', 'J': '黑色建材', 'JM': '黑色建材', 
    'FG': '黑色建材', 'SA': '黑色建材', 'SF': '黑色建材', 'SM': '黑色建材',
    
    # 有色金属
    'CU': '有色金属', 'AL': '有色金属', 'ZN': '有色金属', 'PB': '有色金属', 'NI': '有色金属', 
    'SN': '有色金属', 'AO': '有色金属', 'BC': '有色金属', 'AD': '有色金属', 'SS': '有色金属',
    
    # 贵金属
    'AU': '贵金属', 'AG': '贵金属', 'PD': '贵金属', 'PT': '贵金属',
    
    # 新新能源
    'LC': '新能源', 'SI': '新能源', 'PS': '新能源',
    
    # 能源化工
    'SC': '能源化工', 'FU': '能源化工', 'LU': '能源化工', 'BU': '能源化工', 
    'MA': '能源化工', 'TA': '能源化工', 'EG': '能源化工', 'EB': '能源化工', 
    'V': '能源化工', 'PP': '能源化工', 'L': '能源化工', 'PG': '能源化工', 
    'PX': '能源化工', 'PF': '能源化工', 'SH': '能源化工', 'BR': '能源化工', 
    'BZ': '能源化工', 'PL': '能源化工', 'PR': '能源化工', 'UR': '能源化工',
    
    # 油脂油料
    'A': '油脂油料', 'B': '油脂油料', 'M': '油脂油料', 'Y': '油脂油料', 
    'P': '油脂油料', 'OI': '油脂油料', 'RM': '油脂油料', 'PK': '油脂油料',
    
    # 农产品
    'C': '农产品', 'CS': '农产品', 'SR': '农产品', 'CF': '农产品', 'CY': '农产品', 
    'AP': '农产品', 'CJ': '农产品', 'JD': '农产品', 'LH': '农产品', 'RR': '农产品',
    'RU': '农产品', 'NR': '农产品',
    
    # 航运轻工
    'EC': '航运轻工', 'OP': '航运轻工', 'SP': '航运轻工', 'LG': '航运轻工',
}

def get_trading_hours_info(symbol):
    """
    Get the trading hours string and trading hours session type for a commodity symbol.
    - Type 1: Day Session Only (09:00-15:00)
    - Type 2: Night Session (21:00-23:00) + Day Session
    - Type 3: Night Session (21:00-01:00) + Day Session
    - Type 4: Night Session (21:00-02:30) + Day Session
    """
    symbol = symbol.upper()
    
    # Type 4: Night to 02:30 (Precious metals, Crude oil, Low sulfur fuel oil)
    if symbol in ['AU', 'AG', 'SC', 'LU']:
        return "21:00-02:30,09:00-10:15,10:30-11:30,13:30-15:00", 4
        
    # Type 3: Night to 01:00 (Base metals)
    elif symbol in ['CU', 'AL', 'ZN', 'PB', 'NI', 'SN', 'AO', 'BC']:
        return "21:00-01:00,09:00-10:15,10:30-11:30,13:30-15:00", 3
        
    # Type 1: Day Session Only (No night session agricultural and some bulk)
    elif symbol in ['JD', 'LH', 'PK', 'AP', 'CJ', 'SF', 'SM', 'UR', 'C', 'CS', 'JR', 'LR', 'PM', 'RI', 'WH', 'FB', 'BB', 'LC', 'SI', 'PS', 'RR']:
        return "09:00-10:15,10:30-11:30,13:30-15:00", 1
        
    # Type 2: Night to 23:00 (Default for other commodity chemical/black products)
    else:
        return "21:00-23:00,09:00-10:15,10:30-11:30,13:30-15:00", 2

def init_db(db_path=DEFAULT_DB_PATH, recreate=False):
    """
    Initialize SQLite database and create tables if they do not exist.
    If recreate is True, drops existing tables first.
    """
    if recreate and os.path.exists(db_path):
        try:
            os.remove(db_path)
            print(f"Removed old database file: {db_path}")
        except Exception as e:
            print(f"Could not remove database file: {e}")
            
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    # 1. Create contract_metadata table (with sector and trading hours)
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS contract_metadata (
        symbol TEXT PRIMARY KEY,
        name TEXT,
        exchange TEXT,
        multiplier REAL,
        tick_size REAL,
        margin_rate REAL,
        current_main_contract TEXT,
        sector TEXT,
        trading_hours TEXT,
        trading_hours_type INTEGER,
        updated_at TEXT
    )
    """)
    
    # 2. Create kline_daily table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS kline_daily (
        symbol TEXT,
        contract TEXT,
        date TEXT,
        open REAL,
        high REAL,
        low REAL,
        close REAL,
        volume REAL,
        open_interest REAL,
        settlement REAL,
        is_continuous INTEGER,
        PRIMARY KEY (symbol, contract, date)
    )
    """)
    
    # 3. Create kline_2h table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS kline_2h (
        symbol TEXT,
        contract TEXT,
        datetime TEXT,
        open REAL,
        high REAL,
        low REAL,
        close REAL,
        volume REAL,
        open_interest REAL,
        is_continuous INTEGER,
        PRIMARY KEY (symbol, contract, datetime)
    )
    """)
    
    conn.commit()
    conn.close()
    print(f"Database initialized at: {db_path}")

def update_metadata(db_path=DEFAULT_DB_PATH, min_oi_capital=50000000, min_turnover=100000000):
    """
    Fetch fee and margin info from AkShare, filter active commodities based on
    liquidity (Open Interest Capital and Daily Turnover), and save metadata with
    sector and trading hours.
    
    - min_oi_capital: Minimum Open Interest Capital in RMB (default 50,000,000 / 5,000万)
    - min_turnover: Minimum Daily Turnover in RMB (default 100,000,000 / 1亿)
    """
    print(f"Updating contract metadata with liquidity filter...")
    print(f"Filter: Open Interest Capital >= {min_oi_capital/10000:.1f}万 RMB OR Daily Turnover >= {min_turnover/10000:.1f}万 RMB")
    
    try:
        df = None
        for attempt in range(3):
            try:
                df = ak.futures_fees_info()
                if df is not None and not df.empty:
                    break
            except Exception as retry_e:
                print(f"  Attempt {attempt+1}/3 failed: {retry_e}")
                if attempt < 2:
                    time.sleep(3)
        if df is None or df.empty:
            raise ValueError("All retry attempts failed or returned empty data")
    except Exception as e:
        print(f"Failed to fetch futures fees info: {e}")
        return []
    
    # Filter out financial futures (CFFEX) and keep only active commodity contracts
    df = df[(df['持仓量'] > 0) & (df['交易所'] != 'CFFEX')].copy()
    if df.empty:
        print("No active commodity contracts with open interest found.")
        return []
    
    df['品种代码_upper'] = df['品种代码'].str.upper()
    
    # Correct zero prices for commodity contracts (e.g. GFEX products like LC, SI, PS)
    zero_price_mask = df['最新价'] == 0.0
    if zero_price_mask.any():
        zero_price_symbols = df[zero_price_mask]['品种代码_upper'].unique()
        print(f"Zero price detected for active commodity symbols: {zero_price_symbols}. Fetching prices from Sina...")
        for sym in zero_price_symbols:
            cont_code = sym + "0"
            try:
                # Get the last few days of daily bars to find the latest close price
                k_df = ak.futures_main_sina(symbol=cont_code, start_date=(datetime.datetime.now() - datetime.timedelta(days=15)).strftime("%Y%m%d"))
                if k_df is not None and not k_df.empty:
                    k_df.columns = ['date', 'open', 'high', 'low', 'close', 'volume', 'open_interest', 'settlement'][:len(k_df.columns)]
                    latest_price = float(k_df.iloc[-1]['close'])
                    df.loc[df['品种代码_upper'] == sym, '最新价'] = latest_price
                    print(f"  Successfully fixed price for {sym}: {latest_price}")
                else:
                    print(f"  Warning: failed to fetch daily K-line for price correction of {cont_code}")
            except Exception as ex:
                print(f"  Error fetching price for {cont_code}: {ex}")
            time.sleep(0.5)
            
    # Calculate Liquidity Metrics
    df['沉淀资金'] = df['持仓量'] * df['最新价'] * df['合约乘数'] * df['做多保证金率']
    df['日成交额'] = df['成交量'] * df['最新价'] * df['合约乘数']
    
    # Identify the main contract for each symbol (by open interest)
    idx = df.groupby('品种代码_upper')['持仓量'].idxmax()
    main_contracts_df = df.loc[idx].copy()
    
    # Apply Liquidity Filter
    active_main_df = main_contracts_df[
        (main_contracts_df['沉淀资金'] >= min_oi_capital) | 
        (main_contracts_df['日成交额'] >= min_turnover)
    ].copy()
    
    print(f"Total listed commodities (excl. CFFEX): {len(main_contracts_df)}, passed liquidity filter: {len(active_main_df)}")
    
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    # First clear old metadata
    cursor.execute("DELETE FROM contract_metadata")
    
    updated_symbols = []
    now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    
    for _, row in active_main_df.iterrows():
        symbol = row['品种代码_upper']
        name = row['品种名称']
        exchange = row['交易所']
        multiplier = float(row['合约乘数'])
        tick_size = float(row['最小跳动'])
        margin_rate = float(row['做多保证金率'])
        current_main = row['合约代码']
        
        # Determine sector and trading hours
        sector = SECTOR_MAP.get(symbol, "其它")
        trading_hours, hours_type = get_trading_hours_info(symbol)
        
        cursor.execute("""
        INSERT OR REPLACE INTO contract_metadata 
        (symbol, name, exchange, multiplier, tick_size, margin_rate, current_main_contract, sector, trading_hours, trading_hours_type, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (symbol, name, exchange, multiplier, tick_size, margin_rate, current_main, sector, trading_hours, hours_type, now_str))
        
        updated_symbols.append({
            'symbol': symbol,
            'name': name,
            'exchange': exchange,
            'multiplier': multiplier,
            'tick_size': tick_size,
            'margin_rate': margin_rate,
            'current_main': current_main,
            'sector': sector,
            'trading_hours': trading_hours,
            'trading_hours_type': hours_type
        })
        
    conn.commit()
    conn.close()
    print(f"Successfully stored metadata for {len(updated_symbols)} active commodity contracts.")
    return updated_symbols

def get_resample_group_label(datetime_str, hours_type):
    # Split datetime into date and time
    parts = str(datetime_str).split(' ')
    date_part = parts[0]
    time_part = parts[1] if len(parts) > 1 else ""
    time_part = time_part.strip()
    
    if hours_type in [1, 2, 3]:
        # Standard commodity times
        if time_part in ['09:00:00', '10:00:00', '11:15:00']:
            return f"{date_part} 11:15:00"
        elif time_part in ['13:30:00', '14:15:00', '15:00:00']:
            return f"{date_part} 15:00:00"
        elif time_part in ['21:00:00', '22:00:00', '23:00:00']:
            return f"{date_part} 23:00:00"
        elif time_part in ['00:00:00', '01:00:00']:
            return f"{date_part} 01:00:00"
        else:
            return f"{date_part} {time_part}"
            
    elif hours_type == 4:
        # Type 4: Precious metals & Crude oil (with 5 trading sessions grouped into 5 bars)
        if time_part in ['21:00:00', '22:00:00', '23:00:00']:
            return f"{date_part} 23:00:00"
        elif time_part in ['00:00:00', '01:00:00']:
            return f"{date_part} 01:00:00"
        elif time_part in ['02:00:00', '09:30:00']:
            return f"{date_part} 09:30:00"
        elif time_part in ['10:45:00', '13:45:00']:
            return f"{date_part} 13:45:00"
        elif time_part in ['14:45:00', '15:00:00']:
            return f"{date_part} 15:00:00"
        else:
            return f"{date_part} {time_part}"
    else:
        return f"{date_part} {time_part}"

def resample_60m_to_2h(df_60m, hours_type):
    """
    Resample 60-minute K-lines to 2-hour K-lines using robust rule-based session grouping.
    - hours_type: 1, 2, 3, or 4
    """
    if df_60m.empty:
        return pd.DataFrame()
        
    df = df_60m.copy()
    df['group_label'] = df['datetime'].apply(lambda x: get_resample_group_label(x, hours_type))
    
    res = df.groupby('group_label').agg({
        'open': 'first',
        'high': 'max',
        'low': 'min',
        'close': 'last',
        'volume': 'sum',
        'hold': 'last'
    }).reset_index()
    
    res.rename(columns={'group_label': 'datetime', 'hold': 'open_interest'}, inplace=True)
    res = res.sort_values('datetime').reset_index(drop=True)
    return res

def expand_czce_contract(contract, exchange):
    """
    Convert CZCE contract code (like SR609) to Sina format with 4-digit year (like SR2609).
    """
    if exchange != 'CZCE':
        return contract
        
    import re
    m = re.search(r'([A-Za-z]+)(\d{3})$', contract)
    if not m:
        return contract
        
    symbol = m.group(1)
    digits = m.group(2) # e.g. "609"
    
    year_digit = int(digits[0]) # e.g. 6
    month_digits = digits[1:]   # e.g. "09"
    
    current_year = datetime.datetime.now().year # e.g. 2026
    current_year_last_digit = current_year % 10 # e.g. 6
    current_decade = (current_year // 10) * 10  # e.g. 2020
    
    if year_digit >= current_year_last_digit - 2:
        year = current_decade + year_digit
    else:
        year = current_decade + 10 + year_digit
        
    return f"{symbol.upper()}{str(year)[2:]}{month_digits}"

def fetch_and_save_daily(symbol, contract, db_path=DEFAULT_DB_PATH, start_date="20250101", exchange=None):
    """
    Fetch daily K-line for a specific contract and save to kline_daily.
    """
    is_continuous = 1 if contract.upper() == symbol.upper() + '0' else 0
    api_symbol = contract.upper()
    
    # Prepend year digits for CZCE actual main contracts (e.g. SR609 -> SR2609)
    if not is_continuous and exchange == 'CZCE':
        api_symbol = expand_czce_contract(api_symbol, exchange)
            
    try:
        df = ak.futures_main_sina(symbol=api_symbol, start_date=start_date)
        if df is None or df.empty:
            return False
            
        # Positional column renaming to avoid character encoding mismatches
        df.columns = ['date', 'open', 'high', 'low', 'close', 'volume', 'open_interest', 'settlement'][:len(df.columns)]
        
        df['open'] = df['open'].astype(float)
        df['high'] = df['high'].astype(float)
        df['low'] = df['low'].astype(float)
        df['close'] = df['close'].astype(float)
        df['volume'] = df['volume'].astype(float)
        df['open_interest'] = df['open_interest'].astype(float)
        if 'settlement' in df.columns:
            df['settlement'] = df['settlement'].astype(float)
        else:
            df['settlement'] = None
            
        df['symbol'] = symbol.upper()
        df['contract'] = contract.lower()
        df['is_continuous'] = is_continuous
        
        conn = sqlite3.connect(db_path)
        df.to_sql('temp_daily', conn, if_exists='replace', index=False)
        
        cursor = conn.cursor()
        cursor.execute("""
        INSERT OR REPLACE INTO kline_daily 
        (symbol, contract, date, open, high, low, close, volume, open_interest, settlement, is_continuous)
        SELECT symbol, contract, date, open, high, low, close, volume, open_interest, settlement, is_continuous
        FROM temp_daily
        """)
        cursor.execute("DROP TABLE temp_daily")
        conn.commit()
        conn.close()
        return True
    except Exception as e:
        print(f"Error fetching daily K-line for {contract} (API Symbol: {api_symbol}): {e}")
        return False

def fetch_and_save_2h(symbol, contract, db_path=DEFAULT_DB_PATH, exchange=None):
    """
    Fetch 60-minute K-line, resample to 2-hour, and save to kline_2h.
    """
    is_continuous = 1 if contract.upper() == symbol.upper() + '0' else 0
    api_symbol = contract.upper()
    
    # Prepend year digits for CZCE actual main contracts (e.g. SR609 -> SR2609)
    if not is_continuous and exchange == 'CZCE':
        api_symbol = expand_czce_contract(api_symbol, exchange)
            
    try:
        df_60m = ak.futures_zh_minute_sina(symbol=api_symbol, period="60")
        if df_60m is None or df_60m.empty:
            return False
            
        # Get hours_type using get_trading_hours_info
        _, hours_type = get_trading_hours_info(symbol)
        df_2h = resample_60m_to_2h(df_60m, hours_type)
        if df_2h.empty:
            return False
            
        df_2h['symbol'] = symbol.upper()
        df_2h['contract'] = contract.lower()
        df_2h['is_continuous'] = is_continuous
        
        conn = sqlite3.connect(db_path)
        df_2h.to_sql('temp_2h', conn, if_exists='replace', index=False)
        
        cursor = conn.cursor()
        cursor.execute("""
        INSERT OR REPLACE INTO kline_2h 
        (symbol, contract, datetime, open, high, low, close, volume, open_interest, is_continuous)
        SELECT symbol, contract, datetime, open, high, low, close, volume, open_interest, is_continuous
        FROM temp_2h
        """)
        cursor.execute("DROP TABLE temp_2h")
        conn.commit()
        conn.close()
        return True
    except Exception as e:
        print(f"Error fetching 2h K-line for {contract}: {e}")
        return False

def sync_data(db_path=DEFAULT_DB_PATH, start_date="20250101", target_symbols=None, min_oi_capital=50000000, min_turnover=100000000, recreate_db=False, sync_all_2h=False):
    """
    Sync K-lines for active commodity futures.
    - If target_symbols is provided, syncs only those (must still pass liquidity filter or be in metadata).
    - Otherwise, automatically syncs all commodities stored in contract_metadata (i.e. those passing the liquidity filter).
    - Continuous contract codes are constructed as SYMBOL + '0' (e.g. RB → RB0).
    """
    # Initialize DB
    init_db(db_path, recreate=recreate_db)
    
    # 1. Update metadata and filter liquid active contracts
    active_meta = update_metadata(db_path, min_oi_capital, min_turnover)
    if not active_meta:
        print("No active symbols found after liquidity filtering. Aborting sync.")
        return
        
    meta_map = {item['symbol']: item for item in active_meta}
    
    # 2. Build sync list from metadata
    if target_symbols:
        sync_list = [m for m in active_meta if m['symbol'] in target_symbols]
        if not sync_list:
            print(f"None of {target_symbols} found in active metadata. Aborting.")
            return
    else:
        sync_list = [m for m in active_meta if m['exchange'] != 'CFFEX']
    
    print(f"\nWill sync {len(sync_list)} commodity symbols (Daily K-lines).")
    print("For 2H K-lines, we will sync only the 4 representative hour types unless sync_all_2h is True.")
    
    count = 0
    t0 = time.time()
    
    for item in sync_list:
        symbol = item['symbol']           # e.g. "RB"
        name = item['name']               # e.g. "螺纹钢"
        actual_main = item['current_main'] # e.g. "rb2610"
        continuous_code = symbol + '0'     # e.g. "RB0" for Sina continuous contract
        exchange = item['exchange']       # e.g. "CZCE"
        
        print(f"\n[{count+1}/{len(sync_list)}] Syncing {symbol} ({name}) | Sector: {item['sector']}")
        
        # A. Fetch Continuous Daily K-line (e.g. RB0)
        success_daily_cont = fetch_and_save_daily(symbol, continuous_code, db_path, start_date, exchange)
        print(f"  Continuous Daily ({continuous_code}): {'OK' if success_daily_cont else 'FAILED'}")
        
        # B. Fetch Continuous 2h K-line (restricted to test list or sync_all_2h)
        if sync_all_2h or symbol in ['LC', 'RB', 'CU', 'SC']:
            success_2h_cont = fetch_and_save_2h(symbol, continuous_code, db_path, exchange)
            print(f"  Continuous 2-Hour ({continuous_code}): {'OK' if success_2h_cont else 'FAILED'}")
        else:
            print(f"  Continuous 2-Hour ({continuous_code}): SKIPPED (not in 2H test list)")
            
        # C. Fetch Current Actual Main Contract Daily & 2h K-lines (e.g. rb2610)
        print(f"  Current Main Contract: {actual_main}")
        
        success_daily_main = fetch_and_save_daily(symbol, actual_main, db_path, start_date, exchange)
        print(f"  Main Contract Daily ({actual_main}): {'OK' if success_daily_main else 'FAILED'}")
        
        if sync_all_2h or symbol in ['LC', 'RB', 'CU', 'SC']:
            success_2h_main = fetch_and_save_2h(symbol, actual_main, db_path, exchange)
            print(f"  Main Contract 2-Hour ({actual_main}): {'OK' if success_2h_main else 'FAILED'}")
        else:
            print(f"  Main Contract 2-Hour ({actual_main}): SKIPPED (not in 2H test list)")
            
        count += 1
        time.sleep(0.5) # Anti-rate limiting delay
        
    elapsed = time.time() - t0
    print(f"\nSync complete. Synced {count} active commodity symbols in {elapsed:.1f}s ({elapsed/60:.1f}min).")

if __name__ == "__main__":
    # Run full sync: fetch Daily K-lines for all active commodities across the 8 sectors, 
    # but limit 2H sync to the 4 hours types (LC, RB, CU, SC) for testing.
    print("Running full Daily sync (all sectors) and 2H test sync for representative types...")
    sync_data(DEFAULT_DB_PATH, start_date="20251101", target_symbols=None, recreate_db=True, sync_all_2h=False)


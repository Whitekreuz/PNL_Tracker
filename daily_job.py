import os
import sqlite3
import pandas as pd
from datetime import datetime
import sys

# Ensure local imports work regardless of cwd
sys.path.append(r"d:\datasci\PNL日志")
from data_fetcher import sync_data
from market_reviewer import MarketReviewer

BASE_DIR = r"d:\datasci\PNL日志"
DB_PATH = os.path.join(BASE_DIR, "futures_data.db")
REPORTS_DIR = os.path.join(BASE_DIR, "reports")

def generate_html_report():
    print("Generating HTML report...")
    reviewer = MarketReviewer(DB_PATH)
    
    flow_res = reviewer.calculate_capital_flow()
    rps_res = reviewer.calculate_rps(periods=[20, 60])
    sector_indices = reviewer.generate_sector_indices(start_date='20250101')
    
    conn = sqlite3.connect(DB_PATH)
    dates = pd.read_sql("SELECT DISTINCT date FROM kline_daily ORDER BY date DESC LIMIT 15", conn)['date'].tolist()
    t10_date = dates[10] if len(dates) > 10 else dates[-1]
    
    rps_res_t10 = reviewer.calculate_rps(periods=[20, 60], target_date=t10_date)
    
    query_10d = f"SELECT symbol, date, open_interest, settlement FROM kline_daily WHERE is_continuous=1 AND date >= '{t10_date}' ORDER BY symbol, date"
    df_10d = pd.read_sql(query_10d, conn)
    conn.close()
    
    df_10d['prev_oi'] = df_10d.groupby('symbol')['open_interest'].shift(1)
    df_10d['delta_oi'] = df_10d['open_interest'] - df_10d['prev_oi']
    df_10d['multiplier'] = df_10d['symbol'].map(lambda x: float(reviewer._metadata_cache.loc[x, 'contract_multiplier']) if x in reviewer._metadata_cache.index else 10.0)
    df_10d['capital_flow'] = df_10d['delta_oi'] * df_10d['settlement'] * df_10d['multiplier']
    df_10d['sector'] = df_10d['symbol'].map(lambda x: reviewer._metadata_cache.loc[x, 'sector'] if x in reviewer._metadata_cache.index else '未知')
    
    flow_10d_sector = df_10d.groupby('sector')['capital_flow'].sum().reset_index()
    total_abs_flow_10d = flow_10d_sector['capital_flow'].abs().sum()
    flow_10d_sector['flow_ratio_10d'] = flow_10d_sector['capital_flow'] / total_abs_flow_10d if total_abs_flow_10d > 0 else 0
    
    symbol_rps_now = rps_res.get('symbol_rps', pd.DataFrame())
    symbol_rps_t10 = rps_res_t10.get('symbol_rps', pd.DataFrame())
    if not symbol_rps_t10.empty and 'RPS_20' in symbol_rps_t10.columns:
        symbol_rps_now['RPS_20_t10'] = symbol_rps_now.index.map(lambda x: symbol_rps_t10.loc[x, 'RPS_20'] if x in symbol_rps_t10.index else symbol_rps_now.loc[x, 'RPS_20'])
    else:
        symbol_rps_now['RPS_20_t10'] = symbol_rps_now['RPS_20']
    symbol_rps_now['RPS_Change_10d'] = symbol_rps_now['RPS_20'] - symbol_rps_now['RPS_20_t10']
    
    sector_rps_now = rps_res.get('sector_rps', pd.DataFrame())
    sector_rps_t10 = rps_res_t10.get('sector_rps', pd.DataFrame())
    if not sector_rps_now.empty and not sector_rps_t10.empty:
        sector_rps_now['RPS_20_t10'] = sector_rps_now.index.map(lambda x: sector_rps_t10.loc[x, 'RPS_20'] if x in sector_rps_t10.index else sector_rps_now.loc[x, 'RPS_20'])
        sector_rps_now['RPS_Change_10d'] = sector_rps_now['RPS_20'] - sector_rps_now['RPS_20_t10']
        sector_summary = pd.merge(sector_rps_now.reset_index().rename(columns={'index': 'sector'}), flow_10d_sector, on='sector', how='left')
    else:
        sector_summary = flow_10d_sector
        
    top10_long = symbol_rps_now.sort_values(by='RPS_20', ascending=False).head(10)[['RPS_20', 'RPS_Change_10d', 'Return_20', 'sector']]
    top10_short = symbol_rps_now.sort_values(by='RPS_20', ascending=True).head(10)[['RPS_20', 'RPS_Change_10d', 'Return_20', 'sector']]
    
    def format_rps(x): return f"{x:.1f}"
    def format_rps_change(x): return f"{x:+.1f}"
    def format_ret(x): return f"{x:.2%}"
    
    long_html = top10_long.style.format({'RPS_20': format_rps, 'RPS_Change_10d': format_rps_change, 'Return_20': format_ret}).set_table_attributes('class="data-table"').to_html()
    short_html = top10_short.style.format({'RPS_20': format_rps, 'RPS_Change_10d': format_rps_change, 'Return_20': format_ret}).set_table_attributes('class="data-table"').to_html()
    
    if 'RPS_20' in sector_summary.columns:
        sec_sum_disp = sector_summary[['sector', 'RPS_20', 'RPS_Change_10d', 'capital_flow', 'flow_ratio_10d']].sort_values(by='RPS_20', ascending=False)
        sec_sum_html = sec_sum_disp.style.format({'RPS_20': format_rps, 'RPS_Change_10d': format_rps_change, 'capital_flow': '{:,.0f}', 'flow_ratio_10d': '{:.2%}'}).set_table_attributes('class="data-table"').to_html()
    else:
        sec_sum_html = "<p>N/A</p>"

    # Heatmap
    sec_df_list_hm = []
    for sec, s_data in sector_indices.items():
        s_data = s_data.copy()
        sec_df_list_hm.append(s_data[['nw_index']].rename(columns={'nw_index': sec}))
        
    sector_pivot_hm = pd.concat(sec_df_list_hm, axis=1).ffill().dropna()
    returns_20_hm = sector_pivot_hm.pct_change(periods=20).dropna()
    last_10_returns_hm = returns_20_hm.tail(10)
    ranks_hm = last_10_returns_hm.rank(axis=1, ascending=True)
    n_sectors_hm = sector_pivot_hm.shape[1]
    rps_10d_history_hm = (ranks_hm - 1.0) / (n_sectors_hm - 1.0) * 100.0
    
    rps_heatmap_df = rps_10d_history_hm.T
    rps_heatmap_df = rps_heatmap_df.sort_values(by=rps_heatmap_df.columns[-1], ascending=False)
    
    if isinstance(rps_heatmap_df.columns, pd.DatetimeIndex):
        rps_heatmap_df.columns = rps_heatmap_df.columns.strftime('%Y-%m-%d')
    else:
        rps_heatmap_df.columns = [str(c)[:10] for c in rps_heatmap_df.columns]
        
    styled_heatmap = rps_heatmap_df.style.background_gradient(cmap='RdYlGn_r', axis=None, vmin=0, vmax=100).format("{:.1f}").set_table_attributes('class="data-table"')
    heatmap_html = styled_heatmap.to_html()

    today_str = datetime.now().strftime('%Y-%m-%d')
    html_content = f"""
    <!DOCTYPE html>
    <html>
    <head>
    <meta charset="utf-8">
    <title>市场复盘与强弱分析 - {today_str}</title>
    <style>
        body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif; padding: 20px; color: #333; background-color: #f9f9fb; }}
        h1 {{ border-bottom: 2px solid #ddd; padding-bottom: 10px; }}
        h2 {{ margin-top: 30px; color: #1f3a93; border-left: 4px solid #1f3a93; padding-left: 10px; }}
        .data-table {{ border-collapse: collapse; width: 100%; margin-top: 10px; background-color: #fff; box-shadow: 0 1px 3px rgba(0,0,0,0.1); border-radius: 5px; overflow: hidden; }}
        .data-table th, .data-table td {{ border: 1px solid #eee; padding: 10px; text-align: right; }}
        .data-table th {{ background-color: #f0f2f5; font-weight: bold; text-align: center; }}
        .flex-container {{ display: flex; gap: 20px; }}
        .flex-child {{ flex: 1; }}
    </style>
    </head>
    <body>
        <h1>📊 市场复盘每日研报 ({today_str})</h1>
        
        <div class="flex-container">
            <div class="flex-child">
                <h2>🔥 最强多头榜 Top 10</h2>
                {long_html}
            </div>
            <div class="flex-child">
                <h2>🧊 最弱空头榜 Top 10</h2>
                {short_html}
            </div>
        </div>
        
        <h2>📈 各大板块强弱与 10 日资金流占比</h2>
        {sec_sum_html}
        
        <h2>🌡️ 各大板块近 10 个交易日 RPS 变动热力图</h2>
        {heatmap_html}
        
        <p style="margin-top: 50px; font-size: 12px; color: #888;">Report automatically generated by PNL_Engine.</p>
    </body>
    </html>
    """
    
    os.makedirs(REPORTS_DIR, exist_ok=True)
    report_path = os.path.join(REPORTS_DIR, f"daily_report_{today_str}.html")
    with open(report_path, 'w', encoding='utf-8') as f:
        f.write(html_content)
    print(f"Report successfully saved to: {report_path}")

def run_daily_job():
    print(f"[{datetime.now()}] Starting daily sync job...")
    # Sync data first
    sync_data(start_date="20250101", recreate_db=False, sync_all_2h=False)
    # Then generate report
    generate_html_report()
    print(f"[{datetime.now()}] Daily job completed.")

if __name__ == "__main__":
    run_daily_job()

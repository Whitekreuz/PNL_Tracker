import os

def patch_app():
    with open('app.py', 'r', encoding='utf-8') as f:
        content = f.read()

    # 1. Update tab definitions
    old_tabs = 'tab_market, tab_acceleration, tab_single, tab_position, tab_risk = st.tabs(["📊 市场复盘与强弱分析", "⚡ 板块动能加速度分析", "🔍 单品种详细分析", "💰 头寸计算器", "🚨 风控体检单"])'
    new_tabs = 'tab_market, tab_acceleration, tab_capital_flow, tab_single, tab_position, tab_risk = st.tabs(["📊 市场复盘与强弱分析", "⚡ 板块与品种动能加速度分析", "💸 资金流与沉淀资金分析", "🔍 单品种详细分析", "💰 头寸计算器", "🚨 风控体检单"])'
    
    if old_tabs in content:
        content = content.replace(old_tabs, new_tabs)
    else:
        # Fallback in case tabs were already changed
        content = content.replace(
            'tab_market, tab_acceleration, tab_single, tab_position, tab_risk = st.tabs',
            'tab_market, tab_acceleration, tab_capital_flow, tab_single, tab_position, tab_risk = st.tabs'
        )

    # 2. Extract and replace the tab_acceleration block
    target_start = "with tab_acceleration:"
    target_end = 'st.error(f"个股商品动能加速度分析生成失败: {e}")'

    start_idx = content.find(target_start)
    end_idx = content.find(target_end)

    if start_idx == -1 or end_idx == -1:
        print("Could not find start or end index for tab_acceleration replacement.")
        return

    end_idx += len(target_end)

    new_tabs_code = """with tab_acceleration:
    st.header("⚡ 板块与品种动能加速度分析")
    
    # 选项：RPS 周期选择 (1/5/20)
    selected_period = st.radio("选择动能计算周期 (D)：", [1, 5, 20], index=2, horizontal=True)
    
    try:
        # 一次性获取全市场行情与元数据，用于动能与资金流计算
        conn = sqlite3.connect(DB_PATH)
        dates_all = pd.read_sql("SELECT DISTINCT date FROM kline_daily ORDER BY date DESC LIMIT 60", conn)['date'].tolist()
        start_date_all = dates_all[-1] if len(dates_all) > 0 else "2025-01-01"
        
        query_all = \"\"\"
        SELECT k.symbol, k.date, k.close, k.open_interest, k.settlement, m.multiplier, m.margin_rate, m.sector 
        FROM kline_daily k
        LEFT JOIN contract_metadata m ON k.symbol = m.symbol
        WHERE k.is_continuous = 1 AND k.date >= ?
        \"\"\"
        df_all_raw = pd.read_sql(query_all, conn, params=(start_date_all,))
        conn.close()
        
        # 填充元数据默认值，防止部分品种匹配失败
        df_all_raw['sector'] = df_all_raw['sector'].fillna('其他')
        df_all_raw['multiplier'] = df_all_raw['multiplier'].fillna(10.0)
        df_all_raw['margin_rate'] = df_all_raw['margin_rate'].fillna(0.15)
        
        # 计算单品种每日资金流向
        df_all_raw = df_all_raw.sort_values(by=['symbol', 'date'])
        df_all_raw['prev_oi'] = df_all_raw.groupby('symbol')['open_interest'].shift(1)
        df_all_raw['delta_oi'] = df_all_raw['open_interest'] - df_all_raw['prev_oi']
        df_all_raw['capital_flow'] = df_all_raw['delta_oi'] * df_all_raw['settlement'] * df_all_raw['multiplier']
        df_all_raw = df_all_raw.dropna(subset=['prev_oi'])
        
        # 1. 各大板块分析
        sec_df_list_acc = []
        for sec, s_data in sector_indices.items():
            s_data = s_data.copy()
            sec_df_list_acc.append(s_data[['nw_index']].rename(columns={'nw_index': sec}))
        sector_pivot_acc = pd.concat(sec_df_list_acc, axis=1).ffill().dropna()
        
        returns_N_acc = sector_pivot_acc.pct_change(periods=selected_period).dropna()
        last_10_returns_acc = returns_N_acc.tail(10)
        ranks_acc = last_10_returns_acc.rank(axis=1, ascending=True)
        n_sectors_acc = sector_pivot_acc.shape[1]
        rps_10d_history_acc = (ranks_acc - 1.0) / (n_sectors_acc - 1.0) * 100.0
        
        rps_heatmap_acc = rps_10d_history_acc.T
        latest_returns_acc = returns_N_acc.iloc[-1].rename(f'{selected_period}D 收益率')
        
        if rps_heatmap_acc.shape[1] >= 10:
            change_10d_acc = (rps_heatmap_acc[rps_heatmap_acc.columns[-1]] - rps_heatmap_acc[rps_heatmap_acc.columns[0]]).rename('10D 变动')
        else:
            change_10d_acc = pd.Series(0.0, index=rps_heatmap_acc.index, name='10D 变动')
            
        # 计算对应周期内的累计板块资金流
        sector_flow_daily = df_all_raw.groupby(['date', 'sector'])['capital_flow'].sum().reset_index()
        pivot_sector_flow = sector_flow_daily.pivot(index='date', columns='sector', values='capital_flow').ffill().fillna(0.0)
        latest_sector_flow_N = (pivot_sector_flow.tail(selected_period).sum() / 1e8).rename('资金流向 (亿)')
        
        formatted_columns = [str(c)[:10] for c in rps_heatmap_acc.columns]
        rps_heatmap_acc.columns = formatted_columns
        date_cols = list(rps_heatmap_acc.columns)
        
        # 合并板块数据
        display_df = rps_heatmap_acc.join(change_10d_acc).join(latest_returns_acc).join(latest_sector_flow_N)
        display_df = display_df.sort_values(by=date_cols[-1], ascending=False)
        
        format_dict = {
            f'{selected_period}D 收益率': '{:+.2%}',
            '10D 变动': '{:+.1f}',
            '资金流向 (亿)': '{:+.2f} 亿'
        }
        for d_col in date_cols:
            format_dict[d_col] = '{:.1f}'
            
        styled_df = display_df.style.background_gradient(
            cmap='RdYlGn_r', 
            subset=date_cols, 
            vmin=0, 
            vmax=100
        ).format(format_dict)
            
        st.subheader(f"🔥 各大板块近 10 个交易日 RPS_{selected_period} 变动热力图")
        st.dataframe(styled_df, use_container_width=True)
        
        # 2. 个股分析 (多头/空头榜)
        pivot_close_all = df_all_raw.pivot(index='date', columns='symbol', values='close').ffill()
        returns_all = pivot_close_all.pct_change(periods=selected_period).dropna()
        last_10_returns_all = returns_all.tail(10)
        ranks_all = last_10_returns_all.rank(axis=1, ascending=True)
        n_symbols_all = pivot_close_all.shape[1]
        rps_10d_all = (ranks_all - 1.0) / (n_symbols_all - 1.0) * 100.0
        
        # 计算对应周期内的累计个股资金流 (万元)
        pivot_flow_all = df_all_raw.pivot(index='date', columns='symbol', values='capital_flow').ffill().fillna(0.0)
        latest_flow_N_all = (pivot_flow_all.tail(selected_period).sum() / 1e4).rename('资金流向 (万)')
        latest_returns_symbol = returns_all.iloc[-1].rename(f'{selected_period}D 收益率')
        
        latest_rps_all = rps_10d_all.iloc[-1]
        top10_long_symbols = latest_rps_all.sort_values(ascending=False).head(10).index.tolist()
        top10_short_symbols = latest_rps_all.sort_values(ascending=True).head(10).index.tolist()
        
        # 多头榜
        long_hm_df = rps_10d_all[top10_long_symbols].T
        long_hm_df = long_hm_df.sort_values(by=long_hm_df.columns[-1], ascending=False)
        long_hm_df.columns = [str(c)[:10] for c in long_hm_df.columns]
        date_cols_all = list(long_hm_df.columns)
        
        long_display = long_hm_df.join(latest_returns_symbol).join(latest_flow_N_all)
        long_display = long_display.sort_values(by=date_cols_all[-1], ascending=False)
        
        # 空头榜
        short_hm_df = rps_10d_all[top10_short_symbols].T
        short_hm_df = short_hm_df.sort_values(by=short_hm_df.columns[-1], ascending=True)
        short_hm_df.columns = [str(c)[:10] for c in short_hm_df.columns]
        
        short_display = short_hm_df.join(latest_returns_symbol).join(latest_flow_N_all)
        short_display = short_display.sort_values(by=date_cols_all[-1], ascending=True)
        
        format_dict_all = {
            f'{selected_period}D 收益率': '{:+.2%}',
            '资金流向 (万)': '{:+.0f} 万'
        }
        for c in date_cols_all:
            format_dict_all[c] = '{:.1f}'
            
        st.markdown("---")
        st.subheader(f"🔥 最强多头榜 Top 10 品种近 10 个交易日 RPS_{selected_period} 热力图")
        styled_long = long_display.style.background_gradient(
            cmap='RdYlGn_r', subset=date_cols_all, vmin=0, vmax=100
        ).format(format_dict_all)
        st.dataframe(styled_long, use_container_width=True)
        
        st.subheader(f"🧊 最弱空头榜 Top 10 品种近 10 个交易日 RPS_{selected_period} 热力图")
        styled_short = short_display.style.background_gradient(
            cmap='RdYlGn_r', subset=date_cols_all, vmin=0, vmax=100
        ).format(format_dict_all)
        st.dataframe(styled_short, use_container_width=True)
        
    except Exception as e:
        st.error(f"动能加速度分析生成失败: {e}")

# ==========================================
# Tab 1.3: 资金流与沉淀资金分析
# ==========================================
with tab_capital_flow:
    st.header("💸 资金流与沉淀资金分析")
    
    # 选项：计算周期选择 (1/5/20)
    selected_period_flow = st.radio("选择资金流计算周期 (D)：", [1, 5, 20], index=2, horizontal=True, key="flow_period_selector")
    
    try:
        # 重新建立连接，获取足够用于计算 20日 滚动值的行情数据 (需过去 50 天)
        conn = sqlite3.connect(DB_PATH)
        dates_flow = pd.read_sql("SELECT DISTINCT date FROM kline_daily ORDER BY date DESC LIMIT 60", conn)['date'].tolist()
        start_date_flow = dates_flow[-1] if len(dates_flow) > 0 else "2025-01-01"
        
        query_flow = \"\"\"
        SELECT k.symbol, k.date, k.open_interest, k.settlement, m.multiplier, m.margin_rate, m.sector 
        FROM kline_daily k
        LEFT JOIN contract_metadata m ON k.symbol = m.symbol
        WHERE k.is_continuous = 1 AND k.date >= ?
        \"\"\"
        df_flow_raw = pd.read_sql(query_flow, conn, params=(start_date_flow,))
        conn.close()
        
        # 填充元数据默认值
        df_flow_raw['sector'] = df_flow_raw['sector'].fillna('其他')
        df_flow_raw['multiplier'] = df_flow_raw['multiplier'].fillna(10.0)
        df_flow_raw['margin_rate'] = df_flow_raw['margin_rate'].fillna(0.15)
        
        # 1. 计算单品种每日资金流向与持仓沉淀资金
        df_flow_raw = df_flow_raw.sort_values(by=['symbol', 'date'])
        df_flow_raw['prev_oi'] = df_flow_raw.groupby('symbol')['open_interest'].shift(1)
        df_flow_raw['delta_oi'] = df_flow_raw['open_interest'] - df_flow_raw['prev_oi']
        df_flow_raw['capital_flow'] = df_flow_raw['delta_oi'] * df_flow_raw['settlement'] * df_flow_raw['multiplier']
        
        # 资金沉淀 Notional Margin = OI * Settle * Multiplier * MarginRate
        df_flow_raw['oi_capital'] = df_flow_raw['open_interest'] * df_flow_raw['settlement'] * df_flow_raw['multiplier'] * df_flow_raw['margin_rate']
        df_flow_raw = df_flow_raw.dropna(subset=['prev_oi'])
        
        # 宽表化
        pivot_flow_all = df_flow_raw.pivot(index='date', columns='symbol', values='capital_flow').ffill().fillna(0.0)
        pivot_capital_all = df_flow_raw.pivot(index='date', columns='symbol', values='oi_capital').ffill().fillna(0.0)
        
        # 按所选周期计算滚动累计资金流
        rolling_flow_all = pivot_flow_all.rolling(window=selected_period_flow).sum().dropna()
        # 取过去 20 个交易日
        heatmap_flow_all = rolling_flow_all.tail(20)
        
        # 板块每日数据聚合
        sector_daily = df_flow_raw.groupby(['date', 'sector']).agg({'capital_flow': 'sum', 'oi_capital': 'sum'}).reset_index()
        pivot_sector_flow = sector_daily.pivot(index='date', columns='sector', values='capital_flow').ffill().fillna(0.0)
        pivot_sector_capital = sector_daily.pivot(index='date', columns='sector', values='oi_capital').ffill().fillna(0.0)
        
        rolling_sector_flow = pivot_sector_flow.rolling(window=selected_period_flow).sum().dropna()
        heatmap_sector_flow = rolling_sector_flow.tail(20)
        heatmap_sector_capital = pivot_sector_capital.tail(20) # 资金沉淀只显示过去20天的当日水平
        
        # 获取用于个股筛选的 Top 10 (基于当前周期对应的最新一日 RPS)
        # 直接使用全市场最新的 RPS
        conn = sqlite3.connect(DB_PATH)
        # 用前一个计算周期内的收益率计算当前 RPS
        query_close = "SELECT symbol, date, close FROM kline_daily WHERE is_continuous = 1 AND date >= ?"
        df_close = pd.read_sql(query_close, conn, params=(start_date_flow,))
        conn.close()
        pivot_close = df_close.pivot(index='date', columns='symbol', values='close').ffill()
        returns_flow_rps = pivot_close.pct_change(periods=selected_period_flow).dropna()
        latest_returns_flow_rps = returns_flow_rps.iloc[-1]
        ranks_flow_rps = latest_returns_flow_rps.rank(ascending=True)
        rps_flow_rps = (ranks_flow_rps - 1.0) / (pivot_close.shape[1] - 1.0) * 100.0
        
        top10_long_flow = rps_flow_rps.sort_values(ascending=False).head(10).index.tolist()
        top10_short_flow = rps_flow_rps.sort_values(ascending=True).head(10).index.tolist()
        
        # Format Date columns helper
        def format_date_cols(df_hm):
            if isinstance(df_hm.columns, pd.DatetimeIndex):
                df_hm.columns = df_hm.columns.strftime('%Y-%m-%d')
            else:
                df_hm.columns = [str(c)[:10] for c in df_hm.columns]
            return list(df_hm.columns)
            
        # ========================================================
        # 第一部分：累计资金流向 (20日变化, 单位: 亿元)
        # ========================================================
        st.subheader(f"📊 板块 - 近 20 日累计资金流向 (周期: {selected_period_flow}D, 单位: 亿元)")
        sec_flow_hm = (heatmap_sector_flow / 1e8).T
        sec_flow_hm = sec_flow_hm.sort_values(by=sec_flow_hm.columns[-1], ascending=False)
        date_cols_flow = format_date_cols(sec_flow_hm)
        
        styled_sec_flow = sec_flow_hm.style.background_gradient(
            cmap='RdYlGn_r', axis=None
        ).format({c: '{:+.2f} 亿' for c in date_cols_flow})
        st.dataframe(styled_sec_flow, use_container_width=True)
        
        # 个股多头/空头资金流
        st.subheader(f"🔥 最强多头榜 Top 10 品种 - 近 20 日累计资金流向 (周期: {selected_period_flow}D, 单位: 亿元)")
        long_flow_hm = (heatmap_flow_all[top10_long_flow] / 1e8).T
        long_flow_hm = long_flow_hm.sort_values(by=long_flow_hm.columns[-1], ascending=False)
        format_date_cols(long_flow_hm)
        styled_long_flow = long_flow_hm.style.background_gradient(cmap='RdYlGn_r', axis=None).format({c: '{:+.3f} 亿' for c in date_cols_flow})
        st.dataframe(styled_long_flow, use_container_width=True)
        
        st.subheader(f"🧊 最弱空头榜 Top 10 品种 - 近 20 日累计资金流向 (周期: {selected_period_flow}D, 单位: 亿元)")
        short_flow_hm = (heatmap_flow_all[top10_short_flow] / 1e8).T
        short_flow_hm = short_flow_hm.sort_values(by=short_flow_hm.columns[-1], ascending=True)
        format_date_cols(short_flow_hm)
        styled_short_flow = short_flow_hm.style.background_gradient(cmap='RdYlGn_r', axis=None).format({c: '{:+.3f} 亿' for c in date_cols_flow})
        st.dataframe(styled_short_flow, use_container_width=True)
        
        # ========================================================
        # 第二部分：持仓资金沉淀 (20日数值, 单位: 亿元)
        # ========================================================
        st.markdown("---")
        st.subheader("💰 各大板块 - 过去 20 个交易日资金沉淀变化 (单位: 亿元)")
        sec_cap_hm = (heatmap_sector_capital / 1e8).T
        sec_cap_hm = sec_cap_hm.sort_values(by=sec_cap_hm.columns[-1], ascending=False)
        date_cols_cap = format_date_cols(sec_cap_hm)
        
        # 资金沉淀是绝对正值，我们使用 YlOrRd 渐变色，越红代表沉淀规模越大
        styled_sec_cap = sec_cap_hm.style.background_gradient(
            cmap='YlOrRd', axis=None
        ).format({c: '{:,.2f} 亿' for c in date_cols_cap})
        st.dataframe(styled_sec_cap, use_container_width=True)
        
        st.subheader("🔥 最强多头榜 Top 10 品种 - 过去 20 个交易日资金沉淀变化 (单位: 亿元)")
        long_cap_hm = (heatmap_capital_all[top10_long_flow] / 1e8).T
        long_cap_hm = long_cap_hm.sort_values(by=long_cap_hm.columns[-1], ascending=False)
        format_date_cols(long_cap_hm)
        styled_long_cap = long_cap_hm.style.background_gradient(cmap='YlOrRd', axis=None).format({c: '{:,.3f} 亿' for c in date_cols_cap})
        st.dataframe(styled_long_cap, use_container_width=True)
        
        st.subheader("🧊 最弱空头榜 Top 10 品种 - 过去 20 个交易日资金沉淀变化 (单位: 亿元)")
        short_cap_hm = (heatmap_capital_all[top10_short_flow] / 1e8).T
        short_cap_hm = short_cap_hm.sort_values(by=short_cap_hm.columns[-1], ascending=False)
        format_date_cols(short_cap_hm)
        styled_short_cap = short_cap_hm.style.background_gradient(cmap='YlOrRd', axis=None).format({c: '{:,.3f} 亿' for c in date_cols_cap})
        st.dataframe(styled_short_cap, use_container_width=True)
        
    except Exception as e:
        st.error(f"资金流向与沉淀资金分析生成失败: {e}")"""

    # Inject the modified code
    patched_content = content[:start_idx] + new_tabs_code + content[end_idx:]

    with open('app.py', 'w', encoding='utf-8') as f:
        f.write(patched_content)
        
    print("Tab 1.2 and 1.3 patched successfully.")

if __name__ == "__main__":
    patch_app()

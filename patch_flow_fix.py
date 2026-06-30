import os

def patch_app():
    with open('app.py', 'r', encoding='utf-8') as f:
        content = f.read()

    # Define the replacement block for Tab 1.3
    # We will locate 'with tab_capital_flow:' and replace it up to the next tab
    target_start = "with tab_capital_flow:"
    target_end = 'st.error(f"资金流向与沉淀资金分析生成失败: {e}")'

    start_idx = content.find(target_start)
    end_idx = content.find(target_end)

    if start_idx == -1 or end_idx == -1:
        print("Could not find start or end index for tab_capital_flow replacement.")
        return

    end_idx += len(target_end)

    new_tab_code = """with tab_capital_flow:
    st.header("💸 资金流与沉淀资金分析")
    
    # 选项：计算周期选择 (1/5/20)
    selected_period_flow = st.radio("选择资金流向计算周期 (D)：", [1, 5, 20], index=2, horizontal=True, key="flow_period_selector")
    
    try:
        # 获取足够用于计算滚动累计值的行情数据 (需要 60 天)
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
        # 取过去 10 个交易日
        heatmap_flow_all = rolling_flow_all.tail(10)
        heatmap_capital_all = pivot_capital_all.tail(10) # 修复：定义各品种资金沉淀历史并取10天
        
        # 板块每日数据聚合
        sector_daily = df_flow_raw.groupby(['date', 'sector']).agg({'capital_flow': 'sum', 'oi_capital': 'sum'}).reset_index()
        pivot_sector_flow = sector_daily.pivot(index='date', columns='sector', values='capital_flow').ffill().fillna(0.0)
        pivot_sector_capital = sector_daily.pivot(index='date', columns='sector', values='oi_capital').ffill().fillna(0.0)
        
        rolling_sector_flow = pivot_sector_flow.rolling(window=selected_period_flow).sum().dropna()
        heatmap_sector_flow = rolling_sector_flow.tail(10)
        heatmap_sector_capital = pivot_sector_capital.tail(10) # 资金沉淀只显示过去 10 天的当日水平
        
        # 获取用于个股筛选的 Top 10 (基于当前周期对应的最新一日 RPS)
        conn = sqlite3.connect(DB_PATH)
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
        # 第一部分：累计资金流向 (10日变化, 单位: 亿元)
        # ========================================================
        st.subheader(f"📊 板块 - 近 10 日累计资金流向 (周期: {selected_period_flow}D, 单位: 亿元)")
        sec_flow_hm = (heatmap_sector_flow / 1e8).T
        sec_flow_hm = sec_flow_hm.sort_values(by=sec_flow_hm.columns[-1], ascending=False)
        date_cols_flow = format_date_cols(sec_flow_hm)
        
        styled_sec_flow = sec_flow_hm.style.background_gradient(
            cmap='RdYlGn_r', axis=None
        ).format({c: '{:+.2f} 亿' for c in date_cols_flow})
        st.dataframe(styled_sec_flow, use_container_width=True)
        
        # 个股多头/空头资金流
        st.subheader(f"🔥 最强多头榜 Top 10 品种 - 近 10 日累计资金流向 (周期: {selected_period_flow}D, 单位: 亿元)")
        long_flow_hm = (heatmap_flow_all[top10_long_flow] / 1e8).T
        long_flow_hm = long_flow_hm.sort_values(by=long_flow_hm.columns[-1], ascending=False)
        format_date_cols(long_flow_hm)
        styled_long_flow = long_flow_hm.style.background_gradient(cmap='RdYlGn_r', axis=None).format({c: '{:+.3f} 亿' for c in date_cols_flow})
        st.dataframe(styled_long_flow, use_container_width=True)
        
        st.subheader(f"🧊 最弱空头榜 Top 10 品种 - 近 10 日累计资金流向 (周期: {selected_period_flow}D, 单位: 亿元)")
        short_flow_hm = (heatmap_flow_all[top10_short_flow] / 1e8).T
        short_flow_hm = short_flow_hm.sort_values(by=short_flow_hm.columns[-1], ascending=True)
        format_date_cols(short_flow_hm)
        styled_short_flow = short_flow_hm.style.background_gradient(cmap='RdYlGn_r', axis=None).format({c: '{:+.3f} 亿' for c in date_cols_flow})
        st.dataframe(styled_short_flow, use_container_width=True)
        
        # ========================================================
        # 第二部分：持仓资金沉淀 (10日数值, 单位: 亿元)
        # ========================================================
        st.markdown("---")
        st.subheader("💰 各大板块 - 过去 10 个交易日资金沉淀变化 (单位: 亿元)")
        sec_cap_hm = (heatmap_sector_capital / 1e8).T
        sec_cap_hm = sec_cap_hm.sort_values(by=sec_cap_hm.columns[-1], ascending=False)
        date_cols_cap = format_date_cols(sec_cap_hm)
        
        styled_sec_cap = sec_cap_hm.style.background_gradient(
            cmap='YlOrRd', axis=None
        ).format({c: '{:,.2f} 亿' for c in date_cols_cap})
        st.dataframe(styled_sec_cap, use_container_width=True)
        
        st.subheader("🔥 最强多头榜 Top 10 品种 - 过去 10 个交易日资金沉淀变化 (单位: 亿元)")
        long_cap_hm = (heatmap_capital_all[top10_long_flow] / 1e8).T
        long_cap_hm = long_cap_hm.sort_values(by=long_cap_hm.columns[-1], ascending=False)
        format_date_cols(long_cap_hm)
        styled_long_cap = long_cap_hm.style.background_gradient(cmap='YlOrRd', axis=None).format({c: '{:,.3f} 亿' for c in date_cols_cap})
        st.dataframe(styled_long_cap, use_container_width=True)
        
        st.subheader("🧊 最弱空头榜 Top 10 品种 - 过去 10 个交易日资金沉淀变化 (单位: 亿元)")
        short_cap_hm = (heatmap_capital_all[top10_short_flow] / 1e8).T
        short_cap_hm = short_cap_hm.sort_values(by=short_cap_hm.columns[-1], ascending=False)
        format_date_cols(short_cap_hm)
        styled_short_cap = short_cap_hm.style.background_gradient(cmap='YlOrRd', axis=None).format({c: '{:,.3f} 亿' for c in date_cols_cap})
        st.dataframe(styled_short_cap, use_container_width=True)
        
    except Exception as e:
        st.error(f"资金流向与沉淀资金分析生成失败: {e}")"""

    patched_content = content[:start_idx] + new_tab_code + content[end_idx:]

    with open('app.py', 'w', encoding='utf-8') as f:
        f.write(patched_content)
        
    print("Tab 1.3 optimized successfully.")

if __name__ == "__main__":
    patch_app()

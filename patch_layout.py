import os

def patch_app():
    with open('app.py', 'r', encoding='utf-8') as f:
        content = f.read()

    # Replacement 1: Sidebar removal and tab definitions
    old_sidebar_tab = """# --- 侧边栏：全局风控中枢 ---
st.sidebar.header("⚙️ 全局风控中枢")
st.sidebar.markdown("---")

drawdown_limit = st.sidebar.number_input("最大回撤容忍度 (RMB)", value=200000.0, step=10000.0)
risk_factor = st.sidebar.slider("风险乘数因子 (k)", min_value=0.01, max_value=0.20, value=0.075, step=0.005)
cppi_m = st.sidebar.number_input("CPPI 乘数 (M)", value=1.0, min_value=0.1, max_value=5.0, step=0.1)

# 计算全局目标 VaR
target_var = pos_calc.calculate_target_var(drawdown_limit, risk_factor, cppi_m)

st.sidebar.markdown("---")
st.sidebar.metric(label="🎯 组合目标 VaR 限额", value=f"¥ {target_var:,.0f}")
st.sidebar.caption("当日全市场最大允许的 99% VaR 波动敞口。")

# --- 主页面 Tabs ---
tab_market, tab_acceleration, tab_capital_flow, tab_single, tab_position, tab_risk = st.tabs(["📊 市场复盘与强弱分析", "⚡ 板块与品种动能加速度分析", "💸 资金流与沉淀资金分析", "🔍 单品种详细分析", "💰 头寸计算器", "🚨 风控体检单"])"""

    new_sidebar_tab = """# --- 主页面 Tabs ---
tab_market, tab_acceleration, tab_capital_flow, tab_single, tab_var_risk = st.tabs([
    "📊 市场复盘与强弱分析", 
    "⚡ 板块与品种动能加速度分析", 
    "💸 资金流与沉淀资金分析", 
    "🔍 单品种详细分析", 
    "🛡️ VaR风控管理"
])"""

    content = content.replace(old_sidebar_tab, new_sidebar_tab)

    # Replacement 2: Single Commodity tab adjustments for RPS_5
    old_single_calc = """                    # 我们需要获取全市场近 80 天的收盘价，以便计算 60 天内的每日 RPS_20
                    dates_80 = pd.read_sql("SELECT DISTINCT date FROM kline_daily ORDER BY date DESC LIMIT 81", conn)['date'].tolist()
                    if len(dates_80) >= 21:
                        start_date_80 = dates_80[-1]
                        
                        # 取全市场计算 RPS
                        query_all = f"SELECT symbol, date, close FROM kline_daily WHERE is_continuous=1 AND date >= '{start_date_80}'"
                        df_all = pd.read_sql(query_all, conn)
                        
                        pivot_close = df_all.pivot(index='date', columns='symbol', values='close').ffill()
                        returns_20 = pivot_close.pct_change(periods=20).dropna()
                        
                        ranks = returns_20.rank(axis=1, ascending=True)
                        n_symbols = pivot_close.shape[1]
                        rps_history = (ranks - 1.0) / (n_symbols - 1.0) * 100.0
                        
                        # 取选定品种的 RPS
                        if selected_symbol in rps_history.columns:
                            symbol_rps = rps_history[selected_symbol]
                        else:
                            symbol_rps = pd.Series(dtype=float)"""

    new_single_calc = """                    # 我们需要获取全市场近 80 天的收盘价，以便计算 60 天内的每日 RPS_5
                    dates_80 = pd.read_sql("SELECT DISTINCT date FROM kline_daily ORDER BY date DESC LIMIT 81", conn)['date'].tolist()
                    if len(dates_80) >= 21:
                        start_date_80 = dates_80[-1]
                        
                        # 取全市场计算 RPS_5
                        query_all = f"SELECT symbol, date, close FROM kline_daily WHERE is_continuous=1 AND date >= '{start_date_80}'"
                        df_all = pd.read_sql(query_all, conn)
                        
                        pivot_close = df_all.pivot(index='date', columns='symbol', values='close').ffill()
                        returns_5 = pivot_close.pct_change(periods=5).dropna()
                        
                        ranks = returns_5.rank(axis=1, ascending=True)
                        n_symbols = pivot_close.shape[1]
                        rps_history = (ranks - 1.0) / (n_symbols - 1.0) * 100.0
                        
                        # 取选定品种的 RPS_5
                        if selected_symbol in rps_history.columns:
                            symbol_rps = rps_history[selected_symbol]
                        else:
                            symbol_rps = pd.Series(dtype=float)"""

    content = content.replace(old_single_calc, new_single_calc)

    # Replace merges
    content = content.replace("df_single['rps_20'] = symbol_rps", "df_single['rps_5'] = symbol_rps")
    
    # Replace candlestick subplot trace
    old_subplot_trace = """                            # 4. RPS 20 日动能变化 (Row 4)
                            fig.add_trace(go.Scatter(
                                x=df_single.index, y=df_single['rps_20'],
                                name="RPS 20", line=dict(color='purple', width=2),
                                mode='lines+markers'
                            ), row=4, col=1)"""
                            
    new_subplot_trace = """                            # 4. RPS 5 日动能变化 (Row 4)
                            fig.add_trace(go.Scatter(
                                x=df_single.index, y=df_single['rps_5'],
                                name="RPS 5", line=dict(color='purple', width=2),
                                mode='lines+markers'
                            ), row=4, col=1)"""
    content = content.replace(old_subplot_trace, new_subplot_trace)

    # Replace layout titles
    content = content.replace(
        "title=f\"{selected_symbol} 过去 60 日详细复盘 (价格/量仓/资金/RPS)\"",
        "title=f\"{selected_symbol} 过去 60 日详细复盘 (价格/量仓/资金/RPS 5)\""
    )
    content = content.replace(
        'fig.update_yaxes(title_text="RPS (0-100)", range=[0, 100], row=4, col=1)',
        'fig.update_yaxes(title_text="RPS 5 (0-100)", range=[0, 100], row=4, col=1)'
    )

    # Replace single tab heatmaps at the bottom
    old_single_heatmaps = """                            # ======= 新增：板块及内部品种 20 日 RPS 热力图 =======
                            
                            # 1. 板块 RPS 热力图
                            sector_indices_all = reviewer.generate_sector_indices(start_date='20250101')
                            if sector_indices_all:
                                sec_df_list = []
                                for sec, s_data in sector_indices_all.items():
                                    sec_df_list.append(s_data[['nw_index']].rename(columns={'nw_index': sec}))
                                sector_pivot = pd.concat(sec_df_list, axis=1).ffill().dropna()
                                returns_20_sec = sector_pivot.pct_change(periods=20).dropna()
                                last_20_returns_sec = returns_20_sec.tail(20)
                                ranks_sec = last_20_returns_sec.rank(axis=1, ascending=True)
                                rps_20d_history_sec = (ranks_sec - 1.0) / (sector_pivot.shape[1] - 1.0) * 100.0
                                
                                if selected_sector in rps_20d_history_sec.columns:
                                    sec_rps_heatmap = rps_20d_history_sec[[selected_sector]].T
                                    sec_rps_heatmap.columns = [str(c)[:10] for c in sec_rps_heatmap.columns]
                                    
                                    st.subheader(f"🔥 {selected_sector}板块整体 - 近 20 个交易日 RPS 热力图")
                                    st.dataframe(sec_rps_heatmap.style.background_gradient(cmap='RdYlGn_r', axis=None, vmin=0, vmax=100).format("{:.1f}"), use_container_width=True)
                                    
                            # 2. 板块内各品种 RPS 热力图
                            rps_history_20d = rps_history.tail(20)
                            symbols_to_plot = [s for s in symbols_in_sector if s in rps_history_20d.columns]
                            if symbols_to_plot:
                                sym_rps_heatmap = rps_history_20d[symbols_to_plot].T
                                # 按最新一天的分数降序排列
                                sym_rps_heatmap = sym_rps_heatmap.sort_values(by=sym_rps_heatmap.columns[-1], ascending=False)
                                sym_rps_heatmap.columns = [str(c)[:10] for c in sym_rps_heatmap.columns]
                                
                                st.subheader(f"📊 {selected_sector}板块内所有品种 - 近 20 个交易日 RPS 热力图")
                                st.dataframe(sym_rps_heatmap.style.background_gradient(cmap='RdYlGn_r', axis=None, vmin=0, vmax=100).format("{:.1f}"), height=(len(symbols_to_plot) * 35 + 40), use_container_width=True)"""

    new_single_heatmaps = """                            # ======= 新增：板块及内部品种 10 个交易日 RPS_5 热力图 =======
                            
                            # 1. 板块 RPS_5 热力图
                            sector_indices_all = reviewer.generate_sector_indices(start_date='20250101')
                            if sector_indices_all:
                                sec_df_list = []
                                for sec, s_data in sector_indices_all.items():
                                    sec_df_list.append(s_data[['nw_index']].rename(columns={'nw_index': sec}))
                                sector_pivot = pd.concat(sec_df_list, axis=1).ffill().dropna()
                                returns_5_sec = sector_pivot.pct_change(periods=5).dropna()
                                last_10_returns_sec = returns_5_sec.tail(10)
                                ranks_sec = last_10_returns_sec.rank(axis=1, ascending=True)
                                rps_5d_history_sec = (ranks_sec - 1.0) / (sector_pivot.shape[1] - 1.0) * 100.0
                                
                                if selected_sector in rps_5d_history_sec.columns:
                                    sec_rps_heatmap = rps_5d_history_sec[[selected_sector]].T
                                    sec_rps_heatmap.columns = [str(c)[:10] for c in sec_rps_heatmap.columns]
                                    
                                    st.subheader(f"🔥 {selected_sector}板块整体 - 近 10 个交易日 RPS_5 热力图")
                                    st.dataframe(sec_rps_heatmap.style.background_gradient(cmap='RdYlGn_r', axis=None, vmin=0, vmax=100).format("{:.1f}"), use_container_width=True)
                                    
                            # 2. 板块内各品种 RPS_5 热力图
                            rps_history_10d = rps_history.tail(10)
                            symbols_to_plot = [s for s in symbols_in_sector if s in rps_history_10d.columns]
                            if symbols_to_plot:
                                sym_rps_heatmap = rps_history_10d[symbols_to_plot].T
                                # 按最新一天的分数降序排列
                                sym_rps_heatmap = sym_rps_heatmap.sort_values(by=sym_rps_heatmap.columns[-1], ascending=False)
                                sym_rps_heatmap.columns = [str(c)[:10] for c in sym_rps_heatmap.columns]
                                
                                st.subheader(f"📊 {selected_sector}板块内所有品种 - 近 10 个交易日 RPS_5 热力图")
                                st.dataframe(sym_rps_heatmap.style.background_gradient(cmap='RdYlGn_r', axis=None, vmin=0, vmax=100).format("{:.1f}"), height=(len(symbols_to_plot) * 35 + 40), use_container_width=True)"""

    content = content.replace(old_single_heatmaps, new_single_heatmaps)

    # Replacement 3: Combine tab_position and tab_risk into tab_var_risk
    # We will search from 'with tab_position:' to the end of the file
    pos_idx = content.find("with tab_position:")
    if pos_idx == -1:
        # Fallback if tab_position names were changed
        pos_idx = content.find("with tab_var_risk:")
        
    if pos_idx == -1:
        print("Could not find start index for tab_position replacement.")
        return

    combined_tab_code = """with tab_var_risk:
    st.header("🛡️ VaR 风控与头寸管理")
    
    # 顶部渲染全局风控中枢
    st.markdown("### ⚙️ 全局风控中枢设置")
    col_var1, col_var2, col_var3, col_var4 = st.columns(4)
    with col_var1:
        drawdown_limit = st.number_input("最大回撤容忍度 (RMB)", value=200000.0, step=10000.0, key="drawdown_limit_input")
    with col_var2:
        risk_factor = st.slider("风险乘数因子 (k)", min_value=0.01, max_value=0.20, value=0.075, step=0.005, key="risk_factor_input")
    with col_var3:
        cppi_m = st.number_input("CPPI 乘数 (M)", value=1.0, min_value=0.1, max_value=5.0, step=0.1, key="cppi_m_input")
    with col_var4:
        target_var = pos_calc.calculate_target_var(drawdown_limit, risk_factor, cppi_m)
        st.metric(label="🎯 组合目标 VaR 限额", value=f"¥ {target_var:,.0f}")
        st.caption("当日全市场最大允许的 99% VaR 波动敞口。")
        
    st.markdown("---")
    
    # 左右分栏：左列头寸计算，右列实时风控评估
    col_calc, col_diag = st.columns([1, 1])
    
    with col_calc:
        st.subheader("💰 交互式资金头寸计算器")
        st.markdown("在这里构建您的计划交易清单。")
        
        # 状态缓存
        if 'portfolio_items' not in st.session_state:
            st.session_state.portfolio_items = []
            
        with st.form("add_symbol_form"):
            form_c1, form_c2, form_c3 = st.columns([1, 1, 1])
            with form_c1:
                input_sym = st.text_input("品种代码 (如 RB, CU)").upper()
            with form_c2:
                input_price = st.number_input("计划开仓价", min_value=0.0, step=1.0)
            with form_c3:
                input_direction = st.selectbox("交易方向", ["做多 (1)", "做空 (-1)"])
            add_btn = st.form_submit_button("添加/更新品种")
            
        if add_btn and input_sym:
            meta = pos_calc.get_symbol_metadata(input_sym)
            if not meta:
                st.error(f"数据库中未找到品种 {input_sym}")
            else:
                returns_df = get_aligned_returns(DB_PATH, [input_sym], period='daily', start_date='20200101', is_continuous=1)
                if not returns_df.empty and input_sym in returns_df.columns:
                    returns = returns_df[input_sym]
                    var_value, _, _ = calculate_ewma_var(returns, confidence_level=0.99, lambda_param=0.94)
                    
                    exists = False
                    for item in st.session_state.portfolio_items:
                        if item['symbol'] == input_sym:
                            item['price'] = input_price
                            item['direction'] = 1 if '做多' in input_direction else -1
                            item['var_pct'] = var_value
                            exists = True
                    if not exists:
                        st.session_state.portfolio_items.append({
                            'symbol': input_sym,
                            'price': input_price,
                            'direction': 1 if '做多' in input_direction else -1,
                            'var_pct': var_value,
                            'planned_lots': 0
                        })
                    st.success(f"{input_sym} 已添加！真实 VaR: {var_value*100:.2f}%")
                else:
                    st.error("无法计算该品种历史 VaR。")
                    
        if st.session_state.portfolio_items:
            st.markdown("#### 当前配置表")
            for i, item in enumerate(st.session_state.portfolio_items):
                sym = item['symbol']
                cc1, cc2, cc3 = st.columns([1, 1, 1])
                cc1.write(f"**{sym}** ({'多' if item['direction']==1 else '空'} @ {item['price']})\\nVaR: {item['var_pct']*100:.2f}%")
                
                meta = pos_calc.get_symbol_metadata(sym)
                multiplier = meta['multiplier'] if meta else 10.0
                occupied_var = item['planned_lots'] * item['price'] * multiplier * item['var_pct']
                max_res = pos_calc.calculate_single_asset_lots(sym, target_var, item['price'], item['var_pct'])
                
                cc2.write(f"建议上限: {max_res['suggested_lots']} 手\\n已占: ¥{occupied_var:,.0f}")
                item['planned_lots'] = cc3.number_input(f"计划手数 ({sym})", value=int(item['planned_lots']), min_value=0, step=1, key=f"lots_{sym}")
                st.markdown("---")
                
            if st.button("🗑️ 清空所有品种"):
                st.session_state.portfolio_items = []
                st.rerun()
                
    with col_diag:
        st.subheader("🚨 投资组合全局风控诊断报告")
        if not st.session_state.portfolio_items:
            st.info("请在左侧添加头寸，并在右侧查看实时风控诊断。")
        else:
            portfolio_dict = {}
            symbols_list = []
            for item in st.session_state.portfolio_items:
                if item['planned_lots'] > 0:
                    portfolio_dict[item['symbol']] = {
                        'lots': item['planned_lots'],
                        'direction': item['direction'],
                        'price': item['price']
                    }
                    symbols_list.append(item['symbol'])
                    
            if not portfolio_dict:
                st.warning("所有品种计划手数均为 0，无持仓数据可分析。")
            else:
                with st.spinner("正在评估组合对冲风险..."):
                    aligned_returns = get_aligned_returns(DB_PATH, symbols_list, period='daily', start_date='20200101', is_continuous=1)
                    cov_matrix, corr_matrix = calculate_covariance_correlation(aligned_returns)
                    res_port = pos_calc.evaluate_portfolio_risk(portfolio_dict, cov_matrix)
                    
                m1, m2 = st.columns(2)
                m1.metric("当前组合总 VaR", f"¥ {res_port['portfolio_var']:,.0f}", 
                          delta=f"剩余额度 {target_var - res_port['portfolio_var']:,.0f}", delta_color="normal")
                var_usage = res_port['portfolio_var'] / target_var
                m2.metric("VaR 预算使用率", f"{var_usage*100:.1f}%")
                
                if var_usage > 1.0:
                    st.error("🚨 警告：组合总 VaR 已超标，请削减仓位！")
                
                st.write(f"**占用总保证金**: ¥ {res_port['total_margin']:,.0f}")
                st.markdown("---")
                
                st.markdown("#### 一、板块集中度预警 (40% Cap)")
                pie_df = pd.DataFrame(list(res_port['sector_var_ratios'].items()), columns=['Sector', 'Ratio'])
                fig_pie = px.pie(pie_df, values='Ratio', names='Sector', title="各大板块风险贡献度")
                st.plotly_chart(fig_pie, use_container_width=True)
                
                if res_port['sector_warnings']:
                    for w in res_port['sector_warnings']:
                        st.error(f"❌ {w['message']}")
                        st.warning(f"建议削减该板块头寸 **{w['reduction_factor']*100:.1f}%**")
                else:
                    st.success("✅ 所有板块均处于安全集中度阈值内。")
                    
                st.markdown("---")
                st.markdown("#### 二、高相关性同质化拦截")
                if len(symbols_list) > 1:
                    fig_corr = px.imshow(corr_matrix, text_auto=".2f", color_continuous_scale='RdBu_r', range_color=[-1, 1], title="持仓品种相关系数")
                    st.plotly_chart(fig_corr, use_container_width=True)
                    
                    has_penalty = False
                    checked = set()
                    for s1 in symbols_list:
                        penalties = pos_calc.check_correlation_penalty(s1, [s for s in symbols_list if s != s1], corr_matrix)
                        for p in penalties:
                            s2 = p['symbol']
                            pair = tuple(sorted([s1, s2]))
                            if pair not in checked:
                                has_penalty = True
                                st.warning(f"⚠️ **{s1}** 与 **{s2}** 高相关 ({p['correlation']:.2f})！建议降权至 **{p['penalty_factor']*100:.0f}%**。")
                                checked.add(pair)
                    if not has_penalty:
                        st.success("✅ 持仓结构相关度健康，无同质化预警。")
                else:
                    st.info("单品种持仓不存在相关性校验。")
"""

    patched_content = content[:pos_idx] + combined_tab_code

    with open('app.py', 'w', encoding='utf-8') as f:
        f.write(patched_content)
        
    print("Tab refactoring and single commodity tab RPS_5 optimization applied successfully.")

if __name__ == "__main__":
    patch_app()

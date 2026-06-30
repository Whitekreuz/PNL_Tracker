import os

def patch_app():
    with open('app.py', 'r', encoding='utf-8') as f:
        content = f.read()

    # 1. Update tab definitions
    old_tabs = 'tab_market, tab_single, tab_position, tab_risk = st.tabs(["📊 市场复盘与强弱分析", "🔍 单品种详细分析", "💰 头寸计算器", "🚨 风控体检单"])'
    new_tabs = 'tab_market, tab_acceleration, tab_single, tab_position, tab_risk = st.tabs(["📊 市场复盘与强弱分析", "⚡ 板块动能加速度分析", "🔍 单品种详细分析", "💰 头寸计算器", "🚨 风控体检单"])'
    content = content.replace(old_tabs, new_tabs)

    # 2. Inject Tab 1.2: 板块动能加速度分析
    insertion_marker = "# ==========================================\n# Tab 1.5: 单品种详细分析"
    
    acceleration_tab_code = """# ==========================================
# Tab 1.2: 板块动能加速度分析
# ==========================================
with tab_acceleration:
    st.header("⚡ 板块动能加速度分析")
    
    # 选项：RPS 周期选择 (1/5/20)
    selected_period = st.radio("选择动能计算周期 (D)：", [1, 5, 20], index=2, horizontal=True)
    
    # 获取板块收益率与 RPS 历史 (过去 10 个交易日)
    try:
        sec_df_list_acc = []
        for sec, s_data in sector_indices.items():
            s_data = s_data.copy()
            # 默认使用持仓金额加权指数 'nw_index'
            sec_df_list_acc.append(s_data[['nw_index']].rename(columns={'nw_index': sec}))
            
        sector_pivot_acc = pd.concat(sec_df_list_acc, axis=1).ffill().dropna()
        
        # 计算指定周期 N 的收益率历史
        returns_N_acc = sector_pivot_acc.pct_change(periods=selected_period).dropna()
        
        # 取过去 10 个交易日
        last_10_returns_acc = returns_N_acc.tail(10)
        
        # 计算这 10 天的截面排名 (RPS)
        ranks_acc = last_10_returns_acc.rank(axis=1, ascending=True)
        n_sectors_acc = sector_pivot_acc.shape[1]
        rps_10d_history_acc = (ranks_acc - 1.0) / (n_sectors_acc - 1.0) * 100.0
        
        # 1. 动能变动热力图 DataFrame
        rps_heatmap_acc = rps_10d_history_acc.T
        # 按最新一天排序
        rps_heatmap_acc = rps_heatmap_acc.sort_values(by=rps_heatmap_acc.columns[-1], ascending=False)
        
        # 2. 板块当天收益率一列，合并在后面
        # 最新一天的 N 日收益率
        latest_returns_acc = returns_N_acc.iloc[-1].rename(f'{selected_period}D 收益率')
        
        # 计算 RPS 变化量 (最新一日 - 10天前一日)
        if rps_heatmap_acc.shape[1] >= 10:
            change_10d_acc = (rps_heatmap_acc[rps_heatmap_acc.columns[-1]] - rps_heatmap_acc[rps_heatmap_acc.columns[0]]).rename('10D 变动')
        else:
            change_10d_acc = pd.Series(0.0, index=rps_heatmap_acc.index, name='10D 变动')
            
        # 格式化日期列名
        formatted_columns = []
        for c in rps_heatmap_acc.columns:
            formatted_columns.append(str(c)[:10])
        rps_heatmap_acc.columns = formatted_columns
        
        date_cols = list(rps_heatmap_acc.columns)
        
        # 合并
        display_df = rps_heatmap_acc.join(change_10d_acc).join(latest_returns_acc)
        
        # 排序：按最新一天的 RPS (date_cols[-1]) 降序排列
        display_df = display_df.sort_values(by=date_cols[-1], ascending=False)
        
        # 使用 Pandas styler 进行美化
        styled_df = display_df.style.background_gradient(
            cmap='RdYlGn_r', 
            subset=date_cols, 
            vmin=0, 
            vmax=100
        ).format({
            f'{selected_period}D 收益率': '{:+.2%}',
            '10D 变动': '{:+.1f}'
        })
        for d_col in date_cols:
            styled_df = styled_df.format({d_col: '{:.1f}'})
            
        st.subheader(f"🔥 板块近 10 个交易日 RPS_{selected_period} 变动热力图")
        st.dataframe(styled_df, use_container_width=True)
        
    except Exception as e:
        st.error(f"动能加速度分析生成失败: {e}")

"""

    content = content.replace(insertion_marker, acceleration_tab_code + "\n\n" + insertion_marker)

    with open('app.py', 'w', encoding='utf-8') as f:
        f.write(content)
        
    print("Tab 1.2 patched successfully.")

if __name__ == "__main__":
    patch_app()

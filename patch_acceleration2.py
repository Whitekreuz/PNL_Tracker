import os

def patch_app():
    with open('app.py', 'r', encoding='utf-8') as f:
        content = f.read()

    # Define the target block to replace (from line 280 to 353 approx)
    target_start = "with tab_acceleration:"
    target_end = "except Exception as e:\n        st.error(f\"动能加速度分析生成失败: {e}\")"

    start_idx = content.find(target_start)
    end_idx = content.find(target_end)

    if start_idx == -1 or end_idx == -1:
        print("Could not find start or end index for tab_acceleration replacement.")
        return

    # Adjust end_idx to cover the entire block
    end_idx += len(target_end)

    new_tab_code = """with tab_acceleration:
    st.header("⚡ 板块与品种动能加速度分析")
    
    # 选项：RPS 周期选择 (1/5/20)
    selected_period = st.radio("选择动能计算周期 (D)：", [1, 5, 20], index=2, horizontal=True)
    
    # 1. 板块动能变动与收益率
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
        
        # 动能变动热力图 DataFrame
        rps_heatmap_acc = rps_10d_history_acc.T
        # 按最新一天排序
        rps_heatmap_acc = rps_heatmap_acc.sort_values(by=rps_heatmap_acc.columns[-1], ascending=False)
        
        # 板块当天收益率一列，合并在后面
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
        
        # 使用 Pandas styler 进行美化 (合并所有 columns 格式化，避免覆盖)
        format_dict = {
            f'{selected_period}D 收益率': '{:+.2%}',
            '10D 变动': '{:+.1f}'
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
        
    except Exception as e:
        st.error(f"板块动能加速度分析生成失败: {e}")

    # 2. 个股商品多头与空头 Top 10 热力图
    try:
        conn = sqlite3.connect(DB_PATH)
        # 获取最新的 50 个交易日以便计算 (N=20 时，20+10=30日就足够了，取 50 更稳妥)
        dates_all = pd.read_sql("SELECT DISTINCT date FROM kline_daily ORDER BY date DESC LIMIT 50", conn)['date'].tolist()
        if len(dates_all) >= (selected_period + 10):
            start_date_all = dates_all[-1]
            query_all = f"SELECT symbol, date, close FROM kline_daily WHERE is_continuous=1 AND date >= '{start_date_all}'"
            df_all_raw = pd.read_sql(query_all, conn)
            
            pivot_close_all = df_all_raw.pivot(index='date', columns='symbol', values='close').ffill()
            
            # 计算 N 日收益率
            returns_all = pivot_close_all.pct_change(periods=selected_period).dropna()
            
            # 取最后 10 个交易日
            last_10_returns_all = returns_all.tail(10)
            
            # 计算这 10 天每日的截面 RPS 排名
            ranks_all = last_10_returns_all.rank(axis=1, ascending=True)
            n_symbols_all = pivot_close_all.shape[1]
            rps_10d_all = (ranks_all - 1.0) / (n_symbols_all - 1.0) * 100.0
            
            # 最新一天的 RPS 向量用于做 Top 10 选择
            latest_rps_all = rps_10d_all.iloc[-1]
            
            # 选出多头 Top 10 (最新一天最高) 和 空头 Top 10 (最新一天最低)
            top10_long_symbols = latest_rps_all.sort_values(ascending=False).head(10).index.tolist()
            top10_short_symbols = latest_rps_all.sort_values(ascending=True).head(10).index.tolist()
            
            # 构建多头热力图 DataFrame
            long_hm_df = rps_10d_all[top10_long_symbols].T
            long_hm_df = long_hm_df.sort_values(by=long_hm_df.columns[-1], ascending=False)
            
            # 构建空头热力图 DataFrame
            short_hm_df = rps_10d_all[top10_short_symbols].T
            short_hm_df = short_hm_df.sort_values(by=short_hm_df.columns[-1], ascending=True)
            
            # 格式化日期列名
            for hm_df in [long_hm_df, short_hm_df]:
                if isinstance(hm_df.columns, pd.DatetimeIndex):
                    hm_df.columns = hm_df.columns.strftime('%Y-%m-%d')
                else:
                    hm_df.columns = [str(c)[:10] for c in hm_df.columns]
                    
            date_cols_all = list(long_hm_df.columns)
            format_dict_all = {c: '{:.1f}' for c in date_cols_all}
            
            st.markdown("---")
            st.subheader(f"🔥 最强多头榜 Top 10 品种近 10 个交易日 RPS_{selected_period} 热力图")
            styled_long = long_hm_df.style.background_gradient(
                cmap='RdYlGn_r', axis=None, vmin=0, vmax=100
            ).format(format_dict_all)
            st.dataframe(styled_long, use_container_width=True)
            
            st.subheader(f"🧊 最弱空头榜 Top 10 品种近 10 个交易日 RPS_{selected_period} 热力图")
            styled_short = short_hm_df.style.background_gradient(
                cmap='RdYlGn_r', axis=None, vmin=0, vmax=100
            ).format(format_dict_all)
            st.dataframe(styled_short, use_container_width=True)
            
        else:
            st.warning("全市场历史数据不足，无法计算当前周期下的个股 RPS 10 日变动热力图。")
        conn.close()
    except Exception as e:
        st.error(f"个股商品动能加速度分析生成失败: {e}")"""

    patched_content = content[:start_idx] + new_tab_code + content[end_idx:]

    with open('app.py', 'w', encoding='utf-8') as f:
        f.write(patched_content)
        
    print("Tab 1.2 optimized successfully.")

if __name__ == "__main__":
    patch_app()

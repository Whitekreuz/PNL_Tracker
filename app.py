import streamlit as st
import pandas as pd
import numpy as np
import plotly.express as px
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import sqlite3
import os

from risk_engine import calculate_ewma_var, get_aligned_returns, calculate_covariance_correlation
from position_calculator import PositionCalculator
from market_reviewer import MarketReviewer

# --- 全局配置 ---
st.set_page_config(page_title="量化交易风控工作台", layout="wide", page_icon="📈")
import os
DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "futures_data.db")
# --- 缓存底层数据加载 ---
@st.cache_resource
def load_engines():
    if not os.path.exists(DB_PATH):
        st.error(f"数据库 {DB_PATH} 不存在！")
        st.stop()
    pos_calc = PositionCalculator(DB_PATH)
    reviewer = MarketReviewer(DB_PATH)
    return pos_calc, reviewer

pos_calc, reviewer = load_engines()

# --- 主页面 Tabs ---
tab_market, tab_acceleration, tab_capital_flow, tab_single, tab_var_risk = st.tabs([
    "📊 市场复盘与强弱分析", 
    "⚡ 板块与品种动能加速度分析", 
    "💸 资金流与沉淀资金分析", 
    "🔍 单品种详细分析", 
    "🛡️ VaR风控管理"
])

# ==========================================
# Tab 1: 市场复盘与强弱分析
# ==========================================
with tab_market:
    st.header("1. 板块与品种资金面与技术面扫描")
    
    # 提取复盘数据
    with st.spinner("正在计算全市场资金流向与 RPS..."):
        flow_res = reviewer.calculate_capital_flow()
        rps_res = reviewer.calculate_rps(periods=[1, 5, 20, 60])
        sector_indices = reviewer.generate_sector_indices(start_date='20250101')
        
        # 10日变化逻辑
        conn = sqlite3.connect(DB_PATH)
        dates = pd.read_sql("SELECT DISTINCT date FROM kline_daily ORDER BY date DESC LIMIT 15", conn)['date'].tolist()
        t10_date = dates[10] if len(dates) > 10 else dates[-1]
        
        rps_res_t10 = reviewer.calculate_rps(periods=[1, 5, 20, 60], target_date=t10_date)
        
        query_10d = f"SELECT symbol, date, open_interest, settlement FROM kline_daily WHERE is_continuous=1 AND date >= '{t10_date}' ORDER BY symbol, date"
        df_10d = pd.read_sql(query_10d, conn)
        conn.close()
        df_10d = df_10d[df_10d['symbol'].isin(reviewer._metadata_cache.index)].copy()
        
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
        
    if flow_res and rps_res and sector_indices:
        data_date = flow_res['target_date']
        st.caption(f"📅 数据日期: {data_date}")
        
        # --- 视图 1：九大板块走势对比 ---
        st.subheader("一、全市场宏观板块趋势对比")
        index_type = st.radio("选择指数计算模式：", ["持仓金额加权 (默认)", "等权重 (探寻小品种)"], horizontal=True)
        col_name = 'nw_index' if '持仓' in index_type else 'ew_index'
        
        # 组装 9 大板块走势为宽表
        sec_df_list = []
        for sec, s_data in sector_indices.items():
            s_data = s_data.copy()
            s_data.rename(columns={col_name: sec}, inplace=True)
            sec_df_list.append(s_data[sec])
        
        all_sector_df = pd.concat(sec_df_list, axis=1).ffill().dropna()
        
        fig_sectors = px.line(all_sector_df, title=f"9 大板块历史走势 ({index_type})")
        fig_sectors.update_layout(xaxis_title="日期", yaxis_title="指数净值 (基准 1000)", height=500)
        st.plotly_chart(fig_sectors, use_container_width=True)
        
        st.markdown("---")
        
        
# 板块强弱与 10日资金流
        st.subheader("各大板块强弱与 10 日资金流占比")
        if 'RPS_20' in sector_summary.columns:
            st.dataframe(sector_summary[['sector', 'RPS_20', 'RPS_Change_10d', 'Return_1', 'Return_5', 'capital_flow', 'flow_ratio_10d']].sort_values(by='RPS_20', ascending=False).style.format({
                'RPS_20': '{:.1f}', 'RPS_Change_10d': '{:+.1f}', 'Return_1': '{:+.2%}', 'Return_5': '{:+.2%}', 'capital_flow': '{:,.0f}', 'flow_ratio_10d': '{:.2%}'
            }))
            
        # 板块 10日 RPS 历史热力图
        st.subheader("各大板块近 10 个交易日 RPS 变动热力图")
        try:
            sec_df_list_hm = []
            for sec, s_data in sector_indices.items():
                s_data = s_data.copy()
                sec_df_list_hm.append(s_data[[col_name]].rename(columns={col_name: sec}))
                
            sector_pivot_hm = pd.concat(sec_df_list_hm, axis=1).ffill().dropna()
            
            returns_20_hm = sector_pivot_hm.pct_change(periods=20).dropna()
            last_10_returns_hm = returns_20_hm.tail(10)
            
            ranks_hm = last_10_returns_hm.rank(axis=1, ascending=True)
            n_sectors_hm = sector_pivot_hm.shape[1]
            rps_10d_history_hm = (ranks_hm - 1.0) / (n_sectors_hm - 1.0) * 100.0
            
            # 转置为 行：板块，列：日期
            rps_heatmap_df = rps_10d_history_hm.T
            # 按最新一天的 RPS 降序排列
            rps_heatmap_df = rps_heatmap_df.sort_values(by=rps_heatmap_df.columns[-1], ascending=False)
            
            # 将列名(日期)转换为字符串格式
            if isinstance(rps_heatmap_df.columns, pd.DatetimeIndex):
                rps_heatmap_df.columns = rps_heatmap_df.columns.strftime('%Y-%m-%d')
            else:
                rps_heatmap_df.columns = [str(c)[:10] for c in rps_heatmap_df.columns]
                
            # 渲染带背景色的热力图表格
            styled_heatmap = rps_heatmap_df.style.background_gradient(cmap='RdYlGn_r', axis=None, vmin=0, vmax=100).format("{:.1f}")
            st.dataframe(styled_heatmap, use_container_width=True)
        except Exception as e:
            st.error(f"热力图渲染失败: {e}")
        
        st.markdown("---")
        
        # --- 视图 2：全市场个股对比 (RPS 散点图) ---
        st.subheader("二、全市场单品种 20 日动能与资金流对比")
        symbol_flow = flow_res['symbol_flow'].set_index('symbol')
        symbol_rps = rps_res['symbol_rps']
        
        # 合并 RPS 和资金流
        market_scatter_df = pd.merge(symbol_rps, symbol_flow[['capital_flow', 'delta_oi']], left_index=True, right_index=True, how='left')
        
        fig_scatter = px.scatter(
            market_scatter_df.reset_index(), 
            x='capital_flow', 
            y='RPS_20', 
            color='sector', 
            hover_data=['symbol', 'Return_20'],
            labels={'capital_flow': '当日资金净流入 (RMB)', 'RPS_20': '20日相对强度 (RPS)'},
            title="全市场品种：资金流向与动能强弱散点图"
        )
        # 添加辅助线
        fig_scatter.add_hline(y=50, line_dash="dash", line_color="gray")
        fig_scatter.add_vline(x=0, line_dash="dash", line_color="gray")
        st.plotly_chart(fig_scatter, use_container_width=True)
        
        st.markdown("---")
        
        # --- 视图 3：板块内横向对比 ---
        st.subheader("三、板块内部结构深扒")
        selected_sector = st.selectbox("选择要分析的板块：", market_scatter_df['sector'].unique())
        
        # 获取该板块内的所有品种数据
        intra_sector_df = market_scatter_df[market_scatter_df['sector'] == selected_sector]
        intra_symbols = intra_sector_df.index.tolist()
        
        col1, col2 = st.columns(2)
        with col1:
            st.write(f"**[{selected_sector}] 板块内部 RPS 与资金流水**")
            st.dataframe(intra_sector_df[['RPS_20', 'Return_20', 'capital_flow']].sort_values(by='RPS_20', ascending=False).style.format({'RPS_20': '{:.1f}', 'Return_20': '{:.2%}', 'capital_flow': '{:,.0f}'}))
            
        with col2:
            # 绘制板块内部各个品种的净值走势
            st.write(f"**[{selected_sector}] 内部各品种近半年净值对比**")
            try:
                conn = sqlite3.connect(DB_PATH)
                query = f"SELECT symbol, date, close FROM kline_daily WHERE is_continuous=1 AND date >= '20250601' AND symbol IN ({','.join(['?']*len(intra_symbols))})"
                intra_prices = pd.read_sql(query, conn, params=intra_symbols)
                conn.close()
                intra_pivot = intra_prices.pivot(index='date', columns='symbol', values='close').ffill().dropna()
                # 归一化到 1000
                intra_norm = (intra_pivot / intra_pivot.iloc[0]) * 1000
                fig_intra = px.line(intra_norm)
                fig_intra.update_layout(xaxis_title="日期", yaxis_title="归一化净值 (基准 1000)", showlegend=True)
                st.plotly_chart(fig_intra, use_container_width=True)
            except Exception as e:
                st.warning(f"加载板块内部对比图表失败: {e}")

# ==========================================
# Tab 2: 头寸计算器


# --- 视图 1.5：全市场最强与最弱 TOP 10 ---
        st.subheader("全市场最强 (多头) 与最弱 (空头) Top 10 品种")
        top10_long = symbol_rps_now.sort_values(by='RPS_20', ascending=False).head(10)[['RPS_20', 'RPS_Change_10d', 'Return_1', 'Return_5', 'Return_20', 'sector']]
        top10_short = symbol_rps_now.sort_values(by='RPS_20', ascending=True).head(10)[['RPS_20', 'RPS_Change_10d', 'Return_1', 'Return_5', 'Return_20', 'sector']]
        
        col_l, col_s = st.columns(2)
        with col_l:
            st.write("🔥 **最强多头榜 Top 10**")
            st.dataframe(top10_long.style.format({'RPS_20': '{:.1f}', 'RPS_Change_10d': '{:+.1f}', 'Return_1': '{:+.2%}', 'Return_5': '{:+.2%}', 'Return_20': '{:+.2%}'}))
        with col_s:
            st.write("🧊 **最弱空头榜 Top 10**")
            st.dataframe(top10_short.style.format({'RPS_20': '{:.1f}', 'RPS_Change_10d': '{:+.1f}', 'Return_1': '{:+.2%}', 'Return_5': '{:+.2%}', 'Return_20': '{:+.2%}'}))
            

        # --- 新增：最强最弱 Top 10 品种近 10 日 RPS 热力图 ---
        st.subheader("最强与最弱 Top 10 品种近 10 个交易日 RPS 热力图")
        try:
            conn = sqlite3.connect(DB_PATH)
            dates_31 = pd.read_sql("SELECT DISTINCT date FROM kline_daily ORDER BY date DESC LIMIT 31", conn)['date'].tolist()
            if len(dates_31) >= 21:
                start_date = dates_31[-1]
                query_all = f"SELECT symbol, date, close FROM kline_daily WHERE is_continuous=1 AND date >= '{start_date}'"
                df_all = pd.read_sql(query_all, conn)
                
                pivot_close = df_all.pivot(index='date', columns='symbol', values='close').ffill()
                returns_20 = pivot_close.pct_change(periods=20).dropna()
                last_10_returns = returns_20.tail(10)
                
                ranks = last_10_returns.rank(axis=1, ascending=True)
                n_symbols = pivot_close.shape[1]
                rps_10d_history = (ranks - 1.0) / (n_symbols - 1.0) * 100.0
                
                top_symbols = list(top10_long.index) + list(top10_short.index)
                available_symbols = [s for s in top_symbols if s in rps_10d_history.columns]
                
                rps_heatmap_df = rps_10d_history[available_symbols].T
                rps_heatmap_df = rps_heatmap_df.sort_values(by=rps_heatmap_df.columns[-1], ascending=False)
                
                if isinstance(rps_heatmap_df.columns, pd.DatetimeIndex):
                    rps_heatmap_df.columns = rps_heatmap_df.columns.strftime('%Y-%m-%d')
                else:
                    rps_heatmap_df.columns = [str(c)[:10] for c in rps_heatmap_df.columns]
                    
                styled_heatmap = rps_heatmap_df.style.background_gradient(cmap='RdYlGn_r', axis=None, vmin=0, vmax=100).format("{:.1f}")
                st.dataframe(styled_heatmap, use_container_width=True)
            else:
                st.info("数据不足 30 个交易日，无法生成单品种 RPS 热力图。")
            conn.close()
        except Exception as e:
            st.error(f"生成单品种热力图失败: {e}")
            
        
# ==========================================
# Tab 1.2: 板块动能加速度分析
# ==========================================
with tab_acceleration:
    st.header("⚡ 板块与品种动能加速度分析")
    
    # 选项：RPS 周期选择 (1/5/20)
    selected_period = st.radio("选择动能计算周期 (D)：", [1, 5, 20], index=2, horizontal=True)
    
    try:
        # 一次性获取全市场行情与元数据，用于动能与资金流计算
        conn = sqlite3.connect(DB_PATH)
        dates_all = pd.read_sql("SELECT DISTINCT date FROM kline_daily ORDER BY date DESC LIMIT 60", conn)['date'].tolist()
        start_date_all = dates_all[-1] if len(dates_all) > 0 else "2025-01-01"
        
        query_all = """
        SELECT k.symbol, k.date, k.close, k.open_interest, k.settlement, m.multiplier, m.margin_rate, m.sector 
        FROM kline_daily k
        LEFT JOIN contract_metadata m ON k.symbol = m.symbol
        WHERE k.is_continuous = 1 AND k.date >= ?
        """
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
    selected_period_flow = st.radio("选择资金流向计算周期 (D)：", [1, 5, 20], index=2, horizontal=True, key="flow_period_selector")
    
    try:
        # 获取足够用于计算滚动累计值的行情数据 (需要 60 天)
        conn = sqlite3.connect(DB_PATH)
        dates_flow = pd.read_sql("SELECT DISTINCT date FROM kline_daily ORDER BY date DESC LIMIT 60", conn)['date'].tolist()
        start_date_flow = dates_flow[-1] if len(dates_flow) > 0 else "2025-01-01"
        
        query_flow = """
        SELECT k.symbol, k.date, k.open_interest, k.settlement, m.multiplier, m.margin_rate, m.sector 
        FROM kline_daily k
        LEFT JOIN contract_metadata m ON k.symbol = m.symbol
        WHERE k.is_continuous = 1 AND k.date >= ?
        """
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
        st.error(f"资金流向与沉淀资金分析生成失败: {e}")



# ==========================================
# Tab 1.5: 单品种详细分析
# ==========================================
with tab_single:
    st.header("🔍 单品种 60 日量价与动能分析")
    
    # 确保所需的基础数据已就绪
    try:
        sectors = list(reviewer._metadata_cache['sector'].unique())
        sectors = [s for s in sectors if str(s) != 'nan' and s.strip() != '']
    except:
        sectors = []
        
    if not sectors:
        st.warning("暂无可用的板块数据。")
    else:
        col1, col2 = st.columns(2)
        with col1:
            selected_sector = st.selectbox("1. 选择板块", options=sorted(sectors))
        
        # 筛选该板块下的品种
        symbols_in_sector = reviewer._metadata_cache[reviewer._metadata_cache['sector'] == selected_sector].index.tolist()
        
        with col2:
            selected_symbol = st.selectbox("2. 选择品种", options=sorted(symbols_in_sector))
            
        if selected_symbol:
            with st.spinner(f"正在生成 {selected_symbol} 的分析图表..."):
                try:
                    conn = sqlite3.connect(DB_PATH)
                    # 我们需要获取全市场近 80 天的收盘价，以便计算 60 天内的每日 RPS_5
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
                            symbol_rps = pd.Series(dtype=float)
                            
                        # 取选定品种近 60 天的详细 K 线数据
                        start_date_60 = dates_80[60] if len(dates_80) > 60 else dates_80[-1]
                        query_single = f"SELECT date, open, high, low, close, volume, open_interest, settlement FROM kline_daily WHERE symbol='{selected_symbol}' AND is_continuous=1 AND date >= '{start_date_60}' ORDER BY date"
                        df_single = pd.read_sql(query_single, conn)
                        
                        if not df_single.empty:
                            # 资金流向计算
                            multiplier = float(reviewer._metadata_cache.loc[selected_symbol, 'contract_multiplier']) if selected_symbol in reviewer._metadata_cache.index else 10.0
                            df_single['prev_oi'] = df_single['open_interest'].shift(1)
                            df_single['delta_oi'] = df_single['open_interest'] - df_single['prev_oi']
                            df_single['capital_flow'] = df_single['delta_oi'] * df_single['settlement'] * multiplier
                            
                            df_single.set_index('date', inplace=True)
                            
                            # 合并 RPS
                            df_single['rps_5'] = symbol_rps
                            
                            # 转换为 datetime 索引以便 rangebreaks 能够生效
                            df_single.index = pd.to_datetime(df_single.index)
                            
                            # 剔除第一行可能缺失 delta_oi 的数据
                            df_single = df_single.dropna(subset=['close']).tail(60)
                            
                            # ====== 绘制复合图表 ======
                            fig = make_subplots(
                                rows=4, cols=1, shared_xaxes=True, 
                                vertical_spacing=0.03,
                                row_heights=[0.4, 0.2, 0.2, 0.2],
                                specs=[[{"secondary_y": False}],
                                       [{"secondary_y": True}],
                                       [{"secondary_y": False}],
                                       [{"secondary_y": False}]]
                            )
                            
                            # 1. K 线图 (Row 1)
                            fig.add_trace(go.Candlestick(
                                x=df_single.index,
                                open=df_single['open'],
                                high=df_single['high'],
                                low=df_single['low'],
                                close=df_single['close'],
                                name="K线",
                                increasing_line_color='red', decreasing_line_color='green'
                            ), row=1, col=1)
                            
                            # 2. 成交量与持仓量 (Row 2)
                            fig.add_trace(go.Bar(
                                x=df_single.index, y=df_single['volume'],
                                name="成交量", marker_color='rgba(158,202,225,0.7)'
                            ), row=2, col=1, secondary_y=False)
                            
                            fig.add_trace(go.Scatter(
                                x=df_single.index, y=df_single['open_interest'],
                                name="持仓量", line=dict(color='orange', width=2)
                            ), row=2, col=1, secondary_y=True)
                            
                            # 3. 资金流向变化 (Row 3)
                            colors = ['red' if val > 0 else 'green' for val in df_single['capital_flow']]
                            fig.add_trace(go.Bar(
                                x=df_single.index, y=df_single['capital_flow'],
                                name="资金净流入", marker_color=colors
                            ), row=3, col=1)
                            
                            # 4. RPS 5 日动能变化 (Row 4)
                            fig.add_trace(go.Scatter(
                                x=df_single.index, y=df_single['rps_5'],
                                name="RPS 5", line=dict(color='purple', width=2),
                                mode='lines+markers'
                            ), row=4, col=1)
                            
                            # 布局设置
                            fig.update_layout(
                                title=f"{selected_symbol} 过去 60 日详细复盘 (价格/量仓/资金/RPS 5)",
                                xaxis_rangeslider_visible=False,
                                height=900,
                                margin=dict(l=40, r=40, t=60, b=40),
                                hovermode="x unified"
                            )
                            # 收集非交易日以去除空白
                            all_dates = pd.date_range(start=df_single.index.min(), end=df_single.index.max())
                            df_dates = pd.to_datetime(df_single.index)
                            missing_dates = all_dates.difference(df_dates).strftime('%Y-%m-%d').tolist()
                            
                            # 设置十字准星，并通过 rangebreaks 隐藏非交易日
                            fig.update_xaxes(
                                rangebreaks=[dict(values=missing_dates)],
                                showspikes=True,
                                spikemode="across",
                                spikesnap="cursor",
                                showline=True,
                                spikedash="solid",
                                spikethickness=1,
                                spikecolor="grey"
                            )
                            
                            # 设置 Y 轴标题
                            fig.update_yaxes(title_text="价格", row=1, col=1)
                            fig.update_yaxes(title_text="成交量", row=2, col=1, secondary_y=False)
                            fig.update_yaxes(title_text="持仓量", row=2, col=1, secondary_y=True)
                            fig.update_yaxes(title_text="资金流向", row=3, col=1)
                            fig.update_yaxes(title_text="RPS 5 (0-100)", range=[0, 100], row=4, col=1)
                            
                            st.plotly_chart(fig, use_container_width=True)
                            
                            st.markdown("---")
                            # ======= 新增：板块及内部品种 10 个交易日 RPS_5 热力图 =======
                            
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
                                st.dataframe(sym_rps_heatmap.style.background_gradient(cmap='RdYlGn_r', axis=None, vmin=0, vmax=100).format("{:.1f}"), height=(len(symbols_to_plot) * 35 + 40), use_container_width=True)
                            
                        else:
                            st.warning(f"未能获取到 {selected_symbol} 的历史行情数据。")
                    else:
                        st.warning("全市场数据不足以计算 60 日 RPS (需要至少 80 个交易日的数据)。")
                        
                    conn.close()
                except Exception as e:
                    st.error(f"图表生成失败: {e}")


# ==========================================
with tab_var_risk:
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
                cc1.write(f"**{sym}** ({'多' if item['direction']==1 else '空'} @ {item['price']})\nVaR: {item['var_pct']*100:.2f}%")
                
                meta = pos_calc.get_symbol_metadata(sym)
                multiplier = meta['multiplier'] if meta else 10.0
                occupied_var = item['planned_lots'] * item['price'] * multiplier * item['var_pct']
                max_res = pos_calc.calculate_single_asset_lots(sym, target_var, item['price'], item['var_pct'])
                
                cc2.write(f"建议上限: {max_res['suggested_lots']} 手\n已占: ¥{occupied_var:,.0f}")
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

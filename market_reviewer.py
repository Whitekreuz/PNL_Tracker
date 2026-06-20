import pandas as pd
import numpy as np
import sqlite3

class MarketReviewer:
    def __init__(self, db_path: str):
        self.db_path = db_path
        self._metadata_cache = None
        self._load_metadata()

    def _load_metadata(self):
        """加载品种元数据并建立分类映射"""
        conn = sqlite3.connect(self.db_path)
        query = "SELECT symbol, sector, multiplier as contract_multiplier FROM contract_metadata"
        self._metadata_cache = pd.read_sql(query, conn).set_index('symbol')
        conn.close()
        
    def _get_daily_data(self, start_date: str = '20200101', target_date: str = None) -> pd.DataFrame:
        """获取主力连续合约的日线数据"""
        conn = sqlite3.connect(self.db_path)
        query = "SELECT symbol, date, close, open_interest, settlement FROM kline_daily WHERE is_continuous = 1"
        params = []
        if target_date:
            query += " AND date = ?"
            params.append(target_date)
        else:
            query += " AND date >= ?"
            params.append(start_date)
            
        df = pd.read_sql(query, conn, params=params)
        conn.close()
        return df

    def calculate_capital_flow(self, target_date: str = None) -> dict:
        """
        计算指定日期（或最新交易日）全市场所有品种的资金流入流出，并按板块进行聚合汇总。
        """
        # 为了计算 Delta OI，我们需要当天和前一天的数据
        # 这里最安全的做法是拉取所有历史数据然后进行 shift
        df = self._get_daily_data()
        if df.empty:
            return {'symbol_flow': pd.DataFrame(), 'sector_flow': pd.DataFrame()}
            
        # 确保按时间排序
        df = df.sort_values(by=['symbol', 'date'])
        
        # 计算单品种的 Delta OI
        df['prev_oi'] = df.groupby('symbol')['open_interest'].shift(1)
        df['delta_oi'] = df['open_interest'] - df['prev_oi']
        
        # 匹配乘数
        df['multiplier'] = df['symbol'].map(lambda x: float(self._metadata_cache.loc[x, 'contract_multiplier']) if x in self._metadata_cache.index else 10.0)
        
        # 资金净流入 Flow = Delta OI * Settle * Multiplier
        df['capital_flow'] = df['delta_oi'] * df['settlement'] * df['multiplier']
        
        # 提取目标日的数据，如果不传 target_date，则取全市场最新的日期
        if target_date is None:
            target_date = df['date'].max()
            
        target_df = df[df['date'] == target_date].copy()
        
        # 附带上板块信息
        target_df['sector'] = target_df['symbol'].map(lambda x: self._metadata_cache.loc[x, 'sector'] if x in self._metadata_cache.index else '未知')
        
        # 按资金流入金额降序排列
        target_df = target_df.sort_values(by='capital_flow', ascending=False)
        
        # 板块汇总
        sector_flow = target_df.groupby('sector')['capital_flow'].sum().reset_index()
        sector_flow = sector_flow.sort_values(by='capital_flow', ascending=False)
        
        return {
            'target_date': target_date,
            'symbol_flow': target_df[['symbol', 'sector', 'date', 'delta_oi', 'settlement', 'capital_flow']],
            'sector_flow': sector_flow
        }

    def generate_sector_indices(self, start_date: str = '20200101') -> dict:
        """
        根据本地各品种日K，构建并计算 9 大板块的历史净值走势曲线（持仓加权与等权重）。
        """
        df = self._get_daily_data(start_date)
        if df.empty:
            return {}
            
        df = df.sort_values(by=['symbol', 'date'])
        df['return'] = df.groupby('symbol')['close'].pct_change()
        df['sector'] = df['symbol'].map(lambda x: self._metadata_cache.loc[x, 'sector'] if x in self._metadata_cache.index else '未知')
        df['multiplier'] = df['symbol'].map(lambda x: float(self._metadata_cache.loc[x, 'contract_multiplier']) if x in self._metadata_cache.index else 10.0)
        
        # 计算名义持仓金额 Notional Value = OI * Close * Multiplier
        df['notional_value'] = df['open_interest'] * df['close'] * df['multiplier']
        
        # 清除无法计算的行
        df = df.dropna(subset=['return'])
        
        # 计算等权重指数日收益率
        equal_weight_return = df.groupby(['date', 'sector'])['return'].mean().reset_index()
        equal_weight_return.rename(columns={'return': 'ew_return'}, inplace=True)
        
        # 计算持仓金额加权指数日收益率
        # Weight_i = Notional_i / Sum(Notional_Sector)
        # Sector_Return = Sum(Weight_i * Return_i)
        
        # 为了避免前视偏差（look-ahead bias），权重应使用 t-1 期的持仓规模
        df['prev_notional'] = df.groupby('symbol')['notional_value'].shift(1)
        
        # 按日期和板块汇总总前置持仓金额
        sector_total_notional = df.groupby(['date', 'sector'])['prev_notional'].sum().reset_index()
        sector_total_notional.rename(columns={'prev_notional': 'sector_total_notional'}, inplace=True)
        
        merged_df = pd.merge(df, sector_total_notional, on=['date', 'sector'], how='left')
        merged_df['weight'] = np.where(merged_df['sector_total_notional'] > 0, 
                                       merged_df['prev_notional'] / merged_df['sector_total_notional'], 
                                       0)
                                       
        merged_df['weighted_return'] = merged_df['weight'] * merged_df['return']
        notional_weight_return = merged_df.groupby(['date', 'sector'])['weighted_return'].sum().reset_index()
        notional_weight_return.rename(columns={'weighted_return': 'nw_return'}, inplace=True)
        
        # 合并两种收益率
        indices_df = pd.merge(equal_weight_return, notional_weight_return, on=['date', 'sector'], how='inner')
        
        # 转换为累计净值序列 (基准为1000)
        sector_indices = {}
        sectors = indices_df['sector'].unique()
        
        for sec in sectors:
            sec_data = indices_df[indices_df['sector'] == sec].sort_values(by='date').copy()
            sec_data['ew_index'] = 1000 * (1 + sec_data['ew_return']).cumprod()
            sec_data['nw_index'] = 1000 * (1 + sec_data['nw_return']).cumprod()
            sector_indices[sec] = sec_data[['date', 'ew_index', 'nw_index', 'ew_return', 'nw_return']].set_index('date')
            
        return sector_indices

    def _calc_rank_score(self, series: pd.Series) -> pd.Series:
        """将收益率截面序列映射为 0-100 的 RPS 分数"""
        # rank 升序排列（最小值为 1），如果数量为 N
        # 公式: (rank - 1) / (N - 1) * 100
        n = len(series.dropna())
        if n <= 1:
            return pd.Series(50.0, index=series.index)
        ranks = series.rank(ascending=True, na_option='bottom')
        return (ranks - 1.0) / (n - 1.0) * 100.0

    def calculate_rps(self, periods: list = [20, 60, 120]) -> dict:
        """
        计算全市场所有单品种（主力连续）以及各板块（持仓加权指数）的 RPS 评分。
        """
        df = self._get_daily_data()
        if df.empty:
            return {}
            
        # --- 1. 单品种 RPS 计算 ---
        # 重塑为宽表：行为日期，列为品种
        pivot_close = df.pivot(index='date', columns='symbol', values='close').ffill()
        
        symbol_rps_results = {}
        latest_date = pivot_close.index[-1]
        
        for N in periods:
            # 计算 N 日收益率
            # (P_t - P_{t-N}) / P_{t-N}
            returns_N = pivot_close.pct_change(periods=N)
            # 取最后一天的截面收益率
            latest_returns = returns_N.iloc[-1]
            
            # 计算 RPS 分数
            rps_score = self._calc_rank_score(latest_returns)
            symbol_rps_results[f'RPS_{N}'] = rps_score
            symbol_rps_results[f'Return_{N}'] = latest_returns
            
        symbol_rps_df = pd.DataFrame(symbol_rps_results)
        symbol_rps_df['sector'] = symbol_rps_df.index.map(lambda x: self._metadata_cache.loc[x, 'sector'] if x in self._metadata_cache.index else '未知')
        symbol_rps_df = symbol_rps_df.sort_values(by=f'RPS_{periods[0]}', ascending=False)
        
        # --- 2. 板块级别 RPS 计算 ---
        sector_indices = self.generate_sector_indices()
        if not sector_indices:
            return {'symbol_rps': symbol_rps_df, 'sector_rps': pd.DataFrame()}
            
        # 将 9 个板块的 nw_index (持仓金额加权指数) 提取为宽表
        sec_df_list = []
        for sec, s_data in sector_indices.items():
            s_data = s_data.copy()
            s_data.rename(columns={'nw_index': sec}, inplace=True)
            sec_df_list.append(s_data[sec])
            
        sector_pivot = pd.concat(sec_df_list, axis=1).ffill()
        
        sector_rps_results = {}
        for N in periods:
            returns_N = sector_pivot.pct_change(periods=N)
            latest_returns = returns_N.iloc[-1]
            rps_score = self._calc_rank_score(latest_returns)
            sector_rps_results[f'RPS_{N}'] = rps_score
            sector_rps_results[f'Return_{N}'] = latest_returns
            
        sector_rps_df = pd.DataFrame(sector_rps_results).sort_values(by=f'RPS_{periods[0]}', ascending=False)
        
        return {
            'target_date': latest_date,
            'symbol_rps': symbol_rps_df,
            'sector_rps': sector_rps_df
        }

    def get_sector_leaders_laggards(self, symbol_rps_df: pd.DataFrame, period: int = 20) -> dict:
        """
        分析各板块内部的强弱关系，提取出每个板块内 RPS 排名第一（龙头）和倒数第一（龙尾）的品种。
        返回: dict
        """
        rps_col = f'RPS_{period}'
        if rps_col not in symbol_rps_df.columns:
            return {}
            
        result = {}
        grouped = symbol_rps_df.groupby('sector')
        
        for sector, group in grouped:
            if group.empty or len(group.dropna(subset=[rps_col])) == 0:
                continue
                
            sorted_group = group.sort_values(by=rps_col, ascending=False)
            leader_symbol = sorted_group.index[0]
            leader_score = sorted_group.iloc[0][rps_col]
            
            laggard_symbol = sorted_group.index[-1]
            laggard_score = sorted_group.iloc[-1][rps_col]
            
            # 为了在板块内也计算相对强度，额外做一次组内 rank
            group_scores = self._calc_rank_score(group[f'Return_{period}'])
            leader_internal_score = group_scores.loc[leader_symbol]
            laggard_internal_score = group_scores.loc[laggard_symbol]
            
            result[sector] = {
                'leader': {
                    'symbol': leader_symbol,
                    'global_rps': leader_score,
                    'internal_rps': leader_internal_score,
                    'return': sorted_group.iloc[0][f'Return_{period}']
                },
                'laggard': {
                    'symbol': laggard_symbol,
                    'global_rps': laggard_score,
                    'internal_rps': laggard_internal_score,
                    'return': sorted_group.iloc[-1][f'Return_{period}']
                }
            }
            
        return result

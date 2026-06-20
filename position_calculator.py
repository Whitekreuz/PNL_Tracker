import pandas as pd
import numpy as np
import sqlite3
import math

class PositionCalculator:
    def __init__(self, db_path: str):
        self.db_path = db_path
        self._metadata_cache = None
        self._load_metadata()

    def _load_metadata(self):
        """加载品种元数据（乘数、保证金率、所属板块等）"""
        conn = sqlite3.connect(self.db_path)
        query = "SELECT symbol, sector, exchange, multiplier as contract_multiplier, margin_rate as long_margin_ratio FROM contract_metadata"
        self._metadata_cache = pd.read_sql(query, conn).set_index('symbol')
        conn.close()

    def get_symbol_metadata(self, symbol: str) -> dict:
        symbol = symbol.upper()
        if symbol not in self._metadata_cache.index:
            return None
        row = self._metadata_cache.loc[symbol]
        # 有些可能是重复条目（不同合约），取第一条
        if isinstance(row, pd.DataFrame):
            row = row.iloc[0]
            
        # 安全转换
        try:
            multiplier = float(row['contract_multiplier'])
        except (ValueError, TypeError):
            multiplier = 10.0
            
        try:
            long_margin = float(row['long_margin_ratio'])
        except (ValueError, TypeError):
            long_margin = 0.1
            
        return {
            'sector': row['sector'],
            'multiplier': multiplier,
            'margin_ratio': long_margin # 简化处理：默认使用多头保证金率
        }

    def calculate_target_var(self, drawdown_budget: float, risk_factor: float = 0.075, cppi_multiplier: float = 1.0) -> float:
        """
        计算账户总目标 VaR 限额
        :param drawdown_budget: 最大回撤容忍度 (D)
        :param risk_factor: 风险偏好系数 (k)，默认 7.5%
        :param cppi_multiplier: CPPI 动态安全垫乘数 (M)
        """
        base_target_var = drawdown_budget * risk_factor
        return base_target_var * cppi_multiplier

    def calculate_single_asset_lots(self, symbol: str, target_var: float, current_price: float, var_pct: float, 
                                    weight_alloc: float = 1.0) -> dict:
        """
        计算单品种在给定目标 VaR 下的基础开仓手数。
        """
        meta = self.get_symbol_metadata(symbol)
        if not meta:
            raise ValueError(f"找不到品种 {symbol} 的元数据")
            
        multiplier = meta['multiplier']
        margin_ratio = meta['margin_ratio']
        
        # 1. 计算单手合约的 VaR 金额
        unit_var = current_price * multiplier * var_pct
        
        if unit_var == 0:
            max_lots = 0
        else:
            # 2. 分配到的风险预算
            allocated_var = target_var * weight_alloc
            max_lots = math.floor(allocated_var / unit_var)
            
        # 3. 占用保证金
        notional_value = max_lots * current_price * multiplier
        margin_occupied = notional_value * margin_ratio
        
        return {
            'symbol': symbol.upper(),
            'sector': meta['sector'],
            'suggested_lots': max_lots,
            'unit_var': unit_var,
            'allocated_var': allocated_var,
            'margin_occupied': margin_occupied,
            'notional_value': notional_value
        }

    def evaluate_portfolio_risk(self, portfolio: dict, cov_matrix: pd.DataFrame, var_pct_dict: dict = None) -> dict:
        """
        评估投资组合级别的风险。
        :param portfolio: {'RB': {'lots': 10, 'direction': 1, 'price': 3500}, 'CU': {'lots': 5, 'direction': -1, 'price': 80000}}
        """
        symbols = list(portfolio.keys())
        
        # 构建名义敞口向量 W (包含方向)
        w_dict = {}
        total_margin = 0.0
        portfolio_sectors = {}
        
        for sym in symbols:
            meta = self.get_symbol_metadata(sym)
            if not meta:
                continue
                
            lots = portfolio[sym].get('lots', 0)
            direction = portfolio[sym].get('direction', 1)
            price = portfolio[sym].get('price', 0)
            
            w = lots * price * meta['multiplier'] * direction
            w_dict[sym] = w
            
            margin = abs(w) * meta['margin_ratio']
            total_margin += margin
            
            portfolio_sectors[sym] = meta['sector']
            
        # 对齐向量与协方差矩阵
        # 提取在 cov_matrix 中存在的品种
        valid_symbols = [s for s in symbols if s in cov_matrix.columns and s in w_dict]
        if not valid_symbols:
            return {'error': 'No valid symbols found in covariance matrix.'}
            
        W = np.array([w_dict[s] for s in valid_symbols])
        Sigma = cov_matrix.loc[valid_symbols, valid_symbols].values
        
        # 组合方差 = W^T * Sigma * W
        portfolio_variance = W.T @ Sigma @ W
        
        # 由于我们用的可能是 EWMA 计算出的日波动率/VaR，
        # 这里的 cov_matrix 应该是收益率的协方差。
        # 标准正态下的组合波动率金额
        portfolio_vol_amt = np.sqrt(max(portfolio_variance, 0))
        
        # 使用 99% 置信度 Z=2.326
        Z_99 = 2.3263478740408408
        portfolio_var = portfolio_vol_amt * Z_99
        
        # 计算 Component VaR
        # CVaR_i = w_i * (Sigma * W)_i / vol_amt * Z
        if portfolio_vol_amt > 0:
            marginal_vol = (Sigma @ W) / portfolio_vol_amt
            cvar_array = W * marginal_vol * Z_99
        else:
            cvar_array = np.zeros(len(valid_symbols))
            
        component_var = {sym: cvar_array[i] for i, sym in enumerate(valid_symbols)}
        
        # 计算板块 VaR 占比
        sector_var = {}
        for sym, cvar in component_var.items():
            sector = portfolio_sectors[sym]
            sector_var[sector] = sector_var.get(sector, 0) + cvar
            
        sector_ratios = {}
        sector_warnings = []
        if portfolio_var > 0:
            for sector, svar in sector_var.items():
                ratio = svar / portfolio_var
                sector_ratios[sector] = ratio
                if ratio > 0.40:
                    # 线性缩减近似：要使板块占比降至 40%，大致需要缩减的乘数 gamma
                    # 注意：这是对板块整体头寸的一阶近似缩减系数
                    gamma = (0.40 * portfolio_var) / svar
                    reduction_pct = (1 - gamma) * 100
                    sector_warnings.append({
                        'sector': sector,
                        'ratio': ratio,
                        'reduction_factor': 1 - gamma,
                        'message': f"板块 '{sector}' 的风险贡献占比达到 {ratio*100:.2f}%，超过 40% 的风控上限！建议该板块内所有多头/空头头寸同步削减约 {reduction_pct:.1f}% 的手数。"
                    })
                    
        return {
            'portfolio_var': portfolio_var,
            'component_var': component_var,
            'total_margin': total_margin,
            'sector_var_ratios': sector_ratios,
            'sector_warnings': sector_warnings
        }

    def check_correlation_penalty(self, target_symbol: str, portfolio_symbols: list, corr_matrix: pd.DataFrame, threshold: float = 0.7) -> list:
        """
        检查拟开仓品种与现有持仓中是否存在高相关性共振风险。
        返回超出阈值的品种列表及其相关系数。
        """
        target_symbol = target_symbol.upper()
        if target_symbol not in corr_matrix.columns:
            return []
            
        penalties = []
        for sym in portfolio_symbols:
            sym = sym.upper()
            if sym in corr_matrix.columns and sym != target_symbol:
                corr = corr_matrix.loc[target_symbol, sym]
                abs_corr = abs(corr)
                if abs_corr > threshold:
                    # 动态折算惩罚系数：在 threshold (如 0.7) 时不惩罚为 1.0，完全相关 1.0 时惩罚一半 (0.5)
                    # 线性插值公式
                    penalty = 1.0 - ((abs_corr - threshold) / (1.0 - threshold)) * 0.5
                    # 限制最小惩罚系数在 0.5
                    penalty = max(0.5, min(1.0, penalty))
                    penalties.append({
                        'symbol': sym,
                        'correlation': corr,
                        'penalty_factor': round(penalty, 2)
                    })
                    
        return penalties

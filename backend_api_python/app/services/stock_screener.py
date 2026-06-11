"""
A股批量选股引擎
对接腾讯行情API + akshare，在系统中完成通达信公式选股
"""
import json, re, time, threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import List, Dict, Optional
import requests
import pandas as pd
import numpy as np

from app.data_sources import DataSourceFactory
from app.utils.logger import get_logger

logger = get_logger(__name__)

# A股主板+创业板股票列表缓存
_STOCK_LIST_CACHE: Optional[List[Dict]] = None
_STOCK_LIST_LOCK = threading.Lock()
_CACHE_FILE = None  # set by init


def _get_cache_path():
    import os
    return os.path.join(os.path.dirname(__file__), '..', '..', 'data', 'a_stock_list.json')


def fetch_a_stock_list(force_refresh: bool = False) -> List[Dict]:
    """获取A股全量列表,缓存到本地JSON。仅含主板(60xxxx/00xxxx)和创业板(30xxxx)"""
    global _STOCK_LIST_CACHE
    cache_path = _get_cache_path()

    if not force_refresh and _STOCK_LIST_CACHE is not None:
        return _STOCK_LIST_CACHE

    # 尝试读缓存
    if not force_refresh and _STOCK_LIST_CACHE is None:
        try:
            with open(cache_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
                if len(data) > 3000:
                    _STOCK_LIST_CACHE = data
                    logger.info(f"Loaded {len(data)} stocks from cache")
                    return data
        except Exception:
            pass

    # 通过akshare获取
    stocks = []
    try:
        import akshare as ak
        df = ak.stock_info_a_code_name()
        for _, row in df.iterrows():
            code = str(row.get('code', '')).strip()
            name = str(row.get('name', '')).strip()
            if not code or len(code) != 6:
                continue
            # 仅保留主板和创业板
            if code.startswith(('60', '00', '30')):
                stocks.append({'code': code, 'name': name})
        logger.info(f"Fetched {len(stocks)} A-share stocks from akshare")
    except Exception as e:
        logger.warning(f"akshare fetch failed: {e}, using fallback list")
        # 回退：常用股票列表
        stocks = _fallback_stock_list()

    # 缓存
    try:
        import os
        os.makedirs(os.path.dirname(cache_path), exist_ok=True)
        with open(cache_path, 'w', encoding='utf-8') as f:
            json.dump(stocks, f, ensure_ascii=False)
    except Exception:
        pass

    _STOCK_LIST_CACHE = stocks
    return stocks


def _fallback_stock_list() -> List[Dict]:
    """akshare不可用时的回退列表（沪深300+中证500常见标的）"""
    codes = []
    # 沪深300部分
    for c in ['000001','000002','000333','000651','000725','000858','002024','002049','002142',
              '002230','002271','002304','002352','002415','002460','002466','002475','002594',
              '002714','002812','002920','300015','300033','300059','300122','300124','300274',
              '300285','300308','300316','300347','300390','300394','300408','300413','300433',
              '300442','300450','300454','300476','300502','300529','300540','300558','300595',
              '600000','600009','600016','600019','600021','600028','600030','600031','600036',
              '600048','600050','600085','600104','600111','600150','600196','600276','600309',
              '600340','600346','600352','600406','600415','600426','600436','600438','600482',
              '600489','600519','600547','600570','600585','600588','600690','600703','600745',
              '600809','600837','600887','600893','600900','600919','601006','601012','601088',
              '601111','601138','601166','601211','601225','601288','601318','601328','601390',
              '601398','601456','601601','601628','601633','601668','601688','601728','601766',
              '601800','601808','601857','601878','601899','601919','601939','601985','601988',
              '601998','603019','603129','603160','603259','603288','603369','603392','603501',
              '603589','603690','603799','603833','603899','603986','605117','605133','605358']:
        codes.append({'code': c, 'name': ''})
    return codes


# ============================================================
# 选股公式定义
# ============================================================

class ScreenFormula:
    """选股公式基类 — 子类实现 compute() 方法"""

    def __init__(self, name: str, description: str):
        self.name = name
        self.description = description

    def compute(self, df: pd.DataFrame) -> bool:
        """输入日线DataFrame(降序或升序均可,会自动排序),返回是否满足条件"""
        raise NotImplementedError


class GoldenCrossScreen(ScreenFormula):
    """金叉选股: ZXDQ上穿ZXDK 且 C<110"""

    def __init__(self):
        super().__init__("金叉选股", "白线上穿黄线金叉, C<110")

    def compute(self, df: pd.DataFrame) -> bool:
        if len(df) < 120:
            return False
        df = df.sort_index().copy()
        close = df["close"]
        zxdq = close.ewm(span=10, adjust=False).mean().ewm(span=10, adjust=False).mean()
        zxdk = (close.rolling(14).mean() + close.rolling(28).mean() +
                close.rolling(57).mean() + close.rolling(114).mean()) / 4.0
        # 最新bar: 金叉 + 股价限制
        last = len(df) - 1
        golden = (float(zxdq.iloc[last]) > float(zxdk.iloc[last]) and
                  float(zxdq.iloc[last-1]) <= float(zxdk.iloc[last-1]))
        return golden and float(close.iloc[last]) < 110


class BupiaoScreen(ScreenFormula):
    """补票选股: 长期>=94 AND 短期>=99 + ZXDQ>=ZXDK + C<250"""

    def __init__(self):
        super().__init__("补票选股", "长期>=94,短期>=99,趋势确认, C<250")

    def compute(self, df: pd.DataFrame) -> bool:
        if len(df) < 120:
            return False
        df = df.sort_index().copy()
        close = df["close"]
        high = df["high"]
        low = df["low"]
        vol = df["volume"]

        # 短期(3日)
        low_3 = low.rolling(3).min()
        high_3 = high.rolling(3).max()
        short_term = (close - low_3) / (high_3 - low_3) * 100.0
        short_term = short_term.fillna(50).clip(0, 100)

        # 长期(21日)
        low_21 = low.rolling(21).min()
        high_21 = high.rolling(21).max()
        long_term = (close - low_21) / (high_21 - low_21) * 100.0
        long_term = long_term.fillna(50).clip(0, 100)

        # 趋势线
        zxdq = close.ewm(span=10, adjust=False).mean().ewm(span=10, adjust=False).mean()
        zxdk = (close.rolling(14).mean() + close.rolling(28).mean() +
                close.rolling(57).mean() + close.rolling(114).mean()) / 4.0

        last = len(df) - 1
        return (float(long_term.iloc[last]) >= 94 and
                float(short_term.iloc[last]) >= 99 and
                float(zxdq.iloc[last]) >= float(zxdk.iloc[last]) and
                float(close.iloc[last]) < 250 and
                float(vol.iloc[last]) > 0)


# 注册公式
FORMULAS = {
    "golden_cross": GoldenCrossScreen(),
    "bupiao": BupiaoScreen(),
}


# ============================================================
# 选股引擎
# ============================================================

def screen_stocks(formula_key: str, stock_codes: Optional[List[str]] = None,
                  max_workers: int = 8, progress_callback=None) -> List[Dict]:
    """
    批量选股
    - formula_key: 'golden_cross' | 'bupiao'
    - stock_codes: 可选,限定股票范围;None=全市场
    - max_workers: 并发数
    - progress_callback: 进度回调 (current, total, symbol, match)
    """
    formula = FORMULAS.get(formula_key)
    if formula is None:
        raise ValueError(f"Unknown formula: {formula_key}")

    # 获取股票列表
    all_stocks = fetch_a_stock_list()
    if stock_codes:
        code_set = set(c.strip() for c in stock_codes)
        candidates = [s for s in all_stocks if s['code'] in code_set]
    else:
        candidates = all_stocks

    logger.info(f"Screening {len(candidates)} stocks with {formula.name}")
    results = []
    ds = DataSourceFactory.get_source("CNStock")
    total = len(candidates)

    def _check_one(stock):
        try:
            df = ds.get_kline(stock['code'], '1D', limit=150)
            if df is None or len(df) < 100:
                return None
            if formula.compute(df):
                last_close = float(df["close"].iloc[-1])
                return {'code': stock['code'], 'name': stock.get('name', ''), 'price': round(last_close, 2)}
            return None
        except Exception as e:
            logger.debug(f"Screen {stock['code']}: {e}")
            return None

    completed = 0
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {executor.submit(_check_one, s): s for s in candidates}
        for future in as_completed(futures):
            completed += 1
            try:
                match = future.result()
                if match:
                    results.append(match)
                if progress_callback:
                    progress_callback(completed, total, futures[future]['code'], match is not None)
            except Exception:
                pass

    results.sort(key=lambda x: x['code'])
    logger.info(f"Screen complete: {len(results)}/{total} matched")
    return results

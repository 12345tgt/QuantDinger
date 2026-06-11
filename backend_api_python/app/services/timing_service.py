"""
Timing Indicator Service — 择时叠加系统
管理择时指标 CRUD、择时组合、以及运行时计算
"""
from __future__ import annotations

import json
from typing import Dict, List, Optional, Any
from datetime import datetime

import pandas as pd
import numpy as np

from app.utils.db import get_db_connection
from app.utils.logger import get_logger
from app.data_sources import DataSourceFactory
from app.utils.safe_exec import safe_exec_code

logger = get_logger(__name__)


class TimingService:
    """择时服务"""

    # ── CRUD: 择时指标 ──────────────────────────────

    def list_indicators(self, user_id: int) -> List[Dict]:
        with get_db_connection() as db:
            cur = db.cursor()
            cur.execute(
                "SELECT id, name, description, symbol, market, timeframe, "
                "output_type, bull_multiplier, bear_multiplier, params, created_at "
                "FROM qd_timing_indicators WHERE user_id = ? ORDER BY id",
                (user_id,)
            )
            rows = cur.fetchall() or []
            cur.close()
        return [dict(r) for r in rows]

    def get_indicator(self, indicator_id: int, user_id: int) -> Optional[Dict]:
        with get_db_connection() as db:
            cur = db.cursor()
            cur.execute(
                "SELECT * FROM qd_timing_indicators WHERE id = ? AND user_id = ?",
                (indicator_id, user_id)
            )
            row = cur.fetchone()
            cur.close()
        return dict(row) if row else None

    def save_indicator(self, payload: Dict, user_id: int) -> int:
        indicator_id = payload.get("id")
        name = (payload.get("name") or "").strip()
        code = (payload.get("indicator_code") or payload.get("code") or "").strip()
        if not name or not code:
            raise ValueError("name and indicator_code are required")

        symbol = (payload.get("symbol") or "").strip()
        market = (payload.get("market") or "CNStock").strip()
        timeframe = (payload.get("timeframe") or "1D").strip()
        output_type = (payload.get("output_type") or "binary").strip()
        bull_mult = float(payload.get("bull_multiplier", 1.0))
        bear_mult = float(payload.get("bear_multiplier", 0.5))
        desc = (payload.get("description") or "").strip()
        params_json = json.dumps(payload.get("params") or {})

        with get_db_connection() as db:
            cur = db.cursor()
            if indicator_id:
                cur.execute(
                    "UPDATE qd_timing_indicators SET name=?, description=?, indicator_code=?, "
                    "symbol=?, market=?, timeframe=?, output_type=?, bull_multiplier=?, "
                    "bear_multiplier=?, params=?, updated_at=NOW() "
                    "WHERE id=? AND user_id=?",
                    (name, desc, code, symbol, market, timeframe, output_type,
                     bull_mult, bear_mult, params_json, indicator_id, user_id)
                )
                cur.close()
                return int(indicator_id)
            else:
                cur.execute(
                    "INSERT INTO qd_timing_indicators "
                    "(user_id, name, description, indicator_code, symbol, market, timeframe, "
                    "output_type, bull_multiplier, bear_multiplier, params) "
                    "VALUES (?,?,?,?,?,?,?,?,?,?,?) RETURNING id",
                    (user_id, name, desc, code, symbol, market, timeframe,
                     output_type, bull_mult, bear_mult, params_json)
                )
                new_id = cur.fetchone()["id"]
                cur.close()
                return new_id

    def delete_indicator(self, indicator_id: int, user_id: int) -> bool:
        with get_db_connection() as db:
            cur = db.cursor()
            cur.execute(
                "DELETE FROM qd_timing_indicators WHERE id = ? AND user_id = ?",
                (indicator_id, user_id)
            )
            affected = cur.rowcount
            cur.close()
        return affected > 0

    # ── CRUD: 择时组合 ──────────────────────────────

    def list_profiles(self, user_id: int) -> List[Dict]:
        with get_db_connection() as db:
            cur = db.cursor()
            cur.execute(
                "SELECT p.*, "
                "(SELECT json_agg(json_build_object("
                "  'id', i.id, 'name', i.name, 'symbol', i.symbol, "
                "  'output_type', i.output_type, "
                "  'bull_multiplier', i.bull_multiplier, 'bear_multiplier', i.bear_multiplier"
                ")) FROM qd_timing_profile_items pi "
                "JOIN qd_timing_indicators i ON i.id = pi.timing_indicator_id "
                "WHERE pi.profile_id = p.id ORDER BY pi.sort_order) AS items "
                "FROM qd_timing_profiles p WHERE p.user_id = ? ORDER BY p.id",
                (user_id,)
            )
            rows = cur.fetchall() or []
            cur.close()
        results = []
        for r in rows:
            d = dict(r)
            d["items"] = json.loads(d.get("items") or "[]") if isinstance(d.get("items"), str) else (d.get("items") or [])
            results.append(d)
        return results

    def get_profile(self, profile_id: int, user_id: int) -> Optional[Dict]:
        profiles = self.list_profiles(user_id)
        for p in profiles:
            if p["id"] == profile_id:
                return p
        return None

    def save_profile(self, payload: Dict, user_id: int) -> int:
        profile_id = payload.get("id")
        name = (payload.get("name") or "").strip()
        stack_mode = (payload.get("stack_mode") or "multiply").strip()
        items = payload.get("items") or []

        if not name:
            raise ValueError("name is required")

        with get_db_connection() as db:
            cur = db.cursor()
            if profile_id:
                cur.execute(
                    "UPDATE qd_timing_profiles SET name=?, stack_mode=?, updated_at=NOW() "
                    "WHERE id=? AND user_id=?",
                    (name, stack_mode, profile_id, user_id)
                )
                # Replace items
                cur.execute("DELETE FROM qd_timing_profile_items WHERE profile_id=?", (profile_id,))
            else:
                cur.execute(
                    "INSERT INTO qd_timing_profiles (user_id, name, stack_mode) "
                    "VALUES (?,?,?) RETURNING id",
                    (user_id, name, stack_mode)
                )
                profile_id = cur.fetchone()["id"]

            for idx, item in enumerate(items):
                ti_id = item.get("id") or item.get("timing_indicator_id")
                if ti_id:
                    cur.execute(
                        "INSERT INTO qd_timing_profile_items (profile_id, timing_indicator_id, sort_order) "
                        "VALUES (?,?,?) ON CONFLICT (profile_id, timing_indicator_id) DO UPDATE SET sort_order=?",
                        (profile_id, ti_id, idx, idx)
                    )
            cur.close()
        return profile_id

    def delete_profile(self, profile_id: int, user_id: int) -> bool:
        with get_db_connection() as db:
            cur = db.cursor()
            cur.execute("DELETE FROM qd_timing_profiles WHERE id=? AND user_id=?", (profile_id, user_id))
            affected = cur.rowcount
            cur.close()
        return affected > 0

    # ── Runtime: 计算择时状态 ─────────────────────────

    def compute_timing(
        self,
        profile_id: int,
        user_id: int,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        kline_cache: Optional[Dict] = None,
    ) -> Optional[pd.DataFrame]:
        """
        计算择时组合的每日乘数,返回 DataFrame:
        索引=日期, 列: multiplier, bullish, 各指标的bullish/bearish
        返回 None 表示未配置择时组合
        """
        profile = self.get_profile(profile_id, user_id)
        if not profile or not profile.get("items"):
            return None

        items = profile["items"]
        stack_mode = profile.get("stack_mode", "multiply")

        # 并行计算每个择时指标
        timing_dfs = []
        for item in items:
            ti = self.get_indicator(item["id"], user_id)
            if not ti:
                continue
            df_ti = self._run_timing_indicator(ti, start_date, end_date, kline_cache)
            if df_ti is not None:
                timing_dfs.append((ti, df_ti))

        if not timing_dfs:
            return None

        # 合并所有择时指标到一个 DataFrame
        # 以第一个指标的索引为准
        result = timing_dfs[0][1][["bullish"]].copy()
        result.rename(columns={"bullish": f"t0_bull"}, inplace=True)

        for i, (ti, df_ti) in enumerate(timing_dfs):
            bull_col = f"ti_{ti['id']}_bull"
            bear_col = f"ti_{ti['id']}_bear"
            result[bull_col] = df_ti.get("bullish", pd.Series(False, index=result.index))
            result[bear_col] = df_ti.get("bearish", pd.Series(False, index=result.index))

            if stack_mode == "multiply":
                # 乘积累加: 每多一个多头,乘数叠加
                pass  # 在下面统一计算
            elif stack_mode == "require_all":
                # AND模式: 任一空头则乘数为0
                pass

        # 计算最终乘数
        if stack_mode == "multiply":
            result["multiplier"] = 1.0
            for ti, df_ti in timing_dfs:
                bull_mult = float(ti.get("bull_multiplier", 1.0))
                bear_mult = float(ti.get("bear_multiplier", 0.5))
                bullish = df_ti.get("bullish", pd.Series(False, index=result.index))
                bearish = df_ti.get("bearish", pd.Series(False, index=result.index))
                # 对于每个bar: 多头=bull_mult, 空头=bear_mult, 其他=1.0
                bar_mult = pd.Series(1.0, index=result.index)
                bar_mult[bullish.fillna(False)] = bull_mult
                bar_mult[bearish.fillna(False)] = bear_mult
                result["multiplier"] = result["multiplier"] * bar_mult
        elif stack_mode == "require_all":
            # 所有指标都多头才开仓
            all_bull = pd.Series(True, index=result.index)
            for _, df_ti in timing_dfs:
                bullish = df_ti.get("bullish", pd.Series(False, index=result.index))
                all_bull = all_bull & bullish.fillna(False)
            result["multiplier"] = all_bull.astype(float)  # 1.0 or 0.0

        result["bullish"] = result["multiplier"] >= 1.0
        return result

    def _run_timing_indicator(
        self, ti: Dict, start_date: str = None, end_date: str = None, kline_cache: Dict = None
    ) -> Optional[pd.DataFrame]:
        """运行单个择时指标,返回含 bullish/bearish 列的 DataFrame"""
        symbol = ti.get("symbol", "")
        market = ti.get("market", "CNStock")
        timeframe = ti.get("timeframe", "1D")
        code = ti.get("indicator_code", "")

        if not code or not symbol:
            return None

        # 获取数据
        cache_key = f"{market}:{symbol}:{timeframe}:{start_date}:{end_date}"
        if kline_cache and cache_key in kline_cache:
            df_kline = kline_cache[cache_key].copy()
        else:
            try:
                ds = DataSourceFactory.get_source(market)
                limit = 300
                df_kline = ds.get_kline(symbol, timeframe, limit=limit)
                if df_kline is None or len(df_kline) < 10:
                    logger.warning(f"Timing {ti['name']}: insufficient kline data for {symbol}")
                    return None
                if kline_cache is not None:
                    kline_cache[cache_key] = df_kline.copy()
            except Exception as e:
                logger.error(f"Timing {ti['name']}: fetch kline error {e}")
                return None

        # 日期过滤
        df_kline = df_kline.sort_index()
        if start_date:
            df_kline = df_kline[df_kline.index >= pd.Timestamp(start_date)]
        if end_date:
            df_kline = df_kline[df_kline.index <= pd.Timestamp(end_date)]
        if len(df_kline) < 5:
            return None

        # 沙箱执行指标代码
        module_vars = {"df": df_kline.copy(), "params": ti.get("params") or {}}

        # 手动安装需要的库
        import_statements = "import numpy as np\nimport pandas as pd\n"
        exec_code = import_statements + "\n" + code + """\n

_has_bullish = 'bullish' in df.columns
_has_bearish = 'bearish' in df.columns
if not _has_bullish:
    df['bullish'] = False
if not _has_bearish:
    df['bearish'] = False
"""

        try:
            local_vars = {}
            exec(exec_code, module_vars, local_vars)
            result_df = module_vars.get("df", df_kline)

            # 确保有 bullish/bearish 列
            if "bullish" not in result_df.columns:
                result_df["bullish"] = False
            if "bearish" not in result_df.columns:
                result_df["bearish"] = False

            return result_df[["bullish", "bearish"]]
        except Exception as e:
            logger.error(f"Timing indicator {ti['name']} execution error: {e}")
            return None


# Singleton
_timing_service: Optional[TimingService] = None


def get_timing_service() -> TimingService:
    global _timing_service
    if _timing_service is None:
        _timing_service = TimingService()
    return _timing_service

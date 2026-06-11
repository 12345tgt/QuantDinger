"""
择时指标管理 API
"""
from flask import Blueprint, request, jsonify, g
from app.utils.auth import login_required
from app.services.timing_service import get_timing_service
from app.utils.logger import get_logger

logger = get_logger(__name__)

timing_bp = Blueprint('timing', __name__, url_prefix='/api/timing')


@timing_bp.route('/indicators', methods=['GET'])
@login_required
def list_indicators():
    ts = get_timing_service()
    items = ts.list_indicators(g.user_id)
    return jsonify({'code': 1, 'msg': 'ok', 'data': items})


@timing_bp.route('/indicators', methods=['POST'])
@login_required
def save_indicator():
    data = request.get_json() or {}
    try:
        tid = get_timing_service().save_indicator(data, g.user_id)
        return jsonify({'code': 1, 'msg': 'success', 'data': {'id': tid}})
    except ValueError as e:
        return jsonify({'code': 0, 'msg': str(e), 'data': None})


@timing_bp.route('/indicators/<int:indicator_id>', methods=['DELETE'])
@login_required
def delete_indicator(indicator_id):
    ok = get_timing_service().delete_indicator(indicator_id, g.user_id)
    return jsonify({'code': 1 if ok else 0, 'msg': 'deleted' if ok else 'not found'})


@timing_bp.route('/indicators/<int:indicator_id>/test', methods=['POST'])
@login_required
def test_indicator(indicator_id):
    """测试运行择时指标,返回计算出的序列供前端绘图"""
    data = request.get_json() or {}
    start = data.get('startDate', '')
    end = data.get('endDate', '')

    ts = get_timing_service()
    ti = ts.get_indicator(indicator_id, g.user_id)
    if not ti:
        return jsonify({'code': 0, 'msg': 'indicator not found', 'data': None})

    # 获取K线数据并运行指标
    import pandas as pd
    from app.data_sources import DataSourceFactory

    try:
        ds = DataSourceFactory.get_source(ti.get('market', 'CNStock'))
        df_kline = ds.get_kline(ti['symbol'], ti.get('timeframe', '1D'), limit=300)
        if df_kline is None or len(df_kline) < 5:
            return jsonify({'code': 0, 'msg': 'Insufficient data', 'data': None})

        df_kline = df_kline.sort_index()
        if start:
            df_kline = df_kline[df_kline.index >= pd.Timestamp(start)]
        if end:
            df_kline = df_kline[df_kline.index <= pd.Timestamp(end)]

        exec_code = "import numpy as np\nimport pandas as pd\n" + (ti.get('indicator_code') or '')
        exec_code += "\nif 'bullish' not in df.columns:\n    df['bullish'] = False\n"
        exec_code += "if 'bearish' not in df.columns:\n    df['bearish'] = False\n"
        exec_code += "if 'multiplier' not in df.columns:\n    df['multiplier'] = 1.0\n"

        module_vars = {"df": df_kline.copy(), "params": ti.get("params") or {}}
        exec(exec_code, module_vars)
        result_df = module_vars["df"]

        # 返回时间序列数据
        dates = [str(d) for d in result_df.index]
        return jsonify({'code': 1, 'msg': 'ok', 'data': {
            'dates': dates,
            'bullish': [bool(v) for v in result_df.get('bullish', [False]*len(dates))],
            'bearish': [bool(v) for v in result_df.get('bearish', [False]*len(dates))],
            'multiplier': [float(v) for v in result_df.get('multiplier', [1.0]*len(dates))],
        }})
    except Exception as e:
        logger.error(f"Test timing indicator error: {e}")
        return jsonify({'code': 0, 'msg': str(e), 'data': None})


@timing_bp.route('/profiles', methods=['GET'])
@login_required
def list_profiles():
    items = get_timing_service().list_profiles(g.user_id)
    return jsonify({'code': 1, 'msg': 'ok', 'data': items})


@timing_bp.route('/profiles', methods=['POST'])
@login_required
def save_profile():
    data = request.get_json() or {}
    try:
        pid = get_timing_service().save_profile(data, g.user_id)
        return jsonify({'code': 1, 'msg': 'success', 'data': {'id': pid}})
    except ValueError as e:
        return jsonify({'code': 0, 'msg': str(e), 'data': None})


@timing_bp.route('/profiles/<int:profile_id>', methods=['DELETE'])
@login_required
def delete_profile(profile_id):
    ok = get_timing_service().delete_profile(profile_id, g.user_id)
    return jsonify({'code': 1 if ok else 0, 'msg': 'deleted' if ok else 'not found'})

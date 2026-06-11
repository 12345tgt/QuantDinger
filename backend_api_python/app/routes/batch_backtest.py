"""
批量回测+选股 Web 页面
"""
from flask import Blueprint, request, jsonify
from app.utils.logger import get_logger

logger = get_logger(__name__)

batch_bp = Blueprint('batch_backtest', __name__, url_prefix='/api/batch-backtest')

BATCH_PAGE = '''<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
<title>选股+回测</title>
<style>
*{box-sizing:border-box;margin:0;padding:0}
body{font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;background:#0d1117;color:#c9d1d9;padding:16px;min-height:100vh}
h2{font-size:18px;margin-bottom:8px;color:#58a6ff}
.tabs{display:flex;gap:8px;margin-bottom:16px}
.tab{padding:8px 16px;border-radius:6px;border:1px solid #30363d;background:#161b22;color:#8b949e;font-size:14px;cursor:pointer}
.tab.active{background:#1f6feb;color:#fff;border-color:#1f6feb}
label{display:block;font-size:13px;color:#8b949e;margin-bottom:4px;margin-top:12px}
textarea{width:100%;height:100px;background:#161b22;border:1px solid #30363d;border-radius:6px;color:#c9d1d9;padding:10px;font-size:14px;resize:vertical;font-family:monospace}
select,input[type=text]{width:100%;background:#161b22;border:1px solid #30363d;border-radius:6px;color:#c9d1d9;padding:10px;font-size:14px}
.btn{width:100%;padding:14px;background:#238636;color:#fff;border:none;border-radius:6px;font-size:16px;font-weight:600;margin-top:12px;cursor:pointer}
.btn:disabled{background:#30363d;color:#8b949e}
.btn2{background:#21262d;border:1px solid #30363d;color:#c9d1d9;margin-top:8px}
.panel{display:none}
.panel.active{display:block}
.result{margin-top:16px}
table{width:100%;border-collapse:collapse;font-size:12px;margin-top:8px}
th{background:#161b22;padding:8px 6px;text-align:right;border-bottom:2px solid #30363d;font-weight:500;color:#8b949e;font-size:11px}
th:first-child,td:first-child{text-align:left}
td{padding:7px 6px;border-bottom:1px solid #21262d;text-align:right;font-variant-numeric:tabular-nums}
.good{color:#3fb950}.bad{color:#f85149}.warn{color:#d2991d}
.summary{background:#161b22;border-radius:6px;padding:12px;margin-top:12px;font-size:13px}
.spin{display:inline-block;width:14px;height:14px;border:2px solid #30363d;border-top-color:#58a6ff;border-radius:50%;animation:spin .6s linear infinite;margin-right:6px;vertical-align:middle}
@keyframes spin{to{transform:rotate(360deg)}}
.status{margin-top:8px;font-size:13px;color:#8b949e;max-height:200px;overflow-y:auto}
.match{display:inline-block;padding:2px 8px;margin:2px;background:#1a3a2a;border-radius:4px;font-size:12px;cursor:pointer}
.match.selected{background:#1f6feb}
</style>
</head>
<body>
<h2>选股 + 批量回测</h2>

<div class="tabs">
  <div class="tab active" onclick="switchTab('screen')">自动选股</div>
  <div class="tab" onclick="switchTab('manual')">手动粘贴</div>
</div>

<!-- 自动选股面板 -->
<div id="screen" class="panel active">
  <label>选股公式</label>
  <select id="screenFormula">
    <option value="golden_cross">金叉选股</option>
    <option value="bupiao" selected>补票选股</option>
  </select>

  <label>限定范围 (可选,留空=全市场)</label>
  <textarea id="screenScope" placeholder="留空扫描全A股,或限定范围&#10;600021&#10;600519"></textarea>

  <button class="btn" id="screenBtn" onclick="runScreen()">开始选股</button>
  <div class="status" id="screenStatus"></div>
  <div id="screenMatches"></div>

  <div id="btPanel" style="display:none">
    <label>回测起始日期</label>
    <input type="text" id="btStartDate" value="2024-09-24">
    <label>回测策略</label>
    <select id="btIndicator">
      <option value="2">金叉选股</option>
      <option value="3" selected>补票选股</option>
    </select>
    <button class="btn btn2" id="btBtn" onclick="runBatchFromScreen()">对选中股票批量回测</button>
  </div>
</div>

<!-- 手动粘贴面板 -->
<div id="manual" class="panel">
  <label>回测策略</label>
  <select id="mIndicator">
    <option value="2">金叉选股</option>
    <option value="3" selected>补票选股</option>
  </select>
  <label>起始日期</label>
  <input type="text" id="mStartDate" value="2024-09-24">
  <label>股票代码</label>
  <textarea id="mSymbols" placeholder="空格/换行/逗号分隔&#10;600021&#10;600519&#10;000001"></textarea>
  <button class="btn" id="mBtn" onclick="runManual()">开始批量回测</button>
</div>

<div class="result" id="result"></div>

<script>
const BASE = window.location.origin + '/api';
let TOKEN = '';
let screenMatches = [];
let selectedCodes = new Set();

(async function(){
  try{
    const r = await fetch(BASE+'/auth/login',{
      method:'POST',
      headers:{'Content-Type':'application/json'},
      body:JSON.stringify({username:'quantdinger',password:'123456'})
    });
    const d = await r.json();
    TOKEN = d.data?.token || '';
  }catch(e){}
})();

function switchTab(t){
  document.querySelectorAll('.tab').forEach(el=>el.classList.remove('active'));
  event.target.classList.add('active');
  document.querySelectorAll('.panel').forEach(el=>el.classList.remove('active'));
  document.getElementById(t).classList.add('active');
}

function runScreen(){
  const formula = document.getElementById('screenFormula').value;
  const scope = document.getElementById('screenScope').value
    .split(/[\\s,;，；、\\n]+/).map(s=>s.trim()).filter(s=>/^\\d{6}$/.test(s));
  const st = document.getElementById('screenStatus');
  const btn = document.getElementById('screenBtn');
  btn.disabled = true;
  btn.innerHTML = '<span class="spin"></span>选股中...';
  st.innerHTML = '正在获取股票列表...';

  fetch(BASE+'/batch-backtest/screen',{
    method:'POST',
    headers:{'Content-Type':'application/json','Authorization':'Bearer '+TOKEN},
    body:JSON.stringify({formula:formula, stocks:scope.length?scope:null})
  }).then(r=>r.json()).then(d=>{
    if(d.code===1){
      screenMatches = d.data.matches || [];
      st.innerHTML = `选股完成: 共扫描 ${d.data.total} 只, 命中 <b>${screenMatches.length}</b> 只`;
      let html = '<div style="margin-top:8px">';
      screenMatches.forEach(m=>{
        const sel = selectedCodes.has(m.code);
        html += `<span class="match${sel?' selected':''}" onclick="toggleCode('${m.code}')" id="m_${m.code}">${m.code} ${m.name||''} ${m.price}</span> `;
      });
      html += '</div><div style="margin-top:8px;font-size:12px;color:#8b949e">点击代码选中/取消, 已选 <b id="selCount">${selectedCodes.size}</b> 只</div>';
      document.getElementById('screenMatches').innerHTML = html;
      document.getElementById('btPanel').style.display = 'block';
    }else{
      st.innerHTML = `选股失败: ${d.msg}`;
    }
    btn.disabled = false;
    btn.textContent = '开始选股';
  }).catch(e=>{
    st.innerHTML = `网络错误: ${e.message}`;
    btn.disabled = false;
    btn.textContent = '开始选股';
  });
}

function toggleCode(code){
  if(selectedCodes.has(code)) selectedCodes.delete(code);
  else selectedCodes.add(code);
  document.getElementById('m_'+code).classList.toggle('selected');
  document.getElementById('selCount').textContent = selectedCodes.size;
}

function runBatchFromScreen(){
  if(selectedCodes.size===0){
    // 全选
    screenMatches.forEach(m=>selectedCodes.add(m.code));
    document.getElementById('selCount').textContent = selectedCodes.size;
  }
  const symbols = Array.from(selectedCodes);
  runBacktest(symbols, document.getElementById('btIndicator').value, document.getElementById('btStartDate').value);
}

function runManual(){
  const symbols = document.getElementById('mSymbols').value
    .split(/[\\s,;，；、\\n]+/).map(s=>s.trim()).filter(s=>/^\\d{6}$/.test(s));
  if(!symbols.length){alert('请输入有效的6位股票代码');return}
  runBacktest(symbols, document.getElementById('mIndicator').value, document.getElementById('mStartDate').value);
}

async function runBacktest(symbols, indicatorId, startDate){
  const resultDiv = document.getElementById('result');
  resultDiv.innerHTML = `<div style="color:#8b949e;margin-top:12px"><span class="spin"></span>正在回测 ${symbols.length} 只股票...</div>`;

  const results = [];
  for(let i=0; i<symbols.length; i++){
    const sym = symbols[i];
    resultDiv.innerHTML = `<div style="color:#8b949e;margin-top:12px"><span class="spin"></span>[${i+1}/${symbols.length}] ${sym} ...</div>`;
    try{
      const r = await fetch(BASE+'/indicator/backtest',{
        method:'POST',
        headers:{'Content-Type':'application/json','Authorization':'Bearer '+TOKEN},
        body:JSON.stringify({
          indicatorId:parseInt(indicatorId), symbol:sym, market:'CNStock', timeframe:'1D',
          startDate:startDate||'2024-09-24', endDate:'2026-06-11',
          initialCapital:100000, commission:0.0003, slippage:0.001, leverage:1, tradeDirection:'long', persist:false
        })
      });
      const d = await r.json();
      if(d.code===1){
        const rd = d.data.result;
        results.push({symbol:sym, totalReturn:rd.totalReturn||0, annualReturn:rd.annualReturn||0,
          maxDrawdown:rd.maxDrawdown||0, sharpeRatio:rd.sharpeRatio||0, winRate:rd.winRate||0,
          totalTrades:rd.totalTrades||0, totalProfit:rd.totalProfit||0});
      }else{results.push({symbol:sym,error:d.msg||'unknown'});}
    }catch(e){results.push({symbol:sym,error:e.message});}
    await new Promise(r=>setTimeout(r,200));  // 避免API过载
  }

  const valid = results.filter(r=>!r.error&&r.totalTrades>0);
  const zeroTrades = results.filter(r=>!r.error&&r.totalTrades===0);
  const errors = results.filter(r=>r.error);
  valid.sort((a,b)=>b.totalReturn-a.totalReturn);

  let html = `<table><thead><tr><th>代码</th><th>总收益%</th><th>年化%</th><th>回撤%</th><th>夏普</th><th>胜率%</th><th>交易</th><th>盈亏</th></tr></thead><tbody>`;
  for(const r of valid){
    const cls = r.totalReturn>20?'good':r.totalReturn<0?'bad':'warn';
    html += `<tr><td>${r.symbol}</td><td class="${cls}">${r.totalReturn.toFixed(1)}%</td>
      <td>${r.annualReturn.toFixed(1)}%</td><td>${r.maxDrawdown.toFixed(1)}%</td>
      <td>${r.sharpeRatio.toFixed(2)}</td><td>${r.winRate.toFixed(0)}%</td>
      <td>${r.totalTrades}</td><td>${r.totalProfit.toFixed(0)}</td></tr>`;
  }
  html += '</tbody></table>';
  if(zeroTrades.length) html += `<div style="margin-top:8px;color:#8b949e">无信号: ${zeroTrades.map(r=>r.symbol).join(', ')}</div>`;
  if(errors.length) html += `<div style="margin-top:8px;color:#f85149">失败: ${errors.map(r=>r.symbol+':'+r.error).join(', ')}</div>`;
  const avgRet = valid.length ? (valid.reduce((s,r)=>s+r.totalReturn,0)/valid.length).toFixed(1) : '0';
  html += `<div class="summary">共 ${results.length} 只 | 有交易 ${valid.length} 只 | 平均收益 ${avgRet}% | 无信号 ${zeroTrades.length} 只</div>`;
  resultDiv.innerHTML = html;
}
</script>
</body>
</html>'''


# ===== Flask API Routes =====
from flask import jsonify, request as flask_request
from app.services.stock_screener import screen_stocks, fetch_a_stock_list, FORMULAS

@batch_bp.route('/screen', methods=['POST'])
def api_screen():
    """选股API"""
    try:
        data = flask_request.get_json() or {}
        formula_key = data.get('formula', 'bupiao')
        stock_codes = data.get('stocks')  # None = 全市场

        if formula_key not in FORMULAS:
            return jsonify({'code': 0, 'msg': f'Unknown formula: {formula_key}', 'data': None})

        all_stocks = fetch_a_stock_list()
        total = len(all_stocks)

        matches = screen_stocks(formula_key, stock_codes, max_workers=6)

        return jsonify({'code': 1, 'msg': 'ok', 'data': {
            'total': total, 'matches': matches, 'formula': FORMULAS[formula_key].name
        }})
    except Exception as e:
        logger.error(f"Screen error: {e}")
        return jsonify({'code': 0, 'msg': str(e), 'data': None})


@batch_bp.route('/page', methods=['GET'])
def batch_page():
    return BATCH_PAGE


@batch_bp.route('/stock-count', methods=['GET'])
def api_stock_count():
    """获取股票池大小"""
    try:
        stocks = fetch_a_stock_list()
        return jsonify({'code': 1, 'msg': 'ok', 'data': {'count': len(stocks)}})
    except Exception as e:
        return jsonify({'code': 0, 'msg': str(e), 'data': None})

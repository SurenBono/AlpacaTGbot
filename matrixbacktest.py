from flask import Flask, render_template_string, request, jsonify
import yfinance as yf
import pandas as pd
import numpy as np
import warnings
warnings.filterwarnings('ignore')

app = Flask(__name__)

def run_ut_bot(symbol, start_date, end_date, sensitivity, atr_period, leverage):
    """Run UT Bot backtest and return results"""
    
    df = yf.download(symbol, start=start_date, end=end_date, progress=False)
    
    if df.empty:
        return None
    
    closes = df['Close'].values.flatten()
    highs = df['High'].values.flatten()
    lows = df['Low'].values.flatten()
    dates = df.index.strftime('%Y-%m-%d').tolist()
    
    # Calculate ATR
    n = len(closes)
    tr = np.zeros(n)
    
    for i in range(1, n):
        hl = highs[i] - lows[i]
        hc = abs(highs[i] - closes[i-1])
        lc = abs(lows[i] - closes[i-1])
        tr[i] = max(hl, hc, lc)
    
    atr = np.zeros(n)
    for i in range(atr_period, n):
        atr[i] = np.mean(tr[i-atr_period:i])
    
    # Calculate trailing stop
    nloss = sensitivity * atr
    stop = np.zeros(n)
    stop[0] = closes[0] - nloss[0]
    
    for i in range(1, n):
        close = closes[i]
        prev_close = closes[i-1]
        prev_stop = stop[i-1]
        nloss_val = nloss[i]
        
        if close > prev_stop and prev_close > prev_stop:
            stop[i] = max(prev_stop, close - nloss_val)
        elif close < prev_stop and prev_close < prev_stop:
            stop[i] = min(prev_stop, close + nloss_val)
        elif close > prev_stop:
            stop[i] = close - nloss_val
        else:
            stop[i] = close + nloss_val
    
    # Generate signals
    buy_signals = []
    sell_signals = []
    
    for i in range(1, n):
        if closes[i] > stop[i] and closes[i-1] <= stop[i-1]:
            buy_signals.append(i)
        elif closes[i] < stop[i] and closes[i-1] >= stop[i-1]:
            sell_signals.append(i)
    
    # Backtest
    capital = 10000.0
    position = 0
    entry_price = 0.0
    trades = []
    
    for i in range(1, n):
        price = closes[i]
        
        if i in buy_signals and position == 0:
            position = 1
            entry_price = price
            trades.append({
                'date': dates[i],
                'type': 'BUY',
                'price': float(price),
                'exit_price': None,
                'pnl': None
            })
        
        elif i in sell_signals and position == 1:
            pnl_pct = (price - entry_price) / entry_price * 100 * leverage
            capital = capital * (1 + pnl_pct / 100)
            trades[-1]['exit_price'] = float(price)
            trades[-1]['pnl'] = float(pnl_pct)
            position = 0
    
    if position == 1:
        final_price = closes[-1]
        pnl_pct = (final_price - entry_price) / entry_price * 100 * leverage
        capital = capital * (1 + pnl_pct / 100)
        trades[-1]['exit_price'] = float(final_price)
        trades[-1]['pnl'] = float(pnl_pct)
    
    total_return = (capital - 10000) / 10000 * 100
    
    prices = [float(x) for x in closes]
    stops = [float(x) for x in stop]
    
    buy_dates = [dates[i] for i in buy_signals]
    buy_prices = [float(closes[i]) for i in buy_signals]
    
    sell_dates = [dates[i] for i in sell_signals]
    sell_prices = [float(closes[i]) for i in sell_signals]
    
    completed_trades = len([t for t in trades if t['exit_price'] is not None])
    
    return {
        'success': True,
        'dates': dates,
        'prices': prices,
        'stops': stops,
        'buy_dates': buy_dates,
        'buy_prices': buy_prices,
        'sell_dates': sell_dates,
        'sell_prices': sell_prices,
        'trades': trades,
        'total_return': round(float(total_return), 2),
        'final_equity': round(float(capital), 2),
        'total_trades': completed_trades
    }

# ==================== HTML TEMPLATE WITH FIXED ALIGNMENT ====================

HTML = '''
<!DOCTYPE html>
<html>
<head>
    <title>UT Bot Backtest</title>
    <meta name="viewport" content="width=device-width, initial-scale=1.0, user-scalable=yes">
    <script src="https://cdn.plot.ly/plotly-3.0.1.min.js" charset="utf-8"></script>
    <style>
        * { box-sizing: border-box; }
        body {
            background: #0a0a0a;
            color: #00ff00;
            font-family: 'Courier New', monospace;
            padding: 10px;
            margin: 0;
        }
        .container { 
            max-width: 1400px; 
            margin: 0 auto;
            width: 100%;
        }
        h1 {
            text-align: center;
            color: #00ff00;
            border-bottom: 2px solid #00ff00;
            display: inline-block;
            margin: 0 auto 20px;
            padding-bottom: 8px;
            font-size: 20px;
        }
        .header { text-align: center; margin-bottom: 20px; }
        .panel {
            background: #111111;
            border: 1px solid #00ff00;
            padding: 15px;
            margin-bottom: 20px;
            border-radius: 8px;
        }
        .grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(130px, 1fr));
            gap: 12px;
            margin-bottom: 15px;
        }
        .item { display: flex; flex-direction: column; }
        label {
            font-size: 9px;
            color: #00ff00aa;
            margin-bottom: 4px;
        }
        input, select {
            background: #1a1a1a;
            border: 1px solid #00ff00;
            color: #00ff00;
            padding: 6px;
            font-family: monospace;
            font-size: 11px;
            border-radius: 4px;
        }
        button {
            background: #1a1a1a;
            border: 1px solid #00ff00;
            color: #00ff00;
            padding: 10px 25px;
            font-family: monospace;
            font-size: 14px;
            cursor: pointer;
            border-radius: 5px;
        }
        button:hover {
            background: #00ff00;
            color: #000000;
        }
        .metrics {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
            gap: 12px;
            margin-bottom: 20px;
        }
        .card {
            background: #111111;
            border: 1px solid #00ff00;
            padding: 12px;
            text-align: center;
            border-radius: 8px;
        }
        .card h3 {
            font-size: 10px;
            color: #00ff00aa;
            margin: 0 0 6px 0;
        }
        .value { font-size: 22px; font-weight: bold; }
        .positive { color: #00ff00; text-shadow: 0 0 5px #00ff00; }
        .negative { color: #ff4444; text-shadow: 0 0 5px #ff4444; }
        .chart {
            background: #111111;
            border: 1px solid #00ff00;
            padding: 12px;
            margin-bottom: 20px;
            border-radius: 8px;
        }
        .chart h3 {
            margin: 0 0 10px 0;
            font-size: 11px;
            color: #00ff00aa;
        }
        .hidden { display: none; }
        .loading {
            position: fixed;
            top: 50%;
            left: 50%;
            transform: translate(-50%, -50%);
            background: #000000;
            border: 2px solid #00ff00;
            padding: 25px 40px;
            text-align: center;
            z-index: 1000;
            border-radius: 10px;
        }
        .loading-text { font-size: 16px; margin-bottom: 8px; }
        .loading-small { font-size: 10px; color: #00ff00aa; }
        
        /* Fixed Table Styles - Proper Alignment */
        .table-container {
            overflow-x: auto;
            width: 100%;
            margin-top: 10px;
            -webkit-overflow-scrolling: touch;
        }
        table {
            width: 100%;
            min-width: 650px;
            border-collapse: collapse;
            font-size: 11px;
            font-family: 'Courier New', monospace;
        }
        th {
            background: #1a1a1a;
            color: #00ff00;
            padding: 10px 6px;
            text-align: center;
            border: 1px solid #00ff00;
            font-weight: bold;
            position: sticky;
            top: 0;
            white-space: nowrap;
        }
        td {
            padding: 8px 6px;
            text-align: center;
            border-bottom: 1px solid #333;
        }
        tr:hover {
            background: #1a3a1a;
        }
        .trade-profit {
            color: #00ff00;
            font-weight: bold;
        }
        .trade-loss {
            color: #ff4444;
            font-weight: bold;
        }
        .price-cell {
            text-align: right;
            font-family: monospace;
            white-space: nowrap;
        }
        .date-cell {
            text-align: center;
            white-space: nowrap;
            font-size: 10px;
        }
        .type-cell {
            text-align: center;
            font-weight: bold;
        }
        .number-cell {
            text-align: right;
            white-space: nowrap;
        }
        .center-cell {
            text-align: center;
        }
        
        @keyframes blink {
            0%, 100% { opacity: 1; }
            50% { opacity: 0; }
        }
        .cursor {
            display: inline-block;
            width: 8px;
            height: 14px;
            background: #00ff00;
            animation: blink 1s infinite;
            margin-left: 5px;
        }
        
        /* Scrollbar */
        ::-webkit-scrollbar {
            width: 6px;
            height: 6px;
        }
        ::-webkit-scrollbar-track {
            background: #1a1a1a;
        }
        ::-webkit-scrollbar-thumb {
            background: #00ff00;
            border-radius: 3px;
        }
        
        @media (max-width: 768px) {
            body { padding: 5px; }
            .value { font-size: 18px; }
            th { font-size: 9px; padding: 6px 3px; }
            td { font-size: 9px; padding: 6px 3px; }
            table { min-width: 550px; }
        }
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>UT BOT BACKTEST <span class="cursor"></span></h1>
        </div>
        
        <div class="panel">
            <div class="grid">
                <div class="item">
                    <label>SYMBOL</label>
                    <select id="symbol">
                        <option value="BTC-USD">BTC/USD</option>
                        <option value="ETH-USD">ETH/USD</option>
                        <option value="SOL-USD">SOL/USD</option>
                    </select>
                </div>
                <div class="item">
                    <label>START DATE</label>
                    <input type="date" id="start_date" value="2023-01-01">
                </div>
                <div class="item">
                    <label>END DATE</label>
                    <input type="date" id="end_date" value="2025-05-17">
                </div>
                <div class="item">
                    <label>SENSITIVITY</label>
                    <input type="number" id="sensitivity" value="1" step="0.5" min="0.5" max="5">
                </div>
                <div class="item">
                    <label>ATR PERIOD</label>
                    <input type="number" id="atr_period" value="7" step="1" min="5" max="21">
                </div>
                <div class="item">
                    <label>LEVERAGE</label>
                    <input type="number" id="leverage" value="2" step="1" min="1" max="5">
                </div>
            </div>
            <div style="text-align: center;">
                <button onclick="runBacktest()">▶ RUN BACKTEST</button>
            </div>
        </div>
        
        <div id="results" class="hidden">
            <div class="metrics" id="metrics"></div>
            <div class="chart">
                <h3>PRICE CHART WITH SIGNALS</h3>
                <div id="priceChart"></div>
            </div>
            <div class="chart">
                <h3>TRADE HISTORY</h3>
                <div class="table-container" id="tradesTable"></div>
            </div>
        </div>
    </div>
    
    <div id="loading" class="hidden loading">
        <div class="loading-text">>> PROCESSING <<</div>
        <div class="loading-small">Downloading data... first run takes 5-10 seconds</div>
    </div>
    
    <script>
        async function runBacktest() {
            document.getElementById('loading').classList.remove('hidden');
            document.getElementById('results').classList.add('hidden');
            
            const data = {
                symbol: document.getElementById('symbol').value,
                start_date: document.getElementById('start_date').value,
                end_date: document.getElementById('end_date').value,
                sensitivity: parseFloat(document.getElementById('sensitivity').value),
                atr_period: parseInt(document.getElementById('atr_period').value),
                leverage: parseFloat(document.getElementById('leverage').value)
            };
            
            try {
                const response = await fetch('/backtest', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(data)
                });
                
                const result = await response.json();
                
                document.getElementById('loading').classList.add('hidden');
                
                if (result.success) {
                    displayResults(result);
                    document.getElementById('results').classList.remove('hidden');
                } else {
                    alert('Error: ' + (result.error || 'Unknown error'));
                }
            } catch (error) {
                document.getElementById('loading').classList.add('hidden');
                alert('Error: ' + error.message);
            }
        }
        
        function formatNumber(num) {
            return '$' + num.toLocaleString('en-US', {minimumFractionDigits: 2, maximumFractionDigits: 2});
        }
        
        function formatNumberShort(num) {
            return num.toLocaleString('en-US', {minimumFractionDigits: 0, maximumFractionDigits: 0});
        }
        
        function formatPnl(pnl) {
            if (pnl === null || pnl === undefined) return '--';
            return pnl.toFixed(2) + '%';
        }
        
        function displayResults(data) {
            const returnClass = data.total_return >= 0 ? 'positive' : 'negative';
            
            document.getElementById('metrics').innerHTML = `
                <div class="card">
                    <h3>TOTAL RETURN</h3>
                    <div class="value ${returnClass}">${data.total_return.toFixed(2)}%</div>
                </div>
                <div class="card">
                    <h3>FINAL EQUITY</h3>
                    <div class="value positive">${formatNumber(data.final_equity)}</div>
                </div>
                <div class="card">
                    <h3>TOTAL TRADES</h3>
                    <div class="value">${data.total_trades}</div>
                </div>
            `;
            
            // Chart
            const trace1 = {
                x: data.dates,
                y: data.prices,
                mode: 'lines',
                name: 'Price',
                line: { color: '#00ff00', width: 1.5 }
            };
            
            const trace2 = {
                x: data.buy_dates,
                y: data.buy_prices,
                mode: 'markers',
                name: 'BUY',
                marker: { color: '#00ff00', size: 10, symbol: 'triangle-up' }
            };
            
            const trace3 = {
                x: data.sell_dates,
                y: data.sell_prices,
                mode: 'markers',
                name: 'SELL',
                marker: { color: '#ff4444', size: 10, symbol: 'triangle-down' }
            };
            
            const trace4 = {
                x: data.dates,
                y: data.stops,
                mode: 'lines',
                name: 'Trailing Stop',
                line: { color: '#ffaa00', width: 1, dash: 'dash' }
            };
            
            const layout = {
                paper_bgcolor: '#111111',
                plot_bgcolor: '#111111',
                font: { color: '#00ff00', family: 'monospace', size: 10 },
                xaxis: { 
                    gridcolor: '#333333', 
                    title: 'Date',
                    tickangle: -45
                },
                yaxis: { 
                    gridcolor: '#333333', 
                    title: 'Price (USD)',
                    tickformat: '$,.0f'
                },
                showlegend: true,
                legend: { x: 0, y: 1, bgcolor: 'rgba(0,0,0,0.7)', font: { size: 9 } },
                margin: { l: 50, r: 30, t: 30, b: 50 }
            };
            
            Plotly.newPlot('priceChart', [trace1, trace2, trace3, trace4], layout, {responsive: true});
            
            // Trades table with proper formatting
            let tableHtml = `
                <table>
                    <thead>
                        <tr>
                            <th>#</th>
                            <th>DATE</th>
                            <th>TYPE</th>
                            <th>ENTRY ($)</th>
                            <th>EXIT ($)</th>
                            <th>P&L (%)</th>
                        </tr>
                    </thead>
                    <tbody>
            `;
            
            let tradeCount = 0;
            for (const trade of data.trades) {
                tradeCount++;
                const pnlClass = trade.pnl && trade.pnl >= 0 ? 'trade-profit' : 'trade-loss';
                const pnlDisplay = formatPnl(trade.pnl);
                const exitDisplay = trade.exit_price ? formatNumber(trade.exit_price) : '--';
                
                tableHtml += `
                    <tr>
                        <td class="center-cell" style="color:#666">${tradeCount}</td>
                        <td class="date-cell">${trade.date}</td>
                        <td class="type-cell" style="color:${trade.type === 'BUY' ? '#00ff00' : '#ff4444'}">${trade.type}</td>
                        <td class="number-cell">${formatNumber(trade.price)}</td>
                        <td class="number-cell">${exitDisplay}</td>
                        <td class="center-cell ${pnlClass}">${pnlDisplay}</td>
                    </tr>
                `;
            }
            
            tableHtml += `
                    </tbody>
                </table>
            `;
            
            document.getElementById('tradesTable').innerHTML = tableHtml;
        }
    </script>
</body>
</html>
'''

@app.route('/')
def index():
    return render_template_string(HTML)

@app.route('/backtest', methods=['POST'])
def backtest():
    try:
        data = request.json
        print(f"\n📊 Backtest started for {data['symbol']}")
        
        result = run_ut_bot(
            symbol=data['symbol'],
            start_date=data['start_date'],
            end_date=data['end_date'],
            sensitivity=data['sensitivity'],
            atr_period=data['atr_period'],
            leverage=data['leverage']
        )
        
        if result is None:
            return jsonify({'success': False, 'error': 'No data available'})
        
        print(f"   ✅ Return: {result['total_return']:.2f}% | Trades: {result['total_trades']}")
        
        return jsonify(result)
        
    except Exception as e:
        print(f"   ❌ Error: {e}")
        return jsonify({'success': False, 'error': str(e)})

if __name__ == '__main__':
    print("\n" + "="*50)
    print("🟢 UT BOT BACKTEST SERVER")
    print("="*50)
    print("\n✅ Server is running!")
    print("\n🌐 Open in browser:")
    print("   http://localhost:5000")
    print("   or http://192.168.0.170:5000")
    print("="*50 + "\n")
    
    app.run(host='0.0.0.0', port=5000, debug=False)

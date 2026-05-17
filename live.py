from flask import Flask, render_template_string, request, jsonify, session
import yfinance as yf
import pandas as pd
import numpy as np
import datetime as dt
import time
import threading
import json
import warnings
warnings.filterwarnings('ignore')

app = Flask(__name__)
app.secret_key = 'ut_bot_secret_key_2024'

# Default configuration
default_config = {
    'symbol': 'BTC-USD',
    'timeframe': '1d',
    'sensitivity': 1.0,
    'atr_period': 7,
    'leverage': 2,
    'taker_fee': 0.06,
    'maker_fee': 0.02,
    'starting_balance': 10000,
    'trade_direction': 'both',  # 'long_only', 'short_only', 'both'
    'position_size_pct': 10,    # % of capital per trade
    'auto_refresh': 60,         # seconds
    'status': 'Waiting for config'
}

# Global variables
live_data = {
    'price': 0,
    'signal': 'HOLD',
    'stop': 0,
    'atr': 0,
    'last_update': '',
    'timestamp': '',
    'recommendation': '',
    'entry_zone': '',
    'stop_loss': '',
    'take_profit_1': '',
    'take_profit_2': '',
    'chart_dates': [],
    'chart_prices': [],
    'chart_stops': []
}

signal_history = []
current_config = default_config.copy()
monitor_running = True

# ==================== UT BOT ENGINE ====================

def calculate_ut_bot(df, sensitivity, atr_period):
    """Calculate UT Bot signals"""
    if df is None or df.empty or len(df) < atr_period + 10:
        return None
    
    closes = df['Close'].values.flatten()
    highs = df['High'].values.flatten()
    lows = df['Low'].values.flatten()
    dates = df.index.strftime('%Y-%m-%d').tolist()
    
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
    
    return {
        'closes': closes,
        'stops': stop,
        'atr_values': atr,
        'dates': dates,
        'n': n
    }

def get_current_signal(df, sensitivity, atr_period, trade_direction):
    """Get current signal based on trade direction"""
    result = calculate_ut_bot(df, sensitivity, atr_period)
    if not result:
        return None
    
    closes = result['closes']
    stops = result['stops']
    atr_values = result['atr_values']
    
    current_price = closes[-1]
    current_stop = stops[-1]
    prev_price = closes[-2]
    prev_stop = stops[-2]
    
    # Determine raw signal
    if current_price > current_stop and prev_price <= prev_stop:
        raw_signal = "BUY"
    elif current_price < current_stop and prev_price >= prev_stop:
        raw_signal = "SELL"
    else:
        raw_signal = "HOLD"
    
    # Apply trade direction filter
    if trade_direction == 'long_only':
        signal = "BUY" if raw_signal == "BUY" else "HOLD"
    elif trade_direction == 'short_only':
        signal = "SELL" if raw_signal == "SELL" else "HOLD"
    else:
        signal = raw_signal
    
    return {
        'price': current_price,
        'signal': signal,
        'raw_signal': raw_signal,
        'stop': current_stop,
        'atr': atr_values[-1],
        'dates': result['dates'][-50:],
        'prices': [float(x) for x in closes[-50:]],
        'stops': [float(x) for x in stops[-50:]]
    }

def fetch_data(symbol, timeframe, days=100):
    """Fetch historical data"""
    end = dt.datetime.now()
    
    # Map timeframe to yfinance interval and days
    timeframe_map = {
        '1h': ('1h', 7),
        '4h': ('1h', 30),  # Will resample to 4h
        '1d': ('1d', 365),
        '1w': ('1wk', 730)
    }
    
    interval, default_days = timeframe_map.get(timeframe, ('1d', 365))
    start = end - dt.timedelta(days=days)
    
    df = yf.download(symbol, start=start, end=end, interval=interval, progress=False)
    
    if df.empty:
        return None
    
    # Resample for 4h
    if timeframe == '4h' and interval == '1h':
        df = df.resample('4H').agg({
            'Open': 'first',
            'High': 'max',
            'Low': 'min',
            'Close': 'last',
            'Volume': 'sum'
        }).dropna()
    
    df.columns = ['Open', 'High', 'Low', 'Close', 'Volume']
    return df

def update_live_data():
    """Update live data in background thread"""
    global live_data, signal_history, current_config, monitor_running
    
    while monitor_running:
        try:
            config = current_config.copy()
            
            # Fetch data
            df = fetch_data(config['symbol'], config['timeframe'], days=150)
            
            if df is None or df.empty:
                live_data['status'] = 'Error: No data'
                time.sleep(30)
                continue
            
            # Get signal
            result = get_current_signal(df, config['sensitivity'], config['atr_period'], config['trade_direction'])
            
            if result:
                current_price = result['price']
                current_stop = result['stop']
                signal = result['signal']
                raw_signal = result['raw_signal']
                
                # Calculate trading levels
                if signal == "BUY":
                    entry_zone = f"${current_price:,.0f} - ${current_price * 1.01:,.0f}"
                    stop_loss = f"${current_stop:,.0f}"
                    take_profit_1 = f"${current_price * (1 + 0.05 * config['leverage']):,.0f}"
                    take_profit_2 = f"${current_price * (1 + 0.10 * config['leverage']):,.0f}"
                    recommendation = f"LONG ENTRY (Leverage: {config['leverage']}x)"
                elif signal == "SELL":
                    entry_zone = f"${current_price:,.0f} - ${current_price * 0.99:,.0f}"
                    stop_loss = f"${current_stop:,.0f}"
                    take_profit_1 = f"${current_price * (1 - 0.05 * config['leverage']):,.0f}"
                    take_profit_2 = f"${current_price * (1 - 0.10 * config['leverage']):,.0f}"
                    recommendation = f"SHORT ENTRY (Leverage: {config['leverage']}x)"
                else:
                    entry_zone = "Waiting for signal"
                    stop_loss = f"${current_stop:,.0f}"
                    take_profit_1 = "N/A"
                    take_profit_2 = "N/A"
                    recommendation = "NO ACTION - HOLD"
                
                # Update live data
                live_data = {
                    'price': current_price,
                    'signal': signal,
                    'raw_signal': raw_signal,
                    'stop': current_stop,
                    'atr': result['atr'],
                    'last_update': dt.datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                    'timestamp': dt.datetime.now().strftime('%H:%M:%S'),
                    'recommendation': recommendation,
                    'entry_zone': entry_zone,
                    'stop_loss': stop_loss,
                    'take_profit_1': take_profit_1,
                    'take_profit_2': take_profit_2,
                    'chart_dates': result['dates'],
                    'chart_prices': result['prices'],
                    'chart_stops': result['stops'],
                    'status': 'Active'
                }
                
                # Record signal change
                if signal_history and signal_history[-1]['signal'] != signal:
                    signal_history.append({
                        'timestamp': live_data['last_update'],
                        'signal': signal,
                        'raw_signal': raw_signal,
                        'price': current_price,
                        'stop': current_stop
                    })
                    if len(signal_history) > 20:
                        signal_history.pop(0)
                elif not signal_history:
                    signal_history.append({
                        'timestamp': live_data['last_update'],
                        'signal': signal,
                        'raw_signal': raw_signal,
                        'price': current_price,
                        'stop': current_stop
                    })
                
                print(f"[{live_data['last_update']}] {signal} @ ${current_price:,.0f} | Stop: ${current_stop:,.0f} | {config['trade_direction']}")
            
            # Wait before next update
            time.sleep(config.get('auto_refresh', 60))
            
        except Exception as e:
            print(f"Monitor error: {e}")
            time.sleep(30)

# Start background thread
monitor_thread = threading.Thread(target=update_live_data, daemon=True)
monitor_thread.start()

# ==================== HTML TEMPLATE ====================

HTML = '''
<!DOCTYPE html>
<html>
<head>
    <title>UT Bot Live Trading Studio</title>
    <meta name="viewport" content="width=device-width, initial-scale=1.0, user-scalable=yes">
    <script src="https://cdn.plot.ly/plotly-3.0.1.min.js" charset="utf-8"></script>
    <style>
        * { box-sizing: border-box; }
        body {
            background: #0a0a0a;
            color: #00ff00;
            font-family: 'Courier New', monospace;
            padding: 15px;
            margin: 0;
        }
        .container { max-width: 1400px; margin: 0 auto; }
        
        /* Header */
        .header {
            text-align: center;
            margin-bottom: 20px;
            border-bottom: 2px solid #00ff00;
            padding-bottom: 10px;
        }
        h1 {
            color: #00ff00;
            display: inline-block;
            margin: 0;
            font-size: 22px;
        }
        .subtitle {
            font-size: 10px;
            color: #00ff00aa;
            margin-top: 5px;
        }
        .cursor {
            display: inline-block;
            width: 8px;
            height: 14px;
            background: #00ff00;
            animation: blink 1s infinite;
            margin-left: 5px;
        }
        
        /* Control Panel */
        .control-panel {
            background: #111111;
            border: 1px solid #00ff00;
            border-radius: 10px;
            padding: 15px;
            margin-bottom: 20px;
        }
        .config-grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(140px, 1fr));
            gap: 12px;
            margin-bottom: 15px;
        }
        .config-item {
            display: flex;
            flex-direction: column;
        }
        .config-item label {
            font-size: 9px;
            color: #00ff00aa;
            margin-bottom: 4px;
        }
        .config-item input, .config-item select {
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
            padding: 8px 20px;
            font-family: monospace;
            font-size: 12px;
            cursor: pointer;
            border-radius: 5px;
        }
        button:hover {
            background: #00ff00;
            color: #000000;
        }
        
        /* Signal Card */
        .signal-card {
            background: #111111;
            border: 2px solid #00ff00;
            border-radius: 12px;
            padding: 20px;
            margin-bottom: 20px;
            text-align: center;
        }
        .signal-buy {
            background: #003300;
            border-color: #00ff00;
            box-shadow: 0 0 20px #00ff00;
        }
        .signal-sell {
            background: #330000;
            border-color: #ff4444;
            box-shadow: 0 0 20px #ff4444;
        }
        .signal-hold {
            background: #1a1a00;
            border-color: #ffaa00;
        }
        .signal-text {
            font-size: 48px;
            font-weight: bold;
            letter-spacing: 5px;
        }
        .signal-buy .signal-text { color: #00ff00; text-shadow: 0 0 10px #00ff00; }
        .signal-sell .signal-text { color: #ff4444; text-shadow: 0 0 10px #ff4444; }
        .signal-hold .signal-text { color: #ffaa00; text-shadow: 0 0 10px #ffaa00; }
        
        .price-main {
            font-size: 36px;
            font-weight: bold;
            margin: 10px 0;
        }
        .stop-price {
            font-size: 18px;
            margin: 5px 0;
        }
        
        /* Metrics Grid */
        .metrics-grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
            gap: 12px;
            margin-bottom: 20px;
        }
        .metric-card {
            background: #111111;
            border: 1px solid #00ff00;
            padding: 10px;
            text-align: center;
            border-radius: 8px;
        }
        .metric-card h4 {
            font-size: 9px;
            color: #00ff00aa;
            margin: 0 0 6px 0;
        }
        .metric-value {
            font-size: 18px;
            font-weight: bold;
        }
        
        /* Recommendation Card */
        .rec-card {
            background: #111111;
            border: 1px solid #00ff00;
            padding: 15px;
            margin-bottom: 20px;
            border-radius: 8px;
        }
        .rec-card h3 {
            margin: 0 0 10px 0;
            font-size: 12px;
            color: #00ff00;
        }
        .rec-row {
            display: flex;
            justify-content: space-between;
            padding: 6px 0;
            border-bottom: 1px solid #333;
        }
        .rec-label {
            color: #00ff00aa;
            font-size: 11px;
        }
        .rec-value {
            font-size: 12px;
            font-weight: bold;
        }
        
        /* Chart */
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
        
        /* Table */
        .table-container {
            overflow-x: auto;
            margin-top: 10px;
        }
        table {
            width: 100%;
            min-width: 500px;
            border-collapse: collapse;
            font-size: 10px;
        }
        th, td {
            padding: 6px;
            text-align: center;
            border-bottom: 1px solid #333;
        }
        th {
            color: #00ff00;
            border-bottom: 2px solid #00ff00;
        }
        
        .status-bar {
            background: #0a0a0a;
            border-top: 1px solid #00ff00;
            padding: 10px;
            margin-top: 20px;
            text-align: center;
            font-size: 9px;
            color: #00ff00aa;
        }
        
        @keyframes blink {
            0%, 100% { opacity: 1; }
            50% { opacity: 0; }
        }
        .blink {
            animation: blink 1s infinite;
        }
        
        @media (max-width: 768px) {
            .signal-text { font-size: 32px; }
            .price-main { font-size: 28px; }
            .metric-value { font-size: 14px; }
        }
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>UT BOT LIVE TRADING STUDIO <span class="cursor"></span></h1>
            <div class="subtitle">FULLY CONFIGURABLE | REAL-TIME SIGNALS</div>
        </div>
        
        <!-- Control Panel -->
        <div class="control-panel">
            <div class="config-grid">
                <div class="config-item">
                    <label>SYMBOL</label>
                    <select id="symbol">
                        <option value="BTC-USD">BTC/USD</option>
                        <option value="ETH-USD">ETH/USD</option>
                        <option value="SOL-USD">SOL/USD</option>
                        <option value="BNB-USD">BNB/USD</option>
                        <option value="XRP-USD">XRP/USD</option>
                    </select>
                </div>
                <div class="config-item">
                    <label>TIMEFRAME</label>
                    <select id="timeframe">
                        <option value="1h">1 Hour</option>
                        <option value="4h">4 Hours</option>
                        <option value="1d">1 Day</option>
                        <option value="1w">1 Week</option>
                    </select>
                </div>
                <div class="config-item">
                    <label>SENSITIVITY</label>
                    <input type="number" id="sensitivity" value="1" step="0.5" min="0.5" max="5">
                </div>
                <div class="config-item">
                    <label>ATR PERIOD</label>
                    <input type="number" id="atr_period" value="7" step="1" min="5" max="21">
                </div>
            </div>
            <div class="config-grid">
                <div class="config-item">
                    <label>LEVERAGE</label>
                    <input type="number" id="leverage" value="2" step="1" min="1" max="10">
                </div>
                <div class="config-item">
                    <label>TRADE DIRECTION</label>
                    <select id="trade_direction">
                        <option value="both">Both (Long & Short)</option>
                        <option value="long_only">Long Only</option>
                        <option value="short_only">Short Only</option>
                    </select>
                </div>
                <div class="config-item">
                    <label>REFRESH (seconds)</label>
                    <input type="number" id="auto_refresh" value="60" step="30" min="30" max="300">
                </div>
                <div class="config-item">
                    <label>POSITION SIZE (%)</label>
                    <input type="number" id="position_size" value="10" step="5" min="5" max="50">
                </div>
            </div>
            <div style="text-align: center;">
                <button onclick="applyConfig()">▶ APPLY CONFIGURATION</button>
                <button onclick="resetConfig()">⟳ RESET</button>
            </div>
        </div>
        
        <!-- Signal Card -->
        <div id="signalCard" class="signal-card signal-hold">
            <div class="signal-text" id="signalText">--</div>
            <div class="price-main" id="priceDisplay">--</div>
            <div class="stop-price" id="stopDisplay">Stop: --</div>
        </div>
        
        <!-- Metrics -->
        <div class="metrics-grid">
            <div class="metric-card">
                <h4>ATR</h4>
                <div class="metric-value" id="atrValue">--</div>
            </div>
            <div class="metric-card">
                <h4>LAST UPDATE</h4>
                <div class="metric-value" id="updateTime" style="font-size: 11px;">--</div>
            </div>
            <div class="metric-card">
                <h4>STATUS</h4>
                <div class="metric-value blink" id="status">--</div>
            </div>
            <div class="metric-card">
                <h4>DIRECTION</h4>
                <div class="metric-value" id="direction">--</div>
            </div>
        </div>
        
        <!-- Recommendation -->
        <div class="rec-card">
            <h3>📊 TRADING RECOMMENDATION</h3>
            <div class="rec-row">
                <span class="rec-label">ACTION:</span>
                <span class="rec-value" id="recommendation">--</span>
            </div>
            <div class="rec-row">
                <span class="rec-label">ENTRY ZONE:</span>
                <span class="rec-value" id="entryZone">--</span>
            </div>
            <div class="rec-row">
                <span class="rec-label">STOP LOSS:</span>
                <span class="rec-value" id="stopLoss">--</span>
            </div>
            <div class="rec-row">
                <span class="rec-label">TAKE PROFIT 1:</span>
                <span class="rec-value" id="tp1">--</span>
            </div>
            <div class="rec-row">
                <span class="rec-label">TAKE PROFIT 2:</span>
                <span class="rec-value" id="tp2">--</span>
            </div>
        </div>
        
        <!-- Chart -->
        <div class="chart">
            <h3>📈 PRICE CHART WITH TRAILING STOP</h3>
            <div id="priceChart"></div>
        </div>
        
        <!-- Signal History -->
        <div class="chart">
            <h3>📋 SIGNAL HISTORY</h3>
            <div class="table-container">
                <div id="historyTable"></div>
            </div>
        </div>
        
        <div class="status-bar">
            ⚡ LIVE MODE | Updates every configured seconds | UT Bot Active
        </div>
    </div>
    
    <script>
        function formatNumber(num) {
            if (!num) return '--';
            return '$' + num.toLocaleString('en-US', {minimumFractionDigits: 0, maximumFractionDigits: 0});
        }
        
        function applyConfig() {
            const config = {
                symbol: document.getElementById('symbol').value,
                timeframe: document.getElementById('timeframe').value,
                sensitivity: parseFloat(document.getElementById('sensitivity').value),
                atr_period: parseInt(document.getElementById('atr_period').value),
                leverage: parseFloat(document.getElementById('leverage').value),
                trade_direction: document.getElementById('trade_direction').value,
                auto_refresh: parseInt(document.getElementById('auto_refresh').value),
                position_size: parseFloat(document.getElementById('position_size').value)
            };
            
            fetch('/api/apply_config', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(config)
            })
            .then(response => response.json())
            .then(data => {
                if (data.success) {
                    alert('Configuration applied! Refreshing data...');
                    setTimeout(updateDisplay, 1000);
                } else {
                    alert('Error: ' + data.error);
                }
            });
        }
        
        function resetConfig() {
            document.getElementById('sensitivity').value = 1;
            document.getElementById('atr_period').value = 7;
            document.getElementById('leverage').value = 2;
            document.getElementById('trade_direction').value = 'both';
            document.getElementById('auto_refresh').value = 60;
            document.getElementById('position_size').value = 10;
            applyConfig();
        }
        
        function updateDisplay() {
            fetch('/api/live_data')
                .then(response => response.json())
                .then(data => {
                    // Update signal card
                    const signalCard = document.getElementById('signalCard');
                    signalCard.className = 'signal-card signal-' + data.signal.toLowerCase();
                    document.getElementById('signalText').innerText = data.signal;
                    document.getElementById('priceDisplay').innerHTML = formatNumber(data.price);
                    document.getElementById('stopDisplay').innerHTML = 'Stop: ' + formatNumber(data.stop);
                    
                    // Update metrics
                    document.getElementById('atrValue').innerHTML = '$' + (data.atr || 0).toFixed(0);
                    document.getElementById('updateTime').innerHTML = data.last_update;
                    document.getElementById('status').innerHTML = data.status;
                    
                    let directionText = '';
                    if (data.trade_direction === 'long_only') directionText = 'LONG ONLY';
                    else if (data.trade_direction === 'short_only') directionText = 'SHORT ONLY';
                    else directionText = 'BOTH';
                    document.getElementById('direction').innerHTML = directionText;
                    
                    // Update recommendation
                    document.getElementById('recommendation').innerHTML = data.recommendation;
                    document.getElementById('entryZone').innerHTML = data.entry_zone;
                    document.getElementById('stopLoss').innerHTML = data.stop_loss;
                    document.getElementById('tp1').innerHTML = data.take_profit_1;
                    document.getElementById('tp2').innerHTML = data.take_profit_2;
                    
                    // Update chart
                    if (data.chart_dates && data.chart_prices && data.chart_stops) {
                        const trace1 = {
                            x: data.chart_dates,
                            y: data.chart_prices,
                            mode: 'lines',
                            name: 'Price',
                            line: { color: '#00ff00', width: 1.5 }
                        };
                        const trace2 = {
                            x: data.chart_dates,
                            y: data.chart_stops,
                            mode: 'lines',
                            name: 'Trailing Stop',
                            line: { color: '#ffaa00', width: 1, dash: 'dash' }
                        };
                        const layout = {
                            paper_bgcolor: '#111111',
                            plot_bgcolor: '#111111',
                            font: { color: '#00ff00', family: 'monospace', size: 10 },
                            xaxis: { gridcolor: '#333333', tickangle: -45 },
                            yaxis: { gridcolor: '#333333', tickformat: '$,.0f' },
                            showlegend: true,
                            margin: { l: 50, r: 30, t: 20, b: 50 }
                        };
                        Plotly.newPlot('priceChart', [trace1, trace2], layout, {responsive: true});
                    }
                    
                    // Update history table
                    if (data.history && data.history.length > 0) {
                        let html = '<table><thead><tr><th>Time</th><th>Signal</th><th>Raw Signal</th><th>Price</th><th>Stop</th></tr></thead><tbody>';
                        for (const h of data.history.slice(-10).reverse()) {
                            const signalColor = h.signal === 'BUY' ? '#00ff00' : (h.signal === 'SELL' ? '#ff4444' : '#ffaa00');
                            const rawColor = h.raw_signal === 'BUY' ? '#00ff00' : (h.raw_signal === 'SELL' ? '#ff4444' : '#ffaa00');
                            html += `<tr>
                                <td>${h.timestamp.split(' ')[1]}${h.timestamp.split(' ')[0] ? '' : ''}</td>
                                <td style="color:${signalColor}">${h.signal}</td>
                                <td style="color:${rawColor}">${h.raw_signal}</td>
                                <td>${formatNumber(h.price)}</td>
                                <td>${formatNumber(h.stop)}</td>
                            </tr>`;
                        }
                        html += '</tbody></table>';
                        document.getElementById('historyTable').innerHTML = html;
                    }
                });
        }
        
        // Initial load
        setTimeout(updateDisplay, 500);
        // Auto refresh based on config (will be updated when config changes)
        let refreshInterval = setInterval(updateDisplay, 60000);
        
        // Re-set interval when config changes (simplified - just keep updating)
        setInterval(updateDisplay, 30000);
    </script>
</body>
</html>
'''

# ==================== API ROUTES ====================

@app.route('/')
def index():
    return render_template_string(HTML)

@app.route('/api/live_data')
def api_live_data():
    return jsonify({
        'price': live_data.get('price', 0),
        'signal': live_data.get('signal', 'HOLD'),
        'raw_signal': live_data.get('raw_signal', 'HOLD'),
        'stop': live_data.get('stop', 0),
        'atr': live_data.get('atr', 0),
        'last_update': live_data.get('last_update', '--'),
        'status': current_config.get('status', 'Active'),
        'recommendation': live_data.get('recommendation', '--'),
        'entry_zone': live_data.get('entry_zone', '--'),
        'stop_loss': live_data.get('stop_loss', '--'),
        'take_profit_1': live_data.get('take_profit_1', '--'),
        'take_profit_2': live_data.get('take_profit_2', '--'),
        'chart_dates': live_data.get('chart_dates', []),
        'chart_prices': live_data.get('chart_prices', []),
        'chart_stops': live_data.get('chart_stops', []),
        'history': signal_history[-10:],
        'trade_direction': current_config.get('trade_direction', 'both')
    })

@app.route('/api/apply_config', methods=['POST'])
def apply_config():
    global current_config, monitor_running, monitor_thread
    
    try:
        new_config = request.json
        print(f"\n📝 New configuration applied:")
        print(f"   Symbol: {new_config['symbol']}")
        print(f"   Timeframe: {new_config['timeframe']}")
        print(f"   Sensitivity: {new_config['sensitivity']}")
        print(f"   ATR Period: {new_config['atr_period']}")
        print(f"   Leverage: {new_config['leverage']}x")
        print(f"   Trade Direction: {new_config['trade_direction']}")
        print(f"   Refresh: {new_config['auto_refresh']}s")
        
        # Update config
        current_config.update(new_config)
        current_config['status'] = 'Config updated'
        
        return jsonify({'success': True})
        
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})

if __name__ == '__main__':
    print("\n" + "="*60)
    print("🟢 UT BOT LIVE TRADING STUDIO")
    print("="*60)
    print("\n✅ Fully configurable live monitor is running!")
    print("\n🌐 Open in browser:")
    print("   http://localhost:5000")
    print("   or http://192.168.0.170:5000")
    print("\n📊 Configurable options:")
    print("   ✓ Symbol (BTC, ETH, SOL, BNB, XRP)")
    print("   ✓ Timeframe (1H, 4H, 1D, 1W)")
    print("   ✓ Sensitivity & ATR Period")
    print("   ✓ Leverage (1-10x)")
    print("   ✓ Trade Direction (Long Only / Short Only / Both)")
    print("   ✓ Refresh Rate")
    print("   ✓ Position Size %")
    print("\n⏱️  Updates based on your refresh setting")
    print("="*60 + "\n")
    
    app.run(host='0.0.0.0', port=5000, debug=False)

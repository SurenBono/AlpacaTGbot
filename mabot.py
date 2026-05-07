import os
import time
import logging
import threading
from datetime import datetime, timedelta
from functools import wraps
from flask import Flask, render_template_string, jsonify, request
import pandas as pd
import numpy as np
from dotenv import load_dotenv
from alpaca.trading.client import TradingClient
from alpaca.trading.requests import MarketOrderRequest
from alpaca.trading.enums import OrderSide, TimeInForce
from alpaca.data.historical.crypto import CryptoHistoricalDataClient
from alpaca.data.requests import CryptoBarsRequest
from alpaca.data.timeframe import TimeFrame

# Load environment variables
load_dotenv()

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('trading_bot.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# Flask app for web dashboard
app = Flask(__name__)
bot_instance = None

# Suppress pandas warnings
import warnings
warnings.filterwarnings('ignore', category=FutureWarning)


def retry_on_timeout(max_retries=3, delay=2):
    """Decorator to retry on timeout errors"""
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            for attempt in range(max_retries):
                try:
                    return func(*args, **kwargs)
                except Exception as e:
                    error_str = str(e).lower()
                    if ("timeout" in error_str or "connection" in error_str) and attempt < max_retries - 1:
                        wait_time = delay * (attempt + 1)
                        if len(args) > 1:
                            args[0].add_log(f"Retry {attempt+1}/{max_retries} for {args[1]} after {wait_time}s...")
                        time.sleep(wait_time)
                        continue
                    raise e
            return None
        return wrapper
    return decorator


# HTML Template for Dashboard - No Auto Refresh, API Only
DASHBOARD_TEMPLATE = """
<!DOCTYPE html>
<html>
<head>
    <title>ALPACA SPOT BOT</title>
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body {
            font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
            background: linear-gradient(135deg, #1a1a2e 0%, #16213e 100%);
            color: #fff;
            padding: 20px;
            min-height: 100vh;
        }
        .container { max-width: 1600px; margin: 0 auto; }
        h1 { 
            text-align: center; 
            margin-bottom: 30px; 
            color: #00d4ff;
            font-size: 2em;
        }
        .grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(380px, 1fr));
            gap: 20px;
            margin-bottom: 20px;
        }
        .card {
            background: rgba(255,255,255,0.1);
            backdrop-filter: blur(10px);
            border-radius: 15px;
            padding: 20px;
            border: 1px solid rgba(255,255,255,0.2);
        }
        .card h3 {
            color: #00d4ff;
            margin-bottom: 15px;
            border-bottom: 1px solid rgba(255,255,255,0.2);
            padding-bottom: 10px;
            font-size: 1.2em;
        }
        .stat {
            font-size: 2em;
            font-weight: bold;
            margin: 10px 0;
        }
        .stat-label { color: #aaa; font-size: 0.85em; }
        .positive { color: #00ff88; }
        .negative { color: #ff4444; }
        .status-badge {
            display: inline-block;
            padding: 4px 12px;
            border-radius: 20px;
            font-size: 0.8em;
            font-weight: bold;
        }
        .status-long { background: #00ff88; color: #000; }
        .status-flat { background: #888; color: #fff; }
        .signal-buy { background: #00ff88; color: #000; }
        .signal-sell { background: #ff4444; color: #fff; }
        button {
            background: #00d4ff;
            color: #000;
            border: none;
            padding: 8px 16px;
            border-radius: 5px;
            cursor: pointer;
            font-weight: bold;
            margin: 5px;
        }
        button:hover { opacity: 0.8; }
        button.danger { background: #ff4444; color: #fff; }
        button.small { padding: 4px 8px; font-size: 0.8em; }
        .logs {
            height: 250px;
            overflow-y: scroll;
            font-family: monospace;
            font-size: 0.75em;
            background: rgba(0,0,0,0.3);
            border-radius: 10px;
            padding: 10px;
            display: flex;
            flex-direction: column;
        }
        .log-entry { 
            border-bottom: 1px solid rgba(255,255,255,0.05); 
            padding: 4px 0;
            font-family: monospace;
            font-size: 0.75em;
            word-break: break-all;
        }
        .symbol-table {
            width: 100%;
            border-collapse: collapse;
        }
        .symbol-table th, .symbol-table td {
            padding: 10px 5px;
            text-align: left;
            border-bottom: 1px solid rgba(255,255,255,0.1);
            font-size: 0.85em;
        }
        .symbol-table th { color: #00d4ff; }
        .setting-row {
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin: 12px 0;
            flex-wrap: wrap;
        }
        .setting-row label { width: 45%; font-size: 0.85em; }
        .setting-row input, .setting-row select { 
            width: 50%; 
            padding: 6px;
            border-radius: 5px;
            border: none;
            background: rgba(255,255,255,0.2);
            color: #fff;
        }
        .setting-row input[type="range"] { width: 50%; }
        .value-display { 
            font-size: 0.85em; 
            color: #00d4ff;
            margin-left: 8px;
        }
        hr { border-color: rgba(255,255,255,0.1); margin: 12px 0; }
        .elapsed-time {
            font-family: monospace;
            font-size: 1em;
            color: #00d4ff;
            text-align: center;
            margin-top: 10px;
            padding: 8px;
            background: rgba(0,0,0,0.3);
            border-radius: 8px;
        }
        .pnl-row {
            display: flex;
            justify-content: space-between;
            margin: 8px 0;
            padding: 5px;
            background: rgba(0,0,0,0.2);
            border-radius: 5px;
            font-size: 0.9em;
        }
        @media (max-width: 768px) {
            .grid { grid-template-columns: 1fr; }
            body { padding: 10px; }
            .stat { font-size: 1.5em; }
        }
    </style>
</head>
<body>
    <div class="container">
        <h1>🤖 ALPACA SPOT BOT</h1>
        
        <div class="grid">
            <!-- Account Status Card -->
            <div class="card">
                <h3>📊 Account Status &amp; P&amp;L</h3>
                <div class="stat-label">Starting Balance</div>
                <div class="stat" id="startingBalance">$0.00</div>
                <div class="stat-label">Portfolio Value</div>
                <div class="stat" id="portfolioValue">$0.00</div>
                <div class="stat-label">Buying Power</div>
                <div class="stat" id="buyingPower">$0.00</div>
                
                <hr>
                
                <div class="pnl-row">
                    <span>📈 Today's P&amp;L:</span>
                    <span id="todayPnl">$0.00 (0.00%)</span>
                </div>
                <div class="pnl-row">
                    <span>📊 Realized P&amp;L:</span>
                    <span id="realizedPnl">$0.00</span>
                </div>
                <div class="pnl-row">
                    <span>💹 Unrealized P&amp;L:</span>
                    <span id="unrealizedPnl">$0.00</span>
                </div>
                <div class="pnl-row">
                    <span>🎯 Total P&amp;L:</span>
                    <span id="totalPnl">$0.00 (0.00%)</span>
                </div>
                
                <div class="elapsed-time">
                    ⏱️ Running: <span id="elapsedValue">0s</span>
                </div>
            </div>
            
            <!-- Live Controls Card -->
            <div class="card">
                <h3>🎛️ Live Controls</h3>
                
                <div class="setting-row">
                    <label>⏱️ Timeframe:</label>
                    <select id="timeframe" onchange="updateSetting('timeframe', this.value)">
                        <option value="1Min">1 Minute</option>
                        <option value="5Min">5 Minutes</option>
                        <option value="15Min" selected>15 Minutes</option>
                        <option value="30Min">30 Minutes</option>
                        <option value="1H">1 Hour</option>
                        <option value="2H">2 Hours</option>
                        <option value="4H">4 Hours</option>
                        <option value="1D">1 Day</option>
                    </select>
                </div>
                
                <div class="setting-row">
                    <label>📊 MA Fast Period:</label>
                    <input type="range" id="ma_fast" min="2" max="20" step="1" value="5" oninput="updateMAFastValue(this.value)" onchange="updateSetting('ma_fast', parseInt(this.value))">
                    <span id="maFastValue" class="value-display">5</span>
                </div>
                
                <div class="setting-row">
                    <label>📈 MA Slow Period:</label>
                    <input type="range" id="ma_slow" min="5" max="50" step="1" value="10" oninput="updateMASlowValue(this.value)" onchange="updateSetting('ma_slow', parseInt(this.value))">
                    <span id="maSlowValue" class="value-display">10</span>
                </div>
                
                <div class="setting-row">
                    <label>🛡️ Stop Loss %:</label>
                    <input type="range" id="stop_loss" min="1" max="10" step="0.5" value="5" oninput="updateStopLossValue(this.value)" onchange="updateSetting('stop_loss', parseFloat(this.value) / 100)">
                    <span id="stopLossValue" class="value-display">5.0%</span>
                </div>
                
                <div class="setting-row">
                    <label>💰 Min Profit $:</label>
                    <input type="number" id="min_profit_usd" step="0.1" value="1.00" style="width: 50%;" onchange="updateSetting('min_profit_usd', parseFloat(this.value))">
                </div>
                
                <div class="setting-row">
                    <label>📈 Heikin Ashi:</label>
                    <select id="heikin_ashi" onchange="updateSetting('heikin_ashi', this.value === 'true')">
                        <option value="true" selected>Enabled</option>
                        <option value="false">Disabled</option>
                    </select>
                </div>
                
                <hr>
                
                <div style="text-align: center;">
                    <div class="stat-label">Bot Status</div>
                    <div class="status-badge" id="botStatus" style="background: #00ff88">RUNNING</div>
                    <button onclick="fetch('/stop', {method: 'POST'})" class="danger small" style="margin-top: 10px;">Stop Bot</button>
                </div>
            </div>
            
            <!-- Active Positions Card -->
            <div class="card">
                <h3>📈 Active Positions 
                    <button onclick="fetch('/close_all_positions', {method: 'POST'})" class="danger small" style="float: right;">Close All</button>
                </h3>
                <table class="symbol-table">
                    <thead>
                        <tr><th>Symbol</th><th>Qty</th><th>Entry</th><th>Current</th><th>P&amp;L</th><th>Stop Loss</th></tr>
                    </thead>
                    <tbody id="positionsBody">
                        <tr><td colspan="6" style="text-align:center; padding:20px; color:#888;">No active positions</td></tr>
                    </tbody>
                </table>
            </div>
        </div>
        
        <div class="grid">
            <!-- Symbol Signals Card -->
            <div class="card">
                <h3>🎯 Symbol Signals</h3>
                <table class="symbol-table">
                    <thead>
                        <tr><th>Symbol</th><th>Price</th><th>MA Fast</th><th>MA Slow</th><th>Trail Stop</th><th>Signal</th><th>Position</th></tr>
                    </thead>
                    <tbody id="signalsBody">
                        <tr><td colspan="7" style="text-align:center; padding:20px; color:#888;">Loading...</td></tr>
                    </tbody>
                </table>
            </div>
            
            <!-- Live Logs Card -->
            <div class="card">
                <h3>📝 Live Logs (Last 10)</h3>
                <div class="logs" id="logs">
                    <div class="log-entry">Waiting for logs...</div>
                </div>
            </div>
        </div>
    </div>
    
    <script>
        let botStartTime = Math.floor(Date.now() / 1000);
        
        function updateElapsedTime() {
            if (botStartTime > 0) {
                let elapsed = Math.floor((Date.now() / 1000) - botStartTime);
                let hours = Math.floor(elapsed / 3600);
                let minutes = Math.floor((elapsed % 3600) / 60);
                let seconds = elapsed % 60;
                let elapsedStr = '';
                if (hours > 0) elapsedStr += hours + 'h ';
                if (minutes > 0 || hours > 0) elapsedStr += minutes + 'm ';
                elapsedStr += seconds + 's';
                document.getElementById('elapsedValue').innerText = elapsedStr;
            }
        }
        
        function updateMAFastValue(val) {
            document.getElementById('maFastValue').innerText = val;
        }
        function updateMASlowValue(val) {
            document.getElementById('maSlowValue').innerText = val;
        }
        function updateStopLossValue(val) {
            document.getElementById('stopLossValue').innerText = parseFloat(val).toFixed(1) + '%';
        }
        
        function updateSetting(setting, value) {
            fetch('/update_setting', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({setting: setting, value: value})
            })
            .then(response => response.json())
            .then(data => {
                if (data.status === 'ok') {
                    console.log('Setting updated: ' + setting + ' = ' + value);
                }
            });
        }
        
        function updateDashboard(data) {
            // Update account stats
            if (data.account) {
                document.getElementById('startingBalance').innerHTML = '$' + data.account.starting_balance.toFixed(2);
                document.getElementById('portfolioValue').innerHTML = '$' + data.account.portfolio_value.toFixed(2);
                document.getElementById('buyingPower').innerHTML = '$' + data.account.buying_power.toFixed(2);
                
                let todayClass = data.account.today_pnl >= 0 ? 'positive' : 'negative';
                document.getElementById('todayPnl').innerHTML = '<span class="' + todayClass + '">$' + data.account.today_pnl.toFixed(2) + ' (' + data.account.today_pnl_percent.toFixed(2) + '%)</span>';
                
                let realizedClass = data.account.total_realized_pnl >= 0 ? 'positive' : 'negative';
                document.getElementById('realizedPnl').innerHTML = '<span class="' + realizedClass + '">$' + data.account.total_realized_pnl.toFixed(2) + '</span>';
                
                let unrealizedClass = data.account.unrealized_pnl >= 0 ? 'positive' : 'negative';
                document.getElementById('unrealizedPnl').innerHTML = '<span class="' + unrealizedClass + '">$' + data.account.unrealized_pnl.toFixed(2) + '</span>';
                
                let totalClass = data.account.total_pnl >= 0 ? 'positive' : 'negative';
                document.getElementById('totalPnl').innerHTML = '<span class="' + totalClass + '">$' + data.account.total_pnl.toFixed(2) + ' (' + data.account.total_pnl_percent.toFixed(2) + '%)</span>';
            }
            
            // Update positions
            if (data.positions && data.positions.length > 0) {
                let html = '';
                for (let pos of data.positions) {
                    let pnlClass = pos.pnl >= 0 ? 'positive' : 'negative';
                    html += `<tr>
                        <td>${pos.symbol}</td>
                        <td>${pos.qty.toFixed(6)}</td>
                        <td>$${pos.entry_price.toFixed(2)}</td>
                        <td>$${pos.current_price.toFixed(2)}</td>
                        <td class="${pnlClass}">$${pos.pnl.toFixed(2)}</td>
                        <td class="negative">$${pos.stop_loss_price.toFixed(2)}</td>
                    </tr>`;
                }
                document.getElementById('positionsBody').innerHTML = html;
            } else if (data.positions) {
                document.getElementById('positionsBody').innerHTML = '<tr><td colspan="6" style="text-align:center; padding:20px; color:#888;">No active positions</td></tr>';
            }
            
            // Update signals
            if (data.symbols && data.symbols.length > 0) {
                let html = '';
                for (let sym of data.symbols) {
                    let signalBadge = sym.signal_type ? `<span class="status-badge signal-${sym.signal_type.toLowerCase()}">${sym.signal_type}</span>` : '<span class="status-badge" style="background:#888">NONE</span>';
                    let positionBadge = sym.position_status === 'long' ? '<span class="status-badge status-long">LONG</span>' : '<span class="status-badge status-flat">FLAT</span>';
                    let maFastClass = sym.ma_fast > sym.ma_slow ? 'positive' : 'negative';
                    html += `<tr>
                        <td>${sym.symbol}</td>
                        <td>$${sym.price.toFixed(2)}</td>
                        <td class="${maFastClass}">$${sym.ma_fast.toFixed(2)}</td>
                        <td>$${sym.ma_slow.toFixed(2)}</td>
                        <td>$${sym.trail_stop.toFixed(2)}</td>
                        <td>${signalBadge}</td>
                        <td>${positionBadge}</td>
                    </tr>`;
                }
                document.getElementById('signalsBody').innerHTML = html;
            }
            
            // Update logs (show last 10, newest at bottom)
            if (data.logs && data.logs.length > 0) {
                let logsHtml = '';
                for (let log of data.logs) {
                    logsHtml += `<div class="log-entry">${log}</div>`;
                }
                document.getElementById('logs').innerHTML = logsHtml;
                // Auto-scroll to bottom to see newest log
                let logsDiv = document.getElementById('logs');
                if (logsDiv) {
                    logsDiv.scrollTop = logsDiv.scrollHeight;
                }
            }
            
            // Update settings display
            if (data.current_settings) {
                let tf = document.getElementById('timeframe');
                if (tf && data.current_settings.timeframe !== tf.value) {
                    tf.value = data.current_settings.timeframe;
                }
                let mf = document.getElementById('ma_fast');
                if (mf && data.current_settings.ma_fast !== parseInt(mf.value)) {
                    mf.value = data.current_settings.ma_fast;
                    document.getElementById('maFastValue').innerText = data.current_settings.ma_fast;
                }
                let ms = document.getElementById('ma_slow');
                if (ms && data.current_settings.ma_slow !== parseInt(ms.value)) {
                    ms.value = data.current_settings.ma_slow;
                    document.getElementById('maSlowValue').innerText = data.current_settings.ma_slow;
                }
                let sl = document.getElementById('stop_loss');
                if (sl && data.current_settings.stop_loss_percent * 100 !== parseFloat(sl.value)) {
                    sl.value = data.current_settings.stop_loss_percent * 100;
                    document.getElementById('stopLossValue').innerText = data.current_settings.stop_loss_percent * 100 + '%';
                }
                let mp = document.getElementById('min_profit_usd');
                if (mp && data.current_settings.min_profit_usd !== parseFloat(mp.value)) {
                    mp.value = data.current_settings.min_profit_usd;
                }
                let ha = document.getElementById('heikin_ashi');
                if (ha && data.current_settings.heikin_ashi.toString() !== ha.value) {
                    ha.value = data.current_settings.heikin_ashi;
                }
            }
            
            if (data.bot_start_time) {
                botStartTime = data.bot_start_time;
            }
            
            if (data.bot_running !== undefined) {
                let statusEl = document.getElementById('botStatus');
                if (data.bot_running) {
                    statusEl.style.background = '#00ff88';
                    statusEl.style.color = '#000';
                    statusEl.innerText = 'RUNNING';
                } else {
                    statusEl.style.background = '#ff4444';
                    statusEl.style.color = '#fff';
                    statusEl.innerText = 'STOPPED';
                }
            }
        }
        
        // Initial load
        fetch('/api/status')
            .then(response => response.json())
            .then(data => updateDashboard(data));
        
        // Update every 3 seconds
        setInterval(function() {
            fetch('/api/status')
                .then(response => response.json())
                .then(data => updateDashboard(data));
        }, 3000);
        
        setInterval(updateElapsedTime, 1000);
        updateElapsedTime();
    </script>
</body>
</html>
"""


class AlpacaSpotBot:
    """Alpaca Spot Bot - MA Crossover (Fast & Slow) with Trailing Stop Exit Only"""
    
    def __init__(self):
        """Initialize bot with parameters from .env file"""
        
        # Store start time for elapsed timer
        self.bot_start_time = time.time()
        
        # Load symbols from .env (comma-separated list)
        symbols_str = os.getenv('SYMBOLS', 'ETH/USD,BTC/USD,SOL/USD')
        self.symbols = [s.strip() for s in symbols_str.split(',')]
        
        # Load common parameters (with live update support)
        self._load_settings_from_env()
        
        # Individual symbol quantities
        self.symbol_quantities = {}
        for symbol in self.symbols:
            base = symbol.replace('/USD', '').replace('USDT', '')
            qty_env = os.getenv(f'QUANTITY_{base}', str(self.quantity))
            self.symbol_quantities[symbol] = float(qty_env)
        
        # Parse timeframe
        self._update_timeframe_settings()
        
        # Initialize Alpaca clients
        api_key = os.getenv('APCA_API_KEY_ID')
        secret_key = os.getenv('APCA_API_SECRET_KEY')
        
        if not api_key or not secret_key:
            logger.error("API keys not found in .env file")
            raise ValueError("Missing API keys")
        
        if self.paper_trading:
            self.trading_client = TradingClient(api_key, secret_key, paper=True)
        else:
            self.trading_client = TradingClient(api_key, secret_key)
        
        self.data_client = CryptoHistoricalDataClient(api_key, secret_key)
        
        # Tracking variables per symbol
        self.last_buy_signal = {symbol: False for symbol in self.symbols}
        self.trades_history = []
        self.logs = []
        
        # Initialize starting balance from .env
        self.starting_balance = float(os.getenv('STARTING_BALANCE', '100000.00'))
        self.day_start_equity = None
        self.today_date = None
        
        # Log startup configuration
        self._log_configuration()
    
    def _load_settings_from_env(self):
        """Load settings from .env file"""
        self.quantity = float(os.getenv('QUANTITY', '0.01'))
        self.timeframe_str = os.getenv('TIMEFRAME', '15Min')
        self.ma_fast = int(os.getenv('MA_FAST', '5'))
        self.ma_slow = int(os.getenv('MA_SLOW', '10'))
        self.use_heikin_ashi = os.getenv('HEIKIN_ASHI', 'True').lower() == 'true'
        self.paper_trading = os.getenv('PAPER_TRADING', 'True').lower() == 'true'
        self.running = True
        self.stop_loss_percent = float(os.getenv('STOP_LOSS_PERCENT', '0.05'))
        self.min_profit_usd = float(os.getenv('MIN_PROFIT_USD', '1.00'))
        self.min_profit_percent = float(os.getenv('MIN_PROFIT_PERCENT', '0.01'))
    
    def _update_timeframe_settings(self):
        """Update timeframe-related settings"""
        self.timeframe_minutes = self._parse_timeframe_to_minutes(self.timeframe_str)
        self.interval_map = {
            "1Min": 60, "5Min": 300, "15Min": 900, "30Min": 1800,
            "1H": 3600, "2H": 7200, "4H": 14400, "1D": 86400
        }
        self.check_interval = self.interval_map.get(self.timeframe_str, 900)
        self.bars_to_fetch = 200 if self.timeframe_str in ["1D", "4H"] else 100
    
    def _log_configuration(self):
        """Log current configuration"""
        logger.info("="*50)
        logger.info("ALPACA SPOT BOT - MA Crossover Strategy")
        logger.info("="*50)
        logger.info(f"Starting Balance: ${self.starting_balance:,.2f}")
        logger.info(f"Symbols: {', '.join(self.symbols)}")
        for sym, qty in self.symbol_quantities.items():
            logger.info(f"  {sym}: {qty} {sym.replace('/USD', '')}")
        logger.info(f"Timeframe: {self.timeframe_str}")
        logger.info(f"MA Fast: {self.ma_fast} | MA Slow: {self.ma_slow}")
        logger.info(f"Heikin Ashi: {self.use_heikin_ashi}")
        logger.info(f"Mode: {'PAPER' if self.paper_trading else 'LIVE'}")
        logger.info("-"*30)
        logger.info("STRATEGY:")
        logger.info("  BUY: Fast MA crosses ABOVE Slow MA")
        logger.info("  SELL: Price crosses BELOW Trailing Stop only")
        logger.info("-"*30)
        logger.info("RISK MANAGEMENT:")
        logger.info(f"  Stop Loss: {self.stop_loss_percent*100:.1f}%")
        logger.info(f"  Min Profit: ${self.min_profit_usd} or {self.min_profit_percent*100:.1f}%")
        logger.info("="*50)
        logger.info("🌐 Web dashboard: http://localhost:5000")
        logger.info("   Type 'y' to start trading")
        logger.info("="*50)
    
    def update_setting(self, setting, value):
        """Update a setting live (no restart needed)"""
        if setting == 'timeframe':
            self.timeframe_str = value
            self._update_timeframe_settings()
            self.add_log(f"⚙️ Timeframe changed to {value}")
        elif setting == 'ma_fast':
            self.ma_fast = int(value)
            self.add_log(f"⚙️ MA Fast changed to {self.ma_fast}")
        elif setting == 'ma_slow':
            self.ma_slow = int(value)
            self.add_log(f"⚙️ MA Slow changed to {self.ma_slow}")
        elif setting == 'stop_loss':
            self.stop_loss_percent = float(value)
            self.add_log(f"⚙️ Stop Loss changed to {self.stop_loss_percent*100:.1f}%")
        elif setting == 'min_profit_usd':
            self.min_profit_usd = float(value)
            self.add_log(f"⚙️ Min Profit USD changed to ${self.min_profit_usd}")
        elif setting == 'heikin_ashi':
            self.use_heikin_ashi = bool(value)
            self.add_log(f"⚙️ Heikin Ashi {'enabled' if self.use_heikin_ashi else 'disabled'}")
        
        # Update .env file for persistence
        self._update_env_file(setting, value)
        return True
    
    def _update_env_file(self, setting, value):
        """Update .env file to persist settings"""
        env_path = os.path.join(os.path.dirname(__file__), '.env')
        env_key_map = {
            'timeframe': 'TIMEFRAME',
            'ma_fast': 'MA_FAST',
            'ma_slow': 'MA_SLOW',
            'stop_loss': 'STOP_LOSS_PERCENT',
            'min_profit_usd': 'MIN_PROFIT_USD',
            'heikin_ashi': 'HEIKIN_ASHI'
        }
        
        if setting in env_key_map:
            env_key = env_key_map[setting]
            try:
                with open(env_path, 'r') as f:
                    lines = f.readlines()
                
                updated = False
                for i, line in enumerate(lines):
                    if line.startswith(f"{env_key}="):
                        lines[i] = f"{env_key}={value}\n"
                        updated = True
                        break
                
                if not updated:
                    lines.append(f"{env_key}={value}\n")
                
                with open(env_path, 'w') as f:
                    f.writelines(lines)
            except Exception:
                pass
    
    def get_current_settings(self):
        """Get current settings for dashboard"""
        return {
            'timeframe': self.timeframe_str,
            'ma_fast': self.ma_fast,
            'ma_slow': self.ma_slow,
            'stop_loss_percent': self.stop_loss_percent,
            'min_profit_usd': self.min_profit_usd,
            'heikin_ashi': self.use_heikin_ashi
        }
    
    def _parse_timeframe_to_minutes(self, timeframe_str):
        timeframe_map = {
            "1Min": 1, "5Min": 5, "15Min": 15, "30Min": 30,
            "1H": 60, "2H": 120, "4H": 240, "1D": 1440
        }
        return timeframe_map.get(timeframe_str, 15)
    
    def normalize_symbol(self, symbol: str, to_display: bool = False) -> str:
        if to_display:
            if '/' in symbol:
                return symbol
            if len(symbol) >= 6:
                base = symbol[:-3]
                quote = symbol[-3:]
                return f"{base}/{quote}"
            return symbol
        else:
            return symbol.replace('/', '')
    
    def add_log(self, message, level="INFO"):
        """Add log message - keeps last 10 logs, newest at bottom"""
        timestamp = datetime.now().strftime('%H:%M:%S')
        log_entry = f"[{timestamp}] {message}"
        
        # Append to end (newest at bottom)
        self.logs.append(log_entry)
        
        # Keep only last 10 logs
        if len(self.logs) > 10:
            self.logs = self.logs[-10:]
        
        if level == "ERROR":
            logger.error(message)
        else:
            logger.info(message)
    
    def resume_existing_positions(self):
        try:
            positions = self.trading_client.get_all_positions()
            if positions:
                self.add_log("="*40)
                self.add_log("🔄 RESUME MODE: Existing positions detected")
                self.add_log("="*40)
                for pos in positions:
                    display_symbol = self.normalize_symbol(pos.symbol, to_display=True)
                    if display_symbol in self.symbols:
                        qty = float(pos.qty)
                        entry = float(pos.avg_entry_price)
                        current = float(pos.current_price)
                        pnl = float(pos.unrealized_pl)
                        
                        self.add_log(f"  📍 {display_symbol}: {qty} at ${entry:.2f}")
                        self.add_log(f"     Current: ${current:.2f} | P&L: ${pnl:.2f}")
                        self.last_buy_signal[display_symbol] = True
                self.add_log("="*40)
                self.add_log("✅ Bot will manage these positions (Exit via trailing stop only)")
                self.add_log("="*40)
                return True
            else:
                self.add_log("📭 No existing positions - starting fresh")
                return False
        except Exception as e:
            self.add_log(f"Error checking existing positions: {e}", "ERROR")
            return False
    
    def get_heikin_ashi(self, df):
        ha_df = pd.DataFrame(index=df.index)
        ha_df['close'] = (df['open'] + df['high'] + df['low'] + df['close']) / 4
        ha_df['open'] = (df['open'].shift(1) + df['close'].shift(1)) / 2
        if len(ha_df) > 0:
            ha_df.loc[ha_df.index[0], 'open'] = (df['open'].iloc[0] + df['close'].iloc[0]) / 2
        ha_df['high'] = df[['high', 'open', 'close']].max(axis=1)
        ha_df['low'] = df[['low', 'open', 'close']].min(axis=1)
        return ha_df
    
    def calculate_atr(self, df, period=14):
        high = df['high']
        low = df['low']
        close = df['close']
        tr1 = high - low
        tr2 = (high - close.shift()).abs()
        tr3 = (low - close.shift()).abs()
        tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
        atr = tr.rolling(window=period).mean()
        return atr
    
    def calculate_signals(self, df):
        """Calculate MA crossover signals - BUY only on crossover, SELL only from trailing stop"""
        df = df.copy()
        
        if self.use_heikin_ashi:
            ha = self.get_heikin_ashi(df)
            close_price = ha['close']
        else:
            close_price = df['close']
        
        # Calculate Moving Averages
        df['ma_fast'] = close_price.rolling(window=self.ma_fast).mean()
        df['ma_slow'] = close_price.rolling(window=self.ma_slow).mean()
        
        # BUY signal: Fast MA crosses ABOVE Slow MA
        df['buy_signal'] = (df['ma_fast'] > df['ma_slow']) & (df['ma_fast'].shift(1) <= df['ma_slow'].shift(1))
        
        # Calculate ATR for trailing stop (2x ATR)
        atr = self.calculate_atr(df, 14)
        df['trailing_stop'] = close_price - (2 * atr)
        
        # Trailing stop moves up only (ratchet effect)
        for i in range(1, len(df)):
            df.loc[df.index[i], 'trailing_stop'] = max(
                df.loc[df.index[i], 'trailing_stop'],
                df.loc[df.index[i-1], 'trailing_stop']
            )
        
        # SELL signal: Price crosses below trailing stop
        df['sell_signal'] = (close_price < df['trailing_stop']) & (close_price.shift(1) >= df['trailing_stop'].shift(1))
        
        return df
    
    @retry_on_timeout(max_retries=3, delay=2)
    def get_historical_data(self, symbol, bars=None):
        """Fetch historical crypto bar data with retry logic"""
        if bars is None:
            bars = self.bars_to_fetch
            
        end = datetime.now()
        total_minutes = self.timeframe_minutes * (bars + 50)
        start = end - timedelta(minutes=total_minutes)
        
        if self.timeframe_str == "1D":
            timeframe = TimeFrame.Day
        elif "H" in self.timeframe_str:
            timeframe = TimeFrame.Hour
        else:
            timeframe = TimeFrame.Minute
        
        request = CryptoBarsRequest(
            symbol_or_symbols=symbol,
            timeframe=timeframe,
            start=start,
            end=end,
            limit=bars + 100
        )
        
        bars_data = self.data_client.get_crypto_bars(request)
        if not bars_data.data or symbol not in bars_data.data:
            return None
            
        df = bars_data.df
        if df.empty or len(df) < 50:
            return None
            
        df = df.reset_index()
        df = df.rename(columns={'timestamp': 'datetime', 'open': 'open', 
                                 'high': 'high', 'low': 'low', 'close': 'close'})
        df.set_index('datetime', inplace=True)
        df = df.sort_index()
        return df
    
    def execute_order(self, symbol, side, quantity=None):
        if quantity is None:
            quantity = self.symbol_quantities.get(symbol, self.quantity)
        quantity = float(quantity)
        display = symbol.replace('/USD', '')
        
        try:
            order_data = MarketOrderRequest(
                symbol=symbol,
                qty=quantity,
                side=side,
                time_in_force=TimeInForce.GTC
            )
            order = self.trading_client.submit_order(order_data)
            fill_price = float(order.filled_avg_price) if order.filled_avg_price else 0
            self.add_log(f"✅ {side.upper()} {quantity} {display} at ${fill_price:.2f}")
            return order
        except Exception as e:
            self.add_log(f"Order failed for {symbol}: {e}", "ERROR")
            return None
    
    def get_position_info(self, symbol):
        try:
            positions = self.trading_client.get_all_positions()
            alpaca_symbol = self.normalize_symbol(symbol, to_display=False)
            for pos in positions:
                if pos.symbol == alpaca_symbol:
                    return {
                        'entry': float(pos.avg_entry_price),
                        'qty': abs(float(pos.qty)),
                        'symbol': pos.symbol
                    }
            return None
        except Exception:
            return None
    
    def is_profitable_enough(self, symbol, entry_price, current_price, qty):
        pnl = (current_price - entry_price) * qty
        position_value = entry_price * qty
        profit_threshold = max(self.min_profit_usd, position_value * self.min_profit_percent)
        
        if pnl <= 0:
            return False
        if pnl < profit_threshold:
            self.add_log(f"⚠️ {symbol} Profit ${pnl:.2f} below threshold ${profit_threshold:.2f} - holding")
            return False
        return True
    
    def check_stop_loss(self, symbol, entry_price, current_price, qty):
        loss_percent = (entry_price - current_price) / entry_price
        
        if loss_percent >= self.stop_loss_percent:
            loss_amount = (entry_price - current_price) * qty
            self.add_log(f"🛑 {symbol} STOP LOSS triggered! Loss: {loss_percent*100:.1f}% (${loss_amount:.2f})")
            return True
        return False
    
    def close_position(self, symbol):
        try:
            positions = self.trading_client.get_all_positions()
            alpaca_symbol = self.normalize_symbol(symbol, to_display=False)
            for pos in positions:
                if pos.symbol == alpaca_symbol:
                    qty = abs(float(pos.qty))
                    entry_price = float(pos.avg_entry_price)
                    
                    df = self.get_historical_data(symbol, bars=5)
                    if df is None:
                        return False
                    current_price = df.iloc[-1]['close']
                    
                    pnl = (current_price - entry_price) * qty
                    
                    self.execute_order(symbol, OrderSide.SELL, qty)
                    
                    trade = {
                        'time': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                        'symbol': symbol,
                        'type': "CLOSE_LONG",
                        'price': current_price,
                        'pnl': pnl
                    }
                    self.trades_history.insert(0, trade)
                    self.add_log(f"✅ Closed {symbol} at ${current_price:.2f}, PnL: ${pnl:.2f}")
                    
                    # Reset buy signal flag
                    self.last_buy_signal[symbol] = False
                    return True
            return True
        except Exception as e:
            if "position does not exist" not in str(e):
                self.add_log(f"Error closing {symbol}: {e}", "ERROR")
            return False
    
    def close_all_positions(self):
        try:
            positions = self.trading_client.get_all_positions()
            for pos in positions:
                display_symbol = self.normalize_symbol(pos.symbol, to_display=True)
                if display_symbol in self.symbols:
                    self.close_position(display_symbol)
            self.add_log("✅ Closed all positions")
            return True
        except Exception as e:
            self.add_log(f"Error closing all positions: {e}", "ERROR")
            return False
    
    def get_account_status(self):
        """Get current account status with accurate P&L from starting balance"""
        try:
            account = self.trading_client.get_account()
            current_equity = float(account.equity)
            
            # Calculate TOTAL P&L from starting balance
            total_pnl = current_equity - self.starting_balance
            
            # Calculate unrealized P&L from open positions
            unrealized_pnl = 0.0
            try:
                positions = self.trading_client.get_all_positions()
                for pos in positions:
                    if self.normalize_symbol(pos.symbol, to_display=True) in self.symbols:
                        unrealized_pnl += float(pos.unrealized_pl)
            except Exception:
                pass
            
            # Realized P&L = Total P&L - Unrealized P&L
            realized_pnl = total_pnl - unrealized_pnl
            
            # Track today's P&L (since midnight)
            current_date = datetime.now().date()
            if self.day_start_equity is None:
                self.day_start_equity = current_equity
                self.today_date = current_date
            elif current_date != self.today_date:
                # New day - reset
                self.day_start_equity = current_equity
                self.today_date = current_date
            
            today_pnl = current_equity - self.day_start_equity
            today_pnl_percent = (today_pnl / self.day_start_equity * 100) if self.day_start_equity > 0 else 0
            total_pnl_percent = (total_pnl / self.starting_balance * 100) if self.starting_balance > 0 else 0
            
            return {
                'buying_power': float(account.buying_power),
                'portfolio_value': current_equity,
                'today_pnl': today_pnl,
                'total_realized_pnl': realized_pnl,
                'unrealized_pnl': unrealized_pnl,
                'total_pnl': total_pnl,
                'today_pnl_percent': today_pnl_percent,
                'total_pnl_percent': total_pnl_percent,
                'starting_balance': self.starting_balance
            }
        except Exception as e:
            return {
                'buying_power': 0, 'portfolio_value': 0,
                'today_pnl': 0, 'total_realized_pnl': 0,
                'unrealized_pnl': 0, 'total_pnl': 0,
                'today_pnl_percent': 0, 'total_pnl_percent': 0,
                'starting_balance': self.starting_balance
            }
    
    def get_all_positions(self):
        positions = []
        try:
            all_positions = self.trading_client.get_all_positions()
            for pos in all_positions:
                display_symbol = self.normalize_symbol(pos.symbol, to_display=True)
                if display_symbol in self.symbols:
                    entry = float(pos.avg_entry_price)
                    positions.append({
                        'symbol': display_symbol,
                        'qty': float(pos.qty),
                        'entry_price': entry,
                        'current_price': float(pos.current_price),
                        'pnl': float(pos.unrealized_pl),
                        'stop_loss_price': entry * (1 - self.stop_loss_percent)
                    })
        except Exception:
            pass
        return positions
    
    def get_position_status(self, symbol):
        try:
            positions = self.trading_client.get_all_positions()
            alpaca_symbol = self.normalize_symbol(symbol, to_display=False)
            for pos in positions:
                if pos.symbol == alpaca_symbol:
                    return True
            return False
        except Exception:
            return False
    
    def process_symbol(self, symbol):
        try:
            df = self.get_historical_data(symbol)
            if df is None or len(df) < 50:
                return
            
            signals_df = self.calculate_signals(df)
            latest_data = signals_df.iloc[-1]
            
            latest_close = latest_data['close']
            latest_ma_fast = latest_data['ma_fast']
            latest_ma_slow = latest_data['ma_slow']
            latest_trailing_stop = latest_data['trailing_stop']
            
            buy_signal = latest_data['buy_signal']
            sell_signal = latest_data['sell_signal']
            
            display = symbol.replace('/USD', '')
            
            # Check position status
            has_position = self.get_position_status(symbol)
            position_info = self.get_position_info(symbol) if has_position else None
            
            # Check STOP LOSS first (priority)
            if has_position and position_info:
                entry_price = position_info['entry']
                qty = position_info['qty']
                
                if self.check_stop_loss(display, entry_price, latest_close, qty):
                    self.close_position(symbol)
                    return
            
            # Log current state (only every few cycles to avoid spam)
            if not hasattr(self, '_last_log_time'):
                self._last_log_time = {}
            
            current_time = time.time()
            if symbol not in self._last_log_time or (current_time - self._last_log_time[symbol]) > 30:
                self.add_log(f"{display}: ${latest_close:.2f} | MA{self.ma_fast}: ${latest_ma_fast:.2f} | MA{self.ma_slow}: ${latest_ma_slow:.2f} | Trail: ${latest_trailing_stop:.2f}")
                self._last_log_time[symbol] = current_time
            
            # BUY SIGNAL: MA Crossover
            if buy_signal and not has_position:
                self.add_log(f"🎯 {display} BUY SIGNAL: MA{self.ma_fast} crossed above MA{self.ma_slow} at ${latest_close:.2f}")
                self.add_log(f"🔵 {display} BUY SIGNAL - Going LONG")
                self.execute_order(symbol, OrderSide.BUY)
                self.last_buy_signal[symbol] = True
            
            # SELL SIGNAL: Only from trailing stop (when price crosses below)
            elif sell_signal and has_position:
                self.add_log(f"🎯 {display} SELL SIGNAL: Price crossed below trailing stop at ${latest_close:.2f}")
                if position_info:
                    if self.is_profitable_enough(display, position_info['entry'], latest_close, position_info['qty']):
                        self.add_log(f"🔴 {display} SELL SIGNAL - Closing position")
                        self.close_position(symbol)
                    else:
                        self.add_log(f"🔴 {display} SELL SIGNAL - Holding (profit below threshold)")
                else:
                    self.add_log(f"🔴 {display} SELL SIGNAL - Closing position")
                    self.close_position(symbol)
                    
        except Exception as e:
            self.add_log(f"Error processing {symbol}: {e}", "ERROR")
    
    def run_strategy(self):
        global bot_instance
        bot_instance = self
        
        self.add_log(f"🚀 Starting ALPACA SPOT BOT")
        self.add_log(f"💰 Starting Balance: ${self.starting_balance:,.2f}")
        self.add_log(f"📊 Strategy: MA{self.ma_fast} / MA{self.ma_slow} Crossover for BUY")
        self.add_log(f"📊 Exit: Only when price crosses below trailing stop")
        self.add_log(f"📊 Monitoring: {', '.join(self.symbols)}")
        self.add_log(f"🛡️ Stop Loss: {self.stop_loss_percent*100:.1f}%")
        self.add_log(f"💰 Min Profit: ${self.min_profit_usd} or {self.min_profit_percent*100:.1f}%")
        self.add_log(f"🌐 Web dashboard: http://localhost:5000")
        
        self.resume_existing_positions()
        
        while self.running:
            for symbol in self.symbols:
                if not self.running:
                    break
                self.process_symbol(symbol)
                time.sleep(2)
            time.sleep(self.check_interval)
    
    def get_dashboard_data(self):
        account = self.get_account_status()
        positions = self.get_all_positions()
        
        symbols_data = []
        for symbol in self.symbols:
            try:
                df = self.get_historical_data(symbol, bars=50)
                if df is not None:
                    signals = self.calculate_signals(df)
                    has_position = self.get_position_status(symbol)
                    latest = signals.iloc[-1]
                    
                    # Determine signal type
                    signal_type = None
                    if latest['buy_signal'] and not has_position:
                        signal_type = 'BUY'
                    elif latest['sell_signal'] and has_position:
                        signal_type = 'SELL'
                    
                    symbols_data.append({
                        'symbol': symbol.replace('/USD', '').replace('USDT', ''),
                        'price': float(latest['close']),
                        'ma_fast': float(latest['ma_fast']),
                        'ma_slow': float(latest['ma_slow']),
                        'trail_stop': float(latest['trailing_stop']),
                        'signal_type': signal_type,
                        'position_status': 'long' if has_position else 'flat'
                    })
            except Exception:
                symbols_data.append({
                    'symbol': symbol.replace('/USD', '').replace('USDT', ''),
                    'price': 0, 'ma_fast': 0, 'ma_slow': 0,
                    'trail_stop': 0,
                    'signal_type': None, 'position_status': 'unknown'
                })
        return account, positions, symbols_data


# Flask routes
@app.route('/')
def dashboard():
    return render_template_string(DASHBOARD_TEMPLATE)


@app.route('/api/status')
def api_status():
    global bot_instance
    if not bot_instance:
        return jsonify({
            'logs': ['Bot not running'],
            'current_settings': {},
            'bot_start_time': 0,
            'bot_running': False
        })
    
    account, positions, symbols_data = bot_instance.get_dashboard_data()
    current_settings = bot_instance.get_current_settings()
    
    return jsonify({
        'account': account,
        'positions': positions,
        'symbols': symbols_data,
        'logs': bot_instance.logs[-10:],  # Last 10 logs
        'current_settings': current_settings,
        'bot_start_time': int(bot_instance.bot_start_time),
        'bot_running': bot_instance.running
    })


@app.route('/update_setting', methods=['POST'])
def update_setting():
    global bot_instance
    if not bot_instance:
        return jsonify({'status': 'error', 'message': 'Bot not running'})
    
    data = request.get_json()
    setting = data.get('setting')
    value = data.get('value')
    
    if bot_instance.update_setting(setting, value):
        return jsonify({'status': 'ok', 'message': f'{setting} updated to {value}'})
    else:
        return jsonify({'status': 'error', 'message': 'Failed to update setting'})


@app.route('/close_all_positions', methods=['POST'])
def close_all_route():
    global bot_instance
    if bot_instance:
        bot_instance.close_all_positions()
    return jsonify({'status': 'ok'})


@app.route('/stop', methods=['POST'])
def stop_route():
    global bot_instance
    if bot_instance:
        bot_instance.running = False
    return jsonify({'status': 'stopping'})


def run_dashboard():
    app.run(host='0.0.0.0', port=5000, debug=False, use_reloader=False)


def main():
    print("\n" + "="*50)
    print("🤖 ALPACA SPOT BOT - MA Crossover Strategy")
    print("="*50)
    print("  BUY:  Fast MA crosses above Slow MA")
    print("  SELL: Price crosses below Trailing Stop only")
    print("="*50)
    print("Loading configuration from .env file...")
    
    try:
        bot = AlpacaSpotBot()
        dashboard_thread = threading.Thread(target=run_dashboard, daemon=True)
        dashboard_thread.start()
        print("\n🌐 Web Dashboard: http://localhost:5000")
        print("   Live updates every 3 seconds - No page refresh!")
        print("   Logs show last 10 entries (newest at BOTTOM)")
        print("")
        response = input("🚀 Start paper trading? (y/n): ").lower().strip()
        if response == 'y':
            print("\n⚠️  Crypto trading runs 24/7. Press Ctrl+C to stop.")
            print("📊 BUY: MA crossover | SELL: Trailing stop only")
            bot.run_strategy()
        else:
            print("Bot stopped.")
    except Exception as e:
        print(f"\n❌ Error: {e}")


if __name__ == "__main__":
    main()

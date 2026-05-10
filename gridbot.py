import os
import time
import logging
import threading
import sys
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


# HTML Template for Dashboard with Net P&L
DASHBOARD_TEMPLATE = """
<!DOCTYPE html>
<html>
<head>
    <title>ALPACA SPOT BOT - Net P&L</title>
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
        h1 { text-align: center; margin-bottom: 30px; color: #00d4ff; }
        .grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(400px, 1fr));
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
        }
        .stat-value {
            font-size: 1.8em;
            font-weight: bold;
        }
        .stat-label { color: #aaa; font-size: 0.85em; }
        .positive { color: #00ff88; }
        .negative { color: #ff4444; }
        .neutral { color: #ffaa00; }
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
        button.success { background: #00aa44; color: #fff; }
        .logs {
            height: 250px;
            overflow-y: auto;
            font-family: monospace;
            font-size: 0.7em;
            background: rgba(0,0,0,0.3);
            border-radius: 10px;
            padding: 10px;
        }
        .log-entry { 
            border-bottom: 1px solid rgba(255,255,255,0.05); 
            padding: 4px 0;
            font-family: monospace;
            font-size: 0.7em;
        }
        .data-table {
            width: 100%;
            border-collapse: collapse;
            font-size: 0.8em;
        }
        .data-table th, .data-table td {
            padding: 8px 4px;
            text-align: left;
            border-bottom: 1px solid rgba(255,255,255,0.1);
        }
        .data-table th { color: #00d4ff; }
        .setting-row {
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin: 10px 0;
            padding: 5px;
            background: rgba(0,0,0,0.2);
            border-radius: 5px;
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
            text-align: center;
            margin-top: 10px;
            padding: 8px;
            background: rgba(0,0,0,0.3);
            border-radius: 8px;
            font-family: monospace;
        }
        .action-buttons { white-space: nowrap; }
        .info-note {
            font-size: 0.7em;
            color: #ffaa00;
            text-align: center;
            margin-top: 10px;
        }
        @media (max-width: 768px) {
            .grid { grid-template-columns: 1fr; }
            .action-buttons { white-space: normal; }
        }
    </style>
</head>
<body>
    <div class="container">
        <h1>ðŸ¤– ALPACA SPOT BOT - NET P&L</h1>
        
        <div class="grid">
            <!-- Account Status Card -->
            <div class="card">
                <h3>ðŸ“Š Account Status</h3>
                <div class="setting-row">
                    <span class="stat-label">Starting Balance</span>
                    <span class="stat-value" id="startingBalance">$0.00</span>
                </div>
                <div class="setting-row">
                    <span class="stat-label">Portfolio Value</span>
                    <span class="stat-value" id="portfolioValue">$0.00</span>
                </div>
                <div class="setting-row">
                    <span class="stat-label">Buying Power</span>
                    <span class="stat-value" id="buyingPower">$0.00</span>
                </div>
                <div class="setting-row">
                    <span class="stat-label">Net Realized P&L (after fees)</span>
                    <span id="realizedPnl">$0.00</span>
                </div>
                <div class="setting-row">
                    <span class="stat-label">Net Unrealized P&L</span>
                    <span id="unrealizedPnl">$0.00</span>
                </div>
                <div class="setting-row">
                    <span class="stat-label">Net Total P&L</span>
                    <span id="totalPnl">$0.00 (0.00%)</span>
                </div>
                <div class="elapsed-time">
                    â±ï¸ Running: <span id="elapsedValue">0s</span>
                </div>
            </div>
            
            <!-- Live Controls Card with Inputs -->
            <div class="card">
                <h3>ðŸŽ›ï¸ Live Controls</h3>
                
                <div class="setting-row">
                    <label>â±ï¸ Timeframe</label>
                    <select id="timeframe" onchange="updateSetting('timeframe', this.value)">
                        <option value="1Min">1 Minute</option>
                        <option value="5Min">5 Minutes</option>
                        <option value="15Min">15 Minutes</option>
                        <option value="30Min" selected>30 Minutes</option>
                        <option value="1H">1 Hour</option>
                        <option value="2H">2 Hours</option>
                        <option value="4H">4 Hours</option>
                        <option value="1D">1 Day</option>
                    </select>
                </div>
                
                <div class="setting-row">
                    <label>ðŸŽ¯ UT Sensitivity (a)</label>
                    <div style="width: 50%; display: flex; align-items: center;">
                        <input type="range" id="sensitivity" min="0.5" max="3.0" step="0.1" value="1.0" style="flex:1" oninput="updateSensitivityValue(this.value)" onchange="updateSetting('sensitivity', parseFloat(this.value))">
                        <span id="sensitivityValue" class="value-display">1.0</span>
                    </div>
                </div>
                
                <div class="setting-row">
                    <label>ðŸ“Š ATR Period</label>
                    <div style="width: 50%; display: flex; align-items: center;">
                        <input type="range" id="atr_period" min="5" max="20" step="1" value="10" style="flex:1" oninput="updateATRValue(this.value)" onchange="updateSetting('atr_period', parseInt(this.value))">
                        <span id="atrValue" class="value-display">10</span>
                    </div>
                </div>
                
                <div class="setting-row">
                    <label>ðŸ“ Grid Step (%)</label>
                    <div style="width: 50%; display: flex; align-items: center;">
                        <input type="range" id="grid_size" min="0.05" max="0.5" step="0.01" value="0.1" style="flex:1" oninput="updateGridSizeValue(this.value)" onchange="updateSetting('grid_size', parseFloat(this.value) / 100)">
                        <span id="gridSizeValue" class="value-display">0.10%</span>
                    </div>
                </div>
                
                <div class="setting-row">
                    <label>ðŸ’° Min Net Profit ($)</label>
                    <div style="width: 50%;">
                        <input type="number" id="min_net_profit" step="0.1" value="0.50" style="width: 70%;" onchange="updateSetting('min_net_profit', parseFloat(this.value))">
                    </div>
                </div>
                
                <div class="setting-row">
                    <label>ðŸ“Š Spread %</label>
                    <div style="width: 50%;">
                        <input type="number" id="spread_percent" step="0.1" value="0.3" style="width: 70%;" onchange="updateSetting('spread_percent', parseFloat(this.value) / 100)">
                        <span class="value-display">%</span>
                    </div>
                </div>
                
                <div class="setting-row">
                    <label>ðŸ“ˆ Heikin Ashi</label>
                    <select id="heikin_ashi" style="width: 50%;" onchange="updateSetting('heikin_ashi', this.value === 'true')">
                        <option value="false" selected>Disabled</option>
                        <option value="true">Enabled</option>
                    </select>
                </div>
                
                <hr>
                
                <div class="setting-row">
                    <span class="stat-label">Bot Status</span>
                    <span id="botStatus" class="status-badge" style="background:#00ff88;color:#000;">RUNNING</span>
                </div>
                <div style="text-align: center;">
                    <button onclick="fetch('/stop',{method:'POST'})" class="danger">Stop Bot</button>
                </div>
            </div>
            
            <!-- Active Positions Card -->
            <div class="card">
                <h3>ðŸ“ˆ Active Positions (Net P&L after fees)</h3>
                <table class="data-table">
                    <thead><tr><th>Symbol</th><th>Qty</th><th>Entry</th><th>Current</th><th>Net P&L</th><th>Grid Stop</th><th>Action</th></tr></thead>
                    <tbody id="positionsBody"><tr><td colspan="7" style="text-align:center;">No active positions</td></tr></tbody>
                </table>
            </div>
        </div>
        
        <div class="grid">
            <!-- Symbol Signals Card -->
            <div class="card">
                <h3>ðŸŽ¯ UT Bot Signals &amp; Manual Controls</h3>
                <table class="data-table">
                    <thead><tr><th>Symbol</th><th>Price</th><th>Trailing Stop</th><th>Signal</th><th>Position</th><th>Actions</th></tr></thead>
                    <tbody id="signalsBody"><tr><td colspan="6" style="text-align:center;">Loading...</td></tr></tbody>
                </table>
            </div>
            
            <!-- Live Logs Card -->
            <div class="card">
                <h3>ðŸ“ Live Logs</h3>
                <div class="logs" id="logs"><div class="log-entry">Waiting for logs...</div></div>
                <div class="info-note">ðŸ“Š All P&L shown are NET (after spread + fees)</div>
            </div>
        </div>
    </div>
    
    <script>
        let botStartTime = Math.floor(Date.now() / 1000);
        
        function updateElapsedTime() {
            let elapsed = Math.floor((Date.now() / 1000) - botStartTime);
            let h = Math.floor(elapsed / 3600), m = Math.floor((elapsed % 3600) / 60), s = elapsed % 60;
            document.getElementById('elapsedValue').innerText = (h?h+'h ':'') + (m?m+'m ':'') + s+'s';
        }
        
        function updateSensitivityValue(val) {
            document.getElementById('sensitivityValue').innerText = parseFloat(val).toFixed(1);
        }
        function updateATRValue(val) {
            document.getElementById('atrValue').innerText = val;
        }
        function updateGridSizeValue(val) {
            document.getElementById('gridSizeValue').innerText = parseFloat(val).toFixed(2) + '%';
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
        
        function manualAction(symbol, action) {
            fetch('/manual_action', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({symbol: symbol, action: action})
            });
        }
        
        function updateDashboard(data) {
            // Account data
            if (data.account) {
                document.getElementById('startingBalance').innerHTML = '$' + (data.account.starting_balance?.toFixed(2) || '0.00');
                document.getElementById('portfolioValue').innerHTML = '$' + (data.account.portfolio_value?.toFixed(2) || '0.00');
                document.getElementById('buyingPower').innerHTML = '$' + (data.account.buying_power?.toFixed(2) || '0.00');
                
                let pnlClass = data.account.total_net_pnl >= 0 ? 'positive' : 'negative';
                document.getElementById('realizedPnl').innerHTML = '<span class="' + pnlClass + '">$' + (data.account.net_realized_pnl?.toFixed(2) || '0.00') + '</span>';
                document.getElementById('unrealizedPnl').innerHTML = '<span class="' + pnlClass + '">$' + (data.account.net_unrealized_pnl?.toFixed(2) || '0.00') + '</span>';
                document.getElementById('totalPnl').innerHTML = '<span class="' + pnlClass + '">$' + (data.account.total_net_pnl?.toFixed(2) || '0.00') + ' (' + (data.account.total_net_pnl_percent?.toFixed(2) || '0.00') + '%)</span>';
            }
            
            // Settings - update input values
            if (data.current_settings) {
                let tf = document.getElementById('timeframe');
                if (tf && data.current_settings.timeframe !== tf.value) tf.value = data.current_settings.timeframe;
                
                let sens = document.getElementById('sensitivity');
                if (sens && data.current_settings.sensitivity !== parseFloat(sens.value)) {
                    sens.value = data.current_settings.sensitivity;
                    document.getElementById('sensitivityValue').innerText = data.current_settings.sensitivity.toFixed(1);
                }
                
                let atr = document.getElementById('atr_period');
                if (atr && data.current_settings.atr_period !== parseInt(atr.value)) {
                    atr.value = data.current_settings.atr_period;
                    document.getElementById('atrValue').innerText = data.current_settings.atr_period;
                }
                
                let gs = document.getElementById('grid_size');
                if (gs && (data.current_settings.grid_size || 0.001) * 100 !== parseFloat(gs.value)) {
                    gs.value = (data.current_settings.grid_size || 0.001) * 100;
                    document.getElementById('gridSizeValue').innerText = ((data.current_settings.grid_size || 0.001) * 100).toFixed(2) + '%';
                }
                
                let mp = document.getElementById('min_net_profit');
                if (mp && data.current_settings.min_net_profit !== parseFloat(mp.value)) mp.value = data.current_settings.min_net_profit;
                
                let sp = document.getElementById('spread_percent');
                if (sp && (data.current_settings.spread_percent || 0.003) * 100 !== parseFloat(sp.value)) sp.value = (data.current_settings.spread_percent || 0.003) * 100;
                
                let ha = document.getElementById('heikin_ashi');
                if (ha && data.current_settings.heikin_ashi?.toString() !== ha.value) ha.value = data.current_settings.heikin_ashi ? 'true' : 'false';
            }
            
            // Positions with Net P&L
            if (data.positions && data.positions.length > 0) {
                let html = '';
                for (let pos of data.positions) {
                    let pnlClass = pos.net_pnl >= 0 ? 'positive' : (pos.net_pnl < 0 ? 'negative' : 'neutral');
                    html += `<tr>
                        <td>${pos.symbol}</td>
                        <td>${pos.qty.toFixed(6)}</td>
                        <td>$${pos.entry_price.toFixed(2)}</td>
                        <td>$${pos.current_price.toFixed(2)}</td>
                        <td class="${pnlClass}">$${pos.net_pnl.toFixed(2)}</td>
                        <td class="positive">${pos.grid_stop ? '$'+pos.grid_stop.toFixed(2) : 'N/A'}</td>
                        <td class="action-buttons"><button onclick="manualAction('${pos.symbol}','close')" class="danger">Close</button></td>
                    </tr>`;
                }
                document.getElementById('positionsBody').innerHTML = html;
            } else {
                document.getElementById('positionsBody').innerHTML = '<tr><td colspan="7" style="text-align:center;">No active positions</td></tr>';
            }
            
            // Signals
            if (data.symbols && data.symbols.length > 0) {
                let html = '';
                for (let sym of data.symbols) {
                    let signalBadge = sym.signal_type ? `<span class="status-badge signal-${sym.signal_type.toLowerCase()}">${sym.signal_type}</span>` : '<span class="status-badge" style="background:#888">NONE</span>';
                    let positionBadge = sym.position_status === 'long' ? '<span class="status-badge status-long">LONG</span>' : '<span class="status-badge status-flat">FLAT</span>';
                    html += `<tr>
                        <td>${sym.symbol}</td>
                        <td>$${sym.price.toFixed(2)}</td>
                        <td>$${sym.trailing_stop.toFixed(2)}</td>
                        <td>${signalBadge}</td>
                        <td>${positionBadge}</td>
                        <td class="action-buttons">
                            <button onclick="manualAction('${sym.symbol}','buy')" class="success">Buy</button>
                            <button onclick="manualAction('${sym.symbol}','close')" class="danger">Close</button>
                        </td>
                    </tr>`;
                }
                document.getElementById('signalsBody').innerHTML = html;
            }
            
            // Logs
            if (data.logs && data.logs.length > 0) {
                let logsHtml = '';
                for (let log of data.logs.slice(-15)) {
                    logsHtml += `<div class="log-entry">${log}</div>`;
                }
                document.getElementById('logs').innerHTML = logsHtml;
            }
            
            if (data.bot_start_time) botStartTime = data.bot_start_time;
            if (data.bot_running !== undefined) {
                let el = document.getElementById('botStatus');
                if (data.bot_running) {
                    el.style.background = '#00ff88';
                    el.style.color = '#000';
                    el.innerText = 'RUNNING';
                } else {
                    el.style.background = '#ff4444';
                    el.style.color = '#fff';
                    el.innerText = 'STOPPED';
                }
            }
        }
        
        // Fetch and update every 3 seconds
        fetch('/api/status').then(r=>r.json()).then(d=>updateDashboard(d));
        setInterval(() => { fetch('/api/status').then(r=>r.json()).then(d=>updateDashboard(d)); }, 3000);
        setInterval(updateElapsedTime, 1000);
    </script>
</body>
</html>
"""


class AlpacaSpotBot:
    """Alpaca Spot Bot - Grid Trailing Stop with Net P&L"""
    
    def __init__(self):
        """Initialize bot with parameters from .env file"""
        
        self.bot_start_time = time.time()
        
        symbols_str = os.getenv('SYMBOLS', 'ETH/USD,BTC/USD,SOL/USD')
        self.symbols = [s.strip() for s in symbols_str.split(',')]
        
        self._load_settings_from_env()
        
        self.symbol_quantities = {}
        for symbol in self.symbols:
            base = symbol.replace('/USD', '').replace('USDT', '')
            qty_env = os.getenv(f'QUANTITY_{base}', str(self.quantity))
            self.symbol_quantities[symbol] = float(qty_env)
        
        self._update_timeframe_settings()
        
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
        
        self.last_buy_signal = {symbol: False for symbol in self.symbols}
        self.trades_history = []
        self.logs = []
        
        # Track grid stops per symbol
        self.grid_stops = {symbol: None for symbol in self.symbols}
        
        # Net P&L tracking
        self.total_net_realized_pnl = 0.0
        self.day_net_realized_pnl = 0.0
        self.day_date = datetime.now().date()
        
        self.starting_balance = float(os.getenv('STARTING_BALANCE', '100000.00'))
        self.day_start_equity = None
        self.today_date = None
        
        self._log_configuration()
    
    def calculate_net_pnl(self, entry_price, exit_price, qty):
        """Calculate net P&L after spread and fees"""
        position_value = entry_price * qty
        spread_cost = position_value * self.spread_percent
        fee_cost = position_value * self.fee_percent * 2
        total_costs = spread_cost + fee_cost
        
        gross_pnl = (exit_price - entry_price) * qty
        net_pnl = gross_pnl - total_costs
        
        return net_pnl, gross_pnl, total_costs
    
    def get_position_net_pnl(self, symbol, entry_price, current_price, qty):
        """Calculate current net P&L for an open position"""
        return self.calculate_net_pnl(entry_price, current_price, qty)[0]
    
    def _load_settings_from_env(self):
        """Load settings from .env file"""
        self.quantity = float(os.getenv('QUANTITY', '0.01'))
        self.timeframe_str = os.getenv('TIMEFRAME', '30Min')
        self.a = float(os.getenv('SENSITIVITY', '1.0'))
        self.atr_period = int(os.getenv('ATR_PERIOD', '10'))
        self.use_heikin_ashi = os.getenv('HEIKIN_ASHI', 'False').lower() == 'true'
        self.paper_trading = os.getenv('PAPER_TRADING', 'True').lower() == 'true'
        self.running = True
        
        # Grid stop settings
        self.grid_size = float(os.getenv('GRID_SIZE', '0.001'))
        self.first_profit_level = float(os.getenv('FIRST_PROFIT_LEVEL', '0.009'))
        
        # Spread and fee protection
        self.spread_percent = float(os.getenv('SPREAD_PERCENT', '0.003'))
        self.fee_percent = float(os.getenv('FEE_PERCENT', '0.0025'))
        self.min_net_profit = float(os.getenv('MIN_NET_PROFIT', '0.50'))
    
    def _update_timeframe_settings(self):
        """Update timeframe-related settings"""
        self.timeframe_minutes = self._parse_timeframe_to_minutes(self.timeframe_str)
        self.interval_map = {
            "1Min": 60, "5Min": 300, "15Min": 900, "30Min": 1800,
            "1H": 3600, "2H": 7200, "4H": 14400, "1D": 86400
        }
        self.check_interval = self.interval_map.get(self.timeframe_str, 1800)
        self.bars_to_fetch = 300 if self.timeframe_str in ["1D", "4H"] else 200
    
    def _log_configuration(self):
        """Log current configuration"""
        logger.info("="*50)
        logger.info("ALPACA SPOT BOT - GRID TRAILING STOP")
        logger.info("="*50)
        logger.info(f"Starting Balance: ${self.starting_balance:,.2f}")
        logger.info(f"Symbols: {', '.join(self.symbols)}")
        logger.info(f"Timeframe: {self.timeframe_str}")
        logger.info(f"UT Sensitivity (a): {self.a}")
        logger.info(f"ATR Period: {self.atr_period}")
        logger.info(f"Grid Size: {self.grid_size*100:.2f}%")
        logger.info(f"First Profit Level: {self.first_profit_level*100:.1f}%")
        logger.info(f"Heikin Ashi: {self.use_heikin_ashi}")
        logger.info("-"*30)
        logger.info("SPREAD PROTECTION (Net P&L):")
        logger.info(f"  Spread: {self.spread_percent*100:.1f}%")
        logger.info(f"  Fees: {self.fee_percent*100:.1f}%")
        logger.info(f"  Min Net Profit: ${self.min_net_profit}")
        logger.info("="*50)
    
    def update_setting(self, setting, value):
        """Update a setting live"""
        if setting == 'timeframe':
            self.timeframe_str = value
            self._update_timeframe_settings()
            self.add_log(f"âš™ï¸ Timeframe changed to {value}")
        elif setting == 'sensitivity':
            self.a = float(value)
            self.add_log(f"âš™ï¸ UT Sensitivity changed to {self.a}")
        elif setting == 'atr_period':
            self.atr_period = int(value)
            self.add_log(f"âš™ï¸ ATR Period changed to {self.atr_period}")
        elif setting == 'grid_size':
            self.grid_size = float(value)
            self.add_log(f"âš™ï¸ Grid Step changed to {self.grid_size*100:.2f}%")
        elif setting == 'min_net_profit':
            self.min_net_profit = float(value)
            self.add_log(f"âš™ï¸ Min Net Profit changed to ${self.min_net_profit}")
        elif setting == 'spread_percent':
            self.spread_percent = float(value)
            self.add_log(f"âš™ï¸ Spread changed to {self.spread_percent*100:.1f}%")
        elif setting == 'heikin_ashi':
            self.use_heikin_ashi = bool(value)
            self.add_log(f"âš™ï¸ Heikin Ashi {'enabled' if self.use_heikin_ashi else 'disabled'}")
        
        self._update_env_file(setting, value)
        return True
    
    def _update_env_file(self, setting, value):
        """Update .env file"""
        env_path = os.path.join(os.path.dirname(__file__), '.env')
        env_key_map = {
            'timeframe': 'TIMEFRAME',
            'sensitivity': 'SENSITIVITY',
            'atr_period': 'ATR_PERIOD',
            'grid_size': 'GRID_SIZE',
            'min_net_profit': 'MIN_NET_PROFIT',
            'spread_percent': 'SPREAD_PERCENT',
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
            'sensitivity': self.a,
            'atr_period': self.atr_period,
            'grid_size': self.grid_size,
            'min_net_profit': self.min_net_profit,
            'spread_percent': self.spread_percent,
            'heikin_ashi': self.use_heikin_ashi
        }
    
    def _parse_timeframe_to_minutes(self, timeframe_str):
        timeframe_map = {
            "1Min": 1, "5Min": 5, "15Min": 15, "30Min": 30,
            "1H": 60, "2H": 120, "4H": 240, "1D": 1440
        }
        return timeframe_map.get(timeframe_str, 30)
    
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
        timestamp = datetime.now().strftime('%H:%M:%S')
        log_entry = f"[{timestamp}] {message}"
        self.logs.append(log_entry)
        if len(self.logs) > 50:
            self.logs = self.logs[-50:]
        
        if level == "ERROR":
            logger.error(message)
        else:
            logger.info(message)
    
    def calculate_grid_stop(self, symbol, entry_price, current_price, qty):
        """Grid-based trailing stop that only activates after profitable"""
        
        position_value = entry_price * qty
        spread_cost = position_value * self.spread_percent
        fee_cost = position_value * self.fee_percent * 2
        total_costs = spread_cost + fee_cost
        cost_percent = total_costs / position_value if position_value > 0 else 0
        
        first_profit_level_price = entry_price * (1 + self.first_profit_level + cost_percent)
        exit_buffer = 0.0002
        
        if current_price >= first_profit_level_price:
            grid_step_price = entry_price * self.grid_size
            levels_above = int((current_price - first_profit_level_price) / grid_step_price)
            current_stop = first_profit_level_price + (levels_above * grid_step_price)
            current_stop = current_stop * (1 - exit_buffer)
            
            sell_price = current_stop
            gross_pnl = (sell_price - entry_price) * qty
            net_profit = gross_pnl - total_costs
            net_profit_percent = (net_profit / position_value) * 100 if position_value > 0 else 0
            
            self.add_log(f"ðŸ“Š {symbol} Grid Stop: Level {levels_above} | Stop: ${current_stop:.2f} | Net Profit: {net_profit_percent:.2f}%")
            return current_stop, True
        else:
            return None, False
    
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
        """Original UT Bot signal calculation"""
        df = df.copy()
        
        if self.use_heikin_ashi:
            ha = self.get_heikin_ashi(df)
            price = ha['close']
        else:
            price = df['close']
        
        atr = self.calculate_atr(df, self.atr_period)
        n_loss = self.a * atr
        
        ut_trailing_stop = pd.Series(index=df.index, dtype=float)
        
        for i in range(len(df)):
            if i == 0:
                ut_trailing_stop.iloc[i] = price.iloc[i] - n_loss.iloc[i]
                continue
            
            prev_stop = ut_trailing_stop.iloc[i-1]
            curr_price = price.iloc[i]
            prev_price = price.iloc[i-1]
            
            if curr_price > prev_stop and prev_price > prev_stop:
                ut_trailing_stop.iloc[i] = max(prev_stop, curr_price - n_loss.iloc[i])
            elif curr_price < prev_stop and prev_price < prev_stop:
                ut_trailing_stop.iloc[i] = min(prev_stop, curr_price + n_loss.iloc[i])
            elif curr_price > prev_stop:
                ut_trailing_stop.iloc[i] = curr_price - n_loss.iloc[i]
            else:
                ut_trailing_stop.iloc[i] = curr_price + n_loss.iloc[i]
        
        df['trailing_stop'] = ut_trailing_stop
        
        price_cross_above = (price > df['trailing_stop']) & (price.shift(1) <= df['trailing_stop'].shift(1))
        price_cross_below = (price < df['trailing_stop']) & (price.shift(1) >= df['trailing_stop'].shift(1))
        
        df['buy_signal'] = price_cross_above
        df['sell_signal'] = price_cross_below
        
        return df
    
    @retry_on_timeout(max_retries=3, delay=2)
    def get_historical_data(self, symbol, bars=None):
        if bars is None:
            bars = self.bars_to_fetch
            
        end = datetime.now()
        total_minutes = self.timeframe_minutes * (bars + 100)
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
            limit=bars + 150
        )
        
        bars_data = self.data_client.get_crypto_bars(request)
        if not bars_data.data or symbol not in bars_data.data:
            return None
            
        df = bars_data.df
        if df.empty or len(df) < 100:
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
            self.add_log(f"âœ… {side.upper()} {quantity} {display} at ${fill_price:.2f}")
            return order
        except Exception as e:
            self.add_log(f"Order failed for {symbol}: {e}", "ERROR")
            return None
    
    def manual_buy(self, symbol):
        display = symbol.replace('/USD', '')
        self.add_log(f"ðŸ”µ MANUAL BUY for {display}")
        return self.execute_order(symbol, OrderSide.BUY)
    
    def manual_sell(self, symbol):
        display = symbol.replace('/USD', '')
        self.add_log(f"ðŸ”´ MANUAL CLOSE for {display}")
        
        try:
            positions = self.trading_client.get_all_positions()
            alpaca_symbol = self.normalize_symbol(symbol, to_display=False)
            for pos in positions:
                if pos.symbol == alpaca_symbol:
                    qty = abs(float(pos.qty))
                    return self.execute_order(symbol, OrderSide.SELL, qty)
            self.add_log(f"No position found for {symbol}")
            return None
        except Exception as e:
            self.add_log(f"Error closing {symbol}: {e}", "ERROR")
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
    
    def close_position(self, symbol):
        try:
            positions = self.trading_client.get_all_positions()
            alpaca_symbol = self.normalize_symbol(symbol, to_display=False)
            for pos in positions:
                if pos.symbol == alpaca_symbol:
                    qty = abs(float(pos.qty))
                    entry_price = float(pos.avg_entry_price)
                    
                    order = self.execute_order(symbol, OrderSide.SELL, qty)
                    
                    if order and order.filled_avg_price:
                        fill_price = float(order.filled_avg_price)
                        net_pnl, gross_pnl, costs = self.calculate_net_pnl(entry_price, fill_price, qty)
                    else:
                        df = self.get_historical_data(symbol, bars=2)
                        fill_price = df.iloc[-1]['close'] if df is not None else entry_price
                        net_pnl, gross_pnl, costs = self.calculate_net_pnl(entry_price, fill_price, qty)
                    
                    # Update net P&L tracking
                    self.total_net_realized_pnl += net_pnl
                    
                    current_date = datetime.now().date()
                    if current_date != self.day_date:
                        self.day_date = current_date
                        self.day_net_realized_pnl = 0
                    self.day_net_realized_pnl += net_pnl
                    
                    trade = {
                        'time': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                        'symbol': symbol,
                        'type': "CLOSE_LONG",
                        'entry_price': entry_price,
                        'exit_price': fill_price,
                        'qty': qty,
                        'gross_pnl': gross_pnl,
                        'costs': costs,
                        'net_pnl': net_pnl
                    }
                    self.trades_history.insert(0, trade)
                    self.add_log(f"âœ… Closed {symbol}: {qty} @ ${fill_price:.2f} | Gross: ${gross_pnl:.2f} | Costs: ${costs:.2f} | NET: ${net_pnl:.2f}")
                    
                    self.grid_stops[symbol] = None
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
            self.add_log("âœ… Closed all positions")
            return True
        except Exception as e:
            self.add_log(f"Error closing all positions: {e}", "ERROR")
            return False
    
    def get_account_status(self):
        """Get current account status with Net P&L"""
        try:
            account = self.trading_client.get_account()
            current_equity = float(account.equity)
            
            total_net_pnl = current_equity - self.starting_balance
            
            # Calculate net unrealized P&L
            net_unrealized_pnl = 0.0
            try:
                positions = self.trading_client.get_all_positions()
                for pos in positions:
                    if self.normalize_symbol(pos.symbol, to_display=True) in self.symbols:
                        entry = float(pos.avg_entry_price)
                        current = float(pos.current_price)
                        qty = abs(float(pos.qty))
                        _, _, _ = self.calculate_net_pnl(entry, current, qty)
                        net_pnl = self.get_position_net_pnl(pos.symbol, entry, current, qty)
                        net_unrealized_pnl += net_pnl
            except Exception:
                pass
            
            net_realized_pnl = total_net_pnl - net_unrealized_pnl
            total_net_pnl_percent = (total_net_pnl / self.starting_balance * 100) if self.starting_balance > 0 else 0
            
            return {
                'buying_power': float(account.buying_power),
                'portfolio_value': current_equity,
                'net_realized_pnl': net_realized_pnl,
                'net_unrealized_pnl': net_unrealized_pnl,
                'total_net_pnl': total_net_pnl,
                'total_net_pnl_percent': total_net_pnl_percent,
                'starting_balance': self.starting_balance
            }
        except Exception as e:
            return {
                'buying_power': 0, 'portfolio_value': 0,
                'net_realized_pnl': 0, 'net_unrealized_pnl': 0,
                'total_net_pnl': 0, 'total_net_pnl_percent': 0,
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
                    current = float(pos.current_price)
                    qty = float(pos.qty)
                    net_pnl = self.get_position_net_pnl(display_symbol, entry, current, abs(qty))
                    grid_stop, _ = self.calculate_grid_stop(display_symbol, entry, current, abs(qty))
                    positions.append({
                        'symbol': display_symbol,
                        'qty': qty,
                        'entry_price': entry,
                        'current_price': current,
                        'net_pnl': net_pnl,
                        'grid_stop': grid_stop if grid_stop else None
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
    
    def is_profitable_enough(self, symbol, entry_price, current_price, qty):
        """Check if net profit is enough to overcome costs"""
        net_pnl, _, _ = self.calculate_net_pnl(entry_price, current_price, qty)
        
        if net_pnl <= 0:
            return False
        if net_pnl < self.min_net_profit:
            self.add_log(f"âš ï¸ {symbol} Net profit ${net_pnl:.4f} < ${self.min_net_profit:.2f} - holding")
            return False
        
        self.add_log(f"âœ… {symbol} Net profit ${net_pnl:.4f} >= ${self.min_net_profit:.2f} - proceed")
        return True
    
    def process_symbol(self, symbol):
        try:
            df = self.get_historical_data(symbol)
            if df is None or len(df) < 100:
                return
            
            signals_df = self.calculate_signals(df)
            latest_data = signals_df.iloc[-1]
            
            latest_close = latest_data['close']
            latest_trailing_stop = latest_data['trailing_stop']
            
            buy_signal = latest_data['buy_signal']
            sell_signal = latest_data['sell_signal']
            
            display = symbol.replace('/USD', '')
            
            has_position = self.get_position_status(symbol)
            position_info = self.get_position_info(symbol) if has_position else None
            
            if has_position and position_info:
                entry_price = position_info['entry']
                qty = position_info['qty']
                
                grid_stop, is_active = self.calculate_grid_stop(display, entry_price, latest_close, qty)
                self.grid_stops[symbol] = grid_stop
                
                if is_active and latest_close <= grid_stop:
                    self.add_log(f"ðŸŽ¯ {display} Grid Stop Hit! Selling at ${latest_close:.2f}")
                    self.close_position(symbol)
                    return
            
            if not hasattr(self, '_last_log_time'):
                self._last_log_time = {}
            
            current_time = time.time()
            if symbol not in self._last_log_time or (current_time - self._last_log_time[symbol]) > 30:
                self.add_log(f"{display}: ${latest_close:.2f} | Stop: ${latest_trailing_stop:.2f}")
                self._last_log_time[symbol] = current_time
            
            if buy_signal and not has_position:
                self.add_log(f"ðŸŽ¯ {display} ðŸ”µ BUY SIGNAL at ${latest_close:.2f}")
                self.add_log(f"ðŸ”µ {display} - Going LONG")
                self.execute_order(symbol, OrderSide.BUY)
                self.last_buy_signal[symbol] = True
            
            elif sell_signal and has_position:
                self.add_log(f"ðŸŽ¯ {display} ðŸ”´ SELL SIGNAL at ${latest_close:.2f}")
                if position_info:
                    entry_price = position_info['entry']
                    qty = position_info['qty']
                    
                    if self.grid_stops.get(symbol):
                        self.add_log(f"ðŸ”´ {display} - Grid stop active. Following grid stop.")
                    else:
                        if self.is_profitable_enough(display, entry_price, latest_close, qty):
                            self.add_log(f"ðŸ”´ {display} - Closing position (profitable)")
                            self.close_position(symbol)
                        else:
                            self.add_log(f"ðŸ”´ {display} - Holding (net profit below threshold)")
                else:
                    self.close_position(symbol)
                    
        except Exception as e:
            self.add_log(f"Error processing {symbol}: {e}", "ERROR")
    
    def run_strategy(self):
        global bot_instance
        bot_instance = self
        
        self.add_log(f"ðŸš€ Starting ALPACA SPOT BOT - Net P&L Tracking")
        self.add_log(f"ðŸ’° Starting Balance: ${self.starting_balance:,.2f}")
        self.add_log(f"ðŸ“Š UT Bot: Price crosses ATR trailing stop (a={self.a}, ATR={self.atr_period})")
        self.add_log(f"ðŸ“Š Grid Stop: First at +{self.first_profit_level*100:.1f}%, then every +{self.grid_size*100:.2f}%")
        self.add_log(f"ðŸ›¡ï¸ All P&L shown are NET after {self.spread_percent*100:.1f}% spread + {self.fee_percent*100:.1f}% fees")
        self.add_log(f"ðŸ“Š Monitoring: {', '.join(self.symbols)}")
        self.add_log(f"ðŸŒ Web dashboard: http://localhost:5000")
        
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
                df = self.get_historical_data(symbol, bars=150)
                if df is not None:
                    signals = self.calculate_signals(df)
                    has_position = self.get_position_status(symbol)
                    latest = signals.iloc[-1]
                    
                    signal_type = None
                    if latest['buy_signal'] and not has_position:
                        signal_type = 'BUY'
                    elif latest['sell_signal'] and has_position:
                        signal_type = 'SELL'
                    
                    symbols_data.append({
                        'symbol': symbol.replace('/USD', '').replace('USDT', ''),
                        'price': float(latest['close']),
                        'trailing_stop': float(latest['trailing_stop']),
                        'signal_type': signal_type,
                        'position_status': 'long' if has_position else 'flat'
                    })
            except Exception:
                symbols_data.append({
                    'symbol': symbol.replace('/USD', '').replace('USDT', ''),
                    'price': 0, 'trailing_stop': 0,
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
        'logs': bot_instance.logs[-50:],
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


@app.route('/manual_action', methods=['POST'])
def manual_action():
    global bot_instance
    if not bot_instance:
        return jsonify({'status': 'error', 'message': 'Bot not running'})
    
    data = request.get_json()
    symbol = data.get('symbol')
    action = data.get('action')
    
    alpaca_symbol = f"{symbol}/USD"
    
    if action == 'buy':
        result = bot_instance.manual_buy(alpaca_symbol)
    elif action == 'close':
        result = bot_instance.manual_sell(alpaca_symbol)
    else:
        return jsonify({'status': 'error', 'message': 'Invalid action'})
    
    if result:
        return jsonify({'status': 'ok', 'message': f'{action} executed for {symbol}'})
    else:
        return jsonify({'status': 'error', 'message': f'Failed to execute {action} for {symbol}'})
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
    print("ðŸ¤– ALPACA SPOT BOT - NET P&L VERSION")
    print("="*50)
    print("  BUY:  Price crosses ABOVE ATR trailing stop")
    print("  SELL: Grid stop when price falls below locked profit level")
    print("  GRID: First stop at +0.9%, then every +0.1%")
    print("  P&L:  ALL profits shown are NET after spread & fees")
    print("="*50)
    print("Loading configuration from .env file...")
    
    # Check for auto-start flag
    auto_start = '--auto' in sys.argv or '-y' in sys.argv
    
    try:
        bot = AlpacaSpotBot()
        dashboard_thread = threading.Thread(target=run_dashboard, daemon=True)
        dashboard_thread.start()
        print("\nðŸŒ Web Dashboard: http://localhost:5000")
        print("   ðŸ“Š All P&L shown are NET after spread + fees")
        print("   ðŸ›¡ï¸ Spread protection active")
        print("   ðŸŽ¯ Manual Buy/Close buttons available")
        print("")
        
        if auto_start:
            print("ðŸš€ Auto-starting paper trading...")
            response = 'y'
        else:
            response = input("ðŸš€ Start paper trading? (y/n): ").lower().strip()
        
        if response == 'y':
            print("\nâš ï¸  Crypto trading runs 24/7. Press Ctrl+C to stop.")
            print("ðŸ“Š BUY: Price crosses above trailing stop")
            print("ðŸ“Š EXIT: Grid stop (never sell at a loss)")
            print("ðŸ’° All P&L displayed is NET after costs")
            bot.run_strategy()
        else:
            print("Bot stopped.")
    except Exception as e:
        print(f"\nâŒ Error: {e}")


if __name__ == "__main__":
    main()

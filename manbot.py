import os
import time
import logging
import threading
import sys
from datetime import datetime, timedelta
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
        logging.FileHandler('manual_bot.log'),
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


# Minimum quantity requirements for Alpaca crypto
MINIMUM_QUANTITIES = {
    'AAVE': 0.009, 'ADA': 8, 'ALGO': 5, 'APE': 0.1, 'ARB': 0.5,
    'ATOM': 0.1, 'AVAX': 0.1, 'BAT': 9, 'BCH': 0.002, 'BTC': 0.00002,
    'CRV': 3.8, 'DOGE': 30, 'DOT': 0.8, 'ETC': 0.05, 'ETH': 0.0005,
    'FIL': 0.05, 'GRT': 35, 'LINK': 0.1, 'LTC': 0.02, 'MATIC': 6,
    'MKR': 0.0006, 'NEAR': 0.1, 'OP': 0.3, 'SHIB': 152000, 'SOL': 0.02,
    'SUI': 0.1, 'UNI': 0.26, 'XLM': 10, 'XTZ': 2.6
}

# HTML Template for Dashboard
DASHBOARD_TEMPLATE = """
<!DOCTYPE html>
<html>
<head>
    <title>MANUAL BUY/SELL + BOT SELL ONLY</title>
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
        h1 { text-align: center; margin-bottom: 15px; color: #00d4ff; font-size: 1.5em; }
        .subtitle { text-align: center; margin-bottom: 25px; color: #ffaa00; font-size: 0.85em; }
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
            font-size: 1.1em;
        }
        .stat-value {
            font-size: 1.5em;
            font-weight: bold;
        }
        .stat-label { color: #aaa; font-size: 0.8em; }
        .positive { color: #00ff88; }
        .negative { color: #ff4444; }
        .neutral { color: #ffaa00; }
        .status-badge {
            display: inline-block;
            padding: 4px 12px;
            border-radius: 20px;
            font-size: 0.75em;
            font-weight: bold;
        }
        .status-long { background: #00ff88; color: #000; }
        .status-flat { background: #888; color: #fff; }
        button {
            background: #00d4ff;
            color: #000;
            border: none;
            padding: 5px 10px;
            border-radius: 5px;
            cursor: pointer;
            font-weight: bold;
            margin: 3px;
            font-size: 0.7em;
        }
        button:hover { opacity: 0.8; }
        button.danger { background: #ff4444; color: #fff; }
        button.success { background: #00aa44; color: #fff; }
        button.disabled { background: #555; cursor: not-allowed; opacity: 0.5; }
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
            font-size: 0.7em;
        }
        .data-table th, .data-table td {
            padding: 6px 3px;
            text-align: left;
            border-bottom: 1px solid rgba(255,255,255,0.1);
        }
        .data-table th { color: #00d4ff; }
        .setting-row {
            display: flex;
            justify-content: space-between;
            margin: 8px 0;
            padding: 5px;
            background: rgba(0,0,0,0.2);
            border-radius: 5px;
        }
        .setting-row label { width: 45%; font-size: 0.8em; }
        .setting-row input, .setting-row select { 
            width: 50%; 
            padding: 4px;
            border-radius: 5px;
            border: none;
            background: rgba(255,255,255,0.2);
            color: #fff;
        }
        .setting-row input[type="range"] { width: 50%; }
        .value-display { 
            font-size: 0.8em; 
            color: #00d4ff;
            margin-left: 8px;
        }
        .elapsed-time {
            text-align: center;
            margin-top: 10px;
            padding: 8px;
            background: rgba(0,0,0,0.3);
            border-radius: 8px;
            font-family: monospace;
            font-size: 0.8em;
        }
        .action-buttons { white-space: nowrap; }
        .info-note {
            font-size: 0.65em;
            color: #00ff88;
            text-align: center;
            margin-top: 10px;
        }
        .warning-note {
            font-size: 0.65em;
            color: #ffaa00;
            text-align: center;
            margin-top: 5px;
        }
        hr { border-color: rgba(255,255,255,0.1); margin: 10px 0; }
        @media (max-width: 768px) {
            .grid { grid-template-columns: 1fr; }
            .action-buttons { white-space: normal; }
            .data-table { font-size: 0.6em; }
        }
    </style>
</head>
<body>
    <div class="container">
        <h1>🤖 MANUAL BUY/SELL + BOT SELL ONLY</h1>
        <div class="subtitle">📍 Manual Buy/Sell | 🔄 Bot Auto-Sell at Target Net Profit (after spread + fees)</div>

        <div class="grid">
            <!-- Account Status Card -->
            <div class="card">
                <h3>📊 Account Status</h3>
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
                    <span class="stat-label">Net Realized P&L</span>
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
                    ⏱️ Running: <span id="elapsedValue">0s</span>
                </div>
            </div>

            <!-- Live Controls Card -->
            <div class="card">
                <h3>🎛️ Live Controls</h3>
                
                <div class="setting-row">
                    <label>🎯 Target Net Profit</label>
                    <div style="width: 50%; display: flex; align-items: center;">
                        <input type="range" id="target_profit" min="1" max="20" step="0.5" value="5" style="flex:1" oninput="updateTargetValue(this.value)" onchange="updateSetting('target_profit', parseFloat(this.value) / 100)">
                        <span id="targetValue" class="value-display">5.0%</span>
                    </div>
                </div>
                
                <div class="setting-row">
                    <span class="stat-label">Spread %</span>
                    <span id="spreadValue">0.3%</span>
                </div>
                <div class="setting-row">
                    <span class="stat-label">Fee %</span>
                    <span id="feeValue">0.25%</span>
                </div>
                <hr>
                <div class="setting-row">
                    <span class="stat-label">Bot Status</span>
                    <span id="botStatus" class="status-badge" style="background:#00ff88;color:#000;">RUNNING</span>
                </div>
                <div style="text-align: center;">
                    <button onclick="fetch('/stop',{method:'POST'})" class="danger">Stop Bot</button>
                    <button onclick="fetch('/close_all_positions',{method:'POST'})" class="danger">Close All</button>
                    <button onclick="fetch('/health',{method:'GET'}).then(r=>r.json()).then(d=>alert('Status: '+d.status))" style="background:#333;">Health</button>
                </div>
            </div>

            <!-- Active Positions Card -->
            <div class="card">
                <h3>📈 Active Positions</h3>
                <table class="data-table">
                    <thead>
                        <tr><th>Symbol</th><th>Qty</th><th>Entry</th><th>Current</th><th>Mkt Value</th><th>Net P&L</th><th>Net %</th><th>Target</th><th>Action</th></tr>
                    </thead>
                    <tbody id="positionsBody">
                        <tr><td colspan="9" style="text-align:center;">No active positions</td></tr>
                    </tbody>
                </table>
            </div>
        </div>

        <!-- All Symbols Card -->
        <div class="card">
            <h3>📊 All Available Symbols - Manual Buy/Sell (sorted by price ↓)</h3>
            <table class="data-table">
                <thead>
                    <tr><th>Symbol</th><th>Price</th><th>24h Chg</th><th>24h High</th><th>24h Low</th><th>Quantity</th><th>Min</th><th>Actions</th></tr>
                </thead>
                <tbody id="symbolsBody">
                    <tr><td colspan="8" style="text-align:center;">Loading...</td></tr>
                </tbody>
            </table>
            <div class="warning-note">⚠️ Buy button disabled if quantity below minimum requirement</div>
        </div>

        <!-- Live Logs Card -->
        <div class="card">
            <h3>📝 Live Logs</h3>
            <div class="logs" id="logs"><div class="log-entry">Waiting for logs...</div></div>
            <div class="info-note">🟢 MANUAL BUY/SELL | 🔴 BOT AUTO-SELL at target net profit</div>
        </div>
    </div>

    <script>
        let botStartTime = Math.floor(Date.now() / 1000);
        
        function updateElapsedTime() {
            let elapsed = Math.floor((Date.now() / 1000) - botStartTime);
            let h = Math.floor(elapsed / 3600), m = Math.floor((elapsed % 3600) / 60), s = elapsed % 60;
            document.getElementById('elapsedValue').innerText = (h?h+'h ':'') + (m?m+'m ':'') + s+'s';
        }
        
        function updateTargetValue(val) {
            document.getElementById('targetValue').innerText = parseFloat(val).toFixed(1) + '%';
        }
        
        function updateSetting(setting, value) {
            fetch('/update_setting', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({setting: setting, value: value})
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

            // Settings
            if (data.current_settings) {
                document.getElementById('spreadValue').innerText = (data.current_settings.spread_percent * 100).toFixed(1) + '%';
                document.getElementById('feeValue').innerText = (data.current_settings.fee_percent * 100).toFixed(2) + '%';
                let targetPercent = (data.current_settings.target_profit_percent * 100).toFixed(1);
                document.getElementById('targetValue').innerText = targetPercent + '%';
                let slider = document.getElementById('target_profit');
                if (slider && parseFloat(slider.value) !== parseFloat(targetPercent)) {
                    slider.value = targetPercent;
                }
            }

            // Positions
            if (data.positions && data.positions.length > 0) {
                let html = '';
                for (let pos of data.positions) {
                    let pnlClass = pos.net_pnl >= 0 ? 'positive' : 'negative';
                    let targetClass = pos.net_percent >= pos.target_percent ? 'positive' : 'neutral';
                    html += `<tr>
                        <td>${pos.symbol}</td>
                        <td>${pos.qty.toFixed(6)}</td>
                        <td>$${pos.entry_price.toFixed(2)}</td>
                        <td>$${pos.current_price.toFixed(2)}</td>
                        <td>$${pos.market_value.toFixed(2)}</td>
                        <td class="${pnlClass}">$${pos.net_pnl.toFixed(2)}</td>
                        <td class="${pnlClass}">${pos.net_percent.toFixed(2)}%</td>
                        <td class="${targetClass}">${pos.target_percent.toFixed(1)}%</td>
                        <td class="action-buttons"><button onclick="manualAction('${pos.symbol}','close')" class="danger">Close</button></td>
                    </tr>`;
                }
                document.getElementById('positionsBody').innerHTML = html;
            } else {
                document.getElementById('positionsBody').innerHTML = '<tr><td colspan="9" style="text-align:center;">No active positions</td></tr>';
            }

            // All symbols
            if (data.symbols && data.symbols.length > 0) {
                let html = '';
                for (let sym of data.symbols) {
                    let changeClass = sym.change_24h >= 0 ? 'positive' : 'negative';
                    let buyDisabled = !sym.quantity_valid ? 'disabled' : '';
                    let buyTitle = !sym.quantity_valid ? `Minimum quantity is ${sym.min_quantity}` : '';
                    let closeAction = sym.has_position ? `<button onclick="manualAction('${sym.symbol}','close')" class="danger">Close</button>` : '';
                    html += `<tr>
                        <td><strong>${sym.symbol}</strong></td>
                        <td>$${sym.price.toFixed(2)}</td>
                        <td class="${changeClass}">${sym.change_24h.toFixed(2)}%</td>
                        <td class="positive">$${sym.high_24h.toFixed(2)}</td>
                        <td class="negative">$${sym.low_24h.toFixed(2)}</td>
                        <td>${sym.quantity.toFixed(6)}</td>
                        <td class="neutral">${sym.min_quantity}</td>
                        <td class="action-buttons">
                            <button onclick="manualAction('${sym.symbol}','buy')" class="success ${buyDisabled}" ${buyTitle}>Buy</button>
                            ${closeAction}
                        </td>
                    </tr>`;
                }
                document.getElementById('symbolsBody').innerHTML = html;
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

        fetch('/api/status').then(r=>r.json()).then(d=>updateDashboard(d));
        setInterval(() => { fetch('/api/status').then(r=>r.json()).then(d=>updateDashboard(d)); }, 3000);
        setInterval(updateElapsedTime, 1000);
    </script>
</body>
</html>
"""


class ManualSellBot:
    """Manual Buy/Sell + Bot Auto-Sell at Target Profit"""

    def __init__(self):
        self.bot_start_time = time.time()
        
        # Load symbols from .env MANUAL_SYMBOLS
        symbols_str = os.getenv('MANUAL_SYMBOLS', '')
        if symbols_str:
            self.symbols = [s.strip() for s in symbols_str.split(',')]
        else:
            # Fallback to common symbols if MANUAL_SYMBOLS not set
            self.symbols = ["SOL/USD", "BTC/USD", "ETH/USD", "BCH/USD", "AAVE/USD"]
        
        self.display_symbols = [s.replace('/USD', '') for s in self.symbols]

        # Load settings
        self._load_settings_from_env()
        
        # Load quantities from .env QUANTITY_XXX
        self.symbol_quantities = {}
        self.quantity_valid = {}
        for symbol in self.symbols:
            base = symbol.replace('/USD', '').replace('USDT', '')
            qty_env = os.getenv(f'QUANTITY_{base}')
            if qty_env:
                self.symbol_quantities[symbol] = float(qty_env)
                # Check against minimum
                min_qty = MINIMUM_QUANTITIES.get(base, 0)
                self.quantity_valid[symbol] = self.symbol_quantities[symbol] >= min_qty
                if not self.quantity_valid[symbol]:
                    logger.warning(f"⚠️ {symbol} quantity {self.symbol_quantities[symbol]} below minimum {min_qty}")
            else:
                self.symbol_quantities[symbol] = 0
                self.quantity_valid[symbol] = False
                logger.warning(f"⚠️ {symbol} has no QUANTITY_{base} in .env")

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

        self.trades_history = []
        self.logs = []

        # Net P&L tracking
        self.total_net_realized_pnl = 0.0
        self.day_net_realized_pnl = 0.0
        self.day_date = datetime.now().date()

        self.starting_balance = float(os.getenv('STARTING_BALANCE', '100000.00'))

        self._log_configuration()

    def _load_settings_from_env(self):
        """Load settings from .env file"""
        self.paper_trading = os.getenv('PAPER_TRADING', 'True').lower() == 'true'
        self.running = True
        self.spread_percent = float(os.getenv('SPREAD_PERCENT', '0.003'))
        self.fee_percent = float(os.getenv('FEE_PERCENT', '0.0025'))
        self.target_profit_percent = float(os.getenv('TARGET_PROFIT_PERCENT', '0.05'))

    def _log_configuration(self):
        """Log current configuration"""
        logger.info("="*50)
        logger.info("MANUAL BUY/SELL + BOT SELL ONLY")
        logger.info("="*50)
        logger.info(f"Starting Balance: ${self.starting_balance:,.2f}")
        logger.info(f"Symbols: {', '.join(self.display_symbols)}")
        for sym in self.symbols:
            base = sym.replace('/USD', '')
            qty = self.symbol_quantities.get(sym, 0)
            valid = "✅" if self.quantity_valid.get(sym, False) else "⚠️"
            logger.info(f"  {valid} {base}: {qty} (min: {MINIMUM_QUANTITIES.get(base, 'N/A')})")
        logger.info(f"Spread: {self.spread_percent*100:.1f}% | Fee: {self.fee_percent*100:.2f}%")
        logger.info(f"Target Net Profit: {self.target_profit_percent*100:.1f}%")
        logger.info("STRATEGY: Manual Buy/Sell | Bot Auto-Sell at target profit")
        logger.info("="*50)

    def update_setting(self, setting, value):
        """Update a setting live"""
        if setting == 'target_profit':
            self.target_profit_percent = float(value)
            self.add_log(f"⚙️ Target Net Profit changed to {self.target_profit_percent*100:.1f}%")
        return True

    def get_current_settings(self):
        return {
            'spread_percent': self.spread_percent,
            'fee_percent': self.fee_percent,
            'target_profit_percent': self.target_profit_percent
        }

    def add_log(self, message, level="INFO"):
        timestamp = datetime.now().strftime('%H:%M:%S')
        self.logs.append(f"[{timestamp}] {message}")
        if len(self.logs) > 50:
            self.logs = self.logs[-50:]
        if level == "ERROR":
            logger.error(message)
        else:
            logger.info(message)

    def calculate_net_pnl(self, entry_price, exit_price, qty):
        """Calculate net P&L after spread and fees"""
        position_value = entry_price * qty
        spread_cost = position_value * self.spread_percent
        fee_cost = position_value * self.fee_percent * 2
        total_costs = spread_cost + fee_cost
        gross_pnl = (exit_price - entry_price) * qty
        net_pnl = gross_pnl - total_costs
        return net_pnl, gross_pnl, total_costs

    def get_position_net_pnl(self, entry_price, current_price, qty):
        return self.calculate_net_pnl(entry_price, current_price, qty)[0]

    def get_position_net_percent(self, entry_price, current_price, qty):
        net_pnl, _, _ = self.calculate_net_pnl(entry_price, current_price, qty)
        position_value = entry_price * qty
        if position_value > 0:
            return (net_pnl / position_value) * 100
        return 0

    def get_target_sell_price(self, entry_price, qty):
        """Calculate the price needed to achieve target net profit"""
        position_value = entry_price * qty
        spread_cost = position_value * self.spread_percent
        fee_cost = position_value * self.fee_percent * 2
        total_costs = spread_cost + fee_cost

        target_net_profit = position_value * self.target_profit_percent
        target_gross_profit = target_net_profit + total_costs
        target_price = entry_price + (target_gross_profit / qty)
        return target_price

    def get_24h_data(self, symbol):
        """Get 24h price change, high, low, and current price"""
        try:
            end = datetime.now()
            start = end - timedelta(days=1)

            request = CryptoBarsRequest(
                symbol_or_symbols=symbol,
                timeframe=TimeFrame.Hour,
                start=start,
                end=end,
                limit=24
            )
            bars_data = self.data_client.get_crypto_bars(request)

            if not bars_data.data or symbol not in bars_data.data:
                return 0, 0, 0, 0

            df = bars_data.df
            if df.empty or len(df) < 2:
                return 0, 0, 0, 0

            current_price = float(df['close'].iloc[-1])
            high_24h = float(df['high'].max())
            low_24h = float(df['low'].min())
            oldest_close = float(df['close'].iloc[0])
            change_percent = ((current_price - oldest_close) / oldest_close) * 100

            return current_price, change_percent, high_24h, low_24h

        except Exception as e:
            self.add_log(f"Error getting 24h data for {symbol}: {e}", "ERROR")
            return 0, 0, 0, 0

    def execute_order(self, symbol, side, quantity=None):
        if quantity is None:
            quantity = self.symbol_quantities.get(symbol, 0)
        
        # Validate quantity before attempting order
        base = symbol.replace('/USD', '')
        min_qty = MINIMUM_QUANTITIES.get(base, 0)
        if quantity < min_qty:
            self.add_log(f"❌ Order failed: {quantity} {base} below minimum {min_qty}", "ERROR")
            return None
            
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

            if side == OrderSide.BUY:
                target_price = self.get_target_sell_price(fill_price, quantity)
                market_value = fill_price * quantity
                self.add_log(f"🟢 MANUAL BUY: {quantity} {display} at ${fill_price:.2f} | Mkt Val: ${market_value:.2f} | Target: ${target_price:.2f} (+{self.target_profit_percent*100:.1f}% net)")
            else:
                self.add_log(f"🔴 MANUAL SELL: {quantity} {display} at ${fill_price:.2f}")

            return order
        except Exception as e:
            self.add_log(f"Order failed for {symbol}: {e}", "ERROR")
            return None

    def manual_buy(self, symbol):
        display = symbol.replace('/USD', '')
        if not self.quantity_valid.get(symbol, False):
            base = symbol.replace('/USD', '')
            min_qty = MINIMUM_QUANTITIES.get(base, 0)
            self.add_log(f"❌ Cannot buy {display}: quantity {self.symbol_quantities.get(symbol, 0)} below minimum {min_qty}", "ERROR")
            return None
        self.add_log(f"🟢 MANUAL BUY requested for {display}")
        return self.execute_order(symbol, OrderSide.BUY)

    def manual_sell(self, symbol):
        display = symbol.replace('/USD', '')
        self.add_log(f"🔴 MANUAL CLOSE requested for {display}")

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

    def normalize_symbol(self, symbol: str, to_display: bool = False) -> str:
        if to_display:
            if '/' in symbol:
                return symbol
            if len(symbol) >= 6:
                base = symbol[:-3]
                quote = symbol[-3:]
                return f"{base}/{quote}"
            return symbol
        return symbol.replace('/', '')

    def get_position_info(self, symbol):
        try:
            positions = self.trading_client.get_all_positions()
            alpaca_symbol = self.normalize_symbol(symbol, to_display=False)
            for pos in positions:
                if pos.symbol == alpaca_symbol:
                    return {
                        'entry': float(pos.avg_entry_price),
                        'qty': abs(float(pos.qty)),
                        'current': float(pos.current_price)
                    }
            return None
        except Exception:
            return None

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

    def check_and_sell_at_target(self):
        """Check all positions and sell if target profit is reached"""
        try:
            positions = self.trading_client.get_all_positions()
            for pos in positions:
                display_symbol = self.normalize_symbol(pos.symbol, to_display=True)

                if display_symbol in self.symbols:
                    entry_price = float(pos.avg_entry_price)
                    current_price = float(pos.current_price)
                    qty = abs(float(pos.qty))

                    net_percent = self.get_position_net_percent(entry_price, current_price, qty)

                    if net_percent >= self.target_profit_percent * 100:
                        self.add_log(f"🎯 TARGET REACHED! {display_symbol}: {net_percent:.2f}% net profit (target: {self.target_profit_percent*100:.1f}%)")
                        self.add_log(f"🔴 AUTO SELLING {display_symbol} at ${current_price:.2f}")
                        self.close_position(display_symbol)

        except Exception as e:
            self.add_log(f"Error checking targets: {e}", "ERROR")

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
                        fill_price = entry_price
                        net_pnl, gross_pnl, costs = self.calculate_net_pnl(entry_price, fill_price, qty)

                    self.total_net_realized_pnl += net_pnl

                    current_date = datetime.now().date()
                    if current_date != self.day_date:
                        self.day_date = current_date
                        self.day_net_realized_pnl = 0
                    self.day_net_realized_pnl += net_pnl

                    self.add_log(f"✅ Closed {symbol}: {qty} @ ${fill_price:.2f} | Gross: ${gross_pnl:.2f} | Costs: ${costs:.2f} | NET: ${net_pnl:.2f} ({((net_pnl/(entry_price*qty))*100):.2f}%)")

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
        try:
            account = self.trading_client.get_account()
            current_equity = float(account.equity)

            total_net_pnl = current_equity - self.starting_balance

            net_unrealized_pnl = 0.0
            try:
                positions = self.trading_client.get_all_positions()
                for pos in positions:
                    if self.normalize_symbol(pos.symbol, to_display=True) in self.symbols:
                        entry = float(pos.avg_entry_price)
                        current = float(pos.current_price)
                        qty = abs(float(pos.qty))
                        net_pnl = self.get_position_net_pnl(entry, current, qty)
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
        except Exception:
            return {'buying_power': 0, 'portfolio_value': 0, 'net_realized_pnl': 0, 'net_unrealized_pnl': 0, 'total_net_pnl': 0, 'total_net_pnl_percent': 0, 'starting_balance': self.starting_balance}

    def get_all_positions(self):
        positions = []
        try:
            all_positions = self.trading_client.get_all_positions()
            for pos in all_positions:
                display_symbol = self.normalize_symbol(pos.symbol, to_display=True)
                if display_symbol in self.symbols:
                    entry = float(pos.avg_entry_price)
                    current = float(pos.current_price)
                    qty = abs(float(pos.qty))
                    net_pnl = self.get_position_net_pnl(entry, current, qty)
                    net_percent = self.get_position_net_percent(entry, current, qty)
                    market_value = entry * qty
                    target_percent = self.target_profit_percent * 100

                    positions.append({
                        'symbol': display_symbol,
                        'qty': qty,
                        'entry_price': entry,
                        'current_price': current,
                        'market_value': market_value,
                        'net_pnl': net_pnl,
                        'net_percent': net_percent,
                        'target_percent': target_percent
                    })
        except Exception as e:
            self.add_log(f"Error getting positions: {e}", "ERROR")
        return positions

    def get_all_symbols_data(self):
        """Get all symbols with current price, sorted by price highest to lowest"""
        symbols_data = []
        for symbol in self.symbols:
            current_price, change_24h, high_24h, low_24h = self.get_24h_data(symbol)
            base = symbol.replace('/USD', '')
            quantity = self.symbol_quantities.get(symbol, 0)
            min_qty = MINIMUM_QUANTITIES.get(base, 0)
            has_position = self.get_position_status(symbol)
            
            symbols_data.append({
                'symbol': base,
                'price': current_price,
                'change_24h': change_24h,
                'high_24h': high_24h,
                'low_24h': low_24h,
                'quantity': quantity,
                'min_quantity': min_qty,
                'quantity_valid': quantity >= min_qty,
                'has_position': has_position
            })
        # Sort by price descending (highest to lowest)
        symbols_data.sort(key=lambda x: x['price'], reverse=True)
        return symbols_data

    def run_strategy(self):
        global bot_instance
        bot_instance = self

        self.add_log(f"🚀 Starting MANUAL BUY/SELL + BOT SELL ONLY")
        self.add_log(f"💰 Starting Balance: ${self.starting_balance:,.2f}")
        self.add_log(f"📊 Monitoring {len(self.symbols)} symbols for auto-sell")
        self.add_log(f"🛡️ Spread: {self.spread_percent*100:.1f}% | Fee: {self.fee_percent*100:.2f}%")
        self.add_log(f"🎯 Target Net Profit: {self.target_profit_percent*100:.1f}%")
        self.add_log(f"🌐 Web dashboard: http://localhost:5001")

        while self.running:
            self.check_and_sell_at_target()
            time.sleep(5)

    def get_dashboard_data(self):
        account = self.get_account_status()
        positions = self.get_all_positions()
        symbols_data = self.get_all_symbols_data()
        return account, positions, symbols_data


# Flask routes
@app.route('/')
def dashboard():
    return render_template_string(DASHBOARD_TEMPLATE)

@app.route('/api/status')
def api_status():
    global bot_instance
    if not bot_instance:
        return jsonify({'logs': ['Bot not running'], 'current_settings': {}, 'bot_start_time': 0, 'bot_running': False})
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

@app.route('/health')
def health_check():
    global bot_instance
    if bot_instance and bot_instance.running:
        return jsonify({'status': 'healthy', 'uptime': time.time() - bot_instance.bot_start_time})
    else:
        return jsonify({'status': 'stopped'}), 503

@app.route('/update_setting', methods=['POST'])
def update_setting():
    global bot_instance
    if not bot_instance:
        return jsonify({'status': 'error', 'message': 'Bot not running'})
    data = request.get_json()
    setting = data.get('setting')
    value = data.get('value')
    if bot_instance.update_setting(setting, value):
        return jsonify({'status': 'ok'})
    return jsonify({'status': 'error'})

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
    return jsonify({'status': 'ok' if result else 'error'})

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
    app.run(host='0.0.0.0', port=5001, debug=False, use_reloader=False)

def main():
    print("\n" + "="*50)
    print("🤖 MANUAL BUY/SELL + BOT SELL ONLY")
    print("="*50)
    print("  ACTION: Manual BUY/SELL")
    print("  AUTO:   Bot sells when target net profit reached")
    print("  FEES:   Accounts for spread (0.3%) + fees (0.25%)")
    print("="*50)
    
    auto_start = '--auto' in sys.argv or '-y' in sys.argv

    try:
        bot = ManualSellBot()
        dashboard_thread = threading.Thread(target=run_dashboard, daemon=True)
        dashboard_thread.start()
        print("\n🌐 Web Dashboard: http://localhost:5001")
        print("   🟢 Click BUY/SELL manually")
        print("   🔴 Bot auto-sells at target net profit")
        print("   📊 Adjust target profit with slider")
        print("   📈 Symbols sorted by price (highest to lowest)")
        print("   ⚠️ Buy button disabled if quantity below minimum")
        print("")
        
        if auto_start:
            print("🚀 Auto-starting...")
            response = 'y'
        else:
            response = input("🚀 Start bot? (y/n): ").lower().strip()
        
        if response == 'y':
            print("\n⚠️  Bot running. Press Ctrl+C to stop.")
            print("📈 BUY/SELL manually | BOT sells automatically at target profit")
            bot.run_strategy()
        else:
            print("Bot stopped.")
    except Exception as e:
        print(f"\n❌ Error: {e}")

if __name__ == "__main__":
    main()

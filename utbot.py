import os
import time
import logging
import json
import threading
from datetime import datetime, timedelta
from flask import Flask, render_template_string, jsonify, request
import pandas as pd
import numpy as np
import requests
from dotenv import load_dotenv
from alpaca.trading.client import TradingClient
from alpaca.trading.requests import MarketOrderRequest
from alpaca.trading.enums import OrderSide, TimeInForce
from alpaca.data.historical import HistoricalDataClient
from alpaca.data.requests import StockBarsRequest
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
bot_instance = None  # Will be set when bot starts

# HTML Template for Dashboard
DASHBOARD_TEMPLATE = """
<!DOCTYPE html>
<html>
<head>
    <title>UT Bot Trading Dashboard</title>
    <meta http-equiv="refresh" content="5">
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body {
            font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
            background: linear-gradient(135deg, #1a1a2e 0%, #16213e 100%);
            color: #fff;
            padding: 20px;
            min-height: 100vh;
        }
        .container { max-width: 1400px; margin: 0 auto; }
        h1 { text-align: center; margin-bottom: 30px; color: #00d4ff; }
        .grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(300px, 1fr));
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
        .stat {
            font-size: 2em;
            font-weight: bold;
            margin: 10px 0;
        }
        .stat-label { color: #aaa; font-size: 0.9em; }
        .positive { color: #00ff88; }
        .negative { color: #ff4444; }
        .neutral { color: #ffaa00; }
        table {
            width: 100%;
            border-collapse: collapse;
            margin-top: 10px;
        }
        th, td {
            padding: 8px;
            text-align: left;
            border-bottom: 1px solid rgba(255,255,255,0.1);
        }
        th { color: #00d4ff; }
        .status-badge {
            display: inline-block;
            padding: 4px 12px;
            border-radius: 20px;
            font-size: 0.8em;
            font-weight: bold;
        }
        .status-long { background: #00ff88; color: #000; }
        .status-short { background: #ff4444; color: #fff; }
        .status-flat { background: #888; color: #fff; }
        .signal-buy { background: #00ff88; color: #000; }
        .signal-sell { background: #ff4444; color: #fff; }
        button {
            background: #00d4ff;
            color: #000;
            border: none;
            padding: 10px 20px;
            border-radius: 5px;
            cursor: pointer;
            font-weight: bold;
            margin: 5px;
        }
        button:hover { opacity: 0.8; }
        button.danger { background: #ff4444; color: #fff; }
        .logs {
            height: 300px;
            overflow-y: scroll;
            font-family: monospace;
            font-size: 0.8em;
            background: rgba(0,0,0,0.3);
            border-radius: 10px;
            padding: 10px;
        }
        .log-entry { 
            border-bottom: 1px solid rgba(255,255,255,0.05); 
            padding: 4px 0;
        }
    </style>
</head>
<body>
    <div class="container">
        <h1>🤖 UT Bot Alerts Trading Dashboard</h1>
        
        <div class="grid">
            <div class="card">
                <h3>📊 Account Status</h3>
                <div class="stat-label">Buying Power</div>
                <div class="stat ${{ 'positive' if account.buying_power > 0 else '' }}">${{ "%.2f"|format(account.buying_power) }}</div>
                <div class="stat-label">Portfolio Value</div>
                <div class="stat">${{ "%.2f"|format(account.portfolio_value) }}</div>
                <div class="stat-label">Today's P&L</div>
                <div class="stat ${{ 'positive' if account.today_pnl >= 0 else 'negative' }}">${{ "%.2f"|format(account.today_pnl) }}</div>
            </div>
            
            <div class="card">
                <h3>📈 Current Position</h3>
                <div class="stat">
                    <span class="status-badge status-{{ position.status }}">{{ position.status|upper }}</span>
                </div>
                <div class="stat-label">Symbol</div>
                <div>{{ position.symbol }}</div>
                <div class="stat-label">Quantity</div>
                <div>{{ position.quantity }}</div>
                <div class="stat-label">Entry Price</div>
                <div>${{ "%.2f"|format(position.entry_price) if position.entry_price else 'N/A' }}</div>
                <div class="stat-label">Current P&L</div>
                <div class="${{ 'positive' if position.current_pnl >= 0 else 'negative' }}">${{ "%.2f"|format(position.current_pnl) }}</div>
            </div>
            
            <div class="card">
                <h3>🎯 Strategy Signals</h3>
                <div class="stat-label">Latest Signal</div>
                <div>
                    <span class="status-badge signal-{{ signal.type }}">{{ signal.type|upper if signal.type else 'NONE' }}</span>
                </div>
                <div class="stat-label">Current Price</div>
                <div>${{ "%.2f"|format(signal.price) }}</div>
                <div class="stat-label">Trailing Stop</div>
                <div>${{ "%.2f"|format(signal.stop) }}</div>
                <div class="stat-label">Timeframe</div>
                <div>{{ signal.timeframe }}</div>
            </div>
            
            <div class="card">
                <h3>⚙️ Controls</h3>
                <button onclick="fetch('/close_position', {method: 'POST'})">Close Position</button>
                <button onclick="fetch('/refresh', {method: 'POST'})">Refresh Data</button>
                <button class="danger" onclick="fetch('/stop', {method: 'POST'})">Stop Bot</button>
                <div style="margin-top: 15px;">
                    <div class="stat-label">Bot Status</div>
                    <div class="status-badge" style="background: {{ '#00ff88' if bot_running else '#ff4444' }}">{{ 'RUNNING' if bot_running else 'STOPPED' }}</div>
                </div>
            </div>
        </div>
        
        <div class="grid">
            <div class="card">
                <h3>📋 Recent Trades</h3>
                <table>
                    <thead>
                        <tr><th>Time</th><th>Type</th><th>Price</th><th>PnL</th></tr>
                    </thead>
                    <tbody>
                        {% for trade in trades %}
                        <tr>
                            <td>{{ trade.time }}</td>
                            <td class="${{ 'positive' if 'BUY' in trade.type or 'LONG' in trade.type else 'negative' }}">{{ trade.type }}</td>
                            <td>${{ "%.2f"|format(trade.price) }}</td>
                            <td class="${{ 'positive' if trade.pnl and trade.pnl > 0 else 'negative' if trade.pnl and trade.pnl < 0 else '' }}">${{ "%.2f"|format(trade.pnl) if trade.pnl else 'N/A' }}</td>
                        </tr>
                        {% endfor %}
                    </tbody>
                </table>
            </div>
            
            <div class="card">
                <h3>📝 Live Logs</h3>
                <div class="logs" id="logs">
                    {% for log in logs %}
                    <div class="log-entry">{{ log }}</div>
                    {% endfor %}
                </div>
            </div>
        </div>
    </div>
    
    <script>
        setInterval(function() {
            fetch('/api/status')
                .then(response => response.json())
                .then(data => {
                    if (data.logs) {
                        let logsDiv = document.getElementById('logs');
                        logsDiv.innerHTML = data.logs.map(l => `<div class="log-entry">${l}</div>`).join('');
                        logsDiv.scrollTop = logsDiv.scrollHeight;
                    }
                });
        }, 3000);
    </script>
</body>
</html>
"""


class TelegramNotifier:
    """Telegram alert system"""
    
    def __init__(self, bot_token=None, chat_id=None):
        self.bot_token = bot_token or os.getenv('TELEGRAM_BOT_TOKEN')
        self.chat_id = chat_id or os.getenv('TELEGRAM_CHAT_ID')
        self.enabled = bool(self.bot_token and self.chat_id)
        
        if self.enabled:
            logger.info("Telegram notifications enabled")
        else:
            logger.warning("Telegram notifications disabled - missing credentials")
    
    def send_message(self, message):
        """Send message via Telegram"""
        if not self.enabled:
            return False
        
        try:
            url = f"https://api.telegram.org/bot{self.bot_token}/sendMessage"
            payload = {
                'chat_id': self.chat_id,
                'text': message,
                'parse_mode': 'HTML'
            }
            response = requests.post(url, json=payload, timeout=5)
            if response.status_code == 200:
                logger.info(f"Telegram alert sent: {message[:50]}...")
                return True
            else:
                logger.error(f"Telegram error: {response.text}")
                return False
        except Exception as e:
            logger.error(f"Telegram send failed: {e}")
            return False
    
    def send_trade_alert(self, action, price, pnl=None, reason=None):
        """Send formatted trade alert"""
        emoji = "🟢" if "BUY" in action or "LONG" in action else "🔴"
        message = f"""
{emoji} <b>TRADE ALERT</b> {emoji}

<b>Action:</b> {action}
<b>Price:</b> ${price:.2f}
<b>Time:</b> {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
"""
        if pnl is not None:
            pnl_emoji = "✅" if pnl >= 0 else "❌"
            message += f"<b>PnL:</b> {pnl_emoji} ${pnl:.2f}\n"
        if reason:
            message += f"<b>Reason:</b> {reason}\n"
        
        self.send_message(message)
    
    def send_daily_summary(self, trades, total_pnl, win_rate):
        """Send daily performance summary"""
        emoji = "🎉" if total_pnl > 0 else "😔"
        message = f"""
📊 <b>DAILY TRADING SUMMARY</b> 📊

{emoji} <b>Total PnL:</b> ${total_pnl:.2f}
<b>Trades:</b> {len(trades)}
<b>Win Rate:</b> {win_rate:.1f}%
<b>Date:</b> {datetime.now().strftime('%Y-%m-%d')}
"""
        self.send_message(message)
    
    def send_signal_alert(self, signal_type, price, stop, timeframe):
        """Send strategy signal alert"""
        emoji = "📈" if signal_type == "BUY" else "📉"
        message = f"""
{emoji} <b>STRATEGY SIGNAL</b> {emoji}

<b>Signal:</b> {signal_type}
<b>Price:</b> ${price:.2f}
<b>Stop:</b> ${stop:.2f}
<b>Timeframe:</b> {timeframe}
<b>Time:</b> {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
"""
        self.send_message(message)


class UTBotAlerts:
    def __init__(self, symbol="SPY", a=1, atr_period=10, 
                 use_heikin_ashi=False, timeframe="15Min", 
                 quantity=1, paper_trading=True):
        """
        Initialize UT Bot Strategy with Telegram and Web Dashboard
        """
        self.symbol = symbol
        self.a = a
        self.atr_period = atr_period
        self.use_heikin_ashi = use_heikin_ashi
        self.quantity = quantity
        self.paper_trading = paper_trading
        self.running = True
        
        # Timeframe mapping
        self.timeframe_map = {
            "1Min": TimeFrame.Minute,
            "5Min": TimeFrame.Minute(5),
            "15Min": TimeFrame.Minute(15),
            "30Min": TimeFrame.Minute(30),
            "1H": TimeFrame.Hour,
            "2H": TimeFrame.Hour(2),
            "4H": TimeFrame.Hour(4),
            "1D": TimeFrame.Day
        }
        
        self.interval_map = {
            "1Min": 60, "5Min": 300, "15Min": 900, "30Min": 1800,
            "1H": 3600, "2H": 7200, "4H": 14400, "1D": 86400
        }
        
        self.timeframe_str = timeframe
        self.timeframe = self.timeframe_map.get(timeframe, TimeFrame.Minute(15))
        self.check_interval = self.interval_map.get(timeframe, 900)
        self.bars_to_fetch = 200 if timeframe in ["1D", "4H"] else 100
        
        # Initialize Telegram
        self.telegram = TelegramNotifier()
        
        # Initialize Alpaca clients
        if paper_trading:
            self.trading_client = TradingClient(
                api_key=os.getenv('APCA_API_KEY_ID'),
                secret_key=os.getenv('APCA_API_SECRET_KEY'),
                paper=True
            )
        else:
            self.trading_client = TradingClient(
                api_key=os.getenv('APCA_API_KEY_ID'),
                secret_key=os.getenv('APCA_API_SECRET_KEY')
            )
        
        self.data_client = HistoricalDataClient(
            api_key=os.getenv('APCA_API_KEY_ID'),
            secret_key=os.getenv('APCA_API_SECRET_KEY')
        )
        
        # Tracking variables
        self.current_position = 0
        self.last_signal = None
        self.trades_history = []
        self.logs = []
        self.daily_stats = {'trades': 0, 'pnl': 0, 'wins': 0}
        
        # Send startup message
        self.telegram.send_message(f"""
🤖 <b>UT Bot Started</b>

<b>Symbol:</b> {symbol}
<b>Timeframe:</b> {timeframe}
<b>Sensitivity:</b> {a}
<b>ATR Period:</b> {atr_period}
<b>Mode:</b> {'PAPER' if paper_trading else 'LIVE'}
        """)
        
        logger.info(f"Initialized UT Bot with: {timeframe} timeframe")
    
    def add_log(self, message, level="INFO"):
        """Add log message to memory for dashboard"""
        timestamp = datetime.now().strftime('%H:%M:%S')
        log_entry = f"[{timestamp}] {message}"
        self.logs.append(log_entry)
        if len(self.logs) > 100:
            self.logs = self.logs[-100:]
        
        if level == "ERROR":
            logger.error(message)
        else:
            logger.info(message)
    
    def get_heikin_ashi(self, df):
        """Convert regular candles to Heikin Ashi"""
        ha_df = pd.DataFrame(index=df.index)
        ha_df['close'] = (df['open'] + df['high'] + df['low'] + df['close']) / 4
        ha_df['open'] = (df['open'].shift(1) + df['close'].shift(1)) / 2
        ha_df['open'].iloc[0] = (df['open'].iloc[0] + df['close'].iloc[0]) / 2
        ha_df['high'] = df[['high', 'open', 'close']].max(axis=1)
        ha_df['low'] = df[['low', 'open', 'close']].min(axis=1)
        return ha_df
    
    def calculate_atr(self, df, period=14):
        """Calculate Average True Range"""
        high = df['high']
        low = df['low']
        close = df['close']
        
        tr1 = high - low
        tr2 = abs(high - close.shift())
        tr3 = abs(low - close.shift())
        
        tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
        atr = tr.rolling(window=period).mean()
        
        return atr
    
    def calculate_signals(self, df):
        """Calculate UT Bot trading signals"""
        df = df.copy()
        
        if self.use_heikin_ashi:
            ha = self.get_heikin_ashi(df)
            src = ha['close']
        else:
            src = df['close']
        
        atr = self.calculate_atr(df, self.atr_period)
        nLoss = self.a * atr
        
        xATRTrailingStop = pd.Series(index=df.index, dtype=float)
        pos = pd.Series(index=df.index, dtype=int)
        
        for i in range(len(df)):
            if i == 0:
                xATRTrailingStop.iloc[i] = src.iloc[i] - nLoss.iloc[i]
                pos.iloc[i] = 0
                continue
            
            prev_stop = xATRTrailingStop.iloc[i-1]
            prev_pos = pos.iloc[i-1]
            current_src = src.iloc[i]
            prev_src = src.iloc[i-1]
            current_nLoss = nLoss.iloc[i]
            
            if current_src > prev_stop and prev_src > prev_stop:
                xATRTrailingStop.iloc[i] = max(prev_stop, current_src - current_nLoss)
            elif current_src < prev_stop and prev_src < prev_stop:
                xATRTrailingStop.iloc[i] = min(prev_stop, current_src + current_nLoss)
            elif current_src > prev_stop:
                xATRTrailingStop.iloc[i] = current_src - current_nLoss
            else:
                xATRTrailingStop.iloc[i] = current_src + current_nLoss
            
            if prev_src < prev_stop and current_src > prev_stop:
                pos.iloc[i] = 1
            elif prev_src > prev_stop and current_src < prev_stop:
                pos.iloc[i] = -1
            else:
                pos.iloc[i] = prev_pos
        
        ema = src.ewm(span=1, adjust=False).mean()
        above = (ema > xATRTrailingStop) & (ema.shift(1) <= xATRTrailingStop.shift(1))
        below = (ema < xATRTrailingStop) & (ema.shift(1) >= xATRTrailingStop.shift(1))
        
        df['signal'] = 0
        buy_condition = (src > xATRTrailingStop) & above
        sell_condition = (src < xATRTrailingStop) & below
        df.loc[buy_condition, 'signal'] = 1
        df.loc[sell_condition, 'signal'] = -1
        df['trailing_stop'] = xATRTrailingStop
        df['src'] = src
        
        return df
    
    def get_historical_data(self, bars=None):
        """Fetch historical bar data"""
        if bars is None:
            bars = self.bars_to_fetch
            
        end = datetime.now()
        
        if self.timeframe_str == "1D":
            start = end - timedelta(days=bars * 2)
        elif self.timeframe_str in ["4H", "2H"]:
            start = end - timedelta(days=bars)
        elif self.timeframe_str == "1H":
            start = end - timedelta(hours=bars * 2)
        else:
            minutes_per_bar = {"1Min": 1, "5Min": 5, "15Min": 15, "30Min": 30}.get(self.timeframe_str, 1)
            start = end - timedelta(minutes=bars * minutes_per_bar * 2)
        
        request = StockBarsRequest(
            symbol_or_symbols=self.symbol,
            timeframe=self.timeframe,
            start=start,
            end=end,
            limit=bars + self.atr_period + 10
        )
        
        try:
            bars_data = self.data_client.get_stock_bars(request)
            if not bars_data.data or self.symbol not in bars_data.data:
                return None
                
            df = bars_data.df
            if df.empty or len(df) < 20:
                return None
            
            df = df.reset_index()
            df = df.rename(columns={'timestamp': 'datetime', 'open': 'open', 
                                     'high': 'high', 'low': 'low', 'close': 'close'})
            df.set_index('datetime', inplace=True)
            
            return df
        except Exception as e:
            self.add_log(f"Error fetching data: {e}", "ERROR")
            return None
    
    def execute_order(self, side, quantity=None):
        """Execute a market order with Telegram alert"""
        if quantity is None:
            quantity = self.quantity
            
        try:
            order_data = MarketOrderRequest(
                symbol=self.symbol,
                qty=quantity,
                side=side,
                time_in_force=TimeInForce.DAY
            )
  
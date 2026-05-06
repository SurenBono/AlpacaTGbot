import os
import time
import logging
import threading
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

# HTML Template for Dashboard
DASHBOARD_TEMPLATE = """
<!DOCTYPE html>
<html>
<head>
    <title>UT Bot Multi-Crypto Dashboard</title>
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
            grid-template-columns: repeat(auto-fit, minmax(350px, 1fr));
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
            padding: 10px 20px;
            border-radius: 5px;
            cursor: pointer;
            font-weight: bold;
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
        .symbol-table {
            width: 100%;
            border-collapse: collapse;
        }
        .symbol-table th, .symbol-table td {
            padding: 8px;
            text-align: left;
            border-bottom: 1px solid rgba(255,255,255,0.1);
        }
        .symbol-table th { color: #00d4ff; }
    </style>
</head>
<body>
    <div class="container">
        <h1>🤖 UT Bot Multi-Crypto Dashboard</h1>
        
        <div class="grid">
            <div class="card">
                <h3>📊 Account Status</h3>
                <div class="stat-label">Buying Power (USD)</div>
                <div class="stat">${{ "%.2f"|format(account.buying_power) }}</div>
                <div class="stat-label">Portfolio Value</div>
                <div class="stat">${{ "%.2f"|format(account.portfolio_value) }}</div>
                <div class="stat-label">Stop Loss</div>
                <div class="stat">{{ "%.1f"|format(stop_loss * 100) }}%</div>
            </div>
            
            <div class="card">
                <h3>📈 Active Positions</h3>
                <table class="symbol-table">
                    <thead>
                        <tr><th>Symbol</th><th>Qty</th><th>Entry</th><th>Current</th><th>P&L</th><th>Stop Loss</th></tr>
                    </thead>
                    <tbody>
                        {% for pos in positions %}
                        <tr>
                            <td>{{ pos.symbol }}</td>
                            <td>{{ "%.6f"|format(pos.qty) }}</td>
                            <td>${{ "%.2f"|format(pos.entry_price) }}</td>
                            <td>${{ "%.2f"|format(pos.current_price) }}</td>
                            <td class="{{ 'positive' if pos.pnl >= 0 else 'negative' }}">${{ "%.2f"|format(pos.pnl) }}</td>
                            <td class="negative">${{ "%.2f"|format(pos.stop_loss_price) }}</td>
                        </tr>
                        {% endfor %}
                    </tbody>
                </table>
            </div>
            
            <div class="card">
                <h3>⚙️ Controls</h3>
                <button onclick="fetch('/close_all_positions', {method: 'POST'})">Close All Positions</button>
                <button onclick="fetch('/stop', {method: 'POST'})" class="danger">Stop Bot</button>
                <div style="margin-top: 15px;">
                    <div class="stat-label">Bot Status</div>
                    <div class="status-badge" style="background: {{ '#00ff88' if bot_running else '#ff4444' }}">{{ 'RUNNING' if bot_running else 'STOPPED' }}</div>
                </div>
            </div>
        </div>
        
        <div class="card">
            <h3>🎯 Symbol Signals</h3>
            <table class="symbol-table">
                <thead>
                    <tr><th>Symbol</th><th>Price</th><th>Trailing Stop</th><th>Signal</th><th>Position</th></tr>
                </thead>
                <tbody>
                    {% for sym in symbols %}
                    <tr>
                        <td>{{ sym.symbol }}</td>
                        <td>${{ "%.2f"|format(sym.price) }}</td>
                        <td>${{ "%.2f"|format(sym.stop) }}</td>
                        <td><span class="status-badge signal-{{ sym.signal_type }}">{{ sym.signal_type|upper if sym.signal_type else 'NONE' }}</span></td>
                        <td><span class="status-badge status-{{ sym.position_status }}">{{ sym.position_status|upper }}</span></td>
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
                    location.reload();
                });
        }, 10000);
    </script>
</body>
</html>
"""


class CryptoTradingBot:
    """Multi-symbol UT Bot for Crypto trading with Stop Loss & Profit Protection"""
    
    def __init__(self):
        """Initialize bot with parameters from .env file"""
        
        # Load symbols from .env (comma-separated list)
        symbols_str = os.getenv('SYMBOLS', 'ETH/USD')
        self.symbols = [s.strip() for s in symbols_str.split(',')]
        
        # Load common parameters
        self.quantity = float(os.getenv('QUANTITY', '0.01'))
        self.timeframe_str = os.getenv('TIMEFRAME', '15Min')
        self.a = float(os.getenv('SENSITIVITY', '1.0'))
        self.atr_period = int(os.getenv('ATR_PERIOD', '10'))
        self.use_heikin_ashi = os.getenv('HEIKIN_ASHI', 'True').lower() == 'true'
        self.paper_trading = os.getenv('PAPER_TRADING', 'True').lower() == 'true'
        self.running = True
        
        # Risk Management Parameters
        self.stop_loss_percent = float(os.getenv('STOP_LOSS_PERCENT', '0.03'))
        self.min_profit_usd = float(os.getenv('MIN_PROFIT_USD', '0.50'))
        self.min_profit_percent = float(os.getenv('MIN_PROFIT_PERCENT', '0.005'))
        
        # Individual symbol quantities
        self.symbol_quantities = {}
        for symbol in self.symbols:
            base = symbol.replace('/USD', '').replace('USDT', '')
            qty_env = os.getenv(f'QUANTITY_{base}', str(self.quantity))
            self.symbol_quantities[symbol] = float(qty_env)
        
        # Parse timeframe
        self.timeframe_minutes = self._parse_timeframe_to_minutes(self.timeframe_str)
        
        # Interval mapping
        self.interval_map = {
            "1Min": 60, "5Min": 300, "15Min": 900, "30Min": 1800,
            "1H": 3600, "2H": 7200, "4H": 14400, "1D": 86400
        }
        self.check_interval = self.interval_map.get(self.timeframe_str, 900)
        self.bars_to_fetch = 200 if self.timeframe_str in ["1D", "4H"] else 100
        
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
        self.last_signals = {symbol: None for symbol in self.symbols}
        self.trades_history = []
        self.logs = []
        
        # Log startup configuration
        logger.info("="*50)
        logger.info("UT Bot Multi-Crypto Started")
        logger.info("="*50)
        logger.info(f"Symbols: {', '.join(self.symbols)}")
        for sym, qty in self.symbol_quantities.items():
            logger.info(f"  {sym}: {qty} {sym.replace('/USD', '')}")
        logger.info(f"Timeframe: {self.timeframe_str}")
        logger.info(f"Sensitivity: {self.a}")
        logger.info(f"ATR Period: {self.atr_period}")
        logger.info(f"Heikin Ashi: {self.use_heikin_ashi}")
        logger.info(f"Mode: {'PAPER' if self.paper_trading else 'LIVE'}")
        logger.info("-"*30)
        logger.info("RISK MANAGEMENT:")
        logger.info(f"  Stop Loss: {self.stop_loss_percent*100:.1f}%")
        logger.info(f"  Min Profit: ${self.min_profit_usd} or {self.min_profit_percent*100:.1f}%")
        logger.info("="*50)
    
    def _parse_timeframe_to_minutes(self, timeframe_str):
        timeframe_map = {
            "1Min": 1, "5Min": 5, "15Min": 15, "30Min": 30,
            "1H": 60, "2H": 120, "4H": 240, "1D": 1440
        }
        return timeframe_map.get(timeframe_str, 15)
    
    def normalize_symbol(self, symbol: str, to_display: bool = False) -> str:
        """
        Convert between Alpaca format (BTCUSD) and display format (BTC/USD)
        to_display=True: BTCUSD → BTC/USD
        to_display=False: BTC/USD → BTCUSD
        """
        if to_display:
            # Convert Alpaca format (BTCUSD) to display format (BTC/USD)
            if '/' in symbol:
                return symbol
            if len(symbol) >= 6:
                base = symbol[:-3]
                quote = symbol[-3:]
                return f"{base}/{quote}"
            return symbol
        else:
            # Convert display format (BTC/USD) to Alpaca format (BTCUSD)
            return symbol.replace('/', '')
    
    def add_log(self, message, level="INFO"):
        timestamp = datetime.now().strftime('%H:%M:%S')
        log_entry = f"[{timestamp}] {message}"
        self.logs.append(log_entry)
        if len(self.logs) > 100:
            self.logs = self.logs[-100:]
        
        if level == "ERROR":
            logger.error(message)
        else:
            logger.info(message)
    
    def resume_existing_positions(self):
        """Check for and log any existing positions on startup"""
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
                        self.last_signals[display_symbol] = 1
                self.add_log("="*40)
                self.add_log("✅ Bot will manage these positions on next signals")
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
                pos.iloc[i] = pos.iloc[i-1]
        
        ema = src.ewm(span=1, adjust=False).mean()
        above = (ema > xATRTrailingStop) & (ema.shift(1) <= xATRTrailingStop.shift(1))
        below = (ema < xATRTrailingStop) & (ema.shift(1) >= xATRTrailingStop.shift(1))
        
        df['signal'] = 0
        buy_condition = (src > xATRTrailingStop) & above
        sell_condition = (src < xATRTrailingStop) & below
        df.loc[buy_condition, 'signal'] = 1
        df.loc[sell_condition, 'signal'] = -1
        df['trailing_stop'] = xATRTrailingStop
        
        return df
    
    def get_historical_data(self, symbol, bars=None):
        if bars is None:
            bars = self.bars_to_fetch
            
        end = datetime.now()
        total_minutes = self.timeframe_minutes * (bars + self.atr_period + 20)
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
            limit=bars + self.atr_period + 10
        )
        
        try:
            bars_data = self.data_client.get_crypto_bars(request)
            if not bars_data.data or symbol not in bars_data.data:
                return None
            df = bars_data.df
            if df.empty or len(df) < 20:
                return None
            df = df.reset_index()
            df = df.rename(columns={'timestamp': 'datetime', 'open': 'open', 
                                     'high': 'high', 'low': 'low', 'close': 'close'})
            df.set_index('datetime', inplace=True)
            df = df.sort_index()
            return df
        except Exception as e:
            self.add_log(f"Error fetching {symbol} data: {e}", "ERROR")
            return None
    
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
        """Get entry price and quantity for a symbol"""
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
        except Exception as e:
            self.add_log(f"Error getting position info: {e}", "ERROR")
            return None
    
    def is_profitable_enough(self, symbol, entry_price, current_price, qty):
        """Check if profit meets minimum threshold"""
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
        """Check if stop loss is triggered"""
        loss_percent = (entry_price - current_price) / entry_price
        
        if loss_percent >= self.stop_loss_percent:
            loss_amount = (entry_price - current_price) * qty
            self.add_log(f"🛑 {symbol} STOP LOSS triggered! Loss: {loss_percent*100:.1f}% (${loss_amount:.2f})")
            return True
        return False
    
    def close_position(self, symbol):
        """Close position for a specific symbol"""
        try:
            positions = self.trading_client.get_all_positions()
            alpaca_symbol = self.normalize_symbol(symbol, to_display=False)
            for pos in positions:
                if pos.symbol == alpaca_symbol:
                    qty = abs(float(pos.qty))
                    entry_price = float(pos.avg_entry_price)
                    
                    df = self.get_historical_data(symbol, bars=2)
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
            return {
                'buying_power': float(account.buying_power),
                'portfolio_value': float(account.portfolio_value)
            }
        except Exception:
            return {'buying_power': 0, 'portfolio_value': 0}
    
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
        except Exception as e:
            self.add_log(f"Error getting positions: {e}", "ERROR")
        return positions
    
    def get_position_status(self, symbol):
        """Check if a symbol has an open position"""
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
        """Process a single symbol with stop loss and profit protection"""
        try:
            df = self.get_historical_data(symbol)
            if df is None or len(df) < self.atr_period + 10:
                return
            
            signals_df = self.calculate_signals(df)
            latest_signal = signals_df.iloc[-1]['signal']
            latest_close = signals_df.iloc[-1]['close']
            latest_stop = signals_df.iloc[-1]['trailing_stop']
            display = symbol.replace('/USD', '')
            
            # Get position info
            has_position = self.get_position_status(symbol)
            position_info = self.get_position_info(symbol) if has_position else None
            
            # Check STOP LOSS first (priority)
            if has_position and position_info:
                entry_price = position_info['entry']
                qty = position_info['qty']
                
                if self.check_stop_loss(display, entry_price, latest_close, qty):
                    self.close_position(symbol)
                    return
            
            self.add_log(f"{display}: ${latest_close:.2f} | Trail: ${latest_stop:.2f} | Signal: {latest_signal}")
            
            if latest_signal != 0 and latest_signal != self.last_signals.get(symbol):
                signal_type = "BUY" if latest_signal == 1 else "SELL"
                self.add_log(f"🎯 {display} SIGNAL: {signal_type} at ${latest_close:.2f}")
                self.last_signals[symbol] = latest_signal
            
            # Execute signals
            if latest_signal == 1:
                self.add_log(f"🔵 {display} BUY SIGNAL - Going LONG")
                if has_position:
                    self.add_log(f"Closing existing {display} position before opening new LONG")
                    self.close_position(symbol)
                    time.sleep(2)
                self.execute_order(symbol, OrderSide.BUY)
                
            elif latest_signal == -1:
                if has_position and position_info:
                    if self.is_profitable_enough(display, position_info['entry'], latest_close, position_info['qty']):
                        self.add_log(f"🔴 {display} SELL SIGNAL - Closing position")
                        self.close_position(symbol)
                    else:
                        self.add_log(f"🔴 {display} SELL SIGNAL - Holding (profit below threshold)")
                elif has_position:
                    self.add_log(f"🔴 {display} SELL SIGNAL - Closing position")
                    self.close_position(symbol)
                else:
                    self.add_log(f"🔴 {display} SELL SIGNAL received but no position to close")
                    
        except Exception as e:
            self.add_log(f"Error processing {symbol}: {e}", "ERROR")
    
    def run_strategy(self):
        global bot_instance
        bot_instance = self
        
        self.add_log(f"🚀 Starting Multi-Crypto UT Bot")
        self.add_log(f"📊 Monitoring: {', '.join(self.symbols)}")
        self.add_log(f"🛡️ Stop Loss: {self.stop_loss_percent*100:.1f}%")
        self.add_log(f"💰 Min Profit: ${self.min_profit_usd} or {self.min_profit_percent*100:.1f}%")
        
        # Check for existing positions
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
                df = self.get_historical_data(symbol, bars=5)
                if df is not None:
                    signals = self.calculate_signals(df)
                    has_position = self.get_position_status(symbol)
                    latest_signal = signals.iloc[-1]['signal']
                    symbols_data.append({
                        'symbol': symbol.replace('/USD', ''),
                        'price': float(signals.iloc[-1]['close']),
                        'stop': float(signals.iloc[-1]['trailing_stop']),
                        'signal_type': {1: 'BUY', -1: 'SELL'}.get(latest_signal, None),
                        'position_status': 'long' if has_position else 'flat'
                    })
            except Exception:
                symbols_data.append({
                    'symbol': symbol.replace('/USD', ''),
                    'price': 0, 'stop': 0, 'signal_type': None, 'position_status': 'unknown'
                })
        return account, positions, symbols_data


# Flask routes
@app.route('/')
def dashboard():
    global bot_instance
    if not bot_instance or not bot_instance.running:
        return render_template_string("<h1>🤖 Bot is starting...</h1><p>Check terminal for live updates.</p>"), 200
    account, positions, symbols_data = bot_instance.get_dashboard_data()
    return render_template_string(DASHBOARD_TEMPLATE,
        account=account, 
        positions=positions, 
        symbols=symbols_data,
        logs=bot_instance.logs[-50:], 
        bot_running=bot_instance.running,
        stop_loss=bot_instance.stop_loss_percent
    )

@app.route('/api/status')
def api_status():
    global bot_instance
    if not bot_instance:
        return jsonify({'logs': []})
    return jsonify({'logs': bot_instance.logs[-50:]})

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
    print("🤖 UT Bot Multi-Crypto - Fixed Symbol Detection")
    print("="*50)
    print("Loading configuration from .env file...")
    
    try:
        bot = CryptoTradingBot()
        dashboard_thread = threading.Thread(target=run_dashboard, daemon=True)
        dashboard_thread.start()
        print("\n🌐 Web Dashboard: http://localhost:5000")
        response = input("\n🚀 Start paper trading? (yes/no): ").lower().strip()
        if response == 'y':
            print("\n⚠️  Crypto trading runs 24/7. Press Ctrl+C to stop.")
            bot.run_strategy()
        else:
            print("Bot stopped.")
    except Exception as e:
        print(f"\n❌ Error: {e}")


if __name__ == "__main__":
    main()

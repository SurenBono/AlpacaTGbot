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
    <title>UT Bot Crypto Dashboard</title>
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
        .container { max-width: 1200px; margin: 0 auto; }
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
        <h1>🤖 UT Bot Crypto Dashboard</h1>
        
        <div class="grid">
            <div class="card">
                <h3>📊 Account Status</h3>
                <div class="stat-label">Buying Power (USDT)</div>
                <div class="stat">${{ "%.2f"|format(account.buying_power) }}</div>
                <div class="stat-label">Portfolio Value</div>
                <div class="stat">${{ "%.2f"|format(account.portfolio_value) }}</div>
            </div>
            
            <div class="card">
                <h3>📈 Current Position</h3>
                <div class="stat">
                    <span class="status-badge status-{{ position.status }}">{{ position.status|upper }}</span>
                </div>
                <div class="stat-label">Quantity (ETH)</div>
                <div>{{ "%.4f"|format(position.quantity) }}</div>
                <div class="stat-label">Entry Price</div>
                <div>${{ "%.2f"|format(position.entry_price) if position.entry_price else 'N/A' }}</div>
                <div class="stat-label">Current P&L</div>
                <div class="{{ 'positive' if position.current_pnl >= 0 else 'negative' }}">${{ "%.2f"|format(position.current_pnl) }}</div>
            </div>
            
            <div class="card">
                <h3>🎯 Latest Signal</h3>
                <div class="stat">
                    <span class="status-badge signal-{{ signal.type }}">{{ signal.type|upper if signal.type else 'NONE' }}</span>
                </div>
                <div class="stat-label">Price</div>
                <div>${{ "%.2f"|format(signal.price) }}</div>
                <div class="stat-label">Trailing Stop</div>
                <div>${{ "%.2f"|format(signal.stop) }}</div>
                <div class="stat-label">Timeframe</div>
                <div>{{ signal.timeframe }}</div>
            </div>
            
            <div class="card">
                <h3>⚙️ Controls</h3>
                <button onclick="fetch('/close_position', {method: 'POST'})">Close Position</button>
                <button onclick="fetch('/stop', {method: 'POST'})" class="danger">Stop Bot</button>
                <div style="margin-top: 15px;">
                    <div class="stat-label">Bot Status</div>
                    <div class="status-badge" style="background: {{ '#00ff88' if bot_running else '#ff4444' }}">{{ 'RUNNING' if bot_running else 'STOPPED' }}</div>
                </div>
            </div>
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
                });
        }, 3000);
    </script>
</body>
</html>
"""


class UTBotAlerts:
    def __init__(self):
        """Initialize UT Bot with parameters from .env file"""
        
        # Load all parameters from .env
        self.symbol = os.getenv('SYMBOL', 'ETH/USDT')
        self.quantity = float(os.getenv('QUANTITY', '0.001'))
        self.timeframe_str = os.getenv('TIMEFRAME', '15Min')
        self.a = float(os.getenv('SENSITIVITY', '1.0'))
        self.atr_period = int(os.getenv('ATR_PERIOD', '10'))
        self.use_heikin_ashi = os.getenv('HEIKIN_ASHI', 'False').lower() == 'true'
        self.paper_trading = os.getenv('PAPER_TRADING', 'True').lower() == 'true'
        self.running = True
        
        # Parse timeframe to minutes for API
        self.timeframe_minutes = self._parse_timeframe_to_minutes(self.timeframe_str)
        
        # Get display symbol (without /USDT)
        self.display_symbol = self.symbol.replace('/USDT', '').replace('USDT', '')
        
        # Interval mapping for sleep time
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
        
        # Tracking variables
        self.last_signal = None
        self.trades_history = []
        self.logs = []
        
        # Log startup configuration
        logger.info("="*50)
        logger.info("UT Bot Crypto Started")
        logger.info("="*50)
        logger.info(f"Symbol: {self.symbol}")
        logger.info(f"Quantity: {self.quantity} {self.display_symbol}")
        logger.info(f"Timeframe: {self.timeframe_str} (24/7)")
        logger.info(f"Sensitivity: {self.a}")
        logger.info(f"ATR Period: {self.atr_period}")
        logger.info(f"Heikin Ashi: {self.use_heikin_ashi}")
        logger.info(f"Mode: {'PAPER' if self.paper_trading else 'LIVE'}")
        logger.info(f"Check Interval: {self.check_interval}s")
        logger.info("="*50)
    
    def _parse_timeframe_to_minutes(self, timeframe_str):
        """Convert timeframe string to minutes"""
        timeframe_map = {
            "1Min": 1, "5Min": 5, "15Min": 15, "30Min": 30,
            "1H": 60, "2H": 120, "4H": 240, "1D": 1440
        }
        return timeframe_map.get(timeframe_str, 15)
    
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
        """Convert regular candles to Heikin Ashi - Fixed no warnings"""
        ha_df = pd.DataFrame(index=df.index)
        
        # Calculate Heikin Ashi values using .loc to avoid warnings
        ha_df['close'] = (df['open'] + df['high'] + df['low'] + df['close']) / 4
        ha_df['open'] = (df['open'].shift(1) + df['close'].shift(1)) / 2
        
        # Fix the first row using .loc
        if len(ha_df) > 0:
            ha_df.loc[ha_df.index[0], 'open'] = (df['open'].iloc[0] + df['close'].iloc[0]) / 2
        
        ha_df['high'] = df[['high', 'open', 'close']].max(axis=1)
        ha_df['low'] = df[['low', 'open', 'close']].min(axis=1)
        
        return ha_df
    
    def calculate_atr(self, df, period=14):
        """Calculate Average True Range"""
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
        """Fetch historical crypto bar data"""
        if bars is None:
            bars = self.bars_to_fetch
            
        end = datetime.now()
        
        # Calculate start date based on timeframe in minutes
        total_minutes = self.timeframe_minutes * (bars + self.atr_period + 20)
        start = end - timedelta(minutes=total_minutes)
        
        # Create the correct timeframe for Alpaca API
        if self.timeframe_str == "1D":
            timeframe = TimeFrame.Day
        elif "H" in self.timeframe_str:
            timeframe = TimeFrame.Hour
        else:
            timeframe = TimeFrame.Minute
        
        request = CryptoBarsRequest(
            symbol_or_symbols=self.symbol,
            timeframe=timeframe,
            start=start,
            end=end,
            limit=bars + self.atr_period + 10
        )
        
        try:
            bars_data = self.data_client.get_crypto_bars(request)
            if not bars_data.data or self.symbol not in bars_data.data:
                return None
                
            df = bars_data.df
            if df.empty or len(df) < 20:
                return None
            
            # Reset index and rename columns
            df = df.reset_index()
            df = df.rename(columns={'timestamp': 'datetime', 'open': 'open', 
                                     'high': 'high', 'low': 'low', 'close': 'close'})
            df.set_index('datetime', inplace=True)
            
            # Sort by time
            df = df.sort_index()
            
            return df
        except Exception as e:
            self.add_log(f"Error fetching data: {e}", "ERROR")
            return None
    
    def execute_order(self, side, quantity=None):
        """Execute a crypto market order"""
        if quantity is None:
            quantity = self.quantity
        
        quantity = float(quantity)
        
        try:
            order_data = MarketOrderRequest(
                symbol=self.symbol,
                qty=quantity,
                side=side,
                time_in_force=TimeInForce.GTC
            )
            
            order = self.trading_client.submit_order(order_data)
            fill_price = float(order.filled_avg_price) if order.filled_avg_price else 0
            self.add_log(f"✅ {side.upper()} {quantity} {self.display_symbol} at ${fill_price:.2f}")
            return order
        except Exception as e:
            self.add_log(f"Order failed: {e}", "ERROR")
            return None
    
    def close_position(self):
        """Close current position"""
        try:
            position = self.trading_client.get_position(self.symbol)
            qty = abs(float(position.qty))
            entry_price = float(position.avg_entry_price)
            current_price = float(position.current_price)
            
            if float(position.side) > 0:
                order_side = OrderSide.SELL
                pnl = (current_price - entry_price) * qty
                position_type = "LONG"
            else:
                order_side = OrderSide.BUY
                pnl = (entry_price - current_price) * qty
                position_type = "SHORT"
            
            self.execute_order(order_side, qty)
            
            trade = {
                'time': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                'type': f"CLOSE_{position_type}",
                'price': current_price,
                'pnl': pnl
            }
            self.trades_history.insert(0, trade)
            if len(self.trades_history) > 50:
                self.trades_history = self.trades_history[:50]
            
            self.add_log(f"Closed {position_type} at ${current_price:.2f}, PnL: ${pnl:.2f}")
            return True
        except Exception as e:
            if "position does not exist" in str(e):
                return True
            self.add_log(f"Error closing position: {e}", "ERROR")
            return False
    
    def get_account_status(self):
        """Get current account status for dashboard"""
        try:
            account = self.trading_client.get_account()
            return {
                'buying_power': float(account.buying_power),
                'portfolio_value': float(account.portfolio_value)
            }
        except Exception:
            return {'buying_power': 0, 'portfolio_value': 0}
    
    def get_current_position(self):
        """Get current position for dashboard"""
        try:
            position = self.trading_client.get_position(self.symbol)
            entry_price = float(position.avg_entry_price)
            current_price = float(position.current_price)
            side = "LONG" if float(position.side) > 0 else "SHORT"
            qty = float(position.qty)
            pnl = (current_price - entry_price) * qty if side == "LONG" else (entry_price - current_price) * qty
            
            return {
                'status': side.lower(),
                'quantity': qty,
                'entry_price': entry_price,
                'current_pnl': pnl
            }
        except Exception:
            return {'status': 'flat', 'quantity': 0, 'entry_price': 0, 'current_pnl': 0}
    
    def get_latest_signal(self):
        """Get latest signal for dashboard"""
        try:
            df = self.get_historical_data(bars=10)
            if df is not None and len(df) > 5:
                signals = self.calculate_signals(df)
                last_idx = -1
                return {
                    'type': {1: 'BUY', -1: 'SELL'}.get(signals.iloc[last_idx]['signal'], None),
                    'price': float(signals.iloc[last_idx]['close']),
                    'stop': float(signals.iloc[last_idx]['trailing_stop']),
                    'timeframe': self.timeframe_str
                }
        except Exception:
            pass
        return {'type': None, 'price': 0, 'stop': 0, 'timeframe': self.timeframe_str}
    
    def run_strategy(self):
        """Main strategy loop"""
        global bot_instance
        bot_instance = self
        
        self.add_log(f"🚀 Starting UT Bot on {self.display_symbol}")
        self.add_log(f"📊 Trading {self.quantity} {self.display_symbol} per signal")
        
        while self.running:
            try:
                df = self.get_historical_data()
                if df is None or len(df) < self.atr_period + 10:
                    time.sleep(self.check_interval)
                    continue
                
                signals_df = self.calculate_signals(df)
                latest_signal = signals_df.iloc[-1]['signal']
                latest_close = signals_df.iloc[-1]['close']
                latest_stop = signals_df.iloc[-1]['trailing_stop']
                
                # Log current state
                self.add_log(f"{self.display_symbol}: ${latest_close:.2f} | Stop: ${latest_stop:.2f} | Signal: {latest_signal}")
                
                # Send alert on new signal
                if latest_signal != 0 and latest_signal != self.last_signal:
                    signal_type = "BUY" if latest_signal == 1 else "SELL"
                    self.add_log(f"🎯 SIGNAL: {signal_type} at ${latest_close:.2f}")
                    self.last_signal = latest_signal
                
                # Check current position
                try:
                    self.trading_client.get_position(self.symbol)
                    has_position = True
                except:
                    has_position = False
                
                # Execute signals
                if latest_signal == 1:
                    self.add_log("🔵 BUY SIGNAL - Going LONG")
                    if has_position:
                        self.close_position()
                        time.sleep(2)
                    self.execute_order(OrderSide.BUY)
                    
                elif latest_signal == -1:
                    self.add_log("🔴 SELL SIGNAL - Going SHORT")
                    if has_position:
                        self.close_position()
                        time.sleep(2)
                    self.execute_order(OrderSide.SELL)
                
                time.sleep(self.check_interval)
                
            except KeyboardInterrupt:
                self.add_log("🛑 Bot stopped by user")
                break
            except Exception as e:
                self.add_log(f"Error: {e}", "ERROR")
                time.sleep(self.check_interval)


# Flask routes
@app.route('/')
def dashboard():
    global bot_instance
    if not bot_instance or not bot_instance.running:
        return render_template_string("<h1>🤖 Bot is running...</h1><p>Check terminal for live updates.</p>"), 200
    
    account = bot_instance.get_account_status()
    position = bot_instance.get_current_position()
    signal = bot_instance.get_latest_signal()
    
    return render_template_string(DASHBOARD_TEMPLATE,
        account=account,
        position=position,
        signal=signal,
        logs=bot_instance.logs[-50:],
        bot_running=bot_instance.running
    )

@app.route('/api/status')
def api_status():
    global bot_instance
    if not bot_instance:
        return jsonify({'logs': []})
    
    return jsonify({'logs': bot_instance.logs[-50:]})

@app.route('/close_position', methods=['POST'])
def close_position_route():
    global bot_instance
    if bot_instance:
        bot_instance.close_position()
    return jsonify({'status': 'ok'})

@app.route('/stop', methods=['POST'])
def stop_route():
    global bot_instance
    if bot_instance:
        bot_instance.running = False
    return jsonify({'status': 'stopping'})


def run_dashboard():
    """Run Flask dashboard in separate thread"""
    app.run(host='0.0.0.0', port=5000, debug=False, use_reloader=False)


def main():
    print("\n" + "="*50)
    print("🤖 UT Bot Crypto - Clean Version")
    print("="*50)
    print("Loading configuration from .env file...")
    
    try:
        # Create bot instance (loads all from .env)
        bot = UTBotAlerts()
        
        # Start dashboard
        dashboard_thread = threading.Thread(target=run_dashboard, daemon=True)
        dashboard_thread.start()
        print("\n🌐 Web Dashboard: http://localhost:5000")
        
        # Start trading
        response = input("\n🚀 Start paper trading? (yes/no): ").lower().strip()
        if response == 'y':
            print("\n⚠️  Crypto trading runs 24/7. Press Ctrl+C to stop.\n")
            bot.run_strategy()
        else:
            print("Bot stopped.")
    except Exception as e:
        print(f"\n❌ Error: {e}")
        print("Please check your .env file has all required fields.")


if __name__ == "__main__":
    main()

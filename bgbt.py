import vectorbt as vbt
import pandas as pd
import numpy as np
import datetime as dt
import requests
import time
import warnings
warnings.filterwarnings('ignore')

import pandas_ta_classic as ta

print("="*70)
print("UT BOT FUTURES BACKTESTER - VERBOSE MODE")
print("="*70)
print(f"Time started: {dt.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
print(f"Python version: {__import__('sys').version}")
print(f"pandas-ta-classic version: {ta.version}")
print("="*70)

# ==================== DATA FETCHING WITH DETAILED LOGGING ====================

def download_bitget_futures_data(symbol: str, interval: str, start: dt.datetime, end: dt.datetime):
    """Fetch USDT-M Futures OHLCV data from Bitget with detailed logging"""
    
    print(f"\n[1/4] STARTING DATA DOWNLOAD")
    print(f"      Symbol: {symbol}")
    print(f"      Interval: {interval}")
    print(f"      Start: {start.strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"      End: {end.strftime('%Y-%m-%d %H:%M:%S')}")
    print("-"*70)
    
    interval_map = {
        '1m': '1m', '5m': '5m', '15m': '15m', '30m': '30m',
        '1h': '1H', '4h': '4H', '6h': '6H', '12h': '12H',
        '1d': '1D', '1w': '1W'
    }
    bitget_interval = interval_map.get(interval, interval)
    print(f"      Mapped interval: {bitget_interval}")
    
    start_ts = int(start.timestamp() * 1000)
    end_ts = int(end.timestamp() * 1000)
    print(f"      Start timestamp: {start_ts}")
    print(f"      End timestamp: {end_ts}")
    
    all_candles = []
    current_start = start_ts
    batch_num = 0
    total_candles = 0
    
    print(f"\n[DOWNLOAD PROGRESS]")
    
    while current_start < end_ts:
        batch_num += 1
        batch_end = min(current_start + (90 * 24 * 60 * 60 * 1000), end_ts)
        
        print(f"\n  Batch #{batch_num}:")
        print(f"    Requesting from {dt.datetime.fromtimestamp(current_start/1000).strftime('%Y-%m-%d')}")
        print(f"    to {dt.datetime.fromtimestamp(batch_end/1000).strftime('%Y-%m-%d')}")
        
        url = "https://api.bitget.com/api/v2/mix/market/history-candles"
        params = {
            'symbol': symbol,
            'productType': 'usdt-futures',
            'granularity': bitget_interval,
            'startTime': str(current_start),
            'endTime': str(batch_end),
            'limit': '200'
        }
        
        print(f"    URL: {url}")
        print(f"    Params: {params}")
        
        try:
            request_start = time.time()
            response = requests.get(url, params=params, timeout=10)
            request_time = time.time() - request_start
            print(f"    Response time: {request_time:.2f} seconds")
            print(f"    HTTP Status: {response.status_code}")
            
            data = response.json()
            print(f"    API Code: {data.get('code')}")
            print(f"    API Message: {data.get('msg')}")
            
            if data.get('code') == '00000' and data.get('data'):
                candles = data['data']
                batch_candles = len(candles)
                total_candles += batch_candles
                print(f"    ✅ Received {batch_candles} candles")
                
                if batch_candles > 0:
                    print(f"    First candle timestamp: {dt.datetime.fromtimestamp(int(candles[0][0])/1000)}")
                    print(f"    Last candle timestamp: {dt.datetime.fromtimestamp(int(candles[-1][0])/1000)}")
                    print(f"    Price range: {float(candles[0][4])} - {float(candles[-1][4])}")
                
                for candle in candles:
                    all_candles.append({
                        'timestamp': int(candle[0]),
                        'open': float(candle[1]),
                        'high': float(candle[2]),
                        'low': float(candle[3]),
                        'close': float(candle[4]),
                        'volume': float(candle[5])
                    })
                
                if batch_candles < 200:
                    print(f"    Last batch received, breaking")
                    break
                    
                current_start = int(candles[-1][0]) + 1
                print(f"    Next start timestamp: {dt.datetime.fromtimestamp(current_start/1000)}")
            else:
                print(f"    ❌ API error: {data.get('msg')} (Code: {data.get('code')})")
                break
                
        except requests.exceptions.Timeout:
            print(f"    ❌ Request timeout after 10 seconds")
            break
        except requests.exceptions.ConnectionError:
            print(f"    ❌ Connection error - check internet")
            break
        except Exception as e:
            print(f"    ❌ Unexpected error: {type(e).__name__}: {e}")
            break
        
        print(f"    Waiting 0.1s before next request...")
        time.sleep(0.1)
    
    print(f"\n[DOWNLOAD SUMMARY]")
    print(f"  Total batches: {batch_num}")
    print(f"  Total candles: {total_candles}")
    print(f"  Memory usage: {len(all_candles) * 48 / 1024:.2f} KB (approx)")
    
    if not all_candles:
        print("  ❌ No data downloaded!")
        return pd.DataFrame()
    
    print(f"\n[2/4] PROCESSING RAW DATA")
    df = pd.DataFrame(all_candles)
    print(f"  Raw DataFrame shape: {df.shape}")
    
    df['datetime'] = pd.to_datetime(df['timestamp'], unit='ms')
    df = df.set_index('datetime')
    df = df.sort_index()
    
    print(f"  Sorted by datetime")
    print(f"  Final DataFrame shape: {df.shape}")
    print(f"  Date range: {df.index.min()} to {df.index.max()}")
    print(f"  Missing values: {df.isnull().sum().sum()}")
    
    return df

# ==================== SIGNAL CALCULATION WITH DETAILED LOGGING ====================

def calculate_ut_bot_signals(df, sensitivity=1, atr_period=10):
    """UT Bot Strategy signals with detailed logging"""
    
    print(f"\n[3/4] CALCULATING UT BOT SIGNALS")
    print(f"  Sensitivity: {sensitivity}")
    print(f"  ATR Period: {atr_period}")
    print(f"  Input data shape: {df.shape}")
    print("-"*70)
    
    data = df.copy()
    
    print("  Calculating ATR...")
    data['xATR'] = ta.atr(data['high'], data['low'], data['close'], length=atr_period)
    data['nLoss'] = sensitivity * data['xATR']
    print(f"    ATR range: {data['xATR'].min():.2f} - {data['xATR'].max():.2f}")
    
    initial_rows = len(data)
    data = data.dropna()
    dropped_rows = initial_rows - len(data)
    print(f"  Dropped {dropped_rows} rows with NaN values")
    print(f"  Data shape after dropna: {data.shape}")
    
    data = data.reset_index(drop=True)
    
    print("  Calculating ATRTrailingStop (this may take a moment)...")
    
    def calc_trailing_stop(close, prev_close, prev_stop, nloss):
        if close > prev_stop and prev_close > prev_stop:
            return max(prev_stop, close - nloss)
        elif close < prev_stop and prev_close < prev_stop:
            return min(prev_stop, close + nloss)
        elif close > prev_stop:
            return close - nloss
        else:
            return close + nloss
    
    data['ATRTrailingStop'] = 0.0
    data.loc[0, 'ATRTrailingStop'] = data.loc[0, 'close'] - data.loc[0, 'nLoss']
    
    for i in range(1, len(data)):
        data.loc[i, 'ATRTrailingStop'] = calc_trailing_stop(
            data.loc[i, 'close'],
            data.loc[i-1, 'close'],
            data.loc[i-1, 'ATRTrailingStop'],
            data.loc[i, 'nLoss']
        )
        if i % 500 == 0:
            print(f"    Progress: {i}/{len(data)} rows processed ({i/len(data)*100:.1f}%)")
    
    print(f"  ATRTrailingStop range: {data['ATRTrailingStop'].min():.2f} - {data['ATRTrailingStop'].max():.2f}")
    
    print("  Calculating EMA signals...")
    data['ema'] = data['close'].ewm(span=1).mean()
    
    data['Above'] = (data['ema'] > data['ATRTrailingStop']) & (data['ema'].shift(1) <= data['ATRTrailingStop'].shift(1))
    data['Below'] = (data['ema'] < data['ATRTrailingStop']) & (data['ema'].shift(1) >= data['ATRTrailingStop'].shift(1))
    
    data['Long_Entry'] = (data['close'] > data['ATRTrailingStop']) & data['Above']
    data['Short_Entry'] = (data['close'] < data['ATRTrailingStop']) & data['Below']
    data['Long_Exit'] = (data['close'] < data['ATRTrailingStop']) & data['Below']
    data['Short_Exit'] = (data['close'] > data['ATRTrailingStop']) & data['Above']
    
    print(f"\n[SIGNAL SUMMARY]")
    print(f"  Long entries: {data['Long_Entry'].sum()}")
    print(f"  Short entries: {data['Short_Entry'].sum()}")
    print(f"  Long exits: {data['Long_Exit'].sum()}")
    print(f"  Short exits: {data['Short_Exit'].sum()}")
    print(f"  Total signals: {data['Long_Entry'].sum() + data['Short_Entry'].sum()}")
    
    return data

# ==================== BACKTEST WITH DETAILED LOGGING ====================

def run_backtest():
    """Run the complete backtest with verbose logging"""
    
    print("\n" + "="*70)
    print("STARTING BACKTEST")
    print("="*70)
    
    # Configuration
    SYMBOL = "BTCUSDT"
    INTERVAL = "4h"
    START_DATE = dt.datetime(2024, 9, 1)
    END_DATE = dt.datetime(2025, 5, 17)
    
    LEVERAGE = 10
    INITIAL_CAPITAL = 10000
    TAKER_FEE = 0.0006
    
    print(f"\n[CONFIGURATION]")
    print(f"  Symbol: {SYMBOL}")
    print(f"  Interval: {INTERVAL}")
    print(f"  Date range: {START_DATE.date()} to {END_DATE.date()}")
    print(f"  Leverage: {LEVERAGE}x")
    print(f"  Initial capital: ${INITIAL_CAPITAL:,}")
    print(f"  Taker fee: {TAKER_FEE*100}%")
    
    # Download data
    df = download_bitget_futures_data(SYMBOL, INTERVAL, START_DATE, END_DATE)
    
    if df.empty:
        print("\n❌ FATAL: No data downloaded. Cannot continue.")
        return None, None
    
    # Calculate signals
    signals = calculate_ut_bot_signals(df, sensitivity=1, atr_period=10)
    
    print(f"\n[4/4] RUNNING PORTFOLIO BACKTEST")
    print("-"*70)
    
    try:
        print("  Creating vectorbt portfolio...")
        pf = vbt.Portfolio.from_signals(
            close=signals['close'],
            entries=signals['Long_Entry'],
            exits=signals['Long_Exit'],
            short_entries=signals['Short_Entry'],
            short_exits=signals['Short_Exit'],
            init_cash=INITIAL_CAPITAL,
            fees=TAKER_FEE,
            slippage=0.0005,
            direction='both',
            upon_opposite_entry='ReverseReduce'
        )
        print("  ✅ Portfolio created successfully")
        
        print("  Calculating statistics...")
        stats = pf.stats()
        print("  ✅ Statistics calculated")
        
    except Exception as e:
        print(f"  ❌ Error during portfolio execution: {type(e).__name__}: {e}")
        return None, None
    
    # Display results
    print("\n" + "="*70)
    print("📈 FINAL BACKTEST RESULTS")
    print("="*70)
    
    metrics = {
        'Start Value': stats.get('Start Value', 0),
        'End Value': stats.get('End Value', 0),
        'Total Return [%]': stats.get('Total Return [%]', 0),
        'Benchmark Return [%]': stats.get('Benchmark Return [%]', 0),
        'Sharpe Ratio': stats.get('Sharpe Ratio', 0),
        'Sortino Ratio': stats.get('Sortino Ratio', 0),
        'Calmar Ratio': stats.get('Calmar Ratio', 0),
        'Max Drawdown [%]': stats.get('Max Drawdown [%]', 0),
        'Max Drawdown Duration': stats.get('Max Drawdown Duration', 0),
        'Total Trades': stats.get('Total Trades', 0),
        'Total Closed Trades': stats.get('Total Closed Trades', 0),
        'Win Rate [%]': stats.get('Win Rate [%]', 0),
        'Best Trade [%]': stats.get('Best Trade [%]', 0),
        'Worst Trade [%]': stats.get('Worst Trade [%]', 0),
        'Avg Winning Trade [%]': stats.get('Avg Winning Trade [%]', 0),
        'Avg Losing Trade [%]': stats.get('Avg Losing Trade [%]', 0),
        'Profit Factor': stats.get('Profit Factor', 0),
        'Expectancy': stats.get('Expectancy', 0),
    }
    
    for name, value in metrics.items():
        if isinstance(value, float):
            print(f"{name:25}: {value:.4f}")
        else:
            print(f"{name:25}: {value}")
    
    print("\n" + "="*70)
    print(f"Backtest completed at: {dt.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("="*70)
    
    # Try to show plot
    try:
        print("\n📊 Generating equity curve plot...")
        fig = pf.plot(subplots=['cum_returns'])
        print("  ✅ Plot created")
        fig.show()
        print("  📈 Plot displayed (may open in new window)")
    except Exception as e:
        print(f"  ⚠️ Plot could not be displayed: {e}")
    
    return pf, signals

# ==================== MAIN EXECUTION ====================

if __name__ == "__main__":
    print("\n" + "🚀" * 35)
    print("STARTING VERBOSE BACKTEST")
    print("🚀" * 35)
    
    start_time = time.time()
    portfolio, signals = run_backtest()
    end_time = time.time()
    
    elapsed = end_time - start_time
    print(f"\n⏱️  Total execution time: {elapsed:.2f} seconds ({elapsed/60:.2f} minutes)")
    
    if portfolio is not None:
        print("\n✅ Backtest completed successfully!")
    else:
        print("\n❌ Backtest failed. Check the logs above.")
    
    print("\n" + "="*70)

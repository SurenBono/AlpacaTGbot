# AlpacaSpotBot

.. just a terminal API test trading bot with localhost Web interface run on the smartphone via userland with DeepSeek.

Requirements:-

- 64bit Android Smartphone
- internet
- userland from playstore
- python3
- Ubuntu terminal basics
- Deepseek,Cloude..etc
- Dependency.. ask A.i
- Alpaca Trading API ( Demo Paper Trade )
- time & patience
- luck & timing

  ______________________________________
Get Ubuntu latest updates
```console
sudo apt-get update && apt-get upgrade -y
```
Dependency 1

```console
pip install alpaca-py pandas numpy python-dotenv flask requests
```

Dependencies 2
```console
pip install -r requirements.txt
```
Create Dir
```console
mkdir bot && cd ~/bot
python3 -m venv venv
source venv/bin/activate
```
Fill parameters & API keys 
```console
nano .env 
```
# Save with  Ctrl+X - y - Enter

Create bot
```console
nano botname.py
```
# Save with  Ctrl+X - y - Enter

Run
```console
python3 bot.py
```
# Confirm with 'y' or Cancel with Ctrl+C
# Open browser example http://192.168.0.170:5000/
______________________________________
 ![](pic/boot.jpg)
 ![](pic/localhost.jpg)
 ![](pic/lc2.jpg)
 ![](pic/lc3.jpg)

/home/yourusername/alpaca-bot/
1.  venv/             # Virtual environment
2. .env               # API keys 
3.  bot.py            # THE BOT 
4.  bot.log           # debug
5.  requirements.txt  # Optional


-suren 8/5/26-

#!/bin/bash
sudo apt-get -y update
sudo apt-get -y upgrade
sudo apt install -y python3 python3-pip python3-venv
mkdir ~/bot && cd ~/bot
python3 -m venv venv
source venv/bin/activate
pip install alpaca-trade-api python-dotenv requests flask pandas numpy
# Step 5 - Create your .env file
wget https://raw.githubusercontent.com/SurenBono/AlpacaTGbot/main/.env
nano .env
# Paste your credentials, then Ctrl+X → Y → Enter to save
wget https://raw.githubusercontent.com/SurenBono/AlpacaTGbot/main/emabot.py
# Step 6 - Run the bot
python3 alpaca_bot.py

import os
import time
import asyncio
from telethon import TelegramClient, events
from dotenv import load_dotenv
from signal_parser import parse_signal
from blofin_trading import trading_workflow

load_dotenv()

api_id = int(os.getenv("TELEGRAM_API_ID"))
api_hash = os.getenv("TELEGRAM_API_HASH")
channel_username = os.getenv("TELEGRAM_CHANNEL")

client = TelegramClient('session_name', api_id, api_hash)

@client.on(events.NewMessage(chats=channel_username))
async def message_handler(event):
    message_text = event.message.message
    parsed_signal = parse_signal(message_text)
    print(f"Parsed Signal from Telegram: {parsed_signal}")
    
    # Validate that all required fields are present
    if (parsed_signal.get('ticker') is not None and 
        parsed_signal.get('trade_type') is not None and 
        parsed_signal.get('entry') is not None and 
        parsed_signal.get('targets') is not None and 
        parsed_signal.get('stoploss') is not None):
        print("All required fields found. Creating Order...")
        
        # Launch the trading workflow as a background task
        asyncio.create_task(trading_workflow(parsed_signal))
    else:
        print("Parsed signal is missing required fields. Skipping order.")
        print('------------------------------------------------------------------------------------')

async def main():
    print(f"Starting Telegram listener for channel: {channel_username}")
    await client.start()  # Restores session and logs in
    print("Client started, listening for messages...")
    print('------------------------------------------------------------------------------------')
    await client.run_until_disconnected()

if __name__ == '__main__':
    # Auto-reconnect loop: if the client disconnects, wait 10 seconds and reconnect.
    while True:
        try:
            asyncio.run(main())
        # except ConnectionResetError as e:
        except Exception as e:
            print(f"Connection error encountered: {e}")
            print("Reconnecting in 10 seconds...")
            time.sleep(10)


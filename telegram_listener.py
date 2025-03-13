import os
import asyncio
import logging
from telethon import TelegramClient, events
from dotenv import load_dotenv
from signal_parser import parse_signal
from blofin_trading import trading_workflow

load_dotenv()

api_id = int(os.getenv("TELEGRAM_API_ID"))
api_hash = os.getenv("TELEGRAM_API_HASH")
channel_username = os.getenv("TELEGRAM_CHANNEL")

# Initialize the Telegram client with a persistent session
client = TelegramClient('session_name', api_id, api_hash)

@client.on(events.NewMessage(chats=channel_username))
async def message_handler(event):
    message_text = event.message.message
    parsed_signal = parse_signal(message_text)
    print(f"Parsed Signal from Telegram: {parsed_signal}")

    # TODO: Forward parsed_signal to your trading module if valid
    if (parsed_signal.get('ticker') is not None and 
      parsed_signal.get('trade_type') is not None and 
      parsed_signal.get('entry') is not None and 
      parsed_signal.get('targets') is not None and 
      parsed_signal.get('stoploss') is not None):
        print("All required fields found. Creating Order...")
        asyncio.create_task(trading_workflow(parsed_signal))
    else:
        print("Parsed signal is missing required fields. Skipping order.")
        print('------------------------------------------------------------------------------------')

async def main():
    print(f"Starting Telegram listener for channel: {channel_username}")
    await client.start()  # Automatically handles login and session restoration
    print("Client started, listening for messages...")
    print('------------------------------------------------------------------------------------')

    # Run until disconnected (Telethon auto-reconnects on network issues)
    await client.run_until_disconnected()

if __name__ == '__main__':
    asyncio.run(main())

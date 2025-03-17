import os
import asyncio
from telethon import TelegramClient, events
from dotenv import load_dotenv
from signal_parser import parse_signal
from blofin_trading import trading_workflow

# Load configuration from .env
load_dotenv()

api_id = int(os.getenv("TELEGRAM_API_ID"))
api_hash = os.getenv("TELEGRAM_API_HASH")
channel_username = os.getenv("TELEGRAM_CHANNEL")

client = TelegramClient('session_name', api_id, api_hash)

@client.on(events.NewMessage(chats=channel_username))
async def message_handler(event):
    """
    Invoked on new messages in the Telegram Channel.
    """
    message_text = event.message.message
    parsed_signal = parse_signal(message_text)
    print(f"Parsed Signal from Telegram: {parsed_signal}")
    
    # Validate required fields in the parsed signal
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

async def disconnect_after(delay: int):
    await asyncio.sleep(delay)
    await client.disconnect()

async def main():
    while True:
        print('------------------------------------------------------------------------------------')
        print(f"Starting Telegram listener for channel: {channel_username}")
        await client.start()  # This restores the session and logs in
        print("Client started, listening for messages...")
        print('------------------------------------------------------------------------------------')
        
        # Run both the listener and the disconnect task concurrently.
        # When disconnect_after finishes, it will call client.disconnect()
        # which in turn causes run_until_disconnected() to return.
        await asyncio.gather(
            client.run_until_disconnected(),
            disconnect_after(7200)
        )
        print("Scheduled disconnection from Telegram. Waiting 10 seconds before reconnecting...")
        await asyncio.sleep(10)

if __name__ == '__main__':
    asyncio.run(main())

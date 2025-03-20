import os
import asyncio
from datetime import datetime, timezone
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

    # Workaround fixing telethon client sometimes parsing the last two messages when re-starting the server.
    # Ignores a message if its more than a minute old
    message_date_utc = event.message.date.astimezone(timezone.utc)
    if (datetime.now(timezone.utc) - message_date_utc).total_seconds() > 60:
        print("Ignoring old message")
        return

    message_text = event.message.message
    parsed_signal = parse_signal(message_text)
    print(f"({datetime.now().strftime('%I:%M%p').lstrip('0')}) Parsed Signal from Telegram: {parsed_signal}")
    
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
    print(f"({datetime.now().strftime('%I:%M%p').lstrip('0')}) Scheduled telegram disconnect. Reconnecting in 10 seconds...")
    await client.disconnect()

async def main():
    while True:
        print(f"Starting Telegram listener for channel: {channel_username}")
        await client.start()  # This restores the session and logs in
        print("Client started, listening for messages...")
        print('------------------------------------------------------------------------------------')
        
        # Run both the listener and the disconnect task concurrently.
        # When disconnect_after finishes, it will call client.disconnect()
        # which in turn causes run_until_disconnected() to return.
        await asyncio.gather(
            client.run_until_disconnected(),
            disconnect_after(7200) # in seconds
        )
        # Wait ten seconds after scheduled disconnect before reconnecting
        await asyncio.sleep(10)

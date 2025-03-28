import os
import asyncio
from datetime import datetime, timedelta, timezone
from telethon import TelegramClient
from dotenv import load_dotenv
from signal_parser import parse_signal
from blofin_trading import trading_workflow

load_dotenv()
api_id = int(os.getenv("TELEGRAM_API_ID"))
api_hash = os.getenv("TELEGRAM_API_HASH")
channel_username = os.getenv("TELEGRAM_CHANNEL")

# Initialize the Telegram client with a persistent session
client = TelegramClient("session_name", api_id, api_hash)

async def poll_messages():
    """
    Polls messages from the telegram channel every 10 minutes.
    """
    last_processed = None  # Track the latest message date we've processed
    while True:
        now = datetime.now(timezone.utc)
        # We want to poll messages from the past 10 minutes.
        # If we have processed messages before, only look at messages newer than last_processed.
        lower_bound = now - timedelta(minutes=10)
        if last_processed and last_processed > lower_bound:
            lower_bound = last_processed
        
        # print(f"Polling messages from {lower_bound.strftime('%H:%M')} to now...")
        # Fetch up to 10 messages from the channel
        messages = await client.get_messages(channel_username, limit=10)
        messages = list(messages)
        # Reverse to process in chronological order
        messages.reverse()
        
        for msg in messages:
            # msg.date is a datetime (likely offset-aware)
            if msg.date >= lower_bound:
                # print(f"Processing message {msg.id} at {msg.date.strftime('%H:%M')}")
                parsed_signal = parse_signal(msg.message)
                print(f"Parsed signal: {parsed_signal}")
                # Validate required fields
                if (parsed_signal.get('ticker') is not None and
                    parsed_signal.get('trade_type') is not None and
                    parsed_signal.get('entry') is not None and
                    parsed_signal.get('targets') is not None and
                    parsed_signal.get('stoploss') is not None):
                    print("Valid signal detected. Launching trading workflow...")
                    asyncio.create_task(trading_workflow(parsed_signal))
                else:
                    print("Invalid signal. Skipping.")
                    print('------------------------------------------------------------------------------------')
                
                # Update the last processed timestamp
                if (last_processed is None) or (msg.date > last_processed):
                    last_processed = msg.date
        
        print("Sleeping for 10 minutes...")
        await asyncio.sleep(600)

async def main():
    await client.start()
    print("Telegram client started. Polling messages...")
    print('------------------------------------------------------------------------------------')
    await poll_messages()

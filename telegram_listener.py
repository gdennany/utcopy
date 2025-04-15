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

client = TelegramClient("session_name", api_id, api_hash)

async def poll_messages():
    """
    Every 10 minutes, open a new connection, fetch messages from the last 10 minutes,
    process them, and then disconnect.
    """
    last_processed = None  # Track the latest message date we've processed
    
    while True:
        try:
            # Connect for this poll cycle
            await client.connect()
            now = datetime.now(timezone.utc)
            # Set lower_bound to 10 minutes ago (or later if we've processed recent messages)
            lower_bound = now - timedelta(minutes=10)
            if last_processed and last_processed > lower_bound:
                lower_bound = last_processed

            # Fetch up to 10 messages
            messages = await client.get_messages(channel_username, limit=20)
            messages = list(messages)
            messages.reverse()  # Process in chronological order
            for msg in messages:
                if msg.date >= lower_bound:
                    print(f"Processing message id {msg.id} from {msg.date.strftime('%H:%M')}")
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

            # Disconnect at the end of this poll cycle
            await client.disconnect()
        except Exception as e:
            print(f"Error during polling: {e}")
            try:
                await client.disconnect()
            except Exception as e_disconnect:
                print(f"Error while disconnecting: {e_disconnect}")
        print("Polling complete. Sleeping for 10 minutes...")
        await asyncio.sleep(600)

async def main():
    print("Telegram client started. Polling messages...")
    print('------------------------------------------------------------------------------------')
    await poll_messages()

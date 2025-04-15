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

async def poll_messages():
    """
    Every 10 minutes, open a new connection with Telegram, fetch messages from the last 10 minutes,
    process them, and then disconnect.
    """
    print(f"Telegram client started for channel {channel_username}. Polling messages...")
    print('------------------------------------------------------------------------------------')

    last_processed = None  # Track latest message date processed

    while True:
        # Create a fresh client instance for this cycle
        client = TelegramClient("session_name", api_id, api_hash)

        try:
            await client.start()
            # Resolve the channel entity once so we don't repeatedly re-resolve the username
            channel_entity = await client.get_entity(channel_username)
            
            now = datetime.now(timezone.utc)
            # Poll messages from the last 10 minutes
            lower_bound = now - timedelta(minutes=10)
            if last_processed and last_processed > lower_bound:
                lower_bound = last_processed
            
            # Fetch up to 10 messages from the channel
            messages = await client.get_messages(channel_entity, limit=10)
            # Reverse to process in chronological order
            messages = list(messages)
            messages.reverse()

            for msg in messages:
                # Only process messages whose timestamp is >= lower_bound
                if msg.date >= lower_bound:
                    parsed_signal = parse_signal(msg.message)
                    print(f"({datetime.now().strftime('%I:%M%p').lstrip('0')}) Parsed signal: {parsed_signal}")

                    # Validate required fields in the parsed signal
                    if (parsed_signal.get('ticker') is not None and
                        parsed_signal.get('trade_type') is not None and
                        parsed_signal.get('entry') is not None and
                        parsed_signal.get('targets') is not None and
                        parsed_signal.get('stoploss') is not None):
                        print("All required fields found. Launching trading workflow...")
                        asyncio.create_task(trading_workflow(parsed_signal))
                    else:
                        print("Invalid signal detected. Skipping.")
                        print('------------------------------------------------------------------------------------')
                    
                    # Update last_processed to the latest message date encountered
                    if last_processed is None or msg.date > last_processed:
                        last_processed = msg.date

        except Exception as e:
            print(f"Error during polling: {e}")
        finally:
            try:
                await client.disconnect()
            except Exception as e_disconnect:
                print(f"Error disconnecting client: {e_disconnect}")

        await asyncio.sleep(600)

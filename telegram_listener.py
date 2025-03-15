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
    message_text = event.message.message
    parsed_signal = parse_signal(message_text)
    print(f"Parsed Signal from Telegram: {parsed_signal}")
    
    # Validate required fields from the parsed signal (using dictionary keys)
    if (parsed_signal.get('ticker') is not None and 
        parsed_signal.get('trade_type') is not None and 
        parsed_signal.get('entry') is not None and 
        parsed_signal.get('targets') is not None and 
        parsed_signal.get('stoploss') is not None):
        print("All required fields found. Creating Order...")
        # Launch the trading workflow as a background task
        # asyncio.create_task(trading_workflow(parsed_signal))
    else:
        print("Parsed signal is missing required fields. Skipping order.")
        print('------------------------------------------------------------------------------------')

async def main():
    while True:
        try:
            print('------------------------------------------------------------------------------------')
            print(f"Starting Telegram listener for channel: {channel_username}")
            await client.start()
            print("Client started, listening for messages...")
            print('------------------------------------------------------------------------------------')
            
             # Schedule disconnect after 1 hours (3600 seconds)
            async def disconnect_after(delay: int):
                await asyncio.sleep(delay)
                print("Scheduled disconnect from Telegram. Reconnecting in 10 seconds...")
                await client.disconnect()

            asyncio.create_task(disconnect_after(1600))
                
            # Run until the client disconnects
            await client.run_until_disconnected()
        except Exception as e:
            print(f"Connection error encountered: {e}. Reconnecting in 10 seconds...")
            await asyncio.sleep(10)
            await client.disconnect()
        else:
            # Hit after scheduled disconnect
            await asyncio.sleep(10)


if __name__ == '__main__':
    # Run the main function in a single event loop
    asyncio.run(main())

import asyncio
from telegram_listener import poll_messages

if __name__ == "__main__":
    asyncio.run(poll_messages())

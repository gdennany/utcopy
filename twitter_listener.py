import os
import asyncio
from datetime import datetime, timezone, timedelta
import tweepy
from dotenv import load_dotenv
from signal_parser import parse_signal
from blofin_trading import trading_workflow

# Load environment variables from .env
load_dotenv()
TWITTER_BEARER_TOKEN = os.getenv("TWITTER_BEARER_TOKEN")
TARGET_TWITTER_USER = os.getenv("TARGET_TWITTER_USER")

# Initialize Tweepy client for Twitter API v2 using a Bearer token
twitter_client = tweepy.Client(bearer_token=TWITTER_BEARER_TOKEN, wait_on_rate_limit=True)

def get_user_id(username: str) -> str:
    """Fetch the Twitter user ID given a username."""
    response = twitter_client.get_user(username=username)
    if response.data:
        return response.data.id
    else:
        raise Exception(f"Unable to find user id for username: {username}")

# Retrieve the target user's ID once.
user_id = get_user_id(TARGET_TWITTER_USER)

async def poll_twitter():
    """
    Every 10 minutes, poll recent tweets from the target user, parse them,
    and launch the trading workflow for each valid signal.
    """
    # Start with last_checked as 10 minutes ago.
    last_checked = datetime.now(timezone.utc) - timedelta(minutes=10)
    while True:
        now = datetime.now(timezone.utc)
        print(f"Polling tweets from {TARGET_TWITTER_USER} between {last_checked.strftime('%H:%M')} and {now.strftime('%H:%M')}")
        
        # Construct a query to fetch tweets from this user
        # Search for tweets that are recent; this returns tweets in reverse-chronological order.
        query = f"from:{TARGET_TWITTER_USER}"
        response = twitter_client.search_recent_tweets(
            query=query,
            tweet_fields=["created_at"],
            max_results=20
        )
        
        if response.data:
            # Process tweets in reverse order (oldest first)
            tweets = sorted(response.data, key=lambda t: t.created_at)
            for tweet in tweets:
                # Only process tweets newer than last_checked
                if tweet.created_at > last_checked:
                    tweet_time = tweet.created_at.strftime("%H:%M")
                    print(f"New tweet at {tweet_time}: {tweet.text}")
                    signal = parse_signal(tweet.text)
                    print(f"Parsed signal: {signal}")
                    # Validate required fields
                    if (signal.get('ticker') is not None and
                        signal.get('trade_type') is not None and
                        signal.get('entry') is not None and
                        signal.get('targets') is not None and
                        signal.get('stoploss') is not None):
                        print("Valid signal detected. Launching trading workflow...")
                        asyncio.create_task(trading_workflow(signal))
                    else:
                        print("Signal missing required fields. Skipping.")
        else:
            print("No tweets found for this interval.")
        
        # Update last_checked to now
        last_checked = now
        # Wait for 10 minutes (600 seconds) before polling again
        await asyncio.sleep(600)

async def main():
    print("Starting Twitter signal poller...")
    await poll_twitter()

if __name__ == "__main__":
    asyncio.run(main())

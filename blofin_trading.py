import os
import asyncio
import base64
import hmac
import hashlib
import json
import requests
import time
import uuid
import websockets
from dotenv import load_dotenv

load_dotenv()
API_KEY = os.getenv("BLOFIN_API_KEY")
SECRET = os.getenv("BLOFIN_API_SECRET")
PASSPHRASE = os.getenv("BLOFIN_API_PASSPHRASE")
LEVERAGE = os.getenv("LEVERAGE")
ORDER_USD_AMOUNT = os.getenv("ORDER_USD_AMOUNT")

ROOT_URL = os.getenv("BLOFIN_ROOT_URL")
WS_URL = os.getenv("BLOFIN_WS_URL")


def generate_ws_signature(timestamp: str, nonce: str) -> str:
    """
    Generate signature for WebSocket authentication.
    Fixed components for WS auth:
      - path: "/users/self/verify"
      - method: "GET"
    Prehash string = path + method + timestamp + nonce
    """
    path = "/users/self/verify"
    method = "GET"
    msg = f"{path}{method}{timestamp}{nonce}"
    hex_signature = hmac.new(SECRET.encode(), msg.encode(), hashlib.sha256).hexdigest().encode()
    return base64.b64encode(hex_signature).decode()

async def sign_and_login(ws) -> None:
    """
    Authenticate to Blofin’s WebSocket using private login.
    """
    timestamp = str(int(time.time() * 1000))
    nonce = str(uuid.uuid4())
    sign = generate_ws_signature(timestamp, nonce)
    login_payload = {
        "op": "login",
        "args": [{
            "apiKey": API_KEY,
            "passphrase": PASSPHRASE,
            "timestamp": timestamp,
            "sign": sign,
            "nonce": nonce
        }]
    }
    await ws.send(json.dumps(login_payload))
    response = await ws.recv()

def generate_rest_signature(path: str, method: str, timestamp: str, nonce: str, body: str) -> str:
    """
    Generate the signature for the REST API.
    Prehash string = path + method + timestamp + nonce + body
    """
    msg = f"{path}{method.upper()}{timestamp}{nonce}{body}"
    hex_signature = hmac.new(SECRET.encode('utf-8'), msg.encode('utf-8'), hashlib.sha256).hexdigest().encode('utf-8')
    return base64.b64encode(hex_signature).decode()

def place_rest_order(signal: dict) -> dict:
    """
    Place a limit order using Blofin's REST API based on the Telegram signal.
    
    For LONG: uses the highest entry price.
    For SHORT: uses the lowest entry price.
    Uses the first target as the take profit price.
    
    The order USD amount and leverage are taken from .env variables.
    The order size (in tokens) is calculated as:
        (ORDER_USD_AMOUNT * leverage) / entry_price
    """
    trade_type = signal.get("trade_type", "").upper()
    entries = signal.get("entry", [])
    if not entries:
        raise Exception("No entry prices in signal.")
    
    if trade_type == "LONG":
        entry_price = max(entries)
        side = "buy"
    elif trade_type == "SHORT":
        entry_price = min(entries)
        side = "sell"
    else:
        raise Exception("Invalid trade type in signal.")

    targets = signal.get("targets", [])
    if not targets:
        raise Exception("No target prices in signal.")
    take_profit = targets[0]

    stoploss = signal.get("stoploss")
    if stoploss is None:
        raise Exception("No stop loss provided in signal.")

    ticker = signal.get("ticker")
    if not ticker:
        raise Exception("No ticker provided in signal.")
    instId = f"{ticker.upper()}-USDT"

    # Calculate order size from desired USD amount and leverage:
    usd_amount = float(ORDER_USD_AMOUNT)
    leverage = float(LEVERAGE)
    notional = usd_amount * leverage
    order_size = notional / entry_price  # Number of tokens/contracts

    order_request = {
        "instId": instId,
        "marginMode": "cross",
        "side": side,
        "orderType": "limit",
        "price": str(entry_price),
        "size": str(round(order_size, 2)),
        "slTriggerPrice": str(stoploss),
        "slOrderPrice": "-1",
        "tpTriggerPrice": str(take_profit),
        "tpOrderPrice": "-1",
        "leverage": str(int(leverage)),
        "positionSide": "net",
    }
    body = json.dumps(order_request)
    path = "/api/v1/trade/order"
    method = "POST"
    timestamp = str(int(time.time() * 1000))
    nonce = timestamp  # Using timestamp as nonce for simplicity
    signature = generate_rest_signature(path, method, timestamp, nonce, body)

    headers = {
        "ACCESS-KEY": API_KEY,
        "ACCESS-SIGN": signature,
        "ACCESS-TIMESTAMP": timestamp,
        "ACCESS-NONCE": nonce,
        "ACCESS-PASSPHRASE": PASSPHRASE,
        "Content-Type": "application/json"
    }

    url = ROOT_URL + path
    print("Placing order with payload:")
    print(json.dumps(order_request, indent=2))
    response = requests.post(url, headers=headers, json=order_request)
    response.raise_for_status()
    order_response = response.json()
    if "code" in order_response and order_response["code"] != "0":
        raise Exception(f"Order API error: {order_response}")
    if "data" not in order_response:
        raise Exception(f"No data in order response: {order_response}")
    return order_response

async def wait_for_order_confirmation(ws, order_id: str, timeout: int = 10) -> dict:
    """
    Listen for order updates on the WebSocket and wait until the update for order_id is received.
    """
    async def listen():
        while True:
            data = json.loads(await ws.recv())
            if data.get("action") == "update":
                for order in data.get("data", []):
                    if order.get("orderId") == order_id:
                        return order
    try:
        order_update = await asyncio.wait_for(listen(), timeout=timeout)
        return order_update
    except asyncio.TimeoutError:
        raise Exception("Timeout waiting for order confirmation.")

async def trading_workflow(signal: dict):
    """
    Complete trading workflow using a Telegram signal.
    """
    # 1. Connect to WebSocket and authenticate
    ws = await websockets.connect(WS_URL)
    await sign_and_login(ws)
    await asyncio.sleep(1)
    
    # 2. Subscribe to orders channel for the instrument from the signal
    instId = f"{signal.get('ticker').upper()}-USDT"
    subscribe_payload = {
        "op": "subscribe",
        "args": [{"channel": "orders", "instId": instId}]
    }
    await ws.send(json.dumps(subscribe_payload))
    sub_response = await ws.recv()
    
    # 3. Place limit order via REST using the signal details
    order_response = place_rest_order(signal)
    order_id = order_response["data"][0]["orderId"]
    
    # 4. Wait for order confirmation via WebSocket
    try:
        order_update = await wait_for_order_confirmation(ws, order_id)
        print("Order confirmed")
    except Exception as e:
        print("Order failed")
        print(str(e))

  
    print('------------------------------------------------------------------------------------')
    
    # (Optional) 5. Order cancellation code can be added similarly.
    
    # Clean up WebSocket connection
    await ws.close()

if __name__ == "__main__":
    # Example Telegram signal parsed from a message:
    telegram_signal = {
        "ticker": "SOL",
        "trade_type": "LONG",
        "entry": [122.34],
        "targets": [200],
        "stoploss": 80
    }
    asyncio.run(trading_workflow(telegram_signal))

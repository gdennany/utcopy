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
    await ws.recv()


def generate_rest_signature(path: str, method: str, timestamp: str, nonce: str, body: str) -> str:
    """
    Generate the signature for the REST API.
    Prehash string = path + method + timestamp + nonce + body
    """
    msg = f"{path}{method.upper()}{timestamp}{nonce}{body}"
    hex_signature = hmac.new(SECRET.encode('utf-8'), msg.encode('utf-8'), hashlib.sha256).hexdigest().encode('utf-8')
    return base64.b64encode(hex_signature).decode()

def set_leverage(instId: str) -> dict:
    """
    Set the leverage for the given instrument. Using cross margin mode so
    marginMode is always "cross" and positionSide is "net".
    
    Example payload:
    {
        "instId": "BTC-USDT",
        "leverage": "5",
        "marginMode": "cross",
        "positionSide": "net"
    }
    """
    payload = {
        "instId": instId,
        "leverage": LEVERAGE,
        "marginMode": "cross"
    }

    body = json.dumps(payload)
    path = "/api/v1/account/set-leverage"
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
    response = requests.post(url, headers=headers, json=payload)
    response.raise_for_status()
    leverage_response = response.json()

    if "code" in leverage_response and leverage_response["code"] != "0":
        raise Exception(f"Set leverage error: {leverage_response}")

    return leverage_response

def get_instrument_details(instId: str) -> dict:
    """
    Retrieve instrument details from the GET /api/v1/market/instruments endpoint.
    """
    url = f"{ROOT_URL}/api/v1/market/instruments"
    params = {"instId": instId}
    response = requests.get(url, params=params)
    response.raise_for_status()
    data = response.json()
    if "data" not in data or not data["data"]:
        raise Exception(f"No instrument data for {instId}")
    # Return the first instrument matching the instId
    return data["data"][0]

def round_to_multiple(value: float, multiple: float) -> float:
    """
    Round value to the nearest multiple.
    """
    return round(round(value / multiple) * multiple, 8)


def place_rest_order(signal: dict) -> dict:
    """
    Place a limit order using Blofin's REST API based on the Telegram signal.
    
    For LONG: uses the highest entry price.
    For SHORT: uses the lowest entry price.
    Uses the first target as the take profit price.
    
    The order USD amount and leverage are taken from .env variables.
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
    
    # Retrieve instrument details. These are used to determine the amount of "contracts" to buy, and the floating point precision
    # allowed. The "size" in the order request must be sent in contract size, and contract size is not always 1:1 with a coin. So
    # arithmetic is requiored to parse the actual order size for the given contract size. 
    instrument = get_instrument_details(instId)
    contractValue = float(instrument.get("contractValue", "1"))
    lotSize = float(instrument.get("lotSize", "1"))
    tickSize = float(instrument.get("tickSize", "0.0001"))   

    # Adjust entry price to the nearest tick size:
    entry_price = round_to_multiple(entry_price, tickSize)

    # Calculate order size (number of contracts):
    usd_amount = float(ORDER_USD_AMOUNT)
    leverage_val = float(LEVERAGE)
    notional = usd_amount * leverage_val
    # Cost per contract in USD:
    cost_per_contract = entry_price * contractValue
    order_size = notional / cost_per_contract
    # Round order_size to the nearest multiple of lotSize:
    order_size = round_to_multiple(order_size, lotSize)

    # Build the order request payload.
    # For SL and TP, using "-1" means market execution when triggered.
    order_request = {
        "instId": instId,
        "marginMode": "cross",
        "side": side,
        "orderType": "limit",
        "price": str(entry_price),
        "size": str(order_size),
        "slTriggerPrice": str(stoploss),
        "slOrderPrice": "-1",
        "tpTriggerPrice": str(take_profit),
        "tpOrderPrice": "-1",
        "leverage": str(int(leverage_val)),
        "positionSide": "net",
    }

    print("Placing order with payload:")
    print(json.dumps(order_request, indent=2))

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
    
    # Determine instrument from signal
    instId = f"{signal.get('ticker').upper()}-USDT"
    
    # 1. Set the desired leverage (always using cross margin mode)
    try:
        set_leverage(instId)
    except Exception as e:
        raise Exception("Set leverage failed:", e)
    
    # 2. Connect to WebSocket and authenticate
    ws = await websockets.connect(WS_URL)
    await sign_and_login(ws)
    await asyncio.sleep(1)
    
    # 3. Subscribe to orders channel for the instrument from the signal
    subscribe_payload = {
        "op": "subscribe",
        "args": [{"channel": "orders", "instId": instId}]
    }
    await ws.send(json.dumps(subscribe_payload))
    await ws.recv()
    
    # 4. Place limit order via REST using the signal details
    order_response = place_rest_order(signal)
    order_id = order_response["data"][0]["orderId"]
    
    # 5. Wait for order confirmation via WebSocket
    try:
        await wait_for_order_confirmation(ws, order_id)
        print("Order placed successfully.")
    except Exception as e:
        print("Order failed: ", e)
    
    print('------------------------------------------------------------------------------------')
    
    # (Optional) 6. Order cancellation logic.
    
    # Clean up WebSocket connection
    await ws.close()

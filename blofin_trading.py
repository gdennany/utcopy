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

    # Split position into two legs for partial TP behavior.
    # Leg A: 50% size with TP at first target and SL (market on trigger)
    # Leg B: remaining size with SL only (no TP)

    # Compute half sizes respecting lot size increments. Ensure we do not end up with zero-size legs.
    half_size = round_to_multiple(order_size / 2.0, lotSize)
    if half_size <= 0:
        half_size = order_size
    remaining_size = round_to_multiple(order_size - half_size, lotSize)
    if remaining_size < 0:
        remaining_size = 0

    # Build payload for Leg A (with TP and SL)
    order_request_with_tp = {
        "instId": instId,
        "marginMode": "cross",
        "side": side,
        "orderType": "limit",
        "price": str(entry_price),
        "size": str(half_size),
        "slTriggerPrice": str(stoploss),
        "slOrderPrice": "-1",
        "tpTriggerPrice": str(take_profit),
        "tpOrderPrice": "-1",
        "leverage": str(int(leverage_val)),
        "positionSide": "net",
    }

    print("Placing order (50% with TP) with payload:")
    print(json.dumps(order_request_with_tp, indent=2))

    path = "/api/v1/trade/order"
    method = "POST"
    url = ROOT_URL + path

    # Sign and send Leg A
    body_a = json.dumps(order_request_with_tp)
    timestamp_a = str(int(time.time() * 1000))
    nonce_a = timestamp_a
    signature_a = generate_rest_signature(path, method, timestamp_a, nonce_a, body_a)
    headers_a = {
        "ACCESS-KEY": API_KEY,
        "ACCESS-SIGN": signature_a,
        "ACCESS-TIMESTAMP": timestamp_a,
        "ACCESS-NONCE": nonce_a,
        "ACCESS-PASSPHRASE": PASSPHRASE,
        "Content-Type": "application/json"
    }
    response_a = requests.post(url, headers=headers_a, json=order_request_with_tp)
    response_a.raise_for_status()
    order_response_a = response_a.json()
    if "code" in order_response_a and order_response_a["code"] != "0":
        raise Exception(f"Order API error (leg A): {order_response_a}")
    if "data" not in order_response_a:
        raise Exception(f"No data in order response (leg A): {order_response_a}")

    # If there is remaining size, place Leg B (SL only)
    if remaining_size > 0:
        order_request_sl_only = {
            "instId": instId,
            "marginMode": "cross",
            "side": side,
            "orderType": "limit",
            "price": str(entry_price),
            "size": str(remaining_size),
            "slTriggerPrice": str(stoploss),
            "slOrderPrice": "-1",
            # No TP for this leg
            "leverage": str(int(leverage_val)),
            "positionSide": "net",
        }

        print("Placing order (remaining with SL only) with payload:")
        print(json.dumps(order_request_sl_only, indent=2))

        body_b = json.dumps(order_request_sl_only)
        timestamp_b = str(int(time.time() * 1000))
        nonce_b = timestamp_b
        signature_b = generate_rest_signature(path, method, timestamp_b, nonce_b, body_b)
        headers_b = {
            "ACCESS-KEY": API_KEY,
            "ACCESS-SIGN": signature_b,
            "ACCESS-TIMESTAMP": timestamp_b,
            "ACCESS-NONCE": nonce_b,
            "ACCESS-PASSPHRASE": PASSPHRASE,
            "Content-Type": "application/json"
        }
        response_b = requests.post(url, headers=headers_b, json=order_request_sl_only)
        response_b.raise_for_status()
        order_response_b = response_b.json()
        if "code" in order_response_b and order_response_b["code"] != "0":
            raise Exception(f"Order API error (leg B): {order_response_b}")

    # Return list of created order IDs for downstream confirmation waits
    order_ids = [order_response_a["data"][0]["orderId"]]
    if remaining_size > 0:
        order_ids.append(order_response_b["data"][0]["orderId"])  # type: ignore[name-defined]
    return order_ids


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


async def wait_for_multiple_order_confirmations(ws, order_ids, timeout: int = 10) -> dict:
    """
    Wait for confirmations for all order_ids using a single receiver loop.
    Returns a mapping of order_id -> order update payload.
    """
    remaining = set(order_ids)
    found = {}

    async def listen_one():
        data = json.loads(await ws.recv())
        if data.get("action") == "update":
            for order in data.get("data", []):
                oid = order.get("orderId")
                if oid in remaining:
                    found[oid] = order
                    remaining.discard(oid)

    try:
        deadline = asyncio.get_event_loop().time() + timeout
        while remaining:
            time_left = deadline - asyncio.get_event_loop().time()
            if time_left <= 0:
                missing = ", ".join(list(remaining))
                raise Exception(f"Timeout waiting for confirmations for: {missing}")
            per_wait = min(1.0, time_left)
            await asyncio.wait_for(listen_one(), timeout=per_wait)
        return found
    except asyncio.TimeoutError:
        missing = ", ".join(list(remaining))
        raise Exception(f"Timeout waiting for confirmations for: {missing}")


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
    
    # 4. Place limit order(s) via REST using the signal details
    order_ids = place_rest_order(signal)
    
    # 5. Wait for confirmations for all created orders via WebSocket
    try:
        confirmations = await wait_for_multiple_order_confirmations(ws, order_ids)
        print("Orders placed successfully:")
        for oid in order_ids:
            print(f" - {oid}: {confirmations.get(oid, {})}")
    except Exception as e:
        print("Order confirmation failed: ", e)

    print('------------------------------------------------------------------------------------')
    
    # (Optional) 6. Order cancellation logic.
    
    # Clean up WebSocket connection
    await ws.close()

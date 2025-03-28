import re

def parse_signal(message: str) -> dict:
    """
    Parses a Telegram trade signal message and extracts key trading parameters.

    Expected message format examples:
    Long Trade:
        "#PHB $PHB LONG TRADE
         ENTRY: 0.765
         TARGETS: 0.791 - 0.823 - 0.89
         STOPLOSS: 0.738"

    Short Trade:
        "#WIF $WIF SHORT TRADE
         ENTRY: 0.771 - 0.786
         TARGETS: 0.65 - 0.587
         STOPLOSS: 0.8025"

    Returns:
        A dictionary with the following keys:
        - ticker: e.g. "BTC"
        - trade_type: "LONG" or "SHORT"
        - entry: list of floats (one or more entry prices)
        - targets: list of floats (target prices)
        - stoploss: float (stop loss value)
    """
    data = {}
    message = message.strip()

    # Extract the ticker symbol (look for '#' first, then '$' if not found)
    ticker_match = re.search(r'#([A-Za-z0-9]+)', message)
    if not ticker_match:
        ticker_match = re.search(r'\$([A-Za-z0-9]+)', message)
    data['ticker'] = ticker_match.group(1).upper() if ticker_match else None

    # Identify the trade type (LONG or SHORT)
    trade_type_match = re.search(r'\b(LONG|SHORT)\b', message, re.IGNORECASE)
    data['trade_type'] = trade_type_match.group(1).upper() if trade_type_match else None

    # Helper function to extract values from lines like "ENTRY:" or "TARGETS:".
    # The colon is made optional using :?
    def extract_values(label: str):
        if label.upper() == "TARGETS":
            pattern = r'TARGETS?:\s*:?\s*([\d\.\-\s,]+)'
        else:
            pattern = rf'{label}:?\s*([\d\.\-\s,]+)'
        match = re.search(pattern, message, re.IGNORECASE)
        if match:
            values = match.group(1).strip()
            return [float(x) for x in re.split(r'[\-\s,]+', values) if x]
        return None

    data['entry'] = extract_values("ENTRY")
    data['targets'] = extract_values("TARGETS")
    
    # Extract the stoploss value with an optional colon
    stoploss_match = re.search(r'STOPLOSS:?\s*([\d\.]+)', message, re.IGNORECASE)
    data['stoploss'] = float(stoploss_match.group(1)) if stoploss_match else None

    return data

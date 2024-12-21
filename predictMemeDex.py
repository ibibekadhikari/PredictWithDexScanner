import asyncio
import random
import aiohttp
from datetime import datetime
from termcolor import colored  # For colored output

# API endpoints
TOKEN_LIST_URL = "https://api.dexscreener.com/token-boosts/latest/v1"
TOKEN_DETAILS_URL = "https://api.dexscreener.com/latest/dex/tokens/{tokenAddresses}"

# Parameters
MONITOR_DURATION = 60  # Monitor duration in seconds
FETCH_INTERVAL = 10  # Interval between API requests in seconds
INITIAL_BALANCE = 200  # Starting balance in USD (SOL equivalent)
SELL_DROP_THRESHOLD = 0.95  # Sell if price drops below 95% of the bought price
SELL_GAIN_THRESHOLD = 1.10  # Sell if price exceeds 105% of the bought price

async def fetch_data(session, url):
    """
    Asynchronously fetch data from the given URL.
    """
    async with session.get(url) as response:
        if response.status != 200:
            raise Exception(f"Failed to fetch data: {response.status}")
        return await response.json()

async def get_random_tokens(session):
    """
    Fetch the token list and randomly select 15 token addresses.
    """
    data = await fetch_data(session, TOKEN_LIST_URL)
    if isinstance(data, list):
        tokens = random.sample(data, min(len(data), 15))  # Select up to 15 random tokens
    else:
        raise Exception("Unexpected response format. Expected a list of tokens.")
    return tokens

async def evaluate_token(token, session):
    """
    Fetch token details and evaluate based on price, market cap, liquidity, and volume.
    Returns None if token data is invalid or unsuitable.
    """
    try:
        # Fetch token details
        token_url = TOKEN_DETAILS_URL.format(tokenAddresses=token['tokenAddress'])
        token_data = await fetch_data(session, token_url)

        # Ensure 'pairs' exists and is non-empty
        if "pairs" not in token_data or not token_data["pairs"]:
            print(f"Token {token.get('tokenAddress')} has no pairs data.")
            return None

        # Extract details from token data
        pair = token_data["pairs"][0]
        
        # Extract liquidity and volume, defaulting to 0 if missing
        liquidity = float(pair.get("liquidity", {}).get("usd", 0))  # Handle missing liquidity
        volume_24h = float(pair.get("volume", {}).get("h24", 0))  # Handle missing volume
        txns = pair.get("txns", {}).get("h24", {})
        buys_24h = float(txns.get("buys", 0))
        sells_24h = float(txns.get("sells", 0))
        
        # Calculate buy/sell ratio, avoiding division by zero
        buy_sell_ratio = buys_24h / max(sells_24h, 1)  # Prevent division by zero
        
        # Get FDV and handle if it's missing (default to 1)
        fdv = float(pair.get("fdv", 1))
        
        # Price change (24h) and handle missing data
        price_change_24h = float(pair.get("priceChange", {}).get("h24", 0))

        # Market cap (if missing, use FDV as fallback)
        market_cap = float(pair.get("marketCap", fdv))
        print(f"MCAP {market_cap} FDV {fdv}")

        # Calculate score based on the factors
        score = (
            liquidity * 0.4 +          # Liquidity weight
            volume_24h * 0.3 +         # Volume weight
            buy_sell_ratio * 0.2 +      # Buy/Sell ratio weight
            price_change_24h * 0.1      # Price change momentum weight
        ) / max(fdv, 1)  # Normalize by FDV

        # Ensure the score is a float and store it in the token dictionary
        token["score"] = float(score)

        # Return the relevant details: tokenAddress, tokenName, and score
        return {
            "tokenAddress": token["tokenAddress"],
            "tokenName": token_data["pairs"][0]["baseToken"]["symbol"],
            "score": score
        }

    except (KeyError, ZeroDivisionError, TypeError, ValueError) as e:
        # Log the error for debugging purposes (you can enhance this as needed)
        print(f"Error evaluating token {token.get('tokenAddress')}: {e}")
        return None

async def monitor_token(token, session):
    """
    Monitor the price of the selected token and execute buy/sell logic.
    """
    buy_price = None
    purchased_amount = 0
    current_balance = INITIAL_BALANCE

    while True:
        try:
            # Fetch token details for monitoring price and making buy/sell decisions
            token_url = TOKEN_DETAILS_URL.format(tokenAddresses=token['tokenAddress'])
            token_data = await fetch_data(session, token_url)

            # Extract price in USD
            token_name = token_data["pairs"][0]["baseToken"]["symbol"]
            price = float(token_data["pairs"][0]["priceUsd"])

            print(f"Monitoring {token_name}: Current price ${price:.10f}")

            # Initial buy
            if buy_price is None:
                buy_price = price
                purchased_amount = current_balance / buy_price
                print(f"Bought {token_name} at ${buy_price:.10f}")

            # Sell conditions
            if price <= buy_price * SELL_DROP_THRESHOLD or price >= buy_price * SELL_GAIN_THRESHOLD:
                profit = (price - buy_price) * purchased_amount
                current_balance += profit

                color = "red" if profit < 0 else "green"
                print(colored(f"Sold {token_name} at ${price:.10f}. Profit/Loss: ${profit:.4f}", color))
                return

            await asyncio.sleep(FETCH_INTERVAL)

        except Exception as e:
            print(f"Error monitoring token: {e}")
            return

async def main():
    async with aiohttp.ClientSession() as session:
        # Fetch and evaluate tokens
        random_tokens = await get_random_tokens(session)

        # Evaluate each token and filter out invalid tokens
        evaluated_tokens = []
        for token in random_tokens:
            evaluated_token = await evaluate_token(token, session)
            if evaluated_token:
                evaluated_tokens.append(evaluated_token)

        if not evaluated_tokens:
            print("No valid tokens found.")
            return

        # Print the list of evaluated tokens with their score
        print("\nEvaluated Tokens:")
        for token in evaluated_tokens:
            print(f"Token Address: {token['tokenAddress']} | Token Name: {token['tokenName']} | Score: {token['score']:.4f}")

        # Select the best token based on score
        best_token = max(evaluated_tokens, key=lambda x: x["score"])
        print(f"\nBest token selected: {best_token['tokenName']} ({best_token['tokenAddress']})")

        # Monitor the selected token
        await monitor_token(best_token, session)

if __name__ == "__main__":
    asyncio.run(main())

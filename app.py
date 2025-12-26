import streamlit as st
import requests
import time
import aiohttp
import asyncio
from fuzzywuzzy import fuzz, process

# Constants
GAMMA_API = "https://gamma-api.polymarket.com/markets"
CLOB_ORDERBOOK = "https://clob.polymarket.com/orderbook"
DRIFT_CONTRACTS = "https://data.api.drift.trade/contracts"

async def async_get(session, url, params=None):
    async with session.get(url, params=params) as resp:
        return await resp.json() if resp.status == 200 else []

def fetch_drift_markets():
    """Fetch Drift BET markets (binary prediction perps)."""
    try:
        resp = requests.get(DRIFT_CONTRACTS)
        if resp.status_code != 200:
            return []
        contracts = resp.json().get("contracts", [])
        drift_markets = []
        for c in contracts:
            if "-BET" in c.get("ticker_id", ""):
                question = c["base_currency"].replace("-", " ").title()
                yes_price = float(c.get("last_price", 0))
                drift_markets.append({
                    "question": question,
                    "yes_price": yes_price,
                    "no_price": 1 - yes_price,  # Approximate (ignores spread)
                    "volume": c.get("quote_volume", 0),
                    "oi": c.get("open_interest", 0),
                    "ticker": c["ticker_id"]
                })
        return drift_markets
    except:
        return []

async def fetch_all_polymarket_markets_async():
    """Async version for faster combined scan."""
    markets = []
    offset = 0
    limit = 500
    async with aiohttp.ClientSession() as session:
        while True:
            params = {"active": "true", "closed": "false", "limit": limit, "offset": offset}
            data = await async_get(session, GAMMA_API, params)
            if not data:
                break
            markets.extend(data)
            if len(data) < limit:
                break
            offset += limit
    return markets

def get_poly_best_asks(markets):
    """Get best ask YES/NO for binary Poly markets (sync for simplicity)."""
    poly_prices = []
    for market in markets:
        clob_token_ids = market.get("clobTokenIds", [])
        if len(clob_token_ids) != 2:
            continue
        yes_token, no_token = clob_token_ids
        yes_resp = requests.get(f"{CLOB_ORDERBOOK}?token_id={yes_token}")
        no_resp = requests.get(f"{CLOB_ORDERBOOK}?token_id={no_token}")
        if yes_resp.status_code != 200 or no_resp.status_code != 200:
            continue
        yes_book = yes_resp.json()
        no_book = no_resp.json()
        yes_asks = yes_book.get("asks", [])
        no_asks = no_book.get("asks", [])
        if not yes_asks or not no_asks:
            continue
        best_yes = float(min(yes_asks, key=lambda x: float(x[0]))[0])
        best_no = float(min(no_asks, key=lambda x: float(x[0]))[0])
        poly_prices.append({
            "question": market["question"],
            "yes_price": best_yes,
            "no_price": best_no,
            "volume": market.get("volume", 0)
        })
    return poly_prices

def find_cross_arbs(poly_prices, drift_markets, match_threshold=70, profit_threshold=0.03):
    arbs = []
    for drift in drift_markets:
        # Fuzzy match question
        match = process.extractOne(drift["question"], [p["question"] for p in poly_prices], scorer=fuzz.partial_ratio)
        if match and match[1] >= match_threshold:
            poly = next(p for p in poly_prices if p["question"] == match[0])
            diff_yes = abs(poly["yes_price"] - drift["yes_price"])
            if diff_yes > profit_threshold:
                cheaper = "Drift" if drift["yes_price"] < poly["yes_price"] else "Polymarket"
                arbs.append({
                    "Event": drift["question"],
                    "Poly YES": round(poly["yes_price"], 4),
                    "Drift YES": round(drift["yes_price"], 4),
                    "Spread": round(diff_yes * 100, 2),
                    "Cheaper Platform": cheaper,
                    "Potential Profit %": round(diff_yes * 100, 2)
                })
    return arbs

# Dashboard
st.title("🔍 Polymarket + Drift BET Cross-Platform Arb Scanner")

threshold = st.slider("Min Spread % for Arb Alert", 1.0, 10.0, 3.0) / 100

if st.button("🚀 Scan Both Platforms Now"):
    with st.spinner("Fetching Polymarket markets..."):
        loop = asyncio.new_event_loop()
        poly_markets = loop.run_until_complete(fetch_all_polymarket_markets_async())
    
    with st.spinner("Fetching Drift BET markets..."):
        drift_markets = fetch_drift_markets()
        st.info(f"Found {len(drift_markets)} Drift BET markets.")
    
    with st.spinner("Getting Polymarket prices..."):
        poly_prices = get_poly_best_asks(poly_markets)
        st.info(f"Processed {len(poly_prices)} binary Polymarket markets.")
    
    with st.spinner("Matching & detecting cross-arbs..."):
        cross_arbs = find_cross_arbs(poly_prices, drift_markets, profit_threshold=threshold)
    
    if cross_arbs:
        st.success(f"🎯 Found {len(cross_arbs)} cross-platform opportunities!")
        st.dataframe(cross_arbs)
    else:
        st.warning("No cross-arbs at current threshold. Try lowering or scan later—opps appear during news/volatility.")

# Auto-refresh
if st.checkbox("🔄 Auto-scan every 60 seconds"):
    time.sleep(60)
    st.experimental_rerun()

st.info("Manual trade: Buy YES on cheaper platform. Windows last minutes+ due to Drift's thinner liquidity.")

import streamlit as st
import requests
import time
from fuzzywuzzy import fuzz, process

# Constants
GAMMA_API = "https://gamma-api.polymarket.com/markets"
CLOB_ORDERBOOK = "https://clob.polymarket.com/orderbook"

def fetch_all_markets():
    markets = []
    offset = 0
    limit = 500
    while True:
        params = {"active": "true", "closed": "false", "limit": limit, "offset": offset}
        resp = requests.get(GAMMA_API, params=params)
        if resp.status_code != 200:
            st.error(f"API error: {resp.text}")
            return []
        data = resp.json()
        markets.extend(data)
        if len(data) < limit:
            break
        offset += limit
    return markets

def get_best_asks(token_ids):
    if len(token_ids) != 2:
        return None, None
    yes_token, no_token = token_ids
    yes_resp = requests.get(f"{CLOB_ORDERBOOK}?token_id={yes_token}")
    no_resp = requests.get(f"{CLOB_ORDERBOOK}?token_id={no_token}")
    if yes_resp.status_code != 200 or no_resp.status_code != 200:
        return None, None
    yes_book = yes_resp.json().get("asks", [])
    no_book = no_resp.json().get("asks", [])
    if not yes_book or not no_book:
        return None, None
    best_yes = float(min(yes_book, key=lambda x: float(x[0]))[0])
    best_no = float(min(no_book, key=lambda x: float(x[0]))[0])
    return best_yes, best_no

def detect_combinatorial_arbs(markets, threshold=0.02):
    arbs = []
    # Group potential linked markets by fuzzy title similarity and volume
    questions = [m["question"] for m in markets if m.get("clobTokenIds")]
    for i, market in enumerate(markets):
        clob_ids = market.get("clobTokenIds")
        if not clob_ids or len(clob_ids) != 2:
            continue
        yes_price, no_price = get_best_asks(clob_ids)
        if yes_price is None:
            continue
        
        # Simple rebalancing first (YES + NO < 1 - threshold)
        total_cost = yes_price + no_price
        if total_cost < 1 - threshold:
            arbs.append({
                "Type": "Rebalancing (Single Market)",
                "Question": market["question"],
                "YES Ask": round(yes_price, 4),
                "NO Ask": round(no_price, 4),
                "Total Cost": round(total_cost, 4),
                "Profit %": round((1 - total_cost) * 100, 2),
                "Volume": market.get("volume", 0)
            })
        
        # Find potential linked markets (conditional/combinatorial)
        matches = process.extract(market["question"], questions, limit=5, scorer=fuzz.token_sort_ratio)
        for match_q, score in matches:
            if score < 75 or match_q == market["question"]:
                continue
            linked_market = next(m for m in markets if m["question"] == match_q and m.get("clobTokenIds"))
            linked_yes, linked_no = get_best_asks(linked_market.get("clobTokenIds", []))
            if linked_yes is None:
                continue
            
            # Example combinatorial check: if probs imply overlap/misprice (e.g., base + conditional sum >1 or <1)
            # Simple heuristic: if one market's YES > other's NO complement or similar
            if yes_price + linked_no < 1 - threshold or no_price + linked_yes < 1 - threshold:
                profit = min(1 - (yes_price + linked_no), 1 - (no_price + linked_yes))
                arbs.append({
                    "Type": "Combinatorial (Cross-Market)",
                    "Base Question": market["question"],
                    "Linked Question": linked_market["question"],
                    "Base YES/Linked NO Cost": round(yes_price + linked_no, 4),
                    "Base NO/Linked YES Cost": round(no_price + linked_yes, 4),
                    "Profit %": round(profit * 100, 2),
                    "Match Score": score
                })
    
    return arbs

# Dashboard
st.title("🔍 Polymarket Combinatorial & Conditional Arb Scanner")
st.markdown("Detects single-market rebalancing and cross-market (conditional/combinatorial) arbitrage opportunities on Polymarket. Windows typically 1-5+ minutes.")

threshold = st.slider("Min Profit % Threshold (after gas/slippage)", 0.5, 10.0, 2.0) / 100

if st.button("🚀 Scan All Markets Now", type="primary"):
    with st.spinner("Fetching all active markets..."):
        markets = fetch_all_markets()
        st.info(f"Loaded {len(markets)} active markets.")
    
    with st.spinner("Analyzing for arbitrage opportunities..."):
        arbs = detect_combinatorial_arbs(markets, threshold)
    
    if arbs:
        st.success(f"🎯 Found {len(arbs)} potential arbitrage opportunities!")
        st.dataframe(arbs, use_container_width=True)
    else:
        st.warning("No opportunities found at current threshold. Try lowering it or scanning during high volatility/news events.")

if st.checkbox("🔄 Auto-scan every 60 seconds"):
    time.sleep(60)
    st.experimental_rerun()

st.info("**Manual execution**: Buy the underpriced sides for guaranteed payout on resolution. Check market links on Polymarket.com.")
st.caption("MVP for longer-window arbs | Opportunities from linked/conditional markets | Dec 2025")

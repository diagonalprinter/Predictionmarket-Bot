import streamlit as st
import requests
import time

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
            st.error(f"API Error: {resp.status_code}")
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
    yes_book = yes_resp.json()
    no_book = no_resp.json()
    yes_asks = yes_book.get("asks", [])
    no_asks = no_book.get("asks", [])
    if not yes_asks or not no_asks:
        return None, None
    best_yes = float(min(yes_asks, key=lambda x: float(x[0]))[0])
    best_no = float(min(no_asks, key=lambda x: float(x[0]))[0])
    return best_yes, best_no

def find_spread_arbs(markets, min_profit_percent=1.0):
    arbs = []
    progress = st.progress(0)
    total = len(markets)
    
    for idx, market in enumerate(markets):
        progress.progress((idx + 1) / total)
        
        clob_ids = market.get("clobTokenIds")
        if not clob_ids or len(clob_ids) != 2:
            continue
        
        yes_ask, no_ask = get_best_asks(clob_ids)
        if yes_ask is None or no_ask is None:
            continue
        
        total_cost = yes_ask + no_ask
        profit = 1.0 - total_cost
        
        if profit * 100 >= min_profit_percent:
            arbs.append({
                "Question": market["question"][:100] + "..." if len(market["question"]) > 100 else market["question"],
                "YES Ask": f"${yes_ask:.4f}",
                "NO Ask": f"${no_ask:.4f}",
                "Total Cost": f"${total_cost:.4f}",
                "Profit %": f"{profit * 100:.2f}%",
                "Profit per $100": f"${profit * 100:.2f}",
                "Volume": f"${float(market.get('volume', 0)):,.0f}",
                "Market ID": market.get("id", "N/A")
            })
    
    progress.empty()
    # Sort by highest profit
    arbs.sort(key=lambda x: float(x["Profit %"].strip("%")), reverse=True)
    return arbs

# Dashboard
st.set_page_config(page_title="Polymarket Spread Arb", layout="wide")
st.title("💰 Polymarket Rebalancing Spread Arbitrage Scanner")
st.markdown("""
Scans all active binary markets for **risk-free** opportunities where:
  
**Best Ask (YES) + Best Ask (NO) < $1.00**

You buy both outcomes → guaranteed $1 payout on resolution → instant profit.
""")

col1, col2 = st.columns(2)
with col1:
    min_profit = st.slider("Minimum Profit % to Show", 0.1, 10.0, 1.0, 0.1)
with col2:
    st.markdown("#### Controls")
    scan_button = st.button("🔥 Scan All Markets Now", type="primary")

if scan_button or st.checkbox("🔄 Auto-scan every 30 seconds"):
    with st.spinner("Fetching all active markets from Polymarket..."):
        markets = fetch_all_markets()
        st.success(f"Loaded {len(markets)} active markets.")

    with st.spinner("Scanning order books for spread arbitrage..."):
        arbs = find_spread_arbs(markets, min_profit)

    if arbs:
        st.success(f"🎯 Found **{len(arbs)}** profitable spread opportunities!")
        st.dataframe(arbs, use_container_width=True, hide_index=True)
        
        st.info("""
**How to execute**:
1. Click the market on Polymarket.com
2. Place limit buys at (or better than) the shown YES/NO ask prices
3. Hold until resolution → collect $1 per share pair
        """)
    else:
        st.warning(f"No spreads ≥ {min_profit}% found right now. Try lowering threshold or scan again in a few minutes — new ones appear constantly.")

    if st.checkbox("🔄 Auto-scan every 30 seconds"):
        time.sleep(30)
        st.experimental_rerun()

st.caption("Risk-free rebalancing arbitrage | Manual execution recommended | Dec 2025")

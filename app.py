import streamlit as st
import requests
import time

# ======================
# Constants
# ======================
GAMMA_API = "https://gamma-api.polymarket.com/markets"
CLOB_ORDERBOOK = "https://clob.polymarket.com/orderbook"

# ======================
# Helper Functions
# ======================
def fetch_all_markets():
    """Fetch all active, open markets from Polymarket Gamma API."""
    markets = []
    offset = 0
    limit = 500  # Max per request
    
    with st.spinner("Fetching markets from Polymarket..."):
        while True:
            params = {
                "active": "true",
                "closed": "false",
                "limit": limit,
                "offset": offset
            }
            response = requests.get(GAMMA_API, params=params)
            
            if response.status_code != 200:
                st.error(f"Error fetching markets: {response.status_code} – {response.text}")
                return []
            
            data = response.json()
            if not data:
                break
                
            markets.extend(data)
            st.info(f"Fetched {len(data)} markets (total: {len(markets)})")
            
            if len(data) < limit:
                break
                
            offset += limit
            
    st.success(f"Successfully loaded {len(markets)} active markets.")
    return markets


def detect_arbitrage(markets, threshold=0.02):
    """Scan binary markets for arb: best_ask_yes + best_ask_no < 1 - threshold."""
    arbs = []
    total_scanned = 0
    
    progress_bar = st.progress(0)
    
    for idx, market in enumerate(markets):
        progress_bar.progress((idx + 1) / len(markets))
        
        total_scanned += 1
        
        # Only consider binary markets with exactly 2 outcomes
        clob_token_ids = market.get("clobTokenIds", [])
        if len(clob_token_ids) != 2:
            continue
            
        yes_token, no_token = clob_token_ids
        
        # Fetch order books directly via REST
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
        
        # Best (lowest) ask price for each side
        best_ask_yes = float(min(yes_asks, key=lambda x: float(x[0]))[0])
        best_ask_no = float(min(no_asks, key=lambda x: float(x[0]))[0])
        
        total_cost = best_ask_yes + best_ask_no
        
        if total_cost < 1 - threshold:
            profit_per_dollar = 1 - total_cost
            arbs.append({
                "Question": market["question"],
                "YES Price": round(best_ask_yes, 4),
                "NO Price": round(best_ask_no, 4),
                "Total Cost": round(total_cost, 4),
                "Profit %": round(profit_per_dollar * 100, 2),
                "Est. Profit/$100": round(profit_per_dollar * 100, 2),
                "Volume": f"${float(market.get('volume', 0)):,.0f}",
                "Market ID": market.get("id", "N/A")
            })
    
    progress_bar.empty()
    return arbs


# ======================
# Streamlit Dashboard
# ======================
st.set_page_config(page_title="Polymarket Arb Scanner", layout="wide")
st.title("🔍 Polymarket Arbitrage Scanner MVP")
st.markdown("Scans all active binary markets for YES + NO pricing inefficiencies (post-gas threshold).")

# Controls
col1, col2 = st.columns([1, 3])
with col1:
    threshold = st.slider(
        "Profit Threshold % (covers gas/slippage)",
        min_value=0.0,
        max_value=10.0,
        value=2.0,
        step=0.1,
        help="Only show opportunities with at least this % profit after estimated costs."
    ) / 100

with col2:
    st.markdown("#### Scan Controls")
    if st.button("🚀 Scan All Markets Now", type="primary"):
        markets = fetch_all_markets()
        if markets:
            with st.spinner("Analyzing order books for arbitrage..."):
                arbs = detect_arbitrage(markets, threshold)
            
            if arbs:
                st.success(f"🎯 Found {len(arbs)} arbitrage opportunities!")
                st.dataframe(arbs, use_container_width=True)
                
                # Download option
                st.download_button(
                    "Download Results as CSV",
                    data="\n".join([",".join(map(str, row.values())) for row in arbs]),
                    file_name=f"polymarket_arbs_{time.strftime('%Y%m%d_%H%M')}.csv",
                    mime="text/csv"
                )
            else:
                st.warning("No arbitrage opportunities found at current threshold. Try lowering it or scan again later.")

# Auto-refresh
if st.checkbox("🔄 Auto-refresh every 20 seconds (for monitoring)"):
    time.sleep(20)
    st.experimental_rerun()

# Execution Note
st.markdown("---")
st.header("📈 Execution")
st.info("""
**Auto-trading is not included in this cloud version** (to avoid key exposure and SDK issues).

**Manual execution recommended**:
1. Copy a market from the table above.
2. Go to Polymarket.com → find the market.
3. Place limit buys at the displayed YES/NO prices (or better).

**For auto-trading later**: We'll build a separate local Python script (using `py-clob-client` on your machine/VPS with Python 3.11) that can execute instantly when an arb is detected.
""")

st.caption("Built with ❤️ for prediction market edge hunters | Dec 2025")

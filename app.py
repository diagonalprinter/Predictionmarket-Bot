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

def scan_for_opportunities(markets, spread_threshold=0.02, combo_threshold=0.02, near_certain=0.95, rules_keywords=["if", "by", "or", "unless", "before"]):
    spread_arbs = []
    combo_arbs = []
    near_certain_opps = []
    rules_arbs = []
    
    questions = [m["question"] for m in markets if m.get("clobTokenIds")]
    progress = st.progress(0)
    total = len(markets)
    
    for idx, market in enumerate(markets):
        progress.progress((idx + 1) / total)
        
        clob_ids = market.get("clobTokenIds")
        if not clob_ids or len(clob_ids) != 2:
            continue
        
        yes_ask, no_ask = get_best_asks(clob_ids)
        if yes_ask is None:
            continue
        
        question = market["question"].lower()
        
        # 1. Spread/Rebalancing Arb
        total_cost = yes_ask + no_ask
        if total_cost < 1 - spread_threshold:
            profit = 1 - total_cost
            spread_arbs.append({
                "Question": question,
                "YES Ask": yes_ask,
                "NO Ask": no_ask,
                "Total Cost": total_cost,
                "Profit %": profit * 100,
                "Volume": market.get("volume", 0)
            })
        
        # 2. Combinatorial/Cross-Market Arb
        matches = process.extract(question, questions, limit=5, scorer=fuzz.token_sort_ratio)
        for match_q, score in matches:
            if score < 75 or match_q.lower() == question:
                continue
            linked = next(m for m in markets if m["question"].lower() == match_q.lower())
            linked_yes, linked_no = get_best_asks(linked.get("clobTokenIds", []))
            if linked_yes is None:
                continue
            if yes_ask + linked_no < 1 - combo_threshold or no_ask + linked_yes < 1 - combo_threshold:
                profit = min(1 - (yes_ask + linked_no), 1 - (no_ask + linked_yes))
                combo_arbs.append({
                    "Base Question": question,
                    "Linked Question": linked["question"],
                    "Profit %": profit * 100,
                    "Match Score": score
                })
        
        # 3. Near-Certain Outcomes
        if yes_ask <= 1 - near_certain or no_ask <= 1 - near_certain:
            cheap_side = "YES" if yes_ask <= 1 - near_certain else "NO"
            cheap_price = yes_ask if cheap_side == "YES" else no_ask
            profit = (1 - cheap_price) * 100
            near_certain_opps.append({
                "Question": question,
                "Cheap Side": cheap_side,
                "Price": cheap_price,
                "Implied Prob %": (1 - cheap_price) * 100 if cheap_side == "NO" else cheap_price * 100,
                "Profit %": profit,
                "Volume": market.get("volume", 0)
            })
        
        # 4. Rules-Based Arb (Ambiguous)
        if any(word in question for word in rules_keywords):
            rules_arbs.append({
                "Question": question,
                "Potential Ambiguity": ", ".join(word for word in rules_keywords if word in question),
                "YES Ask": yes_ask,
                "NO Ask": no_ask,
                "Volume": market.get("volume", 0)
            })
    
    progress.empty()
    return spread_arbs, combo_arbs, near_certain_opps, rules_arbs

# Dashboard
st.set_page_config(page_title="Polymarket Arb MVP", layout="wide")
st.title("🔍 Polymarket Arbitrage MVP Dashboard")
st.markdown("Scans for spread, combinatorial, near-certain, and rules-based opportunities. Windows vary by type (seconds to minutes+).")

col1, col2 = st.columns(2)
with col1:
    spread_thresh = st.slider("Spread Threshold %", 0.5, 5.0, 2.0) / 100
    combo_thresh = st.slider("Combinatorial Threshold %", 0.5, 5.0, 2.0) / 100
with col2:
    near_cert = st.slider("Near-Certain Prob %", 90.0, 99.0, 95.0) / 100
    rules_kw = st.text_input("Rules Ambiguity Keywords (comma-separated)", "if,by,or,unless,before").split(",")

if st.button("🚀 Scan All Opportunities Now", type="primary"):
    with st.spinner("Fetching markets..."):
        markets = fetch_all_markets()
        st.info(f"Loaded {len(markets)} markets.")
    
    with st.spinner("Scanning for all arb types..."):
        spread, combo, near, rules = scan_for_opportunities(markets, spread_thresh, combo_thresh, near_cert, [kw.strip().lower() for kw in rules_kw])
    
    if spread:
        st.success(f"Found {len(spread)} Spread Arbs!")
        st.table(spread)
    else:
        st.warning("No Spread Arbs.")
    
    if combo:
        st.success(f"Found {len(combo)} Combinatorial Arbs!")
        st.table(combo)
    else:
        st.warning("No Combinatorial Arbs.")
    
    if near:
        st.success(f"Found {len(near)} Near-Certain Opps!")
        st.table(near)
    else:
        st.warning("No Near-Certain Opps.")
    
    if rules:
        st.success(f"Found {len(rules)} Potential Rules Arbs (manual review needed)!")
        st.table(rules)
    else:
        st.warning("No Rules Arbs flagged.")

if st.checkbox("🔄 Auto-scan every 60s"):
    time.sleep(60)
    st.experimental_rerun()

st.info("Manual execution: Buy flagged sides on Polymarket.com. For rules arbs, research resolution disputes.")

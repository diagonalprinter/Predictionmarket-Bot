import streamlit as st
import requests
import time
from py_clob_client.client import ClobClient
from py_clob_client.clob_types import OrderArgs, OrderType
from py_clob_client.constants import BUY  
from py_clob_client.constants import GTC

# Constants
GAMMA_API = "https://gamma-api.polymarket.com/markets"
CLOB_HOST = "https://clob.polymarket.com"
CHAIN_ID = 137  # Polygon

# Read-only client for public data
public_client = ClobClient(CLOB_HOST)

def fetch_all_markets():
    markets = []
    offset = 0
    limit = 500
    while True:
        params = {"active": "true", "closed": "false", "limit": limit, "offset": offset}
        resp = requests.get(GAMMA_API, params=params)
        if resp.status_code != 200:
            st.error(f"Gamma API error: {resp.status_code} - {resp.text}")
            return []
        data = resp.json()
        markets.extend(data)
        if len(data) < limit:
            break
        offset += limit
    return markets

def detect_arbitrage(markets, threshold=0.02):
    arbs = []
    for market in markets:
        clob_token_ids = market.get("clobTokenIds", [])
        if len(clob_token_ids) != 2:
            continue  # Skip non-binary
        yes_token, no_token = clob_token_ids
        
        yes_book = public_client.get_order_book(yes_token)
        no_book = public_client.get_order_book(no_token)
        
        yes_asks = yes_book.get("asks", [])
        no_asks = no_book.get("asks", [])
        if not yes_asks or not no_asks:
            continue
        
        best_ask_yes = float(yes_asks[0][0])
        best_ask_no = float(no_asks[0][0])
        
        total_cost = best_ask_yes + best_ask_no
        if total_cost < 1 - threshold:
            profit = 1 - total_cost
            arbs.append({
                "question": market["question"],
                "yes_token": yes_token,
                "no_token": no_token,
                "best_ask_yes": best_ask_yes,
                "best_ask_no": best_ask_no,
                "total_cost": total_cost,
                "profit_per_dollar": profit,
                "volume": market.get("volume", 0),
            })
    return arbs

st.title("Polymarket Arb Bot MVP")

st.header("Arbitrage Scanner")
threshold = st.slider("Profit Threshold (after gas/slippage)", 0.0, 0.1, 0.02, 0.005)

if st.button("Scan Markets Now"):
    with st.spinner("Fetching all active markets..."):
        markets = fetch_all_markets()
        st.info(f"Fetched {len(markets)} active markets.")
    with st.spinner("Scanning for arbs..."):
        arbs = detect_arbitrage(markets, threshold)
    if arbs:
        st.success(f"Found {len(arbs)} arbitrage opportunities!")
        st.dataframe(arbs)
    else:
        st.warning("No opportunities found right now. Try a lower threshold or scan again.")

if st.checkbox("Auto-scan every 15 seconds (for monitoring)"):
    time.sleep(15)
    st.experimental_rerun()

st.header("Execution (Use dummy wallet!)")
st.warning("Private key is loaded from secrets - never commit it to GitHub!")

if "arbs" not in locals():
    arbs = []

if arbs:
    selected_question = st.selectbox("Select market to arbitrage", [a["question"] for a in arbs])
    usdc_amount = st.number_input("Total USDC to spend (split between YES/NO)", min_value=1.0, value=10.0)

    if st.button("Execute Arbitrage"):
        try:
            private_key = st.secrets["polymarket"]["private_key"]
            funder = st.secrets["polymarket"].get("funder_address", None)
            sig_type = st.secrets["polymarket"].get("signature_type", 1)
        except:
            st.error("Secrets not configured! Add to .streamlit/secrets.toml locally or in Cloud settings.")
            st.stop()

        arb = next(a for a in arbs if a["question"] == selected_question)

        with st.spinner("Authenticating wallet..."):
            auth_client = ClobClient(
                CLOB_HOST,
                key=private_key,
                chain_id=CHAIN_ID,
                signature_type=sig_type,
                funder=funder
            )
            auth_client.set_api_creds(auth_client.create_or_derive_api_creds())

        yes_size = (usdc_amount / 2) / arb["best_ask_yes"]
        no_size = (usdc_amount / 2) / arb["best_ask_no"]

        try:
            # YES order
            yes_args = OrderArgs(token_id=arb["yes_token"], price=arb["best_ask_yes"], size=yes_size, side=BUY)
            signed_yes = auth_client.create_order(yes_args)
            resp_yes = auth_client.post_order(signed_yes, OrderType.GTC)
            st.json(resp_yes)

            # NO order
            no_args = OrderArgs(token_id=arb["no_token"], price=arb["best_ask_no"], size=no_size, side=BUY)
            signed_no = auth_client.create_order(no_args)
            resp_no = auth_client.post_order(signed_no, OrderType.GTC)
            st.json(resp_no)

            st.success("Orders placed successfully!")
        except Exception as e:
            st.error(f"Trade error: {e}")

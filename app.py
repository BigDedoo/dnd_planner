import streamlit as st
import datetime
import pandas as pd

# --- PAGE CONFIGURATION ---
st.set_page_config(page_title="DnD Planner", page_icon="🎲", layout="wide")

# --- DATABASE SIMULATION (Session State) ---
# In the final version, this will be replaced by Supabase or Firebase
if 'disponibilites' not in st.session_state:
    st.session_state.disponibilites = [] # List of dictionaries {'user': ..., 'date': ..., 'status': ...}

# Patient List
PLAYERS = ["Me (Admin)", "Alice", "Bob", "Charlie", "David"]

# --- SIDEBAR: LOGIN ---
with st.sidebar:
    st.header("👤 Login")
    user = st.selectbox("Who are you?", PLAYERS)
    st.divider()
    st.info(f"Logged in as: **{user}**")

# --- TITLE ---
st.title("🎲 DnD Session Planner")
st.markdown("Select your availability dates for the coming month.")

# --- DATE SELECTION (Player View) ---
col1, col2 = st.columns([1, 2])

with col1:
    st.subheader("📅 My Availabilities")
    # Simple date selector
    d = st.date_input("Pick a date", datetime.date.today())
    
    # Action buttons
    c1, c2 = st.columns(2)
    if c1.button("✅ Available", use_container_width=True):
        st.session_state.disponibilites.append({'user': user, 'date': d, 'status': 'Available'})
        st.success(f"Availability added for {d}")
        
    if c2.button("❌ Not Available", use_container_width=True):
        # Remove existing availabilities for this day/user
        st.session_state.disponibilites = [
            x for x in st.session_state.disponibilites 
            if not (x['user'] == user and x['date'] == d)
        ]
        st.warning(f"Removed for {d}")

    # Small personal recap
    st.write("---")
    st.caption("My saved dates:")
    mes_dates = [x['date'] for x in st.session_state.disponibilites if x['user'] == user]
    if mes_dates:
        st.write(sorted(list(set(mes_dates))))
    else:
        st.write("No dates selected.")

# --- GROUP DASHBOARD (Admin/Global View) ---
with col2:
    st.subheader("⚔️ Group Availabilities")
    
    if st.session_state.disponibilites:
        # Data transformation for display
        df = pd.DataFrame(st.session_state.disponibilites)
        
        if not df.empty:
            # Count how many people are available per day
            recap = df.groupby('date')['user'].unique().reset_index()
            recap['nombre_joueurs'] = recap['user'].apply(len)
            recap['noms'] = recap['user'].apply(lambda x: ", ".join(x))
            
            # Display as interactive table
            st.dataframe(
                recap.style.background_gradient(subset=['nombre_joueurs'], cmap="Greens"),
                column_config={
                    "date": "Date",
                    "nombre_joueurs": st.column_config.ProgressColumn(
                        "Available", 
                        format="%d/5", 
                        min_value=0, 
                        max_value=len(PLAYERS)
                    ),
                    "noms": "Players Ready"
                },
                use_container_width=True,
                hide_index=True
            )
        else:
            st.info("Waiting for data...")
    else:
        st.info("No availabilities entered yet.")

# --- DM EXPLANATION ---
st.divider()
st.markdown("""
**How it works**
1. Each player "logs in" via the left menu.
2. They add their dates.
3. The dashboard on the right updates in real-time. 
*Dates where everyone is available will appear in dark green!*
""")
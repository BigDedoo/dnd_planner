import streamlit as st
import datetime
import pandas as pd
import calendar
import random

# --- PAGE CONFIGURATION ---
st.set_page_config(page_title="DnD Planner", page_icon="🎲", layout="wide")

# --- DATABASE SIMULATION (Session State) ---
if 'disponibilites' not in st.session_state:
    st.session_state.disponibilites = [] # List of {'group':..., 'user': ..., 'date': ..., 'status': ...}

# --- GROUPS CONFIGURATION ---
GROUPS = {
    "Group A (5 Players)": ["Alice", "Bob", "Charlie", "David", "Eve"],
    "Group B (4 Players)": ["Zara", "Xavier", "Yann", "Walter"]
}

# --- HELPER FUNCTIONS ---
def get_user_availability(group, user, date):
    """Returns the status string or None for a user on a given date."""
    for entry in st.session_state.disponibilites:
        # We now check group as well to be safe
        if entry.get('group') == group and entry['user'] == user and entry['date'] == date:
            return entry['status']
    return None

def toggle_availability(group, user, date):
    """Cycles through: None -> Available -> Maybe -> No -> None"""
    current = get_user_availability(group, user, date)
    
    # Remove existing entry if any
    st.session_state.disponibilites = [
        entry for entry in st.session_state.disponibilites
        if not (entry.get('group') == group and entry['user'] == user and entry['date'] == date)
    ]
    
    new_status = None
    if current is None:
        new_status = 'Available'
    elif current == 'Available':
        new_status = 'Maybe'
    elif current == 'Maybe':
        new_status = 'No'
    elif current == 'No':
        new_status = None # Back to empty
        
    if new_status:
        st.session_state.disponibilites.append({
            'group': group,
            'user': user, 
            'date': date, 
            'status': new_status
        })

def get_status_icon(status):
    if status == 'Available': return "✅"
    if status == 'Maybe': return "❓"
    if status == 'No': return "❌"
    return "⬜"

def generate_test_data():
    """Generates random data for January 2026 for all groups/players."""
    # Clear existing data
    st.session_state.disponibilites = []
    
    year = 2026
    month = 1
    num_days = calendar.monthrange(year, month)[1]
    
    for group_name, players in GROUPS.items():
        for player in players:
            for day in range(1, num_days + 1):
                # Randomize: 40% Available, 20% Maybe, 40% No
                r = random.random()
                status = 'No'
                if r < 0.4:
                    status = 'Available'
                elif r < 0.6: # 20% chance (0.4 to 0.6)
                    status = 'Maybe'
                
                # Always append, as we want full coverage
                date_obj = datetime.date(year, month, day)
                st.session_state.disponibilites.append({
                    'group': group_name,
                    'user': player,
                    'date': date_obj,
                    'status': status
                })

# --- SIDEBAR: LOGIN ---
with st.sidebar:
    st.header("👤 Login")
    
    # Group Selection
    selected_group_name = st.selectbox("Select Group", list(GROUPS.keys()))
    group_players = GROUPS[selected_group_name]
    
    # User Selection
    user = st.selectbox("Who are you?", group_players)
    
    st.divider()
    st.info(f"Group: **{selected_group_name}**\n\nPlayer: **{user}**")
    
    st.divider()
    if st.button("⚡ Generate Test Data (Jan)"):
        generate_test_data()
        st.rerun()

# --- TITLE ---
st.title(f"🎲 DnD Planner - {selected_group_name}")
st.markdown("Select your availability dates for the coming month.")

# --- CALENDAR & DASHBOARD LAYOUT ---
col1, col2 = st.columns([1, 1], gap="large")

with col1:
    st.subheader("📅 Availability Calendar")
    
    # Month/Year selection
    today = datetime.date.today()
    c_col1, c_col2 = st.columns(2)
    current_year = c_col1.number_input("Year", min_value=today.year, max_value=today.year+1, value=today.year)
    current_month = c_col2.selectbox("Month", range(1, 13), index=today.month-1, format_func=lambda x: calendar.month_name[x])
    
    # Calendar Grid
    cal = calendar.monthcalendar(current_year, current_month)
    
    # Weekday Headers
    cols = st.columns(7)
    days = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
    for i, day in enumerate(days):
        cols[i].markdown(f"**{day}**")
    
    # Calendar Days
    for week in cal:
        cols = st.columns(7)
        for i, day in enumerate(week):
            if day == 0:
                cols[i].write("") # Empty cell
            else:
                date_obj = datetime.date(current_year, current_month, day)
                status = get_user_availability(selected_group_name, user, date_obj)
                icon = get_status_icon(status)
                
                # We use the day number + icon as the label
                # Key must be unique per group/user context or just globally unique?
                # Using group name in key ensures uniqueness if switching groups
                btn_key = f"btn_{selected_group_name}_{current_year}_{current_month}_{day}"
                
                if cols[i].button(f"{day} {icon}", key=btn_key):
                    toggle_availability(selected_group_name, user, date_obj)
                    st.rerun()

    st.caption("Click to cycle: ⬜ -> ✅ Available -> ❓ Maybe -> ❌ No -> ⬜")

# --- GROUP DASHBOARD ---
with col2:
    st.subheader("⚔️ Group Status")
    
    if st.session_state.disponibilites:
        df = pd.DataFrame(st.session_state.disponibilites)
        
        # FILTER: Only show data for the CURRENT GROUP
        df = df[df['group'] == selected_group_name]
        
        if not df.empty:
            active_dates = df[df['status'].isin(['Available', 'Maybe'])]
            
            if not active_dates.empty:
                recap = active_dates.groupby('date').agg({
                    'user': lambda x: list(x),
                    'status': lambda x: list(x)
                }).reset_index()
                
                # Format for display
                def format_players(row):
                    players = []
                    for u, s in zip(row['user'], row['status']):
                        icon = "✅" if s == 'Available' else "❓"
                        players.append(f"{u} {icon}")
                    return ", ".join(players)
                
                recap['Attendees'] = recap.apply(format_players, axis=1)
                recap['Count'] = recap['user'].apply(len)
                
                recap = recap.sort_values(by=['Count', 'date'], ascending=[False, True])
                
                max_players = len(group_players)
                
                st.dataframe(
                    recap[['date', 'Attendees', 'Count']],
                    column_config={
                        "date": "Date",
                        "Count": st.column_config.ProgressColumn(
                            "Potential Players",
                            format=f"%d/{max_players}",
                            min_value=0,
                            max_value=max_players,
                        ),
                    },
                    hide_index=True,
                    use_container_width=True
                )
            else:
                 st.info(f"No active availabilities found for {selected_group_name}.")
        else:
            st.info("Waiting for data...")
    else:
        st.info("Start clicking dates on the calendar!")

# --- DM EXPLANATION ---
st.divider()
st.markdown("""
**How it works**
1. Select your **Group** and **Name**.
2. Click on dates in the calendar.
3. The dashboard shows availability only for your group.
""")
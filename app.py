import streamlit as st
import datetime
import pandas as pd
import calendar

# --- PAGE CONFIGURATION ---
st.set_page_config(page_title="DnD Planner", page_icon="🎲", layout="wide")

# --- DATABASE SIMULATION (Session State) ---
if 'disponibilites' not in st.session_state:
    st.session_state.disponibilites = [] # List of {'user': ..., 'date': ..., 'status': ...}

# Patient List
PLAYERS = ["Me (Admin)", "Alice", "Bob", "Charlie", "David"]

# --- HELPER FUNCTIONS ---
def get_user_availability(user, date):
    """Returns the status string or None for a user on a given date."""
    for entry in st.session_state.disponibilites:
        if entry['user'] == user and entry['date'] == date:
            return entry['status']
    return None

def toggle_availability(user, date):
    """Cycles through: None -> Available -> Maybe -> No -> None"""
    current = get_user_availability(user, date)
    
    # Remove existing entry if any
    st.session_state.disponibilites = [
        entry for entry in st.session_state.disponibilites
        if not (entry['user'] == user and entry['date'] == date)
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
        st.session_state.disponibilites.append({'user': user, 'date': date, 'status': new_status})

def get_status_icon(status):
    if status == 'Available': return "✅"
    if status == 'Maybe': return "❓"
    if status == 'No': return "❌"
    return "⬜"

# --- SIDEBAR: LOGIN ---
with st.sidebar:
    st.header("👤 Login")
    user = st.selectbox("Who are you?", PLAYERS)
    st.divider()
    st.info(f"Logged in as: **{user}**")

# --- TITLE ---
st.title("🎲 DnD Session Planner")
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
                status = get_user_availability(user, date_obj)
                icon = get_status_icon(status)
                
                # We use the day number + icon as the label
                # Key is crucial for Streamlit to distinguish buttons
                if cols[i].button(f"{day} {icon}", key=f"btn_{current_year}_{current_month}_{day}"):
                    toggle_availability(user, date_obj)
                    st.rerun() # Force refresh to show new state immediately

    # Small legend
    st.caption("Click to cycle: ⬜ -> ✅ Available -> ❓ Maybe -> ❌ No -> ⬜")

# --- GROUP DASHBOARD ---
with col2:
    st.subheader("⚔️ Group Status")
    
    if st.session_state.disponibilites:
        df = pd.DataFrame(st.session_state.disponibilites)
        
        # Filter for the selected month to keep dashboard relevant
        # (Optional: simplistic filtering or just show all)
        
        if not df.empty:
            # Aggregate data
            # We want to see who is Available/Maybe for each date
            
            # Pivot table might be cleaner or just grouping
            # Let's count 'Available' as 1, 'Maybe' as 0.5 for sorting? Or just display strings.
            
            # Filter only for "Available" or "Maybe" to show promising dates
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
                
                # Sort by Count desc, then Date asc
                recap = recap.sort_values(by=['Count', 'date'], ascending=[False, True])
                
                st.dataframe(
                    recap[['date', 'Attendees', 'Count']],
                    column_config={
                        "date": "Date",
                        "Count": st.column_config.ProgressColumn(
                            "Potential Players",
                            format="%d",
                            min_value=0,
                            max_value=len(PLAYERS),
                        ),
                    },
                    hide_index=True,
                    use_container_width=True
                )
            else:
                 st.info("No active availabilities found.")
        else:
            st.info("Waiting for data...")
    else:
        st.info("Start clicking dates on the calendar!")

# --- DM EXPLANATION ---
st.divider()
st.markdown("""
**How it works**
1. Select your user profile.
2. Click on dates in the calendar to toggle your status.
3. Check the dashboard to find the best date for the group.
""")
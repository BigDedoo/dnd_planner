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
if 'selected_date_details' not in st.session_state:
    st.session_state.selected_date_details = None

# --- GROUPS CONFIGURATION ---
GROUPS = {
    "Group A (5 Players)": ["Alice", "Bob", "Charlie", "David", "Eve"],
    "Group B (4 Players)": ["Zara", "Xavier", "Yann", "Walter"]
}

# --- HELPER FUNCTIONS ---
def get_user_availability(group, user, date):
    """Returns the status string or None for a user on a given date."""
    for entry in st.session_state.disponibilites:
        if entry.get('group') == group and entry['user'] == user and entry['date'] == date:
            return entry['status']
    return None

def toggle_availability(group, user, date):
    """Cycles through: None -> Available -> Maybe -> No -> None"""
    current = get_user_availability(group, user, date)
    
    # Remove existing
    st.session_state.disponibilites = [
        entry for entry in st.session_state.disponibilites
        if not (entry.get('group') == group and entry['user'] == user and entry['date'] == date)
    ]
    
    new_status = None
    if current is None: new_status = 'Available'
    elif current == 'Available': new_status = 'Maybe'
    elif current == 'Maybe': new_status = 'No'
    elif current == 'No': new_status = None 
        
    if new_status:
        st.session_state.disponibilites.append({
            'group': group, 'user': user, 'date': date, 'status': new_status
        })

def get_status_icon(status):
    if status == 'Available': return "✅"
    if status == 'Maybe': return "❓"
    if status == 'No': return "❌"
    return "⬜"

def generate_test_data():
    """Generates random data for January 2026 for all groups/players."""
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
                if r < 0.4: status = 'Available'
                elif r < 0.6: status = 'Maybe'
                
                date_obj = datetime.date(year, month, day)
                st.session_state.disponibilites.append({
                    'group': group_name, 'user': player, 'date': date_obj, 'status': status
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

# --- TITLE & CONTROLS ---
st.title(f"🎲 DnD Planner - {selected_group_name}")

# Move Date Controls to Top
c1, c2, c3 = st.columns([1, 1, 4])
today = datetime.date.today()
current_year = c1.number_input("Year", min_value=today.year, max_value=today.year+1, value=today.year)
current_month = c2.selectbox("Month", range(1, 13), index=today.month-1, format_func=lambda x: calendar.month_name[x])

st.divider()

# --- CALENDARS ---
col_left, col_right = st.columns([1, 1], gap="large")

# Common Calendar Data
cal = calendar.monthcalendar(current_year, current_month)
days_header = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]

# LEFT: PERSONAL INPUT
with col_left:
    st.subheader(f"📅 {user}'s Availability")
    
    # Headers
    h_cols = st.columns(7)
    for i, day in enumerate(days_header):
        h_cols[i].markdown(f"**{day}**")
        
    # Grid
    for week in cal:
        cols = st.columns(7)
        for i, day in enumerate(week):
            if day == 0:
                cols[i].write("")
            else:
                date_obj = datetime.date(current_year, current_month, day)
                status = get_user_availability(selected_group_name, user, date_obj)
                icon = get_status_icon(status)
                
                # Unique key: btn_input_GROUP_YEAR_MONTH_DAY
                btn_key = f"btn_input_{selected_group_name}_{current_year}_{current_month}_{day}"
                if cols[i].button(f"{day} {icon}", key=btn_key):
                    toggle_availability(selected_group_name, user, date_obj)
                    st.rerun()
    st.caption("Click to cycle: ⬜ -> ✅ -> ❓ -> ❌ -> ⬜")

# RIGHT: GROUP DASHBOARD
with col_right:
    st.subheader(f"⚔️ Team Overview")
    
    # Headers
    h_cols = st.columns(7)
    for i, day in enumerate(days_header):
        h_cols[i].markdown(f"**{day}**")
        
    # Pre-calculate data for efficiency
    # We need counts for each day in this month for this group
    stats_map = {}
    if st.session_state.disponibilites:
        df = pd.DataFrame(st.session_state.disponibilites)
        df_group = df[df['group'] == selected_group_name]
        
        if not df_group.empty:
            # Group by date and count
            # We want Available and Maybe counts
            # Filter for this month/year for optimization? Not strictly necessary with small data
            for _, row in df_group.iterrows():
                d = row['date']
                if d.year == current_year and d.month == current_month:
                    if d not in stats_map: stats_map[d] = {'Available': [], 'Maybe': [], 'No': []}
                    if row['status'] == 'Available':
                        stats_map[d]['Available'].append(row['user'])
                    elif row['status'] == 'Maybe':
                        stats_map[d]['Maybe'].append(row['user'])
                    elif row['status'] == 'No':
                        stats_map[d]['No'].append(row['user'])

    max_p = len(group_players)

    # Grid
    for week in cal:
        cols = st.columns(7)
        for i, day in enumerate(week):
            if day == 0:
                cols[i].write("")
            else:
                date_obj = datetime.date(current_year, current_month, day)
                
                # Get stats
                stats = stats_map.get(date_obj, {'Available': [], 'Maybe': [], 'No': []})
                count_ok = len(stats['Available'])
                count_maybe = len(stats['Maybe'])
                
                # Visual Indicator (Traffic Light)
                # Green if everyone available, Yellow if > half, Red otherwise
                # Or Green if count_ok == max_p
                
                label_icon = "⚪"
                if count_ok == max_p:
                    label_icon = "🟢" # Perfect
                elif count_ok >= (max_p / 2):
                    label_icon = "🟡" # Good
                elif count_ok > 0:
                    label_icon = "🟠" # Okay
                
                label = f"{day}\n{label_icon} {count_ok}/{max_p}"
                
                # Interactive Button for Details
                btn_key = f"btn_view_{selected_group_name}_{current_year}_{current_month}_{day}"
                if cols[i].button(label, key=btn_key):
                    st.session_state.selected_date_details = {
                        'date': date_obj,
                        'available': stats['Available'],
                        'maybe': stats['Maybe'],
                        'no': stats['No']
                    }
                    st.rerun()

# --- DETAILS SECTION ---
if st.session_state.selected_date_details:
    details = st.session_state.selected_date_details
    st.divider()
    st.markdown(f"### 🔎 Details for **{details['date'].strftime('%A %d %B %Y')}**")
    
    col_d1, col_d2, col_d3 = st.columns(3)
    with col_d1:
        st.success(f"**Available ({len(details['available'])})**")
        for p in details['available']:
            st.write(f"• {p}")
            
    with col_d2:
        st.warning(f"**Maybe ({len(details['maybe'])})**")
        for p in details['maybe']:
            st.write(f"• {p}")
            
    with col_d3:
        st.error(f"**Unavailable ({len(details['no'])})**")
        for p in details['no']:
            st.write(f"• {p}")
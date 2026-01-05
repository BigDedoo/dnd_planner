import streamlit as st
import datetime
import pandas as pd
import calendar
import random
import sqlite3
import os
import datetime
import pandas as pd
import calendar
import random
import sqlite3

# --- PAGE CONFIGURATION ---
st.set_page_config(page_title="DnD Planner", page_icon="🎲", layout="wide")

# --- DATABASE CONNECTION ---
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_FILE = os.path.join(BASE_DIR, "dnd_planner.db")

def init_db():
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute('''
        CREATE TABLE IF NOT EXISTS availability (
            group_name TEXT,
            user_name TEXT,
            date TEXT,
            status TEXT,
            PRIMARY KEY (group_name, user_name, date)
        )
    ''')
    conn.commit()
    conn.close()

# Initialize DB on load
init_db()

# --- SESSION STATE (UI Only) ---
if 'selected_date_details' not in st.session_state:
    st.session_state.selected_date_details = None

# --- GROUPS CONFIGURATION ---
GROUPS = {
    "Green flag": ["Jiken", "Nuxio", "Ulrich", "Daerrus"],
    "Red flags": ["Gaelle", "Rico", "Yoann", "Romane", "Victor"]
}

# --- HELPER FUNCTIONS ---
def get_all_users():
    users = []
    for p_list in GROUPS.values():
        users.extend(p_list)
    return sorted(users)

def get_group_for_user(username):
    for g, p_list in GROUPS.items():
        if username in p_list:
            return g
    return None

def get_db_connection():
    return sqlite3.connect(DB_FILE)

def get_user_availability(group, user, date_obj):
    """Returns the status string or None for a user on a given date."""
    conn = get_db_connection()
    c = conn.cursor()
    c.execute("SELECT status FROM availability WHERE group_name=? AND user_name=? AND date=?", 
              (group, user, date_obj.isoformat()))
    result = c.fetchone()
    conn.close()
    return result[0] if result else None

def toggle_availability(group, user, date_obj):
    """Cycles through: None -> Available -> Maybe -> No -> None"""
    current = get_user_availability(group, user, date_obj)
    
    new_status = None
    if current is None: new_status = 'Available'
    elif current == 'Available': new_status = 'Maybe'
    elif current == 'Maybe': new_status = 'No'
    elif current == 'No': new_status = None 
    
    conn = get_db_connection()
    c = conn.cursor()
    if new_status:
        c.execute("INSERT OR REPLACE INTO availability (group_name, user_name, date, status) VALUES (?, ?, ?, ?)",
                  (group, user, date_obj.isoformat(), new_status))
    else:
        c.execute("DELETE FROM availability WHERE group_name=? AND user_name=? AND date=?",
                  (group, user, date_obj.isoformat()))
    conn.commit()
    conn.close()

def get_status_icon(status):
    if status == 'Available': return "✅"
    if status == 'Maybe': return "❓"
    if status == 'No': return "❌"
    return "⬜"

def generate_test_data():
    """Generates random data for January 2026 for all groups/players."""
    conn = get_db_connection()
    c = conn.cursor()
    
    # Clear existing data for strict testing
    c.execute("DELETE FROM availability WHERE date LIKE '2026-01-%'")
    
    year = 2026
    month = 1
    num_days = calendar.monthrange(year, month)[1]
    
    for group_name, players in GROUPS.items():
        for player in players:
            for day in range(1, num_days + 1):
                r = random.random()
                status = 'No'
                if r < 0.4: status = 'Available'
                elif r < 0.6: status = 'Maybe'
                
                date_str = datetime.date(year, month, day).isoformat()
                c.execute("INSERT INTO availability (group_name, user_name, date, status) VALUES (?, ?, ?, ?)",
                          (group_name, player, date_str, status))
    conn.commit()
    conn.close()

def load_data_as_df():
    conn = get_db_connection()
    df = pd.read_sql_query("SELECT group_name as [group], user_name as user, date, status FROM availability", conn)
    conn.close()
    if not df.empty:
        df['date'] = pd.to_datetime(df['date']).dt.date
    return df

# --- SIDEBAR: NAVIGATION ---
with st.sidebar:
    st.header("🧭 Navigation")
    
    # Construct grouped options
    login_options = ["--- SYSTEM ---", "Admin"]
    for group, players in GROUPS.items():
        login_options.append(f"--- {group.upper()} ---")
        login_options.extend(players)

    def format_identity(option):
        if option.startswith("---"):
            return option
        if option == "Admin":
            return f"      {option}"
        return f"      {option}" # Indented for players

    current_login = st.selectbox(
        "Who are you?", 
        login_options, 
        format_func=format_identity
    )
    
    # Check if a header was selected
    if current_login.startswith("---"):
        st.warning("⚠️ Please select a name from the list.")
        st.stop()

    # Defaults
    selected_group_name = None
    user = None
    is_admin_view = False
    is_oneshot_view = False
    
    if current_login == "Admin":
        st.divider()
        st.caption("🛠️ Admin Controls")
        
        # Mode Selection
        mode = st.radio("Mode", ["Player View", "Cross-Group", "Oneshot"], index=0)
        
        if mode == "Player View":
            st.subheader("👤 Ghost Login")
            selected_group_name = st.selectbox("Select Group", list(GROUPS.keys()))
            group_players = GROUPS[selected_group_name]
            user = st.selectbox(
                "Simulate User", 
                group_players,
                format_func=lambda x: f"{x} ({selected_group_name})"
            )
            st.info(f"Viewing as: **{user}**")
            
        elif mode == "Admin / Cross-Group":
            is_admin_view = True
            st.info("Comparing Group Availabilities")

        elif mode == "Oneshot Recruiter":
            is_oneshot_view = True
            st.info("Find guests for your sessions")
            
        st.divider()
        if st.button("⚡ Generate Test Data (Jan)"):
            generate_test_data()
            st.rerun()
            
    else:
        # REGULAR USER LOGIN
        user = current_login
        selected_group_name = get_group_for_user(user)
        
        st.divider()
        st.success(f"Logged in as **{user}**")
        st.caption(f"Member of **{selected_group_name}**")
        
        # Regular users are forced into Player View for their group
        is_admin_view = False
        is_oneshot_view = False

# --- TITLE & CONTROLS ---
if is_admin_view:
    st.title("🎲 DnD - Cross-Group Overview")
elif is_oneshot_view:
    st.title("🎲 DnD - Oneshot Recruiter")
else:
    st.title(f"🎲 DnD Planner - {selected_group_name}")

# Move Date Controls to Top
c1, c2, c3 = st.columns([1, 1, 4])
today = datetime.date.today()
current_year = c1.number_input("Year", min_value=today.year, max_value=today.year+1, value=today.year)
current_month = c2.selectbox("Month", range(1, 13), index=today.month-1, format_func=lambda x: calendar.month_name[x])

st.divider()

# --- COMMON CALENDAR DATA ---
cal = calendar.monthcalendar(current_year, current_month)
days_header = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]


# ==========================================
# VIEW MODE: NORMAL (Single Group)
# ==========================================
if not is_admin_view and not is_oneshot_view:
    col_left, col_right = st.columns([1, 1], gap="large")

    # LEFT: PERSONAL INPUT
    with col_left:
        st.subheader(f"📅 {user}'s Availability")
        h_cols = st.columns(7)
        for i, day in enumerate(days_header): h_cols[i].markdown(f"**{day}**")
            
        for week in cal:
            cols = st.columns(7)
            for i, day in enumerate(week):
                if day == 0:
                    cols[i].write("")
                else:
                    date_obj = datetime.date(current_year, current_month, day)
                    status = get_user_availability(selected_group_name, user, date_obj)
                    icon = get_status_icon(status)
                    btn_key = f"btn_input_{selected_group_name}_{current_year}_{current_month}_{day}"
                    if cols[i].button(f"{day} {icon}", key=btn_key):
                        toggle_availability(selected_group_name, user, date_obj)
                        st.rerun()
        st.caption("Click to cycle: ⬜ -> ✅ -> ❓ -> ❌ -> ⬜")

    # RIGHT: GROUP DASHBOARD
    with col_right:
        st.subheader(f"⚔️ Team Overview")
        h_cols = st.columns(7)
        for i, day in enumerate(days_header): h_cols[i].markdown(f"**{day}**")
        
        # Aggregate Stats
        stats_map = {}
        df = load_data_as_df()
        
        if not df.empty:
            df_group = df[df['group'] == selected_group_name]
            if not df_group.empty:
                for _, row in df_group.iterrows():
                    d = row['date']
                    if d.year == current_year and d.month == current_month:
                        if d not in stats_map: stats_map[d] = {'Available': [], 'Maybe': [], 'No': []}
                        if row['status'] in ['Available', 'Maybe', 'No']:
                            stats_map[d][row['status']].append(row['user'])

        max_p = len(GROUPS[selected_group_name])

        for week in cal:
            cols = st.columns(7)
            for i, day in enumerate(week):
                if day == 0:
                    cols[i].write("")
                else:
                    date_obj = datetime.date(current_year, current_month, day)
                    stats = stats_map.get(date_obj, {'Available': [], 'Maybe': [], 'No': []})
                    count_ok = len(stats['Available'])
                    
                    label_icon = "⚪"
                    if count_ok == max_p: label_icon = "🟢"
                    elif count_ok >= (max_p / 2): label_icon = "🟡"
                    elif count_ok > 0: label_icon = "🟠"
                    
                    label = f"{day}\n{label_icon} {count_ok}/{max_p}"
                    btn_key = f"btn_view_{selected_group_name}_{current_year}_{current_month}_{day}"
                    if cols[i].button(label, key=btn_key):
                        st.session_state.selected_date_details = {
                            'date': date_obj,
                            'stats': stats, # Passing the whole dict
                            'mode': 'single'
                        }
                        st.rerun()


# ==========================================
# VIEW MODE: ADMIN (Cross-Group)
# ==========================================
elif is_admin_view:
    st.subheader("⚔️ Combined Availability")
    
    cg_c1, cg_c2 = st.columns(2)
    g1 = cg_c1.selectbox("Group 1", list(GROUPS.keys()), index=0)
    g2 = cg_c2.selectbox("Group 2", list(GROUPS.keys()), index=1)
    
    max_p_total = len(GROUPS[g1]) + len(GROUPS[g2])
    
    # Calculate Combined Stats
    combined_stats_map = {}
    df = load_data_as_df()
    
    if not df.empty:
        # Filter for G1 OR G2
        df_combined = df[df['group'].isin([g1, g2])]
        
        if not df_combined.empty:
             for _, row in df_combined.iterrows():
                d = row['date']
                if d.year == current_year and d.month == current_month:
                    if d not in combined_stats_map: 
                        combined_stats_map[d] = {
                            'Available': [], 'Maybe': [], 'No': []
                        }
                    # We store tuple (user, group) to distinguish
                    if row['status'] in ['Available', 'Maybe', 'No']:
                        combined_stats_map[d][row['status']].append(f"{row['user']} ({row['group']})")

    # Render ONE big calendar
    h_cols = st.columns(7)
    for i, day in enumerate(days_header): h_cols[i].markdown(f"**{day}**")

    for week in cal:
        cols = st.columns(7)
        for i, day in enumerate(week):
            if day == 0:
                cols[i].write("")
            else:
                date_obj = datetime.date(current_year, current_month, day)
                stats = combined_stats_map.get(date_obj, {'Available': [], 'Maybe': [], 'No': []})
                count_ok = len(stats['Available'])
                
                label_icon = "⚪"
                # stricter criteria for large groups?
                if count_ok == max_p_total: label_icon = "🟢"
                elif count_ok >= (max_p_total * 0.7): label_icon = "🟡"
                elif count_ok > 0: label_icon = "🟠"
                
                label = f"{day}\n{label_icon} {count_ok}/{max_p_total}"
                btn_key = f"btn_cross_{current_year}_{current_month}_{day}"
                
                if cols[i].button(label, key=btn_key):
                    st.session_state.selected_date_details = {
                        'date': date_obj,
                        'stats': stats,
                        'mode': 'cross'
                    }
                    st.rerun()

# ==========================================
# VIEW MODE: ONESHOT RECRUITER
# ==========================================
elif is_oneshot_view:
    st.subheader("🤝 Find Guest Players")
    
    os_c1, os_c2 = st.columns(2)
    host_group = os_c1.selectbox("Host Group (We are playing)", list(GROUPS.keys()), index=0)
    guest_group = os_c2.selectbox("Guest Group (Recruit from)", list(GROUPS.keys()), index=1)
    
    if host_group == guest_group:
        st.warning("Please select two different groups.")
    else:
        st.markdown(f"Showing **{guest_group}** players available on dates when **{host_group}** is playing.")
        
        recruit_data = [] # List of dicts
        df = load_data_as_df()
        
        if not df.empty:
            # Helper to get users by status for a specific group/date
            def get_users_by_status(grp, yr, mo, dy, valid_statuses=['Available']):
                # Inefficient but simple
                d_obj = datetime.date(yr, mo, dy)
                matches = df[
                    (df['group'] == grp) & 
                    (df['date'] == d_obj) & 
                    (df['status'].isin(valid_statuses))
                ]
                return matches['user'].tolist()

            num_days = calendar.monthrange(current_year, current_month)[1]
            for day in range(1, num_days + 1):
                date_obj = datetime.date(current_year, current_month, day)
                
                host_available = get_users_by_status(host_group, current_year, current_month, day, ['Available'])
                
                # STRICT FILTER: Only dates where EVERYONE in the host group is Available
                if len(host_available) == len(GROUPS[host_group]): 
                     guest_available = get_users_by_status(guest_group, current_year, current_month, day, ['Available', 'Maybe'])
                     
                     if guest_available:
                         recruit_data.append({
                             "Date": date_obj,
                             "Host Attendance": "✅ Full Team", 
                             "Available Guests": ", ".join(guest_available)
                         })
        
        if recruit_data:
            df_recruit = pd.DataFrame(recruit_data)
            st.dataframe(
                df_recruit,
                column_config={
                    "Date": st.column_config.DateColumn("Session Date", format="DD/MM/YYYY"),
                    "Available Guests": st.column_config.TextColumn("Guest Candidates (Available/Maybe)")
                },
                hide_index=True,
                use_container_width=True
            )
        else:
            st.info("No overlaps found. Try selecting different groups or ensuring data is generated.")



# --- DETAILS SECTION ---
if st.session_state.selected_date_details:
    details = st.session_state.selected_date_details
    d_stats = details.get('stats')
    
    # Check because Oneshot view doesn't set 'stats' but we might have lingering state
    if d_stats:
        st.divider()
        st.markdown(f"### 🔎 Details for **{details['date'].strftime('%A %d %B %Y')}**")
        
        col_d1, col_d2, col_d3 = st.columns(3)
        with col_d1:
            st.success(f"**Available ({len(d_stats.get('Available', []))})**")
            for p in d_stats.get('Available', []): st.write(f"• {p}")
        with col_d2:
            st.warning(f"**Maybe ({len(d_stats.get('Maybe', []))})**")
            for p in d_stats.get('Maybe', []): st.write(f"• {p}")
        with col_d3:
            st.error(f"**Unavailable ({len(d_stats.get('No', []))})**")
            for p in d_stats.get('No', []): st.write(f"• {p}")
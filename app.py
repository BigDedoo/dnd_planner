import streamlit as st
import datetime
import pandas as pd

# --- CONFIGURATION DE LA PAGE ---
st.set_page_config(page_title="DnD Planner", page_icon="🎲", layout="wide")

# --- SIMULATION DE BASE DE DONNÉES (Session State) ---
# Dans la version finale, ceci sera remplacé par Supabase ou Firebase
if 'disponibilites' not in st.session_state:
    st.session_state.disponibilites = [] # Liste de dictionnaires {'user': ..., 'date': ..., 'status': ...}

# Liste des joueurs
JOUEURS = ["Moi (Admin)", "Alice", "Bob", "Charlie", "David"]

# --- BARRE LATÉRALE : CONNEXION ---
with st.sidebar:
    st.header("👤 Connexion")
    user = st.selectbox("Qui êtes-vous ?", JOUEURS)
    st.divider()
    st.info(f"Connecté en tant que : **{user}**")

# --- TITRE ---
st.title("🎲 Planificateur de Session DnD")
st.markdown("Sélectionnez vos jours de dispo pour le mois à venir.")

# --- SÉLECTION DES DATES (Vue Joueur) ---
col1, col2 = st.columns([1, 2])

with col1:
    st.subheader("📅 Mes disponibilités")
    # Sélecteur de date simple
    d = st.date_input("Choisir une date", datetime.date.today())
    
    # Boutons d'action
    c1, c2 = st.columns(2)
    if c1.button("✅ Dispo", use_container_width=True):
        st.session_state.disponibilites.append({'user': user, 'date': d, 'status': 'Dispo'})
        st.success(f"Dispo ajoutée pour le {d}")
        
    if c2.button("❌ Pas dispo", use_container_width=True):
        # On retire les dispos existantes pour ce jour/user
        st.session_state.disponibilites = [
            x for x in st.session_state.disponibilites 
            if not (x['user'] == user and x['date'] == d)
        ]
        st.warning(f"Retiré pour le {d}")

    # Petit récap personnel
    st.write("---")
    st.caption("Mes dates enregistrées :")
    mes_dates = [x['date'] for x in st.session_state.disponibilites if x['user'] == user]
    if mes_dates:
        st.write(sorted(list(set(mes_dates))))
    else:
        st.write("Aucune date sélectionnée.")

# --- TABLEAU DE BORD DU GROUPE (Vue Admin/Globale) ---
with col2:
    st.subheader("⚔️ Disponibilités du Groupe")
    
    if st.session_state.disponibilites:
        # Transformation des données pour affichage
        df = pd.DataFrame(st.session_state.disponibilites)
        
        if not df.empty:
            # On compte combien de personnes sont dispos par jour
            recap = df.groupby('date')['user'].unique().reset_index()
            recap['nombre_joueurs'] = recap['user'].apply(len)
            recap['noms'] = recap['user'].apply(lambda x: ", ".join(x))
            
            # Affichage sous forme de tableau interactif
            st.dataframe(
                recap.style.background_gradient(subset=['nombre_joueurs'], cmap="Greens"),
                column_config={
                    "date": "Date",
                    "nombre_joueurs": st.column_config.ProgressColumn(
                        "Disponibles", 
                        format="%d/5", 
                        min_value=0, 
                        max_value=len(JOUEURS)
                    ),
                    "noms": "Joueurs Prêts"
                },
                use_container_width=True,
                hide_index=True
            )
        else:
            st.info("En attente de données...")
    else:
        st.info("Aucune disponibilité rentrée pour l'instant.")

# --- EXPLICATION POUR LE DM ---
st.divider()
st.markdown("""
**Comment ça marche ?**
1. Chaque joueur se "connecte" via le menu de gauche.
2. Il ajoute ses dates.
3. Le tableau de droite se met à jour en temps réel. 
*Les dates où tout le monde est là apparaîtront en vert foncé !*
""")
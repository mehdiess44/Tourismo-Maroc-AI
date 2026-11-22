import os
from datetime import date, time

import requests
import streamlit as st

BASE = os.getenv("TOURISMO_API_URL", "http://127.0.0.1:8000")


def request(path, **kwargs):
    result = requests.request("POST" if kwargs else "GET", BASE + path, timeout=45, **kwargs)
    result.raise_for_status()
    return result.json()


st.title("Tourismo AI · Meknès")
try:
    entries = {entry["id"]: entry for entry in request("/catalog")}
    places = request("/places")
    action = st.radio("Parcours", ["Reconnaître", "Consulter", "Planifier"], horizontal=True)
    if action == "Reconnaître":
        kind = st.selectbox("Type", ["monument", "artisanat"])
        image = st.file_uploader("Photo", type=["jpg", "jpeg", "png", "webp"])
        if st.button("Analyser") and image:
            result = request("/recognitions", data={"kind": kind},
                             files={"photo": ("photo", image.getvalue(), image.type)})
            st.session_state["candidates"] = [entry["id"] for entry in result["candidates"]]
            st.session_state["recognition_status"] = result["status"]
        if st.session_state.get("recognition_status") == "unavailable":
            st.warning("Modèle visuel indisponible.")
        elif st.session_state.get("recognition_status"):
            st.info("Confirmez la fiche correspondant à votre photo.")
        allowed = [key for key, entry in entries.items() if entry["kind"] == kind]
        preferred = [key for key in st.session_state.get("candidates", []) if key in allowed]
        choices = list(dict.fromkeys([*preferred, *allowed]))
        selection = st.selectbox("Confirmer ou corriger", choices, format_func=lambda key: entries[key]["name"])
    elif action == "Consulter":
        selection = st.selectbox("Fiche", entries, format_func=lambda key: entries[key]["name"])
    else:
        selection = None
        if not places:
            st.warning("Réseau piéton indisponible.")
        else:
            with st.form("walk"):
                start = st.selectbox("Départ", places, format_func=lambda key: places[key]["name"])
                end = st.selectbox("Arrivée", places, format_func=lambda key: places[key]["name"])
                day = st.date_input("Date", date.today())
                hour = st.time_input("Heure à Meknès", time(10))
                hours = st.slider("Durée maximale", 1, 6, 3)
                speed = st.selectbox("Vitesse en km/h", [3, 4, 5], index=1)
                interests = st.multiselect("Intérêts", ["architecture", "histoire", "musees", "artisanat"])
                required = st.multiselect("Étapes obligatoires", places, format_func=lambda key: places[key]["name"])
                if st.form_submit_button("Calculer"):
                    plan = request("/itineraries", json={"departure": start, "arrival": end, "day": str(day),
                                   "start": hour.strftime("%H:%M"), "hours": hours, "speed": speed,
                                   "interests": interests, "required": required})
                    if plan["status"] == "ok":
                        st.metric("Durée estimée", f"{plan['minutes']} min")
                        st.dataframe(plan["steps"], hide_index=True)
                        for warning in plan["warnings"]:
                            st.warning(warning)
                    else:
                        st.warning(plan["reason"])
    if selection:
        entry = request(f"/entities/{selection}")
        st.subheader(entry["name"])
        if not entry["facts"]:
            st.info("Faits en cours de documentation.")
        for fact in entry["facts"]:
            st.write(fact["text"])
            st.link_button(fact["passage"], fact["url"])
except requests.RequestException:
    st.error("Demande impossible. Vérifiez le service puis réessayez.")

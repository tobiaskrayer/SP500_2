"""
Supabase-Client pro Streamlit-Session.
Liest URL und Anon-Key aus st.secrets (Streamlit Cloud) oder Umgebungsvariablen.

Bewusst KEIN @st.cache_resource: das würde einen Client (inkl. Auth-Token!)
über alle Browser-Sessions teilen — Login von Nutzer B würde den Token von
Nutzer A überschreiben und sb.auth.get_session() gäbe fremde Sessions heraus.
"""

import os
import streamlit as st


def get_supabase():
    """Gibt den Supabase-Client der aktuellen Session zurück (lazy erstellt)."""
    if "sb_client" in st.session_state:
        return st.session_state.sb_client

    try:
        url = st.secrets["SUPABASE_URL"]
        key = st.secrets["SUPABASE_ANON_KEY"]
    except (KeyError, FileNotFoundError):
        url = os.environ.get("SUPABASE_URL", "")
        key = os.environ.get("SUPABASE_ANON_KEY", "")

    if not url or not key:
        raise RuntimeError(
            "Supabase-Credentials fehlen. "
            "Bitte SUPABASE_URL und SUPABASE_ANON_KEY in .streamlit/secrets.toml eintragen."
        )

    from supabase import create_client
    st.session_state.sb_client = create_client(url, key)
    return st.session_state.sb_client

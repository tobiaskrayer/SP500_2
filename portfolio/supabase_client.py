"""
Supabase-Client-Singleton.
Liest URL und Anon-Key aus st.secrets (Streamlit Cloud) oder Umgebungsvariablen.
"""

import os
import streamlit as st


@st.cache_resource
def get_supabase():
    """Gibt einen gecachten Supabase-Client zurück."""
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
    return create_client(url, key)

# Dashboard

Streamlit-App mit vier Seiten: **Fragen**, **Inbox**, **Vault**, **System**. Sie spricht nur mit der REST-API des Assistenten (`API_URL`, Standard `http://localhost:8080`) und braucht nur `streamlit` und `httpx`.

```bash
# mit Docker (empfohlen): startet mit dem restlichen Stack
docker compose up -d --build        # dann http://localhost:8501

# ohne Docker
pip install -e ".[dashboard]"
assistant serve &                   # API auf :8080
cd dashboard && streamlit run app.py
```

| Datei | Aufgabe |
|---|---|
| `app.py` | Einstieg: Navigation oben, Statuszeile (Gaming-PC, Index, Nachtjob) |
| `seiten/` | Eine Datei je Seite |
| `api_client.py` | Typisierter Client für die API, Fehler als `ApiFehler` |
| `daten.py` | API-Antworten kurz zwischenspeichern (`st.cache_data`) |
| `ansicht.py` | Reine Hilfsfunktionen: Zeiten, Texte, `[[Wikilink]]`-Chips (ohne Streamlit testbar) |
| `bausteine.py` | Tabelle mit „Öffnen“-Link nach Obsidian, liegende Balken |
| `.streamlit/config.toml` | Design „Graphit & Moos“, hell und dunkel, nur Theme-Optionen |
| `static/fonts/` | Atkinson Hyperlegible Next und Source Serif 4 (SIL Open Font License) |

Tests: `tests/test_dashboard.py` startet die echte API mit Fakes in einem Thread und prüft jede Seite mit `streamlit.testing.v1.AppTest`.

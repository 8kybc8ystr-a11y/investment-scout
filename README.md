# Investment Scout V1

Eine funktionsfähige Streamlit-Web-App für regelbasiertes Screening von internationalen Dividendenaktien und übermäßig gefallenen Aktien. **Kein Broker, keine Orderausführung und keine personalisierte Anlageberatung.**

## Lokal starten

Python 3.11+ installieren, dann im Projektverzeichnis:

```bash
python -m venv .venv
# macOS/Linux: source .venv/bin/activate
# Windows: .venv\Scripts\activate
pip install -r requirements.txt
python scanner.py --tickers MSFT JNJ BAS.DE NESN.SW
streamlit run app.py
```

Für den vollständigen ersten Scan: `python scanner.py`. Je nach API-Limits kann der Scan dauern oder für einzelne Symbole fehlschlagen. Der Scanner bewahrt den alten Snapshot, wenn gar keine Daten geladen werden können. Für einen lokalen Test ist eine Internetverbindung erforderlich.

## Web-App online stellen

1. Dateien samt verstecktem Ordner `.github/workflows/` in ein **privates** GitHub-Repository hochladen.
2. Unter GitHub → Settings → Actions → General die Schreibberechtigung für den `GITHUB_TOKEN` erlauben (Workflow permissions: Read and write permissions). Falls organisatorische Richtlinien das verbieten, einen anderen Speichermechanismus konfigurieren.
3. Unter Actions → Daily stock scan → Run workflow den ersten Scan ausführen und prüfen, ob `data/latest.json` im Repository erzeugt wurde.
4. Unter [share.streamlit.io](https://share.streamlit.io/) anmelden, GitHub verbinden, Repository und `app.py` auswählen, deployen. Für private Repositories gelten die jeweiligen Hosting-Zugangs- und Tarifbedingungen.
5. Die App auf dem iPhone in Safari öffnen und über Teilen → Zum Home-Bildschirm als Icon hinzufügen.

GitHub Actions startet planmäßig an Werktagen um 19:20 UTC. Geplante Jobs können verzögert werden oder ausfallen. Bei längerer Inaktivität können GitHub-Zeitpläne deaktiviert werden. Der Scan aktualisiert den Snapshot; die App zeigt beim erneuten Laden den neuesten Commit.

## Dateien

- `scanner.py`: Kurs- und Fundamentaldaten laden, transparentes Ranking und Risiken berechnen
- `app.py`: Filter, Ranking, Detailansicht, Kurschart
- `universe.csv`: editierbare Liste internationaler Aktien
- `.github/workflows/daily-scan.yml`: geplanter Scan und Git-Commit
- `data/latest.json`: automatisch erzeugter Snapshot (nicht im Download enthalten)

## Grenzen und geplante Erweiterungen

- Das Universum umfasst eine **kuratierte internationale Watchlist**, nicht alle weltweit börsennotierten Unternehmen.
- Yahoo Finance via `yfinance` ist eine inoffizielle, nicht für kritische Produktionssysteme garantierte Datenquelle. Fehlende Daten ergeben null Punkte; Datenverfügbarkeit beeinflusst das Ranking.
- Die Dividendenrendite wird aus der gemeldeten jährlichen Dividende / dem aktuellen Kurs berechnet. Dies ist kein Nachweis künftiger Ausschüttungen.
- Der Score ist ein transparenter Heuristikwert (kein erwarteter Ertrag). Branchenvergleiche, Währungseffekte, Bilanzqualität und aktuelle Unternehmensnachrichten fehlen.
- **Keine LLM-Analyse in V1**: Die Argumente werden deterministisch aus Daten abgeleitet. Eine optionale KI-Analyse kann später mit verifizierten Geschäftsberichten und Nachrichten ergänzt werden.
- **Keine proaktiven Browser-Push-Nachrichten in V1**: Der tägliche Scan läuft automatisch, aber neue Ergebnisse werden erst beim Öffnen/Neuladen der Web-App sichtbar. Echte Web-Push-Benachrichtigungen erfordern zusätzlich einen Push-Service, Nutzerzustimmung und geeignete Infrastruktur.
- Für große Universen und belastbare Fundamentalanalysen ist eine lizenzierte Marktdaten-API ratsam.

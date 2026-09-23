# Live Wordcloud

Deelnemers scannen de QR-code en sturen woorden in via hun telefoon; op het grote scherm groeit de wolk live mee.

## Op Railway zetten
1. Zet deze map in een GitHub-repo en maak in Railway een nieuw project vanuit die repo.
2. Voeg bij Variables toe:
   - `ADMIN_PASSWORD` – wachtwoord voor de presentatorpagina
   - `SECRET_KEY` – een lange willekeurige tekst
3. Optioneel, om vragen en antwoorden te bewaren na een herstart: voeg een Volume toe op `/data` en zet `DATA_DIR=/data`.
4. Genereer onder Settings > Networking een publiek domein.

## Gebruik
- Presentator: `https://<jouw-domein>/presenter` (inloggen met ADMIN_PASSWORD). Zet dit op de beamer.
- Deelnemers: `https://<jouw-domein>/` of de QR-code op het scherm.
- Sneltoetsen op het scherm: B beheer, pijltjes vorige/volgende vraag, L insturen open/dicht, Q QR-code tonen/verbergen, F volledig scherm.
- In het beheerpaneel: vragen vooraf klaarzetten, aantal woorden per deelnemer (1–10), woorden verwijderen, antwoorden wissen en alles exporteren als CSV (opent in Excel).

## Lokaal testen
    pip install -r requirements.txt
    ADMIN_PASSWORD=test python app.py

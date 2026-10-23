# Huurbot Gouda e.o.

Scant elke 10 minuten Pararius, Huurwoningen.nl, Funda, Stienstra, Vesteda,
Ikwilhuren (MVGM), VB&T, Rotsvast en 123Wonen op nieuwe huurwoningen in Gouda
en omgeving, en stuurt ze naar WhatsApp en/of Telegram.

## Stap 1 — WhatsApp koppelen (CallMeBot, gratis)
1. Open https://www.callmebot.com/blog/free-api-whatsapp-messages/ en sla het
   telefoonnummer van de CallMeBot-bot dat daar staat op in je contacten.
2. Stuur dat contact via WhatsApp: `I allow callmebot to send me messages`
3. Je krijgt een bericht terug met je **API key**. Bewaar die.
   (Geen antwoord binnen 2 minuten? Probeer het na 24 uur opnieuw.)

## Stap 2 — GitHub-repo
1. Log in op github.com → rechtsboven **+** → **New repository**.
2. Naam: `huurbot`, kies **Public**, klik **Create repository**.
3. Klik **uploading an existing file**, sleep alle bestanden uit deze map erin
   (ook de map `.github`!) en klik **Commit changes**.
   Tip: zie je de map `.github` niet? Zet "verborgen bestanden tonen" aan.
4. **Settings → Secrets and variables → Actions → New repository secret**:
   - `WHATSAPP_PHONE` = je nummer, bijv. `+31612345678`
   - `WHATSAPP_APIKEY` = de key van CallMeBot
   - (optioneel) `TELEGRAM_TOKEN` en `TELEGRAM_CHAT_ID`
5. **Settings → Actions → General → Workflow permissions** →
   **Read and write permissions** → Save.

## Stap 3 — Testen
1. Tab **Actions** → (eventueel "I understand, enable workflows") →
   **Huurbot scan** → **Run workflow** → vink **Testmodus** aan → Run.
2. Binnen 2 à 3 minuten krijg je een WhatsApp met per site hoeveel woningen
   er gevonden zijn. Stuur een screenshot naar Claude als iets 0 geeft.

## Stap 4 — Live
Run nog één keer **zonder** Testmodus. Je krijgt per site een bericht
"gekoppeld". Daarna draait de bot elke 10 minuten vanzelf en krijg je alleen
nog nieuwe woningen.

## Aanpassen
Alles staat in `config.yaml`: prijsrange, minimale m², plaatsen en sites.

## Goed om te weten
- GitHub kan geplande runs soms 5–15 minuten vertragen.
- Levert een site een uur lang niets op, dan krijg je een ⚠️-melding.
- GitHub zet geplande runs uit na 60 dagen zonder activiteit; krijg je daar
  een mail over, klik dan op "Enable workflow".

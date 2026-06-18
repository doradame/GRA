# Amministrazione LibreChat

Questa guida raccoglie le operazioni di amministrazione per l'istanza LibreChat deployata in Docker.

- URL LibreChat: `https://chat.matamune.4nk.eu`
- URL Admin Panel: `https://chat-admin.matamune.4nk.eu`
- Container LibreChat: `igr-librechat`

## Accesso al pannello admin

Il [LibreChat Admin Panel](https://www.librechat.ai/docs/features/admin_panel) è un'interfaccia web separata per gestire utenti, gruppi, ruoli e configurazioni.

1. Apri `https://chat-admin.matamune.4nk.eu`
2. Accedi con un account che abbia ruolo `ADMIN` in LibreChat
3. Il pannello consente di:
   - visualizzare e cercare gli utenti
   - gestire gruppi e ruoli
   - applicare override di configurazione per ruoli/gruppi
   - rilasciare grant di sistema (`access:admin`, `manage:users`, ecc.)

> **Nota:** il pannello admin non espone (al momento) una funzione di invito via email. Per creare nuovi account si usa lo script Python descritto sotto.

## Configurazione email (Resend)

La configurazione SMTP è in `librechat/librechat.env`:

```env
EMAIL_FROM=matamune@moja-ia.eu
EMAIL_FROM_NAME=LibreChat
EMAIL_HOST=smtp.resend.com
EMAIL_PORT=587
EMAIL_ENCRYPTION=starttls
EMAIL_USERNAME=resend
EMAIL_PASSWORD=<resend-api-key>
ALLOW_PASSWORD_RESET=true
```

Per verificare che la configurazione sia valida:

```bash
docker exec igr-librechat node -e "const { checkEmailConfig } = require('@librechat/api'); console.log('Email config valid:', checkEmailConfig());"
```

## Gestione utenti

### Creare / invitare un utente (script consigliato)

Lo script `librechat/scripts/invite_user.py` crea l'utente e invia automaticamente un'email con le credenziali.

```bash
cd /mnt/HC_Volume_106071907/proj/graph-rag-assistant
python3 librechat/scripts/invite_user.py dr@mojalab.com --name "Dario Rossi"
```

Comportamento:

- legge API key, mittente e dominio da `librechat/librechat.env`
- genera una password sicura
- crea l'utente nel container `igr-librechat`
- invia l'email di benvenuto con email, password temporanea e link di accesso

Opzioni utili:

```bash
# Solo creare l'utente, senza inviare email
python3 librechat/scripts/invite_user.py dr@mojalab.com --no-email

# Specificare username e password
python3 librechat/scripts/invite_user.py dr@mojalab.com --username dario --password "Password123!"

# Usare un env file alternativo
python3 librechat/scripts/invite_user.py dr@mojalab.com --env-file /path/altro.env
```

> **Nota:** il comando `npm run invite-user` di LibreChat è attualmente non funzionante in questa versione (`v0.8.7-rc1`) perché cerca un modulo `models/inviteUser` che non esiste. Per questo motivo si usa lo script Python sopra.

### Creare un utente manualmente

Dentro il container LibreChat:

```bash
docker exec -it igr-librechat bash
npm run create-user
```

Lo script chiede email, nome, username e password. In alternativa, tutti gli argomenti da riga di comando:

```bash
docker exec igr-librechat npm run create-user -- dr@mojalab.com "Dario Rossi" dario "Password123!" --email-verified=true
```

### Eliminare un utente

```bash
docker exec igr-librechat npm run delete-user dr@mojalab.com
```

Confermare con `y` quando richiesto. Per automatizzare la conferma:

```bash
echo -e "y\ny" | docker exec -i igr-librechat npm run delete-user dr@mojalab.com
```

### Resettare la password di un utente

Usa lo script dedicato:

```bash
cd /mnt/HC_Volume_106071907/proj/graph-rag-assistant
python3 backend/scripts/reset_password.py dr@mojalab.com "NuovaPassword123!"
```

Lo script aggiorna direttamente la password nel database MongoDB.

## Note

- `ALLOW_REGISTRATION=false` in `librechat/librechat.env` blocca la registrazione libera. Gli account devono essere creati dall'amministratore.
- Il file `librechat/librechat.env` contiene secret ed è in `.gitignore`. Non committarlo.
- I file `.env.example` nel repository fungono da template e possono essere aggiornati se si aggiungono nuove variabili.

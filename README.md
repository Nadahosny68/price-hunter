# Price Hunter
1. Create a new GitHub repo, upload all these files (keep the .github folder).
2. Repo > Settings > Secrets > Actions: add TELEGRAM_TOKEN, TELEGRAM_CHAT_ID, SERPAPI_KEY (serpapi.com free key).
3. Actions tab > "Daily price alert" > Run workflow to test.
4. Phone UI: share.streamlit.io > New app > pick the repo, file app.py. In Advanced > Secrets add:
   SERPAPI_KEY = "..."
   GH_REPO = "yourname/price-hunter"
   GH_TOKEN = "github token with Contents: read/write on this repo"
5. Open the app link on your phone > Add to Home Screen.

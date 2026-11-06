# Repsy: workout tracker

A mobile-friendly fitness web app built with Python and Flask.

- **Workout templates:** build routines with exercises, sets, target reps, weight and rest time.
- **Start a workout** from a template, or start empty and add exercises as you go.
- **Track every set:** weight and reps, with your previous performance shown next to each set (tap it to copy).
- **Rest timer:** starts automatically when you tick off a set, using that exercise's rest time. It has ±15s and Skip buttons, beeps and vibrates when time is up, and keeps running if you reload the page. You can also start one manually.
- **History:** duration, completed sets and total volume for each workout. You can save any workout as a new template.
- **Sign in with Google or Apple.** Accounts with the same verified email are linked automatically.
- Built-in exercise library (about 50 exercises). Any new name you type becomes a custom exercise.
- Choose kg or lb, and set a default rest time.

## Run with Docker

```bash
cp .env.example .env        # then fill in SECRET_KEY and your SSO credentials
docker compose up --build
```

Open http://localhost:8000. This starts the app (gunicorn) and PostgreSQL. Data is stored in the `pgdata` volume.

To try the app before you have SSO credentials, set `DEV_LOGIN=1` in `.env`. The login page then shows an email-only sign-in form. **Never enable it in production**, because it lets anyone sign in as any email.

Run the image on its own with SQLite:

```bash
docker build -t repsy .
docker run -p 8000:8000 --env-file .env -e DATABASE_URL=sqlite:////data/fitness.db -v repsy-data:/data repsy
```

## Local development (without Docker)

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt pytest
DEV_LOGIN=1 .venv/bin/flask --app wsgi:app run --debug
.venv/bin/python -m pytest
```

## Setting up SSO

### Google
1. Go to [Google Cloud Console → APIs & Services → Credentials](https://console.cloud.google.com/apis/credentials). Create an **OAuth client ID** of type *Web application*.
2. Add this **Authorized redirect URI**: `{BASE_URL}/auth/callback/google` (for local use, `http://localhost:8000/auth/callback/google`).
3. Put the client ID and secret in `GOOGLE_CLIENT_ID` and `GOOGLE_CLIENT_SECRET`.

### Apple
You need a paid Apple Developer account. Apple only accepts **HTTPS on a real domain**, so it won't work on `localhost`.

1. In [Certificates, Identifiers & Profiles](https://developer.apple.com/account/resources/identifiers), create an **App ID** with *Sign in with Apple* enabled.
2. Create a **Services ID**. This is your `APPLE_CLIENT_ID`, for example `com.example.fitness.web`. Enable *Sign in with Apple* on it, add your domain, and set the return URL to `{BASE_URL}/auth/callback/apple`.
3. Under **Keys**, create a key with *Sign in with Apple* and download the `.p8` file. Its Key ID goes in `APPLE_KEY_ID`, and your Team ID (top right of the portal) goes in `APPLE_TEAM_ID`.
4. Provide the key in one of two ways: paste its contents into `APPLE_PRIVATE_KEY` with newlines written as `\n`, or mount the file and set `APPLE_PRIVATE_KEY_PATH`.
5. Set `SESSION_COOKIE_SECURE=1`, since you're on HTTPS.

The app generates the short-lived ES256 client secret that Apple requires on each sign-in. Apple sends the user's name only on the very first sign-in, and the app stores it then.

A login button only appears for a provider whose credentials are configured.

## Configuration

| Variable | Purpose |
|---|---|
| `SECRET_KEY` | Required. A long random string. |
| `DATABASE_URL` | SQLAlchemy URL. Docker Compose sets it to Postgres. The default is SQLite. |
| `BASE_URL` | Public URL, used to build OAuth redirect URIs. |
| `SESSION_COOKIE_SECURE` | `1` when served over HTTPS. |
| `PROXY_COUNT` | Number of reverse proxies in front of the app, so `X-Forwarded-*` headers are trusted. The default is `1`. |
| `GOOGLE_*`, `APPLE_*` | SSO credentials, as described above. |
| `DEV_LOGIN` | `1` enables the email-only test login. Local use only. |

## Project layout

```
app/
  __init__.py      app factory, `flask init-db` command
  auth.py          Google / Apple OAuth + account linking
  models.py        User, OAuthIdentity, Exercise, WorkoutTemplate, Workout, SetEntry, ...
  services.py      workout logic shared by views and API
  views.py         HTML pages
  api.py           JSON API used by the live workout screen
  static/js/workout.js   set logging + rest timer
tests/             pytest suite
```

## Notes and limitations
- The database schema is created with `db.create_all()` on start-up. Adding Alembic (Flask-Migrate) is the next step before changing models on a live database.
- Changing the unit setting relabels weights; it doesn't convert numbers already logged.

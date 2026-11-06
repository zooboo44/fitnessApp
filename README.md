# Repsy: workout tracker

A mobile-friendly fitness web app built with Python and Flask.

- **Workout templates:** build routines where every set is its own entry with its own weight, reps and rest time.
- **Templates learn from you:** when you finish a workout started from a template, you pick one of three options:
  - **Save workout only:** the template is left unchanged.
  - **Save + update weights & reps:** the weight and reps of each completed set become the targets for that template set. The number of sets and exercises stays the same.
  - **Save + update weights, reps & exercises:** the template is rebuilt to match the workout. Added or removed sets, added or removed exercises, exercise order and rest times all carry over. A set you didn't complete keeps its old target.

  Discarding a workout never changes the template.
- **Start a workout** from a template, or start empty and add exercises as you go.
- **Track every set:** each set is its own row. **+ Add set** pre-fills weight and reps from the same set number in your previous workout of that exercise. If there was no such set, it copies the set above. Previous values are shown next to each set (tap to copy).
- **A rest timer after every set:** each set gets its own timer row. Type a rest time straight into it (`90`, `1:30`, `2m` or `1m30s`), or nudge it with the −15/+15 buttons. The template editor accepts the same formats. The timer starts when you tick the set's **Done** box. It counts down inline, and a bar pinned to the bottom of the screen appears when you scroll away. It beeps and vibrates when time is up and survives a page reload.
- **History:** duration, completed sets and total volume for each workout. You can save any workout as a new template.
- **Sign in with just your email,** or with Google or Apple. Entering a new email creates an account. Accounts with the same email are linked automatically.
- Built-in exercise library (about 50 exercises). Any new name you type becomes a custom exercise.
- Weights are in pounds (lb) by default; switch to kg in Settings. You can also set a default rest time.

## Run with Docker

```bash
cp .env.example .env        # then fill in SECRET_KEY and your SSO credentials
docker compose up --build
```

Open http://localhost (port 80). This starts the app (gunicorn) and PostgreSQL. Data is stored in the `pgdata` volume.

If port 80 is already taken on your machine, set `HTTP_PORT=8080` (or another free port) in `.env` and include the port in `BASE_URL`.

Enter your email to sign in; a new email creates an account. Google and Apple are optional and only appear once configured.

Run the image on its own with SQLite:

```bash
docker build -t repsy .
docker run -p 80:8000 --env-file .env -e DATABASE_URL=sqlite:////data/fitness.db -v repsy-data:/data repsy
```

## Local development (without Docker)

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt pytest
FLASK_DEBUG=1 .venv/bin/flask --app wsgi:app run
.venv/bin/python -m pytest
```

## Setting up SSO

### Google
1. Go to [Google Cloud Console → APIs & Services → Credentials](https://console.cloud.google.com/apis/credentials). Create an **OAuth client ID** of type *Web application*.
2. Add this **Authorized redirect URI**: `{BASE_URL}/auth/callback/google` (for local use, `http://localhost/auth/callback/google`).
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

### How email accounts and SSO fit together
- Email sign-in and an SSO login with the same **verified** email become one account.

> **Security warning:** email sign-in has no password or verification step. Anyone who can reach the app can open any account by typing that person's email address, including accounts that also use Google or Apple. This is fine on your own machine or home network, but **don't expose the app to the internet like this.** Before you do, switch to emailed one-click sign-in links (needs an email service such as SendGrid or Postmark), or keep only Google and Apple sign-in.

## Configuration

| Variable | Purpose |
|---|---|
| `SECRET_KEY` | Required. A long random string. |
| `DATABASE_URL` | SQLAlchemy URL. Docker Compose sets it to Postgres. The default is SQLite. |
| `BASE_URL` | Public URL, used to build OAuth redirect URIs. |
| `SESSION_COOKIE_SECURE` | `1` when served over HTTPS. |
| `PROXY_COUNT` | Number of reverse proxies in front of the app, so `X-Forwarded-*` headers are trusted. The default is `1`. |
| `GOOGLE_*`, `APPLE_*` | SSO credentials, as described above. |

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

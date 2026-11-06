import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec
from joserfc import jwt
from joserfc.jwk import ECKey

from app import create_app
from app.extensions import db
from app.models import OAuthIdentity, SetEntry, User, Workout, WorkoutTemplate


@pytest.fixture
def app():
    app = create_app(
        {
            "TESTING": True,
            "SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:",
            "WTF_CSRF_ENABLED": False,
            "DEV_LOGIN": True,
        }
    )
    with app.app_context():
        db.create_all()
    yield app


@pytest.fixture
def client(app):
    return app.test_client()


def login(client, email="lifter@example.com"):
    return client.post("/auth/dev-login", data={"email": email}, follow_redirects=False)


def make_template(client, name="Push Day"):
    return client.post(
        "/templates/new",
        data={
            "name": name,
            "exercise_name": ["Bench Press", "My Custom Press"],
            "sets": ["3", "2"],
            "reps": ["8", "12"],
            "weight": ["60", ""],
            "rest_seconds": ["120", "60"],
        },
    )


def test_requires_login(client):
    r = client.get("/")
    assert r.status_code == 302 and "/auth/login" in r.headers["Location"]
    assert client.get("/api/workouts/1").status_code == 401


def test_login_page_without_providers(app):
    app.config["DEV_LOGIN"] = False
    r = app.test_client().get("/auth/login")
    assert b"No sign-in providers are configured" in r.data


def test_dev_login_disabled_returns_404(app):
    app.config["DEV_LOGIN"] = False
    assert app.test_client().post("/auth/dev-login", data={"email": "a@b.c"}).status_code == 404


def test_template_crud_and_start_workout(client, app):
    login(client)
    r = make_template(client)
    assert r.status_code == 302

    with app.app_context():
        t = WorkoutTemplate.query.one()
        assert [te.exercise.name for te in t.exercises] == ["Bench Press", "My Custom Press"]
        assert t.exercises[0].weight == 60 and t.exercises[0].rest_seconds == 120
        tid = t.id

    r = client.post("/workouts/start", data={"template_id": tid})
    assert r.status_code == 302
    wid = int(r.headers["Location"].rsplit("/", 1)[1])

    data = client.get(f"/api/workouts/{wid}").get_json()
    assert data["name"] == "Push Day"
    bench = data["exercises"][0]
    assert len(bench["sets"]) == 3 and bench["sets"][0]["weight"] == 60 and bench["sets"][0]["reps"] == 8
    assert bench["rest_seconds"] == 120

    # Can't start a second workout while one is active
    r = client.post("/workouts/start", data={})
    assert r.headers["Location"].endswith(f"/workouts/{wid}")

    # Log sets
    for s in bench["sets"][:2]:
        r = client.patch(f"/api/sets/{s['id']}", json={"reps": 7, "weight": "62.5", "completed": True})
        assert r.status_code == 200 and r.get_json()["completed"] is True

    # Add an exercise manually and a set to it
    r = client.post(f"/api/workouts/{wid}/exercises", json={"name": "  pull-up  ", "sets": 1})
    assert r.status_code == 201 and r.get_json()["name"] == "Pull-up"  # matched built-in
    we_id = r.get_json()["id"]
    s = client.post(f"/api/workout-exercises/{we_id}/sets").get_json()
    client.patch(f"/api/sets/{s['id']}", json={"reps": 10, "completed": True})

    # Finish
    client.post(f"/workouts/{wid}/finish")
    with app.app_context():
        w = db.session.get(Workout, wid)
        assert w.finished_at is not None
        # Untouched sets from "My Custom Press" (no weight) still have reps from template, so kept;
        # the empty first set of Pull-up is dropped.
        pull = [we for we in w.exercises if we.exercise.name == "Pull-up"][0]
        assert len(pull.sets) == 1
        assert w.total_volume == 2 * 7 * 62.5

    # Finished workouts are read-only through the API
    assert client.patch(f"/api/sets/{bench['sets'][2]['id']}", json={"reps": 1}).status_code == 409

    assert b"Push Day" in client.get("/history").data
    assert b"Push Day" in client.get(f"/workouts/{wid}").data

    # Next workout prefills from previous performance
    r = client.post("/workouts/start", data={})
    wid2 = int(r.headers["Location"].rsplit("/", 1)[1])
    we = client.post(f"/api/workouts/{wid2}/exercises", json={"name": "Bench Press", "sets": 2}).get_json()
    assert we["previous"][0] == {"reps": 7, "weight": 62.5}
    assert we["sets"][0]["weight"] == 62.5


def test_save_workout_as_template(client, app):
    login(client)
    wid = int(client.post("/workouts/start").headers["Location"].rsplit("/", 1)[1])
    we = client.post(f"/api/workouts/{wid}/exercises", json={"name": "Deadlift", "sets": 2}).get_json()
    for s in we["sets"]:
        client.patch(f"/api/sets/{s['id']}", json={"reps": 5, "weight": 140, "completed": True})
    client.post(f"/workouts/{wid}/finish")
    r = client.post(f"/workouts/{wid}/save-template", data={"name": "Pull Day"})
    assert r.status_code == 302
    with app.app_context():
        t = WorkoutTemplate.query.filter_by(name="Pull Day").one()
        assert t.exercises[0].sets == 2 and t.exercises[0].weight == 140


def test_discard_and_reorder(client, app):
    login(client)
    wid = int(client.post("/workouts/start").headers["Location"].rsplit("/", 1)[1])
    a = client.post(f"/api/workouts/{wid}/exercises", json={"name": "Squat A"}).get_json()
    b = client.post(f"/api/workouts/{wid}/exercises", json={"name": "Squat B"}).get_json()
    client.patch(f"/api/workout-exercises/{b['id']}", json={"move": "up", "rest_seconds": 45})
    data = client.get(f"/api/workouts/{wid}").get_json()
    assert [e["name"] for e in data["exercises"]] == ["Squat B", "Squat A"]
    assert data["exercises"][0]["rest_seconds"] == 45

    client.delete(f"/api/sets/{a['sets'][0]['id']}")
    client.delete(f"/api/workout-exercises/{a['id']}")
    client.post(f"/workouts/{wid}/delete")
    with app.app_context():
        assert Workout.query.count() == 0 and SetEntry.query.count() == 0


def test_users_are_isolated(app):
    c1, c2 = app.test_client(), app.test_client()
    login(c1, "one@example.com")
    login(c2, "two@example.com")
    make_template(c1)
    wid = int(c1.post("/workouts/start").headers["Location"].rsplit("/", 1)[1])
    we = c1.post(f"/api/workouts/{wid}/exercises", json={"name": "Bench Press"}).get_json()

    with app.app_context():
        tid = WorkoutTemplate.query.one().id
    assert c2.get(f"/templates/{tid}/edit").status_code == 404
    assert c2.post("/workouts/start", data={"template_id": tid}).status_code == 404
    assert c2.get(f"/api/workouts/{wid}").status_code == 404
    assert c2.patch(f"/api/sets/{we['sets'][0]['id']}", json={"reps": 1}).status_code == 404
    assert c2.post(f"/workouts/{wid}/delete").status_code == 404
    # Custom exercise from user one isn't visible to user two
    assert b"My Custom Press" not in c2.get("/templates/new").data


def test_settings(client, app):
    login(client)
    client.post("/settings", data={"name": "Sam", "unit": "lb", "default_rest_seconds": "150"})
    with app.app_context():
        u = User.query.one()
        assert (u.name, u.unit, u.default_rest_seconds) == ("Sam", "lb", 150)


def test_identity_linking_by_verified_email(app):
    from app.auth import _login_from_claims

    with app.test_request_context():
        _login_from_claims("google", {"sub": "g-1", "email": "Same@Example.com", "email_verified": True, "name": "G"})
        _login_from_claims("apple", {"sub": "a-1", "email": "same@example.com", "email_verified": "true"})
        # Unverified email must not link to an existing account
        _login_from_claims("apple", {"sub": "a-2", "email": "same@example.com", "email_verified": False})
        assert User.query.count() == 2
        same = User.query.filter_by(email="same@example.com").one()
        assert {i.provider for i in same.identities} == {"google", "apple"}
        assert OAuthIdentity.query.count() == 3


def test_apple_client_secret(app):
    from app.auth import _apple_client_secret

    key = ec.generate_private_key(ec.SECP256R1())
    pem = key.private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()
    ).decode()
    app.config.update(APPLE_CLIENT_ID="com.example.web", APPLE_TEAM_ID="TEAM123", APPLE_KEY_ID="KEY123",
                      APPLE_PRIVATE_KEY=pem.replace("\n", "\\n"))
    with app.app_context():
        token = _apple_client_secret()
    decoded = jwt.decode(token, ECKey.import_key(pem))
    assert decoded.header["kid"] == "KEY123" and decoded.header["alg"] == "ES256"
    assert decoded.claims["iss"] == "TEAM123" and decoded.claims["sub"] == "com.example.web"
    assert decoded.claims["aud"] == "https://appleid.apple.com"


def test_oauth_providers_registered_when_configured():
    from app.auth import providers

    google_app = create_app({"SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:", "GOOGLE_CLIENT_ID": "gid",
                             "GOOGLE_CLIENT_SECRET": "gsecret", "AUTO_INIT_DB": False, "TESTING": True})
    plain_app = create_app({"SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:", "AUTO_INIT_DB": False, "TESTING": True})
    with google_app.test_request_context():
        assert providers() == ["google"]
    with plain_app.test_request_context():
        assert providers() == []
    assert b"Continue with Google" in google_app.test_client().get("/auth/login").data
    assert plain_app.test_client().get("/auth/login/apple").status_code == 404


def test_healthz(client):
    assert client.get("/healthz").get_json() == {"status": "ok"}

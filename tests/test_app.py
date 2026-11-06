import json

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec
from joserfc import jwt
from joserfc.jwk import ECKey

from app import create_app
from app.extensions import db
from app.models import OAuthIdentity, SetEntry, User, Workout, WorkoutTemplate

PASSWORD = "correct-horse"


@pytest.fixture
def app():
    app = create_app(
        {
            "TESTING": True,
            "SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:",
            "WTF_CSRF_ENABLED": False,
        }
    )
    with app.app_context():
        db.create_all()
    yield app


@pytest.fixture
def client(app):
    return app.test_client()


def register(client, email="lifter@example.com", password=PASSWORD):
    return client.post(
        "/auth/register", data={"email": email, "password": password, "confirm": password}
    )


def make_template(client, name="Push Day"):
    payload = {
        "name": name,
        "notes": "",
        "exercises": [
            {
                "name": "Bench Press",
                "sets": [
                    {"reps": 8, "weight": 60, "rest_seconds": 120},
                    {"reps": 8, "weight": 60, "rest_seconds": 120},
                    {"reps": 6, "weight": 65, "rest_seconds": 180},
                ],
            },
            {"name": "My Custom Press", "sets": [{"reps": 12, "weight": "", "rest_seconds": 60}]},
        ],
    }
    return client.post("/templates/new", data={"payload": json.dumps(payload)})


def start(client, template_id=None):
    data = {"template_id": template_id} if template_id else {}
    r = client.post("/workouts/start", data=data)
    return int(r.headers["Location"].rsplit("/", 1)[1])


# --------------------------------------------------------------------------- auth


def test_requires_login(client):
    r = client.get("/")
    assert r.status_code == 302 and "/auth/login" in r.headers["Location"]
    assert client.get("/api/workouts/1").status_code == 401


def test_register_login_logout(client, app):
    r = register(client, "New@Example.com")
    assert r.status_code == 302 and r.headers["Location"] == "/"
    with app.app_context():
        u = User.query.one()
        assert u.email == "new@example.com" and u.password_hash and u.password_hash != PASSWORD

    client.post("/auth/logout")
    assert client.get("/").status_code == 302

    r = client.post("/auth/login", data={"email": "new@example.com", "password": "wrong-pass"})
    assert b"Incorrect email or password" in r.data
    r = client.post("/auth/login", data={"email": "NEW@example.com ", "password": PASSWORD})
    assert r.status_code == 302 and client.get("/").status_code == 200


def test_register_validation(client, app):
    assert b"at least 8" in register(client, password="short").data
    assert b"valid email" in register(client, email="nope").data
    r = client.post("/auth/register", data={"email": "a@b.co", "password": PASSWORD, "confirm": "different1"})
    assert b"match" in r.data
    register(client, "dup@example.com")
    client.post("/auth/logout")
    assert b"already exists" in register(client, "dup@example.com").data
    with app.app_context():
        assert User.query.count() == 1


def test_change_password(client, app):
    register(client)
    r = client.post("/settings", data={"form": "password", "current_password": "nope-nope",
                                       "new_password": "newpassword", "confirm": "newpassword"},
                    follow_redirects=True)
    assert b"Current password is incorrect" in r.data
    client.post("/settings", data={"form": "password", "current_password": PASSWORD,
                                   "new_password": "newpassword", "confirm": "newpassword"})
    client.post("/auth/logout")
    assert client.post("/auth/login", data={"email": "lifter@example.com", "password": "newpassword"}).status_code == 302


def test_sso_links_to_password_account_and_drops_unverified_password(app):
    from app.auth import _login_from_claims

    with app.test_request_context():
        squatter = User(email="victim@example.com")
        squatter.set_password(PASSWORD)
        db.session.add(squatter)
        db.session.commit()

        _login_from_claims("google", {"sub": "g-1", "email": "victim@example.com", "email_verified": True})
        u = User.query.one()
        assert u.password_hash is None and u.email_verified
        assert [i.provider for i in u.identities] == ["google"]

        # Once the email is verified, a password set afterwards survives another SSO login.
        u.set_password("brand-new-pass")
        db.session.commit()
        _login_from_claims("apple", {"sub": "a-1", "email": "victim@example.com", "email_verified": "true"})
        assert u.check_password("brand-new-pass")


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
    plain_login = plain_app.test_client().get("/auth/login").data
    assert b"Continue with" not in plain_login and b"Password" in plain_login
    assert plain_app.test_client().get("/auth/login/apple").status_code == 404


# --------------------------------------------------------------------------- templates & workouts


def test_template_sets_are_individual_entries(client, app):
    register(client)
    assert make_template(client).status_code == 302
    with app.app_context():
        t = WorkoutTemplate.query.one()
        bench = t.exercises[0]
        assert [(s.reps, s.weight, s.rest_seconds) for s in bench.sets] == [(8, 60, 120), (8, 60, 120), (6, 65, 180)]
        assert t.exercises[1].sets[0].weight is None

    # Editor round-trips the per-set data
    page = client.get(f"/templates/{t.id}/edit").data.decode()
    assert '"rest_seconds": 180' in page and '"weight": 65.0' in page

    # Validation error keeps what the user typed
    r = client.post("/templates/new", data={"payload": json.dumps({"name": "", "exercises": []})})
    assert b"Give the template a name" in r.data


def test_workout_from_template_and_template_learns(client, app):
    register(client)
    make_template(client)
    with app.app_context():
        tid = WorkoutTemplate.query.one().id

    wid = start(client, tid)
    data = client.get(f"/api/workouts/{wid}").get_json()
    bench = data["exercises"][0]
    assert [(s["weight"], s["reps"], s["rest_seconds"]) for s in bench["sets"]] == [(60, 8, 120), (60, 8, 120), (65, 6, 180)]

    # Can't start a second workout while one is active
    assert start(client) == wid

    # User goes heavier on sets 1 and 2, skips set 3
    for s in bench["sets"][:2]:
        r = client.patch(f"/api/sets/{s['id']}", json={"reps": 7, "weight": "62.5", "completed": True})
        assert r.status_code == 200 and r.get_json()["completed"] is True
    r = client.post(f"/workouts/{wid}/finish", data={"template_update": "values"}, follow_redirects=True)
    assert "updated (weights &amp; reps)" in r.data.decode()

    with app.app_context():
        w = db.session.get(Workout, wid)
        assert w.finished_at is not None and w.total_volume == 2 * 7 * 62.5
        t = db.session.get(WorkoutTemplate, tid)
        sets = t.exercises[0].sets
        # Completed sets updated the template; the skipped set kept its old target.
        assert [(s.weight, s.reps) for s in sets] == [(62.5, 7), (62.5, 7), (65, 6)]
        assert [s.rest_seconds for s in sets] == [120, 120, 180]

    # Next time, the template's new numbers are the defaults
    wid2 = start(client, tid)
    bench2 = client.get(f"/api/workouts/{wid2}").get_json()["exercises"][0]
    assert [(s["weight"], s["reps"]) for s in bench2["sets"]] == [(62.5, 7), (62.5, 7), (65, 6)]

    # Finished workouts are read-only through the API
    assert client.patch(f"/api/sets/{bench['sets'][2]['id']}", json={"reps": 1}).status_code == 409


def _template_shape(app, tid):
    with app.app_context():
        t = db.session.get(WorkoutTemplate, tid)
        return [
            (te.exercise.name, [(s.weight, s.reps, s.rest_seconds) for s in te.sets]) for te in t.exercises
        ]


def _template_workout_with_changes(client, app):
    """Start Push Day, then: do bench sets 1-2 heavier, delete bench set 3, add a 4th-style
    extra set, drop "My Custom Press", add Dips. Returns (template id, workout id)."""
    make_template(client)
    with app.app_context():
        tid = WorkoutTemplate.query.one().id
    wid = start(client, tid)
    data = client.get(f"/api/workouts/{wid}").get_json()
    bench, custom = data["exercises"]
    for s in bench["sets"][:2]:
        client.patch(f"/api/sets/{s['id']}", json={"reps": 7, "weight": 62.5, "completed": True})
    client.delete(f"/api/sets/{bench['sets'][2]['id']}")
    extra = client.post(f"/api/workout-exercises/{bench['id']}/sets").get_json()
    client.patch(f"/api/sets/{extra['id']}", json={"reps": 5, "weight": 70, "rest_seconds": 200, "completed": True})
    client.delete(f"/api/workout-exercises/{custom['id']}")
    dips = client.post(f"/api/workouts/{wid}/exercises", json={"name": "Chest Dip"}).get_json()
    client.patch(f"/api/sets/{dips['sets'][0]['id']}", json={"reps": 12, "weight": 0, "completed": True})
    return tid, wid


ORIGINAL_SHAPE = [
    ("Bench Press", [(60, 8, 120), (60, 8, 120), (65, 6, 180)]),
    ("My Custom Press", [(None, 12, 60)]),
]


def test_finish_without_updating_template(client, app):
    register(client)
    tid, wid = _template_workout_with_changes(client, app)
    r = client.post(f"/workouts/{wid}/finish", data={"template_update": "none"}, follow_redirects=True)
    assert b"Workout saved. Nice work!" in r.data
    assert _template_shape(app, tid) == ORIGINAL_SHAPE
    # A missing or unknown choice also leaves the template alone
    wid2 = start(client, tid)
    client.post(f"/workouts/{wid2}/finish", data={"template_update": "bogus"})
    assert _template_shape(app, tid) == ORIGINAL_SHAPE


def test_finish_updating_template_values_only(client, app):
    register(client)
    tid, wid = _template_workout_with_changes(client, app)
    client.post(f"/workouts/{wid}/finish", data={"template_update": "values"})
    # Same sets and exercises; positions 1-2 got the new numbers. Position 3 in the workout
    # is now the extra 70x5 set, which was completed, so it updates template set 3.
    assert _template_shape(app, tid) == [
        ("Bench Press", [(62.5, 7, 120), (62.5, 7, 120), (70, 5, 180)]),
        ("My Custom Press", [(None, 12, 60)]),
    ]


def test_finish_updating_template_values_and_exercises(client, app):
    register(client)
    tid, wid = _template_workout_with_changes(client, app)
    r = client.post(f"/workouts/{wid}/finish", data={"template_update": "full"}, follow_redirects=True)
    assert "weights, reps &amp; exercises" in r.data.decode()
    assert _template_shape(app, tid) == [
        ("Bench Press", [(62.5, 7, 120), (62.5, 7, 120), (70, 5, 200)]),
        ("Chest Dip", [(0, 12, 90)]),
    ]
    # Next time the template is used it follows the new shape
    wid2 = start(client, tid)
    ex = client.get(f"/api/workouts/{wid2}").get_json()["exercises"]
    assert [e["name"] for e in ex] == ["Bench Press", "Chest Dip"]
    assert [(s["weight"], s["reps"]) for s in ex[0]["sets"]] == [(62.5, 7), (62.5, 7), (70, 5)]


def test_full_update_keeps_targets_for_sets_not_done(client, app):
    register(client)
    make_template(client)
    with app.app_context():
        tid = WorkoutTemplate.query.one().id
    wid = start(client, tid)
    bench = client.get(f"/api/workouts/{wid}").get_json()["exercises"][0]
    # Only set 1 done; user typed a different weight into set 3 but never did it
    client.patch(f"/api/sets/{bench['sets'][0]['id']}", json={"reps": 9, "completed": True})
    client.patch(f"/api/sets/{bench['sets'][2]['id']}", json={"weight": 999})
    client.post(f"/workouts/{wid}/finish", data={"template_update": "full"})
    assert _template_shape(app, tid)[0] == ("Bench Press", [(60, 9, 120), (60, 8, 120), (65, 6, 180)])


def test_discarded_workout_does_not_change_template(client, app):
    register(client)
    make_template(client)
    with app.app_context():
        tid = WorkoutTemplate.query.one().id
    wid = start(client, tid)
    s = client.get(f"/api/workouts/{wid}").get_json()["exercises"][0]["sets"][0]
    client.patch(f"/api/sets/{s['id']}", json={"reps": 1, "weight": 200, "completed": True})
    client.post(f"/workouts/{wid}/delete")
    with app.app_context():
        assert db.session.get(WorkoutTemplate, tid).exercises[0].sets[0].weight == 60


def test_add_set_prefills_from_previous_workout(client, app):
    register(client)
    # Last time: chin-ups 3 sets — bodyweight+10 x 8, +10 x 7, +5 x 6
    wid = start(client)
    we = client.post(f"/api/workouts/{wid}/exercises", json={"name": "Chin-up"}).get_json()
    assert len(we["sets"]) == 1
    first = we["sets"][0]
    client.patch(f"/api/sets/{first['id']}", json={"reps": 8, "weight": 10, "rest_seconds": 150, "completed": True})
    for reps, weight in [(7, 10), (6, 5)]:
        s = client.post(f"/api/workout-exercises/{we['id']}/sets").get_json()
        assert s["rest_seconds"] == 150  # rest copies the set above
        client.patch(f"/api/sets/{s['id']}", json={"reps": reps, "weight": weight, "completed": True})
    client.post(f"/workouts/{wid}/finish")

    # This time: each added set defaults to the same set number from last time
    wid2 = start(client)
    we2 = client.post(f"/api/workouts/{wid2}/exercises", json={"name": "chin-up"}).get_json()
    assert we2["name"] == "Chin-up"
    assert (we2["sets"][0]["weight"], we2["sets"][0]["reps"]) == (10, 8)
    s2 = client.post(f"/api/workout-exercises/{we2['id']}/sets").get_json()
    s3 = client.post(f"/api/workout-exercises/{we2['id']}/sets").get_json()
    s4 = client.post(f"/api/workout-exercises/{we2['id']}/sets").get_json()
    assert (s2["weight"], s2["reps"]) == (10, 7)
    assert (s3["weight"], s3["reps"]) == (5, 6)
    assert (s4["weight"], s4["reps"]) == (5, 6)  # beyond last time: copy the set above
    assert we2["previous"] == [{"reps": 8, "weight": 10}, {"reps": 7, "weight": 10}, {"reps": 6, "weight": 5}]

    # Per-set rest can be changed
    r = client.patch(f"/api/sets/{s2['id']}", json={"rest_seconds": 45})
    assert r.get_json()["rest_seconds"] == 45


def test_save_workout_as_template(client, app):
    register(client)
    wid = start(client)
    we = client.post(f"/api/workouts/{wid}/exercises", json={"name": "Deadlift"}).get_json()
    client.post(f"/api/workout-exercises/{we['id']}/sets")
    sets = client.get(f"/api/workouts/{wid}").get_json()["exercises"][0]["sets"]
    for s, w in zip(sets, (140, 150)):
        client.patch(f"/api/sets/{s['id']}", json={"reps": 5, "weight": w, "completed": True})
    client.post(f"/workouts/{wid}/finish")
    r = client.post(f"/workouts/{wid}/save-template", data={"name": "Pull Day"})
    assert r.status_code == 302
    with app.app_context():
        t = WorkoutTemplate.query.filter_by(name="Pull Day").one()
        assert [(s.weight, s.reps) for s in t.exercises[0].sets] == [(140, 5), (150, 5)]


def test_discard_and_reorder(client, app):
    register(client)
    wid = start(client)
    a = client.post(f"/api/workouts/{wid}/exercises", json={"name": "Squat A"}).get_json()
    b = client.post(f"/api/workouts/{wid}/exercises", json={"name": "Squat B"}).get_json()
    client.patch(f"/api/workout-exercises/{b['id']}", json={"move": "up"})
    data = client.get(f"/api/workouts/{wid}").get_json()
    assert [e["name"] for e in data["exercises"]] == ["Squat B", "Squat A"]

    client.delete(f"/api/sets/{a['sets'][0]['id']}")
    client.delete(f"/api/workout-exercises/{a['id']}")
    client.post(f"/workouts/{wid}/delete")
    with app.app_context():
        assert Workout.query.count() == 0 and SetEntry.query.count() == 0


def test_users_are_isolated(app):
    c1, c2 = app.test_client(), app.test_client()
    register(c1, "one@example.com")
    register(c2, "two@example.com")
    make_template(c1)
    wid = start(c1)
    we = c1.post(f"/api/workouts/{wid}/exercises", json={"name": "Bench Press"}).get_json()

    with app.app_context():
        tid = WorkoutTemplate.query.one().id
    assert c2.get(f"/templates/{tid}/edit").status_code == 404
    assert c2.post("/workouts/start", data={"template_id": tid}).status_code == 404
    assert c2.get(f"/api/workouts/{wid}").status_code == 404
    assert c2.patch(f"/api/sets/{we['sets'][0]['id']}", json={"reps": 1}).status_code == 404
    assert c2.post(f"/api/workout-exercises/{we['id']}/sets").status_code == 404
    assert c2.post(f"/workouts/{wid}/delete").status_code == 404
    # Custom exercise from user one isn't visible to user two
    assert b"My Custom Press" not in c2.get("/templates/new").data


def test_settings(client, app):
    register(client)
    client.post("/settings", data={"name": "Sam", "unit": "lb", "default_rest_seconds": "150"})
    with app.app_context():
        u = User.query.one()
        assert (u.name, u.unit, u.default_rest_seconds) == ("Sam", "lb", 150)


def test_pages_render(client):
    register(client)
    make_template(client)
    for url in ("/", "/templates", "/templates/new", "/history", "/settings"):
        assert client.get(url).status_code == 200, url


def test_healthz(client):
    assert client.get("/healthz").get_json() == {"status": "ok"}


def test_outdated_schema_is_reported(tmp_path):
    import sqlite3

    from app import SchemaOutdated, check_schema

    path = tmp_path / "old.db"
    con = sqlite3.connect(path)
    con.execute("CREATE TABLE user (id INTEGER PRIMARY KEY, email VARCHAR(255))")  # pre-password schema
    con.commit()
    con.close()
    app = create_app({"SQLALCHEMY_DATABASE_URI": f"sqlite:///{path}", "AUTO_INIT_DB": False, "TESTING": True})
    with app.app_context():
        db.create_all()
        with pytest.raises(SchemaOutdated, match="user.password_hash"):
            check_schema()


def test_insecure_secret_key_refused():
    with pytest.raises(RuntimeError, match="SECRET_KEY"):
        create_app({"SECRET_KEY": "change-me", "SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:", "AUTO_INIT_DB": False})

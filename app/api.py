"""JSON endpoints used by the live workout screen (static/js/workout.js)."""

from flask import Blueprint, abort, request
from flask_login import current_user, login_required

from .extensions import db
from .models import Exercise, SetEntry, Workout, WorkoutExercise, utcnow
from .services import (
    add_exercise_to_workout,
    owned_or_404,
    parse_float,
    parse_int,
    set_to_dict,
    workout_exercise_to_dict,
    workout_to_dict,
)

bp = Blueprint("api", __name__, url_prefix="/api")


def _active_workout(workout_id):
    workout = owned_or_404(Workout, workout_id)
    if not workout.is_active:
        abort(409, "Workout already finished")
    return workout


def _workout_exercise(we_id):
    we = db.session.get(WorkoutExercise, we_id)
    if we is None or we.workout.user_id != current_user.id:
        abort(404)
    if not we.workout.is_active:
        abort(409, "Workout already finished")
    return we


def _set(set_id):
    s = db.session.get(SetEntry, set_id)
    if s is None or s.workout_exercise.workout.user_id != current_user.id:
        abort(404)
    if not s.workout_exercise.workout.is_active:
        abort(409, "Workout already finished")
    return s


@bp.errorhandler(404)
@bp.errorhandler(409)
@bp.errorhandler(400)
def _json_error(err):
    return {"error": getattr(err, "description", str(err))}, err.code


@bp.get("/workouts/<int:workout_id>")
@login_required
def get_workout(workout_id):
    return workout_to_dict(owned_or_404(Workout, workout_id))


@bp.patch("/workouts/<int:workout_id>")
@login_required
def update_workout(workout_id):
    workout = _active_workout(workout_id)
    data = request.get_json(silent=True) or {}
    if "name" in data:
        workout.name = (str(data["name"]).strip() or "Workout")[:120]
    if "notes" in data:
        workout.notes = str(data["notes"]).strip() or None
    db.session.commit()
    return {"ok": True}


@bp.post("/workouts/<int:workout_id>/exercises")
@login_required
def add_exercise(workout_id):
    workout = _active_workout(workout_id)
    data = request.get_json(silent=True) or {}
    exercise = None
    if data.get("exercise_id"):
        exercise = db.session.get(Exercise, int(data["exercise_id"]))
        if exercise is None or exercise.user_id not in (None, current_user.id):
            abort(404)
    elif data.get("name"):
        exercise = Exercise.get_or_create(current_user, str(data["name"]))
    if exercise is None:
        abort(400, "Exercise name required")
    we = add_exercise_to_workout(workout, exercise, sets=parse_int(data.get("sets"), 1, 20) or 1)
    db.session.commit()
    return workout_exercise_to_dict(we), 201


@bp.patch("/workout-exercises/<int:we_id>")
@login_required
def update_workout_exercise(we_id):
    we = _workout_exercise(we_id)
    data = request.get_json(silent=True) or {}
    if "rest_seconds" in data:
        we.rest_seconds = parse_int(data["rest_seconds"], 0, 3600) or 0
    if "move" in data and data["move"] in ("up", "down"):
        siblings = list(we.workout.exercises)
        i = siblings.index(we)
        j = i - 1 if data["move"] == "up" else i + 1
        if 0 <= j < len(siblings):
            siblings[i], siblings[j] = siblings[j], siblings[i]
            for pos, item in enumerate(siblings):
                item.position = pos
    db.session.commit()
    return {"ok": True}


@bp.delete("/workout-exercises/<int:we_id>")
@login_required
def delete_workout_exercise(we_id):
    we = _workout_exercise(we_id)
    db.session.delete(we)
    db.session.commit()
    return {"ok": True}


@bp.post("/workout-exercises/<int:we_id>/sets")
@login_required
def add_set(we_id):
    we = _workout_exercise(we_id)
    last = we.sets[-1] if we.sets else None
    s = SetEntry(
        position=(last.position + 1) if last else 0,
        reps=last.reps if last else None,
        weight=last.weight if last else None,
    )
    we.sets.append(s)
    db.session.commit()
    return set_to_dict(s), 201


@bp.patch("/sets/<int:set_id>")
@login_required
def update_set(set_id):
    s = _set(set_id)
    data = request.get_json(silent=True) or {}
    if "reps" in data:
        s.reps = parse_int(data["reps"], 0, 1000)
    if "weight" in data:
        s.weight = parse_float(data["weight"])
    if "completed" in data:
        s.completed = bool(data["completed"])
        s.completed_at = utcnow() if s.completed else None
    db.session.commit()
    return set_to_dict(s)


@bp.delete("/sets/<int:set_id>")
@login_required
def delete_set(set_id):
    s = _set(set_id)
    we = s.workout_exercise
    we.sets.remove(s)
    for pos, item in enumerate(we.sets):
        item.position = pos
    db.session.commit()
    return {"ok": True}

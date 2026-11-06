"""Workout logic shared by the HTML views and the JSON API."""

from flask import abort
from flask_login import current_user

from .extensions import db
from .models import (
    Exercise,
    SetEntry,
    TemplateExercise,
    Workout,
    WorkoutExercise,
    WorkoutTemplate,
    utcnow,
)


def owned_or_404(model, obj_id):
    obj = db.session.get(model, obj_id)
    if obj is None or obj.user_id != current_user.id:
        abort(404)
    return obj


def active_workout(user):
    return (
        Workout.query.filter_by(user_id=user.id, finished_at=None)
        .order_by(Workout.started_at.desc())
        .first()
    )


def previous_sets(user, exercise_id, exclude_workout_id=None):
    """Sets from the most recent finished workout that included this exercise."""
    q = (
        WorkoutExercise.query.join(Workout)
        .filter(
            Workout.user_id == user.id,
            Workout.finished_at.isnot(None),
            WorkoutExercise.exercise_id == exercise_id,
        )
        .order_by(Workout.finished_at.desc())
    )
    if exclude_workout_id:
        q = q.filter(Workout.id != exclude_workout_id)
    we = q.first()
    if we is None:
        return []
    return [s for s in we.sets if s.completed] or list(we.sets)


def add_exercise_to_workout(workout, exercise, sets=1, reps=None, weight=None, rest_seconds=None):
    position = max((we.position for we in workout.exercises), default=-1) + 1
    we = WorkoutExercise(
        exercise=exercise,
        position=position,
        rest_seconds=rest_seconds if rest_seconds is not None else current_user.default_rest_seconds,
    )
    workout.exercises.append(we)
    prev = previous_sets(current_user, exercise.id, exclude_workout_id=workout.id)
    for i in range(max(1, sets)):
        p = prev[i] if i < len(prev) else (prev[-1] if prev else None)
        we.sets.append(
            SetEntry(
                position=i,
                reps=reps if reps is not None else (p.reps if p else None),
                weight=weight if weight is not None else (p.weight if p else None),
            )
        )
    return we


def start_workout(user, template=None):
    workout = Workout(user_id=user.id, name=template.name if template else "Workout")
    if template:
        workout.template_id = template.id
    db.session.add(workout)
    db.session.flush()
    if template:
        for te in template.exercises:
            add_exercise_to_workout(
                workout, te.exercise, sets=te.sets, reps=te.reps, weight=te.weight, rest_seconds=te.rest_seconds
            )
    db.session.commit()
    return workout


def finish_workout(workout):
    # Drop sets that were never touched, then exercises left with no sets.
    for we in list(workout.exercises):
        for s in list(we.sets):
            if not s.completed and s.reps is None and s.weight is None:
                we.sets.remove(s)
        if not we.sets:
            workout.exercises.remove(we)
    workout.finished_at = utcnow()
    db.session.commit()


def save_workout_as_template(user, workout, name):
    template = WorkoutTemplate(user_id=user.id, name=name or workout.name)
    for i, we in enumerate(workout.exercises):
        done = [s for s in we.sets if s.completed] or we.sets
        last = done[-1] if done else None
        template.exercises.append(
            TemplateExercise(
                exercise_id=we.exercise_id,
                position=i,
                sets=max(1, len(done)),
                reps=last.reps if last else None,
                weight=last.weight if last else None,
                rest_seconds=we.rest_seconds,
            )
        )
    db.session.add(template)
    db.session.commit()
    return template


# --------------------------------------------------------------------------- serialisation


def set_to_dict(s):
    return {
        "id": s.id,
        "position": s.position,
        "reps": s.reps,
        "weight": s.weight,
        "completed": s.completed,
    }


def workout_exercise_to_dict(we):
    prev = previous_sets(current_user, we.exercise_id, exclude_workout_id=we.workout_id)
    return {
        "id": we.id,
        "exercise_id": we.exercise_id,
        "name": we.exercise.name,
        "rest_seconds": we.rest_seconds,
        "sets": [set_to_dict(s) for s in we.sets],
        "previous": [{"reps": p.reps, "weight": p.weight} for p in prev],
    }


def workout_to_dict(workout):
    return {
        "id": workout.id,
        "name": workout.name,
        "notes": workout.notes or "",
        "started_at": workout.started_at.isoformat() + "Z",
        "finished_at": workout.finished_at.isoformat() + "Z" if workout.finished_at else None,
        "unit": current_user.unit,
        "exercises": [workout_exercise_to_dict(we) for we in workout.exercises],
    }


def parse_int(value, lo=None, hi=None):
    if value in (None, ""):
        return None
    try:
        v = int(float(value))
    except (TypeError, ValueError):
        return None
    if lo is not None and v < lo:
        return lo
    if hi is not None and v > hi:
        return hi
    return v


def parse_float(value, lo=0.0, hi=10000.0):
    if value in (None, ""):
        return None
    try:
        v = float(str(value).replace(",", "."))
    except (TypeError, ValueError):
        return None
    if v != v:  # NaN
        return None
    return max(lo, min(hi, round(v, 2)))


def exercise_names_for(user):
    return [e.name for e in Exercise.visible_to(user)]

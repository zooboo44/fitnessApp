"""Workout logic shared by the HTML views and the JSON API."""

from flask import abort
from flask_login import current_user

from .extensions import db
from .models import (
    Exercise,
    SetEntry,
    TemplateExercise,
    TemplateSet,
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


def new_set_for(we, prev=None):
    """Build the next set for a workout exercise, pre-filled with sensible defaults.

    Reps/weight: the same set number from the previous workout, else the set above it in
    this workout, else the last set of the previous workout.
    Rest: the set above it, else the previous workout's set, else the user's default.
    """
    if prev is None:
        prev = previous_sets(current_user, we.exercise_id, exclude_workout_id=we.workout_id)
    i = len(we.sets)
    same = prev[i] if i < len(prev) else None
    above = we.sets[-1] if we.sets else None
    source = same or above or (prev[-1] if prev else None)
    rest_source = above or same
    return SetEntry(
        position=i,
        reps=source.reps if source else None,
        weight=source.weight if source else None,
        rest_seconds=rest_source.rest_seconds if rest_source else (we.rest_seconds or current_user.default_rest_seconds),
    )


def add_exercise_to_workout(workout, exercise, sets=1):
    position = max((we.position for we in workout.exercises), default=-1) + 1
    we = WorkoutExercise(exercise=exercise, position=position, rest_seconds=current_user.default_rest_seconds)
    workout.exercises.append(we)
    prev = previous_sets(current_user, exercise.id, exclude_workout_id=workout.id)
    for _ in range(max(1, sets)):
        we.sets.append(new_set_for(we, prev))
    return we


def start_workout(user, template=None):
    workout = Workout(user_id=user.id, name=template.name if template else "Workout")
    if template:
        workout.template_id = template.id
    db.session.add(workout)
    db.session.flush()
    if template:
        for pos, te in enumerate(template.exercises):
            we = WorkoutExercise(
                exercise_id=te.exercise_id,
                position=pos,
                rest_seconds=te.sets[0].rest_seconds if te.sets else user.default_rest_seconds,
                template_exercise_id=te.id,
            )
            workout.exercises.append(we)
            prev = previous_sets(user, te.exercise_id, exclude_workout_id=workout.id)
            for i, ts in enumerate(te.sets):
                p = prev[i] if i < len(prev) else None
                we.sets.append(
                    SetEntry(
                        position=i,
                        reps=ts.reps if ts.reps is not None else (p.reps if p else None),
                        weight=ts.weight if ts.weight is not None else (p.weight if p else None),
                        rest_seconds=ts.rest_seconds,
                    )
                )
    db.session.commit()
    return workout


# How finishing a template workout affects the template:
TEMPLATE_KEEP = "none"  # save the workout only
TEMPLATE_VALUES = "values"  # update weight/reps of the template's existing sets
TEMPLATE_FULL = "full"  # also take on added/removed sets and exercises (and order, rest times)
TEMPLATE_UPDATE_MODES = (TEMPLATE_KEEP, TEMPLATE_VALUES, TEMPLATE_FULL)


def workout_template(workout):
    """The template this workout was started from, if it still exists."""
    template = db.session.get(WorkoutTemplate, workout.template_id) if workout.template_id else None
    if template is None or template.user_id != workout.user_id:
        return None
    return template


def _matching_template_exercise(template, we):
    """The template row a workout exercise came from. The template may have been edited
    mid-workout, so only rows that still belong to it with the same exercise count."""
    if not we.template_exercise_id:
        return None
    te = db.session.get(TemplateExercise, we.template_exercise_id)
    if te is None or te.template_id != template.id or te.exercise_id != we.exercise_id:
        return None
    return te


def _update_template_values(template, workout):
    """Copy weight/reps of completed sets into the matching template sets.
    Set count, exercises and rest times stay as they are."""
    for we in workout.exercises:
        te = _matching_template_exercise(template, we)
        if te is None:
            continue
        for s, ts in zip(we.sets, te.sets):
            if s.completed:
                ts.reps = s.reps
                ts.weight = s.weight


def _update_template_full(template, workout):
    """Rebuild the template's exercises and sets to match the workout: added or removed
    sets and exercises, the exercise order and each set's rest time all carry over.
    Weight/reps come from completed sets; a set that wasn't done keeps the template's
    old target for that position (or the workout's value if it's a new set)."""
    if not workout.exercises:
        return False
    rebuilt = []
    used = set()
    for pos, we in enumerate(workout.exercises):
        te = _matching_template_exercise(template, we)
        if te is None or te.id in used:
            te = TemplateExercise(exercise_id=we.exercise_id)
        else:
            used.add(te.id)
        te.position = pos
        old_sets = list(te.sets)
        new_sets = []
        for i, s in enumerate(we.sets):
            old = old_sets[i] if i < len(old_sets) else None
            source = s if (s.completed or old is None) else old
            new_sets.append(
                TemplateSet(position=i, reps=source.reps, weight=source.weight, rest_seconds=s.rest_seconds)
            )
        te.sets = new_sets
        rebuilt.append(te)
    template.exercises = rebuilt  # rows no longer listed are deleted (delete-orphan)
    return True


def finish_workout(workout, template_update=TEMPLATE_KEEP):
    """Mark the workout finished. Returns True if its template was changed."""
    # Drop sets that were never touched, then exercises left with no sets.
    for we in list(workout.exercises):
        for s in list(we.sets):
            if not s.completed and s.reps is None and s.weight is None:
                we.sets.remove(s)
        if not we.sets:
            workout.exercises.remove(we)
    workout.finished_at = utcnow()

    updated = False
    template = workout_template(workout)
    if template is not None and template_update == TEMPLATE_VALUES:
        _update_template_values(template, workout)
        updated = True
    elif template is not None and template_update == TEMPLATE_FULL:
        updated = _update_template_full(template, workout)
    db.session.commit()
    return updated


def save_workout_as_template(user, workout, name):
    template = WorkoutTemplate(user_id=user.id, name=name or workout.name)
    for i, we in enumerate(workout.exercises):
        done = [s for s in we.sets if s.completed] or list(we.sets)
        te = TemplateExercise(exercise_id=we.exercise_id, position=i)
        for j, s in enumerate(done):
            te.sets.append(TemplateSet(position=j, reps=s.reps, weight=s.weight, rest_seconds=s.rest_seconds))
        template.exercises.append(te)
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
        "rest_seconds": s.rest_seconds,
        "completed": s.completed,
    }


def workout_exercise_to_dict(we):
    prev = previous_sets(current_user, we.exercise_id, exclude_workout_id=we.workout_id)
    return {
        "id": we.id,
        "exercise_id": we.exercise_id,
        "name": we.exercise.name,
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
        "from_template": workout.template_id is not None,
        "exercises": [workout_exercise_to_dict(we) for we in workout.exercises],
    }


def template_to_dict(template):
    return {
        "name": template.name or "",
        "notes": template.notes or "",
        "exercises": [
            {
                "name": te.exercise.name,
                "sets": [
                    {"reps": ts.reps, "weight": ts.weight, "rest_seconds": ts.rest_seconds} for ts in te.sets
                ],
            }
            for te in template.exercises
        ],
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

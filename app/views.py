import json

from flask import Blueprint, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required

from .extensions import db
from .models import Exercise, TemplateExercise, TemplateSet, Workout, WorkoutTemplate
from .services import (
    active_workout,
    exercise_names_for,
    finish_workout,
    owned_or_404,
    parse_float,
    parse_int,
    save_workout_as_template,
    start_workout,
    template_to_dict,
)

bp = Blueprint("main", __name__)


@bp.route("/")
@login_required
def dashboard():
    templates = WorkoutTemplate.query.filter_by(user_id=current_user.id).order_by(WorkoutTemplate.name).all()
    recent = (
        Workout.query.filter(Workout.user_id == current_user.id, Workout.finished_at.isnot(None))
        .order_by(Workout.finished_at.desc())
        .limit(5)
        .all()
    )
    return render_template(
        "dashboard.html", templates=templates, recent=recent, active=active_workout(current_user)
    )


# --------------------------------------------------------------------------- templates


@bp.route("/templates")
@login_required
def template_list():
    templates = WorkoutTemplate.query.filter_by(user_id=current_user.id).order_by(WorkoutTemplate.name).all()
    return render_template("workout_templates/list.html", templates=templates)


def _save_template_from_form(template):
    """The template editor posts its contents as JSON in a hidden `payload` field."""
    try:
        data = json.loads(request.form.get("payload") or "{}")
    except ValueError:
        return "Could not read the template — please try again."
    name = str(data.get("name") or "").strip()
    if not name:
        return "Give the template a name."

    rows = []
    for ex in data.get("exercises") or []:
        ex_name = str(ex.get("name") or "").strip()
        sets = ex.get("sets") or []
        if not ex_name or not sets:
            continue
        exercise = Exercise.get_or_create(current_user, ex_name)
        te = TemplateExercise(exercise_id=exercise.id, position=len(rows))
        for i, st in enumerate(sets[:50]):
            te.sets.append(
                TemplateSet(
                    position=i,
                    reps=parse_int(st.get("reps"), 0, 1000),
                    weight=parse_float(st.get("weight")),
                    rest_seconds=parse_int(st.get("rest_seconds"), 0, 3600)
                    if st.get("rest_seconds") not in (None, "")
                    else current_user.default_rest_seconds,
                )
            )
        rows.append(te)
    if not rows:
        return "Add at least one exercise with at least one set."

    template.name = name[:120]
    template.notes = str(data.get("notes") or "").strip() or None
    template.exercises.clear()
    db.session.flush()
    template.exercises.extend(rows)
    return None


def _render_template_form(template, payload=None):
    return render_template(
        "workout_templates/form.html",
        template=template,
        payload=payload or template_to_dict(template),
        exercise_names=exercise_names_for(current_user),
    )


def _posted_payload():
    """Re-show what the user typed after a validation error."""
    try:
        return json.loads(request.form.get("payload") or "{}") or None
    except ValueError:
        return None


@bp.route("/templates/new", methods=["GET", "POST"])
@login_required
def template_new():
    template = WorkoutTemplate(user_id=current_user.id, name="")
    if request.method == "POST":
        error = _save_template_from_form(template)
        if error:
            db.session.rollback()
            flash(error, "error")
        else:
            db.session.add(template)
            db.session.commit()
            flash("Template created.", "success")
            return redirect(url_for("main.template_list"))
        return _render_template_form(template, _posted_payload())
    return _render_template_form(template)


@bp.route("/templates/<int:template_id>/edit", methods=["GET", "POST"])
@login_required
def template_edit(template_id):
    template = owned_or_404(WorkoutTemplate, template_id)
    if request.method == "POST":
        error = _save_template_from_form(template)
        if error:
            db.session.rollback()
            flash(error, "error")
            return _render_template_form(owned_or_404(WorkoutTemplate, template_id), _posted_payload())
        db.session.commit()
        flash("Template saved.", "success")
        return redirect(url_for("main.template_list"))
    return _render_template_form(template)


@bp.route("/templates/<int:template_id>/delete", methods=["POST"])
@login_required
def template_delete(template_id):
    template = owned_or_404(WorkoutTemplate, template_id)
    Workout.query.filter_by(template_id=template.id).update({"template_id": None})
    db.session.delete(template)
    db.session.commit()
    flash("Template deleted.", "success")
    return redirect(url_for("main.template_list"))


# --------------------------------------------------------------------------- workouts


@bp.route("/workouts/start", methods=["POST"])
@login_required
def workout_start():
    existing = active_workout(current_user)
    if existing:
        flash("You already have a workout in progress — finish or discard it first.", "error")
        return redirect(url_for("main.workout_view", workout_id=existing.id))
    template = None
    if request.form.get("template_id"):
        template = owned_or_404(WorkoutTemplate, int(request.form["template_id"]))
    workout = start_workout(current_user, template)
    return redirect(url_for("main.workout_view", workout_id=workout.id))


@bp.route("/workouts/<int:workout_id>")
@login_required
def workout_view(workout_id):
    workout = owned_or_404(Workout, workout_id)
    if workout.is_active:
        return render_template(
            "workouts/active.html", workout=workout, exercise_names=exercise_names_for(current_user)
        )
    return render_template("workouts/detail.html", workout=workout)


@bp.route("/workouts/<int:workout_id>/finish", methods=["POST"])
@login_required
def workout_finish(workout_id):
    workout = owned_or_404(Workout, workout_id)
    if workout.is_active:
        finish_workout(workout)
        flash("Workout saved. Nice work!", "success")
    return redirect(url_for("main.workout_view", workout_id=workout.id))


@bp.route("/workouts/<int:workout_id>/delete", methods=["POST"])
@login_required
def workout_delete(workout_id):
    workout = owned_or_404(Workout, workout_id)
    was_active = workout.is_active
    db.session.delete(workout)
    db.session.commit()
    flash("Workout discarded." if was_active else "Workout deleted.", "success")
    return redirect(url_for("main.dashboard" if was_active else "main.history"))


@bp.route("/workouts/<int:workout_id>/save-template", methods=["POST"])
@login_required
def workout_save_template(workout_id):
    workout = owned_or_404(Workout, workout_id)
    if not workout.exercises:
        flash("This workout has no exercises to save.", "error")
        return redirect(url_for("main.workout_view", workout_id=workout.id))
    template = save_workout_as_template(current_user, workout, (request.form.get("name") or "").strip())
    flash(f"Saved as template “{template.name}”.", "success")
    return redirect(url_for("main.template_edit", template_id=template.id))


@bp.route("/history")
@login_required
def history():
    page = parse_int(request.args.get("page"), 1) or 1
    pagination = (
        Workout.query.filter(Workout.user_id == current_user.id, Workout.finished_at.isnot(None))
        .order_by(Workout.finished_at.desc())
        .paginate(page=page, per_page=20, error_out=False)
    )
    return render_template("workouts/history.html", pagination=pagination)


# --------------------------------------------------------------------------- settings


@bp.route("/settings", methods=["GET", "POST"])
@login_required
def settings():
    if request.method == "POST" and request.form.get("form") == "password":
        from .auth import MIN_PASSWORD_LENGTH

        new = request.form.get("new_password") or ""
        if current_user.password_hash and not current_user.check_password(request.form.get("current_password") or ""):
            flash("Current password is incorrect.", "error")
        elif len(new) < MIN_PASSWORD_LENGTH:
            flash(f"Password must be at least {MIN_PASSWORD_LENGTH} characters.", "error")
        elif new != request.form.get("confirm"):
            flash("Passwords don't match.", "error")
        elif not current_user.email:
            flash("Your account has no email address, so a password can't be used to sign in.", "error")
        else:
            current_user.set_password(new)
            db.session.commit()
            flash("Password updated.", "success")
        return redirect(url_for("main.settings"))
    if request.method == "POST":
        current_user.name = (request.form.get("name") or "").strip()[:255] or None
        if request.form.get("unit") in ("kg", "lb"):
            current_user.unit = request.form["unit"]
        current_user.default_rest_seconds = parse_int(request.form.get("default_rest_seconds"), 0, 3600) or 90
        db.session.commit()
        flash("Settings saved.", "success")
        return redirect(url_for("main.settings"))
    return render_template("settings.html")

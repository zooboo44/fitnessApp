from datetime import datetime, timezone

from flask_login import UserMixin
from sqlalchemy import func
from werkzeug.security import check_password_hash, generate_password_hash

from .extensions import db


def utcnow():
    return datetime.now(timezone.utc).replace(tzinfo=None)


class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(255), unique=True, index=True)
    name = db.Column(db.String(255))
    unit = db.Column(db.String(2), nullable=False, default="lb")  # "lb" or "kg"
    default_rest_seconds = db.Column(db.Integer, nullable=False, default=90)
    password_hash = db.Column(db.String(255))
    # True once an SSO provider has vouched for this email address.
    email_verified = db.Column(db.Boolean, nullable=False, default=False)
    created_at = db.Column(db.DateTime, nullable=False, default=utcnow)

    identities = db.relationship("OAuthIdentity", back_populates="user", cascade="all, delete-orphan")

    def set_password(self, password):
        self.password_hash = generate_password_hash(password) if password else None

    def check_password(self, password):
        return bool(self.password_hash) and check_password_hash(self.password_hash, password)

    @property
    def display_name(self):
        return self.name or (self.email.split("@")[0] if self.email else "Athlete")


class OAuthIdentity(db.Model):
    """Links an external SSO account (provider + subject) to a local user."""

    id = db.Column(db.Integer, primary_key=True)
    provider = db.Column(db.String(20), nullable=False)  # "google" | "apple" | "dev"
    subject = db.Column(db.String(255), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False, index=True)
    created_at = db.Column(db.DateTime, nullable=False, default=utcnow)

    user = db.relationship("User", back_populates="identities")

    __table_args__ = (db.UniqueConstraint("provider", "subject"),)


class Exercise(db.Model):
    """Exercise library. user_id NULL = built-in exercise visible to everyone."""

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False)
    category = db.Column(db.String(40))
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), index=True)

    @classmethod
    def visible_to(cls, user):
        return cls.query.filter((cls.user_id.is_(None)) | (cls.user_id == user.id)).order_by(cls.name)

    @classmethod
    def get_or_create(cls, user, name):
        name = " ".join(name.split())
        if not name:
            return None
        ex = (
            cls.query.filter(func.lower(cls.name) == name.lower())
            .filter((cls.user_id.is_(None)) | (cls.user_id == user.id))
            .order_by(cls.user_id.is_(None).desc())
            .first()
        )
        if ex is None:
            ex = cls(name=name[:120], user_id=user.id)
            db.session.add(ex)
            db.session.flush()
        return ex


class WorkoutTemplate(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False, index=True)
    name = db.Column(db.String(120), nullable=False)
    notes = db.Column(db.Text)
    created_at = db.Column(db.DateTime, nullable=False, default=utcnow)
    updated_at = db.Column(db.DateTime, nullable=False, default=utcnow, onupdate=utcnow)

    exercises = db.relationship(
        "TemplateExercise",
        back_populates="template",
        cascade="all, delete-orphan",
        order_by="TemplateExercise.position",
    )


class TemplateExercise(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    template_id = db.Column(db.Integer, db.ForeignKey("workout_template.id"), nullable=False, index=True)
    exercise_id = db.Column(db.Integer, db.ForeignKey("exercise.id"), nullable=False)
    position = db.Column(db.Integer, nullable=False, default=0)

    template = db.relationship("WorkoutTemplate", back_populates="exercises")
    exercise = db.relationship("Exercise")
    sets = db.relationship(
        "TemplateSet",
        back_populates="template_exercise",
        cascade="all, delete-orphan",
        order_by="TemplateSet.position",
    )


class TemplateSet(db.Model):
    """One planned set in a template. Reps/weight are updated from the latest workout."""

    id = db.Column(db.Integer, primary_key=True)
    template_exercise_id = db.Column(
        db.Integer, db.ForeignKey("template_exercise.id"), nullable=False, index=True
    )
    position = db.Column(db.Integer, nullable=False, default=0)
    reps = db.Column(db.Integer)
    weight = db.Column(db.Float)
    rest_seconds = db.Column(db.Integer, nullable=False, default=90)

    template_exercise = db.relationship("TemplateExercise", back_populates="sets")


class Workout(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False, index=True)
    template_id = db.Column(db.Integer, db.ForeignKey("workout_template.id", ondelete="SET NULL"))
    name = db.Column(db.String(120), nullable=False)
    notes = db.Column(db.Text)
    started_at = db.Column(db.DateTime, nullable=False, default=utcnow)
    finished_at = db.Column(db.DateTime)

    exercises = db.relationship(
        "WorkoutExercise",
        back_populates="workout",
        cascade="all, delete-orphan",
        order_by="WorkoutExercise.position",
    )

    @property
    def is_active(self):
        return self.finished_at is None

    @property
    def duration_seconds(self):
        end = self.finished_at or utcnow()
        return int((end - self.started_at).total_seconds())

    @property
    def completed_sets(self):
        return [s for we in self.exercises for s in we.sets if s.completed]

    @property
    def total_volume(self):
        return sum((s.weight or 0) * (s.reps or 0) for s in self.completed_sets)


class WorkoutExercise(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    workout_id = db.Column(db.Integer, db.ForeignKey("workout.id"), nullable=False, index=True)
    exercise_id = db.Column(db.Integer, db.ForeignKey("exercise.id"), nullable=False)
    position = db.Column(db.Integer, nullable=False, default=0)
    # Default rest for sets added to this exercise when there is no earlier set to copy.
    rest_seconds = db.Column(db.Integer, nullable=False, default=90)
    # Which template row this came from, so finishing the workout can update the template.
    template_exercise_id = db.Column(db.Integer)

    workout = db.relationship("Workout", back_populates="exercises")
    exercise = db.relationship("Exercise")
    sets = db.relationship(
        "SetEntry",
        back_populates="workout_exercise",
        cascade="all, delete-orphan",
        order_by="SetEntry.position",
    )


class SetEntry(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    workout_exercise_id = db.Column(db.Integer, db.ForeignKey("workout_exercise.id"), nullable=False, index=True)
    position = db.Column(db.Integer, nullable=False, default=0)
    reps = db.Column(db.Integer)
    weight = db.Column(db.Float)
    # Rest timer that follows this set; starts when the set is marked done.
    rest_seconds = db.Column(db.Integer, nullable=False, default=90)
    completed = db.Column(db.Boolean, nullable=False, default=False)
    completed_at = db.Column(db.DateTime)

    workout_exercise = db.relationship("WorkoutExercise", back_populates="sets")

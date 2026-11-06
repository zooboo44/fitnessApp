from .extensions import db
from .models import Exercise

BUILTIN_EXERCISES = {
    "Chest": [
        "Bench Press", "Incline Bench Press", "Decline Bench Press", "Dumbbell Bench Press",
        "Incline Dumbbell Press", "Dumbbell Fly", "Cable Crossover", "Push-up", "Chest Dip",
    ],
    "Back": [
        "Deadlift", "Pull-up", "Chin-up", "Barbell Row", "Dumbbell Row", "Lat Pulldown",
        "Seated Cable Row", "T-Bar Row", "Face Pull",
    ],
    "Legs": [
        "Back Squat", "Front Squat", "Romanian Deadlift", "Leg Press", "Bulgarian Split Squat",
        "Walking Lunge", "Leg Extension", "Leg Curl", "Hip Thrust", "Standing Calf Raise",
        "Seated Calf Raise",
    ],
    "Shoulders": [
        "Overhead Press", "Dumbbell Shoulder Press", "Arnold Press", "Lateral Raise",
        "Front Raise", "Rear Delt Fly", "Upright Row", "Shrug",
    ],
    "Arms": [
        "Barbell Curl", "Dumbbell Curl", "Hammer Curl", "Preacher Curl", "Cable Curl",
        "Tricep Pushdown", "Skull Crusher", "Overhead Tricep Extension", "Close-Grip Bench Press",
        "Tricep Dip",
    ],
    "Core": ["Plank", "Hanging Leg Raise", "Cable Crunch", "Ab Wheel Rollout", "Russian Twist"],
}


def seed_exercises():
    existing = {e.name for e in Exercise.query.filter(Exercise.user_id.is_(None))}
    added = 0
    for category, names in BUILTIN_EXERCISES.items():
        for name in names:
            if name not in existing:
                db.session.add(Exercise(name=name, category=category, user_id=None))
                added += 1
    if added:
        db.session.commit()
    return added

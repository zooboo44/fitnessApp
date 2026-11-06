def fmt_duration(seconds):
    seconds = int(seconds or 0)
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    if h:
        return f"{h}h {m:02d}m"
    return f"{m}m {s:02d}s" if m else f"{s}s"


def fmt_weight(value):
    if value is None:
        return ""
    value = round(float(value), 2)
    return str(int(value)) if value.is_integer() else f"{value:g}"


def fmt_date(dt):
    return dt.strftime("%a, %b %-d %Y") if dt else ""


def register_filters(app):
    app.jinja_env.filters["duration"] = fmt_duration
    app.jinja_env.filters["weight"] = fmt_weight
    app.jinja_env.filters["date"] = fmt_date

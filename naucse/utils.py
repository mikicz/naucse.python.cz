from typing import Any, Dict
from datetime import date, datetime, time

from . import routes
from .models import Course


def get_course_from_slug(slug):
    # type: (str) -> Course
    parts = slug.split("/")

    if parts[0] == "course":
        return routes.model.courses[parts[1]]

    else:
        return routes.model.runs[(int(parts[0]), parts[1])]


def course_info(slug, *args, **kwargs):
    # type: (str) -> Dict[str, Any]
    
    course = get_course_from_slug(slug)
    if "course" in slug:
        attributes = Course.COURSE_INFO
    else:
        attributes = Course.RUN_INFO

    data = {}

    for attr in attributes:
        val = getattr(course, attr)

        if isinstance(val, (date, datetime, time)):
            val = val.isoformat()

        data[attr] = val

    return data


def render(page_type, slug, *args, **kwargs):
    course = get_course_from_slug(slug)

    with routes.app.test_request_context():

        if page_type == "course":
            return routes.course(course)

        if page_type == "course_page":
            lesson_slug, page, solution, *_ = args
            return routes.course_page(course, routes.model.get_lesson(lesson_slug), page, solution)

        if page_type == "session_coverpage":
            session, coverpage, *_ = args
            return routes.session_coverpage(course, session, coverpage)

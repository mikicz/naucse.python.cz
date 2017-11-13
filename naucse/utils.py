from typing import Any, Dict
from datetime import date, datetime, time

import os



def get_course_from_slug(slug: str):
    """ Gets the actual course instance from a slug.
    """
    from . import routes

    parts = slug.split("/")

    if parts[0] == "course":
        return routes.model.courses[parts[1]]
    else:
        return routes.model.runs[(int(parts[0]), parts[1])]


def course_info(slug: str, *args, **kwargs) -> Dict[str, Any]:
    """ Returns info about the course/run. Returns some extra info when it's a run (based on COURSE_INFO/RUN_INFO)
    """
    from .models import Course

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


def render(page_type: str, slug: str, *args, **kwargs) -> str:
    """ Returns a rendered page for a course, based on page_type and slug.
    """

    # docker is not running in the docker - we don't need the backend here
    # lets set it to a dummy backed without a check that would fail
    os.environ["ARCA_BACKEND"] = "arca.backend.VenvBackend"

    from . import routes

    course = get_course_from_slug(slug)

    if course.is_link():
        raise ValueError("Circular dependency.")

    with routes.app.test_request_context():

        if page_type == "course":
            return routes.course(course)

        if page_type == "course_page":
            lesson_slug, page, solution, *_ = args
            return routes.course_page(course, routes.model.get_lesson(lesson_slug), page, solution)

        if page_type == "session_coverpage":
            session, coverpage, *_ = args
            return routes.session_coverpage(course, session, coverpage)

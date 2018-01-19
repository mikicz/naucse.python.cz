from typing import Any, Dict, Optional
from datetime import date, datetime, time

from flask import url_for

from naucse.templates import edit_link
from . import routes
from .models import Course


def get_course_from_slug(slug: str) -> Course:
    """ Gets the actual course instance from a slug.
    """
    parts = slug.split("/")

    if parts[0] == "course":
        return routes.model.courses[parts[1]]
    else:
        return routes.model.runs[(int(parts[0]), parts[1])]


def course_info(slug: str, *args, **kwargs) -> Dict[str, Any]:
    """ Returns info about the course/run. Returns some extra info when it's a run (based on COURSE_INFO/RUN_INFO)
    """
    course = get_course_from_slug(slug)

    if course.is_link():
        raise ValueError("Circular dependency.")

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


def serialize_license(license) -> Optional[Dict[str, str]]:
    """ Serializes a License instance into a dict
    """
    if license:
        return {
            "url": license.url,
            "title": license.title
        }

    return None


def render(page_type: str, slug: str, *args, **kwargs) -> Dict[str, Any]:
    """ Returns a rendered page for a course, based on page_type and slug.
    """
    course = get_course_from_slug(slug)

    if course.is_link():
        raise ValueError("Circular dependency.")

    with routes.app.test_request_context():
        info = {
            "course": {
                "title": course.title,
                "url": routes.course_url(course)
            },
            "edit_url": edit_link(course.edit_path),
            "coach_present": course.vars["coach-present"]
        }

        if page_type == "course":
            info.update({
                "content": routes.course(course, content_only=True)
            })

        elif page_type == "calendar":
            info.update({
                "content": routes.course_calendar(course, content_only=True)
            })

        elif page_type == "course_page":
            lesson_slug, page, solution, *_ = args
            lesson = routes.model.get_lesson(lesson_slug)

            info.update({
                "canonical_url": url_for('lesson', lesson=lesson, _external=True),
                "content": routes.course_page(course, lesson, page, solution, content_only=True),
            })

            page, session, *_ = routes.get_page(course, lesson, page)
            info.update({
                "page": {
                    "title": page.title,
                    "css": page.css,
                    "latex": page.latex,
                    "attributions": page.attributions,
                    "license": serialize_license(page.license),
                    "license_code": serialize_license(page.license_code)
                },
                "edit_url": edit_link(page.edit_path),
            })

            if session is not None:
                info["session"] = {
                    "title": session.title,
                    "url": url_for("session_coverpage", course=course.slug, session=session.slug)
                }

        elif page_type == "session_coverpage":
            session_slug, coverpage, *_ = args

            session = course.sessions.get(session_slug)

            info.update({
                "session_title": session.title,
                "content": routes.session_coverpage(course, session_slug, coverpage, content_only=True),
                "edit_url": edit_link(session.get_edit_path(course, coverpage))
            })
        else:
            raise ValueError("Invalid page type.")

        return info

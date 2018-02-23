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


def get_edit_icon():
    """ Should return None or some other icon from `templates/_bytesize_icons.html` if the fork is not on GitHub.
    """
    return "github"


def get_edit_page_name():
    """ Should return the name of the page where editing is possible, in Czech in the 6th case.
        Will be used to replace X in the sentence: `Uprav tuto stránku na X.`
    """
    return "GitHubu"



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
                "url": routes.course_url(course),
                "vars": course.vars,
                "canonical": course.canonical,
                "is_derived": course.is_derived,
            },
            "edit_info": {
                "url": edit_link(course.edit_path),
                "icon": get_edit_icon(),
                "page_name": get_edit_page_name(),
            }
        }

        if page_type == "course":
            info.update({
                "content": routes.course(course, content_only=True)
            })

        elif page_type == "calendar":
            info.update({
                "content": routes.course_calendar(course, content_only=True)
            })

        elif page_type == "calendar_ics":
            info.update({
                "calendar": str(routes.generate_calendar_ics(course))
            })

        elif page_type == "course_page":
            lesson_slug, page, solution, *_ = args
            lesson = routes.model.get_lesson(lesson_slug)

            info.update({
                "content": routes.course_page(course, lesson, page, solution, content_only=True, **kwargs),
            })

            page, session, prv, nxt = routes.get_page(course, lesson, page)

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

            lesson_url, *_ = routes.relative_url_functions(lesson_slug, page.slug != "index", solution)

            prev_link, session_link, next_link = routes.get_footer_links(course, session, prv, nxt, lesson_url)
            info["footer"] = {
                "prev_link": prev_link,
                "session_link": session_link,
                "next_link": next_link
            }

        elif page_type == "session_coverpage":
            session_slug, coverpage, *_ = args

            session = course.sessions.get(session_slug)

            info.update({
                "session": {
                    "title": session.title,
                    "url": url_for("session_coverpage", course=course.slug, session=session.slug),
                },
                "content": routes.session_coverpage(course, session_slug, coverpage, content_only=True),
                "edit_url": edit_link(session.get_edit_path(course, coverpage))
            })
        else:
            raise ValueError("Invalid page type.")

        return info

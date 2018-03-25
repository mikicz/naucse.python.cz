from typing import Any, Dict, Optional
from datetime import date, datetime, time

from flask import url_for
from flask_frozen import UrlForLogger
from git import Repo

from naucse.routes import page_content_cache_key
from naucse.templates import edit_link
from naucse import routes
from naucse.models import Course
from naucse.utils.routes import last_commit_modifying_lesson


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

    path = []
    if kwargs.get("request_url"):
        path = [kwargs["request_url"]]

    logger = UrlForLogger(routes.app)
    with routes.app.test_request_context(*path):
        with logger:

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
                info["content"] = routes.course(course, content_only=True)

            elif page_type == "calendar":
                raise ValueError("Test exceptions")
                info["content"] = routes.course_calendar(course, content_only=True)

            elif page_type == "calendar_ics":
                raise ValueError("Test exceptions")
                info["calendar"] = str(routes.generate_calendar_ics(course))

            elif page_type == "course_page":
                raise ValueError("Test exceptions")
                lesson_slug, page, solution, *_ = args
                lesson = routes.model.get_lesson(lesson_slug)

                content_offer_key = kwargs.get("content_key")
                content = -1

                if content_offer_key is not None:
                    # the base repository has a cached version of the content
                    content_key = page_content_cache_key(Repo("."), lesson_slug, page, solution, course.vars)

                    # if the key matches what would be produced here, let's not return anything
                    # and the cached version will be used
                    if content_offer_key == content_key:
                        content = None

                # if content isn't cached or the version was refused, let's render
                # the content here (but just the content and not the whole page with headers, menus etc)
                if content == -1:
                    content = routes.course_page(course, lesson, page, solution, content_only=True)

                if content is None:
                    info["content"] = None
                    info["content_urls"] = []
                else:
                    info["content"] = content["content"]
                    info["content_urls"] = content["urls"]

                page, session, prv, nxt = routes.get_page(course, lesson, page)

                info.update({
                    "page": {
                        "title": page.title,
                        "css": page.info.get("css"),  # not page.css since we want the css without limitation
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

                request_url = kwargs.get("request_url")
                if request_url is None:
                    request_url = url_for('course_page', course=course, lesson=lesson, page=page, solution=solution)

                lesson_url, *_ = routes.relative_url_functions(request_url, course, lesson)

                prev_link, session_link, next_link = routes.get_footer_links(course, session, prv, nxt, lesson_url)
                info["footer"] = {
                    "prev_link": prev_link,
                    "session_link": session_link,
                    "next_link": next_link
                }

            elif page_type == "session_coverpage":
                raise ValueError("Test exceptions")
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

        urls = set()
        for endpoint, values in logger.iter_calls():
            url = url_for(endpoint, **values)
            if url.startswith(f"/{slug}"):
                urls.add(url)

        info["urls"] = list(urls)

    return info

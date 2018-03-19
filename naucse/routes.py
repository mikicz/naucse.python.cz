import hashlib
import json
import logging
import os
import datetime
import calendar

import jinja2
from arca.exceptions import PullError, BuildError
from flask import Flask, render_template, url_for, send_from_directory, request
from flask import abort, Response
from jinja2 import StrictUndefined
from jinja2.exceptions import TemplateNotFound
from werkzeug.local import LocalProxy
from pathlib import Path
import ics

from naucse import models
from naucse.models import allowed_elements_parser
from naucse.utils.models import arca
from naucse.utils.routes import (get_recent_runs, list_months, last_commit_modifying_lessons, DisallowedStyle,
                                 DisallowedElement, does_course_return_info, urls_from_forks)
from naucse.utils import links
from naucse.urlconverters import register_url_converters
from naucse.templates import setup_jinja_env, vars_functions

app = Flask('naucse')
app.config['TEMPLATES_AUTO_RELOAD'] = True
logger = logging.getLogger("naucse")
logger.setLevel(logging.DEBUG)

setup_jinja_env(app.jinja_env)
POSSIBLE_FORK_EXCEPTIONS = (PullError, BuildError, DisallowedStyle, DisallowedElement)

_cached_model = None

@LocalProxy
def model():
    """Return the root of the naucse model

    In debug mode (elsa serve), a new model is returned for each requests,
    so changes are picked up.

    In non-debug mode (elsa freeze), a single model is used (and stored in
    _cached_model), so that metadata is only read once.
    """
    global _cached_model
    if _cached_model:
        return _cached_model
    model = models.Root(os.path.join(app.root_path, '..'))
    if not app.config['DEBUG']:
        _cached_model = model
    return model

register_url_converters(app, model)

app.jinja_env.undefined = StrictUndefined


def template_function(func):
    app.jinja_env.globals[func.__name__] = func
    return func


@template_function
def static(filename):
    return url_for('static', filename=filename)


@template_function
def course_url(course):
    return url_for('course', course=course)


@template_function
def lesson_url(lesson, page='index', solution=None):
    return url_for('lesson', lesson=lesson, page=page, solution=solution)


@template_function
def session_url(course, session, coverpage='front'):
    return url_for("session_coverpage",
                   course=course,
                   session=session,
                   coverpage=coverpage)


@app.route('/')
def index():
    return render_template("index.html",
                           edit_path=Path("."))


@app.route('/runs/')
def runs():
    safe_years = {}
    for year, run_years in model.run_years.items():
        safe_run_years = []

        for run in run_years.runs.values():
            if not run.is_link():
                safe_run_years.append(run)
            elif does_course_return_info(run, extra_required=["start_date", "end_date"]):
                safe_run_years.append(run)

        safe_years[year] = safe_run_years

    return render_template("run_list.html",
                           run_years=safe_years,
                           title="Seznam offline kurzů Pythonu",
                           today=datetime.date.today(),
                           edit_path=model.runs_edit_path)


@app.route('/courses/')
def courses():
    safe_courses = []

    for course in model.courses.values():
        if not course.is_link():
            safe_courses.append(course)
        elif does_course_return_info(course):
            safe_courses.append(course)

    return render_template("course_list.html",
                           courses=safe_courses,
                           title="Seznam online kurzů Pythonu",
                           edit_path=model.courses_edit_path)


@app.route('/lessons/<lesson_slug:lesson>/static/<path:path>', defaults={"course": None})
@app.route('/<course:course>/<lesson_slug:lesson>/static/<path:path>')
def lesson_static(course, lesson, path):
    """Get the endpoint for static files in lessons.

    Args:
        course  optional info about which course the static file is for
        lesson  lesson in which is the file located
        path    path to file in the static folder

    Returns:
        endpoint for the static file
    """
    lesson_slug = lesson
    try:
        lesson = model.get_lesson(lesson_slug)
    except LookupError:
        lesson = None

    if course is not None and course.is_link():  # is static file from a link?
        try:
            return send_from_directory(*course.lesson_static(lesson_slug, path))
        except (PullError, FileNotFoundError):
            # if the file cannot be retrieved use canonical file instead
            pass

    # only if the lesson is canonical
    if lesson is None:
        abort(404)

    directory = str(lesson.path)
    filename = os.path.join('static', path)
    return send_from_directory(directory, filename)


@app.route('/<course:course>/')
def course(course, content_only=False):
    # if not content_only:
    if course.is_link():
        try:
            # from naucse.utils import render
            # data_from_fork = render("course", course.slug)
            data_from_fork = course.render_course()
        except POSSIBLE_FORK_EXCEPTIONS as e:
            logger.error("There was an error rendering url %s for course '%s'", request.path, course.slug)
            logger.exception(e)
            return render_template(
                "error_in_fork.html",
                malfunctioning_course=course,
                edit_path=course.edit_path,
                faulty_page="course",
                root_slug=model.meta.slug
            )

        try:
            edit_info = links.EditInfo.get_edit_link(data_from_fork.get("edit_info"))

            return render_template(
                "link/course_link.html",
                course=course,
                edit_info=edit_info,
                content=data_from_fork.get("content"),
                recent_runs=get_recent_runs(course)
            )
        except TemplateNotFound:
            abort(404)

    def lesson_url(lesson, *args, **kwargs):
        if kwargs.get("page") == "index":
            kwargs.pop("page")

        return url_for('course_page', course=course, lesson=lesson, *args, **kwargs)

    if content_only:
        template_name = 'content/course.html'
        recent_runs = None
    else:
        template_name = 'course.html'
        recent_runs = get_recent_runs(course)

    try:
        return render_template(
            template_name,
            course=course,
            plan=course.sessions,
            title=course.title,
            lesson_url=lesson_url,
            recent_runs=recent_runs,
            **vars_functions(course.vars),
            edit_path=course.edit_path)
    except TemplateNotFound:
        abort(404)


def page_content_cache_key(info, repo=None) -> str:
    """ Returns a key under which content fragments will be stored in cache, depending on the page
    and the last commit which modified lesson rendering in ``repo``
    """
    return "commit:{}:content:{}".format(
        last_commit_modifying_lessons(repo),
        hashlib.sha1(json.dumps(
            info,
            sort_keys=True
        ).encode("utf-8")).hexdigest()
    )


def render_page(page, solution=None, vars=None, **kwargs):
    lesson = page.lesson

    course = kwargs.get("course", None)
    content_only = kwargs.get("content_only", False)
    static_url = kwargs.get("static_url")

    if static_url is None:
        def static_url(path):
            return url_for('lesson_static', lesson=lesson, path=path, course=course)

    content = None

    try:
        def content_creator():
            return {"content": page.render_html(
                solution=solution,
                static_url=static_url,
                lesson_url=kwargs.get('lesson_url', lesson_url),
                subpage_url=kwargs.get('subpage_url', None),
                vars=vars
            ), "urls": []}

        content_key = page_content_cache_key(
            {
                "lesson": lesson.slug,
                "page": page.slug,
                "solution": solution,
                "vars": course.vars if course is not None else None
            },
        )

        # only use the cache if there are no local changes
        if not arca.is_dirty():
            # since ARCA_IGNORE_CACHE_ERRORS is set, this won't fail in forks even if the cache doesn't work
            # this is only dangerous if the fork sets absolute path to cache and
            # CurrentEnvironmentBackend or VenvBackend are used locally
            # FIXME? But I don't think there's a way to prevent writing to a file in those backends
            content = arca.region.get_or_create(content_key, content_creator)
        else:
            content = content_creator()["content"]

    except FileNotFoundError:
        abort(404)

    if content_only:
        return content

    kwargs.setdefault('lesson', lesson)
    kwargs.setdefault('page', page)

    if solution is not None:
        template_name = 'solution.html'
        kwargs.setdefault('solution_number', solution)
    else:
        template_name = 'lesson.html'

    kwargs.setdefault('title', page.title)
    kwargs.setdefault('content', content)
    kwargs.setdefault('root_slug', model.meta.slug)

    return render_template(template_name, **kwargs, **vars_functions(vars),
                           edit_path=page.edit_path)


def get_page(course, lesson, page):
    for session in course.sessions.values():
        for material in session.materials:
            if (material.type == "page" and material.page.lesson.slug == lesson.slug):
                material = material.subpages[page]
                page = material.page
                nxt = material.next
                prv = material.prev
                break
        else:
            continue
        break
    else:
        page = lesson.pages[page]
        session = None
        prv = nxt = None

    return page, session, prv, nxt


def get_footer_links(course, session, prv, nxt, lesson_url):
    """ Reusable function that will return urls and info about prev/next page based on current session, page etc
    """
    prev_link = None
    if prv is not None:
        prev_link = {
            "url": lesson_url(prv.page.lesson, page=prv.page.slug),
            "title": prv.page.title,
        }

    session_link = None
    if session is not None:
        session_link = {
            "url": session_url(course.slug, session.slug),
            "title": session.title,
        }

    next_link = None
    if nxt is not None:
        next_link = {
            "url": lesson_url(nxt.page.lesson, page=nxt.page.slug),
            "title": nxt.page.title,
        }
    elif session is not None:
        next_link = {
            "url": session_url(course.slug, session.slug, coverpage="back"),
            "title": "Závěr lekce",
        }

    return prev_link, session_link, next_link


def get_relative_url(current, target):
    rel = os.path.relpath(target, current)

    if rel[-1] != "/":
        if "." not in rel.split("/")[-1]:
            rel += "/"

    if not rel.startswith("../") and rel != "./":
        rel = f"./{rel}"

    return rel


def relative_url_functions(current_url, course, lesson):
    """ Builds relative urls generators based on current page
    """
    def lesson_url(lesson, *args, **kwargs):
        if not isinstance(lesson, str):
            lesson = lesson.slug

        if course is not None:
            absolute = url_for('course_page', course=course, lesson=lesson, *args, **kwargs)
        else:
            absolute = url_for('lesson', lesson=lesson, *args, **kwargs)
        return get_relative_url(current_url, absolute)

    def subpage_url(page_slug):
        if course is not None:
            absolute = url_for('course_page', course=course, lesson=lesson, page=page_slug)
        else:
            absolute = url_for('lesson', lesson=lesson, page=page_slug)

        return get_relative_url(current_url, absolute)

    def static_url(path):
        absolute = url_for('lesson_static', lesson=lesson, path=path, course=course)

        return get_relative_url(current_url, absolute)

    return lesson_url, subpage_url, static_url


def course_link_page(course, lesson_slug, page, solution):
    """ Builds a lesson page from a fork.

    1) checks if a content fragment is in cache, retrieve it to offer it
    2) calls  Arca to run render in the fork code
        a) renders returned content here with local templates for headers, footer, etc.
        b) if the task fails and the lesson is canonical (exists in this repo), renders current version with a warning
    """
    canonical_url = None
    kwargs = {}

    # if the page is canonical (exists in the root repository), retrieve it to get the canonical url
    # and for possible use if the lesson render fails in the fork
    try:
        lesson = model.get_lesson(lesson_slug)
        canonical_url = url_for('lesson', lesson=lesson, _external=True)
    except LookupError:
        lesson = None

    try:
        # checks if the rendered page content is in cache locally to offer it to the fork
        content_key = page_content_cache_key(
            {
                "lesson": lesson_slug,
                "page": page,
                "solution": solution,
                "vars": course.vars  # this calls ``course_info`` so it has to be in the try block
            },
            arca.get_repo(course.repo, course.branch)
        )

        content_offer = arca.region.get(content_key)

        if content_offer:
            kwargs.update({
                "content_key": content_key,
            })


        data_from_fork = course.render_page(lesson_slug, page, solution, **kwargs)

        content = data_from_fork["content"]

        if content is None:
            content = content_offer["content"]
            urls_from_forks.extend(content_offer["urls"])
        else:
            arca.region.set(content_key, {"content": content, "urls": data_from_fork["urls"]})

        # get PageLink here since css parsing is in it so the exception can be caught here
        page = links.PageLink(data_from_fork.get("page", {}))
    except POSSIBLE_FORK_EXCEPTIONS as e:
        logger.error("There was an error rendering url %s for course '%s'", request.path, course.slug)
        if lesson is not None:
            try:
                return course_page(course=course, lesson=lesson_slug, page=page, solution=solution,
                                   error_in_fork=True)
            except:
                logger.error("Tried to render the canonical version, that failed.")
                pass
            finally:
                logger.error("Rendered the canonical version with a warning.")

        logger.exception(e)
        return render_template(
            "error_in_fork.html",
            malfunctioning_course=course,
            edit_path=course.edit_path,
            faulty_page="lesson",
            lesson=lesson_slug,
            pg=page,  # avoid name conflict
            solution=solution,
            root_slug=model.meta.slug
        )

    # from naucse.utils import render
    # data_from_fork = render("course_page", course.slug, lesson_slug, page, solution, **kwargs)

    solution_number = None
    if solution is not None:
        solution_number = int(solution)

    try:
        course = links.CourseLink(data_from_fork.get("course", {}))

        session = links.SessionLink.get_session_link(data_from_fork.get("session"))
        edit_info = links.EditInfo.get_edit_link(data_from_fork.get("edit_info"))

        footer = data_from_fork["footer"]
        title = '{}: {}'.format(course.title, page.title)

        return render_template(
            "link/lesson_link.html",
            course=course,
            title=title,
            page=page,
            session=session,

            solution_number=solution_number,
            canonical_url=canonical_url,
            edit_info=edit_info,

            content=content,

            prev_link=footer.get("prev_link"),
            session_link=footer.get("session_link"),
            next_link=footer.get("next_link"),
        )
    except TemplateNotFound:
        abort(404)



@app.route('/<course:course>/<lesson_slug:lesson>/', defaults={'page': 'index'})
@app.route('/<course:course>/<lesson_slug:lesson>/<page>/')
@app.route('/<course:course>/<lesson_slug:lesson>/<page>/solutions/<int:solution>/')
def course_page(course, lesson, page, solution=None, content_only=False, **kwargs):
    """ Render the html of the given lesson page in the course.

        The lesson url convertor can't be used since there can be new lessons in the forked repositories,
        however if the course isn't a lik to a fork and the lesson doesn't exist in the current repository,
        the function returns a 404
    """
    page_explicit = page != "index"

    if course.is_link() and not kwargs.get("error_in_fork", False):
        return course_link_page(course, lesson, page, solution)

    try:
        lesson = model.get_lesson(lesson)
    except LookupError:
        abort(404)

    page, session, prv, nxt = get_page(course, lesson, page)

    lesson_url, subpage_url, static_url = relative_url_functions(kwargs.get("request_url", request.path),
                                                                 course, lesson)

    canonical_url = url_for('lesson', lesson=lesson, _external=True)

    title = '{}: {}'.format(course.title, page.title)

    prev_link, session_link, next_link = get_footer_links(course, session, prv, nxt, lesson_url)

    return render_page(page=page, title=title,
                       lesson_url=lesson_url,
                       subpage_url=subpage_url,
                       canonical_url=canonical_url,
                       static_url=static_url,
                       course=course,
                       solution=solution,
                       vars=course.vars,
                       prev_link=prev_link,
                       session_link=session_link,
                       next_link=next_link,
                       content_only=content_only,
                       page_explicit=page_explicit,
                       **kwargs)


@app.route('/lessons/<lesson:lesson>/', defaults={'page': 'index'})
@app.route('/lessons/<lesson:lesson>/<page>/')
@app.route('/lessons/<lesson:lesson>/<page>/solutions/<int:solution>/')
def lesson(lesson, page, solution=None):
    """Render the html of the given lesson page."""

    lesson_url, subpage_url, static_url = relative_url_functions(request.path, None, lesson)

    page = lesson.pages[page]
    return render_page(page=page, solution=solution,
                       lesson_url=lesson_url,
                       subpage_url=subpage_url,
                       static_url=static_url)


@app.route('/<course:course>/sessions/<session>/', defaults={'coverpage': 'front'})
@app.route('/<course:course>/sessions/<session>/<coverpage>/')
def session_coverpage(course, session, coverpage, content_only=False):
    """Render the session coverpage.

    Args:
        course      course where the session belongs
        session     name of the session
        coverpage   coverpage of the session, front is default

    Returns:
        rendered session coverpage
    """
    if course.is_link():
        try:
            data_from_fork = course.render_session_coverpage(session, coverpage)
        except POSSIBLE_FORK_EXCEPTIONS as e:
            logger.error("There was an error rendering url %s for course '%s'", request.path, course.slug)
            logger.exception(e)
            return render_template(
                "error_in_fork.html",
                malfunctioning_course=course,
                edit_path=course.edit_path,
                faulty_page=f"session_{coverpage}",
                session=session,
                root_slug=model.meta.slug
            )

        # from naucse.utils import render
        # data_from_fork = render("session_coverpage", course.slug, session, coverpage)

        try:
            course = links.CourseLink(data_from_fork.get("course", {}))
            session = links.SessionLink.get_session_link(data_from_fork.get("session"))
            edit_info = links.EditInfo.get_edit_link(data_from_fork.get("edit_info"))

            return render_template(
                "link/coverpage_link.html",
                course=course,
                session=session,
                edit_info=edit_info,

                content=data_from_fork.get("content"),
            )
        except TemplateNotFound:
            abort(404)


    session = course.sessions.get(session)

    def lesson_url(lesson, *args, **kwargs):
        if kwargs.get("page") == "index":
            kwargs.pop("page")

        return url_for('course_page', course=course, lesson=lesson, *args, **kwargs)

    def session_url(session):
        return url_for("session_coverpage",
                       course=course,
                       session=session,
                       coverpage=coverpage)

    content = session.get_coverpage_content(course, coverpage, app)

    template = "coverpage.html" if not content_only else "content/coverpage.html"
    if coverpage == "back":
        template = "backpage.html" if not content_only else "content/backpage.html"

    homework_section = False
    link_section = False
    cheatsheet_section = False
    for mat in session.materials:
        if mat.url_type == "homework":
            homework_section = True
        if mat.url_type == "link":
            link_section = True
        if mat.url_type == "cheatsheet":
            cheatsheet_section = True

    return render_template(template,
                           content=content,
                           session=session,
                           course=course,
                           lesson_url=lesson_url,
                           **vars_functions(course.vars),
                           edit_path=session.get_edit_path(course, coverpage),
                           homework_section=homework_section,
                           link_section=link_section,
                           cheatsheet_section=cheatsheet_section)


@app.route('/<course:course>/calendar/')
def course_calendar(course, content_only=False):
    if course.is_link():
        try:
            data_from_fork = course.render_calendar()
        except POSSIBLE_FORK_EXCEPTIONS as e:
            logger.error("There was an error rendering url %s for course '%s'", request.path, course.slug)
            logger.exception(e)
            return render_template(
                "error_in_fork.html",
                malfunctioning_course=course,
                edit_path=course.edit_path,
                faulty_page="calendar",
                root_slug=model.meta.slug
            )

        try:
            course = links.CourseLink(data_from_fork.get("course", {}))
            edit_info = links.EditInfo.get_edit_link(data_from_fork.get("edit_info"))

            return render_template(
                "link/course_calendar_link.html",
                course=course,
                edit_info=edit_info,
                content=data_from_fork.get("content"),
            )
        except TemplateNotFound:
            abort(404)

    if not course.start_date:
        abort(404)

    sessions_by_date = {s.date: s for s in course.sessions.values()}
    return render_template('course_calendar.html' if not content_only else 'content/course_calendar.html',
                           edit_path=course.edit_path,
                           course=course,
                           sessions_by_date=sessions_by_date,
                           months=list_months(course.start_date,
                                              course.end_date),
                           calendar=calendar.Calendar())


def generate_calendar_ics(course):
    calendar = ics.Calendar()
    for session in course.sessions.values():
        if session.start_time:
            start_time = session.start_time
            end_time = session.end_time
        else:
            raise ValueError("One of the sessions doesn't have a start time.")

        cal_event = ics.Event(
            name=session.title,
            begin=start_time,
            end=end_time,
            uid=url_for("session_coverpage",
                      course=course,
                      session=session.slug,
                      _external=True),
        )
        calendar.events.append(cal_event)

    return calendar


@app.route('/<course:course>/calendar.ics')
def course_calendar_ics(course):
    if not course.start_date:
        abort(404)

    if course.is_link():
        try:
            data_from_fork = course.render_calendar_ics()
        except POSSIBLE_FORK_EXCEPTIONS as e:
            logger.error("There was an error rendering url %s for course '%s'", request.path, course.slug)
            logger.exception(e)
            return render_template(
                "error_in_fork.html",
                malfunctioning_course=course,
                edit_path=course.edit_path,
                faulty_page="calendar",
                root_slug=model.meta.slug
            )

        calendar = data_from_fork["calendar"]
    else:
        try:
            calendar = generate_calendar_ics(course)
        except ValueError:
            abort(404)

    return Response(str(calendar), mimetype="text/calendar")

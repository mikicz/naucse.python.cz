import hashlib
import json
import os
import datetime
import calendar

import jinja2
from flask import Flask, render_template, url_for, send_from_directory
from flask import abort
from jinja2 import StrictUndefined
from jinja2.exceptions import TemplateNotFound
from werkzeug.local import LocalProxy
from pathlib import Path

from naucse import models
from naucse.modelutils import arca
from naucse.routes_util import get_recent_runs, PageLink, list_months, last_commit_modifying_lessons
from naucse.urlconverters import register_url_converters
from naucse.templates import setup_jinja_env, vars_functions

app = Flask('naucse')
app.config['TEMPLATES_AUTO_RELOAD'] = True

setup_jinja_env(app.jinja_env)


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
    return render_template("run_list.html",
                           run_years=model.run_years,
                           title="Seznam offline kurzů Pythonu",
                           today=datetime.date.today(),
                           edit_path=model.runs_edit_path)


@app.route('/courses/')
def courses():
    return render_template("course_list.html",
                           courses=model.courses,
                           title="Seznam online kurzů Pythonu",
                           edit_path=model.courses_edit_path)


@app.route('/lessons/<lesson:lesson>/static/<path:path>', defaults={"course": None})
@app.route('/<course:course>/<lesson:lesson>/static/<path:path>')
def lesson_static(course, lesson, path):
    """Get the endpoint for static files in lessons.

    Args:
        lesson  lesson in which is the file located
        path    path to file in the static folder

    Returns:
        endpoint for the static file
    """
    if course is not None and course.is_link():
        return send_from_directory(*course.lesson_static(lesson, path))

    directory = str(lesson.path)
    filename = os.path.join('static', path)
    return send_from_directory(directory, filename)


@app.route('/<course:course>/')
def course(course, content_only=False):
    if course.is_link():
        data_from_fork = course.render_course()

        try:
            course = data_from_fork.get("course", {})

            return render_template(
                "link/course_link.html",
                title=course.get("title"),
                course_title=course.get("title"),
                coach_present=data_from_fork.get("coach_present"),
                edit_url=data_from_fork.get("edit_url"),
                content=data_from_fork.get("content"),
            )
        except TemplateNotFound:
            abort(404)

    def lesson_url(lesson, *args, **kwargs):
        if kwargs.get("page") == "index":
            kwargs.pop("page")

        return url_for('course_page', course=course, lesson=lesson, *args, **kwargs)

    try:
        return render_template(
            'course.html' if not content_only else 'content/course.html',
            course=course,
            plan=course.sessions,
            title=course.title,
            lesson_url=lesson_url,
            recent_runs=get_recent_runs(course),
            **vars_functions(course.vars),
            edit_path=course.edit_path)
    except TemplateNotFound:
        abort(404)


def hash_content_info(info):
    """ Creates the hash key used to store rendered content in cache and to offer the content to forks.
    """
    return "content_hash:" + hashlib.sha1(json.dumps(
        info,
        sort_keys=True
    ).encode("utf-8")).hexdigest()


def render_page(page, solution=None, vars=None, **kwargs):
    lesson = page.lesson

    course = kwargs.get("course", None)
    content_only = kwargs.get("content_only", False)
    static_url = kwargs.get("static_url")
    relative_urls = kwargs.get("relative_urls", False)
    content_offer_hash = kwargs.get("content_hash")
    content_offer = kwargs.get("content_offer")

    if static_url is None:
        def static_url(path):
            return url_for('lesson_static', lesson=lesson, path=path, course=course)

    try:
        def render_content():
            return page.render_html(
                solution=solution,
                static_url=static_url,
                lesson_url=kwargs.get('lesson_url', lesson_url),
                subpage_url=kwargs.get('subpage_url', None),
                vars=vars)

        content = None

        if relative_urls:
            # only store content in cache if the page is rendered with relative urls
            # (rendered with absolute in just lessons)
            content_hash = hash_content_info(
                {
                    "commit": last_commit_modifying_lessons(),
                    "lesson": lesson.slug,
                    "page": page.slug,
                    "solution": solution,
                    "vars": vars
                }
            )

            # since this function is called in both the root naucse and in forks,
            # 1) use the content offer if received an offer with same hash
            # 2) store the rendered content if rendering full page (-> rendering in root naucse)

            if content_offer_hash == content_hash:
                content = jinja2.Markup(content_offer)
            elif not content_only:
                # even if this condition would be changed in forks, this will not poison cache in
                # Arca Docker and Vagrant backends - cache initialization will fail and null cache will be used
                # instead thanks to the ARCA_IGNORE_CACHE_ERRORS setting

                content = arca.region.get_or_create(
                    key=content_hash,
                    creator=render_content,
                    should_cache_fn=arca.should_cache_fn
                )

        if content is None:
            content = render_content()
    except FileNotFoundError:
        abort(404)

    kwargs.setdefault('lesson', lesson)
    kwargs.setdefault('page', page)

    if solution is not None:
        template_name = 'solution.html' if not content_only else 'content/solution.html'
        kwargs.setdefault('solution_number', solution)
    else:
        template_name = 'lesson.html' if not content_only else 'content/lesson.html'

    kwargs.setdefault('title', page.title)
    kwargs.setdefault('content', content)

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


def relative_url_functions(lesson_slug, page_explicit, solution):
    """ Builds relative urls generators based on current page
    """
    def lesson_url(lesson, *args, **kwargs):
        if not isinstance(lesson, str):
            lesson = lesson.slug

        lesson_parent = "../" * (lesson_slug.count("/") + 1)

        if solution is not None:
            lesson_parent = f"../../../" + lesson_parent
        elif page_explicit:
            lesson_parent = f"../" + lesson_parent

        if kwargs.get("solution") is not None:
            solution_ = kwargs.get("solution")
            page_ = kwargs.get("page")
            if not isinstance(page_, str):
                page_ = page_.slug
            return f"{lesson_parent}{lesson}/{page_}/solutions/{solution_}/"

        if kwargs.get("page") is not None:
            page_ = kwargs.get("page")
            if not isinstance(page_, str):
                page_ = page_.slug

            if page_ != "index":
                return f"{lesson_parent}{lesson}/{page_}/"

        return f"{lesson_parent}{lesson}/"

    def subpage_url(page_slug):
        if page_explicit:
            return f"../{page_slug}/"
        return f"./{page_slug}/"

    def static_url(path):
        if solution:
            return f"../../../static/{path}"
        if page_explicit:
            return f"../static/{path}"
        return f"static/{path}"

    return lesson_url, subpage_url, static_url


def course_link_page(course, lesson_slug, page, solution):
    """ Builds a lesson page from a fork.
        1) checks if the lesson exists in root repository, tries to retrieve the last version from cache and offer it
           to the fork
        2) calls Arca to run render in the fork code
        3) renders returned content here with local templates for headers, footer, etc.
    """
    kwargs = {}

    # if the page is canonical (exists in the root repository), try to retrieve it from cache (with correct variables),
    # offer it to the fork
    try:
        model.get_lesson(lesson_slug)

        content_hash = hash_content_info(
            {
                "commit": last_commit_modifying_lessons(),
                "lesson": lesson_slug,
                "page": page,
                "solution": solution,
                "vars": course.vars
            })

        content_offer = arca.region.get(content_hash)

        if content_offer:
            kwargs.update({
                "content_hash": content_hash,
                "content_offer": str(content_offer)
            })

    except LookupError:
        pass

    data_from_fork = course.render_page(lesson_slug, page, solution, **kwargs)
    # data_from_fork = render("course_page", course.slug, lesson_slug, page, solution, **kwargs)

    try:
        course = data_from_fork.get("course", {})
        session = data_from_fork.get("session", {})
        page = data_from_fork.get("page", {})
        footer = data_from_fork["footer"]

        title = '{}: {}'.format(course.get("title"), page.get("title"))

        return render_template(
            "link/lesson_link.html",
            course_title=course.get("title"),
            course_url=course.get("url"),
            coach_present=course.get("coach_present"),
            course_is_derived=course.get("is_derived"),
            title=title,

            page=PageLink(page),

            canonical_url=data_from_fork.get("canonical_url"),

            session_title=session.get("title"),
            session_url=session.get("url"),

            edit_url=data_from_fork.get("edit_url"),
            content=data_from_fork.get("content"),

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

    if course.is_link():
    # if not content_only:
        return course_link_page(course, lesson, page, solution)

    try:
        lesson = model.get_lesson(lesson)
    except LookupError:
        abort(404)

    page, session, prv, nxt = get_page(course, lesson, page)

    lesson_slug = lesson.slug

    lesson_url, subpage_url, static_url = relative_url_functions(lesson_slug, page_explicit, solution)

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
                       relative_urls=True,
                       **kwargs)


@app.route('/lessons/<lesson:lesson>/', defaults={'page': 'index'})
@app.route('/lessons/<lesson:lesson>/<page>/')
@app.route('/lessons/<lesson:lesson>/<page>/solutions/<int:solution>/')
def lesson(lesson, page, solution=None):
    """Render the html of the given lesson page."""
    page = lesson.pages[page]
    return render_page(page=page, solution=solution)


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
        data_from_fork = course.render_session_coverpage(session, coverpage)

        try:
            course = data_from_fork.get("course", {})

            return render_template(
                "link/coverpage_link.html",
                course_title=course.get("title"),
                course_url=course.get("url"),

                coach_present=data_from_fork.get("coach_present"),
                edit_url=data_from_fork.get("edit_url"),
                content=data_from_fork.get("content"),

                session_title=data_from_fork.get("session_title"),
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
    if not course.start_date:
        abort(404)

    if course.is_link():
        data_from_fork = course.render_calendar()

        try:
            course = data_from_fork.get("course", {})

            return render_template(
                "link/course_calendar_link.html",
                course_title=course.get("title"),
                course_url=course.get("url"),

                coach_present=data_from_fork.get("coach_present"),
                edit_url=data_from_fork.get("edit_url"),
                content=data_from_fork.get("content"),
            )
        except TemplateNotFound:
            abort(404)

    sessions_by_date = {s.date: s for s in course.sessions.values()}
    return render_template('course_calendar.html' if not content_only else 'content/course_calendar.html',
                           edit_path=course.edit_path,
                           course=course,
                           sessions_by_date=sessions_by_date,
                           months=list_months(course.start_date,
                                              course.end_date),
                           calendar=calendar.Calendar())

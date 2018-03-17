from collections import OrderedDict

import datetime

import pytest
import shutil
import tempfile
from pathlib import Path

import yaml
from arca.exceptions import BuildError
from flask.testing import FlaskClient
from git import Repo

from naucse import models


def generate_course(title):
    return {
        "title": title,
        "description": "Course description",
        "long_description": "Course long description",
        "vars": {
            "coach-present": False,
            "some-var": True
        },
        "plan": [
            {"title": "First session",
             "slug": "first-session",
             "materials": [
                 {"lesson": "beginners/cmdline"},
                 {"lesson": "beginners/install"},
             ]},
            {"title": "Second session",
             "slug": "second-session",
             "materials": [
                 {"lesson": "beginners/first-steps"},
                 {"lesson": "beginners/install-editor"},
             ]},
        ]
    }


def generate_run(title):
    return {
        "title": title,
        "description": "Run description",
        "long_description": "Run long description",
        "default_time": {
            "start": "18:00",
            "end": "20:00"
        },
        "vars": {
            "coach-present": True,
            "some-var": False
        },
        "plan": [
            {"title": "First session",
             "slug": "first-session",
             "date": datetime.date(2018, 2, 6),
             "materials": [
                 {"lesson": "beginners/cmdline"},
                 {"lesson": "beginners/install"}
             ]},
            {"title": "Second session",
             "slug": "second-session",
             "date": datetime.date(2018, 2, 8),
             "materials": [
                 {"lesson": "beginners/first-steps"},
                 {"lesson": "beginners/install-editor"}
             ]},
        ]
    }


@pytest.fixture(scope="module")
def fork():
    def ignore(_, names):
        return [x for x in names
                if ((x.startswith(".") and x not in {".git", ".gitignore", ".travis.yml"}) or
                    x == "_build" or
                    x == "__pycache__")]

    test_dir = Path(tempfile.mkdtemp()) / "naucse"
    naucse = Path(__file__).parent.parent
    shutil.copytree(naucse, str(test_dir), ignore=ignore)

    repo = Repo(str(test_dir))
    branch = "test_branch"
    repo.create_head(branch)
    getattr(repo.heads, branch).checkout()

    course_info = test_dir / "courses/test-course/info.yml"
    course_info.parent.mkdir(exist_ok=True, parents=True)
    course_info.write_text(yaml.dump(generate_course("Course title"), default_flow_style=False))

    run_info = test_dir / "runs/2018/test-run/info.yml"
    run_info.parent.mkdir(exist_ok=True, parents=True)
    run_info.write_text(yaml.dump(generate_run("Run title"), default_flow_style=False))

    repo.git.add([str(course_info), str(run_info)])
    repo.git.add(A=True)
    repo.index.commit("Commited everything")

    branch = "test_broken_branch"
    repo.create_head(branch)
    getattr(repo.heads, branch).checkout()

    course_broken_info = test_dir / "courses/test-broken-course/info.yml"
    course_broken_info.parent.mkdir(exist_ok=True, parents=True)
    course_broken_info.write_text(yaml.dump(generate_course("Broken course title"), default_flow_style=False))

    run_broken_info = test_dir / "runs/2018/test-broken-run/info.yml"
    run_broken_info.parent.mkdir(exist_ok=True, parents=True)
    run_broken_info.write_text(yaml.dump(generate_run("Broken run title"), default_flow_style=False))

    utils = test_dir / "naucse/utils" / "forks.py"
    with utils.open("w") as fl:
        fl.write("")

    repo.git.add([str(course_broken_info), str(run_broken_info), str(utils)])
    repo.index.commit("Created duplicates in a different branch, but broke rendering")

    yield f"file://{test_dir}"
    shutil.rmtree(test_dir.parent)


@pytest.fixture(scope="module")
def model(fork):
    path = Path(__file__).parent / 'fixtures/test_content'
    root = models.Root(path)

    course = models.CourseLink(root, path / 'courses/test-course')
    course.repo = fork
    course.branch = "test_branch"

    course_broken = models.CourseLink(root, path / 'courses/test-broken-course')
    course_broken.repo = fork
    course_broken.branch = "test_broken_branch"

    run = models.CourseLink(root, path / 'runs/2018/test-run')
    run.repo = fork
    run.branch = "test_branch"

    run_broken = models.CourseLink(root, path / 'runs/2018/test-broken-run')
    run_broken.repo = fork
    run_broken.branch = "test_broken_branch"

    root.courses = OrderedDict([("test-course", course), ('test-broken-course', course_broken)])

    run_year = models.RunYear(root, path / 'runs/2018')
    run_year.runs = OrderedDict([
        ("test-run", run),
        ("test-broken-run", run_broken)
    ])

    root.run_years = OrderedDict([
        (2018, run_year)
    ])
    root.runs = {(2018, "test-run"): run, (2018, "test-broken-run"): run_broken}

    return root


@pytest.fixture
def client(model, mocker):
    mocker.patch("naucse.routes._cached_model", model)
    from naucse import app
    app.testing = True
    yield app.test_client()


def test_course_info(model):
    assert model.courses["test-course"].title == "Course title"
    assert model.courses["test-course"].description == "Course description"
    assert model.courses["test-course"].start_date is None
    assert model.courses["test-course"].end_date is None
    assert not model.courses["test-course"].canonical
    assert model.courses["test-course"].vars.get("coach-present") is False
    assert model.courses["test-course"].vars.get("some-var") is True


def test_run_info(model):
    assert model.runs[(2018, "test-run")].title == "Run title"
    assert model.runs[(2018, "test-run")].description == "Run description"
    assert model.runs[(2018, "test-run")].start_date == datetime.date(2018, 2, 6)
    assert model.runs[(2018, "test-run")].end_date == datetime.date(2018, 2, 8)
    assert not model.runs[(2018, "test-run")].canonical
    assert model.runs[(2018, "test-run")].vars.get("coach-present") is True
    assert model.runs[(2018, "test-run")].vars.get("some-var") is False


def test_course_render(model):
    assert model.courses["test-course"].render_course()
    with pytest.raises(BuildError):
        model.courses["test-course"].render_calendar()

    with pytest.raises(BuildError):
        model.courses["test-course"].render_calendar_ics()

    assert model.courses["test-course"].render_session_coverpage("first-session", "front")
    assert model.courses["test-course"].render_session_coverpage("first-session", "back")

    index = model.courses["test-course"].render_page("beginners/cmdline", "index", None)
    assert index
    solution = model.courses["test-course"].render_page("beginners/cmdline", "index", 0)
    assert solution
    assert index != solution

    index = model.courses["test-course"].render_page("beginners/install", "index", None)
    assert index
    linux = model.courses["test-course"].render_page("beginners/install", "linux", None)
    assert linux
    assert index != linux


def test_run_render(model):
    assert model.runs[(2018, "test-run")].render_course()

    assert model.runs[(2018, "test-run")].render_calendar()
    assert model.runs[(2018, "test-run")].render_calendar_ics()

    assert model.runs[(2018, "test-run")].render_session_coverpage("first-session", "front")
    assert model.runs[(2018, "test-run")].render_session_coverpage("first-session", "back")

    index = model.runs[(2018, "test-run")].render_page("beginners/cmdline", "index", None)
    assert index
    solution = model.runs[(2018, "test-run")].render_page("beginners/cmdline", "index", 0)
    assert solution
    assert index != solution

    index = model.runs[(2018, "test-run")].render_page("beginners/install", "index", None)
    assert index
    linux = model.runs[(2018, "test-run")].render_page("beginners/install", "linux", None)
    assert linux
    assert index != solution


def test_courses_page(mocker, client: FlaskClient):
    mocker.patch("naucse.utils.routes.should_raise_basic_course_problems", lambda: True)

    # there's a problem in one of the branches, it should raise error if the conditions for raising are True
    with pytest.raises(BuildError):
        client.get("/courses/")

    # unless problems are silenced
    mocker.patch("naucse.utils.routes.should_raise_basic_course_problems", lambda: False)
    response = client.get("/courses/")
    assert b"Broken course title" not in response.data

    # but working forks are still present
    assert b"Course title" in response.data


def test_runs_page(mocker, client: FlaskClient):
    mocker.patch("naucse.utils.routes.should_raise_basic_course_problems", lambda: True)

    # there's a problem in one of the branches, it should raise error if the conditions for raising are True
    with pytest.raises(BuildError):
        client.get("/runs/")

    # unless problems are silenced
    mocker.patch("naucse.utils.routes.should_raise_basic_course_problems", lambda: False)
    response = client.get("/runs/")
    assert b"Broken run title" not in response.data

    # but working forks are still present
    assert b"Run title" in response.data


@pytest.mark.parametrize("url", [
    "/course/test-broken-course/",
    "/course/test-broken-course/sessions/first-session/",
    "/course/test-broken-course/beginners/cmdline/",
    "/course/test-broken-course/beginners/cmdline/index/solutions/0/",
    "/course/test-broken-course/beginners/install/linux/",
    "/2018/test-broken-run/",
    "/2018/test-broken-run/calendar/",
])
def test_pages(url, client: FlaskClient):
    """ Rendering of the page shouldn't fail, it should return a page win an error message
    """
    response = client.get(url)
    assert b"alert alert-danger" in response.data

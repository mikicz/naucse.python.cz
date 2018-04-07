""" These classes serve as compatibility utils for info from forks, so changes to templates aren't required.
"""
from xml.dom import SyntaxErr

from naucse.models import Page
from naucse.utils.routes import DisallowedStyle


class CourseLink:

    def __init__(self, course, slug=None):
        self.title = course["title"]
        self.url = course["url"]
        self.vars = course.get("vars", {})
        self.canonical = course.get("canonical")
        self.is_derived = course.get("is_derived")
        self.slug = slug


class SessionLink:

    @classmethod
    def get_session_link(cls, session_data, slug=None):
        if session_data is None:
            return None
        return SessionLink(session_data["title"], session_data["url"], slug or session_data["slug"])

    def __init__(self, title, url, slug):
        self.title = title
        self.url = url
        self.slug = slug


class LicenseLink:

    def __init__(self, url, title):
        self.url = url
        self.title = title


class PageLink:

    def __init__(self, page):
        self.title = page.get("title")
        self.latex = page.get("latex")
        self.attributions = page.get("attributions")

        if page.get("license"):
            self.license = LicenseLink(**page.get("license"))
        else:
            self.license = None

        if page.get("license_code"):
            self.license_code = LicenseLink(**page.get("license_code"))
        else:
            self.license_code = None

        self.css = page.get("css")

        if self.css is not None:
            try:
                self.css = Page.limit_css_to_lesson_content(self.css)
            except SyntaxErr:
                raise DisallowedStyle(DisallowedStyle.COULD_NOT_PARSE)


class EditInfo:

    @classmethod
    def get_edit_link(cls, edit_info_data):
        if edit_info_data is None:
            return None
        return EditInfo(edit_info_data)

    def __init__(self, edit_info):
        self.url = edit_info.get("url")
        self.icon = edit_info.get("icon")
        self.page_name = edit_info.get("page_name")

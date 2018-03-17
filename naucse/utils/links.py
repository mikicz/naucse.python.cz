
class CourseLink:

    def __init__(self, course):
        self.title = course["title"]
        self.url = course["url"]
        self.vars = course.get("vars", {})
        self.canonical = course.get("canonical")
        self.is_derived = course.get("is_derived")


class SessionLink:

    @classmethod
    def get_session_link(cls, session_data):
        if session_data is None:
            return None
        return SessionLink(session_data["title"], session_data["url"])

    def __init__(self, title, url):
        self.title = title
        self.url = url


class LicenseLink:

    def __init__(self, url, title):
        self.url = url
        self.title = title


class PageLink:

    def __init__(self, page):
        self.css = page.get("css")
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

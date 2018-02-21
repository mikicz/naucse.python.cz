import datetime
from html.parser import HTMLParser
from xml.dom import SyntaxErr

import cssutils
from git import Repo


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


def get_recent_runs(course):
    """Build a list of "recent" runs based on a course.

    By recent we mean: haven't ended yet, or ended up to ~2 months ago
    (Note: even if naucse is hosted dynamically,
    it's still beneficial to show recently ended runs.)
    """
    recent_runs = []
    if not course.start_date:
        today = datetime.date.today()
        cutoff = today - datetime.timedelta(days=2*30)
        this_year = today.year
        for year, run_year in reversed(course.root.run_years.items()):
            for run in run_year.runs.values():
                if run.base_course is course and run.end_date > cutoff:
                    recent_runs.append(run)
            if year < this_year:
                # Assume no run lasts for more than a year,
                # e.g. if it's Jan 2018, some run that started in 2017 may
                # be included, but don't even look through runs from 2016
                # or earlier.
                break
    recent_runs.sort(key=lambda r: r.start_date, reverse=True)
    return recent_runs


def list_months(start_date, end_date):
    """Return a span of months as a list of (year, month) tuples

    The months of start_date and end_date are both included.
    """
    months = []
    year = start_date.year
    month = start_date.month
    while (year, month) <= (end_date.year, end_date.month):
        months.append((year, month))
        month += 1
        if month > 12:
            month = 1
            year += 1
    return months


_last_commit = None


def last_commit_modifying_lessons():
    """ Returns commit hash of the last commit which modified either lessons contents or rendering mechanisms of naucse.
    """
    from .routes import app
    global _last_commit
    if _last_commit:
        return _last_commit

    # git log -n 1 --format=%H lessons/ naucse/ licenses/
    last_commit = Repo(".").git.log("lessons/", "naucse/", n=1, format="%H")

    if not app.config['DEBUG']:
        _last_commit = last_commit

    return last_commit


class DisallowedElement(Exception):
    pass


class AllowedElementsParser(HTMLParser):

    def __init__(self, **kwargs):
        super(AllowedElementsParser, self).__init__(**kwargs)
        self.current_element = None
        self.css_parser = cssutils.CSSParser(raiseExceptions=True)
        self.allowed_elements = {
            # functional:
            'a', 'abbr', 'audio', 'img', 'source',

            # styling:
            'big', 'blockquote', 'code', 'font', 'i', 'tt', 'kbd', 'u', 'var', 'small', 'em', 'strong', 'sub',

            # formatting:
            'br', 'div', 'hr', 'p', 'pre', 'span',

            # lists
            'dd', 'dl', 'dt', 'li', 'ul', 'ol',

            # headers
            'h1', 'h2', 'h3', 'h4', 'h5', 'h6',

            # tables
            'table', 'tbody', 'td', 'th', 'thead', 'tr',

            # icons
            'svg', 'circle', 'path',

            # A special check is applied in `handle_data` method (only `.dataframe` styles allowed)
            'style',
        }

    def handle_starttag(self, tag, attrs):
        if tag not in self.allowed_elements:
            raise DisallowedElement(f"Element {tag} is not allowed.")
        self.current_element = tag

    def handle_startendtag(self, tag, attrs):
        if tag not in self.allowed_elements:
            raise DisallowedElement(f"Element {tag} is not allowed.")
        self.current_element = tag

    def handle_data(self, data):
        if self.current_element == "style":
            try:
                parsed_css = self.css_parser.parseString(data)
            except SyntaxErr:
                raise DisallowedElement("Style element is only allowed when it modifies .dataframe elements,"
                                        "could not parse styles and verify.")
            else:
                if len(parsed_css.cssRules) == 0:
                    return

                if not all([rule.selectorText.startswith(".dataframe") for rule in parsed_css.cssRules]):
                    raise DisallowedElement("Style element is only allowed when it modifies .dataframe elements. "
                                            "Rendered page contains a style that modifies something else.")

    def reset_and_feed(self, data):
        self.reset()
        self.feed(data)

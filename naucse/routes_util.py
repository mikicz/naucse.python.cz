import datetime


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
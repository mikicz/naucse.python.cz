import contextlib

from elsa._shutdown import ShutdownableFreezer
from flask_frozen import UrlForLogger

from naucse.utils.routes import absolute_urls_to_freeze


class AllLinksLogger(UrlForLogger):
    """ AllLinksLogger primarily logs ``url_for`` calls, but yields urls from  ``absolute_urls_to_freeze`` as well.
    """

    def iter_calls(self):
        """ Yields all logged urls and links parsed from content.
            Unfortunately, ``yield from`` cannot be used as the queues are modified on the go.
        """
        while self.logged_calls or absolute_urls_to_freeze:
            if self.logged_calls:
                yield self.logged_calls.popleft()
            if absolute_urls_to_freeze:
                yield absolute_urls_to_freeze.popleft()


@contextlib.contextmanager
def temporary_url_for_logger(app):
    """ A context manager which temporary adds a new UrlForLogger to the app and yields it, so it can be used
        to get logged calls.
    """
    logger = UrlForLogger(app)

    yield logger

    app.url_default_functions[None].pop(0)


class NaucseFreezer(ShutdownableFreezer):

    def __init__(self, app):
        super(NaucseFreezer, self).__init__(app)
        self.url_for_logger = AllLinksLogger(app)  # override the default url_for_logger with our modified version

import contextlib

from elsa._shutdown import ShutdownableFreezer
from flask_frozen import UrlForLogger

from naucse.utils.routes import urls_from_forks


class AllLinksLogger(UrlForLogger):
    """ AllLinksLogger logs both `url_for` calls and urls parsed from content (either returned from Arca or built,
        locally). The `iter_calls` method yields primarily urls from `url_for`, because they're more likely to be
        the ones, whose cached content will be later used in parsed urls.
    """

    def iter_calls(self):
        """ Yields all logged urls and links parsed from content.
            Unfortunately, `yield from` cannot be used as the queues are modified on the go
        """
        while self.logged_calls or urls_from_forks:
            if self.logged_calls:
                yield self.logged_calls.popleft()
            if urls_from_forks:
                yield urls_from_forks.popleft()


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

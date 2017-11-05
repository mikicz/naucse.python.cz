import collections
import mimetypes
import warnings
from urllib.parse import urlparse

import os
from bs4 import BeautifulSoup, SoupStrainer
from elsa._shutdown import ShutdownableFreezer
from flask_frozen import UrlForLogger, MimetypeMismatchWarning, RedirectWarning, conditional_context, patch_url_for, \
    NotFoundWarning


class AllLinksLogger(UrlForLogger):

    def __init__(self, *args):
        super(AllLinksLogger, self).__init__(*args)
        self.links = collections.deque()

    def is_absolute(self, url):
        return bool(urlparse(url).netloc)

    def add_page(self, content):
        for link in BeautifulSoup(content, "html.parser", parse_only=SoupStrainer("a")):
            if link.has_attr("href") and not self.is_absolute(link["href"]) and link["href"].startswith("/"):
                self.links.append(link["href"])

        for img in BeautifulSoup(content, "html.parser", parse_only=SoupStrainer("img")):
            if img.has_attr("src") and not self.is_absolute(img["src"]) and img["src"].startswith("/"):
                self.links.append(img["src"])

    def iter_calls(self):
        while self.logged_calls or self.links:
            if self.logged_calls:
                yield self.logged_calls.popleft()
            if self.links:
                yield self.links.popleft()


class NaucseFreezer(ShutdownableFreezer):

    def __init__(self, app):
        super(NaucseFreezer, self).__init__(app)
        self.url_for_logger = AllLinksLogger(app)  # override the default url_for_logger with our modified version

    # This function is a copy from the original Freezer
    # For efficiency sake the response is needed and there isn't a nice way to access it nicely
    # The modified part is at the bottom, clearly marked.

    def _build_one(self, url):
        """Get the given ``url`` from the app and write the matching file."""
        client = self.app.test_client()
        base_url = self.app.config['FREEZER_BASE_URL']
        redirect_policy = self.app.config['FREEZER_REDIRECT_POLICY']
        follow_redirects = redirect_policy == 'follow'
        ignore_redirect = redirect_policy == 'ignore'

        destination_path = self.urlpath_to_filepath(url)
        filename = os.path.join(self.root, *destination_path.split('/'))

        skip = self.app.config['FREEZER_SKIP_EXISTING']
        if skip and os.path.isfile(filename):
            return filename

        with conditional_context(self.url_for_logger, self.log_url_for):
            with conditional_context(patch_url_for(self.app),
                                     self.app.config['FREEZER_RELATIVE_URLS']):
                response = client.get(url, follow_redirects=follow_redirects,
                                      base_url=base_url)

        # The client follows redirects by itself
        # Any other status code is probably an error
        # except we explicitly want 404 errors to be skipped
        # (eg. while application is in development)
        ignore_404 = self.app.config['FREEZER_IGNORE_404_NOT_FOUND']
        if response.status_code != 200:
            if response.status_code == 404 and ignore_404:
                warnings.warn('Ignored %r on URL %s' % (response.status, url),
                              NotFoundWarning,
                              stacklevel=3)
            elif response.status_code in (301, 302) and ignore_redirect:
                warnings.warn('Ignored %r on URL %s' % (response.status, url),
                              RedirectWarning,
                              stacklevel=3)
            else:
                raise ValueError('Unexpected status %r on URL %s' % (response.status, url))

        if not self.app.config['FREEZER_IGNORE_MIMETYPE_WARNINGS']:
            # Most web servers guess the mime type of static files by their
            # filename.  Check that this guess is consistent with the actual
            # Content-Type header we got from the app.
            basename = os.path.basename(filename)
            guessed_type, guessed_encoding = mimetypes.guess_type(basename)
            if not guessed_type:
                # Used by most server when they can not determine the type
                guessed_type = self.app.config['FREEZER_DEFAULT_MIMETYPE']

            if not guessed_type == response.mimetype:
                warnings.warn(
                    'Filename extension of %r (type %s) does not match Content-'
                    'Type: %s' % (basename, guessed_type, response.content_type),
                    MimetypeMismatchWarning,
                    stacklevel=3)

        # Create directories as needed
        dirname = os.path.dirname(filename)
        if not os.path.isdir(dirname):
            os.makedirs(dirname)

        # Write the file, but only if its content has changed
        content = response.data
        if os.path.isfile(filename):
            with open(filename, 'rb') as fd:
                previous_content = fd.read()
        else:
            previous_content = None
        if content != previous_content:
            # Do not overwrite when content hasn't changed to help rsync
            # by keeping the modification date.
            with open(filename, 'wb') as fd:
                fd.write(content)

        ################################################################################################################
        # START MODIFIED PART
        ################################################################################################################

        if filename.endswith(".html") and "X-RENDERED-FROM-ARCA" in response.headers:
            self.url_for_logger.add_page(content)

        ################################################################################################################
        # END_MODIFIED PART
        ################################################################################################################

        response.close()
        return filename

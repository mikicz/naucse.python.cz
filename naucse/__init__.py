import logging
import sys
from logging.handlers import RotatingFileHandler

from naucse.freezer import NaucseFreezer

if sys.version_info[0] <3 :
    raise RuntimeError('We love Python 3.')

from elsa import cli
from naucse.routes import app


def main():
    handler = RotatingFileHandler('.arca/arca.log', maxBytes=10000, backupCount=0)
    formatter = logging.Formatter("[%(asctime)s] {%(pathname)s:%(lineno)d} %(levelname)s - %(message)s")

    handler.setLevel(logging.INFO)
    handler.setFormatter(formatter)

    logger = logging.getLogger("arca")
    logger.addHandler(handler)

    cli(app, base_url='http://naucse.python.cz', freezer=NaucseFreezer(app))

import logging
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

from naucse.freezer import NaucseFreezer

if sys.version_info[0] <3 :
    raise RuntimeError('We love Python 3.')

from elsa import cli
from naucse.routes import app


def main():
    log_path = Path(".arca/arca.log")
    log_path.parent.mkdir(exist_ok=True)
    log_path.touch()

    handler = RotatingFileHandler(log_path, maxBytes=10000, backupCount=0)
    formatter = logging.Formatter("[%(asctime)s] {%(pathname)s:%(lineno)d} %(levelname)s - %(message)s")

    handler.setLevel(logging.INFO)
    handler.setFormatter(formatter)

    logger = logging.getLogger("arca")
    logger.addHandler(handler)

    cli(app, base_url='http://naucse.poul.me', freezer=NaucseFreezer(app))

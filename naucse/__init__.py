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
    arca_log_path = Path(".arca/arca.log")
    arca_log_path.parent.mkdir(exist_ok=True)
    arca_log_path.touch()

    naucse_log_path = Path(".arca/naucse.log")
    naucse_log_path.touch()

    def get_handler(path):
        handler = RotatingFileHandler(path, maxBytes=10000, backupCount=0)
        formatter = logging.Formatter("[%(asctime)s] {%(pathname)s:%(lineno)d} %(levelname)s - %(message)s")

        handler.setLevel(logging.INFO)
        handler.setFormatter(formatter)

        return handler

    logger = logging.getLogger("arca")
    logger.addHandler(get_handler(arca_log_path))

    logger = logging.getLogger("naucse")
    logger.addHandler(get_handler(naucse_log_path))

    cli(app, base_url='http://naucse.poul.me', freezer=NaucseFreezer(app))

# encoding=utf-8
from __future__ import unicode_literals, print_function

import click
import elsa
from colorama import Fore, Style

from naucse.utils.routes import does_course_return_info


def cli(app, *, base_url=None, freezer=None):
    """ Extends the elsa command line interface with a new command which prints all courses and runs
        which are present with basic info about them.
    """
    elsa_group = elsa.cli(app, base_url=base_url, freezer=freezer, invoke_cli=False)

    reset = f"{Style.RESET_ALL}"
    blue = f"{Fore.BLUE}{Style.BRIGHT}"
    green = f"{Fore.GREEN}{Style.BRIGHT}"
    red = f"{Fore.RED}{Style.BRIGHT}"

    @click.group()
    def naucse():
        pass

    @naucse.command()
    @click.option("--forks-only", default=False, is_flag=True,
                  help="Only list courses and runs from forks")
    def list_courses(forks_only):
        """ List all courses and runs and info about them.

        Mainly useful for courses from forks, shows where do they sourced from and if
        they return even the most basic information and will therefore be included in
        list of courses/runs.

        A practical benefit also is that on Travis CI the docker images are pulled/built
        in this command and the freezing won't fail on the 10 minute limit if things are taking particularly long.
        """
        from naucse.routes import model

        def canonical(course, x=""):
            click.echo(f"{green}{course.slug}: {course.title}{x}{reset}")

        def fork_invalid(course):
            click.echo(f"{red}{course.slug}, from {course.repo}@{course.branch}: "
                       f"Fork doesn't return basic info, will be ignored.{reset}")

        def fork_valid(course, x=""):
            click.echo(f"{green}{course.slug}, from {course.repo}@{course.branch}: {course.title}{x}{reset}")

        click.echo(f"{blue}Courses:{reset}")

        for course in model.courses.values():
            if forks_only and not course.is_link():
                continue

            if not course.is_link():
                canonical(course)
            else:
                if does_course_return_info(course, force_ignore=True):
                    fork_valid(course)
                else:
                    fork_invalid(course)

        click.echo(f"{blue}Runs:{reset}")

        for course in model.runs.values():
            if forks_only and not course.is_link():
                continue

            if not course.is_link():
                canonical(course, x=f" ({course.start_date} - {course.end_date})")
            else:
                if does_course_return_info(course, ["start_date", "end_date"], force_ignore=True):
                    fork_valid(course, x=f" ({course.start_date} - {course.end_date})")
                else:
                    fork_invalid(course)

    cli = click.CommandCollection(sources=[naucse, elsa_group])

    return cli()

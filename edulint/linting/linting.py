from typing import List, Callable, Tuple, Dict, Set, Any
from edulint.linting.problem import ProblemJson, Problem
from edulint.linting.nonparsing_checkers import report_infile_config
from edulint.linting.process_handler import ProcessHandler
from edulint.linting.overrides import get_overriders
from edulint.linting.tweakers import get_tweakers, Tweakers
from edulint.config.config import ImmutableConfig
from edulint.options import Option, ImmutableT
from edulint.linters import Linter
from functools import partial
import sys
import json
import os


def get_proper_path(path: str) -> str:
    return os.path.abspath(path) if os.path.isabs(path) else os.path.relpath(path)


def flake8_to_problem(raw: ProblemJson) -> Problem:
    assert isinstance(raw["filename"], str), f'got {type(raw["filename"])} for filename'
    assert isinstance(raw["line_number"], int), f'got {type(raw["line_number"])} for line_number'
    assert isinstance(
        raw["column_number"], int
    ), f'got {type(raw["column_number"])} for column_number'
    assert isinstance(raw["code"], str), f'got {type(raw["code"])} for code'
    assert isinstance(raw["text"], str), f'got {type(raw["text"])} for text'

    return Problem(
        Linter.FLAKE8,
        get_proper_path(raw["filename"]),
        raw["line_number"],
        raw["column_number"],
        raw["code"],
        raw["text"],
    )


def pylint_to_problem(filenames: List[str], raw: ProblemJson) -> Problem:
    assert isinstance(raw["path"], str), f'got {type(raw["path"])} for path'
    assert isinstance(raw["line"], int), f'got {type(raw["line"])} for line'
    assert isinstance(raw["column"], int), f'got {type(raw["column"])} for column'
    assert isinstance(raw["message-id"], str), f'got {type(raw["message-id"])} for message-id'
    assert isinstance(raw["message"], str), f'got {type(raw["message"])} for message'
    assert (
        isinstance(raw["endLine"], int) or raw["endLine"] is None
    ), f'got {type(raw["endLine"])} for endLine'
    assert (
        isinstance(raw["endColumn"], int) or raw["endColumn"] is None
    ), f'got {type(raw["endColumn"])} for endColumn'
    assert isinstance(raw["symbol"], str), f'get {type(raw["symbol"])} for symbol'

    def get_used_filename(path: str) -> str:
        for filename in filenames:
            if os.path.abspath(filename) == os.path.abspath(path):
                return filename
        assert False, "unreachable"

    return Problem(
        Linter.PYLINT,
        get_proper_path(get_used_filename(raw["path"])),
        raw["line"],
        raw["column"],
        raw["message-id"],
        raw["message"],
        raw["endLine"],
        raw["endColumn"],
        raw["symbol"],
    )


def lint_any(
    linter: Linter,
    filenames: List[str],
    linter_args: List[str],
    config_arg: ImmutableT,
    result_getter: Callable[[Any], Any],
    out_to_problem: Callable[[ProblemJson], Problem],
) -> List[Problem]:
    command = [sys.executable, "-m", str(linter)] + linter_args + list(config_arg) + filenames  # type: ignore
    return_code, outs, errs = ProcessHandler.run(command, timeout=1000)

    if ProcessHandler.is_status_code_by_timeout(return_code):
        print(f"edulint: {linter} was likely killed by timeout", file=sys.stderr)
        raise TimeoutError(f"Timeout from {linter}")

    print(errs, file=sys.stderr, end="")
    if (linter == Linter.FLAKE8 and return_code not in (0, 1)) or (
        linter == Linter.PYLINT and return_code == 32
    ):
        print(f"edulint: {linter} exited with {return_code}", file=sys.stderr)
        exit(return_code)

    if not outs:
        return []

    result = result_getter(json.loads(outs))
    return list(map(out_to_problem, result))


def lint_edulint(filenames: List[str], config: ImmutableConfig) -> List[Problem]:
    ignored_infile = set(config[Option.IGNORE_INFILE_CONFIG_FOR])
    if len(ignored_infile) > 0:
        return report_infile_config(filenames, ignored_infile)
    return []


def lint_flake8(filenames: List[str], config: ImmutableConfig) -> List[Problem]:
    flake8_args = ["--format=json"]
    return lint_any(
        Linter.FLAKE8,
        filenames,
        flake8_args,
        config[Option.FLAKE8],
        lambda r: [problem for problems in r.values() for problem in problems],
        flake8_to_problem,
    )


def lint_pylint(filenames: List[str], config: ImmutableConfig) -> List[Problem]:
    pylint_args = ["--output-format=json"]
    return lint_any(
        Linter.PYLINT,
        filenames,
        pylint_args,
        config[Option.PYLINT],
        lambda r: r,
        partial(pylint_to_problem, filenames),
    )


def apply_overrides(problems: List[Problem], overriders: Dict[str, Set[str]]) -> List[Problem]:
    codes_on_lines: Dict[int, Set[str]] = {
        line: set() for line in set([problem.line for problem in problems])
    }

    for problem in problems:
        codes_on_lines[problem.line].add(problem.code)

    result = []
    for problem in problems:
        o = overriders.get(problem.code, set())
        if not (o & codes_on_lines[problem.line]):
            result.append(problem)

    return result


def apply_tweaks(
    problems: List[Problem], tweakers: Tweakers, config: ImmutableConfig
) -> List[Problem]:
    result = []
    for problem in problems:
        tweaker = tweakers.get((problem.source, problem.code))
        if tweaker:
            if tweaker.should_keep(
                problem, [arg for arg in config if arg.option in tweaker.used_options]
            ):
                problem.text = tweaker.get_reword(problem)
                result.append(problem)
        else:
            result.append(problem)
    return result


def lint_one(filename: str, config: ImmutableConfig) -> List[Problem]:
    return lint([filename], config)


def sort(filenames: List[str], problems: List[Problem]) -> List[Problem]:
    indices = {get_proper_path(fn): i for i, fn in enumerate(filenames)}
    problems.sort(key=lambda problem: (indices[problem.path], problem.line, problem.column))
    return problems


def lint(filenames: List[str], config: ImmutableConfig) -> List[Problem]:
    edulint_result = lint_edulint(filenames, config)
    flake8_result = [] if config[Option.NO_FLAKE8] else lint_flake8(filenames, config)
    pylint_result = lint_pylint(filenames, config)
    result = apply_overrides(edulint_result + flake8_result + pylint_result, get_overriders())
    result = apply_tweaks(result, get_tweakers(), config)
    return sort(filenames, result)


def lint_many(partition: List[Tuple[List[str], ImmutableConfig]]) -> List[Problem]:
    return [problem for filenames, config in partition for problem in lint(filenames, config)]

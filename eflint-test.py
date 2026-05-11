#!/usr/bin/env python3
# EFLINT TEST.py
#   by Lut99
#
# Created:
#   21 Jun 2024, 11:18:46
# Last edited:
#   05 Sep 2024, 14:59:54
# Auto updated?
#   Yes
#
# Description:
#   Implements a unit test script for eFLINT scripts.
#

import abc
import argparse
import io
import os
import random
import re
import subprocess
import string
import sys
import threading
from io import TextIOWrapper
from typing import Generator, List, Optional, Self, Set


##### CONSTANTS #####
# Defines the maximum line width occupied
CONSOLE_WIDTH: int = 150

# Defines the number of bytes to read per iteration of input file(s).
BUFFER_SIZE: int = 8192

# Defines a common prefix to all script prefixes
COMMON_PREFIX: str = "//#"
# Describes which header identifies 'assert'-comments
ASSERT_PREFIX: str = COMMON_PREFIX + "assert "
# Describes which header identifies 'violated'-comments
VIOLATED_PREFIX: str = COMMON_PREFIX + "violated "

# Describes which header identifiers `#require`-statements.
REQUIRE_PREFIX: str = "#require "
# Describes which header identifiers `#include`-statements.
INCLUDE_PREFIX: str = "#include "





##### GLOBALS #####
# Determines if `pdebug()` does anything
DEBUG: bool = False

# Determines if `perror()` has been called
ERRORED: bool = False


##### HELPER FUNCTIONS #####
def line_len(line: str):
    """
        Gets the length of a line without ANSI characters.
    """

    return len(re.sub(
        r'[\u001B\u009B][\[\]()#;?]*((([a-zA-Z\d]*(;[-a-zA-Z\d\/#&.:=?%@~_]*)*)?\u0007)|((\d{1,4}(?:;\d{0,4})*)?[\dA-PR-TZcf-ntqry=><~]))', '', line))



def supports_color():
    """
        Returns True if the running system's terminal supports color, and False
        otherwise.

        From: https://stackoverflow.com/a/22254892
    """
    plat = sys.platform
    supported_platform = plat != 'Pocket PC' and (plat != 'win32' or
                                                  'ANSICON' in os.environ)
    # isatty is not always implemented, #6223.
    is_a_tty = hasattr(sys.stdout, 'isatty') and sys.stdout.isatty()
    return supported_platform and is_a_tty


def get_default_jobs() -> int:
    """
        Returns a sensible cross-platform default for '-j/--jobs'.
    """

    # Linux can expose CPU affinity (available CPUs for this process).
    if hasattr(os, "sched_getaffinity"):
        try:
            affinity = os.sched_getaffinity(0)
            if affinity:
                return len(affinity)
        except OSError:
            # Fall through to a generic CPU count fallback.
            pass

    return max(1, os.cpu_count() or 1)


def pdebug(text: str, end: str = "\n", use_colour: Optional[bool] = None, file: io.TextIOWrapper = sys.stdout):
    """
        Prints a DEBUG-log message.
    """

    # Don't do anything if not debugging
    if not DEBUG: return

    # Derive colour annotations
    coloured = use_colour if use_colour is not None else supports_color()
    colour = Debug.get_accent() if coloured else ""
    clear = "\033[0m" if coloured else ""

    # Print it
    print(f"{colour}{Debug.get_prompt()}: {text}{clear}", end=end, file=file)

def pnote(text: str, end: str = "\n", use_colour: Optional[bool] = None, file: io.TextIOWrapper = sys.stdout):
    """
        Prints an INFO-log message.
    """

    # Derive colour annotations
    coloured = use_colour if use_colour is not None else supports_color()
    accent = Note.get_accent() if coloured else ""
    clear = "\033[0m" if coloured else ""

    # Print it
    print(f"{accent}{Note.get_prompt()}{clear}: {text}{clear}", end=end, file=file)

def pinfo(text: str, end: str = "\n", use_colour: Optional[bool] = None, file: io.TextIOWrapper = sys.stdout):
    """
        Prints an INFO-log message.
    """

    # Derive colour annotations
    coloured = use_colour if use_colour is not None else supports_color()
    accent = Note.get_accent() if coloured else ""
    clear = "\033[0m" if coloured else ""

    # Print it
    print(f"{accent}{Note.get_prompt()}{clear}: {text}{clear}", end=end, file=file)

def pwarn(text: str, end: str = "\n", use_colour: Optional[bool] = None, file: io.TextIOWrapper = sys.stderr):
    """
        Prints a WARN-log message.
    """

    # Derive colour annotations
    coloured = use_colour if use_colour is not None else supports_color()
    colour = Warn.get_accent() if coloured else ""
    bold = "\033[1m" if coloured else ""
    clear = "\033[0m" if coloured else ""

    # Print it
    print(f"{colour}{Warn.get_prompt()}{clear}{bold}: {text}{clear}", end=end, file=file)

def perror(text: str, end: str = "\n", use_colour: Optional[bool] = None, file: io.TextIOWrapper = sys.stderr):
    """
        Prints an ERROR-log message.
    """

    global ERRORED

    # Derive colour annotations
    coloured = use_colour if use_colour is not None else supports_color()
    colour = Err.get_accent() if coloured else ""
    bold = "\033[1m" if coloured else ""
    clear = "\033[0m" if coloured else ""

    # Print it
    print(f"{colour}{Err.get_prompt()}{clear}{bold}: {text}{clear}", end=end, file=file)
    ERRORED = True

def prunning(path: str, end: str = "\n", use_colour: Optional[bool] = None, file: io.TextIOWrapper = sys.stdout, width: int = CONSOLE_WIDTH, clear: bool = False):
    """
        Prints that a test file started running.
    """

    # Derive colour annotations
    coloured = use_colour if use_colour is not None else supports_color()
    clear = "\33[2K" if coloured and clear else ""
    colour = "\033[92;1m" if coloured else ""
    bold = "\033[1m" if coloured else ""
    fin = "\033[0m" if coloured else ""

    # Print it
    if len(path) > width - 8: path = "..." + path[len(path) - (width - 8 - 3):]
    print(f"{clear}{colour}Running{fin} {bold}{path}{fin}", end=end, file=file)

def ptesting(paths: List[str], end: str = "\n", use_colour: Optional[bool] = None, file: io.TextIOWrapper = sys.stdout, width: int = CONSOLE_WIDTH, clear: bool = False):
    """
        Prints an update on what is currently running
    """

    # Derive colour annotations
    coloured = use_colour if use_colour is not None else supports_color()
    clear = "\33[2K" if coloured and clear else ""
    colour = "\033[96;1m" if coloured else ""
    # bold = "\033[1m" if coloured else ""
    fin = "\033[0m" if coloured else ""

    # Print it
    paths = ', '.join(paths)
    if len(paths) > width - 8: paths = paths[:width - 8 - 3] + "..."
    print(f"{clear}{colour}Testing{fin} {paths}", end=end, file=file)
def ptesting_done(end: str = "\n", use_colour: Optional[bool] = None, file: io.TextIOWrapper = sys.stdout, width: int = CONSOLE_WIDTH, clear: bool = False):
    """
        Prints an update on what is currently running (which is nothing because we are done)
    """

    # Derive colour annotations
    coloured = use_colour if use_colour is not None else supports_color()
    clear = "\33[2K" if coloured and clear else ""
    colour = "\033[96;1m" if coloured else ""
    bold = "\033[1m" if coloured else ""
    fin = "\033[0m" if coloured else ""

    # Print it
    print(f"{clear}{colour}Testing{fin} {bold}done{end}", end=end, file=file)





##### CONTEXTS #####
class DoneContext():
    event: threading.Event

    def __init__(self, event: threading.Event):
        self.event = event

    def __enter__(self): return self.event

    def __exit__(self, type, value, traceback):
        self.event.set()
        return True





##### REPORTING #####
class Report(abc.ABC):
    """
        Abstract ancestor of various deferred log statements.
    """

    text: str

    def __init__(self, text: str):
        self.text = text


    def print_all(file: str, output: List[Self], use_colour: Optional[bool] = None, width: int = CONSOLE_WIDTH):
        assert width >= 20

        # Define colors
        colored = supports_color() if use_colour is None else use_colour
        accent = "\033[93;1m" if colored else ""
        bold = "\033[1m" if colored else ""
        clear = "\033[0m" if colored else ""

        # Render the header
        line_width = width - 4
        print()
        print(f"{bold}Test {clear}{accent}{file}{clear}{bold} reported:")
        print(f"┌{(line_width + 2) * '-'}┐")

        # Render the lines
        for rep in output:
            # Nothing to do if a debug but not DEBUG
            if not DEBUG and isinstance(rep, Debug): continue

            # Get some formatting information
            prompt = type(rep).get_prompt()
            prompt_len = len(prompt)
            accent = type(rep).get_accent() if colored else ""
            text = "\033[1m" if colored else ""
            if isinstance(rep, Debug):
                text = accent
            elif isinstance(rep, Info) or isinstance(rep, Note):
                text = ""

            # Perform a linebreak on the line
            chunk_width = line_width - prompt_len - 2
            lines = [[line[i:i+chunk_width] for i in range(0, len(line), chunk_width)] for line in rep.text.splitlines()]
            lines = [(f"| {accent}{prompt}{clear}{text}: {chunk}{clear}{(chunk_width - len(chunk)) * ' '} |" if i == 0 else f"| {len(prompt) * ' '}  {text}{chunk}{clear}{(chunk_width - len(chunk)) * ' '} |") for line in lines for i, chunk in enumerate(line)]

            # Print the lines
            for line in lines:
                print(line)

        # Draw the footer
        print(f"└{(line_width + 2) * '-'}┘")


    @abc.abstractmethod
    def get_prompt() -> str:
        raise NotImplementedError()

    @abc.abstractmethod
    def get_accent() -> str:
        raise NotImplementedError()

class Debug(Report):
    """
        Represents a debug statement for the user.
    """

    def __init__(self, text: str):
        Report.__init__(self, text)

    def get_prompt() -> str:
        return "DEBUG"

    def get_accent() -> str:
        return "\033[90;1m"

class Info(Report):
    """
        Represents an info statement for the user.
    """

    def __init__(self, text: str):
        Report.__init__(self, text)

    def get_prompt() -> str:
        return "INFO"

    def get_accent() -> str:
        return "\033[1m"

class Note(Report):
    """
        Represents a note statement for the user.
    """

    def __init__(self, text: str):
        Report.__init__(self, text)

    def get_prompt() -> str:
        return "NOTE"

    def get_accent() -> str:
        return "\033[94;1m"

class Warn(Report):
    """
        Represents a warning for the user.
    """

    def __init__(self, text: str):
        Report.__init__(self, text)

    def get_prompt() -> str:
        return "WARNING"

    def get_accent() -> str:
        return "\033[93;1m"

class Err(Report):
    """
        Represents an error for the user.
    """

    text: str

    def __init__(self, text: str):
        Report.__init__(self, text)

    def get_prompt() -> str:
        return "ERROR"

    def get_accent() -> str:
        return "\033[91;1m"





##### PARSER #####
class Instance(abc.ABC):
    """
        Represents a parsed `Instance`.
    """

    def parse(text: str) -> Optional[Self]:
        """
            Attempts to parse one of the child instances.

            # Arguments
            - `text`: Some string parsed from the input handle that should contain an instance.

            # Returns
            A new `Instance`, or `None` if we failed to parse one.
        """

        # Try any of the literals first
        if (lit := LitBool._parse(text)) is not None:
            return lit
        elif (lit := LitInt._parse(text)) is not None:
            return lit
        elif (lit := LitStr._parse(text)) is not None:
            return lit
        elif (lit := Wildcard._parse(text)) is not None:
            return lit
        else:
            return Composite._parse(text)

    def __eq__(self, other: Self) -> bool:
        if isinstance(self, LitBool) and isinstance(other, LitBool):
            return self.value == other.value
        elif isinstance(self, LitInt) and isinstance(other, LitInt):
            return self.value == other.value
        elif isinstance(self, LitStr) and isinstance(other, LitStr):
            return self.value == other.value
        elif isinstance(self, Composite) and isinstance(other, Composite):
            if self.name != other.name: return False
            if len(self.args) != len(other.args): return False
            for (arg1, arg2) in zip(self.args, other.args):
                if arg1 != arg2: return False
            return True
        elif isinstance(self, Wildcard) or isinstance(other, Wildcard):
            return True
        else:
            return False

    @abc.abstractmethod
    def _parse(text: str) -> Self:
        """
            Parser for a specific child instance.

            # Arguments
            - `text`: Some string parsed from the input handle that should contain an instance.

            # Returns
            A new `Instance`.

            # Errors
            This function can throw `` if it failed to parse the input text.
        """

        raise NotImplementedError("Instance does not implement '_parse' by itself; see any of the child classes.")

    @abc.abstractmethod
    def _to_eflint(self) -> str:
        raise NotImplementedError("Instance does not implement '_to_eflint' by itself; see any of the child classes.")

    @abc.abstractmethod
    def __str__(self) -> str:
        raise NotImplementedError("Instance does not implement '__str__' by itself; see any of the child classes.")

class LitBool(Instance):
    """
        A literal boolean instance.
    """

    value: bool

    def __init__(self, value: bool):
        """
            Constructor for the LitBool.

            # Arguments
            - `value`: The value of the boolean literal.
        """

        self.value = value

    def _parse(text: str) -> Optional[Instance]:
        """
            Parser for a LitBool

            # Arguments
            - `text`: Some string parsed from the input handle that should contain an instance.

            # Returns
            A new `LitBool`, or `None` if we failed to parse any.
        """

        # Strip whitespace out of courtesy
        text = text.strip()

        # Check values
        if text == "True":
            return LitBool(True)
        elif text == "False":
            return LitBool(False)
        else:
            return None

    def _to_eflint(self) -> str:
        return f"{'True' if self.value else 'False'}"

    def __str__(self) -> str:
        return f"Bool({self.value})"

    def __hash__(self):
        return hash(str(self))

class LitInt(Instance):
    """
        A literal int instance.
    """

    value: int

    def __init__(self, value: int):
        """
            Constructor for the LitInt.

            # Arguments
            - `value`: The value of the integer literal.
        """

        self.value = value

    def _parse(text: str) -> Optional[Instance]:
        """
            Parser for a LitInt

            # Arguments
            - `text`: Some string parsed from the input handle that should contain an instance.

            # Returns
            A new `LitInt`, or `None` if we failed to parse any.
        """

        # Strip whitespace out of courtesy
        text = text.strip()

        # Check values
        value = 0
        for c in text:
            if ord(c) >= ord('0') and ord(c) <= ord('9'):
                value *= 10
                value += int(c)
            else:
                return None
        return LitInt(value)

    def _to_eflint(self) -> str:
        return f"{self.value}"

    def __str__(self) -> str:
        return f"Int({self.value})"

    def __hash__(self):
        return hash(str(self))

class LitStr(Instance):
    """
        A literal string instance.
    """

    value: str

    def __init__(self, value: str):
        """
            Constructor for the LitStr.

            # Arguments
            - `value`: The value of the string literal.
        """

        self.value = value

    def _parse(text: str) -> Optional[Instance]:
        """
            Parser for a LitStr

            # Arguments
            - `text`: Some string parsed from the input handle that should contain an instance.

            # Returns
            A new `LitStr`, or `None` if we failed to parse any.
        """

        # Strip whitespace out of courtesy
        text = text.strip()

        # Little state machine
        state = 0
        i = 0
        value = ""
        while i < len(text):
            c = text[i]
            if state == 0:
                if ord(c) >= ord('A') and ord(c) <= ord('Z'):
                    # Capital letter
                    value += c
                    state = 1
                    i += 1
                    continue
                elif c == '"':
                    # Quoted
                    state = 2
                    i += 1
                    continue
                else:
                    return None
            elif state == 1:
                # Capital letter parsing
                if (ord(c) >= ord('A') and ord(c) <= ord('Z')) or (ord(c) >= ord('a') and ord(c) <= ord('z')):
                    value += c
                    i += 1
                    continue
                else:
                    return None
            elif state == 2:
                # Quoted parsing
                if c == '"':
                    # End
                    if i < len(text) - 1:
                        # Some was left
                        return None
                    i += 1
                    continue
                elif c == '\\':
                    state = 3
                    i += 1
                    continue
                else:
                    value += c
                    i += 1
                    continue
            elif state == 3:
                # Escaping characters
                value += c
                state = 2
                i += 1
                continue
            else:
                raise RuntimeError(f"Encountered unknown state '{state}' (should never happen!)")

        # OK, parsing done
        return LitStr(value)

    def _to_eflint(self) -> str:
        return f"\"{self.value}\""

    def __str__(self) -> str:
        return f"Str({self.value})"

    def __hash__(self):
        return hash(str(self))

class Composite(Instance):
    """
        A composite instance, existing of a name and 0 or more nested relations.
    """

    name: str
    args: List[Instance]

    def __init__(self, name: str, args: List[Instance]):
        """
            Constructor for the LitStr.

            # Arguments
            - `name`: The name of the type.
            - `args`: Any instance arguments.
        """

        self.name = name
        self.args = args

    def _parse(text: str) -> Optional[Instance]:
        """
            Parser for a Composite.

            # Arguments
            - `text`: Some string parsed from the input handle that should contain an instance.

            # Returns
            A new `Composite`, a `LitStr` if this is `ref(LitStr)`, or `None` if we failed to parse any.
        """

        # Strip whitespace out of courtesy
        text = text.strip()

        # Parse an identifier first
        name = ""
        i = 0
        while (
            i < len(text) and (
                (ord(text[i]) >= ord('a') and ord(text[i]) <= ord('z'))
                or (ord(text[i]) >= ord('A') and ord(text[i]) <= ord('Z'))
                # or (ord(text[i]) >= ord('0') and ord(text[i]) <= ord('9'))
                or (text[i] == '-')
                or (text[i] == '_')
        )):
            name += text[i]
            i += 1
        if len(name) == 0:
            return None

        # Parse an optional opening parenthesis
        args = []
        if i < len(text) and text[i] == '(':
            # Parse up until the next ')', collecting arguments as we go
            end_pos = -1
            j = i
            stack = 0
            raw_args = [""]
            while j < len(text):
                c = text[j]
                if c == '(':
                    if stack > 0:
                        raw_args[-1] += c
                    stack += 1
                elif c == ')':
                    stack -= 1
                    if stack == 0:
                        end_pos = j
                        break
                    elif stack < 0:
                        return None
                    raw_args[-1] += c
                elif c == ',' and stack == 1:
                    raw_args.append("")
                else:
                    raw_args[-1] += c
                j += 1
            if end_pos < 0:
                return None
            if len(raw_args) == 1 and len(raw_args[-1]) == 0:
                raw_args = []

            # Parse the arguments
            for arg in raw_args:
                arg = arg.strip()
                if (ins := Instance.parse(arg)) is not None:
                    args.append(ins)
                else:
                    raise ValueError(f"Failed to parse '{arg}' as an eFLINT instance")
            i = end_pos

            # Parse a closing parenthesis
            if i >= len(text) or text[i] != ')':
                return None
            i += 1

        # Everything must be consumed
        if i < len(text):
            return None

        # Then: collapse any `ref(STRING)` occurrences
        if name == "ref" and len(args) == 1 and isinstance(args[0], LitStr):
            return args[0]

        # OK, parsing done
        return Composite(name, args)

    def _to_eflint(self) -> str:
        return f"{self.name}({', '.join([arg._to_eflint() for arg in self.args])})"

    def __str__(self) -> str:
        return f"{self.name}({', '.join([str(arg) for arg in self.args])})"

    def __hash__(self):
        return hash(str(self))

class Wildcard(Instance):
    """
        A wildcard, which represents ANY instance.
    """

    def __init__(self):
        pass

    def _parse(text: str) -> Optional[Instance]:
        """
            Parser for a Wildcard.

            # Arguments
            - `text`: Some string parsed from the input handle that should contain an instance.

            # Returns
            A new `Wildcard`, or `None` if we failed to parse any.
        """

        # Strip whitespace out of courtesy
        text = text.strip()

        # See if it's an aterisk
        if text == "*":
            return Wildcard()
        else:
            return None

    def _to_eflint(self) -> str:
        return "*"

    def __str__(self) -> str:
        return "Wildcard"

    def __hash__(self):
        return hash(str(self))



class Effect(abc.ABC):
    """
        Represents a certain effect emitted by the reasoner.
    """

    def parse(line: str, reports: List[Report]) -> Optional[Self]:
        """
            Attempts to parse one of the child effects.

            # Arguments
            - `line`: Some line parsed from the input handle that should contain an effect.

            # Returns
            A new `Effect`, or `None` if we failed to parse one.
        """

        # Simply try them all
        if (
            ((effect := Create._parse(line, reports)) is not None)
            or ((effect := Terminate._parse(line, reports)) is not None)
            or ((effect := Obfuscate._parse(line, reports)) is not None)
            or ((effect := InvariantViolation._parse(line, reports)) is not None)
            or ((effect := ActViolation._parse(line, reports)) is not None)
            or ((effect := DutyViolation._parse(line, reports)) is not None)
        ):
            reports.append(Debug(f"    > Reasoner emitted {effect}"))
            return effect

        # Else, no luck chief
        return None

    def __eq__(self, other: Self) -> bool:
        if isinstance(self, Create) and isinstance(other, Create):
            return self.instance == other.instance
        elif isinstance(self, Terminate) and isinstance(other, Terminate):
            return self.instance == other.instance
        elif isinstance(self, Obfuscate) and isinstance(other, Obfuscate):
            return self.instance == other.instance
        elif isinstance(self, InvariantViolation) and isinstance(other, InvariantViolation):
            return self.name == other.name
        elif isinstance(self, ActViolation) and isinstance(other, ActViolation):
            return self.instance == other.instance
        elif isinstance(self, DutyViolation) and isinstance(other, DutyViolation):
            return self.instance == other.instance
        else:
            return False

    @abc.abstractmethod
    def __str__(self) -> str:
        raise NotImplementedError("Effect does not implement '__str__' by itself; see any of the child classes.")

class Create(Effect):
    """
        Represents the positive postulation of an instance.
    """

    instance: Instance

    def __init__(self, instance: Instance):
        """
            Constructor for the Create.

            # Arguments
            - `instance`: The created `Instance`.
        """

        self.instance = instance

    def _parse(line: str, reports: List[Report]) -> Optional[Self]:
        """
            Attempts to parse a Create-effect.

            # Arguments
            - `line`: Some line parsed from the input handle that should contain an effect.

            # Returns
            A new `Create`, or `None` if we failed to parse one.
        """

        # Strip the line
        line = line.strip()

        # The line must begin with a `+`
        if len(line) < 1 or line[0] != '+':
            return None

        # Then we expect an instance
        ins = Instance.parse(line[1:])
        if ins is None:
            reports.append(Warn(f"Failed to parse '+{line[1:]}' as a valid Create-effect"))
            reports.append(Note(f"The problem is parsing '{line[1:]}' as an instance"))

        # OK, create self
        return Create(ins)

    def __str__(self) -> str:
        return f"Create({self.instance._to_eflint()})"

    def __hash__(self) -> int:
        return hash(str(self))

class Terminate(Effect):
    """
        Represents the negative postulation of an instance.
    """

    instance: Instance

    def __init__(self, instance: Instance):
        """
            Constructor for the Terminate.

            # Arguments
            - `instance`: The terminated `Instance`.
        """

        self.instance = instance

    def _parse(line: str, reports: List[Report]) -> Optional[Self]:
        """
            Attempts to parse a Terminate-effect.

            # Arguments
            - `line`: Some line parsed from the input handle that should contain an effect.

            # Returns
            A new `Terminate`, or `None` if we failed to parse one.
        """

        # Strip the line
        line = line.strip()

        # The line must begin with a `-`
        if len(line) < 1 or line[0] != '-':
            return None

        # Then we expect an instance
        ins = Instance.parse(line[1:])
        if ins is None:
            reports.append(Warn(f"Failed to parse '-{line[1:]}' as a valid Terminate-effect"))
            reports.append(Note(f"The problem is parsing '{line[1:]}' as an instance"))

        # OK, create self
        return Terminate(ins)

    def __str__(self) -> str:
        return f"Terminate({self.instance._to_eflint()})"

    def __hash__(self) -> int:
        return hash(str(self))

class Obfuscate(Effect):
    """
        Represents the obfuscating postulation of an instance.

        For now, this is interpreted as a `Terminate`.
    """

    instance: Instance

    def __init__(self, instance: Instance):
        """
            Constructor for the Obfuscate.

            # Arguments
            - `instance`: The obfuscated `Instance`.
        """

        self.instance = instance

    def _parse(line: str, reports: List[Report]) -> Optional[Self]:
        """
            Attempts to parse a Obfuscate-effect.

            # Arguments
            - `line`: Some line parsed from the input handle that should contain an effect.

            # Returns
            A new `Obfuscate`, or `None` if we failed to parse one.
        """

        # Strip the line
        line = line.strip()

        # The line must begin with a `~`
        if len(line) < 1 or line[0] != '~':
            return None

        # Then we expect an instance
        ins = Instance.parse(line[1:])
        if ins is None:
            reports.append(Warn(f"Failed to parse '~{line[1:]}' as a valid Obfuscate-effect"))
            reports.append(Note(f"The problem is parsing '{line[1:]}' as an instance"))

        # OK, create self
        return Obfuscate(ins)

    def __str__(self) -> str:
        return f"Obfuscate({self.instance._to_eflint()})"

    def __hash__(self) -> int:
        return hash(str(self))

class InvariantViolation(Effect):
    """
        Represents a violated invariant.
    """

    name: str

    def __init__(self, name: str):
        """
            Constructor for the InvariantViolation.

            # Arguments
            - `name`: The name of the violated invariant.
        """

        self.name = name

    def _parse(line: str, _reports: List[Report]) -> Optional[Self]:
        """
            Attempts to parse a InvariantViolation-effect.

            # Arguments
            - `line`: Some line parsed from the input handle that should contain an effect.

            # Returns
            A new `InvariantViolation`, or `None` if we failed to parse one.
        """

        # Strip the line
        line = line.strip()

        # The line must begin with a `violated invariant!: `
        if len(line) < 21 or line[:21] != 'violated invariant!: ':
            return None
        # Then we expect a string name
        name = line[21:]

        # OK, create self
        return InvariantViolation(name)

    def __str__(self) -> str:
        return f"InvariantViolation({self.name})"

    def __hash__(self) -> int:
        return hash(str(self))

class ActViolation(Effect):
    """
        Represents a violated Act (i.e., it was disabled).
    """

    instance: Instance

    def __init__(self, instance: Instance):
        """
            Constructor for the ActViolation.

            # Arguments
            - `instance`: The violated Act itself.
        """

        self.instance = instance

    def _parse(line: str, reports: List[Report]) -> Optional[Self]:
        """
            Attempts to parse a ActViolation-effect.

            # Arguments
            - `line`: Some line parsed from the input handle that should contain an effect.

            # Returns
            A new `ActViolation`, or `None` if we failed to parse one.
        """

        # Strip the line
        line = line.strip()

        # The line must begin with a `disabled action: `
        if len(line) < 17 or line[:17] != 'disabled action: ':
            return None
        raw_ins = line[17:]

        # Then we expect the violated Act instance
        ins = Instance.parse(raw_ins)
        if ins is None:
            reports.append(Warn(f"Failed to parse 'disabled action: {raw_ins}' as a valid ActViolation-effect"))
            reports.append(Note(f"The problem is parsing '{raw_ins}' as an instance"))

        # OK, create self
        return ActViolation(ins)

    def __str__(self) -> str:
        return f"ActViolation({self.instance._to_eflint()})"

    def __hash__(self) -> int:
        return hash(str(self))

class DutyViolation(Effect):
    """
        Represents a violated Duty.
    """

    instance: Instance

    def __init__(self, instance: Instance):
        """
            Constructor for the DutyViolation.

            # Arguments
            - `instance`: The violated Duty itself.
        """

        self.instance = instance

    def _parse(line: str, reports: List[Report]) -> Optional[Self]:
        """
            Attempts to parse a DutyViolation-effect.

            # Arguments
            - `line`: Some line parsed from the input handle that should contain an effect.

            # Returns
            A new `DutyViolation`, or `None` if we failed to parse one.
        """

        # Strip the line
        line = line.strip()

        # The line must begin with a `violated duty!: `
        if len(line) < 16 or line[:16] != 'violated duty!: ':
            return None
        raw_ins = line[16:]

        # Then we expect the violated Duty instance
        ins = Instance.parse(raw_ins)
        if ins is None:
            reports.append(Warn(f"Failed to parse 'violated duty!: {raw_ins}' as a valid DutyViolation-effect"))
            reports.append(Note(f"The problem is parsing '{raw_ins}' as an instance"))

        # OK, create self
        return DutyViolation(ins)

    def __str__(self) -> str:
        return f"DutyViolation({self.instance._to_eflint()})"

    def __hash__(self) -> int:
        return hash(str(self))



class Phrase(abc.ABC):
    """
        Abstract parent of possible phrases.
    """

    _line: int

    def parse(line: str, l: int) -> Self:
        """
            Attempts to parse one of the child phrases.

            # Arguments
            - `line`: Some line parsed from the input handle. It is assumed it is a full line, excluding any newlines.
            - `l`: The line one's parsing.

            # Returns
            A new `Phrase`.

            # Errors
            This function can throw `ValueError` if it failed to parse the input `line`.
        """

        # Apply some "lookahead"
        if len(line) >= len(ASSERT_PREFIX) and line[:len(ASSERT_PREFIX)] == ASSERT_PREFIX:
            # It's an assert

            # Check if a negation follows
            line = line[len(ASSERT_PREFIX):].strip()
            if len(line) >= 1 and line[0] == "!":
                line = line[1:].strip()
                existance = False
            elif (len(line) >= 3 and line[:3] == "not") or (len(line) >= 3 and line[:3] == "Not"):
                line = line[3:].strip()
                existance = False
            else:
                existance = True

            # Parse an instance now
            ins = Instance.parse(line)
            if ins is None:
                raise ValueError(f"Failed to parse '{line}' as an eFLINT instance")

            # Return the phrase now
            return AssertPhrase(ins, existance, l)

        elif len(line) >= len(VIOLATED_PREFIX) and line[:len(VIOLATED_PREFIX)] == VIOLATED_PREFIX:
            # It's a violated

            # Check if a negation follows
            line = line[len(VIOLATED_PREFIX):].strip()
            if len(line) >= 1 and line[0] == "!":
                line = line[1:].strip()
                existance = False
            elif (len(line) >= 3 and line[:3] == "not") or (len(line) >= 3 and line[:3] == "Not"):
                line = line[3:].strip()
                existance = False
            else:
                existance = True

            # Parse an instance now
            ins = Instance.parse(line)
            if ins is None:
                raise ValueError(f"Failed to parse '{line}' as an eFLINT instance")

            # Return the phrase now
            return ViolatedPhrase(ins, existance, l)

        elif len(line) >= len(REQUIRE_PREFIX) and line[:len(REQUIRE_PREFIX)] == REQUIRE_PREFIX:
            # It's a `#require`

            # Get the string literal
            string = LitStr._parse(line[len(REQUIRE_PREFIX):])
            if string is None:
                raise ValueError(f"Failed to parse '{line[len(REQUIRE_PREFIX):]}' as an eFLINT string literal")

            # Return the phrase now
            return ImportPhrase(string.value, True, l)
        elif len(line) >= len(INCLUDE_PREFIX) and line[:len(INCLUDE_PREFIX)] == INCLUDE_PREFIX:
            # It's a `#include`

            # Get the string literal
            string = LitStr._parse(line[len(INCLUDE_PREFIX):])
            if string is None:
                raise ValueError(f"Failed to parse '{line[len(INCLUDE_PREFIX):]}' as an eFLINT string literal")

            # Return the phrase now
            return ImportPhrase(string.value, False, l)

        else:
            # It's a raw
            return EFlintPhrase(line, l)

    @abc.abstractmethod
    def __str__(self) -> str:
        raise NotImplementedError("Phrase does not implement '__str__' by itself; see any of the child classes.")

class AssertPhrase(Phrase):
    """
        A special test comment that asserts whether some instance is present.
    """

    existance: bool
    instance: Instance

    def __init__(self, instance: Instance, existance: bool, l: int):
        """
            Constructor for the AssertPhrase.

            # Arguments
            - `instance`: Some parsed `Instance` that will be checked for in the knowledge base.
            - `existance`: Whether to check for the _existance_ (True) of the `instance`, or the _absence_ (False).
            - `l`: The line one's parsing.
        """

        self._l = l

        self.existance = existance
        self.instance = instance

    def __str__(self) -> str:
        return f"Assert({'' if self.existance else '!'}{self.instance})"

class ViolatedPhrase(Phrase):
    """
        A special test comment that asserts whether something is (not) violated.
    """

    existance: bool
    instance: Instance

    def __init__(self, instance: Instance, existance: bool, l: int):
        """
            Constructor for the ViolatedPhrase.

            # Arguments
            - `instance`: Some parsed `Instance` of which its violated status will be checked.
            - `existance`: Whether to check for the _existance_ (True) of the `instance`, or the _absence_ (False).
            - `l`: The line one's parsing.
        """

        self._l = l

        self.existance = existance
        self.instance = instance

    def __str__(self) -> str:
        return f"Violated({'' if self.existance else '!'}{self.instance})"

class ImportPhrase(Phrase):
    """
        Represent eFLINT's `#require "".` and `#include "".`-statements.
    """

    # If True, then it's a `#require`; else, it's an `#include`
    include_once: bool
    # The directory to import the file from
    fold: Optional[str]
    # The file to import
    file: str

    def __init__(self, path: str, include_once: bool, l: int):
        """
            Constructor for the ImportPhrase.

            # Arguments
            - `include_once`: Whether this is a `#require` (True) or an `#include` (False).
            - `path`: The path given in the file. Will be split into a directory-part (if any) and a file-part.
            - `l`: The line one's parsing.
        """

        self._l = l
        self.include_once = include_once

        # Split into a directory name and file name
        self.fold = os.path.dirname(path)
        if len(self.fold) == 0: self.fold = None
        self.file = os.path.basename(path)

    def __str__(self) -> str:
        return f"{'Require' if self.include_once else 'Include'}({self.file}{' (include dir: ' + self.fold + ')' if self.fold is not None else ''})"

class EFlintPhrase(Phrase):
    """
        Any eFLINT phrase not parsed by the tool.
    """

    line: str

    def __init__(self, line: str, l: int):
        """
            Constructor for the EFlintPhrase.

            # Arguments
            - `line`: Some "raw" eFLINT phrase (line) to store. Should _not_ include newlines.
            - `l`: The line one's parsing.
        """

        self._l = l

        self.line = line

    def __str__(self) -> str:
        return f"EFlint({self.line})"



class PhraseParser:
    """
        Defines a parser over a file that returns objects relevant to eFLINT phrases.
    """

    _input: str
    reports: List[Report]


    def __init__(self, h: TextIOWrapper, reports: List[Report] = []):
        """
            Constructor for the Phraseparser.

            Note that we'll read the entire input in one go. Not crazy elegant, but simple.

            # Arguments
            - `h`: Some handle to something producing text.
        """

        # Initialize ourselves
        self._input = h.read()
        self.reports = reports

        # Preprocess out all comments
        i = 0
        while i < len(self._input):
            rem = self._input[i:]

            # Check if we're looking at a comment (but NOT our prefixes)
            if (len(rem) >= 2 and rem[:2] == "//"
                and (len(rem) < len(ASSERT_PREFIX) or rem[:len(ASSERT_PREFIX)] != ASSERT_PREFIX)
                and (len(rem) < len(VIOLATED_PREFIX) or rem[:len(VIOLATED_PREFIX)] != VIOLATED_PREFIX)
            ):
                # OK; find the end of the comment
                newline_pos = rem.find('\n')
                if newline_pos >= 0:
                    self._input = self._input[:i] + self._input[i + newline_pos:]
                else:
                    self._input = self._input[:i]
                continue

            # Else, slide the window
            i += 1

        # OK, ready to parse phrases
        self.reports.append(Debug(f"Preprocessed input file:\n{'-' * 80}\n{self._input}\n{'-' * 80}"))

    def phrases(self) -> Generator[Phrase, None, None]:
        """
            Iterator for reading phrases.

            # Returns
            A [`Phrase`] that encodes something from the eFLINT program, or `None` if there aren't any.
        """

        i = 0
        l = 1
        while i < len(self._input):
            # Get the next phrase
            new_l = l
            mode = [0]
            raw_phrase = ""
            while i < len(self._input):
                c = self._input[i]

                # Switch on the state
                if mode[-1] == 0:
                    if c == '.':
                        i += 1
                        break
                    elif c == '{':
                        # Start of a phrase group
                        mode[-1] = 1
                        raw_phrase += c
                        i += 1
                        continue
                    elif c == '(':
                        # Start of a parenthesis
                        mode.append(4)
                        raw_phrase += c
                        i += 1
                        continue
                    elif c == '"':
                        # Start of a string; essentially enter escape mode
                        mode.append(2)
                        raw_phrase += c
                        i += 1
                        continue
                    elif c.isspace():
                        # Note newlines
                        if c == '\n':
                            new_l += 1
                            if len(raw_phrase) > 0 and not raw_phrase[-1].isspace():
                                raw_phrase += ' '
                        elif len(raw_phrase) > 0 and not raw_phrase[-1].isspace():
                            raw_phrase += c
                        i += 1
                        continue
                    else:
                        # Keep parsing the phrase
                        raw_phrase += c
                        i += 1
                        continue
                elif mode[-1] == 1:
                    if c == '}':
                        # end of a phrase group
                        raw_phrase += c
                        i += 1
                        break
                    elif c == '"':
                        # Start of a string; essentially enter escape mode
                        mode.append(2)
                        raw_phrase += c
                        i += 1
                        continue
                    elif c.isspace():
                        # Note newlines
                        if c == '\n':
                            new_l += 1
                            if len(raw_phrase) > 0 and not raw_phrase[-1].isspace():
                                raw_phrase += ' '
                        elif len(raw_phrase) > 0 and not raw_phrase[-1].isspace():
                            raw_phrase += c
                        i += 1
                        continue
                    else:
                        # Keep parsing the phrase
                        raw_phrase += c
                        i += 1
                        continue
                elif mode[-1] == 2:
                    if c == '\\':
                        # Enter _escape_ escape mode
                        mode.append(3)
                        raw_phrase += c
                        i += 1
                        continue
                    elif c == '"':
                        # Exit string mode
                        mode.pop()
                        raw_phrase += c
                        i += 1
                        continue
                    else:
                        raw_phrase += c
                        i += 1
                        continue
                elif mode[-1] == 3:
                    # Just parse the character literally
                    mode.pop()
                    raw_phrase += c
                    i += 1
                    continue
                elif mode[-1] == 4:
                    if c == '(':
                        # Increase the level of indentation
                        mode.append(4)
                        raw_phrase += c
                        i += 1
                        continue
                    elif c == ')':
                        mode.pop()
                        raw_phrase += c
                        i += 1
                        continue
                    elif c.isspace():
                        # Note newlines
                        if c == '\n':
                            new_l += 1
                            if len(raw_phrase) > 0 and not raw_phrase[-1].isspace():
                                raw_phrase += ' '
                        elif len(raw_phrase) > 0 and not raw_phrase[-1].isspace():
                            raw_phrase += c
                        i += 1
                        continue
                    else:
                        raw_phrase += c
                        i += 1
                        continue
                else:
                    raise RuntimeError(f"Encountered unknown parse state '{mode}' (this should never happen!)")
            self.reports.append(Debug(f" > Parsing '{raw_phrase}' (line {l})"))

            # If it's empty, just skip
            if len(raw_phrase.strip()) == 0: continue

            # Attempt to parse as a phrase
            try:
                phrase = Phrase.parse(raw_phrase, l + 1)
            except ValueError as e:
                self.reports.append(Err(f"{l}: {e}"))
            l = new_l
            yield phrase

class Reasoner:
    """
        Wrapper around an eFLINT reasoner process to run tests.
    """

    _cmd: List[str]
    _h: subprocess.Popen
    _trigger_fact: str
    _trigger_fact_state: bool
    effects: List[Effect]
    handled_violations: Set[Effect]
    checked_ever: bool
    reports: List[Report]


    def __init__(self, exec: str, include_dirs: List[str], reports: List[Report] = []):
        """
            Constructor for the Reasoner.

            # Arguments
            - `exec`: The command to execute to call the reasoner.
            - `include_dirs`: Any (additional) include directories to pass to the `eflint-repl`.
        """

        # Build the command
        self._cmd = os.path.expanduser(os.path.expandvars(exec)).split()
        for incl in include_dirs:
            self._cmd += ["-i", os.path.realpath(incl)]

        # Call the command
        self._h = subprocess.Popen(self._cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    
        # Set the text buffer
        self.effects = []
        self.handled_violations = set()
        self.checked_ever = False
        self.reports = reports

        # Set the random fact
        self._trigger_fact = f"unit-tester-{''.join(random.choices(string.ascii_lowercase, k=16))}"
        self._trigger_fact_state = False

        # Wait until we've had the initial text
        while True:
            # Read a line
            line = self._h.stdout.readline().decode("utf-8")
            # Check if it's ready for input
            if len(line) >= 24 and line[:24] == " or just type a <PHRASE>":
                break

        # Define the random trigger fact
        self._h.stdin.write(f"Fact {self._trigger_fact} Identified by Int.\n".encode("utf-8"))
        self._h.stdin.flush()

    def submit(self, phrase: EFlintPhrase, strict: bool):
        """
            Submits a raw eFLINT snippet to the reasoner.

            # Arguments
            - `phrase`: Some `EFlintPhrase` to submit.
        """

        self.reports.append(Debug(f" > Submitting: \"{phrase.line}\\n\""))
        self._h.stdin.write(phrase.line.encode("utf-8"))
        self._h.stdin.write(b'\n')

        # Also submit the trigger state to get the next one
        self._h.stdin.write(f"{'~' if self._trigger_fact_state else '+'}{self._trigger_fact}(0).\n".encode("utf-8"))
        self._h.stdin.flush()
        self._trigger_fact_state = not self._trigger_fact_state

        # Collect results until the prompt appears for new input
        chunk = ""
        while True:
            # Read a line
            line = self._h.stdout.readline().decode("utf-8")

            # Skip the first input (creating the trigger state)
            if len(line) >= 5 and line[:5] == "#1 > ":
                continue

            # Remove any prompts
            while len(line) >= 1 and line[0] == "#" and line.find(" > ") >= 0:
                line = line[line.find(" > ") + 3:]
            self.reports.append(Debug(f"    > Effect: \"{line.strip()}\""))

            # Check if it's our stop marker
            if (len(line) >= 1 and (line[0] == '+' or line[0] == '~')
                and Instance.parse(line[1:]) == Composite(self._trigger_fact, [LitInt(0)])
            ):
                # It's our triggered state, so quit
                break

            # Otherwise, it's any effect line
            chunk += line

        # Now parse the effect lines
        for line in chunk.splitlines():
            # Define some special lines that would be recognized as effects but shouldn't be
            contains_exception = lambda line: "+ AKA keychar('+')" in line or "- AKA keychar('-')" in line or "~ AKA keychar('~')" in line

            # Now attempt to parse the line
            if not contains_exception(line) and (effect := Effect.parse(line, self.reports)) is not None:
                self.effects.append(effect)
            elif not (
                (len(line) >= 9 and line[:9] == "New type ")
                or (len(line) >= 14 and line[:14] == "New invariant ")
                or (len(line) >= 11 and line[:11] == "violations:")
                or (len(line) >= 6 and line[:6] == "query ")
                or (len(line) >= 20 and line[:20] == "executed transition:")
                or (len(line) >= 10 and line[-10:] == " (ENABLED)")
                or (len(line) >= 11 and line[-11:] == " (DISABLED)")
            ):
                if not strict:
                    self.reports.append(Warn(line))
                else:
                    self.reports.append(Err(line))
            else:
                # Just skip
                continue

    def check(self, phrase: AssertPhrase):
        """
            Checks if a particular fact is derived in the current knowledge base.

            # Arguments
            - `phrase`: The AssertPhrase to check.
        """

        self.reports.append(Debug(f" > Assert: {'' if phrase.existance else '!'}{phrase.instance._to_eflint()}"))
        self.checked_ever = True

        # Now iterate over the contents to find the result
        derived_instances = set()
        for effect in self.effects:
            if isinstance(effect, Create):
                # If they are the same, party
                if phrase.instance == effect.instance:
                    derived_instances.add(effect.instance)
            elif isinstance(effect, Terminate):
                # If they are the same, party
                if phrase.instance == effect.instance:
                    derived_instances.remove(effect.instance)
            elif isinstance(effect, Obfuscate):
                # If they are the same, party
                if phrase.instance == effect.instance:
                    derived_instances.remove(effect.instance)

        # Assert whether this is what we expect
        if (len(derived_instances) > 0) != phrase.existance:
            self.reports.append(Err(f"Assertion on line {phrase._l} failed: instance '{phrase.instance._to_eflint()}' {'does not ' if phrase.existance else ''}hold{'' if phrase.existance else 's'}"))
            if not phrase.existance:
                for ins in derived_instances:
                    self.reports.append(Note(f"Assertion on line {phrase._l} counter-evidence: '{ins._to_eflint()}'"))

    def violated(self, phrase: ViolatedPhrase):
        """
            Checks if a particular thing is violated in the current knowledge base.

            # Arguments
            - `phrase`: The ViolatedPhrase to check.
        """

        self.reports.append(Debug(f" > Violated: {'' if phrase.existance else '!'}{phrase.instance._to_eflint()}"))
        self.checked_ever = True

        # Now iterate over the contents to find the result
        if isinstance(phrase.instance, Composite):
            sname = phrase.instance.name
        else:
            sname = None
        violated_instances = set()
        for effect in self.effects:
            if isinstance(effect, InvariantViolation):
                if sname == effect.name:
                    violated_instances.add(Composite(effect.name, []))
                    self.handled_violations.add(effect)
            elif isinstance(effect, ActViolation):
                # If they are the same, party
                if phrase.instance == effect.instance:
                    violated_instances.add(effect.instance)
                    self.handled_violations.add(effect)
            elif isinstance(effect, DutyViolation):
                # If they are the same, party
                if phrase.instance == effect.instance:
                    violated_instances.add(effect.instance)
                    self.handled_violations.add(effect)

        # If we got here, did not violate
        if phrase.existance and len(violated_instances) == 0:
            self.reports.append(Err(f"Assertion on line {phrase._l} failed: instance '{phrase.instance._to_eflint()}' does not violate"))
        elif not phrase.existance and len(violated_instances) > 0:
            self.reports.append(Err(f"Assertion on line {phrase._l} failed: instance '{phrase.instance._to_eflint()}' violates"))
            for ins in violated_instances:
                self.reports.append(Info(f"Assertion on line {phrase._l} counter-evidence: '{ins._to_eflint()}'"))
            self.reports.append(Note(f"Violation scanning is incomplete. This tool does not detect if violations are later resolved."))





##### ENTRYPOINT #####
class UnitTest(threading.Thread):
    """
        Represents the business logic for running a single test on its own thread.
    """

    # The file to test
    file: str
    # Whether to turn (some) warnings into errors
    strict: bool
    # Which additional eFLINT include directories to define.
    include_dirs: List[str]
    # Does not add the test's parent directory as include directory if True.
    no_test_include: bool
    # The event to use to wakeup the main thread.
    event: threading.Event
    # The output string to write
    output: List[Report]


    def __init__(self, file: str, exe: List[str], strict: bool, include_dirs: List[str], no_test_include: bool, event: threading.Event):
        """
            Constructor for the UnitTest.

            # Arguments
            - `file`: The file to test.
            - `exe`: The `eflint-repl` executable to call.
            - `strict`: If given, turns unknown line warnings into errors.
            - `include_dirs`: Any (additional) include directories to pass to the `eflint-repl`.
            - `no_test_include`: Does not automatically include test file directories if given, only `include_dirs`.
            - `event`: Event to use to wakeup the parent thread.
        """

        threading.Thread.__init__(self, name=f"eflint-test.py: '{file}'", daemon=True)

        # Store the things we need
        self.file = file
        self.exe = exe
        self.strict = strict
        self.include_dirs = include_dirs
        self.no_test_include = no_test_include
        self.event = event
        self.output = []

    def run(self):
        with DoneContext(self.event):
            # Setup the parser and parse all phrases into a list first
            try:
                phrases = list(PhraseParser(open(self.file, "r"), reports=self.output).phrases())
            except IOError as e:
                self.output.append(Err(f"Failed to open file '{self.file}': {e}"))
                return

            # Find all imports and their include directories
            incl_dirs = set(self.include_dirs.copy())
            if not self.no_test_include:
                basedir = os.path.dirname(self.file)
                for phrase in phrases:
                    if not isinstance(phrase, ImportPhrase):
                        continue
                    if phrase.fold is not None:
                        path = phrase.fold
                        if not os.path.isabs(path):
                            path = os.path.join(basedir, path)
                        incl_dirs.add(path)

            # Setup the reasoner with the relevant include directories
            reasoner = Reasoner(self.exe, list(incl_dirs), reports=self.output)

            # Setup the parser
            for phrase in phrases:
                self.output.append(Debug(f" > Next phrase: {phrase}"))

                # Match
                if isinstance(phrase, AssertPhrase):
                    reasoner.check(phrase)
                elif isinstance(phrase, ViolatedPhrase):
                    reasoner.violated(phrase)
                elif isinstance(phrase, EFlintPhrase):
                    reasoner.submit(phrase, self.strict)
                elif isinstance(phrase, ImportPhrase):
                    reasoner.submit(EFlintPhrase(f"#{'require' if phrase.include_once else 'include'} {phrase.file}", phrase._l), self.strict)
                else:
                    raise RuntimeError(f"Received invalid phrase '{phrase}' from phrase parser (this should never happen!)")

            # Warn if we never called anything interesting
            if not reasoner.checked_ever:
                self.output.append(Warn("No '//#assert' or '//#violated' in file"))

            # Warn if there are uncaught violations
            for effect in reasoner.effects:
                if (
                    isinstance(effect, InvariantViolation)
                    or isinstance(effect, ActViolation)
                    or isinstance(effect, DutyViolation)
                ):
                    if not effect in reasoner.handled_violations:
                        self.output.append(Warn(f"Violation '{effect}' occurred which has not been asserted to (not) occur"))
                        reasoner.handled_violations.add(effect)

            # Done!
            return



def main(files: List[str], extension: str, exe: str, strict: bool, n_jobs: int, include_dirs: List[str], no_test_include: bool) -> int:
    """
        Main entrypoint to the script.

        # Arguments
        - `files`: The files to test.
        - `extension`: The extensions to filter on iff `files` is a directory.
        - `exe`: Shell command that will run `eflint-repl`.
        - `strict`: If given, turns unknown line warnings into errors.
        - `n_jobs`: The number of tests to run in parallel.
        - `include_dirs`: Any (additional) include directories to pass to the `eflint-repl`.
        - `no_test_include`: Does not automatically include test file directories if given, only `include_dirs`.

        # Returns
        The exit code with which the script exits.
    """
    pdebug("***eflint-test***")

    # First we collect a list of all tests to run
    files.reverse()
    todo = []
    while len(files) > 0:
        file = files.pop()

        # Check what it is
        if os.path.isfile(file):
            todo.append(file)
        elif os.path.isdir(file):
            # Recurse its children
            try:
                for entry in os.listdir(file):
                    # We either accept directories _or_ files ending in the target extension
                    path = os.path.join(file, entry)
                    if (os.path.isfile(path) and path.endswith(extension)) or os.path.isdir(path):
                        files.append(path)
            except IOError as e:
                perror(f"Failed to read directory '{file}': {e}")
        else:
            perror(f"Entry '{file}' is neither a file or a directory")
    todo.sort(reverse=True)
    pdebug(f"Running {len(todo)} test(s)")
    if len(todo) == 0:
        pinfo("No tests found, nothing to do.")
        return 0

    # Process the files
    event = threading.Event()
    handles = []
    outputs = []
    while len(todo) > 0:
        # If we have space, spawn a new process
        if len(handles) < n_jobs:
            file = todo.pop()

            # Print what file we're doing
            prunning(file, clear=True)
            ptesting([os.path.basename(handle.file) for handle in handles], clear=True, end='\r')

            # Create the test runner
            handle = UnitTest(file, exe, strict, include_dirs, no_test_include, event)
            handle.start()
            handles.append(handle)
        else:
            ptesting([os.path.basename(handle.file) for handle in handles], clear=True, end='\r')

            # Wait for one to complete
            event.clear()
            event.wait()

            # Prune all the finished ones
            rem_handles = []
            for handle in handles:
                if handle.is_alive():
                    rem_handles.append(handle)
                elif len(handle.output) > 0 and any(rep for rep in handle.output if not isinstance(rep, Debug)):
                    outputs.append((handle.file, handle.output))
            handles = rem_handles

            # Try again
            continue

    # Now we just wait until the remaining ones complete
    for handle in handles:
        ptesting([os.path.basename(handle.file) for handle in handles], clear=True, end='\r')
        handle.join()
        if len(handle.output) > 0 and any(rep for rep in handle.output if not isinstance(rep, Debug)):
            outputs.append((handle.file, handle.output))
    ptesting_done(clear=True)

    # Finally, print the results
    for file, output in outputs:
        Report.print_all(file, output, use_colour=None)

    # Done
    return 0 if not ERRORED else 1



# Actual entrypoint
if __name__ == "__main__":
    # Define the arguments
    parser = argparse.ArgumentParser(formatter_class=argparse.ArgumentDefaultsHelpFormatter)

    parser.add_argument("FILE", nargs='+', help = "The eFLINT files to run. If a directory, will recurse into it to run all `.eflint` files (see '--extension').")
    parser.add_argument("-e", "--exec", default="eflint-repl", help="The Haskell implementation binary to call. Given as the start of a shell command, i.e., respects PATH and other shell niceness.")
    parser.add_argument("-i", "--include-dir", default=[], nargs='*', help="Defines an additional include directory for the eFLINT REPL. By default, the directory of the test file in question is included.")
    parser.add_argument("--no-include", action="store_true", help="Does not automatically include directories of the given test files. Only include directories given by '--include-dir' are used.")

    parser.add_argument("--debug", action="store_true", help="If given, increases logging verbosity.")
    parser.add_argument("-s", "--strict", action="store_true", help="If given, turns any warnings into errors.")
    parser.add_argument("-x", "--extension", type=str, default=".eflint", help="If FILE is a directory, then nested files ending in this extension will be assumed to be eFLINT files.")
    parser.add_argument("-j", "--jobs", type=int, default=get_default_jobs(), help="The number of tests to run in parallel.")

    # Parse the arguments
    args = parser.parse_args()
    if args.debug:
        DEBUG = True

    # Run main with that
    exit(main(args.FILE, args.extension, args.exec, args.strict, args.jobs, args.include_dir, args.no_include))

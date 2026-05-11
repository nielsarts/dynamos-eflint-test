"""Terminal colour/style helpers.

All functions degrade gracefully to plain text when stdout is not a tty
(e.g. CI log capture or pipe redirection).
"""
from __future__ import annotations

import sys

_COLOR: bool = sys.stdout.isatty()

_RST  = "\033[0m"
_BOLD = "\033[1m"
_DIM  = "\033[2m"
_RED  = "\033[31m"
_GRN  = "\033[32m"
_YLW  = "\033[33m"
_CYN  = "\033[36m"


def _w(code: str, text: str) -> str:
    return f"{code}{text}{_RST}" if _COLOR else text


def bold(t: str)        -> str: return _w(_BOLD,         t)
def dim(t: str)         -> str: return _w(_DIM,          t)
def green(t: str)       -> str: return _w(_GRN,          t)
def red(t: str)         -> str: return _w(_RED,          t)
def yellow(t: str)      -> str: return _w(_YLW,          t)
def cyan(t: str)        -> str: return _w(_CYN,          t)
def bold_green(t: str)  -> str: return _w(_BOLD + _GRN,  t)
def bold_red(t: str)    -> str: return _w(_BOLD + _RED,  t)
def bold_cyan(t: str)   -> str: return _w(_BOLD + _CYN,  t)
def bold_yellow(t: str) -> str: return _w(_BOLD + _YLW,  t)

"""Rewrites of C that keep its meaning but change what the compiler makes of it: statement and declaration order,
casts, comparison forms, increment styles, `register`. A permuter (decompdecomp's app/permute.py) tries them on near misses;
the caller's judge decides what matches."""

from __future__ import annotations

import random
import re

TYPES_32 = ["int", "unsigned", "unsigned int", "long", "unsigned long", "s32", "u32", "uInt", "uLong"]
CASTS = ["(int)", "(unsigned)", "(s32)", "(u32)", "(uInt)", "(uLong)", "(short)", "(unsigned short)"]
# Typedef names: only offered when the source or its header declares them. zlib's uInt/uLong made 9,970 of 10,000
# rewrites of an N64 function fail to compile, crowding out everything else the pass could have tried.
_TYPEDEFS = {"s32", "u32", "uInt", "uLong"}
_TYPE_WORDS = {"char", "short", "int", "long", "unsigned", "signed", "float", "double", "void", "const", "volatile",
               "struct", "union", "enum", "sizeof", "return"}
# (the type and the name are separate words: with `\s*` between them `D_80102ED4 = 0;` read as type `D_80102ED`
# and name `4`, and _toggle_register made a store to a global into `register D_80102ED4 = 0;`, a new local; 35
# functions of an N64 game kept that as their best C because dropping the store raised the byte score)
_DECL = re.compile(r"^(\s+)(register\s+)?((?:unsigned\s+|signed\s+)?(?!(?:return|goto|case|else|do|sizeof)\b)\w+)"
                   r"(\s+\**\s*|\s*\*+\s*)(\w+)(\s*(?:=[^;]*)?;)\s*$")
_STMT = re.compile(r"^\s+[^\s{}#][^{}]*;\s*$")
# statements that transfer control (or open blocks) are never moved; one-line `if (c) x;` statements may be
_CONTROL = re.compile(r"\b(return|break|continue|goto|case|default)\b|^\s*(else|for|while|do|switch)\b")


def _body_bounds(lines: list[str]) -> tuple[int, int]:
    start = next((i for i, l in enumerate(lines) if "{" in l), 0)
    end = max((i for i, l in enumerate(lines) if l.strip().startswith("}")), default=len(lines) - 1)
    return start + 1, end


def _swap_statements(lines, rng, known=None):
    lo, hi = _body_bounds(lines)
    pairs = [i for i in range(lo, hi - 1) if _STMT.match(lines[i]) and _STMT.match(lines[i + 1])
             and not _CONTROL.search(lines[i] + lines[i + 1]) and not _DECL.match(lines[i])
             and lines[i][:len(lines[i]) - len(lines[i].lstrip())] == lines[i + 1][:len(lines[i + 1]) - len(lines[i + 1].lstrip())]]
    if not pairs:
        return None
    i = rng.choice(pairs)
    lines[i], lines[i + 1] = lines[i + 1], lines[i]
    return lines


def _shuffle_declarations(lines, rng, known=None):
    lo, hi = _body_bounds(lines)
    run = []
    for i in range(lo, hi):
        if _DECL.match(lines[i]) and "=" not in lines[i]:
            run.append(i)
        elif run:
            break
    if len(run) < 2:
        return None
    a, b = rng.sample(run, 2)
    lines[a], lines[b] = lines[b], lines[a]
    return lines


def _declared(name, known):
    return name.strip("()") not in _TYPEDEFS or name.strip("()") in known


def _retype_local(lines, rng, known=frozenset(_TYPEDEFS)):
    lo, hi = _body_bounds(lines)
    cands = [i for i in range(lo, hi) if (m := _DECL.match(lines[i])) and m.group(3) in TYPES_32 and not m.group(4).strip()]
    if not cands:
        return None
    i = rng.choice(cands)
    m = _DECL.match(lines[i])
    types = [t for t in TYPES_32 if t != m.group(3) and _declared(t, known)]
    lines[i] = f"{m.group(1)}{m.group(2) or ''}{rng.choice(types)}{m.group(4)}{m.group(5)}{m.group(6)}"
    return lines


def _toggle_register(lines, rng, known=None):
    lo, hi = _body_bounds(lines)
    cands = [i for i in range(lo, hi) if _DECL.match(lines[i])]
    if not cands:
        return None
    i = rng.choice(cands)
    m = _DECL.match(lines[i])
    reg = "" if m.group(2) else "register "
    lines[i] = f"{m.group(1)}{reg}{m.group(3)}{m.group(4)}{m.group(5)}{m.group(6)}"
    return lines


_REWRITES = [
    (re.compile(r"\b(\w+)\+\+;"), lambda m: f"{m.group(1)} += 1;"),
    (re.compile(r"\b(\w+) \+= 1;"), lambda m: f"++{m.group(1)};"),
    (re.compile(r"\+\+(\w+);"), lambda m: f"{m.group(1)}++;"),
    (re.compile(r"\b(\w+)--;"), lambda m: f"{m.group(1)} -= 1;"),
    (re.compile(r"\b(\w+) -= 1;"), lambda m: f"{m.group(1)}--;"),
    (re.compile(r"\((\w+) < (\w+)\)"), lambda m: f"({m.group(2)} > {m.group(1)})"),
    (re.compile(r"\((\w+) > (\w+)\)"), lambda m: f"({m.group(2)} < {m.group(1)})"),
    (re.compile(r"\((\w+) <= (\w+)\)"), lambda m: f"({m.group(2)} >= {m.group(1)})"),
    (re.compile(r"\((\w+) >= (\w+)\)"), lambda m: f"({m.group(2)} <= {m.group(1)})"),
    (re.compile(r"\(!(\w+)\)"), lambda m: f"({m.group(1)} == 0)"),
    (re.compile(r"\((\w+) == 0\)"), lambda m: f"(!{m.group(1)})"),
    (re.compile(r"\((\w+) != 0\)"), lambda m: f"({m.group(1)})"),
    (re.compile(r"\(\s*(?:unsigned short|unsigned|short|int|s32|u32|uInt|uLong)\s*\)\s*(?=\w)"), lambda m: ""),
]


def _rewrite(lines, rng, known=None):
    lo, hi = _body_bounds(lines)
    options = [(i, rx, fn) for i in range(lo, hi) for rx, fn in _REWRITES if rx.search(lines[i])]
    if not options:
        return None
    i, rx, fn = rng.choice(options)
    matches = list(rx.finditer(lines[i]))
    m = rng.choice(matches)
    lines[i] = lines[i][:m.start()] + fn(m) + lines[i][m.end():]
    return lines


def _add_cast(lines, rng, known=frozenset(_TYPEDEFS)):
    lo, hi = _body_bounds(lines)
    # (pointers are never cast to an integer type here: in `(char *)(D_80109698) + 0xFC` the operand of the pointer
    # cast once became `(unsigned short)D_80109698`, an address cut to 16 bits, kept because it raised the byte score)
    pointers = {m.group(1) for line in lines for m in re.finditer(r"\*\s*(\w+)\s*[;=,)]", line)}
    cands = [(i, m) for i in range(lo, hi) if not _DECL.match(lines[i]) and "=" in lines[i]
             # rvalues only: never cast an assignment target, a call, or the base of a member/array access
             # (nor a type name: `(char *)` became `((unsigned)char *)`)
             for m in re.finditer(r"(?<=[=(,+\-*/&|^ ])(\w+)\b(?!\s*(?:\(|=(?!=)|\+\+|--|\[|\.|->|[-+*/&|^]=|\*+\s*\)))",
                                  lines[i])
             # (no literal: `(unsigned short)0xDA380003` stored 3 where an N64 function stored a display-list command,
             # and the byte score rewarded it; `isdigit` let every hex literal through)
             if not m.group(1)[0].isdigit() and m.group(1) not in pointers
             and m.group(1) not in _TYPE_WORDS
             and not re.search(r"\*\s*\)\s*\(?\s*$", lines[i][:m.start()])]
    if not cands:
        return None
    i, m = rng.choice(cands)
    lines[i] = lines[i][:m.start()] + rng.choice([c for c in CASTS if _declared(c, known)]) + lines[i][m.start():]
    return lines


MUTATIONS = [_swap_statements, _shuffle_declarations, _retype_local, _toggle_register, _rewrite, _rewrite, _add_cast]


def mutate(source: str, rng: random.Random, focus: str = "", header: str | None = None) -> str | None:
    """One rewrite of `source`. Typedef names (s32, uInt, ...) are used only where `source` or `header` declares or
    uses them; without a header, only those the source itself names."""
    lines = source.split("\n")
    known = frozenset(t for t in _TYPEDEFS if re.search(r"\b" + t + r"\b", source + "\n" + (header or "")))
    preferred = {"stack": [_shuffle_declarations, _toggle_register],
                 "register": [_swap_statements, _shuffle_declarations],
                 "call": [_retype_local, _add_cast], "constant": [_rewrite, _add_cast],
                 "control": [_rewrite, _swap_statements]}.get(focus, [])
    for _ in range(6):
        out = rng.choice(MUTATIONS + preferred * 2)(list(lines), rng, known)
        if out is not None and out != lines:
            return "\n".join(out)
    return None

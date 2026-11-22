"""Phase splits a hand-edited source hides from the analysis, and the chain of them as one child.

`phase_lifetime_repairs` splits a local that holds unrelated values in turn (a pointer reloaded at each level of a
nested walk, a cursor set for two loops) into one local per phase, and it proves each split with the function's
liveness. It reads only what m2c writes: one local per declaration, and no macro that names a local. A saved best an
agent edited by hand usually carries both departures:

  - `void *a, *b, *c;` (a list of declarators), which its local patterns do not see, and
  - `#define NF ((found ^ 1) & 1)` (an object-like macro that reads a local), which makes the context check decline the
    whole function (a macro can read a local out of the analysis's sight).

On a 249-instruction KMC (`gcc-2.7.2-kmc -G0 -mips3 -mgp32 -mfp32 -O2`) nested-list walk whose saved best carried
both, the library offered nothing for the split locals (`prove_chain` stopped at 110). Written one declarator per line
and with the macro expanded where it is used (the same program), `split_integer_phase` took it 110 -> 30 -> 0: the
first level's pointer in a local of its own, then the innermost level's. This module does that rewrite first, offers
each proven split alone, and offers the splits applied one after another as one child, so a beam that scores children
one edit deep still sees the whole chain. A candidate rewrite; the exact judge decides. The register effect is a
hypothesis read from `local-alloc.c`/`global.c` (each web becomes a pseudo of its own, with its own priority and live
length); it was measured, not proven.

Nothing is offered by the single-split part when the source needs neither rewrite (`split_integer_phase` already does
that), and the macro is only expanded where its object-like body is one line.
"""
import re

from . import phase_lifetime_repairs
from .integer_repair_support import IDENT, view

FAMILY = 'normalized_phase_split'
CHAIN_FAMILY = 'normalized_phase_chain'
FAMILIES = (FAMILY, CHAIN_FAMILY)
CHAIN_STEPS = 6
LIMIT = 6

_KEYWORDS = {'return', 'else', 'goto', 'case', 'default', 'typedef', 'extern', 'static', 'if', 'while', 'for', 'do',
             'switch', 'break', 'continue', 'sizeof'}
_DECLARATOR = rf'\*{{0,3}}[ \t]*{IDENT}'
_LIST = re.compile(rf'(?m)^([ \t]*)((?:(?:struct|union|unsigned|signed)[ \t]+)?{IDENT})[ \t]+'
                   rf'({_DECLARATOR}(?:[ \t]*,[ \t]*{_DECLARATOR})+)[ \t]*;[ \t]*$')
_DEFINE = re.compile(rf'(?m)^[ \t]*#[ \t]*define[ \t]+({IDENT})[ \t]+([^\n]*?)[ \t]*$')


def _split_lists(source, part):
    """`T *a, *b;` as one declaration per line, inside the function's own top-level declarations."""
    edits = []
    for hit in _LIST.finditer(source, part.opening + 1, part.end):
        if hit[2] in _KEYWORDS or hit[2].startswith('#'):
            continue
        before = source[part.opening + 1:hit.start()].rstrip()
        if before and before[-1] not in ';{}':
            continue
        lines = []
        for declarator in hit[3].split(','):
            stars, name = re.fullmatch(rf'(\*{{0,3}})[ \t]*({IDENT})', declarator.strip()).groups()
            lines.append(f'{hit[1]}{hit[2]} {stars}{name};')
        edits.append((hit.start(), hit.end(), '\n'.join(lines)))
    return edits


def _expand_macros(source, part, locals_):
    """Object-like one-line macros whose body reads a local, written out where the function uses them."""
    edits, removals = [], []
    for hit in _DEFINE.finditer(source):
        name, body = hit[1], hit[2]
        if body.endswith('\\') or '#' in body or not set(re.findall(IDENT, body)) & locals_:
            continue
        elsewhere = source[:hit.start()] + source[hit.end():]
        if re.search(rf'\b{name}\s*\(', elsewhere):
            continue
        uses = [use for use in re.finditer(rf'(?<![\w.>]){name}\b', source)
                if part.opening < use.start() < part.end]
        if not uses or len(re.findall(rf'(?<![\w.>]){name}\b', elsewhere)) != len(uses):
            continue
        wrapped = body if re.fullmatch(r'\((?:[^()]|\([^()]*\))*\)', body) else f'({body})'
        edits += [(use.start(), use.end(), wrapped) for use in uses]
        removals.append((hit.start(), hit.end() + 1 if source[hit.end():hit.end() + 1] == '\n' else hit.end(), ''))
    return edits, removals


def _apply(source, edits):
    for start, end, text in sorted(edits, reverse=True):
        source = source[:start] + text + source[end:]
    return source


def normalize(source, name):
    """The same program with one declarator per line and local-reading object macros expanded (unchanged if neither)."""
    part = view(source, name)
    if not part:
        return source
    declared = _split_lists(source, part)
    after = _apply(source, declared) if declared else source
    part = view(after, name)
    if not part:
        return source
    locals_ = set(re.findall(rf'(?:^|[;{{}}])[ \t]*(?:[A-Za-z_]\w*[ \t]+)+\**[ \t]*({IDENT})[ \t]*;',
                             after[part.opening:part.end], re.M))
    macro_edits, removals = _expand_macros(after, part, locals_)
    return _apply(after, macro_edits + removals) if macro_edits else after


def _chain(text, name, header):
    """The first proposed split, then the first of what that leaves, up to CHAIN_STEPS (each a distinct web)."""
    steps = 0
    for _ in range(CHAIN_STEPS):
        proposals = [t for t in phase_lifetime_repairs.splits(text, name, header) if t != text]
        if not proposals:
            break
        text, steps = proposals[0], steps + 1
    return text if steps >= 2 else None


def variants(source, name, header=''):
    normal = normalize(source, name)
    out = []
    if normal != source:
        out += [(FAMILY, text) for text in phase_lifetime_repairs.splits(normal, name, header) if text != source]
    if chain := _chain(normal, name, header):
        out.append((CHAIN_FAMILY, chain))
    return list(dict.fromkeys(out))[:LIMIT]


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name', 'header')}  # the registry: no caller wiring (registry.py)

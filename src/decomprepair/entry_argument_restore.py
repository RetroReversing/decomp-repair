"""A call argument the target never loads, written back as the caller's own parameter in that register.

m2c names whatever it last saw loaded as a call's argument. When the target never writes `$a0` between the entry and a
`jal`, the callee's first argument is the caller's own first parameter, passed on, however the draft spells it. An
autopilot draft of an actor update (SN gcc 2.8.1, `-G0 -mips3 -O2 -mfp64`, 51 instructions) passed a byte read from
another object, `releaseEntity(temp_a1_2)` under `s32 releaseEntity(u8);`, where the callee's matched C takes the actor
the function was given: `releaseEntity(arg0)` went 365 -> 210. `passthrough_argument` only inserts a missing argument;
it never replaces one.

entry_argument_restore
    The evidence is the target's own assembly (MIPS, `argument_passthrough_to_callees.incoming_sites`): for a callee,
    the argument register K still holds the caller's value on every path to every `jal` of it. Each of the C's calls
    that passes a plain local (not the parameter, nor a copy of it) at position K passes the parameter there instead,
    and a prototype in the source whose parameter at K cannot take it gains the parameter's type (`void *` for a
    pointer). Only a plain name is replaced, so nothing evaluated is dropped; every parameter of the caller must be an
    integer or pointer (position K is then register `$aK`), and the parameter must not be written in the body.
    One child per callee and position. MIPS only. Judged like any child.

    The assembly may still call a renamed function by its address (`jal func_8004904C` for the C's `releaseEntity`), as
    the app's stored target does: when exactly one address name of the target and exactly one called name of the C have
    no counterpart, they are taken as the same function.
"""
import re

from . import m2cfix
from .argument_passthrough_to_callees import _written, incoming_sites
from .csource import _blank
from .integer_repair_support import IDENT, calls, edit, view

FAMILY = 'entry_argument_restore'
FAMILIES = (FAMILY,)
LIMIT = 4
_INTEGER = r'(?:(?:unsigned|signed)\s+)?(?:[su](?:8|16|32)|char|short|int|long|M2C_UNK(?:8|16|32)?)'


def _parameters(part):
    """[(type, name)] of the definition's parameters when every one is an integer or a pointer, else None."""
    head = part.clean[:part.opening].rstrip()
    if not head.endswith(')'):
        return None
    depth, at = 0, len(head)
    while at > 0:
        at -= 1
        depth += (head[at] == ')') - (head[at] == '(')
        if not depth:
            break
    out = []
    for piece in m2cfix._split_top_level(head[at + 1:-1]):
        found = re.fullmatch(rf'\s*(?P<type>[\w\s]+?[\s*]+)(?P<name>{IDENT})\s*', piece)
        if not found or ('*' not in found['type'] and not re.fullmatch(_INTEGER, found['type'].strip())):
            return None
        out.append((found['type'].strip(), found['name']))
    return out


def _aliases(body, parameter):
    """The parameter and every local whose only assignment is a plain copy of it."""
    names = {parameter}
    for found in re.finditer(rf'(?<![\w.>])({IDENT})\s*=\s*{re.escape(parameter)}\s*;', body):
        if len(re.findall(rf'(?<![\w.>]){found[1]}\s*=(?!=)', body)) == 1:
            names.add(found[1])
    return names


def _retyped(source, callee, position, kind):
    """`source` with a prototype of `callee` taking `kind` at `position`, where it declares something else."""
    clean = _blank(source)
    for found in re.finditer(rf'(?m)^[ \t]*(?:extern[ \t]+)?[\w ]+?[ \t*]+{re.escape(callee)}[ \t]*\(([^()]*)\)[ \t]*;',
                             clean):
        pieces = [piece.strip() for piece in source[found.start(1):found.end(1)].split(',')]
        if position >= len(pieces) or pieces == ['']:
            continue
        pointer = '*' in kind
        if ('*' in pieces[position]) == pointer and pointer:
            continue
        wanted = 'void *' if pointer else kind
        if pieces[position] == wanted or pieces[position] == '...':
            continue
        pieces[position] = wanted
        return source[:found.start(1)] + ', '.join(pieces) + source[found.end(1):]
    return source


def _target_sites(body, asm):
    """`incoming_sites` keyed by the C's names, pairing a lone renamed callee with its lone address name."""
    sites = dict(incoming_sites(asm))
    called = {found for found in re.findall(rf'(?<![\w.>])({IDENT})\s*\(', body)
              if found not in ('if', 'while', 'for', 'switch', 'return', 'sizeof') and not found.isupper()}
    unseen = called - set(sites)
    addressed = [callee for callee in set(sites) - called if re.fullmatch(r'func_[0-9A-Fa-f]{8}', callee)]
    if len(unseen) == 1 and len(addressed) == 1:
        sites[unseen.pop()] = sites.pop(addressed[0])
    return sites


def variants(source, name, asm=None, arch=None, header=''):
    """Proposals: the caller's own parameter at each call position the target passes it through untouched."""
    if arch not in (None, 'mips') or not asm:
        return []
    part = view(source, name)
    if not part:
        return []
    parameters = _parameters(part)
    if not parameters:
        return []
    body = part.body
    result = []
    for callee, sites in sorted(_target_sites(body, asm).items()):
        untouched = set.intersection(*sites)
        found = list(calls(part, callee))
        if not found:
            continue
        for position, (kind, parameter) in enumerate(parameters[:4]):
            if position not in untouched or _written(body, parameter):
                continue
            aliases = _aliases(body, parameter)
            changes = []
            for start, end in found:
                arguments = m2cfix._split_top_level(part.clean[start:end])
                if position >= len(arguments):
                    continue
                argument = arguments[position].strip()
                if not re.fullmatch(IDENT, argument) or argument in aliases:
                    continue
                offset = start
                for earlier in arguments[:position]:
                    offset = part.clean.index(',', offset + len(earlier)) + 1
                offset = part.clean.index(argument, offset)
                changes.append((offset, offset + len(argument), parameter))
            if changes:
                result.append((FAMILY, _retyped(edit(source, changes), callee, position, kind)))
    return result[:LIMIT]


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name', 'asm', 'arch', 'header'),
          'archs': ('mips',)}

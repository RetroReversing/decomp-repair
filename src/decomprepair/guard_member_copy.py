"""A pointer loaded, then tested through its local, written as the test of the member and the copy inside the guard.

m2c writes a member that is null-tested and then used through one register as a load above the test:

    child = obj->child;                       obj->timer = -1;
    obj->timer = -1;                  ->      if (obj->child != NULL) {
    if (child != NULL) {                          child = obj->child;

Where the target loads into a scratch register, branches on it and copies it into the register the block uses
(`lw $v0,0x48($s0); beqz $v0,end; sh; addu $a1,$v0,$zero`, or the copy in a later branch's delay slot), the source
tested the member and assigned the local inside the guard: cse then turns the second read into the `move`. Written with
the load above, the local is the loaded register itself and the `move` is missing. An N64 effect update
(`sn-n64-281 -G0 -mips3 -O2`) had two such sites; from its saved best with the other repairs done, restoring one left
170 and 430 points, both gave 0.

Two sites whose locals share a pointer type and take turns (one's guard in each arm of an `if`) are also offered
written as one local: the restored copies alone were no gain there (380 -> 380), and only the one shared variable gave
the target's `$a1` in both arms (380 -> 0).

A proposal takes `V = LOAD;` (a member, `M2C_FIELD` or dereference, no call), then only simple assignments that
cannot change what LOAD reads (a local LOAD does not name, or another member offset of the same base), then
`if (V)`, `if (V != 0)` or `if (V != NULL)` with a braced block. V must not be read elsewhere before it is assigned
again, so the guard's false path loses nothing. One child with every site, then each site alone. The exact judge
decides each.
"""
import re

from .c_scan import close
from .csource import _blank, find
from .integer_repair_support import edit

FAMILY = 'guard_member_copy'
FAMILIES = (FAMILY,)
LIMIT = 8

_IDENT = r'[A-Za-z_]\w*'
_ASSIGN = re.compile(rf'(?m)^(?P<indent>[ \t]*)(?P<name>{_IDENT})[ \t]*=(?!=)[ \t]*(?P<load>[^;\n{{}}]+);[ \t]*\n')
_LINE = re.compile(r'[ \t]*(?P<lhs>[^;\n{}=]+?)[ \t]*(?:[-+|&^]|<<|>>)?=(?!=)(?P<rhs>[^;\n{}]+);[ \t]*\n')
_CALL = re.compile(rf'\b(?!M2C_FIELD\b|sizeof\b)({_IDENT})\s*\(')
_FIELD = re.compile(rf'^M2C_FIELD\(\s*(?P<base>{_IDENT})\s*,[^,()]+,\s*(?P<offset>-?(?:0[xX][0-9A-Fa-f]+|\d+))\s*\)$')
_ARROW = re.compile(rf'^(?P<base>{_IDENT})\s*->\s*(?P<offset>{_IDENT})$')


def _pure(expression):
    """No call, assignment or increment; a cast's `(T *)` is not a call."""
    return not (_CALL.search(expression) or '++' in expression or '--' in expression
                or re.search(r'(?<![=!<>])=(?!=)', expression))


def _member(text):
    return _FIELD.match(text) or _ARROW.match(text)


def _harmless(lhs, load):
    """Whether storing to `lhs` leaves what `load` reads: a local it does not name, or another member of its base."""
    if re.fullmatch(_IDENT, lhs):
        return not re.search(rf'\b{lhs}\b', load)
    store, read = _member(lhs), _member(load)
    if not store or not read or store['base'] != read['base']:
        return False
    first, second = store['offset'], read['offset']
    if first[:1].isalpha() or second[:1].isalpha():
        return first[:1].isalpha() and second[:1].isalpha() and first != second
    return abs(int(first, 0) - int(second, 0)) >= 4


def _unused_elsewhere(body, name, kept):
    """Whether every mention of `name` outside the `kept` span is its declaration or follows a fresh assignment."""
    after = body[kept[1]:]
    later = re.search(rf'\b{name}\b', after)
    if later is None:
        return True
    return bool(re.match(r'\s*=(?!=)', after[later.end():]))


def _sites(source, clean, lo, hi):
    sites = []
    body = clean[:hi]
    for found in _ASSIGN.finditer(body, lo):
        name = found['name']
        start, end = found.start('load'), found.end('load')
        load = clean[start:end].strip()
        if not (_member(load) or load.startswith('*') or '->' in load) or not _pure(load) or re.search(
                rf'\b{name}\b', load):
            continue
        at = found.end()
        while True:
            line = _LINE.match(body, at)
            if not line:
                break
            lhs, rhs = line['lhs'].strip(), line['rhs']
            if (re.search(rf'\b{name}\b', line[0]) or not _pure(rhs) or _CALL.search(lhs)
                    or not _harmless(lhs, load)):
                break
            at = line.end()
        guard = re.compile(rf'[ \t]*if[ \t]*\([ \t]*(?P<v>{name})(?:[ \t]*!=[ \t]*(?:0|NULL))?[ \t]*\)[ \t]*\{{[ \t]*\n'
                           ).match(body, at)
        if not guard:
            continue
        opening = guard.start() + guard[0].rindex('{')
        closing = close(clean, opening, '{', '}')
        if closing < 0 or closing >= hi or re.match(r'\s*else\b', clean[closing + 1:hi]):
            continue
        if re.search(rf'(?<!&)&(?!&)\s*{name}\b', clean[lo:hi]) or not _unused_elsewhere(clean[:hi], name, (found.start(), closing + 1)):
            continue
        text = source[start:end].strip()
        inner = re.match(r'[ \t]*', source[guard.end():]).group()
        if not inner:
            inner = found['indent'] + '    '
        sites.append([(found.start(), found.end(), ''),
                      (guard.start('v'), guard.end('v'), text),
                      (guard.end(), guard.end(), f'{inner}{name} = {text};\n')])
    return sites


def _one_local(source, name):
    """Each pair of guard-copy locals that take turns, written as the first one."""
    span = find(source, name)
    clean = _blank(source)
    body = clean[span[0]:span[1]]
    locals_ = [found['name'] for found in re.finditer(
        rf'(?m)^[ \t]*if[ \t]*\(.*\)[ \t]*\{{[ \t]*\n[ \t]*(?P<name>{_IDENT})[ \t]*=', body)]
    for first, second in zip(locals_, locals_[1:]):
        declared = {}
        for local in (first, second):
            found = re.search(rf'(?m)^[ \t]*(?P<type>{_IDENT}[ \t]*\*)[ \t]*{local}[ \t]*;[ \t]*\n', body)
            if found:
                declared[local] = found
        if first == second or len(declared) != 2:
            continue
        if re.sub(r'\s', '', declared[first]['type']) != re.sub(r'\s', '', declared[second]['type']):
            continue
        uses = [[use.start() for use in re.finditer(rf'(?<![\w.>]){local}\b', body)
                 if not declared[local].start() <= use.start() < declared[local].end()] for local in (first, second)]
        if not all(uses) or max(uses[0]) > min(uses[1]):
            continue
        gone = declared[second]
        edits = [(span[0] + gone.start(), span[0] + gone.end(), '')]
        edits += [(span[0] + at, span[0] + at + len(second), first) for at in uses[1]]
        yield edit(source, edits)


def variants(source, name):
    span = find(source, name)
    if not span or 'if' not in source:
        return []
    clean = _blank(source)
    sites = _sites(source, clean, span[0], span[1])
    picks = ([sites] if len(sites) > 1 else []) + [[site] for site in sites]
    children = [edit(source, [change for site in pick for change in site]) for pick in picks[:LIMIT]]
    if len(sites) > 1:
        children[1:1] = list(_one_local(children[0], name))[:2]
    return [(FAMILY, child) for child in children]


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name')}

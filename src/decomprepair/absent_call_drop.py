"""A call the target never makes, written out of the candidate.

A draft adapted from another game's matching C, or from a close relative of the function, keeps calls that this build of
the function does not have (a controller pak directory count that ends by asking for the pak's status in one version of
the SDK and by returning 0 in another). No reshuffling of the body removes a `jal`, so the search stops at the extra
call and the register differences it causes: 500 on a 62-instruction function, 95 with the call written as
`return 0;`, and 0 after one more family (`goto_backward_loop`). Hand work on one function, KMC GCC 2.7.2.

`variants` reads the function's own text and the target's assembly (MIPS `jal`). An *absent* callee is a function the
source declares a prototype for (or an address name, `func_80001234`) that the assembly never mentions at all, and that
`renamed_callee_refresh` would not pair with an unclaimed target (that one is a rename, not an extra call). For each:

* a call whose result is what the function goes on to return, with nothing else left to run: `return 0;`;
* `return f(...);`: `return 0;`;
* `v = f(...);`: `v = 0;`;
* a bare `f(...);`: removed;
* a call inside a larger expression: `0`.

A call whose arguments have effects of their own (an assignment, `++`, a call the target does make) is left alone. The
judge decides: a callee the compiler inlined is absent from the target too, and its removal scores worse."""
import re

from .integer_repair_support import IDENT, view
from .pattern_repairs import close
from .renamed_callee_refresh import _defined, _pairs

FAMILY = 'absent_call_drop'
FAMILIES = (FAMILY,)
_LIMIT = 4  # callees tried on one source
# gcc and the SDK headers write these inline, so a target without the `jal` still performs them
_BUILTINS = {'abs', 'labs', 'fabs', 'fabsf', 'sqrt', 'sqrtf', 'memcpy', 'memset', 'strlen', 'strcpy', 'strcmp', 'alloca'}
_NOT_CALLS = {'if', 'while', 'for', 'switch', 'return', 'sizeof', 'else', 'do', 'case', 'defined', 'typeof', 'void',
              'char', 'short', 'int', 'long', 'float', 'double', 'signed', 'unsigned', '__attribute__'}
_ADDRESS_NAME = re.compile(r'func_[0-9A-Fa-f]{8}$')


def _declared(context, name):
    """Whether `context` has a prototype of the function `name` (not a pointer variable or a macro of that name)."""
    if re.search(rf'(?m)^[ \t]*#[ \t]*define[ \t]+{re.escape(name)}\b', context):
        return False
    return bool(re.search(rf'(?m)^[ \t]*(?:{IDENT}[ \t*]+)+{re.escape(name)}[ \t]*\([^;{{}}]*\)[ \t]*;', context))


def _absent(source, body, asm, name, header):
    words = set(re.findall(r'[A-Za-z_]\w*', asm))
    defined = _defined(source) | {name}
    renamed = {old for old, _ in _pairs(source, body, asm, name)}
    context = source + '\n' + header
    found = []
    for hit in re.finditer(rf'(?<![\w.>])({IDENT})[ \t]*\(', body):
        callee = hit[1]
        if (callee in found or callee in _NOT_CALLS or callee in _BUILTINS or callee in words or callee in defined
                or callee in renamed or callee.startswith('__builtin')):
            continue
        if re.search(rf'(?m)^[ \t]*#[ \t]*define[ \t]+{re.escape(callee)}\b', context):
            continue
        if _ADDRESS_NAME.match(callee) or _declared(context, callee):
            found.append(callee)
    return found[:_LIMIT]


def _sites(part, callee, words):
    """[(start of the name, end past its closing parenthesis)] of the calls that can be removed."""
    sites = []
    for hit in re.finditer(rf'(?<![\w.>]){re.escape(callee)}[ \t]*\(', part.clean[part.opening:part.end]):
        start = part.opening + hit.start()
        paren = part.opening + hit.end() - 1
        end = close(part.clean, paren)
        if end is None or end <= paren:
            return []
        end = end if part.clean[end - 1] == ')' else end + 1
        inside = part.clean[paren + 1:end - 1]
        if re.search(r'\+\+|--|(?<![=!<>])=(?!=)|<<=|>>=', inside):
            return []
        if any(called in words for called in re.findall(rf'({IDENT})[ \t]*\(', inside)):
            return []
        sites.append((start, end))
    return sites


def _loop_or_switch(clean, brace):
    """Whether the closing brace at `brace` ends a loop or a switch (leaving it does not just go on downwards)."""
    depth = 0
    for at in range(brace, -1, -1):
        depth += (clean[at] == '}') - (clean[at] == '{')
        if depth == 0:
            before = clean[:at].rstrip()
            if re.search(r'\bdo$', before):
                return True
            if not before.endswith(')'):
                return False
            level = 0
            for back in range(len(before) - 1, -1, -1):
                level += (before[back] == ')') - (before[back] == '(')
                if level == 0:
                    return bool(re.search(r'\b(?:for|while|switch)\s*$', before[:back]))
            return False
    return False


def _returns_next(part, after, result):
    """Whether nothing runs after offset `after` but the closing braces of branches and `return result;`."""
    at = after
    while True:
        while at < part.end and part.clean[at].isspace():
            at += 1
        if at >= part.end or part.clean[at] != '}':
            break
        if _loop_or_switch(part.clean, at):
            return False
        at += 1
    return bool(re.compile(rf'return\s+{re.escape(result)}\s*;\s*}}').match(part.clean, at))


def _edit(part, start, end, returns):
    """(from, to, text) for one call site; `returns` picks the `return 0;` form of a tail call over `v = 0;`."""
    clean = part.clean
    before = clean[part.opening:start]
    head = max(before.rfind(';'), before.rfind('{'), before.rfind('}'), before.rfind(':'))
    lead = before[head + 1:]
    statement = part.opening + head + 1 + (len(lead) - len(lead.lstrip()))
    lead = lead.lstrip()
    tail = re.match(r'\s*;', clean[end:])
    if tail:
        stop = end + tail.end()
        if not lead:
            return statement, stop, ';'
        if re.fullmatch(r'return\s*(?:\(\s*[\w\s*]+\)\s*)?', lead):
            return statement, stop, 'return 0;'
        assigned = re.fullmatch(rf'({IDENT})\s*=\s*(?:\(\s*[\w\s*]+\)\s*)?', lead)
        if assigned and returns and _returns_next(part, stop, assigned[1]):
            return statement, stop, 'return 0;'
    return start, end, '0'


def variants(source, name, asm='', header=''):
    part = view(source, name)
    if not part or not asm or not re.search(r'\bjal\b', asm):
        return []
    words = set(re.findall(r'[A-Za-z_]\w*', asm))
    found = _absent(source, part.clean[part.opening:part.end], asm, name, header)
    groups = [sites for sites in (_sites(part, callee, words) for callee in found) if sites]
    if len(groups) > 1:
        groups.append(sorted(site for sites in groups for site in sites))
    out, seen = [], {source}
    for sites in groups:
        for returns in (True, False):
            text = source
            edits = [_edit(part, start, end, returns) for start, end in sites]
            for start, end, new in reversed(edits):
                text = text[:start] + new + text[end:]
            if text not in seen:
                seen.add(text)
                out.append((FAMILY, text))
    return out


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name', 'asm', 'header'), 'archs': ('mips',),
          'order': 11}

"""An assignment written above an early-return guard, moved below it.

    base = table;                          if (index >= count) {
    if (index >= count) {          ->          return 0;
        return 0;                          }
    }                                      base = table;
    return base[index * 24 + 12];          return base[index * 24 + 12];

A search (or the symbol-address family's `__base_SYM = SYM;`) and m2c both leave a local set at the head of the
function although the path that returns early never reads it. SN64 GCC 2.8.1 then starts the address before the
compare and leaves the branch's delay slot to another instruction; below the guard the `lui` fills that slot, as the
target has it (a 15-instruction table getter, 60 -> 0). `assignment_guard_sink` is the other shape: a guard that
`continue`s and ends its block.

The child is equivalent to its parent: the target is a plain local or parameter whose address is never taken, neither
the condition nor the guard's body names it, the condition has no call or assignment (so the value read below is the
value read above), and the guard's body ends in a `return` with no other way out. A run of such assignments moves as
one child, and a row of guards is crossed one at a time or all at once.
"""
import re

from .integer_repair_support import IDENT, _address_taken, edit, view
from .pattern_repairs import close

FAMILY = 'exit_guard_assignment_sink'
FAMILIES = (FAMILY,)
LIMIT = 12
_ASSIGN = re.compile(rf'(?m)^[ \t]*(?P<var>{IDENT})[ \t]*=(?!=)(?P<rhs>[^;{{}}\n]+);[ \t]*\n')
_EFFECT = re.compile(r'(?<![=!<>])=(?!=)|<<=|>>=|\+\+|--')
_CALL = re.compile(rf'(?<![\w.>])(?!(?:if|sizeof)\b){IDENT}\s*\(|\)\s*\(\s*(?![\s*]*\))[^()]*,|\]\s*\(')
_CAST = re.compile(r'\(\s*(?:(?:const|struct|union|unsigned|signed)\s+)*[A-Za-z_]\w*[\s*]*\)')
_LEAVES = re.compile(r'\b(?:break|continue|goto|case|default|volatile)\b|(?m:^\s*\w+\s*:(?!:))')


def _quiet(text):
    """No call, assignment or volatile access in an expression (casts are not calls)."""
    plain = _CAST.sub(' ', text)
    return not (_EFFECT.search(plain) or _CALL.search(plain) or re.search(r'\)\s*\(|\bvolatile\b', plain))


def _local(part, name):
    """Whether `name` is a parameter or a plain (not static, extern or volatile) local whose address stays put."""
    head = part.clean[:part.opening].rstrip()
    parameters = head[head.rfind('(') + 1:-1] if head.endswith(')') else ''
    declared = re.search(rf'(?m)(?:^|[;{{])[ \t]*(?!(?:return|else|goto)\b)(?P<type>(?:{IDENT}[ \t]+|{IDENT}[ \t]*\*+[ \t]*)+)'
                         rf'(?:{IDENT}[ \t]*,[ \t]*\**[ \t]*)*{re.escape(name)}[ \t]*[;,=]', part.body)
    if declared:
        if re.search(r'\b(?:static|extern|volatile)\b', declared['type']):
            return False
    elif not re.search(rf'[\w*]\s*[\s*]{re.escape(name)}\s*(?:,|$)', parameters) or 'volatile' in parameters:
        return False
    return not _address_taken(part.body, name)


def _guard(clean, at, end):
    """(condition, body, stop) of an `if` at `at` that has no `else` and always returns when taken, or None."""
    head = re.compile(r'\s*if\s*\(').match(clean, at, end)
    if not head:
        return None
    condition_end = close(clean, head.end() - 1)
    if not condition_end:
        return None
    braced = re.compile(r'\s*\{').match(clean, condition_end, end)
    if braced:
        stop = close(clean, braced.end() - 1, '{', '}')
        if not stop:
            return None
        body = clean[braced.end():stop - 1]
        if not re.search(r'(?:^|[;}])\s*return\b[^;{}]*;\s*$', body):
            return None
    else:
        single = re.compile(r'\s*return\b[^;{}]*;').match(clean, condition_end, end)
        if not single:
            return None
        stop, body = single.end(), single[0]
    if re.match(r'\s*else\b', clean[stop:stop + 40]) or _LEAVES.search(body):
        return None
    return clean[head.end() - 1:condition_end], body, stop


def variants(source, name):
    part = view(source, name)
    if not part:
        return []
    clean = part.clean
    hits = [hit for hit in _ASSIGN.finditer(clean, part.opening + 1, part.end)
            if clean[:hit.start()].rstrip()[-1:] in {';', '{', '}'}]
    result = []
    for index, last in enumerate(hits):
        guards, at = [], last.end()
        while (found := _guard(clean, at, part.end)) is not None:
            guards.append(found)
            at = found[2]
        if not guards:
            continue
        run = [last]
        for earlier in reversed(hits[:index]):
            if clean[earlier.end():run[0].start()].strip():
                break
            run.insert(0, earlier)
        for moved in ([last], run) if len(run) > 1 else ([last],):
            if not all(_quiet(hit['rhs']) and _local(part, hit['var']) for hit in moved):
                continue
            names = '|'.join(re.escape(hit['var']) for hit in moved)
            crossed = 0
            for condition, body, _ in guards:
                if not _quiet(condition) or re.search(rf'(?<![\w.>])(?:{names})\b', condition + body):
                    break
                crossed += 1
            for count in dict.fromkeys((crossed, 1)) if crossed else ():
                stop = guards[count - 1][2]
                if clean[stop:stop + 1] == '\n':
                    stop += 1
                    lines = ''.join(source[hit.start():hit.end()] for hit in moved)
                else:
                    lines = '\n' + ''.join(source[hit.start():hit.end()] for hit in moved)
                result.append((FAMILY, edit(source, [(moved[0].start(), moved[-1].end(), ''), (stop, stop, lines)])))
    return list(dict.fromkeys(result))[:LIMIT]


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name'), 'order': 96}  # the registry

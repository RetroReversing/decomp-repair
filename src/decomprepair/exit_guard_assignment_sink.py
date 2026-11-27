"""An assignment written above an early-return guard, moved below it.

    base = table;                          if (index >= count) {
    if (index >= count) {          ->          return 0;
        return 0;                          }
    }                                      base = table;
    return base[index * 24 + 12];          return base[index * 24 + 12];

`char *base = table;` written in the declaration is split: the declaration stays and `base = table;` goes below the
guard (only declarations may lie between the two). No other family splits an address initialiser, so the table getter
stayed at 60 written that way.

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
_DECLARE = re.compile(rf'(?m)^(?P<indent>[ \t]*)(?!(?:return|else|goto)\b)(?P<type>(?:{IDENT}[ \t]+|{IDENT}[ \t]*\*+[ \t]*)+)'
                      rf'(?P<var>{IDENT})[ \t]*=(?!=)(?P<rhs>[^;{{}}\n,]+);[ \t]*\n')
_DECLARATION = re.compile(rf'\s*(?!(?:return|else|goto)\b)(?:{IDENT}[ \t]+|{IDENT}[ \t]*\*+[ \t]*)+{IDENT}\s*(?:\[[^\]]*\]\s*)?'
                          rf'(?:=(?P<rhs>[^;{{}},]+))?;')
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


def _guards(clean, at, end):
    """The returning guards in a row at `at`."""
    found = []
    while (guard := _guard(clean, at, end)) is not None:
        found.append(guard)
        at = guard[2]
    return found


def _crossable(guards, names):
    """How many leading guards an assignment of `names` can move below."""
    crossed = 0
    for condition, body, _ in guards:
        if not _quiet(condition) or re.search(rf'(?<![\w.>])(?:{names})\b', condition + body):
            break
        crossed += 1
    return crossed


def _below(source, clean, stop, lines, removals):
    """`source` with `removals` made and `lines` put on their own lines after the guard ending at `stop`."""
    if clean[stop:stop + 1] == '\n':
        stop += 1
    else:
        lines = '\n' + lines
    return edit(source, [*removals, (stop, stop, lines)])


def _initialisers(source, part):
    """Children that split `T x = e;` and put `x = e;` below the returning guards after the declarations."""
    clean, result = part.clean, []
    for hit in _DECLARE.finditer(clean, part.opening + 1, part.end):
        kind, var = hit['type'], hit['var']
        if clean[:hit.start()].rstrip()[-1:] not in {';', '{'} or re.search(r'\*[\s*]*const\b', kind):
            continue
        if re.search(r'\bconst\b', kind) and '*' not in kind:
            continue
        if not _quiet(hit['rhs']) or not _local(part, var):
            continue
        at = hit.end()
        while (later := _DECLARATION.match(clean, at, part.end)) is not None:
            if re.search(rf'(?<![\w.>]){var}\b', later[0]) or not _quiet(later['rhs'] or ''):
                break
            at = later.end()
        guards = _guards(clean, at, part.end)
        crossed = _crossable(guards, var)
        for count in dict.fromkeys((crossed, 1)) if crossed else ():
            line = f"{hit['indent']}{var} ={source[hit.start('rhs'):hit.end('rhs')]};\n"
            declaration = f"{hit['indent']}{source[hit.start('type'):hit.end('var')]};\n"
            result.append((FAMILY, _below(source, clean, guards[count - 1][2], line,
                                          [(hit.start(), hit.end(), declaration)])))
    return result


def variants(source, name):
    part = view(source, name)
    if not part:
        return []
    clean = part.clean
    hits = [hit for hit in _ASSIGN.finditer(clean, part.opening + 1, part.end)
            if clean[:hit.start()].rstrip()[-1:] in {';', '{', '}'}]
    result = []
    for index, last in enumerate(hits):
        guards = _guards(clean, last.end(), part.end)
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
            crossed = _crossable(guards, '|'.join(re.escape(hit['var']) for hit in moved))
            for count in dict.fromkeys((crossed, 1)) if crossed else ():
                lines = ''.join(source[hit.start():hit.end()] for hit in moved)
                result.append((FAMILY, _below(source, clean, guards[count - 1][2], lines,
                                              [(moved[0].start(), moved[-1].end(), '')])))
    result += _initialisers(source, part)
    return list(dict.fromkeys(result))[:LIMIT]


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name'), 'order': 96}  # the registry

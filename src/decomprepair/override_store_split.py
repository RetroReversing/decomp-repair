"""A local set to a constant, overwritten under a test, and used once, written as an `if`/`else` with the use in each arm.

m2c reads a conditional constant as a variable set first and overwritten under the test (`var_v0 = 4; if (c) { var_v0 =
-1; }`), then stored or returned once, and writes the other form (`if (c) { v = -1; } else { v = 4; }`) the same way:

    var_v0 = 4;                                       if (M2C_FIELD(arg0, s32 *, 0x34) < 0) {
    if (M2C_FIELD(arg0, s32 *, 0x34) < 0) {               M2C_FIELD(arg0, s32 *, 0x68) = -1;
        var_v0 = -1;                         ->       } else {
    }                                                     M2C_FIELD(arg0, s32 *, 0x68) = 4;
    M2C_FIELD(arg0, s32 *, 0x68) = var_v0;            }

A 70-instruction N64 function (`-G0 -mips3`, an old GCC) was 15 away with three register rows: the local lived in `$v1`
where the target has `$v0`. With the store written in each arm the variable is gone, there are two stores and no join
pseudo, and the registers were the target's: 15 -> 0. (Hypothesis from the match, not confirmed in the compiler's
source: the pseudo set twice and read at the join is one more quantity for the local allocator to rank against the
block's other temporaries; with the use in each arm no such quantity exists.) The ternary spelling and a copy of the
test's load into a temporary, the other tails tried, scored 1005 and 220 there.

Child, for a local `V` that nothing else in the function names, set by `V = K1;` straight before `if (C) { ... V = K2; }`
(no else), or set last in both arms of `if (C) { ... V = K2; } else { ... V = K1; }`, then read once by the next simple
statement (`LHS = V;`, `return V;`, a call with `V` as an argument): `if (C) { ... USE[K2] } else { USE[K1] }` and the
same with the test negated and the arms exchanged (the arms' order is a layout the target decides). `K` and `C` are
literals, names and plain reads with no call, assignment, `++` or `--`, so evaluating them after the test changes
nothing. The variable's declaration goes with it when it stands alone. The candidate is never a verdict: the judge
decides.
"""
import re

from .integer_repair_support import IDENT, edit, view
from .pattern_repairs import close, negate

FAMILY = 'override_store_split'
FAMILIES = (FAMILY,)
LIMIT = 6
_IF = re.compile(r'\bif\s*\(')
_ELSE = re.compile(r'\s*else\b')
_KEYWORD = re.compile(r'\s*(?:if|else|while|for|do|switch|case|default|goto|break|continue)\b')
_ASSIGN = re.compile(r'(?:\+\+|--)|(?<![=!<>])=(?!=)|[-+*/%&|^]=|<<=|>>=')
_CALLS = {'M2C_FIELD', 'M2C_BITWISE', 'sizeof'}
_TYPES = r'(?:const\s+|volatile\s+|unsigned\s+|signed\s+|struct\s+)*(?!(?:return|goto|else|case)\b)[A-Za-z_]\w*'


def _pure(text):
    """No call (other than the m2c field macros), assignment, `++` or `--`: evaluating it later or earlier is the same."""
    text = text.strip()
    if not text or len(text) > 80 or _ASSIGN.search(text) or re.search(r'[{};?]', text):
        return False
    return all(name in _CALLS for name in re.findall(rf'({IDENT})\s*\(', text))


def _negated(cond):
    cond = cond.strip()
    flipped = negate(cond)
    if flipped:
        return flipped
    if re.fullmatch(rf'!\s*\(?{IDENT}\)?', cond):
        return cond.lstrip('!').strip().strip('()')
    return f'!({cond})' if re.fullmatch(rf'{IDENT}|\({IDENT}\)', cond) else None


def _statement_end(clean, at):
    """The position past the `;` that ends the simple statement starting at `at`, or None for a block or label."""
    depth = 0
    for pos in range(at, len(clean)):
        ch = clean[pos]
        if ch in '([':
            depth += 1
        elif ch in ')]':
            depth -= 1
        elif depth == 0 and ch in '{}':
            return None
        elif depth == 0 and ch == ';':
            return pos + 1
    return None


def _arm(clean, at):
    """(start, end, inner_start, inner_end) of the arm after `at`: a braced block or one simple statement."""
    start = at + len(clean[at:]) - len(clean[at:].lstrip())
    if clean[start:start + 1] == '{':
        end = close(clean, start, '{', '}')
        return (start, end, start + 1, end - 1) if end else None
    end = _statement_end(clean, start)
    return (start, end, start, end) if end and not _KEYWORD.match(clean, start) else None


def _last_set(source, clean, arm, var):
    """(prefix text, value) of an arm whose last statement is `V = K;` and whose earlier text never names `V`."""
    lo, hi = arm[2], arm[3]
    hit = re.search(rf'\b{re.escape(var)}\s*=(?!=)\s*(?P<k>[^;{{}}]+);\s*\Z', clean[lo:hi])
    if not hit or not _pure(hit['k']):
        return None
    if re.search(rf'\b{re.escape(var)}\b', clean[lo:lo + hit.start()]):
        return None
    return source[lo:lo + hit.start()], hit['k'].strip()


_WIDE = re.compile(r'(?:const\s+|volatile\s+)*(?:s32|u32|int|long|unsigned(?:\s+int|\s+long)?|signed(?:\s+int)?|M2C_UNK|M2C_UNK32|'
                  r'size_t|[A-Za-z_]\w*\s*\*)\s*\**\s*')
_RANGE = {'s8': (-128, 127), 'char': (-128, 127), 'u8': (0, 255), 's16': (-32768, 32767), 'short': (-32768, 32767),
          'u16': (0, 65535)}


def _holds(kind, values):
    """Whether the local's type keeps each value as written: a 32-bit integer or pointer always, a narrower one only
    for literals inside its range (`u8 v = -1` is 255, and the use of the literal itself would read -1)."""
    kind = (kind or '').strip()
    if kind and _WIDE.fullmatch(kind + ' '):
        return True
    bounds = _RANGE.get(kind)
    if not bounds:
        return False
    try:
        return all(bounds[0] <= int(value, 0) <= bounds[1] for value in values)
    except ValueError:
        return False


def _atomic(value):
    return bool(re.fullmatch(rf'{IDENT}|(?:0[xX][0-9a-fA-F]+|\d+\.?\d*[fFuUlL]*)', value))


def _use(clean, at, var):
    """(end, template) for the simple statement at `at` that names `var` once: text before it, after it, and whether
    the value may stand bare (`LHS = V;` and `return V;`)."""
    end = _statement_end(clean, at)
    if not end or _KEYWORD.match(clean, at) or re.match(rf'{IDENT}\s*:(?!:)', clean[at:end]):
        return None
    text = clean[at:end]
    names = list(re.finditer(rf'\b{re.escape(var)}\b', text))
    if len(names) != 1:
        return None
    mark = names[0]
    direct = (re.fullmatch(rf'return\s+{re.escape(var)}\s*;', text) or
              re.fullmatch(rf'[^;=]*?[^;=<>!+\-*/%&|^]=\s*{re.escape(var)}\s*;', text))
    return end, (at, mark.start() + at, mark.end() + at, bool(direct))


def variants(source, name):
    part = view(source, name)
    if not part:
        return []
    clean = part.clean
    body = clean[part.opening:part.end]
    out = []
    for hit in _IF.finditer(clean, part.opening + 1, part.end):
        shut = close(clean, hit.end() - 1)
        cond = clean[hit.end():shut - 1].strip() if shut else ''
        then = _arm(clean, shut) if shut else None
        if not then or not _pure(cond):
            continue
        orelse = _ELSE.match(clean, then[1])
        start = hit.start()
        if orelse:
            other = _arm(clean, orelse.end())
            last = re.search(rf'\b({IDENT})\s*=(?!=)\s*[^;{{}}]+;\s*\Z', clean[then[2]:then[3]])
            if not other or not last:
                continue
            var = last[1]
            arms = (_last_set(source, clean, then, var), _last_set(source, clean, other, var))
            stop, used = other[1], clean[then[2]:then[3]] + clean[other[2]:other[3]]
        else:
            before = clean[:hit.start()].rstrip()
            prev = re.search(rf'(?P<d>(?:{_TYPES}[\s*]+)?)(?P<v>{IDENT})\s*=(?!=)\s*(?P<k>[^;{{}}]+);\Z', before)
            if not prev or before[:prev.start()].rstrip()[-1:] not in (';', '{', '}') or not _pure(prev['k']):
                continue
            var = prev['v']
            arms = (_last_set(source, clean, then, var), ('', prev['k'].strip()))
            start, stop, used = prev.start(), then[1], clean[prev.start():prev.end()] + clean[then[2]:then[3]]
        if not all(arms) or re.search(rf'\b{re.escape(var)}\b', cond):
            continue
        at = stop + len(clean[stop:]) - len(clean[stop:].lstrip())
        after = _use(clean, at, var)
        if not after:
            continue
        end, template = after
        # the variable is named nowhere else but in its declaration (a lone one goes with it)
        mine = re.compile(rf'\b{re.escape(var)}\b')
        extra = len(mine.findall(body)) - len(mine.findall(used + clean[at:end]))
        edits = [(start, end)]
        kind = None if orelse else prev['d']
        if extra == 1:
            lone = list(re.finditer(rf'(?:^|(?<=[;{{}}]))\s*(?P<t>{_TYPES}[\s*]+){re.escape(var)}\s*;', body))
            if len(lone) == 1 and part.opening + lone[0].end() <= start:
                edits.append((part.opening + lone[0].start(), part.opening + lone[0].end()))
                kind = lone[0]['t']
            elif not re.search(rf'(?:^|[;{{}}])\s*{_TYPES}[\s*]+[^;(){{}}=]*\b{re.escape(var)}\b[^;(){{}}=]*;', body):
                continue
        elif extra != 0:
            continue
        if not _holds(kind, [value for _, value in arms]):
            continue
        indent = re.search(r'[ \t]*\Z', source[:start])[0]
        for flip in (False, True):
            test, order = cond, arms
            if flip:
                test, order = _negated(cond), arms[::-1]
                if not test:
                    continue
            blocks = []
            for prefix, value in order:
                use = source[template[0]:template[1]] + (value if template[3] or _atomic(value) else f'({value})') \
                    + source[template[2]:end]
                blocks.append('{' + prefix.rstrip() + '\n' + indent + '    ' + use + '\n' + indent + '}')
            text = f'if ({test}) {blocks[0]} else {blocks[1]}'
            out.append((FAMILY, edit(source, [(edits[0][0], edits[0][1], text)] + [(a, b, '') for a, b in edits[1:]])))
    return out[:LIMIT]


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name')}

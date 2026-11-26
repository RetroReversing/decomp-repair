"""A narrow call result used in an argument's arithmetic, staged in a word local first.

m2c writes `put(p, (s16) (get(p) - x));`, and a hand rewrite `put(p, get(p) - x);`. With `get` declared to return a
halfword, GCC folds its sign extension into the narrowing of the sum, so the `sll`/`sra` after the call is gone. The
game kept the result in an `int` and changed that: `v = get(p); v -= x; put(p, v);` extends it first. A KMC GCC 2.7.2
N64 function sat at 200 with only those two instructions missing and was exact with the compound form; the form with
the arithmetic left in the argument scored 120 (the extension a move too early). Both are offered, in a block of their
own. Only calls whose other arguments call nothing are rewritten, so the order of calls is unchanged.
"""
import re

FAMILY = 'narrow_call_result_stage'
FAMILIES = (FAMILY,)
LOCAL = 'staged_result'
_NARROW = r'\b(?:s8|u8|s16|u16|short|char)\s+'
_STATEMENT = re.compile(r'(?m)^([ \t]*)([A-Za-z_]\w*)[ \t]*\(')
_CALL = re.compile(r'(?<![\w.>])(?!(?:sizeof|if|while|for|switch|return)\b)[A-Za-z_]\w*\s*\(|\)\s*\(')
_CAST = re.compile(r'\(\s*(?:(?:const|volatile|unsigned|signed|struct)\s+)*(?:(?:s8|u8|s16|u16|s32|u32|f32|char|short|int|long|void)'
                   r'(?:\s*\*+)?|[A-Za-z_]\w*\s*\*+)\s*\)')
_ASSIGNS = re.compile(r'\+\+|--|(?<![=!<>])=(?!=)')
MAX_SITES = 6


def _closing(text, start):
    depth = 0
    for at in range(start, len(text)):
        depth += {'(': 1, ')': -1}.get(text[at], 0)
        if depth == 0:
            return at
    return None


def _arguments(text):
    parts, depth, last = [], 0, 0
    for at, char in enumerate(text):
        depth += {'(': 1, '[': 1, ')': -1, ']': -1}.get(char, 0)
        if char == ',' and depth == 0:
            parts.append(text[last:at].strip())
            last = at + 1
    return [*parts, text[last:].strip()]


def _calls(text):
    """Whether the expression calls something (a cast before a parenthesis is not a call)."""
    return bool(_CALL.search(_CAST.sub(' ', text)))


def _unwrapped(text):
    while text.startswith('(') and _closing(text, 0) == len(text) - 1:
        text = text[1:-1].strip()
    return text


def _split(argument, narrow):
    """(cast, call, operator, rest) for `[(T)] (get(..) OP rest)` with `get` returning a narrow type."""
    cast = ''
    found = re.match(r'\(\s*(?:s16|u16|s8|u8|s32|u32)\s*\)\s*(?=\()', argument)
    if found and _closing(argument, found.end()) == len(argument) - 1:
        cast, argument = found[0].strip() + ' ', argument[found.end():]
    expression = _unwrapped(argument)
    head = re.match(r'([A-Za-z_]\w*)\s*\(', expression)
    if not head or head[1] not in narrow:
        return None
    end = _closing(expression, head.end() - 1)
    if end is None:
        return None
    tail = re.fullmatch(r'\s*([-+&|^])(?![-+&|=>])\s*(.+)', expression[end + 1:], re.S)
    if not tail:
        return None
    rest = tail[2].strip()
    if _calls(rest) or _ASSIGNS.search(rest) or _calls(expression[head.end():end]):
        return None
    # `a - b + c` stays one expression: only a single operand can move to the compound statement unchanged
    depth = 0
    for at, char in enumerate(rest):
        depth += {'(': 1, '[': 1, ')': -1, ']': -1}.get(char, 0)
        if depth == 0 and char in '+-*/&|^<>?' and at and rest[at - 1] == ' ':
            return None
    return cast, expression[:end + 1], tail[1], rest


def variants(source, name, header=''):
    if re.search(r'\b' + LOCAL + r'\b', source):
        return []
    narrow = set(re.findall(_NARROW + r'([A-Za-z_]\w*)\s*\(', header + '\n' + source)) - {name}
    if not narrow:
        return []
    sites = []
    for found in _STATEMENT.finditer(source):
        indent, callee = found[1], found[2]
        end = _closing(source, found.end() - 1)
        if end is None or not source[end + 1:].lstrip(' \t').startswith(';') or callee in ('if', 'while', 'for', 'switch'):
            continue
        before = source[:found.start()].rstrip()
        if not before.endswith((';', '{', '}')):  # the statement of an unbraced `if` or a continued line
            continue
        arguments = _arguments(source[found.end():end])
        for index, argument in enumerate(arguments):
            parts = _split(argument, narrow)
            if parts and not any(_calls(other) or _ASSIGNS.search(other)
                                 for at, other in enumerate(arguments) if at != index):
                stop = source.index(';', end) + 1
                sites.append((found.start(), stop, indent, callee, arguments, index, parts))
                break
    out = []
    for start, stop, indent, callee, arguments, index, (cast, call, operator, rest) in sites[:MAX_SITES]:
        for compound in (True, False):
            used = list(arguments)
            used[index] = f'{cast}{LOCAL}' if compound else f'{cast}({LOCAL} {operator} {rest})'
            lines = ['{', f'    s32 {LOCAL};', f'    {LOCAL} = {call};']
            if compound:
                lines.append(f'    {LOCAL} {operator}= {rest};')
            lines += [f'    {callee}({", ".join(used)});', '}']
            block = '\n'.join(indent + line for line in lines)
            out.append((FAMILY, source[:start] + block + source[stop:]))
    return out


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name', 'header')}

"""A parameter masked or adjusted into a temporary, written back into the parameter itself.

m2c names the value a parameter is reduced to and keeps the parameter as it came in:

    temp_fp = arg3 & (-(D_800CA338 == 0));
    if (temp_fp != 0) { ... use(temp_fp) ... }

The game assigned into the parameter (`arg3 &= -(g == 0);`), and then the one pseudo for the argument carries every
use: its reference count and live range decide whether it gets one of the last saved registers or is spilled. In a
392-instruction object initialiser the argument was the one whose use counts (with a loop's weighting) put it in `$fp`
while the first argument went to the stack; with the temporary the two were swapped (6506 -> 6791 alone, the first
half of the change that gave the arguments the target's registers).

`variants` offers, for each statement `temp = param OP expr;` (`OP` one of `& | ^ << >>`, or `+ -` with a literal, `temp` a local of the same
integer type that nothing mentions before it, `param` not mentioned after it and the statement outside any loop),
`param OP= expr;` with the later uses of `temp` renamed to `param`; one child per statement, at most 3."""
import re

from .csource import _blank, find

FAMILY = 'param_in_place_update'
FAMILIES = (FAMILY,)
LIMIT = 3
IDENT = r'[A-Za-z_]\w*'
TYPE = r'(?:unsigned\s+(?:char|short|int|long)|signed\s+(?:char|short|int|long)|[su](?:8|16|32)|char|short|int|long)'
UPDATE = re.compile(rf'(?m)^(?P<indent>[ \t]*)(?P<temp>{IDENT})[ \t]*=[ \t]*\(?[ \t]*(?P<param>{IDENT})[ \t]*(?P<op><<|>>|[&|^+\-])[ \t]*(?P<expr>[^;{{}}\n]+);[ \t]*\n')


def _words(text, name):
    return [m.start() for m in re.finditer(rf'(?<![\w.]){re.escape(name)}(?!\w)', text)]


def _in_loop(clean, start, at):
    depth, i = 0, at
    while i > start:
        i -= 1
        if clean[i] == '}':
            depth += 1
        elif clean[i] == '{':
            if depth == 0:
                if re.search(r'(?:\bdo|\bfor\s*\([^{};]*\)|\bwhile\s*\([^{};]*\))\s*$', clean[max(start, i - 120):i]):
                    return True
            else:
                depth -= 1
    return False


def variants(source, name):
    """Proposals: each `temp = param OP expr;` as an in-place update of the parameter."""
    span = find(source, name)
    if not span:
        return []
    clean = _blank(source)
    signature = re.search(rf'\b{re.escape(name)}\s*\(([^)]*)\)\s*{{', clean[span[0]:span[1]])
    if not signature:
        return []
    params = {}
    for part in signature[1].split(','):
        hit = re.fullmatch(rf'\s*({TYPE})\s+({IDENT})\s*', part)
        if hit:
            params[hit[2]] = re.sub(r'\s+', ' ', hit[1])
    body_start = span[0] + signature.end()
    out = []
    for hit in UPDATE.finditer(clean, body_start, span[1]):
        temp, param = hit['temp'], hit['param']
        if param not in params or temp == param or temp in re.findall(IDENT, hit['expr']):
            continue
        if hit['op'] in '+-' and not re.fullmatch(r'\s*(?:0[xX][0-9a-fA-F]+|\d+)[uUlL]*\s*', hit['expr']):
            continue  # (a sum of two variables is a new value, not a reduction of the parameter)
        declared = re.search(rf'(?m)^[ \t]*({TYPE})[ \t]+{re.escape(temp)}[ \t]*;[ \t]*\n', clean[body_start:hit.start()])
        if not declared or re.sub(r'\s+', ' ', declared[1]) != params[param]:
            continue
        if len(_words(clean[body_start:hit.start()], temp)) != 1 or _words(clean[hit.end():span[1]], param):
            continue
        if _in_loop(clean, body_start, hit.start()):
            continue
        edited = source[:body_start + declared.start()] + source[body_start + declared.end():hit.start()]
        edited += f"{hit['indent']}{param} {hit['op']}= {hit['expr'].strip()};\n"
        edited += re.sub(rf'(?<![\w.]){re.escape(temp)}(?!\w)', param, source[hit.end():])
        out.append(edited)
    return [(FAMILY, text) for text in dict.fromkeys(out)][:LIMIT]


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name'), 'order': 61}

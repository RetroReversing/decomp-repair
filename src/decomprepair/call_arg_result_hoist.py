"""A call argument that is another call's result with arithmetic or a mask, computed in a local just before the call.

m2c writes a call with many arguments as one statement, the last argument `(g(8) + 0x26) & 0xFF`. With more than four
arguments the extra ones are stack stores, and the compiler schedules the `andi` of the nested result among them, ahead
of stores the target makes first. An N64 function (KMC GCC 2.7.2, `-G0 -mips3 -mgp32 -mfp32 -O2`, 60 points, an eleven
argument call) was exact with `t = g(8) + 0x26;` as its own statement right before the call and `t & 0xFF` as the last
argument (`s32 t;` declared with the other locals; `u8 t;` matched as well): the inner call and its add happen before
the stack stores begin and the mask stays at its use. The scheduling reading is a hypothesis; the judge decides.

call_arg_result_hoist
    A statement `[lvalue =] f(a, ..., (g(...) OP K) [& M], ...)` with at least five arguments, where one argument
    is a call to g (arguments without side effects) plus or minus a constant, optionally masked, becomes `t = g(...) OP
    K;` before it with the argument `t [& M]`. Children: an `s32` local, a `u8` local (a mask of 0xFF kept), and a `u8`
    local with that mask dropped; one site each, at most 12 children.
"""
import re

from .arm_block_support import KEYWORDS, brace_pairs, statements
from .integer_repair_support import IDENT, NUMBER, edit, split_args, view
from .pattern_repairs import close

FAMILY = 'call_arg_result_hoist'
FAMILIES = (FAMILY,)
LIMIT = 12
MIN_ARGS = 5
INNER = re.compile(rf'\(?\s*(?P<call>{IDENT}\s*\()')
DECL = re.compile(rf'(?:(?:unsigned|signed|struct|const|static)\s+)*{IDENT}(?:\s*\*+\s*|\s+){IDENT}\s*(?:\[[^\]]*\])?\s*;')


def _top_equals(text):
    depth = 0
    for at, char in enumerate(text):
        if char in '([{':
            depth += 1
        elif char in ')]}':
            depth -= 1
        elif char == '=' and depth == 0 and text[at - 1:at] not in '=!<>' and text[at + 1:at + 2] != '=':
            return at
    return -1


def _hoistable(arg):
    """(stage expression, replacement template with `{t}`, mask) when `arg` is `(g(..) +- K) [& M]`, else None."""
    text = arg.strip()
    mask = None
    hit = re.fullmatch(rf'(?P<body>.*?)\s*&\s*(?P<mask>{NUMBER})', text, re.S)
    if hit:
        text, mask = hit['body'].strip(), hit['mask']
    while text.startswith('(') and close(text, 0) == len(text):
        text = text[1:-1].strip()
    start = INNER.match(text)
    if not start or not text.startswith(start['call']):
        return None
    end = close(text, start.end() - 1)
    if not end or not re.fullmatch(rf'\s*[-+]\s*{NUMBER}\s*', text[end:]):
        return None
    inner = text[start.end():end - 1]
    if re.search(r'\+\+|--|(?<![=!<>])=(?!=)', inner):
        return None
    return text, mask


def _sites(part):
    clean = part.clean
    pairs = brace_pairs(clean, part.opening, part.end)
    if not pairs:
        return []
    found = []
    for block_open, block_close in sorted(pairs.items()):
        for start, end in statements(clean, block_open + 1, block_close):
            text = clean[start:end].rstrip()
            if not text.endswith(';') or re.match(rf'(?:{"|".join(KEYWORDS - {"return"})})\b', text) or DECL.fullmatch(text):
                continue
            body = text[:-1]
            equals = _top_equals(body)
            rhs_at = start + (equals + 1 if equals >= 0 else 0)
            rhs = clean[rhs_at:start + len(body)]
            call = re.match(rf'\s*(?:return\s+)?{IDENT}\s*\(', rhs)
            if not call or close(rhs, call.end() - 1) != len(rhs.rstrip()):
                continue
            args_at = rhs_at + call.end()
            args = clean[args_at:rhs_at + len(rhs.rstrip()) - 1]
            if re.search(r'\+\+|--', args):
                continue
            spans = split_args(args)
            if len(spans) < MIN_ARGS:
                continue
            for first, last in reversed(spans):
                got = _hoistable(args[first:last])
                if got:
                    found.append((start, args_at + first, args_at + last, got[0], got[1]))
                    break
    return found


def _fresh(clean):
    name = 't'
    while re.search(rf'\b{name}\b', clean):
        name += '_'
    return name


def _declare(source, part, declaration):
    clean = part.clean
    last = None
    for start, end in statements(clean, part.opening + 1, part.end - 1):
        if not DECL.fullmatch(clean[start:end].strip()) or clean[start:end].strip().split()[0] in KEYWORDS:
            break
        last = end
    at = (source.find('\n', last) + 1) if last is not None else source.find('\n', part.opening) + 1
    indent = re.match(r'[ \t]*', source[at:])[0] or '    '
    return source[:at] + f'{indent}{declaration}\n' + source[at:]


def _child(source, part, name, site, kind, keep_mask):
    start, first, last, stage, mask = site
    local = _fresh(part.clean)
    line = source.rfind('\n', 0, start) + 1
    indent = source[line:start] if not source[line:start].strip() else '    '
    arg = source[first:last]
    lead = arg[:len(arg) - len(arg.lstrip())]
    trail = arg[len(arg.rstrip()):]
    new_arg = lead + (f'{local} & {mask}' if mask and keep_mask else local) + trail
    child = edit(source, [(start, start, f'{local} = {stage};\n{indent}'), (first, last, new_arg)])
    return _declare(child, view(child, name), f'{kind} {local};')


def variants(source, name):
    part = view(source, name)
    if not part or not part.body.strip():
        return []
    out = []
    for site in _sites(part)[:LIMIT // 3]:
        out.append(_child(source, part, name, site, 's32', True))
        if site[4] is not None and int(site[4].rstrip('uUlL'), 0) == 0xFF:
            out.append(_child(source, part, name, site, 'u8', True))
            out.append(_child(source, part, name, site, 'u8', False))
    return [(FAMILY, child) for child in dict.fromkeys(out)][:LIMIT]


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name')}

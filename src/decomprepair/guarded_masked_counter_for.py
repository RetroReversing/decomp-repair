"""m2c's rotated loop over a narrow counter that starts at an expression, written as the `for` loop it came from.

`for (i = START; i < LIMIT; i++)` over a `u16` counter comes back from m2c as a word counter, a masked copy and the
compiler's entry test:

    start = (page - 1) * 6;                         u16 i;
    var_s0 = start;                                 for (i = (page - 1) * 6; i < (page - 1) * 6 + 6; i++) {
    var_a0 = var_s0 & 0xFFFF;                           ... table[i] ...
    if (var_a0 < (start + 6)) {              ->     }
        do {
            ... var_a0 ... var_s0 & 0xFFFF ...
            var_s0 += 1;
            f(x);
            var_a0 = var_s0 & 0xFFFF;
        } while (var_a0 < (((page - 1) * 6) + 6));
    }

`masked_counter_loop` (masked_counter_repairs) and `masked_counter_guard_for` need a counter that starts at 0.

`guarded_masked_counter_for`: offered when the wide counter is set from the start value, copied through a 0xFFFF or
0xFF mask, the guard compares the copy with the loop's bound (as written, or through the local that holds the start),
the body steps the wide counter once, with nothing naming either after the step, and ends by copying it again. The
masked copy becomes the `u16`/`u8` counter, so what reads it after the loop reads the same value. One child writes the
start's local into the header (when only the counter and the guard use it), one keeps it. In an SN GCC 2.8.1 `-O2` N64
function this step was 3698 -> 2403 after its stack records were written. The exact judge decides.
"""
import re

from .csource import _blank, find
from .pattern_repairs import close

FAMILY = 'guarded_masked_counter_for'
FAMILIES = (FAMILY,)

_ID = r'[A-Za-z_]\w*'
_MASKS = {'0xffff': 'u16', '65535': 'u16', '0xff': 'u8', '255': 'u8'}
_HEAD = re.compile(
    rf'(?m)^(?P<indent>[ \t]*)(?P<wide>{_ID}) = (?P<start>[^;{{}}\n]+);\n'
    rf'[ \t]*(?P<narrow>{_ID}) = (?P=wide) & (?P<mask>0[xX][0-9A-Fa-f]+|\d+);\n'
    r'[ \t]*if \((?P<test>[^{};\n]+)\) \{\n'
    r'[ \t]*do \{\n')


def _flat(expression):
    return re.sub(r'[\s()]', '', expression)


def _count(text, name):
    return len(re.findall(rf'\b{name}\b', _blank(text)))


def variants(source, name):
    span = find(source, name)
    if not span:
        return []
    clean = _blank(source)
    out = []
    for head in _HEAD.finditer(clean, *span):
        out.extend(_loop(source, clean, span, head))
    return out[:4]


def _loop(source, clean, span, head):
    wide, narrow, kind = head['wide'], head['narrow'], _MASKS.get(head['mask'].lower())
    if not kind or wide == narrow:
        return []
    outer = clean.find('{', head.start('test'))
    outer_end = close(clean, outer, '{', '}')
    inner = clean.find('{', outer + 1)
    inner_end = close(clean, inner, '{', '}')
    if not outer_end or not inner_end:
        return []
    tail = re.compile(rf'[ \t]*while \({narrow} < (?P<bound>[^;{{}}\n]+)\);\n[ \t]*\}}[ \t]*\n').match(
        clean, _after(clean, inner_end))
    if not tail or tail.end() < outer_end:
        return []
    test = re.fullmatch(rf'{narrow} < (?P<bound>.+)', source[head.start('test'):head.end('test')].strip())
    if not test:
        return []
    bound = source[tail.start('bound'):tail.end('bound')].strip()
    start = source[head.start('start'):head.end('start')].strip()
    # the local that holds the start value, set just above the counter
    local = None
    before = re.compile(rf'(?m)^[ \t]*(?P<v>{_ID}) = (?P<value>[^;{{}}\n]+);\n\Z').search(clean, span[0], head.start())
    if before and before['v'] == start and start != wide:
        local = (before, source[before.start('value'):before.end('value')].strip())
    guard = test['bound']
    if local:
        guard = re.sub(rf'\b{local[0]["v"]}\b', lambda _: f'({local[1]})', guard)
    if _flat(guard) != _flat(bound) or _count(bound, wide) or _count(bound, narrow):
        return []
    body_start = clean.find('\n', inner) + 1
    body_end = clean.rfind('\n', body_start, inner_end - 1) + 1
    body = source[body_start:body_end]
    last = re.search(rf'(?m)^[ \t]*{narrow} = {wide} & {head["mask"]};\n\Z', body)
    step = re.search(rf'(?m)^[ \t]*(?:{wide} \+= 1|{wide}\+\+|\+\+{wide});\n', body)
    if not last or not step or step.start() > last.start():
        return []
    rest = body[step.end():last.start()]
    if _count(rest, wide) or _count(rest, narrow) or re.search(r'\b(?:continue|goto)\b', _blank(body)):
        return []
    body = body[:step.start()] + rest
    mask = rf'\b{wide}\s*&\s*{head["mask"]}\b'
    body = re.sub(rf'\({mask}\)', narrow, body)
    body = re.sub(mask, narrow, body)
    renamed = []
    # a local that only renames the masked read (`temp = var_s0 & 0xFFFF;`) is the counter itself
    for copy in re.findall(rf'(?m)^[ \t]*({_ID}) = {narrow};\n', body):
        line = rf'(?m)^[ \t]*{copy} = {narrow};\n'
        if copy != narrow and _count(source[span[0]:span[1]], copy) == _count(body, copy) + 1 \
                and len(re.findall(rf'\b{copy}\s*(?:[-+*/&|^]?=(?!=)|\+\+|--)|(?:\+\+|--|&)\s*{copy}\b', _blank(body))) == 1:
            body = re.sub(rf'\b{copy}\b', narrow, re.sub(line, '', body))
            renamed.append(copy)
    if _count(body, wide) or re.search(rf'\b{narrow}\s*(?:[-+*/&|^]?=(?!=)|\+\+|--)|(?:\+\+|--|&)\s*{narrow}\b', body):
        return []
    after = source[tail.end():span[1]]
    if _count(after, wide):
        return []
    indent = head['indent']
    lines = body.split('\n')
    body = '\n'.join(line[4:] if line.startswith(indent + '        ') else line for line in lines)

    def build(first, drop_local):
        begin = local[0].start() if drop_local else head.start()
        loop = f'{indent}for ({narrow} = {first}; {narrow} < {bound}; {narrow}++) {{\n{body}{indent}}}\n'
        text = source[:begin] + loop + source[tail.end():]
        end = span[1] + len(text) - len(source)
        function = text[span[0]:end]
        function, found = re.subn(rf'(?m)^([ \t]*)(?:s32|u32|int|s16|u16|u8|M2C_UNK)[ \t]+{narrow};', rf'\1{kind} {narrow};',
                                  function, count=1)
        if not found:
            return None
        for dead in [wide, *renamed] + ([local[0]['v']] if drop_local else []):
            if _count(function, dead) == 1:
                function = re.sub(rf'(?m)^[ \t]*[A-Za-z_]\w*[ \t]+{dead};\n', '', function, count=1)
        return text[:span[0]] + function + text[end:]

    children = []
    if local:
        name_ = local[0]['v']
        uses = _count(source[span[0]:span[1]], name_)
        # its declaration, its assignment, the counter's start and the guard
        if uses <= 4 and not _count(bound, name_) and not _count(body, name_):
            children.append(build(local[1], True))
    children.append(build(start, False))
    return [(FAMILY, child) for child in children if child]


def _after(clean, end):
    """The index just past the `}` that `close` found (it may return either the brace or the index after it)."""
    return end if clean[end - 1] == '}' else end + 1


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name')}

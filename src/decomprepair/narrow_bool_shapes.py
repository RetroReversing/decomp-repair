"""Two source shapes the allocator and the first scheduler read differently from m2c's (KMC gcc 2.7.2, `-G0 -mips3 -mgp32 -mfp32 -O2`).

Found on a 214-instruction slot-update loop whose saved best was 140 and went 140 -> 80 -> 70 by these two edits
(docs/learnings/function/narrow-param-unwrap-bool-pair.md):

- `narrow_param_unwrap`: `e = helper((u16) i, sizeof(*p), (u32) p);` where `static inline T helper(u16 a, int b, u32 c)
  { return (T) ((a * b) + c); }`, written as `a_t = i; e = (T) ((a_t * sizeof(*p)) + (u32) p);`. Every unwrap family
  that already exists expands the helper with its arguments substituted; the halfword *parameter* is a user pseudo of
  its own in the compiled helper (`reg/v:HI`) and it is what cse compares the later `p[(u16) i]` addresses against, so
  dropping it makes cse merge them and the game's separate recomputation after the join disappears (650), while
  keeping the helper leaves the return-value copy that combine cannot fold into the add (`addu v0; move s0,v0`).
  The halfword temp written out keeps the first and removes the second (140 -> 80, the load of the entry's first byte
  also returns to the target's place). Hypothesis, from cse.c's make_regs_eqv and the RTL dumps; not isolated further.
- `bool_pair_inline`: `t = x == 0; u = y == 0; if (u & t)` with `t` and `u` read nowhere else, as one expression
  `if ((x == 0) & (y == 0))`. Each named temp is a user pseudo that local-alloc ties to the register of the operand
  that dies at its set, so the chain's registers differ from the game's, whose two comparisons are plain temporaries
  (70 from 80: two `sltiu` destinations). Both operand orders are offered.

`narrow_bool_shapes` offers both at once.
"""
import re

from .integer_repair_support import DECL, IDENT, INTEGER, edit, view

FAMILY_PARAM = 'narrow_param_unwrap'
FAMILY_BOOL = 'bool_pair_inline'
FAMILY_BOTH = 'narrow_bool_shapes'
FAMILIES = (FAMILY_PARAM, FAMILY_BOOL, FAMILY_BOTH)
NARROW = {'u8', 'u16', 's8', 's16', 'unsigned char', 'unsigned short', 'signed char', 'short', 'char'}
HELPER = re.compile(rf'(?:static\s+inline|inline\s+static)\s+(?P<ret>[\w\s]*?\w[\w\s]*?\s*\**)\s*\b(?P<name>{IDENT})\s*'
                    rf'\((?P<params>[^()]*)\)\s*{{\s*return\s+(?P<expression>[^;{{}}]+);\s*}}')


def _split(text):
    """Top-level comma-separated pieces of an argument list."""
    pieces, depth, start = [], 0, 0
    for index, char in enumerate(text):
        if char in '([':
            depth += 1
        elif char in ')]':
            depth -= 1
        elif char == ',' and depth == 0:
            pieces.append(text[start:index])
            start = index + 1
    pieces.append(text[start:])
    return [piece.strip() for piece in pieces]


def _params(text):
    """[(type, name)] of a helper's parameter list, or None when a parameter is not `type name`."""
    result = []
    for piece in _split(text):
        match = re.fullmatch(rf'(?P<type>(?:unsigned\s+|signed\s+)?{IDENT}(?:\s*\*+)?)(?:\s+|(?<=\*)\s*)(?P<name>{IDENT})', piece)
        if not match:
            return None
        result.append((re.sub(r'\s+', ' ', match['type']).strip(), match['name']))
    return result


def _unwrap(source, part):
    """[(start, end, text)] for each `lhs = helper(args);` whose helper has a narrow parameter, with the declarations to add."""
    helpers = {}
    for match in HELPER.finditer(part.clean[:part.opening]):
        params = _params(match['params'])
        if params and any(kind in NARROW for kind, _ in params) and not re.search(rf'\b{re.escape(match["name"])}\b', match['expression']):
            helpers[match['name']] = (params, match['expression'].strip())
    if not helpers:
        return None
    edits, declarations, taken = [], [], set()
    call = re.compile(rf'(?<![\w.>])(?P<lhs>{IDENT})\s*=(?!=)\s*(?P<callee>{IDENT})\s*\((?P<args>[^;{{}}]*)\)\s*;')
    for found in call.finditer(part.clean, part.opening, part.end):
        if found['callee'] not in helpers or part.clean[:found.start()].rstrip()[-1:] not in (';', '{', '}'):
            continue
        params, expression = helpers[found['callee']]
        args = _split(source[found.start('args'):found.end('args')])
        if len(args) != len(params):
            continue
        replacement, temps = {}, []
        for (kind, name), argument in zip(params, args):
            if kind in NARROW:
                temp = f'{found["callee"]}_{name}'
                while temp in taken or re.search(rf'\b{re.escape(temp)}\b', source):
                    temp += '_'
                taken.add(temp)
                temps.append(f'{temp} = {argument};')
                declarations.append(f'  {kind} {temp};')
                replacement[name] = temp
            else:
                replacement[name] = argument if re.fullmatch(r'[\w.]+|\([^()]*\)|sizeof\s*\([^()]*\)', argument) else f'({argument})'
        body = re.sub(rf'(?<![\w.>])({IDENT})\b', (lambda m, table=replacement: table.get(m.group(1), m.group(0))), expression)
        indent = re.match(r'[ \t]*', source[source.rfind('\n', 0, found.start()) + 1:]).group()
        text = ('\n' + indent).join(temps + [f'{found["lhs"]} = {body};'])
        edits.append((found.start(), found.end(), text))
    if not edits:
        return None
    opening = part.opening + 1
    declared = DECL.search(part.clean, part.opening, part.end)
    where = declared.start() if declared else opening
    line = source.rfind('\n', 0, where) + 1 if declared else opening
    edits.append((line, line, ('\n' if not declared else '') + '\n'.join(declarations) + '\n'))
    return edits


def _bool_pairs(source, part):
    """[[(start, end, text)]], one edit list per operand order, joining two single-use comparison temps in an `if`."""
    clean = part.clean
    pattern = re.compile(rf'(?<![\w.>])(?P<x>{IDENT})\s*=(?!=)\s*(?P<ex>[^;{{}}]*?[=!<>]=[^;{{}}=]*?);\s*(?P<y>{IDENT})\s*=(?!=)\s*(?P<ey>[^;{{}}]*?[=!<>]=[^;{{}}=]*?);\s*'
                         r'if\s*\(')
    orders = ([], [])
    for found in pattern.finditer(clean, part.opening, part.end):
        x, y = found['x'], found['y']
        if x == y or re.search(rf'(?<![\w.>]){re.escape(x)}\b', found['ey']):
            continue
        if any(re.search(rf'(?<![\w.>])(?!sizeof\b){IDENT}\s*\(|\+\+|--|(?<![=!<>])=(?!=)', expression) for expression in (found['ex'], found['ey'])):
            continue
        depth, close = 1, found.end()
        while close < part.end and depth:
            depth += {'(': 1, ')': -1}.get(clean[close], 0)
            close += 1
        if depth:
            continue
        test = re.sub(r'\(\s*(?:u16|u8|u32|s32|int)\s*\)', '', clean[found.end():close - 1])
        names = re.findall(IDENT, test)
        if sorted(names) != sorted([x, y]) or '&&' in test or '||' in test or not re.fullmatch(rf'[\s()]*{IDENT}[\s()]*&[\s()]*{IDENT}[\s()]*', test):
            continue
        for name in (x, y):
            rest = [m for m in re.finditer(rf'(?<![\w.>]){re.escape(name)}\b', clean[close:part.end])]
            before = [m for m in re.finditer(rf'(?<![\w.>]){re.escape(name)}\b', clean[part.opening:found.start()])
                      if not re.search(rf'\b(?:{INTEGER})\s+$', clean[:part.opening + m.start()])]
            if rest and not re.match(rf'{re.escape(name)}\s*=(?!=)', clean[close + rest[0].start():]):
                break
            if before and not re.match(rf'{re.escape(name)}\s*=(?!=)', clean[part.opening + before[0].start():]):
                break
        else:
            first, second = found['ex'].strip(), found['ey'].strip()
            for index, (one, two) in enumerate(((first, second), (second, first))):
                orders[index].append((found.start(), close, f'if (({one}) & ({two}))'))
    return [edits for edits in orders if edits]


def variants(source, name):
    part = view(source, name)
    if not part or re.search(r'\b(?:asm|__asm__|setjmp|longjmp)\b|^\s*#', part.body, re.M):
        return []
    result, every = [], []
    unwrapped = _unwrap(source, part)
    if unwrapped:
        text = edit(source, unwrapped)
        if text != source:
            result.append((FAMILY_PARAM, text))
            every.extend(unwrapped)
    pairs = _bool_pairs(source, part)
    for edits in pairs:
        text = edit(source, edits)
        if text != source:
            result.append((FAMILY_BOOL, text))
    if unwrapped and pairs:
        text = edit(source, unwrapped + pairs[0])
        if text != source:
            result.append((FAMILY_BOTH, text))
    return result


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name'), 'order': 82}

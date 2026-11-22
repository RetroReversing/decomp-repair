"""A backward-goto loop written the way the game wrote a real loop, so GCC 2.x's loop pass hoists its invariants.

m2c writes a loop as `again: ... if (c) goto again;` and caches every value computed from a parameter in a local
before the label (`high = (u32)(p & 0xffff) >> 7; low = p & 0x7f;`). A loop the compiler never sees as a loop gets
none of loop.c's treatment, and a cached local gets its own pseudo whose known bits combine.c uses to fold a later
`low & 0xff`. A KMC gcc 2.7.2 sound-voice function (45 -> 0) was exact once the whole set was changed together:

1. the label and its one backward `if (c) goto L;` became `do { ... } while (c);`;
2. the cached locals were written at their uses in the loop (loop.c hoists them again, into pseudos combine.c
   cannot fold, so the target's `andi $a3,$sN,0xff` on a masked-to-7-bits value stays);
3. a second computation of an offset the loop already computed (`handle = *(T *)(&sym + i * 0x1a0)` after
   `off = i * 0x1a0`) went through a local of its own, so cse leaves it as the target's separate shifts;
4. a callee's byte parameter that every call masked with `& 0xff` was declared `u8` and the masks dropped, which is
   the zero-extension the target does for it.
Each step alone left the score worse or unchanged (1441 -> 910 -> 0); the whole set is one child here, with the
shorter combinations as extra children. The reasons are hypotheses read from the output, not from compiler source.
"""
import re

from .integer_repair_support import IDENT, edit, view

FAMILY = 'goto_loop_invariants'
FAMILIES = (FAMILY,)

TYPE = r'(?:unsigned\s+(?:char|short|int)|signed\s+(?:char|short|int)|[su](?:8|16|32)|int|short|char)'
UNSAFE = re.compile(r'\b(?:volatile|asm|__asm__|setjmp|longjmp|switch|case|default|break|continue|return)\b|^\s*#', re.M)
FRESH = '__repair_loop_stage'


def _balanced(text):
    depth = 0
    for char in text:
        depth += (char == '{') - (char == '}')
        if depth < 0:
            return False
    return depth == 0


def _written(name, text):
    return re.search(rf'\b{name}\s*(?:=(?!=)|[-+*/%&|^]=|<<=|>>=|\+\+|--)|(?:\+\+|--)\s*{name}\b|&\s*{name}\b', text)


def _loop(part):
    """(label match, goto match, condition) of the one backward `if (c) goto L;` that closes its own block."""
    labels = list(re.finditer(rf'(?m)^[ \t]*({IDENT})\s*:(?!:)[ \t]*', part.body))
    for label in labels:
        name = label[1]
        if name in {'default'}:
            continue
        gotos = list(re.finditer(rf'\bgoto\s+{name}\s*;', part.body))
        closing = re.search(rf'\bif\s*\(([^;{{}}]*)\)\s*goto\s+{name}\s*;', part.body[label.end():])
        if len(gotos) != 1 or not closing or gotos[0].start() < label.end():
            continue
        start = label.end()+closing.start()
        if _balanced(part.body[label.end():start]) and not part.body[label.end()+closing.end():].lstrip().startswith('else'):
            return label, (label.end()+closing.start(), label.end()+closing.end()), closing[1]
    return None


def _stages(part, label, loop_end):
    """Assignments `name = pure expression;` just before the label whose name is read only inside the loop."""
    before = part.body[:label.start()]
    found = []
    for match in reversed(list(re.finditer(rf'(?m)^[ \t]*({IDENT})\s*=\s*([^;{{}}=]*?)\s*;[ \t]*\n?', before))):
        if found and match.end() != found[-1].start() or not found and before[match.end():].strip():
            break
        found.append(match)
    stages = []
    inside = part.body[label.end():loop_end]
    for match in found:
        name, expr = match[1], match[2]
        for ident in set(re.findall(IDENT, expr)):
            # The loop rewrites `ident`, but it still holds the copy it started as: read the original instead.
            copy = re.search(rf'\b{TYPE}\s+{ident}\s*=\s*({IDENT})\s*[;,]', part.body[:label.start()])
            if (copy and _written(ident, inside) and not _written(copy[1], part.body)
                    and not _written(ident, part.body[copy.end():label.start()])):
                expr = re.sub(rf'\b{ident}\b', copy[1], expr)
        outside = part.body[:match.start()]+part.body[match.end():label.start()]+part.body[loop_end:]
        outside = re.sub(rf'\b{TYPE}\s+{name}\s*(?:=[^;,]*)?;', '', outside)
        if re.search(rf'\b{name}\b', outside):
            continue
        if (re.search(rf'\b{IDENT}\s*\(', re.sub(rf'\(\s*{TYPE}\s*\)', '', expr)) or re.search(r'[\[\]*]|->|\+\+|--', expr)
                or _written(name, inside)
                or any(_written(ident, inside) for ident in set(re.findall(IDENT, expr)) - {'u8', 'u16', 'u32', 's8', 's16', 's32'})
                or not re.search(rf'\b{name}\b', inside)):
            continue
        stages.append((match, expr))
    return stages


def _declaration(part, name):
    """The one `TYPE name;` or `TYPE name = init;` statement (alone on its statement) that declares the local."""
    hits = list(re.finditer(rf'(?m)(?<![\w,])({TYPE})\s+{name}\s*(?:=\s*[^;,{{}}]*)?;[ \t]*\n?', part.body))
    return hits[0] if len(hits) == 1 else None


def _stage_products(text, name):
    """Edits that send a second `x * K` through a fresh local, where the loop already assigned that product."""
    part = view(text, name)
    found = _loop(part) if part else None
    if not found:
        return text
    label, (goto_start, _), _ = found
    inside = part.body[label.end():goto_start]
    for product in re.finditer(rf'(?m)^[ \t]*{IDENT}\s*=\s*({IDENT}\s*\*\s*(?:0[xX][0-9a-fA-F]+|\d+))\s*;', inside):
        pattern = re.escape(product[1]).replace(r'\ ', r'\s*')
        later = [m for m in re.finditer(pattern, inside) if m.start() >= product.end()]
        if not later:
            continue
        use = later[0]
        line = inside.rfind('\n', 0, use.start())+1
        base = part.opening+1+label.end()
        return edit(text, [(part.opening+1, part.opening+1, f'\ns32 {FRESH};\n'),
                           (base+line, base+line, f'{FRESH} = {product[1]};\n'),
                           (base+use.start(), base+use.end(), FRESH)])
    return text


def _narrow_calls(text, name):
    """Declare a callee's last parameter `u8` where every call in the loop masks that argument with 0xff."""
    part = view(text, name)
    found = _loop(part) if part else None
    if not found:
        return text
    label, (goto_start, _), _ = found
    base, body = part.opening+1+label.end(), part.body[label.end():goto_start]
    calls = {}
    for call in re.finditer(rf'\b({IDENT})\s*\(', body):
        args, depth, start = [], 0, call.end()
        for i in range(call.end(), len(body)):
            if body[i] in '([':
                depth += 1
            elif body[i] in ')]' and depth:
                depth -= 1
            elif body[i] == ')':
                args.append((start, i))
                break
            elif body[i] == ',' and depth == 0:
                args.append((start, i))
                start = i+1
        calls.setdefault(call[1], []).append(args)
    for callee, sites in calls.items():
        if len(sites) < 2 or len({len(site) for site in sites}) != 1 or not sites[0]:
            continue
        proto = re.search(rf'(?m)^[^\n(;{{}}]*\b{callee}\s*\(([^()]*)\)\s*;', text[:part.opening])
        if not proto:
            continue
        params = [p.strip() for p in proto[1].split(',')]
        if len(params) != len(sites[0]) or not re.fullmatch(r'(?:s32|u32|int|unsigned int)', params[-1]):
            continue
        changes = []
        for site in sites:
            start, end = site[-1]
            mask = re.fullmatch(r'(\s*)(.*?)\s*&\s*(?:0[xX][fF][fF]|255)\s*', body[start:end], re.S)
            if not mask:
                changes = None
                break
            changes.append((base+start, base+end, ' '+mask[2].strip()))
        if changes:
            last = proto.start(1)+proto[1].rfind(params[-1])
            return edit(text, changes+[(last, last+len(params[-1]), 'u8')])
    return text


def _convert(source, name):
    """The loop as a `do { } while`, with the parameter-derived locals written where the loop reads them."""
    part = view(source, name)
    if not part:
        return None
    if re.search(r'\b(?:volatile|asm|__asm__|setjmp|longjmp|switch|case|default)\b|^\s*#', part.body, re.M):
        return None
    found = _loop(part)
    if not found or re.search(r'\b(?:break|continue)\b', part.body[found[0].end():found[1][0]]):
        return None
    label, (goto_start, goto_end), cond = found
    stages = _stages(part, label, goto_start)
    if not stages:
        return None
    base = part.opening+1
    changes = [(base+label.start(), base+label.end(), 'do {\n'), (base+goto_start, base+goto_end, f'}} while ({cond});')]
    for stage, expr in stages:
        decl = _declaration(part, stage[1])
        if not decl or decl.start() > stage.start():
            return None
        changes += [(base+stage.start(), base+stage.end(), ''), (base+decl.start(), base+decl.end(), '')]
        for use in re.finditer(rf'\b{stage[1]}\b', part.body[label.end():goto_start]):
            at = base+label.end()+use.start()
            changes.append((at, at+len(stage[1]), f'({expr})'))
    text = edit(source, changes)
    # A one-shot scope left on a call inside the loop only fences the loop pass's view of it.
    again = view(text, name)
    fenced = re.compile(r'do\s*{\s*([^{};]*;)\s*}\s*while\s*\(\s*0\s*\)\s*;')
    return text[:again.opening]+fenced.sub(r'\1', text[again.opening:again.end])+text[again.end:]


def variants(source, name, header=''):
    part = view(source, name)
    if not part or FRESH in part.clean:
        return []
    out = []
    for narrow in (False, True):
        for stage in (False, True):
            text = source
            if narrow:
                text = _narrow_calls(text, name)
            if stage:
                text = _stage_products(text, name)
            if (narrow or stage) and text == source:
                continue
            text = _convert(text, name)
            if text and text != source and text not in out:
                out.append(text)
    # the whole set first: it is the child that matched, the shorter ones are the stepping stones
    return [(FAMILY, text) for text in reversed(out)]

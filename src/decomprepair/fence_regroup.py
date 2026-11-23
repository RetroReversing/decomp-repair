"""A search's loop fences and join guard regrouped: the fences opened, one narrowed to the run it ends on, the guard
before a compare made a real condition, the counter's reset after the call, as one child.

A saved best that a search has worked on is full of `do { } while (0);` fences (each one a loop note that gcc 2.7.2 reads
as one more level of loop depth: flow.c adds `loop_depth` to every reference inside, so the allocator's priority,
`floor_log2 (refs) * refs / live length`, ranks pseudos by how deep the search happened to nest them) and of identical-arm
guards (`if (x) { S } else { S }`, cross-jumped back to `S`, whose only effect is a join before the next compare). On a
370-instruction mixing function (KMC GCC 2.7.2, `-G0 -mips3 -mgp32 -mfp32 -O2`) the right priorities (loop counter
first, then the word copied from the post-increment, then the sample count) came only from opening every fence, and then
the reload of a global in an `else` arm, which the target has, came back only when the compare sat after a join: the
guard that did that read an uninitialised local, and the same guard on a flag the function had already tested kept the
join with defined behaviour. Each step alone was worse (opening one fence 100 -> 175, the real condition alone 100, the
reset after the call alone 100); together with a fence round the last two statements of the block the outer fence had
ended on, 100 -> 0.

`variants` offers, each when it applies, as separate children and as one combined child (`fence_regroup`):
- `fence_open`: every `do { S } while (0);` written as the block `{ S }` (breaks inside nested loops of `S` stay with
  those loops; a break of the fence itself keeps it), the outermost fence's last two statements fenced again;
- `tail_guard_collapse`: an identical-arm `if (c) { S } else { S }` whose arms hold no call and whose condition is
  free of calls and assignments, written as `S`;
- `join_guard_flag`: an identical-arm guard whose arms hold a call and whose condition is a local nothing assigns before
  it (so it reads an uninitialised local), its condition written as a scalar global the function tests earlier (one child
  per candidate, at most three);
- `init_after_call`: `x = K;` written straight before a call that does not mention `x` (`x` a local whose address is not
  taken), after the call.
The compiler explanations (flow.c's loop-depth weights, global.c's priority order, cse.c's path following, which needs a
barrier before the `else` label) are read from the source and labelled hypotheses; the judge decides each child.
"""
import re

from .identical_arm_collapse_repairs import ARMS
from .integer_repair_support import IDENT, INTEGER, _address_taken, edit, view
from .line_scan import lines
from .pattern_repairs import close

FAMILY = 'fence_regroup'
FAMILIES = (FAMILY, 'fence_open', 'tail_guard_collapse', 'join_guard_flag', 'init_after_call')
FENCE = re.compile(r'\bdo\s*\{')
FENCE_END = re.compile(r'\s*while\s*\(\s*0\s*\)\s*;')
LOOP_OPEN = re.compile(r'\bdo\s*\{|\b(?:for|while|switch)\s*\([^{};]*\)\s*\{')
CALL_IN = re.compile(rf'(?<![\w.>])(?!(?:if|while|for|switch|sizeof|return)\b){IDENT}\s*\(')
CONST_INIT = re.compile(rf'^(?P<indent>[ \t]*)(?P<name>{IDENT})\s*=\s*(?:0[xX][0-9a-fA-F]+|[0-9]+)\s*;\s*$')
CALL_LINE = re.compile(rf'^[ \t]*(?!(?:if|while|for|switch|return)\b){IDENT}\s*\([^;{{}}]*\)\s*;\s*$')
EXTERN_SCALAR = re.compile(rf'(?m)^[ \t]*extern\s+(?:{INTEGER})\s+(?P<name>{IDENT})\s*;[ \t]*$')
FLAGS = 3


def _owns_jump(clean, brace, end, at):
    """Whether the `break`/`continue` at `at` belongs to a loop or switch nested inside the fence body."""
    for hit in LOOP_OPEN.finditer(clean, brace + 1, at):
        opening = hit.end() - 1
        stop = close(clean, opening, '{', '}')
        if stop and stop > at and opening > brace:
            return True
    return False


def _fences(part):
    """Each `do { S } while (0);` as `(start, brace, end, stop)`: the `do`, its `{`, just past its `}` and past the `;`."""
    found = []
    for hit in FENCE.finditer(part.clean, part.opening, part.end):
        brace = hit.end() - 1
        end = close(part.clean, brace, '{', '}')
        tail = FENCE_END.match(part.clean, end) if end else None
        if not tail:
            continue
        jumps = [brace + j.start() for j in re.finditer(r'\b(?:break|continue)\b', part.clean[brace:end])]
        if any(not _owns_jump(part.clean, brace, end, at) for at in jumps):
            continue
        found.append((hit.start(), brace, end, tail.end()))
    return found


def fence_open(source, name):
    """Every fence opened, the outermost one's last two statements fenced again; None when there is no fence."""
    text = source
    narrowed = False
    for _ in range(64):
        part = view(text, name)
        if not part:
            return None
        fences = _fences(part)
        if not fences:
            break
        start, brace, end, stop = fences[0]
        body = text[brace + 1:end - 1]
        outer = not any(a < start and stop <= d for a, _, _, d in fences[1:]) and not narrowed
        tail = re.search(r'(?:(?<=[;{}])|^)[ \t]*\n?(?P<tail>(?:[ \t]*[^;{}\n]+;[ \t]*\n){2}|(?:[ \t]*[^;{}\n]+;[ \t]*\n[ \t]*[^;{}\n]+;))\s*$', body)
        if outer and tail and end - 1 - len(body) + tail.start('tail') > brace:
            narrowed = True
            keep = body[:tail.start('tail')].rstrip()
            last = tail['tail'].strip('\n')
            inner = re.match(r'[ \t]*', last)[0]
            lead = text[text.rfind('\n', 0, start) + 1:start]
            outer_indent = lead if not lead.strip() else ''
            text = (text[:start] + '{' + keep + '\n' + inner + 'do __KEEP__ { '
                    + ' '.join(x.strip() for x in last.split('\n') if x.strip()) + ' } while (0);\n' + outer_indent + '}' + text[stop:])
        else:
            text = text[:start] + '{' + body + '}' + text[stop:]
    text = text.replace('do __KEEP__ {', 'do {')
    return text if text != source else None


def _guards(part, source):
    return [m for m in ARMS.finditer(part.clean, part.opening, part.end)
            if ' '.join(m['a'].split()) == ' '.join(m['b'].split()) and ' '.join(m['a'].split())]


def tail_guard_collapse(source, name):
    part = view(source, name)
    if not part:
        return None
    edits = []
    for m in _guards(part, source):
        if CALL_IN.search(m['a']) or re.search(r'(?<![=!<>])=(?!=)|\+\+|--', re.sub(r'\(\s*[su](?:8|16|32)\s*\)', '', m['cond'])) \
                or CALL_IN.search(m['cond']):
            continue
        body = source[m.start('a'):m.end('a')].strip()
        indent = re.match(r'[ \t]*', part.clean[part.clean.rfind('\n', 0, m.start()) + 1:m.start()])[0]
        statements = [line.strip() for line in body.split('\n') if line.strip()]
        edits.append((m.start(), m.end(), ('\n' + indent).join(statements)))
    return edit(source, edits) if edits else None


def join_guard_flag(source, name):
    """Children, one per flag: the call-holding identical-arm guard on an unassigned local, its condition a flag."""
    part = view(source, name)
    if not part:
        return []
    head = part.clean[:part.opening]
    scalars = {m['name'] for m in EXTERN_SCALAR.finditer(head)}
    out = []
    for m in _guards(part, source):
        cond = m['cond'].strip()
        if not re.fullmatch(IDENT, cond) or not CALL_IN.search(m['a']):
            continue
        before = part.clean[part.opening:m.start()]
        if re.search(rf'(?<![\w.>]){re.escape(cond)}\s*(?:[-+*&|^]|<<|>>)?=(?!=)|(?:\+\+|--)\s*{re.escape(cond)}\b|{re.escape(cond)}\s*(?:\+\+|--)', before) \
                or re.search(rf'\b{re.escape(cond)}\b', head[head.rfind('('):]):
            continue
        flags = []
        for g in re.finditer(rf'\bif\s*\(\s*(?P<g>{IDENT})\s*(?:!=\s*0\s*)?\)', before):
            if g['g'] in scalars and g['g'] not in flags:
                flags.append(g['g'])
        for flag in flags[:FLAGS]:
            out.append(edit(source, [(m.start('cond'), m.end('cond'), flag)]))
    return out


def init_after_call(source, name):
    part = view(source, name)
    if not part or re.search(r'\b(?:asm|__asm__|volatile|goto)\b', part.body):
        return None
    body = lines(part, source)
    local = {m[1] for m in re.finditer(rf'(?<![\w*])(?:{INTEGER})\s+({IDENT})\s*[;=,]', part.clean[part.opening:part.end])}
    local = {n for n in local if not _address_taken(part.body, n)}
    edits = []
    for i in range(len(body) - 1):
        init = CONST_INIT.match(body[i].text)
        if not init or init['name'] not in local or not CALL_LINE.match(body[i + 1].text) \
                or re.search(rf'(?<![\w.>]){re.escape(init["name"])}\b', body[i + 1].text):
            continue
        edits.append((body[i].start, body[i + 1].end, body[i + 1].source + '\n' + body[i].source + '\n'))
    return edit(source, edits) if edits else None


def variants(source, name):
    opened = fence_open(source, name)
    collapsed = tail_guard_collapse(source, name)
    after = init_after_call(source, name)
    flags = join_guard_flag(source, name)
    single = []
    if opened:
        single.append(('fence_open', opened))
    if collapsed:
        single.append(('tail_guard_collapse', collapsed))
    if after:
        single.append(('init_after_call', after))
    single += [('join_guard_flag', text) for text in flags]
    combined = []
    for flag_index in range(max(1, min(len(flags), FLAGS))):
        text = source
        used = 0
        for step in (fence_open, tail_guard_collapse, init_after_call):
            changed = step(text, name)
            if changed:
                text, used = changed, used + 1
        if flags:
            changed = join_guard_flag(text, name)
            if len(changed) > flag_index:
                text, used = changed[flag_index], used + 1
        if used >= 2 and text != source and (FAMILY, text) not in combined:
            combined.append((FAMILY, text))
    result = combined + [(f, t) for f, t in single if t != source]
    seen, out = set(), []
    for family, text in result:
        if text not in seen:
            seen.add(text)
            out.append((family, text))
    return out[:12]


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name'), 'order': 120}  # the registry: no caller wiring (registry.py)

"""A call argument staged in a local before the counters it reads are bumped, written in the call with the bumps after it.

m2c stages a call's argument when the target computed it before updating a counter the argument reads:

    temp = (u16) counter;  counter += 0xC0;  ++count;  call(table[index], temp);

gcc 2.7.2 evaluates the arguments of `call(table[index], (u16) counter)` where they are written, so the argument's
`andi` follows the table load (the target's order), while the staged local is computed first and the add that follows
it is scheduled in the call's delay slot differently (sched.c orders by the dependence chains ahead of each insn, and the
extra local also adds a use that the allocator weighs). Written as `call(table[index], (u16) counter); counter += 0xC0;
++count;` the call's own reads come first and the bumps are plain statements after it: the same program, as the
bumps touch only locals the call cannot see (none is address-taken and none appears among the other arguments).

`variants` finds `T = EXPR;` followed by updates of other locals (`x += K;`, `++x;`, `x = expression of locals;`) and then
a call statement with `T` as a plain argument that no later statement reads before assigning it again, EXPR reading only
locals, literals and side-effect-free `inline` helpers: the call is moved up to the assignment's place with EXPR in
`T`'s argument slot and the updates follow it. One child per site and one with every site (KMC GCC 2.7.2, `-G0 -mips3
-mgp32 -mfp32 -O2`: two of the three loops of a mixing function, 1560 -> 1355 one loop, 1150 both). The ordering reading
is from sched.c; the judge decides each child.
"""
import re

from .csource import _blank
from .integer_repair_support import IDENT, INTEGER, _address_taken, edit, view
from .line_scan import lines

FAMILY = 'call_arg_late_update'
FAMILIES = (FAMILY,)
LIMIT = 8
GAP = 6  # update statements between the staged local and the call
STAGE = re.compile(rf'^(?P<indent>[ \t]*)(?P<temp>{IDENT})\s*=\s*(?P<expr>[^;{{}}=]*?)\s*;\s*$')
UPDATE = re.compile(rf'^[ \t]*(?:(?P<dest>{IDENT})\s*(?:[-+*&|^]|<<|>>)?=(?!=)\s*(?P<value>[^;{{}}]*?)|'
                    rf'(?:\+\+|--)\s*(?P<pre>{IDENT})|(?P<post>{IDENT})\s*(?:\+\+|--))\s*;\s*$')
CALL = re.compile(rf'^(?P<indent>[ \t]*)(?P<callee>{IDENT})\s*\((?P<args>[^;{{}}]*)\)\s*;\s*$')
TYPE_WORDS = frozenset('u8 u16 u32 s8 s16 s32 int short char unsigned signed long'.split())
KEYWORDS = frozenset('if else for while do return break continue goto switch case sizeof'.split())
PURE_HELPER = re.compile(rf'(?m)^[ \t]*(?:inline\s+static|static\s+inline)\s+{INTEGER}\s+(?P<name>{IDENT})\s*\([^)]*\)\s*\{{(?P<body>[^{{}}]*)\}}')


def _names(text):
    """The identifiers in `text`, not the tail of a hex literal (`0xC0` has no `xC0`)."""
    return re.findall(rf'(?<![\w.]){IDENT}', text)


def _args(text):
    parts, depth, start = [], 0, 0
    for at, ch in enumerate(text):
        depth += (ch in '([') - (ch in ')]')
        if ch == ',' and depth == 0:
            parts.append((start, at))
            start = at + 1
    parts.append((start, len(text)))
    return parts


def variants(source, name):
    part = view(source, name)
    if not part or re.search(r'\b(?:asm|__asm__|volatile|goto)\b', part.body):
        return []
    head = part.clean[:part.opening]
    helpers = {m['name'] for m in PURE_HELPER.finditer(_blank(source)[:part.opening])
               if not re.search(r'\+\+|--|[^=!<>]=(?!=)', m['body'].replace('return', ''))}
    local_names = {m['name'] for m in re.finditer(rf'(?<![\w*])(?:{INTEGER}|void\s*\*|s\d+\s*\*|u\d+\s*\*)\s*\**\s*(?P<name>{IDENT})\s*[;=,\[]', part.clean[part.opening:part.end])}
    local_names |= set(_names(head[head.rfind('('):]))
    local_names = {n for n in local_names if not _address_taken(part.body, n)}
    body = lines(part, source)
    sites = []
    for i, line in enumerate(body):
        stage = STAGE.match(line.text)
        if not stage or stage['temp'] not in local_names:
            continue
        temp, expr = stage['temp'], stage['expr'].strip()
        names = set(_names(expr)) - TYPE_WORDS
        if not expr or temp in names or not names <= local_names | helpers:
            continue
        updates, call = [], None
        for j in range(i + 1, min(len(body), i + 2 + GAP)):
            text = body[j].text
            if re.search(r'[{}]|\blabel\b', text):
                break
            hit = CALL.match(text)
            if hit and hit['callee'] not in KEYWORDS and hit['callee'] not in local_names:
                call = (j, hit)
                break
            upd = UPDATE.match(text)
            if not upd:
                break
            written = upd['dest'] or upd['pre'] or upd['post']
            value = upd['value'] or ''
            if written not in local_names or written == temp or not set(_names(value)) - TYPE_WORDS <= local_names | helpers:
                break
            updates.append((j, written))
        if call is None or not updates:
            continue
        j, hit = call
        args = hit['args']
        spans = _args(args)
        slots = [k for k, (a, b) in enumerate(spans) if args[a:b].strip() == temp]
        if len(slots) != 1 or len(re.findall(rf'(?<![\w.>]){temp}\b', args)) != 1:
            continue
        others = ' '.join(args[a:b] for k, (a, b) in enumerate(spans) if k != slots[0])
        if {w for _, w in updates} & set(_names(others)):
            continue
        later = re.compile(rf'(?<![\w.>]){re.escape(temp)}\b').search(part.clean, body[j].end, part.end)
        if later and not re.match(r'\s*=(?!=)', part.clean[later.end():]):
            continue
        sites.append((i, j, [u for u, _ in updates], temp, expr, args, spans[slots[0]]))
    if not sites:
        return []

    def build(chosen):
        edits = []
        for i, j, updates, temp, expr, args, (a, b) in chosen:
            call = body[j].source
            call_hit = CALL.match(body[j].text)
            wrapped = expr if re.fullmatch(rf'{IDENT}|\w+|[\w ]+\([^()]*\)|\(\s*[\w ]+\)\s*\w+', expr) else f'({expr})'
            new_args = args[:a] + args[a:b].replace(temp, wrapped) + args[b:]
            new_call = call[:call_hit.start('args')] + new_args + call[call_hit.end('args'):]
            moved = [body[u].source for u in updates]
            block = '\n'.join([new_call] + moved) + '\n'
            edits.append((body[i].start, body[j].end, block))
        return edit(source, edits)

    results = []
    for chosen in ([sites] if len(sites) > 1 else []) + [[site] for site in sites]:
        text = build(chosen)
        if text != source and (FAMILY, text) not in results:
            results.append((FAMILY, text))
        if len(results) >= LIMIT:
            break
    return results


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name'), 'order': 70}  # the registry: no caller wiring (registry.py)

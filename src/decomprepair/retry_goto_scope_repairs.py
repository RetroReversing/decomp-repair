"""A retry `goto` that leaves its loop, pinned in a one-shot `do { } while (0)`, with m2c's skip-join written as an `if`.

m2c writes a search loop that restarts the outer attempt when a candidate is too close (a rejection loop: pick a
random entry, compare it to every slot except the player's own, start again when one is within a distance) as

    if ((V == CUR)) { T = V + 1; goto NEXT; }
    T = V + 1;
    if (!(!(COND))) goto RETRY;
    NEXT:
    V = T;
    if (T >= LIMIT) break;

GCC 2.7.2 (KMC, N64) turns that into a `bne` over the call with a `j` and the increment folded into `V`, so the loop
test reads the sign-extended `V` and the increment lands in the slot of the jump. The target's loop has the shape of
the ordinary `for` body: `beql V, CUR` whose slot is the increment, the call, `bc1t RETRY` with the increment in its
slot, one `move V, T`, and the test on the temporary. That needs two changes together, and neither helps alone
(475 -> 480 for the `if` form, 475 for the pinned goto alone):

    if (V != CUR) { if (COND) { do { goto RETRY; } while (0); } }
    T = V + 1;
    V = T;

Why the pair works is a hypothesis, not read from the compiler: the `do { } while (0)` may leave loop notes behind
that make `goto RETRY` look like a branch out of the loop it sits in, which reorg.c's `mostly_true_jump` would rate
"highly unlikely", so the delay-slot filler would take the following instruction for the beql's slot instead of
hoisting the shift into it. Only the matching result is evidenced. A 154-instruction
function matched this way, 475 -> 0, `gcc-2.7.2-kmc -G0 -mips3 -mgp32 -mfp32 -O2` (COMPILER_MATCHING_LEARNINGS.md).

Three proposals: the `if` form with the pinned goto (the exact child), the `if` form alone, and the pinned goto alone
for every backward `goto` that stands in a loop (a label defined earlier in the function). A join label other gotos also
reach stays in place, before the copy. The step may be any
constant (`V - 1`, `V + 0x10`) as long as both arms use the same one. A candidate for the exact
judge, never a verdict. Only MIPS is proposed (the GCC delay-slot filler)."""
import re

from .integer_repair_support import IDENT, edit, view

FAMILIES = ('retry_goto_scope',)
LIMIT = 8


def _close(clean, start, left='(', right=')'):
    depth = 0
    for pos in range(start, len(clean)):
        depth += (clean[pos] == left) - (clean[pos] == right)
        if depth == 0:
            return pos + 1
    return None


def _unwrap(text):
    """`text` without the redundant parentheses that wrap all of it."""
    text = text.strip()
    while text.startswith('(') and _close(text, 0) == len(text):
        text = text[1:-1].strip()
    return text


def _top_level_equal(text):
    depth = 0
    for pos in range(len(text) - 1):
        depth += (text[pos] in '([') - (text[pos] in ')]')
        if depth == 0 and text[pos:pos + 2] == '==' and text[pos - 1:pos] not in '!<>=' and text[pos + 2:pos + 3] != '=':
            return pos
    return None


def _positive(condition):
    """`X` for m2c's `!(!(X))`, else the condition as written."""
    text = condition.strip()
    for _ in range(2):
        if not text.startswith('!'):
            return condition.strip()
        rest = text[1:].lstrip()
        if not rest.startswith('(') or _close(rest, 0) != len(rest):
            return condition.strip()
        text = rest[1:-1].strip()
    return text


def _skip_joins(part):
    """(start, end, edited text) for each skip-join of the shape above."""
    clean, source = part.clean, part.source
    found = []
    for guard in re.finditer(r'\bif\s*\(', clean[part.opening:part.end]):
        at = part.opening + guard.start()
        paren = part.opening + guard.end() - 1
        paren_end = _close(clean, paren)
        if not paren_end:
            continue
        condition = _unwrap(clean[paren + 1:paren_end - 1])
        split = _top_level_equal(condition)
        if split is None:
            continue
        var, current = condition[:split].strip(), condition[split + 2:].strip()
        if not re.fullmatch(IDENT, var):
            continue
        body = re.compile(rf'\s*\{{\s*(?P<t>{IDENT})\s*=\s*{re.escape(var)}\s*(?P<s>[-+]\s*(?:0[xX][0-9A-Fa-f]+|\d+))\s*;\s*goto\s+(?P<n>{IDENT})\s*;\s*\}}\s*'
                          ).match(clean, paren_end)
        if not body:
            continue
        temp, label = body['t'], body['n']
        step = re.sub(r'\s+', ' ', body['s'].replace('+', '+ ', 1).replace('-', '- ', 1)).strip()
        again = re.compile(rf'{re.escape(temp)}\s*=\s*{re.escape(var)}\s*{re.escape(body["s"][0])}\s*'
                           rf'{re.escape(body["s"][1:].strip())}\s*;\s*if\s*\(').match(clean, body.end())
        if not again:
            continue
        retry_open = again.end() - 1
        retry_close = _close(clean, retry_open)
        tail = re.compile(rf'\s*goto\s+(?P<l>{IDENT})\s*;\s*{re.escape(label)}\s*:\s*{re.escape(var)}\s*=\s*{re.escape(temp)}\s*;'
                          ).match(clean, retry_close) if retry_close else None
        uses = len(re.findall(rf'\b{re.escape(label)}\b', clean[part.opening:part.end])) if tail else 0
        if uses < 2:
            continue
        shared = uses > 2  # other gotos jump to the join too: the label stays where the join was
        # the retry label must be defined earlier: this is the backward goto that leaves the loop
        if not re.search(rf'(?m)(?:^|[;{{}}])\s*{re.escape(tail["l"])}\s*:', clean[part.opening:at]):
            continue
        pad = re.match(r'[ \t]*', source[source.rfind('\n', 0, at) + 1:at])[0]
        retry = _positive(source[retry_open + 1:retry_close - 1])
        found.append((at, tail.end(), tail['l'], retry, current, var, temp, pad, step, label if shared else None))
    return found


def _restructured(part):
    out = []
    for at, end, label, retry, current, var, temp, pad, step, shared in _skip_joins(part):
        text = (f'if ({var} != {current})\n{pad}{{\n{pad}  if ({retry}) {{ do {{ goto {label}; }} while (0); }}\n{pad}}}\n'
                f'{pad}{temp} = {var} {step};\n{pad}' + (f'{shared}:\n{pad}' if shared else '') + f'{var} = {temp};')
        plain = text.replace(f'{{ do {{ goto {label}; }} while (0); }}', f'goto {label};')
        out.append((edit(part.source, [(at, end, text)]), edit(part.source, [(at, end, plain)])))
    return out


def _wraps(source, name):
    part = view(source, name)
    if not part:
        return []
    out = []
    for jump in re.finditer(rf'\bgoto\s+(?P<l>{IDENT})\s*;', part.clean[part.opening:part.end]):
        at = part.opening + jump.start()
        if not re.search(rf'(?m)(?:^|[;{{}}])\s*{re.escape(jump["l"])}\s*:', part.clean[part.opening:at]):
            continue
        before = part.clean[:at].rstrip()
        if re.search(r'\bdo\s*\{$', before):
            continue
        unbraced = before.endswith(')') or re.search(r'\belse$', before)
        wrapped = f'do {{ goto {jump["l"]}; }} while (0);'
        out.append(edit(source, [(at, part.opening + jump.end(), f'{{ {wrapped} }}' if unbraced else wrapped)]))
    return out


def variants(source, name, arch='mips', asm='', header=''):
    if arch != 'mips':
        return []
    part = view(source, name)
    if not part:
        return []
    out = []
    for wrapped, plain in _restructured(part):
        out += [wrapped, plain]
    out += _wraps(source, name)
    seen, unique = set(), []
    for text in out:
        if text != source and text not in seen:
            seen.add(text)
            unique.append((FAMILIES[0], text))
    return unique[:LIMIT]

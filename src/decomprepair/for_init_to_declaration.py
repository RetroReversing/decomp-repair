"""A loop counter's start written in its declaration, shared by the loops of the arms that count with it.

m2c and a hand rewrite write `for (i = 0; ...)` in each arm of an `if`/`else`. The game often initialised the counter
where it declared it (`u32 i = 0;`, then `for (; ...)`): the register is cleared once, above the first branch, after the
locals initialised before it. On a 129-instruction N64 table insertion with one loop per arm (SN64 GCC 2.8.1,
`-G0 -mips3 -O2`) this was 360 -> 140 from the clean rewrite; the target clears the counter's saved register in the
prologue, ahead of the other register saves. Declared before the other initialised local it was worse (the clearing
order is the declaration order), so both places are offered.

Only when every loop that starts the counter is in its own arm (never after or inside another), and nothing else names
the counter before the last of them ends, so each loop still starts from the same value. Children: the initialiser in
the declaration where it stands, and with that declaration moved below the last initialised one.
"""
import re

from .integer_repair_support import INTEGER, NUMBER, _address_taken, edit, view
from .pattern_repairs import close

FAMILY = 'for_init_to_declaration'
FAMILIES = (FAMILY,)
LIMIT = 8


def variants(source, name):
    part = view(source, name)
    if not part:
        return []
    body = part.clean[part.opening:part.end]
    if re.search(r'\b(?:goto|switch)\b', body):
        return []
    out = []
    for decl in re.finditer(rf'(?<=[;{{}}])\n(?P<indent>[ \t]*)(?P<type>{INTEGER})\s+(?P<name>[A-Za-z_]\w*)\s*;', body):
        local = decl['name']
        if _depth(body, decl.start('type')) != 1 or _address_taken(body, local):
            continue
        loops = _loops(body, local)
        if not loops:
            continue
        values = {value for _, _, _, _, value in loops}
        if len(values) != 1 or not _separate(body, loops):
            continue
        spans = [(start, end) for start, end, _, _, _ in loops]
        last = max(end for _, end in spans)
        others = [hit.start() for hit in re.finditer(rf'(?<![\w.])(?<!->){re.escape(local)}\b', body)
                  if hit.start() != decl.start('name') and not any(a <= hit.start() < b for a, b in spans)]
        if any(at < last for at in others):
            continue
        cleared = [(part.opening + a, part.opening + b, '') for _, _, a, b, _ in loops]
        value = values.pop()
        initialised = f'{decl["type"]} {local} = {value};'
        out.append((FAMILY, edit(source, cleared + [(part.opening + decl.start('type'),
                                                     part.opening + decl.end(), initialised)])))
        below = _after_last_initialised(body, decl.end())
        if below is not None:
            out.append((FAMILY, edit(source, cleared + [
                (part.opening + decl.start(), part.opening + decl.end(), ''),
                (part.opening + below, part.opening + below, f'\n{decl["indent"]}{initialised}')])))
        if len(out) >= LIMIT:
            break
    return out


def _loops(body, local):
    """[(loop start, loop end, initialiser start, initialiser end, value)] of the `for`s that start `local`."""
    found = []
    for hit in re.finditer(r'\bfor\s*\(', body):
        init = re.compile(rf'\s*(?P<init>{re.escape(local)}\s*=\s*(?P<value>-?{NUMBER}))\s*;').match(body, hit.end())
        if not init:
            continue
        after = close(body, hit.end() - 1)
        if after is None:
            return []
        opened = re.compile(r'\s*\{').match(body, after)
        end = close(body, opened.end() - 1, '{', '}') if opened else None
        if end is None:
            return []
        found.append((hit.start(), end, init.start('init'), init.end('init'), init['value']))
    return found


def _depth(body, at):
    return body.count('{', 0, at) - body.count('}', 0, at)


def _separate(body, loops):
    """Whether no path runs two of the loops, or one of them twice."""
    for hit in re.finditer(r'\b(?:for|while)\s*\(|\bdo\s*\{', body):
        if hit[0].startswith('do'):
            end = close(body, hit.end() - 1, '{', '}')
        else:
            after = close(body, hit.end() - 1)
            opened = re.compile(r'\s*\{').match(body, after) if after else None
            end = close(body, opened.end() - 1, '{', '}') if opened else after
        if end is not None and any(hit.start() < start < end for start, *_ in loops):
            return False
    arms = _arms(body)
    starts = [start for start, *_ in loops]
    return all(any((a[0] <= x < a[1] and b[0] <= y < b[1]) for a, b in arms)
               for index, x in enumerate(starts) for y in starts[index + 1:])


def _arms(body):
    """[((then start, then end), (else start, else end))] of every braced `if` with an `else`."""
    pairs = []
    for hit in re.finditer(r'\bif\s*\(', body):
        found = _if(body, hit.start())
        if found and found[1]:
            pairs.append((found[0], found[1]))
    return pairs


def _if(body, at):
    """((then span), (else span) or None) of the braced `if` at `at`; None when an arm has no braces."""
    head = re.compile(r'if\s*\(').match(body, at)
    after = close(body, head.end() - 1) if head else None
    opened = re.compile(r'\s*\{').match(body, after) if after else None
    end = close(body, opened.end() - 1, '{', '}') if opened else None
    if end is None:
        return None
    then = (opened.end() - 1, end)
    other = re.compile(r'\s*else\b\s*').match(body, end)
    if not other:
        return then, None
    if body.startswith('{', other.end()):
        stop = close(body, other.end(), '{', '}')
        return (then, (other.end(), stop)) if stop else None
    inner = _if(body, other.end())
    return (then, (other.end(), (inner[1] or inner[0])[1])) if inner else None


def _after_last_initialised(body, after):
    """Where the last initialised declaration that follows at the function's top ends, or None."""
    found, at = None, after
    declaration = re.compile(rf'\s*(?:{INTEGER}|f32|f64|float|double)\s+\**\s*[A-Za-z_]\w*\s*(?P<init>=[^;{{}}]*)?;')
    while True:
        hit = declaration.match(body, at)
        if not hit:
            return found
        at = hit.end()
        if hit['init']:
            found = at


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name'), 'order': 40}

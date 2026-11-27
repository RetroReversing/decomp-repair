"""m2c's character-table ladder, written back: four spellings it leaves around a range ladder ending in a switch.

    do {
        c = *src;
        if (c >= 0x42) { goto block_3; }
        if ((u32) ((c - 0x10) & 0xFF) < 0xA) { *dst = c + 0x20; }
        else if (c != 0 || i >= (n - 1)) {
            switch (*src) { case 0x38: block_3: *dst = '*'; break; ... }     // no `default:`
        } else { *dst = ' '; }
        dst += 1; i += 1; src += 1;
    } while (i < n);

* `goto_case_else_arm`: the early `if` that jumps into a case of a later switch is `if (c) { <the case> } else <rest>`.
* `lockstep_byte_cursor_index`: pointers copied from a base and stepped beside the counter are `base[i]`.
* `switch_fallback_default`: the switch's `default:` and the `else` beside it are one block (m2c prints a `default:`
  label in the `else`, which a draft that only compiles C cannot keep): copy it into the switch, with and without
  the `if` written the other way round. The added `default:` changes what an unmatched value does, so only the exact
  judge says it was the original's.
* `masked_range_bounds`: `(u32) ((c - K) & 0xFF) < N` on a `u8` is `c >= K && c <= K + N - 1`.

An N64 text-conversion function of 89 instructions (SN GCC 2.8.1, `-G0 -mips3 -O2`) was exact only with all four from
its m2c draft (7170 -> 0 by hand); `m2c_ladder_combined` makes them at once. A candidate rewrite; the exact judge
decides.
"""
import re

from .branch_polarity_repairs import negate_any
from .integer_repair_support import IDENT, edit, view
from .pattern_repairs import close

GOTO_CASE = 'goto_case_else_arm'
CURSOR = 'lockstep_byte_cursor_index'
FALLBACK = 'switch_fallback_default'
BOUNDS = 'masked_range_bounds'
COMBINED = 'm2c_ladder_combined'
FAMILIES = (GOTO_CASE, CURSOR, FALLBACK, BOUNDS, COMBINED)

_SIMPLE = r'[^{}:?]*?;'  # statements with no block, label or `case`
_NUMBER = r'(?:0[xX][0-9A-Fa-f]+|\d+)'
_UNSAFE = re.compile(r'\b(?:goto|break|continue|return|case|default)\b')


def _space(clean, at):
    return re.compile(r'\s*').match(clean, at).end()


def _if_chain_end(clean, at):
    """The index after the braced `if (..) {..} else if (..) {..} else {..}` statement that starts at `at`, or None."""
    while True:
        head = re.compile(r'if\s*\(').match(clean, at)
        if not head:
            return None
        condition = close(clean, head.end() - 1)
        if not condition:
            return None
        block = _space(clean, condition)
        if not clean.startswith('{', block):
            return None
        end = close(clean, block, '{', '}')
        if not end:
            return None
        other = re.compile(r'\s*else\b\s*').match(clean, end)
        if not other:
            return end
        at = other.end()
        if clean.startswith('{', at):
            return close(clean, at, '{', '}')


def _switches(clean, start, end):
    """(keyword, opening brace, index after the closing brace) of each switch between `start` and `end`."""
    for hit in re.compile(r'\bswitch\s*\(').finditer(clean, start, end):
        condition = close(clean, hit.end() - 1)
        if not condition:
            continue
        brace = _space(clean, condition)
        if clean.startswith('{', brace) and (after := close(clean, brace, '{', '}')):
            yield hit.start(), brace, after


def _only_leaves(clean, at, end):
    """Whether only closing braces and skipped `else` arms lie between `at` and `end`."""
    while at < end:
        at = _space(clean, at)
        if at >= end:
            break
        if clean[at] == '}':
            at += 1
            continue
        other = re.compile(r'else\b\s*').match(clean, at)
        if not other:
            return False
        at = other.end()
        if clean.startswith('{', at):
            at = close(clean, at, '{', '}')
        else:
            at = _if_chain_end(clean, at)
        if not at:
            return False
    return True


def _goto_case(source, name):
    part = view(source, name)
    if not part:
        return None
    clean = part.clean
    pattern = re.compile(r'\bif\s*\(')
    for head in pattern.finditer(clean, part.opening + 1, part.end):
        condition = close(clean, head.end() - 1)
        if not condition:
            continue
        jump = re.compile(rf'\s*\{{\s*goto\s+(?P<label>{IDENT})\s*;\s*\}}').match(clean, condition)
        if not jump:
            continue
        label = jump['label']
        if len(re.findall(rf'\bgoto\s+{label}\b', clean[part.opening:part.end])) != 1:
            continue
        rest = _space(clean, jump.end())
        rest_end = _if_chain_end(clean, rest)
        if not rest_end:
            continue
        target = re.compile(rf'\bcase\s+[^:;{{}}]+:\s*(?P<l>{label}\s*:)(?P<run>{_SIMPLE}*?)\s*\bbreak\s*;').search(
            clean, rest, rest_end)
        if not target or _UNSAFE.search(target['run']) or not target['run'].strip():
            continue
        owner = [s for s in _switches(clean, rest, rest_end) if s[1] < target.start() < s[2]]
        if not owner:
            continue
        after = max(owner, key=lambda s: s[1])[2]
        # the case's `break` leaves the switch, and nothing but the rest of the chain follows it
        if not _only_leaves(clean, after, rest_end):
            continue
        statements = source[target.start('run'):target.end('run')].strip()
        arm = f'{{ {statements} }} else '
        return edit(source, [(condition, rest, ' ' + arm), (target.start('l'), target.end('l'), '')])
    return None


def _declared(clean, part, name):
    """The declared type text of `name`, as a parameter or a local, with its stars."""
    hit = re.search(rf'(?:[(,]\s*|(?:^|[;{{}}])\s*)(?P<type>(?:(?:unsigned|signed|const)\s+)?{IDENT}(?:\s*\*+\s*|\s+))'
                    rf'{re.escape(name)}\s*(?=[,);=\[])', clean)
    return ''.join(hit['type'].split()) if hit else None


def _cursor(source, name):
    part = view(source, name)
    if not part:
        return None
    clean = part.clean
    body = clean[part.opening:part.end]
    edits, used = [], set()
    for step in re.finditer(rf'(?<![\w.>])(?P<v>{IDENT})\s*\+=\s*1\s*;', body):
        v = step['v']
        kind = _declared(clean, part, v)
        if not kind or not kind.endswith('*') or v in used:
            continue
        inits = list(re.finditer(rf'(?<![\w.>*]){v}\s*=\s*(?P<base>{IDENT})\s*;', body))
        if len(inits) != 1 or _declared(clean, part, inits[0]['base']) != kind:
            continue
        base = inits[0]['base']
        if re.search(rf'(?<![\w.>]){base}\s*(?:[-+*/|&^]?=(?!=)|\+\+|--)|(?:\+\+|--|(?<![&\w)\]])&)\s*{base}\b', body):
            continue
        # the counter: stepped in the same run of `x += 1;` statements as the cursor, and started at zero
        run = next((r for r in re.finditer(rf'(?:\b{IDENT}\s*\+=\s*1\s*;\s*)+', body)
                    if r.start() <= step.start() < r.end()), None)
        if not run:
            continue
        counter = None
        for other in re.findall(rf'\b({IDENT})\s*\+=\s*1', run[0]):
            other_kind = _declared(clean, part, other)
            if (other != v and other_kind and '*' not in other_kind
                    and len(re.findall(rf'(?<![\w.>]){other}\s*(?:[-+*/|&^]?=(?!=)|\+\+|--)', body)) == 2
                    and re.search(rf'(?<![\w.>]){other}\s*=\s*0\s*;', body)):
                counter = other
                break
        if not counter:
            continue
        # every other use is `*v` inside the loop the steps close, after the counter was set to zero
        loops = [(d.end() - 1, close(body, d.end() - 1, '{', '}')) for d in re.finditer(r'\bdo\s*\{', body)]
        loops = [(a, b) for a, b in loops if b and a < run.start() < b]
        if not loops:
            continue
        opening, _ = max(loops)
        zero = re.search(rf'(?<![\w.>]){counter}\s*=\s*0\s*;', body).start()
        reads = list(re.finditer(rf'\*\s*{v}\b(?!\s*[\[(.]|\s*->)', body))
        reads = [r for r in reads if not re.search(rf'(?:^|[;{{}}])\s*{IDENT}\s*$', body[:r.start()])]
        declaration = re.search(rf'(?m)^[ \t]*(?:(?:unsigned|signed|const)\s+)?{IDENT}\s*\*+\s*{v}\s*;[ \t]*\n', body)
        if not declaration or not reads or zero > opening:
            continue
        if any(not opening < r.start() < run.start() for r in reads):
            continue
        if len(re.findall(rf'(?<![\w.>]){v}\b', body)) != len(reads) + 3:  # declaration, init, step
            continue
        used.add(v)
        offset = part.opening
        edits.append((offset + declaration.start(), offset + declaration.end(), ''))
        for spot in (inits[0], step):
            edits.append((offset + spot.start(), offset + spot.end(), ''))
        edits += [(offset + r.start(), offset + r.end(), f'{base}[{counter}]') for r in reads]
    if not edits:
        return None
    return re.sub(r'(?m)^[ \t]+\n(?=[ \t]*\S)', '', edit(source, edits))


def _fallbacks(source, name):
    """[default added, default added and the `if` turned round] for the first `if (..) {.. switch} else {S}` (only the
    second when the switch has that default already)."""
    part = view(source, name)
    if not part:
        return []
    clean = part.clean
    for head in re.compile(r'\bif\s*\(').finditer(clean, part.opening + 1, part.end):
        condition = close(clean, head.end() - 1)
        if not condition:
            continue
        block = _space(clean, condition)
        if not clean.startswith('{', block) or not (then_end := close(clean, block, '{', '}')):
            continue
        other = re.compile(rf'\s*else\s*\{{(?P<s>{_SIMPLE}(?:\s*{_SIMPLE})*)\s*\}}').match(clean, then_end)
        if not other or _UNSAFE.search(other['s']):
            continue
        last = [s for s in _switches(clean, block, then_end) if not clean[s[2]:then_end - 1].strip()]
        if not last:
            continue
        _, brace, after = last[0]
        # a switch that already ends in the same `default:` (a draft that kept it) still takes the turned-round `if`
        own = re.search(r'\bdefault\s*:(?P<d>[^{}]*?)\bbreak\s*;\s*\}$', clean[brace:after])
        if re.search(r'\bdefault\s*:', clean[brace:after]):
            if not own or own['d'].split() != other['s'].split():
                continue
        if re.search(rf'(?:^|[;{{}}])\s*(?:{IDENT}\s+)+\**\s*{IDENT}\s*(?:=|;|\[)', other['s']):
            continue  # a declaration would need its own block
        statements = source[other.start('s'):other.end('s')].strip()
        # the switch's last case must leave on its own, or it would fall into the added default
        if not own and not re.search(r'(?:\bbreak|\breturn\b[^;{}]*|\bcontinue)\s*;\s*$', clean[brace:after - 1]):
            continue
        added = (after - 1, after - 1, '' if own else f'default: {statements} break; ')
        results = [] if own else [edit(source, [added])]
        inverted = negate_any(source[head.end():condition - 1])
        if inverted:
            then = edit(source, [added])[block:then_end + len(added[2])]
            results.append(source[:head.end()] + f'{inverted}) {{ {statements} }} else {then}' + source[other.end():])
        return results
    return []


def _bounds(source, name):
    part = view(source, name)
    if not part:
        return None
    clean = part.clean
    pattern = re.compile(rf'\(\s*u32\s*\)\s*\(\s*(?:\(\s*(?P<v>{IDENT})\s*-\s*(?P<k>{_NUMBER})\s*\)\s*&\s*0[xX][Ff][Ff]'
                         rf'|(?P<w>{IDENT})\s*-\s*(?P<j>{_NUMBER}))\s*\)\s*<\s*(?P<n>{_NUMBER})[uU]?')
    edits = []
    for hit in pattern.finditer(clean, part.opening + 1, part.end):
        var = hit['v'] or hit['w']
        # unmasked, the subtraction is done as a signed int and only the cast makes it unsigned: the same for a u8
        if _declared(clean, part, var) not in ('u8', 'unsignedchar'):
            continue
        low, span = int(hit['k'] or hit['j'], 0), int(hit['n'], 0)
        if low < 1 or span < 2 or low + span > 256:
            continue
        written = hit['k'] or hit['j']
        number = (lambda value: f'0x{value:X}') if written.lower().startswith('0x') else str
        text = f'{var} >= {written} && {var} <= {number(low + span - 1)}'
        before, after = clean[:hit.start()].rstrip(), clean[hit.end():].lstrip()
        if not (before.endswith('(') and after.startswith(')')):
            text = f'({text})'
        edits.append((hit.start(), hit.end(), text))
    return edit(source, edits) if edits else None


def variants(source, name):
    results = []
    for family, step in ((GOTO_CASE, _goto_case), (CURSOR, _cursor), (BOUNDS, _bounds)):
        if (child := step(source, name)) and child != source:
            results.append((family, child))
    results += [(FALLBACK, child) for child in _fallbacks(source, name)]
    current, applied = source, 0
    for step in (_goto_case, _cursor, _bounds, lambda s, n: (_fallbacks(s, n) or [None])[-1]):
        if child := step(current, name):
            current, applied = child, applied + 1
    if applied > 1:
        results.insert(0, (COMBINED, current))
    return results


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name')}

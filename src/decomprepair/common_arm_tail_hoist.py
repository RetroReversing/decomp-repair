"""The statement both arms of an if/else end with, written once after the test.

    if (!(flags & 8)) { word[2] = 1; mode = 0; } else { mode = 0; }        if (!(flags & 8)) { word[2] = 1; } mode = 0;

m2c writes the join of a state machine's arms into each arm (and `goto` target), so an arm that sets a value on the
way and one that only sets it come out as two full copies. The game wrote the common statement once. GCC 2.7.2's
cross-jumping merges the tails after register allocation either way, but only when the label it has to merge at was
there before the pass: the two spellings differ in which branch becomes the conditional's skip, so the `beql` over the
single store is laid out one way for the hoisted form and the other way for the copies (the jump table's second and
third arms of a 417-instruction input handler: two `beql` targets, the last 20 of a function matched otherwise).

Offered for `if (C) { ...; T; } else { T; }` with braced arms and identical last statements (spacing ignored), where the
then arm has more than the tail: one child per if. A candidate rewrite; the exact judge decides.

`chain_tail_hoist` does the same for a whole exhaustive if / `else if` / `else` chain, nested chains included, whose
every leaf ends with the same statement: m2c copies a loop's `n++;` into each arm, where the game wrote it once after
the chain (a 92-instruction table fill, KMC GCC 2.7.2 `-O1`: 600 -> 180 from this alone, then 0 with two other
families). It moves all the copies at once, since removing only some changes what the others do.
"""
import re

from .integer_repair_support import edit, view
from .pattern_repairs import close

FAMILY = 'common_arm_tail_hoist'
CHAIN = 'chain_tail_hoist'
FAMILIES = (FAMILY, CHAIN)
_IF = re.compile(r'\bif\s*\(')


def _last(block):
    """(start, end) of the last statement of a block body `{ ... }` given without its braces, when it is one simple
    statement; else None."""
    stripped = block.rstrip()
    if not stripped.endswith(';'):
        return None
    start = max(stripped.rfind(';', 0, -1), stripped.rfind('{'), stripped.rfind('}')) + 1
    statement = stripped[start:].strip()
    if not statement or re.search(r'[{}]|\b(?:if|else|for|while|do|switch|case|default|return|break|continue|goto)\b', statement):
        return None
    return start + (len(stripped[start:]) - len(stripped[start:].lstrip())), len(stripped)


def _chain(clean, at):
    """(end, [(open, close) of every braced arm]) of an exhaustive if/else chain starting at `at`, else None."""
    arms = []
    while True:
        head = _IF.match(clean, at)
        shut = close(clean, head.end() - 1) if head else None
        then = re.compile(r'\s*\{').match(clean, shut) if shut else None
        end = close(clean, then.end() - 1, '{', '}') if then else None
        if not end:
            return None
        arms.append((then.end(), end - 1))
        other = re.compile(r'\s*else\b\s*').match(clean, end)
        if not other:
            return None
        at = other.end()
        if clean.startswith('{', at):
            end = close(clean, at, '{', '}')
            if not end:
                return None
            arms.append((at + 1, end - 1))
            return end, arms


def _leaves(clean, arm):
    """The spans of the statements that run last in an arm, following a chain that ends it; None when unknown."""
    start, end = arm
    body = clean[start:end].rstrip()
    if body.endswith('}'):
        for hit in _IF.finditer(clean, start, end):
            before = clean[start:hit.start()].rstrip()
            if before and before[-1] not in ';{}':
                continue
            if before.count('{') != before.count('}'):
                continue
            chain = _chain(clean, hit.start())
            if chain and chain[0] == start + len(body):
                spans = []
                for inner in chain[1]:
                    found = _leaves(clean, inner)
                    if found is None:
                        return None
                    spans += found
                return spans
        return None
    last = _last(clean[start:end])
    return [(start + last[0], start + last[1])] if last else None


def _chain_variants(source, part):
    clean = part.clean
    out = []
    for hit in _IF.finditer(clean, part.opening + 1, part.end):
        before = clean[:hit.start()].rstrip()
        if before[-1:] not in (';', '{', '}'):
            continue  # an `else if`, or the whole body of a test or loop
        chain = _chain(clean, hit.start())
        if not chain:
            continue
        end, arms = chain
        spans = []
        for arm in arms:
            found = _leaves(clean, arm)
            if found is None:
                break
            spans += found
        else:
            if len({re.sub(r'\s+', '', clean[a:b]) for a, b in spans}) != 1:
                continue
            a, b = spans[0]
            tail = source[a:b]
            names = set(re.findall(r'[A-Za-z_]\w*', clean[a:b]))
            if any(re.search(rf'\b[A-Za-z_]\w*[\s*]+{re.escape(n)}\s*(?:[;=,\[])', clean[hit.start():end])
                   for n in names):
                continue  # a name the chain declares itself would be out of scope after it
            indent = re.match(r'[ \t]*', source[source.rfind('\n', 0, hit.start()) + 1:])[0]
            edits = []
            for a, b in spans:
                line = source.rfind('\n', 0, a) + 1
                if not source[line:a].strip() and source[b:b + 1] == '\n':
                    a, b = line, b + 1
                edits.append((a, b, ''))
            edits.append((end, end, f'\n{indent}{tail}'))
            out.append((CHAIN, edit(source, edits)))
    return out


def variants(source, name):
    part = view(source, name)
    if not part:
        return []
    clean = part.clean
    out = []
    for hit in _IF.finditer(clean, part.opening + 1, part.end):
        shut = close(clean, hit.end() - 1)
        then = re.compile(r'\s*\{').match(clean, shut) if shut else None
        if not then:
            continue
        then_end = close(clean, then.end() - 1, '{', '}')
        other = re.compile(r'\s*else\s*\{').match(clean, then_end) if then_end else None
        if not other:
            continue
        else_end = close(clean, other.end() - 1, '{', '}')
        if not else_end:
            continue
        then_body = clean[then.end():then_end - 1]
        else_body = clean[other.end():else_end - 1]
        a, b = _last(then_body), _last(else_body)
        if not a or not b:
            continue
        tail = then_body[a[0]:a[1]]
        if re.sub(r'\s+', '', tail) != re.sub(r'\s+', '', else_body[b[0]:b[1]]) or not then_body[:a[0]].strip():
            continue
        if re.sub(r'\s+', '', else_body[:b[0]]):
            continue  # the else arm has more than the tail
        before = clean[:hit.start()].rstrip()
        if before[-1:] not in (';', '{', '}') and not re.search(r'\belse\Z', before):
            continue  # the `if` is the whole body of a test or loop: a statement after it would leave that body
        indent = re.match(r'[ \t]*', source[source.rfind('\n', 0, hit.start()) + 1:])[0]
        kept = source[then.end():then.end() + a[0]].rstrip()
        text = f'{source[hit.start():then.end()]}{kept}\n{indent}}}\n{indent}{source[then.end() + a[0]:then.end() + a[1]].strip()}'
        if before.endswith('else'):  # `else if`: the else gets the braces its two statements need
            text = f'{{\n{indent}{text}\n{indent}}}'
        out.append((FAMILY, edit(source, [(hit.start(), else_end, text)])))
    made = {text for _, text in out}
    return out + [child for child in _chain_variants(source, part) if child[1] not in made]


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name')}

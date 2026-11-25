"""A stray trailing argument `v + K` m2c passed a callee, dropped with the store of the same sum stepped in place.

m2c passes whatever the argument registers still held when it cannot tell a callee's arity. When the function had just
stored a counter's next value, `G = v + K;`, and that value was still in `$a3` at the call, m2c writes it as a fourth
argument: `G = v + 1; f(a, b, c, v + 1);` where the callee's matched definition takes three. `callee_arity_trim` drops
only plain names, so the evaluated `v + 1` stayed, and dropping it alone is not the game's code either: the target's
`addiu $a3, $a3, 1; sw $a3, G` is the counter advanced in place (`v++; G = v;`), the value in `$a3` only because the
variable was born there.

A 234-instruction N64 scene init (SN64 GCC 2.8.1 `-G0 -mips3 -O2 -mfp32`) needed one more edit with those two: m2c had
reused the counter's local for the entry test (`v = arg0->f; if (v == 0) { v = G; ... }`), which gives the counter two
sets (so sched.c's `birthing_insn_p` does not boost its load: the `lui` of `G` stays at the top of the block, as in the
target) but puts the entry test in the counter's register. With the in-place step the counter has its two sets
anyway, and the entry test written inline (`if (arg0->f == 0)`) gets a register of its own: 10 -> 0, where each edit
alone or in pairs scored 35, 240 or 560.

arity_drop_store_step
    For each callee whose matched definition (in `callees`) takes N parameters and is called with more, where the
    dropped arguments are side-effect free and at least one is not a plain name (plain names are
    `callee_arity_trim`'s): the call without them; then, for a dropped `v + K` (or `v - K`) that a statement before the
    call stores (`LHS = v + K;`) while `v` is read nowhere after that store, the store written as `v += K; LHS = v;`
    (`v++` for 1); then that child with an entry test inlined, when `v` was set just before an `if (v == 0)` /
    `if (v != 0)` / `if (v)` / `if (!v)` whose block assigns `v` before reading it and `v` is read nowhere after
    the block. A prototype in the source that declares more fixed parameters than the definition is trimmed with
    the call. A candidate rewrite; the judge decides."""
import re

from .callee_arity_trim import _arguments
from .csource import _blank, find
from .missing_call_argument_local import _definition
from .pattern_repairs import close as _close

FAMILY = 'arity_drop_store_step'
FAMILIES = (FAMILY,)
LIMIT = 6
IDENT = r'[A-Za-z_]\w*'
NUMBER = r'(?:0[xX][0-9A-Fa-f]+|\d+)[uUlL]*'
_PURE = re.compile(r'[\w\s.+\-*&|^<>\[\]~]*')
_STEP = re.compile(rf'({IDENT})\s*([+-])\s*({NUMBER})')


def _pure(text):
    """Side-effect free: names, numbers, member and index reads, arithmetic; no calls, casts or assignments."""
    text = text.strip()
    return bool(text) and _PURE.fullmatch(text) is not None and '++' not in text and '--' not in text \
        and not re.search(r'(?<![<>=!])=(?!=)', text)


def _mentions(clean, name, start, end):
    return re.search(rf'(?<![\w.>]){re.escape(name)}\b', clean[start:end]) is not None


def _statement_start(clean, at):
    return max(clean.rfind(';', 0, at), clean.rfind('{', 0, at), clean.rfind('}', 0, at)) + 1


def _indent(source, at):
    line = source.rfind('\n', 0, at) + 1
    return re.match(r'[ \t]*', source[line:])[0]


def _prototype_edits(source, clean, span, callee, params):
    """Edits trimming declarations of `callee` outside the function to the definition's parameter list."""
    edits = []
    for hit in re.finditer(rf'(?m)^[^\n;{{}}#]*\b{re.escape(callee)}\s*\(([^()]*)\)\s*;', clean):
        if span[0] <= hit.start() < span[1] or '...' in hit[1]:
            continue
        declared = [p for p in hit[1].split(',') if p.strip() and p.strip() != 'void']
        if len(declared) > len(params):
            edits.append((hit.start(1), hit.end(1), ', '.join(params) if params else 'void'))
    return edits


def _apply(source, edits):
    for start, end, text in sorted(edits, reverse=True):
        source = source[:start] + text + source[end:]
    return source


def _entry_inline(source, clean, body_start, store_at, var):
    """The edits writing `v = Y; if (v == 0) {` as `if (Y == 0) {` when the block assigns `v` before reading it."""
    assign = re.compile(rf'(?<![\w.>]){re.escape(var)}\s*=(?!=)\s*([^;]*);\s*if\s*\(\s*(!\s*)?'
                        rf'{re.escape(var)}\s*(?:([!=]=)\s*0\s*)?\)\s*{{')
    for hit in assign.finditer(clean, body_start, store_at):
        value = hit[1].strip()
        if not _pure(value) or _mentions(value, var, 0, len(value)):
            continue
        opening = hit.end() - 1
        end = _close(clean, opening, '{', '}')
        closing = None if end is None else end - 1
        if closing is None or closing < store_at:
            continue
        first = re.search(rf'(?<![\w.>]){re.escape(var)}\b', clean[opening:closing])
        if not first:
            continue
        after = clean[opening + first.end():closing]
        if not re.match(r'\s*=(?!=)', after):
            continue
        if _mentions(clean, var, closing, len(clean)):
            continue
        if hit[2] or hit[3] == '==':
            test = f'{value} == 0'
        elif hit[3] == '!=':
            test = f'{value} != 0'
        else:
            test = value
        semi = clean.index(';', hit.start())
        if_at = clean.index('if', semi)
        lparen = clean.index('(', if_at)
        rparen = clean.rindex(')', lparen, opening)
        return [(hit.start(), if_at, ''), (lparen + 1, rparen, test)]
    return None


def variants(source, name, callees=''):
    span = find(source, name)
    if not span or not callees:
        return []
    clean = _blank(source)
    head = re.search(r'\b' + re.escape(name) + r'\s*\([^{};]*\)\s*{', clean[span[0]:span[1]])
    if not head:
        return []
    opening = span[0] + head.end() - 1
    out = []
    for hit in re.finditer(rf'(?<![\w.>])({IDENT})\s*\(', clean[:span[1]]):
        if hit.start() < opening or hit[1] in ('if', 'while', 'for', 'switch', 'return', 'sizeof'):
            continue
        params = _definition(callees, hit[1])
        if params is None:
            continue
        params = [p.strip() for p in params if p.strip() and p.strip() != 'void']
        count = len(params)
        end = _close(clean, hit.end() - 1)
        if end is None or end > span[1]:
            continue
        close = end - 1
        inner = clean[hit.end():close]
        args = _arguments(inner)
        if len(args) <= count:
            continue
        dropped = [inner[a:b].strip() for a, b in args[count:]]
        if not all(_pure(d) for d in dropped) or all(re.fullmatch(IDENT, d) for d in dropped):
            continue
        cut = hit.end() + (args[count - 1][1] if count else 0)
        drop = [(cut, close, '')] + _prototype_edits(source, clean, span, hit[1], params)
        out.append((FAMILY, _apply(source, drop)))
        call_start = _statement_start(clean, hit.start())
        for text in dropped:
            step = _STEP.fullmatch(text)
            if not step:
                continue
            var, sign, amount = step[1], step[2], step[3]
            norm = re.sub(r'\s+', '', text)
            store = None
            for found in re.finditer(r'([^;{}]*?)=(?!=)([^;{}]*);', clean[opening:call_start]):
                left, right = found[1].strip(), re.sub(r'\s+', '', found[2])
                if right == norm and left != var and not left.endswith(('+', '-', '*', '/', '&', '|', '^', '<', '>',
                                                                        '!')):
                    store = (opening + found.start(), opening + found.end(), found[1].strip())
            if store is None:
                continue
            store_at = _statement_start(clean, store[0])
            while clean[store_at] in ' \t\n':
                store_at += 1
            later = clean[store[1]:cut] + clean[close:span[1]]
            if _mentions(later, var, 0, len(later)):
                continue
            bump = f'{var}++;' if sign == '+' and amount == '1' else f'{var}--;' if amount == '1' \
                else f'{var} {sign}= {amount};'
            indent = _indent(source, store_at)
            stepped = drop + [(store_at, store[1], f'{bump}\n{indent}{store[2]} = {var};')]
            out.append((FAMILY, _apply(source, stepped)))
            entry = _entry_inline(source, clean, opening + 1, store_at, var)
            if entry:
                out.append((FAMILY, _apply(source, stepped + entry)))
    seen, unique = set(), []
    for family, text in out:
        if text != source and text not in seen:
            seen.add(text)
            unique.append((family, text))
    return unique[:LIMIT]


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name', 'callees')}

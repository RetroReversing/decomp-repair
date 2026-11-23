"""A pointer local set from the loop counter at the top of a loop body, written into each arm that reads it.

m2c, and an agent keeping its output, write a table walk's per-iteration pointers as locals set first in the body:

    do {
        name = gTable[i].name;                 /* read in both arms of the `if` below */
        code = gTable[i].code;
        submit(..., i, &gRaw[i]);
        if (wait() == 5) {
            gTable[i].used = 0;
            j = 15; do { name[j] = ' '; } while (--j >= 0);  name[16] = 0;
            ...
        } else {
            gTable[i].used = 1;
            decode(name, gRaw[i].name, 16);
            decode(code, &gRaw[i].codeByte, 4);
        }
        i++;
    } while (i < 16);

GCC 2.7.2's loop.c (`strength_reduce`) records a giv for every insn that computes a value from the counter, in the order
it meets them, and it *prepends* each to the biv's list: the preheader's initial values and the increments at the loop's
end are emitted in the reverse of that order. A local set at the top is met first, so its register is initialised and
stepped last; the target (written with the expression at each use) had the name pointer and the code pointer ahead of the
flag pointer, in the order the arms use them (hypothesis from loop.c; the judge decides). The same rule keeps the
local honest where a *store through it at a constant offset* needs a register of its own: `combine_givs_p` /
`express_from` derive another giv's address only from a giv whose additive part is a literal (`g1->add_val` must be a
CONST_INT), and a symbol-based pointer's is not, so `gTable[i].name[16] = 0` written as an expression is addressed from
the counter's own multiple (`lui $at; addu $at,$at,$s3; sb`) instead of `0x10($s1)`. A giv local that is *set in the
store's own basic block* is replaceable even when that block is not run every iteration (loop.c `record_giv`:
`last_use_this_basic_block`), so the offset store keeps a one-use local set just before it, and every other read is the
expression. Neither half alone changes the score: a 265-instruction save-slot scan (KMC GCC 2.7.2, `-O2 -G0 -mips3`) with
the pointers indexed by the counter stood at 195 (six rows of preheader and increment order, three registers); the
expressions alone gave 1775, the one-use locals alone 195, both 0.

The child (`loop_giv_local_arm_inline`) removes each qualifying `P = E;` and the declaration of `P`, writes `E` for every
read of `P` (`(E)` when it is not a plain postfix expression), and, for a read that begins a statement as `P[<integer>]`,
inserts `P_k = E;` before the statement and reads `P_k` there. The child with every local at once comes first, then each
alone. `P` qualifies when:
- it is a pointer or integer local, assigned exactly once, by a statement among the first statements of a loop body;
- `E` has no call, assignment, step or `&P`, names the loop's counter (a variable the body steps by one) and no other
  variable the body assigns;
- every read of `P` is inside that loop body, in two or more statements, and the body has an `if`.
"""
import re

from .csource import _blank, find
from .pattern_repairs import close
from .reassigned_local_inline import IDENT

FAMILY = 'loop_giv_local_arm_inline'
FAMILIES = (FAMILY,)
LIMIT = 6
NUMBER = r'(?:0[xX][0-9A-Fa-f]+|\d+)'
_ASSIGNMENT = re.compile(rf'\s*(?P<name>{IDENT})\s*=(?!=)\s*(?P<value>[^;{{}}=]+?)\s*;')
_POSTFIX = re.compile(rf'(?:\(\s*[^()]*\)|{IDENT})(?:\s*(?:\[[^\[\]]*\]|\.\s*{IDENT}|->\s*{IDENT}))*\Z')
_STEP = re.compile(rf'(?<![\w.>])({IDENT})\s*(?:\+\+|\+=\s*1\b|=\s*\1\s*\+\s*1\b)|\+\+\s*({IDENT})')
_TYPE_WORDS = {'return', 'goto', 'break', 'continue', 'else', 'case', 'default', 'typedef', 'extern', 'static', 'if', 'while', 'for', 'do'}


def _loops(clean, opening, end):
    """(body_open, body_close) of every loop in the function whose body is a block."""
    for hit in re.finditer(r'\b(?:do|for|while)\b', clean[opening:end]):
        at = opening + hit.start()
        after = opening + hit.end()
        if hit[0] == 'do':
            brace = re.match(r'\s*\{', clean[after:end])
            if not brace:
                continue
            body = after + brace.end() - 1
        else:
            paren = re.match(r'\s*\(', clean[after:end])
            if not paren:
                continue
            close_paren = close(clean, after + paren.end() - 1)
            brace = re.match(r'\s*\{', clean[close_paren:end]) if close_paren else None
            if not brace:
                continue
            body = close_paren + brace.end() - 1
        stop = close(clean, body, '{', '}')
        if stop:
            yield at, body, stop


def _whole_line(clean, first, last, end):
    begin = clean.rfind('\n', 0, first) + 1
    stop = clean.find('\n', last)
    stop = end if stop < 0 else stop
    if clean[begin:first].strip() or clean[last:stop].strip():
        return None
    return begin, stop + 1


def _leading(clean, body, stop):
    """The assignments that open a loop body: (name, expression, start, end) each."""
    out, at = [], body + 1
    while True:
        hit = _ASSIGNMENT.match(clean, at, stop)
        if not hit:
            return out
        out.append((hit['name'], hit['value'], hit.start() + len(hit[0]) - len(hit[0].lstrip()), hit.end()))
        at = hit.end()


def _spelled(expression):
    text = expression.strip()
    return text if _POSTFIX.match(text) else f'({text})'


def variants(source, name):
    span = find(source, name)
    if not span:
        return []
    clean = _blank(source)
    opening = clean.find('{', span[0], span[1])
    end = close(clean, opening, '{', '}') if opening >= 0 else None
    if not end or 'volatile' in clean[opening:end]:
        return []
    function = clean[opening:end]
    taken = set(re.findall(IDENT, clean))
    plans = []
    for _, body, stop in _loops(clean, opening, end):
        text = clean[body:stop]
        if not re.search(r'\bif\b', text):
            continue
        counters = {a or b for a, b in _STEP.findall(text)}
        assigned = {m[1] for m in re.finditer(rf'(?<![\w.>])({IDENT})\s*(?:[-+*/&|^]|<<|>>)?=(?!=)', text)} | \
                   {m[1] for m in re.finditer(rf'(?:\+\+|--)\s*({IDENT})', text)} | \
                   {m[1] for m in re.finditer(rf'({IDENT})\s*(?:\+\+|--)', text)}
        for pointer, value, first, last in _leading(clean, body, stop):
            names = set(re.findall(rf'(?<![\w.>]){IDENT}', value))
            if re.search(r'\w\s*\(|=|\+\+|--|;', value) or not (names & counters) or names & (assigned - counters):
                continue
            declared = re.search(rf'(?m)^[ \t]*(?P<type>(?:unsigned\s+)?[A-Za-z_]\w*(?:\s+[A-Za-z_]\w*)*?\s*\**)\s*{re.escape(pointer)}\s*;[ \t]*$',
                                 clean[opening:body])
            if not declared or declared['type'].split()[0] in _TYPE_WORDS:
                continue
            if len(re.findall(rf'(?<![\w.>]){re.escape(pointer)}\s*(?:[-+*/&|^]|<<|>>)?=(?!=)|(?:\+\+|--)\s*{re.escape(pointer)}\b|\b{re.escape(pointer)}\s*(?:\+\+|--)', function)) != 1:
                continue
            if re.search(rf'&\s*{re.escape(pointer)}\b', function):
                continue
            uses = [opening + m.start() for m in re.finditer(rf'(?<![\w.>]){re.escape(pointer)}\b', function)]
            declaration_at = opening + declared.start()
            reads = [at for at in uses if not (declaration_at <= at < opening + declared.end()) and not (first <= at < last)]
            if len(reads) < 2 or any(not body < at < stop for at in reads):
                continue
            plans.append((pointer, value, declared, first, last, reads, stop, opening))
    if not plans:
        return []
    children = []
    groups = [plans] + ([[plan] for plan in plans] if len(plans) > 1 else [])
    for group in groups:
        edits, declarations, fresh, decl_starts = [], [], set(), []
        ok = True
        for pointer, value, declared, first, last, reads, stop, base in group:
            line = _whole_line(clean, first, last, end)
            decl_line = _whole_line(clean, base + declared.start(), base + declared.end(), end)
            if line is None or decl_line is None:
                ok = False
                break
            kind = re.sub(r'\s+', ' ', declared['type']).strip()
            kind = re.sub(r'\s*\*', ' *', kind).replace('* *', '**')
            decl_starts.append(decl_line[0])
            edits.append((line[0], line[1], ''))
            edits.append((decl_line[0], decl_line[1], ''))
            count = 0
            for at in reads:
                tail = re.match(rf'{re.escape(pointer)}\s*\[\s*{NUMBER}\s*\]', clean[at:end])
                before = clean[:at].rstrip()
                starts_statement = bool(tail) and before[-1:] in (';', '{', '}')
                if not starts_statement:
                    edits.append((at, at + len(pointer), _spelled(value)))
                    continue
                count += 1
                local = f'{pointer}_{count}'
                while local in taken or local in fresh:
                    local += '_'
                fresh.add(local)
                indent = clean[clean.rfind('\n', 0, at) + 1:at]
                indent = indent if not indent.strip() else ''
                edits.append((at, at, f'{local} = {value.strip()};\n{indent}'))
                edits.append((at, at + len(pointer), local))
                declarations.append(f'  {kind}{local};\n' if kind.endswith('*') else f'  {kind} {local};\n')
        if not ok:
            continue
        # the fresh locals are declared where the first removed declaration was
        if declarations:
            edits.append((min(decl_starts), min(decl_starts), ''.join(declarations)))
        text = source
        for first, last, replacement in sorted(edits, key=lambda e: (e[0], e[1]), reverse=True):
            text = text[:first] + replacement + text[last:]
        if text != source and text not in children:
            children.append(text)
    return [(FAMILY, text) for text in children[:LIMIT]]


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name'), 'order': 70}  # the registry: no caller wiring (registry.py)

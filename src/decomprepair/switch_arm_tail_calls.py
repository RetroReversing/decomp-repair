"""A call after a switch whose arguments the arms assigned, written as one call at the end of each arm.

    switch (k) { case 0: first(&A, x); a = &B; b = x; break;  case 1: first(&C, x); a = &D; b = x; break; ... }
    second(a, b, rest);

is m2c's way of sharing the call every arm ends with: it makes the arms assign the call's arguments and calls once after
the switch. The game's source called in each arm (`second(&B, x, rest);`), and the compiler's cross-jumping merged the
identical tails again. The shared form is a different program for the compiler's allocator: the arguments are
multiple-set pseudos that live across the whole switch, and their address loads are scheduled before the arms' first
call (`lui $s1,%hi(B)` hoisted above `first`), so every arm differs from the target's. A 417-instruction input handler's
tail of eight arms went 3145 -> 905 with the call per arm and the callee's byte parameter written as `u8` (the arms then
matched and the arguments' registers followed).

Offered for a `switch` whose arms all end in their one `break;` (the last may fall out of the braces), followed at once
by a call statement whose arguments include names the arms assign at their own top level: the call is copied before each
`break;` with those names replaced by the arm's last value, the shared call goes, and an assignment nothing reads any
more goes with it. The arms' own byte temporaries (`t = x & 0xFF;` read by two calls) are the business of the
single-use inline families: after this rewrite they are read by two calls each. A candidate rewrite; the exact judge
decides.
"""
import re

from .integer_repair_support import IDENT, edit, view
from .pattern_repairs import close

FAMILY = 'switch_arm_tail_calls'
FAMILIES = (FAMILY,)
_SWITCH = re.compile(r'\bswitch\s*\(')
_LABEL = re.compile(r'\b(?:case\b[^:;{}?]*|default)\s*:')


def _python_split(text):
    parts, depth, start = [], 0, 0
    for at, char in enumerate(text):
        depth += (char in '([{') - (char in ')]}')
        if char == ',' and depth == 0:
            parts.append(text[start:at].strip())
            start = at + 1
    parts.append(text[start:].strip())
    return parts


_split = _python_split
try:  # the typed kernel (native_build.py), when it is built: same answers, the loop in C
    from . import _scan
except ImportError:
    _scan = None
if _scan is not None:
    def _split(text):
        return [piece.strip() for piece in _scan.top_pieces(text, ',', 3)]


def _python_top_level(text, start):
    """Offsets in `text` that are outside every bracket, from `start`."""
    depth, spans = 0, []
    for at in range(start, len(text)):
        char = text[at]
        if char in '([{':
            depth += 1
        elif char in ')]}':
            depth -= 1
        spans.append(depth == 0)
    return spans


_top_level = _python_top_level
try:  # the typed kernel (native_build.py), when it is built: same answers, the loop in C
    from . import _scan
except ImportError:
    _scan = None
if _scan is not None:
    def _top_level(text, start):
        found = _scan.top_level_flags(text, start)
        return _python_top_level(text, start) if found is NotImplemented else found


def _arms(clean, body_start, body_end):
    labels = []
    depth = 0
    for at in range(body_start, body_end):
        char = clean[at]
        if char in '([{':
            depth += 1
        elif char in ')]}':
            depth -= 1
        elif depth == 0 and (clean.startswith('case', at) or clean.startswith('default', at)):
            hit = _LABEL.match(clean, at)
            if hit and (at == body_start or not re.match(r'\w', clean[at - 1])):
                labels.append((hit.start(), hit.end()))
    arms = []
    for k, (start, end) in enumerate(labels):
        arms.append((end, labels[k + 1][0] if k + 1 < len(labels) else body_end))
    return arms


_BYTE_TEMP = re.compile(rf'(?<![\w.>])(?P<v>{IDENT})\s*=\s*(?P<e>{IDENT}\s*&\s*0[xX][0-9A-Fa-f]+)\s*;')


def _inline_byte_temps(source, name):
    part = view(source, name)
    if not part:
        return None
    clean = part.clean
    body = clean[part.opening:part.end]
    edits = []
    for hit in _SWITCH.finditer(clean, part.opening + 1, part.end):
        shut = close(clean, hit.end() - 1)
        block = re.match(r'\s*\{', clean[shut:]) if shut else None
        end = close(clean, shut + block.end() - 1, '{', '}') if block else None
        if not end:
            continue
        for start, stop in _arms(clean, shut + block.end(), end - 1):
            text = clean[start:stop]
            flat = _top_level(text, 0)
            for assign in _BYTE_TEMP.finditer(text):
                var, expr = assign['v'], re.sub(r'\s+', ' ', assign['e'])
                everywhere = len(re.findall(rf'(?<![\w.>]){re.escape(var)}\b', body))
                declared = len(re.findall(rf'(?m)^\s*(?:register\s+|volatile\s+|unsigned\s+|signed\s+)*\w+[\s*]+{re.escape(var)}\s*;', clean[:part.end]))
                here = len(re.findall(rf'(?<![\w.>]){re.escape(var)}\b', text))
                sets = len(re.findall(rf'(?<![\w.>]){re.escape(var)}\s*=(?!=)', body))
                if not flat[assign.start()] or everywhere - declared != here or sets != 1:
                    continue
                edits.append((start + assign.start(), start + assign.end(), ''))
                for use in re.finditer(rf'(?<![\w.>]){re.escape(var)}\b', text):
                    if not assign.start() <= use.start() < assign.end():
                        edits.append((start + use.start(), start + use.end(), f'({expr})'))
    return edit(source, edits) if edits else None


def variants(source, name):
    part = view(source, name)
    if not part:
        return []
    clean = part.clean
    out = []
    for hit in _SWITCH.finditer(clean, part.opening + 1, part.end):
        shut = close(clean, hit.end() - 1)
        block = re.match(r'\s*\{', clean[shut:]) if shut else None
        if not block:
            continue
        open_at = shut + block.end() - 1
        end = close(clean, open_at, '{', '}')
        call = re.match(rf'\s*(?P<c>(?P<f>{IDENT})\s*\((?P<args>[^;]*)\)\s*;)', clean[end:]) if end else None
        if not call or call['f'] in ('if', 'while', 'for', 'switch', 'return'):
            continue
        args = _split(call['args'])
        names = [a for a in args if re.fullmatch(IDENT, a)]
        arms = _arms(clean, open_at + 1, end - 1)
        if not names or len(arms) < 2:
            continue
        per_arm = []
        usable = True
        for start, stop in arms:
            text = clean[start:stop]
            if re.search(r'\b(?:return|goto|continue)\b', text) or len(re.findall(r'\bbreak\b', text)) > 1:
                usable = False
                break
            tail = re.search(r'\bbreak\s*;\s*\Z', text)
            if len(re.findall(r'\bbreak\b', text)) == 1 and not tail:
                usable = False
                break
            flat = _top_level(text, 0)
            values = {}
            sequence = []
            for assign in re.finditer(rf'(?<![\w.>])(?P<v>{IDENT})\s*=\s*(?P<e>[^;=][^;]*);', text):
                if flat[assign.start()] and assign['v'] in names and not text[:assign.start()].rstrip().endswith('='):
                    expr = source[start + assign.start('e'):start + assign.end('e')].strip()
                    values[assign['v']] = (assign.start(), assign.end(), expr)
                    sequence.append((assign.start(), assign.end(), assign['v'], expr))
            per_arm.append((start, stop, tail, values, sequence))
        if not usable or not any(values for _, _, _, values, _ in per_arm):
            continue
        edits = [(end, end + call.end('c'), '')]
        removed = {}
        body = clean[part.opening:part.end]
        replaced = {}
        for start, stop, tail, values, sequence in per_arm:
            new_args = []
            for arg in args:
                got = values.get(arg) if re.fullmatch(IDENT, arg) else None
                value = got[2] if got else arg
                if got and not re.fullmatch(r'[\w.]+|\(\s*\w[\w\s*]*\)\s*[\w.&]+|&\s*\w+', value):
                    value = f'({value})'
                new_args.append(value)
            copy = f"{call['f']}({', '.join(new_args)});"
            at = start + tail.start() if tail else stop
            line_start = source.rfind('\n', 0, at) + 1
            lead = source[line_start:at]
            indent = lead if tail and not lead.strip() else re.match(r'[ \t]*', source[source.rfind('\n', 0, start) + 1:])[0] + '  '
            if tail and not lead.strip():
                at = line_start
            edits.append((at, at, f'{indent}{copy}\n' if tail and not lead.strip() else (f'{copy}\n{indent}' if tail else f'\n{indent}{copy}')))
            # a later read of an assigned name in the same arm sees the value assigned last before it
            text = clean[start:stop]
            for var in {item[2] for item in sequence}:
                for read in re.finditer(rf'(?<![\w.>]){re.escape(var)}\b(?!\s*=(?!=))', text):
                    before = [item for item in sequence if item[1] <= read.start() and item[2] == var]
                    if before and not any(item[0] <= read.start() < item[1] for item in sequence):
                        value = before[-1][3]
                        value = value if re.fullmatch(r'[\w.]+|&\s*\w+', value) else f'({value})'
                        edits.append((start + read.start(), start + read.end(), value))
                        replaced[var] = replaced.get(var, 0) + 1
            for x, y, var, _ in sequence:
                removed.setdefault(var, []).append((start + x, start + y))
        # an assignment is dropped when nothing else reads its variable
        for var, spans in removed.items():
            seen = len(re.findall(rf'(?<![\w.>]){re.escape(var)}\b', body))
            written = len(re.findall(rf'(?<![\w.>]){re.escape(var)}\s*=(?!=)', body))
            declared = len(re.findall(rf'(?m)^\s*(?:register\s+|volatile\s+|unsigned\s+|signed\s+)*\w+[\s*]+{re.escape(var)}\s*;', clean[:part.end]))
            if seen - replaced.get(var, 0) - written - declared - 1 <= 0:  # the one read left is the shared call's, which is going away
                for x, y in spans:
                    edits.append((x, y, ''))
        tailed = edit(source, edits)
        out.append((FAMILY, tailed))
        # the same with each arm's byte temporaries (`t = x & 0xFF;`, read by the arm's two calls) written out where
        # they are read: with the temporaries the two calls share one register that crosses the first call, which
        # is not what the game's two `(u8)x` arguments compile to
        inlined = _inline_byte_temps(tailed, name)
        if inlined and inlined != tailed:
            out.append((FAMILY, inlined))
    return out


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name')}

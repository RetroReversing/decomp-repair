"""m2c's comma-assignment gate written as the plain condition it tests, and a held volatile read used from its local.

When one comparison feeds a flag test, m2c spells it as a flag assigned inside each way into the test:

    if (held != 0 && ((flag = a < b, byte != 0) || (flag = a < b, word == 0)) && flag == 0)

That is `held != 0 && (byte != 0 || word == 0) && !(a < b)`. GCC 2.7.2 builds the two spellings differently: the flag
is a pseudo of its own that the assignments in both ways make a global one, the comparison is computed once per way
into it, and the delay slots and the register after it follow (a 616-instruction audio command builder, 8456 -> 7996
with the next edit; the plain gate kept the target's `sltu` in the branch's delay slot). The rewrite is made only when
nothing else could depend on the flag:
- every group `(flag = E, rest)` assigns the same expression E, and E, the `rest` conditions and the tests have no
  call, `++`, `--`, assignment or `volatile`, so evaluating E once, after the conditions, is the same program;
- the flag is named nowhere else in the function but its declaration (which is dropped when it becomes unused);
- the tests of the flag are `flag == 0`, `flag != 0`, `!flag` or `flag` as a `&&`/`||` operand of the same condition.

`held_volatile_reread` is the other half of that function's gate: a `volatile` word read into a local on its own
line (`held = *(volatile u32 *) (p + 0x38);`) and read again from memory in the next `if` is the same read twice, which
GCC 2.7.2 must repeat (a `volatile` is never merged), so the target's third load of the word is not a fourth: the
second read is the local. The child is made only when the statement is the one directly before the statement that holds the `if`, with the
same expression text, and the local is read nowhere else between them. The explanation of why GCC repeats the load is
read off the target's three loads, not from the compiler's source, and is a hypothesis; every child is judged.

A child with both edits is offered too, since the gate with both measured 8456 -> 7996 and either alone less."""
import re

from .integer_repair_support import edit, view
from .pattern_repairs import close

FAMILY = 'comma_gate_plain'
FAMILY_REREAD = 'held_volatile_reread'
FAMILIES = (FAMILY, FAMILY_REREAD)

_IDENT = r'[A-Za-z_]\w*'
_TYPES = {'u8', 'u16', 'u32', 's8', 's16', 's32', 'f32', 'f64', 'int', 'unsigned', 'char', 'short', 'long', 'float',
          'double', 'void', 'const', 'signed', 'struct', 'sizeof', 'if', 'while', 'for', 'switch', 'return'}
_EFFECT = re.compile(r'\+\+|--|(?<![=!<>])=(?!=)|\bvolatile\b')


def _impure(text):
    """True when `text` may call, assign or read a volatile: evaluating it later or once would change the program."""
    if _EFFECT.search(text):
        return True
    for match in re.finditer(r'\b(' + _IDENT + r')\s*\(', text):
        if match[1] not in _TYPES:
            return True
    return False


def _has_call(text):
    return any(match[1] not in _TYPES for match in re.finditer(r'\b(' + _IDENT + r')\s*\(', text))


def _python_top_comma(text):
    """The offset of the one comma at depth 0 of `text`, or None when there is none or more than one."""
    depth, found = 0, []
    for index, char in enumerate(text):
        depth += (char in '([') - (char in ')]')
        if char == ',' and depth == 0:
            found.append(index)
    return found[0] if len(found) == 1 else None


_top_comma = _python_top_comma
try:  # the typed kernel (native_build.py), when it is built: same answers, the loop in C
    from . import _scan
except ImportError:
    _scan = None
if _scan is not None:
    def _top_comma(text):
        found = _scan.top_offsets(text, ',', 2)
        return found[0] if len(found) == 1 else None


def _groups(condition):
    """Every parenthesised `(flag = E, rest)` in `condition`: (start, end, flag, E, rest)."""
    out = []
    for match in re.finditer(r'\(', condition):
        end = close(condition, match.start())
        if not end:
            continue
        inner = condition[match.start() + 1:end - 1]
        comma = _top_comma(inner)
        if comma is None:
            continue
        head = re.fullmatch(r'\s*(' + _IDENT + r')\s*=(?!=)\s*(.+?)\s*', inner[:comma], re.S)
        if head and inner[comma + 1:].strip():
            out.append((match.start(), end, head[1], head[2], inner[comma + 1:].strip()))
    return out


def _tests(condition, flag):
    """The spans of the flag's tests in `condition`: (start, end, meaning) with meaning 'zero' or 'nonzero'."""
    out = []
    for match in re.finditer(r'\(\s*' + re.escape(flag) + r'\s*(==|!=)\s*0\s*\)|(?<![\w.])' + re.escape(flag)
                             + r'\s*(==|!=)\s*0(?![\w.])|!\s*' + re.escape(flag) + r'\b', condition):
        operator = match[1] or match[2]
        out.append((match.start(), match.end(), 'nonzero' if operator == '!=' else 'zero'))
    return out


def _plain_gate(condition, body_clean, whole):
    """`condition` rewritten, or None. `whole` is the function's blanked text (to count the flag's other mentions)."""
    groups = _groups(condition)
    if not groups:
        return None
    flags = {group[2] for group in groups}
    if len(flags) != 1:
        return None
    flag = flags.pop()
    if len({re.sub(r'\s+', ' ', group[3]) for group in groups}) != 1:
        return None
    expression = groups[0][3]
    if _impure(expression) or any(_impure(group[4]) for group in groups):
        return None
    tests = _tests(condition, flag)
    if not tests:
        return None
    mentions = len(re.findall(r'(?<![\w.])' + re.escape(flag) + r'\b', whole))
    declared = len(re.findall(r'\b[A-Za-z_]\w*(?:\s+|\s*\*\s*)' + re.escape(flag) + r'\s*;', whole))
    if mentions != len(groups) + len(tests) + declared:
        return None
    # nested groups would overlap: keep the outermost only
    edits = []
    for start, end, _flag, _expr, rest in groups:
        if not any(a[0] < start and end <= a[1] for a in groups if a[:2] != (start, end)):
            edits.append((start, end, '(' + rest + ')'))
    for start, end, meaning in tests:
        text = '(' + expression + ')' if meaning == 'nonzero' else '!(' + expression + ')'
        edits.append((start, end, text))
    return edit(condition, edits), flag


def _if_spans(clean, opening, end):
    for match in re.finditer(r'\bif\s*\(', clean[opening:end]):
        start = opening + match.end() - 1
        stop = close(clean, start)
        if stop:
            yield start, stop


def _gate_variants(source, part):
    out = []
    whole = part.clean
    for start, stop in _if_spans(part.clean, part.opening, part.end):
        condition = source[start:stop]
        made = _plain_gate(condition, part.clean, whole[part.opening:part.end])
        if not made:
            continue
        text, flag = made
        edits = [(start, stop, text)]
        # the flag's declaration goes with its last mention
        declaration = re.search(r'(?m)^[ \t]*[A-Za-z_]\w*(?:[ \t]+|[ \t]*\*[ \t]*)' + re.escape(flag) + r'[ \t]*;[ \t]*\n',
                                part.clean[part.opening:part.end])
        if declaration:
            edits.append((part.opening + declaration.start(), part.opening + declaration.end(), ''))
        out.append(edit(source, edits))
    return out


def _reread_variants(source, part):
    """`held = VOLATILE;` followed, with only plain statements between, by an `if` that reads the same VOLATILE."""
    out = []
    pattern = re.compile(r'(?m)^([ \t]*)(' + _IDENT + r')\s*=\s*(\*\s*\(\(volatile\s+[^;]*?\)[^;]*\))\s*;[ \t]*\n')
    for match in pattern.finditer(part.clean, part.opening, part.end):
        local, volatile = match[2], match[3]
        rest = part.clean[match.end():part.end]
        found = re.search(r'\bif\s*\(', rest)
        if not found:
            continue
        between = rest[:found.start()]
        if re.search(r'[{}]', between) or re.search(r'(?<![\w.])' + re.escape(local) + r'\b|\blabel\b|:', between) \
                or _has_call(between):
            continue
        opening = match.end() + found.end() - 1
        stop = close(part.clean, opening)
        if not stop:
            continue
        condition = part.clean[opening:stop]
        edits = [(opening + hit.start(), opening + hit.end(), local)
                 for hit in re.finditer(r'\(\s*' + re.escape(volatile) + r'\s*\)|' + re.escape(volatile), condition)]
        if not edits:
            continue
        # another volatile read between them (the sum the word is part of): the held read follows it, as the target's
        # loads do (the word's own load after the sum's), so the assignment moves to just after that statement
        last = between.rfind('volatile')
        if last >= 0:
            semicolon = between.find(';', last)
            if semicolon < 0:
                continue
            at = match.end() + semicolon + 1
            line = source[match.start():match.end()]
            newline = source.find('\n', at)
            edits += [(match.start(), match.end(), ''),
                      (newline + 1 if newline >= 0 else at, newline + 1 if newline >= 0 else at, line)]
        out.append(edit(source, edits))
    return out


def variants(source, name):
    part = view(source, name)
    if not part:
        return []
    out = []
    gates = _gate_variants(source, part)
    rereads = _reread_variants(source, part)
    out += [(FAMILY, text) for text in gates]
    out += [(FAMILY_REREAD, text) for text in rereads]
    for gate in gates[:1]:
        again = view(gate, name)
        if again:
            both = _reread_variants(gate, again)
            out += [(FAMILY, text) for text in both]
    return list(dict.fromkeys(out))


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name'), 'order': 220}

"""An opcode byte read once into a `u8` local, then tested and switched on.

A byte-code interpreter written the usual way reads the opcode once:

    u8 op;
    while ((op = *code) != 12) { switch (op) { ... } }

m2c writes the byte twice (once in the loop test, once in the `switch`), and the compiler has no reason to keep the
byte in a register of its own: the two reads fold into one `lbu` and the test and the jump table both use the loaded
word. GCC 2.7.2 keeps a `u8` local in a QImode register: the load goes to one register and the test and the table index
use its zero extension (`lbu $a0, 0($s0); andi $v1, $a0, 0xff; bne $v1, $v0, ...`), one more instruction per
dispatch and a different register for the loop's other values (a 125 -> 20 step in a 359-instruction interpreter).

`variants` finds a byte expression `E` (`name[literal]`, `*name`, a field read through a `u8 *` or `u8` cast) that is
both the controlling expression of a `switch` and a compared operand of the test that leads to it:
  * `L: if (E OP K) { goto D; }` with `D: switch (E)` (m2c's loop form), the body holding nothing that writes memory or
    the pointer the byte is read through, or
  * `while (E OP K) { switch (E) {...} ... }` with the switch the loop body's first statement,
and writes the test as `op = E; if (op OP K)` (`while ((op = E) OP K)`) and the switch as `switch (op)`.
Every use of `E` as a controlling expression in between is the same value, so the program is the same.
Declares `u8 op;` (a name that is not used) with the function's locals."""
import re

from .integer_repair_support import IDENT, edit, view
from .pattern_repairs import close

FAMILY = 'dispatch_byte_local'
FAMILIES = (FAMILY,)
NAME = 'op'
BYTE = rf'(?:\*\s*{IDENT}|{IDENT}\s*\[\s*(?:0[xX][0-9a-fA-F]+|\d+)\s*\])'
COMPARE = r'(?:==|!=|<=|>=|<|>)'
NUMBER = r'(?:0[xX][0-9a-fA-F]+|\d+)'


def _bytes_pointer(clean, expression):
    pointer = re.search(IDENT, expression)[0]
    declared = re.search(rf'(?m)(?:^|[(,])\s*(?:register\s+|const\s+)*((?:unsigned\s+)?\w+)\s*\*\s*{re.escape(pointer)}\b', clean)
    return pointer, declared[1] if declared else None


def _fresh(clean):
    name = NAME
    while re.search(rf'\b{name}\b', clean):
        name += '_'
    return name


def _first_statement(clean, at):
    text = clean[at:]
    skip = re.match(r'\s*', text).end()
    return at + skip


def variants(source, name):
    part = view(source, name)
    if not part:
        return []
    clean = part.clean
    base, end = part.opening + 1, part.end - 1
    body = clean[base:end]
    if re.search(r'\bvolatile\b', body):
        return []
    found = []
    # m2c's form: `if (E OP K) { ... goto D; }` where `D:` is followed by `switch (E)`
    for test in re.finditer(rf'\bif\s*\(\s*({BYTE})\s*({COMPARE})\s*({NUMBER})\s*\)\s*{{', body):
        expression = re.sub(r'\s+', '', test[1])
        brace = base + test.end() - 1
        stop = close(clean, brace, '{', '}')
        if not stop:
            continue
        inner = clean[brace + 1:stop - 1]
        goto = re.search(r'\bgoto\s+(\w+)\s*;\s*$', inner)
        if not goto:
            continue
        pointer, kind = _bytes_pointer(clean, expression)
        if (re.search(r'\w\s*\[[^\]]*\]\s*(?:[-+*/|&^]|<<|>>)?=(?!=)|\*[^;=]*(?:[-+*/|&^]|<<|>>)?=(?!=)|\(', inner[:goto.start()])
                or re.search(rf'(?<![\w.>*]){re.escape(pointer)}\s*(?:[-+*/|&^]|<<|>>)?=(?!=)|(?:\+\+|--)\s*{re.escape(pointer)}|{re.escape(pointer)}\s*(?:\+\+|--)', inner)):
            continue
        label = re.search(rf'(?<![\w.>]){re.escape(goto[1])}\s*:\s*switch\s*\(\s*({BYTE})\s*\)', clean[base:end])
        if not label or re.sub(r'\s+', '', label[1]) != expression:
            continue
        found.append(('goto', test, base + label.start(1), base + label.end(1), expression, kind))
    # the loop form: `while (E OP K) { switch (E) ...`
    for test in re.finditer(rf'\bwhile\s*\(\s*({BYTE})\s*({COMPARE})\s*({NUMBER})\s*\)\s*{{\s*switch\s*\(\s*({BYTE})\s*\)', body):
        expression = re.sub(r'\s+', '', test[1])
        if re.sub(r'\s+', '', test[4]) == expression:
            found.append(('while', test, base + test.start(4), base + test.end(4), expression, _bytes_pointer(clean, expression)[1]))
    out = []
    for form, test, low, high, expression, kind in found:
        local = _fresh(clean)
        # the byte type: u8 for a byte pointer (the unsigned char behind `u8`), otherwise leave the decision to the judge
        if kind not in ('u8', 'unsigned char', 'char', 's8', 'signed char'):
            continue
        declared = 'u8' if kind in ('u8', 'unsigned char') else 's8'
        edits = [(low, high, local)]
        if form == 'goto':
            at = base + test.start()
            line = source.rfind('\n', 0, at) + 1
            pad = source[line:at] if not source[line:at].strip() else ''
            edits.append((at, at, f'{local} = {test[1]};\n{pad}'))
            edits.append((base + test.start(1), base + test.end(1), local))
        else:
            edits.append((base + test.start(1), base + test.end(3), f'({local} = {test[1]}) {test[2]} {test[3]}'))
        # declare the local with the others: before the first statement of the function body
        first = _first_statement(clean, base)
        indent = re.match(r'[ \t]*', source[source.rfind('\n', 0, first) + 1:first])[0] or '  '
        edits.append((first, first, f'{declared} {local};\n{indent}'))
        out.append((FAMILY, edit(source, edits)))
    return out


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name')}

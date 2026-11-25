"""A `void` function whose target keeps `$v0` live at its exit: declare it `s32` and write no return statement.

The compiler's delay-slot filler (reorg) will not move an instruction that writes `$v0` into the slot of a branch whose
taken path reaches the function's exit with `$v0` still live: that would clobber the return value on the taken path. In a
`void` function nothing is live there, so the same instruction does fill the slot. A target with the slot left as a `nop`
after a conditional branch, where the fall-through's first instruction is a plain write to `$v0` and the taken path runs to
the `jr $ra` without writing `$v0`, is therefore a function that was declared to return a value and never returns one on
that path (an m2c draft is `void` because no caller reads the value):

    void f(void *o) { ...; if (g(o) != 0) { o->a = 0; o->b = &h; } }
    s32  f(void *o) { ...; if (g(o) != 0) { o->a = 0; o->b = &h; } }     /* falls off the end: `$v0` is `g`'s result */

(three animation-state handlers of an N64 game: each 100 -> 0 / a few rows -> 0 by the declaration alone). The target's
bytes cannot say the type, only that `$v0` is live, and a `s32` with no `return` is what falls off the end with it.

Evidence (MIPS): a non-likely conditional branch (`beq bne beqz bnez bgez bgtz blez bltz bc1f bc1t`) whose delay slot is
a `nop`, whose following instruction writes `$v0` (an ALU or load-immediate form), and whose target label reaches a
`jr $ra` with no write to `$v0`, call or further branch in between. One child: the same function declared `s32` (its earlier
`void` prototypes too); a `void` function that has a `return <value>;` already, or a header prototype declaring it `void`,
gets nothing."""
import re

from .csource import find
from .integer_repair_support import edit, view

FAMILY = 'nonvoid_no_return'
FAMILIES = (FAMILY,)

BRANCHES = {'beq', 'bne', 'beqz', 'bnez', 'bgez', 'bgtz', 'blez', 'bltz', 'bc1f', 'bc1t'}
WRITERS = {'lui', 'addiu', 'addi', 'ori', 'addu', 'add', 'or', 'move', 'li', 'andi', 'xori', 'slti', 'sltiu', 'slt',
           'sltu', 'subu', 'sub', 'sll', 'srl', 'sra', 'negu', 'nor', 'and', 'xor', 'daddiu', 'daddu'}
FLOW = {'jal', 'jalr', 'j', 'jr', 'b', 'bal'} | BRANCHES | {'beql', 'bnel', 'beqzl', 'bnezl', 'bc1fl', 'bc1tl'}
ROW = re.compile(r'^\s*(?:/\*.*?\*/)?\s*(?P<op>[a-z][\w.]*)\s*(?P<args>[^\n]*)$')
LABEL = re.compile(r'^\s*(?P<name>[.\w$]+):\s*$')


def _items(asm):
    """[('label', name) | (op, args)] of the function's lines."""
    items = []
    for line in (asm or '').splitlines():
        text = line.strip()
        if not text or text.startswith(('glabel', 'endlabel', '.size', '.type', '.set')) or text.startswith('/*') and text.endswith('*/'):
            continue
        label = LABEL.match(line)
        if label:
            items.append(('label', label['name']))
            continue
        hit = ROW.match(line)
        if hit and not text.startswith('.'):
            items.append((hit['op'], hit['args'].strip()))
    return items


def _writes_v0(op, args):
    return op in WRITERS and re.match(r'\$v0\b', args) is not None


def _reaches_exit(items, label):
    at = next((i for i, (op, args) in enumerate(items) if op == 'label' and args == label), None)
    if at is None:
        return False
    for op, args in items[at + 1:]:
        if op == 'label':
            continue
        if op == 'jr' and args == '$ra':
            return True
        if op in FLOW or re.match(r'\$v0\b', args) and op not in ('sw', 'sh', 'sb', 'swc1', 'sdc1', 'sd'):
            return False
    return False


def live_at_exit(asm):
    """Whether the target leaves a delay slot unfilled that `$v0` would have filled (see the module's docstring)."""
    items = _items(asm)
    for i, (op, args) in enumerate(items[:-2]):
        if op not in BRANCHES or items[i + 1] != ('nop', ''):
            continue
        following = items[i + 2]
        if following[0] == 'label' or not _writes_v0(*following):
            continue
        target = args.split(',')[-1].strip()
        if _reaches_exit(items, target):
            return True
    return False


def variants(source, name, asm, header=''):
    if not live_at_exit(asm):
        return []
    part = view(source, name)
    if not part:
        return []
    top = source.rfind('\n', 0, find(source, name)[0]) + 1
    head = re.search(rf'(?P<result>[^;{{}}]*?)\b{re.escape(name)}\s*\([^()]*\)\s*$', part.clean[top:part.opening].rstrip())
    void = re.search(r'\bvoid\s*$', head['result']) if head else None
    if not void or not re.fullmatch(r'\s*(?:(?:static|inline|extern)\s+)*', head['result'][:void.start()]):
        return []
    if re.search(rf'\bvoid\s+{re.escape(name)}\s*\(', header or '') or re.search(r'\breturn\s*[^;\s]', part.clean[part.opening:part.end]):
        return []
    at = top + head.start('result') + void.start()
    edits = [(at, at + 4, 's32')]
    for proto in re.finditer(rf'(?m)^[ \t]*(?:extern[ \t]+)?void(?=\s+{re.escape(name)}\s*\([^;{{}}]*\)\s*;)', part.clean[:top + head.start('result')]):
        edits.append((proto.end() - 4, proto.end(), 's32'))
    text = edit(source, edits)
    return [(FAMILY, text)] if text != source else []


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name', 'asm', 'header'),
          'order': 64, 'archs': ('mips',)}

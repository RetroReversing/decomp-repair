"""A `void` function whose target hands its incoming parameter back in `$v0`: declare it to return that parameter.

    void f(void *arg0, void *arg1, void *arg2) { arg0[0] = arg1[0] + arg2[0]; ... }
    s32  f(void *arg0, void *arg1, void *arg2) { arg0[0] = arg1[0] + arg2[0]; ...  return (s32) arg0; }

A vector helper (`dst = a + b`, three float adds stored through the destination) is compiled by KMC GCC 2.7.2 (N64,
`-G0 -mips2 -O2`) with a `move $v0, $a0` in front of the first store and every store addressed through `$v0`: the
function returns its destination pointer. m2c cannot see that, the callers never read `$v0`, so its draft is `void` and
stores through `$a0`. The `void` form is one row short (the `move`) and a copy of `arg0` into a local does not add it
(115 -> 35 by a clobber; the exact form is the next sentence). Declaring the function `s32` and ending with
`return (s32) arg0;` is exact (35 -> 0, 14 instructions; a neighbour has the same shape). `returned_register_local` keeps
the declared return type and offers nothing for `void`, because changing a type needs evidence; this is the evidence the
other way.

The evidence is the target's own epilogue (MIPS): the last write to `$v0` before the single `jr $ra` is a plain copy
(`move`, `addu`/`or` with `$zero`) of an argument register `$a0`..`$a3`, no call, branch or branch target sits between that
copy and the return, and nothing wrote that argument register or called before the copy (so it still holds the caller's
value). A `void` function never loads `$v0` from `$a0`, so the target returns the parameter. The parameter is the one at
that register's position when every parameter before it is a word (no float, 64-bit or by-value record).

For a `void` function with that evidence, one child each (children differ only in the declared type, which the target's
bytes cannot tell apart):
- the parameter's own pointer type with `return argN;` (the destination pointer, the usual value);
- `s32` with `return (s32) argN;` (the form that matched; for a pointer parameter, and for a word one `return argN;`).
Every bare `return;` becomes the same return and a final one is added when the body does not end in one. A `void`
prototype of the function earlier in the same source is rewritten with it. A caller that ignores the value compiles the
same after the change; whether a caller reads `$v0` is the callers' evidence (decompdecomp's `get_callers`), not the
library's, and the child is a candidate the exact judge scores. Nothing is offered when the function is not `void`, the
parameter is assigned in the body (the target copies the incoming value; a local copy would be a different edit), the
parameter has a narrow, float or 64-bit type, or the project's header declares the function as `void` (a header edit is
not a source rewrite: change the prototype with `edit_context` first). Hypothesis, not confirmed in the compiler source:
the copy comes from the front end's return expression being the one value live across the stores."""
import re

from . import mips_regions as flow
from .integer_repair_support import IDENT, edit, split_args, view
from .returned_register_local import returned_register

FAMILY = 'void_parameter_return'
FAMILIES = (FAMILY,)

SCALARS = {'s32', 'u32', 'int', 'unsigned', 'unsigned int', 'signed int', 's32_bool', 'long', 'unsigned long',
           'vs32', 'vu32'}
NOT_WRITTEN = flow.STORES | flow.CONDITIONAL | flow.JUMPS | flow.CALLS | set(
    'swl swr sc sdl sdr swc2 mtc1 dmtc1 mtc0 ctc1 mthi mtlo mult multu div divu teq tne tlt tge nop'.split())
LABEL = re.compile(r'^\s*(?:\.?[\w.$]+):\s*$')
LINE = re.compile(r'^\s*(?:/\*.*?\*/)?\s*(?P<op>[a-z][\w.]*)\s*(?P<args>[^\n]*)$')


def _rows(asm):
    rows = []
    for line in (asm or '').splitlines():
        if line.strip().startswith(('glabel', 'endlabel', '.')) and not line.strip().endswith(':'):
            continue
        if LABEL.match(line) and not line.strip().startswith('/*'):
            rows.append(('label', ''))
            continue
        hit = LINE.match(line)
        if hit and not hit['op'].endswith(':') and not line.strip().startswith('.'):
            rows.append((hit['op'], hit['args'].strip()))
    return rows


def incoming_parameter(asm):
    """The argument register number the target returns in `$v0` unchanged from entry, or None."""
    register = returned_register(asm)
    if not register or not re.fullmatch(r'a[0-3]', register):
        return None
    rows = _rows(asm)
    returns = [i for i, (op, args) in enumerate(rows) if op == 'jr' and args == '$ra']
    if len(returns) != 1:
        return None
    copy = None
    for i in range(returns[0] + 1, -1, -1):
        if i >= len(rows):
            continue
        op, args = rows[i]
        if op == 'label':
            return None  # a branch can reach the return past the copy
        if op not in NOT_WRITTEN and op != 'label' and re.match(r'\$v0\b', args):
            copy = i
            break
    if copy is None:
        return None
    for op, args in rows[:copy]:
        if op in flow.CALLS or (op not in NOT_WRITTEN and op != 'label' and re.match(rf'\${register}\b', args)):
            return None  # the register is no longer the caller's value
    return int(register[1])


def _parameters(params_text):
    text = params_text.strip()
    if text in ('', 'void'):
        return []
    return [text[a:b].strip() for a, b in split_args(text)]


def _changed(body, arg):
    """Whether `arg` is assigned, stepped or has its address taken in `body` (a store through it, `*arg = x`, is not)."""
    for hit in re.finditer(rf'(?<![\w.>])(?:(?:\+\+|--)\s*{arg}\b|{arg}\s*(?:\+\+|--|(?:[-+*/%&|^]|<<|>>)?=(?!=)))', body):
        if body[:hit.start()].rstrip()[-1:] not in ('*', ')') or hit.group().startswith(('++', '--')):
            return True
    return bool(re.search(rf'(?<![\w)\]])&\s*{arg}\b', body))


def _word(kind):
    """Whether a parameter type is one 32-bit register on MIPS o32: a pointer or a word integer."""
    kind = ' '.join(kind.replace('*', ' * ').split())
    return '*' in kind or kind in SCALARS


def _ends_in_return(body):
    """Whether the function body's last top-level statement is a `return` (not one under an `if`)."""
    tail = body.rstrip()[1:-1].rstrip()
    last = re.search(r'\breturn\b[^;{}]*;$', tail)
    if not last:
        return False
    before = tail[:last.start()].rstrip()
    depth = before.count('{') - before.count('}')
    return depth == 0 and before[-1:] in ('', ';', '{', '}')


def variants(source, name, asm, header=''):
    index = incoming_parameter(asm)
    if index is None:
        return []
    part = view(source, name)
    if not part:
        return []
    head = re.search(rf'(?P<result>[^;{{}}]*?)\b{re.escape(name)}\s*\((?P<params>[^()]*)\)\s*$',
                     part.clean[:part.opening].rstrip())
    void = re.search(r'\bvoid\s*$', head['result']) if head else None
    if not void or not re.fullmatch(r'\s*(?:(?:static|inline|extern)\s+)*', head['result'][:void.start()].rsplit('\n', 1)[-1]):
        return []
    if re.search(rf'\bvoid\s+{re.escape(name)}\s*\(', header or ''):
        return []  # a header prototype would conflict; changing it is the header's edit
    params = _parameters(head['params'])
    if index >= len(params) or not all(_word(re.sub(rf'{IDENT}\s*$', '', p)) for p in params[:index + 1]):
        return []
    declared = re.fullmatch(rf'(?P<type>.*?[\s*])(?P<name>{IDENT})\s*', params[index])
    if not declared:
        return []
    spelled, arg = ' '.join(declared['type'].split()), declared['name']
    kind = ' '.join(spelled.replace('*', ' * ').split())
    pointer = '*' in kind
    if _changed(part.clean[part.opening:part.end], arg):
        return []  # the parameter changes in the body: the target's copy is of the incoming value
    forms = []
    if pointer:
        forms.append((spelled, arg))
    forms.append(('s32', arg if kind in ('s32', 'int', 'signed int') else f'(s32) {arg}'))
    result = []
    result_at = head.start('result') + void.start()
    protos = list(re.finditer(rf'(?m)^[ \t]*(?:extern[ \t]+)?void(?=\s+{re.escape(name)}\s*\([^;{{}}]*\)\s*;)',
                              part.clean[:part.opening]))
    for new_type, value in forms:
        edits = [(result_at, result_at + 4, new_type)]
        edits += [(m.end() - 4, m.end(), new_type) for m in protos]
        body = part.clean[part.opening:part.end]
        for bare in re.finditer(r'\breturn\s*;', body):
            edits.append((part.opening + bare.start(), part.opening + bare.end(), f'return {value};'))
        if not _ends_in_return(body):
            close = part.opening + len(body.rstrip()) - 1
            lead = '' if part.clean[close - 1] == '\n' else '\n'
            edits.append((close, close, f'{lead}    return {value};\n'))
        text = edit(source, edits)
        if text != source:
            result.append((FAMILY, text))
    return result


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name', 'asm', 'header'),
          'order': 61, 'archs': ('mips',)}  # the registry: no caller wiring (registry.py)

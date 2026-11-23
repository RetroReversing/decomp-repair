"""A middle argument the target never sets: the caller's own incoming register, passed on as a parameter.

A wrapper that loads two fields of a table entry into `$a0` and `$a2` and calls a three-argument callee leaves `$a1`
alone: the callee gets whatever the caller itself was given in `$a1`, its own second argument passed on. m2c sees
the caller use only `$a0`, so the draft is `void f(s32 arg0)` calling `g(p->a, p->c)` with two arguments, and the
compiler puts the second one in `$a1` (one register row, score 5 on an N64 function built by KMC GCC 2.7.2, 15
instructions, whose callee's matched C reads all three parameters). Passing the caller's second argument,
`void f(s32 arg0, s32 arg1)` and `g(p->a, arg1, p->c)`, is exact. The hand match had passed an uninitialised local in
the middle (`s32 mid;`), which compiles the same and says nothing true; this is the faithful form.

`passthrough_argument` already passes a caller's parameter it has; this family adds the parameter the caller does not
have yet. For a callee the function calls once, on the straight-line path from its entry
(`passthrough_argument._incoming_calls`, which proves which argument registers still hold the caller's own values at
the `jal`): when the target writes argument registers on both sides of one or more it leaves untouched, the C passes
as many arguments as the target writes, and each untouched slot still holds the caller's own register, the call gets
`argK` at each such slot and the caller's signature gains `s32 argK` (and any parameters before it it lacked). One
child. No child when the caller already has that parameter (`passthrough_argument`'s step), for a varargs callee or
caller, when the callee's matched definition (`callees`) or the header gives another number of parameters, or when the
header declares the caller itself with its current parameters. The callee's declaration in the source gains `s32` at
the slot (its matched definition's type when supplied); an unprototyped `()` stays. MIPS only. Judged like any child."""
import re

from . import passthrough_argument_repairs as passthrough
from . import target_call_arity_repairs as arity
from .csource import _blank
from .integer_repair_support import IDENT, edit, split_args, view

FAMILY = 'untouched_argument_parameter'
FAMILIES = (FAMILY,)
ARGREG = arity.ARGREG


def _params(text):
    text = text.strip()
    if not text or text == 'void':
        return []
    return [text[a:b].strip() for a, b in split_args(text)]


def _param_name(param):
    hit = re.search(rf'({IDENT})\s*$', param)
    return hit[1] if hit and not re.fullmatch(r'void|[su](?:8|16|32)|int|char|short|long|float|double|f32|f64',
                                              hit[1]) else None


def _type_only(param):
    name = _param_name(param)
    return ' '.join((param[:param.rfind(name)] if name else param).split())


def _definition(callees, callee):
    clean = _blank(callees or '')
    hits = list(re.finditer(rf'(?<![\w.>]){re.escape(callee)}\s*\(([^(){{}};]*)\)\s*{{', clean))
    return _params(hits[0][1]) if len(hits) == 1 else None


def _header_counts(header, name):
    counts = set()
    for hit in re.finditer(rf'(?m)^[^\n;{{}}#]*\b{re.escape(name)}\s*\(([^()]*)\)\s*;', _blank(header or '')):
        counts.add(-1 if '...' in hit[1] else len(_params(hit[1])) if hit[1].strip() else None)
    counts.discard(None)
    return counts


def variants(source, name, asm, header='', callees=''):
    part = view(source, name)
    if not part or not asm:
        return []
    head = re.search(rf'\b{re.escape(name)}\s*\((?P<params>[^()]*)\)\s*$', part.clean[:part.opening].rstrip())
    if not head or '...' in head['params']:
        return []
    params = _params(head['params'])
    names = [_param_name(p) for p in params]
    if None in names:
        return []
    incoming = passthrough._incoming_calls(asm)
    written = {callee: regs for callee, regs in arity.calls(asm)}
    result = []
    for callee, slots in incoming.items():
        regs = written.get(callee)
        if not regs or callee == name:
            continue
        count = max(ARGREG.index(r) + 1 for r in regs)
        untouched = [k for k in range(count) if ARGREG[k] not in regs]
        if not untouched or not all(k in slots for k in untouched):
            continue
        if any(k < len(names) for k in untouched):
            continue  # the caller has the parameter: passthrough_argument's step
        sites = list(re.finditer(rf'(?<![\w.>]){re.escape(callee)}\s*\(', part.clean[part.opening:part.end]))
        if len(sites) != 1:
            continue
        paren = part.opening + sites[0].end() - 1
        inner = part.clean[paren + 1:part.end]
        depth, stop = 0, None
        for i, ch in enumerate(inner):
            depth += (ch in '([{') - (ch in ')]}')
            if depth < 0:
                stop = paren + 1 + i
                break
        if stop is None:
            continue
        inner = part.clean[paren + 1:stop]
        spans = split_args(inner) if inner.strip() else []
        if len(spans) != count - len(untouched):
            continue
        matched = _definition(callees, callee)
        if matched is not None and len(matched) != count:
            continue
        if _header_counts(header, callee) - {count}:
            continue
        own = _header_counts(header, name)
        if own and own != {max(untouched) + 1}:
            continue  # the header declares the caller with its present parameters
        # the call: the caller's register at each untouched slot, the C's arguments filling the written ones in order
        given = iter(part.source[paren + 1 + x:paren + 1 + y].strip() for x, y in spans)
        edits = [(paren + 1, stop, ', '.join(f'arg{k}' if k in untouched else next(given) for k in range(count)))]
        # the caller's signature: the missing parameters up to the last untouched slot
        added = [f's32 arg{k}' for k in range(len(names), max(untouched) + 1)]
        start, end = head.start('params'), head.end('params')
        edits.append((start, end, ', '.join(params + added)))
        declaration = re.search(rf'(?m)^[^\n;{{}}#]*\b{re.escape(callee)}\s*\(([^()]*)\)\s*;',
                                part.clean[:head.start()])
        if declaration and '...' in declaration[1]:
            continue
        if declaration and declaration[1].strip() and declaration[1].strip() != 'void':
            types = _params(declaration[1])
            if len(types) != len(spans):
                continue
            new = [_type_only(p) for p in matched] if matched is not None else None
            if new is None:
                new = list(types)
                for k in untouched:
                    new.insert(k, 's32')
            edits.append((declaration.start(1), declaration.end(1), ', '.join(new)))
        text = edit(source, edits)
        if text != source:
            result.append((FAMILY, text))
    return result


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name', 'asm', 'header', 'callees'),
          'order': 60, 'archs': ('mips',)}  # the registry: no caller wiring (registry.py); `callees` from the caller

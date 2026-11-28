"""A display-list builder whose cursor is a parameter it returns, written as the SDK's Gbi macros on `Gfx *`.

`Gfx *draw(Gfx *gfx, ..) { gDPPipeSync(gfx++); .. return gfx; }` is how much of an N64 game's display-list code is
written. m2c reads it back as a `void *` parameter, a chain of `temp = cursor + 8` locals, the words stored through them
in the scheduler's order and the final cursor in a result local; with several switch arms it also keeps the arms' common
tail once behind a label and carries the cursor into it in more locals. `gbi_macro_commands` reads a cursor that lives
in a global (or behind `void **`), so it wrote nothing on such a draft.

This family turns the draft into one that run finder reads: a labelled straight run that ends in `break;` is copied over
each `goto` into it (the compiler cross-jumps the copies back together), the result local becomes the parameter, a plain
copy of a chain pointer becomes a derived pointer, and the parameter is shadowed by a pointer global. The parameter is
then declared `Gfx *` and every command is a macro on `gfx++`. A child is written only when no byte arithmetic on the
cursor is left, since `+ 8` would mean eight commands on the new type.

Measured on a 430-instruction N64 texture loader with three arms (SN GCC, `-G0 -mips3 -O2`): the m2c draft was 28740
and wrote no child before; the macro child was 26516. The draft's own computations of the load's words stay ahead of
the commands, so it is one step of a match, not the whole of it. One function."""
import re

from . import gbi_macro_commands as macros
from .integer_repair_support import IDENT, edit, view

FAMILY = 'gbi_value_cursor'
FAMILIES = (FAMILY,)
SHADOW = '__repair_cursor'
LIMIT = 2


def _switch_of(clean, position):
    """Where the innermost `switch` block holding `position` opens, or None."""
    depth = 0
    for i in range(position - 1, -1, -1):
        if clean[i] == '}':
            depth += 1
        elif clean[i] == '{':
            if depth:
                depth -= 1
            elif re.search(r'\bswitch\s*\([^{};]*\)\s*(?:/\*[^{}]*\*/\s*)?$', clean[:i]):
                return i
    return None


def _tail_copies(source, name):
    """Each `goto L;` replaced by the straight run `L: ..; break;` it jumps to, and the label dropped. Only where the
    copied `break` leaves the same switch, in a function without loops."""
    while True:
        part = view(source, name)
        if not part or re.search(r'\b(?:for|while|do)\b', part.clean[part.opening:part.end]):
            return source
        for label in re.finditer(rf'(?m)^[ \t]*(?P<l>{IDENT})[ \t]*:[ \t]*\n(?P<run>[^{{}}]*?\bbreak\s*;)',
                                 part.clean[part.opening:part.end]):
            if label['l'] == 'default' or re.search(r'\b(?:goto|case|default|return|if|else|switch)\b', label['run']):
                continue
            start, stop = part.opening + label.start(), part.opening + label.end()
            home = _switch_of(part.clean, start)
            jumps = list(re.finditer(rf'\bgoto\s+{label["l"]}\s*;', part.clean))
            if home is None or not jumps or any(
                    _switch_of(part.clean, jump.start()) != home or part.clean[:jump.start()].rstrip()[-1] not in '{};:'
                    for jump in jumps):
                continue
            begin = part.opening + label.start('run')
            run = source[begin:stop]
            edits = [(start, begin, '')] + [(jump.start(), jump.end(), run.strip()) for jump in jumps]
            source = edit(source, edits)
            break
        else:
            return source


def _chain(body, cursor):
    names = {cursor}
    while True:
        more = {m['y'] for m in re.finditer(rf'(?<![\w.>])(?P<y>{IDENT})\s*=\s*(?P<x>{IDENT})\s*(?:\+\s*\w+\s*)?;', body)
                if m['x'] in names} - names
        if not more:
            return names
        names |= more


def _stale(body, param, result):
    """True when the parameter is read on a path after the result was given another value: one name could not serve
    for both. A path ends at a `break`, a `return`, a `goto` or the next `case`."""
    for write in re.finditer(rf'(?<![\w.>]){result}\s*=(?!=)(?!\s*{param}\s*;)[^;]*;', body):
        rest = body[write.end():]
        leaves = re.search(r'\b(?:break|goto|case|default)\b|\breturn\b', rest)
        path = rest if not leaves else rest[:leaves.start()]
        if re.search(rf'(?<![\w.>]){param}\b', path) or (leaves and re.match(rf'return\s+{param}\b', rest[leaves.start():])):
            return True
    return False


def _shadowed(source, name):
    """(source with the cursor parameter shadowed by a pointer global, the parameter's name), or None."""
    part = view(source, name)
    if not part:
        return None
    head = part.clean.rfind('\n', 0, part.clean.rfind(name, 0, part.opening)) + 1
    body = part.clean[part.opening:part.end]
    returned = set(re.findall(rf'\breturn\s+({IDENT})\s*;', body))
    for found in re.finditer(rf'\b(?:void|Gfx)\s*\*\s*(?P<p>{IDENT})\s*(?=[,)])', part.clean[head:part.opening]):
        param = found['p']
        results = returned - {param}
        if not returned or len(results) > 1 or not re.search(rf'=\s*{param}\s*\+\s*(?:8|0x8)\s*;', body) \
                or re.search(rf'(?<![\w.>]){param}\s*(?:[-+]?=(?!=)|\+\+|--)', body):
            continue
        edits, words, declared = [], {param: SHADOW}, None
        if results:
            result = results.pop()
            declared = re.search(rf'(?m)^[ \t]*(?:void|Gfx|s32)\s*\*\s*{result}\s*;[ \t]*\n', body)
            if not declared or _stale(body, param, result):
                continue
            edits.append((part.opening + declared.start(), part.opening + declared.end(), ''))
            words[result] = SHADOW
        elif param not in returned:
            continue
        for m in re.finditer(rf'(?<![\w.>])(?:{"|".join(words)})\b', body):
            if declared and declared.start() <= m.start() < declared.end():
                continue
            edits.append((part.opening + m.start(), part.opening + m.end(), SHADOW))
        edits.append((head, head, f'extern void *{SHADOW};\n'))
        out = edit(source, edits)
        out = re.sub(rf'(?m)^[ \t]*{SHADOW}\s*=\s*{SHADOW}\s*;[ \t]*\n', '', out)
        shadow = view(out, name)
        if not shadow:
            continue
        inside = shadow.clean[shadow.opening:shadow.end]
        chain = _chain(inside, SHADOW) - {SHADOW}
        copies = [(shadow.opening + m.end('x'), shadow.opening + m.end('x'), ' + 0')
                  for m in re.finditer(rf'(?<![\w.>])(?P<y>{IDENT})\s*=\s*(?P<x>{IDENT})(?=\s*;)', inside)
                  if m['x'] in chain and m['y'] != SHADOW]
        return edit(out, copies) if copies else out, param
    return None


def variants(source, name, header=''):
    if SHADOW in source or not view(source, name):
        return []
    # a `case` label ends its own statement, so an arm's first command is not read as part of the label
    prepared = re.sub(r'(?m)^([ \t]*(?:case[ \t]+[^:;{}?\n]+|default):)', r'\1;', source)
    found = _shadowed(_tail_copies(prepared, name), name)
    if not found:
        return []
    shadow, param = found
    shadow = macros._explicit_reads(macros._arm_stores(shadow, name, {}), name, SHADOW)
    result = []
    for family, text in macros._variants(shadow, name, header):
        if family not in (macros.FAMILY, macros.RAW_FAMILY):
            continue
        text = text.replace(f'extern Gfx *{SHADOW};\n', '')
        # reads of the cursor the run finder left behind (a path that only returns it) stand for the parameter itself
        text = re.sub(r'(?m)^[ \t]*void \*_cur\d+;[ \t]*\n', '', text)
        for local in set(re.findall(rf'\b(_cur\d+)\s*=\s*{SHADOW}\s*;', text)):
            text = re.sub(rf'(?m)^[ \t]*{local}\s*=\s*{SHADOW}\s*;[ \t]*\n', '', text)
            text = re.sub(rf'\b{local}\b', SHADOW, text)
        part = view(text, name)
        if not part:
            continue
        body = part.clean[part.opening:part.end]
        left = re.sub(rf'\b{SHADOW}\+\+|\breturn\s+{SHADOW}\s*;', '', body)
        if SHADOW in left or re.search(r'\b_cur\d+\b', body):
            continue  # a command was not rewritten: its byte offsets would mean something else on a `Gfx *`
        text = text.replace(SHADOW, param)
        # typed after the run finder: a `Gfx` it already saw in the source it would take for the project's own
        text = re.sub(rf'\b{name}\s*\([^{{;]*\)\s*\{{',
                      lambda m: re.sub(rf'\b(?:void|Gfx)\s*\*\s*{param}\b', f'Gfx *{param}', m[0]), text, count=1)
        result.append((FAMILY, text))
    return result[:LIMIT]


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name', 'header'), 'archs': ('mips',)}

"""Restore literal call arguments once a native float setup carries the saved zero."""

import re
from collections import Counter

from .call_lifetime_repairs import block_path
from .integer_repair_support import IDENT, edit
from .natural_pointer_spill import _GOTO, _LABEL, _MUTATION, _WORD_FLOAT
from .operand_lifetime_repairs import _escaped, _visible
from .pattern_repairs import close

FAMILY = 'native_setup_call_zeros'
_MOVE = re.compile(r'move \$a1, (\$(?:s[0-7]|fp))')
_CALL = re.compile(rf'jal ({IDENT})')


def _witnesses(rows):
    counts = Counter()
    for i, (_, target, candidate) in enumerate(rows[:-1]):
        call = _CALL.fullmatch(target) if target == candidate else None
        if not call or rows[i + 1][1] != 'move $a1, $zero':
            continue
        if carrier := _MOVE.fullmatch(rows[i + 1][2]):
            counts[call[1], carrier[1]] += 1
    return {(name, reg) for (name, reg), count in counts.items() if count == 2}


def _phase_end(part, opening):
    end = close(part.clean, opening, '{', '}')
    if not end or re.search(r'\bgoto\s*\*', part.body):
        return None
    body = part.clean[opening:end]
    outside = part.clean[part.opening:opening] + part.clean[end:part.end]
    if set(_GOTO.findall(outside)).intersection(_LABEL.findall(body)):
        return None
    switches = {opening + hit.end() - 1 for hit in re.finditer(r'\bswitch\s*\([^;{}]+\)\s*{', body)}
    if any(not switches.intersection(block_path(part, opening + hit.start()))
           for hit in re.finditer(r'\b(?:default|case\s+[^:;{}]+)\s*:', body)):
        return None
    return end


def _private_zero_uses(part, word, init, end, param, macros, zero):
    owner, bits, number = (word[key] for key in ('owner', 'word', 'number'))
    raw = rf'{owner}\s*\.\s*{bits}'
    shift = rf'\(\s*{raw}\s*>>\s*16\s*\)\s*<<\s*16'
    zero_write = re.compile(rf'\s*\.\s*{bits}\s*=\s*(?:{zero}|0|{shift})\s*;')
    scalar_read = re.compile(rf'\s*\.\s*(?:{bits}|{number})\b(?!\s*(?:\)\s*)*{_MUTATION})')
    if _escaped(part.body, owner) or _escaped(part.body, param):
        return False
    for use in re.compile(rf'\b{owner}\b').finditer(part.clean, part.opening + 1, part.end):
        start, finish = use.span()
        if word.start() <= start < word.end() or init.start() <= start < init.end():
            continue
        if not init.end() <= start < end:
            return False
        before = part.clean[part.clean.rfind('\n', 0, start) + 1:start]
        after = part.clean[finish:end]
        line = before + owner + after.split('\n', 1)[0]
        if macros.intersection(re.findall(IDENT, line)) or re.search(r'(?:\+\+|--)\s*\(*\s*$', before):
            return False
        if not (zero_write.match(after) or scalar_read.match(after)):
            return False
    return True


def variants(source, name, rows, header='', max_bytes=65536):
    witnesses = _witnesses(rows)
    visible = _visible(source, name, header) if witnesses else None
    if not visible:
        return []
    part, context = visible
    macros = set(re.findall(rf'(?m)^\s*#\s*(?:define|undef)\s+({IDENT})', context))
    signature = part.clean[part.clean.rfind('}', 0, part.opening) + 1:part.opening]
    if any(' '.join(typ.split()) != 'unsigned int'
           for typ in re.findall(r'\btypedef\s+([^;{}]+?)\s+u32\s*;', context)):
        return []
    reads = re.compile(rf'(?m)^[ \t]*(?P<callee>{IDENT})\(\s*(?P<arg>{IDENT})\s*,\s*'
                       rf'(?P<value>\(\s*(?P<kind>s32|int)\s*\)\s*(?P<owner>{IDENT})'
                       rf'\s*\.\s*(?P<bits>{IDENT}))\s*\)\s*;')
    for callee, carrier in sorted(witnesses):
        sites = [hit for hit in reads.finditer(part.clean, part.opening + 1, part.end) if hit['callee'] == callee]
        if len(sites) != 2:
            continue
        arg, owner, bits, kind = (sites[0][key] for key in ('arg', 'owner', 'bits', 'kind'))
        prototype = rf'\b{callee}\s*\(\s*void\s*\*\s*(?:{IDENT}\s*)?,\s*{kind}(?:\s+{IDENT})?\s*\)\s*;'
        if (macros & {callee, arg, owner, bits, kind}
                or any(hit['owner'] != owner or hit['bits'] != bits or hit['arg'] != arg or hit['kind'] != kind
                       for hit in sites)
                or not re.search(prototype, context)
                or not re.search(rf'[(,]\s*void\s*\*\s*{arg}\s*[,)]', signature)
                or re.search(rf'\b{IDENT}\s+\**\s*{arg}\s*[,;=\[]', part.body)):
            continue
        words = [word for word in _WORD_FLOAT.finditer(part.clean, part.opening + 1, sites[0].start())
                 if word['owner'] == owner and word['word'] == bits]
        if len(words) != 1 or block_path(part, words[0].start()) != [part.opening]:
            continue
        word = words[0]
        typ = rf'{word["type"]}' if word['type'] == 'u32' else r'unsigned\s+int'
        if macros.intersection({word['type'], word['number'], word['float']}):
            continue
        zero = rf'\(\s*{typ}\s*\)\s*{arg}\s*&\s*~\s*\(\s*{typ}\s*\)\s*{arg}\b'
        initial = re.compile(rf'(?m)^[ \t]*{owner}\s*\.\s*{bits}\s*=\s*{zero}\s*;\s*{{')
        inits = list(initial.finditer(part.clean, word.end(), sites[0].start()))
        if len(inits) != 1 or not any(a == b == f'move {carrier}, $zero' for _, a, b in rows):
            continue
        init = inits[0]
        previous = part.clean[part.opening:init.start()].rstrip()
        while label := re.search(rf'\b{IDENT}\s*:$', previous):
            previous = previous[:label.start()].rstrip()
        if previous[-1:] not in ('{', '}', ';'):
            continue
        end = _phase_end(part, init.end() - 1)
        if not end or sites[-1].end() > end or not _private_zero_uses(part, word, init, end, arg, macros, zero):
            continue
        # The shape must already have the setup copy from the same word.
        raw = rf'{owner}\s*\.\s*{bits}'
        setup_copy = rf'{raw}\s*=\s*\(\s*{raw}\s*>>\s*16\s*\)\s*<<\s*16\s*;\s*{IDENT}\s*=\s*{owner}\s*\.\s*{word["number"]}\s*;'
        if not re.search(setup_copy, part.clean[init.end():sites[0].start()]):
            continue
        trial = edit(source, [(*site.span('value'), '0') for site in sites])
        if len(trial.encode()) <= max_bytes:
            return [(FAMILY, trial)]
    return []

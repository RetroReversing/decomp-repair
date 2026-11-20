"""Correct a repeated literal first argument when the target proves its value."""
import re

from .csource import _blank, find
from .integer_repair_support import edit
from .pattern_repairs import close
from .target_call_arity_repairs import IDENT, LINE
from .target_constant_repairs import LITERAL

FAMILY = 'target_call_constant'

IMMEDIATE = re.compile(r'\$a0,\s*\$zero,\s*(-?(?:0x[0-9a-fA-F]+|[0-9]+))')
SET = {'addiu', 'ori', 'daddiu'}
BRANCH = {'beq', 'bne', 'beqz', 'bnez', 'blez', 'bgtz', 'bltz', 'bgez'}
STRAIGHT = {'nop', 'lui', 'addu', 'daddu', 'or', 'move', 'sll', 'addiu', 'andi', 'ori',
            'lw', 'lbu', 'lb', 'lh', 'lhu', 'ld', 'sw', 'sb', 'sh', 'sd'}


def _code(asm):
    instructions, labels = [], {}
    for line in asm.splitlines():
        if label := re.fullmatch(r'\s*([.\w]+):\s*', line):
            labels[label[1]] = len(instructions)
        elif match := LINE.match(line):
            if match['op'] not in {'glabel', 'endlabel'}:
                instructions.append((match['op'], match['args'].strip()))
    return instructions, labels


def _value(instruction):
    op, args = instruction
    hit = IMMEDIATE.fullmatch(args) if op in SET else None
    if not hit:
        return None
    value = int(hit[1], 16 if '0x' in hit[1] else 10)
    return value if 0 <= value <= 32767 else None


def _diamond(code, labels, call):
    """Both paths reach one call with the immediate from the branch's common slot."""
    delay_op, delay_args = code[call + 1]
    if delay_op not in STRAIGHT or re.search(r'\$a0\b', delay_args):
        return None
    if any(op == 'jr' and operands != '$ra' for op, operands in code):
        return None
    for branch in range(max(0, call - 20), call - 4):
        op, args = code[branch]
        if op not in BRANCH:
            continue
        arm = labels.get(args.split(',')[-1].strip(), -1)
        if not branch + 3 < arm < call or code[arm - 2][0] != 'j':
            continue
        if labels.get(code[arm - 2][1]) != call:
            continue
        if set(labels.values()) & set(range(branch + 1, call)) != {arm}:
            continue
        # An extra transfer into either arm or the join could bypass the constant.
        entries = {label for label, at in labels.items() if at in {arm, call}}
        if any(index not in {branch, arm - 2} and mnemonic not in STRAIGHT
               and operands.split(',')[-1].strip() in entries
               for index, (mnemonic, operands) in enumerate(code)):
            continue
        paths = code[branch + 2:arm - 2] + code[arm - 1:call]
        if all(mnemonic in STRAIGHT and not re.search(r'\$a0\b', operands)
               for mnemonic, operands in paths):
            return _value(code[branch + 1])
    return None


def variants(source, name, asm):
    span = find(source, name)
    if not span or not asm or re.search(r'^\s*(?:/\*.*?\*/\s*)?\.(?:word|short|byte)\b', asm, re.M):
        return []
    clean = _blank(source)
    opening = clean.find('{', *span)
    end = close(clean, opening, '{', '}') if opening >= 0 else None
    if not end:
        return []

    code, labels = _code(asm)
    calls = {}
    for index, (op, callee) in enumerate(code[:-1]):
        if op == 'jal' and re.fullmatch(IDENT, callee):
            calls.setdefault(callee, []).append(index)
    result = []
    for callee, sites in calls.items():
        refs = list(re.finditer(r'(?<![.>\w])' + re.escape(callee) + r'\s*\(', clean[opening:end]))
        if len(refs) != 2 or len(sites) not in {1, 2}:
            continue
        values = [_value(code[index + 1]) if code[index + 1][0] in STRAIGHT else None for index in sites]
        if len(sites) == 1:
            values = [_diamond(code, labels, sites[0])] if values[0] is None else values
        if values[0] is None or len(set(values)) != 1:
            continue
        # Replace only the two first arguments. Preserve other uses of the old constant.
        pattern = re.compile(r'\s*(' + LITERAL.pattern + r')\s*[,)]')
        hits = [pattern.match(clean, opening + ref.end()) for ref in refs]
        if not all(hits) or hits[0][1] != hits[1][1]:
            continue
        literal = hits[0][2]
        if int(literal, 16 if literal.lower().startswith('0x') else 10) == values[0]:
            continue
        replacement = str(values[0]) + hits[0][3]
        result.append((FAMILY, edit(source, [(hit.start(1), hit.end(1), replacement) for hit in hits])))
        if len(result) == 4:
            break
    return result

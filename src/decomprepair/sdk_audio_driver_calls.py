"""Adapt SDK synthesizer calls when the target calls their driverless variants.

Some SDK revisions pass the synthesizer through the player; another SDK ABI uses a global driver and omits that
argument. A locally installed SDK's typed compact-sequence handler exposed the same layout and control flow as a
near-match in the latter ABI. Only propose a call when its driverless symbol is actually called by the target and a
prototype is available; the ordinary judge still decides whether the resulting source matches.
"""
import re

from .csource import _blank, find

FAMILY = 'sdk_audio_driver_calls'
NAMES = ('alSynSetVol', 'alSynSetPan', 'alSynSetPitch', 'alSynSetFXMix')
IDENT = r'[A-Za-z_]\w*'
CALL = re.compile(r'\b(?P<name>' + '|'.join(NAMES) + r')\s*\(\s*(?P<player>' + IDENT + r')\s*->\s*drvr\s*,\s*')


def variants(source, name, header='', asm=''):
    span = find(source, name)
    if not span or not asm:
        return []
    clean = _blank(source)
    body = clean[span[0]:span[1]]
    if re.search(r'\bvolatile\b|\b(?:asm|__asm__)\b|^\s*#', body, re.M):
        return []
    declarations = _blank(header + '\n' + source)
    edits = {}
    for found in CALL.finditer(clean, span[0], span[1]):
        original = found['name']
        replacement = 'n_' + original
        # A named target call, not a textual mention or an unverified SDK name, supplies the ABI evidence.
        if not re.search(r'\b(?:jal|jalx|bal)\s+' + re.escape(replacement) + r'\b', asm):
            continue
        if not re.search(r'\b(?:void|s32|u32|int)\s+' + re.escape(replacement) + r'\s*\(', declarations):
            continue
        # A volatile driver read is observable even though the driverless call does not consume it.
        if re.search(r'\bvolatile\b[^;{}]*\bdrvr\b|\bdrvr\b[^;{}]*\bvolatile\b', declarations):
            continue
        edits.setdefault(original, []).append((found.start(), found.end(), replacement + '('))
    # One target call cannot justify replacing several unrelated donor calls.
    for original, changes in list(edits.items()):
        replacement = 'n_' + original
        target_calls = len(re.findall(r'\b(?:jal|jalx|bal)\s+' + re.escape(replacement) + r'\b', asm))
        existing = len(re.findall(r'\b' + re.escape(replacement) + r'\s*\(', body))
        if target_calls < len(changes) + existing:
            del edits[original]
    if not edits:
        return []

    def apply(changes):
        text = source
        for start, end, replacement in sorted(changes, reverse=True):
            text = text[:start] + replacement + text[end:]
        return FAMILY, text

    out = [apply(changes) for changes in edits.values()]
    all_changes = [change for changes in edits.values() for change in changes]
    combined = apply(all_changes)
    if combined not in out:
        out.append(combined)
    return out


REPAIR = {'families': (FAMILY,), 'variants': variants, 'needs': ('source', 'name', 'header', 'asm'), 'archs': ('mips',)}

"""arm_scratch_merge: arm scratch locals folded into the local that takes over, and a shared scratch split per arm."""
from decomprepair import arm_scratch_merge as asm
from decomprepair import registry

SOURCE = '''void use(void *, s32, s32);

void f(void *p, s32 mode, s32 n) {
    u8 low;
    u8 low2;
    s32 keep;
    s32 pad;

    pad = n + 6;
    if (n > pad) {
        use(p, pad, 0);
    }
    if (mode == 1) {
        low = (n & 0x3F) & 0xFF;
        pad = (u8) (low & 0x1F);
        use(p, low >> 5, pad);
        keep = pad;
    } else {
        low2 = (n & 3) & 0xFF;
        pad = (u8) (low2 & 7);
        use(p, low2, pad);
        keep = pad;
    }
    use(p, keep, 1);
}
'''


def by_family(family):
    return [text for name, text in asm.variants(SOURCE, 'f') if name == family]


def test_the_arm_scratch_is_folded_into_the_local_assigned_after_it():
    out = by_family(asm.FAMILY_MERGE)
    assert out
    assert all('low' not in text for text in out)  # `low` and `low2` are `keep` now
    assert 'keep = (n & 0x3F) & 0xFF;' in out[0]
    assert 'u8 keep;' in out[0] and 's32 keep;' not in out[0]  # the narrow type moves with it (one child keeps `s32`)
    assert any('s32 keep;' in text for text in out)


def test_the_shared_scratch_gets_a_name_per_arm():
    out = by_family(asm.FAMILY_SPLIT)
    assert out
    text = out[0]
    assert 'pad_a = (u8) (low & 0x1F);' in text and 'pad_b = (u8) (low2 & 7);' in text
    assert 'pad = n + 6;' in text and 'use(p, pad, 0);' in text  # the head keeps the name
    assert 's32 pad_a;' in text and 's32 pad_b;' in text


def test_both_halves_are_one_child():
    both = by_family(asm.FAMILY)
    assert both
    assert any('pad_a' in text and 'low' not in text for text in both)


def test_a_scratch_read_after_the_arms_is_not_folded():
    source = SOURCE.replace('    use(p, keep, 1);', '    use(p, keep, low);')
    assert all('u8 low;' in t for n, t in asm.variants(source, 'f') if n == asm.FAMILY_MERGE)


def test_an_address_taken_scratch_is_left_alone():
    source = SOURCE.replace('use(p, low >> 5, pad);', 'use(&low, low >> 5, pad);')
    assert all('&low' in t and 'u8 low;' in t for n, t in asm.variants(source, 'f') if n == asm.FAMILY_MERGE)


def test_a_backward_jump_leaves_the_split_alone():
    source = SOURCE.replace('    pad = n + 6;', 'again:\n    pad = n + 6;').replace('    use(p, keep, 1);', '    use(p, keep, 1);\n    if (n-- > 0) goto again;')
    assert not [t for n, t in asm.variants(source, 'f') if n == asm.FAMILY_SPLIT]


def test_it_declares_itself_to_the_registry():
    repair = registry.get('arm_scratch_merge')
    assert repair is not None and registry.problems(repair) == []

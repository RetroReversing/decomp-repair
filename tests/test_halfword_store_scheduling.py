from decomprepair.halfword_store_scheduling import probes

SOURCE = '''void f(void) {
    value = *(volatile s32 *)(input + src);
    i++;
    src += 8;
    *(s32 *)(output + dst) = value;
}'''
ASM = '''/* address */ lh $v0, %lo(input)($v0)
    addiu $s0, $s0, 1
    lui $at, %hi(output)
    sw $v0, %lo(output)($at)
'''
PROFILE = {'toolchain': 'gcc-2.7.2-kmc', 'flags': ['-O2', '-fschedule-insns']}


def proposals(source=SOURCE, asm=ASM):
    return probes({'arch': 'mips'}, {'name': 'f', 'best_source': source, 'asm': asm}, PROFILE)


def test_pairs_both_source_edits_with_the_scheduling_flag():
    [(flags, child)] = proposals()
    assert flags == ('-O2', '-fno-schedule-insns')
    assert child == SOURCE.replace('volatile s32', 's16').replace('*(s32 *)', '*(volatile s32 *)')


def test_requires_matching_signed_load_and_word_store_with_same_value():
    assert not proposals(asm=ASM.replace('lh ', 'lhu '))
    assert not proposals(asm=ASM.replace('sw $v0', 'sw $v1'))
    assert not proposals(asm=ASM.replace('%lo(output)', '%lo(other)'))
    assert not proposals(SOURCE.replace('= value;', '= other;'))
    assert not proposals(SOURCE.replace('i++;', 'use(value);'))
    assert not proposals(SOURCE.replace("i++;", "value++;"))

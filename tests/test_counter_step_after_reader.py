from decomprepair import counter_step_after_reader as repair

SOURCE = '''extern char names[];
void drawRow(s32, s32);

void drawColumn(void) {
    s32 y;
    u32 i;
    u8 id;

    i = 0;
    y = 0x20;
    do {
        id = 0;
        if (gMode == 1) {
            goto block_3;
        }
        if (gMode == 2) {
block_3:
            id = names[i];
        }
        y += 0xC;
        i += 1;
        drawRow(id, y);
    } while (i < 4U);
}
'''

ASM = '''
.L80001000:
/* 000 80001000 02203021 */  addu       $a1, $s1, $zero
.L80001004:
/* 004 80001004 2631000C */  addiu      $s1, $s1, 0xC
/* 008 80001008 26100001 */  addiu      $s0, $s0, 0x1
/* 00C 8000100C 0C000000 */  jal        drawRow
/* 010 80001010 00802021 */  addu       $a0, $a0, $zero
'''


def test_moves_the_step_run_after_the_call_that_reads_it():
    children = dict(repair.variants(SOURCE, 'drawColumn', ASM))
    moved = children[repair.FAMILY]
    assert 'drawRow(id, y);\n        y += 0xC;\n        i += 1;\n    } while' in moved
    combined = children[repair.COMBINED]
    assert 'drawRow(id, (0x20 + i * 0xC));\n        i += 1;\n    } while' in combined
    assert 'goto' not in combined and 'block_3' not in combined


def test_needs_the_copy_before_the_step():
    assert repair.variants(SOURCE, 'drawColumn') == []
    after = ASM.replace('addu       $a1, $s1, $zero', 'nop').replace(
        'addiu      $s0, $s0, 0x1', 'addu       $a1, $s1, $zero')
    assert repair.variants(SOURCE, 'drawColumn', after) == []


def test_the_copy_must_reach_the_callee():
    rewritten = ASM.replace('addu       $a0, $a0, $zero', 'addiu      $a1, $zero, 0x1')
    assert repair.variants(SOURCE, 'drawColumn', rewritten) == []
    other = ASM.replace('0xC\n', '0x8\n')
    assert repair.variants(SOURCE, 'drawColumn', other) == []


def test_leaves_a_stepped_name_the_call_also_computes_with():
    source = SOURCE.replace('drawRow(id, y);', 'drawRow(y + 1, y);')
    assert repair.variants(source, 'drawColumn', ASM) == []

from decomprepair import call_argument_width as repair
from decomprepair import guarded_sentinel_while

ASM = '''glabel f
addu       $s1, $a0, $zero
.L1:
sw         $s2, 0x28($sp)
andi       $a1, $s1, 0xffff
jal        draw
andi       $a2, $fp, 0xff
jal        other
nop
'''

SOURCE = '''void draw(s32 *, s32, s32);
void f(s32 x0, s32 y0) {
    s32 x;
    s32 y;
    x = x0;
    y = y0;
    draw(0, x, y);
}
'''


def test_locals_and_prototype_take_the_target_widths():
    assert repair.witnessed(ASM) == {'draw': {1: 'u16', 2: 'u8'}}
    children = repair.variants(SOURCE, 'f', ASM)
    both = children[0]
    assert both[0] == repair.LOCAL
    assert 'u16 x;' in both[1] and 'u8 y;' in both[1]
    prototype = dict(children)[repair.PROTOTYPE]
    assert 'void draw(s32 *, u16, u8);' in prototype
    assert any('u16 x;' in child and 's32 y;' in child for _, child in children)


def test_no_witness_no_child():
    assert repair.variants(SOURCE, 'f', 'jal draw\nmove $a1, $s1\n') == []
    assert repair.variants(SOURCE, 'f', '') == []


FOLDED = '''void f(u8 flag, s32 a) {
    u16 t[16];
    s32 i;
    s32 s;
    s = a;
    if (flag != 0 && t[8] == 0) {
        i = 0;
        do {
            t[8 + i] = 0xFFFF;
            i++;
        } while (t[8 + i] == 0 && i < 4);
        s = a;
    }
    use(s, t);
}
'''


def test_first_test_in_the_guard_becomes_a_while():
    children = dict(guarded_sentinel_while.variants(FOLDED, 'f'))
    child = children[guarded_sentinel_while.FIRST]
    assert 'if (flag != 0) { i = 0; while (t[8 + i] == 0 && i < 4) {' in child
    assert 's = a;\n    }\n    use' in child


def test_first_test_keeps_a_statement_that_is_not_repeated():
    source = FOLDED.replace('        s = a;\n    }', '        s = 0;\n    }')
    assert guarded_sentinel_while.FIRST not in dict(guarded_sentinel_while.variants(source, 'f'))

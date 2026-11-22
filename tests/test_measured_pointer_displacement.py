from decomprepair.measured_pointer_displacement import variants

SOURCE = '''void f(void *base, s32 length) {
    void *end;
    end = (base + length) - 0x14;
    M2C_FIELD(base, void **, 0) = end;
}'''
ROWS = [(' ', 'addu $a1, $a0, $a1', 'addu $a1, $a0, $a1'),
        ('r', 'addiu $a1, $a1, -0x14', 'addiu $v0, $a1, -0x14')]


def test_split_pointer_displacement():
    result=variants(SOURCE,'f','',ROWS)
    assert len(result)==1
    assert 'end = base + length; end = (void *)((char *)end - 0x14);' in result[0][1]


def test_requires_evidence_and_unescaped_ordinary_pointer():
    assert not variants(SOURCE,'f','',[])
    assert not variants(SOURCE.replace('0x14','0x10'),'f','',ROWS)
    assert not variants(SOURCE.replace('void *end;', 'void *end; save(&end);'),'f','',ROWS)
    assert not variants(SOURCE.replace('void *end;', 'void *volatile end;'),'f','',ROWS)
    assert not variants(SOURCE,'f','#define length get_length()',ROWS)

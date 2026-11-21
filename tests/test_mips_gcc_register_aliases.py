from decomprepair.mips import gcc_register_aliases


def test_gprs_and_fprs_are_named_and_nothing_else_is():
    assert gcc_register_aliases(16) == ('s0', '16')
    assert gcc_register_aliases(30) == ('fp', '30', 's8')
    # GCC 2.x numbers the FPRs 32-63: a float pseudo "in 52" is $f20
    assert gcc_register_aliases(52) == ('f20', '52')
    assert gcc_register_aliases(32) == ('f0', '32')
    assert gcc_register_aliases(64) == () and gcc_register_aliases(-1) == ()

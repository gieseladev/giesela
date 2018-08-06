from giesela.lib.ui import create_bar


def test_bar():
    assert create_bar(.5) == "■■■■■□□□□□"
    assert create_bar(.33, length=30) == "■■■■■■■■■■□□□□□□□□□□□□□□□□□□□□"
    assert create_bar(.75, half_char="O") == "■■■■■■■O□□"

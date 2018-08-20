from giesela.lib.ui import create_bar, create_player_bar, create_scroll_bar


def test_bar():
    assert create_bar(.5) == "■■■■■□□□□□"
    assert create_bar(.33, length=30) == "■■■■■■■■■■□□□□□□□□□□□□□□□□□□□□"
    assert create_bar(.75, half_char="O") == "■■■■■■■O□□"
    assert create_scroll_bar(.6, .3) == "□□□□□□■■■□"
    assert create_scroll_bar(1, 0) == "□□□□□□□□□■"
    assert create_scroll_bar(0.967, .079, length=33) == "□□□□□□□□□□□□□□□□□□□□□□□□□□□□□□□■■■■"
    assert create_player_bar(1) == "▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬🔘"
    assert create_player_bar(.5) == "▬▬▬▬▬▬▬▬▬🔘▬▬▬▬▬▬▬▬▬▬"
    assert create_player_bar(0) == "🔘▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬"

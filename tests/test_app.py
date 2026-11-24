

def test_extracted_folders_open_in_pr7e_only_when_it_is_the_folder_app(tmp_path, monkeypatch):
    from pr7z import app, family
    a, b = tmp_path / "a", tmp_path / "b"
    a.mkdir()
    b.mkdir()
    opened = []
    monkeypatch.setattr(family, "pr7e_for_folders", lambda: False)
    assert app.show_extracted([str(a)], launch=lambda name, args: opened.append(args)) == [] and opened == []
    monkeypatch.setattr(family, "pr7e_for_folders", lambda: True)
    shown = app.show_extracted([str(a), str(a), str(b), str(tmp_path / "gone")],
                               launch=lambda name, args: opened.append((name, args)))
    assert shown == [str(a), str(b)] and opened == [("PR7-E", [str(a)]), ("PR7-E", [str(b)])]

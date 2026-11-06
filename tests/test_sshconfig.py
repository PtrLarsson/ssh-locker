from ssh_locker.sshconfig import ImportedHost, parse_ssh_config


def write(tmp_path, text, name="config"):
    path = tmp_path / name
    path.write_text(text)
    return path


def test_basic_host(tmp_path):
    path = write(
        tmp_path,
        "Host web\n  HostName web.example.com\n  Port 2222\n  User deploy\n",
    )
    assert parse_ssh_config(path) == [
        ImportedHost("web", "web.example.com", 2222, "deploy")
    ]


def test_defaults(tmp_path):
    path = write(tmp_path, "Host bare\n")
    assert parse_ssh_config(path) == [ImportedHost("bare", "bare", 22, "")]


def test_wildcards_skipped(tmp_path):
    path = write(
        tmp_path,
        "Host *\n  User x\nHost *.corp\nHost a?\nHost !nope\nHost real\n",
    )
    assert [h.alias for h in parse_ssh_config(path)] == ["real"]


def test_multiple_aliases_on_one_line(tmp_path):
    path = write(tmp_path, "Host a b\n  HostName shared.example\n  Port 2200\n")
    assert parse_ssh_config(path) == [
        ImportedHost("a", "shared.example", 2200, ""),
        ImportedHost("b", "shared.example", 2200, ""),
    ]


def test_match_block_skipped(tmp_path):
    path = write(
        tmp_path,
        "Host one\n  HostName one.example\n"
        "Match host two\n  HostName leaked.example\n  User leaked\n"
        "Host three\n  HostName three.example\n",
    )
    assert parse_ssh_config(path) == [
        ImportedHost("one", "one.example", 22, ""),
        ImportedHost("three", "three.example", 22, ""),
    ]


def test_include_followed(tmp_path):
    write(tmp_path, "Host inc\n  HostName inc.example\n", name="extra")
    sub = tmp_path / "conf.d"
    sub.mkdir()
    (sub / "a.conf").write_text("Host globbed\n  HostName g.example\n")
    path = write(tmp_path, "Include extra\nInclude conf.d/*.conf\nHost main\n")
    assert [h.alias for h in parse_ssh_config(path)] == ["inc", "globbed", "main"]


def test_include_cycle_and_missing_file(tmp_path):
    path = write(
        tmp_path,
        "Include config\nInclude does-not-exist\nHost ok\n  HostName ok.example\n",
    )
    assert parse_ssh_config(path) == [ImportedHost("ok", "ok.example", 22, "")]


def test_missing_config_returns_empty(tmp_path):
    assert parse_ssh_config(tmp_path / "nope") == []


def test_case_insensitive_keywords_and_equals_syntax(tmp_path):
    path = write(tmp_path, "host=x\n  hostname=x.example\n  PORT 2022\n  user=me\n")
    assert parse_ssh_config(path) == [ImportedHost("x", "x.example", 2022, "me")]

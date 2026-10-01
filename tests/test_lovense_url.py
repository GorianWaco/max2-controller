from max2_controller.backends.lovense_local import (
    _url_for_game_port,
    build_phone_api_url,
    lan_hosts,
    parse_phone_api_url,
    phone_api_candidates,
)


def test_build_phone_url() -> None:
    assert (
        build_phone_api_url("192.168.0.15", 30010)
        == "https://192-168-0-15.lovense.club:30010/command"
    )
    assert build_phone_api_url("127.0.0.1", 20010) == "http://127.0.0.1:20010/command"


def test_phone_candidates_cover_http_and_https() -> None:
    urls = phone_api_candidates("192.168.0.15", 30010)
    assert urls[0] == "https://192-168-0-15.lovense.club:30010/command"
    assert "http://192.168.0.15:20010/command" in urls
    assert len(urls) <= 4
    typed = phone_api_candidates("192.168.0.15", 20011)
    assert typed[0] == "http://192.168.0.15:20011/command"
    assert "https://192-168-0-15.lovense.club:30011/command" in typed


def test_lan_hosts_skip_self() -> None:
    hosts = lan_hosts("192.168.0.15")
    assert len(hosts) == 253
    assert "192.168.0.15" not in hosts
    assert hosts[0] == "192.168.0.1"
    assert hosts[-1] == "192.168.0.254"
    assert lan_hosts("nie-ip") == []


def test_game_port_url_scheme() -> None:
    assert _url_for_game_port("192.168.0.5", 20010) == "http://192.168.0.5:20010/command"
    assert (
        _url_for_game_port("192.168.0.5", 30010)
        == "https://192-168-0-5.lovense.club:30010/command"
    )


def test_parse_phone_url() -> None:
    ip, port = parse_phone_api_url("https://192-168-0-15.lovense.club:30010/command")
    assert ip == "192.168.0.15"
    assert port == 30010
    ip, port = parse_phone_api_url("http://127.0.0.1:20010/command")
    assert ip == "127.0.0.1"
    assert port == 20010

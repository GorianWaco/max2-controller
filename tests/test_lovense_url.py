from max2_controller.backends.lovense_local import build_phone_api_url, parse_phone_api_url


def test_build_phone_url() -> None:
    assert (
        build_phone_api_url("192.168.0.15", 30010)
        == "https://192-168-0-15.lovense.club:30010/command"
    )
    assert build_phone_api_url("127.0.0.1", 20010) == "http://127.0.0.1:20010/command"


def test_parse_phone_url() -> None:
    ip, port = parse_phone_api_url("https://192-168-0-15.lovense.club:30010/command")
    assert ip == "192.168.0.15"
    assert port == 30010
    ip, port = parse_phone_api_url("http://127.0.0.1:20010/command")
    assert ip == "127.0.0.1"
    assert port == 20010

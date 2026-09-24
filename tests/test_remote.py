import threading

from jetson_player.remote.auth import RemoteAuth, generate_pin
from jetson_player.remote.events import EventBroker


class Clock:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t


def test_pin_login_and_token_persistence(tmp_path):
    f = str(tmp_path / "tokens.json")
    auth = RemoteAuth("1234", f)
    assert auth.login("1.1.1.1", "0000") is None
    token = auth.login("1.1.1.1", "1234")
    assert token and auth.is_valid(token)
    assert not auth.is_valid("forged") and not auth.is_valid("")
    assert RemoteAuth("1234", f).is_valid(token)            # 재시작 후에도 유지
    assert token not in open(f).read()                        # 원문 토큰은 저장하지 않음


def test_bruteforce_lockout_and_expiry(tmp_path):
    clock = Clock()
    auth = RemoteAuth("4321", str(tmp_path / "t.json"), now=clock)
    for _ in range(8):
        assert auth.login("9.9.9.9", "0000") is None
    assert auth.login("9.9.9.9", "4321") == "locked"         # 맞는 PIN이어도 잠금 중
    assert auth.login("8.8.8.8", "4321") not in (None, "locked")  # 다른 IP는 영향 없음
    clock.t += 301
    assert auth.login("9.9.9.9", "4321") not in (None, "locked")


def test_reset_revokes_tokens(tmp_path):
    auth = RemoteAuth("1111", str(tmp_path / "t.json"))
    token = auth.login("1.1.1.1", "1111")
    auth.reset("2222")
    assert not auth.is_valid(token)
    assert auth.login("1.1.1.1", "1111") is None


def test_generate_pin():
    pins = {generate_pin() for _ in range(50)}
    assert all(len(p) == 4 and p.isdigit() for p in pins) and len(pins) > 1


def test_event_broker_dedup_and_wait():
    b = EventBroker()
    assert b.publish("status", {"a": 1}) is True
    assert b.publish("status", {"a": 1}) is False           # 같은 내용은 재전송 안 함
    items, ver = b.wait_newer(0, timeout=0.01)
    assert items == [("status", '{"a":1}')]
    got = []
    t = threading.Thread(target=lambda: got.append(b.wait_newer(ver, timeout=2)))
    t.start()
    b.publish("playlist", [1, 2])
    t.join(3)
    assert got and got[0][0] == [("playlist", "[1,2]")]
    items, _ = b.wait_newer(got[0][1], timeout=0.01)
    assert items == []

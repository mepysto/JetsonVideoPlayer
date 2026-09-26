"""SSE(Server-Sent Events) 방송: 메인 스레드가 상태를 게시하면 연결된 리모컨들이 즉시 받습니다."""
import json
import threading


class EventBroker:
    def __init__(self):
        self.cond = threading.Condition()
        self.version = 0
        self.latest = {}            # 이벤트 이름 → (버전, JSON 문자열)
        self.closed = False

    def publish(self, name, payload):
        """payload가 직전과 같으면 보내지 않습니다. 새로 게시했으면 True."""
        data = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
        with self.cond:
            prev = self.latest.get(name)
            if prev and prev[1] == data:
                return False
            self.version += 1
            self.latest[name] = (self.version, data)
            self.cond.notify_all()
            return True

    def snapshot(self):
        with self.cond:
            return self.version, dict(self.latest)

    def wait_newer(self, since, timeout):
        """since 이후 게시된 [(이름, JSON)] 과 새 버전을 반환 (timeout이면 빈 목록)."""
        with self.cond:
            if self.version <= since and not self.closed:
                self.cond.wait(timeout)
            items = [(name, data) for name, (ver, data) in self.latest.items() if ver > since]
            return items, self.version

    def close(self):
        with self.cond:
            self.closed = True
            self.cond.notify_all()

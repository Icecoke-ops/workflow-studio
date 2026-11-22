"""fd 级日志接管：用 ``os.pipe`` + ``os.dup2`` 拿到 fd 1/2 的字节流，切成行交给回调。

不是替换 ``sys.stdout``——插件里 ``os.write(1, ...)`` 这种 C 层输出也能抓到。
"""

import codecs
import os
import re
import sys
import threading
import time
from collections import deque

CR_WINDOW = 0.5  # 同节点连续 \r 的合并窗口（秒）
ANSI_RE = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")
LINE_RE = re.compile(r"\r\n|\r|\n")
# 节点切换前的同步标记：写进 fd 1/2，读线程处理到它就说明之前的字节都已发出
SYNC_RE = re.compile("\x00\x01FDSYNC(\\d+)\x02")


class FdLog:
    """接管 fd 1/2，把输出按行交给 ``emit(node, stream, text)``。"""

    def __init__(self, emit, current_node):
        self._emit = emit  # (node, stream, text)
        self._current_node = current_node
        self._saved = []  # [(fd, dup 出来的原 fd)]
        self._reads = {}
        self._readers = []
        self._pending = {}  # (node, stream) -> [text, deadline]
        self._pending_lock = threading.Lock()
        self._closed = threading.Event()
        self._fd_lock = threading.Lock()  # sync 写标记与 stop 还原 fd 互斥
        self._active = False
        self._sync_lock = threading.Lock()
        self._sync_id = 0
        self._syncs = {}  # 标记号 -> [Event, {看到它的流}]

    def start(self):
        sys.stdout.flush()
        sys.stderr.flush()
        os.environ["PYTHONUNBUFFERED"] = "1"
        try:
            for fd, stream in ((1, "stdout"), (2, "stderr")):
                read_fd, write_fd = os.pipe()
                try:
                    saved = os.dup(fd)
                    self._saved.append((fd, saved))  # 先记账，dup2 失败也还原得回来
                    os.dup2(write_fd, fd)
                except BaseException:
                    os.close(read_fd)  # 半途失败不能把管道句柄漏掉
                    os.close(write_fd)
                    raise
                os.close(write_fd)
                self._reads[stream] = read_fd
                reader = threading.Thread(
                    target=self._pump, args=(read_fd, stream), daemon=True
                )
                self._readers.append(reader)
                reader.start()
            for stream in (sys.stdout, sys.stderr):
                try:
                    # write_through：进度条那种不带换行的 \r 写入也要立刻进管道
                    stream.reconfigure(line_buffering=True, write_through=True)
                except Exception:
                    pass
            threading.Thread(target=self._flush_loop, daemon=True).start()
            self._active = True
        except BaseException:
            self.stop()  # 半途失败也要还原 fd 1/2，否则进程再也看不到输出
            raise

    def sync(self, timeout):
        """往 fd 1/2 各写一个标记并等读线程处理到它：之前的字节一定已解析并发出。

        节点切换前用它替代「睡一会儿」：空闲节点零等待，最坏等 ``timeout`` 秒。
        """
        with self._fd_lock:
            if not self._active:
                return
            # 先 flush：不带换行的半行还压在 Python 缓冲里，标记一进管道就会
            # 把「节点边界」划在半行之前，那半行就会挂到下一个节点上
            for stream in (sys.stdout, sys.stderr):
                try:
                    stream.flush()
                except Exception:
                    pass
            with self._sync_lock:
                self._sync_id += 1
                token = self._sync_id
                event = threading.Event()
                self._syncs[token] = [event, set()]
            marker = f"\x00\x01FDSYNC{token}\x02\n".encode("ascii")
            for fd in (1, 2):
                try:
                    os.write(fd, marker)
                except OSError:
                    pass
        event.wait(timeout)
        with self._sync_lock:
            self._syncs.pop(token, None)

    def _mark_sync(self, token, stream):
        with self._sync_lock:
            entry = self._syncs.get(token)
            if entry is None:
                return
            entry[1].add(stream)
            if len(entry[1]) == 2:
                entry[0].set()

    def stop(self):
        self._active = False
        for stream in (sys.stdout, sys.stderr):
            try:
                stream.flush()
            except Exception:
                pass
        with self._fd_lock:
            for fd, saved in self._saved:
                try:
                    os.dup2(saved, fd)
                    os.close(saved)
                except OSError:
                    pass
            self._saved = []
        for reader in self._readers:
            reader.join(timeout=2)
        self._closed.set()
        self._flush(expired_only=False)
        for read_fd in self._reads.values():
            try:
                os.close(read_fd)
            except OSError:
                pass
        self._reads = {}

    # -- 读 --------------------------------------------------------------
    def _pump(self, read_fd, stream):
        decoder = codecs.getincrementaldecoder("utf-8")("replace")
        buffer = ""
        while True:
            try:
                chunk = os.read(read_fd, 65536)
            except OSError:
                break
            if not chunk:
                break
            buffer = self._parse(buffer + decoder.decode(chunk), stream)
        buffer += decoder.decode(b"", True)
        self._parse(buffer, stream, final=True)

    def _parse(self, buffer, stream, final=False):
        while True:
            match = LINE_RE.search(buffer)
            if match is None:
                break
            text, buffer = buffer[: match.start()], buffer[match.end():]
            if match.group() == "\r":
                self._progress(stream, text)
            else:
                self._line(stream, text)
        if final and buffer:
            self._line(stream, buffer)
        return buffer

    def _line(self, stream, text):
        self._flush(stream=stream)  # 先吐掉这条流上挂着的 \r 行，保持顺序
        matches = SYNC_RE.findall(text)
        node = self._current_node()
        if matches:
            text = SYNC_RE.sub("", text)
            if text:
                self._emit(node, stream, ANSI_RE.sub("", text))
            # 回执放最后：_enter_node 一收到回执就切 _log_node，
            # 先回执再取标签的话，标记终结的这行会挂到下一个节点上
            for token in matches:
                self._mark_sync(int(token), stream)
            return
        self._emit(node, stream, ANSI_RE.sub("", text))

    def _progress(self, stream, text):
        node = self._current_node()
        with self._pending_lock:
            self._pending[(node, stream)] = [
                ANSI_RE.sub("", text),
                time.monotonic() + CR_WINDOW,
            ]

    # -- 合并 / 定时器 ---------------------------------------------------
    def _flush_loop(self):
        while not self._closed.wait(0.05):
            self._flush(expired_only=True)

    def _flush(self, stream=None, expired_only=False):
        ready = []
        now = time.monotonic()
        with self._pending_lock:
            for key, (text, deadline) in list(self._pending.items()):
                node, pending_stream = key
                if stream is not None and pending_stream != stream:
                    continue
                if expired_only and deadline > now:
                    continue
                ready.append((node, pending_stream, text))
                del self._pending[key]
        for node, pending_stream, text in ready:
            self._emit(node, pending_stream, text)


class Outbox:
    """每条连接的待发送队列：满了丢最旧的，读线程 put 永不阻塞、内存也不涨。"""

    def __init__(self, limit):
        self._items = deque(maxlen=limit)
        self._cond = threading.Condition()
        self._closed = False

    def put(self, payload):
        with self._cond:
            if self._closed:
                return
            self._items.append(payload)  # deque 满了会自动丢最旧的
            self._cond.notify()

    def get(self):
        with self._cond:
            while not self._items and not self._closed:
                self._cond.wait()
            if not self._items:
                return None
            return self._items.popleft()

    def close(self):
        with self._cond:
            self._closed = True
            self._cond.notify_all()

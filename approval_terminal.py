"""Own the real terminal; the sandbox receives a separate PTY, never approval input."""
import fcntl
import os
import pty
import queue
import re
import select
import signal
import subprocess
import sys
import termios
import textwrap
import time
import tty

from host_change import description


def write(fd, data):
    while data:
        data = data[os.write(fd, data):]


def dimensions(fd):
    try:
        size = os.get_terminal_size(fd)
        return size.columns or 80, size.lines or 24
    except OSError:
        return 80, 24


def draw(request, output_fd, offset):
    width, height = dimensions(output_fd)
    lines = []
    for line in description(request).splitlines():
        lines.extend(textwrap.wrap(line, width - 4, replace_whitespace=False) or [""])
    page = height - 5
    offset = min(max(0, offset), max(0, len(lines) - page))
    screen = "\x1b[0m\x1b[2J\x1b[H"
    for row, line in enumerate(lines[offset:offset + page], start=1):
        screen += f"\x1b[{row};3H" + line
    screen += f"\x1b[{height - 3};3HZeilen {offset + 1}-{min(offset + page, len(lines))}/{len(lines)} | Scroll: Pfeile/Mausrad"
    screen += f"\x1b[{height - 1};3H\x1b[30;47m[ Allow once ]\x1b[0m"
    screen += f"\x1b[{height - 1};20H\x1b[30;47m[ Reject ]\x1b[0m"
    write(output_fd, screen.encode())
    return offset, width, height


def escape_sequence(input_fd):
    result = bytearray()
    for _ in range(64):
        if not select.select([input_fd], [], [], 0.05)[0]:
            break
        part = os.read(input_fd, 1)
        if not part:
            break
        result.extend(part)
        if len(result) > 1 and 64 <= part[0] <= 126:
            break
        if len(result) == 1 and part not in (b"[", b"O"):
            break
    return bytes(result)


def ask(request, input_fd, output_fd):
    width, height = dimensions(output_fd)
    if width < 40 or height < 10:
        return False
    termios.tcflush(input_fd, termios.TCIFLUSH)
    # Save the TUI modes, then use SGR coordinates only for our own buttons.
    mouse_modes = b"1000;1002;1003;1005;1006;1015;1016"
    write(output_fd, b"\x1b[?" + mouse_modes + b"s\x1b[?" + mouse_modes + b"l")
    # Mode 47 switches buffers without erasing the TUI's existing screen on return.
    write(output_fd, b"\x1b[?25;2004s\x1b7\x1b[?47l\x1b[0m\x1b[?25l\x1b[?2004h\x1b[?1000h\x1b[?1006h")
    offset, width, height = draw(request, output_fd, 0)
    pasted = False
    try:
        while time.monotonic() < request.deadline:
            current_width, current_height = dimensions(output_fd)
            if current_width < 40 or current_height < 10:
                return False
            if dimensions(output_fd) != (width, height):
                offset, width, height = draw(request, output_fd, offset)
            if not select.select([input_fd], [], [], 0.25)[0]:
                continue
            char = os.read(input_fd, 1)
            if not char or char in (b"\x03", b"\x04"):
                return False
            if char == b"\x1b":
                seq = escape_sequence(input_fd)
                if not seq:
                    return False
                if seq in (b"[200~", b"[201~"):
                    pasted = seq == b"[200~"
                    continue
                if pasted:
                    continue
                mouse = re.fullmatch(rb"\[<(\d+);(\d+);(\d+)([Mm])", seq)
                if mouse:
                    button, x, y = map(int, mouse.groups()[:3])
                    if button == 0 and mouse[4] == b"M" and y == height - 1:
                        if 3 <= x <= 16:
                            return True
                        if 20 <= x <= 29:
                            return False
                    if button in (64, 65) and mouse[4] == b"M":
                        offset, width, height = draw(request, output_fd, offset + (-3 if button == 64 else 3))
                elif seq in (b"[A", b"[B", b"[5~", b"[6~"):
                    delta = {b"[A": -1, b"[B": 1, b"[5~": -(height - 5), b"[6~": height - 5}[seq]
                    offset, width, height = draw(request, output_fd, offset + delta)
                continue
            if pasted:
                continue
            if char in (b"j", b"J"):
                return True
            if char in (b"n", b"N", b"\r", b"\n"):
                return False
        return False
    finally:
        termios.tcflush(input_fd, termios.TCIFLUSH)
        write(output_fd, b"\x1b[?1000l\x1b[?1006l\x1b[?47h\x1b8")
        write(output_fd, b"\x1b[?" + mouse_modes + b"r")
        write(output_fd, b"\x1b[?25;2004r")


def run_terminal(cmd, environment, gate):
    input_fd, output_fd = sys.stdin.fileno(), sys.stdout.fileno()
    interactive = os.isatty(input_fd) and os.isatty(output_fd)
    if not interactive:
        return subprocess.call(cmd, env=environment)
    master, slave = pty.openpty()
    original = termios.tcgetattr(input_fd)
    old_handler = signal.getsignal(signal.SIGWINCH)

    def resize(*_):
        dimensions = fcntl.ioctl(input_fd, termios.TIOCGWINSZ, b"\0" * 8)
        fcntl.ioctl(master, termios.TIOCSWINSZ, dimensions)

    process = None
    try:
        resize()
        signal.signal(signal.SIGWINCH, resize)
        process = subprocess.Popen(cmd, env=environment, stdin=slave, stdout=slave,
                                   stderr=slave, start_new_session=True)
        os.close(slave)
        slave = -1
        tty.setraw(input_fd)
        gate.enabled = True
        while True:
            try:
                request = gate.pending.get_nowait()
            except queue.Empty:
                request = None
            if request is not None:
                if time.monotonic() < request.deadline and not gate.closed.is_set():
                    request.approved = ask(request, input_fd, output_fd)
                request.answered.set()
                resize()
            readable = select.select([input_fd, master], [], [], 0.1)[0]
            if master in readable:
                try:
                    data = os.read(master, 65536)
                except OSError:
                    break
                if not data:
                    break
                write(output_fd, data)
            if input_fd in readable:
                data = os.read(input_fd, 65536)
                if not data:
                    break
                write(master, data)
            if process.poll() is not None and master not in readable:
                break
        return process.wait(timeout=5)
    finally:
        gate.closed.set()
        gate.enabled = False
        termios.tcsetattr(input_fd, termios.TCSADRAIN, original)
        signal.signal(signal.SIGWINCH, old_handler)
        if slave >= 0:
            os.close(slave)
        os.close(master)
        if process is not None and process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()

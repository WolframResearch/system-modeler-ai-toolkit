"""Python client for a System Modeler simulation executable running in server mode.

A model compiled by System Modeler is an executable plus a ``.sim`` settings file. Started with
``-server host:port`` it accepts TCP clients that start, pause and stop the run, change inputs and
tunable parameters while it integrates, and subscribe to variables streamed at every output
interval (System Modeler User Guide, "Communication with Simulation via TCP").

Protocol summary as implemented here:

* Packet: 8-byte little-endian header ``version | type<<8 | subscription<<16 | state<<24 |
  payload_length<<32``, then the payload. Types: 1 HELLO_SCS, 2 HELLO_SDS, 3 CMD, 4 CMD_REPLY,
  5 CMD_ERROR, 6 SDS_OUTPUT_DATA, 8 SDS_INPUT_DATA.
* Control session (SCS): text commands, replies as ``{...}`` arrays.
* Data session (SDS): opened with the SCS session id (braces included, ``{1}``); one packet per
  output interval carries the simulation time followed by the subscribed values as doubles.
* The server waits for ``startSimulation()``; real-time pacing is the ``SyncWithRealTime``
  option of the ``.sim`` file (``prepare_sim_file`` writes it).

Standard library only.
"""

from __future__ import annotations

import glob
import os
import queue
import re
import socket
import struct
import subprocess
import threading
import time
from typing import Iterable, Iterator

HELLO_SCS, HELLO_SDS, CMD, CMD_REPLY, CMD_ERROR, SDS_OUTPUT_DATA, SDS_INPUT_DATA = 1, 2, 3, 4, 5, 6, 8
NOT_STARTED = 1


class WsmError(RuntimeError):
    """A CMD_ERROR reply from the simulation server."""


# -- packets -------------------------------------------------------------------------------------

def _header(ptype: int, payload_len: int, specific: int = 0) -> bytes:
    return struct.pack("<Q", 1 | (ptype << 8) | ((specific & 0xFF) << 16) | (payload_len << 32))


def _send(sock: socket.socket, ptype: int, payload: bytes = b"", specific: int = 0) -> None:
    sock.sendall(_header(ptype, len(payload), specific) + payload)


def _recv_exact(sock: socket.socket, n: int) -> bytes:
    buf = b""
    while len(buf) < n:
        chunk = sock.recv(n - len(buf))
        if not chunk:
            raise ConnectionError("simulation server closed the connection")
        buf += chunk
    return buf


def _recv(sock: socket.socket):
    (v,) = struct.unpack("<Q", _recv_exact(sock, 8))
    return (v >> 8) & 0xFF, (v >> 16) & 0xFF, _recv_exact(sock, v >> 32)


def _hello(sock: socket.socket, hello_type: int, payload: bytes = b"") -> bytes:
    _send(sock, hello_type, payload)
    ptype, _spec, data = _recv(sock)
    if ptype == CMD_ERROR:
        raise WsmError("hello failed: %s" % data.decode(errors="replace"))
    return data


# -- replies -------------------------------------------------------------------------------------

_BOOL_LITERAL = re.compile(r'"(?:[^"\\]|\\.)*"|\b(true|false)\b')


def _numeric_booleans(command: str) -> str:
    """``true``/``false`` outside strings as ``1``/``0``, the form the server reads values in."""
    return _BOOL_LITERAL.sub(lambda m: m.group(0) if m.group(1) is None else
                             "1" if m.group(1) == "true" else "0", command)


_TOKEN = re.compile(r'\s*(?:("(?:[^"\\]|\\.)*")|([-+]?(?:\d+\.\d*|\.\d+|\d+)(?:[eE][-+]?\d+)?)|(true|false)|([{},]))')


def parse_reply(text: str):
    """Parse a ``{...}`` reply. A one-element array of a scalar collapses to the scalar."""
    pos = 0
    stack = [[]]
    while pos < len(text):
        m = _TOKEN.match(text, pos)
        if not m:
            if text[pos:].strip() == "":
                break
            raise ValueError("cannot parse reply: %r" % text)
        pos = m.end()
        s, num, boolean, punct = m.groups()
        if s is not None:
            stack[-1].append(bytes(s[1:-1], "utf-8").decode("unicode_escape"))
        elif num is not None:
            stack[-1].append(float(num) if any(c in num for c in ".eE") else int(num))
        elif boolean is not None:
            stack[-1].append(boolean == "true")
        elif punct == "{":
            stack.append([])
        elif punct == "}":
            inner = stack.pop()
            stack[-1].append(inner)
    result = stack[0]
    if len(result) == 1:
        result = result[0]
        if isinstance(result, list) and len(result) == 1 and not isinstance(result[0], list):
            result = result[0]
    return result


def _fmt(value) -> str:
    if isinstance(value, bool):
        return "1" if value else "0"
    if isinstance(value, str):
        return '"%s"' % value.replace('"', '\\"')
    if isinstance(value, (list, tuple)):
        return "{" + ", ".join(_fmt(v) for v in value) + "}"
    return repr(float(value)) if isinstance(value, float) else str(value)


def _pairs(mapping: dict) -> str:
    items = []
    for k, v in mapping.items():
        items += [_fmt(k), _fmt(v)]
    return "{" + ", ".join(items) + "}"


def _as_list(v) -> list:
    return list(v) if isinstance(v, list) else [v]


# -- sessions ------------------------------------------------------------------------------------

class ScsSession:
    """Simulation Control Session."""

    def __init__(self, host: str, port: int, timeout: float = 10.0):
        self.sock = socket.create_connection((host, port), timeout=timeout)
        self.session_id_raw = _hello(self.sock, HELLO_SCS).decode()
        self.session_id = parse_reply(self.session_id_raw)
        self.lock = threading.Lock()

    def command_raw(self, text: str) -> str:
        """Send one command verbatim and return the reply text (``{...}``)."""
        if text.lstrip().startswith("set"):
            text = _numeric_booleans(text)
        with self.lock:
            _send(self.sock, CMD, text.encode())
            ptype, _spec, payload = _recv(self.sock)
        reply = payload.decode(errors="replace")
        if ptype == CMD_ERROR:
            raise WsmError("%s -> %s" % (text, reply))
        if ptype != CMD_REPLY:
            raise WsmError("unexpected packet type %d for %s" % (ptype, text))
        return reply

    def command(self, text: str):
        return parse_reply(self.command_raw(text))

    def model_name(self) -> str: return self.command("getModelName()")
    def input_names(self) -> list: return _as_list(self.command("getInputVariableNames()"))
    def output_names(self) -> list: return _as_list(self.command("getOutputVariableNames()"))
    def parameter_names(self) -> list: return _as_list(self.command("getParameterNames()"))
    def tunable_parameter_names(self) -> list: return _as_list(self.command("getTunableParameterNames()"))
    def state_names(self) -> list: return _as_list(self.command("getStateVariableNames()"))
    def variable_names(self) -> list: return _as_list(self.command("getVariableNames()"))
    def time(self) -> float: return float(self.command("getTime()"))
    def state(self) -> int: return int(self.command("getSimulationState()"))

    def get_values(self, names: Iterable[str]) -> dict:
        names = list(names)
        values = _as_list(self.command("getVariableValues(%s)" % _fmt(names)))
        return dict(zip(names, (float(v) for v in values)))

    def set_inputs(self, values: dict | None = None, **kw) -> None:
        """Input values used from the next solver step on."""
        self.command("setInputValues(%s)" % _pairs({**(values or {}), **kw}))

    def set_parameters(self, values: dict | None = None, **kw) -> None:
        """Before start: any parameter. After start: tunable parameters only."""
        self.command("setParameterValues(%s)" % _pairs({**(values or {}), **kw}))

    def subscribe(self, names: Iterable[str]) -> int:
        return int(self.command("setSubscription(%s)" % _fmt(list(names))))

    def start(self) -> None: self.command("startSimulation()")
    def stop(self) -> None: self.command("stopSimulation()")
    def suspend(self) -> None: self.command("suspendSimulation()")
    def resume(self) -> None: self.command("continueSimulation()")
    def restart(self) -> None: self.command("restartSimulation()")

    def close(self) -> None:
        try:
            self.sock.close()
        except OSError:
            pass


class SdsSession:
    """Simulation Data Session: a reader thread queues ``(subscription_id, (time, values))``."""

    def __init__(self, host: str, port: int, scs: ScsSession, timeout: float = 10.0, maxsize: int = 100000):
        self.sock = socket.create_connection((host, port), timeout=timeout)
        self.session_id = parse_reply(_hello(self.sock, HELLO_SDS, scs.session_id_raw.encode()).decode())
        self.queue: "queue.Queue[tuple[int, tuple[float, tuple]]]" = queue.Queue(maxsize=maxsize)
        self.latest: dict[int, tuple[float, tuple]] = {}
        self.packets = 0
        self.dropped = 0
        self._stop = threading.Event()
        self.sock.settimeout(0.5)
        self._thread = threading.Thread(target=self._reader, name="wsm-sds-reader", daemon=True)
        self._thread.start()

    def _reader(self) -> None:
        while not self._stop.is_set():
            try:
                ptype, spec, payload = _recv(self.sock)
            except socket.timeout:
                continue
            except (ConnectionError, OSError):
                break
            if ptype != SDS_OUTPUT_DATA:
                continue
            doubles = struct.unpack("<%dd" % (len(payload) // 8), payload)
            item = (doubles[0], doubles[1:])
            self.latest[spec] = item
            self.packets += 1
            try:
                self.queue.put_nowait((spec, item))
            except queue.Full:
                self.dropped += 1

    def send_inputs(self, values: Iterable[float]) -> None:
        """All input variables as doubles, in ``getInputVariableNames()`` order."""
        vals = [float(v) for v in values]
        _send(self.sock, SDS_INPUT_DATA, struct.pack("<%dd" % len(vals), *vals))

    def close(self) -> None:
        self._stop.set()
        try:
            self.sock.close()
        except OSError:
            pass


# -- executable and settings file ------------------------------------------------------------------

def sim_model_name(sim: str) -> str | None:
    """The model name recorded in a ``.sim`` file."""
    with open(sim, encoding="utf-8", errors="replace") as fh:
        m = re.search(r'<model\s+name="([^"]*)"', fh.read())
    return m.group(1) if m else None


def sim_start_time(sim: str) -> float:
    """The start time recorded in a ``.sim`` file (0 if absent)."""
    with open(sim, encoding="utf-8", errors="replace") as fh:
        m = re.search(r'<simulation\b[^>]*\bstart="([^"]*)"', fh.read())
    try:
        return float(m.group(1)) if m else 0.0
    except ValueError:
        return 0.0


def _is_model(sim: str, model: str) -> bool:
    name = sim_model_name(sim)
    return name == model or ("." not in model and name is not None and name.rsplit(".", 1)[-1] == model)


def find_simulation(path: str, model: str | None = None) -> tuple[str, str]:
    """``(exe, sim)`` for an executable path, or the newest executable of ``model`` in a build
    directory (``model`` as recorded in its ``.sim``: the full name, or its last part)."""
    if os.path.isfile(path):
        exe = path
    else:
        pattern = model.rsplit(".", 1)[-1] + "*" if model else "*"
        exes = [e for e in glob.glob(os.path.join(path, pattern))
                if os.path.isfile(e) and not e.endswith(".sim") and os.path.isfile(_strip_exe(e) + ".sim")
                and (model is None or _is_model(_strip_exe(e) + ".sim", model))]
        if not exes:
            raise FileNotFoundError("no simulation executable%s with a .sim file in %s"
                                    % (" for " + model if model else "", path))
        exe = max(exes, key=os.path.getmtime)
    exe = os.path.abspath(exe)
    sim = _strip_exe(exe) + ".sim"
    if not os.path.isfile(sim):
        raise FileNotFoundError("settings file missing: %s" % sim)
    return exe, sim


def _strip_exe(p: str) -> str:
    return p[:-4] if p.lower().endswith(".exe") else p


def free_port(host: str = "127.0.0.1") -> int:
    with socket.socket() as s:
        s.bind((host, 0))
        return s.getsockname()[1]


METHODS = ("dassl", "cvodes", "lsodar", "explicit-euler", "heuns-method", "rk4")


def _get_attr(head: str, name: str) -> str | None:
    m = re.search(r'\b%s="([^"]*)"' % name, head)
    return m.group(1) if m else None


def _set_attr(head: str, name: str, value) -> str:
    if _get_attr(head, name) is not None:
        return re.sub(r'\b%s="[^"]*"' % name, '%s="%s"' % (name, value), head)
    return head + ' %s="%s"' % (name, value)


def prepare_sim_file(src: str, dst: str, end: float | None = None, realtime: bool | None = None,
                     scale: float = 1.0, step: float | None = None, method: str | None = None,
                     interval: float | None = None, no_result_file: bool = True) -> str:
    """Write a copy of a ``.sim`` file set up for an interactive run.

    ``end``: stop time (large for open-ended sessions). ``realtime``/``scale``: pace the solver to
    wall-clock time times ``scale``. ``step``/``method``: solver step size and integrator.
    ``interval``: output interval, which is also the streaming interval; by default the model's own
    interval is kept when ``end`` changes. ``no_result_file``: do not write a result file.
    """
    if method is not None and method.lower() not in METHODS:
        raise ValueError("unknown integration method %r (use one of %s)" % (method, ", ".join(METHODS)))
    text = open(src, encoding="utf-8").read()
    head_end = text.index(">", text.index("<simulation "))
    head = text[:head_end]

    start = float(_get_attr(head, "start") or 0.0)
    old_end = _get_attr(head, "end")
    old_steps = float(_get_attr(head, "outputSteps") or 0)
    old_step_size = float(_get_attr(head, "stepSize") or 0)
    if interval is None and end is not None and old_end:
        if old_steps > 0:
            interval = (float(old_end) - start) / old_steps
        elif old_step_size > 0:
            interval = old_step_size
    if end is not None:
        head = _set_attr(head, "end", repr(float(end)))
    if interval:
        stop = float(end) if end is not None else float(old_end)
        head = _set_attr(head, "outputSteps", str(max(1, round((stop - start) / interval))))
    if step is not None:
        head = _set_attr(head, "stepSize", repr(float(step)))
    if method is not None:
        head = _set_attr(head, "method", method.lower())
    if no_result_file:
        head = re.sub(r'\s*resultFilePath="[^"]*"', "", head)
    text = head + text[head_end:]

    if realtime is not None:
        text = re.sub(r'\s*<Option name="SyncWithRealTime">.*?</Option>', "", text, flags=re.S)
        opt = ('\n    <Option name="SyncWithRealTime">\n      <OptionValue name="enable" value="%s" />\n'
               '      <OptionValue name="scale" value="%s" />\n    </Option>'
               % ("true" if realtime else "false", repr(float(scale))))
        if "<Options>" in text:
            text = text.replace("<Options>", "<Options>" + opt, 1)
        else:
            text = text.replace("</simulation>", "  <Options>%s\n  </Options>\n</simulation>" % opt)
    with open(dst, "w", encoding="utf-8") as fh:
        fh.write(text)
    return dst


class SimulationServer:
    """The executable started with ``-server``; terminates it on ``__exit__``."""

    def __init__(self, exe: str, sim_file: str, host: str = "127.0.0.1", port: int | None = None,
                 log_path: str | None = None, remove_sim_file: bool = False):
        self.exe, self.sim_file, self.host = exe, sim_file, host
        self._remove_sim_file = remove_sim_file
        self.port = port or free_port(host)
        args = [exe, "-f", sim_file, "-server", "%s:%d" % (host, self.port), "-v3", "-ls", "general,settings,com"]
        self._log = open(log_path, "w", encoding="utf-8") if log_path else subprocess.DEVNULL
        self.proc = subprocess.Popen(args, stdout=self._log, stderr=subprocess.STDOUT, cwd=os.path.dirname(exe) or None)
        self._wait_until_listening()

    def _wait_until_listening(self, timeout: float = 15.0) -> None:
        t0 = time.time()
        while time.time() - t0 < timeout:
            if self.proc.poll() is not None:
                raise RuntimeError("simulation executable exited with code %s before listening (see its log)"
                                   % self.proc.returncode)
            try:
                with socket.create_connection((self.host, self.port), timeout=0.5):
                    return
            except OSError:
                time.sleep(0.1)
        raise TimeoutError("simulation server did not open %s:%d" % (self.host, self.port))

    def terminate(self) -> None:
        if self.proc.poll() is None:
            self.proc.terminate()
            try:
                self.proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.proc.kill()
        if self._log is not subprocess.DEVNULL:
            self._log.close()
        if self._remove_sim_file:
            try:
                os.remove(self.sim_file)
            except OSError:
                pass

    def __enter__(self): return self
    def __exit__(self, *exc): self.terminate()


# -- facade --------------------------------------------------------------------------------------

class WsmSimulation:
    """A control session and a data session against a running or launched server."""

    def __init__(self, host: str = "127.0.0.1", port: int = 7000, server: SimulationServer | None = None):
        self.server = server
        self._connect(host, port)
        self.inputs = self.scs.input_names()
        self.outputs = self.scs.output_names()
        self.realtime = bool(self.scs.command("isSynchronizedWithRealTime()"))
        self.subscriptions: dict[int, list] = {}
        self._launch_args: dict | None = None
        self._set_inputs: dict = {}
        self._set_parameters: dict = {}

    def _connect(self, host: str, port: int) -> None:
        self.scs = ScsSession(host, port)
        self.sds = SdsSession(host, port, self.scs)

    @staticmethod
    def _start_server(exe, sim_file, end, realtime, scale, step, method, interval, log_path) -> SimulationServer:
        port = free_port()
        interactive = os.path.join(os.path.dirname(os.path.abspath(exe)), "interactive_%d.sim" % port)
        prepare_sim_file(sim_file, interactive, end=end, realtime=realtime, scale=scale, step=step,
                         method=method, interval=interval)
        return SimulationServer(exe, interactive, port=port, log_path=log_path, remove_sim_file=True)

    @classmethod
    def launch(cls, exe: str, sim_file: str | None = None, end: float = 1e6, realtime: bool = True,
               scale: float = 1.0, step: float | None = None, method: str | None = None,
               interval: float | None = None, log_path: str | None = None) -> "WsmSimulation":
        """Start ``exe`` in server mode with an interactive copy of its ``.sim`` and connect."""
        args = dict(exe=exe, sim_file=sim_file or _strip_exe(exe) + ".sim", end=end, realtime=realtime,
                    scale=scale, step=step, method=method, interval=interval, log_path=log_path)
        server = cls._start_server(**args)
        try:
            sim = cls("127.0.0.1", server.port, server)
        except Exception:
            server.terminate()
            raise
        sim._launch_args = args
        return sim

    @classmethod
    def attach(cls, host: str, port: int) -> "WsmSimulation":
        """Connect to a server somebody else started."""
        return cls(host, port, None)

    @property
    def can_restart(self) -> bool:
        return self._launch_args is not None

    def subscribe(self, names: Iterable[str]) -> int:
        names = list(names)
        sid = self.scs.subscribe(names)
        self.subscriptions[sid] = names
        return sid

    def start(self): self.scs.start()
    def stop(self): self.scs.stop()
    def suspend(self): self.scs.suspend()
    def resume(self): self.scs.resume()
    def time(self) -> float: return self.scs.time()
    def get_values(self, names) -> dict: return self.scs.get_values(names)

    def set_inputs(self, values=None, **kw):
        values = {**(values or {}), **kw}
        self.scs.set_inputs(values)
        self._set_inputs.update(values)

    def set_parameters(self, values=None, **kw):
        values = {**(values or {}), **kw}
        self.scs.set_parameters(values)
        self._set_parameters.update(values)

    def send_inputs(self, values: Iterable[float]) -> None:
        """All inputs as one binary packet, in ``self.inputs`` order (for high-rate feeds)."""
        values = list(values)
        if len(values) != len(self.inputs):
            raise ValueError("send_inputs needs %d values (%s), got %d"
                             % (len(self.inputs), ", ".join(self.inputs), len(values)))
        if not self.realtime:
            raise WsmError("the simulation ignores binary input packets without real-time pacing; "
                           "use set_inputs")
        self.sds.send_inputs(values)
        self._set_inputs.update(zip(self.inputs, values))

    def restart(self) -> None:
        """Run again from the start time, keeping the subscriptions and the inputs and parameters set
        through this instance. The executable's own ``restartSimulation()`` ends the process, so a
        launched simulation is restarted by launching it again; an attached one cannot be restarted."""
        if not self.can_restart:
            raise WsmError("restartSimulation() ends the simulation process; only a simulation "
                           "launched by this client can be restarted")
        self.sds.close()
        self.scs.close()
        self.server.terminate()
        self.server = self._start_server(**self._launch_args)
        self._connect("127.0.0.1", self.server.port)
        old, self.subscriptions = self.subscriptions, {}
        for sid, names in sorted(old.items()):
            if self.subscribe(names) != sid:
                raise WsmError("subscription ids changed on restart")
        if self._set_parameters:
            self.scs.set_parameters(self._set_parameters)
        if self._set_inputs:
            self.scs.set_inputs(self._set_inputs)
        self.start()

    def latest(self, sid: int) -> tuple[float, dict] | None:
        item = self.sds.latest.get(sid)
        return (item[0], dict(zip(self.subscriptions[sid], item[1]))) if item is not None else None

    def stream(self, sid: int, seconds: float | None = None, timeout: float = 5.0) -> Iterator[tuple[float, dict]]:
        """Yield ``(sim_time, {name: value})`` per output interval until ``seconds`` of wall time pass
        (None: no limit) or no packet arrives within ``timeout`` seconds."""
        names = self.subscriptions[sid]
        t_end = None if seconds is None else time.time() + seconds
        while t_end is None or time.time() < t_end:
            try:
                s, (t, vals) = self.sds.queue.get(timeout=timeout)
            except queue.Empty:
                return
            if s == sid:
                yield t, dict(zip(names, vals))

    def close(self) -> None:
        """Close the sessions; stop the simulation and the process only if this instance launched it.
        An attached client leaves the shared server running for the others."""
        if self.server:
            try:
                self.scs.stop()
            except Exception:
                pass
        self.sds.close()
        self.scs.close()
        if self.server:
            self.server.terminate()

    def __enter__(self): return self
    def __exit__(self, *exc): self.close()

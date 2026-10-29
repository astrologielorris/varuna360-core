# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under AGPL-3.0 — see LICENSE file for details.
"""Finding the running app instances' endpoints (SPEC-SET-003 §4.5b). Qt-free.

Each app instance writes ``<user-data>/app_endpoints/<pid>.json``::

    {"v": 1, "pid": 1234, "start_time": 5678, "server": "<full server name>",
     "token": "<32 hex digits>", "edition": "lite" | "pro"}

with mode 0600 (the folder 0700), and removes it at clean exit. ``server`` is
what a client connects to: the Unix socket path on Linux and macOS, the named
pipe path on Windows.

A reader ignores a file whose process is not running, or is another process
that reused the PID (its start time now differs from the recorded one), the
same rule as the live frame files (``core.capabilities.live_state``).
``list_endpoints`` orders the live instances by the activation order the live
frame files already keep: most recently activated window first.

The app hands its OWN endpoint to the task MCP server it launches through the
environment variable ``ENDPOINT_ENV`` (the discovery file's path), so a task
reaches the window that started it and never another (D-18); W6b wires it.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Tuple

from core.capabilities import live_state

PROTOCOL_VERSION = 1
FOLDER_NAME = "app_endpoints"
SUFFIX = ".json"
# The environment variable the app sets when it launches the task MCP server:
# the absolute path of its own discovery file (the token stays in the file).
ENDPOINT_ENV = "VARUNA360_APP_ENDPOINT"
# Beside it (W6b): a fingerprint of that instance's token (not the token), so
# a later instance that reused the PID, and so the discovery file's path, is
# never taken for the window that launched the task (D-18: never redirected).
ENDPOINT_FP_ENV = "VARUNA360_APP_ENDPOINT_FP"


def token_fingerprint(token: str) -> str:
    """The non-secret fingerprint of an endpoint token (``ENDPOINT_FP_ENV``)."""
    import hashlib
    return hashlib.sha256(("varuna360-endpoint\0" + str(token)).encode("utf-8")).hexdigest()[:32]

_TOKEN_RE = re.compile(r"^[0-9a-f]{32}$")


@dataclass(frozen=True)
class Endpoint:
    """One live app instance a client may connect to."""
    pid: int
    start_time: object          # int (Linux ticks, Windows FILETIME), float, or None
    server: str
    token: str
    edition: str
    path: Path                  # the discovery file
    activated_at: Optional[float] = None
    changed_at: float = 0.0


def process_start_time(pid: int):
    """``live_state.process_start_time``, plus macOS without psutil: the
    start time ``ps`` prints (seconds resolution, which is enough to tell a
    reused PID from the process that wrote a file). None when unreadable."""
    value = live_state.process_start_time(pid)
    if value is not None or sys.platform != "darwin":
        return value
    try:
        out = subprocess.run(["ps", "-o", "lstart=", "-p", str(int(pid))],
                             capture_output=True, text=True, timeout=5,
                             env={**os.environ, "LC_ALL": "C"})
    except Exception:
        return None
    text = out.stdout.strip()
    return f"ps:{text}" if out.returncode == 0 and text else None


def _same_process(pid: int, doc: dict) -> bool:
    """True when ``pid`` runs and is the process that wrote ``doc`` (its
    start time unchanged). A record without a start time is trusted on the
    PID alone only where this platform cannot read start times at all."""
    if not live_state._pid_alive(pid):
        return False
    return _start_matches(doc.get("start_time"), process_start_time(pid))


def _start_matches(recorded, current) -> bool:
    """The recorded start time is the running process's (``_same_process``)."""
    if recorded is None:
        return current is None
    return current is not None and current == recorded


def endpoints_dir(folder) -> Path:
    """The discovery folder inside the user-data folder ``folder``."""
    return Path(folder) / FOLDER_NAME


def endpoint_path(folder, pid: Optional[int] = None) -> Path:
    """The discovery file of one instance (this process by default)."""
    return endpoints_dir(folder) / f"{os.getpid() if pid is None else int(pid)}{SUFFIX}"


def _pid_of(name: str) -> Optional[int]:
    if not name.endswith(SUFFIX):
        return None
    core = name[:-len(SUFFIX)]
    return int(core) if core.isdigit() else None


def write_endpoint(folder, server: str, token: str, edition: str) -> Path:
    """Publish this instance's endpoint. The folder is created 0700, the file
    is written 0600 from the start (never readable by others, whatever the
    umask), then moved into place atomically. On Windows the folder gets a
    protected user-only DACL and the file is created with one (W6b fix F6).
    Raises on failure (nothing published)."""
    if not _TOKEN_RE.match(token or ""):
        raise ValueError("token must be 32 lowercase hex digits")
    target_dir = endpoints_dir(folder)
    target_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
    try:
        os.chmod(target_dir, 0o700)
    except OSError:
        pass
    doc = {"v": PROTOCOL_VERSION, "pid": os.getpid(),
           "start_time": process_start_time(os.getpid()),
           "server": str(server), "token": token, "edition": str(edition)}
    final = endpoint_path(folder)
    tmp = target_dir / f"{os.getpid()}.tmp"
    try:
        os.unlink(tmp)                  # a leftover of a crashed process with this PID
    except FileNotFoundError:
        pass
    if sys.platform == "win32":
        # W6b fix F6: os.chmod cannot express "this user only" on Windows, and
        # the folder's inherited ACL is not enough (VARUNA360_USER_DATA_DIR
        # can point at a shared folder). The folder gets a protected,
        # user-only DACL first, and the file is CREATED with one
        # (CreateFileW + SECURITY_ATTRIBUTES): the token is never in a file
        # that was readable by anyone else, not even for an instant, and a
        # process that dies between the steps leaves nothing readable.
        # Failing any step, nothing is published.
        api = _win_security()
        restrict_to_current_user(target_dir, api=api)
        fd = api.create_private_file(tmp)
    else:
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(doc, fh, sort_keys=True)
        if sys.platform != "win32":
            os.chmod(tmp, 0o600)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
    os.replace(tmp, final)
    return final


# ── Windows: an explicit user-only ACL (W6b, spec §4.5b) ────────────────────

GENERIC_ALL = 0x10000000
SET_ACCESS = 2                      # ACCESS_MODE
NO_INHERITANCE = 0
TRUSTEE_IS_SID = 0
TRUSTEE_IS_USER = 1
SE_FILE_OBJECT = 1
DACL_SECURITY_INFORMATION = 0x00000004
PROTECTED_DACL_SECURITY_INFORMATION = 0x80000000
TOKEN_QUERY = 0x0008
TOKEN_USER_CLASS = 1                # TOKEN_INFORMATION_CLASS.TokenUser
SDDL_REVISION_1 = 1
GENERIC_WRITE = 0x40000000
CREATE_NEW = 1
FILE_ATTRIBUTE_NORMAL = 0x80


def private_sddl(sid_text: str) -> str:
    """The security descriptor of a discovery file (W6b fix F6), in SDDL: a
    PROTECTED DACL (``P``: no inherited entries) with one entry, full file
    access (``FA``) for the user's SID."""
    return f"D:P(A;;FA;;;{sid_text})"


def _win_security():
    """The real Windows calls (a seam: tests replace it)."""
    return _WinSecurity()


class _WinSecurity:
    """The few advapi32/kernel32 calls the user-only ACL needs, through
    ctypes (standard library). Separate so the logic in
    ``restrict_to_current_user`` is unit-tested with a fake on any OS."""

    def __init__(self, advapi32=None, kernel32=None):
        import ctypes
        from ctypes import wintypes
        self.ctypes, self.wintypes = ctypes, wintypes
        # the DLLs exist on Windows only; tests pass fakes
        self.advapi32 = advapi32 or ctypes.WinDLL("advapi32", use_last_error=True)
        self.kernel32 = kernel32 or ctypes.WinDLL("kernel32", use_last_error=True)

        class TRUSTEE_W(ctypes.Structure):
            _fields_ = [("pMultipleTrustee", ctypes.c_void_p),
                        ("MultipleTrusteeOperation", ctypes.c_int),
                        ("TrusteeForm", ctypes.c_int),
                        ("TrusteeType", ctypes.c_int),
                        ("ptstrName", ctypes.c_void_p)]

        class EXPLICIT_ACCESS_W(ctypes.Structure):
            _fields_ = [("grfAccessPermissions", wintypes.DWORD),
                        ("grfAccessMode", ctypes.c_int),
                        ("grfInheritance", wintypes.DWORD),
                        ("Trustee", TRUSTEE_W)]
        self.EXPLICIT_ACCESS_W = EXPLICIT_ACCESS_W

        class SECURITY_ATTRIBUTES(ctypes.Structure):
            _fields_ = [("nLength", wintypes.DWORD),
                        ("lpSecurityDescriptor", ctypes.c_void_p),
                        ("bInheritHandle", wintypes.BOOL)]
        self.SECURITY_ATTRIBUTES = SECURITY_ATTRIBUTES
        if advapi32 is None and kernel32 is None:
            # real DLLs: pointer-sized handles and pointers on 64-bit
            k, a = self.kernel32, self.advapi32
            k.GetCurrentProcess.restype = wintypes.HANDLE
            # Without argtypes ctypes passes a Python int as a 32-bit C int:
            # the pseudo-handle -1 read back through HANDLE is 2**64-1 and
            # OpenProcessToken raised "int too long to convert", so the
            # endpoint never started on Windows (VM smoke run 2026-10-22).
            k.CloseHandle.argtypes = [wintypes.HANDLE]
            k.CloseHandle.restype = wintypes.BOOL
            a.OpenProcessToken.argtypes = [wintypes.HANDLE, wintypes.DWORD,
                                           ctypes.POINTER(wintypes.HANDLE)]
            a.OpenProcessToken.restype = wintypes.BOOL
            a.GetTokenInformation.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p,
                                              wintypes.DWORD, ctypes.POINTER(wintypes.DWORD)]
            a.GetTokenInformation.restype = wintypes.BOOL
            a.SetEntriesInAclW.argtypes = [wintypes.ULONG, ctypes.c_void_p, ctypes.c_void_p,
                                           ctypes.POINTER(ctypes.c_void_p)]
            a.SetEntriesInAclW.restype = wintypes.DWORD
            a.SetNamedSecurityInfoW.argtypes = [wintypes.LPWSTR, ctypes.c_int, wintypes.DWORD,
                                                ctypes.c_void_p, ctypes.c_void_p,
                                                ctypes.c_void_p, ctypes.c_void_p]
            a.SetNamedSecurityInfoW.restype = wintypes.DWORD
            k.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
                                      ctypes.c_void_p, wintypes.DWORD, wintypes.DWORD,
                                      wintypes.HANDLE]
            k.CreateFileW.restype = wintypes.HANDLE
            k.LocalFree.argtypes = [ctypes.c_void_p]
            k.LocalFree.restype = ctypes.c_void_p
            a.ConvertSidToStringSidW.argtypes = [ctypes.c_void_p,
                                                 ctypes.POINTER(ctypes.c_void_p)]
            a.ConvertSidToStringSidW.restype = wintypes.BOOL
            a.ConvertStringSecurityDescriptorToSecurityDescriptorW.argtypes = [
                wintypes.LPCWSTR, wintypes.DWORD, ctypes.POINTER(ctypes.c_void_p),
                ctypes.c_void_p]
            a.ConvertStringSecurityDescriptorToSecurityDescriptorW.restype = wintypes.BOOL

    def _fail(self, what):
        err = self.ctypes.get_last_error()
        raise OSError(err, f"{what} failed (Windows error {err})")

    def current_user_sid(self):
        """(sid pointer, buffer keeping it alive) of this process's user."""
        ctypes, wintypes = self.ctypes, self.wintypes
        token = wintypes.HANDLE()
        if not self.advapi32.OpenProcessToken(self.kernel32.GetCurrentProcess(),
                                              TOKEN_QUERY, ctypes.byref(token)):
            self._fail("OpenProcessToken")
        try:
            size = wintypes.DWORD(0)
            self.advapi32.GetTokenInformation(token, TOKEN_USER_CLASS, None, 0,
                                              ctypes.byref(size))
            buf = ctypes.create_string_buffer(size.value)
            if not self.advapi32.GetTokenInformation(token, TOKEN_USER_CLASS, buf, size,
                                                     ctypes.byref(size)):
                self._fail("GetTokenInformation")
        finally:
            self.kernel32.CloseHandle(token)
        # TOKEN_USER starts with SID_AND_ATTRIBUTES, whose first field is the SID pointer
        sid = ctypes.cast(buf, ctypes.POINTER(ctypes.c_void_p))[0]
        return sid, buf

    def user_only_acl(self, sid):
        """A new ACL with exactly one entry: full access for ``sid``."""
        ctypes = self.ctypes
        ea = self.EXPLICIT_ACCESS_W()
        ea.grfAccessPermissions = GENERIC_ALL
        ea.grfAccessMode = SET_ACCESS
        ea.grfInheritance = NO_INHERITANCE
        ea.Trustee.TrusteeForm = TRUSTEE_IS_SID
        ea.Trustee.TrusteeType = TRUSTEE_IS_USER
        ea.Trustee.ptstrName = sid
        acl = ctypes.c_void_p()
        err = self.advapi32.SetEntriesInAclW(1, ctypes.byref(ea), None, ctypes.byref(acl))
        if err:
            raise OSError(err, f"SetEntriesInAclW failed (Windows error {err})")
        return acl

    def set_protected_dacl(self, path, acl):
        """Replace the file's DACL with ``acl`` and block inheritance."""
        err = self.advapi32.SetNamedSecurityInfoW(
            self.ctypes.c_wchar_p(str(path)), SE_FILE_OBJECT,
            DACL_SECURITY_INFORMATION | PROTECTED_DACL_SECURITY_INFORMATION,
            None, None, acl, None)
        if err:
            raise OSError(err, f"SetNamedSecurityInfoW failed (Windows error {err})")

    def free(self, acl):
        self.kernel32.LocalFree(acl)

    def user_sid_text(self) -> str:
        """This process's user SID as text (``S-1-5-...``)."""
        ctypes = self.ctypes
        sid, keep = self.current_user_sid()
        text = ctypes.c_void_p()
        if not self.advapi32.ConvertSidToStringSidW(sid, ctypes.byref(text)):
            self._fail("ConvertSidToStringSidW")
        try:
            return ctypes.wstring_at(text.value)
        finally:
            self.kernel32.LocalFree(text)
            del keep

    def create_private_file(self, path) -> int:
        """Create ``path`` (it must not exist) WITH a protected user-only
        DACL (``private_sddl``), open for writing; return a C file
        descriptor. Nothing is ever written to a file without that DACL."""
        import os
        ctypes = self.ctypes
        sddl = private_sddl(self.user_sid_text())
        descriptor = ctypes.c_void_p()
        if not self.advapi32.ConvertStringSecurityDescriptorToSecurityDescriptorW(
                sddl, SDDL_REVISION_1, ctypes.byref(descriptor), None):
            self._fail("ConvertStringSecurityDescriptorToSecurityDescriptorW")
        try:
            sa = self.SECURITY_ATTRIBUTES()
            sa.nLength = ctypes.sizeof(self.SECURITY_ATTRIBUTES)
            sa.lpSecurityDescriptor = descriptor.value
            sa.bInheritHandle = False
            handle = self.kernel32.CreateFileW(str(path), GENERIC_WRITE, 0, ctypes.byref(sa),
                                               CREATE_NEW, FILE_ATTRIBUTE_NORMAL, None)
            if handle is None or handle == ctypes.c_void_p(-1).value or handle == -1:
                self._fail("CreateFileW")
        finally:
            self.kernel32.LocalFree(descriptor)
        return self.open_handle(handle, os.O_WRONLY | getattr(os, "O_BINARY", 0))

    def open_handle(self, handle, flags) -> int:
        import msvcrt
        return msvcrt.open_osfhandle(handle, flags)


def restrict_to_current_user(path, api=None) -> None:
    """Windows: give ``path`` an explicit, protected DACL with one entry,
    full access for the current user (no inherited entries, no other
    account, not even Administrators or SYSTEM by inheritance). Raises
    OSError when any step fails (the caller then does not publish).
    ``api``: the Windows calls (a fake in tests)."""
    api = api if api is not None else _WinSecurity()
    sid, keep = api.current_user_sid()
    acl = api.user_only_acl(sid)
    try:
        api.set_protected_dacl(path, acl)
    finally:
        api.free(acl)
        del keep


def remove_endpoint(folder, token: Optional[str] = None) -> bool:
    """Remove this instance's discovery file at exit. With ``token``, only
    when the file still holds that token (a newer endpoint of the same
    process is never removed by an older one's cleanup). Never raises."""
    path = endpoint_path(folder)
    try:
        if token is not None:
            doc = _read_doc(path)
            if doc is None or doc.get("token") != token:
                return False
        os.unlink(path)
        return True
    except Exception:
        return False


def _read_doc(path: Path) -> Optional[dict]:
    try:
        with open(path, "r", encoding="utf-8") as fh:
            doc = json.load(fh)
    except (OSError, ValueError):
        return None
    return doc if isinstance(doc, dict) else None


def _valid(doc: dict, pid: int) -> bool:
    return (doc.get("v") == PROTOCOL_VERSION and doc.get("pid") == pid
            and isinstance(doc.get("server"), str) and doc.get("server")
            and isinstance(doc.get("token"), str) and bool(_TOKEN_RE.match(doc["token"]))
            and isinstance(doc.get("edition"), str))


def read_endpoint(path) -> Optional[Endpoint]:
    """The endpoint in discovery file ``path`` when its instance is alive
    (same process: PID running and start time unchanged), else None."""
    path = Path(path)
    pid = _pid_of(path.name)
    if pid is None:
        return None
    doc = _read_doc(path)
    if doc is None or not _valid(doc, pid):
        return None
    if not _same_process(pid, doc):
        return None
    activated, changed = _activation(path.parent.parent, pid)
    return Endpoint(pid=pid, start_time=doc.get("start_time"), server=doc["server"],
                    token=doc["token"], edition=doc["edition"], path=path,
                    activated_at=activated, changed_at=changed)


def _activation(folder: Path, pid: int):
    """(activated_at or None, changed_at) from instance ``pid``'s live frame
    file in the same user-data folder: the activation order the live frame
    already keeps (``live_state``). (None, 0.0) when it has none."""
    doc = _read_doc(Path(folder) / live_state.live_filename(pid))
    if doc is None or doc.get("pid") != pid:
        return None, 0.0
    return (live_state._activated_field(doc),
            live_state._time_field(doc, "changed_at", doc.get("written_at", 0.0)))


def list_endpoints(folder) -> List[Endpoint]:
    """The live endpoints in user-data folder ``folder``, the instance whose
    window the user activated most recently first (then by ``changed_at``,
    then PID). Instances that never recorded an activation come after every
    instance that did (``live_state``'s rule, as an order)."""
    if folder is None:
        return []
    directory = endpoints_dir(folder)
    try:
        names = os.listdir(directory)
    except OSError:
        return []
    found = []
    for name in names:
        if _pid_of(name) is None:
            continue
        ep = read_endpoint(directory / name)
        if ep is not None:
            found.append(ep)
    found.sort(key=lambda e: (e.activated_at is not None, e.activated_at or 0.0,
                              e.changed_at, e.pid), reverse=True)
    return found


def endpoint_from_env(environ=None) -> Optional[Endpoint]:
    """The endpoint of the app that launched this process (``ENDPOINT_ENV``),
    when that instance is still alive; None when the variable is unset or the
    instance is gone (the caller refuses: never redirected to another).
    ``ENDPOINT_FP_ENV`` is required, and the file must hold the token it
    names (a new instance that reused the PID is not the launcher); without
    it: None."""
    return endpoint_and_reason(environ)[0]


def endpoint_and_reason(environ=None) -> Tuple[Optional[Endpoint], str]:
    """``endpoint_from_env`` and, when it gives None, which of its checks
    failed, in words for the error journal (never the token), from the SAME
    pass: a second look could pass where the first failed. A packaged Mac app
    that had run for hours refused every AI setting change ``window_closed``
    while the window answered other clients (VM test 2026-10-27); a restart
    cleared it and the cause could not be reproduced, so the next one says
    which step it was. The reason is "ok" with an endpoint."""
    env = os.environ if environ is None else environ
    raw = (env.get(ENDPOINT_ENV) or "").strip()
    if not raw:
        return None, "no endpoint in the environment"
    fingerprint = (env.get(ENDPOINT_FP_ENV) or "").strip()
    if not fingerprint:
        # D-18 fails closed (W6b fix round 1): without the fingerprint the
        # file at that path cannot be told from a later instance's.
        return None, "no token fingerprint in the environment"
    path = Path(raw)
    pid = _pid_of(path.name)
    if pid is None:
        return None, f"not a discovery file name: {path.name}"
    doc = _read_doc(path)
    if doc is None:
        return None, f"discovery file missing or unreadable: {path}"
    if not _valid(doc, pid):
        return None, f"discovery file not valid: {path}"
    if not live_state._pid_alive(pid):
        return None, f"process {pid} is gone"
    recorded, current = doc.get("start_time"), process_start_time(pid)
    if not _start_matches(recorded, current):
        if current is None:
            return None, f"process {pid} start time unreadable now (recorded {recorded!r})"
        return None, f"process {pid} start time changed: recorded {recorded!r}, now {current!r}"
    if token_fingerprint(doc["token"]) != fingerprint:
        # another instance now: the launcher is gone
        return None, "the discovery file holds another token (the endpoint was restarted)"
    activated, changed = _activation(path.parent.parent, pid)
    return Endpoint(pid=pid, start_time=recorded, server=doc["server"],
                    token=doc["token"], edition=doc["edition"], path=path,
                    activated_at=activated, changed_at=changed), "ok"


def prune_stale(folder) -> int:
    """Remove discovery files left by instances that are gone (a crash): the
    process is dead or its PID is now another process. Never touches a live
    instance's file. The app calls this at start. Returns the count."""
    directory = endpoints_dir(folder)
    try:
        names = os.listdir(directory)
    except OSError:
        return 0
    removed = 0
    for name in names:
        if name.endswith(".tmp") and name[:-4].isdigit():
            # a crashed publisher's staging file (it may hold a token): gone
            # with its process (W6b fix F6; born user-only on every OS)
            tmp_pid = int(name[:-4])
            if tmp_pid != os.getpid() and not live_state._pid_alive(tmp_pid):
                try:
                    os.unlink(directory / name)
                    removed += 1
                except OSError:
                    pass
            continue
        pid = _pid_of(name)
        if pid is None or pid == os.getpid():
            continue
        path = directory / name
        doc = _read_doc(path)
        if doc is not None and _same_process(pid, doc):
            continue
        if doc is None and live_state._pid_alive(pid):
            continue                    # unreadable but maybe being written
        if doc is not None:
            _remove_dead_socket(doc.get("server"))
        try:
            os.unlink(path)
            removed += 1
        except OSError:
            continue
    return removed


def _remove_dead_socket(server) -> None:
    """The Unix socket a crashed instance left behind: removed only when it
    is a socket owned by this user (never a pipe name, never anything else)."""
    if not isinstance(server, str) or sys.platform == "win32" or not os.path.isabs(server):
        return
    try:
        import stat as _stat
        info = os.lstat(server)
        if _stat.S_ISSOCK(info.st_mode) and info.st_uid == os.getuid():
            os.unlink(server)
    except OSError:
        pass

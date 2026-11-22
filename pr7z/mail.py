"""Compress and email: hand the archive to the default email program, as 7-Zip does (Simple MAPI)."""

from __future__ import annotations

import ctypes
import os
import subprocess
from pathlib import Path


def send_files(paths: list[str], subject: str = "") -> bool:
    """Open a new message with the files attached. True if the email program took it."""
    if os.name != "nt":
        return False
    from ctypes import wintypes

    class MapiFileDescW(ctypes.Structure):
        _fields_ = [("ulReserved", wintypes.ULONG), ("flFlags", wintypes.ULONG), ("nPosition", wintypes.ULONG),
                    ("lpszPathName", wintypes.LPWSTR), ("lpszFileName", wintypes.LPWSTR),
                    ("lpFileType", ctypes.c_void_p)]

    class MapiMessageW(ctypes.Structure):
        _fields_ = [("ulReserved", wintypes.ULONG), ("lpszSubject", wintypes.LPWSTR),
                    ("lpszNoteText", wintypes.LPWSTR), ("lpszMessageType", wintypes.LPWSTR),
                    ("lpszDateReceived", wintypes.LPWSTR), ("lpszConversationID", wintypes.LPWSTR),
                    ("flFlags", wintypes.ULONG), ("lpOriginator", ctypes.c_void_p), ("nRecipCount", wintypes.ULONG),
                    ("lpRecips", ctypes.c_void_p), ("nFileCount", wintypes.ULONG),
                    ("lpFiles", ctypes.POINTER(MapiFileDescW))]

    try:
        mapi = ctypes.WinDLL("mapi32.dll")
        send = mapi.MAPISendMailW
    except (OSError, AttributeError):
        return False
    send.argtypes = [ctypes.c_size_t, ctypes.c_size_t, ctypes.POINTER(MapiMessageW), wintypes.ULONG, wintypes.ULONG]
    send.restype = wintypes.ULONG
    files = (MapiFileDescW * len(paths))()
    for i, p in enumerate(paths):
        files[i] = MapiFileDescW(0, 0, 0xFFFFFFFF, str(Path(p)), Path(p).name, None)
    msg = MapiMessageW()
    msg.lpszSubject = subject or ", ".join(Path(p).name for p in paths)
    msg.nFileCount = len(paths)
    msg.lpFiles = files
    MAPI_LOGON_UI, MAPI_DIALOG = 0x1, 0x8
    result = send(0, 0, ctypes.byref(msg), MAPI_LOGON_UI | MAPI_DIALOG, 0)
    return result in (0, 1)  # SUCCESS_SUCCESS, or MAPI_USER_ABORT (the user closed the message: not an error)


def reveal(path: str) -> None:
    """Show the file selected in Explorer (when no email program is set up)."""
    if os.name == "nt":
        subprocess.Popen(["explorer", "/select,", str(Path(path))])

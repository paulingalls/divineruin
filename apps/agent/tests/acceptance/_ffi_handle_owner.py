"""Identify the creator of a LiveKit handle when native disposal fails."""

import sys

from livekit.rtc import _ffi_client


def install_ffi_handle_owner() -> None:
    handle_class = _ffi_client.FfiHandle
    original_init = handle_class.__init__
    original_dispose = handle_class.dispose

    def init(self: _ffi_client.FfiHandle, handle: int) -> None:
        original_init(self, handle)
        frame = sys._getframe(1)
        while frame.f_code.co_filename == _ffi_client.__file__ and frame.f_back is not None:
            frame = frame.f_back
        caller_locals = frame.f_locals
        try:
            code = frame.f_code
            creator = code.co_qualname
            if "self" in caller_locals:
                creator = f"{type(caller_locals['self']).__qualname__}.{code.co_name}"
            vars(self)["_creator"] = f"{creator} ({code.co_filename}:{frame.f_lineno})"
        finally:
            del frame, caller_locals

    def dispose(self: _ffi_client.FfiHandle) -> None:
        try:
            original_dispose(self)
        except AssertionError as exc:
            creator = getattr(self, "_creator", "creator not recorded: handle created before instrumentation")
            raise AssertionError(f"FfiHandle({self.handle}) created by {creator}") from exc

    # Patch the class in place because RTC modules already hold aliases to it.
    handle_class.__init__ = init
    handle_class.dispose = dispose

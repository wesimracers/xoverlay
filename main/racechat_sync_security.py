"""Windows ACL boundary for encrypted RaceChat transfer files."""
import ctypes
from ctypes import wintypes as w
from pathlib import Path


def api(dll, name, args, result=w.BOOL):
    fn = getattr(ctypes.WinDLL(dll, use_last_error=True), name)
    fn.argtypes, fn.restype = args, result
    return fn


def free(pointer):
    api('kernel32', 'LocalFree', [w.LPVOID], w.LPVOID)(pointer)


def sid_text(pointer):
    result = w.LPWSTR()
    if not api('advapi32', 'ConvertSidToStringSidW', [w.LPVOID, ctypes.POINTER(w.LPWSTR)])(pointer, ctypes.byref(result)):
        raise RuntimeError('Could not identify the Windows account.')
    try:
        return result.value
    finally:
        free(result)


def account_sid(name):
    size, domain_size, use = w.DWORD(), w.DWORD(), w.DWORD()
    fn = api('advapi32', 'LookupAccountNameW', [w.LPCWSTR, w.LPCWSTR, w.LPVOID,
             ctypes.POINTER(w.DWORD), w.LPWSTR, ctypes.POINTER(w.DWORD), ctypes.POINTER(w.DWORD)])
    fn(None, name, None, ctypes.byref(size), None, ctypes.byref(domain_size), ctypes.byref(use))
    sid, domain = ctypes.create_string_buffer(size.value), ctypes.create_unicode_buffer(domain_size.value)
    if not fn(None, name, sid, ctypes.byref(size), domain, ctypes.byref(domain_size), ctypes.byref(use)):
        raise RuntimeError('A configured Windows account does not exist.')
    return sid_text(sid)


def current_sid():
    token, size = w.HANDLE(), w.DWORD()
    process = api('kernel32', 'GetCurrentProcess', [], w.HANDLE)()
    if not api('advapi32', 'OpenProcessToken', [w.HANDLE, w.DWORD, ctypes.POINTER(w.HANDLE)])(process, 8, ctypes.byref(token)):
        raise RuntimeError('Could not identify the current Windows account.')
    try:
        fn = api('advapi32', 'GetTokenInformation', [w.HANDLE, w.DWORD, w.LPVOID, w.DWORD, ctypes.POINTER(w.DWORD)])
        fn(token, 1, None, 0, ctypes.byref(size))
        data = ctypes.create_string_buffer(size.value)
        if not fn(token, 1, data, size, ctypes.byref(size)):
            raise RuntimeError('Could not identify the current Windows account.')
        return sid_text(ctypes.cast(data, ctypes.POINTER(w.LPVOID))[0])
    finally:
        api('kernel32', 'CloseHandle', [w.HANDLE])(token)


def expected_aces(sids):
    return {'S-1-5-18': 0x1f01ff, 'S-1-5-32-544': 0x1f01ff,
            **{sid: 0x1301bf for sid in sids}}


def secure_directory(path, sids):
    """Set the protected DACL at creation, before any transfer data is written."""
    path = Path(path)
    if not path.exists():
        sddl = 'D:P' + ''.join(f'(A;OICI;0x{mask:x};;;{sid})' for sid, mask in expected_aces(sids).items())
        descriptor = w.LPVOID()
        if not api('advapi32', 'ConvertStringSecurityDescriptorToSecurityDescriptorW',
                   [w.LPCWSTR, w.DWORD, ctypes.POINTER(w.LPVOID), ctypes.POINTER(w.DWORD)])(sddl, 1, ctypes.byref(descriptor), None):
            raise RuntimeError('Could not prepare restricted RaceChat permissions.')
        class Attributes(ctypes.Structure):
            _fields_ = [('length', w.DWORD), ('descriptor', w.LPVOID), ('inherit', w.BOOL)]
        attributes = Attributes(ctypes.sizeof(Attributes), descriptor, False)
        try:
            if not api('kernel32', 'CreateDirectoryW', [w.LPCWSTR, ctypes.POINTER(Attributes)])(str(path), ctypes.byref(attributes)):
                if ctypes.get_last_error() != 183:
                    raise RuntimeError('Could not create the restricted RaceChat transfer folder.')
        finally:
            free(descriptor)
    verify_permissions(path, sids, directory=True)


def verify_permissions(path, sids, directory=False):
    path = Path(path)
    attrs = api('kernel32', 'GetFileAttributesW', [w.LPCWSTR], w.DWORD)(str(path))
    if attrs == 0xffffffff or attrs & 0x400:
        raise RuntimeError('RaceChat synchronization requires a regular protected path.')
    dacl, descriptor = w.LPVOID(), w.LPVOID()
    fn = api('advapi32', 'GetNamedSecurityInfoW', [w.LPCWSTR, w.DWORD, w.DWORD,
             w.LPVOID, w.LPVOID, ctypes.POINTER(w.LPVOID), w.LPVOID, ctypes.POINTER(w.LPVOID)], w.DWORD)
    if fn(str(path), 1, 4, None, None, ctypes.byref(dacl), None, ctypes.byref(descriptor)):
        raise RuntimeError('Could not verify RaceChat transfer permissions.')
    try:
        control, revision = w.WORD(), w.DWORD()
        if not api('advapi32', 'GetSecurityDescriptorControl', [w.LPVOID, ctypes.POINTER(w.WORD), ctypes.POINTER(w.DWORD)])(descriptor, ctypes.byref(control), ctypes.byref(revision)):
            raise RuntimeError('Could not verify RaceChat transfer permissions.')
        if not dacl.value or (directory and not control.value & 0x1000):
            raise RuntimeError('RaceChat transfer permissions are not restricted.')
        count = ctypes.c_ushort.from_address(dacl.value + 4).value
        actual = {}
        for index in range(count):
            ace = w.LPVOID()
            if not api('advapi32', 'GetAce', [w.LPVOID, w.DWORD, ctypes.POINTER(w.LPVOID)])(dacl, index, ctypes.byref(ace)):
                raise RuntimeError('Could not verify RaceChat transfer permissions.')
            if ctypes.c_ubyte.from_address(ace.value).value != 0:
                raise RuntimeError('Unexpected RaceChat transfer permissions.')
            sid = sid_text(ace.value + 8)
            if sid in actual:
                raise RuntimeError('Unexpected RaceChat transfer permissions.')
            actual[sid] = w.DWORD.from_address(ace.value + 4).value
        if actual != expected_aces(sids):
            raise RuntimeError('RaceChat transfer permissions include unexpected accounts or rights.')
    finally:
        free(descriptor)

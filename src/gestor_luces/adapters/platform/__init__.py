"""Adaptadores de plataforma: puentes finos hacia APIs nativas del sistema operativo.

Los modulos de `windows/` encapsulan las llamadas Win32 (ctypes, DWM, WinForms) para
que el resto de la aplicacion no dependa de `ctypes` ni de detalles del sistema.
"""

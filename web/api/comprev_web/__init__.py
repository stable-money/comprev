"""FastAPI web backend for the comprev compliance engine.

A thin layer over ``comprev`` that lets a non-engineer upload a video, run the
engine off the request thread, watch coarse staged progress, and read the
verdict in the browser. No engine code is changed — everything here reuses the
existing ``comprev`` functions.
"""

"""One module per group of ports. Each exposes `provider`, a dishka Provider instance.

A port is bound in exactly one module. Whoever implements a port replaces its binding in
that module; nothing else needs to change.
"""

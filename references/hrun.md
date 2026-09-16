# hrun fallback

Use `scripts/hdev_call.py` by default to run procedures in `.hdev` files; see the [Python runner](hdevengine_python_runner.md) for explicit inputs, JSON results, tests, and SVG output.

```bash
python scripts/hdev_call.py program.hdev --procedure inspect_part --image Image=images/part.png
```

The current runner calls named local procedures, not the program entry point: passing only a filename or `--procedure main` does not execute `main()`. Keep `main()` for examples and `test_*` for procedure tests; do not introduce global-variable dispatchers.

Use `hrun` only when execution of an existing program's `main()` is required, Python bindings are unavailable, or the user specifically needs `hrun` behavior:

```bash
hrun -b -P program.hdev
```

`-b` uses buffered windows; `-P` rejects invalid/unresolved lines. Avoid interactive operators and `stop()`. Consult the installed `hrun --help` for version-specific options instead of relying on a copied option catalog. For intermediate-state diagnosis, prefer the [debugger](hdev_debug.md).

"""Zero-code activation: `import provekit.auto` turns tracing on with no other calls.

    import provekit.auto      # reads PROVEKIT_API_KEY / PROVEKIT_ENDPOINT and instruments

Put this once at your program's entrypoint (before the libraries you want traced do their
work). Everything instrumented below it is then captured automatically. Fail-open: if the
env vars are unset or OpenTelemetry isn't installed, this is a silent no-op.
"""
from provekit.trace import init

init()

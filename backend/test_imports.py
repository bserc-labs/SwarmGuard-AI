import signal
import sys
def handler(*args): raise Exception("Timeout")
signal.signal(signal.SIGALRM, handler)

pkgs = ['numpy', 'sqlalchemy', 'pydantic', 'starlette', 'anyio', 'fastapi', 'uvicorn', 'scikit-learn']
for p in pkgs:
    try:
        signal.alarm(1)
        __import__(p)
        print(f"{p} OK")
    except Exception as e:
        print(f"{p} FAILED: {e}")

import signal
def handler(signum, frame):
    raise TimeoutError("Import timed out!")
signal.signal(signal.SIGALRM, handler)
signal.alarm(2)
import fastapi
print('FastAPI imported successfully!')

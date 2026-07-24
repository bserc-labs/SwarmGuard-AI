import signal
def handler(signum, frame):
    raise TimeoutError("Import timed out!")
signal.signal(signal.SIGALRM, handler)
signal.alarm(5)

try:
    import main
    print('Main imported')
except Exception as e:
    print(f"Failed: {e}")

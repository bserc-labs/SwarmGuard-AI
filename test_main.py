import signal
import sys
def handler(*args): raise Exception("Timeout")
signal.signal(signal.SIGALRM, handler)
signal.alarm(5)

print("Importing main...")
import main
print("Main imported!")

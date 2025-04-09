import inspect
import os
import pickle
import requests

initial_dir = os.path.dirname(os.path.abspath(inspect.getsourcefile(lambda:0)))

session = None
session_file = os.path.join(initial_dir, 'session.ser')

def load_session():
    global session, session_file

    if os.path.isfile(session_file):
        try:
            with open(session_file, 'rb') as f:
                session = pickle.load(f)
        except:
            pass
    else:
        session = requests.session()

def save_session():
    global session, session_file

    with open(session_file, 'wb') as f:
        pickle.dump(session, f)

load_session()
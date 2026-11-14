import tornado.web

from state import _progress_lock, progress_state


class ProgressHandler(tornado.web.RequestHandler):
    def get(self):
        with _progress_lock:
            self.write(progress_state)

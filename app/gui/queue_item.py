import os

STATUS_WAITING = 'waiting'
STATUS_RUNNING = 'running'
STATUS_DONE = 'done'
STATUS_ERROR = 'error'
STATUS_CANCELED = 'canceled'

SUPPORTED_EXTENSIONS = ('epub', 'txt', 'srt')


class QueueItem:
    def __init__(self, path):
        self.path = path
        self.title = os.path.splitext(os.path.basename(path))[0]
        self.input_format = os.path.splitext(path)[1].lstrip('.').lower()
        self.source_lang = 'Auto detect'
        self.target_lang = 'Turkish'
        self.status = STATUS_WAITING
        self.output_path = None
        self.error = None

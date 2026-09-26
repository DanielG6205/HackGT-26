"""Nonblocking robot prompt playback for the camera demo."""
from concurrent.futures import ThreadPoolExecutor


class PromptSpeaker:
    def __init__(self, speech=None, emit=print):
        self.speech = speech
        self.emit = emit
        self._worker = ThreadPoolExecutor(max_workers=1, thread_name_prefix='robot-prompt')
        self._future = None
        self._new_prompt = False

    def __call__(self, message):
        self.emit(message)
        if self.speech is not None and message.startswith('[ROBOT] '):
            if self.busy:
                raise RuntimeError('Previous robot prompt is still playing')
            self._future = self._worker.submit(self.speech.speak, message[len('[ROBOT] '):])
            self._new_prompt = True

    @property
    def busy(self):
        if self._new_prompt:
            self._new_prompt = False
            return True  # Ensure even fast playback pauses/resets the trial clock.
        if self._future is None:
            return False
        if not self._future.done():
            return True
        future, self._future = self._future, None
        # Fail visibly rather than count a trial whose prompt was never heard.
        future.result()
        return False

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self._worker.shutdown(wait=True, cancel_futures=True)

"""All system I/O runs serially on one Qt worker thread; never touch widgets here."""

import logging

from PySide6.QtCore import QObject, Signal, Slot

from ..backends.base import DisplayError


class StudioWorker(QObject):
    completed = Signal(str, object, str)

    def __init__(self, factory):
        super().__init__()
        self.factory, self.studio = factory, None

    @Slot(str, object)
    def perform(self, action, args):
        result, error = None, ""
        try:
            if action == "scan":
                if self.studio is None:
                    self.studio = self.factory()  # initial scan is also off the UI thread
                else:
                    self.studio.refresh()
                result = self.studio.state()
            elif action == "apply":
                result = self.studio.apply(args["ids"], args["profile"], args["brightness"])
            elif action == "undo":
                result = self.studio.undo(args["id"])
            else:
                raise ValueError(action)
        except Exception as exc:
            if isinstance(exc, (OSError, DisplayError)):
                error = str(exc)
            else:
                logging.getLogger(__name__).exception("Studio operation failed")
                error = "Не удалось завершить операцию. Обновите список устройств."
            if self.studio is not None:
                # A failed write may leave a recoverable journal. Do not hide Undo.
                try:
                    result = self.studio.state()
                except Exception:
                    logging.getLogger(__name__).exception("Unable to read studio state")
        self.completed.emit(action, result, error)

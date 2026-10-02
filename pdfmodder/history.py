"""Historial de instantáneas completas e inmutables en disco, nunca replays."""
from pathlib import Path
import tempfile
import uuid


class History:
    def __init__(self, original:bytes, directory=None, max_states=40, max_bytes=512*1024*1024):
        self.folder=tempfile.TemporaryDirectory(prefix='pdfmodder-history-',dir=directory)
        self.root=Path(self.folder.name)
        self.max_states=max_states
        self.max_bytes=max_bytes
        self.states=[]
        self.reports=[]
        self.base_reports=[]
        self.index=-1
        self.dropped=0
        self.push(original,None)

    @property
    def current(self):
        return self.states[self.index].read_bytes()

    def push(self,data,report):
        # Materialize first: disk-full/export errors must retain redo as well.
        new_path=self.root/(uuid.uuid4().hex+'.pdf')
        try:
            new_path.write_bytes(data)
        except OSError:
            new_path.unlink(missing_ok=True)
            raise
        for path in self.states[self.index+1:]:
            path.unlink()
        self.states=self.states[:self.index+1]
        self.reports=self.reports[:self.index+1]
        self.states.append(new_path)
        self.reports.append(report)
        self.index=len(self.states)-1
        while len(self.states)>2 and (len(self.states)>self.max_states or
              sum(p.stat().st_size for p in self.states)>self.max_bytes):
            self.states.pop(0).unlink()
            previous=self.reports.pop(0)
            if previous:
                self.base_reports.append(previous)
            self.index-=1
            self.dropped+=1

    def undo(self):
        if self.index>0:
            self.index-=1
        return self.current

    def redo(self):
        if self.index+1<len(self.states):
            self.index+=1
        return self.current

    def close(self):
        self.folder.cleanup()

try:
    import LCClib
except ModuleNotFoundError:
    LCClib = None


class LCCService:
    def __init__(self):
        if LCClib is None:
            self.lcc = None
            self.retardances = []
            self.enabled = False
        else:
            self.lcc = getattr(LCClib, "LCC", None)
            self.retardances = getattr(LCClib, "retardances", [])
            self.enabled = self.lcc is not None

    def set_retardance(self, value):
        if not self.enabled:
            return
        self.lcc.write("RE={}".format(value))

    def drain(self):
        if not self.enabled:
            return None
        return self.lcc.read()


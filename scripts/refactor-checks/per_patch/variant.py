"""A per-patch report variant: `full` (the reference), `pure` (no patches), or the patches
left out of the series, `NNNN` or several joined by `+` (`0005+0006+0007`)."""
import re
from dataclasses import dataclass

_LEFT_OUT = re.compile(r"[0-9]{4}(?:\+[0-9]{4})*")


@dataclass(frozen=True)
class Variant:
    name: str
    excluded: tuple = ()

    @classmethod
    def parse(cls, text):
        if text in ("full", "pure"):
            return cls(text)
        if not _LEFT_OUT.fullmatch(text):
            raise ValueError(f"not a variant: {text!r} (full, pure, NNNN or NNNN+NNNN...)")
        return cls(text, tuple(text.split("+")))

    def build_args(self):
        """The selection, as `larch-patches/build.py` options."""
        if self.name == "pure":
            return ["--pure-upstream"]
        return [arg for number in self.excluded for arg in ("--exclude", number)]

    def title(self, series_names):
        """The report heading; `series_names` are the patch file names, `NNNN-*.patch`."""
        if self.name == "full":
            return "Full patch set (the reference)"
        if self.name == "pure":
            return "Pure upstream (no patches)"
        files = [name for name in series_names if name[:4] in self.excluded]
        return f"Without {' + '.join(self.excluded)} ({', '.join(f'`{f}`' for f in files)})"

    def sort_key(self, series_names):
        """`full`, then by the first patch left out (fewer first), then `pure`."""
        order = {name[:4]: i for i, name in enumerate(series_names, 1)}
        if self.name == "full":
            return (0, 0, "")
        if self.name == "pure":
            return (len(order) + 1, 0, "")
        return (order.get(self.excluded[0], len(order) + 1), len(self.excluded), self.name)

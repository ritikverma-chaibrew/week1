"""Tiny in-memory stand-in for the async MongoDB API surface the app uses."""

import copy


class FakeCursor:
    def __init__(self, docs):
        self._docs = docs

    def sort(self, key, direction=1):
        self._docs = sorted(self._docs, key=lambda d: d[key], reverse=direction < 0)
        return self

    def limit(self, n):
        self._docs = self._docs[:n]
        return self

    async def to_list(self, length=None):
        return [copy.deepcopy(d) for d in self._docs[:length]]


class FakeCollection:
    def __init__(self):
        self.docs: list[dict] = []

    def _match(self, flt):
        return [d for d in self.docs if all(d.get(k) == v for k, v in flt.items())]

    async def insert_one(self, doc):
        self.docs.append(copy.deepcopy(doc))

    async def find_one(self, flt):
        found = self._match(flt)
        return copy.deepcopy(found[0]) if found else None

    def find(self, flt=None):
        return FakeCursor(self._match(flt or {}))

    async def update_one(self, flt, update, upsert=False):
        found = self._match(flt)
        if found:
            found[0].update(copy.deepcopy(update.get("$set", {})))
        elif upsert:
            doc = {**flt, **update.get("$setOnInsert", {}), **update.get("$set", {})}
            self.docs.append(copy.deepcopy(doc))

    async def delete_many(self, flt):
        self.docs = [d for d in self.docs if d not in self._match(flt)]

    async def create_index(self, *args, **kwargs):
        return None


class FakeDB:
    def __init__(self):
        self._collections: dict[str, FakeCollection] = {}

    def __getattr__(self, name):
        return self._collections.setdefault(name, FakeCollection())

    __getitem__ = __getattr__

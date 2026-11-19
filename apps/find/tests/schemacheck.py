"""A small JSON Schema checker for the contract tests (no new dependency: CI installs only the hash-pinned lock).

It understands the subset contract/*.schema.json uses: type (one or a list), properties, required,
additionalProperties (bool or schema), items, enum, const, anyOf, oneOf, minimum, maximum, minLength, maxLength,
pattern, and $ref to "#/$defs/name" in the same file or "<file>.schema.json#/$defs/name" next to it.
Anything else in a schema is an error, so the schema can't silently say more than is checked.
"""
import json
import os
import re

KNOWN = {"$schema", "$id", "$defs", "$comment", "title", "description", "type", "properties", "required",
         "additionalProperties", "items", "enum", "const", "anyOf", "oneOf", "minimum", "maximum", "minLength",
         "maxLength", "pattern", "$ref", "examples", "default"}
TYPES = {"object": dict, "array": list, "string": str, "boolean": bool, "null": type(None)}


def load(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


class Checker:
    def __init__(self, folder):
        self.folder = folder
        self._docs = {}

    def doc(self, name):
        if name not in self._docs:
            self._docs[name] = load(os.path.join(self.folder, name))
        return self._docs[name]

    def resolve(self, ref, base):
        file, _, frag = ref.partition("#")
        name = file or base
        node = self.doc(name)
        for part in [p for p in frag.split("/") if p]:
            node = node[part]
        return node, name

    def unknown_keywords(self, schema, where="$"):
        """Keywords anywhere in `schema` that this checker doesn't check."""
        if not isinstance(schema, dict):
            return []
        out = [f"{where}.{k}" for k in schema if k not in KNOWN]
        for k, v in schema.items():
            if k in ("properties", "$defs"):
                for name, sub in v.items():
                    out += self.unknown_keywords(sub, f"{where}.{k}.{name}")
            elif k in ("items", "additionalProperties"):
                out += self.unknown_keywords(v, f"{where}.{k}")
            elif k in ("anyOf", "oneOf"):
                for i, sub in enumerate(v):
                    out += self.unknown_keywords(sub, f"{where}.{k}[{i}]")
        return out

    def errors(self, value, schema, base, where="$"):
        out = []
        self._check(value, schema, base, where, out)
        return out

    def _type_ok(self, value, t):
        if t == "integer":
            return isinstance(value, int) and not isinstance(value, bool)
        if t == "number":
            return isinstance(value, (int, float)) and not isinstance(value, bool)
        return isinstance(value, TYPES[t]) and not (t != "boolean" and isinstance(value, bool))

    def _check(self, v, s, base, where, out):
        if s is True:
            return
        unknown = set(s) - KNOWN
        if unknown:
            out.append(f"{where}: schema uses unsupported keywords {sorted(unknown)}")
            return
        if "$ref" in s:
            target, name = self.resolve(s["$ref"], base)
            self._check(v, target, name, where, out)
            return
        if "type" in s:
            types = s["type"] if isinstance(s["type"], list) else [s["type"]]
            if not any(self._type_ok(v, t) for t in types):
                out.append(f"{where}: {type(v).__name__} is not {'/'.join(types)}")
                return
        if "const" in s and v != s["const"]:
            out.append(f"{where}: {v!r} is not {s['const']!r}")
        if "enum" in s and v not in s["enum"]:
            out.append(f"{where}: {v!r} is not one of {s['enum']}")
        for key in ("anyOf", "oneOf"):
            if key in s:
                ok = sum(1 for sub in s[key] if not self.errors(v, sub, base, where))
                if ok == 0 or (key == "oneOf" and ok > 1):
                    out.append(f"{where}: matches {ok} of the {key} choices")
        if isinstance(v, (int, float)) and not isinstance(v, bool):
            if "minimum" in s and v < s["minimum"]:
                out.append(f"{where}: {v} < {s['minimum']}")
            if "maximum" in s and v > s["maximum"]:
                out.append(f"{where}: {v} > {s['maximum']}")
        if isinstance(v, str):
            if "minLength" in s and len(v) < s["minLength"]:
                out.append(f"{where}: shorter than {s['minLength']}")
            if "maxLength" in s and len(v) > s["maxLength"]:
                out.append(f"{where}: longer than {s['maxLength']}")
            if "pattern" in s and not re.search(s["pattern"], v):
                out.append(f"{where}: {v!r} doesn't match {s['pattern']}")
        if isinstance(v, dict):
            props = s.get("properties", {})
            for k in s.get("required", []):
                if k not in v:
                    out.append(f"{where}: '{k}' is missing")
            extra = s.get("additionalProperties", True)
            for k, item in v.items():
                if k in props:
                    self._check(item, props[k], base, f"{where}.{k}", out)
                elif extra is False:
                    out.append(f"{where}: '{k}' isn't in the schema")
                elif isinstance(extra, dict):
                    self._check(item, extra, base, f"{where}.{k}", out)
        if isinstance(v, list) and "items" in s:
            for i, item in enumerate(v):
                self._check(item, s["items"], base, f"{where}[{i}]", out)

"""Reads and writes the config file (/etc/hazbat/hazbat.ini) without losing
its comments.

The whole file is loaded into a ConfigFile: the lines before the first section,
then each section with its lines in order. Comment lines, blank lines and the
order of everything are kept, so a file that has been edited by hand
comes back out as it went in, apart from the settings that were set.

The format is deliberately small, and anything outside it is an error that
names the line:
    # a comment      a line whose first character (after any spaces) is # or ;
    ; a comment
    [section]        a section header, on a line of its own
    name = value     a setting: the name is everything before the first =,
                     the value everything after it
    (blank lines)
Values are text. There are no quotes, no comments after a value (a # inside a
value is part of the value), no continuation lines, and no repeated section or
setting names. Settings must be inside a section.
"""

import os
import shutil


class ConfigError(Exception):
    """The file, or a name or value to be stored, is outside the format above."""


class Section:
    """One [section]: its header line as it was written, and its lines in order."""

    def __init__(self, name, header):
        self.name = name
        self.header = header
        self.lines = []


class Line:
    """One line of a section, or of the lines before the first section.
    kind is "comment", "blank" or "setting". A setting also has a name and a value."""

    def __init__(self, text, kind, name=None, value=None):
        self.text = text
        self.kind = kind
        self.name = name
        self.value = value


class ConfigFile:
    def __init__(self):
        self.preamble = []
        self.sections = []

    @classmethod
    def load(cls, path):
        """The file's contents, or an empty ConfigFile if there is no such file."""
        if not os.path.exists(path):
            return cls()
        with open(path, encoding="utf-8") as f:
            return cls.parse(f.read(), path)

    @classmethod
    def parse(cls, text, label):
        """Builds a ConfigFile from text. label names the file in error messages."""
        config = cls()
        current = None
        for number, raw in enumerate(text.splitlines(), start=1):
            stripped = raw.strip()
            if stripped == "" or stripped[0] in "#;":
                kind = "blank"
                if stripped != "":
                    kind = "comment"
                if current is None:
                    config.preamble.append(Line(raw, kind))
                else:
                    current.lines.append(Line(raw, kind))
            elif stripped[0] == "[":
                if not stripped.endswith("]"):
                    raise ConfigError(
                        f"{label}: line {number}: section header has no closing "
                        f"]: {raw!r}"
                    )
                name = stripped[1:-1].strip()
                check_section_name(name)
                if config.find(name) is not None:
                    raise ConfigError(
                        f"{label}: line {number}: section [{name}] appears twice"
                    )
                current = Section(name, raw)
                config.sections.append(current)
            else:
                if "=" not in stripped:
                    raise ConfigError(
                        f"{label}: line {number}: not a comment, section or "
                        f"name = value: {raw!r}"
                    )
                if current is None:
                    raise ConfigError(
                        f"{label}: line {number}: setting is not inside "
                        f"a section: {raw!r}"
                    )
                name, value = stripped.split("=", 1)
                name = name.strip()
                value = value.strip()
                check_name(name)
                for line in current.lines:
                    if line.name == name:
                        raise ConfigError(
                            f"{label}: line {number}: [{current.name}] {name} "
                            "appears twice"
                        )
                current.lines.append(Line(raw, "setting", name, value))
        return config

    def find(self, section):
        """The Section with this name, or None."""
        for candidate in self.sections:
            if candidate.name == section:
                return candidate
        return None

    def get(self, section, name):
        """The value of a setting, or None if the section or the setting is not
        there.
        """
        found = self.find(section)
        if found is None:
            return None
        for line in found.lines:
            if line.name == name:
                return line.value
        return None

    def as_dict(self):
        """The settings as {section: {name: value}}."""
        data = {}
        for section in self.sections:
            values = {}
            for line in section.lines:
                if line.kind == "setting":
                    values[line.name] = line.value
            data[section.name] = values
        return data

    def set(self, section, name, value):
        """Sets a setting. An existing one keeps its place and the comments
        around it. A new one goes after the section's last setting (or straight
        after its header), and a new section goes at the end of the file.
        """
        value = str(value)
        check_section_name(section)
        check_name(name)
        check_value(value)
        found = self.find(section)
        if found is None:
            before = self.preamble
            if self.sections:
                before = self.sections[-1].lines
            if before and before[-1].text.strip() != "":
                before.append(Line("", "blank"))
            found = Section(section, f"[{section}]")
            self.sections.append(found)
        text = f"{name} = {value}"
        for line in found.lines:
            if line.name == name:
                line.text = text
                line.value = value
                return
        position = 0
        for index, line in enumerate(found.lines):
            if line.kind == "setting":
                position = index + 1
        found.lines.insert(position, Line(text, "setting", name, value))

    def text(self):
        """The file as it should be written."""
        lines = []
        for line in self.preamble:
            lines.append(line.text)
        for section in self.sections:
            lines.append(section.header)
            for line in section.lines:
                lines.append(line.text)
        if not lines:
            return ""
        return "\n".join(lines) + "\n"

    def save(self, path, mode, group):
        """
        Writes the file through a temporary file, so a failure never leaves a
        half-written one.
        mode is the permissions of the new file and group is the group that owns it.
        """
        os.makedirs(os.path.dirname(path), exist_ok=True)
        temporary = path + ".tmp"
        fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, mode)
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(self.text())
        os.chmod(temporary, mode)  # the mode given to os.open is cut down by the umask
        shutil.chown(temporary, group=group)
        os.replace(temporary, path)


def check_section_name(name):
    """Section names must be non-empty and have no brackets or line breaks."""
    if name == "" or any(character in name for character in "[]\r\n"):
        raise ConfigError(f"Not a usable section name: {name!r}")


def check_name(name):
    """
    Setting names must be non-empty, have no = or line breaks,
    and not look like a comment or a section.
    """
    if (
        name == ""
        or name[0] in "#;["
        or any(character in name for character in "=\r\n")
    ):
        raise ConfigError(f"Not a usable setting name: {name!r}")


def check_value(value):
    """Values must be on one line."""
    if "\r" in value or "\n" in value:
        raise ConfigError(f"A value must be on one line: {value!r}")


def truthy(value):
    """
    Returns True for the text true or 1 (in any case).
    Anything else, including None, is false.
    """
    return value is not None and value.strip().lower() in ("true", "1")

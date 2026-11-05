from utils.config import ConfigFile


class VariableRegistry:
    def __init__(self, path="/etc/hazbat/hazbat.ini"):
        self.path = path
        self.sections = ConfigFile.load(path).as_dict()

    def __getitem__(self, section):
        """The section's names and values, as a dict. Raises KeyError if there is no such section."""
        return self.sections[section]

    def get(self, section, name):
        """The value of a name in a section, or None if it is not there."""
        return self.sections.get(section, {}).get(name)

    def require(self, section, *names):
        """Raises one RuntimeError naming every one of these that is missing from the section."""
        present = self.sections.get(section, {})
        missing = []
        for name in names:
            if name not in present:
                missing.append(name)
        if missing:
            raise RuntimeError(f"Not set in section [{section}] of {self.path}: {', '.join(missing)}")


# The one shared registry, read when this module is first imported
settings = VariableRegistry()

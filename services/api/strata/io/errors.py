"""Input parsing errors. Messages are safe to show to users and never include genotype data."""


class InputFormatError(ValueError):
    """The uploaded content could not be parsed in any supported format."""

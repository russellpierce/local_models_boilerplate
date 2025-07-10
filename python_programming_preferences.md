## Python Programming Preferences

* For scripts that run stand alone
  * use PEP 723 syntax compatible with uv run
  * Establish a shabang consistent with uv run
* Do not use f-strings unless you're actually doing string interpolation.
* Never throw a bare exception.  Always raise a specific exception.
* Never use bare except.  Always specify the exception type."
* When catching an exception with the intent to print info about it, always print (or log) the source exception type and message.  Generally prefer to re-raise the exception unless the cause can be known and it needs a better message e.g. f"Failed to load audio file {audio_path}, AudioSegment.from_file said: {type(e).__name__}: {e}" if good because it included information about the caller than produced the exception and what that caller indicated about the exception.
* Use type hints where possible.
* Adhere to the ruff formatting syntax where possible.


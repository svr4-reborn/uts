try:
	from .floppyfslib import *
	from .floppyfslib import main
except ImportError:
	from floppyfslib import *
	from floppyfslib import main

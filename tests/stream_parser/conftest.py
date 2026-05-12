"""Enable Cython JIT compilation for stream-parser performance modules."""

import pyximport

pyximport.install(language_level=3, build_in_temp=True, inplace=True)
